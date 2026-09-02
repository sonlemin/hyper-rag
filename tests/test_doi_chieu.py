"""Đối chiếu khóa quyền hai kho sau mỗi đợt ingest (story 2.1, NFR-03).

Viết trước cơ chế (FR-27). Ba thứ được đo ở đây, và chúng khác nhau:

1. **Sổ đợt** - "mọi id được ghi trong đợt, gồm id bị read-merge-write chạm" là
   một tính chất của code (adapter tự ghi sổ trong đường ghi), không phải một
   danh sách mà pipeline nhớ liệt kê.
2. **Phép so** - so cả *giá trị khóa* lẫn *id join chéo hai kho*: một id có ở
   kho này mà thiếu ở kho kia cũng là lệch, không chỉ hai khóa khác nhau.
3. **Thứ tự ghi graph trước vector** - tính chất của `operate.py`, ghim bằng
   test chứ không cài lại (Never của spec).

Không mạng, không container: kho vector là local mode, driver graph là bản giả.
"""

import ast
import asyncio
import inspect

import pytest
from qdrant_client import models

from adapters.doi_chieu import (
    KHO_GRAPH,
    SoDot,
    TEN_VANG_MO_HO,
    ReconcileStoreContractMissing,
    ReconcileStoreMissing,
    StoreKeyMismatch,
    doi_chieu_dot,
    dot_ingest,
    ghi_vao_so,
    kho_cua_engine,
    so_dang_mo,
    ten_kho_kv,
    ten_kho_vector,
    tim_lech,
    van_tay,
    vang_la_mo_ho,
)
from adapters.ingest_labels import ingest_label
from core.ids import point_id
from core.keys import CHUA_GHI, FILTER_KEY_FIELD, KHONG_KHOA
from core.permission import use_context
from core.system_context import system_context
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, THEO_ID
from tests.gia_lap_llm import LLMGia
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.gia_lap_qdrant import QdrantGhiLai
from tests.ho_tro_m1 import dung_engine
from tests.nap_kho import nap_mot_hyperedge, ten_hyperedge

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

HE = THEO_ID["HE-01"]
# Entity dùng làm mục thử: nó có mặt ở cả graph (id node = giá trị slot) lẫn
# collection `entities` (id upstream `ent-…`, payload mang `entity_name`), nên
# nó là chỗ phép join chéo hai kho có việc để làm.
ENTITY = HE["slots"]["subject"]


class _MoiTruong:
    """Engine cùng hai kho giả, giữ lại để test chọc thẳng vào kho."""

    def __init__(self, engine, client, driver):
        self.engine = engine
        self.client = client
        self.driver = driver


async def _nap_mot_dot(workspace_dir, khong_gian, policy, *, cac_he=(HE,)):
    """Nạp một đợt nhỏ và trả về (môi trường, sổ đợt) khi ngữ cảnh còn mở."""
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    engine = dung_engine(workspace_dir, client, driver, LLMGia())
    await engine.khoi_tao()
    with dot_ingest() as so:
        for he in cac_he:
            with ingest_label(scope=he["scope"], content_type=he["content_type"]):
                await nap_mot_hyperedge(engine, he)
    return _MoiTruong(engine, client, driver), so


# --- Sổ đợt: ai ghi vào đó, và ghi những gì ------------------------------


def test_so_dot_ke_du_ba_kho_cua_mot_hyperedge(workspace_dir, khong_gian, policy):
    """Một hyperedge nạp xong thì sổ có id join của nó ở cả graph lẫn vector."""

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            _, so = await _nap_mot_dot(workspace_dir, khong_gian, policy)
            return so

    so = asyncio.run(chay())
    assert ten_hyperedge(HE) in so.cac_id()
    assert ENTITY in so.cac_id()
    assert so.kho_cua(ENTITY) == {
        KHO_GRAPH: ENTITY,
        ten_kho_vector("entities"): f"ent-{ENTITY}",
    }
    # Kỳ vọng khớp đúng hai kho đó và không thiếu kho nào: đây là chỗ luật
    # "một id phải có mặt ở cả hai phía" được khai, và nó do adapter khai chứ
    # không do một bảng trong bước đối chiếu.
    assert so.kho_ky_vong(ENTITY) == {KHO_GRAPH, ten_kho_vector("entities")}
    assert so.kho_thieu(ENTITY) == set()
    assert so.kho_cua(ten_hyperedge(HE))[ten_kho_vector("hyperedges")] == (
        f"rel-{HE['id']}"
    )


