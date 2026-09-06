"""Đồ thị theo quyền: hình dạng, luật lắp và phép từ chối (story 3.7, FR-19, AD-8).

`POST /do-thi` nhận một danh sách id hyperedge của một lượt và trả `graph` của
envelope AD-8 có nội dung. Server **lọc lại toàn bộ** theo ngữ cảnh quyền của
token hiện tại: đỉnh nào thấy được, tên nào phải che, hyperedge nào vắng mặt
đều quyết ở adapter graph và ở tầng che, không ở client. Nếu client tự dựng đồ
thị từ `citations` thì client là người quyết đỉnh nào ngoài quyền, đúng thứ
AD-8 và AD-9 cấm.

Ba luật của module, cả ba là cơ chế chứ không phải quy ước.

**Đỉnh vào đồ thị đi qua mệnh đề chặt.** `Neo4jACLGraphStorage.do_thi_cua` dùng
`_dieu_kien` cho cả ba biến (hyperedge, cạnh, entity): L0, khác space, **không
khóa** đều là "ngoài quyền" và bị loại tại server. Khác `get_node_edges`, đường
này không nới cho entity không khóa (AD-5): ngữ cảnh gửi LLM cần "có một fact ở
đây mà tôi không được đọc" để không mất một slot (FR-12), còn đồ thị vẽ lên
màn thì EXPERIENCE.md chốt "không vẽ node". Hyperedge không còn đỉnh nào qua
lọc vắng mặt như một id không tồn tại - `MATCH`, không `OPTIONAL MATCH`. Lý do
đầy đủ ở `docs/adr/ADR-018`.

**Đỉnh qua lọc mà nằm ở vai bị che thì xuống dạng đã che, và là một node riêng
theo cặp (hyperedge, slot).** Tên là dấu che do `core.masking.mask` sinh qua
`_che` của adapter; `masked` suy bằng phép so tên trước và sau che ở adapter,
không parse dấu che. Id node che là `f"{id_hyperedge}#{slot}"` (`id_node_che`):
hai hyperedge cùng che một entity thật **không** gộp thành một node, vì gộp là
kể rằng hai fact chung một thực thể bị che. Entity thấy được thì id node là id
entity, dùng chung giữa các hyperedge.

**Hình dạng là tập đóng và thứ tự tất định.** Ba dataclass đóng băng tự kiểm
lúc dựng, ba tuple khóa mà `api.hoi_dap.dung_envelope` đối chiếu từng node và
từng edge như nó đối chiếu citation. Hyperedge theo thứ tự id vào (đã khử
trùng), entity theo thứ tự xuất hiện, edge theo (thứ tự hyperedge, `SLOT_ROLES`,
label). Không id chunk, không `source_id`, không `description`, không trọng số,
không số đếm nào bị loại.

Module ở `adapters/` cùng lý do với `adapters/trich_dan.py`: hình dạng phải
sống ở một chỗ mà cả engine (nơi dựng) lẫn `api/` (nơi chuyển sang dict) nhập
được, và nó cần `core/` nhưng không cần kho nào. Chỉ hàm thuần và dataclass;
lời gọi kho ở `adapters/neo4j.py::do_thi_cua`, lời gọi ghép ở
`adapters/engine.py::EngineACL.do_thi`.
"""

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from adapters.trich_dan import MUC_TRICH_DAN, TrichDanNgoaiQuyen
from core import masking
from core.ids import normalize_id
from core.keys import split_key
from core.permission import PermissionContext
from core.slots import SLOT_ROLE_SET, SLOT_ROLES

# Hai giá trị của `kind`, tập đóng. Client phân biệt hai loại node bằng đúng
# trường này chứ không bằng hình dạng id.
KIND_HYPEREDGE: str = "hyperedge"
KIND_ENTITY: str = "entity"

