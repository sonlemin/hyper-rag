"""Cổng M1: hai tài khoản, hai kết quả, sinh từ cơ chế thật (story 1.7).

Bảy kịch bản `1.7-INT-001..007` của test-design cộng mọi hàng I/O Matrix của
spec. Khác mọi bộ test trước của Epic 1 ở một điểm: ba adapter không còn được
gọi trực tiếp mà đi qua `HyperGraphRAG.aquery` thật, nên đây là chỗ đầu tiên
chứng minh được contextvar quyền sống qua pipeline async của upstream.

Ba lớp assert, theo thứ tự quan trọng:

1. **Chuỗi ngữ cảnh truy hồi** (`QueryParam(only_need_context=True)`), không
   bao giờ là câu trả lời LLM - chốt brief §6. Bộ này còn ghim luôn rằng không
   có lời gọi LLM nào mang `system_prompt`, tức không đường nào đi tới bước
   sinh câu trả lời.
2. **Bộ lọc đi cùng request**: đối tượng filter trong search request Qdrant và
   mệnh đề WHERE trong chính câu Cypher. Nhìn vào kết quả thì không phân biệt
   được pre-filter với lọc lại phía Python.
3. **Kỳ vọng lấy từ `tests/fixtures/oracle.py`**, bộ tính độc lập không import
   `core/`.

Không mạng, không container, không key LLM: Qdrant là local mode có ghi nhật
ký, Neo4j là driver giả, LLM là bản giả trả đúng định dạng bản ghi từ khóa,
embedding là hàm hash cố định, và bộ mã hóa token được thay bằng bản offline
(tiktoken tải bảng BPE qua mạng ở lần dùng đầu tiên).
"""

import asyncio
import logging
from dataclasses import FrozenInstanceError, asdict, fields, replace
from pathlib import Path

import pytest
import yaml
from hypergraphrag import HyperGraphRAG
from hypergraphrag.base import QueryParam
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient

from adapters.engine import (
    BIEN_MOI_TRUONG,
    KHOA_CAU_HINH_KHO,
    KHOA_KHONG_LAY_TU_MOI_TRUONG,
    EngineACL,
    cau_hinh_kho_tu_moi_truong,
)
from adapters.identity_seed import (
    DUONG_DAN_DANH_TINH_DEMO,
    IdentitySeedInvalid,
    nap_danh_tinh,
)
from adapters.kv import ENABLE_LLM_CACHE, JsonACLKVStorage, LLMCacheDisabled
from adapters.neo4j import Neo4jACLGraphStorage
from adapters.policy_loader import load_policy
from adapters.qdrant import QdrantVectorDBStorage
from core.identity import DanhTinh, RoleUnknown, ngu_canh_cua
from core.permission import PermissionContextMissing, use_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, THEO_ID
from tests.gia_lap_llm import LLMGia
from tests.gia_lap_neo4j import Neo4jGhiLai, canh_moi_bien_deu_bi_loc
from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia, khoa_trong_filter
from tests.nap_kho import kiem_fixture, nap_ba_kho, ten_hyperedge

REPO_ROOT = Path(__file__).resolve().parent.parent

CAU_HOI = "App01 trả lỗi 502 thì xử lý thế nào"

# Hai giá trị nhận biết được, chỉ dùng cho ca kiểm secret-không-ra-log. Không
# phải secret thật và không giống một secret thật: chuỗi trong bộ test là thứ
# người ta hay copy đi chỗ khác.
MAT_KHAU_NHAN_BIET = "mat-khau-khong-duoc-ra-log-a1b2c3"
API_KEY_NHAN_BIET = "api-key-khong-duoc-ra-log-d4e5f6"

# Ba dấu hiệu của việc chạy code trong thread khác. Nếu `vendor/` dùng bất kỳ
# cái nào thì contextvar quyền có thể đứt và đường lùi "engine per-request" của
# spine (`:245`) phải được dựng. Grep ra rỗng là bằng chứng cho quyết định
# không dựng nó; test dưới đây giữ bằng chứng đó sống thay vì để nó thành một
# câu trong tài liệu.
DAU_HIEU_THREAD = (
    "to_thread",
    "run_in_executor",
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "threading.Thread",
    "run_coroutine_threadsafe",
    "call_soon_threadsafe",
)


class _MaHoaOffline:
    """Bộ đếm token thay `tiktoken` cho bộ Đo 1 nền.

    `truncate_list_by_token_size` (`utils.py:206`) gọi
    `tiktoken.encoding_for_model`, và lần gọi đầu tải bảng BPE **qua mạng**.
    Bộ Đo 1 nền phải chạy không mạng, mà thứ nó đo là quyền chứ không phải phép
    đếm token, nên đếm bằng byte UTF-8 là đủ: ngân sách 4000 token của
    `QueryParam` rộng hơn nhiều lần toàn bộ fixture, nên không có mục nào bị
    cắt vì cách đếm.
    """

    @staticmethod
    def encode(noi_dung: str) -> list[int]:
        return list(noi_dung.encode("utf-8"))

    @staticmethod
    def decode(tokens: list[int]) -> str:
        return bytes(tokens).decode("utf-8", errors="ignore")


@pytest.fixture(autouse=True)
def ma_hoa_offline(monkeypatch):
    # `raising=True`: `ENCODER` có sẵn ở `utils.py:31`. Nếu upstream đổi tên nó
    # thì phép vá phải đỏ ở đây, chứ không lặng lẽ thành no-op rồi để bộ Đo 1
    # nền tải bảng BPE qua mạng - đúng thứ nó dựng ra để tránh.
    monkeypatch.setattr("hypergraphrag.utils.ENCODER", _MaHoaOffline(), raising=True)


