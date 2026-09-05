"""Cổng Postgres của bảng `users` (AD-7, story 3.1).

Ở `api/` vì đây là trạng thái ứng dụng - AD-7 chốt `users`, `breakglass_*` và
`audit_log` chỉ ở Postgres - và vì `adapters/` với `eval/` không được import
`api/`. Cùng khuôn với `api/audit_postgres.py`, và dùng lại nguyên phép đọc
cấu hình môi trường của nó thay vì viết bản thứ hai: hai bản thì một hôm nào đó
tiến trình phục vụ mở hai kết nối tới hai Postgres khác nhau.

**Một chiều, từ file xuống bảng.** `config/tai-khoan.yaml` là nguồn; bảng là
nơi trạng thái sống và là nơi Epic 5 khóa ngoại về. `dong_bo` chạy lúc khởi
động, `INSERT ... ON CONFLICT DO UPDATE`, nên chạy lại không đổi gì và sửa seed
thì lần khởi động sau là đủ. Không có đường ngược lại: một bảng ghi ngược vào
YAML là hai nguồn sự thật cho cùng một câu hỏi.

**Không xóa tài khoản vắng mặt trong seed.** Xóa một dòng `users` là xóa chủ sở
hữu của những hàng `audit_log` và (từ Epic 5) `breakglass_*` trỏ tới nó, và một
seed gõ sót một dòng khi đó thành một phép xóa im lặng lúc khởi động. Gỡ quyền
một người là một thao tác có chủ đích, không phải hệ quả phụ của một lần deploy.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import asyncpg

from adapters.identity_seed import MucTaiKhoan, nap_tai_khoan
from api.audit_postgres import cau_hinh_postgres_tu_moi_truong

DUONG_DAN_DDL: Path = Path(__file__).resolve().parent / "sql" / "users.sql"

_SQL_DONG_BO = """
    INSERT INTO users
        (account, mat_khau_hash, role, group_name, khong_gian, demo, admin, cap_nhat)
    VALUES ($1, $2, $3, $4, $5, $6, $7, now())
    ON CONFLICT (account) DO UPDATE SET
        mat_khau_hash = EXCLUDED.mat_khau_hash,
        role          = EXCLUDED.role,
        group_name    = EXCLUDED.group_name,
        khong_gian    = EXCLUDED.khong_gian,
        demo          = EXCLUDED.demo,
        admin         = EXCLUDED.admin,
        cap_nhat      = now()
"""

_SQL_MOT_TAI_KHOAN = """
    SELECT account, mat_khau_hash, role, group_name, khong_gian, demo, admin
    FROM users
    WHERE account = $1
"""


@dataclass(frozen=True)
class DongUser:
    """Một dòng `users` đọc lên; hình dạng mà `api/xac_thuc.py` cần và không hơn."""

    account: str
    mat_khau_hash: str
    role: str
    group_name: str
    khong_gian: str
    demo: bool
    admin: bool


class KhoTaiKhoan:
    """Bảng `users` trên một pool asyncpg; sở hữu pool nó mở."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def mo(cls, cau_hinh: Mapping | None = None) -> "KhoTaiKhoan":
        """Mở pool từ cấu hình (mặc định đọc môi trường)."""
        cau_hinh = (
            cau_hinh_postgres_tu_moi_truong() if cau_hinh is None else dict(cau_hinh)
        )
        pool = await asyncpg.create_pool(min_size=1, max_size=4, **cau_hinh)
        return cls(pool)

    async def khoi_tao(self) -> None:
        """Chạy DDL idempotent; gọi mỗi lần tiến trình lên, lặp lại không đổi gì."""
        ddl = DUONG_DAN_DDL.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            await conn.execute(ddl)

    async def dong_bo(self, cac_muc: Sequence[MucTaiKhoan] | None = None) -> int:
        """Đổ seed xuống bảng, trả số dòng đã ghi.

        Một transaction cho cả seed: nửa danh sách vào bảng còn nửa kia không là
        một hệ mà một phần người dùng đăng nhập được và phần kia thì không, và
        không có gì nói ra chuyện đó.
        """
        cac_muc = nap_tai_khoan() if cac_muc is None else cac_muc
        async with self._pool.acquire() as conn, conn.transaction():
            for m in cac_muc:
                tk = m.tai_khoan
                await conn.execute(
                    _SQL_DONG_BO,
                    tk.tai_khoan,
                    m.mat_khau_hash,
                    tk.danh_tinh.vai,
                    tk.nhom,
                    tk.danh_tinh.khong_gian,
                    tk.demo,
                    tk.admin,
                )
        return len(cac_muc)

    async def tra(self, account: str) -> DongUser | None:
        """Một dòng `users`, `None` khi không có tài khoản đó.

        `None` chứ không phải một exception: nơi gọi là đường đăng nhập, và ở đó
        "không có tài khoản" phải chạy tiếp qua đúng một phép bcrypt trên hash
        giả rồi trả về cùng một mã lỗi với ca sai mật khẩu. Nổ ở đây là dựng lại
        đúng kênh dò mà `DANG_NHAP_SAI` sinh ra để bịt.
        """
        async with self._pool.acquire() as conn:
            dong = await conn.fetchrow(_SQL_MOT_TAI_KHOAN, account)
        if dong is None:
            return None
        return DongUser(
            account=dong["account"],
            mat_khau_hash=dong["mat_khau_hash"],
            role=dong["role"],
            group_name=dong["group_name"],
            khong_gian=dong["khong_gian"],
            demo=bool(dong["demo"]),
            admin=bool(dong["admin"]),
        )

    async def dong(self) -> None:
        await self._pool.close()
