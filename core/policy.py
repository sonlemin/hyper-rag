"""Bảng chính sách dạng dữ liệu: kiểm và dựng object thuần (FR-09, AD-6).

Nửa I/O (đọc file, sha256, `yaml.safe_load`) nằm ở `adapters/policy_loader.py`
để `core/` giữ nguyên luật không I/O (AD-1). Module này nhận dict đã parse cộng
`policy_version` rồi kiểm từng trường và dựng `Policy` bất biến.

Schema (story 1.2 chốt, spine im lặng về tên trường)::

    version: 1
    roles:
      tech_support:
        scopes: [noi_bo]
        disclosure: {bao_cao_su_co: L1, runbook: L2}
        masked_slots: {bao_cao_su_co: [cause, source]}

Không hard-code enum vai hay enum loại nội dung: thêm vai là sửa YAML. Ba thứ
đóng: tập mức (L0/L1/L2), danh mục 8 vai slot, và `version` của chính schema.

Che là khái niệm của riêng L1 (FR-10, AD-9): `masked_slots` chỉ khai được cho
loại nội dung mà vai đó đang ở L1. L0 thì hyperedge vắng mặt hẳn nên không có
gì để che; L2 thì chỉ còn luật `owner` áp ở tầng che.

Kiểm tra được làm hết lúc nạp, không để lười: một bảng đã nạp phải là bảng chạy
được.

**Validator đơn điệu của AD-5 (story 3.2).** `build_policy` đòi một bảng hạng
độ nhạy **tiêm vào** (`core/` chỉ stdlib nên nó không đọc file nào) và kiểm ba
thứ trên bảng đó: mỗi vai khai *đúng* tập loại nội dung có hạng, mức tiết lộ
không tăng theo hạng, và tập slot bị che không giảm theo hạng trong vùng L1.
Trần 50 khóa của AD-4 chỉ là một dòng WARNING, không phải một phép từ chối.

**Vì sao đòi khai đủ mọi loại có hạng thay vì để mặc định L0 ngầm.**
`RolePolicy.level` trả L0 cho loại chưa khai, nên mức *thực tế* của một vai
luôn phủ đủ bảng hạng. Kiểm đơn điệu chỉ trên loại đã khai thì bỏ sót đúng ca
validator sinh ra để bắt: một bảng khai `cmdb: L2` mà bỏ `faq` là fail-open và
đọc như fail-closed. Khai đủ biến mặc định ngầm thành khẳng định tường minh, và
làm hai vế của AD-5 hết mâu thuẫn. Mặc định L0 của `level()` giữ nguyên làm
lưới an toàn cho loại nội dung nạp vào *sau* khi bảng được viết, nó không còn là
cách một file cấu hình phát biểu "loại này L0".
"""

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from core.keys import filter_key
from core.slots import OWNER_SLOT, POLICY_MASKABLE_SLOTS, SLOT_ROLE_SET

# Phiên bản schema mà module này hiểu. Đổi hình dạng bảng là tăng số này cùng
# lúc với code đọc nó, không để hai bên trôi dạt âm thầm.
SCHEMA_VERSION: int = 1

# Ba mức tiết lộ, đóng. Thứ tự dùng để hỏi "đạt từ mức X trở lên".
DISCLOSURE_LEVELS: tuple[str, ...] = ("L0", "L1", "L2")
LEVEL_ORDER: Mapping[str, int] = MappingProxyType(
    {muc: i for i, muc in enumerate(DISCLOSURE_LEVELS)}
)

# Mức tối thiểu để một khóa được vào tập của từng namespace vector (NFR-06).
# Chunk và mô tả entity là văn bản không che theo slot được nên chỉ vào khi vai
# đạt L2; hyperedge vào từ L1 trở lên vì nó che được từng slot.
NAMESPACE_MIN_LEVEL: Mapping[str, str] = MappingProxyType(
    {"chunks": "L2", "entities": "L2", "hyperedges": "L1"}
)
# Dẫn xuất, không khai tay: hai danh sách rời nhau là chỗ để lệch.
NAMESPACES: tuple[str, ...] = tuple(NAMESPACE_MIN_LEVEL)

# Trần khóa lọc của một vai ở một namespace (AD-4). **Cảnh báo, không từ chối:**
# vượt trần buộc đo lại recall/độ trễ trước khi tiến, và đó là một việc của
# người chạy phép đo chứ không phải một lý do để hệ không khởi động được. Đếm
# theo từng vai *và* từng namespace vì tập khóa của `chunks` hẹp hơn tập của
# `hyperedges`, và cái vượt trần là cái đi vào một filter Qdrant cụ thể.
TRAN_KHOA_MOI_VAI: int = 50

