"""Adapter Qdrant: pre-filter thật tại tầng vector (story 1.3, FR-07, chốt 2).

Sáu kịch bản `1.3-INT-001..006` của test-design cộng mọi hàng I/O Matrix của
spec. Hai lớp assert, theo thứ tự quan trọng:

1. Đối tượng filter trong search request đã ghi lại. Local mode duyệt vét cạn
   nên "kết quả đúng" chưa chứng minh được bộ lọc đi cùng truy vấn; lớp này
   mới chứng minh. Cùng cặp assert này chạy lại trên Qdrant thật ở cổng M1.
2. Nội dung kết quả, đối chiếu với `tests/fixtures/oracle.py` - bộ tính kỳ vọng
   độc lập, không gọi `core/`.

Không mạng, không container, không key LLM: client là local mode, embedding là
hàm hash cố định.
"""

import asyncio
from types import SimpleNamespace

import pytest
from qdrant_client import models

from adapters.ingest_labels import IngestLabelMissing, current_ingest_key, ingest_label
from adapters.policy_loader import load_policy
from adapters.qdrant import (
    FILTER_MAX_CONDITIONS,
    UPSTREAM_ID_FIELD,
    MaskContractViolated,
    PointFilterKeyMissing,
    QdrantIndexMissing,
    QdrantVectorDBStorage,
)
from core.ids import point_id
from core.keys import FILTER_KEY_FIELD, filter_key
from core.permission import PermissionContextMissing, use_context, user_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.gia_lap_qdrant import (
    QdrantGhiLai,
    embedding_gia,
    field_trong_filter,
    khoa_trong_filter,
    vector_tu_chuoi,
)

CAU_HOI = "App01 trả lỗi 502 thì xử lý thế nào"


@pytest.fixture()
def bang():
    """Bảng chính sách đọc thô, đầu vào của oracle."""
    return oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def policy():
    """Bảng chính sách đã nạp qua loader, đầu vào của factory ngữ cảnh."""
    return load_policy(oracle.POLICY_TOI_GIAN)


@pytest.fixture()
def khong_gian(session_prefix):
    """Không gian dữ liệu của một phiên test (E1-DATA-01, AD-12)."""
    return f"{session_prefix}_synth"


def vai(policy, ten_vai: str, khong_gian: str):
    """Ngữ cảnh quyền của một vai; đây là thứ adapter đọc lúc query."""
    return user_context(
        policy=policy, role=ten_vai, space=khong_gian, real_account=f"{ten_vai}01"
    )


def ngu_canh_ingest(khong_gian: str, policy):
    """Ngữ cảnh hệ thống của pipeline nạp; adapter chỉ lấy `space` từ đây."""
    return system_context(space=khong_gian, policy_version=policy.policy_version)


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
        meta_fields=set(
            {"hyperedge_name"} if meta_fields is None else meta_fields
        ),
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


# --- 1.3-INT-001: upsert từ chối khi payload index chưa có ------------------


def test_upsert_tu_choi_khi_chua_co_payload_index(khong_gian, policy):
    """Collection có mà index khóa vắng thì cả lô bị từ chối, không ghi point nào.

    AD-4: extra HNSW edge chỉ dựng cho field đã có index lúc build. Ghi trước
    rồi tạo index sau là có một vùng dữ liệu vĩnh viễn nằm ngoài đường lọc
    nhanh, nên upsert phải từ chối chứ không tự chữa.
    """

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            ten_collection = f"{khong_gian}_hyperedges"
            await client.bo_index(ten_collection, FILTER_KEY_FIELD)
            client.xoa_nhat_ky()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(QdrantIndexMissing) as loi:
                    await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert loi.value.code == "QDRANT_INDEX_MISSING"
        assert client.cac_loi_goi("upsert") == []
        assert await client.dem_point(ten_collection) == 0

    asyncio.run(chay())


def test_upsert_tu_choi_khi_chua_co_collection(khong_gian, policy):
    """Chưa khởi tạo lần nào cũng là "chưa có index", cùng một lỗi."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(QdrantIndexMissing):
                    await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert client.cac_loi_goi("upsert") == []

    asyncio.run(chay())


def test_khoi_tao_tao_collection_va_index_trong_cung_mot_buoc(khong_gian, policy):
    """Index khóa là keyword + `is_tenant`, tạo cùng lúc với collection (AD-4)."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
        tao_index = client.loi_goi_cuoi("create_payload_index")
        assert tao_index.collection() == f"{khong_gian}_hyperedges"
        assert tao_index.kwargs["field_name"] == FILTER_KEY_FIELD
        schema = tao_index.kwargs["field_schema"]
        assert isinstance(schema, models.KeywordIndexParams)
        assert schema.is_tenant is True
        # Cùng một bước: không có lời gọi ghi dữ liệu nào chen vào giữa.
        assert [lg.ten for lg in client.loi_goi if lg.ten.startswith("create")] == [
            "create_collection",
            "create_payload_index",
        ]

    asyncio.run(chay())


# --- 1.3-INT-002: filter match_any một field đi cùng search request ---------


