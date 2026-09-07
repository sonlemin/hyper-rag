"""Citation "được dùng" thu hẹp theo `nguon` của model; audit giữ tập thấy (story 3.8, ADR-022).

Đặc tả viết trước cơ chế (FR-27). Khoản ledger 3.4 đo được 97 citation cho một
lượt trả lời trên `synth` - đúng bằng số dòng Relationships mà vendor dựng, không
phải số nguồn câu trả lời dùng. Story 3.8 chọn đường (b) của khoản đó: prompt
trả thêm khóa `nguon` (chỉ số dòng đã dùng), engine giao với tập citation đã
dựng. Ba điều bộ này chấm, và cả ba là chốt brief §6 dưới dạng cơ chế:

- `nguon` **chỉ thu hẹp**: tập citation ra khỏi engine luôn là tập con của
  `id_hyperedge_trong(ngu_canh)`; một chỉ số lạ bị bỏ, không thêm được id nào.
- Vắng, rỗng hay toàn chỉ số lạ thì citation là **cả** tập thấy, không lặng lẽ
  thành rỗng.
- Audit `query.hyperedge_ids` ghi **tập thấy**, response mang tập dùng; hậu kiểm
  không đứng trên một danh sách do model khai.

Tách file thay vì nối vào `tests/test_tu_choi.py` / `tests/test_trich_dan.py`:
hai file ấy đã ở ngưỡng 1000 dòng của cổng M1. Các ca sửa nhỏ (parametrize thêm
ca sai kiểu, ví dụ mang `nguon`) vẫn nằm ở chỗ cũ của chúng.
"""

import asyncio
import json
import logging

import pytest
from hypergraphrag.utils import process_combine_contexts

from adapters.tra_loi import (
    KHOA_CAU_TRA_LOI,
    KHOA_KHONG_CO_DAP_AN,
    KHOA_NGUON,
    PROMPT_TRA_LOI,
    TRAN_SO_NGUON,
    VI_DU_DAU_RA,
    DauRaTraLoiKhongDoc,
    KetQuaHoiDap,
    doc_dau_ra,
    hang_hyperedge_trong,
    id_hyperedge_trong,
    loc_trich_dan_theo_nguon,
)
from api.hoi_dap import MA_DAU_RA_LLM_KHONG_DOC_DUOC, dict_trich_dan
from core.audit import EVENT_QUERY, EVENT_REFUSAL
from tests.gia_lap_llm import phan_hoi_hai_luot
from tests.test_trich_dan import _bang_quan_he, _client, _engine, _hoi, _hoi_dap, _kho_gia, _ngu_canh, _td
from tests.test_tu_choi import khung_ngu_canh
from tests.test_xac_thuc import AuditGia, EngineGia

# --- Lớp 1: hàm thuần ------------------------------------------------------------


def test_hang_hyperedge_trong_doc_cot_id_va_khong_khu_trung():
    """Từng dòng `(chỉ số cột id, id)`, kể cả hai dòng cùng hyperedge; `id_hyperedge_trong` suy từ nó."""
    khoi = _bang_quan_he([0, "he-b", "x"], [1, "he-a", "y"], [2, "he-b", "z"])
    nc = khung_ngu_canh(relations=khoi)
    assert hang_hyperedge_trong(nc) == ((0, "he-b"), (1, "he-a"), (2, "he-b"))
    assert id_hyperedge_trong(nc) == ("he-b", "he-a")


