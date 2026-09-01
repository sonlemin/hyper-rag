"""Adapter KV: cổng đọc chunk có phân quyền (story 1.5, AD-18, FR-05).

Hai kịch bản `1.5-INT-001`, `1.5-INT-002` của test-design cộng mọi hàng I/O
Matrix của spec. Lỗ mà bộ này canh là đường trả lời của upstream: nó lấy id
chunk từ `source_id` của entity và hyperedge rồi gọi thẳng
`text_chunks_db.get_by_id(c_id)` (`operate.py:843`, `:1073`), không bao giờ hỏi
collection `chunks`. Vai đạt L1 với một loại nội dung vì thế vẫn nhận trọn
nguyên văn của nó nếu cổng KV không có điểm chèn quyền.

Đối chứng là `tests/fixtures/oracle.py` - bộ tính kỳ vọng độc lập, không gọi
`core/` - chứ không phải chính adapter. Không con số nào ghim cứng trong assert
nếu oracle tính ra được nó.

Kho là file JSON trong thư mục tạm nên bộ này không cần mạng, không cần
container, không cần key LLM.
"""

import asyncio
import json

import pytest

from adapters.ingest_labels import (
    IngestLabelMissing,
    IngestOutsideSystemContext,
    ingest_label,
)
from adapters.kv import (
    DUOI_TAM,
    ENABLE_LLM_CACHE,
    KV_NAMESPACES,
    KV_PERMISSION_NAMESPACE,
    LLM_CACHE_NAMESPACE,
    JsonACLKVStorage,
    KVNamespaceInvalid,
    KVStoreCorrupt,
    LLMCacheDisabled,
    RecordFilterKeyMissing,
)
from adapters.mask_contract import MaskContractViolated
from adapters.policy_loader import load_policy
from core.keys import FILTER_KEY_FIELD, filter_key
from core.masking import MASKED_READ_METHODS
from core.permission import PermissionContextMissing, use_context, user_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import (
    CHUNK_THEO_ID,
    CHUNKS,
    HYPEREDGE_THEO_CHUNK,
    HYPEREDGES,
    TAI_LIEU_GOC,
    TAI_LIEU_THEO_ID,
)


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
    """Ngữ cảnh quyền của một vai; đây là thứ adapter đọc lúc truy vấn."""
    return user_context(
        policy=policy, role=ten_vai, space=khong_gian, real_account=f"{ten_vai}01"
    )


def ngu_canh_ingest(khong_gian: str, policy):
    """Ngữ cảnh hệ thống của pipeline nạp; adapter chỉ lấy `space` từ đây."""
    return system_context(space=khong_gian, policy_version=policy.policy_version)


def dung_adapter(workspace_dir, namespace="text_chunks"):
    """Adapter đúng cách upstream dựng nó (`hypergraphrag.py:208,213`)."""
    return JsonACLKVStorage(
        namespace=namespace,
        global_config={"working_dir": str(workspace_dir)},
        embedding_func=None,
    )


def lo_upsert(muc) -> dict[str, dict]:
    """Một lô upsert đúng hình dạng upstream dựng cho `text_chunks`.

    Upstream chỉ thêm `full_doc_id` vào dict chunk (`hypergraphrag.py:296-300`):
    không có khe nào nhét `scope` với `content_type` vào, nên nhãn quyền phải
    đi đường khác - phạm vi nhãn ingest. Test dựng lại đúng hình dạng đó, bỏ
    hai nhãn ra khỏi bản ghi.
    """
    ban_ghi = {k: v for k, v in dict(muc).items() if k not in ("scope", "content_type")}
    return {muc["id"]: ban_ghi}


async def nap(adapter, khong_gian, policy, cac_muc) -> None:
    """Nạp fixture dưới ngữ cảnh hệ thống, mỗi tài liệu một phạm vi nhãn."""
    with use_context(ngu_canh_ingest(khong_gian, policy)):
        for muc in cac_muc:
            with ingest_label(scope=muc["scope"], content_type=muc["content_type"]):
                await adapter.upsert(lo_upsert(muc))


