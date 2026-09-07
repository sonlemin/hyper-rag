"""Endpoint đồ thị theo quyền (story 3.7, FR-19, AD-8, AD-9).

Đặc tả viết trước cơ chế (FR-27): mọi hàng I/O Matrix của story nằm ở đây, cộng
bốn mệnh đề mà không hàng nào phát biểu được một mình.

- **Server lọc lại toàn bộ.** Tập hyperedge, mức và tập node che của mỗi vai
  chấm bằng oracle độc lập (`tests/fixtures/oracle.py`), và câu Cypher đã gửi
  phải ràng cả ba biến (`canh_moi_bien_deu_bi_loc`). Không assert nào đọc
  `answer` (chốt brief §6).
- **Ngoài quyền là vắng mặt, không phân biệt được.** Id không tồn tại, id L0
  và danh sách rỗng cho ba thân response byte-identical.
- **Đỉnh không khóa bị loại ở đồ thị** (khác ngữ cảnh LLM, nơi nó được che
  cứng): kiểm bằng ca nạp thêm một hyperedge làm một entity hợp nhất khác
  scope, và hyperedge chỉ có đỉnh ấy vắng cả vòng.
- **Không lời gọi LLM, không embedding, không hàng audit mới** trên đường này.

Ba lớp như `tests/test_trich_dan.py`: hàm thuần (`adapters/do_thi.py`,
serializer), engine cổng M1 thật (ba adapter, LLM giả), HTTP với `EngineGia` và
với engine M1 thật qua hai tài khoản seed.
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

from adapters.do_thi import (
    KHOA_CANH,
    KHOA_DONG_ADAPTER,
    KHOA_NODE_ENTITY,
    KHOA_NODE_HYPEREDGE,
    KIND_ENTITY,
    KIND_HYPEREDGE,
    CanhDoThi,
    DoThi,
    DoThiNgoaiQuyen,
    NodeEntity,
    NodeHyperedge,
    chuan_hoa_ids,
    do_thi_tu_dict,
    dung_do_thi,
    id_node_che,
)
from adapters.neo4j import Neo4jUnavailable
from adapters.trich_dan import TrichDanNgoaiQuyen
from api import do_thi as api_do_thi
from api import main as api_main
from api.hoi_dap import (
    KHOA_ENVELOPE,
    MA_DANH_SACH_ID_QUA_DAI,
    MA_KHO_KHONG_SAN_SANG,
    MA_THAN_YEU_CAU_LA,
    MA_TRICH_DAN_NGOAI_QUYEN,
    SO_ID_TOI_DA,
    dict_do_thi,
    dung_envelope,
    graph_rong,
)
from api.main import MA_LOI_KHONG_XAC_DINH
from api.che_do_do import BIEN_CHE_DO_DO
from api.xac_thuc import BIEN_KHOA_KY
from core.facts import cau_fact
from core.audit import EVENT_EMBEDDING_COST, EVENT_LLM_COST, EVENT_QUERY, EVENT_REFUSAL
from core.masking import MASKED_READ_METHODS
from core.permission import use_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.gia_lap_neo4j import canh_moi_bien_deu_bi_loc
from tests.ho_tro_m1 import cong_m1, ten_hyperedge_ky_vong
from tests.nap_kho import ten_hyperedge
from tests.ngu_canh import ngu_canh_ingest, vai
from tests.test_xac_thuc import KHOA_TEST, MAT_KHAU, TEN_GO, AuditGia, EngineGia, KhoGia, _dong

GOC = Path(__file__).resolve().parent.parent
ADR_018 = GOC / "docs" / "adr" / "ADR-018-do-thi-theo-quyen.md"

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

HAI_VAI = ("devops", "tech_support")
META = {"role": "devops", "space": "synth", "policy_version": "v"}


# --- Lớp 1: hàm thuần ------------------------------------------------------------


def test_do_thi_cua_nam_trong_danh_sach_dong_cua_tang_che():
    """AD-9: method đọc mới trả tên entity phải khai vào `MASKED_READ_METHODS`."""
    assert "do_thi_cua" in MASKED_READ_METHODS


def _dong_adapter(id_he, khoa, slot, ten, bi_che=False) -> dict:
    return {"id_hyperedge": id_he, "khoa": khoa, "slot": slot, "ten_da_che": ten, "bi_che": bi_che}


def test_dung_do_thi_thu_tu_tat_dinh_va_node_che_theo_cap(policy, khong_gian):
    """Hyperedge theo id vào, entity theo lần xuất hiện, edge theo (hyperedge, SLOT_ROLES, label).

    Hai hyperedge cùng che một entity thật ra **hai** node che, id
    `{hyperedge}#{slot}`; entity thấy được là **một** node chung. Hai entity cùng
    bị che ở một vai của một hyperedge ra đúng một node và một cạnh.
    """
    ctx = vai(policy, "devops", khong_gian)
    k_l2, k_l1 = "noi_bo:runbook", "noi_bo:bi_mat_ha_tang"
    dong = [
        _dong_adapter("B", k_l1, "remediation", "[remediation:masked]", True),
        _dong_adapter("B", k_l1, "owner", "[owner:DevOps]", True),
        _dong_adapter("B", k_l1, "subject", "App01"),
        _dong_adapter("B", k_l1, "remediation", "[remediation:masked]", True),
        _dong_adapter("A", k_l2, "owner", "[owner:DevOps]", True),
        _dong_adapter("A", k_l2, "condition", "b-điều kiện"),
        _dong_adapter("A", k_l2, "condition", "a-điều kiện"),
        _dong_adapter("A", k_l2, "subject", "App01"),
    ]
    dt = dung_do_thi(ctx, ("A", "B"), dong)
    assert [n.id for n in dt.nodes] == [
        "A", "App01", "a-điều kiện", "b-điều kiện", "A#owner",
        "B", "B#remediation", "B#owner",
    ]
    assert [(n.id, n.level) for n in dt.nodes if isinstance(n, NodeHyperedge)] == [("A", "L2"), ("B", "L1")]
    # Label dựng từ đúng các cạnh đã khử trùng, theo `SLOT_ROLES`, giá trị đã che.
    assert _he_theo_id(dt)["A"].label == cau_fact({"subject": ["App01"], "condition": ["a-điều kiện", "b-điều kiện"], "owner": ["[owner:DevOps]"]})
    assert _he_theo_id(dt)["B"].label == cau_fact({"subject": ["App01"], "remediation": ["[remediation:masked]"], "owner": ["[owner:DevOps]"]})
    assert [c for c in dt.edges] == [
        CanhDoThi("A", "App01", "subject"),
        CanhDoThi("A", "a-điều kiện", "condition"),
        CanhDoThi("A", "b-điều kiện", "condition"),
        CanhDoThi("A", "A#owner", "owner"),
        CanhDoThi("B", "App01", "subject"),
        CanhDoThi("B", "B#remediation", "remediation"),
        CanhDoThi("B", "B#owner", "owner"),
    ]
    che = {n.id: n for n in dt.nodes if isinstance(n, NodeEntity) and n.masked}
    assert set(che) == {"A#owner", "B#remediation", "B#owner"}
    assert che["A#owner"].label == che["B#owner"].label == "[owner:DevOps]"
    assert id_node_che("A", "owner") == "A#owner"
    with pytest.raises(ValueError):
        id_node_che("A", "la")


def test_dung_do_thi_id_vang_khong_loi_va_rong_la_do_thi_rong(policy, khong_gian):
    """Khác citation: id vào mà adapter không thấy **không** là lỗi, chỉ vắng mặt."""
    ctx = vai(policy, "devops", khong_gian)
    assert dung_do_thi(ctx, ("x", "y"), []) == DoThi()
    assert dung_do_thi(ctx, (), []) == DoThi()
    dt = dung_do_thi(ctx, ("x", "A"), [_dong_adapter("A", "noi_bo:runbook", "subject", "App01")])
    assert [n.id for n in dt.nodes] == ["A", "App01"]


def test_dung_do_thi_tu_choi_ngu_canh_he_thong(policy, khong_gian):
    from core.permission import SystemContextRawRead

    with pytest.raises(DoThiNgoaiQuyen) as loi:
        dung_do_thi(ngu_canh_ingest(khong_gian, policy), ("A",), [])
    assert isinstance(loi.value, TrichDanNgoaiQuyen)
    assert loi.value.code == MA_TRICH_DAN_NGOAI_QUYEN
    assert not isinstance(loi.value, SystemContextRawRead)


@pytest.mark.parametrize(
    "dong",
    [
        _dong_adapter("A", "khong-tach", "subject", "x"),
        _dong_adapter("A", "noi_bo:runbook", "vai_la", "x"),
        {k: v for k, v in _dong_adapter("A", "noi_bo:runbook", "subject", "x").items() if k != "bi_che"},
    ],
    ids=["khoa_khong_tach", "vai_la", "thieu_khoa_dong"],
)
def test_du_lieu_kho_hong_ra_ma_on_dinh(policy, khong_gian, dong):
    ctx = vai(policy, "devops", khong_gian)
    with pytest.raises(DoThiNgoaiQuyen):
        dung_do_thi(ctx, ("A",), [dong])


def test_dung_do_thi_khoa_ngoai_quyen_la_fail_closed(policy, khong_gian):
    """Một dòng mang khóa vai không thấy tới được đây là filter hỏng: `core/` dội, không che bừa."""
    from core.masking import MaskItemOutOfPermission

    ctx = vai(policy, "tech_support", khong_gian)
    with pytest.raises(MaskItemOutOfPermission):
        dung_do_thi(ctx, ("A",), [_dong_adapter("A", "noi_bo:bi_mat_ha_tang", "subject", "x")])


@pytest.mark.parametrize(
    "dong",
    [
        [_dong_adapter("A", "noi_bo:runbook", "subject", "A")],
        [_dong_adapter("A", "noi_bo:runbook", "owner", "[owner:DevOps]", True),
         _dong_adapter("A", "noi_bo:runbook", "subject", "A#owner")],
        [_dong_adapter("A", "noi_bo:runbook", "subject", "")],
        [_dong_adapter("A", "noi_bo:runbook", "subject", None)],
        [_dong_adapter("A", "noi_bo:runbook", None, "x")],
    ],
    ids=["entity_trung_id_hyperedge", "entity_trung_id_node_che", "ten_rong", "ten_none", "slot_none"],
)
def test_va_cham_id_va_dong_hong_ra_ma_on_dinh(policy, khong_gian, dong):
    """Entity mang id của hyperedge, hay tên dạng `<he>#<slot>`, hay tên rỗng: `DoThiNgoaiQuyen`, không `ValueError` trần."""
    ctx = vai(policy, "devops", khong_gian)
    with pytest.raises(DoThiNgoaiQuyen) as loi:
        dung_do_thi(ctx, ("A",), dong)
    assert not isinstance(loi.value, ValueError)


def test_chuan_hoa_ids_khu_trung_giu_thu_tu():
    assert chuan_hoa_ids(["HE-01", " HE-01 ", '"HE-01"', "he-01", "HE-02"]) == ("HE-01", "he-01", "HE-02")
    with pytest.raises(ValueError):
        chuan_hoa_ids(["  "])
    with pytest.raises(TypeError):
        chuan_hoa_ids([1])


def test_do_thi_tu_kiem_id_trung_va_canh_lo_lung():
    he = NodeHyperedge("A", "nhãn", "L2", "noi_bo", "runbook")
    e = NodeEntity("x", "x", False)
    with pytest.raises(ValueError):
        DoThi(nodes=(he, NodeEntity("A", "A", False)), edges=())
    with pytest.raises(ValueError):
        DoThi(nodes=(he, e), edges=(CanhDoThi("A", "y", "subject"),))
    with pytest.raises(ValueError):
        DoThi(nodes=(he, e), edges=(CanhDoThi("x", "x", "subject"),))
    with pytest.raises(ValueError):
        DoThi(nodes=(he, e), edges=(CanhDoThi("A", "x", "subject"),) * 2)
    with pytest.raises(ValueError):
        NodeHyperedge("A", "nhãn", "L0", "noi_bo", "runbook")
    with pytest.raises(ValueError):
        NodeHyperedge("A", "", "L2", "noi_bo", "runbook")
    with pytest.raises(ValueError):
        CanhDoThi("A", "x", "la")
    assert tuple(KHOA_DONG_ADAPTER) == ("id_hyperedge", "khoa", "slot", "ten_da_che", "bi_che")


def _dt_mau() -> DoThi:
    return DoThi(
        nodes=(
            NodeHyperedge("A", "chủ thể: App01; nguyên nhân: [cause:masked]", "L1", "noi_bo", "bao_cao_su_co"),
            NodeEntity("App01", "App01", False),
            NodeEntity("A#cause", "[cause:masked]", True),
        ),
        edges=(CanhDoThi("A", "App01", "subject"), CanhDoThi("A", "A#cause", "cause")),
    )


def test_do_thi_tu_dict_dung_lai_dung_do_thi():
    dt = _dt_mau()
    assert do_thi_tu_dict(dict_do_thi(dt)) == dt
    with pytest.raises(ValueError):
        do_thi_tu_dict({"nodes": []})


def test_dict_do_thi_dung_khoa_dong_va_thu_tu():
    g = dict_do_thi(_dt_mau())
    assert list(g) == ["nodes", "edges"]
    assert tuple(g["nodes"][0]) == KHOA_NODE_HYPEREDGE == ("id", "kind", "label", "level", "scope", "content_type")
    assert g["nodes"][0]["kind"] == KIND_HYPEREDGE
    assert tuple(g["nodes"][1]) == KHOA_NODE_ENTITY and g["nodes"][1]["kind"] == KIND_ENTITY
    assert g["nodes"][2] == {"id": "A#cause", "kind": "entity", "label": "[cause:masked]", "masked": True}
    assert [tuple(c) for c in g["edges"]] == [KHOA_CANH] * 2
    assert dung_envelope(answer=None, refused=False, citations=[], graph=g, meta=META)["graph"] == g
    assert dung_envelope(answer=None, refused=False, citations=[], graph=graph_rong(), meta=META)["graph"] == graph_rong()


def _g(**sua) -> dict:
    g = dict_do_thi(_dt_mau())
    for k, v in sua.items():
        g[k] = v
    return g


@pytest.mark.parametrize(
    "graph",
    [
        _g(nodes=[{**dict_do_thi(_dt_mau())["nodes"][0], "source_id": "c"}] + dict_do_thi(_dt_mau())["nodes"][1:]),
        _g(nodes=[{k: v for k, v in dict_do_thi(_dt_mau())["nodes"][0].items() if k != "level"}] + dict_do_thi(_dt_mau())["nodes"][1:]),
        _g(nodes=[{**dict_do_thi(_dt_mau())["nodes"][0], "level": "L0"}] + dict_do_thi(_dt_mau())["nodes"][1:]),
        _g(nodes=[{**dict_do_thi(_dt_mau())["nodes"][0], "kind": "chunk"}] + dict_do_thi(_dt_mau())["nodes"][1:]),
        _g(nodes=dict_do_thi(_dt_mau())["nodes"] + [{"id": "App01", "kind": "entity", "label": "App01", "masked": False}]),
        _g(nodes=dict_do_thi(_dt_mau())["nodes"][:1] + [{**dict_do_thi(_dt_mau())["nodes"][1], "description": "x"}] + dict_do_thi(_dt_mau())["nodes"][2:]),
        _g(nodes=dict_do_thi(_dt_mau())["nodes"][:1] + [{**dict_do_thi(_dt_mau())["nodes"][1], "masked": "no"}] + dict_do_thi(_dt_mau())["nodes"][2:]),
        _g(edges=dict_do_thi(_dt_mau())["edges"] + [{"source": "A", "target": "la", "slot": "subject"}]),
        _g(edges=dict_do_thi(_dt_mau())["edges"] + [{"source": "App01", "target": "A", "slot": "subject"}]),
        _g(edges=[{**dict_do_thi(_dt_mau())["edges"][0], "weight": 1.0}]),
        _g(edges=[{**dict_do_thi(_dt_mau())["edges"][0], "slot": "la"}]),
        _g(nodes="x"),
        _g(nodes=["A"]),
        {"nodes": [], "edges": [], "bi_loai": 0},
    ],
    ids=["he_thua_khoa", "he_thieu_khoa", "l0", "kind_la", "id_trung", "entity_thua_khoa",
         "masked_khong_bool", "canh_dich_vang", "canh_nguoc_chieu", "canh_thua_khoa", "canh_vai_la",
         "nodes_khong_list", "node_khong_dict", "graph_thua_khoa"],
)
def test_serializer_tu_choi_graph_sai_hinh(graph):
    """Serializer là chỗ duy nhất canh hình dạng: mọi lệch là `ValueError` tại `dung_envelope`."""
    with pytest.raises(ValueError):
        dung_envelope(answer=None, refused=False, citations=[], graph=graph, meta=META)


def test_kiem_danh_sach_id_khu_trung_va_hai_ma_loi():
    from api.hoi_dap import LoiHoiDap

    assert api_do_thi.kiem_danh_sach_id(["a", "b", "a", " a "]) == ["a", "b", " a "]
    assert api_do_thi.kiem_danh_sach_id([]) == []
    with pytest.raises(LoiHoiDap) as loi:
        api_do_thi.kiem_danh_sach_id(["a"] * (SO_ID_TOI_DA + 1))
    assert loi.value.ma == MA_DANH_SACH_ID_QUA_DAI
    assert api_do_thi.kiem_danh_sach_id(["a"] * SO_ID_TOI_DA) == ["a"]
    for xau in (["a", ""], ["a", "  "], ["a", 1], "a", None):
        with pytest.raises(LoiHoiDap) as loi:
            api_do_thi.kiem_danh_sach_id(xau)
        assert loi.value.ma == MA_THAN_YEU_CAU_LA


# --- Lớp 2: engine cổng M1 thật ----------------------------------------------------


def _engine(workspace_dir, khong_gian, policy, them=()):
    from tests.gia_lap_llm import LLMGia
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine
    from tests.nap_kho import nap_ba_kho

    if not them:
        return asyncio.run(cong_m1(workspace_dir, khong_gian, policy))
    client, driver, llm = QdrantGhiLai(), Neo4jGhiLai(), LLMGia()
    engine = dung_engine(workspace_dir, client, driver, llm)
    asyncio.run(nap_ba_kho(engine, khong_gian=khong_gian, policy=policy, them=them))
    client.xoa_nhat_ky()
    driver.xoa_nhat_ky()
    llm.xoa_nhat_ky()
    engine.so_audit.xoa()
    return engine, client, driver, llm


BON_ID = tuple(ten_hyperedge(he) for he in HYPEREDGES)


def _do_thi(engine, ngu_canh, ids=BON_ID) -> DoThi:
    async def chay():
        with use_context(ngu_canh):
            return await engine.do_thi(ids)

    return asyncio.run(chay())


def _he_theo_id(dt: DoThi) -> dict[str, NodeHyperedge]:
    return {n.id: n for n in dt.nodes if isinstance(n, NodeHyperedge)}


def _entity_theo_id(dt: DoThi) -> dict[str, NodeEntity]:
    return {n.id: n for n in dt.nodes if isinstance(n, NodeEntity)}


def _canh_cua(dt: DoThi, id_he: str) -> list[CanhDoThi]:
    return [c for c in dt.edges if c.source == id_he]


def _ky_vong_mot_he(bang, ten_vai, he) -> tuple[dict[str, str], dict[str, str]]:
    """(vai không che -> tên thật, vai che -> dấu che kỳ vọng) của một hyperedge, từ oracle."""
    che = oracle.slot_phai_che(bang, ten_vai, he)
    thay = {v: g for v, g in he["slots"].items() if v not in che}
    dau = {v: oracle.dau_che_ky_vong(v, he["content_type"]) for v in che}
    return thay, dau


def _chac_khop_oracle(dt: DoThi, bang, ten_vai) -> None:
    """Tập hyperedge, mức, node che và node thật của một vai bằng đúng oracle."""
    he_thay = _he_theo_id(dt)
    assert set(he_thay) == ten_hyperedge_ky_vong(bang, ten_vai), ten_vai
    entity = _entity_theo_id(dt)
    for he in HYPEREDGES:
        ten = ten_hyperedge(he)
        if ten not in he_thay:
            continue
        node = he_thay[ten]
        assert node.level == oracle.muc_ky_vong(bang, ten_vai, he["content_type"])
        assert (node.scope, node.content_type) == (he["scope"], he["content_type"])
        thay, dau = _ky_vong_mot_he(bang, ten_vai, he)
        canh = {c.slot: c.target for c in _canh_cua(dt, ten)}
        assert set(canh) == set(he["slots"]), f"{ten_vai}/{ten}: mọi vai có mặt đều có cạnh"
        _chac_label_tu_chinh_do_thi(dt, node)
        for v, dau_che in dau.items():
            assert dau_che in node.label and he["slots"][v] not in node.label, f"{ten_vai}/{ten}: label lộ vai {v}"
        for v, gia_tri in thay.items():
            assert canh[v] == gia_tri and entity[gia_tri] == NodeEntity(gia_tri, gia_tri, False)
        for v, dau_che in dau.items():
            assert canh[v] == id_node_che(ten, v)
            assert entity[canh[v]] == NodeEntity(canh[v], dau_che, True)


def _chac_label_tu_chinh_do_thi(dt: DoThi, node: NodeHyperedge) -> None:
    """Label bằng `cau_fact` tính lại từ chính các edge và node entity của đồ thị."""
    entity = _entity_theo_id(dt)
    theo_vai: dict[str, list[str]] = {}
    for c in _canh_cua(dt, node.id):
        theo_vai.setdefault(c.slot, []).append(entity[c.target].label)
    assert node.label == cau_fact(theo_vai), node.id


def _khong_lo_gia_tri_bi_che(dt: DoThi, bang, ten_vai) -> None:
    """Không một giá trị slot bị che (hay của hyperedge vắng) nào xuất hiện trong thân JSON."""
    van_ban = json.dumps(dict_do_thi(dt), ensure_ascii=False)
    thay = set(ten_hyperedge_ky_vong(bang, ten_vai))
    for he in HYPEREDGES:
        che = oracle.slot_phai_che(bang, ten_vai, he) if ten_hyperedge(he) in thay else set(he["slots"])
        for v in che:
            assert he["slots"][v] not in van_ban, f"{ten_vai}: rò giá trị vai {v} của {he['id']}"


def test_ac1_hai_vai_theo_oracle_khong_llm_khong_embedding(workspace_dir, khong_gian, policy, bang):
    """AC-1: tập hyperedge, mức, tập node che của mỗi vai bằng oracle; 0 lời gọi LLM/embedding."""
    engine, client, _, llm = _engine(workspace_dir, khong_gian, policy)
    for ten_vai in HAI_VAI:
        dt = _do_thi(engine, vai(policy, ten_vai, khong_gian))
        _chac_khop_oracle(dt, bang, ten_vai)
        _khong_lo_gia_tri_bi_che(dt, bang, ten_vai)
    assert llm.so_lan == 0
    assert client.cac_loi_goi("query_points") == []
    assert engine.so_audit.cac_su_kien(EVENT_LLM_COST) == []
    assert engine.so_audit.cac_su_kien(EVENT_EMBEDDING_COST) == []
    assert engine.so_audit.cac_su_kien() == []


def test_hang_dau_io_matrix_devops(workspace_dir, khong_gian, policy, bang):
    """`devops`: 4 hyperedge (HE-03 L1, ba cái kia L2); `owner` của HE-01/02/03 là node che
    `[owner:DevOps]`; HE-03 che thêm theo oracle; HE-04 không có node che nào."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    dt = _do_thi(engine, vai(policy, "devops", khong_gian))
    he = _he_theo_id(dt)
    assert set(he) == set(BON_ID)
    assert {i: n.level for i, n in he.items()} == {
        ten_hyperedge(THEO_ID[k]): ("L1" if k == "HE-03" else "L2") for k in THEO_ID
    }
    entity = _entity_theo_id(dt)
    for k in ("HE-01", "HE-02", "HE-03"):
        ten = ten_hyperedge(THEO_ID[k])
        # Dấu che `owner` mang tên nhóm phụ trách của loại nội dung (ADR-011):
        # `runbook`/`bi_mat_ha_tang` là DevOps, `bao_cao_su_co` là Tech Support.
        assert entity[id_node_che(ten, "owner")].label == oracle.dau_che_ky_vong("owner", THEO_ID[k]["content_type"])
    assert entity[id_node_che(ten_hyperedge(THEO_ID["HE-01"]), "owner")].label == "[owner:DevOps]"
    ten3 = ten_hyperedge(THEO_ID["HE-03"])
    che3 = {c.slot for c in _canh_cua(dt, ten3) if entity[c.target].masked}
    assert che3 == oracle.slot_phai_che(bang, "devops", THEO_ID["HE-03"]) >= {"owner", "remediation"}
    assert "cụm máy chủ thanh toán" in entity and not entity["cụm máy chủ thanh toán"].masked
    ten4 = ten_hyperedge(THEO_ID["HE-04"])
    assert not [c for c in _canh_cua(dt, ten4) if entity[c.target].masked]
    assert "[owner:DevOps]" in json.dumps(dict_do_thi(dt), ensure_ascii=False)


