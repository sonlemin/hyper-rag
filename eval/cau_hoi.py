"""Bộ 52 câu, bộ vàng 30 câu và nhãn truy hồi vàng: lược đồ, loader, trần lý thuyết.

Story 2.9, mẫu số của Đo 2 (PRD 5.2) và Đo 3 (PRD 5.3). Ba file dữ liệu, một
loader, cùng khuôn mà story 2.5 đặt cho bộ vàng trích xuất: lớp lỗi gom mọi
thông điệp rồi ném một lần, dataclass frozen, `doc_*` là điểm vào.

- `eval/anh_do_thi/synth.json` - ảnh chụp đồ thị `synth`, do `eval/chup_do_thi.py`
  ghi. **Nguồn chuẩn của mọi id hyperedge.**
- `eval/bo_cau_hoi.json` - 52 câu theo phân bố PRD mục 5, mỗi câu một vai người
  hỏi. Bộ vàng 30 câu là **cờ `bo_vang` trên chính câu**, không phải một file
  thứ hai: hai file là hai chỗ để lệch nhau về việc câu nào có đáp án tay.
- `eval/nhan_truy_hoi_vang.json` - nhãn cho 22 câu N3 + N5.

Bốn điều quyết định mọi thứ ở đây:

- **Nhãn không lọc theo mức tiết lộ.** Mức tiết lộ là biến duy nhất của Đo 3;
  lọc nhãn theo nó thì cả bốn cấu hình đều ra recall 100% và phép đo mất nghĩa.
  Nhãn tay trả lời một câu hỏi ngữ nghĩa: fact nào trong đồ thị trả lời được
  câu này. Ai thấy được fact đó là việc của bảng chính sách.
- **Trần lý thuyết là phép tính, không phải nhãn tay.** Nó suy được từ
  `scope`/`content_type` của hyperedge cộng bảng chính sách, nên gán tay là
  chép lại một phép tính rồi để hai bản lệch nhau. `tran_theo_vai()` tính nó,
  không ai lưu nó.
- **Neo hai lớp.** Mỗi cặp câu-hyperedge mang cả `id` của ảnh chụp lẫn neo mô
  tả (`doc_key` + `neo_subject`). Id là thứ harness dùng; neo mô tả là thứ cứu
  được nhãn khi một lần re-ingest đổi id. Id trôi mà neo còn khớp là một *cảnh
  báo có tên câu*, không phải một nhãn chết im lặng.
- **Luật một-một**, cùng luật mà 2.5 đặt cho bộ vàng và 2.8 đặt cho corpus: mọi
  câu N3/N5 có nhãn, không câu nào ngoài N3/N5 có nhãn, mọi id trong nhãn tồn
  tại trong ảnh chụp, mọi `slot_dap_an` là một vai mà chính hyperedge đó có
  điền. Lệch một chiều nào cũng là `uv run pytest` đỏ.

Module thuần: đọc file trên đĩa, không chạm kho, không gọi LLM, không tốn tiền.
Chỉ import `core/`, `adapters/` (seed danh tính, bảng chính sách) và
`eval.bo_vang` (luật chuẩn hóa chuỗi so sánh), không import `api/` (import-lint).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

import yaml

from adapters.identity_seed import IdentitySeedInvalid, nap_danh_tinh
from adapters.policy_loader import load_policy
from core.facts import cau_fact
from core.keys import split_key
from core.policy import Policy, PolicyInvalid
from core.slots import SLOT_ROLES, SLOT_ROLE_SET
from eval.bo_vang import chuan_so_sanh

_GOC = Path(__file__).resolve().parent

DUONG_DAN_ANH_MAC_DINH: Path = _GOC / "anh_do_thi" / "synth.json"
DUONG_DAN_BO_CAU_HOI_MAC_DINH: Path = _GOC / "bo_cau_hoi.json"
DUONG_DAN_NHAN_MAC_DINH: Path = _GOC / "nhan_truy_hoi_vang.json"
DUONG_DAN_CORPUS_THIET_KE: Path = _GOC / "corpus_thiet_ke.yaml"
POLICY_MAC_DINH: Path = _GOC.parent / "config" / "policy-toi-gian.yaml"

# Ba lược đồ độc lập, ba hằng (vòng review 03/09): ép chung một số thì nâng
# version của riêng ảnh chụp làm hai file kia đỏ, dù chúng không đổi một chữ.
VERSION_ANH: int = 2
VERSION_BO_CAU_HOI: int = 1
VERSION_NHAN: int = 1

# Phân bố 7 nhóm của PRD mục 5, khóa cứng. Đây là con số mà chương 4 báo cáo
# phân rã theo nhóm; một nhóm lệch một câu là một tỉ lệ sai ở bảng kết quả.
PHAN_BO: Mapping[str, int] = MappingProxyType(
    {"N1": 6, "N2": 8, "N3": 12, "N4": 5, "N5": 10, "N6": 5, "N7": 6}
)
NHOM: tuple[str, ...] = tuple(PHAN_BO)
TONG_CAU: int = sum(PHAN_BO.values())

# Bộ vàng của Đo 2: 30 câu, chứa **trọn** N7 (tiêu chí từ chối của PRD 5.2 cần
# đủ 6 câu làm mẫu số), sáu nhóm còn lại đều có ít nhất một câu.
SO_CAU_BO_VANG: int = 30
NHOM_TU_CHOI: str = "N7"

# Hai nhóm mang phát biểu của Đo 3 (PRD 2.6): chỉ chúng có nhãn truy hồi vàng.
# 30 câu còn lại cố ý không gán, tiết kiệm công T2.
NHOM_CO_NHAN: tuple[str, ...] = ("N3", "N5")

# Id câu phải đọc ra nhóm: `n3-04` là câu N3. Một id tự do là một id mà bảng
# phân rã theo nhóm phải tra ngược, và là chỗ để một câu N5 mang id `n3-…`.
MAU_ID_CAU = re.compile(r"^n[1-7]-\d{2}$")

KHOA_GOC_ANH: frozenset[str] = frozenset(
    {
        "version",
        "space",
        "ngay_do",
        "policy_version",
        "so_tai_lieu",
        "so_hyperedge",
        "so_hyperedge_da_nguon",
        "tai_lieu",
        "hyperedge",
    }
)
KHOA_TAI_LIEU_ANH: frozenset[str] = frozenset({"doc_key", "sha256", "scope", "content_type"})
KHOA_HYPEREDGE_ANH: frozenset[str] = frozenset({"id", "doc_key", "khoa", "slots"})
KHOA_GOC_CAU: frozenset[str] = frozenset({"version", "cau"})
KHOA_CAU: frozenset[str] = frozenset(
    {
        "id",
        "nhom",
        "cau_hoi",
        "vai_hoi",
        "kich_ban",
        "bo_vang",
        "dap_an",
        "y_chinh",
        "neo_loai",
        "han_che",
    }
)

# Vùng khóa lọc mà đáp án của một câu N7 *sẽ* nằm nếu nó có thật. Không suy được
# từ nhãn (N7 cố ý không có nhãn), nên khai tay - và nhờ khai mà kiểm được bằng
# máy rằng câu N7 từ chối vì **thiếu thông tin** chứ không vì bị chặn quyền, đúng
# hai đường mà FR-16 tách ra. Nhóm khác để rỗng: vùng của chúng suy từ nhãn.
#
# Danh mục **đóng** các dấu hạn chế. Chúng không phải ghi chú tự do: `kiem_danh_dau`
# tính lại đúng hai tập này từ bảng chính sách cộng nhãn và bắt chúng khớp từng
# id, nên một dấu thừa hay thiếu là `uv run pytest` đỏ.
HAN_CHE_N7_QUA_XAC_DINH: str = "n7_qua_xac_dinh"
HAN_CHE_VAI_HOI_KHONG_THAY: str = "vai_hoi_khong_thay"
HAN_CHE: tuple[str, ...] = (HAN_CHE_N7_QUA_XAC_DINH, HAN_CHE_VAI_HOI_KHONG_THAY)
KHOA_GOC_NHAN: frozenset[str] = frozenset({"version", "nhan"})
KHOA_NHAN: frozenset[str] = frozenset({"cau_id", "hyperedge"})
KHOA_HYPEREDGE_NHAN: frozenset[str] = frozenset(
    {"id", "doc_key", "neo_subject", "slot_dap_an"}
)


class _GomLoi(ValueError):
    """Khuôn chung: gom hết lỗi rồi ném một lần, `code` ổn định để test bắt.

    Người sửa dữ liệu phải thấy toàn bộ danh sách trong một lượt chạy, không
    sửa một dòng rồi chạy lại để lộ ra dòng kế (luật của `eval/bo_vang.py`).
    """

    code = "DU_LIEU_KHONG_HOP_LE"
    tieu_de = "dữ liệu không hợp lệ"

    def __init__(self, loi: Sequence[str]):
        self.loi: tuple[str, ...] = tuple(loi)
        super().__init__(f"{self.tieu_de}:\n- " + "\n- ".join(self.loi))


class AnhDoThiKhongHopLe(_GomLoi):
    """Ảnh chụp đồ thị không dùng được làm nguồn chuẩn của id."""

    code = "ANH_DO_THI_KHONG_HOP_LE"
    tieu_de = "ảnh chụp đồ thị không hợp lệ"


class AnhDoThiRong(AnhDoThiKhongHopLe):
    """Ảnh chụp không có hyperedge nào: space chưa nạp, hoặc sai thư mục làm việc."""

    code = "ANH_DO_THI_RONG"
    tieu_de = "ảnh chụp đồ thị rỗng"

    def __init__(self, thong_diep: str):
        super().__init__([thong_diep])


class BoCauHoiKhongHopLe(_GomLoi):
    """Bộ câu hỏi không dùng được làm mẫu số của Đo 2."""

    code = "BO_CAU_HOI_KHONG_HOP_LE"
    tieu_de = "bộ câu hỏi không hợp lệ"


class NhanKhongHopLe(_GomLoi):
    """Nhãn truy hồi vàng sai lược đồ, sai luật một-một, hoặc trỏ id không có."""

    code = "NHAN_KHONG_HOP_LE"
    tieu_de = "nhãn truy hồi vàng không hợp lệ"


class NhanTroiId(_GomLoi):
    """Id hyperedge của nhãn đã trôi khỏi ảnh chụp, nhưng neo mô tả còn nói được gì đó.

    Tách khỏi `NhanKhongHopLe` vì hai thứ này đòi hai việc khác nhau: một nhãn
    sai lược đồ thì sửa nhãn, còn một id trôi thì phải quyết xem đồ thị mới có
    còn kể cùng một sự thật không. Loader **không tự sửa file**: nó nêu câu, id
    cũ và id mới đề xuất, rồi để người soát quyết.
    """

    code = "NHAN_TROI_ID"
    tieu_de = "nhãn truy hồi vàng có id đã trôi"


# --------------------------------------------------------------------------
# Ảnh chụp đồ thị
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HyperedgeAnh:
    """Một hyperedge trong ảnh chụp: id, các tài liệu nguồn, khóa lọc, slot."""

    id: str
    doc_key: tuple[str, ...]
    khoa: str | None
    slots: Mapping[str, tuple[str, ...]]

    def __post_init__(self):
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))

    @property
    def scope(self) -> str | None:
        """Scope suy từ khóa lọc; `None` khi hyperedge không mang khóa (AD-5)."""
        return None if self.khoa is None else split_key(self.khoa)[0]

    @property
    def content_type(self) -> str | None:
        return None if self.khoa is None else split_key(self.khoa)[1]

    @property
    def da_nguon(self) -> bool:
        return len(self.doc_key) > 1

    def chu_the(self) -> tuple[str, ...]:
        return self.slots.get("subject", ())

    def cau(self) -> str:
        """Câu render của fact, đúng hàm mà pipeline dùng để nhúng point hyperedge."""
        return cau_fact(self.slots)


@dataclass(frozen=True)
class TaiLieuAnh:
    """Một tài liệu trong sổ tại thời điểm chụp: đủ để đối chiếu với thư mục nguồn.

    `sha256` là băm **thân** tài liệu (sau khi tách frontmatter), đúng thứ
    `adapters.ingest` ghi vào sổ để nhận ra "không đổi". Nó là dấu vết xuất xứ
    thật của ảnh chụp: sửa một chữ trong `eval/corpus/` mà quên chụp lại thì
    `tests/test_bo_cau_hoi.py` đỏ, chứ không phải chờ tới lúc một nhãn chết.
    """

    doc_key: str
    sha256: str
    scope: str
    content_type: str


@dataclass(frozen=True)
class AnhDoThi:
    """Ảnh chụp đã kiểm. Chỉ dữ liệu, không luật chấm nào."""

    version: int
    space: str
    ngay_do: str
    policy_version: str
    tai_lieu: tuple[TaiLieuAnh, ...]
    hyperedge: tuple[HyperedgeAnh, ...]

    @property
    def so_hyperedge(self) -> int:
        return len(self.hyperedge)

    @property
    def so_tai_lieu(self) -> int:
        return len(self.tai_lieu)

    @property
    def doc_key(self) -> frozenset[str]:
        """Tập `doc_key` của sổ tài liệu tại thời điểm chụp."""
        return frozenset(t.doc_key for t in self.tai_lieu)

    @property
    def theo_id(self) -> Mapping[str, HyperedgeAnh]:
        return MappingProxyType({h.id: h for h in self.hyperedge})

    def da_nguon(self) -> tuple[HyperedgeAnh, ...]:
        """Hyperedge có `source_id` gộp từ hai tài liệu trở lên (ca FR-11 mức fact)."""
        return tuple(h for h in self.hyperedge if h.da_nguon)

    def tim_theo_neo(self, doc_key: str, neo_subject: str) -> tuple[HyperedgeAnh, ...]:
        """Hyperedge khớp neo mô tả: đúng tài liệu, và `subject` khớp `neo_subject`.

        So sau khi NFC, gộp khoảng trắng và `casefold()` - cùng luật với phép so
        nhãn của bộ vàng trích xuất, nên một neo viết hoa chữ đầu vẫn khớp còn
        một neo viết lại chữ thì không.

        **Khớp bằng trước, khớp chứa sau.** Một tài liệu thường có nhiều fact
        cùng chủ thể ngắn ("App01") cạnh một fact chủ thể dài hơn chứa nó
        ("trang thanh toán của App01"): khớp chứa thuần thì neo ngắn luôn mơ hồ,
        còn khớp bằng thuần thì người soát phải chép nguyên văn một giá trị mà
        LLM sinh ra. Nên neo trùng *đúng* một giá trị `subject` thì chỉ những
        hyperedge đó là ứng viên; không trùng đúng cái nào thì mới nới sang khớp
        chứa. Ràng buộc "đúng một ứng viên" của loader là thứ giữ cho phép nới
        đó không thành mơ hồ.
        """
        can = chuan_so_sanh(neo_subject)
        if not can:
            return ()
        cua_tai_lieu = [h for h in self.hyperedge if doc_key in h.doc_key]
        bang = tuple(
            h for h in cua_tai_lieu if any(can == chuan_so_sanh(c) for c in h.chu_the())
        )
        if bang:
            return bang
        return tuple(
            h for h in cua_tai_lieu if any(can in chuan_so_sanh(c) for c in h.chu_the())
        )


def doc_anh_do_thi(duong_dan: str | Path | None = None) -> AnhDoThi:
    """Đọc và kiểm ảnh chụp; mọi cách hỏng là `AnhDoThiKhongHopLe` ném một lần."""
    duong_dan = Path(duong_dan) if duong_dan is not None else DUONG_DAN_ANH_MAC_DINH
    raw = _doc_json(duong_dan, AnhDoThiKhongHopLe)

    loi: list[str] = []
    if not isinstance(raw, dict):
        raise AnhDoThiKhongHopLe([f"{duong_dan}: gốc file phải là một object"])
    _khoa_dung(raw, KHOA_GOC_ANH, f"{duong_dan} cấp gốc", loi)
    if raw.get("version") != VERSION_ANH:
        loi.append(f"version phải là {VERSION_ANH}, nhận được {raw.get('version')!r}")
    space = raw.get("space")
    if not isinstance(space, str) or not space.strip():
        loi.append("`space` phải là chuỗi không rỗng")
        space = "?"
    chuoi = {"ngay_do": "", "policy_version": ""}
    for khoa in chuoi:
        gia_tri = raw.get(khoa)
        if not isinstance(gia_tri, str) or not gia_tri.strip():
            loi.append(f"`{khoa}` phải là chuỗi không rỗng")
        else:
            chuoi[khoa] = gia_tri
    cac_tai_lieu = _dung_tai_lieu_anh(raw.get("tai_lieu"), loi)
    if raw.get("so_tai_lieu") != len(cac_tai_lieu):
        loi.append(
            f"`so_tai_lieu` = {raw.get('so_tai_lieu')!r} không khớp"
            f" {len(cac_tai_lieu)} mục thật trong `tai_lieu`"
        )
    danh_sach = raw.get("hyperedge")
    if not isinstance(danh_sach, list):
        loi.append("`hyperedge` phải là một danh sách")
        raise AnhDoThiKhongHopLe(loi)
    if not danh_sach:
        raise AnhDoThiRong(
            f"ảnh chụp {duong_dan} khai space {space!r} với 0 hyperedge:"
            " space chưa nạp, hoặc `HYPER_RAG_WORKING_DIR` trỏ sai sổ tài liệu"
        )

    cac_he = _dung_hyperedge_anh(danh_sach, loi)
    if raw.get("so_hyperedge") != len(danh_sach):
        loi.append(
            f"`so_hyperedge` = {raw.get('so_hyperedge')!r} không khớp"
            f" {len(danh_sach)} mục thật trong `hyperedge`"
        )
    da_nguon = sum(1 for h in danh_sach if isinstance(h, dict) and isinstance(h.get("doc_key"), list) and len(h["doc_key"]) > 1)
    if raw.get("so_hyperedge_da_nguon") != da_nguon:
        loi.append(
            f"`so_hyperedge_da_nguon` = {raw.get('so_hyperedge_da_nguon')!r}"
            f" không khớp {da_nguon} mục thật"
        )
    thieu_so = sorted({d for h in cac_he for d in h.doc_key} - {t.doc_key for t in cac_tai_lieu})
    if thieu_so:
        loi.append(
            f"hyperedge dẫn `doc_key` không có trong `tai_lieu`: {thieu_so}"
            " - ảnh chụp tự mâu thuẫn, hai nửa đến từ hai lần đọc sổ khác nhau"
        )
    if loi:
        raise AnhDoThiKhongHopLe(loi)
    return AnhDoThi(
        version=raw["version"],
        space=space,
        ngay_do=chuoi["ngay_do"],
        policy_version=chuoi["policy_version"],
        tai_lieu=tuple(cac_tai_lieu),
        hyperedge=tuple(cac_he),
    )


def _dung_tai_lieu_anh(danh_sach, loi: list[str]) -> list[TaiLieuAnh]:
    """Sổ tài liệu tại thời điểm chụp, đã kiểm hình dạng và không trùng `doc_key`."""
    if not isinstance(danh_sach, list) or not danh_sach:
        loi.append("`tai_lieu` phải là một danh sách không rỗng")
        return []
    ra: list[TaiLieuAnh] = []
    da_thay: set[str] = set()
    for i, muc in enumerate(danh_sach):
        cho = f"tài liệu thứ {i}"
        if not isinstance(muc, dict):
            loi.append(f"{cho} phải là một object, nhận được {type(muc).__name__}")
            continue
        if isinstance(muc.get("doc_key"), str) and muc["doc_key"].strip():
            cho = muc["doc_key"]
        if not _khoa_dung(muc, KHOA_TAI_LIEU_ANH, cho, loi):
            continue
        sai = [k for k in sorted(KHOA_TAI_LIEU_ANH) if not isinstance(muc[k], str) or not muc[k].strip()]
        if sai:
            loi.append(f"{cho}: phải là chuỗi không rỗng - {sai}")
            continue
        if muc["doc_key"] in da_thay:
            loi.append(f"{cho}: doc_key khai hai lần trong ảnh chụp")
            continue
        da_thay.add(muc["doc_key"])
        ra.append(TaiLieuAnh(**{k: muc[k] for k in KHOA_TAI_LIEU_ANH}))
    return ra


def _dung_hyperedge_anh(danh_sach: Iterable, loi: list[str]) -> list[HyperedgeAnh]:
    ra: list[HyperedgeAnh] = []
    da_thay: set[str] = set()
    for i, muc in enumerate(danh_sach):
        cho = f"hyperedge thứ {i}"
        if not isinstance(muc, dict):
            loi.append(f"{cho} phải là một object, nhận được {type(muc).__name__}")
            continue
        id_he = muc.get("id")
        if isinstance(id_he, str) and id_he.strip():
            cho = id_he
        if not _khoa_dung(muc, KHOA_HYPEREDGE_ANH, cho, loi):
            continue
        if not isinstance(id_he, str) or not id_he.strip():
            loi.append(f"{cho}: `id` phải là chuỗi không rỗng")
            continue
        if id_he in da_thay:
            loi.append(f"{id_he}: id khai hai lần trong ảnh chụp")
            continue
        da_thay.add(id_he)
        doc_key = muc["doc_key"]
        if not isinstance(doc_key, list) or not doc_key or not all(
            isinstance(d, str) and d.strip() for d in doc_key
        ):
            loi.append(f"{id_he}: `doc_key` phải là danh sách tên tài liệu không rỗng")
            continue
        khoa = muc["khoa"]
        if khoa is not None:
            if not isinstance(khoa, str):
                loi.append(f"{id_he}: `khoa` phải là chuỗi hoặc null")
                continue
            try:
                split_key(khoa)
            except (TypeError, ValueError) as e:
                loi.append(f"{id_he}: khóa lọc {khoa!r} không đúng dạng scope:content_type ({e})")
                continue
        slots = muc["slots"]
        if not isinstance(slots, dict) or not slots:
            loi.append(f"{id_he}: `slots` phải là một object không rỗng")
            continue
        vai_la = sorted(set(slots) - SLOT_ROLE_SET)
        if vai_la:
            loi.append(
                f"{id_he}: vai ngoài danh mục 8 vai {vai_la}, danh mục là {list(SLOT_ROLES)}"
            )
            continue
        if not all(
            isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v)
            for v in slots.values()
        ):
            loi.append(f"{id_he}: mỗi vai phải mang một danh sách chuỗi không rỗng")
            continue
        if not slots.get("subject"):
            loi.append(f"{id_he}: thiếu vai `subject` - lược đồ fact bắt buộc nó")
            continue
        ra.append(
            HyperedgeAnh(
                id=id_he,
                doc_key=tuple(sorted(doc_key)),
                khoa=khoa,
                slots={vai: tuple(slots[vai]) for vai in SLOT_ROLES if vai in slots},
            )
        )
    return ra


# --------------------------------------------------------------------------
# Bộ câu hỏi
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CauHoi:
    """Một câu hỏi. `bo_vang` bật thì `dap_an` và `y_chinh` bắt buộc, và ngược lại."""

    id: str
    nhom: str
    cau_hoi: str
    vai_hoi: str
    kich_ban: str
    bo_vang: bool
    dap_an: str
    y_chinh: tuple[str, ...]
    neo_loai: tuple[str, ...]
    han_che: tuple[str, ...]

    @property
    def co_nhan(self) -> bool:
        """Câu này có nhãn truy hồi vàng không (chỉ N3 và N5, PRD 2.6)."""
        return self.nhom in NHOM_CO_NHAN


@dataclass(frozen=True)
class BoCauHoi:
    version: int
    cau: tuple[CauHoi, ...]

    @property
    def theo_id(self) -> Mapping[str, CauHoi]:
        return MappingProxyType({c.id: c for c in self.cau})

    def theo_nhom(self) -> Mapping[str, tuple[CauHoi, ...]]:
        """Câu theo nhóm, đủ 7 khóa kể cả nhóm rỗng (hàng của bảng phân rã 5.2)."""
        return MappingProxyType(
            {nhom: tuple(c for c in self.cau if c.nhom == nhom) for nhom in NHOM}
        )

    def bo_vang(self) -> tuple[CauHoi, ...]:
        return tuple(c for c in self.cau if c.bo_vang)

    def cau_co_nhan(self) -> tuple[CauHoi, ...]:
        return tuple(c for c in self.cau if c.co_nhan)

    def theo_vai(self) -> Mapping[str, tuple[CauHoi, ...]]:
        vai = sorted({c.vai_hoi for c in self.cau})
        return MappingProxyType({v: tuple(c for c in self.cau if c.vai_hoi == v) for v in vai})


def vai_cua_seed(path: str | Path | None = None) -> set[str]:
    """Tập vai người hỏi hợp lệ, đọc từ `config/danh-tinh-demo.yaml`.

    Vai đo của Đo 3 và vai người hỏi của bộ câu là **một** danh mục: một câu gắn
    vai không có danh tính nào là một câu không ai hỏi được ở T7.
    """
    return {dt.vai for dt in nap_danh_tinh(path)}


def kich_ban_cua_corpus(path: str | Path | None = None) -> set[str]:
    """Tập id kịch bản khai trong `eval/corpus_thiet_ke.yaml` (nguồn chuẩn của 2.8)."""
    duong_dan = Path(path) if path is not None else DUONG_DAN_CORPUS_THIET_KE
    raw = yaml.safe_load(duong_dan.read_text(encoding="utf-8"))
    return {k["id"] for k in raw["kich_ban"]}


def doc_bo_cau_hoi(duong_dan: str | Path | None = None) -> BoCauHoi:
    """Đọc và kiểm bộ câu hỏi; mọi cách hỏng là `BoCauHoiKhongHopLe` ném một lần."""
    duong_dan = (
        Path(duong_dan) if duong_dan is not None else DUONG_DAN_BO_CAU_HOI_MAC_DINH
    )
    raw = _doc_json(duong_dan, BoCauHoiKhongHopLe)

    loi: list[str] = []
    if not isinstance(raw, dict):
        raise BoCauHoiKhongHopLe([f"{duong_dan}: gốc file phải là một object"])
    _khoa_dung(raw, KHOA_GOC_CAU, f"{duong_dan} cấp gốc", loi)
    if raw.get("version") != VERSION_BO_CAU_HOI:
        loi.append(f"version phải là {VERSION_BO_CAU_HOI}, nhận được {raw.get('version')!r}")
    danh_sach = raw.get("cau")
    if not isinstance(danh_sach, list) or not danh_sach:
        loi.append("`cau` phải là một danh sách không rỗng")
        raise BoCauHoiKhongHopLe(loi)

    try:
        vai_hop_le = vai_cua_seed()
    except IdentitySeedInvalid as e:
        loi.append(f"không nạp được seed danh tính để kiểm vai người hỏi: {e}")
        vai_hop_le = None
    try:
        kich_ban_hop_le = kich_ban_cua_corpus()
    except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
        loi.append(f"không đọc được bảng thiết kế corpus để kiểm kịch bản: {e}")
        kich_ban_hop_le = None

    cau = _dung_cau_hoi(danh_sach, vai_hop_le, kich_ban_hop_le, loi)
    _kiem_toan_bo_cau(cau, loi)
    if loi:
        raise BoCauHoiKhongHopLe(loi)
    return BoCauHoi(version=raw["version"], cau=tuple(cau))


def _dung_cau_hoi(danh_sach, vai_hop_le, kich_ban_hop_le, loi: list[str]) -> list[CauHoi]:
    ra: list[CauHoi] = []
    da_thay: set[str] = set()
    for i, muc in enumerate(danh_sach):
        cho = f"câu thứ {i}"
        if not isinstance(muc, dict):
            loi.append(f"{cho} phải là một object, nhận được {type(muc).__name__}")
            continue
        id_cau = muc.get("id")
        if isinstance(id_cau, str) and id_cau.strip():
            cho = id_cau
        if not _khoa_dung(muc, KHOA_CAU, cho, loi):
            continue
        if not isinstance(id_cau, str) or not MAU_ID_CAU.match(id_cau):
            loi.append(f"{cho}: `id` phải có dạng `n<nhóm>-<hai chữ số>`, ví dụ `n3-04`")
            continue
        if id_cau in da_thay:
            loi.append(f"{id_cau}: id câu khai hai lần")
            continue
        da_thay.add(id_cau)
        nhom = muc["nhom"]
        if nhom not in NHOM:
            loi.append(f"{id_cau}: nhóm {nhom!r} ngoài 7 nhóm {list(NHOM)}")
            continue
        if not id_cau.startswith(nhom.lower() + "-"):
            loi.append(f"{id_cau}: id không đọc ra nhóm {nhom!r}")
            continue
        sai_kieu = [
            k for k in ("cau_hoi", "vai_hoi", "kich_ban")
            if not isinstance(muc[k], str) or not muc[k].strip()
        ]
        if sai_kieu:
            loi.append(f"{id_cau}: phải là chuỗi không rỗng - {sai_kieu}")
            continue
        if vai_hop_le is not None and muc["vai_hoi"] not in vai_hop_le:
            loi.append(
                f"{id_cau}: vai người hỏi {muc['vai_hoi']!r} không có trong seed"
                f" danh tính, các vai khai được là {sorted(vai_hop_le)}"
            )
            continue
        if kich_ban_hop_le is not None and muc["kich_ban"] not in kich_ban_hop_le:
            loi.append(
                f"{id_cau}: kịch bản {muc['kich_ban']!r} không có trong bảng thiết kế"
                f" corpus, các kịch bản khai được là {sorted(kich_ban_hop_le)}"
            )
            continue
        if not isinstance(muc["bo_vang"], bool):
            # `"false"` là chuỗi truthy: không kiểm kiểu thì một câu lặng lẽ vào
            # mẫu số của Đo 2 mà không ai thấy.
            loi.append(f"{id_cau}: `bo_vang` phải là true/false, nhận được {muc['bo_vang']!r}")
            continue
        dap_an = muc["dap_an"]
        y_chinh = muc["y_chinh"]
        if not isinstance(dap_an, str):
            loi.append(f"{id_cau}: `dap_an` phải là chuỗi")
            continue
        if not isinstance(y_chinh, list) or not all(
            isinstance(y, str) and y.strip() for y in y_chinh
        ):
            loi.append(f"{id_cau}: `y_chinh` phải là danh sách chuỗi không rỗng")
            continue
        if muc["bo_vang"]:
            if not dap_an.strip():
                loi.append(f"{id_cau}: câu bộ vàng phải có `dap_an` - đó là mẫu số của Đo 2")
                continue
            if not y_chinh:
                loi.append(
                    f"{id_cau}: câu bộ vàng phải có `y_chinh` - rubric 'đủ ý' của"
                    " PRD 5.2 chấm trên danh sách đó"
                )
                continue
        else:
            if dap_an.strip() or y_chinh:
                loi.append(
                    f"{id_cau}: câu ngoài bộ vàng mang đáp án tay - mẫu số 30 câu"
                    " của Đo 2 nở ra mà không ai thấy; bật `bo_vang` hoặc xóa đáp án"
                )
                continue
        neo_loai = muc["neo_loai"]
        han_che = muc["han_che"]
        if not isinstance(neo_loai, list) or not all(isinstance(x, str) for x in neo_loai):
            loi.append(f"{id_cau}: `neo_loai` phải là danh sách khóa lọc `scope:content_type`")
            continue
        khoa_hong = []
        for khoa in neo_loai:
            try:
                split_key(khoa)
            except (TypeError, ValueError) as e:
                khoa_hong.append(f"{khoa!r} ({e})")
        if khoa_hong:
            loi.append(f"{id_cau}: `neo_loai` không đúng dạng scope:content_type - {khoa_hong}")
            continue
        if (nhom == NHOM_TU_CHOI) != bool(neo_loai):
            loi.append(
                f"{id_cau}: `neo_loai` phải khai cho câu {NHOM_TU_CHOI} và **chỉ** cho"
                f" nhóm đó (nhóm {nhom}, khai {neo_loai}) - vùng của nhóm khác suy từ nhãn"
            )
            continue
        if not isinstance(han_che, list) or not all(isinstance(x, str) for x in han_che):
            loi.append(f"{id_cau}: `han_che` phải là một danh sách chuỗi")
            continue
        la = sorted(set(han_che) - set(HAN_CHE))
        if la or len(set(han_che)) != len(han_che):
            loi.append(
                f"{id_cau}: dấu hạn chế lạ hoặc trùng {han_che}, danh mục là {list(HAN_CHE)}"
            )
            continue
        ra.append(
            CauHoi(
                id=id_cau,
                nhom=nhom,
                cau_hoi=muc["cau_hoi"],
                vai_hoi=muc["vai_hoi"],
                kich_ban=muc["kich_ban"],
                bo_vang=muc["bo_vang"],
                dap_an=dap_an,
                y_chinh=tuple(y_chinh),
                neo_loai=tuple(neo_loai),
                han_che=tuple(han_che),
            )
        )
    return ra


def _kiem_toan_bo_cau(cau: Sequence[CauHoi], loi: list[str]) -> None:
    """Bốn luật ở mức cả bộ: tổng, phân bố, số câu bộ vàng, và phủ nhóm của bộ vàng."""
    if len(cau) != TONG_CAU:
        loi.append(f"bộ câu hỏi phải có đúng {TONG_CAU} câu, nhận được {len(cau)}")
    dem = {nhom: sum(1 for c in cau if c.nhom == nhom) for nhom in NHOM}
    for nhom in NHOM:
        if dem[nhom] != PHAN_BO[nhom]:
            loi.append(
                f"nhóm {nhom} có {dem[nhom]} câu, phân bố PRD mục 5 đòi {PHAN_BO[nhom]}"
            )
    vang = [c for c in cau if c.bo_vang]
    if len(vang) != SO_CAU_BO_VANG:
        loi.append(
            f"bộ vàng có {len(vang)} câu, PRD 2.6 đòi đúng {SO_CAU_BO_VANG}"
        )
    thieu_n7 = [c.id for c in cau if c.nhom == NHOM_TU_CHOI and not c.bo_vang]
    if thieu_n7:
        loi.append(
            f"bộ vàng phải chứa **trọn** {PHAN_BO[NHOM_TU_CHOI]} câu {NHOM_TU_CHOI},"
            f" còn thiếu {sorted(thieu_n7)} - tiêu chí từ chối của Đo 2 mất mẫu số"
        )
    nhom_vang = {c.nhom for c in vang}
    thieu_nhom = [nhom for nhom in NHOM if nhom not in nhom_vang]
    if thieu_nhom:
        loi.append(
            f"nhóm không có câu bộ vàng nào: {thieu_nhom} - PRD 2.6 đòi sáu nhóm"
            " còn lại đều có ít nhất một câu, nếu không bảng phân rã 5.2 có hàng rỗng"
        )


# --------------------------------------------------------------------------
# Nhãn truy hồi vàng
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HyperedgeKyVong:
    """Một hyperedge mà câu hỏi kỳ vọng thấy trong ngữ cảnh, cùng slot mang đáp án."""

    id: str
    doc_key: str
    neo_subject: str
    slot_dap_an: tuple[str, ...]


@dataclass(frozen=True)
class NhanCau:
    cau_id: str
    hyperedge: tuple[HyperedgeKyVong, ...]


@dataclass(frozen=True)
class NhanTruyHoi:
    version: int
    nhan: tuple[NhanCau, ...]

    @property
    def theo_cau(self) -> Mapping[str, NhanCau]:
        return MappingProxyType({n.cau_id: n for n in self.nhan})

    def so_cap(self) -> int:
        """Tổng số cặp câu-hyperedge: mẫu số thô của recall Đo 3."""
        return sum(len(n.hyperedge) for n in self.nhan)


def doc_nhan_truy_hoi(
    duong_dan: str | Path | None = None,
    *,
    bo: BoCauHoi,
    anh: AnhDoThi,
    policy: Policy | None = None,
) -> NhanTruyHoi:
    """Đọc và kiểm nhãn; đối chiếu với bộ câu hỏi và ảnh chụp.

    `bo` và `anh` **bắt buộc**, không có mặc định (vòng review 03/09): một mặc
    định "nạp file thật của repo" làm một nhãn tạm trong `tmp_path` bị chấm bằng
    bộ câu hỏi và ảnh chụp của repo, và lỗi báo ra nói về một file mà người gọi
    không hề truyền vào. Ba nguồn phải đến cùng một chỗ.

    Hai loại lỗi, hai việc phải làm khác nhau: `NhanKhongHopLe` là nhãn sai (sửa
    nhãn), `NhanTroiId` là đồ thị đã đổi (quyết xem đồ thị mới còn kể cùng một
    sự thật không). Lỗi sai lược đồ ném trước, vì đọc một cảnh báo trôi id trên
    một file còn sai lược đồ là đuổi theo triệu chứng.
    """
    duong_dan = Path(duong_dan) if duong_dan is not None else DUONG_DAN_NHAN_MAC_DINH
    raw = _doc_json(duong_dan, NhanKhongHopLe)

    loi: list[str] = []
    troi: list[str] = []
    if not isinstance(raw, dict):
        raise NhanKhongHopLe([f"{duong_dan}: gốc file phải là một object"])
    _khoa_dung(raw, KHOA_GOC_NHAN, f"{duong_dan} cấp gốc", loi)
    if raw.get("version") != VERSION_NHAN:
        loi.append(f"version phải là {VERSION_NHAN}, nhận được {raw.get('version')!r}")
    danh_sach = raw.get("nhan")
    if not isinstance(danh_sach, list) or not danh_sach:
        loi.append("`nhan` phải là một danh sách không rỗng")
        raise NhanKhongHopLe(loi)

    nhan = _dung_nhan(danh_sach, bo, anh, loi, troi)
    _kiem_mot_mot(nhan, bo, loi)
    if loi:
        raise NhanKhongHopLe(loi)
    if troi:
        raise NhanTroiId(troi)
    ket_qua = NhanTruyHoi(version=raw["version"], nhan=tuple(nhan))
    kiem_danh_dau(bo, ket_qua, anh, policy=policy)
    return ket_qua


def _dung_nhan(
    danh_sach, bo: BoCauHoi, anh: AnhDoThi, loi: list[str], troi: list[str]
) -> list[NhanCau]:
    theo_id_cau = bo.theo_id
    theo_id_he = anh.theo_id
    ra: list[NhanCau] = []
    da_thay: set[str] = set()
    for i, muc in enumerate(danh_sach):
        cho = f"nhãn thứ {i}"
        if not isinstance(muc, dict):
            loi.append(f"{cho} phải là một object, nhận được {type(muc).__name__}")
            continue
        cau_id = muc.get("cau_id")
        if isinstance(cau_id, str) and cau_id.strip():
            cho = cau_id
        if not _khoa_dung(muc, KHOA_NHAN, cho, loi):
            continue
        if not isinstance(cau_id, str) or not cau_id.strip():
            loi.append(f"{cho}: `cau_id` phải là chuỗi không rỗng")
            continue
        if cau_id in da_thay:
            loi.append(f"{cau_id}: câu này có hai mục nhãn, gộp chúng lại làm một")
            continue
        da_thay.add(cau_id)
        cau = theo_id_cau.get(cau_id)
        if cau is None:
            loi.append(f"{cau_id}: không có câu nào mang id này trong bộ câu hỏi")
            continue
        if not cau.co_nhan:
            loi.append(
                f"{cau_id}: câu nhóm {cau.nhom} không được gán nhãn truy hồi -"
                f" PRD 2.6 chỉ gán cho {list(NHOM_CO_NHAN)}, phần còn lại cố ý"
                " tiết kiệm công T2"
            )
            continue
        danh_sach_he = muc["hyperedge"]
        if not isinstance(danh_sach_he, list) or not danh_sach_he:
            loi.append(
                f"{cau_id}: `hyperedge` phải là danh sách không rỗng - một câu N3/N5"
                " không kỳ vọng hyperedge nào là một câu không đo được"
            )
            continue
        cac_he = _dung_hyperedge_ky_vong(cau_id, danh_sach_he, theo_id_he, anh, loi, troi)
        ra.append(NhanCau(cau_id=cau_id, hyperedge=tuple(cac_he)))
    return ra


def _dung_hyperedge_ky_vong(
    cau_id: str, danh_sach, theo_id_he, anh: AnhDoThi, loi: list[str], troi: list[str]
) -> list[HyperedgeKyVong]:
    ra: list[HyperedgeKyVong] = []
    da_thay: set[str] = set()
    for j, muc in enumerate(danh_sach):
        cho = f"{cau_id} hyperedge#{j}"
        if not isinstance(muc, dict):
            loi.append(f"{cho} phải là một object, nhận được {type(muc).__name__}")
            continue
        if not _khoa_dung(muc, KHOA_HYPEREDGE_NHAN, cho, loi):
            continue
        sai_kieu = [
            k for k in ("id", "doc_key", "neo_subject")
            if not isinstance(muc[k], str) or not muc[k].strip()
        ]
        if sai_kieu:
            loi.append(f"{cho}: phải là chuỗi không rỗng - {sai_kieu}")
            continue
        id_he = muc["id"]
        if id_he in da_thay:
            loi.append(f"{cho}: id {id_he} khai hai lần cho cùng một câu")
            continue
        da_thay.add(id_he)
        slot = muc["slot_dap_an"]
        if not isinstance(slot, list) or not slot or not all(isinstance(s, str) for s in slot):
            loi.append(
                f"{cho}: `slot_dap_an` phải là danh sách vai không rỗng - lớp"
                " 'recall trả lời được' của PRD 5.3 chấm trên nó"
            )
            continue
        vai_la = sorted(set(slot) - SLOT_ROLE_SET)
        if vai_la:
            loi.append(
                f"{cho}: vai đáp án {vai_la} ngoài danh mục, 8 vai hợp lệ là"
                f" {list(SLOT_ROLES)}"
            )
            continue

        ung_vien = anh.tim_theo_neo(muc["doc_key"], muc["neo_subject"])
        trong_anh = theo_id_he.get(id_he)
        neo = f"{muc['doc_key']} / {muc['neo_subject']!r}"
        if len(ung_vien) > 1:
            troi.append(
                f"{cho}: neo mô tả ({neo}) khớp {len(ung_vien)} hyperedge"
                f" {[h.id for h in ung_vien]} - neo phải xác định đúng một fact,"
                " viết `neo_subject` sát hơn"
            )
        elif not ung_vien:
            if trong_anh is None:
                loi.append(
                    f"{cho}: id {id_he} không có trong ảnh chụp và neo mô tả ({neo})"
                    " cũng không khớp hyperedge nào - nhãn trỏ vào chỗ trống"
                )
                continue
            troi.append(
                f"{cho}: id {id_he} còn trong ảnh chụp nhưng neo mô tả ({neo})"
                " không khớp nó nữa - sửa `doc_key`/`neo_subject` cho khớp fact thật"
            )
        elif ung_vien[0].id != id_he:
            troi.append(
                f"{cho}: id {id_he}"
                f" {'đã trôi khỏi ảnh chụp' if trong_anh is None else 'trỏ một fact khác'},"
                f" neo mô tả ({neo}) chỉ tới {ung_vien[0].id} - id mới đề xuất:"
                f" {ung_vien[0].id}"
            )

        moc = ung_vien[0] if len(ung_vien) == 1 else trong_anh
        if moc is not None:
            thieu = [s for s in slot if s not in moc.slots]
            if thieu:
                loi.append(
                    f"{cho}: hyperedge {moc.id} không điền vai {thieu}, nên không vai"
                    f" nào mang đáp án ở đó; vai đã điền là {list(moc.slots)}"
                )
                continue
        ra.append(
            HyperedgeKyVong(
                id=id_he,
                doc_key=muc["doc_key"],
                neo_subject=muc["neo_subject"],
                slot_dap_an=tuple(slot),
            )
        )
    return ra


def _kiem_mot_mot(nhan: Sequence[NhanCau], bo: BoCauHoi, loi: list[str]) -> None:
    """Luật một-một: đúng tập câu N3/N5 có nhãn, không hơn không kém."""
    co_nhan = {n.cau_id for n in nhan}
    can_nhan = {c.id for c in bo.cau_co_nhan()}
    thieu = sorted(can_nhan - co_nhan)
    if thieu:
        loi.append(
            f"câu {list(NHOM_CO_NHAN)} chưa có nhãn truy hồi: {thieu} - mỗi câu"
            " không nhãn là một lỗ trong mẫu số của Đo 3"
        )


# --------------------------------------------------------------------------
# Trần lý thuyết theo vai
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TranCau:
    """Trần lý thuyết của một câu với một vai, hai lớp recall của PRD 5.3."""

    cau_id: str
    vai: str
    tong: int
    ton_tai: int
    tra_loi_duoc: int
    ly_do: tuple[str, ...]


@dataclass(frozen=True)
class TranVai:
    """Trần lý thuyết của một vai trên toàn bộ nhãn."""

    vai: str
    cau: tuple[TranCau, ...]

    @property
    def tong(self) -> int:
        return sum(c.tong for c in self.cau)

    @property
    def ton_tai(self) -> int:
        return sum(c.ton_tai for c in self.cau)

    @property
    def tra_loi_duoc(self) -> int:
        return sum(c.tra_loi_duoc for c in self.cau)

    def ti_le_ton_tai(self) -> float:
        return self.ton_tai / self.tong if self.tong else 0.0

    def ti_le_tra_loi_duoc(self) -> float:
        return self.tra_loi_duoc / self.tong if self.tong else 0.0

    def canh_bao(self) -> tuple[str, ...]:
        """Câu có trần 0 kèm lý do. **Cảnh báo, không phải lỗi.**

        Hôm nay `config/policy-toi-gian.yaml` mới khai 3 trong 13 loại nội dung
        và không vai nào chạm `khach_hang_b`, nên nhiều câu có trần 0. Đó là
        trạng thái fail-closed đúng cho tới story 3.2; coi nó là lỗi thì bộ test
        đỏ vì một việc chưa tới lượt làm.
        """
        ra = []
        for c in self.cau:
            if c.ton_tai == 0:
                nhan = "trần 0"
            elif c.tra_loi_duoc < c.ton_tai:
                # Ca L1 của Đo 3: hyperedge vào được ngữ cảnh mà slot mang đáp
                # án bị che. Bỏ nó khỏi khối cảnh báo là để người soát đọc bảng
                # tổng rồi tưởng ba câu mang đúng luận điểm L1 là lành.
                nhan = f"mất lớp trả lời được ({c.tra_loi_duoc}/{c.ton_tai})"
            else:
                continue
            ra.append(f"{c.cau_id}: {nhan} với vai {c.vai} - " + "; ".join(c.ly_do))
        return tuple(ra)

    def cau_tran_khong(self) -> tuple[TranCau, ...]:
        """Chỉ những câu mất sạch lớp tồn tại - con số in ở bảng tổng."""
        return tuple(c for c in self.cau if c.ton_tai == 0)


def _hang_cua_vai(policy: Policy, ten_vai: str):
    try:
        return policy.role(ten_vai)
    except KeyError:
        raise PolicyInvalid(
            f"vai {ten_vai!r} có trong seed danh tính mà không có trong bảng"
            " chính sách: trần lý thuyết của nó không tính được"
        ) from None


def _tran_mot_cau(hang, n: NhanCau, theo_id_he) -> TranCau:
    """Trần của một câu với một vai. Một bản duy nhất cho cả hai bảng trần.

    Hai lớp, đúng hai định nghĩa của PRD 5.3:

    - **tồn tại** - hyperedge vào được ngữ cảnh của vai: khóa lọc nằm trong
      `allowed_keys['hyperedges']`, tức scope thuộc `scopes` *và* mức tiết lộ
      đạt L1 trở lên.
    - **trả lời được** - thêm điều kiện: không slot nào trong `slot_dap_an` bị
      `masked_slots` của vai che ở loại nội dung đó.

    `owner` không tính là bị che dù tầng che luôn tổng quát hóa nó (AD-9): nó ra
    ở mức vai/nhóm chứ không biến mất. Bảng chính sách cũng không cho khai
    `owner` trong `masked_slots`.
    """
    duoc_phep = hang.allowed_keys["hyperedges"]
    ton_tai = tra_loi = 0
    ly_do: list[str] = []
    for he in n.hyperedge:
        moc = theo_id_he.get(he.id)
        if moc is None:
            # Không phải ca AD-5: đây là một nhãn chết, id không có trong ảnh
            # chụp. Gộp hai thông điệp làm một là nói sai nguyên nhân cho người
            # đọc trang soát (vòng review 03/09).
            ly_do.append(f"{he.id} không có trong ảnh chụp - nhãn chết, chụp lại rồi soát")
            continue
        if moc.khoa is None:
            ly_do.append(f"{he.id} không mang khóa lọc (hợp nhất khác scope, AD-5)")
            continue
        scope, loai = moc.scope, moc.content_type
        if scope not in hang.scopes:
            ly_do.append(f"{he.id} ở scope {scope!r} ngoài scopes của vai")
            continue
        muc = hang.level(loai)
        if muc == "L0":
            ly_do.append(
                f"{he.id} mang loại nội dung {loai!r} ở mức {muc}"
                + (
                    " (chưa khai trong bảng chính sách, fail-closed)"
                    if loai not in hang.disclosure
                    else ""
                )
            )
            continue
        if moc.khoa not in duoc_phep:
            ly_do.append(f"{he.id} có khóa {moc.khoa!r} ngoài tập khóa của vai")
            continue
        ton_tai += 1
        bi_che = set(hang.masked_slots.get(loai, ())) & set(he.slot_dap_an)
        if bi_che:
            ly_do.append(
                f"{he.id} vào được ngữ cảnh nhưng slot đáp án {sorted(bi_che)}"
                f" bị che ở mức {muc}"
            )
            continue
        tra_loi += 1
    return TranCau(
        cau_id=n.cau_id,
        vai=hang.name,
        tong=len(n.hyperedge),
        ton_tai=ton_tai,
        tra_loi_duoc=tra_loi,
        ly_do=tuple(ly_do),
    )


def tran_theo_vai(
    nhan: NhanTruyHoi,
    anh: AnhDoThi,
    *,
    policy: Policy | None = None,
    vai: Iterable[str] | None = None,
) -> dict[str, TranVai]:
    """Trần lý thuyết của **mỗi vai đo trên mọi câu**: hàm thuần từ ba nguồn có commit.

    Bảng này trả lời "vai X thấy được bao nhiêu phần của toàn bộ nhãn", tức nó
    là bảng để *so hai vai với nhau*: chênh giữa hai cột phải đọc ra được từ
    `scopes` và `disclosure`, không từ nhãn tay (AC của story 2.9).

    Nó **không** phải mẫu số của Đo 3. Mỗi câu chỉ được hỏi bởi đúng một vai,
    nên phép đo thật chấm từng câu với `vai_hoi` của nó; bảng đó là
    `tran_theo_vai_hoi()`. Hai bảng trả lời hai câu hỏi khác nhau và cả hai đều
    được in ra, vì chỉ có một bảng thì con số kia bị đọc nhầm thành con số này.
    """
    policy = load_policy(POLICY_MAC_DINH) if policy is None else policy
    if vai is None:
        try:
            vai = sorted(vai_cua_seed())
        except IdentitySeedInvalid:
            vai = sorted(policy.roles)
    theo_id_he = anh.theo_id
    ket_qua: dict[str, TranVai] = {}
    for ten_vai in vai:
        hang = _hang_cua_vai(policy, ten_vai)
        ket_qua[ten_vai] = TranVai(
            vai=ten_vai,
            cau=tuple(_tran_mot_cau(hang, n, theo_id_he) for n in nhan.nhan),
        )
    return ket_qua


# Nhãn của bảng trần theo vai hỏi. Không phải tên một vai thật: mỗi câu trong
# bảng này mang `vai_hoi` của chính nó.
VAI_HOI_CUA_CAU: str = "(vai hỏi của từng câu)"


def tran_theo_vai_hoi(
    bo: BoCauHoi,
    nhan: NhanTruyHoi,
    anh: AnhDoThi,
    *,
    policy: Policy | None = None,
) -> TranVai:
    """Trần lý thuyết **theo đúng vai hỏi của từng câu** - mẫu số mà Đo 3 sẽ chạy.

    `tran_theo_vai()` tính cả hai vai trên cả 41 cặp, nhưng không ai hỏi cùng một
    câu hai lần bằng hai danh tính: bộ câu hỏi gán cho mỗi câu đúng một `vai_hoi`,
    và recall của PRD 5.3 tính "theo từng vai người hỏi". Trộn hai bảng là báo
    một con số lạc quan hơn thực tế, vì mỗi cặp được tính bằng vai *dễ nhất*
    trong hai vai.
    """
    policy = load_policy(POLICY_MAC_DINH) if policy is None else policy
    theo_id_he = anh.theo_id
    theo_id_cau = bo.theo_id
    cac_cau: list[TranCau] = []
    for n in nhan.nhan:
        cau = theo_id_cau.get(n.cau_id)
        if cau is None:
            raise BoCauHoiKhongHopLe(
                [f"{n.cau_id}: nhãn trỏ một câu không có trong bộ câu hỏi"]
            )
        cac_cau.append(_tran_mot_cau(_hang_cua_vai(policy, cau.vai_hoi), n, theo_id_he))
    return TranVai(vai=VAI_HOI_CUA_CAU, cau=tuple(cac_cau))


# --------------------------------------------------------------------------
# Tiện ích chung
# --------------------------------------------------------------------------


def _doc_json(duong_dan: Path, lop_loi):
    try:
        van_ban = duong_dan.read_text(encoding="utf-8")
    except OSError as e:
        raise lop_loi([f"không đọc được {duong_dan}: {e}"]) from None
    except UnicodeDecodeError as e:
        raise lop_loi([f"{duong_dan} không phải UTF-8: {e}"]) from None
    try:
        return json.loads(van_ban)
    except json.JSONDecodeError as e:
        raise lop_loi([f"JSON hỏng ở {duong_dan}: {e}"]) from None


def _khoa_dung(muc: Mapping, khoa: frozenset[str], cho: str, loi: list[str]) -> bool:
    """Lược đồ đóng: khóa thiếu hay khóa lạ đều là lỗi, nêu cả hai một lần."""
    thieu = sorted(khoa - set(muc))
    la = sorted(set(muc) - khoa)
    if thieu or la:
        loi.append(f"{cho}: khóa thiếu {thieu}, khóa lạ {la}")
        return False
    return True


def kiem_danh_dau(
    bo: BoCauHoi, nhan: NhanTruyHoi, anh: AnhDoThi, *, policy: Policy | None = None
) -> None:
    """Hai dấu `han_che` phải khớp *đúng* thứ tính lại được từ bảng chính sách.

    Dấu hạn chế không phải một ghi chú tự do mà là một khẳng định kiểm được:

    - `n7_qua_xac_dinh` - câu N7 mà vai hỏi **không** thấy mọi vùng khai trong
      `neo_loai` ở mức L2. Với những câu đó, một lần từ chối không phân biệt
      được "không có đáp án" với "bị chặn quyền", mà FR-16 tách đúng hai thứ đó
      thành hai phép đo. Câu N7 sạch là câu neo vào vùng vai hỏi thấy hết.
    - `vai_hoi_khong_thay` - câu N3/N5 mà trần lớp *tồn tại* tính theo **vai
      hỏi của chính nó** bằng 0. Với câu bộ vàng, Đo 2 sẽ chấm "đủ ý" và "đúng
      trích dẫn" ra 0 vì một lý do không liên quan tới chất lượng sinh; với câu
      còn lại, Đo 3 mất một hàng.

    Thừa một dấu cũng đỏ như thiếu một dấu: một dấu để lại sau khi story 3.2 mở
    bảng chính sách là một câu bị coi là hỏng trong khi nó đã lành.
    """
    policy = load_policy(POLICY_MAC_DINH) if policy is None else policy
    loi: list[str] = []

    khoa_co_that = {h.khoa for h in anh.hyperedge if h.khoa is not None}
    n7_can: set[str] = set()
    for c in bo.cau:
        if c.nhom != NHOM_TU_CHOI:
            continue
        la = sorted(set(c.neo_loai) - khoa_co_that)
        if la:
            loi.append(
                f"{c.id}: `neo_loai` khai vùng {la} không có hyperedge nào trong ảnh"
                " chụp - vùng đó không tồn tại thì câu N7 không neo vào đâu cả"
            )
            continue
        hang = _hang_cua_vai(policy, c.vai_hoi)
        if not all(
            split_key(k)[0] in hang.scopes and hang.level(split_key(k)[1]) == "L2"
            for k in c.neo_loai
        ):
            n7_can.add(c.id)

    tran = tran_theo_vai_hoi(bo, nhan, anh, policy=policy)
    khong_thay_can = {t.cau_id for t in tran.cau if t.ton_tai == 0}

    for ten, can in (
        (HAN_CHE_N7_QUA_XAC_DINH, n7_can),
        (HAN_CHE_VAI_HOI_KHONG_THAY, khong_thay_can),
    ):
        khai = {c.id for c in bo.cau if ten in c.han_che}
        thieu = sorted(can - khai)
        thua = sorted(khai - can)
        if thieu or thua:
            loi.append(
                f"dấu {ten!r} lệch: thiếu ở {thieu}, thừa ở {thua} - dấu hạn chế"
                " là khẳng định tính lại được từ bảng chính sách, không phải ghi chú"
            )
    if loi:
        raise BoCauHoiKhongHopLe(loi)
