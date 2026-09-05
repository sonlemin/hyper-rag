"""Trích xuất fact 8 vai qua pipeline thật: adapter, engine `ainsert` và lỗ L1 đã đóng (story 2.4).

Viết trước cơ chế (FR-27). Không mạng, không container, không key: LLM là bản
giả trả JSON fact xác định theo chunk (`tests/ho_tro_ingest.llm_theo_fact`),
kho vector local mode, driver graph giả. Mỗi hàng I/O Matrix của spec liên
quan đến trích xuất là một test ở đây; hàng lược đồ thuần nằm ở
`tests/test_fact_schema.py`, hàng cạnh/degree của adapter graph nằm ở
`tests/test_adapter_neo4j.py`.
"""

import asyncio
import json
import logging

import pytest

from adapters.ingest import (
    MA_KHONG_CO_FACT,
    TRANG_THAI_DA_NAP,
    TRANG_THAI_LOI,
    nap_thu_muc,
    xoa_tai_lieu,
)
from adapters.neo4j import SLOT_FIELD
from adapters.trich_xuat import (
    GOI_Y_VAI,
    PROMPT_KHONG_TU_DIEN,
    PROMPT_TRICH_XUAT,
    THAM_SO_LLM,
    VI_DU_DAU_RA,
    ThongKeTrichXuat,
    dung_prompt,
    khoi_tu_dien,
)
from core.audit import EVENT_EXTRACT_DOC, EVENT_INGEST_DOC, TIER_OBSERVATION
from core.facts import (
    GIA_TRI_TOI_DA,
    KHOA_FACTS,
    MA_GIA_TRI_RONG,
    MA_KHONG_PHAI_JSON,
    MA_THIEU_SUBJECT,
    MA_VAI_LA,
    TEN_VAI_TIENG_VIET,
    cau_fact,
    phan_tich_phan_hoi,
)
from core.ids import point_id
from core.keys import FILTER_KEY_FIELD, filter_key
from core.masking import dau_che, dau_che_owner
from core.permission import use_context
from core.slots import SLOT_ROLE_SET, SLOT_ROLES
from tests.fixtures import oracle
from tests.gia_lap_llm import SoAuditBoNho
from tests.ho_tro_ingest import (
    KHONG_FACT,
    SEP,
    dung_moi_truong,
    id_chunk,
    id_vector_entity,
    id_vector_hyperedge,
    llm_theo_fact,
    phan_hoi_fact,
    ten_entity,
    ten_hyperedge,
    viet_tai_lieu,
)
from tests.ho_tro_m1 import hoi
from tests.ngu_canh import ngu_canh_ingest, vai

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

THAN_SU_CO = "Báo cáo sự cố INC-1208. App01 trả lỗi 502 vì chỉnh sai giới hạn bộ nhớ PHP-FPM."
FACT_DU = {
    "subject": "App01",
    "symptom": "trang thanh toán trả lỗi 502",
    "cause": "chỉnh sai giới hạn bộ nhớ PHP-FPM",
    "condition": "traffic vượt 5000 request mỗi phút",
    "remediation": "trả giới hạn bộ nhớ về mức cũ",
    "source": "báo cáo sự cố INC-1208",
    "time": "2026-08-12 09:20",
    "owner": "Trần Thị Hạnh",
}

THAN_VPN = "Quy định VPN. Làm việc ngoài văn phòng thì phải bật VPN nội bộ."
FACT_VPN = {"subject": "VPN nội bộ", "condition": "làm việc ngoài văn phòng"}

THAN_SOP = "SOP-12 quy định chính nó: SOP-12 được xem lại mỗi quý theo SOP-12."
FACT_SOP = {"subject": "SOP-12", "source": "SOP-12", "condition": "mỗi quý"}


async def _nap(mt, thu_muc, khong_gian, policy, **them):
    return await nap_thu_muc(
        mt.engine, thu_muc, space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit, **them
    )


def _extract_doc(mt, doc_key):
    sk = [s for s in mt.so_audit.cac_su_kien(EVENT_EXTRACT_DOC) if s.chi_tiet["doc_key"] == doc_key]
    assert len(sk) == 1, f"mỗi tài liệu đúng một extract_doc, thấy {len(sk)}"
    return sk[0]


# --- Prompt và tham số ----------------------------------------------------------


def test_prompt_dung_tu_danh_muc_vai_co_chu_json_va_vi_du_parse_duoc():
    """Prompt chứa đủ 8 tên vai, chữ "json" (DeepSeek JSON mode đòi) và một ví dụ đúng lược đồ."""
    for vai_slot in SLOT_ROLES:
        assert f'- "{vai_slot}" ({TEN_VAI_TIENG_VIET[vai_slot]}):' in PROMPT_TRICH_XUAT, vai_slot
    assert "json" in PROMPT_TRICH_XUAT.lower()
    assert f"tối đa {GIA_TRI_TOI_DA} ký tự" in PROMPT_TRICH_XUAT, "khớp validator (<= GIA_TRI_TOI_DA)"
    assert set(GOI_Y_VAI) == SLOT_ROLE_SET
    # Ví dụ đầu ra trong prompt phải tự parse được bằng chính lược đồ.
    assert VI_DU_DAU_RA in PROMPT_TRICH_XUAT
    kq = phan_tich_phan_hoi(VI_DU_DAU_RA)
    assert kq.chunk_hong is False and len(kq.facts) >= 2 and not kq.loai_theo_ma
    prompt = dung_prompt("đoạn {văn} bản {có} ngoặc")
    assert "đoạn {văn} bản {có} ngoặc" in prompt


