---
scope: khach_hang_b
content_type: runbook
---
Runbook triển khai bản vá tháng cho hệ thống của khách hàng B.
Bản vá tháng được triển khai trong cửa sổ bảo trì 01 giờ đến 03 giờ ngày Chủ nhật đầu tháng, đúng cửa sổ đã thỏa thuận với khách hàng B.
Trước khi triển khai, người thực hiện phải chụp ảnh máy ảo và xác nhận bản sao lưu cơ sở dữ liệu của đêm trước đã chạy xong.
Thứ tự triển khai là máy chủ ứng dụng trước, máy chủ cơ sở dữ liệu sau, không đảo thứ tự kể cả khi bản vá cơ sở dữ liệu nhỏ hơn.
Nếu sau 30 phút dịch vụ chưa nhận lại được giao dịch thử, người thực hiện phải quay lui về ảnh chụp trước triển khai.
Kết quả triển khai được báo cho đầu mối kỹ thuật của khách hàng B chậm nhất 09 giờ sáng cùng ngày.
