"""Cùng bộ assert cốt lõi của story 1.3, chạy trên Qdrant thật (marker `qdrant`).

Local mode của qdrant-client lọc `match_any` đúng ngữ nghĩa nên đủ để kiểm
hành vi pre-filter, nhưng nó duyệt vét cạn và bỏ qua payload index: nó không
chứng minh được rằng lọc chạy *trong* HNSW có index, cũng không chứng minh
được `payload_schema`, `hnsw_config` và `strict_mode_config` có tác dụng. Đó
đúng là khoản nợ story 1.3 ghi lại cho cổng M1; file này trả nó bằng chính cơ
chế mà story 1.4 dựng cho Neo4j.

Mặc định bỏ qua (`addopts = -m 'not neo4j and not qdrant'`). Chạy thật::

    QDRANT_URL=http://<ip-container>:6333 uv run pytest -m qdrant

Trên máy chủ, Qdrant không publish cổng ra host nhưng IP container vẫn tới
được từ host; hook CI tự lấy IP đó và chạy file này sau bộ chính.

Mỗi lần chạy dùng một `space` riêng (tên collection mang `session_prefix`) và
xóa collection ở cuối, nên chạy nhiều lần trên cùng một server không giẫm nhau.
"""

import asyncio
import os
from contextlib import asynccontextmanager

import pytest
from qdrant_client import models

from adapters.ingest_labels import ingest_label
from adapters.qdrant import (
    FILTER_MAX_CONDITIONS,
    GLOBAL_M,
    PAYLOAD_M,
    QdrantIndexMissing,
    QdrantVectorDBStorage,
)
from core.keys import FILTER_KEY_FIELD
from core.permission import use_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.gia_lap_qdrant import (
    SO_CHIEU,
    QdrantGhiLai,
    embedding_gia,
    khoa_trong_filter,
)
from tests.ho_tro_qdrant import CAU_HOI, lo_upsert
from tests.ngu_canh import vai

pytestmark = pytest.mark.qdrant

URL = os.environ.get("QDRANT_URL")
API_KEY = os.environ.get("QDRANT_API_KEY")


@pytest.fixture()
def khong_gian(session_prefix):
    if not URL:
        if os.environ.get("QDRANT_REQUIRED"):
            pytest.fail("QDRANT_REQUIRED được đặt nhưng thiếu QDRANT_URL")
        pytest.skip("thiếu QDRANT_URL: bỏ qua test cần container")
    return f"{session_prefix}_that"


def dung_adapter(client, namespace="hyperedges"):
    return QdrantVectorDBStorage(
        namespace=namespace,
        global_config={"embedding_batch_num": 2},
        embedding_func=embedding_gia(),
        meta_fields={"hyperedge_name"},
        qdrant_client=client,
    )


@asynccontextmanager
async def kho_that(khong_gian: str, policy, nap: bool = True):
    """Client thật + adapter đã nạp 4 hyperedge fixture; xóa collection ở cuối."""
    client = QdrantGhiLai.noi_toi(URL, API_KEY)
    adapter = dung_adapter(client)
    ten = f"{khong_gian}_hyperedges"
    try:
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            if nap:
                await adapter.initialize()
                for he in HYPEREDGES:
                    with ingest_label(
                        scope=he["scope"], content_type=he["content_type"]
                    ):
                        await adapter.upsert(lo_upsert(he))
        client.xoa_nhat_ky()
        yield client, adapter, ten
    finally:
        try:
            await client.delete_collection(collection_name=ten)
        finally:
            await client._that.close()