def test_moi_gia_tri_cua_vi_du_prompt_la_doan_co_that_trong_than_few_shot():
    """Ví dụ của prompt phải trích sát văn bản, đúng luật mà nó dạy LLM (story 2.6).

    Prompt bảo "trích sát văn bản, không suy diễn" rồi lại đưa một ví dụ viết
    lại câu (`time` dạng "2026-08-12 09:20" trong khi tài liệu viết "12/08/2026
    lúc 09:20"): ví dụ mạnh hơn lời dặn, nên LLM chuẩn hóa theo ví dụ và không
    còn khớp nổi nhãn vàng - nhãn vàng bị luật nạp 2.5 ép phải là đoạn có thật
    trong thân. Đây là cùng một luật, áp cho cả hai phía của phép chấm.

    So trên dạng `chuan_so_sanh` (NFC, gộp khoảng trắng, casefold), giống hệt
    phép canh nhãn vàng.
    """
    from eval.bo_vang import chuan_so_sanh, doc_bo_vang

    few = doc_bo_vang().tai_lieu_few_shot()
    assert few, "phải có tài liệu few-shot để đối chiếu"
    than = {t.doc_key: chuan_so_sanh(t.than) for t in few}
    for i, fact in enumerate(json.loads(VI_DU_DAU_RA)[KHOA_FACTS]):
        nguon = set(than)
        for vai_slot, gia_tri in fact.items():
            co = {k for k, t in than.items() if chuan_so_sanh(gia_tri) in t}
            assert co, (
                f"ví dụ fact#{i} vai {vai_slot}={gia_tri!r} không phải đoạn có thật"
                " trong thân tài liệu few-shot nào"
            )
            nguon &= co
        # Cả fact phải đọc được từ *một* tài liệu: một fact trộn chữ của hai
        # tài liệu là một fact không có thật, và nó dạy LLM ghép chéo nguồn.
        assert nguon, (
            f"ví dụ fact#{i} lấy chữ từ nhiều tài liệu khác nhau, không tài liệu"
            " nào chứa trọn nó"
        )


def test_tham_so_llm_temperature_0_json_object_max_tokens_huu_han():
    assert THAM_SO_LLM["temperature"] == 0
    assert THAM_SO_LLM["response_format"] == {"type": "json_object"}
    assert isinstance(THAM_SO_LLM["max_tokens"], int) and 0 < THAM_SO_LLM["max_tokens"] < 100_000


def test_thong_ke_ty_le_loai():
    tk = ThongKeTrichXuat(so_chunk=2, so_chunk_hong=0, so_fact_tho=4, so_hop_le=3, so_loai=1, loai_theo_ma={MA_VAI_LA: 1})
    assert tk.ty_le_loai == pytest.approx(0.25)
    assert ThongKeTrichXuat().ty_le_loai == 0.0
    ct = tk.chi_tiet()
    assert {"so_chunk", "so_chunk_hong", "so_fact_tho", "so_hop_le", "so_loai", "loai_theo_ma", "ty_le_loai"} <= set(ct)


# --- Hàng "Fact đủ vai" / "Fact 2 vai" -------------------------------------------


def test_fact_du_vai_ra_dung_hinh_dang_ba_kho(workspace_dir, khong_gian, policy, tmp_path):
    """1 node `he-…` không mang giá trị slot, 8 entity, 8 cạnh mỗi cạnh một `slot`; point hyperedge content là câu render."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_DU]}))

    async def chay():
        kq = await _nap(mt, thu_muc, khong_gian, policy)
        return kq, await mt.points(khong_gian, "hyperedges"), await mt.points(khong_gian, "entities")

    kq, diem_h, diem_e = asyncio.run(chay())
    tt = kq.tai_lieu[0]
    assert tt.trang_thai == TRANG_THAI_DA_NAP
    assert (tt.so_fact_hop_le, tt.so_fact_loai, tt.so_hyperedge, tt.so_entity) == (1, 0, 1, 8)

    he = ten_hyperedge(FACT_DU)
    assert list(mt.cac_node_vai(khong_gian, "hyperedge")) == [he] and he.startswith("he-")
    props = mt.node(khong_gian, he).props
    for gia_tri in FACT_DU.values():
        assert all(gia_tri not in str(v) for v in props.values()), "node hyperedge không mang giá trị slot"
    assert props["weight"] == 1.0 and props["source_id"] == id_chunk(THAN_SU_CO)
    assert props[FILTER_KEY_FIELD] == filter_key("noi_bo", "bao_cao_su_co")

    entity = mt.cac_node_vai(khong_gian, "entity")
    assert set(entity) == {ten_entity(v) for v in FACT_DU.values()}
    for vai_slot, gia_tri in FACT_DU.items():
        assert entity[ten_entity(gia_tri)]["entity_type"] == vai_slot
        assert entity[ten_entity(gia_tri)]["description"] == ""
    canh = mt.canh_cua(khong_gian, he)
    assert len(canh) == 8
    assert {c.props[SLOT_FIELD] for c in canh} == SLOT_ROLE_SET
    assert {(c.props[SLOT_FIELD], c.tgt) for c in canh} == {(k, ten_entity(v)) for k, v in FACT_DU.items()}
    for c in canh:
        assert c.props["source_id"] == id_chunk(THAN_SU_CO) and c.props["weight"] == 1.0

    # Kho vector: payload `hyperedge_name` là chính id mờ; content nhúng là câu render.
    assert [p["hyperedge_name"] for p in diem_h.values()] == [he]
    assert set(diem_h) == {point_id(id_vector_hyperedge(FACT_DU))}
    assert cau_fact(FACT_DU) in mt.van_ban_da_nhung()
    assert {p["entity_name"] for p in diem_e.values()} == {ten_entity(v) for v in FACT_DU.values()}
    assert set(diem_e) == {point_id(id_vector_entity(v)) for v in FACT_DU.values()}
    # Không câu fact nguyên văn nào lọt vào payload hay audit.
    for p in list(diem_h.values()) + list(diem_e.values()):
        assert "content" not in p
    for s in mt.so_audit.su_kien:
        assert all(FACT_DU["cause"] not in str(v) for v in s.chi_tiet.values())
        assert all(FACT_DU["cause"] not in h for h in s.hyperedge_ids)


def test_fact_hai_vai_hop_le_hai_canh(workspace_dir, khong_gian, policy, tmp_path):
    """FR-04: quan hệ 2 ngôi là fact 2 slot, đi cùng một đường."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "v.md", scope="noi_bo", content_type="runbook", than=THAN_VPN)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_VPN: [FACT_VPN]}))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert kq.tai_lieu[0].so_fact_hop_le == 1
    he = ten_hyperedge(FACT_VPN)
    assert mt.node(khong_gian, he) is not None
    assert sorted(c.props[SLOT_FIELD] for c in mt.canh_cua(khong_gian, he)) == ["condition", "subject"]


