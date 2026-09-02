"""Pipeline ingest tuần tự: nạp, re-ingest ghi đè sạch, xóa, khóa tiến trình, audit (story 2.3).

Viết trước cơ chế (FR-27). Không mạng, không container, không key: kho vector
là local mode, driver graph là bản giả, LLM là bản giả trả fact xác định theo
chunk (`tests/ho_tro_ingest.llm_theo_fact`), nên mỗi tài liệu cho ra đúng tập
hyperedge/entity mà test khai.

Mỗi hàng I/O Matrix của spec là một test, trừ hàng marker `qdrant` (ở
`tests/test_adapter_qdrant_that.py`), hàng chunk trùng hai scope
(`tests/test_ingest_khoa_chunk_trung.py`) và hai hàng xóa (`tests/test_xoa_kho.py`).
"""

import asyncio
import fcntl

import pytest

from adapters.doi_chieu import StoreKeyMismatch, so_dang_mo
from adapters.ingest import (
    MA_DA_CO_TRONG_KHO,
    MA_KHONG_CO_FACT,
    MA_TRUNG_NOI_DUNG,
    TRANG_THAI_DA_NAP,
    TRANG_THAI_DA_XOA,
    TRANG_THAI_KHONG_DOI,
    TRANG_THAI_LOI,
    TRANG_THAI_TU_CHOI,
    IngestAlreadyRunning,
    KetQuaNap,
    KhoaIngest,
    LedgerCorrupt,
    LocalLLMUnavailable,
    SoTaiLieu,
    nap_cac_file,
    nap_thu_muc,
    xoa_tai_lieu,
)
from core.keys import KHONG_KHOA
from adapters.ingest_labels import current_ingest_key
from adapters.llm_wrapper import ProviderNotAllowedForSpace
from adapters.sensitivity_loader import bang_hang_mac_dinh
from core.audit import (
    EVENT_DELETE_DOC,
    EVENT_INGEST_DOC,
    TIER_MUTATION,
)
from core.ids import point_id
from core.keys import FILTER_KEY_FIELD, filter_key
from core.permission import current_context, use_context
from tests.ngu_canh import ngu_canh_ingest
from tests.ho_tro_ingest import (
    KHONG_FACT,
    SEP,
    dung_moi_truong,
    dung_moi_truong_cuc_bo,
    id_chunk,
    id_vector_entity,
    id_vector_hyperedge,
    llm_theo_fact,
    ten_entity,
    ten_hyperedge,
    viet_tai_lieu,
)
from tests.ngu_canh import vai

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

# Ba tài liệu, hai scope. `APP01` chung giữa A và B (cùng scope, khác loại nội
# dung); C ở scope khác và không chạm entity nào của A/B.
THAN_A = "Runbook App01. Khi traffic cao thì khởi động lại pool PHP-FPM theo SOP-12."
THAN_B = "Báo cáo sự cố INC-1208. App01 trả lỗi 502 vì chỉnh sai giới hạn bộ nhớ PHP-FPM."
THAN_C = "Runbook khách hàng A. Cổng thanh toán báo hàng đợi đầy thì giãn nhịp gọi API."
THAN_A_SUA = "Runbook App01 bản mới. Khi traffic cao thì tăng số worker PHP-FPM rồi theo dõi."

# Từ story 2.4 fact là dict slot (`core.slots`), entity là giá trị slot, id
# hyperedge là nhãn mờ `he-…`; `App01` chung giữa A và B.
FACT_A = {"subject": "App01", "condition": "traffic cao", "remediation": "khởi động lại pool PHP-FPM theo SOP-12"}
FACT_B = {"subject": "App01", "symptom": "trả lỗi 502", "cause": "chỉnh sai giới hạn bộ nhớ PHP-FPM"}
FACT_C = {"subject": "Cổng thanh toán A", "condition": "hàng đợi đầy", "remediation": "giãn nhịp gọi API"}
FACT_A_SUA = {"subject": "App01", "condition": "traffic cao", "remediation": "tăng số worker PHP-FPM"}

BANG_FACT = {
    THAN_A: [FACT_A],
    THAN_B: [FACT_B],
    THAN_C: [FACT_C],
    THAN_A_SUA: [FACT_A_SUA],
}

E = ten_entity("App01")
H_A = ten_hyperedge(FACT_A)
H_B = ten_hyperedge(FACT_B)


def _viet_ba_tai_lieu(thu_muc, *, loai_a="runbook"):
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type=loai_a, than=THAN_A)
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_B)
    viet_tai_lieu(thu_muc, "c.txt", scope="khach_hang_a", content_type="runbook", than=THAN_C)


async def _nap(mt, thu_muc, khong_gian, policy, **them) -> KetQuaNap:
    return await nap_thu_muc(
        mt.engine,
        thu_muc,
        space=khong_gian,
        policy_version=policy.policy_version,
        audit=mt.so_audit,
        **them,
    )


# --- Nạp lần đầu -------------------------------------------------------------