def test_query_gui_match_any_dung_tap_khoa_cua_vai(khong_gian, policy, bang):
    """Vai chỉ được một phần khóa: filter mang đúng tập khóa, kết quả theo đó.

    Lớp assert chính là đối tượng filter trong search request; lớp thứ hai là
    nội dung kết quả, đối chiếu oracle.
    """

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            ket_qua = await adapter.query(CAU_HOI, top_k=10)

        goi = client.loi_goi_cuoi("query_points")
        bo_loc = goi.kwargs["query_filter"]
        assert field_trong_filter(bo_loc) == FILTER_KEY_FIELD
        assert khoa_trong_filter(bo_loc) == oracle.allowed_keys_ky_vong(
            bang, "tech_support"
        )["hyperedges"]
        assert goi.kwargs["limit"] == 10

        assert id_trong(ket_qua) == sorted(
            oracle.hyperedge_thay_duoc(bang, "tech_support", HYPEREDGES)
        )
        assert all(
            r[FILTER_KEY_FIELD] in khoa_trong_filter(bo_loc) for r in ket_qua
        )

    asyncio.run(chay())


def test_query_giu_nguyen_hop_dong_voi_upstream(khong_gian, policy):
    """Mỗi bản ghi có `distance`, `id` gốc và đủ `meta_fields` (operate.py:953)."""

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            ket_qua = await adapter.query(CAU_HOI, top_k=10)
        assert ket_qua
        for r in ket_qua:
            assert isinstance(r["distance"], float)
            assert r["id"].startswith("rel-HE-")
            assert r["hyperedge_name"]
            assert "content" not in r
        # Sắp xếp giảm dần theo điểm, như upstream vẫn nhận từ NanoVectorDB.
        diem = [r["distance"] for r in ket_qua]
        assert diem == sorted(diem, reverse=True)
        # `cosine_better_than_threshold` của upstream phải đi cùng request,
        # nếu không NanoVectorDB và Qdrant cắt kết quả theo hai luật khác nhau.
        goi = client.loi_goi_cuoi("query_points")
        assert goi.kwargs["score_threshold"] == adapter.cosine_better_than_threshold
        assert adapter.cosine_better_than_threshold == 0.2

    asyncio.run(chay())


# --- 1.3-INT-003: tập khóa theo namespace (NFR-06) -------------------------


@pytest.mark.parametrize("ten_vai", ["devops", "tech_support"])
def test_namespace_dung_tap_khoa_cua_muc(khong_gian, policy, bang, ten_vai):
    """`chunks`/`entities` dùng tập L2, `hyperedges` dùng tập từ L1 trở lên.

    Ba adapter dùng chung một client: khác biệt phải sinh từ `keys_for(namespace)`
    chứ không từ ba đường code khác nhau.
    """

    async def chay():
        client = QdrantGhiLai()
        theo_ns = {}
        for namespace, meta in (
            ("hyperedges", {"hyperedge_name"}),
            ("entities", {"entity_name"}),
            ("chunks", set()),
        ):
            adapter = dung_adapter(client, khong_gian, namespace, meta)
            with use_context(ngu_canh_ingest(khong_gian, policy)):
                await adapter.initialize()
            with use_context(vai(policy, ten_vai, khong_gian)):
                await adapter.query(CAU_HOI, top_k=5)
            theo_ns[namespace] = khoa_trong_filter(
                client.loi_goi_cuoi("query_points").kwargs["query_filter"]
            )

        ky_vong = oracle.allowed_keys_ky_vong(bang, ten_vai)
        for namespace, khoa in theo_ns.items():
            assert khoa == ky_vong[namespace], namespace
        assert theo_ns["chunks"] == theo_ns["entities"]
        assert theo_ns["chunks"] <= theo_ns["hyperedges"]

    asyncio.run(chay())


# --- 1.3-INT-004: tập khóa rỗng ------------------------------------------


def test_tap_khoa_rong_tra_rong_va_khong_goi_qdrant(khong_gian, tmp_path):
    """Vai không thấy gì: trả `[]`, không lỗi, và tuyệt đối không bỏ filter.

    Đường "gọi Qdrant với filter rỗng" là đường mở toang, nên nhánh đúng là
    không gọi. Assert trên nhật ký client, không chỉ trên kết quả rỗng.
    """
    bang_mu = tmp_path / "policy-mu.yaml"
    bang_mu.write_text(
        "version: 1\n"
        "roles:\n"
        "  khach:\n"
        "    scopes: [noi_bo]\n"
        "    disclosure:\n"
        "      runbook: L0\n"
        "      bao_cao_su_co: L0\n",
        encoding="utf-8",
    )
    policy_mu = load_policy(bang_mu)

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy_mu)):
            await adapter.initialize()
        client.xoa_nhat_ky()
        with use_context(vai(policy_mu, "khach", khong_gian)):
            assert await adapter.query(CAU_HOI, top_k=10) == []
        assert client.loi_goi == []

    asyncio.run(chay())


# --- 1.3-INT-005: hai vai, hai kết quả ------------------------------------


