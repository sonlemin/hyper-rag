---
scope: khach_hang_a
content_type: log
---
Trích nhật ký máy chủ web01 ngày 12/08/2026 quanh khung giờ sự cố INC-1208, do Trần Thị Hạnh trích khi lập báo cáo.
09:20 nginx error: upstream sent too big header while reading response header from upstream, client tới trang thanh toán.
09:21 php-fpm warning: child 4471 exited on signal 9 (SIGKILL), pool www đang có 12 tiến trình.
09:22 nginx error: connect() to unix socket failed (11: Resource temporarily unavailable), trả 502 cho toàn bộ yêu cầu.
09:52 systemd: bắt đầu dừng dịch vụ php7.4-fpm theo yêu cầu của người vận hành.
10:00 php-fpm notice: fpm is running, pool www khởi động lại với 24 tiến trình, mã lỗi 502 về 0.
Nhật ký của web01 được giữ 90 ngày rồi chuyển sang kho lưu trữ lạnh.
