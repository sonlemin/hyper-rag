"""Ba tỷ lệ n-ngôi: ca biên của I/O Matrix cộng số khóa của hai space (story 2.10).

Ba định nghĩa đếm chốt ở `docs/adr/ADR-012-dinh-nghia-dem-ba-ty-le-n-ngoi.md`.
File này là chỗ chúng bị khóa lại: **đổi một luật đếm là test đỏ**, không phải
một con số lặng lẽ khác đi ở bảng của chương 4.

Hai lớp assert:

- **Ca biên dựng tay.** Ngưỡng 3 vai, ngưỡng hạng 20, hyperedge không khóa lấy
  hạng cao nhất trong các `doc_key`, mẫu số nhạy cảm rỗng cho `None` chứ không
  cho 0, `E(h)` rỗng không vào tử số composition risk, và thiếu cả hai nguồn
  hạng là từ chối cả đợt.
- **Số khóa của hai space.** Ba tỷ lệ đếm trên ảnh chụp đã commit là những con
  số mà chương 4 báo cáo; viết tay ở đây để một lần nạp lại đổi số thì có chỗ
  đỏ, và người sửa phải đối chiếu lại chứ không chép số mới vào báo cáo.

Không test nào chạm kho hay gọi LLM: mọi thứ chạy trên ảnh chụp và trên
`AnhDoThi` dựng tay.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from adapters.sensitivity_loader import DUONG_DAN_MAC_DINH as HANG_MAC_DINH
from adapters.sensitivity_loader import tai_hang_do_nhay
from eval.cau_hoi import AnhDoThi, HyperedgeAnh, TaiLieuAnh, doc_anh_do_thi
from eval.ty_le_n_ngoi import (
    NGUONG_NHAY_CAM,
    NHAN_KHONG_KHOA,
    TOI_THIEU_VAI_N_NGOI,
    HangKhongXacDinh,
    ThieuCotDoiChieu,
    TyLe,
    ba_ty_le,
    doi_chieu,
    entity_cua,
    hang_cua_hyperedge,
    la_n_ngoi,
    loai_chung,
    loai_theo_doc_key,
    so_vai_da_dien,
)

GOC_REPO = Path(__file__).resolve().parent.parent
ANH_SYNTH = GOC_REPO / "eval" / "anh_do_thi" / "synth.json"
ANH_KHAO_SAT = GOC_REPO / "eval" / "anh_do_thi" / "khao_sat.json"

# Số khóa của space `synth`, đếm ngày 04/09/2026 trên ảnh chụp
# `eval/anh_do_thi/synth.json` (254 hyperedge / 50 tài liệu, chụp 03/09/2026).
# Viết tay chứ không tính lại trong test: một kỳ vọng tính bằng chính hàm đang
# đo là một test luôn xanh.
SYNTH_HYPEREDGE = 254
SYNTH_N_NGOI = 228
SYNTH_NHAY_CAM = 81
SYNTH_NHAY_CAM_N_NGOI = 76
SYNTH_COMPOSITION_RISK = 0

# Số khóa của space `khao_sat`, đếm ngày 04/09/2026 trên ảnh chụp
# `eval/anh_do_thi/khao_sat.json` (398 hyperedge / 50 bản ghi, chụp 04/09 ngay sau
# đợt nạp `32293e26e25f450bb7004ed3d4c63826`). Cùng luật viết tay với số của
# `synth`: một lần nạp lại làm số lệch thì phải đối chiếu lại, không chép số mới
# vào chương 4.
KHAO_SAT_HYPEREDGE = 398
KHAO_SAT_N_NGOI = 319
KHAO_SAT_NHAY_CAM = 151
KHAO_SAT_NHAY_CAM_N_NGOI = 133
KHAO_SAT_COMPOSITION_RISK = 0

# Ba hạng đóng băng từ story 2.1, ngưỡng nhạy cảm gắn vào số giữa.
HANG_RUNBOOK = 10
HANG_BAO_CAO_SU_CO = 20
HANG_BI_MAT_HA_TANG = 30


@pytest.fixture(scope="module")
def hang() -> dict[str, int]:
    return dict(tai_hang_do_nhay(HANG_MAC_DINH).hang)


def _he(id_he: str, khoa, slots, doc_key=("a.md",)) -> HyperedgeAnh:
    return HyperedgeAnh(
        id=id_he,
        doc_key=tuple(doc_key),
        khoa=khoa,
        slots={vai: tuple(gt) for vai, gt in slots.items()},
    )


def _anh(hyperedge, tai_lieu=(("a.md", "noi_bo", "runbook"),), space="thu") -> AnhDoThi:
    return AnhDoThi(
        version=2,
        space=space,
        ngay_do="2026-09-04T00:00:00+00:00",
        policy_version="x" * 8,
        tai_lieu=tuple(
            TaiLieuAnh(doc_key=d, sha256="0" * 64, scope=s, content_type=c)
            for d, s, c in tai_lieu
        ),
        hyperedge=tuple(hyperedge),
    )


# ---------------------------------------------------------------------------
# Định nghĩa 1: n-ngôi là từ 3 vai được điền
# ---------------------------------------------------------------------------


def test_nguong_n_ngoi_la_ba_vai():
    """Kỳ vọng viết tay, không đọc lại hằng: ngưỡng là một quyết định của ADR-012.

    Đọc `TOI_THIEU_VAI_N_NGOI` vào cả hai vế thì đổi hằng thành 2 vẫn xanh, tức
    mở lại một định nghĩa đã chốt mà không ai thấy.
    """
    assert TOI_THIEU_VAI_N_NGOI == 3
    hai = _he("h2", "noi_bo:runbook", {"subject": ["a"], "cause": ["b"]})
    ba = _he("h3", "noi_bo:runbook", {"subject": ["a"], "cause": ["b"], "time": ["t"]})
    assert so_vai_da_dien(hai) == 2 and not la_n_ngoi(hai)
    assert so_vai_da_dien(ba) == 3 and la_n_ngoi(ba)


def test_dem_vai_chu_khong_dem_entity():
    """Hai giá trị cùng vai là hai giá trị của một chiều, không phải hai chiều.

    Đếm entity thì hyperedge dưới đây thành "4 ngôi" và tỷ lệ 1 trở thành phép
    đo độ dài danh sách giá trị mà LLM trích ra.
    """
    h = _he("h", "noi_bo:runbook", {"subject": ["a"], "symptom": ["x", "y", "z"]})
    assert len(entity_cua(h)) == 4
    assert so_vai_da_dien(h) == 2
    assert not la_n_ngoi(h)


def test_vai_rong_khong_tinh_la_da_dien():
    h = _he("h", "noi_bo:runbook", {"subject": ["a"], "cause": ["b"], "time": []})
    assert so_vai_da_dien(h) == 2 and not la_n_ngoi(h)


# ---------------------------------------------------------------------------
# Định nghĩa 2: nhạy cảm là hạng từ 20
# ---------------------------------------------------------------------------


def test_nguong_nhay_cam_gan_vao_ba_hang_dong_bang(hang):
    """Ngưỡng 20 là hạng `bao_cao_su_co`, một trong ba hạng đóng băng từ story 2.1.

    Chọn một số đóng băng nghĩa là ngưỡng không trôi khi story 3.2 khai thêm
    loại nội dung. Đổi một trong ba số này là re-ingest, và khi đó ba tỷ lệ phải
    đếm lại - nên cả bốn con số bị khóa cùng một chỗ.
    """
    assert NGUONG_NHAY_CAM == HANG_BAO_CAO_SU_CO
    assert hang["runbook"] == HANG_RUNBOOK
    assert hang["bao_cao_su_co"] == HANG_BAO_CAO_SU_CO
    assert hang["bi_mat_ha_tang"] == HANG_BI_MAT_HA_TANG


def test_hang_lay_tu_khoa_loc_cua_hyperedge(hang):
    h = _he("h", "khach_hang_a:postmortem", {"subject": ["a"]})
    assert hang_cua_hyperedge(h, hang, {}) == hang["postmortem"]


def test_ranh_gioi_nhay_cam_dung_o_hai_muoi(hang):
    """`canh_bao` hạng 16 không nhạy cảm, `bao_cao_su_co` hạng 20 thì có."""
    duoi = _he("duoi", "noi_bo:canh_bao", {"subject": ["a"]})
    tren = _he("tren", "noi_bo:bao_cao_su_co", {"subject": ["b"]})
    kq = ba_ty_le(_anh([duoi, tren]), hang)
    assert kq.id_nhay_cam == ("tren",)
    assert kq.sensitive_n_ary.mau_so == 1


def test_hyperedge_khong_khoa_lay_hang_cao_nhat_trong_doc_key(hang):
    """Hàng "Hyperedge không khóa" của I/O Matrix: hợp nhất khác scope (AD-5).

    Chiều hạn chế nhất, không phải chiều thấp nhất. Fail-open ở đây là một fact
    ghép từ runbook cộng postmortem bị xếp không nhạy cảm, tức rơi khỏi mẫu số
    của hai trong ba tỷ lệ.
    """
    h = _he("h", None, {"subject": ["a"]}, doc_key=("r.md", "p.md"))
    theo_dk = {"r.md": "runbook", "p.md": "postmortem"}
    assert hang_cua_hyperedge(h, hang, theo_dk) == hang["postmortem"]
    assert hang["postmortem"] > hang["runbook"]


def test_thieu_ca_hai_nguon_hang_thi_tu_choi_ca_dot(hang):
    """Hàng "thiếu cả hai nguồn": từ chối cả đợt, không gán một hạng mặc định."""
    h = _he("h", None, {"subject": ["a"]}, doc_key=("mat.md",))
    with pytest.raises(HangKhongXacDinh) as loi:
        hang_cua_hyperedge(h, hang, {})
    assert loi.value.code == "HANG_KHONG_XAC_DINH"
    assert "h" in str(loi.value) and "mat.md" in str(loi.value)


def test_loai_noi_dung_khong_co_hang_thi_tu_choi_ca_dot(hang):
    h = _he("h", "noi_bo:runbok", {"subject": ["a"]})
    with pytest.raises(HangKhongXacDinh) as loi:
        hang_cua_hyperedge(h, hang, {})
    assert "runbok" in str(loi.value)


def test_ba_ty_le_tu_choi_ca_dot_khi_mot_hyperedge_khong_suy_duoc_hang(hang):
    """Một mục hỏng là cả đợt hỏng: một ảnh chụp nửa đếm được là một con số sai."""
    tot = _he("tot", "noi_bo:runbook", {"subject": ["a"]})
    hong = _he("hong", None, {"subject": ["b"]}, doc_key=("mat.md",))
    with pytest.raises(HangKhongXacDinh):
        ba_ty_le(_anh([tot, hong]), hang)


# ---------------------------------------------------------------------------
# Định nghĩa 3: composition risk
# ---------------------------------------------------------------------------


def test_composition_risk_can_moi_entity_deu_lo(hang):
    """"Mọi" chứ không "có ít nhất một": một mảnh không lộ là đủ chặn phép ghép."""
    lo = _he("lo", "noi_bo:runbook", {"subject": ["a"], "cause": ["b"]})
    du = _he("du", "noi_bo:bao_cao_su_co", {"subject": ["a"], "cause": ["b"]})
    thieu = _he("thieu", "noi_bo:bao_cao_su_co", {"subject": ["a"], "cause": ["rieng"]})
    kq = ba_ty_le(_anh([lo, du, thieu]), hang)
    assert kq.id_composition_risk == ("du",)
    assert kq.composition_risk.tu_so == 1
    assert kq.composition_risk.mau_so == 2
    # Ca "thiếu" lộ một phần (1/2 entity); ca "du" lộ hết nên nó là tử số của tỷ
    # lệ 3, không phải một ca "lộ một phần".
    assert kq.so_nhay_cam_lo_mot_phan == 1
    assert kq.so_nhay_cam_co_entity_lo == 2


def test_entity_chi_lo_o_hyperedge_nhay_cam_khac_thi_khong_tinh(hang):
    """Lộ ở một ca nhạy cảm khác không phải là lộ: người bị chặn vẫn không thấy nó."""
    a = _he("a", "noi_bo:bao_cao_su_co", {"subject": ["x"], "cause": ["y"]})
    b = _he("b", "noi_bo:postmortem", {"subject": ["x"], "cause": ["y"]})
    kq = ba_ty_le(_anh([a, b]), hang)
    assert kq.composition_risk.tu_so == 0
    assert kq.composition_risk.mau_so == 2


def test_hyperedge_nhay_cam_khong_entity_khong_vao_tu_so(hang):
    """`E(h)` rỗng: "mọi e đều lộ" đúng một cách rỗng, nên phải loại tường minh."""
    rong = _he("rong", "noi_bo:bao_cao_su_co", {})
    kq = ba_ty_le(_anh([rong]), hang)
    assert kq.composition_risk.tu_so == 0
    assert kq.composition_risk.mau_so == 1
    assert kq.so_nhay_cam_lo_mot_phan == 0


# ---------------------------------------------------------------------------
# Mẫu số rỗng, tử số và mẫu số tường minh
# ---------------------------------------------------------------------------


def test_mau_so_nhay_cam_rong_cho_none_khong_cho_khong(hang):
    """Hàng "Mẫu số nhạy cảm rỗng" của I/O Matrix.

    "Không có ca nào để đo" và "đo được và bằng không" là hai câu khác nhau; một
    trang in `0%` cho câu đầu là một trang nói dối.
    """
    h = _he("h", "noi_bo:runbook", {"subject": ["a"], "cause": ["b"], "time": ["t"]})
    kq = ba_ty_le(_anh([h]), hang)
    assert kq.sensitive_n_ary.mau_so == 0
    assert kq.sensitive_n_ary.ti_le is None
    assert kq.composition_risk.ti_le is None
    assert "mẫu số 0" in kq.sensitive_n_ary.mo_ta()
    assert kq.overall_n_ary.ti_le == 1.0


def test_moi_ty_le_mang_tu_so_va_mau_so_tuong_minh(hang):
    """AC: mỗi tỷ lệ in kèm tử số và mẫu số, không chỉ một phần trăm."""
    h = _he("h", "noi_bo:bao_cao_su_co", {"subject": ["a"], "cause": ["b"], "time": ["t"]})
    kq = ba_ty_le(_anh([h]), hang)
    for t in kq.bo_ba():
        assert isinstance(t.tu_so, int) and isinstance(t.mau_so, int)
        assert f"{t.tu_so}/{t.mau_so}" in t.mo_ta()


def test_hai_ty_le_sau_dung_chung_mau_so(hang):
    """Sensitive N-ary và Composition-Risk đọc cạnh nhau, nên mẫu số phải là một."""
    ds = [
        _he("a", "noi_bo:bao_cao_su_co", {"subject": ["x"]}),
        _he("b", "noi_bo:postmortem", {"subject": ["y"], "cause": ["z"], "time": ["t"]}),
        _he("c", "noi_bo:runbook", {"subject": ["x"]}),
    ]
    kq = ba_ty_le(_anh(ds), hang)
    assert kq.sensitive_n_ary.mau_so == kq.composition_risk.mau_so == 2
    assert kq.overall_n_ary.mau_so == 3


def test_ty_le_khong_chia_cho_khong():
    assert TyLe("x", 0, 0).ti_le is None
    assert TyLe("x", 1, 4).ti_le == 0.25


# ---------------------------------------------------------------------------
# Hàm thuần: cùng đầu vào là cùng đầu ra
# ---------------------------------------------------------------------------


def test_chay_hai_lan_tren_cung_anh_chup_cho_cung_ba_con_so(hang):
    """AC: chạy `eval.xem_ty_le` hai lần trên cùng ảnh chụp ra cùng ba con số."""
    anh = doc_anh_do_thi(ANH_SYNTH)
    a = ba_ty_le(anh, hang)
    b = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    assert a.bo_ba() == b.bo_ba()
    assert a.id_composition_risk == b.id_composition_risk
    assert a.phan_bo_hang == b.phan_bo_hang


def test_doi_chieu_giu_thu_tu_ba_ty_le_va_tinh_chenh(hang):
    trai = ba_ty_le(_anh([_he("a", "noi_bo:runbook", {"subject": ["x"]})]), hang)
    phai = ba_ty_le(
        _anh(
            [
                _he("b", "noi_bo:runbook", {"subject": ["x"], "cause": ["y"], "time": ["t"]}),
            ]
        ),
        hang,
    )
    dong = doi_chieu(trai, phai)
    assert [d.ten for d in dong] == [
        "Overall N-ary",
        "Sensitive N-ary",
        "Composition-Risk",
    ]
    assert dong[0].chenh == pytest.approx(1.0)
    # Cả hai space đều không có ca nhạy cảm nào: chênh không so được, không phải 0.
    assert dong[1].chenh is None and dong[2].chenh is None


def test_loai_theo_doc_key_doc_tu_so_tai_lieu_da_chup():
    anh = doc_anh_do_thi(ANH_SYNTH)
    theo_dk = loai_theo_doc_key(anh)
    assert len(theo_dk) == anh.so_tai_lieu
    assert theo_dk["k1-03-bao-cao-su-co-inc-1208.md"] == "bao_cao_su_co"


# ---------------------------------------------------------------------------
# Số khóa của hai space
# ---------------------------------------------------------------------------


def test_so_khoa_cua_space_synth(hang):
    """Ba tỷ lệ của corpus, đếm trên ảnh chụp đã commit.

    Đổi luật đếm, hoặc nạp lại corpus rồi chụp lại, đều làm những con số này
    lệch - và khi đó phải đối chiếu lại chứ không chép số mới vào chương 4.
    """
    kq = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    assert kq.space == "synth"
    assert kq.so_hyperedge == SYNTH_HYPEREDGE
    assert kq.overall_n_ary == TyLe("Overall N-ary", SYNTH_N_NGOI, SYNTH_HYPEREDGE)
    assert kq.sensitive_n_ary == TyLe(
        "Sensitive N-ary", SYNTH_NHAY_CAM_N_NGOI, SYNTH_NHAY_CAM
    )
    assert kq.composition_risk == TyLe(
        "Composition-Risk", SYNTH_COMPOSITION_RISK, SYNTH_NHAY_CAM
    )


def test_so_khoa_cua_space_khao_sat(hang):
    """Ba tỷ lệ của mẫu số khảo sát, đếm trên ảnh chụp đã commit.

    Nạp thật chạy 04/09/2026 sau khi sonlm duyệt (0,066651 USD, 50 NẠP / 0 TỪ
    CHỐI, rc=0 nên đối chiếu hai kho sạch). Số khóa viết tay như số của `synth`.
    """
    kq = ba_ty_le(doc_anh_do_thi(ANH_KHAO_SAT), hang)
    assert kq.space == "khao_sat"
    assert kq.so_tai_lieu == 50
    assert kq.so_hyperedge == KHAO_SAT_HYPEREDGE
    assert kq.overall_n_ary == TyLe("Overall N-ary", KHAO_SAT_N_NGOI, KHAO_SAT_HYPEREDGE)
    assert kq.sensitive_n_ary == TyLe(
        "Sensitive N-ary", KHAO_SAT_NHAY_CAM_N_NGOI, KHAO_SAT_NHAY_CAM
    )
    assert kq.composition_risk == TyLe(
        "Composition-Risk", KHAO_SAT_COMPOSITION_RISK, KHAO_SAT_NHAY_CAM
    )
    # Mẫu số nhạy cảm không rỗng: bảng thiết kế bắt buộc điều đó
    # (`tests/test_khao_sat.py::test_mau_so_nhay_cam_khong_rong`), nên một mẫu số
    # 0 ở đây là đợt nạp hỏng chứ không phải một tính chất của mẫu số.
    assert kq.sensitive_n_ary.mau_so > 0


def test_doi_chieu_hai_space_khop_co(hang):
    """AC: hai cột cạnh nhau kèm chênh lệch, đủ để kết luận khớp cỡ hay không.

    Kỳ vọng viết tay chứ không "chênh nhỏ hơn X": ngưỡng khớp cỡ không phải một
    con số đã chốt ở đâu, và một test tự đặt ngưỡng rồi tự đạt là một test không
    nói gì. Cái nó canh là ba chênh lệch còn đúng như lần đọc 04/09/2026, để một
    lần nạp lại đổi kết luận thì có chỗ đỏ.
    """
    trai = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    phai = ba_ty_le(doc_anh_do_thi(ANH_KHAO_SAT), hang)
    dong = doi_chieu(trai, phai)
    assert [d.ten for d in dong] == [
        "Overall N-ary",
        "Sensitive N-ary",
        "Composition-Risk",
    ]
    assert dong[0].chenh == pytest.approx(-0.0961, abs=5e-4)
    assert dong[1].chenh == pytest.approx(-0.0572, abs=5e-4)
    assert dong[2].chenh == pytest.approx(0.0, abs=1e-9)


def test_composition_risk_khong_tren_ca_hai_space_la_that(hang):
    """Composition-Risk 0/0 trên cả hai space là kết quả, không phải mẫu số hỏng.

    Hai số chẩn đoán nói vì sao: phần lớn ca nhạy cảm **có** entity lộ ở vùng
    không nhạy cảm, chỉ không lộ *hết*. Chuẩn hóa thực thể chưa làm (story 2.12)
    nên hai tài liệu hiếm khi sinh cùng một id entity, và một mảnh không lộ là đủ
    chặn phép ghép. Khóa hai số này lại để 2.12 chạy xong thì có chỗ đỏ buộc đếm
    lại chứ không phải một con số 0 đọc thành "không có rủi ro".
    """
    synth = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    khao_sat = ba_ty_le(doc_anh_do_thi(ANH_KHAO_SAT), hang)
    assert synth.so_nhay_cam_lo_mot_phan == 26
    assert khao_sat.so_nhay_cam_lo_mot_phan == 40
    # Tử số tỷ lệ 3 bằng 0, nên mọi ca có entity lộ đều là ca lộ *một phần*: hai
    # số này bằng nhau hôm nay, và chúng tách ra ngay khi 2.12 làm tử số khác 0.
    assert synth.so_nhay_cam_co_entity_lo == 26
    assert khao_sat.so_nhay_cam_co_entity_lo == 40
    assert synth.trung_binh_phan_entity_lo == pytest.approx(0.2985, abs=5e-4)
    assert khao_sat.trung_binh_phan_entity_lo == pytest.approx(0.2754, abs=5e-4)
    # Có ca lộ một phần mà không ca nào lộ hết: đó là hình dạng của kết quả.
    assert synth.so_nhay_cam_lo_mot_phan > synth.composition_risk.tu_so == 0
    assert khao_sat.so_nhay_cam_lo_mot_phan > khao_sat.composition_risk.tu_so == 0


# ---------------------------------------------------------------------------
# Ba số chẩn đoán: đếm đúng cái chúng khai
# ---------------------------------------------------------------------------


def test_lo_mot_phan_khong_dem_ca_lo_het(hang):
    """"Lộ một phần" là có entity lộ **mà không lộ hết**, không phải "có ít nhất một".

    Ca lộ hết chính là tử số của tỷ lệ 3, nên gộp nó vào đây là một con số cộng
    chung "gần thành rủi ro" với "đã là rủi ro". Trên dữ liệu thật hôm nay tử số
    bằng 0 nên hai cách đếm cho cùng một số - đó đúng là lúc dễ chép nhầm cách
    đọc nhất, nên ca này dựng tay để hai cách đếm tách ra được.
    """
    ds = [
        _he("lo", "noi_bo:runbook", {"subject": ["a"], "cause": ["b"]}),
        _he("het", "noi_bo:bao_cao_su_co", {"subject": ["a"], "cause": ["b"]}),
        _he("mot_phan", "noi_bo:bao_cao_su_co", {"subject": ["a"], "cause": ["rieng"]}),
        _he("khong", "noi_bo:bao_cao_su_co", {"subject": ["x"], "cause": ["y"]}),
    ]
    kq = ba_ty_le(_anh(ds), hang)
    assert kq.composition_risk.tu_so == 1  # "het"
    assert kq.so_nhay_cam_lo_mot_phan == 1  # chỉ "mot_phan"
    assert kq.so_nhay_cam_co_entity_lo == 2  # "het" + "mot_phan"


def test_trung_binh_phan_entity_lo_tinh_tren_nhom_co_lo(hang):
    """Mẫu số là ca **có ít nhất một entity lộ**, không phải mọi ca nhạy cảm.

    Câu con số này trả lời là "khi một ca đã hở, nó hở bao nhiêu". Trộn những ca
    hở 0% vào mẫu số làm nó thành một câu khác, và câu khác đó nhỏ hơn hẳn - đúng
    kiểu sai làm người đọc yên tâm nhầm.
    """
    ds = [
        _he("lo", "noi_bo:runbook", {"subject": ["a"]}),
        # 1/2 entity lộ
        _he("nua", "noi_bo:bao_cao_su_co", {"subject": ["a"], "cause": ["rieng"]}),
        # không entity nào lộ: phải nằm ngoài mẫu số
        _he("khong", "noi_bo:bao_cao_su_co", {"subject": ["x"], "cause": ["y"]}),
    ]
    kq = ba_ty_le(_anh(ds), hang)
    assert kq.so_nhay_cam_co_entity_lo == 1
    assert kq.trung_binh_phan_entity_lo == pytest.approx(0.5)


def test_trung_binh_phan_entity_lo_la_none_khi_khong_ca_nao_lo(hang):
    """Cùng luật với `TyLe.ti_le`: mẫu số rỗng là `None`, không phải 0.0.

    0.0 đọc thành "đã đo và không ca nào hở", còn sự thật là "không có ca nào để
    đo" - hai câu khác nhau, và cái sau không được phép đội lốt cái trước.
    """
    ds = [_he("mot_minh", "noi_bo:bao_cao_su_co", {"subject": ["chi-o-day"]})]
    kq = ba_ty_le(_anh(ds), hang)
    assert kq.so_nhay_cam_co_entity_lo == 0
    assert kq.trung_binh_phan_entity_lo is None


def test_ca_nhay_cam_khong_entity_nam_ngoai_ca_ba_so_chan_doan(hang):
    """`E(h)` rỗng: "hở bao nhiêu phần" không có nghĩa, nên nó không vào mẫu số nào."""
    kq = ba_ty_le(_anh([_he("rong", "noi_bo:bao_cao_su_co", {})]), hang)
    assert kq.composition_risk.tu_so == 0
    assert kq.so_nhay_cam_lo_mot_phan == 0
    assert kq.so_nhay_cam_co_entity_lo == 0
    assert kq.trung_binh_phan_entity_lo is None


# ---------------------------------------------------------------------------
# Bảng phân bố: ca không khóa có nhãn riêng
# ---------------------------------------------------------------------------


def test_ca_khong_khoa_khong_bi_don_vao_o_cua_mot_loai_that(hang):
    """Hyperedge không khóa không có `content_type` của riêng nó.

    Dồn nó vào ô của loại suy từ `doc_key` là nói dối hai lần: bảng đọc thành "có
    N hyperedge loại `postmortem`" trong khi một phần là ca không loại nào, và
    phép so hai space cộng chung hai thứ khác bản chất vào một ô.
    """
    ds = [
        _he("that", "noi_bo:postmortem", {"subject": ["a"]}),
        _he("khong_khoa", None, {"subject": ["b"]}, doc_key=("p.md",)),
    ]
    kq = ba_ty_le(_anh(ds, tai_lieu=(("p.md", "noi_bo", "postmortem"),)), hang)
    assert kq.phan_bo_loai["postmortem"] == 1
    nhan_rieng = [t for t in kq.phan_bo_loai if t.startswith(NHAN_KHONG_KHOA)]
    assert len(nhan_rieng) == 1
    assert "postmortem" in nhan_rieng[0], nhan_rieng
    assert kq.phan_bo_loai[nhan_rieng[0]] == 1
    # Hạng vẫn đúng: cả hai đều nhạy cảm, chỉ nhãn hiển thị là khác.
    assert kq.phan_bo_hang[hang["postmortem"]] == 2


# ---------------------------------------------------------------------------
# Số chép tay phải khớp nguồn tính ra nó
# ---------------------------------------------------------------------------


def test_precision_ghep_cap_khop_vong_chot():
    """`PRECISION_GHEP_CAP` phải bằng precision ghép cặp của vòng chốt 2.6.

    Luật số chép tay của story 2.7/2.8: một con số sống ở hai chỗ thì hai chỗ
    phải có một cái đỏ khi chúng lệch. Trang ba tỷ lệ giữ hằng thay vì chấm lại
    bốn vòng đo (kéo cả bộ vàng vào một trang chỉ cần *một* con số), nên chỗ canh
    là đây.
    """
    from eval.bo_vang import doc_bo_vang
    from eval.cham_trich_xuat import cham_bo
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong
    from eval.xem_ty_le import PRECISION_GHEP_CAP, VONG_CHOT_2_6

    vong = [v for v in doc_moi_vong(THU_MUC_KET_QUA) if v.vong == VONG_CHOT_2_6]
    assert len(vong) == 1, f"không tìm thấy vòng chốt {VONG_CHOT_2_6!r}"
    that = cham_bo(doc_bo_vang(), vong[0].facts_theo_tai_lieu()).chi_so.precision
    assert round(that, 3) == PRECISION_GHEP_CAP, (
        f"precision ghép cặp của {VONG_CHOT_2_6} là {that:.6f}, còn"
        f" eval/xem_ty_le.py chép {PRECISION_GHEP_CAP} - sửa hằng, đừng sửa test"
    )


# ---------------------------------------------------------------------------
# Trang hai cột
# ---------------------------------------------------------------------------


def test_trang_ghi_duoc_va_co_ca_hai_cot_cung_cot_chenh(tmp_path):
    """AC: hai cột cạnh nhau kèm chênh lệch, đủ để kết luận khớp cỡ hay không."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich)]) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "<th>synth</th>" in trang and "<th>khao_sat</th>" in trang
    assert "<th>chênh khao_sat - synth</th>" in trang
    for ten in ("Overall N-ary", "Sensitive N-ary", "Composition-Risk"):
        assert ten in trang
    # Tử số và mẫu số tường minh, không chỉ một phần trăm.
    assert f"{SYNTH_N_NGOI}/{SYNTH_HYPEREDGE}" in trang
    assert f"{KHAO_SAT_N_NGOI}/{KHAO_SAT_HYPEREDGE}" in trang
    # Hai điều phải đọc trước ba con số.
    assert "hệ trích được" in trang and "giả lập" in trang


