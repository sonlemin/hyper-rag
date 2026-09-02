"""Đối chiếu khóa quyền giữa các kho sau mỗi đợt ingest (story 2.1, NFR-03).

Luật hợp nhất khóa sống ở một chỗ (`core.keys.hop_nhat_khoa`, gọi qua cửa chung
`adapters.ingest_labels`), nên ba đường ghi không lệch nhau vì *luật*. Cái còn
lại là lệch vì **sự cố**: một lô ghi đứt giữa chừng, một kho rớt, một id được
ghi ở kho này mà trượt ở kho kia. Bước này bắt đúng loại lệch đó, và bắt bằng
cách đọc lại cả hai kho chứ không bằng cách tin vào giá trị vừa tính.

**Không tự sửa, không có cờ tắt.** Lệch là đợt ingest fail kèm danh sách cặp
id. Tự sửa nghĩa là đoán kho nào đúng, mà cả hai kho đều có thể là kho sai; và
một cờ tắt là thứ sẽ được bật đúng vào lúc nó cần nhất.

**Sổ đợt do chính adapter ghi.** Nếu pipeline tự liệt kê id đã ghi thì id bị
read-merge-write chạm (ghi lại khóa mà không thêm bản ghi mới) là thứ dễ quên
nhất, và cũng là thứ story này sinh ra để canh. Ba adapter ghi vào sổ ngay
trong đường ghi của chúng, nên "mọi id được ghi trong đợt" là một tính chất của
code chứ không phải một lời hứa. Ngoài phạm vi một đợt thì `ghi_vao_so` là
no-op: bộ test adapter lẻ và đường truy vấn không có gì để đối chiếu.

**Id join chéo hai kho.** Node graph mang tên thực thể/tên hyperedge làm id,
còn point vector mang id upstream (`ent-…`, `rel-…`) và giữ chính cái tên đó
trong payload (`operate.py:461-479` ghi `entity_name`/`hyperedge_name`). Nên id
join là *tên node*, và mỗi kho tự khai id nội bộ của nó. Chunk thì id ở kho KV
và ở collection `chunks` trùng nhau nên join là chính id đó.

**Vector không phân biệt được "vắng" với "không khóa".** Ca không khóa xóa point
khỏi collection (AD-5 đòi vắng mặt tuyệt đối), nên nhìn từ Qdrant một point
vắng có thể là "chưa từng ghi" hoặc "đã hợp nhất ra không khóa". Bước đối chiếu
nhận cả hai khả năng cho báo cáo của kho vector và chỉ kết luận lệch khi không
còn khả năng nào chung với các kho khác. Điều đó **mỗi kho tự khai** bằng
`VANG_LA_MO_HO`, không phải bước đối chiếu suy từ tên kho: suy từ tên là treo
ngữ nghĩa của phép so vào một tiền tố chuỗi, và hai chỗ ấy trôi dạt được.
"""

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, Mapping

from core.keys import CHUA_GHI, KHONG_KHOA

# Tên kho trong sổ đợt và trong thông điệp lỗi. Một hằng cho kho graph, hai hàm
# cho hai họ kho có nhiều namespace: `vector:entities` và `kv:text_chunks` đọc
# ra ngay là kho nào, thứ mà một thông điệp lỗi nói về "kho 0 và kho 1" không
# làm được.
KHO_GRAPH: str = "graph"


def ten_kho_vector(namespace: str) -> str:
    return f"vector:{namespace}"


def ten_kho_kv(namespace: str) -> str:
    return f"kv:{namespace}"


class StoreKeyMismatch(RuntimeError):
    """Khóa quyền của một id lệch giữa hai kho, hoặc có ở kho này thiếu ở kho kia.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).

    **Thông điệp cố ý không mang id nguyên văn.** Id join của node graph *là*
    tên thực thể, tức có thể là nguyên văn một giá trị slot thuộc scope hạn chế
    (fixture của dự án mô hình hóa đúng như vậy). Bước đối chiếu chạy dưới cờ
    system nên nó đọc thô được mọi khóa, và thông điệp lỗi thì đi thẳng vào log
    vận hành - ngoài mọi tầng che, vào một file mà người đọc không nhất thiết
    có quyền với scope đó. Nên phần định danh trong thông điệp là **vân tay**
    sha256 rút gọn; ai cần id thật thì đọc `CapLech.id_join` của exception, một
    chỗ có kiểm soát chứ không phải một dòng log.
    """

    code = "STORE_KEY_MISMATCH"


