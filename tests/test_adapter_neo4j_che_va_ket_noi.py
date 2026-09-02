"""Adapter Neo4j: bản ghi đã che, fail-closed và vòng đời kết nối (story 1.4).

Nửa thứ hai của bộ test story 1.4; nửa đầu (`1.4-INT-001`, `1.4-INT-002`,
`1.6-INT-001`) nằm ở `tests/test_adapter_neo4j.py`. Tách ra khi file gốc vượt
ngưỡng 1000 dòng.

Phần này ghim bốn nhóm: hình dạng bản ghi node khi nội dung không được phép ra
(khoản 38 và 39), fail-closed toàn tuyến cùng điểm gọi tầng che
(`1.4-INT-003`, `1.4-INT-004`), health-check chờ Neo4j sẵn sàng
(`1.4-INT-005`), và id chuẩn hóa dùng chung hai kho (`1.4-UNIT-001`) cùng cấu
hình, vòng đời kết nối.

Driver là bản giả trong `tests/gia_lap_neo4j.py`; không mạng, không container.
"""

import asyncio

import pytest

from adapters.ingest_labels import IngestOutsideSystemContext, ingest_label
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
)
from adapters.policy_loader import load_policy
from core.ids import SPACE_MAX_LEN, normalize_id, point_id
from core.keys import FILTER_KEY_FIELD, filter_key
from core.masking import dau_che
from core.permission import PermissionContextMissing, use_context, user_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import THEO_ID
from tests.gia_lap_neo4j import Neo4jGhiLai, canh_moi_bien_deu_bi_loc
from tests.ho_tro_neo4j import (
    BAY_METHOD_DOC,
    dung_adapter,
    graph_da_nap,
    id_hyperedge,
    khoa_cua,
    nap_hyperedge,
)
from tests.ngu_canh import ngu_canh_ingest, vai


# --- Khoản 38 + 39: bản ghi node khi nội dung không được phép ra ------------


def test_khoan_38_get_node_tren_dau_che_tra_node_da_che_chu_khong_None(
    khong_gian, policy
):
    """Dấu che ở vị trí id: `get_node` trả node đã che, đủ hình dạng upstream đọc.

    `operate.py:1036-1039` mang thẳng `e[1]` đi hỏi `get_node` rồi trải
    `{**n, "entity_name": k, "rank": d}` **không lọc `None`** - khác hai chỗ
    tiêu thụ kia. Test mô phỏng đúng dòng đó để chứng minh nó không còn nổ.
    """

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_node(dau_che("cause"))

    node = asyncio.run(chay())
    assert node is not None
    # Hai trường upstream đọc để dựng bảng Entities (`operate.py:774-784`).
    assert node["entity_type"] == dau_che("cause")
    assert node["description"] == dau_che("cause")
    # Không mang `source_id`: đó là đường với tới chunk nguồn.
    assert "source_id" not in node
    assert FILTER_KEY_FIELD not in node
    # Chính dòng của `operate.py:1036-1039`, không diễn giải lại.
    dong = {**node, "entity_name": dau_che("cause"), "rank": 0}
    assert dong["entity_name"] == dau_che("cause")


def test_khoan_38_ten_entity_that_khong_bi_nham_la_dau_che(khong_gian, policy):
    """Nhận diện bằng dựng lại, không bằng `startswith("[")`.

    Một tên entity thật mở đầu bằng dấu ngoặc vuông mà bị nhận nhầm là dấu che
    thì một fact có thật biến mất khỏi ngữ cảnh, thay bằng một node rỗng.
    """
    he = THEO_ID["HE-01"]
    ten_giong_dau_che = "[cause:khong phai dau che]"

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(
                scope=he["scope"], content_type=he["content_type"]
            ):
                await adapter.upsert_node(
                    ten_giong_dau_che,
                    {"role": "entity", "entity_type": "KHAC",
                     "description": "mô tả thật", "source_id": he["id"]},
                )
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_node(ten_giong_dau_che)

    node = asyncio.run(chay())
    assert node is not None
    assert node["entity_type"] == "KHAC"
    assert node["source_id"] == he["id"]


