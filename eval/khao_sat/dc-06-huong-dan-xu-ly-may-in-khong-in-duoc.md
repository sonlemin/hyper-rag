---
scope: noi_bo
content_type: troubleshooting
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Hướng dẫn xử lý máy in không in được

## Thông tin cần hỏi người báo
1. Máy in nào, đặt ở tầng mấy.
2. Lỗi hiện trên màn hình máy in hay trên máy tính.
3. Người khác có in được vào máy in đó không.
4. Máy tính nối mạng dây hay Wi-Fi.

## Phân nhánh xử lý
### Chỉ một người không in được
Nhiều khả năng lỗi ở máy tính hoặc trình điều khiển.
1. Kiểm tra hàng đợi in, xóa các lệnh in đang kẹt.
2. Kiểm tra máy in mặc định có đúng không.
3. Gỡ và cài lại trình điều khiển, thêm lại máy in theo địa chỉ IP.

### Cả phòng không in được
Nhiều khả năng lỗi ở máy in hoặc mạng.
1. Ping tới địa chỉ IP của máy in.
```
ping <ip-may-in>
```
2. Ping không thông thì kiểm tra dây mạng và đèn cổng trên switch.
3. Ping thông mà không in được thì khởi động lại máy in, chờ 2 phút.
4. Kiểm tra máy in có báo hết mực, kẹt giấy, hoặc hết giấy không.

## Trường hợp thường gặp
| Hiện tượng | Nguyên nhân hay gặp | Xử lý |
|---|---|---|
| Lệnh in kẹt ở hàng đợi | dịch vụ in trên máy tính treo | khởi động lại dịch vụ Print Spooler |
| In ra giấy trắng | hết mực nhưng máy không báo | thay hộp mực |
| In sai khổ giấy | khay giấy đặt sai khổ | chỉnh khay và cấu hình in |
| Máy in mất kết nối sau khi cúp điện | máy in nhận IP mới từ DHCP | đặt IP tĩnh cho máy in |

## Lưu ý
Máy in dùng chung nên đặt IP tĩnh. Máy in đổi IP sau mỗi lần mất điện là nguyên nhân của phần lớn
phiếu báo lỗi in.

Người thực hiện: NV13
