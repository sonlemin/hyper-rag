"""API xin break-glass: ba tuyến, một bảng Postgres, audit trong transaction (FR-20, story 5.1).

Tech Support thấy một dòng hạn chế L1 (`citations[].masked_slots` cộng
`owner_group` từ 3.4) và không có đường chính thức nào để xin đọc phần bị che;
đi hỏi chui là đúng thứ FR-20 sinh ra để thay. Module này là ruột của ba tuyến
(`api/main.py` chỉ nối tuyến): xin cho **một** hyperedge mà vai hiện tại thấy
ở mức L1, người xin hủy khi còn chờ, và liệt kê yêu cầu của chính mình. Duyệt,
từ chối, cấp grant là 5.2; `grant_ids` vào ngữ cảnh là 5.3.

Bốn luật, cả bốn là cơ chế.

**Mức tiết lộ hỏi qua đúng cửa quyền của citation.** "Vai này thấy hyperedge
này ở mức nào" là câu mà `Neo4jACLGraphStorage.trich_dan_cua` cộng
`adapters.trich_dan.dung_trich_dan` đã trả lời ở 3.4; `EngineACL.trich_dan_theo_id`
gọi đúng hai thứ ấy. Nhờ vậy hyperedge L0, id không tồn tại và id khác space
đều là **vắng mặt** ở cùng một phép kiểm, và endpoint trả **một** thân
byte-identical 404 `HYPEREDGE_KHONG_XIN_DUOC` cho cả ba - không có truy vấn thứ
hai nào để biết id có tồn tại không (AD-14). Vai đã thấy L2 là 400
`HYPEREDGE_DA_THAY_DU`: không rò gì, vai đang đọc được nó đầy đủ.

**Mọi trường quyền chép từ ngữ cảnh, không từ thân request.** `act`, `role`,
`space` của yêu cầu là `real_account`/`role`/`space` của `PermissionContext`
mà `api.hoi_dap.ngu_canh_cua_claim` dựng từ token; thân request chỉ có
`hyperedge_id` và `ly_do` (`extra="forbid"`).

**Chặn trùng ở hai tầng, hai cặp khớp khác nhau có chủ đích.** Yêu cầu chờ
khớp (`act`, `hyperedge_id`): một người một thẻ trên hàng chờ của owner, đổi
vai không mở được thẻ thứ hai - phép kiểm trước insert cộng index duy nhất một
phần của `api/sql/breakglass.sql` cho cùng mã 409 `YEU_CAU_DANG_CHO`. Grant
còn hạn khớp (`act`, `role`, `hyperedge_id`): grant bind cặp (5.2), ở vai khác
nó ngủ (5.3), nên một grant đang ngủ không phải lý do từ chối xin ở vai này.
Cả hai phép kiểm chạy **bên trong** transaction của câu INSERT, trên cùng một
kết nối.

**Audit bên trong transaction của bảng yêu cầu.** Postgres của bảng yêu cầu và
của `audit_log` là hai pool, không chung transaction; thứ tự INSERT -> audit ->
COMMIT cho bất biến "không hàng yêu cầu nào thiếu hàng audit". Audit hỏng là
rollback và 500 `AUDIT_GHI_HONG`, không hàng nào ở `breakglass_requests`.
Chiều ngược (audit đã ghi, COMMIT hỏng) để lại một hàng audit nói về một yêu
cầu không tồn tại - chấp nhận được, sổ ghi *ý định* và bảng ghi *trạng thái*.
`ly_do` không vào `audit_log`: sổ chỉ giữ dấu vết, nội dung tự do của người
dùng ở bảng.

**Duyệt, từ chối, cấp chủ động (story 5.2) - vùng cấp hai pha, owner từ bảng
`users`.** Owner là tài khoản có `group_name` bằng `nhom_duyet` của yêu cầu,
cùng space, và **không phải chính người xin** (bảng nhóm đặt `bao_cao_su_co`
dưới Tech Support trong khi `tech_support` chỉ thấy nó ở L1, nên không cấm thì
"owner duyệt" thành "tự cấp"). Vùng cấp tính dưới ngữ cảnh của **người xin**
dựng lại từ ảnh chụp `(act, role, space)` qua đúng `ngu_canh_cua_claim`:
`EngineACL.vung_lan_can(ids, k)` cho tập thô đã qua ba mệnh đề lọc quyền của
vai xin, `core.break_glass.loc_vung_cap` áp ba bộ lọc thuần. Vùng rỗng là
409 `VUNG_CAP_RONG`, không grant. Duyệt và cấp ghi grant **trong cùng
transaction** với `UPDATE ... WHERE trang_thai = 'cho_duyet'` và hàng audit;
`expires_at` do Postgres tính (`now() + make_interval`, ADR-019 mục 4).

Mã lỗi và luật viết ở `docs/adr/ADR-019-api-xin-break-glass.md` (xin) và
`docs/adr/ADR-020-vung-cap-hai-pha-va-duyet.md` (duyệt, từ chối, cấp).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Mapping

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from adapters.engine import EngineACL
from adapters.trich_dan import TrichDanNgoaiQuyen
from api.audit_postgres import cau_hinh_postgres_tu_moi_truong
from api.hoi_dap import (
    MA_AUDIT_GHI_HONG,
    MA_KHO_KHONG_SAN_SANG,
    MA_THAN_YEU_CAU_LA,
    MA_TRICH_DAN_NGOAI_QUYEN,
    THOI_HAN_BIEN_DOI,
    THONG_DIEP_AUDIT_HONG,
    THONG_DIEP_KHO,
    THONG_DIEP_TRICH_DAN,
    LoiHoiDap,
    loi_truy_hoi,
    ngu_canh_cua_claim,
)
from api.tai_khoan import KhoTaiKhoan
from api.xac_thuc import ClaimNguoiHoi
from core.audit import (
    EVENT_BREAKGLASS_APPROVE,
    EVENT_BREAKGLASS_CANCEL,
    EVENT_BREAKGLASS_GRANT,
    EVENT_BREAKGLASS_REJECT,
    EVENT_BREAKGLASS_REQUEST,
    TIER_MUTATION,
    AuditPort,
    SuKienAudit,
    ghi_bien_doi,
    kiem_thoi_diem,
    thoi_diem_utc,
)
from core.break_glass import (
    K_MAC_DINH,
    THOI_HAN_PHUT,
    TRANG_THAI,
    TRANG_THAI_CHO_DUYET,
    TRANG_THAI_DA_DUYET,
    TRANG_THAI_DA_HUY,
    TRANG_THAI_TU_CHOI,
    UngVienVung,
    huy_duoc,
    loc_vung_cap,
    xu_ly_duoc,
)
from core.identity import RoleUnknown
from core.ids import normalize_id
from core.permission import PermissionContextMissing, use_context
from core.policy import Policy

logger = logging.getLogger(__name__)

# --- Mã lỗi (AD-8, test assert trên `code`) ------------------------------------

# 404 cho **cả ba** ca vô hình: L0, id không tồn tại, id khác space. Một thân,
# một mã - phân biệt chúng là cách liệt kê hyperedge từ ngoài (AD-14).
MA_HYPEREDGE_KHONG_XIN_DUOC: str = "HYPEREDGE_KHONG_XIN_DUOC"
# 400: vai đang thấy hyperedge đầy đủ, không có gì để xin.
MA_HYPEREDGE_DA_THAY_DU: str = "HYPEREDGE_DA_THAY_DU"
# 409: cùng tài khoản đã có yêu cầu đang chờ cho hyperedge này (bất kể vai).
MA_YEU_CAU_DANG_CHO: str = "YEU_CAU_DANG_CHO"
# 409: cặp (tài khoản, vai) đang có grant còn hạn chứa hyperedge này.
MA_GRANT_CON_HAN: str = "GRANT_CON_HAN"
# 404 cho yêu cầu không có **và** yêu cầu của người khác: một thân.
MA_YEU_CAU_KHONG_CO: str = "YEU_CAU_KHONG_CO"
# 409: yêu cầu không còn ở trạng thái chờ duyệt.
MA_YEU_CAU_KHONG_CON_CHO: str = "YEU_CAU_KHONG_CON_CHO"
MA_LY_DO_RONG: str = "LY_DO_RONG"
MA_LY_DO_QUA_DAI: str = "LY_DO_QUA_DAI"
# 500: bảng nhóm phụ trách không khai loại nội dung này - cấu hình hỏng, không
# phải lỗi của người gọi, và không có nhóm thì không có ai để duyệt.
MA_NHOM_DUYET_KHONG_CO: str = "NHOM_DUYET_KHONG_CO"

# 403 (story 5.2) cho **cả ba** ca không được xử lý yêu cầu: khác nhóm duyệt,
# chính người xin, tài khoản không còn trong bảng `users`. Một thân, một mã.
MA_KHONG_PHAI_OWNER: str = "KHONG_PHAI_OWNER"
# 409: sau ba bộ lọc, vùng cấp không còn hyperedge nào (kể cả gốc, khi bảng
# chính sách đã hoán và gốc không còn L1 với vai xin); không grant.
MA_VUNG_CAP_RONG: str = "VUNG_CAP_RONG"
# 400 (cấp chủ động) cho **cả ba** ca người nhận không hợp lệ: tài khoản lạ,
# khác space, vai không có trong bảng chính sách. Một thân, một mã.
MA_NGUOI_NHAN_KHONG_HOP_LE: str = "NGUOI_NHAN_KHONG_HOP_LE"

DAI_LY_DO_TOI_DA: int = 1000
# Trần độ dài của `hyperedge_id` trên đường mạng: id thật là `he-` + 24 hex,
# tên fixture dài vài chục ký tự; 200 chặn ca dán một đoạn văn vào ô id.
DAI_ID_TOI_DA: int = 200
# Ký tự NUL không vào Postgres `text` và không có trong một id hay một lý do
# thật; gặp nó là thân sai, không phải một chuỗi cần cắt.
KY_TU_CAM: str = "\x00"
# Trần của `GET /break-glass/yeu-cau`: danh sách của một người, mới nhất trước.
SO_YEU_CAU_TOI_DA: int = 100

# Thông điệp cố định, không ghép id hay tên nào vào (cùng luật với `api/hoi_dap.py`).
THONG_DIEP_KHONG_XIN_DUOC: str = "không xin được hyperedge này"
THONG_DIEP_DA_THAY_DU: str = "vai hiện tại đã thấy hyperedge này đầy đủ"
THONG_DIEP_DANG_CHO: str = "đã có một yêu cầu đang chờ duyệt cho hyperedge này"
THONG_DIEP_GRANT_CON_HAN: str = "đang có một grant còn hạn cho hyperedge này"
THONG_DIEP_YEU_CAU_KHONG_CO: str = "không có yêu cầu này"
THONG_DIEP_KHONG_CON_CHO: str = "yêu cầu không còn ở trạng thái chờ duyệt"
THONG_DIEP_LY_DO_RONG: str = "lý do rỗng"
THONG_DIEP_LY_DO_QUA_DAI: str = f"lý do quá dài, tối đa {DAI_LY_DO_TOI_DA} ký tự"
THONG_DIEP_THAN_LA: str = (
    "thân yêu cầu chỉ nhận `hyperedge_id` (chuỗi không rỗng) và `ly_do`;"
    " tài khoản, vai và không gian lấy từ token"
)
THONG_DIEP_NHOM_DUYET: str = "không tra được nhóm duyệt cho loại nội dung này"
THONG_DIEP_KHONG_PHAI_OWNER: str = "tài khoản hiện tại không xử lý được yêu cầu này"
THONG_DIEP_VUNG_CAP_RONG: str = "vùng cấp rỗng, không có hyperedge nào để cấp"
THONG_DIEP_NGUOI_NHAN: str = "người nhận không hợp lệ"
THONG_DIEP_THAN_TU_CHOI: str = "thân yêu cầu chỉ nhận `ly_do`"
THONG_DIEP_THAN_CAP: str = (
    "thân yêu cầu chỉ nhận `act`, `role` và `hyperedge_id` (chuỗi không rỗng);"
    " owner lấy từ token"
)

# Khóa `chi_tiet` của hai hàng audit. `request_id` ở đây là **id của yêu cầu
# break-glass** (`bg-…`), không phải id của một lượt hỏi: đường này không có
# lượt, và 5.2 nối hàng duyệt với hàng xin bằng đúng khóa này.
CT_REQUEST_ID: str = "request_id"
CT_TRANG_THAI: str = "trang_thai"
CT_K: str = "k"
CT_THOI_HAN_PHUT: str = "thoi_han_phut"
CT_NHOM_DUYET: str = "nhom_duyet"
# Ba khóa thêm của hàng duyệt/từ chối/cấp (5.2): id grant (`None` khi không
# có), người nhận và vai nhận - cặp mà grant bind.
CT_GRANT_ID: str = "grant_id"
CT_NGUOI_NHAN: str = "nguoi_nhan"
CT_VAI_NHAN: str = "vai_nhan"

TIEN_TO_ID: str = "bg-"
TIEN_TO_GRANT: str = "gr-"
# Tên index duy nhất một phần ở `api/sql/breakglass.sql`; `tao` chỉ đổi
# `UniqueViolationError` mang đúng tên này thành 409 - một va chạm khóa chính
# không được đọc thành "đang chờ".
INDEX_CHO_DUYET: str = "breakglass_requests_cho_duyet_idx"
MUC_XIN_DUOC: str = "L1"
MUC_DA_THAY_DU: str = "L2"
# Trần độ dài của `act`/`role` trong thân cấp chủ động: `users.account` và tên
# vai thật đều vài chục ký tự; 200 chặn ca dán một đoạn văn vào ô.
DAI_TEN_TOI_DA: int = 200


class ThanXinBreakGlass(BaseModel):
    """Thân của `POST /break-glass/yeu-cau`: **đúng hai** trường.

    `extra="forbid"` là nội dung: `k`, `thoi_han_phut`, `role`, `space`, hay một
    danh sách id đều là thứ quyết định phạm vi của yêu cầu, và mọi thứ trong số
    đó phải đến từ hằng của server hoặc từ token. Chuỗi rỗng và độ dài kiểm ở
    `xin` để có mã riêng; `max_length` của `ly_do` chỉ là trần rẻ trên đường
    mạng (gấp bốn trần thật), ca vượt trần thật vẫn ra `LY_DO_QUA_DAI`.
    """

    model_config = ConfigDict(extra="forbid")

    hyperedge_id: str = Field(max_length=DAI_ID_TOI_DA)
    ly_do: str = Field(max_length=DAI_LY_DO_TOI_DA * 4)


class ThanTuChoi(BaseModel):
    """Thân của `POST /break-glass/yeu-cau/{id}/tu-choi`: **đúng một** trường (story 5.2)."""

    model_config = ConfigDict(extra="forbid")

    ly_do: str = Field(max_length=DAI_LY_DO_TOI_DA * 4)


class ThanCapChuDong(BaseModel):
    """Thân của `POST /break-glass/grant`: người nhận `(act, role)` và gốc, không hơn (story 5.2).

    Owner, space, k và thời hạn đều **không** ở đây: owner từ token, space từ
    token (người nhận phải cùng space), k và thời hạn là hai hằng của
    `core/break_glass.py`. Người nhận khai tường minh vì cấp chủ động không có
    yêu cầu nào để chép cặp từ đó.
    """

    model_config = ConfigDict(extra="forbid")

    act: str = Field(max_length=DAI_TEN_TOI_DA)
    role: str = Field(max_length=DAI_TEN_TOI_DA)
    hyperedge_id: str = Field(max_length=DAI_ID_TOI_DA)


@dataclass(frozen=True)
class YeuCauBreakGlass:
    """Một hàng `breakglass_requests`, đã kiểm, bất biến; hình dạng mà thân 201 trả."""

    id: str
    act: str
    role: str
    space: str
    hyperedge_id: str
    scope: str
    content_type: str
    nhom_duyet: str
    ly_do: str
    k: int
    thoi_han_phut: int
    trang_thai: str
    tao_luc: str
    cap_nhat: str
    # Hai trường 5.2 điền khi owner xử lý; `None` cho tới lúc đó.
    ly_do_tu_choi: str | None = None
    xu_ly_boi: str | None = None

    def __post_init__(self):
        for ten in ("id", "act", "role", "space", "hyperedge_id", "scope", "content_type", "nhom_duyet"):
            gia_tri = getattr(self, ten)
            if not isinstance(gia_tri, str) or not gia_tri.strip():
                raise ValueError(f"{ten} phải là chuỗi không rỗng")
        if not isinstance(self.ly_do, str) or not self.ly_do.strip() or len(self.ly_do) > DAI_LY_DO_TOI_DA:
            raise ValueError(f"ly_do phải là chuỗi 1..{DAI_LY_DO_TOI_DA} ký tự")
        if not isinstance(self.k, int) or isinstance(self.k, bool) or self.k < 0:
            raise ValueError("k phải là số nguyên không âm")
        if not isinstance(self.thoi_han_phut, int) or isinstance(self.thoi_han_phut, bool) or self.thoi_han_phut <= 0:
            raise ValueError("thoi_han_phut phải là số nguyên dương")
        if self.trang_thai not in TRANG_THAI:
            raise ValueError(f"trang_thai {self.trang_thai!r} ngoài danh mục {sorted(TRANG_THAI)}")
        kiem_thoi_diem(self.tao_luc)
        kiem_thoi_diem(self.cap_nhat)
        for ten in ("ly_do_tu_choi", "xu_ly_boi"):
            gia_tri = getattr(self, ten)
            if gia_tri is not None and (not isinstance(gia_tri, str) or not gia_tri.strip()):
                raise ValueError(f"{ten} phải là chuỗi không rỗng hoặc None")
        # Trạng thái và hai trường xử lý phải kể cùng một chuyện: từ chối mà
        # không có lý do, hay đã xử lý mà không có ai xử lý, là một hàng nói dối.
        if (self.trang_thai == TRANG_THAI_TU_CHOI) != (self.ly_do_tu_choi is not None):
            raise ValueError("ly_do_tu_choi có khi và chỉ khi trang_thai là tu_choi")
        if (self.trang_thai in (TRANG_THAI_DA_DUYET, TRANG_THAI_TU_CHOI)) != (self.xu_ly_boi is not None):
            raise ValueError("xu_ly_boi có khi và chỉ khi yêu cầu đã được duyệt hay từ chối")


# Thứ tự khóa của thân yêu cầu, đóng; `dict_yeu_cau` là chỗ duy nhất dựng nó.
# 14 khóa từ 5.1, hai khóa cuối `ly_do_tu_choi` · `xu_ly_boi` từ 5.2 (`None`
# khi chưa có).
KHOA_YEU_CAU: tuple[str, ...] = (
    "id", "act", "role", "space", "hyperedge_id", "scope", "content_type",
    "nhom_duyet", "trang_thai", "k", "thoi_han_phut", "ly_do", "tao_luc", "cap_nhat",
    "ly_do_tu_choi", "xu_ly_boi",
)


def dict_yeu_cau(yc: YeuCauBreakGlass) -> dict:
    """Thân JSON của một yêu cầu, 16 khóa đóng theo `KHOA_YEU_CAU`."""
    return {k: getattr(yc, k) for k in KHOA_YEU_CAU}


def ma_yeu_cau() -> str:
    """Id yêu cầu: `bg-` + 12 hex của `uuid4`."""
    return TIEN_TO_ID + uuid.uuid4().hex[:12]


def ma_grant() -> str:
    """Id grant: `gr-` + 12 hex của `uuid4`."""
    return TIEN_TO_GRANT + uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class Grant:
    """Một hàng `breakglass_grants`, đã kiểm, bất biến; hình dạng mà thân duyệt/cấp trả (story 5.2).

    `request_id` là `None` cho grant cấp chủ động. `hyperedge_ids` là vùng cấp
    đã lọc, gốc đứng đầu, không rỗng. Hai mốc thời gian đến từ Postgres
    (`RETURNING expires_at, tao_luc`), không từ tiến trình `api`.
    """

    id: str
    request_id: str | None
    act: str
    role: str
    space: str
    hyperedge_ids: tuple[str, ...]
    expires_at: str
    cap_boi: str
    tao_luc: str

    def __post_init__(self):
        for ten in ("id", "act", "role", "space", "cap_boi"):
            gia_tri = getattr(self, ten)
            if not isinstance(gia_tri, str) or not gia_tri.strip():
                raise ValueError(f"{ten} phải là chuỗi không rỗng")
        if not self.id.startswith(TIEN_TO_GRANT):
            raise ValueError(f"id grant phải mang tiền tố {TIEN_TO_GRANT!r}")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not self.request_id.startswith(TIEN_TO_ID)
        ):
            raise ValueError(f"request_id phải là None hoặc id yêu cầu mang tiền tố {TIEN_TO_ID!r}")
        if (
            not isinstance(self.hyperedge_ids, tuple)
            or not self.hyperedge_ids
            or not all(isinstance(h, str) and h.strip() for h in self.hyperedge_ids)
            or len(set(self.hyperedge_ids)) != len(self.hyperedge_ids)
        ):
            raise ValueError("hyperedge_ids phải là tuple id không rỗng, không lặp")
        het = kiem_thoi_diem(self.expires_at)
        tao = kiem_thoi_diem(self.tao_luc)
        if het <= tao:
            raise ValueError("expires_at phải sau tao_luc")


# Thứ tự khóa của thân grant, đóng; `dict_grant` là chỗ duy nhất dựng nó.
KHOA_GRANT: tuple[str, ...] = (
    "id", "request_id", "act", "role", "space", "hyperedge_ids", "expires_at", "cap_boi", "tao_luc",
)


def dict_grant(g: Grant) -> dict:
    """Thân JSON của một grant, 9 khóa đóng; `hyperedge_ids` là list."""
    than = {k: getattr(g, k) for k in KHOA_GRANT}
    than["hyperedge_ids"] = list(g.hyperedge_ids)
    return than


def kiem_ly_do(ly_do) -> str:
    """Lý do đã strip, 1..`DAI_LY_DO_TOI_DA` ký tự; không phải chuỗi là thân sai."""
    if not isinstance(ly_do, str) or KY_TU_CAM in ly_do:
        raise LoiHoiDap(400, MA_THAN_YEU_CAU_LA, THONG_DIEP_THAN_LA)
    sach = ly_do.strip()
    if not sach:
        raise LoiHoiDap(400, MA_LY_DO_RONG, THONG_DIEP_LY_DO_RONG)
    if len(sach) > DAI_LY_DO_TOI_DA:
        raise LoiHoiDap(400, MA_LY_DO_QUA_DAI, THONG_DIEP_LY_DO_QUA_DAI)
    return sach


def kiem_hyperedge_id(hyperedge_id) -> str:
    """Id hyperedge đã `normalize_id`; rỗng hay không phải chuỗi là thân sai (400)."""
    if (
        not isinstance(hyperedge_id, str)
        or not hyperedge_id.strip()
        or len(hyperedge_id) > DAI_ID_TOI_DA
        or KY_TU_CAM in hyperedge_id
    ):
        raise LoiHoiDap(400, MA_THAN_YEU_CAU_LA, THONG_DIEP_THAN_LA)
    return normalize_id(hyperedge_id)


def loi_khong_xin_duoc() -> LoiHoiDap:
    """Một lỗi cho cả ba ca vô hình; hàm để hai chỗ dội không lệch nhau một byte."""
    return LoiHoiDap(404, MA_HYPEREDGE_KHONG_XIN_DUOC, THONG_DIEP_KHONG_XIN_DUOC)


def loi_dang_cho() -> LoiHoiDap:
    return LoiHoiDap(409, MA_YEU_CAU_DANG_CHO, THONG_DIEP_DANG_CHO)


def loi_grant_con_han() -> LoiHoiDap:
    return LoiHoiDap(409, MA_GRANT_CON_HAN, THONG_DIEP_GRANT_CON_HAN)


def loi_yeu_cau_khong_co() -> LoiHoiDap:
    return LoiHoiDap(404, MA_YEU_CAU_KHONG_CO, THONG_DIEP_YEU_CAU_KHONG_CO)


def loi_khong_con_cho() -> LoiHoiDap:
    return LoiHoiDap(409, MA_YEU_CAU_KHONG_CON_CHO, THONG_DIEP_KHONG_CON_CHO)


def loi_khong_phai_owner() -> LoiHoiDap:
    """Một lỗi cho cả ba ca không phải owner; hàm để mọi chỗ dội không lệch nhau một byte."""
    return LoiHoiDap(403, MA_KHONG_PHAI_OWNER, THONG_DIEP_KHONG_PHAI_OWNER)


def loi_vung_cap_rong() -> LoiHoiDap:
    return LoiHoiDap(409, MA_VUNG_CAP_RONG, THONG_DIEP_VUNG_CAP_RONG)


def loi_nguoi_nhan() -> LoiHoiDap:
    """Một lỗi cho cả ba ca người nhận không hợp lệ (lạ, khác space, vai lạ)."""
    return LoiHoiDap(400, MA_NGUOI_NHAN_KHONG_HOP_LE, THONG_DIEP_NGUOI_NHAN)


def su_kien_break_glass(event: str, ngu_canh, yc: YeuCauBreakGlass) -> SuKienAudit:
    """Hàng audit tầng mutation của một lần tạo/hủy: dấu vết, không `ly_do`."""
    return SuKienAudit(
        tier=TIER_MUTATION,
        event=event,
        space=ngu_canh.space,
        policy_version=ngu_canh.policy_version,
        thoi_diem=thoi_diem_utc(),
        act=ngu_canh.real_account,
        role=ngu_canh.role,
        hyperedge_ids=(yc.hyperedge_id,),
        chi_tiet={
            CT_REQUEST_ID: yc.id,
            CT_TRANG_THAI: yc.trang_thai,
            CT_K: yc.k,
            CT_THOI_HAN_PHUT: yc.thoi_han_phut,
            CT_NHOM_DUYET: yc.nhom_duyet,
        },
    )


def su_kien_duyet(
    event: str,
    ngu_canh,
    *,
    hyperedge_ids: tuple[str, ...],
    nguoi_nhan: str,
    vai_nhan: str,
    nhom_duyet: str,
    k: int,
    thoi_han_phut: int,
    yc: "YeuCauBreakGlass | None" = None,
    grant: "Grant | None" = None,
) -> SuKienAudit:
    """Hàng audit tầng mutation của một lần duyệt/từ chối/cấp (story 5.2).

    `act`/`role`/`space` là của **owner** (ngữ cảnh đang gọi); người nhận và vai
    nhận đi vào `chi_tiet`. `hyperedge_ids` là vùng cấp (từ chối: chỉ gốc).
    Tám khóa đóng, `request_id`/`grant_id` là `None` khi không có; **không**
    `ly_do`/`ly_do_tu_choi`.
    """
    return SuKienAudit(
        tier=TIER_MUTATION,
        event=event,
        space=ngu_canh.space,
        policy_version=ngu_canh.policy_version,
        thoi_diem=thoi_diem_utc(),
        act=ngu_canh.real_account,
        role=ngu_canh.role,
        hyperedge_ids=tuple(hyperedge_ids),
        chi_tiet={
            CT_REQUEST_ID: yc.id if yc is not None else None,
            CT_TRANG_THAI: yc.trang_thai if yc is not None else None,
            CT_GRANT_ID: grant.id if grant is not None else None,
            CT_NGUOI_NHAN: nguoi_nhan,
            CT_VAI_NHAN: vai_nhan,
            CT_K: k,
            CT_THOI_HAN_PHUT: thoi_han_phut,
            CT_NHOM_DUYET: nhom_duyet,
        },
    )


GhiAudit = Callable[[YeuCauBreakGlass], Awaitable[None]]
# Callable của ba đường 5.2: kho gọi với hàng yêu cầu **sau** UPDATE (hay
# `None` ở cấp chủ động) và grant vừa ghi (hay `None` ở từ chối).
GhiAuditDuyet = Callable[["YeuCauBreakGlass | None", "Grant | None"], Awaitable[None]]


async def _ghi_co_han(audit: AuditPort, event: str, su_kien: SuKienAudit) -> None:
    try:
        await asyncio.wait_for(ghi_bien_doi(audit, su_kien), timeout=THOI_HAN_BIEN_DOI)
    except Exception as loi:
        logger.error("audit mutation %s không ghi được (%s: %s)", event, type(loi).__name__, loi)
        raise LoiHoiDap(500, MA_AUDIT_GHI_HONG, THONG_DIEP_AUDIT_HONG) from None


def _ghi_audit_duyet(
    audit: AuditPort, ngu_canh, event: str, *, nhom_duyet: str, nguoi_nhan: str, vai_nhan: str
) -> GhiAuditDuyet:
    """Callable của ba đường 5.2, gọi **bên trong** transaction; hỏng là `AUDIT_GHI_HONG` và rollback.

    `nhom_duyet`/`nguoi_nhan`/`vai_nhan` truyền từ ngoài vì ở cấp chủ động
    không có hàng yêu cầu nào để đọc chúng; ở duyệt/từ chối chúng đúng bằng
    ba trường của hàng.
    """

    async def ghi(yc: YeuCauBreakGlass | None, grant: Grant | None) -> None:
        if grant is not None:
            ids = grant.hyperedge_ids
        else:
            ids = (yc.hyperedge_id,) if yc is not None else ()
        await _ghi_co_han(
            audit,
            event,
            su_kien_duyet(
                event,
                ngu_canh,
                hyperedge_ids=ids,
                nguoi_nhan=nguoi_nhan,
                vai_nhan=vai_nhan,
                nhom_duyet=nhom_duyet,
                k=yc.k if yc is not None else K_MAC_DINH,
                thoi_han_phut=yc.thoi_han_phut if yc is not None else THOI_HAN_PHUT,
                yc=yc,
                grant=grant,
            ),
        )

    return ghi


def _ghi_audit(audit: AuditPort, ngu_canh, event: str) -> GhiAudit:
    """Callable mà kho gọi **bên trong** transaction; hỏng là `AUDIT_GHI_HONG` và rollback."""

    async def ghi(yc: YeuCauBreakGlass) -> None:
        await _ghi_co_han(audit, event, su_kien_break_glass(event, ngu_canh, yc))

    return ghi


# --- Kho Postgres --------------------------------------------------------------

DUONG_DAN_DDL: Path = Path(__file__).resolve().parent / "sql" / "breakglass.sql"

# Cột ghi lúc xin (14); cột đọc thêm hai cột 5.2 điền (`ly_do_tu_choi`, `xu_ly_boi`).
_COT_TAO = (
    "id, act, role, space, hyperedge_id, scope, content_type, nhom_duyet, ly_do,"
    " k, thoi_han_phut, trang_thai, tao_luc, cap_nhat"
)
_COT = _COT_TAO + ", ly_do_tu_choi, xu_ly_boi"
_SQL_DANG_CHO = f"""
    SELECT 1 FROM breakglass_requests
    WHERE act = $1 AND hyperedge_id = $2 AND trang_thai = '{TRANG_THAI_CHO_DUYET}'
    LIMIT 1