async def kho_da_nap(workspace_dir, khong_gian, policy, namespace="text_chunks"):
    """Adapter đã nạp xong chunk fixture, ghi luôn xuống đĩa."""
    adapter = dung_adapter(workspace_dir, namespace)
    await nap(adapter, khong_gian, policy, CHUNKS)
    await adapter.index_done_callback()
    return adapter


def con_lai_file_tam(workspace_dir) -> list[str]:
    """Tên các file tạm còn sót trong thư mục làm việc."""
    return sorted(p.name for p in workspace_dir.glob(f"*{DUOI_TAM}"))


# --- Bất biến của chính fixture --------------------------------------------


def test_nhan_cua_chunk_bang_nhan_cua_nguon_no():
    """Khóa quyền của chunk là khóa của tài liệu cắt ra nó, không phải nhãn thứ hai.

    `CHUNKS` chép `scope`/`content_type` dưới dạng chuỗi literal, nên quan hệ
    "cùng nhãn với nguồn" chỉ đúng chừng nào có ai canh. Lệch một nhãn ở đây
    là mọi assert quyền của story này đo một thứ khác với thứ nó nói.
    """
    for c in CHUNKS:
        tai_lieu = TAI_LIEU_THEO_ID[c["full_doc_id"]]
        assert (c["scope"], c["content_type"]) == (
            tai_lieu["scope"],
            tai_lieu["content_type"],
        ), c["id"]
        he = HYPEREDGE_THEO_CHUNK.get(c["id"])
        if he is not None:
            assert (c["scope"], c["content_type"]) == (
                he["scope"],
                he["content_type"],
            ), c["id"]


def test_fixture_co_du_hai_nua_cua_khoa():
    """Fixture phải phân biệt được nửa `scope` lẫn nửa `content_type` của khóa.

    Không có cặp "cùng `content_type`, khác `scope`" thì một adapter chỉ kiểm
    `content_type` vẫn xanh cả bộ - đúng đột biến đã sống sót ở vòng review.
    """
    cung_loai_khac_scope = [
        c
        for c in CHUNKS
        if c["content_type"] == "runbook" and c["scope"] == "khach_hang_a"
    ]
    assert cung_loai_khac_scope, "thiếu chunk khác scope mà cùng loại nội dung"
    cung_scope_khac_loai = {c["content_type"] for c in CHUNKS if c["scope"] == "noi_bo"}
    assert len(cung_scope_khac_loai) > 1


# --- 1.5-INT-001: đọc một mục, trong và ngoài quyền -------------------------


def test_doc_chunk_trong_quyen_qua_tang_che(workspace_dir, khong_gian, policy):
    """Vai đạt L2 với nguồn thì đọc được, và bản ghi đã đi qua tầng che."""

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_by_id("chunk-HE-01")

    ban_ghi = asyncio.run(chay())
    assert ban_ghi is not None
    assert ban_ghi["content"] == CHUNK_THEO_ID["chunk-HE-01"]["content"]
    # Khóa quyền ở lại trong bản ghi: nó là nhãn của chính mục đó, thứ tầng che
    # tra `masked_slots` theo và thứ cho phép truy nguyên một mục đã ra ngoài.
    assert ban_ghi[FILTER_KEY_FIELD] == filter_key("noi_bo", "runbook")


def test_doc_chunk_ngoai_quyen_vang_mat_im_lang(workspace_dir, khong_gian, policy):
    """Vai chỉ đạt L1 với nguồn: `get_by_id` trả `None`, không phải lỗi.

    `None` là ngôn ngữ upstream đã hiểu - cả hai chỗ tiêu thụ đều lọc `None`
    ra trước khi dựng ngữ cảnh - nên ca thường gặp nhất không cần mã lỗi nào.
    """

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_by_id("chunk-HE-02")

    assert asyncio.run(chay()) is None


