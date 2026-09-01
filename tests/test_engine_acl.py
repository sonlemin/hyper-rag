"""`EngineACL`: registry adapter, khóa cấu hình và vòng đời kết nối (story 1.7).

Nửa thứ hai của bộ test story 1.7; cổng M1 và bộ Đo 1 nền nằm ở
`tests/test_cong_m1.py`. Tách ra khi file gốc vượt ngưỡng 1000 dòng.

Phần này ghim những thứ quyết định lúc *dựng* engine chứ không lúc truy vấn:
`_get_storage_class()` trả đúng ba adapter của dự án, tám khóa cấu hình kho đi
xuống `global_config` qua `asdict(self)`, kết nối không phải field (vì `asdict`
`deepcopy` mọi field), secret không ra log, `khoi_tao()` và `dong()` lặp lại
được, mỗi lời gọi truy vấn dùng một `QueryParam` mới, và mọi biến môi trường
engine đọc đều có nguồn trong `docker-compose.yml`.

Không mạng, không container, không key LLM.
"""

import asyncio
import logging
from dataclasses import asdict, fields
from pathlib import Path

import pytest
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
from adapters.kv import ENABLE_LLM_CACHE, JsonACLKVStorage, LLMCacheDisabled
from adapters.neo4j import Neo4jACLGraphStorage
from adapters.qdrant import QdrantVectorDBStorage
from core.permission import PermissionContextMissing, use_context
from core.system_context import system_context
from tests.gia_lap_llm import LLMGia
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia
from tests.ho_tro_compose import doc_compose
from tests.ho_tro_m1 import CAU_HOI, cong_m1, dung_engine
from tests.nap_kho import kiem_fixture

# Hai giá trị nhận biết được, chỉ dùng cho ca kiểm secret-không-ra-log. Không
# phải secret thật và không giống một secret thật: chuỗi trong bộ test là thứ
# người ta hay copy đi chỗ khác.
MAT_KHAU_NHAN_BIET = "mat-khau-khong-duoc-ra-log-a1b2c3"
API_KEY_NHAN_BIET = "api-key-khong-duoc-ra-log-d4e5f6"

# Đường dựng engine của `test_moi_loi_goi_truy_van_dung_query_param_moi` đi qua
# `kg_query` thật, thứ gọi `tiktoken`. Dùng bộ đếm token offline cho cả file.
pytestmark = pytest.mark.usefixtures("ma_hoa_offline")


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


def test_compose_khai_du_bien_moi_truong_engine_doc():
    """Mỗi biến mà engine đọc phải có nguồn trong `docker-compose.yml`."""
    api = doc_compose()["services"]["api"]
    thieu = [ten for ten in BIEN_MOI_TRUONG.values() if ten not in api["environment"]]
    assert not thieu, f"biến {thieu} chưa có nguồn trong docker-compose.yml"


def test_thu_muc_lam_viec_nam_tren_volume_co_khai():
    """`HYPER_RAG_WORKING_DIR` phải nằm dưới một mount có volume khai ở gốc.

    Kho KV JSON là nơi **duy nhất** giữ khóa quyền của chunk đã nạp. Không có
    mount thì nó nằm trong lớp ghi của container và mất sau mỗi `up --build` -
    một mất mát im lặng mà `docker compose config --quiet` không thấy, và phép
    tìm chuỗi trong compose cũng không thấy.
    """
    compose = doc_compose()
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
