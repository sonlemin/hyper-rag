# ADR-019 - API xin break-glass: một response cho id vô hình, luật trùng hai tầng, audit trong transaction

**Bối cảnh.** Tech Support thấy dòng hạn chế L1 (`citations[].masked_slots` cộng `owner_group` từ ADR-016) nhưng không có đường chính thức nào để xin đọc phần bị che. Story 5.1 (FR-20) thêm ba tuyến trong `cua_dong`: `POST /break-glass/yeu-cau` tạo yêu cầu cho **một** hyperedge mà vai hiện tại thấy ở mức L1, `POST /break-glass/yeu-cau/{id}/huy` cho người xin hủy khi còn chờ, `GET /break-glass/yeu-cau` liệt kê yêu cầu của chính mình. Trạng thái ở Postgres (`breakglass_requests`, `breakglass_grants` theo ERD, DDL `api/sql/breakglass.sql`), ruột ở `api/break_glass.py`, luật thuần ở `core/break_glass.py`. Duyệt/từ chối/cấp grant là 5.2, `grant_ids` vào ngữ cảnh là 5.3, UI là 5.4/5.5. Ba quyết định dưới đây là chỗ 5.2 và 5.4 đọc luật.

## Quyết định 1 - Một response cho ba id vô hình, mã riêng cho hyperedge đã thấy đủ

Mức tiết lộ của một hyperedge với vai hiện tại hỏi qua **đúng cửa quyền của citation**: `Neo4jACLGraphStorage.trich_dan_cua` (một câu Cypher, ba mệnh đề lọc của `get_node_edges`) cộng `adapters.trich_dan.dung_trich_dan`, gói ở `EngineACL.trich_dan_theo_id(ids) -> dict[str, TrichDan]`. Không mở method đọc mới ở adapter: một method thứ hai là một bản nữa của ba mệnh đề lọc và một dòng nữa trong `MASKED_READ_METHODS`. Hệ quả: "không xin được" và "vắng trong citation" là **cùng một phép kiểm**, nên endpoint xin không nói được gì mà citation chưa nói.

Hyperedge L0, id không tồn tại, id khác space đều **vắng mặt** khỏi dict và ra **một** thân byte-identical 404 `HYPEREDGE_KHONG_XIN_DUOC`, thông điệp cố định, không ghép id vào. Không có truy vấn thứ hai nào để biết id có tồn tại không (AD-14, cùng luật với `/do-thi` ở ADR-018): một mã riêng cho id không tồn tại là cách liệt kê hyperedge từ ngoài. Mỗi ca gửi đúng một câu Cypher và không lời gọi LLM/embedding nào (`tests/test_break_glass.py` đếm bằng driver giả).

Hyperedge mà vai đã thấy L2 là 400 `HYPEREDGE_DA_THAY_DU`: mã riêng vì không rò gì, vai đang đọc được nó đầy đủ, và một 404 ở đây sẽ dạy client rằng hyperedge ấy không có.

Phương án đã loại: *hỏi Neo4j bằng một truy vấn không lọc rồi tự so mức* - đúng đường đọc đi vòng cửa quyền mà Never của 3.6/3.7 cấm.

## Quyết định 2 - Luật trùng hai tầng, và hai cặp khớp khác nhau có chủ đích

**Yêu cầu chờ khớp (`act`, `hyperedge_id`).** Phép kiểm trước insert ở `KhoBreakGlass.tao` cho 409 `YEU_CAU_DANG_CHO` ở ca thường; index duy nhất một phần `(act, hyperedge_id) WHERE trang_thai = 'cho_duyet'` bắt ca hai request chen nhau, `UniqueViolationError` đổi thành **cùng mã**. Cặp không có `role`: một người một thẻ trên hàng chờ của owner, đổi vai không được mở thẻ thứ hai. Yêu cầu đã hủy/duyệt/từ chối không chặn xin lại vì index chỉ phủ hàng đang chờ.

**Grant còn hạn khớp (`act`, `role`, `hyperedge_id`).** `co_grant_con_han` đọc `breakglass_grants` với `expires_at > now()` và `$3 = ANY(hyperedge_ids)`, ra 409 `GRANT_CON_HAN`. Có `role` vì grant bind cặp (5.2), ở vai khác nó ngủ (5.3): một grant đang ngủ không phải lý do để từ chối xin ở vai hiện tại. Grant hết hạn không chặn. Bảng `breakglass_grants` dựng ở 5.1 chỉ để phép kiểm này đứng lên; **không có đường ghi nào** ngoài helper test `tests/ho_tro_break_glass.py::chen_grant`.

