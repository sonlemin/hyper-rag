"""Khử nhạy cảm tại máy cho tài liệu thật trước khi đưa vào bất kỳ đường xử lý nào.

    uv run python -m scripts.khu_nhay_cam <thư mục txt vào> <thư mục ra> <file bảng bí danh>

Thay tại chỗ, một-một và nhất quán trên **mọi lần chạy**, không chỉ trong một
lần chạy:

  - IP công cộng (bỏ private/loopback/DNS công cộng nổi tiếng) -> 203.0.113.x (TEST-NET-3)
  - email                                                     -> maiNN@example.invalid
  - tên miền công ty và tên miền lạ                            -> khachhangNN.example
  - số điện thoại VN                                           -> 0900000NNN
  - giá trị sau từ khóa credential                             -> <DA_KHU_credential>
  - tên cá nhân khai tay trong bảng                            -> NVnn
  - tên tổ chức / thương hiệu / cơ sở khai tay                 -> ToChucNN, DCnn

Vì sao công cụ nằm trong repo (story 2.11): nó là một bước của **phương pháp**
khóa luận, nên nó phải soát được và có test. Nó không đọc và không ghi file nào
trong repo - đầu vào, đầu ra và bảng bí danh đều nằm ngoài (FR-31).

**Bảng bí danh cộng dồn.** Bản trong `extra/` dựng bảng từ rỗng rồi ghi đè, nên
lần chạy thứ hai cấp lại `203.0.113.1` cho một IP khác và 30 tài liệu đã khử ở
lần một mất đường tra ngược. Ở đây bảng cũ được đọc trước, bí danh đã cấp giữ
nguyên, giá trị mới đánh số tiếp, và **mọi khóa lạ trong bảng được giữ nguyên
văn** - `cred_ro` và `nguoi` do người thêm tay, một lần ghi đè im lặng là mất
chúng.

Script chỉ in số lượng, không in giá trị thật: log là một đường rò thứ hai mà
không ai canh.
"""

import json
import re
import sys
from pathlib import Path
from typing import Mapping

# --- Bốn loại script tự sinh bí danh, kèm khuôn số ---------------------------

MAU_BI_DANH: Mapping[str, str] = {
    "ip": "203.0.113.{n}",
    "email": "mai{n:02d}@example.invalid",
    "domain": "khachhang{n:02d}.example",
    "phone": "0900000{n:03d}",
}
LOAI_SINH: tuple[str, ...] = tuple(MAU_BI_DANH)

# Loại **nhiều-một** duy nhất: mọi credential về cùng một dấu. Nó được ghi lại
# để người soát biết đã gỡ những gì, không để dựng lại bản gốc - nên nó là ngoại
# lệ tường minh của phép kiểm một-một.
LOAI_GHI_NHAN: str = "cred_ro"
DAU_CREDENTIAL: str = "<DA_KHU_credential>"

# Hai loại do **người** điền, script chỉ áp dụng. Nhận diện tên riêng tiếng Việt
# bằng regex là một cửa sai cả hai chiều, nên phần nhận diện là việc của người
# soát. Chúng có mặt ở đây vì không có bước áp dụng thì luật một-một cho tên
# riêng chỉ là lời hứa: 50 tài liệu sửa tay không có cách nào canh cùng một
# người, cùng một khách hàng luôn ra cùng một mã.
#
# `nguoi` là tên cá nhân. `to_chuc` là tên tổ chức, thương hiệu và cơ sở - dạng
# **trần** của chúng, thứ mà regex tên miền không thấy: `khachx.vn` đã thành
# `khachhang26.example` nhưng chữ `khachx` trong câu văn thì chưa.
LOAI_TAY: tuple[str, ...] = ("nguoi", "to_chuc")

