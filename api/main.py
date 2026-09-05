"""App FastAPI của tiến trình phục vụ: `/health` và cửa xác thực (story 3.1).

Story 1.1 để lại đúng 13 dòng và một tuyến `/health`. Story này thêm nửa xác
thực của FR-17: một lifespan mở bảng `users`, một endpoint phát JWT, và một cửa
đọc claim cho endpoint đòi quyền demo/admin.

**Lifespan này chỉ mở Postgres.** Engine tri thức, ba kho và audit port thuộc
story 3.3 - chỗ endpoint đầu tiên thật sự đọc tri thức. Dựng engine ở đây là
dựng một thứ chưa ai gọi, và nó kéo theo ba kết nối phải khỏe trước khi một
người đăng nhập được.

**`/health` cố ý nằm ngoài mọi cửa.** Nó là healthcheck của compose: một
healthcheck đòi token là một container không bao giờ `healthy`.

**Không có endpoint dữ liệu nào ở đây.** `tests/test_api_khong_cham_tang_che.py`
canh điều đó, và nó là chỗ story 3.3 phải dừng lại để trả lời câu "nội dung ra
khỏi handler này đã đi qua tầng che chưa".
"""

import logging
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adapters.identity_seed import IdentitySeedInvalid, nap_tai_khoan
from adapters.nhom_phu_trach import bang_nhom_mac_dinh
from api.tai_khoan import KhoTaiKhoan
from api.xac_thuc import (
    ClaimNguoiHoi,
    LoiXacThuc,
    doc_token,
    doi_demo_hoac_admin,
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


@asynccontextmanager
async def vong_doi(app: FastAPI):
    """Khởi động: kiểm khóa ký, mở bảng `users`, đổ seed. Tắt: đóng pool.

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
    kho = await mo_kho_tai_khoan()
    app.state.kho_tai_khoan = kho
    try:
        so = await kho.dong_bo(nap_tai_khoan())
    except BaseException:
        # `nap_tai_khoan()` và `dong_bo` đều hỏng được (seed sai, DB rớt giữa
        # transaction). Không đóng pool ở đây là rò đúng cái mà `finally` bên
        # dưới lo, chỉ khác là `finally` chưa chạy vì `yield` chưa tới.
        await kho.dong()
        raise
    logger.info("đồng bộ %d tài khoản seed vào bảng users", so)
    try:
        yield
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


async def _claim(request: Request) -> ClaimNguoiHoi:
    """Claim của token trong header `Authorization`; mọi ca hỏng là một mã."""
    return doc_token(
        token_tu_header(request.headers.get("authorization")),
        request.app.state.khoa_ky,
    )


@app.post("/auth/login")
async def dang_nhap(request: Request) -> dict:
    """Đổi tài khoản + mật khẩu lấy một JWT HS256 sống 12 giờ.

    Thân request hỏng, thiếu trường, sai kiểu đều trả về đúng `DANG_NHAP_SAI`
    như hai ca đăng nhập sai thật. Để FastAPI tự sinh 422 cho chúng là một thân
    phản hồi *khác* thoát ra khỏi envelope `{error: {code, message}}`, và là một
    cách phân biệt "gõ sai tên trường" với "gõ sai mật khẩu" mà người ngoài đọc
    được.

    Tài khoản không tồn tại vẫn đi qua đúng một phép bcrypt (`so_mat_khau` với
    hash `None`), nên thời gian đáp ứng của hai nhánh bằng nhau.
    """
    try:
        than = await request.json()
    except Exception:
        raise loi_dang_nhap_sai() from None
    if not isinstance(than, dict):
        raise loi_dang_nhap_sai()
    ten = than.get("tai_khoan")
    mat_khau = than.get("mat_khau")
    if not isinstance(ten, str) or not isinstance(mat_khau, str):
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


@app.get("/auth/toi")
async def toi(request: Request) -> dict:
    """Claim của chính token đang cầm: ai, vai gì, không gian nào, cờ nào.

    Không chạm kho tri thức và không dựng ngữ cảnh quyền: nó chỉ đọc lại thứ đã
    ký. Web dùng nó để biết hiện đang là ai sau khi tải lại trang, và bộ test
    dùng nó để chấm ca "token thiếu / hết hạn / sai chữ ký" tách khỏi ca thiếu
    quyền demo/admin.
    """
    c = await _claim(request)
    return {
        "tai_khoan": c.sub,
        "vai": c.role,
        "khong_gian": c.space,
        "demo": c.demo,
        "admin": c.admin,
    }


@app.get("/auth/tai-khoan")
async def danh_sach_tai_khoan(request: Request) -> dict:
    """Danh sách tài khoản seed - **đòi `demo` hoặc `admin`** (nền FR-18).

    Người tiêu thụ đầu tiên của cửa quyền hai cờ: nhịp demo và cổng M2 (story
    3.8) cần liệt kê "hai tài khoản, hai kết quả" mà không phải mở file cấu hình
    trên máy chủ. Một tài khoản thường gọi vào đây nhận 403, và đó là hàng I/O
    Matrix của story này.

    Đọc từ seed chứ không từ bảng `users`, và **không** trả `mat_khau_hash`: cái
    ra khỏi đây là danh mục, không phải bản sao của bảng.
    """
    doi_demo_hoac_admin(await _claim(request))
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
