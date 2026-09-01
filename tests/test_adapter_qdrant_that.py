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
from adapters.policy_loader import load_policy
from adapters.qdrant import QdrantIndexMissing, QdrantVectorDBStorage
from core.keys import FILTER_KEY_FIELD
from core.permission import use_context, user_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia, khoa_trong_filter
from tests.test_adapter_qdrant import CAU_HOI, lo_upsert

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


@pytest.fixture()
def policy():
    return load_policy(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def bang():
    return oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)


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
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (client, _, ten):
            return await client.get_collection(collection_name=ten)

    tt = asyncio.run(chay())
    mo_ta = tt.payload_schema[FILTER_KEY_FIELD]
    assert mo_ta.data_type == models.PayloadSchemaType.KEYWORD
    assert mo_ta.params.is_tenant is True
    hnsw = tt.config.hnsw_config
    assert (hnsw.m, hnsw.payload_m) == (16, 16)
    strict = tt.config.strict_mode_config
    assert strict.enabled is True and strict.filter_max_conditions == 1


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
                with use_context(
                    user_context(
                        policy=policy,
                        role=ten_vai,
                        space=khong_gian,
                        real_account=f"{ten_vai}01",
                    )
                ):
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
                    query=[1.0] * 8,
                    query_filter=hai_dieu_kien,
                    limit=1,
                )
            return str(loi.value)

    thong_diep = asyncio.run(chay())
    assert "condition" in thong_diep.lower() or "strict mode" in thong_diep.lower()
