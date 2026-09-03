---
scope: noi_bo
content_type: runbook
---
Runbook sao lưu và phục hồi cơ sở dữ liệu dùng chung.
Sao lưu đầy đủ chạy lúc 01 giờ mỗi Chủ nhật, sao lưu tăng dần chạy lúc 01 giờ các ngày còn lại trong tuần.
Bản sao lưu được giữ 35 ngày trên kho gần và 12 tháng trên kho lưu trữ lạnh.
Mỗi quý phải diễn tập phục hồi ít nhất một cơ sở dữ liệu trên môi trường thử nghiệm và ghi kết quả vào sổ diễn tập.
Phục hồi trên môi trường sản xuất chỉ chạy khi có phê duyệt của Giám đốc Kỹ thuật và có mặt hai người, một thao tác một soát lại.
Nếu bản sao lưu gần nhất hỏng, người vận hành phải dừng lại và báo ngay thay vì thử phục hồi từ bản cũ hơn mà không thông báo.
