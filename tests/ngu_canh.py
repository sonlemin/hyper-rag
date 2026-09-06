"""Hai cửa dựng ngữ cảnh mà mọi bộ test adapter dùng chung.

Trước đây hai hàm này chép nguyên văn ở bốn file test, kèm cả docstring. Bản
thứ hai của một quy ước là chỗ hai bên lệch nhau mà không ai biết: quy ước
`real_account = f"{ten_vai}01"` từng bị viết tay thành `"ts01"` ở
`tests/test_adapter_neo4j_that.py`, nên đổi quy ước ở một chỗ không kéo theo
chỗ kia.

Đặt ở `tests/` chứ không ở `tests/fixtures/`: luật import-lint cấm thư mục
fixture gọi vào `core/`, còn hai hàm này phải gọi đúng hai factory của `core/`.
"""

from core.permission import PermissionContext, user_context
from core.system_context import system_context


def vai(policy, ten_vai: str, khong_gian: str, grant_ids: tuple[str, ...] = ()) -> PermissionContext:
    """Ngữ cảnh quyền của một vai; đây là thứ adapter đọc lúc truy vấn.

    Tài khoản suy từ tên vai để mỗi vai có đúng một định danh trong mọi bộ
    test, và để một bộ test không tự chế ra một tài khoản không khớp bộ khác.

    `grant_ids` (story 5.3) là dãy id hyperedge của grant break-glass còn hạn,
    đi thẳng xuống factory; mặc định rỗng nên mọi ca trước 5.3 giữ nguyên.
    """
    return user_context(
        policy=policy, role=ten_vai, space=khong_gian, real_account=f"{ten_vai}01",
        grant_ids=grant_ids,
    )


def ngu_canh_ingest(khong_gian: str, policy) -> PermissionContext:
    """Ngữ cảnh hệ thống của pipeline nạp; adapter chỉ lấy `space` từ đây."""
    return system_context(space=khong_gian, policy_version=policy.policy_version)
