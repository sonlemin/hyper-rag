# ADR-021 - Grant là một thành phần của ngữ cảnh quyền đi qua cùng tầng che; đường phụ chọn theo id trên Neo4j

**Bối cảnh.** Sau story 5.2 (ADR-020) bảng `breakglass_grants` có hàng nhưng grant không có tác dụng lên một lượt hỏi: `PermissionContext.grant_ids` luôn rỗng, `mask` chưa nới, và hai khoản ledger địa chỉ 5.3 còn treo (đường *dùng* `grant_ids`, và `filter_max_conditions = 1` của Qdrant có chặn đường truy vấn phụ hay không). Nhịp 4 của demo cần "hỏi lại câu này" đọc được đầy đủ hyperedge đã cấp và quyền tự thu về sau 60 phút (FR-20, Đo 1 lớp f). Story 5.3 đóng cả hai khoản bằng bốn quyết định dưới đây.

## Quyết định 1 - Grant đi vào `PermissionContext.grant_ids` ở đầu lượt, đọc từ Postgres, và chỉ ở hai tuyến `/hoi-dap`, `/do-thi`

`grant_ids` là **dãy id hyperedge** (không phải id `gr-`), đọc bằng `KhoBreakGlass.grant_hieu_luc(act, role, space)` - `WHERE act = $1 AND role = $2 AND space = $3 AND expires_at > now()`, hợp các `hyperedge_ids`, khử trùng, sắp xếp; "còn hạn" so với `now()` của Postgres như mọi phép kiểm grant khác (ADR-019 mục 4). `api.hoi_dap.doc_grant_ids` gọi nó ngay sau phép kiểm đầu vào và **trước** khi dựng ngữ cảnh, rồi đưa vào `ngu_canh_cua_claim(..., grant_ids=)` -> `core.identity.ngu_canh_cua(..., grant_ids=)` -> `user_context`. Không có kênh nào khác: thân request vẫn cấm trường `grant_ids` (`ThanHoiDap`, từ 3.3), claim không mang nó, không contextvar thứ hai.

Ba hệ quả là cơ chế:

- **Ngữ cảnh đóng băng theo lượt.** Grant hết hạn giữa lượt thì lượt vẫn chạy trọn với ngữ cảnh đã dựng; lượt kế đọc lại và không còn. Không có phép kiểm hạn thứ hai ở giữa lượt.
- **Kho grant hỏng là 503 `KHO_KHONG_SAN_SANG`** (qua `api.break_glass.loi_kho`), không lặng lẽ hạ về `()`: một lượt chạy không grant vì kho rớt trông y như một lượt bình thường, và người vừa được duyệt sẽ tin rằng grant vô dụng.
- **Ba tuyến break-glass không đọc grant.** `ngu_canh_nguoi_xin` giữ `grant_ids = ()`, nên mức nền cho xin và vùng cấp là mức của bảng chính sách; xin lại một hyperedge đã được cấp vẫn là 409 `GRANT_CON_HAN` của 5.1, không thành 400 `HYPEREDGE_DA_THAY_DU`. Đổi điều này là Ask First.

Grant ở vai khác hay space khác ngủ ở đó: cửa đọc lọc đúng ba cột mà grant bind.

## Quyết định 2 - Nới ở `mask` bằng một trường làm giàu, sau cửa fail-closed; chữ ký `mask` không đổi

`mask(result, context, hyperedge_key)` là chữ ký T1 dùng chung ba adapter; grant là id hyperedge, còn khóa quyền là của cả một loại nội dung trong một scope. Cùng đường với `OWNER_GROUP_FIELD` và `NEIGHBOR_NO_KEY_FIELD`: adapter biết id, gắn `core.masking.HYPEREDGE_ID_FIELD` vào bản ghi trước khi gọi hàm che và gỡ sau (`Neo4jACLGraphStorage._che(ban_ghi, context, khoa, id_hyperedge)`, bốn nơi gọi `get_node`, `get_edge`, `get_node_edges`, `do_thi_cua` truyền id), luật vẫn sống ở `core/`. Hai hàm thuần mới: `muc_hieu_luc(context, key, id)` = `muc_tiet_lo` rồi nâng lên L2 nếu `id in context.grant_ids`; `vai_phai_che_hieu_luc(context, content_type, id)` = `{owner}` nếu được cấp, không thì `vai_phai_che`. `mask` đọc id từ trường, **sau** cửa `MaskItemOutOfPermission`.

