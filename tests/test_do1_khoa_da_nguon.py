"""Đo 1 lớp (d): khóa của artifact đa nguồn, đo trên ngữ cảnh truy hồi thật.

Hai fixture mà epic-2 context gọi tên, dựng ở đây và chạy qua engine thật với
LLM/embedding giả:

- **nạp nhạy trước, thường sau** - bắt chiều last-writer-wins. Một entity vào
  từ tài liệu `bi_mat_ha_tang` rồi vào lại từ tài liệu `runbook` cùng scope;
  khóa của nó phải giữ hạng cao, và vai chỉ đạt L0 với `bi_mat_ha_tang` không
  được thấy nó ở bất kỳ đường nào.
- **hai scope chạm cùng entity** - entity vắng mặt tuyệt đối ở cả 3 collection
  vector, node graph ở lại không khóa.

Assert trên **ngữ cảnh truy hồi**, không bao giờ trên câu trả lời LLM (chốt
brief §6): `QueryParam(only_need_context=True)`. Bộ này chạy trong CI - không
mạng, không container, không key LLM.

Ba fixture hyperedge phụ dùng chung một `source_id` với chunk có sẵn: chunk
không phải thứ bộ này đo, và dựng thêm chunk chỉ để có `source_id` riêng là
thêm một mặt phải bảo trì mà không trả lời câu hỏi nào.
"""

import asyncio

import pytest

from adapters.doi_chieu import (
    KHO_GRAPH,
    StoreKeyMismatch,
    doi_chieu_dot,
    dot_ingest,
    kho_cua_engine,
    ten_kho_vector,
    tim_lech,
    van_tay,
)
from adapters.ingest_labels import ingest_label
from core.ids import point_id
from core.keys import CHUA_GHI, FILTER_KEY_FIELD, KHONG_KHOA, filter_key
from core.masking import dau_che_lan_can_khong_khoa
from core.permission import use_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.gia_lap_llm import LLMGia
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.gia_lap_qdrant import QdrantGhiLai
from tests.ho_tro_m1 import dung_engine, hoi
from tests.nap_kho import nap_ba_kho, nap_mot_hyperedge, ten_hyperedge
from tests.ngu_canh import ngu_canh_ingest, vai

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

# --- Fixture (d1): cùng scope, nhạy trước thường sau ----------------------
#
# `subject` khác nhau ở hai hyperedge nên tên hyperedge fixture
# (`{subject} - {loại}`) không mang giá trị entity dùng chung. Nếu để chúng
# trùng `subject` thì entity dùng chung *cũng* nằm trong tên hyperedge, và một
# assert "giá trị này không xuất hiện trong ngữ cảnh" sẽ đỏ vì tên fixture chứ
# không vì luật hợp nhất khóa - hai nguyên nhân khác nhau, một thông điệp.
# Đường trích xuất thật đã đóng lỗ `hyperedge_name` bằng id mờ ở story 2.4;
# fixture giữ tên riêng nên ghi chú này vẫn đúng cho nó.
KHOA_QUAN_TRI = "khóa quản trị cụm thanh toán xoay mỗi quý"

HE_NHAY = {
    "id": "HE-D1-NHAY",
    "source_id": "chunk-HE-03",
    "scope": "noi_bo",
    "content_type": "bi_mat_ha_tang",
    "slots": {
        "subject": "Quy trình xoay khóa quản trị",
        "remediation": KHOA_QUAN_TRI,
    },
}
HE_THUONG = {
    "id": "HE-D1-THUONG",
    "source_id": "chunk-HE-01",
    "scope": "noi_bo",
    "content_type": "runbook",
    "slots": {
        "subject": "Bàn giao ca trực App01",
        "remediation": KHOA_QUAN_TRI,
    },
}

# --- Fixture (d2): hai scope chạm cùng entity -----------------------------

QUY_TRINH_CHUNG = "giãn nhịp gọi API rồi mở lại theo quy trình chung"