def test_nua_scope_cua_khoa_tu_no_quyet_dinh(workspace_dir, khong_gian, policy, bang):
    """Cùng `content_type` ở L2, khác `scope`: vai ngoài scope vẫn không đọc được.

    `runbook` là L2 với cả hai vai, nên chunk này chỉ bị chặn bởi nửa trái của
    khóa. Đây là biên cách ly khách hàng RT-01 chiếu lên đường chunk, và cũng
    là ca mà một adapter chỉ kiểm `content_type` sẽ để lọt.
    """
    id_chunk = "chunk-KH-A-RUNBOOK"

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        thay = {}
        for ten_vai in ("devops", "tech_support"):
            with use_context(vai(policy, ten_vai, khong_gian)):
                thay[ten_vai] = await adapter.get_by_id(id_chunk)
        return thay

    thay = asyncio.run(chay())
    assert thay["devops"]["content"] == CHUNK_THEO_ID[id_chunk]["content"]
    assert thay["tech_support"] is None
    # Đối chứng độc lập, và nó phải khác nhau đúng ở nửa `scope`.
    assert id_chunk in oracle.chunk_thay_duoc(bang, "devops", CHUNKS)
    assert id_chunk not in oracle.chunk_thay_duoc(bang, "tech_support", CHUNKS)
    assert oracle.muc_ky_vong(bang, "tech_support", "runbook") == "L2"


def test_thay_hyperedge_o_l1_van_khong_lay_duoc_chunk_nguon(
    workspace_dir, khong_gian, policy, bang
):
    """Lớp (b) của AD-18: thấy hyperedge không kéo theo đọc được nguyên văn.

    Đây đúng là đường mà upstream đi - `source_id` của hyperedge dẫn thẳng tới
    `text_chunks_db.get_by_id` - nên nó phải có một test đi đúng đường đó chứ
    không chỉ có test đọc một id rời.
    """
    thay_hyperedge = set(oracle.hyperedge_thay_duoc(bang, "tech_support", HYPEREDGES))
    doc_duoc_chunk = set(oracle.chunk_thay_duoc(bang, "tech_support", CHUNKS))
    o_l1 = [
        he
        for he in HYPEREDGES
        if he["id"] in thay_hyperedge and he["source_id"] not in doc_duoc_chunk
    ]
    assert o_l1, "fixture phải có hyperedge thấy được mà chunk nguồn thì không"

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return {he["id"]: await adapter.get_by_id(he["source_id"]) for he in o_l1}

    assert asyncio.run(chay()) == {he["id"]: None for he in o_l1}


def test_ngu_canh_he_thong_doc_tho(workspace_dir, khong_gian, policy):
    """Cờ system: đọc thô mọi mục, không filter, không che (AD-3)."""

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            return [await adapter.get_by_id(c["id"]) for c in CHUNKS]

    ket_qua = asyncio.run(chay())
    assert [r["content"] for r in ket_qua] == [c["content"] for c in CHUNKS]


def test_hai_vai_khac_nhau_cung_mot_id(workspace_dir, khong_gian, policy, bang):
    """Cùng id chunk, hai ngữ cảnh vai: khác biệt sinh từ tập khóa.

    Đây là hình chiếu của cổng M1 lên đường KV: devops đạt L2 với báo cáo sự
    cố nên đọc được nguyên văn, tech_support chỉ đạt L1 nên mục vắng mặt.
    """

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        ket_qua = {}
        for ten_vai in ("devops", "tech_support"):
            with use_context(vai(policy, ten_vai, khong_gian)):
                ket_qua[ten_vai] = await adapter.get_by_id("chunk-HE-02")
        return ket_qua

    ket_qua = asyncio.run(chay())
    assert ket_qua["devops"]["content"] == CHUNK_THEO_ID["chunk-HE-02"]["content"]
    assert ket_qua["tech_support"] is None
    # Đối chứng độc lập: đúng cái oracle nói, không phải cái adapter nói.
    assert "chunk-HE-02" in oracle.chunk_thay_duoc(bang, "devops", CHUNKS)
    assert "chunk-HE-02" not in oracle.chunk_thay_duoc(bang, "tech_support", CHUNKS)


