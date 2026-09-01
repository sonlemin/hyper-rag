"""Adapter Neo4j: WHERE-injection và cấu trúc hai phía (story 1.4, FR-08).

Năm kịch bản `1.4-UNIT-001`, `1.4-INT-001..005` của test-design cộng mọi hàng
I/O Matrix của spec. Hai lớp assert, theo thứ tự quan trọng:

1. Chính câu Cypher đã gửi. Mọi biến node trong pattern phải bị ràng cả
   `space` lẫn khóa quyền; lọc lại phía Python sau khi bản ghi đã về là đúng
   thứ FR-08 cấm, và nhìn vào kết quả thì không phân biệt được hai đường đó.
2. Nội dung kết quả, đối chiếu `tests/fixtures/oracle.py` - bộ tính kỳ vọng
   độc lập, không gọi `core/`.

Driver là bản giả trong `tests/gia_lap_neo4j.py`: nó lọc theo đúng điều kiện
mà câu Cypher khai, nên quên tiêm WHERE cho một biến là kết quả sai chứ không
phải một câu văn khác đi. Không mạng, không container. Phần "Cypher có hợp lệ
với Neo4j thật không" do `tests/test_adapter_neo4j_that.py` gánh.
"""

import asyncio

import pytest

from adapters.ingest_labels import IngestLabelMissing, ingest_label
from adapters.mask_contract import HyperedgeKeyMissing, MaskContractViolated
from adapters.neo4j import (
    EDGE_TYPE,
    GRAPH_NAMESPACE,
    LABEL_ENTITY,
    LABEL_HYPEREDGE,
    NODE_ID_FIELD,
    EdgeEndpointMissing,
    Neo4jACLGraphStorage,
    Neo4jUnavailable,
    NodeRoleInvalid,
    SlotRoleInvalid,
)
from adapters.policy_loader import load_policy
from core.ids import normalize_id, point_id
from core.keys import FILTER_KEY_FIELD, filter_key
from core.permission import PermissionContextMissing, use_context, user_context
from core.slots import SLOT_ROLES
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.gia_lap_neo4j import Neo4jGhiLai, canh_moi_bien_deu_bi_loc


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


def vai(policy, ten_vai: str, khong_gian: str):
    """Ngữ cảnh quyền của một vai; đây là thứ adapter đọc lúc dựng WHERE."""
    return user_context(
        policy=policy, role=ten_vai, space=khong_gian, real_account=f"{ten_vai}01"
    )


def ngu_canh_ingest(khong_gian: str, policy):
    """Ngữ cảnh hệ thống của pipeline nạp; adapter chỉ lấy `space` từ đây."""
    return system_context(space=khong_gian, policy_version=policy.policy_version)


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
            {"role": "entity", "entity_type": "KHAC", "description": gia_tri,
             "source_id": he["id"]},
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


def khoa_cua(he) -> str:
    return filter_key(he["scope"], he["content_type"])


# --- 1.4-INT-001: upsert đúng cấu trúc hai phía ---------------------------


def test_upsert_dung_cau_truc_hai_phia(khong_gian, policy):
    """Hyperedge là node mang thuộc tính, cạnh nối entity mang vai slot.

    Đây là hình dạng mà FR-03/04 đòi: quan hệ n-ngôi không bị bẻ thành các cặp
    hai ngôi, mà thành một node hyperedge cộng n cạnh có vai.
    """

    async def chay():
        driver, _ = await graph_da_nap(khong_gian, policy)
        he = THEO_ID["HE-01"]
        node = driver.node_tho(khong_gian, id_hyperedge(he))
        assert node is not None
        assert node.nhan == {khong_gian, LABEL_HYPEREDGE}
        assert node.props["role"] == "hyperedge"
        assert node.props[FILTER_KEY_FIELD] == khoa_cua(he)
        assert node.props["space"] == khong_gian

        for slot, gia_tri in he["slots"].items():
            entity = driver.node_tho(khong_gian, gia_tri)
            assert entity is not None, gia_tri
            assert entity.nhan == {khong_gian, LABEL_ENTITY}
            canh = driver.canh_tho(khong_gian, id_hyperedge(he), gia_tri)
            assert canh is not None, slot
            assert canh.props["slot"] == slot
            assert canh.props[FILTER_KEY_FIELD] == khoa_cua(he)
            assert canh.props["space"] == khong_gian

        # Vai slot chỉ lấy từ danh mục `core/`, không có bảng thứ hai.
        assert set(he["slots"]) <= set(SLOT_ROLES)

    asyncio.run(chay())