@pytest.fixture()
def bang():
    """Bảng chính sách đọc thô, đầu vào của oracle."""
    return oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def policy():
    """Bảng chính sách đã nạp qua loader, đầu vào của factory ngữ cảnh."""
    return load_policy(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def khong_gian(session_prefix):
    """Không gian dữ liệu của một phiên test (E1-DATA-01, AD-12)."""
    return f"{session_prefix}_synth"


@pytest.fixture()
def danh_tinh_demo(khong_gian):
    """Hai danh tính seed, chuyển sang không gian cách ly của phiên test.

    Vai và tài khoản lấy từ `config/danh-tinh-demo.yaml`, không viết trong
    test: đó đúng là điều AC đòi ("ngữ cảnh quyền phát từ danh tính, không
    hard-code trong test"). `khong_gian` thì là chuyện cách ly dữ liệu của bộ
    test, nên nó - và chỉ nó - được thay.
    """
    return tuple(
        replace(dt, khong_gian=khong_gian) for dt in nap_danh_tinh()
    )


def dung_engine(workspace_dir, client, driver, llm, **them) -> EngineACL:
    """Engine cổng M1: ba adapter thật, ba kết nối giả, LLM giả."""
    return EngineACL(
        working_dir=str(workspace_dir),
        embedding_func=embedding_gia(),
        llm_model_func=llm,
        embedding_batch_num=2,
        tao_qdrant_client=(lambda: client) if client is not None else None,
        tao_neo4j_driver=(lambda: driver) if driver is not None else None,
        **them,
    )


async def cong_m1(workspace_dir, khong_gian, policy):
    """Engine đã khởi tạo và nạp xong fixture, nhật ký đã xóa sạch."""
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    llm = LLMGia()
    engine = dung_engine(workspace_dir, client, driver, llm)
    await nap_ba_kho(engine, khong_gian=khong_gian, policy=policy)
    client.xoa_nhat_ky()
    driver.xoa_nhat_ky()
    llm.xoa_nhat_ky()
    return engine, client, driver, llm


async def hoi(engine, ngu_canh, cau_hoi: str = CAU_HOI) -> str:
    """Một truy vấn dừng ở ngữ cảnh truy hồi, dưới một ngữ cảnh quyền."""
    with use_context(ngu_canh):
        return await engine.aquery(cau_hoi, QueryParam(only_need_context=True))


def ten_hyperedge_trong(ngu_canh_truy_hoi: str) -> set[str]:
    """Tên các hyperedge xuất hiện trong chuỗi ngữ cảnh.

    Tên hyperedge là chuỗi duy nhất định danh một fact ở cả hai kho, nên nó là
    thứ đo được "vai này truy hồi được những fact nào" mà không phải parse CSV
    của upstream.
    """
    return {
        ten_hyperedge(he)
        for he in HYPEREDGES
        if ten_hyperedge(he) in ngu_canh_truy_hoi
    }


def chunk_trong(ngu_canh_truy_hoi: str) -> set[str]:
    """Id các chunk mà nguyên văn nội dung của chúng lọt vào ngữ cảnh."""
    return {c["id"] for c in CHUNKS if c["content"] in ngu_canh_truy_hoi}


def ten_hyperedge_ky_vong(bang, vai: str) -> set[str]:
    """Tập tên hyperedge mà oracle nói vai này còn thấy (từ L1 trở lên)."""
    return {
        ten_hyperedge(THEO_ID[id_he])
        for id_he in oracle.hyperedge_thay_duoc(bang, vai, HYPEREDGES)
    }


def khoa_theo_collection(client: QdrantGhiLai) -> dict[str, set[str]]:
    """Tập khóa của filter trong mỗi search request đã phát, theo collection."""
    theo_collection: dict[str, set[str]] = {}
    for goi in client.cac_loi_goi("query_points"):
        ten = goi.kwargs["collection_name"]
        theo_collection[ten] = khoa_trong_filter(goi.kwargs["query_filter"])
    return theo_collection


# --- I/O Matrix: dựng engine ------------------------------------------------


def test_registry_tra_ba_adapter_cua_du_an(workspace_dir):
    """`_get_storage_class()` chỉ còn ba adapter của dự án, và cache LLM tắt.

    Đây là cơ chế thật mà story 1.5 còn phải giả lập bằng monkeypatch tên
    module: registry của upstream được override, nên `llm_response_cache is
    None` là kết quả của chính đường mà sản phẩm đi.
    """
    engine = dung_engine(workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), LLMGia())
    registry = engine._get_storage_class()
    lop = {ten: getattr(muc, "func", muc) for ten, muc in registry.items()}
    assert set(lop.values()) == {
        JsonACLKVStorage,
        QdrantVectorDBStorage,
        Neo4jACLGraphStorage,
    }
    assert lop[engine.kv_storage] is JsonACLKVStorage
    assert lop[engine.vector_storage] is QdrantVectorDBStorage
    assert lop[engine.graph_storage] is Neo4jACLGraphStorage
    assert engine.llm_response_cache is None
    assert isinstance(engine.text_chunks, JsonACLKVStorage)
    assert isinstance(engine.entities_vdb, QdrantVectorDBStorage)
    assert isinstance(engine.chunk_entity_relation_graph, Neo4jACLGraphStorage)


def test_bay_khoa_cau_hinh_kho_di_qua_asdict(workspace_dir):
    """Bảy khóa cấu hình kho có mặt trong `asdict(self)` mà adapter đọc.

    Đây là khoản nợ chung của cả ba story adapter: mỗi adapter đọc một nhóm
    khóa từ `global_config` mà chưa ai sinh ra chúng. `asdict(self)` là cái
    duy nhất upstream truyền xuống storage (`hypergraphrag.py:198-240`), nên
    "khóa có nguồn" nghĩa đúng là "khóa là field của engine".
    """
    engine = dung_engine(
        workspace_dir,
        QdrantGhiLai(),
        Neo4jGhiLai(),
        LLMGia(),
        qdrant_url="http://qdrant:6333",
        qdrant_api_key="bi-mat",
        neo4j_uri="bolt://neo4j:7687",
        neo4j_password="mat-khau",
        cosine_better_than_threshold=0.31,
    )
    ten_field = {f.name for f in fields(EngineACL)}
    cau_hinh = asdict(engine)
    for khoa in KHOA_CAU_HINH_KHO:
        assert khoa in ten_field, f"{khoa} không phải field của engine"
        assert khoa in cau_hinh, f"{khoa} không đi xuống global_config"
    # Bảy khóa kết nối của I/O Matrix, viết thẳng ra để con số trong spec có
    # người canh.
    assert {
        "qdrant_url",
        "qdrant_api_key",
        "neo4j_uri",
        "neo4j_username",
        "neo4j_password",
        "neo4j_health_retries",
        "neo4j_health_delay",
    } <= set(KHOA_CAU_HINH_KHO)
    assert cau_hinh["qdrant_url"] == "http://qdrant:6333"
    assert cau_hinh["neo4j_uri"] == "bolt://neo4j:7687"
    # Khóa thứ tám, tìm ra ở vòng review: nó không phải field của
    # `HyperGraphRAG` nên trước story này không bao giờ tới được adapter.
    assert "cosine_better_than_threshold" in KHOA_CAU_HINH_KHO
    assert engine.hyperedges_vdb.cosine_better_than_threshold == 0.31


def test_ket_noi_khong_phai_field_cua_engine(workspace_dir):
    """Kết nối kho không được là field: `asdict(self)` `deepcopy` mọi field.

    `dataclasses.asdict` chạy 10 lần trên đường dựng và truy vấn, và nó
    `deepcopy` mọi field không phải dataclass. `deepcopy` một client có socket
    là nổ hoặc là một bản sao vô nghĩa. Khe tiêm vì thế là một *hàm*
    (`copy._deepcopy_atomic` trả về chính hàm đó), còn kết nối sống ngoài danh
    sách field.
    """
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    engine = dung_engine(workspace_dir, client, driver, LLMGia())
    cau_hinh = asdict(engine)
    assert not any(
        isinstance(v, (AsyncQdrantClient, AsyncDriver, QdrantGhiLai, Neo4jGhiLai))
        for v in cau_hinh.values()
    )
    # Hàm tiêm thì đi qua được `asdict` nguyên vẹn, đó là điểm của thiết kế.
    assert cau_hinh["tao_qdrant_client"] is engine.tao_qdrant_client
    assert engine.tao_qdrant_client() is client
    assert engine.tao_neo4j_driver() is driver


def test_thieu_khoa_bat_buoc_thi_adapter_tu_no_valueerror(workspace_dir):
    """Thiếu khóa kho mà không tiêm kết nối: lỗi của chính adapter, không phải của engine.

    Engine không dựng thêm một tầng kiểm cấu hình thứ hai. Adapter đã có thông
    điệp nói đúng khóa nào thiếu; nhân bản luật đó ở engine là hai bản dễ lệch.
    """
    with pytest.raises(ValueError) as loi_graph:
        dung_engine(workspace_dir, QdrantGhiLai(), None, LLMGia())
    assert "neo4j_uri" in str(loi_graph.value)

    with pytest.raises(ValueError) as loi_vector:
        dung_engine(workspace_dir, None, Neo4jGhiLai(), LLMGia())
    assert "qdrant_url" in str(loi_vector.value)


