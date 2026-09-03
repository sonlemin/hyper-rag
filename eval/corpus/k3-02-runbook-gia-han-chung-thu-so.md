---
scope: khach_hang_b
content_type: runbook
---
Runbook gia hạn chứng thư số cho tên miền của khách hàng B.
Chứng thư số của khách hàng B có chu kỳ 90 ngày và phải được gia hạn chậm nhất 14 ngày trước ngày hết hạn.
Hệ nhắc gia hạn gửi thư điện tử trước 30 ngày, trước 14 ngày và trước 7 ngày tới hộp thư của nhóm sở hữu tên miền.
Người thực hiện gia hạn là kỹ sư của nhóm sở hữu tên miền ghi trong bản ghi CMDB, không phải người nhận được thư nhắc.
Sau khi cài chứng thư mới, người thực hiện phải nạp lại cấu hình Nginx và kiểm ngày hết hạn mới bằng lệnh kiểm chứng thư từ bên ngoài mạng công ty.
Khi một tên miền đổi nhóm sở hữu, người bàn giao phải cập nhật hộp thư nhận nhắc trong cùng ngày bàn giao.
