"""Nạp bảng chính sách từ file YAML (AD-6, spine Deferred sàn T1).

Đây là nửa I/O của loader: đọc bytes, băm sha256 thành `policy_version`, parse
YAML. Phần kiểm và dựng object nằm ở `core/policy.py` để `core/` giữ nguyên
luật không I/O (AD-1).

Đặt ở `adapters/` chứ không ở `api/` vì `redteam/` và `eval/` cũng cần nạp
policy (hoán đổi 4 cấu hình đo của FR-28) mà không import được `api/`.

Mọi cách hỏng đều ra một loại lỗi: `PolicyInvalid` kèm tên file. File thiếu,
đường dẫn là thư mục, byte không phải UTF-8, YAML sai cú pháp, khóa trùng, sai
lược đồ - người vận hành chỉ cần bắt một exception và đọc một thông điệp.

Từ story 3.2 đây cũng là chỗ **ghép bảng hạng độ nhạy** vào lời gọi
`build_policy`: `core/` không đọc file nên validator đơn điệu của AD-5 nhận
bảng hạng qua tham số, và cửa duy nhất truyền nó vào là hàm này. Vắng tham số
thì dùng bảng chốt của repo (`config/hang-do-nhay.yaml`) chứ **không** bỏ qua
phép kiểm: một validator tắt được bằng cách quên một tham số là một validator
không canh gì. Bảng hạng hỏng cũng ra `PolicyInvalid`, kèm nguyên văn lý do của
loader hạng - nơi gọi vẫn chỉ phải bắt một exception.

Story 3.2 cũng đặt **cách gọi tên một bảng chính sách** ở đây: hình dạng id và
phép quét `config/policy-*.yaml`. Hai nơi tiêu thụ chúng là `api/chinh_sach.py`
(danh mục đóng của endpoint hoán policy) và `eval/bo_vang.py` (luật phủ loại nội
dung quét cả bốn cấu hình đo); `eval/` không import được `api/` nên module này là
nhà chung duy nhất, và nó vốn đã sở hữu toàn bộ I/O của file policy. Để regex
sống riêng ở `api/` thì một `config/policy-Thu Nghiem.yaml` bị luật phủ bắt tuân
thủ trong khi API không bao giờ hoán sang được - hai định nghĩa "một bảng chính
sách" cho hai câu trả lời khác nhau.
"""

import hashlib
import re
from pathlib import Path
from typing import Mapping

import yaml

from adapters.sensitivity_loader import SensitivityRanksInvalid, bang_hang_mac_dinh
from core.policy import Policy, PolicyInvalid, build_policy

# Thư mục cấu hình chốt của repo, cùng luật với `sensitivity_loader`.
THU_MUC_CAU_HINH: Path = Path(__file__).resolve().parent.parent / "config"

# Tên file là `policy-<id>.yaml`; id là phần giữa. Một chỗ dựng và một chỗ tách,
# để danh mục và đường dẫn không thể lệch nhau.
TIEN_TO: str = "policy-"
DUOI: str = ".yaml"
GLOB_POLICY: str = TIEN_TO + "*" + DUOI

# Id hợp lệ về hình dạng: chữ thường, số và dấu nối. Kiểm hình dạng **trước** khi
# tra danh mục để một chuỗi như `../../etc/passwd` không bao giờ đi tới một phép
# ghép đường dẫn, kể cả nếu danh mục có lúc nào đó được dựng theo cách khác.
HINH_DANG_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def la_id_policy(ma) -> bool:
    """Chuỗi có phải một id bảng chính sách hợp lệ về hình dạng hay không."""
    return isinstance(ma, str) and bool(HINH_DANG_ID.match(ma))


def cac_bang_chinh_sach(thu_muc: str | Path | None = None) -> dict[str, Path]:
    """Danh mục id -> đường dẫn của mọi `policy-<id>.yaml` trong một thư mục.

    Quét chứ không liệt kê tên: FR-28 đòi bốn cấu hình đo, và một danh sách viết
    tay để bảng thứ ba, thứ tư lọt lưới đúng vào lúc chúng mới nhất. File có tên
    không đúng hình dạng id bị **bỏ qua** ở cả hai nơi tiêu thụ cùng lúc, nên
    không có ca "luật phủ bắt tuân thủ mà API không hoán sang được".

    Quét mỗi lần gọi chứ không cache: thêm một file cấu hình đo thứ năm phải có
    hiệu lực mà không phải khởi động lại tiến trình, và phép quét một thư mục
    bốn file rẻ hơn mọi thứ nó thay thế.
    """
    goc = Path(thu_muc) if thu_muc is not None else THU_MUC_CAU_HINH
    ra: dict[str, Path] = {}
    for duong_dan in sorted(goc.glob(GLOB_POLICY)):
        ma = duong_dan.name[len(TIEN_TO) : -len(DUOI)]
        if la_id_policy(ma):
            ra[ma] = duong_dan
    return ra


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


def load_policy(path: str | Path, *, hang: Mapping[str, int] | None = None) -> Policy:
    """Nạp một file policy YAML thành `Policy` đã kiểm.

    `policy_version` = sha256 nội dung file nguyên trạng, tính trước khi parse:
    hai file khác nhau một dấu cách vẫn là hai phiên bản chính sách khác nhau,
    và cache offline gắn theo nó (AD-9) không bị lẫn.

    `hang` là bảng hạng độ nhạy mà validator đơn điệu chấm trên; `None` là bảng
    chốt của repo. Tham số có mặt để bộ test dựng được một bảng chính sách nhỏ
    trên một bảng hạng nhỏ - hệ chạy thật chỉ có một bảng hạng, và nó là file
    đóng băng trước ingest.
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
    if hang is None:
        try:
            hang = bang_hang_mac_dinh().hang
        except SensitivityRanksInvalid as loi:
            raise PolicyInvalid(
                f"không nạp được bảng hạng độ nhạy để kiểm {duong_dan}: {loi}"
            ) from None
    try:
        return build_policy(raw, policy_version=policy_version, hang=hang)
    except PolicyInvalid as loi:
        raise PolicyInvalid(f"{duong_dan}: {loi}") from None
