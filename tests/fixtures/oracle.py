"""Oracle quyền độc lập của Epic 1 (story 1.2).

Tính kỳ vọng từ hai nguồn duy nhất: nội dung file YAML chính sách và nhãn của
fixture dựng tay. Module này cố ý **không import ``core/``** và không gọi
loader của ``adapters/``: nếu nó dùng lại cùng một hàm với hệ thì test chỉ
chứng minh hệ nhất quán với chính nó, không chứng minh hệ đúng.

Cái giá phải trả là ba dòng lặp lại có chủ đích (đọc file, sha256, ghép khóa
``{scope}:{content_type}``). Đó là bản thứ hai, viết độc lập, dùng làm đối
chứng - không phải trùng lặp cần gỡ.

Story 1.3-1.7 dùng lại chính các hàm này để chấm ngữ cảnh truy hồi thật.
"""

import hashlib
from pathlib import Path

import yaml

GOC_REPO = Path(__file__).resolve().parent.parent.parent
POLICY_TOI_GIAN = GOC_REPO / "config" / "policy-toi-gian.yaml"
POLICY_NHI_PHAN = GOC_REPO / "config" / "policy-nhi-phan.yaml"

# Thứ tự mức, chỉ dùng để so sánh "đạt từ mức X trở lên".
THU_TU_MUC = {"L0": 0, "L1": 1, "L2": 2}

# Ngữ nghĩa mức theo namespace (NFR-06): chunk và mô tả entity là văn bản không
# che theo slot được nên chỉ vào khi vai đạt L2; hyperedge vào từ L1 trở lên.
MUC_TOI_THIEU_THEO_NAMESPACE = {
    "chunks": "L2",
    "entities": "L2",
    "hyperedges": "L1",
}

# Tám vai slot theo Consistency Conventions của spine. Khai lại ở đây để oracle
# đứng độc lập với danh mục trong ``core/``; test đối chiếu hai bản với nhau.
TAM_VAI_SLOT = (
    "subject",
    "symptom",
    "cause",
    "condition",
    "remediation",
    "source",
    "time",
    "owner",
)


def doc_bang_chinh_sach(duong_dan: Path) -> dict:
    """Đọc thô bảng chính sách thành dict, không kiểm gì thêm."""
    return yaml.safe_load(Path(duong_dan).read_text(encoding="utf-8"))


def bam_file_chinh_sach(duong_dan: Path) -> str:
    """sha256 của nội dung file, tính độc lập với loader (`policy_version`)."""
    return hashlib.sha256(Path(duong_dan).read_bytes()).hexdigest()


def muc_ky_vong(bang: dict, vai: str, loai_noi_dung: str) -> str:
    """Mức tiết lộ của một vai với một loại nội dung; vắng trong bảng là L0."""
    return bang["roles"][vai]["disclosure"].get(loai_noi_dung, "L0")


def khoa_ky_vong(scope: str, loai_noi_dung: str) -> str:
    """Ghép khóa lọc theo AD-4, bản viết tay của oracle."""
    return scope + ":" + loai_noi_dung


def allowed_keys_ky_vong(bang: dict, vai: str) -> dict[str, set[str]]:
    """Tập khóa được phép của một vai, tính riêng cho từng namespace."""
    cau_hinh = bang["roles"][vai]
    ky_vong: dict[str, set[str]] = {}
    for namespace, muc_toi_thieu in MUC_TOI_THIEU_THEO_NAMESPACE.items():
        nguong = THU_TU_MUC[muc_toi_thieu]
        ky_vong[namespace] = {
            khoa_ky_vong(scope, loai)
            for scope in cau_hinh["scopes"]
            for loai, muc in cau_hinh["disclosure"].items()
            if THU_TU_MUC[muc] >= nguong
        }
    return ky_vong


def masked_slots_ky_vong(bang: dict, vai: str) -> dict[str, set[str]]:
    """Map loại nội dung -> tập vai slot phải che, đúng như bảng khai."""
    khai = bang["roles"][vai].get("masked_slots") or {}
    return {loai: set(slots) for loai, slots in khai.items()}


