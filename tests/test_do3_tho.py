"""Đo 3 thô (story 3.8): hàm chấm thuần, vòng chạy với engine giả, ba rào, hai file kết quả.

Ba hàng của I/O Matrix có test tên riêng: một câu có 1/2 hyperedge trong ngữ
cảnh; kho trả `CAU_HONG_UPSTREAM` thành `tu_khoa_rong` 0/0 mà không dừng vòng;
space ngoài danh sách bị từ chối trước khi mở engine (mã thoát 2). Vòng chạy
dùng nhãn, bộ câu và ảnh chụp **thật của repo** cộng một engine giả trả khung
vendor chứa các id do test chọn, nên bảng tổng kiểm được bằng số đếm tay.
"""

import json
from pathlib import Path

import pytest

from adapters.policy_loader import load_policy
from adapters.tra_loi import CAU_HONG_UPSTREAM
from core.permission import current_context
from eval import do3_tho
from eval.cau_hoi import doc_anh_do_thi, doc_bo_cau_hoi, doc_nhan_truy_hoi
from eval.do3_tho import (
    CAU_HINH_PHAT_BIEU,
    THU_TU_PRD,
    Do3ThoTuChoi,
    cham_cau,
    dung_html,
    dung_ket_qua,
    mat_giua_hai_cau_hinh,
    thu_tu_cau_hinh,
    tong_hop,
)
from tests.fixtures import oracle
from tests.test_trich_dan import _bang_quan_he
from tests.test_tu_choi import khung_ngu_canh

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def nguon():
    anh = doc_anh_do_thi(REPO / "eval" / "anh_do_thi" / "synth.json")
    bo = doc_bo_cau_hoi()
    nhan = doc_nhan_truy_hoi(bo=bo, anh=anh)
    return anh, bo, nhan


def _policy(ma: str):
    return load_policy(REPO / "config" / f"policy-{ma}.yaml")


# --- Hàm thuần ------------------------------------------------------------------


def test_cham_mot_cau_mot_trong_hai_co_mat_va_slot_khong_bi_che(nguon):
    """Hàng "Đo 3 thô một câu": nhãn 2 hyperedge, ngữ cảnh có 1 -> 1/1, lý do nêu id vắng."""
    anh, bo, nhan = nguon
    n = nhan.theo_cau["n3-01"]
    cau = bo.theo_id["n3-01"]
    hang = _policy("day-du").role(cau.vai_hoi)
    co, vang = n.hyperedge[0].id, n.hyperedge[1].id
    kq = cham_cau(hang, n, anh.theo_id, [co, "he-la"], nhom=cau.nhom)
    assert (kq.tong, kq.ton_tai, kq.tra_loi_duoc) == (2, 1, 1)
    assert kq.co_mat == (co,) and kq.vang == (vang,)
    assert len(kq.ly_do) == 1 and vang in kq.ly_do[0] and "top-k" in kq.ly_do[0]
    assert kq.so_hyperedge_ngu_canh == 2 and kq.tu_khoa_rong is False


def test_cham_cau_lop_tra_loi_duoc_tut_khi_slot_dap_an_bi_che(nguon):
    """Cấu hình tối-thiểu-L1 che đủ 7 slot ở ô mới lên L1: có mặt nhưng không trả lời được."""
    anh, bo, nhan = nguon
    # Tìm một nhãn mà vai hỏi ở toi-thieu-l1 thấy L1 và slot đáp án bị che.
    policy = _policy("toi-thieu-l1")
    for n in nhan.nhan:
        cau = bo.theo_id[n.cau_id]
        hang = policy.role(cau.vai_hoi)
        for he in n.hyperedge:
            moc = anh.theo_id[he.id]
            if moc.khoa and hang.level(moc.content_type) == "L1" and set(hang.masked_slots.get(moc.content_type, ())) & set(he.slot_dap_an):
                kq = cham_cau(hang, n, anh.theo_id, [he.id], nhom=cau.nhom)
                assert kq.ton_tai >= 1 and kq.tra_loi_duoc < kq.ton_tai
                assert any("bị che" in l for l in kq.ly_do)
                return
    pytest.fail("không tìm được cặp nhãn L1 có slot đáp án bị che ở toi-thieu-l1")


