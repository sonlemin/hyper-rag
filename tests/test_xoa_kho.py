"""Đường xóa/ghi thẳng của ba adapter và xóa cả space (story 2.3).

Viết trước cơ chế (FR-27). Ba adapter nhận đường xóa/ghi thẳng mà pipeline
re-ingest cần, và cả ba đi chung một luật: chỉ chạy dưới ngữ cảnh hệ thống
(`bat_buoc_ngu_canh_he_thong`), `space` lấy từ ngữ cảnh, mã lỗi ổn định.
Kho vector còn nhận sổ không khóa bền vững - thứ làm nó *nhớ* được trạng thái
không khóa dù point đã bị xóa (AD-5).

Không mạng, không container: kho vector local mode, driver graph giả.
"""

import asyncio
import json

import pytest
from qdrant_client import models

from adapters.doi_chieu import dot_ingest
from adapters.ingest import SoTaiLieu, nap_thu_muc, xoa_space
from adapters.ingest_labels import IngestOutsideSystemContext, ingest_label
from adapters.qdrant import (
    FILTER_MAX_CONDITIONS,
    GLOBAL_M,
    PAYLOAD_M,
    QdrantVectorDBStorage,
)
from core.audit import EVENT_DELETE_SPACE, TIER_MUTATION
from core.ids import point_id
from core.keys import CHUA_GHI, FILTER_KEY_FIELD, KHONG_KHOA, filter_key
from core.permission import use_context
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, THEO_ID
from tests.gia_lap_neo4j import Neo4jGhiLai, canh_moi_bien_deu_bi_loc  # noqa: F401
from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia
from tests.ho_tro_ingest import (
    dung_moi_truong,
    llm_theo_fact,
    viet_tai_lieu,
)
from tests.ho_tro_kv import dung_adapter as dung_kv
from tests.ho_tro_kv import kho_da_nap as kv_da_nap
from tests.ho_tro_neo4j import dung_adapter as dung_graph
from tests.ho_tro_neo4j import graph_da_nap, id_hyperedge
from tests.ho_tro_qdrant import kho_da_nap as qdrant_da_nap
from tests.ho_tro_qdrant import lo_upsert
from tests.ngu_canh import ngu_canh_ingest, vai

HE1 = THEO_ID["HE-01"]
HE2 = THEO_ID["HE-02"]


# --- Luật chung: ba adapter từ chối xóa ngoài ngữ cảnh hệ thống ----------------


def _qdrant_co_working_dir(client, workspace_dir, namespace="hyperedges", meta_fields=None):
    return QdrantVectorDBStorage(
        namespace=namespace,
        global_config={"embedding_batch_num": 2, "working_dir": str(workspace_dir)},
        embedding_func=embedding_gia(),
        meta_fields=set({"hyperedge_name"} if meta_fields is None else meta_fields),
        qdrant_client=client,
    )


@pytest.mark.parametrize(
    "goi",
    [
        lambda a: a.xoa(["x"]),
        lambda a: a.xoa_tat_ca(),
    ],
    ids=["xoa", "xoa_tat_ca"],
)
def test_kv_xoa_duoi_vai_nguoi_dung_bi_tu_choi(workspace_dir, khong_gian, policy, goi):
    """Hàng "Xóa ngoài ngữ cảnh hệ thống" ở đường KV: không chạm kho."""

    async def chay():
        adapter = await kv_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(IngestOutsideSystemContext) as loi:
                await goi(adapter)
        assert loi.value.code == "INGEST_OUTSIDE_SYSTEM_CONTEXT"
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await adapter.all_keys()

    assert sorted(asyncio.run(chay())) == sorted(c["id"] for c in CHUNKS)


