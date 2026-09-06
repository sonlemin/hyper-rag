"""Audit hai tầng đầy đủ (story 3.6, AD-16, ADR-017).

Đặc tả viết trước cơ chế (FR-27): mọi hàng I/O Matrix của spec 3.6 nằm ở đây,
cộng bốn mệnh đề mà không hàng nào phát biểu được một mình.

- **Sự kiện lọc chỉ phát từ tầng post-filter, và chỉ mang số đếm.** Adapter KV
  là tầng duy nhất so khóa từng bản ghi sau khi đọc; Qdrant và Neo4j pre-filter
  nên không có mục bị loại để đếm (chốt brief §6). Hàng `filter` mang namespace
  và số đếm theo mức, `hyperedge_ids` rỗng, không id, không nội dung, và kết
  quả trả về của adapter không đổi một byte có hay không có port (AD-8).
- **Tầng của `refusal` khai theo cờ chế độ đo, không theo `event`.** Cờ tắt thì
  observation như 3.5; cờ bật thì mutation và ghi hỏng là 500 `AUDIT_GHI_HONG`.
  Thân 200 của hai chế độ giống nhau từng byte.
- **Sự kiện tiến trình mang `space="*"`**, và mọi tổng theo space không thấy
  chúng: `startup` là mốc của một cửa sổ đo, `auth_login` hai chiều là cửa đếm
  của 3-8, `policy_swap` đã có từ 3.2.
- **Một lượt nối được các hàng của nó** bằng `request_id` trong `chi_tiet`,
  chở trong `PermissionContext` chứ không qua một contextvar thứ hai; không vào
  response.

Ba lớp. Lớp hàm thuần (`core/`, `adapters/cua_khoa_doc.py`, `api/che_do_do.py`,
`api/xac_thuc.py`). Lớp adapter và engine cổng M1 thật (ba adapter, LLM giả,
`SoAuditBoNho`), chấm số đếm lọc bằng oracle độc lập. Lớp HTTP qua `TestClient`
với `AuditGia` khỏe và hỏng. Phần cần Postgres thật (marker `postgres`) nằm ở
`tests/test_audit_postgres.py`.
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypergraphrag.utils import compute_mdhash_id

from adapters.cua_khoa_doc import MUC_BI_LOAI_L0, MUC_BI_LOAI_L1, muc_bi_loai
from adapters.kv import CT_BI_LOAI, CT_NAMESPACE, JsonACLKVStorage
from adapters.policy_loader import load_policy
from adapters.tra_loi import LY_DO_CO_NO_ANSWER, LY_DO_NGU_CANH_RONG
from adapters.trich_dan import TrichDanNgoaiQuyen
from adapters.trich_xuat import TIEN_TO_ID_VECTOR, id_vector_cua
from api import main as api_main
from api.audit_postgres import AuditPostgres
from api.che_do_do import (
    BIEN_CHE_DO_DO,
    CT_CHE_DO_DO,
    CT_POLICY_ID,
    CT_POLICY_VERSION,
    MA_CHE_DO_DO_KHONG_HOP_LE,
    CheDoDoKhongHopLe,
    doc_che_do_do,
    su_kien_startup,
)
from api.chinh_sach import ID_MAC_DINH, SPACE_TOAN_HE, KhoChinhSach
from api.hoi_dap import CT_LY_DO, CT_MA, CT_MILI_GIAY, MA_AUDIT_GHI_HONG, MA_TRICH_DAN_NGOAI_QUYEN
from api.xac_thuc import (
    BIEN_KHOA_KY,
    CT_KET_QUA,
    DAI_ACT_TOI_DA,
    KET_QUA_THANH_CONG,
    KET_QUA_THAT_BAI,
    MA_DANG_NHAP_SAI,
    su_kien_dang_nhap,
)
from core.audit import (
    CT_REQUEST_ID,
    EVENT_AUTH_LOGIN,
    EVENT_EMBEDDING_COST,
    EVENT_FILTER,
    EVENT_LLM_COST,
    EVENT_PERMISSION_MISMATCH,
    EVENT_QUERY,
    EVENT_REFUSAL,
    EVENT_STARTUP,
    EVENTS,
    SPACE_TIEN_TRINH,
    TIER_MUTATION,
    TIER_OBSERVATION,
)
from core.facts import TIEN_TO_ID_FACT
from core.ids import validate_space
from core.permission import use_context, user_context
from core.system_context import system_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES
from tests.gia_lap_llm import SoAuditBoNho, phan_hoi_hai_luot
from tests.ho_tro_ingest import dung_moi_truong, llm_theo_fact, viet_tai_lieu
from tests.ho_tro_m1 import CAU_HOI, cong_m1
from tests.ngu_canh import vai
from tests.test_xac_thuc import KHOA_TEST, MAT_KHAU, TEN_GO, AuditGia, EngineGia, KhoGia, _dong

GOC = Path(__file__).resolve().parent.parent
ADR_017 = GOC / "docs" / "adr" / "ADR-017-co-che-do-do-va-su-kien-loc.md"

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")


# --- Lớp 1: hàm thuần -----------------------------------------------------------


def test_bon_su_kien_moi_va_hang_space_tien_trinh_o_core():
    """Bốn hằng `event` mới nằm trong danh mục đóng; `"*"` có tên và không phải space thật."""
    assert {EVENT_FILTER, EVENT_AUTH_LOGIN, EVENT_STARTUP, EVENT_PERMISSION_MISMATCH} <= EVENTS
    assert SPACE_TIEN_TRINH == "*" and SPACE_TOAN_HE is SPACE_TIEN_TRINH
    with pytest.raises(ValueError):
        validate_space(SPACE_TIEN_TRINH)
    assert CT_REQUEST_ID == "request_id"


def test_request_id_di_theo_kenh_ngu_canh_quyen(policy):
    """`user_context` phát `request_id`, ingest để `None`, sai kiểu là lỗi lúc dựng."""
    ctx = user_context(policy=policy, role="devops", space="synth", real_account="dev01", request_id="r-1")
    assert ctx.request_id == "r-1"
    assert user_context(policy=policy, role="devops", space="synth", real_account="dev01").request_id is None
    assert system_context(space="synth", policy_version=policy.policy_version).request_id is None
    with pytest.raises(TypeError):
        replace(ctx, request_id=7)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(ctx, request_id="")


class _NguCanhGia:
    def __init__(self, hyperedges: frozenset[str]):
        self.bypass_filter = False
        self._he = hyperedges

    def keys_for(self, namespace):
        return self._he if namespace == "hyperedges" else frozenset()


def test_muc_bi_loai_la_muc_cua_vai_voi_muc_do():
    """Khóa nằm trong tập khóa hyperedge -> vai thấy ở L1, chunk chặn bởi luật L2 -> `L1`; còn lại `L0`."""
    ctx = _NguCanhGia(frozenset({"noi_bo:bao_cao_su_co"}))
    assert muc_bi_loai(ctx, "noi_bo:bao_cao_su_co") == MUC_BI_LOAI_L1 == "L1"
    assert muc_bi_loai(ctx, "noi_bo:bi_mat_ha_tang") == MUC_BI_LOAI_L0 == "L0"
    assert muc_bi_loai(ctx, None) == MUC_BI_LOAI_L0, "bản ghi không khóa vô hình với mọi vai: L0"


@pytest.mark.parametrize(
    "moi_truong, ky_vong",
    [({}, False), ({BIEN_CHE_DO_DO: ""}, False), ({BIEN_CHE_DO_DO: "0"}, False), ({BIEN_CHE_DO_DO: " 1 "}, True)],
)
def test_doc_co_che_do_do_chi_nhan_0_va_1(moi_truong, ky_vong):
    assert doc_che_do_do(moi_truong) is ky_vong


@pytest.mark.parametrize("xau", ["yes", "true", "on", "2", "bật"])
def test_co_che_do_do_gia_tri_la_la_loi_co_ma(xau):
    """Hàng "Cờ sai giá trị": không đoán `yes` là bật; một cấu hình gõ sai phải nổ."""
    with pytest.raises(CheDoDoKhongHopLe) as loi:
        doc_che_do_do({BIEN_CHE_DO_DO: xau})
    assert loi.value.code == MA_CHE_DO_DO_KHONG_HOP_LE == "CHE_DO_DO_KHONG_HOP_LE"


def test_su_kien_startup_mutation_space_tien_trinh_ba_khoa():
    kho = KhoChinhSach.nap(ID_MAC_DINH)
    sk = su_kien_startup(kho, True)
    assert (sk.tier, sk.event, sk.space) == (TIER_MUTATION, EVENT_STARTUP, SPACE_TIEN_TRINH)
    assert sk.policy_version == kho.hien_tai().policy_version
    assert dict(sk.chi_tiet) == {
        CT_POLICY_ID: ID_MAC_DINH,
        CT_POLICY_VERSION: kho.hien_tai().policy_version,
        CT_CHE_DO_DO: True,
    }
    assert (sk.act, sk.role, sk.hyperedge_ids) == (None, None, ())


def test_su_kien_dang_nhap_hai_chieu_mot_khoa_khong_ly_do():
    """`act` là tên gõ vào, `chi_tiet` đúng một khóa `ket_qua`, không trường nào nói vì sao sai."""
    dung = su_kien_dang_nhap("TS01", True, "v")
    sai = su_kien_dang_nhap("ai-do", False, "v")
    hong = su_kien_dang_nhap(None, False, "v")
    for sk in (dung, sai, hong):
        assert (sk.tier, sk.event, sk.space, sk.role) == (TIER_OBSERVATION, EVENT_AUTH_LOGIN, SPACE_TIEN_TRINH, None)
        assert set(sk.chi_tiet) == {CT_KET_QUA}
    assert (dung.act, dung.chi_tiet[CT_KET_QUA]) == ("TS01", KET_QUA_THANH_CONG)
    assert (sai.act, sai.chi_tiet[CT_KET_QUA]) == ("ai-do", KET_QUA_THAT_BAI)
    assert hong.act is None and hong.chi_tiet[CT_KET_QUA] == KET_QUA_THAT_BAI
    # Tên gõ vào là đầu vào tự do: cắt về `DAI_ACT_TOI_DA`, rỗng thành `None`.
    assert DAI_ACT_TOI_DA == 64
    assert su_kien_dang_nhap("x" * 500, False, "v").act == "x" * 64
    assert su_kien_dang_nhap("", False, "v").act is None


def test_anh_xa_hai_quy_uoc_id_co_ten_va_ghim_hai_tien_to():
    """`id_vector_cua` là `rel-` + md5 của id node `he-…`; hai tiền tố ghim bằng giá trị."""
    assert TIEN_TO_ID_FACT == "he-" and TIEN_TO_ID_VECTOR == "rel-"
    he_id = "he-0123456789abcdef01234567"
    assert id_vector_cua(he_id) == compute_mdhash_id(he_id, prefix="rel-")
    assert id_vector_cua(he_id).startswith("rel-") and id_vector_cua(he_id) != id_vector_cua("he-khac")


def test_dem_su_kien_tu_choi_event_la_va_moc_khong_utc_truoc_khi_cham_pool():
    audit = AuditPostgres(pool=None)

    async def chay():
        with pytest.raises(ValueError):
            await audit.dem_su_kien("khong_co", space="synth")
        with pytest.raises(ValueError):
            await audit.dem_su_kien(EVENT_REFUSAL, space="synth", tu="2026-09-06T10:00:00+07:00")
        with pytest.raises(TypeError):
            await audit.dem_su_kien(EVENT_REFUSAL, space="synth", theo=3)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await audit.su_kien_tien_trinh(tu="2026-09-06T10:00:00")
        # Ba phép từ chối của vòng review: space tiến trình / space lạ, cửa sổ rỗng, `theo` rỗng.
        with pytest.raises(ValueError, match="su_kien_tien_trinh"):
            await audit.dem_su_kien(EVENT_REFUSAL, space=SPACE_TIEN_TRINH)
        with pytest.raises(ValueError):
            await audit.dem_su_kien(EVENT_REFUSAL, space="Khong Hop Le")
        with pytest.raises(ValueError, match="cửa sổ rỗng"):
            await audit.dem_su_kien(
                EVENT_REFUSAL, space="synth", tu="2026-09-06T10:00:00+00:00", den="2026-09-06T10:00:00+00:00"
            )
        with pytest.raises(ValueError, match="cửa sổ rỗng"):
            await audit.su_kien_tien_trinh(tu="2026-09-06T11:00:00+00:00", den="2026-09-06T10:00:00+00:00")
        with pytest.raises(ValueError, match="theo rỗng"):
            await audit.dem_su_kien(EVENT_REFUSAL, space="synth", theo="")
        with pytest.raises(ValueError):
            await audit.su_kien_tien_trinh(gioi_han=0)

    asyncio.run(chay())


# --- Lớp 2a: adapter KV -------------------------------------------------------------


def _kho_kv(workspace_dir, khong_gian, audit):
    kho = JsonACLKVStorage(
        namespace="text_chunks",
        global_config={"working_dir": str(workspace_dir)},
        embedding_func=None,
        audit=audit,
    )
    kho._kho[khong_gian] = {
        "c-runbook": {"content": "sop", "filter_key": "noi_bo:runbook"},
        "c-su-co": {"content": "inc", "filter_key": "noi_bo:bao_cao_su_co"},
        "c-bi-mat": {"content": "ssh", "filter_key": "noi_bo:bi_mat_ha_tang"},
        "c-khong-khoa": {"content": "x", "filter_key": None},
    }
    return kho


def _chay(coro):
    return asyncio.run(coro)


def test_get_by_id_bi_loai_o_l1_phat_dung_mot_hang_filter(workspace_dir, khong_gian, policy):
    """Hàng đầu I/O Matrix ở tầng adapter: `tech_support` đọc chunk của một hyperedge L1."""
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)
    ctx = replace(vai(policy, "tech_support", khong_gian), request_id="r-7f3a")

    async def chay():
        with use_context(ctx):
            kq = await kho.get_by_id("c-su-co")
            # Ngữ cảnh mang `request_id`: hàng phát khi lượt xả sổ, không ở từng lời gọi.
            assert so.su_kien == []
            await kho.xa_loc("r-7f3a")
            return kq

    assert _chay(chay()) is None
    hang = so.cac_su_kien(EVENT_FILTER)
    assert len(hang) == 1 and so.su_kien == hang
    sk = hang[0]
    assert sk.tier == TIER_OBSERVATION and sk.hyperedge_ids == ()
    assert (sk.space, sk.policy_version, sk.act, sk.role) == (khong_gian, policy.policy_version, "tech_support01", "tech_support")
    assert dict(sk.chi_tiet) == {CT_NAMESPACE: "text_chunks", CT_BI_LOAI: {"L1": 1}, CT_REQUEST_ID: "r-7f3a"}


def test_get_by_ids_gom_theo_muc_khong_id_khong_noi_dung(workspace_dir, khong_gian, policy):
    """Một lời gọi, một hàng: `L1` cho hyperedge vai thấy, `L0` cho thứ vai không thấy và bản ghi không khóa."""
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)

    async def chay():
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await kho.get_by_ids(["c-runbook", "c-su-co", "c-bi-mat", "c-khong-khoa", "c-vang"])

    kq = _chay(chay())
    assert [r is None for r in kq] == [False, True, True, True, True]
    (sk,) = so.cac_su_kien(EVENT_FILTER)
    assert sk.chi_tiet[CT_BI_LOAI] == {"L0": 2, "L1": 1}, "mục vắng mặt thật không đếm, mục bị loại thì đếm theo mức"
    van_ban = json.dumps(dict(sk.chi_tiet), ensure_ascii=False)
    for cam in ("c-su-co", "c-bi-mat", "inc", "ssh", "filter_key"):
        assert cam not in van_ban, f"hàng filter lộ {cam!r}"


def test_all_keys_va_filter_keys_cung_dem(workspace_dir, khong_gian, policy):
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)

    async def chay():
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await kho.all_keys(), await kho.filter_keys(["c-runbook", "c-bi-mat", "c-moi"])

    keys, chua_co = _chay(chay())
    assert keys == ["c-runbook"] and chua_co == {"c-bi-mat", "c-moi"}
    assert [dict(sk.chi_tiet[CT_BI_LOAI]) for sk in so.cac_su_kien(EVENT_FILTER)] == [{"L0": 2, "L1": 1}, {"L0": 1}]


@pytest.mark.parametrize("ten_vai", ["devops", "tech_support"])
def test_khong_muc_nao_bi_loai_thi_khong_hang(workspace_dir, khong_gian, policy, ten_vai):
    """Hàng "Không mục nào bị loại": đọc thứ vai được đọc, sổ audit trống."""
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)

    async def chay():
        with use_context(vai(policy, ten_vai, khong_gian)):
            return await kho.get_by_id("c-runbook"), await kho.get_by_ids(["c-runbook", "c-vang"])

    a, b = _chay(chay())
    assert a is not None and b[0] is not None and b[1] is None
    assert so.su_kien == []


def test_ngu_canh_he_thong_khong_phat_va_vang_port_khong_loi(workspace_dir, khong_gian, policy):
    """Hàng "Ingest dưới cờ hệ thống": đọc thô không loại gì, không hàng; `audit=None` là im lặng."""
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)
    khong_port = _kho_kv(workspace_dir, khong_gian, None)

    async def chay():
        with use_context(system_context(space=khong_gian, policy_version=policy.policy_version)):
            he_thong = await kho.get_by_ids(["c-su-co", "c-bi-mat", "c-khong-khoa"])
        with use_context(vai(policy, "tech_support", khong_gian)):
            vai_ts = await khong_port.get_by_ids(["c-su-co", "c-bi-mat"])
        return he_thong, vai_ts

    he_thong, vai_ts = _chay(chay())
    assert all(r is not None for r in he_thong) and vai_ts == [None, None]
    assert so.su_kien == []
    assert khong_port.audit is None


def test_ket_qua_doc_khong_doi_co_hay_khong_co_port_va_port_hong_chi_warning(
    workspace_dir, khong_gian, policy, caplog
):
    """AD-8: số đếm lọc không vào kết quả; port hỏng là WARNING, kết quả vẫn y nguyên."""
    hong = SoAuditBoNho(loi=RuntimeError("postgres chết"))
    co = _kho_kv(workspace_dir, khong_gian, hong)
    khong = _kho_kv(workspace_dir, khong_gian, None)
    ids = ["c-runbook", "c-su-co", "c-bi-mat", "c-khong-khoa"]

    async def chay(kho):
        with use_context(vai(policy, "tech_support", khong_gian)):
            return await kho.get_by_ids(ids), await kho.get_by_id("c-su-co"), await kho.all_keys()

    with caplog.at_level("WARNING"):
        kq_co = _chay(chay(co))
    kq_khong = _chay(chay(khong))
    assert kq_co == kq_khong
    assert any("audit observation filter" in r.getMessage() for r in caplog.records), caplog.text


def test_tap_khoa_rong_khong_cham_kho_va_khong_dem(workspace_dir, khong_gian, policy):
    """Nhánh "không thấy gì" không chạm kho nên không biết mục có tồn tại; không bịa số."""
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)
    ctx = replace(
        vai(policy, "tech_support", khong_gian),
        allowed_keys={"chunks": frozenset(), "hyperedges": frozenset(), "entities": frozenset()},
    )

    async def chay():
        with use_context(ctx):
            return await kho.get_by_ids(["c-su-co"])

    assert _chay(chay()) == [None] and so.su_kien == []


# --- Lớp 2b: engine cổng M1 thật -----------------------------------------------------


def _engine_m1(workspace_dir, khong_gian, policy):
    engine, client, driver, llm = asyncio.run(cong_m1(workspace_dir, khong_gian, policy))
    llm.theo_prompt = phan_hoi_hai_luot()
    return engine, llm


def _hoi_dap(engine, ngu_canh):
    async def chay():
        with use_context(ngu_canh):
            return await engine.hoi_dap(CAU_HOI)

    return asyncio.run(chay())


def _ghi_lai_get_by_id(engine) -> list[str]:
    """Bọc `text_chunks.get_by_id` để biết vendor xin những chunk nào - đầu vào của oracle."""
    da_xin: list[str] = []
    goc = engine.text_chunks.get_by_id

    async def _get(id):
        da_xin.append(id)
        return await goc(id)

    engine.text_chunks.get_by_id = _get
    return da_xin


def _ky_vong_bi_loai(bang, ten_vai, da_xin) -> dict[str, int]:
    """Số đếm kỳ vọng theo mức, tính thuần từ oracle trên đúng dãy chunk vendor xin."""
    theo_chunk = {c["id"]: c for c in CHUNKS}
    he_theo_chunk = {he["source_id"]: he for he in HYPEREDGES}
    thay_he = set(oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES))
    doc_duoc = set(oracle.chunk_thay_duoc(bang, ten_vai, CHUNKS))
    ra: dict[str, int] = {}
    for id_chunk in da_xin:
        if id_chunk not in theo_chunk or id_chunk in doc_duoc:
            continue
        he = he_theo_chunk.get(id_chunk)
        muc = "L1" if he is not None and he["id"] in thay_he else "L0"
        ra[muc] = ra.get(muc, 0) + 1
    return ra


@pytest.mark.parametrize("ten_vai", ["devops", "tech_support"])
def test_ac2_hang_filter_tren_engine_m1_khop_oracle_va_ket_qua_khong_doi(
    workspace_dir, khong_gian, policy, bang, ten_vai
):
    """AC-2 trên bảng vận hành: số đếm theo mức bằng oracle độc lập, response y hệt bản 3.4.

    Với `policy-day-du.yaml` **cả hai vai** đều có một mục bị loại ở `L1`
    (`devops` thấy HE-03 ở L1 nên chunk-HE-03 bị chặn; `tech_support` thấy HE-02
    ở L1 nên chunk-HE-02 bị chặn) - oracle nói thế, và ca này chấm bằng oracle
    chứ không bằng một con số chép tay. Ca "vai thấy đủ, không hàng nào" ở ngay
    dưới, trên cấu hình tắt phân quyền.
    """
    engine, _ = _engine_m1(workspace_dir, khong_gian, policy)
    ngu_canh = replace(vai(policy, ten_vai, khong_gian), request_id="r-m1")
    da_xin = _ghi_lai_get_by_id(engine)
    engine.so_audit.xoa()
    kq = _hoi_dap(engine, ngu_canh)
    hang = engine.so_audit.cac_su_kien(EVENT_FILTER)
    # **Đúng một hàng** cho namespace `text_chunks` của lượt, dù vendor xin chunk
    # nhiều lần: sổ cộng dồn theo `request_id`, `xa_loc` phát một lần.
    assert len(hang) == 1, [dict(sk.chi_tiet) for sk in hang]
    (sk,) = hang
    assert sk.tier == TIER_OBSERVATION and sk.hyperedge_ids == ()
    assert sk.chi_tiet[CT_NAMESPACE] == "text_chunks" and sk.chi_tiet[CT_REQUEST_ID] == "r-m1"
    assert (sk.role, sk.space) == (ten_vai, khong_gian)
    gom = dict(sk.chi_tiet[CT_BI_LOAI])
    assert gom == _ky_vong_bi_loai(bang, ten_vai, da_xin)
    assert gom, "fixture M1 phải có ít nhất một mục bị loại cho vai này, nếu không ca này chấm rỗng"
    assert engine.text_chunks._so_loc == {} and engine.full_docs._so_loc == {}, "sổ của lượt phải được xóa"
    # Response không đổi: cùng engine, tắt port ở adapter KV, cùng câu, cùng kết quả.
    engine.text_chunks.audit = None
    assert _hoi_dap(engine, ngu_canh) == kq


def test_vai_thay_du_thi_khong_hang_filter(workspace_dir, khong_gian, bang):
    """Hàng "Không mục nào bị loại": cấu hình tắt phân quyền, `devops` đọc được mọi chunk."""
    policy_mo = load_policy(oracle.POLICY_TAT_PHAN_QUYEN)
    bang_mo = oracle.doc_bang_chinh_sach(oracle.POLICY_TAT_PHAN_QUYEN)
    engine, _ = _engine_m1(workspace_dir, khong_gian, policy_mo)
    da_xin = _ghi_lai_get_by_id(engine)
    engine.so_audit.xoa()
    kq = _hoi_dap(engine, vai(policy_mo, "devops", khong_gian))
    assert kq.trich_dan, "vai thấy đủ phải có citation, nếu không ca này không đo gì"
    assert da_xin, "vendor phải xin chunk thì ca 'không hàng' mới có nghĩa"
    assert _ky_vong_bi_loai(bang_mo, "devops", da_xin) == {}
    assert engine.so_audit.cac_su_kien(EVENT_FILTER) == []


def test_moi_hang_cua_mot_luot_mang_cung_request_id_va_hai_luot_dong_thoi_khong_lan(
    workspace_dir, khong_gian, policy
):
    """Hàng "Hai request đồng thời cùng vai": `llm_cost`/`embedding_cost`/`filter` nối đúng lượt của nó."""
    engine, _ = _engine_m1(workspace_dir, khong_gian, policy)
    engine.so_audit.xoa()
    a = replace(vai(policy, "tech_support", khong_gian), request_id="r-a")
    b = replace(vai(policy, "tech_support", khong_gian), request_id="r-b")

    async def mot(ngu_canh):
        with use_context(ngu_canh):
            return await engine.hoi_dap(CAU_HOI)

    async def chay():
        return await asyncio.gather(mot(a), mot(b))

    asyncio.run(chay())
    assert engine.so_audit.su_kien, "hai lượt phải để lại hàng"
    assert all(CT_REQUEST_ID in sk.chi_tiet for sk in engine.so_audit.su_kien), "mọi hàng của lượt mang khóa request_id"
    theo_id: dict[str, list[str]] = {}
    for sk in engine.so_audit.su_kien:
        theo_id.setdefault(sk.chi_tiet[CT_REQUEST_ID], []).append(sk.event)
    assert set(theo_id) == {"r-a", "r-b"}
    for events in theo_id.values():
        assert events.count(EVENT_LLM_COST) == 2, events
        assert events.count(EVENT_EMBEDDING_COST) >= 1 and events.count(EVENT_FILTER) == 1, events


def test_so_loc_cong_don_theo_luot_va_xa_mot_hang(workspace_dir, khong_gian, policy):
    """Ngữ cảnh mang `request_id`: nhiều lời gọi đọc -> một sổ, `xa_loc` phát đúng một hàng gộp."""
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)
    ctx = replace(vai(policy, "tech_support", khong_gian), request_id="r-gom")

    async def chay():
        with use_context(ctx):
            await kho.get_by_id("c-su-co")
            await kho.get_by_id("c-su-co")
            await kho.get_by_ids(["c-bi-mat", "c-khong-khoa"])
            assert so.su_kien == [], "chưa phát gì trước xa_loc"
            assert kho._so_loc == {"r-gom": {"L1": 2, "L0": 2}}
            await kho.xa_loc("r-gom")
            await kho.xa_loc("r-gom")

    _chay(chay())
    (sk,) = so.cac_su_kien(EVENT_FILTER)
    assert dict(sk.chi_tiet) == {CT_NAMESPACE: "text_chunks", CT_BI_LOAI: {"L0": 2, "L1": 2}, CT_REQUEST_ID: "r-gom"}
    assert (sk.act, sk.role) == ("tech_support01", "tech_support") and kho._so_loc == {}


def test_bo_so_loc_khong_phat_va_xa_loc_luot_rong_khong_hang(workspace_dir, khong_gian, policy):
    so = SoAuditBoNho()
    kho = _kho_kv(workspace_dir, khong_gian, so)
    ctx = replace(vai(policy, "tech_support", khong_gian), request_id="r-hong")

    async def chay():
        with use_context(ctx):
            await kho.get_by_id("c-su-co")
            kho.bo_so_loc("r-hong")
            await kho.xa_loc("r-hong")
            await kho.xa_loc("r-chua-tung-co")

    _chay(chay())
    assert so.su_kien == [] and kho._so_loc == {}


def test_luot_hong_giua_chung_bo_so_loc_khong_de_lai_hang(workspace_dir, khong_gian, policy, monkeypatch):
    """`aquery` nổ sau khi KV đã loại mục: sổ của lượt bị bỏ, không hàng `filter`, không rò sang lượt sau."""
    engine, _ = _engine_m1(workspace_dir, khong_gian, policy)
    engine.so_audit.xoa()
    ctx = replace(vai(policy, "tech_support", khong_gian), request_id="r-no")

    async def aquery_no(cau_hoi, param=None):
        await engine.text_chunks.get_by_id("chunk-HE-02")
        raise RuntimeError("kho nổ giữa chừng")

    monkeypatch.setattr(engine, "aquery", aquery_no)

    async def chay():
        with use_context(ctx):
            await engine.hoi_dap(CAU_HOI)

    with pytest.raises(RuntimeError, match="kho nổ"):
        asyncio.run(chay())
    assert engine.so_audit.cac_su_kien(EVENT_FILTER) == []
    assert engine.text_chunks._so_loc == {} and engine.full_docs._so_loc == {}


def test_khe_lay_audit_tra_none_la_khong_port(workspace_dir):
    from tests.gia_lap_llm import LLMGia
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine

    engine = dung_engine(workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), LLMGia(), lay_audit=lambda: None)
    assert engine.text_chunks.audit is None and engine.full_docs.audit is None


# --- Lớp 2c: hai số đếm trùng của trích xuất -----------------------------------------


THAN_GOP = "Sự cố khách A. app01.company.vn trả lỗi 502 lúc cao điểm; APP-01 trả lỗi 502 lúc cao điểm."
FACT_DAI = {"subject": "app01.company.vn", "symptom": "trả lỗi 502 lúc cao điểm"}
FACT_NGAN = {"subject": "APP-01", "symptom": "trả lỗi 502 lúc cao điểm"}
TU_DIEN = """
version: 1
muc:
  - chuan: App01
    scope: khach_hang_a
    bi_danh: [app01.company.vn, APP-01]
    xac_nhan: "sonlm 2026-09-05"