def test_hang_hai_tech_support_app01_mot_node_chung(workspace_dir, khong_gian, policy, bang):
    """`tech_support`: HE-03/HE-04 vắng; HE-02 L1 với `cause`/`remediation`/`owner` che;
    `App01` là **một** node chung của HE-01 và HE-02."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    dt = _do_thi(engine, vai(policy, "tech_support", khong_gian))
    he = _he_theo_id(dt)
    assert set(he) == {ten_hyperedge(THEO_ID["HE-01"]), ten_hyperedge(THEO_ID["HE-02"])}
    ten2 = ten_hyperedge(THEO_ID["HE-02"])
    assert he[ten2].level == "L1"
    entity = _entity_theo_id(dt)
    che2 = {c.slot for c in _canh_cua(dt, ten2) if entity[c.target].masked}
    assert che2 == {"cause", "remediation", "owner", "source"} == oracle.slot_phai_che(bang, "tech_support", THEO_ID["HE-02"])
    app01 = [n for n in dt.nodes if isinstance(n, NodeEntity) and n.label == "App01"]
    assert len(app01) == 1 and app01[0].id == "App01" and not app01[0].masked
    assert {c.source for c in dt.edges if c.target == "App01"} == set(he)
    assert "Trần Thị Hạnh" not in json.dumps(dict_do_thi(dt), ensure_ascii=False)


def test_id_la_id_l0_va_danh_sach_rong_khong_phan_biet_duoc(workspace_dir, khong_gian, policy):
    """Ba lời gọi của `tech_support` cho cùng một đồ thị rỗng, không lỗi."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    ctx = vai(policy, "tech_support", khong_gian)
    he3 = ten_hyperedge(THEO_ID["HE-03"])
    he4 = ten_hyperedge(THEO_ID["HE-04"])
    ra = [_do_thi(engine, ctx, ids) for ids in ([he3, "HE-KHONG-CO"], [he4], ["HE-KHONG-CO"], [])]
    assert all(dt == DoThi() for dt in ra)
    assert all(dict_do_thi(dt) == graph_rong() for dt in ra)