@pytest.mark.parametrize(
    "goi",
    [
        lambda a: a.xoa(["rel-HE-01"]),
        lambda a: a.ghi_thang("rel-X", content="x", khoa="noi_bo:runbook"),
        lambda a: a.xoa_tat_ca(),
    ],
    ids=["xoa", "ghi_thang", "xoa_tat_ca"],
)
def test_qdrant_xoa_ghi_thang_duoi_vai_bi_tu_choi(khong_gian, policy, goi):
    async def chay():
        client, adapter = await qdrant_da_nap(khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(IngestOutsideSystemContext):
                await goi(adapter)
        assert client.cac_loi_goi("delete") == [] and client.cac_loi_goi("upsert") == []
        assert client.cac_loi_goi("delete_collection") == []
        return await client.dem_point(f"{khong_gian}_hyperedges")

    assert asyncio.run(chay()) == len(HYPEREDGES)


@pytest.mark.parametrize(
    "goi",
    [
        lambda a: a.xoa_node(["App01"]),
        lambda a: a.delete_node("App01"),
        lambda a: a.khoa_lan_can_hyperedge("App01"),
        lambda a: a.dat_lai_entity("App01", description="d", source_id="s", khoa="noi_bo:runbook"),
        lambda a: a.xoa_tat_ca(),
        lambda a: a.slot_cua_hyperedge("rel-HE-01"),
    ],
    ids=["xoa_node", "delete_node", "khoa_lan_can_hyperedge", "dat_lai_entity", "xoa_tat_ca", "slot_cua_hyperedge"],
)
def test_neo4j_duong_xoa_ghi_thang_duoi_vai_bi_tu_choi(khong_gian, policy, goi):
    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        so_node = driver.dem_node()
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(IngestOutsideSystemContext):
                await goi(adapter)
        assert driver.loi_goi == [], "không câu Cypher nào được gửi"
        return so_node, driver.dem_node()

    truoc, sau = asyncio.run(chay())
    assert truoc == sau


# --- KV: xóa theo id, xóa cả space -------------------------------------------


def test_kv_xoa_theo_id_va_ghi_xuong_dia(workspace_dir, khong_gian, policy):
    async def chay():
        adapter = await kv_da_nap(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            da_xoa = await adapter.xoa(["chunk-HE-01", "chunk-KHONG-CO"])
            await adapter.index_done_callback()
            con = await adapter.all_keys()
        # Instance mới đọc lại từ đĩa: bản ghi đã xóa không quay lại.
        moi = dung_kv(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            tren_dia = await moi.all_keys()
        return da_xoa, con, tren_dia

    da_xoa, con, tren_dia = asyncio.run(chay())
    assert da_xoa == ["chunk-HE-01"], "trả về đúng phần đã xóa, id lạ bỏ qua"
    assert "chunk-HE-01" not in con and "chunk-HE-01" not in tren_dia
    assert len(con) == len(CHUNKS) - 1


def test_kv_xoa_tat_ca_lam_kho_rong_va_go_file(workspace_dir, khong_gian, policy):
    async def chay():
        adapter = await kv_da_nap(workspace_dir, khong_gian, policy)
        duong_dan = adapter._duong_dan(khong_gian)
        assert duong_dan.exists()
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.xoa_tat_ca()
            con = await adapter.all_keys()
        return con, duong_dan.exists(), sorted(p.name for p in workspace_dir.iterdir())

    con, con_file, ten_file = asyncio.run(chay())
    assert con == [] and not con_file
    assert not any(n.endswith(".dang-ghi") for n in ten_file)


def test_kv_xoa_khong_cham_space_khac(workspace_dir, session_prefix, policy):
    """`space` lấy từ ngữ cảnh: xóa ở space này không chạm file của space kia."""
    a, b = f"{session_prefix}_a", f"{session_prefix}_b"

    async def chay():
        adapter = dung_kv(workspace_dir)
        for sp in (a, b):
            with use_context(ngu_canh_ingest(sp, policy)):
                with ingest_label(scope="noi_bo", content_type="runbook"):
                    await adapter.upsert({"c1": {"content": "x"}})
        await adapter.index_done_callback()
        with use_context(ngu_canh_ingest(a, policy)):
            await adapter.xoa_tat_ca()
        with use_context(ngu_canh_ingest(b, policy)):
            return await adapter.all_keys()

    assert asyncio.run(chay()) == ["c1"]


# --- Qdrant: xóa, ghi thẳng, sổ không khóa bền vững ----------------------------


def test_qdrant_vang_khong_con_mo_ho():
    """Kho vector nay nhớ trạng thái không khóa bằng sổ, nên "vắng" của nó không còn mơ hồ.

    Đổi kỳ vọng của story 2.1 (`VANG_LA_MO_HO = True`): trước đây point không
    khóa bị xóa và kho không còn chỗ giữ trạng thái; sổ không khóa theo space
    trong `working_dir` là chỗ giữ đó, và `khoa_hien_co` trả `KHONG_KHOA` cho
    id trong sổ.
    """
    assert QdrantVectorDBStorage.VANG_LA_MO_HO is False


def test_qdrant_xoa_theo_id(workspace_dir, khong_gian, policy):
    async def chay():
        client = QdrantGhiLai()
        adapter = _qdrant_co_working_dir(client, workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HE1))
                await adapter.upsert(lo_upsert(HE2))
            await adapter.xoa([id_hyperedge(HE1), "rel-KHONG-CO"])
            khoa = await adapter.khoa_hien_co([id_hyperedge(HE1), id_hyperedge(HE2)])
        return khoa, await client.dem_point(f"{khong_gian}_hyperedges")

    khoa, so_point = asyncio.run(chay())
    assert khoa[id_hyperedge(HE1)] is CHUA_GHI and khoa[id_hyperedge(HE2)] == filter_key("noi_bo", "runbook")
    assert so_point == 1


def test_qdrant_ghi_thang_mot_point_voi_khoa_va_payload(workspace_dir, khong_gian, policy):
    async def chay():
        client = QdrantGhiLai()
        adapter = _qdrant_co_working_dir(client, workspace_dir, "entities", {"entity_name"})
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with dot_ingest() as so:
                await adapter.ghi_thang(
                    "ent-APP01",
                    content="App01 mô tả",
                    khoa=filter_key("noi_bo", "bi_mat_ha_tang"),
                    meta={"entity_name": "App01"},
                )
            khoa = await adapter.khoa_hien_co(["ent-APP01"])
        diem = await client._that.retrieve(collection_name=f"{khong_gian}_entities", ids=[point_id("ent-APP01")])
        return khoa, diem, so

    khoa, diem, so = asyncio.run(chay())
    assert khoa["ent-APP01"] == filter_key("noi_bo", "bi_mat_ha_tang")
    assert diem[0].payload["entity_name"] == "App01" and "content" not in diem[0].payload
    # Ghi thẳng cũng vào sổ đợt, id join là tên entity: bước đối chiếu thấy nó.
    assert so.cac_id() == ["App01"]


def test_qdrant_ghi_thang_khong_khoa_thi_xoa_point_va_ghi_so(workspace_dir, khong_gian, policy):
    async def chay():
        client = QdrantGhiLai()
        adapter = _qdrant_co_working_dir(client, workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HE1))
            await adapter.ghi_thang(id_hyperedge(HE1), content="x", khoa=KHONG_KHOA)
            khoa = await adapter.khoa_hien_co([id_hyperedge(HE1)])
            so = adapter.so_khong_khoa(khong_gian)
        return khoa, await client.dem_point(f"{khong_gian}_hyperedges"), so

    khoa, so_point, so = asyncio.run(chay())
    assert khoa[id_hyperedge(HE1)] is KHONG_KHOA and so_point == 0
    assert so == {id_hyperedge(HE1)}


def test_qdrant_so_khong_khoa_ben_vung_qua_instance_moi(workspace_dir, khong_gian, policy):
    """Hợp nhất ra không khóa thì id vào sổ trên đĩa; instance mới đọc lại trả `KHONG_KHOA`."""

    async def chay():
        client = QdrantGhiLai()
        adapter = _qdrant_co_working_dir(client, workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HE1))
            with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
                await adapter.upsert(lo_upsert(HE1))
        file_so = workspace_dir / f"khong_khoa_{khong_gian}_hyperedges.json"
        assert file_so.exists()
        noi_dung = json.loads(file_so.read_text(encoding="utf-8"))
        moi = _qdrant_co_working_dir(client, workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            khoa = await moi.khoa_hien_co([id_hyperedge(HE1)])
            # Nạp lần ba cùng scope lần đầu: vẫn không khóa, không có point.
            with ingest_label(scope="noi_bo", content_type="runbook"):
                da_ghi = await moi.upsert(lo_upsert(HE1))
            khoa_sau = await moi.khoa_hien_co([id_hyperedge(HE1)])
        return noi_dung, khoa, da_ghi, khoa_sau, await client.dem_point(f"{khong_gian}_hyperedges")

    noi_dung, khoa, da_ghi, khoa_sau, so_point = asyncio.run(chay())
    assert noi_dung == {"version": 1, "ids": [id_hyperedge(HE1)]}
    assert khoa[id_hyperedge(HE1)] is KHONG_KHOA
    assert da_ghi == [] and khoa_sau[id_hyperedge(HE1)] is KHONG_KHOA and so_point == 0
    assert not any(p.name.endswith(".dang-ghi") for p in workspace_dir.iterdir())


def test_qdrant_xoa_go_id_khoi_so_khong_khoa(workspace_dir, khong_gian, policy):
    """Xóa hẳn (re-ingest, xóa tài liệu) thì id rời sổ: lần nạp sau là id mới."""

    async def chay():
        client = QdrantGhiLai()
        adapter = _qdrant_co_working_dir(client, workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HE1))
            with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
                await adapter.upsert(lo_upsert(HE1))
            await adapter.xoa([id_hyperedge(HE1)])
            khoa = await adapter.khoa_hien_co([id_hyperedge(HE1)])
            with ingest_label(scope="noi_bo", content_type="runbook"):
                da_ghi = await adapter.upsert(lo_upsert(HE1))
            khoa_sau = await adapter.khoa_hien_co([id_hyperedge(HE1)])
        return khoa, da_ghi, khoa_sau

    khoa, da_ghi, khoa_sau = asyncio.run(chay())
    assert khoa[id_hyperedge(HE1)] is CHUA_GHI
    assert len(da_ghi) == 1 and khoa_sau[id_hyperedge(HE1)] == filter_key("noi_bo", "runbook")


