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
    FileLaTrongThuMucNguon,
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


# IP đầu vào của test lấy từ TEST-NET-2 (`198.51.100.0/24`, RFC 5737), đầu ra là
# TEST-NET-3 (`203.0.113.0/24`) như bí danh thật. Cả hai dải đều dành riêng cho
# tài liệu và không định tuyến: một fixture mang IP thuộc dải cấp phát thật là
# một chuỗi mà người soát sau phải dừng lại kiểm xem có phải của công ty không.
def test_ip_cong_cong_thanh_test_net_3():
    bang = _bang()
    ra, _ = khu_van_ban("server 198.51.100.10 tra loi", bang)
    assert ra == "server 203.0.113.1 tra loi"
    assert bang.muc("ip") == {"198.51.100.10": "203.0.113.1"}


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
        _viet(tmp_path / "v1", a="ip 198.51.100.10"), tmp_path / "r1", bang_file
    )
    cu = json.loads(bang_file.read_text(encoding="utf-8"))
    assert cu["ip"] == {"198.51.100.10": "203.0.113.1"}

    khu_thu_muc(
        _viet(tmp_path / "v2", b="ip 198.51.100.11 va 198.51.100.10"),
        tmp_path / "r2",
        bang_file,
    )
    moi = json.loads(bang_file.read_text(encoding="utf-8"))
    assert moi["ip"] == {"198.51.100.10": "203.0.113.1", "198.51.100.11": "203.0.113.2"}
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
        json.dumps({"ip": {"198.51.100.11": "203.0.113.7"}}), encoding="utf-8"
    )
    khu_thu_muc(
        _viet(tmp_path / "v", a="198.51.100.10", b="198.51.100.11"),
        tmp_path / "r",
        bang_file,
    )
    ip = json.loads(bang_file.read_text(encoding="utf-8"))["ip"]
    assert ip["198.51.100.11"] == "203.0.113.7", "bí danh cũ bị cấp lại"
    assert ip["198.51.100.10"] not in {"203.0.113.7"}


def test_bi_danh_moi_khong_giam_len_so_da_dung_trong_bang(tmp_path):
    """Bảng sửa tay để lại lỗ số; bí danh mới phải nhảy qua số đã dùng.

    `len(bảng) + 1` là công thức của bản cũ và nó cấp `203.0.113.2` cho một IP
    mới trong khi `203.0.113.2` đã thuộc về một IP khác - hai giá trị thật một
    bí danh, đúng thứ bảng này sinh ra để chống.
    """
    bang = _bang(ip={"198.51.100.11": "203.0.113.2"})
    khu_van_ban("198.51.100.10", bang)
    assert bang.muc("ip")["198.51.100.10"] != "203.0.113.2"
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
    khu_thu_muc(_viet(tmp_path / "v", a="198.51.100.10"), tmp_path / "r", bang_file)

    sau = json.loads(bang_file.read_text(encoding="utf-8"))
    assert sau["cred_ro"] == goc["cred_ro"]
    assert sau["nguoi"] == goc["nguoi"]
    assert sau["khoa_la_chua_dat_ten"] == goc["khoa_la_chua_dat_ten"]
    assert sau["ip"] == {"198.51.100.10": "203.0.113.1"}


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
    bang = _bang(ip={"198.51.100.10": "203.0.113.1", "198.51.100.11": "203.0.113.1"})
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
        "ip 198.51.100.10, mail ns@acme.vn, ten mien mail.acme.vn, dt 0912345678", bang
    )
    lan2, dem = khu_van_ban(lan1, bang)
    assert lan2 == lan1
    assert sum(dem.values()) == 0


def test_khu_thu_muc_tra_so_file(tmp_path):
    vao = _viet(tmp_path / "v", a="198.51.100.10", b="198.51.100.11")
    so = khu_thu_muc(vao, tmp_path / "r", tmp_path / "bang.json")
    assert so == 2
    assert sorted(p.name for p in (tmp_path / "r").iterdir()) == ["a.txt", "b.txt"]


