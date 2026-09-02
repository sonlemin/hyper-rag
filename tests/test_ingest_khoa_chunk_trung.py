"""Đặc tả hiện trạng: lối vào `ainsert` né được luật hợp nhất ở đường KV.

Không phải khẳng định hành vi đúng, mà là **mốc so sánh** - cùng kiểu mà story
1.3 và 1.5 đã dùng cho hai chiều last-write-wins/first-write-wins, và cùng lý
do: story sau phải thấy rõ mình đang đổi cái gì.

Lỗ nằm ở `vendor/hypergraphrag/hypergraphrag.py:309-313`. `ainsert` gọi
`text_chunks.filter_keys(...)` rồi **loại các id đã tồn tại** khỏi
`inserting_chunks` trước khi gọi `chunks_vdb.upsert` (`:320`) và
`text_chunks.upsert` (`:336`). Adapter KV chạy phép đó dưới cờ system, nên
`_ton_tai` trả `True` cho mọi id đã có - và đúng những chunk trùng id mà luật
hợp nhất sinh ra để xử lý thì không bao giờ tới được `upsert`. Bản ghi giữ nhãn
*rộng* của lần nạp đầu, và vai chạm scope đó vẫn đọc được nó. `full_docs` dính
cùng phép lọc (`:284-285`).

**Phạm vi chính xác của lỗ**: đường KV (`text_chunks`, `full_docs`) và
collection vector `chunks`. Đường graph và hai collection `entities`/
`hyperedges` **không** dính, vì `extract_entities` gọi thẳng `upsert_node` và
`upsert` mà không qua `filter_keys` - test dưới đây ghim cả ranh giới đó, nếu
không thì một lần đọc vội biến "lỗ ở đường chunk" thành "luật hợp nhất không
chạy".

Không sửa `vendor/`. Quyết định đường ingest của dự án có đi qua `filter_keys`
hay không thuộc story 2.3 (pipeline ingest tuần tự), và ledger giữ địa chỉ đó.
"""

import asyncio

import pytest

from adapters.ingest_labels import ingest_label
from core.keys import filter_key
from core.permission import use_context
from core.system_context import system_context
from tests.gia_lap_llm import LLMGia
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.gia_lap_qdrant import QdrantGhiLai
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


async def _nap_hai_tai_lieu(workspace_dir, khong_gian, policy):
    """Nạp hai tài liệu chia nhau đúng một chunk, dưới hai nhãn khác scope."""
    client = QdrantGhiLai()
    engine = dung_engine(
        workspace_dir,
        client,
        Neo4jGhiLai(),
        LLMGia(),
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


def test_dac_ta_hien_trang_ainsert_khong_siet_khoa_chunk_trung(
    workspace_dir, khong_gian, policy
):
    """Chunk trùng id giữa hai tài liệu khác scope **không** bị siết khóa.

    Hành vi đúng theo FR-11 là chunk ấy thành "không khóa" (hai scope chạm cùng
    một id). Hiện trạng: nó giữ nhãn `noi_bo:runbook` của lần nạp đầu, vì
    `filter_keys` đã loại nó khỏi lô trước khi `upsert` nhìn thấy.

    Hệ quả nhìn thấy được ở dòng cuối: `tech_support` - vai **không** chạm
    scope `khach_hang_a` - vẫn đọc được nguyên văn một đoạn văn bản mà lần nạp
    thứ hai xếp vào scope đó.
    """
    id_chung = _id_chunk(DOAN_CHUNG)

    async def chay():
        engine, _ = await _nap_hai_tai_lieu(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            khoa = await engine.text_chunks.khoa_hien_co([id_chung])
        with use_context(vai(policy, "tech_support", khong_gian)):
            doc_duoc = await engine.text_chunks.get_by_id(id_chung)
        return khoa[id_chung], doc_duoc

    khoa, doc_duoc = asyncio.run(chay())
    assert khoa == RONG, "hiện trạng cần ghim: nhãn rộng của lần nạp đầu thắng"
    assert khoa != HEP
    assert khoa is not None, (
        "hành vi *đúng* của FR-11 là không khóa; ngày nào dòng này đỏ là ngày"
        " lỗ đã được đóng, và test đặc tả này phải bị thay bằng test hành vi"
    )
    assert doc_duoc is not None, (
        "vai không chạm scope khach_hang_a vẫn đọc được đoạn văn bản mà lần nạp"
        " thứ hai xếp vào scope đó - đó là hình dạng của lỗ"
    )


def test_pham_vi_lo_dung_la_duong_kv_khong_phai_duong_graph(
    workspace_dir, khong_gian, policy
):
    """Ranh giới của lỗ: `filter_keys` chặn đường chunk, không chặn đường graph.

    `extract_entities` gọi `upsert_node`/`upsert` thẳng, không qua
    `filter_keys`, nên luật hợp nhất *có* chạy ở đó. Ghim ranh giới này để một
    lần đọc vội không biến "lỗ ở đường chunk" thành "luật hợp nhất không chạy",
    và để story 2.3 biết đúng phạm vi phải sửa.
    """

    async def chay():
        engine, _ = await _nap_hai_tai_lieu(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            # Mọi node do `extract_entities` sinh ra trong đợt hai đều mang
            # khóa của tài liệu thứ hai, hoặc khóa hợp nhất nếu trùng id với
            # đợt một. Không node nào giữ nhãn rộng vì bị `filter_keys` loại.
            graph = engine.chunk_entity_relation_graph
            tu_khoa = await graph.khoa_hien_co(["APP01"])
        return tu_khoa["APP01"]

    khoa = asyncio.run(chay())
    # `APP01` là từ khóa cố định mà LLM giả trả về, nên nó là entity duy nhất
    # được trích trong *cả hai* đợt - tức đúng ca đa nguồn khác scope, và
    # đường graph xử lý nó đúng luật: không khóa.
    assert khoa is None, (
        "đường graph phải hợp nhất bình thường; nếu nó cũng giữ nhãn rộng thì"
        " phạm vi lỗ rộng hơn thứ ledger đang ghi"
    )
