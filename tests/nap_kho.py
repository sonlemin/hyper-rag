"""Loader dùng chung: nạp fixture dựng tay vào cả ba kho (story 1.7).

Cổng M1 chạy đường truy vấn thật của upstream, nhưng **không** chạy ingest thật:
`extract_entities` cần LLM sinh fact 8 vai, việc đó thuộc story 2.4. Nên dữ
liệu vào kho bằng chính hợp đồng `upsert*` của ba adapter, dưới ngữ cảnh hệ
thống, đúng hình dạng mà `operate.py` sẽ đọc lại.

Ba luật của file này là chỗ đường e2e sống hay chết. Mỗi luật đều đã từng là
một cách "xanh mà không truy hồi được gì":

1. **Một chuỗi duy nhất cho hyperedge.** `operate.py:938-943` lấy
   `hyperedge_name` từ payload vector rồi mang thẳng chuỗi đó đi hỏi
   `get_node`. Test story 1.3 dùng `"App01 - bao_cao_su_co"` làm payload, test
   story 1.4 dùng `rel-HE-02` làm id node: hai chuỗi khác nhau thì `get_node`
   trả `None`, `edge_datas` rỗng và cả nhánh global câm. Ở đây `ten_hyperedge`
   là nguồn duy nhất cho cả hai kho. Cùng luật cho `entity_name`
   (`operate.py:747,755`).
2. **`source_id` là id chunk, không phải id hyperedge.** `operate.py:843` và
   `:1073` tách `source_id` của node rồi gọi `text_chunks.get_by_id(c_id)`.
   `source_id = "HE-02"` thì không có chunk nào tên vậy và mục Sources rỗng.
3. **Khóa quyền đi bằng phạm vi nhãn ingest**, một nhãn cho mỗi tài liệu, đúng
   như pipeline Epic 2 sẽ làm. Không có nhãn thì cả ba adapter từ chối ghi.

Hai hệ quả cố ý của bộ fixture, giữ nguyên chứ không lách:

- entity `App01` xuất hiện ở HE-01 và HE-02, cùng scope `noi_bo`, nên từ story
  2.1 khóa của nó là khóa **hạn chế nhất** trong hai nguồn
  (`noi_bo:bao_cao_su_co`, hạng cao hơn `runbook`). Trước story 2.1 đó là khóa
  của lần ghi sau, và vì HE-02 vốn nạp sau HE-01 nên giá trị cuối cùng không
  đổi - cổng M1 không phải sửa kỳ vọng nào. Cái đổi là *lý do*: nay nó không
  còn phụ thuộc thứ tự nạp;
- id node entity chính là **giá trị slot**. Mô hình hóa như vậy để tầng che có
  thứ thật để che ở đường `get_node_edges`; hệ quả là ở mức L2 tên entity ra
  nguyên văn qua kho vector `entities` (khoản nợ có địa chỉ, ghi trong ledger).

Từ story 2.1 loader mở một **đợt ingest** quanh cả lần nạp rồi chạy bước đối
chiếu hai kho ở cuối. Bộ test vì thế đi đúng đường mà pipeline Epic 2 sẽ đi, và
một lệch khóa giữa hai kho làm cả bộ test đỏ ngay ở bước nạp chứ không hiện ra
dưới dạng một kết quả truy hồi khó hiểu.
"""

from adapters.doi_chieu import doi_chieu_dot, dot_ingest, kho_cua_engine
from adapters.ingest_labels import ingest_label

# Tên nhãn vai node của adapter graph. Nhập lại từ adapter thì loader và adapter
# nói cùng một ngôn ngữ; viết cứng ở đây là bản thứ hai của cùng một hằng.
from adapters.neo4j import ROLE_ENTITY, ROLE_FIELD, ROLE_HYPEREDGE
from core.permission import use_context
from core.system_context import system_context
from core.slots import SLOT_ROLES
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, TAI_LIEU_GOC

# Kiểu entity mặc định. Upstream đọc trường này để dựng cột `type` của bảng
# Entities (`operate.py:781`); giá trị không mang nghĩa quyền nào.
KIEU_ENTITY: str = "KHAC"

# Trọng số của node hyperedge và của cạnh. `operate.py:955` và `:900` sắp xếp
# theo `weight`, nên trường này bắt buộc phải có mặt, không phải trang trí.
TRONG_SO: float = 1.0


