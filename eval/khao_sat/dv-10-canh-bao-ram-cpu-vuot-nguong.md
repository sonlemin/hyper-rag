---
scope: noi_bo
content_type: canh_bao
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: xử lý cảnh báo RAM và CPU vượt ngưỡng

## Ngưỡng hiện hành
| Chỉ số | Cảnh báo | Nghiêm trọng | Thời gian giữ ngưỡng |
|---|---|---|---|
| CPU | 80% | 95% | 10 phút |
| RAM sử dụng thật | 85% | 95% | 10 phút |
| Đĩa | 85% | 92% | 5 phút |

## Đọc đúng chỉ số RAM
Đồ thị RAM trên bảng theo dõi gồm cả phần cache. Máy chủ báo RAM gần đầy nhưng phần dùng thật
chỉ vài trăm MB là chuyện bình thường, cache được cấp để tận dụng RAM trống. Chỉ số cần nhìn là
phần `used` sau khi trừ `buff/cache`.
```
free -h
vmstat 1 5
```

## Hướng dẫn xử lý CPU cao
1. Tìm tiến trình chiếm CPU.
```
top -b -n 1 | head -20
pidstat -u 1 5
```
2. Nếu là tiến trình ứng dụng, kiểm tra có đợt truy cập bất thường không, đọc access log.
3. Nếu là tiến trình hệ thống, kiểm tra job định kỳ có trùng giờ không.

## Hướng dẫn xử lý RAM cao
1. Xác nhận phần dùng thật, không tính cache.
2. Kiểm tra rò rỉ bộ nhớ bằng cách so mức dùng theo thời gian trong 7 ngày.
3. Nếu là node Kubernetes, kiểm tra pod nào không đặt giới hạn bộ nhớ.

## Lưu ý
Nâng cấu hình là biện pháp cuối. Trước khi nâng phải trả lời được câu hỏi tài nguyên đi đâu, nếu
không thì nâng xong vẫn đầy như cũ.

Người thực hiện: NV03