def test_qdrant_xoa_tat_ca_lam_collection_rong_va_go_so(workspace_dir, khong_gian, policy):
    async def chay():
        client = QdrantGhiLai()
        adapter = _qdrant_co_working_dir(client, workspace_dir)
        ten = f"{khong_gian}_hyperedges"
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HE1))
            with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
                await adapter.upsert(lo_upsert(HE1))
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(lo_upsert(HE2))
            await adapter.xoa_tat_ca()
            so = adapter.so_khong_khoa(khong_gian)
            con_collection = await client._that.collection_exists(collection_name=ten)
            # Khởi tạo lại được ngay và kho rỗng.
            await adapter.initialize()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                da_ghi = await adapter.upsert(lo_upsert(HE1))
        return so, con_collection, da_ghi, (workspace_dir / f"khong_khoa_{khong_gian}_hyperedges.json").exists()

    so, con_collection, da_ghi, con_file = asyncio.run(chay())
    assert so == set() and not con_collection and not con_file
    assert len(da_ghi) == 1, "sau xóa cả space, id cũ không còn bị sổ không khóa giữ"


def test_qdrant_initialize_ap_lai_hnsw_va_strict_mode_len_collection_da_co(khong_gian, policy):
    """Hàng "Collection cũ khác HNSW" trên kho giả: có lời `update_collection` đúng hằng.

    Local mode nhận rồi bỏ qua `hnsw_config`/`strict_mode_config` (báo
    `payload_m=None`, strict `None`), nên ở đây chỉ chứng minh được rằng adapter
    *phát* lời cập nhật khi cấu hình đọc về lệch hằng, và lời đó mang đúng ba
    hằng. Hiệu lực thật đo ở `tests/test_adapter_qdrant_that.py` (marker `qdrant`).
    """

    async def chay():
        client = QdrantGhiLai()
        adapter = QdrantVectorDBStorage(
            namespace="hyperedges",
            global_config={"embedding_batch_num": 2},
            embedding_func=embedding_gia(),
            meta_fields={"hyperedge_name"},
            qdrant_client=client,
        )
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            assert client.cac_loi_goi("update_collection") == [], "lần tạo mới không cần cập nhật"
            await adapter.initialize()
        return client.cac_loi_goi("update_collection")

    goi = asyncio.run(chay())
    assert len(goi) == 1
    hnsw = goi[0].kwargs["hnsw_config"]
    strict = goi[0].kwargs["strict_mode_config"]
    assert (hnsw.m, hnsw.payload_m) == (GLOBAL_M, PAYLOAD_M)
    assert strict.enabled is True and strict.filter_max_conditions == FILTER_MAX_CONDITIONS
    assert strict.unindexed_filtering_retrieve is False and strict.unindexed_filtering_update is False


