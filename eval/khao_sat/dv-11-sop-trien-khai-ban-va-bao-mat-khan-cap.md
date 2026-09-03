---
scope: noi_bo
content_type: sop
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# SOP: triển khai bản vá bảo mật khẩn cấp

## Phạm vi
Áp dụng cho lỗ hổng mức nghiêm trọng hoặc cao có khai thác công khai, ảnh hưởng hệ thống đang
phục vụ khách hàng.

## Mốc thời gian bắt buộc
| Mức | Đánh giá ảnh hưởng | Vá staging | Vá sản xuất |
|---|---|---|---|
| Nghiêm trọng | trong 4 giờ | trong 24 giờ | trong 48 giờ |
| Cao | trong 24 giờ | trong 72 giờ | trong 7 ngày |

## Các bước
1. Người phát hiện mở phiếu sự cố bảo mật, gán mức và ghi nguồn công bố.
2. Trưởng nhóm vận hành đánh giá phạm vi ảnh hưởng, liệt kê máy chủ và dịch vụ liên quan.
3. Thử bản vá trên staging, chạy bộ kiểm thử hồi quy.
4. Xin phê duyệt triển khai khẩn từ trưởng bộ phận. Với mức nghiêm trọng, phê duyệt qua tin nhắn
   là đủ, biên bản bổ sung sau trong 24 giờ.
5. Triển khai theo từng đợt, mỗi đợt không quá một phần ba số máy chủ, theo dõi 15 phút giữa hai đợt.
6. Xác nhận phiên bản sau khi vá và đóng phiếu.

## Đường lùi
Mọi bản vá phải có bước quay lui viết sẵn trong phiếu trước khi bắt đầu triển khai. Không có
đường lùi thì không được triển khai vào giờ phục vụ.

## Ghi nhận
Phiếu phải ghi thời điểm phát hiện, thời điểm vá xong sản xuất, và danh sách máy chủ đã vá. Số
liệu này vào báo cáo bảo mật hằng quý.

Người thực hiện: NV09