def test_quan_he_hai_vai_di_cung_mot_duong(khong_gian, policy):
    """Quan hệ 2 vai là ca suy biến, không có nhánh ghi riêng (FR-04).

    Chấm bằng chính câu Cypher: hyperedge 2 vai và hyperedge 5 vai phát ra
    cùng một câu, chỉ khác tham số. Một nhánh riêng cho quan hệ hai ngôi sẽ
    hiện ra ở đây thành câu thứ hai.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        hai_vai = {
            "id": "HE-2N",
            "scope": "noi_bo",
            "content_type": "runbook",
            "slots": {"subject": "App02", "owner": "Phạm Văn Sơn"},
        }
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            for he in (THEO_ID["HE-01"], hai_vai):
                with ingest_label(
                    scope=he["scope"], content_type=he["content_type"]
                ):
                    await nap_hyperedge(adapter, he)

        cau_ghi_canh = {lg.cypher for lg in driver.loi_goi if "MERGE (a)-[" in lg.cypher}
        assert len(cau_ghi_canh) == 1, "quan hệ 2 vai đi một câu Cypher khác"
        assert driver.canh_tho(khong_gian, "rel-HE-2N", "App02").props["slot"] == "subject"
        assert driver.canh_tho(khong_gian, "rel-HE-2N", "Phạm Văn Sơn").props["slot"] == "owner"

    asyncio.run(chay())


def test_vai_slot_ngoai_danh_muc_bi_tu_choi(khong_gian, policy):
    """Slot lạ là lỗi, không phải một nhãn tự do: danh mục 8 vai là hợp đồng."""

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node("rel-X", {"role": "hyperedge"})
                await adapter.upsert_node("App01", {"role": "entity"})
                driver.xoa_nhat_ky()
                with pytest.raises(SlotRoleInvalid) as loi:
                    await adapter.upsert_edge(
                        "rel-X", "App01", {"weight": 1.0, "slot": "nguoi_bao_cao"}
                    )
        assert loi.value.code == "SLOT_ROLE_INVALID"
        assert driver.loi_goi == []
        assert driver.dem_canh() == 0

    asyncio.run(chay())


def test_canh_khong_khai_vai_van_ghi_duoc(khong_gian, policy):
    """Cạnh chưa có vai vẫn ghi được - upstream hiện chưa gửi vai nào.

    `_merge_edges_then_upsert` của upstream chỉ gửi `weight` và `source_id`;
    prompt trích xuất 8 vai thuộc story 2.4. Cấm cạnh thiếu vai ngay bây giờ là
    chặn chính đường e2e của cổng M1. Test ghim hiện trạng làm mốc so sánh cho
    story 2.4, không phải khẳng định đây là hành vi cuối cùng.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node("rel-X", {"role": "hyperedge"})
                await adapter.upsert_node("App01", {"role": "entity"})
                await adapter.upsert_edge("rel-X", "App01", {"weight": 1.0})
        canh = driver.canh_tho(khong_gian, "rel-X", "App01")
        assert canh is not None
        assert canh.props.get("slot") is None
        assert canh.props[FILTER_KEY_FIELD] == "noi_bo:runbook"

    asyncio.run(chay())


def test_ghi_ngoai_pham_vi_nhan_bi_tu_choi(khong_gian, policy):
    """Chưa mở nhãn ingest thì không node hay cạnh nào được tạo.

    Cùng luật với đường vector (story 1.3): một mục không khóa hoặc vô hình
    vĩnh viễn, hoặc lọt vào mọi vai.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with pytest.raises(IngestLabelMissing) as loi:
                await adapter.upsert_node("rel-X", {"role": "hyperedge"})
            with pytest.raises(IngestLabelMissing):
                await adapter.upsert_edge("rel-X", "App01", {"weight": 1.0})
        assert loi.value.code == "INGEST_LABEL_MISSING"
        assert driver.dem_node() == 0 and driver.dem_canh() == 0

    asyncio.run(chay())


def test_khoi_tao_tao_index_cho_duong_tra_node(khong_gian, policy):
    """`initialize()` dựng index cho thứ mọi đường đọc bắt đầu bằng: tra id.

    Hình dạng index chỉ kiểm được thật trên Neo4j (`test_adapter_neo4j_that.py`
    đọc `SHOW INDEXES`); ở đây chỉ ghim rằng bước khởi tạo có phát ra một câu
    tạo index lặp lại được, đúng nhãn không gian.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            # Gọi lại phải không hỏng: khởi động lại tiến trình là chuyện thường.
            await adapter.initialize()
        cau = driver.cau_cuoi().cypher
        assert cau.startswith("CREATE INDEX")
        assert "IF NOT EXISTS" in cau
        assert f"`{khong_gian}`" in cau
        assert f"ON (n.{NODE_ID_FIELD})" in cau

    asyncio.run(chay())


# --- 1.4-INT-002: bảy method đọc tiêm WHERE theo khóa ---------------------

BAY_METHOD_DOC = (
    "has_node",
    "has_edge",
    "get_node",
    "get_edge",
    "get_node_edges",
    "node_degree",
    "edge_degree",
)


