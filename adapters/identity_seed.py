"""Nạp seed danh tính demo từ YAML (story 1.7, FR-17 đầy đủ ở Epic 3).

Nửa I/O của `core/identity.py`, cùng khuôn với cặp `core/policy.py` và
`adapters/policy_loader.py`: đọc file, parse, kiểm hình dạng, dựng object thuần.
`core/` giữ nguyên luật không I/O (AD-1).

Mọi cách hỏng đều ra một loại lỗi kèm tên file: `IdentitySeedInvalid`. Danh sách
rỗng cũng là hỏng, không phải "chưa có ai": một hệ chạy với zero danh tính là
một hệ mà không ai hỏi được, và nó im lặng cho tới lúc có người thử.

Seed **không** khai quyền. Nó chỉ khai vai, còn vai ánh xạ ra tập khóa ở bảng
chính sách. Nếu file này khai được `allowed_keys` thì có hai nguồn quyền, và
hai nguồn thì lệch được - đúng thứ AD-6 dựng bảng chính sách dạng dữ liệu để
tránh.
"""

from pathlib import Path

import yaml

from core.identity import DanhTinh

# Phiên bản schema mà module này hiểu, cùng luật với `core/policy.py`: đổi hình
# dạng file là tăng số này cùng lúc với code đọc nó.
SCHEMA_VERSION: int = 1

# Khối gốc chứa danh sách danh tính.
KHOI_DANH_TINH: str = "danh_tinh"

# Danh mục **đóng** các khóa cấp gốc. Danh sách cho phép chứ không phải danh
# sách cấm, cùng lý do với `KV_NAMESPACES` của adapter KV: một khối lạ ở cấp gốc
# - `allowed_keys:` chẳng hạn - nạp bình thường và không ai biết nó bị bỏ qua,
# tức là người viết seed tin rằng mình vừa cấp quyền. Đúng thứ docstring module
# này lấy làm lý do tồn tại, nên nó phải được canh chứ không chỉ được nói.
KHOA_GOC: frozenset[str] = frozenset({"version", KHOI_DANH_TINH})

# Ba trường bắt buộc, đúng ba trường của `DanhTinh`. Dẫn xuất chứ không khai
# tay là để thêm một trường ở `core/` mà quên sửa loader thì hỏng ngay, thay vì
# lặng lẽ nạp thiếu.
TRUONG_BAT_BUOC: tuple[str, ...] = tuple(DanhTinh.__dataclass_fields__)

DUONG_DAN_DANH_TINH_DEMO: Path = (
    Path(__file__).resolve().parent.parent / "config" / "danh-tinh-demo.yaml"
)


class IdentitySeedInvalid(ValueError):
    """File seed danh tính không nạp được; từ chối nạp, không chạy danh sách rỗng.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp
    (AD-8, Consistency Conventions).
    """

    code = "IDENTITY_SEED_INVALID"


def nap_danh_tinh(path: str | Path | None = None) -> tuple[DanhTinh, ...]:
    """Nạp seed thành tuple `DanhTinh`, giữ thứ tự khai trong file.

    Tuple chứ không list: seed là dữ liệu cấu hình đã chốt lúc khởi động, và
    một danh sách sửa được tại chỗ là một đường thêm tài khoản giữa lúc chạy.
    """
    duong_dan = Path(path) if path is not None else DUONG_DAN_DANH_TINH_DEMO
    try:
        van_ban = duong_dan.read_text(encoding="utf-8")
    except OSError as loi:
        raise IdentitySeedInvalid(
            f"không đọc được file danh tính {duong_dan}: {loi}"
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
            f"{duong_dan}: khóa lạ ở cấp gốc {la}: seed chỉ khai danh tính,"
            " quyền thì tra bảng chính sách theo vai"
        )
    khai = raw.get(KHOI_DANH_TINH)
    if not isinstance(khai, list) or not khai:
        raise IdentitySeedInvalid(
            f"{duong_dan}: khối `{KHOI_DANH_TINH}` phải là danh sách không rỗng"
        )

    danh_sach = []
    da_thay = set()
    for i, muc in enumerate(khai):
        cho = f"{duong_dan}: danh tính thứ {i + 1}"
        if not isinstance(muc, dict):
            raise IdentitySeedInvalid(f"{cho} không phải một khối ánh xạ")
        thieu = [t for t in TRUONG_BAT_BUOC if t not in muc]
        if thieu:
            raise IdentitySeedInvalid(f"{cho} thiếu trường bắt buộc {thieu}")
        thua = [t for t in muc if t not in TRUONG_BAT_BUOC]
        if thua:
            raise IdentitySeedInvalid(
                f"{cho} khai trường lạ {thua}: seed chỉ khai danh tính, quyền"
                " thì tra bảng chính sách theo vai"
            )
        try:
            danh_tinh = DanhTinh(**muc)
        except (TypeError, ValueError) as loi:
            raise IdentitySeedInvalid(f"{cho}: {loi}") from None
        if danh_tinh.tai_khoan in da_thay:
            raise IdentitySeedInvalid(
                f"{cho}: tài khoản {danh_tinh.tai_khoan!r} khai hai lần, một"
                " tài khoản hai vai là hai câu trả lời cho cùng một người hỏi"
            )
        da_thay.add(danh_tinh.tai_khoan)
        danh_sach.append(danh_tinh)
    return tuple(danh_sach)
