"""Citation theo quyền: hình dạng, luật dựng và phép từ chối (story 3.4, FR-14, FR-15).

Một citation nói **ba điều về một hyperedge mà vai vừa thấy trong ngữ cảnh**: nó
là fact nào (`id`, cùng id node mà endpoint đồ thị 3.7 nhận), vai đang đọc nó ở
mức nào (`level`), và vai nào của nó đã bị che (`masked_slots`) cộng nhóm nào
phụ trách (`owner_group`). Epic 4 dựng slab bôi đen, dòng hạn chế và placeholder
"còn một phần bị hạn chế, liên hệ [nhóm]" từ đúng sáu trường này; Epic 5 lấy
điểm khởi phát break-glass ở đây. Không trường nào mang nội dung slot, tên
entity hay câu fact.

**Citation dựng từ ngữ cảnh truy hồi cộng cửa quyền của adapter graph, không từ
văn bản `answer`.** Id đọc được trong chuỗi ngữ cảnh chỉ là **khóa tra**; khóa
quyền, các vai có mặt và nhóm phụ trách đến từ adapter dưới ngữ cảnh vai hiện
tại, còn mức và tập vai bị che tính bằng **hai hàm thuần của `core/masking.py`**
(`muc_hieu_luc`, `vai_phai_che_hieu_luc` - bản đã tính grant break-glass của
`muc_tiet_lo`/`vai_phai_che`, story 5.3) - chính hàm mà `mask` dùng, nên citation
và dấu che không trôi khỏi nhau. Hai hàm ấy gọi **qua module** (`masking.vai_phai_che_hieu_luc`)
chứ không nhập theo tên: luật phân giải lúc gọi, nên ca đột biến của
`tests/test_trich_dan.py` thay luật ở một chỗ là cả dấu che lẫn citation đổi
theo - đó là cơ chế của câu "một luật một chỗ", không phải một quy ước.

Một chuỗi ngữ cảnh bị sửa tay vì thế không dựng ra được một citation ngoài
quyền: adapter không thấy id ấy, và hàm ở đây dội `TrichDanNgoaiQuyen` thay vì
bỏ lặng lẽ một mục.

Module ở `adapters/` vì hai lý do. Một, hình dạng citation phải sống ở **một**
chỗ mà cả engine (nơi dựng) lẫn `api/` (nơi chuyển sang dict) đều nhập được, và
chiều import cho phép cả hai nhập `adapters/`. Hai, nó cần `core/` (luật che,
tách khóa) nhưng không cần kho nào, nên nó không thuộc một adapter cụ thể.

Chỉ hàm thuần và một dataclass đóng băng. Lời gọi kho nằm ở
`adapters/neo4j.py::trich_dan_cua`, lời gọi ghép nằm ở `adapters/engine.py`.
"""

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from core import masking
from core.keys import split_key
from core.permission import PermissionContext
from core.policy import LEVEL_ORDER, NAMESPACE_MIN_LEVEL
from core.slots import SLOT_ROLE_SET, SLOT_ROLES

# Sáu khóa của một citation, **tập đóng, liệt kê tường minh**, theo đúng thứ tự
# đi ra JSON. `api.hoi_dap.dung_envelope` kiểm từng citation bằng tuple này như
# nó kiểm `meta`: thêm hay bớt một khóa là đổi hợp đồng AD-8 và phải đi qua
# Ask First của spec 3.4.
KHOA_TRICH_DAN: tuple[str, ...] = (
    "id",
    "level",
    "scope",
    "content_type",
    "masked_slots",
    "owner_group",
)

# Hai mức mà một citation mang được. L0 **không có mặt**: hyperedge L0 vắng
# khỏi ngữ cảnh ở tầng lọc, nên không có id nào để tra, và citation không đếm
# nó. Dẫn xuất từ ngưỡng namespace chứ không viết tay hai chuỗi: mức thấp nhất
# mà một hyperedge còn vào được ngữ cảnh là ngưỡng của `hyperedges`.
MUC_TRICH_DAN: frozenset[str] = frozenset(
    muc
    for muc, bac in LEVEL_ORDER.items()
    if bac >= LEVEL_ORDER[NAMESPACE_MIN_LEVEL[masking.MASK_NAMESPACE]]
)


class TrichDanNgoaiQuyen(RuntimeError):
    """Ngữ cảnh mang một id hyperedge mà adapter graph không thấy dưới vai này.

    Đây là **lỗi hệ thống 5xx mang mã ổn định**, không phải một citation bị bỏ
    lặng lẽ. Hai đường tới đây, cả hai đều là hỏng: tầng lọc để một id lọt vào
    ngữ cảnh mà cửa quyền của adapter không xác nhận (filter và cửa quyền lệch
    nhau), hay chuỗi ngữ cảnh bị sửa giữa đường. Bỏ qua id đó là biến một lệch
    quyền thành một citation thiếu, thứ không ai nhìn ra.

    `code` là mã lỗi API ổn định để test assert trên `code` (AD-8).
    """

    code = "TRICH_DAN_NGOAI_QUYEN"

    def __init__(self, thong_diep: str, *, ids: tuple[str, ...] = ()):
        super().__init__(thong_diep)
        # Các id mà cửa quyền không xác nhận (story 3.6): handler ghi chúng vào
        # `hyperedge_ids` của hàng `permission_mismatch`, còn thân lỗi thì
        # không - id là khóa tra, không phải thứ đi ra theo một 500.
        self.ids = tuple(ids)


