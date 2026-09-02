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

Từ story 2.1, cửa chung còn **hợp nhất** khóa mới với khóa đang có của chính id
đó (FR-11). Luật hợp nhất là hàm thuần trong `core/`; chỗ này chỉ là nơi duy
nhất gọi nó, và đó là điểm: ba đường ghi đã đi qua đúng một cửa để lấy khóa,
nên đặt phép hợp nhất ở đây thì chúng không thể lệch nhau về luật. Cái mỗi
adapter tự lo là *đọc khóa cũ* - ba kho ba cách đọc - còn *quyết định* thì một
chỗ. Bước đối chiếu hai kho (`adapters/doi_chieu.py`) vì thế chỉ còn phải bắt
lệch do sự cố, không phải bắt hai bản sao của cùng một luật trôi dạt.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Mapping

from core.keys import CHUA_GHI, filter_key, hop_nhat_khoa
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


def bat_buoc_ngu_canh_he_thong(viec: str) -> None:
    """Cửa AD-3 dùng chung: việc này chỉ chạy dưới ngữ cảnh hệ thống.

    Ba đường ghi đi qua đây, và từ story 2.1 cả bước đọc khóa hiện có của
    read-merge-write cũng vậy: bước đó đọc thô một trường (khóa quyền) trên
    những mục mà vai đang nạp có thể không được thấy, nên nó là ngoại lệ có đặc
    tả của AD-3 chứ không phải một đường đọc bình thường. Bị lọc theo khóa của
    tài liệu đang nạp thì nó không bao giờ thấy khóa khác scope cần hợp nhất, và
    khi đó luật hợp nhất chạy trên dữ liệu sai.

    Thiếu ngữ cảnh hoàn toàn thì `current_context()` tự dội
    `PermissionContextMissing` lên, giữ nguyên luật fail-closed đã có.
    """
    if not current_context().bypass_filter:
        raise IngestOutsideSystemContext(
            f"{viec} phải chạy dưới ngữ cảnh hệ thống của pipeline ingest"
            " (AD-3), không phải dưới ngữ cảnh vai người dùng"
        )


def ingest_key_for_write(khoa_cu, *, hang: Mapping[str, int]) -> str | None:
    """Cửa chung của đường ghi: đúng ngữ cảnh, đúng nhãn, rồi hợp nhất khóa.

    Ba adapter đều đi qua đây trước khi ghi, nên hai luật sống một chỗ thay vì
    ba bản sao dễ lệch: "ghi chỉ chạy dưới ngữ cảnh hệ thống" (AD-3) và "khóa
    của một id đa nguồn là khóa hạn chế nhất" (FR-11).

    `khoa_cu` **không có giá trị mặc định**, có chủ đích: một nơi gọi quên
    truyền khóa cũ mà vẫn chạy được là một đường ghi lặng lẽ quay về
    last-write-wins - đúng thứ story này đóng, và đúng loại lỗi mà không test
    nào bắt được vì kết quả vẫn là một khóa hợp lệ. Nơi nào cố ý không
    read-merge-write thì truyền `CHUA_GHI` tường minh và nói lý do tại chỗ
    (`Neo4jACLGraphStorage.upsert_edge` là nơi duy nhất như vậy).

    `khoa_cu` là khóa mà chính kho của adapter đang giữ cho id sắp ghi:
    `CHUA_GHI` khi kho chưa có id đó, `KHONG_KHOA` khi id đã hợp nhất ra không
    khóa, hoặc một khóa thật. Trả về khóa để ghi, hoặc `KHONG_KHOA` - và khi đó
    mỗi kho có nghĩa riêng của nó (vector xóa point, KV vô hình với mọi vai,
    graph giữ node cấu trúc không khóa).

    Loại nội dung không có hạng độ nhạy là `SensitivityRankUnknown` dội lên từ
    `core.keys`, trước khi chạm kho: từ chối cả lô.

    Tách khỏi `current_ingest_key` vì hàm kia chỉ trả lời "nhãn nào đang mở" và
    có nơi gọi ngoài đường ghi (fixture canh rò nhãn trong `tests/conftest.py`).
    """
    bat_buoc_ngu_canh_he_thong("ghi tri thức")
    return hop_nhat_khoa(khoa_cu, current_ingest_key(), hang=hang)


def ingest_keys_for_write(
    khoa_cu_theo_id: Mapping[str, object], *, hang: Mapping[str, int]
) -> dict[str, str | None]:
    """Bản theo lô của `ingest_key_for_write`, cho đường ghi nhiều id một lần.

    Cùng một cửa, cùng hai luật, chỉ khác hình dạng đầu vào: kho vector và kho
    KV nhận cả lô nên chúng đọc khóa cũ một lượt rồi hợp nhất một lượt. Kiểm
    ngữ cảnh và nhãn *một lần cho cả lô* và trước khi hợp nhất mục đầu tiên, nên
    ngữ nghĩa "từ chối cả lô" giữ nguyên.
    """
    bat_buoc_ngu_canh_he_thong("ghi tri thức")
    khoa_moi = current_ingest_key()
    return {
        id: hop_nhat_khoa(khoa_cu, khoa_moi, hang=hang)
        for id, khoa_cu in khoa_cu_theo_id.items()
    }


def current_ingest_key() -> str:
    """Khóa lọc của phạm vi nhãn đang mở, hoặc lỗi fail-closed."""
    try:
        return _NHAN.get()
    except LookupError:
        raise IngestLabelMissing(
            "chưa mở phạm vi nhãn ingest: không ghi được point thiếu khóa quyền"
        ) from None
