"""Phép chấm trích xuất, lược đồ file kết quả vòng đo và ngoại suy FR-30 (story 2.6).

Viết trước cơ chế (FR-27): mỗi hàng I/O Matrix của spec 2.6 là một test ở đây,
dựng bằng fact viết tay. Không mạng, không key, không kho - phép chấm và phép
ngoại suy đều là hàm thuần, còn runner tốn tiền chỉ được chạm tới qua hai thứ
không gọi LLM: lược đồ file kết quả (`doc_ket_qua`) và cửa ghi
(`ghi_ket_qua`).

Một luật xuyên suốt: **đơn vị chấm là slot đã điền**. Mọi assert đếm slot, kể
cả khi tiện tay hơn nếu đếm fact.
"""

import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from core.facts import MA_KHONG_PHAI_JSON, MA_THIEU_SUBJECT, MA_VAI_LA, id_fact
from core.slots import SLOT_ROLES
from eval.bo_vang import doc_bo_vang
from eval.cham_trich_xuat import (
    CHI_SO_GHEP_CAP,
    CHI_SO_MUC_TAI_LIEU,
    CONG_R2_CHI_SO,
    COT_MA_TRAN,
    HANG_MA_TRAN,
    KHOP_CHAT,
    KHOP_LONG,
    NGUONG_R2,
    VAI_THIEU,
    VAI_THUA,
    VERDICT_DAT,
    VERDICT_DUOI,
    VERDICT_KHONG_CHAM_DUOC,
    ChiSo,
    cap_vai_lan_nhieu_nhat,
    cham_bo,
    cham_bo_muc_tai_lieu,
    cham_muc_tai_lieu,
    cham_tai_lieu,
    ma_tran_lan_lon,
    mau_so_phu,
    theo_vai,
    verdict_r2,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# sha256 của bộ vàng tại lần đo 02/09/2026. Mọi con số khóa trong file này đo
# trên đúng bản đó; đổi một nhãn tay là mọi con số đổi, nên hằng này đứng cùng
# chỗ với chúng.
BAM_BO_VANG = "76afee13422a424028cd51f3731f3f85184e8294521bd8401d69de2b0933a333"


@pytest.fixture(scope="module")
def bo_vang():
    return doc_bo_vang()


# ---------------------------------------------------------------------------
# Ghép cặp: neo ở `subject`
# ---------------------------------------------------------------------------


def test_ghep_duoc_cap_cung_subject_va_cham_tung_vai():
    """Hàng 'Ghép được cặp': cùng `subject` sau chuẩn hóa thì ghép một-một."""
    vang = [{"subject": "App01", "symptom": "trang thanh toán trả lỗi 502"}]
    pred = [{"subject": "app01", "symptom": "trang thanh toán trả lỗi 502"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert len(kq.cap) == 1
    assert kq.vang_khong_ghep == () and kq.pred_khong_ghep == ()
    assert kq.ket_qua.chi_so.recall == pytest.approx(1.0)
    assert kq.ket_qua.chi_so.precision == pytest.approx(1.0)


def test_nhieu_ung_vien_chon_cap_chong_lap_cao_nhat_con_lai_thanh_fp():
    """Hàng 'Nhiều ứng viên': fact pipeline thua cuộc thành FP, không biến mất."""
    vang = [{"subject": "VPN", "condition": "quá 3 lần sai", "remediation": "khóa tài khoản"}]
    pred = [
        {"subject": "VPN", "condition": "quá 3 lần sai", "remediation": "khóa tài khoản"},
        {"subject": "VPN", "owner": "phòng IT"},
    ]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert len(kq.cap) == 1
    assert len(kq.pred_khong_ghep) == 1
    assert kq.pred_khong_ghep[0]["owner"] == "phòng IT"
    # 3 slot vàng khớp hết; 2 slot của fact thua cuộc thành FP.
    cs = kq.ket_qua.chi_so
    assert (cs.tp, cs.fn, cs.fp) == (3, 0, 2)


def test_nhieu_ung_vien_hoa_diem_thi_id_fact_nho_hon_thang():
    vang = [{"subject": "VPN", "condition": "quá 3 lần sai"}]
    a = {"subject": "VPN", "condition": "quá 3 lần sai"}
    b = {"subject": "VPN", "condition": "quá 3 lần sai", "owner": "phòng IT"}
    # Hai ứng viên cùng số slot vàng khớp được (2); trọng tài là `id_fact`.
    thang = min(id_fact(a), id_fact(b))
    kq = cham_tai_lieu(vang, [a, b], doc_key="d")
    assert kq.cap[0].id_pred == thang


def test_fact_vang_khong_ghep_thi_moi_slot_la_fn():
    """Hàng 'Fact vàng không ghép': không ca nào rơi ra ngoài sổ."""
    vang = [{"subject": "App01", "cause": "chỉnh sai giới hạn bộ nhớ"}]
    pred = [{"subject": "App02", "cause": "chỉnh sai giới hạn bộ nhớ"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap == ()
    assert len(kq.vang_khong_ghep) == 1 and len(kq.pred_khong_ghep) == 1
    cs = kq.ket_qua.chi_so
    assert (cs.tp, cs.fn, cs.fp) == (0, 2, 2)
    ma_tran = ma_tran_lan_lon(kq.ket_qua)
    assert ma_tran["subject"][VAI_THIEU] == 1
    assert ma_tran["cause"][VAI_THIEU] == 1
    assert ma_tran[VAI_THUA]["subject"] == 1


def test_fact_pipeline_khong_ghep_thi_moi_slot_la_fp():
    vang = [{"subject": "App01", "cause": "hết dung lượng đĩa"}]
    pred = [
        {"subject": "App01", "cause": "hết dung lượng đĩa"},
        {"subject": "Máy in tầng 3", "symptom": "kẹt giấy"},
    ]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    cs = kq.ket_qua.chi_so
    assert (cs.tp, cs.fn, cs.fp) == (2, 0, 2)
    assert cs.precision == pytest.approx(0.5)
    assert cs.recall == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Chấm trong một cặp: chặt, lỏng, lẫn vai, thiếu, thừa
# ---------------------------------------------------------------------------


def test_khop_chat_dem_rieng_cot_khop_chat():
    vang = [{"subject": "App01", "remediation": "khởi động lại dịch vụ"}]
    pred = [{"subject": "App01", "remediation": "Khởi  động lại dịch vụ"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap[0].khop == {"subject": KHOP_CHAT, "remediation": KHOP_CHAT}
    cs = kq.ket_qua.chi_so
    assert cs.chat == 2 and cs.long == 0
    assert cs.precision_chat == pytest.approx(1.0)


def test_khop_long_la_chuoi_con_khong_vao_cot_khop_chat():
    """Hàng 'Khớp lỏng': hai đoạn của cùng một câu, quan hệ tự nhiên là chuỗi con."""
    vang = [{"subject": "App01", "remediation": "trả giới hạn bộ nhớ về mức cũ"}]
    pred = [{"subject": "App01", "remediation": "trả giới hạn bộ nhớ về mức cũ rồi khởi động lại"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap[0].khop["remediation"] == KHOP_LONG
    cs = kq.ket_qua.chi_so
    assert cs.chat == 1 and cs.long == 1 and cs.tp == 2
    # Số chính là khớp lỏng; khớp chặt vẫn in kèm để thấy độ trôi câu chữ.
    assert cs.recall == pytest.approx(1.0)
    assert cs.recall_chat == pytest.approx(0.5)


def test_lan_vai_vao_o_v_w_va_tinh_fn_cho_v_fp_cho_w():
    """Hàng 'Lẫn vai': đúng chữ mà sai vai không phải TP - đó là câu hỏi của A13."""
    vang = [{"subject": "App01", "cause": "quá 90% dung lượng đĩa"}]
    pred = [{"subject": "App01", "condition": "quá 90% dung lượng đĩa"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap[0].lan_vai == (("cause", "condition"),)
    ma_tran = ma_tran_lan_lon(kq.ket_qua)
    assert ma_tran["cause"]["condition"] == 1
    assert ma_tran["cause"][VAI_THIEU] == 0
    vai = theo_vai(kq.ket_qua)
    assert vai["cause"].fn == 1 and vai["cause"].tp == 0
    assert vai["condition"].fp == 1 and vai["condition"].tp == 0
    cs = kq.ket_qua.chi_so
    assert (cs.tp, cs.fn, cs.fp) == (1, 1, 1)


def test_thieu_vai_vao_o_v_thieu():
    vang = [{"subject": "App01", "owner": "Trần Thị Hạnh", "time": "09:20"}]
    pred = [{"subject": "App01", "owner": "Trần Thị Hạnh"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap[0].thieu == ("time",)
    assert ma_tran_lan_lon(kq.ket_qua)["time"][VAI_THIEU] == 1
    assert theo_vai(kq.ket_qua)["time"].fn == 1


def test_thua_vai_vao_o_thua_w():
    vang = [{"subject": "App01", "owner": "Trần Thị Hạnh"}]
    pred = [{"subject": "App01", "owner": "Trần Thị Hạnh", "source": "SOP-12"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap[0].thua == ("source",)
    assert ma_tran_lan_lon(kq.ket_qua)[VAI_THUA]["source"] == 1
    assert theo_vai(kq.ket_qua)["source"].fp == 1


def test_moi_gia_tri_pred_chi_duoc_tieu_thu_mot_lan():
    """Chống nuốt cả câu: một giá trị pred dài không ăn điểm ở hai vai vàng."""
    vang = [{"subject": "sao lưu", "condition": "hằng ngày", "time": "hằng ngày"}]
    pred = [{"subject": "sao lưu", "condition": "hằng ngày"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    cs = kq.ket_qua.chi_so
    assert cs.tp == 2, "vai `time` không được ăn ké giá trị đã dùng cho `condition`"
    assert cs.fn == 1
    assert kq.cap[0].thieu == ("time",)


def test_ghep_chat_truoc_ghep_long_sau():
    """Giá trị pred khớp chặt một vai và khớp lỏng vai khác thì phần chặt thắng."""
    vang = [{"subject": "VPN", "remediation": "đổi mật khẩu", "condition": "đổi mật khẩu định kỳ"}]
    pred = [{"subject": "VPN", "condition": "đổi mật khẩu định kỳ", "remediation": "đổi mật khẩu"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap[0].khop == {
        "subject": KHOP_CHAT,
        "condition": KHOP_CHAT,
        "remediation": KHOP_CHAT,
    }


def test_thu_tu_vai_theo_slot_roles():
    """Hai vai vàng cùng tranh một giá trị pred: vai đứng trước trong danh mục thắng."""
    # `cause` đứng trước `remediation` trong SLOT_ROLES.
    vang = [{"subject": "App01", "cause": "khóa phiên", "remediation": "khóa phiên"}]
    pred = [{"subject": "App01", "remediation": "khóa phiên"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    assert kq.cap[0].khop == {"subject": KHOP_CHAT, "remediation": KHOP_CHAT}
    assert kq.cap[0].thieu == ("cause",)


def test_tai_lieu_khong_co_fact_hop_le_nao():
    """Hàng 'Tài liệu 0 fact hợp lệ': recall 0, precision không chia cho 0."""
    vang = [{"subject": "App01", "cause": "hết đĩa"}]
    kq = cham_tai_lieu(vang, [], doc_key="d")
    cs = kq.ket_qua.chi_so
    assert cs.recall == pytest.approx(0.0)
    assert cs.precision is None
    assert cs.f1 is None
    assert cs.fn == 2 and cs.fp == 0


def test_khong_co_fact_vang_lan_pred_thi_moi_chi_so_la_none():
    cs = cham_tai_lieu([], [], doc_key="d").ket_qua.chi_so
    assert cs.precision is None and cs.recall is None and cs.f1 is None


# ---------------------------------------------------------------------------
# Ma trận lẫn lộn và bất biến của nó
# ---------------------------------------------------------------------------


def test_ma_tran_du_hang_du_cot_va_khong_co_o_thua_thieu():
    kq = cham_tai_lieu([{"subject": "a", "cause": "b"}], [{"subject": "a", "cause": "b"}], doc_key="d")
    ma_tran = ma_tran_lan_lon(kq.ket_qua)
    assert tuple(ma_tran) == HANG_MA_TRAN == SLOT_ROLES + (VAI_THUA,)
    for hang in ma_tran.values():
        assert tuple(hang) == COT_MA_TRAN == SLOT_ROLES + (VAI_THIEU,)
    assert ma_tran[VAI_THUA][VAI_THIEU] == 0, "ô (thừa, thiếu) không có nghĩa gì"


def test_tong_hang_bang_so_slot_vang_tong_cot_bang_so_slot_pred():
    """Bất biến sổ sách: không slot nào rơi ra ngoài ma trận."""
    vang = [
        {"subject": "App01", "cause": "hết đĩa", "remediation": "dọn log"},
        {"subject": "VPN", "condition": "quá 3 lần sai"},
    ]
    pred = [
        {"subject": "App01", "condition": "hết đĩa", "owner": "phòng IT"},
        {"subject": "Máy in", "symptom": "kẹt giấy"},
    ]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    ma_tran = ma_tran_lan_lon(kq.ket_qua)
    for vai in SLOT_ROLES:
        assert sum(ma_tran[vai].values()) == kq.ket_qua.vang_theo_vai[vai]
        assert sum(ma_tran[h][vai] for h in HANG_MA_TRAN) == kq.ket_qua.pred_theo_vai[vai]
    # Ô trong vùng vai×vai tiêu thụ một slot vàng và một slot pred cùng lúc
    # (khớp đúng vai hoặc lẫn vai), nên tổng ô ít hơn tổng hai phía đúng bấy nhiêu.
    o_ghep = sum(ma_tran[v][w] for v in SLOT_ROLES for w in SLOT_ROLES)
    assert sum(sum(h.values()) for h in ma_tran.values()) == (
        kq.ket_qua.chi_so.so_vang + kq.ket_qua.chi_so.so_pred - o_ghep
    )
    assert o_ghep == kq.ket_qua.chi_so.tp + 1, "một ô lẫn vai cause -> condition"


def test_duong_cheo_ma_tran_bang_tp_tung_vai():
    vang = [{"subject": "App01", "cause": "hết đĩa"}]
    pred = [{"subject": "App01", "cause": "hết đĩa"}]
    kq = cham_tai_lieu(vang, pred, doc_key="d")
    ma_tran = ma_tran_lan_lon(kq.ket_qua)
    vai = theo_vai(kq.ket_qua)
    for v in SLOT_ROLES:
        assert ma_tran[v][v] == vai[v].tp


# ---------------------------------------------------------------------------
# Chấm cả bộ và mẫu số phụ
# ---------------------------------------------------------------------------


def test_cham_bo_lay_mau_so_tu_bo_vang_khong_tinh_lai(bo_vang):
    """Mẫu số là `BoVang.mau_so_slot()`, và tài liệu few-shot không được chấm."""
    pred = {t.doc_key: [dict(f.slots) for f in t.facts] for t in bo_vang.tai_lieu_cham()}
    kq = cham_bo(bo_vang, pred)
    assert kq.chi_so.so_vang == bo_vang.mau_so_slot()
    assert kq.chi_so.precision == pytest.approx(1.0)
    assert kq.chi_so.recall == pytest.approx(1.0)
    assert kq.chi_so.f1 == pytest.approx(1.0)


def test_cham_bo_tu_choi_doc_key_cua_tai_lieu_few_shot(bo_vang):
    few = bo_vang.tai_lieu_few_shot()[0].doc_key
    pred = {t.doc_key: [] for t in bo_vang.tai_lieu_cham()}
    pred[few] = []
    with pytest.raises(ValueError) as e:
        cham_bo(bo_vang, pred)
    assert few in str(e.value)


def test_cham_bo_tu_choi_thieu_tai_lieu_cham(bo_vang):
    pred = {t.doc_key: [] for t in bo_vang.tai_lieu_cham()}
    thieu = sorted(pred)[0]
    del pred[thieu]
    with pytest.raises(ValueError) as e:
        cham_bo(bo_vang, pred)
    assert thieu in str(e.value)


def test_cham_bo_khong_fact_nao_thi_recall_0_precision_none(bo_vang):
    kq = cham_bo(bo_vang, {t.doc_key: [] for t in bo_vang.tai_lieu_cham()})
    assert kq.chi_so.recall == pytest.approx(0.0)
    assert kq.chi_so.precision is None
    assert kq.chi_so.so_vang == bo_vang.mau_so_slot()


def test_mau_so_phu_bo_subject(bo_vang):
    """`subject` bắt buộc theo lược đồ nên nó không phân biệt prompt tốt với tồi."""
    pred = {t.doc_key: [dict(f.slots) for f in t.facts] for t in bo_vang.tai_lieu_cham()}
    kq = cham_bo(bo_vang, pred)
    phu = mau_so_phu(kq)
    assert phu.so_vang == kq.chi_so.so_vang - kq.vang_theo_vai["subject"]
    assert phu.so_vang < kq.chi_so.so_vang
    assert phu.recall == pytest.approx(1.0)


def test_theo_vai_du_tam_vai_ke_ca_vai_khong_co_gi(bo_vang):
    kq = cham_bo(bo_vang, {t.doc_key: [] for t in bo_vang.tai_lieu_cham()})
    vai = theo_vai(kq)
    assert tuple(vai) == SLOT_ROLES
    assert all(c.tp == 0 for c in vai.values())


def test_chi_so_cong_duoc_de_gop_tung_tai_lieu():
    a = cham_tai_lieu([{"subject": "x", "cause": "y"}], [{"subject": "x", "cause": "y"}], doc_key="a")
    b = cham_tai_lieu([{"subject": "z", "cause": "w"}], [], doc_key="b")
    tong = a.ket_qua + b.ket_qua
    assert tong.chi_so.so_vang == 4 and tong.chi_so.tp == 2
    assert tong.chi_so.recall == pytest.approx(0.5)


def test_chi_so_f1_la_trung_binh_dieu_hoa():
    cs = ChiSo(so_vang=4, so_pred=2, chat=2, long=0)
    assert cs.precision == pytest.approx(1.0)
    assert cs.recall == pytest.approx(0.5)
    assert cs.f1 == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# File kết quả vòng đo: lược đồ và cửa ghi
# ---------------------------------------------------------------------------


def _vong_toi_thieu(phan_hoi: str = '{"facts": [{"subject": "App01", "cause": "hết đĩa"}]}') -> dict:
    return {
        "version": 1,
        "vong": "v-test",
        "model": "deepseek-v4-flash",
        "nha_cung_cap": "deepseek",
        "thoi_diem": "2026-09-02T10:00:00+00:00",
        "danh_muc_version": "abc123",
        "prompt": "PROMPT <<VAN_BAN>>",
        "tham_so_llm": {"temperature": 0},
        "chunk": {"chunk_token_size": 1200, "chunk_overlap_token_size": 100, "tiktoken_model_name": "gpt-4o"},
        "tai_lieu": [
            {
                "doc_key": "02-vpn-va-mat-khau.txt",
                "chunks": [
                    {
                        "stt": 0,
                        "van_ban": "thân chunk",
                        "phan_hoi": phan_hoi,
                        "token_vao": 100,
                        "token_ra": 20,
                        "chi_phi_usd": 0.0001,
                    }
                ],
            }
        ],
    }


def test_doc_ket_qua_doc_lai_fact_tho_va_dem_ma_loai(tmp_path):
    from eval.do_trich_xuat import doc_ket_qua

    p = tmp_path / "v-test.json"
    p.write_text(
        json.dumps(
            _vong_toi_thieu(
                '{"facts": [{"subject": "App01", "cause": "hết đĩa"},'
                ' {"cause": "thiếu subject"}, {"subject": "x", "vai_la": "y"}]}'
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    kq = doc_ket_qua(p)
    assert kq.vong == "v-test" and kq.model == "deepseek-v4-flash"
    assert kq.facts_theo_tai_lieu()["02-vpn-va-mat-khau.txt"] == [
        {"subject": "App01", "cause": "hết đĩa"}
    ]
    assert kq.loai_theo_ma() == {MA_THIEU_SUBJECT: 1, MA_VAI_LA: 1}
    assert kq.so_fact_tho() == 3 and kq.so_hop_le() == 1
    assert kq.ty_le_loai() == pytest.approx(2 / 3)
    assert (kq.token_vao(), kq.token_ra()) == (100, 20)
    assert kq.chi_phi_usd() == pytest.approx(0.0001)


def test_doc_ket_qua_dem_chunk_hong(tmp_path):
    from eval.do_trich_xuat import doc_ket_qua

    p = tmp_path / "v-test.json"
    p.write_text(json.dumps(_vong_toi_thieu("không phải json")), encoding="utf-8")
    kq = doc_ket_qua(p)
    assert kq.so_chunk_hong() == 1
    assert kq.loai_theo_ma() == {MA_KHONG_PHAI_JSON: 1}


@pytest.mark.parametrize(
    "sua,manh",
    [
        (lambda d: d.pop("prompt"), "prompt"),
        (lambda d: d.update(version=99), "version"),
        (lambda d: d.update(khoa_la=1), "khoa_la"),
        (lambda d: d.update(tai_lieu=[]), "tai_lieu"),
        (lambda d: d["tai_lieu"][0].pop("doc_key"), "doc_key"),
        (lambda d: d["tai_lieu"][0].update(la=1), "la"),
        (lambda d: d["tai_lieu"][0]["chunks"][0].pop("phan_hoi"), "phan_hoi"),
        (lambda d: d["tai_lieu"][0]["chunks"][0].update(token_vao="nhiều"), "token_vao"),
        (lambda d: d.update(vong=""), "vong"),
    ],
)
def test_file_ket_qua_sai_luoc_do_bi_tu_choi(tmp_path, sua, manh):
    from eval.do_trich_xuat import KetQuaDoKhongHopLe, doc_ket_qua

    d = _vong_toi_thieu()
    sua(d)
    p = tmp_path / "v-test.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KetQuaDoKhongHopLe) as e:
        doc_ket_qua(p)
    assert e.value.code == "KET_QUA_DO_KHONG_HOP_LE"
    assert manh in str(e.value) and p.name in str(e.value)


def test_file_ket_qua_json_hong_bi_tu_choi(tmp_path):
    from eval.do_trich_xuat import KetQuaDoKhongHopLe, doc_ket_qua

    p = tmp_path / "v-test.json"
    p.write_text("{khong phai json", encoding="utf-8")
    with pytest.raises(KetQuaDoKhongHopLe):
        doc_ket_qua(p)


def test_ten_vong_trong_file_phai_khop_ten_file(tmp_path):
    from eval.do_trich_xuat import KetQuaDoKhongHopLe, doc_ket_qua

    d = _vong_toi_thieu()
    d["vong"] = "vong-khac"
    p = tmp_path / "v-test.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KetQuaDoKhongHopLe) as e:
        doc_ket_qua(p)
    assert "vong-khac" in str(e.value)


def test_ghi_de_file_da_co_bi_tu_choi_neu_khong_co_co(tmp_path):
    """Hàng 'Chạy trùng tên vòng': tiền đã tiêu rồi, không ghi đè lặng lẽ."""
    from eval.do_trich_xuat import CO_GHI_DE, KetQuaDoDaCo, ghi_ket_qua

    p = tmp_path / "v-test.json"
    ghi_ket_qua(p, _vong_toi_thieu())
    with pytest.raises(KetQuaDoDaCo) as e:
        ghi_ket_qua(p, _vong_toi_thieu())
    assert e.value.code == "KET_QUA_DO_DA_CO"
    assert p.name in str(e.value) and CO_GHI_DE in str(e.value)
    ghi_ket_qua(p, _vong_toi_thieu(), ghi_de=True)


def test_ghi_ket_qua_roi_doc_lai_ra_dung_thu_da_ghi(tmp_path):
    from eval.do_trich_xuat import doc_ket_qua, ghi_ket_qua

    p = tmp_path / "v-test.json"
    ghi_ket_qua(p, _vong_toi_thieu())
    assert doc_ket_qua(p).prompt == "PROMPT <<VAN_BAN>>"


def test_doc_moi_vong_sap_theo_ten(tmp_path):
    from eval.do_trich_xuat import doc_moi_vong, ghi_ket_qua

    for ten in ("v1-b", "v0-a"):
        d = _vong_toi_thieu()
        d["vong"] = ten
        ghi_ket_qua(tmp_path / f"{ten}.json", d)
    assert [v.vong for v in doc_moi_vong(tmp_path)] == ["v0-a", "v1-b"]


def test_bon_vong_cua_repo_doc_duoc_va_cham_duoc(bo_vang):
    """Bốn file kết quả có commit phải nạp được và chấm được, không cần LLM."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong

    vong = doc_moi_vong(THU_MUC_KET_QUA)
    assert len(vong) >= 4, "story 2.6 chốt bốn vòng"
    for v in vong:
        kq = cham_bo(bo_vang, v.facts_theo_tai_lieu())
        assert kq.chi_so.so_vang == bo_vang.mau_so_slot()


def test_vong_0_chay_tren_prompt_truoc_khi_sua_vi_du_time():
    """Mốc so với lần nạp thật 2.4: vòng 0 giữ nguyên văn prompt cũ."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_ket_qua

    v0 = doc_ket_qua(THU_MUC_KET_QUA / "v0-deepseek-goc.json")
    assert '"time": "2026-08-12 09:20"' in v0.prompt
    v1 = doc_ket_qua(THU_MUC_KET_QUA / "v1-deepseek.json")
    assert '"time": "2026-08-12 09:20"' not in v1.prompt
    assert "12/08/2026 lúc 09:20" in v1.prompt


# ---------------------------------------------------------------------------
# Ngoại suy FR-30
# ---------------------------------------------------------------------------


def test_ngoai_suy_du_sau_khoan_co_tong_va_doi_chieu_bao_dong():
    from eval.ngoai_suy import MUC_BAO_DONG_USD, SoDoNap, ngoai_suy

    bang = ngoai_suy(SoDoNap(so_tai_lieu=8, token_vao_llm=20000, token_ra_llm=4000,
                             chi_phi_llm_usd=0.014, token_embedding=6000,
                             chi_phi_embedding_usd=0.0002))
    assert len(bang.khoan) == 6
    assert bang.tong_usd == pytest.approx(sum(k.chi_phi_usd for k in bang.khoan))
    assert bang.muc_bao_dong_usd == MUC_BAO_DONG_USD == 60.0
    assert bang.vuot_bao_dong is (bang.tong_usd > 60.0)
    assert all(k.chi_phi_usd >= 0 for k in bang.khoan)
    assert all(k.model for k in bang.khoan)


def test_ngoai_suy_ty_le_thuan_voi_so_tai_lieu_corpus():
    from eval.ngoai_suy import GiaDinh, SoDoNap, ngoai_suy

    do = SoDoNap(so_tai_lieu=8, token_vao_llm=20000, token_ra_llm=4000,
                 chi_phi_llm_usd=0.014, token_embedding=6000, chi_phi_embedding_usd=0.0002)
    mot = ngoai_suy(do, gia_dinh=GiaDinh(so_tai_lieu_corpus=40))
    hai = ngoai_suy(do, gia_dinh=GiaDinh(so_tai_lieu_corpus=80))
    assert hai.khoan_theo_ten("nap_corpus").chi_phi_usd == pytest.approx(
        2 * mot.khoan_theo_ten("nap_corpus").chi_phi_usd
    )


def test_ngoai_suy_khoan_nap_corpus_dung_so_do_that():
    from eval.ngoai_suy import GiaDinh, SoDoNap, ngoai_suy

    do = SoDoNap(so_tai_lieu=8, token_vao_llm=20000, token_ra_llm=4000,
                 chi_phi_llm_usd=0.02, token_embedding=6000, chi_phi_embedding_usd=0.001)
    bang = ngoai_suy(do, gia_dinh=GiaDinh(so_tai_lieu_corpus=8))
    assert bang.khoan_theo_ten("nap_corpus").chi_phi_usd == pytest.approx(0.021)


def test_ngoai_suy_so_do_khong_co_tai_lieu_nao_la_loi():
    from eval.ngoai_suy import SoDoNap, ngoai_suy

    with pytest.raises(ValueError):
        ngoai_suy(SoDoNap(so_tai_lieu=0, token_vao_llm=0, token_ra_llm=0, chi_phi_llm_usd=0,
                          token_embedding=0, chi_phi_embedding_usd=0))


def test_ngoai_suy_noi_ro_don_gia_la_can_tren():
    from eval.ngoai_suy import GHI_CHU_DON_GIA

    assert "cận trên" in GHI_CHU_DON_GIA and "hóa đơn" in GHI_CHU_DON_GIA


def test_gpt_4o_co_trong_danh_muc_model():
    """Bậc 1 của R2 là GPT-4o toàn phần: đơn giá phải có trước khi ngoại suy."""
    from adapters.model_catalog import LOAI_LLM, danh_muc_mac_dinh

    muc = danh_muc_mac_dinh().muc("gpt-4o", loai=LOAI_LLM)
    assert muc.nha_cung_cap == "openai"
    assert muc.gia_vao_usd_1m > 0 and muc.gia_ra_usd_1m > 0


# ---------------------------------------------------------------------------
# Trang báo cáo
# ---------------------------------------------------------------------------


def test_trang_bao_cao_thu_muc_rong_thi_in_lenh_can_chay_va_tra_1(tmp_path, capsys):
    from eval.xem_do_trich_xuat import main

    ma = main(dich=tmp_path / "t.html", thu_muc_ket_qua=tmp_path / "rong")
    assert ma == 1
    ra = capsys.readouterr()
    assert "eval.do_trich_xuat" in (ra.out + ra.err)


def test_trang_bao_cao_co_bang_so_ma_tran_va_verdict(tmp_path, capsys):
    from eval.xem_do_trich_xuat import main

    dich = tmp_path / "do_trich_xuat.html"
    assert main(dich=dich) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "Ma trận lẫn lộn" in trang
    assert "mẫu số phụ" in trang.lower()
    assert "60" in trang and "R2" in trang
    for vai in SLOT_ROLES:
        assert vai in trang
    assert VAI_THIEU in trang and VAI_THUA in trang
    ra = capsys.readouterr().out
    assert "R2" in ra


def test_trang_bao_cao_khong_goi_llm_nao(tmp_path, monkeypatch):
    """Đổi luật chấm rồi render lại là việc của fact thô đã lưu, không tốn tiền."""
    import openai

    def cam(*a, **k):
        raise AssertionError("trang báo cáo không được gọi LLM")

    monkeypatch.setattr(openai, "AsyncOpenAI", cam)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from eval.xem_do_trich_xuat import main

    assert main(dich=tmp_path / "t.html") == 0


def test_chay_bang_python_m_eval_xem_do_trich_xuat(tmp_path):
    ket_qua = subprocess.run(
        [sys.executable, "-m", "eval.xem_do_trich_xuat", str(tmp_path / "t.html")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert ket_qua.returncode == 0, ket_qua.stderr
    assert (tmp_path / "t.html").exists()
    assert "R2" in ket_qua.stdout


# ===========================================================================
# Vòng review 1: chỉ số mức tài liệu, verdict có assert, và các khóa số
# ===========================================================================


def test_chi_so_muc_tai_lieu_mu_do_hat_fact():
    """Hàng I/O 'Chỉ số mức tài liệu': đúng vai ở *fact khác* vẫn là TP.

    Đây là ca mà LLM gom hai câu của nhãn tay vào một fact: ranh giới fact khác
    nhau nhưng vai dán đúng, và câu hỏi của R2 là vai.
    """
    vang = [
        {"subject": "App01", "cause": "hết dung lượng đĩa"},
        {"subject": "App01", "remediation": "dọn log cũ"},
    ]
    pred = [{"subject": "App01", "cause": "hết dung lượng đĩa", "remediation": "dọn log cũ"}]
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    assert muc.ket_qua.chi_so.tp == 3, "cả `cause` lẫn `remediation` đều đúng vai"
    assert muc.vang_han == () and muc.lan_vai == ()
    # Chỉ số ghép cặp phạt đúng ca này: một fact vàng không tìm được bạn.
    cap = cham_tai_lieu(vang, pred, doc_key="d")
    assert cap.ket_qua.chi_so.tp < muc.ket_qua.chi_so.tp
    assert cap.ket_qua.so_fact_vang_khong_ghep == 1


def test_lan_vai_xuyen_fact_vao_o_v_w_cua_ma_tran_a13():
    """Hàng I/O 'Lẫn vai xuyên fact': giá trị vàng vai `v` chỉ có ở vai `w` của fact khác."""
    vang = [{"subject": "thay đổi khẩn cấp", "time": "trong 24 giờ"}]
    pred = [
        {"subject": "thay đổi khẩn cấp", "remediation": "bổ sung phiếu trong 24 giờ"},
    ]
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    assert [(k.vai_vang, k.vai_pred) for k in muc.lan_vai] == [("time", "remediation")]
    assert ma_tran_lan_lon(muc.ket_qua)["time"]["remediation"] == 1
    assert muc.ket_qua.so_lan_vai == 1
    assert muc.vang_han == (), "giá trị có mặt, chỉ sai vai - không phải bỏ sót"


def test_luot_quy_loi_khong_tieu_thu_nen_ho_nuot_bi_nhieu_slot_chi_mat():
    """Một `remediation` nuốt cả câu phải bị *nhiều* slot vàng cùng chỉ mặt.

    Đây là dấu hiệu "hố nuốt" mà A13 cần thấy; tiêu thụ ở lượt quy lỗi sẽ chỉ
    ghi được một ô rồi đẩy phần còn lại sang cột "thiếu", tức lại đọc thành bỏ sót.
    """
    vang = [{"subject": "phiếu thay đổi", "time": "trong 24 giờ", "owner": "Hội đồng thay đổi"}]
    pred = [
        {
            "subject": "phiếu thay đổi",
            "remediation": "Hội đồng thay đổi duyệt phiếu trong 24 giờ",
        }
    ]
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    ma_tran = ma_tran_lan_lon(muc.ket_qua)
    assert ma_tran["time"]["remediation"] == 1
    assert ma_tran["owner"]["remediation"] == 1
    assert muc.ket_qua.so_o_thieu == 0 and muc.ket_qua.so_vang_han == 0
    # Cái giá đã ghi trong docstring: tổng cột lớn hơn số slot pred của vai đó.
    assert sum(ma_tran[h]["remediation"] for h in HANG_MA_TRAN) > muc.ket_qua.pred_theo_vai["remediation"]


def test_vang_han_moi_la_bo_sot_that():
    """Hàng I/O 'Vắng hẳn': giá trị không xuất hiện ở bất kỳ giá trị pred nào."""
    vang = [{"subject": "App01", "source": "SOP-12"}]
    pred = [{"subject": "App01", "remediation": "khởi động lại dịch vụ"}]
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    assert muc.vang_han == (("source", "SOP-12"),)
    assert ma_tran_lan_lon(muc.ket_qua)["source"][VAI_THIEU] == 1
    assert muc.ket_qua.so_o_thieu == 1
    assert muc.ket_qua.so_vang_han == 1, "đây mới là bỏ sót thật"
    assert muc.ket_qua.so_trung_nhan == 0 and muc.ket_qua.so_ung_vien_da_dung == 0


def test_nhan_vang_lap_khong_an_diem_hai_lan():
    """Nhãn tay lặp cùng (vai, giá trị) nhiều hơn số lần pipeline trả nó.

    Không vào đường chéo: cộng điểm hai lần cho một slot pred làm precision
    vượt quá 1. Đếm riêng ở `trung_nhan` để không ai đọc nó thành bỏ sót.
    """
    vang = [
        {"subject": "sao lưu", "owner": "phòng IT"},
        {"subject": "khôi phục", "owner": "phòng IT"},
    ]
    pred = [{"subject": "sao lưu", "owner": "phòng IT"}]
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    assert muc.ket_qua.chat_theo_vai["owner"] == 1
    assert muc.trung_nhan == (("owner", "phòng IT"),)
    assert muc.ung_vien_da_dung == ()
    assert ("owner", "phòng IT") not in muc.vang_han, "giá trị có mặt, chỉ hết chỗ"
    assert muc.vang_han == (("subject", "khôi phục"),)
    assert muc.ket_qua.so_vang_han == 1 and muc.ket_qua.so_trung_nhan == 1
    assert muc.ket_qua.chi_so.precision <= 1.0


def test_dung_vai_thang_khop_chat_o_vai_sai():
    """Hàng I/O 'Đúng vai thắng khớp chặt': TP khớp lỏng ở vai đúng, không lẫn vai.

    Ưu tiên ngược lại (chặt trước bất kể vai) biến một TP thành FN cộng FP, tức
    phép chấm tự dựng ra một ca lẫn vai chưa từng xảy ra.
    """
    vang = [{"subject": "VPN", "remediation": "khóa tài khoản"}]
    pred = [{"subject": "VPN", "source": "khóa tài khoản", "remediation": "khóa tài khoản tự động"}]
    cap = cham_tai_lieu(vang, pred, doc_key="d")
    assert cap.cap[0].khop["remediation"] == KHOP_LONG
    assert cap.cap[0].lan_vai == ()
    assert cap.cap[0].thua == ("source",)
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    assert muc.ket_qua.chat_theo_vai["remediation"] + muc.ket_qua.long_theo_vai["remediation"] == 1


def test_cham_bo_muc_tai_lieu_dung_mau_so_cua_bo_vang(bo_vang):
    pred = {t.doc_key: [dict(f.slots) for f in t.facts] for t in bo_vang.tai_lieu_cham()}
    kq = cham_bo_muc_tai_lieu(bo_vang, pred)
    assert kq.chi_so.so_vang == bo_vang.mau_so_slot()
    assert kq.chi_so.precision == pytest.approx(1.0)
    assert kq.chi_so.recall == pytest.approx(1.0)
    assert kq.so_lan_vai == 0 and kq.so_o_thieu == 0
    assert kq.so_vang_han == 0


def test_tong_hang_ma_tran_muc_tai_lieu_van_khit(bo_vang):
    """Bất biến còn lại của ma trận mức tài liệu: không slot vàng nào rơi ra ngoài."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_ket_qua

    v = doc_ket_qua(THU_MUC_KET_QUA / "v1-deepseek.json")
    kq = cham_bo_muc_tai_lieu(bo_vang, v.facts_theo_tai_lieu())
    ma_tran = ma_tran_lan_lon(kq)
    for vai in SLOT_ROLES:
        assert sum(ma_tran[vai].values()) == kq.vang_theo_vai[vai]


def test_cap_vai_lan_nhieu_nhat_sap_giam_dan():
    vang = [{"subject": "x", "time": "A", "owner": "B"}, {"subject": "y", "time": "C"}]
    pred = [
        {"subject": "x", "remediation": "A và B cùng lúc"},
        {"subject": "y", "remediation": "C"},
    ]
    kq = cham_muc_tai_lieu(vang, pred, doc_key="d").ket_qua
    top = cap_vai_lan_nhieu_nhat(kq)
    assert top[0] == ("time", "remediation", 2)
    assert ("owner", "remediation", 1) in top


# --- Verdict R2: khóa bằng assert trên giá trị -----------------------------


def test_nguong_r2_dung_bang_60_phan_tram():
    """Ngưỡng của PRD mục 6.1. Đổi hằng này là đổi kết luận của chương 4."""
    assert NGUONG_R2 == 0.60


def test_verdict_r2_dung_bang_nguong_la_dat():
    """PRD viết "dưới 60% thì kích hoạt", nên đúng 60,0% là ĐẠT.

    Đảo `>=` thành `>` hay thành `<` đều làm test này đỏ.
    """
    assert verdict_r2(NGUONG_R2) == VERDICT_DAT
    assert verdict_r2(NGUONG_R2 + 1e-9) == VERDICT_DAT
    assert verdict_r2(NGUONG_R2 - 1e-9) == VERDICT_DUOI
    assert verdict_r2(1.0) == VERDICT_DAT
    assert verdict_r2(0.0) == VERDICT_DUOI


def test_verdict_r2_precision_none_khong_phai_duoi_nguong():
    """Hàng I/O 'Verdict R2': không có slot pred nào thì không có phép chia nào."""
    assert verdict_r2(None) == VERDICT_KHONG_CHAM_DUOC
    assert verdict_r2(None) != VERDICT_DUOI


def test_verdict_r2_nhan_nguong_khac_de_thu_do_nhay():
    assert verdict_r2(0.61, nguong=0.70) == VERDICT_DUOI
    assert verdict_r2(0.61, nguong=0.60) == VERDICT_DAT


def test_cong_r2_chinh_thuc_la_chi_so_ghep_cap():
    assert CONG_R2_CHI_SO == CHI_SO_GHEP_CAP


# --- Khóa số của vòng hiện hành --------------------------------------------

# Con số của `v1-deepseek` đi thẳng vào chương 4. Đổi luật chấm mà quên đo lại
# thì bốn dòng dưới đây đỏ, kèm số cũ - không có đường nào để một con số mới
# lặng lẽ thay số cũ trong tài liệu.
SO_KHOA_V1_DEEPSEEK = {
    CHI_SO_GHEP_CAP: dict(tp=87, so_pred=123, precision=0.707, recall=0.576, f1=0.635),
    CHI_SO_MUC_TAI_LIEU: dict(tp=95, so_pred=123, precision=0.772, recall=0.629, f1=0.693),
}


@pytest.mark.parametrize("ten_chi_so", sorted(SO_KHOA_V1_DEEPSEEK))
def test_khoa_so_cua_vong_v1_deepseek(bo_vang, ten_chi_so):
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_ket_qua

    v = doc_ket_qua(THU_MUC_KET_QUA / "v1-deepseek.json")
    pred = v.facts_theo_tai_lieu()
    kq = cham_bo(bo_vang, pred) if ten_chi_so == CHI_SO_GHEP_CAP else cham_bo_muc_tai_lieu(bo_vang, pred)
    cho_doi = SO_KHOA_V1_DEEPSEEK[ten_chi_so]
    cs = kq.chi_so
    assert cs.tp == cho_doi["tp"]
    assert cs.so_pred == cho_doi["so_pred"]
    assert cs.precision == pytest.approx(cho_doi["precision"], abs=5e-4)
    assert cs.recall == pytest.approx(cho_doi["recall"], abs=5e-4)
    assert cs.f1 == pytest.approx(cho_doi["f1"], abs=5e-4)


def test_khoa_hinh_dang_loi_cua_vong_v1_deepseek(bo_vang):
    """Lỗi là *lẫn vai*, không phải bỏ sót: khóa luôn cả hai con số đó."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_ket_qua

    v = doc_ket_qua(THU_MUC_KET_QUA / "v1-deepseek.json")
    kq = cham_bo_muc_tai_lieu(bo_vang, v.facts_theo_tai_lieu())
    assert kq.so_lan_vai == 51
    # Con số trụ của chương 4: chỉ 2 slot vàng thật sự vắng mặt. Ba loại của cột
    # `thiếu` phải tách được, không thì một nhãn mang hai nghĩa.
    assert kq.so_vang_han == 2
    assert kq.so_trung_nhan == 2
    assert kq.so_ung_vien_da_dung == 1
    assert kq.so_o_thieu == 5 == kq.so_vang_han + kq.so_trung_nhan + kq.so_ung_vien_da_dung
    co_mat = kq.chi_so.tp + kq.so_lan_vai + kq.so_trung_nhan + kq.so_ung_vien_da_dung
    assert co_mat == 149, "149/151 giá trị vàng có mặt trong đầu ra"
    assert kq.so_lan_vai > 20 * kq.so_vang_han, "kết luận của chương 4 đứng trên chênh lệch này"
    assert cap_vai_lan_nhieu_nhat(kq)[0] == ("time", "remediation", 11)


def test_vong_hien_hanh_ghim_prompt_tham_so_va_cach_chia_chunk():
    """Sửa prompt mà không đo lại là bộ test đỏ, không phải một báo cáo lặng lẽ sai."""
    from adapters.trich_xuat import PROMPT_TRICH_XUAT, THAM_SO_LLM
    from eval.do_trich_xuat import THU_MUC_KET_QUA, cau_hinh_chunk, doc_ket_qua

    for ten in ("v1-deepseek", "v1-gpt-4o-mini", "v1-gpt-4o"):
        v = doc_ket_qua(THU_MUC_KET_QUA / f"{ten}.json")
        assert v.prompt == PROMPT_TRICH_XUAT, f"{ten} chạy trên một prompt khác prompt đang ship"
        assert dict(v.tham_so_llm) == dict(THAM_SO_LLM), ten
        assert dict(v.chunk) == cau_hinh_chunk(), ten


def test_bo_vang_khong_doi_ke_tu_lan_do():
    """Ghim sha256 bộ vàng: sửa một nhãn tay là mọi con số ở trên đổi lặng lẽ."""
    import hashlib

    from eval.bo_vang import DUONG_DAN_MAC_DINH

    bam = hashlib.sha256(DUONG_DAN_MAC_DINH.read_bytes()).hexdigest()
    assert bam == BAM_BO_VANG, (
        "bộ vàng đã đổi kể từ lần đo 02/09/2026: chạy lại"
        " `uv run python -m eval.xem_do_trich_xuat`, cập nhật số khóa ở file test này"
        " và mọi bảng số trong spec/ledger/sprint-status"
    )



# --- Runner: seam tiêm LLM, cứu hộ, kiểm tên vòng ---------------------------


class _NhaCungCapGia:
    """Provider giả khớp hợp đồng `NhaCungCapLLM`: không mạng, không key."""

    ten = "deepseek"
    cuc_bo = False

    def __init__(self, phan_hoi: str = '{"facts": [{"subject": "App01", "cause": "hết đĩa"}]}'):
        self.phan_hoi = phan_hoi
        self.so_lan = 0

    async def hoan_thanh(self, model, messages, **kwargs):
        from adapters.llm_wrapper import KetQuaLLM

        self.so_lan += 1
        return KetQuaLLM(noi_dung=self.phan_hoi, token_vao=100, token_ra=20)


def _llm_gia(ncc):
    def dung(muc, danh_muc, audit):
        from adapters.llm_wrapper import bo_llm

        return bo_llm(nha_cung_cap=ncc, model=muc.ten, audit=audit, danh_muc=danh_muc)

    return dung


def test_chay_vong_chay_het_duong_di_voi_llm_gia(tmp_path, bo_vang):
    """Toàn bộ phần tốn tiền phải test được: seam `dung_llm` tiêm provider giả."""
    import asyncio

    from eval.do_trich_xuat import chay_vong, doc_ket_qua

    ncc = _NhaCungCapGia()
    dich = asyncio.run(
        chay_vong(
            vong="v-gia",
            model="deepseek-v4-flash",
            thu_muc_ket_qua=tmp_path,
            dung_llm=_llm_gia(ncc),
            in_ra=lambda *a, **k: None,
        )
    )
    assert ncc.so_lan == 8, "đúng 8 tài liệu chấm, mỗi tài liệu một chunk"
    kq = doc_ket_qua(dich)
    assert {t.doc_key for t in kq.tai_lieu} == {t.doc_key for t in bo_vang.tai_lieu_cham()}
    assert kq.token_vao() == 800 and kq.token_ra() == 160
    assert kq.prompt.count("<<VAN_BAN>>") == 1
    # Chạy lại cùng tên vòng là từ chối, kể cả khi không tốn tiền.
    from eval.do_trich_xuat import KetQuaDoDaCo

    with pytest.raises(KetQuaDoDaCo):
        asyncio.run(
            chay_vong(
                vong="v-gia",
                model="deepseek-v4-flash",
                thu_muc_ket_qua=tmp_path,
                dung_llm=_llm_gia(ncc),
                in_ra=lambda *a, **k: None,
            )
        )


def test_chay_vong_hong_giua_chung_van_giu_phan_hoi_da_tra_tien(tmp_path):
    """Tiền đã tiêu cho 3 tài liệu đầu không được bay mất vì tài liệu thứ 4 hỏng."""
    import asyncio
    import json

    from eval.do_trich_xuat import THU_MUC_CHUA_XONG, chay_vong

    class Hong(_NhaCungCapGia):
        async def hoan_thanh(self, model, messages, **kwargs):
            if self.so_lan >= 3:
                raise RuntimeError("429 rate limit")
            return await super().hoan_thanh(model, messages, **kwargs)

    ncc = Hong()
    with pytest.raises(RuntimeError):
        asyncio.run(
            chay_vong(
                vong="v-hong",
                model="deepseek-v4-flash",
                thu_muc_ket_qua=tmp_path,
                dung_llm=_llm_gia(ncc),
                in_ra=lambda *a, **k: None,
            )
        )
    assert not (tmp_path / "v-hong.json").exists(), "file kết quả chỉ ghi khi chạy xong"
    cuu_ho = sorted((tmp_path / THU_MUC_CHUA_XONG).glob("v-hong-*.json"))
    assert len(cuu_ho) == 1
    du_lieu = json.loads(cuu_ho[0].read_text(encoding="utf-8"))
    assert len(du_lieu["tai_lieu"]) == 3
    # File cứu hộ không được lọt vào danh sách vòng: một lần chạy hỏng làm chết
    # cả trang báo cáo là mất luôn số của những vòng đã trả tiền.
    from eval.do_trich_xuat import doc_moi_vong

    assert doc_moi_vong(tmp_path) == []


@pytest.mark.parametrize("ten", ["", "../x", "a/b", "v 1", "-x", "." * 5 + "/y"])
def test_ten_vong_khong_hop_le_bi_tu_choi(ten):
    from eval.do_trich_xuat import KetQuaDoKhongHopLe, kiem_ten_vong

    with pytest.raises(KetQuaDoKhongHopLe):
        kiem_ten_vong(ten)


def test_ten_vong_hop_le_duoc_nhan():
    from eval.do_trich_xuat import kiem_ten_vong

    for ten in ("v0-deepseek-goc", "v1_gpt-4o.2", "V2"):
        assert kiem_ten_vong(ten) == ten


def test_cau_hinh_chunk_khop_duong_ingest_that():
    """Chia chunk của harness phải là chính cách `EngineACL.ainsert` chia."""
    from dataclasses import fields

    from hypergraphrag.operate import chunking_by_token_size

    from adapters.engine import EngineACL
    from eval.do_trich_xuat import TRUONG_CHUNK, cau_hinh_chunk, chia_chunk

    mac_dinh = {f.name: f.default for f in fields(EngineACL)}
    for ten in TRUONG_CHUNK:
        assert ten in mac_dinh, f"{ten} không còn là field của EngineACL"
        assert cau_hinh_chunk()[ten] == mac_dinh[ten]
    van_ban = "  Dòng một.\nDòng hai.  "
    cho_doi = chunking_by_token_size(
        van_ban.strip(),
        overlap_token_size=mac_dinh["chunk_overlap_token_size"],
        max_token_size=mac_dinh["chunk_token_size"],
        tiktoken_model=mac_dinh["tiktoken_model_name"],
    )
    assert [c["content"] for c in chia_chunk(van_ban)] == [c["content"] for c in cho_doi]


def test_ty_le_loai_khong_co_ban_ghi_nao_tra_none(tmp_path):
    """Vòng mà mọi chunk đều hỏng không được đọc thành '0% bị loại'."""
    import json

    from eval.do_trich_xuat import doc_ket_qua

    p = tmp_path / "v-test.json"
    p.write_text(json.dumps(_vong_toi_thieu("không phải json")), encoding="utf-8")
    kq = doc_ket_qua(p)
    assert kq.so_fact_tho() == 0
    assert kq.ty_le_loai() is None


@pytest.mark.parametrize("gia", ["NaN", "Infinity", "-Infinity"])
def test_chi_phi_usd_khong_huu_han_bi_tu_choi(tmp_path, gia):
    from eval.do_trich_xuat import KetQuaDoKhongHopLe, doc_ket_qua

    p = tmp_path / "v-test.json"
    raw = json.dumps(_vong_toi_thieu())
    raw = raw.replace('"chi_phi_usd": 0.0001', f'"chi_phi_usd": {gia}')
    p.write_text(raw, encoding="utf-8")
    with pytest.raises(KetQuaDoKhongHopLe) as e:
        doc_ket_qua(p)
    assert "chi_phi_usd" in str(e.value)


def test_fact_trung_qua_vung_overlap_duoc_gop(tmp_path):
    """Chunk chồng lấn 100 token: một fact vắt qua ranh giới bị trả hai lần."""
    import json

    from eval.do_trich_xuat import doc_ket_qua

    d = _vong_toi_thieu()
    d["tai_lieu"][0]["chunks"].append(dict(d["tai_lieu"][0]["chunks"][0], stt=1))
    p = tmp_path / "v-test.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    kq = doc_ket_qua(p)
    assert kq.so_hop_le() == 2, "đếm thô vẫn thấy hai bản ghi"
    assert len(kq.facts_theo_tai_lieu()["02-vpn-va-mat-khau.txt"]) == 1
    assert kq.so_fact_trung_chunk() == 1


# --- Phép chấm: cửa kiểm đầu vào -------------------------------------------


def test_vai_la_trong_pred_bi_tu_choi_kem_ten_vai():
    with pytest.raises(ValueError) as e:
        cham_tai_lieu([{"subject": "x", "cause": "y"}], [{"subject": "x", "vai_la": "y"}])
    assert "vai_la" in str(e.value)


def test_mau_so_phu_vai_ngoai_danh_muc_bi_tu_choi():
    kq = cham_tai_lieu([{"subject": "x", "cause": "y"}], []).ket_qua
    with pytest.raises(ValueError):
        mau_so_phu(kq, bo_vai="khong_phai_vai")


# --- Ngoại suy: mép của mức báo động ----------------------------------------


def test_vuot_bao_dong_dung_bang_muc_la_cham():
    """PRD viết "chạm là dừng và tính lại", nên `>=` chứ không `>`."""
    from eval.ngoai_suy import BangNgoaiSuy, Khoan

    k = Khoan(
        ten="x", mo_ta="", model="m", so_luong=1, don_vi="lời gọi",
        token_vao=1, token_ra=1, chi_phi_usd=60.0, nguon="đo",
    )
    from dataclasses import replace

    assert BangNgoaiSuy(khoan=(k,), tong_usd=60.0).vuot_bao_dong is True
    duoi = replace(k, chi_phi_usd=59.999)
    assert BangNgoaiSuy(khoan=(duoi,), tong_usd=59.999).vuot_bao_dong is False


def test_tong_ngoai_suy_phai_khop_tong_cac_khoan():
    """`tong_usd` là tham số, nên nó có thể lệch tổng các khoản - chặn ở cửa dựng."""
    from eval.ngoai_suy import BangNgoaiSuy, Khoan

    k = Khoan(
        ten="x", mo_ta="", model="m", so_luong=1, don_vi="lời gọi",
        token_vao=1, token_ra=1, chi_phi_usd=1.0, nguon="đo",
    )
    BangNgoaiSuy(khoan=(k,), tong_usd=1.0)
    with pytest.raises(ValueError):
        BangNgoaiSuy(khoan=(k,), tong_usd=2.0)


def test_muc_bao_dong_khong_duong_bi_tu_choi():
    from eval.ngoai_suy import BangNgoaiSuy

    with pytest.raises(ValueError):
        BangNgoaiSuy(khoan=(), tong_usd=1.0, muc_bao_dong_usd=0)


def _do_mau():
    from eval.ngoai_suy import SoDoNap

    return SoDoNap(so_tai_lieu=8, token_vao_llm=1, token_ra_llm=1, chi_phi_llm_usd=0.1,
                   token_embedding=1, chi_phi_embedding_usd=0.01)


@pytest.mark.parametrize(
    "truong,gia_tri",
    [
        ("so_tai_lieu_corpus", 0),
        ("so_tai_lieu_corpus", -1),
        ("so_cau", -1),
        ("token_vao_sinh", float("nan")),
        ("ty_le_bat_dong", 5.0),
    ],
)
def test_gia_dinh_xau_bi_tu_choi(truong, gia_tri):
    from dataclasses import replace

    from eval.ngoai_suy import GiaDinh, ngoai_suy

    with pytest.raises(ValueError) as e:
        ngoai_suy(_do_mau(), gia_dinh=replace(GiaDinh(), **{truong: gia_tri}))
    assert truong in str(e.value)


@pytest.mark.parametrize("truong", ["ty_le_bat_dong", "so_vong_rubric", "so_cau_so_chunk"])
def test_gia_dinh_bang_0_la_tat_mot_khoan_chu_khong_phai_loi(truong):
    """"Bỏ ensemble thì còn bao nhiêu" là câu hỏi hợp lệ, không phải cấu hình hỏng."""
    from dataclasses import replace

    from eval.ngoai_suy import GiaDinh, ngoai_suy

    day_du = ngoai_suy(_do_mau())
    tat = ngoai_suy(_do_mau(), gia_dinh=replace(GiaDinh(), **{truong: 0}))
    assert tat.tong_usd < day_du.tong_usd


def test_so_do_nap_khong_huu_han_bi_tu_choi():
    from dataclasses import replace

    from eval.ngoai_suy import ngoai_suy

    with pytest.raises(ValueError) as e:
        ngoai_suy(replace(_do_mau(), chi_phi_llm_usd=float("inf")))
    assert "chi_phi_llm_usd" in str(e.value)


# --- Số đo nạp đọc từ file, không còn hằng chép tay (story 2.7) ---------------


def test_file_so_do_nap_that_trong_repo_doc_duoc():
    """`eval/so_do_nap/nap-that.json` có commit và là nguồn của khoản 1 và 5.

    File hỏng hay bị xóa thì bảng ngoại suy của chương 4 mất chân đứng, nên nó
    phải được đọc trong bộ test chứ không chỉ lúc chạy báo cáo.
    """
    from eval.ngoai_suy import DUONG_DAN_SO_DO_NAP, doc_so_do_nap

    assert DUONG_DAN_SO_DO_NAP.exists(), "file số đo nạp phải nằm trong repo"
    do = doc_so_do_nap()
    assert do.so_tai_lieu > 0
    assert do.token_vao_llm > 0 and do.token_ra_llm > 0 and do.chi_phi_llm_usd > 0
    assert do.token_embedding > 0 and do.chi_phi_embedding_usd > 0


def test_so_do_nap_that_khop_lan_nap_02_09():
    """Khóa sáu con số của lần nạp thật: đổi file mà quên cập nhật bảng là đỏ.

    Cùng vai trò với `SO_DO_NAP_THAT` cũ, chỉ khác là nguồn nay là file chứ
    không phải một hằng trong code - và test này là chỗ nói rõ bảng ngoại suy
    đang đứng trên số nào.
    """
    from eval.ngoai_suy import doc_so_do_nap

    do = doc_so_do_nap()
    assert (do.so_tai_lieu, do.token_vao_llm, do.token_ra_llm) == (10, 10111, 3651)
    assert do.chi_phi_llm_usd == pytest.approx(0.00926816)
    assert do.token_embedding == 8874
    assert do.chi_phi_embedding_usd == pytest.approx(0.00017748)


def _ghi_so_do(tmp_path, *, tu_tinh_tong=True, **thay):
    """File số đo mẫu; `tong` tự cộng lại từ `theo_model` trừ khi test đặt tay."""
    import json

    goc = {
        "version": 1,
        "ngay": "2026-09-02T11:24:57+00:00",
        "lenh": "x",
        "space": "synth",
        "so_tai_lieu": 2,
        "theo_model": [
            {"model": "m", "loai": "llm", "so_lan": 1, "token_vao": 10, "token_ra": 5, "chi_phi_usd": 0.1}
        ],
    }
    goc.update(thay)
    if tu_tinh_tong and "tong" not in thay:
        dong = [d for d in goc["theo_model"] if isinstance(d, dict)]
        goc["tong"] = {
            "so_lan": sum(d.get("so_lan", 0) for d in dong),
            "token_vao": sum(d.get("token_vao", 0) for d in dong if isinstance(d.get("token_vao"), (int, float))),
            "token_ra": sum(d.get("token_ra", 0) for d in dong if isinstance(d.get("token_ra"), (int, float))),
            "chi_phi_usd": sum(d.get("chi_phi_usd", 0) for d in dong if isinstance(d.get("chi_phi_usd"), (int, float))),
        }
    dich = tmp_path / "nap-that.json"
    dich.write_text(json.dumps(goc), encoding="utf-8")
    return dich


def _dong(**thay):
    d = {"model": "m", "loai": "llm", "so_lan": 1, "token_vao": 10, "token_ra": 5, "chi_phi_usd": 0.1}
    d.update(thay)
    return d


@pytest.mark.parametrize(
    "thay,dau_hieu",
    [
        ({"version": 2}, "version"),
        ({"version": "1"}, "version"),
        ({"theo_model": []}, "theo_model"),
        ({"theo_model": [{"model": "m", "loai": "llm"}]}, "thiếu khóa"),
        ({"so_tai_lieu": "hai"}, "so_tai_lieu"),
        ({"theo_model": [_dong(token_vao="x")]}, "token_vao"),
        # Số đo không dùng được, mà trước đây lọt tới `_kiem_so_do` rồi ném
        # `ValueError` trần - thứ mà `except SoDoNapKhongHopLe` không bắt.
        ({"so_tai_lieu": 0}, "so_tai_lieu"),
        ({"so_tai_lieu": -3}, "so_tai_lieu"),
        ({"theo_model": [_dong(token_vao=-1)]}, "âm"),
        ({"theo_model": [_dong(chi_phi_usd=float("nan"))]}, "không hữu hạn"),
        ({"theo_model": [_dong(chi_phi_usd=float("inf"))]}, "không hữu hạn"),
        # `loai` lạ rơi vào nhánh LLM là âm thầm thổi phồng token trích xuất.
        ({"theo_model": [_dong(loai="reranker")]}, "loai"),
        ({"theo_model": [_dong(loai="")]}, "loai"),
        ({"theo_model": [_dong(token_vao=True)]}, "token_vao"),
    ],
)
def test_so_do_nap_hong_bi_tu_choi_kem_ten_file_va_ly_do(tmp_path, thay, dau_hieu):
    from eval.ngoai_suy import SoDoNapKhongHopLe, doc_so_do_nap

    dich = _ghi_so_do(tmp_path, **thay)
    with pytest.raises(SoDoNapKhongHopLe) as e:
        doc_so_do_nap(dich)
    assert "nap-that.json" in str(e.value) and dau_hieu in str(e.value)


@pytest.mark.parametrize(
    "tong,dau_hieu",
    [
        ({"so_lan": 1, "token_vao": 11, "token_ra": 5, "chi_phi_usd": 0.1}, "tong.token_vao"),
        ({"so_lan": 1, "token_vao": 10, "token_ra": 6, "chi_phi_usd": 0.1}, "tong.token_ra"),
        ({"so_lan": 1, "token_vao": 10, "token_ra": 5, "chi_phi_usd": 0.2}, "tong.chi_phi_usd"),
        ({"so_lan": 9, "token_vao": 10, "token_ra": 5, "chi_phi_usd": 0.1}, "tong.so_lan"),
        ({"token_vao": 10, "token_ra": 5, "chi_phi_usd": 0.1}, "thiếu khóa"),
        ("khong-phai-object", "object"),
    ],
)
def test_khoi_tong_lech_theo_model_bi_tu_choi(tmp_path, tong, dau_hieu):
    """Hai con số trong cùng một file có commit mà lệch nhau thì ít nhất một cái sai.

    Trước đây `so_do_nap` ghi khối `tong` còn `doc_so_do_nap` bỏ qua nó và tự
    cộng lại, nên không gì đỏ khi chúng rời nhau.
    """
    from eval.ngoai_suy import SoDoNapKhongHopLe, doc_so_do_nap

    dich = _ghi_so_do(tmp_path, tong=tong)
    with pytest.raises(SoDoNapKhongHopLe) as e:
        doc_so_do_nap(dich)
    assert "nap-that.json" in str(e.value) and dau_hieu in str(e.value)


def test_khoi_tong_khop_thi_doc_duoc(tmp_path):
    from eval.ngoai_suy import doc_so_do_nap

    assert doc_so_do_nap(_ghi_so_do(tmp_path)).token_vao_llm == 10


def test_so_do_nap_khong_phai_utf8_bi_tu_choi(tmp_path):
    """`read_text` ném `UnicodeDecodeError`, không phải `OSError`: hai nhánh khác nhau."""
    from eval.ngoai_suy import SoDoNapKhongHopLe, doc_so_do_nap

    dich = tmp_path / "nap-that.json"
    dich.write_bytes(b"\xff\xfe{}")
    with pytest.raises(SoDoNapKhongHopLe) as e:
        doc_so_do_nap(dich)
    assert "nap-that.json" in str(e.value) and "UTF-8" in str(e.value)


def test_moi_duong_thoat_cua_cua_doc_deu_la_so_do_nap_khong_hop_le(tmp_path):
    """`SoDoNapKhongHopLe` là con của `ValueError`, nên một `ValueError` trần lọt
    ra sẽ *không* bị `except SoDoNapKhongHopLe` bắt - báo cáo chết bằng traceback."""
    import json

    from eval.ngoai_suy import SoDoNapKhongHopLe, doc_so_do_nap

    xau = [
        b"[]",
        b"{}",
        b"khong phai json",
        json.dumps({"version": 1, "ngay": "x", "lenh": "x", "space": "s",
                    "so_tai_lieu": 0, "theo_model": [_dong()], "tong": {}}).encode(),
    ]
    dich = tmp_path / "nap-that.json"
    for noi_dung in xau:
        dich.write_bytes(noi_dung)
        with pytest.raises(SoDoNapKhongHopLe):
            doc_so_do_nap(dich)
    dich.unlink()
    with pytest.raises(SoDoNapKhongHopLe):
        doc_so_do_nap(dich)


def test_bao_cao_tu_choi_file_so_do_hong_thay_vi_chet_bang_traceback(tmp_path, capsys):
    """Nhánh lỗi của `eval/xem_do_trich_xuat.main` phải có test chạy vào.

    Trước đây `main` gọi `doc_so_do_nap()` không tham số nên mọi test đều đọc
    file thật trong repo, và nhánh xử lý lỗi chưa từng chạy một lần.
    """
    from eval.xem_do_trich_xuat import main

    hong = _ghi_so_do(tmp_path, version=99)
    ma = main(dich=tmp_path / "t.html", so_do_nap=hong)
    assert ma == 1
    assert "nap-that.json" in capsys.readouterr().err


def test_so_do_nap_thieu_khoa_goc_bi_tu_choi(tmp_path):
    import json

    from eval.ngoai_suy import SoDoNapKhongHopLe, doc_so_do_nap

    dich = tmp_path / "nap-that.json"
    dich.write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(SoDoNapKhongHopLe) as e:
        doc_so_do_nap(dich)
    assert "thiếu khóa" in str(e.value)


def test_so_do_nap_file_khong_co_bi_tu_choi_kem_duong_dan(tmp_path):
    from eval.ngoai_suy import SoDoNapKhongHopLe, doc_so_do_nap

    with pytest.raises(SoDoNapKhongHopLe) as e:
        doc_so_do_nap(tmp_path / "chua-co.json")
    assert "chua-co.json" in str(e.value)


def test_so_do_nap_khong_phai_json_bi_tu_choi(tmp_path):
    from eval.ngoai_suy import SoDoNapKhongHopLe, doc_so_do_nap

    dich = tmp_path / "nap-that.json"
    dich.write_text("khong phai json", encoding="utf-8")
    with pytest.raises(SoDoNapKhongHopLe):
        doc_so_do_nap(dich)


def test_so_do_nap_cong_theo_loai_khong_theo_ten_model(tmp_path):
    """Hai model LLM trong cùng một đợt cộng chung; embedding vẫn tách riêng."""
    from eval.ngoai_suy import doc_so_do_nap

    dich = _ghi_so_do(
        tmp_path,
        theo_model=[
            {"model": "a", "loai": "llm", "token_vao": 10, "token_ra": 5, "chi_phi_usd": 0.1},
            {"model": "b", "loai": "llm", "token_vao": 20, "token_ra": 7, "chi_phi_usd": 0.2},
            {"model": "e", "loai": "embedding", "token_vao": 30, "token_ra": 0, "chi_phi_usd": 0.3},
        ],
    )
    do = doc_so_do_nap(dich)
    assert (do.token_vao_llm, do.token_ra_llm) == (30, 12)
    assert do.chi_phi_llm_usd == pytest.approx(0.3)
    assert do.token_embedding == 30 and do.chi_phi_embedding_usd == pytest.approx(0.3)


def test_khoan_ap_don_gia_model_khac_len_token_do_duoc_la_gia_dinh():
    """Áp giá GPT-4o lên token đo của DeepSeek là một giả định, phải nêu tên."""
    from eval.ngoai_suy import NGUON_DO, NGUON_GIA_DINH, doc_so_do_nap, ngoai_suy

    bang = ngoai_suy(doc_so_do_nap())
    assert bang.khoan_theo_ten("nap_corpus").nguon == NGUON_DO
    for ten in ("gpt4o_dung_cuoi", "ensemble_a13", "sinh_t7", "judge_do2", "vong_so_chunk"):
        k = bang.khoan_theo_ten(ten)
        assert k.nguon == NGUON_GIA_DINH, ten
        assert k.gia_dinh, f"{ten}: cờ giả định mà không nêu giả định nào"
    assert all(k.don_vi for k in bang.khoan)


def test_so_vn_dung_dau_phay_thap_phan():
    from eval.ngoai_suy import so_vn

    assert so_vn(4.0019) == "4,0019"
    assert so_vn(70.7, 1) == "70,7"


# --- Trang báo cáo: những thứ một kết luận đứng lên -------------------------


def test_trang_in_ca_hai_chi_so_va_bon_cot_verdict(tmp_path, capsys):
    from eval.cham_trich_xuat import CONG_R2_MAU_SO
    from eval.xem_do_trich_xuat import main

    dich = tmp_path / "t.html"
    assert main(dich=dich) == 0
    trang = dich.read_text(encoding="utf-8")
    ra = capsys.readouterr().out
    for van_ban in (CHI_SO_GHEP_CAP, CHI_SO_MUC_TAI_LIEU, CONG_R2_MAU_SO, "cổng R2"):
        assert van_ban in trang, van_ban
    assert "lẫn vai" in trang and "vắng hẳn" in trang
    # Verdict của cả bốn cột có mặt ở console, kèm dấu cột nào là cổng.
    assert ra.count("cổng R2") >= 4
    assert CHI_SO_MUC_TAI_LIEU in ra


def test_trang_va_console_deu_giu_co_nguon_va_canh_bao_don_gia(tmp_path, capsys):
    """Xóa câu cảnh báo đơn giá hay đổi cờ `nguon` mặc định là bộ test đỏ."""
    from eval.ngoai_suy import GHI_CHU_DON_GIA, NGUON_DO, NGUON_GIA_DINH
    from eval.xem_do_trich_xuat import main

    dich = tmp_path / "t.html"
    assert main(dich=dich) == 0
    trang = dich.read_text(encoding="utf-8")
    ra = capsys.readouterr().out
    for dau_ra, ten in ((trang, "trang HTML"), (ra, "console")):
        assert GHI_CHU_DON_GIA in dau_ra or "cận trên chưa đối chiếu hóa đơn" in dau_ra, ten
        assert NGUON_DO in dau_ra and NGUON_GIA_DINH in dau_ra, ten
    assert "giả định có tên" in trang
    assert "60 USD" in trang and "60 USD" in ra


def test_trang_co_cot_loai_theo_ma(tmp_path):
    """Khoản ledger `PHAN_HOI_BI_CAT` đóng dựa đúng vào việc cột này tồn tại."""
    from eval.xem_do_trich_xuat import main

    dich = tmp_path / "t.html"
    assert main(dich=dich) == 0
    assert "loại theo mã" in dich.read_text(encoding="utf-8")


def test_trang_bo_qua_vong_lech_tap_tai_lieu_thay_vi_chet_ca_bao_cao(tmp_path, capsys):
    import json
    import shutil

    from eval.do_trich_xuat import THU_MUC_KET_QUA
    from eval.xem_do_trich_xuat import main

    thu_muc = tmp_path / "ket_qua"
    thu_muc.mkdir()
    shutil.copy(THU_MUC_KET_QUA / "v1-deepseek.json", thu_muc / "v1-deepseek.json")
    cu = json.loads((THU_MUC_KET_QUA / "v1-deepseek.json").read_text(encoding="utf-8"))
    cu["vong"] = "v-corpus-cu"
    cu["tai_lieu"] = cu["tai_lieu"][:3]
    (thu_muc / "v-corpus-cu.json").write_text(json.dumps(cu, ensure_ascii=False), encoding="utf-8")
    assert main(dich=tmp_path / "t.html", thu_muc_ket_qua=thu_muc) == 0
    loi = capsys.readouterr().err
    assert "BỎ QUA vòng v-corpus-cu" in loi


def test_trang_dung_argparse_khong_tao_file_ten_h(tmp_path):
    ket_qua = subprocess.run(
        [sys.executable, "-m", "eval.xem_do_trich_xuat", "-h"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert ket_qua.returncode == 0
    assert "usage:" in ket_qua.stdout
    assert not (REPO_ROOT / "-h").exists()


def test_trang_ghi_thoi_diem_dung_va_meta_viewport(tmp_path):
    from eval.xem_do_trich_xuat import main

    dich = tmp_path / "t.html"
    assert main(dich=dich) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "Dựng lúc" in trang
    assert 'name="viewport"' in trang
    assert 'class="cuon"' in trang, "bảng rộng phải cuộn ngang được"


# ===========================================================================
# Vòng review 2: khóa tầng trình bày vào hàm chấm, tách ba nghĩa của cột "thiếu"
# ===========================================================================


class _DocBang(HTMLParser):
    """Trích bảng có `data-bang` từ trang: mỗi bảng thành list hàng, mỗi ô là (text, attrs).

    Trang là thứ người đọc và chương 4 nhìn thấy, nên khóa số phải đặt *ở đó*:
    hai đột biến của vòng review 2 (đổi chỉ số ở cột cổng R2, đổi nguồn của ma
    trận A13) đều nằm trong hàm dựng HTML chứ không trong phép chấm.
    """

    def __init__(self):
        super().__init__()
        self.bang: list[tuple[dict, list[list[tuple[str, dict]]]]] = []
        self._sau: list[list[tuple[str, dict]]] | None = None
        self._o: list[str] | None = None
        self._attrs: dict = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            if "data-bang" in a:
                self._sau = []
                self.bang.append((a, self._sau))
            else:
                self._sau = None
        elif tag == "tr" and self._sau is not None:
            self._sau.append([])
        elif tag in ("td", "th") and self._sau is not None:
            self._o = []
            self._attrs = a

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._o is not None and self._sau:
            self._sau[-1].append(("".join(self._o).strip(), self._attrs))
            self._o = None

    def handle_data(self, data):
        if self._o is not None:
            self._o.append(data)


def _bang_cua_trang(trang: str) -> list[tuple[dict, list]]:
    p = _DocBang()
    p.feed(trang)
    return p.bang


@pytest.fixture(scope="module")
def trang_that(tmp_path_factory, bo_vang):
    """Trang dựng từ đúng bốn vòng của repo, dùng lại cho mọi test khóa số."""
    from eval.xem_do_trich_xuat import main

    dich = tmp_path_factory.mktemp("trang") / "do_trich_xuat.html"
    assert main(dich=dich) == 0
    return dich.read_text(encoding="utf-8")


def test_o_cong_r2_tren_trang_lay_so_tu_chi_so_ghep_cap(trang_that, bo_vang):
    """Đảo ternary chọn chỉ số -> cột cổng lấy 77,2% thay vì 70,7%. Test này phải đỏ."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong
    from eval.xem_do_trich_xuat import MAU_SO_PHU, MAU_SO_TONG, _pc

    o_theo_khoa = {}
    for attrs, hang in _bang_cua_trang(trang_that):
        if attrs.get("data-bang") != "verdict":
            continue
        for r in hang:
            for text, a in r:
                if "data-vong" in a:
                    o_theo_khoa[(a["data-vong"], a["data-chi-so"], a["data-mau-so"])] = text
    assert o_theo_khoa, "không tìm thấy bảng verdict trên trang"

    for v in doc_moi_vong(THU_MUC_KET_QUA):
        pred = v.facts_theo_tai_lieu()
        cho_doi = {
            (CHI_SO_GHEP_CAP, MAU_SO_TONG): cham_bo(bo_vang, pred).chi_so,
            (CHI_SO_GHEP_CAP, MAU_SO_PHU): mau_so_phu(cham_bo(bo_vang, pred)),
            (CHI_SO_MUC_TAI_LIEU, MAU_SO_TONG): cham_bo_muc_tai_lieu(bo_vang, pred).chi_so,
            (CHI_SO_MUC_TAI_LIEU, MAU_SO_PHU): mau_so_phu(cham_bo_muc_tai_lieu(bo_vang, pred)),
        }
        for (chi_so, mau_so), cs in cho_doi.items():
            o = o_theo_khoa[(v.vong, chi_so, mau_so)]
            assert o.startswith(_pc(cs.precision)), (v.vong, chi_so, mau_so, o)
            assert verdict_r2(cs.precision) in o


def test_ma_tran_tren_trang_dung_chi_so_muc_tai_lieu(trang_that, bo_vang):
    """Đổi `d.muc` thành `d.cap` -> ma trận in "time -> remediation 2" thay vì 11."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong

    bang = {
        a["data-vong"]: h
        for a, h in _bang_cua_trang(trang_that)
        if a.get("data-bang") == "ma-tran"
    }
    assert bang, "không tìm thấy ma trận nào trên trang"
    for v in doc_moi_vong(THU_MUC_KET_QUA):
        cho_doi = ma_tran_lan_lon(cham_bo_muc_tai_lieu(bo_vang, v.facts_theo_tai_lieu()))
        hang = bang[v.vong]
        cot = [t for t, _ in hang[0]][1:]
        assert cot == list(COT_MA_TRAN)
        doc_duoc = {}
        for r in hang[1:]:
            ten_hang = r[0][0]
            doc_duoc[ten_hang] = {
                cot[i]: int(t) if t else 0 for i, (t, _) in enumerate(r[1:])
            }
        assert doc_duoc == cho_doi, v.vong


def test_cot_vang_han_tren_trang_khong_phai_tong_cot_thieu(trang_that, bo_vang):
    """Con số trụ của chương 4: 2, không phải 5 (5 gộp cả nhãn tay hết chỗ)."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong

    o = {}
    for attrs, hang in _bang_cua_trang(trang_that):
        if attrs.get("data-bang") != "so-vong":
            continue
        for r in hang:
            for text, a in r:
                if a.get("data-o"):
                    o[(a["data-vong"], a["data-chi-so"], a["data-o"])] = text
    assert o, "không tìm thấy ô nào mang data-o trên bảng so vòng"

    for v in doc_moi_vong(THU_MUC_KET_QUA):
        pred = v.facts_theo_tai_lieu()
        muc = cham_bo_muc_tai_lieu(bo_vang, pred)
        cap = cham_bo(bo_vang, pred)
        assert o[(v.vong, CHI_SO_MUC_TAI_LIEU, "vang-han")] == str(muc.so_vang_han)
        assert o[(v.vong, CHI_SO_MUC_TAI_LIEU, "o-thieu")] == str(muc.so_o_thieu)
        # Chỉ số ghép cặp không phân loại được cột `thiếu`, nên nó phải in `-`
        # chứ không mượn con số của cột bên cạnh.
        assert o[(v.vong, CHI_SO_GHEP_CAP, "vang-han")] == "-"
        assert o[(v.vong, CHI_SO_GHEP_CAP, "o-thieu")] == str(cap.so_o_thieu)
    assert o[("v1-deepseek", CHI_SO_MUC_TAI_LIEU, "vang-han")] == "2"
    assert o[("v1-deepseek", CHI_SO_MUC_TAI_LIEU, "o-thieu")] == "5"


def test_ung_vien_da_dung_khong_bi_goi_la_nhan_vang_lap():
    """Hai giá trị vàng *khác nhau* cùng vai tranh một giá trị pred dài."""
    vang = [
        {"subject": "App01", "remediation": "dọn log"},
        {"subject": "App01", "cause": "đĩa đầy", "remediation": "dọn log cũ"},
    ]
    pred = [{"subject": "App01", "cause": "đĩa đầy", "remediation": "dọn log cũ trên App01"}]
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    assert muc.trung_nhan == (), "hai nhãn khác chữ, không phải nhãn lặp"
    assert muc.ung_vien_da_dung == (("remediation", "dọn log"),)
    assert muc.vang_han == ()
    assert muc.ket_qua.so_vang_han == 0 and muc.ket_qua.so_ung_vien_da_dung == 1


def test_pred_da_bi_quy_loi_khong_dem_tiep_vao_thua():
    """Một giá trị dán sai vai đã có chỗ trong ma trận; đếm tiếp vào `thừa` là hai lần."""
    vang = [{"subject": "phiếu", "time": "trong 24 giờ"}]
    pred = [{"subject": "phiếu", "remediation": "bổ sung phiếu trong 24 giờ"}]
    muc = cham_muc_tai_lieu(vang, pred, doc_key="d")
    assert [(k.vai_vang, k.vai_pred) for k in muc.lan_vai] == [("time", "remediation")]
    assert muc.pred_thua == ()
    ma_tran = ma_tran_lan_lon(muc.ket_qua)
    assert ma_tran[VAI_THUA]["remediation"] == 0
    assert ma_tran["time"]["remediation"] == 1


def test_khoa_so_bon_vong_va_verdict_bon_cot(bo_vang):
    """Spec và sprint-status trích số của cả bốn vòng, không chỉ v1-deepseek."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong

    cho_doi = {
        "v0-deepseek-goc": {CHI_SO_GHEP_CAP: (0.648, 0.550), CHI_SO_MUC_TAI_LIEU: (0.742, 0.629)},
        "v1-deepseek": {CHI_SO_GHEP_CAP: (0.707, 0.576), CHI_SO_MUC_TAI_LIEU: (0.772, 0.629)},
        "v1-gpt-4o-mini": {CHI_SO_GHEP_CAP: (0.664, 0.497), CHI_SO_MUC_TAI_LIEU: (0.761, 0.570)},
        "v1-gpt-4o": {CHI_SO_GHEP_CAP: (0.650, 0.530), CHI_SO_MUC_TAI_LIEU: (0.732, 0.596)},
    }
    phu_ghep_cap = {
        "v0-deepseek-goc": 0.538,
        "v1-deepseek": 0.614,
        "v1-gpt-4o-mini": 0.577,
        "v1-gpt-4o": 0.571,
    }
    vong = {v.vong: v for v in doc_moi_vong(THU_MUC_KET_QUA)}
    assert set(vong) == set(cho_doi)
    for ten, v in vong.items():
        pred = v.facts_theo_tai_lieu()
        cap, muc = cham_bo(bo_vang, pred), cham_bo_muc_tai_lieu(bo_vang, pred)
        for kq, ten_chi_so in ((cap, CHI_SO_GHEP_CAP), (muc, CHI_SO_MUC_TAI_LIEU)):
            p, r = cho_doi[ten][ten_chi_so]
            assert kq.chi_so.precision == pytest.approx(p, abs=5e-4), (ten, ten_chi_so)
            assert kq.chi_so.recall == pytest.approx(r, abs=5e-4), (ten, ten_chi_so)
        # Cổng R2 đạt ở cả bốn vòng, còn mẫu số phụ của chỉ số ghép cặp thì
        # 3/4 vòng DƯỚI - câu "biên mỏng" của spec đứng trên đúng chỗ này.
        assert verdict_r2(cap.chi_so.precision) == VERDICT_DAT, ten
        assert mau_so_phu(cap).precision == pytest.approx(phu_ghep_cap[ten], abs=5e-4), ten
    duoi = [
        ten
        for ten, v in vong.items()
        if verdict_r2(mau_so_phu(cham_bo(bo_vang, v.facts_theo_tai_lieu())).precision)
        != VERDICT_DAT
    ]
    assert sorted(duoi) == ["v0-deepseek-goc", "v1-gpt-4o", "v1-gpt-4o-mini"]


def test_gpt_4o_khong_tot_hon_deepseek_o_bat_ky_cot_nao(bo_vang):
    """Câu "bậc 1 của R2 không có căn cứ" đứng trên bốn phép so này."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_ket_qua

    def cot(ten):
        pred = doc_ket_qua(THU_MUC_KET_QUA / f"{ten}.json").facts_theo_tai_lieu()
        cap, muc = cham_bo(bo_vang, pred), cham_bo_muc_tai_lieu(bo_vang, pred)
        return (
            cap.chi_so.precision,
            mau_so_phu(cap).precision,
            muc.chi_so.precision,
            mau_so_phu(muc).precision,
        )

    ds, gpt = cot("v1-deepseek"), cot("v1-gpt-4o")
    assert all(g < d for g, d in zip(gpt, ds)), (gpt, ds)


def test_bon_vong_khong_co_ban_ghi_bi_loai():
    """Khoản ledger PHAN_HOI_BI_CAT đóng dựa vào đúng hai con số này."""
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong

    for v in doc_moi_vong(THU_MUC_KET_QUA):
        assert v.loai_theo_ma() == {}, v.vong
        assert v.so_chunk_hong() == 0, v.vong
        assert v.so_fact_tho() == v.so_hop_le(), v.vong
        assert max(c.token_ra for t in v.tai_lieu for c in t.chunks) < 8192, v.vong


SO_KHOA_NGOAI_SUY = {
    "nap_corpus": 0.0378,
    "sinh_t7": 0.6178,
    "judge_do2": 5.5350,
    "vong_so_chunk": 0.2446,
    "gpt4o_dung_cuoi": 0.2479,
    "ensemble_a13": 0.0890,
}


def test_khoa_so_bang_ngoai_suy():
    """Đổi một đơn giá trong danh mục là bảng ngoại suy đổi; phải đỏ, không im."""
    from eval.ngoai_suy import MUC_BAO_DONG_USD, doc_so_do_nap, ngoai_suy

    bang = ngoai_suy(doc_so_do_nap())
    for ten, usd in SO_KHOA_NGOAI_SUY.items():
        assert bang.khoan_theo_ten(ten).chi_phi_usd == pytest.approx(usd, abs=5e-5), ten
    assert bang.tong_usd == pytest.approx(6.7720, abs=5e-5)
    assert bang.vuot_bao_dong is False
    assert bang.phan_tram_bao_dong == pytest.approx(100 * 6.7720 / MUC_BAO_DONG_USD, abs=0.01)


def test_chia_chunk_khop_chunk_ma_ainsert_that_ghi_ra(tmp_path):
    """Parity quan sát trên đường nạp thật, không phải dựng lại lời gọi chuẩn.

    Tài liệu dài hơn một chunk để phép chia thật sự cắt; nếu ai đó đổi ba tham
    số chunk của `EngineACL` thì harness lệch pipeline và test này đỏ.
    """
    import asyncio

    from adapters.chunking import chia_chunk
    from tests.ho_tro_ingest import (
        KHONG_FACT,
        dung_moi_truong,
        llm_theo_fact,
        phan_hoi_fact,
        viet_tai_lieu,
    )

    # Mỗi câu khác nhau: hai chunk trùng nội dung có cùng id md5 nên `ainsert`
    # lọc bớt một, và test sẽ đỏ vì một chuyện không phải cách chia chunk.
    than = " ".join(
        f"Máy chủ App{i:03d} chạy dịch vụ thanh toán số {i} và ghi nhật ký vào phân"
        f" vùng riêng theo quy định vận hành nội bộ số {i} của phòng Kỹ thuật."
        for i in range(220)
    )
    thu_muc = tmp_path / "data"
    viet_tai_lieu(thu_muc, "01-dai.txt", scope="noi_bo", content_type="runbook", than=than)
    fact = {"subject": "App01", "remediation": "ghi nhật ký vào phân vùng riêng"}
    mt = dung_moi_truong(tmp_path / "work", llm_theo_fact({}, mac_dinh=phan_hoi_fact([fact])))
    assert KHONG_FACT  # bản giả có sẵn cho ca 0 fact, không dùng ở đây

    from adapters.ingest import nap_thu_muc
    from adapters.policy_loader import load_policy

    policy = load_policy(REPO_ROOT / "config" / "policy-toi-gian.yaml")
    asyncio.run(
        nap_thu_muc(
            mt.engine,
            thu_muc,
            space="synth",
            policy_version=policy.policy_version,
            audit=mt.so_audit,
        )
    )
    chunk_kho = mt.kv("text_chunks", "synth")
    that = sorted(c["content"] for c in chunk_kho.values())
    assert len(that) > 1, "tài liệu phải dài hơn một chunk thì parity mới có nghĩa"
    assert sorted(c["content"] for c in chia_chunk(than)) == that
