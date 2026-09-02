"""Pipeline ingest tuần tự: quét, nạp từng tài liệu, re-ingest ghi đè sạch, xóa (story 2.3).

Đây là **nơi duy nhất** gọi `ainsert` của engine (test import-lint canh), và
cũng là dòng duy nhất của danh sách trắng được import `core.system_context`
(AD-3). Mọi đường nạp tri thức của dự án đi qua đây, nên ba luật của Epic 2
sống ở một chỗ thay vì ở từng script:

1. **Tuần tự, mỗi tài liệu một bộ ba riêng** - một
   `use_context(system_context(space, policy_version))`, một `ingest_label`,
   một `dot_ingest`, và `doi_chieu_dot` ngay sau `ainsert` (AD-4: không batch
   trộn scope). Lệch đối chiếu là dừng cả lần chạy, không tự sửa, không sang
   tài liệu kế.
2. **Re-ingest là ghi đè sạch.** `ainsert` của upstream chỉ biết thêm
   (`source_id` được join, `description` được gộp), nên nạp lại một tài liệu
   mà không xóa phần cũ là cộng dồn fact cũ. Pipeline giữ một sổ tài liệu bền
   vững theo space (`so_tai_lieu_{space}.json`) ghi id đã tạo và phần đóng góp
   vào entity chung; re-ingest = xóa sạch phần cũ theo sổ, dựng lại hyperedge
   và entity chung từ phần của các tài liệu còn lại, hợp nhất lại khóa, rồi
   nạp như mới. Tài liệu không đổi (cùng sha256, cùng nhãn) thì không chạm kho
   trừ khi ép (`ep_ghi_de`).
3. **Một tiến trình ingest mỗi space**, ép bằng `fcntl.flock` không chặn trên
   `working_dir/ingest_{space}.lock`. Đây là quyết định cho cả hai khoản
   "hai tiến trình" của ledger (kho KV ghi đè file, read-merge-write không
   nguyên tử): không CAS, không khóa từng kho.

Space `real` (AD-12): trước khi chạm kho, cả provider LLM lẫn embedding phải
là cục bộ và `san_sang()`; không thì `LOCAL_LLM_UNAVAILABLE`, không fallback.

Sự kiện audit ở tầng **mutation** (`ghi_bien_doi`): nạp và xóa tri thức là
thay đổi kho, và mất dấu một lần xóa là mất dấu một thay đổi quyền. Port hỏng
thì tài liệu đó ghi lỗi, sổ không cập nhật, lần chạy dừng. Re-ingest phát
`delete_doc` ngay sau khi gỡ xong, trước `ainsert`, để một `ainsert` hỏng sau
đó vẫn để lại dấu của lần xóa.
"""

import errno
import fcntl
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from hypergraphrag.operate import chunking_by_token_size
from hypergraphrag.prompt import GRAPH_FIELD_SEP
from hypergraphrag.utils import compute_mdhash_id

from adapters.doi_chieu import (
    SoDot,
    doi_chieu_dot,
    dot_ingest,
    kho_cua_engine,
    ten_kho_kv,
    ten_kho_vector,
)
from adapters.ingest_labels import ingest_label
from adapters.kv import DUOI_TAM
from adapters.llm_wrapper import ProviderNotAllowedForSpace, nha_cung_cap_cua
from adapters.sensitivity_loader import bang_hang_cho
from core.audit import (
    EVENT_DELETE_DOC,
    EVENT_DELETE_SPACE,
    EVENT_INGEST_DOC,
    TIER_MUTATION,
    AuditPort,
    SuKienAudit,
    ghi_bien_doi,
    thoi_diem_utc,
)
from core.ids import la_space_real, validate_space
from core.ingest_scan import (
    MA_TRUNG_NOI_DUNG,
    KetQuaQuet,
    TaiLieuNguon,
    TuChoi,
    quet_cac_file,
    quet_thu_muc,
)
from core.keys import CHUA_GHI, KHONG_KHOA, SensitivityRankUnknown, filter_key, hop_nhat_khoa
from core.permission import use_context
from core.system_context import system_context

SEP = GRAPH_FIELD_SEP

# Trạng thái của một tài liệu trong kết quả một lần chạy.
TRANG_THAI_DA_NAP: str = "da_nap"
TRANG_THAI_KHONG_DOI: str = "khong_doi"
TRANG_THAI_DA_XOA: str = "da_xoa"
TRANG_THAI_LOI: str = "loi"
TRANG_THAI_TU_CHOI: str = "tu_choi"

# Mã lỗi của tài liệu không trích được hyperedge nào: pipeline dọn mọi thứ
# `ainsert` đã ghi trong đợt (upstream ghi chunk, và có thể cả entity, trước
# khi biết là không có hyperedge) và đi tiếp. Cảnh báo "0 fact" đúng nghĩa
# (đếm, báo cáo) thuộc story 2.4.
MA_KHONG_CO_FACT: str = "KHONG_CO_FACT"
# `ainsert` return sớm vì doc/chunk đã có trong kho mà sổ tài liệu không biết
# (dữ liệu nạp trước khi có sổ): đợt rỗng, không có gì để dọn, không nạp được.
MA_DA_CO_TRONG_KHO: str = "DA_CO_TRONG_KHO"