HE_NOI_BO = {
    "id": "HE-D2-NOI-BO",
    "source_id": "chunk-HE-01",
    "scope": "noi_bo",
    "content_type": "runbook",
    "slots": {
        "subject": "Hàng đợi thanh toán nội bộ",
        "remediation": QUY_TRINH_CHUNG,
    },
}
HE_KHACH_A = {
    "id": "HE-D2-KHACH-A",
    "source_id": "chunk-HE-04",
    "scope": "khach_hang_a",
    "content_type": "bao_cao_su_co",
    "slots": {
        "subject": "Hàng đợi thanh toán khách hàng A",
        "remediation": QUY_TRINH_CHUNG,
    },
}


async def _dung_kho(workspace_dir, khong_gian, policy, them):
    """Engine đã nạp fixture chuẩn cộng các hyperedge phụ, theo đúng thứ tự."""
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    engine = dung_engine(workspace_dir, client, driver, LLMGia())
    await nap_ba_kho(engine, khong_gian=khong_gian, policy=policy, them=them)
    client.xoa_nhat_ky()
    return engine, client, driver


async def _khoa_o_ba_kho(engine, khong_gian, policy, gia_tri: str):
    """Khóa của một entity ở graph và ở cả ba collection vector.

    Hỏi mỗi collection bằng **id upstream của chính nó**, không phải bằng
    `ent-…` cho cả ba: `hyperedges` định danh bằng `rel-…` và `chunks` bằng
    chính id chunk, nên hỏi ba collection bằng một tiền tố là ba câu trả lời
    `CHUA_GHI` luôn đúng - một assert không đo gì. Ở đây id upstream của một
    entity ở `hyperedges`/`chunks` không tồn tại theo *thiết kế*, nên phép đo
    đúng là hỏi bằng point id: point của entity phải không có mặt ở đó.
    """
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        graph = await engine.chunk_entity_relation_graph.khoa_hien_co([gia_tri])
        entities = (await engine.entities_vdb.khoa_hien_co([f"ent-{gia_tri}"]))[
            f"ent-{gia_tri}"
        ]
    return graph[gia_tri], entities


async def _point_con_lai(client, khong_gian, id_upstream: str) -> dict[str, list]:
    """Point mang `point_id(id_upstream)` còn sót ở từng collection vector.

    Hỏi thẳng bằng point id: đó là phép đo duy nhất trả lời được "vắng mặt
    tuyệt đối", vì một truy vấn *có filter* vẫn trả rỗng cho một point mang
    khóa lạ mà chưa vai nào được cấp.
    """
    pid = point_id(id_upstream)
    con_lai = {}
    for namespace in ("entities", "hyperedges", "chunks"):
        ban_ghi = await client.retrieve(
            collection_name=f"{khong_gian}_{namespace}", ids=[pid]
        )
        con_lai[namespace] = list(ban_ghi)
    return con_lai


# --- (d1) nạp nhạy trước, thường sau --------------------------------------


