---
scope: noi_bo
content_type: sop
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# SOP: quy trình thay đổi cấu hình hạ tầng

## Phạm vi
Mọi thay đổi chạm tới máy chủ sản xuất, cấu hình mạng, quy tắc tường lửa, WAF, load balancer
và cơ sở dữ liệu.

## Phân loại thay đổi
| Loại | Ví dụ | Phê duyệt | Cửa sổ |
|---|---|---|---|
| Thường | thêm quy tắc theo dõi, đổi ngưỡng cảnh báo | trưởng nhóm | giờ hành chính |
| Có rủi ro | đổi quy tắc tường lửa, nâng phiên bản dịch vụ | trưởng bộ phận | 22:00 tới 02:00 |
| Khẩn | vá lỗ hổng, khắc phục sự cố đang diễn ra | phê duyệt sau | bất kỳ lúc nào |

## Nội dung phiếu thay đổi
1. Mô tả thay đổi và lý do.
2. Hệ thống bị ảnh hưởng và người dùng bị ảnh hưởng.
3. Các bước thực hiện, viết đủ để người khác làm theo được.
4. Cách kiểm tra sau khi làm.
5. Đường lùi và thời gian cần để lùi.
6. Người thực hiện và người giám sát.

## Sau khi thực hiện
Ghi kết quả vào phiếu trong 24 giờ, gồm thời điểm bắt đầu, thời điểm kết thúc, và có phải lùi
hay không. Phiếu không đóng trong 7 ngày sẽ vào danh sách nhắc hằng tuần.

## Lưu ý
Thay đổi tường lửa và WAF phải kiểm tra lại đường truy cập của khách hàng ngay sau khi áp dụng.
Danh sách IP ghi nhầm sẽ khiến người dùng hợp lệ mất truy cập, và lỗi này thường chỉ lộ ra khi
khách hàng báo.

Người thực hiện: NV09
