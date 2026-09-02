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

from neo4j.exceptions import ClientError, ConstraintError, ServiceUnavailable

from adapters.neo4j import (
    LABEL_ENTITY,
    LABEL_HYPEREDGE,
    NODE_ID_FIELD,
    ROLE_FIELD,
    SLOT_FIELD,
    SPACE_FIELD,
)
from core.keys import FILTER_KEY_FIELD

# --- Đọc mệnh đề lọc ra khỏi câu Cypher ---------------------------------

_LOC_KHOA = re.compile(rf"(\w+)\.{FILTER_KEY_FIELD} IN \$keys")
# Nhánh nới của AD-9/AD-5: biến lân cận cho node **vai entity không khóa** đi
# qua. Đọc thẳng từ câu Cypher như mọi mệnh đề khác, nên biến nào *không* khai
# nhánh này thì ở đây cũng không được nới - quên nới ở adapter là kết quả sai,
# không phải một câu văn khác đi.
_CHO_KHONG_KHOA = re.compile(
    rf"(\w+)\.{FILTER_KEY_FIELD} IS NULL AND \1\.{ROLE_FIELD} = \$vai_entity"
)
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


def bien_cho_khong_khoa(cypher: str) -> set[str]:
    """Các biến được phép nhận node vai entity không khóa."""
    return set(_CHO_KHONG_KHOA.findall(cypher))


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


def _loi_rang_buoc(space: str, id_node: str) -> ConstraintError:
    """`ConstraintError` đúng hình dạng mà Neo4j 5.26 thật dội ra.

    Đo trên container ngày 01/09/2026: `code` là
    `Neo.ClientError.Schema.ConstraintValidationFailed` và thông điệp là
    "Node(39) already exists with label `{space}` and property `id` = 'X'" -
    nó mang nhãn và tên thuộc tính trong nháy ngược, và **không** mang tên ràng
    buộc. Adapter lọc theo đúng hai thứ đó trước khi kết luận "id trùng khác
    vai", nên kho giả phải nói cùng một ngôn ngữ; nếu không thì nhánh lọc ấy
    chỉ được đo trên container.

    Đặt thẳng hai thuộc tính riêng của `Neo4jError` thay vì gọi `hydrate` hay
    gán `.message`: cả hai đường kia đều phát `DeprecationWarning` của driver,
    tức bộ giả lập đi một đường mà `vendor/` không đi.
    """
    loi = ConstraintError()
    loi._neo4j_code = "Neo.ClientError.Schema.ConstraintValidationFailed"
    loi._message = (
        f"Node(0) already exists with label `{space}` and property"
        f" `{NODE_ID_FIELD}` = '{id_node}'"
    )
    return loi


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
    """Một câu Cypher đã gửi kèm tham số, loại câu và các dòng nó trả về.

    Từ story 2.1 mang thêm hai thứ mà adapter phải khai tường minh: câu này đi
    trong transaction đọc hay ghi (`kieu_giao_dich`), và phiên mở trên database
    nào (`database`). Không ghi lại thì "dùng `execute_write` cho đường ghi" và
    "truyền `database=`" là hai câu trong docstring mà không gì canh.
    """

    cypher: str
    params: dict
    loai: str = ""
    dong: list[dict] = field(default_factory=list)
    kieu_giao_dich: str = ""
    database: str | None = None


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


class GiaoDichGia:
    """Đứng thay `AsyncManagedTransaction`: chỉ có `run`, đúng thứ adapter dùng."""

    def __init__(self, kho: "Neo4jGhiLai", kieu: str, database: str | None):
        self._kho = kho
        self._kieu = kieu
        self._database = database

    async def run(self, cypher: str, **params) -> KetQuaGia:
        return self._kho._chay(
            cypher, params, kieu_giao_dich=self._kieu, database=self._database
        )


class PhienGia:
    """Đứng thay `AsyncSession`: hai cửa transaction có quản lý.

    Cố ý **không** có `run`: adapter đi qua `execute_read`/`execute_write` từ
    story 2.1, nên giữ lại cửa autocommit ở đây là để một lần quay lui lặng lẽ
    vẫn xanh.
    """

    def __init__(self, kho: "Neo4jGhiLai", database: str | None):
        self._kho = kho
        self._database = database

    async def __aenter__(self):
        return self

    async def __aexit__(self, *loi):
        return False

    async def execute_read(self, cong_viec):
        return await cong_viec(GiaoDichGia(self._kho, "read", self._database))

    async def execute_write(self, cong_viec):
        return await cong_viec(GiaoDichGia(self._kho, "write", self._database))