@pytest.mark.parametrize(
    "thu_tu",
    [(HE_NHAY, HE_THUONG), (HE_THUONG, HE_NHAY)],
    ids=["nhay_truoc_thuong_sau", "thuong_truoc_nhay_sau"],
)
def test_entity_da_nguon_giu_hang_cao_du_thu_tu_nao(
    workspace_dir, khong_gian, policy, thu_tu
):
    """Khóa của entity đa nguồn là hạng cao nhất, không phải khóa lần ghi cuối.

    Chạy cả hai thứ tự nạp và đòi cùng một kết quả. Đó mới là điều làm cho một
    đợt ingest chạy lại cho ra cùng một kho, và là thứ mà last-write-wins không
    có: với nó, `uv run pytest` xanh hay đỏ phụ thuộc thư mục tài liệu được
    duyệt theo thứ tự nào.
    """

    async def chay():
        engine, client, _ = await _dung_kho(workspace_dir, khong_gian, policy, thu_tu)
        khoa_graph, khoa_entities = await _khoa_o_ba_kho(
            engine, khong_gian, policy, KHOA_QUAN_TRI
        )
        con_lai = await _point_con_lai(
            client, khong_gian, f"ent-{KHOA_QUAN_TRI}"
        )
        return khoa_graph, khoa_entities, con_lai

    khoa_graph, khoa_entities, con_lai = asyncio.run(chay())
    nhay = filter_key("noi_bo", "bi_mat_ha_tang")
    assert khoa_graph == nhay
    assert khoa_entities == nhay
    # Point của entity chỉ nằm ở `entities`, và nó *có* ở đó với đúng khóa hợp
    # nhất. Hai collection kia không có point nào mang point id ấy - đo bằng
    # chính point id, chứ hỏi chúng bằng id `ent-…` thì câu trả lời `CHUA_GHI`
    # luôn đúng và không chứng minh được gì.
    assert len(con_lai["entities"]) == 1
    assert con_lai["entities"][0].payload[FILTER_KEY_FIELD] == nhay
    assert con_lai["hyperedges"] == [] and con_lai["chunks"] == []


def test_vai_khong_dat_muc_khong_thay_entity_da_nguon_trong_ngu_canh(
    workspace_dir, khong_gian, policy
):
    """Đo trên ngữ cảnh truy hồi: `tech_support` không nhận giá trị nhạy.

    `tech_support` đạt L2 với `runbook` và L0 với `bi_mat_ha_tang`. Entity dùng
    chung vào hệ từ cả hai loại; nếu khóa của nó là khóa của lần ghi cuối
    (runbook) thì nó nằm trong `allowed_keys["entities"]` của vai và đi thẳng
    vào bảng Entities của ngữ cảnh. Hợp nhất theo hạng cao nhất đóng đường đó.

    `devops` đạt L1 với `bi_mat_ha_tang` nên nó *thấy* hyperedge nhạy - đối
    chứng để test không xanh chỉ vì fixture không bao giờ được truy hồi.
    """

    async def chay():
        engine, _, _ = await _dung_kho(
            workspace_dir, khong_gian, policy, (HE_NHAY, HE_THUONG)
        )
        # Câu hỏi mặc định của cổng M1: từ khóa mà `kg_query` đem đi embed là
        # từ khóa do LLM giả trả về, không phải chuỗi câu hỏi, và embedding giả
        # cho cosine gần nhau với mọi chuỗi. Nên tập kết quả do *bộ lọc quyền*
        # quyết định - đúng thứ bộ này đo. Truyền một câu hỏi "trúng" giá trị
        # nhạy chỉ tạo cảm giác là nội dung câu hỏi có vai trò.
        return {
            ten_vai: await hoi(engine, vai(policy, ten_vai, khong_gian))
            for ten_vai in ("tech_support", "devops")
        }

    ngu_canh = asyncio.run(chay())
    assert KHOA_QUAN_TRI not in ngu_canh["tech_support"]
    assert HE_NHAY["slots"]["subject"] not in ngu_canh["tech_support"]
    # Đối chứng đặt trên **chính giá trị đang đo**, không trên `subject`. Với
    # `devops` thì `bi_mat_ha_tang` ở mức L1 và bảng chính sách khai
    # `masked_slots: [source, remediation]`, nên `KHOA_QUAN_TRI` (nằm ở slot
    # `remediation`) bị *che* chứ không ra nguyên văn - tức không vai nào từng
    # thấy nó, và một assert kiểu "devops thấy nó" sẽ đỏ vì lý do sai. Đối
    # chứng đúng là: entity ấy *có* trong tầm với của `devops` qua chính
    # hyperedge nhạy, và dấu che của slot đó có mặt trong ngữ cảnh.
    assert HE_NHAY["slots"]["subject"] in ngu_canh["devops"], (
        "hyperedge nhạy phải truy hồi được với devops, nếu không test này xanh"
        " vì fixture không bao giờ được truy hồi"
    )
    assert oracle.dau_che_ky_vong("remediation") in ngu_canh["devops"], (
        "giá trị nằm ở slot bị che của devops nên phải thấy dấu che, không phải"
        " thấy nguyên văn và cũng không phải vắng hẳn"
    )


