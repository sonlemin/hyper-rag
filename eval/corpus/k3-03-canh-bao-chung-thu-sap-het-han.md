---
scope: khach_hang_b
content_type: canh_bao
---
Cấu hình cảnh báo hết hạn chứng thư số của khách hàng B.
Cảnh báo "chứng thư sắp hết hạn" bắn khi thời hạn còn dưới 30 ngày và lặp lại mỗi 3 ngày cho tới khi chứng thư được gia hạn.
Cảnh báo mức nghiêm trọng bắn khi thời hạn còn dưới 7 ngày và gọi điện cho kỹ sư trực của nhóm sở hữu tên miền.
Địa chỉ nhận cảnh báo lấy từ trường hộp thư nhóm trong bản ghi CMDB của tên miền, không lấy từ danh sách trực chung.
Cảnh báo cho tên miền pay.khachhangb.vn đã bắn đủ ba lượt từ ngày 27/07 nhưng gửi tới hộp thư của nhóm Tích hợp cũ.
Cảnh báo không tự đóng khi hết hạn: nó chuyển thành cảnh báo "chứng thư đã hết hạn" mức nghiêm trọng và giữ nguyên cho tới khi có chứng thư mới.
