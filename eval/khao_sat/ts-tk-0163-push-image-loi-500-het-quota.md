---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0163: push image lên registry trả 500 Internal Server Error

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang06.example |
| Dịch vụ | Container Registry |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV21 |
| Mở lúc | 01/10/2026 09:50 |
| Đóng lúc | 01/10/2026 10:35 |

## Mô tả từ khách hàng
Pipeline CI dừng ở bước đẩy image, báo 500 Internal Server Error. Kéo image xuống thì bình thường.

## Kiểm tra của kỹ thuật
Kiểm tra quota tài khoản, dung lượng đã dùng đạt 100%.

## Nguyên nhân
Tài khoản hết quota lưu trữ. Thông điệp lỗi trả về 500 thay vì báo hết quota, gây hiểu nhầm là lỗi
hệ thống.

## Xử lý
1. Liên hệ bộ phận dịch vụ tăng quota cho tài khoản, xử lý trong 20 phút.
2. Tư vấn khách đặt chính sách giữ 20 tag gần nhất mỗi repo, và chỉ đẩy image cho nhánh chính.
3. Xác nhận pipeline chạy lại thành công.

## Ghi chú nội bộ
Mã lỗi 500 cho ca hết quota là lỗi phía dịch vụ, đã ghi phiếu cho đội phát triển đổi thành 413 kèm
thông điệp rõ. Trong quý này có 6 ticket cùng nguyên nhân.