# --- (d2) hai scope chạm cùng entity --------------------------------------


def test_entity_hai_scope_vang_mat_tuyet_doi_o_ca_ba_collection(
    workspace_dir, khong_gian, policy
):
    """Không khóa nghĩa là point không tồn tại, không phải mang một khóa lạ.

    Kiểm bằng chính point id (UUID5 của id upstream) trên cả ba collection, chứ
    không bằng một truy vấn có filter: một khóa đặc biệt kiểu `"__none__"` vẫn
    vắng mặt trong mọi truy vấn *có filter* cho tới ngày một vai vô ý được cấp
    nó. Điều phải đúng là point không có ở đó.
    """

    async def chay():
        engine, client, driver = await _dung_kho(
            workspace_dir, khong_gian, policy, (HE_NOI_BO, HE_KHACH_A)
        )
        pid = point_id(f"ent-{QUY_TRINH_CHUNG}")
        con_lai = {}
        for namespace in ("entities", "hyperedges", "chunks"):
            ban_ghi = await client.retrieve(
                collection_name=f"{khong_gian}_{namespace}", ids=[pid]
            )
            con_lai[namespace] = list(ban_ghi)
        node = driver.node_tho(khong_gian, QUY_TRINH_CHUNG)
        return con_lai, node

    con_lai, node = asyncio.run(chay())
    assert con_lai == {"entities": [], "hyperedges": [], "chunks": []}
    # Node cấu trúc ở lại, không khóa: xóa nó là cắt cả hai hyperedge hợp lệ
    # nối vào, trong khi cái phải mất là *đường tới* nó với mọi vai.
    assert node is not None
    assert "filter_key" not in node.props


def test_entity_hai_scope_vo_hinh_voi_moi_vai_tren_ngu_canh_truy_hoi(
    workspace_dir, khong_gian, policy
):
    """Cả vai hẹp lẫn vai chạm *cả hai* scope đều không nhận **giá trị** đó.

    `devops` chạm cả `noi_bo` lẫn `khach_hang_a`, nên nếu "không khóa" được cài
    bằng một chuỗi khóa đặc biệt nào đó thì đây là vai nhìn thấy nó. Vô hình
    với mọi vai nghĩa là vô hình cả với vai rộng nhất.

    Hai hyperedge chứa nó thì *vẫn* truy hồi được theo đúng quyền của chúng -
    cái mất là một giá trị slot, không phải cả fact.

    **Kỳ vọng siết lại 02/09/2026.** Bản đầu chỉ khẳng định nguyên văn vắng
    mặt, và câu đó đúng dưới *cả hai* cách đọc của phần frozen - kể cả cách đọc
    (b) mà story đã cài nhầm, nơi lân cận không khóa biến mất hẳn khỏi danh
    sách cạnh. Nói cách khác nó không phân biệt được "che" với "mất", tức nó
    không đo được thứ AD-9 chốt. Nay assert thêm rằng **dấu che có mặt**: vai
    biết có một fact ở đó mà nó không được đọc (FR-12). Ca đầy đủ của AD-5 nằm
    ở `test_duyet_qua_entity_khac_scope_thi_ten_bi_che_cung`; ở đây chỉ đóng lỗ
    của chính assert này.
    """

    async def chay():
        engine, _, _ = await _dung_kho(
            workspace_dir, khong_gian, policy, (HE_NOI_BO, HE_KHACH_A)
        )
        return {
            ten_vai: await hoi(engine, vai(policy, ten_vai, khong_gian))
            for ten_vai in ("tech_support", "devops")
        }

    ngu_canh = asyncio.run(chay())
    for ten_vai, chuoi in ngu_canh.items():
        assert QUY_TRINH_CHUNG not in chuoi, ten_vai
        assert dau_che_lan_can_khong_khoa() in chuoi, (
            f"{ten_vai}: giá trị vắng mặt nhưng dấu che cũng vắng - không phân"
            " biệt được 'đã che' với 'mất hẳn cạnh'"
        )
    assert HE_NOI_BO["slots"]["subject"] in ngu_canh["devops"]
    assert HE_KHACH_A["slots"]["subject"] in ngu_canh["devops"]
    # `tech_support` không chạm scope `khach_hang_a`: biên cách ly khách hàng
    # của RT-01 vẫn đứng, luật hợp nhất không nới nó ra.
    assert HE_KHACH_A["slots"]["subject"] not in ngu_canh["tech_support"]


