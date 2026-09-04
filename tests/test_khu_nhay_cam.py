"""Công cụ khử nhạy cảm `scripts/khu_nhay_cam.py` (story 2.11).

Viết **trước** khi sửa script, theo FR-27. Lỗi thật mà story này phải đóng: bản
trong `extra/` dựng bảng bí danh từ rỗng rồi ghi đè, nên chạy lần hai trên 20
tài liệu mới cấp lại `203.0.113.1` cho một IP khác - và 30 tài liệu đã khử ở
lần một không còn tra ngược được nữa. Một bảng bí danh không cộng dồn là một
bảng nói dối, và nó nói dối im lặng.

Bốn nhóm ca:

- **Cộng dồn.** Chạy lần hai giữ nguyên mọi bí danh đã cấp và đánh số tiếp.
- **Khóa thêm tay.** `cred_ro` và `nguoi` không do script sinh; ghi lại bảng
  phải giữ chúng nguyên vẹn, kể cả khóa lạ chưa có tên.
- **Một-một hai chiều.** Một giá trị thật đúng một bí danh, và một bí danh đúng
  một giá trị thật - chiều thứ hai mới là chiều chống ghép nhầm hai khách hàng.
- **Không đổi bí danh cũ.** Bảng đã có thì giá trị cũ giữ số cũ dù thứ tự file
  đọc vào khác đi.

Không file nào của công ty đi vào test: mọi ca dựng chuỗi tại chỗ.
"""

import json
from pathlib import Path

import pytest

from scripts.khu_nhay_cam import (
    LOAI_NHIEU_MOT,
    LOAI_SINH,
    BangBiDanh,
    BangBiDanhHong,
    BiDanhTrung,
    khu_thu_muc,
    khu_van_ban,
)


def _bang(**loai) -> BangBiDanh:
    return BangBiDanh(dict(loai))


def _viet(thu_muc: Path, **file) -> Path:
    thu_muc.mkdir(parents=True, exist_ok=True)
    for ten, noi_dung in file.items():
        (thu_muc / f"{ten}.txt").write_text(noi_dung, encoding="utf-8")
    return thu_muc


# ---------------------------------------------------------------------------
# Thay tại chỗ: đúng năm loại, đúng danh sách giữ nguyên
# ---------------------------------------------------------------------------


def test_ip_cong_cong_thanh_test_net_3():
    bang = _bang()
    ra, _ = khu_van_ban("server 45.117.80.10 tra loi", bang)
    assert ra == "server 203.0.113.1 tra loi"
    assert bang.muc("ip") == {"45.117.80.10": "203.0.113.1"}


@pytest.mark.parametrize(
    "giu", ["10.0.0.1", "192.168.1.1", "172.16.0.9", "127.0.0.1", "8.8.8.8", "1.1.1.1"]
)
def test_ip_noi_bo_va_dns_noi_tieng_giu_nguyen(giu):
    """Khử một IP private là xóa mất chính thông tin cấu trúc mạng cần cho fact."""
    ra, _ = khu_van_ban(f"gateway {giu}", _bang())
    assert ra == f"gateway {giu}"


def test_email_va_ten_mien_va_dien_thoai():
    bang = _bang()
    ra, dem = khu_van_ban(
        "lien he ns@acme.vn hoac mail.acme.vn, goi 0912345678", bang
    )
    assert ra == "lien he mai01@example.invalid hoac khachhang01.example, goi 0900000001"
    assert dem["email"] == 1 and dem["domain"] == 1 and dem["phone"] == 1


def test_credential_bi_xoa_va_ghi_vao_cred_ro():
    """Giá trị thật không được nằm lại trong bản đã khử, nhưng phải tra ngược được.

    `cred_ro` là khóa duy nhất *nhiều-một*: mọi credential về cùng một dấu. Nó
    có mặt để người soát biết đã gỡ những gì, không để dựng lại bản gốc.
    """
    bang = _bang()
    ra, dem = khu_van_ban("password: Mau@98765x", bang)
    assert ra == "password: <DA_KHU_credential>"
    assert dem["cred"] == 1
    assert bang.muc("cred_ro") == {"Mau@98765x": "<DA_KHU_credential>"}


