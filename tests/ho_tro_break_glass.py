"""Bản giả của `api.break_glass.KhoBreakGlass` và helper chèn grant (story 5.1).

`KhoBreakGlassGia` giữ hai bảng trong hai dict và **mô phỏng đúng ba cơ chế**
của bản Postgres mà bộ test HTTP cần chấm: index duy nhất một phần
`(act, hyperedge_id) WHERE trang_thai = 'cho_duyet'` (kể cả khi phép kiểm
trước insert bị tắt bằng `bo_kiem_truoc`, để chấm ca race ra cùng mã), hủy có
điều kiện (`UPDATE ... WHERE trang_thai = 'cho_duyet'`, 0 hàng là thất bại), và
**rollback khi audit hỏng**: hàng chỉ vào dict sau khi `ghi_audit` trả về.

`chen_grant` là **đường ghi duy nhất** vào `breakglass_grants` ở story này -
helper test, không phải sản phẩm - và nhận cả bản giả lẫn `KhoBreakGlass` thật
để bộ `postgres` và bộ HTTP dùng chung một lời gọi.

Mọi TestClient của suite chạy lifespan thật, và lifespan từ 5.1 mở kho thứ tư;
`tests/conftest.py::kho_break_glass_gia` cài bản này cho cả suite.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Sequence

from api.break_glass import (
    KhoBreakGlass,
    YeuCauBreakGlass,
    loi_dang_cho,
    loi_grant_con_han,
    loi_khong_con_cho,
    loi_yeu_cau_khong_co,
)
from core.audit import thoi_diem_utc
from core.break_glass import TRANG_THAI_CHO_DUYET, TRANG_THAI_DA_HUY, huy_duoc


class KhoBreakGlassGia:
    """Cùng interface với `KhoBreakGlass`: `tao`, `huy`, `cua_toi`, `co_grant_con_han`, `dong`."""

    def __init__(self):
        self.yeu_cau: dict[str, YeuCauBreakGlass] = {}
        # (act, role, hyperedge_ids, expires_at)
        self.grants: list[tuple[str, str, tuple[str, ...], datetime]] = []
        self.no: BaseException | None = None
        self.bo_kiem_truoc = False
        self.da_dong = False
        self.so_lan_tao = 0

    def _dang_cho(self, act: str, hyperedge_id: str) -> bool:
        return any(
            y.act == act and y.hyperedge_id == hyperedge_id and y.trang_thai == TRANG_THAI_CHO_DUYET
            for y in self.yeu_cau.values()
        )

    async def tao(self, yc: YeuCauBreakGlass, ghi_audit) -> YeuCauBreakGlass:
        if self.no is not None:
            raise self.no
        self.so_lan_tao += 1
        # Cùng thứ tự với bản Postgres: grant còn hạn, rồi đang chờ, rồi ghi.
        if await self.co_grant_con_han(yc.act, yc.role, yc.hyperedge_id):
            raise loi_grant_con_han()
        if not self.bo_kiem_truoc and self._dang_cho(yc.act, yc.hyperedge_id):
            raise loi_dang_cho()
        # "Index duy nhất": kiểm lại ngay trước khi ghi, bất kể phép kiểm trước.
        if self._dang_cho(yc.act, yc.hyperedge_id):
            raise loi_dang_cho()
        # INSERT -> audit -> COMMIT: hàng chỉ vào dict khi audit đã ghi.
        await ghi_audit(yc)
        self.yeu_cau[yc.id] = yc
        return yc

    async def huy(self, id_yeu_cau: str, act: str, space: str, ghi_audit) -> YeuCauBreakGlass:
        if self.no is not None:
            raise self.no
        cu = self.yeu_cau.get(id_yeu_cau)
        if cu is None or cu.act != act or cu.space != space:
            raise loi_yeu_cau_khong_co()
        if not huy_duoc(cu.trang_thai):
            raise loi_khong_con_cho()
        moi = replace(cu, trang_thai=TRANG_THAI_DA_HUY, cap_nhat=thoi_diem_utc())
        await ghi_audit(moi)
        self.yeu_cau[id_yeu_cau] = moi
        return moi

    async def cua_toi(self, act: str, gioi_han: int = 100) -> tuple[YeuCauBreakGlass, ...]:
        if self.no is not None:
            raise self.no
        cua = [y for y in self.yeu_cau.values() if y.act == act]
        cua.sort(key=lambda y: (y.tao_luc, y.id), reverse=True)
        return tuple(cua[:gioi_han])

    async def co_grant_con_han(self, act: str, role: str, hyperedge_id: str) -> bool:
        if self.no is not None:
            raise self.no
        bay_gio = datetime.now(timezone.utc)
        return any(
            a == act and r == role and hyperedge_id in ids and het > bay_gio
            for a, r, ids, het in self.grants
        )

    async def dong(self) -> None:
        self.da_dong = True


async def chen_grant(
    kho,
    *,
    act: str,
    role: str,
    hyperedge_ids: Sequence[str],
    con_han_phut: float = 10,
    space: str = "synth",
    cap_boi: str = "test",
) -> str:
    """Chèn một grant cho cặp (`act`, `role`); `con_han_phut` âm là grant đã hết hạn.

    Trả id grant. Với `KhoBreakGlass` thật nó INSERT thẳng bằng pool của kho -
    sản phẩm không có đường ghi này ở 5.1.
    """
    import uuid

    het = datetime.now(timezone.utc) + timedelta(minutes=con_han_phut)
    ma = "grant-" + uuid.uuid4().hex[:12]
    if isinstance(kho, KhoBreakGlassGia):
        kho.grants.append((act, role, tuple(hyperedge_ids), het))
        return ma
    assert isinstance(kho, KhoBreakGlass)
    async with kho._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO breakglass_grants"
            " (id, request_id, act, role, space, hyperedge_ids, expires_at, cap_boi)"
            " VALUES ($1, NULL, $2, $3, $4, $5, $6, $7)",
            ma, act, role, space, list(hyperedge_ids), het, cap_boi,
        )
    return ma