logger = logging.getLogger(__name__)


class PolicyInvalid(ValueError):
    """Bảng chính sách không nạp được. Từ chối nạp, không chạy policy rỗng."""

    code = "POLICY_INVALID"


@dataclass(frozen=True)
class RolePolicy:
    """Một hàng của bảng: vai người dùng và những gì vai đó thấy.

    `allowed_keys` tính sẵn lúc nạp (map namespace -> tập khóa), không tính lười:
    khóa hỏng phải nổ ở `build_policy` chứ không nổ giữa một request.
    """

    name: str
    scopes: tuple[str, ...]
    disclosure: Mapping[str, str]
    masked_slots: Mapping[str, frozenset[str]]
    allowed_keys: Mapping[str, frozenset[str]]

    def level(self, content_type: str) -> str:
        """Mức tiết lộ với một loại nội dung; không khai trong bảng là L0.

        Mặc định an toàn: loại nội dung mới nạp vào mà chưa ai khai chính sách
        thì vô hình, không phải mở toang.
        """
        return self.disclosure.get(content_type, "L0")


@dataclass(frozen=True)
class Policy:
    """Bảng chính sách đã kiểm, bất biến, gắn `policy_version`."""

    version: int
    policy_version: str
    roles: Mapping[str, RolePolicy]

    def role(self, name: str) -> RolePolicy:
        """Hàng của một vai; vai không có trong bảng là KeyError."""
        try:
            return self.roles[name]
        except KeyError:
            raise KeyError(f"vai {name!r} không có trong bảng chính sách") from None

    def level(self, role: str, content_type: str) -> str:
        return self.role(role).level(content_type)

    def allowed_keys(self, role: str) -> Mapping[str, frozenset[str]]:
        return self.role(role).allowed_keys

    def masked_slots(self, role: str) -> Mapping[str, frozenset[str]]:
        return self.role(role).masked_slots


def _ten(gia_tri) -> str:
    return type(gia_tri).__name__


def _mapping(gia_tri, cho: str) -> Mapping:
    if not isinstance(gia_tri, Mapping):
        raise PolicyInvalid(f"{cho} phải là một khối ánh xạ, nhận được {_ten(gia_tri)}")
    return gia_tri


def _chuoi_khong_rong(gia_tri, cho: str) -> str:
    """Trả bản đã cắt khoảng trắng; sai kiểu hoặc rỗng là `PolicyInvalid`.

    Cắt khoảng trắng ngay tại cửa nạp để giá trị trong bảng và giá trị đi vào
    khóa lọc là một chuỗi duy nhất, không phải hai bản lệch một dấu cách.
    """
    if not isinstance(gia_tri, str):
        raise PolicyInvalid(f"{cho} phải là chuỗi, nhận được {_ten(gia_tri)}")
    gon = gia_tri.strip()
    if not gon:
        raise PolicyInvalid(f"{cho} rỗng")
    return gon


def _scopes(raw, vai: str) -> tuple[str, ...]:
    if "scopes" not in raw:
        raise PolicyInvalid(f"vai {vai!r} thiếu trường bắt buộc `scopes`")
    gia_tri = raw["scopes"]
    if not isinstance(gia_tri, (list, tuple)) or not gia_tri:
        raise PolicyInvalid(f"vai {vai!r}: `scopes` phải là danh sách không rỗng")
    return tuple(
        _chuoi_khong_rong(scope, f"vai {vai!r}: scope") for scope in gia_tri
    )


def _disclosure(raw, vai: str) -> Mapping[str, str]:
    if "disclosure" not in raw:
        raise PolicyInvalid(f"vai {vai!r} thiếu trường bắt buộc `disclosure`")
    bang = _mapping(raw["disclosure"], f"vai {vai!r}: `disclosure`")
    if not bang:
        raise PolicyInvalid(f"vai {vai!r}: `disclosure` rỗng")
    hop_le = "/".join(DISCLOSURE_LEVELS)
    da_kiem = {}
    for loai_raw, muc in bang.items():
        loai = _chuoi_khong_rong(loai_raw, f"vai {vai!r}: tên loại nội dung")
        if not isinstance(muc, str) or muc not in LEVEL_ORDER:
            raise PolicyInvalid(
                f"vai {vai!r}, loại nội dung {loai!r}: mức {muc!r} không hợp lệ,"
                f" tập hợp lệ là {hop_le}"
            )
        da_kiem[loai] = muc
    return MappingProxyType(da_kiem)


