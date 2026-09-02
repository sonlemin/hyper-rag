"""Adapter Qdrant: cửa ghi, cấu hình kho và hợp đồng tầng che (story 1.3).

Nửa thứ hai của bộ test story 1.3; nửa đầu (`1.3-INT-001..006`, phạm vi nhãn
ingest, cách ly không gian) nằm ở `tests/test_adapter_qdrant.py`. Tách ra khi
file gốc vượt ngưỡng 1000 dòng.

Phần này ghim những thứ quyết định lúc *dựng* và lúc *ghi* chứ không lúc đọc:
nhãn ingest an toàn giữa các task async, payload không bao giờ mang nội dung,
cửa kiểm kiểu index, cấu hình collection (cạnh HNSW theo khóa và hàng rào
strict mode), hợp đồng hai nửa của tầng che, chia lô, và luật sở hữu kết nối.

Không mạng, không container, không key LLM: client là local mode, embedding là
hàm hash cố định.
"""

import asyncio
from types import SimpleNamespace

import pytest
from qdrant_client import models

from adapters.ingest_labels import (
    IngestLabelMissing,
    IngestOutsideSystemContext,
    ingest_label,
)
from adapters.qdrant import (
    FILTER_MAX_CONDITIONS,
    UPSTREAM_ID_FIELD,
    MaskContractViolated,
    PointFilterKeyMissing,
    PointIdCollision,
    QdrantIndexMissing,
    QdrantVectorDBStorage,
)
from core.ids import point_id
from core.keys import (
    CHUA_GHI,
    FILTER_KEY_FIELD,
    SensitivityRankUnknown,
    filter_key,
)
from core.permission import use_context
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia, vector_tu_chuoi
from tests.ho_tro_qdrant import CAU_HOI, dung_adapter, kho_da_nap, lo_upsert
from tests.ngu_canh import ngu_canh_ingest, vai


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

    Nửa thứ nhất của hợp đồng che. Không có cửa này thì lỗi nổ tận
    `operate.py:944` ở `r["hyperedge_name"]`, cách chỗ gây ra vài tầng.
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


def test_che_bo_mat_truong_thi_no_tai_cho(khong_gian, policy, monkeypatch):
    """Nửa thứ hai của hợp đồng che: che là thay giá trị, không bỏ khóa.

    Đường vector là đường cần nửa này nhất - `operate.py:953` đọc thẳng
    `k["distance"]` của chính bản ghi này, nên một khóa rụng ở đây thành
    `KeyError` sâu trong `vendor/`. Story 1.6 cho `_ban_ghi` gọi
    `kiem_ket_qua_che` thay vì tự viết một nửa hợp đồng, và đây là chỗ ghim
    rằng nửa còn lại thật sự có người canh.
    """
    from adapters import qdrant as mo_dun

    monkeypatch.setattr(
        mo_dun,
        "mask",
        lambda ket_qua, context, khoa: {
            k: v for k, v in ket_qua.items() if k != "distance"
        },
    )

    async def chay():
        _client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            with pytest.raises(MaskContractViolated) as loi:
                await adapter.query(CAU_HOI, top_k=10)
        assert loi.value.code == "MASK_CONTRACT_VIOLATED"
        assert "distance" in str(loi.value)

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


# --- Khóa đa nguồn: read-merge-write ở đường vector (story 2.1, FR-11) ----
#
# Ba test dưới đây thay `test_dac_ta_hien_trang_khoa_da_nguon_last_write_wins`
# của story 1.3. Test cũ ghim *hiện trạng* last-write-wins làm mốc so sánh và
# nói thẳng trong docstring rằng story 2.1 sẽ đổi hành vi này; nay hành vi đã
# đổi nên mốc so sánh hết việc. Ba ca mới phủ đúng ba hàng đầu của I/O Matrix
# story 2.1 trên chính đường ghi vector.


async def _nap_hai_lan(client, adapter, khong_gian, policy, cac_nhan):
    """Nạp cùng một lô hyperedge dưới lần lượt các nhãn, rồi trả các point còn lại."""
    chung = HYPEREDGES[0]
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        await adapter.initialize()
        for scope, loai in cac_nhan:
            with ingest_label(scope=scope, content_type=loai):
                await adapter.upsert(lo_upsert(chung))
    diem, _ = await client.scroll(
        collection_name=f"{khong_gian}_hyperedges", limit=10, with_payload=True
    )
    return diem


