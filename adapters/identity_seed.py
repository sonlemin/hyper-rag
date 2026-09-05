"""Nạp seed tài khoản từ YAML (story 1.7, mở rộng đầy đủ ở story 3.1 / FR-17).

Nửa I/O của `core/identity.py`, cùng khuôn với cặp `core/policy.py` và
`adapters/policy_loader.py`: đọc file, parse, kiểm hình dạng, dựng object thuần.
`core/` giữ nguyên luật không I/O (AD-1).

Mọi cách hỏng đều ra một loại lỗi kèm tên file: `IdentitySeedInvalid`. Danh sách
rỗng cũng là hỏng, không phải "chưa có ai": một hệ chạy với zero tài khoản là
một hệ mà không ai hỏi được, và nó im lặng cho tới lúc có người thử.

Seed **không** khai quyền. Nó chỉ khai vai, còn vai ánh xạ ra tập khóa ở bảng
chính sách. Nếu file này khai được `allowed_keys` thì có hai nguồn quyền, và
hai nguồn thì lệch được - đúng thứ AD-6 dựng bảng chính sách dạng dữ liệu để
tránh. Cùng lý do, `nhom` ở đây **không** vào khóa lọc: nó là nhóm phụ trách để
audit và để dấu che FR-14 gọi tên, không phải một trục quyền thứ tư.

**Hash mật khẩu dừng ở tầng này.** Nó vào `MucTaiKhoan` (bản ghi của
`adapters/`) và xuống bảng `users` của Postgres, không bao giờ vào
`core.identity.TaiKhoan`: `core/` chỉ stdlib nên nó không so được hash, và một
trường hash ở đó là một giá trị lọt vào mọi `repr()` của tầng trên. Phép so
bcrypt sống ở `api/xac_thuc.py`, chỗ duy nhất import `bcrypt`.

**Story 3.1 lên `version: 2`.** File đổi tên (`config/danh-tinh-demo.yaml` ->
`config/tai-khoan.yaml`), khối gốc đổi từ `danh_tinh` sang `tai_khoan`, và mỗi
mục thêm `mat_khau_hash`, `nhom`, `demo`, `admin`. Một seed version 1 vì thế bị
từ chối chứ không nạp thiếu ba trường mới - đúng luật "đổi hình dạng file là
tăng số này cùng lúc với code đọc nó" mà `core/policy.py` đặt.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.identity import DanhTinh, TaiKhoan

# Phiên bản schema mà module này hiểu, cùng luật với `core/policy.py`: đổi hình
# dạng file là tăng số này cùng lúc với code đọc nó.
SCHEMA_VERSION: int = 2

# Khối gốc chứa danh sách tài khoản.
KHOI_TAI_KHOAN: str = "tai_khoan"

# Danh mục **đóng** các khóa cấp gốc. Danh sách cho phép chứ không phải danh
# sách cấm, cùng lý do với `KV_NAMESPACES` của adapter KV: một khối lạ ở cấp gốc
# - `allowed_keys:` chẳng hạn - nạp bình thường và không ai biết nó bị bỏ qua,
# tức là người viết seed tin rằng mình vừa cấp quyền. Đúng thứ docstring module
# này lấy làm lý do tồn tại, nên nó phải được canh chứ không chỉ được nói.
KHOA_GOC: frozenset[str] = frozenset({"version", KHOI_TAI_KHOAN})

# Ba trường của `DanhTinh`, dẫn xuất chứ không khai tay: thêm một trường ở
# `core/` mà quên sửa loader thì hỏng ngay, thay vì lặng lẽ nạp thiếu.
TRUONG_DANH_TINH: tuple[str, ...] = tuple(DanhTinh.__dataclass_fields__)

# Tên trường mật khẩu đã hash. Nó không đi vào `core/`, nên nó khai ở đây.
TRUONG_HASH: str = "mat_khau_hash"

# Trường bắt buộc của một mục seed: ba trường danh tính, cộng hash và nhóm.
# `demo`/`admin` không bắt buộc - vắng là `False`, tức mặc định *không* quyền,
# đúng chiều fail-closed. Ngược lại thì một mục quên khai `admin` sẽ là một tài
# khoản quản trị mà không ai gõ ra chữ đó.
TRUONG_BAT_BUOC: tuple[str, ...] = TRUONG_DANH_TINH + (TRUONG_HASH, "nhom")
TRUONG_CO: tuple[str, ...] = ("demo", "admin")
TRUONG_CHO_PHEP: frozenset[str] = frozenset(TRUONG_BAT_BUOC + TRUONG_CO)

# Hình dạng một hash bcrypt: `$2<a|b|y>$<cost>$<22 ký tự muối + 31 ký tự hash>`,
# tổng đúng 60 ký tự. Kiểm hình dạng ở đường nạp chứ không đợi lần đăng nhập
# đầu: một chuỗi không phải hash bcrypt làm `bcrypt.checkpw` dội `ValueError`
# giữa một handler, và khi đó ca "sai mật khẩu" và ca "seed hỏng" trả về hai
# thứ khác nhau - tức chính kênh dò mà `DANG_NHAP_SAI` sinh ra để bịt.
HASH_BCRYPT = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")

DUONG_DAN_TAI_KHOAN: Path = (
    Path(__file__).resolve().parent.parent / "config" / "tai-khoan.yaml"
)


class IdentitySeedInvalid(ValueError):
    """File seed tài khoản không nạp được; từ chối nạp, không chạy danh sách rỗng.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp
    (AD-8, Consistency Conventions).
    """

    code = "IDENTITY_SEED_INVALID"


@dataclass(frozen=True)
class MucTaiKhoan:
    """Một dòng seed: tài khoản thuần của `core/` cộng hash mật khẩu.

    Hai nửa tách nhau có chủ đích. `tai_khoan` là thứ đi tiếp vào ngữ cảnh
    quyền, vào claim của token và vào bảng `users`; `mat_khau_hash` chỉ đi vào
    bảng `users` rồi dừng, và nó không bao giờ rời `adapters/` hay `api/` theo
    hướng nào khác.
    """

    tai_khoan: TaiKhoan
    mat_khau_hash: str

    @property
    def ten(self) -> str:
        return self.tai_khoan.tai_khoan


def nap_tai_khoan(path: str | Path | None = None) -> tuple[MucTaiKhoan, ...]:
    """Nạp seed thành tuple `MucTaiKhoan`, giữ thứ tự khai trong file.

    Tuple chứ không list: seed là dữ liệu cấu hình đã chốt lúc khởi động, và
    một danh sách sửa được tại chỗ là một đường thêm tài khoản giữa lúc chạy.
    """
    duong_dan = Path(path) if path is not None else DUONG_DAN_TAI_KHOAN
    try:
        van_ban = duong_dan.read_text(encoding="utf-8")
    except OSError as loi:
        raise IdentitySeedInvalid(
            f"không đọc được file tài khoản {duong_dan}: {loi}"
        ) from None
    try:
        raw = yaml.safe_load(van_ban)
    except yaml.YAMLError as loi:
        raise IdentitySeedInvalid(
            f"YAML hỏng ở {duong_dan}: {str(loi).replace(chr(10), ' ')}"
        ) from loi
    if not isinstance(raw, dict):
        raise IdentitySeedInvalid(
            f"{duong_dan}: gốc file phải là một khối ánh xạ"
        )
    if raw.get("version") != SCHEMA_VERSION or isinstance(raw.get("version"), bool):
        raise IdentitySeedInvalid(
            f"{duong_dan}: `version` = {raw.get('version')!r} không đọc được,"
            f" schema hiện hành là version {SCHEMA_VERSION}"
        )
    la = sorted(set(raw) - KHOA_GOC)
    if la:
        raise IdentitySeedInvalid(
            f"{duong_dan}: khóa lạ ở cấp gốc {la}: seed chỉ khai tài khoản,"
            " quyền thì tra bảng chính sách theo vai"
        )
    khai = raw.get(KHOI_TAI_KHOAN)
    if not isinstance(khai, list) or not khai:
        raise IdentitySeedInvalid(
            f"{duong_dan}: khối `{KHOI_TAI_KHOAN}` phải là danh sách không rỗng"
        )

    danh_sach: list[MucTaiKhoan] = []
    da_thay = set()
    for i, muc in enumerate(khai):
        cho = f"{duong_dan}: tài khoản thứ {i + 1}"
        danh_sach.append(_muc(cho, muc))
        ten = danh_sach[-1].ten
        if ten in da_thay:
            raise IdentitySeedInvalid(
                f"{cho}: tài khoản {ten!r} khai hai lần, một tài khoản hai vai"
                " là hai câu trả lời cho cùng một người hỏi"
            )
        da_thay.add(ten)
    return tuple(danh_sach)


def _muc(cho: str, muc) -> MucTaiKhoan:
    """Một mục seed đã kiểm; mọi cách hỏng là `IdentitySeedInvalid` kèm chỗ."""
    if not isinstance(muc, dict):
        raise IdentitySeedInvalid(f"{cho} không phải một khối ánh xạ")
    thieu = [t for t in TRUONG_BAT_BUOC if t not in muc]
    if thieu:
        raise IdentitySeedInvalid(f"{cho} thiếu trường bắt buộc {thieu}")
    thua = [t for t in muc if t not in TRUONG_CHO_PHEP]
    if thua:
        raise IdentitySeedInvalid(
            f"{cho} khai trường lạ {thua}: seed chỉ khai tài khoản, quyền thì"
            " tra bảng chính sách theo vai"
        )
    hash_mk = muc[TRUONG_HASH]
    if not isinstance(hash_mk, str) or not HASH_BCRYPT.match(hash_mk):
        raise IdentitySeedInvalid(
            f"{cho}: `{TRUONG_HASH}` không phải một hash bcrypt"
            " (`$2b$<cost>$<53 ký tự>`); seed chỉ chứa hash, không chứa mật khẩu"
        )
    try:
        tk = TaiKhoan(
            danh_tinh=DanhTinh(**{t: muc[t] for t in TRUONG_DANH_TINH}),
            nhom=muc["nhom"],
            **{t: muc[t] for t in TRUONG_CO if t in muc},
        )
    except (TypeError, ValueError) as loi:
        raise IdentitySeedInvalid(f"{cho}: {loi}") from None
    return MucTaiKhoan(tai_khoan=tk, mat_khau_hash=hash_mk)


def nap_danh_tinh(path: str | Path | None = None) -> tuple[DanhTinh, ...]:
    """Chỉ phần danh tính của seed, giữ thứ tự khai trong file.

    Cửa cũ của story 1.7, giữ nguyên chữ ký vì `eval/cau_hoi.py` và bộ test cổng
    M1 chỉ cần vai và không gian. Nó **dẫn xuất** từ `nap_tai_khoan` chứ không
    đọc file lần thứ hai: hai đường đọc là hai bộ kiểm trôi dạt được, và trôi
    dạt ở đây nghĩa là một seed hỏng qua được một cửa và chết ở cửa kia.
    """
    return tuple(m.tai_khoan.danh_tinh for m in nap_tai_khoan(path))