def _masked_slots(raw, vai: str, disclosure: Mapping[str, str]):
    khai = raw.get("masked_slots", {})
    bang = _mapping({} if khai is None else khai, f"vai {vai!r}: `masked_slots`")
    khai_duoc = ", ".join(POLICY_MASKABLE_SLOTS)
    ket_qua = {}
    for loai, slots in bang.items():
        if loai not in disclosure:
            raise PolicyInvalid(
                f"vai {vai!r}: `masked_slots` nhắc loại nội dung {loai!r}"
                " không có trong `disclosure`"
            )
        if disclosure[loai] != "L1":
            raise PolicyInvalid(
                f"vai {vai!r}: `masked_slots` khai cho loại nội dung {loai!r}"
                f" đang ở mức {disclosure[loai]}; che là luật của riêng L1"
                " (L0 thì vắng mặt hẳn, L2 thì chỉ còn luật owner ở tầng che)"
            )
        if not isinstance(slots, (list, tuple)):
            raise PolicyInvalid(
                f"vai {vai!r}, {loai!r}: `masked_slots` phải là danh sách,"
                f" nhận được {_ten(slots)}"
            )
        for slot in slots:
            if slot == OWNER_SLOT:
                raise PolicyInvalid(
                    f"vai {vai!r}: không khai slot {OWNER_SLOT!r} trong"
                    " `masked_slots`, nó luôn được tổng quát hóa ở tầng che"
                )
            if not isinstance(slot, str) or slot not in SLOT_ROLE_SET:
                raise PolicyInvalid(
                    f"vai {vai!r}, {loai!r}: slot {slot!r} không hợp lệ,"
                    f" các slot khai được là {khai_duoc}"
                )
        ket_qua[loai] = frozenset(slots)
    return MappingProxyType(ket_qua)


def _allowed_keys(vai: str, scopes: tuple[str, ...], disclosure: Mapping[str, str]):
    """Tích Descartes `scopes` × loại nội dung, cắt theo ngưỡng từng namespace.

    Dựng khóa cho *toàn bộ* tích Descartes trước rồi mới cắt: nhờ vậy một scope
    hay một loại nội dung có hình dạng hỏng (chứa dấu phân tách) bị bắt ngay
    lúc nạp, kể cả khi nó đang ở L0 và chưa lọt vào tập khóa nào.
    """
    moi_khoa = {}
    for scope in scopes:
        for content_type in disclosure:
            try:
                moi_khoa[(scope, content_type)] = filter_key(scope, content_type)
            except (TypeError, ValueError) as loi:
                raise PolicyInvalid(
                    f"vai {vai!r}: không dựng được khóa lọc - {loi}"
                ) from None
    theo_namespace = {}
    for namespace, muc_toi_thieu in NAMESPACE_MIN_LEVEL.items():
        nguong = LEVEL_ORDER[muc_toi_thieu]
        theo_namespace[namespace] = frozenset(
            khoa
            for (_, content_type), khoa in moi_khoa.items()
            if LEVEL_ORDER[disclosure[content_type]] >= nguong
        )
    return MappingProxyType(theo_namespace)


def _kiem_bang_hang(hang) -> None:
    """Bảng hạng tiêm vào phải là một **thứ tự toàn phần** trên loại nội dung.

    Ba luật, và cả ba là điều kiện để hai phép kiểm đơn điệu dưới đây có nghĩa.
    Rỗng hay không phải map: validator không chạy được thì bảng chính sách không
    được nạp. Hạng không phải `int`: phép so hạng là phép so số nguyên, và một
    chuỗi lọt vào làm `sorted` dội `TypeError` giữa `build_policy`. Hai loại
    **cùng hạng**: `sorted` của Python ổn định nhưng không có tie-break, nên thứ
    tự duyệt của hai loại ngang hạng là thứ tự chúng xuất hiện trong `disclosure`
    - và khi đó cùng một bảng chính sách nạp được hay bị từ chối tùy vào thứ tự
    hai dòng trong file YAML.

    Luật thứ ba trùng với luật của `adapters/sensitivity_loader`, và đó không
    phải trùng lặp cần gỡ: loader canh **file** chốt của repo, còn hàm này canh
    **tham số** mà bất kỳ nơi gọi nào cũng truyền vào được, kể cả một dict dựng
    tay trong bộ test. Bỏ nó đi là để kết quả của validator phụ thuộc thứ tự
    dòng YAML ở đúng đường mà file chốt không đi qua.

    `bool` là con của `int` trong Python, và `runbook: True` thành hạng 1 là một
    bảng chạy được mà không ai định khai như vậy - cùng ca mà loader hạng chặn.
    """
    if not isinstance(hang, Mapping) or not hang:
        raise PolicyInvalid(
            "thiếu bảng hạng độ nhạy để kiểm đơn điệu (AD-5): validator không"
            " chạy được thì bảng chính sách không được nạp"
        )
    sai_kieu = sorted(
        str(loai)
        for loai, so in hang.items()
        if isinstance(so, bool) or not isinstance(so, int)
    )
    if sai_kieu:
        raise PolicyInvalid(
            f"bảng hạng độ nhạy có hạng không phải số nguyên ở {sai_kieu}:"
            " phép kiểm đơn điệu của AD-5 so hạng bằng phép so số nguyên"
        )
    trung = sorted(
        loai for loai, so in hang.items() if list(hang.values()).count(so) > 1
    )
    if trung:
        raise PolicyInvalid(
            f"bảng hạng độ nhạy có hai loại nội dung cùng hạng: {trung}."
            " Phép kiểm đơn điệu duyệt theo hạng tăng dần, nên hai loại ngang"
            " hạng làm kết quả phụ thuộc thứ tự dòng trong file chính sách"
        )


