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
đường ghi và cùng một đường đọc, không có nhánh riêng. Từ story 2.4 vai là
bắt buộc và nằm trong khóa MERGE của cạnh: một entity điền hai vai của cùng
hyperedge là hai cạnh; `get_node_edges` một bản ghi mỗi cạnh (che theo vai
từng cạnh), `get_edge` gộp mọi cạnh của cặp, `node_degree` đếm distinct lân cận.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Mapping

from hypergraphrag.base import BaseGraphStorage
from hypergraphrag.prompt import GRAPH_FIELD_SEP
from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import (
    AuthError,
    ConfigurationError,
    ConstraintError,
    Neo4jError,
    ServiceUnavailable,
)

from adapters.cua_khoa_doc import khoa_doc
from adapters.do_thi import DoThiNgoaiQuyen, chuan_hoa_ids
from adapters.doi_chieu import KHO_GRAPH, ghi_vao_so, ten_kho_vector
from adapters.ingest_labels import (
    bat_buoc_ngu_canh_he_thong,
    ingest_key_for_write,
)
from adapters.mask_contract import (
    HyperedgeKeyMissing,
    MaskContractViolated,
    kiem_ket_qua_che,
)
from adapters.nhom_phu_trach import BangNhomPhuTrach, bang_nhom_cho
from adapters.sensitivity_loader import bang_hang_cho
from core.ids import normalize_id, validate_space
from core.keys import CHUA_GHI, FILTER_KEY_FIELD, split_key
# `SLOT_FIELD` là hợp đồng giữa tầng che và adapter này: nhãn vai trên cạnh
# Neo4j và tên trường mà tầng che đọc để biết bản ghi khai vai gì phải là một.
# Khai bản thứ hai ở đây là hai hằng trôi dạt được, và trôi dạt nghĩa là tên
# lân cận không bao giờ bị che.
from core.masking import (
    MASK_NAMESPACE,
    MASK_REASON_L2_ONLY,
    MaskItemOutOfPermission,
    SlotRoleUnknown,
    NEIGHBOR_FIELD,
    NEIGHBOR_NO_KEY_FIELD,
    HYPEREDGE_ID_FIELD,
    OWNER_GROUP_FIELD,
    SLOT_FIELD,
    SLOTS_FIELD,
    dau_che_truong,
    la_dau_che,
    mask,
)
from core.permission import current_context
from core.slots import SLOT_ROLE_SET

# Khóa cấu hình đọc từ `global_config` (upstream truyền `asdict(HyperGraphRAG)`).
NEO4J_URI_KEY = "neo4j_uri"
NEO4J_USERNAME_KEY = "neo4j_username"
NEO4J_PASSWORD_KEY = "neo4j_password"
NEO4J_DATABASE_KEY = "neo4j_database"
HEALTH_RETRIES_KEY = "neo4j_health_retries"
HEALTH_DELAY_KEY = "neo4j_health_delay"

# Đường graph hỏi tập khóa của namespace `hyperedges`: từ L1 trở lên (AD-4).
# Không phải `chunks`/`entities` - hai namespace đó là ngưỡng L2 của kho vector,
# còn ở đây một entity chỉ tới được qua hyperedge đã lọt filter.
#
# Cùng một hằng với cửa fail-closed của tầng che, không phải hai bản trùng giá
# trị: nếu đường đọc lọc theo một tập mà tầng che kiểm theo một tập khác thì
# mọi bản ghi hợp lệ đều nổ, hoặc tệ hơn, không bản nào nổ khi lẽ ra phải nổ.
GRAPH_NAMESPACE = MASK_NAMESPACE

# Hình dạng graph. Story 1.7 và pipeline ingest Epic 2 ghi theo đúng bộ hằng
# này; đổi một tên ở đây là đổi hợp đồng của cả hai.
LABEL_HYPEREDGE = "Hyperedge"
LABEL_ENTITY = "Entity"
EDGE_TYPE = "SLOT"
SPACE_FIELD = "space"
NODE_ID_FIELD = "id"
ROLE_FIELD = "role"
ROLE_HYPEREDGE = "hyperedge"
ROLE_ENTITY = "entity"

# Hai trường của node entity mà upstream đọc để dựng bảng Entities gửi LLM
# (`operate.py:774-784`, `:997-1006` đều đọc đúng hai cái này bằng `.get`).
DESCRIPTION_FIELD = "description"
ENTITY_TYPE_FIELD = "entity_type"

# Mô tả entity hỏi tập khóa của namespace `entities`: ngưỡng L2 (NFR-06). Khác
# `GRAPH_NAMESPACE` một cách có chủ đích - đường graph *đi tới* một node từ L1
# trở lên, nhưng `description` của node entity là văn bản viết lại từ chính giá
# trị slot, nên nó chỉ vào ngữ cảnh khi vai đạt L2 với nguồn (FR-05).
ENTITY_NAMESPACE = "entities"

# Số lần thử health-check và khoảng nghỉ giữa hai lần, tính ra khoảng 15 giây.
# Neo4j lên chậm hơn `api` là chuyện thường trên máy chủ 15 GB RAM (bẫy A2),
# nên chờ là hành vi đúng; chờ vô hạn thì không.
HEALTH_RETRIES_MAC_DINH = 30
HEALTH_DELAY_MAC_DINH = 0.5

# Tài khoản mặc định của Neo4j Community, cũng là giá trị mà `docker-compose.yml`
# đặt cho `NEO4J_USERNAME`. Một hằng, một chỗ: `adapters/engine.py` nhập lại nó
# thay vì viết bản thứ hai, cùng luật với hai hằng health-check ở trên.
NEO4J_USERNAME_MAC_DINH = "neo4j"

# Database mặc định của Neo4j Community. Community chỉ có một database nên giá
# trị này gần như không đổi, nhưng truyền `database=` tường minh thì mọi phiên
# nói rõ nó làm việc trên đâu thay vì dựa vào mặc định ngầm của driver - và đó
# là điều kiện để đường lùi Enterprise (một database mỗi `space`) sau này chỉ
# phải đổi cấu hình. Khoản nợ có địa chỉ 2.1, ledger story 1.4.
NEO4J_DATABASE_MAC_DINH = "neo4j"


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


class SlotRoleMissing(ValueError):
    """Cạnh không khai vai slot (story 2.4).

    Từ 2.4 mọi cạnh trong graph đều sinh từ một fact 8 vai, nên một cạnh không
    vai là một cạnh mà tầng che không tra được luật nào ở đường
    `get_node_edges` - để nó vào kho là fail-open im lặng. Trước 2.4 cạnh thiếu
    vai được chấp nhận vì upstream chưa gửi vai (ledger 1.4); quyết định ở 2.4
    là đóng cửa đó.
    """

    code = "SLOT_ROLE_MISSING"


class NodeRoleInvalid(ValueError):
    """Node không khai `role` là hyperedge hay entity.

    Đồ thị hai phía mất nghĩa nếu có node không thuộc phía nào: tầng che tra
    khóa hyperedge theo chính `role` này.
    """

    code = "NODE_ROLE_INVALID"


class NodeIdRoleConflict(RuntimeError):
    """Cùng một id ghi một lần dưới vai hyperedge, một lần dưới vai entity.

    `MERGE (n:{space}:{nhan} {id})` khóa theo *cả* nhãn, nên trước story 2.1
    hai vai khác nhau cho hai node cùng id: `get_node` (LIMIT 1) trả node nào là
    không xác định và `node_degree` gộp cạnh của cả hai. Ràng buộc duy nhất
    `id` theo `space` đóng cửa đó, và cửa đóng lại phải *nổ* chứ không gộp: gộp
    hai vai vào một node là trộn một hyperedge với một entity, hai thứ mà tầng
    che xử lý bằng hai luật khác nhau.

    Đây cũng là điều kiện nền của luật hợp nhất khóa: read-merge-write đọc
    "khóa của node có id này", câu đó chỉ có nghĩa khi một id là một node.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).
    """

    code = "NODE_ID_ROLE_CONFLICT"


class NodeIdConstraintUnbuildable(RuntimeError):
    """Không dựng được ràng buộc duy nhất vì kho *đã* có id trùng khác vai.

    Ca thật của một kho nạp bằng bản trước story 2.1: `MERGE` khóa theo cả nhãn
    nên cùng một id có thể đang là hai node. Neo4j từ chối `CREATE CONSTRAINT`
    khi dữ liệu hiện có vi phạm, và nó dội một lỗi thô không nói phải làm gì.
    Đổi thành mã lỗi của dự án kèm đúng một câu chỉ việc: dọn id trùng (hoặc
    re-ingest cả `space`) rồi chạy lại bước khởi động.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).
    """

    code = "NODE_ID_CONSTRAINT_UNBUILDABLE"


class EntityMissing(RuntimeError):
    """Đặt lại một entity không có trong graph của `space` này.

    `MATCH ... SET` không khớp là một no-op im lặng của Cypher; với đường dựng
    lại entity chung của re-ingest (story 2.3) thì im lặng nghĩa là khóa mới
    tính không được ghi và bước đối chiếu sẽ báo lệch ở một chỗ xa nguyên nhân.
    """

    code = "ENTITY_MISSING"


class HyperedgeMissing(RuntimeError):
    """Đặt lại một hyperedge không có trong graph của `space` này; cùng lý do với `EntityMissing`."""

    code = "HYPEREDGE_MISSING"


