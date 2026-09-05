"""`api/` không che lại và không bỏ che.

Trả khoản action item số 7 của retro Epic 1 (F3). Mệnh đề đó khai ở `epics.md`
AC-1.6-1, và cuối Epic 1 nó **đúng một cách rỗng**: `api/main.py` có 13 dòng,
chỉ `GET /health`, nên không có gì để sai. `tests/test_phan_chieu_che.py` chỉ
phản chiếu ba adapter, `tests/test_import_lint.py` canh chiều import chứ không
canh hành vi che. Không cơ chế nào canh mệnh đề này, và nó là mệnh đề sẽ ngừng
đúng ở đúng story 3.3 khi endpoint dữ liệu đầu tiên trả nội dung.

Đây là tripwire cho lúc đó.

**Hai vế, và chúng hỏng theo hai cách khác nhau.**

*Không che lại.* Che là việc của tầng adapter (AD-9): mọi method đọc trong danh
sách đóng `MASKED_READ_METHODS` đi qua `core.masking.mask` trước khi rời
adapter. Một lớp che thứ hai ở `api/` không làm dữ liệu an toàn hơn - nó làm
tầng che có **hai** nguồn sự thật, và lần sửa sau chỉ sửa một. Tệ hơn, nó làm
một lỗ ở tầng dưới trông như đã bịt.

*Không bỏ che.* Handler không được đi vòng qua adapter để lấy dữ liệu thô. Hai
đường vòng có thật: gọi thẳng một lớp storage rồi đọc kết quả trước khi che, và
mở một ngữ cảnh hệ thống trên đường phục vụ người dùng. Đường thứ hai đã có
`CHO_PHEP_SYSTEM_CONTEXT` của `test_import_lint.py` canh phía module; test này
canh phía còn lại.

**Vì sao là danh sách đóng chứ không phải một phép quét thông minh.** Không
phép quét tĩnh nào phân biệt được "handler trả nội dung đã che" với "handler
trả nội dung thô" - cả hai đều là một `return`. Cái canh được là **module nào
trong `api/` được phép cầm một đường tới kho**, và hôm nay câu trả lời là
đúng ba module của đường ingest. Story 3.3 thêm một handler chạm engine thì nó phải
khai vào đây kèm lý do, và lúc khai là lúc người viết phải trả lời câu "nó trả
nội dung đã che chưa". Đó là điều khoản F3 đòi: mệnh đề ngừng đúng ở đâu thì có
người biết ở đó.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API = REPO_ROOT / "api"

# Module `api/` được phép cầm một đường tới kho, kèm lý do. Cả ba đều thuộc
# đường **ingest**, chạy dưới ngữ cảnh hệ thống có khai báo (AD-3), và không
# module nào phục vụ một truy vấn người dùng. `api/nguon_thu_muc.py` cố ý không
# có ở đây: nó chỉ quét thư mục và đối chiếu file `.space`, không chạm kho.
#
# Thêm một dòng ở đây là một quyết định, không phải một thủ tục: nó nói rằng
# module mới chạm kho trực tiếp và người khai đã xét xem nội dung ra khỏi nó có
# đi qua tầng che chưa.
CHAM_STORAGE_CO_LY_DO: dict[str, str] = {
    "api/do_chi_phi.py": "CLI nạp và xóa space; đọc sổ tài liệu, gọi chay_lan_nap và xoa_space",
    "api/dot_nap.py": "lõi một đợt nạp; dựng EngineACL và chạy ingest tuần tự",
    "api/man_nap.py": "màn nạp web, đi qua đúng chay_lan_nap của CLI; không có đường đọc tri thức",
}

# Tên mở một đường tới kho tri thức: ba lớp storage, engine, và bốn cửa của
# `adapters/ingest.py` mà một module `api/` có thể gọi mà không nhìn thấy lớp
# storage nào. Danh sách gồm cả nhóm thứ hai vì đó là hình dạng thật hôm nay:
# chỉ `dot_nap.py` cầm `EngineACL`, hai module kia đi qua `chay_lan_nap`. Một
# danh sách chỉ có tên lớp sẽ bỏ lọt đúng hai module đang chạm kho.
LOP_STORAGE: frozenset[str] = frozenset(
    {
        "Neo4jACLGraphStorage",
        "QdrantVectorDBStorage",
        "JsonACLKVStorage",
        "EngineACL",
        "cau_hinh_kho_tu_moi_truong",
        "chay_lan_nap",
        "nap_cac_tai_lieu",
        "xoa_space",
        "SoTaiLieu",
    }
)

# Mọi thứ của tầng che. `api/` không được nhập bất kỳ cái nào: che xong ở
# adapter rồi, và một lời gọi thứ hai ở đây là lớp che thứ hai.
TANG_CHE: frozenset[str] = frozenset(
    {"mask", "MASKED_READ_METHODS", "dau_che_truong", "dau_che_slot"}
)


def _module_api() -> list[Path]:
    return sorted(p for p in API.rglob("*.py") if p.name != "__init__.py")


def _ten(py: Path) -> str:
    return str(py.relative_to(REPO_ROOT))


def _cay(py: Path) -> ast.Module:
    return ast.parse(py.read_text(encoding="utf-8"), filename=str(py))


def _ten_duoc_nhap(py: Path) -> set[str]:
    ra: set[str] = set()
    for n in ast.walk(_cay(py)):
        if isinstance(n, ast.ImportFrom):
            ra.update(a.asname or a.name for a in n.names)
        elif isinstance(n, ast.Import):
            ra.update(a.asname or a.name.split(".")[0] for a in n.names)
    return ra


def _nhap_tu(py: Path, package: str) -> set[str]:
    ra: set[str] = set()
    for n in ast.walk(_cay(py)):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(package):
            ra.update(a.name for a in n.names)
    return ra


def test_api_khong_che_lai():
    """Không module `api/` nào nhập tầng che.

    Vế "không che lại". Nếu một handler thấy cần che thêm thì thứ hỏng là tầng
    dưới, và chỗ sửa là tầng dưới.
    """
    vi_pham = []
    for py in _module_api():
        cham = _nhap_tu(py, "core.masking") | (_ten_duoc_nhap(py) & TANG_CHE)
        if cham:
            vi_pham.append(f"{_ten(py)} nhập {sorted(cham)}")
    assert not vi_pham, (
        "`api/` không được che lại (AC-1.6-1): che là việc của adapter, và một lớp"
        " thứ hai ở đây làm tầng che có hai nguồn sự thật.\n  " + "\n  ".join(vi_pham)
    )


def test_module_api_cham_kho_deu_duoc_khai_kem_ly_do():
    """Vế "không bỏ che": một module `api/` mới cầm đường tới kho phải khai.

    Đây là dòng đỏ lên ở story 3.3. Lúc khai là lúc người viết phải trả lời câu
    "nội dung ra khỏi handler này đã đi qua tầng che chưa".
    """
    chua_khai = []
    for py in _module_api():
        ten = _ten(py)
        if ten in CHAM_STORAGE_CO_LY_DO:
            continue
        cham = _ten_duoc_nhap(py) & LOP_STORAGE
        if cham:
            chua_khai.append(f"{ten} chạm {sorted(cham)}")
    assert not chua_khai, (
        "Module `api/` chạm lớp storage mà chưa khai trong `CHAM_STORAGE_CO_LY_DO`."
        " Khai kèm lý do, và trả lời được câu nội dung ra khỏi nó đã che chưa"
        " (AC-1.6-1, khoản F3 của retro Epic 1).\n  " + "\n  ".join(chua_khai)
    )


def test_ly_do_khai_van_con_that():
    """Mỗi dòng khai phải trỏ vào file có thật và file đó phải còn chạm kho.

    Một miễn trừ chết là một dòng không ai dám xóa vì không ai biết nó còn canh
    gì. Cùng luật với danh sách trắng vendor của `test_import_lint.py`.
    """
    for ten, ly_do in sorted(CHAM_STORAGE_CO_LY_DO.items()):
        py = REPO_ROOT / ten
        assert py.exists(), f"khai trỏ vào file không có: {ten}"
        assert ly_do.strip(), f"{ten} khai mà không có lý do"
        assert _ten_duoc_nhap(py) & LOP_STORAGE, (
            f"{ten} không còn chạm lớp storage nào; gỡ nó khỏi `CHAM_STORAGE_CO_LY_DO`"
        )


def test_menh_de_hom_nay_dung_mot_cach_rong_va_dieu_do_duoc_ghi_ra():
    """`api/main.py` chưa có endpoint dữ liệu nào, và test phải nói ra điều đó.

    Không có ca này thì ba test trên xanh và người đọc tưởng mệnh đề AC-1.6-1
    đã được chứng minh. Nó chưa: hôm nay nó đúng vì không có gì để sai. Ca này
    đỏ ở đúng lúc điều đó thay đổi, và thông điệp nói người sửa phải làm gì.
    """
    main = REPO_ROOT / "api" / "main.py"
    tuyen = [
        n
        for n in ast.walk(_cay(main))
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    ten_tuyen = {n.name for n in tuyen}
    assert ten_tuyen <= {"health"}, (
        "`api/main.py` có endpoint mới ngoài /health. Mệnh đề AC-1.6-1 tới giờ"
        " đúng một cách rỗng vì không endpoint nào trả nội dung tri thức; từ lúc"
        " này nó là một khẳng định thật. Viết một test khẳng định nội dung ra khỏi"
        " endpoint đã đi qua tầng che, rồi cập nhật ca này (khoản F3 của retro"
        f" Epic 1). Endpoint đang có: {sorted(ten_tuyen)}"
    )