Thứ tự kiểm ở `xin`: thân -> ngữ cảnh -> cửa quyền -> grant -> tạo (trong đó có phép kiểm đang chờ). Cửa quyền chạy trước mọi phép đọc Postgres: một id vô hình không đáng một truy vấn bảng yêu cầu.

Mọi trường quyền của hàng (`act`, `role`, `space`) chép từ `PermissionContext` mà `api.hoi_dap.ngu_canh_cua_claim` dựng, không từ thân; thân chỉ có `hyperedge_id` và `ly_do` (`extra="forbid"`, thừa một trường là 400 mà không chạm kho). `k = 0` và `thoi_han_phut = 60` là hằng của `core/break_glass.py`, chép vào từng hàng để người duyệt thấy đúng con số sẽ có hiệu lực. Hủy: chỉ chính `act` (bất kỳ vai nào của tài khoản đó); không có hay của người khác là một thân 404 `YEU_CAU_KHONG_CO`; không còn chờ là 409 `YEU_CAU_KHONG_CON_CHO`. Phép chuyển là `core.break_glass.huy_duoc` cộng `UPDATE ... WHERE trang_thai = 'cho_duyet'` (0 hàng là thất bại), nên hai lần hủy chen nhau không cùng thắng.

## Quyết định 3 - Audit bên trong transaction, hai hằng event tầng mutation

Hai hằng mới ở `core/audit.py`: `breakglass_request` và `breakglass_cancel`, cả hai tầng **mutation** (lý do ghi cạnh hằng). Ghi qua `ghi_bien_doi` với trần `THOI_HAN_BIEN_DOI` (10 giây) **bên trong** transaction Postgres của bảng yêu cầu: thứ tự INSERT/UPDATE -> audit -> COMMIT. Audit hỏng hay quá hạn là rollback và 500 `AUDIT_GHI_HONG`, không hàng nào ở `breakglass_requests`; lần gọi sau khi audit khỏe tạo được. Chiều ngược (audit đã ghi, COMMIT hỏng) để lại một hàng audit nói về một yêu cầu không tồn tại - chấp nhận được, vì sổ ghi *ý định* còn bảng ghi *trạng thái*, và bất biến cần giữ là "không hàng yêu cầu nào thiếu hàng audit".

Hàng audit mang `space`/`act`/`role` của ngữ cảnh, `hyperedge_ids = (hyperedge_id,)`, `chi_tiet = {request_id, trang_thai, k, thoi_han_phut, nhom_duyet}`. `request_id` ở đây là **id của yêu cầu break-glass** (`bg-` + 12 hex), không phải id một lượt hỏi - đường này không có lượt, và 5.2 nối hàng duyệt với hàng xin bằng đúng khóa này. **Không `ly_do`**: nội dung tự do của người dùng ở bảng, sổ audit chỉ giữ dấu vết. Hàng `breakglass_request` là hàng duy nhất của lượt: không `query`, không `refusal`, không `llm_cost`/`embedding_cost`.

Phương án đã loại: *ghi bảng rồi audit sau, ngoài transaction* - một Postgres audit chết để lại hàng chờ không dấu vết, đúng thứ FR-20 sinh ra để thay; và *nuốt lỗi audit thành WARNING* - đó là tầng observation, dành cho số liệu đo chứ không cho một thao tác đổi quyền.

## Hình dạng, và vì sao nó đóng

Thân 201 và thân của hủy/danh sách là cùng một serializer `dict_yeu_cau`, 14 khóa đóng theo thứ tự: `id` · `act` · `role` · `space` · `hyperedge_id` · `scope` · `content_type` · `nhom_duyet` · `trang_thai` · `k` · `thoi_han_phut` · `ly_do` · `tao_luc` · `cap_nhat`. Không `ly_do_tu_choi`/`xu_ly_boi` (cột có, 5.2 điền và trả). `GET` trả `{"yeu_cau": [...]}` mới nhất trước, chỉ của `act` trong token, tối đa `SO_YEU_CAU_TOI_DA = 100`. Lỗi kho là 503 `KHO_KHONG_SAN_SANG` cho cả Neo4j (qua `api.hoi_dap.loi_truy_hoi`) lẫn Postgres (`api.break_glass.loi_kho`, nhận diện theo gốc module `asyncpg` và lỗi socket), không envelope AD-8 vì đây là tài nguyên chứ không phải lượt hỏi. Bảng nhóm không khai loại nội dung là 500 `NHOM_DUYET_KHONG_CO`, cấu hình hỏng chứ không phải lỗi người gọi.

