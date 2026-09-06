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

import logging
import os
from dataclasses import asdict, dataclass, field, replace
from functools import partial
from typing import Callable

from hypergraphrag import HyperGraphRAG
from hypergraphrag.base import QueryParam
from hypergraphrag.operate import chunking_by_token_size
from hypergraphrag.utils import compute_mdhash_id
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient

from adapters.kv import ENABLE_LLM_CACHE, WORKING_DIR_KEY, JsonACLKVStorage
from adapters.llm_wrapper import LLMStreamNotSupported, la_wrapper
from adapters.tra_loi import (
    CAU_HONG_UPSTREAM,
    LY_DO_CO_NO_ANSWER,
    LY_DO_NGU_CANH_RONG,
    LY_DO_TU_KHOA_RONG,
    THAM_SO_LLM as THAM_SO_LLM_TRA_LOI,
    KetQuaHoiDap,
    NguCanhTruyHoiLa,
    doc_dau_ra,
    dung_prompt as dung_prompt_tra_loi,
    id_hyperedge_trong,
    ngu_canh_rong,
)
from adapters.trich_dan import dung_danh_sach
from adapters.trich_xuat import ThongKeTrichXuat, trich_xuat_chunks
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
from adapters.nhom_phu_trach import NHOM_PHU_TRACH_KEY
from adapters.sensitivity_loader import SENSITIVITY_RANKS_KEY
from adapters.tu_dien_thuc_the import ENTITY_DICTIONARY_KEY
from core.permission import current_context

logger = logging.getLogger(__name__)

# Tên đăng ký trong registry. Chuỗi này đi vào ba field `kv_storage`,
# `vector_storage`, `graph_storage` của upstream, nên nó là hợp đồng chứ không
# phải một cái tên tùy ý; đặt hằng để không có bản viết tay thứ hai.
# Danh mục `QueryParam.mode` mà engine chạy được. Chép đúng nhánh duy nhất của
# `vendor/hypergraphrag/hypergraphrag.py:497` (`if param.mode in ["hybrid"]`);
# đây là một phép **phản chiếu** một dòng vendor, không phải một quyết định
# riêng của dự án, nên sửa nó là phải đọc lại đúng dòng đó.
MODE_HO_TRO: frozenset[str] = frozenset({"hybrid"})

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
# Hai khóa vào ở story 2.1: `neo4j_database` (khoản nợ vòng đời kết nối
# Neo4j) và `sensitivity_ranks_path` (bảng hạng độ nhạy của luật hợp nhất khóa).
# Khóa vào ở story 2.12: `entity_dictionary_path` (từ điển thực thể chuẩn
# theo scope, FR-32). Nó đi cùng đường với bảng hạng - không phải khóa kết nối,
# nhưng `asdict(self)` là thứ duy nhất xuống tới `trich_xuat_chunks`, nên nó
# phải là một field của engine chứ không một tham số truyền tay.
# Khóa cuối vào ở story 3.1 (trả nợ): `owner_groups_path` (bảng nhóm phụ trách
# của dấu che `owner`). Cùng lý do và cùng đường với hai khóa trên - adapter
# graph đọc nó từ `global_config`, nên không có field này thì bảng nhóm là một
# hằng của tiến trình và không cấu hình nào chạm được.
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
    NHOM_PHU_TRACH_KEY,
    ENTITY_DICTIONARY_KEY,
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
# Từ điển thực thể nằm cùng chỗ và vì cùng lý do: đổi từ điển là đổi id entity
# và id hyperedge, tức re-ingest. Hai môi trường hai từ điển là hai kho không so
# được với nhau, đúng như hai bảng hạng khác nhau.
# Bảng nhóm phụ trách cũng vậy, và còn chặt hơn: nó là tên nhóm mà mọi vai đọc
# được trong câu trả lời FR-14, nên hai môi trường hai bảng là hai hệ nói hai
# tên cho cùng một tài liệu. Nó ở đây để bốn cấu hình đo của story 3.2 chứng
# minh được rằng chênh lệch của chúng không đến từ bảng nhóm.
KHOA_KHONG_LAY_TU_MOI_TRUONG: frozenset[str] = frozenset(
    {
        HEALTH_RETRIES_KEY,
        HEALTH_DELAY_KEY,
        COSINE_THRESHOLD_KEY,
        SENSITIVITY_RANKS_KEY,
        NHOM_PHU_TRACH_KEY,
        ENTITY_DICTIONARY_KEY,
    }
)


