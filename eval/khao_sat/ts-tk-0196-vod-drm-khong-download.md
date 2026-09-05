---
scope: khach_hang_b
content_type: vong_doi_ticket
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0196: không tải xuống được video đã mã hóa DRM

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang13.example |
| Dịch vụ | VOD |
| Mức ưu tiên | Thấp |
| Người tiếp nhận | NV23 |
| Mở lúc | 21/08/2026 15:10 |
| Đóng lúc | 21/08/2026 15:35 |

## Mô tả từ khách hàng
Khách muốn tải bản gốc của một số video đã mã hóa về máy, nhưng nút tải trên bảng điều khiển không
hoạt động và công cụ trên trình duyệt cũng không lấy được.

## Nguyên nhân
Video đã mã hóa bảo vệ nội dung không tải trực tiếp từ bảng điều khiển hoặc công cụ trình duyệt được.
Đó là mục đích của lớp bảo vệ.

## Xử lý
1. Hướng dẫn khách dùng API quản lý tệp để tải.
2. Phần khóa x-key phải gửi phiếu để bộ phận hỗ trợ cấp riêng, không tự lấy trên giao diện.
3. Khách tải thành công sau khi nhận khóa.

## Ghi chú nội bộ
Khóa x-key cấp theo tài khoản và không hết hạn. Đã đề xuất bổ sung cơ chế thu hồi khóa, vì hiện tại
khóa lộ ra là không có đường vô hiệu.