Ask First còn mở cho story sau: thêm trường vào thân (k, thời hạn, danh sách id), endpoint đọc cho owner hay trạng thái nhẹ (5.2/5.4), đổi lược đồ hai bảng sau khi 5.2 đứng lên.

## Giới hạn đã biết

- **Một request giữ một kết nối pool suốt lúc chờ audit.** Audit ghi bên trong transaction của bảng yêu cầu, nên kết nối bị giữ tối đa `THOI_HAN_BIEN_DOI` (10 giây); pool tối đa 4. Chấp nhận: xin break-glass là thao tác hiếm. `acquire` trong `tao`/`huy` có hạn bằng chính trần đó, nên pool cạn là một lỗi kho ra 503 `KHO_KHONG_SAN_SANG` chứ không phải một request treo.
- **`GET /break-glass/yeu-cau` trả `scope`/`content_type`/`nhom_duyet` của yêu cầu cũ mà không kiểm lại bảng chính sách hiện hành.** Chấp nhận: ba trường đó đã hiện với vai ấy ở thời điểm xin (chúng là khóa quyền của một hyperedge vai thấy ở L1 và tên nhóm đã ra qua `owner_group`), và hàng là của chính người xin. Hoán bảng sau đó không thu hồi được thông tin đã trả.
- **Cặp (`act`, `role`) là ảnh chụp lúc xin, không đối chiếu lại với seed.** Một tài khoản đổi vai sau đó vẫn có yêu cầu mang vai cũ trên hàng chờ; 5.2 cấp grant cho đúng cặp đã ghi, và ở vai mới grant ấy ngủ (5.3). Hủy so cả `space` của ngữ cảnh, nên yêu cầu của space cũ không hủy được từ token của space mới.
- **Một hàng audit có thể tồn tại cho một yêu cầu đã rollback.** Thứ tự INSERT -> audit -> COMMIT chỉ bảo đảm chiều "không hàng yêu cầu nào thiếu hàng audit"; COMMIT hỏng sau khi audit đã ghi để lại một hàng `breakglass_request` không có yêu cầu tương ứng. Chấp nhận: sổ ghi ý định, bảng ghi trạng thái; hậu kiểm đối chiếu bằng `chi_tiet.request_id`.
- **Chuỗi kiểm đầu vào là trần cứng, không phải lược đồ id.** `hyperedge_id` tối đa `DAI_ID_TOI_DA` = 200 ký tự, `ly_do` tối đa 1000 sau strip (pydantic chặn trước ở 4000), ký tự NUL bị từ chối ở cả hai; id hủy phải mang tiền tố `bg-` mới chạm kho. Không kiểm định dạng id hyperedge sâu hơn: fixture M1 và id `he-` + 24 hex của kho thật là hai lược đồ khác nhau.

## Quyết định 4 - Một nguồn giờ cho `expires_at`: giờ của Postgres

Phép kiểm "grant còn hạn" (`_SQL_GRANT_CON_HAN`) so `expires_at > now()` bằng đồng hồ của Postgres. Chốt ngay ở 5.1, trước khi 5.2 viết dòng ghi đầu tiên: `expires_at` phải do **cùng đồng hồ đó** sinh ra, tức 5.2 ghi `now() + make_interval(mins => $n)` ngay trong câu INSERT, không tính `datetime.now()` ở tiến trình `api` rồi truyền vào. Hai đồng hồ (container `api` và container `postgres`) hôm nay lệch mili giây vì cùng một máy, nhưng luật "ghi và đọc cùng nguồn giờ" là thứ phải đứng trước con số đo được. Phương án đã loại: truyền giờ của `api` vào cả hai câu - nó buộc mọi đường đọc grant sau này (5.3, hàng chờ 5.5) nhớ truyền cùng một tham số, còn `now()` của Postgres thì không ai quên được. Luật ghi ở comment của `api/sql/breakglass.sql` ngay trên bảng `breakglass_grants`.

## Điều đã thấy khi viết test trên fixture M1

Trên `policy-day-du.yaml`, `tech_support` thấy HE-02 ở L1 còn `devops` thấy HE-02 ở L2 và HE-03 ở L1. Vì vậy câu "ts01 xin HE-02 rồi dev01 xin HE-02, hai yêu cầu độc lập" của AC-1 chấm trên fixture thành: `ts01` xin HE-02 được 201, `dev01` xin HE-02 là 400 `HYPEREDGE_DA_THAY_DU` (đúng vế "không id nào ngoài tập L1 tạo được"), và yêu cầu độc lập thứ hai là của `dev01` cho HE-03. Tập id xin được của mỗi vai bằng đúng `{h : muc_ky_vong(bang, vai, loại) == "L1"}`.
