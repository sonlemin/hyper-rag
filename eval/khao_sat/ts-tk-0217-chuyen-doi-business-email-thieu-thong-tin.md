---
scope: khach_hang_b
content_type: vong_doi_ticket
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0217: chuyển đổi sang Business Email dừng giữa chừng

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang18.example |
| Dịch vụ | Business Email |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV24 |
| Mở lúc | 26/08/2026 09:00 |
| Đóng lúc | 28/08/2026 11:30 |

## Mô tả từ khách hàng
Khách yêu cầu chuyển 42 hộp thư sang Business Email. Sau khi bắt đầu, quá trình dừng vì thiếu
thông tin.

## Nguyên nhân
Biểu mẫu thu thập thông tin khách hàng chưa điền đủ. Thiếu danh sách hộp thư kèm dung lượng, thiếu
xác nhận quyền quản trị tên miền, thiếu thời điểm khách chấp nhận gián đoạn.

## Xử lý
1. Gửi lại biểu mẫu thu thập, hướng dẫn khách điền đủ ba mục còn thiếu.
2. Xác nhận quyền quản trị tên miền bằng bản ghi DNS TXT.
3. Thống nhất chuyển đổi vào 22:00 thứ bảy để giảm gián đoạn.
4. Chuyển đổi 42 hộp thư trong 3 giờ, kiểm tra ngẫu nhiên 5 hộp thư, dữ liệu đầy đủ.

## Ghi chú nội bộ
Chuyển đổi tay tốn nhiều công vì phải xử lý từng hộp thư. Hộp thư trên 20 GB nên chia nhỏ theo
thư mục, chuyển một lần dễ lỗi giữa chừng và phải làm lại từ đầu.
