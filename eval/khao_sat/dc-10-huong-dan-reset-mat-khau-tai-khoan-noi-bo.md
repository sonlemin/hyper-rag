---
scope: noi_bo
content_type: sop
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Hướng dẫn đặt lại mật khẩu tài khoản nội bộ

## Xác minh danh tính trước khi làm
Không đặt lại mật khẩu chỉ vì có người nhắn tin nhờ. Xác minh bằng một trong ba cách:
1. Gọi lại vào số điện thoại nội bộ ghi trong danh bạ, không gọi vào số người đó vừa gửi.
2. Xác nhận qua trưởng bộ phận của người đó.
3. Gặp trực tiếp và đối chiếu thẻ nhân viên.

## Các bước
1. Ghi phiếu, gồm tên người yêu cầu, cách xác minh đã dùng, thời điểm.
2. Đặt lại mật khẩu trên hệ quản trị tài khoản, bật cờ bắt đổi mật khẩu ở lần đăng nhập đầu.
3. Gửi mật khẩu tạm qua kênh khác với kênh yêu cầu. Yêu cầu qua chat thì gửi qua điện thoại.
4. Xác nhận người dùng đăng nhập được và đã đổi mật khẩu.
5. Đóng phiếu.

## Với tài khoản có quyền quản trị
Thêm hai bước:
1. Phải có phê duyệt của trưởng bộ phận công nghệ thông tin, không chấp nhận phê duyệt miệng.
2. Kiểm tra lại xác thực hai lớp còn hoạt động sau khi đặt lại mật khẩu.

## Kiểm tra xác thực hai lớp
Trên trang quản trị, mở danh sách người dùng, lọc theo trạng thái xác thực hai lớp. Tài khoản có
quyền quản trị mà chưa bật là phát hiện phải xử lý trong ngày.

## Lưu ý
Yêu cầu đặt lại mật khẩu gấp, kèm lý do khẩn và không cho gọi lại, là dấu hiệu của lừa đảo mạo
danh. Càng gấp càng phải xác minh.

Người thực hiện: NV14