"""


def test_so_gop_do_bi_danh_tach_khoi_so_trung_do_llm(workspace_dir, khong_gian, policy, tmp_path):
    """Khoản ledger 2.12: hai fact khác nhau mà từ điển gộp về một id là `so_gop_do_bi_danh`, không phải LLM lặp."""
    from adapters.ingest import nap_thu_muc

    tu_dien = tmp_path / "td.yaml"
    tu_dien.write_text(TU_DIEN, encoding="utf-8")
    thu_muc = tmp_path / "corpus"
    viet_tai_lieu(thu_muc, "a.md", scope="khach_hang_a", content_type="bao_cao_su_co", than=THAN_GOP)
    mt = dung_moi_truong(
        workspace_dir,
        llm_theo_fact({THAN_GOP: [FACT_DAI, FACT_NGAN, dict(FACT_NGAN)]}),
        entity_dictionary_path=str(tu_dien),
    )
    kq = asyncio.run(
        nap_thu_muc(mt.engine, thu_muc, space=khong_gian, policy_version=policy.policy_version, audit=mt.so_audit)
    )
    assert kq.tai_lieu[0].so_fact_hop_le == 3 and kq.tai_lieu[0].so_hyperedge == 1
    (sk,) = [s for s in mt.so_audit.cac_su_kien("extract_doc") if s.chi_tiet["doc_key"] == "a.md"]
    assert (sk.chi_tiet["so_trung_do_llm"], sk.chi_tiet["so_gop_do_bi_danh"]) == (1, 1)
    assert "so_trung_trong_chunk" not in sk.chi_tiet


# --- Lớp 3: HTTP -------------------------------------------------------------------


def _kho_gia() -> KhoGia:
    return KhoGia(
        {
            TEN_GO["ts01"]: _dong("ts01"),
            TEN_GO["dev01"]: _dong("dev01", role="devops", demo=True, admin=True),
        }
    )


def _client(monkeypatch, audit, engine, *, che_do_do: str | None = None, kho=None):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    if che_do_do is None:
        monkeypatch.delenv(BIEN_CHE_DO_DO, raising=False)
    else:
        monkeypatch.setenv(BIEN_CHE_DO_DO, che_do_do)
    kho = _kho_gia() if kho is None else kho

    async def _mo_kho():
        return kho

    async def _mo_audit():
        return audit

    async def _mo_engine(_audit):
        return engine

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    return TestClient(api_main.app)


def _dang_nhap(client, tai_khoan: str, mat_khau: str = MAT_KHAU):
    return client.post("/auth/login", json={"tai_khoan": tai_khoan, "mat_khau": mat_khau})


def _hoi(client, tai_khoan: str):
    kq = _dang_nhap(client, TEN_GO[tai_khoan])
    assert kq.status_code == 200, kq.text
    return client.post("/hoi-dap", json={"cau_hoi": CAU_HOI}, headers={"Authorization": "Bearer " + kq.json()["token"]})


def _su_kien(audit, event):
    return [sk for sk in audit.su_kien if sk.event == event]


def test_khoi_dong_ghi_mot_hang_startup_mutation_truoc_engine(monkeypatch):
    """Hàng "Khởi động": một `startup` mutation, `space="*"`, ba khóa, và đứng trước mọi hàng khác."""
    audit = AuditGia()
    engine = EngineGia()
    with _client(monkeypatch, audit, engine, che_do_do="1") as client:
        assert client.get("/health").status_code == 200
        kho = client.app.state.kho_chinh_sach
        assert client.app.state.che_do_do is True
    assert [sk.event for sk in audit.su_kien] == [EVENT_STARTUP]
    sk = audit.su_kien[0]
    assert (sk.tier, sk.space) == (TIER_MUTATION, SPACE_TIEN_TRINH)
    assert dict(sk.chi_tiet) == {
        CT_POLICY_ID: kho.ma,
        CT_POLICY_VERSION: kho.hien_tai().policy_version,
        CT_CHE_DO_DO: True,
    }
    assert sk.policy_version == kho.hien_tai().policy_version


def test_co_vang_la_tat_va_ghi_vao_startup(monkeypatch):
    audit = AuditGia()
    with _client(monkeypatch, audit, EngineGia()) as client:
        assert client.app.state.che_do_do is False
    assert audit.su_kien[0].chi_tiet[CT_CHE_DO_DO] is False


def test_startup_ghi_hong_thi_tien_trinh_khong_len_va_dong_nguoc(monkeypatch):
    """Tầng mutation: audit hỏng lúc khởi động là lifespan dội lỗi; audit và bảng users đều đóng."""
    audit = AuditGia()
    audit.no = RuntimeError("audit_log chết")
    engine = EngineGia()
    kho = _kho_gia()
    with pytest.raises(RuntimeError, match="audit_log chết"):
        with _client(monkeypatch, audit, engine, kho=kho):
            pass
    assert audit.da_dong and kho.da_dong
    assert not engine.da_dong, "engine chưa được dựng thì không có gì để đóng: startup ghi trước khi mở engine"


def test_co_sai_gia_tri_chet_o_lifespan_truoc_moi_ket_noi(monkeypatch):
    """Hàng "Cờ sai giá trị": chết ở giây đầu, trước khi mở bảng `users`."""
    da_mo: list[str] = []

    async def _mo_kho():
        da_mo.append("kho")
        return _kho_gia()

    audit = AuditGia()
    with pytest.raises(CheDoDoKhongHopLe):
        with _client(monkeypatch, audit, EngineGia(), che_do_do="yes"):
            pass
    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    with pytest.raises(CheDoDoKhongHopLe):
        with TestClient(api_main.app):
            pass
    assert da_mo == [] and audit.su_kien == []


def test_dang_nhap_dung_va_ba_nhanh_sai_deu_ghi_auth_login(monkeypatch):
    """Hàng "Đăng nhập đúng / sai": bốn hàng `auth_login` observation, thân response không đổi."""
    audit = AuditGia()
    with _client(monkeypatch, audit, EngineGia()) as client:
        audit.su_kien.clear()
        dung = _dang_nhap(client, TEN_GO["ts01"])
        sai_mk = _dang_nhap(client, TEN_GO["ts01"], "sai")
        la = _dang_nhap(client, "khong-co-ai")
        hong = client.post("/auth/login", content=b"{", headers={"content-type": "application/json"})
    assert dung.status_code == 200
    for kq in (sai_mk, la, hong):
        assert kq.status_code == 401 and kq.json()["error"]["code"] == MA_DANG_NHAP_SAI
    assert sai_mk.content == la.content == hong.content
    hang = _su_kien(audit, EVENT_AUTH_LOGIN)
    assert [sk.event for sk in audit.su_kien] == [EVENT_AUTH_LOGIN] * 4
    assert [(sk.act, sk.chi_tiet[CT_KET_QUA]) for sk in hang] == [
        (TEN_GO["ts01"], KET_QUA_THANH_CONG),
        (TEN_GO["ts01"], KET_QUA_THAT_BAI),
        ("khong-co-ai", KET_QUA_THAT_BAI),
        (None, KET_QUA_THAT_BAI),
    ]
    for sk in hang:
        assert (sk.tier, sk.space, sk.role) == (TIER_OBSERVATION, SPACE_TIEN_TRINH, None)
        assert set(sk.chi_tiet) == {CT_KET_QUA}, "không trường nào nói vì sao sai"


def test_audit_hong_thi_dang_nhap_van_chay_va_than_khong_doi(monkeypatch, caplog):
    audit = AuditGia()
    with _client(monkeypatch, audit, EngineGia()) as client:
        khoe_dung = _dang_nhap(client, TEN_GO["ts01"])
        khoe_sai = _dang_nhap(client, TEN_GO["ts01"], "sai").content
        audit.no = RuntimeError("postgres chết")
        with caplog.at_level("WARNING"):
            hong_dung = _dang_nhap(client, TEN_GO["ts01"])
            hong_sai = _dang_nhap(client, TEN_GO["ts01"], "sai").content
    assert khoe_dung.status_code == hong_dung.status_code == 200
    assert khoe_sai == hong_sai
    assert any("audit observation auth_login" in r.getMessage() for r in caplog.records), caplog.text


def test_tu_choi_co_tat_la_observation_va_audit_hong_van_200(monkeypatch, caplog):
    """Hàng "Từ chối, cờ tắt": như 3.5, `refusal` observation, audit hỏng là WARNING + 200."""
    audit = AuditGia()
    engine = EngineGia(ly_do=LY_DO_CO_NO_ANSWER)
    with _client(monkeypatch, audit, engine, che_do_do="0") as client:
        khoe = _hoi(client, "ts01")
        (sk,) = _su_kien(audit, EVENT_REFUSAL)
        audit.no = RuntimeError("postgres chết")
        with caplog.at_level("WARNING"):
            hong = _hoi(client, "ts01")
    assert sk.tier == TIER_OBSERVATION and sk.chi_tiet[CT_LY_DO] == LY_DO_CO_NO_ANSWER
    assert khoe.status_code == hong.status_code == 200 and khoe.content == hong.content
    assert any("audit observation refusal" in r.getMessage() for r in caplog.records), caplog.text


def test_tu_choi_co_bat_la_mutation_than_giong_co_tat_va_audit_hong_la_500(monkeypatch):
    """AC-1 và hàng "Từ chối, cờ bật": `refusal` mutation; thân 200 byte-identical với cờ tắt; hỏng là 500."""
    engine = EngineGia(ly_do=LY_DO_NGU_CANH_RONG)
    audit_tat = AuditGia()
    with _client(monkeypatch, audit_tat, engine, che_do_do="0") as client:
        than_tat = _hoi(client, "ts01").content
    audit_bat = AuditGia()
    with _client(monkeypatch, audit_bat, engine, che_do_do="1") as client:
        kq = _hoi(client, "ts01")
        assert kq.status_code == 200 and kq.content == than_tat
        (sk,) = _su_kien(audit_bat, EVENT_REFUSAL)
        assert sk.tier == TIER_MUTATION and sk.chi_tiet[CT_LY_DO] == LY_DO_NGU_CANH_RONG
        assert _su_kien(audit_tat, EVENT_REFUSAL)[0].tier == TIER_OBSERVATION
        audit_bat.no = RuntimeError("postgres chết")
        hong = _hoi(client, "ts01")
    assert hong.status_code == 500, hong.text
    assert tuple(hong.json()) == ("error",)
    assert hong.json()["error"]["code"] == MA_AUDIT_GHI_HONG == "AUDIT_GHI_HONG"
    assert "refused" not in hong.text and "postgres" not in hong.text


def test_co_bat_refusal_hong_thi_khong_hang_query(monkeypatch):
    """Thứ tự ghi: `refusal` trước `query`, nên một lượt 500 vì audit không để lại hàng thời gian (NFR-08)."""
    audit = AuditGia()
    engine = EngineGia(ly_do=LY_DO_NGU_CANH_RONG)
    with _client(monkeypatch, audit, engine, che_do_do="1") as client:
        audit.no = RuntimeError("postgres chết")
        kq = _hoi(client, "ts01")
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_AUDIT_GHI_HONG
    assert _su_kien(audit, EVENT_QUERY) == [] and _su_kien(audit, EVENT_REFUSAL) == []


def test_co_bat_port_treo_qua_tran_la_500_audit_ghi_hong(monkeypatch):
    """Trần chờ của mutation ở `api/`: port treo lâu hơn `THOI_HAN_BIEN_DOI` cũng là 500, không treo request."""
    from api import hoi_dap as mod

    class AuditTreo(AuditGia):
        async def ghi(self, su_kien):
            if su_kien.event == EVENT_REFUSAL:
                await asyncio.sleep(5)
            self.su_kien.append(su_kien)

    monkeypatch.setattr(mod, "THOI_HAN_BIEN_DOI", 0.05)
    audit = AuditTreo()
    with _client(monkeypatch, audit, EngineGia(ly_do=LY_DO_CO_NO_ANSWER), che_do_do="1") as client:
        kq = _hoi(client, "ts01")
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_AUDIT_GHI_HONG
    assert _su_kien(audit, EVENT_QUERY) == []


def test_luot_tra_loi_khong_bi_co_bat_anh_huong_khi_audit_hong(monkeypatch, caplog):
    """Cờ bật chỉ đổi tầng của `refusal`: `query` vẫn observation, câu trả lời vẫn về."""
    audit = AuditGia()
    engine = EngineGia()
    with _client(monkeypatch, audit, engine, che_do_do="1") as client:
        audit.no = RuntimeError("postgres chết")
        with caplog.at_level("WARNING"):
            kq = _hoi(client, "dev01")
    assert kq.status_code == 200 and kq.json()["answer"] == engine.tra_loi


def test_query_va_refusal_cung_request_id_khong_vao_response(monkeypatch):
    audit = AuditGia()
    with _client(monkeypatch, audit, EngineGia(ly_do=LY_DO_CO_NO_ANSWER)) as client:
        kq = _hoi(client, "ts01")
    (q,) = _su_kien(audit, EVENT_QUERY)
    (r,) = _su_kien(audit, EVENT_REFUSAL)
    rid = q.chi_tiet[CT_REQUEST_ID]
    assert isinstance(rid, str) and len(rid) == 32 and r.chi_tiet[CT_REQUEST_ID] == rid
    assert set(q.chi_tiet) == {CT_MILI_GIAY, CT_REQUEST_ID} and set(r.chi_tiet) == {CT_LY_DO, CT_REQUEST_ID}
    assert rid not in kq.text and CT_REQUEST_ID not in kq.text
    assert CT_BI_LOAI not in kq.text and "che_do_do" not in kq.text


def test_hai_luot_hai_request_id_khac_nhau(monkeypatch):
    audit = AuditGia()
    with _client(monkeypatch, audit, EngineGia()) as client:
        _hoi(client, "ts01")
        _hoi(client, "ts01")
    ids = [sk.chi_tiet[CT_REQUEST_ID] for sk in _su_kien(audit, EVENT_QUERY)]
    assert len(ids) == 2 and ids[0] != ids[1]


def test_lech_quyen_hai_tang_ghi_permission_mismatch_khong_query_khong_refusal(monkeypatch):
    """Hàng "Lệch quyền hai tầng": 500 như 3.4 cộng một hàng observation mang id thiếu."""
    audit = AuditGia()
    engine = EngineGia(loi=TrichDanNgoaiQuyen("ngữ cảnh mang 2 id lạ", ids=("he-x", "he-y")))
    with _client(monkeypatch, audit, engine) as client:
        kq = _hoi(client, "dev01")
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_TRICH_DAN_NGOAI_QUYEN
    assert "he-x" not in kq.text
    assert [sk.event for sk in audit.su_kien if sk.event != EVENT_STARTUP and sk.event != EVENT_AUTH_LOGIN] == [
        EVENT_PERMISSION_MISMATCH
    ]
    (sk,) = _su_kien(audit, EVENT_PERMISSION_MISMATCH)
    assert sk.tier == TIER_OBSERVATION and sk.hyperedge_ids == ("he-x", "he-y")
    assert (sk.act, sk.role) == ("dev01", "devops")
    assert set(sk.chi_tiet) == {CT_MA, CT_REQUEST_ID} and sk.chi_tiet[CT_MA] == "TRICH_DAN_NGOAI_QUYEN"


def test_lech_quyen_audit_hong_van_500_dung_ma(monkeypatch, caplog):
    audit = AuditGia()
    engine = EngineGia(loi=TrichDanNgoaiQuyen("lạ", ids=("he-x",)))
    with _client(monkeypatch, audit, engine) as client:
        audit.no = RuntimeError("postgres chết")
        with caplog.at_level("WARNING"):
            kq = _hoi(client, "dev01")
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_TRICH_DAN_NGOAI_QUYEN
    assert any("audit observation permission_mismatch" in r.getMessage() for r in caplog.records)


def test_khong_co_endpoint_bat_tat_co_che_do_do():
    """Cờ là biến môi trường của tiến trình (AD-6, AD-7): không tuyến nào đổi được nó."""
    duong = {getattr(r, "path", "") for r in api_main.app.routes}
    assert not any("che-do-do" in d or "che_do_do" in d for d in duong), duong


# --- Tài liệu và cấu hình -----------------------------------------------------------------


def test_adr_017_ghi_ba_quyet_dinh_cua_story():
    assert ADR_017.exists(), ADR_017
    van_ban = ADR_017.read_text(encoding="utf-8")
    for cum in ("HYPER_RAG_CHE_DO_DO", "post-filter", "tu_khoa_rong", "AUDIT_GHI_HONG", "L1", "L0", "endpoint"):
        assert cum in van_ban, f"ADR-017 thiếu {cum!r}"
