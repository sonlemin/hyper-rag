"""Adapter Qdrant: điểm chèn quyền duy nhất của đường vector (FR-07, chốt 2).

Hợp đồng với upstream giữ nguyên - `upsert(data: dict[str, dict])` embed từ
field `content`, `query(query, top_k)` trả list dict có `distance` cộng đủ
`meta_fields` - nên `HyperGraphRAG` không biết gì về quyền và `vendor/` không
phải sửa một dòng nào. Toàn bộ phần quyền nằm ở hai chỗ trong file này:

- lúc `upsert`, khóa `{scope}:{content_type}` lấy từ phạm vi nhãn ingest đang
  mở (`adapters/ingest_labels.py`) và ghi vào payload;
- lúc `query`, tập khóa lấy từ `context.keys_for(namespace)` và đi cùng search
  request dưới dạng `match_any` trên đúng một field keyword.

Pre-filter, không post-filter: bộ lọc gửi kèm truy vấn nên dữ liệu ngoài quyền
không bao giờ được chấm điểm trong HNSW. Không có nhánh nào lọc lại phía Python
sau khi có kết quả, và không có nhánh nào chạy với filter rỗng - tập khóa rỗng
là trả `[]` mà không chạm Qdrant.

Adapter không tự suy mức L0/L1/L2 và không đọc bảng chính sách. Ngữ nghĩa mức
theo namespace (NFR-06) đã nằm trong `core/policy.py`; ở đây chỉ có "hỏi tập
khóa của namespace này rồi lọc theo nó".

Filter là `match_any` một field, cố ý không AND đa điều kiện: extra HNSW edge
chỉ dựng cho một field đã có index lúc build, nên lọc nhiều điều kiện là điểm
mù recall (research qdrant-filterable-hnsw). Cũng vì thế payload index phải
tạo trước khi nạp dữ liệu, và upsert từ chối chạy khi index chưa có (AD-4).
"""

import asyncio
from dataclasses import dataclass

from hypergraphrag.base import BaseVectorStorage
from qdrant_client import AsyncQdrantClient, models

from adapters.doi_chieu import KHO_GRAPH, ghi_vao_so, ten_kho_kv, ten_kho_vector
from adapters.ingest_labels import (
    bat_buoc_ngu_canh_he_thong,
    ingest_keys_for_write,
)
# Hợp đồng che dùng chung với hai adapter kia: một luật, một chỗ. `_ban_ghi`
# gọi `kiem_ket_qua_che` chứ không tự viết một nửa hợp đồng. `MaskContractViolated`
# nhập lại ở đây để tên vẫn lấy được từ `adapters.qdrant`, như nơi gọi cũ vẫn làm.
from adapters.mask_contract import MaskContractViolated, kiem_ket_qua_che
from adapters.sensitivity_loader import bang_hang_cho
from core.ids import normalize_id, point_id
from core.keys import CHUA_GHI, FILTER_KEY_FIELD, KHONG_KHOA
from core.masking import mask
from core.permission import current_context

# Khóa cấu hình đọc từ `global_config` (upstream truyền `asdict(HyperGraphRAG)`).
QDRANT_URL_KEY = "qdrant_url"
QDRANT_API_KEY_KEY = "qdrant_api_key"
EMBEDDING_BATCH_KEY = "embedding_batch_num"
COSINE_THRESHOLD_KEY = "cosine_better_than_threshold"

# Id điểm Qdrant phải là UUID hoặc số nguyên, còn id của upstream là chuỗi
# (`rel-…`, `ent-…`, `chunk-…`). Point id là UUID5 của id gốc, id gốc giữ trong
# payload dưới field này rồi trả lại nguyên vẹn ở khóa `id` của kết quả - nhờ
# vậy id join chéo Qdrant và Neo4j vẫn là một (Consistency Conventions).
UPSTREAM_ID_FIELD = "upstream_id"

# Không bao giờ ghi nội dung vào payload: kho vector không được thành bản sao
# thứ hai của nội dung chưa che.
CONTENT_FIELD = "content"

