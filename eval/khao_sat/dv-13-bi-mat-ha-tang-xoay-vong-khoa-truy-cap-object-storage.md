---
scope: noi_bo
content_type: bi_mat_ha_tang
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# SOP: xoay vòng khóa truy cập Object Storage

## Phạm vi
Toàn bộ cặp khóa truy cập dùng cho bucket sao lưu, bucket tài nguyên tĩnh và bucket log.

## Chu kỳ
| Loại khóa | Chu kỳ | Người giữ |
|---|---|---|
| Khóa bucket sao lưu | 90 ngày | trưởng nhóm vận hành |
| Khóa ứng dụng đọc ghi | 180 ngày | chủ dịch vụ |
| Khóa chỉ đọc cho CDN | 365 ngày | chủ dịch vụ |

## Các bước xoay vòng
1. Tạo cặp khóa mới, chưa xóa khóa cũ.
2. Cập nhật khóa mới vào kho bí mật, không dán vào biến môi trường trong tệp cấu hình.
3. Khởi động lại dịch vụ theo từng đợt, xác nhận đọc ghi bình thường.
4. Theo dõi log truy cập 48 giờ, xác nhận không còn lời gọi nào dùng khóa cũ.
5. Vô hiệu khóa cũ, chờ thêm 7 ngày rồi xóa hẳn.

## Khi nghi ngờ lộ khóa
Vô hiệu ngay lập tức, bỏ qua bước theo dõi 48 giờ. Sau đó rà log truy cập của bucket trong 30
ngày gần nhất, tìm địa chỉ lạ. Mở phiếu sự cố bảo mật kể cả khi chưa thấy dấu hiệu bị dùng.

## Lưu ý
Khóa của bucket sao lưu không được dùng chung với khóa của ứng dụng. Ứng dụng bị chiếm quyền mà
khóa sao lưu dùng chung thì mất luôn đường khôi phục.

Người thực hiện: NV07
