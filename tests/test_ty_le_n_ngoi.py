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
    ThieuMauDoDai,
    dai_ba_ty_le,
    NHAN_KHONG_KHOA,
    TOI_THIEU_VAI_N_NGOI,
    VAI_THUC_THE,
    HangKhongXacDinh,
    KhongCoTaiLieuChung,
    ThieuCotDoiChieu,
    TyLe,
    ba_ty_le,
    doi_chieu,
    entity_cua,
    han_che_theo_tai_lieu,
    hang_cua_hyperedge,
    la_n_ngoi,
    loai_chung,
    loai_theo_doc_key,
    so_vai_da_dien,
    tai_lieu_chung,
)

GOC_REPO = Path(__file__).resolve().parent.parent
ANH_SYNTH = GOC_REPO / "eval" / "anh_do_thi" / "synth.json"
ANH_KHAO_SAT = GOC_REPO / "eval" / "anh_do_thi" / "khao_sat.json"
ANH_REAL = GOC_REPO / "eval" / "anh_do_thi" / "real_rut_gon.json"
ANH_THAT_KHU = GOC_REPO / "eval" / "anh_do_thi" / "that_khu_rut_gon.json"

# Số khóa của space `synth`, đếm ngày 05/09/2026 trên ảnh chụp
# `eval/anh_do_thi/synth.json` (281 hyperedge / 52 tài liệu, chụp 05/09 ngay sau
# đợt nạp lại `9c4a1ba7` của story 2.12). Viết tay chứ không tính lại trong
# test: một kỳ vọng tính bằng chính hàm đang đo là một test luôn xanh.
#
# **Số cũ của story 2.10 giữ lại để so, đúng như điều kiện đổi của ADR-012 đòi**
# (đếm 04/09 trên 254 hyperedge / 50 tài liệu): Overall 228/254 = 89,8% ·
# Sensitive 76/81 = 93,8% · Composition-Risk 0/81 = 0%.
#
# 52 tài liệu chứ không 50: corpus lên 42 (hai tài liệu bí danh của story 2.12)
# cộng 10 tài liệu bộ vàng, nạp lại **toàn bộ** sau `--xoa-space` để từ điển
# thực thể áp cho mọi tài liệu chứ không chỉ tài liệu mới.
SYNTH_HYPEREDGE = 281
SYNTH_N_NGOI = 252
SYNTH_NHAY_CAM = 93
SYNTH_NHAY_CAM_N_NGOI = 78
SYNTH_COMPOSITION_RISK = 0
# Số chẩn đoán **vai thực thể** (story 2.12): cùng phép đếm của tỷ lệ 3 nhưng
# `E(h)` thu về ba vai `subject`/`owner`/`source`. Đếm 05/09/2026 sau khi phép
# lộ đã siết theo scope; chưa siết là 13/93. Trên ảnh chụp *trước* đợt nạp lại
# nó là 8/81 (chưa siết 9/81).
SYNTH_CR_VAI_THUC_THE = 12

# Số khóa của space `khao_sat`, đếm ngày 05/09/2026 trên ảnh chụp
# `eval/anh_do_thi/khao_sat.json` (379 hyperedge / 50 bản ghi, chụp 05/09 ngay
# sau đợt nạp lại `3b0f428f` của story 2.12). Cùng luật viết tay với số của
# `synth`: một lần nạp lại làm số lệch thì phải đối chiếu lại, không chép số mới
# vào chương 4.
#
# **Số cũ của story 2.10 giữ lại để so** (đếm 04/09 trên 398 hyperedge, đợt
# `32293e26`): Overall 319/398 = 80,2% · Sensitive 133/151 = 88,1% ·
# Composition-Risk 0/151 = 0%. Đợt nạp lại **không** có từ điển thực thể (không
# có `config/tu-dien-thuc-the/khao_sat.yaml`); thứ đổi là **nội dung** 50 bản
# ghi - ba khiếm khuyết đã khai được sửa - cộng dao động của một lần chạy LLM.
KHAO_SAT_HYPEREDGE = 379
KHAO_SAT_N_NGOI = 308
KHAO_SAT_NHAY_CAM = 150
KHAO_SAT_NHAY_CAM_N_NGOI = 135
KHAO_SAT_COMPOSITION_RISK = 0
# Chẩn đoán vai thực thể (story 2.12), sau khi siết theo scope; chưa siết 13/150.
KHAO_SAT_CR_VAI_THUC_THE = 7

# Số khóa của space `real`, đếm ngày 04/09/2026 trên ảnh chụp **rút gọn**
# `eval/anh_do_thi/real_rut_gon.json` (369 hyperedge / 41 tài liệu, chụp 04/09
# ngay sau đợt nạp `45465ae0`). Bản rút gọn cho **đúng** ba con số của bản đầy
# đủ (`tests/test_anh_rut_gon.py`), nên số ở đây tính lại được từ repo y như số
# của hai space kia - đó là cả lý do bản rút gọn tồn tại.
#
# **41 chứ không 50**: 9 tài liệu ra 0 fact hợp lệ trên đường Qwen cục bộ và bị
# pipeline dọn sạch (4 ca JSON hỏng, 5 ca LLM trả danh sách rỗng). sonlm chốt
# nhận 41 làm mẫu số và báo cáo tỷ lệ mất 18% như một kết quả đo được, không nạp
# lại.
#
# **Hai số 100% là hiện tượng của bộ trích xuất, không phải của tri thức.** Ba
# dấu vân tay đo được ở dưới; đọc chúng trước khi đọc hai con số này.
REAL_HYPEREDGE = 369
REAL_TAI_LIEU = 41
REAL_N_NGOI = 369
REAL_NHAY_CAM = 144
REAL_NHAY_CAM_N_NGOI = 144
REAL_COMPOSITION_RISK = 0

# Số khóa của space `that_khu`, đếm ngày 05/09/2026 trên ảnh chụp **rút gọn**
# `eval/anh_do_thi/that_khu_rut_gon.json` (720 hyperedge / 50 tài liệu, chụp
# 05/09 ngay sau đợt nạp `6278dd87`). **Cùng 50 tài liệu đã khử với `real`, cùng
# nội dung từng byte** (sha256 từng file khớp), cùng muối băm - khác đúng ở bộ
# trích xuất: `deepseek-v4-flash` thay cho `qwen2.5:7b`.
#
# **50 chứ không 41**: DeepSeek trích được fact từ **cả 50** tài liệu, gồm cả ba
# tài liệu mà soát tay 05/09 xếp là "giới hạn corpus, bộ trích xuất nào cũng trả
# rỗng" (`ts-r-08`, `ts-r-10` 311 byte, `ts-r-11` 416 byte). Phép đo này **bác
# bỏ** cách phân loại đó: cả 9 ca mất của đường Qwen là lỗi bộ trích xuất, tức
# 18%, không phải 12%.
#
# Ba tỷ lệ thấp hơn `real` rất xa (67,8% so với 100,0%) và đó là điều phải đọc:
# hai con số 100% của `real` là hằng của bộ trích xuất, còn 67,8% là một phép đo.
# **Đợt thứ hai, 05/09/2026** (`13d3ed8d`, story 2.12): cùng 50 tài liệu đó,
# cùng model, **không** từ điển thực thể (từ điển của space này là nội dung tài
# liệu công ty nên nó không nằm trong `config/`). Nó là mẫu thứ hai của cùng
# một phép đo, thứ mà ledger của story 2.10 đã xin: hai lần chạy cùng đầu vào
# lệch nhau 720 -> 712 hyperedge, Overall 67,8% -> 75,0%, Sensitive 71,6% ->
# 81,0%. Ba tỷ lệ vì vậy là số của **một lần chạy**, không phải hằng của tập dữ
# liệu, và chương 4 phải trình chúng như thế.
#
# Số của đợt 05/09 sáng (`6278dd87`) giữ lại để so: 720 hyperedge, Overall
# 488/720 = 67,8% · Sensitive 161/225 = 71,6% · Composition-Risk 0/225 = 0%.
THAT_KHU_HYPEREDGE = 712
THAT_KHU_TAI_LIEU = 50
THAT_KHU_N_NGOI = 534
THAT_KHU_NHAY_CAM = 211
# Chẩn đoán vai thực thể của cột này (story 2.12), đếm 05/09/2026.
THAT_KHU_CR_VAI_THUC_THE = 4
THAT_KHU_NHAY_CAM_N_NGOI = 171
THAT_KHU_COMPOSITION_RISK = 0

# Số khóa của cột `that_khu` **hạn chế về 41 tài liệu có ở cả hai kho** - mẫu số
# của *khối đối chứng*, không của bảng chính. Hai mẫu số và cả hai đều đúng:
# bảng chính báo cáo `that_khu` trên cả 50 tài liệu (phép đo tốt nhất về hình
# dạng tri thức), còn phép so hai bộ trích xuất phải đứng trên đúng tập tài liệu
# có mặt ở cả hai vế - kho `real` chỉ có 41 vì Qwen làm rơi 9.
#
# Tính lại được ngay trong repo vì hai ảnh rút gọn dùng **chung một muối**: 41
# `doc_key` đã băm của `real` là tập con thật sự của 50 `doc_key` của `that_khu`.
THAT_KHU_CHUNG_TAI_LIEU = 41
THAT_KHU_CHUNG_HYPEREDGE = 614
THAT_KHU_CHUNG_N_NGOI = 444
THAT_KHU_CHUNG_NHAY_CAM = 203
THAT_KHU_CHUNG_NHAY_CAM_N_NGOI = 163
THAT_KHU_CHUNG_COMPOSITION_RISK = 0

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
    # Đợt nạp lại 05/09 đổi dấu của chênh thứ hai: `khao_sat` nay **cao hơn**
    # `synth` ở Sensitive N-ary. Số của story 2.10 là -9,6 và -5,7 điểm.
    assert dong[0].chenh == pytest.approx(-0.0841, abs=5e-4)
    assert dong[1].chenh == pytest.approx(+0.0613, abs=5e-4)
    assert dong[2].chenh == pytest.approx(0.0, abs=1e-9)


