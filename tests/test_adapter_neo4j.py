"""Adapter Neo4j: WHERE-injection và cấu trúc hai phía (story 1.4, FR-08).

Hai kịch bản `1.4-INT-001` và `1.4-INT-002` của test-design, cộng `1.6-INT-001`
(tên node lân cận đi qua tầng che). Hai lớp assert, theo thứ tự quan trọng:

1. Chính câu Cypher đã gửi. Mọi biến node trong pattern phải bị ràng cả
   `space` lẫn khóa quyền; lọc lại phía Python sau khi bản ghi đã về là đúng
   thứ FR-08 cấm, và nhìn vào kết quả thì không phân biệt được hai đường đó.
2. Nội dung kết quả, đối chiếu `tests/fixtures/oracle.py` - bộ tính kỳ vọng
   độc lập, không gọi `core/`.

Phần bản ghi node đã che, fail-closed, health-check, id dùng chung hai kho và
vòng đời kết nối nằm ở `tests/test_adapter_neo4j_che_va_ket_noi.py`.

Driver là bản giả trong `tests/gia_lap_neo4j.py`: nó lọc theo đúng điều kiện
mà câu Cypher khai, nên quên tiêm WHERE cho một biến là kết quả sai chứ không
phải một câu văn khác đi. Không mạng, không container. Phần "Cypher có hợp lệ
với Neo4j thật không" do `tests/test_adapter_neo4j_that.py` gánh.
"""

import asyncio

import pytest

