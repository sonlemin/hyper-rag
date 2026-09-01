"""Helper dựng và nạp kho graph, dùng chung cho các bộ test adapter Neo4j.

Tách khỏi file test khi `tests/test_adapter_neo4j.py` vượt ngưỡng 1000 dòng và
phải chia đôi. Bộ test chạy trên Neo4j thật cũng đứng lên đúng những hàm này,
nên trước đó nó phải import từ một file test khác - một chiều phụ thuộc mà
module helper riêng gỡ được.

`nap_hyperedge` dựng đúng thứ tự và đúng hình dạng dict mà upstream gọi
(`operate.py:134-253`): node hyperedge, node entity, rồi cạnh nối hai bên.
"""

from core.keys import filter_key
from core.permission import use_context
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.ngu_canh import ngu_canh_ingest

from adapters.ingest_labels import ingest_label
from adapters.neo4j import Neo4jACLGraphStorage

# Bảy method đọc của `BaseGraphStorage`, đúng danh sách mà adapter override.
BAY_METHOD_DOC = (
    "has_node",
    "has_edge",
    "get_node",
    "get_edge",
    "get_node_edges",
    "node_degree",
    "edge_degree",
)


def dung_adapter(driver, **cau_hinh) -> Neo4jACLGraphStorage:
    """Adapter đúng cách upstream dựng nó, cộng driver giả để đo."""
    return Neo4jACLGraphStorage(
        namespace="chunk_entity_relation",
        global_config=cau_hinh,
        embedding_func=None,
        neo4j_driver=driver,
    )


def id_hyperedge(he) -> str:
    """Id hyperedge đúng hình dạng upstream sinh (`rel-…`)."""
    return f"rel-{he['id']}"


def khoa_cua(he) -> str:
    """Khóa lọc của một hyperedge fixture."""
    return filter_key(he["scope"], he["content_type"])


async def nap_hyperedge(adapter, he) -> None:
    """Nạp một hyperedge fixture thành cấu trúc hai phía.

    Đúng thứ tự và đúng hình dạng dict mà upstream gọi (`operate.py:134-253`):
    node hyperedge, node entity, rồi cạnh nối hai bên. Vai slot là thứ upstream
    *chưa* gửi (story 2.4 mới có prompt trích xuất), nên test truyền tường minh
    để cơ chế nhãn vai được kiểm ngay từ story này.
    """
    id_he = id_hyperedge(he)
    await adapter.upsert_node(
        id_he, {"role": "hyperedge", "weight": 1.0, "source_id": he["id"]}
    )
    for slot, gia_tri in he["slots"].items():
        await adapter.upsert_node(
            gia_tri,
            {
                "role": "entity",
                "entity_type": "KHAC",
                "description": gia_tri,
                "source_id": he["id"],
            },
        )
        await adapter.upsert_edge(
            id_he, gia_tri, {"weight": 1.0, "source_id": he["id"], "slot": slot}
        )


async def graph_da_nap(khong_gian, policy, driver=None):
    """Driver giả + adapter đã nạp xong 4 hyperedge fixture."""
    driver = driver or Neo4jGhiLai()
    adapter = dung_adapter(driver)
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        await adapter.initialize()
        for he in HYPEREDGES:
            with ingest_label(scope=he["scope"], content_type=he["content_type"]):
                await nap_hyperedge(adapter, he)
    driver.xoa_nhat_ky()
    return driver, adapter


async def goi_moi_method_doc(adapter, id_he: str, id_entity: str) -> None:
    """Gọi đúng bảy method đọc của `BaseGraphStorage` một lượt."""
    await adapter.has_node(id_he)
    await adapter.has_edge(id_he, id_entity)
    await adapter.get_node(id_he)
    await adapter.get_edge(id_he, id_entity)
    await adapter.get_node_edges(id_he)
    await adapter.node_degree(id_he)
    await adapter.edge_degree(id_he, id_entity)
