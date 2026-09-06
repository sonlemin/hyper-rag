"""Adapter KV: kho trên đĩa, cách ly và danh mục namespace (story 1.5).

Nửa thứ hai của bộ test story 1.5; nửa đầu (`1.5-INT-001`, `1.5-INT-002`, hai
cửa ghi) nằm ở `tests/test_adapter_kv.py`. Tách ra khi file gốc vượt ngưỡng
1000 dòng.

Phần này ghim những thứ chỉ lộ ra khi có đĩa thật trong ảnh: ghi nguyên tử
không sót file tạm, file kho hỏng cho mã lỗi của dự án, tên file mang cả
`space` lẫn `namespace`, cộng luật hợp nhất khóa đa nguồn của story 2.1 trên
chính đường ghi này.

Kho là file JSON trong thư mục tạm nên bộ này không cần mạng, không cần
container, không cần key LLM.
"""

import asyncio
import json

import pytest

from adapters.ingest_labels import IngestOutsideSystemContext, ingest_label
from adapters.kv import (
    ENABLE_LLM_CACHE,
    KV_NAMESPACES,
    KV_PERMISSION_NAMESPACE,
    LLM_CACHE_NAMESPACE,
    KVNamespaceInvalid,
    KVStoreCorrupt,
    LLMCacheDisabled,
    RecordFilterKeyMissing,
)
from adapters.policy_loader import load_policy
from core.keys import (
    CHUA_GHI,
    FILTER_KEY_FIELD,
    SensitivityRankUnknown,
    filter_key,
)
from core.masking import MASKED_READ_METHODS
from core.permission import use_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, TAI_LIEU_GOC
from tests.ho_tro_kv import con_lai_file_tam, dung_adapter, kho_da_nap, nap
from tests.ngu_canh import ngu_canh_ingest, vai


# --- Ghi xuống đĩa: nguyên tử, không sót file tạm ---------------------------


def test_ghi_xuong_dia_khong_sot_file_tam(workspace_dir, khong_gian, policy):
    """Đường chạy đúng: file kho đủ nội dung, không còn file tạm nào."""

    async def chay():
        await kho_da_nap(workspace_dir, khong_gian, policy)

    asyncio.run(chay())
    assert con_lai_file_tam(workspace_dir) == []
    duong_dan = workspace_dir / f"kv_store_{khong_gian}_text_chunks.json"
    assert set(json.loads(duong_dan.read_text(encoding="utf-8"))) == {
        c["id"] for c in CHUNKS
    }


def test_ghi_dut_giua_chung_khong_pha_kho_cu(workspace_dir, khong_gian, policy):
    """File kho là nơi *duy nhất* giữ khóa quyền, nên ghi phải nguyên tử.

    Đè thẳng lên file thật mà đứt giữa chừng là mất cả kho đã gắn nhãn, và
    kho cụt đó không nói được nó cụt. Ghi ra file tạm rồi `os.replace`: hoặc
    file cũ còn nguyên, hoặc file mới đã đủ, không có trạng thái thứ ba.
    """

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                # `set` không serialize được: `json.dump` nổ giữa lúc ghi file
                # tạm, sau khi file tạm đã được tạo.
                await adapter.upsert({"chunk-hong": {"content": {"không", "json"}}})
        with pytest.raises(TypeError):
            await adapter.index_done_callback()

    asyncio.run(chay())
    assert con_lai_file_tam(workspace_dir) == [], "sót file tạm: một kho ma"
    duong_dan = workspace_dir / f"kv_store_{khong_gian}_text_chunks.json"
    tren_dia = json.loads(duong_dan.read_text(encoding="utf-8"))
    assert set(tren_dia) == {c["id"] for c in CHUNKS}, "kho cũ bị phá"


# --- File kho hỏng, bản ghi không khóa --------------------------------------


