"""`api/` không che lại và không bỏ che.

Trả khoản action item số 7 của retro Epic 1 (F3). Mệnh đề đó khai ở `epics.md`
AC-1.6-1, và cuối Epic 1 nó **đúng một cách rỗng**: `api/main.py` có 13 dòng,
chỉ `GET /health`, nên không có gì để sai. `tests/test_phan_chieu_che.py` chỉ
phản chiếu ba adapter, `tests/test_import_lint.py` canh chiều import chứ không
canh hành vi che. Không cơ chế nào canh mệnh đề này, và nó là mệnh đề sẽ ngừng
đúng ở đúng story 3.3 khi endpoint dữ liệu đầu tiên trả nội dung.

Đây là tripwire cho lúc đó.

**Story 3.1 đổi hình dạng ca cuối, không đổi mệnh đề.** `api/main.py` nay có ba
tuyến xác thực, nên câu "chỉ có `/health`" không phát biểu được nữa; thay bằng
"mỗi hàm cấp module phải khai kèm lý do nó không trả nội dung tri thức"
(`HAM_MAIN_CO_LY_DO`). Mệnh đề vẫn chưa được chứng minh và vẫn ngừng ở 3.3.

**Cửa xác thực nay mặc định đóng** (trả khoản ledger của 3.1). Tuyến đóng đăng
ký vào `api.main.cua_dong`, router mang `Depends(_claim)`; ba ca cuối file chấm
chính cơ chế ấy trên `app.routes` thay vì đọc AST tìm một lời gọi trong thân
handler.

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
    # Dòng thứ tư, và là dòng đầu tiên **không** thuộc đường ingest. Nó là chỗ
    # câu hỏi của F3 phải được trả lời chứ không hoãn thêm nữa, nên câu trả lời
    # viết ra ở đây: nội dung ra khỏi module này là chuỗi ngữ cảnh mà `kg_query`
    # dựng từ kết quả của ba adapter, và cả ba gọi `core.masking.mask` trong
    # đường trả về của mọi method đọc (AD-9, `tests/test_phan_chieu_che.py`
    # canh danh sách method). Module này không che lại và không bỏ che: nó
    # không import một cái tên nào của tầng che (ca `test_api_khong_che_lai`),
    # và nó không mở ngữ cảnh hệ thống (ca `test_chi_mot_module_api_dung_ngu_canh_quyen`
    # cộng danh sách trắng `CHO_PHEP_SYSTEM_CONTEXT` của import-lint).
    "api/hoi_dap.py": (
        "endpoint hỏi đáp: dựng engine truy hồi và gọi aquery dưới ngữ cảnh vai;"
        " nội dung ra khỏi nó đã đi qua tầng che của ba adapter (AD-9), api/"
        " không che lại và không bỏ che"
    ),
    # Dòng thứ năm (story 3.7), cùng câu trả lời với dòng trên: nội dung ra
    # khỏi module này là đồ thị mà `EngineACL.do_thi` lắp từ các dòng của
    # `Neo4jACLGraphStorage.do_thi_cua`, mỗi dòng qua `_che` (method nằm trong
    # `MASKED_READ_METHODS`) và hyperedge ngoài quyền vắng ngay trong Cypher.
    # Module không nhập `core.masking`, không dựng ngữ cảnh (gọi
    # `api.hoi_dap.ngu_canh_cua_claim`), không dựng đồ thị từ `citations`.
    "api/do_thi.py": (
        "endpoint đồ thị theo quyền: gọi EngineACL.do_thi dưới ngữ cảnh vai;"
        " mọi tên entity ra khỏi nó đã qua _che của adapter graph, hyperedge"
        " ngoài quyền vắng mặt ở Cypher, api/ chỉ chuyển kiểu"
    ),
    # Dòng thứ sáu (story 5.1). Module cầm `EngineACL` chỉ để hỏi **mức tiết
    # lộ** qua `trich_dan_theo_id` - cùng cửa quyền với citation của 3.4
    # (`trich_dan_cua` + `dung_trich_dan`, không trả giá trị slot hay tên
    # entity). Thứ ra khỏi nó là hàng yêu cầu break-glass (id, khóa quyền tách
    # đôi, nhóm duyệt, lý do người xin gõ), không một byte nội dung fact; nó
    # không nhập `core.masking` và không dựng ngữ cảnh (gọi `ngu_canh_cua_claim`).
    "api/break_glass.py": (
        "API xin break-glass: gọi EngineACL.trich_dan_theo_id dưới ngữ cảnh vai"
        " để biết mức tiết lộ; ra khỏi nó là hàng yêu cầu ở Postgres, không nội"
        " dung tri thức, id vô hình là một 404 duy nhất. Story 5.2 thêm"
        " EngineACL.vung_lan_can dưới ngữ cảnh người xin: cũng chỉ id, mức và"
        " khóa quyền tách đôi, ra khỏi nó là hàng grant"
    ),
}

# Tên mở một đường tới kho tri thức: ba lớp storage, engine, và bốn cửa của
# `adapters/ingest.py` mà một module `api/` có thể gọi mà không nhìn thấy lớp
# storage nào. Danh sách gồm cả nhóm thứ hai vì đó là hình dạng thật hôm nay:
# chỉ `dot_nap.py` cầm `EngineACL`, hai module kia đi qua `chay_lan_nap`. Một
# danh sách chỉ có tên lớp sẽ bỏ lọt đúng hai module đang chạm kho.
#
# `api/tai_khoan.py` và `api/xac_thuc.py` (story 3.1) cố ý **không** có ở đây:
# bảng `users` là trạng thái ứng dụng của AD-7, không phải một kho tri thức, và
# hai module đó không nhập tên nào trong danh sách dưới.
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


# Hàm cấp module của `api/main.py`, mỗi cái kèm lý do nó **không** trả nội dung
# tri thức. Danh sách đóng, cùng hình dạng với `CHAM_STORAGE_CO_LY_DO` ở trên:
# thêm một dòng ở đây là một quyết định, và lúc khai là lúc người viết phải trả
# lời câu "nội dung ra khỏi handler này đã đi qua tầng che chưa".
#
# Story 3.1 là lần đầu danh sách này không còn chỉ có `health`. Ba hàm mới đều
# thuộc đường **xác thực**: chúng đọc bảng `users` của Postgres và file seed,
# hai nguồn không có một byte tri thức nào, và không hàm nào chạm ba kho hay
# dựng một `PermissionContext`.
#
# Story 3.3 là lần đầu danh sách có một hàm **trả nội dung tri thức** (`hoi`),
# và đó đúng là chỗ mệnh đề AC-1.6-1 ngừng đúng một cách rỗng. Lý do của nó vì
# thế không nói "không chạm kho" nữa mà nói nội dung đã che ở đâu; và ba ca
# dưới đây thêm một mệnh đề mới thay chỗ: `api/main.py` vẫn không dựng ngữ cảnh
# quyền, và **đúng một** module `api/` dựng nó.
HAM_MAIN_CO_LY_DO: dict[str, str] = {
    "health": "healthcheck của compose; trả một hằng, nằm ngoài mọi cửa",
    "hoi": "POST /hoi-dap; gọi thẳng api.hoi_dap.tra_loi, nội dung đã che ở ba adapter (AD-9)",
    "do_thi": "POST /do-thi; gọi thẳng api.do_thi.lay_do_thi, tên entity đã che ở adapter graph (AD-9), không LLM",
    "_than_yeu_cau_la": "exception handler, đổi 422 thô của FastAPI thành 400 đúng envelope",
    "_tuyen_khong_co": "exception handler, đổi 404/405 thô của Starlette thành envelope {error:{code,message}}; không chạm kho",
    "_loi_khong_xac_dinh": "exception handler lưới cuối; trả {error:{code,message}} từ hai hằng, nội dung lỗi chỉ vào log",
    "mo_kho_tai_khoan": "điểm nối mở pool Postgres cho bảng users; test thay bằng bản giả",
    "mo_audit": "điểm nối mở pool Postgres cho bảng audit_log; không phải kho tri thức",
    "vong_doi": "lifespan: kiểm khóa ký, nạp policy, đọc cờ chế độ đo, mở bảng users, audit_log (ghi hàng startup) và engine truy hồi; không gọi khoi_tao()",
    "_loi_xac_thuc": "exception handler, dựng {error:{code,message}} từ hai hằng",
    "_claim": "đọc claim của token trong header; không chạm kho",
    "dang_nhap": "POST /auth/login; đọc bảng users, phát JWT, ghi hàng auth_login best-effort (không nội dung)",
    "toi": "GET /auth/toi; đọc lại claim của chính token",
    "danh_sach_tai_khoan": "GET /auth/tai-khoan; liệt kê seed, đòi demo/admin, không có hash",
    "policy_dang_chay": "GET /admin/policy; trả id + policy_version + danh mục id, không nội dung",
    "hoan_policy": "POST /admin/policy; trỏ sang một file config đã có, không đọc tri thức",
    "mo_kho_break_glass": "điểm nối mở pool Postgres cho hai bảng breakglass_*; trạng thái ứng dụng, không phải kho tri thức",
    "xin_break_glass": "POST /break-glass/yeu-cau; gọi thẳng api.break_glass.xin, mức tiết lộ hỏi qua cửa quyền của citation, thân là hàng yêu cầu",
    "huy_break_glass": "POST /break-glass/yeu-cau/{id}/huy; gọi api.break_glass.huy_yeu_cau, chỉ đổi trạng thái một hàng Postgres",
    "yeu_cau_break_glass_cua_toi": "GET /break-glass/yeu-cau; gọi api.break_glass.danh_sach, liệt kê hàng của chính tài khoản, không nội dung tri thức",
    "hang_cho_break_glass": "GET /break-glass/hang-cho; gọi api.break_glass.hang_cho, hàng chờ của nhóm owner kèm dãy id vùng cấp đã qua cửa quyền của citation, không nội dung tri thức",
    "duyet_break_glass": "POST /break-glass/yeu-cau/{id}/duyet; gọi api.break_glass.duyet, đổi trạng thái một hàng và ghi một hàng grant trong một transaction, thân là hai hàng Postgres",
    "tu_choi_break_glass": "POST /break-glass/yeu-cau/{id}/tu-choi; gọi api.break_glass.tu_choi, chỉ đổi trạng thái một hàng Postgres",
    "cap_break_glass": "POST /break-glass/grant; gọi api.break_glass.cap_chu_dong, mức của gốc hỏi qua cửa quyền của citation dưới ngữ cảnh người nhận, thân là hàng grant",
}


def test_moi_ham_cua_main_deu_duoc_khai_kem_ly_do():
    """`api/main.py` không có endpoint dữ liệu nào, và test phải nói ra điều đó.

    Tới cuối Epic 1 mệnh đề AC-1.6-1 đúng một cách **rỗng**: `api/main.py` có 13
    dòng và một tuyến `/health`, nên không có gì để sai. Story 3.1 thêm ba tuyến
    xác thực, và ca này đổi hình dạng theo: từ "chỉ có health" thành "mỗi hàm
    phải khai kèm lý do nó không trả nội dung tri thức".

    Mệnh đề vẫn chưa được chứng minh, và nó **ngừng đúng ở story 3.3** - chỗ
    endpoint đầu tiên trả nội dung. Lúc đó dòng khai của nó không nói được câu
    "không chạm kho", và người viết phải thay bằng một test khẳng định nội dung
    ra khỏi endpoint đã đi qua tầng che (khoản F3 của retro Epic 1).
    """
    main = REPO_ROOT / "api" / "main.py"
    # `ast.walk`, không phải `.body`: quét cấp module bỏ lọt đúng hình dạng mà
    # ca này sinh ra để bắt - một tuyến đăng ký trong một hàm lồng, một factory
    # dựng app, hay một `include_router`. Đó là những cách tự nhiên nhất để
    # story 3.3 thêm endpoint dữ liệu, và nếu chúng không bị đòi khai thì
    # tripwire im lặng đúng lúc nó phải kêu.
    ten_ham = {
        n.name
        for n in ast.walk(_cay(main))
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    chua_khai = sorted(ten_ham - set(HAM_MAIN_CO_LY_DO))
    assert not chua_khai, (
        "`api/main.py` có hàm mới chưa khai trong `HAM_MAIN_CO_LY_DO`. Khai kèm"
        " lý do, và trả lời được câu nội dung ra khỏi nó đã đi qua tầng che chưa"
        f" (AC-1.6-1, khoản F3 của retro Epic 1). Hàm chưa khai: {chua_khai}"
    )
    chet = sorted(set(HAM_MAIN_CO_LY_DO) - ten_ham)
    assert not chet, (
        "Dòng khai trỏ vào hàm không còn tồn tại; gỡ nó đi, một miễn trừ chết là"
        f" một dòng không ai dám xóa vì không ai biết nó còn canh gì: {chet}"
    )


def test_main_khong_dung_ngu_canh_quyen_nao():
    """Đường xác thực không dựng ngữ cảnh quyền, và không đọc tri thức.

    Vế cụ thể của "chưa có endpoint dữ liệu": story 3.1 phát token, còn việc đổi
    một token thành `PermissionContext` là của story 3.3 - và khi đó nó phải đi
    qua `core.identity.ngu_canh_cua`, thứ `tests/test_import_lint.py` đã canh.
    Ca này đỏ nếu `api/main.py` tự dựng ngữ cảnh trước lúc ấy.
    """
    cham = _ten_duoc_nhap(REPO_ROOT / "api" / "main.py") & (TEN_DUNG_NGU_CANH | TEN_DUNG_NGU_CANH_PHU)
    assert not cham, f"`api/main.py` chạm ngữ cảnh quyền: {sorted(cham)}"


# Tên **dựng** một ngữ cảnh quyền. `use_context`/`current_context` không nằm ở
# đây vì chúng chỉ mở và đọc một ngữ cảnh đã có; `PermissionContext` thì có, vì
# gọi thẳng lớp ấy là đúng đường vòng mà `tests/test_import_lint.py` cấm.
TEN_DUNG_NGU_CANH: frozenset[str] = frozenset(
    {"user_context", "system_context", "PermissionContext", "ngu_canh_cua"}
)
# Tên chỉ *dùng* một ngữ cảnh. Tách khỏi tập trên để ca dưới nói được hai mệnh
# đề khác nhau: ai dựng, và ai chỉ mở.
TEN_DUNG_NGU_CANH_PHU: frozenset[str] = frozenset({"use_context", "current_context"})

# Module `api/` được phép dựng ngữ cảnh quyền, kèm lý do. **Đúng một dòng**, và
# đó là mệnh đề: một request người dùng dựng ngữ cảnh của nó ở đúng một chỗ, nên
# không có chỗ thứ hai để một luật quyền trôi tới.
DUNG_NGU_CANH_CO_LY_DO: dict[str, str] = {
    "api/hoi_dap.py": (
        "endpoint hỏi đáp dựng PermissionContext từ claim JWT, một lần mỗi"
        " request, qua đúng cửa core.identity.ngu_canh_cua"
    ),
}


def test_chi_mot_module_api_dung_ngu_canh_quyen():
    """Đúng một module `api/` dựng ngữ cảnh quyền, và mọi module khác thì không.

    Chặt hơn ca ngay trên: nó nói về `api/main.py`, còn ca này nói về cả gói.
    Một module `api/` thứ hai dựng ngữ cảnh là hai chỗ quyết định vai của một
    request, và lần sửa sau chỉ sửa một.
    """
    vi_pham = []
    for py in _module_api():
        ten = _ten(py)
        if ten in DUNG_NGU_CANH_CO_LY_DO:
            continue
        cham = _ten_duoc_nhap(py) & TEN_DUNG_NGU_CANH
        if cham:
            vi_pham.append(f"{ten} dựng ngữ cảnh quyền qua {sorted(cham)}")
    assert not vi_pham, (
        "Module `api/` dựng ngữ cảnh quyền mà chưa khai trong"
        " `DUNG_NGU_CANH_CO_LY_DO` (NFR-10, khoản ledger 1.2).\n  "
        + "\n  ".join(vi_pham)
    )
    for ten, ly_do in sorted(DUNG_NGU_CANH_CO_LY_DO.items()):
        py = REPO_ROOT / ten
        assert py.exists(), f"khai trỏ vào file không có: {ten}"
        assert ly_do.strip(), f"{ten} khai mà không có lý do"
        assert _ten_duoc_nhap(py) & TEN_DUNG_NGU_CANH, (
            f"{ten} không còn dựng ngữ cảnh quyền; gỡ nó khỏi `DUNG_NGU_CANH_CO_LY_DO`"
        )


def test_module_dung_ngu_canh_chi_dung_duoc_ngu_canh_vai():
    """Lớp thứ ba của NFR-10: module ấy dựng được **ngữ cảnh vai** và không hơn.

    Hai lớp đầu là `tests/test_import_lint.py` (danh sách trắng
    `CHO_PHEP_SYSTEM_CONTEXT` phía module) và `core.permission.use_context`
    (`SystemContextNested`, ngữ cảnh hệ thống sinh ra *giữa chừng*). Lớp này
    chặn một ngữ cảnh hệ thống **đến từ ngoài**, đúng chỗ khoản ledger 1.2 chỉ:
    tầng handler.

    Hai vế. Vế tĩnh: module không nhập `system_context` và cũng không nhập
    `user_context` - nó đi qua đúng `core.identity.ngu_canh_cua`, cửa duy nhất
    hợp lệ, thứ đọc bảng chính sách thay vì nhận một `allowed_keys` bịa ra. Vế
    chạy được nằm ở `tests/test_hoi_dap.py`: một `ngu_canh_cua` bị thay để trả
    ngữ cảnh hệ thống thì handler từ chối chứ không truy hồi thô.
    """
    for ten in sorted(DUNG_NGU_CANH_CO_LY_DO):
        nhap = _ten_duoc_nhap(REPO_ROOT / ten)
        assert "system_context" not in nhap, f"{ten} nhập system_context"
        assert "user_context" not in nhap, (
            f"{ten} nhập thẳng `user_context`: cửa hợp lệ của `api/` là"
            " `core.identity.ngu_canh_cua`, thứ đổi `KeyError` của một vai lạ"
            " thành `RoleUnknown` có `code` (AD-8)"
        )
        assert "ngu_canh_cua" in nhap, f"{ten} khai là chỗ dựng ngữ cảnh mà không nhập cửa nào"


# Tuyến của `api/main.py` **không** đi qua cửa xác thực, kèm lý do. Hai dòng,
# và cả hai là ngoại lệ có lập luận chứ không phải chỗ chưa làm. Danh mục
# **đóng**: mọi tuyến khác đăng ký vào `api.main.cua_dong` và nhận cửa từ
# framework, nên thêm một dòng ở đây là một quyết định mở một endpoint.
TUYEN_KHONG_XAC_THUC: dict[str, str] = {
    "/health": "healthcheck của compose; một healthcheck đòi token là một container không bao giờ healthy",
    "/auth/login": "chính là chỗ phát token, nên nó không thể đòi một token có sẵn",
}


def _trai_phang(cac):
    """Tuyến thật sự phục vụ được, duỗi qua mọi lớp `include_router`.

    FastAPI 0.141 không chép tuyến của một router vào `app.routes` lúc
    `include_router` nữa; nó để lại một `_IncludedRouter` và dựng danh sách thật
    khi cần (`effective_candidates()`). Duyệt `app.routes` mà không duỗi lớp đó
    cho một danh sách **không có tuyến nào của mình** - và một ca "mọi tuyến đều
    có cửa" chạy trên danh sách rỗng thì xanh vĩnh viễn.
    """
    for t in cac:
        if hasattr(t, "effective_candidates"):
            yield from _trai_phang(t.effective_candidates())
        elif getattr(t, "path", None) is not None and getattr(t, "endpoint", None) is not None:
            yield t
        elif hasattr(t, "routes"):
            yield from _trai_phang(t.routes)


# Bốn tuyến FastAPI tự thêm khi `docs_url`/`redoc_url`/`openapi_url` còn mặc
# định. Chúng vào thẳng `app.router`, không qua `cua_dong`, nên chúng là bốn
# tuyến không xác thực mà `cua_mo` không khai.
TUYEN_TAI_LIEU_TU_DONG: frozenset[str] = frozenset(
    {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)


def _tuyen_cua_app() -> list:
    """Mọi tuyến của `api/main.py`, không loại trừ gì.

    Bản trước lọc bỏ bốn tuyến tài liệu của `TUYEN_TAI_LIEU_TU_DONG` trước khi
    chấm, nên ca "mọi tuyến đều qua cửa" xanh vĩnh viễn trong khi
    `/openapi.json` thật sự trả 200 không token (retro Epic 3, F1). Nay
    `api/main.py` tắt cả ba tham số, `test_khong_co_tuyen_tai_lieu_tu_dong`
    khẳng định bốn tuyến ấy không còn, và ca này chấm trên danh sách đầy đủ -
    bật lại một tham số là ca dưới đỏ chứ không phải lặng.
    """
    from api.main import app

    tuyen = list(_trai_phang(app.routes))
    # Danh sách rỗng là cách im lặng nhất mà ba ca dưới có thể hỏng: chúng đều
    # là "không tuyến nào vi phạm", nên không tuyến nào cũng là xanh.
    assert tuyen, "không đọc được tuyến nào của `api/main.py`"
    return tuyen


def test_khong_co_tuyen_tai_lieu_tu_dong():
    """`/openapi.json`, `/docs`, `/redoc` không tồn tại, và không trả 200 cho ai.

    Hai vế vì một vế không đủ. Vế cấu trúc bắt được lần ai đó bỏ một tham số
    `*_url=None`; vế HTTP bắt được lần một tuyến tài liệu quay lại bằng một
    đường khác (một router phụ, một middleware phục vụ tĩnh). Cổng 8000 publish
    công khai, nên một bản đồ API trả 200 không token là bề mặt thật chứ không
    phải một chi tiết nội bộ - và nó không nằm trong bốn giới hạn mà ADR-022
    nhận.
    """
    from fastapi.testclient import TestClient

    from api.main import app

    co = sorted(t.path for t in _tuyen_cua_app() if t.path in TUYEN_TAI_LIEU_TU_DONG)
    assert not co, (
        f"FastAPI đang phơi {co} ngoài `cua_dong`. Dựng `FastAPI(...)` với"
        " `docs_url=None, redoc_url=None, openapi_url=None` như `api/man_nap.py`;"
        " nếu cố ý mở thì khai vào `TUYEN_KHONG_XAC_THUC` kèm lý do và ghi vào"
        " mục giới hạn của ADR-022."
    )

    khach = TestClient(app, raise_server_exceptions=False)
    for duong in sorted(TUYEN_TAI_LIEU_TU_DONG):
        assert khach.get(duong).status_code == 404, f"{duong} còn phục vụ được"


def _cua_khai_o_tuyen(tuyen) -> bool:
    """Tuyến có mang `Depends(_claim)` **khai ở chính tuyến** hay không.

    Đọc `route.dependencies`, tức danh sách mà router và decorator truyền vào -
    không phải `route.dependant`, thứ còn gom cả dependency của tham số handler.
    Phân biệt ấy là cả nội dung của ca: cửa phải đứng ở tuyến trước khi thân hàm
    chạy, chứ không phải là một tham số mà handler sau nhớ khai.
    """
    from api.main import _claim

    return any(
        getattr(d, "dependency", None) is _claim
        for d in getattr(tuyen, "dependencies", ())
    )


def test_moi_tuyen_deu_di_qua_cua_xac_thuc_tru_hai_ngoai_le_co_ly_do():
    """Cửa xác thực **mặc định đóng**, và ca này chấm cơ chế chứ không chấm thân hàm.

    Story 3.1 để cửa ở dạng opt-in: mỗi handler tự gõ `await _claim(request)`,
    và ca này truy ngược tên hàm trong AST của riêng `api/main.py`. Hai chỗ hở:
    một handler quên gõ dòng ấy là một endpoint mở, và một handler sống ở module
    khác vào bằng `include_router` thì `endpoint.__name__` không nằm trong tập
    tên quét được nên thông điệp nói sai nguyên nhân.

    Nay tuyến đóng đăng ký vào `api.main.cua_dong`, router mang
    `Depends(_claim)`, nên cửa là mặc định của framework. Ca này duyệt
    `app.routes` và hỏi từng tuyến có mang cửa ấy không; tuyến nào không mang
    phải khai trong `TUYEN_KHONG_XAC_THUC`. Nó đọc tuyến thật sự được đăng ký
    nên nó không quan tâm handler sống ở module nào.
    """
    ho = [
        f"{t.path} -> {getattr(t.endpoint, '__name__', t.endpoint)!r}"
        for t in _tuyen_cua_app()
        if t.path not in TUYEN_KHONG_XAC_THUC and not _cua_khai_o_tuyen(t)
    ]
    assert not ho, (
        "Tuyến không mang `Depends(_claim)` và không khai trong"
        " `TUYEN_KHONG_XAC_THUC`. Cửa xác thực là mặc định đóng: đăng ký tuyến"
        " vào `api.main.cua_dong` thay vì vào `app` hay `cua_mo`, hoặc khai nó"
        f" là ngoại lệ kèm lý do:\n  " + "\n  ".join(ho)
    )


def test_hai_tuyen_mo_that_su_khong_mang_cua():
    """Chiều ngược lại: danh mục mở phải mô tả đúng hiện trạng.

    Một tuyến khai là ngoại lệ mà thật ra vẫn mang cửa là một dòng nói sai về
    hệ, và nó làm người đọc tin rằng `/health` đòi token trong khi không.
    """
    sai = [
        t.path
        for t in _tuyen_cua_app()
        if t.path in TUYEN_KHONG_XAC_THUC and _cua_khai_o_tuyen(t)
    ]
    assert not sai, f"khai là ngoại lệ nhưng vẫn mang cửa xác thực: {sai}"


def test_them_mot_tuyen_khong_khai_va_khong_co_cua_thi_ca_tren_do():
    """Đột biến chạy được, không phải một lời hứa trong docstring.

    Dựng một app mang đúng hình dạng sai mà ca trên sinh ra để bắt - một tuyến
    đăng ký thẳng vào `app`, không vào `cua_dong` và không khai ngoại lệ - rồi
    khẳng định phép chấm trả về "hở". Không có ca này thì `_cua_khai_o_tuyen`
    có thể trả `True` cho mọi thứ và ca trên vẫn xanh.
    """
    from fastapi import FastAPI

    dot_bien = FastAPI()

    @dot_bien.get("/tuyen-quen-cua")
    async def _quen() -> dict:
        return {}

    tuyen = [t for t in dot_bien.routes if getattr(t, "path", "") == "/tuyen-quen-cua"]
    assert len(tuyen) == 1
    assert _cua_khai_o_tuyen(tuyen[0]) is False
    assert tuyen[0].path not in TUYEN_KHONG_XAC_THUC


def test_hai_ngoai_le_khong_xac_thuc_van_la_tuyen_co_that():
    """Một miễn trừ chết là một dòng không ai dám xóa vì không ai biết nó canh gì."""
    co_that = {t.path for t in _tuyen_cua_app()}
    thieu = sorted(set(TUYEN_KHONG_XAC_THUC) - co_that)
    assert not thieu, f"khai trỏ vào tuyến không còn tồn tại: {thieu}"
    for duong, ly_do in TUYEN_KHONG_XAC_THUC.items():
        assert ly_do.strip(), f"{duong} khai mà không có lý do"
