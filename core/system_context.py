"""Constructor ngữ cảnh hệ thống - cửa duy nhất mở cờ bỏ-filter (AD-3).

Pipeline dựng graph của upstream tự gọi storage khi không có người hỏi, nên
ingest chạy dưới một ngữ cảnh khai báo riêng. Đây là ngoại lệ có đặc tả của
NFR-10, không phải cửa hậu, nên nó sống một file riêng: `test_import_lint.py`
canh bằng tên module, chỉ module ingest trong danh sách trắng được import.

Đây là module duy nhất chạm `core.permission._SYSTEM_KIND`. Sentinel đó là thứ
làm cho cửa này thành cửa duy nhất thật sự: module khác dựng thẳng
`PermissionContext(kind="system", ...)` sẽ nhận `SystemContextForbidden`, nên
không ai đi vòng qua được lớp canh của import-lint.

Handler truy vấn không bao giờ phát ngữ cảnh này; việc từ chối nó trên đường
truy vấn người dùng đặt ở tầng handler (Epic 3), vì adapter chỉ thấy contextvar
và không phân biệt được nguồn lời gọi.
"""

from types import MappingProxyType

from core.permission import _SYSTEM_KIND, PermissionContext

# Không có gì để che khi đọc thô, nhưng trường vẫn phải có mặt để hình dạng
# context là một, không phải hai.
_KHONG_CHE = MappingProxyType({})


def system_context(*, space: str, policy_version: str) -> PermissionContext:
    """Ngữ cảnh ingest: cờ bỏ-filter, không mang `allowed_keys`.

    `policy_version` vẫn đi kèm để audit ghi được bản chính sách đang hiệu lực
    tại thời điểm nạp.
    """
    return PermissionContext(
        kind=_SYSTEM_KIND,
        space=space,
        role=None,
        real_account=None,
        allowed_keys=None,
        masked_slots=_KHONG_CHE,
        grant_ids=(),
        policy_version=policy_version,
    )