"""
_SQL_TAO = f"""
    INSERT INTO breakglass_requests ({_COT_TAO})
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
"""
_SQL_MOT_CUA_ACT = f"SELECT {_COT} FROM breakglass_requests WHERE id = $1 AND act = $2 AND space = $3"
_SQL_HUY = f"""
    UPDATE breakglass_requests
    SET trang_thai = '{TRANG_THAI_DA_HUY}', cap_nhat = $2
    WHERE id = $1 AND trang_thai = '{TRANG_THAI_CHO_DUYET}'
    RETURNING {_COT}
"""
_SQL_CUA_TOI = f"""
    SELECT {_COT} FROM breakglass_requests
    WHERE act = $1
    ORDER BY tao_luc DESC, id DESC
    LIMIT $2
"""
# Grant khớp cặp `(act, role)` **trong một space**: bảng có cột `space` và một
# grant của space khác không nói gì về space này (review 5.2).
_SQL_GRANT_CON_HAN = """
    SELECT 1 FROM breakglass_grants
    WHERE act = $1 AND role = $2 AND $3 = ANY(hyperedge_ids) AND space = $4 AND expires_at > now()
    LIMIT 1
"""
# 1. Tuần tự hóa mọi đường ghi grant của một cặp trong một space (review 5.2):
# `duyet` và `cap` đều là kiểm-rồi-ghi, hai transaction chen nhau trên cùng
# cặp không thấy nhau trước COMMIT, nên hai owner cấp cùng lúc là hai grant.
# Khóa tư vấn theo transaction giữ tới COMMIT/ROLLBACK, không cần mở.
_SQL_KHOA_CAP = "SELECT pg_advisory_xact_lock(hashtext($1))"


def _khoa_cap(space: str, act: str, role: str) -> str:
    return f"{space}|{act}|{role}"
_SQL_MOT = f"SELECT {_COT} FROM breakglass_requests WHERE id = $1"
# Hàng chờ của owner: cùng nhóm duyệt, cùng space, còn chờ, **cũ nhất trước**
# (index `breakglass_requests_nhom_duyet_cho_idx`).
_SQL_HANG_CHO = f"""
    SELECT {_COT} FROM breakglass_requests
    WHERE nhom_duyet = $1 AND space = $2 AND trang_thai = '{TRANG_THAI_CHO_DUYET}'
    ORDER BY tao_luc ASC, id ASC
    LIMIT $3
