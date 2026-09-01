"""Helper dựng và nạp kho vector, dùng chung cho các bộ test adapter Qdrant.

Tách khỏi file test khi `tests/test_adapter_qdrant.py` vượt ngưỡng 1000 dòng và
phải chia đôi. Hai file test và bộ test chạy trên Qdrant thật đều đứng lên đúng
những hàm này, nên hình dạng lô upsert và cách nạp fixture chỉ có một bản.

`lo_upsert` dựng đúng hình dạng mà upstream ghép cho `hyperedges_vdb`
(`operate.py:461`): hai field, không có khe nào nhét `scope` với `content_type`
vào. Đó là lý do nhãn quyền phải đi đường khác, tức phạm vi nhãn ingest.
"""

from core.permission import use_context
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia
from tests.ngu_canh import ngu_canh_ingest

from adapters.ingest_labels import ingest_label
from adapters.qdrant import QdrantVectorDBStorage

CAU_HOI = "App01 trả lỗi 502 thì xử lý thế nào"


def lo_upsert(he) -> dict[str, dict]:
    """Một lô upsert đúng hình dạng upstream dựng cho `hyperedges_vdb`.

    Upstream viết cứng đúng hai field (`operate.py:461`): không có khe nào nhét
    `scope` với `content_type` vào. Test dựng lại đúng hình dạng đó để chứng
    minh nhãn quyền phải đi đường khác - phạm vi nhãn ingest.
    """
    ten = f"{he['slots']['subject']} - {he['content_type']}"
    return {f"rel-{he['id']}": {"content": ten, "hyperedge_name": ten}}


def dung_adapter(client, khong_gian, namespace="hyperedges", meta_fields=None):
    """Adapter đúng cách upstream dựng nó, cộng client đã bọc để đo."""
    return QdrantVectorDBStorage(
        namespace=namespace,
        global_config={"embedding_batch_num": 2},
        embedding_func=embedding_gia(),
        meta_fields=set({"hyperedge_name"} if meta_fields is None else meta_fields),
        qdrant_client=client,
    )


async def kho_da_nap(khong_gian, policy, namespace="hyperedges", meta_fields=None):
    """Client giả + adapter đã khởi tạo và nạp xong 4 hyperedge fixture."""
    client = QdrantGhiLai()
    adapter = dung_adapter(client, khong_gian, namespace, meta_fields)
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        await adapter.initialize()
        for he in HYPEREDGES:
            with ingest_label(scope=he["scope"], content_type=he["content_type"]):
                await adapter.upsert(lo_upsert(he))
    client.xoa_nhat_ky()
    return client, adapter


def id_trong(ket_qua) -> list[str]:
    """Id fixture (`HE-0x`) của các bản ghi trả về, bỏ tiền tố `rel-`."""
    return sorted(r["id"].removeprefix("rel-") for r in ket_qua)
