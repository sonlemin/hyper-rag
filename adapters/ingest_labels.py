"""Phạm vi nhãn ingest: khóa quyền của tài liệu đang được nạp (AD-4, FR-05).

Upstream dựng dict upsert bằng dict comprehension viết cứng đúng hai field
(`operate.py:461-479`), chunk cũng do upstream dựng và chỉ thêm `full_doc_id`.
Không có khe nào nhét `scope` với `content_type` vào, mà luật dự án cấm sửa
`vendor/`. Nên nhãn đi đường ngầm: pipeline ingest mở một phạm vi nhãn quanh
mỗi tài liệu, adapter đọc nhãn đang mở lúc `upsert`.

Không có nhãn mặc định. Chưa mở nhãn mà ghi là `IngestLabelMissing`, và adapter
từ chối cả lô. Một point không khóa hoặc vô hình vĩnh viễn, hoặc lọt vào mọi
vai; cả hai đều tệ hơn một lỗi nhìn thấy được.

Module này ở `adapters/`, không ở `core/`: nó là chuyện của tầng ghi, và `core/`
đang giữ ngân sách 500-800 dòng. Adapter Neo4j (story 1.4) ghi khóa lên node
đọc lại đúng module này, nhờ vậy hai kho lấy khóa từ một nguồn.

Điểm yếu đã biết: một entity xuất hiện trong nhiều tài liệu khác scope sẽ mang
nhãn của tài liệu ghi sau. Đó là khoản nợ "hợp nhất khóa đa nguồn" có địa chỉ ở
story 2.1, không chữa ở đây.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from core.keys import filter_key
from core.permission import current_context


class IngestOutsideSystemContext(RuntimeError):
    """Ghi tri thức dưới ngữ cảnh vai người dùng, không phải ngữ cảnh ingest.

    AD-3 nói ingest chạy dưới ngữ cảnh hệ thống tường minh. Đường ghi là chỗ
    duy nhất *đặt* khóa quyền, nên nếu một đường truy vấn người dùng ghi được
    thì chính người hỏi quyết định nhãn quyền của dữ liệu - đúng thứ toàn bộ
    tầng này dựng ra để chống. `space` cũng lấy theo ngữ cảnh, nên nó còn là
    một đường ghi chéo không gian.

    Ngoại lệ có đặc tả (đọc thô lúc hợp nhất khóa đa nguồn, story 2.1) vẫn nằm
    trong ngữ cảnh hệ thống nên không đụng cửa này.
    """

    code = "INGEST_OUTSIDE_SYSTEM_CONTEXT"


class IngestLabelMissing(RuntimeError):
    """Ghi dữ liệu mà chưa mở phạm vi nhãn ingest.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp
    (Consistency Conventions).
    """

    code = "INGEST_LABEL_MISSING"


# Không giá trị mặc định, cùng lý do với contextvar quyền: "chưa ai đặt nhãn"
# phải là một lỗi, không phải một nhãn rỗng chạy tiếp được.
_NHAN: ContextVar[str] = ContextVar("ingest_label")


@contextmanager
def ingest_label(*, scope: str, content_type: str):
    """Mở phạm vi nhãn cho một tài liệu; mọi lô ghi bên trong mang khóa này.

    Khóa dựng ngay tại cửa chứ không lúc ghi: nhãn hỏng (rỗng, chứa dấu phân
    tách) nổ ở dòng mở phạm vi, nơi người viết pipeline còn nhìn thấy tài liệu
    nào gây ra nó.

    Lồng nhau thì nhãn trong cùng thắng và thoát ra trả lại nhãn ngoài - đúng
    ngữ nghĩa token của contextvar, không phải một chồng nhãn tự quản.
    """
    khoa = filter_key(scope, content_type)
    token = _NHAN.set(khoa)
    try:
        yield khoa
    finally:
        _NHAN.reset(token)


def ingest_key_for_write() -> str:
    """Cửa chung của đường ghi: đúng ngữ cảnh, đúng nhãn, rồi mới trả khóa.

    Hai adapter đều đi qua đây trước khi ghi, nên luật "ghi chỉ chạy dưới ngữ
    cảnh hệ thống" (AD-3) sống một chỗ thay vì hai bản sao dễ lệch. Thiếu ngữ
    cảnh hoàn toàn thì `current_context()` tự dội `PermissionContextMissing`
    lên, giữ nguyên luật fail-closed đã có.

    Tách khỏi `current_ingest_key` vì hàm kia chỉ trả lời "nhãn nào đang mở" và
    có nơi gọi ngoài đường ghi (fixture canh rò nhãn trong `tests/conftest.py`).
    """
    if not current_context().bypass_filter:
        raise IngestOutsideSystemContext(
            "ghi tri thức phải chạy dưới ngữ cảnh hệ thống của pipeline ingest"
            " (AD-3), không phải dưới ngữ cảnh vai người dùng"
        )
    return current_ingest_key()


def current_ingest_key() -> str:
    """Khóa lọc của phạm vi nhãn đang mở, hoặc lỗi fail-closed."""
    try:
        return _NHAN.get()
    except LookupError:
        raise IngestLabelMissing(
            "chưa mở phạm vi nhãn ingest: không ghi được point thiếu khóa quyền"
        ) from None
