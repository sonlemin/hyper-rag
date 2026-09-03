---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2609-0160: PVC kẹt Terminating không xóa được

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang05.example |
| Dịch vụ | Kubernetes Engine |
| Mức ưu tiên | Thấp |
| Người tiếp nhận | NV24 |
| Mở lúc | 30/09/2026 15:30 |
| Đóng lúc | 30/09/2026 16:12 |

## Mô tả từ khách hàng
Xóa PVC nhưng nó kẹt ở trạng thái Terminating mãi không biến mất.

## Kiểm tra của kỹ thuật
Khách đã vào giao diện Cloud Server xóa ổ đĩa vật lý trước, sau đó mới chạy `kubectl delete pvc`.
Kubernetes gọi API xóa đĩa nhận về 404 nên không gỡ cờ bảo vệ.

## Nguyên nhân
Thứ tự xóa ngược. Phải xóa từ phía Kubernetes trước, để nó gọi API xóa đĩa vật lý.

## Xử lý
1. Kiểm tra không còn pod nào đang dùng PVC.
2. Ép gỡ cờ bảo vệ.
```
kubectl patch pvc <ten-pvc> -p '{"metadata":{"finalizers":null}}'
```
3. PVC biến mất ngay sau đó.

## Ghi chú nội bộ
Cách ép gỡ cờ này an toàn khi đĩa vật lý đã thực sự bị xóa. Nếu đĩa còn tồn tại thì gỡ cờ sẽ để lại
đĩa mồ côi tính tiền mà không ai dùng, phải kiểm tra trước khi hướng dẫn khách.
