"""Quy ước cách ly dữ liệu test cho toàn bộ suite (E1-DATA-01).

Mọi test đụng storage thật (Qdrant collection, Neo4j workspace, thư mục làm
việc HyperGraphRAG) phải đặt tên qua fixture `session_prefix` để hai phiên
test chạy song song không giẫm dữ liệu nhau và dọn được theo prefix.
Bộ test CI không cần mạng ngoài, không cần key LLM.
"""

import uuid

import pytest


@pytest.fixture(scope="session")
def session_prefix() -> str:
    """Prefix duy nhất theo phiên test, ví dụ ``test_3fa9c1d2``.

    Quy ước: prefix gấp vào trong ``space`` của ngữ cảnh quyền, ví dụ
    ``test_3fa9c1d2_synth``. Tên collection Qdrant là ``{space}_{namespace}``
    (AD-12), nên nó thành ``test_3fa9c1d2_synth_hyperedges``. Workspace Neo4j
    và thư mục làm việc cũng mang prefix theo cùng cách.
    """
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def workspace_dir(tmp_path, session_prefix):
    """Thư mục làm việc HyperGraphRAG cách ly cho một test."""
    d = tmp_path / session_prefix
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def ngu_canh_quyen_sach():
    """Xóa contextvar quyền trước và sau mỗi test.

    Test fail-closed khẳng định "chưa ai set thì raise". Không có fixture này,
    một test rò ngữ cảnh ra ngoài phạm vi của nó sẽ làm khẳng định đó đúng hay
    sai tùy thứ tự chạy - đúng kiểu test bảo mật xanh vì lý do sai.

    Chạm vào `_CURRENT` là cố ý: `core/` không phơi hàm xóa ngữ cảnh, và cũng
    không nên phơi, vì ngoài test không có ai cần nó.
    """
    from core.permission import _CURRENT

    def xoa():
        token = _CURRENT.set(None)
        _CURRENT.reset(token)

    xoa()
    yield
    xoa()


@pytest.fixture(autouse=True)
def nhan_ingest_sach():
    """Canh nhãn ingest không rò ra ngoài phạm vi một test.

    Đối xứng với ``ngu_canh_quyen_sach`` và cùng một lý do: test "chưa mở nhãn
    thì từ chối ghi" chỉ có nghĩa khi không test nào trước đó bỏ quên một nhãn
    đang mở, nếu không kết quả phụ thuộc thứ tự chạy.

    Kiểm hai đầu chứ không xóa, vì contextvar không có phép xóa: giữ token để
    xóa được nghĩa là biến phải ở trạng thái *đã đặt* suốt test, đúng thứ làm
    hỏng các test fail-closed. Nhãn chỉ mở được qua ``ingest_label`` (một
    context manager có try/finally), nên rò nhãn là dấu hiệu ai đó chạm thẳng
    contextvar - đáng nổ to chứ không đáng dọn im lặng.
    """
    from adapters.ingest_labels import IngestLabelMissing, current_ingest_key

    def dang_mo():
        try:
            return current_ingest_key()
        except IngestLabelMissing:
            return None

    ro_ri = dang_mo()
    assert ro_ri is None, f"một test chạy trước đã để rò nhãn ingest {ro_ri!r}"
    yield
    ro_ri = dang_mo()
    assert ro_ri is None, f"test này thoát khi nhãn ingest {ro_ri!r} còn mở"
