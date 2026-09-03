---
scope: khach_hang_a
content_type: vong_doi_ticket
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0183: nâng cấu hình node bị trả về cấu hình cũ

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang10.example |
| Dịch vụ | Kubernetes Engine |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV24 |
| Mở lúc | 06/10/2026 09:20 |
| Đóng lúc | 06/10/2026 10:40 |

## Mô tả từ khách hàng
Khách vào Cloud Server nâng RAM cho một node trong pool. Sau vài ngày node bị recycle và quay về
cấu hình cũ, ứng dụng thiếu bộ nhớ.

## Nguyên nhân
Cấu hình node do pool quy định. Nâng trực tiếp trên Cloud Server chỉ có hiệu lực tới lần recycle
kế tiếp.

## Xử lý
1. Tạo pool mới với cấu hình mong muốn.
2. Cordon các node thuộc pool cũ.
```
kubectl cordon <ten-node>
kubectl drain <ten-node> --ignore-daemonsets --delete-emptydir-data
```
3. Xác nhận workload đã chuyển sang pool mới, xóa pool cũ.

## Ghi chú nội bộ
Khách hỏi thêm cách bật auto-repair cho pool đã tạo. Dịch vụ hiện chưa hỗ trợ bật sau, phải tạo
pool mới rồi chuyển workload. Đã ghi phiếu đề xuất tính năng.