class Neo4jGhiLai:
    """Driver giả: nhật ký Cypher cộng một graph hai phía trong bộ nhớ."""

    def __init__(
        self, so_lan_chua_san_sang: int = 0, loi_ket_noi=None, nhat_ky_chung=None
    ):
        # Nhật ký dùng chung với client vector giả, khi test cần *thứ tự giữa
        # hai kho*; xem docstring của field cùng tên ở `tests/gia_lap_qdrant.py`.
        self.nhat_ky_chung = nhat_ky_chung
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

    def session(self, database=None, **_):
        return PhienGia(self, database)

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

    def _chay(
        self,
        cypher: str,
        params: dict,
        *,
        kieu_giao_dich: str = "",
        database: str | None = None,
    ) -> KetQuaGia:
        lg = LoiGoiCypher(
            cypher=cypher,
            params=dict(params),
            kieu_giao_dich=kieu_giao_dich,
            database=database,
        )
        self.loi_goi.append(lg)
        lg.loai, lg.dong = self._dien_giai(cypher, params)
        self._canh_kieu_giao_dich(lg)
        if self.nhat_ky_chung is not None:
            self.nhat_ky_chung.append(("graph", lg.loai))
        return KetQuaGia(lg.dong)

    # Loại câu chỉ chạy được trong transaction ghi. Neo4j thật từ chối chúng
    # trong `execute_read` bằng `ForbiddenOnReadOnlyDatabase`/`ClientError`;
    # driver giả phải từ chối luôn, nếu không thì bỏ `ghi=True` ở một đường ghi
    # chỉ đỏ được trên container - tức `uv run pytest` mất một cửa canh.
    LOAI_PHAI_GHI: tuple[str, ...] = ("ghi:",)

    def _canh_kieu_giao_dich(self, lg: "LoiGoiCypher") -> None:
        if lg.kieu_giao_dich == "read" and lg.loai.startswith(self.LOAI_PHAI_GHI):
            raise ClientError(
                "giả lập: câu ghi không chạy được trong transaction đọc"
                f" (execute_read). Đường ghi phải khai `ghi=True`:\n{lg.cypher}"
            )

    def _dien_giai(self, cypher: str, params: dict) -> tuple[str, list[dict]]:
        if cypher.startswith("CREATE CONSTRAINT") or cypher.startswith("DROP INDEX"):
            return "ghi:index", []
        # Ba đường của story 2.3, nhận dạng trước các câu chung hơn. Đều mang
        # tiền tố `ghi:` vì chúng là đường ghi (hoặc đọc-để-ghi) chạy dưới cờ
        # system, cùng lý do với `ghi:doc-khoa` ở dưới.
        if "DETACH DELETE" in cypher:
            return "ghi:xoa", self._xoa_node(cypher, params)
        if "AS khoa_hyperedge" in cypher:
            return "ghi:doc-khoa-lan-can", self._doc_khoa_lan_can(cypher, params)
        if "AS da_ghi" in cypher and "SET n." in cypher:
            return "ghi:dat-lai", self._dat_lai(cypher, params)
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
        if "AS khoa_node" in cypher:
            # Cố ý **không** mang tiền tố `doc:`: đây là bước đọc khóa của
            # read-merge-write, chạy dưới cờ system trên đường *ghi*. Gộp nó
            # vào `cac_cau_doc()` là làm mọi lớp assert "mọi câu đọc đều lọc
            # khóa quyền" nhận thêm một câu mà theo thiết kế không lọc.
            return "ghi:doc-khoa", self._doc_khoa(cypher, params)
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
        nhan_moi = self._nhan_cua_merge(cypher)
        node = self.nodes.get(khoa)
        if node is not None and not (nhan_moi <= node.nhan):
            # Ràng buộc duy nhất `id` theo `space` (story 2.1). `MERGE` theo một
            # nhãn vai khác không khớp node đã có nên nó tạo node mới, và node
            # mới vi phạm `id IS UNIQUE`. Kho giả phải dựng lại đúng chỗ đó, nếu
            # không thì bộ test chạy trên một Neo4j *không có* ràng buộc và ca
            # id trùng khác vai chỉ đỏ trên container thật.
            # Thông điệp dựng theo đúng hình dạng của Neo4j 5.26 thật (đo
            # ngày 01/09/2026): nó mang nhãn và tên thuộc tính trong dấu nháy
            # ngược, và **không** mang tên ràng buộc. Adapter lọc theo đúng hai
            # thứ đó, nên kho giả phải nói cùng một ngôn ngữ - nếu không thì
            # nhánh lọc chỉ được đo trên container.
            raise _loi_rang_buoc(params["space"], params["id"])
        if node is None:
            node = self.nodes.setdefault(khoa, NodeGia())
        node.nhan |= nhan_moi
        node.props[NODE_ID_FIELD] = params["id"]
        self._ap_gan(node.props, cypher, params, "n")
        # `SET n.x = null` gỡ hẳn thuộc tính trong Neo4j, không để lại một giá
        # trị null. Ca "không khóa" của story 2.1 đi đúng đường này, và nếu kho
        # giả giữ lại `filter_key: None` thì mệnh đề `IN $keys` ở đây vẫn trượt
        # nhưng `properties(n)` lại trả về một trường mà server thật không có.
        for ten in [k for k, v in node.props.items() if v is None]:
            del node.props[ten]
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

    def _xoa_node(self, cypher: str, params: dict) -> list[dict]:
        """`DETACH DELETE`: theo danh sách id nếu câu mang `$ids`, không thì cả space."""
        ids = params.get("ids") if "$ids" in cypher else None
        muc = [
            (sp, id_node)
            for (sp, id_node), node in self.nodes.items()
            if sp == params["space"]
            and (ids is None or id_node in ids)
            and self._hop_le(cypher, params, "n", node.props)
        ]
        for khoa in muc:
            del self.nodes[khoa]
        da_xoa = {id_node for _, id_node in muc}
        self.canh = [
            c
            for c in self.canh
            if not (c.space == params["space"] and (c.src in da_xoa or c.tgt in da_xoa))
        ]
        return [{"da_xoa": len(muc)}]

    def _doc_khoa_lan_can(self, cypher: str, params: dict) -> list[dict]:
        """Khóa của hyperedge nối tới entity: chỉ lân cận mang nhãn Hyperedge."""
        e = self._node_hop_le(cypher, params, "id", "e")
        if e is None:
            return []
        return [
            {"id_hyperedge": id_kia, "khoa_hyperedge": kia.props.get(FILTER_KEY_FIELD)}
            for _, id_kia, kia in self._lan_can(cypher, params, params["id"], "h")
            if LABEL_HYPEREDGE in kia.nhan
        ]

    def _dat_lai(self, cypher: str, params: dict) -> list[dict]:
        """`MATCH (n:space:<Entity|Hyperedge> {id}) SET ...`: no-op im lặng khi không khớp, như Cypher."""
        node = self.nodes.get((params["space"], params["id"]))
        nhan = LABEL_HYPEREDGE if f"`{LABEL_HYPEREDGE}`" in cypher.split("\n")[0] else LABEL_ENTITY
        if (
            node is None
            or nhan not in node.nhan
            or not self._hop_le(cypher, params, "n", node.props)
        ):
            return [{"da_ghi": 0}]
        self._ap_gan(node.props, cypher, params, "n")
        for ten in [k for k, v in node.props.items() if v is None]:
            del node.props[ten]
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
            trong_tap = props.get(FILTER_KEY_FIELD) in set(params.get("keys") or ())
            # Nhánh AD-9: node vai entity không khóa đi qua được, nhưng chỉ ở
            # biến mà câu Cypher *có* khai nhánh ấy.
            khong_khoa_duoc_phep = (
                bien in bien_cho_khong_khoa(cypher)
                and props.get(FILTER_KEY_FIELD) is None
                and props.get(ROLE_FIELD) == params.get("vai_entity")
            )
            if not (trong_tap or khong_khoa_duoc_phep):
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

    def _doc_khoa(self, cypher: str, params: dict) -> list[dict]:
        """Bước đọc khóa của read-merge-write: quét theo danh sách id."""
        return [
            {
                "id_node": id_node,
                "khoa_node": node.props.get(FILTER_KEY_FIELD),
            }
            for (space, id_node), node in self.nodes.items()
            if space == params["space"]
            and id_node in params["ids"]
            and self._hop_le(cypher, params, "n", node.props)
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