def test_cung_scope_nap_lai_duoi_nhan_nhay_hon_thi_siet_khoa(khong_gian, policy):
    """Hàng 1 của I/O Matrix ở đường vector: khóa thành nhãn hạn chế hơn."""

    async def chay():
        client = QdrantGhiLai()
        diem = await _nap_hai_lan(
            client,
            dung_adapter(client, khong_gian),
            khong_gian,
            policy,
            (("noi_bo", "runbook"), ("noi_bo", "bi_mat_ha_tang")),
        )
        assert len(diem) == 1, "cùng id upstream thì cùng point id, không nhân bản"
        assert diem[0].payload[FILTER_KEY_FIELD] == filter_key(
            "noi_bo", "bi_mat_ha_tang"
        )

    asyncio.run(chay())


def test_cung_scope_nap_lai_duoi_nhan_thuong_hon_thi_khong_noi_long(
    khong_gian, policy
):
    """Hàng 2: chiều mà last-write-wins làm sai - nạp sau không nới quyền ra."""

    async def chay():
        client = QdrantGhiLai()
        diem = await _nap_hai_lan(
            client,
            dung_adapter(client, khong_gian),
            khong_gian,
            policy,
            (("noi_bo", "bi_mat_ha_tang"), ("noi_bo", "runbook")),
        )
        assert len(diem) == 1
        assert diem[0].payload[FILTER_KEY_FIELD] == filter_key(
            "noi_bo", "bi_mat_ha_tang"
        )

    asyncio.run(chay())


def test_khac_scope_thi_point_vang_mat_khoi_collection(khong_gian, policy):
    """Hàng 3: khác scope ra "không khóa", và không khóa nghĩa là point bị xóa.

    Không phải một khóa đặc biệt: một khóa `"__none__"` sẽ là một giá trị hợp lệ
    trong `match_any`, và chỉ cần một vai vô ý được cấp nó là mọi artifact đa
    nguồn khác scope đổ ra. AD-5 đòi vắng mặt tuyệt đối ở cả 3 collection, nên
    ca này *xóa* point cũ và không ghi point mới.
    """

    async def chay():
        client = QdrantGhiLai()
        diem = await _nap_hai_lan(
            client,
            dung_adapter(client, khong_gian),
            khong_gian,
            policy,
            (("noi_bo", "runbook"), ("khach_hang_a", "bao_cao_su_co")),
        )
        assert diem == [], "point đa nguồn khác scope phải vắng mặt tuyệt đối"
        assert client.cac_loi_goi("delete"), "phải xóa point cũ, không chỉ bỏ qua"

    asyncio.run(chay())


def test_khac_scope_nap_lan_ba_cung_scope_dau_van_khong_khoa(khong_gian, policy):
    """Trạng thái hút phải sống được qua một lần nạp nữa ở đường vector.

    Point đã bị xóa nên kho vector một mình nó không phân biệt được "chưa từng
    ghi" với "đã hợp nhất ra không khóa" - đó là hệ quả cố ý của việc xóa thật.
    Ở đây nạp lại lần ba dưới đúng nhãn của lần đầu và ghim rằng point *quay
    lại*: hành vi này được biết, và chính bước đối chiếu hai kho là thứ bắt nó
    (node graph vẫn nhớ trạng thái không khóa), chứ không phải kho vector.
    """

    async def chay():
        client = QdrantGhiLai()
        diem = await _nap_hai_lan(
            client,
            dung_adapter(client, khong_gian),
            khong_gian,
            policy,
            (
                ("noi_bo", "runbook"),
                ("khach_hang_a", "bao_cao_su_co"),
                ("noi_bo", "runbook"),
            ),
        )
        assert len(diem) == 1 and diem[0].payload[FILTER_KEY_FIELD] == filter_key(
            "noi_bo", "runbook"
        )

    asyncio.run(chay())


def test_loai_noi_dung_khong_co_hang_thi_tu_choi_ca_lo(khong_gian, policy):
    """Hàng 4: nhãn mang loại nội dung ngoài bảng hạng là từ chối trước khi ghi."""

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            client.xoa_nhat_ky()
            with ingest_label(scope="noi_bo", content_type="hop_dong"):
                with pytest.raises(SensitivityRankUnknown) as loi:
                    await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert loi.value.code == "SENSITIVITY_RANK_UNKNOWN"
        assert client.cac_loi_goi("upsert") == []
        assert await client.dem_point(f"{khong_gian}_hyperedges") == 0

    asyncio.run(chay())