# --- 1.5-INT-002: danh sách trộn quyền -------------------------------------


@pytest.mark.parametrize("ten_vai", ["devops", "tech_support"])
def test_get_by_ids_tron_quyen(workspace_dir, khong_gian, policy, bang, ten_vai):
    """List đúng độ dài, `None` đúng vị trí của mục ngoài quyền.

    Hợp đồng upstream là list cùng độ dài đầu vào (`storage.py:42`), nên mục
    ngoài quyền không được rơi ra khỏi list mà phải thành `None` tại chỗ.
    """
    ids = [c["id"] for c in CHUNKS] + ["chunk-KHONG-TON-TAI"]

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, ten_vai, khong_gian)):
            return await adapter.get_by_ids(ids)

    ket_qua = asyncio.run(chay())
    assert len(ket_qua) == len(ids)
    thay_duoc = oracle.chunk_thay_duoc(bang, ten_vai, CHUNKS)
    assert [ids[i] for i, r in enumerate(ket_qua) if r is not None] == thay_duoc
    # Id không tồn tại và id ngoài quyền không phân biệt được từ ngoài.
    assert ket_qua[-1] is None


def test_get_by_ids_chieu_truong(workspace_dir, khong_gian, policy):
    """`fields` chiếu sau khi đã lọc và che, không phải trước."""
    ids = ["chunk-HE-01", "chunk-HE-02"]

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await adapter.get_by_ids(ids, fields={"content"})

    ket_qua = asyncio.run(chay())
    assert ket_qua[0] == {"content": CHUNK_THEO_ID["chunk-HE-01"]["content"]}
    assert ket_qua[1] is None


def test_chieu_truong_khong_bo_qua_tang_che(
    workspace_dir, khong_gian, policy, bang, monkeypatch
):
    """Chiếu trường không được thành đường vòng qua tầng che.

    Đột biến mà test này bắt: chiếu `fields` ngay trên dữ liệu thô rồi mới
    lọc. Ghim bằng cách đếm lời gọi `mask` - có chiếu trường thì mọi bản ghi
    trả về vẫn phải đi qua tầng che đúng một lần.
    """
    da_goi = []

    def mask_dem(ket_qua, context, khoa):
        da_goi.append(khoa)
        return ket_qua

    monkeypatch.setattr("adapters.kv.mask", mask_dem)

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            return await adapter.get_by_ids(
                [c["id"] for c in CHUNKS], fields={"content"}
            )

    ket_qua = asyncio.run(chay())
    thay_duoc = oracle.chunk_thay_duoc(bang, "devops", CHUNKS)
    assert len(da_goi) == len([r for r in ket_qua if r is not None]) == len(thay_duoc)
    assert sorted(da_goi) == sorted(
        filter_key(CHUNK_THEO_ID[id]["scope"], CHUNK_THEO_ID[id]["content_type"])
        for id in thay_duoc
    )


def test_tang_che_tra_rong_la_loi_tai_adapter(workspace_dir, khong_gian, policy, monkeypatch):
    """`mask` trả rỗng hay bỏ mất trường là vi phạm hợp đồng, có mã ổn định.

    Muốn giấu hẳn một mục thì method đọc phải lọc nó ra, không đưa một giá trị
    rỗng vào kết quả: một `None` lọt xuống sẽ nổ tận trong `vendor/`.
    """
    monkeypatch.setattr("adapters.kv.mask", lambda ket_qua, context, khoa: {})

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "tech_support", khong_gian)):
            await adapter.get_by_id("chunk-HE-01")

    with pytest.raises(MaskContractViolated) as loi:
        asyncio.run(chay())
    assert loi.value.code == "MASK_CONTRACT_VIOLATED"