def test_bat_cache_llm_thi_khong_dung_duoc_engine(workspace_dir):
    """Cờ cache bật là nổ ngay lúc dựng, qua registry thật (AD-18).

    Story 1.5 chỉ chứng minh được điều này bằng cách vá tên
    `hypergraphrag.hypergraphrag.JsonKVStorage`. Ở đây không vá gì: registry
    của engine trả đúng adapter của dự án, và `__post_init__` của upstream
    dựng `llm_response_cache` bằng chính lớp đó.
    """
    assert ENABLE_LLM_CACHE is False
    assert EngineACL.__dataclass_fields__["enable_llm_cache"].default is False
    with pytest.raises(LLMCacheDisabled) as loi:
        dung_engine(
            workspace_dir,
            QdrantGhiLai(),
            Neo4jGhiLai(),
            LLMGia(),
            enable_llm_cache=True,
        )
    assert loi.value.code == "LLM_CACHE_DISABLED"




class _BatLog(logging.Handler):
    """Bắt mọi record mà logger `hypergraphrag` thật sự phát ra."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.dong: list[str] = []

    def emit(self, record):
        self.dong.append(record.getMessage())


def _dung_engine_va_bat_log(workspace_dir, **them) -> list[str]:
    """Dựng một engine rồi trả mọi dòng log nó phát ra lúc dựng.

    Bắt qua handler chứ không đọc file: `set_logger` mở `FileHandler` theo CWD
    và chỉ gắn một lần cho cả tiến trình (`utils.py:46` kiểm
    `if not logger.handlers`), nên file trên đĩa không nói được gì về *lần dựng
    này*. Handler thì nói.
    """
    logger = logging.getLogger("hypergraphrag")
    goc = logging.getLogger()
    bat = _BatLog()
    muc_cu, muc_goc_cu = logger.level, goc.level
    logger.addHandler(bat)
    # Dựng đúng tình huống nguy hiểm, không phải tình huống thuận lợi: một
    # `logging.basicConfig(level=DEBUG)` ở `api/` đặt mức DEBUG lên logger gốc.
    # Mặc định của upstream (`log_level` = NOTSET) *kế thừa* mức đó, nên chỉ khi
    # root ở DEBUG thì hai cách khai mức mới phân biệt được - và đó chính là
    # đường mà secret ra đĩa.
    goc.setLevel(logging.DEBUG)
    try:
        dung_engine(
            workspace_dir,
            QdrantGhiLai(),
            Neo4jGhiLai(),
            LLMGia(),
            qdrant_api_key=API_KEY_NHAN_BIET,
            neo4j_uri="bolt://neo4j:7687",
            neo4j_password=MAT_KHAU_NHAN_BIET,
            **them,
        )
    finally:
        logger.removeHandler(bat)
        logger.setLevel(muc_cu)
        goc.setLevel(muc_goc_cu)
    return bat.dong


def test_secret_khong_ra_log_o_muc_mac_dinh(workspace_dir):
    """`neo4j_password` và `qdrant_api_key` không được nằm trong log.

    `hypergraphrag.py:178-179` dựng `_print_config` từ `asdict(self)` - tức là
    gồm cả hai secret - rồi `logger.debug(...)`, trong khi `set_logger` đã gắn
    một FileHandler mức DEBUG vào `hypergraphrag.log`. Mặc định của upstream
    (`log_level` = `logger.level` lúc import = NOTSET) làm dòng đó im, nhưng
    "im vì chưa ai bật" không phải một cơ chế. `EngineACL` ghim mức log tường
    minh, và test này là chỗ ghim đó có người canh - Policy của AGENTS.md nói
    không bao giờ commit credentials, và một secret trong file log là đúng thứ
    đó.
    """
    dong = _dung_engine_va_bat_log(workspace_dir)
    ro = [d for d in dong if MAT_KHAU_NHAN_BIET in d or API_KEY_NHAN_BIET in d]
    assert not ro, f"secret nằm trong log: {ro}"
    assert logging.getLogger("hypergraphrag").getEffectiveLevel() > logging.DEBUG


def test_doi_chung_bat_debug_thi_secret_ra_that(workspace_dir):
    """Đối chứng: cùng đường đó với `log_level="DEBUG"` thì secret ra thật.

    Không có ca này thì test trên xanh cả khi upstream bỏ hẳn dòng
    `logger.debug(_print_config)`, và bộ test sẽ canh một đường rò không còn
    tồn tại. Đây cũng là hình dạng chính xác của khoản nợ còn treo: che secret
    ngay cả khi ai đó cố ý bật DEBUG cần một chỗ khác giữ giá trị thô, địa chỉ
    story 3.1.
    """
    dong = _dung_engine_va_bat_log(workspace_dir, log_level="DEBUG")
    assert any(MAT_KHAU_NHAN_BIET in d for d in dong)
    assert any(API_KEY_NHAN_BIET in d for d in dong)


def test_khoi_tao_dung_ba_collection_va_index_graph(workspace_dir, khong_gian, policy):
    """Bước khởi động tạo đủ ba collection vector và index graph, lặp lại được."""

    async def chay():
        client = QdrantGhiLai()
        driver = Neo4jGhiLai()
        engine = dung_engine(workspace_dir, client, driver, LLMGia())
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            await engine.khoi_tao()
            # Gọi lại không hỏng: cả hai adapter đều dựng bước khởi tạo lặp
            # lại được, và bước khởi động của tiến trình sẽ chạy mỗi lần lên.
            await engine.khoi_tao()
            co_mat = [
                await client.collection_exists(collection_name=f"{khong_gian}_{ns}")
                for ns in ("entities", "hyperedges", "chunks")
            ]
        cau_index = [
            lg for lg in driver.loi_goi if lg.cypher.startswith("CREATE INDEX")
        ]
        return co_mat, cau_index

    co_mat, cau_index = asyncio.run(chay())
    assert co_mat == [True, True, True]
    assert cau_index, "chưa có câu tạo index nào cho graph"
    assert f"node_id_{khong_gian}" in cau_index[0].cypher


def test_khoi_tao_thieu_ngu_canh_la_fail_closed(workspace_dir):
    """Không ngữ cảnh thì không biết `space` nào, nên không tạo kho nào."""

    async def chay():
        engine = dung_engine(
            workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), LLMGia()
        )
        with pytest.raises(PermissionContextMissing) as loi:
            await engine.khoi_tao()
        return loi.value.code

    assert asyncio.run(chay()) == "PERMISSION_CONTEXT_MISSING"


def test_dong_flush_kv_va_khong_dong_ket_noi_duoc_tiem(
    workspace_dir, khong_gian, policy
):
    """Tắt engine: KV xuống đĩa, kết nối tiêm từ ngoài **không** bị đóng.

    Luật sở hữu: kết nối tiêm từ ngoài thuộc về người tiêm. Engine đóng hộ là
    làm hỏng kết nối của người khác, và ở bộ test thì đó là làm hỏng luôn phần
    đo của chính test.
    """

    async def chay():
        engine, client, driver, _ = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        await engine.dong()
        # Gọi hai lần không hỏng: đường tắt tiến trình có thể chạy hai lần.
        await engine.dong()
        return client, driver

    client, driver = asyncio.run(chay())
    assert driver.da_dong is False
    assert client.cac_loi_goi("close") == []
    ten_file = {p.name for p in Path(workspace_dir).iterdir()}
    assert f"kv_store_{khong_gian}_text_chunks.json" in ten_file
    assert f"kv_store_{khong_gian}_full_docs.json" in ten_file


def test_dong_dong_dung_ket_noi_do_engine_tu_mo(
    workspace_dir, khong_gian, policy, monkeypatch
):
    """Engine tự mở từ cấu hình thì chính engine đóng, đối chứng của test trên."""
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    monkeypatch.setattr(
        QdrantVectorDBStorage, "_dung_client", staticmethod(lambda cau_hinh: client)
    )
    monkeypatch.setattr(
        Neo4jACLGraphStorage, "_dung_driver", staticmethod(lambda cau_hinh: driver)
    )

    async def chay():
        engine = dung_engine(
            workspace_dir,
            None,
            None,
            LLMGia(),
            qdrant_url="http://qdrant:6333",
            neo4j_uri="bolt://neo4j:7687",
            neo4j_password="mat-khau",
        )
        await engine.dong()
        await engine.dong()

    asyncio.run(chay())
    assert driver.da_dong is True
    assert len(client.cac_loi_goi("close")) == 1


def test_dong_hong_giua_chung_van_goi_lai_duoc(
    workspace_dir, khong_gian, policy, monkeypatch
):
    """`dong()` nổ lúc ghi đĩa thì lần gọi sau vẫn chạy tiếp, không trả về ngay.

    Cờ "đã đóng" đặt trước bước flush là: một exception lúc ghi làm mọi lời gọi
    sau đó im lặng trả về, kết nối do engine mở nằm lại không ai đóng, và phần
    chưa flush mất luôn - đúng thứ method này sinh ra để tránh.
    """
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    monkeypatch.setattr(
        QdrantVectorDBStorage, "_dung_client", staticmethod(lambda cau_hinh: client)
    )
    monkeypatch.setattr(
        Neo4jACLGraphStorage, "_dung_driver", staticmethod(lambda cau_hinh: driver)
    )

    async def chay():
        engine = dung_engine(
            workspace_dir,
            None,
            None,
            LLMGia(),
            qdrant_url="http://qdrant:6333",
            neo4j_uri="bolt://neo4j:7687",
            neo4j_password="mat-khau",
        )

        async def no():
            raise OSError("đĩa đầy")

        that = engine.text_chunks.index_done_callback
        engine.text_chunks.index_done_callback = no
        with pytest.raises(OSError):
            await engine.dong()
        giua_chung = (driver.da_dong, len(client.cac_loi_goi("close")))
        engine.text_chunks.index_done_callback = that
        await engine.dong()
        return giua_chung

    giua_chung = asyncio.run(chay())
    assert giua_chung == (False, 0), "đóng kết nối trước khi flush xong"
    assert driver.da_dong is True
    assert len(client.cac_loi_goi("close")) == 1


def test_khe_tiem_tra_none_bi_tu_choi(workspace_dir):
    """Thông điệp phải nói về khe tiêm, không nói về khóa cấu hình thiếu."""
    with pytest.raises(ValueError) as loi:
        EngineACL(
            working_dir=str(workspace_dir),
            embedding_func=embedding_gia(),
            llm_model_func=LLMGia(),
            tao_qdrant_client=lambda: None,
            tao_neo4j_driver=lambda: Neo4jGhiLai(),
        )
    assert "tao_qdrant_client" in str(loi.value)
    assert "qdrant_url" not in str(loi.value)


def test_hashing_kv_xuong_ham_llm_la_none_tren_duong_truy_van(
    workspace_dir, khong_gian, policy
):
    """AD-18 trên chính đường truy vấn, không chỉ trên thuộc tính của engine.

    `HyperGraphRAG.__post_init__` bind `hashing_kv=self.llm_response_cache`
    bằng `partial` (`hypergraphrag.py:242-248`), và `handle_cache`/`save_to_cache`
    đọc đúng giá trị đó. Ghim ở đầu ra của lời gọi LLM là ghim chỗ cơ chế thật
    sự đọc, chứ không phải chỗ nó được khai.
    """

    async def chay():
        engine, _, _, llm = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian)
        await hoi(engine, ngu_canh_cua(dt, policy))
        return llm.kwargs

    kwargs = asyncio.run(chay())
    assert kwargs, "không có lời gọi LLM nào để kiểm"
    for lan in kwargs:
        assert "hashing_kv" in lan, "upstream đã bỏ tham số cache, xem lại AD-18"
        assert lan["hashing_kv"] is None


def test_moi_loi_goi_truy_van_dung_query_param_moi(workspace_dir, monkeypatch):
    """`aquery` không bao giờ dùng lại một `QueryParam`.

    Chữ ký upstream là `param: QueryParam = QueryParam()` - một instance dựng
    lúc import, dùng chung cho mọi lời gọi - và `_build_query_context` **ghi**
    `query_param.mode` lên chính nó (`operate.py:658,681,700`). Hai truy vấn
    song song không truyền param tường minh là hai truy vấn chia nhau một mảnh
    trạng thái.
    """
    da_nhan = []

    async def kg_query_gia(*args, **kwargs):
        # Bắt theo *kiểu*, không theo vị trí: `args[5]` gắn chặt vào thứ tự
        # tham số của `kg_query`, nên upstream đảo tham số thì test đọc nhầm
        # đối tượng hoặc `IndexError` thay vì đỏ ở chỗ nói đúng nguyên nhân.
        param = [
            g for g in list(args) + list(kwargs.values())
            if isinstance(g, QueryParam)
        ]
        assert len(param) == 1, f"không tìm thấy đúng một QueryParam: {param!r}"
        da_nhan.append(param[0])
        return "ngữ cảnh giả"

    monkeypatch.setattr(
        "hypergraphrag.hypergraphrag.kg_query", kg_query_gia, raising=True
    )

    async def chay():
        engine = dung_engine(
            workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), LLMGia()
        )
        await engine.aquery(CAU_HOI)
        await engine.aquery(CAU_HOI)
        dung_chung = HyperGraphRAG.aquery.__defaults__[0]
        await engine.aquery(CAU_HOI, dung_chung)
        return dung_chung

    dung_chung = asyncio.run(chay())
    assert len(da_nhan) == 3
    assert len({id(p) for p in da_nhan}) == 3, "hai lời gọi dùng chung một param"
    assert all(p is not dung_chung for p in da_nhan), (
        "một lời gọi dùng thẳng instance mặc định dùng chung của upstream"
    )


# --- 1.7-INT-001: contextvar qua pipeline async tới cả ba adapter -----------


def test_contextvar_toi_ca_ba_adapter_mang_dung_tap_khoa(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-001`: một truy vấn e2e, ba adapter, ba lần đúng tập khóa của vai.

    Test hai chiều, không chỉ "có filter": tập khóa trong request phải **bằng**
    tập oracle tính độc lập, và hai vai phải cho hai tập khác nhau.
    """

    async def chay():
        engine, client, driver, llm = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        thu = {}
        for dt in danh_tinh_demo:
            client.xoa_nhat_ky()
            driver.xoa_nhat_ky()
            llm.xoa_nhat_ky()
            ngu_canh = await hoi(engine, ngu_canh_cua(dt, policy))
            thu[dt.vai] = (
                ngu_canh,
                khoa_theo_collection(client),
                [dict(lg.params) for lg in driver.cac_cau_doc()],
                [lg.cypher for lg in driver.cac_cau_doc()],
                llm.so_lan,
                list(llm.prompts_sinh_cau_tra_loi),
            )
        return thu

    thu = asyncio.run(chay())
    for vai, (ngu_canh, khoa_qdrant, tham_so, cypher, so_lan_llm, sinh) in thu.items():
        ky_vong = oracle.allowed_keys_ky_vong(bang, vai)

        # Đường vector: bộ lọc đi *cùng* request, một lần cho mỗi collection.
        assert khoa_qdrant[f"{khong_gian}_hyperedges"] == ky_vong["hyperedges"]
        assert khoa_qdrant[f"{khong_gian}_entities"] == ky_vong["entities"]

        # Đường graph: WHERE nằm trong chính câu Cypher, mọi biến đều bị ràng.
        assert cypher, f"vai {vai} không phát câu đọc graph nào"
        for cau in cypher:
            canh_moi_bien_deu_bi_loc(cau)
        for p in tham_so:
            assert set(p["keys"]) == ky_vong["hyperedges"]
            assert p["space"] == khong_gian

        # Đường KV: không chunk nào ngoài ngưỡng L2 của vai lọt vào ngữ cảnh.
        thay = chunk_trong(ngu_canh)
        assert thay, f"vai {vai} không truy hồi được chunk nào"
        assert thay <= set(oracle.chunk_thay_duoc(bang, vai, CHUNKS))

        # Đúng một lời gọi LLM (trích từ khóa), không lời gọi sinh câu trả lời:
        # bộ này assert trên ngữ cảnh truy hồi, không trên câu trả lời.
        assert so_lan_llm == 1
        assert sinh == []

    # Chiều thứ hai: hai vai không thể cho cùng một tập khóa.
    assert (
        thu["tech_support"][1][f"{khong_gian}_hyperedges"]
        < thu["devops"][1][f"{khong_gian}_hyperedges"]
    )