def test_nap_lan_dau_ba_tai_lieu_hai_scope(workspace_dir, khong_gian, policy, tmp_path, monkeypatch):
    """Hàng "Nạp lần đầu": 3 `ainsert` tuần tự, mỗi cái một ngữ cảnh hệ thống + nhãn + đợt riêng.

    Đếm bằng cách bọc chính `ainsert` của engine và `doi_chieu_dot` của pipeline:
    trong mỗi lời gọi phải thấy ngữ cảnh hệ thống của đúng space, nhãn của
    đúng tài liệu, và một sổ đợt *khác* với lời gọi trước.
    """
    thu_muc = tmp_path / "corpus"
    _viet_ba_tai_lieu(thu_muc)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    goc_ainsert = mt.engine.ainsert
    thay: list[tuple[bool, str, str, int]] = []

    async def ainsert_spy(noi_dung):
        ctx = current_context()
        thay.append((ctx.bypass_filter, ctx.space, current_ingest_key(), id(so_dang_mo())))
        return await goc_ainsert(noi_dung)

    monkeypatch.setattr(mt.engine, "ainsert", ainsert_spy)
    doi_chieu: list[int] = []
    import adapters.ingest as mod

    goc_doi_chieu = mod.doi_chieu_dot

    async def doi_chieu_spy(so, *, kho):
        doi_chieu.append(id(so))
        return await goc_doi_chieu(so, kho=kho)

    monkeypatch.setattr(mod, "doi_chieu_dot", doi_chieu_spy)

    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))

    assert [t.doc_key for t in kq.tai_lieu] == ["a.md", "b.md", "c.txt"]
    assert all(t.trang_thai == TRANG_THAI_DA_NAP and not t.re_ingest for t in kq.tai_lieu)
    assert kq.tu_choi == []
    # Ba lời gọi, mỗi cái đúng ngữ cảnh hệ thống + nhãn riêng + đợt riêng.
    assert [(b, sp, nhan) for b, sp, nhan, _ in thay] == [
        (True, khong_gian, filter_key("noi_bo", "runbook")),
        (True, khong_gian, filter_key("noi_bo", "bao_cao_su_co")),
        (True, khong_gian, filter_key("khach_hang_a", "runbook")),
    ]
    assert len({so for *_, so in thay}) == 3, "mỗi tài liệu một đợt riêng"
    assert doi_chieu == [so for *_, so in thay], "đối chiếu ngay sau mỗi ainsert, đúng sổ đó"
    # Sổ tài liệu bền vững có 3 mục.
    so = SoTaiLieu.mo(workspace_dir, khong_gian)
    assert set(so.cac_doc_key()) == {"a.md", "b.md", "c.txt"}
    muc_a = so.muc("a.md")
    assert muc_a.scope == "noi_bo" and muc_a.content_type == "runbook"
    assert muc_a.chunk_ids == [id_chunk(THAN_A)]
    assert set(muc_a.hyperedge) == {H_A}
    assert muc_a.hyperedge[H_A] == id_vector_hyperedge(FACT_A)
    assert set(muc_a.entity) == {ten_entity(v) for v in FACT_A.values()}
    assert muc_a.entity[E]["vector_id"] == id_vector_entity("App01")
    assert muc_a.entity[E]["chunk_ids"] == [id_chunk(THAN_A)]
    # Story 2.4: `description` entity rỗng (giá trị slot chính là tên entity,
    # mô tả LLM viết lại chỉ nhân đôi và mở thêm mặt rò L2), nên đóng góp mô
    # tả của mọi tài liệu là danh sách rỗng. Trước 2.4 kỳ vọng là mảnh mô tả.
    assert muc_a.entity[E]["mo_ta"] == []
    # 3 sự kiện ingest_doc, tầng mutation, mang phiên bản bảng hạng.
    sk = mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)
    assert [s.chi_tiet["doc_key"] for s in sk] == ["a.md", "b.md", "c.txt"]
    for s in sk:
        assert s.tier == TIER_MUTATION and s.space == khong_gian
        assert s.policy_version == policy.policy_version
        assert s.chi_tiet["sensitivity_ranks_version"] == bang_hang_mac_dinh().version
        assert s.chi_tiet["re_ingest"] is False
        assert s.chi_tiet["so_chunk"] == 1 and s.chi_tiet["so_hyperedge"] == 1
        assert s.chi_tiet["so_entity"] >= 1
        assert {"doc_id", "scope", "content_type"} <= set(s.chi_tiet)
    # Không có mục nào lọt vào cửa `ghi_bien_doi` mà không mang tier mutation.
    assert all(s.tier == TIER_MUTATION for s in mt.so_audit.su_kien if s.event == EVENT_INGEST_DOC)
    # Entity chung `APP01` cùng scope: khóa hạn chế nhất ở cả hai kho.
    assert mt.node(khong_gian, E).props[FILTER_KEY_FIELD] == filter_key("noi_bo", "bao_cao_su_co")


def test_nap_thu_muc_fixture_tu_choi_bon_file_va_nap_ba(workspace_dir, khong_gian, policy):
    """Corpus fixture thật: 4 từ chối trong kết quả, 3 nạp; một file hỏng không chặn file kế."""
    from pathlib import Path

    corpus = Path(__file__).resolve().parent / "fixtures" / "corpus_2_3"
    than = {p.name: p.read_text(encoding="utf-8").split("---\n")[-1].strip() for p in corpus.glob("0[1-3]-*")}
    bang = {t: [{"subject": f"fact cua {ten}", "source": f"E_{i}"}] for i, (ten, t) in enumerate(than.items())}
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(bang))
    kq = asyncio.run(_nap(mt, corpus, khong_gian, policy))
    assert sorted(tc.ten for tc in kq.tu_choi) == [
        "04-tai-lieu.pdf",
        "05-file-rong.md",
        "06-thieu-frontmatter.md",
        "07-khong-utf8.txt",
    ]
    assert [t.doc_key for t in kq.tai_lieu if t.trang_thai == TRANG_THAI_DA_NAP] == sorted(than)


# --- Re-ingest ---------------------------------------------------------------


