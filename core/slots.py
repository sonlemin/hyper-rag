"""Danh mục 8 vai slot của hyperedge - một nơi duy nhất cho toàn hệ.

Prompt trích xuất, nhãn cạnh Neo4j, `masked_slots` của bảng chính sách, API và
UI đều tra danh mục này (Consistency Conventions của spine). Nhãn tiếng Việt
hiển thị ("[nguyên nhân: che]") map từ đây nhưng sống ở `web/`, không ở đây.
"""

# Thứ tự cố định, snake_case. Thêm vai mới là đổi hợp đồng toàn hệ, không phải
# việc của một story lẻ.
SLOT_ROLES: tuple[str, ...] = (
    "subject",
    "symptom",
    "cause",
    "condition",
    "remediation",
    "source",
    "time",
    "owner",
)

SLOT_ROLE_SET: frozenset[str] = frozenset(SLOT_ROLES)

# Slot người phụ trách. Tách tên riêng vì nó là ngoại lệ có luật: tầng che luôn
# tổng quát hóa nó về mức vai/nhóm, kể cả khi vai đang hỏi ở L2 (AD-9). Vì luôn
# áp nên nó không được khai trong `masked_slots` của bảng chính sách.
OWNER_SLOT: str = "owner"

# Bảy slot còn lại - đúng tập khai được trong `masked_slots`. Thông điệp lỗi của
# validator liệt kê tập này, không liệt kê cả 8: gợi ý `owner` cho người sửa
# YAML là đẩy họ sang một lỗi khác.
POLICY_MASKABLE_SLOTS: tuple[str, ...] = tuple(s for s in SLOT_ROLES if s != OWNER_SLOT)
