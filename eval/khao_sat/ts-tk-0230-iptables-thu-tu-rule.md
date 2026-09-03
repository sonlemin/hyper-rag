---
scope: khach_hang_b
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0230: quy tắc cho phép không có tác dụng

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang20.example |
| Dịch vụ | Cloud Server |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV23 |
| Mở lúc | 17/10/2026 10:10 |
| Đóng lúc | 17/10/2026 10:55 |

## Mô tả từ khách hàng
Khách đã thêm quy tắc cho phép một dải IP truy cập cổng ứng dụng, nhưng dải đó vẫn bị chặn.

## Kiểm tra của kỹ thuật
```
sudo iptables -L INPUT -n --line-numbers
```
Quy tắc DROP toàn bộ nằm ở dòng 3, quy tắc cho phép dải IP nằm ở dòng 7.

## Nguyên nhân
iptables duyệt quy tắc theo thứ tự và dừng ở quy tắc khớp đầu tiên. Quy tắc DROP đứng trước nên
quy tắc cho phép phía sau không bao giờ được xét.

## Xử lý
1. Xóa quy tắc cho phép ở dòng 7.
2. Chèn lại vào trước quy tắc DROP.
```
sudo iptables -I INPUT 3 -s <dai-ip> -p tcp --dport <cong> -j ACCEPT
```
3. Kiểm tra từ dải đó, truy cập thành công.

## Ghi chú nội bộ
Đây là lỗi phổ biến nhất khi khách tự cấu hình iptables. Nên bổ sung phần thứ tự quy tắc vào đầu
tài liệu hướng dẫn thay vì để ở mục cuối.