def ten_hyperedge(he) -> str:
    """Chuỗi duy nhất định danh một hyperedge ở *cả* kho vector lẫn graph.

    Giữ đúng công thức mà test story 1.3 đã dùng cho payload `hyperedge_name`
    (`tests/test_adapter_qdrant.lo_upsert`), vì đó là chuỗi mà upstream mang đi
    hỏi `get_node`.
    """
    return f"{he['slots']['subject']} - {he['content_type']}"


def id_vector_hyperedge(he) -> str:
    """Id upstream của point hyperedge (`operate.py:478` dùng tiền tố `rel-`)."""
    return f"rel-{he['id']}"


def id_vector_entity(gia_tri: str) -> str:
    """Id upstream của point entity (`operate.py:467` dùng tiền tố `ent-`).

    Suy từ *tên entity* chứ không từ hyperedge chứa nó: cùng một entity ở hai
    hyperedge phải là một point. Upstream đạt điều đó bằng
    `compute_mdhash_id(entity_name)` (md5); ở đây là tiền tố cộng chính chuỗi
    tên, vì `core.ids.point_id` đã băm UUID5 một lần nữa ở adapter và fixture
    thì dễ đọc hơn khi id còn nhìn ra được. Thứ phải giống upstream là *tính
    một-một với tên entity*, không phải phép băm. Nhờ vậy khóa quyền của point
    và của node graph cùng chịu một luật last-write-wins, hai kho không lệch
    nhau.
    """
    return f"ent-{gia_tri}"


def kiem_fixture(cac_he=None) -> None:
    """Ba giả định mà loader đứng lên; hỏng cái nào cũng câm chứ không nổ.

    Rẻ, chạy một lần mỗi lần nạp, và mỗi dòng ứng với một cách mà bộ test sẽ
    "xanh mà không truy hồi được gì":

    - thiếu slot `subject` thì `ten_hyperedge` nổ `KeyError` - đó là ca dễ, còn
      hai ca dưới thì im lặng;
    - hai slot của cùng một hyperedge mang cùng giá trị nghĩa là hai cạnh cùng
      cặp `(hyperedge, entity)`, và `MERGE (a)-[r:SLOT]->(b)` không mang `slot`
      trong pattern (khoản nợ có địa chỉ story 2.4), nên cạnh ghi sau đè cạnh
      ghi trước và một vai biến mất khỏi graph. Tầng che khi đó "đúng" trên một
      graph đã thiếu;
    - hai hyperedge trùng `ten_hyperedge` là hai fact chung một node, nên
      `get_node_edges` trộn lân cận của cả hai và khóa quyền là của lần ghi sau.

    `cac_he` để nơi gọi kiểm một danh sách khác bộ chuẩn. Bộ hyperedge phụ
    truyền qua `them=` phải đi qua đúng guard này: đi vòng qua nó là mở lại
    đúng ba cách "xanh mà không truy hồi được gì" mà guard dựng ra để chặn.
    """
    ten_da_thay = {}
    for he in HYPEREDGES if cac_he is None else cac_he:
        slots = he["slots"]
        assert "subject" in slots, f"{he['id']} thiếu slot `subject`"
        assert set(slots) <= set(SLOT_ROLES), (
            f"{he['id']} khai vai ngoài danh mục 8 vai: {sorted(set(slots) - set(SLOT_ROLES))}"
        )
        assert len(set(slots.values())) == len(slots), (
            f"{he['id']} có hai slot cùng giá trị, cạnh ghi sau sẽ đè cạnh trước:"
            f" {sorted(slots.values())}"
        )
        ten = ten_hyperedge(he)
        assert ten not in ten_da_thay, (
            f"{he['id']} và {ten_da_thay[ten]} cùng tên hyperedge {ten!r}:"
            " hai fact sẽ dùng chung một node graph"
        )
        ten_da_thay[ten] = he["id"]


KHO_GRAPH_NK: str = "graph"
KHO_VECTOR_NK: str = "vector"