def test_qdrant_initialize_khong_cap_nhat_khi_cau_hinh_da_khop(khong_gian, policy, monkeypatch):
    """Đối chứng: cấu hình đọc về đã khớp hằng thì không có lời cập nhật nào."""

    async def chay():
        client = QdrantGhiLai()
        adapter = QdrantVectorDBStorage(
            namespace="hyperedges",
            global_config={"embedding_batch_num": 2},
            embedding_func=embedding_gia(),
            meta_fields={"hyperedge_name"},
            qdrant_client=client,
        )
        goc = client._that.get_collection

        async def get_collection_khop(**kw):
            tt = await goc(**kw)
            tt.config.hnsw_config = models.HnswConfig(m=GLOBAL_M, payload_m=PAYLOAD_M, ef_construct=100, full_scan_threshold=10000)
            tt.config.strict_mode_config = models.StrictModeConfig(
                enabled=True,
                filter_max_conditions=FILTER_MAX_CONDITIONS,
                unindexed_filtering_retrieve=False,
                unindexed_filtering_update=False,
            )
            return tt

        monkeypatch.setattr(client._that, "get_collection", get_collection_khop)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            await adapter.initialize()
        return client.cac_loi_goi("update_collection")

    assert asyncio.run(chay()) == []


# --- Neo4j: xóa node, khóa lân cận, đặt lại entity, xóa space ------------------