@pytest.mark.parametrize(
    "noi_dung,mo_ta",
    [
        ("{ khong phai json", "json_hong"),
        ('["mot", "danh", "sach"]', "goc_khong_phai_dict"),
        ('{"chunk-x": "mot chuoi tran"}', "ban_ghi_khong_phai_dict"),
    ],
    ids=["json_hong", "goc_khong_phai_dict", "ban_ghi_khong_phai_dict"],
)
def test_file_kho_hong_cho_ma_loi_cua_du_an(
    workspace_dir, khong_gian, policy, noi_dung, mo_ta
):
    """File kho hỏng nổ bằng mã lỗi của dự án, không phải lỗi thô từ `vendor/`."""
    adapter = dung_adapter(workspace_dir)
    duong_dan = adapter._duong_dan(khong_gian)
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    duong_dan.write_text(noi_dung, encoding="utf-8")

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            await adapter.get_by_id("chunk-x")

    with pytest.raises(KVStoreCorrupt) as loi:
        asyncio.run(chay())
    assert loi.value.code == "KV_STORE_CORRUPT"


@pytest.mark.parametrize(
    "goi",
    [
        lambda a: a.get_by_id("chunk-lac"),
        lambda a: a.get_by_ids(["chunk-lac"]),
        lambda a: a.all_keys(),
        lambda a: a.filter_keys(["chunk-lac"]),
    ],
    ids=["get_by_id", "get_by_ids", "all_keys", "filter_keys"],
)
def test_ban_ghi_khong_khoa_bi_tu_choi_o_moi_method_doc(
    workspace_dir, khong_gian, policy, goi
):
    """Mục ghi thẳng vào file không qua adapter: từ chối, ở *mọi* đường đọc.

    Cùng luật với `PointFilterKeyMissing` của đường vector: một bản ghi không
    tra được khóa quyền thì không che được, và "không che gì" chính là mặc
    định fail-open mà cả epic này dựng ra để chống. `all_keys`/`filter_keys`
    cũng tra khóa, nên chúng phải nổ cùng một kiểu chứ không âm thầm bỏ qua.
    """
    adapter = dung_adapter(workspace_dir)
    duong_dan = adapter._duong_dan(khong_gian)
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    duong_dan.write_text(
        json.dumps({"chunk-lac": {"content": "ghi tay, không có khóa"}}),
        encoding="utf-8",
    )

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            await goi(adapter)

    with pytest.raises(RecordFilterKeyMissing) as loi:
        asyncio.run(chay())
    assert loi.value.code == "RECORD_FILTER_KEY_MISSING"


def test_ban_ghi_khong_khoa_cung_ma_loi_o_ca_hai_namespace(
    workspace_dir, khong_gian, policy
):
    """Mã lỗi là hợp đồng test assert lên, nên nó phải đúng cho cả hai kho."""

    async def chay(namespace):
        adapter = dung_adapter(workspace_dir, namespace)
        duong_dan = adapter._duong_dan(khong_gian)
        duong_dan.parent.mkdir(parents=True, exist_ok=True)
        duong_dan.write_text(json.dumps({"muc-lac": {"content": "x"}}), encoding="utf-8")
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(RecordFilterKeyMissing) as loi:
                await adapter.get_by_id("muc-lac")
        return loi.value.code

    ma_chunks = asyncio.run(chay("text_chunks"))
    ma_docs = asyncio.run(chay("full_docs"))
    assert ma_chunks == ma_docs == "RECORD_FILTER_KEY_MISSING"


# --- Cách ly space và cách ly namespace -------------------------------------