def test_cham_cau_tu_khoa_rong_la_0_tren_0_va_mot_ly_do(nguon):
    """Hàng "kho trả CAU_HONG_UPSTREAM": 0/0, cờ bật, lý do nói `tu_khoa_rong`, không nói vì quyền."""
    anh, bo, nhan = nguon
    n = nhan.nhan[0]
    hang = _policy("day-du").role(bo.theo_id[n.cau_id].vai_hoi)
    kq = cham_cau(hang, n, anh.theo_id, (), nhom="N3", tu_khoa_rong=True)
    assert (kq.ton_tai, kq.tra_loi_duoc, kq.tu_khoa_rong) == (0, 0, True)
    assert kq.vang == tuple(h.id for h in n.hyperedge)
    assert len(kq.ly_do) == 1 and "tu_khoa_rong" in kq.ly_do[0]


def test_cham_cau_ly_do_vang_phan_loai_theo_quyen(nguon):
    """Vắng vì L0 và vắng vì scope nói khác nhau, và khác với "vắng dù được thấy"."""
    anh, bo, nhan = nguon
    # n5-05: tech_support hỏi, đáp án ở bi_mat_ha_tang (L0 với tech_support ở day-du).
    n = nhan.theo_cau["n5-05"]
    hang = _policy("day-du").role("tech_support")
    kq = cham_cau(hang, n, anh.theo_id, (), nhom="N5")
    assert kq.ton_tai == 0
    assert all("L0" in l or "scope" in l for l in kq.ly_do), kq.ly_do


def test_tong_hop_va_mat_giua_hai_cau_hinh(nguon):
    anh, bo, nhan = nguon
    n = nhan.theo_cau["n3-01"]
    hang = _policy("day-du").role("devops")
    du = cham_cau(hang, n, anh.theo_id, [h.id for h in n.hyperedge], nhom="N3")
    thieu = cham_cau(hang, n, anh.theo_id, [n.hyperedge[0].id], nhom="N3")
    th = tong_hop([du, thieu])
    assert th["tat_ca"] == {"so_cau": 2, "tong": 4, "ton_tai": 3, "tra_loi_duoc": 3, "recall_ton_tai": 0.75, "recall_tra_loi_duoc": 0.75}
    assert th["theo_nhom"]["N3"]["tong"] == 4 and th["so_cau_tu_khoa_rong"] == 0
    mat = mat_giua_hai_cau_hinh({"day-du": [du], "nhi-phan": [thieu]}, "day-du", "nhi-phan")
    assert mat == [{"cau_id": "n3-01", "nhom": "N3", "vai": "devops", "mat": [n.hyperedge[1].id], "ly_do": [thieu.ly_do[0]]}]
    assert mat_giua_hai_cau_hinh({"day-du": [du], "nhi-phan": [du]}, "day-du", "nhi-phan") == []


def test_thu_tu_cau_hinh_theo_prd_va_tu_choi_id_la(tmp_path):
    assert thu_tu_cau_hinh({m: Path() for m in THU_TU_PRD}) == ["tat-phan-quyen", "nhi-phan", "day-du", "toi-thieu-l1"]
    assert set(CAU_HINH_PHAT_BIEU) <= set(THU_TU_PRD)
    with pytest.raises(Do3ThoTuChoi):
        thu_tu_cau_hinh({"day-du": Path(), "la": Path()})


# --- Vòng chạy với engine giả -----------------------------------------------------