def test_composition_risk_khong_tren_ca_hai_space_la_that(hang):
    """Composition-Risk 0/0 trên cả hai space là kết quả, không phải mẫu số hỏng.

    Hai số chẩn đoán nói vì sao: phần lớn ca nhạy cảm **có** entity lộ ở vùng
    không nhạy cảm, chỉ không lộ *hết*. Chuẩn hóa thực thể chưa làm (story 2.12)
    nên hai tài liệu hiếm khi sinh cùng một id entity, và một mảnh không lộ là đủ
    chặn phép ghép. Khóa hai số này lại để 2.12 chạy xong thì có chỗ đỏ buộc đếm
    lại chứ không phải một con số 0 đọc thành "không có rủi ro".

    **Bốn con số này đổi ở story 2.12 vì hai nguyên nhân, và chúng phải tách
    ra.** Một, phép lộ nay siết theo scope (mục bổ sung 05/09/2026 của ADR-012):
    trên ảnh chụp *trước* đợt nạp lại nó đưa synth 26 -> 22 và khao_sat 40 -> 25.
    Hai, ba đợt nạp lại cùng ngày đổi chính đồ thị: số được assert dưới đây là
    **34/93** và **23/150**, đếm trên ảnh chụp sau đợt nạp.

    Ba tỷ lệ chính thức thì không đổi vì phép siết, và
    `test_siet_theo_scope_khong_doi_ba_ty_le_tren_bon_anh_da_commit` ngay dưới
    là chỗ khẳng định đó - nó chạy cả hai bản trên cùng bốn ảnh.
    """
    synth = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    khao_sat = ba_ty_le(doc_anh_do_thi(ANH_KHAO_SAT), hang)
    assert synth.so_nhay_cam_lo_mot_phan == 34
    assert khao_sat.so_nhay_cam_lo_mot_phan == 23
    # Tử số tỷ lệ 3 bằng 0, nên mọi ca có entity lộ đều là ca lộ *một phần*: hai
    # số này bằng nhau hôm nay, và chúng tách ra ngay khi 2.12 làm tử số khác 0.
    assert synth.so_nhay_cam_co_entity_lo == 34
    assert khao_sat.so_nhay_cam_co_entity_lo == 23
    assert synth.trung_binh_phan_entity_lo == pytest.approx(0.3479, abs=5e-4)
    assert khao_sat.trung_binh_phan_entity_lo == pytest.approx(0.2613, abs=5e-4)
    # Có ca lộ một phần mà không ca nào lộ hết: đó là hình dạng của kết quả.
    assert synth.so_nhay_cam_lo_mot_phan > synth.composition_risk.tu_so == 0
    assert khao_sat.so_nhay_cam_lo_mot_phan > khao_sat.composition_risk.tu_so == 0


# ---------------------------------------------------------------------------
# Siết phép lộ theo scope (story 2.12, ca 3 của "Điều kiện đổi định nghĩa")
# ---------------------------------------------------------------------------


def test_siet_theo_scope_khong_doi_ba_ty_le_tren_bon_anh_da_commit(hang):
    """Bằng chứng đo được của mục bổ sung ADR-012 ngày 05/09/2026.

    ADR-012 đòi ba điều khi đổi một định nghĩa, và một trong ba là ba tỷ lệ được
    đếm lại với số cũ giữ lại để so. Ở thời điểm chốt, siết theo scope **không
    đổi một con số nào** trên cả bốn ảnh chụp đã commit - tử số tỷ lệ 3 đang bằng
    0 ở cả bốn, nên phép siết chỉ có thể giữ nguyên nó. Đây là cửa sổ an toàn mà
    chính ADR mô tả, và test này là chỗ nó được khẳng định bằng máy chứ không
    bằng một câu trong tài liệu.

    Test sẽ đỏ ngay khi một lần nạp lại làm tử số khác 0 - đúng lúc phải đọc lại
    ADR trước khi báo cáo con số mới.
    """
    for duong_dan in (ANH_SYNTH, ANH_KHAO_SAT, ANH_REAL, ANH_THAT_KHU):
        anh = doc_anh_do_thi(duong_dan)
        cu = ba_ty_le(anh, hang, siet_theo_scope=False)
        moi = ba_ty_le(anh, hang, siet_theo_scope=True)
        assert cu.bo_ba() == moi.bo_ba(), duong_dan.name
        assert moi.siet_theo_scope is True and cu.siet_theo_scope is False


def test_siet_theo_scope_bo_phep_ghep_khong_ai_thuc_hien_duoc(hang):
    """Mảnh lộ ở scope khác không còn tính là lộ.

    Ca dựng tay: một ca nhạy cảm của `khach_hang_a` có đúng một entity, và entity
    đó chỉ xuất hiện ở một hyperedge không nhạy cảm của `khach_hang_b`. Không vai
    nào thấy cả hai khoang, nên phép ghép đó không ai thực hiện được - định nghĩa
    gốc vẫn đếm nó, bản siết thì không.
    """
    nhay = _he("n", "khach_hang_a:bao_cao_su_co", {"subject": ["web01"]})
    lo_ben_kia = _he("k", "khach_hang_b:runbook", {"subject": ["web01"]})
    anh = _anh([nhay, lo_ben_kia])
    assert ba_ty_le(anh, hang, siet_theo_scope=False).composition_risk.tu_so == 1
    assert ba_ty_le(anh, hang, siet_theo_scope=True).composition_risk.tu_so == 0


def test_siet_theo_scope_giu_phep_ghep_trong_cung_scope(hang):
    """Cùng ca đó nhưng hai hyperedge cùng scope thì vẫn là composition risk."""
    nhay = _he("n", "khach_hang_a:bao_cao_su_co", {"subject": ["web01"]})
    lo_cung_scope = _he("k", "khach_hang_a:runbook", {"subject": ["web01"]})
    anh = _anh([nhay, lo_cung_scope])
    assert ba_ty_le(anh, hang, siet_theo_scope=True).composition_risk.tu_so == 1


def test_hyperedge_khong_khoa_nhin_thay_phan_lo_cua_moi_scope_sinh_ra_no(hang):
    """Ca AD-5: hyperedge không khóa thuộc về **mọi** scope của `doc_key` nó.

    Phía an toàn là phía đếm nhiều rủi ro hơn, đúng chiều mà `hang_cua_hyperedge`
    đã chọn khi lấy hạng **cao nhất**.
    """
    nhay = _he("n", None, {"subject": ["web01"]}, doc_key=("a.md", "b.md"))
    lo_b = _he("k", "khach_hang_b:runbook", {"subject": ["web01"]})
    anh = _anh(
        [nhay, lo_b],
        tai_lieu=(
            ("a.md", "khach_hang_a", "bao_cao_su_co"),
            ("b.md", "khach_hang_b", "runbook"),
        ),
    )
    assert ba_ty_le(anh, hang, siet_theo_scope=True).composition_risk.tu_so == 1


def test_composition_risk_vai_thuc_the_la_chan_doan_khong_phai_ty_le_thu_tu(hang):
    """Chỉ ba vai `subject`/`owner`/`source` vào tập entity của số chẩn đoán.

    Ca dựng tay: mọi thực thể của một ca nhạy cảm đều lộ, nhưng `remediation` của
    nó là một mệnh đề không lặp lại ở đâu. Tỷ lệ chính thức đếm cả mệnh đề nên nó
    bằng 0; số chẩn đoán chỉ đếm ba vai thực thể nên nó bằng 1. Đó đúng là hình
    dạng mà `E(h)` của ADR-012 tạo ra trên dữ liệu thật, và là lý do số này tồn
    tại.
    """
    nhay = _he(
        "n",
        "noi_bo:bao_cao_su_co",
        {
            "subject": ["web01"],
            "owner": ["Phòng IT"],
            "remediation": ["khởi động lại pool php-fpm rồi kiểm tra lại log"],
        },
    )
    lo = _he("k", "noi_bo:runbook", {"subject": ["web01"], "owner": ["Phòng IT"]})
    kq = ba_ty_le(_anh([nhay, lo]), hang)
    assert kq.composition_risk.tu_so == 0
    assert kq.composition_risk_vai_thuc_the.tu_so == 1
    assert kq.id_composition_risk_vai_thuc_the == ("n",)
    # Cùng mẫu số với tỷ lệ 3: hai số đọc cạnh nhau mới nói được điều gì.
    assert kq.composition_risk_vai_thuc_the.mau_so == kq.composition_risk.mau_so


