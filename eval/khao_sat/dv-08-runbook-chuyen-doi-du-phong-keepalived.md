---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: chuyển đổi dự phòng keepalived khi node Master hỏng

## Mục tiêu
Xác nhận VIP đã chuyển sang node Backup và dịch vụ tiếp tục chạy, hoặc chuyển tay khi tự động
không hoạt động.

## Kiểm tra nhanh
```
ip a show eth1
systemctl status keepalived
journalctl -u keepalived -n 50
```
Node đang giữ VIP là node có địa chỉ ảo trong kết quả `ip a`.

## Chuyển đổi tay
1. Trên node Master, dừng keepalived.
```
sudo systemctl stop keepalived
```
2. Trên node Backup, xác nhận đã nhận VIP.
```
ip a show eth1
```
3. Kiểm tra dịch vụ phía sau VIP trả lời bình thường.

## Khi VIP không chuyển
Ba nguyên nhân hay gặp:
- `virtual_router_id` khác nhau giữa hai node, gói VRRP không nhận nhau.
- VIP chưa được khai trong Allow Pair của Network Interface trên Dashboard, hạ tầng chặn gói.
- Firewall chặn giao thức VRRP giữa hai node.

## Lưu ý
Mặc định VIP quay lại Master khi Master khôi phục. Nếu không muốn chuyển đi chuyển lại, thêm
`nopreempt` vào cấu hình và đặt cả hai node ở trạng thái BACKUP.

Người thực hiện: NV06