# --- Hàng "Một giá trị hai vai" ----------------------------------------------------


def test_mot_gia_tri_hai_vai_la_mot_entity_hai_canh_che_theo_tung_canh(workspace_dir, khong_gian, policy, tmp_path):
    """`SOP-12` vừa `subject` vừa `source`: 1 entity, 2 cạnh; che `source` không che `subject`; degree không đếm đôi."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "s.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SOP)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SOP: [FACT_SOP]}))
    he = ten_hyperedge(FACT_SOP)
    graph = mt.engine.chunk_entity_relation_graph

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            cap_ts = await graph.get_node_edges(he)
            bac_ts = await graph.node_degree(he)
        with use_context(vai(policy, "devops", khong_gian)):
            cap_dev = await graph.get_node_edges(he)
            bac_dev = await graph.node_degree(he)
        return cap_ts, bac_ts, cap_dev, bac_dev

    cap_ts, bac_ts, cap_dev, bac_dev = asyncio.run(chay())
    assert len(mt.cac_node_vai(khong_gian, "entity")) == 2, "SOP-12 là một entity"
    canh_sop = [c for c in mt.canh_cua(khong_gian, he) if c.tgt == "SOP-12"]
    assert sorted(c.props[SLOT_FIELD] for c in canh_sop) == ["source", "subject"], "hai cạnh khác slot"
    # tech_support (L1, che source): một bản ghi mỗi cạnh, cạnh `source` che, cạnh `subject` ra.
    lan_can_ts = sorted(c[1] for c in cap_ts)
    assert lan_can_ts == sorted(["SOP-12", dau_che("source"), "mỗi quý"])
    assert sorted(c[1] for c in cap_dev) == sorted(["SOP-12", "SOP-12", "mỗi quý"])
    # degree đếm distinct lân cận: 2, không phải 3 cạnh.
    assert bac_dev == 2 and bac_ts == 2


# --- Hàng "Vai lạ" / "Thiếu subject" / "Giá trị sai" / chunk hỏng: đếm, không ném ------


def test_ban_ghi_sai_luoc_do_bi_loai_va_dem_theo_ma(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    bang = {
        THAN_SU_CO: [
            FACT_DU,
            {"subject": "App01", "root_cause": "x"},
            {"cause": "x"},
            {"subject": "App01", "cause": ""},
        ]
    }
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(bang))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    tt = kq.tai_lieu[0]
    assert tt.trang_thai == TRANG_THAI_DA_NAP
    assert (tt.so_fact_hop_le, tt.so_fact_loai) == (1, 3)
    sk = _extract_doc(mt, "b.md")
    assert sk.tier == TIER_OBSERVATION and sk.space == khong_gian
    ct = sk.chi_tiet
    assert (ct["so_chunk"], ct["so_chunk_hong"], ct["so_fact_tho"], ct["so_hop_le"], ct["so_loai"]) == (1, 0, 4, 1, 3)
    assert dict(ct["loai_theo_ma"]) == {MA_VAI_LA: 1, MA_THIEU_SUBJECT: 1, MA_GIA_TRI_RONG: 1}
    assert ct["ty_le_loai"] == pytest.approx(0.75)
    assert sk.hyperedge_ids == (id_vector_hyperedge(FACT_DU),)
    # Chỉ fact hợp lệ vào graph.
    assert list(mt.cac_node_vai(khong_gian, "hyperedge")) == [ten_hyperedge(FACT_DU)]


def test_chunk_khong_json_loai_ca_chunk_van_dem(workspace_dir, khong_gian, policy, tmp_path):
    """Chunk trả văn bản tự do: tài liệu `KHONG_CO_FACT`, `so_chunk_hong=1`, lý do nói rõ, không ném."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_VPN)
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_VPN: "Tôi không tìm thấy fact nào.", THAN_SU_CO: [FACT_DU]}))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    tt = {t.doc_key: t for t in kq.tai_lieu}
    assert tt["a.md"].trang_thai == TRANG_THAI_LOI and tt["a.md"].ma == MA_KHONG_CO_FACT
    assert MA_KHONG_PHAI_JSON in tt["a.md"].ly_do
    assert tt["b.md"].trang_thai == TRANG_THAI_DA_NAP, "tài liệu kế vẫn chạy"
    ct = _extract_doc(mt, "a.md").chi_tiet
    assert (ct["so_chunk"], ct["so_chunk_hong"], ct["so_fact_tho"], ct["so_hop_le"]) == (1, 1, 0, 0)
    assert dict(ct["loai_theo_ma"]) == {MA_KHONG_PHAI_JSON: 1}


