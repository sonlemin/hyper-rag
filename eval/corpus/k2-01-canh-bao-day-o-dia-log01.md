---
scope: noi_bo
content_type: canh_bao
---
Cấu hình cảnh báo dung lượng ổ đĩa cho máy chủ nội bộ.
Cảnh báo "phân vùng đầy" mức cảnh giác bắn khi một phân vùng vượt 85% dung lượng và gửi vào kênh chat của nhóm Hạ tầng.
Cảnh báo mức nghiêm trọng bắn khi phân vùng vượt 95% và gọi điện cho kỹ sư trực hạ tầng.
Riêng máy chủ log01, ngưỡng nghiêm trọng hạ xuống 90% vì tốc độ ghi nhật ký ở đó cao hơn các máy chủ khác.
Hệ giám sát kiểm dung lượng mỗi 5 phút và tự mở ticket khi cảnh báo nghiêm trọng kéo dài quá 20 phút.
Cảnh báo dung lượng không được tắt tiếng quá 30 phút, ngoại lệ phải có phê duyệt của trưởng nhóm Hạ tầng.
