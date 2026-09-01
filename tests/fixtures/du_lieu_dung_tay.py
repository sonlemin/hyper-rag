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
thuần cho oracle và cho test dựng ngữ cảnh quyền. Story 1.5 thêm chunk và tài
liệu gốc dẫn xuất từ đúng 4 hyperedge này, ở cuối file.
"""

from types import MappingProxyType

# Ba hyperedge, ba loại nội dung. Chỉ khai các slot có nội dung thật; slot vắng
# mặt nghĩa là fact này không có vai đó, không phải "bị che".
#
# `source_id` là tên trường của chính upstream (`operate.py:134-253` ghi nó lên
# node hyperedge, `operate.py:843` và `:1073` đọc nó ra để lấy chunk). Đó là
# đường mà một vai thấy hyperedge ở mức L1 dùng để với tới nguyên văn chunk,
# nên quan hệ hyperedge -> chunk phải có thật trong fixture chứ không nằm ở
# quy ước đặt tên id. Upstream nối nhiều chunk id bằng `GRAPH_FIELD_SEP`; ở
# đây mỗi hyperedge cắt ra từ đúng một chunk nên trường này là một id trần.
HYPEREDGES: tuple[MappingProxyType, ...] = (
    MappingProxyType(
        {
            "id": "HE-01",
            "source_id": "chunk-HE-01",
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
            "source_id": "chunk-HE-02",
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
            "source_id": "chunk-HE-03",
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
            "source_id": "chunk-HE-04",
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


# Chunk và tài liệu gốc dẫn xuất từ đúng 4 hyperedge ở trên (story 1.5).
#
# Cổng KV của upstream đọc chunk theo `source_id` của entity và hyperedge, nên
# nội dung chunk phải là nguyên văn của chính fact đã dựng ra hyperedge tương
# ứng. Mỗi chunk mang lại `scope` và `content_type` của nguồn nó: khóa quyền
# của chunk là khóa của tài liệu cắt ra nó, không phải một nhãn thứ hai.
#
# Bộ này cho đúng ca trộn quyền mà story 1.5 cần. Với `tech_support`, chunk của
# HE-01 (runbook, L2) đọc được còn chunk của HE-02 (báo cáo sự cố, L1) thì
# không - vai thấy hyperedge HE-02 ở mức L1 mà vẫn không được nguyên văn của
# nó, đúng luật chunk-chỉ-L2 (NFR-06). Với `devops` thì chunk HE-02 đọc được,
# nên cùng một id chunk cho hai kết quả khác nhau theo vai.
TAI_LIEU_GOC: tuple[MappingProxyType, ...] = (
    MappingProxyType(
        {
            "id": "doc-sop12",
            "scope": "noi_bo",
            "content_type": "runbook",
            "content": (
                "SOP-12 runbook vận hành App01. Khi traffic vượt 5000 request"
                " mỗi phút, khởi động lại pool PHP-FPM theo các bước trong mục"
                " 3. Người phụ trách: Nguyễn Văn Minh."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "doc-inc-1208",
            "scope": "noi_bo",
            "content_type": "bao_cao_su_co",
            "content": (
                "Báo cáo sự cố INC-1208 (hạn chế). Trang thanh toán của App01"
                " trả lỗi 502 trong 40 phút ngày 12/08/2026 do chỉnh sai giới"
                " hạn bộ nhớ PHP-FPM. Trần Thị Hạnh trả giới hạn về mức cũ rồi"
                " nạp lại cấu hình."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "doc-so-tay-ha-tang",
            "scope": "noi_bo",
            "content_type": "bi_mat_ha_tang",
            "content": (
                "Sổ tay hạ tầng, mục khóa quản trị. Cụm máy chủ thanh toán chỉ"
                " nhận truy cập quản trị từ dải VPN nội bộ; khóa quản trị xoay"
                " mỗi quý theo lịch. Người giữ khóa: Lê Quốc Bảo."
            ),
        }
    ),
    # Nửa `scope` của khóa, một mình nó quyết định. `runbook` là L2 với cả hai
    # vai, nên nếu đường KV chỉ kiểm `content_type` thì tech_support vẫn đọc
    # được tài liệu này - trong khi `khach_hang_a` không nằm trong `scopes` của
    # nó. Đây là biên cách ly khách hàng RT-01 chiếu lên đường chunk.
    MappingProxyType(
        {
            "id": "doc-runbook-khach-hang-a",
            "scope": "khach_hang_a",
            "content_type": "runbook",
            "content": (
                "Runbook vận hành riêng cho khách hàng A. Khi cổng thanh toán"
                " báo hàng đợi đầy, giãn nhịp gọi API rồi mở lại theo mục 4."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "doc-khach-hang-a",
            "scope": "khach_hang_a",
            "content_type": "bao_cao_su_co",
            "content": (
                "Biên bản làm việc với khách hàng A. Giao dịch trên cổng thanh"
                " toán treo ở bước xác thực ngày 19/08/2026 vì chứng chỉ ký"
                " giao dịch hết hạn."
            ),
        }
    ),
)

# Một chunk cho mỗi hyperedge, cắt ra từ tài liệu cùng nhãn. `full_doc_id` và
# `tokens` giữ đúng hình dạng `TextChunkSchema` của upstream (`base.py:8`) để
# adapter KV được kiểm trên bản ghi thật chứ không trên dict rút gọn.
CHUNKS: tuple[MappingProxyType, ...] = (
    MappingProxyType(
        {
            "id": "chunk-HE-01",
            "scope": "noi_bo",
            "content_type": "runbook",
            "full_doc_id": "doc-sop12",
            "chunk_order_index": 0,
            "tokens": 48,
            "content": (
                "App01 vượt 5000 request mỗi phút thì làm theo SOP-12: khởi"
                " động lại pool PHP-FPM. Chủ sở hữu quy trình là Nguyễn Văn Minh."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "chunk-HE-02",
            "scope": "noi_bo",
            "content_type": "bao_cao_su_co",
            "full_doc_id": "doc-inc-1208",
            "chunk_order_index": 0,
            "tokens": 56,
            "content": (
                "Trang thanh toán App01 trả lỗi 502 trong 40 phút vì chỉnh sai"
                " giới hạn bộ nhớ PHP-FPM; Trần Thị Hạnh trả giới hạn về mức cũ"
                " rồi nạp lại cấu hình."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "chunk-HE-03",
            "scope": "noi_bo",
            "content_type": "bi_mat_ha_tang",
            "full_doc_id": "doc-so-tay-ha-tang",
            "chunk_order_index": 0,
            "tokens": 44,
            "content": (
                "Cụm máy chủ thanh toán chỉ cho truy cập quản trị từ dải VPN"
                " nội bộ, khóa quản trị xoay mỗi quý. Người giữ khóa là Lê Quốc"
                " Bảo."
            ),
        }
    ),
    # Cặp với `doc-runbook-khach-hang-a`: không có hyperedge nào trong bộ này
    # cắt ra từ nó, vì phía hyperedge đã chốt ở story 1.2 và đường KV không
    # cần nó. Chunk vẫn phải có mặt để nửa `scope` của khóa được kiểm thật.
    MappingProxyType(
        {
            "id": "chunk-KH-A-RUNBOOK",
            "scope": "khach_hang_a",
            "content_type": "runbook",
            "full_doc_id": "doc-runbook-khach-hang-a",
            "chunk_order_index": 0,
            "tokens": 36,
            "content": (
                "Cổng thanh toán của khách hàng A báo hàng đợi đầy thì giãn"
                " nhịp gọi API rồi mở lại theo mục 4 của runbook."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "chunk-HE-04",
            "scope": "khach_hang_a",
            "content_type": "bao_cao_su_co",
            "full_doc_id": "doc-khach-hang-a",
            "chunk_order_index": 0,
            "tokens": 40,
            "content": (
                "Cổng thanh toán của khách hàng A treo giao dịch ở bước xác"
                " thực vì chứng chỉ ký giao dịch hết hạn."
            ),
        }
    ),
)

CHUNK_THEO_ID: MappingProxyType = MappingProxyType({c["id"]: c for c in CHUNKS})

# Chiều ngược của `source_id`, tính ra chứ không chép tay: chunk nào cắt ra từ
# hyperedge nào. Chunk không có hyperedge trong bộ này thì vắng mặt ở đây.
HYPEREDGE_THEO_CHUNK: MappingProxyType = MappingProxyType(
    {he["source_id"]: he for he in HYPEREDGES}
)
TAI_LIEU_THEO_ID: MappingProxyType = MappingProxyType(
    {d["id"]: d for d in TAI_LIEU_GOC}
)