async def goi_moi_method_doc(adapter, id_he: str, id_entity: str) -> None:
    """Gọi đúng bảy method đọc của `BaseGraphStorage` một lượt."""
    await adapter.has_node(id_he)
    await adapter.has_edge(id_he, id_entity)
    await adapter.get_node(id_he)
    await adapter.get_edge(id_he, id_entity)
    await adapter.get_node_edges(id_he)
    await adapter.node_degree(id_he)
    await adapter.edge_degree(id_he, id_entity)


def test_moi_method_doc_tiem_where_theo_khoa(khong_gian, policy, bang):
    """Cả 7 method đọc mang mệnh đề khóa trong chính câu Cypher (FR-08, AD-2).

    Assert hai chiều trên mọi câu đã gửi: mọi biến node bị ràng cả `space` lẫn
    khóa, và tập khóa trong tham số đúng bằng tập oracle tính độc lập. Một
    method quên tiêm WHERE thì hoặc biến của nó lọt lưới ở đây, hoặc kết quả
    của nó sai ở các test dưới.
    """

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        ky_vong = oracle.allowed_keys_ky_vong(bang, "tech_support")["hyperedges"]
        with use_context(vai(policy, "tech_support", khong_gian)):
            await goi_moi_method_doc(adapter, "rel-HE-01", "App01")

        cac_cau = driver.cac_cau_doc()
        for lg in cac_cau:
            canh_moi_bien_deu_bi_loc(lg.cypher)
            assert set(lg.params["keys"]) == ky_vong
            assert lg.params["space"] == khong_gian
        # Đếm theo từng method, không đếm tổng: một method ngừng gửi câu nào
        # đi (ví dụ ai đó thêm một lớp cache sớm) vẫn qua được phép đếm tổng.
        da_gui = {lg.loai.removeprefix("doc:") for lg in cac_cau}
        thieu = {ten for ten in BAY_METHOD_DOC if ten != "edge_degree"} - da_gui
        assert not thieu, f"method không gửi câu nào đi: {sorted(thieu)}"
        # `edge_degree` cố ý không có câu riêng: nó là tổng hai `node_degree`,
        # nên nó co theo quyền bằng chính luật của `node_degree`.
        assert "edge_degree" not in da_gui

    asyncio.run(chay())


def test_get_node_ngoai_quyen_tra_none(khong_gian, policy, bang):
    """Hyperedge ở L0 với vai đang hỏi thì vắng mặt, không phải bị che."""

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            assert await adapter.get_node("rel-HE-03") is None
            assert await adapter.get_node("rel-HE-01") is not None
        thay_duoc = oracle.hyperedge_thay_duoc(bang, "tech_support", HYPEREDGES)
        assert "HE-03" not in thay_duoc and "HE-01" in thay_duoc

    asyncio.run(chay())


def test_hai_vai_hai_tap_khoa_hai_ket_qua(khong_gian, policy, bang):
    """Cùng một node id, hai vai: khác biệt sinh từ WHERE, không từ lọc lại."""

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        thay = {}
        for ten_vai in ("devops", "tech_support"):
            driver.xoa_nhat_ky()
            with use_context(vai(policy, ten_vai, khong_gian)):
                thay[ten_vai] = [
                    he["id"]
                    for he in HYPEREDGES
                    if await adapter.get_node(id_hyperedge(he)) is not None
                ]
            cau = driver.cac_cau_doc()[-1]
            assert set(cau.params["keys"]) == oracle.allowed_keys_ky_vong(
                bang, ten_vai
            )["hyperedges"]

        for ten_vai in thay:
            assert thay[ten_vai] == oracle.hyperedge_thay_duoc(
                bang, ten_vai, HYPEREDGES
            )
        assert set(thay["tech_support"]) < set(thay["devops"])

    asyncio.run(chay())


def test_node_degree_co_theo_quyen(khong_gian, policy):
    """Số đếm co theo quyền: 3 lân cận thật, vai chỉ thấy 1 thì trả 1.

    Degree đi thẳng vào xếp hạng ngữ cảnh trả về (`operate.py:1041`), nên một
    entity "hạng 3" với vai chỉ thấy một hyperedge tự nó đã kể rằng còn hai
    fact nữa tồn tại.

    Bảng nhị phân dùng ở đây vì với nó `tech_support` chỉ còn thấy runbook -
    đúng ca "thấy 1 trong 3". Entity `App01` được ghi lại dưới nhãn runbook ở
    bước cuối để khóa của chính nó nằm trong tầm nhìn của vai; last-write-wins
    của khóa đa nguồn là khoản nợ có địa chỉ ở story 2.1.
    """
    policy_nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy_nhi_phan)):
            for he in (THEO_ID["HE-02"], THEO_ID["HE-03"], THEO_ID["HE-01"]):
                with ingest_label(
                    scope=he["scope"], content_type=he["content_type"]
                ):
                    await nap_hyperedge(adapter, he)
                    # HE-03 không có `App01` trong slot của nó; nối thêm ở đây
                    # để dựng đúng ca "một entity nằm trên ba hyperedge".
                    if he["id"] == "HE-03":
                        await adapter.upsert_edge(
                            "rel-HE-03", "App01", {"weight": 1.0, "slot": "subject"}
                        )
        assert driver.dem_lan_can_tho(khong_gian, "App01") == 3

        with use_context(vai(policy_nhi_phan, "tech_support", khong_gian)):
            assert await adapter.node_degree("App01") == 1
        with use_context(vai(policy_nhi_phan, "devops", khong_gian)):
            assert await adapter.node_degree("App01") == 2

    asyncio.run(chay())


