"""Luật thuần của break-glass (FR-20, story 5.1 và 5.2): trạng thái, hằng, phép chuyển, ba bộ lọc vùng cấp.

Ở `core/` vì đây là luật mà ba story của Epic 5 dùng chung (xin ở 5.1, duyệt
và từ chối ở 5.2, đường phụ ở 5.3) và vì nó không biết gì về kho: bảng
`breakglass_requests` sống ở Postgres (`api/break_glass.py`), còn chỗ này chỉ
nói một yêu cầu có những trạng thái nào, từ trạng thái nào thì hủy hay xử lý
được, và một hyperedge lân cận có được vào vùng cấp hay không.

Hai hằng số của FR-20 khóa cứng ở đây chứ không đến từ thân request hay biến
môi trường: `k = 0` (người xin không được kê thêm hyperedge nào ngoài cái đang
xin) và 60 phút. Nới hai số này là Ask First của spec 5.1 và 5.2.

**Vùng cấp hai pha, biên là biên import (story 5.2).** Pha một ở `adapters/`
trả tập hyperedge lân cận thô theo bước hyperedge, đã qua ba mệnh đề lọc quyền
của **vai xin**; pha hai là `loc_vung_cap` ở đây, ba bộ lọc thuần trên bản ghi
năm trường, không chạm kho. Tách hai pha để bộ lọc nào cũng đọc được trước hội
đồng bằng một hàm không phụ thuộc gì, và để đường cấp không thể đi vòng nó:
`api/` chỉ có một hàm để hỏi "vùng cấp là gì".
"""

from dataclasses import dataclass
from typing import Iterable

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
# Mức tiết lộ mà một hyperedge phải có với vai xin để xin được (5.1) và để vào
# vùng cấp (5.2): L0 thì vai không biết nó tồn tại, L2 thì không có gì để mở.
MUC_XIN_DUOC: str = "L1"


def _kiem_trang_thai(trang_thai: str) -> None:
    if trang_thai not in TRANG_THAI:
        raise ValueError(f"trạng thái {trang_thai!r} không có trong {sorted(TRANG_THAI)}")


def huy_duoc(trang_thai: str) -> bool:
    """Người xin hủy được yêu cầu chỉ khi nó còn chờ duyệt.

    Trạng thái ngoài danh mục là lỗi lúc gọi, không phải `False`: một hàng
    mang trạng thái lạ là dữ liệu hỏng, và trả `False` cho nó là biến lỗi ấy
    thành một 409 trông như một ca vận hành.
    """
    _kiem_trang_thai(trang_thai)
    return trang_thai == TRANG_THAI_CHO_DUYET


def xu_ly_duoc(trang_thai: str) -> bool:
    """Owner duyệt hay từ chối được yêu cầu chỉ khi nó còn chờ duyệt (story 5.2).

    Cùng luật với `huy_duoc` và cố ý là một hàm riêng: hai phép chuyển của hai
    tác nhân khác nhau, hôm nay trùng điều kiện, mai một trong hai đổi (ví dụ
    cho phép duyệt lại một yêu cầu đã từ chối) thì chỗ đổi có tên.
    """
    _kiem_trang_thai(trang_thai)
    return trang_thai == TRANG_THAI_CHO_DUYET


@dataclass(frozen=True)
class UngVienVung:
    """Một hyperedge ứng viên của vùng cấp, năm trường và không hơn.

    `level` là mức tiết lộ của **vai xin** với hyperedge này (không phải của
    owner), `nhom` là nhóm phụ trách của loại nội dung (`None` khi bảng nhóm
    chưa khai). Không có giá trị slot hay tên entity: bộ lọc không cần và
    `core/` không được cầm nội dung.
    """

    id: str
    scope: str
    content_type: str
    level: str
    nhom: str | None


def loc_vung_cap(
    goc: UngVienVung,
    ung_vien: Iterable[UngVienVung],
    *,
    muc_xin_duoc: str = MUC_XIN_DUOC,
) -> tuple[str, ...]:
    """Ba bộ lọc của vùng cấp: cùng scope gốc, vai xin thấy ở L1, cùng nhóm phụ trách.

    Gốc cũng phải qua bộ lọc (b): một gốc không còn L1 với vai xin (bảng chính
    sách đã hoán) cho vùng **rỗng**, và vùng rỗng là thao tác thất bại ở tầng
    trên, không phải một grant không có gì. Gốc không có nhóm phụ trách cũng là
    vùng rỗng: không có nhóm thì không có owner nào để cấp.

    Kết quả là dãy id, gốc đứng đầu, còn lại theo thứ tự id, mỗi id một lần.
    Viết cho k tổng quát: ứng viên là hợp của mọi bước lân cận, hàm không biết
    và không cần biết chúng cách gốc bao nhiêu bước.
    """
    if goc.level != muc_xin_duoc or goc.nhom is None:
        return ()
    con_lai: set[str] = set()
    for uv in ung_vien:
        if uv.id == goc.id:
            continue
        if uv.scope != goc.scope:
            continue
        if uv.level != muc_xin_duoc:
            continue
        if uv.nhom != goc.nhom:
            continue
        con_lai.add(uv.id)
    return (goc.id, *sorted(con_lai))