def test_hang_hyperedge_trong_doc_duoc_dang_hybrid_va_chi_so_la_cot_id():
    """Dạng hybrid đánh số lại cột `id`; chỉ số phải là số model đọc thấy, không phải vị trí dòng."""
    hl = _bang_quan_he([0, "he-1", "a"], [1, "he-2", "b"])
    ll = _bang_quan_he([0, "he-3", "c"], [1, "he-1", "d"])
    hybrid = process_combine_contexts(hl, ll)
    hang = hang_hyperedge_trong(khung_ngu_canh(relations=hybrid))
    # Vendor khử trùng theo **cả dòng** (bỏ cột id), nên hai dòng `he-1` khác
    # `related_entities` đều còn; và nó đánh số lại từ **1**. Chỉ số phải là số
    # model đọc thấy, không phải vị trí dòng.
    assert [h[1] for h in hang] == ["he-1", "he-2", "he-3", "he-1"]
    assert [h[0] for h in hang] == [1, 2, 3, 4]
    assert id_hyperedge_trong(khung_ngu_canh(relations=hybrid)) == ("he-1", "he-2", "he-3")
    # Cột `id` không phải số thì chỉ số là -1 (không khớp `nguon` nào), không nổ,
    # và dòng vẫn vào tập thấy: vị trí dòng không phải thứ model đọc.
    khoi = _bang_quan_he(["a", "he-1", "x"], ["b", "he-2", "y"])
    assert hang_hyperedge_trong(khung_ngu_canh(relations=khoi)) == ((-1, "he-1"), (-1, "he-2"))
    assert id_hyperedge_trong(khung_ngu_canh(relations=khoi)) == ("he-1", "he-2")


@pytest.mark.parametrize("chuoi", ["không phải khung", "", None, khung_ngu_canh()])
def test_hang_hyperedge_trong_khong_phai_khung_thi_rong(chuoi):
    assert hang_hyperedge_trong(chuoi) == ()


HANG_5 = tuple((i, f"he-{i}") for i in range(5))
THAY_5 = tuple(_td(f"he-{i}") for i in range(5))


def test_nguon_hop_le_thu_hep_theo_thu_tu_ngu_canh():
    """Hàng "`nguon` hợp lệ": `[3, 0]` cho đúng dòng 0 và 3, **theo thứ tự ngữ cảnh**."""
    dung = loc_trich_dan_theo_nguon(THAY_5, HANG_5, (3, 0))
    assert [td.id for td in dung] == ["he-0", "he-3"]


@pytest.mark.parametrize("nguon", [(), (99,), (99, -1)], ids=["rong", "la", "la_va_am"])
def test_nguon_rong_hay_toan_chi_so_la_thi_giu_ca_tap_thay_va_canh_bao(nguon, caplog):
    """Hàng "`nguon` rỗng, thiếu, hay toàn chỉ số lạ": citation là cả 5, có WARNING."""
    with caplog.at_level(logging.WARNING, logger="adapters.tra_loi"):
        assert loc_trich_dan_theo_nguon(THAY_5, HANG_5, nguon) == THAY_5
    assert any("tập thấy" in r.getMessage() for r in caplog.records)


def test_nguon_chi_thu_hep_khong_bao_gio_them_id():
    """Chỉ số lạ trộn với chỉ số thật: chỉ phần thật còn lại, và không id nào ngoài tập thấy."""
    dung = loc_trich_dan_theo_nguon(THAY_5, HANG_5, (99, 2, 7))
    assert [td.id for td in dung] == ["he-2"]
    # Hai dòng cùng hyperedge (đường phụ chưa hợp nhất): một chỉ số là đủ.
    hang = ((0, "he-a"), (1, "he-b"), (2, "he-a"))
    thay = (_td("he-a"), _td("he-b"))
    assert [td.id for td in loc_trich_dan_theo_nguon(thay, hang, (2,))] == ["he-a"]


def _dau_ra(nguon=..., **sua) -> str:
    than = {KHOA_KHONG_CO_DAP_AN: False, KHOA_CAU_TRA_LOI: "x", **sua}
    if nguon is not ...:
        than[KHOA_NGUON] = nguon
    return json.dumps(than, ensure_ascii=False)


def test_doc_dau_ra_nguon_ba_dang_hop_le():
    """Hợp lệ (khử trùng, giữ thứ tự, bỏ số âm), rỗng, và vắng (hình dạng hai khóa của 3.5 vẫn đọc được)."""
    assert doc_dau_ra(_dau_ra([3, 0, 3, -1])).nguon == (3, 0)
    with pytest.raises(DauRaTraLoiKhongDoc):
        doc_dau_ra(_dau_ra(list(range(TRAN_SO_NGUON + 1))))
    assert doc_dau_ra(_dau_ra([])).nguon == ()
    assert doc_dau_ra(_dau_ra()).nguon == ()
    # Lượt từ chối mang `nguon` cũng đọc được, và cờ vẫn là thứ quyết định.
    tu_choi = doc_dau_ra(_dau_ra([0], **{KHOA_KHONG_CO_DAP_AN: True, KHOA_CAU_TRA_LOI: ""}))
    assert tu_choi.khong_co_dap_an is True


