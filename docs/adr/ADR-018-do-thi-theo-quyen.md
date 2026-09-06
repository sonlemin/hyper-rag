# ADR-018 - Đồ thị theo quyền: đỉnh không khóa bị loại, node che tách theo (hyperedge, slot), không ghi audit

**Bối cảnh.** Envelope AD-8 chốt hình dạng `graph: {nodes, edges}` từ story 3.3 nhưng nội dung luôn rỗng, nên drawer đồ thị của Epic 4 (FR-19) không có gì để vẽ. Story 3.7 thêm `POST /do-thi`: nhận danh sách id hyperedge của một lượt, server lọc lại toàn bộ theo `PermissionContext` của token hiện tại và trả cùng envelope với `/hoi-dap`. Đường đọc là một method mới của adapter graph, `Neo4jACLGraphStorage.do_thi_cua`, khai vào `MASKED_READ_METHODS` (danh sách đóng AD-9) và gọi `_che` trong đường trả về; lắp node và edge là hàm thuần `adapters/do_thi.py::dung_do_thi`; `api/do_thi.py` chỉ chuyển kiểu. Ba quyết định dưới đây đều là lựa chọn giữa những phương án chạy được, và Epic 4 cùng story 7.4 đọc luật ở đây.

## Quyết định 1 - Đỉnh entity không khóa bị loại ở đồ thị, dù ở ngữ cảnh LLM nó được che cứng

`get_node_edges` nới cho entity không khóa (AD-5: entity hợp nhất từ hai tài liệu khác scope không nhận khóa nào) đi qua mệnh đề lọc của biến lân cận, rồi tên nó bị che cứng ở tầng che (`[neighbor_id:no_key]`). Lý do là FR-12: LLM cần thấy "có một fact ở đây mà tôi không được đọc" để không mất hẳn một slot của hyperedge, và một dấu che trong ngữ cảnh không kể ra tên.

`do_thi_cua` **không** dùng nhánh nới ấy. Cả ba biến của câu Cypher - hyperedge `h`, cạnh `r`, entity `e` - đi qua mệnh đề chặt `_dieu_kien` (khóa trong tập khóa graph của vai, cùng space) cộng `e.role = entity`. AD-8 định nghĩa "ngoài quyền" cho đồ thị bằng ba ca tường minh - L0, khác space, **không khóa** - và cả ba bị loại tại server. Hyperedge không còn đỉnh nào qua lọc bị loại nguyên vòng (`MATCH`, không `OPTIONAL MATCH`), vắng mặt như một id không tồn tại.

Hai luật không mâu thuẫn, vì chúng nói về hai thứ khác nhau: một cái là ngữ cảnh gửi LLM, một cái là thứ vẽ lên màn. EXPERIENCE.md dòng 32 chốt "không vẽ node" cho đỉnh ngoài quyền, và một node mang dấu `[neighbor_id:no_key]` trên màn là một node kể rằng có một thực thể chung giữa hai khoang thuê bao - đúng thứ AD-5 giữ lại trên graph để hợp nhất khóa chứ không để cho ai xem. Đỉnh **bị che** (qua lọc, nằm ở vai bảng chính sách bắt che hoặc vai `owner`) thì khác: nó có khóa, vai được thấy hyperedge, và dấu che của nó là thứ Epic 4 bôi đen được; nó không tính vào điều kiện loại vòng.

Hệ quả phải nói ra: `masked_slots` của citation (đi qua `_dieu_kien_lan_can`, nới cho không khóa) có thể nhắc một vai mà đồ thị không có đỉnh nào cho vai đó. `tests/test_do_thi.py::test_ac2_dinh_khong_khoa_vang_va_hyperedge_chi_co_dinh_ay_vang_ca_vong` ghim cả hai vế trên cùng một kho: entity ấy vắng ở đồ thị, có mặt dưới dạng che cứng ở `get_node_edges`, và citation của hyperedge chỉ có đỉnh ấy vẫn dựng được.

Phương án đã loại: *vẽ đỉnh không khóa dưới dạng node che* - đặt AD-9 lên trên AD-8 ở đúng chỗ AD-8 nói rõ hơn, và mở một đường để đếm số thực thể chung giữa hai scope từ ngoài.

## Quyết định 2 - Mỗi đỉnh bị che là một node riêng theo cặp (hyperedge, slot)

Id của node che là `f"{id_hyperedge}#{slot}"` (`adapters.do_thi.id_node_che`), label là dấu che do `core.masking.mask` sinh, `masked: true`. Hai hyperedge cùng che một entity thật ra **hai** node; entity thấy được thì id node là id entity và dùng chung giữa các hyperedge.