def test_so_dot_ke_ca_id_chi_bi_read_merge_write_cham(
    workspace_dir, khong_gian, policy
):
    """Id không thêm bản ghi mới vẫn phải nằm trong đợt.

    Đây là ca dễ quên nhất nếu pipeline tự liệt kê "đã ghi những gì": lần nạp
    thứ hai của một chunk trùng id không chèn bản ghi nào (ngữ nghĩa chỉ-chèn
    của upstream), nhưng nó *có* đổi khóa quyền của bản ghi cũ. Bỏ nó ra khỏi
    đợt là bỏ đúng loại id mà story này sinh ra để canh.
    """

    async def chay():
        client = QdrantGhiLai()
        engine = dung_engine(workspace_dir, client, Neo4jGhiLai(), LLMGia())
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            await engine.khoi_tao()
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await engine.text_chunks.upsert({"c1": {"content": "x"}})
            with dot_ingest() as so:
                with ingest_label(scope="noi_bo", content_type="bi_mat_ha_tang"):
                    them = await engine.text_chunks.upsert({"c1": {"content": "x"}})
            return so, them

    so, them = asyncio.run(chay())
    assert them == {}, "lần nạp thứ hai không chèn bản ghi mới"
    assert so.cac_id() == ["c1"], "id bị read-merge-write chạm vẫn phải vào sổ"
    assert so.kho_cua("c1") == {ten_kho_kv("text_chunks"): "c1"}
    # Lô này cố ý chỉ ghi kho KV, nên bản sao vector của chunk còn thiếu - và
    # sổ nói được điều đó ngay cả khi chưa ai chạy phép so.
    assert so.kho_thieu("c1") == {ten_kho_vector("chunks")}


def test_ghi_so_ngoai_pham_vi_dot_la_no_op():
    """Ngoài một đợt thì không có gì để đối chiếu, nên ghi sổ là no-op.

    Cố ý không phải lỗi: bộ test adapter lẻ và đường truy vấn đều ghi/đọc hợp
    lệ mà không ai định đối chiếu. Cửa đối chiếu nằm ở chỗ *mở đợt*, tức ở
    pipeline ingest, không ở từng lời gọi ghi.
    """
    assert so_dang_mo() is None
    ghi_vao_so(id_join="x", kho=KHO_GRAPH, id_trong_kho="x")  # không nổ


def test_dot_long_nhau_thi_so_trong_cung_thang():
    """Ngữ nghĩa token của contextvar, không phải một chồng sổ tự quản."""
    with dot_ingest() as ngoai:
        ghi_vao_so(id_join="a", kho=KHO_GRAPH, id_trong_kho="a")
        with dot_ingest() as trong:
            ghi_vao_so(id_join="b", kho=KHO_GRAPH, id_trong_kho="b")
        ghi_vao_so(id_join="c", kho=KHO_GRAPH, id_trong_kho="c")
    assert ngoai.cac_id() == ["a", "c"]
    assert trong.cac_id() == ["b"]
    assert so_dang_mo() is None


# --- Phép so: giá trị khóa và id join chéo hai kho -----------------------


def test_dot_nap_binh_thuong_thi_khong_lech(workspace_dir, khong_gian, policy):
    """Đường chạy đúng: hai kho nói cùng một khóa cho mọi id của đợt."""

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            mt, so = await _nap_mot_dot(workspace_dir, khong_gian, policy)
            return await tim_lech(so, kho=kho_cua_engine(mt.engine))

    assert asyncio.run(chay()) == []


