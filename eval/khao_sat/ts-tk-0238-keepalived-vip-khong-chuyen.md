---
scope: khach_hang_b
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0238: VIP không chuyển sang node dự phòng

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang22.example |
| Dịch vụ | Cloud Server, VPC |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV21 |
| Mở lúc | 31/08/2026 11:00 |
| Đóng lúc | 31/08/2026 14:15 |

## Mô tả từ khách hàng
Khách dựng cặp máy chủ dùng keepalived. Khi dừng dịch vụ trên node chính, node dự phòng không nhận
được địa chỉ ảo, dịch vụ mất luôn.

## Kiểm tra của kỹ thuật
1. Cấu hình hai node giống nhau, cùng nhóm định tuyến ảo, độ ưu tiên khác nhau đúng.
2. Nhật ký keepalived trên node dự phòng cho thấy nó đã chuyển sang trạng thái chính.
3. Địa chỉ ảo có trên interface nhưng lưu lượng không tới.
4. Kiểm tra Network Interface trên Dashboard, phần Allow Pair của node dự phòng chưa khai địa chỉ ảo.

## Nguyên nhân
Hạ tầng mạng chặn gói mang địa chỉ nguồn không thuộc interface, trừ khi địa chỉ đó được khai trong
Allow Pair. Node chính có khai, node dự phòng thì chưa.

## Xử lý
1. Điền địa chỉ ảo vào Allow Pair của cả hai Network Interface.
2. Thử lại chuyển đổi dự phòng, lưu lượng đi đúng sang node dự phòng.
3. Hướng dẫn khách thêm `nopreempt` nếu không muốn địa chỉ ảo tự quay về node chính.

## Ghi chú nội bộ
Cấu hình phía máy chủ đúng nhưng thiếu một bước phía hạ tầng. Tài liệu hướng dẫn có nói bước Allow
Pair, khách bỏ qua vì bước đó nằm ở phần đầu, tách khỏi phần cấu hình keepalived.