# --- Hàng "Hai fact trùng id trong một tài liệu" -------------------------------------


CO_CHUNK = 60
DOAN_1 = "A" * CO_CHUNK
DOAN_2 = "B" * CO_CHUNK
FACT_TRUNG = {"subject": "App01", "cause": "hết bộ nhớ"}


def test_hai_fact_trung_id_hai_chunk_gom_mot_node_hop_source_id(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=DOAN_1 + DOAN_2)
    mt = dung_moi_truong(
        workspace_dir,
        llm_theo_fact({DOAN_1: [FACT_TRUNG], DOAN_2: [FACT_TRUNG]}),
        chunk_token_size=CO_CHUNK,
        chunk_overlap_token_size=0,
    )
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    tt = kq.tai_lieu[0]
    assert (tt.so_chunk, tt.so_hyperedge, tt.so_fact_hop_le, tt.so_fact_loai) == (2, 1, 2, 0)
    ct = _extract_doc(mt, "a.md").chi_tiet
    assert (ct["so_chunk"], ct["so_fact_tho"], ct["so_hop_le"]) == (2, 2, 2)
    he = ten_hyperedge(FACT_TRUNG)
    props = mt.node(khong_gian, he).props
    assert set(props["source_id"].split(SEP)) == {id_chunk(DOAN_1), id_chunk(DOAN_2)}
    assert props["weight"] == 2.0
    for c in mt.canh_cua(khong_gian, he):
        assert set(c.props["source_id"].split(SEP)) == {id_chunk(DOAN_1), id_chunk(DOAN_2)}
    assert len(mt.llm.kwargs) == 2, "mỗi chunk đúng một lời gọi"


# --- Hàng "Tài liệu 0 fact hợp lệ" ------------------------------------------------------


def test_tai_lieu_0_fact_hop_le_canh_bao_dem_va_chay_tiep(workspace_dir, khong_gian, policy, tmp_path, caplog):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_VPN)
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    bang = {
        THAN_VPN: [{"subject": "VPN", "root_cause": "x"}, {"cause": "x"}, {"subject": "VPN", "cause": ""}],
        THAN_SU_CO: [FACT_DU],
    }
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(bang))

    async def chay():
        kq = await _nap(mt, thu_muc, khong_gian, policy)
        return kq, await mt.points(khong_gian, "chunks")

    with caplog.at_level(logging.WARNING, logger="adapters.ingest"):
        kq, chunks = asyncio.run(chay())
    tt = {t.doc_key: t for t in kq.tai_lieu}
    a = tt["a.md"]
    assert a.trang_thai == TRANG_THAI_LOI and a.ma == MA_KHONG_CO_FACT
    assert (a.so_fact_hop_le, a.so_fact_loai) == (0, 3)
    assert "3" in a.ly_do and MA_VAI_LA in a.ly_do and MA_THIEU_SUBJECT in a.ly_do and MA_GIA_TRI_RONG in a.ly_do
    assert "0 bản ghi" not in a.ly_do
    assert any("a.md" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
    sk = _extract_doc(mt, "a.md")
    assert sk.chi_tiet["so_hop_le"] == 0 and sk.chi_tiet["so_loai"] == 3 and sk.hyperedge_ids == ()
    # Dọn đợt như 2.3: chunk của a vắng, b nạp bình thường.
    assert set(chunks) == {point_id(id_chunk(THAN_SU_CO))}
    assert tt["b.md"].trang_thai == TRANG_THAI_DA_NAP
    assert [s.chi_tiet["doc_key"] for s in mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)] == ["b.md"]


def test_llm_tra_0_ban_ghi_ly_do_khac_voi_deu_bi_loai(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_VPN)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_VPN: KHONG_FACT}))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    a = kq.tai_lieu[0]
    assert a.ma == MA_KHONG_CO_FACT and "0 bản ghi" in a.ly_do
    assert (a.so_fact_hop_le, a.so_fact_loai) == (0, 0)
    assert _extract_doc(mt, "a.md").chi_tiet["so_fact_tho"] == 0


# --- Hàng "Lỗ L1 đóng" (FR-12) ------------------------------------------------------------