class EdgeEndpointMissing(RuntimeError):
    """Ghi cạnh mà một trong hai đầu chưa có trong graph.

    `MATCH ... MATCH ... MERGE` của Cypher là một no-op im lặng khi MATCH
    trượt: cạnh biến mất mà đợt ingest vẫn xanh. Upstream luôn ghi node trước
    cạnh (`operate.py:214-248`), nên trượt ở đây nghĩa là thứ tự ghi đã đổi
    hoặc một lô ghi hỏng nửa chừng - cả hai đều phải nhìn thấy được.
    """

    code = "EDGE_ENDPOINT_MISSING"


NHAN_THEO_VAI = {ROLE_HYPEREDGE: LABEL_HYPEREDGE, ROLE_ENTITY: LABEL_ENTITY}

logger = logging.getLogger(__name__)


@dataclass
class Neo4jACLGraphStorage(BaseGraphStorage):
    """`BaseGraphStorage` của upstream, ruột là Neo4j có WHERE tiêm theo khóa."""

    # Bước đối chiếu hai kho hỏi thuộc tính này (`adapters/doi_chieu.py`).
    # `False` vì ca hợp nhất ra "không khóa" giữ node lại và chỉ gỡ thuộc tính
    # khóa, nên "vắng" ở đây đúng là chưa từng ghi. Không chú kiểu: annotation
    # sẽ biến nó thành field của dataclass.
    VANG_LA_MO_HO = False

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
        # Database của mọi phiên, truyền tường minh thay vì để driver dùng mặc
        # định ngầm của server.
        self._database = cau_hinh.get(NEO4J_DATABASE_KEY) or NEO4J_DATABASE_MAC_DINH
        # Bảng hạng độ nhạy, nạp lúc dựng adapter: cùng nguồn với hai adapter
        # kia, nên ba đường ghi không chạy trên hai bảng hạng khác nhau.
        self._bang_hang = bang_hang_cho(cau_hinh)
        # Bảng nhóm phụ trách, cùng khe tiêm và cùng lúc: nó đọc `global_config`
        # của chính adapter này, không phải một hằng của tiến trình. Vắng khóa
        # thì `bang_nhom_cho` trả đúng bảng đã nhớ của repo, nên đường chạy hôm
        # nay không đọc thêm file nào. Bảng hạng để đối chiếu cũng lấy từ cấu
        # hình này, nên một adapter không bao giờ chạy trên hai bảng lệch nhau.
        self._bang_nhom = bang_nhom_cho(cau_hinh)

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
            auth=(
                cau_hinh.get(NEO4J_USERNAME_KEY) or NEO4J_USERNAME_MAC_DINH,
                mat_khau,
            ),
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
        khóa node là kết quả hợp nhất đa nguồn (story 2.1) còn khóa cạnh là
        khóa của tài liệu ghi cạnh đó, nên một cạnh sinh từ tài liệu hạn chế có
        thể nối hai node mà vai đang hỏi vẫn thấy. Không lọc cạnh là để lộ
        `source_id` và vai slot của một fact ngoài quyền.

        Ngữ cảnh hệ thống đọc thô nên chỉ còn `space` - ingest phải thấy hết
        để hợp nhất khóa, đó là ngoại lệ có đặc tả của AD-3.
        """
        dieu_kien = f"{bien}.{SPACE_FIELD} = $space"
        if not context.bypass_filter:
            dieu_kien += f" AND {bien}.{FILTER_KEY_FIELD} IN $keys"
        return dieu_kien

    @staticmethod
    def _dieu_kien_lan_can(bien: str, context) -> str:
        """Mệnh đề lọc của biến **lân cận** trong `get_node_edges` (AD-9, AD-5).

        Khác `_dieu_kien` đúng một nhánh: node **vai entity không khóa** cũng đi
        qua. AD-5 chốt "node entity không khóa chỉ đạt tới được qua hyperedge đã
        lọc và tên luôn bị che cứng qua tầng AD-9", và đây là chỗ cài nửa đầu
        câu đó; nửa sau nằm ở `core/masking.py`.

        **Nới đúng một đường, và nó không phải một đường mới.** Lân cận tới được
        chỉ vì lời gọi đã bắt đầu từ một node mà vai *được* thấy: biến nguồn `n`
        và biến cạnh `r` giữ nguyên điều kiện chặt, nên không có cách nào bắt
        đầu từ một node ngoài quyền để với tới đây. Sáu đường đọc còn lại
        (`has_node`, `has_edge`, `get_node`, `get_edge`, `node_degree`,
        `edge_degree`) **không** dùng mệnh đề này - AD-9 chỉ nói về đường làm
        giàu lân cận của `get_node_edges`, nên một node không khóa vẫn không tra
        thẳng được, không đếm vào degree, và không tự nó là một cạnh đọc được.

        Ràng thêm `role = entity` chứ không nới cho mọi node không khóa: một
        node **hyperedge** không khóa là một fact mà không vai nào được thấy, và
        cho nó vào danh sách lân cận là kể ra rằng fact đó tồn tại. Chỉ entity -
        thứ mà AD-5 gọi tên - mới đi qua.

        Ngữ cảnh hệ thống đọc thô nên chỉ còn `space`, như mọi đường khác.
        """
        dieu_kien = f"{bien}.{SPACE_FIELD} = $space"
        if not context.bypass_filter:
            dieu_kien += (
                f" AND ({bien}.{FILTER_KEY_FIELD} IN $keys"
                f" OR ({bien}.{FILTER_KEY_FIELD} IS NULL"
                f" AND {bien}.{ROLE_FIELD} = $vai_entity))"
            )
        return dieu_kien

    def _tham_so_loc(self, context) -> dict:
        tham_so = {"space": context.space}
        loc_theo = khoa_doc(context, GRAPH_NAMESPACE).loc_theo
        if loc_theo is not None:
            # sorted() để hai lần gọi cùng tập khóa ra cùng một câu, thứ giúp
            # so sánh giữa các lần chạy và đọc log dễ hơn.
            tham_so["keys"] = sorted(loc_theo)
        return tham_so

    def _co_khoa_de_doc(self, context) -> bool:
        """Vai không có khóa nào thì không gửi câu nào đi.

        Gửi `IN []` là nhờ Neo4j lọc hộ một danh sách rỗng: đúng kết quả nhưng
        sai nguyên tắc, vì nó biến "không có quyền" thành một truy vấn bình
        thường. Nhánh đúng là không chạm kho.

        Luật sống ở `adapters/cua_khoa_doc.py`, dùng chung với hai adapter kia
        (retro Epic 1 F5). Method này giữ nguyên tên và nguyên chữ ký để mọi
        điểm gọi cùng mọi test cũ không đổi.
        """
        return not khoa_doc(context, GRAPH_NAMESPACE).khong_thay_gi

    async def _chay(self, cypher: str, *, ghi: bool = False, **tham_so) -> list[dict]:
        """Một chỗ duy nhất gửi Cypher đi, để không có đường đọc thứ hai.

        Transaction có quản lý (`execute_read`/`execute_write`) chứ không phải
        `session.run` autocommit, và `database=` truyền tường minh - hai khoản
        nợ có địa chỉ 2.1 từ ledger story 1.4. Cái được là retry của driver cho
        lỗi thoáng qua (`TransientError`, đổi leader): với autocommit thì một
        đợt nạp corpus dài gặp một lần đổi leader là hỏng cả đợt, còn ở đây
        driver chạy lại chính hàm công việc.

        Vì driver có thể chạy lại `cong_viec`, hàm đó phải **đọc hết** kết quả
        bên trong transaction và không được mang trạng thái nào ra ngoài. Nó
        đúng là như vậy: dựng list rồi trả, không đụng gì của adapter.

        `ghi` chia hai đường vì chúng khác nhau ở phía server chứ không chỉ ở
        tên: `execute_read` đi tới replica đọc được và không mở transaction ghi.
        Mặc định là đọc, nên một đường đọc mới quên khai vẫn an toàn; đường ghi
        thì có đúng ba nơi và chúng khai tường minh.
        """
        await self._dam_bao_san_sang()

        async def cong_viec(tx):
            ket_qua = await tx.run(cypher, **tham_so)
            return [dict(dong) async for dong in ket_qua]

        try:
            async with self._driver.session(database=self._database) as phien:
                if ghi:
                    return await phien.execute_write(cong_viec)
                return await phien.execute_read(cong_viec)
        except ServiceUnavailable:
            # Neo4j rớt giữa phiên: mở lại cửa health-check để lời gọi sau chờ
            # nó lên thay vì dội lỗi driver thô mãi. Lời gọi này vẫn hỏng - thử
            # lại ngay ở đây là giấu mất một sự cố thật.
            self._da_san_sang = False
            raise

    # --- Ghi ---------------------------------------------------------------

    async def initialize(self) -> None:
        """Ràng buộc duy nhất `id` theo `space` - vừa là luật, vừa là index.

        Ràng buộc là **điều kiện**, không phải một tính năng kèm.
        `MERGE (n:{space}:{nhan} {id})` khóa theo cả nhãn, nên trước story 2.1
        cùng một id ghi dưới hai vai là hai node; read-merge-write đọc "khóa của
        node có id này" trên nền đó sẽ đọc trúng node nào là không xác định, tức
        luật hợp nhất chạy trên dữ liệu sai. Ràng buộc phải vào trước, và id
        trùng khác vai phải nổ (`NodeIdRoleConflict`) chứ không gộp.

        Nó thay luôn index của story 1.7: Neo4j dựng một index hậu thuẫn cho
        mỗi ràng buộc duy nhất, nên đường tra `MATCH (n:{space} {id: $id})` mà
        mọi câu đọc mở đầu bằng vẫn có index - hai thứ chứ không phải hai lần.
        Index cũ bị gỡ ở dòng đầu vì Neo4j từ chối dựng ràng buộc khi đã có một
        index tương đương; nếu không có nó thì `initialize()` chạy trên một kho
        đã nạp bằng bản cũ sẽ hỏng, và đó là kho duy nhất mà việc này đáng lo.

        Lặp lại được (`IF EXISTS`/`IF NOT EXISTS`), nên gọi lại lúc khởi động
        không hỏng gì.
        """
        context = current_context()
        space = self._nhan_space(context)
        await self._chay(f"DROP INDEX `node_id_{space}` IF EXISTS", ghi=True)
        try:
            await self._chay(
                f"CREATE CONSTRAINT `id_duy_nhat_{space}` IF NOT EXISTS\n"
                f"FOR (n:`{space}`) REQUIRE n.{NODE_ID_FIELD} IS UNIQUE",
                ghi=True,
            )
        except Neo4jError as loi:
            # Kho nạp bằng bản trước story 2.1 có thể *đã* chứa id trùng khác
            # vai - đúng ca story này mô tả. Neo4j từ chối dựng ràng buộc và
            # dội một lỗi thô; đổi thành mã lỗi của dự án kèm câu chỉ việc,
            # ngay ở chỗ còn biết `space` nào.
            if not self._la_loi_du_lieu_vi_pham(loi):
                raise
            raise NodeIdConstraintUnbuildable(
                f"không dựng được ràng buộc duy nhất `id` cho không gian"
                f" {space!r}: dữ liệu hiện có đã vi phạm, tức đang có id trùng"
                " dưới hai vai khác nhau. Dọn id trùng (hoặc re-ingest cả"
                f" không gian) rồi chạy lại bước khởi động. Lỗi gốc: {loi}"
            ) from loi

    # Mã lỗi Neo4j cho "dựng ràng buộc hỏng vì dữ liệu hiện có đã vi phạm".
    # Đo trên Neo4j 5.26 thật: nó là `DatabaseError`, không phải `ClientError`,
    # nên nơi bắt phải là `Neo4jError`. Nhận theo *mã* chứ không theo thông
    # điệp: thông điệp đổi theo phiên bản, mã thì là hợp đồng.
    MA_DUNG_RANG_BUOC_HONG = "Neo.DatabaseError.Schema.ConstraintCreationFailed"

    @classmethod
    def _la_loi_du_lieu_vi_pham(cls, loi: Neo4jError) -> bool:
        """Đúng lỗi "dữ liệu hiện có vi phạm ràng buộc", tách khỏi mọi lỗi khác.

        Mã khác (cú pháp sai, thiếu quyền, DB chưa lên) đi tiếp nguyên trạng -
        nuốt hết là biến một lỗi cấu hình thành một câu nói sai nguyên nhân.
        """
        return (getattr(loi, "code", "") or "") == cls.MA_DUNG_RANG_BUOC_HONG

    async def khoa_hien_co(self, ids: list[str]) -> dict[str, object]:
        """Khóa quyền mà graph đang giữ cho từng id node, không đọc gì khác.

        Bước đọc của read-merge-write (FR-11) và cửa mà bước đối chiếu hai kho
        hỏi. Chỉ trả trường khóa nên tầng che không áp dụng; chạy dưới cờ system
        vì bị lọc theo khóa của tài liệu đang nạp thì nó không bao giờ thấy khóa
        khác scope cần hợp nhất.

        Ba trạng thái: `CHUA_GHI` (không có node id đó trong `space` này),
        `KHONG_KHOA` (node ở lại mà không mang khóa - kết quả hợp nhất khóa đa
        nguồn khác scope), hoặc một khóa thật. Graph là kho **nhớ** được trạng
        thái không khóa: node cấu trúc ở lại để hyperedge vẫn nối được, chỉ là
        không vai nào tới được nó vì mọi câu đọc ràng khóa trên từng biến.
        """
        bat_buoc_ngu_canh_he_thong("đọc khóa hiện có của kho graph")
        if not ids:
            return {}
        context = current_context()
        space = self._nhan_space(context)
        id_chuan = [normalize_id(i) for i in ids]
        # `ghi=True` dù đây là một câu đọc: bước đọc khóa cũ của
        # read-merge-write phải nhìn thấy chính thứ mà lần ghi kế tiếp sẽ đè
        # lên. `execute_read` đi tới replica đọc được, và một replica trễ một
        # nhịp là luật hợp nhất chạy trên khóa cũ hơn khóa thật - tức nới quyền
        # ra mà không ai biết. Đường ghi thì luôn tới leader.
        dong = await self._chay(
            f"MATCH (n:`{space}`)\n"
            f"WHERE {self._dieu_kien('n', context)}"
            f" AND n.{NODE_ID_FIELD} IN $ids\n"
            f"RETURN n.{NODE_ID_FIELD} AS id_node,"
            f" n.{FILTER_KEY_FIELD} AS khoa_node",
            ghi=True,
            ids=id_chuan,
            **self._tham_so_loc(context),
        )
        trong_kho = {d["id_node"]: d["khoa_node"] for d in dong}
        return {
            goc: trong_kho.get(chuan, CHUA_GHI)
            for goc, chuan in zip(ids, id_chuan)
        }

    async def upsert_node(self, node_id: str, node_data: dict[str, str]) -> None:
        """Ghi một node, khóa hợp nhất với khóa mà node đang mang (FR-11).

        Ba cửa trước khi chạm kho: có ngữ cảnh (để biết `space`), node khai vai
        hợp lệ, và có nhãn ingest dưới ngữ cảnh hệ thống với loại nội dung có
        hạng độ nhạy. Không có nhãn mặc định - một node không khóa vì *quên
        nhãn* thì hoặc vô hình vĩnh viễn, hoặc lọt vào mọi vai.

        Read-merge-write, không phải last-write-wins: trước story 2.1 một entity
        nạp lần sau đè khóa của lần trước, nên nhãn quyền của nó phụ thuộc thứ
        tự nạp tài liệu. Nay khóa cũ được đọc lại rồi hợp nhất ở cửa chung.

        Ca hợp nhất ra "không khóa" ghi `filter_key = null`, tức Neo4j gỡ hẳn
        thuộc tính đó. Node **ở lại**: nó là node cấu trúc của đồ thị hai phía,
        xóa nó là cắt cả những hyperedge hợp lệ nối vào. Không vai nào tới được
        nó, vì mọi câu đọc ràng `n.filter_key IN $keys` trên *từng* biến và một
        thuộc tính vắng không khớp giá trị nào.
        """
        context = current_context()
        space = self._nhan_space(context)
        nhan = self._nhan_vai(node_data)
        id_chuan = normalize_id(node_id)
        khoa = ingest_key_for_write(
            (await self.khoa_hien_co([id_chuan]))[id_chuan],
            hang=self._bang_hang.hang,
        )
        # Ghi sổ **ý định** trước khi chạm kho, cùng luật với hai adapter kia:
        # hỏng giữa chừng thì id phải nằm trong sổ mà khóa vắng ở kho (NFR-03).
        ghi_vao_so(
            id_join=id_chuan,
            kho=KHO_GRAPH,
            id_trong_kho=id_chuan,
            kho_doi=ten_kho_vector(
                "hyperedges" if nhan == LABEL_HYPEREDGE else "entities"
            ),
        )
        try:
            await self._chay(
                f"MERGE (n:`{space}`:`{nhan}` {{{NODE_ID_FIELD}: $id}})\n"
                f"SET n += $props, n.{SPACE_FIELD} = $space,"
                f" n.{FILTER_KEY_FIELD} = $key, n.{NODE_ID_FIELD} = $id",
                ghi=True,
                id=id_chuan,
                props=dict(node_data),
                space=space,
                key=khoa,
            )
        except ConstraintError as loi:
            # Ràng buộc duy nhất bắt được đúng ca id trùng khác vai: MERGE theo
            # nhãn khác không khớp node đã có nên nó *tạo mới*, và node mới vi
            # phạm `id IS UNIQUE` trong `space`. Đổi thành mã lỗi của dự án
            # ngay tại đây, nơi còn biết id và vai nào gây ra nó.
            #
            # Chỉ đổi khi đúng ràng buộc *của mình*: một ràng buộc khác do
            # người vận hành thêm vào (trên nhãn khác, hay trên thuộc tính
            # khác của cùng nhãn) nói về một luật khác, và đổi nó thành "id
            # trùng khác vai" là một thông điệp sai nguyên nhân.
            #
            # Nhận theo nhãn `space` và thuộc tính `id` trong thông điệp, không
            # theo tên ràng buộc: đo trên Neo4j 5.26 thật thì thông điệp là
            # "Node(39) already exists with label `{space}` and property `id`
            # = 'X'" - nó **không** mang tên ràng buộc, nên lọc theo tên là một
            # nhánh không bao giờ khớp và mọi lỗi đều dội nguyên.
            thong_diep = str(loi)
            if f"`{space}`" not in thong_diep or f"`{NODE_ID_FIELD}`" not in thong_diep:
                raise
            raise NodeIdRoleConflict(
                f"id {id_chuan!r} đã tồn tại trong không gian {space!r} dưới"
                f" một vai khác, nay ghi lại dưới vai {node_data.get(ROLE_FIELD)!r}:"
                " một id là một node, không gộp hai vai vào một"
            ) from loi

    # --- Đường xóa và ghi thẳng của pipeline re-ingest (story 2.3) ----------

    async def xoa_node(self, ids: list[str]) -> int:
        """`DETACH DELETE` các node theo id trong `space` hiện tại; trả số đã xóa.

        Đường xóa của re-ingest và xóa tài liệu: hyperedge cũ của tài liệu và
        entity không còn hyperedge nào nối rời graph cùng mọi cạnh của chúng.
        Cùng cửa AD-3 với `upsert_node`; id không có thì bỏ qua. Không vào sổ
        đợt: node đã xóa không còn gì để đối chiếu.
        """
        bat_buoc_ngu_canh_he_thong("xóa node graph")
        if not ids:
            return 0
        context = current_context()
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}`)\n"
            f"WHERE {self._dieu_kien('n', context)}"
            f" AND n.{NODE_ID_FIELD} IN $ids\n"
            "DETACH DELETE n\n"
            "RETURN count(n) AS da_xoa",
            ghi=True,
            ids=[normalize_id(i) for i in ids],
            **self._tham_so_loc(context),
        )
        return int(dong[0]["da_xoa"]) if dong else 0

    async def delete_node(self, node_id: str) -> None:
        """Hợp đồng upstream, đi cùng luật với `xoa_node`: một id, cùng cửa hệ thống."""
        await self.xoa_node([node_id])

    async def khoa_lan_can_hyperedge(self, entity_id: str) -> list[str | None]:
        """Khóa của mọi hyperedge còn nối tới entity này qua cạnh SLOT.

        Nguồn sự thật để dựng lại khóa entity chung khi một tài liệu bị bỏ
        (story 2.3, Design Notes): hyperedge mang khóa của tài liệu sinh ra nó,
        nên gấp danh sách này bằng `hop_nhat_khoa` cho cùng luật với
        read-merge-write. `None` là hyperedge đã hợp nhất ra không khóa - phần
        tử đó kéo cả entity về không khóa. Không trả nội dung nên tầng che không
        áp dụng; chạy dưới cờ system và trong transaction ghi, cùng lý do với
        `khoa_hien_co`: phải thấy trạng thái mà lần ghi kế tiếp sẽ đè lên.
        """
        bat_buoc_ngu_canh_he_thong("đọc khóa hyperedge lân cận")
        context = current_context()
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (e:`{space}` {{{NODE_ID_FIELD}: $id}})"
            f"-[r:{EDGE_TYPE}]-(h:`{space}`:`{LABEL_HYPEREDGE}`)\n"
            f"WHERE {self._dieu_kien('e', context)}"
            f" AND {self._dieu_kien('h', context)}"
            f" AND {self._dieu_kien('r', context)}\n"
            f"RETURN h.{NODE_ID_FIELD} AS id_hyperedge,"
            f" h.{FILTER_KEY_FIELD} AS khoa_hyperedge",
            ghi=True,
            id=normalize_id(entity_id),
            **self._tham_so_loc(context),
        )
        return [d["khoa_hyperedge"] for d in dong]

    async def slot_cua_hyperedge(self, hyperedge_id: str) -> dict[str, list[str]]:
        """`{vai: [id entity đã sắp xếp]}` của mọi cạnh SLOT nối tới một hyperedge (2.4).

        Nguồn để dựng lại `content` (`core.facts.cau_fact`) của hyperedge chung
        khi re-ingest: node hyperedge không mang giá trị slot nào, giá trị chỉ
        sống ở entity và cạnh, nên đọc cạnh là cách duy nhất lắp fact lại. Trả
        nội dung (tên entity) nên chỉ chạy dưới cờ system, cùng khuôn với
        `khoa_lan_can_hyperedge`: `ghi=True` để thấy đúng trạng thái mà lần ghi
        kế tiếp sẽ đè lên. Hyperedge không có hay không có cạnh: dict rỗng.
        """
        bat_buoc_ngu_canh_he_thong("đọc slot của hyperedge")
        context = current_context()
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (h:`{space}`:`{LABEL_HYPEREDGE}` {{{NODE_ID_FIELD}: $id}})"
            f"-[r:{EDGE_TYPE}]-(e:`{space}`)\n"
            f"WHERE {self._dieu_kien('h', context)}"
            f" AND {self._dieu_kien('e', context)}"
            f" AND {self._dieu_kien('r', context)}\n"
            f"RETURN r.{SLOT_FIELD} AS slot_hyperedge, e.{NODE_ID_FIELD} AS id_entity",
            ghi=True,
            id=normalize_id(hyperedge_id),
            **self._tham_so_loc(context),
        )
        ket_qua: dict[str, list[str]] = {}
        khong_vai = 0
        for d in dong:
            if d["slot_hyperedge"] is None:
                # Dữ liệu nạp trước 2.4 (cạnh không vai): không lắp được vào
                # câu render, bỏ qua nhưng nói ra - kho như vậy phải xóa space
                # rồi nạp lại (AGENTS.md), không có di trú tự động.
                khong_vai += 1
                continue
            ket_qua.setdefault(d["slot_hyperedge"], []).append(d["id_entity"])
        if khong_vai:
            logger.warning(
                "hyperedge %s có %d cạnh không mang slot (dữ liệu trước 2.4), bỏ qua khi dựng lại content",
                hyperedge_id,
                khong_vai,
            )
        return {vai: sorted(ids) for vai, ids in ket_qua.items()}

    async def dat_lai_entity(
        self, node_id: str, *, description: str, source_id: str, khoa: str | None
    ) -> None:
        """Ghi đè `description`, `source_id` và khóa của một entity đã có.

        Không read-merge-write: pipeline đã tính khóa từ hyperedge còn nối, và
        cửa hợp nhất chạy lại ở đây sẽ hợp nhất với khóa cũ của chính node rồi
        không bao giờ nới được. `khoa=None` gỡ hẳn thuộc tính (`SET ... = null`),
        đúng nghĩa không khóa của graph. Node phải có sẵn: `EntityMissing` nếu
        không. Vào sổ đợt để bước đối chiếu so với point tương ứng.
        """
        bat_buoc_ngu_canh_he_thong("đặt lại entity")
        context = current_context()
        space = self._nhan_space(context)
        id_chuan = normalize_id(node_id)
        ghi_vao_so(
            id_join=id_chuan,
            kho=KHO_GRAPH,
            id_trong_kho=id_chuan,
            kho_doi=ten_kho_vector("entities"),
        )
        dong = await self._chay(
            f"MATCH (n:`{space}`:`{LABEL_ENTITY}` {{{NODE_ID_FIELD}: $id}})\n"
            f"WHERE {self._dieu_kien('n', context)}\n"
            f"SET n.{DESCRIPTION_FIELD} = $description, n.source_id = $source_id,"
            f" n.{FILTER_KEY_FIELD} = $key\n"
            "RETURN count(n) AS da_ghi",
            ghi=True,
            id=id_chuan,
            description=description,
            source_id=source_id,
            key=khoa,
            **self._tham_so_loc(context),
        )
        if not dong or not dong[0]["da_ghi"]:
            raise EntityMissing(
                f"không có entity {id_chuan!r} trong không gian {space!r} để đặt lại"
            )

    async def dat_lai_hyperedge(self, node_id: str, *, source_id: str, khoa: str | None) -> None:
        """Ghi đè `source_id` và khóa của một hyperedge đã có (hyperedge chung hai tài liệu).

        Cùng luật với `dat_lai_entity`: pipeline re-ingest đã gấp khóa từ nhãn
        các tài liệu còn kể tên hyperedge này, không read-merge-write ở đây.
        `khoa=None` gỡ hẳn thuộc tính. Node phải có sẵn: `HyperedgeMissing`.
        """
        bat_buoc_ngu_canh_he_thong("đặt lại hyperedge")
        context = current_context()
        space = self._nhan_space(context)
        id_chuan = normalize_id(node_id)
        ghi_vao_so(
            id_join=id_chuan,
            kho=KHO_GRAPH,
            id_trong_kho=id_chuan,
            kho_doi=ten_kho_vector("hyperedges"),
        )
        dong = await self._chay(
            f"MATCH (n:`{space}`:`{LABEL_HYPEREDGE}` {{{NODE_ID_FIELD}: $id}})\n"
            f"WHERE {self._dieu_kien('n', context)}\n"
            f"SET n.source_id = $source_id, n.{FILTER_KEY_FIELD} = $key\n"
            "RETURN count(n) AS da_ghi",
            ghi=True,
            id=id_chuan,
            source_id=source_id,
            key=khoa,
            **self._tham_so_loc(context),
        )
        if not dong or not dong[0]["da_ghi"]:
            raise HyperedgeMissing(
                f"không có hyperedge {id_chuan!r} trong không gian {space!r} để đặt lại"
            )

    async def xoa_tat_ca(self) -> int:
        """`DETACH DELETE` mọi node mang nhãn `space` hiện tại; trả số đã xóa.

        Chỉ nhãn của không gian trong ngữ cảnh: không gian khác trên cùng DB
        không bị chạm (AD-12). Ràng buộc duy nhất `id` giữ nguyên.
        """
        bat_buoc_ngu_canh_he_thong("xóa cả không gian graph")
        context = current_context()
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}`)\n"
            f"WHERE {self._dieu_kien('n', context)}\n"
            "DETACH DELETE n\n"
            "RETURN count(n) AS da_xoa",
            ghi=True,
            **self._tham_so_loc(context),
        )
        return int(dong[0]["da_xoa"]) if dong else 0

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

        Vai slot **bắt buộc** và kiểm theo danh mục `core/` trước khi gửi câu đi
        (story 2.4): thiếu là `SlotRoleMissing`, lạ là `SlotRoleInvalid`. Khóa
        MERGE mang `slot` - `(a)-[r:SLOT {slot: $slot}]->(b)` - nên một entity
        điền hai vai của cùng hyperedge là hai cạnh, và che theo vai ở
        `get_node_edges` che đúng cạnh của vai đó chứ không che luôn vai kia.
        Ghi lại cùng (hyperedge, entity, vai) là chính cạnh đó, không sinh
        cạnh thứ hai.

        **Cạnh cố ý không read-merge-write** (giữ ở 2.4). Luật hợp nhất của
        story 2.1 nói về khóa của một *id*, và cạnh không có id: nó được định
        danh bằng (hyperedge, entity, vai), tức bằng hai node đã hợp nhất. Một
        tài liệu thường hơn ghi lại cùng cạnh đó có nới khóa cạnh ra, nhưng
        cạnh vẫn không đi tới được: cả ba đường đọc cạnh (`has_edge`,
        `get_edge`, `get_node_edges`) đòi *cả hai* đầu qua filter, và node
        hyperedge thì đã mang khóa hợp nhất.
        """
        context = current_context()
        space = self._nhan_space(context)
        # `CHUA_GHI` tường minh: cạnh cố ý không read-merge-write (lý do ở
        # docstring trên), và cửa chung không có giá trị mặc định để một nơi
        # gọi *quên* truyền khóa cũ không lặng lẽ quay về last-write-wins.
        khoa = ingest_key_for_write(CHUA_GHI, hang=self._bang_hang.hang)
        props = dict(edge_data)
        vai = props.get(SLOT_FIELD)
        if vai is None:
            raise SlotRoleMissing(
                f"cạnh {source_node_id!r} -> {target_node_id!r} không khai"
                f" {SLOT_FIELD!r}: mọi cạnh phải mang một vai trong danh mục 8 vai"
            )
        # `isinstance` trước khi tra tập: một list/dict lọt vào đây phải ra mã
        # `SLOT_ROLE_INVALID`, không phải `TypeError: unhashable type`.
        if not isinstance(vai, str) or vai not in SLOT_ROLE_SET:
            raise SlotRoleInvalid(
                f"vai slot {vai!r} không có trong danh mục 8 vai của core/"
            )
        dong = await self._chay(
            f"MATCH (a:`{space}` {{{NODE_ID_FIELD}: $src}})\n"
            f"MATCH (b:`{space}` {{{NODE_ID_FIELD}: $tgt}})\n"
            f"MERGE (a)-[r:{EDGE_TYPE} {{{SLOT_FIELD}: $slot}}]->(b)\n"
            f"SET r += $props, r.{SPACE_FIELD} = $space,"
            f" r.{FILTER_KEY_FIELD} = $key\n"
            "RETURN count(r) AS da_ghi",
            ghi=True,
            src=normalize_id(source_node_id),
            tgt=normalize_id(target_node_id),
            slot=vai,
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
        """Thuộc tính node, đã qua tầng che; ngoài quyền là `None`.

        Hai luật che gặp nhau ở đây vì chúng trả lời cùng một câu hỏi - một bản
        ghi node rời adapter trông thế nào khi nội dung của nó không được ra.

        Một: id hỏi tới có thể chính là một dấu che mà `get_node_edges` vừa
        sinh ra, vì `operate.py:1036` mang thẳng `e[1]` đi hỏi `get_node`. Kho
        không có node nào tên như vậy, mà `None` thì nổ ở `operate.py:1039`
        (`{**n, ...}` không lọc `None`). Trả về một node đã che.

        Hai: `description` của node entity chỉ vào ngữ cảnh khi vai đạt L2 với
        nguồn - xem `_che_mo_ta`.
        """
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return None
        id_chuan = normalize_id(node_id)
        if not context.bypass_filter and la_dau_che(
            id_chuan, self._bang_nhom.ten_nhom
        ):
            return self._node_da_che(id_chuan)
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}` {{{NODE_ID_FIELD}: $id}})\n"
            f"WHERE {self._dieu_kien('n', context)}\n"
            "RETURN properties(n) AS thuoc_tinh_node\n"
            "LIMIT 1",
            id=id_chuan,
            **self._tham_so_loc(context),
        )
        if not dong:
            return None
        props = self._che_mo_ta(self._ban_ghi(dong[0]["thuoc_tinh_node"]), context)
        # Id hyperedge chỉ có nghĩa khi node *là* hyperedge; node entity điền
        # vào nhiều hyperedge nên không có một id nào để grant nới (5.3).
        id_he = id_chuan if props.get(ROLE_FIELD) == ROLE_HYPEREDGE else None
        return self._che(props, context, props.get(FILTER_KEY_FIELD), id_he)

    @staticmethod
    def _node_da_che(dau: str) -> dict:
        """Node trả về khi id hỏi tới là một dấu che của chính tầng che.

        Không chạm kho và không tra thêm quyền, vì không có gì để tra: người
        gọi cầm được dấu che này nghĩa là họ đã đi qua `get_node_edges` có
        filter, và bản thân dấu che không mang thông tin nào về nội dung bị
        che. Hỏi kho bằng một id không tồn tại chỉ tốn một vòng truy vấn.

        Hình dạng khớp thứ upstream đọc: `entity_type` và `description` để dựng
        bảng Entities (`operate.py:774-784`, `:997-1006`). Cả hai mang đúng dấu
        che chứ không mang một giá trị bịa ra như `"UNKNOWN"` - mọi giá trị
        khác đều là một khẳng định về node đang bị che mà không ai kiểm quyền
        cho nó.

        Cố ý **không** mang `source_id`: đó là đường với tới chunk nguồn
        (`operate.py:833` chỉ đọc nó khi `"source_id" in v`, nên vắng mặt là
        một nhánh upstream đã biết đi). Cũng không mang khóa quyền: node này
        không sinh ra từ tài liệu nào, gắn cho nó một nhãn quyền là nói dối.
        """
        return {
            NODE_ID_FIELD: dau,
            ROLE_FIELD: ROLE_ENTITY,
            ENTITY_TYPE_FIELD: dau,
            DESCRIPTION_FIELD: dau,
        }

    @staticmethod
    def _che_mo_ta(props: dict, context) -> dict:
        """`description` của node entity chỉ ra nguyên văn khi vai đạt L2.

        Mô tả entity là văn bản LLM viết lại từ chính giá trị slot đã sinh ra
        nó, và `operate.py:194-196` còn gộp mô tả qua nhiều hyperedge bằng
        `GRAPH_FIELD_SEP.join` - nên một entity với tới được qua loại nội dung
        L2 vẫn có thể mang theo mô tả gộp từ hyperedge hạn chế. NFR-06 và FR-05
        chốt ngưỡng L2 cho mô tả entity; đường graph thì đi tới node từ L1 trở
        lên, nên hai ngưỡng lệch nhau đúng ở trường này.

        **Luật này chỉ chạm `description`.** Id node (tên entity) vẫn ra
        nguyên: người gọi tới được `get_node` là đã cầm tên đó trong tay từ
        `get_node_edges` - nơi tên đã đi qua tầng che - còn upstream thì lấy
        `entity_name` từ kho vector `entities` (ngưỡng L2 sẵn) chứ không lấy từ
        dict node này. Che thêm id ở đây không bịt thêm đường nào mà lại cắt
        mất đường tra ngược.

        Node vai hyperedge không có `description` (`operate.py:153` chỉ ghi
        `role`, `weight`, `source_id`) nên luật không chạm nó; điều đó được
        kiểm bằng test chứ không chỉ nói ở đây.
        """
        if context.bypass_filter:
            return props
        if props.get(ROLE_FIELD) != ROLE_ENTITY or DESCRIPTION_FIELD not in props:
            return props
        if props.get(FILTER_KEY_FIELD) in context.keys_for(ENTITY_NAMESPACE):
            return props
        return {
            **props,
            DESCRIPTION_FIELD: dau_che_truong(DESCRIPTION_FIELD, MASK_REASON_L2_ONLY),
        }

    async def get_edge(
        self, source_node_id: str, target_node_id: str
    ) -> dict | None:
        """Thuộc tính của **mọi** cạnh giữa hai node, gộp một bản ghi, đã qua tầng che.

        Từ story 2.4 một cặp (hyperedge, entity) có thể có nhiều cạnh (một cạnh
        mỗi vai). Upstream chỉ dùng `weight` của cặp để sắp xếp
        (`operate.py:900`), nên gộp là đúng ngữ nghĩa: `weight` cộng, `source_id`
        hợp, các vai vào danh sách `slots` đã sắp xếp; trường `slot` đơn không
        còn trong bản ghi. Ngoài quyền là `None`. Cạnh nào cũng phải qua filter
        riêng của nó (biến `r`), nên cạnh mang khóa ngoài quyền không vào tổng.
        """
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
            "WITH a, b, collect(properties(r)) AS cac_canh\n"
            "RETURN cac_canh AS thuoc_tinh_canh,"
            f" a.{ROLE_FIELD} AS vai_a, a.{FILTER_KEY_FIELD} AS khoa_a,"
            f" b.{ROLE_FIELD} AS vai_b, b.{FILTER_KEY_FIELD} AS khoa_b\n"
            "LIMIT 1",
            src=normalize_id(source_node_id),
            tgt=normalize_id(target_node_id),
            **self._tham_so_loc(context),
        )
        if not dong or not dong[0]["thuoc_tinh_canh"]:
            return None
        d = dong[0]
        khoa = self._khoa_de_che(
            context, (d["vai_a"], d["khoa_a"]), (d["vai_b"], d["khoa_b"])
        )
        # Đầu nào là hyperedge thì id đầu ấy là id hyperedge của cạnh (5.3);
        # hai id đã chuẩn hóa ở tham số câu, không đọc lại từ kho.
        id_he = (
            normalize_id(source_node_id) if d["vai_a"] == ROLE_HYPEREDGE
            else normalize_id(target_node_id) if d["vai_b"] == ROLE_HYPEREDGE
            else None
        )
        return self._che(self._gop_canh(d["thuoc_tinh_canh"]), context, khoa, id_he)

    @classmethod
    def _gop_canh(cls, cac_canh) -> dict:
        """Gộp thuộc tính nhiều cạnh của một cặp thành một bản ghi.

        `weight` cộng, `source_id` hợp (tách bằng `GRAPH_FIELD_SEP`, giữ thứ tự
        gặp), `slots` (`core.masking.SLOTS_FIELD`) là danh sách vai sắp xếp; các
        trường còn lại lấy của cạnh đầu **sau khi sắp theo `slot`**, nên kết quả
        tất định dù Neo4j trả `collect` theo thứ tự nào. Khóa quyền của cạnh
        (`filter_key`) trong bản ghi gộp chỉ là nhãn truy nguyên: tầng che tra
        `masked_slots` bằng khóa của *hyperedge* (`_khoa_hyperedge`), không bằng
        khóa cạnh, nên hai cạnh khác khóa không đổi cách che. Nhận cả một dict
        đơn để không phụ thuộc hình dạng dòng.
        """
        if isinstance(cac_canh, Mapping):
            cac_canh = [cac_canh]
        cac_canh = sorted((dict(c) for c in cac_canh), key=lambda c: str(c.get(SLOT_FIELD) or ""))
        gop = cls._ban_ghi(cac_canh[0])
        gop.pop(SLOT_FIELD, None)
        weight = 0.0
        co_weight = False
        nguon: list[str] = []
        slots: set[str] = set()
        for c in cac_canh:
            if c.get("weight") is not None:
                co_weight = True
                weight += float(c["weight"])
            for m in str(c.get("source_id") or "").split(GRAPH_FIELD_SEP):
                if m and m not in nguon:
                    nguon.append(m)
            if c.get(SLOT_FIELD) is not None:
                slots.add(c[SLOT_FIELD])
        if co_weight:
            gop["weight"] = weight
        if nguon or "source_id" in gop:
            gop["source_id"] = GRAPH_FIELD_SEP.join(nguon)
        gop[SLOTS_FIELD] = sorted(slots)
        return gop

    async def get_node_edges(self, source_node_id: str) -> list[tuple[str, str]]:
        """Cặp `(id, id_lân_cận)` của mọi cạnh còn thấy được.

        Hình dạng này là hợp đồng, không phải lựa chọn: `operate.py:884-925`
        đưa thẳng `e[1]` vào `get_edge`/`get_node`. Lân cận ngoài quyền vắng
        mặt khỏi danh sách chứ không phải xuất hiện với nội dung rỗng - một cái
        tên bị che vẫn kể rằng có một fact ở đó.

        Tầng che nhận cả vai slot của cạnh, vì tên node lân cận điền vào một
        slot đang bị che thì phải bị che như nội dung slot (AD-9). Vì sao đường
        này là đường rò thật của Epic 1: docstring `core/masking.py`.

        **Một ngoại lệ về lọc, và chỉ ở method này.** Node entity *không khóa*
        (kết quả hợp nhất đa nguồn khác scope, AD-5) đi qua được mệnh đề lọc
        của biến lân cận - xem `_dieu_kien_lan_can` - rồi tên nó bị che cứng ở
        tầng che. Vai vì thế biết "có một fact ở đây mà tôi không được đọc"
        (FR-12) thay vì thấy một hyperedge thiếu hẳn một slot. Đây là đường duy
        nhất tới được một node không khóa; sáu method đọc còn lại giữ nguyên
        mệnh đề chặt.
        """
        context = current_context()
        if not self._co_khoa_de_doc(context):
            return []
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (n:`{space}` {{{NODE_ID_FIELD}: $id}})"
            f"-[r:{EDGE_TYPE}]-(m:`{space}`)\n"
            f"WHERE {self._dieu_kien('n', context)}"
            f" AND {self._dieu_kien_lan_can('m', context)}"
            f" AND {self._dieu_kien('r', context)}\n"
            f"RETURN n.{NODE_ID_FIELD} AS nguon, m.{NODE_ID_FIELD} AS lan_can,"
            f" r.{SLOT_FIELD} AS slot, n.{ROLE_FIELD} AS vai_nguon,"
            f" n.{FILTER_KEY_FIELD} AS khoa_nguon,"
            f" m.{ROLE_FIELD} AS vai_lan_can,"
            f" m.{FILTER_KEY_FIELD} AS khoa_lan_can",
            id=normalize_id(source_node_id),
            vai_entity=ROLE_ENTITY,
            **self._tham_so_loc(context),
        )
        cac_cap = []
        for d in dong:
            # Vai của lân cận đọc từ chính dữ liệu, không suy ra từ vai của
            # node nguồn: suy ra là một giả định, và giả định sai ở đây nghĩa
            # là che một loại nội dung bằng luật của loại nội dung khác.
            khoa = self._khoa_de_che(
                context,
                (d["vai_nguon"], d["khoa_nguon"]),
                (d["vai_lan_can"], d["khoa_lan_can"]),
            )
            # Vai slot mô tả *entity điền vào* hyperedge, nên nó chỉ có nghĩa
            # cho lân cận là entity. Gọi từ phía entity (`operate.py:818`,
            # `:887` ở local mode) thì lân cận là chính node hyperedge, thứ
            # không điền vào slot nào - khai vai cho nó là bảo tầng che che id
            # hyperedge, và `operate.py:900-907` sẽ nhận `get_edge(..., dấu
            # che) -> None` rồi loại nguyên dòng đó, tức một fact mà vai *được*
            # thấy ở L1 biến mất khỏi ngữ cảnh (đi ngược FR-12).
            #
            # Tên trường lấy từ `core.masking`, không viết lại: `NEIGHBOR_FIELD`
            # cố ý không phải `source`, vì `source` là *một trong 8 vai slot* và
            # tầng che tra bản ghi theo tên vai - hai nghĩa trùng tên trong một
            # dict là một lỗi chờ sẵn. Lệch một chữ ở đây thì tầng che không tra
            # trúng gì và tên lân cận ra nguyên văn.
            vai_slot = d["slot"] if d["vai_lan_can"] == ROLE_ENTITY else None
            ban_ghi = self._che(
                {
                    "node_id": d["nguon"],
                    NEIGHBOR_FIELD: d["lan_can"],
                    SLOT_FIELD: vai_slot,
                    # Cờ làm giàu của AD-9: "adapter làm giàu nó với khóa (hoặc
                    # cờ không-khóa) của từng node lân cận trước khi gọi hàm
                    # che". Đây là thứ cho phép luật che cứng đọc được trạng
                    # thái không-khóa mà chữ ký T1 của hàm che không đổi.
                    NEIGHBOR_NO_KEY_FIELD: d["khoa_lan_can"] is None,
                },
                context,
                khoa,
                # Id hyperedge của cạnh (5.3): đầu nguồn nếu gọi từ phía
                # hyperedge, đầu lân cận nếu gọi từ phía entity. Không đầu nào
                # là hyperedge thì `_khoa_de_che` đã nổ ở trên.
                d["nguon"] if d["vai_nguon"] == ROLE_HYPEREDGE else d["lan_can"],
            )
            cac_cap.append((ban_ghi["node_id"], ban_ghi[NEIGHBOR_FIELD]))
        return cac_cap

    async def trich_dan_cua(self, ids) -> dict[str, tuple[str, tuple[str, ...]]]:
        """`{id hyperedge: (khóa quyền, các vai có mặt)}` dưới ngữ cảnh vai (story 3.4).

        Cửa quyền của citation. Id vào là **khóa tra** đọc từ cột `hyperedge`
        của ngữ cảnh; thứ đi ra là khóa quyền và tên vai của đúng những
        hyperedge mà vai hiện tại còn thấy. Hyperedge ngoài quyền **vắng mặt**
        khỏi dict - không xuất hiện với giá trị rỗng, vì "có id này" cũng là
        một câu trả lời - và nơi gọi (`adapters/trich_dan.dung_danh_sach`)
        đổi mỗi chỗ vắng thành `TrichDanNgoaiQuyen`.

        **Không mở đường đọc mới.** Ba mệnh đề lọc chép nguyên từ
        `get_node_edges`: `_dieu_kien` cho node hyperedge và cho cạnh,
        `_dieu_kien_lan_can` cho entity - kể cả nhánh nới cho entity không khóa
        của AD-5, vì một vai bị che cứng ở vai ấy vẫn phải thấy `masked_slots`
        nhắc tới nó. Method trả **tên vai và khóa**, không trả giá trị slot
        hay tên entity, nên nó không đi qua `mask`; lý do khai ở
        `tests/test_phan_chieu_che.py`.

        Vai đọc bằng `collect(DISTINCT r.slot)` trên `OPTIONAL MATCH`: một
        hyperedge còn thấy được mà không có cạnh nào qua lọc vẫn về một dòng
        với danh sách rỗng, và `collect` bỏ `null`. Cạnh không mang `slot`
        (dữ liệu trước 2.4) bị bỏ, cùng cách với `slot_cua_hyperedge`. Thứ tự
        trả về không hứa gì (`IN $ids`); nơi gọi xếp lại theo ngữ cảnh.
        """
        context = current_context()
        cac_id: list[str] = []
        for i in ids:
            chuan = normalize_id(i)
            if chuan not in cac_id:
                cac_id.append(chuan)
        if not cac_id or not self._co_khoa_de_doc(context):
            return {}
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (h:`{space}`:`{LABEL_HYPEREDGE}`)\n"
            f"WHERE h.{NODE_ID_FIELD} IN $ids AND {self._dieu_kien('h', context)}\n"
            f"OPTIONAL MATCH (h)-[r:{EDGE_TYPE}]-(e:`{space}`)\n"
            f"WHERE {self._dieu_kien('r', context)}"
            f" AND {self._dieu_kien_lan_can('e', context)}\n"
            f"RETURN h.{NODE_ID_FIELD} AS id_hyperedge,"
            f" h.{FILTER_KEY_FIELD} AS khoa_trich_dan,"
            f" collect(DISTINCT r.{SLOT_FIELD}) AS cac_vai",
            ids=cac_id,
            vai_entity=ROLE_ENTITY,
            **self._tham_so_loc(context),
        )
        ra: dict[str, tuple[str, tuple[str, ...]]] = {}
        for d in dong:
            if not d["khoa_trich_dan"]:
                # Không khóa mà vẫn qua được mệnh đề lọc chỉ xảy ra dưới cờ
                # system (mệnh đề chỉ còn `space`); ở đó không có mức tiết lộ
                # nào để nói, nên không có citation.
                continue
            vai = tuple(sorted(v for v in d["cac_vai"] if v is not None))
            ra[d["id_hyperedge"]] = (d["khoa_trich_dan"], vai)
        return ra

    async def do_thi_cua(self, ids) -> list[dict]:
        """Các dòng (hyperedge, vai, tên entity **đã che**) dưới ngữ cảnh vai (story 3.7).

        Đường đọc của `POST /do-thi`. Một câu Cypher `IN $ids`, **`MATCH`** chứ
        không `OPTIONAL MATCH`, và cả ba biến - hyperedge `h`, cạnh `r`, entity
        `e` - đi qua mệnh đề **chặt** `_dieu_kien` cộng `e.role = entity`. Khác
        `get_node_edges` và `trich_dan_cua` đúng một chỗ: entity không khóa
        (AD-5) **không** đi qua. AD-8 định nghĩa "ngoài quyền" của đồ thị bằng
        ba ca tường minh và không khóa là một trong ba; ngữ cảnh gửi LLM cần
        biết "có một fact ở đây" (FR-12), đồ thị vẽ lên màn thì không (ADR-018).
        Hệ quả là một hyperedge mà mọi đỉnh đều ngoài quyền không về dòng nào,
        tức vắng mặt như một id không tồn tại - đúng điều spec đòi.

        Mỗi dòng đi qua `_che` với bản ghi **cùng hình dạng `get_node_edges`**
        (`node_id`, `NEIGHBOR_FIELD`, `SLOT_FIELD`, `NEIGHBOR_NO_KEY_FIELD=False`)
        và khóa của hyperedge, nên luật che là một chỗ và bảng nhóm là bảng của
        chính adapter. `bi_che` là phép so tên trước và sau che, không parse dấu
        che. Cạnh không mang `slot` (dữ liệu trước 2.4) bị bỏ **trước** khi tới
        tầng che: một cạnh không vai không tra được luật che nào, và đưa nó ra
        là để tên đi ra nguyên văn. Cạnh mang `slot` **lạ** (không phải chuỗi
        hay ngoài danh mục 8 vai) là dữ liệu kho hỏng: `DoThiNgoaiQuyen` mang
        mã ổn định, không để `SlotRoleUnknown` của `core/` lên HTTP thành một
        500 không tên; cùng cách với `MaskItemOutOfPermission` từ `_che`.

        Ngữ cảnh hệ thống bị **từ chối** chứ không đọc thô: `_che` trả bản ghi
        nguyên trạng ở đó, và đường này không có nơi gọi hợp lệ nào dưới cờ
        ingest. Cùng mã với citation (`DoThiNgoaiQuyen`).
        """
        context = current_context()
        if context.bypass_filter:
            raise DoThiNgoaiQuyen(
                "do_thi_cua không chạy dưới ngữ cảnh hệ thống: tầng che trả tên"
                " thô ở đó, và đồ thị theo quyền không có nghĩa nào để nói"
            )
        cac_id = chuan_hoa_ids(ids)
        if not cac_id or not self._co_khoa_de_doc(context):
            return []
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (h:`{space}`:`{LABEL_HYPEREDGE}`)-[r:{EDGE_TYPE}]-(e:`{space}`)\n"
            f"WHERE h.{NODE_ID_FIELD} IN $ids AND {self._dieu_kien('h', context)}"
            f" AND {self._dieu_kien('r', context)}"
            f" AND {self._dieu_kien('e', context)}"
            f" AND e.{ROLE_FIELD} = $vai_entity\n"
            f"RETURN h.{NODE_ID_FIELD} AS id_hyperedge,"
            f" h.{FILTER_KEY_FIELD} AS khoa_do_thi,"
            f" r.{SLOT_FIELD} AS slot, e.{NODE_ID_FIELD} AS id_entity",
            ids=list(cac_id),
            vai_entity=ROLE_ENTITY,
            **self._tham_so_loc(context),
        )
        ra: list[dict] = []
        for d in dong:
            if d["slot"] is None:
                continue
            if not isinstance(d["slot"], str) or d["slot"] not in SLOT_ROLE_SET:
                raise DoThiNgoaiQuyen(
                    f"hyperedge {d['id_hyperedge']!r} có cạnh mang vai"
                    f" {d['slot']!r} ngoài danh mục 8 vai: dữ liệu kho hỏng,"
                    " không dựng đồ thị"
                )
            khoa = self._khoa_hyperedge((ROLE_HYPEREDGE, d["khoa_do_thi"]), (ROLE_ENTITY, None))
            try:
                ban_ghi = self._che(
                    {
                        "node_id": d["id_hyperedge"],
                        NEIGHBOR_FIELD: d["id_entity"],
                        SLOT_FIELD: d["slot"],
                        NEIGHBOR_NO_KEY_FIELD: False,
                    },
                    context,
                    khoa,
                    d["id_hyperedge"],
                )
            except (MaskItemOutOfPermission, SlotRoleUnknown) as loi:
                raise DoThiNgoaiQuyen(
                    f"không che được cạnh của hyperedge {d['id_hyperedge']!r}"
                    f" ({type(loi).__name__}): tầng lọc và tầng che lệch nhau"
                ) from loi
            ra.append(
                {
                    "id_hyperedge": d["id_hyperedge"],
                    "khoa": khoa,
                    "slot": d["slot"],
                    "ten_da_che": ban_ghi[NEIGHBOR_FIELD],
                    "bi_che": ban_ghi[NEIGHBOR_FIELD] != d["id_entity"],
                }
            )
        return ra

    async def hyperedge_ke_can(self, ids) -> tuple[str, ...]:
        """Id hyperedge cách các id vào **một bước hyperedge**, dưới ngữ cảnh vai (story 5.2).

        Pha một của vùng cấp break-glass. Một bước là hai cạnh SLOT qua một
        entity chung: `(g)-[r1]-(e)-[r2]-(h)`. Năm biến của pattern đều bị ràng
        `space` và khóa quyền: `g`, `h`, `r1`, `r2` qua mệnh đề **chặt**
        `_dieu_kien`, `e` qua `_dieu_kien_lan_can` (entity không khóa của AD-5
        vẫn là cầu nối, vì hai fact chung một entity đã hợp nhất thành không
        khóa vẫn là hai fact cùng nói về một thứ - nhưng `h` ở đầu kia phải là
        hyperedge vai **thấy**, nên không kể ra fact nào ngoài quyền). Ngữ cảnh
        là của **vai xin**, không phải owner: bộ lọc (b) của `core.break_glass`
        hỏi "vai xin thấy ở L1", nên tập thô phải là tập vai xin thấy.

        Trả **chỉ id**, `DISTINCT`, không khóa, không vai, không tên entity;
        không có gì để che nên nó ở `XU_LY_RIENG_THEO_ADAPTER` chứ không ở
        `MASKED_READ_METHODS`. Id vào không có trong kết quả (gốc không phải
        lân cận của chính nó, và một id vào khác cũng không): lọc ở Python vì
        Neo4j chỉ cấm trùng **cạnh** trong một pattern, không cấm `h = g` qua
        hai vai của cùng một entity. Mỗi lời gọi là một bước; `k` bước là `k`
        lời gọi (`EngineACL.vung_lan_can`), không phải một đường biến độ dài.

        Ngữ cảnh hệ thống bị **từ chối** như `do_thi_cua`: vùng cấp không có
        nghĩa nào dưới một ngữ cảnh đọc thô.
        """
        context = current_context()
        if context.bypass_filter:
            raise DoThiNgoaiQuyen(
                "hyperedge_ke_can không chạy dưới ngữ cảnh hệ thống: vùng cấp"
                " break-glass tính dưới vai xin, không có nghĩa nào khi đọc thô"
            )
        cac_id = chuan_hoa_ids(ids)
        if not cac_id or not self._co_khoa_de_doc(context):
            return ()
        space = self._nhan_space(context)
        dong = await self._chay(
            f"MATCH (g:`{space}`:`{LABEL_HYPEREDGE}`)-[r1:{EDGE_TYPE}]-(e:`{space}`)"
            f"-[r2:{EDGE_TYPE}]-(h:`{space}`:`{LABEL_HYPEREDGE}`)\n"
            f"WHERE g.{NODE_ID_FIELD} IN $ids AND {self._dieu_kien('g', context)}"
            f" AND {self._dieu_kien('r1', context)}"
            f" AND {self._dieu_kien_lan_can('e', context)}"
            f" AND {self._dieu_kien('r2', context)}"
            f" AND {self._dieu_kien('h', context)}\n"
            f"RETURN DISTINCT h.{NODE_ID_FIELD} AS id_ke_can",
            ids=list(cac_id),
            vai_entity=ROLE_ENTITY,
            **self._tham_so_loc(context),
        )
        vao = set(cac_id)
        ra: list[str] = []
        for d in dong:
            id_h = d["id_ke_can"]
            if id_h in vao or id_h in ra:
                continue
            ra.append(id_h)
        return tuple(ra)

    @property
    def bang_nhom(self) -> BangNhomPhuTrach:
        """Bảng nhóm phụ trách mà adapter này che bằng; citation tra cùng bảng.

        Thuộc tính đọc, không phải một đường đọc kho: nó trả cấu hình đã nạp
        lúc dựng adapter. Đưa ra ngoài để `EngineACL.hoi_dap` điền
        `owner_group` bằng **đúng bảng** đã sinh dấu che `[owner:<nhóm>]` trong
        ngữ cảnh - một bảng thứ hai nạp ở engine là hai chỗ nói hai tên nhóm
        cho cùng một hyperedge (khoản ledger 3.1 mà story 3.4 đóng).
        """
        return self._bang_nhom

    async def node_degree(self, node_id: str) -> int:
        """Số lân cận *còn thấy được* (distinct), không phải tổng số cạnh.

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
            # `DISTINCT m` (2.4): một entity điền hai vai của cùng hyperedge là
            # hai cạnh nhưng một lân cận, giữ ngữ nghĩa đơn đồ thị của
            # `NetworkXStorage` upstream để xếp hạng không đổi.
            "RETURN count(DISTINCT m) AS bac",
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

    @classmethod
    def _khoa_de_che(cls, context, dau_a: tuple, dau_b: tuple) -> str | None:
        """Khóa để che một bản ghi cạnh, hoặc `None` khi lời gọi đọc thô.

        Ngữ cảnh hệ thống không che gì, nên hỏi "khóa nào để tra `masked_slots`"
        là hỏi một câu không dùng tới - và từ story 2.1 nó còn là một câu *nổ
        được*: một hyperedge đa nguồn khác scope hợp nhất ra "không khóa" thì
        node của nó không mang khóa nữa, và `_khoa_hyperedge` fail-closed đúng
        như nó phải làm. Nhưng cửa fail-closed ấy sinh ra để chặn một bản ghi
        rời adapter mà **không được che**, còn ở đây không có gì để che.

        Không nới lỏng gì cho đường vai người dùng: nhánh dưới vẫn đi qua
        `_khoa_hyperedge` nguyên vẹn. Đường đọc thô thì node không khóa vốn đã
        đi tới được (mệnh đề lọc chỉ còn `space`), nên nếu không có nhánh này
        thì chính pipeline ingest hỏng khi nó đọc lại một hyperedge vừa hợp
        nhất - và đó không phải một lỗi quyền, đó là một cửa hỏi sai chỗ.
        """
        if context.bypass_filter:
            return None
        return cls._khoa_hyperedge(dau_a, dau_b)

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

    def _nhom_phu_trach(self, khoa: str) -> str | None:
        """Tên nhóm phụ trách suy từ `content_type` của khóa, `None` nếu chưa khai.

        Một chỗ tra, không hai: mọi bản ghi rời adapter này đi qua `_che`, nên
        đặt phép tra ở đó là đủ cho cả sáu method đọc. Bảng nạp lúc dựng adapter
        từ `global_config` (`bang_nhom_cho`), cùng khe tiêm và cùng luật đóng
        băng với bảng hạng - hai bảng của một adapter đến từ một cấu hình.

        Khóa hỏng thì trả `None` chứ không nổ: `split_key` đã có cửa riêng ở
        đường ghi, và ở đường đọc một khóa không tách được vẫn phải che - chỉ là
        che bằng hằng cũ. Nổ ở đây là biến một dấu che thiếu tên nhóm thành một
        câu trả lời biến mất.
        """
        try:
            _, content_type = split_key(khoa)
        except (TypeError, ValueError):
            return None
        return self._bang_nhom.nhom_cua(content_type)

    def _che(self, ban_ghi: dict, context, khoa: str | None, id_hyperedge: str | None = None) -> dict:
        """Cửa duy nhất gọi tầng che, để không method nào quên gọi (AD-9).

        Ngữ cảnh hệ thống đọc thô nên không che. Khóa truyền vào là khóa của
        hyperedge liên quan, kể cả khi lời gọi bắt đầu từ phía entity; khóa
        vắng là fail-closed chứ không phải che bằng khóa rỗng.

        Trước khi gọi tầng che, bản ghi được làm giàu với tên nhóm phụ trách
        (story 3.1) - đúng tiền lệ `NEIGHBOR_NO_KEY_FIELD` của AD-9: trạng thái
        thêm đi xuống bằng một trường của bản ghi, nên chữ ký `mask` không đổi
        và `core/` vẫn không đọc file nào. Loại nội dung chưa khai nhóm thì
        trường vắng mặt và dấu che rơi về `[owner:group]` như trước.

        **Trường ấy là một đường vận chuyển, nên nó bị gỡ ở cả hai đầu.**

        Gỡ ở đầu vào: một node Neo4j có thể mang sẵn một property tên
        `owner_group` - kho nhận bất kỳ khóa nào ở đường ghi - và nếu nó đi
        thẳng xuống `dau_che_owner` thì dấu che mang một giá trị **không có
        trong bảng nhóm**. `la_dau_che` dựng lại từ bảng nên nó không nhận ra
        chuỗi đó ở vị trí id, `get_node` chạy Cypher với một id không tồn tại,
        trả `None`, và `operate.py:1039` nổ `TypeError` giữa `vendor/` - đúng
        landmine mà story 1.6 đã gỡ một lần.

        Gỡ ở đầu ra: không gỡ thì tên nhóm đi tiếp lên `vendor/` ở **dạng thô**,
        nằm cạnh chính dấu che `[owner:<nhóm>]` mà nó vừa sinh ra. Gỡ ở đây chứ
        không gỡ trong `mask`: bản ghi đã làm giàu chính là `truoc_khi_che` của
        `kiem_ket_qua_che`, nên một phép gỡ bên trong hàm che sẽ bị hợp đồng báo
        là **mất trường**.

        `id_hyperedge` (story 5.3, ADR-021) đi cùng đường vận chuyển ấy dưới tên
        `HYPEREDGE_ID_FIELD`: tầng che so nó với `context.grant_ids` để nới về
        luật L2 cho hyperedge được cấp break-glass, **sau** cửa fail-closed của
        chính nó. Bốn method đọc truyền id của hyperedge mà bản ghi thuộc về;
        vắng (`None`) là không nới. Cũng gỡ ở cả hai đầu, cùng lý do với nhóm:
        một property cùng tên trong kho không được thành một grant tự phong, và
        id không đi tiếp lên `vendor/` như một trường lạ.
        """
        if context.bypass_filter:
            return ban_ghi
        if not khoa:
            raise HyperedgeKeyMissing(
                f"bản ghi {ban_ghi!r} không truy ra khóa hyperedge để che"
            )
        truong_van_chuyen = (OWNER_GROUP_FIELD, HYPEREDGE_ID_FIELD)
        if any(t in ban_ghi for t in truong_van_chuyen):
            ban_ghi = {k: v for k, v in ban_ghi.items() if k not in truong_van_chuyen}
        nhom = self._nhom_phu_trach(khoa)
        if nhom is not None:
            ban_ghi = {**ban_ghi, OWNER_GROUP_FIELD: nhom}
        if id_hyperedge is not None:
            ban_ghi = {**ban_ghi, HYPEREDGE_ID_FIELD: id_hyperedge}
        da_che = kiem_ket_qua_che(mask(ban_ghi, context, khoa), ban_ghi, repr(ban_ghi))
        for t in truong_van_chuyen:
            da_che.pop(t, None)
        return da_che