def test_hai_vai_hai_tap_khoa_hai_ket_qua(khong_gian, policy, bang):
    """Cùng một câu hỏi, hai vai: khác biệt sinh từ filter, không từ lọc lại (R3).

    Chứng minh "không lọc lại phía Python" bằng cách đối chiếu hai chiều: tập
    khóa trong hai search request khác nhau, và số bản ghi Qdrant trả về đúng
    bằng số bản ghi adapter trả ra ở cả hai lần.
    """

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        thu = {}
        for ten_vai in ("devops", "tech_support"):
            client.xoa_nhat_ky()
            with use_context(vai(policy, ten_vai, khong_gian)):
                thu[ten_vai] = await adapter.query(CAU_HOI, top_k=10)
            goi = client.loi_goi_cuoi("query_points")
            assert khoa_trong_filter(goi.kwargs["query_filter"]) == oracle.allowed_keys_ky_vong(
                bang, ten_vai
            )["hyperedges"]

        assert id_trong(thu["devops"]) == sorted(
            oracle.hyperedge_thay_duoc(bang, "devops", HYPEREDGES)
        )
        assert id_trong(thu["tech_support"]) == sorted(
            oracle.hyperedge_thay_duoc(bang, "tech_support", HYPEREDGES)
        )
        assert id_trong(thu["devops"]) != id_trong(thu["tech_support"])
        # Vai hẹp hơn thấy tập con thật sự, không phải một danh sách khác.
        assert set(id_trong(thu["tech_support"])) < set(id_trong(thu["devops"]))

    asyncio.run(chay())


def test_khong_loc_lai_phia_python(khong_gian, policy):
    """Adapter trả đúng những bản ghi Qdrant đưa cho nó, không bớt bản nào.

    So với phản hồi thật của *chính* lần gọi đó (`LoiGoi.phan_hoi`), không phải
    với một lần chạy lại: chạy lại là một lời gọi khác, nó chứng minh Qdrant
    xác định chứ không chứng minh adapter trung thực.
    """

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            ket_qua = await adapter.query(CAU_HOI, top_k=10)
        # Kho có nhiều hơn phần vai này được thấy, nếu không phép so là rỗng nghĩa.
        assert await client.dem_point(f"{khong_gian}_hyperedges") == len(HYPEREDGES)
        phan_hoi = client.loi_goi_cuoi("query_points").phan_hoi
        assert len(phan_hoi.points) < len(HYPEREDGES)
        assert [r["distance"] for r in ket_qua] == [p.score for p in phan_hoi.points]
        assert id_trong(ket_qua) == sorted(
            p.payload[UPSTREAM_ID_FIELD].removeprefix("rel-")
            for p in phan_hoi.points
        )

    asyncio.run(chay())


# --- 1.3-INT-006: kết quả đi qua hàm che trước khi rời adapter -------------


def test_ket_qua_di_qua_ham_che(khong_gian, policy, monkeypatch):
    """Mỗi bản ghi qua `mask(kết quả, context, khóa hyperedge)` (AD-9).

    Story 1.6 thay ruột hàm che mà không phải mở lại adapter, nên thứ phải ghim
    ở đây là điểm gọi và ba tham số, không phải hành vi che.
    """
    from adapters import qdrant as mo_dun

    da_goi = []

    def mask_gia(ket_qua, context, hyperedge_key):
        da_goi.append((ket_qua, context, hyperedge_key))
        return {**ket_qua, "da_che": True}

    monkeypatch.setattr(mo_dun, "mask", mask_gia)

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        ctx = vai(policy, "tech_support", khong_gian)
        with use_context(ctx):
            ket_qua = await adapter.query(CAU_HOI, top_k=10)
        assert ket_qua and all(r["da_che"] for r in ket_qua)
        assert len(da_goi) == len(ket_qua)
        for ban_ghi, context, khoa in da_goi:
            assert context is ctx
            assert khoa == ban_ghi[FILTER_KEY_FIELD]
            assert khoa in ctx.keys_for("hyperedges")

    asyncio.run(chay())


# --- Fail-closed: thiếu ngữ cảnh quyền (NFR-10) ---------------------------


def test_query_thieu_ngu_canh_thi_raise(khong_gian, policy):
    """Không có nhánh nào chạy không filter khi chưa ai set ngữ cảnh."""

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with pytest.raises(PermissionContextMissing):
            await adapter.query(CAU_HOI, top_k=10)
        assert client.cac_loi_goi("query_points") == []

    asyncio.run(chay())


def test_upsert_thieu_ngu_canh_thi_raise(khong_gian, policy):
    """Kể cả khi phạm vi nhãn ingest đang mở, thiếu ngữ cảnh vẫn là lỗi."""

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with ingest_label(scope="noi_bo", content_type="runbook"):
            with pytest.raises(PermissionContextMissing):
                await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert client.cac_loi_goi("upsert") == []

    asyncio.run(chay())


# --- Ngữ cảnh hệ thống: đọc thô ------------------------------------------


