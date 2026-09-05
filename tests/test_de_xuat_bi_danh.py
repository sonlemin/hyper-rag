"""Công cụ đề xuất bí danh: gom ứng viên, ràng scope và cửa chặn `config/` (story 2.12).

Bước người xác nhận là **một cửa, không phải một lời hứa**. Hai khẳng định phải
có test chứ không chỉ có docstring: công cụ không ghi được vào `config/`, và file
nó ghi ra **không nạp được** bằng loader từ điển đang chạy. Phần còn lại là ba
luật gom ứng viên và luật ràng scope.

Không test nào gọi LLM: bước hỏi LLM là tùy chọn và các test ở đây chạy nhánh
tất định.
"""

import pytest
import yaml

from adapters.tu_dien_thuc_the import TuDienThucTheInvalid, tai_tu_dien_thuc_the
from eval.cau_hoi import AnhDoThi, HyperedgeAnh, TaiLieuAnh
from eval.de_xuat_bi_danh import (
    LY_DO_DAU_NOI,
    LY_DO_HOA_THUONG,
    LY_DO_TEN_MIEN,
    THU_MUC_DE_XUAT,
    DeXuatKhongGhiDuoc,
    bo_dau_ten_may,
    doc_nhan_xet,
    dung_de_xuat,
    dung_prompt_de_xuat,
    ghi_de_xuat,
    khoa_gom,
    ly_do_cua_nhom,
    ly_do_tu_choi_dich,
    nhom_lien_scope,
    ung_vien_bi_danh,
)


def _he(id_he, khoa, slots, doc_key=("a.md",)):
    return HyperedgeAnh(
        id=id_he,
        doc_key=tuple(doc_key),
        khoa=khoa,
        slots={vai: tuple(gt) for vai, gt in slots.items()},
    )


def _anh(hyperedge, tai_lieu=(("a.md", "noi_bo", "runbook"),), space="synth"):
    return AnhDoThi(
        version=2,
        space=space,
        ngay_do="2026-09-05T00:00:00+00:00",
        policy_version="x" * 8,
        tai_lieu=tuple(
            TaiLieuAnh(doc_key=d, sha256="0" * 64, scope=s, content_type=c)
            for d, s, c in tai_lieu
        ),
        hyperedge=tuple(hyperedge),
    )


# ---------------------------------------------------------------------------
# Ba luật gom
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Phòng IT", "phòng IT"),
        ("App01", "app01.company.vn"),
        ("app01", "APP-01"),
        ("app 01", "app_01"),
        ("App01", "app-01.company.vn"),
    ],
)
def test_ba_luat_gom_ve_cung_mot_khoa(a, b):
    assert khoa_gom(a) == khoa_gom(b), (a, b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("App01", "App02"),
        ("phòng 3.2", "phòng 3"),
        ("v1.4", "v1"),
    ],
)
def test_hai_thuc_the_khac_nhau_khong_gom_chung(a, b):
    assert khoa_gom(a) != khoa_gom(b), (a, b)


def test_bo_dau_ten_may_chi_cham_chuoi_dang_ten_may():
    assert bo_dau_ten_may("app01.company.vn") == "app01"
    # "phòng 3.2" có khoảng trắng và chữ tiếng Việt: không phải tên máy.
    assert bo_dau_ten_may("phòng 3.2") == "phòng 3.2"


def test_ly_do_chi_neu_buoc_that_su_can():
    """Một nhóm chỉ khác hoa/thường mang đúng một lý do.

    Bản đầu tiên so ba luật trên chuỗi thô nên mọi nhóm nhận đủ ba nhãn, và
    trường `ly_do` thành một trường không mang tin.
    """
    assert ly_do_cua_nhom(["Phòng IT", "phòng IT"]) == (LY_DO_HOA_THUONG,)
    assert ly_do_cua_nhom(["App01", "app01.company.vn"]) == (
        LY_DO_HOA_THUONG,
        LY_DO_TEN_MIEN,
    )
    assert ly_do_cua_nhom(["app01", "APP-01"]) == (LY_DO_HOA_THUONG, LY_DO_DAU_NOI)


# ---------------------------------------------------------------------------
# Ràng theo scope
# ---------------------------------------------------------------------------


def test_ung_vien_gom_trong_mot_scope():
    anh = _anh(
        [
            _he("h1", "khach_hang_a:runbook", {"subject": ["App01"]}),
            _he("h2", "khach_hang_a:runbook", {"subject": ["app01.company.vn"]}),
        ]
    )
    (nhom,) = ung_vien_bi_danh(anh)
    assert nhom.scope == "khach_hang_a"
    assert nhom.chuan in {"App01", "app01.company.vn"}
    assert set(nhom.bi_danh) | {nhom.chuan} == {"App01", "app01.company.vn"}