@pytest.mark.parametrize(
    "nguon",
    ["0,3", [0, "x"], [True], {"0": 1}, 3, [1.5]],
    ids=["chuoi", "phan_tu_chuoi", "bool", "dict", "so_tran", "so_thuc"],
)
def test_doc_dau_ra_nguon_sai_kieu_la_doi_khong_doan(nguon):
    """Hàng "`nguon` sai kiểu": `DauRaTraLoiKhongDoc`, cùng lớp với ba khóa kia."""
    with pytest.raises(DauRaTraLoiKhongDoc):
        doc_dau_ra(_dau_ra(nguon))


def test_ket_qua_hoi_dap_suy_tap_thay_va_cam_citation_ngoai_tap_thay():
    """Vắng `hyperedge_da_thay` thì bằng dãy id citation; citation ngoài tập thấy là lỗi lúc dựng."""
    kq = KetQuaHoiDap(cau_tra_loi="x", trich_dan=(_td("he-2"), _td("he-1")))
    assert kq.hyperedge_da_thay == ("he-2", "he-1")
    kq2 = KetQuaHoiDap(cau_tra_loi="x", trich_dan=(_td("he-2"),), hyperedge_da_thay=("he-2", "he-1"))
    assert kq2.hyperedge_da_thay == ("he-2", "he-1")
    with pytest.raises(ValueError):
        KetQuaHoiDap(cau_tra_loi="x", trich_dan=(_td("he-9"),), hyperedge_da_thay=("he-2",))
    with pytest.raises(TypeError):
        KetQuaHoiDap(cau_tra_loi="x", hyperedge_da_thay=["he-2"])
    # Lượt từ chối: tập thấy rỗng, cùng hình dạng tuple rỗng của 3.4 - và bị từ chối nếu không rỗng.
    assert KetQuaHoiDap(ly_do_tu_choi="co_no_answer").hyperedge_da_thay == ()
    with pytest.raises(ValueError):
        KetQuaHoiDap(ly_do_tu_choi="co_no_answer", hyperedge_da_thay=("he-1",))


def test_loc_theo_nguon_trich_dan_rong_khong_canh_bao_va_giu_id_duoc_cap(caplog):
    """Ngữ cảnh không khung: rỗng ra rỗng, không WARNING; `giu` luôn giữ id được cấp nếu có trong tập thấy."""
    with caplog.at_level(logging.WARNING, logger="adapters.tra_loi"):
        assert loc_trich_dan_theo_nguon((), (), (0, 1)) == ()
    assert caplog.records == []
    dung = loc_trich_dan_theo_nguon(THAY_5, HANG_5, (1,), giu=("he-4", "he-99"))
    assert [td.id for td in dung] == ["he-1", "he-4"], "he-4 giữ vì được cấp, he-99 không thêm được"
    # `giu` không cứu ca nguon rỗng khỏi fallback: cả tập thấy vẫn trả về.
    assert loc_trich_dan_theo_nguon(THAY_5, HANG_5, (), giu=("he-4",)) == THAY_5


# --- Prompt v2 ---------------------------------------------------------------------


def test_prompt_v2_day_dau_che_la_phan_bi_che_khong_phai_thieu_du_lieu():
    """Khoản ledger 5.1: `ts01` bị `co_no_answer` vì model đọc `[cause:masked]` thành thiếu dữ liệu.

    Prompt v2 phải nói hai điều bằng lời của **cơ chế** (không nói về quyền, xem
    `tests/test_tu_choi.py`): một dòng mang dấu che vẫn là dữ liệu về điều nó
    nói tới, và cờ chỉ bật khi không dòng nào nói về điều được hỏi.
    """
    assert "dấu che là phần bị che của một fact có thật" in PROMPT_TRA_LOI
    assert "không phải một chỗ thiếu dữ liệu" in PROMPT_TRA_LOI
    assert f'Chỉ đặt "{KHOA_KHONG_CO_DAP_AN}" là true khi không dòng nào' in PROMPT_TRA_LOI
    # Không dạy model về phân quyền (luật của 3.5 giữ nguyên).
    for cam in ("đã được lọc theo quyền", "không được đọc", "không được phép", "hạn chế quyền"):
        assert cam not in PROMPT_TRA_LOI