def test_edge_degree_co_theo_quyen(khong_gian, policy):
    """`edge_degree` giữ ngữ nghĩa upstream (tổng hai degree) nên co cùng luật."""

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            bac_he = await adapter.node_degree("rel-HE-01")
            bac_entity = await adapter.node_degree("App01")
            assert await adapter.edge_degree("rel-HE-01", "App01") == (
                bac_he + bac_entity
            )
            # Một đầu ngoài quyền thì phần của nó đóng góp 0, không nổ.
            assert await adapter.edge_degree("rel-HE-03", "App01") == bac_entity

    asyncio.run(chay())


def test_has_node_va_has_edge_tra_false_ngoai_quyen(khong_gian, policy):
    """`has_*` trả False cho mục ngoài quyền, không phải lỗi và không phải True."""

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            assert await adapter.has_node("rel-HE-01") is True
            assert await adapter.has_node("rel-HE-03") is False
            assert await adapter.has_edge("rel-HE-01", "App01") is True
            assert (
                await adapter.has_edge(
                    "rel-HE-03", THEO_ID["HE-03"]["slots"]["subject"]
                )
                is False
            )
            # Hyperedge ngoài quyền cũng không kể ra cạnh nào: một cái tên lân
            # cận vẫn nói rằng có fact ở đó.
            assert await adapter.get_node_edges("rel-HE-03") == []
        with use_context(vai(policy, "devops", khong_gian)):
            assert await adapter.has_node("rel-HE-03") is True

    asyncio.run(chay())


def test_get_node_edges_tra_cap_id(khong_gian, policy):
    """Hợp đồng upstream: list cặp `(id, id_lân_cận)`, lân cận nằm ở `e[1]`.

    `operate.py:884-925` đưa thẳng `e[1]` vào `get_edge`/`get_node`, nên hình
    dạng này là hợp đồng chứ không phải lựa chọn.
    """

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        he = THEO_ID["HE-01"]
        with use_context(vai(policy, "tech_support", khong_gian)):
            cac_cap = await adapter.get_node_edges(id_hyperedge(he))
        assert all(isinstance(c, tuple) and len(c) == 2 for c in cac_cap)
        assert {c[0] for c in cac_cap} == {id_hyperedge(he)}
        assert sorted(c[1] for c in cac_cap) == sorted(he["slots"].values())

    asyncio.run(chay())


def test_get_node_edges_khong_ke_lan_can_ngoai_quyen(khong_gian, policy):
    """Lân cận ngoài quyền vắng mặt trong danh sách cạnh, không chỉ vắng nội dung."""
    policy_nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy_nhi_phan)):
            for he in (THEO_ID["HE-02"], THEO_ID["HE-01"]):
                with ingest_label(
                    scope=he["scope"], content_type=he["content_type"]
                ):
                    await nap_hyperedge(adapter, he)
        with use_context(vai(policy_nhi_phan, "tech_support", khong_gian)):
            cac_cap = await adapter.get_node_edges("App01")
        # App01 nối cả HE-01 (runbook, thấy) lẫn HE-02 (bao_cao_su_co, L0).
        assert [c[1] for c in cac_cap] == ["rel-HE-01"]

    asyncio.run(chay())


def test_tap_khoa_rong_khong_cham_neo4j(khong_gian, tmp_path):
    """Vai không thấy gì: trả rỗng theo từng method, không gửi câu nào đi.

    Đường "gửi truy vấn với danh sách khóa rỗng" là đường dựa vào Neo4j lọc
    hộ; nhánh đúng là không gọi. Assert trên nhật ký driver, không chỉ trên
    kết quả rỗng.
    """
    bang_mu = tmp_path / "policy-mu.yaml"
    bang_mu.write_text(
        "version: 1\n"
        "roles:\n"
        "  khach:\n"
        "    scopes: [noi_bo]\n"
        "    disclosure:\n"
        "      runbook: L0\n",
        encoding="utf-8",
    )
    policy_mu = load_policy(bang_mu)

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy_mu)
        with use_context(vai(policy_mu, "khach", khong_gian)):
            assert await adapter.has_node("rel-HE-01") is False
            assert await adapter.has_edge("rel-HE-01", "App01") is False
            assert await adapter.get_node("rel-HE-01") is None
            assert await adapter.get_edge("rel-HE-01", "App01") is None
            assert await adapter.get_node_edges("rel-HE-01") == []
            assert await adapter.node_degree("rel-HE-01") == 0
            assert await adapter.edge_degree("rel-HE-01", "App01") == 0
        assert driver.loi_goi == []

    asyncio.run(chay())


