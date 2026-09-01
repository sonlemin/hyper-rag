"""Hai bộ giả lập cho bộ test adapter Qdrant (story 1.3).

Đặt ở `tests/` chứ không ở `tests/fixtures/`: luật import-lint cấm thư mục
fixture gọi vào `core/` và `vendor/`, còn hai thứ ở đây phải nói đúng ngôn ngữ
của adapter (`EmbeddingFunc` của upstream, client của qdrant-client). Fixture
giữ vai trò đối chứng độc lập; file này là đồ nghề đo đạc.

Hai thứ trong file:

`QdrantGhiLai` bọc `AsyncQdrantClient(":memory:")`. Local mode lọc `match_any`
đúng ngữ nghĩa nên đủ để kiểm hành vi pre-filter, nhưng nó bỏ qua payload index
và `get_collection().payload_schema` luôn rỗng ở đó. Nếu adapter tự nới lỏng
cho local mode thì cửa đó thành đường rò, nên phần thiếu được bù ở đây: lớp bọc
tổng hợp `payload_schema` từ chính các lời gọi `create_payload_index` mà adapter
đã phát ra. Nhờ vậy adapter giữ đúng một nhánh kiểm index, và cả hai nhánh
(có index / chưa có index) đều có test chạy vào.

Lớp bọc cũng ghi lại mọi lời gọi. Đó là lớp assert chính của story: local mode
duyệt vét cạn, không có HNSW thật, nên "kết quả đúng" chưa chứng minh được bộ
lọc đã đi cùng truy vấn. Đối tượng filter trong search request mới chứng minh
được.

`embedding_gia` trả vector suy từ hash chuỗi: cố định giữa các lần chạy, không
cần mạng, không cần key LLM.
"""

import hashlib
import warnings
from dataclasses import dataclass, field
from typing import Any

from hypergraphrag.utils import EmbeddingFunc
from qdrant_client import AsyncQdrantClient, models

# Số chiều nhỏ nhất còn đủ để hai chuỗi khác nhau ra hai vector khác nhau.
SO_CHIEU: int = 8


@dataclass
class LoiGoi:
    """Một lời gọi client đã ghi lại: tên, tham số, và phản hồi thật của nó.

    Giữ cả `phan_hoi` để test so được "adapter trả ra" với "Qdrant đưa cho
    adapter" của **chính lần gọi đó**. Chạy lại truy vấn để so là so với một
    lần gọi khác, không chứng minh được adapter không bớt bản ghi nào.
    """

    ten: str
    args: tuple
    kwargs: dict
    phan_hoi: Any = None

    def collection(self) -> str | None:
        """Tên collection của lời gọi, dù truyền kiểu từ khóa hay vị trí."""
        if "collection_name" in self.kwargs:
            return self.kwargs["collection_name"]
        return self.args[0] if self.args else None


