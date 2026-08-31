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

    Quy ước: tên collection Qdrant = ``{session_prefix}_{space}_{namespace}``,
    workspace Neo4j và thư mục làm việc cũng mang prefix này.
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