def test_ngu_canh_he_thong_doc_tho_khong_filter_khong_che(
    khong_gian, policy, monkeypatch
):
    """Cờ bỏ-filter: không filter, không che, và không hỏi `allowed_keys`."""
    from adapters import qdrant as mo_dun

    monkeypatch.setattr(
        mo_dun, "mask", lambda *a, **kw: pytest.fail("ngữ cảnh hệ thống không che")
    )

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            ket_qua = await adapter.query(CAU_HOI, top_k=10)
        assert client.loi_goi_cuoi("query_points").kwargs["query_filter"] is None
        assert id_trong(ket_qua) == sorted(he["id"] for he in HYPEREDGES)

    asyncio.run(chay())


# --- Phạm vi nhãn ingest --------------------------------------------------


def test_upsert_ngoai_pham_vi_nhan_tu_choi_ca_lo(khong_gian, policy):
    """Không có nhãn mặc định: chưa mở nhãn là từ chối, không ghi point nào.

    Một point không khóa hoặc vô hình vĩnh viễn, hoặc lọt vào mọi vai. Cả hai
    đều tệ hơn một lỗi nhìn thấy được.
    """

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            client.xoa_nhat_ky()
            with pytest.raises(IngestLabelMissing) as loi:
                await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert loi.value.code == "INGEST_LABEL_MISSING"
        assert client.cac_loi_goi("upsert") == []
        assert await client.dem_point(f"{khong_gian}_hyperedges") == 0

    asyncio.run(chay())


def test_upsert_trong_pham_vi_nhan_moi_point_mang_khoa(khong_gian, policy):
    """Payload đúng ba phần: `meta_fields`, id gốc, khóa quyền. Không có `content`."""

    async def chay():
        client, _ = await kho_da_nap(khong_gian, policy)
        diem, _cursor = await client.scroll(
            collection_name=f"{khong_gian}_hyperedges", limit=100, with_payload=True
        )
        assert len(diem) == len(HYPEREDGES)
        theo_id = {p.payload[UPSTREAM_ID_FIELD]: p for p in diem}
        for he in HYPEREDGES:
            p = theo_id[f"rel-{he['id']}"]
            assert p.payload[FILTER_KEY_FIELD] == filter_key(
                he["scope"], he["content_type"]
            )
            assert set(p.payload) == {
                "hyperedge_name",
                UPSTREAM_ID_FIELD,
                FILTER_KEY_FIELD,
            }
            assert str(p.id) == point_id(f"rel-{he['id']}")

    asyncio.run(chay())


def test_moi_point_cua_mot_lo_mang_cung_mot_khoa(khong_gian, policy):
    """Một phạm vi nhãn là một tài liệu: cả lô mang đúng một khóa.

    Nhãn đang mở là nguồn sự thật duy nhất của khóa quyền, và adapter không
    đọc `scope` từ dữ liệu vì upstream không có chỗ nào để nhét nó vào. Trách
    nhiệm không trộn nhiều scope trong một lô thuộc về phía gọi (pipeline
    ingest, story 2.3): trộn thì cả lô nhận nhãn đang mở, và đó là gán sai
    quyền chứ không phải hành vi đúng để test đóng đinh. Lô ở đây vì thế chỉ
    gồm các bản ghi cùng scope `noi_bo`.
    """
    cung_scope = [he for he in HYPEREDGES if he["scope"] == "noi_bo"]

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            lo = {}
            for he in cung_scope:
                lo.update(lo_upsert(he))
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo)
        diem, _ = await client.scroll(
            collection_name=f"{khong_gian}_hyperedges", limit=100, with_payload=True
        )
        assert len(diem) == len(cung_scope) > 1
        assert {p.payload[FILTER_KEY_FIELD] for p in diem} == {"noi_bo:runbook"}

    asyncio.run(chay())


def test_nhan_long_nhau_thi_nhan_trong_cung_thang():
    """Mở nhãn thứ hai trong nhãn thứ nhất: trong cùng thắng, thoát ra trả lại."""
    with pytest.raises(IngestLabelMissing):
        current_ingest_key()
    with ingest_label(scope="noi_bo", content_type="runbook"):
        assert current_ingest_key() == "noi_bo:runbook"
        with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
            assert current_ingest_key() == "khach_hang_a:bao_cao_su_co"
        assert current_ingest_key() == "noi_bo:runbook"
    with pytest.raises(IngestLabelMissing):
        current_ingest_key()


def test_nhan_hong_bi_tu_choi_ngay_tai_cua():
    """Khóa lệch một dấu cách là mục vĩnh viễn không ai lọc trúng, nên nổ sớm."""
    with pytest.raises(ValueError):
        with ingest_label(scope="noi_bo:lach", content_type="runbook"):
            pass
    with pytest.raises(ValueError):
        with ingest_label(scope="  ", content_type="runbook"):
            pass
    with pytest.raises(IngestLabelMissing):
        current_ingest_key()


# --- Ngoại vi hợp đồng ----------------------------------------------------


