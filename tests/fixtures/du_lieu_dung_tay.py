"""Dữ liệu hyperedge dựng tay tiếng Việt cho bộ test Đo 1 nền (story 1.2).

Neo vào ví dụ xuyên suốt App01 của PRD addendum: một runbook công khai và một
báo cáo sự cố hạn chế, cộng một hyperedge bí mật hạ tầng để `masked_slots` được
kiểm trên nhiều hơn một hàng của bảng chính sách.

Hai ca biên cố ý có mặt từ đầu. HE-04 mang scope khác (`khach_hang_a`) để nửa
trái của khóa lọc được kiểm thật, không chỉ nửa phải: tech_support không chạm
scope này dù cùng loại nội dung với HE-02 mà nó thấy - đó là biên cách ly
khách hàng của RT-01. HE-04 cũng không có slot `owner`, để luật owner của AD-9
được kiểm trên ca thiếu slot chứ không chỉ ca đủ slot.

Mỗi hyperedge mang đủ ba thứ mà tầng quyền cần: nhãn `scope`, nhãn
`content_type` (hai thành phần của khóa lọc, AD-4) và các vai slot. Không đặt
sẵn mức tiết lộ lên dữ liệu - mức do bảng chính sách tính lúc truy vấn (FR-09).

Story 1.3-1.7 nạp chính bộ này vào Qdrant/Neo4j; ở story 1.2 nó chỉ là đầu vào
thuần cho oracle và cho test dựng ngữ cảnh quyền.
"""

from types import MappingProxyType

# Ba hyperedge, ba loại nội dung. Chỉ khai các slot có nội dung thật; slot vắng
# mặt nghĩa là fact này không có vai đó, không phải "bị che".
HYPEREDGES: tuple[MappingProxyType, ...] = (
    MappingProxyType(
        {
            "id": "HE-01",
            "scope": "noi_bo",
            "content_type": "runbook",
            "slots": MappingProxyType(
                {
                    "subject": "App01",
                    "condition": "traffic vượt 5000 request mỗi phút",
                    "remediation": "làm theo SOP-12: khởi động lại pool PHP-FPM",
                    "source": "SOP-12 runbook vận hành App01",
                    "owner": "Nguyễn Văn Minh",
                }
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "HE-02",
            "scope": "noi_bo",
            "content_type": "bao_cao_su_co",
            "slots": MappingProxyType(
                {
                    "subject": "App01",
                    "symptom": "trang thanh toán trả lỗi 502 trong 40 phút",
                    "cause": "chỉnh sai giới hạn bộ nhớ PHP-FPM",
                    "time": "2026-08-12T09:20:00Z",
                    "remediation": "trả giới hạn bộ nhớ về mức cũ rồi nạp lại cấu hình",
                    "source": "báo cáo sự cố INC-1208 (hạn chế)",
                    "owner": "Trần Thị Hạnh",
                }
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "HE-03",
            "scope": "noi_bo",
            "content_type": "bi_mat_ha_tang",
            "slots": MappingProxyType(
                {
                    "subject": "cụm máy chủ thanh toán",
                    "condition": "truy cập quản trị chỉ từ dải VPN nội bộ",
                    "source": "sổ tay hạ tầng, mục khóa quản trị",
                    "remediation": "xoay khóa quản trị mỗi quý theo lịch",
                    "owner": "Lê Quốc Bảo",
                }
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "HE-04",
            "scope": "khach_hang_a",
            "content_type": "bao_cao_su_co",
            "slots": MappingProxyType(
                {
                    "subject": "cổng thanh toán của khách hàng A",
                    "symptom": "giao dịch treo ở bước xác thực",
                    "cause": "chứng chỉ ký giao dịch hết hạn",
                    "time": "2026-08-19T02:05:00Z",
                    "source": "biên bản làm việc với khách hàng A",
                }
            ),
        }
    ),
)

# Tra nhanh theo id, để test khỏi lặp vòng lặp tìm kiếm.
THEO_ID: MappingProxyType = MappingProxyType({he["id"]: he for he in HYPEREDGES})
