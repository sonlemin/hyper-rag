---
scope: noi_bo
content_type: runbook
---
<!-- TÀI LIỆU DỰNG, không phải bản ghi thật. Sinh ngày 03/09/2026 cho story 2.10,
     dựng theo nghiệp vụ của 30 tài liệu Tech Support thật. Thuộc mẫu số 50 bản ghi
     giả lập của khảo sát ba tỷ lệ n-ngôi; xem docs/adr/ADR-012. -->

# Hướng dẫn đọc log Nginx bằng GoAccess khi nghi có truy cập bất thường

## Mục tiêu
Xác định nhanh nguồn gây tải, đường dẫn bị quét và mã trạng thái bất thường trong một đợt sự cố.

## Chuẩn bị
GoAccess đã cài trên máy chủ log. Định dạng log phải khớp với cấu hình, sai định dạng thì công cụ
đọc ra số 0 mà không báo lỗi.

## Các lệnh hay dùng
Xem trực tiếp trên terminal:
```
goaccess /var/log/nginx/access.log --log-format=COMBINED
```

Xuất báo cáo HTML để gửi kèm phiếu sự cố:
```
goaccess /var/log/nginx/access.log --log-format=COMBINED -o /tmp/bao-cao.html
```

Chỉ đọc khoảng thời gian xảy ra sự cố:
```
sed -n '/12\/Sep\/2026:09:0/,/12\/Sep\/2026:10:1/p' /var/log/nginx/access.log | goaccess - --log-format=COMBINED
```

## Bốn bảng cần nhìn trước
1. Top request theo đường dẫn. Một đường dẫn chiếm quá nửa lượng truy cập là dấu hiệu bị quét.
2. Top địa chỉ nguồn. Một dải địa chỉ chiếm phần lớn thì cân nhắc chặn tại WAF.
3. Phân bố mã trạng thái. Tỷ lệ 5xx tăng đột ngột chỉ tới tầng ứng dụng, 4xx tăng chỉ tới quét đường dẫn.
4. Top user-agent. Crawler thường khai tên trong user-agent, chặn theo đó nhanh hơn chặn theo địa chỉ.

## Lưu ý
Báo cáo HTML chứa địa chỉ IP của người dùng thật. Không đính kèm vào phiếu gửi ra ngoài bộ phận,
chỉ gửi phần tổng hợp.

Người thực hiện: NV05