def test_ten_collection_theo_khong_gian_cua_ngu_canh(khong_gian, policy):
    """Tên collection là `{space}_{namespace}`, `space` lấy từ ngữ cảnh (AD-12)."""

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            await adapter.query(CAU_HOI, top_k=3)
        assert (
            client.loi_goi_cuoi("query_points").collection()
            == f"{khong_gian}_hyperedges"
        )

    asyncio.run(chay())


def test_lo_rong_khong_cham_kho(khong_gian, policy):
    """Lô rỗng không ghi gì và không cần gì, đúng như upstream."""

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            assert await adapter.upsert({}) == []
        assert client.loi_goi == []

    asyncio.run(chay())


def test_upsert_embed_theo_lo_cua_global_config(khong_gian, policy):
    """Embedding chạy theo lô `embedding_batch_num`, giữ hợp đồng upstream."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        so_lan = []
        goc = adapter.embedding_func.func

        async def dem(cac_van_ban):
            so_lan.append(len(cac_van_ban))
            return await goc(cac_van_ban)

        adapter.embedding_func.func = dem
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            lo = {}
            for he in HYPEREDGES:
                lo.update(lo_upsert(he))
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo)
        assert so_lan == [2, 2]

    asyncio.run(chay())


# --- Cách ly hai không gian dữ liệu (AD-12) -------------------------------


def test_hai_space_khong_doc_du_lieu_cua_nhau(khong_gian, policy, session_prefix):
    """Cùng một instance adapter, hai `space`: mỗi bên chỉ thấy collection của mình.

    Tên collection phải tính lại theo từng lời gọi. Ghim nó sau lần gọi đầu là
    một request của space B đọc dữ liệu của space A - rò rỉ xuyên khách hàng,
    không phải một lỗi hiệu năng.
    """
    space_b = f"{session_prefix}_synth_b"

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        # Space B tồn tại nhưng chưa có dữ liệu: khác biệt duy nhất giữa hai
        # lần query là `space` của ngữ cảnh.
        with use_context(ngu_canh_ingest(space_b, policy)):
            await adapter.initialize()
        client.xoa_nhat_ky()

        with use_context(vai(policy, "devops", khong_gian)):
            ket_qua_a = await adapter.query(CAU_HOI, top_k=10)
        assert (
            client.loi_goi_cuoi("query_points").collection()
            == f"{khong_gian}_hyperedges"
        )
        assert ket_qua_a

        with use_context(vai(policy, "devops", space_b)):
            ket_qua_b = await adapter.query(CAU_HOI, top_k=10)
        assert client.loi_goi_cuoi("query_points").collection() == f"{space_b}_hyperedges"
        assert ket_qua_b == []

    asyncio.run(chay())


def test_upsert_ghi_vao_collection_cua_space_dang_mo(khong_gian, policy, session_prefix):
    """Đường ghi cũng tính lại tên collection theo ngữ cảnh, không ghim."""
    space_b = f"{session_prefix}_synth_b"

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(space_b, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert await client.dem_point(f"{space_b}_hyperedges") == 1
        assert await client.dem_point(f"{khong_gian}_hyperedges") == len(HYPEREDGES)

    asyncio.run(chay())


# --- Nhãn ingest an toàn giữa các task async ------------------------------


def test_hai_tai_lieu_nap_song_song_khong_lan_nhan(khong_gian, policy):
    """Hai tài liệu nạp đồng thời mang đúng nhãn của mình.

    Cùng khuôn với `tests/test_ngu_canh_quyen.py::test_hai_task_async_khong_lan_context`.
    Nhãn phải là contextvar chứ không phải một chồng toàn cục: chồng toàn cục
    thì task nạp sau ghi đè nhãn của task nạp trước, và khóa quyền sai đi thẳng
    vào dữ liệu bền vững - hỏng im lặng, chỉ lộ ra khi có người đọc được thứ
    không thuộc về họ.
    """
    tai_lieu = [HYPEREDGES[0], HYPEREDGES[3]]
    assert tai_lieu[0]["scope"] != tai_lieu[1]["scope"]

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)

        async def nap(he, nhip):
            with ingest_label(scope=he["scope"], content_type=he["content_type"]):
                # Nhường quyền chạy giữa lúc mở nhãn và lúc ghi: đây đúng là
                # khe mà một chồng toàn cục sẽ lẫn.
                for _ in range(nhip):
                    await asyncio.sleep(0)
                await adapter.upsert(lo_upsert(he))

        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            await asyncio.gather(nap(tai_lieu[0], 3), nap(tai_lieu[1], 1))

        diem, _ = await client.scroll(
            collection_name=f"{khong_gian}_hyperedges", limit=100, with_payload=True
        )
        theo_id = {p.payload[UPSTREAM_ID_FIELD]: p.payload for p in diem}
        assert len(theo_id) == 2
        for he in tai_lieu:
            assert theo_id[f"rel-{he['id']}"][FILTER_KEY_FIELD] == filter_key(
                he["scope"], he["content_type"]
            )

    asyncio.run(chay())


# --- Payload không bao giờ mang nội dung ----------------------------------


def test_content_bi_chan_ke_ca_khi_nam_trong_meta_fields(khong_gian, policy):
    """`content` không vào payload dù ai đó khai nó trong `meta_fields`.

    Kho vector không được thành bản sao thứ hai của nội dung chưa che. Đây là
    một dòng chặn tường minh, không phải giả định về cách upstream cấu hình,
    nên nó phải có test chạy vào.
    """

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(
            client, khong_gian, meta_fields={"hyperedge_name", "content"}
        )
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        diem, _ = await client.scroll(
            collection_name=f"{khong_gian}_hyperedges", limit=10, with_payload=True
        )
        assert len(diem) == 1
        assert set(diem[0].payload) == {
            "hyperedge_name",
            UPSTREAM_ID_FIELD,
            FILTER_KEY_FIELD,
        }

    asyncio.run(chay())


# --- Ngưỡng cosine đọc từ global_config ----------------------------------


def test_nguong_cosine_lay_tu_global_config(khong_gian, policy):
    """Đổi `cosine_better_than_threshold` là đổi giá trị trong search request."""

    async def chay():
        client = QdrantGhiLai()
        adapter = QdrantVectorDBStorage(
            namespace="hyperedges",
            global_config={"embedding_batch_num": 2, "cosine_better_than_threshold": 0.75},
            embedding_func=embedding_gia(),
            meta_fields={"hyperedge_name"},
            qdrant_client=client,
        )
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
        with use_context(vai(policy, "devops", khong_gian)):
            await adapter.query(CAU_HOI, top_k=5)
        assert adapter.cosine_better_than_threshold == 0.75
        assert client.loi_goi_cuoi("query_points").kwargs["score_threshold"] == 0.75

    asyncio.run(chay())


# --- Mã lỗi ổn định (Consistency Conventions) -----------------------------


def test_ma_loi_on_dinh():
    """Test assert trên `code`, nên `code` là hợp đồng: đổi nó là đỏ ở đây."""
    assert QdrantIndexMissing.code == "QDRANT_INDEX_MISSING"
    assert IngestLabelMissing.code == "INGEST_LABEL_MISSING"
    assert PointFilterKeyMissing.code == "POINT_FILTER_KEY_MISSING"
    assert MaskContractViolated.code == "MASK_CONTRACT_VIOLATED"


# --- Cửa index kiểm cả kiểu, không chỉ sự có mặt -------------------------


@pytest.mark.parametrize(
    "mo_ta, vi_sao",
    [
        (
            models.PayloadIndexInfo(
                data_type=models.PayloadSchemaType.TEXT, params=None, points=0
            ),
            "index text tách từ nên match_any trượt",
        ),
        (
            models.PayloadIndexInfo(
                data_type=models.PayloadSchemaType.KEYWORD, params=None, points=0
            ),
            "keyword trần: is_tenant mặc định là false",
        ),
        (
            models.PayloadIndexInfo(
                data_type=models.PayloadSchemaType.KEYWORD,
                params=models.KeywordIndexParams(
                    type=models.KeywordIndexType.KEYWORD, is_tenant=False
                ),
                points=0,
            ),
            "keyword nhưng tắt is_tenant",
        ),
    ],
    ids=["text", "keyword_tran", "khong_tenant"],
)
def test_upsert_tu_choi_khi_index_sai_kieu(khong_gian, policy, mo_ta, vi_sao):
    """Index "có" mà sai kiểu là đúng ca cửa này dựng ra để chặn."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        ten_collection = f"{khong_gian}_hyperedges"
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            await client.dat_index_tho(ten_collection, FILTER_KEY_FIELD, mo_ta)
            client.xoa_nhat_ky()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(QdrantIndexMissing) as loi:
                    await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert loi.value.code == "QDRANT_INDEX_MISSING", vi_sao
        assert client.cac_loi_goi("upsert") == []
        assert await client.dem_point(ten_collection) == 0

    asyncio.run(chay())