# Loại được phép **nhiều-một**: `cred_ro` cộng cả hai loại khai tay. Mọi
# credential về cùng một dấu xóa. Một tổ chức viết được nhiều kiểu (`CongTyX`,
# `CongTyx`, `congtyxcloud`) và một người có cả tên đầy đủ lẫn tên tài khoản
# (`Nguyễn Văn A`, `nvana`); cả hai *phải* về cùng một bí danh - đó chính là
# tính nhất quán bảng này bảo vệ, không phải một vi phạm của nó.
#
# Chiều còn lại - hai người khác nhau chung một bí danh - là phép kiểm của người
# soát, không bắt được bằng máy. Phép kiểm một-một vì vậy chỉ còn áp cho bốn
# loại script tự sinh, nơi vòng nhảy số của `bi_danh` đã bảo đảm nó và nơi một
# lần sửa tay có thể phá nó.
LOAI_NHIEU_MOT: frozenset[str] = frozenset({LOAI_GHI_NHAN, *LOAI_TAY})

IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:vn|com|net|io|cloud)\b", re.I)
PHONE = re.compile(r"\b0\d{9,10}\b")
# Nháy bao quanh giá trị là **tùy chọn** và bị nuốt cùng giá trị. Bản trong
# `extra/` cấm nháy trong lớp ký tự nhưng không cho phép nó ở hai đầu, nên
# `SECRET="00000000-..."` đi lọt qua cả lần khử 03/09 - một credential thật nằm
# lại trong bản "đã khử" chỉ vì nó được viết trong dấu nháy.
CRED = re.compile(
    r"((?:password|passwd|pass|mật\s*khẩu|token|secret|api[_\- ]?key)\s*[:=]\s*)"
    r"[\"']?([^\s'\"]{4,})[\"']?",
    re.I,
)

# IP giữ nguyên. `203.0.113.` nằm trong danh sách này là điều kiện **bất động**:
# chạy công cụ lên chính đầu ra của nó không được cấp thêm bí danh nào, nếu
# không một lần trỏ nhầm vào thư mục `txt-khu/` làm bảng mất nghĩa.
IP_GIU = re.compile(
    r"^(?:10\.|127\.|0\.|255\.|169\.254\.|192\.168\.|203\.0\.113\.|"
    r"172\.(?:1[6-9]|2\d|3[01])\.)"
)
IP_CONG_CONG_GIU = frozenset({"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1"})
# Số điện thoại đã là bí danh (`0900000NNN`): cùng lý do bất động với IP trên.
PHONE_DA_KHU = re.compile(r"^0900000\d{3}$")
DUOI_EMAIL_GIU = ("example.com", "example.org", "example.invalid")
DOMAIN_GIU = frozenset(
    {
        "example.com", "example.org", "domain.com", "google.com", "gmail.com",
        "microsoft.com", "ubuntu.com", "github.com", "docker.com", "kernel.org",
        "nginx.com", "apache.org", "mysql.com", "redhat.com", "centos.org",
        "debian.org", "cloudflare.com", "letsencrypt.org", "python.org",
    }
)


class BangBiDanhHong(RuntimeError):
    """Bảng bí danh trên đĩa không đọc được hoặc sai hình dạng.

    **Không** rơi về bảng rỗng: một bảng đọc hỏng mà im lặng thành rỗng là cấp
    lại số từ đầu, tức hai giá trị thật dùng chung một bí danh trên hai đợt.
    """

    code = "BANG_BI_DANH_HONG"


class BiDanhTrung(ValueError):
    """Hai giá trị thật cùng một bí danh (ngoài `cred_ro`), tức bảng mất tính một-một."""

    code = "BI_DANH_TRUNG"