# --- 1.4-INT-003: fail-closed khi thiếu ngữ cảnh --------------------------


def test_thieu_ngu_canh_moi_method_deu_raise(khong_gian, policy):
    """Không có ngữ cảnh quyền thì không có đường nào chạy, kể cả đường ghi."""

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        for ten in BAY_METHOD_DOC:
            method = getattr(adapter, ten)
            with pytest.raises(PermissionContextMissing) as loi:
                if ten in ("has_edge", "get_edge", "edge_degree"):
                    await method("rel-HE-01", "App01")
                else:
                    await method("rel-HE-01")
            assert loi.value.code == "PERMISSION_CONTEXT_MISSING"
        with pytest.raises(PermissionContextMissing):
            await adapter.upsert_node("rel-X", {"role": "hyperedge"})
        with pytest.raises(PermissionContextMissing):
            await adapter.upsert_edge("rel-X", "App01", {"weight": 1.0})
        assert driver.loi_goi == []

    asyncio.run(chay())


def test_ngu_canh_he_thong_doc_tho(khong_gian, policy, monkeypatch):
    """Cờ bỏ-filter: không mệnh đề khóa, không che, vẫn ràng `space` (AD-3)."""
    from adapters import neo4j as mo_dun

    monkeypatch.setattr(
        mo_dun, "mask", lambda *a, **k: pytest.fail("che chạy dưới cờ bỏ-filter")
    )

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            assert await adapter.get_node("rel-HE-03") is not None
            assert await adapter.node_degree("rel-HE-03") == len(
                THEO_ID["HE-03"]["slots"]
            )
        for lg in driver.cac_cau_doc():
            canh_moi_bien_deu_bi_loc(lg.cypher, co_khoa=False)
            assert "keys" not in lg.params

    asyncio.run(chay())


# --- 1.4-INT-004: ba method trả nội dung đi qua tầng che ------------------


def test_ba_method_tra_noi_dung_di_qua_ham_che(khong_gian, policy, monkeypatch):
    """`get_node`/`get_edge`/`get_node_edges` qua `mask(kết quả, ctx, khóa)`.

    Story 1.6 thay ruột hàm che mà không mở lại adapter, nên thứ ghim ở đây là
    điểm gọi và ba tham số, không phải hành vi che. Khóa truyền vào phải là
    khóa của hyperedge liên quan (AD-9), kể cả khi lời gọi bắt đầu từ entity.
    """
    from adapters import neo4j as mo_dun

    da_goi = []

    def mask_gia(ket_qua, context, hyperedge_key):
        da_goi.append((ket_qua, context, hyperedge_key))
        return ket_qua

    monkeypatch.setattr(mo_dun, "mask", mask_gia)

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        he = THEO_ID["HE-01"]
        khoa = khoa_cua(he)
        ctx = vai(policy, "tech_support", khong_gian)
        with use_context(ctx):
            await adapter.get_node(id_hyperedge(he))
            await adapter.get_edge(id_hyperedge(he), "App01")
            await adapter.get_node_edges(id_hyperedge(he))
            # Bắt đầu từ entity: khóa che vẫn phải là khóa của hyperedge.
            await adapter.get_node_edges("App01")

        assert len(da_goi) == 2 + len(he["slots"]) + 2
        assert all(c is ctx for _, c, _ in da_goi)
        assert da_goi[0][2] == khoa

        # Khóa che của từng dòng phải đúng khóa của hyperedge *ở dòng đó*.
        # Assert theo tập là không đủ: `App01` mang khóa của HE-02 (last-write
        # -wins), nên một bản lấy nhầm khóa của phía entity vẫn nằm trong tập.
        theo_lan_can = {
            r["neighbor_id"]: k
            for r, _, k in da_goi
            if isinstance(r, dict) and "neighbor_id" in r and r["node_id"] == "App01"
        }
        assert theo_lan_can == {
            id_hyperedge(THEO_ID["HE-01"]): filter_key("noi_bo", "runbook"),
            id_hyperedge(THEO_ID["HE-02"]): filter_key("noi_bo", "bao_cao_su_co"),
        }

    asyncio.run(chay())


# --- 1.4-INT-005: health-check chờ Neo4j sẵn sàng -------------------------


def test_health_check_cho_neo4j_san_sang(khong_gian, policy):
    """Neo4j lên chậm hơn api là chuyện thường (bẫy A2, E1-OPS-01)."""

    async def chay():
        driver = Neo4jGhiLai(so_lan_chua_san_sang=2)
        adapter = dung_adapter(driver, neo4j_health_delay=0)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
        assert driver.so_lan_kiem_ket_noi == 3

    asyncio.run(chay())


