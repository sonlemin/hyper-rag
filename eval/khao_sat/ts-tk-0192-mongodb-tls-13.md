---
scope: khach_hang_b
content_type: vong_doi_ticket
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0192: yêu cầu bật TLS 1.3 cho MongoDB

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang12.example |
| Dịch vụ | Cloud Database |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV22 |
| Mở lúc | 20/08/2026 14:40 |
| Đóng lúc | 24/08/2026 10:15 |

## Mô tả từ khách hàng
Khách yêu cầu bật TLS 1.2 và 1.3 cho instance MongoDB, hỏi có bắt buộc dùng TLS 1.3 được không và
ai cấp chứng chỉ.

## Xử lý
1. Xác nhận với bộ phận dịch vụ, phía dịch vụ hỗ trợ cấu hình TLS 1.2 và 1.3 theo yêu cầu.
2. Thống nhất khách cung cấp chứng chỉ máy chủ và chứng chỉ gốc của họ.
3. Bộ phận dịch vụ nạp chứng chỉ, cấu hình chỉ chấp nhận TLS 1.3.
4. Khách kiểm tra kết nối từ ứng dụng, thành công.

## Ghi chú nội bộ
Chứng chỉ khách cấp hết hạn 12 tháng. Đã đưa vào bảng theo dõi hạn chứng chỉ để cảnh báo trước 30
ngày, tránh lặp lại ca chứng chỉ hết hạn không ai biết.
