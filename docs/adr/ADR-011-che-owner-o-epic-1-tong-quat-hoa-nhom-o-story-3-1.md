# ADR-011 - Che slot `owner` ở Epic 1, tổng quát hóa thành tên nhóm ở story 3.1

**Bối cảnh.** AC story 1.6 đòi slot `owner` "luôn tổng quát hóa mức vai/nhóm kể cả ở L2" (FR-10, FR-14, AD-9). Tầng che của Epic 1 hiện thay giá trị `owner` bằng một hằng chung `[owner:group]`, không nói nhóm nào, vì Epic 1 chưa có bảng tài khoản để tra người phụ trách sang nhóm. Ánh xạ đó nằm ở `users.group_name` (SPINE :214) và seed `config/`, cả hai thuộc story 3.1. Ma trận truy vết 01/09/2026 chấm tiêu chí này PARTIAL và kéo bao phủ P0 của Epic 1 xuống dưới 100%.

**Quyết định.** Tách tiêu chí làm hai. Epic 1 chịu trách nhiệm phần cơ chế: `owner` luôn bị che kể cả ở L2, dấu che là hằng số một nơi trong `core/`, không rò tên cá nhân. Story 3.1 chịu phần nội dung: đổi hằng đó thành một tra cứu ra tên nhóm phụ trách thật, chữ ký hàm che không đổi và không mở lại adapter. AC story 1.6 và story 3.1 trong `epics.md` sửa theo đúng ranh giới này.

**Phương án đã loại.**
- *Làm sớm ánh xạ nhóm ngay trong Epic 1.* Phải kéo seed tài khoản và bảng `users` về trước cổng M1, tức kéo một mảnh Epic 3 vào tuần 1 chỉ để một dấu che đọc đẹp hơn. Cơ chế bảo mật không khá hơn chút nào: tên cá nhân đã không ra ngoài từ trước.
- *Giữ nguyên AC và chấp nhận tiêu chí P0 đỏ suốt Epic 2.* Cổng bao phủ sẽ báo FAIL ở mọi lần chạy trace vì một khoản đã biết và đã có địa chỉ, làm mất tác dụng cảnh báo của chính cái cổng đó.
- *Hạ tiêu chí xuống P1.* Sai bản chất: che `owner` là cơ chế bảo mật P0, chỉ có vế đặt tên nhóm mới là việc của Epic 3.

**Hệ quả.** Bao phủ P0 của Epic 1 hết khoản PARTIAL này, tiêu chí trở thành FULL với test đang có (`test_tang_che.py:218,232`), không phải viết thêm dòng code nào. Đổi lại, `MASK_REASON_OWNER` thành nợ có địa chỉ ở story 3.1: nếu 3.1 quên, dấu che ở lại mức chung và FR-14 hụt một nửa, nên AC story 3.1 đã ghi thẳng khoản này kèm test bắt buộc. Khoản tương ứng trong `deferred-work.md` đổi địa chỉ từ ghi chú sang một AC thật.

**Ngày.** 01/09/2026