# --- Point về mà thiếu khóa quyền: nổ, không che bằng khóa rỗng ----------


def test_point_thieu_khoa_quyen_thi_raise(khong_gian, policy):
    """Không có mặc định fail-open trong đường trả về.

    Gọi thẳng `_ban_ghi` vì đường end-to-end không tới được nhánh này: filter
    `match_any` không bao giờ khớp một point thiếu chính field đang lọc. Đó là
    lớp phòng vệ chiều sâu cho ca có ai đó ghi vào collection không qua adapter,
    và một lớp phòng vệ chưa từng chạy là một lớp chưa biết có chạy được không.
    """
    client = QdrantGhiLai()
    adapter = dung_adapter(client, khong_gian)
    ctx = vai(policy, "devops", khong_gian)
    diem = SimpleNamespace(
        id="00000000-0000-5000-8000-000000000000",
        payload={"hyperedge_name": "App01", UPSTREAM_ID_FIELD: "rel-HE-01"},
        score=0.9,
    )
    with pytest.raises(PointFilterKeyMissing) as loi:
        adapter._ban_ghi(diem, ctx)
    assert loi.value.code == "POINT_FILTER_KEY_MISSING"


# --- Cấu hình hỏng thì hỏng sớm ------------------------------------------


@pytest.mark.parametrize("gia_tri", [0, -1, "khong-phai-so"])
def test_kich_thuoc_lo_hong_thi_no_ngay_luc_dung_adapter(khong_gian, gia_tri):
    """`range(0, n, 0)` nổ giữa đường ghi là lỗi khó đọc; chặn ở cửa cấu hình."""
    with pytest.raises(ValueError):
        QdrantVectorDBStorage(
            namespace="hyperedges",
            global_config={"embedding_batch_num": gia_tri},
            embedding_func=embedding_gia(),
            meta_fields={"hyperedge_name"},
            qdrant_client=QdrantGhiLai(),
        )


