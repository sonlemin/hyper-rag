"""Cờ chế độ đo và sự kiện khởi động của tiến trình phục vụ (story 3.6, ADR-017).

Hai thứ, cả hai thuộc **vòng đời** chứ không thuộc một request, và cả hai sống ở
module riêng vì `api/main.py` không nhận hàm cấp module mới mà không khai lý do
(`tests/test_api_khong_cham_tang_che.py::HAM_MAIN_CO_LY_DO`).

**Cờ chế độ đo là biến môi trường của tiến trình**, không phải endpoint. Ba lý
do. AD-6 đã chốt công tắc đo namespace là biến môi trường của tiến trình đo và
trạng thái ghi vào audit; cờ này cùng loại. Một cờ lật lúc chạy là trạng thái
ứng dụng ngoài Postgres (AD-7). Và cửa sổ T7 chạy trên bản khôi phục từ snapshot
bằng một tiến trình riêng (7.5), nên "bật" đúng nghĩa là "tiến trình này sinh ra
để đo" - một cửa sổ đo mà admin lật giữa chừng là một mẫu số không ai đếm được.
Đọc **đúng một lần** ở lifespan, ngay sau khi bảng chính sách nạp xong và
trước khi mở bất kỳ kết nối nào; chỉ nhận `0`/`1`, giá trị khác là chết ở giây
đầu, cùng chỗ với một `HYPER_RAG_POLICY_ID` gõ sai (policy nổ trước, cờ nổ sau).

Cờ bật đổi đúng một thứ: hàng `refusal` ghi tầng **mutation** qua `ghi_bien_doi`
(`api/hoi_dap.py::_ghi_audit_tu_choi`), ghi hỏng là 500 `AUDIT_GHI_HONG`. Hai cột
của Đo 2 (PRD 5.2) đếm trên chính hàng đó, và một hàng được phép mất trong cửa
sổ đo là một mẫu số harness không tin được. Thân response không đổi một byte
theo cờ (AD-8).

**Sự kiện `startup`** ghi tầng mutation, **sau** khi audit mở và **trước** khi
engine dựng: bảng chính sách nào đang chạy (cả id lẫn `policy_version` đầy đủ,
thứ mà `logger.info` cắt 12 ký tự không join được với cột `policy_version`) và
cờ chế độ đo. `space` là `SPACE_TIEN_TRINH`: nó thuộc tiến trình, không thuộc
space nào. Ghi hỏng thì tiến trình không lên - không có mốc thì cửa sổ đo không
có điểm bắt đầu.
"""

import os
from typing import Mapping

from api.chinh_sach import KhoChinhSach
from core.audit import (
    EVENT_STARTUP,
    SPACE_TIEN_TRINH,
    TIER_MUTATION,
    AuditPort,
    SuKienAudit,
    ghi_bien_doi,
    thoi_diem_utc,
)

# Biến môi trường của cờ. **Không phải secret**, sống ở `.env.server`/`.env.laptop`.
BIEN_CHE_DO_DO: str = "HYPER_RAG_CHE_DO_DO"

MA_CHE_DO_DO_KHONG_HOP_LE: str = "CHE_DO_DO_KHONG_HOP_LE"

# Ba khóa `chi_tiet` của sự kiện `startup`. Hằng vì harness Đo 2/Đo 3 đọc đúng
# tên này để tìm mốc của một cửa sổ đo.
CT_POLICY_ID: str = "policy_id"
CT_POLICY_VERSION: str = "policy_version"
CT_CHE_DO_DO: str = "che_do_do"

# Hai giá trị duy nhất cờ nhận. Không nhận `yes`/`true`/`on`: một cờ đo phải
# đọc được không cần đoán, và một giá trị lạ là một cấu hình gõ sai chứ không
# phải một cách nói khác của "bật".
GIA_TRI_TAT: str = "0"
GIA_TRI_BAT: str = "1"


class CheDoDoKhongHopLe(ValueError):
    """`HYPER_RAG_CHE_DO_DO` mang giá trị ngoài `0`/`1`; tiến trình chết ở giây đầu."""

    code = MA_CHE_DO_DO_KHONG_HOP_LE


def doc_che_do_do(moi_truong: Mapping[str, str] | None = None) -> bool:
    """Cờ chế độ đo từ môi trường: vắng hay rỗng là tắt, `0` tắt, `1` bật.

    Hàm thuần trên một map chuỗi, cùng hình dạng với `api.chinh_sach.
    ma_policy_mac_dinh` để bộ test truyền map vào. Mặc định tắt vì một tiến
    trình không ai khai cờ phải chạy như 3.5, không phải như một cửa sổ đo.
    """
    nguon = os.environ if moi_truong is None else moi_truong
    gia_tri = nguon.get(BIEN_CHE_DO_DO)
    gon = gia_tri.strip() if isinstance(gia_tri, str) else ""
    if gon in ("", GIA_TRI_TAT):
        return False
    if gon == GIA_TRI_BAT:
        return True
    raise CheDoDoKhongHopLe(
        f"{BIEN_CHE_DO_DO} chỉ nhận {GIA_TRI_TAT!r} hoặc {GIA_TRI_BAT!r}, nhận được {gia_tri!r}"
    )


def su_kien_startup(kho: KhoChinhSach, che_do_do: bool) -> SuKienAudit:
    """Hàng `startup`, tầng mutation, dựng từ **một** phép đọc nguyên tử của kho."""
    ma, policy = kho.ma_va_policy()
    return SuKienAudit(
        tier=TIER_MUTATION,
        event=EVENT_STARTUP,
        space=SPACE_TIEN_TRINH,
        policy_version=policy.policy_version,
        thoi_diem=thoi_diem_utc(),
        chi_tiet={
            CT_POLICY_ID: ma,
            CT_POLICY_VERSION: policy.policy_version,
            CT_CHE_DO_DO: che_do_do,
        },
    )


async def ghi_startup(audit: AuditPort, kho: KhoChinhSach, che_do_do: bool) -> None:
    """Ghi hàng `startup`; lỗi của port dội thẳng lên lifespan (tầng mutation)."""
    await ghi_bien_doi(audit, su_kien_startup(kho, che_do_do))