def test_khoa_lech_giua_hai_kho_lam_dot_fail(workspace_dir, khong_gian, policy):
    """Hai kho nói hai khóa khác nhau cho cùng một id: đợt fail, có tên id.

    Sửa thẳng vào kho graph để dựng ca "lệch do sự cố" - thứ mà luật hợp nhất
    một chỗ không chặn được: một lô ghi đứt giữa chừng, một kho rớt, hay ai đó
    sửa tay. Đó đúng là loại lệch mà bước này sinh ra để bắt.
    """

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            mt, so = await _nap_mot_dot(workspace_dir, khong_gian, policy)
            mt.driver.nodes[(khong_gian, ENTITY)].props[FILTER_KEY_FIELD] = (
                "khach_hang_a:bao_cao_su_co"
            )
            with pytest.raises(StoreKeyMismatch) as loi:
                await doi_chieu_dot(so, kho=kho_cua_engine(mt.engine))
            sau_khi_lech = mt.driver.nodes[(khong_gian, ENTITY)].props[
                FILTER_KEY_FIELD
            ]
        return loi.value, sau_khi_lech

    loi, sau_khi_lech = asyncio.run(chay())
    assert loi.code == "STORE_KEY_MISMATCH"
    # Thông điệp mang **vân tay**, không mang id nguyên văn: id join của node
    # graph là tên thực thể, tức có thể là nguyên văn một giá trị slot thuộc
    # scope hạn chế, và thông điệp lỗi thì đi thẳng vào log vận hành - ngoài
    # mọi tầng che.
    assert ENTITY not in str(loi)
    assert van_tay(ENTITY) in str(loi)
    assert "graph" in str(loi) and "vector:entities" in str(loi)
    # Không tự sửa: cả hai kho giữ nguyên trạng thái lệch sau khi lỗi ném ra.
    assert sau_khi_lech == "khach_hang_a:bao_cao_su_co"


def test_point_bien_mat_sau_khi_ghi_la_lech(workspace_dir, khong_gian, policy):
    """Node graph còn khóa mà point vector biến mất: hai đường truy hồi lệch nhau.

    Ca "kho rớt sau khi đã ghi". Đường graph vẫn kể fact đó ra, đường vector
    thì không tìm ra nó nữa, nên hai vai hỏi cùng một câu nhận hai bức tranh
    khác nhau tùy đường nào chạm tới trước.
    """

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            mt, so = await _nap_mot_dot(workspace_dir, khong_gian, policy)
            await mt.client.delete(
                collection_name=f"{khong_gian}_entities",
                points_selector=models.PointIdsList(
                    points=[point_id(f"ent-{ENTITY}")]
                ),
                wait=True,
            )
            with pytest.raises(StoreKeyMismatch) as loi:
                await doi_chieu_dot(so, kho=kho_cua_engine(mt.engine))
        return str(loi.value)

    thong_diep = asyncio.run(chay())
    assert van_tay(ENTITY) in thong_diep
    assert "vắng" in thong_diep


def test_id_truot_han_o_kho_thu_hai_cung_la_lech(
    workspace_dir, khong_gian, policy
):
    """Ca thật của "có ở kho này thiếu ở kho kia": kho thứ hai **không bao giờ**
    nhận id đó.

    Đây là ca mà phép giao một mình không bắt được, và nó là ca hay xảy ra
    nhất: lô ghi vector nổ giữa chừng, hoặc kho vector rớt, nên id chỉ vào
    được graph. Nếu sổ chỉ kể các kho *đã ghi xong* thì id ấy có đúng một báo
    cáo, phép giao trên một tập không bao giờ rỗng, và đợt vẫn "xanh".

    Hai cơ chế cùng đóng ca này, và test dựng đúng chỗ chúng gặp nhau: adapter
    ghi sổ **ý định** trước khi chạm kho, và sổ mang **tập kho kỳ vọng** do
    chính adapter khai.
    """

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            client = QdrantGhiLai()
            driver = Neo4jGhiLai()
            engine = dung_engine(workspace_dir, client, driver, LLMGia())
            await engine.khoi_tao()
            with dot_ingest() as so:
                with ingest_label(
                    scope=HE["scope"], content_type=HE["content_type"]
                ):
                    # Chỉ ghi phía graph. Lô vector không bao giờ chạy - đúng
                    # thứ một kho rớt giữa đợt để lại.
                    await engine.chunk_entity_relation_graph.upsert_node(
                        ENTITY,
                        {"role": "entity", "entity_type": "KHAC",
                         "description": ENTITY, "source_id": HE["source_id"]},
                    )
                thieu = so.kho_thieu(ENTITY)
                with pytest.raises(StoreKeyMismatch) as loi:
                    await doi_chieu_dot(so, kho=kho_cua_engine(engine))
        return thieu, str(loi.value)

    thieu, thong_diep = asyncio.run(chay())
    assert thieu == {ten_kho_vector("entities")}
    assert van_tay(ENTITY) in thong_diep
    assert "không có trong đợt" in thong_diep