def test_upsert_tra_ve_dung_phan_da_ghi_va_khong_ai_doc_gia_tri_do(
    khong_gian, policy
):
    """Hợp đồng giá trị trả về đổi ở story 2.1; ghim cả phần đổi lẫn phần an toàn.

    Lô có mục hợp nhất ra "không khóa" thì point ấy bị xóa, nên danh sách trả
    về **ngắn hơn** đầu vào. Điều làm cho việc đó an toàn không phải là một giả
    định: không nơi nào trong `vendor/` đọc giá trị này. Test đọc chính mã
    nguồn upstream bằng AST để khẳng định câu ấy, thay vì để nó nằm trong một
    docstring và mục rữa dần theo thời gian.
    """
    import ast
    import inspect

    from hypergraphrag import hypergraphrag as hgr
    from hypergraphrag import operate

    async def chay():
        client = QdrantGhiLai()
        adapter = dung_adapter(client, khong_gian)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HYPEREDGES[0]))
            with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
                # Một mục hợp nhất ra không khóa, một mục bình thường.
                lo = {**lo_upsert(HYPEREDGES[0]), **lo_upsert(HYPEREDGES[3])}
                return await adapter.upsert(lo), lo

    tra_ve, lo = asyncio.run(chay())
    assert len(tra_ve) == 1 and len(lo) == 2, (
        "phần hợp nhất ra không khóa không nằm trong danh sách trả về"
    )

    # Mọi lời gọi `*_vdb.upsert` / `chunks_vdb.upsert` của upstream đều là một
    # câu lệnh độc lập (`ast.Expr`), tức giá trị trả về bị bỏ ngay.
    dung_gia_tri = []
    for module in (hgr, operate):
        cay = ast.parse(inspect.getsource(module))
        goi_bo_di = {
            id(n.value) for n in ast.walk(cay) if isinstance(n, ast.Expr)
        }
        for n in ast.walk(cay):
            if not isinstance(n, ast.Await):
                continue
            goi = n.value
            if not isinstance(goi, ast.Call):
                continue
            if getattr(goi.func, "attr", None) != "upsert":
                continue
            ten_kho = getattr(goi.func.value, "attr", "") or getattr(
                goi.func.value, "id", ""
            )
            if not ten_kho.endswith("vdb"):
                continue
            if id(n) not in goi_bo_di:
                dung_gia_tri.append(f"{module.__name__}:{n.lineno}")
    assert not dung_gia_tri, (
        "upstream đọc giá trị trả về của `upsert` ở"
        f" {dung_gia_tri}: hợp đồng danh sách ngắn hơn đầu vào không còn an toàn"
    )


def test_doc_khoa_hien_co_chi_chay_duoi_co_system(khong_gian, policy):
    """Bước đọc khóa của read-merge-write là ngoại lệ có đặc tả của AD-3.

    Dưới ngữ cảnh vai thì nó bị lọc theo khóa của vai đó, tức không bao giờ
    thấy khóa khác scope cần hợp nhất - luật hợp nhất khi ấy chạy trên dữ liệu
    sai. Nên cửa này từ chối thẳng thay vì trả một kết quả đã bị lọc.
    """

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(IngestOutsideSystemContext) as loi:
                await adapter.khoa_hien_co(["rel-HE-01"])
        assert loi.value.code == "INGEST_OUTSIDE_SYSTEM_CONTEXT"
        assert client.cac_loi_goi("retrieve") == []

    asyncio.run(chay())


def test_doc_khoa_hien_co_no_khi_point_mat_khoa(khong_gian, policy):
    """Point nằm trong kho mà không mang khóa là dữ liệu hỏng, phải nổ.

    Nhánh này chưa từng chạy trước đây: hai test khác đo nhánh *sinh đôi* ở
    đường đọc (`_ban_ghi`). Hậu quả nếu nó rụng thì nặng và im lặng - point
    hỏng cho `khoa = None`, `hop_nhat_khoa` coi `None` là trạng thái hút, và
    lần `upsert` kế tiếp **xóa hẳn** point đó. Mất dữ liệu mà không ai biết.
    """

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        # Gỡ khóa của một point đã nạp, đúng hình dạng một lần ghi tay không
        # qua adapter.
        await client.set_payload(
            collection_name=f"{khong_gian}_hyperedges",
            payload={FILTER_KEY_FIELD: None},
            points=[point_id("rel-HE-01")],
            wait=True,
        )
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with pytest.raises(PointFilterKeyMissing) as loi:
                await adapter.khoa_hien_co(["rel-HE-01"])
        return loi.value.code

    assert asyncio.run(chay()) == "POINT_FILTER_KEY_MISSING"


