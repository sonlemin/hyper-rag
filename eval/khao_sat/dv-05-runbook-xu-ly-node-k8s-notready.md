---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Runbook: xử lý node Kubernetes chuyển NotReady

## Mục tiêu
Đưa node về trạng thái Ready hoặc thay thế node, không để workload kẹt ở Pending quá 15 phút.

## Dấu hiệu
`kubectl get nodes` trả về node ở trạng thái `NotReady`, hoặc cảnh báo từ bảng theo dõi
báo kubelet ngừng gửi tín hiệu.

## Các bước kiểm tra
1. Xem trạng thái và sự kiện của node.
```
kubectl get nodes -o wide
kubectl describe node <ten-node>
```
2. Đọc phần Conditions. Ba trường hợp hay gặp:
   - `MemoryPressure True` - node hết RAM, kubelet đã bị kill.
   - `DiskPressure True` - đĩa của node đầy, thường do image cũ không dọn.
   - `Ready Unknown` - mất kết nối mạng tới control plane.
3. Nếu pool có bật auto-repair, chờ 10 phút xem hệ thống tự thay node chưa.

## Hướng dẫn xử lý
### Trường hợp MemoryPressure
```
ssh <ten-node>
sudo systemctl status kubelet
sudo systemctl restart kubelet
```
Nếu node là stateless, recycle node cho nhanh thay vì sửa tại chỗ.

### Trường hợp DiskPressure
```
sudo crictl rmi --prune
df -h /var/lib/containerd
```

### Trường hợp Ready Unknown
Kiểm tra kết nối tới control plane, sau đó drain và recycle nếu không khôi phục trong 10 phút.
```
kubectl cordon <ten-node>
kubectl drain <ten-node> --ignore-daemonsets --delete-emptydir-data
```

## Lưu ý
Không nâng cấu hình node trực tiếp trên Cloud Server. Node sẽ trở về cấu hình cũ của pool khi
recycle. Muốn đổi cấu hình thì tạo pool mới rồi drain workload sang.

Người thực hiện: NV03
