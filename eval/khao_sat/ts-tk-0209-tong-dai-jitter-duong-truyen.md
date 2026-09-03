---
scope: khach_hang_b
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0209: rớt cuộc gọi vào giờ cao điểm

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang16.example |
| Dịch vụ | Call Center |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV22 |
| Mở lúc | 12/10/2026 14:00 |
| Đóng lúc | 13/10/2026 17:20 |

## Mô tả từ khách hàng
Cuộc gọi rớt và tiếng ngắt quãng trong khoảng 09:00 tới 11:00 và 14:00 tới 16:00. Ngoài hai khung
đó thì bình thường.

## Kiểm tra của kỹ thuật
1. Đo đường truyền tại văn phòng khách vào giờ cao điểm, chọn điểm đo trong nước.
2. Kết quả: tải xuống 45 Mbps, tải lên 8 Mbps, ping 28 ms, jitter 62 ms.
3. Đo ngoài giờ cao điểm: jitter 9 ms.

## Nguyên nhân
Jitter cao vào giờ cao điểm. Tốc độ tải nhìn vẫn đủ nhưng độ trễ dao động lớn làm gói thoại tới
không đều, gây ngắt tiếng và rớt cuộc gọi.

## Xử lý
1. Chuyển thiết bị tổng đài từ Wi-Fi sang mạng dây, jitter giảm còn 21 ms.
2. Đề nghị khách bật ưu tiên lưu lượng thoại trên router.
3. Đề nghị khách làm việc với nhà cung cấp đường truyền về băng thông tải lên.
4. Sau ba ngày theo dõi, không còn báo rớt cuộc gọi.

## Ghi chú nội bộ
Tốc độ tải xuống cao che mất vấn đề thật. Nhóm hỗ trợ nên yêu cầu số jitter trong mọi ticket về
chất lượng thoại, không chỉ tốc độ.
