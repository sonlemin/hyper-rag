---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: thay ổ cứng hỏng trong máy chủ vật lý

## Dấu hiệu
Cảnh báo từ bộ điều khiển RAID, đèn báo lỗi trên khay ổ, hoặc log hệ thống báo lỗi đọc ghi lặp lại
trên cùng một thiết bị.

## Kiểm tra trước khi ra phòng máy
```
sudo megacli -PDList -aALL | grep -E "Slot|Firmware state"
sudo smartctl -a /dev/sdX
```
Ghi lại số khay, số sê ri ổ và trạng thái mảng RAID. Ra phòng máy mà không có số khay thì dễ rút
nhầm ổ đang tốt.

## Các bước thay
1. Xác nhận mảng RAID còn chịu được mất một ổ. Mảng đang suy giảm mà rút thêm ổ là mất dữ liệu.
2. Lấy ổ thay thế cùng dung lượng và cùng dòng từ kho, ghi phiếu xuất kho.
3. Vào phòng máy theo quy trình ra vào, mang theo phiếu công việc.
4. Đối chiếu số khay và đèn báo trước khi rút. Bật đèn định vị nếu bộ điều khiển hỗ trợ.
```
sudo megacli -PdLocate -start -physdrv[E:S] -aALL
```
5. Rút ổ hỏng, lắp ổ mới, chờ mảng bắt đầu dựng lại.
6. Theo dõi tiến trình dựng lại tới khi hoàn tất.
```
sudo megacli -PDRbld -ShowProg -physdrv[E:S] -aALL
```

## Sau khi thay
- Ghi vào sổ thiết bị, gồm ngày thay, số sê ri ổ cũ và ổ mới, người thực hiện.
- Ổ hỏng dán nhãn và bỏ vào thùng chờ hủy. Ổ chứa dữ liệu khách hàng phải xóa an toàn hoặc hủy
  vật lý trước khi rời phòng máy.
- Cập nhật số lượng tồn kho ổ dự phòng, đặt mua thêm khi còn dưới 3 ổ mỗi dòng.

Người thực hiện: NV11
