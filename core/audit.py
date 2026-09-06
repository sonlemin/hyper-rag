"""Audit port: interface, danh mục sự kiện và luật hai tầng (AD-16, story 2.2).

Audit là một *port* tiêm vào chứ không phải một kho: `core/` chỉ nói sự kiện
trông thế nào và ai được phép hỏng theo cách nào; hiện thực (Postgres ở
`api/`, sổ bộ nhớ trong `tests/`) ở ngoài. Nhờ vậy wrapper LLM ở `adapters/`
ghi được sự kiện chi phí mà không import `api/`, và `eval/` cũng thế.

Hai tầng, luật sống một chỗ ở đây:

- **mutation** (`ghi_bien_doi`): ghi đồng bộ, port hỏng là thao tác hỏng. Dành
  cho sự kiện mà không có bản ghi thì thao tác không được phép xảy ra
  (break-glass, đổi chính sách - Epic 3/5).
- **observation** (`ghi_quan_sat`): best-effort và có thời hạn. Port hỏng hay
  quá hạn thì một dòng WARNING và thao tác vẫn trả kết quả. Dành cho số liệu
  đo (chi phí LLM, FR-30): một Postgres chết hay treo không được làm câu hỏi
  của người dùng chết hay treo theo.

`tier` khai tại nơi gọi, không suy từ `event`: cùng một sự kiện có thể quan
trọng khác nhau ở hai đường, và chỗ gọi là nơi duy nhất biết điều đó.

Danh mục `event` là hằng cạnh interface; thêm sự kiện là thêm hằng vào `EVENTS`.
Sự kiện lạ bị từ chối lúc dựng, để một chuỗi viết sai không thành một hàng
audit không ai truy vấn tới.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Protocol

TIER_MUTATION: str = "mutation"
TIER_OBSERVATION: str = "observation"
TIERS: frozenset[str] = frozenset({TIER_MUTATION, TIER_OBSERVATION})

# Danh mục sự kiện. Story 2.2 có hai sự kiện chi phí (tầng observation); story
# 2.3 thêm ba sự kiện ghi tri thức của pipeline ingest (tầng mutation: nạp và
# xóa đổi kho, mất dấu vết một lần xóa là mất dấu vết một thay đổi quyền);
# story 2.4 thêm `extract_doc` (tầng observation: số fact thô / hợp lệ / bị
# loại theo mã của một tài liệu, FR-02 - số liệu đo, mất một hàng không được
# làm hỏng lần nạp); story 3.2 thêm `policy_swap` (tầng **mutation**: hoán bảng
# chính sách đổi cái mà mọi vai thấy được, và một lần hoán không có bản ghi là
# một khoảng thời gian không ai nói được hệ đang chạy bảng nào - ghi hỏng là
# thao tác hỏng); story 3.3 thêm `query` (tầng **observation**: thời gian của
# một truy vấn là số liệu NFR-08, và một Postgres chết không được làm câu hỏi
# của người dùng chết theo); story 3.5 thêm `refusal` (tầng **observation**: một
# lượt từ chối là một hàng của hai cột mà Đo 2 đếm, và lý do từ chối chỉ được
# phép đi vào đây chứ không vào response - AD-8, FR-16); `query` và `refusal`
# tách ra sớm vì AC cuối của 3.3 đòi thời gian truy vấn ghi qua audit và FR-16
# đòi lý do từ chối ghi được ở đâu đó. Story 3.6 mở nốt bốn sự kiện để cả hai
# tầng đủ (AD-16), tầng của từng sự kiện ghi ngay cạnh hằng của nó ở dưới.
# Riêng `refusal` thì **tầng khai tại nơi gọi theo cờ chế độ đo**
# (`HYPER_RAG_CHE_DO_DO`, ADR-017): tắt thì observation như 3.5, bật thì mutation
# - một hàng `refusal` trong cửa sổ đo mà được phép mất là một mẫu số Đo 2
# không ai tin được.
EVENT_LLM_COST: str = "llm_cost"
EVENT_EMBEDDING_COST: str = "embedding_cost"
EVENT_INGEST_DOC: str = "ingest_doc"
EVENT_DELETE_DOC: str = "delete_doc"
EVENT_DELETE_SPACE: str = "delete_space"
EVENT_EXTRACT_DOC: str = "extract_doc"
EVENT_POLICY_SWAP: str = "policy_swap"
EVENT_QUERY: str = "query"
EVENT_REFUSAL: str = "refusal"
# Tầng observation: adapter KV lọc bớt mục sau khi đọc (tầng post-filter duy
# nhất, brief §6), chỉ số đếm theo mức, không id, không nội dung; mất một hàng
# là mất một số liệu của Đo 3, không được làm câu hỏi hỏng.
EVENT_FILTER: str = "filter"
# Tầng observation: một lần đăng nhập, cả hai chiều, để cửa đếm của 3-8 đứng
# lên; audit chết không được làm đăng nhập chết theo.
EVENT_AUTH_LOGIN: str = "auth_login"
# Tầng **mutation**: tiến trình khởi động với bảng chính sách nào và chế độ đo
# nào - không có hàng này thì cửa sổ đo không có mốc, nên ghi hỏng là tiến trình
# không lên.
EVENT_STARTUP: str = "startup"
# Tầng observation: tầng lọc và cửa quyền của adapter lệch nhau
# (`TRICH_DAN_NGOAI_QUYEN`), là lỗi hệ thống đã thành 500 ở handler; hàng này
# là dấu vết cho hậu kiểm FR-20 chứ không phải điều kiện để trả lời.
EVENT_PERMISSION_MISMATCH: str = "permission_mismatch"
# Tầng **mutation** (story 5.1, FR-20): một yêu cầu break-glass được tạo - ghi
# bên trong transaction của bảng yêu cầu, audit hỏng là không có hàng yêu cầu
# nào, vì một yêu cầu xin đọc phần bị che mà không có dấu vết là đúng thứ FR-20
# sinh ra để thay.
EVENT_BREAKGLASS_REQUEST: str = "breakglass_request"
# Tầng **mutation** (story 5.1): người xin hủy yêu cầu còn chờ; cùng luật với
# hàng tạo - hủy mà không có dấu vết là một yêu cầu biến mất khỏi hàng chờ của
# owner mà không ai nói được ai rút nó.
EVENT_BREAKGLASS_CANCEL: str = "breakglass_cancel"
# Tầng **mutation** (story 5.2, FR-20): owner duyệt một yêu cầu và grant được
# ghi trong cùng transaction - một grant mở phần bị che mà không có hàng nói ai
# duyệt, cho ai, vùng nào, là đúng lỗ mà FR-20 đòi bịt; audit hỏng là không
# có grant.
EVENT_BREAKGLASS_APPROVE: str = "breakglass_approve"
# Tầng **mutation** (story 5.2): owner từ chối; cùng luật với hủy - một yêu cầu
# rời hàng chờ phải để lại dấu vết ai gạt nó, dù không có grant nào sinh ra.
EVENT_BREAKGLASS_REJECT: str = "breakglass_reject"
# Tầng **mutation** (story 5.2): owner cấp chủ động không qua yêu cầu; đây là
# đường cấp duy nhất không có hàng `breakglass_request` đứng trước, nên hàng
# này là dấu vết duy nhất của grant ấy.
EVENT_BREAKGLASS_GRANT: str = "breakglass_grant"
EVENTS: frozenset[str] = frozenset(
    {
        EVENT_LLM_COST,
        EVENT_EMBEDDING_COST,
        EVENT_INGEST_DOC,
        EVENT_DELETE_DOC,
        EVENT_DELETE_SPACE,
        EVENT_EXTRACT_DOC,
        EVENT_POLICY_SWAP,
        EVENT_QUERY,
        EVENT_REFUSAL,
        EVENT_FILTER,
        EVENT_AUTH_LOGIN,
        EVENT_STARTUP,
        EVENT_PERMISSION_MISMATCH,
        EVENT_BREAKGLASS_REQUEST,
        EVENT_BREAKGLASS_CANCEL,
        EVENT_BREAKGLASS_APPROVE,
        EVENT_BREAKGLASS_REJECT,
        EVENT_BREAKGLASS_GRANT,
    }
)

# Space của sự kiện **thuộc tiến trình** (`startup`, `policy_swap`, `auth_login`):
# bảng chính sách hay một lần đăng nhập không thuộc không gian tri thức nào, mà
# `SuKienAudit` đòi `space` không rỗng. Luật: hàng mang giá trị này thuộc tiến
# trình, không thuộc space nào; mọi tổng theo space (`tong_chi_phi`,
# `dem_su_kien`) lọc bằng `=` nên không bao giờ trả nó, và cửa đọc riêng của nó
# là `AuditPostgres.su_kien_tien_trinh`. `core.ids.validate_space` từ chối chuỗi
# này, nên nó không thể lặng lẽ thành một tên space thật.
SPACE_TIEN_TRINH: str = "*"

# Khóa `chi_tiet` mang id của một lượt hỏi (story 3.6). `PermissionContext`
# chở nó xuống wrapper LLM, nên `query`, `refusal`, `filter`, `llm_cost`,
# `embedding_cost` và `permission_mismatch` của cùng một lượt nối được với nhau
# bằng một phép so chuỗi; ingest không có lượt nên để `None`.
CT_REQUEST_ID: str = "request_id"

# Thời hạn (giây) cho một lần ghi ở tầng observation. Một Postgres treo giữ
# kết nối mở mà không trả lời sẽ giữ lời gọi LLM treo theo nếu không có hạn;
# vài giây là đủ cho một INSERT trong network compose, và quá hạn thì mất một
# hàng số liệu chứ không mất một câu trả lời.
THOI_HAN_QUAN_SAT: float = 3.0

logger = logging.getLogger(__name__)


def thoi_diem_utc() -> str:
    """Thời điểm hiện tại, UTC, ISO-8601 có múi giờ (Consistency Conventions)."""
    return datetime.now(timezone.utc).isoformat()


def kiem_thoi_diem(chuoi: str) -> datetime:
    """Chuỗi phải parse được và phải mang múi giờ UTC; trả `datetime` đã parse.

    Public để hiện thực ở `api/` kiểm mốc thời gian đầu vào bằng đúng luật mà
    sự kiện dùng, thay vì viết bản thứ hai.
    """
    if not isinstance(chuoi, str):
        raise TypeError(f"thoi_diem phải là chuỗi ISO-8601, nhận được {type(chuoi).__name__}")
    try:
        gia_tri = datetime.fromisoformat(chuoi)
    except ValueError:
        raise ValueError(f"thoi_diem {chuoi!r} không phải ISO-8601") from None
    if gia_tri.tzinfo is None or gia_tri.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"thoi_diem {chuoi!r} phải mang múi giờ UTC")
    return gia_tri


def _chuoi_hoac_none(gia_tri, ten: str) -> None:
    if gia_tri is not None and not isinstance(gia_tri, str):
        raise TypeError(f"{ten} phải là chuỗi hoặc None, nhận được {type(gia_tri).__name__}")


@dataclass(frozen=True)
class SuKienAudit:
    """Một sự kiện audit, đã kiểm, bất biến.

    Bảy trường tối thiểu của AD-16 (`tier`, `act`, `role`, `event`,
    `hyperedge_ids`, `policy_version`, `space`) cộng `thoi_diem` và `chi_tiet`.
    `act` là tài khoản thật đứng sau lời gọi (`real_account` của ngữ cảnh quyền),
    `None` với ngữ cảnh hệ thống của ingest; `role` cũng vậy. `chi_tiet` là số
    liệu riêng của từng loại sự kiện (token, model, USD), giữ dạng map để hiện
    thực Postgres ghi thành jsonb mà không đổi lược đồ bảng khi thêm sự kiện.

    Quy ước `hyperedge_ids`, **hai dạng theo loại sự kiện**, cả hai đều mờ và
    không mang nội dung fact vì audit đi vào một kho ngoài tầng che:

    - sự kiện ingest (2.3) ghi id **vector** của hyperedge (`rel-<md5>`, do
      upstream sinh từ tên fact) - đó là id mà đường nạp cầm trong tay;
    - sự kiện `query` (3.4) ghi id **node** hyperedge, cùng id với trường `id`
      của từng citation trong response, để hậu kiểm đối chiếu được response
      với audit bằng một phép so chuỗi. Lượt từ chối ghi tuple rỗng;
      `permission_mismatch` (3.6) ghi các id node mà cửa quyền không xác nhận.
      Sự kiện `filter` (3.6) ghi tuple rỗng: nó chỉ mang số đếm theo mức.

    Ánh xạ giữa hai dạng có tên: `adapters.trich_xuat.id_vector_cua(he_id)` cho
    id vector từ id node, một chiều (băm), nên hậu kiểm nối `query` với hàng
    ingest bằng cách băm id của citation chứ không dò ngược.
    """

    tier: str
    event: str
    space: str
    policy_version: str
    thoi_diem: str
    act: str | None = None
    role: str | None = None
    hyperedge_ids: tuple[str, ...] = ()
    chi_tiet: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if self.tier not in TIERS:
            raise ValueError(f"tier {self.tier!r} không hợp lệ, chỉ có {sorted(TIERS)}")
        if self.event not in EVENTS:
            raise ValueError(
                f"event {self.event!r} không có trong danh mục {sorted(EVENTS)}:"
                " thêm sự kiện là thêm hằng trong core/audit.py"
            )
        if not isinstance(self.space, str) or not self.space:
            raise ValueError("space rỗng: sự kiện audit phải biết nó thuộc không gian nào")
        if not isinstance(self.policy_version, str) or not self.policy_version:
            raise ValueError("policy_version rỗng")
        kiem_thoi_diem(self.thoi_diem)
        _chuoi_hoac_none(self.act, "act")
        _chuoi_hoac_none(self.role, "role")
        if not isinstance(self.hyperedge_ids, tuple):
            raise TypeError(
                f"hyperedge_ids phải là tuple, nhận được {type(self.hyperedge_ids).__name__}"
            )
        if not all(isinstance(h, str) for h in self.hyperedge_ids):
            raise TypeError("mọi phần tử của hyperedge_ids phải là chuỗi id")
        if not isinstance(self.chi_tiet, Mapping):
            raise TypeError(f"chi_tiet phải là map, nhận được {type(self.chi_tiet).__name__}")
        # Đóng băng phần chi tiết: sự kiện đã dựng thì không ai sửa số được nữa.
        object.__setattr__(self, "chi_tiet", MappingProxyType(dict(self.chi_tiet)))


class AuditPort(Protocol):
    """Hợp đồng tối thiểu của một hiện thực audit: ghi một sự kiện."""

    async def ghi(self, su_kien: SuKienAudit) -> None: ...


async def ghi_bien_doi(port: AuditPort, su_kien: SuKienAudit) -> None:
    """Tầng mutation: ghi đồng bộ, lỗi của port dội thẳng lên nơi gọi."""
    if su_kien.tier != TIER_MUTATION:
        raise ValueError(
            f"ghi_bien_doi chỉ nhận tier {TIER_MUTATION!r}, sự kiện mang {su_kien.tier!r}"
        )
    await port.ghi(su_kien)


async def ghi_quan_sat(
    port: AuditPort, su_kien: SuKienAudit, *, thoi_han: float = THOI_HAN_QUAN_SAT
) -> None:
    """Tầng observation: best-effort có thời hạn, port hỏng hay quá hạn thì WARNING.

    Bắt `Exception` chứ không `BaseException`: hủy task (`CancelledError`) và
    ngắt tiến trình vẫn phải đi qua, chỉ lỗi của chính port mới được nuốt.
    `TimeoutError` của `wait_for` là `Exception`, nên quá hạn đi cùng nhánh.
    """
    if su_kien.tier != TIER_OBSERVATION:
        raise ValueError(
            f"ghi_quan_sat chỉ nhận tier {TIER_OBSERVATION!r}, sự kiện mang {su_kien.tier!r}"
        )
    try:
        await asyncio.wait_for(port.ghi(su_kien), timeout=thoi_han)
    except TimeoutError:
        logger.warning(
            "audit observation %s quá hạn %.1fs, bỏ qua; lời gọi vẫn tiếp tục",
            su_kien.event,
            thoi_han,
        )
    except Exception as loi:
        logger.warning(
            "audit observation %s không ghi được (%s: %s); lời gọi vẫn tiếp tục",
            su_kien.event,
            type(loi).__name__,
            loi,
        )
