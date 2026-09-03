---
scope: khach_hang_a
content_type: postmortem
---
Postmortem sự cố INC-1208 trên App01 (tài liệu hạn chế).
Sự cố bắt đầu lúc 09:20 ngày 12/08/2026 và dịch vụ phục hồi lúc 10:00, tổng gián đoạn 40 phút, người xử lý là Trần Thị Hạnh thuộc đội Vận hành ứng dụng.
Phiếu thay đổi giới hạn bộ nhớ PHP-FPM được duyệt mà không qua bước thử trên môi trường thử nghiệm, đó là lỗi quy trình chứ không phải lỗi thao tác.
Thời gian phát hiện là 12 phút kể từ khi lỗi 502 bắt đầu, chậm hơn cam kết 5 phút vì cảnh báo mức nghiêm trọng gửi nhầm vào kênh chat thay vì gọi điện.
Hành động khắc phục là bổ sung bước thử bắt buộc cho mọi phiếu thay đổi chạm tham số bộ nhớ, hạn hoàn thành 30/08, do trưởng nhóm vận hành khách hàng A chịu trách nhiệm.
Hành động thứ hai là tách kênh cảnh báo nghiêm trọng khỏi kênh chat chung, hạn hoàn thành 15/09.
Bài học chính là một tham số hạ tầng đổi trong ca đêm vẫn gây thiệt hại cao nhất vào giờ cao điểm sáng hôm sau.