def test_duoi_la_trong_thu_muc_nguon_la_tu_choi_ca_dot(tmp_path):
    """Bỏ qua im lặng một đuôi lạ là để một tài liệu thật đi ra ngoài không khử.

    Bản trước lọc bằng `glob("*.txt")`, nên một `.md` đặt nhầm vào thư mục nguồn
    không được khử và cũng không có dòng nào nói ra - người chạy đọc "30 file đã
    khử" rồi tin cả thư mục đã sạch.
    """
    vao = _viet(tmp_path / "v", a="198.51.100.10")
    (vao / "ghi-chu.md").write_text("198.51.100.12", encoding="utf-8")
    with pytest.raises(FileLaTrongThuMucNguon) as loi:
        khu_thu_muc(vao, tmp_path / "r", tmp_path / "bang.json")
    assert loi.value.code == "FILE_LA_TRONG_THU_MUC_NGUON"
    assert "ghi-chu.md" in str(loi.value)
    assert not (tmp_path / "r").exists(), "không được ghi gì khi đã từ chối"


def test_file_an_trong_thu_muc_nguon_khong_tinh_la_duoi_la(tmp_path):
    """`.space`, `.DS_Store` là file ẩn, không phải một tài liệu sai đuôi."""
    vao = _viet(tmp_path / "v", a="198.51.100.10")
    (vao / ".space").write_text("real\n", encoding="utf-8")
    assert khu_thu_muc(vao, tmp_path / "r", tmp_path / "bang.json") == 1


def test_file_khong_phai_utf8_la_tu_choi_chu_khong_thay_ky_tu(tmp_path):
    """`errors="replace"` biến byte hỏng thành mojibake, mà mojibake vô hiệu hóa
    mọi regex: một tên thật méo đi được ghi ra như thể đã khử."""
    vao = tmp_path / "v"
    vao.mkdir()
    (vao / "a.txt").write_bytes(b"ten that \xff\xfe roi 198.51.100.10")
    with pytest.raises(UnicodeDecodeError):
        khu_thu_muc(vao, tmp_path / "r", tmp_path / "bang.json")
    assert not (tmp_path / "r").exists()


def test_bang_hong_san_thi_doi_loi_va_thu_muc_ra_rong(tmp_path):
    """Ghi trọn thư mục ra **rồi** mới kiểm bảng là dựng đúng trạng thái mà story
    này sinh ra để chống: một thư mục đã khử mà bảng tra ngược không được lưu.

    Bảng hỏng phải dội **trước** khi chạm thư mục ra.
    """
    bang_file = tmp_path / "bang.json"
    bang_file.write_text(
        json.dumps({"ip": {"a": "203.0.113.1", "b": "203.0.113.1"}}), encoding="utf-8"
    )
    vao = _viet(tmp_path / "v", a="198.51.100.10")
    with pytest.raises(BiDanhTrung):
        khu_thu_muc(vao, tmp_path / "r", bang_file)
    assert not (tmp_path / "r").exists(), "thư mục ra phải rỗng"


def test_bang_luon_nam_tren_dia_truoc_file_dau_tien(tmp_path):
    """Thứ tự ghi: bảng trước, file sau. Đứt giữa chừng thì bảng vẫn là một
    siêu tập của những gì đã ghi ra, không bao giờ ngược lại."""
    vao = _viet(tmp_path / "v", a="198.51.100.10")
    khu_thu_muc(vao, tmp_path / "r", tmp_path / "bang.json")
    bang = json.loads((tmp_path / "bang.json").read_text(encoding="utf-8"))
    assert bang["ip"] == {"198.51.100.10": "203.0.113.1"}


def test_khong_in_gia_tri_that_ra_console(tmp_path, capsys):
    """Script chỉ in số lượng: log là một đường rò thứ hai không ai canh."""
    from scripts.khu_nhay_cam import main

    main(
        [
            str(_viet(tmp_path / "v", a="198.51.100.10 ns@acme.vn")),
            str(tmp_path / "r"),
            str(tmp_path / "bang.json"),
        ]
    )
    ra = capsys.readouterr().out
    assert "198.51.100.10" not in ra and "acme.vn" not in ra
    assert "ip=1" in ra and "email=1" in ra


# ---------------------------------------------------------------------------
# Vá vòng review 05/09: bốn lỗ của công cụ, vá cho lần sau
# ---------------------------------------------------------------------------


def test_credential_co_khoang_trang_bi_nuot_tron():
    """`password: "hai tu"` mà chỉ nuốt token đầu là để nửa sau nằm lại.

    Bản trước cho ra `password: <DA_KHU_credential> tu"` - nửa sau của chính
    mật khẩu, cộng một dấu nháy lạc.
    """
    ra, _ = khu_van_ban('password: "mat khau hai tu" roi', _bang())
    assert ra == "password: <DA_KHU_credential> roi"