def test_neo4j_xoa_node_detach_go_ca_canh(khong_gian, policy):
    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            so = await adapter.xoa_node([id_hyperedge(HE1), "khong-co"])
        cau = driver.cau_cuoi()
        return so, driver.node_tho(khong_gian, id_hyperedge(HE1)), driver.dem_lan_can_tho(khong_gian, id_hyperedge(HE1)), cau

    so, node, lan_can, cau = asyncio.run(chay())
    assert so == 1 and node is None and lan_can == 0
    assert "DETACH DELETE" in cau.cypher and cau.kieu_giao_dich == "write"
    canh_moi_bien_deu_bi_loc(cau.cypher, co_khoa=False)
    assert cau.params["ids"] == [id_hyperedge(HE1), "khong-co"]


def test_neo4j_delete_node_upstream_di_cung_luat(khong_gian, policy):
    """`delete_node` của hợp đồng upstream = `xoa_node([id])`, cùng cửa hệ thống."""

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.delete_node(id_hyperedge(HE2))
        return driver.node_tho(khong_gian, id_hyperedge(HE2)), driver.cau_cuoi().cypher

    node, cypher = asyncio.run(chay())
    assert node is None and "DETACH DELETE" in cypher


def test_neo4j_khoa_lan_can_hyperedge(khong_gian, policy):
    """Khóa của mọi hyperedge nối tới entity, kể cả `None` khi hyperedge không khóa."""

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            app01 = await adapter.khoa_lan_can_hyperedge("App01")
            cau = driver.cau_cuoi()
            # Gỡ khóa của HE-02 để có một lân cận không khóa.
            driver.nodes[(khong_gian, id_hyperedge(HE2))].props.pop(FILTER_KEY_FIELD)
            app01_sau = await adapter.khoa_lan_can_hyperedge("App01")
            la = await adapter.khoa_lan_can_hyperedge("khong-co")
        return app01, app01_sau, la, cau

    app01, app01_sau, la, cau = asyncio.run(chay())
    assert sorted(app01) == sorted([filter_key("noi_bo", "runbook"), filter_key("noi_bo", "bao_cao_su_co")])
    assert sorted(app01_sau, key=str) == sorted([None, filter_key("noi_bo", "runbook")], key=str)
    assert la == []
    assert cau.kieu_giao_dich == "write", "đọc khóa để hợp nhất phải thấy trạng thái leader"
    canh_moi_bien_deu_bi_loc(cau.cypher, co_khoa=False)


