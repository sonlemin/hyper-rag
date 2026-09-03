---
scope: khach_hang_a
content_type: bao_cao_su_co
---
Báo cáo sự cố INC-1208 (tài liệu hạn chế).
Ngày 12/08/2026 lúc 09:20, trang thanh toán App01 của khách hàng A ngừng phục vụ 40 phút, ảnh hưởng trực tiếp nhóm khách VIP đang thanh toán.
Nguyên nhân là chỉnh sai giới hạn bộ nhớ PHP-FPM trong một phiếu thay đổi được duyệt tối hôm trước, làm tiến trình bị hệ điều hành thu hồi hàng loạt khi lưu lượng vượt 5000 req/phút.
Triệu chứng ghi nhận là trang thanh toán trả lỗi 502 với tỷ lệ 100% trong khi Nginx vẫn chạy bình thường.
Kỹ sư trực Trần Thị Hạnh, đội Vận hành ứng dụng, trả giới hạn bộ nhớ PHP-FPM về mức cũ rồi nạp lại cấu hình theo SOP-12, dịch vụ phục hồi lúc 10:00.
Sự cố được xếp mức nghiêm trọng P1 và báo cho quản lý dịch vụ của khách hàng A trong vòng một ngày làm việc.