def test_trang_noi_ra_hai_cot_khong_cung_truc_loai_noi_dung(tmp_path):
    """Khảo sát thiếu 4 loại, hai trong đó nhạy cảm; trang phải nói ra chỗ người đọc số."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich)]) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "không cùng trục loại nội dung" in trang
    for loai in ("cmdb", "faq", "log", "tai_lieu_san_pham"):
        assert loai in trang
    assert "loại nhạy cảm" in trang


def test_thieu_mot_anh_chup_thi_in_ten_file_va_lenh_dung_lai(tmp_path, capsys):
    """Không có nhánh dựng bảng một cột: thiếu ảnh nào là nói tên file cùng lệnh."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    ma = main([str(dich), "--anh-khao-sat", str(tmp_path / "chua-co.json")])
    assert ma == 1
    err = capsys.readouterr().err
    assert "chua-co.json" in err
    assert "--space khao_sat" in err, "phải in lệnh dựng lại được ảnh chụp"
    assert not dich.exists()


def test_tro_nham_hai_tham_so_ra_cung_mot_space_la_loi(tmp_path, capsys):
    """Ca sai nguy hiểm nhất: một space in hai lần, chênh 0, đọc thành khớp cỡ tuyệt đối."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-khao-sat", str(ANH_SYNTH)]) == 1
    err = capsys.readouterr().err
    assert "space 'synth'" in err and "khao_sat" in err
    assert not dich.exists()


def test_ly_do_tu_choi_anh_cham_hai_chieu():
    """Hàm thuần: đúng space thì `None`, lệch space thì một câu nói được cả hai."""
    from eval.xem_ty_le import ly_do_tu_choi_anh

    anh = doc_anh_do_thi(ANH_SYNTH)
    assert ly_do_tu_choi_anh(ANH_SYNTH, "synth", anh) is None
    ly_do = ly_do_tu_choi_anh(ANH_SYNTH, "khao_sat", anh)
    assert ly_do and "synth" in ly_do and "khao_sat" in ly_do


def test_bang_hang_hong_thi_in_ly_do_va_thoat_ma_1(tmp_path, capsys):
    from eval.xem_ty_le import main

    xau = tmp_path / "hang.yaml"
    xau.write_text("version: 1\nranks:\n  runbook: 10\n  sop: 10\n", encoding="utf-8")
    assert main([str(tmp_path / "x.html"), "--hang", str(xau)]) == 1
    assert capsys.readouterr().err.strip()


def test_khong_ghi_duoc_file_thi_tra_1_khong_ne_traceback(tmp_path, capsys):
    from eval.xem_ty_le import main

    chan = tmp_path / "chan"
    chan.write_text("khong phai thu muc", encoding="utf-8")
    assert main([str(chan / "sau" / "ty_le.html")]) == 1
    assert "không ghi được" in capsys.readouterr().err


def test_chay_bang_python_m_eval_xem_ty_le(tmp_path):
    """`python -m eval.xem_ty_le` chạy được từ gốc repo.

    Ghi vào `tmp_path` chứ không vào `eval/expr/ty_le_n_ngoi.html` thật: một bộ
    test không được sửa file của repo mỗi lần chạy.
    """
    dich = tmp_path / "ty_le.html"
    kq = subprocess.run(
        [sys.executable, "-m", "eval.xem_ty_le", str(dich)],
        cwd=GOC_REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert kq.returncode == 0, kq.stderr
    assert dich.exists()
    assert "Overall N-ary" in kq.stdout
    assert "chẩn đoán" in kq.stdout


# ---------------------------------------------------------------------------
# Cột thứ ba: space `real` (story 2.11)
# ---------------------------------------------------------------------------


def _anh_real(tmp_path: Path, ten: str = "real.json") -> Path:
    """Ảnh chụp `real` dựng tay trong `tmp_path`.

    Ảnh chụp `real` **thật** nằm ngoài cây repo (nó dump nguyên văn giá trị mọi
    slot của tài liệu công ty), nên test không có file nào để đọc và cũng không
    được có. Cái nó chấm là *hình dạng ba cột*, không phải con số của đợt nạp.
    """
    import json

    anh = {
        "version": 2,
        "space": "real",
        "ngay_do": "2026-09-04T00:00:00+00:00",
        "policy_version": "x" * 8,
        "so_tai_lieu": 1,
        "so_hyperedge": 1,
        "so_hyperedge_da_nguon": 0,
        "tai_lieu": [
            {
                "doc_key": "r1.md",
                "sha256": "0" * 64,
                "scope": "noi_bo",
                "content_type": "bao_cao_su_co",
            }
        ],
        "hyperedge": [
            {
                "id": "he-r1",
                "doc_key": ["r1.md"],
                "khoa": "noi_bo:bao_cao_su_co",
                "slots": {"subject": ["A"], "cause": ["B"], "time": ["T"]},
            }
        ],
    }
    dich = tmp_path / ten
    dich.write_text(json.dumps(anh, ensure_ascii=False), encoding="utf-8")
    return dich


def test_doi_chieu_nhan_ba_cot_va_chenh_deu_so_voi_cot_moc(hang):
    """Chữ ký cũ hai cột vẫn chạy; cột thứ ba so với **cột đầu**, không so dây chuyền.

    Cột đầu (`synth`) là tập duy nhất có precision trích xuất đã đo, nên nó là
    mốc. So `real` với `khao_sat` là so hai tập mà cả hai đều chưa neo vào gì.
    """
    mot_vai = ba_ty_le(_anh([_he("a", "noi_bo:runbook", {"subject": ["x"]})]), hang)
    ba_vai = ba_ty_le(
        _anh([_he("b", "noi_bo:runbook", {"subject": ["x"], "cause": ["y"], "time": ["t"]})]),
        hang,
    )
    dong = doi_chieu(mot_vai, ba_vai, mot_vai)
    assert [d.ten for d in dong] == ["Overall N-ary", "Sensitive N-ary", "Composition-Risk"]
    assert len(dong[0].cot) == 3
    assert dong[0].chenh_voi_moc(1) == pytest.approx(1.0)
    assert dong[0].chenh_voi_moc(2) == pytest.approx(0.0)
    # Ba tên cũ vẫn là hợp đồng của trang hai cột.
    assert dong[0].trai is dong[0].cot[0] and dong[0].phai is dong[0].cot[1]
    assert dong[0].chenh == dong[0].chenh_voi_moc(1)


def test_doi_chieu_mot_cot_la_loi_co_ma(hang):
    """Một cột đứng một mình không trả lời được câu hỏi khớp cỡ."""
    mot = ba_ty_le(_anh([_he("a", "noi_bo:runbook", {"subject": ["x"]})]), hang)
    with pytest.raises(ThieuCotDoiChieu) as loi:
        doi_chieu(mot)
    assert loi.value.code == "THIEU_COT_DOI_CHIEU"


def test_loai_chung_bang_giao_cua_moi_cot(hang):
    """Với hai cột nó đúng bằng phép hiệu hai chiều mà story 2.10 in ra."""
    a = ba_ty_le(_anh([_he("a", "noi_bo:runbook", {"subject": ["x"]})]), hang)
    b = ba_ty_le(
        _anh(
            [_he("b", "noi_bo:bao_cao_su_co", {"subject": ["x"]}, doc_key=("c.md",))],
            tai_lieu=(("c.md", "noi_bo", "bao_cao_su_co"),),
        ),
        hang,
    )
    assert loai_chung(a, b) == frozenset()
    assert loai_chung(a, a) == frozenset({"runbook"})


def test_trang_ba_cot_in_cot_real_va_canh_bao_bo_trich_xuat_khac(tmp_path):
    """AC: ba cột kèm cảnh báo cột `real` dùng bộ trích xuất khác."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-real", str(_anh_real(tmp_path))]) == 0
    trang = dich.read_text(encoding="utf-8")
    for cot in ("<th>synth</th>", "<th>khao_sat</th>", "<th>real</th>"):
        assert cot in trang
    assert "<th>chênh khao_sat - synth</th>" in trang
    assert "<th>chênh real - synth</th>" in trang
    assert "bộ trích xuất" in trang and "Qwen" in trang
    assert "chưa đo lần nào" in trang


