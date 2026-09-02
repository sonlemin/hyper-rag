"""Cổng M1: hai tài khoản, hai kết quả, sinh từ cơ chế thật (story 1.7).

Bảy kịch bản `1.7-INT-001..007` của test-design cộng danh tính seed. Khác mọi
bộ test trước của Epic 1 ở một điểm: ba adapter không còn được gọi trực tiếp mà
đi qua `HyperGraphRAG.aquery` thật, nên đây là chỗ đầu tiên chứng minh được
contextvar quyền sống qua pipeline async của upstream.

Ba lớp assert, theo thứ tự quan trọng:

1. **Chuỗi ngữ cảnh truy hồi** (`QueryParam(only_need_context=True)`), không
   bao giờ là câu trả lời LLM - chốt brief §6. Bộ này còn ghim luôn rằng không
   có lời gọi LLM nào mang `system_prompt`, tức không đường nào đi tới bước
   sinh câu trả lời.
2. **Bộ lọc đi cùng request**: đối tượng filter trong search request Qdrant và
   mệnh đề WHERE trong chính câu Cypher. Nhìn vào kết quả thì không phân biệt
   được pre-filter với lọc lại phía Python.
3. **Kỳ vọng lấy từ `tests/fixtures/oracle.py`**, bộ tính độc lập không import
   `core/`.

Phần dựng engine, khóa cấu hình, secret trong log và vòng đời kết nối nằm ở
`tests/test_engine_acl.py`.

Không mạng, không container, không key LLM: Qdrant là local mode có ghi nhật
ký, Neo4j là driver giả, LLM là bản giả trả đúng định dạng bản ghi từ khóa,
embedding là hàm hash cố định, và bộ mã hóa token được thay bằng bản offline
qua fixture `ma_hoa_offline` (tiktoken tải bảng BPE qua mạng ở lần dùng đầu).
"""

import asyncio
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from adapters.identity_seed import (
    DUONG_DAN_DANH_TINH_DEMO,
    IdentitySeedInvalid,
    nap_danh_tinh,
)
from core.identity import DanhTinh, RoleUnknown, ngu_canh_cua
from core.permission import PermissionContextMissing
from hypergraphrag.base import QueryParam
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, THEO_ID
from tests.gia_lap_neo4j import canh_moi_bien_deu_bi_loc
from tests.gia_lap_qdrant import khoa_trong_filter
from tests.ho_tro_m1 import (
    CAU_HOI,
    chunk_trong,
    cong_m1,
    hoi,
    khoa_theo_collection,
    ten_hyperedge_ky_vong,
    ten_hyperedge_trong,
)
from tests.nap_kho import ten_hyperedge

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ba dấu hiệu của việc chạy code trong thread khác. Nếu `vendor/` dùng bất kỳ
# cái nào thì contextvar quyền có thể đứt và đường lùi "engine per-request" của
# spine (`:245`) phải được dựng. Grep ra rỗng là bằng chứng cho quyết định
# không dựng nó; test dưới đây giữ bằng chứng đó sống thay vì để nó thành một
# câu trong tài liệu.
DAU_HIEU_THREAD = (
    "to_thread",
    "run_in_executor",
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "threading.Thread",
    "run_coroutine_threadsafe",
    "call_soon_threadsafe",
)

# Đường truy vấn thật của upstream gọi `tiktoken`, thứ tải bảng BPE qua mạng ở
# lần dùng đầu. Bộ Đo 1 nền phải chạy không mạng, nên cả file dùng bộ đếm token
# offline. Khai một dòng ở đây thay vì lặp lại một fixture autouse mỗi file.
pytestmark = pytest.mark.usefixtures("ma_hoa_offline")