class LLMNotWrapped(TypeError):
    """`llm_model_func` hoặc `embedding_func` không đi qua wrapper của dự án.

    "Mọi lời gọi LLM đều qua wrapper" (AD-13, FR-30) mà chỉ là quy ước thì test
    cổng M1 dùng hàm giả trần vẫn xanh và không ai biết đường sản phẩm có bọc
    hay không. Cửa này biến quy ước thành cấu trúc: hàm trần không dựng được
    engine. Mã lỗi ổn định để test assert trên `code`.
    """

    code = "LLM_NOT_WRAPPED"


class QueryModeKhongHoTro(ValueError):
    """`QueryParam.mode` ngoài danh mục engine chạy được.

    `hypergraphrag.py:497-510` chỉ có nhánh `if param.mode in ["hybrid"]` rồi
    `return response`, nên mọi mode khác rơi vào một biến chưa gán và ra
    `UnboundLocalError` trần từ `vendor/`. Một `UnboundLocalError` không phải
    một mã lỗi của dự án: tầng API không đổi được nó thành `{error: {code,
    message}}` mà test assert lên (AD-8), và thông điệp của nó nói về một biến
    Python chứ không về tham số người gọi vừa gửi.

    Cửa này đứng **trước** khi chạm `vendor/`, nên nó cũng là chỗ duy nhất
    không phải sửa `vendor/` mà vẫn nói đúng nguyên nhân (khoản ledger 1.7).
    """

    code = "QUERY_MODE_KHONG_HO_TRO"


# Dấu gắn lên chính ngoại lệ khi `super().__post_init__()` nổ *sau* khi hai kết
# nối đã mở. Gắn lên lỗi gốc chứ không bọc nó vào một lớp mới, và đó là cả
# thiết kế: `api/man_nap.py` bắt theo `code`, `tests/test_engine_acl.py` bắt
# theo *loại* (`LLMCacheDisabled`, `ValueError` của adapter thiếu khóa), nên một
# lớp bọc thêm đổi cả hai hợp đồng để trả một khoản nợ về vòng đời kết nối - hai
# việc không liên quan gì nhau. Lỗi dội lên **nguyên vẹn**; thứ thêm vào chỉ là
# một chỗ để nơi gọi async tìm thấy phần phải đóng.
DAU_KET_NOI_CHUA_DONG: str = "_hyper_rag_ket_noi_chua_dong"


class KetNoiChuaDong:
    """Hai kết nối đã mở của một engine dựng hỏng, kèm luật sở hữu của chúng.

    `__post_init__` là hàm **đồng bộ** nên nó không `await close()` được, mà cả
    hai kết nối phải tồn tại *trước* lời gọi `super().__post_init__()` vì chính
    nó dựng sáu storage. Không có bản ghi này thì client Qdrant và driver Neo4j
    nằm lại trong một object không ai còn cầm tham chiếu (khoản ledger 1.7).

    `tu_mo_*` giữ nguyên luật sở hữu của `dong()`: kết nối tiêm từ ngoài thuộc
    về người tiêm, đóng hộ là làm hỏng kết nối của người khác.
    """

    def __init__(self, *, client_qdrant, tu_mo_qdrant, driver_neo4j, tu_mo_neo4j):
        self.client_qdrant = client_qdrant
        self.tu_mo_qdrant = tu_mo_qdrant
        self.driver_neo4j = driver_neo4j
        self.tu_mo_neo4j = tu_mo_neo4j

    async def dong(self) -> None:
        """Đóng đúng phần engine tự mở, theo thứ tự ngược; **không bao giờ ném**.

        Không ném vì nơi gọi đang trên đường dội lỗi gốc lên: một lỗi thứ hai ở
        đây thay chỗ lỗi gốc, và lỗi gốc mới là thứ nói được vì sao tiến trình
        không lên.
        """
        for co_mo, ket_noi in (
            (self.tu_mo_neo4j, self.driver_neo4j),
            (self.tu_mo_qdrant, self.client_qdrant),
        ):
            if not co_mo or ket_noi is None:
                continue
            try:
                await ket_noi.close()
            except Exception:  # noqa: BLE001
                logger.exception("không đóng được kết nối của một engine dựng hỏng")