def test_neo4j_khong_len_thi_bao_loi_on_dinh(khong_gian, policy):
    """Chờ tới hạn rồi báo một mã lỗi ổn định, không treo vô hạn."""

    async def chay():
        driver = Neo4jGhiLai(so_lan_chua_san_sang=99)
        adapter = dung_adapter(driver, neo4j_health_retries=3, neo4j_health_delay=0)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with pytest.raises(Neo4jUnavailable) as loi:
                await adapter.initialize()
        assert loi.value.code == "NEO4J_UNAVAILABLE"
        assert driver.so_lan_kiem_ket_noi == 3

    asyncio.run(chay())


# --- 1.4-UNIT-001: id chuẩn hóa dùng chung hai kho ------------------------


def test_id_chuan_hoa_dung_chung_hai_kho(khong_gian, policy):
    """Cùng đầu vào cho cùng id ở đường graph và đường vector (NFR-03).

    Upstream bọc tên node bằng dấu nháy kép. Adapter graph phải gỡ bằng đúng
    hàm mà `point_id` của Qdrant gỡ, nếu không id join chéo hai kho lệch nhau
    và test NFR-03 mất ý nghĩa.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node('"App01"', {"role": "entity"})
                await adapter.upsert_node("rel-HE-01", {"role": "hyperedge"})
                await adapter.upsert_edge(
                    '"rel-HE-01"', ' "App01" ', {"weight": 1.0, "slot": "subject"}
                )
        assert driver.node_tho(khong_gian, "App01") is not None
        assert driver.node_tho(khong_gian, '"App01"') is None
        assert driver.canh_tho(khong_gian, "rel-HE-01", "App01") is not None

        with use_context(vai(policy, "tech_support", khong_gian)):
            assert await adapter.get_node('"App01"') is not None
            assert await adapter.has_node("App01") is True

        # Cùng một hàm chuẩn hóa nuôi cả hai kho.
        assert point_id('"App01"') == point_id(normalize_id("App01"))

    asyncio.run(chay())


def test_cau_hinh_thieu_uri_thi_bao_ngay(khong_gian):
    """Không tiêm driver mà cũng không có `neo4j_uri` là hỏng lúc dựng adapter."""
    with pytest.raises(ValueError):
        Neo4jACLGraphStorage(
            namespace="chunk_entity_relation", global_config={}, embedding_func=None
        )


def test_hang_so_hop_dong_khong_troi_dat():
    """Ba hằng mà story 1.7 và Epic 2 sẽ ghi theo, ghim lại một chỗ."""
    assert GRAPH_NAMESPACE == "hyperedges"
    assert EDGE_TYPE == "SLOT"
    assert (LABEL_HYPEREDGE, LABEL_ENTITY) == ("Hyperedge", "Entity")


# --- Lớp bổ sung sau vòng review -------------------------------------------


def test_khoa_quyen_cua_canh_cung_bi_loc(khong_gian, policy):
    """Cạnh mang khóa riêng, và khóa đó phải nằm trong WHERE như khóa node.

    Khóa của node là last-write-wins theo tài liệu nạp sau (khoản nợ 2.1), nên
    một cạnh sinh từ tài liệu hạn chế có thể nối hai node mà vai đang hỏi vẫn
    thấy. Không lọc cạnh là để lộ `source_id` và vai slot của một fact ngoài
    quyền, dù hai đầu đều hợp lệ.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node("rel-HE-01", {"role": "hyperedge"})
                await adapter.upsert_node("App01", {"role": "entity"})
            # Cạnh nạp dưới một nhãn khác: hai đầu runbook, cạnh bí mật hạ tầng.
            with ingest_label(scope="noi_bo", content_type="bi_mat_ha_tang"):
                await adapter.upsert_edge(
                    "rel-HE-01", "App01", {"weight": 1.0, "slot": "subject"}
                )

        with use_context(vai(policy, "tech_support", khong_gian)):
            # tech_support thấy cả hai đầu (runbook = L2) nhưng không thấy cạnh.
            assert await adapter.get_node("rel-HE-01") is not None
            assert await adapter.get_node("App01") is not None
            assert await adapter.has_edge("rel-HE-01", "App01") is False
            assert await adapter.get_edge("rel-HE-01", "App01") is None
            assert await adapter.get_node_edges("rel-HE-01") == []
            assert await adapter.node_degree("rel-HE-01") == 0
        with use_context(vai(policy, "devops", khong_gian)):
            # devops thấy bi_mat_ha_tang ở L1, nên cạnh hiện ra.
            assert await adapter.has_edge("rel-HE-01", "App01") is True
            assert await adapter.node_degree("rel-HE-01") == 1

    asyncio.run(chay())