Điều kiện nền của `core/permission.py` ("vai hiện tại còn thấy hyperedge từ L1 trở lên") vì thế là chính cửa ấy: bảng chính sách hoán sang `nhi-phan` làm HE-02 thành L0 thì bản ghi không tới được tầng che, đường phụ câm ở `get_node_edges`, và không có `MaskItemOutOfPermission` nào - grant không kéo được thứ bảng đã hạ. Ba thứ grant **không** nới: `owner` vẫn `[owner:<nhóm>]` (AD-9), lân cận không khóa vẫn che cứng (AD-9), và bản ghi không mang trường - chunk của kho KV, point của kho vector, `description` của node entity - giữ nguyên, tức grant **chỉ nâng hyperedge**, đúng chữ "danh sách hyperedge" của FR-20. Mở chunk hay `description` của nguồn được cấp là Ask First.

`adapters/trich_dan.py` và `adapters/do_thi.py` đổi sang hai hàm `_hieu_luc` để citation `level`/`masked_slots` và node đồ thị nói đúng mức đã áp: hyperedge được cấp cho `level: L2`, `masked_slots: ["owner"]` (hay `[]` nếu không có vai ấy), node đồ thị `L2` với node che chỉ còn `<id>#owner`.

## Quyết định 3 - Đường phụ chọn theo id trên Neo4j, hợp nhất tường minh, không chạm Qdrant; `FILTER_MAX_CONDITIONS` giữ 1

`EngineACL.ngu_canh_hoi_dap(cau_hoi, param)` tách từ `hoi_dap`: đường chính `aquery(only_need_context=True)` + `xa_loc` như 3.6, rồi nếu ngữ cảnh mang `grant_ids` thì **một** câu `trich_dan_cua` trên dãy id đã khử trùng - đúng cửa quyền của citation - và chỉ id có mặt trong kết quả mới đi tiếp. Cửa ấy là chỗ "câm" duy nhất: id vai không còn thấy (L0, id lạ, khác space) và id không phải hyperedge (một id entity chèn tay vào bảng grant có cạnh trong graph nhưng không dựng được một dòng vendor) đều vắng ở đó, không dòng, không lỗi, không oracle mới. Với mỗi id còn lại một câu `get_node_edges(id)` dưới chính ngữ cảnh vai của lượt; có cạnh thì một dòng cùng hình dạng dòng vendor (`operate.py:987-997`), tên lân cận đã qua `_che` với trường id nên đủ giá trị trừ `owner`, và **sắp xếp chuỗi** trước khi ghép `"|"` (Cypher của `get_node_edges` không có `ORDER BY`; dòng vendor giữ thứ tự kho trả, dòng phụ thì tất định). Hàm thuần `adapters/tra_loi.py::hop_nhat_ngu_canh(ngu_canh, hang_phu)` ghép vào khối Relationships: bỏ mọi dòng có cột `hyperedge` trùng id được cấp, nối dòng phụ bằng CSV chuẩn với `id` đánh tiếp, giữ nguyên văn dòng khác; chạy được trên cả dạng CSV chuẩn lẫn dạng hybrid của `process_combine_contexts`; khối rỗng nhận header của vendor rồi mới nhận dòng phụ (ca "câu hỏi không truy hồi được hyperedge được cấp" phải cho một lượt không rỗng); chuỗi không phải khung trả nguyên. Hợp nhất chạy **sau** nhánh `tu_khoa_rong` và **trước** `ngu_canh_rong`. `aquery` giữ nguyên cho `eval/` và `tests/ho_tro_m1.py::hoi`.

Vì sao đường phụ luôn chèn: đường chính phụ thuộc từ khóa LLM trích, còn nhịp "hỏi lại câu này" của demo phải tất định. Vì sao không chạm Qdrant: hyperedge được cấp đã ở L1 nên nó đã qua filter một field của cả ba kho; thứ còn thiếu là bảo đảm có mặt và bản đầy đủ, và chọn theo id trên Neo4j cho cả hai mà không thêm điều kiện filter nào. **Khoản ledger Qdrant đóng bằng quyết định này**: `adapters/qdrant.py::FILTER_MAX_CONDITIONS = 1` giữ nguyên, comment cập nhật, nới là Ask First. Đường phụ không LLM, không embedding, không thêm lời gọi trả tiền nào (một lượt trả lời vẫn hai lời gọi).

