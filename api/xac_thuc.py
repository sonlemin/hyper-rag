"""Phát và kiểm JWT, so mật khẩu bcrypt, cửa quyền demo/admin (story 3.1, FR-17).

Ở `api/` vì đây là tầng duy nhất được import `jwt` và `bcrypt` (spec 3.1
Boundaries). `core/` chỉ stdlib; `adapters/` không biết gì về phiên đăng nhập.

**Khóa ký đọc từ biến môi trường, không có mặc định và không tự sinh.** Thiếu là
từ chối khởi động kèm mã ổn định `JWT_SECRET_MISSING`. Một khóa ngẫu nhiên mỗi
lần khởi động làm mọi token đã phát chết im lặng, và trong lúc gỡ lỗi nó trông
giống hệt "token sai chữ ký".

**Một mã lỗi chung cho mọi ca đăng nhập sai.** Tài khoản không tồn tại và mật
khẩu sai trả về `DANG_NHAP_SAI` với thân byte giống hệt nhau, và ca không tồn
tại vẫn chạy đúng một phép bcrypt trên `HASH_GIA`. bcrypt cố ý chậm: một nhánh
trả về sớm nhanh hơn nhánh so hash vài chục mili giây, và chênh đó đủ để liệt kê
tài khoản nào có thật. Cùng tinh thần chống kênh dò với FR-16, khác tầng.

**Ba ca token hỏng cũng một mã.** Thiếu, hết hạn, sai chữ ký đều là
`TOKEN_KHONG_HOP_LE`. Nói ra ca nào là nói cho người cầm một token rác biết
token của họ *từng* hợp lệ, hay biết khóa ký đã đổi.

Không có claim `act` và không có đường xem-như ở đây: AD-10 và Epic 4.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from core.audit import (
    EVENT_AUTH_LOGIN,
    SPACE_TIEN_TRINH,
    TIER_OBSERVATION,
    AuditPort,
    SuKienAudit,
    ghi_quan_sat,
    thoi_diem_utc,
)

# Biến môi trường giữ khóa ký. Secret nên nó sống ở `.env` gốc repo (đã
# gitignore), không ở `.env.server`/`.env.laptop` - hai file đó chỉ mang tham số
# môi trường (Consistency Conventions "Cấu hình").
BIEN_KHOA_KY: str = "JWT_SECRET"

# Thuật toán và TTL chốt ở spine (`Xác thực`): HS256, token sống 12 giờ. Hằng ở
# đây chứ không phải biến môi trường: TTL là một quyết định bảo mật, và một
# quyết định bảo mật đọc từ môi trường là một quyết định đổi được mà không ai
# xem lại diff.
THUAT_TOAN: str = "HS256"
TTL_GIO: int = 12

# Độ dài tối thiểu của khóa ký. HS256 lấy nguyên chuỗi làm khóa HMAC, nên một
# khóa 8 ký tự là một khóa dò được ngoại tuyến từ chính token đã phát.
DAI_KHOA_TOI_THIEU: int = 32

# Hash để so khi tài khoản không tồn tại. Là một hash bcrypt thật (của một chuỗi
# ngẫu nhiên không ai biết), nên `checkpw` chạy trọn vòng cost 12 rồi trả `False`
# - đúng chi phí của nhánh có tài khoản. Một chuỗi không phải hash sẽ làm
# `checkpw` dội ngay, tức là lại nhanh hơn, tức là lại thành kênh dò.
HASH_GIA: str = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.uMWX0hlBLPXBW/QJfBk2sRFrM0f9Sm2"

MA_DANG_NHAP_SAI: str = "DANG_NHAP_SAI"
MA_TOKEN_KHONG_HOP_LE: str = "TOKEN_KHONG_HOP_LE"
MA_THIEU_QUYEN: str = "THIEU_QUYEN_DEMO_ADMIN"
# Mã **khác** của cửa chỉ-`admin` (story 3.2). Hai cửa, hai mã: một tài khoản
# `demo` bị từ chối ở đây phải đọc được rằng nó thiếu đúng cờ `admin`, chứ không
# phải rằng nó thiếu "demo hoặc admin" - thứ mà nó có. Gộp một mã là biến hai
# cửa quyền khác nhau thành một dòng log không phân biệt được.
MA_THIEU_QUYEN_ADMIN: str = "THIEU_QUYEN_ADMIN"

# Thông điệp cố định, không mang tên tài khoản. Thân phản hồi của ca "tài khoản
# lạ" và ca "sai mật khẩu" phải giống nhau **từng byte**, nên một thông điệp
# ghép tên vào là chỗ duy nhất cần để phân biệt hai ca.
THONG_DIEP_DANG_NHAP_SAI: str = "tài khoản hoặc mật khẩu không đúng"
THONG_DIEP_TOKEN: str = "token không hợp lệ"
THONG_DIEP_THIEU_QUYEN: str = "endpoint này đòi quyền demo hoặc admin"
THONG_DIEP_THIEU_QUYEN_ADMIN: str = "endpoint này đòi quyền admin"


class JwtSecretMissing(RuntimeError):
    """Thiếu khóa ký JWT trong môi trường; từ chối khởi động, không tự sinh khóa.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).
    """

    code = "JWT_SECRET_MISSING"


class LoiXacThuc(Exception):
    """Lỗi của tầng xác thực, mang mã ổn định và mã HTTP; test assert trên `ma`.

    Cùng hình dạng với `api.man_nap.LoiMan`: một lớp, một handler, và thân phản
    hồi là `{error: {code, message}}` đúng Consistency Conventions.
    """

    def __init__(self, http: int, ma: str, thong_diep: str):
        super().__init__(thong_diep)
        self.http, self.ma, self.thong_diep = http, ma, thong_diep


@dataclass(frozen=True)
class ClaimNguoiHoi:
    """Claim đã kiểm của một token: ai, vai gì, không gian nào, hai cờ quyền."""

    sub: str
    role: str
    space: str
    demo: bool
    admin: bool


def khoa_ky(moi_truong=None) -> str:
    """Khóa ký đọc từ môi trường; thiếu hoặc quá ngắn là từ chối.

    Đọc mỗi lần gọi chứ không cache ở tầng module: lifespan gọi nó một lần lúc
    khởi động để hỏng sớm, còn cache là một giá trị sống lâu hơn tiến trình test
    và làm hai bộ test lẫn nhau.
    """
    nguon = os.environ if moi_truong is None else moi_truong
    gia_tri = (nguon.get(BIEN_KHOA_KY) or "").strip()
    if not gia_tri:
        raise JwtSecretMissing(
            f"thiếu biến môi trường {BIEN_KHOA_KY}: khóa ký JWT không có mặc"
            " định và không tự sinh, vì một khóa ngẫu nhiên mỗi lần khởi động"
            " làm mọi token đã phát chết im lặng"
        )
    if len(gia_tri) < DAI_KHOA_TOI_THIEU:
        raise JwtSecretMissing(
            f"{BIEN_KHOA_KY} dài {len(gia_tri)} ký tự, tối thiểu"
            f" {DAI_KHOA_TOI_THIEU}: HS256 lấy nguyên chuỗi làm khóa HMAC nên"
            " khóa ngắn dò được ngoại tuyến từ chính token đã phát"
        )
    return gia_tri


def so_mat_khau(mat_khau: str, hash_mk: str | None) -> bool:
    """So mật khẩu với hash bcrypt; mọi cách hỏng vẫn tốn đúng một phép bcrypt.

    `hash_mk` rỗng hay `None` là ca "không có tài khoản đó" (và ca dòng bảng
    hỏng). Nó chạy `checkpw` trên `HASH_GIA` rồi trả `False`, nên hai nhánh tốn
    cùng một lượng thời gian. Trả `False` chứ không dội: nơi gọi trả cùng một
    mã lỗi cho cả hai ca.

    **Hàm này không được dội, không ca nào.** `bcrypt.checkpw` dội `ValueError`
    ở ít nhất hai đường có thật: mật khẩu dài hơn 72 byte (kiểm chứng trên
    bcrypt 5.0.0 - `password cannot be longer than 72 bytes`) và hash không
    parse được (một dòng `users.mat_khau_hash` bị sửa tay). Cả hai đi qua
    `POST /auth/login`, nên một exception thoát ra là một 500 trần nằm ngoài
    envelope `{error: {code, message}}` - và nó phân biệt được ca "mật khẩu 73
    byte của một tài khoản có thật" với ca "tài khoản lạ", tức phá đúng bất
    biến một-mã-một-thân mà hai hàng I/O Matrix dựng ra.

    Rỗng cũng phải là `None`, không được là một chuỗi để so: `("" or HASH_GIA)`
    cho `HASH_GIA`, và nếu nhánh cuối chỉ hỏi `hash_mk is not None` thì một
    dòng bảng có hash rỗng sẽ đăng nhập được bằng chính mật khẩu bí mật của
    `HASH_GIA`.
    """
    try:
        tho = mat_khau.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        tho = b""
    co_hash = isinstance(hash_mk, str) and bool(hash_mk.strip())
    try:
        that = bcrypt.checkpw(tho, (hash_mk if co_hash else HASH_GIA).encode("utf-8"))
    except ValueError:
        # Vẫn đã trả tiền một phép bcrypt trước khi dội ở ca hash hỏng; ở ca
        # mật khẩu quá dài thì `checkpw` dội trước khi băm, nhưng ca đó không
        # phân biệt được hai nhánh tài khoản vì nó không phụ thuộc `hash_mk`.
        return False
    return bool(that) and co_hash


def phat_token(
    *,
    sub: str,
    role: str,
    space: str,
    demo: bool,
    admin: bool,
    khoa: str,
    phat_luc: datetime | None = None,
) -> str:
    """Token HS256 của một tài khoản, `exp` cách `iat` đúng `TTL_GIO` giờ.

    `iat` truyền vào được để test kiểm khoảng cách hai mốc mà không phải chờ.
    Thời gian là UTC (Consistency Conventions); `jwt` mã hóa chúng thành epoch
    giây, nên mốc phải bỏ phần lẻ trước khi ký - nếu không `exp - iat` đọc lại
    lệch tới một giây và một test đúng sẽ đỏ ngẫu nhiên.
    """
    luc = (phat_luc or datetime.now(timezone.utc)).replace(microsecond=0)
    return jwt.encode(
        {
            "sub": sub,
            "role": role,
            "space": space,
            "demo": bool(demo),
            "admin": bool(admin),
            "iat": luc,
            "exp": luc + timedelta(hours=TTL_GIO),
        },
        khoa,
        algorithm=THUAT_TOAN,
    )


def doc_token(token: str | None, khoa: str) -> ClaimNguoiHoi:
    """Giải mã và kiểm token; thiếu, hết hạn, sai chữ ký đều là một mã.

    `algorithms=[THUAT_TOAN]` là danh sách một phần tử có chủ đích: nhận cả
    `none` hay cả RS256 là nhận một token do người gửi tự chọn cách ký.
    """
    if not token:
        raise LoiXacThuc(401, MA_TOKEN_KHONG_HOP_LE, THONG_DIEP_TOKEN)
    try:
        claim = jwt.decode(
            token,
            khoa,
            algorithms=[THUAT_TOAN],
            options={"require": ["sub", "role", "space", "exp", "iat"]},
        )
    except jwt.PyJWTError:
        raise LoiXacThuc(401, MA_TOKEN_KHONG_HOP_LE, THONG_DIEP_TOKEN) from None
    return ClaimNguoiHoi(
        sub=claim["sub"],
        role=claim["role"],
        space=claim["space"],
        demo=bool(claim.get("demo")),
        admin=bool(claim.get("admin")),
    )


def token_tu_header(authorization: str | None) -> str | None:
    """Phần token của một header `Authorization: Bearer <token>`.

    Header vắng, sai lược đồ, hay không có phần token đều trả `None`, và nơi gọi
    biến `None` thành đúng `TOKEN_KHONG_HOP_LE` như mọi ca hỏng khác.
    """
    if not authorization:
        return None
    phan = authorization.split(None, 1)
    if len(phan) != 2 or phan[0].lower() != "bearer":
        return None
    return phan[1].strip() or None


def doi_demo_hoac_admin(claim: ClaimNguoiHoi) -> ClaimNguoiHoi:
    """Cửa quyền của endpoint đòi `demo` hoặc `admin` (spine `:105`, nền FR-18).

    Hai cờ, phép **hoặc**: API đổi vai, endpoint cache offline và toggle demo
    đòi một trong hai. API ghi đè policy chỉ nhận `admin` và sẽ có cửa riêng của
    nó - không nới cửa này để dùng chung, vì khi đó một tài khoản demo ghi đè
    được bảng chính sách.
    """
    if not (claim.demo or claim.admin):
        raise LoiXacThuc(403, MA_THIEU_QUYEN, THONG_DIEP_THIEU_QUYEN)
    return claim


def doi_admin(claim: ClaimNguoiHoi) -> ClaimNguoiHoi:
    """Cửa quyền của endpoint **chỉ** nhận `admin` (AD-10, FR-22 nền, story 3.2).

    Đây là chỗ hai cờ của AD-10 khác nhau thật: `doi_demo_hoac_admin` là cửa của
    API đổi vai và cache offline, còn đường hoán bảng chính sách đổi cái mà mọi
    vai thấy được nên nó không được mở cho một tài khoản demo. Nới cửa kia để
    dùng chung ở đây là cho một tài khoản demo ghi đè bảng chính sách.

    `demo` **không** ngụ ý `admin` và ngược lại: hai cờ riêng, không phải hai
    mức của một thang. `config/tai-khoan.yaml` giữ `demo01` (demo mà không
    admin) đúng để ca từ chối này chứng minh được qua HTTP.
    """
    if not claim.admin:
        raise LoiXacThuc(403, MA_THIEU_QUYEN_ADMIN, THONG_DIEP_THIEU_QUYEN_ADMIN)
    return claim


def loi_dang_nhap_sai() -> LoiXacThuc:
    """Lỗi duy nhất của mọi ca đăng nhập sai; một chỗ dựng, nên không lệch byte."""
    return LoiXacThuc(401, MA_DANG_NHAP_SAI, THONG_DIEP_DANG_NHAP_SAI)


# --- Sự kiện đăng nhập (story 3.6) ---------------------------------------------

# Khóa và hai giá trị của `chi_tiet.ket_qua`. Chỉ hai giá trị và **không** trường
# nào khác: hàng thất bại không ghi "vì sao sai" (tài khoản lạ hay mật khẩu sai),
# vì đó chính là thứ mà thân response cố ý không phân biệt.
CT_KET_QUA: str = "ket_qua"
KET_QUA_THANH_CONG: str = "thanh_cong"
KET_QUA_THAT_BAI: str = "that_bai"

# Trần độ dài của `act` trong hàng `auth_login`. Tên gõ vào là đầu vào tự do
# của người lạ: một chuỗi vài megabyte không đáng một hàng audit dài ngần ấy,
# và một mật khẩu gõ nhầm ô thì cắt ngắn không cứu được (ADR-017 nói thẳng rủi
# ro đó), nhưng ít nhất sổ không ôm cả thân request.
DAI_ACT_TOI_DA: int = 64


def su_kien_dang_nhap(ten: str | None, thanh_cong: bool, policy_version: str) -> SuKienAudit:
    """Hàng `auth_login` tầng observation; `act` là tên gõ vào (cắt về `DAI_ACT_TOI_DA`), `None` khi thân hỏng hay rỗng."""
    return SuKienAudit(
        tier=TIER_OBSERVATION,
        event=EVENT_AUTH_LOGIN,
        space=SPACE_TIEN_TRINH,
        policy_version=policy_version,
        thoi_diem=thoi_diem_utc(),
        act=(ten[:DAI_ACT_TOI_DA] if ten else None),
        chi_tiet={CT_KET_QUA: KET_QUA_THANH_CONG if thanh_cong else KET_QUA_THAT_BAI},
    )


async def ghi_dang_nhap(
    audit: AuditPort, *, ten: str | None, thanh_cong: bool, policy_version: str
) -> None:
    """Ghi một lần đăng nhập, cả hai chiều, best-effort.

    Observation vì audit chết không được làm đăng nhập chết theo, và vì thân
    response của mọi ca sai phải giữ byte-identical: một 500 ở đúng nhánh sai là
    một cách phân biệt "sai mật khẩu lúc Postgres khỏe" với "sai mật khẩu lúc
    Postgres chết". Chặn nhịp theo số lần là việc của 3-8, đứng trên chính hàng này.
    """
    await ghi_quan_sat(audit, su_kien_dang_nhap(ten, thanh_cong, policy_version))