def test_trung_va_khoang_trang_ra_mot_node_giu_thu_tu_dau(workspace_dir, khong_gian, policy):
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    he1, he2 = ten_hyperedge(THEO_ID["HE-01"]), ten_hyperedge(THEO_ID["HE-02"])
    dt = _do_thi(engine, vai(policy, "devops", khong_gian), [he2, f" {he1} ", he1, he1.lower(), f'"{he2}"'])
    assert list(_he_theo_id(dt)) == [he2, he1]


def test_cypher_mot_cau_match_loc_du_ba_bien_dung_tap_khoa(workspace_dir, khong_gian, policy, bang):
    """Một câu `MATCH` (không `OPTIONAL`), `h`/`r`/`e` đều ràng space và khóa, keys = oracle."""
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    for ten_vai in HAI_VAI:
        driver.xoa_nhat_ky()
        _do_thi(engine, vai(policy, ten_vai, khong_gian))
        cau = driver.cac_cau_doc()
        assert [lg.loai for lg in cau] == ["doc:do_thi_cua"], ten_vai
        cypher = cau[0].cypher
        canh_moi_bien_deu_bi_loc(cypher)
        assert "OPTIONAL MATCH" not in cypher and cypher.startswith("MATCH")
        for bien in ("h", "r", "e"):
            assert f"{bien}.space = $space" in cypher
        assert "e.role = $vai_entity" in cypher
        assert "IS NULL" not in cypher, "đường đồ thị không nới cho entity không khóa"
        assert set(cau[0].params["keys"]) == oracle.allowed_keys_ky_vong(bang, ten_vai)["hyperedges"]
        assert cau[0].params["space"] == khong_gian
        assert cau[0].params["ids"] == list(BON_ID)


