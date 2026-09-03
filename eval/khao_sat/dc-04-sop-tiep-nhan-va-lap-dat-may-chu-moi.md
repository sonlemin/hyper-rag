---
scope: noi_bo
content_type: sop
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# SOP: tiếp nhận và lắp đặt máy chủ mới vào tủ rack

## Bước 1: tiếp nhận
1. Đối chiếu phiếu giao hàng với đơn đặt, kiểm tra số lượng và cấu hình.
2. Kiểm tra tình trạng thùng, chụp ảnh nếu có dấu hiệu va đập.
3. Ghi số sê ri từng máy vào sổ thiết bị trước khi mở thùng.

## Bước 2: chuẩn bị
1. Xác định vị trí tủ và độ cao lắp đặt theo sơ đồ tủ. Cập nhật sơ đồ trước khi lắp, không lắp trước
   rồi vẽ sau.
2. Chuẩn bị đủ ray, ốc, dây nguồn và dây mạng đúng chiều dài. Dây dài thừa gây cản luồng khí.
3. Kiểm tra tủ còn đủ công suất nguồn cho máy mới.

## Bước 3: lắp đặt
1. Lắp ray và đưa máy vào tủ, hai người nâng với máy trên 2U.
2. Đấu hai nguồn vào hai đường cấp khác nhau. Máy chỉ đấu một nguồn phải ghi lý do vào phiếu.
3. Đấu mạng theo sơ đồ, dán nhãn hai đầu mỗi sợi dây.
4. Bịt các khe trống của tủ bằng tấm chắn.

## Bước 4: bàn giao
1. Cài phần mềm quản trị ngoài băng, đặt địa chỉ theo dải quản trị.
2. Cập nhật cơ sở dữ liệu cấu hình, gồm số sê ri, vị trí tủ, địa chỉ quản trị, ngày lắp.
3. Bàn giao cho vận hành kèm biên bản, ghi rõ người nhận.

## Lưu ý
Máy chưa vào cơ sở dữ liệu cấu hình thì coi như không tồn tại. Khi có sự cố, không ai tìm được nó
nằm ở tủ nào.

Người thực hiện: NV11
