---
scope: khach_hang_b
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0226: khách tự đặt quy tắc tường lửa và mất SSH vào máy chủ

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang19.example |
| Dịch vụ | Cloud Server |
| Mức ưu tiên | Nghiêm trọng |
| Người tiếp nhận | NV22 |
| Mở lúc | 16/10/2026 16:45 |
| Đóng lúc | 16/10/2026 17:30 |

## Mô tả từ khách hàng
Khách chạy một loạt lệnh iptables theo bài hướng dẫn trên mạng, sau đó mất kết nối SSH vào máy chủ
và không vào lại được.

## Nguyên nhân
Khách đặt chính sách mặc định của chuỗi INPUT thành DROP trước khi thêm quy tắc cho phép cổng SSH.
Phiên đang mở bị ngắt ngay tại lệnh đó.

## Xử lý
1. Hướng dẫn khách dùng bảng điều khiển từ xa của Cloud Server để vào máy, đường này không đi qua SSH.
2. Thêm quy tắc cho phép cổng SSH và cho phép kết nối đã thiết lập.
```
sudo iptables -I INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -I INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
```
3. Xác nhận SSH vào lại được, sau đó lưu quy tắc.

## Ghi chú nội bộ
Nhắc khách quy trình an toàn: thêm quy tắc cho phép trước, đổi chính sách mặc định sau, và luôn mở
sẵn một phiên thứ hai khi sửa tường lửa. Đã gửi tài liệu hướng dẫn đặt iptables tránh rủi ro.