def test_prompt_v2_khai_khoa_nguon_va_vi_du_mang_nguon():
    """Khóa thứ ba `nguon` là chỉ số cột `id` của bảng quan hệ; ba ví dụ đều mang nó."""
    assert f'"{KHOA_NGUON}" là danh sách số nguyên' in PROMPT_TRA_LOI
    assert 'cột "id"' in PROMPT_TRA_LOI
    assert "đúng ba khóa" in PROMPT_TRA_LOI and "đúng hai khóa" not in PROMPT_TRA_LOI
    vi_du = [json.loads(d) for d in VI_DU_DAU_RA.splitlines()]
    assert len(vi_du) == 3
    assert all(isinstance(v[KHOA_NGUON], list) for v in vi_du)
    assert vi_du[1][KHOA_NGUON] == [] and vi_du[1][KHOA_KHONG_CO_DAP_AN] is True
    assert all(all(isinstance(i, int) for i in v[KHOA_NGUON]) for v in vi_du)
    # Ví dụ dấu che (thứ ba) vẫn là một lượt **trả lời**, có nguồn.
    assert vi_du[2][KHOA_KHONG_CO_DAP_AN] is False and vi_du[2][KHOA_NGUON]


# --- Lớp 2: engine cổng M1 thật ----------------------------------------------------


def test_m1_nguon_thu_hep_citation_va_tap_thay_bang_ngu_canh(workspace_dir, khong_gian, policy):
    """Model khai `nguon=[0]`: citation là đúng dòng 0 của ngữ cảnh, tập thấy là cả ngữ cảnh."""
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    ngu_canh = _ngu_canh(engine, policy, "devops", khong_gian)
    hang = hang_hyperedge_trong(ngu_canh)
    assert len(hang) >= 2, "fixture M1 phải cho `devops` hơn một dòng Relationships"
    llm.theo_prompt = phan_hoi_hai_luot(nguon=[hang[0][0]])
    kq = _hoi_dap(engine, policy, "devops", khong_gian)
    assert kq.ly_do_tu_choi is None
    assert [td.id for td in kq.trich_dan] == [hang[0][1]]
    assert kq.hyperedge_da_thay == id_hyperedge_trong(ngu_canh)
    assert set(td.id for td in kq.trich_dan) < set(kq.hyperedge_da_thay)


@pytest.mark.parametrize("nguon", [None, [], [99]], ids=["vang", "rong", "la"])
def test_m1_nguon_vang_rong_la_thi_citation_la_ca_tap_thay(workspace_dir, khong_gian, policy, nguon):
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    llm.theo_prompt = phan_hoi_hai_luot(nguon=nguon)
    kq = _hoi_dap(engine, policy, "devops", khong_gian)
    assert kq.ly_do_tu_choi is None
    assert tuple(td.id for td in kq.trich_dan) == kq.hyperedge_da_thay
    assert kq.hyperedge_da_thay == id_hyperedge_trong(_ngu_canh(engine, policy, "devops", khong_gian))


def test_m1_nguon_sai_kieu_la_loi_he_thong_khong_them_loi_goi(workspace_dir, khong_gian, policy):
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    llm.theo_prompt = phan_hoi_hai_luot(nguon="0,3")
    with pytest.raises(DauRaTraLoiKhongDoc):
        _hoi_dap(engine, policy, "devops", khong_gian)
    assert llm.so_lan == 2, "sai kiểu không được kéo theo một lời gọi LLM thứ ba"


# --- Lớp 3: HTTP -------------------------------------------------------------------


