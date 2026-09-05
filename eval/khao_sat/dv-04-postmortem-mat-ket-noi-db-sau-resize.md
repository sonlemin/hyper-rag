---
scope: noi_bo
content_type: postmortem
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Báo cáo sự cố INC-0903: mất kết nối Cloud Database sau khi resize máy chủ

## Tóm tắt
Ngày 16/07/2026, sau khi resize máy chủ ứng dụng app-03 để tăng RAM, ứng dụng không kết nối
được tới Cloud Database trong 38 phút. Nguyên nhân là định tuyến bất đối xứng do máy chủ có
hai default route sau khi khởi động lại.

## Dòng thời gian
- 14:05 - resize app-03 từ 8 GB lên 16 GB RAM, máy chủ khởi động lại theo quy trình.
- 14:09 - ứng dụng báo lỗi timeout khi kết nối tới cổng database.
- 14:16 - NV06 kiểm tra bằng `telnet` tới IP database, không thông.
- 14:24 - kiểm tra `ip route`, thấy hai default route cùng metric 100.
- 14:35 - đặt lại route-metric trong netplan, áp dụng cấu hình.
- 14:43 - kết nối trở lại, đóng sự cố.

## Nguyên nhân gốc
Máy chủ gắn cả Internet Gateway lẫn WAN. Sau khi khởi động lại, cả hai interface đều nhận
default route từ DHCP với cùng metric. Gói tin đi ra bằng một đường và về bằng đường kia,
danh sách IP được phép của Cloud Database chỉ có một trong hai địa chỉ.

## Biện pháp khắc phục
| Việc | Người | Hạn | Trạng thái |
|---|---|---|---|
| Ghim `route-metric` trong `50-cloud-init.yaml` cho mọi máy chủ hai interface | NV06 | 23/07 | xong |
| Thêm bước kiểm tra `ip route` vào quy trình sau resize | NV06 | 23/07 | xong |
| Rà soát 14 máy chủ khác có hai interface | NV08 | 02/08 | xong, 3 máy có cùng lỗi |

## Bài học
Lỗi này đã có tài liệu xử lý bên Tech Support từ trước, nhưng đội vận hành không biết tài
liệu đó tồn tại vì nó nằm trong kho của bộ phận khác. Tri thức có mà không tìm được thì
thời gian khắc phục vẫn tính đủ.

Người thực hiện: NV06
Người duyệt: NV09
