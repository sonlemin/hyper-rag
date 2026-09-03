---
scope: noi_bo
content_type: bao_cao_su_co
---
Báo cáo sự cố INC-1520 (tài liệu hạn chế).
Ngày 18/08, phân vùng nhật ký của máy chủ log01 đầy 100% lúc 09 giờ 40 và gây hỏng dây chuyền bốn dịch vụ nội bộ trong 95 phút.
Nguyên nhân là tác vụ xoay vòng nhật ký ngừng chạy từ ngày 11/08 mà không ai nhận được thông báo, nhật ký dồn lại 7 ngày.
Cổng nội bộ không đăng nhập được vì không ghi được phiên; hệ thống chấm công mất bản ghi của buổi sáng; Jira nội bộ chỉ đọc; kho ảnh Docker từ chối mọi lượt đẩy ảnh mới.
Kỹ sư hạ tầng Lê Thị Hà nén nhật ký cũ hơn 30 ngày, khôi phục tác vụ xoay vòng và mở lại từng dịch vụ theo thứ tự phụ thuộc.
Sự cố xếp mức nghiêm trọng P1, không mất dữ liệu chấm công vì bản ghi được nhập lại từ máy quét cửa.