@dataclass(frozen=True)
class TrichDan:
    """Một citation, sáu trường, bất biến, kiểm hình dạng ngay lúc dựng.

    `masked_slots` là tuple theo thứ tự `SLOT_ROLES`, không phải tập: thứ tự
    đi thẳng ra JSON và Epic 4 render theo thứ tự đó. `owner_group` là tên nhóm
    hoặc `None` khi bảng nhóm chưa khai loại nội dung ấy - `None` chứ không
    phải lỗi, cùng luật với `dau_che_owner`.
    """

    id: str
    level: str
    scope: str
    content_type: str
    masked_slots: tuple[str, ...]
    owner_group: str | None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("citation phải mang id hyperedge không rỗng")
        if self.level not in MUC_TRICH_DAN:
            raise ValueError(
                f"level {self.level!r} không hợp lệ cho citation, chỉ có"
                f" {sorted(MUC_TRICH_DAN)}: L0 vô hình, không vào citation"
            )
        for ten in ("scope", "content_type"):
            if not isinstance(getattr(self, ten), str) or not getattr(self, ten):
                raise ValueError(f"citation phải mang {ten} không rỗng")
        if not isinstance(self.masked_slots, tuple):
            raise TypeError("masked_slots phải là tuple theo thứ tự SLOT_ROLES")
        la = [v for v in self.masked_slots if v not in SLOT_ROLE_SET]
        if la:
            raise ValueError(f"masked_slots mang vai ngoài danh mục 8 vai: {la}")
        theo_thu_tu = tuple(v for v in SLOT_ROLES if v in self.masked_slots)
        if theo_thu_tu != self.masked_slots:
            raise ValueError(
                f"masked_slots phải theo thứ tự SLOT_ROLES và không lặp: {self.masked_slots}"
            )
        if self.owner_group is not None and (
            not isinstance(self.owner_group, str) or not self.owner_group.strip()
        ):
            raise ValueError("owner_group phải là tên nhóm không rỗng hoặc None")


def dung_trich_dan(
    context: PermissionContext,
    id_hyperedge: str,
    khoa: str,
    cac_vai: Iterable[str],
    nhom: str | None,
) -> TrichDan:
    """Một citation từ id, khóa quyền, các vai có mặt và nhóm phụ trách.

    `masked_slots = vai_phai_che_hieu_luc(context, content_type, id) ∩ cac_vai`,
    đúng luật của `mask`, và **chỉ** giao với vai có mặt trên hyperedge: một
    hyperedge không có vai `owner` (HE-04 của fixture, 229/281 của `synth`) không
    mang `owner` trong `masked_slots`, dù `owner_group` vẫn điền theo loại nội
    dung. `level` suy từ `allowed_keys` qua `muc_hieu_luc`, không tra lại bảng;
    hyperedge nằm trong `context.grant_ids` (story 5.3) cho `L2` và chỉ còn
    `owner` bị che - đúng mức mà `mask` vừa áp lên ngữ cảnh.

    Khóa ngoài quyền dội `MaskItemOutOfPermission` từ `core/` nguyên vẹn: nơi
    gọi đã lọc bằng cửa quyền của adapter, nên tới đây mà còn ngoài quyền là
    một lỗi cấu trúc, không phải một ca vận hành. Hai ca hỏng dữ liệu kho -
    khóa không tách được, vai cạnh ngoài danh mục - và ca gọi dưới ngữ cảnh hệ
    thống đều dội `TrichDanNgoaiQuyen`, để lên tới HTTP chúng là một 500 **mang
    mã** chứ không một `ValueError`/`SystemContextRawRead` không phân loại.
    """
    _khong_phai_he_thong(context)
    try:
        scope, content_type = split_key(khoa)
    except (TypeError, ValueError) as loi:
        raise TrichDanNgoaiQuyen(
            f"khóa quyền của hyperedge {id_hyperedge!r} không tách được thành"
            " scope và loại nội dung: không suy được mức hay tập che"
        ) from loi
    muc = masking.muc_hieu_luc(context, khoa, id_hyperedge)
    co_mat = set(cac_vai)
    la = sorted(v for v in co_mat if not isinstance(v, str) or v not in SLOT_ROLE_SET)
    if la:
        raise TrichDanNgoaiQuyen(
            f"hyperedge {id_hyperedge!r} mang vai ngoài danh mục 8 vai: {la}"
        )
    che = masking.vai_phai_che_hieu_luc(context, content_type, id_hyperedge) & co_mat
    return TrichDan(
        id=id_hyperedge,
        level=muc,
        scope=scope,
        content_type=content_type,
        masked_slots=tuple(v for v in SLOT_ROLES if v in che),
        owner_group=nhom,
    )