def _kiem_khai_du_hang(vai: str, disclosure: Mapping[str, str], hang: Mapping[str, int]):
    """Tập loại khai phải **bằng** tập loại có hạng: thiếu hay thừa đều từ chối.

    Hai chiều, hai lỗi khác nhau vì hai cách sửa khác nhau. Thiếu một loại là
    một khẳng định fail-closed viết bằng cách im lặng, và validator đơn điệu
    không đọc được sự im lặng đó. Thừa một loại là một dòng chính sách gán cho
    một loại nội dung mà ingest sẽ từ chối bằng `SensitivityRankUnknown`, tức
    một dòng không bao giờ có hiệu lực.
    """
    thieu = sorted(set(hang) - set(disclosure))
    if thieu:
        raise PolicyInvalid(
            f"vai {vai!r}: `disclosure` thiếu loại nội dung có hạng {thieu}."
            " Bảng chính sách phải khai tường minh đủ mọi loại của bảng hạng độ"
            " nhạy; để mặc định L0 ngầm thì validator đơn điệu không phân biệt"
            " được 'cố ý L0' với 'quên khai'"
        )
    la = sorted(set(disclosure) - set(hang))
    if la:
        raise PolicyInvalid(
            f"vai {vai!r}: `disclosure` khai loại nội dung {la} không có hạng độ"
            " nhạy, nên ingest sẽ từ chối cả lô mang loại đó và dòng chính sách"
            " này không bao giờ có hiệu lực"
        )


def _kiem_don_dieu_muc(vai: str, disclosure: Mapping[str, str], hang: Mapping[str, int]):
    """Điều kiện (1) của AD-5: hạng(A) <= hạng(B) kéo theo mức(A) >= mức(B).

    Duyệt theo hạng tăng dần và đòi mức không tăng. Kiểm cặp kề là đủ cho toàn
    bộ quan hệ vì "không tăng" bắc cầu; và cặp kề cũng là cặp dễ sửa nhất để in
    ra - hai loại nội dung cạnh nhau trong bảng hạng.
    """
    theo_hang = sorted(disclosure, key=lambda loai: hang[loai])
    for thap, cao in zip(theo_hang, theo_hang[1:]):
        if LEVEL_ORDER[disclosure[thap]] < LEVEL_ORDER[disclosure[cao]]:
            raise PolicyInvalid(
                f"vai {vai!r} đảo chiều điều kiện (1) của AD-5 ở cặp"
                f" {thap!r} (hạng {hang[thap]}, mức {disclosure[thap]}) và"
                f" {cao!r} (hạng {hang[cao]}, mức {disclosure[cao]}):"
                " hạng thấp hơn phải có mức tiết lộ không thấp hơn"
            )


def _kiem_don_dieu_che(
    vai: str,
    disclosure: Mapping[str, str],
    masked_slots: Mapping[str, frozenset[str]],
    hang: Mapping[str, int],
):
    """Điều kiện (2) của AD-5, chỉ trong vùng L1 của vai.

    Che là khái niệm của riêng L1 (`_masked_slots` đã ép điều đó), nên vùng so
    sánh là đúng những loại nội dung mà vai này đang ở L1. Loại hạng cao hơn
    phải che *ít nhất* những gì loại hạng thấp hơn che; ngược lại là một bảng
    trong đó tài liệu nhạy cảm hơn lộ nhiều slot hơn tài liệu thường hơn.
    """
    l1 = sorted(
        (loai for loai, muc in disclosure.items() if muc == "L1"),
        key=lambda loai: hang[loai],
    )
    for thap, cao in zip(l1, l1[1:]):
        che_thap = masked_slots.get(thap, frozenset())
        che_cao = masked_slots.get(cao, frozenset())
        thieu = sorted(che_thap - che_cao)
        if thieu:
            raise PolicyInvalid(
                f"vai {vai!r} đảo chiều điều kiện (2) của AD-5 ở cặp"
                f" {thap!r} (hạng {hang[thap]}, che {sorted(che_thap)}) và"
                f" {cao!r} (hạng {hang[cao]}, che {sorted(che_cao)}):"
                f" loại hạng cao hơn thiếu {thieu}"
            )


