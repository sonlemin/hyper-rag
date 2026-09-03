---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: mở rộng dung lượng volume cho máy chủ và node Kubernetes

## Mục tiêu
Tăng dung lượng đĩa khi phân vùng vượt 85%, không dừng dịch vụ.

## Chuẩn bị
- Xác nhận đĩa hiện tại còn cho phép mở rộng. Cloud chỉ hỗ trợ mở rộng, cấm thu hẹp.
- Chụp lại `df -h` và `lsblk` trước khi làm.

## Hướng dẫn xử lý
1. Mở rộng đĩa trên Dashboard, mục Cloud Server, chọn máy chủ, chọn ổ đĩa, nhấn mở rộng.
2. Trên máy chủ, xác nhận kernel đã thấy dung lượng mới.
```
lsblk
sudo partprobe /dev/vdb
```
3. Nếu dùng LVM, mở rộng physical volume rồi logical volume.
```
sudo pvresize /dev/vdb
sudo lvextend -l +100%FREE /dev/vg_data/lv_data
sudo resize2fs /dev/vg_data/lv_data
```
4. Nếu không dùng LVM, mở rộng phân vùng rồi hệ thống tệp.
```
sudo growpart /dev/vdb 1
sudo resize2fs /dev/vdb1
```
5. Xác nhận bằng `df -h`.

## Với PVC trên Kubernetes
Sửa `spec.resources.requests.storage` trong PVC rồi `kubectl apply`. StorageClass phải có
`allowVolumeExpansion: true`. Giảm dung lượng là không được, phải tạo PVC mới và chép dữ liệu.

## Lưu ý
Đĩa vật lý gắn cố định vào một vùng khả dụng. Pod xếp sang vùng khác sẽ kẹt Pending với lỗi
`volume node affinity conflict`. Dùng `volumeBindingMode: WaitForFirstConsumer` để tránh.

Người thực hiện: NV06