def test_thieu_co_anh_real_thi_van_in_hai_cot_nhu_cu(tmp_path):
    """Hàng "Trang tỷ lệ thiếu cột real" của I/O Matrix."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich)]) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "<th>real</th>" not in trang
    assert "bộ trích xuất" not in trang
    assert "<th>chênh khao_sat - synth</th>" in trang


def test_anh_real_tro_nham_sang_space_khac_la_loi(tmp_path, capsys):
    """Cùng rào với hai cột kia: một ảnh `synth` cắm vào cột `real` là chênh 0 giả."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-real", str(ANH_SYNTH)]) == 1
    err = capsys.readouterr().err
    assert "space 'synth'" in err and "real" in err
    assert not dich.exists()


def test_thieu_anh_real_in_lenh_dung_lai_co_co_cuc_bo(tmp_path, capsys):
    """Lệnh dựng lại phải mang `HYPER_RAG_CUC_BO=1` và `--dich` ra ngoài repo."""
    from eval.xem_ty_le import main

    ma = main([str(tmp_path / "x.html"), "--anh-real", str(tmp_path / "chua-co.json")])
    assert ma == 1
    err = capsys.readouterr().err
    assert "HYPER_RAG_CUC_BO=1" in err and "--space real" in err and "--dich" in err


def test_console_ba_cot_in_ca_hai_canh_bao(tmp_path, capsys):
    from eval.xem_ty_le import main

    assert main([str(tmp_path / "ty_le.html"), "--anh-real", str(_anh_real(tmp_path))]) == 0
    ra = capsys.readouterr().out
    assert "(synth -> khao_sat)" in ra and "(synth -> real)" in ra
    assert "không cùng trục loại nội dung" in ra
    assert "Qwen 2.5 7B cục bộ" in ra
