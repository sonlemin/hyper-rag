"""Adapter Neo4j: điểm chèn quyền duy nhất của đường graph (FR-08, AD-2).

Hợp đồng với upstream giữ nguyên - 7 method đọc cộng `upsert_node`/`upsert_edge`
của `BaseGraphStorage` - nên `HyperGraphRAG` không biết gì về quyền và
`vendor/` không phải sửa một dòng nào. Toàn bộ phần quyền nằm ở hai chỗ:

- lúc ghi, khóa `{scope}:{content_type}` lấy từ phạm vi nhãn ingest đang mở
  (`adapters/ingest_labels.py`, cùng nguồn với adapter Qdrant) và ghi lên cả
  node lẫn cạnh;
- lúc đọc, tập khóa lấy từ `context.keys_for(GRAPH_NAMESPACE)` và đi vào chính
  câu Cypher dưới dạng `x.filter_key IN $keys`, ràng cùng chỗ với `x.space`.

Mệnh đề WHERE tiêm cho **mọi** biến node của pattern, không chỉ biến đích. Lọc
node đích mà quên lân cận là đường rò kinh điển của graph: số đếm degree và
danh sách cạnh vẫn kể ra thứ ngoài quyền, tức là vẫn tiết lộ rằng có fact tồn
tại. Vì thế `node_degree` đếm sau filter và `has_*` trả `False` cho mục ngoài
quyền thay vì báo lỗi.

Không dùng `vendor/hypergraphrag/kg/neo4j_impl.py`: bản đó biến mỗi tên thực
thể thành một label Neo4j và không có chỗ nào cho quyền hay `space`.

Hypergraph nằm dạng hai phía (FR-03/04): hyperedge là node `:Hyperedge` mang
thuộc tính, entity là node `:Entity`, cạnh `:SLOT` nối hai bên và mang vai slot
từ danh mục `core/`. Quan hệ 2 vai là hyperedge có đúng 2 cạnh, đi cùng một
đường ghi và cùng một đường đọc, không có nhánh riêng.
"""

import asyncio
from dataclasses import dataclass

from hypergraphrag.base import BaseGraphStorage
from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import AuthError, ConfigurationError, ServiceUnavailable

from adapters.ingest_labels import ingest_key_for_write
from adapters.mask_contract import (
    HyperedgeKeyMissing,
    MaskContractViolated,
    kiem_ket_qua_che,
)
from core.ids import normalize_id, validate_space
from core.keys import FILTER_KEY_FIELD
from core.masking import mask
from core.permission import current_context
from core.slots import SLOT_ROLE_SET

# Khóa cấu hình đọc từ `global_config` (upstream truyền `asdict(HyperGraphRAG)`).
NEO4J_URI_KEY = "neo4j_uri"
NEO4J_USERNAME_KEY = "neo4j_username"
NEO4J_PASSWORD_KEY = "neo4j_password"
HEALTH_RETRIES_KEY = "neo4j_health_retries"
HEALTH_DELAY_KEY = "neo4j_health_delay"

# Đường graph hỏi tập khóa của namespace `hyperedges`: từ L1 trở lên (AD-4).
# Không phải `chunks`/`entities` - hai namespace đó là ngưỡng L2 của kho vector,
# còn ở đây một entity chỉ tới được qua hyperedge đã lọt filter.
GRAPH_NAMESPACE = "hyperedges"

# Hình dạng graph. Story 1.7 và pipeline ingest Epic 2 ghi theo đúng bộ hằng
# này; đổi một tên ở đây là đổi hợp đồng của cả hai.
LABEL_HYPEREDGE = "Hyperedge"
LABEL_ENTITY = "Entity"
EDGE_TYPE = "SLOT"
SLOT_FIELD = "slot"
SPACE_FIELD = "space"
NODE_ID_FIELD = "id"
ROLE_FIELD = "role"
ROLE_HYPEREDGE = "hyperedge"
ROLE_ENTITY = "entity"