"""
_SQL_DUYET = f"""
    UPDATE breakglass_requests
    SET trang_thai = '{TRANG_THAI_DA_DUYET}', xu_ly_boi = $2, cap_nhat = $3
    WHERE id = $1 AND trang_thai = '{TRANG_THAI_CHO_DUYET}'
    RETURNING {_COT}
"""
_SQL_TU_CHOI = f"""
    UPDATE breakglass_requests
    SET trang_thai = '{TRANG_THAI_TU_CHOI}', ly_do_tu_choi = $2, xu_ly_boi = $3, cap_nhat = $4
    WHERE id = $1 AND trang_thai = '{TRANG_THAI_CHO_DUYET}'
    RETURNING {_COT}
"""
# **Một nguồn giờ**: `expires_at` và `tao_luc` đều là `now()` của Postgres,
# cùng đồng hồ với `_SQL_GRANT_CON_HAN` (ADR-019 mục 4). Không tham số datetime
# nào đi từ tiến trình `api` vào câu này; `$7` là số phút.
_SQL_GHI_GRANT = """
    INSERT INTO breakglass_grants
        (id, request_id, act, role, space, hyperedge_ids, expires_at, cap_boi)
    VALUES ($1, $2, $3, $4, $5, $6, now() + make_interval(mins => $7::int), $8)
    RETURNING expires_at, tao_luc
