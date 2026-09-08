# ADR-023 - Một phép hỏi lại trên đường phục vụ, trần 264 giây, và sàn máy chiếu là tripwire chứ không phán quyết

**Bối cảnh.** Story 4.7 dựng đường demo ba nhịp đầu thành một phép kiểm chạy lại được. Nó phải sửa ba thứ mà buổi bảo vệ đứng lên và cả ba là "nhịp demo đứng trên may rủi": một lượt hợp lệ bị từ chối vì đuôi từ khóa hỏng của vendor (khoản ledger từ 3.8), vòng focus trên topbar 1,55:1 (khoản từ 4.5), và đỉnh mờ 45% chỉ 2,71:1 trên màn hình hoàn hảo (đo ở 4.6). Ba phép sửa ấy chạm ba thứ mà mọi story 3.x-5.x cùng hạng đều để lại một ADR: một phép **thử lại trên đường phục vụ** - thứ 3.3 và 3.5 đóng băng là "không có"; một con số **chương 4 phát biểu cho NFR-08**; và một **token màu ghi đè một giá trị đã duyệt** của DESIGN.md. Không có file này thì cả ba chỉ sống trong `AGENTS.md`, một comment `sprint-status.yaml` và ba khối `resolved:`.

## Quyết định 1 - Hỏi lại đúng một lần khi đầu ra **đã về** mà không parse được; ranh giới với lớp thử lại 429 là "chờ" hay "hỏi"

`adapters/tra_loi.py::SO_LAN_HOI_LAI_TU_KHOA_HONG = 1`. `EngineACL.ngu_canh_hoi_dap` gọi lại `aquery(only_need_context=True)` đúng một lần khi chuỗi trả về **bằng** `CAU_HONG_UPSTREAM`, kèm một dòng WARNING mang `request_id`. Hai lần đều hỏng thì chuỗi ấy đi ra nguyên và `hoi_dap` cho `tu_khoa_rong` như trước; không có lý do từ chối thứ tư, không hàng audit mới.

**Ranh giới với luật đóng băng ở 3.3, và nó là ranh giới về bản chất chứ không về số lần.** Luật cũ: một 429 giữa một câu hỏi là 502 ngay, vì chặn nhịp là **trạng thái của provider** - cửa sổ chưa mở thì thử lại chỉ nhân trần độ trễ lên mà không tăng cơ hội, và trần một request thì suy từ số lời gọi *không* thử lại. Ca này khác ở đúng chỗ đó: đầu ra **đã về**, đủ token, không lỗi mạng; nó chỉ không parse được (`<|>COMPLETE|>` thay `<|COMPLETE|>`, đo trên máy chủ 07/09, log 00:52:31Z). Hỏi lại ở đây là hỏi một lần nữa, không phải chờ một cửa sổ mở ra. Ba hệ quả là cơ chế:

- Nó **không** đi qua `adapters/thu_lai.py`: không lùi lũy thừa, không jitter, không `Retry-After`, không trần chờ. Luật "đúng một lớp thử lại trên mỗi đường gọi" không bị chạm, vì đây không phải một lớp thử lại.
- Nó đếm thành một lời gọi LLM **thứ ba** của lượt, tức nó đi vào trần chứ không nấp dưới nó (quyết định 2).
- Nới nó lên 2 hay hơn là **Ask First**: hai lần liên tiếp cùng hỏng là dấu hiệu một bản upstream đổi định dạng, và khi ấy phép sửa đúng là ở bộ parser chứ không ở số lần hỏi.

## Quyết định 2 - Chỗ đặt là trong `ngu_canh_hoi_dap`, và lý do là một vòng đời cộng một phép phòng, **không** một hàng `filter` thứ hai

Phép hỏi lại nằm ngay sau `aquery` và **trước** `xa_loc`, tức bên trong khối `try` của sổ lọc.

Bản đầu của story viết lý do là "đặt ở `hoi_dap` thì lượt sinh hai hàng `filter` mỗi namespace, phá luật của 3.6". **Câu đó sai**, và nó sai vì spec khẳng định luồng điều khiển của `vendor/` mà không đọc nó. Sự thật kiểm được ở `vendor/hypergraphrag/operate.py`: mọi đường trả `PROMPTS["fail_response"]` mà `only_need_context=True` với tới được nằm ở `:568` (JSONDecodeError), `:573`, `:576`, `:581` (thiếu từ khóa) - **tất cả trước** lời gọi `_build_query_context` ở `:584`; đường `:599` là code chết vì `:596-597` trả về trước. Một lần thử hỏng vì thế không đọc `text_chunks`/`full_docs`, `_so_loc` của lượt vẫn rỗng, và `xa_loc` không phát hàng nào. Hai chỗ đặt cho **cùng một** kết quả quan sát được.