def test_neo4j_dat_lai_entity(khong_gian, policy):
    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with dot_ingest() as so:
                await adapter.dat_lai_entity(
                    "App01", description="mô tả mới", source_id="chunk-HE-02", khoa=filter_key("noi_bo", "bao_cao_su_co")
                )
            cau = driver.cau_cuoi()
            await adapter.dat_lai_entity("App01", description="", source_id="", khoa=KHONG_KHOA)
            khoa = await adapter.khoa_hien_co(["App01"])
        return driver.node_tho(khong_gian, "App01").props, cau, so, khoa

    props, cau, so, khoa = asyncio.run(chay())
    assert props["description"] == "" and props["source_id"] == ""
    assert props["role"] == "entity" and props["entity_type"] == "KHAC", "trường khác giữ nguyên"
    assert FILTER_KEY_FIELD not in props and khoa["App01"] is KHONG_KHOA
    assert cau.kieu_giao_dich == "write" and cau.params["key"] == filter_key("noi_bo", "bao_cao_su_co")
    assert so.cac_id() == ["App01"], "đặt lại cũng vào sổ đợt để đối chiếu"
    assert "vector:entities" in so.kho_ky_vong("App01")


def test_neo4j_dat_lai_entity_khong_co_node_la_loi(khong_gian, policy):
    from adapters.neo4j import EntityMissing

    async def chay():
        _, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with pytest.raises(EntityMissing) as loi:
                await adapter.dat_lai_entity("khong-co", description="d", source_id="s", khoa="noi_bo:runbook")
        return loi.value.code

    assert asyncio.run(chay()) == "ENTITY_MISSING"


def test_neo4j_xoa_tat_ca_chi_space_cua_ngu_canh(session_prefix, policy):
    a, b = f"{session_prefix}_a", f"{session_prefix}_b"

    async def chay():
        driver = Neo4jGhiLai()
        for sp in (a, b):
            await graph_da_nap(sp, policy, driver=driver)
        with use_context(ngu_canh_ingest(a, policy)):
            await adapter_xoa(driver)
        return sorted({sp for sp, _ in driver.nodes}), [c.space for c in driver.canh]

    async def adapter_xoa(driver):
        await dung_graph(driver).xoa_tat_ca()

    spaces, canh = asyncio.run(chay())
    assert spaces == [b] and set(canh) == {b}


# --- Xóa space qua pipeline ---------------------------------------------------