def test_khoan_39_mo_ta_entity_chi_ra_nguyen_van_khi_vai_dat_l2(
    khong_gian, policy, bang
):
    """`description` của entity là văn bản viết lại từ giá trị slot (NFR-06).

    HE-02 là `bao_cao_su_co`: L1 với `tech_support`, L2 với `devops`. Ngưỡng
    lấy từ oracle chứ không từ `core/`, nên assert không tự đúng theo code.
    """
    he = THEO_ID["HE-02"]
    ten_entity = he["slots"]["symptom"]  # slot công khai, không bị che theo slot

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        ket = {}
        for ten_vai in ("tech_support", "devops"):
            with use_context(vai(policy, ten_vai, khong_gian)):
                ket[ten_vai] = await adapter.get_node(ten_entity)
        return ket

    ket = asyncio.run(chay())
    duoc_phep = oracle.allowed_keys_ky_vong(bang, "tech_support")["entities"]
    assert khoa_cua(he) not in duoc_phep, "fixture phải giữ ca L1 với vai này"
    assert khoa_cua(he) in oracle.allowed_keys_ky_vong(bang, "devops")["entities"]

    assert ket["tech_support"]["description"] == "[description:l2_only]"
    assert ket["devops"]["description"] == ten_entity
    # Chỉ `description` bị chạm: id node vẫn ra, và tập khóa không đổi.
    assert ket["tech_support"][NODE_ID_FIELD] == normalize_id(ten_entity)
    assert set(ket["tech_support"]) == set(ket["devops"])


def test_khoan_39_node_vai_hyperedge_khong_bi_luat_mo_ta_cham(khong_gian, policy):
    """Node hyperedge không có `description` (`operate.py:153`), nên không bị chạm."""

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_node(id_hyperedge(THEO_ID["HE-02"]))

    node = asyncio.run(chay())
    assert node is not None
    assert node["role"] == "hyperedge"
    assert "description" not in node
    assert node["source_id"] == "HE-02"


def test_khoan_39_ngu_canh_he_thong_van_doc_mo_ta_nguyen_van(khong_gian, policy):
    """Ingest phải thấy mô tả thật: `_merge_nodes_then_upsert` ghi lại chính nó."""
    he = THEO_ID["HE-02"]
    ten_entity = he["slots"]["symptom"]

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await adapter.get_node(ten_entity)

    assert asyncio.run(chay())["description"] == ten_entity