class EngineGiaDo3:
    """Trả khung vendor chứa đúng các id mà nhãn kỳ vọng cho câu hỏi, trừ những câu bị cắt.

    Ghi lại vai của ngữ cảnh quyền từng lời gọi để test chứng minh mỗi ô chạy
    dưới `vai_hoi` của chính câu đó.
    """

    def __init__(self, nhan, bo, *, bo_cau: set[str] = frozenset(), hong: set[str] = frozenset()):
        self.theo_cau_hoi = {bo.theo_id[n.cau_id].cau_hoi: n for n in nhan.nhan}
        self.bo_cau, self.hong = set(bo_cau), set(hong)
        self.vai_da_thay: list[tuple[str, str]] = []
        self.da_dong = False

    async def ngu_canh_hoi_dap(self, cau_hoi: str) -> str:
        n = self.theo_cau_hoi[cau_hoi]
        self.vai_da_thay.append((n.cau_id, current_context().role))
        if n.cau_id in self.hong:
            return CAU_HONG_UPSTREAM
        ids = [] if n.cau_id in self.bo_cau else [h.id for h in n.hyperedge]
        return khung_ngu_canh(relations=_bang_quan_he(*[[i, he, "x"] for i, he in enumerate(ids)]))

    async def dong(self):
        self.da_dong = True


def _chay_main(monkeypatch, tmp_path, engine, *argv):
    monkeypatch.setattr(do3_tho, "THU_MUC_KET_QUA", tmp_path / "kq")
    monkeypatch.setattr(do3_tho, "THU_MUC_EXPR", tmp_path / "expr")
    dong: list[str] = []
    rc = do3_tho.main(["--space", "synth", *argv], tao_engine=lambda so_audit: engine, in_ra=lambda *a, **k: dong.append(" ".join(str(x) for x in a)))
    return rc, dong


def test_vong_chay_du_bon_cau_hinh_hai_file_va_moi_o_duoi_vai_hoi(monkeypatch, tmp_path, nguon):
    anh, bo, nhan = nguon
    engine = EngineGiaDo3(nhan, bo, bo_cau={"n3-01"}, hong={"n5-01"})
    rc, dong = _chay_main(monkeypatch, tmp_path, engine)
    assert rc == 0, dong
    f_kq = tmp_path / "kq" / "do3-tho-synth.json"
    f_nc = tmp_path / "kq" / "do3-tho-synth-ngu-canh.json"
    kq = json.loads(f_kq.read_text(encoding="utf-8"))
    nc = json.loads(f_nc.read_text(encoding="utf-8"))
    assert list(kq["cau_hinh"]) == ["tat-phan-quyen", "nhi-phan", "day-du", "toi-thieu-l1"]
    assert kq["so_cau_co_nhan"] == 22 and engine.da_dong
    # Mỗi ô chạy dưới vai hỏi của chính câu đó, 88 lần.
    assert len(engine.vai_da_thay) == 88
    assert all(bo.theo_id[c].vai_hoi == vai for c, vai in engine.vai_da_thay)
    for ma, c in kq["cau_hinh"].items():
        assert c["policy_version"] == _policy(ma).policy_version
        assert c["so_cau_tu_khoa_rong"] == 1
        theo_id = {x["cau_id"]: x for x in c["cau"]}
        assert theo_id["n5-01"]["tu_khoa_rong"] is True and theo_id["n5-01"]["ton_tai"] == 0
        assert theo_id["n3-01"]["ton_tai"] == 0 and theo_id["n3-01"]["so_hyperedge_ngu_canh"] == 0
        assert len(nc["ngu_canh"][ma]) == 22 and nc["ngu_canh"][ma]["n5-01"] == CAU_HONG_UPSTREAM
    # Engine giả trả trọn nhãn nên tồn tại = tổng trừ hai câu bị cắt/hỏng ở mọi cấu hình.
    tong = nhan.so_cap()
    cat = len(nhan.theo_cau["n3-01"].hyperedge) + len(nhan.theo_cau["n5-01"].hyperedge)
    assert kq["cau_hinh"]["tat-phan-quyen"]["tat_ca"]["ton_tai"] == tong - cat
    # Lớp trả lời được ở tat-phan-quyen bằng lớp tồn tại (không slot nào bị che ở L2).
    assert kq["cau_hinh"]["tat-phan-quyen"]["tat_ca"]["tra_loi_duoc"] == tong - cat
    # Chi phí: engine giả không đi qua wrapper nên bằng 0, nhưng hình dạng phải có.
    assert set(kq["chi_phi"]) == {"so_loi_goi_llm", "so_loi_goi_embedding", "token_vao", "token_ra", "usd"}
    assert any("Đo 3 thô" in d for d in dong)


