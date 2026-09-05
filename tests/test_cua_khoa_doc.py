"""Cửa tập khóa đọc dùng chung, và luật ba adapter phải đi qua nó.

Trả khoản action item số 9 của retro Epic 1 (F5): cùng một luật fail-closed viết
ba hình dạng ở ba adapter, và rủi ro cụ thể là Epic 5 nới quyền cho break-glass
phải sửa ba chỗ khác hình dạng, bỏ sót một chỗ là fail-open im lặng.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from adapters.cua_khoa_doc import KhoaDoc, khoa_doc
from core.permission import SystemContextRawRead

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class _NguCanhGia:
    """Bản giả tối thiểu, đúng hợp đồng `NguCanhDoc`."""

    bypass: bool
    bang: dict[str, frozenset[str]]

    @property
    def bypass_filter(self) -> bool:
        return self.bypass

    def keys_for(self, namespace: str) -> frozenset[str]:
        if self.bypass:
            raise SystemContextRawRead("context hệ thống không mang allowed_keys")
        if namespace not in self.bang:
            raise KeyError(f"namespace {namespace!r} không có trong ngữ cảnh")
        return self.bang[namespace]


# --- Ba nhánh, và chúng phải phân biệt được -------------------------------


def test_ngu_canh_he_thong_la_doc_tho_va_khong_hoi_tap_khoa():
    """Nhánh 1. Hỏi `keys_for` dưới cờ hệ thống là lỗi lập trình.

    Bản giả dội `SystemContextRawRead` đúng như `core.permission` làm, nên nếu
    cửa gọi `keys_for` trước khi kiểm `bypass_filter` thì test này đỏ. Thứ tự
    hai dòng đó là hợp đồng, không phải một tinh chỉnh.
    """
    cua = khoa_doc(_NguCanhGia(bypass=True, bang={}), "chunks")
    assert cua.doc_tho
    assert not cua.khong_thay_gi
    assert cua.loc_theo is None


def test_tap_khoa_rong_la_khong_thay_gi_chu_khong_phai_doc_tho():
    """Nhánh 2. Hai nhánh này có nghĩa ngược hẳn nhau, không được lẫn.

    Đây là ca mà một phép gom cẩu thả làm hỏng: gộp "đọc thô" với "tập rỗng"
    thành một giá trị rỗng duy nhất biến vai không có quyền thành vai thấy tất.
    """
    cua = khoa_doc(_NguCanhGia(bypass=False, bang={"chunks": frozenset()}), "chunks")
    assert cua.khong_thay_gi
    assert not cua.doc_tho
    assert cua.loc_theo == frozenset()


def test_tap_khoa_khong_rong_thi_loc_theo_dung_tap_do():
    """Nhánh 3."""
    khoa = frozenset({"noi_bo:runbook"})
    cua = khoa_doc(_NguCanhGia(bypass=False, bang={"chunks": khoa}), "chunks")
    assert not cua.doc_tho and not cua.khong_thay_gi
    assert cua.loc_theo == khoa


def test_namespace_la_van_no_ra_chu_khong_thanh_khong_thay_gi():
    """Một namespace gõ sai phải nổ, không được lặng lẽ thành fail-closed.

    Fail-closed vì gõ sai *trông* an toàn nhưng nó giấu một lỗi lập trình sau
    một hành vi hợp lệ, và lần sửa sau sẽ đi tìm ở chỗ khác.
    """
    with pytest.raises(KeyError):
        khoa_doc(_NguCanhGia(bypass=False, bang={"chunks": frozenset()}), "go_sai")


def test_doc_tho_thi_khoa_luon_rong():
    """Bất biến của kiểu: `doc_tho` đi cùng một tập rỗng, và nó không phải tập khóa."""
    assert khoa_doc(_NguCanhGia(bypass=True, bang={}), "x").khoa == frozenset()


def test_khong_thay_gi_va_doc_tho_khong_bao_gio_cung_dung():
    """Hai nhánh loại trừ nhau trên mọi tổ hợp."""
    for doc_tho in (True, False):
        for khoa in (frozenset(), frozenset({"a"})):
            cua = KhoaDoc(doc_tho=doc_tho, khoa=frozenset() if doc_tho else khoa)
            assert not (cua.doc_tho and cua.khong_thay_gi)


# --- Luật: không adapter nào giữ bản sao của cửa này ------------------------

# Ba adapter mang luật này, và mỗi cái có một lý do riêng để giữ một method bọc
# mỏng: Neo4j cần một vị từ `bool`, KV cần hình dạng `frozenset | None` cho
# đường lọc từng bản ghi, Qdrant dùng thẳng. Cái không được phép là **tự phân
# giải lại** tập khóa, vì đó chính là ba hình dạng mà khoản F5 nói tới.
ADAPTER_MANG_LUAT: frozenset[str] = frozenset(
    {"adapters/neo4j.py", "adapters/kv.py", "adapters/qdrant.py"}
)

# Miễn trừ tường minh kèm lý do, thay vì nới luật. Cùng hình dạng với
# `CHO_PHEP_VENDOR` của `test_import_lint.py`.
#
# `Neo4jACLGraphStorage._che_mo_ta` hỏi tập khóa của namespace `entities` để
# quyết **một bản ghi** có được giữ `description` không (ngưỡng L2, AD-9). Đó
# là đường **che**, không phải cửa đọc: cửa đọc quyết có chạm kho hay không và
# chạy một lần cho cả lời gọi, còn phép này chạy trên từng node đã lấy về.
# Gộp hai thứ vào một cửa là gộp hai luật khác nhau dưới một cái tên.
CHO_PHEP_GOI_KEYS_FOR: frozenset[str] = frozenset({"adapters/neo4j.py"})


def _goi_keys_for(duong_dan: Path) -> list[int]:
    """Dòng của mọi lời gọi `.keys_for(...)` trong một file."""
    cay = ast.parse(duong_dan.read_text(encoding="utf-8"), filename=str(duong_dan))
    return [
        n.lineno
        for n in ast.walk(cay)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "keys_for"
    ]


def test_ba_adapter_di_qua_cua_chung_chu_khong_tu_phan_giai():
    """Không adapter nào gọi thẳng `keys_for` trên đường đọc nữa.

    Đây là phần có răng của phép gom. Không có nó, một story sau viết lại một
    nhánh `if not context.bypass_filter: ... keys_for(...)` ngay trong thân một
    method mới và ba hình dạng mọc lại, đúng chuyện đã xảy ra ở Epic 1.
    """
    vi_pham = []
    for ten in sorted(ADAPTER_MANG_LUAT):
        dong = _goi_keys_for(REPO_ROOT / ten)
        if dong and ten not in CHO_PHEP_GOI_KEYS_FOR:
            vi_pham.append(f"{ten}:{dong}")
    assert not vi_pham, (
        "Adapter tự phân giải tập khóa thay vì đi qua `adapters.cua_khoa_doc.khoa_doc`: "
        + ", ".join(vi_pham)
        + ". Xem khoản F5 của retro Epic 1."
    )
    # Miễn trừ được ghim bằng **số lời gọi**, không chỉ bằng tên file: thêm một
    # lời gọi thứ hai vào `neo4j.py` là đỏ, kể cả khi file đã có tên trong danh
    # sách. Không có ràng buộc này thì một miễn trừ mở cửa cho cả file.
    assert len(_goi_keys_for(REPO_ROOT / "adapters/neo4j.py")) == 1, (
        "adapters/neo4j.py chỉ được gọi `keys_for` đúng một lần, ở `_che_mo_ta`"
        " (đường che từng bản ghi). Lời gọi mới phải đi qua `khoa_doc`."
    )


def test_moi_file_goi_keys_for_ngoai_core_deu_duoc_khai():
    """Danh sách đóng: một điểm gọi mới phải khai kèm lý do.

    Quét cả `adapters/` và `api/`. `core/permission.py` là nơi định nghĩa nên
    nó ngoài phạm vi.
    """
    la = []
    for goi in ("adapters", "api"):
        for py in sorted((REPO_ROOT / goi).rglob("*.py")):
            ten = str(py.relative_to(REPO_ROOT))
            if ten in CHO_PHEP_GOI_KEYS_FOR or ten == "adapters/cua_khoa_doc.py":
                continue
            if _goi_keys_for(py):
                la.append(f"{ten}:{_goi_keys_for(py)}")
    assert not la, (
        "File gọi `keys_for` mà chưa khai trong `CHO_PHEP_GOI_KEYS_FOR`: "
        + ", ".join(la)
        + ". Đường đọc thì đi qua `khoa_doc`; đường ghi thì khai kèm lý do."
    )


def test_mien_tru_van_con_that():
    """Danh sách miễn trừ phải trỏ vào file có thật và file đó phải còn gọi.

    Một miễn trừ chết là một dòng không ai dám xóa vì không ai biết nó còn canh
    gì. Cùng luật với `test_danh_sach_trang_vendor_dung_mot_dong_va_van_con_that`.
    """
    for ten in sorted(CHO_PHEP_GOI_KEYS_FOR):
        py = REPO_ROOT / ten
        assert py.exists(), f"miễn trừ trỏ vào file không có: {ten}"
        assert _goi_keys_for(py), (
            f"{ten} không còn gọi `keys_for`; gỡ nó khỏi `CHO_PHEP_GOI_KEYS_FOR`"
        )