def test_vai_khong_co_khoa_nao_thi_khong_gui_cau_nao(workspace_dir, khong_gian, policy):
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    ctx = vai(policy, "tech_support", khong_gian)
    rong = replace(ctx, allowed_keys={ns: frozenset() for ns in ctx.allowed_keys})
    driver.xoa_nhat_ky()
    assert _do_thi(engine, rong) == DoThi()
    assert driver.cac_cau_doc() == []


def test_ngu_canh_he_thong_bi_tu_choi_o_adapter_khong_cham_kho(workspace_dir, khong_gian, policy):
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    graph = engine.chunk_entity_relation_graph
    driver.xoa_nhat_ky()

    async def chay():
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await graph.do_thi_cua(BON_ID)

    with pytest.raises(DoThiNgoaiQuyen) as loi:
        asyncio.run(chay())
    assert loi.value.code == MA_TRICH_DAN_NGOAI_QUYEN
    assert driver.cac_cau_doc() == []
    with pytest.raises(DoThiNgoaiQuyen):
        _do_thi(engine, ngu_canh_ingest(khong_gian, policy))


def test_adapter_khong_tra_ten_tho_duoi_khoa_nao(workspace_dir, khong_gian, policy, bang):
    """Dòng của `do_thi_cua` mang đúng năm khóa, và tên ở vai che là dấu che."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    graph = engine.chunk_entity_relation_graph

    async def chay():
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await graph.do_thi_cua(BON_ID)

    dong = asyncio.run(chay())
    assert dong and all(tuple(d) == KHOA_DONG_ADAPTER for d in dong)
    he2 = THEO_ID["HE-02"]
    che = oracle.slot_phai_che(bang, "tech_support", he2)
    for d in dong:
        if d["id_hyperedge"] != ten_hyperedge(he2):
            continue
        assert d["khoa"] == oracle.khoa_ky_vong(he2["scope"], he2["content_type"])
        if d["slot"] in che:
            assert d["bi_che"] and d["ten_da_che"] == oracle.dau_che_ky_vong(d["slot"], he2["content_type"])
        else:
            assert not d["bi_che"] and d["ten_da_che"] == he2["slots"][d["slot"]]


# Hyperedge phụ (AC-2): cùng `subject` với HE-03 nhưng ở scope khác, nên entity
# "cụm máy chủ thanh toán" hợp nhất khác scope ra **không khóa** (AD-5). Nó là
# đỉnh duy nhất của HE-05.
HE_05 = MappingProxyType(
    {
        "id": "HE-05",
        "source_id": "chunk-HE-04",
        "scope": "khach_hang_a",
        "content_type": "runbook",
        "slots": MappingProxyType({"subject": "cụm máy chủ thanh toán"}),
    }
)


def test_ac2_dinh_khong_khoa_vang_va_hyperedge_chi_co_dinh_ay_vang_ca_vong(workspace_dir, khong_gian, policy, bang):
    """Đỉnh không khóa bị loại ở đồ thị (AD-8 thắng nới của AD-9); HE-05 vắng cả vòng.

    Đối chứng: cùng entity ấy vẫn **có mặt dưới dạng che cứng** ở ngữ cảnh LLM
    (`get_node_edges`), và citation của HE-05 vẫn dựng được với `subject` trong
    tập vai - hai luật cho hai đường, đúng như ADR-018 nói.
    """
    from core.masking import dau_che_lan_can_khong_khoa

    engine, *_ = _engine(workspace_dir, khong_gian, policy, them=(HE_05,))
    ctx = vai(policy, "devops", khong_gian)
    he3, he5 = ten_hyperedge(THEO_ID["HE-03"]), ten_hyperedge(HE_05)
    assert oracle.muc_ky_vong(bang, "devops", HE_05["content_type"]) == "L2"
    dt = _do_thi(engine, ctx, (*BON_ID, he5))
    he = _he_theo_id(dt)
    assert he5 not in he, "hyperedge mà đỉnh duy nhất không khóa phải vắng cả vòng"
    assert he3 in he and he[he3].level == "L1"
    assert "cụm máy chủ thanh toán" not in _entity_theo_id(dt)
    assert {c.slot for c in _canh_cua(dt, he3)} == set(THEO_ID["HE-03"]["slots"]) - {"subject"}
    # Label của HE-03 không mang đỉnh bị loại: nó là văn bản của đồ thị, không phải câu fact gốc.
    assert "cụm máy chủ thanh toán" not in he[he3].label and "chủ thể" not in he[he3].label
    _chac_label_tu_chinh_do_thi(dt, he[he3])
    # Tên hyperedge của fixture mang `subject` trong id (`{subject} - {content_type}`),
    # nên phép so chuỗi chỉ đúng trên node entity: không node entity nào mang tên ấy.
    assert not [n for n in dt.nodes if isinstance(n, NodeEntity) and "cụm máy chủ thanh toán" in (n.id, n.label)]
    graph = engine.chunk_entity_relation_graph

    async def doi_chung():
        with use_context(ctx):
            return await graph.get_node_edges(he5), await graph.trich_dan_cua([he5])

    lan_can, td = asyncio.run(doi_chung())
    assert lan_can == [(he5, dau_che_lan_can_khong_khoa())]
    assert td[he5][1] == ("subject",)


def test_hoan_policy_doi_do_thi_theo_bang_moi(workspace_dir, khong_gian, policy):
    """`policy-tat-phan-quyen.yaml`: `tech_support` thấy đủ 4, chỉ `owner` che; về bảng đầy đủ thì HE-03/04 vắng lại."""
    from adapters.policy_loader import load_policy

    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    mo = load_policy(oracle.POLICY_TAT_PHAN_QUYEN)
    dt = _do_thi(engine, vai(mo, "tech_support", khong_gian))
    he = _he_theo_id(dt)
    assert set(he) == set(BON_ID) and {n.level for n in he.values()} == {"L2"}
    entity = _entity_theo_id(dt)
    assert {c.slot for c in dt.edges if entity[c.target].masked} == {"owner"}
    dt2 = _do_thi(engine, vai(policy, "tech_support", khong_gian))
    assert set(_he_theo_id(dt2)) == {ten_hyperedge(THEO_ID["HE-01"]), ten_hyperedge(THEO_ID["HE-02"])}


# --- Lớp 3: HTTP ---------------------------------------------------------------------


def _client(monkeypatch, kho, audit, engine, **tuy_chon):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    # Story 3.8: các ca hoán sang bảng đo qua HTTP chạy như tiến trình đo.
    monkeypatch.setenv(BIEN_CHE_DO_DO, "1")

    async def _mo_kho():
        return kho

    async def _mo_audit():
        return audit

    async def _mo_engine(_audit):
        return engine

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    return TestClient(api_main.app, **tuy_chon)


def _kho_gia(khong_gian: str = "synth") -> KhoGia:
    return KhoGia(
        {
            TEN_GO["ts01"]: replace(_dong("ts01"), khong_gian=khong_gian),
            TEN_GO["dev01"]: replace(_dong("dev01", role="devops", demo=True, admin=True), khong_gian=khong_gian),
        }
    )


def _token(client, tai_khoan: str) -> str:
    kq = client.post("/auth/login", json={"tai_khoan": TEN_GO[tai_khoan], "mat_khau": MAT_KHAU})
    assert kq.status_code == 200, kq.text
    return kq.json()["token"]


def _goi(client, token: str, than):
    return client.post("/do-thi", json=than, headers={"Authorization": "Bearer " + token})


def test_http_envelope_nam_khoa_va_engine_nhan_dung_ids(monkeypatch):
    audit = AuditGia()
    engine = EngineGia(do_thi=_dt_mau())
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        token = _token(client, "dev01")
        so_su_kien = len(audit.su_kien)
        kq = _goi(client, token, {"hyperedge_ids": ["A", "B", "A"]})
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert tuple(than) == KHOA_ENVELOPE
    assert than["answer"] is None and than["refused"] is False and than["citations"] == []
    assert than["graph"] == dict_do_thi(_dt_mau())
    assert than["meta"]["role"] == "devops" and than["meta"]["space"] == "synth"
    assert engine.ids == [["A", "B"]]
    assert engine.ngu_canh[0].role == "devops" and not engine.ngu_canh[0].bypass_filter
    assert engine.ngu_canh[0].request_id is None
    assert engine.cau_hoi == [], "không lời gọi hỏi đáp nào"
    assert len(audit.su_kien) == so_su_kien, "không hàng audit mới cho lượt lấy đồ thị"


@pytest.mark.parametrize(
    "than,ma",
    [
        ({"hyperedge_ids": ["x"] * (SO_ID_TOI_DA + 1)}, MA_DANH_SACH_ID_QUA_DAI),
        ({"hyperedge_ids": "HE-01"}, MA_THAN_YEU_CAU_LA),
        ({}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_ids": ["a"], "role": "devops"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_ids": ["a", 1]}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_ids": ["a", ""]}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_ids": [None]}, MA_THAN_YEU_CAU_LA),
    ],
    ids=["qua_dai", "khong_list", "thieu_khoa", "thua_khoa", "muc_int", "muc_rong", "muc_none"],
)
def test_http_400_khong_cham_kho(monkeypatch, than, ma):
    engine = EngineGia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        kq = _goi(client, _token(client, "ts01"), than)
    assert kq.status_code == 400, kq.text
    assert kq.json()["error"]["code"] == ma
    assert engine.ids == []


def test_http_danh_sach_rong_la_do_thi_rong_dung_envelope(monkeypatch):
    engine = EngineGia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        kq = _goi(client, _token(client, "ts01"), {"hyperedge_ids": []})
    assert kq.status_code == 200
    assert kq.json() == {"answer": None, "refused": False, "citations": [], "graph": graph_rong(), "meta": kq.json()["meta"]}
    assert engine.ids == [[]]


def test_http_khong_token_bi_chan_o_cua(monkeypatch):
    engine = EngineGia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        kq = client.post("/do-thi", json={"hyperedge_ids": ["a"]})
    assert kq.status_code == 401
    assert engine.ids == []


@pytest.mark.parametrize(
    "loi,http,ma",
    [
        (Neo4jUnavailable("rớt"), 503, MA_KHO_KHONG_SAN_SANG),
        (TrichDanNgoaiQuyen("hỏng"), 500, MA_TRICH_DAN_NGOAI_QUYEN),
        (DoThiNgoaiQuyen("hệ thống"), 500, MA_TRICH_DAN_NGOAI_QUYEN),
    ],
    ids=["neo4j_rot", "trich_dan_ngoai_quyen", "do_thi_ngoai_quyen"],
)
def test_http_loi_kho_cung_anh_xa_voi_hoi_dap(monkeypatch, loi, http, ma):
    audit = AuditGia()
    engine = EngineGia(loi=loi)
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        kq = _goi(client, _token(client, "ts01"), {"hyperedge_ids": ["a"]})
    assert kq.status_code == http
    assert kq.json()["error"]["code"] == ma and "refused" not in kq.json()
    assert [sk for sk in audit.su_kien if sk.event in (EVENT_QUERY, EVENT_REFUSAL)] == []


def test_http_serializer_tu_choi_graph_sai_hinh_thanh_500_co_ma(monkeypatch):
    """Một `dict_do_thi` trả graph mang khóa lạ không ra được ngoài: 500 mang mã, không thân lạ."""
    engine = EngineGia(do_thi=_dt_mau())
    monkeypatch.setattr(api_do_thi, "dict_do_thi", lambda dt: {**dict_do_thi(dt), "bi_loai": 3})
    # `raise_server_exceptions=False`: ca này chấm chính lưới cuối của `api/main.py`.
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine, raise_server_exceptions=False) as client:
        kq = _goi(client, _token(client, "ts01"), {"hyperedge_ids": ["A"]})
    assert kq.status_code == 500
    assert kq.json()["error"]["code"] == MA_LOI_KHONG_XAC_DINH
    assert "bi_loai" not in kq.text


def test_http_hai_tai_khoan_seed_tren_engine_m1_that(monkeypatch, workspace_dir, khong_gian, policy, bang):
    """AC-1 qua HTTP: `dev01` và `ts01` gọi `POST /do-thi` với bốn id fixture."""
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        for tai_khoan, ten_vai in (("dev01", "devops"), ("ts01", "tech_support")):
            token = _token(client, tai_khoan)
            so_su_kien = len(audit.su_kien)
            kq = _goi(client, token, {"hyperedge_ids": list(BON_ID)})
            assert kq.status_code == 200, kq.text
            than = kq.json()
            assert tuple(than) == KHOA_ENVELOPE and than["citations"] == [] and than["refused"] is False
            assert than["meta"]["role"] == ten_vai
            # Dựng lại `DoThi` từ thân response rồi chấm bằng oracle: đúng thứ client sẽ đọc.
            dt = _do_thi_tu_than(than["graph"])
            _chac_khop_oracle(dt, bang, ten_vai)
            _khong_lo_gia_tri_bi_che(dt, bang, ten_vai)
            assert len(audit.su_kien) == so_su_kien
    assert llm.so_lan == 0
    assert engine.so_audit.cac_su_kien(EVENT_LLM_COST) == [] and engine.so_audit.cac_su_kien(EVENT_EMBEDDING_COST) == []


def _do_thi_tu_than(graph: dict) -> DoThi:
    """Đọc thân response bằng đúng bộ kiểm mà serializer dùng - một bộ, không hai."""
    return do_thi_tu_dict(graph)


def test_http_id_la_id_l0_va_rong_byte_identical(monkeypatch, workspace_dir, khong_gian, policy):
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    he3 = ten_hyperedge(THEO_ID["HE-03"])
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        token = _token(client, "ts01")
        ba = [
            _goi(client, token, {"hyperedge_ids": [he3, "HE-KHONG-CO"]}),
            _goi(client, token, {"hyperedge_ids": ["HE-KHONG-CO"]}),
            _goi(client, token, {"hyperedge_ids": []}),
        ]
    assert [kq.status_code for kq in ba] == [200] * 3
    assert ba[0].content == ba[1].content == ba[2].content
    ky_vong = json.dumps(
        {"answer": None, "refused": False, "citations": [], "graph": {"nodes": [], "edges": []}, "meta": ba[0].json()["meta"]},
        separators=(",", ":"),
    ).encode()
    assert ba[0].content == ky_vong


def test_http_hoan_policy_giua_chung(monkeypatch, workspace_dir, khong_gian, policy):
    """`POST /admin/policy` sang `tat-phan-quyen` rồi gọi lại: `ts01` thấy đủ 4; về `day-du` thì HE-03/04 vắng lại."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        admin = _token(client, "dev01")
        ts = _token(client, "ts01")
        truoc = _goi(client, ts, {"hyperedge_ids": list(BON_ID)}).json()["graph"]
        kq = client.post("/admin/policy", json={"id": "tat-phan-quyen"}, headers={"Authorization": "Bearer " + admin})
        assert kq.status_code == 200, kq.text
        mo = _goi(client, ts, {"hyperedge_ids": list(BON_ID)}).json()["graph"]
        kq = client.post("/admin/policy", json={"id": "day-du"}, headers={"Authorization": "Bearer " + admin})
        assert kq.status_code == 200, kq.text
        sau = _goi(client, ts, {"hyperedge_ids": list(BON_ID)}).json()["graph"]

    def he(g):
        return {n["id"] for n in g["nodes"] if n["kind"] == KIND_HYPEREDGE}

    assert he(mo) == set(BON_ID)
    dau_owner = {oracle.dau_che_ky_vong("owner", he["content_type"]) for he in HYPEREDGES}
    assert {n["label"] for n in mo["nodes"] if n["kind"] == KIND_ENTITY and n["masked"]} <= dau_owner
    assert {c["slot"] for c in mo["edges"] if c["target"].endswith("#owner")} == {"owner"}
    assert he(truoc) == he(sau) == {ten_hyperedge(THEO_ID["HE-01"]), ten_hyperedge(THEO_ID["HE-02"])}
    assert truoc == sau


