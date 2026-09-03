---
scope: noi_bo
content_type: troubleshooting
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Hướng dẫn xử lý Wi-Fi văn phòng chập chờn

## Thông tin cần hỏi người báo
1. Vị trí ngồi, tầng nào, gần bộ phát nào.
2. Chập chờn cả ngày hay theo giờ.
3. Thiết bị nào bị, chỉ một máy hay nhiều máy.
4. Có kèm hiện tượng rớt cuộc gọi hoặc hội họp trực tuyến giật không.

## Kiểm tra tại chỗ
1. Đo cường độ tín hiệu tại vị trí người báo. Dưới âm 70 dBm là yếu.
2. Đếm số thiết bị đang nối vào bộ phát gần nhất. Bộ phát hiện tại đặt trần 50 thiết bị.
3. Kiểm tra đường truyền bằng trang đo tốc độ, ghi lại ping, jitter, tốc độ tải lên và tải xuống.

## Đánh giá kết quả đo
| Tốc độ tải xuống | Đánh giá |
|---|---|
| dưới 10 Mbps | chậm |
| 20 tới 50 Mbps | trung bình tốt |
| trên 100 Mbps | nhanh |

Jitter trên 30 ms là nguyên nhân hay gặp của rớt cuộc gọi, kể cả khi tốc độ tải nhìn vẫn tốt.

## Hướng dẫn xử lý
1. Tín hiệu yếu ở một khu vực, đề xuất bổ sung bộ phát, ghi vị trí vào sơ đồ phủ sóng.
2. Quá tải thiết bị, chuyển bớt máy sang băng tần 5 GHz hoặc chuyển máy bàn sang mạng dây.
3. Chập chờn theo giờ, kiểm tra có trùng giờ sao lưu hoặc giờ họp trực tuyến đông người không.
4. Chỉ một thiết bị bị, kiểm tra trình điều khiển card mạng của máy đó.

## Lưu ý
Thiết bị dùng cho tổng đài và hội họp nên nối mạng dây. Wi-Fi văn phòng chia sẻ băng thông nên
không bảo đảm được jitter thấp.

Người thực hiện: NV13
