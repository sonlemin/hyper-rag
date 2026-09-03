---
scope: noi_bo
content_type: known_issue
---
Lỗi đã biết KI-014 về tác vụ xoay vòng nhật ký.
Tác vụ xoay vòng nhật ký dừng im lặng khi gặp một file nhật ký đang bị tiến trình khác giữ, và không ghi dòng lỗi nào vào nhật ký hệ thống.
Lỗi xuất hiện từ phiên bản công cụ xoay vòng 3.19, chưa có bản vá của nhà phát triển tính tới ngày 20/08.
Cách vòng tránh là chạy tay lệnh xoay vòng mỗi sáng thứ Hai và kiểm dấu thời gian của file nhật ký mới nhất.
Dấu hiệu nhận biết là dung lượng phân vùng nhật ký tăng đều mà số file nhật ký không đổi trong nhiều ngày.
Lỗi này được đánh giá mức trung bình vì có cách vòng tránh, nhưng nó là nguyên nhân xa của sự cố INC-1520.