def test_payload_index_va_hnsw_co_that(khong_gian, policy):
    """Ba tham số của `initialize()` chỉ Qdrant thật mới xác nhận được.

    Local mode nhận rồi bỏ qua cả ba, nên tới đây mới biết `QdrantIndexMissing`
    đang canh một cơ chế thật sự được bật: index keyword có `is_tenant`, cạnh
    HNSW theo khóa (`payload_m`), và hàng rào strict mode.

    Đối chiếu với chính hằng của adapter, không với số viết tay: đây là khoản
    kiểm mà docstring `initialize()` hẹn ở cổng M1, và nếu ai đó nới `PAYLOAD_M`
    hay `FILTER_MAX_CONDITIONS` thì test này phải nói rằng server *đã* nhận giá
    trị mới, chứ không âm thầm so với một con số cũ.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (client, _, ten):
            return await client.get_collection(collection_name=ten)

    tt = asyncio.run(chay())
    mo_ta = tt.payload_schema[FILTER_KEY_FIELD]
    assert mo_ta.data_type == models.PayloadSchemaType.KEYWORD
    assert mo_ta.params.is_tenant is True
    hnsw = tt.config.hnsw_config
    assert (hnsw.m, hnsw.payload_m) == (GLOBAL_M, PAYLOAD_M)
    strict = tt.config.strict_mode_config
    assert strict.enabled is True
    assert strict.filter_max_conditions == FILTER_MAX_CONDITIONS
    # Neo tuyệt đối cạnh phép so với hằng, vì hai phép đó bắt hai chuyện khác
    # nhau. So với hằng bắt "server không nhận giá trị mới"; neo dưới đây bắt
    # "ai đó nới chính cái hằng". `filter_max_conditions == 1` là phát biểu của
    # bất biến AD-4 - một field, không AND đa điều kiện - nên nới nó là đổi một
    # quyết định kiến trúc, và test phải đỏ để chỗ nới có người đọc lại.
    # `payload_m > 0` là điều kiện để cạnh HNSW theo khóa quyền tồn tại.
    assert strict.filter_max_conditions == 1
    assert hnsw.payload_m > 0 and hnsw.m > 0
    # Hai cờ này là nửa còn lại của hàng rào: lọc trên field chưa có index đi
    # vòng qua cả AD-4 lẫn `QdrantIndexMissing` bằng một lần duyệt vét cạn có
    # lọc, và server phải từ chối thay vì làm hộ.
    assert strict.unindexed_filtering_retrieve is False
    assert strict.unindexed_filtering_update is False


def test_upsert_tu_choi_khi_chua_initialize_tren_server_that(khong_gian, policy):
    """Ghi trước khi có index bị từ chối bởi chính cửa của adapter, không phải bởi may."""

    async def chay():
        async with kho_that(khong_gian, policy, nap=False) as (client, adapter, ten):
            with use_context(
                system_context(
                    space=khong_gian, policy_version=policy.policy_version
                )
            ):
                with ingest_label(scope="noi_bo", content_type="runbook"):
                    with pytest.raises(QdrantIndexMissing) as loi:
                        await adapter.upsert(lo_upsert(HYPEREDGES[0]))
            return loi.value.code, client.cac_loi_goi("upsert")

    ma, da_ghi = asyncio.run(chay())
    assert ma == "QDRANT_INDEX_MISSING"
    assert da_ghi == []


def test_hai_vai_hai_ket_qua_tren_qdrant_that(khong_gian, policy, bang):
    """Cổng M1 phía vector: pre-filter thật trong HNSW có index, hai vai hai kết quả."""

    async def chay():
        thu = {}
        async with kho_that(khong_gian, policy) as (client, adapter, _):
            for ten_vai in ("devops", "tech_support"):
                client.xoa_nhat_ky()
                with use_context(vai(policy, ten_vai, khong_gian)):
                    ket_qua = await adapter.query(CAU_HOI, top_k=10)
                goi = client.loi_goi_cuoi("query_points")
                thu[ten_vai] = (
                    sorted(r["id"].removeprefix("rel-") for r in ket_qua),
                    khoa_trong_filter(goi.kwargs["query_filter"]),
                )
        return thu

    thu = asyncio.run(chay())
    for ten_vai, (thay, khoa) in thu.items():
        # Bộ lọc đi *cùng* request, đúng tập khóa oracle tính độc lập.
        assert khoa == oracle.allowed_keys_ky_vong(bang, ten_vai)["hyperedges"]
        assert thay == sorted(oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES))
    assert set(thu["tech_support"][0]) < set(thu["devops"][0])


def test_filter_hai_dieu_kien_bi_server_tu_choi(khong_gian, policy):
    """Hàng rào phía server: `filter_max_conditions=1` chặn cả đường code chưa viết.

    Quy ước trong adapter cộng helper assert trong test chỉ chặn được đường code
    hiện tại. Đây là chỗ chứng minh hàng rào thật sự có hiệu lực, và nó là lý do
    story 5.3 phải quyết tường minh khi cần lọc theo cả khóa lẫn grant.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (client, _, ten):
            khoa = ["noi_bo:runbook", "noi_bo:bao_cao_su_co"]
            hai_dieu_kien = models.Filter(
                must=[
                    models.FieldCondition(
                        key=FILTER_KEY_FIELD, match=models.MatchAny(any=khoa)
                    ),
                    models.FieldCondition(
                        key=FILTER_KEY_FIELD,
                        match=models.MatchValue(value=khoa[0]),
                    ),
                ]
            )
            with pytest.raises(Exception) as loi:
                await client.query_points(
                    collection_name=ten,
                    query=[1.0] * SO_CHIEU,
                    query_filter=hai_dieu_kien,
                    limit=1,
                )
            return str(loi.value)

    thong_diep = asyncio.run(chay())
    assert "condition" in thong_diep.lower() or "strict mode" in thong_diep.lower()


def test_collection_that_khac_so_chieu_bi_tu_choi_luc_initialize(khong_gian, policy):
    """Trên Qdrant thật: collection dựng sẵn với size khác thì `initialize()` nổ, không sửa gì."""
    from adapters.qdrant import EmbeddingDimMismatch
    from qdrant_client import models

    async def chay():
        client = QdrantGhiLai.noi_toi(URL, API_KEY)
        ten = f"{khong_gian}_hyperedges"
        try:
            await client.create_collection(
                collection_name=ten,
                vectors_config=models.VectorParams(size=16, distance=models.Distance.COSINE),
            )
            with use_context(
                system_context(space=khong_gian, policy_version=policy.policy_version)
            ):
                with pytest.raises(EmbeddingDimMismatch) as loi:
                    await dung_adapter(client).initialize()
            size_sau = (await client.get_collection(collection_name=ten)).config.params.vectors.size
            return loi.value, size_sau
        finally:
            try:
                await client.delete_collection(collection_name=ten)
            finally:
                await client._that.close()

    loi, size_sau = asyncio.run(chay())
    assert loi.code == "EMBEDDING_DIM_MISMATCH"
    assert "16" in str(loi)
    assert size_sau == 16, "initialize() không được sửa collection đang có"