def test_hai_khong_gian_khong_doc_duoc_cua_nhau(workspace_dir, policy, session_prefix):
    """Cách ly `space` (AD-12): `space` tính theo lời gọi, không ghim lúc dựng.

    Một instance adapter phục vụ nhiều không gian, đúng cách `_ten_collection`
    của adapter Qdrant tính tên collection. Không có luật này thì khoang
    `synth` và khoang `real` (story 2.11) dùng chung một file chunk.

    Đọc lại bằng một instance mới sau khi đã ghi xuống đĩa, không chỉ đọc từ
    bộ nhớ: bộ nhớ tách theo `space` sẵn rồi, nên một adapter gấp thiếu `space`
    vào *tên file* vẫn qua được phép thử trong bộ nhớ. Chỗ hai không gian thật
    sự trộn vào nhau là trên đĩa.
    """
    a = f"{session_prefix}_synth"
    b = f"{session_prefix}_real"

    async def chay():
        nap_vao = dung_adapter(workspace_dir)
        await nap(nap_vao, a, policy, CHUNKS)
        await nap_vao.index_done_callback()

        doc_ra = dung_adapter(workspace_dir)
        with use_context(vai(policy, "devops", b)):
            trong_b = await doc_ra.get_by_id("chunk-HE-01")
            khoa_b = await doc_ra.all_keys()
        with use_context(vai(policy, "devops", a)):
            trong_a = await doc_ra.get_by_id("chunk-HE-01")
        return trong_a, trong_b, khoa_b, doc_ra

    trong_a, trong_b, khoa_b, doc_ra = asyncio.run(chay())
    assert trong_a is not None
    assert trong_b is None
    assert khoa_b == []
    # Tên file mang `space`, nên hai khoang là hai file chứ không phải hai
    # nhánh trong cùng một file.
    assert doc_ra._duong_dan(a) != doc_ra._duong_dan(b)
    assert a in doc_ra._duong_dan(a).name and b in doc_ra._duong_dan(b).name


def test_hai_namespace_trong_cung_thu_muc_khong_tron(
    workspace_dir, khong_gian, policy
):
    """`text_chunks` và `full_docs` cùng `space`, cùng thư mục: hai file rời nhau.

    Upstream dựng cả hai kho trong một `working_dir` (`hypergraphrag.py:208,213`),
    nên tên file phải mang cả `namespace`. Thiếu nó thì kho nạp sau đè kho nạp
    trước, và một nửa dữ liệu biến mất im lặng.
    """

    async def chay():
        chunks = dung_adapter(workspace_dir, "text_chunks")
        docs = dung_adapter(workspace_dir, "full_docs")
        await nap(chunks, khong_gian, policy, CHUNKS)
        await nap(docs, khong_gian, policy, TAI_LIEU_GOC)
        await chunks.index_done_callback()
        await docs.index_done_callback()

        doc_chunks = dung_adapter(workspace_dir, "text_chunks")
        doc_docs = dung_adapter(workspace_dir, "full_docs")
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return (
                await doc_chunks.all_keys(),
                await doc_docs.all_keys(),
                doc_chunks._duong_dan(khong_gian),
                doc_docs._duong_dan(khong_gian),
            )

    id_chunks, id_docs, duong_chunks, duong_docs = asyncio.run(chay())
    assert id_chunks == [c["id"] for c in CHUNKS]
    assert id_docs == [d["id"] for d in TAI_LIEU_GOC]
    assert not set(id_chunks) & set(id_docs)
    assert duong_chunks != duong_docs


# --- `all_keys` và `filter_keys`: vắng mặt im lặng lan tới đâu --------------


@pytest.mark.parametrize("ten_vai", ["devops", "tech_support"])
def test_all_keys_theo_quyen(workspace_dir, khong_gian, policy, bang, ten_vai):
    """`all_keys` chỉ kể id mà vai đạt L2: "có tồn tại không" cũng là rò."""

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, ten_vai, khong_gian)):
            return await adapter.all_keys()

    assert asyncio.run(chay()) == oracle.chunk_thay_duoc(bang, ten_vai, CHUNKS)


def test_filter_keys_tinh_muc_ngoai_quyen_la_chua_ton_tai(
    workspace_dir, khong_gian, policy, bang
):
    """`filter_keys` trả tập id *chưa* tồn tại; ngoài quyền tính là chưa tồn tại.

    Trả lời trung thực "id này đã có trong kho" cho một vai không được đọc nó
    là kể ra rằng fact đó tồn tại, và trên đường ingest nó còn khiến một tài
    liệu bị bỏ qua vì tưởng đã nạp.
    """
    hoi = [c["id"] for c in CHUNKS] + ["chunk-KHONG-TON-TAI"]

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.filter_keys(hoi)

    thay_duoc = set(oracle.chunk_thay_duoc(bang, "tech_support", CHUNKS))
    assert asyncio.run(chay()) == set(hoi) - thay_duoc