def test_so_chan_doan_vai_thuc_the_cua_bon_anh_da_commit(hang):
    """Số khóa của dòng chẩn đoán mới, đếm 05/09/2026 trên bốn ảnh đã commit.

    Bốn con số đọc từ chính bốn hằng ở đầu file, **sau khi siết theo scope** và
    **sau ba đợt nạp lại 05/09**: `synth` 12/93, `khao_sat` 7/150, `real` 0/144,
    `that_khu` 4/211. Chưa siết thì `synth` là 13/93, và khoảng cách giữa hai
    con số đó chính là phần "phép ghép không ai thực hiện được".

    Trên ảnh chụp *trước* đợt nạp lại nó là 8/81 (chưa siết 9/81); spec của
    story 2.12 trích con số 9/81 đó.
    """
    so = {}
    for ten, duong_dan in (
        ("synth", ANH_SYNTH),
        ("khao_sat", ANH_KHAO_SAT),
        ("real", ANH_REAL),
        ("that_khu", ANH_THAT_KHU),
    ):
        kq = ba_ty_le(doc_anh_do_thi(duong_dan), hang)
        so[ten] = (
            kq.composition_risk_vai_thuc_the.tu_so,
            kq.composition_risk_vai_thuc_the.mau_so,
        )
    assert so == {
        "synth": (SYNTH_CR_VAI_THUC_THE, SYNTH_NHAY_CAM),
        "khao_sat": (KHAO_SAT_CR_VAI_THUC_THE, KHAO_SAT_NHAY_CAM),
        "real": (0, REAL_NHAY_CAM),
        "that_khu": (THAT_KHU_CR_VAI_THUC_THE, THAT_KHU_NHAY_CAM),
    }, so
    # Chưa siết theo scope thì cao hơn ở hai cột corpus dựng; khoảng cách đó là
    # phần "phép ghép không ai thực hiện được".
    chua_siet = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang, siet_theo_scope=False)
    assert chua_siet.composition_risk_vai_thuc_the.tu_so == 13


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


def test_trang_in_so_chan_doan_vai_thuc_the(tmp_path):
    """AC story 2.12: kết luận mỏ neo phát biểu được **kèm số chẩn đoán vai thực thể**.

    Số 0 của tỷ lệ 3 đọc được hai cách; dòng vai thực thể là chỗ người đọc chương
    4 phân biệt "0 vì tri thức kín" với "0 vì `E(h)` đếm cả mệnh đề".
    """
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich)]) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "vai mang thực thể" in trang
    for vai in VAI_THUC_THE:
        assert f"<code>{vai}</code>" in trang or vai in trang
    # Con số của cột mốc, tính từ chính ảnh chụp.
    assert f"{SYNTH_CR_VAI_THUC_THE}/{SYNTH_NHAY_CAM}" in trang
    # Và trang nói ra rằng phép lộ đã siết theo scope.
    assert "siết theo scope" in trang


def test_ket_luan_mo_neo_mang_so_chan_doan_vai_thuc_the(tmp_path):
    """Khối đối chứng bốn cột: câu kết luận mỏ neo phải mang cả hai con số."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    ma = main(
        [
            str(dich),
            "--anh-real",
            str(ANH_REAL),
            "--anh-that-khu",
            str(ANH_THAT_KHU),
        ]
    )
    assert ma == 0
    trang = dich.read_text(encoding="utf-8")
    assert "Mỏ neo Composition-Risk" in trang
    assert f"{THAT_KHU_CR_VAI_THUC_THE}/{THAT_KHU_NHAY_CAM}" in trang
    assert f"{SYNTH_CR_VAI_THUC_THE}/{SYNTH_NHAY_CAM}" in trang
    assert "chẩn đoán" in trang


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
    # Story 2.13 thay câu "chưa đo lần nào" bằng con số đo được; trang phải mang
    # **cả hai** vế, precision của Qwen và của DeepSeek, nếu không người đọc chỉ
    # thấy một số mà không có gì để so.
    # 71,0% là precision của `v3-deepseek-tu-dien`, vòng chốt từ story 2.12.
    assert "48.2%" in trang and "71.0%" in trang and "dưới cổng" in trang


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


def test_cot_real_nhan_ca_ban_rut_gon(tmp_path):
    """`--anh-real` nhận cả ảnh đầy đủ (ngoài repo) lẫn ảnh rút gọn (có commit).

    Bản rút gọn là dạng duy nhất của `real` đi vào repo được, nên nếu cờ chỉ
    nhận dạng đầy đủ thì trang ba cột chỉ dựng được trên máy có file ngoài repo -
    tức không ai đọc repo dựng lại được nó.
    """
    import json

    from eval.anh_rut_gon import rut_gon_anh
    from eval.xem_ty_le import main

    goc = json.loads(_anh_real(tmp_path).read_text(encoding="utf-8"))
    rut = tmp_path / "real_rut_gon.json"
    rut.write_text(
        json.dumps(rut_gon_anh(goc, "muoi-du-dai-cho-test-0123456789"), ensure_ascii=False),
        encoding="utf-8",
    )
    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-real", str(rut)]) == 0
    trang = dich.read_text(encoding="utf-8")
    # Tiêu đề cột nói ra dạng nào đang được dùng.
    assert "<th>real_rut_gon</th>" in trang
    # Và cảnh báo bộ trích xuất khác vẫn in: nó gắn với space, không với dạng file.
    assert "Qwen" in trang and "48.2%" in trang


def test_cot_real_hai_dang_cho_cung_ba_ty_le(tmp_path, hang):
    """Tính chất làm bản rút gọn dùng được: hai dạng cho **cùng** ba con số."""
    import json

    from eval.anh_rut_gon import rut_gon_anh

    day_du = json.loads(_anh_real(tmp_path).read_text(encoding="utf-8"))
    rut = rut_gon_anh(day_du, "muoi-du-dai-cho-test-0123456789")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(day_du, ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(rut, ensure_ascii=False), encoding="utf-8")
    assert ba_ty_le(doc_anh_do_thi(a), hang).bo_ba() == ba_ty_le(doc_anh_do_thi(b), hang).bo_ba()


# ---------------------------------------------------------------------------
# Số khóa của space `real` (story 2.11)
# ---------------------------------------------------------------------------


def test_so_khoa_cua_space_real(hang):
    """Ba tỷ lệ của tài liệu thật, đếm trên ảnh chụp **rút gọn** đã commit.

    Cùng khuôn với hai space kia và vì cùng một lý do: một lần nạp lại `real`
    làm số lệch thì phải đối chiếu lại, không chép số mới vào chương 4. Bản rút
    gọn là thứ làm phép khóa này khả thi - ảnh đầy đủ không commit được.
    """
    kq = ba_ty_le(doc_anh_do_thi(ANH_REAL), hang)
    assert kq.space == "real_rut_gon"
    assert kq.so_tai_lieu == REAL_TAI_LIEU
    assert kq.so_hyperedge == REAL_HYPEREDGE
    assert kq.overall_n_ary == TyLe("Overall N-ary", REAL_N_NGOI, REAL_HYPEREDGE)
    assert kq.sensitive_n_ary == TyLe(
        "Sensitive N-ary", REAL_NHAY_CAM_N_NGOI, REAL_NHAY_CAM
    )
    assert kq.composition_risk == TyLe(
        "Composition-Risk", REAL_COMPOSITION_RISK, REAL_NHAY_CAM
    )


def test_chan_doan_composition_risk_cua_real(hang):
    """Composition-Risk 0 trên `real` cũng là kết quả, không phải mẫu số hỏng.

    Cùng hình dạng với hai space kia: phần lớn ca nhạy cảm **có** entity lộ ở
    vùng không nhạy cảm, chỉ không lộ hết. Chuẩn hóa thực thể chưa làm (2.12).
    """
    kq = ba_ty_le(doc_anh_do_thi(ANH_REAL), hang)
    assert kq.so_nhay_cam_lo_mot_phan == 85
    assert kq.so_nhay_cam_co_entity_lo == 85
    assert kq.trung_binh_phan_entity_lo == pytest.approx(0.2590, abs=5e-4)


def test_hai_ty_le_100_phan_tram_cua_real_la_hien_tuong_cua_bo_trich_xuat(hang):
    """**Đọc test này trước khi đọc hai con số 100% ở trên.**

    Ba dấu vân tay đo được, khóa bằng giá trị để một lần nạp lại đổi kết luận
    thì có chỗ đỏ. Chúng nói rằng 100% là hằng của bộ trích xuất chứ không phải
    phép đo về tri thức:

    1. `real` **không có một hyperedge 2 vai nào**, trong khi `synth` có 10,2%.
       Ngưỡng n-ngôi là 3 vai, nên một tập không bao giờ xuống dưới 3 cho tỷ lệ
       1 bằng 100% *theo định nghĩa*.
    2. Vai `owner` được điền ở 96,5% hyperedge của `real` so với 18,9% của
       `synth` - trên một tập mà phần lớn tài liệu là runbook và tài liệu sản
       phẩm, thứ không nêu người phụ trách.
    3. 9,5% hyperedge của `real` có một entity ở hai vai trở lên, `synth` 0,4%.
    """
    real = ba_ty_le(doc_anh_do_thi(ANH_REAL), hang)
    synth = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)

    assert real.phan_hyperedge_hai_vai() == 0.0
    assert synth.phan_hyperedge_hai_vai() == pytest.approx(0.1032, abs=5e-4)
    assert real.so_vai_pho_bien_nhat() == 5
    assert synth.so_vai_pho_bien_nhat() == 3
    assert min(real.phan_bo_so_vai) == 3, "real không có hyperedge dưới 3 vai"

    vai, cua_real, cua_synth = real.vai_da_dien_nhieu_nhat(synth)
    assert vai == "owner"
    assert cua_real == pytest.approx(0.9648, abs=5e-4)
    assert cua_synth == pytest.approx(0.1851, abs=5e-4)

    assert real.phan_entity_lap_vai() == pytest.approx(0.0949, abs=5e-4)
    assert synth.phan_entity_lap_vai() == pytest.approx(0.0320, abs=5e-4)


def test_canh_bao_cot_real_mang_ba_bang_chung_do_duoc(tmp_path):
    """Cảnh báo phải in **số**, không chỉ câu "precision chưa đo lần nào".

    Cột `real` ra 100% ở hai tỷ lệ đầu; một người đọc thấy 100% mà không có số
    đối chiếu sẽ đọc thành một kết quả rất tốt. Và số phải tính từ chính hai ảnh
    chụp: một cảnh báo mang số chép tay nói về lần nạp trước chứ không về file
    đang mở.
    """
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-real", str(ANH_REAL)]) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "0.0%" in trang and "10.3%" in trang, "dấu 1: hyperedge 2 vai"
    assert "<code>owner</code>" in trang and "96.5%" in trang, "dấu 2: vai điền thừa"
    assert "9.5%" in trang and "3.2%" in trang, "dấu 3: entity lặp giữa các vai"
    assert "không khôi phục được mỏ neo Composition-Risk" in trang


def test_console_cot_real_in_cung_ba_bang_chung(tmp_path, capsys):
    """Console và trang nói cùng một thứ, dựng từ **một** hàm.

    Một bản console viết tay là bản thứ hai của cùng ba câu, và hai bản sẽ trôi
    khỏi nhau đúng lúc người đọc console tin rằng nó nói cùng thứ với trang.
    """
    from eval.xem_ty_le import main

    assert main([str(tmp_path / "x.html"), "--anh-real", str(ANH_REAL)]) == 0
    ra = capsys.readouterr().out
    assert "owner" in ra and "96.5%" in ra
    assert "KHÔNG khôi phục được mỏ neo Composition-Risk" in ra
    assert "<b>" not in ra, "dòng console không được mang thẻ HTML"


def test_chi_mot_cot_co_nghia_la_dung_mot_cot(hang, tmp_path):
    """"chỉ X có" phải đúng nghĩa "đúng một cột có".

    Với hai cột, "nằm ngoài phần giao" và "chỉ một cột có" là một; với ba cột
    thì không. Một loại mà **hai** trong ba cột cùng có nằm ngoài phần giao của
    cả ba, nên công thức cũ in nó thành "chỉ A có" *và* "chỉ B có" cùng lúc -
    hai câu, cả hai sai, ngay cạnh nhau.
    """
    from eval.xem_ty_le import _loai_rieng

    def cot(space, cac_loai):
        return ba_ty_le(
            _anh(
                [
                    _he(f"{space}-{i}", f"noi_bo:{loai}", {"subject": ["x"]},
                        doc_key=(f"{space}.md",))
                    for i, loai in enumerate(cac_loai)
                ],
                tai_lieu=((f"{space}.md", "noi_bo", cac_loai[0]),),
                space=space,
            ),
            hang,
        )

    # `runbook` có ở cả ba; `sop` có ở hai; `faq` chỉ ở một.
    a = cot("a", ["runbook", "sop", "faq"])
    b = cot("b", ["runbook", "sop"])
    c = cot("c", ["runbook"])
    rieng = dict(_loai_rieng([a, b, c]))
    assert rieng["a"] == ["faq"], "chỉ `faq` là của riêng một cột"
    assert rieng["b"] == [] and rieng["c"] == []


def test_entity_lap_vai_khong_dem_trung_trong_cung_mot_vai(hang):
    """Chỉ số khai "một entity ở hai vai trở lên"; trùng *trong* một vai là
    chuyện khác (LLM lặp một giá trị) và trộn hai thứ làm câu cảnh báo nói sai
    thứ nó đang đo."""
    trong_mot_vai = ba_ty_le(
        _anh([_he("a", "noi_bo:runbook", {"subject": ["X", "X"], "cause": ["Y"]})]), hang
    )
    hai_vai = ba_ty_le(
        _anh([_he("b", "noi_bo:runbook", {"subject": ["X"], "cause": ["X"]})]), hang
    )
    assert trong_mot_vai.so_entity_lap_vai == 0
    assert hai_vai.so_entity_lap_vai == 1


# ---------------------------------------------------------------------------
# Cột thứ tư: space `that_khu` (story 2.13)
# ---------------------------------------------------------------------------


def _anh_that_khu(tmp_path: Path, ten: str = "that_khu.json") -> Path:
    """Ảnh chụp `that_khu` dựng tay: **cùng tài liệu** với `_anh_real`, ít vai hơn.

    Ảnh chụp thật của `that_khu` nằm ngoài cây repo ở dạng đầy đủ (cùng luật với
    `real`: nội dung tuy đã khử vẫn là văn bản công ty), nên test không có file
    nào để đọc và cũng không được có. Cái nó chấm là *hình dạng bốn cột* và khối
    đối chứng, không phải con số của đợt nạp.

    Hai vai thay vì bốn là để khối đối chứng có gì để in: đó đúng là dấu vân tay
    mà story 2.11 đo được giữa Qwen và DeepSeek trên hai tập khác nhau, ở đây
    trên cùng một tập.
    """
    import json

    anh = {
        "version": 2,
        "space": "that_khu",
        "ngay_do": "2026-09-05T00:00:00+00:00",
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
                "id": "he-t1",
                "doc_key": ["r1.md"],
                "khoa": "noi_bo:bao_cao_su_co",
                "slots": {"subject": ["A"], "cause": ["B"]},
            }
        ],
    }
    dich = tmp_path / ten
    dich.write_text(json.dumps(anh, ensure_ascii=False), encoding="utf-8")
    return dich


def test_trang_bon_cot_in_cot_that_khu(tmp_path):
    """AC: bốn cột, cột thứ tư kèm chênh so với **cột mốc** như ba cột kia."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    ma = main(
        [
            str(dich),
            "--anh-real",
            str(_anh_real(tmp_path)),
            "--anh-that-khu",
            str(_anh_that_khu(tmp_path)),
        ]
    )
    assert ma == 0
    trang = dich.read_text(encoding="utf-8")
    for cot in ("<th>synth</th>", "<th>khao_sat</th>", "<th>real</th>", "<th>that_khu</th>"):
        assert cot in trang
    assert "<th>chênh that_khu - synth</th>" in trang


