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
THU_MUC_CAU_HINH = GOC_REPO / "config"

# Bốn cấu hình đo của FR-28, theo đúng thứ tự PRD 5.3 đánh số chúng. Tên biến
# mang số thứ tự vì tài liệu và ledger gọi chúng bằng số ("cấu hình 2"), còn tên
# file mang tên phép biến đổi sinh ra nó.
POLICY_TAT_PHAN_QUYEN = THU_MUC_CAU_HINH / "policy-tat-phan-quyen.yaml"  # (1)
POLICY_NHI_PHAN = THU_MUC_CAU_HINH / "policy-nhi-phan.yaml"  # (2)
POLICY_DAY_DU = THU_MUC_CAU_HINH / "policy-day-du.yaml"  # (3), bảng vận hành
POLICY_TOI_THIEU_L1 = THU_MUC_CAU_HINH / "policy-toi-thieu-l1.yaml"  # (4)
BON_CAU_HINH = (
    POLICY_TAT_PHAN_QUYEN,
    POLICY_NHI_PHAN,
    POLICY_DAY_DU,
    POLICY_TOI_THIEU_L1,
)

NHOM_PHU_TRACH = THU_MUC_CAU_HINH / "nhom-phu-trach.yaml"

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


def ke_can_ky_vong(bang: dict, vai: str, hyperedges, goc: list[str]) -> set[str]:
    """Id fixture của hyperedge kề cận một bước hyperedge với `goc`, dưới vai (story 5.2).

    Kề cận là chung ít nhất một giá trị slot (một entity) với một gốc; gốc phải
    là hyperedge vai thấy, lân cận cũng vậy, và id vào không có trong kết quả.
    Đây là oracle chung cho ca driver giả (`tests/test_break_glass_duyet.py`) và
    ca Neo4j thật (`tests/test_adapter_neo4j_that.py`), để kỳ vọng không phải
    hai bản chép tay (khoản ledger 2.12 về test marker).
    """
    thay = set(hyperedge_thay_duoc(bang, vai, hyperedges))
    theo_id = {he["id"]: he for he in hyperedges}
    gia_tri_goc = {
        v for g in goc if g in thay for v in theo_id[g]["slots"].values()
    }
    return {
        he["id"]
        for he in hyperedges
        if he["id"] in thay
        and he["id"] not in goc
        and gia_tri_goc & set(he["slots"].values())
    }


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

# Tên trường mà adapter gắn thêm để mang tên nhóm phụ trách xuống tầng che
# (story 3.1). Viết tay ở đây đúng như đã viết tay tám vai slot: oracle không
# import ``core/``, nên hằng này là bản đối chứng chứ không phải bản sao dùng
# chung. ``test_oracle_va_core_khai_cung_bang_hang`` đối chiếu hai bản.
TRUONG_NHOM_PHU_TRACH = "owner_group"


def doc_bang_nhom(duong_dan: Path = NHOM_PHU_TRACH) -> dict:
    """Bảng nhóm phụ trách đọc thô, không đi qua loader của ``adapters/``."""
    return yaml.safe_load(Path(duong_dan).read_text(encoding="utf-8"))["nhom"]


def nhom_ky_vong(loai_noi_dung: str, duong_dan: Path = NHOM_PHU_TRACH):
    """Nhóm phụ trách của một loại nội dung; loại chưa khai là ``None``."""
    return doc_bang_nhom(duong_dan).get(loai_noi_dung)


def dau_che_ky_vong(slot: str, loai_noi_dung: str | None = None) -> str:
    """Dấu che kỳ vọng của một vai slot, bản viết tay của oracle.

    ``loai_noi_dung`` chỉ có nghĩa với vai ``owner`` (story 3.1): dấu che của
    nó mang **tên nhóm phụ trách** của loại nội dung ấy thay cho chữ ``group``
    chung. Vắng tham số, hay loại nội dung chưa khai nhóm, thì rơi về hằng cũ -
    đúng hai nhánh mà ``core.masking.dau_che_owner`` có.
    """
    if slot != "owner":
        return "[" + slot + ":" + LY_DO_CHE_THEO_BANG + "]"
    nhom = nhom_ky_vong(loai_noi_dung) if loai_noi_dung else None
    return "[owner:" + (nhom or LY_DO_CHE_OWNER) + "]"


def ban_ghi_slot_ky_vong(bang: dict, vai: str, hyperedge, co_nhom: bool = False) -> dict:
    """Bản ghi "dict theo slot" sau khi che, tính hoàn toàn từ bảng và fixture.

    Đối chứng độc lập cho story 1.6: giữ nguyên tập khóa của bản ghi gốc (che
    là thay giá trị, không bỏ khóa), thay giá trị của đúng những slot mà
    ``slot_phai_che`` chỉ ra, và không bịa thêm slot nào mà hyperedge không có.

    ``co_nhom`` là ca của story 3.1: nơi gọi khai nhóm phụ trách, và khi đó
    tầng che **thêm** khóa ``owner`` mang tên nhóm, kể cả khi hyperedge không
    có vai đó. Mặc định ``False`` giữ nguyên kỳ vọng của Epic 1 cho bản ghi
    không ai gắn nhóm.

    Kỳ vọng này là bản ghi **rời adapter**, nên nó không mang
    ``TRUONG_NHOM_PHU_TRACH``: trường ấy là đường vận chuyển tên nhóm xuống
    tầng che, và adapter gỡ nó ở đầu ra. Một oracle giữ lại trường đó là một
    oracle khóa chính cái rò lại - tên nhóm ở dạng thô đi tiếp lên ``vendor/``
    nằm cạnh chính dấu che nó vừa sinh ra.
    """
    che = slot_phai_che(bang, vai, hyperedge)
    # Tên nhóm chỉ xuống tới tầng che qua trường mà nơi gọi gắn thêm, nên bản
    # ghi không mang trường ấy phải nhận đúng hằng cũ.
    loai = hyperedge["content_type"] if co_nhom else None
    ra = {
        slot: dau_che_ky_vong(slot, loai) if slot in che else gia_tri
        for slot, gia_tri in hyperedge["slots"].items()
    }
    if co_nhom:
        ra["owner"] = dau_che_ky_vong("owner", hyperedge["content_type"])
    return ra
