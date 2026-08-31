"""Tầng che dùng chung - stub chữ ký của story 1.2 (AD-9).

Story 1.6 viết ruột; ở đây chỉ chốt hai thứ mà story 1.3-1.5 cần có ngay:
chữ ký cố định để adapter gọi được trong đường trả về, và danh sách đóng các
method đọc phải đi qua tầng che. Nhờ vậy story 1.6 thay ruột mà không phải mở
lại adapter nào.

Chữ ký ba tham số theo AD-9: (kết quả, ngữ cảnh quyền, khóa hyperedge). Khóa
hyperedge là thứ cho phép tra `masked_slots` theo đúng loại nội dung của mục
đang che, và cũng là chỗ story 1.6 kiểm điều kiện nền của `grant_ids`.
"""

from typing import Any

from core.permission import PermissionContext

# Danh sách đóng, sống cạnh interface. Method đọc public mới của adapter mà
# chưa khai vào đây là CI fail (test phản chiếu ở story 1.7). Các method đọc
# ngoài danh sách được xử lý tường minh chỗ khác: `node_degree`/`edge_degree`
# co theo filter quyền, `has_node`/`has_edge` trả False cho mục ngoài quyền.
MASKED_READ_METHODS: frozenset[str] = frozenset(
    {"query", "get_node", "get_edge", "get_node_edges"}
)


def mask(result: Any, context: PermissionContext, hyperedge_key: str) -> Any:
    """Che nội dung theo chính sách slot trước khi kết quả rời adapter.

    Stub của story 1.2: trả nguyên trạng. Đúng với hiện trạng vì `grant_ids`
    còn rỗng và chưa có adapter nào ghi dữ liệu thật; story 1.6 thay phần thân
    mà giữ nguyên ba tham số này.
    """
    return result
