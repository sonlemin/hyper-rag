# ADR-022 - Bề mặt phơi ra ở cổng M2: ba trần bằng cơ chế, bốn giới hạn nhận, và nghĩa của "trích dẫn"

**Bối cảnh.** Story 3.8 là lần đầu toàn cơ chế chạy trước hội đồng bằng curl trên corpus thật, và chín khoản ledger "bề mặt phơi ra" của các story 1.7, 3.1, 3.2, 3.3, 3.4, 3.5, 5.1 đang đợi ở địa chỉ 3-8. Kiểm tay 06/09 còn cho thấy `ts01` bị `co_no_answer` ở mọi câu vì model đọc dấu che thành thiếu dữ liệu, và một lượt của `dev01` mang 97 citation. ADR này chốt từng khoản một, phân làm ba nhóm: sửa bằng cơ chế trong 3.8, nhận làm giới hạn đã khai của khóa luận, và đổi nghĩa của một trường trong envelope.

## Nhóm A - Sửa bằng cơ chế

### Quyết định 1 - Trần thân request 64 KB ở tầng ASGI, một trần cho mọi tuyến

`api/gioi_han_than.py::GioiHanThan` là middleware ASGI thuần gắn vào `api.main.app`. Hai cửa: `Content-Length` vượt trần là 413 `THAN_QUA_LON` ngay, handler không chạy; không header hay header nói dối thì bọc `receive` đếm byte và dội 413 khi vượt. Thân 413 là envelope `{error: {code, message}}`. Không dùng `BaseHTTPMiddleware` của Starlette vì nó đọc trọn thân vào bộ nhớ trước khi gọi tiếp, đúng việc trần này chặn. Trần 64 KB gấp năm thân hợp lệ lớn nhất (`POST /do-thi` 200 id, `POST /hoi-dap` 4000 ký tự UTF-8), nên mọi phép kiểm theo ký tự phía sau (`CAU_HOI_QUA_DAI`, `LY_DO_QUA_DAI`) chạy như cũ. Không gắn vào `api/man_nap.py`: màn tải file là đường ghi hàng megabyte hợp lệ, sống sau loopback (Quyết định 6).

Đóng khoản ledger 3.3 "trần kích thước thân request" cùng hai mặt mở rộng ở 5.1 và 5.2.

### Quyết định 2 - Ba cấu hình đo chỉ chạy trên tiến trình đo, gắn vào cờ `HYPER_RAG_CHE_DO_DO` đã có

Danh mục `config/policy-*.yaml` là phẳng, nhưng chỉ `day-du` là bảng vận hành; `tat-phan-quyen` bỏ cả mức tiết lộ lẫn biên cách ly `khach_hang_b`. `api/chinh_sach.py::POLICY_VAN_HANH = {"day-du"}` và `kiem_cong_cau_hinh_do`: cờ tắt thì `KhoChinhSach.nap` (khởi động) và `hoan` (lúc chạy) từ chối id ngoài tập đó bằng 400 `POLICY_CHI_CHE_DO_DO`, **trước** `load_policy` và trước audit, nên không hàng `policy_swap` cho một lần hoán không xảy ra. Lifespan đọc cờ trước khi nạp policy; cả hai vẫn trước mọi kết nối.

Vì sao không thêm cờ mới: ADR-017 đã định nghĩa "tiến trình này sinh ra để đo" bằng đúng biến ấy, và ba bảng đo chỉ có nghĩa trong cửa sổ đó. Hệ quả nhận, và nó là một trade-off phải nói ra: máy chủ M2 chạy `HYPER_RAG_CHE_DO_DO=1` (`.env.server`), tức hàng `refusal` ở đó ghi tầng mutation - một lần Postgres chậm quá 10 giây biến lượt từ chối thành 500 `AUDIT_GHI_HONG` thay vì một template, và cổng `POLICY_CHI_CHE_DO_DO` chỉ còn có hiệu lực trên tiến trình nào chạy cờ tắt (máy dev, và bất kỳ triển khai vận hành nào sau khóa luận). Chấp nhận vì tiến trình duy nhất đang chạy là máy đo và máy demo cùng lúc, và Đo 2 cần hàng `refusal` không mất. `GET /admin/policy` trả thêm khóa chỉ đọc `che_do_do` để người vận hành thấy trạng thái trước khi hoán. Kịch bản cổng M2 nói ra mã lỗi phải thấy khi ai đó chạy nó trên tiến trình cờ tắt.

Đóng khoản ledger 3.2 "ba cấu hình đo hoán sang được trên tiến trình đang phục vụ".

### Quyết định 3 - Trần đồng thời bằng `--limit-concurrency 16` của uvicorn, không semaphore ứng dụng, không trần nhịp theo tài khoản

