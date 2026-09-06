# ADR-016 - Citation dựng từ tầng truy hồi, và dấu che được chép vào `answer`

**Bối cảnh.** Tới story 3.5, `POST /hoi-dap` trả `citations: []` ở mọi lượt. Epic 4 cần một nguồn tất định cho slab bôi đen, dòng hạn chế và placeholder "còn một phần bị hạn chế, liên hệ [nhóm]" (FR-14, FR-15); Epic 5 cần điểm khởi phát break-glass. Hai khoản ledger địa chỉ 3.4 chờ ở đúng chỗ này: nhóm phụ trách chỉ tồn tại dưới dạng dấu che `[owner:<nhóm>]` trong chuỗi ngữ cảnh, và cùng một hyperedge cho hai dấu `owner` khác nhau tùy đường truy hồi (graph ra tên nhóm, vector và KV ra hằng `[owner:group]`). Story 3.4 chốt ba quyết định, ghi ở đây vì cả ba đều là lựa chọn giữa những phương án đều chạy được.

## Quyết định 1 - Citation đứng trên ngữ cảnh truy hồi cộng cửa quyền của adapter, không trên `answer`

`EngineACL.hoi_dap` đọc id hyperedge ở cột `hyperedge` của bảng Relationships trong chính chuỗi ngữ cảnh gửi cho LLM (`adapters/tra_loi.id_hyperedge_trong`), rồi hỏi adapter Neo4j **dưới ngữ cảnh vai** về khóa quyền và các vai có mặt của đúng những id ấy (`Neo4jACLGraphStorage.trich_dan_cua`, lọc bằng đúng ba mệnh đề của `get_node_edges`). Mức và tập vai bị che tính bằng hai hàm thuần của `core/masking.py` (`muc_tiet_lo`, `vai_phai_che`) - `mask` gọi cùng hàm `vai_phai_che` ấy, và `adapters/trich_dan.py` gọi nó qua module để một phép đột biến ở một chỗ đổi cả hai bên. Nhóm phụ trách vào citation dưới dạng trường có cấu trúc `owner_group`, tra từ bảng nhóm **của chính adapter graph** (`bang_nhom`), tức cùng bảng đã sinh dấu che.

Vì sao id đọc từ chuỗi mà vẫn không phải "parse chuỗi để lấy sự thật": id chỉ là **khóa tra**. Khóa quyền, mức, vai có mặt và nhóm đều đến từ adapter dưới ngữ cảnh vai hiện tại, nên một chuỗi ngữ cảnh bị sửa tay không dựng ra được một citation ngoài quyền. Nó chỉ dựng ra được một 5xx: một id có trong ngữ cảnh mà adapter không thấy là `TRICH_DAN_NGOAI_QUYEN` (500), trước lời gọi LLM sinh câu trả lời, không hàng `refusal`. Bỏ qua id đó là biến một lệch giữa tầng lọc và cửa quyền thành một citation thiếu, thứ không ai nhìn ra.

Vì sao là cột `hyperedge` chứ không thu thập ở adapter Qdrant như 3.3 gợi ý: nhánh local lấy hyperedge qua `get_node_edges(entity)`, không qua kho vector, nên một khe ở Qdrant bỏ sót nửa nhánh; và cả hai nhánh còn bị `truncate_list_by_token_size` cắt *sau* adapter, nên "adapter đã trả" khác "LLM đã thấy". Cột `hyperedge` là thứ duy nhất khớp đúng với ngữ cảnh gửi đi.

Phương án đã loại: *dựng citation bằng cách parse ngược dấu che `[slot:lý_do]` trong ngữ cảnh*. Dấu che là hiển thị, nó không mang id hyperedge, và một tên entity thật bắt đầu bằng dấu ngoặc vuông sẽ bị đọc nhầm. *Dựng từ `answer`*: đặt an toàn lên chính thứ chốt brief §6 cấm assert.