def test_khong_truy_van_nao_cham_hai_khong_gian(khong_gian, policy, session_prefix):
    """Cách ly `space`: nạp ở không gian này, đọc ở không gian kia là rỗng (AD-12)."""
    khong_gian_khac = f"{session_prefix}_real"

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node("rel-HE-01", {"role": "hyperedge"})
                await adapter.upsert_node("App01", {"role": "entity"})
                await adapter.upsert_edge(
                    "rel-HE-01", "App01", {"weight": 1.0, "slot": "subject"}
                )
        with use_context(vai(policy, "tech_support", khong_gian_khac)):
            assert await adapter.get_node("rel-HE-01") is None
            assert await adapter.has_node("rel-HE-01") is False
            assert await adapter.node_degree("rel-HE-01") == 0
            assert await adapter.get_node_edges("rel-HE-01") == []
        # Vẫn thấy được ở đúng không gian của nó: phép so mới có nghĩa.
        with use_context(vai(policy, "tech_support", khong_gian)):
            assert await adapter.get_node("rel-HE-01") is not None

    asyncio.run(chay())


def test_space_doc_khong_vao_duoc_cau_cypher(khong_gian, policy):
    """`space` là chuỗi duy nhất được nội suy vào Cypher, nên nó có lớp canh.

    Hai lớp: factory ngữ cảnh của `core/` từ chối dựng, và adapter kiểm lại
    trước khi ghép vào câu. Lớp thứ hai là thứ giữ cho một đường tương lai
    dựng context bằng cách khác không mở được cửa nội suy.
    """
    from types import SimpleNamespace

    for xau in ("khong gian", "synth`", "1_synth", "a" * 65):
        with pytest.raises(ValueError):
            user_context(
                policy=policy, role="devops", space=xau, real_account="tk01"
            )
    adapter = dung_adapter(Neo4jGhiLai())
    with pytest.raises(ValueError):
        adapter._nhan_space(SimpleNamespace(space="synth`OR-1=1"))
    assert adapter._nhan_space(SimpleNamespace(space=khong_gian)) == khong_gian


def test_node_khong_khai_vai_bi_tu_choi(khong_gian, policy):
    """Node không thuộc phía nào của đồ thị hai phía là lỗi, không phải node lạ."""

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                for du_lieu in ({}, {"role": "canh"}, {"role": None}):
                    with pytest.raises(NodeRoleInvalid) as loi:
                        await adapter.upsert_node("rel-X", du_lieu)
                    assert loi.value.code == "NODE_ROLE_INVALID"
        assert driver.dem_node() == 0

    asyncio.run(chay())


def test_ghi_canh_thieu_dau_thi_no_chu_khong_im(khong_gian, policy):
    """`MATCH ... MERGE` trượt là no-op im lặng của Cypher; adapter phải nổ."""

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node("rel-HE-01", {"role": "hyperedge"})
                with pytest.raises(EdgeEndpointMissing) as loi:
                    await adapter.upsert_edge(
                        "rel-HE-01", "App01", {"weight": 1.0, "slot": "subject"}
                    )
        assert loi.value.code == "EDGE_ENDPOINT_MISSING"
        assert driver.dem_canh() == 0

    asyncio.run(chay())


def test_hop_dong_che_bi_pha_thi_no_tai_cho(khong_gian, policy, monkeypatch):
    """`mask` trả rỗng hoặc bỏ mất trường là lỗi tại adapter, không phải sau đó.

    Story 1.6 viết ruột hàm che. Một bản trả `None` để "giấu hẳn" sẽ biến một
    fact thành "không tìm thấy" ở `get_node`, và thành `TypeError` trần ở
    `get_node_edges` - hai kiểu hỏng khác nhau, không kiểu nào có mã lỗi. Đường
    vector đã chốt hợp đồng này ở story 1.3; đường graph chốt cùng một luật.
    """
    from adapters import neo4j as mo_dun

    async def chay(mask_gia):
        monkeypatch.setattr(mo_dun, "mask", mask_gia)
        _, adapter = await graph_da_nap(khong_gian, policy)
        he = THEO_ID["HE-01"]
        with use_context(vai(policy, "tech_support", khong_gian)):
            for goi in (
                lambda: adapter.get_node(id_hyperedge(he)),
                lambda: adapter.get_edge(id_hyperedge(he), "App01"),
                lambda: adapter.get_node_edges(id_hyperedge(he)),
            ):
                with pytest.raises(MaskContractViolated) as loi:
                    await goi()
                assert loi.value.code == "MASK_CONTRACT_VIOLATED"

    asyncio.run(chay(lambda ban_ghi, ctx, khoa: None))
    asyncio.run(chay(lambda ban_ghi, ctx, khoa: {}))
    # Che là thay nội dung, không phải bỏ khóa khỏi bản ghi.
    asyncio.run(
        chay(lambda ban_ghi, ctx, khoa: {"chi_con_mot_truong": "[che]"})
    )