def ket_noi_chua_dong(loi: BaseException) -> "KetNoiChuaDong | None":
    """Phần kết nối còn mở của một lỗi dựng engine, hoặc `None`.

    **Hai nơi gọi, và cả hai đều cần.** `api.hoi_dap.mo_engine` là đường phục
    vụ; `api.dot_nap.chay_lan_nap` là đường nạp, và nó cần *vì `api/man_nap.py`
    là một FastAPI chạy dài* - `_chay_nen` gọi `chay_lan_nap` mỗi lần có người
    tải tài liệu lên, nên một cấu hình sai thật (`QDRANT_URL` có mà `NEO4J_URI`
    thiếu) là mỗi đợt rò thêm một client. Lời khai cũ "dot_nap chạy một lượt
    rồi thoát" chỉ đúng với CLI `api/do_chi_phi.py`, không đúng với màn nạp.
    """
    ban_ghi = getattr(loi, DAU_KET_NOI_CHUA_DONG, None)
    return ban_ghi if isinstance(ban_ghi, KetNoiChuaDong) else None


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
    # Đường dẫn file nhóm phụ trách (story 3.1, FR-14). `None` nghĩa là dùng
    # bảng chốt của repo (`config/nhom-phu-trach.yaml`). Cùng hình dạng với
    # dòng trên vì cùng lý do: `asdict(self)` là thứ duy nhất xuống tới adapter
    # graph, nên một bảng nhóm cấu hình được phải là một field của engine.
    owner_groups_path: str | None = None
    # Đường dẫn file từ điển thực thể chuẩn theo scope (story 2.12, FR-32).
    # `None` nghĩa là **không có từ điển**, không phải "dùng file chốt của repo":
    # đường trích xuất khi đó chạy y hệt trước story này - prompt không có khối
    # từ điển và `ap_bi_danh` nhận bảng rỗng. Một từ điển mặc định ngầm là một
    # phép gộp thực thể mà không ai khai, và nó đổi id hyperedge của mọi space.
    entity_dictionary_path: str | None = None

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
        # Cửa từ chối hàm chưa bọc đứng trước mọi thứ khác (story 2.2): mặc
        # định của upstream (`gpt_4o_mini_complete`, `openai_embedding`) cũng
        # là hàm trần, nên quên truyền là nổ ở đây chứ không phải một engine
        # gọi API ngoài mà không đếm token và không kiểm space.
        for ten in ("llm_model_func", "embedding_func"):
            if not la_wrapper(getattr(self, ten)):
                raise LLMNotWrapped(
                    f"{ten} không đi qua wrapper của dự án; dựng bằng"
                    " adapters.llm_wrapper.bo_llm / bo_embedding (FR-30)"
                )
        # Kết nối phải có trước `super().__post_init__()`: chính lời gọi đó tra
        # registry và dựng sáu storage.
        cau_hinh = asdict(self)
        # Cả **ba** bước nằm trong cùng một khối phục hồi, không chỉ bước cuối.
        # Ca mà một khối chỉ bọc `super().__post_init__()` bỏ lọt là ca của
        # chính khoản nợ này: `_mo_qdrant` mở client xong rồi `_mo_neo4j` nổ
        # (thiếu `neo4j_uri`, hàm tiêm trả `None`) - client kia rò, và lỗi
        # không mang dấu nào để nơi gọi async đóng nó.
        self._client_qdrant = self._driver_neo4j = None
        self._tu_mo_qdrant = self._tu_mo_neo4j = False
        self._da_dong = False
        try:
            self._client_qdrant, self._tu_mo_qdrant = self._mo_qdrant(cau_hinh)
            self._driver_neo4j, self._tu_mo_neo4j = self._mo_neo4j(cau_hinh)
            super().__post_init__()
        except BaseException as loi:
            # Object này sắp bị vứt nên không ai còn tham chiếu để đóng phần đã
            # mở. Gắn nó lên chính lỗi rồi dội **nguyên vẹn** - `raise` trần,
            # giữ cả loại lẫn traceback (khoản ledger 1.7).
            #
            # Đọc thuộc tính chứ không đọc biến cục bộ: ở ca `_mo_neo4j` nổ thì
            # `self._driver_neo4j` còn là `None` và `self._tu_mo_neo4j` còn là
            # `False`, tức bản ghi mô tả đúng trạng thái **tại thời điểm nổ**.
            self._gan_ket_noi_chua_dong(loi)
            raise

    def _gan_ket_noi_chua_dong(self, loi: BaseException) -> None:
        """Gắn phần kết nối còn mở lên một lỗi dựng engine; không bao giờ ném.

        Tách thành method để ca "gắn không được" có một chỗ đọc được, và để
        `tests/test_engine_acl.py` chấm được nó tách khỏi đường dựng.
        """
        try:
            setattr(
                loi,
                DAU_KET_NOI_CHUA_DONG,
                KetNoiChuaDong(
                    client_qdrant=self._client_qdrant,
                    tu_mo_qdrant=self._tu_mo_qdrant,
                    driver_neo4j=self._driver_neo4j,
                    tu_mo_neo4j=self._tu_mo_neo4j,
                ),
            )
        except Exception:  # noqa: BLE001
            # Ngoại lệ từ chối thuộc tính mới (một lớp tự chặn `__setattr__`,
            # một proxy ngoại lệ của SDK). Hiếm - `__slots__` một mình không đủ,
            # vì mọi lớp con của `BaseException` đều có `__dict__` - nhưng im
            # lặng ở đây là đúng ca rò mà khoản ledger mô tả, nên nó phải để lại
            # một dòng.
            logger.exception(
                "không gắn được kết nối đã mở lên lỗi dựng engine;"
                " kết nối có thể nằm lại"
            )

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

    # --- Nạp -----------------------------------------------------------------

    async def ainsert(self, string_or_strings) -> ThongKeTrichXuat | None:
        """Đường nạp của upstream với bộ trích xuất 8 vai của dự án thay `extract_entities` (2.4).

        Chép đúng luồng `hypergraphrag.py:274-339` - doc id `doc-md5`,
        `filter_keys` hai lần, `chunks_vdb.upsert`, trích xuất, rồi
        `full_docs`/`text_chunks.upsert`, `_insert_done` trong `finally` - và
        chỉ đổi một bước: `adapters.trich_xuat.trich_xuat_chunks` thay
        `extract_entities`. Không gọi `super().ainsert`: hàm upstream gắn cứng
        `extract_entities` bên trong, không có khe tiêm.

        Trả `None` khi không có gì mới (doc hay mọi chunk đã trong kho), và
        trả `ThongKeTrichXuat` mọi khi trích xuất đã chạy - kể cả 0 fact hợp
        lệ, để pipeline phát `extract_doc` và phân biệt "LLM trả 0 bản ghi" với
        "N bản ghi đều bị loại". Ở ca 0 fact hợp lệ hàm dừng trước
        `full_docs`/`text_chunks.upsert` như upstream; pipeline dọn `chunks_vdb`.

        **Đúng một tài liệu mỗi lời gọi.** Upstream nhận danh sách; ở đây
        danh sách dài hơn một là `ValueError`: pipeline luôn gọi từng tài liệu
        (mỗi tài liệu một nhãn, một đợt, một `extract_doc`), và một thống kê gộp
        nhiều tài liệu che mất ca 0 fact của từng tài liệu.

        Chỉ `adapters/ingest.py` được gọi hàm này (import-lint canh).

        **Thứ tự phải đọc đúng, vì một lời khai cũ đọc sai nó** (khoản ledger
        2.12): `chunks_vdb.upsert(inserting_chunks)` chạy **trước**
        `trich_xuat_chunks`, và upsert đó nhúng mọi chunk. Nên một cấu hình mà
        `trich_xuat_chunks` mới kiểm - từ điển thực thể của story 2.12 - dừng
        đợt trước lời gọi **LLM** đầu tiên, không phải trước đồng tiền đầu tiên:
        tiền embedding của cả tài liệu đã tiêu. Ở ba đợt đã trả tiền embedding
        chiếm 1,8-2,3% tổng nên thiệt hại nhỏ, nhưng câu "dừng trước khi tiêu
        tiền" thì sai và không được viết lại ở đâu nữa.
        """
        update_storage = False
        try:
            if isinstance(string_or_strings, str):
                string_or_strings = [string_or_strings]
            string_or_strings = list(string_or_strings)
            if len(string_or_strings) != 1:
                raise ValueError(
                    f"ainsert nhận đúng một tài liệu mỗi lời gọi, nhận được {len(string_or_strings)}:"
                    " pipeline nạp tuần tự từng tài liệu để thống kê trích xuất không bị gộp"
                )
            new_docs = {
                compute_mdhash_id(c.strip(), prefix="doc-"): {"content": c.strip()}
                for c in string_or_strings
            }
            _add_doc_keys = await self.full_docs.filter_keys(list(new_docs.keys()))
            new_docs = {k: v for k, v in new_docs.items() if k in _add_doc_keys}
            if not new_docs:
                logger.warning("ainsert: mọi tài liệu đã có trong kho")
                return None
            update_storage = True

            inserting_chunks: dict[str, dict] = {}
            for doc_key, doc in new_docs.items():
                inserting_chunks.update(
                    {
                        compute_mdhash_id(dp["content"], prefix="chunk-"): {
                            **dp,
                            "full_doc_id": doc_key,
                        }
                        for dp in chunking_by_token_size(
                            doc["content"],
                            overlap_token_size=self.chunk_overlap_token_size,
                            max_token_size=self.chunk_token_size,
                            tiktoken_model=self.tiktoken_model_name,
                        )
                    }
                )
            _add_chunk_keys = await self.text_chunks.filter_keys(list(inserting_chunks.keys()))
            inserting_chunks = {k: v for k, v in inserting_chunks.items() if k in _add_chunk_keys}
            if not inserting_chunks:
                logger.warning("ainsert: mọi chunk đã có trong kho")
                return None

            await self.chunks_vdb.upsert(inserting_chunks)
            thong_ke = await trich_xuat_chunks(
                inserting_chunks,
                graph=self.chunk_entity_relation_graph,
                entity_vdb=self.entities_vdb,
                hyperedge_vdb=self.hyperedges_vdb,
                global_config=asdict(self),
            )
            if thong_ke.so_hop_le == 0:
                logger.warning("ainsert: không có fact hợp lệ nào, không ghi doc/chunk vào KV")
                return thong_ke
            await self.full_docs.upsert(new_docs)
            await self.text_chunks.upsert(inserting_chunks)
            return thong_ke
        finally:
            if update_storage:
                await self._insert_done()

    # --- Truy vấn ------------------------------------------------------------

    async def aquery(self, query: str, param: QueryParam | None = None):
        """Một truy vấn, một `QueryParam` riêng của nó, `mode` kiểm trước `vendor/`.

        `replace(param)` chứ không phải "dùng lại nếu nơi gọi có truyền": bản
        sao bảo vệ cả instance mặc định dùng chung của upstream lẫn instance
        của nơi gọi, và `_build_query_context` ghi lên `mode` của bất kỳ cái
        nào nó nhận được.

        Cửa `mode` là **một** phép kiểm chứ không phải một luật thứ hai của
        engine: `MODE_HO_TRO` chép đúng danh sách mà `hypergraphrag.py:497` có
        nhánh, và mọi giá trị khác ở đó cho `UnboundLocalError` trần. Kiểm ở
        đây vì từ story 3.3 `mode` đến được từ một request người dùng, và
        `vendor/` thì không sửa.
        """
        param = QueryParam() if param is None else replace(param)
        if param.mode not in MODE_HO_TRO:
            raise QueryModeKhongHoTro(
                f"mode {param.mode!r} không chạy được: engine chỉ hỗ trợ"
                f" {sorted(MODE_HO_TRO)}. Mode khác không phải một nhánh chậm,"
                " nó là một biến chưa gán trong vendor/hypergraphrag.py:497."
            )
        return await super().aquery(query, param)

    async def hoi_dap(self, cau_hoi: str, param: QueryParam | None = None) -> KetQuaHoiDap:
        """Một lượt hỏi đáp đầy đủ: ngữ cảnh của vendor, câu trả lời của dự án (story 3.5).

        **Method mới chứ không phải một nhánh trong `aquery`.** `eval/` và
        `tests/ho_tro_m1.py::hoi` gọi `aquery(..., only_need_context=True)` để
        lấy nguyên chuỗi ngữ cảnh, và toàn bộ bộ Đo 1 assert trên chuỗi đó (chốt
        brief §6: assert trên ngữ cảnh truy hồi, không trên câu trả lời LLM).
        Nhét nhánh từ chối vào `aquery` là đổi kiểu trả về của đường ấy; tách ra
        thì đường ngữ cảnh thô chạy y nguyên và ca "chỉ tốn một lời gọi LLM khi
        ngữ cảnh rỗng" vẫn đo được.

        Ba nhánh, và **thứ tự là nội dung**:

        1. Chuỗi trả về bằng đúng `CAU_HONG_UPSTREAM` -> `tu_khoa_rong`. Phải
           hỏi trước, vì `kg_query` trả câu ấy *thay cho* cả cái khung ngữ cảnh
           (`operate.py:573,576,581`) nên `ngu_canh_rong` sẽ đọc nó thành "không
           có khối csv nào" và cho `False`, tức một lỗi nội bộ đi thẳng vào một
           lời gọi LLM trả tiền.
        2. Ba khối csv của khung đều rỗng -> `ngu_canh_rong`, và **không có lời
           gọi LLM thứ hai**. Đây là chỗ ca L0 chặn sạch đi ra, và là nhánh tất
           định mà FR-16 đòi ("ngữ cảnh truy hồi rỗng thì render template không
           gọi LLM").
        3. **Citation dựng ở đây, trước lời gọi LLM** (story 3.4): id đọc từ
           cột `hyperedge` của ngữ cảnh chỉ là khóa tra, adapter graph xác
           nhận khóa quyền và các vai có mặt dưới chính ngữ cảnh vai này, hai
           hàm thuần của `core/masking.py` cho mức và tập vai bị che. Một id
           adapter không thấy là `TrichDanNgoaiQuyen` dội lên nguyên - 5xx,
           không lời gọi LLM trả tiền, không hàng `refusal`.
        4. Còn lại -> prompt của dự án, rồi `doc_dau_ra`. Cờ bật thì
           `co_no_answer` (citation bỏ đi, lượt từ chối rỗng); không thì một
           câu trả lời kèm citation.

        Đầu ra không đọc được **dội lên nguyên** dưới dạng `DauRaTraLoiKhongDoc`:
        nó là lỗi hệ thống, và nuốt nó thành một lý do từ chối thứ tư là trộn
        lỗi nội bộ vào hai cột mà Đo 2 (PRD 5.2) đếm. Cùng luật cho một `aquery`
        trả về thứ **không phải chuỗi**: `ngu_canh_rong` cho `True` với mọi giá
        trị không phải `str`, nên không có phép kiểm kiểu tường minh thì một lỗi
        nội bộ của đường truy hồi lặng lẽ thành một lượt từ chối được đo
        (`NguCanhTruyHoiLa`, cùng mã lỗi vì cùng mệnh đề).

        **`stream=True` bị từ chối tường minh**, và cửa này phải có vì đường mới
        làm mất một cửa cũ. Trước story 3.5 `kg_query:606` truyền
        `stream=query_param.stream` xuống wrapper và `bo_llm` dội
        `LLMStreamNotSupported`; đường này thoát ở `:596-597` nên lời gọi ấy
        không chạy nữa, và bỏ qua `param.stream` im lặng là biến một tham số vô
        hiệu thành một tham số trông như có tác dụng (khoản ledger 2.2, UX-DR4).
        Handler không truyền `param` nên nó không tới được từ HTTP; cửa này canh
        nơi gọi trong mã dự án.

        `self.llm_model_func` là field của `HyperGraphRAG` đã bọc qua
        `limit_async_func_call` và `partial(hashing_kv=...)`
        (`hypergraphrag.py:242-248`), tức đúng hàm mà `kg_query` gọi. Dùng lại nó
        chứ không dựng một hàm mới: một hàm thứ hai là một đường LLM thứ hai
        không đi qua wrapper đếm token của story 2.2, và khi đó `llm_cost` của
        một lượt hỏi thiếu mất một nửa.

        **Không có lớp thử lại, và từ story này đó là một lựa chọn chứ không một
        chỗ không gắn được.** Lý lẽ cũ - "nơi gọi nằm trong `vendor/kg_query` nên
        không có chỗ nào gắn một lớp thử lại" (`adapters/llm_wrapper.bo_llm`,
        AGENTS.md) - hết đúng ở đây: lời gọi thứ hai nay nằm trong mã dự án, tức
        chỗ gắn đã có. Vẫn không gắn, vì hai lý do đã đóng băng ở story 3.3: một
        429 giữa một câu hỏi là 502 ngay (khác hẳn đường nạp, và đó là câu chương
        4 phải nói), và một lớp thử lại ở đây nhân trần độ trễ của một request
        lên - trần 204 giây suy từ số lời gọi *không* thử lại. Trần thời gian cho
        một lời gọi thì vẫn có, ở `bo_llm`.

        Không đi qua cache LLM của upstream, và không được bật nó lại:
        `compute_args_hash` (`operate.py:493-500,622-634`) chỉ băm `(mode,
        query)`, không mang space, vai hay `policy_version`, nên một lượt trả lời
        được cache đi xuyên ranh giới quyền (AD-18).
        """
        param = QueryParam() if param is None else replace(param)
        if param.stream:
            raise LLMStreamNotSupported(
                "hoi_dap không chạy stream: wrapper chưa đếm được token trên"
                " stream, và đường này không còn đi qua lời gọi của vendor - nơi"
                " phép kiểm ấy từng nằm"
            )
        ngu_canh = await self.aquery(cau_hoi, replace(param, only_need_context=True))
        if not isinstance(ngu_canh, str):
            raise NguCanhTruyHoiLa(
                "đường truy hồi trả về"
                f" {type(ngu_canh).__name__} thay vì chuỗi ngữ cảnh: đó là một"
                " lỗi nội bộ, không phải một lượt từ chối"
            )
        if ngu_canh == CAU_HONG_UPSTREAM:
            logger.warning("hoi_dap: kg_query không trích được từ khóa, từ chối")
            return KetQuaHoiDap(ly_do_tu_choi=LY_DO_TU_KHOA_RONG)
        if ngu_canh_rong(ngu_canh):
            return KetQuaHoiDap(ly_do_tu_choi=LY_DO_NGU_CANH_RONG)
        # Citation trước khi trả tiền cho lời gọi LLM: cửa quyền của adapter
        # graph chạy dưới đúng contextvar của request (cùng ngữ cảnh mà ba
        # adapter vừa lọc), và bảng nhóm là bảng của chính adapter ấy.
        graph = self.chunk_entity_relation_graph
        ids = id_hyperedge_trong(ngu_canh)
        tu_adapter = await graph.trich_dan_cua(ids) if ids else {}
        trich_dan = dung_danh_sach(current_context(), ids, tu_adapter, graph.bang_nhom.nhom_cua)
        tho = await self.llm_model_func(
            dung_prompt_tra_loi(cau_hoi, ngu_canh), **THAM_SO_LLM_TRA_LOI
        )
        ket_qua = doc_dau_ra(tho)
        if ket_qua.khong_co_dap_an:
            return KetQuaHoiDap(ly_do_tu_choi=LY_DO_CO_NO_ANSWER)
        return KetQuaHoiDap(cau_tra_loi=ket_qua.cau_tra_loi, trich_dan=trich_dan)