def test_thieu_co_anh_that_khu_thi_trang_van_in_ba_cot_nhu_2_11(tmp_path):
    """Cột thứ tư là **tùy chọn**, cùng khuôn với cột `real` của story 2.11."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-real", str(_anh_real(tmp_path))]) == 0
    trang = dich.read_text(encoding="utf-8")
    assert "<th>that_khu</th>" not in trang
    assert "Đối chứng Qwen / DeepSeek" not in trang


def test_anh_that_khu_tro_nham_sang_space_khac_la_loi(tmp_path, capsys):
    """Cùng rào với ba cột kia: một ảnh `synth` cắm vào cột `that_khu` là chênh 0 giả."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-that-khu", str(ANH_SYNTH)]) == 1
    err = capsys.readouterr().err
    assert "space 'synth'" in err and "that_khu" in err
    assert not dich.exists()


def test_thieu_anh_that_khu_in_lenh_dung_lai_khong_co_co_cuc_bo(tmp_path, capsys):
    """Lệnh dựng lại của `that_khu` **không** mang `HYPER_RAG_CUC_BO=1`.

    Đó là cả điểm của story: bản đã khử đi ra API ngoài được (NFR-05), nên đợt
    này chạy đúng đường nạp của `synth` và `khao_sat`. Một lệnh dựng lại mang cờ
    cục bộ là chép nhầm lệnh của `real` và người chạy lại nạp bằng Qwen.
    """
    from eval.xem_ty_le import main

    ma = main([str(tmp_path / "x.html"), "--anh-that-khu", str(tmp_path / "chua-co.json")])
    assert ma == 1
    err = capsys.readouterr().err
    assert "--space that_khu" in err and "--rut-gon" in err
    assert "HYPER_RAG_CUC_BO=1" not in err


def test_cot_that_khu_nhan_ca_ban_rut_gon(tmp_path):
    """Bản rút gọn là dạng duy nhất của `that_khu` đi vào repo được."""
    import json

    from eval.anh_rut_gon import rut_gon_anh
    from eval.xem_ty_le import main

    goc = json.loads(_anh_that_khu(tmp_path).read_text(encoding="utf-8"))
    rut = tmp_path / "that_khu_rut_gon.json"
    rut.write_text(
        json.dumps(rut_gon_anh(goc, "muoi-du-dai-cho-test-0123456789"), ensure_ascii=False),
        encoding="utf-8",
    )
    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-that-khu", str(rut)]) == 0
    assert "<th>that_khu_rut_gon</th>" in dich.read_text(encoding="utf-8")


def test_khoi_doi_chung_noi_ro_bo_trich_xuat_la_bien_duy_nhat(tmp_path):
    """AC: trang phát biểu **bộ trích xuất là biến duy nhất đi vào ba tỷ lệ**.

    Và nói rõ model embedding cũng khác (`bge-m3` với `text-embedding-3-small`)
    nhưng không vào phép đếm nào của ADR-012 - ba định nghĩa đếm đọc số vai được
    điền, hạng theo `content_type` và entity chung giữa các hyperedge, không đọc
    một vector nào. Để câu "khác đúng một biến" đứng trần là nói quá.
    """
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert (
        main(
            [
                str(dich),
                "--anh-real",
                str(_anh_real(tmp_path)),
                "--anh-that-khu",
                str(_anh_that_khu(tmp_path)),
            ]
        )
        == 0
    )
    trang = dich.read_text(encoding="utf-8")
    # Số tài liệu lấy từ chính hai ảnh, **không** chép cứng vào chuỗi: fixture
    # này có đúng một tài liệu, và một câu "cùng 50 tài liệu" in trên nó là một
    # câu nói về thư mục nguồn chứ không về hai thứ đang được so.
    assert "Đối chứng Qwen / DeepSeek trên 1 tài liệu có ở cả hai kho" in trang
    assert "50" not in trang.split("Đối chứng Qwen")[1].split("</div>")[0]
    assert "bộ trích xuất là biến duy nhất đi vào" in trang
    assert "bge-m3" in trang and "text-embedding-3-small" in trang
    assert "không vào phép đếm nào" in trang