# Ba tập khóa đóng, liệt kê tường minh theo đúng thứ tự đi ra JSON. Thêm hay
# bớt một khóa là đổi hợp đồng AD-8 và phải đi qua Ask First của spec 3.7.
KHOA_NODE_HYPEREDGE: tuple[str, ...] = ("id", "kind", "level", "scope", "content_type")
KHOA_NODE_ENTITY: tuple[str, ...] = ("id", "kind", "label", "masked")
KHOA_CANH: tuple[str, ...] = ("source", "target", "slot")

# Năm khóa của một dòng mà `Neo4jACLGraphStorage.do_thi_cua` trả về, sau tầng
# che. `ten_da_che` là tên **đã** qua `_che`; `bi_che` là phép so tên trước và
# sau che ở adapter. Adapter không trả tên thô dưới bất kỳ khóa nào.
KHOA_DONG_ADAPTER: tuple[str, ...] = ("id_hyperedge", "khoa", "slot", "ten_da_che", "bi_che")

# Dấu nối giữa id hyperedge và tên vai trong id của một node che. Một ký tự
# không xuất hiện trong danh mục 8 vai và hiếm trong tên hyperedge.
DAU_NOI_NODE_CHE: str = "#"


class DoThiNgoaiQuyen(TrichDanNgoaiQuyen):
    """Đồ thị không dựng được dưới ngữ cảnh này; **cùng mã** với citation.

    Hai đường tới đây, cả hai là hỏng chứ không phải ca vận hành: gọi dưới ngữ
    cảnh hệ thống (không có mức tiết lộ nào để suy, và `_che` sẽ trả tên thô),
    hay dữ liệu kho hỏng (khóa không tách được, vai cạnh ngoài danh mục). Kế
    thừa `TrichDanNgoaiQuyen` để `api/` bắt bằng **một** nhánh và ra cùng một
    500 `TRICH_DAN_NGOAI_QUYEN`; id bị lộ không có, vì đường này không có id
    nào "thiếu" - hyperedge ngoài quyền vắng mặt là hợp lệ.
    """


@dataclass(frozen=True)
class NodeHyperedge:
    """Một node hyperedge: mức và loại suy như citation, không nội dung."""

    id: str
    level: str
    scope: str
    content_type: str
    kind: str = field(default=KIND_HYPEREDGE, init=False)

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("node hyperedge phải mang id không rỗng")
        if self.level not in MUC_TRICH_DAN:
            raise ValueError(
                f"level {self.level!r} không hợp lệ cho node hyperedge, chỉ có"
                f" {sorted(MUC_TRICH_DAN)}: L0 vô hình, không vào đồ thị"
            )
        for ten in ("scope", "content_type"):
            if not isinstance(getattr(self, ten), str) or not getattr(self, ten):
                raise ValueError(f"node hyperedge phải mang {ten} không rỗng")


@dataclass(frozen=True)
class NodeEntity:
    """Một node entity: `label` là tên thật hoặc dấu che, `masked` nói là cái nào."""

    id: str
    label: str
    masked: bool
    kind: str = field(default=KIND_ENTITY, init=False)

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("node entity phải mang id không rỗng")
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("node entity phải mang label không rỗng")
        if not isinstance(self.masked, bool):
            raise TypeError("masked của node entity phải là bool")


@dataclass(frozen=True)
class CanhDoThi:
    """Một cạnh hyperedge -> entity mang đúng một vai slot."""

    source: str
    target: str
    slot: str

    def __post_init__(self):
        for ten in ("source", "target"):
            if not isinstance(getattr(self, ten), str) or not getattr(self, ten):
                raise ValueError(f"cạnh phải mang {ten} không rỗng")
        if self.slot not in SLOT_ROLE_SET:
            raise ValueError(f"cạnh mang vai {self.slot!r} ngoài danh mục 8 vai")


