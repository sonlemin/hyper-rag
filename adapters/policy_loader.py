"""Nạp bảng chính sách từ file YAML (AD-6, spine Deferred sàn T1).

Đây là nửa I/O của loader: đọc bytes, băm sha256 thành `policy_version`, parse
YAML. Phần kiểm và dựng object nằm ở `core/policy.py` để `core/` giữ nguyên
luật không I/O (AD-1).

Đặt ở `adapters/` chứ không ở `api/` vì `redteam/` và `eval/` cũng cần nạp
policy (hoán đổi 4 cấu hình đo của FR-28) mà không import được `api/`.

Mọi cách hỏng đều ra một loại lỗi: `PolicyInvalid` kèm tên file. File thiếu,
đường dẫn là thư mục, byte không phải UTF-8, YAML sai cú pháp, khóa trùng, sai
lược đồ - người vận hành chỉ cần bắt một exception và đọc một thông điệp.
"""

import hashlib
from pathlib import Path

import yaml

from core.policy import Policy, PolicyInvalid, build_policy


class _KhongTrungKhoa(yaml.SafeLoader):
    """SafeLoader từ chối khóa trùng trong cùng một khối ánh xạ.

    Mặc định của YAML là lấy bản cuối. Với bảng chính sách, khai `roles.devops`
    hai lần nghĩa là một hàng quyền biến mất im lặng - đúng kiểu lỗi mà FR-09
    không cho phép chạy tiếp.
    """


def _mapping_khong_trung(loader, node, deep=False):
    da_thay = set()
    for khoa_node, _ in node.value:
        khoa = loader.construct_object(khoa_node, deep=deep)
        if khoa in da_thay:
            raise yaml.constructor.ConstructorError(
                "khi nạp bảng chính sách",
                node.start_mark,
                f"khóa trùng {khoa!r}",
                khoa_node.start_mark,
            )
        da_thay.add(khoa)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_KhongTrungKhoa.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_khong_trung
)


def load_policy(path: str | Path) -> Policy:
    """Nạp một file policy YAML thành `Policy` đã kiểm.

    `policy_version` = sha256 nội dung file nguyên trạng, tính trước khi parse:
    hai file khác nhau một dấu cách vẫn là hai phiên bản chính sách khác nhau,
    và cache offline gắn theo nó (AD-9) không bị lẫn.
    """
    duong_dan = Path(path)
    try:
        noi_dung = duong_dan.read_bytes()
    except OSError as loi:
        raise PolicyInvalid(f"không đọc được file chính sách {duong_dan}: {loi}") from None
    policy_version = hashlib.sha256(noi_dung).hexdigest()
    try:
        van_ban = noi_dung.decode("utf-8")
    except UnicodeDecodeError as loi:
        raise PolicyInvalid(f"file chính sách {duong_dan} không phải UTF-8: {loi}") from None
    try:
        raw = yaml.load(van_ban, Loader=_KhongTrungKhoa)
    except yaml.YAMLError as loi:
        raise PolicyInvalid(
            f"YAML hỏng ở {duong_dan}: {str(loi).replace(chr(10), ' ')}"
        ) from loi
    try:
        return build_policy(raw, policy_version=policy_version)
    except PolicyInvalid as loi:
        raise PolicyInvalid(f"{duong_dan}: {loi}") from None