def test_re_ingest_noi_dung_sua_ghi_de_sach(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Re-ingest nội dung sửa": H1 cũ vắng, E còn một bản, source_id sạch, chunk cũ vắng."""
    thu_muc = tmp_path / "corpus"
    _viet_ba_tai_lieu(thu_muc)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A_SUA)
        kq = await _nap(mt, thu_muc, khong_gian, policy)
        return kq

    kq = asyncio.run(chay())
    tt = {t.doc_key: t for t in kq.tai_lieu}
    assert tt["a.md"].trang_thai == TRANG_THAI_DA_NAP and tt["a.md"].re_ingest is True
    # b, c nội dung và nhãn không đổi: không chạm kho (`KHONG_DOI`), ép bằng `ep_ghi_de`.
    assert tt["b.md"].trang_thai == TRANG_THAI_KHONG_DOI and tt["c.txt"].trang_thai == TRANG_THAI_KHONG_DOI

    # H1 cũ vắng ở graph và cả 3 collection; H1' có mặt.
    assert mt.node(khong_gian, H_A) is None
    assert mt.node(khong_gian, ten_hyperedge(FACT_A_SUA)) is not None

    async def kiem_vector():
        for ns in ("hyperedges", "entities", "chunks"):
            assert not await mt.co_point(khong_gian, ns, id_vector_hyperedge(FACT_A)), ns
        assert await mt.co_point(khong_gian, "hyperedges", id_vector_hyperedge(FACT_A_SUA))
        # E đúng một point, `entity_name` trỏ về E.
        diem = await mt.points(khong_gian, "entities")
        cua_e = [p for p in diem.values() if p.get("entity_name") == E]
        assert len(cua_e) == 1
        assert cua_e[0][FILTER_KEY_FIELD] == filter_key("noi_bo", "bao_cao_su_co")
        # Chunk cũ của A vắng ở KV và `chunks`; chunk mới có mặt.
        assert not await mt.co_point(khong_gian, "chunks", id_chunk(THAN_A))
        assert await mt.co_point(khong_gian, "chunks", id_chunk(THAN_A_SUA))

    asyncio.run(kiem_vector())
    # E đúng một node; source_id không còn chunk cũ của A, có chunk mới và chunk của B.
    e_nodes = [k for k in mt.cac_node_vai(khong_gian, "entity") if k == E]
    assert len(e_nodes) == 1
    props = mt.node(khong_gian, E).props
    nguon = set(props["source_id"].split(SEP))
    assert id_chunk(THAN_A) not in nguon
    assert {id_chunk(THAN_A_SUA), id_chunk(THAN_B)} <= nguon
    # Story 2.4: mô tả entity rỗng ở mọi đường (nạp mới lẫn dựng lại); trước
    # 2.4 kỳ vọng là mảnh của bản A mới có mặt và mảnh bản A cũ vắng.
    assert props["description"] == ""
    # Khóa E = hợp nhất khóa các hyperedge còn nối (runbook + bao_cao_su_co cùng scope).
    assert props[FILTER_KEY_FIELD] == filter_key("noi_bo", "bao_cao_su_co")
    kv = mt.kv("text_chunks", khong_gian)
    assert id_chunk(THAN_A) not in kv and id_chunk(THAN_A_SUA) in kv and id_chunk(THAN_B) in kv
    # Mỗi hyperedge/entity đúng một bản (AC 2).
    assert sorted(mt.cac_node_vai(khong_gian, "hyperedge")) == sorted(
        {ten_hyperedge(FACT_A_SUA), H_B, ten_hyperedge(FACT_C)}
    )
    sk = mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)
    assert [s.chi_tiet["re_ingest"] for s in sk if s.chi_tiet["doc_key"] == "a.md"] == [False, True]


def test_re_ingest_doi_do_nhay_siet_khoa_entity_chung(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Re-ingest đổi độ nhạy": A thường -> hạn chế, E chung với B cùng scope lên hạng cao hơn."""
    thu_muc = tmp_path / "corpus"
    _viet_ba_tai_lieu(thu_muc)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        truoc = mt.node(khong_gian, E).props[FILTER_KEY_FIELD]
        viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="bi_mat_ha_tang", than=THAN_A)
        kq = await _nap(mt, thu_muc, khong_gian, policy)  # đối chiếu sạch: không ném
        diem = await mt.points(khong_gian, "entities")
        khoa_vector = [p[FILTER_KEY_FIELD] for p in diem.values() if p.get("entity_name") == E]
        return truoc, kq, khoa_vector

    truoc, kq, khoa_vector = asyncio.run(chay())
    assert truoc == filter_key("noi_bo", "bao_cao_su_co")
    tt = {t.doc_key: t.trang_thai for t in kq.tai_lieu}
    assert tt == {"a.md": TRANG_THAI_DA_NAP, "b.md": TRANG_THAI_KHONG_DOI, "c.txt": TRANG_THAI_KHONG_DOI}
    assert mt.node(khong_gian, E).props[FILTER_KEY_FIELD] == filter_key("noi_bo", "bi_mat_ha_tang")
    assert khoa_vector == [filter_key("noi_bo", "bi_mat_ha_tang")]
    assert mt.node(khong_gian, H_A).props[FILTER_KEY_FIELD] == filter_key("noi_bo", "bi_mat_ha_tang")


# --- Xóa tài liệu -------------------------------------------------------------