def test_credential_trong_dau_nhay_cung_bi_xoa():
    """Lỗ thật của bản `extra/`, phát hiện khi soát tay 04/09.

    Lớp ký tự cấm nháy *bên trong* giá trị nhưng không cho nháy ở hai đầu, nên
    `SECRET="00000000-..."` đi lọt qua cả lần khử 03/09 và nằm lại trong bản
    "đã khử". Nháy bị nuốt cùng giá trị, không giữ lại.
    """
    bang = _bang()
    ra, dem = khu_van_ban('SECRET="00000000-1111-2222-3333-444444444444"', bang)
    assert ra == "SECRET=<DA_KHU_credential>"
    assert dem["cred"] == 1
    lan2, dem2 = khu_van_ban(ra, bang)
    assert lan2 == ra and dem2["cred"] == 0


def test_ten_nguoi_khai_tay_duoc_ap_dung():
    """`nguoi` do người thêm tay, nhưng script phải *dùng* nó.

    Không có bước này thì luật một-một cho tên cá nhân chỉ là lời hứa: 50 tài
    liệu sửa tay không có cách nào canh cùng một người luôn ra cùng một mã.
    """
    bang = _bang(nguoi={"Nguyễn Văn Mẫu": "NV01"})
    ra, _ = khu_van_ban("Nguyễn Văn Mẫu xac nhan", bang)
    assert ra == "NV01 xac nhan"


def test_khong_gan_bi_danh_cho_ten_mien_ha_tang_pho_bien():
    ra, _ = khu_van_ban("apt tu ubuntu.com va github.com", _bang())
    assert ra == "apt tu ubuntu.com va github.com"


def test_ten_mien_con_cua_mot_ten_mien_giu_van_bi_khu():
    """Khiếm khuyết **đã khai**, giữ nguyên có chủ đích: danh sách giữ khớp
    *đúng* tên miền, không khớp tên miền con.

    `archive.ubuntu.com` vì vậy nhận một bí danh dù nó là hạ tầng công cộng. Đó
    là khử thừa, tức lệch về phía an toàn, và nó đã xảy ra trên 30 tài liệu Tech
    Support khử ngày 03/09 (`khachhang06.example` trong bảng). Nới danh sách
    thành khớp hậu tố bây giờ là làm 20 tài liệu mới khác luật với 30 tài liệu
    cũ, tức một corpus hai luật khử - đắt hơn hẳn cái nó sửa.
    """
    ra, _ = khu_van_ban("apt tu archive.ubuntu.com", _bang())
    assert ra == "apt tu khachhang01.example"


# ---------------------------------------------------------------------------
# Cộng dồn
# ---------------------------------------------------------------------------


def test_chay_lan_hai_giu_nguyen_bi_danh_cu_va_danh_so_tiep(tmp_path):
    """Hàng "Khử lần hai" của I/O Matrix."""
    bang_file = tmp_path / "bang.json"
    khu_thu_muc(
        _viet(tmp_path / "v1", a="ip 45.117.80.10"), tmp_path / "r1", bang_file
    )
    cu = json.loads(bang_file.read_text(encoding="utf-8"))
    assert cu["ip"] == {"45.117.80.10": "203.0.113.1"}

    khu_thu_muc(
        _viet(tmp_path / "v2", b="ip 45.117.80.11 va 45.117.80.10"),
        tmp_path / "r2",
        bang_file,
    )
    moi = json.loads(bang_file.read_text(encoding="utf-8"))
    assert moi["ip"] == {"45.117.80.10": "203.0.113.1", "45.117.80.11": "203.0.113.2"}
    # Bản đã khử của lần một vẫn tra ngược được: bí danh cũ không đổi chủ.
    assert (tmp_path / "r1" / "a.txt").read_text(encoding="utf-8") == "ip 203.0.113.1"
    assert (
        (tmp_path / "r2" / "b.txt").read_text(encoding="utf-8")
        == "ip 203.0.113.2 va 203.0.113.1"
    )