def test_hai_id_cung_point_id_thi_tu_choi_ca_lo(khong_gian, policy):
    """Hai id upstream chuẩn hóa về một point id là từ chối, không phải nuốt một.

    `point_id` là UUID5 của id đã chuẩn hóa, nên `"App01"` và `' "App01" '`
    là một point. Không có cửa này thì bước đọc khóa cũ nuốt mất một id, phép
    hợp nhất mất khóa cũ, và point nhận nhãn **rộng hơn** nhãn nó đang mang.
    """

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(PointIdCollision) as loi:
                    await adapter.upsert(
                        {
                            "rel-HE-01": {"content": "a", "hyperedge_name": "a"},
                            ' "rel-HE-01" ': {"content": "b", "hyperedge_name": "b"},
                        }
                    )
        return loi.value.code, client.cac_loi_goi("upsert")

    ma, da_ghi = asyncio.run(chay())
    assert ma == "POINT_ID_COLLISION"
    assert da_ghi == [], "từ chối cả lô, không ghi nửa nào"


def test_doc_khoa_hien_co_tra_ba_trang_thai(khong_gian, policy):
    """Id vắng ra `CHUA_GHI`, id đã ghi ra chính khóa của nó."""

    async def chay():
        _, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await adapter.khoa_hien_co(["rel-HE-01", "rel-KHONG-CO"])

    khoa = asyncio.run(chay())
    assert khoa["rel-HE-01"] == filter_key("noi_bo", "runbook")
    assert khoa["rel-KHONG-CO"] is CHUA_GHI


def test_ghi_duoi_ngu_canh_vai_bi_tu_choi(khong_gian, policy):
    """Ghi vector chỉ chạy dưới ngữ cảnh hệ thống của ingest (AD-3).

    Cùng một luật với đường graph và cùng một cửa (`ingest_key_for_write`):
    đường ghi là chỗ duy nhất đặt khóa quyền, nên nó không được mở cho ngữ cảnh
    vai người dùng.
    """

    async def chay():
        client, adapter = await kho_da_nap(khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                with pytest.raises(IngestOutsideSystemContext) as loi:
                    await adapter.upsert(lo_upsert(HYPEREDGES[0]))
        assert loi.value.code == "INGEST_OUTSIDE_SYSTEM_CONTEXT"
        assert client.cac_loi_goi("upsert") == []

    asyncio.run(chay())


# --- Vòng đời kết nối: `close()` đóng đúng thứ mình mở (story 1.7) ---------


def test_close_dong_client_do_chinh_adapter_mo(khong_gian, monkeypatch):
    """Không tiêm client thì adapter tự mở, và chính nó đóng lại.

    Nhánh này không có đường nào khác chạy vào: cặp test ở
    `tests/test_cong_m1.py` canh luật sở hữu ở *tầng engine*, nên đổi thân
    `close()` thành `pass` vẫn làm chúng xanh. Đây là chỗ đo chính thân method.
    """
    client = QdrantGhiLai()
    monkeypatch.setattr(
        QdrantVectorDBStorage, "_dung_client", staticmethod(lambda cau_hinh: client)
    )
    adapter = QdrantVectorDBStorage(
        namespace="hyperedges",
        global_config={"qdrant_url": "http://qdrant:6333"},
        embedding_func=embedding_gia(),
        meta_fields={"hyperedge_name"},
    )
    asyncio.run(adapter.close())
    assert len(client.cac_loi_goi("close")) == 1


def test_close_khong_dong_client_duoc_tiem(khong_gian):
    """Client tiêm từ ngoài thuộc về người tiêm; đóng hộ là làm hỏng kho khác.

    Engine tiêm **một** client cho cả ba namespace vector, nên một storage đóng
    hộ là hai namespace còn lại mất kết nối.
    """
    client = QdrantGhiLai()
    adapter = dung_adapter(client, khong_gian)
    asyncio.run(adapter.close())
    assert client.cac_loi_goi("close") == []
