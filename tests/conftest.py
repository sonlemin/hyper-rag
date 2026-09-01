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


@pytest.fixture()
def khong_gian(session_prefix):
    """Không gian dữ liệu của một phiên test (E1-DATA-01, AD-12).

    Hai file `*_that.py` khai đè fixture này trong chính module của chúng để
    đổi hậu tố và để thêm cổng bỏ qua khi thiếu container.
    """
    return f"{session_prefix}_synth"


@pytest.fixture()
def policy():
    """Bảng chính sách đã nạp qua loader, đầu vào của factory ngữ cảnh."""
    from adapters.policy_loader import load_policy

    from tests.fixtures import oracle

    return load_policy(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def bang():
    """Bảng chính sách đọc thô, đầu vào của oracle.

    Cố ý là *hai* fixture chứ không một: `policy` đi qua loader của hệ, `bang`
    đọc thẳng file. Test đối chiếu hai bên với nhau, nên chúng phải đến từ hai
    đường khác nhau.
    """
    from tests.fixtures import oracle

    return oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def ma_hoa_offline(monkeypatch):
    """Bộ đếm token không cần mạng, cho bộ test đi qua `kg_query` thật.

    `truncate_list_by_token_size` (`utils.py:206`) gọi
    `tiktoken.encoding_for_model`, và lần gọi đầu tải bảng BPE **qua mạng**.
    Bộ Đo 1 nền phải chạy không mạng, mà thứ nó đo là quyền chứ không phải
    phép đếm token, nên đếm bằng byte UTF-8 là đủ: ngân sách 4000 token của
    `QueryParam` rộng hơn nhiều lần toàn bộ fixture, nên không mục nào bị cắt
    vì cách đếm.

    Không autouse: chỉ file nào đi qua đường truy vấn upstream mới cần, và
    file đó khai `pytestmark = pytest.mark.usefixtures("ma_hoa_offline")`. Bật
    cho cả suite là lặng lẽ thay một thành phần của `vendor/` ở những test
    chưa ai xét xem chúng có phụ thuộc nó không.

    `raising=True`: `ENCODER` có sẵn ở `utils.py:31`. Nếu upstream đổi tên nó
    thì phép vá phải đỏ ở đây, chứ không lặng lẽ thành no-op rồi để bộ Đo 1
    nền tải bảng BPE qua mạng - đúng thứ nó dựng ra để tránh.
    """
    from tests.gia_lap_llm import MaHoaOffline

    monkeypatch.setattr("hypergraphrag.utils.ENCODER", MaHoaOffline(), raising=True)


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
