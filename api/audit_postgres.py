"""Hiện thực Postgres tối thiểu của audit port (AD-16, story 2.2).

Ở `api/` vì đây là trạng thái ứng dụng (AD-7: users, breakglass_*, audit_log
chỉ ở Postgres) và vì `adapters/` với `eval/` không được import `api/`: cả hai
chỉ cần interface `core.audit.AuditPort`, còn hiện thực tiêm vào từ tiến trình
phục vụ (lifespan, Epic 3) hoặc từ script đo (`api/do_chi_phi.py`).

Tối thiểu nghĩa là: một bảng, một lệnh ghi, một phép cộng. Sự kiện lọc / từ
chối / truy vấn của adapter và màn tình trạng (3.6, FR-25) đứng lên chính bảng
này mà không đổi lược đồ, vì phần riêng của mỗi sự kiện là jsonb. Không có
đường xóa: audit là sổ chỉ ghi thêm, dọn dữ liệu test là việc của bộ test.

Async toàn tuyến bằng `asyncpg` (spine Stack 0.31); pool nhỏ vì chỉ có một tiến
trình phục vụ và một script đo.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping

import asyncpg

from adapters.llm_wrapper import (
    CT_CHI_PHI_USD,
    CT_MODEL,
    CT_NHA_CUNG_CAP,
    CT_TOKEN_RA,
    CT_TOKEN_VAO,
)
from core.audit import EVENT_EMBEDDING_COST, EVENT_LLM_COST, SuKienAudit, kiem_thoi_diem

DUONG_DAN_DDL: Path = Path(__file__).resolve().parent / "sql" / "audit_log.sql"

# Biến môi trường của compose (service `api` và `postgres` dùng chung ba biến
# `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`). Cổng có mặc định vì compose
# không publish và trong network nội bộ luôn là 5432.
BIEN_POSTGRES: dict[str, str] = {
    "host": "POSTGRES_HOST",
    "port": "POSTGRES_PORT",
    "user": "POSTGRES_USER",
    "password": "POSTGRES_PASSWORD",
    "database": "POSTGRES_DB",
}
PORT_MAC_DINH: int = 5432
CAC_SU_KIEN_CHI_PHI: tuple[str, ...] = (EVENT_LLM_COST, EVENT_EMBEDDING_COST)


class PostgresConfigMissing(ValueError):
    """Thiếu hoặc sai một tham số kết nối Postgres trong môi trường."""

    code = "POSTGRES_CONFIG_MISSING"


def cau_hinh_postgres_tu_moi_truong(moi_truong: Mapping[str, str] | None = None) -> dict:
    """Tham số kết nối từ môi trường, cùng luật với `cau_hinh_kho_tu_moi_truong`.

    Biến rỗng là chưa đặt. Thiếu host/user/password/database, hay cổng không
    phải số trong 1..65535, là lỗi có mã ở đây, không phải một `asyncpg` nổ với
    thông điệp về socket.
    """
    nguon = os.environ if moi_truong is None else moi_truong
    cau_hinh: dict = {}
    for khoa, ten_bien in BIEN_POSTGRES.items():
        gia_tri = nguon.get(ten_bien)
        if gia_tri is None:
            continue
        gon = str(gia_tri).strip()
        if gon:
            cau_hinh[khoa] = gon
    thieu = [BIEN_POSTGRES[k] for k in ("host", "user", "password", "database") if k not in cau_hinh]
    if thieu:
        raise PostgresConfigMissing(f"thiếu biến môi trường Postgres: {thieu}")
    cong = cau_hinh.get("port", str(PORT_MAC_DINH))
    if not cong.isdigit() or not 1 <= int(cong) <= 65535:
        raise PostgresConfigMissing(
            f"{BIEN_POSTGRES['port']} phải là số trong 1..65535, nhận được {cong!r}"
        )
    cau_hinh["port"] = int(cong)
    return cau_hinh


@dataclass(frozen=True)
class DongChiPhi:
    """Tổng của một cặp (model, nhà cung cấp) trong một space."""

    model: str
    nha_cung_cap: str
    so_lan: int
    token_vao: int
    token_ra: int
    chi_phi_usd: float


@dataclass(frozen=True)
class TongChiPhi:
    so_lan: int
    token_vao: int
    token_ra: int
    chi_phi_usd: float
    theo_model: tuple[DongChiPhi, ...]


# Câu cộng theo model. f-string ở đây **chỉ** ghép các hằng CT_* (tên trường
# trong jsonb, khai ở adapters/llm_wrapper.py), không bao giờ ghép giá trị
# động: mọi đầu vào của người gọi (space, mốc thời gian) đi qua tham số $n.
_SQL_TONG_CHI_PHI = f"""
    SELECT chi_tiet->>'{CT_MODEL}' AS model,
           chi_tiet->>'{CT_NHA_CUNG_CAP}' AS nha_cung_cap,
           count(*) AS so_lan,
           coalesce(sum((chi_tiet->>'{CT_TOKEN_VAO}')::bigint), 0) AS token_vao,
           coalesce(sum((chi_tiet->>'{CT_TOKEN_RA}')::bigint), 0) AS token_ra,
           coalesce(sum((chi_tiet->>'{CT_CHI_PHI_USD}')::numeric), 0) AS chi_phi_usd
    FROM audit_log
    WHERE space = $1
      AND event = ANY($2::text[])
      AND ($3::timestamptz IS NULL OR thoi_diem >= $3)
      AND ($4::timestamptz IS NULL OR thoi_diem < $4)
    GROUP BY 1, 2
    ORDER BY 1, 2
