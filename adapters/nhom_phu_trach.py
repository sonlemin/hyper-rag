"""Nạp bảng nhóm phụ trách từ file YAML (story 3.1, FR-14, ADR-011).

Cùng khuôn với `adapters/sensitivity_loader.py` và cùng lý do: đọc bytes, băm
sha256 thành phiên bản, parse YAML bằng loader từ chối khóa trùng, và mọi cách
hỏng cho **một** loại lỗi kèm tên file và tên mục. Người vận hành chỉ cần bắt
một exception và đọc một thông điệp.

Bảng này chỉ đặt tên cho một dấu che. Nó **không** là một trục quyền: quyền vẫn
là vai × loại nội dung × scope (AD-4), và tên nhóm không bao giờ vào khóa lọc.
Vì thế nó không sống trong `config/policy-*.yaml` và không đi qua `core/policy.py`.

Đặt ở `adapters/` chứ không ở `api/` vì nơi tra bảng là adapter graph - chỗ duy
nhất biết khóa hyperedge của một bản ghi trước khi gọi tầng che - và `eval/`
cũng phải đọc được nó mà không import `api/`. `core/` thì không đọc file (AD-1),
nên nửa I/O nằm ở đây và nửa hàm thuần (`dau_che_owner`) ở `core/masking.py`.

**Đối chiếu với bảng hạng độ nhạy.** Một loại nội dung khai ở đây mà không có
trong `config/hang-do-nhay.yaml` là một hàng không bao giờ tra trúng: dấu che
vẫn rơi về `[owner:group]` và không ai biết vì sao. Chiều ngược lại không bắt
buộc - loại chưa khai nhóm rơi về hằng cũ, đúng hành vi trước story 3.1.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

from adapters.sensitivity_loader import (
    SensitivityRanksInvalid,
    bang_hang_mac_dinh,
)
from core.ids import normalize_id

# File chốt của repo. Cùng luật "cấu hình đóng băng của hệ" với bảng hạng: hai
# môi trường hai bảng nhóm là hai hệ nói hai tên nhóm cho cùng một tài liệu.
DUONG_DAN_MAC_DINH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "nhom-phu-trach.yaml"
)

# Lược đồ đóng của file, cùng lý do với `KHOA_GOC` của bảng hạng: một khóa gõ
# thiếu một chữ mà file vẫn nạp được nghĩa là bảng rỗng chạy tiếp.
KHOI_NHOM: str = "nhom"
KHOA_GOC: frozenset[str] = frozenset({"version", KHOI_NHOM})
VERSION_HO_TRO: int = 1

# Ký tự cấm trong tên nhóm. Dấu che dựng bằng `[owner:{nhóm}]` và được nhận
# diện bằng cách **dựng lại** (`core.masking.la_dau_che`), nên một tên mang dấu
# ngoặc vuông hay dấu hai chấm làm hai luật đọc ngược nhau - và `[` còn là ký tự
# mà `la_dau_che` cố ý *không* dùng để nhận diện.
KY_TU_CAM: tuple[str, ...] = ("[", "]", ":")


class NhomPhuTrachInvalid(ValueError):
    """File nhóm phụ trách không nạp được thành một bảng hợp lệ.

    Một loại lỗi cho mọi cách hỏng - file thiếu, YAML sai, khóa gốc lạ, version
    sai, loại nội dung không có hạng, tên nhóm rỗng hay mang ký tự cấm - vì
    phản ứng đúng cho tất cả là như nhau: sửa file rồi chạy lại, không nạp gì.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).
    """

    code = "NHOM_PHU_TRACH_INVALID"


class _KhongTrungKhoa(yaml.SafeLoader):
    """SafeLoader từ chối khóa trùng trong cùng một khối ánh xạ.

    Mặc định của YAML là lấy bản cuối. Khai `runbook` hai lần nghĩa là một tên
    nhóm biến mất im lặng, và tên nhóm là thứ đi thẳng vào ngữ cảnh gửi LLM.
    """


def _mapping_khong_trung(loader, node, deep=False):
    da_thay = set()
    for khoa_node, _ in node.value:
        khoa = loader.construct_object(khoa_node, deep=deep)
        if khoa in da_thay:
            raise yaml.constructor.ConstructorError(
                "khi nạp bảng nhóm phụ trách",
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
class BangNhomPhuTrach:
    """Bảng nhóm đã kiểm, bất biến, kèm phiên bản của chính file sinh ra nó.

    `version` là sha256 nội dung file nguyên trạng, cùng luật với
    `policy_version` và với bảng hạng: đổi một tên nhóm là đổi văn bản ngữ cảnh
    mà mọi vai đọc được, nên audit cần biết bảng nào đang hiệu lực.
    """

    nhom: Mapping[str, str]
    version: str

    def nhom_cua(self, content_type: str) -> str | None:
        """Tên nhóm của một loại nội dung, `None` khi bảng không khai.

        `None` chứ không phải lỗi: loại chưa khai nhóm rơi về `[owner:group]`,
        đúng hành vi trước story 3.1. Fail-closed ở đây sẽ là chặn cả một câu
        trả lời vì một hàng cấu hình còn thiếu, trong khi hằng cũ đã che đúng.
        """
        return self.nhom.get(content_type)

    @property
    def ten_nhom(self) -> frozenset[str]:
        """Tập tên nhóm phân biệt; `core.masking.la_dau_che` dựng lại từ đây."""
        return frozenset(self.nhom.values())


def tai_nhom_phu_trach(path: str | Path) -> BangNhomPhuTrach:
    """Nạp một file nhóm phụ trách thành `BangNhomPhuTrach` đã kiểm."""
    duong_dan = Path(path)
    try:
        noi_dung = duong_dan.read_bytes()
    except OSError as loi:
        raise NhomPhuTrachInvalid(
            f"không đọc được file nhóm phụ trách {duong_dan}: {loi}"
        ) from None
    version = hashlib.sha256(noi_dung).hexdigest()
    try:
        van_ban = noi_dung.decode("utf-8")
    except UnicodeDecodeError as loi:
        raise NhomPhuTrachInvalid(
            f"file nhóm phụ trách {duong_dan} không phải UTF-8: {loi}"
        ) from None
    try:
        raw = yaml.load(van_ban, Loader=_KhongTrungKhoa)
    except yaml.YAMLError as loi:
        raise NhomPhuTrachInvalid(
            f"YAML hỏng ở {duong_dan}: {str(loi).replace(chr(10), ' ')}"
        ) from loi
    try:
        return BangNhomPhuTrach(nhom=_kiem(raw), version=version)
    except NhomPhuTrachInvalid as loi:
        raise NhomPhuTrachInvalid(f"{duong_dan}: {loi}") from None


def _kiem(raw) -> Mapping[str, str]:
    """Kiểm lược đồ rồi trả bảng bất biến; mọi lỗi là `NhomPhuTrachInvalid`."""
    if not isinstance(raw, dict):
        raise NhomPhuTrachInvalid(
            f"gốc file phải là một bảng, nhận được {type(raw).__name__}"
        )
    la = set(raw) - KHOA_GOC
    if la:
        raise NhomPhuTrachInvalid(f"khóa lạ ở cấp gốc: {sorted(la)}")
    if raw.get("version") != VERSION_HO_TRO or isinstance(raw.get("version"), bool):
        raise NhomPhuTrachInvalid(
            f"version phải là {VERSION_HO_TRO}, nhận được {raw.get('version')!r}"
        )
    khai = raw.get(KHOI_NHOM)
    if not isinstance(khai, dict) or not khai:
        raise NhomPhuTrachInvalid(
            f"`{KHOI_NHOM}` phải là một bảng loại nội dung -> tên nhóm và không rỗng"
        )
    # Bảng hạng hỏng thì lỗi của *nó* thoát ra ở đây, và người gọi bắt
    # `NhomPhuTrachInvalid` sẽ không thấy. Hợp đồng của module là "một loại lỗi
    # cho mọi cách hỏng", nên bọc lại kèm nguyên nhân thật thay vì để hai mã
    # lỗi cùng thoát ra từ một cửa.
    try:
        co_hang = bang_hang_mac_dinh().hang
    except SensitivityRanksInvalid as loi:
        raise NhomPhuTrachInvalid(
            f"không đối chiếu được với bảng hạng độ nhạy: {loi}"
        ) from None
    bang: dict[str, str] = {}
    for loai, ten in khai.items():
        if not isinstance(loai, str) or not loai.strip():
            raise NhomPhuTrachInvalid(f"loại nội dung {loai!r} không hợp lệ")
        loai = loai.strip()
        if loai not in co_hang:
            raise NhomPhuTrachInvalid(
                f"mục {loai!r}: loại nội dung không có trong bảng hạng độ nhạy"
                f" (đang có {sorted(co_hang)}); một hàng như vậy không bao giờ"
                " tra trúng và dấu che vẫn rơi về hằng cũ"
            )
        if not isinstance(ten, str) or not ten.strip():
            raise NhomPhuTrachInvalid(
                f"mục {loai!r}: tên nhóm {ten!r} phải là chuỗi không rỗng"
            )
        if ten != ten.strip():
            raise NhomPhuTrachInvalid(
                f"mục {loai!r}: tên nhóm {ten!r} có khoảng trắng bao quanh, nó"
                " đi nguyên văn vào dấu che nên một dấu cách là một tên khác"
            )
        cam = [k for k in KY_TU_CAM if k in ten]
        if cam:
            raise NhomPhuTrachInvalid(
                f"mục {loai!r}: tên nhóm {ten!r} chứa ký tự {cam}: dấu che"
                " `[owner:<nhóm>]` được nhận diện bằng cách dựng lại, một tên"
                " mang dấu ngoặc làm hai luật đọc ngược nhau"
            )
        # Tên nhóm phải là **điểm bất động** của `core.ids.normalize_id`. Dấu
        # che đi vào vị trí id, và `get_node` chuẩn hóa id trước khi hỏi
        # `la_dau_che`; nếu tên nhóm bị chuẩn hóa viết lại (tiếng Việt gõ dạng
        # tổ hợp NFD, hay một tên bọc dấu nháy kép) thì chuỗi dựng lại từ bảng
        # không khớp chuỗi đã chuẩn hóa, `la_dau_che` trả `False`, `get_node`
        # trả `None`, và `vendor/.../operate.py:1039` nổ `TypeError`.
        #
        # Bảng hôm nay toàn NFC nên lỗ này đang ngủ. Một hàng gõ bằng bàn phím
        # tiếng Việt dạng tổ hợp là đủ để đánh thức nó, và triệu chứng nằm cách
        # đây ba tầng.
        try:
            chuan = normalize_id(ten)
        except (TypeError, ValueError) as loi:
            raise NhomPhuTrachInvalid(f"mục {loai!r}: tên nhóm {ten!r}: {loi}") from None
        if chuan != ten:
            raise NhomPhuTrachInvalid(
                f"mục {loai!r}: tên nhóm {ten!r} bị `core.ids.normalize_id` viết"
                f" lại thành {chuan!r}. Dấu che đi vào vị trí id và `get_node`"
                " chuẩn hóa id trước khi nhận diện, nên một tên không chuẩn làm"
                " phép dựng lại không khớp và `vendor/` nổ TypeError. Viết tên"
                " ở dạng NFC, không bọc dấu nháy kép."
            )
        bang[loai] = ten
    return MappingProxyType(bang)


_MAC_DINH: BangNhomPhuTrach | None = None


def bang_nhom_mac_dinh() -> BangNhomPhuTrach:
    """Bảng nhóm của repo, nạp một lần cho mỗi tiến trình.

    Nhớ lại sau lần nạp đầu, cùng lý do với bảng hạng: sửa file giữa lúc phục
    vụ mà nửa số câu trả lời nói một tên nhóm còn nửa kia nói tên khác là một
    hệ không ai giải thích được. Đổi bảng thì khởi động lại tiến trình.
    """
    global _MAC_DINH
    if _MAC_DINH is None:
        _MAC_DINH = tai_nhom_phu_trach(DUONG_DAN_MAC_DINH)
    return _MAC_DINH


def nap_nhom(path: str | Path | None = None) -> Mapping[str, str]:
    """Bảng `loại nội dung -> tên nhóm`; mặc định là file chốt của repo."""
    if path is None:
        return bang_nhom_mac_dinh().nhom
    return tai_nhom_phu_trach(path).nhom
