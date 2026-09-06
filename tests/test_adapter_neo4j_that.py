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
    NodeIdRoleConflict,
)
from core.keys import CHUA_GHI, FILTER_KEY_FIELD
from core.permission import use_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.ho_tro_neo4j import id_hyperedge, nap_hyperedge
from tests.ngu_canh import vai

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
                await phien.run(
                    f"DROP CONSTRAINT `id_duy_nhat_{khong_gian}` IF EXISTS"
                )
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


def test_rang_buoc_duy_nhat_co_that_va_mang_theo_index(khong_gian, policy):
    """`initialize()` tạo ràng buộc duy nhất thật, kèm index hậu thuẫn của nó.

    Đây là chỗ duy nhất chứng minh câu `CREATE CONSTRAINT` hợp lệ: driver giả
    chỉ so chuỗi con, nên một cú pháp sai vẫn qua được bộ test không container.
    Và đây cũng là chỗ trả lời câu hỏi "đổi index thường sang ràng buộc thì
    đường tra node theo id còn index không" - Neo4j dựng một index hậu thuẫn
    cho mỗi ràng buộc duy nhất, và test đọc chính `SHOW INDEXES` để khẳng định.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, _):
            return (
                await doc_tho(
                    driver,
                    "SHOW CONSTRAINTS YIELD name, properties, labelsOrTypes, type",
                ),
                await doc_tho(
                    driver, "SHOW INDEXES YIELD name, properties, labelsOrTypes"
                ),
            )

    rang_buoc, index = asyncio.run(chay())
    cua_ta = [d for d in rang_buoc if d["name"] == f"id_duy_nhat_{khong_gian}"]
    assert cua_ta, [d["name"] for d in rang_buoc]
    assert cua_ta[0]["properties"] == ["id"]
    assert cua_ta[0]["labelsOrTypes"] == [khong_gian]
    assert "UNIQUENESS" in cua_ta[0]["type"]
    # Index hậu thuẫn mang cùng tên với ràng buộc.
    ho_tro = [d for d in index if d["name"] == f"id_duy_nhat_{khong_gian}"]
    assert ho_tro, [d["name"] for d in index]
    assert ho_tro[0]["properties"] == ["id"]
    # Index thường của story 1.4 phải đã được gỡ: hai index tương đương trên
    # cùng một thuộc tính là một mặt phải bảo trì mà không ai cần.
    assert not [d for d in index if d["name"] == f"node_id_{khong_gian}"]


def test_id_trung_khac_vai_bi_neo4j_that_tu_choi(khong_gian, policy):
    """Hàng cuối I/O Matrix, đo trên chính DB: `id IS UNIQUE` nổ, không gộp.

    Driver giả dựng lại luật này bằng tay, nên nó chỉ chứng minh adapter *đổi*
    lỗi thành mã của dự án. Thứ chỉ Neo4j thật trả lời được là ràng buộc có
    thật sự chặn hay không - và nếu nó không chặn thì read-merge-write đang đọc
    "khóa của node có id này" trên hai node.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, adapter):
            he = THEO_ID["HE-01"]
            with use_context(
                system_context(
                    space=khong_gian, policy_version=policy.policy_version
                )
            ):
                with ingest_label(scope="noi_bo", content_type="runbook"):
                    with pytest.raises(NodeIdRoleConflict) as loi:
                        # `App01` đã là node vai entity; ghi lại dưới vai
                        # hyperedge là đúng ca id trùng khác vai.
                        await adapter.upsert_node(
                            he["slots"]["subject"], {"role": "hyperedge"}
                        )
            dem = await doc_tho(
                driver,
                f"MATCH (n:`{khong_gian}` {{id: $id}}) RETURN count(n) AS so",
                id=he["slots"]["subject"],
            )
            return loi.value.code, dem[0]["so"]

    ma, so_node = asyncio.run(chay())
    assert ma == "NODE_ID_ROLE_CONFLICT"
    assert so_node == 1, "ràng buộc không chặn: một id thành hai node"