def test_lo_l1_dong_tech_support_thay_id_mo_va_dau_che_khong_thay_cause(workspace_dir, khong_gian, policy, tmp_path):
    """Fact `bao_cao_su_co` có `cause`; `tech_support` hỏi `only_need_context`: id `he-…` và `[cause:masked]` có mặt, giá trị `cause` vắng; `devops` thấy giá trị."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_DU]}))
    he = ten_hyperedge(FACT_DU)

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        ts = await hoi(mt.engine, vai(policy, "tech_support", khong_gian))
        dev = await hoi(mt.engine, vai(policy, "devops", khong_gian))
        return ts, dev

    ts, dev = asyncio.run(chay())
    assert he in ts, "fact vẫn có mặt qua id mờ (FR-12)"
    assert dau_che("cause") in ts
    for slot in ("cause", "source", "remediation", "owner"):
        assert FACT_DU[slot] not in ts, slot
    assert FACT_DU["symptom"] in ts
    assert he in dev and FACT_DU["cause"] in dev and FACT_DU["remediation"] in dev
    assert dau_che_owner(oracle.nhom_ky_vong("bao_cao_su_co")) in dev, (
        "đường graph tổng quát hóa owner ở mọi mức (AD-9), và từ story 3.1 dấu"
        " che mang tên nhóm phụ trách của loại nội dung chứ không phải một chữ chung"
    )


def test_dac_ta_hien_trang_owner_ra_nguyen_van_o_l2_qua_entities(workspace_dir, khong_gian, policy, tmp_path):
    """Đặc tả hiện trạng, không phải hành vi đúng: tên `owner` ra nguyên văn ở L2 qua bảng Entities.

    Phép đo mà ledger 1.7 giao cho 2.4: với trích xuất thật, tên entity của
    vai `owner` chính là tên người (`normalize_id` của giá trị slot), và ở L2
    kho vector `entities` trả nó về, `operate.py:779` ghép thẳng vào bảng
    Entities - trong khi đường graph đã tổng quát hóa cùng lúc.

    **Story 3.1 không đóng được lỗ này, và đây là chỗ ghi ra vì sao.** 3.1 đổi
    dấu che của đường graph từ `[owner:group]` sang tên nhóm thật, tức nó trả
    nửa "tổng quát hóa về mức nhóm" của ADR-011. Nửa còn lại - tên người không
    ra khỏi hệ qua *kho vector* - không nằm ở tầng che: nhìn từ một point
    `entities` lẻ không biết nó điền vào vai nào, nên chỗ sửa duy nhất là
    đường **ingest** (point của entity chỉ điền vai `owner` mang tên nhóm, hay
    không vào collection `entities`), và sửa ở đó là một đợt nạp lại - thứ spec
    3.1 xếp vào Ask First và không có trong Tasks của nó. Khoản ledger vì thế
    được gán địa chỉ mới kèm lý do, không đóng bằng một câu.

    Nghịch lý mà story 3.4 phải quyết: từ 3.1 câu trả lời nói "liên hệ Tech
    Support" trong khi ngữ cảnh cùng lúc mang tên người thật, nên hai nửa nói
    hai điều khác nhau về cùng một fact.
    """
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_DU]}))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        return await hoi(mt.engine, vai(policy, "devops", khong_gian))

    dev = asyncio.run(chay())
    assert dau_che_owner(oracle.nhom_ky_vong("bao_cao_su_co")) in dev
    assert FACT_DU["owner"] in dev, "hiện trạng: tên owner qua entities ở L2; địa chỉ 3.4"


# --- Hàng "Lời gọi LLM" -------------------------------------------------------------------


def test_moi_chunk_dung_mot_loi_goi_llm_voi_tham_so_json(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_DU]}))
    asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert mt.llm.so_lan == 1
    kwargs = mt.llm.kwargs[0]
    assert kwargs["temperature"] == 0
    assert kwargs["response_format"] == {"type": "json_object"}
    assert isinstance(kwargs["max_tokens"], int) and kwargs["max_tokens"] > 0
    assert "hashing_kv" not in kwargs
    prompt = mt.llm.prompts[0]
    assert THAN_SU_CO in prompt and "json" in prompt.lower()
    for vai_slot in SLOT_ROLES:
        assert vai_slot in prompt
    assert mt.llm.prompts_sinh_cau_tra_loi == [], "không lượt tự kiểm, không gleaning"


# --- Hàng "Re-ingest hyperedge chung" -----------------------------------------------------


THAN_F1 = "Tài liệu nội bộ về App01. App01 chạy trên cụm K8S nội bộ."
THAN_F2 = "Tài liệu khách hàng A về App01. App01 chạy trên cụm K8S nội bộ, theo hợp đồng."
FACT_F = {"subject": "App01", "condition": "chạy trên cụm K8S nội bộ"}


def test_re_ingest_hyperedge_chung_dung_lai_content_bang_cau_fact_tu_canh(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "f1.md", scope="noi_bo", content_type="runbook", than=THAN_F1)
    viet_tai_lieu(thu_muc, "f2.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_F2)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_F1: [FACT_F], THAN_F2: [FACT_F]}))
    he = ten_hyperedge(FACT_F)
    ghi = []
    goc = mt.engine.hyperedges_vdb.ghi_thang

    async def ghi_thang_spy(id_goc, *, content, khoa, meta=None):
        ghi.append((id_goc, content, khoa, dict(meta or {})))
        return await goc(id_goc, content=content, khoa=khoa, meta=meta)

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        mt.engine.hyperedges_vdb.ghi_thang = ghi_thang_spy
        await xoa_tai_lieu(mt.engine, "f2.md", space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await mt.engine.chunk_entity_relation_graph.slot_cua_hyperedge(he)

    slots = asyncio.run(chay())
    assert mt.node(khong_gian, he) is not None
    assert mt.node(khong_gian, he).props[FILTER_KEY_FIELD] == filter_key("noi_bo", "runbook"), "khóa gấp từ tài liệu còn lại"
    assert slots == {"subject": ["App01"], "condition": ["chạy trên cụm K8S nội bộ"]}
    assert ghi == [(id_vector_hyperedge(FACT_F), cau_fact(slots), filter_key("noi_bo", "runbook"), {"hyperedge_name": he})]


# --- Engine ainsert -----------------------------------------------------------------------


def test_ainsert_tra_thong_ke_va_none_khi_khong_co_gi_moi(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_DU]}))
    goc = mt.engine.ainsert
    tra_ve = []

    async def spy(noi_dung):
        kq = await goc(noi_dung)
        tra_ve.append(kq)
        return kq

    mt.engine.ainsert = spy

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        # Nạp lại cùng nội dung sau khi xóa sổ: kho đã có -> None.
        from adapters.ingest import SoTaiLieu

        SoTaiLieu.duong_dan(workspace_dir, khong_gian).unlink()
        await _nap(mt, thu_muc, khong_gian, policy)

    asyncio.run(chay())
    assert isinstance(tra_ve[0], ThongKeTrichXuat) and tra_ve[0].so_hop_le == 1
    assert tra_ve[1] is None
    assert len(mt.so_audit.cac_su_kien(EVENT_EXTRACT_DOC)) == 1, "không trích xuất thì không có extract_doc"


def test_fixture_epic_1_van_nap_duoc_qua_nap_kho(workspace_dir, khong_gian, policy):
    """Hàng "Fixture Epic 1": loader ghi trực tiếp vẫn hợp lệ vì cạnh của nó đã có `slot`."""
    from tests.ho_tro_m1 import cong_m1

    async def chay():
        engine, _, driver, _ = await cong_m1(workspace_dir, khong_gian, policy)
        return list(driver.canh)

    canh = asyncio.run(chay())
    assert canh, "fixture phải nạp được ít nhất một cạnh"
    assert all(c.props.get(SLOT_FIELD) in SLOT_ROLE_SET for c in canh), "mọi cạnh mang vai trong danh mục"
    assert not [c for c in canh if SLOT_FIELD not in c.props], "không cạnh nào thiếu slot"


# --- Vòng review đối kháng 02/09/2026 -----------------------------------------------------


# sha256 của `inspect.getsource(HyperGraphRAG.ainsert)` tại commit vendor hiện tại.
BAM_AINSERT_UPSTREAM = "8cf825a133d02a6d79c29c491414f183c6d1f8472fd86f9b9b66019dc64cb393"


def test_ainsert_upstream_khong_doi_ke_tu_ban_chep():
    """`EngineACL.ainsert` là bản chép của `HyperGraphRAG.ainsert` (không có khe tiêm).

    Vendor đổi luồng nạp (thứ tự `filter_keys`, id chunk, chỗ ghi KV) thì bản
    chép phải được soát lại tay: test này đỏ đúng lúc đó. Băm nguồn của method,
    không băm file, để một lần format lại vendor ở chỗ khác không đỏ.
    """
    import hashlib
    import inspect

    from hypergraphrag import HyperGraphRAG

    nguon = inspect.getsource(HyperGraphRAG.ainsert)
    assert hashlib.sha256(nguon.encode("utf-8")).hexdigest() == BAM_AINSERT_UPSTREAM, (
        "vendor đổi `ainsert`: soát lại `EngineACL.ainsert` rồi cập nhật hằng băm"
    )


def test_ainsert_chi_nhan_dung_mot_tai_lieu(workspace_dir, khong_gian, policy):
    """Danh sách dài hơn một là `ValueError`, không chạm kho: thống kê trích xuất là của *một* tài liệu."""
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_DU]}))

    async def chay():
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with pytest.raises(ValueError):
                await mt.engine.ainsert([THAN_SU_CO, THAN_VPN])
            with pytest.raises(ValueError):
                await mt.engine.ainsert([])

    asyncio.run(chay())
    assert mt.llm.so_lan == 0 and mt.driver.loi_goi == []


def test_fact_trung_trong_cung_chunk_gop_weight_mot_lan(workspace_dir, khong_gian, policy, tmp_path):
    """Cùng fact lặp hai lần trong một chunk: hyperedge weight 1.0, `so_hop_le` 3, `so_trung_trong_chunk` 1."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_TRUNG, dict(FACT_TRUNG), FACT_VPN]}))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert kq.tai_lieu[0].so_fact_hop_le == 3 and kq.tai_lieu[0].so_hyperedge == 2
    props = mt.node(khong_gian, ten_hyperedge(FACT_TRUNG)).props
    assert props["weight"] == 1.0 and props["source_id"] == id_chunk(THAN_SU_CO)
    ct = _extract_doc(mt, "b.md").chi_tiet
    assert (ct["so_hop_le"], ct["so_trung_trong_chunk"], ct["so_loai"]) == (3, 1, 0)


