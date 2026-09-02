"""Engine của dự án: `HyperGraphRAG` nối vào ba adapter mang quyền (AD-2).

Ba adapter của story 1.3-1.5 đều xanh nhưng chưa cái nào được engine dùng:
`_get_storage_class()` vẫn trả registry mặc định của upstream, `initialize()`
chưa ai gọi, và bảy khóa cấu hình kho chưa ai sinh ra. File này nối dây, và
**chỉ** nối dây - không luật lọc, không luật che, không mã lỗi mới. Mọi quyết
định về quyền đã nằm ở `core/` và ở ba adapter; thêm một luật thứ hai ở đây là
tạo ra hai chỗ để trả lời cùng một câu hỏi.

Bốn điều file này chốt, và vì sao chúng phải ở đây chứ không ở chỗ khác:

**Registry chỉ còn ba adapter của dự án.** `_get_storage_class()` của upstream
là instance method trả một dict tên chuỗi -> lớp, tra ba lần trong
`__post_init__` (`hypergraphrag.py:181-189`). Bản override này bỏ hẳn các mục
của upstream thay vì thêm ba mục mới: một `kv_storage="JsonKVStorage"` viết
nhầm phải là `KeyError` ngay lúc dựng, không phải một engine chạy được mà
không có tầng quyền nào.

**Kết nối kho không được là field.** `asdict(self)` chạy 10 lần trên đường dựng
và truy vấn (`:178,198,210,215,220,226,232,238,328,506`), và
`dataclasses.asdict` `deepcopy` mọi field không phải dataclass. `deepcopy` một
`AsyncQdrantClient` (có khóa, có socket) là nổ hoặc là một bản sao vô nghĩa.
Nên khe tiêm là một **hàm** - `copy.deepcopy` trả về chính đối tượng cho hàm
(`copy._deepcopy_atomic`) nên nó đi qua được cả 10 lần - còn kết nối sống
ngoài danh sách field, dưới dạng thuộc tính thường.

Kết nối phải tồn tại **trước** `super().__post_init__()`, vì chính lời gọi đó
dựng sáu storage. Upstream chấp nhận entry không phải class trong registry
(`lazy_external_import` trả một closure), nên `functools.partial` bind sẵn kết
nối là hợp lệ với hợp đồng của nó.

**Một kết nối cho mỗi kho.** Ba namespace vector dùng chung một
`AsyncQdrantClient`, một namespace graph dùng một `AsyncDriver`. Không tiêm thì
engine tự mở từ cấu hình, và khi đó chính engine đóng lại lúc `dong()`. Kết nối
tiêm từ ngoài thì không: nó thuộc về người tiêm, đóng hộ là làm hỏng kết nối
của người khác. Cùng luật sở hữu mà `Neo4jACLGraphStorage.close()` đã giữ.

**`aquery` dựng `QueryParam` mới mỗi lời gọi.** Chữ ký upstream là
`param: QueryParam = QueryParam()` - một instance dựng lúc import, dùng chung
cho mọi lời gọi - và `_build_query_context` **ghi** `query_param.mode` lên
chính nó (`operate.py:658,681,700`). Hai truy vấn song song không truyền param
tường minh là hai truy vấn chia nhau một mảnh trạng thái. Không phải chuyện
quyền, nhưng nó nằm đúng trên đường mà cổng M1 phải chứng minh là không lẫn.

**Không dựng engine per-request.** Spine để ngỏ đường lùi đó phòng khi
contextvar quyền đứt qua executor. Không cần dùng: `vendor/` không có
`to_thread`, `run_in_executor` hay `ThreadPoolExecutor` nào, fan-out chỉ là
`gather`/`as_completed` trên cùng event loop nơi contextvar được kế thừa. Đó là
bằng chứng chứ không phải lời hứa - `tests/test_cong_m1.py` giữ phép grep đó
sống dưới dạng một test.
"""

import os
from dataclasses import asdict, dataclass, field, replace
from functools import partial
from typing import Callable

