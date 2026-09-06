"""Hiện thực Postgres tối thiểu của audit port (AD-16, story 2.2).

Ở `api/` vì đây là trạng thái ứng dụng (AD-7: users, breakglass_*, audit_log
chỉ ở Postgres) và vì `adapters/` với `eval/` không được import `api/`: cả hai
chỉ cần interface `core.audit.AuditPort`, còn hiện thực tiêm vào từ tiến trình
phục vụ (lifespan, Epic 3) hoặc từ script đo (`api/do_chi_phi.py`).

Tối thiểu nghĩa là: một bảng, một lệnh ghi, một phép cộng. Sự kiện lọc / từ
chối / truy vấn của adapter và màn tình trạng (3.6, FR-25) đứng lên chính bảng
này mà không đổi lược đồ, vì phần riêng của mỗi sự kiện là jsonb. Không có
đường xóa: audit là sổ chỉ ghi thêm, dọn dữ liệu test là việc của bộ test.

Story 3.6 thêm **đúng hai** cửa đọc, cả hai tham số hóa hoàn toàn (f-string chỉ
ghép hằng tên trường, mọi đầu vào đi qua `$n`):

- `dem_su_kien(event, *, space, tu, den, theo)` gom số hàng của một sự kiện
  theo một khóa `chi_tiet` (hai cột của Đo 2 là `theo="ly_do"` trên `refusal`;
  `tu_khoa_rong` ra thành hàng thứ ba, không cộng vào cột nào - ADR-017), và
  trả kèm `so_khong_dong_bo`: số hàng **không** mang tầng mutation trong cửa
  sổ. Cửa đếm phải nói được cửa sổ có hàng nào không được bảo đảm, vì `refusal`
  ghi observation khi cờ chế độ đo tắt và một hàng như thế được phép mất.
- `su_kien_tien_trinh(tu, den)` là cửa đọc "hệ chạy bảng nào, từ lúc nào": mọi
  hàng mang `space = SPACE_TIEN_TRINH` (`startup`, `policy_swap`, `auth_login`)
  theo thời gian. `tong_chi_phi` và `dem_su_kien` lọc `space = $1` nên không
  bao giờ thấy chúng - đó là luật của hằng ấy ở `core/audit.py`.

Async toàn tuyến bằng `asyncpg` (spine Stack 0.31); pool nhỏ vì chỉ có một tiến
trình phục vụ và một script đo.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
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
from core.audit import (
    EVENT_EMBEDDING_COST,
    EVENT_LLM_COST,
    EVENTS,
    SPACE_TIEN_TRINH,
    TIER_MUTATION,
    SuKienAudit,
    kiem_thoi_diem,
)
from core.ids import validate_space

# Trần số hàng mà `su_kien_tien_trinh` trả trong một lần đọc: sổ chỉ ghi thêm
# và một tiến trình khởi động lại nhiều tháng thì dãy này không có trần tự nhiên.
GIOI_HAN_TIEN_TRINH: int = 1000

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


@dataclass(frozen=True)
class DemSuKien:
    """Kết quả của `dem_su_kien`.

    `so_theo` là số hàng theo giá trị của `chi_tiet->>theo` (khóa `None` là hàng
    không có trường đó); `theo=None` là không gom, khi đó `so_theo` rỗng và chỉ
    `tong` có nghĩa. `tong` là tổng; và
    `so_khong_dong_bo` là số hàng trong cửa sổ **không** mang tầng mutation -
    những hàng được phép mất theo AD-16, nên một cửa sổ đo mà số này khác 0 là
    một mẫu số phải đọc kèm dấu hỏi.
    """

    so_theo: dict
    tong: int
    so_khong_dong_bo: int


# Đếm theo một khóa `chi_tiet`. `chi_tiet->>$5` nhận tên khóa qua tham số nên
# không có tên trường nào ghép vào câu; `$5` là NULL thì gom về một hàng.
_SQL_DEM_SU_KIEN = f"""
    SELECT chi_tiet->>$5::text AS khoa,
           count(*) AS so_hang,
           count(*) FILTER (WHERE tier <> '{TIER_MUTATION}') AS khong_dong_bo
    FROM audit_log
    WHERE space = $1
      AND event = $2
      AND ($3::timestamptz IS NULL OR thoi_diem >= $3)
      AND ($4::timestamptz IS NULL OR thoi_diem < $4)
    GROUP BY 1
    ORDER BY 1
