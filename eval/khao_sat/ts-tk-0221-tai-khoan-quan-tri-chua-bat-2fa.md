---
scope: khach_hang_b
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0221: rà soát tài khoản chưa bật xác thực hai lớp

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang18.example |
| Dịch vụ | Google Workspace |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV21 |
| Mở lúc | 15/10/2026 13:20 |
| Đóng lúc | 17/10/2026 09:50 |

## Mô tả từ khách hàng
Sau một vụ lừa đảo mạo danh nhắm vào nhân viên, khách yêu cầu rà soát tài khoản nào chưa bật xác
thực hai lớp.

## Xử lý
1. Vào trang quản trị Google Workspace, mở danh sách người dùng.
2. Thêm cột trạng thái xác thực hai lớp, lọc theo trạng thái chưa bật.
3. Kết quả: 11 trên 42 tài khoản chưa bật, trong đó có 2 tài khoản quản trị.
4. Gửi danh sách cho đầu mối của khách, hướng dẫn bật bắt buộc theo đơn vị tổ chức.
5. Sau hai ngày, còn 1 tài khoản chưa bật, thuộc nhân sự đang nghỉ phép.

## Ghi chú nội bộ
Hai tài khoản quản trị không bật xác thực hai lớp là rủi ro cao. Đã đề nghị khách đặt chính sách
bắt buộc cho nhóm quản trị thay vì nhắc từng người.
