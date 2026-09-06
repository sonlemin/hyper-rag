"""App FastAPI của tiến trình phục vụ: `/health`, xác thực, hoán policy (3.1/3.2).

Story 1.1 để lại đúng 13 dòng và một tuyến `/health`. Story này thêm nửa xác
thực của FR-17: một lifespan mở bảng `users`, một endpoint phát JWT, và một cửa
đọc claim cho endpoint đòi quyền demo/admin.

**Story 3.3 nối engine tri thức vào lifespan, và nó chỉ đọc.** Lifespan mở bốn
thứ theo thứ tự: bảng `users` (3.1), bảng `audit_log` (3.2), rồi engine truy
hồi - engine sau audit vì wrapper LLM cần một `AuditPort` lúc dựng. Nó **không**
gọi `khoi_tao()`: dựng collection, payload index và ràng buộc graph là việc của
đường nạp, và cửa duy nhất mở cờ bỏ-filter nằm ở `core/system_context.py` với
một danh sách trắng import canh giữ. Nhờ bỏ bước đó, phát biểu của NFR-10 mạnh
hơn một phép kiểm: **tiến trình phục vụ không có đường import nào tới một ngữ
cảnh hệ thống**. Lo ngại cũ của ledger 1.7 ("ba kết nối phải khỏe trước khi một
người đăng nhập được") không xảy ra: dựng `EngineACL` không mở socket nào, cả
`AsyncQdrantClient` lẫn driver Neo4j đều mở pool lười.

**Cửa xác thực mặc định đóng.** Tuyến đăng ký vào `cua_dong`, và router đó
mang `Depends(_claim)` nên mọi tuyến của nó đi qua cửa bằng cơ chế của
framework. Trước đó cửa là opt-in: mỗi handler tự gõ `await _claim(request)`
trong thân hàm, và một dòng bị quên là một endpoint không xác thực mà không cơ
chế nào cản. Hai tuyến được mở phải khai vào `cua_mo` và có lý do, hôm nay đúng
hai: `/health` là healthcheck của compose (một healthcheck đòi token là một
container không bao giờ `healthy`), và `/auth/login` chính là chỗ phát token nên
nó không thể đòi một token có sẵn.

**Endpoint dữ liệu đầu tiên vào ở story 3.3, và ruột của nó không ở đây.**
`POST /hoi-dap` là một tuyến gọi thẳng `api.hoi_dap.tra_loi`; model thân yêu
cầu, danh mục mã lỗi, serializer envelope, engine và phép dựng ngữ cảnh quyền
đều sống ở `api/hoi_dap.py`. Nhờ vậy `api/main.py` vẫn không import một cái tên
nào của tầng ngữ cảnh quyền, và
`tests/test_api_khong_cham_tang_che.py::test_main_khong_dung_ngu_canh_quyen_nao`
giữ nguyên ý nghĩa thay vì bị xóa - cộng thêm một mệnh đề chặt hơn: **đúng một**
module `api/` dựng ngữ cảnh quyền, và nó chỉ dựng được ngữ cảnh vai.

**Story 3.2 thêm hai tuyến `/admin/policy` và một port audit.** Hoán bảng chính
sách là thao tác tầng mutation của AD-16 nên nó cần một port audit sống cùng
tiến trình; đó là Postgres, cùng cơ sở dữ liệu với bảng `users`, không phải một
trong ba kho tri thức mà Never của spec 3.2 xếp vào story 3.3. Hai tuyến chỉ
**trỏ sang một file đã có** trong `config/`: màn cấu hình FR-22 và API ghi đè
*nội dung* file policy không thuộc story này.
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from adapters.identity_seed import IdentitySeedInvalid, nap_tai_khoan
from adapters.nhom_phu_trach import bang_nhom_mac_dinh
from api import break_glass
from api import do_thi as api_do_thi
from api import hoi_dap
from api.audit_postgres import AuditPostgres
from api.che_do_do import doc_che_do_do, ghi_startup
from api.chinh_sach import KhoChinhSach, ma_policy_mac_dinh
from api.tai_khoan import KhoTaiKhoan
from api.xac_thuc import (
    ClaimNguoiHoi,
    LoiXacThuc,
    doc_token,
    doi_admin,
    doi_demo_hoac_admin,
    ghi_dang_nhap,
    khoa_ky,
    loi_dang_nhap_sai,
    phat_token,
    so_mat_khau,
    token_tu_header,
)

logger = logging.getLogger(__name__)

# Mã lỗi của ca seed không đọc được **lúc chạy**. Khác `IDENTITY_SEED_INVALID`
# của loader có chủ đích: loader nói "file hỏng", còn mã này nói "một request
# vừa hỏng vì file hỏng", và hai chuyện đó xảy ra ở hai thời điểm khác nhau -
# lifespan đã nạp seed thành công một lần rồi.
MA_SEED_KHONG_DOC_DUOC: str = "SEED_KHONG_DOC_DUOC"

# Mã của **mọi ngoại lệ chưa ai xếp loại** thoát ra khỏi một handler. Không phải
# một mã "bịa cho lỗi lạ": chỗ *phân loại* lỗi vẫn ở tầng dưới và vẫn từ chối
# đoán (`api/hoi_dap.py::loi_truy_hoi` trả `None` cho thứ nó không biết). Cái
# mã này nói một chuyện khác và đúng: mọi phản hồi lỗi của tiến trình mang hình
# dạng `{error: {code, message}}` (AD-8). Không có handler này thì một ngoại lệ
# lạ - kể cả `TypeError`/`ValueError` của chính serializer envelope - cho một
# thân `Internal Server Error` trần nằm ngoài envelope, tức đúng thứ mà cả
# story dựng ra để không xảy ra.
MA_LOI_KHONG_XAC_DINH: str = "LOI_KHONG_XAC_DINH"

# Mã của một đường dẫn hay phương thức không khớp tuyến nào. Thấy lần đầu ở
# kiểm tay story 5.1: `POST /break-glass/yeu-cau//huy` (id rỗng) ra
# `{"detail":"Not Found"}` trần của Starlette, thân duy nhất của tiến trình nằm
# ngoài envelope `{error: {code, message}}` (AD-8). Thông điệp cố định, không
# dội lại đường dẫn người gọi gửi.
MA_TUYEN_KHONG_CO: str = "TUYEN_KHONG_CO"
THONG_DIEP_TUYEN_KHONG_CO: str = "không có tuyến nào cho đường dẫn và phương thức này"

# Thông điệp **chung** của ca thân yêu cầu sai lược đồ. Ở đây chứ không ở
# `api/hoi_dap.py` vì handler phủ mọi tuyến của app, không riêng `/hoi-dap`.
THONG_DIEP_THAN_YEU_CAU_LA: str = "thân yêu cầu không đúng lược đồ của endpoint này"

THONG_DIEP_LOI_KHONG_XAC_DINH: str = "lỗi không xác định phía máy chủ"


async def mo_kho_tai_khoan() -> KhoTaiKhoan:
    """Mở bảng `users` cho tiến trình; hàm riêng để test thay bằng bản giả.

    Cùng khuôn với `api.man_nap.mo_audit`: một điểm nối tên được, thay vì một
    lời gọi nằm giữa lifespan mà không có cách nào chen vào.

    `khoi_tao()` hỏng thì pool đã mở phải được đóng trước khi dội tiếp. Không
    đóng thì một `JWT_SECRET` đúng cộng một DDL hỏng để lại một pool asyncpg
    treo trong một tiến trình sắp chết, và trong bộ test nó thành một cảnh báo
    "Task was destroyed but it is pending" xa chỗ gây ra.
    """
    kho = await KhoTaiKhoan.mo()
    try:
        await kho.khoi_tao()
    except BaseException:
        await kho.dong()
        raise
    return kho


async def mo_audit() -> AuditPostgres:
    """Mở port audit của tiến trình; hàm riêng để test thay bằng bản giả.

    Cùng khuôn với `mo_kho_tai_khoan` ngay trên và với `api.man_nap.mo_audit`.
    Mở **một lần cho cả tiến trình** chứ không một lần mỗi request: hoán policy
    là thao tác hiếm, nhưng một pool asyncpg dựng rồi vứt ở mỗi lời gọi là một
    pool không ai đóng khi handler dội lỗi.
    """
    audit = await AuditPostgres.mo()
    try:
        await audit.khoi_tao()
    except BaseException:
        await audit.dong()
        raise
    return audit


async def mo_kho_break_glass() -> break_glass.KhoBreakGlass:
    """Mở hai bảng break-glass (story 5.1); hàm riêng để test thay bằng bản giả.

    Cùng khuôn với hai hàm trên: một điểm nối tên được, mở **một lần cho cả
    tiến trình**, và `khoi_tao()` hỏng thì pool đã mở phải đóng trước khi dội
    tiếp - không đóng là một pool asyncpg treo lại trong một tiến trình sắp
    chết. Mở **sau** audit (đường xin ghi audit mutation bên trong transaction
    của nó) và **sau** bảng `users` (DDL khóa ngoại về `users(account)`), đóng
    **trước** audit ở `finally`.
    """
    kho = await break_glass.KhoBreakGlass.mo()
    try:
        await kho.khoi_tao()
    except BaseException:
        await kho.dong()
        raise
    return kho


@asynccontextmanager
async def vong_doi(app: FastAPI):
    """Khởi động: kiểm cấu hình, rồi mở bốn tài nguyên theo thứ tự. Tắt: đóng ngược.

    Thứ tự mở là nội dung: bảng `users` (3.1, đổ seed ngay sau) -> port audit
    (3.2, ghi hàng `startup`) -> kho break-glass (5.1, cần audit vì nó ghi
    mutation trong transaction, cần `users` vì khóa ngoại) -> engine truy hồi
    (3.3, wrapper LLM cần audit lúc dựng). Đóng theo thứ tự ngược, lồng
    `try/finally` để một `dong()` nổ không bỏ sót cái sau nó, ở cả nhánh lỗi
    khởi động lẫn nhánh tắt.

    Kiểm khóa ký **trước** khi mở kết nối nào: thiếu `JWT_SECRET` là một lỗi cấu
    hình, và nó phải nổ ở giây đầu tiên chứ không phải ở lần đăng nhập đầu tiên,
    lúc đó nó trông giống một sự cố kho.

    Đồng bộ seed mỗi lần khởi động, một chiều từ `config/tai-khoan.yaml` xuống
    bảng. Idempotent, nên khởi động lại không đổi gì; sửa seed thì lần khởi động
    sau là đủ, và không có đường nào ghi ngược lên file.
    """
    app.state.khoa_ky = khoa_ky()
    # Nạp bảng nhóm phụ trách **lúc khởi động**, cùng lý do với việc kiểm khóa
    # ký ở dòng trên. `bang_nhom_mac_dinh` nạp lười ở lần đọc đầu, tức lần đầu
    # một bản ghi đi qua tầng che - nên một `config/nhom-phu-trach.yaml` hỏng
    # sẽ làm mọi truy hồi nổ giữa chừng thay vì làm tiến trình chết ở giây đầu.
    # Đây là một lời gọi cấu hình, không phải một đường đọc tri thức.
    bang_nhom_mac_dinh()
    # Nạp policy **trước** khi mở kết nối nào, cùng lý do với hai lời gọi trên:
    # một `config/policy-*.yaml` hỏng hay một `HYPER_RAG_POLICY_ID` gõ sai là
    # lỗi cấu hình, và nó phải nổ ở giây đầu chứ không ở request đầu tiên dựng
    # ngữ cảnh quyền - lúc đó nó trông giống một sự cố kho.
    app.state.kho_chinh_sach = KhoChinhSach.nap(ma_policy_mac_dinh())
    logger.info(
        "bảng chính sách %r, policy_version %s",
        app.state.kho_chinh_sach.ma,
        app.state.kho_chinh_sach.hien_tai().policy_version[:12],
    )
    # Cờ chế độ đo (story 3.6, ADR-017): đọc **đúng một lần**, ở đây, trước mọi
    # kết nối - một giá trị lạ là lỗi cấu hình và chết cùng nhịp với một id
    # policy gõ sai. Không có endpoint bật/tắt.
    app.state.che_do_do = doc_che_do_do()
    kho = await mo_kho_tai_khoan()
    app.state.kho_tai_khoan = kho
    audit = None
    kho_bg = None
    engine = None
    try:
        so = await kho.dong_bo(nap_tai_khoan())
        audit = await mo_audit()
        # Hàng `startup` tầng mutation, **sau** khi audit mở và **trước** khi
        # engine dựng: bảng nào đang chạy, cờ đo thế nào. Ghi hỏng thì tiến
        # trình không lên, đóng ngược ở nhánh dưới.
        await ghi_startup(audit, app.state.kho_chinh_sach, app.state.che_do_do)
        # Kho break-glass (5.1) mở sau audit: đường xin ghi audit mutation bên
        # trong transaction của nó, nên port audit phải có trước.
        kho_bg = await mo_kho_break_glass()
        # Engine mở **sau** audit vì wrapper LLM cần một `AuditPort` lúc dựng
        # (`bo_llm`/`bo_embedding` ghi sự kiện chi phí), và đóng **trước** audit
        # ở `finally` bên dưới - thứ tự ngược của thứ tự mở.
        engine = await hoi_dap.mo_engine(audit)
    except BaseException:
        # `nap_tai_khoan()`, `dong_bo` và hai bước mở đều hỏng được (seed sai,
        # DB rớt giữa transaction, thiếu key provider). Không đóng ở đây là rò
        # đúng cái mà `finally` bên dưới lo, chỉ khác là `finally` chưa chạy vì
        # `yield` chưa tới.
        #
        # Đóng theo thứ tự ngược **và lồng `try/finally`**, đúng khuôn nhánh
        # `finally` bên dưới: một `audit.dong()` nổ mà không lồng thì
        # `kho.dong()` không bao giờ chạy và pool asyncpg nằm lại trong một
        # tiến trình sắp chết - đúng thứ nhánh này tồn tại để tránh. Mỗi bước tự
        # chịu ca "chưa mở được" bằng một phép kiểm `None`.
        try:
            if engine is not None:
                await engine.dong()
        finally:
            try:
                if kho_bg is not None:
                    await kho_bg.dong()
            finally:
                try:
                    if audit is not None:
                        await audit.dong()
                finally:
                    await kho.dong()
        raise
    app.state.audit = audit
    app.state.kho_break_glass = kho_bg
    app.state.engine = engine
    logger.info("đồng bộ %d tài khoản seed vào bảng users", so)
    try:
        yield
    finally:
        try:
            await engine.dong()
        finally:
            try:
                await kho_bg.dong()
            finally:
                try:
                    await audit.dong()
                finally:
                    await kho.dong()


app = FastAPI(title="hyper-rag-copilot", lifespan=vong_doi)


@app.exception_handler(LoiXacThuc)
async def _loi_xac_thuc(request: Request, loi: LoiXacThuc) -> JSONResponse:
    """Mã lỗi API là `{error: {code, message}}` (Consistency Conventions).

    Thân phản hồi dựng **chỉ** từ `ma` và `thong_diep`, hai giá trị đến từ một
    tập hằng đóng trong `api/xac_thuc.py`. Nhờ vậy ca "tài khoản lạ" và ca "sai
    mật khẩu" ra hai chuỗi byte giống hệt nhau, thứ mà một thông điệp ghép tên
    tài khoản vào sẽ phá ngay.
    """
    return JSONResponse(
        status_code=loi.http,
        content={"error": {"code": loi.ma, "message": loi.thong_diep}},
    )


@app.exception_handler(RequestValidationError)
async def _than_yeu_cau_la(request: Request, loi: RequestValidationError) -> JSONResponse:
    """Thân yêu cầu sai lược đồ là 400 đúng envelope, không phải 422 thô.

    Mặc định của FastAPI là HTTP 422 với thân `{"detail": [...]}`: không có
    `code` nào để test assert lên (AD-8, Consistency Conventions), và mỗi mục
    `detail` còn mang `loc`/`input`, tức nó dội lại nguyên văn thứ người gọi vừa
    gửi. Ở đây một mã ổn định và một thông điệp cố định.

    Handler đăng ký trên `app` chứ không trên router, nên nó phủ cả tuyến mở lẫn
    tuyến đóng: một tuyến mới quên nghĩ tới ca này vẫn ra đúng envelope. Vì phủ
    mọi tuyến nên thông điệp phải **chung**, không mô tả hợp đồng của một tuyến:
    hôm nay chỉ `/hoi-dap` khai một thân pydantic, nhưng tuyến thứ hai khai một
    thân như thế sẽ trả lời bằng một câu nói về `cau_hoi` nếu thông điệp mượn
    của `api/hoi_dap.py`.

    Không lời gọi LLM nào chạy trước nó: lược đồ thân kiểm trong
    `solve_dependencies`, trước thân handler.
    """
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": hoi_dap.MA_THAN_YEU_CAU_LA,
                "message": THONG_DIEP_THAN_YEU_CAU_LA,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def _tuyen_khong_co(request: Request, loi: StarletteHTTPException) -> JSONResponse:
    """404/405 của router (đường dẫn hay phương thức không khớp tuyến) ra đúng envelope.

    Không handler nào của dự án dội `HTTPException` (lỗi của dự án là
    `LoiXacThuc` và lớp con), nên mọi ngoại lệ tới đây là của chính Starlette
    khi không tìm được tuyến. Giữ mã HTTP của nó, thay thân bằng một mã ổn định
    và một thông điệp cố định: thân mặc định `{"detail": "Not Found"}` là hình
    dạng duy nhất trong tiến trình không mang `code` để test assert lên (AD-8).
    """
    return JSONResponse(
        status_code=loi.status_code,
        content={"error": {"code": MA_TUYEN_KHONG_CO, "message": THONG_DIEP_TUYEN_KHONG_CO}},
    )


@app.exception_handler(Exception)
async def _loi_khong_xac_dinh(request: Request, loi: Exception) -> JSONResponse:
    """Mọi ngoại lệ chưa ai xếp loại vẫn ra `{error: {code, message}}` (AD-8).

    Hai chuyện khác nhau, và handler này chỉ làm chuyện thứ hai. **Không bịa
    một mã cho một lỗi chưa ai xếp loại** - việc đó vẫn do tầng dưới quyết, và
    `api/hoi_dap.py::loi_truy_hoi` cố ý trả `None` cho thứ nó không biết, vì
    gán một mã sẵn có là làm mất chính thông tin cần để xếp loại nó lần sau.
    Chuyện thứ hai là **hình dạng**: một thân `Internal Server Error` trần nằm
    ngoài envelope là một client phải viết hai đường đọc lỗi, và nó là hình
    dạng duy nhất trong cả tiến trình không mang `code` để test assert lên.

    Nguyên lỗi vào log (`logger.exception`), ra ngoài là một thông điệp cố
    định: đường dẫn hệ thống, tên container và tên biến môi trường không đi ra
    theo một lỗi 500.

    Đăng ký trên `app` nên nó là lưới cuối; hai handler hẹp hơn
    (`LoiXacThuc`, `RequestValidationError`) vẫn được chọn trước theo luật khớp
    loại của Starlette.
    """
    logger.exception("lỗi không xác định khi phục vụ %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": MA_LOI_KHONG_XAC_DINH,
                "message": THONG_DIEP_LOI_KHONG_XAC_DINH,
            }
        },
    )


async def _claim(request: Request) -> ClaimNguoiHoi:
    """Claim của token trong header `Authorization`; mọi ca hỏng là một mã.

    Vừa là dependency của `cua_dong` (nên nó chạy trước mọi handler đóng, kể cả
    handler không cần đọc claim), vừa là dependency của tham số ở hai handler
    cần chính giá trị ấy. FastAPI nhớ kết quả trong một request nên nó chỉ chạy
    một lần, và không có đường nào để hai lớp đọc hai token khác nhau.
    """
    return doc_token(
        token_tu_header(request.headers.get("authorization")),
        request.app.state.khoa_ky,
    )


# Hai router, và sự khác nhau giữa chúng là **cơ chế** chứ không phải quy ước.
# `cua_dong` là chỗ mặc định của một tuyến mới: nó mang `Depends(_claim)` nên
# tuyến nào vào đây cũng đòi token mà người viết không phải nhớ gõ gì. `cua_mo`
# là danh mục **đóng** của ngoại lệ, hôm nay đúng hai tuyến kèm lý do ở docstring
# đầu file, và `tests/test_api_khong_cham_tang_che.py` đòi tập tuyến không có cửa
# đúng bằng danh mục đó.
cua_mo = APIRouter()
cua_dong = APIRouter(dependencies=[Depends(_claim)])

# Claim đã kiểm, dùng làm tham số của handler cần đọc chính nó.
Claim = Annotated[ClaimNguoiHoi, Depends(_claim)]


@cua_mo.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@cua_mo.post("/auth/login")
async def dang_nhap(request: Request) -> dict:
    """Đổi tài khoản + mật khẩu lấy một JWT HS256 sống 12 giờ.

    Thân request hỏng, thiếu trường, sai kiểu đều trả về đúng `DANG_NHAP_SAI`
    như hai ca đăng nhập sai thật. Để FastAPI tự sinh 422 cho chúng là một thân
    phản hồi *khác* thoát ra khỏi envelope `{error: {code, message}}`, và là một
    cách phân biệt "gõ sai tên trường" với "gõ sai mật khẩu" mà người ngoài đọc
    được.

    Tài khoản không tồn tại vẫn đi qua đúng một phép bcrypt (`so_mat_khau` với
    hash `None`), nên thời gian đáp ứng của hai nhánh bằng nhau.

    Mọi nhánh, đúng lẫn sai, ghi một hàng `auth_login` best-effort (story 3.6):
    `act` là tên gõ vào (`None` khi thân hỏng), `chi_tiet.ket_qua` là kết cục,
    không trường nào nói vì sao sai. Audit hỏng là WARNING, đăng nhập vẫn chạy
    và thân response không đổi một byte.
    """
    audit = request.app.state.audit
    policy_version = request.app.state.kho_chinh_sach.hien_tai().policy_version
    try:
        than = await request.json()
    except Exception:
        than = None
    ten = than.get("tai_khoan") if isinstance(than, dict) else None
    mat_khau = than.get("mat_khau") if isinstance(than, dict) else None
    if not isinstance(ten, str) or not isinstance(mat_khau, str):
        await ghi_dang_nhap(
            audit,
            ten=ten if isinstance(ten, str) else None,
            thanh_cong=False,
            policy_version=policy_version,
        )
        raise loi_dang_nhap_sai()

    dong = await request.app.state.kho_tai_khoan.tra(ten)
    # bcrypt cost 12 là ~0,2-0,3 giây CPU **đồng bộ**. Gọi thẳng trong một
    # handler `async def` là chặn event loop suốt thời gian đó, nên một vòng dò
    # mật khẩu làm nghẽn mọi request khác của tiến trình - kể cả `/health`, tức
    # container rơi khỏi `healthy` vì một người gõ sai mật khẩu. Đẩy sang
    # threadpool giữ nguyên tính chất hai nhánh tốn cùng thời gian, vì cả hai
    # nhánh đi qua đúng lời gọi này.
    khop = await anyio.to_thread.run_sync(
        so_mat_khau, mat_khau, dong.mat_khau_hash if dong else None
    )
    await ghi_dang_nhap(audit, ten=ten, thanh_cong=bool(khop), policy_version=policy_version)
    if not khop:
        raise loi_dang_nhap_sai()

    token = phat_token(
        sub=dong.account,
        role=dong.role,
        space=dong.khong_gian,
        demo=dong.demo,
        admin=dong.admin,
        khoa=request.app.state.khoa_ky,
    )
    return {"token": token, "token_type": "bearer"}


@cua_dong.get("/auth/toi")
async def toi(c: Claim) -> dict:
    """Claim của chính token đang cầm: ai, vai gì, không gian nào, cờ nào.

    Không chạm kho tri thức và không dựng ngữ cảnh quyền: nó chỉ đọc lại thứ đã
    ký. Web dùng nó để biết hiện đang là ai sau khi tải lại trang, và bộ test
    dùng nó để chấm ca "token thiếu / hết hạn / sai chữ ký" tách khỏi ca thiếu
    quyền demo/admin.
    """
    return {
        "tai_khoan": c.sub,
        "vai": c.role,
        "khong_gian": c.space,
        "demo": c.demo,
        "admin": c.admin,
    }


@cua_dong.get("/auth/tai-khoan")
async def danh_sach_tai_khoan(c: Claim) -> dict:
    """Danh sách tài khoản seed - **đòi `demo` hoặc `admin`** (nền FR-18).

    Người tiêu thụ đầu tiên của cửa quyền hai cờ: nhịp demo và cổng M2 (story
    3.8) cần liệt kê "hai tài khoản, hai kết quả" mà không phải mở file cấu hình
    trên máy chủ. Một tài khoản thường gọi vào đây nhận 403, và đó là hàng I/O
    Matrix của story này.

    Đọc từ seed chứ không từ bảng `users`, và **không** trả `mat_khau_hash`: cái
    ra khỏi đây là danh mục, không phải bản sao của bảng.
    """
    doi_demo_hoac_admin(c)
    # Seed đọc lại từ đĩa ở mỗi lời gọi, nên nó hỏng được **sau** khi lifespan
    # đã nạp nó thành công một lần: ai đó sửa file trên máy chủ, hay volume
    # `config/` rớt. Để `IdentitySeedInvalid` hay `OSError` thoát ra là một 500
    # trần nằm ngoài envelope `{error: {code, message}}` mà test assert lên
    # (AD-8) - và nó còn in nguyên đường dẫn file cấu hình ra cho người gọi.
    try:
        cac_muc = nap_tai_khoan()
    except (IdentitySeedInvalid, OSError) as loi:
        logger.error("không đọc được seed tài khoản lúc phục vụ: %s", loi)
        raise LoiXacThuc(
            500,
            MA_SEED_KHONG_DOC_DUOC,
            "không đọc được danh mục tài khoản",
        ) from None
    return {
        "tai_khoan": [
            {
                "tai_khoan": m.ten,
                "vai": m.tai_khoan.danh_tinh.vai,
                "khong_gian": m.tai_khoan.danh_tinh.khong_gian,
                "nhom": m.tai_khoan.nhom,
                "demo": m.tai_khoan.demo,
                "admin": m.tai_khoan.admin,
            }
            for m in cac_muc
        ]
    }


@cua_dong.get("/admin/policy")
async def policy_dang_chay(request: Request, c: Claim) -> dict:
    """Bảng chính sách đang chạy và danh mục id hoán được - **đòi `admin`**.

    Đọc `kho.ma_va_policy()` **một lần**, không phải `ma` rồi `hien_tai()`: hai
    phép đọc là một handler có thể báo `policy_version` của bảng này và tên của
    bảng kia.
    """
    doi_admin(c)
    kho = request.app.state.kho_chinh_sach
    ma, policy = kho.ma_va_policy()
    return {
        "id": ma,
        "policy_version": policy.policy_version,
        "danh_muc": kho.danh_muc(),
    }


@cua_dong.post("/admin/policy")
async def hoan_policy(request: Request, c: Claim) -> dict:
    """Hoán sang một bảng chính sách khác trong danh mục - **đòi `admin`**.

    Nhận `{"id": "<id trong danh mục>"}`. Không nhận đường dẫn: danh mục là danh
    mục đóng suy từ glob `config/policy-*.yaml`, và một tham số đường dẫn trên
    một endpoint admin là một đường đọc file tùy ý.

    Không restart tiến trình và không chạm dữ liệu: mức tiết lộ tính lúc truy
    vấn chứ không ghi lên kho, nên hoán bảng là hoán một object trong bộ nhớ.
    Đây **không** phải FR-22: nó chỉ trỏ sang một file đã có, không ghi đè nội
    dung file nào.
    """
    doi_admin(c)
    try:
        than = await request.json()
    except Exception:
        than = None
    ma = than.get("id") if isinstance(than, dict) else None
    kho = request.app.state.kho_chinh_sach
    # `hoan` trả cả cặp, và handler đọc đúng cặp đó. Đọc lại `kho.ma` ở đây là
    # đọc trạng thái *sau* một `await`, tức có thể là bảng của một lần hoán
    # khác vừa chen vào - và khi đó phản hồi khai id của bảng này kèm
    # `policy_version` của bảng kia.
    ma_moi, policy = await kho.hoan(
        ma if isinstance(ma, str) else "",
        audit=request.app.state.audit,
        act=c.sub,
        role=c.role,
    )
    return {"id": ma_moi, "policy_version": policy.policy_version}


@cua_dong.post("/hoi-dap")
async def hoi(request: Request, than: hoi_dap.ThanHoiDap, c: Claim) -> dict:
    """Endpoint hỏi đáp, envelope AD-8 (FR-13, story 3.3).

    Tuyến ở đây, **ruột ở `api/hoi_dap.py`**: model thân, danh mục mã lỗi,
    serializer envelope, engine và phép dựng ngữ cảnh quyền đều sống ở module
    kia. Nhờ vậy `api/main.py` không import một cái tên nào của tầng ngữ cảnh
    quyền, và bộ test giữ được mệnh đề "đúng một module `api/` dựng ngữ cảnh
    quyền, và nó chỉ dựng được ngữ cảnh vai".

    Nội dung ra khỏi handler này **đã đi qua tầng che**: nó là chuỗi mà
    `kg_query` dựng từ kết quả của ba adapter, và cả ba gọi `core.masking.mask`
    trong đường trả về của mọi method đọc (AD-9). `api/` không che lại và không
    bỏ che.

    `hien_tai()` đọc **một lần** ở đây rồi truyền object xuống: hai phép đọc
    quanh một `await` là hai bản chính sách trong cùng một request (AD-3).
    """
    return await hoi_dap.tra_loi(
        than.cau_hoi,
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        engine=request.app.state.engine,
        audit=request.app.state.audit,
        che_do_do=request.app.state.che_do_do,
    )


@cua_dong.post("/do-thi")
async def do_thi(request: Request, than: api_do_thi.ThanDoThi, c: Claim) -> dict:
    """Endpoint đồ thị theo quyền, cùng envelope AD-8 (FR-19, story 3.7).

    Tuyến ở đây, **ruột ở `api/do_thi.py`** - cùng khuôn với `hoi`. Nội dung ra
    khỏi handler này đã đi qua tầng che: mỗi dòng của
    `Neo4jACLGraphStorage.do_thi_cua` qua `_che` trước khi rời adapter, và
    hyperedge ngoài quyền vắng mặt ngay trong câu Cypher. `api/` không che lại
    và không bỏ che; không lời gọi LLM nào trên đường này.

    `hien_tai()` đọc **một lần** rồi truyền object xuống, như `hoi`.
    """
    return await api_do_thi.lay_do_thi(
        than.hyperedge_ids,
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        engine=request.app.state.engine,
    )


@cua_dong.post("/break-glass/yeu-cau", status_code=201)
async def xin_break_glass(request: Request, than: break_glass.ThanXinBreakGlass, c: Claim) -> dict:
    """Tạo một yêu cầu break-glass cho một hyperedge vai đang thấy ở L1 (FR-20, story 5.1).

    Tuyến ở đây, **ruột ở `api/break_glass.py`** - cùng khuôn với `hoi` và
    `do_thi`. Không nội dung tri thức nào ra khỏi handler này: thân 201 là hàng
    yêu cầu (id, khóa quyền tách đôi, nhóm duyệt, lý do người xin vừa gõ), mức
    tiết lộ hỏi qua đúng cửa quyền của citation. `hien_tai()` đọc **một lần**.
    """
    return await break_glass.xin(
        than.hyperedge_id,
        than.ly_do,
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        engine=request.app.state.engine,
        kho=request.app.state.kho_break_glass,
        audit=request.app.state.audit,
    )


@cua_dong.post("/break-glass/yeu-cau/{id_yeu_cau}/huy")
async def huy_break_glass(request: Request, id_yeu_cau: str, c: Claim) -> dict:
    """Người xin hủy yêu cầu của chính mình khi còn chờ duyệt (story 5.1)."""
    return await break_glass.huy_yeu_cau(
        id_yeu_cau,
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        kho=request.app.state.kho_break_glass,
        audit=request.app.state.audit,
    )


@cua_dong.get("/break-glass/yeu-cau")
async def yeu_cau_break_glass_cua_toi(request: Request, c: Claim) -> dict:
    """Yêu cầu break-glass của chính tài khoản trong token, mới nhất trước (story 5.1)."""
    return await break_glass.danh_sach(
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        kho=request.app.state.kho_break_glass,
    )


@cua_dong.get("/break-glass/hang-cho")
async def hang_cho_break_glass(request: Request, c: Claim) -> dict:
    """Hàng chờ của owner: yêu cầu còn chờ của nhóm mình, cũ nhất trước, kèm `vung_cap` (story 5.2).

    Ruột ở `api/break_glass.py::hang_cho`. Nhóm của owner đọc từ bảng `users`
    (không từ thân, không từ token), vùng cấp tính dưới ngữ cảnh **người xin**
    và chỉ là dãy id đã qua cửa quyền của citation; không nội dung tri thức.
    """
    return await break_glass.hang_cho(
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        engine=request.app.state.engine,
        kho=request.app.state.kho_break_glass,
        kho_tai_khoan=request.app.state.kho_tai_khoan,
    )


@cua_dong.post("/break-glass/yeu-cau/{id_yeu_cau}/duyet")
async def duyet_break_glass(request: Request, id_yeu_cau: str, c: Claim) -> dict:
    """Owner duyệt một yêu cầu: grant ghi cùng transaction với phép chuyển trạng thái (story 5.2).

    Ruột ở `api/break_glass.py::duyet`. Không thân request: vùng cấp và thời
    hạn là quyết định của server, không nhận từ client. Thân trả về là hàng
    yêu cầu và hàng grant (id, cặp nhận, dãy id, hai mốc giờ của Postgres).
    """
    return await break_glass.duyet(
        id_yeu_cau,
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        engine=request.app.state.engine,
        kho=request.app.state.kho_break_glass,
        kho_tai_khoan=request.app.state.kho_tai_khoan,
        audit=request.app.state.audit,
    )


@cua_dong.post("/break-glass/yeu-cau/{id_yeu_cau}/tu-choi")
async def tu_choi_break_glass(
    request: Request, id_yeu_cau: str, than: break_glass.ThanTuChoi, c: Claim
) -> dict:
    """Owner từ chối một yêu cầu với lý do bắt buộc (story 5.2). Ruột ở `api/break_glass.py::tu_choi`."""
    return await break_glass.tu_choi(
        id_yeu_cau,
        than.ly_do,
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        kho=request.app.state.kho_break_glass,
        kho_tai_khoan=request.app.state.kho_tai_khoan,
        audit=request.app.state.audit,
    )


@cua_dong.post("/break-glass/grant", status_code=201)
async def cap_break_glass(request: Request, than: break_glass.ThanCapChuDong, c: Claim) -> dict:
    """Owner cấp chủ động cho một cặp `(act, role)` một gốc L1, không qua yêu cầu (story 5.2).

    Ruột ở `api/break_glass.py::cap_chu_dong`. Mức của gốc hỏi dưới ngữ cảnh
    **người nhận** qua cửa quyền của citation; owner từ bảng `users`.
    """
    return await break_glass.cap_chu_dong(
        than.act,
        than.role,
        than.hyperedge_id,
        claim=c,
        policy=request.app.state.kho_chinh_sach.hien_tai(),
        engine=request.app.state.engine,
        kho=request.app.state.kho_break_glass,
        kho_tai_khoan=request.app.state.kho_tai_khoan,
        audit=request.app.state.audit,
    )


# Đăng ký sau khi mọi tuyến đã khai, một chỗ, để đọc file này là thấy ngay tập
# tuyến mở và tập tuyến đóng.
app.include_router(cua_mo)
app.include_router(cua_dong)