def test_thieu_ca_client_lan_url_thi_no_ngay():
    """Không có gì để nối tới thì phải nói ra, không im lặng dựng client rỗng."""
    with pytest.raises(ValueError, match="qdrant_url"):
        QdrantVectorDBStorage(
            namespace="hyperedges",
            global_config={},
            embedding_func=embedding_gia(),
            meta_fields=set(),
        )


def test_dung_client_tu_url_trong_global_config():
    """Không tiêm client thì dựng từ `qdrant_url`; không chạm mạng lúc dựng."""

    async def chay():
        adapter = QdrantVectorDBStorage(
            namespace="hyperedges",
            global_config={"qdrant_url": "http://127.0.0.1:6399"},
            embedding_func=embedding_gia(),
            meta_fields=set(),
        )
        from qdrant_client import AsyncQdrantClient

        assert isinstance(adapter._client, AsyncQdrantClient)
        await adapter._client.close()

    asyncio.run(chay())


# --- Embedding không ghép 1-1 --------------------------------------------


def test_embedding_khong_ghep_1_1_thi_tu_choi_ca_lo(khong_gian, policy):
    """Thiếu vector cho một mục là ghi lệch khóa cho mọi mục sau nó."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)

        async def thieu_mot(cac_van_ban):
            return [vector_tu_chuoi(t) for t in cac_van_ban][:-1] or []

        adapter.embedding_func.func = thieu_mot
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            client.xoa_nhat_ky()
            lo = {}
            for he in HYPEREDGES[:2]:
                lo.update(lo_upsert(he))
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(RuntimeError):
                    await adapter.upsert(lo)
        assert client.cac_loi_goi("upsert") == []
        assert await client.dem_point(f"{khong_gian}_hyperedges") == 0

    asyncio.run(chay())


# --- initialize() lặp lại được -------------------------------------------


def test_initialize_goi_lai_khong_hong_gi(khong_gian, policy):
    """Khởi động lại tiến trình gọi lại `initialize()`; nó phải im lặng đi qua."""

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        client.xoa_nhat_ky()
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
        # Collection đã có thì không tạo lại (tạo lại là xóa sạch dữ liệu),
        # còn index thì tạo lại được và không hỏng gì.
        assert client.cac_loi_goi("create_collection") == []
        assert len(client.cac_loi_goi("create_payload_index")) == 1
        assert await client.dem_point(f"{khong_gian}_hyperedges") == len(HYPEREDGES)
        with use_context(vai(policy, "devops", khong_gian)):
            assert await adapter.query(CAU_HOI, top_k=10)

    asyncio.run(chay())


# --- Query trên space chưa khởi tạo --------------------------------------


def test_query_tren_collection_chua_ton_tai_cho_ma_loi_on_dinh(
    khong_gian, policy, session_prefix
):
    """Space mới chưa ai gọi `initialize()` là ca dễ gặp ở M1, phải có mã lỗi."""

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        client.xoa_nhat_ky()
        with use_context(vai(policy, "devops", f"{session_prefix}_chua_co")):
            with pytest.raises(QdrantIndexMissing) as loi:
                await adapter.query(CAU_HOI, top_k=5)
        assert loi.value.code == "QDRANT_INDEX_MISSING"
        # Lỗi khác của Qdrant không bị nuốt thành mã này: cửa chỉ đổi lỗi khi
        # đúng là collection vắng mặt, và nó kiểm điều đó ở nhánh lỗi.
        assert client.cac_loi_goi("collection_exists")

    asyncio.run(chay())


# --- Cấu hình collection: cạnh HNSW theo tenant và hàng rào phía server ---


def test_collection_dung_voi_canh_hnsw_theo_khoa(khong_gian, policy):
    """`payload_m` là thứ biến "có index" thành pre-filter chạy trong HNSW.

    Không đặt nó thì cả AD-4 lẫn `QdrantIndexMissing` đang canh một cơ chế chưa
    được bật. `m` giữ khác 0 có chủ đích: hướng dẫn tenant của Qdrant khuyên
    `m=0` khi mọi truy vấn đều có filter tenant, nhưng ngữ cảnh hệ thống của
    mình đọc thô không filter, nên tắt index toàn cục là biến đường ingest
    thành full scan.
    """

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
        hnsw = client.loi_goi_cuoi("create_collection").kwargs["hnsw_config"]
        assert hnsw.payload_m and hnsw.payload_m > 0
        assert hnsw.m != 0

    asyncio.run(chay())


def test_collection_bat_strict_mode_lam_hang_rao_phia_server(khong_gian, policy):
    """Filter một điều kiện là luật của NFR-06, và server phải tự giữ được nó.

    Quy ước trong code cộng helper assert trong test chỉ chặn được đường code
    hiện tại. Nới `filter_max_conditions` là một quyết định phải viết ra (Epic 5
    break-glass), không phải thứ một adapter tương lai lách qua im lặng.
    """

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
        strict = client.loi_goi_cuoi("create_collection").kwargs["strict_mode_config"]
        assert strict.enabled is True
        assert strict.filter_max_conditions == FILTER_MAX_CONDITIONS == 1
        assert strict.unindexed_filtering_retrieve is False
        assert strict.unindexed_filtering_update is False

    asyncio.run(chay())


# --- Hợp đồng của tầng che, ghim trước khi story 1.6 thay ruột -----------


def test_ket_qua_khong_bao_gio_chua_phan_tu_rong(khong_gian, policy):
    """Upstream đọc thẳng `r["hyperedge_name"]`, nên list không được có lỗ."""

    async def chay():
        _client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            ket_qua = await adapter.query(CAU_HOI, top_k=10)
        assert ket_qua
        for r in ket_qua:
            assert r and isinstance(r, dict)
            assert r["hyperedge_name"] and r["id"]

    asyncio.run(chay())


def test_che_tra_gia_tri_rong_thi_no_tai_cho(khong_gian, policy, monkeypatch):
    """Muốn giấu hẳn một mục thì `query` phải lọc nó ra, không trả `None` vào list.

    Ghim hợp đồng trước khi story 1.6 viết ruột thật: không có cửa này thì lỗi
    nổ tận `operate.py:944` ở `r["hyperedge_name"]`, cách chỗ gây ra vài tầng.
    """
    from adapters import qdrant as mo_dun

    monkeypatch.setattr(mo_dun, "mask", lambda ket_qua, context, khoa: None)

    async def chay():
        _client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            with pytest.raises(MaskContractViolated) as loi:
                await adapter.query(CAU_HOI, top_k=10)
        assert loi.value.code == "MASK_CONTRACT_VIOLATED"

    asyncio.run(chay())


# --- Tải lên chia lô ------------------------------------------------------


def test_upsert_chia_lo_phia_tai_len(khong_gian, policy):
    """Phần đẩy point lên chia theo cùng `embedding_batch_num` với embedding."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)  # embedding_batch_num = 2
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            client.xoa_nhat_ky()
            lo = {}
            for he in HYPEREDGES:
                lo.update(lo_upsert(he))
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo)
        cac_lo = client.cac_loi_goi("upsert")
        assert len(cac_lo) == 2
        assert [len(lg.kwargs["points"]) for lg in cac_lo] == [2, 2]
        assert all(lg.kwargs["wait"] is True for lg in cac_lo)
        assert await client.dem_point(f"{khong_gian}_hyperedges") == len(HYPEREDGES)

    asyncio.run(chay())


