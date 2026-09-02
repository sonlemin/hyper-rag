"""Chunk trùng id giữa hai tài liệu khác scope qua lối vào `ainsert` (story 2.1 -> 2.3).

Story 2.1 ghim đây là *đặc tả hiện trạng* của một lỗ: `ainsert`
(`vendor/hypergraphrag/hypergraphrag.py:309-313`) gọi `text_chunks.filter_keys`
rồi loại id đã có khỏi lô trước khi `upsert` nhìn thấy, nên chunk trùng id
giữa hai tài liệu khác quyền giữ nhãn rộng của lần nạp đầu và không bao giờ
tới cửa hợp nhất. Story 2.3 đóng lỗ ở adapter KV: dưới nhãn ingest,
`filter_keys` coi id đã có mà khóa sẽ đổi sau hợp nhất là "chưa có", nên
`ainsert` đưa nó qua `upsert` và khóa được hợp nhất ở cả KV lẫn collection
`chunks`. File này vì thế đổi từ đặc tả hiện trạng thành test hành vi.

Không sửa `vendor/`. Ranh giới cũ (đường graph không dính lỗ) giữ nguyên làm
đối chứng.
"""

import asyncio

import pytest

from adapters.ingest_labels import ingest_label
from core.keys import filter_key
from core.permission import use_context
from core.system_context import system_context
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.gia_lap_qdrant import QdrantGhiLai
from tests.ho_tro_ingest import llm_theo_fact
from tests.ho_tro_m1 import dung_engine
from tests.ngu_canh import ngu_canh_ingest, vai

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

# Bộ đếm token của bộ test là byte UTF-8 (`MaHoaOffline`), nên "40 token" là 40
# byte. Văn bản thuần ASCII để một lần cắt không rơi vào giữa một ký tự nhiều
# byte - `decode(errors="ignore")` của bộ đếm sẽ nuốt mất ký tự đó và hai chunk
# lẽ ra trùng nhau lại khác nhau một ký tự.
CO_CHUNK: int = 40
DOAN_CHUNG: str = "A" * CO_CHUNK
DOC_MOT: str = DOAN_CHUNG + "B" * CO_CHUNK
DOC_HAI: str = DOAN_CHUNG + "C" * CO_CHUNK

RONG = filter_key("noi_bo", "runbook")
HEP = filter_key("khach_hang_a", "bao_cao_su_co")

# Story 2.4: LLM giả trả JSON fact 8 vai cho từng chunk. `App01` có mặt ở cả
# hai tài liệu nên nó là entity đa nguồn khác scope của test thứ hai.
ENTITY_CHUNG = "App01"
BANG_FACT = {
    DOAN_CHUNG: [{"subject": ENTITY_CHUNG, "condition": "doan chung"}],
    "B" * CO_CHUNK: [{"subject": ENTITY_CHUNG, "remediation": "doan b"}],
    "C" * CO_CHUNK: [{"subject": ENTITY_CHUNG, "remediation": "doan c"}],
}


async def _nap_hai_tai_lieu(workspace_dir, khong_gian, policy):
    """Nạp hai tài liệu chia nhau đúng một chunk, dưới hai nhãn khác scope."""
    client = QdrantGhiLai()
    engine = dung_engine(
        workspace_dir,
        client,
        Neo4jGhiLai(),
        llm_theo_fact(BANG_FACT),
        # Cắt nhỏ để hai tài liệu chia nhau *đúng* chunk đầu: id chunk của
        # upstream là md5 nội dung chunk, nên hai chunk trùng nội dung là một id.
        chunk_token_size=CO_CHUNK,
        chunk_overlap_token_size=0,
    )
    with use_context(
        system_context(space=khong_gian, policy_version=policy.policy_version)
    ):
        await engine.khoi_tao()
        with ingest_label(scope="noi_bo", content_type="runbook"):
            await engine.ainsert(DOC_MOT)
        with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
            await engine.ainsert(DOC_HAI)
    return engine, client


def _id_chunk(noi_dung: str) -> str:
    from hypergraphrag.utils import compute_mdhash_id

    return compute_mdhash_id(noi_dung, prefix="chunk-")


