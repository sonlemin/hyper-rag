"""Ngữ cảnh quyền bất biến và kênh truyền fail-closed (AD-3, NFR-10).

Hợp đồng storage của upstream không có tham số người dùng và `vendor/` không
được sửa, nên ngữ cảnh quyền đi bằng contextvar quấn quanh lời gọi. Contextvar
ở đây cố ý **không có giá trị mặc định**: đọc mà chưa ai set là
`PermissionContextMissing`, không có nhánh nào trả kết quả không filter.

Hai trạng thái, không có trạng thái thứ ba, và bất biến này được canh bằng code
chứ không bằng docstring. `__post_init__` bắt buộc `bypass_filter` đúng bằng
`allowed_keys is None`, nên không dựng được context vừa có cờ bỏ-filter vừa có
tập khóa, cũng không dựng được context không có cả hai.

Cờ bỏ-filter chỉ mở được từ `core/system_context.py`: giá trị `kind` của context
hệ thống phải đúng là đối tượng sentinel `_SYSTEM_KIND`, chuỗi `"system"` trần
bị từ chối.

Sentinel là phòng vệ lúc chạy, không phải hàng rào duy nhất - Python không có
private thật nên ai cũng import được tên bắt đầu bằng gạch dưới. Hàng rào chính
là hai luật danh sách trắng trong `tests/test_import_lint.py`: chỉ
`core/permission.py` (factory `user_context`) và `core/system_context.py` được
dựng thẳng `PermissionContext(...)`, và ngoài `core/` không ai được import tên
riêng tư của module này. Hai luật đó phát biểu được thành một câu và không có
biến thể cú pháp nào lách được, khác với việc đuổi theo từng dạng biểu thức.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Mapping

from core.ids import validate_space
from core.policy import Policy

KIND_USER = "user"
KIND_SYSTEM = "system"
KINDS = frozenset({KIND_USER, KIND_SYSTEM})


def _ten(gia_tri) -> str:
    return type(gia_tri).__name__


class _SystemKind(str):
    """Kiểu của sentinel `kind` cho context hệ thống. Không tự nó là chìa khóa."""

    __slots__ = ()


# Chìa khóa thật là chính đối tượng này, không phải kiểu của nó: `__post_init__`
# so bằng `is`, nên dựng một `_SystemKind("system")` mới cũng không qua được.
# Đây là lớp phòng vệ lúc chạy; lớp canh chính là luật danh sách trắng trong
# `tests/test_import_lint.py` - chỉ hai factory được dựng PermissionContext.
_SYSTEM_KIND: str = _SystemKind(KIND_SYSTEM)


class PermissionContextMissing(RuntimeError):
    """Gọi đường truy hồi mà chưa ai set ngữ cảnh quyền.

    `code` là mã lỗi API ổn định để test assert trên `code`, không trên thông
    điệp (AD-8, Consistency Conventions).
    """

    code = "PERMISSION_CONTEXT_MISSING"


class SystemContextRawRead(RuntimeError):
    """Hỏi `allowed_keys` trên context hệ thống - nhánh đúng là đọc thô."""

    code = "SYSTEM_CONTEXT_RAW_READ"


class SystemContextForbidden(RuntimeError):
    """Dựng context hệ thống ngoài `core/system_context.py`."""

    code = "SYSTEM_CONTEXT_FORBIDDEN"


@dataclass(frozen=True)
class PermissionContext:
    """Ngữ cảnh quyền của một request, phân giải một lần rồi đóng băng.

    Tám trường theo AD-3. `allowed_keys` là map namespace -> tập khóa, hoặc
    None với context hệ thống. `masked_slots` là map loại nội dung -> tập vai
    slot phải che, không phải tập phẳng: tầng che tra theo khóa của chính
    hyperedge đang che.
    """

    kind: str
    space: str
    role: str | None
    real_account: str | None
    allowed_keys: Mapping[str, frozenset[str]] | None
    masked_slots: Mapping[str, frozenset[str]]
    grant_ids: tuple[str, ...]
    policy_version: str

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(
                f"kind {self.kind!r} không hợp lệ, chỉ có {'/'.join(sorted(KINDS))}"
            )
        if self.kind == KIND_SYSTEM and self.kind is not _SYSTEM_KIND:
            raise SystemContextForbidden(
                "context hệ thống chỉ dựng được qua core.system_context.system_context()"
            )
        if (self.allowed_keys is None) != (self.kind == KIND_SYSTEM):
            raise ValueError(
                "không có trạng thái thứ ba: context hệ thống không mang "
                "allowed_keys, mọi context khác bắt buộc mang"
            )
        if not isinstance(self.grant_ids, tuple):
            raise TypeError(f"grant_ids phải là tuple, nhận được {_ten(self.grant_ids)}")

    @property
    def bypass_filter(self) -> bool:
        """Adapter gặp cờ này thì đọc thô; mọi context khác đều bị lọc."""
        return self.kind == KIND_SYSTEM

    def keys_for(self, namespace: str) -> frozenset[str]:
        """Tập khóa được phép của một namespace vector."""
        if self.bypass_filter:
            raise SystemContextRawRead(
                "context hệ thống không mang allowed_keys; kiểm `bypass_filter` "
                "rồi đọc thô thay vì hỏi tập khóa"
            )
        if namespace not in self.allowed_keys:
            raise KeyError(f"namespace {namespace!r} không có trong ngữ cảnh")
        return self.allowed_keys[namespace]

    def slots_to_mask(self, content_type: str) -> frozenset[str]:
        """Tập vai slot mà *bảng chính sách* bắt che với một loại nội dung.

        Chỉ phần khai trong YAML, và vì validator chỉ cho khai `masked_slots`
        cho loại nội dung đang ở L1, tập này tự nó đã là tập của riêng L1.
        Luật `owner` luôn tổng quát hóa (AD-9) áp thêm ở tầng che, không cộng
        vào đây - hai luật khác nguồn thì để khác chỗ.
        """
        return self.masked_slots.get(content_type, frozenset())


# Không giá trị mặc định: thiếu ngữ cảnh là lỗi, không phải "không filter".
_CURRENT: ContextVar[PermissionContext] = ContextVar("permission_context")


def current_context() -> PermissionContext:
    """Ngữ cảnh quyền của lời gọi hiện tại, hoặc lỗi fail-closed."""
    try:
        return _CURRENT.get()
    except LookupError:
        raise PermissionContextMissing(
            "chưa set ngữ cảnh quyền cho lời gọi này"
        ) from None


@contextmanager
def use_context(context: PermissionContext):
    """Quấn một lời gọi (thường là `aquery` của upstream) bằng ngữ cảnh quyền."""
    if not isinstance(context, PermissionContext):
        raise TypeError(f"use_context cần một PermissionContext, nhận được {_ten(context)}")
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)


def user_context(
    *,
    policy: Policy,
    role: str,
    space: str,
    real_account: str,
    grant_ids: tuple[str, ...] = (),
) -> PermissionContext:
    """Factory duy nhất dựng ngữ cảnh quyền của người dùng.

    Hàm thuần: chỉ tra bảng chính sách đã nạp, không đọc store. Điều kiện nền
    của `grant_ids` ("vai hiện tại còn thấy hyperedge từ L1 trở lên") kiểm ở
    tầng che, nơi khóa của hyperedge đã có trong tay.
    """
    if isinstance(grant_ids, str) or not isinstance(grant_ids, (tuple, list)):
        raise TypeError(f"grant_ids phải là tuple/list id, nhận được {_ten(grant_ids)}")
    if not isinstance(real_account, str):
        raise TypeError(f"real_account phải là chuỗi, nhận được {_ten(real_account)}")
    if not real_account.strip():
        raise ValueError("real_account rỗng, ngữ cảnh quyền không định danh được")
    # `space` đi thẳng vào tên collection Qdrant và nhãn Neo4j, nên nó có luật
    # riêng chặt hơn "chuỗi không rỗng"; luật đó sống ở `core/ids.py`.
    validate_space(space)
    hang = policy.role(role)
    return PermissionContext(
        kind=KIND_USER,
        space=space,
        role=role,
        real_account=real_account,
        allowed_keys=hang.allowed_keys,
        masked_slots=hang.masked_slots,
        grant_ids=tuple(grant_ids),
        policy_version=policy.policy_version,
    )