"""


def _tu_dong(dong: Mapping) -> YeuCauBreakGlass:
    return YeuCauBreakGlass(
        id=dong["id"],
        act=dong["act"],
        role=dong["role"],
        space=dong["space"],
        hyperedge_id=dong["hyperedge_id"],
        scope=dong["scope"],
        content_type=dong["content_type"],
        nhom_duyet=dong["nhom_duyet"],
        ly_do=dong["ly_do"],
        k=int(dong["k"]),
        thoi_han_phut=int(dong["thoi_han_phut"]),
        trang_thai=dong["trang_thai"],
        tao_luc=_iso(dong["tao_luc"]),
        cap_nhat=_iso(dong["cap_nhat"]),
        ly_do_tu_choi=dong["ly_do_tu_choi"],
        xu_ly_boi=dong["xu_ly_boi"],
    )


def _iso(gia_tri: datetime) -> str:
    """timestamptz của asyncpg (tz-aware) về chuỗi ISO-8601 UTC như `thoi_diem_utc`."""
    return kiem_thoi_diem(gia_tri.isoformat()).isoformat()


class KhoBreakGlass:
    """Hai bảng break-glass trên một pool asyncpg; cùng khuôn `KhoTaiKhoan`.

    Kho **không biết mã HTTP của kho**: nó dội `LoiHoiDap` cho ba ca nghiệp vụ
    (đang chờ, không có, không còn chờ) để bản giả trong `tests/` dội đúng
    cùng thứ, còn lỗi kết nối để nguyên cho `loi_kho` ở tầng trên ánh xạ.
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def mo(cls, cau_hinh: Mapping | None = None) -> "KhoBreakGlass":
        cau_hinh = cau_hinh_postgres_tu_moi_truong() if cau_hinh is None else dict(cau_hinh)
        pool = await asyncpg.create_pool(min_size=1, max_size=4, **cau_hinh)
        return cls(pool)

    async def khoi_tao(self) -> None:
        """DDL idempotent; đòi bảng `users` đã có (khóa ngoại `act`)."""
        ddl = DUONG_DAN_DDL.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            await conn.execute(ddl)

    async def tao(self, yc: YeuCauBreakGlass, ghi_audit: GhiAudit) -> YeuCauBreakGlass:
        """Grant -> đang chờ -> INSERT -> audit -> COMMIT, một transaction; hai ca trùng là 409.

        Cả hai phép kiểm trùng chạy **trên cùng kết nối** của transaction, nên
        chúng đọc cùng một ảnh của bảng với câu INSERT. Phép kiểm đang chờ cho
        mã 409 ở ca thường; index duy nhất một phần bắt ca hai request chen
        nhau và ra **cùng** mã - nhưng chỉ khi `UniqueViolationError` mang đúng
        tên index ấy, một va chạm khóa chính dội nguyên. `ghi_audit` hỏng thì
        transaction rollback: không hàng yêu cầu nào thiếu hàng audit.

        `acquire` có hạn bằng `THOI_HAN_BIEN_DOI`: một request giữ một kết nối
        suốt lúc chờ audit, pool tối đa 4, nên pool cạn phải là một lỗi kho
        (503 ở tầng trên) chứ không phải một request treo.
        """
        async with self._pool.acquire(timeout=THOI_HAN_BIEN_DOI) as conn:
            async with conn.transaction():
                if await conn.fetchval(_SQL_GRANT_CON_HAN, yc.act, yc.role, yc.hyperedge_id, yc.space):
                    raise loi_grant_con_han()
                if await conn.fetchval(_SQL_DANG_CHO, yc.act, yc.hyperedge_id):
                    raise loi_dang_cho()
                try:
                    await conn.execute(
                        _SQL_TAO,
                        yc.id, yc.act, yc.role, yc.space, yc.hyperedge_id, yc.scope,
                        yc.content_type, yc.nhom_duyet, yc.ly_do, yc.k, yc.thoi_han_phut,
                        yc.trang_thai, kiem_thoi_diem(yc.tao_luc), kiem_thoi_diem(yc.cap_nhat),
                    )
                except asyncpg.exceptions.UniqueViolationError as loi:
                    if loi.constraint_name != INDEX_CHO_DUYET:
                        raise
                    raise loi_dang_cho() from None
                await ghi_audit(yc)
        return yc

    async def huy(self, id_yeu_cau: str, act: str, space: str, ghi_audit: GhiAudit) -> YeuCauBreakGlass:
        """Hủy có điều kiện: `UPDATE ... WHERE trang_thai = 'cho_duyet'`, 0 hàng là thất bại.

        Phép đọc đầu chỉ để **phân loại lỗi** (không có / của người khác / khác
        space -> 404, không còn chờ -> 409 qua `huy_duoc`); phép chuyển trạng
        thái là chính câu UPDATE có điều kiện, nên hai lần hủy chen nhau không
        cùng thắng. `space` so cùng `act`: một tài khoản đổi space giữa hai lần
        đăng nhập không hủy được yêu cầu của space cũ.
        """
        async with self._pool.acquire(timeout=THOI_HAN_BIEN_DOI) as conn:
            async with conn.transaction():
                dong = await conn.fetchrow(_SQL_MOT_CUA_ACT, id_yeu_cau, act, space)
                if dong is None:
                    raise loi_yeu_cau_khong_co()
                if not huy_duoc(dong["trang_thai"]):
                    raise loi_khong_con_cho()
                moi = await conn.fetchrow(_SQL_HUY, id_yeu_cau, kiem_thoi_diem(thoi_diem_utc()))
                if moi is None:
                    raise loi_khong_con_cho()
                yc = _tu_dong(moi)
                await ghi_audit(yc)
        return yc

    async def cua_toi(self, act: str, gioi_han: int = SO_YEU_CAU_TOI_DA) -> tuple[YeuCauBreakGlass, ...]:
        async with self._pool.acquire() as conn:
            dong = await conn.fetch(_SQL_CUA_TOI, act, gioi_han)
        return tuple(_tu_dong(d) for d in dong)

    async def tra_mot(self, id_yeu_cau: str) -> YeuCauBreakGlass | None:
        """Một hàng theo id, bất kể `act`; `None` khi không có. Cửa phân loại của owner (5.2)."""
        async with self._pool.acquire() as conn:
            dong = await conn.fetchrow(_SQL_MOT, id_yeu_cau)
        return None if dong is None else _tu_dong(dong)

    async def hang_cho(self, nhom_duyet: str, space: str, gioi_han: int = SO_YEU_CAU_TOI_DA) -> tuple[YeuCauBreakGlass, ...]:
        """Yêu cầu còn chờ của một nhóm duyệt trong một space, cũ nhất trước (5.2)."""
        async with self._pool.acquire() as conn:
            dong = await conn.fetch(_SQL_HANG_CHO, nhom_duyet, space, gioi_han)
        return tuple(_tu_dong(d) for d in dong)

    @staticmethod
    async def _khoa_va_kiem_grant(conn, *, act: str, role: str, space: str, hyperedge_ids: tuple[str, ...]) -> None:
        """Khóa tư vấn theo cặp trong space rồi kiểm grant còn hạn cho **mọi** id của vùng (review 5.2).

        Khóa trước, kiểm sau: hai đường ghi grant của cùng cặp xếp hàng, và đường
        sau thấy grant mà đường trước vừa COMMIT. Kiểm mọi id chứ không chỉ gốc:
        với `k > 0` một grant mới phủ lại id lân cận đang nằm trong grant còn hạn
        của cùng cặp là hai grant cho một hyperedge; bất kỳ id nào bị phủ là 409.
        """
        await conn.execute(_SQL_KHOA_CAP, _khoa_cap(space, act, role))
        for id_he in hyperedge_ids:
            if await conn.fetchval(_SQL_GRANT_CON_HAN, act, role, id_he, space):
                raise loi_grant_con_han()

    async def _sau_update_rong(self, conn, id_yeu_cau: str) -> LoiHoiDap:
        """UPDATE có điều kiện 0 hàng: đọc lại để phân loại 404 (không có) / 409 (không còn chờ)."""
        dong = await conn.fetchrow(_SQL_MOT, id_yeu_cau)
        if dong is None:
            return loi_yeu_cau_khong_co()
        return loi_khong_con_cho()

    @staticmethod
    async def _ghi_grant(
        conn, *, request_id: str | None, act: str, role: str, space: str,
        hyperedge_ids: tuple[str, ...], thoi_han_phut: int, cap_boi: str,
    ) -> Grant:
        """INSERT một grant, giờ hết hạn do Postgres tính; đọc lại hai mốc từ `RETURNING`."""
        ma = ma_grant()
        dong = await conn.fetchrow(
            _SQL_GHI_GRANT, ma, request_id, act, role, space, list(hyperedge_ids),
            int(thoi_han_phut), cap_boi,
        )
        return Grant(
            id=ma,
            request_id=request_id,
            act=act,
            role=role,
            space=space,
            hyperedge_ids=tuple(hyperedge_ids),
            expires_at=_iso(dong["expires_at"]),
            cap_boi=cap_boi,
            tao_luc=_iso(dong["tao_luc"]),
        )

    async def duyet(
        self, id_yeu_cau: str, *, xu_ly_boi: str, vung: tuple[str, ...], ghi_audit: GhiAuditDuyet
    ) -> tuple[YeuCauBreakGlass, Grant]:
        """UPDATE có điều kiện -> kiểm grant còn hạn -> INSERT grant -> audit -> COMMIT, một transaction (5.2).

        Câu UPDATE `WHERE trang_thai = 'cho_duyet'` là phép chuyển và là nguồn
        sự thật: hai owner duyệt chen nhau thì đúng một UPDATE có hàng, lần kia
        0 hàng và được phân loại lại bằng một phép đọc (404 nếu hàng biến mất,
        409 nếu đã xử lý). Grant còn hạn của cặp `(act, role)` chứa **bất kỳ** id
        nào của vùng là 409 và rollback, nên yêu cầu **vẫn chờ**; phép kiểm chạy
        sau khóa tư vấn của cặp (`_khoa_va_kiem_grant`). `vung` là vùng đã lọc, gốc đứng
        đầu, do tầng trên tính dưới ngữ cảnh người xin; kho không tính lại.
        """
        if not vung:
            raise loi_vung_cap_rong()
        async with self._pool.acquire(timeout=THOI_HAN_BIEN_DOI) as conn:
            async with conn.transaction():
                moi = await conn.fetchrow(_SQL_DUYET, id_yeu_cau, xu_ly_boi, kiem_thoi_diem(thoi_diem_utc()))
                if moi is None:
                    raise await self._sau_update_rong(conn, id_yeu_cau)
                yc = _tu_dong(moi)
                await self._khoa_va_kiem_grant(conn, act=yc.act, role=yc.role, space=yc.space, hyperedge_ids=vung)
                grant = await self._ghi_grant(
                    conn, request_id=yc.id, act=yc.act, role=yc.role, space=yc.space,
                    hyperedge_ids=vung, thoi_han_phut=yc.thoi_han_phut, cap_boi=xu_ly_boi,
                )
                await ghi_audit(yc, grant)
        return yc, grant

    async def tu_choi(
        self, id_yeu_cau: str, *, xu_ly_boi: str, ly_do: str, ghi_audit: GhiAuditDuyet
    ) -> YeuCauBreakGlass:
        """UPDATE có điều kiện sang `tu_choi` -> audit -> COMMIT (5.2); 0 hàng phân loại như `duyet`."""
        async with self._pool.acquire(timeout=THOI_HAN_BIEN_DOI) as conn:
            async with conn.transaction():
                moi = await conn.fetchrow(
                    _SQL_TU_CHOI, id_yeu_cau, ly_do, xu_ly_boi, kiem_thoi_diem(thoi_diem_utc())
                )
                if moi is None:
                    raise await self._sau_update_rong(conn, id_yeu_cau)
                yc = _tu_dong(moi)
                await ghi_audit(yc, None)
        return yc

    async def cap(
        self, *, act: str, role: str, space: str, hyperedge_ids: tuple[str, ...],
        thoi_han_phut: int, cap_boi: str, ghi_audit: GhiAuditDuyet,
    ) -> Grant:
        """Cấp chủ động: kiểm grant còn hạn -> INSERT grant (`request_id` NULL) -> audit -> COMMIT (5.2)."""
        if not hyperedge_ids:
            raise loi_vung_cap_rong()
        async with self._pool.acquire(timeout=THOI_HAN_BIEN_DOI) as conn:
            async with conn.transaction():
                await self._khoa_va_kiem_grant(conn, act=act, role=role, space=space, hyperedge_ids=hyperedge_ids)
                grant = await self._ghi_grant(
                    conn, request_id=None, act=act, role=role, space=space,
                    hyperedge_ids=hyperedge_ids, thoi_han_phut=thoi_han_phut, cap_boi=cap_boi,
                )
                await ghi_audit(None, grant)
        return grant

    async def co_grant_con_han(self, act: str, role: str, hyperedge_id: str, space: str) -> bool:
        """Cặp (`act`, `role`) trong `space` có grant chưa hết hạn chứa hyperedge này không.

        Cùng câu SQL mà `tao` chạy bên trong transaction của nó; cửa đọc rời
        này cho 5.2/5.3 và bộ test. Không có đường ghi nào vào
        `breakglass_grants` ngoài helper test; gọi dưới ngữ cảnh vai (tham số
        là `real_account`/`role` của ngữ cảnh ấy).
        """
        async with self._pool.acquire() as conn:
            return bool(await conn.fetchval(_SQL_GRANT_CON_HAN, act, role, hyperedge_id, space))

    async def dong(self) -> None:
        await self._pool.close()


