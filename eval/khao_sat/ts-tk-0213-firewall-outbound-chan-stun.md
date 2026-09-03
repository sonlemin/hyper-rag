---
scope: khach_hang_b
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0213: thiết bị thoại không kết nối được tới hệ thống tổng đài

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang17.example |
| Dịch vụ | Call Center |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV23 |
| Mở lúc | 13/10/2026 10:15 |
| Đóng lúc | 13/10/2026 15:40 |

## Mô tả từ khách hàng
Sau khi bộ phận công nghệ thông tin của khách siết tường lửa, toàn bộ thiết bị thoại mất kết nối.

## Kiểm tra của kỹ thuật
Chạy trên máy trong mạng nội bộ của khách:
1. Ping tới máy chủ stun, không có phản hồi.
2. Ping tới tên miền hệ thống thoại, không phản hồi, tra DNS trả về đúng địa chỉ.
3. Kiểm tra cổng bằng telnet tới cả hai đích, đều không mở.

## Nguyên nhân
Chính sách tường lửa mới chặn toàn bộ lưu lượng đi ra trừ cổng web. Hệ thống thoại cần một số
cổng khác.

## Xử lý
1. Gửi khách danh sách điểm cuối và cổng cần mở, bản cập nhật tại thời điểm kiểm tra.
2. Bộ phận công nghệ thông tin của khách mở theo danh sách.
3. Kiểm tra lại, ping và telnet đều thông, thiết bị đăng ký lại được.

## Ghi chú nội bộ
Danh sách điểm cuối đang giữ trên một bảng tính chia sẻ, mỗi lần gửi phải kiểm tra bản mới nhất.
Danh sách này chứa địa chỉ hạ tầng thoại, chỉ gửi cho đầu mối kỹ thuật của khách, không đăng công khai.