def test_lo_no_giua_chung_van_de_lai_dau_vet_trong_so(
    workspace_dir, khong_gian, policy
):
    """Ghi sổ là **ý định ghi**, nên một lô nổ giữa chừng vẫn để lại dấu vết.

    Ghi sổ sau khi chạm kho thì đúng những id của lô hỏng biến mất khỏi đợt, và
    bước đối chiếu cuối đợt không có gì để hỏi về chúng - tức nó mù đúng lúc
    cần nhất. Test dựng một lô upsert vector nổ ở tầng client và khẳng định id
    vẫn nằm trong sổ.
    """

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            client = QdrantGhiLai()
            engine = dung_engine(workspace_dir, client, Neo4jGhiLai(), LLMGia())
            await engine.khoi_tao()

            async def no(*a, **k):
                raise RuntimeError("giả lập: kho vector rớt giữa lô")

            with dot_ingest() as so:
                with ingest_label(
                    scope=HE["scope"], content_type=HE["content_type"]
                ):
                    client._that.upsert = no
                    with pytest.raises(RuntimeError):
                        await engine.entities_vdb.upsert(
                            {f"ent-{ENTITY}": {"content": ENTITY,
                                               "entity_name": ENTITY}}
                        )
            return so

    so = asyncio.run(chay())
    assert ENTITY in so.cac_id(), "id của lô hỏng phải nằm lại trong sổ đợt"
    assert so.kho_thieu(ENTITY) == {KHO_GRAPH}


def test_ca_khong_khoa_khong_bi_bao_lech(workspace_dir, khong_gian, policy):
    """Point bị xóa vì "không khóa" phải khớp với node graph không khóa.

    Kho vector không phân biệt được "vắng" với "không khóa" - xóa point là yêu
    cầu của AD-5 - nên phép so nhận cả hai khả năng cho báo cáo của nó. Không
    có luật đó thì mọi ca hợp nhất khác scope đều báo lệch giả, và một bước đối
    chiếu hay báo động giả là một bước sẽ bị tắt.
    """
    chung = "Xoay khóa ký giao dịch theo quy trình chung"
    he_a = {
        "id": "HE-DC-A",
        "source_id": "chunk-HE-01",
        "scope": "noi_bo",
        "content_type": "runbook",
        "slots": {"subject": "Cổng nội bộ", "remediation": chung},
    }
    he_b = {
        "id": "HE-DC-B",
        "source_id": "chunk-HE-04",
        "scope": "khach_hang_a",
        "content_type": "bao_cao_su_co",
        "slots": {"subject": "Cổng khách hàng A", "remediation": chung},
    }

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            mt, so = await _nap_mot_dot(
                workspace_dir, khong_gian, policy, cac_he=(he_a, he_b)
            )
            lech = await tim_lech(so, kho=kho_cua_engine(mt.engine))
            khoa_graph = await mt.engine.chunk_entity_relation_graph.khoa_hien_co(
                [chung]
            )
            khoa_vector = await mt.engine.entities_vdb.khoa_hien_co([f"ent-{chung}"])
        return lech, khoa_graph[chung], khoa_vector[f"ent-{chung}"]

    lech, khoa_graph, khoa_vector = asyncio.run(chay())
    assert lech == [], "ca không khóa không được báo lệch"
    assert khoa_graph is KHONG_KHOA, "node graph ở lại và nhớ trạng thái không khóa"
    # Đổi kỳ vọng ở story 2.3: point vẫn bị xóa hẳn (AD-5), nhưng id vào sổ
    # không khóa bền vững của kho vector nên `khoa_hien_co` nay trả
    # `KHONG_KHOA` thay vì `CHUA_GHI`. Kho vector không còn "quên".
    assert khoa_vector is KHONG_KHOA, "point bị xóa nhưng sổ không khóa nhớ trạng thái"


