---
scope: noi_bo
content_type: canh_bao
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: kiểm tra nhiệt độ và hệ thống làm mát phòng máy

## Ngưỡng
| Vị trí đo | Bình thường | Cảnh báo | Nghiêm trọng |
|---|---|---|---|
| Luồng khí vào của tủ | 18 tới 24 độ C | trên 27 độ C | trên 32 độ C |
| Luồng khí ra của tủ | dưới 40 độ C | trên 45 độ C | trên 50 độ C |
| Độ ẩm phòng | 40 tới 60% | dưới 30% hoặc trên 70% | dưới 20% hoặc trên 80% |

## Kiểm tra hằng ngày
1. Đọc số trên bảng theo dõi nhiệt độ, so với ngưỡng ở trên.
2. Đi một vòng phòng máy, nghe tiếng quạt bất thường của các dàn lạnh.
3. Kiểm tra không có tủ nào bị chắn luồng khí bởi thùng carton hoặc thiết bị để tạm.
4. Ghi số đo vào sổ trực.

## Khi vượt ngưỡng cảnh báo
1. Xác định vượt ngưỡng cục bộ ở một tủ hay toàn phòng.
2. Vượt cục bộ thường do bịt kín khe trống trong tủ chưa đúng, hoặc một máy chủ có quạt hỏng.
3. Vượt toàn phòng là lỗi dàn lạnh, gọi ngay đơn vị bảo trì và báo trưởng bộ phận.
4. Nếu chạm ngưỡng nghiêm trọng, tắt bớt máy chủ không phục vụ khách hàng theo danh sách ưu tiên
   đã duyệt.

## Lưu ý
Danh sách ưu tiên tắt máy phải được duyệt trước và dán trong phòng máy. Quyết định tắt máy nào
trong lúc nhiệt độ đang tăng là quyết định tồi.

Người thực hiện: NV12