def test_file_da_co_doi_ghi_de_va_xem_dung_trang(monkeypatch, tmp_path, nguon):
    anh, bo, nhan = nguon
    engine = EngineGiaDo3(nhan, bo)
    assert _chay_main(monkeypatch, tmp_path, engine)[0] == 0
    rc, _ = _chay_main(monkeypatch, tmp_path, EngineGiaDo3(nhan, bo))
    assert rc == 1, "file đã có mà không --ghi-de phải từ chối"
    assert _chay_main(monkeypatch, tmp_path, EngineGiaDo3(nhan, bo), "--ghi-de")[0] == 0
    rc, dong = _chay_main(monkeypatch, tmp_path, None, "--xem")
    assert rc == 0
    trang = (tmp_path / "expr" / "do3_tho-synth.html").read_text(encoding="utf-8")
    assert "Đo 3 thô" in trang and "nhi-phan" in trang and "n3-01" in trang


def test_space_ngoai_danh_sach_bi_tu_choi_truoc_khi_mo_engine(monkeypatch, tmp_path, capsys):
    """Hàng "space ngoài danh sách": thoát 2, engine không được dựng."""
    goi = []
    rc = do3_tho.main(["--space", "that_khu"], tao_engine=lambda a: goi.append(1))
    assert rc == 2 and goi == []
    assert "that_khu" in capsys.readouterr().err


def test_uoc_tinh_khong_mo_engine(monkeypatch, tmp_path):
    goi = []
    dong = []
    rc = do3_tho.main(["--space", "synth", "--uoc-tinh"], tao_engine=lambda a: goi.append(1), in_ra=lambda *a: dong.append(a[0]))
    assert rc == 0 and goi == []
    assert "22 câu × 4 cấu hình = 88 ô" in dong[0] and "Embedding không ước" in dong[0]