def test_duyet_qua_entity_khac_scope_thi_ten_bi_che_cung(
    workspace_dir, khong_gian, policy
):
    """Ca Đo 1 mà AD-5 đòi: duyệt qua một entity khác scope.

    > node entity không khóa chỉ đạt tới được qua hyperedge đã lọc và tên luôn
    > bị che cứng qua tầng AD-9 (có test Đo 1 cho ca duyệt qua entity khác
    > scope) - ARCHITECTURE-SPINE, AD-5

    Hai vế, và cả hai đều phải đúng:

    - **dấu che có mặt** (FR-12): vai biết có một fact ở đó mà nó không được
      đọc. Mất hẳn cạnh thì hyperedge trông như thiếu hẳn một slot, và đó là
      một khẳng định sai về dữ liệu;
    - **nguyên văn tên entity vắng mặt** khỏi *toàn bộ* chuỗi ngữ cảnh, không
      chỉ khỏi bảng Relationships.

    `tech_support` đạt L2 với `runbook` nên nó thấy `HE_NOI_BO`, và
    `QUY_TRINH_CHUNG` là lân cận của chính hyperedge ấy - nhưng entity đó cũng
    xuất hiện trong `HE_KHACH_A` thuộc scope `khach_hang_a`, nên nó đã hợp nhất
    ra "không khóa". Đúng hình dạng "duyệt qua entity khác scope".
    """

    async def chay():
        engine, _, _ = await _dung_kho(
            workspace_dir, khong_gian, policy, (HE_NOI_BO, HE_KHACH_A)
        )
        ngu_canh = {
            ten_vai: await hoi(engine, vai(policy, ten_vai, khong_gian))
            for ten_vai in ("tech_support", "devops")
        }
        # Đo thẳng ở tầng adapter nữa: chuỗi ngữ cảnh đi qua nhiều bước cắt
        # theo ngân sách token, nên một assert chỉ trên chuỗi có thể xanh vì
        # mục đó bị cắt chứ không vì cơ chế đúng.
        lan_can = {}
        for ten_vai in ("tech_support", "devops"):
            with use_context(vai(policy, ten_vai, khong_gian)):
                lan_can[ten_vai] = [
                    c[1]
                    for c in await engine.chunk_entity_relation_graph.get_node_edges(
                        ten_hyperedge(HE_NOI_BO)
                    )
                ]
        return ngu_canh, lan_can

    ngu_canh, lan_can = asyncio.run(chay())
    dau = dau_che_lan_can_khong_khoa()

    for ten_vai in ("tech_support", "devops"):
        # Vế 1: cạnh còn đó, tên thay bằng dấu che - không mất hẳn lân cận.
        assert dau in lan_can[ten_vai], (
            f"{ten_vai}: lân cận không khóa biến mất khỏi danh sách cạnh, nên"
            " hyperedge trông như thiếu hẳn một slot"
        )
        # Vế 2: nguyên văn không ở bất kỳ đâu trong ngữ cảnh truy hồi.
        assert QUY_TRINH_CHUNG not in lan_can[ten_vai], ten_vai
        assert QUY_TRINH_CHUNG not in ngu_canh[ten_vai], ten_vai
        assert dau in ngu_canh[ten_vai], (
            f"{ten_vai}: dấu che không tới được chuỗi ngữ cảnh, nên người dùng"
            " không biết có một fact bị giấu ở đó (FR-12)"
        )

    # Lân cận *có* khóa của cùng hyperedge vẫn ra nguyên văn: cửa nới chỉ mở
    # cho node không khóa, không mở cho mọi node.
    assert HE_NOI_BO["slots"]["subject"] in lan_can["tech_support"]