def test_thieu_mot_kho_trong_buoc_doi_chieu_la_loi(workspace_dir, khong_gian, policy):
    """Đối chiếu nửa vời còn tệ hơn không đối chiếu: nó nói "không lệch"."""

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            mt, so = await _nap_mot_dot(workspace_dir, khong_gian, policy)
            kho = kho_cua_engine(mt.engine)
            del kho[ten_kho_vector("entities")]
            with pytest.raises(ReconcileStoreMissing) as loi:
                await doi_chieu_dot(so, kho=kho)
            assert loi.value.code == "RECONCILE_STORE_MISSING"

    asyncio.run(chay())


def test_dot_rong_thi_khong_lech(workspace_dir, khong_gian, policy):
    """Đợt không ghi gì là đợt không có gì để so, không phải một lỗi."""

    async def chay():
        client = QdrantGhiLai()
        engine = dung_engine(workspace_dir, client, Neo4jGhiLai(), LLMGia())
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            with dot_ingest() as so:
                await doi_chieu_dot(so, kho=kho_cua_engine(engine))
        return len(so)

    assert asyncio.run(chay()) == 0


# --- Hợp đồng "vắng của tôi có mơ hồ không" ------------------------------


def test_ba_adapter_deu_khai_vang_la_mo_ho():
    """Mỗi kho tự khai, và ba giá trị phải đúng theo cơ chế của từng kho.

    Kỳ vọng viết tay ở đây, không suy từ chính thuộc tính: đó là điều làm cho
    một lần đổi giá trị thành một test đỏ chứ thành một ngữ nghĩa mới không ai
    duyệt. Story 2.1 kho vector khai `True` vì ca không khóa **xóa** point
    (AD-5) và kho không còn chỗ nhớ. Story 2.3 đổi thành `False`: point vẫn bị
    xóa nhưng sổ không khóa bền vững theo space nhớ trạng thái đó, nên "vắng"
    của kho vector lại đúng là chưa từng ghi, như graph và KV.
    """
    from adapters.kv import JsonACLKVStorage
    from adapters.neo4j import Neo4jACLGraphStorage
    from adapters.qdrant import QdrantVectorDBStorage

    assert QdrantVectorDBStorage.VANG_LA_MO_HO is False
    assert Neo4jACLGraphStorage.VANG_LA_MO_HO is False
    assert JsonACLKVStorage.VANG_LA_MO_HO is False


def test_thuoc_tinh_khai_khong_thanh_field_cua_dataclass():
    """Khai bằng thuộc tính lớp *không chú kiểu*, nên nó không là field.

    Một annotation biến nó thành field của dataclass, và khi đó nó đi vào
    `asdict(self)` của engine rồi xuống `global_config` như một khóa cấu hình -
    thứ nó không phải, và là thứ `test_bien_moi_truong_phu_het_khoa_cau_hinh_kho`
    sẽ không bắt vì nó chỉ canh `KHOA_CAU_HINH_KHO`.
    """
    from adapters.kv import JsonACLKVStorage
    from adapters.neo4j import Neo4jACLGraphStorage
    from adapters.qdrant import QdrantVectorDBStorage

    for lop in (QdrantVectorDBStorage, Neo4jACLGraphStorage, JsonACLKVStorage):
        assert TEN_VANG_MO_HO not in lop.__dataclass_fields__, lop.__name__


def test_kho_khong_khai_thi_buoc_doi_chieu_tu_choi_chay():
    """Không khai là lỗi, không phải một mặc định - fail-closed.

    Đoán mặc định là chọn giữa hai cách hỏng: `True` làm mọi lệch thật thành
    "không lệch", `False` làm mọi ca không khóa thành lệch giả. Cùng kỷ luật
    với `tests/test_phan_chieu_che.py`: một kho mới phải *khai* chỗ đứng của nó.
    """

    class KhoLa:
        async def khoa_hien_co(self, ids):
            return {}

    with pytest.raises(ReconcileStoreContractMissing) as loi:
        vang_la_mo_ho(KhoLa(), "vector:la")
    assert loi.value.code == "RECONCILE_STORE_CONTRACT_MISSING"
    # Khai sai kiểu cũng là chưa khai: một chuỗi `"True"` là truthy và sẽ lặng
    # lẽ chạy như `True`.
    class KhoKhaiSaiKieu:
        VANG_LA_MO_HO = "True"

    with pytest.raises(ReconcileStoreContractMissing):
        vang_la_mo_ho(KhoKhaiSaiKieu(), "vector:la")


