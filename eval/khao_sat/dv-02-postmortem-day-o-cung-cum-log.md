---
scope: noi_bo
content_type: postmortem
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Báo cáo sự cố INC-0918: cụm log ngừng nhận dữ liệu do đầy ổ cứng

## Tóm tắt
Ngày 31/07/2026, cụm log nội bộ ngừng nhận dữ liệu trong 3 giờ 12 phút. Phân vùng
`/var/lib/elasticsearch` đạt 100%, node chuyển sang trạng thái chỉ đọc. Không mất dữ liệu
đã ghi, nhưng log của toàn bộ dịch vụ trong khoảng đó không thu được.

## Dòng thời gian
- 02:41 - node log-02 vượt ngưỡng cảnh báo đĩa 85%, cảnh báo gửi vào kênh trực đêm.
- 02:41 tới 06:10 - không ai xử lý, kênh trực đêm không có người gác.
- 06:10 - NV04 vào ca sáng, thấy đĩa 100% và chỉ mục chuyển `read_only_allow_delete`.
- 06:32 - xóa chỉ mục cũ hơn 30 ngày, giải phóng 210 GB.
- 06:48 - gỡ cờ chỉ đọc, cụm nhận dữ liệu trở lại.
- 09:22 - mở rộng volume thêm 500 GB, đóng sự cố.

## Nguyên nhân gốc
Chính sách vòng đời chỉ mục được đặt giữ 30 ngày, nhưng job dọn dẹp chạy bằng cron trên
node log-01. Node đó được dựng lại ngày 18/07 và cron không được đưa vào ảnh máy chủ, nên
job im lặng ngừng chạy 13 ngày. Không có cảnh báo nào theo dõi việc job có chạy hay không.

## Biện pháp khắc phục
| Việc | Người | Hạn | Trạng thái |
|---|---|---|---|
| Chuyển dọn chỉ mục sang chính sách vòng đời của Elasticsearch | NV04 | 07/08 | xong |
| Thêm cảnh báo khi job dọn không chạy quá 48 giờ | NV04 | 07/08 | xong |
| Bổ sung người gác kênh trực đêm cho cảnh báo mức cao | NV09 | 12/08 | đang làm |
| Đưa cron vào ảnh máy chủ, không cài tay sau khi dựng | NV06 | 12/08 | đang làm |

## Bài học
Cảnh báo có bắn nhưng không có người nhận thì bằng không. Ngưỡng 85% cho 3 giờ 29 phút
thời gian phản ứng, đủ để xử lý nếu có người trực.

Người thực hiện: NV04
Người duyệt: NV09