def test_ca_khong_khoa_go_han_thuoc_tinh_tren_neo4j_that(khong_gian, policy):
    """Hợp nhất ra "không khóa" thì node ở lại mà `filter_key` biến mất thật.

    `SET n.filter_key = null` gỡ hẳn thuộc tính trong Neo4j chứ không để lại
    một giá trị null - đó là hành vi mà luật vô hình đứng lên (`IN $keys`
    không khớp một thuộc tính vắng), và nó chỉ kiểm được trên DB thật.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, adapter):
            entity = THEO_ID["HE-01"]["slots"]["condition"]
            with use_context(
                system_context(
                    space=khong_gian, policy_version=policy.policy_version
                )
            ):
                with ingest_label(
                    scope="khach_hang_a", content_type="bao_cao_su_co"
                ):
                    await adapter.upsert_node(entity, {"role": "entity"})
            trong_db = await doc_tho(
                driver,
                f"MATCH (n:`{khong_gian}` {{id: $id}})\n"
                f"RETURN '{FILTER_KEY_FIELD}' IN keys(n) AS con_khoa,"
                " count(n) AS so",
                id=entity,
            )
            with use_context(vai(policy, "devops", khong_gian)):
                con_thay = await adapter.get_node(entity)
            return trong_db[0], con_thay

    trong_db, con_thay = asyncio.run(chay())
    assert trong_db["so"] == 1, "node cấu trúc phải ở lại"
    assert trong_db["con_khoa"] is False, "khóa phải bị gỡ hẳn, không phải null"
    assert con_thay is None, "vai rộng nhất cũng không tới được node không khóa"


def test_hai_vai_hai_ket_qua_tren_neo4j_that(khong_gian, policy, bang):
    """Cổng M1 phía graph: hai vai, hai ngữ cảnh truy hồi, lọc bởi WHERE thật."""

    async def chay():
        thay = {}
        async with kho_that(khong_gian, policy) as (_, adapter):
            for ten_vai in ("devops", "tech_support"):
                with use_context(vai(policy, ten_vai, khong_gian)):
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
            with use_context(vai(policy, "tech_support", khong_gian)):
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
        oracle.dau_che_ky_vong(slot, THEO_ID["HE-01"]["content_type"])
        if slot == "owner"
        else gia_tri
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
            with use_context(vai(policy, "tech_support", khong_gian)):
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
        oracle.dau_che_ky_vong(slot, THEO_ID["HE-01"]["content_type"])
        if slot == "owner"
        else gia_tri
        for slot, gia_tri in THEO_ID["HE-01"]["slots"].items()
        if slot != "condition"
    )
    assert sorted(c[1] for c in do["cap"]) == con_lai
    assert do["bac"] == len(con_lai)


def test_hai_canh_khac_slot_tren_mot_cap_tren_neo4j_that(khong_gian, policy):
    """Story 2.4: `MERGE ... [r:SLOT {slot: $slot}]` tách hai vai thành hai cạnh trên DB thật.

    Ba đường đọc đổi cùng lúc phải được Neo4j thật chấp nhận: `get_node_edges`
    một bản ghi mỗi cạnh, `get_edge` gộp bằng `collect(properties(r))`,
    `node_degree` bằng `count(DISTINCT m)`; cộng `slot_cua_hyperedge` dưới cờ
    system. Driver giả chỉ diễn giải, cú pháp là việc của file này.
    """
    he = THEO_ID["HE-01"]

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, adapter):
            with use_context(
                system_context(space=khong_gian, policy_version=policy.policy_version)
            ):
                with ingest_label(scope=he["scope"], content_type=he["content_type"]):
                    # `App01` (subject của HE-01) điền thêm vai `source` của chính HE-01.
                    await adapter.upsert_edge(
                        id_hyperedge(he), "App01", {"weight": 2.0, "source_id": "chunk-x", "slot": "source"}
                    )
                slots = await adapter.slot_cua_hyperedge(id_hyperedge(he))
            so_canh = await doc_tho(
                driver,
                f"MATCH (h:`{khong_gian}` {{id: $id}})-[r:{EDGE_TYPE}]->(e:`{khong_gian}` {{id: 'App01'}})"
                " RETURN count(r) AS so, collect(r.slot) AS slot",
                id=id_hyperedge(he),
            )
            with use_context(vai(policy, "devops", khong_gian)):
                cap = await adapter.get_node_edges(id_hyperedge(he))
                canh = await adapter.get_edge(id_hyperedge(he), "App01")
                bac = await adapter.node_degree(id_hyperedge(he))
            return so_canh[0], slots, cap, canh, bac

    so_canh, slots, cap, canh, bac = asyncio.run(chay())
    assert so_canh["so"] == 2 and sorted(so_canh["slot"]) == ["source", "subject"]
    assert [c[1] for c in cap].count("App01") == 2, "một bản ghi mỗi cạnh"
    assert canh["weight"] == 3.0 and canh["slots"] == ["source", "subject"]
    assert set(canh["source_id"].split("<SEP>")) == {he["id"], "chunk-x"}
    assert bac == len(he["slots"]), "degree đếm distinct lân cận"
    assert slots["subject"] == ["App01"] and slots["source"] == sorted(["App01", he["slots"]["source"]])


def test_duong_xoa_va_ghi_thang_hop_le_tren_neo4j_that(khong_gian, policy):
    """Ba câu Cypher mới của story 2.3 chạy được trên server thật, đúng ngữ nghĩa.

    Driver giả chỉ diễn giải câu; `DETACH DELETE ... RETURN count(n)`,
    `MATCH ... SET ... RETURN count(n)` và pattern lân cận theo nhãn Hyperedge
    phải được Neo4j thật chấp nhận. Dọn bằng `xoa_tat_ca` ở cuối.
    """

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, adapter):
            with use_context(
                system_context(space=khong_gian, policy_version=policy.policy_version)
            ):
                khoa = await adapter.khoa_lan_can_hyperedge("App01")
                await adapter.dat_lai_entity(
                    "App01", description="mô tả mới", source_id="chunk-HE-02", khoa=None
                )
                sau_dat_lai = await adapter.khoa_hien_co(["App01"])
                da_xoa = await adapter.xoa_node([id_hyperedge(THEO_ID["HE-01"]), "khong-co"])
                khoa_sau = await adapter.khoa_lan_can_hyperedge("App01")
                con = await adapter.khoa_hien_co([id_hyperedge(THEO_ID["HE-01"])])
                tat_ca = await adapter.xoa_tat_ca()
                rong = await adapter.khoa_hien_co(["App01"])
            return khoa, sau_dat_lai, da_xoa, khoa_sau, con, tat_ca, rong

    khoa, sau_dat_lai, da_xoa, khoa_sau, con, tat_ca, rong = asyncio.run(chay())
    assert len(khoa) == 2 and set(khoa) == {"noi_bo:runbook", "noi_bo:bao_cao_su_co"}
    assert sau_dat_lai["App01"] is None
    assert da_xoa == 1 and khoa_sau == ["noi_bo:bao_cao_su_co"]
    assert con[id_hyperedge(THEO_ID["HE-01"])] is CHUA_GHI
    assert tat_ca > 0 and rong["App01"] is CHUA_GHI


# ---------------------------------------------------------------------------
# Rò chéo hai space trên Neo4j thật (story 2.11)
# ---------------------------------------------------------------------------

# Hyperedge chỉ tồn tại trong space thứ hai; id và giá trị slot khác hẳn bốn
# fixture để một lần rò nhìn thấy được ngay.
HE_CHI_O_REAL = {
    "id": "HE-99",
    "scope": "noi_bo",
    "content_type": "runbook",
    "slots": {"subject": "AppReal99", "symptom": "loi 500", "remediation": "khoi dong lai"},
}


@pytest.fixture()
def hai_khong_gian(session_prefix):
    """Hai space trên **cùng** một Neo4j: một giống `synth`, một là `real`.

    Tên thứ hai kết thúc bằng `_real` nên `core.ids.la_space_real` nhận nó -
    đúng hình dạng story 2.11 dùng thật.
    """
    if not URI or not MAT_KHAU:
        if os.environ.get("NEO4J_REQUIRED"):
            pytest.fail("NEO4J_REQUIRED được đặt nhưng thiếu NEO4J_URI/NEO4J_PASSWORD")
        pytest.skip("thiếu NEO4J_URI/NEO4J_PASSWORD: bỏ qua test cần container")
    return f"{session_prefix}_synth", f"{session_prefix}_real"


@asynccontextmanager
async def hai_kho_that(a: str, b: str, policy):
    """Một driver, hai nhãn space: `a` mang 4 fixture, `b` mang đúng `HE-99`."""
    driver = AsyncGraphDatabase.driver(URI, auth=(TAI_KHOAN, MAT_KHAU))
    adapter = Neo4jACLGraphStorage(
        namespace="chunk_entity_relation",
        global_config={"neo4j_health_delay": 0.2},
        embedding_func=None,
        neo4j_driver=driver,
    )
    try:
        for khong_gian, cac_he in ((a, HYPEREDGES), (b, [HE_CHI_O_REAL])):
            with use_context(
                system_context(space=khong_gian, policy_version=policy.policy_version)
            ):
                await adapter.initialize()
                for he in cac_he:
                    with ingest_label(
                        scope=he["scope"], content_type=he["content_type"]
                    ):
                        await nap_hyperedge(adapter, he)
        yield driver, adapter
    finally:
        try:
            async with driver.session() as phien:
                for khong_gian in (a, b):
                    await phien.run(f"MATCH (n:`{khong_gian}`) DETACH DELETE n")
                    await phien.run(
                        f"DROP CONSTRAINT `id_duy_nhat_{khong_gian}` IF EXISTS"
                    )
                    await phien.run(f"DROP INDEX `node_id_{khong_gian}` IF EXISTS")
        finally:
            await driver.close()


def test_hai_space_khong_ro_cheo_duoi_co_he_thong_tren_neo4j_that(hai_khong_gian, policy):
    """AC story 2.11, đường Cypher: một space không thấy node của space kia.

    Đo dưới **cờ hệ thống**, không dưới một vai. Ngữ cảnh hệ thống bỏ hết lọc
    khóa và chỉ còn điều kiện `space` (`adapters/neo4j.py:_menh_de_loc`), nên
    đây là phép đo duy nhất tách được chiều `space` khỏi chiều quyền: nếu test
    chạy dưới một vai, một kết quả rỗng có thể chỉ là chính sách chặn, và ranh
    giới space vẫn thủng mà không ai biết.
    """
    a, b = hai_khong_gian

    async def chay():
        async with hai_kho_that(a, b, policy) as (_, adapter):
            id_a = id_hyperedge(THEO_ID["HE-01"])
            id_b = id_hyperedge(HE_CHI_O_REAL)
            thay = {}
            for khong_gian in (a, b):
                with use_context(
                    system_context(
                        space=khong_gian, policy_version=policy.policy_version
                    )
                ):
                    thay[khong_gian] = {
                        "a": await adapter.get_node(id_a) is not None,
                        "b": await adapter.get_node(id_b) is not None,
                        "entity_b": await adapter.has_node("AppReal99"),
                    }
            return thay

    thay = asyncio.run(chay())
    # Mỗi space thấy đúng dữ liệu của mình - đối chứng để một kết quả "không
    # thấy gì cả" không đọc thành "cách ly tốt".
    assert thay[a]["a"] is True and thay[b]["b"] is True
    # Và không thấy gì của space kia, cả hyperedge lẫn entity.
    assert thay[a]["b"] is False, "hyperedge của space real lọt sang space synth"
    assert thay[a]["entity_b"] is False, "entity của space real lọt sang space synth"
    assert thay[b]["a"] is False, "hyperedge của space synth lọt sang space real"


def test_khong_node_nao_mang_ca_hai_nhan_space_tren_neo4j_that(hai_khong_gian, policy):
    """Đối chứng ở tầng ghi: hai space là hai tập node rời, đọc thẳng bằng Cypher.

    Test trên chấm đường *đọc*. Không có test này thì một adapter ghi chung node
    cho hai space rồi lọc lúc đọc vẫn xanh, và cách ly là mệnh đề của câu truy
    vấn chứ không của dữ liệu trong kho.
    """
    a, b = hai_khong_gian

    async def chay():
        async with hai_kho_that(a, b, policy) as (driver, _):
            return await doc_tho(
                driver,
                f"OPTIONAL MATCH (ca:`{a}`:`{b}`)\n"
                f"WITH count(ca) AS ca_hai\n"
                f"MATCH (x:`{a}`) WITH ca_hai, count(x) AS so_a\n"
                f"MATCH (y:`{b}`) RETURN ca_hai, so_a, count(y) AS so_b",
            )

    (dong,) = asyncio.run(chay())
    assert dong["ca_hai"] == 0, "có node mang cả hai nhãn space"
    assert dong["so_a"] > dong["so_b"] > 0


def test_trich_dan_cua_tren_neo4j_that(khong_gian, policy, bang):
    """Story 3.4: cửa quyền của citation chạy được trên Neo4j thật, đúng ngữ nghĩa.

    Driver giả chỉ diễn giải câu; `MATCH ... WHERE h.id IN $ids` cộng
    `OPTIONAL MATCH` và `collect(DISTINCT r.slot)` phải được server thật chấp
    nhận. Ba vế: tập id trả về bằng đúng `hyperedge_thay_duoc` của oracle theo
    từng vai (hyperedge L0 vắng mặt), khóa và tập vai của từng mục khớp fixture,
    và một hyperedge thấy được nhưng không cạnh nào qua lọc vẫn về một dòng với
    `cac_vai == ()` - ca ấy dựng bằng một hyperedge mới chỉ có node, không cạnh.
    """
    he_moi = "rel-HE-KHONG-CANH"
    he1 = THEO_ID["HE-01"]

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, adapter):
            with use_context(
                system_context(space=khong_gian, policy_version=policy.policy_version)
            ):
                with ingest_label(scope=he1["scope"], content_type=he1["content_type"]):
                    await adapter.upsert_node(
                        he_moi, {"role": "hyperedge", "weight": 1.0, "source_id": "chunk-x"}
                    )
            ids = [id_hyperedge(he) for he in HYPEREDGES] + [he_moi, "rel-khong-co"]
            ra = {}
            for ten_vai in ("devops", "tech_support"):
                with use_context(vai(policy, ten_vai, khong_gian)):
                    ra[ten_vai] = await adapter.trich_dan_cua(ids)
            return ra

    ra = asyncio.run(chay())
    for ten_vai, thay in ra.items():
        ky_vong = {
            id_hyperedge(he)
            for he in HYPEREDGES
            if he["id"] in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES)
        }
        assert set(thay) == ky_vong | {he_moi}, ten_vai
        assert "rel-khong-co" not in thay
        for he in HYPEREDGES:
            if oracle.muc_ky_vong(bang, ten_vai, he["content_type"]) == "L0":
                assert id_hyperedge(he) not in thay
            if id_hyperedge(he) in thay:
                khoa, cac_vai = thay[id_hyperedge(he)]
                assert khoa == oracle.khoa_ky_vong(he["scope"], he["content_type"])
                assert set(cac_vai) == set(he["slots"])
        assert thay[he_moi] == (oracle.khoa_ky_vong(he1["scope"], he1["content_type"]), ())


def test_hyperedge_ke_can_tren_neo4j_that(khong_gian, policy):
    """Story 5.2: pha một của vùng cấp chạy được trên Neo4j thật, đúng ngữ nghĩa.

    Pattern hai cạnh `(g)-[r1]-(e)-[r2]-(h)` với năm mệnh đề lọc và
    `RETURN DISTINCT` phải được server thật chấp nhận. Ba vế: `tech_support` từ
    HE-02 thấy `(HE-01,)` (chung `subject` App01, HE-01 là runbook L2 nên vẫn
    **thấy** ở pha một, pha hai mới loại), từ HE-03 (L0 với vai này) là `()`;
    id vào không có trong kết quả (HE-01 và HE-02 cùng vào thì rỗng); ngữ cảnh
    hệ thống bị từ chối.
    """
    from adapters.do_thi import DoThiNgoaiQuyen

    he1, he2, he3 = (id_hyperedge(THEO_ID[i]) for i in ("HE-01", "HE-02", "HE-03"))

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, adapter):
            ra = {}
            with use_context(vai(policy, "tech_support", khong_gian)):
                ra["ts_tu_he2"] = await adapter.hyperedge_ke_can([he2])
                ra["ts_tu_he3"] = await adapter.hyperedge_ke_can([he3])
                ra["ts_ca_hai"] = await adapter.hyperedge_ke_can([he2, he1])
            with use_context(vai(policy, "devops", khong_gian)):
                ra["dev_tu_he1"] = await adapter.hyperedge_ke_can([he1])
                ra["dev_tu_he3"] = await adapter.hyperedge_ke_can([he3])
            with use_context(system_context(space=khong_gian, policy_version=policy.policy_version)):
                with pytest.raises(DoThiNgoaiQuyen):
                    await adapter.hyperedge_ke_can([he2])
            return ra

    ra = asyncio.run(chay())
    assert ra["ts_tu_he2"] == (he1,)
    assert ra["ts_tu_he3"] == () and ra["ts_ca_hai"] == ()
    assert ra["dev_tu_he1"] == (he2,) and ra["dev_tu_he3"] == ()


def test_do_thi_cua_tren_neo4j_that(khong_gian, policy, bang):
    """Story 3.7: đường đọc đồ thị chạy được trên Neo4j thật, đúng ngữ nghĩa.

    `MATCH (h)-[r]-(e) WHERE h.id IN $ids ...` với ba mệnh đề chặt phải được
    server thật chấp nhận. Ba vế: tập hyperedge có dòng bằng `hyperedge_thay_duoc`
    của oracle theo từng vai; với từng hyperedge, vai bị che ra dấu che kỳ vọng
    (`dau_che_ky_vong`) còn vai không che ra đúng giá trị slot; và một
    hyperedge mà đỉnh duy nhất là entity **không khóa** (hợp nhất khác scope)
    không về dòng nào - ca ấy dựng bằng một hyperedge mới ở `khach_hang_a`
    dùng lại `subject` của HE-03.
    """
    he_moi = "rel-HE-KHONG-KHOA"
    he3 = THEO_ID["HE-03"]
    subject3 = he3["slots"]["subject"]

    async def chay():
        async with kho_that(khong_gian, policy) as (driver, adapter):
            with use_context(
                system_context(space=khong_gian, policy_version=policy.policy_version)
            ):
                with ingest_label(scope="khach_hang_a", content_type="runbook"):
                    await adapter.upsert_node(
                        he_moi, {"role": "hyperedge", "weight": 1.0, "source_id": "chunk-x"}
                    )
                    await adapter.upsert_node(
                        subject3,
                        {"role": "entity", "entity_type": "KHAC", "description": subject3, "source_id": "chunk-x"},
                    )
                    await adapter.upsert_edge(
                        he_moi, subject3, {"weight": 1.0, "source_id": "chunk-x", "slot": "subject"}
                    )
            ids = [id_hyperedge(he) for he in HYPEREDGES] + [he_moi, "rel-khong-co"]
            ra = {}
            for ten_vai in ("devops", "tech_support"):
                with use_context(vai(policy, ten_vai, khong_gian)):
                    ra[ten_vai] = await adapter.do_thi_cua(ids)
            return ra

    ra = asyncio.run(chay())
    for ten_vai, dong in ra.items():
        co_dong = {d["id_hyperedge"] for d in dong}
        ky_vong = {
            id_hyperedge(he)
            for he in HYPEREDGES
            if he["id"] in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES)
        }
        assert co_dong == ky_vong, ten_vai
        assert he_moi not in co_dong and "rel-khong-co" not in co_dong
        for he in HYPEREDGES:
            if id_hyperedge(he) not in co_dong:
                continue
            che = oracle.slot_phai_che(bang, ten_vai, he)
            theo_vai = {d["slot"]: d for d in dong if d["id_hyperedge"] == id_hyperedge(he)}
            # HE-03 với `devops`: `subject` hợp nhất khác scope thành không khóa và vắng.
            vai_co = set(he["slots"]) - ({"subject"} if he["id"] == "HE-03" else set())
            assert set(theo_vai) == vai_co, (ten_vai, he["id"])
            for v, d in theo_vai.items():
                assert d["khoa"] == oracle.khoa_ky_vong(he["scope"], he["content_type"])
                if v in che:
                    assert d["bi_che"] and d["ten_da_che"] == oracle.dau_che_ky_vong(v, he["content_type"])
                else:
                    assert not d["bi_che"] and d["ten_da_che"] == he["slots"][v]