"""


class AuditPostgres:
    """`AuditPort` trên bảng `audit_log`; sở hữu pool nó mở."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def mo(cls, cau_hinh: Mapping | None = None) -> "AuditPostgres":
        """Mở pool từ cấu hình (mặc định đọc môi trường)."""
        cau_hinh = cau_hinh_postgres_tu_moi_truong() if cau_hinh is None else dict(cau_hinh)
        pool = await asyncpg.create_pool(min_size=1, max_size=4, **cau_hinh)
        return cls(pool)

    async def khoi_tao(self) -> None:
        """Chạy DDL idempotent; gọi mỗi lần tiến trình lên, lặp lại không đổi gì."""
        ddl = DUONG_DAN_DDL.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            await conn.execute(ddl)

    async def ghi(self, su_kien: SuKienAudit) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log
                    (thoi_diem, tier, event, act, role, space, policy_version,
                     hyperedge_ids, chi_tiet)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                """,
                datetime.fromisoformat(su_kien.thoi_diem),
                su_kien.tier,
                su_kien.event,
                su_kien.act,
                su_kien.role,
                su_kien.space,
                su_kien.policy_version,
                list(su_kien.hyperedge_ids),
                json.dumps(dict(su_kien.chi_tiet), ensure_ascii=False),
            )

    async def tong_chi_phi(
        self, space: str, *, tu: str | None = None, den: str | None = None
    ) -> TongChiPhi:
        """Tổng token và USD của các sự kiện chi phí trong một space, theo model.

        `tu`/`den` là mốc ISO-8601 UTC (cùng luật với `thoi_diem` của sự kiện),
        nửa mở `[tu, den)`, để đọc riêng một đoạn (một tài liệu của một lần
        nạp) thay vì cả lịch sử. Cộng bằng SQL chứ không kéo hàng về, và cả
        dòng theo model lẫn dòng tổng cùng một cửa sổ: FR-25 đọc lũy kế từ đây.
        """
        moc = kiem_thoi_diem(tu) if tu else None
        moc_ket = kiem_thoi_diem(den) if den else None
        async with self._pool.acquire() as conn:
            hang = await conn.fetch(_SQL_TONG_CHI_PHI, space, list(CAC_SU_KIEN_CHI_PHI), moc, moc_ket)
        theo_model = tuple(
            DongChiPhi(
                model=h["model"] or "",
                nha_cung_cap=h["nha_cung_cap"] or "",
                so_lan=int(h["so_lan"]),
                token_vao=int(h["token_vao"]),
                token_ra=int(h["token_ra"]),
                chi_phi_usd=float(h["chi_phi_usd"] or Decimal(0)),
            )
            for h in hang
        )
        return TongChiPhi(
            so_lan=sum(d.so_lan for d in theo_model),
            token_vao=sum(d.token_vao for d in theo_model),
            token_ra=sum(d.token_ra for d in theo_model),
            chi_phi_usd=sum(d.chi_phi_usd for d in theo_model),
            theo_model=theo_model,
        )

    async def dong(self) -> None:
        await self._pool.close()