"""

_SQL_SU_KIEN_TIEN_TRINH = """
    SELECT thoi_diem, tier, event, act, role, space, policy_version, hyperedge_ids, chi_tiet
    FROM audit_log
    WHERE space = $1
      AND ($2::timestamptz IS NULL OR thoi_diem >= $2)
      AND ($3::timestamptz IS NULL OR thoi_diem < $3)
    ORDER BY thoi_diem, id
    LIMIT $4
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

    async def dem_su_kien(
        self,
        event: str,
        *,
        space: str,
        tu: str | None = None,
        den: str | None = None,
        theo: str | None = None,
    ) -> DemSuKien:
        """Số hàng của một sự kiện trong một space và cửa sổ, gom theo một khóa `chi_tiet`.

        `event` phải nằm trong danh mục của `core/audit.py`: một tên gõ sai đếm
        ra 0 là một con số trông như thật. `space` phải là một space thật
        (`validate_space`): `"*"` không phải space và có cửa đọc riêng. `tu`/`den`
        nửa mở `[tu, den)`, cùng luật với `tong_chi_phi`, và `tu >= den` là một
        cửa sổ rỗng gõ nhầm chứ không phải một số 0. `theo=None` là không gom,
        `so_theo` rỗng; `theo=""` là tên khóa gõ thiếu.
        """
        if event not in EVENTS:
            raise ValueError(f"event {event!r} không có trong danh mục {sorted(EVENTS)}")
        if space == SPACE_TIEN_TRINH:
            raise ValueError(
                f"space {SPACE_TIEN_TRINH!r} là sự kiện tiến trình, đọc bằng su_kien_tien_trinh"
            )
        validate_space(space)
        if theo is not None and not isinstance(theo, str):
            raise TypeError(f"theo phải là chuỗi hoặc None, nhận được {type(theo).__name__}")
        if theo == "":
            raise ValueError("theo rỗng: tên khóa chi_tiet gõ thiếu")
        moc = kiem_thoi_diem(tu) if tu else None
        moc_ket = kiem_thoi_diem(den) if den else None
        if moc is not None and moc_ket is not None and moc >= moc_ket:
            raise ValueError(f"cửa sổ rỗng: tu={tu!r} không nhỏ hơn den={den!r}")
        async with self._pool.acquire() as conn:
            hang = await conn.fetch(_SQL_DEM_SU_KIEN, space, event, moc, moc_ket, theo)
        tong = sum(int(h["so_hang"]) for h in hang)
        return DemSuKien(
            so_theo={} if theo is None else {h["khoa"]: int(h["so_hang"]) for h in hang},
            tong=tong,
            so_khong_dong_bo=sum(int(h["khong_dong_bo"]) for h in hang),
        )

    async def su_kien_tien_trinh(
        self, *, tu: str | None = None, den: str | None = None, gioi_han: int = GIOI_HAN_TIEN_TRINH
    ) -> tuple[SuKienAudit, ...]:
        """Hàng thuộc tiến trình (`space = SPACE_TIEN_TRINH`) theo thời gian, tối đa `gioi_han`.

        Dựng lại thành `SuKienAudit` qua đúng bộ kiểm lúc ghi, nên một hàng mà
        ai đó chèn tay với `event` lạ nổ ở đây chứ không đi tiếp thành dữ liệu.
        """
        if not isinstance(gioi_han, int) or gioi_han < 1:
            raise ValueError(f"gioi_han phải là số nguyên dương, nhận được {gioi_han!r}")
        moc = kiem_thoi_diem(tu) if tu else None
        moc_ket = kiem_thoi_diem(den) if den else None
        if moc is not None and moc_ket is not None and moc >= moc_ket:
            raise ValueError(f"cửa sổ rỗng: tu={tu!r} không nhỏ hơn den={den!r}")
        async with self._pool.acquire() as conn:
            hang = await conn.fetch(_SQL_SU_KIEN_TIEN_TRINH, SPACE_TIEN_TRINH, moc, moc_ket, gioi_han)
        return tuple(_su_kien_tu_hang(h) for h in hang)

    async def dong(self) -> None:
        await self._pool.close()


def _su_kien_tu_hang(h) -> SuKienAudit:
    chi_tiet = h["chi_tiet"]
    if isinstance(chi_tiet, str):
        chi_tiet = json.loads(chi_tiet)
    return SuKienAudit(
        tier=h["tier"],
        event=h["event"],
        space=h["space"],
        policy_version=h["policy_version"],
        thoi_diem=h["thoi_diem"].astimezone(timezone.utc).isoformat(),
        act=h["act"],
        role=h["role"],
        hyperedge_ids=tuple(h["hyperedge_ids"] or ()),
        chi_tiet=chi_tiet or {},
    )