def _canh_bao_tran_khoa(vai: str, allowed_keys: Mapping[str, frozenset[str]]) -> None:
    """Trần 50 khóa của AD-4: một dòng WARNING mỗi (vai, namespace) vượt trần.

    Không từ chối. Vượt trần là tín hiệu phải đo lại recall và độ trễ của filter
    Qdrant trước khi tiến (spine Deferred "ACORN"), không phải một file cấu hình
    hỏng - và biến nó thành lỗi nạp là chặn đúng cấu hình 1 của FR-28, thứ mở
    hết mọi vai lên L2 để lấy trần recall.
    """
    for namespace, khoa in allowed_keys.items():
        if len(khoa) > TRAN_KHOA_MOI_VAI:
            logger.warning(
                "vai %r ở namespace %r có %d khóa lọc, vượt trần %d của AD-4:"
                " đo lại recall và độ trễ filter trước khi tiến",
                vai,
                namespace,
                len(khoa),
                TRAN_KHOA_MOI_VAI,
            )


def build_policy(raw, policy_version: str, *, hang: Mapping[str, int]) -> Policy:
    """Kiểm dict đã parse rồi dựng `Policy`; sai ở đâu là `PolicyInvalid` ở đó.

    `hang` là bảng hạng độ nhạy (loại nội dung -> số nguyên), **tiêm vào** và
    bắt buộc: `core/` không đọc file nào (AD-1), và một mặc định "bỏ qua phép
    kiểm khi vắng bảng" là một validator tắt được bằng cách quên một tham số.
    Nơi gọi duy nhất là `adapters/policy_loader.load_policy`, chỗ có đường đọc
    đĩa và có bảng chốt của repo.
    """
    _kiem_bang_hang(hang)
    if raw is None:
        raise PolicyInvalid("bảng chính sách rỗng, từ chối nạp")
    goc = _mapping(raw, "bảng chính sách")
    if "version" not in goc:
        raise PolicyInvalid("bảng chính sách thiếu trường bắt buộc `version`")
    if goc["version"] != SCHEMA_VERSION or isinstance(goc["version"], bool):
        raise PolicyInvalid(
            f"`version` = {goc['version']!r} không đọc được,"
            f" schema hiện hành là version {SCHEMA_VERSION}"
        )
    if "roles" not in goc:
        raise PolicyInvalid("bảng chính sách thiếu khối bắt buộc `roles`")
    khoi_roles = _mapping(goc["roles"], "`roles`")
    if not khoi_roles:
        raise PolicyInvalid("khối `roles` rỗng, từ chối nạp")

    roles = {}
    for vai_raw, cau_hinh in khoi_roles.items():
        vai = _chuoi_khong_rong(vai_raw, f"tên vai {vai_raw!r}")
        raw_vai = _mapping(cau_hinh, f"vai {vai!r}")
        disclosure = _disclosure(raw_vai, vai)
        scopes = _scopes(raw_vai, vai)
        masked_slots = _masked_slots(raw_vai, vai, disclosure)
        allowed_keys = _allowed_keys(vai, scopes, disclosure)
        # Lược đồ trước, ngữ nghĩa sau. Một `run:book` viết nhầm vừa hỏng hình
        # dạng khóa lọc vừa "không có hạng độ nhạy"; báo cái thứ hai là chỉ
        # người sửa đi thêm một dòng vào bảng hạng cho một loại không tồn tại.
        _kiem_khai_du_hang(vai, disclosure, hang)
        _kiem_don_dieu_muc(vai, disclosure, hang)
        _kiem_don_dieu_che(vai, disclosure, masked_slots, hang)
        _canh_bao_tran_khoa(vai, allowed_keys)
        roles[vai] = RolePolicy(
            name=vai,
            scopes=scopes,
            disclosure=disclosure,
            masked_slots=masked_slots,
            allowed_keys=allowed_keys,
        )
    return Policy(
        version=goc["version"],
        policy_version=policy_version,
        roles=MappingProxyType(roles),
    )
