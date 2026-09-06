"""Luật thuần của break-glass (FR-20, story 5.1): trạng thái, hằng, phép chuyển.

Ở `core/` vì đây là luật mà ba story của Epic 5 dùng chung (xin ở 5.1, duyệt
và từ chối ở 5.2, đường phụ ở 5.3) và vì nó không biết gì về kho: bảng
`breakglass_requests` sống ở Postgres (`api/break_glass.py`), còn chỗ này chỉ
nói một yêu cầu có những trạng thái nào và từ trạng thái nào thì hủy được.

Hai hằng số của FR-20 khóa cứng ở đây chứ không đến từ thân request hay biến
môi trường: `k = 0` (người xin không được kê thêm hyperedge nào ngoài cái đang
xin) và 60 phút. Nới hai số này là Ask First của spec 5.1.
"""

TRANG_THAI_CHO_DUYET: str = "cho_duyet"
TRANG_THAI_DA_HUY: str = "da_huy"
TRANG_THAI_DA_DUYET: str = "da_duyet"
TRANG_THAI_TU_CHOI: str = "tu_choi"
TRANG_THAI: frozenset[str] = frozenset(
    {TRANG_THAI_CHO_DUYET, TRANG_THAI_DA_HUY, TRANG_THAI_DA_DUYET, TRANG_THAI_TU_CHOI}
)

# Số hyperedge lân cận được kê thêm vào một yêu cầu; 0 nghĩa là đúng một
# hyperedge, cái người xin đang thấy ở mức L1.
K_MAC_DINH: int = 0
# Thời hạn của grant nếu yêu cầu được duyệt (5.2); ghi vào yêu cầu lúc xin để
# người duyệt thấy đúng con số sẽ có hiệu lực.
THOI_HAN_PHUT: int = 60


def huy_duoc(trang_thai: str) -> bool:
    """Người xin hủy được yêu cầu chỉ khi nó còn chờ duyệt.

    Trạng thái ngoài danh mục là lỗi lúc gọi, không phải `False`: một hàng
    mang trạng thái lạ là dữ liệu hỏng, và trả `False` cho nó là biến lỗi ấy
    thành một 409 trông như một ca vận hành.
    """
    if trang_thai not in TRANG_THAI:
        raise ValueError(f"trạng thái {trang_thai!r} không có trong {sorted(TRANG_THAI)}")
    return trang_thai == TRANG_THAI_CHO_DUYET