`api/Dockerfile` CMD thêm `--limit-concurrency 16` (`tests/test_compose_ha_tang.py::test_dockerfile_api_gioi_han_dong_thoi_16` ghim). Cờ đếm **kết nối đang mở** của uvicorn, không đếm riêng request `/hoi-dap`: healthcheck của compose và keep-alive của client đều nằm trong 16, nên con số là trần thô của "bao nhiêu thứ đang chạm tiến trình", và với mỗi lượt `/hoi-dap` là hai lời gọi LLM trả tiền thì nó cũng là trần tiền thô của một khoảnh khắc. Vượt trần thì uvicorn trả 503 văn bản trần, không envelope: giới hạn đã khai, vì đó là lớp dưới ứng dụng và một envelope ở đó đòi một tiến trình thứ hai.

**Trần nhịp theo tài khoản không làm**, và đây là quyết định chứ không phải một phép sửa hoãn. Ba lý do. Một, hệ có đúng ba tài khoản seed, không đăng ký công khai, `admin` là cửa hẹp nhất; kẻ tấn công theo mô hình đe dọa của brief là người **có** tài khoản đọc quá quyền, không phải người đốt tiền. Hai, mọi lời gọi trả tiền đều đã đếm trong `audit_log` (`llm_cost`, `embedding_cost`, `query`, `breakglass_*`), nên phát hiện sau sự việc có sẵn và FR-30 đọc được từng xu. Ba, một trần theo tài khoản đúng chỗ là một truy vấn đếm trên `audit_log` mỗi request, tức thêm một round-trip Postgres vào đường nóng cho một rủi ro mà hai điểm trên đã thu hẹp. Nếu hệ ra khỏi phạm vi khóa luận thì chỗ đặt là một dependency chung trên `cua_dong` đếm hàng theo `act` trong cửa sổ, không phải một bản riêng ở từng endpoint.

Đóng khoản ledger 3.3 "không có trần nhịp, trần đồng thời, trần chi phí theo tài khoản" cùng ba mặt mở rộng ở 5.1, 5.2, 5.3 (bảy tuyến break-glass, số câu Cypher theo số grant).

## Nhóm B - Giới hạn nhận, viết vào chương 4 mục giới hạn

### Quyết định 4 - Token không thu hồi được trước khi hết hạn 12 giờ

JWT stateless, không danh sách thu hồi, `dong_bo` không xóa dòng vắng mặt trong seed. Đường thu hồi duy nhất là đổi `JWT_SECRET` và khởi động lại, giết mọi token cùng lúc. Nhận vì hai phương án thật (cột `token_version` trên `users` đi vào claim, hay bảng thu hồi) đều là lược đồ phải bảo trì cho một hệ ba tài khoản, HTTP nội bộ, và TTL 12 giờ đã là trần của rủi ro. Chương 4 viết câu này nguyên văn.

### Quyết định 5 - Hai secret của engine ra log khi ai đó **cố ý** bật `log_level="DEBUG"`

Đường mặc định đóng từ 1.7 (`EngineACL.log_level = "INFO"` cộng cặp test đối chứng), khóa ký JWT không đi qua `asdict(self)` (3.1). Ca còn lại đòi người vận hành sửa mã nguồn để bật DEBUG; chỗ sửa đúng là một kiểu `Secret` có `__repr__` che cho `neo4j_password` và `qdrant_api_key`, chạm mọi đường đọc cấu hình kho. Nhận: một người sửa được mã nguồn để bật DEBUG thì đọc được `.env` bằng đường ngắn hơn.

### Quyết định 6 - `man-nap` không có cửa xác thực, sống sau loopback cộng SSH tunnel

Ba đường ra của khoản 3.1: gắn `doc_token`, nhận vĩnh viễn, hay bỏ service. Chọn nhận vĩnh viễn. Màn bind `127.0.0.1:8100` trên máy chủ, vào được chỉ qua SSH bằng khóa của chủ máy, `POST /api/nap` từ chối `Origin` lạ, và nó không nằm trong đường demo. Gắn JWT vào một trang không có form đăng nhập là dựng thêm một màn đăng nhập cho một công cụ vận hành một người dùng. Câu "JWT là 3.1" ở `AGENTS.md` và `docker-compose.yml` sửa thành câu này.

### Quyết định 7 - `finish_reason` chuyển địa chỉ sang story 7-4

Phân biệt "chạm trần `max_tokens`" với "model trả văn xuôi" cần `finish_reason` trong `KetQuaLLM` và cả hai lớp provider, tức đổi seam đo FR-30. Nơi con số 502 được đếm theo câu là harness Đo 2 (7.4), và đó là chỗ phải biết hai ca khác nhau; 3.8 không cần.

## Nhóm C - Nghĩa của "trích dẫn" và prompt v2

### Quyết định 8 - Citation là tập "được dùng" ∩ tập "được thấy"; audit giữ tập thấy

Khoản 3.4 đo 97 citation vì citation là mọi dòng Relationships trong ngữ cảnh. Hai đường: (a) hạ `top_k` phía server, (b) prompt trả thêm chỉ số dòng đã dùng rồi giao với tập đã dựng. Chọn (b). Lý do: (a) đổi luôn chuỗi ngữ cảnh mà Đo 3 đếm và Đo 2 chấm, tức đổi mẫu số của hai phép đo để sửa một con số hiển thị; (b) chỉ đọc thêm một khóa `nguon` từ đầu ra LLM và **chỉ thu hẹp**.

