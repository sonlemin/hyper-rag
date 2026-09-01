"""Cùng bộ assert cốt lõi của story 1.4, chạy trên Neo4j thật (marker `neo4j`).

Driver giả trong `tests/gia_lap_neo4j.py` chứng minh được rằng mệnh đề WHERE đi
cùng câu truy vấn và rằng adapter lọc theo đúng điều kiện nó khai. Thứ nó
không chứng minh được là câu Cypher có hợp lệ với Neo4j hay không, và cấu trúc
hai phía có thật sự nằm trong DB hay không. File này gánh phần đó, cùng cách
mà `hnsw_config` của story 1.3 phải chờ Qdrant thật.

Mặc định bỏ qua (`addopts = -m 'not neo4j'`) để `uv run pytest` vẫn chạy được
khi không có container. Chạy thật::

    NEO4J_URI=bolt://<ip-container>:7687 NEO4J_PASSWORD=... uv run pytest -m neo4j

Trên máy chủ, Neo4j không publish cổng ra host nhưng IP container vẫn tới được
từ host::

    docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \\
        hyper-rag-copilot-neo4j-1

Mỗi test mở driver, nạp, đo và dọn trong **một** `asyncio.run` duy nhất: pool
kết nối của driver neo4j gắn với event loop đã dùng nó lần đầu, nên một fixture
mở driver ở loop này rồi trả kết quả cho loop khác là lỗi "attached to a
different loop". Mỗi lần chạy dùng một `space` riêng và dọn nhãn đó ở cuối, nên
chạy nhiều lần trên cùng một DB không giẫm lên nhau.
"""

import asyncio
import os
from contextlib import asynccontextmanager

import pytest
from neo4j import AsyncGraphDatabase

from adapters.ingest_labels import ingest_label
from adapters.neo4j import (
    EDGE_TYPE,
    LABEL_ENTITY,
    LABEL_HYPEREDGE,
    Neo4jACLGraphStorage,
)
from adapters.policy_loader import load_policy
from core.keys import FILTER_KEY_FIELD
from core.permission import use_context, user_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.test_adapter_neo4j import id_hyperedge, nap_hyperedge

pytestmark = pytest.mark.neo4j

URI = os.environ.get("NEO4J_URI")
TAI_KHOAN = os.environ.get("NEO4J_USERNAME", "neo4j")
MAT_KHAU = os.environ.get("NEO4J_PASSWORD")


@pytest.fixture()
def khong_gian(session_prefix):
    if not URI or not MAT_KHAU:
        if os.environ.get("NEO4J_REQUIRED"):
            # CI đặt biến này: ở đó "bỏ qua" và "chạy xanh" phải phân biệt
            # được, nếu không một lần chạy hỏng cấu hình trông y hệt một lần
            # chạy tốt.
            pytest.fail(
                "NEO4J_REQUIRED được đặt nhưng thiếu NEO4J_URI/NEO4J_PASSWORD"
            )
        pytest.skip("thiếu NEO4J_URI/NEO4J_PASSWORD: bỏ qua test cần container")
    return f"{session_prefix}_that"


@pytest.fixture()
def policy():
    return load_policy(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def bang():
    return oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)


@asynccontextmanager
async def kho_that(khong_gian: str, policy):
    """Driver thật + adapter đã nạp 4 hyperedge fixture; dọn nhãn ở cuối."""
    driver = AsyncGraphDatabase.driver(URI, auth=(TAI_KHOAN, MAT_KHAU))
    adapter = Neo4jACLGraphStorage(
        namespace="chunk_entity_relation",
        global_config={"neo4j_health_delay": 0.2},
        embedding_func=None,
        neo4j_driver=driver,
    )
    try:
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            await adapter.initialize()
            for he in HYPEREDGES:
                with ingest_label(scope=he["scope"], content_type=he["content_type"]):
                    await nap_hyperedge(adapter, he)
        yield driver, adapter
    finally:
        try:
            async with driver.session() as phien:
                await phien.run(f"MATCH (n:`{khong_gian}`) DETACH DELETE n")
                await phien.run(f"DROP INDEX `node_id_{khong_gian}` IF EXISTS")
        finally:
            # Dọn hỏng thì vẫn phải đóng driver, nếu không mỗi lần chạy để lại
            # một pool kết nối treo.
            await driver.close()


async def doc_tho(driver, cypher, **params) -> list[dict]:
    """Đọc thẳng vào DB, không qua adapter - dùng để chấm đường ghi."""
    async with driver.session() as phien:
        ket_qua = await phien.run(cypher, **params)
        return [dict(d) async for d in ket_qua]


def test_cypher_hop_le_va_cau_truc_hai_phia_nam_trong_db(khong_gian, policy):
    """Cypher chạy được thật, và graph trong DB đúng hình dạng hai phía."""

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, _):
            he = THEO_ID["HE-01"]
            return await doc_tho(
                driver,
                f"MATCH (h:`{khong_gian}`:{LABEL_HYPEREDGE} {{id: $id}})"
                f"-[r:{EDGE_TYPE}]->(e:`{khong_gian}`:{LABEL_ENTITY})\n"
                "RETURN e.id AS entity, r.slot AS slot,"
                f" h.{FILTER_KEY_FIELD} AS khoa_h, r.{FILTER_KEY_FIELD} AS khoa_r,"
                " h.space AS space",
                id=id_hyperedge(he),
            )

    dong = asyncio.run(chay())
    he = THEO_ID["HE-01"]
    assert sorted(d["entity"] for d in dong) == sorted(he["slots"].values())
    assert {d["slot"] for d in dong} == set(he["slots"])
    assert {d["khoa_h"] for d in dong} == {"noi_bo:runbook"}
    assert {d["khoa_r"] for d in dong} == {"noi_bo:runbook"}
    assert {d["space"] for d in dong} == {khong_gian}