# Phiên bản lược đồ của sổ tài liệu trên đĩa.
VERSION_SO_TAI_LIEU: int = 1


class IngestAlreadyRunning(RuntimeError):
    """Một tiến trình ingest khác đang giữ khóa file của space này."""

    code = "INGEST_ALREADY_RUNNING"


class LocalLLMUnavailable(RuntimeError):
    """Space `real`: provider cục bộ chưa sẵn sàng; không fallback API ngoài (AD-12)."""

    code = "LOCAL_LLM_UNAVAILABLE"


class DocNotInLedger(LookupError):
    """Xóa một tài liệu mà sổ tài liệu của space không có."""

    code = "DOC_NOT_IN_LEDGER"


class LedgerCorrupt(RuntimeError):
    """Sổ tài liệu trên đĩa không đọc được hoặc mang phiên bản lược đồ lạ."""

    code = "INGEST_LEDGER_CORRUPT"


# --- Kết quả một lần chạy ---------------------------------------------------


@dataclass
class TrangThaiTaiLieu:
    doc_key: str
    trang_thai: str
    ma: str | None = None
    ly_do: str = ""
    doc_id: str | None = None
    re_ingest: bool = False
    so_chunk: int = 0
    so_hyperedge: int = 0
    so_entity: int = 0
    bat_dau: str = ""
    ket_thuc: str = ""


@dataclass
class KetQuaNap:
    """Kết quả một lần chạy: từ chối ở cửa quét và trạng thái từng tài liệu.

    Nơi gọi có thể dựng sẵn và truyền vào để giữ được phần đã ghi khi lần chạy
    dừng giữa chừng bằng exception (lệch đối chiếu, port audit hỏng).
    """

    tu_choi: list[TuChoi] = field(default_factory=list)
    tai_lieu: list[TrangThaiTaiLieu] = field(default_factory=list)

    def da_nap(self) -> list[TrangThaiTaiLieu]:
        return [t for t in self.tai_lieu if t.trang_thai == TRANG_THAI_DA_NAP]


# --- Sổ tài liệu bền vững ------------------------------------------------------


@dataclass
class MucTaiLieu:
    """Một tài liệu đã nạp: id đã tạo và phần đóng góp vào entity chung.

    `entity[graph_id] = {"vector_id", "mo_ta": [...], "chunk_ids": [...]}`:
    `mo_ta` là các mảnh `description` mà tài liệu này góp (tính bằng phép trừ
    trên sổ, Design Notes), `chunk_ids` là phần `source_id` của entity thuộc
    chunk của tài liệu này. `sha256` của thân tài liệu để nhận ra "không đổi".
    """

    doc_id: str
    sha256: str
    scope: str
    content_type: str
    chunk_ids: list[str] = field(default_factory=list)
    hyperedge: dict[str, str] = field(default_factory=dict)
    entity: dict[str, dict] = field(default_factory=dict)


