---
scope: khach_hang_a
content_type: canh_bao
---
Cấu hình cảnh báo tải CPU trên cụm máy chủ web của khách hàng A.
Cảnh báo "CPU cao" mức cảnh giác bắn khi tải CPU trung bình vượt 70% trong 15 phút liên tục.
Cảnh báo mức nghiêm trọng bắn khi tải CPU vượt 90% trong 5 phút liên tục và gửi vào kênh trực của nhóm vận hành khách hàng A.
Cảnh báo CPU không gọi điện cho kỹ sư trực, khác với cảnh báo tỷ lệ lỗi của trang thanh toán.
Ngưỡng CPU được nới lên 85% trong hai ngày cuối tháng vì đó là cao điểm đối soát của khách hàng A.
Lịch sử cảnh báo CPU giữ 90 ngày, ngắn hơn lịch sử cảnh báo lỗi ứng dụng.
