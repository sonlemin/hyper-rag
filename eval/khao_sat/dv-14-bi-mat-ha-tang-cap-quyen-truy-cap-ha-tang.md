---
scope: noi_bo
content_type: bi_mat_ha_tang
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# SOP: cấp và thu hồi quyền truy cập hạ tầng

## Phạm vi
Quyền SSH vào máy chủ, quyền vào Dashboard cloud, quyền vào cụm Kubernetes, quyền vào cơ sở dữ liệu.

## Nguyên tắc
- Cấp theo vai, không cấp theo người. Người vào vai nào nhận đúng quyền của vai đó.
- Quyền sản xuất tách khỏi quyền staging. Không có vai nào mặc định có cả hai.
- Mọi quyền có hạn. Quyền tạm cấp tối đa 7 ngày, hết hạn tự thu.

## Cấp quyền cho nhân sự mới
1. Trưởng bộ phận gửi phiếu, ghi rõ vai và hệ thống cần truy cập.
2. Vận hành tạo tài khoản, thêm khóa công khai SSH do nhân sự tự sinh. Không gửi khóa riêng qua
   bất kỳ kênh nào.
3. Bật xác thực hai lớp trước khi cấp quyền vào Dashboard.
4. Ghi vào sổ quyền, gồm ngày cấp, vai, người phê duyệt.

## Thu hồi
1. Bộ phận nhân sự báo ngày nghỉ việc hoặc chuyển bộ phận trước ít nhất 3 ngày làm việc.
2. Vận hành thu quyền trong ngày cuối cùng, không để sang hôm sau.
3. Xoay vòng mọi khóa dùng chung mà người đó từng biết.
4. Rà soát sổ quyền hằng quý, đối chiếu với danh sách nhân sự đang làm việc.

## Lưu ý
Lịch nhắc và tri thức vận hành đặt trong tài khoản cá nhân sẽ mất khi người đó rời đi. Mọi thứ
có tính vận hành phải nằm trong bảng dùng chung.

Người thực hiện: NV09