def test_get_node_edges_khong_ke_lan_can_ngoai_quyen(khong_gian, policy):
    """Lân cận ngoài quyền vắng mặt trong danh sách cạnh, không chỉ vắng nội dung.

    Setup đổi so với story 1.4 vì luật hợp nhất khóa của story 2.1. Bản cũ hỏi
    từ phía `App01` - một entity nằm trên cả HE-01 (runbook) lẫn HE-02
    (bao_cao_su_co) - và dựa vào last-write-wins để `App01` mang khóa runbook.
    Nay `App01` mang khóa hạn chế nhất trong hai nguồn của nó, nên với bảng nhị
    phân `tech_support` không thấy chính `App01` và câu hỏi cũ trả rỗng vì một
    lý do khác hẳn. Bản mới hỏi từ phía node hyperedge runbook và nối vào đó
    một entity chỉ thuộc HE-02, đúng hình dạng "node thấy được, lân cận thì
    không" mà test này đo.

    Hệ quả của luật hợp nhất cũng được ghim luôn ở đây: `App01` biến khỏi danh
    sách lân cận của chính hyperedge runbook. Đó là giá phải trả của "hạn chế
    nhất" (FR-11) và nó phải nhìn thấy được, không nằm im trong một docstring.
    """
    policy_nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)
    chi_cua_he_02 = THEO_ID["HE-02"]["slots"]["cause"]

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy_nhi_phan)):
            for he in (THEO_ID["HE-02"], THEO_ID["HE-01"]):
                with ingest_label(
                    scope=he["scope"], content_type=he["content_type"]
                ):
                    await nap_hyperedge(adapter, he)
            # Cạnh nối thêm dưới nhãn runbook: hyperedge runbook có một lân cận
            # mang khóa bao_cao_su_co, tức ngoài quyền của `tech_support`.
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert_edge(
                    "rel-HE-01", chi_cua_he_02, {"weight": 1.0, "slot": "cause"}
                )
        with use_context(vai(policy_nhi_phan, "tech_support", khong_gian)):
            cac_cap = await adapter.get_node_edges("rel-HE-01")
        return [c[1] for c in cac_cap]

    lan_can = asyncio.run(chay())
    assert chi_cua_he_02 not in lan_can, "lân cận ngoài quyền phải vắng mặt hẳn"
    assert "App01" not in lan_can, (
        "App01 đa nguồn nay mang khóa hạn chế nhất, nên nó cũng ngoài quyền"
    )
    # Các entity chỉ thuộc HE-01 thì vẫn còn: cửa lọc là khóa của từng lân cận,
    # không phải một phép cắt cả danh sách.
    assert THEO_ID["HE-01"]["slots"]["condition"] in lan_can


def test_ngu_canh_he_thong_doc_duoc_hyperedge_da_hop_nhat_ra_khong_khoa(
    khong_gian, policy
):
    """Ingest phải đọc lại được một hyperedge vừa hợp nhất ra "không khóa".

    Hồi quy cho một lỗi mà story 2.1 tự tạo ra và bộ test adapter không bắt
    được - nó lộ ra ở đường `ainsert` thật. `_khoa_hyperedge` fail-closed khi
    node hyperedge không mang khóa, đúng như nó phải làm cho một vai người
    dùng; nhưng nó được gọi **trước** cửa che, nên nó nổ cả dưới cờ system, nơi
    không có gì để che. Hậu quả: `extract_entities` đọc lại cạnh của chính
    hyperedge nó vừa ghi (`_merge_edges_then_upsert` -> `get_edge`) và cả đợt
    nạp hỏng - tức luật hợp nhất tự chặn đường ingest của mình.

    Đường vai người dùng không đổi: node không khóa vẫn bị mệnh đề
    `filter_key IN $keys` lọc ra trước khi tới được cửa đó.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            # Cùng một hyperedge vào từ hai scope: node của nó thành không khóa.
            for scope, loai in (
                ("noi_bo", "runbook"),
                ("khach_hang_a", "bao_cao_su_co"),
            ):
                with ingest_label(scope=scope, content_type=loai):
                    await adapter.upsert_node("rel-X", {"role": "hyperedge"})
                    await adapter.upsert_node("App01", {"role": "entity"})
                    await adapter.upsert_edge(
                        "rel-X", "App01", {"weight": 1.0, "slot": "subject"}
                    )
            khoa = await adapter.khoa_hien_co(["rel-X"])
            # Ba đường đọc mà `extract_entities` đi qua, dưới cờ system.
            return (
                khoa["rel-X"],
                await adapter.get_node("rel-X"),
                await adapter.get_edge("rel-X", "App01"),
                await adapter.get_node_edges("rel-X"),
            )

    khoa, node, canh, lan_can = asyncio.run(chay())
    assert khoa is None, "tiền đề của test: hyperedge đã hợp nhất ra không khóa"
    assert node is not None and FILTER_KEY_FIELD not in node
    assert canh is not None
    assert [c[1] for c in lan_can] == ["App01"]


def test_vai_nguoi_dung_van_khong_toi_duoc_hyperedge_khong_khoa(
    khong_gian, policy
):
    """Chiều ngược của test trên: nới cửa cho cờ system không nới cho vai nào.

    Cặp đối chứng bắt buộc. Nếu sửa "đọc thô không cần khóa che" mà lỡ nới cả
    đường vai người dùng thì một hyperedge đa nguồn khác scope trở thành thứ
    mọi vai đọc được - đúng ngược với thứ luật hợp nhất dựng ra.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            for scope, loai in (
                ("noi_bo", "runbook"),
                ("khach_hang_a", "bao_cao_su_co"),
            ):
                with ingest_label(scope=scope, content_type=loai):
                    await adapter.upsert_node("rel-X", {"role": "hyperedge"})
                    await adapter.upsert_node("App01", {"role": "entity"})
                    await adapter.upsert_edge(
                        "rel-X", "App01", {"weight": 1.0, "slot": "subject"}
                    )
        do = {}
        for ten_vai in ("tech_support", "devops"):
            with use_context(vai(policy, ten_vai, khong_gian)):
                do[ten_vai] = (
                    await adapter.get_node("rel-X"),
                    await adapter.get_edge("rel-X", "App01"),
                    await adapter.get_node_edges("rel-X"),
                    await adapter.node_degree("rel-X"),
                )
        return do

    do = asyncio.run(chay())
    for ten_vai, (node, canh, lan_can, bac) in do.items():
        assert node is None, ten_vai
        assert canh is None, ten_vai
        assert lan_can == [], ten_vai
        assert bac == 0, ten_vai


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

    # Ca cuối dài hơn giới hạn đúng một ký tự, suy từ hằng của `core/`.
    for xau in ("khong gian", "synth`", "1_synth", "a" * (SPACE_MAX_LEN + 1)):
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


