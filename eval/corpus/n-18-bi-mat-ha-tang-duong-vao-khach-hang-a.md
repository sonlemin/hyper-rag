---
scope: khach_hang_a
content_type: bi_mat_ha_tang
---
Sổ tay đường vào hạ tầng khách hàng A (tài liệu hạn chế).
Truy cập quản trị vào cụm máy chủ của khách hàng A chỉ đi qua máy chủ nhảy jump-a.it.local, mọi phiên được ghi lại và giữ 90 ngày.
Khóa SSH quản trị của cụm khách hàng A lưu trong kho khóa Vault, cấp theo yêu cầu có thời hạn 8 giờ và do trưởng nhóm vận hành khách hàng A duyệt.
Dải mạng quản trị của cụm khách hàng A là 10.30.0.0/24, tách khỏi dải mạng dịch vụ và chỉ mở từ máy chủ nhảy.
Tài khoản quản trị cơ sở dữ liệu db01 được xoay vòng mỗi 90 ngày bằng tác vụ tự động của Vault.
Tài liệu này chỉ chia sẻ trong nhóm vận hành khách hàng A và nhóm Hạ tầng, gửi ra ngoài phải có phê duyệt của Giám đốc Kỹ thuật.
