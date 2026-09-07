"""`AuditPostgres` trên Postgres thật của compose (marker `postgres`, story 2.2).

Test cần container mang marker `postgres` từng cái; phần đọc môi trường không
cần container nên chạy ở `uv run pytest` mặc định. Chạy phần container trên máy
chủ::

    POSTGRES_REQUIRED=1 POSTGRES_HOST=<ip-container> POSTGRES_USER=hyperrag \\
    POSTGRES_DB=hyperrag POSTGRES_PASSWORD=... uv run pytest -m postgres

Mỗi test dùng một `space` mang prefix phiên; `kho_audit` dọn hàng của các
space đó trước và sau, bằng connection của pool trực tiếp - lớp sản phẩm không
có đường xóa (audit là sổ chỉ ghi thêm). Mở pool, ghi, đọc và dọn trong
**một** `asyncio.run`: pool asyncpg gắn với event loop mở nó.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import pytest

from adapters.llm_wrapper import (
    CT_CHI_PHI_USD,
    CT_MODEL,
    CT_TOKEN_RA,
    CT_TOKEN_VAO,
    bo_embedding,
    bo_llm,
)
from api.audit_postgres import (
    AuditPostgres,
    PostgresConfigMissing,
    cau_hinh_postgres_tu_moi_truong,
)
from core.audit import (
    EVENT_EMBEDDING_COST,
    EVENT_LLM_COST,
    TIER_OBSERVATION,
    SuKienAudit,
    thoi_diem_utc,
)
from core.permission import use_context
from tests.gia_lap_llm import (
    MODEL_EMBEDDING_GIA,
    MODEL_LLM_GIA,
    EmbeddingGia,
    NhaCungCapGia,
    danh_muc_gia,
)
from tests.ngu_canh import vai

DU = {"POSTGRES_HOST": "pg", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_DB": "d"}


def test_cau_hinh_postgres_tu_moi_truong_luat_bien_rong():
    """Không cần container: chỉ là phép đọc môi trường."""
    cau_hinh = cau_hinh_postgres_tu_moi_truong({**DU, "POSTGRES_HOST": " pg ", "POSTGRES_PORT": ""})
    assert cau_hinh == {"host": "pg", "user": "u", "password": "p", "database": "d", "port": 5432}
    assert cau_hinh_postgres_tu_moi_truong({**DU, "POSTGRES_PORT": "5433"})["port"] == 5433
    with pytest.raises(PostgresConfigMissing) as loi:
        cau_hinh_postgres_tu_moi_truong({"POSTGRES_HOST": "pg"})
    assert loi.value.code == "POSTGRES_CONFIG_MISSING"
    assert "POSTGRES_PASSWORD" in str(loi.value)


@pytest.mark.parametrize("cong", ["abc", "0", "65536", "-1", "54.32", "5432x"])
def test_cong_postgres_hong_la_loi_co_ma(cong):
    with pytest.raises(PostgresConfigMissing) as loi:
        cau_hinh_postgres_tu_moi_truong({**DU, "POSTGRES_PORT": cong})
    assert loi.value.code == "POSTGRES_CONFIG_MISSING"
    assert "POSTGRES_PORT" in str(loi.value)


def test_tong_chi_phi_tu_choi_moc_khong_utc():
    """`tu` đi qua cùng luật thời điểm với sự kiện, trước khi chạm SQL."""

    async def chay():
        audit = AuditPostgres(pool=None)
        with pytest.raises(ValueError):
            await audit.tong_chi_phi("synth", tu="2026-09-02T10:00:00")
        with pytest.raises(ValueError):
            await audit.tong_chi_phi("synth", tu="2026-09-02T10:00:00+07:00")
        with pytest.raises(TypeError):
            await audit.tong_chi_phi("synth", tu=123)  # type: ignore[arg-type]
        # `den` (story 2.3, patch 25) đi qua cùng luật.
        with pytest.raises(ValueError):
            await audit.tong_chi_phi("synth", den="2026-09-02T10:00:00+07:00")

    asyncio.run(chay())


# --- Phần cần container ------------------------------------------------------


@pytest.fixture()
def cau_hinh_pg():
    try:
        return cau_hinh_postgres_tu_moi_truong()
    except PostgresConfigMissing as loi:
        if os.environ.get("POSTGRES_REQUIRED"):
            pytest.fail(f"POSTGRES_REQUIRED được đặt nhưng {loi}")
        pytest.skip(f"{loi}: bỏ qua test cần container")


@asynccontextmanager
async def kho_audit(cau_hinh, *spaces: str):
    """Pool đã mở và bảng đã dựng; dọn các space test trước và sau, bằng pool trực tiếp."""
    audit = await AuditPostgres.mo(cau_hinh)
    try:
        await audit.khoi_tao()
        await _don(audit, spaces)
        yield audit
        await _don(audit, spaces)
    finally:
        await audit.dong()


async def _don(audit: AuditPostgres, spaces) -> None:
    async with audit._pool.acquire() as conn:
        for space in spaces:
            await conn.execute("DELETE FROM audit_log WHERE space = $1", space)


def _su_kien(space: str, event: str, token_vao: int, token_ra: int, usd: float) -> SuKienAudit:
    return SuKienAudit(
        tier=TIER_OBSERVATION,
        event=event,
        space=space,
        policy_version="v-test",
        thoi_diem=thoi_diem_utc(),
        act="dev01",
        role="devops",
        hyperedge_ids=("HE-01",),
        chi_tiet={
            CT_MODEL: "m",
            "nha_cung_cap": "gia",
            CT_TOKEN_VAO: token_vao,
            CT_TOKEN_RA: token_ra,
            CT_CHI_PHI_USD: usd,
            "ghi_chu": "tiếng Việt có dấu",
        },
    )


@pytest.mark.postgres
def test_ghi_roi_doc_mot_hang_dung_kieu_cot(cau_hinh_pg, khong_gian):
    async def chay():
        async with kho_audit(cau_hinh_pg, khong_gian) as audit:
            sk = _su_kien(khong_gian, EVENT_LLM_COST, 12, 34, 0.00008)
            await audit.ghi(sk)
            async with audit._pool.acquire() as conn:
                hang = await conn.fetchrow(
                    "SELECT thoi_diem, tier, event, act, role, space, policy_version,"
                    " hyperedge_ids, chi_tiet, pg_typeof(chi_tiet)::text AS kieu_ct,"
                    " pg_typeof(thoi_diem)::text AS kieu_td"
                    " FROM audit_log WHERE space = $1",
                    khong_gian,
                )
                so_hang = await conn.fetchval(
                    "SELECT count(*) FROM audit_log WHERE space = $1", khong_gian
                )
            tong = await audit.tong_chi_phi(khong_gian)
            return sk, dict(hang), so_hang, tong

    sk, hang, so_hang, tong = asyncio.run(chay())
    assert so_hang == 1
    assert hang["kieu_ct"] == "jsonb"
    assert hang["kieu_td"] == "timestamp with time zone"
    assert hang["tier"] == TIER_OBSERVATION and hang["event"] == EVENT_LLM_COST
    assert hang["act"] == "dev01" and hang["role"] == "devops"
    assert hang["space"] == khong_gian and hang["policy_version"] == "v-test"
    assert hang["hyperedge_ids"] == ["HE-01"]
    assert hang["thoi_diem"].isoformat() == sk.thoi_diem
    ct = json.loads(hang["chi_tiet"])
    assert ct[CT_TOKEN_VAO] == 12 and ct[CT_TOKEN_RA] == 34
    assert ct["ghi_chu"] == "tiếng Việt có dấu"
    assert tong.so_lan == 1 and tong.token_vao == 12 and tong.token_ra == 34
    assert tong.chi_phi_usd == pytest.approx(0.00008)


@pytest.mark.postgres
def test_khoi_tao_hai_lan_khong_loi_bang_giu_nguyen(cau_hinh_pg, khong_gian):
    async def chay():
        async with kho_audit(cau_hinh_pg, khong_gian) as audit:
            await audit.ghi(_su_kien(khong_gian, EVENT_LLM_COST, 1, 1, 0.0))
            await audit.khoi_tao()
            await audit.khoi_tao()
            return (await audit.tong_chi_phi(khong_gian)).so_lan

    assert asyncio.run(chay()) == 1


@pytest.mark.postgres
def test_tong_chi_phi_cong_dung_theo_space_model_va_moc_thoi_gian(cau_hinh_pg, khong_gian):
    khac = f"{khong_gian}_khac"

    async def chay():
        async with kho_audit(cau_hinh_pg, khong_gian, khac) as audit:
            await audit.ghi(_su_kien(khong_gian, EVENT_LLM_COST, 10, 20, 0.001))
            moc = thoi_diem_utc()
            await audit.ghi(_su_kien(khong_gian, EVENT_LLM_COST, 5, 5, 0.0005))
            await audit.ghi(_su_kien(khong_gian, EVENT_EMBEDDING_COST, 7, 0, 0.0001))
            await audit.ghi(_su_kien(khac, EVENT_LLM_COST, 999, 999, 9.0))
            return await audit.tong_chi_phi(khong_gian), await audit.tong_chi_phi(khong_gian, tu=moc)

    tat_ca, tu_moc = asyncio.run(chay())
    assert (tat_ca.so_lan, tat_ca.token_vao, tat_ca.token_ra) == (3, 22, 25)
    assert tat_ca.chi_phi_usd == pytest.approx(0.0016)
    assert len(tat_ca.theo_model) == 1 and tat_ca.theo_model[0].model == "m"
    assert (tu_moc.so_lan, tu_moc.token_vao, tu_moc.token_ra) == (2, 12, 5)


@pytest.mark.postgres
def test_wrapper_ghi_qua_postgres_that(cau_hinh_pg, khong_gian, policy):
    """Đường thật từ wrapper tới bảng: một lời gọi LLM và một lượt embed."""

    async def chay():
        async with kho_audit(cau_hinh_pg, khong_gian) as audit:
            dm = danh_muc_gia()
            llm = bo_llm(nha_cung_cap=NhaCungCapGia(), model=MODEL_LLM_GIA, audit=audit, danh_muc=dm)
            emb = bo_embedding(
                nha_cung_cap=EmbeddingGia(token_vao=3), model=MODEL_EMBEDDING_GIA, audit=audit, danh_muc=dm
            )
            with use_context(vai(policy, "devops", khong_gian)):
                await llm("hỏi")
                await emb(["x"])
            return await audit.tong_chi_phi(khong_gian)

    tong = asyncio.run(chay())
    assert tong.so_lan == 2
    assert tong.token_vao == 12 + 3 and tong.token_ra == 34
    assert {d.model for d in tong.theo_model} == {MODEL_LLM_GIA, MODEL_EMBEDDING_GIA}
    assert tong.chi_phi_usd == pytest.approx((12 * 1.0 + 34 * 2.0 + 3 * 0.5) / 1e6)


@pytest.mark.postgres
def test_tong_chi_phi_theo_doan_tu_den_cung_cua_so_o_dong_model(cau_hinh_pg, khong_gian):
    """`[tu, den)`: cả dòng tổng lẫn dòng theo model đều chỉ đếm sự kiện trong đoạn.

    Patch 25 vòng review 2.3: bảng từng tài liệu của `api/do_chi_phi.py` từng
    in dòng theo model bằng tổng từ mốc đầu tới hết lịch sử vì phép trừ chỉ
    làm ở cấp tổng. Nay mốc kết thúc vào SQL nên hai dòng không lệch nhau.
    """

    async def chay():
        async with kho_audit(cau_hinh_pg, khong_gian) as audit:
            await audit.ghi(_su_kien(khong_gian, EVENT_LLM_COST, 10, 20, 0.001))
            moc = thoi_diem_utc()
            await audit.ghi(_su_kien(khong_gian, EVENT_LLM_COST, 5, 5, 0.0005))
            moc_ket = thoi_diem_utc()
            await audit.ghi(_su_kien(khong_gian, EVENT_LLM_COST, 100, 100, 0.01))
            return (
                await audit.tong_chi_phi(khong_gian, tu=moc, den=moc_ket),
                await audit.tong_chi_phi(khong_gian, den=moc),
            )

    doan, truoc_moc = asyncio.run(chay())
    assert (doan.so_lan, doan.token_vao, doan.token_ra) == (1, 5, 5)
    assert len(doan.theo_model) == 1
    assert (doan.theo_model[0].so_lan, doan.theo_model[0].token_vao) == (1, 5), "dòng theo model cùng cửa sổ với dòng tổng"
    assert (truoc_moc.so_lan, truoc_moc.token_vao) == (1, 10)


# --- Story 3.6: năm sự kiện mới qua INSERT thật và hai cửa đọc ------------------


def _hang_3_6(space: str, event: str, tier: str, chi_tiet: dict, *, act=None, role=None, policy_version="v-3-6", hyperedge_ids=()):
    return SuKienAudit(
        tier=tier,
        event=event,
        space=space,
        policy_version=policy_version,
        thoi_diem=thoi_diem_utc(),
        act=act,
        role=role,
        hyperedge_ids=tuple(hyperedge_ids),
        chi_tiet=chi_tiet,
    )


@pytest.mark.postgres
def test_dem_su_kien_hai_cot_tu_choi_va_so_khong_dong_bo(cau_hinh_pg, khong_gian):
    """Hàng "Đếm hai cột": ba lý do tách nhau, `tu_khoa_rong` là hàng riêng, `so_khong_dong_bo` đếm hàng observation."""
    from adapters.tra_loi import LY_DO_CO_NO_ANSWER, LY_DO_NGU_CANH_RONG, LY_DO_TU_KHOA_RONG
    from api.hoi_dap import CT_LY_DO
    from core.audit import CT_REQUEST_ID, EVENT_REFUSAL, TIER_MUTATION

    async def chay():
        async with kho_audit(cau_hinh_pg, khong_gian) as audit:
            for ly_do, tier in (
                (LY_DO_NGU_CANH_RONG, TIER_MUTATION),
                (LY_DO_NGU_CANH_RONG, TIER_MUTATION),
                (LY_DO_CO_NO_ANSWER, TIER_MUTATION),
                (LY_DO_TU_KHOA_RONG, TIER_MUTATION),
                (LY_DO_CO_NO_ANSWER, TIER_OBSERVATION),
            ):
                await audit.ghi(
                    _hang_3_6(khong_gian, EVENT_REFUSAL, tier, {CT_LY_DO: ly_do, CT_REQUEST_ID: "r-1"}, act="ts01", role="tech_support")
                )
            moc = thoi_diem_utc()
            await audit.ghi(_hang_3_6(khong_gian, EVENT_REFUSAL, TIER_OBSERVATION, {CT_LY_DO: LY_DO_NGU_CANH_RONG}))
            return (
                await audit.dem_su_kien(EVENT_REFUSAL, space=khong_gian, theo=CT_LY_DO, den=moc),
                await audit.dem_su_kien(EVENT_REFUSAL, space=khong_gian),
                await audit.dem_su_kien(EVENT_REFUSAL, space=f"{khong_gian}_khac", theo=CT_LY_DO),
            )

    theo_ly_do, gop, rong = asyncio.run(chay())
    assert theo_ly_do.so_theo == {LY_DO_NGU_CANH_RONG: 2, LY_DO_CO_NO_ANSWER: 2, LY_DO_TU_KHOA_RONG: 1}
    assert (theo_ly_do.tong, theo_ly_do.so_khong_dong_bo) == (5, 1)
    assert gop.so_theo == {} and (gop.tong, gop.so_khong_dong_bo) == (6, 2)
    assert rong.so_theo == {} and (rong.tong, rong.so_khong_dong_bo) == (0, 0)


@pytest.mark.postgres
def test_nam_su_kien_moi_qua_postgres_that_va_su_kien_tien_trinh(cau_hinh_pg, khong_gian):
    """`policy_swap` qua `KhoChinhSach.hoan` thật, `startup`, `auth_login`, `filter`, `refusal` mutation: INSERT rồi đọc lại.

    CI chạy trên **cùng** Postgres `hyperrag` với tiến trình thật, nên mọi hàng
    `space="*"` của test mang một dấu phiên duy nhất (`act` cho `hoan` và
    `auth_login`, `policy_version` cho `startup`), dọn và lọc assert theo dấu đó
    - không đụng hàng `startup`/`policy_swap`/`auth_login` thật của máy chủ, và
    hàng thật chen vào cửa sổ không làm ca thứ tự đỏ. `su_kien_tien_trinh` trả
    đúng ba hàng của phiên theo thứ tự thời gian; `tong_chi_phi(space)` và
    `dem_su_kien(space)` không bao giờ thấy chúng.
    """
    import uuid

    from adapters.kv import CT_BI_LOAI, CT_NAMESPACE
    from api.che_do_do import CT_CHE_DO_DO, CT_POLICY_ID, CT_POLICY_VERSION
    from api.chinh_sach import ID_MAC_DINH, KhoChinhSach
    from api.hoi_dap import CT_LY_DO
    from api.xac_thuc import CT_KET_QUA, KET_QUA_THAT_BAI, su_kien_dang_nhap
    from core.audit import (
        CT_REQUEST_ID,
        EVENT_AUTH_LOGIN,
        EVENT_FILTER,
        EVENT_POLICY_SWAP,
        EVENT_REFUSAL,
        EVENT_STARTUP,
        SPACE_TIEN_TRINH,
        TIER_MUTATION,
    )

    dau = f"pytest-{uuid.uuid4().hex}"
    kho = KhoChinhSach.nap(ID_MAC_DINH)

    async def don(audit):
        async with audit._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM audit_log WHERE space = $1 AND (act = $2 OR policy_version = $2)",
                SPACE_TIEN_TRINH, dau,
            )

    async def chay():
        async with kho_audit(cau_hinh_pg, khong_gian) as audit:
            await don(audit)
            try:
                tu = thoi_diem_utc()
                startup = SuKienAudit(
                    tier=TIER_MUTATION, event=EVENT_STARTUP, space=SPACE_TIEN_TRINH, policy_version=dau,
                    thoi_diem=thoi_diem_utc(),
                    chi_tiet={CT_POLICY_ID: ID_MAC_DINH, CT_POLICY_VERSION: dau, CT_CHE_DO_DO: True},
                )
                await audit.ghi(startup)
                _, moi = await kho.hoan("nhi-phan", audit=audit, act=dau, role="devops", che_do_do=True)
                await audit.ghi(su_kien_dang_nhap(dau, False, "v-3-6"))
                await audit.ghi(
                    _hang_3_6(
                        khong_gian, EVENT_FILTER, TIER_OBSERVATION,
                        {CT_NAMESPACE: "text_chunks", CT_BI_LOAI: {"L1": 1, "L0": 2}, CT_REQUEST_ID: "r-1"},
                        act="ts01", role="tech_support",
                    )
                )
                await audit.ghi(_hang_3_6(khong_gian, EVENT_REFUSAL, TIER_MUTATION, {CT_LY_DO: "ngu_canh_rong", CT_REQUEST_ID: "r-1"}))
                den = thoi_diem_utc()
                tien_trinh = await audit.su_kien_tien_trinh(tu=tu, den=den)
                async with audit._pool.acquire() as conn:
                    hang_loc = await conn.fetchrow(
                        "SELECT chi_tiet FROM audit_log WHERE space = $1 AND event = $2", khong_gian, EVENT_FILTER
                    )
                return (
                    moi.policy_version,
                    tien_trinh,
                    await audit.tong_chi_phi(khong_gian),
                    await audit.dem_su_kien(EVENT_REFUSAL, space=khong_gian),
                    hang_loc["chi_tiet"],
                )
            finally:
                await don(audit)

    pv_moi, tien_trinh, tong, dem, chi_tiet_loc = asyncio.run(chay())
    cua_phien = [sk for sk in tien_trinh if dau in (sk.act, sk.policy_version)]
    assert [sk.event for sk in cua_phien] == [EVENT_STARTUP, EVENT_POLICY_SWAP, EVENT_AUTH_LOGIN]
    assert all(sk.space == SPACE_TIEN_TRINH for sk in cua_phien)
    st, swap, login = cua_phien
    assert st.tier == TIER_MUTATION and dict(st.chi_tiet) == {CT_POLICY_ID: ID_MAC_DINH, CT_POLICY_VERSION: dau, CT_CHE_DO_DO: True}
    assert swap.tier == TIER_MUTATION and swap.chi_tiet["policy_id_moi"] == "nhi-phan"
    assert swap.chi_tiet["policy_version_moi"] == pv_moi and (swap.act, swap.role) == (dau, "devops")
    assert login.act == dau[:64] and dict(login.chi_tiet) == {CT_KET_QUA: KET_QUA_THAT_BAI}
    assert tong.so_lan == 0, "hàng tiến trình không vào tổng theo space"
    assert (dem.tong, dem.so_khong_dong_bo, dem.so_theo) == (1, 0, {})
    assert json.loads(chi_tiet_loc) == {CT_NAMESPACE: "text_chunks", CT_BI_LOAI: {"L0": 2, "L1": 1}, CT_REQUEST_ID: "r-1"}