def test_tim_lech_dung_thuoc_tinh_cua_kho_chu_khong_suy_tu_ten(
    workspace_dir, khong_gian, policy
):
    """Ngữ nghĩa "vắng" đến từ chính kho, không từ tiền tố tên kho.

    Dựng đúng ca phân biệt hai đường: một đợt có ca không khóa (point vector đã
    bị xóa, node graph không khóa) được đăng ký dưới một tên kho **không** mang
    tiền tố `vector:`. Nếu bước đối chiếu còn suy từ tên thì nó coi "vắng" của
    kho ấy là chưa từng ghi và báo lệch giả.
    """
    chung = "Xoay khóa ký giao dịch theo quy trình chung"
    he_a = {
        "id": "HE-TEN-A", "source_id": "chunk-HE-01", "scope": "noi_bo",
        "content_type": "runbook",
        "slots": {"subject": "Cổng nội bộ", "remediation": chung},
    }
    he_b = {
        "id": "HE-TEN-B", "source_id": "chunk-HE-04", "scope": "khach_hang_a",
        "content_type": "bao_cao_su_co",
        "slots": {"subject": "Cổng khách hàng A", "remediation": chung},
    }

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            mt, so = await _nap_mot_dot(
                workspace_dir, khong_gian, policy, cac_he=(he_a, he_b)
            )
            kho = kho_cua_engine(mt.engine)
            # Đăng ký lại kho vector dưới một cái tên không mang tiền tố
            # `vector:`, và ghi sổ theo đúng tên đó.
            ten_la = "kho_khong_theo_quy_uoc"
            kho[ten_la] = kho.pop(ten_kho_vector("entities"))
            so_moi = SoDot()
            so_moi.ghi(id_join=chung, kho=KHO_GRAPH, id_trong_kho=chung,
                       kho_doi=ten_la)
            so_moi.ghi(id_join=chung, kho=ten_la, id_trong_kho=f"ent-{chung}",
                       kho_doi=KHO_GRAPH)
            return await tim_lech(so_moi, kho=kho)

    assert asyncio.run(chay()) == [], (
        "bước đối chiếu vẫn suy ngữ nghĩa 'vắng' từ tên kho, nên một kho vector"
        " đặt tên khác cho ra một lệch giả"
    )


# --- Thứ tự ghi: graph trước, vector sau (tính chất của `operate.py`) ----


def test_upstream_ghi_graph_truoc_vector():
    """`extract_entities` ghi xong graph rồi mới upsert hai kho vector.

    Ghim chứ không cài lại (Never của spec): thứ tự này là tính chất của
    `vendor/hypergraphrag/operate.py`, và luật hợp nhất khóa đứng lên nó. Node
    graph là kho *nhớ* được trạng thái "không khóa" (point vector bị xóa hẳn),
    nên đọc-hợp nhất ở phía graph trước là đọc trên bản đầy đủ nhất; đảo thứ tự
    thì một id đa nguồn khác scope có một cửa sổ mà vector đã ghi khóa mới còn
    graph chưa hợp nhất.

    Đọc bằng AST chứ không tìm chuỗi: một dòng bị comment lại vẫn qua được phép
    tìm chuỗi, và khi đó test khẳng định một tính chất không còn tồn tại.
    """
    from hypergraphrag import operate

    cay = ast.parse(inspect.getsource(operate.extract_entities))
    dong_graph = [
        n.lineno
        for n in ast.walk(cay)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "").startswith("_merge_")
        and getattr(n.func, "id", "").endswith("_then_upsert")
    ]
    dong_vector = [
        n.lineno
        for n in ast.walk(cay)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", None) == "upsert"
        and getattr(getattr(n.func, "value", None), "id", "").endswith("_vdb")
    ]
    assert dong_graph, "không tìm thấy lời gọi ghi graph nào"
    assert dong_vector, "không tìm thấy lời gọi upsert kho vector nào"
    assert max(dong_graph) < min(dong_vector), (
        "upstream không còn ghi graph trước vector: luật hợp nhất khóa đứng"
        " trên thứ tự đó"
    )