def test_che_cung_khong_phu_thuoc_muc_tiet_lo(workspace_dir, khong_gian, policy):
    """"Che cứng với mọi vai" nghĩa là không phụ thuộc bảng chính sách.

    Chạy lại cùng ca trên bảng nhị phân của Đo 3 (`L1 -> L0`), nơi mọi mức tiết
    lộ đổi. Nếu luật che này là một hàng trong bảng thì kết quả đổi theo; nó là
    luật AD-9 nên kết quả không đổi. Cùng hình dạng với luật `owner` (che ở mọi
    mức), và đó là lý do lý do che là một hằng chứ không phải một vai slot.
    """
    from adapters.policy_loader import load_policy

    policy_nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)

    async def chay():
        engine, _, _ = await _dung_kho(
            workspace_dir, khong_gian, policy_nhi_phan, (HE_NOI_BO, HE_KHACH_A)
        )
        with use_context(vai(policy_nhi_phan, "devops", khong_gian)):
            return [
                c[1]
                for c in await engine.chunk_entity_relation_graph.get_node_edges(
                    ten_hyperedge(HE_NOI_BO)
                )
            ]

    lan_can = asyncio.run(chay())
    assert dau_che_lan_can_khong_khoa() in lan_can
    assert QUY_TRINH_CHUNG not in lan_can


def test_dau_che_lan_can_tra_nguoc_duoc_qua_get_node(
    workspace_dir, khong_gian, policy
):
    """Dấu che mới đi vào **vị trí id**, nên `get_node` phải nhận ra nó.

    Landmine đã gỡ một lần ở story 1.6 cho dấu che theo slot:
    `operate.py:1024-1047` gom `e[1]` của `get_node_edges` rồi gọi
    `get_node(entity_name)` và trải `{**n, ...}` **không lọc `None`**. Một dấu
    che mới mà `la_dau_che` không nhận ra thì `get_node` trả `None` và nhánh
    global nổ `TypeError` sâu trong `vendor/`.
    """

    async def chay():
        engine, _, _ = await _dung_kho(
            workspace_dir, khong_gian, policy, (HE_NOI_BO, HE_KHACH_A)
        )
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await engine.chunk_entity_relation_graph.get_node(
                dau_che_lan_can_khong_khoa()
            )

    node = asyncio.run(chay())
    assert node is not None, "dấu che không tra ngược được, nhánh global sẽ nổ"
    assert node["description"] == dau_che_lan_can_khong_khoa()


def test_ca_khong_khoa_khong_lam_hai_kho_lech(workspace_dir, khong_gian, policy):
    """Bước đối chiếu của chính đợt nạp phải xanh với ca không khóa.

    `nap_ba_kho` chạy `doi_chieu_dot` ở cuối đợt và không có cờ tắt, nên test
    này đã xanh từ lúc fixture nạp xong. Chạy lại phép so một lần nữa ở đây để
    khẳng định nó *đo được* trạng thái sau đợt, chứ không chỉ đúng lúc đợt
    còn mở.
    """

    async def chay():
        engine, _, _ = await _dung_kho(
            workspace_dir, khong_gian, policy, (HE_NOI_BO, HE_KHACH_A)
        )
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            khoa_graph = await engine.chunk_entity_relation_graph.khoa_hien_co(
                [QUY_TRINH_CHUNG]
            )
            khoa_vector = await engine.entities_vdb.khoa_hien_co(
                [f"ent-{QUY_TRINH_CHUNG}"]
            )
        return khoa_graph[QUY_TRINH_CHUNG], khoa_vector[f"ent-{QUY_TRINH_CHUNG}"]

    khoa_graph, khoa_vector = asyncio.run(chay())
    assert khoa_graph is KHONG_KHOA
    # Story 2.3: sổ không khóa của kho vector nhớ trạng thái, không còn `CHUA_GHI`.
    assert khoa_vector is KHONG_KHOA


