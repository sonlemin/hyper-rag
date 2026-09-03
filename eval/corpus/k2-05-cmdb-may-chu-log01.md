---
scope: noi_bo
content_type: cmdb
---
Bản ghi CMDB máy chủ nhật ký tập trung log01.
Máy chủ log01 chạy Ubuntu 22.04 với ổ đĩa nhật ký 500 GB gắn ở phân vùng riêng, tách khỏi phân vùng hệ điều hành.
Bốn dịch vụ ghi nhật ký trực tiếp vào log01 là cổng nội bộ, hệ thống chấm công, Jira nội bộ và kho ảnh Docker.
Cả bốn dịch vụ đều coi việc ghi nhật ký là bắt buộc, nên log01 không ghi được thì cả bốn dừng nhận yêu cầu mới.
Nhóm sở hữu log01 là nhóm Hạ tầng, người phụ trách kỹ thuật là Lê Thị Hà.
Tác vụ xoay vòng nhật ký chạy hằng ngày lúc 03 giờ và kết quả được ghi vào chính log01.