# Hai `meta_fields` mà upstream đặt cho hai namespace có mặt trên graph
# (`hypergraphrag.py:224-234`), và cũng là *id node* của mục tương ứng
# (`operate.py:461-479` ghi chính chuỗi ấy vào payload rồi `operate.py:943,747`
# mang nó đi hỏi `get_node`). Nhờ vậy một point vector nói được nó ứng với node
# nào, và bước đối chiếu hai kho có id join mà không phải dựng lại phép băm
# `compute_mdhash_id` của upstream ở một chỗ thứ hai. Namespace `chunks` không
# có meta field nào nên id join của nó là chính id upstream - trùng với id bản
# ghi ở kho KV.
TRUONG_TEN_NODE: tuple[str, ...] = ("entity_name", "hyperedge_name")

# Số cạnh HNSW dựng riêng cho từng giá trị của field đã có payload index. Đây
# là thứ biến "có index" thành "pre-filter chạy trong HNSW" thay vì thành một
# lần duyệt vét cạn có lọc; không đặt nó thì cả AD-4 lẫn `QdrantIndexMissing`
# đang canh một cơ chế chưa được bật.
PAYLOAD_M = 16
# Giữ index toàn cục, cố ý không theo khuyến nghị `m=0` của hướng dẫn tenant
# Qdrant. Khuyến nghị đó đúng khi *mọi* truy vấn đều mang filter tenant, còn ở
# đây ngữ cảnh hệ thống đọc thô không filter (AD-3): tắt index toàn cục là
# biến đường ingest và mọi lần đọc thô thành full scan.
GLOBAL_M = 16
# Số điều kiện tối đa một filter được mang, ép ở phía server (PRD addendum).
# Quy ước trong code cộng helper assert trong test chỉ chặn được đường code
# hiện tại; hằng này chặn cả những đường chưa viết. Nếu Epic 5 (break-glass)
# thật sự cần filter hai điều kiện thì phải quay lại nới chỗ này có chủ đích
# kèm lý do, không nới lén ở một adapter nào đó.
FILTER_MAX_CONDITIONS = 1


class QdrantIndexMissing(RuntimeError):
    """Ghi dữ liệu khi payload index khóa chưa tồn tại.

    Extra HNSW edge chỉ dựng cho field đã có index lúc build, nên point ghi
    trước index là một vùng vĩnh viễn nằm ngoài đường lọc nhanh. Từ chối cả lô
    chứ không tự tạo index rồi ghi tiếp: thứ tự đó mới là thứ phải giữ.
    """

    code = "QDRANT_INDEX_MISSING"


class PointIdCollision(RuntimeError):
    """Hai id upstream khác nhau trong cùng một lô chuẩn hóa về một point id.

    `point_id` là UUID5 của id đã chuẩn hóa (NFC, cắt khoảng trắng, gỡ nháy
    kép), nên hai id chỉ khác nhau ở đúng những thứ đó là một point. Nếu để
    chạy tiếp thì bước đọc khóa cũ nuốt mất một id (báo `CHUA_GHI`), phép hợp
    nhất mất khóa cũ, và point nhận nhãn **rộng hơn** nhãn nó đang mang - một
    đường fail-open im lặng. Từ chối cả lô, ở chỗ còn biết hai id nào đụng nhau.

    `code` là mã lỗi ổn định để test assert trên `code` (AD-8).
    """

    code = "POINT_ID_COLLISION"


class PointFilterKeyMissing(RuntimeError):
    """Một point rời kho mà không mang khóa quyền trong payload.

    Chỉ xảy ra khi có ai đó ghi vào collection này không qua adapter, nên đây
    là hỏng dữ liệu chứ không phải ca vận hành bình thường. Vẫn phải nổ: che
    một mục bằng khóa rỗng nghĩa là không che gì, đúng kiểu mặc định fail-open
    mà cả story này dựng ra để chống.
    """

    code = "POINT_FILTER_KEY_MISSING"


