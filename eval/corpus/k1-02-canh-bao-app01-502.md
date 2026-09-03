---
scope: khach_hang_a
content_type: canh_bao
---
Cấu hình cảnh báo cho trang thanh toán App01.
Cảnh báo "App01 tỷ lệ lỗi 502" bắn khi tỷ lệ phản hồi 502 vượt 2% trong cửa sổ 5 phút.
Cảnh báo mức cảnh giác gửi vào kênh chat của nhóm vận hành khách hàng A; cảnh báo mức nghiêm trọng gọi điện cho kỹ sư trực.
Cảnh báo "App01 lưu lượng cao" bắn khi lưu lượng vượt 5000 req/phút trong 10 phút liên tục.
Cảnh báo bị tắt tiếng tối đa 60 phút và chỉ trưởng nhóm vận hành được tắt tiếng.
Hệ giám sát lấy số liệu từ Nginx mỗi 30 giây và giữ lịch sử cảnh báo 180 ngày.
