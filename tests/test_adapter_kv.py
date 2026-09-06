"""Adapter KV: cổng đọc chunk có phân quyền (story 1.5, AD-18, FR-05).

Hai kịch bản `1.5-INT-001`, `1.5-INT-002` của test-design cộng các hàng I/O
Matrix nói về đường đọc và hai cửa ghi. Lỗ mà bộ này canh là đường trả lời của
upstream: nó lấy id chunk từ `source_id` của entity và hyperedge rồi gọi thẳng
`text_chunks_db.get_by_id(c_id)` (`operate.py:843`, `:1073`), không bao giờ hỏi
collection `chunks`. Vai đạt L1 với một loại nội dung vì thế vẫn nhận trọn
nguyên văn của nó nếu cổng KV không có điểm chèn quyền.

Phần kho trên đĩa, cách ly space/namespace, `all_keys`/`filter_keys`, danh mục
namespace và hai khoản nợ có địa chỉ nằm ở `tests/test_adapter_kv_kho.py`.

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
from adapters.kv import KV_PERMISSION_NAMESPACE
from adapters.mask_contract import MaskContractViolated
from adapters.policy_loader import load_policy
from core.keys import FILTER_KEY_FIELD, filter_key
from core.permission import PermissionContextMissing, use_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import (
    CHUNK_THEO_ID,
    CHUNKS,
    HYPEREDGE_THEO_CHUNK,
    HYPEREDGES,
    TAI_LIEU_THEO_ID,
)
from tests.ho_tro_kv import dung_adapter, kho_da_nap
from tests.ngu_canh import ngu_canh_ingest, vai


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
    policy_l1 = load_policy(bang_l1, hang={"runbook": 10})
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


