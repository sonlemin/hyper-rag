---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: sao lưu và khôi phục Cloud Database

## Mục tiêu
Bảo đảm mỗi cơ sở dữ liệu sản xuất có bản sao lưu không quá 24 giờ và khôi phục được trong
2 giờ.

## Lịch sao lưu hiện hành
| Cụm | Tần suất | Giữ | Nơi lưu |
|---|---|---|---|
| db-prod-01 | hằng ngày 01:00 | 14 ngày | Object Storage bucket `backup-prod` |
| db-prod-02 | hằng ngày 01:30 | 14 ngày | Object Storage bucket `backup-prod` |
| db-staging | hằng tuần chủ nhật | 4 tuần | Object Storage bucket `backup-staging` |

## Kiểm tra bản sao lưu
```
bizfly database backup list --instance db-prod-01
```
Bản sao lưu mới nhất phải trong vòng 24 giờ. Nếu quá hạn, kiểm tra job và báo vào kênh vận hành.

## Khôi phục
1. Tạo instance mới từ bản sao lưu, không ghi đè lên instance đang chạy.
```
bizfly database restore --backup-id <id> --name db-restore-tam
```
2. Kiểm tra dữ liệu trên instance tạm trước khi chuyển ứng dụng sang.
3. Cập nhật danh sách IP được phép cho instance mới, ứng dụng sẽ không kết nối được nếu bỏ bước này.
4. Đổi chuỗi kết nối của ứng dụng, khởi động lại.
5. Giữ instance cũ ít nhất 48 giờ trước khi xóa.

## Diễn tập
Diễn tập khôi phục mỗi quý một lần trên staging. Ghi lại thời gian khôi phục thực tế vào biên
bản diễn tập. Lần gần nhất 12/08/2026, mất 1 giờ 40 phút.

## Lưu ý
Khóa truy cập bucket sao lưu là khóa riêng, không dùng chung với khóa của ứng dụng. Xoay vòng
theo quy trình xoay vòng khóa Object Storage.

Người thực hiện: NV07
