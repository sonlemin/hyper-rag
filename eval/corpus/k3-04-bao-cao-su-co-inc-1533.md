---
scope: khach_hang_b
content_type: bao_cao_su_co
---
Báo cáo sự cố INC-1533 (tài liệu hạn chế).
Ngày 26/08, cổng thanh toán của khách hàng B ngừng nhận giao dịch trong 2 giờ 10 phút kể từ 00 giờ 01.
Nguyên nhân là chứng thư số của tên miền pay.khachhangb.vn hết hạn lúc nửa đêm mà không ai gia hạn.
Triệu chứng ghi nhận là trình duyệt và ứng dụng đối tác đều báo lỗi chứng thư không hợp lệ, trong khi máy chủ và cơ sở dữ liệu đều bình thường.
Cảnh báo hết hạn đã bắn từ ngày 27/07 nhưng gửi tới hộp thư của nhóm Tích hợp cũ, nhóm này đã bàn giao tên miền cho nhóm vận hành khách hàng B từ ngày 01/08.
Kỹ sư Phạm Quốc Bảo cấp chứng thư mới và nạp lại cấu hình Nginx, dịch vụ phục hồi lúc 02 giờ 11 cùng ngày.