def test_khoi_doi_chung_phat_bieu_duoc_ve_mo_neo_composition_risk(tmp_path):
    """AC: kết luận về mỏ neo phát biểu được, dù là có neo hay không neo.

    Story 2.10 mất mỏ neo khi mẫu số chuyển sang bản ghi giả lập; story 2.11
    không lấy lại được vì cột `real` trích bằng một bộ trích xuất khác. Cột
    `that_khu` đóng đúng lỗ đó, và câu phải nêu cả điều **còn lại chưa khử
    được**: trục loại nội dung vẫn khác, và precision đo trên corpus dựng.
    """
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    assert (
        main([str(dich), "--anh-that-khu", str(_anh_that_khu(tmp_path)),
              "--anh-real", str(_anh_real(tmp_path))])
        == 0
    )
    trang = dich.read_text(encoding="utf-8")
    assert "Mỏ neo Composition-Risk" in trang
    assert "cùng bộ trích xuất" in trang
    assert "không cùng trục loại nội dung" in trang
    assert "chưa đo lần nào" in trang


def test_console_in_cung_khoi_doi_chung_khong_mang_the_html(tmp_path, capsys):
    """Console và trang dựng từ **một** hàm, cùng luật với story 2.11."""
    from eval.xem_ty_le import main

    assert (
        main([str(tmp_path / "x.html"), "--anh-real", str(_anh_real(tmp_path)),
              "--anh-that-khu", str(_anh_that_khu(tmp_path))])
        == 0
    )
    ra = capsys.readouterr().out
    assert "đối chứng real / that_khu" in ra
    assert "Mỏ neo Composition-Risk" in ra
    assert "<b>" not in ra, "dòng console không được mang thẻ HTML"


def test_dau_van_tay_do_giua_hai_cot_cung_tap_tai_lieu(hang):
    """`dau_van_tay_bo_trich_xuat` nhận mốc bất kỳ, nên nó đo được `real` với `that_khu`.

    Đây là chỗ story 2.13 khác story 2.11: cùng ba dấu, nhưng trên **cùng một
    tập tài liệu**, nên chúng không trộn được với chênh về hình dạng tri thức.
    """
    from eval.xem_ty_le import dau_van_tay_bo_trich_xuat

    nhieu_vai = ba_ty_le(
        _anh([_he("a", "noi_bo:runbook",
                  {"subject": ["x"], "cause": ["y"], "owner": ["o"]})]),
        hang,
    )
    it_vai = ba_ty_le(
        _anh([_he("b", "noi_bo:runbook", {"subject": ["x"], "cause": ["y"]})]), hang
    )
    dong = dau_van_tay_bo_trich_xuat(nhieu_vai, it_vai)
    assert any("owner" in d for d in dong), "vai bị điền thừa phải chỉ đúng `owner`"
    assert any("2 vai" in d for d in dong)


def test_hai_cot_cung_ba_ty_le_thi_khoi_doi_chung_in_chenh_0(hang, tmp_path):
    """Đối chứng phải in được cả ca "không chênh", không chỉ ca có chênh."""
    import json

    from eval.xem_ty_le import _khoi_doi_chung, dung_doi_chung

    goc = json.loads(_anh_real(tmp_path).read_text(encoding="utf-8"))
    nhu_nhau = dict(goc, space="that_khu")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(goc, ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(nhu_nhau, ensure_ascii=False), encoding="utf-8")
    anh = [doc_anh_do_thi(ANH_SYNTH), doc_anh_do_thi(a), doc_anh_do_thi(b)]
    cot = [ba_ty_le(x, hang) for x in anh]
    khoi = _khoi_doi_chung(dung_doi_chung(anh, cot, hang), cot[0])
    assert "chênh +0.0%" in khoi
    # Hai kho chứa đúng cùng tập tài liệu, nên khối phải nói ra điều đó thay vì
    # in một câu "bỏ ra 0 tài liệu" đọc như một phép hạn chế đã xảy ra.
    assert "đứng trên cùng một mẫu số" in khoi


def test_khoi_doi_chung_noi_ra_hai_mau_so_khac_nhau_o_dau(hang, tmp_path):
    """Khối phải in **cả hai** số tài liệu khi hai kho lệch nhau.

    Đây là finding nặng nhất của vòng review 05/09: câu "cùng 50 tài liệu" là
    phát biểu về *thư mục nguồn*, còn hai kho có 41 và 50. Trang không được để
    người đọc tự trừ, và càng không được khẳng định hai vế bằng nhau.
    """
    import json

    from eval.xem_ty_le import _khoi_doi_chung, dung_doi_chung

    r = json.loads(_anh_real(tmp_path).read_text(encoding="utf-8"))
    # `that_khu` có thêm một tài liệu thứ hai mà `real` không có.
    t = json.loads(_anh_that_khu(tmp_path).read_text(encoding="utf-8"))
    t["tai_lieu"].append(
        {"doc_key": "r2.md", "sha256": "1" * 64, "scope": "noi_bo",
         "content_type": "bao_cao_su_co"}
    )
    t["hyperedge"].append(
        {"id": "he-t2", "doc_key": ["r2.md"], "khoa": "noi_bo:bao_cao_su_co",
         "slots": {"subject": ["C"], "cause": ["D"], "time": ["T"]}}
    )
    t["so_tai_lieu"], t["so_hyperedge"] = 2, 2
    a, b = tmp_path / "r.json", tmp_path / "t.json"
    a.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")

    anh = [doc_anh_do_thi(ANH_SYNTH), doc_anh_do_thi(a), doc_anh_do_thi(b)]
    cot = [ba_ty_le(x, hang) for x in anh]
    dc = dung_doi_chung(anh, cot, hang)
    assert dc.so_tai_lieu_chung == 1
    assert dc.that_khu_day_du.so_hyperedge == 2, "bảng chính vẫn báo cáo cả hai"
    assert dc.that_khu.so_hyperedge == 1, "khối đối chứng chỉ tính tài liệu chung"

    khoi = _khoi_doi_chung(dc, cot[0])
    assert "Hai mẫu số, và chúng khác nhau" in khoi
    assert "bỏ ra 1" in khoi
    assert "trên 1 tài liệu có ở cả hai kho" in khoi


def test_precision_ghep_cap_cuc_bo_khop_vong_do():
    """`PRECISION_GHEP_CAP_CUC_BO` phải bằng precision của vòng đo cục bộ.

    Cùng luật với `test_precision_ghep_cap_khop_vong_chot`: trang giữ hằng thay
    vì chấm lại vòng đo, nên chỗ hai con số lệch nhau phải đỏ là đây. Câu mà
    hằng này thay thế - "precision đường Qwen chưa đo lần nào" của story 2.11 -
    là một phát biểu đi thẳng vào cách đọc cột `real`, nên nó không được phép
    trôi khỏi số đo mà không ai biết.
    """
    from eval.bo_vang import doc_bo_vang
    from eval.cham_trich_xuat import cham_bo, verdict_r2
    from eval.do_trich_xuat import THU_MUC_KET_QUA, doc_moi_vong
    from eval.xem_ty_le import (
        PRECISION_GHEP_CAP,
        PRECISION_GHEP_CAP_CUC_BO,
        VONG_CUC_BO_2_13,
    )

    vong = [v for v in doc_moi_vong(THU_MUC_KET_QUA) if v.vong == VONG_CUC_BO_2_13]
    assert len(vong) == 1, f"không tìm thấy vòng cục bộ {VONG_CUC_BO_2_13!r}"
    that = cham_bo(doc_bo_vang(), vong[0].facts_theo_tai_lieu()).chi_so.precision
    assert round(that, 3) == PRECISION_GHEP_CAP_CUC_BO, (
        f"precision ghép cặp của {VONG_CUC_BO_2_13} là {that:.6f}, còn"
        f" eval/xem_ty_le.py chép {PRECISION_GHEP_CAP_CUC_BO} - sửa hằng, đừng sửa test"
    )
    assert verdict_r2(PRECISION_GHEP_CAP_CUC_BO) != "ĐẠT", "48,2% dưới cổng 60%"
    assert PRECISION_GHEP_CAP_CUC_BO < PRECISION_GHEP_CAP


# ---------------------------------------------------------------------------
# Số khóa của space `that_khu` và phép đối chứng hai bộ trích xuất (story 2.13)
# ---------------------------------------------------------------------------


def test_so_khoa_cua_space_that_khu(hang):
    """Ba tỷ lệ của 50 tài liệu thật trích bằng DeepSeek, trên ảnh rút gọn đã commit."""
    kq = ba_ty_le(doc_anh_do_thi(ANH_THAT_KHU), hang)
    assert kq.space == "that_khu_rut_gon"
    assert kq.so_tai_lieu == THAT_KHU_TAI_LIEU
    assert kq.so_hyperedge == THAT_KHU_HYPEREDGE
    assert kq.overall_n_ary == TyLe("Overall N-ary", THAT_KHU_N_NGOI, THAT_KHU_HYPEREDGE)
    assert kq.sensitive_n_ary == TyLe(
        "Sensitive N-ary", THAT_KHU_NHAY_CAM_N_NGOI, THAT_KHU_NHAY_CAM
    )
    assert kq.composition_risk == TyLe(
        "Composition-Risk", THAT_KHU_COMPOSITION_RISK, THAT_KHU_NHAY_CAM
    )


def test_hai_anh_that_dung_cung_muoi():
    """`real` và `that_khu` phải băm bằng **cùng một muối**, nếu không hai cột không so được.

    Hai bản rút gọn dựng bằng hai muối khác nhau cho hai tập id rời nhau hoàn
    toàn: mọi phép so "cùng entity xuất hiện ở đâu" giữa hai cột sẽ im lặng trả
    lời "không chỗ nào". Đó là kiểu hỏng không đỏ, nên chỗ canh phải là đây.
    """
    import json as _json

    a = _json.loads(ANH_THAT_KHU.read_text(encoding="utf-8"))
    b = _json.loads(ANH_REAL.read_text(encoding="utf-8"))
    assert a["muoi_id"] == b["muoi_id"] == MUOI_ID_CHOT


