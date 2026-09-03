---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2609-0151: PVC kẹt Pending với lỗi invalid access mode

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang04.example |
| Dịch vụ | Kubernetes Engine |
| Mức ưu tiên | Trung bình |
| Người tiếp nhận | NV23 |
| Mở lúc | 28/09/2026 10:02 |
| Đóng lúc | 28/09/2026 11:15 |

## Mô tả từ khách hàng
Tạo ổ cứng cho ứng dụng, PVC kẹt mãi ở Pending. Sự kiện báo
`Failed to provision volume... invalid access mode`.

## Kiểm tra của kỹ thuật
Manifest khai `accessModes: ["ReadWriteMany"]`. Khách muốn ba pod cùng đọc ghi một ổ.

## Nguyên nhân
Ổ Block Storage vật lý trên Cloud chỉ hỗ trợ ReadWriteOnce, một đĩa cắm một máy. API từ chối cấu
hình nhiều máy cùng ghi.

## Xử lý
1. Sửa manifest thành `ReadWriteOnce`, PVC được cấp trong 20 giây.
2. Tư vấn ba hướng cho nhu cầu chia sẻ tệp giữa nhiều pod: dùng Object Storage, dùng File Storage
   bản thử nghiệm, hoặc tự dựng máy chủ NFS.
3. Khách chọn Object Storage vì ứng dụng chỉ ghi tệp tĩnh.

## Ghi chú nội bộ
Khách copy manifest từ một bài hướng dẫn trên mạng viết cho nền tảng khác. Nhóm hỗ trợ nên có sẵn
manifest mẫu đúng cho nền tảng này để gửi kèm.