Ngữ cảnh ở `ngu_canh_hoi_dap` đọc mềm như `hoi_dap` từ 3.6 (thiếu thì `aquery` dội `PermissionContextMissing` đúng chỗ cũ, đường phụ không chạy); ngữ cảnh hệ thống bị từ chối bằng `TrichDanNgoaiQuyen` trước khi chạm kho, như `dung_danh_sach`.

## Quyết định 4 - Audit `query` thêm khóa `grant_ids` chỉ khi có grant; không hằng `event` mới; response không thêm trường

`chi_tiet` của ba hàng một lượt có thể để lại - `query`, `refusal`, `permission_mismatch` - thêm `grant_ids` (dãy id) **chỉ khi** ngữ cảnh mang grant (`api.hoi_dap._kem_grant`, một luật cho cả ba), nên hàng của mọi lượt không grant giữ nguyên hình dạng cũ, và hậu kiểm FR-20 đọc được lượt nào chạy dưới quyền nâng dù lượt ấy trả lời, từ chối hay hỏng ở cửa quyền; `hyperedge_ids` vẫn là dãy id citation. Không hằng `event` mới (danh mục vẫn 18). Response của `/hoi-dap` và `/do-thi` không thêm trường, `meta` không đổi (AD-8): người hỏi thấy quyền nâng qua `citations[].level` và qua nội dung, không qua một cờ.

## Phương án đã loại

- *Một đường đọc thứ hai bỏ che cho id được cấp* (ở engine hay ở `api/`): là "đường bỏ che ngoài `mask`" mà spec 1.6 và 5.3 đều đặt ở Never; nới ở `mask` thì cửa fail-closed, luật `owner`, luật không khóa và hợp đồng `adapters/mask_contract.py` dùng lại nguyên.
- *Đưa grant vào filter Qdrant* (điều kiện thứ hai, hay gộp vào khóa quyền): điều kiện thứ hai phá `FILTER_MAX_CONDITIONS = 1` và chốt brief §6 (pre-filter một field); gộp vào khóa là đổi khóa của một point theo trạng thái tạm thời của một cặp `(act, role)`, tức ghi quyền lên dữ liệu.
- *Đọc grant ở tuyến break-glass* để xin lại hyperedge đã cấp ra 400: đổi ngữ nghĩa của vùng cấp và của 409 `GRANT_CON_HAN` đã có test; Ask First.
- *Đổi chữ ký `mask` thêm tham số id*: mở lại ba adapter và mọi nơi gọi cho một luật mà một trường làm giàu chở được.

## Giới hạn đã biết

- Đường phụ chỉ bảo đảm khối Relationships. Entities và Sources vẫn là của đường chính: entity của hyperedge được cấp vào khối Entities khi đường chính với tới nó, chunk nguồn không mở (Quyết định 2).
- `hop_nhat_ngu_canh` viết lại thân khối Relationships với dấu xuống dòng `\n`; dòng giữ lại nguyên văn về nội dung, chỉ dấu kết dòng của vendor (`\r\n` ở dạng CSV chuẩn) được chuẩn hóa. Không grant thì chuỗi không đổi một byte.
- Tên hyperedge của fixture M1 chứa `subject` trong id, nên trên fixture phép so "không rò tên" chỉ đúng trên giá trị slot, cùng giới hạn đã ghi ở ADR-018.
- Ở dạng hybrid, khối Relationships sau hợp nhất trộn dòng có tab của `process_combine_contexts` với dòng CSV chuẩn của đường phụ. Bộ đọc từng dòng chịu được cả hai; LLM thấy một bảng hai kiểu dòng.
- Thứ tự citation của lượt có grant khác lượt không grant cho cùng câu hỏi: dòng phụ nối cuối khối, nên hyperedge được cấp đứng cuối `citations` dù đường chính từng xếp nó ở giữa.
- Số câu Cypher của một lượt tăng theo số id được cấp (một `trich_dan_cua` cộng một `get_node_edges` mỗi id, tuần tự), chưa có trần; trần nhịp là khoản ledger địa chỉ 3-8.
- Mỗi grant cộng thêm một citation vào con số "97 trích dẫn" của khoản ledger 3-8, vì đường phụ luôn chèn.