@pytest.mark.parametrize(
    "dong",
    [
        "pwd=Zz9!abcdef",
        "PWD: Zz9!abcdef",
        "client_secret=Zz9!abcdef",
        "private_key: Zz9!abcdef",
        "access_key = Zz9!abcdef",
        "Authorization: Bearer Zz9abcdefgh",
    ],
)
def test_tu_khoa_credential_moi(dong):
    """Sáu từ khóa cũ bỏ sót những tên hay gặp nhất trong tài liệu vận hành."""
    ra, dem = khu_van_ban(dong, _bang())
    assert "Zz9" not in ra, ra
    assert dem["cred"] == 1


def test_bearer_dung_mot_minh_cung_bi_khu():
    """Dòng header chép rời khỏi tên header: `Bearer <token>` không có dấu hai chấm."""
    ra, dem = khu_van_ban("gui kem Bearer abcdef123456 vao header", _bang())
    assert ra == "gui kem Bearer <DA_KHU_credential> vao header"
    assert dem["cred"] == 1


def test_authorization_khong_chi_nuot_moi_chu_bearer():
    """`Authorization: Bearer <token>` mà chỉ nuốt `Bearer` là để nguyên token."""
    ra, _ = khu_van_ban("Authorization: Bearer abcdef123456", _bang())
    assert "abcdef123456" not in ra


@pytest.mark.parametrize(
    "ten_mien", ["khach.org", "khach.info", "khach.dev", "khach.co.uk", "khach.app"]
)
def test_ten_mien_ngoai_nam_tld_cu_cung_bi_khu(ten_mien):
    """Bản trước chỉ khớp `vn|com|net|io|cloud`, nên `.org` của khách đi lọt -
    và 7 mục `.org` trong danh sách giữ là mục **chết**, regex không chạm tới."""
    ra, dem = khu_van_ban(f"truy cap {ten_mien}", _bang())
    assert ten_mien not in ra
    assert dem["domain"] == 1


@pytest.mark.parametrize("giu", ["apache.org", "kernel.org", "python.org"])
def test_danh_sach_giu_org_nay_moi_that_su_co_tac_dung(giu):
    """Đối chứng của test trên: nới TLD mà quên danh sách giữ là khử cả hạ tầng
    công cộng."""
    ra, _ = khu_van_ban(f"tai tu {giu}", _bang())
    assert ra == f"tai tu {giu}"


def test_ten_khai_tay_thay_theo_bien_tu():
    """`str.replace` thô làm một mã ngắn cắt vào giữa mọi từ chứa nó."""
    bang = _bang(nguoi={"NV": "NguoiX"})
    ra, dem = khu_van_ban("NV bao cao, NVIDIA khong lien quan, aNVb cung the", bang)
    assert ra == "NguoiX bao cao, NVIDIA khong lien quan, aNVb cung the"
    assert dem["ten_rieng"] == 1


def test_khoa_nam_o_ca_hai_loai_tay_voi_hai_bi_danh_la_tu_choi():
    """Hai lời khai chống nhau về cùng một chuỗi: thứ tự khóa trong file JSON
    quyết định bên nào thắng, tức kết quả khử phụ thuộc thứ tự khóa."""
    bang = _bang(nguoi={"Mau": "NV01"}, to_chuc={"Mau": "ToChuc01"})
    with pytest.raises(BiDanhTrung):
        khu_van_ban("Mau", bang)


def test_khoa_nam_o_ca_hai_loai_tay_cung_bi_danh_thi_khong_sao():
    """Trùng khai mà **cùng** bí danh không mâu thuẫn, không có gì để chọn."""
    bang = _bang(nguoi={"Mau": "X"}, to_chuc={"Mau": "X"})
    ra, _ = khu_van_ban("Mau", bang)
    assert ra == "X"


def test_main_in_ma_loi_thay_vi_traceback(tmp_path, capsys):
    """Mọi đường từ chối của dự án in `code: message` rồi trả mã khác 0."""
    from scripts.khu_nhay_cam import main

    vao = _viet(tmp_path / "v", a="198.51.100.10")
    (vao / "la.md").write_text("x", encoding="utf-8")
    ma = main([str(vao), str(tmp_path / "r"), str(tmp_path / "bang.json")])
    assert ma == 1
    assert "FILE_LA_TRONG_THU_MUC_NGUON" in capsys.readouterr().err