def test_loader_test_giu_dung_thu_tu_do(workspace_dir, khong_gian, policy):
    """Loader của bộ test cũng ghi graph trước vector, như đường thật.

    Không có lớp này thì bộ test chứng minh cơ chế trên một thứ tự ghi mà sản
    phẩm không dùng.

    Đo trên **một nhật ký chung có thứ tự**, không trên hai nhật ký riêng: mỗi
    nhật ký riêng chỉ biết thứ tự bên trong chính nó, nên "graph xong rồi mới
    tới vector" không đo được từ chúng - đảo hẳn hai khối lệnh vẫn cho mỗi
    nhật ký một thứ tự nội bộ y hệt. Đây là task "ghim thứ tự graph trước
    vector" của spec nên nó phải đo thật.
    """

    async def chay():
        chung: list[tuple[str, str]] = []
        client = QdrantGhiLai(nhat_ky_chung=chung)
        driver = Neo4jGhiLai(nhat_ky_chung=chung)
        engine = dung_engine(workspace_dir, client, driver, LLMGia())
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            await engine.khoi_tao()
            chung.clear()
            with ingest_label(scope=HE["scope"], content_type=HE["content_type"]):
                await nap_mot_hyperedge(engine, HE)
        return chung

    chung = asyncio.run(chay())
    ghi_graph = [i for i, (kho, viec) in enumerate(chung)
                 if kho == "graph" and viec.startswith("ghi:")]
    ghi_vector = [i for i, (kho, viec) in enumerate(chung)
                  if kho == "vector" and viec == "upsert"]
    assert ghi_graph, "loader không ghi graph"
    assert ghi_vector, "loader không ghi kho vector"
    assert max(ghi_graph) < min(ghi_vector), (
        "loader ghi vector trước khi ghi xong graph: bộ test đang chứng minh"
        f" cơ chế trên một thứ tự ghi mà sản phẩm không dùng\n{chung}"
    )


def test_nhat_ky_chung_bat_duoc_thu_tu_dao(workspace_dir, khong_gian, policy):
    """Chính bộ đo phải có test: đảo thứ tự thì nó phải đỏ.

    Không có ca này thì một nhật ký chung luôn rỗng (hay luôn cùng thứ tự) vẫn
    làm test trên xanh mãi, và lớp assert vừa dựng lên không đo gì.
    """

    async def chay():
        chung: list[tuple[str, str]] = []
        client = QdrantGhiLai(nhat_ky_chung=chung)
        driver = Neo4jGhiLai(nhat_ky_chung=chung)
        engine = dung_engine(workspace_dir, client, driver, LLMGia())
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            await engine.khoi_tao()
            chung.clear()
            with ingest_label(scope=HE["scope"], content_type=HE["content_type"]):
                ten = ten_hyperedge(HE)
                # Thứ tự **đảo**: vector trước, graph sau.
                await engine.hyperedges_vdb.upsert(
                    {f"rel-{HE['id']}": {"content": ten, "hyperedge_name": ten}}
                )
                await engine.chunk_entity_relation_graph.upsert_node(
                    ten, {"role": "hyperedge", "weight": 1.0,
                          "source_id": HE["source_id"]},
                )
        return chung

    chung = asyncio.run(chay())
    ghi_graph = [i for i, (kho, viec) in enumerate(chung)
                 if kho == "graph" and viec.startswith("ghi:")]
    ghi_vector = [i for i, (kho, viec) in enumerate(chung)
                  if kho == "vector" and viec == "upsert"]
    assert ghi_graph and ghi_vector
    assert max(ghi_graph) > min(ghi_vector), (
        "bộ đo không phân biệt được hai thứ tự, nên test kia không đo gì"
    )


# --- Chunk: kho KV và collection `chunks` cũng phải khớp -----------------