Hệ quả phải nói ra, vì nó là một giới hạn của bộ test: **chỗ đặt hôm nay không có phép canh đỏ.** `tests/test_tu_choi.py::test_hoi_lai_dung_mot_lan_khi_duoi_tu_khoa_hong_va_van_mot_hang_filter` xanh ở cả hai chỗ đặt, và docstring của nó nói thẳng điều đó thay vì khai một bằng chứng không tồn tại. Dựng một ca làm lần thử đầu hỏng *sau* khi đã đọc kho đòi sửa `vendor/` (luật cấm) hay chèn một `fail_response` giả sau `_build_query_context` (tức đo một đường không tồn tại).

Lý do thật có hai vế, và cả hai giữ nguyên giá trị của chỗ đặt:

1. **Sổ lọc và `bo_so_loc` là một vòng đời cho một lượt.** Đặt phép hỏi lại bên trong giữ đúng một lần mở, một lần xả, một lần bỏ, không phụ thuộc chỗ nào trong `vendor/` phát ra chuỗi hỏng.
2. **Phép phòng cho một bản upstream sau.** Nếu `fail_response` có ngày dời xuống **sau** `_build_query_context`, chỗ đặt bên trong vẫn cho một hàng còn chỗ đặt bên ngoài thành hai. Đây là một phép phòng, không một phép sửa cho một lỗi đang có.

Và vì lần thử hỏng không đọc kho: `bi_loai` của hàng `filter` là số của **lần truy hồi đã đọc kho**, không một tổng của hai lần. Câu "số đếm cộng cả hai lần truy hồi" bị bỏ khỏi mọi nơi nó từng được viết.

**Dấu vết máy đọc được của phép hỏi lại là dòng WARNING, và chỉ nó.** Không thêm hằng `event` nào - đó là đổi hợp đồng audit, ngoài phạm vi story - nên dòng ấy mang `request_id` để nối được với hàng `query`/`refusal` của chính lượt đó. Không có nó thì bảng tần suất của buổi diễn tập không phân biệt được "lỗ không xảy ra" với "lỗ xảy ra và phép hỏi lại đã vá"; `kiem-tay-4-7.md` mục 1 có bước `grep` tương ứng.

## Quyết định 3 - Trần NFR-08 là **264 giây**, suy từ một cặp hằng nền cộng số lần hỏi lại

`api/hoi_dap.py` tách hai lớp hằng:

- **Nền**, đọc từ `vendor/` và ghim bằng một phép grep: `SO_LOI_GOI_LLM_NEN = 2` (trích từ khóa của `kg_query:541`, cộng sinh câu trả lời - từ 3.5 lời gọi thứ hai là prompt của **dự án**, nên tên hằng cố ý không nói "vendor") và `SO_LOI_GOI_EMBEDDING_NEN = 2` (`entities_vdb.query` ở `:743`, `hyperedges_vdb.query` ở `:938`).
- **Của một lượt**, suy: `SO_LOI_GOI_LLM_MOI_TRUY_VAN = 2 + 1 = 3`, `SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN = 2`.

Hai hằng cộng thêm **khác nhau**, và đó là toàn bộ chỗ bản đầu sai: một lần thử hỏng thoát trước `_build_query_context`, nơi cả hai lời gọi embedding sinh ra, nên nó tốn đúng **một lời gọi LLM và không lời gọi embedding nào**. `tran_mot_truy_van_giay()` = `3 x 60 + 2 x (2 x 20 + 1 x 2)` = **264 giây**. Bản đầu đoán "thêm 2 lời gọi embedding" và ra 348, cao hơn thật 84 giây - đúng loại số dẫn xuất mà AGENTS.md cấm chép mà không kiểm, và đúng loại số mà chương 4 phát biểu.

Ba điều đi kèm con số:

- Nó là **trần**, không kỳ vọng: một lượt bình thường vẫn tốn 2 và 2, và một lượt từ chối vì ngữ cảnh rỗng chỉ tốn 1 lời gọi LLM.
- **Không chỗ nào áp nó lúc chạy.** NFR-08 không đặt SLA; trần thời gian thật sự áp là trần của một lời gọi, ở `bo_llm`.
- Nó là một **hàm** chứ một hằng, để nó tính lại được từ hai chỗ đã khai - ngân sách của `adapters/thu_lai.py` và hai hằng nền - thay vì lỗi thời lần đầu ai đó đổi một trong hai. Sau story này cả dự án chỉ có **một** con số trần, là 264.

## Quyết định 4 - Sàn trợ năng ghi đè hai giá trị đã duyệt của DESIGN.md, và mô hình máy chiếu là tripwire chứ không phán quyết

Hai giá trị đã duyệt bị ghi đè, cả hai vì cùng một luật đã áp ba lần trước trong Epic 4 (badge L1 ở 4.1, chữ hàng L1 ở 4.4, nhãn tiêu đề dropdown ở 4.5): **sàn trợ năng của EXPERIENCE.md thắng khi nó mâu thuẫn với một giá trị của DESIGN.md.**