def test_bang_chua_co_file_thi_bat_dau_rong(tmp_path):
    bang = BangBiDanh.doc(tmp_path / "chua-co.json")
    assert all(bang.muc(l) == {} for l in LOAI_SINH)


def test_bang_hong_la_loi_co_ma_chu_khong_phai_bang_rong(tmp_path):
    """Một bảng đọc không được mà im lặng thành rỗng là cấp lại số từ đầu."""
    xau = tmp_path / "bang.json"
    xau.write_text("{khong phai json", encoding="utf-8")
    with pytest.raises(BangBiDanhHong) as loi:
        BangBiDanh.doc(xau)
    assert loi.value.code == "BANG_BI_DANH_HONG"


def test_thu_tu_doc_file_khac_di_khong_doi_bi_danh_da_cap(tmp_path):
    """Bảng đã có thì số cũ giữ nguyên, dù lần chạy sau đọc file theo thứ tự khác."""
    bang_file = tmp_path / "bang.json"
    bang_file.write_text(
        json.dumps({"ip": {"45.117.80.11": "203.0.113.7"}}), encoding="utf-8"
    )
    khu_thu_muc(
        _viet(tmp_path / "v", a="45.117.80.10", b="45.117.80.11"),
        tmp_path / "r",
        bang_file,
    )
    ip = json.loads(bang_file.read_text(encoding="utf-8"))["ip"]
    assert ip["45.117.80.11"] == "203.0.113.7", "bí danh cũ bị cấp lại"
    assert ip["45.117.80.10"] not in {"203.0.113.7"}


def test_bi_danh_moi_khong_giam_len_so_da_dung_trong_bang(tmp_path):
    """Bảng sửa tay để lại lỗ số; bí danh mới phải nhảy qua số đã dùng.

    `len(bảng) + 1` là công thức của bản cũ và nó cấp `203.0.113.2` cho một IP
    mới trong khi `203.0.113.2` đã thuộc về một IP khác - hai giá trị thật một
    bí danh, đúng thứ bảng này sinh ra để chống.
    """
    bang = _bang(ip={"45.117.80.11": "203.0.113.2"})
    khu_van_ban("45.117.80.10", bang)
    assert bang.muc("ip")["45.117.80.10"] != "203.0.113.2"
    assert len(set(bang.muc("ip").values())) == 2


# ---------------------------------------------------------------------------
# Khóa thêm tay
# ---------------------------------------------------------------------------


def test_ghi_lai_bang_giu_nguyen_khoa_them_tay(tmp_path):
    """Hàng "Bảng có khóa thêm tay": `cred_ro`, `nguoi` và cả khóa chưa có tên."""
    bang_file = tmp_path / "bang.json"
    goc = {
        "ip": {},
        "cred_ro": {"Mau@1234": "<DA_KHU_credential>"},
        "nguoi": {"MauNV": "NV02"},
        "khoa_la_chua_dat_ten": {"x": "y"},
    }
    bang_file.write_text(json.dumps(goc, ensure_ascii=False), encoding="utf-8")
    khu_thu_muc(_viet(tmp_path / "v", a="45.117.80.10"), tmp_path / "r", bang_file)

    sau = json.loads(bang_file.read_text(encoding="utf-8"))
    assert sau["cred_ro"] == goc["cred_ro"]
    assert sau["nguoi"] == goc["nguoi"]
    assert sau["khoa_la_chua_dat_ten"] == goc["khoa_la_chua_dat_ten"]
    assert sau["ip"] == {"45.117.80.10": "203.0.113.1"}


def test_bang_thieu_mot_loai_sinh_van_doc_duoc(tmp_path):
    """Bảng viết tay thiếu `phone` không được làm cả lần chạy chết."""
    bang_file = tmp_path / "bang.json"
    bang_file.write_text(json.dumps({"ip": {}}), encoding="utf-8")
    khu_thu_muc(_viet(tmp_path / "v", a="goi 0912345678"), tmp_path / "r", bang_file)
    assert json.loads(bang_file.read_text(encoding="utf-8"))["phone"] == {
        "0912345678": "0900000001"
    }


# ---------------------------------------------------------------------------
# Một-một hai chiều và bất động
# ---------------------------------------------------------------------------