def test_filter_keys_duoi_ngu_canh_he_thong_thay_het(workspace_dir, khong_gian, policy):
    """Ingest đọc thô: chỉ id thật sự chưa có mới nằm trong tập trả về."""

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await adapter.filter_keys([c["id"] for c in CHUNKS] + ["chunk-moi"])

    assert asyncio.run(chay()) == {"chunk-moi"}


# --- `full_docs` dùng chung ngưỡng với `text_chunks` ------------------------


@pytest.mark.parametrize("ten_vai", ["devops", "tech_support"])
def test_full_docs_cung_nguong_voi_text_chunks(
    workspace_dir, khong_gian, policy, bang, ten_vai
):
    """Nguyên văn tài liệu ít nhất ngang chunk cắt ra từ nó (NFR-06).

    Hai namespace, một ngưỡng: đưa `full_docs` về cùng luật giữ cho không có
    hai cách tính quyền cho cùng một loại nội dung.
    """

    async def chay():
        adapter = dung_adapter(workspace_dir, namespace="full_docs")
        await nap(adapter, khong_gian, policy, TAI_LIEU_GOC)
        with use_context(vai(policy, ten_vai, khong_gian)):
            return await adapter.all_keys()

    assert asyncio.run(chay()) == oracle.chunk_thay_duoc(bang, ten_vai, TAI_LIEU_GOC)


# --- Đổi bảng chính sách, không sửa code ------------------------------------


@pytest.mark.parametrize("ten_vai", ["devops", "tech_support"])
def test_doi_bang_chinh_sach_khong_sua_code(workspace_dir, khong_gian, ten_vai):
    """Baseline nhị phân `L1 -> L0` của Đo 3 (brief §6 chốt 3, FR-28).

    Trỏ loader sang file khác là đổi cấu hình. Trên đường KV, hai bảng cho
    *cùng* một tập chunk, và đó chính là điều đáng ghim: ngưỡng của kho này đã
    là L2 nên việc hạ L1 xuống L0 không đổi được gì ở đây, trong khi tập
    hyperedge thì đổi. Nếu một ngày tập chunk đổi theo bảng nhị phân thì hoặc
    ngưỡng đã trôi khỏi L2, hoặc adapter đã bắt đầu đọc bảng chính sách.
    """
    bang_nhi_phan = oracle.doc_bang_chinh_sach(oracle.POLICY_NHI_PHAN)
    bang_day_du = oracle.doc_bang_chinh_sach(oracle.POLICY_DAY_DU)
    policy_nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)
    policy_day_du = load_policy(oracle.POLICY_DAY_DU)

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy_day_du)
        with use_context(vai(policy_nhi_phan, ten_vai, khong_gian)):
            return await adapter.all_keys()

    assert asyncio.run(chay()) == oracle.chunk_thay_duoc(
        bang_nhi_phan, ten_vai, CHUNKS
    )
    # Hai bảng đồng ý ở ngưỡng chunk...
    assert oracle.chunk_thay_duoc(bang_nhi_phan, ten_vai, CHUNKS) == (
        oracle.chunk_thay_duoc(bang_day_du, ten_vai, CHUNKS)
    )
    # ...và bất đồng ở ngưỡng hyperedge, nên phép thử không rỗng nghĩa.
    assert oracle.hyperedge_thay_duoc(bang_nhi_phan, ten_vai, HYPEREDGES) != (
        oracle.hyperedge_thay_duoc(bang_day_du, ten_vai, HYPEREDGES)
    )


# --- Danh mục namespace và hằng cấu hình ------------------------------------


def test_namespace_cache_co_lop_loi_rieng(workspace_dir):
    """Namespace cache không rơi vào lỗi chung của danh mục: nó có lý do riêng.

    Góc kiểm ở đây là *phân loại lỗi*. Góc "cache LLM tắt hai lớp" nằm ở
    `tests/test_cache_llm_tat.py`, cùng với lý do (khóa cache không mang vai).
    """
    with pytest.raises(LLMCacheDisabled) as loi:
        dung_adapter(workspace_dir, namespace=LLM_CACHE_NAMESPACE)
    assert loi.value.code == "LLM_CACHE_DISABLED"
    assert not isinstance(loi.value, KVNamespaceInvalid)


