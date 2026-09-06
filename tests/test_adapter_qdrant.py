"""Adapter Qdrant: pre-filter thật tại tầng vector (story 1.3, FR-07, chốt 2).

Sáu kịch bản `1.3-INT-001..006` của test-design cộng các hàng I/O Matrix nói về
đường truy vấn, phạm vi nhãn ingest và cách ly không gian dữ liệu. Hai lớp
assert, theo thứ tự quan trọng:

1. Đối tượng filter trong search request đã ghi lại. Local mode duyệt vét cạn
   nên "kết quả đúng" chưa chứng minh được bộ lọc đi cùng truy vấn; lớp này
   mới chứng minh. Cùng cặp assert này chạy lại trên Qdrant thật ở cổng M1.
2. Nội dung kết quả, đối chiếu với `tests/fixtures/oracle.py` - bộ tính kỳ vọng
   độc lập, không gọi `core/`.

Phần cấu hình collection, hợp đồng của tầng che, chia lô và vòng đời kết nối
nằm ở `tests/test_adapter_qdrant_kho.py`.

Không mạng, không container, không key LLM: client là local mode, embedding là
hàm hash cố định.
"""

import asyncio

import pytest
from qdrant_client import models

from adapters.ingest_labels import (
    IngestLabelMissing,
    current_ingest_key,
    ingest_label,
)
from adapters.policy_loader import load_policy
from adapters.qdrant import UPSTREAM_ID_FIELD, QdrantIndexMissing
from core.ids import point_id
from core.keys import FILTER_KEY_FIELD, filter_key
from core.permission import PermissionContextMissing, use_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.gia_lap_qdrant import (
    QdrantGhiLai,
    field_trong_filter,
    khoa_trong_filter,
)
from tests.ho_tro_qdrant import CAU_HOI, dung_adapter, id_trong, kho_da_nap, lo_upsert
from tests.ngu_canh import ngu_canh_ingest, vai


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
    # Bảng hạng nhỏ tiêm thẳng vào loader: validator đơn điệu của AD-5 đòi bảng
    # chính sách khai đủ mọi loại **có hạng**, nên một bảng hai dòng phải đi kèm
    # một bảng hạng hai dòng. Hệ chạy thật chỉ có một bảng hạng, là file đóng
    # băng của repo.
    policy_mu = load_policy(bang_mu, hang={"runbook": 10, "bao_cao_su_co": 20})

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




# --- Ledger 2.2: collection đã có phải cùng số chiều với embedding cấu hình --


def test_initialize_tu_choi_collection_da_co_khac_so_chieu(khong_gian, policy):
    """Đổi model embedding trên kho đã nạp là `EMBEDDING_DIM_MISMATCH` ngay lúc `initialize()`.

    Không có cửa này thì lỗi chỉ nổ ở lượt upsert đầu, dưới dạng lỗi kích
    thước của Qdrant nói về vector chứ không nói về model.
    """
    from adapters.qdrant import EmbeddingDimMismatch, QdrantVectorDBStorage
    from core.permission import use_context
    from core.system_context import system_context
    from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia

    client = QdrantGhiLai()

    def adapter(so_chieu):
        return QdrantVectorDBStorage(
            namespace="hyperedges",
            global_config={"embedding_batch_num": 2},
            embedding_func=embedding_gia(so_chieu),
            meta_fields={"hyperedge_name"},
            qdrant_client=client,
        )

    async def chay():
        with use_context(system_context(space=khong_gian, policy_version=policy.policy_version)):
            ten = await adapter(8).initialize()
            # Cùng số chiều thì gọi lại vẫn lặp lại được như trước.
            await adapter(8).initialize()
            with pytest.raises(EmbeddingDimMismatch) as loi:
                await adapter(16).initialize()
        return ten, loi.value

    ten, loi = asyncio.run(chay())
    assert loi.code == "EMBEDDING_DIM_MISMATCH"
    assert ten in str(loi) and "8" in str(loi) and "16" in str(loi)
    # Kho giữ nguyên: không có lời tạo lại hay xóa collection nào.
    assert len(client.cac_loi_goi("create_collection")) == 1
    assert client.cac_loi_goi("delete_collection") == []