def dung_danh_sach(
    context: PermissionContext,
    ids: Iterable[str],
    tu_adapter: Mapping[str, tuple[str, tuple[str, ...]]],
    nhom_cua: Callable[[str], str | None],
) -> tuple[TrichDan, ...]:
    """Danh sách citation theo **thứ tự xuất hiện trong ngữ cảnh**.

    `ids` là dãy id đọc từ cột `hyperedge` của ngữ cảnh (đã khử trùng, giữ thứ
    tự); `tu_adapter` là thứ `Neo4jACLGraphStorage.trich_dan_cua` trả về dưới
    ngữ cảnh vai: `{id: (khóa, các vai có mặt)}`, hyperedge ngoài quyền vắng
    mặt. Một id có trong ngữ cảnh mà vắng ở đây là `TrichDanNgoaiQuyen` cho cả
    lượt - không dựng nửa danh sách, vì nửa danh sách trông y như một danh sách
    đúng.

    `nhom_cua` là phép tra nhóm theo loại nội dung, tiêm từ bảng nhóm mà adapter
    graph đang dùng để che - cùng một bảng, nên `owner_group` và dấu che
    `[owner:<nhóm>]` trong ngữ cảnh không nói hai tên. Thứ tự lấy từ `ids` chứ
    không từ `tu_adapter`: `IN $ids` của Cypher không hứa thứ tự nào.
    """
    _khong_phai_he_thong(context)
    # Chốt thành tuple **trước** vòng quét đầu: một generator một lượt bị cạn ở
    # vòng quét `thieu`, và vòng dựng phía sau cho tuple rỗng lặng lẽ.
    ids = tuple(ids)
    thieu = [i for i in ids if i not in tu_adapter]
    if thieu:
        raise TrichDanNgoaiQuyen(
            f"ngữ cảnh mang {len(thieu)} id hyperedge mà adapter graph không"
            f" thấy dưới vai {context.role!r}: tầng lọc và cửa quyền lệch nhau,"
            " không dựng citation cho lượt này",
            ids=tuple(thieu),
        )
    theo_id = dung_theo_id(context, ids, tu_adapter, nhom_cua)
    return tuple(theo_id[i] for i in ids)


def dung_theo_id(
    context: PermissionContext,
    ids: Iterable[str],
    tu_adapter: Mapping[str, tuple[str, tuple[str, ...]]],
    nhom_cua: Callable[[str], str | None],
) -> dict[str, TrichDan]:
    """`{id: TrichDan}` cho những id **có mặt** trong `tu_adapter`; id vắng thì vắng.

    Phần chung của `dung_danh_sach` (3.4, vắng là lỗi) và
    `EngineACL.trich_dan_theo_id` (5.1, vắng là câu trả lời): cùng phép tách
    khóa, cùng phép tra nhóm, cùng `dung_trich_dan`. Ngữ cảnh hệ thống bị từ
    chối **trước** mọi thứ, kể cả với dãy id rỗng. Khóa không tách được là
    `TrichDanNgoaiQuyen` giữ nguyên nhân (`from loi`).
    """
    _khong_phai_he_thong(context)
    ra: dict[str, TrichDan] = {}
    for id_he in ids:
        if id_he not in tu_adapter or id_he in ra:
            continue
        khoa, cac_vai = tu_adapter[id_he]
        try:
            _, content_type = split_key(khoa)
        except (TypeError, ValueError) as loi:
            raise TrichDanNgoaiQuyen(
                f"khóa quyền của hyperedge {id_he!r} không tách được thành scope"
                " và loại nội dung: không tra được nhóm phụ trách"
            ) from loi
        ra[id_he] = dung_trich_dan(context, id_he, khoa, cac_vai, nhom_cua(content_type))
    return ra


def _khong_phai_he_thong(context: PermissionContext) -> None:
    """Citation không dựng dưới ngữ cảnh hệ thống.

    Ngữ cảnh hệ thống không mang `allowed_keys`, nên không có mức tiết lộ nào
    để nói; hỏi `keys_for` ở đó là `SystemContextRawRead`, một lỗi lập trình
    không phân loại. Kiểm trước và dội mã ổn định của module này.
    """
    if context.bypass_filter:
        raise TrichDanNgoaiQuyen(
            "citation không dựng dưới ngữ cảnh hệ thống: không có mức tiết lộ"
            " nào để suy từ một ngữ cảnh đọc thô"
        )


__all__ = [
    "KHOA_TRICH_DAN",
    "MUC_TRICH_DAN",
    "TrichDan",
    "TrichDanNgoaiQuyen",
    "dung_danh_sach",
    "dung_trich_dan",
]
