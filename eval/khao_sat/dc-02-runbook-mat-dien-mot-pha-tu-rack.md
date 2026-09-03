---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: xử lý mất điện một pha trên tủ rack

## Dấu hiệu
Bộ phân phối nguồn báo mất nguồn ở một trong hai đường cấp, hoặc một số máy chủ trong tủ mất một
nguồn trong hai nguồn.

## Kiểm tra ngay
1. Đọc màn hình bộ phân phối nguồn của tủ, ghi lại pha nào mất và dòng điện của pha còn lại.
2. Kiểm tra danh sách máy chủ trong tủ, xác định máy nào chỉ có một nguồn. Những máy đó đang ở
   trạng thái rủi ro, mất nốt đường còn lại là tắt máy.
3. Báo ngay vào kênh trực vận hành, không chờ xác định nguyên nhân.

## Hướng dẫn xử lý
1. Nếu dòng điện của pha còn lại vượt 70% định mức, chuyển bớt tải sang tủ khác trước khi làm gì tiếp.
2. Kiểm tra aptomat của tủ, xác nhận đã nhảy hay chưa. Không đóng lại aptomat quá một lần khi chưa
   biết nguyên nhân.
3. Liên hệ bộ phận điện của tòa nhà nếu mất nguồn từ đầu vào.
4. Nếu nguyên nhân là một thiết bị trong tủ gây quá tải, rút thiết bị đó ra khỏi đường cấp và ghi
   phiếu sự cố.

## Sau sự cố
Ghi phiếu gồm thời điểm mất, thời điểm khôi phục, danh sách máy chủ bị ảnh hưởng và số máy chỉ có
một nguồn. Danh sách máy một nguồn phải chuyển cho vận hành để lên kế hoạch bổ sung nguồn thứ hai.

## Lưu ý
Máy chủ chỉ có một nguồn là rủi ro có thể thấy trước, không phải sự cố bất ngờ. Mỗi lần rà tủ phải
đếm lại số máy này và báo cáo.

Người thực hiện: NV12