def test_khoa_che_dung_theo_tung_ban_ghi(
    workspace_dir, khong_gian, policy, bang, monkeypatch
):
    """Khóa truyền cho tầng che là khóa của chính mục đó, không phải khóa nào khác.

    Nằm trong một tập đúng thì chưa đủ: che một loại nội dung bằng luật của
    loại nội dung khác vẫn có thể để hở, nên ghim theo từng dòng.
    """
    thay = {}

    def mask_ghi(ket_qua, context, khoa):
        thay[ket_qua["id"]] = khoa
        return ket_qua

    monkeypatch.setattr("adapters.kv.mask", mask_ghi)

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            await adapter.get_by_ids([c["id"] for c in CHUNKS])

    asyncio.run(chay())
    assert thay == {
        id: filter_key(
            CHUNK_THEO_ID[id]["scope"], CHUNK_THEO_ID[id]["content_type"]
        )
        for id in oracle.chunk_thay_duoc(bang, "devops", CHUNKS)
    }


# --- Tập khóa rỗng, thiếu ngữ cảnh -----------------------------------------


def test_tap_khoa_rong_khong_cham_dia(workspace_dir, khong_gian, tmp_path):
    """Vai không có loại nội dung nào ở L2: mọi mục vắng mặt, không đọc file.

    Vai `khach` dừng ở L1 với `runbook`, nên nó *thấy hyperedge* mà tập khóa
    của namespace `chunks` thì rỗng - đúng ca mà luật chunk-chỉ-L2 sinh ra, và
    là một vai thật trong một bảng thật chứ không phải một `keys_for` bị vá.
    Assert trên việc không nạp file, không chỉ trên kết quả rỗng.
    """
    bang_l1 = tmp_path / "policy-chi-l1.yaml"
    bang_l1.write_text(
        "version: 1\n"
        "roles:\n"
        "  khach:\n"
        "    scopes: [noi_bo]\n"
        "    disclosure:\n"
        "      runbook: L1\n",
        encoding="utf-8",
    )
    policy_l1 = load_policy(bang_l1)
    ctx = vai(policy_l1, "khach", khong_gian)
    assert ctx.keys_for(KV_PERMISSION_NAMESPACE) == frozenset()
    assert ctx.keys_for("hyperedges"), "vai này vẫn phải thấy hyperedge"

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy_l1)
        # Xóa bộ nhớ đệm để "không chạm đĩa" là một khẳng định kiểm được.
        adapter._kho.clear()
        with use_context(ctx):
            return (
                await adapter.get_by_id("chunk-HE-01"),
                await adapter.get_by_ids(["chunk-HE-01", "chunk-HE-02"]),
                await adapter.all_keys(),
                await adapter.filter_keys(["chunk-HE-01"]),
                adapter._kho,
            )

    mot, nhieu, tat_ca, chua_co, kho = asyncio.run(chay())
    assert mot is None
    assert nhieu == [None, None]
    assert tat_ca == []
    assert chua_co == {"chunk-HE-01"}
    assert kho == {}, "tập khóa rỗng mà vẫn nạp file: đã chạm đĩa"


@pytest.mark.parametrize(
    "goi",
    [
        lambda a: a.get_by_id("chunk-HE-01"),
        lambda a: a.get_by_ids(["chunk-HE-01"]),
        lambda a: a.all_keys(),
        lambda a: a.filter_keys(["chunk-HE-01"]),
        lambda a: a.upsert({"chunk-HE-01": {"content": "x"}}),
        lambda a: a.drop(),
    ],
    ids=["get_by_id", "get_by_ids", "all_keys", "filter_keys", "upsert", "drop"],
)
def test_thieu_ngu_canh_moi_method_deu_raise(workspace_dir, goi):
    """Fail-closed: chưa ai set ngữ cảnh thì không method nào có đường trả về."""
    adapter = dung_adapter(workspace_dir)
    with pytest.raises(PermissionContextMissing) as loi:
        asyncio.run(goi(adapter))
    assert loi.value.code == "PERMISSION_CONTEXT_MISSING"


