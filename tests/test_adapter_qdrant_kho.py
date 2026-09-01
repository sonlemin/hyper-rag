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
    QdrantIndexMissing,
    QdrantVectorDBStorage,
)
from core.keys import FILTER_KEY_FIELD, filter_key
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
