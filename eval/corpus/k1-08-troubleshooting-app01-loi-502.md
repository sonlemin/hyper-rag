---
scope: khach_hang_a
content_type: troubleshooting
---
Hướng dẫn tự kiểm tra khi trang thanh toán của khách hàng A trả lỗi 502.
Trang thanh toán chạy trên máy chủ app01.company.vn.
Bước 1: mở trang trạng thái của app01.company.vn và ghi lại mã trả về; lỗi 502 kéo dài quá 3 phút thì báo trực ban thay vì tự thao tác.
Bước 2: xem số yêu cầu mỗi phút của app01.company.vn trên bảng theo dõi; vượt 5000 req/phút là dấu quá tải chứ không phải lỗi cấu hình.
Bước 3: ghi mốc giờ quan sát được rồi gửi kèm khi mở phiếu hỗ trợ.
Người phụ trách kỹ thuật của app01.company.vn là Trần Thị Hạnh.
Tài liệu này không thay SOP-12: mọi thay đổi tham số giới hạn bộ nhớ vẫn phải có phiếu thay đổi.