# --- Đường ghi --------------------------------------------------------------


def test_ghi_gan_khoa_cua_nhan_ingest(workspace_dir, khong_gian, policy):
    """Bản ghi mang khóa của phạm vi nhãn đang mở, đọc lại từ file thấy đúng."""

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        return adapter._duong_dan(khong_gian)

    duong_dan = asyncio.run(chay())
    tren_dia = json.loads(duong_dan.read_text(encoding="utf-8"))
    assert set(tren_dia) == {c["id"] for c in CHUNKS}
    for c in CHUNKS:
        assert tren_dia[c["id"]][FILTER_KEY_FIELD] == filter_key(
            c["scope"], c["content_type"]
        )


def test_nhan_ingest_thang_khoa_nguoi_goi_nhet_vao(workspace_dir, khong_gian, policy):
    """Dữ liệu không tự khai quyền cho mình được.

    Đường ghi là chỗ *duy nhất* đặt khóa quyền. Một `filter_key` nhét sẵn
    trong dict đầu vào mà thắng nhãn ingest nghĩa là bất kỳ ai dựng được lô
    upsert đều tự chọn được vai nào đọc dữ liệu của mình. Luật này hiện nằm ở
    thứ tự hai vế trong một dict literal, nên nó cần một test riêng.
    """
    khoa_gia = filter_key("noi_bo", "runbook")
    khoa_that = filter_key("khach_hang_a", "bao_cao_su_co")

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
                da_chen = await adapter.upsert(
                    {"chunk-tu-khai": {"content": "nội dung", FILTER_KEY_FIELD: khoa_gia}}
                )
            with use_context(ngu_canh_ingest(khong_gian, policy)):
                trong_kho = await adapter.get_by_id("chunk-tu-khai")
        return da_chen, trong_kho

    da_chen, trong_kho = asyncio.run(chay())
    assert da_chen["chunk-tu-khai"][FILTER_KEY_FIELD] == khoa_that
    assert trong_kho[FILTER_KEY_FIELD] == khoa_that


def test_upsert_tra_ban_sao_khong_tra_chinh_ban_ghi_trong_kho(
    workspace_dir, khong_gian, policy
):
    """Sửa dict trả về không được đổi nhãn quyền trong kho.

    Trả thẳng đối tượng trong kho là một đường fail-open im lặng: nơi gọi chỉ
    cần gán lại `filter_key` là dữ liệu đổi vai đọc mà không đi qua cửa ghi nào.
    """

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                da_chen = await adapter.upsert({"chunk-x": {"content": "nội dung"}})
            da_chen["chunk-x"][FILTER_KEY_FIELD] = filter_key("noi_bo", "bi_mat_ha_tang")
            da_chen["chunk-x"]["content"] = "đã bị sửa"
            with use_context(ngu_canh_ingest(khong_gian, policy)):
                return await adapter.get_by_id("chunk-x")

    trong_kho = asyncio.run(chay())
    assert trong_kho[FILTER_KEY_FIELD] == filter_key("noi_bo", "runbook")
    assert trong_kho["content"] == "nội dung"


def test_upsert_chi_chen_khoa_moi(workspace_dir, khong_gian, policy):
    """Hợp đồng upstream: chỉ khóa mới được chèn, trả về đúng phần đã chèn."""

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                lai = await adapter.upsert(
                    {"chunk-HE-01": {"content": "bản ghi đè"}, "chunk-MOI": {"content": "mới"}}
                )
            with use_context(vai(policy, "tech_support", khong_gian)):
                cu = await adapter.get_by_id("chunk-HE-01")
        return lai, cu

    lai, cu = asyncio.run(chay())
    assert set(lai) == {"chunk-MOI"}
    assert lai["chunk-MOI"][FILTER_KEY_FIELD] == filter_key("noi_bo", "runbook")
    assert cu["content"] == CHUNK_THEO_ID["chunk-HE-01"]["content"]