def test_http_dung_200_id_la_200(monkeypatch):
    engine = EngineGia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        kq = _goi(client, _token(client, "ts01"), {"hyperedge_ids": [f"id-{i}" for i in range(SO_ID_TOI_DA)]})
    assert kq.status_code == 200, kq.text
    assert engine.ids == [[f"id-{i}" for i in range(SO_ID_TOI_DA)]]


@pytest.mark.parametrize(
    "dong",
    [
        lambda he1: [_dong_adapter(he1, "noi_bo:runbook", "subject", he1)],
        lambda he1: [_dong_adapter(he1, "noi_bo:runbook", "owner", "[owner:DevOps]", True),
                     _dong_adapter(he1, "noi_bo:runbook", "subject", id_node_che(he1, "owner"))],
        lambda he1: [_dong_adapter(he1, "noi_bo:runbook", "subject", "")],
    ],
    ids=["entity_trung_id_hyperedge", "entity_trung_id_node_che", "ten_rong"],
)
def test_http_dong_adapter_va_cham_hay_rong_ra_500_co_ma(monkeypatch, workspace_dir, khong_gian, policy, dong):
    """Dòng từ adapter va chạm id hay tên rỗng: 500 `TRICH_DAN_NGOAI_QUYEN`, không `ValueError` trần."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    he1 = ten_hyperedge(THEO_ID["HE-01"])

    async def _do_thi_cua(ids):
        return dong(he1)

    monkeypatch.setattr(engine.chunk_entity_relation_graph, "do_thi_cua", _do_thi_cua)
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        kq = _goi(client, _token(client, "dev01"), {"hyperedge_ids": [he1]})
    assert kq.status_code == 500
    assert kq.json()["error"]["code"] == MA_TRICH_DAN_NGOAI_QUYEN
    assert he1 not in kq.text


def test_http_canh_khong_vai_bi_bo_lang_le_cac_canh_khac_van_ra(monkeypatch, workspace_dir, khong_gian, policy, bang):
    """Cạnh không `slot` (dữ liệu trước 2.4) không về dòng nào và tên đích không ra; request vẫn 200."""
    from adapters.neo4j import ROLE_ENTITY, ROLE_FIELD, SPACE_FIELD
    from core.keys import FILTER_KEY_FIELD
    from tests.gia_lap_neo4j import CanhGia, NodeGia

    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    he1 = ten_hyperedge(THEO_ID["HE-01"])
    khoa = oracle.khoa_ky_vong("noi_bo", "runbook")
    ten_cu = "thực thể của cạnh không vai"
    driver.nodes[(khong_gian, ten_cu)] = NodeGia(
        nhan={khong_gian, "Entity"},
        props={"id": ten_cu, ROLE_FIELD: ROLE_ENTITY, SPACE_FIELD: khong_gian, FILTER_KEY_FIELD: khoa},
    )
    driver.canh.append(CanhGia(space=khong_gian, src=he1, tgt=ten_cu, props={"weight": 1.0, SPACE_FIELD: khong_gian, FILTER_KEY_FIELD: khoa}))

    async def dong_adapter():
        with use_context(vai(policy, "devops", khong_gian)):
            return await engine.chunk_entity_relation_graph.do_thi_cua([he1])

    assert not [d for d in asyncio.run(dong_adapter()) if d["ten_da_che"] == ten_cu]
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        kq = _goi(client, _token(client, "dev01"), {"hyperedge_ids": [he1]})
    assert kq.status_code == 200, kq.text
    assert ten_cu not in kq.text
    dt = _do_thi_tu_than(kq.json()["graph"])
    assert {c.slot for c in _canh_cua(dt, he1)} == set(THEO_ID["HE-01"]["slots"])


def test_adapter_slot_la_ra_ma_on_dinh_khong_slot_role_unknown(workspace_dir, khong_gian, policy):
    """Cạnh mang vai ngoài danh mục là dữ liệu kho hỏng: `DoThiNgoaiQuyen`, không `SlotRoleUnknown` trần."""
    from adapters.neo4j import SPACE_FIELD
    from core.keys import FILTER_KEY_FIELD
    from core.masking import SlotRoleUnknown
    from tests.gia_lap_neo4j import CanhGia

    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    he1 = ten_hyperedge(THEO_ID["HE-01"])
    khoa = oracle.khoa_ky_vong("noi_bo", "runbook")
    driver.canh.append(CanhGia(space=khong_gian, src=he1, tgt="App01", props={"weight": 1.0, "slot": "vai_la", SPACE_FIELD: khong_gian, FILTER_KEY_FIELD: khoa}))

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            return await engine.chunk_entity_relation_graph.do_thi_cua([he1])

    with pytest.raises(DoThiNgoaiQuyen) as loi:
        asyncio.run(chay())
    assert not isinstance(loi.value, SlotRoleUnknown)


# Hyperedge phụ cho ca giới hạn đã biết của phép so tên: entity có tên **đúng
# bằng** một dấu che, ở vai không bị che.
HE_06 = MappingProxyType(
    {
        "id": "HE-06",
        "source_id": "chunk-HE-01",
        "scope": "noi_bo",
        "content_type": "runbook",
        "slots": MappingProxyType({"subject": "[cause:masked]", "condition": "điều kiện thường"}),
    }
)


def test_entity_ten_dung_bang_dau_che_o_vai_khong_che_khong_bi_coi_la_che(workspace_dir, khong_gian, policy):
    """Giới hạn đã biết (ADR-018): `masked` là phép so tên trước/sau che, không parse dấu che,
    nên một entity tên `[cause:masked]` ở vai `subject` (L2, không che) ra `masked: false` với label là tên đó."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy, them=(HE_06,))
    he6 = ten_hyperedge(HE_06)
    dt = _do_thi(engine, vai(policy, "devops", khong_gian), [he6])
    entity = _entity_theo_id(dt)
    assert entity["[cause:masked]"] == NodeEntity("[cause:masked]", "[cause:masked]", False)
    assert CanhDoThi(he6, "[cause:masked]", "subject") in dt.edges
    assert id_node_che(he6, "owner") not in entity, "HE-06 không có vai owner nên không có node che nào"
    assert {n.masked for n in entity.values()} == {False}


# --- Tài liệu -----------------------------------------------------------------------


def test_adr_018_ghi_ba_quyet_dinh_cua_story():
    assert ADR_018.exists(), ADR_018
    van_ban = ADR_018.read_text(encoding="utf-8")
    for cum in ("không khóa", "AD-8", "AD-9", "id_node_che", "#{slot}", "audit", "get_node_edges", "do_thi_cua", "so tên"):
        assert cum in van_ban, f"ADR-018 thiếu {cum!r}"


def test_tuyen_do_thi_di_qua_cua_dong():
    from tests.test_api_khong_cham_tang_che import _cua_khai_o_tuyen, _tuyen_cua_app

    tuyen = [t for t in _tuyen_cua_app() if t.path == "/do-thi"]
    assert len(tuyen) == 1 and _cua_khai_o_tuyen(tuyen[0])