def test_chunk_trung_hai_scope_thanh_khong_khoa_o_kv_va_chunks(
    workspace_dir, khong_gian, policy
):
    """Hàng "Chunk trùng hai scope": chunk chung ra `KHONG_KHOA` ở KV và `chunks`.

    Hành vi đúng theo FR-11: hai scope chạm cùng một id thì id đó không khóa.
    Hệ quả nhìn thấy được: `tech_support` - vai không chạm scope `khach_hang_a`
    - không đọc được nguyên văn đoạn văn bản mà lần nạp thứ hai xếp vào scope
    đó (trước 2.3 thì đọc được, đó là hình dạng của lỗ).
    """
    id_chung = _id_chunk(DOAN_CHUNG)

    async def chay():
        engine, client = await _nap_hai_tai_lieu(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            khoa_kv = await engine.text_chunks.khoa_hien_co([id_chung])
            khoa_vec = await engine.chunks_vdb.khoa_hien_co([id_chung])
        with use_context(vai(policy, "tech_support", khong_gian)):
            doc_duoc = await engine.text_chunks.get_by_id(id_chung)
        diem, _ = await client._that.scroll(
            collection_name=f"{khong_gian}_chunks", limit=10, with_payload=True
        )
        return khoa_kv[id_chung], khoa_vec[id_chung], doc_duoc, diem

    khoa_kv, khoa_vec, doc_duoc, diem = asyncio.run(chay())
    assert khoa_kv is None, "KV: chunk chung hai scope phải không khóa"
    assert khoa_vec is None, "collection chunks: cùng luật, id vào sổ không khóa"
    assert doc_duoc is None, "vai không chạm scope khach_hang_a không được đọc chunk chung"
    # Point của chunk chung vắng mặt tuyệt đối; hai chunk riêng vẫn còn.
    id_point = {d.payload.get("upstream_id") for d in diem}
    assert id_chung not in id_point and len(id_point) == 2


def test_pham_vi_lo_dung_la_duong_kv_khong_phai_duong_graph(
    workspace_dir, khong_gian, policy
):
    """Ranh giới của lỗ: `filter_keys` chặn đường chunk, không chặn đường graph.

    Bộ trích xuất (`adapters/trich_xuat.py`) gọi `upsert_node`/`upsert` thẳng,
    không qua `filter_keys`, nên luật hợp nhất *có* chạy ở đó. Ghim ranh giới
    này để một lần đọc vội không biến "lỗ ở đường chunk" thành "luật hợp nhất
    không chạy", và để story 2.3 biết đúng phạm vi phải sửa.
    """

    async def chay():
        engine, _ = await _nap_hai_tai_lieu(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            # Mọi node do bộ trích xuất sinh ra trong đợt hai đều mang khóa của
            # tài liệu thứ hai, hoặc khóa hợp nhất nếu trùng id với đợt một.
            # Không node nào giữ nhãn rộng vì bị `filter_keys` loại.
            graph = engine.chunk_entity_relation_graph
            tu_khoa = await graph.khoa_hien_co([ENTITY_CHUNG])
        return tu_khoa[ENTITY_CHUNG]

    khoa = asyncio.run(chay())
    # `App01` là `subject` của mọi fact mà LLM giả trả về, nên nó là entity
    # được trích trong *cả hai* đợt - tức đúng ca đa nguồn khác scope, và
    # đường graph xử lý nó đúng luật: không khóa.
    assert khoa is None, (
        "đường graph phải hợp nhất bình thường; nếu nó cũng giữ nhãn rộng thì"
        " phạm vi lỗ rộng hơn thứ ledger đang ghi"
    )


def test_filter_keys_id_da_co_khoa_khong_doi_van_la_da_co(workspace_dir, khong_gian, policy):
    """Nhánh còn lại của `filter_keys` dưới nhãn ingest: cùng nhãn thì khóa không đổi, id báo "đã có".

    Đối chứng tay: bỏ phép so `!= khoa_cu` trong `filter_keys` là tập trả về
    có `c1` và test đỏ.
    """
    from tests.ho_tro_kv import dung_adapter

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert({"c1": {"content": "x"}})
                cung_nhan = await adapter.filter_keys(["c1", "c2"])
            with ingest_label(scope="noi_bo", content_type="bi_mat_ha_tang"):
                nhan_nhay_hon = await adapter.filter_keys(["c1", "c2"])
            with ingest_label(scope="noi_bo", content_type="runbook"):
                # Hạng thấp hơn khóa đang có thì hợp nhất giữ khóa cũ: vẫn "đã có".
                pass
        return cung_nhan, nhan_nhay_hon

    cung_nhan, nhan_nhay_hon = asyncio.run(chay())
    assert cung_nhan == {"c2"}
    assert nhan_nhay_hon == {"c1", "c2"}