from hypergraphrag import HyperGraphRAG
from hypergraphrag.base import QueryParam
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient

from adapters.kv import ENABLE_LLM_CACHE, WORKING_DIR_KEY, JsonACLKVStorage
from adapters.neo4j import (
    HEALTH_DELAY_KEY,
    HEALTH_DELAY_MAC_DINH,
    HEALTH_RETRIES_KEY,
    HEALTH_RETRIES_MAC_DINH,
    NEO4J_DATABASE_KEY,
    NEO4J_DATABASE_MAC_DINH,
    NEO4J_PASSWORD_KEY,
    NEO4J_URI_KEY,
    NEO4J_USERNAME_KEY,
    NEO4J_USERNAME_MAC_DINH,
    Neo4jACLGraphStorage,
)
from adapters.qdrant import (
    COSINE_THRESHOLD_KEY,
    QDRANT_API_KEY_KEY,
    QDRANT_URL_KEY,
    QdrantVectorDBStorage,
)
from adapters.sensitivity_loader import SENSITIVITY_RANKS_KEY

# Tên đăng ký trong registry. Chuỗi này đi vào ba field `kv_storage`,
# `vector_storage`, `graph_storage` của upstream, nên nó là hợp đồng chứ không
# phải một cái tên tùy ý; đặt hằng để không có bản viết tay thứ hai.
TEN_KV: str = JsonACLKVStorage.__name__
TEN_VECTOR: str = QdrantVectorDBStorage.__name__
TEN_GRAPH: str = Neo4jACLGraphStorage.__name__

# Mọi khóa cấu hình kho mà ba adapter đọc từ `global_config`. Tên hằng lấy
# thẳng từ chính adapter đọc chúng: một khóa lệch một chữ ở đây là adapter đọc
# `None` rồi nổ ở chỗ khác, hoặc tệ hơn, lặng lẽ dùng giá trị mặc định.
#
# Tên field của dataclass phải **bằng** các chuỗi này, vì thứ upstream truyền
# xuống storage là `asdict(self)` chứ không phải một dict do mình dựng.
#
# Bảy khóa kết nối (I/O Matrix của spec) cộng `cosine_better_than_threshold` -
# khóa thứ tám tìm ra ở vòng review: nó không phải field của `HyperGraphRAG`
# nên trước story này không bao giờ xuống tới adapter, và ngưỡng đóng cứng ở
# mặc định 0.2 của chính adapter.
# Hai khóa cuối vào ở story 2.1: `neo4j_database` (khoản nợ vòng đời kết nối
# Neo4j) và `sensitivity_ranks_path` (bảng hạng độ nhạy của luật hợp nhất khóa).
KHOA_CAU_HINH_KHO: tuple[str, ...] = (
    QDRANT_URL_KEY,
    QDRANT_API_KEY_KEY,
    COSINE_THRESHOLD_KEY,
    NEO4J_URI_KEY,
    NEO4J_USERNAME_KEY,
    NEO4J_PASSWORD_KEY,
    NEO4J_DATABASE_KEY,
    HEALTH_RETRIES_KEY,
    HEALTH_DELAY_KEY,
    SENSITIVITY_RANKS_KEY,
)

# Biến môi trường -> khóa cấu hình. Đây là chỗ khép vòng cho khoản nợ "khóa cấu
# hình chưa có nguồn" của cả ba story adapter: `docker-compose.yml` đặt biến
# cho service `api`, hàm dưới đây đổi chúng thành field của engine, và
# `asdict(self)` mang chúng xuống adapter.
#
# `working_dir` mang tiền tố `HYPER_RAG_` vì nó là tham số của *ứng dụng*, khác
# bốn biến kia là địa chỉ của dịch vụ ngoài (tên do chính dịch vụ đó quy ước).
BIEN_MOI_TRUONG: dict[str, str] = {
    QDRANT_URL_KEY: "QDRANT_URL",
    QDRANT_API_KEY_KEY: "QDRANT_API_KEY",
    NEO4J_URI_KEY: "NEO4J_URI",
    NEO4J_USERNAME_KEY: "NEO4J_USERNAME",
    NEO4J_PASSWORD_KEY: "NEO4J_PASSWORD",
    NEO4J_DATABASE_KEY: "NEO4J_DATABASE",
    WORKING_DIR_KEY: "HYPER_RAG_WORKING_DIR",
}