def test_khong_bao_gio_de_xuat_gop_hai_scope():
    """`web01` của khách A và `web01` của khách B không thành một nhóm.

    Đây là luật mà cả story dựng ra để giữ: gộp hai khoang thuê bao là hỏng đúng
    chỗ tỷ lệ Composition-Risk đo.
    """
    anh = _anh(
        [
            _he("h1", "khach_hang_a:runbook", {"subject": ["web01"]}),
            _he("h2", "khach_hang_b:runbook", {"subject": ["WEB01"]}),
        ]
    )
    assert ung_vien_bi_danh(anh) == ()
    # Nhưng nó không im lặng: cặp đó hiện ra ở danh sách "liên scope".
    assert nhom_lien_scope(anh) == (("WEB01", "web01"),)


def test_khong_muc_nao_mang_scope_chung():
    """Công cụ không tự nâng lên `*`; đó là quyết định của người xác nhận."""
    anh = _anh(
        [
            _he("h1", "khach_hang_a:runbook", {"subject": ["App01"]}),
            _he("h2", "khach_hang_a:runbook", {"subject": ["app01"]}),
            _he("h3", "khach_hang_b:runbook", {"subject": ["App01"]}),
            _he("h4", "khach_hang_b:runbook", {"subject": ["app01"]}),
        ]
    )
    nhom = ung_vien_bi_danh(anh)
    assert {n.scope for n in nhom} == {"khach_hang_a", "khach_hang_b"}
    assert all(n.scope != "*" for n in nhom)
    # Nhưng có ghi chú để người xác nhận biết hai scope cùng có nhóm này.
    assert all(n.cung_nhom_o_scope for n in nhom)


def test_hyperedge_khong_khoa_dem_vao_moi_scope_sinh_ra_no():
    """Ca AD-5, cùng hình dạng với `eval.ty_le_n_ngoi.scope_cua_hyperedge`."""
    anh = _anh(
        [
            _he("h1", None, {"subject": ["App01"]}, doc_key=("a.md", "b.md")),
            _he("h2", "khach_hang_b:runbook", {"subject": ["app01"]}, doc_key=("b.md",)),
        ],
        tai_lieu=(
            ("a.md", "khach_hang_a", "runbook"),
            ("b.md", "khach_hang_b", "runbook"),
        ),
    )
    nhom = ung_vien_bi_danh(anh)
    assert [n.scope for n in nhom] == ["khach_hang_b"]


def test_chuan_de_xuat_la_bien_the_hay_gap_nhat():
    anh = _anh(
        [
            _he("h1", "noi_bo:runbook", {"subject": ["phòng IT"], "owner": ["phòng IT"]}),
            _he("h2", "noi_bo:runbook", {"subject": ["Phòng IT"]}),
        ]
    )
    (nhom,) = ung_vien_bi_danh(anh)
    assert nhom.chuan == "phòng IT"
    assert nhom.bi_danh == ("Phòng IT",)
    assert nhom.so_lan == {"Phòng IT": 1, "phòng IT": 2}


def test_gia_tri_dai_khong_thanh_ung_vien():
    """Vai mệnh đề nằm ngoài phép gom: gộp bí danh trên mệnh đề là viết lại câu."""
    dai_a = "khởi động lại pool php-fpm rồi kiểm tra lại log của App01 ngay sau đó"
    dai_b = dai_a.upper()
    anh = _anh(
        [
            _he("h1", "noi_bo:runbook", {"subject": ["x"], "remediation": [dai_a]}),
            _he("h2", "noi_bo:runbook", {"subject": ["y"], "remediation": [dai_b]}),
        ]
    )
    assert ung_vien_bi_danh(anh) == ()


def test_ham_thuan_cung_dau_vao_cung_dau_ra():
    anh = _anh(
        [
            _he("h1", "noi_bo:runbook", {"subject": ["App01"]}),
            _he("h2", "noi_bo:runbook", {"subject": ["app01"]}),
        ]
    )
    assert ung_vien_bi_danh(anh) == ung_vien_bi_danh(anh)


# ---------------------------------------------------------------------------
# Cửa: không ghi vào `config/`, và file ghi ra không nạp được thành từ điển
# ---------------------------------------------------------------------------


def test_tu_choi_ghi_vao_config(tmp_path):
    """Cửa chặn phải chặn **cả** đường ghi đè lên từ điển đang chạy.

    Hai đích, hai ca khác nhau: một file chưa tồn tại trong `config/` (nếu ghi
    được thì lần sau nó thành một bảng gộp thực thể không ai xác nhận), và chính
    `config/tu-dien-thuc-the/synth.yaml` đang chạy (nếu ghi được thì một lần gõ
    nhầm `--dich` thay cả bảng bằng một đề xuất).
    """
    goc_config = THU_MUC_DE_XUAT.parent.parent / "config" / "tu-dien-thuc-the"
    chua_co = goc_config / "khong-bao-gio-ton-tai.yaml"
    assert ly_do_tu_choi_dich(chua_co) is not None
    with pytest.raises(DeXuatKhongGhiDuoc) as e:
        ghi_de_xuat(chua_co, {"version": 1})
    assert e.value.code == "DE_XUAT_KHONG_GHI_DUOC"
    assert not chua_co.exists()

    dang_chay = goc_config / "synth.yaml"
    truoc = dang_chay.read_bytes() if dang_chay.exists() else None
    with pytest.raises(DeXuatKhongGhiDuoc):
        ghi_de_xuat(dang_chay, {"version": 1}, ghi_de=True)
    if truoc is not None:
        assert dang_chay.read_bytes() == truoc