def test_index_duoc_dung_that(khong_gian, policy):
    """`initialize()` tạo index thật, không phải một câu chạy rồi trôi.

    Đây cũng là chỗ duy nhất chứng minh câu `CREATE INDEX` hợp lệ: driver giả
    chỉ so chuỗi con, nên một cú pháp sai (ví dụ `ON EACH [...]` của fulltext)
    vẫn qua được bộ test không container.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, _):
            return await doc_tho(
                driver, "SHOW INDEXES YIELD name, properties, labelsOrTypes"
            )

    dong = asyncio.run(chay())
    cua_ta = [d for d in dong if d["name"] == f"node_id_{khong_gian}"]
    assert cua_ta, [d["name"] for d in dong]
    assert cua_ta[0]["properties"] == ["id"]
    assert cua_ta[0]["labelsOrTypes"] == [khong_gian]


def test_hai_vai_hai_ket_qua_tren_neo4j_that(khong_gian, policy, bang):
    """Cổng M1 phía graph: hai vai, hai ngữ cảnh truy hồi, lọc bởi WHERE thật."""

    async def chay():
        thay = {}
        async with kho_that(khong_gian, policy) as (_, adapter):
            for ten_vai in ("devops", "tech_support"):
                ctx = user_context(
                    policy=policy,
                    role=ten_vai,
                    space=khong_gian,
                    real_account=f"{ten_vai}01",
                )
                with use_context(ctx):
                    thay[ten_vai] = [
                        he["id"]
                        for he in HYPEREDGES
                        if await adapter.get_node(id_hyperedge(he)) is not None
                    ]
        return thay

    thay = asyncio.run(chay())
    for ten_vai in thay:
        assert thay[ten_vai] == oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES)
    assert set(thay["tech_support"]) < set(thay["devops"])


def test_degree_va_has_co_theo_quyen_tren_neo4j_that(khong_gian, policy):
    """Degree co theo quyền và `has_*` trả False, đo trên chính DB."""

    async def chay():
        async with kho_that(khong_gian, policy) as (_, adapter):
            ctx = user_context(
                policy=policy,
                role="tech_support",
                space=khong_gian,
                real_account="ts01",
            )
            with use_context(ctx):
                return {
                    "bac_he01": await adapter.node_degree(
                        id_hyperedge(THEO_ID["HE-01"])
                    ),
                    "bac_he03": await adapter.node_degree(
                        id_hyperedge(THEO_ID["HE-03"])
                    ),
                    "co_he01": await adapter.has_node(id_hyperedge(THEO_ID["HE-01"])),
                    "co_he03": await adapter.has_node(id_hyperedge(THEO_ID["HE-03"])),
                    "cap_he01": await adapter.get_node_edges(
                        id_hyperedge(THEO_ID["HE-01"])
                    ),
                }

    do = asyncio.run(chay())
    assert do["bac_he01"] == len(THEO_ID["HE-01"]["slots"])
    # HE-03 là bí mật hạ tầng: L0 với vai này, nên vắng mặt hoàn toàn.
    assert do["bac_he03"] == 0
    assert do["co_he01"] is True
    assert do["co_he03"] is False
    # Lân cận điền vào slot `owner` bị tổng quát hóa kể cả ở L2 (AD-9, story
    # 1.6); sáu slot còn lại của runbook ra nguyên văn.
    assert sorted(c[1] for c in do["cap_he01"]) == sorted(
        oracle.dau_che_ky_vong(slot) if slot == "owner" else gia_tri
        for slot, gia_tri in THEO_ID["HE-01"]["slots"].items()
    )


def test_khoa_quyen_cua_canh_bi_loc_tren_neo4j_that(khong_gian, policy):
    """Cạnh mang khóa ngoài quyền vắng mặt, dù hai đầu đều thấy được.

    Ca này chỉ có nghĩa khi Cypher thật chạy được mệnh đề lọc trên biến cạnh,
    nên nó phải có mặt ở đây chứ không chỉ ở driver giả.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (_, adapter):
            with use_context(
                system_context(
                    space=khong_gian, policy_version=policy.policy_version
                )
            ):
                # Cạnh phụ giữa hai node runbook, nhưng nạp dưới nhãn bí mật.
                with ingest_label(
                    scope="noi_bo", content_type="bi_mat_ha_tang"
                ):
                    await adapter.upsert_edge(
                        id_hyperedge(THEO_ID["HE-01"]),
                        THEO_ID["HE-01"]["slots"]["condition"],
                        {"weight": 1.0, "slot": "condition"},
                    )
            ctx = user_context(
                policy=policy,
                role="tech_support",
                space=khong_gian,
                real_account="ts01",
            )
            with use_context(ctx):
                return {
                    "cap": await adapter.get_node_edges(
                        id_hyperedge(THEO_ID["HE-01"])
                    ),
                    "bac": await adapter.node_degree(
                        id_hyperedge(THEO_ID["HE-01"])
                    ),
                }

    do = asyncio.run(chay())
    con_lai = sorted(
        oracle.dau_che_ky_vong(slot) if slot == "owner" else gia_tri
        for slot, gia_tri in THEO_ID["HE-01"]["slots"].items()
        if slot != "condition"
    )
    assert sorted(c[1] for c in do["cap"]) == con_lai
    assert do["bac"] == len(con_lai)