# Tên thuộc tính mà mỗi storage phải khai để bước đối chiếu đọc được báo cáo
# "vắng" của nó. Hằng ở đây, không phải một chuỗi viết tay ở ba chỗ: đổi tên
# thuộc tính mà quên một adapter thì `ReconcileStoreContractMissing` nổ ngay
# thay vì một adapter lặng lẽ rơi về một mặc định nào đó.
TEN_VANG_MO_HO: str = "VANG_LA_MO_HO"


class ReconcileStoreContractMissing(RuntimeError):
    """Một storage không khai `VANG_LA_MO_HO`, nên bước đối chiếu không chạy.

    Câu hỏi "kho này trả 'vắng' thì có thể là 'không khóa' không" quyết định
    toàn bộ phép so, và chỉ chính kho trả lời được: kho vector xóa point ở ca
    không khóa nên "vắng" của nó mơ hồ, còn graph và KV giữ bản ghi lại nên
    "vắng" của chúng đúng là chưa từng ghi. Đoán một mặc định là chọn giữa hai
    cách hỏng: mặc định True làm mọi lệch thật thành "không lệch", mặc định
    False làm mọi ca không khóa thành lệch giả - và một bước đối chiếu hay báo
    động giả là một bước sẽ bị tắt. Nên không đoán.

    Cùng kỷ luật fail-closed với `tests/test_phan_chieu_che.py`: một kho mới
    phải *khai* chỗ đứng của nó, không được im lặng thừa hưởng một mặc định.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).
    """

    code = "RECONCILE_STORE_CONTRACT_MISSING"


class ReconcileStoreMissing(RuntimeError):
    """Bước đối chiếu không được đưa một kho mà đợt có ghi vào.

    Đối chiếu nửa vời còn tệ hơn không đối chiếu: nó trả về "không lệch" cho
    một tập id mà nó chưa từng nhìn đủ hai phía. `code` theo AD-8 thay vì một
    `KeyError` trần, vì đây là một cách hỏng mà nơi gọi phải phân biệt được.
    """

    code = "RECONCILE_STORE_MISSING"


