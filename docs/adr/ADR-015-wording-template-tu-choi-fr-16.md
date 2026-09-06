# ADR-015 - Wording template từ chối FR-16

**Bối cảnh.** FR-16 đòi một template từ chối **cố định, dùng chung cho cả ca không có đáp án lẫn ca bị chặn L0**, và đòi hai ca ấy không phân biệt được từ phía người dùng. `EXPERIENCE.md` mục "Template từ chối duy nhất (FR-16)" đề xuất một câu và đánh dấu `[ASSUMPTION wording chưa chốt]`; câu hỏi mở 2 của cùng tài liệu ghi rõ "ràng buộc đã rõ, wording trong spine là đề xuất". Story 3.5 là chỗ đầu tiên hệ thật sự render một lượt từ chối, nên nó là chỗ câu ấy phải được chốt. Action item Epic 3 của sonlm trong `sprint-status.yaml` đòi đúng ADR này.

## Quyết định

Wording chốt, nguyên văn, một câu:

> Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi này.

Nó sống ở **đúng một chỗ trong mã Python**: hằng `api.hoi_dap.TEMPLATE_TU_CHOI`. `tests/test_tu_choi.py::test_template_tu_choi_chi_co_mot_ban_trong_ma_nguon` quét sáu thư mục code và đòi chuỗi chỉ xuất hiện ở đó cộng chính file test; `test_adr_015_chot_dung_wording_dang_chay` đòi ADR này mang đúng chuỗi ấy.

**Phép canh ấy chỉ quét `.py`, và phải nói ra điều đó.** Chuỗi này đã có bản chép thứ hai trong repo hôm nay: `_bmad-output/.../mockups/mockup-chat-console.html:530` cùng ba file `.working/direction-*.html`, và phép quét không thấy chúng. Chúng là artifact thiết kế nên chưa phải một lỗi - nhưng chúng đúng là chỗ Epic 4 sẽ chép sang `web/`, và một chuỗi tiếng Việt viết tay trong một file `.tsx` đi lọt qua cả bộ test lẫn ADR này. Đường ra là quyết định của **story 4-3**, và nó có khoản ledger riêng (khoản cuối `deferred-work.md`).

Câu này **không** đi vào trường `answer` của envelope. Envelope của một lượt từ chối khai `answer: null`, `refused: true` (AD-8): máy đọc cờ, còn câu tiếng Việt là hợp đồng của tầng **render** (màn chat Epic 4 hiện đúng nó, không tự soạn lại). Hai chỗ chứa cùng một wording là hai chỗ để nó lệch nhau.

## Vì sao không nhắc quyền, vai, nhóm hay scope

Một chữ đổi theo lý do từ chối là **kênh dò**, và nó là đúng kênh mà FR-16 dựng ra để bịt. Ba lý do hôm nay là `ngu_canh_rong`, `co_no_answer` và `tu_khoa_rong`; hai cái đầu là hai cột mà Đo 2 (PRD 5.2) đếm tách, cái thứ ba là một lỗi nội bộ. Nếu template ghép được tên vai, tên nhóm phụ trách, tên scope hay một số đếm vào, thì:

- người dò phân biệt được ca "không có đáp án" với ca "bị chặn L0" mà **không cần đọc nội dung** - độ dài chuỗi một mình đã đủ;
- một tên nhóm trong lời từ chối là một mảnh cấu trúc tổ chức rò ra ở đúng endpoint mở nhất của hệ;
- và tính chất "byte-identical giữa mọi lý do" - thứ `tests/test_tu_choi.py::test_ba_nhanh_tu_choi_cho_than_bang_nhau_tung_byte` đo bằng phép so `response.content` - vỡ.

Nên template là một hằng **trần**: không chỗ chèn, không `%s`, không `{}`. Đó là một phép kiểm chạy được, không một quy ước.

Ba thứ template cố ý **không** có, đã khai ở `EXPERIENCE.md` và giữ nguyên ở đây: không kèm trích dẫn, không placeholder L1, không gợi ý break-glass. Điểm khởi phát break-glass duy nhất là placeholder L1 của FR-14 (FR-20); một gợi ý break-glass trong lời từ chối là một kênh xin gián tiếp cho nội dung L0, và nó phá tính vô hình của L0.

## Ba biến thể đã bị loại

1. **"Tôi không tìm thấy thông tin phù hợp trong phạm vi quyền của bạn."** Loại vì nó nói ra rằng có một phạm vi quyền đang chắn, tức nó phân biệt được ca L0 với ca không có đáp án ngay trong câu chữ. Đây là biến thể dễ nhận nhất vì nó *thành thật hơn*, và đó chính là vấn đề.
2. **"Tôi không tìm thấy thông tin phù hợp. Liên hệ nhóm [nhóm phụ trách] nếu bạn cần thêm."** Loại vì hai lý do độc lập: tên nhóm đổi theo nội dung mà truy hồi chạm phải, nên câu đổi độ dài theo lý do; và ở lượt ngữ cảnh rỗng thì không có nhóm nào để ghép, tức hai nhánh buộc phải render hai câu khác nhau. Vế "liên hệ nhóm" đã có chỗ đúng của nó rồi: placeholder L1 của FR-14.
3. **Để LLM tự soạn lời từ chối.** Loại vì FR-16 nói thẳng "LLM không tự soạn lời từ chối mà trả một cờ có cấu trúc". Một câu do LLM soạn đổi theo ngữ cảnh nó vừa đọc, nên nó rò chính cái ngữ cảnh đó; và nó không lặp lại được giữa hai lần chạy, tức phép so byte của FR-16 không còn phát biểu được gì.

## Hai kênh mà byte-identical không phủ

Phép so byte phủ **nội dung** response, và chỉ chừng đó. Hai kênh còn lại phân biệt được ba nhánh từ chối, cả hai PRD 5.5 thừa nhận nằm ngoài mô hình đe dọa, và story cố ý không bù:

1. **Thời gian phản hồi.** Lượt `ngu_canh_rong` trả về ngay sau bước truy hồi; lượt `co_no_answer` chờ thêm trọn một lời gọi LLM. Khoảng cách ấy đọc được bằng một đồng hồ. Một `sleep` bù giờ là một cơ chế giả - nó không san bằng phân phối, chỉ dời trung vị - nên không có.
2. **Số lời gọi LLM.** `ngu_canh_rong` tốn 1, `co_no_answer` tốn 2, `tu_khoa_rong` tốn 1. Người hỏi không đọc được con số này, nhưng nó có mặt trong `audit_log` và trong hóa đơn provider, nên nó không phải một kênh với người ngoài mà là một thứ phải nói ra khi báo cáo Đo 2.

Kênh thứ hai chính là thứ làm hai cột của PRD 5.2 đếm được, nên nó vừa là một kênh phân biệt vừa là một phép đo cần thiết. Đó là lý do lý do từ chối vào `audit_log` chứ không vào response: chỗ đọc được nó là chỗ đã cần một tài khoản đọc Postgres.

## Ghi chú

- Đổi wording sau ADR này là một quyết định của sonlm, không phải một lần sửa hằng: hai test ở trên đỏ ngay, và `EXPERIENCE.md` cùng chương 4 phải sửa theo trong cùng một commit.
- Dấu `[ASSUMPTION]` ở `EXPERIENCE.md` mục "Template từ chối duy nhất (FR-16)" gỡ được từ đây.
