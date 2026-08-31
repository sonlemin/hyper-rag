"""Chuẩn hóa id node và sinh point id Qdrant - một nơi duy nhất.

Upstream bọc tên node bằng dấu nháy kép (`"App01"`) khi ghi ra graph. Nếu mỗi
adapter tự gỡ theo cách riêng thì id ở Neo4j và ở Qdrant lệch nhau, và test
NFR-03 (so id join chéo hai kho) mất ý nghĩa. Cả hai adapter gọi hàm ở đây.
"""

import unicodedata
import uuid

# Namespace UUID5 cố định của dự án, đặt cạnh hàm chuẩn hóa theo spine.
# Sinh một lần bằng uuid5(NAMESPACE_DNS, "hyper-rag-copilot.node-id") rồi ghim
# thành hằng: đổi giá trị này là đổi mọi point id đã ghi, phải re-ingest.
ID_NAMESPACE: uuid.UUID = uuid.UUID("93cef57c-8531-53de-a55f-dbe2449c3d9d")


def normalize_id(raw: str) -> str:
    """Chuẩn hóa Unicode về NFC, bỏ khoảng trắng thừa và dấu nháy kép bao quanh.

    Bước NFC không phải làm cho đẹp: tiếng Việt gõ dạng tổ hợp (NFD) và dạng
    dựng sẵn (NFC) là hai chuỗi byte khác nhau, để nguyên thì cùng một thực thể
    ra hai id và hai UUID5 - đúng thứ module này sinh ra để chống.
    """
    if not isinstance(raw, str):
        raise TypeError(f"id phải là chuỗi, nhận được {type(raw).__name__}")
    ten = unicodedata.normalize("NFC", raw).strip()
    while len(ten) >= 2 and ten[0] == '"' and ten[-1] == '"':
        ten = ten[1:-1].strip()
    if not ten:
        raise ValueError(f"id rỗng sau khi chuẩn hóa: {raw!r}")
    return ten


def point_id(raw: str) -> str:
    """Point id Qdrant = UUID5 từ id đã chuẩn hóa; id gốc giữ trong payload."""
    return str(uuid.uuid5(ID_NAMESPACE, normalize_id(raw)))
