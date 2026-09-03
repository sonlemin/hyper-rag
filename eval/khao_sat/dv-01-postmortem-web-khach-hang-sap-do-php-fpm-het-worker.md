---
scope: noi_bo
content_type: postmortem
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Báo cáo sự cố INC-0912: web khachhang01.example sập 47 phút do PHP-FPM hết worker

## Tóm tắt
Ngày 12/09/2026, trang chính của khachhang01.example trả 502 Bad Gateway trong 47 phút,
từ 09:14 tới 10:01. Nguyên nhân là pool PHP-FPM hết worker sau khi một đợt crawler quét
trang tìm kiếm nội bộ. Khắc phục bằng cách nâng `pm.max_children` và chặn user-agent
crawler tại WAF.

## Dòng thời gian
- 09:14 - cảnh báo CloudWatch báo tỷ lệ 5xx vượt 5% trên load balancer.
- 09:19 - NV03 trực ca nhận cảnh báo, kiểm tra Nginx thấy `upstream sent no response`.
- 09:26 - xác nhận PHP-FPM đạt trần `pm.max_children = 40`, hàng đợi listen đầy.
- 09:38 - đọc access log bằng GoAccess, thấy 62% request tới `/tim-kiem` từ một dải IP.
- 09:47 - thêm rule WAF chặn user-agent của crawler, tỷ lệ 5xx bắt đầu giảm.
- 09:55 - nâng `pm.max_children` lên 80, reload PHP-FPM.
- 10:01 - tỷ lệ 5xx về 0, đóng sự cố.

## Nguyên nhân gốc
Trang tìm kiếm nội bộ không có cache và mỗi request chạy một truy vấn LIKE toàn bảng.
Bình thường lượng truy cập tới trang này thấp nên không ai để ý. Khi crawler quét, mỗi
worker giữ kết nối lâu hơn 4 giây, 40 worker bão hòa trong chưa đầy hai phút.

## Biện pháp khắc phục
| Việc | Người | Hạn | Trạng thái |
|---|---|---|---|
| Nâng `pm.max_children` lên 80 và ghim vào playbook Ansible | NV03 | 12/09 | xong |
| Thêm rule WAF chặn crawler ngoài allowlist | NV05 | 12/09 | xong |
| Thêm cache 60 giây cho trang tìm kiếm | NV07 | 20/09 | đang làm |
| Thêm cảnh báo khi worker đang bận vượt 80% trần | NV03 | 20/09 | đang làm |

## Bài học
Cảnh báo hiện chỉ theo dõi tỷ lệ lỗi ở tầng ngoài, nên đội trực biết có sự cố sau khi
người dùng đã chịu lỗi. Chỉ số worker đang bận là chỉ báo sớm, phải đưa vào bảng theo dõi.

Người thực hiện: NV03
Người duyệt: NV09