@pytest.fixture()
def danh_tinh_demo(khong_gian):
    """Hai danh tính seed, chuyển sang không gian cách ly của phiên test.

    Vai và tài khoản lấy từ `config/danh-tinh-demo.yaml`, không viết trong
    test: đó đúng là điều AC đòi ("ngữ cảnh quyền phát từ danh tính, không
    hard-code trong test"). `khong_gian` thì là chuyện cách ly dữ liệu của bộ
    test, nên nó - và chỉ nó - được thay.
    """
    return tuple(replace(dt, khong_gian=khong_gian) for dt in nap_danh_tinh())


def test_hashing_kv_xuong_ham_llm_la_none_tren_duong_truy_van(
    workspace_dir, khong_gian, policy
):
    """AD-18 trên chính đường truy vấn, không chỉ trên thuộc tính của engine.

    `HyperGraphRAG.__post_init__` bind `hashing_kv=self.llm_response_cache`
    bằng `partial` (`hypergraphrag.py:242-248`), và `handle_cache`/`save_to_cache`
    đọc đúng giá trị đó. Ghim ở chỗ giá trị được bind là ghim chỗ cơ chế thật
    sự đọc, chứ không phải chỗ nó được khai.

    Đổi kỳ vọng ở story 2.2: hàm LLM của engine nay là wrapper, và wrapper
    nuốt `hashing_kv` trước khi gọi provider (hợp đồng của nó: provider thật
    không hiểu kwarg này). Nên bản giả không còn nhìn thấy `hashing_kv`; thứ
    nhìn thấy được là `partial` mà upstream bọc quanh wrapper
    (`engine.llm_model_func.__wrapped__`, do `functools.wraps` để lại), và giá
    trị bind ở đó phải là `None`. Vế thứ hai ghim luôn hợp đồng "nuốt": provider
    giả không nhận `hashing_kv` trong bất kỳ lời gọi nào.
    """
    from functools import partial

    async def chay():
        engine, _, _, llm = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian)
        await hoi(engine, ngu_canh_cua(dt, policy))
        return engine.llm_model_func.__wrapped__, llm.kwargs

    bind, kwargs = asyncio.run(chay())
    assert isinstance(bind, partial), "upstream không còn bind hashing_kv bằng partial"
    assert "hashing_kv" in bind.keywords, "upstream đã bỏ tham số cache, xem lại AD-18"
    assert bind.keywords["hashing_kv"] is None
    assert kwargs, "không có lời gọi LLM nào để kiểm"
    for lan in kwargs:
        assert "hashing_kv" not in lan, "wrapper để lọt hashing_kv xuống provider"


# --- 1.7-INT-001: contextvar qua pipeline async tới cả ba adapter -----------


