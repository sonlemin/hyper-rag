"""`KhoBreakGlass` trên Postgres thật của compose (marker `postgres`, story 5.1).

Ba thứ mà bản giả chỉ mô phỏng được, ở đây chấm trên kho thật: DDL của hai bảng
(`api/sql/breakglass.sql`, chạy sau `users.sql` vì khóa ngoại), index duy nhất
một phần bắt ca race (INSERT thẳng hàng thứ hai, không qua phép kiểm trước),
và hủy có điều kiện (`UPDATE ... WHERE trang_thai = 'cho_duyet'`). Cộng bất
biến audit-trong-transaction: `ghi_audit` hỏng thì không hàng nào ở bảng.

Chạy trên máy chủ::

    POSTGRES_REQUIRED=1 POSTGRES_HOST=<ip-container> POSTGRES_USER=hyperrag \\
    POSTGRES_DB=hyperrag POSTGRES_PASSWORD=... uv run pytest -m postgres

Mỗi test dùng tài khoản mang prefix phiên, chèn thẳng vào `users` rồi dọn cả
ba bảng theo tài khoản đó trước và sau, bằng pool trực tiếp. Mở pool, ghi, đọc
và dọn trong **một** `asyncio.run`: pool asyncpg gắn với event loop mở nó.
"""

import asyncio
import os
from contextlib import asynccontextmanager

import asyncpg
import pytest

from api.audit_postgres import PostgresConfigMissing, cau_hinh_postgres_tu_moi_truong
from api import break_glass as bg
from api.break_glass import (
    MA_GRANT_CON_HAN,
    MA_YEU_CAU_DANG_CHO,
    MA_YEU_CAU_KHONG_CO,
    MA_YEU_CAU_KHONG_CON_CHO,
    KhoBreakGlass,
    YeuCauBreakGlass,
    ma_yeu_cau,
)
from api.hoi_dap import LoiHoiDap
from api.tai_khoan import KhoTaiKhoan
from core.audit import thoi_diem_utc
from core.break_glass import K_MAC_DINH, THOI_HAN_PHUT, TRANG_THAI_CHO_DUYET, TRANG_THAI_DA_HUY
from tests.ho_tro_break_glass import chen_grant

pytestmark = pytest.mark.postgres


@pytest.fixture()
def cau_hinh_pg():
    """Cùng cửa bỏ qua/thất bại với `tests/test_audit_postgres.py`."""
    try:
        return cau_hinh_postgres_tu_moi_truong()
    except PostgresConfigMissing as loi:
        if os.environ.get("POSTGRES_REQUIRED"):
            pytest.fail(f"POSTGRES_REQUIRED được đặt nhưng {loi}")
        pytest.skip(f"{loi}: bỏ qua test cần container")


@asynccontextmanager
async def kho_bg(cau_hinh, *tai_khoan: str):
    """Pool đã mở, DDL `users` rồi `breakglass` đã chạy, tài khoản test đã chèn; dọn hai đầu."""
    users = await KhoTaiKhoan.mo(cau_hinh)
    try:
        await users.khoi_tao()
    finally:
        await users.dong()
    kho = await KhoBreakGlass.mo(cau_hinh)
    try:
        await kho.khoi_tao()
        await _don(kho, tai_khoan)
        async with kho._pool.acquire() as conn:
            for tk in tai_khoan:
                await conn.execute(
                    "INSERT INTO users (account, mat_khau_hash, role, group_name, khong_gian)"
                    " VALUES ($1, 'x', 'tech_support', 'Tech Support', 'synth')"
                    " ON CONFLICT (account) DO NOTHING",
                    tk,
                )
        yield kho
        await _don(kho, tai_khoan)
    finally:
        await kho.dong()


async def _don(kho: KhoBreakGlass, tai_khoan) -> None:
    async with kho._pool.acquire() as conn:
        for tk in tai_khoan:
            await conn.execute("DELETE FROM breakglass_grants WHERE act = $1", tk)
            await conn.execute("DELETE FROM breakglass_requests WHERE act = $1", tk)
            await conn.execute("DELETE FROM users WHERE account = $1", tk)


def _yc(act: str, hyperedge_id: str = "HE-02", **sua) -> YeuCauBreakGlass:
    luc = thoi_diem_utc()
    goc = dict(
        id=ma_yeu_cau(), act=act, role="tech_support", space="synth", hyperedge_id=hyperedge_id,
        scope="noi_bo", content_type="bao_cao_su_co", nhom_duyet="Tech Support", ly_do="xin",
        k=K_MAC_DINH, thoi_han_phut=THOI_HAN_PHUT, trang_thai=TRANG_THAI_CHO_DUYET, tao_luc=luc, cap_nhat=luc,
    )
    goc.update(sua)
    return YeuCauBreakGlass(**goc)


