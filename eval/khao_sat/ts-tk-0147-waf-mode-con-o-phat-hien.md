---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2609-0147: rule WAF đã tạo nhưng không chặn

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang03.example |
| Dịch vụ | WAF |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV22 |
| Mở lúc | 27/09/2026 14:20 |
| Đóng lúc | 27/09/2026 15:05 |

## Mô tả từ khách hàng
Khách đã tạo Custom Rule chặn các IP ngoài danh sách cho phép, nhưng thử từ máy ngoài danh sách
vẫn truy cập được bình thường.

## Kiểm tra của kỹ thuật
Rule tồn tại và cấu hình đúng. Xem mục Cấu hình cơ bản thấy WAF Mode đang ở Phát hiện.

## Nguyên nhân
Ở chế độ Phát hiện, hệ thống chỉ ghi log, không chặn lưu lượng. Rule chỉ có hiệu lực khi WAF Mode
ở Ngăn chặn.

## Xử lý
1. Hướng dẫn khách chuyển WAF Mode sang Ngăn chặn.
2. Kiểm tra lại từ máy ngoài whitelist, nhận 403 đúng như mong đợi.
3. Kiểm tra từ máy trong whitelist, truy cập bình thường.

## Ghi chú nội bộ
Đây là ticket thứ tư trong quý về cùng một hiểu nhầm. Đề xuất bổ sung cảnh báo trên giao diện khi
người dùng tạo rule Deny trong lúc WAF Mode đang ở Phát hiện.