def test_http_response_mang_tap_dung_audit_mang_tap_thay(monkeypatch):
    """Hàng AC: `citations` là tập dùng, `query.hyperedge_ids` là tập thấy, envelope không thêm khóa."""
    audit = AuditGia()
    engine = EngineGia(trich_dan=(_td("he-2"),), hyperedge_da_thay=("he-2", "he-1", "he-3"))
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        kq = _hoi(client, "dev01")
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert tuple(than) == ("answer", "refused", "citations", "graph", "meta")
    assert than["citations"] == [dict_trich_dan(_td("he-2"))]
    query = [sk for sk in audit.su_kien if sk.event == EVENT_QUERY]
    assert len(query) == 1 and query[0].hyperedge_ids == ("he-2", "he-1", "he-3")
    assert {c["id"] for c in than["citations"]} <= set(query[0].hyperedge_ids)


def test_http_nguon_sai_kieu_ra_502_khong_refusal_tren_engine_that(monkeypatch, workspace_dir, khong_gian, policy):
    """Hàng "`nguon` sai kiểu" ở tầng HTTP: 502 `DAU_RA_LLM_KHONG_DOC_DUOC`, không `refusal`, không `query`."""
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    llm.theo_prompt = phan_hoi_hai_luot(nguon=[0, "x"])
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        kq = _hoi(client, "dev01")
    assert kq.status_code == 502
    assert kq.json()["error"]["code"] == MA_DAU_RA_LLM_KHONG_DOC_DUOC
    assert [sk for sk in audit.su_kien if sk.event in (EVENT_REFUSAL, EVENT_QUERY)] == []


def test_http_nguon_hop_le_tren_engine_that_citation_la_tap_con_cua_audit(monkeypatch, workspace_dir, khong_gian, policy):
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    ngu_canh = _ngu_canh(engine, policy, "devops", khong_gian)
    hang = hang_hyperedge_trong(ngu_canh)
    llm.theo_prompt = phan_hoi_hai_luot(nguon=[hang[-1][0]])
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        kq = _hoi(client, "dev01")
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert [c["id"] for c in than["citations"]] == [hang[-1][1]]
    query = [sk for sk in audit.su_kien if sk.event == EVENT_QUERY][0]
    assert query.hyperedge_ids == id_hyperedge_trong(ngu_canh)
    assert len(query.hyperedge_ids) > len(than["citations"])


# --- Tương tác với grant break-glass (vòng review 3.8) --------------------------------


def test_m1_hyperedge_duoc_cap_luon_giu_citation_du_model_khong_liet_ke(workspace_dir, khong_gian, policy):
    """ADR-021 hứa hyperedge được cấp có mặt ở lượt hỏi lại; `nguon` bỏ dòng phụ thì citation vẫn giữ."""
    from tests.ngu_canh import vai
    from tests.test_break_glass_duong_phu import HE02, TS
    from tests.test_break_glass_duong_phu import _engine as _engine_grant

    engine, _, _, llm = _engine_grant(workspace_dir, khong_gian, policy)
    nc = vai(policy, TS, khong_gian, grant_ids=(HE02,))
    from core.permission import use_context

    async def _ngu_canh():
        with use_context(nc):
            return await engine.ngu_canh_hoi_dap("App01 trả lỗi 502 thì xử lý thế nào")
    chuoi = asyncio.run(_ngu_canh())
    hang = hang_hyperedge_trong(chuoi)
    stt_khac = [stt for stt, i in hang if i != HE02]
    assert stt_khac and any(i == HE02 for _, i in hang), "ngữ cảnh có grant phải mang dòng phụ của HE02"
    llm.theo_prompt = phan_hoi_hai_luot(nguon=[stt_khac[0]])

    async def _hoi():
        with use_context(nc):
            return await engine.hoi_dap("App01 trả lỗi 502 thì xử lý thế nào")
    kq = asyncio.run(_hoi())
    ids = [td.id for td in kq.trich_dan]
    assert HE02 in ids, "hyperedge được cấp phải giữ citation dù model không liệt kê dòng phụ"
    assert len(ids) == 2