@dataclass(frozen=True)
class DoThi:
    """Đồ thị đã lắp: hai tuple, id node không trùng, mọi cạnh nối hai node có mặt."""

    nodes: tuple = ()
    edges: tuple = ()

    def __post_init__(self):
        if not isinstance(self.nodes, tuple) or not isinstance(self.edges, tuple):
            raise TypeError("nodes và edges của đồ thị phải là tuple")
        he: set[str] = set()
        entity: set[str] = set()
        for n in self.nodes:
            if isinstance(n, NodeHyperedge):
                dich = he
            elif isinstance(n, NodeEntity):
                dich = entity
            else:
                raise TypeError(f"node lạ trong đồ thị: {type(n).__name__}")
            if n.id in he or n.id in entity:
                raise ValueError(f"id node {n.id!r} xuất hiện hai lần trong đồ thị")
            dich.add(n.id)
        da_co: set[tuple] = set()
        for c in self.edges:
            if not isinstance(c, CanhDoThi):
                raise TypeError(f"cạnh lạ trong đồ thị: {type(c).__name__}")
            if c.source not in he:
                raise ValueError(f"cạnh trỏ từ {c.source!r} không phải node hyperedge có mặt")
            if c.target not in entity:
                raise ValueError(f"cạnh trỏ tới {c.target!r} không phải node entity có mặt")
            bo = (c.source, c.target, c.slot)
            if bo in da_co:
                raise ValueError(f"cạnh {bo} xuất hiện hai lần trong đồ thị")
            da_co.add(bo)


def id_node_che(id_hyperedge: str, slot: str) -> str:
    """Id của node che theo cặp (hyperedge, slot); tất định, không mang tên thật."""
    if slot not in SLOT_ROLE_SET:
        raise ValueError(f"vai {slot!r} ngoài danh mục 8 vai")
    return f"{id_hyperedge}{DAU_NOI_NODE_CHE}{slot}"


def chuan_hoa_ids(ids: Iterable[str]) -> tuple[str, ...]:
    """Dãy id đã chuẩn hóa (`normalize_id`) và khử trùng, giữ lần xuất hiện đầu.

    Một hàm cho cả adapter lẫn engine, để thứ tự mà `dung_do_thi` xếp hyperedge
    và tập id mà Cypher nhận là **cùng một dãy**. Không phải chuỗi là `TypeError`
    của `normalize_id`; `api/` đã chặn ca đó ở 400 trước khi tới đây.
    """
    ra: list[str] = []
    for i in ids:
        chuan = normalize_id(i)
        if chuan not in ra:
            ra.append(chuan)
    return tuple(ra)


