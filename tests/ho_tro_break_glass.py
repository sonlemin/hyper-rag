"""Bản giả của `api.break_glass.KhoBreakGlass` và helper chèn grant (story 5.1, mở rộng 5.2).

`KhoBreakGlassGia` giữ hai bảng trong bộ nhớ và **mô phỏng đúng các cơ chế**
của bản Postgres mà bộ test HTTP cần chấm: index duy nhất một phần
`(act, hyperedge_id) WHERE trang_thai = 'cho_duyet'` (kể cả khi phép kiểm
trước insert bị tắt bằng `bo_kiem_truoc`, để chấm ca race ra cùng mã), phép
chuyển có điều kiện (`UPDATE ... WHERE trang_thai = 'cho_duyet'`, 0 hàng là
thất bại - hủy ở 5.1, duyệt và từ chối ở 5.2), grant còn hạn kiểm bên trong
"transaction" của duyệt/cấp, và **rollback khi audit hỏng**: hàng và grant
chỉ vào bộ nhớ sau khi `ghi_audit` trả về.

`grants` là danh sách `Grant` (dataclass của `api/break_glass.py`) từ 5.2, nên
`chen_grant`, `co_grant_con_han` và đường ghi sản phẩm dùng chung một hình
dạng. `chen_grant` vẫn là helper test và nhận cả bản giả lẫn `KhoBreakGlass`
thật để bộ `postgres` và bộ HTTP dùng chung một lời gọi.

Mọi TestClient của suite chạy lifespan thật, và lifespan từ 5.1 mở kho thứ tư;
`tests/conftest.py::kho_break_glass_gia` cài bản này cho cả suite.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Sequence

from api.break_glass import (
    Grant,
    KhoBreakGlass,
    YeuCauBreakGlass,
    loi_dang_cho,
    loi_grant_con_han,
    loi_khong_con_cho,
    loi_vung_cap_rong,
    loi_yeu_cau_khong_co,
    ma_grant,
)
from core.audit import kiem_thoi_diem, thoi_diem_utc
from core.break_glass import (
    TRANG_THAI_CHO_DUYET,
    TRANG_THAI_DA_DUYET,
    TRANG_THAI_DA_HUY,
    TRANG_THAI_TU_CHOI,
    huy_duoc,
)


class KhoBreakGlassGia:
    """Cùng interface với `KhoBreakGlass`: `tao`, `huy`, `cua_toi`, `tra_mot`, `hang_cho`, `duyet`, `tu_choi`, `cap`, `co_grant_con_han`, `dong`."""

    def __init__(self):
        self.yeu_cau: dict[str, YeuCauBreakGlass] = {}
        self.grants: list[Grant] = []
        self.no: BaseException | None = None
        self.bo_kiem_truoc = False
        self.da_dong = False
        self.so_lan_tao = 0
        self.so_lan_duyet = 0

    def _dang_cho(self, act: str, hyperedge_id: str) -> bool:
        return any(
            y.act == act and y.hyperedge_id == hyperedge_id and y.trang_thai == TRANG_THAI_CHO_DUYET
            for y in self.yeu_cau.values()
        )

    def _grant_con_han(self, act: str, role: str, hyperedge_id: str, space: str) -> bool:
        bay_gio = datetime.now(timezone.utc)
        return any(
            g.act == act and g.role == role and g.space == space and hyperedge_id in g.hyperedge_ids
            and kiem_thoi_diem(g.expires_at) > bay_gio
            for g in self.grants
        )

    def _kiem_grant_ca_vung(self, act: str, role: str, space: str, hyperedge_ids) -> None:
        """Cùng luật bản thật: bất kỳ id nào của vùng đang nằm trong grant còn hạn của cặp là 409."""
        for id_he in hyperedge_ids:
            if self._grant_con_han(act, role, id_he, space):
                raise loi_grant_con_han()

    async def tao(self, yc: YeuCauBreakGlass, ghi_audit) -> YeuCauBreakGlass:
        if self.no is not None:
            raise self.no
        self.so_lan_tao += 1
        # Cùng thứ tự với bản Postgres: grant còn hạn, rồi đang chờ, rồi ghi.
        if self._grant_con_han(yc.act, yc.role, yc.hyperedge_id, yc.space):
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

    async def tra_mot(self, id_yeu_cau: str) -> YeuCauBreakGlass | None:
        if self.no is not None:
            raise self.no
        return self.yeu_cau.get(id_yeu_cau)

    async def hang_cho(self, nhom_duyet: str, space: str, gioi_han: int = 100) -> tuple[YeuCauBreakGlass, ...]:
        if self.no is not None:
            raise self.no
        cua = [
            y for y in self.yeu_cau.values()
            if y.nhom_duyet == nhom_duyet and y.space == space and y.trang_thai == TRANG_THAI_CHO_DUYET
        ]
        cua.sort(key=lambda y: (y.tao_luc, y.id))
        return tuple(cua[:gioi_han])

    def _phep_chuyen(self, id_yeu_cau: str) -> YeuCauBreakGlass:
        """`UPDATE ... WHERE trang_thai = 'cho_duyet'`: 0 hàng phân loại 404/409 như bản thật."""
        cu = self.yeu_cau.get(id_yeu_cau)
        if cu is None:
            raise loi_yeu_cau_khong_co()
        if cu.trang_thai != TRANG_THAI_CHO_DUYET:
            raise loi_khong_con_cho()
        return cu

    def _grant_moi(self, *, request_id, act, role, space, hyperedge_ids, thoi_han_phut, cap_boi) -> Grant:
        tao = datetime.now(timezone.utc)
        return Grant(
            id=ma_grant(),
            request_id=request_id,
            act=act,
            role=role,
            space=space,
            hyperedge_ids=tuple(hyperedge_ids),
            expires_at=(tao + timedelta(minutes=thoi_han_phut)).isoformat(),
            cap_boi=cap_boi,
            tao_luc=tao.isoformat(),
        )

    async def duyet(self, id_yeu_cau: str, *, xu_ly_boi: str, vung: tuple[str, ...], ghi_audit):
        if self.no is not None:
            raise self.no
        self.so_lan_duyet += 1
        if not vung:
            raise loi_vung_cap_rong()
        cu = self._phep_chuyen(id_yeu_cau)
        moi = replace(cu, trang_thai=TRANG_THAI_DA_DUYET, xu_ly_boi=xu_ly_boi, cap_nhat=thoi_diem_utc())
        self._kiem_grant_ca_vung(cu.act, cu.role, cu.space, vung)
        grant = self._grant_moi(
            request_id=cu.id, act=cu.act, role=cu.role, space=cu.space,
            hyperedge_ids=vung, thoi_han_phut=cu.thoi_han_phut, cap_boi=xu_ly_boi,
        )
        # UPDATE -> INSERT grant -> audit -> COMMIT: cả hai chỉ vào bộ nhớ sau audit.
        await ghi_audit(moi, grant)
        self.yeu_cau[id_yeu_cau] = moi
        self.grants.append(grant)
        return moi, grant

    async def tu_choi(self, id_yeu_cau: str, *, xu_ly_boi: str, ly_do: str, ghi_audit) -> YeuCauBreakGlass:
        if self.no is not None:
            raise self.no
        cu = self._phep_chuyen(id_yeu_cau)
        moi = replace(
            cu, trang_thai=TRANG_THAI_TU_CHOI, ly_do_tu_choi=ly_do, xu_ly_boi=xu_ly_boi, cap_nhat=thoi_diem_utc()
        )
        await ghi_audit(moi, None)
        self.yeu_cau[id_yeu_cau] = moi
        return moi

    async def cap(self, *, act, role, space, hyperedge_ids, thoi_han_phut, cap_boi, ghi_audit) -> Grant:
        if self.no is not None:
            raise self.no
        if not hyperedge_ids:
            raise loi_vung_cap_rong()
        self._kiem_grant_ca_vung(act, role, space, hyperedge_ids)
        grant = self._grant_moi(
            request_id=None, act=act, role=role, space=space,
            hyperedge_ids=hyperedge_ids, thoi_han_phut=thoi_han_phut, cap_boi=cap_boi,
        )
        await ghi_audit(None, grant)
        self.grants.append(grant)
        return grant

    async def co_grant_con_han(self, act: str, role: str, hyperedge_id: str, space: str) -> bool:
        if self.no is not None:
            raise self.no
        return self._grant_con_han(act, role, hyperedge_id, space)

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

    Trả id grant. Helper test, không phải sản phẩm: nó là cách duy nhất chèn
    một grant **đã hết hạn** (đường sản phẩm luôn ghi `now() + thời hạn`). Với
    `KhoBreakGlass` thật nó INSERT thẳng bằng pool của kho, `expires_at` truyền
    từ Python - đúng thứ đường sản phẩm cấm, và chỉ helper này được làm.
    """
    het = datetime.now(timezone.utc) + timedelta(minutes=con_han_phut)
    ma = ma_grant()
    if isinstance(kho, KhoBreakGlassGia):
        tao = datetime.now(timezone.utc)
        # Grant đã hết hạn vẫn phải dựng được: `Grant` đòi `expires_at > tao_luc`,
        # nên `tao_luc` lùi về trước mốc hết hạn.
        if het <= tao:
            tao = het - timedelta(minutes=1)
        kho.grants.append(
            Grant(
                id=ma, request_id=None, act=act, role=role, space=space,
                hyperedge_ids=tuple(hyperedge_ids), expires_at=het.isoformat(),
                cap_boi=cap_boi, tao_luc=tao.isoformat(),
            )
        )
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