@pytest.mark.parametrize(
    "namespace",
    ["bat_ky_gi", "chunks", "../thoat-ra", "..", "text_chunks/../../etc"],
    ids=["la", "gan_giong", "thoat_thu_muc", "cha", "long_nhau"],
)
def test_namespace_ngoai_danh_muc_bi_tu_choi(workspace_dir, namespace):
    """Danh sách cho phép, không phải danh sách cấm.

    Namespace lạ vừa lặng lẽ mượn ngưỡng quyền của `chunks` mà không ai quyết
    định, vừa đi thẳng vào tên file kho - `../` trong đó là một đường thoát
    khỏi thư mục làm việc. Một luật đóng cả hai lỗ.
    """
    with pytest.raises(KVNamespaceInvalid) as loi:
        dung_adapter(workspace_dir, namespace=namespace)
    assert loi.value.code == "KV_NAMESPACE_INVALID"


def test_moi_namespace_trong_danh_muc_deu_dung_duoc(workspace_dir):
    """Danh mục đóng phải phủ đúng hai kho mà upstream dựng bằng lớp KV này."""
    for namespace in KV_NAMESPACES:
        adapter = dung_adapter(workspace_dir, namespace)
        assert adapter.namespace == namespace


def test_hang_cau_hinh_va_danh_muc_namespace():
    """Hằng mà story 1.7 dựng engine theo, ghim ngay cạnh adapter."""
    assert ENABLE_LLM_CACHE is False
    assert KV_NAMESPACES == ("text_chunks", "full_docs")
    assert KV_PERMISSION_NAMESPACE == "chunks"


def test_hai_method_doc_nam_trong_danh_sach_dong():
    """`get_by_id`/`get_by_ids` trả nội dung nên chúng thuộc danh sách đóng (AD-9)."""
    assert {"get_by_id", "get_by_ids"} <= MASKED_READ_METHODS


# --- Hai khoản nợ có địa chỉ, ghim bằng test --------------------------------


def test_cung_id_hai_nhan_khac_scope_thi_ban_ghi_thanh_khong_khoa(
    workspace_dir, khong_gian, policy
):
    """Chiều first-write-wins của đường KV, đã đóng ở story 2.1 (FR-11).

    Thay `test_dac_ta_hien_trang_cung_id_hai_nhan_first_write_wins` của story
    1.5. Test cũ ghim *hiện trạng*: id chunk của upstream là md5 nội dung
    (`compute_mdhash_id`), không mang `scope`, nên hai tài liệu khác scope có
    đoạn trùng nội dung sinh cùng một id; ngữ nghĩa chỉ-chèn của `upsert` khi
    đó giữ nhãn *rộng* của lần nạp đầu và lần nạp sau không siết lại được. Nó
    nói thẳng rằng story 2.1 sẽ đổi hành vi, nên mốc so sánh nay hết việc.

    Hành vi mới: khóa của bản ghi đã có cũng đi qua phép hợp nhất. Hai nhãn
    khác scope ra "không khóa", và bản ghi *ở lại* kho - khác đường vector, nơi
    point bị xóa. Chunk là văn bản chạy nên KV không có gì để che; luật của nó
    là vô hình với mọi vai, và đọc thô được dưới cờ system để re-ingest (story
    2.3) còn thấy mà dọn.
    """

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert({"chunk-trung": {"content": "đoạn trùng"}})
            with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
                lan_sau = await adapter.upsert({"chunk-trung": {"content": "đoạn trùng"}})
            with use_context(ngu_canh_ingest(khong_gian, policy)):
                trong_kho = await adapter.get_by_id("chunk-trung")
                con_trong_all_keys = await adapter.all_keys()
        doc_theo_vai = {}
        for ten_vai in ("tech_support", "devops"):
            with use_context(vai(policy, ten_vai, khong_gian)):
                doc_theo_vai[ten_vai] = await adapter.get_by_id("chunk-trung")
        return lan_sau, trong_kho, con_trong_all_keys, doc_theo_vai

    lan_sau, trong_kho, con_trong_all_keys, doc_theo_vai = asyncio.run(chay())
    assert lan_sau == {}, "nội dung vẫn chỉ-chèn: lần nạp sau không thêm bản ghi"
    assert trong_kho[FILTER_KEY_FIELD] is None, "khóa cũ phải bị siết thành không khóa"
    assert trong_kho["content"] == "đoạn trùng", "bản ghi ở lại, không bị xóa"
    assert "chunk-trung" in con_trong_all_keys, "cờ system vẫn đọc thô được"
    # `devops` chạm *cả hai* scope, nên nếu "không khóa" được cài bằng một khóa
    # đặc biệt nào đó thì đây là vai nhìn thấy nó. Vô hình với mọi vai nghĩa là
    # vô hình cả với vai rộng nhất.
    assert doc_theo_vai == {"tech_support": None, "devops": None}