Tương tác với đường phụ theo grant (ADR-021): hyperedge được cấp **luôn giữ citation** dù model không liệt kê dòng phụ trong `nguon` (`loc_trich_dan_theo_nguon(..., giu=context.grant_ids)`), vì nhịp "hỏi lại câu này" phải tất định; vẫn chỉ thu hẹp, id được cấp mà không có trong tập thấy thì không thêm được.

Cơ chế: `adapters/tra_loi.py` thêm khóa `nguon` (danh sách số nguyên, giá trị cột `id` của khối Relationships), `hang_hyperedge_trong` nối chỉ số với id, `loc_trich_dan_theo_nguon` giao với tập citation đã dựng dưới cửa quyền của adapter. Ba luật giữ chốt brief §6: kết quả luôn là tập con của `id_hyperedge_trong(ngu_canh)` (`KetQuaHoiDap` từ chối citation ngoài tập thấy lúc dựng); chỉ số lạ bị bỏ, không lỗi; `nguon` vắng, rỗng hay toàn chỉ số lạ thì citation là **cả** tập thấy kèm WARNING, không lặng lẽ thành rỗng. Audit `query.hyperedge_ids` ghi tập thấy (`KetQuaHoiDap.hyperedge_da_thay`) để hậu kiểm không đứng trên danh sách do model khai; response mang tập dùng. Envelope không thêm khóa.

Đo trên máy chủ 07/09: `dev01` hỏi câu ghim, 95 hyperedge thấy, 2 citation dùng; `ts01` 1 citation dùng trên hơn 80 thấy.

### Quyết định 9 - Prompt trả lời v2: dấu che là một giá trị hợp lệ, không phải chỗ thiếu dữ liệu

Khoản 5.1: `ts01` bị `co_no_answer` ở mọi câu dù ngữ cảnh không rỗng, vì `[cause:masked]` bị đọc thành thiếu dữ liệu; grant mở đúng hyperedge ấy thì trả lời được (5.3). Hai bản prompt được thử trên chính ngữ cảnh đã che của `ts01` (07/09): bản chỉ thêm một luật "dòng mang dấu che vẫn là dữ liệu" vào giữa danh sách luật **không đủ**, model vẫn từ chối; bản đưa dấu che thành một đoạn riêng trước danh sách luật, gọi nó là "một giá trị hợp lệ của ngữ cảnh", đảo thứ tự hai luật (điều kiện trả lời đứng trước điều kiện từ chối) và thêm một ví dụ đúng hình câu hỏi ("hỏi nguyên nhân mà vế là `[cause:masked]` thì trả lời bằng chính dấu che") thì `ts01` trả lời `Nguyên nhân sự cố App01 lỗi 502 là [cause:masked].` với citation `L1` mang `masked_slots`. Bản thứ hai là bản chốt. Prompt vẫn không nói với model rằng ngữ cảnh đã lọc theo quyền (luật 3.5, có test).

Hệ quả cho Đo 2: wording mà cột `co_no_answer` đếm đổi ở đây, trước lần đo chính thức T7, không phải giữa hai lần đo. Đó là lý do khoản này phải đóng ở 3.8 chứ không ở 7.4.

## Phương án đã loại

- *Trần nhịp theo tài khoản trên `audit_log`* - xem Quyết định 3.
- *Hạ `top_k` cho đường phục vụ* - xem Quyết định 8; nới lại là Ask First của spec 3.8.
- *Cờ môi trường thứ hai cho cấu hình đo* - hai định nghĩa của một trạng thái.
- *Gắn JWT vào `man-nap`* - xem Quyết định 6.
- *`nguon` rỗng thành `citations: []`* - một lượt trả lời không nguồn đọc như một lượt bịa; fallback tập thấy giữ được thứ để soát.

## Giới hạn đã biết

- 503 của `--limit-concurrency` không mang envelope; `/health` cũng chịu trần ấy nên container rơi khỏi `healthy` dưới tải, và đó là hành vi mong muốn của một tiến trình một người dùng.
- Vendor trích từ khóa bằng LLM đôi khi trả đuôi hỏng (`<|>COMPLETE|>`), lượt ấy là `tu_khoa_rong`; kịch bản cổng M2 chạy lại là hết, nhưng một demo trực tiếp có thể gặp. Khoản ledger mới địa chỉ 4-7.
- `nguon` do model đếm; đếm sai một dòng là mất một citation hiển thị, không phải một lỗ an ninh. Fallback về tập thấy che đi ca model không khai gì. Kịch bản cổng M2 vì thế kiểm mức của hyperedge break-glass qua `POST /do-thi` (tất định), không qua danh sách citation.
- Quy ước `hyperedge_ids` ở docstring `core/audit.py` vẫn viết "cùng id với trường `id` của từng citation"; từ 3.8 phải đọc là "tập thấy, tập cha của citation". Sửa docstring `core/` là việc phải trình sonlm, ghi ở ledger địa chỉ 7-4 (harness Đo 2 đọc cột này).
- Trần thân 64 KB không áp cho `man-nap`.