def test_nap_lai_lan_ba_van_khong_khoa_o_ca_hai_kho_va_doi_chieu_sach(
    workspace_dir, khong_gian, policy
):
    """Trạng thái hút sống qua lần nạp thứ ba ở **cả hai** kho; đợt sạch.

    Đổi kỳ vọng ở story 2.3. Bản 2.1 của test này
    (`test_nap_lai_lan_ba_lam_hai_kho_lech_va_buoc_doi_chieu_bat_duoc`) ghim
    rằng kho vector cấp lại khóa cho point vì nó không phân biệt được "vắng"
    với "không khóa", và bước đối chiếu bắt phần lệch. Nay kho vector giữ sổ
    không khóa bền vững theo space, nên lần nạp thứ ba cùng scope với lần đầu
    vẫn ra không khóa ở cả hai kho, point vẫn vắng mặt, và đợt không lệch.
    """

    async def chay():
        # Ba lần *nạp*, nhưng chỉ hai hyperedge: `HE_NOI_BO` đi qua `them=`
        # một lần rồi được nạp lại tường minh, vì `kiem_fixture()` cấm hai
        # hyperedge trùng tên trong cùng một danh sách (chúng sẽ dùng chung một
        # node graph).
        engine, client, driver = await _dung_kho(
            workspace_dir, khong_gian, policy, (HE_NOI_BO, HE_KHACH_A)
        )
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with dot_ingest() as so:
                with ingest_label(
                    scope=HE_NOI_BO["scope"],
                    content_type=HE_NOI_BO["content_type"],
                ):
                    await nap_mot_hyperedge(engine, HE_NOI_BO)
                await doi_chieu_dot(so, kho=kho_cua_engine(engine))
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            khoa_graph = await engine.chunk_entity_relation_graph.khoa_hien_co(
                [QUY_TRINH_CHUNG]
            )
            khoa_vector = await engine.entities_vdb.khoa_hien_co(
                [f"ent-{QUY_TRINH_CHUNG}"]
            )
        so_point = await client.dem_point(f"{khong_gian}_entities")
        return khoa_graph[QUY_TRINH_CHUNG], khoa_vector[f"ent-{QUY_TRINH_CHUNG}"], so_point

    khoa_graph, khoa_vector, so_point = asyncio.run(chay())
    assert khoa_graph is KHONG_KHOA and khoa_vector is KHONG_KHOA
    # Point của entity không khóa vẫn vắng; các entity khác của hai hyperedge
    # vẫn có mặt (nên số point không phải 0).
    assert so_point > 0


def test_hai_fixture_khong_lam_lech_phan_con_lai_cua_kho(
    workspace_dir, khong_gian, policy
):
    """Bộ fixture chuẩn cộng cả hai ca (d) vẫn cho hai kho khớp nhau."""

    async def chay():
        engine, _, _ = await _dung_kho(
            workspace_dir,
            khong_gian,
            policy,
            (HE_NHAY, HE_THUONG, HE_NOI_BO, HE_KHACH_A),
        )
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with dot_ingest() as so:
                for gia_tri in (KHOA_QUAN_TRI, QUY_TRINH_CHUNG):
                    so.ghi(
                        id_join=gia_tri,
                        kho=KHO_GRAPH,
                        id_trong_kho=gia_tri,
                        kho_doi=ten_kho_vector("entities"),
                    )
                    so.ghi(
                        id_join=gia_tri,
                        kho=ten_kho_vector("entities"),
                        id_trong_kho=f"ent-{gia_tri}",
                        kho_doi=KHO_GRAPH,
                    )
                return await tim_lech(so, kho=kho_cua_engine(engine))

    assert asyncio.run(chay()) == []
