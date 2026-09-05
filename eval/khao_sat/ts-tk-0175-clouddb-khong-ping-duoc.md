---
scope: khach_hang_a
content_type: vong_doi_ticket
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0175: khách báo Cloud Database chết vì không ping được

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang09.example |
| Dịch vụ | Cloud Database |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV22 |
| Mở lúc | 16/08/2026 10:30 |
| Đóng lúc | 16/08/2026 10:52 |

## Mô tả từ khách hàng
Khách báo cơ sở dữ liệu ngừng hoạt động, dẫn chứng là ping tới địa chỉ database không có phản hồi
và SSH cũng không vào được.

## Kiểm tra của kỹ thuật
Instance đang chạy bình thường, tất cả node ở trạng thái tốt. Kết nối tới đúng cổng dịch vụ thông.

## Nguyên nhân
Hiểu nhầm về mô hình dịch vụ. Cloud Database chỉ mở cổng dịch vụ được chỉ định, không mở SSH và
không trả lời ping. Đây là thiết kế, không phải sự cố.

## Xử lý
1. Hướng dẫn khách kiểm tra đúng cách bằng `telnet` tới cổng dịch vụ trên Linux hoặc
   `Test-NetConnection` trên Windows.
2. Gửi tài liệu mô tả mô hình kết nối của dịch vụ.

## Ghi chú nội bộ
Ticket dạng này chiếm phần đáng kể lượng phiếu của dịch vụ Cloud Database. Nên đưa dòng lưu ý lên
đầu trang quản trị của instance thay vì chỉ nằm trong tài liệu.