def test_contextvar_toi_ca_ba_adapter_mang_dung_tap_khoa(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-001`: một truy vấn e2e, ba adapter, ba lần đúng tập khóa của vai.

    Test hai chiều, không chỉ "có filter": tập khóa trong request phải **bằng**
    tập oracle tính độc lập, và hai vai phải cho hai tập khác nhau.
    """

    async def chay():
        engine, client, driver, llm = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        thu = {}
        for dt in danh_tinh_demo:
            client.xoa_nhat_ky()
            driver.xoa_nhat_ky()
            llm.xoa_nhat_ky()
            ngu_canh = await hoi(engine, ngu_canh_cua(dt, policy))
            thu[dt.vai] = (
                ngu_canh,
                khoa_theo_collection(client),
                [dict(lg.params) for lg in driver.cac_cau_doc()],
                [lg.cypher for lg in driver.cac_cau_doc()],
                llm.so_lan,
                list(llm.prompts_sinh_cau_tra_loi),
            )
        return thu

    thu = asyncio.run(chay())
    for vai, (ngu_canh, khoa_qdrant, tham_so, cypher, so_lan_llm, sinh) in thu.items():
        ky_vong = oracle.allowed_keys_ky_vong(bang, vai)

        # Đường vector: bộ lọc đi *cùng* request, một lần cho mỗi collection.
        assert khoa_qdrant[f"{khong_gian}_hyperedges"] == ky_vong["hyperedges"]
        assert khoa_qdrant[f"{khong_gian}_entities"] == ky_vong["entities"]

        # Đường graph: WHERE nằm trong chính câu Cypher, mọi biến đều bị ràng.
        assert cypher, f"vai {vai} không phát câu đọc graph nào"
        for cau in cypher:
            canh_moi_bien_deu_bi_loc(cau)
        for p in tham_so:
            assert set(p["keys"]) == ky_vong["hyperedges"]
            assert p["space"] == khong_gian

        # Đường KV: không chunk nào ngoài ngưỡng L2 của vai lọt vào ngữ cảnh.
        thay = chunk_trong(ngu_canh)
        assert thay, f"vai {vai} không truy hồi được chunk nào"
        assert thay <= set(oracle.chunk_thay_duoc(bang, vai, CHUNKS))

        # Đúng một lời gọi LLM (trích từ khóa), không lời gọi sinh câu trả lời:
        # bộ này assert trên ngữ cảnh truy hồi, không trên câu trả lời.
        assert so_lan_llm == 1
        assert sinh == []

    # Chiều thứ hai: hai vai không thể cho cùng một tập khóa.
    assert (
        thu["tech_support"][1][f"{khong_gian}_hyperedges"]
        < thu["devops"][1][f"{khong_gian}_hyperedges"]
    )


def test_devops_thay_hyperedge_l1_nhung_khong_thay_chunk_cua_no(
    workspace_dir, khong_gian, policy, bang
):
    """Ngưỡng theo namespace: L1 cho hyperedge, L2 cho chunk (NFR-06).

    `devops` ở mức L1 với `bi_mat_ha_tang` nên thấy hyperedge HE-03, nhưng
    nguyên văn chunk cắt ra từ tài liệu đó thì không. Đây là lỗ mà adapter KV
    của story 1.5 bịt, kiểm lần đầu trên đường e2e thật.
    """

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(tai_khoan="dev01", vai="devops", khong_gian=khong_gian)
        return await hoi(engine, ngu_canh_cua(dt, policy))

    ngu_canh = asyncio.run(chay())
    he3 = THEO_ID["HE-03"]
    assert oracle.muc_ky_vong(bang, "devops", he3["content_type"]) == "L1"
    assert ten_hyperedge(he3) in ngu_canh
    assert "chunk-HE-03" not in chunk_trong(ngu_canh)


# --- 1.7-INT-002: hai truy vấn song song không lẫn ngữ cảnh ----------------


def test_hai_truy_van_song_song_khong_lan_ngu_canh(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-002`: hai vai cùng lúc trong pipeline, mỗi kết quả đúng vai nó."""

    async def chay():
        engine, client, _, _ = await cong_m1(workspace_dir, khong_gian, policy)

        async def mot_vai(dt):
            return dt.vai, await hoi(engine, ngu_canh_cua(dt, policy))

        ket_qua = await asyncio.gather(*[mot_vai(dt) for dt in danh_tinh_demo])
        khoa = [
            khoa_trong_filter(lg.kwargs["query_filter"])
            for lg in client.cac_loi_goi("query_points")
            if lg.kwargs["collection_name"] == f"{khong_gian}_hyperedges"
        ]
        return dict(ket_qua), khoa

    theo_vai, khoa = asyncio.run(chay())
    for vai, ngu_canh in theo_vai.items():
        assert ten_hyperedge_trong(ngu_canh) == ten_hyperedge_ky_vong(bang, vai)
    assert theo_vai["tech_support"] != theo_vai["devops"]
    # Không có request nào mang một tập khóa lạ: mỗi request thuộc về đúng một
    # trong hai vai, kể cả khi hai truy vấn đang chồng lên nhau trên cùng loop.
    ky_vong = {
        frozenset(oracle.allowed_keys_ky_vong(bang, vai)["hyperedges"])
        for vai in theo_vai
    }
    assert {frozenset(k) for k in khoa} == ky_vong


def test_vendor_khong_chay_gi_ngoai_event_loop():
    """Bằng chứng cho quyết định không dựng engine per-request.

    AC đòi "có đường lùi engine per-request nếu contextvar đứt qua executor".
    Fan-out của upstream chỉ là `gather`/`as_completed` trên cùng một event
    loop, nơi contextvar được kế thừa, nên đường lùi đó không cần dựng. Đây là
    bằng chứng chứ không phải lời hứa: thêm một `to_thread` vào `vendor/` là
    test này đỏ, và lúc đó quyết định phải xét lại.
    """
    cac_file = sorted((REPO_ROOT / "vendor").rglob("*.py"))
    # `rglob` ra rỗng thì vòng lặp dưới cũng rỗng và test xanh mà chưa quét gì -
    # một bằng chứng rỗng còn tệ hơn không có bằng chứng, vì nó vẫn được viện
    # dẫn trong quyết định.
    assert len(cac_file) > 5, f"quét vendor/ chỉ ra {len(cac_file)} file .py"
    vi_pham = [
        f"{py.relative_to(REPO_ROOT)}: {dau_hieu}"
        for py in cac_file
        for dau_hieu in DAU_HIEU_THREAD
        if dau_hieu in py.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not vi_pham, "vendor/ chạy code ngoài event loop:\n" + "\n".join(vi_pham)
    # Bộ dò phải bắt được thứ nó nói là bắt được, nếu không nó chỉ là một vòng
    # lặp luôn ra rỗng.
    assert any(
        d in "async def x():\n    await asyncio.to_thread(f)\n" for d in DAU_HIEU_THREAD
    )


# --- 1.7-INT-003: hai danh tính seed, hai ngữ cảnh truy hồi ----------------


def test_hai_danh_tinh_hai_ngu_canh_truy_hoi(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-003`: đúng tiêu chí M1 "hai tài khoản, hai kết quả"."""
    assert {dt.vai for dt in danh_tinh_demo} == {"tech_support", "devops"}

    async def chay():
        engine, client, driver, _ = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        thu = {}
        for dt in danh_tinh_demo:
            client.xoa_nhat_ky()
            driver.xoa_nhat_ky()
            ngu_canh = await hoi(engine, ngu_canh_cua(dt, policy))
            thu[dt.vai] = (
                ngu_canh,
                len(client.cac_loi_goi("query_points")),
                len(driver.cac_cau_doc()),
            )
        return thu

    thu = asyncio.run(chay())
    ngu_canh_ts, so_request_ts, so_cau_ts = thu["tech_support"]
    ngu_canh_dev, _, _ = thu["devops"]
    assert ngu_canh_ts != ngu_canh_dev
    assert ten_hyperedge_trong(ngu_canh_ts) == ten_hyperedge_ky_vong(
        bang, "tech_support"
    )
    assert ten_hyperedge_trong(ngu_canh_dev) == ten_hyperedge_ky_vong(bang, "devops")
    assert ten_hyperedge_trong(ngu_canh_ts) < ten_hyperedge_trong(ngu_canh_dev)
    # Cả hai đường đều thật sự chạy, không phải một đường câm rồi kết luận.
    assert so_request_ts >= 2 and so_cau_ts >= 1


def test_ngu_canh_quyen_phat_tu_danh_tinh_seed(policy, khong_gian):
    """Danh tính seed là nguồn duy nhất của vai; test không tự chế ngữ cảnh."""
    dt = DanhTinh(tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian)
    ngu_canh = ngu_canh_cua(dt, policy)
    assert ngu_canh.role == "tech_support"
    assert ngu_canh.real_account == "ts01"
    assert ngu_canh.space == khong_gian
    assert ngu_canh.bypass_filter is False
    assert ngu_canh.policy_version == policy.policy_version


# --- 1.7-INT-004: Đo 1 lớp (a) - không hyperedge L0 ------------------------


def test_do1_lop_a_khong_hyperedge_l0(workspace_dir, khong_gian, policy, bang):
    """`1.7-INT-004`: vai không thấy hyperedge ở L0, kể cả một mẩu nội dung.

    Assert fixture *có* một mục L0 trước đã: một test "vắng mặt" trên một
    fixture không có gì để vắng mặt là một test luôn xanh.
    """

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(
            tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian
        )
        return await hoi(engine, ngu_canh_cua(dt, policy))

    ngu_canh = asyncio.run(chay())
    he3 = THEO_ID["HE-03"]
    assert oracle.muc_ky_vong(bang, "tech_support", he3["content_type"]) == "L0"
    assert "HE-03" not in oracle.hyperedge_thay_duoc(bang, "tech_support", HYPEREDGES)
    assert ten_hyperedge(he3) not in ngu_canh
    for slot, gia_tri in he3["slots"].items():
        assert gia_tri not in ngu_canh, f"nội dung slot {slot} của HE-03 lọt ra"
    # Chunk của tài liệu L0 cũng phải vắng mặt, không chỉ hyperedge.
    assert "chunk-HE-03" not in chunk_trong(ngu_canh)


# --- 1.7-INT-005: Đo 1 lớp (b) - không nội dung slot đã che ----------------


def test_do1_lop_b_khong_noi_dung_slot_da_che(
    workspace_dir, khong_gian, policy, bang, danh_tinh_demo
):
    """`1.7-INT-005`: nguyên văn slot bị che không xuất hiện ở *bất kỳ đâu*.

    Kỳ vọng lấy từ `oracle.slot_phai_che`, tính từ bảng YAML và nhãn fixture.
    Phạm vi là các hyperedge mà vai thấy ở **mức L1** - đúng phạm vi mà che là
    cơ chế quyền (L0 thì hyperedge vắng mặt hẳn, đó là lớp (a)).

    Ở L2 còn đúng một slot phải tổng quát hóa (`owner`), và ở đó tên người phụ
    trách vẫn ra nguyên văn qua kho vector `entities` và qua nguyên văn chunk -
    hai đường mà tầng che của Epic 1 không chạm tới. Khoản đó nằm trong ledger
    với địa chỉ story, không giấu bằng cách thu hẹp assert một cách im lặng.
    """

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        return {
            dt.vai: await hoi(engine, ngu_canh_cua(dt, policy))
            for dt in danh_tinh_demo
        }

    theo_vai = asyncio.run(chay())
    da_kiem = 0
    for vai, ngu_canh in theo_vai.items():
        for he in HYPEREDGES:
            if oracle.muc_ky_vong(bang, vai, he["content_type"]) != "L1":
                continue
            if he["id"] not in oracle.hyperedge_thay_duoc(bang, vai, HYPEREDGES):
                continue
            phai_che = oracle.slot_phai_che(bang, vai, he)
            assert phai_che, f"{vai}/{he['id']} ở L1 mà oracle không đòi che gì"
            for slot in phai_che:
                gia_tri = he["slots"][slot]
                assert gia_tri not in ngu_canh, (
                    f"nguyên văn slot {slot!r} của {he['id']} lọt vào ngữ cảnh"
                    f" của vai {vai}"
                )
                assert oracle.dau_che_ky_vong(slot) in ngu_canh, (
                    f"dấu che của slot {slot!r} không có mặt: fact biến mất"
                    " khỏi ngữ cảnh thay vì bị che (FR-12)"
                )
                da_kiem += 1
    assert da_kiem, "không ca L1 nào được kiểm, bộ test đang rỗng"


def test_do1_lop_b_phu_dung_hang_io_matrix(workspace_dir, khong_gian, policy):
    """Hàng I/O Matrix, viết thẳng: `tech_support` với `bao_cao_su_co` ở L1."""

    async def chay():
        engine, _, _, _ = await cong_m1(workspace_dir, khong_gian, policy)
        dt = DanhTinh(
            tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian
        )
        return await hoi(engine, ngu_canh_cua(dt, policy))

    ngu_canh = asyncio.run(chay())
    he2 = THEO_ID["HE-02"]
    for slot in ("cause", "source", "remediation"):
        assert he2["slots"][slot] not in ngu_canh
    # Fact vẫn có mặt: che là thay giá trị, không phải xóa fact (FR-12).
    assert ten_hyperedge(he2) in ngu_canh
    assert he2["slots"]["symptom"] in ngu_canh


def test_tripwire_ten_hyperedge_chua_mang_nguyen_van_slot_bi_che(bang):
    """Tripwire cho lỗ L1 `hyperedge_name`, giữ làm canh fixture.

    `hyperedge_name` vừa là payload vector vừa là id node hyperedge, và nó đi
    thẳng vào cột `hyperedge` của bảng Relationships gửi LLM
    (`operate.py:952,987`). Tầng che không chạm được nó: đó là văn bản tự do,
    không tách theo slot.

    Story 2.4 đã đóng lỗ trên đường trích xuất thật bằng id mờ `he-<băm slot>`
    (`core.facts.id_fact`; kiểm ở `tests/test_trich_xuat.py`). Fixture Epic 1
    vẫn đặt tên riêng (`subject - content_type`), nên tripwire ở lại để một lần
    sửa fixture không đưa giá trị slot bị che vào tên.
    """
    for vai in ("tech_support", "devops"):
        for he in HYPEREDGES:
            for slot in oracle.slot_phai_che(bang, vai, he):
                assert he["slots"][slot] not in ten_hyperedge(he), (
                    f"tên hyperedge của {he['id']} mang nguyên văn slot"
                    f" {slot!r}, thứ vai {vai} không được thấy"
                )


# --- 1.7-INT-006: Đo 1 lớp (c) - đổi vai, ngữ cảnh thu hẹp ngay ------------


def test_do1_lop_c_doi_vai_thu_hep_ngay_truy_van_ke_tiep(
    workspace_dir, khong_gian, policy, bang
):
    """`1.7-INT-006`: cùng engine, vai hẹp hỏi sau vai rộng, không dựng lại index."""

    async def chay():
        engine, client, driver, _ = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        dev = DanhTinh(tai_khoan="dev01", vai="devops", khong_gian=khong_gian)
        ts = DanhTinh(
            tai_khoan="ts01", vai="tech_support", khong_gian=khong_gian
        )
        rong = await hoi(engine, ngu_canh_cua(dev, policy))
        hep = await hoi(engine, ngu_canh_cua(ts, policy))
        dung_lai_kho = (
            client.cac_loi_goi("create_collection")
            + client.cac_loi_goi("create_payload_index")
            + [lg for lg in driver.loi_goi if lg.cypher.startswith("CREATE INDEX")]
        )
        return rong, hep, dung_lai_kho

    rong, hep, dung_lai_kho = asyncio.run(chay())
    assert ten_hyperedge_trong(hep) < ten_hyperedge_trong(rong)
    assert ten_hyperedge_trong(hep) == ten_hyperedge_ky_vong(bang, "tech_support")
    assert chunk_trong(hep) < chunk_trong(rong)
    assert dung_lai_kho == [], "đổi vai mà phải dựng lại index (NFR-09)"


# --- 1.7-INT-007: Đo 1 lớp (e) - fail-closed toàn tuyến --------------------


def test_do1_lop_e_thieu_ngu_canh_la_fail_closed(workspace_dir, khong_gian, policy):
    """`1.7-INT-007`: `aquery` không bọc `use_context` thì không trả ngữ cảnh nào."""

    async def chay():
        engine, client, driver, _ = await cong_m1(
            workspace_dir, khong_gian, policy
        )
        with pytest.raises(PermissionContextMissing) as loi:
            await engine.aquery(CAU_HOI, QueryParam(only_need_context=True))
        return loi.value.code, client.cac_loi_goi("query_points"), driver.cac_cau_doc()

    ma, request, cau_doc = asyncio.run(chay())
    assert ma == "PERMISSION_CONTEXT_MISSING"
    assert request == [], "có search request đi ra khi chưa có ngữ cảnh quyền"
    assert cau_doc == [], "có câu đọc graph đi ra khi chưa có ngữ cảnh quyền"


# --- Danh tính seed --------------------------------------------------------


def test_seed_danh_tinh_doc_duoc_hai_vai():
    """Seed tối giản: hai danh tính demo, chưa JWT (FR-17 thuộc Epic 3)."""
    danh_tinh = nap_danh_tinh()
    assert len(danh_tinh) == 2
    assert all(isinstance(dt, DanhTinh) for dt in danh_tinh)
    assert {dt.vai for dt in danh_tinh} == {"tech_support", "devops"}
    assert len({dt.tai_khoan for dt in danh_tinh}) == 2
    assert DUONG_DAN_DANH_TINH_DEMO.exists()


# Mỗi dòng là một cách file seed hỏng, và mỗi cách đều có một luật từ chối
# riêng trong loader. Không parametrize thì phần lớn các luật đó không có test
# nào chạy vào - xóa khối chống trùng tài khoản mà không gì đỏ là dấu hiệu đúng
# của chuyện đó.
SEED_HONG = {
    "danh_sach_rong": "version: 1\ndanh_tinh: []\n",
    "thieu_khoi": "version: 1\n",
    "goc_khong_phai_mapping": "- version: 1\n",
    "goc_rong": "",
    "version_sai": "version: 2\ndanh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n",
    "version_thieu": "danh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n",
    "version_la_bool": "version: true\ndanh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n",
    "thieu_vai": "version: 1\ndanh_tinh:\n  - {tai_khoan: x, khong_gian: synth}\n",
    "muc_khong_phai_mapping": "version: 1\ndanh_tinh:\n  - ts01\n",
    "truong_la_trong_muc": (
        "version: 1\ndanh_tinh:\n"
        "  - {tai_khoan: x, vai: y, khong_gian: synth, allowed_keys: [a]}\n"
    ),
    # Khóa lạ ở *cấp gốc*: đây đúng là ca mà docstring module lấy làm lý do tồn
    # tại - một khối `allowed_keys:` cấp gốc nạp bình thường thì người viết seed
    # tin rằng mình vừa cấp quyền, mà không ai đọc nó.
    "khoa_la_o_goc": (
        "version: 1\nallowed_keys: [noi_bo:runbook]\n"
        "danh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: synth}\n"
    ),
    "tai_khoan_trung": (
        "version: 1\ndanh_tinh:\n"
        "  - {tai_khoan: ts01, vai: tech_support, khong_gian: synth}\n"
        "  - {tai_khoan: ts01, vai: devops, khong_gian: synth}\n"
    ),
    "tai_khoan_rong": "version: 1\ndanh_tinh:\n  - {tai_khoan: '', vai: y, khong_gian: synth}\n",
    "vai_co_khoang_trang": (
        "version: 1\ndanh_tinh:\n  - {tai_khoan: x, vai: ' devops ', khong_gian: synth}\n"
    ),
    "khong_gian_sai_ky_tu": (
        "version: 1\ndanh_tinh:\n  - {tai_khoan: x, vai: y, khong_gian: '1-synth'}\n"
    ),
    "yaml_hong": "version: 1\ndanh_tinh: [\n",
}


@pytest.mark.parametrize("ten", sorted(SEED_HONG))
def test_seed_danh_tinh_hong_thi_tu_choi_nap(tmp_path, ten):
    """File seed hỏng là từ chối nạp, không phải chạy với danh sách rỗng.

    Assert trên `code` chứ không trên thông điệp: mã lỗi là hợp đồng (AD-8),
    câu chữ thì không.
    """
    xau = tmp_path / f"{ten}.yaml"
    xau.write_text(SEED_HONG[ten], encoding="utf-8")
    with pytest.raises(IdentitySeedInvalid) as loi:
        nap_danh_tinh(xau)
    assert loi.value.code == "IDENTITY_SEED_INVALID"


def test_seed_danh_tinh_thieu_file(tmp_path):
    """Đường dẫn không tồn tại cũng ra đúng một loại lỗi, kèm tên file."""
    with pytest.raises(IdentitySeedInvalid) as loi:
        nap_danh_tinh(tmp_path / "khong-co.yaml")
    assert loi.value.code == "IDENTITY_SEED_INVALID"
    assert "khong-co.yaml" in str(loi.value)


# --- `DanhTinh`: cửa kiểm của chính bản ghi danh tính ----------------------


@pytest.mark.parametrize(
    "truong", ["tai_khoan", "vai", "khong_gian"]
)
@pytest.mark.parametrize(
    "gia_tri,lop_loi",
    [("", ValueError), ("   ", ValueError), (" ts01 ", ValueError), (None, TypeError), (1, TypeError)],
    ids=["rong", "toan_khoang_trang", "khoang_trang_bao_quanh", "None", "so"],
)
def test_danh_tinh_tu_choi_gia_tri_hong(truong, gia_tri, lop_loi):
    """Ba trường, năm cách hỏng; không có cửa này thì xóa `__post_init__` mà không gì đỏ.

    `" ts01 "` bị từ chối chứ không bị cắt hộ: một danh tính lệch một dấu cách
    là một danh tính khác mà nhìn không ra, và cắt hộ nghĩa là seed nói một
    đằng còn hệ chạy một nẻo.
    """
    hop_le = {"tai_khoan": "ts01", "vai": "devops", "khong_gian": "synth"}
    hop_le[truong] = gia_tri
    with pytest.raises(lop_loi):
        DanhTinh(**hop_le)


def test_vai_khong_co_trong_bang_chinh_sach_la_loi_co_ma(policy, khong_gian):
    """Vai lạ là `RoleUnknown` có `code`, không phải `KeyError` trần.

    Cũng không phải một ngữ cảnh không thấy gì: ngữ cảnh rỗng chạy tiếp được và
    trông giống hệt "người này không được xem gì", nên nó giấu một seed sai cho
    tới lúc có người hỏi vì sao mình không thấy tài liệu nào.
    """
    dt = DanhTinh(tai_khoan="x01", vai="vai_khong_co_that", khong_gian=khong_gian)
    with pytest.raises(RoleUnknown) as loi:
        ngu_canh_cua(dt, policy)
    assert loi.value.code == "ROLE_UNKNOWN"
    assert "x01" in str(loi.value) and "vai_khong_co_that" in str(loi.value)


def test_ngu_canh_cua_tu_choi_kieu_khac(policy):
    """Chữ ký là `DanhTinh`, không phải một dict trông giống nó."""
    with pytest.raises(TypeError):
        ngu_canh_cua({"vai": "devops"}, policy)


def test_danh_tinh_la_bat_bien():
    """`DanhTinh` đóng băng: một danh tính đổi vai giữa chừng là leo quyền."""
    dt = DanhTinh(tai_khoan="ts01", vai="tech_support", khong_gian="synth")
    # Đúng lớp lỗi, không phải `Exception`: `pytest.raises(Exception)` xanh cả
    # khi test gõ nhầm tên thuộc tính và nhận `AttributeError`, tức là nó xanh
    # mà không chứng minh gì về việc đóng băng.
    with pytest.raises(FrozenInstanceError):
        dt.vai = "devops"