class BangBiDanh:
    """Bảng ánh xạ giá trị thật -> bí danh, cộng dồn qua nhiều lần chạy.

    Giữ nguyên văn mọi khóa nó không hiểu. Đó là điều kiện để `cred_ro` và
    `nguoi` - hai khóa người thêm tay - sống sót qua một lần ghi lại.
    """

    def __init__(self, du_lieu: Mapping[str, Mapping[str, str]] | None = None):
        self._du_lieu: dict[str, dict[str, str]] = {
            k: dict(v) for k, v in (du_lieu or {}).items()
        }

    # --- đọc, ghi ---------------------------------------------------------

    @classmethod
    def doc(cls, duong_dan: str | Path) -> "BangBiDanh":
        """Đọc bảng cũ; file chưa có là bảng rỗng, file hỏng là lỗi có mã."""
        duong_dan = Path(duong_dan)
        if not duong_dan.exists():
            return cls()
        try:
            raw = json.loads(duong_dan.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as loi:
            raise BangBiDanhHong(f"không đọc được bảng bí danh {duong_dan}: {loi}") from None
        if not isinstance(raw, dict):
            raise BangBiDanhHong(f"{duong_dan}: gốc phải là object, nhận {type(raw).__name__}")
        for khoa, muc in raw.items():
            if not isinstance(muc, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in muc.items()
            ):
                raise BangBiDanhHong(f"{duong_dan}: khóa {khoa!r} không phải map chuỗi -> chuỗi")
        return cls(raw)

    def ghi(self, duong_dan: str | Path) -> Path:
        """Ghi bảng, sau khi kiểm một-một. Bảng hỏng thì **không** ghi gì.

        Bảng bí danh là thứ duy nhất tra ngược được 50 tài liệu đã khử; ghi đè
        nó bằng một bản đã mất tính một-một là mất luôn khả năng kiểm.
        """
        loi = self.kiem_mot_mot()
        if loi:
            raise BiDanhTrung("; ".join(loi))
        for loai in LOAI_SINH:
            self._du_lieu.setdefault(loai, {})
        duong_dan = Path(duong_dan)
        duong_dan.parent.mkdir(parents=True, exist_ok=True)
        duong_dan.write_text(
            json.dumps(self._du_lieu, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return duong_dan

    # --- tra, cấp ---------------------------------------------------------

    def muc(self, loai: str) -> dict[str, str]:
        """Map của một loại; loại chưa có trả map rỗng (không tạo khóa)."""
        return self._du_lieu.get(loai, {})

    def bi_danh(self, loai: str, that: str) -> str:
        """Bí danh của một giá trị thật, cấp mới nếu chưa có.

        Số mới bắt đầu từ `len + 1` rồi **nhảy qua mọi số đã dùng**: bảng sửa
        tay để lại lỗ, và `len + 1` khi đó cấp một bí danh đang thuộc về giá trị
        khác - hai giá trị thật một bí danh, đúng thứ bảng này chống.
        """
        bang = self._du_lieu.setdefault(loai, {})
        if that in bang:
            return bang[that]
        da_dung = set(bang.values())
        mau = MAU_BI_DANH[loai]
        n = len(bang) + 1
        while mau.format(n=n) in da_dung:
            n += 1
        bang[that] = mau.format(n=n)
        return bang[that]

    def ghi_nhan(self, loai: str, that: str, gia_tri: str) -> None:
        """Ghi một cặp không đánh số (`cred_ro`), giữ giá trị đã có."""
        self._du_lieu.setdefault(loai, {}).setdefault(that, gia_tri)

    def kiem_mot_mot(self) -> list[str]:
        """Danh sách vi phạm một-một, rỗng là bảng lành.

        `LOAI_NHIEU_MOT` được loại tường minh: dấu xóa credential và các cách
        viết khác nhau của cùng một tổ chức là nhiều-một có chủ đích.
        """
        loi: list[str] = []
        for loai, bang in sorted(self._du_lieu.items()):
            if loai in LOAI_NHIEU_MOT:
                continue
            nguoc: dict[str, list[str]] = {}
            for that, bi in bang.items():
                nguoc.setdefault(bi, []).append(that)
            for bi, ds in sorted(nguoc.items()):
                if len(ds) > 1:
                    loi.append(f"{loai}: bí danh {bi!r} dùng cho {len(ds)} giá trị thật")
        return loi


# --- Khử một văn bản ---------------------------------------------------------


def khu_van_ban(text: str, bang: BangBiDanh) -> tuple[str, dict[str, int]]:
    """Khử một chuỗi; trả (chuỗi đã khử, số lần thay theo loại). Không I/O.

    Thứ tự cố ý: credential trước (nó ăn cả token phía sau dấu hai chấm), rồi
    email trước tên miền (để tên miền của email không bị cấp thêm một bí danh
    thứ hai), rồi IP, tên miền, số điện thoại. Tên người áp **cuối cùng**, trên
    phần văn xuôi còn lại, để không cắt vào giữa một email đã thay.
    """
    dem = {"ip": 0, "email": 0, "domain": 0, "phone": 0, "cred": 0, "ten_rieng": 0}

    def thay_cred(m: re.Match) -> str:
        if m.group(2) == DAU_CREDENTIAL:
            return m.group(0)
        dem["cred"] += 1
        bang.ghi_nhan(LOAI_GHI_NHAN, m.group(2), DAU_CREDENTIAL)
        return f"{m.group(1)}{DAU_CREDENTIAL}"

    def thay_email(m: re.Match) -> str:
        v = m.group(0)
        if v.lower().endswith(DUOI_EMAIL_GIU):
            return v
        dem["email"] += 1
        return bang.bi_danh("email", v.lower())

    def thay_ip(m: re.Match) -> str:
        v = m.group(0)
        if IP_GIU.match(v) or v in IP_CONG_CONG_GIU:
            return v
        if any(int(p) > 255 for p in v.split(".")):
            return v
        dem["ip"] += 1
        return bang.bi_danh("ip", v)

    def thay_domain(m: re.Match) -> str:
        v = m.group(0)
        if v.lower() in DOMAIN_GIU:
            return v
        dem["domain"] += 1
        return bang.bi_danh("domain", v.lower())

    def thay_phone(m: re.Match) -> str:
        v = m.group(0)
        if PHONE_DA_KHU.match(v):
            return v
        dem["phone"] += 1
        return bang.bi_danh("phone", v)

    text = CRED.sub(thay_cred, text)
    text = EMAIL.sub(thay_email, text)
    text = IP.sub(thay_ip, text)
    text = DOMAIN.sub(thay_domain, text)
    text = PHONE.sub(thay_phone, text)
    # Tên dài trước tên ngắn, trên **cả hai** loại tay cùng lúc: `CongTyXcloud`
    # phải được thay trước `CongTyX`, nếu không phần còn lại (`cloud`) là một
    # mảnh tên thật nằm lại trong bản đã khử.
    tay = {t: v for loai in LOAI_TAY for t, v in bang.muc(loai).items() if t}
    for that in sorted(tay, key=len, reverse=True):
        if that in text:
            dem["ten_rieng"] += text.count(that)
            text = text.replace(that, tay[that])
    return text, dem


# --- Khử một thư mục ---------------------------------------------------------


def khu_thu_muc(vao: str | Path, ra: str | Path, bang_file: str | Path) -> int:
    """Khử mọi `.txt` trong `vao` ra `ra`, cộng dồn vào `bang_file`; trả số file."""
    vao, ra, bang_file = Path(vao), Path(ra), Path(bang_file)
    bang = BangBiDanh.doc(bang_file)
    ra.mkdir(parents=True, exist_ok=True)
    so_file = 0
    tong = {"ip": 0, "email": 0, "domain": 0, "phone": 0, "cred": 0, "ten_rieng": 0}
    for f in sorted(vao.glob("*.txt")):
        van_ban, dem = khu_van_ban(f.read_text(encoding="utf-8", errors="replace"), bang)
        (ra / f.name).write_text(van_ban, encoding="utf-8")
        for k, v in dem.items():
            tong[k] += v
        so_file += 1
    bang.ghi(bang_file)
    khu_thu_muc.tong_lan_cuoi = tong  # type: ignore[attr-defined]
    return so_file


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 3:
        print(
            "dung: python -m scripts.khu_nhay_cam <thu muc vao> <thu muc ra>"
            " <file bang bi danh>",
            file=sys.stderr,
        )
        return 2
    vao, ra, bang_file = (Path(a) for a in argv)
    so_file = khu_thu_muc(vao, ra, bang_file)
    tong = getattr(khu_thu_muc, "tong_lan_cuoi", {})
    print(f"{so_file} file đã khử -> {ra}")
    print("số lần thay:", ", ".join(f"{k}={v}" for k, v in tong.items()))
    print("bảng bí danh:", bang_file, "(giữ ngoài repo, cộng dồn)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
