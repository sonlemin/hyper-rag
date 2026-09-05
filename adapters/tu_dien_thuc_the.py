"""Nạp từ điển thực thể chuẩn theo scope từ file YAML (story 2.12, FR-32).

Id entity băm nguyên văn giá trị slot, nên `App01` và `app01.company.vn` là hai
node và đồ thị vỡ vụn theo cách viết. Từ điển ở đây là bảng gộp bí danh về tên
chuẩn: nó đi vào prompt trích xuất như một gợi ý, và - phần kiểm được - được áp
tất định lên giá trị slot bằng `core.facts.ap_bi_danh` ngay trước `id_fact`.

Cùng khuôn với `adapters/sensitivity_loader.py`: đọc bytes, băm sha256 thành
phiên bản, parse YAML bằng loader từ chối khóa trùng, và **một** loại lỗi cho
mọi cách hỏng kèm tên file. Khác nó ba chỗ, và cả ba là quyết định:

- **Không có file mặc định.** Khóa cấu hình vắng nghĩa là *không có từ điển*,
  và đường trích xuất chạy y hệt hôm nay - không khối từ điển trong prompt,
  `ap_bi_danh` nhận bảng rỗng và thành hàm đồng nhất. Bảng hạng độ nhạy thì
  ngược lại: nó là cấu hình đóng băng của hệ nên vắng khóa là dùng file chốt của
  repo. Một từ điển mặc định ngầm là một phép gộp thực thể mà không ai khai.
- **Ràng theo scope.** Một mục chỉ áp cho tài liệu đúng scope của nó, hoặc
  `SCOPE_CHUNG` cho thuật ngữ dùng chung. Gộp `web01` của khách hàng A với
  `web01` của khách hàng B là hỏng đúng chỗ mà tỷ lệ Composition-Risk đo: hai
  khoang thuê bao khác nhau bỗng chia chung một id entity.
- **Mọi mục đòi dấu người xác nhận.** Bảng do LLM đề xuất đi vào
  `eval/de_xuat/<space>.yaml` (công cụ `eval/de_xuat_bi_danh.py`), và không có
  đường nào để một đề xuất tự chảy vào từ điển đang chạy. Mục thiếu `xac_nhan`
  là từ chối cả file, không phải bỏ qua một mục.

Ba phép từ chối về cấu trúc, ngoài phần lược đồ thường:

1. **Một bí danh hai tên chuẩn** trong cùng vùng áp dụng. Bảng khi đó không phải
   một hàm, và kết quả phụ thuộc thứ tự duyệt.
2. **Bí danh cũng là tên chuẩn** của một mục khác. `ap_bi_danh` áp đúng một
   bước, nên một chuỗi hai bước cho ra kết quả nửa vời; và một bảng do người sửa
   dần sẽ có ngày tạo vòng lặp mà không ai thấy.
3. **Bí danh trùng chính tên chuẩn của mục mình.** Đó là ca riêng của (2), cùng
   một luật bắt được.

Đặt ở `adapters/` chứ không `core/` vì nó đọc file và parse YAML; luật *áp*
bảng thì ở `core.facts.ap_bi_danh`, hàm thuần, và đó là chỗ test chấm.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

from core.facts import GIA_TRI_TOI_DA, chuan_hoa_gia_tri
from core.keys import KEY_SEPARATOR

# Khóa cấu hình đọc từ `global_config` (upstream truyền `asdict(EngineACL)`).
# Vắng hoặc rỗng nghĩa là **không có từ điển**, không phải "dùng file mặc định".
ENTITY_DICTIONARY_KEY = "entity_dictionary_path"

# Scope đặc biệt: mục áp cho **mọi** tài liệu, dành cho thuật ngữ chung (tên
# công nghệ, tên bộ phận nội bộ). Không phải một wildcard tổng quát: chỉ đúng
# chuỗi này, và nó không hợp lệ làm scope thật vì `core.ids.validate_space` và
# `core.keys.filter_key` đều không sinh ra nó.
SCOPE_CHUNG: str = "*"

# Lược đồ đóng, cả ở gốc lẫn ở từng mục. Khóa lạ bị từ chối: một `bi_danh:` viết
# thành `bidanh:` mà file vẫn nạp được nghĩa là một mục im lặng không gộp gì.
KHOA_GOC: frozenset[str] = frozenset({"version", "muc"})
KHOA_MUC: frozenset[str] = frozenset({"chuan", "scope", "bi_danh", "xac_nhan"})
VERSION_HO_TRO: int = 1


class TuDienThucTheInvalid(ValueError):
    """File từ điển thực thể không nạp được thành một bảng hợp lệ.

    Một loại lỗi cho mọi cách hỏng - file thiếu, không phải UTF-8, YAML sai cú
    pháp, khóa trùng, mục thiếu `xac_nhan`, bí danh xung đột, chuỗi áp nhiều
    bước - vì phản ứng đúng cho tất cả là như nhau: sửa file rồi chạy lại, không
    nạp gì cả. Cùng luật với `SensitivityRanksInvalid`.

    Thông điệp **luôn nêu tên mục** gây lỗi: một từ điển vài trăm dòng do người
    sửa dần thì "có xung đột" mà không nói ở đâu là một thông điệp không dùng
    được.

    `code` ổn định để test assert trên `code` (AD-8).
    """

    code = "TU_DIEN_THUC_THE_INVALID"


class _KhongTrungKhoa(yaml.SafeLoader):
    """SafeLoader từ chối khóa trùng trong cùng một khối ánh xạ.

    Mặc định của YAML là lấy bản cuối. Với từ điển, khai `chuan` hai lần trong
    một mục nghĩa là một tên chuẩn biến mất im lặng.
    """


def _mapping_khong_trung(loader, node, deep=False):
    da_thay = set()
    for khoa_node, _ in node.value:
        khoa = loader.construct_object(khoa_node, deep=deep)
        if khoa in da_thay:
            raise yaml.constructor.ConstructorError(
                "khi nạp từ điển thực thể",
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
class MucTuDien:
    """Một mục đã kiểm: tên chuẩn, scope áp dụng, bí danh, dấu người xác nhận.

    `bi_danh` giữ **bản đã chuẩn hóa** bằng `core.facts.chuan_hoa_gia_tri`, đúng
    hàm mà `kiem_fact` chạy trên giá trị slot trước khi nó tới `ap_bi_danh`. Giữ
    bản thô rồi chuẩn hóa lúc tra là hai bản dễ lệch nhau vì một dấu cách.
    """

    chuan: str
    scope: str
    bi_danh: tuple[str, ...]
    xac_nhan: str

    def ap_cho(self, scope: str | None) -> bool:
        """Mục này có áp cho tài liệu scope đó không.

        `None` (không biết scope) chỉ nhận mục `SCOPE_CHUNG`: đoán scope là gộp
        thực thể của hai khách hàng vì một chỗ gọi quên truyền nhãn.
        """
        return self.scope == SCOPE_CHUNG or self.scope == scope


@dataclass(frozen=True)
class TuDienThucThe:
    """Từ điển đã kiểm, bất biến, kèm phiên bản của chính file sinh ra nó.

    `version` là sha256 nội dung file nguyên trạng, cùng luật với
    `policy_version` và với bảng hạng độ nhạy: đổi từ điển là đổi id entity và
    id hyperedge, tức re-ingest, nên biết một mục được nạp bằng từ điển nào là
    điều kiện để biết mục nào phải nạp lại.
    """

    muc: tuple[MucTuDien, ...]
    version: str

    def bang_cho_scope(self, scope: str | None) -> Mapping[str, str]:
        """`{bí danh đã chuẩn hóa: tên chuẩn}` cho đúng một scope.

        Đây là thứ đi vào `core.facts.ap_bi_danh`. Dựng lại mỗi lần gọi chứ
        không cache theo scope: một đợt nạp gọi nó một lần cho mỗi tài liệu, và
        một cache trên object bất biến chỉ để tiết kiệm vài chục phép ghép dict
        là một mặt trạng thái không đổi lấy gì.
        """
        bang: dict[str, str] = {}
        for m in self.muc:
            if not m.ap_cho(scope):
                continue
            for bd in m.bi_danh:
                bang[bd] = m.chuan
        return MappingProxyType(bang)

    def muc_cho_scope(self, scope: str | None) -> tuple[MucTuDien, ...]:
        """Các mục áp cho một scope, giữ thứ tự file - đầu vào của khối prompt."""
        return tuple(m for m in self.muc if m.ap_cho(scope))


def tai_tu_dien_thuc_the(path: str | Path) -> TuDienThucThe:
    """Nạp một file từ điển thực thể thành `TuDienThucThe` đã kiểm."""
    duong_dan = Path(path)
    try:
        noi_dung = duong_dan.read_bytes()
    except OSError as loi:
        raise TuDienThucTheInvalid(
            f"không đọc được file từ điển thực thể {duong_dan}: {loi}"
        ) from None
    version = hashlib.sha256(noi_dung).hexdigest()
    try:
        van_ban = noi_dung.decode("utf-8")
    except UnicodeDecodeError as loi:
        raise TuDienThucTheInvalid(
            f"file từ điển thực thể {duong_dan} không phải UTF-8: {loi}"
        ) from None
    try:
        raw = yaml.load(van_ban, Loader=_KhongTrungKhoa)
    except yaml.YAMLError as loi:
        raise TuDienThucTheInvalid(
            f"YAML hỏng ở {duong_dan}: {str(loi).replace(chr(10), ' ')}"
        ) from loi
    try:
        return TuDienThucThe(muc=_kiem(raw), version=version)
    except TuDienThucTheInvalid as loi:
        raise TuDienThucTheInvalid(f"{duong_dan}: {loi}") from None


def _chuoi(gia_tri, ten: str, o_dau: str) -> str:
    """Một trường chuỗi không rỗng, trả bản đã chuẩn hóa."""
    if not isinstance(gia_tri, str):
        raise TuDienThucTheInvalid(
            f"{o_dau}: {ten} phải là chuỗi, nhận được {type(gia_tri).__name__}"
        )
    gon = chuan_hoa_gia_tri(gia_tri)
    if not gon:
        raise TuDienThucTheInvalid(f"{o_dau}: {ten} rỗng")
    if len(gon) > GIA_TRI_TOI_DA:
        raise TuDienThucTheInvalid(
            f"{o_dau}: {ten} dài {len(gon)} ký tự, quá {GIA_TRI_TOI_DA} - một giá"
            " trị slot dài hơn thế bị `kiem_fact` loại, nên nó không bao giờ tra"
            " trúng bảng này"
        )
    return gon


def _kiem(raw) -> tuple[MucTuDien, ...]:
    """Kiểm lược đồ và ba luật cấu trúc; mọi lỗi là `TuDienThucTheInvalid`."""
    if not isinstance(raw, dict):
        raise TuDienThucTheInvalid(
            f"gốc file phải là một bảng, nhận được {type(raw).__name__}"
        )
    la = set(raw) - KHOA_GOC
    if la:
        raise TuDienThucTheInvalid(f"khóa lạ ở cấp gốc: {sorted(la)}")
    if raw.get("version") != VERSION_HO_TRO:
        raise TuDienThucTheInvalid(
            f"version phải là {VERSION_HO_TRO}, nhận được {raw.get('version')!r}"
        )
    ds = raw.get("muc")
    if not isinstance(ds, list) or not ds:
        raise TuDienThucTheInvalid("`muc` phải là một danh sách mục và không rỗng")

    muc: list[MucTuDien] = []
    for i, m in enumerate(ds):
        o_dau = f"mục #{i + 1}"
        if not isinstance(m, dict):
            raise TuDienThucTheInvalid(
                f"{o_dau} phải là một bảng, nhận được {type(m).__name__}"
            )
        thieu = KHOA_MUC - set(m)
        if thieu:
            # `xac_nhan` được nêu riêng: nó là luật của story, không phải một
            # trường quên gõ, và thông điệp phải nói ra vì sao nó bắt buộc.
            if thieu == {"xac_nhan"} or "xac_nhan" in thieu:
                ten = m.get("chuan", "(không rõ tên chuẩn)")
                raise TuDienThucTheInvalid(
                    f"{o_dau} ({ten!r}) thiếu dấu xác nhận `xac_nhan`: mọi mục"
                    " phải mang tên người xác nhận kèm ngày. Bảng do LLM đề xuất"
                    " nằm ở `eval/de_xuat/<space>.yaml` và không có đường nào tự"
                    " chảy vào từ điển đang chạy"
                )
            raise TuDienThucTheInvalid(f"{o_dau} thiếu khóa {sorted(thieu)}")
        la_muc = set(m) - KHOA_MUC
        if la_muc:
            raise TuDienThucTheInvalid(f"{o_dau} có khóa lạ: {sorted(la_muc)}")

        chuan = _chuoi(m["chuan"], "chuan", o_dau)
        o_dau = f"mục #{i + 1} ({chuan!r})"
        scope = _chuoi(m["scope"], "scope", o_dau)
        if scope != SCOPE_CHUNG and KEY_SEPARATOR in scope:
            raise TuDienThucTheInvalid(
                f"{o_dau}: scope {scope!r} chứa dấu phân tách {KEY_SEPARATOR!r}:"
                " nó không bao giờ khớp scope tách từ khóa lọc"
            )
        _chuoi(m["xac_nhan"], "xac_nhan", o_dau)

        bi_danh_raw = m["bi_danh"]
        if not isinstance(bi_danh_raw, list) or not bi_danh_raw:
            raise TuDienThucTheInvalid(
                f"{o_dau}: `bi_danh` phải là một danh sách và không rỗng - một mục"
                " không bí danh nào không gộp gì"
            )
        bi_danh: list[str] = []
        for bd in bi_danh_raw:
            gon = _chuoi(bd, "bí danh", o_dau)
            if gon in bi_danh:
                raise TuDienThucTheInvalid(f"{o_dau}: bí danh {gon!r} khai hai lần")
            bi_danh.append(gon)
        muc.append(
            MucTuDien(
                chuan=chuan,
                scope=scope,
                bi_danh=tuple(bi_danh),
                xac_nhan=chuan_hoa_gia_tri(m["xac_nhan"]),
            )
        )

    _kiem_khong_xung_dot(muc)
    _kiem_khong_ap_nhieu_buoc(muc)
    return tuple(muc)


def _giao_scope(a: MucTuDien, b: MucTuDien) -> bool:
    """Hai mục có cùng áp cho ít nhất một tài liệu không.

    `SCOPE_CHUNG` giao với mọi scope, nên một mục chung xung đột với một mục của
    `khach_hang_a` dù hai chuỗi scope khác nhau. Bỏ qua điều đó là để hai mục
    mâu thuẫn cùng áp lên một tài liệu và kết quả phụ thuộc thứ tự duyệt.
    """
    return (
        a.scope == b.scope or a.scope == SCOPE_CHUNG or b.scope == SCOPE_CHUNG
    )


def _kiem_khong_xung_dot(muc: list[MucTuDien]) -> None:
    """Một bí danh không được trỏ về hai tên chuẩn trong cùng vùng áp dụng."""
    for i, a in enumerate(muc):
        for b in muc[i + 1 :]:
            if a.chuan == b.chuan or not _giao_scope(a, b):
                continue
            chung = sorted(set(a.bi_danh) & set(b.bi_danh))
            if chung:
                raise TuDienThucTheInvalid(
                    f"bí danh {chung} trỏ về hai tên chuẩn {a.chuan!r}"
                    f" (scope {a.scope!r}) và {b.chuan!r} (scope {b.scope!r}):"
                    " bảng không còn là một hàm, và kết quả sẽ phụ thuộc thứ tự"
                    " duyệt"
                )


def _kiem_khong_ap_nhieu_buoc(muc: list[MucTuDien]) -> None:
    """Không tên chuẩn nào được là bí danh của một mục cùng vùng áp dụng.

    Bắt luôn ca một mục lấy chính tên chuẩn của mình làm bí danh: đó là cùng một
    hình dạng (`chuan` xuất hiện trong `bi_danh`), chỉ khác chỗ nó vô hại. Cấm
    cả hai vì một luật đọc được đáng hơn một luật có ngoại lệ vô hại.
    """
    for a in muc:
        for b in muc:
            if not _giao_scope(a, b):
                continue
            if a.chuan in b.bi_danh:
                raise TuDienThucTheInvalid(
                    f"tên chuẩn {a.chuan!r} (scope {a.scope!r}) cũng là bí danh"
                    f" của mục {b.chuan!r} (scope {b.scope!r}): phép áp chỉ chạy"
                    " đúng một bước, nên chuỗi này cho một kết quả nửa vời và phụ"
                    " thuộc thứ tự duyệt"
                )


# Bộ nhớ theo đường dẫn, một lần mỗi tiến trình. Cùng ngữ nghĩa "đóng băng
# trước ingest" với `sensitivity_loader.bang_hang_mac_dinh`: sửa file giữa một
# đợt nạp mà nửa đầu gộp bí danh bằng bảng cũ, nửa sau bằng bảng mới, là một kho
# không ai giải thích được. Nó cũng là phép vá cho một chuyện tầm thường hơn:
# `trich_xuat_chunks` chạy **một lần mỗi tài liệu**, nên không có bộ nhớ này thì
# một đợt 50 tài liệu đọc và parse lại cùng một file YAML 50 lần.
_DA_NAP: dict[str, TuDienThucThe] = {}


def tu_dien_cho(cau_hinh: Mapping | None) -> TuDienThucThe | None:
    """Từ điển mà đường trích xuất dùng, suy từ `global_config`.

    Cửa chung, cùng hình dạng với `adapters.sensitivity_loader.bang_hang_cho` -
    khác hai chỗ: khóa vắng trả `None` (tức **không có từ điển**, không có mặc
    định ngầm), và kết quả được nhớ lại theo đường dẫn cho cả tiến trình.
    """
    duong_dan = (cau_hinh or {}).get(ENTITY_DICTIONARY_KEY)
    if not duong_dan:
        return None
    khoa = str(duong_dan)
    if khoa not in _DA_NAP:
        _DA_NAP[khoa] = tai_tu_dien_thuc_the(duong_dan)
    return _DA_NAP[khoa]


def quen_tu_dien_da_nap() -> None:
    """Xóa bộ nhớ; chỉ cho bộ test, nơi mỗi ca viết một file khác cùng tên."""
    _DA_NAP.clear()
