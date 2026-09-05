---
scope: khach_hang_b
content_type: vong_doi_ticket
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0234: cài SQL Server trên Ubuntu 24.04 lỗi phụ thuộc

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang21.example |
| Dịch vụ | Cloud Server |
| Mức ưu tiên | Thấp |
| Người tiếp nhận | NV24 |
| Mở lúc | 30/08/2026 14:25 |
| Đóng lúc | 30/08/2026 16:00 |

## Mô tả từ khách hàng
Cài SQL Server theo tài liệu, bước cài gói báo lỗi không tìm được gói phụ thuộc.

## Kiểm tra của kỹ thuật
Kho phần mềm khách thêm vào là kho dành cho bản Ubuntu cũ hơn. Bản 24.04 cần kho riêng và một gói
thư viện không còn trong kho mặc định.

## Xử lý
1. Gỡ kho cũ, thêm đúng kho cho bản 24.04.
2. Cài gói thư viện thiếu từ kho phụ.
3. Chạy lại cài đặt, hoàn tất.
4. Cấu hình mật khẩu quản trị và bật dịch vụ, kiểm tra kết nối từ máy khác.

## Ghi chú nội bộ
Mật khẩu quản trị do khách tự đặt trong lúc cài, kỹ thuật không giữ. Nếu khách quên thì phải đặt
lại theo quy trình khôi phục của SQL Server, không có đường tra cứu.
