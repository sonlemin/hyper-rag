---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2609-0142: người dùng hợp lệ mất truy cập sau khi bật whitelist WAF

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang01.example |
| Dịch vụ | WAF |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV21 |
| Mở lúc | 26/09/2026 09:12 |
| Đóng lúc | 26/09/2026 11:40 |

## Mô tả từ khách hàng
Sau khi bật rule chỉ cho phép một số IP truy cập, toàn bộ nhân viên tại văn phòng Hà Nội của
khách không vào được trang quản trị, trả về 403. Văn phòng Đà Nẵng vào bình thường.

## Kiểm tra của kỹ thuật
Đọc log WAF thấy request từ dải của văn phòng Hà Nội bị khớp rule Deny. Đối chiếu whitelist
khách khai, thấy khách ghi dải của đường truyền dự phòng chứ không phải đường truyền chính.

## Nguyên nhân
Whitelist ghi thiếu một dải IP. Khách lấy địa chỉ bằng cách xem trên máy tính cá nhân đang
dùng đường dự phòng lúc kiểm tra.

## Xử lý
1. Hướng dẫn khách chạy `curl ifconfig.me` trên máy nằm ở đường truyền chính để lấy đúng địa chỉ ra.
2. Bổ sung dải vào whitelist.
3. Khuyến nghị chuyển WAF Mode về Phát hiện trong 24 giờ để theo dõi log, xác nhận whitelist đủ
   rồi mới chuyển lại Ngăn chặn.

## Ghi chú nội bộ
Khách này có hai đường truyền và địa chỉ ra thay đổi khi đường chính lỗi. Whitelist theo IP không
ổn định với mô hình đó. Đã đề xuất chuyển sang xác thực bằng chứng chỉ phía máy khách, khách chưa
đồng ý vì chi phí triển khai.