Vì sao không gộp: gộp hai node che thành một là kể rằng hai fact chung một thực thể bị che - "nguyên nhân của sự cố A và nguyên nhân của sự cố B là cùng một thứ" là nội dung, dù tên thứ đó đã che. Cùng lý do mà `core/masking.py` không đánh số dấu che: hai entity cùng bị che ở một vai của một hyperedge cho đúng một chuỗi, nên ở đồ thị chúng cũng ra đúng một node và một cạnh, không đếm được có bao nhiêu giá trị bị che.

`masked` suy bằng phép so tên trước và sau che **ở adapter**, không parse dấu che: `la_dau_che` là bộ nhận diện cho vị trí id của `get_node`, và một bộ đọc ngược dấu che ở tầng lắp đồ thị là bản thứ hai của cùng một luật.

Giới hạn đã biết của phép so tên: một entity có tên **đúng bằng** một dấu che (ví dụ `[cause:masked]`) ở một vai không bị che đi ra với `masked: false` và label là chính tên đó - đúng theo luật, vì tầng che không đổi gì, nhưng client không phân biệt được nó với một node che bằng mắt. Ca này có test (`test_entity_ten_dung_bang_dau_che_o_vai_khong_che_khong_bi_coi_la_che`); nó chỉ xảy ra khi tài liệu nguồn chứa nguyên văn một dấu che, và `masked` (không phải label) là trường máy đọc. Hai va chạm id khác - entity mang id của một hyperedge, hay tên dạng `<hyperedge>#<slot>` trùng id một node che - là dữ liệu hỏng theo nghĩa của đồ thị và ra 500 `TRICH_DAN_NGOAI_QUYEN`, không lắp.

## Quyết định 3 - Không ghi hàng audit cho lượt lấy đồ thị

Đường này không ghi hàng nào và không thêm hằng `event`. Mọi hyperedge trả ra đều đã nằm trong `hyperedge_ids` của hàng `query` sinh ra lượt ấy, và cửa quyền là cùng ba mệnh đề lọc (chặt hơn, không nới), nên endpoint không mở thêm một mức đọc nào so với thứ đã ghi. Một hàng `query` không có `mili_giay` của LLM sẽ trộn vào mẫu số NFR-08; một hằng `event` mới là Ask First của story 3.6 (ADR-017). Nếu 7.4 hay hậu kiểm FR-20 cần đếm lượt xem đồ thị thì thêm hằng ở story đó, kèm tầng và lý do như bốn hằng của 3.6.

Đường này cũng không gọi LLM hay embedding: một lời gọi kho graph, một hàm thuần. Ca test đếm `llm_cost`/`embedding_cost` bằng 0 trên engine M1.

## Hình dạng, và vì sao nó đóng

Node hyperedge `{id, kind: "hyperedge", level, scope, content_type}` (mức suy như citation qua `core.masking.muc_tiet_lo`, không tra lại bảng), node entity `{id, kind: "entity", label, masked}`, edge `{source, target, slot}`. Không id chunk, không `source_id`, không `description`, không trọng số, không số đếm bị loại. `api.hoi_dap.dung_envelope` kiểm từng node và edge bằng cách dựng lại `adapters.do_thi.DoThi` (id không trùng, cạnh nối hai node có mặt), cùng cách nó kiểm citation. Thứ tự tất định: hyperedge theo thứ tự id vào (đã khử trùng), entity theo thứ tự xuất hiện, edge theo (thứ tự hyperedge, `SLOT_ROLES`, label).

Id không tồn tại, id L0 và id khác space cho cùng một kết quả là vắng mặt, không lỗi, không 404: một mã riêng cho id không tồn tại là cách phân biệt "không có" với "không được thấy" từ ngoài. Danh sách rỗng là đồ thị rỗng hợp lệ và không chạm kho. Trần `SO_ID_TOI_DA = 200` (hơn số 97 đo được ở 3.4) là 400 `DANH_SACH_ID_QUA_DAI` trước khi chạm kho.

## Khoản ledger

Khoản 1.4 "transaction có quản lý" địa chỉ 3-7 đóng bằng bằng chứng: `adapters/neo4j.py::_chay` dùng `execute_read`/`execute_write` và `database=` từ story 2.1 (commit `e082716`), driver giả cố ý không có `run`. Không có việc mới nào cho 3.7 ở đó.