def test_xoa_space_don_sach_ba_kho_va_hai_so(workspace_dir, khong_gian, policy, tmp_path):
    """Hàng "Xóa space": graph rỗng theo nhãn space, 3 collection rỗng, 2 file KV rỗng, hai sổ xóa, một sự kiện."""
    thu_muc = tmp_path / "corpus"
    than_a = "Runbook App01 chung. Khi traffic cao thì khởi động lại PHP-FPM."
    than_c = "Runbook khách A về App01. App01 lỗi thì gọi đầu mối khách hàng."
    bang = {
        than_a: [{"subject": "App01", "remediation": "khởi động lại PHP-FPM"}],
        than_c: [{"subject": "App01", "remediation": "gọi đầu mối khách hàng"}],
    }
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=than_a)
    viet_tai_lieu(thu_muc, "c.md", scope="khach_hang_a", content_type="runbook", than=than_c)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact(bang))

    async def chay():
        await nap_thu_muc(mt.engine, thu_muc, space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            assert mt.engine.entities_vdb.so_khong_khoa(khong_gian), "APP01 hai scope phải vào sổ không khóa"
        await xoa_space(mt.engine, space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        so_point = {ns: await mt.client.dem_point(f"{khong_gian}_{ns}") for ns in ("entities", "hyperedges", "chunks")}
        # Space vẫn dùng được ngay: nạp lại như mới, không bị sổ cũ giữ.
        kq = await nap_thu_muc(mt.engine, thu_muc, space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        return so_point, kq

    so_point, kq = asyncio.run(chay())
    assert so_point == {"entities": 0, "hyperedges": 0, "chunks": 0}
    sk = mt.so_audit.cac_su_kien(EVENT_DELETE_SPACE)
    assert len(sk) == 1 and sk[0].tier == TIER_MUTATION and sk[0].space == khong_gian
    assert all(not t.re_ingest for t in kq.tai_lieu), "sau xóa space, nạp lại là nạp mới"
    # Bằng chứng đọc từ trạng thái *trước* lần nạp lại: sự kiện xóa ghi số đã dọn.
    assert sk[0].chi_tiet["so_tai_lieu"] == 2


def test_xoa_space_trang_thai_kho_ngay_sau_khi_xoa(workspace_dir, khong_gian, policy, tmp_path):
    """Nhìn thẳng vào kho ngay sau `xoa_space`, trước khi có gì nạp lại."""
    thu_muc = tmp_path / "corpus"
    than_a = "Runbook App01 chung. Khi traffic cao thì khởi động lại PHP-FPM."
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=than_a)
    mt = dung_moi_truong(workspace_dir, llm_theo_fact({than_a: [{"subject": "App01", "remediation": "khởi động lại PHP-FPM"}]}))

    async def chay():
        await nap_thu_muc(mt.engine, thu_muc, space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        await xoa_space(mt.engine, space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            kv = await mt.engine.text_chunks.all_keys(), await mt.engine.full_docs.all_keys()
        return kv

    kv = asyncio.run(chay())
    assert kv == ([], [])
    assert [sp for sp, _ in mt.driver.nodes if sp == khong_gian] == []
    assert not SoTaiLieu.duong_dan(workspace_dir, khong_gian).exists()
    assert not list(workspace_dir.glob(f"khong_khoa_{khong_gian}_*.json"))
    for ns in ("text_chunks", "full_docs"):
        f = workspace_dir / f"kv_store_{khong_gian}_{ns}.json"
        assert not f.exists() or json.loads(f.read_text(encoding="utf-8")) == {}


# --- Vòng review đối kháng 02/09/2026 ------------------------------------------


@pytest.mark.parametrize("noi_dung", ["{ hong", '["rel-x"]', '{"version": 9, "ids": []}', '{"version": 1, "ids": "x"}'])
def test_qdrant_so_khong_khoa_hong_la_loi_co_ma(workspace_dir, khong_gian, policy, noi_dung):
    from adapters.qdrant import KhongKhoaLedgerCorrupt

    (workspace_dir / f"khong_khoa_{khong_gian}_hyperedges.json").write_text(noi_dung, encoding="utf-8")

    async def chay():
        client = QdrantGhiLai()
        adapter = _qdrant_co_working_dir(client, workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.initialize()
            with pytest.raises(KhongKhoaLedgerCorrupt) as loi:
                await adapter.khoa_hien_co([id_hyperedge(HE1)])
        return loi.value.code

    assert asyncio.run(chay()) == "KHONG_KHOA_LEDGER_CORRUPT"


def test_qdrant_payload_cua_doc_tho_duoi_co_system(khong_gian, policy):
    async def chay():
        client, adapter = await qdrant_da_nap(khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(IngestOutsideSystemContext):
                await adapter.payload_cua([id_hyperedge(HE1)])
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await adapter.payload_cua([id_hyperedge(HE1), "rel-KHONG-CO"])

    payload = asyncio.run(chay())
    assert set(payload) == {id_hyperedge(HE1)}
    assert payload[id_hyperedge(HE1)]["hyperedge_name"] == f"{HE1['slots']['subject']} - {HE1['content_type']}"
    assert "content" not in payload[id_hyperedge(HE1)]


def test_neo4j_dat_lai_hyperedge(khong_gian, policy):
    from adapters.neo4j import HyperedgeMissing

    async def chay():
        driver, adapter = await graph_da_nap(khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with dot_ingest() as so:
                await adapter.dat_lai_hyperedge(id_hyperedge(HE1), source_id="chunk-x", khoa=KHONG_KHOA)
            khoa = await adapter.khoa_hien_co([id_hyperedge(HE1)])
            with pytest.raises(HyperedgeMissing) as loi:
                await adapter.dat_lai_hyperedge("App01", source_id="s", khoa="noi_bo:runbook")
        return driver.node_tho(khong_gian, id_hyperedge(HE1)).props, khoa, so, loi.value.code

    props, khoa, so, ma = asyncio.run(chay())
    assert props["source_id"] == "chunk-x" and FILTER_KEY_FIELD not in props and props["role"] == "hyperedge"
    assert khoa[id_hyperedge(HE1)] is KHONG_KHOA
    assert so.cac_id() == [id_hyperedge(HE1)] and "vector:hyperedges" in so.kho_ky_vong(id_hyperedge(HE1))
    assert ma == "HYPEREDGE_MISSING", "một entity không phải hyperedge: MATCH theo nhãn Hyperedge không khớp"