# Khóa cấu hình kho **cố ý** không có biến môi trường. Miễn trừ tường minh chứ
# không phải chỗ bị quên: `test_bien_moi_truong_phu_het_khoa_cau_hinh_kho` bắt
# `KHOA_CAU_HINH_KHO - BIEN_MOI_TRUONG` phải đúng bằng tập này, nên thêm một
# khóa mà quên nguồn là CI đỏ.
#
# Hai knob health-check nằm đây vì mặc định 30 lần × 0.5s (~15 giây) đã đủ cho
# máy chủ 15 GB RAM, và compose còn chờ sẵn bằng `depends_on: condition:
# service_healthy` nên `api` chỉ lên sau khi Neo4j đã healthy. Ngưỡng cosine thì
# là knob chất lượng truy hồi, thứ được đo và chốt trong Epic 7 chứ không phải
# thứ mỗi môi trường tự đặt một kiểu - hai môi trường khác ngưỡng là hai kết quả
# Đo 2 không so được với nhau. Một knob chỉnh được từ môi trường mà không ai
# từng chỉnh là một mặt cấu hình thừa.
# Bảng hạng độ nhạy nằm đây vì nó không phải một knob môi trường mà là cấu hình
# đóng băng của *hệ*: khóa quyền của mọi mục đã nạp được tính bằng đúng bảng đó,
# nên hai môi trường hai bảng hạng là hai kho không so được với nhau và không
# re-ingest chung được (đổi hạng = re-ingest). Đường dẫn vẫn là một field để bộ
# test và `eval/` trỏ sang bảng khác được, chỉ là nó không đến từ `.env`.
KHOA_KHONG_LAY_TU_MOI_TRUONG: frozenset[str] = frozenset(
    {
        HEALTH_RETRIES_KEY,
        HEALTH_DELAY_KEY,
        COSINE_THRESHOLD_KEY,
        SENSITIVITY_RANKS_KEY,
    }
)


def cau_hinh_kho_tu_moi_truong(moi_truong=None) -> dict[str, str]:
    """Khóa cấu hình kho suy từ biến môi trường, bỏ qua biến chưa đặt.

    Biến rỗng tính là **chưa đặt**, không phải đặt bằng chuỗi rỗng: compose
    khai `QDRANT_API_KEY: "${QDRANT_API_KEY:-}"` nên một Qdrant không dùng
    api-key vẫn đẩy xuống một chuỗi rỗng, và một `api_key=""` đi vào client là
    một cấu hình sai im lặng. Khóa vắng thì field giữ mặc định của nó.

    Trả dict để nơi gọi bung vào constructor: `EngineACL(**cau_hinh, ...)`.
    Không tự dựng engine ở đây, vì `embedding_func` và `llm_model_func` không
    đến từ môi trường và chúng là hai thứ còn lại phải quyết tường minh.
    """
    nguon = os.environ if moi_truong is None else moi_truong
    cau_hinh = {}
    for khoa, ten_bien in BIEN_MOI_TRUONG.items():
        gia_tri = nguon.get(ten_bien)
        if gia_tri is None:
            continue
        gon = str(gia_tri).strip()
        if gon:
            # Lấy bản đã cắt khoảng trắng, không chỉ dùng nó để kiểm rỗng: một
            # `QDRANT_URL=" http://qdrant:6333 "` (dấu cách lọt vào lúc sửa
            # `.env`) đi thẳng xuống client thì lỗi nói về DNS, không nói về
            # cấu hình. Cùng thủ pháp với `core.keys.filter_key`.
            cau_hinh[khoa] = gon
    return cau_hinh