def test_thieu_bien_moi_truong_thi_dung_truoc_engine(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(do3_tho, "THU_MUC_KET_QUA", tmp_path)
    for b in do3_tho.BIEN_BAT_BUOC:
        monkeypatch.delenv(b, raising=False)
    assert do3_tho.main(["--space", "synth"]) == 1
    assert "thiếu biến môi trường" in capsys.readouterr().err


def test_dung_ket_qua_va_html_thuan(nguon):
    anh, bo, nhan = nguon
    policies = {m: _policy(m) for m in THU_TU_PRD}
    thu_tu = thu_tu_cau_hinh({m: Path() for m in THU_TU_PRD})
    n = nhan.nhan[0]
    cau = bo.theo_id[n.cau_id]
    kq_cau = {m: [cham_cau(policies[m].role(cau.vai_hoi), n, anh.theo_id, [h.id for h in n.hyperedge], nhom=cau.nhom)] for m in thu_tu}
    kq = dung_ket_qua(space="synth", anh=anh, policies=policies, thu_tu=thu_tu, ket_qua=kq_cau,
                      chi_phi={"so_loi_goi_llm": 4, "so_loi_goi_embedding": 4, "token_vao": 1, "token_ra": 1, "usd": 0.0}, model={})
    assert kq["version"] == 1 and kq["mat_o_baseline_so_voi_van_hanh"] == []
    assert "<table>" in dung_html(kq)
    # Đúng thứ tự PRD cho oracle của 3.2: bốn file có thật.
    assert {oracle.POLICY_DAY_DU.name, oracle.POLICY_TAT_PHAN_QUYEN.name} <= {f"policy-{m}.yaml" for m in thu_tu}


# --- Vòng review 3.8 ------------------------------------------------------------------


def test_chi_phi_tu_doc_dung_hop_dong_chi_tiet_cua_wrapper():
    """Dùng đúng hằng `CT_*`/`EVENT_*`; khóa thiếu là lỗi, không phải 0 lặng lẽ."""
    from adapters.llm_wrapper import CT_CHI_PHI_USD, CT_TOKEN_RA, CT_TOKEN_VAO
    from core.audit import EVENT_EMBEDDING_COST, EVENT_LLM_COST, SuKienAudit, TIER_OBSERVATION, thoi_diem_utc
    from eval.do3_tho import chi_phi_tu
    from eval.do_trich_xuat import GomChiPhi

    so = GomChiPhi()
    def sk(event, **ct):
        return SuKienAudit(tier=TIER_OBSERVATION, event=event, space="synth", policy_version="v", thoi_diem=thoi_diem_utc(), chi_tiet=ct)
    so.su_kien += [
        sk(EVENT_LLM_COST, **{CT_TOKEN_VAO: 100, CT_TOKEN_RA: 40, CT_CHI_PHI_USD: 0.001}),
        sk(EVENT_LLM_COST, **{CT_TOKEN_VAO: 50, CT_TOKEN_RA: 10, CT_CHI_PHI_USD: 0.0005}),
        sk(EVENT_EMBEDDING_COST, **{CT_TOKEN_VAO: 7, CT_CHI_PHI_USD: 0.0001}),
        sk("query", x=1),
    ]
    assert chi_phi_tu(so) == {"so_loi_goi_llm": 2, "so_loi_goi_embedding": 1, "token_vao": 157, "token_ra": 50, "usd": 0.0016}
    so.su_kien.append(sk(EVENT_LLM_COST, **{CT_TOKEN_VAO: 1}))
    with pytest.raises(KeyError):
        chi_phi_tu(so)


def test_ghi_de_giu_bak_va_o_hong_giua_chung_giu_file_chua_xong(monkeypatch, tmp_path, nguon):
    anh, bo, nhan = nguon
    assert _chay_main(monkeypatch, tmp_path, EngineGiaDo3(nhan, bo))[0] == 0
    kq_dir = tmp_path / "kq"
    assert _chay_main(monkeypatch, tmp_path, EngineGiaDo3(nhan, bo), "--ghi-de")[0] == 0
    assert (kq_dir / "do3-tho-synth.bak.json").exists() and (kq_dir / "do3-tho-synth-ngu-canh.bak.json").exists()
    assert not (kq_dir / "do3-tho-synth-ngu-canh-chua-xong.json").exists(), "đợt xong thì xóa file dở"

    class EngineNo(EngineGiaDo3):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self.dem = 0
        async def ngu_canh_hoi_dap(self, cau_hoi):
            self.dem += 1
            if self.dem == 30:
                raise ConnectionError("mạng rớt")
            return await super().ngu_canh_hoi_dap(cau_hoi)

    rc, _ = _chay_main(monkeypatch, tmp_path, EngineNo(nhan, bo), "--ghi-de")
    assert rc == 1
    do = json.loads((kq_dir / "do3-tho-synth-ngu-canh-chua-xong.json").read_text(encoding="utf-8"))
    assert do["dang_do"] is True and sum(len(v) for v in do["ngu_canh"].values()) == 29


def test_xem_tu_choi_version_la_va_trang_mang_ten_space(monkeypatch, tmp_path, nguon, capsys):
    anh, bo, nhan = nguon
    assert _chay_main(monkeypatch, tmp_path, EngineGiaDo3(nhan, bo))[0] == 0
    assert _chay_main(monkeypatch, tmp_path, None, "--xem")[0] == 0
    assert (tmp_path / "expr" / "do3_tho-synth.html").exists()
    f = tmp_path / "kq" / "do3-tho-synth.json"
    f.write_text(json.dumps({"version": 99}), encoding="utf-8")
    assert _chay_main(monkeypatch, tmp_path, None, "--xem")[0] == 1
    assert "version" in capsys.readouterr().err


def test_thieu_cau_hinh_phat_bieu_la_tu_choi():
    with pytest.raises(Do3ThoTuChoi):
        thu_tu_cau_hinh({"tat-phan-quyen": Path(), "toi-thieu-l1": Path()})


def test_khong_dung_duoc_engine_la_ma_thoat_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(do3_tho, "THU_MUC_KET_QUA", tmp_path)
    def no(_): raise ValueError("thiếu LLM_MODEL")
    assert do3_tho.main(["--space", "synth"], tao_engine=no) == 1
    assert "không dựng được engine" in capsys.readouterr().err