def test_lo_rong_khong_cham_kho(workspace_dir, khong_gian, policy):
    """Lô rỗng không ghi gì và không cần gì, đúng như upstream.

    Parity với `test_lo_rong_khong_cham_kho` của đường vector: nó về sớm trước
    cả cửa nhãn ingest, nên gọi nó ngoài mọi phạm vi nhãn vẫn hợp lệ.
    """

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            assert await adapter.upsert({}) == {}
        return adapter._kho, adapter._ban

    kho, ban = asyncio.run(chay())
    assert kho == {}, "lô rỗng mà vẫn nạp kho"
    assert ban == set(), "lô rỗng mà vẫn đánh dấu phải ghi xuống đĩa"
    assert list(workspace_dir.iterdir()) == []


@pytest.mark.parametrize(
    "mo_nhan,loi_mong_doi,ma",
    [
        (False, IngestLabelMissing, "INGEST_LABEL_MISSING"),
        (True, IngestOutsideSystemContext, "INGEST_OUTSIDE_SYSTEM_CONTEXT"),
    ],
    ids=["chua_mo_nhan", "duoi_ngu_canh_vai"],
)
def test_hai_cua_ghi_tu_choi_ca_lo(
    workspace_dir, khong_gian, policy, mo_nhan, loi_mong_doi, ma
):
    """Hỏng cửa nào cũng là từ chối *cả lô*, kể cả lô trộn mới và cũ.

    Chạy trên kho đã nạp và với một lô có cả id đã có lẫn id mới: kho rỗng thì
    `all_keys() == []` vẫn đúng ngay cả khi adapter đã ghi được một nửa, nên
    phép thử cũ không phân biệt được "từ chối cả lô" với "ghi một phần".
    """

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        lo = {
            "chunk-HE-01": {"content": "đè lên mục đã có"},
            "chunk-moi-a": {"content": "a"},
            "chunk-moi-b": {"content": "b"},
        }
        if mo_nhan:
            # Nhãn mở, nhưng ngữ cảnh là vai người dùng: cửa AD-3 phải chặn.
            with use_context(vai(policy, "devops", khong_gian)):
                with ingest_label(scope="noi_bo", content_type="runbook"):
                    with pytest.raises(loi_mong_doi) as loi:
                        await adapter.upsert(lo)
        else:
            with use_context(ngu_canh_ingest(khong_gian, policy)):
                with pytest.raises(loi_mong_doi) as loi:
                    await adapter.upsert(lo)
        assert loi.value.code == ma
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            con_lai = await adapter.all_keys()
            he01 = await adapter.get_by_id("chunk-HE-01")
        return con_lai, he01, adapter._ban

    con_lai, he01, ban = asyncio.run(chay())
    assert con_lai == [c["id"] for c in CHUNKS], "lô bị từ chối mà kho vẫn đổi"
    assert he01["content"] == CHUNK_THEO_ID["chunk-HE-01"]["content"]
    assert ban == set(), "lô bị từ chối mà kho vẫn bị đánh dấu phải ghi xuống đĩa"


