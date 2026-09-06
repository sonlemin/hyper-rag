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

Mã lỗi và luật viết ở `docs/adr/ADR-019-api-xin-break-glass.md`.
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
from api.xac_thuc import ClaimNguoiHoi
from core.audit import (
    EVENT_BREAKGLASS_CANCEL,
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
    TRANG_THAI_DA_HUY,
    huy_duoc,
)
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

# Khóa `chi_tiet` của hai hàng audit. `request_id` ở đây là **id của yêu cầu
# break-glass** (`bg-…`), không phải id của một lượt hỏi: đường này không có
# lượt, và 5.2 nối hàng duyệt với hàng xin bằng đúng khóa này.
CT_REQUEST_ID: str = "request_id"
CT_TRANG_THAI: str = "trang_thai"
CT_K: str = "k"
CT_THOI_HAN_PHUT: str = "thoi_han_phut"
CT_NHOM_DUYET: str = "nhom_duyet"

TIEN_TO_ID: str = "bg-"
# Tên index duy nhất một phần ở `api/sql/breakglass.sql`; `tao` chỉ đổi
# `UniqueViolationError` mang đúng tên này thành 409 - một va chạm khóa chính
# không được đọc thành "đang chờ".
INDEX_CHO_DUYET: str = "breakglass_requests_cho_duyet_idx"
MUC_XIN_DUOC: str = "L1"
MUC_DA_THAY_DU: str = "L2"


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


# Thứ tự khóa của thân 201, đóng; `dict_yeu_cau` là chỗ duy nhất dựng nó.
KHOA_YEU_CAU: tuple[str, ...] = (
    "id", "act", "role", "space", "hyperedge_id", "scope", "content_type",
    "nhom_duyet", "trang_thai", "k", "thoi_han_phut", "ly_do", "tao_luc", "cap_nhat",
)


def dict_yeu_cau(yc: YeuCauBreakGlass) -> dict:
    """Thân JSON của một yêu cầu; không có `ly_do_tu_choi`/`xu_ly_boi` (5.2)."""
    return {k: getattr(yc, k) for k in KHOA_YEU_CAU}


def ma_yeu_cau() -> str:
    """Id yêu cầu: `bg-` + 12 hex của `uuid4`."""
    return TIEN_TO_ID + uuid.uuid4().hex[:12]


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


GhiAudit = Callable[[YeuCauBreakGlass], Awaitable[None]]


def _ghi_audit(audit: AuditPort, ngu_canh, event: str) -> GhiAudit:
    """Callable mà kho gọi **bên trong** transaction; hỏng là `AUDIT_GHI_HONG` và rollback."""

    async def ghi(yc: YeuCauBreakGlass) -> None:
        try:
            await asyncio.wait_for(
                ghi_bien_doi(audit, su_kien_break_glass(event, ngu_canh, yc)),
                timeout=THOI_HAN_BIEN_DOI,
            )
        except Exception as loi:
            logger.error("audit mutation %s không ghi được (%s: %s)", event, type(loi).__name__, loi)
            raise LoiHoiDap(500, MA_AUDIT_GHI_HONG, THONG_DIEP_AUDIT_HONG) from None

    return ghi


# --- Kho Postgres --------------------------------------------------------------

DUONG_DAN_DDL: Path = Path(__file__).resolve().parent / "sql" / "breakglass.sql"

_COT = (
    "id, act, role, space, hyperedge_id, scope, content_type, nhom_duyet, ly_do,"
    " k, thoi_han_phut, trang_thai, tao_luc, cap_nhat"
)
_SQL_DANG_CHO = f"""
    SELECT 1 FROM breakglass_requests
    WHERE act = $1 AND hyperedge_id = $2 AND trang_thai = '{TRANG_THAI_CHO_DUYET}'
    LIMIT 1
"""
_SQL_TAO = f"""
    INSERT INTO breakglass_requests ({_COT})
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
_SQL_GRANT_CON_HAN = """
    SELECT 1 FROM breakglass_grants
    WHERE act = $1 AND role = $2 AND $3 = ANY(hyperedge_ids) AND expires_at > now()
    LIMIT 1
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
                if await conn.fetchval(_SQL_GRANT_CON_HAN, yc.act, yc.role, yc.hyperedge_id):
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

    async def co_grant_con_han(self, act: str, role: str, hyperedge_id: str) -> bool:
        """Cặp (`act`, `role`) có grant chưa hết hạn chứa hyperedge này không.

        Cùng câu SQL mà `tao` chạy bên trong transaction của nó; cửa đọc rời
        này cho 5.2/5.3 và bộ test. Không có đường ghi nào vào
        `breakglass_grants` ngoài helper test; gọi dưới ngữ cảnh vai (tham số
        là `real_account`/`role` của ngữ cảnh ấy).
        """
        async with self._pool.acquire() as conn:
            return bool(await conn.fetchval(_SQL_GRANT_CON_HAN, act, role, hyperedge_id))

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


async def _thay_o_muc_nao(engine: EngineACL, ngu_canh, chuan: str):
    """`TrichDan` của hyperedge dưới vai, hay `None` nếu vắng; lỗi kho ánh xạ như `/hoi-dap`."""
    try:
        with use_context(ngu_canh):
            thay = await engine.trich_dan_theo_id([chuan])
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
    return thay.get(chuan)


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
    try:
        yc = await kho.tao(yc, _ghi_audit(audit, ngu_canh, EVENT_BREAKGLASS_REQUEST))
    except LoiHoiDap:
        raise
    except Exception as loi:
        da_biet = loi_kho(loi)
        if da_biet is None:
            raise
        logger.warning("bảng break-glass hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None
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
    try:
        yc = await kho.huy(
            id_yeu_cau, ngu_canh.real_account, ngu_canh.space,
            _ghi_audit(audit, ngu_canh, EVENT_BREAKGLASS_CANCEL),
        )
    except LoiHoiDap:
        raise
    except Exception as loi:
        da_biet = loi_kho(loi)
        if da_biet is None:
            raise
        logger.warning("bảng break-glass hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None
    return dict_yeu_cau(yc)


async def danh_sach(*, claim: ClaimNguoiHoi, policy: Policy, kho: KhoBreakGlass) -> dict:
    """Yêu cầu của chính tài khoản trong token, mới nhất trước, tối đa `SO_YEU_CAU_TOI_DA`."""
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    try:
        cac = await kho.cua_toi(ngu_canh.real_account, SO_YEU_CAU_TOI_DA)
    except Exception as loi:
        da_biet = loi_kho(loi)
        if da_biet is None:
            raise
        raise da_biet from None
    return {"yeu_cau": [dict_yeu_cau(yc) for yc in cac]}


__all__ = [
    "ThanXinBreakGlass",
    "YeuCauBreakGlass",
    "KhoBreakGlass",
    "dict_yeu_cau",
    "xin",
    "huy_yeu_cau",
    "danh_sach",
]
