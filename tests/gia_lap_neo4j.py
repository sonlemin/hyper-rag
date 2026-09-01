"""Driver Neo4j giả cho bộ test adapter graph (story 1.4).

Neo4j không có local mode như qdrant-client, nên phần lớn bộ test story 1.4
chạy trên driver giả này. Nó làm hai việc:

1. Ghi lại mọi câu Cypher kèm tham số. Đó là lớp assert chính của story: mệnh
   đề WHERE phải nằm trong chính câu gửi đi, không phải một phép lọc lại phía
   Python sau khi bản ghi đã về.
2. Diễn giải đúng những câu mà adapter phát ra, trên một graph hai phía trong
   bộ nhớ. Phần lọc **đọc thẳng từ câu Cypher**: biến nào không có điều kiện
   khóa trong WHERE thì ở đây cũng không bị lọc. Nhờ vậy quên tiêm WHERE cho
   một biến là kết quả sai chứ không phải một câu văn khác đi.

Câu Cypher lạ là lỗi test, không phải một no-op: một đường đọc mới không được
lặng lẽ chạy mà chưa ai kiểm nó có lọc hay không.

Tên field lấy từ chính hằng của `core/` chứ không viết cứng: viết cứng thì đổi
tên hằng là adapter đổi mà bộ canh vẫn xanh.

Thứ driver giả **không** chứng minh được là Cypher có hợp lệ với Neo4j hay
không. Phần đó do `tests/test_adapter_neo4j_that.py` chạy trên container
compose gánh, cùng cách mà `hnsw_config` của story 1.3 phải chờ Qdrant thật.

Đặt ở `tests/` chứ không ở `tests/fixtures/`: luật import-lint cấm thư mục
fixture gọi vào `core/` và `vendor/`, còn file này phải nói đúng ngôn ngữ của
adapter.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from neo4j.exceptions import ServiceUnavailable

from adapters.neo4j import NODE_ID_FIELD, ROLE_FIELD, SLOT_FIELD, SPACE_FIELD
from core.keys import FILTER_KEY_FIELD

# --- Đọc mệnh đề lọc ra khỏi câu Cypher ---------------------------------

_LOC_KHOA = re.compile(rf"(\w+)\.{FILTER_KEY_FIELD} IN \$keys")
_LOC_SPACE = re.compile(rf"(\w+)\.{SPACE_FIELD} = \$space")
# Mọi biến mở ngoặc trong phần pattern, *kể cả biến không nhãn*: `(n)` trong
# một OPTIONAL MATCH cũng phải là biến đã bị lọc ở trên, nếu không nó là một
# cửa vào đồ thị không ai canh.
_BIEN_TRONG_NGOAC = re.compile(r"\((\w+)[\s):{]")
_BIEN_CANH = re.compile(r"-\[(\w+):")
_GAN_TRUONG = re.compile(r"(\w+)\.(\w+) = \$(\w+)")
_GAN_GOP = re.compile(r"(\w+) \+= \$(\w+)")
_NHAN = re.compile(r"`([^`]+)`|:([A-Za-z]\w*)")


def bien_loc_khoa(cypher: str) -> set[str]:
    """Các biến có điều kiện `x.filter_key IN $keys` trong câu."""
    return set(_LOC_KHOA.findall(cypher))


def bien_loc_space(cypher: str) -> set[str]:
    """Các biến có điều kiện `x.space = $space` trong câu."""
    return set(_LOC_SPACE.findall(cypher))


def _phan_pattern(cypher: str) -> str:
    """Phần câu trước `RETURN`: chỗ duy nhất có pattern đồ thị.

    Cắt phần RETURN đi vì `count(r)`, `properties(n)` cũng là dấu ngoặc mở, và
    một hàm gộp không phải một cửa vào đồ thị.
    """
    return cypher.split("RETURN")[0]


def bien_trong_pattern(cypher: str) -> set[str]:
    """Mọi biến node và biến cạnh xuất hiện trong pattern của câu."""
    goc = _phan_pattern(cypher)
    return set(_BIEN_TRONG_NGOAC.findall(goc)) | set(_BIEN_CANH.findall(goc))


def canh_moi_bien_deu_bi_loc(cypher: str, *, co_khoa: bool = True) -> None:
    """Mọi biến trong pattern phải bị ràng cả `space` lẫn khóa quyền.

    Khắt khe có chủ đích, và phủ cả biến cạnh. Lọc đúng biến của MATCH mà quên
    biến của OPTIONAL MATCH là ca rò kinh điển của đường graph: node đích được
    lọc còn lân cận thì không, nên số đếm và danh sách lân cận vẫn kể ra thứ
    ngoài quyền. Quên biến cạnh cũng vậy: cạnh mang khóa riêng và khóa đó có
    thể lệch khóa của hai đầu.

    `co_khoa=False` là đường ngữ cảnh hệ thống: đọc thô, chỉ còn ràng `space`.
    """
    trong_pattern = bien_trong_pattern(cypher)
    assert trong_pattern, f"không đọc được biến nào trong pattern:\n{cypher}"
    thieu_space = trong_pattern - bien_loc_space(cypher)
    assert not thieu_space, f"biến {sorted(thieu_space)} không ràng space:\n{cypher}"
    if co_khoa:
        thieu_khoa = trong_pattern - bien_loc_khoa(cypher)
        assert not thieu_khoa, f"biến {sorted(thieu_khoa)} không lọc khóa:\n{cypher}"
    else:
        thua = bien_loc_khoa(cypher)
        assert not thua, f"ngữ cảnh hệ thống mà vẫn lọc khóa: {sorted(thua)}"


# --- Graph hai phía trong bộ nhớ ----------------------------------------


@dataclass
class NodeGia:
    nhan: set[str] = field(default_factory=set)
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanhGia:
    space: str
    src: str
    tgt: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoiGoiCypher:
    """Một câu Cypher đã gửi kèm tham số, loại câu và các dòng nó trả về."""

    cypher: str
    params: dict
    loai: str = ""
    dong: list[dict] = field(default_factory=list)


class KetQuaGia:
    """Đứng thay `AsyncResult`: `single()` và duyệt bất đồng bộ."""

    def __init__(self, dong: list[dict]):
        self._dong = dong

    async def single(self):
        return self._dong[0] if self._dong else None

    def __aiter__(self):
        async def sinh():
            for d in self._dong:
                yield d

        return sinh()


class PhienGia:
    def __init__(self, kho: "Neo4jGhiLai"):
        self._kho = kho

    async def __aenter__(self):
        return self

    async def __aexit__(self, *loi):
        return False

    async def run(self, cypher: str, **params) -> KetQuaGia:
        return self._kho._chay(cypher, params)


class Neo4jGhiLai:
    """Driver giả: nhật ký Cypher cộng một graph hai phía trong bộ nhớ."""

    def __init__(self, so_lan_chua_san_sang: int = 0, loi_ket_noi=None):
        self.loi_goi: list[LoiGoiCypher] = []
        self.nodes: dict[tuple[str, str], NodeGia] = {}
        self.canh: list[CanhGia] = []
        self.so_lan_kiem_ket_noi = 0
        self.da_dong = False
        self._con_hong = so_lan_chua_san_sang
        self._loi_ket_noi = loi_ket_noi or ServiceUnavailable(
            "giả lập: Neo4j chưa sẵn sàng"
        )

    # --- Phần hợp đồng của AsyncDriver ---------------------------------

    def session(self, **_):
        return PhienGia(self)

    async def verify_connectivity(self):
        """Hỏng đúng `so_lan_chua_san_sang` lần đầu rồi mới sẵn sàng (bẫy A2)."""
        self.so_lan_kiem_ket_noi += 1
        if self._con_hong > 0:
            self._con_hong -= 1
            raise self._loi_ket_noi

    async def close(self):
        self.da_dong = True

    # --- Tra cứu cho phần assert ---------------------------------------

    def cac_cau_doc(self) -> list[LoiGoiCypher]:
        """Mọi câu đọc đã gửi.

        Phân loại theo đúng nhánh mà bộ diễn giải đã chọn, không theo việc câu
        có chứa chuỗi con nào: một câu đọc lỡ mang chữ MERGE trong tên field sẽ
        vô hình với toàn bộ lớp assert chính nếu lọc bằng chuỗi con.
        """
        return [lg for lg in self.loi_goi if lg.loai.startswith("doc:")]

    def cau_cuoi(self) -> LoiGoiCypher:
        assert self.loi_goi, "chưa có câu Cypher nào"
        return self.loi_goi[-1]

    def xoa_nhat_ky(self) -> None:
        """Bắt đầu một đoạn đo mới mà giữ nguyên dữ liệu đã nạp."""
        self.loi_goi.clear()

    def dem_node(self) -> int:
        return len(self.nodes)

    def dem_canh(self) -> int:
        return len(self.canh)

    def node_tho(self, space: str, id_node: str) -> NodeGia | None:
        """Đọc thẳng vào kho, không qua adapter - dùng để chấm đường ghi."""
        return self.nodes.get((space, id_node))

    def dem_lan_can_tho(self, space: str, id_node: str) -> int:
        """Số lân cận thật của một node, không qua lọc quyền - mốc để so."""
        return sum(
            1
            for c in self.canh
            if c.space == space and id_node in (c.src, c.tgt)
        )

    def canh_tho(self, space: str, src: str, tgt: str) -> CanhGia | None:
        for c in self.canh:
            if c.space == space and {c.src, c.tgt} == {src, tgt}:
                return c
        return None

    # --- Diễn giải Cypher ----------------------------------------------

    def _chay(self, cypher: str, params: dict) -> KetQuaGia:
        lg = LoiGoiCypher(cypher=cypher, params=dict(params))
        self.loi_goi.append(lg)
        lg.loai, lg.dong = self._dien_giai(cypher, params)
        return KetQuaGia(lg.dong)

    def _dien_giai(self, cypher: str, params: dict) -> tuple[str, list[dict]]:
        if cypher.startswith("CREATE INDEX"):
            return "ghi:index", []
        if "MERGE (n:" in cypher:
            return "ghi:node", self._ghi_node(cypher, params)
        if "MERGE (a)-[" in cypher:
            return "ghi:canh", self._ghi_canh(cypher, params)
        if "AS ton_tai_node" in cypher:
            return "doc:has_node", [
                {"ton_tai_node": bool(self._node_hop_le(cypher, params))}
            ]
        if "AS thuoc_tinh_node" in cypher:
            n = self._node_hop_le(cypher, params)
            return "doc:get_node", (
                [{"thuoc_tinh_node": dict(n.props)}] if n else []
            )
        if "AS bac" in cypher:
            return "doc:node_degree", [{"bac": self._dem_lan_can(cypher, params)}]
        if "AS ton_tai_canh" in cypher:
            return "doc:has_edge", [
                {"ton_tai_canh": bool(self._cac_canh_hai_dau(cypher, params))}
            ]
        if "AS thuoc_tinh_canh" in cypher:
            return "doc:get_edge", self._doc_canh(cypher, params)
        if "AS lan_can" in cypher:
            return "doc:get_node_edges", self._doc_lan_can(cypher, params)
        raise AssertionError(f"driver giả không biết câu Cypher này:\n{cypher}")

    # --- Ghi ------------------------------------------------------------

    @staticmethod
    def _nhan_cua_merge(cypher: str) -> set[str]:
        dong = next(d for d in cypher.splitlines() if "MERGE (n:" in d)
        return {a or b for a, b in _NHAN.findall(dong)}

    def _ap_gan(self, props: dict, cypher: str, params: dict, bien: str) -> None:
        """Áp đúng các phép gán mà câu Cypher khai, không đoán thêm."""
        for ten_bien, nguon in _GAN_GOP.findall(cypher):
            if ten_bien == bien:
                props.update(params[nguon])
        for ten_bien, truong, nguon in _GAN_TRUONG.findall(cypher):
            if ten_bien == bien:
                props[truong] = params[nguon]

    def _ghi_node(self, cypher: str, params: dict) -> list[dict]:
        khoa = (params["space"], params["id"])
        node = self.nodes.setdefault(khoa, NodeGia())
        node.nhan |= self._nhan_cua_merge(cypher)
        node.props[NODE_ID_FIELD] = params["id"]
        self._ap_gan(node.props, cypher, params, "n")
        return []

    def _ghi_canh(self, cypher: str, params: dict) -> list[dict]:
        space = params["space"]
        a = self.nodes.get((space, params["src"]))
        b = self.nodes.get((space, params["tgt"]))
        if a is None or b is None:
            # MATCH không khớp thì MERGE không chạy, và `count(r)` trên không
            # dòng nào trả 0 - đúng ngữ nghĩa Cypher, và đúng ca mà
            # `EdgeEndpointMissing` của adapter bắt.
            return [{"da_ghi": 0}]
        canh = next(
            (
                c
                for c in self.canh
                if c.space == space
                and c.src == params["src"]
                and c.tgt == params["tgt"]
            ),
            None,
        )
        if canh is None:
            canh = CanhGia(space=space, src=params["src"], tgt=params["tgt"])
            self.canh.append(canh)
        self._ap_gan(canh.props, cypher, params, "r")
        return [{"da_ghi": 1}]

    # --- Đọc ------------------------------------------------------------

    def _hop_le(self, cypher: str, params: dict, bien: str, props: dict) -> bool:
        """Qua được đúng những điều kiện mà câu Cypher đặt cho biến này.

        Dùng chung cho node và cạnh: điều kiện của chúng cùng một hình dạng, và
        điều đáng canh là "câu có đặt điều kiện cho biến này không", chứ không
        phải "biến này là node hay cạnh".
        """
        if bien in bien_loc_space(cypher) and props.get(SPACE_FIELD) != params["space"]:
            return False
        if bien in bien_loc_khoa(cypher):
            if props.get(FILTER_KEY_FIELD) not in set(params.get("keys") or ()):
                return False
        return True

    def _node_hop_le(
        self, cypher: str, params: dict, khoa_id: str = "id", bien: str = "n"
    ):
        node = self.nodes.get((params["space"], params[khoa_id]))
        if node is None or not self._hop_le(cypher, params, bien, node.props):
            return None
        return node

    def _lan_can(self, cypher: str, params: dict, id_goc: str, bien_lan_can: str):
        """Bộ ba (cạnh, id lân cận, node lân cận) qua được điều kiện của câu."""
        ket_qua = []
        for c in self.canh:
            if c.space != params["space"]:
                continue
            if c.src == id_goc:
                id_kia = c.tgt
            elif c.tgt == id_goc:
                id_kia = c.src
            else:
                continue
            if not self._hop_le(cypher, params, "r", c.props):
                continue
            kia = self.nodes.get((params["space"], id_kia))
            if kia is None or not self._hop_le(cypher, params, bien_lan_can, kia.props):
                continue
            ket_qua.append((c, id_kia, kia))
        return ket_qua

    def _dem_lan_can(self, cypher: str, params: dict) -> int:
        n = self._node_hop_le(cypher, params)
        if n is None:
            return 0
        return len(self._lan_can(cypher, params, params["id"], "m"))

    def _cac_canh_hai_dau(self, cypher: str, params: dict):
        a = self._node_hop_le(cypher, params, "src", "a")
        b = self._node_hop_le(cypher, params, "tgt", "b")
        if a is None or b is None:
            return []
        return [
            c
            for c in self.canh
            if c.space == params["space"]
            and {c.src, c.tgt} == {params["src"], params["tgt"]}
            and self._hop_le(cypher, params, "r", c.props)
        ]

    def _doc_canh(self, cypher: str, params: dict) -> list[dict]:
        cac_canh = self._cac_canh_hai_dau(cypher, params)
        if not cac_canh:
            return []
        a = self.nodes[(params["space"], params["src"])]
        b = self.nodes[(params["space"], params["tgt"])]
        return [
            {
                "thuoc_tinh_canh": dict(cac_canh[0].props),
                "vai_a": a.props.get(ROLE_FIELD),
                "khoa_a": a.props.get(FILTER_KEY_FIELD),
                "vai_b": b.props.get(ROLE_FIELD),
                "khoa_b": b.props.get(FILTER_KEY_FIELD),
            }
        ]

    def _doc_lan_can(self, cypher: str, params: dict) -> list[dict]:
        n = self._node_hop_le(cypher, params)
        if n is None:
            return []
        return [
            {
                "nguon": params["id"],
                "lan_can": id_kia,
                "slot": canh.props.get(SLOT_FIELD),
                "vai_nguon": n.props.get(ROLE_FIELD),
                "khoa_nguon": n.props.get(FILTER_KEY_FIELD),
                "vai_lan_can": kia.props.get(ROLE_FIELD),
                "khoa_lan_can": kia.props.get(FILTER_KEY_FIELD),
            }
            for canh, id_kia, kia in self._lan_can(cypher, params, params["id"], "m")
        ]