def test_chunk_doi_chieu_giua_kv_va_collection_chunks(
    workspace_dir, khong_gian, policy
):
    """Chunk nằm ở hai kho khác cặp, và cặp đó cũng được đối chiếu.

    Id chunk ở kho KV và ở collection `chunks` là **cùng một chuỗi**, nên phép
    join không cần payload nào cả. Không đối chiếu cặp này thì chiều
    first-write-wins của đường KV (khoản nợ story 1.5) không có ai canh.
    """
    chunk = CHUNKS[0]

    async def chay():
        client = QdrantGhiLai()
        engine = dung_engine(workspace_dir, client, Neo4jGhiLai(), LLMGia())
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            await engine.khoi_tao()
            with dot_ingest() as so:
                with ingest_label(
                    scope=chunk["scope"], content_type=chunk["content_type"]
                ):
                    await engine.text_chunks.upsert(
                        {chunk["id"]: {"content": chunk["content"]}}
                    )
                    await engine.chunks_vdb.upsert(
                        {chunk["id"]: {"content": chunk["content"]}}
                    )
                truoc = await tim_lech(so, kho=kho_cua_engine(engine))
                # Siết khóa của bản ghi KV mà không đụng point vector: đúng
                # hình dạng lệch mà một lô ghi đứt giữa chừng để lại.
                engine.text_chunks._kho[khong_gian][chunk["id"]][
                    FILTER_KEY_FIELD
                ] = "noi_bo:bi_mat_ha_tang"
                sau = await tim_lech(so, kho=kho_cua_engine(engine))
        return truoc, sau

    truoc, sau = asyncio.run(chay())
    assert truoc == []
    assert [cap.id_join for cap in sau] == [chunk["id"]]
    assert set(sau[0].bao_cao) == {ten_kho_kv("text_chunks"), ten_kho_vector("chunks")}


def test_hai_kho_chuan_hoa_id_join_giong_nhau(workspace_dir, khong_gian, policy):
    """Kho KV và collection `chunks` phải cho ra **cùng một** id join.

    Hôm nay id chunk ở hai kho là cùng một chuỗi nên phép so vẫn chạy dù hai
    bên chuẩn hóa khác nhau - tức luật "dùng chung một phép chuẩn hóa" không có
    gì canh. Ca dưới đây dựng đúng chỗ hai bên lệch được: một id mang khoảng
    trắng thừa. Nếu kho KV ghi sổ id nguyên trạng còn kho vector ghi bản đã
    chuẩn hóa thì một mục thành **hai** id join, mỗi id một kho, và phép so
    giữa chúng biến mất im lặng - cộng với luật "kho kỳ vọng còn thiếu" thì nó
    thành một lệch giả ở mọi đợt, hoặc tệ hơn, một lệch thật không ai báo.
    """
    id_tho = '  chunk-can-chuan-hoa  '
    id_chuan = "chunk-can-chuan-hoa"

    async def chay():
        client = QdrantGhiLai()
        engine = dung_engine(workspace_dir, client, Neo4jGhiLai(), LLMGia())
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            await engine.khoi_tao()
            with dot_ingest() as so:
                with ingest_label(scope="noi_bo", content_type="runbook"):
                    await engine.text_chunks.upsert({id_tho: {"content": "x"}})
                    await engine.chunks_vdb.upsert({id_chuan: {"content": "x"}})
            return so

    so = asyncio.run(chay())
    assert so.cac_id() == [id_chuan], (
        "hai kho chuẩn hóa id join khác nhau nên một mục thành hai id join"
    )
    assert set(so.kho_cua(id_chuan)) == {
        ten_kho_kv("text_chunks"),
        ten_kho_vector("chunks"),
    }
    assert so.kho_thieu(id_chuan) == set()


def test_moi_hyperedge_cua_fixture_deu_vao_so(workspace_dir, khong_gian, policy):
    """Đợt phủ *mọi* id đã ghi, không phải một mẫu."""

    async def chay():
        with use_context(
            system_context(space=khong_gian, policy_version=policy.policy_version)
        ):
            _, so = await _nap_mot_dot(
                workspace_dir, khong_gian, policy, cac_he=HYPEREDGES
            )
            return set(so.cac_id())

    trong_so = asyncio.run(chay())
    ky_vong = {ten_hyperedge(he) for he in HYPEREDGES} | {
        gia_tri for he in HYPEREDGES for gia_tri in he["slots"].values()
    }
    assert trong_so == ky_vong