1. **Vòng focus.** `:focus-visible` toàn cục là `primary` trên mọi nền - đúng trên nền sáng (6,80:1 trên `surface-card`), **1,55:1** trên `primary-deep` của topbar, dưới cả sàn 3:1 cho chỉ báo phi văn bản. Token mới `focus-on-dark: '#FFFFFF'` (chỉ dùng cho `outline`, không bao giờ làm màu chữ hay màu nền) cộng một luật theo **vùng** `.topbar :focus-visible` cho **10,52:1**. Luật đi theo vùng chứ không theo từng nút vì ba nút focus được ở đó đến từ ba story khác nhau (4.2, 4.5) và một nút thứ tư ngày mai phải được đỡ mà không ai phải nhớ. Hai **ngoại lệ có tên** đi kèm, và cả hai là lỗ mà chính phép sửa tạo ra: tấm nổi của "xem như" (`[data-tam-xem-nhu]`, nền `surface-card`) và chip "Đang xem như" (`.chip_xem_nhu`, nền `level-l1-bg` - nút ✕ trong nó focus được từ 4.5, và `outline-offset: 2px` vẽ vòng ra ngoài nút lên nền chip: trắng ở đó là **1,10:1**). Cả hai selector mở đầu bằng `.topbar` để thắng bằng **độ đặc hiệu** (0,3,0 so với 0,2,0), không bằng thứ tự khai: thắng nhờ thứ tự là một phép sửa mà một lần sắp xếp lại `globals.css` làm mất trong khi mọi test vẫn xanh.

2. **Đỉnh L1 mờ và mũi tên tới nó.** `graph-entity-masked` tách `opacity: 0.45` thành `fill-opacity: 0.45` (nền, giữ nguyên cái nhìn thấy được) và `stroke-opacity: 0.8` (viền cùng nhãn `•••`): viền hợp thành ở 0,45 trên nền trắng là **2,71:1**, dưới sàn 3:1 và **không đạt sàn ấy ở bất kỳ hệ số máy chiếu nào**; ở 0,8 là **7,94:1**. Component mới `graph-edge-masked` đưa mũi tên ra khỏi một `opacity: 0.5` chép cứng trong TSX: ở 0,5 mũi tên là **2,21:1** và nhãn vai của nó **2,08:1**, nên `line-opacity: 0.9` và `text-opacity: 1` - dấu "đã che" của mũi tên là **nét đứt**, không phải độ mờ. Nhịp 2 của đường demo nói "che đúng đỉnh, không che cả cụm", và mũi tên là thứ nói đỉnh mờ ấy thuộc **vòng nào**, tức chính mệnh đề ấy.

**Mô hình máy chiếu.** `tests/test_web_khung.py` nhóm (14): với mỗi kênh sRGB, `v' = 0,5 + (v - 0,5) x k` với `HE_SO_MAY_CHIEU = 0.7`; tám cặp có tên của đường demo phải còn `>= 3:1` **sau** mô hình. Ba điều phải nói ra về nó:

- Nó **không** mô hình hóa ánh sáng phòng, gamma máy chiếu, hay tán xạ của màn. Nó trả lời đúng một câu: **cặp nào chết trước** khi tương phản giảm. Nó là một tripwire, không một phán quyết về WCAG.
- Nó dùng **một** sàn 3:1 cho cả tám cặp, kể cả ba cặp chữ. Ba cặp ấy đã qua sàn 4,5:1 của nhóm (2) ở tương phản **đầy đủ**; đòi 4,5:1 *sau* mô hình là đòi khoảng 6,4:1 trước nó, tức đòi sửa lại những token mà DESIGN.md đã duyệt và ba story đã `done` viện dẫn bằng số.
- Nó đứng **cạnh** một ảnh chụp thật (`eval/anh_bang_chung/may-chieu-4-7-1280.png`) và một lần nhìn bằng mắt trên máy chiếu thật (`kiem-tay-4-7.md` mục 2), không thay chúng.

Đo tại `k = 0,7` sau khi sửa: slab 4,13 · badge L1 4,19 · badge L2 3,20 · vòng focus 5,62 · vòng đồ thị 3,81 · viền đỉnh mờ 4,52 · mũi tên tới đỉnh mờ 3,28 · nhãn vai của mũi tên ấy 3,53.

## Giới hạn đã nhận

- **Chỗ đặt phép hỏi lại không có phép canh đỏ** (quyết định 2). Nó là một quyết định về vòng đời và một phép phòng, và bộ test hôm nay chỉ ghim được *kết quả* chứ không ghim được *chỗ đặt*.
- **`tu_khoa_rong` không đọc được từ response** (AD-8), nên bảng tần suất của buổi diễn tập đếm "lượt từ chối của vai đáng lẽ trả lời được" - một **cận trên**. Ba lý do chỉ tách được trong `audit_log`, và phép hỏi lại chỉ đếm được qua `grep` trên log.
- **Trần 264 giây không được áp ở đâu.** Nó là một phát biểu, không một cơ chế; một lượt vượt nó vẫn chạy tới khi trần của một lời gọi nổ.
- **Mô hình máy chiếu là một phép nội suy tuyến tính trên sRGB**, không một mô hình quang học. Một máy chiếu thật lệch cả về gamma lẫn về gam màu, và số của nó không so được với số của WCAG.