# Số lần thử health-check và khoảng nghỉ giữa hai lần, tính ra khoảng 15 giây.
# Neo4j lên chậm hơn `api` là chuyện thường trên máy chủ 15 GB RAM (bẫy A2),
# nên chờ là hành vi đúng; chờ vô hạn thì không.
HEALTH_RETRIES_MAC_DINH = 30
HEALTH_DELAY_MAC_DINH = 0.5


class Neo4jUnavailable(RuntimeError):
    """Chờ hết hạn mà Neo4j vẫn chưa nhận kết nối.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp
    (AD-8, Consistency Conventions).
    """

    code = "NEO4J_UNAVAILABLE"


class SlotRoleInvalid(ValueError):
    """Cạnh mang vai slot ngoài danh mục 8 vai của `core/`.

    Danh mục slot là hợp đồng chung của prompt trích xuất, bảng chính sách và
    tầng che. Một vai lạ lọt xuống graph là một cạnh mà `masked_slots` không
    bao giờ tra trúng, tức là nội dung không bao giờ bị che.
    """

    code = "SLOT_ROLE_INVALID"


class NodeRoleInvalid(ValueError):
    """Node không khai `role` là hyperedge hay entity.

    Đồ thị hai phía mất nghĩa nếu có node không thuộc phía nào: tầng che tra
    khóa hyperedge theo chính `role` này.
    """

    code = "NODE_ROLE_INVALID"


class EdgeEndpointMissing(RuntimeError):
    """Ghi cạnh mà một trong hai đầu chưa có trong graph.

    `MATCH ... MATCH ... MERGE` của Cypher là một no-op im lặng khi MATCH
    trượt: cạnh biến mất mà đợt ingest vẫn xanh. Upstream luôn ghi node trước
    cạnh (`operate.py:214-248`), nên trượt ở đây nghĩa là thứ tự ghi đã đổi
    hoặc một lô ghi hỏng nửa chừng - cả hai đều phải nhìn thấy được.
    """

    code = "EDGE_ENDPOINT_MISSING"


NHAN_THEO_VAI = {ROLE_HYPEREDGE: LABEL_HYPEREDGE, ROLE_ENTITY: LABEL_ENTITY}