from adapters.ingest_labels import IngestLabelMissing, ingest_label
from adapters.neo4j import (
    LABEL_ENTITY,
    LABEL_HYPEREDGE,
    NODE_ID_FIELD,
    SlotRoleInvalid,
)
from adapters.policy_loader import load_policy
from core.ids import normalize_id
from core.keys import FILTER_KEY_FIELD
from core.permission import use_context
from core.slots import SLOT_ROLES
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.gia_lap_neo4j import Neo4jGhiLai, canh_moi_bien_deu_bi_loc
from tests.ho_tro_neo4j import (
    BAY_METHOD_DOC,
    dung_adapter,
    goi_moi_method_doc,
    graph_da_nap,
    id_hyperedge,
    khoa_cua,
    nap_hyperedge,
)
from tests.ngu_canh import ngu_canh_ingest, vai


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

    HE-01 là runbook, L2 với `tech_support`, nên tên lân cận ra nguyên văn -
    trừ lân cận điền vào slot `owner`, thứ luôn tổng quát hóa kể cả ở L2
    (AD-9, story 1.6).
    """

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        he = THEO_ID["HE-01"]
        with use_context(vai(policy, "tech_support", khong_gian)):
            cac_cap = await adapter.get_node_edges(id_hyperedge(he))
        assert all(isinstance(c, tuple) and len(c) == 2 for c in cac_cap)
        assert {c[0] for c in cac_cap} == {id_hyperedge(he)}
        ky_vong = [
            oracle.dau_che_ky_vong(slot) if slot == "owner" else gia_tri
            for slot, gia_tri in he["slots"].items()
        ]
        assert sorted(c[1] for c in cac_cap) == sorted(ky_vong)

    asyncio.run(chay())


# --- 1.6-INT-001: tên node lân cận đi qua tầng che -------------------------


def test_1_6_int_001_get_node_edges_che_ten_lan_can_cua_slot_bi_che(
    khong_gian, policy, bang
):
    """Tên lân cận điền vào slot đang che bị che như nội dung slot (AD-9).

    Đường rò thật của Epic 1; lý do đầy đủ ở docstring `core/masking.py`. Kỳ
    vọng lấy từ oracle, nên nó không tự đúng theo code.
    """

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_node_edges(id_hyperedge(THEO_ID["HE-02"]))

    cac_cap = asyncio.run(chay())
    he = THEO_ID["HE-02"]
    phai_che = oracle.slot_phai_che(bang, "tech_support", he)
    assert phai_che == {"cause", "source", "remediation", "owner"}
    ky_vong = {
        oracle.dau_che_ky_vong(slot) if slot in phai_che else normalize_id(gia_tri)
        for slot, gia_tri in he["slots"].items()
    }
    lan_can = {c[1] for c in cac_cap}
    assert lan_can == ky_vong
    # Nói thẳng điều cần chứng minh: nguyên văn nguyên nhân không ra khỏi kho.
    for slot in phai_che:
        assert he["slots"][slot] not in lan_can, slot
    # Và phần công khai vẫn ra được, nếu không thì "che" chỉ là "chặn".
    assert he["slots"]["symptom"] in lan_can


def test_1_6_int_001_vai_l2_chi_che_lan_can_cua_owner(khong_gian, policy, bang):
    """Cùng hyperedge, vai đạt L2: chỉ lân cận `owner` bị tổng quát hóa."""

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            return await adapter.get_node_edges(id_hyperedge(THEO_ID["HE-02"]))

    cac_cap = asyncio.run(chay())
    he = THEO_ID["HE-02"]
    assert oracle.slot_phai_che(bang, "devops", he) == {"owner"}
    lan_can = {c[1] for c in cac_cap}
    assert lan_can == {
        oracle.dau_che_ky_vong("owner") if slot == "owner" else normalize_id(gia_tri)
        for slot, gia_tri in he["slots"].items()
    }
    assert he["slots"]["cause"] in lan_can
    assert he["slots"]["owner"] not in lan_can


def test_1_6_int_001_goi_tu_phia_entity_khong_che_id_hyperedge(khong_gian, policy):
    """Lân cận là node hyperedge thì không bị che, dù cạnh mang vai đang che.

    Vai slot mô tả entity *điền vào* hyperedge, nên nó chỉ có nghĩa cho lân cận
    entity - đúng câu chữ AC story 1.6, "node điền vào slot đang bị che". Node
    hyperedge không điền vào slot nào.

    Chiều này chạy thật trong sản phẩm: `operate.py:818` và `:887` đều gọi
    `get_node_edges(dp["entity_name"])` ở local mode. Che id hyperedge ở đây
    thì `operate.py:900-907` nhận `get_edge(e[0], dấu_che) -> None` rồi loại
    nguyên dòng đó, tức một fact mà vai *được* thấy ở L1 biến mất khỏi ngữ
    cảnh - đi ngược FR-12, và đi ngược im lặng.
    """
    he = THEO_ID["HE-02"]

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_node_edges(he["slots"]["cause"])

    cac_cap = asyncio.run(chay())
    # Entity "nguyên nhân" chỉ nối vào đúng hyperedge HE-02 trong fixture.
    assert [c[1] for c in cac_cap] == [id_hyperedge(he)]
    assert cac_cap[0][0] == normalize_id(he["slots"]["cause"])


def test_1_6_int_001_hai_entity_cung_slot_cho_cung_mot_dau_che(khong_gian, policy):
    """Dấu che không mang số lượng, nên hai lân cận cùng slot trùng nhau.

    Cố ý (`core/masking.py`): một dấu che có số thứ tự nói ra "có 2 nguyên nhân
    bị che", mà số lượng cũng là thông tin về nội dung bị che. Cái giá là
    `operate.py:893` gom `tuple(e)` vào một `set` nên hai cạnh này khử trùng
    còn một - ghim cả hai vế ở đây để lần sau không ai "sửa" nó thành dấu che
    có số mà không biết mình đang mua lại đường rò nào.
    """
    he = THEO_ID["HE-02"]
    nguyen_nhan_hai = "sai cấu hình timeout ở tầng cân bằng tải"

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(
                scope=he["scope"], content_type=he["content_type"]
            ):
                await adapter.upsert_node(
                    nguyen_nhan_hai,
                    {"role": "entity", "entity_type": "KHAC",
                     "description": nguyen_nhan_hai, "source_id": he["id"]},
                )
                await adapter.upsert_edge(
                    id_hyperedge(he),
                    nguyen_nhan_hai,
                    {"weight": 1.0, "source_id": he["id"], "slot": "cause"},
                )
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_node_edges(id_hyperedge(he))

    cac_cap = asyncio.run(chay())
    lan_can = [c[1] for c in cac_cap]
    assert lan_can.count(oracle.dau_che_ky_vong("cause")) == 2
    assert nguyen_nhan_hai not in lan_can
    assert he["slots"]["cause"] not in lan_can
    # Và đây là cái giá, nói thẳng: upstream khử trùng còn một cạnh.
    assert len({tuple(c) for c in cac_cap}) == len(set(lan_can))


def test_moi_lan_can_tra_nguoc_duoc_bang_get_node(khong_gian, policy):
    """Hợp đồng mà `operate.py` dựa vào: `e[1]` luôn tra ngược được.

    Hai chỗ tiêu thụ lọc `None` trước khi dùng (`operate.py:908`, `:830`),
    nhưng `_find_most_related_entities_from_relationships` thì không. Từ khi
    `get_node` nhận ra dấu che ở vị trí id, mọi lân cận trả ra đều tra được -
    kể cả lân cận đã che. Viết ban đầu làm tripwire `xfail(strict=True)` trỏ
    sang story 1.7; sonlm yêu cầu trả nợ ngay trong story 1.6 nên nó thành một
    assert thật.
    """

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            cac_cap = await adapter.get_node_edges(id_hyperedge(THEO_ID["HE-02"]))
            return [(c[1], await adapter.get_node(c[1])) for c in cac_cap]

    tra_nguoc = asyncio.run(chay())
    khong_tra_duoc = [ten for ten, node in tra_nguoc if node is None]
    assert not khong_tra_duoc, f"lân cận không tra ngược được: {khong_tra_duoc}"