class SoTaiLieu:
    """Sổ tài liệu theo space: JSON `working_dir/so_tai_lieu_{space}.json`, ghi nguyên tử."""

    def __init__(self, duong_dan: Path, muc: dict[str, MucTaiLieu]):
        self._duong_dan = duong_dan
        self._muc = muc

    @staticmethod
    def duong_dan(working_dir, space: str) -> Path:
        return Path(working_dir) / f"so_tai_lieu_{validate_space(space)}.json"

    @classmethod
    def mo(cls, working_dir, space: str) -> "SoTaiLieu":
        duong_dan = cls.duong_dan(working_dir, space)
        muc: dict[str, MucTaiLieu] = {}
        if duong_dan.exists():
            try:
                raw = json.loads(duong_dan.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as loi:
                raise LedgerCorrupt(f"sổ tài liệu {duong_dan.name!r} không parse được: {loi}") from loi
            if not isinstance(raw, dict) or raw.get("version") != VERSION_SO_TAI_LIEU:
                raise LedgerCorrupt(
                    f"sổ tài liệu {duong_dan.name!r} phải là bảng có version={VERSION_SO_TAI_LIEU},"
                    f" nhận được {raw.get('version') if isinstance(raw, dict) else type(raw).__name__!r}"
                )
            tai_lieu = raw.get("tai_lieu")
            if not isinstance(tai_lieu, dict):
                raise LedgerCorrupt(f"sổ tài liệu {duong_dan.name!r} thiếu bảng `tai_lieu`")
            try:
                muc = {k: MucTaiLieu(**v) for k, v in tai_lieu.items()}
            except TypeError as loi:
                raise LedgerCorrupt(f"sổ tài liệu {duong_dan.name!r} có mục sai hình dạng: {loi}") from loi
        return cls(duong_dan, muc)

    def luu(self) -> None:
        self._duong_dan.parent.mkdir(parents=True, exist_ok=True)
        tam = self._duong_dan.with_name(self._duong_dan.name + DUOI_TAM)
        try:
            with tam.open("w", encoding="utf-8") as f:
                json.dump(
                    {"version": VERSION_SO_TAI_LIEU, "tai_lieu": {k: asdict(v) for k, v in self._muc.items()}},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            os.replace(tam, self._duong_dan)
        finally:
            tam.unlink(missing_ok=True)

    def xoa_file(self) -> None:
        self._muc.clear()
        self._duong_dan.unlink(missing_ok=True)

    def cac_doc_key(self) -> list[str]:
        return sorted(self._muc)

    def muc(self, doc_key: str) -> MucTaiLieu | None:
        return self._muc.get(doc_key)

    def dat(self, doc_key: str, muc: MucTaiLieu) -> None:
        self._muc[doc_key] = muc

    def bo(self, doc_key: str) -> None:
        self._muc.pop(doc_key, None)

    def doc_key_cua_doc_id(self, doc_id: str) -> str | None:
        for k, m in self._muc.items():
            if m.doc_id == doc_id:
                return k
        return None

    def chunk_cua_doc_khac(self, doc_key: str) -> set[str]:
        return {c for k, m in self._muc.items() if k != doc_key for c in m.chunk_ids}

    def hyperedge_cua_doc_khac(self, doc_key: str) -> set[str]:
        return {h for k, m in self._muc.items() if k != doc_key for h in m.hyperedge}

    def entity_cua_doc_khac(self, doc_key: str) -> set[str]:
        return {e for k, m in self._muc.items() if k != doc_key for e in m.entity}

    def nhan_cua_doc_khac_ke_hyperedge(self, doc_key: str, hyperedge_id: str) -> list[str]:
        """Khóa lọc của các tài liệu *khác* kể tên hyperedge này."""
        return [
            filter_key(m.scope, m.content_type)
            for k, m in self._muc.items()
            if k != doc_key and hyperedge_id in m.hyperedge
        ]

    def dong_gop_khac(self, doc_key: str, entity_id: str) -> tuple[set[str], set[str]]:
        """(hợp `mo_ta`, hợp `chunk_ids`) mà các tài liệu *khác* góp vào entity."""
        mo_ta: set[str] = set()
        chunk: set[str] = set()
        for k, m in self._muc.items():
            if k == doc_key:
                continue
            e = m.entity.get(entity_id)
            if e:
                mo_ta.update(e.get("mo_ta", ()))
                chunk.update(e.get("chunk_ids", ()))
        return mo_ta, chunk


# --- Khóa một tiến trình mỗi space --------------------------------------------


class KhoaIngest:
    """`flock` không chặn trên `working_dir/ingest_{space}.lock`."""

    def __init__(self, working_dir, space: str):
        self._duong_dan = self.duong_dan(working_dir, space)
        self._f = None

    @staticmethod
    def duong_dan(working_dir, space: str) -> Path:
        return Path(working_dir) / f"ingest_{validate_space(space)}.lock"

    def __enter__(self):
        self._duong_dan.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self._duong_dan, "w")
        try:
            fcntl.flock(self._f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as loi:
            self._f.close()
            self._f = None
            # Chỉ "đang bị giữ" mới là tiến trình thứ hai; lỗi khác (hệ thống
            # file không hỗ trợ flock, hết file descriptor) dội nguyên.
            if loi.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
            raise IngestAlreadyRunning(
                f"một tiến trình ingest khác đang giữ {self._duong_dan}: mỗi space"
                " chỉ một tiến trình ingest"
            ) from None
        return self

    def __exit__(self, *loi):
        if self._f is not None:
            fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
            self._f.close()
            self._f = None
        return False


# --- Kiểm trước khi chạm kho -------------------------------------------------


async def _kiem_real(space: str, engine) -> None:
    """Space `real`: hai provider phải cục bộ và sẵn sàng; không thì không chạm kho."""
    if not la_space_real(space):
        return
    for ten, ham in (("llm", engine.llm_model_func), ("embedding", engine.embedding_func)):
        ncc = nha_cung_cap_cua(ham)
        if ncc is None:
            raise LocalLLMUnavailable(
                f"không tìm thấy provider đứng sau hàm {ten} đã bọc của engine: không kiểm được"
                " provider có cục bộ và sẵn sàng không"
            )
        if not getattr(ncc, "cuc_bo", False):
            raise ProviderNotAllowedForSpace(
                f"space {space!r} là không gian dữ liệu thật, chỉ nhận provider cục bộ;"
                f" provider {ten} {getattr(ncc, 'ten', '?')!r} là API ngoài (AD-12)"
            )
        san_sang = getattr(ncc, "san_sang", None)
        if san_sang is None or not await san_sang():
            raise LocalLLMUnavailable(
                f"provider cục bộ {getattr(ncc, 'ten', '?')!r} ({ten}) chưa sẵn sàng"
                + (" (không có phép thăm dò `san_sang`)" if san_sang is None else "")
                + "; space real không fallback API ngoài (AD-12)"
            )


def _bang_hang(engine):
    return bang_hang_cho(asdict(engine))


def _doc_id(noi_dung: str) -> str:
    """Đúng công thức doc id của `ainsert` (`hypergraphrag.py:281`)."""
    return compute_mdhash_id(noi_dung.strip(), prefix="doc-")


def _sha256(noi_dung: str) -> str:
    return hashlib.sha256(noi_dung.encode("utf-8")).hexdigest()


def _chunk_ids_cua(engine, noi_dung: str) -> list[str]:
    """Id chunk mà `ainsert` sẽ sinh cho tài liệu này, tính bằng chính hàm chia chunk của vendor.

    Sổ đợt chỉ thấy chunk mà `ainsert` *ghi*; chunk trùng nội dung với tài
    liệu khác cùng khóa bị `filter_keys` loại trước khi ghi nên vắng ở đó,
    trong khi tài liệu này vẫn dùng nó. Gọi `chunking_by_token_size` với đúng
    tham số của engine, không viết lại luật.
    """
    return [
        compute_mdhash_id(dp["content"], prefix="chunk-")
        for dp in chunking_by_token_size(
            noi_dung.strip(),
            overlap_token_size=engine.chunk_overlap_token_size,
            max_token_size=engine.chunk_token_size,
            tiktoken_model=engine.tiktoken_model_name,
        )
    ]


# --- Đọc lại sổ đợt sau ainsert ---------------------------------------------


def _id_theo_kho(so_dot: SoDot, ten_kho: str) -> dict[str, str]:
    """`id_join -> id trong kho` của mọi id mà đợt ghi vào một kho."""
    return {
        id_join: kho[ten_kho]
        for id_join in so_dot.cac_id()
        for kho in [so_dot.kho_cua(id_join)]
        if ten_kho in kho
    }


def _dong_gop_cua(so: SoTaiLieu, doc_key: str, entity_id: str, fragment_hien_tai: Iterable[str]) -> list[str]:
    """Đóng góp `description` của tài liệu vào entity = mảnh hiện có trừ hợp đóng góp của tài liệu khác.

    Design Notes: sổ là đầy đủ vì mọi tài liệu đi qua pipeline, nên không cần
    snapshot trước `ainsert`. Bản tóm tắt LLM (nếu upstream đã gộp) rơi vào
    tài liệu vừa nạp và biến mất khi nó bị bỏ - chấp nhận, tóm tắt là dẫn xuất.

    Giới hạn đã biết: upstream gộp mô tả bằng join *set*, nên hai tài liệu góp
    cùng một mảnh giống hệt thì mảnh đó chỉ ghi cho tài liệu nạp trước; bỏ tài
    liệu trước là mất mảnh dù tài liệu sau vẫn góp (ledger, địa chỉ 2.12).
    """
    khac, _ = so.dong_gop_khac(doc_key, entity_id)
    return sorted(set(fragment_hien_tai) - khac)


async def _muc_tu_so_dot(engine, so: SoTaiLieu, tai_lieu: TaiLieuNguon, so_dot: SoDot) -> MucTaiLieu:
    graph = engine.chunk_entity_relation_graph
    chunk_ids = sorted(
        set(_id_theo_kho(so_dot, ten_kho_kv("text_chunks")).values()) | set(_chunk_ids_cua(engine, tai_lieu.noi_dung))
    )
    hyperedge = _id_theo_kho(so_dot, ten_kho_vector("hyperedges"))
    entity_vector = _id_theo_kho(so_dot, ten_kho_vector("entities"))
    tap_chunk = set(chunk_ids)
    entity: dict[str, dict] = {}
    for id_join, vector_id in entity_vector.items():
        node = await graph.get_node(id_join)
        mo_ta = split_sep(node.get("description", "")) if node else []
        nguon = split_sep(node.get("source_id", "")) if node else []
        entity[id_join] = {
            "vector_id": vector_id,
            "mo_ta": _dong_gop_cua(so, tai_lieu.doc_key, id_join, mo_ta),
            # Phần `source_id` thuộc chunk của chính tài liệu này: phép giao là
            # chính xác (chunk trùng nội dung giữa hai tài liệu thuộc cả hai).
            "chunk_ids": sorted(set(nguon) & tap_chunk),
        }
    return MucTaiLieu(
        doc_id=_doc_id(tai_lieu.noi_dung),
        sha256=_sha256(tai_lieu.noi_dung),
        scope=tai_lieu.scope,
        content_type=tai_lieu.content_type,
        chunk_ids=chunk_ids,
        hyperedge=hyperedge,
        entity=entity,
    )


def split_sep(chuoi: str) -> list[str]:
    return [m for m in chuoi.split(SEP) if m]


# --- Xóa theo sổ (dùng cho re-ingest và xóa tài liệu) ------------------------


def _gap_khoa(cac_khoa: Iterable[str | None], hang: Mapping[str, int]):
    """Khóa từ danh sách khóa nguồn: gấp bằng `hop_nhat_khoa` (Design Notes)."""
    ket_qua = CHUA_GHI
    for k in cac_khoa:
        if k is None:
            return KHONG_KHOA
        ket_qua = hop_nhat_khoa(ket_qua, k, hang=hang)
        if ket_qua is KHONG_KHOA:
            return KHONG_KHOA
    return ket_qua


async def _xoa_theo_so(engine, so: SoTaiLieu, doc_key: str) -> MucTaiLieu:
    """Gỡ sạch phần của một tài liệu khỏi ba kho theo sổ, dựng lại hyperedge và entity chung.

    Chạy trong ngữ cảnh hệ thống, trong một đợt riêng có đối chiếu ở cuối:
    mọi mục được đặt lại đều vào sổ đợt qua chính adapter, nên một lần dựng
    lại lệch giữa hai kho cũng đỏ như một lần nạp lệch. Thứ tự: chunk/doc ->
    hyperedge riêng xóa, hyperedge chung dựng lại -> entity (gấp khóa từ
    hyperedge *đã* dựng lại).
    """
    muc = so.muc(doc_key)
    if muc is None:
        raise DocNotInLedger(f"sổ tài liệu không có {doc_key!r}")
    graph = engine.chunk_entity_relation_graph
    hang = _bang_hang(engine).hang

    with dot_ingest() as so_dot:
        # 1. Chunk và doc không còn tài liệu nào dùng.
        chunk_rieng = set(muc.chunk_ids) - so.chunk_cua_doc_khac(doc_key)
        await engine.text_chunks.xoa(sorted(chunk_rieng))
        await engine.chunks_vdb.xoa(sorted(chunk_rieng))
        if so.doc_key_cua_doc_id(muc.doc_id) in (None, doc_key):
            await engine.full_docs.xoa([muc.doc_id])
        # 2. Hyperedge: riêng thì xóa; chung với tài liệu khác thì dựng lại khóa
        #    từ nhãn các tài liệu còn kể tên nó và cắt chunk riêng khỏi source_id.
        h_khac = so.hyperedge_cua_doc_khac(doc_key)
        h_rieng = [h for h in muc.hyperedge if h not in h_khac]
        h_chung = [h for h in muc.hyperedge if h in h_khac]
        await graph.xoa_node(h_rieng)
        await engine.hyperedges_vdb.xoa([muc.hyperedge[h] for h in h_rieng])
        payload_h = await engine.hyperedges_vdb.payload_cua([muc.hyperedge[h] for h in h_chung])
        for h in h_chung:
            khoa = _gap_khoa(so.nhan_cua_doc_khac_ke_hyperedge(doc_key, h), hang)
            node = await graph.get_node(h) or {}
            nguon = sorted(set(split_sep(node.get("source_id", ""))) - chunk_rieng)
            await graph.dat_lai_hyperedge(h, source_id=SEP.join(nguon), khoa=khoa)
            ten = (payload_h.get(muc.hyperedge[h]) or {}).get("hyperedge_name", h)
            await engine.hyperedges_vdb.ghi_thang(
                muc.hyperedge[h], content=ten, khoa=khoa, meta={"hyperedge_name": ten}
            )
        # 3. Entity: còn hyperedge nối thì dựng lại từ đóng góp còn lại, không thì xóa.
        payload_e = await engine.entities_vdb.payload_cua([e["vector_id"] for e in muc.entity.values()])
        for e_id, e in muc.entity.items():
            khoa_lan_can = await graph.khoa_lan_can_hyperedge(e_id)
            if not khoa_lan_can:
                await graph.xoa_node([e_id])
                await engine.entities_vdb.xoa([e["vector_id"]])
                continue
            mo_ta, chunk = so.dong_gop_khac(doc_key, e_id)
            khoa = _gap_khoa(khoa_lan_can, hang)
            description = SEP.join(sorted(mo_ta))
            await graph.dat_lai_entity(
                e_id, description=description, source_id=SEP.join(sorted(chunk)), khoa=khoa
            )
            # Tên trong payload hiện có (upstream giữ nguyên dấu nháy của bản
            # ghi trích xuất), không phải id đã chuẩn hóa: point dựng lại phải
            # giống hệt point mà `ainsert` sẽ ghi.
            ten = (payload_e.get(e["vector_id"]) or {}).get("entity_name", e_id)
            await engine.entities_vdb.ghi_thang(
                e["vector_id"],
                content=ten + description,
                khoa=khoa,
                meta={"entity_name": ten},
            )
        await engine.text_chunks.index_done_callback()
        await engine.full_docs.index_done_callback()
        await doi_chieu_dot(so_dot, kho=kho_cua_engine(engine))
    so.bo(doc_key)
    so.luu()
    return muc


async def _don_dot_khong_fact(engine, so: SoTaiLieu, doc_key: str, doc_id: str, so_dot: SoDot) -> None:
    """Gỡ mọi thứ `ainsert` đã ghi trong đợt của một tài liệu không có hyperedge.

    Upstream chỉ return sớm khi không có cả entity lẫn hyperedge; có entity mà
    không hyperedge thì graph, `entities_vdb`, KV đều đã ghi. Dọn theo sổ đợt,
    trừ phần tài liệu khác đang dùng (chunk chung, entity tài liệu khác kể tên).
    """
    graph = engine.chunk_entity_relation_graph
    entity = _id_theo_kho(so_dot, ten_kho_vector("entities"))
    e_khac = so.entity_cua_doc_khac(doc_key)
    e_rieng = [e for e in entity if e not in e_khac]
    await graph.xoa_node(e_rieng)
    await engine.entities_vdb.xoa([entity[e] for e in e_rieng])
    chunk = set(_id_theo_kho(so_dot, ten_kho_kv("text_chunks")).values()) | set(
        _id_theo_kho(so_dot, ten_kho_vector("chunks")).values()
    )
    chunk_rieng = sorted(chunk - so.chunk_cua_doc_khac(doc_key))
    await engine.text_chunks.xoa(chunk_rieng)
    await engine.chunks_vdb.xoa(chunk_rieng)
    if ten_kho_kv("full_docs") in {k for id_join in so_dot.cac_id() for k in so_dot.kho_cua(id_join)}:
        await engine.full_docs.xoa([doc_id])
    await engine.text_chunks.index_done_callback()
    await engine.full_docs.index_done_callback()


# --- Sự kiện audit ------------------------------------------------------------


def _su_kien(event: str, *, space: str, policy_version: str, hyperedge_ids=(), **chi_tiet) -> SuKienAudit:
    """`hyperedge_ids` là id **vector** (`rel-<md5>`), mờ, không mang nội dung fact."""
    return SuKienAudit(
        tier=TIER_MUTATION,
        event=event,
        space=space,
        policy_version=policy_version,
        thoi_diem=thoi_diem_utc(),
        hyperedge_ids=tuple(hyperedge_ids),
        chi_tiet=chi_tiet,
    )


def _chi_tiet_muc(doc_key: str, muc: MucTaiLieu, *, re_ingest: bool, bang_version: str) -> dict:
    return dict(
        doc_key=doc_key,
        doc_id=muc.doc_id,
        scope=muc.scope,
        content_type=muc.content_type,
        so_chunk=len(muc.chunk_ids),
        so_hyperedge=len(muc.hyperedge),
        so_entity=len(muc.entity),
        re_ingest=re_ingest,
        sensitivity_ranks_version=bang_version,
    )


# --- Nạp một tài liệu --------------------------------------------------------


async def nap_tai_lieu(
    engine,
    tai_lieu: TaiLieuNguon,
    *,
    so: SoTaiLieu,
    space: str,
    policy_version: str,
    audit: AuditPort,
    tt: TrangThaiTaiLieu | None = None,
    ep_ghi_de: bool = False,
) -> TrangThaiTaiLieu:
    """Nạp một tài liệu trong ngữ cảnh hệ thống riêng; gọi từ `nap_cac_tai_lieu` khi đã giữ khóa.

    Thứ tự: kiểm hạng loại nội dung (trước khi chạm kho) -> kiểm trùng nội dung
    -> "không đổi" (cùng sha256 và nhãn, trừ khi `ep_ghi_de`) -> xóa phần cũ +
    `delete_doc` nếu re-ingest -> `ainsert` dưới nhãn + đợt riêng -> dọn nếu
    đợt không có hyperedge -> đối chiếu -> dựng mục sổ -> `ingest_doc` -> lưu
    sổ. Lỗi ở kho hay ở port audit thì trạng thái là `loi` và exception dội
    lên (dừng lần chạy); các kiểm đầu chỉ ghi kết quả và trả về để tài liệu
    kế đi tiếp.

    `tt` là bản ghi trạng thái do nơi gọi giữ, cập nhật **tại chỗ**: một lần
    chạy dừng bằng exception vẫn để lại mã lỗi của tài liệu trong `KetQuaNap`.
    """
    tt = TrangThaiTaiLieu(doc_key=tai_lieu.doc_key, trang_thai=TRANG_THAI_LOI) if tt is None else tt
    tt.trang_thai, tt.bat_dau = TRANG_THAI_LOI, thoi_diem_utc()
    bang = _bang_hang(engine)
    try:
        bang.hang_cua(tai_lieu.content_type)
    except SensitivityRankUnknown as loi:
        tt.ma, tt.ly_do, tt.ket_thuc = loi.code, str(loi), thoi_diem_utc()
        return tt
    doc_id = _doc_id(tai_lieu.noi_dung)
    tt.doc_id = doc_id
    trung = so.doc_key_cua_doc_id(doc_id)
    if trung is not None and trung != tai_lieu.doc_key:
        tt.trang_thai, tt.ma = TRANG_THAI_TU_CHOI, MA_TRUNG_NOI_DUNG
        tt.ly_do = f"cùng nội dung với tài liệu {trung!r} đã nạp (doc_id {doc_id})"
        tt.ket_thuc = thoi_diem_utc()
        return tt
    muc_cu = so.muc(tai_lieu.doc_key)
    tt.re_ingest = muc_cu is not None
    if (
        muc_cu is not None
        and not ep_ghi_de
        and muc_cu.sha256 == _sha256(tai_lieu.noi_dung)
        and (muc_cu.scope, muc_cu.content_type) == (tai_lieu.scope, tai_lieu.content_type)
    ):
        tt.trang_thai, tt.ket_thuc = TRANG_THAI_KHONG_DOI, thoi_diem_utc()
        tt.ly_do = "cùng sha256 và cùng nhãn với bản đã nạp; không chạm kho (ép bằng ep_ghi_de)"
        tt.so_chunk, tt.so_hyperedge, tt.so_entity = len(muc_cu.chunk_ids), len(muc_cu.hyperedge), len(muc_cu.entity)
        return tt

    with use_context(system_context(space=space, policy_version=policy_version)):
        try:
            if tt.re_ingest:
                muc_cu = await _xoa_theo_so(engine, so, tai_lieu.doc_key)
                await ghi_bien_doi(
                    audit,
                    _su_kien(
                        EVENT_DELETE_DOC,
                        space=space,
                        policy_version=policy_version,
                        hyperedge_ids=sorted(muc_cu.hyperedge.values()),
                        **_chi_tiet_muc(tai_lieu.doc_key, muc_cu, re_ingest=True, bang_version=bang.version),
                    ),
                )
            with ingest_label(scope=tai_lieu.scope, content_type=tai_lieu.content_type):
                with dot_ingest() as so_dot:
                    await engine.ainsert(tai_lieu.noi_dung)
                    if len(so_dot) == 0:
                        tt.ma = MA_DA_CO_TRONG_KHO
                        tt.ly_do = "ainsert không ghi gì: doc/chunk đã có trong kho mà sổ tài liệu không biết"
                        tt.ket_thuc = thoi_diem_utc()
                        return tt
                    if not _id_theo_kho(so_dot, ten_kho_vector("hyperedges")):
                        await _don_dot_khong_fact(engine, so, tai_lieu.doc_key, doc_id, so_dot)
                        tt.ma = MA_KHONG_CO_FACT
                        tt.ly_do = "không trích được hyperedge nào; phần đã ghi trong đợt được dọn"
                        tt.ket_thuc = thoi_diem_utc()
                        return tt
                    await doi_chieu_dot(so_dot, kho=kho_cua_engine(engine))
                    muc = await _muc_tu_so_dot(engine, so, tai_lieu, so_dot)
            await ghi_bien_doi(
                audit,
                _su_kien(
                    EVENT_INGEST_DOC,
                    space=space,
                    policy_version=policy_version,
                    hyperedge_ids=sorted(muc.hyperedge.values()),
                    **_chi_tiet_muc(tai_lieu.doc_key, muc, re_ingest=tt.re_ingest, bang_version=bang.version),
                ),
            )
        except Exception as loi:
            tt.ma = getattr(loi, "code", type(loi).__name__)
            tt.ly_do, tt.ket_thuc = str(loi), thoi_diem_utc()
            raise
    so.dat(tai_lieu.doc_key, muc)
    so.luu()
    tt.trang_thai = TRANG_THAI_DA_NAP
    tt.so_chunk, tt.so_hyperedge, tt.so_entity = len(muc.chunk_ids), len(muc.hyperedge), len(muc.entity)
    tt.ket_thuc = thoi_diem_utc()
    return tt


# --- Điểm vào ------------------------------------------------------------------


async def nap_cac_tai_lieu(
    engine,
    cac_tai_lieu: Iterable[TaiLieuNguon],
    *,
    space: str,
    policy_version: str,
    audit: AuditPort,
    tu_choi: Iterable[TuChoi] = (),
    ket_qua: KetQuaNap | None = None,
    ep_ghi_de: bool = False,
) -> KetQuaNap:
    """Nạp tuần tự một danh sách tài liệu đã quét, dưới khóa một tiến trình mỗi space."""
    ket_qua = KetQuaNap() if ket_qua is None else ket_qua
    ket_qua.tu_choi.extend(tu_choi)
    validate_space(space)
    with KhoaIngest(engine.working_dir, space):
        await _kiem_real(space, engine)
        so = SoTaiLieu.mo(engine.working_dir, space)
        with use_context(system_context(space=space, policy_version=policy_version)):
            await engine.khoi_tao()
        for tai_lieu in cac_tai_lieu:
            tt = TrangThaiTaiLieu(doc_key=tai_lieu.doc_key, trang_thai=TRANG_THAI_LOI)
            ket_qua.tai_lieu.append(tt)
            await nap_tai_lieu(
                engine,
                tai_lieu,
                so=so,
                space=space,
                policy_version=policy_version,
                audit=audit,
                tt=tt,
                ep_ghi_de=ep_ghi_de,
            )
    return ket_qua


async def nap_thu_muc(
    engine, thu_muc, *, space: str, policy_version: str, audit: AuditPort, ket_qua=None, ep_ghi_de: bool = False
) -> KetQuaNap:
    """Quét một thư mục rồi nạp; từ chối ở cửa quét nằm trong `KetQuaNap.tu_choi`."""
    return await _nap_ket_qua_quet(
        engine,
        quet_thu_muc(Path(thu_muc)),
        space=space,
        policy_version=policy_version,
        audit=audit,
        ket_qua=ket_qua,
        ep_ghi_de=ep_ghi_de,
    )


async def nap_cac_file(
    engine, cac_file, *, space: str, policy_version: str, audit: AuditPort, ket_qua=None, ep_ghi_de: bool = False
) -> KetQuaNap:
    """Quét một danh sách file rồi nạp, theo thứ tự truyền vào; `doc_key` là tên file."""
    return await _nap_ket_qua_quet(
        engine,
        quet_cac_file([Path(f) for f in cac_file]),
        space=space,
        policy_version=policy_version,
        audit=audit,
        ket_qua=ket_qua,
        ep_ghi_de=ep_ghi_de,
    )


async def _nap_ket_qua_quet(engine, quet: KetQuaQuet, *, space, policy_version, audit, ket_qua, ep_ghi_de) -> KetQuaNap:
    return await nap_cac_tai_lieu(
        engine,
        quet.chap_nhan,
        space=space,
        policy_version=policy_version,
        audit=audit,
        tu_choi=quet.tu_choi,
        ket_qua=ket_qua,
        ep_ghi_de=ep_ghi_de,
    )


async def xoa_tai_lieu(
    engine, doc_key: str, *, space: str, policy_version: str, audit: AuditPort, ket_qua: KetQuaNap | None = None
) -> TrangThaiTaiLieu:
    """Gỡ một tài liệu khỏi ba kho theo sổ; một sự kiện `delete_doc`; trạng thái `da_xoa`."""
    validate_space(space)
    ket_qua = KetQuaNap() if ket_qua is None else ket_qua
    tt = TrangThaiTaiLieu(doc_key=doc_key, trang_thai=TRANG_THAI_LOI, bat_dau=thoi_diem_utc())
    ket_qua.tai_lieu.append(tt)
    with KhoaIngest(engine.working_dir, space):
        await _kiem_real(space, engine)
        so = SoTaiLieu.mo(engine.working_dir, space)
        if so.muc(doc_key) is None:
            tt.ma, tt.ket_thuc = DocNotInLedger.code, thoi_diem_utc()
            tt.ly_do = f"sổ tài liệu của space {space!r} không có {doc_key!r}"
            raise DocNotInLedger(tt.ly_do)
        bang = _bang_hang(engine)
        with use_context(system_context(space=space, policy_version=policy_version)):
            try:
                muc = await _xoa_theo_so(engine, so, doc_key)
                await ghi_bien_doi(
                    audit,
                    _su_kien(
                        EVENT_DELETE_DOC,
                        space=space,
                        policy_version=policy_version,
                        hyperedge_ids=sorted(muc.hyperedge.values()),
                        **_chi_tiet_muc(doc_key, muc, re_ingest=False, bang_version=bang.version),
                    ),
                )
            except Exception as loi:
                tt.ma, tt.ly_do, tt.ket_thuc = getattr(loi, "code", type(loi).__name__), str(loi), thoi_diem_utc()
                raise
        tt.trang_thai, tt.doc_id, tt.ket_thuc = TRANG_THAI_DA_XOA, muc.doc_id, thoi_diem_utc()
        tt.so_chunk, tt.so_hyperedge, tt.so_entity = len(muc.chunk_ids), len(muc.hyperedge), len(muc.entity)
        return tt


async def xoa_space(engine, *, space: str, policy_version: str, audit: AuditPort) -> None:
    """Xóa sạch một space ở cả ba kho, hai sổ, rồi dựng lại kho rỗng; một sự kiện `delete_space`.

    Không đi qua sổ tài liệu từng mục: xóa theo nhãn space ở graph và bỏ cả
    collection ở vector, nên cả dữ liệu nạp trước khi có sổ (đo thô 2.2) cũng
    được dọn. `khoi_tao()` chạy lại ở cuối để space dùng được ngay.
    """
    validate_space(space)
    with KhoaIngest(engine.working_dir, space):
        await _kiem_real(space, engine)
        so = SoTaiLieu.mo(engine.working_dir, space)
        so_tai_lieu = len(so.cac_doc_key())
        bang = _bang_hang(engine)
        with use_context(system_context(space=space, policy_version=policy_version)):
            so_node = await engine.chunk_entity_relation_graph.xoa_tat_ca()
            for vdb in (engine.entities_vdb, engine.hyperedges_vdb, engine.chunks_vdb):
                await vdb.xoa_tat_ca()
            for kv in (engine.text_chunks, engine.full_docs):
                await kv.xoa_tat_ca()
            so.xoa_file()
            await ghi_bien_doi(
                audit,
                _su_kien(
                    EVENT_DELETE_SPACE,
                    space=space,
                    policy_version=policy_version,
                    so_tai_lieu=so_tai_lieu,
                    so_node_graph=so_node,
                    sensitivity_ranks_version=bang.version,
                ),
            )
            await engine.khoi_tao()
