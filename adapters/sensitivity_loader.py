"""Nạp bảng hạng độ nhạy từ file YAML (story 2.1, FR-11).

Cùng khuôn với `adapters/policy_loader.py` và cùng lý do: đọc bytes, băm sha256
thành phiên bản, parse YAML, từ chối khóa trùng, và mọi cách hỏng cho **một**
loại lỗi kèm tên file. Người vận hành chỉ cần bắt một exception và đọc một
thông điệp.

Khác `policy_loader` một chỗ: phần kiểm nằm ngay ở đây chứ không ở `core/`.
Bảng hạng là một map `loại nội dung -> số nguyên`, không có cấu trúc nào để
`core/` phải dựng thành object; thứ `core/` cần là chính map đó
(`core.keys.hop_nhat_khoa` nhận nó làm tham số). Dựng một `build_*` trong
`core/` chỉ để chuyển tiếp một dict là thêm một tầng không trả lời câu hỏi nào.

Đặt ở `adapters/` chứ không ở `api/` vì cả ba adapter kho đều cần bảng này ở
đường ghi, và `eval/` cũng phải nạp được nó mà không import `api/`.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

from core.keys import KEY_SEPARATOR, SensitivityRankUnknown

# File chốt của repo. Adapter không cấu hình đường dẫn thì dùng đúng file này:
# hạng độ nhạy là cấu hình đóng băng của *hệ*, không phải một knob mỗi môi
# trường tự đặt một kiểu (hai môi trường hai bảng hạng là hai kho không so được
# với nhau và không re-ingest chung được).
DUONG_DAN_MAC_DINH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "hang-do-nhay.yaml"
)

# Khóa cấu hình đọc từ `global_config` (upstream truyền `asdict(HyperGraphRAG)`).
# Vắng thì rơi về `DUONG_DAN_MAC_DINH`.
SENSITIVITY_RANKS_KEY = "sensitivity_ranks_path"

# Lược đồ đóng của file. Khóa lạ ở cấp gốc bị từ chối: một `rank:` viết thiếu
# chữ `s` mà file vẫn nạp được nghĩa là bảng rỗng chạy tiếp.
KHOA_GOC: frozenset[str] = frozenset({"version", "ranks"})
VERSION_HO_TRO: int = 1


class SensitivityRanksInvalid(ValueError):
    """File hạng độ nhạy không nạp được thành một bảng hợp lệ.

    Một loại lỗi cho mọi cách hỏng - file thiếu, không phải UTF-8, YAML sai cú
    pháp, khóa trùng, hạng không phải số nguyên, hai loại cùng hạng - vì phản
    ứng đúng cho tất cả là như nhau: sửa file rồi chạy lại, không nạp gì cả.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).
    """

    code = "SENSITIVITY_RANKS_INVALID"


class _KhongTrungKhoa(yaml.SafeLoader):
    """SafeLoader từ chối khóa trùng trong cùng một khối ánh xạ.

    Mặc định của YAML là lấy bản cuối. Với bảng hạng, khai `runbook` hai lần
    nghĩa là một hạng biến mất im lặng, và hạng là thứ quyết định khóa quyền
    của mọi artifact đa nguồn.
    """


def _mapping_khong_trung(loader, node, deep=False):
    da_thay = set()
    for khoa_node, _ in node.value:
        khoa = loader.construct_object(khoa_node, deep=deep)
        if khoa in da_thay:
            raise yaml.constructor.ConstructorError(
                "khi nạp bảng hạng độ nhạy",
                node.start_mark,
                f"khóa trùng {khoa!r}",
                khoa_node.start_mark,
            )
        da_thay.add(khoa)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_KhongTrungKhoa.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_khong_trung
)


@dataclass(frozen=True)
class BangHangDoNhay:
    """Bảng hạng đã kiểm, bất biến, kèm phiên bản của chính file sinh ra nó.

    `version` là sha256 nội dung file nguyên trạng, cùng luật với
    `policy_version`: hai file khác nhau một dấu cách là hai bảng hạng khác
    nhau. Nó có mặt để audit ghi được bảng nào đang hiệu lực lúc nạp - đổi hạng
    là re-ingest, nên biết một mục được tính khóa bằng bảng nào là điều kiện để
    biết mục nào phải nạp lại.
    """

    hang: Mapping[str, int]
    version: str

    def hang_cua(self, content_type: str) -> int:
        """Hạng của một loại nội dung; lạ thì cùng mã lỗi với hàm hợp nhất."""
        if content_type not in self.hang:
            raise SensitivityRankUnknown(
                f"loại nội dung {content_type!r} không có hạng độ nhạy trong"
                f" bảng cấu hình (đang có {sorted(self.hang)})"
            )
        return self.hang[content_type]


def tai_hang_do_nhay(path: str | Path) -> BangHangDoNhay:
    """Nạp một file hạng độ nhạy thành `BangHangDoNhay` đã kiểm."""
    duong_dan = Path(path)
    try:
        noi_dung = duong_dan.read_bytes()
    except OSError as loi:
        raise SensitivityRanksInvalid(
            f"không đọc được file hạng độ nhạy {duong_dan}: {loi}"
        ) from None
    version = hashlib.sha256(noi_dung).hexdigest()
    try:
        van_ban = noi_dung.decode("utf-8")
    except UnicodeDecodeError as loi:
        raise SensitivityRanksInvalid(
            f"file hạng độ nhạy {duong_dan} không phải UTF-8: {loi}"
        ) from None
    try:
        raw = yaml.load(van_ban, Loader=_KhongTrungKhoa)
    except yaml.YAMLError as loi:
        raise SensitivityRanksInvalid(
            f"YAML hỏng ở {duong_dan}: {str(loi).replace(chr(10), ' ')}"
        ) from loi
    try:
        return BangHangDoNhay(hang=_kiem(raw), version=version)
    except SensitivityRanksInvalid as loi:
        raise SensitivityRanksInvalid(f"{duong_dan}: {loi}") from None


def _kiem(raw) -> Mapping[str, int]:
    """Kiểm lược đồ rồi trả bảng bất biến; mọi lỗi là `SensitivityRanksInvalid`."""
    if not isinstance(raw, dict):
        raise SensitivityRanksInvalid(
            f"gốc file phải là một bảng, nhận được {type(raw).__name__}"
        )
    la = set(raw) - KHOA_GOC
    if la:
        raise SensitivityRanksInvalid(f"khóa lạ ở cấp gốc: {sorted(la)}")
    if raw.get("version") != VERSION_HO_TRO:
        raise SensitivityRanksInvalid(
            f"version phải là {VERSION_HO_TRO}, nhận được {raw.get('version')!r}"
        )
    ranks = raw.get("ranks")
    if not isinstance(ranks, dict) or not ranks:
        raise SensitivityRanksInvalid(
            "`ranks` phải là một bảng loại nội dung -> số nguyên và không rỗng"
        )
    hang: dict[str, int] = {}
    for loai, so in ranks.items():
        if not isinstance(loai, str) or not loai.strip():
            raise SensitivityRanksInvalid(f"loại nội dung {loai!r} không hợp lệ")
        if KEY_SEPARATOR in loai:
            raise SensitivityRanksInvalid(
                f"loại nội dung {loai!r} chứa dấu phân tách {KEY_SEPARATOR!r}:"
                " khóa lọc sẽ tách sai và hạng tra trượt"
            )
        # `bool` là con của `int` trong Python, và `runbook: true` thành hạng 1
        # là một bảng chạy được mà không ai định khai như vậy.
        if isinstance(so, bool) or not isinstance(so, int):
            raise SensitivityRanksInvalid(
                f"hạng của {loai!r} phải là số nguyên, nhận được {so!r}"
            )
        hang[loai.strip()] = so
    trung = [so for so in set(hang.values()) if list(hang.values()).count(so) > 1]
    if trung:
        cung_hang = sorted(loai for loai, so in hang.items() if so in trung)
        raise SensitivityRanksInvalid(
            f"các loại nội dung {cung_hang} cùng hạng: 'hạn chế nhất' không xác"
            " định được, nên bảng phải cấm chứ không để hàm hợp nhất chọn bừa"
        )
    return MappingProxyType(hang)


_MAC_DINH: BangHangDoNhay | None = None


def bang_hang_mac_dinh() -> BangHangDoNhay:
    """Bảng hạng của repo, nạp một lần cho mỗi tiến trình.

    Nhớ lại sau lần nạp đầu là đúng ngữ nghĩa "đóng băng trước ingest": sửa file
    giữa một đợt nạp mà nửa đầu tính khóa bằng bảng cũ, nửa sau bằng bảng mới,
    là một kho không ai giải thích được. Đổi bảng thì khởi động lại tiến trình,
    và đổi hạng thì re-ingest.
    """
    global _MAC_DINH
    if _MAC_DINH is None:
        _MAC_DINH = tai_hang_do_nhay(DUONG_DAN_MAC_DINH)
    return _MAC_DINH


def bang_hang_cho(cau_hinh: Mapping | None) -> BangHangDoNhay:
    """Bảng hạng mà một adapter dùng, suy từ `global_config` của nó.

    Cửa chung của cả ba adapter: khóa cấu hình vắng thì dùng bảng chốt của repo,
    có thì nạp file được trỏ tới. Một chỗ, để ba adapter không thể chạy trên hai
    bảng hạng khác nhau vì một cái đọc cấu hình còn cái kia thì không.
    """
    duong_dan = (cau_hinh or {}).get(SENSITIVITY_RANKS_KEY)
    if not duong_dan:
        return bang_hang_mac_dinh()
    return tai_hang_do_nhay(duong_dan)