def dung_do_thi(
    context: PermissionContext,
    ids: Iterable[str],
    tu_adapter: Iterable[Mapping],
) -> DoThi:
    """Lắp đồ thị từ các dòng đã che của adapter, theo thứ tự tất định.

    `ids` là dãy id đã chuẩn hóa và khử trùng (`chuan_hoa_ids`), quyết thứ tự
    hyperedge; `tu_adapter` là các dòng `KHOA_DONG_ADAPTER` mà
    `Neo4jACLGraphStorage.do_thi_cua` trả về dưới ngữ cảnh vai - hyperedge ngoài
    quyền **vắng mặt**, và đây là điểm khác citation: một id vào mà không có
    dòng nào không phải lỗi, nó chỉ không vào đồ thị (id không tồn tại, id L0 và
    id khác space cho cùng một kết quả). Thứ tự dòng của adapter không có nghĩa
    (`IN $ids` không hứa gì); mọi thứ tự dựng lại ở đây.

    Mức của node hyperedge suy bằng `masking.muc_tiet_lo` từ `allowed_keys`,
    gọi **qua module** như citation để một đột biến ở `core/` đổi cả hai. Node
    che dựng theo (hyperedge, slot): hai entity cùng bị che ở một vai của một
    hyperedge ra đúng một node và một cạnh - dấu che không mang số lượng, cùng
    chủ ý với `core/masking.py`.
    """
    _khong_phai_he_thong(context)
    theo_he: dict[str, list[Mapping]] = {}
    for d in tu_adapter:
        thieu = [k for k in KHOA_DONG_ADAPTER if k not in d]
        if thieu:
            raise DoThiNgoaiQuyen(f"dòng của adapter thiếu khóa {thieu}: không lắp được đồ thị")
        if not isinstance(d["ten_da_che"], str) or not d["ten_da_che"]:
            raise DoThiNgoaiQuyen(
                f"dòng của hyperedge {d['id_hyperedge']!r} mang tên đã che"
                f" {d['ten_da_che']!r}: phải là chuỗi không rỗng"
            )
        if not isinstance(d["slot"], str):
            raise DoThiNgoaiQuyen(
                f"dòng của hyperedge {d['id_hyperedge']!r} mang vai {d['slot']!r}: phải là chuỗi"
            )
        theo_he.setdefault(d["id_hyperedge"], []).append(d)
    nodes: list = []
    edges: list = []
    # id node entity -> (label, masked) đã dựng. Cùng id mà khác label hay khác
    # `masked` là va chạm: một entity thật trùng tên `<he>#<slot>` với một node
    # che, và gộp lặng lẽ là gán tên thật cho một node che (hay ngược lại).
    entity_da_co: dict[str, tuple[str, bool]] = {}
    for id_he in ids:
        dong = theo_he.get(id_he)
        if not dong:
            continue
        khoa = dong[0]["khoa"]
        try:
            scope, content_type = split_key(khoa)
        except (TypeError, ValueError) as loi:
            raise DoThiNgoaiQuyen(
                f"khóa quyền của hyperedge {id_he!r} không tách được thành scope"
                " và loại nội dung: không suy được mức"
            ) from loi
        la = sorted({d["slot"] for d in dong if not isinstance(d["slot"], str) or d["slot"] not in SLOT_ROLE_SET}, key=str)
        if la:
            raise DoThiNgoaiQuyen(f"hyperedge {id_he!r} mang vai ngoài danh mục 8 vai: {la}")
        nodes.append(NodeHyperedge(id=id_he, level=masking.muc_tiet_lo(context, khoa), scope=scope, content_type=content_type))
        canh_cua_he: set[tuple[str, str]] = set()
        for d in sorted(dong, key=lambda r: (SLOT_ROLES.index(r["slot"]), r["ten_da_che"])):
            if d["bi_che"]:
                id_node = id_node_che(id_he, d["slot"])
            else:
                id_node = d["ten_da_che"]
            hinh = (d["ten_da_che"], bool(d["bi_che"]))
            if id_node not in entity_da_co:
                nodes.append(NodeEntity(id=id_node, label=hinh[0], masked=hinh[1]))
                entity_da_co[id_node] = hinh
            elif entity_da_co[id_node] != hinh:
                raise DoThiNgoaiQuyen(
                    f"va chạm id node entity {id_node!r}: một entity thật trùng tên với"
                    f" một node che dạng <hyperedge>{DAU_NOI_NODE_CHE}<slot>, không lắp đồ thị"
                )
            if (id_node, d["slot"]) not in canh_cua_he:
                edges.append(CanhDoThi(source=id_he, target=id_node, slot=d["slot"]))
                canh_cua_he.add((id_node, d["slot"]))
    try:
        return DoThi(nodes=tuple(nodes), edges=tuple(edges))
    except (TypeError, ValueError) as loi:
        # Hai ca va chạm id có thật trên dữ liệu kho: một entity mang đúng id
        # của một hyperedge, hay mang tên dạng `<hyperedge>#<slot>` trùng với
        # id một node che. Cả hai là dữ liệu kho hỏng theo nghĩa của đồ thị -
        # một node hai nghĩa - nên ra mã ổn định thay vì một `ValueError` trần.
        raise DoThiNgoaiQuyen(
            f"đồ thị không lắp được vì va chạm id giữa node entity và node"
            f" hyperedge hay node che ({DAU_NOI_NODE_CHE!r}): {loi}"
        ) from loi


