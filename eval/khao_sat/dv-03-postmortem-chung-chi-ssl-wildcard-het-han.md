---
scope: noi_bo
content_type: postmortem
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Báo cáo sự cố INC-0924: chứng chỉ SSL wildcard hết hạn, 6 tên miền lỗi HTTPS

## Tóm tắt
Ngày 06/08/2026 lúc 07:00, chứng chỉ wildcard `*.khachhang02.example` hết hạn. Sáu tên miền
con trả lỗi `NET::ERR_CERT_DATE_INVALID` trong 1 giờ 24 phút. Khắc phục bằng cách phát hành
lại chứng chỉ và nạp lên WAF cùng load balancer.

## Dòng thời gian
- 07:00 - chứng chỉ hết hạn, trình duyệt bắt đầu chặn.
- 07:12 - khách hàng báo qua ticket, không phải từ cảnh báo nội bộ.
- 07:25 - NV05 xác nhận chứng chỉ hết hạn trên cả WAF và load balancer.
- 07:51 - phát hành lại chứng chỉ, xác thực bằng bản ghi DNS TXT.
- 08:10 - nạp chứng chỉ mới lên load balancer, 4 tên miền hết lỗi.
- 08:24 - nạp lên WAF, 2 tên miền còn lại hết lỗi, đóng sự cố.

## Nguyên nhân gốc
Chứng chỉ này được gia hạn tay từ đầu vì tên miền dùng DNS của khách hàng, không tự động
xác thực được. Lịch nhắc gia hạn đặt trong lịch cá nhân của một nhân sự đã chuyển bộ phận
tháng 06. Không có bảng theo dõi hạn chứng chỉ dùng chung.

## Biện pháp khắc phục
| Việc | Người | Hạn | Trạng thái |
|---|---|---|---|
| Lập bảng theo dõi hạn của toàn bộ chứng chỉ đang phục vụ | NV05 | 12/08 | xong |
| Cảnh báo trước hạn 30 ngày và 7 ngày vào kênh vận hành | NV05 | 12/08 | xong |
| Xin khách hàng ủy quyền bản ghi DNS để tự động gia hạn | NV09 | 27/08 | đang làm |

## Bài học
Chứng chỉ nạp ở hai nơi thì phải thay ở cả hai nơi. Lần này bốn tên miền hết lỗi trước hai
tên miền còn lại 14 phút vì WAF có bản sao chứng chỉ riêng, đội xử lý không nhớ điều đó.

Người thực hiện: NV05
Người duyệt: NV09