def test_cung_scope_nap_lai_duoi_nhan_nhay_hon_thi_siet_khoa(
    workspace_dir, khong_gian, policy
):
    """Hàng 1 và hàng 2 của I/O Matrix ở đường KV: siết được, không nới ra."""

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert({"c1": {"content": "x"}, "c2": {"content": "y"}})
            with ingest_label(scope="noi_bo", content_type="bi_mat_ha_tang"):
                await adapter.upsert({"c1": {"content": "x"}})
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert({"c1": {"content": "x"}})
            return await adapter.khoa_hien_co(["c1", "c2", "c3"])

    khoa = asyncio.run(chay())
    assert khoa["c1"] == filter_key("noi_bo", "bi_mat_ha_tang")
    assert khoa["c2"] == filter_key("noi_bo", "runbook")
    assert khoa["c3"] is CHUA_GHI


def test_khong_khoa_la_trang_thai_hut_o_duong_kv(workspace_dir, khong_gian, policy):
    """Bản ghi đã "không khóa" thì lần nạp thứ ba không cấp lại khóa cho nó.

    Khác kho vector: bản ghi KV ở lại nên kho này *nhớ* được trạng thái đó, và
    nó là một trong hai kho mà bước đối chiếu hỏi khi kho vector không phân
    biệt được "vắng" với "không khóa".
    """

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            for scope, loai in (
                ("noi_bo", "runbook"),
                ("khach_hang_a", "bao_cao_su_co"),
                ("noi_bo", "runbook"),
            ):
                with ingest_label(scope=scope, content_type=loai):
                    await adapter.upsert({"c1": {"content": "x"}})
            return await adapter.khoa_hien_co(["c1"])

    assert asyncio.run(chay())["c1"] is None


def test_loai_noi_dung_khong_co_hang_thi_tu_choi_ca_lo(
    workspace_dir, khong_gian, policy
):
    """Hàng 4 của I/O Matrix ở đường KV: từ chối trước khi ghi bản ghi nào."""

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="hop_dong"):
                with pytest.raises(SensitivityRankUnknown) as loi:
                    await adapter.upsert({"c1": {"content": "x"}})
            assert loi.value.code == "SENSITIVITY_RANK_UNKNOWN"
            return await adapter.all_keys()

    assert asyncio.run(chay()) == []


def test_ban_ghi_thieu_han_truong_khoa_van_la_du_lieu_hong(
    workspace_dir, khong_gian, policy
):
    """"Không khóa" là `filter_key=null`, không phải trường vắng mặt.

    Hai ca trông giống nhau mà nghĩa ngược nhau: trường vắng nghĩa là có ai đó
    ghi vào file này không qua adapter (hỏng dữ liệu, phải nổ), còn `null` là
    kết quả hợp nhất khóa đa nguồn (hợp lệ, vô hình với mọi vai). Gộp chúng làm
    một là biến một file kho bị sửa tay thành một mục im lặng.
    """
    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert({"c1": {"content": "x"}})
            await adapter.index_done_callback()
        duong_dan = workspace_dir / f"kv_store_{khong_gian}_text_chunks.json"
        noi_dung = json.loads(duong_dan.read_text(encoding="utf-8"))
        del noi_dung["c1"][FILTER_KEY_FIELD]
        duong_dan.write_text(json.dumps(noi_dung), encoding="utf-8")
        adapter_moi = dung_adapter(workspace_dir)
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(RecordFilterKeyMissing) as loi:
                await adapter_moi.get_by_id("c1")
        return loi.value.code

    assert asyncio.run(chay()) == "RECORD_FILTER_KEY_MISSING"