@dataclass
class EngineACL(HyperGraphRAG):
    """`HyperGraphRAG` với registry của dự án và vòng đời kết nối tường minh."""

    # --- Ba tên đăng ký, thay mặc định của upstream --------------------------
    kv_storage: str = TEN_KV
    vector_storage: str = TEN_VECTOR
    graph_storage: str = TEN_GRAPH

    # Cache LLM tắt hẳn (AD-18). Đây là lớp thứ nhất; lớp thứ hai là
    # `LLMCacheDisabled` của `adapters/kv.py`, nổ ngay trong
    # `super().__post_init__()` nếu ai đó bật cờ này - và nó nổ *qua registry
    # thật*, vì `llm_response_cache` dựng bằng chính lớp KV của dự án.
    enable_llm_cache: bool = ENABLE_LLM_CACHE

    # Mức log của engine, khai tường minh và cố ý **không** phải DEBUG. Đây là
    # chuyện bảo mật, không phải thẩm mỹ log: `hypergraphrag.py:178-179` dựng
    # `_print_config` từ `asdict(self)` - tức là gồm cả `neo4j_password` và
    # `qdrant_api_key` - rồi `logger.debug(...)`, trong khi `set_logger`
    # (`utils.py:35-47`) đã gắn sẵn một FileHandler mức DEBUG vào
    # `hypergraphrag.log`. Mặc định của upstream là `logger.level` lúc import,
    # tức NOTSET, nên hôm nay dòng đó không ra file - nhưng một
    # `logging.basicConfig(level=DEBUG)` ở `api/` cũng đủ để hai secret nằm
    # nguyên văn trên đĩa, đi ngược Policy "không bao giờ commit credentials".
    # Ghim mức ở đây là đóng đường đó lại từ phía engine.
    #
    # Che secret ngay cả khi ai đó cố ý bật DEBUG thì không làm được trong
    # story này (adapter cần giá trị thô để đưa vào driver) - khoản nợ có địa
    # chỉ story 3.1, lúc khóa ký JWT nhập vào cùng chỗ cấu hình.
    log_level: str = "INFO"

    # --- Khóa cấu hình kho ---------------------------------------------------
    # Tên field phải trùng hằng trong `KHOA_CAU_HINH_KHO`; test canh điều đó.
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    # Ngưỡng cosine của đường vector. Nó là field ở đây vì `asdict(self)` là
    # cái duy nhất đi xuống storage, mà `cosine_better_than_threshold` **không**
    # phải field của `HyperGraphRAG` (`hypergraphrag.py:108-169`): không có
    # dòng này thì `adapters/qdrant.py` luôn rơi về mặc định 0.2 của chính nó
    # và knob đó vô hiệu, dù comment ở đó nói ngược lại.
    cosine_better_than_threshold: float = 0.2
    neo4j_uri: str | None = None
    neo4j_username: str = NEO4J_USERNAME_MAC_DINH
    neo4j_password: str | None = None
    # Database của mọi phiên Neo4j. Community chỉ có một, nhưng truyền tường
    # minh thì không phiên nào dựa vào mặc định ngầm của server (khoản nợ vòng
    # đời kết nối, ledger story 1.4, địa chỉ 2.1).
    neo4j_database: str = NEO4J_DATABASE_MAC_DINH
    neo4j_health_retries: int = HEALTH_RETRIES_MAC_DINH
    neo4j_health_delay: float = HEALTH_DELAY_MAC_DINH
    # Đường dẫn file hạng độ nhạy. `None` nghĩa là dùng bảng chốt của repo
    # (`config/hang-do-nhay.yaml`); ba adapter nạp nó qua cùng một cửa nên
    # chúng không thể chạy trên hai bảng khác nhau.
    sensitivity_ranks_path: str | None = None

    # --- Khe tiêm kết nối ----------------------------------------------------
    # Hàm, không phải client: xem docstring đầu file. `None` nghĩa là "tự mở từ
    # cấu hình nếu có đủ khóa"; bộ test tiêm `lambda: gia_lap`.
    tao_qdrant_client: Callable[[], AsyncQdrantClient] | None = field(
        default=None, repr=False
    )
    tao_neo4j_driver: Callable[[], AsyncDriver] | None = field(
        default=None, repr=False
    )

    def __post_init__(self):
        # Kết nối phải có trước `super().__post_init__()`: chính lời gọi đó tra
        # registry và dựng sáu storage.
        cau_hinh = asdict(self)
        self._client_qdrant, self._tu_mo_qdrant = self._mo_qdrant(cau_hinh)
        self._driver_neo4j, self._tu_mo_neo4j = self._mo_neo4j(cau_hinh)
        self._da_dong = False
        super().__post_init__()

    def _mo_qdrant(self, cau_hinh) -> tuple[AsyncQdrantClient | None, bool]:
        """Client dùng chung cho ba namespace vector, và ai sở hữu nó.

        Thiếu cả hàm tiêm lẫn `qdrant_url` thì **không** nổ ở đây: trả `None`
        và để adapter tự dội `ValueError` của nó, thông điệp đã nói đúng khóa
        nào thiếu. Nhân bản luật kiểm cấu hình ở engine là hai bản dễ lệch.
        """
        if self.tao_qdrant_client is not None:
            return self._bat_buoc_co_ket_noi(
                self.tao_qdrant_client(), "tao_qdrant_client"
            ), False
        if not self.qdrant_url:
            return None, False
        return QdrantVectorDBStorage._dung_client(cau_hinh), True

    def _mo_neo4j(self, cau_hinh) -> tuple[AsyncDriver | None, bool]:
        """Driver dùng chung cho namespace graph, và ai sở hữu nó."""
        if self.tao_neo4j_driver is not None:
            return self._bat_buoc_co_ket_noi(
                self.tao_neo4j_driver(), "tao_neo4j_driver"
            ), False
        if not self.neo4j_uri:
            return None, False
        return Neo4jACLGraphStorage._dung_driver(cau_hinh), True

    @staticmethod
    def _bat_buoc_co_ket_noi(ket_noi, ten_khe: str):
        """Hàm tiêm trả `None` là lỗi của người tiêm, không phải "chưa cấu hình".

        Không có cửa này thì lời gọi rơi im lặng về nhánh "không có kết nối
        dùng chung" rồi nổ một `ValueError` nói về khóa cấu hình thiếu - một
        thông điệp đúng cú pháp mà sai nguyên nhân, và người đọc sẽ đi sửa
        `.env` trong khi lỗi nằm ở hàm tiêm.
        """
        if ket_noi is None:
            raise ValueError(
                f"{ten_khe} trả None: khe tiêm kết nối phải trả một kết nối"
                " thật. Muốn engine tự mở từ cấu hình thì để khe này là None,"
                " đừng trả None từ trong hàm."
            )
        return ket_noi

    def _get_storage_class(self) -> dict:
        """Registry của dự án: đúng ba adapter, kết nối bind sẵn.

        `partial` chứ không phải lớp trần khi có kết nối dùng chung - upstream
        gọi entry này như một callable với các tham số từ khóa của nó
        (`hypergraphrag.py:208-240`), và nó vốn đã chấp nhận entry không phải
        class (`lazy_external_import` trả closure).
        """
        return {
            TEN_KV: JsonACLKVStorage,
            TEN_VECTOR: (
                QdrantVectorDBStorage
                if self._client_qdrant is None
                else partial(
                    QdrantVectorDBStorage, qdrant_client=self._client_qdrant
                )
            ),
            TEN_GRAPH: (
                Neo4jACLGraphStorage
                if self._driver_neo4j is None
                else partial(
                    Neo4jACLGraphStorage, neo4j_driver=self._driver_neo4j
                )
            ),
        }

    # --- Vòng đời ------------------------------------------------------------

    async def khoi_tao(self) -> None:
        """Dựng collection, payload index và index graph; chạy dưới ngữ cảnh hệ thống.

        Upstream không có hook khởi tạo storage nào chạy trước lần upsert đầu
        (`index_done_callback` chạy *sau*), nên bước này phải do phía mình gọi.
        Cả bốn lời gọi đều lặp lại được, nên bước khởi động của tiến trình chạy
        mỗi lần lên mà không hỏng gì.

        Không tự mở ngữ cảnh: `space` là thuộc tính của lời gọi, và cửa duy
        nhất mở cờ bỏ-filter nằm ở `core/system_context.py` với một danh sách
        trắng import canh giữ (AD-3). Nơi gọi bọc `use_context(...)`, thiếu
        ngữ cảnh là `PermissionContextMissing` dội thẳng lên từ adapter.

        Tuần tự chứ không `gather`: bốn lời gọi này chạy một lần lúc khởi động
        và chúng dùng chung đúng hai kết nối, nên song song chỉ đổi lấy một
        thông điệp lỗi khó đọc khi một kho chưa lên.
        """
        for vdb in (self.entities_vdb, self.hyperedges_vdb, self.chunks_vdb):
            await vdb.initialize()
        await self.chunk_entity_relation_graph.initialize()

    async def dong(self) -> None:
        """Ghi kho KV xuống đĩa rồi đóng kết nối do chính engine mở.

        Hai bước, đúng thứ tự đó. Kho KV chỉ xuống đĩa ở `index_done_callback`
        (`storage.py:36`, và adapter của mình giữ nguyên nhịp ấy), nên tắt
        tiến trình mà không gọi là mất phần chưa flush.

        Mỗi storage được hỏi `close()` trước: chúng chỉ đóng thứ chúng tự mở,
        nên với kết nối dùng chung tiêm từ engine thì đó là no-op - gọi vẫn
        đúng, vì luật sở hữu sống ở một chỗ chứ không phải ở giả định của nơi
        gọi. Sau đó engine đóng phần của chính nó.

        Gọi hai lần không hỏng: đường tắt tiến trình có thể chạy hai lần.
        """
        if self._da_dong:
            return
        # Đặt cờ **sau** khi mọi bước xong, không phải trước. Một exception lúc
        # ghi đĩa mà cờ đã bật là: lời gọi `dong()` sau đó trả về ngay, kết nối
        # do engine mở nằm lại không ai đóng, và phần chưa flush mất luôn - đúng
        # thứ method này sinh ra để tránh. Hỏng giữa chừng thì gọi lại được, và
        # mỗi bước tự chịu trách nhiệm lặp lại được (`index_done_callback` ghi
        # file tạm rồi `os.replace`; `close()` của hai adapter là idempotent).
        for kho in (self.full_docs, self.text_chunks):
            await kho.index_done_callback()
        for kho in (
            self.entities_vdb,
            self.hyperedges_vdb,
            self.chunks_vdb,
            self.chunk_entity_relation_graph,
        ):
            await kho.close()
        if self._tu_mo_qdrant and self._client_qdrant is not None:
            await self._client_qdrant.close()
        if self._tu_mo_neo4j and self._driver_neo4j is not None:
            await self._driver_neo4j.close()
        self._da_dong = True

    # --- Truy vấn ------------------------------------------------------------

    async def aquery(self, query: str, param: QueryParam | None = None):
        """Một truy vấn, một `QueryParam` riêng của nó.

        `replace(param)` chứ không phải "dùng lại nếu nơi gọi có truyền": bản
        sao bảo vệ cả instance mặc định dùng chung của upstream lẫn instance
        của nơi gọi, và `_build_query_context` ghi lên `mode` của bất kỳ cái
        nào nó nhận được.
        """
        return await super().aquery(
            query, QueryParam() if param is None else replace(param)
        )