def test_khoa_che_vang_thi_fail_closed(khong_gian, policy):
    """Không truy ra khóa hyperedge thì từ chối, không che bằng khóa rỗng.

    Ca này chỉ xảy ra khi dữ liệu hỏng (có ai đó ghi vào graph không qua
    adapter, hoặc cạnh nối hai entity). Che bằng khóa rỗng nghĩa là không che
    gì - đúng kiểu mặc định fail-open mà cả Epic 1 dựng ra để chống.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node("App01", {"role": "entity"})
                await adapter.upsert_node("App02", {"role": "entity"})
                await adapter.upsert_edge(
                    "App01", "App02", {"weight": 1.0, "slot": "subject"}
                )
        with use_context(vai(policy, "tech_support", khong_gian)):
            with pytest.raises(HyperedgeKeyMissing) as loi:
                await adapter.get_edge("App01", "App02")
            assert loi.value.code == "HYPEREDGE_KEY_MISSING"
            with pytest.raises(HyperedgeKeyMissing):
                await adapter.get_node_edges("App01")

    asyncio.run(chay())


def test_ban_ghi_roi_adapter_khong_mang_space(khong_gian, policy):
    """`space` không đi vào chuỗi ngữ cảnh gửi cho LLM; khóa quyền thì ở lại."""

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            node = await adapter.get_node(id_hyperedge(THEO_ID["HE-01"]))
            canh = await adapter.get_edge(id_hyperedge(THEO_ID["HE-01"]), "App01")
        for ban_ghi in (node, canh):
            assert "space" not in ban_ghi
            assert ban_ghi[FILTER_KEY_FIELD] == filter_key("noi_bo", "runbook")
        assert node[NODE_ID_FIELD] == id_hyperedge(THEO_ID["HE-01"])

    asyncio.run(chay())


def test_id_khong_bi_thuoc_tinh_upstream_de(khong_gian, policy):
    """`node_data` mang sẵn `id` không được đè khóa MERGE đã chuẩn hóa."""

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_node(
                    '"App01"', {"role": "entity", "id": "id-rac"}
                )
        node = driver.node_tho(khong_gian, "App01")
        assert node is not None and node.props[NODE_ID_FIELD] == "App01"

    asyncio.run(chay())


# --- Cấu hình và vòng đời kết nối ------------------------------------------


def test_dung_driver_that_tu_global_config():
    """Đường dựng driver thật của story 1.7 phải có test chạy vào.

    Ba khóa cấu hình chỉ xuất hiện trong chính adapter, nên gõ sai một tên là
    thứ chỉ lộ ra khi engine chạy thật. Dựng driver không mở kết nối nào, nên
    kiểm được mà không cần container.
    """
    from neo4j import AsyncDriver

    adapter = Neo4jACLGraphStorage(
        namespace="chunk_entity_relation",
        global_config={
            "neo4j_uri": "bolt://khong-ai-goi:7687",
            "neo4j_username": "neo4j",
            "neo4j_password": "matkhau",
        },
        embedding_func=None,
    )
    assert isinstance(adapter._driver, AsyncDriver)
    assert adapter._tu_mo_driver is True


def test_thieu_mat_khau_bao_ngay_luc_dung():
    """`auth=(user, None)` chỉ hỏng ở lần gọi đầu, quá xa chỗ sửa cấu hình."""
    with pytest.raises(ValueError) as loi:
        Neo4jACLGraphStorage(
            namespace="chunk_entity_relation",
            global_config={"neo4j_uri": "bolt://khong-ai-goi:7687"},
            embedding_func=None,
        )
    assert "neo4j_password" in str(loi.value)


@pytest.mark.parametrize(
    "cau_hinh",
    [{"neo4j_health_retries": 0}, {"neo4j_health_retries": "nhieu"},
     {"neo4j_health_delay": -1}],
)
def test_knob_health_check_sai_thi_hong_luc_dung(cau_hinh):
    """`retries=0` mà không kiểm thì health-check báo sai nguyên nhân."""
    with pytest.raises(ValueError):
        dung_adapter(Neo4jGhiLai(), **cau_hinh)


def test_sai_xac_thuc_khong_thu_lai(khong_gian, policy):
    """Sai mật khẩu không tự lành theo thời gian: hỏng ngay, đúng một lần thử."""
    from neo4j.exceptions import AuthError

    async def chay():
        driver = Neo4jGhiLai(
            so_lan_chua_san_sang=99, loi_ket_noi=AuthError("sai mật khẩu")
        )
        adapter = dung_adapter(driver, neo4j_health_delay=0)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with pytest.raises(Neo4jUnavailable) as loi:
                await adapter.initialize()
        assert loi.value.code == "NEO4J_UNAVAILABLE"
        assert driver.so_lan_kiem_ket_noi == 1

    asyncio.run(chay())


def test_close_khong_dong_driver_duoc_tiem(khong_gian, policy):
    """Driver tiêm từ ngoài là của người tiêm; đóng hộ là làm hỏng hai kho kia."""

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
        await adapter.close()
        assert driver.da_dong is False
        # Cờ sẵn sàng mở lại: instance dùng tiếp phải chờ Neo4j lần nữa.
        assert adapter._da_san_sang is False

    asyncio.run(chay())
