---
scope: khach_hang_b
content_type: vong_doi_ticket
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0201: khách dùng trình phát riêng, cần link m3u8

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang14.example |
| Dịch vụ | VOD |
| Mức ưu tiên | Thấp |
| Người tiếp nhận | NV24 |
| Mở lúc | 10/10/2026 09:45 |
| Đóng lúc | 10/10/2026 10:20 |

## Mô tả từ khách hàng
Khách không dùng trình phát của dịch vụ mà tích hợp trình phát riêng vào ứng dụng, hỏi cách lấy
đường dẫn phát.

## Xử lý
1. Hướng dẫn lấy link video, thêm `.json` vào cuối đường dẫn để lấy dữ liệu mô tả.
2. Trong dữ liệu đó lấy đường dẫn m3u8 để đưa vào trình phát riêng.
3. Khách phát thử thành công trên trình phát của họ.

## Lưu ý đã trao đổi với khách
Trình phát riêng không phát được video đã mã hóa bảo vệ nội dung. Muốn dùng trình phát riêng thì
phải tắt mã hóa cho video đó, đánh đổi bằng việc mất lớp bảo vệ.

## Ghi chú nội bộ
Khách này để toàn bộ video ở chế độ không mã hóa sau khi trao đổi. Có nội dung trả phí trong đó,
đã cảnh báo bằng văn bản và khách xác nhận chấp nhận rủi ro.