def test_devops_thay_hyperedge_l1_nhung_khong_thay_chunk_cua_no(
    workspace_dir, khong_gian, policy, bang
):
    """Ngưỡng theo namespace: L1 cho hyperedge, L2 cho chunk (NFR-06).

    `devops` ở mức L1 với `bi_mat_ha_tang` nên thấy hyperedge HE-03, nhưng
    nguyên văn chunk cắt ra từ tài liệu đó thì không. Đây là lỗ mà adapter KV
    của story 1.5 bịt, kiểm lần đầu trên đường e2e thật.
    """

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(tai_khoan="dev01", vai="devops", khong_gian=khong_gian)
        return await hoi(engine, ngu_canh_cua(dt, policy))

    ngu_canh = asyncio.run(chay())
    he3 = THEO_ID["HE-03"]
    assert oracle.muc_ky_vong(bang, "devops", he3["content_type"]) == "L1"
    assert ten_hyperedge(he3) in ngu_canh
    assert "chunk-HE-03" not in chunk_trong(ngu_canh)


# --- 1.7-INT-002: hai truy vấn song song không lẫn ngữ cảnh ----------------


def test_hai_truy_van_song_song_khong_lan_ngu_canh(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-002`: hai vai cùng lúc trong pipeline, mỗi kết quả đúng vai nó."""

    async def chay():
        engine, client, _, _ = await cong_m1(workspace_dir, khong_gian, policy)

        async def mot_vai(dt):
            return dt.vai, await hoi(engine, ngu_canh_cua(dt, policy))

        ket_qua = await asyncio.gather(*[mot_vai(dt) for dt in danh_tinh_demo])
        khoa = [
            khoa_trong_filter(lg.kwargs["query_filter"])
            for lg in client.cac_loi_goi("query_points")
            if lg.kwargs["collection_name"] == f"{khong_gian}_hyperedges"
        ]
        return dict(ket_qua), khoa

    theo_vai, khoa = asyncio.run(chay())
    for vai, ngu_canh in theo_vai.items():
        assert ten_hyperedge_trong(ngu_canh) == ten_hyperedge_ky_vong(bang, vai)
    assert theo_vai["tech_support"] != theo_vai["devops"]
    # Không có request nào mang một tập khóa lạ: mỗi request thuộc về đúng một
    # trong hai vai, kể cả khi hai truy vấn đang chồng lên nhau trên cùng loop.
    ky_vong = {
        frozenset(oracle.allowed_keys_ky_vong(bang, vai)["hyperedges"])
        for vai in theo_vai
    }
    assert {frozenset(k) for k in khoa} == ky_vong


def test_vendor_khong_chay_gi_ngoai_event_loop():
    """Bằng chứng cho quyết định không dựng engine per-request.

    AC đòi "có đường lùi engine per-request nếu contextvar đứt qua executor".
    Fan-out của upstream chỉ là `gather`/`as_completed` trên cùng một event
    loop, nơi contextvar được kế thừa, nên đường lùi đó không cần dựng. Đây là
    bằng chứng chứ không phải lời hứa: thêm một `to_thread` vào `vendor/` là
    test này đỏ, và lúc đó quyết định phải xét lại.
    """
    cac_file = sorted((REPO_ROOT / "vendor").rglob("*.py"))
    # `rglob` ra rỗng thì vòng lặp dưới cũng rỗng và test xanh mà chưa quét gì -
    # một bằng chứng rỗng còn tệ hơn không có bằng chứng, vì nó vẫn được viện
    # dẫn trong quyết định.
    assert len(cac_file) > 5, f"quét vendor/ chỉ ra {len(cac_file)} file .py"
    vi_pham = [
        f"{py.relative_to(REPO_ROOT)}: {dau_hieu}"
        for py in cac_file
        for dau_hieu in DAU_HIEU_THREAD
        if dau_hieu in py.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not vi_pham, "vendor/ chạy code ngoài event loop:\n" + "\n".join(vi_pham)
    # Bộ dò phải bắt được thứ nó nói là bắt được, nếu không nó chỉ là một vòng
    # lặp luôn ra rỗng.
    assert any(
        d in "async def x():\n    await asyncio.to_thread(f)\n" for d in DAU_HIEU_THREAD
    )


# --- 1.7-INT-003: hai danh tính seed, hai ngữ cảnh truy hồi ----------------


def test_hai_danh_tinh_hai_ngu_canh_truy_hoi(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-003`: đúng tiêu chí M1 "hai tài khoản, hai kết quả"."""
    assert {dt.vai for dt in danh_tinh_demo} == {"tech_support", "devops"}

    async def chay():
        engine, client, driver, _ = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        thu = {}
        for dt in danh_tinh_demo:
            client.xoa_nhat_ky()
            driver.xoa_nhat_ky()
            ngu_canh = await hoi(engine, ngu_canh_cua(dt, policy))
            thu[dt.vai] = (
                ngu_canh,
                len(client.cac_loi_goi("query_points")),
                len(driver.cac_cau_doc()),
            )
        return thu

    thu = asyncio.run(chay())
    ngu_canh_ts, so_request_ts, so_cau_ts = thu["tech_support"]
    ngu_canh_dev, _, _ = thu["devops"]
    assert ngu_canh_ts != ngu_canh_dev
    assert ten_hyperedge_trong(ngu_canh_ts) == ten_hyperedge_ky_vong(
        bang, "tech_support"
    )
    assert ten_hyperedge_trong(ngu_canh_dev) == ten_hyperedge_ky_vong(bang, "devops")
    assert ten_hyperedge_trong(ngu_canh_ts) < ten_hyperedge_trong(ngu_canh_dev)
    # Cả hai đường đều thật sự chạy, không phải một đường câm rồi kết luận.
    assert so_request_ts >= 2 and so_cau_ts >= 1


def test_ngu_canh_quyen_phat_tu_danh_tinh_seed(policy, khong_gian):
    """Danh tính seed là nguồn duy nhất của vai; test không tự chế ngữ cảnh."""
    dt = DanhTinh(tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian)
    ngu_canh = ngu_canh_cua(dt, policy)
    assert ngu_canh.role == "tech_support"
    assert ngu_canh.real_account == "ts01"
    assert ngu_canh.space == khong_gian
    assert ngu_canh.bypass_filter is False
    assert ngu_canh.policy_version == policy.policy_version


# --- 1.7-INT-004: Đo 1 lớp (a) - không hyperedge L0 ------------------------


def test_do1_lop_a_khong_hyperedge_l0(workspace_dir, khong_gian, policy, bang):
    """`1.7-INT-004`: vai không thấy hyperedge ở L0, kể cả một mẩu nội dung.

    Assert fixture *có* một mục L0 trước đã: một test "vắng mặt" trên một
    fixture không có gì để vắng mặt là một test luôn xanh.
    """

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(
            tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian
        )
        return await hoi(engine, ngu_canh_cua(dt, policy))

    ngu_canh = asyncio.run(chay())
    he3 = THEO_ID["HE-03"]
    assert oracle.muc_ky_vong(bang, "tech_support", he3["content_type"]) == "L0"
    assert "HE-03" not in oracle.hyperedge_thay_duoc(bang, "tech_support", HYPEREDGES)
    assert ten_hyperedge(he3) not in ngu_canh
    for slot, gia_tri in he3["slots"].items():
        assert gia_tri not in ngu_canh, f"nội dung slot {slot} của HE-03 lọt ra"
    # Chunk của tài liệu L0 cũng phải vắng mặt, không chỉ hyperedge.
    assert "chunk-HE-03" not in chunk_trong(ngu_canh)


# --- 1.7-INT-005: Đo 1 lớp (b) - không nội dung slot đã che ----------------


def test_do1_lop_b_khong_noi_dung_slot_da_che(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-005`: nguyên văn slot bị che không xuất hiện ở *bất kỳ đâu*.

    Kỳ vọng lấy từ `oracle.slot_phai_che`, tính từ bảng YAML và nhãn fixture.
    Phạm vi là các hyperedge mà vai thấy ở **mức L1** - đúng phạm vi mà che là
    cơ chế quyền (L0 thì hyperedge vắng mặt hẳn, đó là lớp (a)).

    Ở L2 còn đúng một slot phải tổng quát hóa (`owner`), và ở đó tên người phụ
    trách vẫn ra nguyên văn qua kho vector `entities` và qua nguyên văn chunk -
    hai đường mà tầng che của Epic 1 không chạm tới. Khoản đó nằm trong ledger
    với địa chỉ story, không giấu bằng cách thu hẹp assert một cách im lặng.
    """

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        return {
            dt.vai: await hoi(engine, ngu_canh_cua(dt, policy))
            for dt in danh_tinh_demo
        }

    theo_vai = asyncio.run(chay())
    da_kiem = 0
    for vai, ngu_canh in theo_vai.items():
        for he in HYPEREDGES:
            if oracle.muc_ky_vong(bang, vai, he["content_type"]) != "L1":
                continue
            if he["id"] not in oracle.hyperedge_thay_duoc(bang, vai, HYPEREDGES):
                continue
            phai_che = oracle.slot_phai_che(bang, vai, he)
            assert phai_che, f"{vai}/{he['id']} ở L1 mà oracle không đòi che gì"
            for slot in phai_che:
                gia_tri = he["slots"][slot]
                assert gia_tri not in ngu_canh, (
                    f"nguyên văn slot {slot!r} của {he['id']} lọt vào ngữ cảnh"
                    f" của vai {vai}"
                )
                assert oracle.dau_che_ky_vong(slot) in ngu_canh, (
                    f"dấu che của slot {slot!r} không có mặt: fact biến mất"
                    " khỏi ngữ cảnh thay vì bị che (FR-12)"
                )
                da_kiem += 1
    assert da_kiem, "không ca L1 nào được kiểm, bộ test đang rỗng"


def test_do1_lop_b_phu_dung_hang_io_matrix(workspace_dir, khong_gian, policy):
    """Hàng I/O Matrix, viết thẳng: `tech_support` với `bao_cao_su_co` ở L1."""

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(
            tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian
        )
        return await hoi(engine, ngu_canh_cua(dt, policy))

    ngu_canh = asyncio.run(chay())
    he2 = THEO_ID["HE-02"]
    for slot in ("cause", "source", "remediation"):
        assert he2["slots"][slot] not in ngu_canh
    # Fact vẫn có mặt: che là thay giá trị, không phải xóa fact (FR-12).
    assert ten_hyperedge(he2) in ngu_canh
    assert he2["slots"]["symptom"] in ngu_canh


def test_tripwire_ten_hyperedge_chua_mang_nguyen_van_slot_bi_che(bang):
    """Tripwire cho lỗ L1 `hyperedge_name` (khoản nợ có địa chỉ story 2.4).

    `hyperedge_name` vừa là payload vector vừa là id node hyperedge, và nó đi
    thẳng vào cột `hyperedge` của bảng Relationships gửi LLM
    (`operate.py:952,987`). Tầng che không chạm được nó: đó là văn bản tự do,
    không tách theo slot.

    Hôm nay ca đó vô hại vì fixture đặt tên an toàn (`subject - content_type`).
    Story 2.4 cho nguyên văn câu fact vào chỗ này thì test này đỏ, và đó đúng
    là lúc phải quyết. Tripwire ở đây chứ không chỉ một dòng trong ledger vì
    một dòng ledger không đỏ.
    """
    for vai in ("tech_support", "devops"):
        for he in HYPEREDGES:
            for slot in oracle.slot_phai_che(bang, vai, he):
                assert he["slots"][slot] not in ten_hyperedge(he), (
                    f"tên hyperedge của {he['id']} mang nguyên văn slot"
                    f" {slot!r}, thứ vai {vai} không được thấy"
                )


# --- 1.7-INT-006: Đo 1 lớp (c) - đổi vai, ngữ cảnh thu hẹp ngay ------------


def test_do1_lop_c_doi_vai_thu_hep_ngay_truy_van_ke_tiep(
    workspace_dir, khong_gian, policy, bang
):
    """`1.7-INT-006`: cùng engine, vai hẹp hỏi sau vai rộng, không dựng lại index."""

    async def chay():
        engine, client, driver, _ = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        dev = DanhTinh(tai_khoan="dev01", vai="devops", khong_gian=khong_gian)
        ts = DanhTinh(
            tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian
        )
        rong = await hoi(engine, ngu_canh_cua(dev, policy))
        hep = await hoi(engine, ngu_canh_cua(ts, policy))
        dung_lai_kho = (
            client.cac_loi_goi("create_collection")
            + client.cac_loi_goi("create_payload_index")
            + [lg for lg in driver.loi_goi if lg.cypher.startswith("CREATE INDEX")]
        )
        return rong, hep, dung_lai_kho

    rong, hep, dung_lai_kho = asyncio.run(chay())
    assert ten_hyperedge_trong(hep) < ten_hyperedge_trong(rong)
    assert ten_hyperedge_trong(hep) == ten_hyperedge_ky_vong(bang, "tech_support")
    assert chunk_trong(hep) < chunk_trong(rong)
    assert dung_lai_kho == [], "đổi vai mà phải dựng lại index (NFR-09)"


# --- 1.7-INT-007: Đo 1 lớp (e) - fail-closed toàn tuyến --------------------


def test_do1_lop_e_thieu_ngu_canh_la_fail_closed(workspace_dir, khong_gian, policy):
    """`1.7-INT-007`: `aquery` không bọc `use_context` thì không trả ngữ cảnh nào."""

    async def chay():
        engine, client, driver, _ = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        with pytest.raises(PermissionContextMissing) as loi:
            await engine.aquery(CAU_HOI, QueryParam(only_need_context=True))
        return loi.value.code, client.cac_loi_goi("query_points"), driver.cac_cau_doc()

    ma, request, cau_doc = asyncio.run(chay())
    assert ma == "PERMISSION_CONTEXT_MISSING"
    assert request == [], "có search request đi ra khi chưa có ngữ cảnh quyền"
    assert cau_doc == [], "có câu đọc graph đi ra khi chưa có ngữ cảnh quyền"


# --- Danh tính seed --------------------------------------------------------


def test_seed_danh_tinh_doc_duoc_hai_vai():
    """Seed tối giản: hai danh tính demo, chưa JWT (FR-17 thuộc Epic 3)."""
    danh_tinh = nap_danh_tinh()
    assert len(danh_tinh) == 2
    assert all(isinstance(dt, DanhTinh) for dt in danh_tinh)
    assert {dt.vai for dt in danh_tinh} == {"tech_support", "devops"}
    assert len({dt.tai_khoan for dt in danh_tinh}) == 2
    assert DUONG_DAN_DANH_TINH_DEMO.exists()


# Mỗi dòng là một cách file seed hỏng, và mỗi cách đều có một luật từ chối
# riêng trong loader. Không parametrize thì phần lớn các luật đó không có test
# nào chạy vào - xóa khối chống trùng tài khoản mà không gì đỏ là dấu hiệu đúng
# của chuyện đó.
SEED_HONG = {
    "danh_sach_rong": "version: 1\ndanh_tinh: []\n",
    "thieu_khoi": "version: 1\n",
    "goc_khong_phai_mapping": "- version: 1\n",
    "goc_rong": "",
    "version_sai": "version: 2\ndanh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n",
    "version_thieu": "danh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n",
    "version_la_bool": "version: true\ndanh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n",
    "thieu_vai": "version: 1\ndanh_tinh:\n  - {tai_khoan: x, khong_gian: synth}\n",
    "muc_khong_phai_mapping": "version: 1\ndanh_tinh:\n  - ts01\n",
    "truong_la_trong_muc": (
        "version: 1\ndanh_tinh:\n"
        "  - {tai_khoan: x, vai: y, khong_gian: synth, allowed_keys: [a]}\n"
    ),
    # Khóa lạ ở *cấp gốc*: đây đúng là ca mà docstring module lấy làm lý do tồn
    # tại - một khối `allowed_keys:` cấp gốc nạp bình thường thì người viết seed
    # tin rằng mình vừa cấp quyền, mà không ai đọc nó.
    "khoa_la_o_goc": (
        "version: 1\nallowed_keys: [noi_bo:runbook]\n"
        "danh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n"
    ),
    "tai_khoan_trung": (
        "version: 1\ndanh_tinh:\n"
        "  - {tai_khoan: ts01, vai: tech_support, khong_gian: synth}\n"
        "  - {tai_khoan: ts01, vai: devops, khong_gian: synth}\n"
    ),
    "tai_khoan_rong": "version: 1\ndanh_tinh:\n  - {tai_khoan: '', vai: y, khong_gian: synth}\n",
    "vai_co_khoang_trang": (
        "version: 1\ndanh_tinh:\n  - {tai_khoan: x, vai: ' devops ', khong_gian: synth}\n"
    ),
    "khong_gian_sai_ky_tu": (
        "version: 1\ndanh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: '1-synth'}\n"
    ),
    "yaml_hong": "version: 1\ndanh_tinh: [\n",
}


@pytest.mark.parametrize("ten", sorted(SEED_HONG))
def test_seed_danh_tinh_hong_thi_tu_choi_nap(tmp_path, ten):
    """File seed hỏng là từ chối nạp, không phải chạy với danh sách rỗng.

    Assert trên `code` chứ không trên thông điệp: mã lỗi là hợp đồng (AD-8),
    câu chữ thì không.
    """
    xau = tmp_path / f"{ten}.yaml"
    xau.write_text(SEED_HONG[ten], encoding="utf-8")
    with pytest.raises(IdentitySeedInvalid) as loi:
        nap_danh_tinh(xau)
    assert loi.value.code == "IDENTITY_SEED_INVALID"


def test_seed_danh_tinh_thieu_file(tmp_path):
    """Đường dẫn không tồn tại cũng ra đúng một loại lỗi, kèm tên file."""
    with pytest.raises(IdentitySeedInvalid) as loi:
        nap_danh_tinh(tmp_path / "khong-co.yaml")
    assert loi.value.code == "IDENTITY_SEED_INVALID"
    assert "khong-co.yaml" in str(loi.value)


# --- `DanhTinh`: cửa kiểm của chính bản ghi danh tính ----------------------


@pytest.mark.parametrize(
    "truong", ["tai_khoan", "vai", "khong_gian"]
)
@pytest.mark.parametrize(
    "gia_tri,lop_loi",
    [("", ValueError), ("   ", ValueError), (" ts01 ", ValueError), (None, TypeError), (1, TypeError)],
    ids=["rong", "toan_khoang_trang", "khoang_trang_bao_quanh", "None", "so"],
)
def test_danh_tinh_tu_choi_gia_tri_hong(truong, gia_tri, lop_loi):
    """Ba trường, năm cách hỏng; không có cửa này thì xóa `__post_init__` mà không gì đỏ.

    `" ts01 "` bị từ chối chứ không bị cắt hộ: một danh tính lệch một dấu cách
    là một danh tính khác mà nhìn không ra, và cắt hộ nghĩa là seed nói một
    đằng còn hệ chạy một nẻo.
    """
    hop_le = {"tai_khoan": "ts01", "vai": "devops", "khong_gian": "synth"}
    hop_le[truong] = gia_tri
    with pytest.raises(lop_loi):
        DanhTinh(**hop_le)


def test_vai_khong_co_trong_bang_chinh_sach_la_loi_co_ma(policy, khong_gian):
    """Vai lạ là `RoleUnknown` có `code`, không phải `KeyError` trần.

    Cũng không phải một ngữ cảnh không thấy gì: ngữ cảnh rỗng chạy tiếp được và
    trông giống hệt "người này không được xem gì", nên nó giấu một seed sai cho
    tới lúc có người hỏi vì sao mình không thấy tài liệu nào.
    """
    dt = DanhTinh(tai_khoan="x01", vai="vai_khong_co_that", khong_gian=khong_gian)
    with pytest.raises(RoleUnknown) as loi:
        ngu_canh_cua(dt, policy)
    assert loi.value.code == "ROLE_UNKNOWN"
    assert "x01" in str(loi.value) and "vai_khong_co_that" in str(loi.value)


def test_ngu_canh_cua_tu_choi_kieu_khac(policy):
    """Chữ ký là `DanhTinh`, không phải một dict trông giống nó."""
    with pytest.raises(TypeError):
        ngu_canh_cua({"vai": "devops"}, policy)


def test_danh_tinh_la_bat_bien():
    """`DanhTinh` đóng băng: một danh tính đổi vai giữa chừng là leo quyền."""
    dt = DanhTinh(tai_khoan="ts01", vai="tech_support", khong_gian="synth")
    # Đúng lớp lỗi, không phải `Exception`: `pytest.raises(Exception)` xanh cả
    # khi test gõ nhầm tên thuộc tính và nhận `AttributeError`, tức là nó xanh
    # mà không chứng minh gì về việc đóng băng.
    with pytest.raises(FrozenInstanceError):
        dt.vai = "devops"


# --- Khóa cấu hình có nguồn: biến môi trường của compose -------------------


def test_bien_moi_truong_map_dung_khoa_cau_hinh(monkeypatch):
    """`QDRANT_URL`/`NEO4J_*` của compose tới được `global_config` của adapter."""
    moi_truong = {
        "QDRANT_URL": "http://qdrant:6333",
        "QDRANT_API_KEY": "",
        "NEO4J_URI": "bolt://neo4j:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "mat-khau",
        "HYPER_RAG_WORKING_DIR": "/data/hyper-rag",
    }
    cau_hinh = cau_hinh_kho_tu_moi_truong(moi_truong)
    assert cau_hinh["qdrant_url"] == "http://qdrant:6333"
    assert cau_hinh["neo4j_uri"] == "bolt://neo4j:7687"
    assert cau_hinh["neo4j_password"] == "mat-khau"
    assert cau_hinh["working_dir"] == "/data/hyper-rag"
    # Biến rỗng là chưa đặt, không phải đặt bằng chuỗi rỗng: một `api_key=""`
    # đi xuống client là một cấu hình sai im lặng.
    assert "qdrant_api_key" not in cau_hinh
    assert cau_hinh_kho_tu_moi_truong({}) == {}
    # Khoảng trắng bao quanh bị cắt, không đi thẳng xuống client: một
    # `QDRANT_URL=" http://qdrant:6333 "` lọt vào lúc sửa `.env` thì lỗi sẽ nói
    # về DNS chứ không nói về cấu hình.
    assert cau_hinh_kho_tu_moi_truong({"QDRANT_URL": "  http://q:6333\t"})[
        "qdrant_url"
    ] == "http://q:6333"


def test_bien_moi_truong_phu_het_khoa_cau_hinh_kho():
    """Khóa cấu hình kho không có biến môi trường phải là miễn trừ tường minh.

    Không có test này thì thêm một khóa vào `KHOA_CAU_HINH_KHO` mà quên nguồn
    của nó lại tái lập đúng khoản nợ mà story 1.7 đang khép.
    """
    thieu_nguon = set(KHOA_CAU_HINH_KHO) - set(BIEN_MOI_TRUONG)
    assert thieu_nguon == set(KHOA_KHONG_LAY_TU_MOI_TRUONG)
    # Chiều ngược lại: mọi biến khai trong bảng phải trỏ tới một field có thật.
    ten_field = {f.name for f in fields(EngineACL)}
    assert set(BIEN_MOI_TRUONG) <= ten_field


def _compose() -> dict:
    """`docker-compose.yml` đã parse.

    Parse chứ không tìm chuỗi: một dòng bị comment lại vẫn qua được phép tìm
    chuỗi, và khi đó test khẳng định một hợp đồng triển khai không còn tồn tại.
    """
    return yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )


def test_compose_khai_du_bien_moi_truong_engine_doc():
    """Mỗi biến mà engine đọc phải có nguồn trong `docker-compose.yml`."""
    api = _compose()["services"]["api"]
    thieu = [ten for ten in BIEN_MOI_TRUONG.values() if ten not in api["environment"]]
    assert not thieu, f"biến {thieu} chưa có nguồn trong docker-compose.yml"


def test_thu_muc_lam_viec_nam_tren_volume_co_khai():
    """`HYPER_RAG_WORKING_DIR` phải nằm dưới một mount có volume khai ở gốc.

    Kho KV JSON là nơi **duy nhất** giữ khóa quyền của chunk đã nạp. Không có
    mount thì nó nằm trong lớp ghi của container và mất sau mỗi `up --build` -
    một mất mát im lặng mà `docker compose config --quiet` không thấy, và phép
    tìm chuỗi trong compose cũng không thấy.
    """
    compose = _compose()
    api = compose["services"]["api"]
    thu_muc = api["environment"]["HYPER_RAG_WORKING_DIR"]
    mounts = {
        m.split(":")[1]: m.split(":")[0] for m in api.get("volumes", []) if ":" in m
    }
    phu = [
        (diem, ten) for diem, ten in mounts.items()
        if thu_muc == diem or thu_muc.startswith(diem.rstrip("/") + "/")
    ]
    assert phu, (
        f"{thu_muc!r} không nằm dưới mount nào của service api: {sorted(mounts)}"
    )
    for _, ten_volume in phu:
        assert ten_volume in compose.get("volumes", {}), (
            f"mount dùng volume {ten_volume!r} mà khối `volumes:` gốc không khai"
        )