class _SoAudit:
    def __init__(self, no: BaseException | None = None):
        self.da_ghi = []
        self.no = no

    async def __call__(self, yc):
        if self.no is not None:
            raise self.no
        self.da_ghi.append(yc)


async def _dem(kho: KhoBreakGlass, act: str) -> int:
    async with kho._pool.acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM breakglass_requests WHERE act = $1", act)


def test_ddl_idempotent_va_tao_doc_lai_dung_hang(cau_hinh_pg, session_prefix):
    act = f"{session_prefix}_ts01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act) as kho:
            await kho.khoi_tao()  # lần hai không đổi gì
            so = _SoAudit()
            yc = await kho.tao(_yc(act, ly_do="Khách VIP đang chờ"), so)
            assert so.da_ghi == [yc]
            (doc,) = await kho.cua_toi(act)
            assert doc == yc, "hàng đọc lại phải bằng hàng đã ghi, kể cả hai mốc thời gian ISO UTC"
            assert doc.tao_luc.endswith("+00:00")

    asyncio.run(chay())


def test_index_duy_nhat_mot_phan_bat_ca_race_va_khong_chan_sau_huy(cau_hinh_pg, session_prefix):
    act = f"{session_prefix}_ts01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act) as kho:
            yc = await kho.tao(_yc(act), _SoAudit())
            # Phép kiểm trước insert: 409.
            with pytest.raises(LoiHoiDap) as loi:
                await kho.tao(_yc(act, role="devops"), _SoAudit())
            assert loi.value.ma == MA_YEU_CAU_DANG_CHO
            # Đi vòng phép kiểm trước: chính index từ chối.
            hai = _yc(act)
            async with kho._pool.acquire() as conn:
                with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                    await conn.execute(
                        "INSERT INTO breakglass_requests (id, act, role, space, hyperedge_id, scope,"
                        " content_type, nhom_duyet, ly_do, k, thoi_han_phut, trang_thai, tao_luc, cap_nhat)"
                        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now(), now())",
                        hai.id, act, hai.role, hai.space, hai.hyperedge_id, hai.scope, hai.content_type,
                        hai.nhom_duyet, hai.ly_do, hai.k, hai.thoi_han_phut, hai.trang_thai,
                    )
            assert await _dem(kho, act) == 1
            # Hủy rồi thì index không còn chặn: xin lại được, và bảng có hai hàng.
            await kho.huy(yc.id, act, "synth", _SoAudit())
            await kho.tao(_yc(act), _SoAudit())
            assert await _dem(kho, act) == 2

    asyncio.run(chay())


def test_huy_co_dieu_kien_va_hai_ma_loi(cau_hinh_pg, session_prefix):
    act, khac = f"{session_prefix}_ts01", f"{session_prefix}_dev01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act, khac) as kho:
            yc = await kho.tao(_yc(act), _SoAudit())
            for id_yc, ai, sp in ((yc.id, khac, "synth"), ("bg-000000000000", act, "synth"), (yc.id, act, "khac")):
                with pytest.raises(LoiHoiDap) as loi:
                    await kho.huy(id_yc, ai, sp, _SoAudit())
                assert loi.value.ma == MA_YEU_CAU_KHONG_CO
            so = _SoAudit()
            moi = await kho.huy(yc.id, act, "synth", so)
            assert moi.trang_thai == TRANG_THAI_DA_HUY and moi.cap_nhat >= yc.cap_nhat and so.da_ghi == [moi]
            with pytest.raises(LoiHoiDap) as loi:
                await kho.huy(yc.id, act, "synth", _SoAudit())
            assert loi.value.ma == MA_YEU_CAU_KHONG_CON_CHO
            (doc,) = await kho.cua_toi(act)
            assert doc.trang_thai == TRANG_THAI_DA_HUY

    asyncio.run(chay())


def test_audit_hong_thi_rollback_ca_tao_lan_huy(cau_hinh_pg, session_prefix):
    act = f"{session_prefix}_ts01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act) as kho:
            with pytest.raises(RuntimeError):
                await kho.tao(_yc(act), _SoAudit(no=RuntimeError("audit chết")))
            assert await _dem(kho, act) == 0, "audit hỏng mà bảng vẫn có hàng: không rollback"
            yc = await kho.tao(_yc(act), _SoAudit())
            with pytest.raises(RuntimeError):
                await kho.huy(yc.id, act, "synth", _SoAudit(no=RuntimeError("audit chết")))
            (doc,) = await kho.cua_toi(act)
            assert doc.trang_thai == TRANG_THAI_CHO_DUYET

    asyncio.run(chay())


