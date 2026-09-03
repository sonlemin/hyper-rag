---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2609-0156: pod kẹt Pending với lỗi volume node affinity conflict

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang04.example |
| Dịch vụ | Kubernetes Engine |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV23 |
| Mở lúc | 29/09/2026 08:40 |
| Đóng lúc | 29/09/2026 10:22 |

## Mô tả từ khách hàng
Cụm chạy trên hai vùng khả dụng. Một pod kẹt Pending vĩnh viễn, log báo
`node(s) had volume node affinity conflict`.

## Kiểm tra của kỹ thuật
Ổ đĩa đã tạo cố định ở vùng HN1. Bộ lập lịch xếp pod sang máy chủ nằm ở vùng HN2. Đĩa vật lý không
gắn xuyên vùng được.

## Nguyên nhân
StorageClass đang tạo đĩa ngay khi PVC được khai, trước khi biết pod sẽ chạy ở vùng nào.

## Xử lý
1. Sửa StorageClass thêm `volumeBindingMode: WaitForFirstConsumer`, đĩa chỉ tạo sau khi biết vùng
   của pod.
2. Với ổ đã tạo, dùng `nodeSelector` ép pod chạy ở vùng HN1.
3. Xác nhận pod lên Running.

## Ghi chú nội bộ
Cụm này chạy đa vùng nhưng dùng StorageClass mặc định vốn dựng cho cụm một vùng. Nên rà lại các
cụm đa vùng khác của khách hàng đang dùng StorageClass mặc định.