# --- Guard của loader: bộ dò phải bắt được thứ nó nói là bắt được ----------

FIXTURE_HONG = {
    "thieu_subject": ({"id": "X", "scope": "noi_bo", "content_type": "runbook",
                       "source_id": "chunk-X", "slots": {"cause": "a"}},),
    "hai_slot_trung_gia_tri": ({"id": "X", "scope": "noi_bo",
                                "content_type": "runbook", "source_id": "chunk-X",
                                "slots": {"subject": "A", "cause": "A"}},),
    "vai_ngoai_danh_muc": ({"id": "X", "scope": "noi_bo", "content_type": "runbook",
                            "source_id": "chunk-X",
                            "slots": {"subject": "A", "khong_co_vai_nay": "B"}},),
    "trung_ten_hyperedge": (
        {"id": "X", "scope": "noi_bo", "content_type": "runbook",
         "source_id": "chunk-X", "slots": {"subject": "A"}},
        {"id": "Y", "scope": "khach_hang_a", "content_type": "runbook",
         "source_id": "chunk-Y", "slots": {"subject": "A"}},
    ),
}


@pytest.mark.parametrize("ten", sorted(FIXTURE_HONG))
def test_guard_loader_bat_duoc_fixture_hong(monkeypatch, ten):
    """Mỗi ca đều là một cách đường e2e "xanh mà không truy hồi được gì".

    Guard không đổi hành vi của hệ nên không đột biến nào của `core/` hay
    `adapters/` giết được nó; nếu nó cũng không có test riêng thì nó là code
    chết đứng canh một tiền đề mà không ai kiểm.
    """
    monkeypatch.setattr("tests.nap_kho.HYPEREDGES", FIXTURE_HONG[ten])
    with pytest.raises(AssertionError):
        kiem_fixture()


def test_guard_loader_im_voi_fixture_that():
    """Đối chứng: bộ fixture đang dùng phải qua được cả bốn luật."""
    kiem_fixture()