def test_ghi_vao_thu_muc_de_xuat_thi_duoc(tmp_path):
    dich = tmp_path / "synth.yaml"
    assert ly_do_tu_choi_dich(dich) is None
    ra = ghi_de_xuat(dich, {"version": 1, "de_xuat": []})
    assert ra.exists()
    with pytest.raises(DeXuatKhongGhiDuoc, match="đã có"):
        ghi_de_xuat(dich, {"version": 1, "de_xuat": []})
    ghi_de_xuat(dich, {"version": 1, "de_xuat": []}, ghi_de=True)
    assert (tmp_path / "synth.yaml.bak.yaml").exists()


def test_file_de_xuat_khong_nap_duoc_bang_loader_tu_dien(tmp_path):
    """Một `cp` thẳng vào `config/` phải là loader nổ, không phải một bảng lặng lẽ chạy.

    Lược đồ khác nhau là *cơ chế* của điều đó, không phải một quy ước: khóa gốc
    là `de_xuat` chứ không `muc`, nên loader từ chối ngay ở cấp gốc.
    """
    anh = _anh(
        [
            _he("h1", "noi_bo:runbook", {"subject": ["App01"]}),
            _he("h2", "noi_bo:runbook", {"subject": ["app01"]}),
        ]
    )
    nhom = ung_vien_bi_danh(anh)
    dich = ghi_de_xuat(
        tmp_path / "synth.yaml", dung_de_xuat(anh, nhom, anh_chup="x.json")
    )
    with pytest.raises(TuDienThucTheInvalid):
        tai_tu_dien_thuc_the(dich)


def test_khong_muc_nao_mang_xac_nhan(tmp_path):
    """Không có đường nào để một đề xuất tự mang dấu xác nhận."""
    anh = _anh(
        [
            _he("h1", "noi_bo:runbook", {"subject": ["App01"]}),
            _he("h2", "noi_bo:runbook", {"subject": ["app01"]}),
        ]
    )
    du_lieu = dung_de_xuat(anh, ung_vien_bi_danh(anh), anh_chup="x.json")
    assert du_lieu["de_xuat"]
    for m in du_lieu["de_xuat"]:
        assert "xac_nhan" not in m


def test_file_de_xuat_da_commit_cua_synth_van_dung_hinh_dang():
    """`eval/de_xuat/synth.yaml` là file có commit: giữ nó đúng lược đồ và không
    mang đường dẫn tuyệt đối của máy ai."""
    duong_dan = THU_MUC_DE_XUAT / "synth.yaml"
    if not duong_dan.exists():
        pytest.skip("chưa sinh file đề xuất của synth")
    du_lieu = yaml.safe_load(duong_dan.read_text(encoding="utf-8"))
    assert du_lieu["space"] == "synth"
    assert not du_lieu["anh_chup"].startswith("/")
    assert du_lieu["so_nhom"] == len(du_lieu["de_xuat"])
    with pytest.raises(TuDienThucTheInvalid):
        tai_tu_dien_thuc_the(duong_dan)


# ---------------------------------------------------------------------------
# Bước LLM: hỏi được, và phản hồi hỏng không làm mất phần tất định
# ---------------------------------------------------------------------------


def test_prompt_de_xuat_liet_ke_du_nhom():
    anh = _anh(
        [
            _he("h1", "noi_bo:runbook", {"subject": ["App01"]}),
            _he("h2", "noi_bo:runbook", {"subject": ["app01"]}),
        ]
    )
    prompt = dung_prompt_de_xuat(ung_vien_bi_danh(anh))
    assert "App01" in prompt and "app01" in prompt and "json" in prompt.lower()
    assert "<<NHOM>>" not in prompt


def test_phan_hoi_llm_hong_khong_lam_mat_phan_tat_dinh():
    assert doc_nhan_xet("không phải json", 3) == {}
    assert doc_nhan_xet('{"nhan_xet": "x"}', 3) == {}
    # `stt` ngoài khoảng bị bỏ, không nổ và không lệch chỉ số.
    assert doc_nhan_xet('{"nhan_xet": [{"stt": 99, "cung_mot_thuc_the": true}]}', 3) == {}


def test_doc_nhan_xet_doi_stt_ve_chi_so_0():
    ra = doc_nhan_xet(
        '{"nhan_xet": [{"stt": 1, "cung_mot_thuc_the": true, "ly_do": "cùng máy"}]}', 2
    )
    assert ra == {0: {"cung_mot_thuc_the": True, "ly_do": "cùng máy"}}