def test_xoa_tai_lieu_lam_entity_mat_nguon(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Xóa tài liệu làm E mất nguồn": E chỉ có H của A thì E biến mất, sổ không khóa sạch."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    e_rieng = ten_entity(FACT_A["remediation"])

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        assert mt.node(khong_gian, e_rieng) is not None
        tt = await xoa_tai_lieu(
            mt.engine, "a.md", space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit
        )
        con_e = await mt.co_point(khong_gian, "entities", id_vector_entity(FACT_A["remediation"]))
        con_h = await mt.co_point(khong_gian, "hyperedges", id_vector_hyperedge(FACT_A))
        con_c = await mt.co_point(khong_gian, "chunks", id_chunk(THAN_A))
        return tt, con_e, con_h, con_c

    tt, con_e, con_h, con_c = asyncio.run(chay())
    assert tt.doc_key == "a.md" and tt.trang_thai == TRANG_THAI_DA_XOA
    assert mt.node(khong_gian, e_rieng) is None and mt.node(khong_gian, E) is None
    assert mt.node(khong_gian, H_A) is None
    assert not con_e and not con_h and not con_c
    assert mt.kv("text_chunks", khong_gian) == {} and mt.kv("full_docs", khong_gian) == {}
    # Sổ không khóa của kho vector không giữ id đã xóa hẳn.
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        assert mt.engine.entities_vdb.so_khong_khoa(khong_gian) == set()
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == []
    sk = mt.so_audit.cac_su_kien(EVENT_DELETE_DOC)
    assert len(sk) == 1 and sk[0].tier == TIER_MUTATION
    assert sk[0].chi_tiet["doc_key"] == "a.md" and sk[0].chi_tiet["so_hyperedge"] == 1
    assert sk[0].chi_tiet["sensitivity_ranks_version"] == bang_hang_mac_dinh().version


def test_xoa_tai_lieu_khong_co_trong_so_la_loi_co_ma(workspace_dir, khong_gian, policy):
    from adapters.ingest import DocNotInLedger

    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    with pytest.raises(DocNotInLedger) as loi:
        asyncio.run(
            xoa_tai_lieu(mt.engine, "x.md", space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        )
    assert loi.value.code == "DOC_NOT_IN_LEDGER"
    assert mt.so_audit.su_kien == []


# --- Nạp lần ba cùng scope lần đầu ------------------------------------------


def test_nap_lan_ba_cung_scope_lan_dau_van_khong_khoa(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Nạp lần ba": E đã không khóa vì hai scope, tài liệu thứ ba cùng scope A không cấp lại khóa.

    Trước story này kho vector "quên" trạng thái không khóa (point bị xóa) và
    lần nạp thứ ba cấp lại khóa, hai kho lệch, bước đối chiếu bắt được. Nay sổ
    không khóa bền vững của kho vector nhớ trạng thái đó nên đợt sạch.
    """
    thu_muc = tmp_path / "corpus"
    than_c2 = "Runbook khách hàng A về App01. Khi App01 báo lỗi thì báo cho đầu mối khách hàng."
    than_d = "Runbook nội bộ bổ sung. App01 phải được theo dõi bằng dashboard chung."
    bang = {
        THAN_A: BANG_FACT[THAN_A],
        than_c2: [{"subject": "App01", "remediation": "báo cho đầu mối khách hàng A"}],
        than_d: [{"subject": "App01", "condition": "theo dõi bằng dashboard chung"}],
    }
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(bang))

    async def chay():
        viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
        viet_tai_lieu(thu_muc, "c.md", scope="khach_hang_a", content_type="runbook", than=than_c2)
        await _nap(mt, thu_muc, khong_gian, policy)
        assert FILTER_KEY_FIELD not in mt.node(khong_gian, E).props, "hai scope: không khóa ở graph"
        viet_tai_lieu(thu_muc, "d.md", scope="noi_bo", content_type="runbook", than=than_d)
        kq = await _nap(mt, thu_muc, khong_gian, policy)  # không ném: đối chiếu sạch
        con_point = await mt.co_point(khong_gian, "entities", id_vector_entity("App01"))
        return kq, con_point

    kq, con_point = asyncio.run(chay())
    tt = {t.doc_key: t.trang_thai for t in kq.tai_lieu}
    assert tt == {"a.md": TRANG_THAI_KHONG_DOI, "c.md": TRANG_THAI_KHONG_DOI, "d.md": TRANG_THAI_DA_NAP}
    assert FILTER_KEY_FIELD not in mt.node(khong_gian, E).props
    assert not con_point, "point không khóa vẫn vắng mặt tuyệt đối sau lần nạp thứ ba"
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        assert id_vector_entity("App01") in mt.engine.entities_vdb.so_khong_khoa(khong_gian)


# --- Hai tiến trình -----------------------------------------------------------


def test_hai_tien_trinh_thi_lan_thu_hai_khong_cham_kho(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Hai tiến trình": khóa file đang giữ thì `INGEST_ALREADY_RUNNING`, không chạm kho."""
    thu_muc = tmp_path / "corpus"
    _viet_ba_tai_lieu(thu_muc)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    duong_dan = KhoaIngest.duong_dan(workspace_dir, khong_gian)
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    with open(duong_dan, "w") as f:
        # flock theo mô tả file mở, nên hai lần `open` trong cùng tiến trình
        # cũng loại trừ nhau - đủ để dựng ca "tiến trình thứ hai".
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(IngestAlreadyRunning) as loi:
            asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert loi.value.code == "INGEST_ALREADY_RUNNING"
    assert mt.client.loi_goi == [] and mt.driver.loi_goi == []
    assert mt.so_audit.su_kien == []
    assert not SoTaiLieu.duong_dan(workspace_dir, khong_gian).exists()


def test_khoa_file_duoc_nha_sau_lan_chay(workspace_dir, khong_gian, policy, tmp_path):
    """Chạy xong thì nhả khóa: lần chạy kế tiếp trong cùng tiến trình vẫn vào được."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        return await _nap(mt, thu_muc, khong_gian, policy, ep_ghi_de=True)

    kq = asyncio.run(chay())
    assert kq.tai_lieu[0].re_ingest is True and kq.tai_lieu[0].trang_thai == TRANG_THAI_DA_NAP


# --- Space real ---------------------------------------------------------------


def test_space_real_ollama_chet_thi_khong_ghi_gi(workspace_dir, session_prefix, policy, tmp_path):
    """Hàng "Space real, ollama chết": provider cục bộ `san_sang()` False -> `LOCAL_LLM_UNAVAILABLE`."""
    space = f"{session_prefix}_real"
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong_cuc_bo(workspace_dir, llm_theo_fact(BANG_FACT), llm_san_sang=False)
    with pytest.raises(LocalLLMUnavailable) as loi:
        asyncio.run(_nap(mt, thu_muc, space, policy))
    assert loi.value.code == "LOCAL_LLM_UNAVAILABLE"
    assert mt.client.loi_goi == [] and mt.driver.loi_goi == []
    assert mt.so_audit.su_kien == []
    assert "chưa sẵn sàng" in str(loi.value) and "không tìm thấy provider" not in str(loi.value)


def test_space_real_embedding_cuc_bo_chet_cung_chan(workspace_dir, session_prefix, policy, tmp_path):
    """Cả hai provider phải sẵn sàng, không chỉ LLM; thông điệp là nhánh "chưa sẵn sàng"."""
    space = f"{session_prefix}_real"
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong_cuc_bo(workspace_dir, llm_theo_fact(BANG_FACT), emb_san_sang=False)
    with pytest.raises(LocalLLMUnavailable) as loi:
        asyncio.run(_nap(mt, thu_muc, space, policy))
    assert mt.client.loi_goi == [] and mt.driver.loi_goi == []
    assert "(embedding) chưa sẵn sàng" in str(loi.value)


def test_space_real_hai_provider_cuc_bo_san_sang_thi_nap_duoc(workspace_dir, session_prefix, policy, tmp_path):
    """Đối chứng: space real với hai provider cục bộ sẵn sàng nạp bình thường, có `ingest_doc`."""
    space = f"{session_prefix}_real"
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong_cuc_bo(workspace_dir, llm_theo_fact(BANG_FACT))
    kq = asyncio.run(_nap(mt, thu_muc, space, policy))
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_DA_NAP
    assert [s.space for s in mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)] == [space]


def test_space_real_provider_cuc_bo_thieu_san_sang_la_chua_san_sang(workspace_dir, session_prefix, policy, tmp_path):
    """Provider cục bộ không có phép thăm dò `san_sang` thì coi là chưa sẵn sàng, không AttributeError."""
    space = f"{session_prefix}_real"
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong_cuc_bo(workspace_dir, llm_theo_fact(BANG_FACT))
    from adapters.llm_wrapper import nha_cung_cap_cua

    del type(nha_cung_cap_cua(mt.engine.llm_model_func)).san_sang
    try:
        with pytest.raises(LocalLLMUnavailable) as loi:
            asyncio.run(_nap(mt, thu_muc, space, policy))
    finally:
        from tests.gia_lap_llm import NhaCungCapGia

        async def san_sang(self):
            return self._san_sang

        NhaCungCapGia.san_sang = san_sang
    assert "không có phép thăm dò" in str(loi.value)


def test_space_real_provider_api_ngoai_bi_tu_choi(workspace_dir, session_prefix, policy, tmp_path):
    """Hàng "Space real, provider API": `cuc_bo=False` -> `ProviderNotAllowedForSpace`, không fallback."""
    space = f"{session_prefix}_real"
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    with pytest.raises(ProviderNotAllowedForSpace) as loi:
        asyncio.run(_nap(mt, thu_muc, space, policy))
    assert loi.value.code == "PROVIDER_NOT_ALLOWED_FOR_SPACE"
    assert mt.client.loi_goi == [] and mt.driver.loi_goi == []
    assert mt.so_audit.su_kien == []


def test_space_synth_khong_kiem_san_sang(workspace_dir, khong_gian, policy, tmp_path):
    """Space không phải real thì provider API ngoài đi bình thường (đối chứng)."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_DA_NAP


# --- Lệch đối chiếu -----------------------------------------------------------


def test_lech_doi_chieu_dung_ca_lan_chay(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Lệch đối chiếu": kho vector rớt sau khi graph ghi -> tài liệu lỗi, dừng, `StoreKeyMismatch` dội lên."""
    thu_muc = tmp_path / "corpus"
    _viet_ba_tai_lieu(thu_muc)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def nuot(*a, **k):
        # Kho vector "nhận" mà không ghi: đúng hình dạng một kho rớt im lặng.
        return None

    mt.client._that.upsert = nuot
    kq = KetQuaNap()
    with pytest.raises(StoreKeyMismatch) as loi:
        asyncio.run(_nap(mt, thu_muc, khong_gian, policy, ket_qua=kq))
    assert loi.value.code == "STORE_KEY_MISMATCH"
    assert [t.doc_key for t in kq.tai_lieu] == ["a.md"], "không sang tài liệu kế"
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_LOI
    assert kq.tai_lieu[0].ma == "STORE_KEY_MISMATCH"
    # Sổ tài liệu không nhận mục lỗi; không có sự kiện ingest_doc.
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == []
    assert mt.so_audit.cac_su_kien(EVENT_INGEST_DOC) == []


# --- content_type lạ, hai file cùng nội dung ----------------------------------


def test_content_type_la_ghi_loi_va_chay_tiep(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "content_type lạ": `SENSITIVITY_RANK_UNKNOWN` cho tài liệu đó, tài liệu kế vẫn nạp."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="hop_dong", than=THAN_A)
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_B)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    tt = {t.doc_key: t for t in kq.tai_lieu}
    assert tt["a.md"].trang_thai == TRANG_THAI_LOI and tt["a.md"].ma == "SENSITIVITY_RANK_UNKNOWN"
    assert tt["b.md"].trang_thai == TRANG_THAI_DA_NAP
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == ["b.md"]
    assert mt.node(khong_gian, H_A) is None, "tài liệu lỗi không chạm kho"
    assert [s.chi_tiet["doc_key"] for s in mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)] == ["b.md"]


def test_hai_file_cung_noi_dung_file_sau_bi_tu_choi(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Hai file cùng nội dung": doc_id trùng, doc_key khác -> `TRUNG_NOI_DUNG`, không ném."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    viet_tai_lieu(thu_muc, "a2.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    kq = asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    tt = {t.doc_key: t for t in kq.tai_lieu}
    assert tt["a.md"].trang_thai == TRANG_THAI_DA_NAP
    assert tt["a2.md"].trang_thai == TRANG_THAI_TU_CHOI and tt["a2.md"].ma == MA_TRUNG_NOI_DUNG
    assert "a.md" in tt["a2.md"].ly_do, "lý do phải nói trùng với tài liệu nào"
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == ["a.md"]
    # Nhãn của a2 không được chạm vào khóa của tài liệu a.
    assert mt.node(khong_gian, H_A).props[FILTER_KEY_FIELD] == filter_key("noi_bo", "runbook")


def test_tai_lieu_khong_co_fact_ghi_loi_khong_de_lai_rac(workspace_dir, khong_gian, policy, tmp_path):
    """LLM không trích được fact nào: tài liệu lỗi `KHONG_CO_FACT`, chunk đã ghi vào `chunks` bị dọn, chạy tiếp.

    `ainsert` ghi `chunks_vdb` *trước* khi trích và return sớm khi không có
    fact hợp lệ, nên không dọn thì bước đối chiếu báo lệch giả ở mọi tài liệu
    rỗng fact. Phần đếm và lý do "0 bản ghi" / "đều bị loại" là của story 2.4
    (`tests/test_trich_xuat.py`); ở đây giữ kho sạch và lần chạy đi tiếp.
    """
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than="Đoạn văn không có fact nào.")
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_B)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT, mac_dinh=KHONG_FACT))

    async def chay():
        kq = await _nap(mt, thu_muc, khong_gian, policy)
        return kq, await mt.points(khong_gian, "chunks")

    kq, diem = asyncio.run(chay())
    tt = {t.doc_key: t for t in kq.tai_lieu}
    assert tt["a.md"].trang_thai == TRANG_THAI_LOI and tt["a.md"].ma == MA_KHONG_CO_FACT
    assert tt["b.md"].trang_thai == TRANG_THAI_DA_NAP
    assert set(diem) == {point_id(id_chunk(THAN_B))}
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == ["b.md"]


# --- Kết quả truy hồi sau nạp: vai đọc đúng thứ được đọc -----------------------


def test_sau_nap_vai_hep_khong_doc_duoc_chunk_scope_khac(workspace_dir, khong_gian, policy, tmp_path):
    """Pipeline nạp xong thì tầng quyền vẫn đứng: `tech_support` không đọc chunk `khach_hang_a`."""
    thu_muc = tmp_path / "corpus"
    _viet_ba_tai_lieu(thu_muc)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            c = await mt.engine.text_chunks.get_by_id(id_chunk(THAN_C))
            a = await mt.engine.text_chunks.get_by_id(id_chunk(THAN_A))
        return c, a

    c, a = asyncio.run(chay())
    assert c is None and a is not None


def test_audit_port_hong_thi_tai_lieu_loi_va_so_khong_cap_nhat(workspace_dir, khong_gian, policy, tmp_path):
    """Sự kiện ingest ở tầng mutation: port hỏng là tài liệu hỏng, sổ không cập nhật (Design Notes)."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    mt.so_audit.loi = RuntimeError("giả lập: Postgres rớt")
    kq = KetQuaNap()
    with pytest.raises(RuntimeError):
        asyncio.run(_nap(mt, thu_muc, khong_gian, policy, ket_qua=kq))
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_LOI
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == []


# --- Vòng review đối kháng 02/09/2026 ------------------------------------------


def test_khong_doi_thi_khong_cham_kho_khong_goi_llm(workspace_dir, khong_gian, policy, tmp_path):
    """Nạp lại tài liệu cùng sha256 + cùng nhãn: `KHONG_DOI`, LLM không được gọi, không sự kiện."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        mt.llm.xoa_nhat_ky()
        mt.client.xoa_nhat_ky()
        mt.driver.xoa_nhat_ky()
        so_sk = len(mt.so_audit.su_kien)
        kq = await _nap(mt, thu_muc, khong_gian, policy)
        return kq, so_sk

    kq, so_sk = asyncio.run(chay())
    tt = kq.tai_lieu[0]
    assert tt.trang_thai == TRANG_THAI_KHONG_DOI and tt.re_ingest is True and tt.so_hyperedge == 1
    assert mt.llm.so_lan == 0
    assert not [c for c in mt.client.loi_goi if c.ten in ("upsert", "delete")]
    assert not [c for c in mt.driver.loi_goi if c.loai.startswith("ghi:") and c.loai != "ghi:index"]
    assert len(mt.so_audit.su_kien) == so_sk


def test_ep_ghi_de_thi_re_ingest_du_khong_doi(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        mt.llm.xoa_nhat_ky()
        return await _nap(mt, thu_muc, khong_gian, policy, ep_ghi_de=True)

    kq = asyncio.run(chay())
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_DA_NAP and kq.tai_lieu[0].re_ingest is True
    assert mt.llm.so_lan > 0
    sk = mt.so_audit.cac_su_kien(EVENT_DELETE_DOC)
    assert len(sk) == 1 and sk[0].chi_tiet["re_ingest"] is True


def test_re_ingest_phat_delete_doc_truoc_ainsert(workspace_dir, khong_gian, policy, tmp_path, monkeypatch):
    """`ainsert` hỏng sau khi gỡ phần cũ: sổ audit có `delete_doc` cho tài liệu, không có `ingest_doc` mới."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        mt.so_audit.xoa()
        viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A_SUA)

        async def no(*a, **k):
            raise RuntimeError("giả lập: LLM rớt giữa ainsert")

        monkeypatch.setattr(mt.engine, "ainsert", no)
        kq = KetQuaNap()
        with pytest.raises(RuntimeError):
            await _nap(mt, thu_muc, khong_gian, policy, ket_qua=kq)
        return kq

    kq = asyncio.run(chay())
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_LOI and kq.tai_lieu[0].re_ingest is True
    xoa = mt.so_audit.cac_su_kien(EVENT_DELETE_DOC)
    assert [s.chi_tiet["doc_key"] for s in xoa] == ["a.md"] and xoa[0].chi_tiet["re_ingest"] is True
    assert mt.so_audit.cac_su_kien(EVENT_INGEST_DOC) == []
    assert mt.node(khong_gian, H_A) is None, "phần cũ đã gỡ"
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == []


def test_hyperedge_ids_cua_su_kien_la_id_vector(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
    sk = mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)[0]
    assert sk.hyperedge_ids == (id_vector_hyperedge(FACT_A),)
    assert all(h.startswith("rel-") and not any(v in h for v in FACT_A.values()) for h in sk.hyperedge_ids)


CO_CHUNK = 40
DOAN_CHUNG = "A" * CO_CHUNK
DOC_MOT = DOAN_CHUNG + "B" * CO_CHUNK
DOC_HAI = DOAN_CHUNG + "C" * CO_CHUNK
BANG_CHUNK = {
    DOAN_CHUNG: [{"subject": "fact chung", "source": "E_CHUNG"}],
    "B" * CO_CHUNK: [{"subject": "fact b", "source": "E_B"}],
    "C" * CO_CHUNK: [{"subject": "fact c", "source": "E_C"}],
}


def test_chunk_chung_cung_nhan_con_lai_sau_khi_xoa_tai_lieu_dau(workspace_dir, khong_gian, policy, tmp_path):
    """Hai tài liệu cùng nhãn chia nhau một chunk (bị `filter_keys` loại ở tài liệu sau).

    Sổ tài liệu tính chunk từ chính nội dung (`chunking_by_token_size` của
    vendor), không chỉ từ sổ đợt, nên tài liệu sau vẫn "sở hữu" chunk chung và
    xóa tài liệu đầu không được gỡ nó khỏi KV và `chunks`.
    """
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=DOC_MOT)
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="runbook", than=DOC_HAI)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_CHUNK), chunk_token_size=CO_CHUNK, chunk_overlap_token_size=0)
    from hypergraphrag.utils import compute_mdhash_id

    id_chung = compute_mdhash_id(DOAN_CHUNG, prefix="chunk-")

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        so = SoTaiLieu.mo(workspace_dir, khong_gian)
        assert id_chung in so.muc("b.md").chunk_ids, "sổ của b phải có chunk chung dù ainsert không ghi lại nó"
        await xoa_tai_lieu(mt.engine, "a.md", space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        return await mt.co_point(khong_gian, "chunks", id_chung)

    con_point = asyncio.run(chay())
    assert id_chung in mt.kv("text_chunks", khong_gian) and con_point
    assert compute_mdhash_id("B" * CO_CHUNK, prefix="chunk-") not in mt.kv("text_chunks", khong_gian)


THAN_F1 = "Tài liệu nội bộ về App01. App01 chạy trên cụm K8S nội bộ."
THAN_F2 = "Tài liệu khách hàng A về App01. App01 chạy trên cụm K8S nội bộ, theo hợp đồng."
FACT_F = {"subject": "App01", "condition": "chạy trên cụm K8S nội bộ"}
BANG_F = {THAN_F1: [FACT_F], THAN_F2: [FACT_F]}


def test_hyperedge_chung_hai_scope_dung_lai_khoa_sau_khi_xoa_mot_tai_lieu(workspace_dir, khong_gian, policy, tmp_path):
    """Cùng câu fact F + entity E ở hai scope (cả hai không khóa); xóa một tài liệu thì F còn với khóa của tài liệu còn lại, E gấp từ F.

    Đối chứng tay: bỏ điều kiện `h not in h_khac` trong `_xoa_theo_so` là F bị
    xóa hẳn và assert "F còn" đỏ.
    """
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "f1.md", scope="noi_bo", content_type="runbook", than=THAN_F1)
    viet_tai_lieu(thu_muc, "f2.md", scope="khach_hang_a", content_type="runbook", than=THAN_F2)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_F))
    H = ten_hyperedge(FACT_F)

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        assert FILTER_KEY_FIELD not in mt.node(khong_gian, H).props and FILTER_KEY_FIELD not in mt.node(khong_gian, E).props
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            assert id_vector_hyperedge(FACT_F) in mt.engine.hyperedges_vdb.so_khong_khoa(khong_gian)
        await xoa_tai_lieu(mt.engine, "f2.md", space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            so_h = mt.engine.hyperedges_vdb.so_khong_khoa(khong_gian)
            so_e = mt.engine.entities_vdb.so_khong_khoa(khong_gian)
            khoa_h = await mt.engine.hyperedges_vdb.khoa_hien_co([id_vector_hyperedge(FACT_F)])
            khoa_e = await mt.engine.entities_vdb.khoa_hien_co([id_vector_entity("App01")])
        diem_h = await mt.points(khong_gian, "hyperedges")
        return so_h, so_e, khoa_h, khoa_e, diem_h

    so_h, so_e, khoa_h, khoa_e, diem_h = asyncio.run(chay())
    khoa_con = filter_key("noi_bo", "runbook")
    assert mt.node(khong_gian, H) is not None, "F chung không được xóa khi f1 còn kể tên"
    assert mt.node(khong_gian, H).props[FILTER_KEY_FIELD] == khoa_con
    assert set(mt.node(khong_gian, H).props["source_id"].split(SEP)) == {id_chunk(THAN_F1)}
    assert mt.node(khong_gian, E).props[FILTER_KEY_FIELD] == khoa_con
    assert khoa_h[id_vector_hyperedge(FACT_F)] == khoa_con and khoa_e[id_vector_entity("App01")] == khoa_con
    assert so_h == set() and so_e == set()
    # Story 2.4: payload `hyperedge_name` là id mờ `he-…`, không còn câu fact.
    assert [p["hyperedge_name"] for p in diem_h.values()] == [ten_hyperedge(FACT_F)]


def test_payload_entity_name_la_gia_tri_slot_sau_dung_lai(workspace_dir, khong_gian, policy, tmp_path):
    """Point dựng lại của E mang `entity_name` đúng như lúc nạp.

    Đổi kỳ vọng ở story 2.4: entity là giá trị slot đã `normalize_id`, không
    upper-case, không nháy (trước đó là `"APP01"` theo parser upstream).
    """
    thu_muc = tmp_path / "corpus"
    _viet_ba_tai_lieu(thu_muc)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        await xoa_tai_lieu(mt.engine, "a.md", space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        diem = await mt.points(khong_gian, "entities")
        return [p for p in diem.values() if p.get("entity_name") == E]

    cua_e = asyncio.run(chay())
    assert len(cua_e) == 1 and cua_e[0]["entity_name"] == "App01"


def test_khong_hyperedge_don_ca_entity_va_khong_cham_tai_lieu_khac(workspace_dir, khong_gian, policy, tmp_path):
    """Đợt không hyperedge dọn mọi kho theo sổ đợt, trừ chunk/entity tài liệu khác đang dùng.

    Bộ trích xuất không sinh được entity mà không có hyperedge, nên ca này
    dựng bằng cách chặn `upsert_node` vai hyperedge, cạnh SLOT và
    `hyperedges_vdb.upsert`: entity và chunk vẫn được ghi (đúng hình dạng "có
    entity mà không hyperedge" mà finding nêu).
    """
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_B)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT, mac_dinh=KHONG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)  # B vào trước, có APP01
        viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
        graph = mt.engine.chunk_entity_relation_graph
        goc = graph.upsert_node

        async def bo_hyperedge(node_id, node_data):
            if node_data.get("role") == "hyperedge":
                return None
            return await goc(node_id, node_data)

        graph.upsert_node = bo_hyperedge
        goc_edge = graph.upsert_edge

        async def bo_canh(*a, **k):
            return None

        graph.upsert_edge = bo_canh
        goc_vdb = mt.engine.hyperedges_vdb.upsert
        mt.engine.hyperedges_vdb.upsert = bo_canh
        try:
            kq = await _nap(mt, thu_muc, khong_gian, policy)
        finally:
            graph.upsert_node, graph.upsert_edge = goc, goc_edge
            mt.engine.hyperedges_vdb.upsert = goc_vdb
        return kq, await mt.points(khong_gian, "chunks"), await mt.points(khong_gian, "entities")

    kq, chunks, ents = asyncio.run(chay())
    tt = {t.doc_key: t for t in kq.tai_lieu}
    assert tt["a.md"].trang_thai == TRANG_THAI_LOI and tt["a.md"].ma == MA_KHONG_CO_FACT
    # Nhánh thứ ba của lý do (2.4): có fact hợp lệ mà đợt không ghi hyperedge.
    assert "fact hợp lệ" in tt["a.md"].ly_do and tt["a.md"].so_fact_hop_le == 1
    assert set(chunks) == {point_id(id_chunk(THAN_B))}, "chunk của A dọn, chunk của B còn"
    assert mt.node(khong_gian, ten_entity(FACT_A["remediation"])) is None, "entity riêng của A dọn"
    assert mt.node(khong_gian, E) is not None, "entity App01 của B không bị dọn"
    assert {p.get("entity_name") for p in ents.values()} == {ten_entity(v) for v in FACT_B.values()}
    assert id_chunk(THAN_A) not in mt.kv("text_chunks", khong_gian)
    assert SoTaiLieu.mo(workspace_dir, khong_gian).cac_doc_key() == ["b.md"]


def test_dot_rong_vi_kho_da_co_ma_so_khong_biet(workspace_dir, khong_gian, policy, tmp_path):
    """Dữ liệu nạp trước khi có sổ: `ainsert` return sớm, đợt rỗng -> `DA_CO_TRONG_KHO`, không phải `KHONG_CO_FACT`."""
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))

    async def chay():
        await _nap(mt, thu_muc, khong_gian, policy)
        SoTaiLieu.duong_dan(workspace_dir, khong_gian).unlink()  # sổ mất, kho vẫn đầy
        return await _nap(mt, thu_muc, khong_gian, policy)

    kq = asyncio.run(chay())
    assert kq.tai_lieu[0].trang_thai == TRANG_THAI_LOI and kq.tai_lieu[0].ma == MA_DA_CO_TRONG_KHO
    assert mt.node(khong_gian, H_A) is not None, "không dọn gì"


def test_so_tai_lieu_hong_la_loi_co_ma(workspace_dir, khong_gian, policy, tmp_path):
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    duong_dan = SoTaiLieu.duong_dan(workspace_dir, khong_gian)
    for noi_dung in ("{ hong", '{"version": 2, "tai_lieu": {}}', '["a"]', '{"version": 1}'):
        duong_dan.write_text(noi_dung, encoding="utf-8")
        with pytest.raises(LedgerCorrupt) as loi:
            asyncio.run(_nap(mt, thu_muc, khong_gian, policy))
        assert loi.value.code == "INGEST_LEDGER_CORRUPT"
    assert mt.so_audit.su_kien == []


def test_so_khong_khoa_ben_vung_qua_engine_thu_hai(workspace_dir, khong_gian, policy, tmp_path):
    """Đường engine thật: engine B trên cùng `working_dir` đọc sổ không khóa mà engine A ghi."""
    thu_muc = tmp_path / "corpus"
    than_c = "Runbook khách hàng A về App01. Khi App01 báo lỗi thì báo cho đầu mối khách hàng."
    bang = {THAN_A: BANG_FACT[THAN_A], than_c: [{"subject": "App01", "remediation": "báo đầu mối khách hàng"}]}
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    viet_tai_lieu(thu_muc, "c.md", scope="khach_hang_a", content_type="runbook", than=than_c)
    a = dung_moi_truong(workspace_dir, llm_theo_fact(bang))

    async def chay():
        await _nap(a, thu_muc, khong_gian, policy)
        b = dung_moi_truong(workspace_dir, llm_theo_fact(bang))
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await b.engine.entities_vdb.khoa_hien_co([id_vector_entity("App01")])

    khoa = asyncio.run(chay())
    assert (workspace_dir / f"khong_khoa_{khong_gian}_entities.json").exists()
    assert khoa[id_vector_entity("App01")] is KHONG_KHOA


def test_nap_cac_file_giu_thu_tu_va_doc_key_la_ten_file(workspace_dir, khong_gian, policy, tmp_path):
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(BANG_FACT))
    f_b = viet_tai_lieu(tmp_path / "x", "b.md", scope="noi_bo", content_type="bao_cao_su_co", than=THAN_B)
    f_a = viet_tai_lieu(tmp_path / "y", "a.md", scope="noi_bo", content_type="runbook", than=THAN_A)
    kq = asyncio.run(
        nap_cac_file(mt.engine, [f_b, f_a], space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
    )
    assert [t.doc_key for t in kq.tai_lieu] == ["b.md", "a.md"]
    assert all(t.trang_thai == TRANG_THAI_DA_NAP for t in kq.tai_lieu)
    assert [s.chi_tiet["doc_key"] for s in mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)] == ["b.md", "a.md"]
