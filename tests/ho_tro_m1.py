"""Helper dựng engine và đo ngữ cảnh truy hồi cho cổng M1 (story 1.7).

Tách khỏi file test khi `tests/test_cong_m1.py` vượt ngưỡng 1000 dòng và phải
chia đôi: một file cho chính cổng M1 (`1.7-INT-001..007` và Đo 1 nền), một file
cho engine và cấu hình.

Ba hàm đo ở cuối file là cách bộ test đọc "vai này truy hồi được những fact
nào" mà không phải parse CSV của upstream. Tên hyperedge là chuỗi duy nhất định
danh một fact ở cả hai kho, nên nó là thứ đo được.

Từ story 2.2, `dung_engine` là nơi **duy nhất** trong suite dựng `EngineACL`,
và nó bọc hai bản giả qua wrapper của dự án: engine từ chối hàm trần
(`LLMNotWrapped`), nên mọi lời gọi LLM/embedding của cổng M1 đi qua đúng đường
mà sản phẩm đi, và sổ audit bộ nhớ (`engine.so_audit`) có sự kiện chi phí của
từng lời gọi.
"""

from adapters.engine import EngineACL
from adapters.llm_wrapper import bo_embedding, bo_llm
from core.permission import use_context
from hypergraphrag.base import QueryParam
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, THEO_ID
from tests.gia_lap_llm import (
    MODEL_EMBEDDING_GIA,
    MODEL_LLM_GIA,
    EmbeddingGia,
    NhaCungCapGia,
    SoAuditBoNho,
    danh_muc_gia,
)
from tests.gia_lap_qdrant import QdrantGhiLai, khoa_trong_filter
from tests.nap_kho import ten_hyperedge

CAU_HOI = "App01 trả lỗi 502 thì xử lý thế nào"


def llm_boc(llm, so_audit: SoAuditBoNho):
    """`LLMGia` bọc qua wrapper thật, provider giả trả token cố định."""
    return bo_llm(
        nha_cung_cap=NhaCungCapGia(llm),
        model=MODEL_LLM_GIA,
        audit=so_audit,
        danh_muc=danh_muc_gia(),
    )


def embedding_boc(so_audit: SoAuditBoNho):
    """`EmbeddingFunc` bọc qua wrapper thật, ruột là hàm hash của `embedding_gia`."""
    return bo_embedding(
        nha_cung_cap=EmbeddingGia(),
        model=MODEL_EMBEDDING_GIA,
        audit=so_audit,
        danh_muc=danh_muc_gia(),
    )


def dung_engine(workspace_dir, client, driver, llm, so_audit=None, **them) -> EngineACL:
    """Engine cổng M1: ba adapter thật, ba kết nối giả, LLM giả đã bọc.

    Sổ audit gắn lên engine dưới tên `so_audit` - thuộc tính thường, không phải
    field, nên `asdict(self)` không chạm tới nó.
    """
    so_audit = SoAuditBoNho() if so_audit is None else so_audit
    engine = EngineACL(
        working_dir=str(workspace_dir),
        embedding_func=embedding_boc(so_audit),
        llm_model_func=llm_boc(llm, so_audit),
        embedding_batch_num=2,
        tao_qdrant_client=(lambda: client) if client is not None else None,
        tao_neo4j_driver=(lambda: driver) if driver is not None else None,
        **them,
    )
    engine.so_audit = so_audit
    return engine


async def cong_m1(workspace_dir, khong_gian, policy):
    """Engine đã khởi tạo và nạp xong fixture, nhật ký đã xóa sạch."""
    from tests.gia_lap_llm import LLMGia
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.nap_kho import nap_ba_kho

    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    llm = LLMGia()
    engine = dung_engine(workspace_dir, client, driver, llm)
    await nap_ba_kho(engine, khong_gian=khong_gian, policy=policy)
    client.xoa_nhat_ky()
    driver.xoa_nhat_ky()
    llm.xoa_nhat_ky()
    engine.so_audit.xoa()
    return engine, client, driver, llm


async def hoi(engine, ngu_canh, cau_hoi: str = CAU_HOI) -> str:
    """Một truy vấn dừng ở ngữ cảnh truy hồi, dưới một ngữ cảnh quyền."""
    with use_context(ngu_canh):
        return await engine.aquery(cau_hoi, QueryParam(only_need_context=True))


def ten_hyperedge_trong(ngu_canh_truy_hoi: str) -> set[str]:
    """Tên các hyperedge xuất hiện trong chuỗi ngữ cảnh.

    Tên hyperedge là chuỗi duy nhất định danh một fact ở cả hai kho, nên nó là
    thứ đo được "vai này truy hồi được những fact nào" mà không phải parse CSV
    của upstream.
    """
    return {
        ten_hyperedge(he) for he in HYPEREDGES if ten_hyperedge(he) in ngu_canh_truy_hoi
    }


def chunk_trong(ngu_canh_truy_hoi: str) -> set[str]:
    """Id các chunk mà nguyên văn nội dung của chúng lọt vào ngữ cảnh."""
    return {c["id"] for c in CHUNKS if c["content"] in ngu_canh_truy_hoi}


def ten_hyperedge_ky_vong(bang, vai: str) -> set[str]:
    """Tập tên hyperedge mà oracle nói vai này còn thấy (từ L1 trở lên)."""
    return {
        ten_hyperedge(THEO_ID[id_he])
        for id_he in oracle.hyperedge_thay_duoc(bang, vai, HYPEREDGES)
    }


def khoa_theo_collection(client: QdrantGhiLai) -> dict[str, set[str]]:
    """Tập khóa của filter trong mỗi search request đã phát, theo collection."""
    theo_collection: dict[str, set[str]] = {}
    for goi in client.cac_loi_goi("query_points"):
        ten = goi.kwargs["collection_name"]
        theo_collection[ten] = khoa_trong_filter(goi.kwargs["query_filter"])
    return theo_collection
