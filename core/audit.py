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
# xóa đổi kho, mất dấu vết một lần xóa là mất dấu vết một thay đổi quyền). Các
# sự kiện lọc / từ chối / truy vấn của adapter vào ở story 3.6.
EVENT_LLM_COST: str = "llm_cost"
EVENT_EMBEDDING_COST: str = "embedding_cost"
EVENT_INGEST_DOC: str = "ingest_doc"
EVENT_DELETE_DOC: str = "delete_doc"
EVENT_DELETE_SPACE: str = "delete_space"
EVENTS: frozenset[str] = frozenset(
    {
        EVENT_LLM_COST,
        EVENT_EMBEDDING_COST,
        EVENT_INGEST_DOC,
        EVENT_DELETE_DOC,
        EVENT_DELETE_SPACE,
    }
)

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

    Quy ước `hyperedge_ids`: id **vector** của hyperedge (`rel-<md5>`, do
    upstream sinh từ tên fact), mờ, không mang nội dung fact - audit đi vào một
    kho ngoài tầng che. Pipeline ingest (2.3) ghi theo dạng đó; sự kiện lọc /
    truy vấn của adapter (3.6) theo cùng quy ước.
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
