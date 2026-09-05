---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: dọn dẹp registry khi hết quota

## Dấu hiệu
Push image trả về `500 Internal Server Error` hoặc `denied: quota exceeded`. Pipeline CI dừng
ở bước đẩy image.

## Kiểm tra
```
cloudctl registry quota show
cloudctl registry repo list --sort size
```

## Hướng dẫn xử lý
1. Liệt kê tag cũ hơn 90 ngày của các repo lớn nhất.
2. Xóa tag không còn dùng, giữ lại mọi tag đang chạy trên sản xuất.
```
cloudctl registry tag delete --repo <ten-repo> --tag <tag>
```
3. Nếu vẫn thiếu, liên hệ bộ phận dịch vụ để tăng quota cho tài khoản.

## Phòng ngừa
- Đặt chính sách giữ 20 tag gần nhất cho mỗi repo.
- CI chỉ đẩy image cho nhánh chính và nhánh phát hành, không đẩy cho mọi commit.
- Cảnh báo khi dung lượng vượt 80% quota.

## Lưu ý
Trước khi xóa tag phải đối chiếu với danh sách image đang chạy. Xóa nhầm tag đang chạy thì pod
khởi động lại sẽ kẹt ở `ImagePullBackOff`, và không khôi phục được nếu không build lại.

Người thực hiện: NV08
