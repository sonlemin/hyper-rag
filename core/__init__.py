"""Tầng ACL thuần của hyper-rag-copilot.

Chỉ dùng stdlib, không I/O. Chiều import là luật: core/ không import
adapters/, api/, vendor/. Package này không tái xuất gì: mỗi module import
thẳng thứ nó cần, để `core.system_context` (cờ bỏ-filter của ingest) quét được
bằng tên module trong import-lint.

Nội dung hiện có, đặt từ story 1.2:

- `slots`           danh mục 8 vai slot snake_case
- `ids`             chuẩn hóa id node + namespace UUID5 + point id Qdrant
- `keys`            khóa lọc `{scope}:{content_type}` (AD-4)
- `policy`          kiểm và dựng bảng chính sách bất biến (AD-6)
- `permission`      PermissionContext + contextvar fail-closed (AD-3)
- `system_context`  constructor ngữ cảnh ingest, chỉ ingest được import
- `masking`         chữ ký tầng che + danh sách đóng method phải che (AD-9)
- `identity`        danh tính người hỏi và đường sang ngữ cảnh quyền (1.7)

Còn thiếu, vào ở các story sau: hàm hợp nhất khóa đa nguồn (2.1), validator đơn
điệu AD-5 (3.2), bộ lọc vùng break-glass (5.2), audit port (3.6).
"""