def test_hai_anh_dung_chung_muoi_va_cung_tap_tai_lieu():
    """Tiền đề của cả phép đối chứng, kiểm **bằng máy** chứ không bằng `sha256sum` gõ tay.

    Story chỉ khóa `muoi_id` là chưa đủ: cùng muối mới chỉ nói hai file băm bằng
    một phép băm, chưa nói chúng chứa cùng tài liệu. Nhưng chính vì cùng muối,
    ba điều dưới đây kiểm được **ngay trong repo**, không cần ảnh đầy đủ và
    không cần kho đang chạy - `doc_key` đã băm của cùng một tên file là cùng một
    chuỗi, và `sha256` đã băm của cùng một thân tài liệu cũng vậy.

    Đó là "chỗ máy kiểm được" mà story nói tới; trước vòng review nó chỉ tồn tại
    dưới dạng một dòng `sha256sum` gõ tay trên máy chủ, tức một phép kiểm không
    ai chạy lại được.
    """
    real = doc_anh_do_thi(ANH_REAL)
    tk = doc_anh_do_thi(ANH_THAT_KHU)

    assert real.muoi_id == tk.muoi_id, "hai ảnh phải chụp bằng cùng một muối"
    assert real.doc_key < tk.doc_key, (
        "41 tài liệu của `real` phải là tập con **thật sự** của 50 tài liệu"
        " `that_khu`: hai kho nạp từ cùng một thư mục nguồn, Qwen làm rơi 9"
    )
    sha_tk = {t.doc_key: t.sha256 for t in tk.tai_lieu}
    nhan_tk = {t.doc_key: (t.scope, t.content_type) for t in tk.tai_lieu}
    for t in real.tai_lieu:
        assert t.sha256 == sha_tk[t.doc_key], (
            f"thân tài liệu {t.doc_key} khác nhau giữa hai kho: mất phép đối chứng"
        )
        assert (t.scope, t.content_type) == nhan_tk[t.doc_key]


def test_doi_chung_hai_bo_trich_xuat_tren_tap_tai_lieu_chung(hang):
    """Phép đo có đối chứng, tính trên **41 tài liệu có ở cả hai kho**.

    Đây là thứ story 2.11 không dựng được và là lý do story 2.13 tồn tại. Ba dấu
    vân tay của 2.11 đo `real` với `synth` - hai tập tài liệu *khác nhau*, nên
    chúng trộn hình dạng tri thức với chất lượng trích xuất.

    **Và hạn chế là bắt buộc, không phải một tinh chỉnh.** Thư mục nguồn đúng là
    cùng 50 file từng byte, nhưng kho `real` chỉ có 41 - so 41 với 50 là trộn
    thêm 9 tài liệu chỉ một vế có, vào đúng con số được gọi là "có đối chứng".
    Vòng review 05/09 bắt được điều đó khi chênh đang ghi là +32,2 / +28,4; số
    đúng là +35,7 / +29,4.
    """
    real_day_du = doc_anh_do_thi(ANH_REAL)
    tk_day_du = doc_anh_do_thi(ANH_THAT_KHU)
    chung = tai_lieu_chung(real_day_du, tk_day_du)
    assert len(chung) == THAT_KHU_CHUNG_TAI_LIEU

    real = ba_ty_le(han_che_theo_tai_lieu(real_day_du, chung), hang)
    tk = ba_ty_le(han_che_theo_tai_lieu(tk_day_du, chung), hang)
    assert tk.so_tai_lieu == THAT_KHU_CHUNG_TAI_LIEU
    assert tk.so_hyperedge == THAT_KHU_CHUNG_HYPEREDGE
    assert tk.overall_n_ary == TyLe(
        "Overall N-ary", THAT_KHU_CHUNG_N_NGOI, THAT_KHU_CHUNG_HYPEREDGE
    )
    assert tk.sensitive_n_ary == TyLe(
        "Sensitive N-ary", THAT_KHU_CHUNG_NHAY_CAM_N_NGOI, THAT_KHU_CHUNG_NHAY_CAM
    )
    assert tk.composition_risk == TyLe(
        "Composition-Risk", THAT_KHU_CHUNG_COMPOSITION_RISK, THAT_KHU_CHUNG_NHAY_CAM
    )
    # `real` đã là 41 tài liệu nên phép hạn chế không đổi gì ở vế đó - nhưng nó
    # phải được *chạy*, không được giả định: một lần nạp lại `real` là giả định
    # đó sai và không gì báo.
    assert real.so_hyperedge == REAL_HYPEREDGE

    # Qwen đẩy **mọi** hyperedge lên >= 3 vai; DeepSeek để 35,7% ở 2 vai.
    assert real.phan_hyperedge_hai_vai() == 0.0
    assert tk.phan_hyperedge_hai_vai() == pytest.approx(0.277, abs=5e-3)
    # Vai `owner` là dấu rõ nhất: 96,5% so với 5,9% trên **cùng** tài liệu, mà
    # 30/41 tài liệu là runbook không nêu người phụ trách.
    assert real.phan_bo_vai["owner"] / real.so_hyperedge == pytest.approx(0.965, abs=5e-3)
    assert tk.phan_bo_vai["owner"] / tk.so_hyperedge == pytest.approx(0.134, abs=5e-3)
    # Và `owner` phải là **vai lệch nhiều nhất** giữa hai cột, không phải một vai
    # tình cờ: đó mới là phát biểu "Qwen tự điền người phụ trách".
    assert real.vai_da_dien_nhieu_nhat(tk)[0] == "owner"
    # Chênh ba tỷ lệ, con số mà chương 4 trích.
    assert real.overall_n_ary.ti_le - tk.overall_n_ary.ti_le == pytest.approx(
        0.277, abs=5e-3
    )
    assert real.sensitive_n_ary.ti_le - tk.sensitive_n_ary.ti_le == pytest.approx(
        0.197, abs=5e-3
    )


def test_han_che_giu_hyperedge_khi_moi_doc_key_nam_trong_tap_giu(hang):
    """Luật giữ là "**mọi** `doc_key` trong tập giữ", không phải "có một".

    Một hyperedge hợp nhất từ một tài liệu được giữ và một tài liệu bị bỏ tồn
    tại *vì cả hai*, nên đếm nó là đếm một fact quy được một phần cho tài liệu
    ngoài tập so. Trên hai ảnh thật của story 2.13 hai luật cho cùng con số
    (không hyperedge nào đa nguồn), nên ca này phải dựng tay - nếu không lựa
    chọn nằm trong code mà không có gì chấm.
    """
    anh = _anh(
        [
            _he("chi-a", "noi_bo:runbook", {"subject": ["x"]}, doc_key=("a.md",)),
            _he("a-va-b", "noi_bo:runbook", {"subject": ["y"]}, doc_key=("a.md", "b.md")),
            _he("chi-b", "noi_bo:runbook", {"subject": ["z"]}, doc_key=("b.md",)),
        ],
        tai_lieu=(("a.md", "noi_bo", "runbook"), ("b.md", "noi_bo", "runbook")),
    )
    giu = han_che_theo_tai_lieu(anh, {"a.md"})
    assert [h.id for h in giu.hyperedge] == ["chi-a"]
    assert giu.so_tai_lieu == 1
    assert giu.so_hyperedge == 1


def test_han_che_ve_tap_rong_la_loi_co_ma_khong_phai_anh_rong():
    """Hai ảnh chụp bằng **hai muối khác nhau** cho phép giao rỗng.

    Trả một ảnh rỗng thì ba tỷ lệ ra `None` và khối đối chứng in ba dòng "không
    so được" - đọc như một kết quả chứ không như một lỗi cấu hình.
    """
    anh = _anh([_he("a", "noi_bo:runbook", {"subject": ["x"]})])
    with pytest.raises(KhongCoTaiLieuChung) as loi:
        han_che_theo_tai_lieu(anh, {"khong-co-file-nay.md"})
    assert loi.value.code == "KHONG_CO_TAI_LIEU_CHUNG"


def test_tai_lieu_chung_la_phep_giao_cua_moi_anh(hang):
    a = _anh(
        [_he("a", "noi_bo:runbook", {"subject": ["x"]}, doc_key=("a.md",))],
        tai_lieu=(("a.md", "noi_bo", "runbook"), ("b.md", "noi_bo", "runbook")),
    )
    b = _anh(
        [_he("b", "noi_bo:runbook", {"subject": ["x"]}, doc_key=("b.md",))],
        tai_lieu=(("b.md", "noi_bo", "runbook"), ("c.md", "noi_bo", "runbook")),
    )
    assert tai_lieu_chung(a, b) == frozenset({"b.md"})
    assert tai_lieu_chung(a) == frozenset({"a.md", "b.md"})


def test_chan_doan_composition_risk_cua_that_khu(hang):
    """Composition-Risk 0 trên `that_khu` là 0 **vì thiếu chồng lấn entity**, không vì kín.

    Con số quan trọng không phải số 0 mà là 6/225: chỉ 6 trong 225 ca nhạy cảm
    có *một* entity còn lộ ở vùng không nhạy cảm. Trên `synth` là 26/81 và trên
    `khao_sat` là 40/151. Hai tài liệu thật hiếm khi sinh chung một id entity vì
    chuẩn hóa thực thể chưa làm (story 2.12), nên mỏ neo này còn bị chặn trên bởi
    chính lỗ đó - phải phát biểu ra, đừng đọc số 0 thành "tri thức doanh nghiệp kín".
    """
    kq = ba_ty_le(doc_anh_do_thi(ANH_THAT_KHU), hang)
    assert kq.composition_risk.tu_so == 0
    assert kq.so_nhay_cam_co_entity_lo == 6
    assert kq.so_nhay_cam_lo_mot_phan == 6
    assert kq.trung_binh_phan_entity_lo == pytest.approx(0.311, abs=5e-3)


