---
scope: khach_hang_b
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0205: tổng đài không đăng ký được, mất âm thanh một chiều

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang15.example |
| Dịch vụ | Call Center |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV21 |
| Mở lúc | 11/10/2026 08:30 |
| Đóng lúc | 11/10/2026 11:10 |

## Mô tả từ khách hàng
Máy lẻ tại văn phòng khách không đăng ký được lên tổng đài. Khi đăng ký được thì cuộc gọi mất âm
thanh một chiều và rớt sau khoảng 30 giây.

## Kiểm tra của kỹ thuật
1. Xác định địa chỉ cổng mặc định của mạng nội bộ bằng `ipconfig`.
2. Truy cập router, tìm mục cấu hình ALG.
3. SIP ALG đang bật trên router.

## Nguyên nhân
SIP ALG sửa gói tin báo hiệu khi đi qua NAT. Với hạ tầng tổng đài hiện tại, tính năng này gây mất
âm thanh và rớt cuộc gọi.

## Xử lý
1. Tắt SIP ALG trên router, lưu cấu hình.
2. Khởi động lại thiết bị đầu cuối, đăng ký lại thành công.
3. Gọi thử 5 phút, âm thanh hai chiều ổn định.

## Ghi chú nội bộ
Router của khách là dòng phổ thông, thông tin đăng nhập vẫn để mặc định. Đã khuyến nghị khách đổi
mật khẩu quản trị router, ghi vào biên bản làm việc.