async def nap_mot_hyperedge(engine, he) -> None:
    """Một hyperedge thành node + entity + cạnh, cộng point ở hai collection.

    Thứ tự **graph trước, vector sau**, đúng thứ tự mà `operate.py:403-479` giữ.
    Đó không phải một chi tiết thẩm mỹ: node graph là kho *nhớ* được trạng thái
    "không khóa" (point vector thì bị xóa), nên đọc khóa cũ ở phía graph trước
    là đọc trên bản đầy đủ nhất. Thứ tự đó được ghim bằng test chứ không cài
    lại (`tests/test_doi_chieu.py`).
    """
    ten = ten_hyperedge(he)
    id_chunk = he["source_id"]
    graph = engine.chunk_entity_relation_graph

    await graph.upsert_node(
        ten,
        {ROLE_FIELD: ROLE_HYPEREDGE, "weight": TRONG_SO, "source_id": id_chunk},
    )
    for slot, gia_tri in he["slots"].items():
        await graph.upsert_node(
            gia_tri,
            {
                ROLE_FIELD: ROLE_ENTITY,
                "entity_type": KIEU_ENTITY,
                "description": gia_tri,
                "source_id": id_chunk,
            },
        )
        await graph.upsert_edge(
            ten,
            gia_tri,
            {"weight": TRONG_SO, "source_id": id_chunk, "slot": slot},
        )

    await engine.hyperedges_vdb.upsert(
        {id_vector_hyperedge(he): {"content": ten, "hyperedge_name": ten}}
    )
    await engine.entities_vdb.upsert(
        {
            id_vector_entity(gia_tri): {
                "content": gia_tri,
                "entity_name": gia_tri,
            }
            for gia_tri in he["slots"].values()
        }
    )


async def _nap_chunk(engine, chunk) -> None:
    """Một chunk vào kho KV và vào collection `chunks`.

    Collection `chunks` không nằm trên đường truy vấn (`chunks_vdb.query` chỉ
    có ở đường ingest), nhưng nạp nó ở đây giữ cho ba collection vector cùng
    trạng thái - và làm cho bước `khoi_tao()` có ba collection để chứng minh.
    """
    ban_ghi = {
        k: v for k, v in chunk.items() if k not in ("id", "scope", "content_type")
    }
    await engine.text_chunks.upsert({chunk["id"]: ban_ghi})
    await engine.chunks_vdb.upsert({chunk["id"]: {"content": chunk["content"]}})


async def nap_ba_kho(engine, *, khong_gian: str, policy, them=()) -> None:
    """Khởi tạo ba kho rồi nạp bộ fixture chuẩn cộng các hyperedge phụ.

    Bộ chuẩn là 4 hyperedge, 5 chunk và 5 tài liệu gốc; `them` nối vào sau
    chúng, theo đúng thứ tự truyền vào.

    Chạy trọn trong một ngữ cảnh hệ thống: đường ghi của cả ba adapter đòi
    `bypass_filter` (AD-3, cửa `ingest_key_for_write`). Mỗi tài liệu mở đúng
    một phạm vi nhãn, nên khóa quyền của mục nào cũng là khóa của tài liệu
    sinh ra nó.

    `them` là các hyperedge phụ nạp sau bộ fixture chuẩn, theo đúng thứ tự
    truyền vào: bộ test khóa đa nguồn (Đo 1 lớp (d)) dựng ca của nó bằng khe
    này thay vì bằng một loader thứ hai dễ lệch.

    Cuối đợt chạy bước đối chiếu hai kho. Nó không có cờ tắt và không tự sửa:
    lệch là `StoreKeyMismatch` kèm danh sách cặp id, ngay tại bước nạp.
    """
    kiem_fixture()
    if them:
        kiem_fixture(them)
        kiem_fixture((*HYPEREDGES, *them))
    with use_context(
        system_context(space=khong_gian, policy_version=policy.policy_version)
    ):
        await engine.khoi_tao()
        with dot_ingest() as so:
            for he in (*HYPEREDGES, *them):
                with ingest_label(scope=he["scope"], content_type=he["content_type"]):
                    await nap_mot_hyperedge(engine, he)
            for chunk in CHUNKS:
                with ingest_label(
                    scope=chunk["scope"], content_type=chunk["content_type"]
                ):
                    await _nap_chunk(engine, chunk)
            for tai_lieu in TAI_LIEU_GOC:
                with ingest_label(
                    scope=tai_lieu["scope"], content_type=tai_lieu["content_type"]
                ):
                    await engine.full_docs.upsert(
                        {tai_lieu["id"]: {"content": tai_lieu["content"]}}
                    )
            await doi_chieu_dot(so, kho=kho_cua_engine(engine))
