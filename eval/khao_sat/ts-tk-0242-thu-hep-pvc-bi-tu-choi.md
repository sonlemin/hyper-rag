---
scope: khach_hang_a
content_type: known_issue
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0242: không giảm được dung lượng ổ đĩa

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang05.example |
| Dịch vụ | Kubernetes Engine |
| Mức ưu tiên | Thấp |
| Người tiếp nhận | NV22 |
| Mở lúc | 20/10/2026 09:30 |
| Đóng lúc | 20/10/2026 10:10 |

## Mô tả từ khách hàng
Khách đang dùng ổ 100 GB nhưng chỉ dùng hết 30 GB, muốn giảm xuống 50 GB để tiết kiệm chi phí.
Sửa tệp cấu hình và áp dụng thì báo lỗi
`spec.resources.requests.storage: Forbidden: is invalid`.

## Nguyên nhân
Kubernetes và API Cloud chỉ hỗ trợ mở rộng dung lượng, cấm thu hẹp, để tránh cắt vào vùng dữ liệu
đang ghi trên ổ vật lý.

## Xử lý
Hướng dẫn khách ba bước:
1. Tạo một PVC 50 GB mới.
2. Tạo pod tạm gắn cả hai ổ, chép dữ liệu sang ổ mới.
3. Trỏ ứng dụng sang ổ mới, xác nhận chạy đúng, rồi xóa ổ cũ.

## Ghi chú nội bộ
Khách hỏi vì sao hệ thống không tự làm ba bước này. Câu trả lời là bước chép dữ liệu phải dừng ghi,
tức phải dừng ứng dụng, và hệ thống không được phép tự quyết định thời điểm đó.