def test_ba_cua_kiem_xong_truoc_khi_ghi_lo_dau_tien(khong_gian, policy):
    """Chia lô không được làm hỏng ngữ nghĩa "từ chối cả lô"."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            await client.bo_index(f"{khong_gian}_hyperedges", FILTER_KEY_FIELD)
            lo = {}
            for he in HYPEREDGES:
                lo.update(lo_upsert(he))
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(QdrantIndexMissing):
                    await adapter.upsert(lo)
        assert client.cac_loi_goi("upsert") == []
        assert await client.dem_point(f"{khong_gian}_hyperedges") == 0

    asyncio.run(chay())


# --- Đặc tả hiện trạng: khóa đa nguồn là last-write-wins (nợ story 2.1) --


def test_dac_ta_hien_trang_khoa_da_nguon_last_write_wins(khong_gian, policy):
    """Cùng một id upstream nạp từ hai tài liệu khác scope: khóa của lần ghi sau thắng.

    Đây là test **đặc tả hiện trạng**, không phải test khẳng định hành vi đúng.
    `point_id` là UUID5 của id upstream, nên một entity xuất hiện ở hai tài liệu
    khác scope chỉ còn một point và mang nhãn của tài liệu nạp sau. Story 2.1
    ("hợp nhất khóa đa nguồn") sẽ đổi hành vi này; mốc so sánh nằm ở đây, để lúc
    đó thấy rõ mình đang đổi cái gì.
    """
    chung = HYPEREDGES[0]

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            for scope, loai in (("noi_bo", "runbook"), ("khach_hang_a", "bao_cao_su_co")):
                with ingest_label(scope=scope, content_type=loai):
                    await adapter.upsert(lo_upsert(chung))
        diem, _ = await client.scroll(
            collection_name=f"{khong_gian}_hyperedges", limit=10, with_payload=True
        )
        assert len(diem) == 1, "cùng id upstream thì cùng point id, không nhân bản"
        assert diem[0].payload[FILTER_KEY_FIELD] == "khach_hang_a:bao_cao_su_co"

    asyncio.run(chay())