class _LLMMotChunkNo:
    """LLM giả: chunk chứa `DOAN_1` nổ ngay; chunk khác chờ rồi mới hoàn thành.

    Ghi lại số lời gọi *hoàn thành*: với `TaskGroup` lời gọi anh em bị hủy trong
    lúc chờ nên không hoàn thành thêm; với `gather` nó chạy hết rồi mới báo.
    """

    def __init__(self):
        self.bat_dau = 0
        self.hoan_thanh = 0
        self.prompts = []
        self.kwargs = []

    async def __call__(self, prompt, system_prompt=None, **kwargs):
        self.prompts.append(prompt)
        if DOAN_1 in prompt:
            await asyncio.sleep(0)
            raise RuntimeError("giả lập: 429 ở chunk đầu")
        if DOAN_2 in prompt:
            self.bat_dau += 1
            await asyncio.sleep(0.05)
            self.hoan_thanh += 1
            return phan_hoi_fact([FACT_TRUNG])
        from tests.gia_lap_llm import phan_hoi_tu_khoa

        return phan_hoi_tu_khoa()


def test_mot_chunk_no_thi_huy_loi_goi_anh_em(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=DOAN_1 + DOAN_2)
    llm = _LLMMotChunkNo()
    mt = dung_moi_truong(workspace_dir, llm, chunk_token_size=CO_CHUNK, chunk_overlap_token_size=0)
    from adapters.ingest import KetQuaNap

    kq = KetQuaNap()
    with pytest.raises(RuntimeError, match="429"):
        asyncio.run(_nap(mt, thu_muc, khong_gian, policy, ket_qua=kq))
    assert llm.bat_dau == 1, "chunk thứ hai đã bắt đầu"
    assert llm.hoan_thanh == 0, "và bị hủy trước khi hoàn thành (TaskGroup), không chạy hết như gather"
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_LOI and kq.tai_lieu[0].ma == "RuntimeError"
    assert mt.so_audit.cac_su_kien(EVENT_EXTRACT_DOC) == [], "không trích xong thì không có extract_doc"