def loi_kho(loi: BaseException) -> LoiHoiDap | None:
    """Lỗi kết nối Postgres -> 503 `KHO_KHONG_SAN_SANG`; còn lại `None` để dội nguyên.

    Nhận diện theo **gốc module** của lớp ngoại lệ (`asyncpg`), cùng thủ pháp
    với `api.hoi_dap.loi_truy_hoi`, cộng lỗi socket và quá hạn của chính
    Python. Không envelope AD-8: đây là một tài nguyên, không phải một lượt hỏi.
    """
    da_qua: set[int] = set()
    hien_tai: BaseException | None = loi
    while hien_tai is not None and id(hien_tai) not in da_qua:
        da_qua.add(id(hien_tai))
        goc = type(hien_tai).__module__.split(".")[0]
        if goc == "asyncpg" or isinstance(hien_tai, (OSError, TimeoutError)):
            return LoiHoiDap(503, MA_KHO_KHONG_SAN_SANG, THONG_DIEP_KHO)
        hien_tai = hien_tai.__cause__ or hien_tai.__context__
    return None


# --- Ba ruột endpoint ------------------------------------------------------------


async def _duoi_ngu_canh(ngu_canh, goi):
    """Chạy `goi()` (một coroutine của engine) dưới `use_context`; lỗi kho ánh xạ như `/hoi-dap`."""
    try:
        with use_context(ngu_canh):
            return await goi()
    except PermissionContextMissing:
        raise LoiHoiDap(
            500, PermissionContextMissing.code, "thiếu ngữ cảnh quyền cho lời gọi này"
        ) from None
    except TrichDanNgoaiQuyen as loi:
        logger.warning("cửa quyền không dựng được trích dẫn: %s", loi)
        raise LoiHoiDap(500, MA_TRICH_DAN_NGOAI_QUYEN, THONG_DIEP_TRICH_DAN) from None
    except Exception as loi:
        da_biet = loi_truy_hoi(loi)
        if da_biet is None:
            raise
        logger.warning("đọc cửa quyền hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None


async def _thay_o_muc_nao(engine: EngineACL, ngu_canh, chuan: str):
    """`TrichDan` của hyperedge dưới vai, hay `None` nếu vắng."""
    thay = await _duoi_ngu_canh(ngu_canh, lambda: engine.trich_dan_theo_id([chuan]))
    return thay.get(chuan)


async def vung_cap_cua(engine: EngineACL, ngu_canh_xin, goc: str, k: int) -> tuple[str, ...]:
    """Vùng cấp đã lọc của một gốc, dưới ngữ cảnh **người xin** (story 5.2).

    Pha một: `EngineACL.vung_lan_can([goc], k)` - `k` câu `hyperedge_ke_can`
    rồi một câu `trich_dan_cua`, cả hai dưới ba mệnh đề lọc quyền của vai xin.
    Pha hai: `core.break_glass.loc_vung_cap` trên bản ghi năm trường. Gốc mà
    adapter không thấy (L0, không tồn tại, khác space) là vùng rỗng, không
    phải lỗi: tầng trên quyết đó là 404 hay 409 tùy đường.
    """
    thay = await _duoi_ngu_canh(ngu_canh_xin, lambda: engine.vung_lan_can([goc], k))
    if goc not in thay:
        return ()
    ung_vien = [
        UngVienVung(id=td.id, scope=td.scope, content_type=td.content_type, level=td.level, nhom=td.owner_group)
        for td in thay.values()
    ]
    goc_uv = next(uv for uv in ung_vien if uv.id == goc)
    return loc_vung_cap(goc_uv, ung_vien, muc_xin_duoc=MUC_XIN_DUOC)


def ngu_canh_nguoi_xin(act: str, role: str, space: str, policy: Policy):
    """Ngữ cảnh quyền của người xin (hay người nhận) dựng lại từ ảnh chụp `(act, role, space)`.

    Đi qua **đúng** `ngu_canh_cua_claim` với một `ClaimNguoiHoi` không cờ: không
    có factory thứ hai. Vai không còn trong bảng chính sách là `LoiHoiDap` 403
    mang `RoleUnknown.code`; nơi gọi quyết (hàng chờ và duyệt qua
    `_ngu_canh_xin_neu_dung_duoc`; cấp chủ động: 400 `NGUOI_NHAN_KHONG_HOP_LE`).
    Luật ở ADR-020 quyết định 1.
    """
    return ngu_canh_cua_claim(ClaimNguoiHoi(sub=act, role=role, space=space, demo=False, admin=False), policy)


def _la_vai_la(loi: LoiHoiDap) -> bool:
    return loi.http == 403 and loi.ma == RoleUnknown.code


def _ngu_canh_xin_neu_dung_duoc(yc: YeuCauBreakGlass, policy: Policy):
    """Ngữ cảnh người xin của một hàng cũ, hay `None` khi ảnh chụp không còn dựng được.

    Hai ca `None`: vai chụp không còn trong bảng chính sách (403 `RoleUnknown`),
    hay ảnh chụp không dựng được `DanhTinh` (400 `THAN_YEU_CAU_LA`, hàng ghi từ
    một seed cũ). Cả hai là **hàng cũ hỏng** chứ không phải lỗi của người gọi:
    hàng chờ cho mục ấy `vung_cap: []`, duyệt cho 409 `VUNG_CAP_RONG`. Lỗi khác
    dội nguyên.
    """
    try:
        return ngu_canh_nguoi_xin(yc.act, yc.role, yc.space, policy)
    except LoiHoiDap as loi:
        if _la_vai_la(loi) or (loi.http == 400 and loi.ma == MA_THAN_YEU_CAU_LA):
            return None
        raise


async def _goi_kho(goi):
    """Chạy một coroutine của kho; lỗi kết nối Postgres -> 503, `LoiHoiDap` dội nguyên."""
    try:
        return await goi()
    except LoiHoiDap:
        raise
    except Exception as loi:
        da_biet = loi_kho(loi)
        if da_biet is None:
            raise
        logger.warning("bảng break-glass hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None


async def _nhom_cua_owner(kho_tai_khoan: KhoTaiKhoan, claim: ClaimNguoiHoi) -> str | None:
    """Nhóm phụ trách của tài khoản đang gọi, đọc từ bảng `users`; `None` khi không có dòng."""
    dong = await _goi_kho(lambda: kho_tai_khoan.tra(claim.sub))
    return None if dong is None else dong.group_name


async def _yeu_cau_cua_owner(
    id_yeu_cau: str, *, claim: ClaimNguoiHoi, kho: KhoBreakGlass, kho_tai_khoan: KhoTaiKhoan
) -> YeuCauBreakGlass:
    """Hàng yêu cầu mà owner đang gọi được xử lý; ba cửa theo thứ tự cố định.

    Id không tiền tố / không có / khác space là **một** thân 404 (của 5.1),
    không chạm bảng `users`. Khác nhóm duyệt, chính người xin, hay tài khoản
    không còn trong `users` là **một** thân 403. Không còn chờ là 409 ở đây
    để không tốn một transaction; nguồn sự thật vẫn là câu UPDATE.
    """
    id_yeu_cau = id_yeu_cau.strip()
    if not id_yeu_cau.startswith(TIEN_TO_ID):
        raise loi_yeu_cau_khong_co()
    yc = await _goi_kho(lambda: kho.tra_mot(id_yeu_cau))
    if yc is None or yc.space != claim.space:
        raise loi_yeu_cau_khong_co()
    nhom = await _nhom_cua_owner(kho_tai_khoan, claim)
    if nhom is None or nhom != yc.nhom_duyet or yc.act == claim.sub:
        raise loi_khong_phai_owner()
    if not xu_ly_duoc(yc.trang_thai):
        raise loi_khong_con_cho()
    return yc


async def xin(
    hyperedge_id,
    ly_do,
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    engine: EngineACL,
    kho: KhoBreakGlass,
    audit: AuditPort,
) -> dict:
    """Một lần xin: kiểm thân -> ngữ cảnh -> cửa quyền -> tạo (grant, đang chờ, audit trong một transaction).

    Thứ tự cố định như `tra_loi`: thân sai không chạm kho, vai lạ là 403 mà
    không chạm kho, và cửa quyền chạy **trước** mọi phép đọc Postgres - một id
    vô hình không đáng một truy vấn bảng yêu cầu. Hai phép kiểm trùng nằm
    trong `KhoBreakGlass.tao`, cùng transaction với câu INSERT.
    """
    chuan = kiem_hyperedge_id(hyperedge_id)
    ly_do_sach = kiem_ly_do(ly_do)
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    td = await _thay_o_muc_nao(engine, ngu_canh, chuan)
    if td is None:
        raise loi_khong_xin_duoc()
    if td.level == MUC_DA_THAY_DU:
        raise LoiHoiDap(400, MA_HYPEREDGE_DA_THAY_DU, THONG_DIEP_DA_THAY_DU)
    if td.level != MUC_XIN_DUOC:
        raise loi_khong_xin_duoc()
    if td.owner_group is None:
        logger.error("bảng nhóm phụ trách không khai loại %r", td.content_type)
        raise LoiHoiDap(500, MA_NHOM_DUYET_KHONG_CO, THONG_DIEP_NHOM_DUYET)
    luc = thoi_diem_utc()
    yc = YeuCauBreakGlass(
        id=ma_yeu_cau(),
        act=ngu_canh.real_account,
        role=ngu_canh.role,
        space=ngu_canh.space,
        hyperedge_id=chuan,
        scope=td.scope,
        content_type=td.content_type,
        nhom_duyet=td.owner_group,
        ly_do=ly_do_sach,
        k=K_MAC_DINH,
        thoi_han_phut=THOI_HAN_PHUT,
        trang_thai=TRANG_THAI_CHO_DUYET,
        tao_luc=luc,
        cap_nhat=luc,
    )
    yc = await _goi_kho(lambda: kho.tao(yc, _ghi_audit(audit, ngu_canh, EVENT_BREAKGLASS_REQUEST)))
    return dict_yeu_cau(yc)


async def huy_yeu_cau(
    id_yeu_cau: str,
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    kho: KhoBreakGlass,
    audit: AuditPort,
) -> dict:
    """Người xin hủy yêu cầu của chính mình khi còn chờ; `act`/`space` từ ngữ cảnh, không từ đường dẫn.

    Id không mang tiền tố `bg-` là 404 `YEU_CAU_KHONG_CO` **trước** khi chạm
    kho: cùng thân với id lạ, nên không rò gì, và một đường dẫn bịa không
    đáng một truy vấn.
    """
    id_yeu_cau = id_yeu_cau.strip()
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    if not id_yeu_cau.startswith(TIEN_TO_ID):
        raise loi_yeu_cau_khong_co()
    yc = await _goi_kho(
        lambda: kho.huy(
            id_yeu_cau, ngu_canh.real_account, ngu_canh.space,
            _ghi_audit(audit, ngu_canh, EVENT_BREAKGLASS_CANCEL),
        )
    )
    return dict_yeu_cau(yc)


async def danh_sach(*, claim: ClaimNguoiHoi, policy: Policy, kho: KhoBreakGlass) -> dict:
    """Yêu cầu của chính tài khoản trong token, mới nhất trước, tối đa `SO_YEU_CAU_TOI_DA`."""
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    cac = await _goi_kho(lambda: kho.cua_toi(ngu_canh.real_account, SO_YEU_CAU_TOI_DA))
    return {"yeu_cau": [dict_yeu_cau(yc) for yc in cac]}


# --- Bốn ruột của story 5.2 ------------------------------------------------------


async def hang_cho(
    *, claim: ClaimNguoiHoi, policy: Policy, engine: EngineACL, kho: KhoBreakGlass, kho_tai_khoan: KhoTaiKhoan
) -> dict:
    """Hàng chờ của owner: yêu cầu còn chờ có `nhom_duyet` = nhóm của caller, cùng space, cũ nhất trước.

    Mỗi mục mang thêm `vung_cap`, tính **lúc đọc** dưới ngữ cảnh của người xin
    (vai xin không còn trong bảng chính sách -> `[]`). Tài khoản không có dòng
    `users`, hay có mà không nhóm nào khớp, là danh sách rỗng chứ không phải
    lỗi. Không lời gọi LLM nào; mỗi mục tốn `k + 1` câu Cypher.
    """
    ngu_canh_cua_claim(claim, policy)
    nhom = await _nhom_cua_owner(kho_tai_khoan, claim)
    if nhom is None:
        return {"yeu_cau": []}
    cac = await _goi_kho(lambda: kho.hang_cho(nhom, claim.space, SO_YEU_CAU_TOI_DA))
    ra = []
    for yc in cac:
        ngu_canh_xin = _ngu_canh_xin_neu_dung_duoc(yc, policy)
        vung = () if ngu_canh_xin is None else await vung_cap_cua(engine, ngu_canh_xin, yc.hyperedge_id, yc.k)
        than = dict_yeu_cau(yc)
        than["vung_cap"] = list(vung)
        ra.append(than)
    return {"yeu_cau": ra}


async def duyet(
    id_yeu_cau: str,
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    engine: EngineACL,
    kho: KhoBreakGlass,
    kho_tai_khoan: KhoTaiKhoan,
    audit: AuditPort,
) -> dict:
    """Owner duyệt: cửa owner -> ngữ cảnh người xin -> vùng cấp -> UPDATE + grant + audit trong một transaction.

    Thứ tự cố định: ngữ cảnh owner (vai lạ là 403 mà không chạm kho), hàng
    yêu cầu và ba cửa của `_yeu_cau_cua_owner`, rồi vùng cấp dưới ngữ cảnh
    **người xin** (vùng rỗng là 409, yêu cầu vẫn chờ), rồi `KhoBreakGlass.duyet`.
    `hyperedge_ids` của grant là vùng đã lọc, `act`/`role` là cặp của yêu cầu.
    """
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    yc = await _yeu_cau_cua_owner(id_yeu_cau, claim=claim, kho=kho, kho_tai_khoan=kho_tai_khoan)
    ngu_canh_xin = _ngu_canh_xin_neu_dung_duoc(yc, policy)
    vung = () if ngu_canh_xin is None else await vung_cap_cua(engine, ngu_canh_xin, yc.hyperedge_id, yc.k)
    if not vung:
        raise loi_vung_cap_rong()
    ghi = _ghi_audit_duyet(
        audit, ngu_canh, EVENT_BREAKGLASS_APPROVE, nhom_duyet=yc.nhom_duyet, nguoi_nhan=yc.act, vai_nhan=yc.role
    )
    yc_moi, grant = await _goi_kho(lambda: kho.duyet(yc.id, xu_ly_boi=ngu_canh.real_account, vung=vung, ghi_audit=ghi))
    return {"yeu_cau": dict_yeu_cau(yc_moi), "grant": dict_grant(grant)}


async def tu_choi(
    id_yeu_cau: str,
    ly_do,
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    kho: KhoBreakGlass,
    kho_tai_khoan: KhoTaiKhoan,
    audit: AuditPort,
) -> dict:
    """Owner từ chối: lý do kiểm **trước** mọi phép đọc kho (400 như 5.1), rồi cửa owner, rồi UPDATE + audit."""
    ly_do_sach = kiem_ly_do(ly_do)
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    yc = await _yeu_cau_cua_owner(id_yeu_cau, claim=claim, kho=kho, kho_tai_khoan=kho_tai_khoan)
    ghi = _ghi_audit_duyet(
        audit, ngu_canh, EVENT_BREAKGLASS_REJECT, nhom_duyet=yc.nhom_duyet, nguoi_nhan=yc.act, vai_nhan=yc.role
    )
    yc_moi = await _goi_kho(
        lambda: kho.tu_choi(yc.id, xu_ly_boi=ngu_canh.real_account, ly_do=ly_do_sach, ghi_audit=ghi)
    )
    return {"yeu_cau": dict_yeu_cau(yc_moi), "grant": None}


def _kiem_ten(gia_tri) -> str:
    """`act`/`role` của thân cấp chủ động: chuỗi không rỗng, không NUL, trong trần; sai là người nhận không hợp lệ."""
    if not isinstance(gia_tri, str) or KY_TU_CAM in gia_tri or len(gia_tri) > DAI_TEN_TOI_DA:
        raise loi_nguoi_nhan()
    sach = gia_tri.strip()
    if not sach:
        raise loi_nguoi_nhan()
    return sach


async def cap_chu_dong(
    act,
    role,
    hyperedge_id,
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    engine: EngineACL,
    kho: KhoBreakGlass,
    kho_tai_khoan: KhoTaiKhoan,
    audit: AuditPort,
) -> dict:
    """Owner cấp chủ động cho cặp `(act, role)` một gốc mà người nhận thấy ở L1, không qua yêu cầu.

    Thứ tự: thân -> ngữ cảnh owner -> người nhận (có trong `users` cùng space,
    vai có trong bảng chính sách; sai là **một** thân 400) -> mức của gốc
    dưới ngữ cảnh người nhận (vô hình 404, L2 400, cùng thân với đường xin)
    -> cửa owner (nhóm của loại nội dung gốc; người nhận là chính owner cũng
    403, cùng luật cấm tự duyệt) -> vùng cấp -> `KhoBreakGlass.cap`.
    """
    chuan = kiem_hyperedge_id(hyperedge_id)
    act_sach, role_sach = _kiem_ten(act), _kiem_ten(role)
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    dong_nhan = await _goi_kho(lambda: kho_tai_khoan.tra(act_sach))
    if dong_nhan is None or dong_nhan.khong_gian != claim.space:
        raise loi_nguoi_nhan()
    try:
        ngu_canh_nhan = ngu_canh_nguoi_xin(dong_nhan.account, role_sach, claim.space, policy)
    except LoiHoiDap as loi:
        if _la_vai_la(loi):
            raise loi_nguoi_nhan() from None
        raise
    td = await _thay_o_muc_nao(engine, ngu_canh_nhan, chuan)
    if td is None:
        raise loi_khong_xin_duoc()
    if td.level == MUC_DA_THAY_DU:
        raise LoiHoiDap(400, MA_HYPEREDGE_DA_THAY_DU, THONG_DIEP_DA_THAY_DU)
    if td.level != MUC_XIN_DUOC:
        raise loi_khong_xin_duoc()
    if td.owner_group is None:
        logger.error("bảng nhóm phụ trách không khai loại %r", td.content_type)
        raise LoiHoiDap(500, MA_NHOM_DUYET_KHONG_CO, THONG_DIEP_NHOM_DUYET)
    nhom = await _nhom_cua_owner(kho_tai_khoan, claim)
    if nhom is None or nhom != td.owner_group or dong_nhan.account == claim.sub:
        raise loi_khong_phai_owner()
    vung = await vung_cap_cua(engine, ngu_canh_nhan, chuan, K_MAC_DINH)
    if not vung:
        raise loi_vung_cap_rong()
    ghi = _ghi_audit_duyet(
        audit, ngu_canh, EVENT_BREAKGLASS_GRANT, nhom_duyet=td.owner_group,
        nguoi_nhan=dong_nhan.account, vai_nhan=ngu_canh_nhan.role,
    )
    grant = await _goi_kho(
        lambda: kho.cap(
            act=dong_nhan.account, role=ngu_canh_nhan.role, space=claim.space, hyperedge_ids=vung,
            thoi_han_phut=THOI_HAN_PHUT, cap_boi=ngu_canh.real_account, ghi_audit=ghi,
        )
    )
    return {"grant": dict_grant(grant)}


__all__ = [
    "ThanXinBreakGlass",
    "YeuCauBreakGlass",
    "KhoBreakGlass",
    "ThanTuChoi",
    "ThanCapChuDong",
    "Grant",
    "dict_yeu_cau",
    "dict_grant",
    "xin",
    "huy_yeu_cau",
    "danh_sach",
    "hang_cho",
    "duyet",
    "tu_choi",
    "cap_chu_dong",
    "vung_cap_cua",
    "ngu_canh_nguoi_xin",
]