def test_kiem_mot_mot_bat_hai_gia_tri_that_chung_mot_bi_danh():
    bang = _bang(ip={"45.117.80.10": "203.0.113.1", "45.117.80.11": "203.0.113.1"})
    loi = bang.kiem_mot_mot()
    assert loi and "203.0.113.1" in loi[0]


def test_ghi_bang_hong_mot_mot_la_loi_co_ma(tmp_path):
    """Không ghi một bảng đã hỏng: nó là thứ duy nhất tra ngược được 50 tài liệu."""
    bang = _bang(ip={"a": "203.0.113.1", "b": "203.0.113.1"})
    with pytest.raises(BiDanhTrung) as loi:
        bang.ghi(tmp_path / "bang.json")
    assert loi.value.code == "BI_DANH_TRUNG"
    assert not (tmp_path / "bang.json").exists()


@pytest.mark.parametrize("loai", sorted(LOAI_NHIEU_MOT))
def test_loai_nhieu_mot_khong_bi_tinh_la_trung(loai):
    """Hai ngoại lệ tường minh, hai lý do khác nhau.

    `cred_ro` là dấu xóa chứ không phải bí danh tra ngược. `to_chuc` và `nguoi`
    là các cách viết của **cùng một** tổ chức (`CongTyX`, `CongTyx`,
    `congtyxcloud`) hay cùng một người (`Nguyễn Văn A`, `nvana`), và chúng phải
    về cùng một bí danh - đó là tính nhất quán bảng này bảo vệ.
    """
    bang = _bang(**{loai: {"a": "X", "b": "X"}})
    assert bang.kiem_mot_mot() == []


def test_to_chuc_ap_dung_ban_dai_truoc_ban_ngan():
    """`CongTyXcloud` phải thay trước `CongTyX`, nếu không còn lại chữ `cloud`.

    Cùng luật với `nguoi`, và hai loại tay xếp chung một lượt: xếp riêng từng
    loại thì một tên tổ chức ngắn vẫn cắt được vào giữa một tên dài của loại kia.
    """
    bang = _bang(to_chuc={"CongTyX": "ToChuc13", "CongTyXcloud": "ToChuc13"})
    ra, dem = khu_van_ban("CongTyXcloud va CongTyX", bang)
    assert ra == "ToChuc13 va ToChuc13"
    assert dem["ten_rieng"] == 2


def test_khu_lai_ban_da_khu_khong_doi_gi():
    """Bất động: chạy công cụ lên chính đầu ra của nó không cấp thêm bí danh nào.

    Không có tính chất này thì một lần chạy nhầm vào thư mục `txt-khu/` cấp
    `203.0.113.2` cho `203.0.113.1`, và bảng bí danh mất luôn nghĩa.
    """
    bang = _bang()
    lan1, _ = khu_van_ban(
        "ip 45.117.80.10, mail ns@acme.vn, ten mien mail.acme.vn, dt 0912345678", bang
    )
    lan2, dem = khu_van_ban(lan1, bang)
    assert lan2 == lan1
    assert sum(dem.values()) == 0


def test_khu_thu_muc_chi_doc_txt_va_tra_so_file(tmp_path):
    vao = _viet(tmp_path / "v", a="45.117.80.10", b="45.117.80.11")
    (vao / "ghi-chu.md").write_text("45.117.80.12", encoding="utf-8")
    so = khu_thu_muc(vao, tmp_path / "r", tmp_path / "bang.json")
    assert so == 2
    assert sorted(p.name for p in (tmp_path / "r").iterdir()) == ["a.txt", "b.txt"]


def test_khong_in_gia_tri_that_ra_console(tmp_path, capsys):
    """Script chỉ in số lượng: log là một đường rò thứ hai không ai canh."""
    from scripts.khu_nhay_cam import main

    main(
        [
            str(_viet(tmp_path / "v", a="45.117.80.10 ns@acme.vn")),
            str(tmp_path / "r"),
            str(tmp_path / "bang.json"),
        ]
    )
    ra = capsys.readouterr().out
    assert "45.117.80.10" not in ra and "acme.vn" not in ra
    assert "ip=1" in ra and "email=1" in ra