def hyperedge_thay_duoc(bang: dict, vai: str, hyperedges) -> list[str]:
    """Id các hyperedge mà vai còn thấy (từ L1 trở lên), theo thứ tự fixture."""
    return [
        he["id"]
        for he in hyperedges
        if THU_TU_MUC[muc_ky_vong(bang, vai, he["content_type"])] >= THU_TU_MUC["L1"]
        and khoa_ky_vong(he["scope"], he["content_type"])
        in allowed_keys_ky_vong(bang, vai)["hyperedges"]
    ]


def slot_phai_che(bang: dict, vai: str, hyperedge) -> set[str]:
    """Tập slot phải che trên một hyperedge cụ thể với một vai.

    Ba nhánh. L0 thì hyperedge vắng mặt hẳn nên không có gì để che, trả tập
    rỗng. L1 thì che theo bảng cộng slot `owner`. L2 thì chỉ còn `owner` - slot
    này luôn tổng quát hóa về mức vai/nhóm kể cả ở L2 (AD-9), nên nó không nằm
    trong bảng YAML.

    Giao với tập slot thật của hyperedge: bảng khai `remediation` mà fact không
    có slot đó thì không có gì để che, kỳ vọng phải nói đúng như vậy.
    """
    muc = muc_ky_vong(bang, vai, hyperedge["content_type"])
    if muc == "L0" or khoa_ky_vong(
        hyperedge["scope"], hyperedge["content_type"]
    ) not in allowed_keys_ky_vong(bang, vai)["hyperedges"]:
        return set()
    che = {"owner"}
    if muc == "L1":
        che |= masked_slots_ky_vong(bang, vai).get(hyperedge["content_type"], set())
    return che & set(hyperedge["slots"])


def chunk_thay_duoc(bang: dict, vai: str, chunks) -> list[str]:
    """Id các chunk mà vai đọc được, theo ngưỡng L2 của namespace `chunks`.

    Chunk và tài liệu gốc là văn bản chạy, không tách theo slot được, nên
    không có mức trung gian: hoặc vai đạt L2 với loại nội dung của nguồn và
    đọc nguyên văn, hoặc mục vắng mặt hẳn (NFR-06). Đây là chỗ luật đó được
    tính lại bằng tay, độc lập với `core/policy.py`.

    Trả theo thứ tự fixture để test so được cả tập lẫn thứ tự, giống
    `hyperedge_thay_duoc`.
    """
    duoc_phep = allowed_keys_ky_vong(bang, vai)["chunks"]
    return [
        c["id"]
        for c in chunks
        if THU_TU_MUC[muc_ky_vong(bang, vai, c["content_type"])] >= THU_TU_MUC["L2"]
        and khoa_ky_vong(c["scope"], c["content_type"]) in duoc_phep
    ]


# Dấu che kỳ vọng, viết tay ở đây đúng như đã viết tay tám vai slot phía trên.
# Hai lý do vì hai luật khác nguồn; vì sao phải giữ chúng tách nhau thì đọc
# docstring ``core/masking.py``. Test đối chiếu hai bản là
# ``test_oracle_va_core_khai_cung_bang_hang``.
LY_DO_CHE_THEO_BANG = "masked"
LY_DO_CHE_OWNER = "group"


def dau_che_ky_vong(slot: str) -> str:
    """Dấu che kỳ vọng của một vai slot, bản viết tay của oracle."""
    ly_do = LY_DO_CHE_OWNER if slot == "owner" else LY_DO_CHE_THEO_BANG
    return "[" + slot + ":" + ly_do + "]"


def ban_ghi_slot_ky_vong(bang: dict, vai: str, hyperedge) -> dict:
    """Bản ghi "dict theo slot" sau khi che, tính hoàn toàn từ bảng và fixture.

    Đối chứng độc lập cho story 1.6: giữ nguyên tập khóa của bản ghi gốc (che
    là thay giá trị, không bỏ khóa), thay giá trị của đúng những slot mà
    ``slot_phai_che`` chỉ ra, và không bịa thêm slot nào mà hyperedge không có.
    """
    che = slot_phai_che(bang, vai, hyperedge)
    return {
        slot: dau_che_ky_vong(slot) if slot in che else gia_tri
        for slot, gia_tri in hyperedge["slots"].items()
    }
