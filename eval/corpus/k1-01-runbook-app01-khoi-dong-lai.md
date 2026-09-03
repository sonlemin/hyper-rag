---
scope: khach_hang_a
content_type: runbook
---
Runbook vận hành App01 của khách hàng A.
App01 chạy Nginx và PHP-FPM trên máy chủ web01, phục vụ trang thanh toán của khách hàng A.
Khi lưu lượng vượt 5000 req/phút, kỹ sư trực phải mở thêm hai tiến trình PHP-FPM và theo dõi thời gian đáp ứng trong 15 phút tiếp theo.
Khi trang thanh toán trả lỗi 502 quá 3 phút liên tục, người trực được khởi động lại dịch vụ PHP-FPM trước, không khởi động lại Nginx.
Mọi lần chỉnh tham số giới hạn bộ nhớ PHP-FPM phải có phiếu thay đổi theo SOP-12, kể cả khi đang xử lý sự cố.
Sau khi khởi động lại, người trực ghi thao tác vào nhật ký sự cố của khách hàng A trong vòng 24 giờ.