Hệ quả: lượt từ chối (cả ba lý do) vẫn ra `citations: []` byte-identical như 3.5, `KetQuaHoiDap` cấm ca "có lý do từ chối mà có citation" ngay lúc dựng, và sự kiện audit `query` mang `hyperedge_ids` đúng bằng dãy `id` của citations (id node hyperedge; quy ước ở `core/audit.py` đổi cho khớp, ingest vẫn ghi id vector).

## Quyết định 2 - Prompt đổi từ "không chép dấu che" (3.5) sang "chép nguyên dấu che" (3.4)

Story 3.5 cấm LLM chép bất kỳ chuỗi dạng `[tên:lý_do]` vào `cau_tra_loi`, vì khi đó `[owner:DevOps]` đi thẳng ra `answer` là tên nhóm phụ trách rò qua endpoint mở nhất của hệ. Đó là luật đúng của một hệ mà nhóm phụ trách chưa có đường ra nào khác.

**Thứ tự hai quyết định là nội dung, không phải một lần quay lui.** 3.5 chốt trước, khi response chưa có chỗ nào mang nhóm phụ trách ngoài chuỗi ngữ cảnh; 3.4 đổi sau, và điều kiện để đổi là chính citation của 3.4 đã mang `owner_group` - không có trường ấy thì luật của 3.5 vẫn đúng. Từ 3.4 nhóm phụ trách ra qua `citations[].owner_group` cho đúng cùng vai và cùng hyperedge, nên một dấu che `[owner:DevOps]` trong `answer` không lộ thêm gì so với response đã mang nó. Trong khi đó luật cấm chép có cái giá thật: một câu trả lời *bỏ trống* chỗ bị che đọc như một fact thiếu một vế, còn dấu che tại chỗ là thứ Epic 4 bôi đen được và nối được vào citation. Luật mới: **chép nguyên dấu che vào đúng chỗ, không đoán, không bỏ**. Prompt vẫn cấm nhắc tới quyền, hạn chế hay việc thiếu dữ liệu; và nó vẫn không nói với model rằng ngữ cảnh đã lọc theo quyền.

Điều phải giữ nguyên khi đọc quyết định này: **dấu che trong `answer` không có test an ninh nào**, và đó là cố ý. `cau_tra_loi` là văn bản tự do của LLM; phép so byte chỉ phủ lượt từ chối, và mọi assert an ninh của story đứng trên ngữ cảnh truy hồi và trên citation (chốt brief §6). Dấu che trong ngữ cảnh và trong `answer` chỉ còn là hiển thị best-effort; nguồn tất định của "vai nào bị che, nhóm nào phụ trách" là `masked_slots` và `owner_group`.

## Quyết định 3 - `masked_slots` ở L2 vẫn mang `owner`

AD-9 tổng quát hóa `owner` ở mọi mức, kể cả L2; citation nói đúng điều tầng che đã làm, nên ở L2 `masked_slots` là `["owner"]` khi hyperedge có vai ấy, và `[]` khi không có (giao với vai có mặt, HE-04 của fixture và 229/281 hyperedge của `synth`). Kiểu hàng (đầy đủ hay hổ phách) do `level` quyết (EXPERIENCE.md), không do `masked_slots` rỗng hay không. Phương án đã loại: *để `masked_slots` rỗng ở L2 cho "đẹp"* - khi đó citation nói một điều khác với ngữ cảnh, và Epic 4 phải tự suy `owner` bị che từ mức, tức một bản thứ hai của luật AD-9 ở tầng render.

## Hai khoản ledger

Khoản 3.1 (hai dấu `owner` khác nhau tùy đường truy hồi) đóng bằng chính thiết kế này: dấu che là hiển thị best-effort, nguồn tất định của nhóm là `owner_group`. Khoản 1.7 (tên người qua `entities` ở L2) không đóng ở đây: sonlm quyết ngày 06/09/2026 nạp lại `synth` để chuẩn hóa entity của vai `owner` về tên nhóm, việc đó chạm đường ingest (Ask First của spec 3.4) và kéo theo chụp lại ảnh đồ thị cộng gán lại nhãn trôi, nên địa chỉ mới là **3-8** (cổng M2), nơi Đo 3 thô phải đứng trên kho đã nhất quán.