def test_doc_khoa_hien_co_chi_chay_duoi_co_system(workspace_dir, khong_gian, policy):
    """Bước đọc khóa của read-merge-write là ngoại lệ có đặc tả của AD-3."""

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(IngestOutsideSystemContext) as loi:
                await adapter.khoa_hien_co(["c1"])
        return loi.value.code

    assert asyncio.run(chay()) == "INGEST_OUTSIDE_SYSTEM_CONTEXT"


def test_doc_tho_cung_tra_ban_sao_chu_khong_tra_doi_tuong_trong_kho(
    workspace_dir, khong_gian, policy
):
    """Ngữ cảnh hệ thống không che, nhưng vẫn không được phát ra chính dict trong kho.

    Đường ingest đọc rồi ghi lại (`operate.py:177-210` gộp `description` của
    entity), nên nếu `_tra` phát ra đối tượng trong kho thì một phép gán trong
    pipeline sửa thẳng kho mà không đi qua `upsert` - tức là qua mặt cả cửa
    nhãn ingest lẫn khóa quyền. Cùng lý do với bản sao ở nhánh có che, chỉ khác
    là ở đây không có tầng che nào che giấu chuyện đó.
    """

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(
                    {"chunk-tho": {"content": "nguyên văn", "meta": {"owner": "Minh"}}}
                )
            lan_dau = await adapter.get_by_id("chunk-tho")
            lan_dau["content"] = "đã bị sửa từ ngoài"
            lan_dau["meta"]["owner"] = "đã bị sửa từ ngoài"
            lan_dau[FILTER_KEY_FIELD] = filter_key("khach_hang_a", "bao_cao_su_co")
            return await adapter.get_by_id("chunk-tho")

    lan_sau = asyncio.run(chay())
    assert lan_sau["content"] == "nguyên văn"
    assert lan_sau["meta"]["owner"] == "Minh"
    assert lan_sau[FILTER_KEY_FIELD] == filter_key("noi_bo", "runbook")


def test_ket_qua_da_che_khong_ro_nguoc_vao_kho(
    workspace_dir, khong_gian, policy, monkeypatch
):
    """Che một bản ghi cho một vai không được đổi thứ vai khác đọc thấy.

    Kho trong bộ nhớ là bản gốc chưa che, dùng chung cho mọi vai. Nếu tầng che
    biến đổi tại chỗ một giá trị lồng nhau thì dấu che của vai hẹp nằm lại
    trong kho, và vai rộng quyền đọc sau đó nhận bản đã bị che - fail-open
    theo chiều ngược, nhưng vẫn là kết quả sai và vẫn im lặng.

    Story 1.6 trả lời bằng hai lớp: `core.masking.mask` là hàm thuần dựng bản
    ghi mới, và `_tra` sao chép sâu trước khi gọi nó. Test này ghim lớp thứ
    hai, nên nó cố ý vá `mask` bằng một bản biến đổi tại chỗ - lớp thứ nhất
    được ghim riêng ở `tests/test_tang_che.py`.
    """

    def che_bien_doi_tai_cho(ket_qua, context, khoa_hyperedge):
        ket_qua["meta"]["owner"] = "***"
        return ket_qua

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert(
                    {"chunk-long": {"content": "nội dung", "meta": {"owner": "Minh"}}}
                )
        monkeypatch.setattr("adapters.kv.mask", che_bien_doi_tai_cho)
        with use_context(vai(policy, "tech_support", khong_gian)):
            await adapter.get_by_id("chunk-long")
        monkeypatch.undo()
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return await adapter.get_by_id("chunk-long")

    trong_kho = asyncio.run(chay())
    assert trong_kho["meta"]["owner"] == "Minh", "dấu che của một vai rò vào kho"
