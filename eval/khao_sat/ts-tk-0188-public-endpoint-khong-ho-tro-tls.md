---
scope: khach_hang_a
content_type: known_issue
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0188: public endpoint Cloud Database không bật được TLS

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang11.example |
| Dịch vụ | Cloud Database |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV21 |
| Mở lúc | 19/08/2026 11:05 |
| Đóng lúc | 21/08/2026 16:30 |

## Mô tả từ khách hàng
Khách yêu cầu bật TLS cho public endpoint. Chuỗi kết nối mặc định đang là `ssl=false` và máy chủ
từ chối bắt tay TLS. Bộ phận kiểm toán của khách yêu cầu mã hóa đường truyền.

## Kiểm tra của kỹ thuật
Xác nhận public endpoint hiện không hỗ trợ TLS, không có tùy chọn bật trên Dashboard.

## Nguyên nhân
Giới hạn của dịch vụ ở thời điểm hiện tại.

## Xử lý
1. Chuyển yêu cầu sang bộ phận dịch vụ để cấu hình phía hạ tầng.
2. Bộ phận dịch vụ cấu hình xong sau 2 ngày làm việc, cấp chuỗi kết nối mới có TLS.
3. Hướng dẫn khách đổi chuỗi kết nối và kiểm tra bắt tay TLS thành công.

## Ghi chú nội bộ
Cấu hình này làm tay ở tầng hạ tầng, không có trên Dashboard nên không tự phục hồi khi instance
được dựng lại. Phải ghi vào hồ sơ khách hàng để lần sau resize không mất cấu hình.
