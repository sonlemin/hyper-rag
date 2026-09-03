---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0172: không kết nối được Cloud Database sau khi resize máy chủ

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang08.example |
| Dịch vụ | Cloud Database, Cloud Server |
| Mức ưu tiên | Nghiêm trọng |
| Người tiếp nhận | NV24 |
| Mở lúc | 03/10/2026 14:07 |
| Đóng lúc | 03/10/2026 15:22 |

## Mô tả từ khách hàng
Sau khi resize máy chủ ứng dụng, ứng dụng không kết nối được tới cơ sở dữ liệu. Khách báo hệ thống
bán hàng dừng hoàn toàn.

## Kiểm tra của kỹ thuật
1. Hướng dẫn khách kiểm tra kết nối, không thông.
```
telnet <ip-cloud-database> <port>
```
2. Kiểm tra bảng định tuyến trên máy chủ, thấy hai default route cùng metric 100.
```
ip route
```
3. Khách dùng cả Internet Gateway lẫn WAN trên Cloud Server.

## Nguyên nhân
Định tuyến bất đối xứng. Gói tin đi ra bằng một đường và về bằng đường kia, trong khi danh sách IP
được phép của Cloud Database chỉ có một trong hai địa chỉ ra.

## Xử lý
1. Đặt lại độ ưu tiên định tuyến.
```
sudo ip route replace default via <ip-public> dev <interface> metric 50
```
2. Ghim vĩnh viễn bằng `route-metric` trong `/etc/netplan/50-cloud-init.yaml` rồi `netplan apply`.
3. Rà lại danh sách IP được phép trên Dashboard, xóa rule cũ của Internet Gateway.
4. Xác nhận ứng dụng kết nối lại được.

## Ghi chú nội bộ
Cần nhắc khách rằng Cloud Database chỉ mở đúng cổng dịch vụ, không cho SSH và không ping được.
Khách hay kết luận dịch vụ chết vì ping không thông, làm chậm chẩn đoán.