def test_drop_chi_chay_duoi_ngu_canh_he_thong(workspace_dir, khong_gian, policy):
    """`drop` xóa sạch kho của một `space`, và chỉ pipeline ingest gọi được.

    Đọc lại bằng một instance mới sau khi flush: `all_keys()` trên cùng
    instance chỉ đọc bộ nhớ, nên nó xanh cả khi `drop` quên đánh dấu kho phải
    ghi xuống đĩa và file cũ còn nguyên trên đĩa.
    """

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy)
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(IngestOutsideSystemContext):
                await adapter.drop()
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            await adapter.drop()
            trong_bo_nho = await adapter.all_keys()
        await adapter.index_done_callback()

        doc_lai = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            tren_dia = await doc_lai.all_keys()
        return trong_bo_nho, tren_dia

    trong_bo_nho, tren_dia = asyncio.run(chay())
    assert trong_bo_nho == []
    assert tren_dia == [], "drop không xuống tới đĩa: instance mới vẫn thấy kho cũ"


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
    bang_toi_gian = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    policy_nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)
    policy_toi_gian = load_policy(oracle.POLICY_TOI_GIAN)

    async def chay():
        adapter = await kho_da_nap(workspace_dir, khong_gian, policy_toi_gian)
        with use_context(vai(policy_nhi_phan, ten_vai, khong_gian)):
            return await adapter.all_keys()

    assert asyncio.run(chay()) == oracle.chunk_thay_duoc(
        bang_nhi_phan, ten_vai, CHUNKS
    )
    # Hai bảng đồng ý ở ngưỡng chunk...
    assert oracle.chunk_thay_duoc(bang_nhi_phan, ten_vai, CHUNKS) == (
        oracle.chunk_thay_duoc(bang_toi_gian, ten_vai, CHUNKS)
    )
    # ...và bất đồng ở ngưỡng hyperedge, nên phép thử không rỗng nghĩa.
    assert oracle.hyperedge_thay_duoc(bang_nhi_phan, ten_vai, HYPEREDGES) != (
        oracle.hyperedge_thay_duoc(bang_toi_gian, ten_vai, HYPEREDGES)
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


def test_dac_ta_hien_trang_cung_id_hai_nhan_first_write_wins(
    workspace_dir, khong_gian, policy
):
    """Đặc tả hiện trạng: cùng một id nạp hai lần thì nhãn lần *đầu* thắng.

    Không phải khẳng định hành vi đúng, mà là mốc so sánh cho story 2.1. Id
    chunk của upstream là md5 của nội dung (`compute_mdhash_id`), không mang
    `scope`, nên hai tài liệu khác scope có đoạn trùng nội dung sinh cùng một
    id. Ngữ nghĩa chỉ-chèn của `upsert` khi đó giữ nhãn của lần nạp đầu, và
    nếu lần đầu là nhãn rộng hơn thì lần nạp sau *không* siết được nó lại.

    Đây là chiều ngược của khoản nợ last-write-wins ở đường vector và đường
    graph (nhãn của lần ghi sau thắng), nên hai kho lệch nhau ngay trong cùng
    một đợt nạp. Cả hai chiều trả một lần ở story 2.1; đổi luật hợp nhất là
    phải sửa cả test này.
    """
    rong = filter_key("noi_bo", "runbook")
    hep = filter_key("khach_hang_a", "bao_cao_su_co")

    async def chay():
        adapter = dung_adapter(workspace_dir)
        with use_context(ngu_canh_ingest(khong_gian, policy)):
            with ingest_label(scope="noi_bo", content_type="runbook"):
                await adapter.upsert({"chunk-trung": {"content": "đoạn trùng"}})
            with ingest_label(scope="khach_hang_a", content_type="bao_cao_su_co"):
                lan_sau = await adapter.upsert({"chunk-trung": {"content": "đoạn trùng"}})
            with use_context(ngu_canh_ingest(khong_gian, policy)):
                trong_kho = await adapter.get_by_id("chunk-trung")
        with use_context(vai(policy, "tech_support", khong_gian)):
            vai_hep_doc = await adapter.get_by_id("chunk-trung")
        return lan_sau, trong_kho, vai_hep_doc

    lan_sau, trong_kho, vai_hep_doc = asyncio.run(chay())
    assert lan_sau == {}, "lần nạp sau bị bỏ qua, đó chính là hiện trạng cần ghim"
    assert trong_kho[FILTER_KEY_FIELD] == rong
    assert trong_kho[FILTER_KEY_FIELD] != hep
    # Hệ quả nhìn thấy được: vai không chạm scope `khach_hang_a` vẫn đọc được
    # bản ghi mà lần nạp thứ hai định xếp vào scope đó.
    assert vai_hep_doc is not None


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