def van_tay(id_join: str) -> str:
    """Vân tay ngắn của một id, dùng thay id nguyên văn trong thông điệp lỗi.

    12 hex đầu của sha256: đủ để hai lần chạy đối chiếu được với nhau và để
    người vận hành gom các dòng nói về cùng một mục, mà không mang nguyên văn
    một giá trị slot ra khỏi tầng che. Tất định, nên nó tra ngược được bằng
    chính hàm này khi đã có id trong tay.
    """
    return hashlib.sha256(id_join.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class CapLech:
    """Một id mà các kho không nói cùng một khóa.

    `bao_cao` là map tên kho -> mô tả khóa mà kho đó trả về, giữ nguyên thứ tự
    đọc để hai lần chạy cho ra cùng một thông điệp. `id_join` giữ nguyên văn ở
    đây - nơi gọi cầm exception thì đã ở trong tiến trình ingest dưới cờ system
    - còn `__str__` (thứ đi vào log) chỉ mang vân tay.
    """

    id_join: str
    bao_cao: Mapping[str, str]

    def __str__(self) -> str:
        chi_tiet = ", ".join(f"{kho}={mo_ta}" for kho, mo_ta in self.bao_cao.items())
        return f"id#{van_tay(self.id_join)}: {chi_tiet}"


@dataclass
class SoDot:
    """Sổ của một đợt ingest: id join -> (tên kho -> id trong kho đó).

    Mang thêm **tập kho kỳ vọng** của mỗi id. Không có nó thì một id chỉ được
    *một* kho ghi sổ luôn tự khớp với chính nó: phép giao trên đúng một tập
    không bao giờ rỗng, nên hàng I/O Matrix "có ở kho này thiếu ở kho kia" đi
    qua im lặng - đúng ca mà bước đối chiếu sinh ra để bắt.

    Kỳ vọng do chính adapter khai (`kho_doi`), vì chỉ nó biết: node vai
    hyperedge đi cùng `vector:hyperedges`, node vai entity đi cùng
    `vector:entities`, chunk KV đi cùng `vector:chunks`, còn `full_docs` không
    có bản sao vector nào. Khai từ phía kho biết câu trả lời là một bảng, khai
    ở đây là một bảng thứ hai lệch được.
    """

    _muc: dict[str, dict[str, str]] = field(default_factory=dict)
    _ky_vong: dict[str, set[str]] = field(default_factory=dict)

    def ghi(
        self, *, id_join: str, kho: str, id_trong_kho: str, kho_doi: str | None = None
    ) -> None:
        self._muc.setdefault(id_join, {})[kho] = id_trong_kho
        ky_vong = self._ky_vong.setdefault(id_join, set())
        ky_vong.add(kho)
        if kho_doi is not None:
            ky_vong.add(kho_doi)

    def cac_id(self) -> list[str]:
        """Id join của đợt, sắp xếp để thông điệp lỗi ổn định giữa các lần chạy."""
        return sorted(self._muc)

    def kho_cua(self, id_join: str) -> Mapping[str, str]:
        return dict(self._muc.get(id_join, {}))

    def kho_ky_vong(self, id_join: str) -> set[str]:
        """Tập kho mà id này phải có mặt ở cuối đợt."""
        return set(self._ky_vong.get(id_join, ()))

    def kho_thieu(self, id_join: str) -> set[str]:
        """Kho kỳ vọng mà đợt chưa từng ghi id này vào - tự nó đã là lệch."""
        return self.kho_ky_vong(id_join) - set(self._muc.get(id_join, {}))

    def __len__(self) -> int:
        return len(self._muc)


# Không giá trị mặc định, cùng lý do với contextvar quyền và contextvar nhãn
# ingest: "đang ở trong đợt nào" phải là một câu hỏi có câu trả lời rõ ràng.
# Khác một chỗ: ngoài phạm vi đợt thì ghi sổ là no-op chứ không phải lỗi, vì
# đường ghi vẫn hợp lệ khi không ai định đối chiếu (bộ test adapter lẻ).
_DOT: ContextVar[SoDot] = ContextVar("so_dot_ingest")


@contextmanager
def dot_ingest() -> Iterator[SoDot]:
    """Mở một đợt ingest; mọi lời ghi bên trong vào chung một sổ.

    Lồng nhau thì sổ trong cùng thắng và thoát ra trả lại sổ ngoài - đúng ngữ
    nghĩa token của contextvar, không phải một chồng sổ tự quản.
    """
    so = SoDot()
    token = _DOT.set(so)
    try:
        yield so
    finally:
        _DOT.reset(token)


def so_dang_mo() -> SoDot | None:
    """Sổ của đợt đang mở, hoặc `None` khi không ở trong đợt nào."""
    return _DOT.get(None)


def ghi_vao_so(
    *, id_join: str, kho: str, id_trong_kho: str, kho_doi: str | None = None
) -> None:
    """Adapter khai **ý định ghi** một id; ngoài phạm vi đợt thì không làm gì.

    Ghi sổ trước khi chạm kho, không phải sau. Ghi sau thì một lô đứt giữa
    chừng để lại id *không* có trong sổ dưới tên kho đó, và bước đối chiếu cuối
    đợt không có gì để hỏi - đúng ca "một kho rớt, id trượt hẳn" mà nó sinh ra
    để bắt. Ghi trước thì id có trong sổ mà khóa vắng ở kho, và đó là một lệch
    nhìn thấy được.

    `kho_doi` là kho mà id này *cũng* phải có mặt, do chính adapter khai.
    """
    so = _DOT.get(None)
    if so is not None:
        so.ghi(
            id_join=id_join, kho=kho, id_trong_kho=id_trong_kho, kho_doi=kho_doi
        )


def kho_cua_engine(engine) -> dict[str, object]:
    """Map tên kho -> storage, dựng từ sáu storage mà engine giữ.

    Nhận engine theo hình dạng (duck typing) chứ không import `adapters.engine`:
    module này nằm *dưới* engine trong chiều phụ thuộc - ba adapter import nó để
    ghi sổ, nên nó không được biết gì về engine.
    """
    return {
        KHO_GRAPH: engine.chunk_entity_relation_graph,
        ten_kho_vector("entities"): engine.entities_vdb,
        ten_kho_vector("hyperedges"): engine.hyperedges_vdb,
        ten_kho_vector("chunks"): engine.chunks_vdb,
        ten_kho_kv("text_chunks"): engine.text_chunks,
        ten_kho_kv("full_docs"): engine.full_docs,
    }


def _mo_ta(bao_cao) -> str:
    """Báo cáo của một kho, dạng người đọc được."""
    if bao_cao is CHUA_GHI:
        return "vắng"
    if bao_cao is KHONG_KHOA:
        return "không khóa"
    return repr(bao_cao)


def vang_la_mo_ho(storage, ten_kho: str) -> bool:
    """Kho này trả "vắng" thì có thể là "không khóa" không - hỏi chính nó.

    Đọc thuộc tính mà storage khai, **không** suy từ tên kho. Suy từ tên là
    treo ngữ nghĩa của phép so vào một tiền tố chuỗi: đổi `ten_kho_vector`
    thành một tiền tố khác mà quên chỗ suy thì mọi ca không khóa báo lệch giả,
    và hai chỗ ấy không có gì nối chúng với nhau. Kho tự khai thì chúng đi cùng
    một mảnh code.

    Không khai là lỗi, không phải một mặc định - xem `ReconcileStoreContractMissing`.
    """
    gia_tri = getattr(storage, TEN_VANG_MO_HO, None)
    if not isinstance(gia_tri, bool):
        raise ReconcileStoreContractMissing(
            f"kho {ten_kho!r} ({type(storage).__name__}) không khai"
            f" `{TEN_VANG_MO_HO}`: bước đối chiếu không đoán được 'vắng' của nó"
            " là chưa từng ghi hay là đã hợp nhất ra không khóa"
        )
    return gia_tri


def _kha_nang(bao_cao, mo_ho: bool) -> set:
    """Tập trạng thái mà báo cáo của một kho còn cho phép.

    Kho khai `VANG_LA_MO_HO = True` (kho vector) thì "vắng" của nó có thể là
    một trong hai: point bị xóa vì hợp nhất ra không khóa trông y hệt point
    chưa từng ghi. Hai kho kia khai False - node graph và bản ghi KV ở lại với
    khóa `null`, nên "vắng" của chúng đúng là chưa từng ghi.
    """
    if mo_ho and bao_cao is CHUA_GHI:
        return {CHUA_GHI, KHONG_KHOA}
    return {bao_cao}


async def tim_lech(so: SoDot, *, kho: Mapping[str, object]) -> list[CapLech]:
    """Danh sách id mà các kho của đợt không nói cùng một khóa.

    Đọc theo lô một lần cho mỗi kho chứ không một lời gọi cho mỗi id: bước này
    chạy cuối mọi đợt ingest, và "rẻ tới mức không đáng tắt" là một yêu cầu
    thiết kế của chính nó.

    Hai loại lệch, và loại thứ hai là loại dễ mất nhất:

    1. **Khóa không khớp** - các kho có id đó nói hai giá trị không dung hòa
       được;
    2. **Kho kỳ vọng vắng mặt hẳn** - đợt khai sẽ ghi id này vào hai kho mà chỉ
       một kho có nó trong sổ. Không có nhánh này thì phép giao chạy trên đúng
       một tập và không bao giờ rỗng, nên một id trượt hẳn ở kho thứ hai là một
       đợt "xanh". Ở đây không cần id nội bộ của kho vắng để kết luận - chính
       việc nó vắng đã là câu trả lời - nên vẫn không phải dựng lại phép băm
       `compute_mdhash_id` mà upstream giữ.
    """
    theo_kho: dict[str, dict[str, str]] = {}
    for id_join in so.cac_id():
        for ten_kho, id_trong_kho in so.kho_cua(id_join).items():
            theo_kho.setdefault(ten_kho, {})[id_join] = id_trong_kho

    khoa_doc: dict[str, dict[str, object]] = {}
    mo_ho: dict[str, bool] = {}
    for ten_kho, theo_id in theo_kho.items():
        storage = kho.get(ten_kho)
        if storage is None:
            raise ReconcileStoreMissing(
                f"đợt có ghi vào kho {ten_kho!r} nhưng bước đối chiếu không được"
                " đưa kho đó: không đối chiếu nửa vời"
            )
        # Hỏi hợp đồng trước khi đọc dữ liệu: một kho không khai thì cả bước
        # này dừng, chứ không đọc xong rồi mới phát hiện không diễn giải được.
        mo_ho[ten_kho] = vang_la_mo_ho(storage, ten_kho)
        khoa_doc[ten_kho] = await storage.khoa_hien_co(sorted(set(theo_id.values())))

    lech: list[CapLech] = []
    for id_join in so.cac_id():
        bao_cao: dict[str, str] = {}
        con_lai: set | None = None
        for ten_kho, id_trong_kho in sorted(so.kho_cua(id_join).items()):
            gia_tri = khoa_doc[ten_kho].get(id_trong_kho, CHUA_GHI)
            bao_cao[ten_kho] = _mo_ta(gia_tri)
            kha_nang = _kha_nang(gia_tri, mo_ho[ten_kho])
            con_lai = kha_nang if con_lai is None else con_lai & kha_nang
        thieu = so.kho_thieu(id_join)
        for ten_kho in sorted(thieu):
            bao_cao[ten_kho] = "không có trong đợt"
        if thieu or not con_lai:
            lech.append(CapLech(id_join=id_join, bao_cao=bao_cao))
    return lech


async def doi_chieu_dot(so: SoDot, *, kho: Mapping[str, object]) -> None:
    """Đối chiếu cuối đợt; lệch là `StoreKeyMismatch` kèm danh sách cặp id."""
    lech = await tim_lech(so, kho=kho)
    if not lech:
        return
    raise StoreKeyMismatch(
        f"khóa quyền lệch giữa các kho ở {len(lech)}/{len(so)} id của đợt:\n"
        + "\n".join(f"  {cap}" for cap in lech)
    )
