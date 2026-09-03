---
scope: khach_hang_b
content_type: postmortem
---
Postmortem sự cố INC-1533 về chứng thư số của khách hàng B (tài liệu hạn chế).
Nguyên nhân gốc không phải kỹ thuật: đợt bàn giao ngày 01/08 chuyển tên miền pay.khachhangb.vn sang nhóm vận hành khách hàng B mà không cập nhật hộp thư nhận cảnh báo trong bản ghi CMDB.
Ba lượt cảnh báo trước 30 ngày, 14 ngày và 7 ngày đều bắn đúng lịch và đều rơi vào một hộp thư không còn ai đọc.
Thiệt hại là 2 giờ 10 phút gián đoạn vào đầu tháng, vượt cam kết thời gian sẵn sàng 99,5% của tháng 08.
Hành động khắc phục thứ nhất là rà toàn bộ tên miền của khách hàng B, đối chiếu nhóm sở hữu với hộp thư nhận nhắc, hạn hoàn thành 05/09, do trưởng nhóm vận hành khách hàng B chịu trách nhiệm.
Hành động thứ hai là thêm bước kiểm hộp thư nhận cảnh báo vào danh mục bàn giao tài sản, hạn hoàn thành 20/09.