@dataclass
class Neo4jACLGraphStorage(BaseGraphStorage):
    """`BaseGraphStorage` của upstream, ruột là Neo4j có WHERE tiêm theo khóa."""

    # Driver tiêm sẵn, tùy chọn. Không tiêm thì adapter tự mở từ `global_config`.
    # Vòng đời kết nối (một driver dùng chung, đóng lúc tắt tiến trình) chốt ở
    # story 1.7 cùng chỗ gọi `initialize()`.
    neo4j_driver: AsyncDriver | None = None

    def __post_init__(self):
        cau_hinh = self.global_config or {}
        self._driver = self.neo4j_driver or self._dung_driver(cau_hinh)
        self._so_lan_thu = self._so_duong(
            cau_hinh, HEALTH_RETRIES_KEY, HEALTH_RETRIES_MAC_DINH, int, toi_thieu=1
        )
        self._nghi = self._so_duong(
            cau_hinh, HEALTH_DELAY_KEY, HEALTH_DELAY_MAC_DINH, float, toi_thieu=0
        )
        # Chỉ đóng driver do chính adapter mở: story 1.7 tiêm một driver dùng
        # chung cho nhiều storage, đóng hộ nó là làm hỏng hai namespace kia.
        self._tu_mo_driver = self.neo4j_driver is None
        self._da_san_sang = False
        self._khoa_san_sang = asyncio.Lock()

    @staticmethod
    def _so_duong(cau_hinh, khoa: str, mac_dinh, kieu, *, toi_thieu):
        """Knob cấu hình kiểm ngay lúc dựng adapter, không để hỏng giữa đường.

        `neo4j_health_retries=0` mà không kiểm thì health-check không thử lần
        nào rồi báo "Neo4j chưa lên" - một thông điệp nói sai nguyên nhân.
        """
        gia_tri = cau_hinh.get(khoa, mac_dinh)
        try:
            so = kieu(gia_tri)
        except (TypeError, ValueError):
            raise ValueError(f"{khoa} = {gia_tri!r} không phải số") from None
        if so < toi_thieu:
            raise ValueError(f"{khoa} phải >= {toi_thieu}, nhận được {so}")
        return so

    @staticmethod
    def _dung_driver(cau_hinh) -> AsyncDriver:
        """Driver async từ `global_config`; không trộn driver sync.

        Dựng driver không mở kết nối thật - `AsyncGraphDatabase.driver` chỉ
        dựng đối tượng. Phần chờ Neo4j sẵn sàng là `_dam_bao_san_sang`, chạy
        trước lần gọi đầu tiên, vì `__post_init__` là hàm đồng bộ và một I/O
        chặn ở đó đi ngược luật async toàn tuyến của dự án.
        """
        uri = cau_hinh.get(NEO4J_URI_KEY)
        if not uri:
            raise ValueError(
                f"thiếu {NEO4J_URI_KEY!r} trong global_config và không có driver"
                " nào được tiêm vào: adapter Neo4j không có gì để nối tới"
            )
        mat_khau = cau_hinh.get(NEO4J_PASSWORD_KEY)
        if not mat_khau:
            # `auth=(user, None)` chỉ hỏng ở lần gọi đầu, dưới dạng lỗi xác
            # thực - xa chỗ người sửa cấu hình đang nhìn.
            raise ValueError(
                f"thiếu {NEO4J_PASSWORD_KEY!r} trong global_config: Neo4j"
                " Community luôn bật xác thực"
            )
        return AsyncGraphDatabase.driver(
            uri,
            auth=(cau_hinh.get(NEO4J_USERNAME_KEY, "neo4j"), mat_khau),
        )

    async def _dam_bao_san_sang(self) -> None:
        """Chờ Neo4j nhận kết nối, đúng một lần cho mỗi instance (bẫy A2)."""
        if self._da_san_sang:
            return
        async with self._khoa_san_sang:
            if self._da_san_sang:
                return
            loi_cuoi = None
            for lan in range(self._so_lan_thu):
                try:
                    await self._driver.verify_connectivity()
                except (AuthError, ConfigurationError) as loi:
                    # Sai mật khẩu hay sai URI không tự lành theo thời gian;
                    # thử lại 30 lần chỉ làm chậm thông điệp đúng.
                    raise Neo4jUnavailable(
                        f"Neo4j từ chối kết nối vì cấu hình, không phải vì"
                        f" chưa sẵn sàng: {loi}"
                    ) from loi
                except (ServiceUnavailable, OSError) as loi:
                    loi_cuoi = loi
                    if lan + 1 < self._so_lan_thu:
                        await asyncio.sleep(self._nghi)
                else:
                    self._da_san_sang = True
                    return
            raise Neo4jUnavailable(
                f"Neo4j chưa nhận kết nối sau {self._so_lan_thu} lần thử:"
                f" {loi_cuoi}"
            ) from loi_cuoi

    async def close(self) -> None:
        """Đóng driver do chính adapter mở; story 1.7 gọi lúc tắt tiến trình.

        Driver tiêm từ ngoài thì không đóng: nó là của người tiêm, và một
        storage đóng hộ là hai storage còn lại mất kết nối. Cờ sẵn sàng mở lại
        để một instance dùng tiếp sau đó phải chờ Neo4j lần nữa.
        """
        self._da_san_sang = False
        if self._tu_mo_driver:
            await self._driver.close()

    # --- Mệnh đề lọc và chỗ gửi câu ----------------------------------------

    def _nhan_space(self, context) -> str:
        """Nhãn không gian, kiểm ký tự trước khi ghép vào câu (AD-12).

        `space` là thứ duy nhất được nội suy vào Cypher, mọi thứ khác đi bằng
        tham số. `validate_space` của `core/` là lớp canh cho phép nội suy đó.
        """
        return validate_space(context.space)

    @staticmethod
    def _dieu_kien(bien: str, context) -> str:
        """Mệnh đề lọc của một biến - node hay cạnh: `space` và khóa cùng chỗ.

        Cạnh cũng mang khóa riêng, và khóa đó có thể lệch khóa của hai đầu:
        khóa node là last-write-wins theo tài liệu nạp sau (khoản nợ 2.1), nên
        một cạnh sinh từ tài liệu hạn chế có thể nối hai node mà vai đang hỏi
        vẫn thấy. Không lọc cạnh là để lộ `source_id` và vai slot của một fact
        ngoài quyền.

        Ngữ cảnh hệ thống đọc thô nên chỉ còn `space` - ingest phải thấy hết
        để hợp nhất khóa, đó là ngoại lệ có đặc tả của AD-3.
        """
        dieu_kien = f"{bien}.{SPACE_FIELD} = $space"
        if not context.bypass_filter:
            dieu_kien += f" AND {bien}.{FILTER_KEY_FIELD} IN $keys"
        return dieu_kien

    def _tham_so_loc(self, context) -> dict:
        tham_so = {"space": context.space}
        if not context.bypass_filter:
            # sorted() để hai lần gọi cùng tập khóa ra cùng một câu, thứ giúp
            # so sánh giữa các lần chạy và đọc log dễ hơn.
            tham_so["keys"] = sorted(context.keys_for(GRAPH_NAMESPACE))
        return tham_so

    def _co_khoa_de_doc(self, context) -> bool:
        """Vai không có khóa nào thì không gửi câu nào đi.

        Gửi `IN []` là nhờ Neo4j lọc hộ một danh sách rỗng: đúng kết quả nhưng
        sai nguyên tắc, vì nó biến "không có quyền" thành một truy vấn bình
        thường. Nhánh đúng là không chạm kho.
        """
        return context.bypass_filter or bool(context.keys_for(GRAPH_NAMESPACE))

    async def _chay(self, cypher: str, **tham_so) -> list[dict]:
        """Một chỗ duy nhất gửi Cypher đi, để không có đường đọc thứ hai."""
        await self._dam_bao_san_sang()
        try:
            async with self._driver.session() as phien:
                ket_qua = await phien.run(cypher, **tham_so)
                return [dict(dong) async for dong in ket_qua]
        except ServiceUnavailable:
            # Neo4j rớt giữa phiên: mở lại cửa health-check để lời gọi sau chờ
            # nó lên thay vì dội lỗi driver thô mãi. Lời gọi này vẫn hỏng - thử
            # lại ngay ở đây là giấu mất một sự cố thật.
            self._da_san_sang = False
            raise

    # --- Ghi ---------------------------------------------------------------

    async def initialize(self) -> None:
        """Index cho đúng thứ mà mọi đường đọc bắt đầu bằng: tra node theo id.

        Index trên `filter_key` sẽ vô dụng ở đây, khác hẳn phía Qdrant: mọi câu
        đọc đều mở đầu bằng `MATCH (n:{space} {id: $id})` rồi mới lọc quyền
        trên chính node đã tra được, còn lân cận thì tới bằng cạnh chứ không
        bằng index. Không có index nào trên `id` thì mỗi lần đọc là một lần
        quét toàn nhãn.

        Lặp lại được (`IF NOT EXISTS`), nên gọi lại lúc khởi động không hỏng gì.
        """
        context = current_context()
        space = self._nhan_space(context)
        await self._chay(
            f"CREATE INDEX `node_id_{space}` IF NOT EXISTS\n"
            f"FOR (n:`{space}`) ON (n.{NODE_ID_FIELD})"
        )

    async def upsert_node(self, node_id: str, node_data: dict[str, str]) -> None:
        """Ghi một node mang khóa của phạm vi nhãn ingest đang mở.

        Hai cửa trước khi chạm kho: có ngữ cảnh (để biết `space`), có nhãn
        ingest (để biết khóa). Không có nhãn mặc định - một node không khóa
        hoặc vô hình vĩnh viễn, hoặc lọt vào mọi vai.
        """
        context = current_context()
        space = self._nhan_space(context)
        khoa = ingest_key_for_write()
        nhan = self._nhan_vai(node_data)
        await self._chay(
            f"MERGE (n:`{space}`:`{nhan}` {{{NODE_ID_FIELD}: $id}})\n"
            f"SET n += $props, n.{SPACE_FIELD} = $space,"
            f" n.{FILTER_KEY_FIELD} = $key, n.{NODE_ID_FIELD} = $id",
            id=normalize_id(node_id),
            props=dict(node_data),
            space=space,
            key=khoa,
        )

    @staticmethod
    def _nhan_vai(node_data: dict) -> str:
        vai = node_data.get(ROLE_FIELD)
        if vai not in NHAN_THEO_VAI:
            raise NodeRoleInvalid(
                f"node khai {ROLE_FIELD}={vai!r}; đồ thị hai phía chỉ có"
                f" {ROLE_HYPEREDGE!r} và {ROLE_ENTITY!r}"
            )
        return NHAN_THEO_VAI[vai]

    async def upsert_edge(
        self, source_node_id: str, target_node_id: str, edge_data: dict[str, str]
    ) -> None:
        """Ghi cạnh hyperedge → entity, mang vai slot và khóa quyền.

        Vai slot kiểm theo danh mục `core/` trước khi gửi câu đi. Cạnh **chưa**
        khai vai vẫn ghi được: `_merge_edges_then_upsert` của upstream hiện chỉ
        gửi `weight` và `source_id`, prompt trích xuất 8 vai thuộc story 2.4.
        Cấm cạnh thiếu vai ngay bây giờ là chặn chính đường e2e của cổng M1.
        """
        context = current_context()
        space = self._nhan_space(context)
        khoa = ingest_key_for_write()
        props = dict(edge_data)
        vai = props.get(SLOT_FIELD)
        if vai is not None and vai not in SLOT_ROLE_SET:
            raise SlotRoleInvalid(
                f"vai slot {vai!r} không có trong danh mục 8 vai của core/"
            )
        dong = await self._chay(
            f"MATCH (a:`{space}` {{{NODE_ID_FIELD}: $src}})\n"
            f"MATCH (b:`{space}` {{{NODE_ID_FIELD}: $tgt}})\n"
            f"MERGE (a)-[r:{EDGE_TYPE}]->(b)\n"
            f"SET r += $props, r.{SPACE_FIELD} = $space,"
            f" r.{FILTER_KEY_FIELD} = $key\n"
            "RETURN count(r) AS da_ghi",
            src=normalize_id(source_node_id),
            tgt=normalize_id(target_node_id),
            props=props,
            space=space,
            key=khoa,
        )
        if not dong or not dong[0]["da_ghi"]:
            raise EdgeEndpointMissing(
                f"không ghi được cạnh {source_node_id!r} -> {target_node_id!r}:"
                f" một trong hai đầu chưa có trong không gian {space!r}"
            )

    # --- Đọc ---------------------------------------------------------------

    async def has_node(self, node_id: str) -> bool:
        """Node ngoài quyền trả `False`, không phải lỗi: nó vắng mặt với vai này."""
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return False
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}` {{{NODE_ID_FIELD}: $id}})\n"
            f"WHERE {self._dieu_kien('n', context)}\n"
            "RETURN count(n) > 0 AS ton_tai_node",
            id=normalize_id(node_id),
            **self._tham_so_loc(context),
        )
        return bool(dong and dong[0]["ton_tai_node"])

    async def has_edge(self, source_node_id: str, target_node_id: str) -> bool:
        """Cạnh chỉ tồn tại khi *cả hai* đầu nằm trong quyền của vai đang hỏi."""
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return False
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (a:`{space}` {{{NODE_ID_FIELD}: $src}})"
            f"-[r:{EDGE_TYPE}]-(b:`{space}` {{{NODE_ID_FIELD}: $tgt}})\n"
            f"WHERE {self._dieu_kien('a', context)}"
            f" AND {self._dieu_kien('b', context)}"
            f" AND {self._dieu_kien('r', context)}\n"
            "RETURN count(r) > 0 AS ton_tai_canh",
            src=normalize_id(source_node_id),
            tgt=normalize_id(target_node_id),
            **self._tham_so_loc(context),
        )
        return bool(dong and dong[0]["ton_tai_canh"])

    async def get_node(self, node_id: str) -> dict | None:
        """Thuộc tính node, đã qua tầng che; ngoài quyền là `None`."""
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return None
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}` {{{NODE_ID_FIELD}: $id}})\n"
            f"WHERE {self._dieu_kien('n', context)}\n"
            "RETURN properties(n) AS thuoc_tinh_node\n"
            "LIMIT 1",
            id=normalize_id(node_id),
            **self._tham_so_loc(context),
        )
        if not dong:
            return None
        props = self._ban_ghi(dong[0]["thuoc_tinh_node"])
        return self._che(props, context, props.get(FILTER_KEY_FIELD))

    async def get_edge(
        self, source_node_id: str, target_node_id: str
    ) -> dict | None:
        """Thuộc tính cạnh, đã qua tầng che; ngoài quyền là `None`."""
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return None
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (a:`{space}` {{{NODE_ID_FIELD}: $src}})"
            f"-[r:{EDGE_TYPE}]-(b:`{space}` {{{NODE_ID_FIELD}: $tgt}})\n"
            f"WHERE {self._dieu_kien('a', context)}"
            f" AND {self._dieu_kien('b', context)}"
            f" AND {self._dieu_kien('r', context)}\n"
            "RETURN properties(r) AS thuoc_tinh_canh,"
            f" a.{ROLE_FIELD} AS vai_a, a.{FILTER_KEY_FIELD} AS khoa_a,"
            f" b.{ROLE_FIELD} AS vai_b, b.{FILTER_KEY_FIELD} AS khoa_b\n"
            "LIMIT 1",
            src=normalize_id(source_node_id),
            tgt=normalize_id(target_node_id),
            **self._tham_so_loc(context),
        )
        if not dong:
            return None
        d = dong[0]
        khoa = self._khoa_hyperedge(
            (d["vai_a"], d["khoa_a"]), (d["vai_b"], d["khoa_b"])
        )
        return self._che(self._ban_ghi(d["thuoc_tinh_canh"]), context, khoa)

    async def get_node_edges(self, source_node_id: str) -> list[tuple[str, str]]:
        """Cặp `(id, id_lân_cận)` của mọi cạnh còn thấy được.

        Hình dạng này là hợp đồng, không phải lựa chọn: `operate.py:884-925`
        đưa thẳng `e[1]` vào `get_edge`/`get_node`. Lân cận ngoài quyền vắng
        mặt khỏi danh sách chứ không phải xuất hiện với nội dung rỗng - một cái
        tên bị che vẫn kể rằng có một fact ở đó.

        Tầng che nhận cả vai slot của cạnh, vì tên node lân cận điền vào một
        slot đang bị che thì phải bị che như nội dung slot (AD-9, story 1.6).
        """
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return []
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}` {{{NODE_ID_FIELD}: $id}})"
            f"-[r:{EDGE_TYPE}]-(m:`{space}`)\n"
            f"WHERE {self._dieu_kien('n', context)}"
            f" AND {self._dieu_kien('m', context)}"
            f" AND {self._dieu_kien('r', context)}\n"
            f"RETURN n.{NODE_ID_FIELD} AS nguon, m.{NODE_ID_FIELD} AS lan_can,"
            f" r.{SLOT_FIELD} AS slot, n.{ROLE_FIELD} AS vai_nguon,"
            f" n.{FILTER_KEY_FIELD} AS khoa_nguon,"
            f" m.{ROLE_FIELD} AS vai_lan_can,"
            f" m.{FILTER_KEY_FIELD} AS khoa_lan_can",
            id=normalize_id(source_node_id),
            **self._tham_so_loc(context),
        )
        cac_cap = []
        for d in dong:
            # Vai của lân cận đọc từ chính dữ liệu, không suy ra từ vai của
            # node nguồn: suy ra là một giả định, và giả định sai ở đây nghĩa
            # là che một loại nội dung bằng luật của loại nội dung khác.
            khoa = self._khoa_hyperedge(
                (d["vai_nguon"], d["khoa_nguon"]),
                (d["vai_lan_can"], d["khoa_lan_can"]),
            )
            # Tên trường cố ý không phải `source`: `source` là *một trong 8 vai
            # slot*, và tầng che của story 1.6 tra bản ghi theo tên vai. Hai
            # nghĩa trùng tên trong một dict là một lỗi chờ sẵn.
            ban_ghi = self._che(
                {
                    "node_id": d["nguon"],
                    "neighbor_id": d["lan_can"],
                    SLOT_FIELD: d["slot"],
                },
                context,
                khoa,
            )
            cac_cap.append((ban_ghi["node_id"], ban_ghi["neighbor_id"]))
        return cac_cap

    async def node_degree(self, node_id: str) -> int:
        """Số lân cận *còn thấy được*, không phải tổng số cạnh.

        Degree đi thẳng vào xếp hạng ngữ cảnh trả về (`operate.py:754,1041`),
        nên một số đếm không co theo quyền tự nó đã kể rằng còn fact khác tồn
        tại. Node ngoài quyền trả 0, cùng ngữ nghĩa với "không thấy gì".
        """
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return 0
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}` {{{NODE_ID_FIELD}: $id}})\n"
            f"WHERE {self._dieu_kien('n', context)}\n"
            f"OPTIONAL MATCH (n)-[r:{EDGE_TYPE}]-(m:`{space}`)\n"
            f"WHERE {self._dieu_kien('m', context)}"
            f" AND {self._dieu_kien('r', context)}\n"
            "RETURN count(r) AS bac",
            id=normalize_id(node_id),
            **self._tham_so_loc(context),
        )
        return int(dong[0]["bac"]) if dong else 0

    async def edge_degree(self, src_id: str, tgt_id: str) -> int:
        """Tổng hai `node_degree`, đúng ngữ nghĩa upstream.

        Giữ nguyên công thức của upstream nên nó co theo quyền bằng chính luật
        của `node_degree`, không cần một luật thứ hai để lệch với luật kia.
        """
        return await self.node_degree(src_id) + await self.node_degree(tgt_id)

    @staticmethod
    def _ban_ghi(props) -> dict:
        """Bản ghi rời adapter: bỏ `space`, giữ khóa quyền.

        `space` là chuyện nội bộ của cách ly dữ liệu, mà thứ upstream làm với
        dict này là ghép thẳng vào chuỗi ngữ cảnh gửi cho LLM (`operate.py`).
        Khóa quyền thì ở lại: nó là nhãn của chính mục đó, thứ tầng che tra
        `masked_slots` theo và thứ cho phép truy nguyên một mục đã ra ngoài.
        """
        return {k: v for k, v in dict(props).items() if k != SPACE_FIELD}

    @staticmethod
    def _khoa_hyperedge(dau_a: tuple, dau_b: tuple) -> str:
        """Khóa che của một cạnh = khóa của đầu là hyperedge (AD-9).

        Đồ thị hai phía nên đúng một trong hai đầu là hyperedge. Không đầu nào
        là hyperedge nghĩa là dữ liệu hỏng; lấy đại khóa của đầu kia là che một
        loại nội dung bằng luật của loại nội dung khác, tức là che sai - có thể
        che thừa, có thể để hở. Nổ ở đây, không đoán.
        """
        for vai, khoa in (dau_a, dau_b):
            if vai == ROLE_HYPEREDGE:
                if not khoa:
                    raise HyperedgeKeyMissing(
                        "node hyperedge không mang khóa quyền: không tra được"
                        " `masked_slots` nên không che được"
                    )
                return khoa
        raise HyperedgeKeyMissing(
            f"cạnh nối hai đầu vai {dau_a[0]!r} và {dau_b[0]!r}: đồ thị hai"
            " phía phải có đúng một đầu là hyperedge"
        )

    @staticmethod
    def _che(ban_ghi: dict, context, khoa: str | None) -> dict:
        """Cửa duy nhất gọi tầng che, để không method nào quên gọi (AD-9).

        Ngữ cảnh hệ thống đọc thô nên không che. Khóa truyền vào là khóa của
        hyperedge liên quan, kể cả khi lời gọi bắt đầu từ phía entity; khóa
        vắng là fail-closed chứ không phải che bằng khóa rỗng.
        """
        if context.bypass_filter:
            return ban_ghi
        if not khoa:
            raise HyperedgeKeyMissing(
                f"bản ghi {ban_ghi!r} không truy ra khóa hyperedge để che"
            )
        return kiem_ket_qua_che(mask(ban_ghi, context, khoa), ban_ghi, repr(ban_ghi))