def test_hai_anh_khac_muoi_thi_tu_choi_ca_dot(tmp_path, capsys):
    """Hai ảnh rút gọn chụp bằng **hai muối khác nhau** là từ chối, không phải in tiếp.

    Đây là ca im lặng theo cách tệ nhất: hai muối cho hai tập id **rời nhau hoàn
    toàn** dù thư mục nguồn là một, nên phép giao `doc_key` ra rỗng và mọi câu
    hỏi dạng "entity này còn xuất hiện ở đâu" trả lời "không chỗ nào" - đúng
    hình dạng của một kết quả, không của một lỗi.
    """
    import json

    from eval.anh_rut_gon import rut_gon_anh
    from eval.xem_ty_le import main

    def rut(nguon: Path, muoi: str, ten: str) -> Path:
        d = tmp_path / ten
        d.write_text(
            json.dumps(
                rut_gon_anh(json.loads(nguon.read_text(encoding="utf-8")), muoi),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return d

    a = rut(_anh_real(tmp_path), "muoi-mot-du-dai-0123456789abcdef", "real_rut_gon.json")
    b = rut(
        _anh_that_khu(tmp_path),
        "muoi-hai-khac-han-0123456789abcdef",
        "that_khu_rut_gon.json",
    )
    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--anh-real", str(a), "--anh-that-khu", str(b)]) == 1
    err = capsys.readouterr().err
    assert "hai muối khác nhau" in err and "--muoi" in err
    assert not dich.exists()


def test_cung_muoi_thi_cap_anh_di_qua_rao(tmp_path):
    """Nửa còn lại của rào: cùng muối thì không chặn gì."""
    import json

    from eval.anh_rut_gon import rut_gon_anh
    from eval.xem_ty_le import ly_do_tu_choi_cap_muoi

    muoi = "mot-muoi-duy-nhat-0123456789abcdef"
    goi = []
    for nguon, ten in ((_anh_real(tmp_path), "real_rut_gon.json"),
                       (_anh_that_khu(tmp_path), "that_khu_rut_gon.json")):
        d = tmp_path / ten
        d.write_text(
            json.dumps(
                rut_gon_anh(json.loads(nguon.read_text(encoding="utf-8")), muoi),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        goi.append(doc_anh_do_thi(d))
    assert ly_do_tu_choi_cap_muoi(*goi) is None
    # Ảnh **đầy đủ** không khai muối; cặp đó không bị rào này chạm tới.
    assert ly_do_tu_choi_cap_muoi(
        doc_anh_do_thi(_anh_real(tmp_path)), goi[1]
    ) is None


def test_canh_bao_qwen_chi_vao_cot_real_khong_vao_cot_that_khu(tmp_path, capsys):
    """Hai bộ lọc `space_goc(...) == SPACE_REAL` nằm cách nhau ~350 dòng.

    Chúng trôi khỏi nhau được, và mọi assert dạng "có chứa chuỗi" vẫn xanh khi
    một lần gán nhầm cột dán nhãn Qwen lên `that_khu` - cột trích bằng DeepSeek.
    Nên test này đếm số lần xuất hiện và chấm cả vế phủ định.
    """
    from eval.xem_ty_le import main

    assert (
        main([str(tmp_path / "x.html"), "--anh-real", str(_anh_real(tmp_path)),
              "--anh-that-khu", str(_anh_that_khu(tmp_path))])
        == 0
    )
    ra = capsys.readouterr().out
    assert ra.count("KHÔNG khôi phục được mỏ neo Composition-Risk") == 1
    assert "cột real KHÔNG khôi phục" in ra
    assert "cột that_khu KHÔNG khôi phục" not in ra
    assert ra.count("trích bằng Qwen 2.5 7B cục bộ") == 1
    assert "cột that_khu trích bằng Qwen" not in ra


# ---------------------------------------------------------------------------
# Dải sai số của ba tỷ lệ trên nhiều lần chạy cùng một cấu hình (story 2.12)
# ---------------------------------------------------------------------------

# Ba mẫu của **cùng một cấu hình** `that_khu`: cùng 50 tài liệu đã khử, cùng
# `deepseek-v4-flash`, cùng prompt, không từ điển - khác đúng **lần chạy**. Mẫu 2
# là bản đang được báo cáo (`that_khu_rut_gon.json`); hai mẫu kia chỉ tồn tại để
# đo dải, và chúng có commit vì "người đọc repo tính lại được" là điều kiện mà
# ADR-012 đặt cho mọi con số của chương 4.
# Muối chốt của mọi ảnh rút gọn dựng từ tài liệu công ty. Cùng muối là điều
# kiện để hai ảnh so được với nhau: hai muối cho hai tập id rời nhau hoàn toàn.
MUOI_ID_CHOT = "dffc42de62eed6e1"
ANH_THAT_KHU_LAN1 = GOC_REPO / "eval" / "anh_do_thi" / "that_khu_lan1_rut_gon.json"
ANH_THAT_KHU_LAN3 = GOC_REPO / "eval" / "anh_do_thi" / "that_khu_lan3_rut_gon.json"
# Mẫu thứ hai của **cột mốc**: cùng `eval/corpus` + `eval/data`, cùng model,
# **có** từ điển thực thể (space dùng một lần được cấp một bản chép của
# `config/tu-dien-thuc-the/synth.yaml` với cùng sha256, xóa ngay sau khi nạp).
ANH_SYNTH_LAN2 = GOC_REPO / "eval" / "anh_do_thi" / "synth_lan2_rut_gon.json"

# Dải đo được ngày 05/09/2026 trên ba mẫu `that_khu`, viết tay theo cùng luật số
# khóa của story 2.10: một kỳ vọng tính bằng chính hàm đang đo là một test luôn
# xanh. Ba lần chạy cho 720, 712, 716 hyperedge.
THAT_KHU_DAI_OVERALL = (0.678, 0.750)
THAT_KHU_DAI_SENSITIVE = (0.716, 0.810)

# Dải của **cột mốc** trên hai mẫu. Đây là con số ngược với dự đoán và là phát
# hiện chính của phép đo: biên độ **phụ thuộc corpus rất mạnh**. Corpus dựng 52
# tài liệu ngắn cho biên độ khoảng một điểm; 50 tài liệu công ty thật cho bảy
# tới mười. Một "biên độ chung ±7 điểm" là một phát biểu sai theo cả hai chiều.
SYNTH_DAI_OVERALL = (0.897, 0.907)
SYNTH_DAI_SENSITIVE = (0.831, 0.839)


def test_dai_can_it_nhat_hai_mau(hang):
    """Một mẫu cho biên độ 0, và "biên độ 0,0 điểm" đọc y như một kết quả tốt."""
    b = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    with pytest.raises(ThieuMauDoDai) as e:
        dai_ba_ty_le("synth", b)
    assert e.value.code == "THIEU_MAU_DO_DAI"


def test_dai_tu_choi_khi_mot_mau_co_mau_so_rong(hang):
    """"Không tính được" không có chỗ trong một phép lấy min và max."""
    rong = ba_ty_le(_anh([_he("a", "noi_bo:runbook", {"subject": ["x"]})]), hang)
    day = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    with pytest.raises(ThieuMauDoDai, match="mẫu số rỗng"):
        dai_ba_ty_le("thu", rong, day)


def test_dai_tinh_dung_min_max_bien_do_trung_binh():
    """Bốn số dẫn xuất tính từ chính danh sách giá trị, không từ một hằng."""
    from eval.ty_le_n_ngoi import DaiTyLe

    d = DaiTyLe(ten="x", ten_cau_hinh="c", gia_tri=(0.60, 0.75, 0.70), mau_so=(1, 1, 1))
    assert (d.so_mau, d.nho_nhat, d.lon_nhat) == (3, 0.60, 0.75)
    assert d.bien_do == pytest.approx(0.15)
    assert d.trung_binh == pytest.approx(0.6833, abs=5e-4)
    # Một chênh nhỏ hơn biên độ của chính phép đo không đọc thành kết luận được.
    assert d.nho_hon_bien_do(0.05) is True
    assert d.nho_hon_bien_do(-0.05) is True
    assert d.nho_hon_bien_do(0.20) is False
    assert d.nho_hon_bien_do(None) is True


def test_dai_ba_mau_cua_that_khu_tren_anh_da_commit(hang):
    """**Số trụ mới của chương 4**: ba tỷ lệ có biên độ, và biên độ đó lớn.

    Ba mẫu là ba lần nạp cùng 50 tài liệu, cùng model, cùng prompt, không từ
    điển - khác đúng lần chạy. Token vào của cả ba **bằng nhau tới từng token**
    (120.848; nó là số đếm trên chuỗi prompt), nên thứ đổi là đầu ra của LLM,
    tức chính tập fact mà ba tỷ lệ đếm trên.

    Biên độ 7,2 và 9,5 điểm phần trăm **lớn hơn** phần lớn chênh lệch mà epic 2
    từng đọc thành kết luận - chênh "khớp cỡ" của story 2.10 là 9,6 và 5,7 điểm,
    và chênh của cổng R2 ở 2.12 là 0,3 điểm. Đó là lý do test này tồn tại: nó là
    chỗ con số ấy có một địa chỉ, thay vì một câu văn xuôi ai cũng gật đầu rồi
    vẫn trích số.
    """
    mau = [
        ba_ty_le(doc_anh_do_thi(f), hang)
        for f in (ANH_THAT_KHU_LAN1, ANH_THAT_KHU, ANH_THAT_KHU_LAN3)
    ]
    assert [b.so_hyperedge for b in mau] == [720, 712, 716]
    # Cả ba cùng 50 tài liệu và cùng muối: nếu không thì đây là ba tập khác nhau.
    assert {b.so_tai_lieu for b in mau} == {THAT_KHU_TAI_LIEU}
    assert {doc_anh_do_thi(f).muoi_id for f in (ANH_THAT_KHU_LAN1, ANH_THAT_KHU, ANH_THAT_KHU_LAN3)} == {
        MUOI_ID_CHOT
    }

    ov, se, cr = dai_ba_ty_le("that_khu", *mau)
    assert (round(ov.nho_nhat, 3), round(ov.lon_nhat, 3)) == THAT_KHU_DAI_OVERALL
    assert (round(se.nho_nhat, 3), round(se.lon_nhat, 3)) == THAT_KHU_DAI_SENSITIVE
    assert ov.bien_do == pytest.approx(0.072, abs=5e-4)
    assert se.bien_do == pytest.approx(0.095, abs=5e-4)
    # Composition-Risk bằng 0 ở cả ba lần: **đó** là một phát biểu ổn định, khác
    # hẳn hai tỷ lệ đầu. Số 0 không phải nhiễu của một lần chạy.
    assert cr.bien_do == 0.0 and cr.lon_nhat == 0.0

    # Bản đang báo cáo là mẫu 2, và nó **không** đổi: dải là một phát biểu thêm
    # về sai số, không phải một phép thay số.
    assert mau[1].overall_n_ary == TyLe("Overall N-ary", THAT_KHU_N_NGOI, THAT_KHU_HYPEREDGE)


def test_hai_chenh_lech_ma_epic_2_tung_phat_bieu_so_voi_bien_do(hang):
    """Ba phép so, và kết quả **không giống nhau** - đó mới là điều đáng khóa.

    Một test khẳng định "cả ba chênh lệch đều nằm trong biên độ" sẽ tiện hơn cho
    câu chuyện và sai. Số thật:

    - Chênh **Sensitive N-ary** giữa `synth` và `khao_sat` (+6,1 điểm) **nhỏ hơn**
      biên độ 9,5 điểm: nó không đọc thành một phát biểu định lượng được.
    - Chênh **Overall N-ary** (-8,4 điểm) **lớn hơn** biên độ 7,2 điểm, nhưng chỉ
      hơn 1,2 điểm. Nó ở ngay mép, nên nó cũng không chịu nổi một chữ số thập
      phân nào của báo cáo.
    - Chênh của cổng R2 giữa hai prompt (0,3 điểm trên 8 tài liệu chấm) nhỏ hơn
      **cả hai** biên độ, và nhỏ hơn rất xa.
    """
    mau = [
        ba_ty_le(doc_anh_do_thi(f), hang)
        for f in (ANH_THAT_KHU_LAN1, ANH_THAT_KHU, ANH_THAT_KHU_LAN3)
    ]
    ov, se, _ = dai_ba_ty_le("that_khu", *mau)
    synth = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    khao_sat = ba_ty_le(doc_anh_do_thi(ANH_KHAO_SAT), hang)
    dong = doi_chieu(synth, khao_sat)

    assert se.nho_hon_bien_do(dong[1].chenh), "chênh Sensitive phải nhỏ hơn biên độ"
    assert not ov.nho_hon_bien_do(dong[0].chenh), "chênh Overall lớn hơn biên độ"
    # Nhưng chỉ hơn chút: khoảng cách tới biên độ dưới 2 điểm phần trăm.
    assert abs(dong[0].chenh) - ov.bien_do == pytest.approx(0.012, abs=5e-3)

    from eval.xem_ty_le import PRECISION_GHEP_CAP, PRECISION_GHEP_CAP_TU_DIEN

    chenh_r2 = PRECISION_GHEP_CAP_TU_DIEN - PRECISION_GHEP_CAP
    assert ov.nho_hon_bien_do(chenh_r2) and se.nho_hon_bien_do(chenh_r2)


def test_dai_hai_mau_cua_cot_moc(hang):
    """Cột mốc cũng phải có dải - nó là cột mà mọi chênh lệch đo so với.

    `synth_lan2` là một **space dùng một lần**: cùng `eval/corpus` + `eval/data`,
    cùng model, **có** từ điển (space đó được cấp một bản chép của
    `config/tu-dien-thuc-the/synth.yaml` với cùng sha256, xóa ngay sau khi nạp),
    khác đúng lần chạy. Space `synth` **không** bị nạp lại: nạp lại nó là làm
    trôi 28 nhãn truy hồi vừa soát tay.
    """
    moc = ba_ty_le(doc_anh_do_thi(ANH_SYNTH), hang)
    lan2 = ba_ty_le(doc_anh_do_thi(ANH_SYNTH_LAN2), hang)
    assert (moc.so_hyperedge, lan2.so_hyperedge) == (281, 268)
    assert moc.so_tai_lieu == lan2.so_tai_lieu == 52

    ov, se, cr = dai_ba_ty_le("synth", moc, lan2)
    assert (round(ov.nho_nhat, 3), round(ov.lon_nhat, 3)) == SYNTH_DAI_OVERALL
    assert (round(se.nho_nhat, 3), round(se.lon_nhat, 3)) == SYNTH_DAI_SENSITIVE
    assert ov.bien_do == pytest.approx(0.010, abs=5e-4)
    assert se.bien_do == pytest.approx(0.007, abs=5e-4)
    assert cr.bien_do == 0.0


def test_bien_do_phu_thuoc_corpus_chu_khong_phai_mot_hang_chung(hang):
    """**Phát hiện chính của phép đo dải**, và nó ngược với dự đoán ban đầu.

    Biên độ của corpus dựng nhỏ hơn biên độ của tài liệu công ty thật **gần bảy
    lần**. Một câu "ba tỷ lệ có biên độ khoảng bảy điểm" vì vậy sai theo cả hai
    chiều: nó thổi phồng nhiễu của cột mốc, và nó dùng nhiễu của cột ồn nhất để
    hạ những chênh lệch thật sự đọc được ở hai cột sạch.

    Hệ quả cho `eval/xem_ty_le.py`: biên độ phải tra **theo cấu hình**, không lấy
    max chung - đó đúng là điều `_cau_ha_xuong_dinh_tinh` làm.
    """
    moc = [ba_ty_le(doc_anh_do_thi(f), hang) for f in (ANH_SYNTH, ANH_SYNTH_LAN2)]
    tk = [
        ba_ty_le(doc_anh_do_thi(f), hang)
        for f in (ANH_THAT_KHU_LAN1, ANH_THAT_KHU, ANH_THAT_KHU_LAN3)
    ]
    ov_moc = dai_ba_ty_le("synth", *moc)[0]
    ov_tk = dai_ba_ty_le("that_khu", *tk)[0]
    assert ov_tk.bien_do > 5 * ov_moc.bien_do, (ov_moc.bien_do, ov_tk.bien_do)


def test_trang_in_dai_va_tu_ha_chenh_lech_nho_hon_bien_do(tmp_path):
    """AC: dải in **ngay cạnh** ba tỷ lệ, và trang tự hạ hàng nào cần hạ."""
    from eval.xem_ty_le import main

    dich = tmp_path / "ty_le.html"
    ma = main(
        [
            str(dich),
            "--anh-that-khu",
            str(ANH_THAT_KHU),
            "--mau-moc",
            str(ANH_SYNTH_LAN2),
            "--mau-that-khu",
            str(ANH_THAT_KHU_LAN1),
            "--mau-that-khu",
            str(ANH_THAT_KHU_LAN3),
        ]
    )
    assert ma == 0
    trang = dich.read_text(encoding="utf-8")
    assert "số của MỘT lần chạy" in trang
    assert "biên độ 7.2 điểm" in trang and "biên độ 1.0 điểm" in trang
    assert "3 lần chạy" in trang and "2 lần chạy" in trang
    # Chênh Sensitive giữa mốc và that_khu (-2,8 điểm) nhỏ hơn biên độ 9,5 điểm.
    assert "chỉ đọc được ở mức định tính" in trang
    # Cột chưa có mẫu lặp phải được nói ra, không im lặng mượn biên độ của mốc.
    assert "Chưa có mẫu lặp cho" in trang and "khao_sat" in trang
    # Câu về cổng R2 phải có mặt: 0,3 điểm nhỏ hơn mọi biên độ đo được.
    assert "0,3 điểm" in trang


def test_mau_phai_la_mot_lan_chay_khac_cua_cung_cau_hinh(tmp_path, capsys):
    """Trộn một space khác vào phép đo dải là đo trên hai tập dữ liệu."""
    from eval.xem_ty_le import main, ly_do_tu_choi_mau

    anh = doc_anh_do_thi(ANH_KHAO_SAT)
    assert ly_do_tu_choi_mau(ANH_KHAO_SAT, "synth", anh) is not None
    assert ly_do_tu_choi_mau(ANH_SYNTH_LAN2, "synth", doc_anh_do_thi(ANH_SYNTH_LAN2)) is None
    assert ly_do_tu_choi_mau(ANH_SYNTH, "synth", doc_anh_do_thi(ANH_SYNTH)) is None

    dich = tmp_path / "ty_le.html"
    assert main([str(dich), "--mau-moc", str(ANH_KHAO_SAT)]) == 1
    assert "không phải một lần chạy khác" in capsys.readouterr().err
    assert not dich.exists()