def do_thi_tu_dict(d: Mapping) -> DoThi:
    """Dựng lại `DoThi` từ dict hai khóa `nodes`/`edges` - bộ kiểm duy nhất cho dạng dict.

    `api.hoi_dap.dung_envelope` gọi hàm này để kiểm `graph` bằng cách dựng lại,
    và bộ test dùng đúng nó để đọc thân response - một bộ kiểm, không hai. Node
    phân loại theo `kind`; tập khóa của từng loại phải **đúng** tập đóng, thừa
    hay thiếu đều là `ValueError`. Lỗi kiểu ra `ValueError` để nơi gọi bắt một
    lớp.
    """
    if not isinstance(d, Mapping) or set(d) != {"nodes", "edges"}:
        raise ValueError(
            f"graph là tập trường đóng ['nodes', 'edges'], nhận được"
            f" {sorted(d) if isinstance(d, Mapping) else type(d).__name__}"
        )
    for ten in ("nodes", "edges"):
        if not isinstance(d[ten], list):
            raise ValueError(f"graph.{ten} phải là list, nhận được {type(d[ten]).__name__}")
    nodes = []
    for n in d["nodes"]:
        if not isinstance(n, Mapping):
            raise ValueError(f"node của graph phải là dict, nhận được {type(n).__name__}")
        kind = n.get("kind")
        if kind == KIND_HYPEREDGE:
            khoa, lop = KHOA_NODE_HYPEREDGE, NodeHyperedge
        elif kind == KIND_ENTITY:
            khoa, lop = KHOA_NODE_ENTITY, NodeEntity
        else:
            raise ValueError(f"node mang kind {kind!r}, chỉ có {KIND_HYPEREDGE!r} và {KIND_ENTITY!r}")
        thieu = [k for k in khoa if k not in n]
        thua = [k for k in n if k not in khoa]
        if thieu or thua:
            raise ValueError(f"node {kind} là tập trường đóng {list(khoa)}: thiếu {thieu}, thừa {thua}")
        try:
            nodes.append(lop(**{k: n[k] for k in khoa if k != "kind"}))
        except TypeError as loi:
            raise ValueError(f"node {kind} sai hình dạng: {loi}") from loi
    edges = []
    for c in d["edges"]:
        if not isinstance(c, Mapping):
            raise ValueError(f"edge của graph phải là dict, nhận được {type(c).__name__}")
        thieu = [k for k in KHOA_CANH if k not in c]
        thua = [k for k in c if k not in KHOA_CANH]
        if thieu or thua:
            raise ValueError(f"edge là tập trường đóng {list(KHOA_CANH)}: thiếu {thieu}, thừa {thua}")
        try:
            edges.append(CanhDoThi(**{k: c[k] for k in KHOA_CANH}))
        except TypeError as loi:
            raise ValueError(f"edge sai hình dạng: {loi}") from loi
    try:
        return DoThi(nodes=tuple(nodes), edges=tuple(edges))
    except TypeError as loi:
        raise ValueError(f"graph sai hình dạng: {loi}") from loi


def _khong_phai_he_thong(context: PermissionContext) -> None:
    """Đồ thị không dựng dưới ngữ cảnh hệ thống, cùng luật với citation."""
    if context.bypass_filter:
        raise DoThiNgoaiQuyen(
            "đồ thị không dựng dưới ngữ cảnh hệ thống: không có mức tiết lộ nào"
            " để suy, và tầng che trả tên thô ở ngữ cảnh đó"
        )


__all__ = [
    "CanhDoThi",
    "DAU_NOI_NODE_CHE",
    "DoThi",
    "DoThiNgoaiQuyen",
    "KHOA_CANH",
    "KHOA_DONG_ADAPTER",
    "KHOA_NODE_ENTITY",
    "KHOA_NODE_HYPEREDGE",
    "KIND_ENTITY",
    "KIND_HYPEREDGE",
    "NodeEntity",
    "NodeHyperedge",
    "chuan_hoa_ids",
    "do_thi_tu_dict",
    "dung_do_thi",
    "id_node_che",
]
