---
scope: khach_hang_a
content_type: known_issue
---
Lỗi đã biết KI-021 về báo cáo tháng của khách hàng A chạy chậm.
Báo cáo doanh thu tháng của khách hàng A chạy quá 20 phút khi khoảng thời gian chọn vượt 90 ngày, do truy vấn quét toàn bảng đơn hàng.
Lỗi chỉ xuất hiện trên màn quản trị đơn hàng, không ảnh hưởng trang thanh toán và không ảnh hưởng giao dịch đang chạy.
Cách vòng tránh là chia báo cáo thành từng tháng rồi cộng lại, hoặc đặt lịch chạy báo cáo vào ban đêm.
Bản vá tối ưu truy vấn đã lên kế hoạch cho đợt phát hành tháng sau, chưa có ngày cụ thể.
Lỗi được xếp mức thấp vì có cách vòng tránh và chỉ ảnh hưởng ba người dùng nội bộ của khách hàng A.