def test_ghi_duoi_ngu_canh_vai_bi_tu_choi(khong_gian, policy):
    """Ghi tri thức chỉ chạy dưới ngữ cảnh hệ thống của ingest (AD-3).

    Đường ghi là chỗ duy nhất *đặt* khóa quyền. Nếu một ngữ cảnh vai ghi được
    thì chính người hỏi quyết định nhãn quyền của dữ liệu, và `space` cũng lấy
    theo ngữ cảnh đó - thành một đường ghi chéo không gian.
    """

    async def chay():
        driver = Neo4jGhiLai()
        adapter = dung_adapter(driver)
        with use_context(vai(policy, "devops", khong_gian)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(IngestOutsideSystemContext) as loi:
                    await adapter.upsert_node("rel-X", {"role": "hyperedge"})
                assert loi.value.code == "INGEST_OUTSIDE_SYSTEM_CONTEXT"
                with pytest.raises(IngestOutsideSystemContext):
                    await adapter.upsert_edge("rel-X", "App01", {"weight": 1.0})
        assert driver.dem_node() == 0 and driver.dem_canh() == 0

    asyncio.run(chay())


def test_neo4j_rot_giua_phien_thi_mo_lai_cua_health_check(khong_gian, policy):
    """Kết nối đứt giữa phiên: lời gọi sau phải chờ lại, không dội lỗi thô mãi."""
    from neo4j.exceptions import ServiceUnavailable

    class DriverRot(Neo4jGhiLai):
        def __init__(self):
            super().__init__()
            self.no_khi_chay = True

        def session(self, **kw):
            if self.no_khi_chay:
                self.no_khi_chay = False
                raise ServiceUnavailable("giả lập: mất kết nối giữa phiên")
            return super().session(**kw)

    async def chay():
        driver = DriverRot()
        adapter = dung_adapter(driver, neo4j_health_delay=0)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with pytest.raises(ServiceUnavailable):
                await adapter.initialize()
            assert adapter._da_san_sang is False
            # Lời gọi sau kiểm kết nối lại rồi chạy tiếp.
            await adapter.initialize()
        assert driver.so_lan_kiem_ket_noi == 2
        assert adapter._da_san_sang is True

    asyncio.run(chay())