@dataclass
class QdrantVectorDBStorage(BaseVectorStorage):
    """`BaseVectorStorage` của upstream, ruột là Qdrant có pre-filter theo khóa."""

    # Bước đối chiếu hai kho hỏi thuộc tính này (`adapters/doi_chieu.py`).
    # `True` vì ca hợp nhất ra "không khóa" **xóa** point (AD-5 đòi vắng mặt
    # tuyệt đối), nên nhìn từ đây một point vắng có thể là chưa từng ghi hoặc
    # đã hợp nhất ra không khóa - kho này không phân biệt được hai thứ đó.
    # Không chú kiểu: một annotation biến nó thành field của dataclass, và khi
    # đó nó đi vào `asdict(self)` rồi xuống `global_config` như một khóa cấu
    # hình - thứ nó không phải.
    VANG_LA_MO_HO = True

    # Giữ tên và giá trị mặc định của upstream. Khóa `cosine_better_than_threshold`
    # trong `global_config` chỉ *thật sự* có tác dụng từ story 1.7: nó không phải
    # field của `HyperGraphRAG` (`hypergraphrag.py:108-169`) nên `asdict(self)`
    # của engine upstream không bao giờ mang nó xuống, và trước đó ngưỡng luôn
    # đóng cứng ở giá trị mặc định dưới đây. `EngineACL` khai nó thành field nên
    # nhánh `cau_hinh.get(...)` bên dưới mới có đường chạy vào.
    cosine_better_than_threshold: float = 0.2
    # Client tiêm sẵn, tùy chọn. `adapters/engine.py` tiêm một client dùng
    # chung cho cả ba namespace vector; không tiêm thì mỗi instance tự mở kết
    # nối riêng từ `qdrant_url`, và khi đó chính nó đóng lại ở `close()`. Đây
    # cũng là chỗ bộ test cắm client local mode có ghi nhật ký vào.
    qdrant_client: AsyncQdrantClient | None = None

    def __post_init__(self):
        cau_hinh = self.global_config or {}
        self._client = self.qdrant_client or self._dung_client(cau_hinh)
        # Chỉ đóng client do chính adapter mở: engine tiêm một client dùng
        # chung cho ba namespace, đóng hộ nó là làm hỏng hai namespace kia.
        # Cùng luật sở hữu với `Neo4jACLGraphStorage`.
        self._tu_mo_client = self.qdrant_client is None
        self._max_batch_size = self._kich_thuoc_lo(cau_hinh)
        self.cosine_better_than_threshold = cau_hinh.get(
            COSINE_THRESHOLD_KEY, self.cosine_better_than_threshold
        )
        # Bảng hạng độ nhạy, nạp lúc dựng adapter: file hỏng phải nổ ở bước
        # khởi động chứ không giữa một đợt nạp. Cùng nguồn cho cả ba adapter
        # (`adapters/sensitivity_loader.bang_hang_cho`), nên ba đường ghi không
        # chạy trên hai bảng hạng khác nhau.
        self._bang_hang = bang_hang_cho(cau_hinh)

    async def close(self) -> None:
        """Đóng client do chính adapter mở; `adapters/engine.py` gọi lúc tắt.

        Client tiêm từ ngoài thì không đóng: nó là của người tiêm. Với engine
        của dự án thì mọi instance đều nhận client tiêm sẵn, nên method này là
        no-op ở đường sản phẩm - và nó vẫn phải tồn tại, vì luật sở hữu sống ở
        chỗ giữ kết nối chứ không sống ở giả định của nơi gọi.
        """
        if self._tu_mo_client:
            await self._client.close()

    @staticmethod
    def _kich_thuoc_lo(cau_hinh) -> int:
        """Kích thước lô embedding, kiểm ngay lúc dựng adapter.

        `range(0, n, 0)` nổ bằng `ValueError` giữa đường ghi, cách nơi gây ra
        nó vài tầng. Cấu hình sai phải hỏng lúc dựng, chỗ người sửa cấu hình
        còn đang nhìn vào cấu hình.
        """
        gia_tri = cau_hinh.get(EMBEDDING_BATCH_KEY, 32)
        try:
            n = int(gia_tri)
        except (TypeError, ValueError):
            raise ValueError(
                f"{EMBEDDING_BATCH_KEY} = {gia_tri!r} không phải số nguyên"
            ) from None
        if n < 1:
            raise ValueError(f"{EMBEDDING_BATCH_KEY} phải >= 1, nhận được {n}")
        return n

    @staticmethod
    def _dung_client(cau_hinh) -> AsyncQdrantClient:
        """Client từ `global_config`; async toàn tuyến, không trộn driver sync."""
        url = cau_hinh.get(QDRANT_URL_KEY)
        if not url:
            raise ValueError(
                f"thiếu {QDRANT_URL_KEY!r} trong global_config và không có client"
                " nào được tiêm vào: adapter Qdrant không có gì để nối tới"
            )
        return AsyncQdrantClient(
            url=url,
            api_key=cau_hinh.get(QDRANT_API_KEY_KEY),
            # Tắt thăm dò phiên bản: nó chạy một HTTP call chặn trong một
            # thread nền ngay lúc dựng client, mà thứ nó kiểm thì đã được ghim
            # sẵn hai đầu (Qdrant 1.19.0 trong docker-compose, qdrant-client
            # trong pyproject). Một I/O chặn lén trong `__post_init__` đi ngược
            # luật async toàn tuyến của dự án.
            check_compatibility=False,
        )

    # --- Tên collection và bước khởi tạo ----------------------------------

    def _ten_collection(self, context=None) -> str:
        """`{space}_{namespace}`, `space` lấy từ ngữ cảnh hiện tại (AD-12).

        Tính theo từng lời gọi chứ không ghim lúc `__post_init__`: `space` là
        thuộc tính của request, một instance adapter phục vụ nhiều không gian.
        Thiếu ngữ cảnh là `PermissionContextMissing` dội thẳng lên từ đây.
        Nơi gọi đã cầm sẵn ngữ cảnh thì truyền vào, để tên collection chỉ có
        một công thức duy nhất.
        """
        return f"{(context or current_context()).space}_{self.namespace}"

    async def initialize(self) -> str:
        """Tạo collection và payload index khóa trong cùng một bước (AD-4).

        Hai lời gọi liền nhau, không có đường ghi dữ liệu nào chen vào giữa:
        index phải có mặt trước khi point đầu tiên được nạp. Cả hai đều lặp lại
        được, nên gọi lại lúc khởi động không hỏng gì.

        Hai tham số của collection chỉ có hiệu lực trên Qdrant thật, local mode
        nhận rồi bỏ qua: `hnsw_config.payload_m` dựng cạnh HNSW theo khóa quyền,
        `strict_mode_config` là hàng rào phía server cho cùng luật mà adapter tự
        giữ. Hiệu lực thật của cả hai là khoản kiểm ở cổng M1.
        """
        ten = self._ten_collection()
        if not await self._client.collection_exists(collection_name=ten):
            await self._client.create_collection(
                collection_name=ten,
                vectors_config=models.VectorParams(
                    size=self.embedding_func.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
                hnsw_config=models.HnswConfigDiff(payload_m=PAYLOAD_M, m=GLOBAL_M),
                strict_mode_config=models.StrictModeConfig(
                    enabled=True,
                    filter_max_conditions=FILTER_MAX_CONDITIONS,
                    # Lọc trên field chưa có index là đúng thứ AD-4 cấm; để
                    # server từ chối thay vì âm thầm duyệt vét cạn.
                    unindexed_filtering_retrieve=False,
                    unindexed_filtering_update=False,
                ),
            )
        await self._client.create_payload_index(
            collection_name=ten,
            field_name=FILTER_KEY_FIELD,
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                # Gom dữ liệu cùng một khóa nằm gần nhau trên đĩa: khóa quyền
                # chính là chiều tenant của kho này.
                is_tenant=True,
            ),
        )
        return ten

    async def _bat_buoc_co_index(self, ten: str) -> None:
        """Từ chối ghi khi payload index khóa chưa có hoặc sai kiểu (AD-4).

        Kiểm cả kiểu chứ không chỉ sự có mặt: index `text` tách từ nên
        `match_any` trượt, và index keyword thiếu `is_tenant` không gom dữ liệu
        theo khóa. Cả hai đều là index "có" mà cơ chế này hỏng - đúng ca mà
        cửa đây dựng ra để chặn. `initialize()` luôn tạo keyword + `is_tenant`,
        nên một index khác kiểu nghĩa là có ai đó tạo tay theo cách khác.
        """
        if not await self._client.collection_exists(collection_name=ten):
            raise QdrantIndexMissing(
                f"collection {ten!r} chưa tồn tại nên chưa có payload index"
                f" {FILTER_KEY_FIELD!r}: chạy initialize() trước khi nạp"
            )
        thong_tin = await self._client.get_collection(collection_name=ten)
        mo_ta = (thong_tin.payload_schema or {}).get(FILTER_KEY_FIELD)
        if mo_ta is None:
            raise QdrantIndexMissing(
                f"collection {ten!r} thiếu payload index {FILTER_KEY_FIELD!r}:"
                " point nạp trước index nằm ngoài đường lọc nhanh vĩnh viễn"
            )
        if mo_ta.data_type != models.PayloadSchemaType.KEYWORD:
            raise QdrantIndexMissing(
                f"payload index {FILTER_KEY_FIELD!r} của {ten!r} là"
                f" {mo_ta.data_type!r}, phải là keyword để `match_any` khớp"
                " nguyên khóa"
            )
        tham_so = mo_ta.params
        # params vắng nghĩa là index tạo bằng kiểu trần, `is_tenant` khi đó là
        # false theo mặc định của Qdrant - vẫn là sai so với initialize().
        if not isinstance(tham_so, models.KeywordIndexParams) or not tham_so.is_tenant:
            raise QdrantIndexMissing(
                f"payload index {FILTER_KEY_FIELD!r} của {ten!r} không bật"
                " `is_tenant`: khóa quyền là chiều tenant của kho này"
            )

    # --- Ghi ---------------------------------------------------------------

    async def khoa_hien_co(self, ids: list[str]) -> dict[str, object]:
        """Khóa quyền mà kho đang giữ cho từng id upstream, không đọc gì khác.

        Bước đọc của read-merge-write (FR-11) và cũng là cửa mà bước đối chiếu
        hai kho hỏi. Chỉ trả trường khóa: nó không phải một đường đọc nội dung,
        nên tầng che không áp dụng và cũng không có gì để che.

        Chạy dưới cờ system, và đó là điều kiện để luật hợp nhất đúng: bị lọc
        theo khóa của tài liệu đang nạp thì nó không bao giờ thấy khóa khác
        scope cần hợp nhất, và khi ấy mọi artifact đa nguồn khác scope lặng lẽ
        nhận khóa của lần ghi cuối - đúng lỗ story này đóng.

        Ba giá trị trả về, đúng ba trạng thái mà `core.keys.hop_nhat_khoa` phân
        biệt: `CHUA_GHI` (point vắng), một khóa thật, và - không bao giờ ở kho
        này - `KHONG_KHOA`. Ca không khóa **xóa** point khỏi collection (AD-5
        đòi vắng mặt tuyệt đối), nên nhìn từ Qdrant nó trùng với "chưa từng
        ghi"; bước đối chiếu nhận cả hai khả năng cho báo cáo của kho vector.
        """
        bat_buoc_ngu_canh_he_thong("đọc khóa hiện có của kho vector")
        if not ids:
            return {}
        ten = self._ten_collection()
        theo_point = self._theo_point_id(ids)
        ban_ghi = await self._client.retrieve(
            collection_name=ten,
            ids=list(theo_point),
            with_payload=[FILTER_KEY_FIELD],
            with_vectors=False,
        )
        ket_qua: dict[str, object] = {id_goc: CHUA_GHI for id_goc in ids}
        for r in ban_ghi:
            khoa = (r.payload or {}).get(FILTER_KEY_FIELD)
            if not khoa:
                raise PointFilterKeyMissing(
                    f"point {r.id!r} của {ten!r} nằm trong kho mà không mang"
                    f" {FILTER_KEY_FIELD!r}: point không khóa lẽ ra đã bị xóa,"
                    " nên đây là dữ liệu hỏng chứ không phải ca không khóa"
                )
            ket_qua[theo_point[str(r.id)]] = khoa
        return ket_qua

    @staticmethod
    def _theo_point_id(ids: list[str]) -> dict[str, str]:
        """`point_id -> id upstream`, và cửa canh phép ánh xạ đó còn 1-1.

        Không có cửa này thì một lô mang hai id chuẩn hóa về cùng một point
        lặng lẽ mất một id ở bước đọc khóa cũ - xem `PointIdCollision`.
        """
        theo_point: dict[str, str] = {}
        for id_goc in ids:
            pid = point_id(id_goc)
            if pid in theo_point and theo_point[pid] != id_goc:
                raise PointIdCollision(
                    f"id {theo_point[pid]!r} và {id_goc!r} cùng cho point id"
                    f" {pid}: đọc khóa cũ sẽ nuốt mất một trong hai và point"
                    " nhận nhãn rộng hơn nhãn nó đang mang"
                )
            theo_point[pid] = id_goc
        return theo_point

    async def upsert(self, data: dict[str, dict]) -> list[str]:
        """Ghi một lô point, khóa của mỗi point hợp nhất với khóa nó đang mang.

        Bốn cửa phải qua trước khi chạm kho, theo thứ tự từ chung tới riêng:
        có ngữ cảnh (để biết `space`), có index (để khóa còn tác dụng), có ngữ
        cảnh hệ thống (để đọc được khóa cũ của mọi scope), có nhãn ingest và
        loại nội dung có hạng (để hợp nhất được). Hỏng cửa nào cũng là từ chối
        cả lô - ghi được một nửa lô còn tệ hơn không ghi gì, vì nửa kia không ai
        biết thiếu. Bốn cửa kiểm hết trước khi ghi point đầu tiên, nên "từ chối
        cả lô" vẫn đúng sau khi phần tải lên được chia lô.

        Read-merge-write, không phải last-write-wins: `point_id` là UUID5 của id
        upstream nên một entity xuất hiện ở hai tài liệu chỉ có một point, và
        trước story 2.1 point ấy mang nhãn của tài liệu nạp *sau*. Nay khóa cũ
        được đọc lại rồi hợp nhất ở cửa chung (`ingest_keys_for_write`).

        Ca hợp nhất ra "không khóa" thì point cũ bị **xóa** và không có point
        mới nào được ghi: vắng mặt tuyệt đối ở cả 3 collection là yêu cầu của
        AD-5, không phải một khóa đặc biệt. Xóa chạy **trước** phần ghi, và đó
        là chiều an toàn của một lô đứt giữa chừng: hỏng sau khi xóa thì mất
        một point lẽ ra còn (truy hồi thiếu, nhìn thấy được, chạy lại là xong),
        còn hỏng trước khi xóa thì để lại một point lẽ ra phải vắng, mang khóa
        cũ **rộng hơn** - tức một mục đa nguồn khác scope vẫn lọt vào tập khóa
        của một vai.

        Giá trị trả về là point id của phần *đã ghi*, nên nó ngắn hơn đầu vào
        khi lô có mục hợp nhất ra không khóa. Upstream không đọc giá trị này ở
        đường nào (`hypergraphrag.py:320,336` và `operate.py:470,479` đều gọi
        rồi bỏ), nên hợp đồng đó an toàn - và có test ghim đúng câu ấy thay vì
        để nó là một giả định.

        Tải lên chia theo cùng `embedding_batch_num` với phần embedding: một
        request mang cả nghìn point là một request dễ chạm timeout và khó đọc
        khi hỏng. Đứt giữa chừng thì lô đã gửi nằm lại, nhưng point id là UUID5
        của id upstream nên chạy lại chỉ ghi đè đúng chỗ cũ - lặp lại được,
        không sinh bản sao.
        """
        if not data:
            return []
        ten = self._ten_collection()
        await self._bat_buoc_co_index(ten)

        ids_goc = list(data)
        khoa_theo_id = ingest_keys_for_write(
            await self.khoa_hien_co(ids_goc), hang=self._bang_hang.hang
        )
        can_ghi = [id for id in ids_goc if khoa_theo_id[id] is not KHONG_KHOA]
        can_xoa = [id for id in ids_goc if khoa_theo_id[id] is KHONG_KHOA]

        # Ghi sổ **ý định** trước khi chạm kho: một lô đứt giữa chừng phải để
        # lại id trong sổ mà khóa vắng ở kho, chứ không để lại một id vô hình
        # với bước đối chiếu cuối đợt (NFR-03).
        for id_goc in ids_goc:
            ghi_vao_so(
                id_join=self._id_join(id_goc, data[id_goc]),
                kho=ten_kho_vector(self.namespace),
                id_trong_kho=id_goc,
                kho_doi=self._kho_doi(),
            )

        if can_xoa:
            await self._client.delete(
                collection_name=ten,
                points_selector=models.PointIdsList(
                    points=[point_id(id_goc) for id_goc in can_xoa]
                ),
                wait=True,
            )

        vectors = await self._embed_theo_lo(
            [data[id][CONTENT_FIELD] for id in can_ghi]
        )
        if len(vectors) != len(can_ghi):
            raise RuntimeError(
                f"embedding trả về {len(vectors)} vector cho {len(can_ghi)} mục:"
                " không ghép 1-1 được, từ chối cả lô"
            )
        diem = [
            models.PointStruct(
                id=point_id(id_goc),
                vector=vectors[i],
                payload=self._payload(id_goc, data[id_goc], khoa_theo_id[id_goc]),
            )
            for i, id_goc in enumerate(can_ghi)
        ]
        n = self._max_batch_size
        for i in range(0, len(diem), n):
            await self._client.upsert(
                collection_name=ten, points=diem[i : i + n], wait=True
            )
        return [d.id for d in diem]

    def _kho_doi(self) -> str | None:
        """Kho mà mọi id của namespace này *cũng* phải có mặt (NFR-03).

        Khai từ phía kho biết câu trả lời: hai namespace có mặt trên graph đi
        cùng kho graph, còn `chunks` là bản sao vector của kho KV `text_chunks`.
        Không khai thì một id chỉ được một kho ghi sổ luôn tự khớp với chính nó
        và ca "có ở kho này thiếu ở kho kia" đi qua im lặng.
        """
        if self.namespace == "chunks":
            return ten_kho_kv("text_chunks")
        return KHO_GRAPH

    @staticmethod
    def _id_join(id_goc: str, gia_tri: dict) -> str:
        """Id dùng để nối một point với node graph tương ứng của nó.

        Tên node nếu lô mang nó (`entity_name`/`hyperedge_name` - upstream ghi
        chính chuỗi đó vào payload và cũng dùng nó làm id node), còn lại là
        chính id upstream (namespace `chunks`, trùng id bản ghi ở kho KV).
        Chuẩn hóa bằng cùng một hàm với adapter graph, nếu không hai kho nói hai
        chuỗi khác nhau về cùng một mục.
        """
        for ten in TRUONG_TEN_NODE:
            if gia_tri.get(ten):
                return normalize_id(str(gia_tri[ten]))
        return normalize_id(id_goc)

    def _payload(self, id_goc: str, gia_tri: dict, khoa: str) -> dict:
        """Payload một điểm: đúng `meta_fields`, id gốc và khóa quyền.

        `content` bị loại tường minh kể cả khi nó lọt vào `meta_fields`: đó là
        một dòng chặn, không phải một giả định về cách upstream cấu hình.
        """
        payload = {
            ten: gia_tri[ten]
            for ten in self.meta_fields
            if ten != CONTENT_FIELD and ten in gia_tri
        }
        payload[UPSTREAM_ID_FIELD] = id_goc
        payload[FILTER_KEY_FIELD] = khoa
        return payload

    async def _embed_theo_lo(self, cac_van_ban: list[str]) -> list[list[float]]:
        """Embed theo lô `embedding_batch_num`, giữ đúng thứ tự đầu vào."""
        n = self._max_batch_size
        cac_lo = [cac_van_ban[i : i + n] for i in range(0, len(cac_van_ban), n)]
        ket_qua = await asyncio.gather(*[self.embedding_func(lo) for lo in cac_lo])
        return [[float(x) for x in vector] for lo in ket_qua for vector in lo]

    # --- Đọc ---------------------------------------------------------------

    async def query(self, query: str, top_k: int = 5) -> list[dict]:
        """Tìm kiếm vector có pre-filter theo tập khóa của ngữ cảnh hiện tại.

        Ba nhánh, không có nhánh thứ tư. Ngữ cảnh hệ thống đọc thô (ingest cần
        thấy hết). Tập khóa rỗng trả `[]` mà không chạm Qdrant - gọi với filter
        rỗng là mở toang. Còn lại là một `match_any` một field gửi kèm request.

        Che chạy sau khi Qdrant đã cắt theo `limit=top_k`, nên số kết quả thực
        dụng có thể tụt dưới `top_k` khi tầng che rỗng bớt nội dung. Ở M1 đây
        là hành vi chấp nhận: bù lại bằng cách xin dư rồi cắt sau là đổi ngữ
        nghĩa của `top_k` với upstream, việc đó cần một quyết định riêng.
        """
        context = current_context()
        ten = self._ten_collection(context)
        bo_loc = None
        if not context.bypass_filter:
            khoa_duoc_phep = context.keys_for(self.namespace)
            if not khoa_duoc_phep:
                return []
            bo_loc = models.Filter(
                must=[
                    models.FieldCondition(
                        key=FILTER_KEY_FIELD,
                        # sorted() để hai lần gọi cùng tập khóa ra cùng một
                        # request, thứ giúp so sánh request giữa các lần chạy.
                        match=models.MatchAny(any=sorted(khoa_duoc_phep)),
                    )
                ]
            )
        vector = (await self._embed_theo_lo([query]))[0]
        try:
            tra_ve = await self._client.query_points(
                collection_name=ten,
                query=vector,
                query_filter=bo_loc,
                limit=top_k,
                with_payload=True,
                score_threshold=self.cosine_better_than_threshold,
            )
        except Exception:
            # Space mới chưa ai gọi `initialize()` là ca dễ gặp ở M1, và mỗi
            # driver ném một kiểu lỗi khác nhau cho nó. Đổi thành một mã lỗi
            # ổn định, chỉ khi đúng là collection vắng mặt; lỗi khác đi tiếp
            # nguyên trạng. Kiểm ở nhánh lỗi nên đường chạy đúng không tốn
            # thêm một vòng gọi nào.
            if not await self._client.collection_exists(collection_name=ten):
                raise QdrantIndexMissing(
                    f"collection {ten!r} chưa tồn tại: space này chưa chạy"
                    " initialize(), chưa có gì để truy hồi"
                ) from None
            raise
        return [self._ban_ghi(diem, context) for diem in tra_ve.points]

    def _ban_ghi(self, diem, context) -> dict:
        """Một kết quả: hình dạng upstream, đã đi qua tầng che (AD-9).

        Khóa quyền ở lại trong bản ghi vì nó là nhãn của chính mục đó - thứ
        tầng che tra `masked_slots` theo, và thứ cho phép truy nguyên một mục
        đã ra khỏi adapter. Ngữ cảnh hệ thống đọc thô nên không che.
        """
        payload = dict(diem.payload or {})
        ban_ghi = {k: v for k, v in payload.items() if k != UPSTREAM_ID_FIELD}
        ban_ghi["id"] = payload.get(UPSTREAM_ID_FIELD, str(diem.id))
        ban_ghi["distance"] = diem.score
        if context.bypass_filter:
            return ban_ghi
        khoa = payload.get(FILTER_KEY_FIELD)
        if not khoa:
            raise PointFilterKeyMissing(
                f"point {diem.id!r} không mang {FILTER_KEY_FIELD!r} trong"
                " payload: không tra được `masked_slots` nên không che được"
            )
        # Cùng một cửa hợp đồng với hai adapter kia, không phải một nửa viết
        # lại: nhánh "không mất trường" đúng là nhánh đường vector cần nhất, vì
        # `operate.py:953` đọc thẳng `k["distance"]` của bản ghi này và một
        # khóa rụng ở đây thành `KeyError` sâu trong `vendor/`.
        return kiem_ket_qua_che(
            mask(ban_ghi, context, khoa), ban_ghi, f"point {diem.id!r}"
        )
