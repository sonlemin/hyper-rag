---
scope: noi_bo
content_type: runbook
---
Runbook xử lý phân vùng đầy trên máy chủ nội bộ.
Bước đầu tiên là xác định thư mục chiếm nhiều dung lượng nhất, không xóa file nào trước khi biết chủ sở hữu của nó.
Nhật ký cũ hơn 30 ngày trên phân vùng log được nén ngay mà không cần phê duyệt.
Nhật ký cũ hơn 90 ngày được xóa sau khi đã chuyển sang kho lưu trữ lạnh, do kỹ sư hạ tầng xác nhận đã chuyển xong.
Không được xóa file thuộc thư mục cơ sở dữ liệu trong bất kỳ tình huống nào, kể cả khi phân vùng đã đầy 100%.
Sau khi giải phóng dung lượng, người trực phải kiểm lại bốn dịch vụ phụ thuộc máy chủ log01 trước khi đóng cảnh báo.