@dataclass
class QdrantGhiLai:
    """Client Qdrant có ghi nhật ký, cộng sổ payload index riêng.

    Mặc định bọc local mode. `noi_toi()` bọc một server thật: khi đó sổ index
    giả bị tắt, vì server thật tự nuôi `payload_schema` và ghi đè nó bằng sổ
    giả là biến bộ test thành bộ test của chính lớp bọc này.
    """

    loi_goi: list[LoiGoi] = field(default_factory=list)
    # collection -> field -> schema đã tạo. Sổ này thay cho `payload_schema`
    # của server thật, thứ mà local mode không nuôi.
    _so_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    _that: AsyncQdrantClient = field(default_factory=lambda: AsyncQdrantClient(":memory:"))
    # Bù `payload_schema` hay không: local mode cần, server thật thì không.
    bu_payload_schema: bool = True

    @classmethod
    def noi_toi(cls, url: str, api_key: str | None = None) -> "QdrantGhiLai":
        """Bọc một Qdrant thật, giữ nguyên nhật ký lời gọi để assert trên request."""
        return cls(
            _that=AsyncQdrantClient(
                url=url, api_key=api_key, check_compatibility=False
            ),
            bu_payload_schema=False,
        )

    def __getattr__(self, ten: str):
        """Chuyển tiếp mọi method công khai sang client thật, ghi lại trên đường đi.

        Tên bắt đầu bằng gạch dưới không chuyển tiếp: `self._that` chưa kịp gán
        mà rơi vào đây thì thành đệ quy vô hạn, và adapter cũng không có việc gì
        với tên riêng tư của client.
        """
        if ten.startswith("_"):
            raise AttributeError(ten)
        that = getattr(self._that, ten)
        if not callable(that):
            return that

        async def boc(*args, **kwargs):
            loi_goi = LoiGoi(ten=ten, args=args, kwargs=kwargs)
            self.loi_goi.append(loi_goi)
            if ten == "create_payload_index" and self.bu_payload_schema:
                with warnings.catch_warnings():
                    # Local mode cảnh báo "payload index không có tác dụng" ở
                    # mỗi lần tạo index. Đúng, và đó chính là lý do lớp bọc này
                    # tồn tại. Chỉ nuốt đúng cảnh báo này, ở đúng method này:
                    # nuốt hết mọi cảnh báo của qdrant-client là tự bịt mắt.
                    warnings.filterwarnings(
                        "ignore",
                        message=".*[Pp]ayload indexes have no effect.*",
                        category=UserWarning,
                    )
                    ket_qua = await that(*args, **kwargs)
                self._ghi_so_index(loi_goi)
            else:
                ket_qua = await that(*args, **kwargs)
            if ten == "get_collection" and self.bu_payload_schema:
                ket_qua.payload_schema = dict(
                    self._so_index.get(loi_goi.collection(), {})
                )
            loi_goi.phan_hoi = ket_qua
            return ket_qua

        return boc

    def _ghi_so_index(self, loi_goi: LoiGoi) -> None:
        """Ghi vào sổ đúng hình dạng `payload_schema` của server thật.

        Server trả `PayloadIndexInfo(data_type, params, points)`, không trả lại
        nguyên đối tượng `field_schema` đã gửi. Sổ giả phải nói cùng một ngôn
        ngữ, nếu không adapter sẽ được kiểm trên một hình dạng mà production
        không bao giờ gặp.
        """
        schema = loi_goi.kwargs.get("field_schema")
        tham_so = schema if isinstance(schema, models.KeywordIndexParams) else None
        kieu = models.PayloadSchemaType.KEYWORD
        if tham_so is None and isinstance(schema, models.PayloadSchemaType):
            kieu = schema
        self._so_index.setdefault(loi_goi.collection(), {})[
            loi_goi.kwargs["field_name"]
        ] = models.PayloadIndexInfo(data_type=kieu, params=tham_so, points=0)

    async def dat_index_tho(self, collection: str, field_name: str, mo_ta) -> None:
        """Đặt thẳng một mô tả index vào sổ, dựng ca index sai kiểu."""
        self._so_index.setdefault(collection, {})[field_name] = mo_ta

    # --- Tra cứu cho phần assert ------------------------------------------

    def cac_loi_goi(self, ten: str) -> list[LoiGoi]:
        """Mọi lời gọi tới một method, theo thứ tự đã phát."""
        return [lg for lg in self.loi_goi if lg.ten == ten]

    def loi_goi_cuoi(self, ten: str) -> LoiGoi:
        """Lời gọi gần nhất tới một method; chưa có lần nào là lỗi test."""
        cac = self.cac_loi_goi(ten)
        assert cac, f"chưa có lời gọi {ten!r} nào"
        return cac[-1]

    def xoa_nhat_ky(self) -> None:
        """Bắt đầu một đoạn đo mới mà giữ nguyên dữ liệu đã nạp."""
        self.loi_goi.clear()

    async def bo_index(self, collection: str, field_name: str) -> None:
        """Xóa một field khỏi sổ index, dựng lại ca "collection có, index vắng"."""
        self._so_index.get(collection, {}).pop(field_name, None)

    async def dem_point(self, collection: str) -> int:
        """Số point thật đang nằm trong collection, không qua nhật ký."""
        return (await self._that.count(collection_name=collection)).count


def vector_tu_chuoi(van_ban: str) -> list[float]:
    """Vector cố định suy từ sha256 của chuỗi.

    Thành phần đầu luôn là 1.0 và các thành phần còn lại không âm, nên cosine
    giữa hai vector bất kỳ luôn ≥ 1/√SO_CHIEU ≈ 0.354. Nhờ vậy ngưỡng
    `cosine_better_than_threshold` mặc định (0.2) không bao giờ là thứ quyết
    định kết quả test: khác biệt giữa hai vai phải sinh từ bộ lọc quyền, đúng
    thứ story này cần chứng minh.
    """
    bam = hashlib.sha256(van_ban.encode("utf-8")).digest()
    return [1.0] + [bam[i] / 255.0 for i in range(SO_CHIEU - 1)]


def embedding_gia(so_chieu: int = SO_CHIEU) -> EmbeddingFunc:
    """`EmbeddingFunc` của upstream, ruột là hàm hash - không mạng, không key."""

    async def func(cac_van_ban: list[str]) -> list[list[float]]:
        return [vector_tu_chuoi(t) for t in cac_van_ban]

    return EmbeddingFunc(embedding_dim=so_chieu, max_token_size=512, func=func)


def khoa_trong_filter(bo_loc: models.Filter | None) -> set[str]:
    """Tập khóa nằm trong một filter `match_any` một điều kiện.

    Cố ý khắt khe: filter phải đúng một điều kiện `must`, đúng một field, đúng
    kiểu `MatchAny`. Filter hai điều kiện là điểm mù recall của HNSW có lọc
    (research qdrant-filterable-hnsw), nên hình dạng sai phải làm test đỏ chứ
    không phải chỉ làm tập khóa lệch.
    """
    assert isinstance(bo_loc, models.Filter), f"không phải Filter: {bo_loc!r}"
    assert not bo_loc.should and not bo_loc.must_not, "chỉ được dùng nhánh must"
    assert isinstance(bo_loc.must, list) and len(bo_loc.must) == 1, (
        f"phải đúng một điều kiện, đang có: {bo_loc.must!r}"
    )
    dieu_kien = bo_loc.must[0]
    assert isinstance(dieu_kien, models.FieldCondition), f"{dieu_kien!r}"
    assert isinstance(dieu_kien.match, models.MatchAny), f"{dieu_kien.match!r}"
    return set(dieu_kien.match.any)


def field_trong_filter(bo_loc: models.Filter) -> str:
    """Tên field mà filter đang lọc trên."""
    return bo_loc.must[0].key
