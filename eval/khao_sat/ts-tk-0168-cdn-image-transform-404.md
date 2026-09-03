---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0168: ảnh sau chuyển đổi trả 404 trên CDN

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang07.example |
| Dịch vụ | CDN |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV22 |
| Mở lúc | 02/10/2026 13:15 |
| Đóng lúc | 02/10/2026 13:48 |

## Mô tả từ khách hàng
Khách chèn tham số chuyển đổi hình ảnh theo đúng tài liệu, nhưng truy cập link ảnh sau chuyển đổi
nhận về 404.

## Kiểm tra của kỹ thuật
Tên miền của khách chưa bật tính năng chuyển đổi hình ảnh trong trang quản trị CDN.

## Nguyên nhân
Tính năng tắt theo mặc định, tham số trong đường dẫn không có tác dụng khi tính năng chưa bật.

## Xử lý
1. Vào dịch vụ CDN trên Dashboard, chọn tên miền cần bật.
2. Vào mục xử lý hình ảnh, bật chuyển đổi hình ảnh.
3. Chờ 5 phút cho cấu hình lan, kiểm tra lại link ảnh, trả về 200.

## Ghi chú nội bộ
Tài liệu hướng dẫn hiện không nói rõ phải bật tính năng trước. Đã đề nghị bổ sung một dòng ở đầu
tài liệu.
