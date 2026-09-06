"""Endpoint đồ thị theo quyền: token -> ngữ cảnh quyền -> engine -> envelope AD-8 (story 3.7).

`POST /do-thi` nhận danh sách id hyperedge của một lượt (thường là
`citations[].id` của một lượt `/hoi-dap` trước đó) và trả **cùng envelope** với
`/hoi-dap`: `answer: null`, `refused: false`, `citations: []`, `graph` có nội
dung, `meta` ba trường. Drawer đồ thị của Epic 4 (FR-19) vẽ từ đúng `graph`
này; hover một trích dẫn làm sáng hyperedge cùng `id`.

Ba luật của module, cả ba là cơ chế.

**Server lọc lại toàn bộ, `api/` chỉ chuyển kiểu.** Đỉnh nào thấy được, tên
nào phải che, hyperedge nào vắng mặt đều quyết ở `Neo4jACLGraphStorage.do_thi_cua`
(ba mệnh đề lọc chặt, mỗi dòng qua `_che`) và ở hàm thuần
`adapters.do_thi.dung_do_thi`. Module này không nhập một tên nào của
`core.masking` và không dựng đồ thị từ `citations`: nếu client (hay `api/`) tự
dựng thì client là người quyết đỉnh nào ngoài quyền, đúng thứ AD-8 và AD-9
cấm. Id không tồn tại, id L0 và id khác space cho **cùng một kết quả** là vắng
mặt, không lỗi, không 404 - một mã riêng cho id không tồn tại là cách phân
biệt "không có" với "không được thấy".

**Không dựng ngữ cảnh quyền ở đây.** `api/hoi_dap.py` là module `api/` duy nhất
được dựng `PermissionContext` (`tests/test_api_khong_cham_tang_che.py` canh);
module này gọi `api.hoi_dap.ngu_canh_cua_claim` rồi `use_context` bọc **trọn**
lời gọi engine. Bảng chính sách là object đọc **một lần** ở tuyến (`api/main.py`)
và truyền xuống, không phải kho chính sách.

**Không lời gọi LLM, không embedding, không hàng audit mới.** Đường này chỉ
chạm kho graph. Mọi hyperedge trả ra đều đã nằm trong `hyperedge_ids` của hàng
`query` sinh ra lượt ấy và cửa quyền là cùng ba mệnh đề, nên endpoint không mở
thêm một mức đọc nào; một hằng `event` mới là Ask First (ADR-018).
"""

import logging

from pydantic import BaseModel, ConfigDict

from adapters.engine import EngineACL
from adapters.trich_dan import TrichDanNgoaiQuyen
from api.hoi_dap import (
    MA_DANH_SACH_ID_QUA_DAI,
    MA_THAN_YEU_CAU_LA,
    MA_TRICH_DAN_NGOAI_QUYEN,
    SO_ID_TOI_DA,
    THONG_DIEP_THAN_DO_THI,
    THONG_DIEP_TRICH_DAN,
    LoiHoiDap,
    dict_do_thi,
    dung_envelope,
    dung_meta,
    loi_truy_hoi,
    ngu_canh_cua_claim,
)
from api.xac_thuc import ClaimNguoiHoi
from core.permission import PermissionContextMissing, use_context
from core.policy import Policy

logger = logging.getLogger(__name__)


class ThanDoThi(BaseModel):
    """Thân của `POST /do-thi`: **đúng một** trường, một danh sách chuỗi.

    `extra="forbid"` cùng lý do với `ThanHoiDap`: `role`, `space`, `policy` hay
    một cờ "mở rộng lân cận" trong thân đều là thứ quyết định người gọi thấy gì,
    và cả bốn phải đến từ token hoặc từ hằng của server. Mục không phải chuỗi
    là `RequestValidationError` (400 `THAN_YEU_CAU_LA` qua handler chung);
    độ dài và chuỗi rỗng kiểm ở `kiem_danh_sach_id` để có mã riêng.
    """

    model_config = ConfigDict(extra="forbid")

    hyperedge_ids: list[str]


