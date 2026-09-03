---
scope: khach_hang_a
content_type: bao_cao_su_co
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# TICKET TS-2610-0179: node Kubernetes chuyển NotReady

| Trường | Giá trị |
|---|---|
| Khách hàng | khachhang04.example |
| Dịch vụ | Kubernetes Engine |
| Mức ưu tiên | Cao |
| Người tiếp nhận | NV23 |
| Mở lúc | 05/10/2026 21:14 |
| Đóng lúc | 05/10/2026 22:03 |

## Mô tả từ khách hàng
Một node đang chạy tự nhiên chuyển NotReady, pod trên node đó bị đẩy đi hết.

## Kiểm tra của kỹ thuật
1. Hỏi pool có bật auto-repair không, khách trả lời không bật.
2. Xem đồ thị tài nguyên, node từng chạm 100% RAM lúc 21:05.
3. SSH vào node, kubelet ở trạng thái dừng.

## Nguyên nhân
Node hết RAM, hệ điều hành kill kubelet để giải phóng bộ nhớ. Node mất tín hiệu với control plane
nên chuyển NotReady.

## Xử lý
1. Khởi động lại kubelet, node về Ready sau 2 phút.
2. Tư vấn bật auto-repair cho pool.
3. Rà pod không đặt giới hạn bộ nhớ, tìm ra một deployment không khai limit.

## Ghi chú nội bộ
Node này stateless nên recycle sẽ nhanh hơn sửa tại chỗ. Đã ghi lại để lần sau đội trực chọn
recycle trước.