def test_cua_toi_moi_nhat_truoc_chi_cua_minh_va_gioi_han(cau_hinh_pg, session_prefix):
    act, khac = f"{session_prefix}_ts01", f"{session_prefix}_dev01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act, khac) as kho:
            a = await kho.tao(_yc(act, "HE-A", tao_luc="2026-01-01T00:00:00+00:00", cap_nhat="2026-01-01T00:00:00+00:00"), _SoAudit())
            b = await kho.tao(_yc(act, "HE-B"), _SoAudit())
            await kho.tao(_yc(khac, "HE-A"), _SoAudit())
            assert [y.id for y in await kho.cua_toi(act)] == [b.id, a.id]
            assert [y.id for y in await kho.cua_toi(act, 1)] == [b.id]
            assert {y.act for y in await kho.cua_toi(khac)} == {khac}

    asyncio.run(chay())


def test_grant_con_han_theo_cap_act_role(cau_hinh_pg, session_prefix):
    act = f"{session_prefix}_ts01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act) as kho:
            assert await kho.co_grant_con_han(act, "tech_support", "HE-02") is False
            await chen_grant(kho, act=act, role="tech_support", hyperedge_ids=["HE-02", "HE-09"], con_han_phut=10)
            assert await kho.co_grant_con_han(act, "tech_support", "HE-02") is True
            assert await kho.co_grant_con_han(act, "tech_support", "HE-09") is True
            assert await kho.co_grant_con_han(act, "devops", "HE-02") is False, "grant ở vai khác ngủ"
            assert await kho.co_grant_con_han(act, "tech_support", "HE-01") is False
            await chen_grant(kho, act=act, role="devops", hyperedge_ids=["HE-01"], con_han_phut=-1)
            assert await kho.co_grant_con_han(act, "devops", "HE-01") is False, "grant hết hạn không chặn"

    asyncio.run(chay())


def test_race_tao_index_bat_khi_phep_kiem_truoc_mu(cau_hinh_pg, session_prefix, monkeypatch):
    """Phép kiểm trước insert bị làm mù: chính index bắt hàng thứ hai qua `tao`, cùng mã 409, bảng giữ một hàng."""
    act = f"{session_prefix}_ts01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act) as kho:
            await kho.tao(_yc(act), _SoAudit())
            monkeypatch.setattr(bg, "_SQL_DANG_CHO", "SELECT 1 WHERE $1::text = $2::text AND false")
            so = _SoAudit()
            with pytest.raises(LoiHoiDap) as loi:
                await kho.tao(_yc(act), so)
            assert loi.value.ma == MA_YEU_CAU_DANG_CHO
            assert so.da_ghi == [], "index từ chối thì không tới bước audit"
            assert await _dem(kho, act) == 1

    asyncio.run(chay())


def test_race_huy_update_co_dieu_kien_thang_phep_doc_phan_loai(cau_hinh_pg, session_prefix, monkeypatch):
    """Hàng đã `da_huy` giữa phép đọc phân loại và UPDATE: 0 hàng cập nhật, 409, không audit."""
    act = f"{session_prefix}_ts01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act) as kho:
            yc = await kho.tao(_yc(act), _SoAudit())
            # Kết nối thứ hai hủy trước; phép đọc phân loại bị thay bằng một hàng `cho_duyet` giả.
            async with kho._pool.acquire() as conn2:
                await conn2.execute(
                    "UPDATE breakglass_requests SET trang_thai = $2 WHERE id = $1", yc.id, TRANG_THAI_DA_HUY
                )
            monkeypatch.setattr(
                bg, "_SQL_MOT_CUA_ACT",
                f"SELECT '{TRANG_THAI_CHO_DUYET}' AS trang_thai WHERE $1::text = $1::text AND $2::text = $2::text AND $3::text = $3::text",
            )
            so = _SoAudit()
            with pytest.raises(LoiHoiDap) as loi:
                await kho.huy(yc.id, act, "synth", so)
            assert loi.value.ma == MA_YEU_CAU_KHONG_CON_CHO
            assert so.da_ghi == []
            (doc,) = await kho.cua_toi(act)
            assert doc.trang_thai == TRANG_THAI_DA_HUY

    asyncio.run(chay())


def test_grant_con_han_chan_tao_ben_trong_transaction(cau_hinh_pg, session_prefix):
    act = f"{session_prefix}_ts01"

    async def chay():
        async with kho_bg(cau_hinh_pg, act) as kho:
            await chen_grant(kho, act=act, role="tech_support", hyperedge_ids=["HE-02"], con_han_phut=10)
            so = _SoAudit()
            with pytest.raises(LoiHoiDap) as loi:
                await kho.tao(_yc(act), so)
            assert loi.value.ma == MA_GRANT_CON_HAN
            assert so.da_ghi == [] and await _dem(kho, act) == 0
            # Vai khác không bị grant ấy chặn; grant hết hạn cũng không.
            await kho.tao(_yc(act, role="devops"), _SoAudit())
            assert await _dem(kho, act) == 1

    asyncio.run(chay())
