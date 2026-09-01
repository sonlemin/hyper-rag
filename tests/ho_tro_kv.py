"""Helper dựng và nạp kho KV, dùng chung cho các bộ test adapter KV.

Tách khỏi file test khi `tests/test_adapter_kv.py` vượt ngưỡng 1000 dòng và
phải chia đôi.

`lo_upsert` bỏ hai nhãn `scope`/`content_type` ra khỏi bản ghi vì upstream chỉ
thêm `full_doc_id` vào dict chunk (`hypergraphrag.py:296-300`): không có khe nào
nhét nhãn quyền vào, nên nó phải đi bằng phạm vi nhãn ingest.
"""

from core.permission import use_context
from tests.ngu_canh import ngu_canh_ingest

from adapters.ingest_labels import ingest_label
from adapters.kv import DUOI_TAM, JsonACLKVStorage


def dung_adapter(workspace_dir, namespace="text_chunks"):
    """Adapter đúng cách upstream dựng nó (`hypergraphrag.py:208,213`)."""
    return JsonACLKVStorage(
        namespace=namespace,
        global_config={"working_dir": str(workspace_dir)},
        embedding_func=None,
    )


def lo_upsert(muc) -> dict[str, dict]:
    """Một lô upsert đúng hình dạng upstream dựng cho `text_chunks`.

    Upstream chỉ thêm `full_doc_id` vào dict chunk (`hypergraphrag.py:296-300`):
    không có khe nào nhét `scope` với `content_type` vào, nên nhãn quyền phải
    đi đường khác - phạm vi nhãn ingest. Test dựng lại đúng hình dạng đó, bỏ
    hai nhãn ra khỏi bản ghi.
    """
    ban_ghi = {k: v for k, v in dict(muc).items() if k not in ("scope", "content_type")}
    return {muc["id"]: ban_ghi}


async def nap(adapter, khong_gian, policy, cac_muc) -> None:
    """Nạp fixture dưới ngữ cảnh hệ thống, mỗi tài liệu một phạm vi nhãn."""
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        for muc in cac_muc:
            with ingest_label(scope=muc["scope"], content_type=muc["content_type"]):
                await adapter.upsert(lo_upsert(muc))


async def kho_da_nap(workspace_dir, khong_gian, policy, namespace="text_chunks"):
    """Adapter đã nạp xong chunk fixture, ghi luôn xuống đĩa."""
    from tests.fixtures.du_lieu_dung_tay import CHUNKS

    adapter = dung_adapter(workspace_dir, namespace)
    await nap(adapter, khong_gian, policy, CHUNKS)
    await adapter.index_done_callback()
    return adapter


def con_lai_file_tam(workspace_dir) -> list[str]:
    """Tên các file tạm còn sót trong thư mục làm việc."""
    return sorted(p.name for p in workspace_dir.glob(f"*{DUOI_TAM}"))