def kiem_danh_sach_id(hyperedge_ids: list[str]) -> list[str]:
    """Danh sách id đã khử trùng, giữ thứ tự; quá dài hay có mục rỗng là 400.

    Đo độ dài trên danh sách **chưa khử trùng**: đó là thứ đi qua đường mạng.
    Mục rỗng (hay toàn khoảng trắng) là thân sai chứ không phải một id vắng
    mặt: `normalize_id` của adapter sẽ từ chối nó bằng `ValueError`, và một
    `ValueError` từ kho lên tới HTTP là một 500 không tên cho một lỗi của người
    gọi. Khử trùng ở đây chỉ là bước rẻ trên chuỗi thô; adapter chuẩn hóa
    (`normalize_id`) và khử trùng lần nữa trên dạng chuẩn.
    """
    if not isinstance(hyperedge_ids, list):
        raise LoiHoiDap(400, MA_THAN_YEU_CAU_LA, THONG_DIEP_THAN_DO_THI)
    if len(hyperedge_ids) > SO_ID_TOI_DA:
        raise LoiHoiDap(
            400,
            MA_DANH_SACH_ID_QUA_DAI,
            f"danh sách có {len(hyperedge_ids)} id, tối đa {SO_ID_TOI_DA}",
        )
    ra: list[str] = []
    for i in hyperedge_ids:
        if not isinstance(i, str) or not i.strip():
            raise LoiHoiDap(400, MA_THAN_YEU_CAU_LA, THONG_DIEP_THAN_DO_THI)
        if i not in ra:
            ra.append(i)
    return ra


async def lay_do_thi(
    hyperedge_ids: list[str],
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    engine: EngineACL,
) -> dict:
    """Một lượt lấy đồ thị: kiểm đầu vào, dựng ngữ cảnh một lần, đọc kho, trả envelope.

    Thứ tự cố định như `tra_loi`: kiểm đầu vào **trước** khi dựng ngữ cảnh (một
    danh sách quá dài không đáng một phép tra bảng chính sách), dựng ngữ cảnh
    **trước** khi chạm engine (vai lạ là 403 mà không chạm kho), và
    `use_context` bọc trọn `engine.do_thi`. Không `request_id`: đường này không
    ghi hàng audit nào, nên không có gì để nối.

    Ánh xạ lỗi dùng lại đúng bốn nhánh của `api.hoi_dap.loi_truy_hoi`, để một
    Neo4j rớt ra 503 `KHO_KHONG_SAN_SANG` ở cả hai tuyến. `TrichDanNgoaiQuyen`
    (và lớp con `DoThiNgoaiQuyen`) là 500 mang mã, cùng mã với citation: nó chỉ
    xảy ra khi dữ liệu kho hỏng hay đường này bị gọi dưới ngữ cảnh hệ thống,
    hai ca không có ở vận hành bình thường.
    """
    ids = kiem_danh_sach_id(hyperedge_ids)
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    try:
        with use_context(ngu_canh):
            do_thi = await engine.do_thi(ids)
    except PermissionContextMissing:
        raise LoiHoiDap(
            500, PermissionContextMissing.code, "thiếu ngữ cảnh quyền cho lời gọi này"
        ) from None
    except TrichDanNgoaiQuyen as loi:
        # Dữ liệu kho hỏng hay đường này bị gọi dưới ngữ cảnh hệ thống: 500 mang
        # mã, chi tiết chỉ vào log - thân lỗi không kể ra id hay tên nào.
        logger.warning("đồ thị ngoài quyền: %s", loi)
        raise LoiHoiDap(500, MA_TRICH_DAN_NGOAI_QUYEN, THONG_DIEP_TRICH_DAN) from None
    except Exception as loi:
        da_biet = loi_truy_hoi(loi)
        if da_biet is None:
            raise
        logger.warning("đọc đồ thị hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None
    return dung_envelope(
        answer=None,
        refused=False,
        citations=[],
        graph=dict_do_thi(do_thi),
        meta=dung_meta(ngu_canh),
    )


__all__ = ["ThanDoThi", "kiem_danh_sach_id", "lay_do_thi"]