def test_ly_do_deu_bi_loai_tach_ma_fact_va_ma_chunk(workspace_dir, khong_gian, policy, tmp_path):
    """N bản ghi đều bị loại: mã cấp fact cộng lại đúng N, chunk hỏng in riêng; `so_chunk_hong` lên trạng thái."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=DOAN_1 + DOAN_2)
    mt = dung_moi_truong(
        workspace_dir,
        llm_theo_fact({DOAN_1: "văn tự do", DOAN_2: [{"subject": "x", "root_cause": "y"}, {"cause": "x"}]}),
        chunk_token_size=CO_CHUNK,
        chunk_overlap_token_size=0,
    )
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    a = kq.tai_lieu[0]
    assert a.ma == MA_KHONG_CO_FACT and (a.so_fact_loai, a.so_chunk_hong) == (2, 1)
    assert a.ly_do.startswith("2 bản ghi đều bị loại (")
    phan_fact = a.ly_do.split("(")[1].split(")")[0]
    assert sum(int(x.split(": ")[1]) for x in phan_fact.split(", ")) == 2
    assert MA_KHONG_PHAI_JSON not in phan_fact and f"1/2 chunk không đọc được ({MA_KHONG_PHAI_JSON}: 1)" in a.ly_do


class _SoAuditNoTheoSuKien(SoAuditBoNho):
    """Port audit chỉ ném cho một loại sự kiện."""

    def __init__(self, event):
        super().__init__()
        self._no = event

    async def ghi(self, su_kien):
        if su_kien.event == self._no:
            raise ConnectionError("giả lập: Postgres rớt đúng lúc ghi extract_doc")
        await super().ghi(su_kien)


def test_port_audit_hong_o_extract_doc_khong_lam_hong_tai_lieu(workspace_dir, khong_gian, policy, tmp_path, caplog):
    """`extract_doc` là tầng observation: port ném thì WARNING, tài liệu vẫn `DA_NAP` và có `ingest_doc`."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_SU_CO)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({THAN_SU_CO: [FACT_DU]}))
    mt.so_audit = _SoAuditNoTheoSuKien(EVENT_EXTRACT_DOC)
    with caplog.at_level(logging.WARNING, logger="core.audit"):
        kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_DA_NAP
    assert [s.chi_tiet["doc_key"] for s in mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)] == ["b.md"]
    assert mt.so_audit.cac_su_kien(EVENT_EXTRACT_DOC) == []
    assert any(EVENT_EXTRACT_DOC in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


# --- Từ điển thực thể (story 2.12, FR-32) -------------------------------------------

TU_DIEN_A = """
version: 1
muc:
  - chuan: App01
    scope: khach_hang_a
    bi_danh: [app01.company.vn, APP-01]
    xac_nhan: "sonlm 2026-09-05"
"""

THAN_APP_DAI = "Sự cố hosting. app01.company.vn trả lỗi 502 lúc cao điểm."
FACT_APP_DAI = {"subject": "app01.company.vn", "symptom": "trả lỗi 502"}
THAN_APP_NGAN = "Runbook App01. App01 trả lỗi 502 thì kiểm pool PHP-FPM."
FACT_APP_NGAN = {"subject": "App01", "symptom": "trả lỗi 502"}


def _viet_tu_dien(tmp_path, noi_dung=TU_DIEN_A):
    f = tmp_path / "tu-dien.yaml"
    f.write_text(noi_dung, encoding="utf-8")
    return str(f)


def test_khong_khai_tu_dien_thi_prompt_khong_doi_mot_byte():
    """Ca đầu của I/O Matrix: `entity_dictionary_path` rỗng -> chạy y hệt hôm nay.

    `PROMPT_KHONG_TU_DIEN` là hằng mà `tests/test_cham_trich_xuat.py` đối chiếu
    với ba vòng đo đã trả tiền, nên đẳng thức này là chỗ nối hai khẳng định:
    prompt mặc định của hôm nay bằng prompt mà `v1-deepseek` đã chạy.
    """
    assert dung_prompt("XYZ") == PROMPT_KHONG_TU_DIEN.replace("<<VAN_BAN>>", "XYZ")
    assert "<<TU_DIEN>>" not in dung_prompt("XYZ")
    assert khoi_tu_dien(()) == ""


def test_khoi_tu_dien_vao_prompt_khi_co_muc():
    from adapters.tu_dien_thuc_the import MucTuDien

    khoi = khoi_tu_dien(
        [MucTuDien("App01", "khach_hang_a", ("app01.company.vn", "APP-01"), "sonlm 2026-09-05")]
    )
    prompt = dung_prompt("XYZ", khoi)
    assert "App01 <= app01.company.vn, APP-01" in prompt
    assert "XYZ" in prompt and "<<TU_DIEN>>" not in prompt


def test_tai_lieu_chua_chuoi_cho_chen_khong_tu_chen_duoc_khoi_tu_dien():
    """Thay chỗ chèn từ điển **trước** chỗ chèn văn bản, và đây là lý do."""
    prompt = dung_prompt("một tài liệu viết <<TU_DIEN>> trong thân")
    assert "một tài liệu viết <<TU_DIEN>> trong thân" in prompt


def test_bi_danh_dung_scope_gop_ve_mot_entity_va_mot_hyperedge(
    workspace_dir, khong_gian, policy, tmp_path
):
    """Hàng "Bí danh đúng scope": hai cách viết cho **một** id entity (FR-32).

    Hai tài liệu cùng scope `khach_hang_a`, một viết `app01.company.vn`, một
    viết `App01`. Không có từ điển thì đó là hai node entity và hai hyperedge;
    có từ điển thì là một, và `id_fact` của hai fact bằng nhau.
    """
    thu_muc = tmp_path / "nguon"
    viet_tai_lieu(thu_muc, "a.md", scope="khach_hang_a", content_type="bao_cao_su_co", than=THAN_APP_DAI)
    viet_tai_lieu(thu_muc, "b.md", scope="khach_hang_a", content_type="runbook", than=THAN_APP_NGAN)
    mt = dung_moi_truong(
        workspace_dir,
        llm_theo_fact({THAN_APP_DAI: [FACT_APP_DAI], THAN_APP_NGAN: [FACT_APP_NGAN]}),
        entity_dictionary_path=_viet_tu_dien(tmp_path),
    )
    asyncio.run(_nap(mt, thu_muc, khong_gian, policy))

    he = ten_hyperedge(FACT_APP_NGAN)
    assert list(mt.cac_node_vai(khong_gian, "hyperedge")) == [he]
    assert mt.node(khong_gian, ten_entity("App01")) is not None
    assert mt.node(khong_gian, ten_entity("app01.company.vn")) is None
    # Khối từ điển của scope đó cũng đã đi vào prompt.
    assert any("App01 <= app01.company.vn" in p for p in mt.llm.prompts)


def test_bi_danh_khac_scope_khong_bi_thay(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Bí danh khác scope": cùng chuỗi đó ở scope khác **không** bị thay.

    Đây là nửa quan trọng hơn của luật ràng scope: gộp `app01.company.vn` của
    khách A với chuỗi cùng tên ở khách B là hỏng đúng chỗ Composition-Risk đo.
    """
    thu_muc = tmp_path / "nguon"
    viet_tai_lieu(thu_muc, "b.md", scope="khach_hang_b", content_type="bao_cao_su_co", than=THAN_APP_DAI)
    mt = dung_moi_truong(
        workspace_dir,
        llm_theo_fact({THAN_APP_DAI: [FACT_APP_DAI]}),
        entity_dictionary_path=_viet_tu_dien(tmp_path),
    )
    asyncio.run(_nap(mt, thu_muc, khong_gian, policy))

    assert mt.node(khong_gian, ten_entity("app01.company.vn")) is not None
    assert mt.node(khong_gian, ten_entity("App01")) is None
    # Prompt của tài liệu này không mang khối từ điển của khách A.
    assert not any("App01 <= app01.company.vn" in p for p in mt.llm.prompts)


def test_khong_tu_dien_thi_hai_cach_viet_van_la_hai_entity(
    workspace_dir, khong_gian, policy, tmp_path
):
    """Đối chứng: chính hai tài liệu đó, không khai từ điển, cho hai node."""
    thu_muc = tmp_path / "nguon"
    viet_tai_lieu(thu_muc, "a.md", scope="khach_hang_a", content_type="bao_cao_su_co", than=THAN_APP_DAI)
    viet_tai_lieu(thu_muc, "b.md", scope="khach_hang_a", content_type="runbook", than=THAN_APP_NGAN)
    mt = dung_moi_truong(
        workspace_dir,
        llm_theo_fact({THAN_APP_DAI: [FACT_APP_DAI], THAN_APP_NGAN: [FACT_APP_NGAN]}),
    )
    asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert mt.node(khong_gian, ten_entity("App01")) is not None
    assert mt.node(khong_gian, ten_entity("app01.company.vn")) is not None
    assert len(mt.cac_node_vai(khong_gian, "hyperedge")) == 2


def test_tu_dien_hong_dung_ca_dot_truoc_khi_goi_llm(
    workspace_dir, khong_gian, policy, tmp_path
):
    """Từ điển sai lược đồ là **từ chối cả đợt**, không phải một đợt bỏ qua từ điển.

    Cùng chiều với bảng hạng độ nhạy: một cấu hình hỏng dừng đợt, không rơi về
    một mặc định. Ở đây còn thêm một điều kiện - nó phải dừng **trước** lời gọi
    LLM đầu tiên, vì mỗi lời gọi là tiền thật.
    """
    from adapters.tu_dien_thuc_the import TuDienThucTheInvalid

    thu_muc = tmp_path / "nguon"
    viet_tai_lieu(thu_muc, "a.md", scope="khach_hang_a", content_type="runbook", than=THAN_APP_NGAN)
    hong = tmp_path / "hong.yaml"
    hong.write_text("version: 1\nmuc:\n  - chuan: A\n    scope: x\n    bi_danh: [a]\n", encoding="utf-8")
    mt = dung_moi_truong(
        workspace_dir,
        llm_theo_fact({THAN_APP_NGAN: [FACT_APP_NGAN]}),
        entity_dictionary_path=str(hong),
    )
    with pytest.raises(TuDienThucTheInvalid) as e:
        asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert e.value.code == "TU_DIEN_THUC_THE_INVALID"
    assert "xac_nhan" in str(e.value)
    # Không lời gọi LLM nào: một từ điển hỏng phải dừng đợt **trước** khi tiêu
    # tiền, cùng chiều với bảng hạng độ nhạy hỏng (từ chối cả đợt, không đoán).
    assert mt.llm.prompts == []
