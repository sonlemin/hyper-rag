# Deferred work

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-dung-stack-docker-va-truy-van-dau-tien.md`
  summary: Ghim tag image ollama cụ thể (hiện `OLLAMA_TAG=latest`) khi bật profile `local-llm` lần đầu.
  evidence: Mọi image khác đều ghim chặt phiên bản; profile local-llm chưa từng chạy ở story 1.1 nên chưa có cơ sở kiểm chứng tag nào, ghim mù còn rủi ro hơn.
  resolved: 2026-08-31 - ghim `OLLAMA_TAG=0.33.2` (bản stable mới nhất trên Docker Hub, trùng `latest` tại thời điểm ghim) trong `.env.server`, `.env.laptop` và default của compose. Chưa pull/chạy profile; kiểm chứng thật khi bật local-llm lần đầu.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-dung-stack-docker-va-truy-van-dau-tien.md`
  summary: Chốt cách phơi cổng 8000 (bind 127.0.0.1 + reverse proxy, hoặc quy tắc UFW) trước khi API trả dữ liệu thật.
  evidence: Compose đang bind `8000:8000` trên máy chủ công cộng; story 1.1 chỉ có `/health` nên chấp nhận được, nhưng từ Epic 3 (JWT, dữ liệu thật) cần quyết định tường minh.
  resolved: 2026-08-31 - quyết định ghi vào chú thích trong `docker-compose.yml` (service api): 8000 publish công khai có chủ đích cho demo; từ Epic 3 mọi endpoint dữ liệu bắt buộc JWT; DB và ollama không bao giờ publish; không dựa UFW (Docker publish đi vòng qua UFW); muốn siết thêm sau khi có web thì đổi sang `127.0.0.1:8000:8000` + reverse proxy một mối.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-dung-stack-docker-va-truy-van-dau-tien.md`
  summary: Thêm test import-lint canh chiều import (core/ chỉ stdlib, không import ngược) khi core/ có nội dung ở story 1.2.
  evidence: Epic-1 context ghi "Test import-lint chạy CI" nhưng story 1.1 core/ còn rỗng, luật mới nằm trong docstring, chưa có gì canh giữ.
  resolved: 2026-08-31 - thêm `tests/test_import_lint.py` (quét AST: core chỉ stdlib; adapters/api/redteam không import ngược), chạy CI từ giờ; story 1.2 thêm code core là bị canh ngay.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Kiểm contextvar quyền có sống qua pipeline async thật của upstream (`HyperGraphRAG.aquery`), không chỉ qua task asyncio dựng tay.
  evidence: `tests/test_ngu_canh_quyen.py` chứng minh hai task async không lẫn context, nhưng story 1.2 chưa có adapter nào để chạy qua engine upstream. Spine Deferred ghi sẵn đường lùi (engine per-request, bind context vào instance adapter) nếu contextvar đứt qua executor; điểm kiểm tự nhiên là story 1.3 khi adapter Qdrant đầu tiên gọi được từ `aquery`.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Danh sách trắng `CHO_PHEP_SYSTEM_CONTEXT` trong `tests/test_import_lint.py` còn rỗng; story ingest phải thêm đúng một dòng, và test tầng handler từ chối ngữ cảnh hệ thống trên đường truy vấn người dùng thuộc Epic 3.
  evidence: AD-3 và NFR-10 chia trách nhiệm làm hai: import-lint canh phía module (đã có ở story này), còn việc từ chối `kind=system` trên đường truy vấn đặt ở tầng handler API, nơi story 1.2 cố ý không chạm tới.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Nối `adapters/policy_loader.py` vào runtime API - `api/Dockerfile` chưa COPY `config/`, và chưa có biến môi trường trỏ đường dẫn file policy mặc định.
  resolved: 2026-09-01 (một phần) - `api/Dockerfile` COPY `config/`; đã build image trên máy chủ và chạy `load_policy("config/policy-toi-gian.yaml")` trong container, trả đúng hai vai và `policy_version`. Phần còn treo là biến môi trường trỏ file policy mặc định: chọn bảng nào là quyết định của Epic 3 (bốn cấu hình đo của story 3.2), không phải của tầng đóng gói.
  evidence: Review story 1.2 chỉ ra loader chạy trong container sẽ không tìm thấy `config/policy-*.yaml`. Story 1.2 cố ý không chạm handler hay endpoint (Never của spec), nhưng Epic 3 dựng ngữ cảnh quyền ở đầu request thì phải có đường nạp policy thật.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Chặn `use_context` lồng nhau đưa ngữ cảnh hệ thống vào giữa một request người dùng.
  resolved: 2026-09-01 - `use_context` từ chối mở ngữ cảnh hệ thống khi đang ở trong ngữ cảnh vai (`SystemContextNested`, code `SYSTEM_CONTEXT_NESTED`); chiều ngược lại vẫn được vì nó thu hẹp quyền. Diff `core/` đã trình sonlm. Việc từ chối `kind=system` *đến từ ngoài* trên đường truy vấn vẫn thuộc tầng handler Epic 3 - hai lớp khác nhau, không thay thế nhau.
  evidence: `use_context(system_context(...))` lồng trong ngữ cảnh vai hiện không có gì cản, là đường leo quyền im lặng. NFR-10 giao việc từ chối `kind=system` trên đường truy vấn cho tầng handler API, nên chốt ở Epic 3 cùng test tầng handler.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Tripwire buộc story 1.6 phải chạm ruột hàm che, tránh CI xanh trong khi `mask()` vẫn no-op sau khi adapter đã gọi nó.
  resolved: 2026-09-01 - `test_tripwire_ruot_ham_che_phai_thay_that` trong `tests/test_che_stub.py`, đánh `xfail(strict=True)`: hôm nay nó xfail vì `mask` còn là stub, và khi story 1.6 viết ruột thật nó XPASS - `strict=True` biến XPASS thành đỏ, buộc 1.6 gỡ marker. Kỳ vọng lấy từ oracle nên nó không tự đúng theo code.
  evidence: Từ story 1.3 adapter gọi `mask()` trong đường trả về; stub trả nguyên trạng nên suite vẫn xanh dù không che gì. `test_grant_rong_tra_nguyen_trang` khóa hình dạng chứ không khóa hành vi.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Test phản chiếu cho các method đọc ngoài danh sách đóng (`node_degree`, `edge_degree`, `has_node`, `has_edge`) - hiện chỉ được giải thích trong comment.
  resolved: 2026-09-01 - `tests/test_phan_chieu_che.py` quét *mọi* method public của từng adapter (không chỉ method override interface, vì ca nguy hiểm nhất là một method đọc mới toanh) và bắt buộc mỗi cái nằm trong đúng một nhóm: phải che, xử lý riêng kèm lý do, ghi, vòng đời, hoặc ngoài hợp đồng. Thêm nhóm assert rằng method trong danh sách đóng thật sự có đường tới `mask`. Story 1.5 thêm một dòng cho adapter KV.
  evidence: AD-9 giao test phản chiếu phủ cả 3 adapter cho story 1.7, nhưng cách xử lý riêng của 4 method này chưa có gì ghim, story 1.3-1.5 dễ bỏ quên.
  tien_do: 2026-09-01 - story 1.4 ghim hành vi của cả 4 method trên adapter graph (`tests/test_adapter_neo4j.py`: degree co theo quyền, `has_*` trả False ngoài quyền), kèm bản chạy trên Neo4j thật. Phần còn treo là test *phản chiếu* phủ cả 3 adapter, chỉ viết được khi adapter KV của story 1.5 tồn tại; địa chỉ vẫn là story 1.7.
  resolved: 2026-09-01 - story 1.5 đóng nốt: `JsonACLKVStorage` vào `CAC_ADAPTER` nên test phản chiếu chạy trên đủ ba adapter, và `all_keys`/`filter_keys` của đường KV được khai vào `XU_LY_RIENG` kèm câu nói cơ chế quyền thay thế (lọc theo tập khóa, mục ngoài quyền tính là chưa tồn tại). Không còn phần treo cho story 1.7.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Gọi `QdrantVectorDBStorage.initialize()` ở bước khởi động engine (story 1.7), và tiêm một `AsyncQdrantClient` dùng chung cho cả ba namespace vector.
  evidence: Upstream không có hook khởi tạo storage nào chạy trước lần upsert đầu (`index_done_callback` chạy sau), nên collection và payload index phải do phía mình gọi. Story 1.3 cố ý không nối vào `HyperGraphRAG` (Never của spec); chưa ai gọi `initialize()` thì upsert thật sẽ dừng ở `QdrantIndexMissing` - đúng thiết kế, nhưng phải có chỗ gọi.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Chạy lại đúng cặp assert của `tests/test_adapter_qdrant.py` trên Qdrant thật (container) ở cổng M1 story 1.7.
  resolved: 2026-09-01 - `tests/test_adapter_qdrant_that.py` (marker `qdrant`) chạy trên Qdrant 1.19.0 của compose: payload index keyword + `is_tenant`, `hnsw_config` m=16/payload_m=16, strict mode bật với `filter_max_conditions=1`, upsert bị từ chối khi chưa `initialize()`, hai vai ra hai tập khóa và hai kết quả đúng oracle, và filter hai điều kiện bị server từ chối. `QdrantGhiLai.noi_toi()` bọc client thật và tắt sổ index giả. Hook CI chạy cả hai bộ marker sau bộ chính.
  evidence: Local mode duyệt vét cạn và bỏ qua payload index, nên nó chứng minh được ngữ nghĩa lọc chứ không chứng minh được pre-filter chạy trong HNSW có index. Lớp bọc `tests/gia_lap_qdrant.py` bù phần `payload_schema` cho nhánh kiểm index; phần còn lại chỉ Qdrant thật mới trả lời được.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Khoản nợ "kiểm contextvar quyền sống qua pipeline async thật của upstream" chuyển điểm kiểm từ story 1.3 sang story 1.7.
  evidence: Ledger ghi điểm kiểm tự nhiên là 1.3, nhưng spec 1.3 cấm nối adapter vào `HyperGraphRAG` (việc đó thuộc 1.7). Story 1.3 chỉ kiểm được contextvar qua `asyncio.gather` do adapter tự phát lúc embed theo lô, chưa đi qua `aquery`.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Chốt `hnsw_config` (`payload_m`, `m`) lúc tạo collection, hoặc ghi rõ là khoản kiểm ở cổng M1, để cạnh HNSW theo tenant thật sự được dựng.
  evidence: `initialize()` chỉ đặt `VectorParams` cộng payload index `is_tenant=True`. Toàn bộ lý do của AD-4 và của `QdrantIndexMissing` là "extra HNSW edge chỉ dựng cho field đã có index lúc build", nhưng chưa có tham số nào bật đường đó, nên cửa chặn ghi-trước-index đang bảo vệ một cơ chế chưa được cấu hình. Chỉ Qdrant thật mới kiểm được.
  resolved: 2026-09-01 - `initialize()` truyền `hnsw_config=HnswConfigDiff(payload_m=16, m=16)`. Giữ `m` khác 0 có chủ đích: khuyến nghị `m=0` của hướng dẫn tenant chỉ đúng khi mọi truy vấn đều có filter tenant, còn ngữ cảnh hệ thống ở đây đọc thô không filter nên tắt index toàn cục là biến đường ingest thành full scan. Lý do nằm trong comment cạnh hai hằng. Local mode nhận rồi bỏ qua, nên đã kiểm riêng trên Qdrant 1.19.0 thật ngày 2026-09-01: `get_collection().config.hnsw_config` trả về đúng `m=16 payload_m=16`, tức cạnh HNSW theo khóa quyền thật sự được dựng và cửa `QdrantIndexMissing` không còn canh một cơ chế chưa bật.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Guardrail `filter_max_conditions` (strict mode Qdrant) trong PRD addendum chưa có chỗ nào cấu hình.
  evidence: Addendum chốt nó là hàng rào phía server chống filter đa điều kiện. Hiện chỉ có quy ước trong code adapter và helper assert `khoa_trong_filter` trong test; không có gì phía server ngăn một đường code tương lai gửi filter hai điều kiện.
  resolved: 2026-09-01 - `initialize()` truyền `strict_mode_config` với `enabled=True`, `filter_max_conditions=1`, `unindexed_filtering_retrieve=False`, `unindexed_filtering_update=False`. Comment ghi rõ Epic 5 (break-glass) nếu cần filter hai điều kiện thì phải nới chỗ này có chủ đích. Đã kiểm trên Qdrant 1.19.0 thật ngày 2026-09-01, và hai luật fire độc lập nhau: filter hai điều kiện *cùng đặt trên field đã index* vẫn bị từ chối 400 (đó là `filter_max_conditions`), còn filter trên field chưa index bị từ chối với thông điệp `Index required but not found` (đó là `unindexed_filtering_retrieve`). Lần kiểm đầu chỉ dùng field chưa index nên cả hai ca đều rơi vào luật thứ hai và chưa chứng minh được luật thứ nhất.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Thiếu hàm nghịch đảo của `filter_key` trong `core/keys.py` để tách `content_type` ra khỏi khóa.
  evidence: `mask()` nhận khóa dạng `{scope}:{content_type}` nhưng `PermissionContext.slots_to_mask()` tra theo `content_type`. Story 1.6 và adapter Neo4j sẽ mỗi nơi tự tách chuỗi một kiểu, đúng thứ mà lý do của `FILTER_KEY_FIELD` (một hằng, hai kho đọc chung) muốn tránh.
  resolved: 2026-09-01 - thêm `core.keys.split_key(key) -> (scope, content_type)`, kiểm bằng cách dựng lại khóa từ hai nửa vừa tách nên chuỗi không do `filter_key` sinh ra là `ValueError`; sai kiểu là `TypeError`, cùng luật với `filter_key`. Test đối xứng trong `tests/test_chinh_sach.py` gồm ca vòng tròn trên dữ liệu fixture.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Chốt hợp đồng của `mask` khi nó muốn loại hẳn một bản ghi, và cách bù khi che chạy sau `limit=top_k`.
  evidence: `query` gói thẳng kết quả vào list. Nếu ruột thật ở story 1.6 trả `None` hoặc dict rỗng để bỏ một mục thì `operate.py:944` nổ ở `r["hyperedge_name"]`. Che chạy sau khi đã cắt `top_k` cũng làm số kết quả thực dụng tụt mà không ai biết.
  resolved: 2026-09-01 - `_ban_ghi` ném `MaskContractViolated` khi `mask` trả giá trị rỗng, kèm thông điệp nói rõ đường đúng là `query` lọc mục đó khỏi list. Docstring `query` ghi thêm rằng che chạy sau `limit=top_k` nên số kết quả thực dụng có thể tụt dưới `top_k`, và đó là hành vi chấp nhận ở M1 (xin dư rồi cắt là đổi ngữ nghĩa `top_k` với upstream, cần quyết định riêng).

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: `space` chưa được kiểm ký tự trước khi vào tên collection và nhãn Neo4j.
  evidence: `user_context` chỉ kiểm chuỗi không rỗng, còn `_ten_collection` ghép thẳng `{space}_{namespace}`. Space chứa khoảng trắng hay ký tự lạ tạo tên collection hỏng hoặc trỏ sai. Cách ly theo space là chiều cách ly dữ liệu của AD-12 nên nơi kiểm đúng là `core/`, cùng chỗ với factory ngữ cảnh.
  resolved: 2026-09-01 - thêm `core.ids.validate_space`, gọi từ cả `user_context` lẫn `system_context`. Tập hợp lệ: chữ cái mở đầu rồi chữ/số/gạch dưới, tối đa 64 ký tự - đủ cho quy ước đang dùng (`synth`, `test_<hex>_synth`) và an toàn ở cả tên collection Qdrant lẫn nhãn Neo4j không cần dấu nháy ngược.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Hai khóa cấu hình `qdrant_url` và `qdrant_api_key` chưa có nơi nào sinh ra; `QDRANT_URL` trong compose chưa được map vào `global_config`.
  evidence: Hai khóa chỉ xuất hiện trong chính `adapters/qdrant.py`. Chưa có subclass `HyperGraphRAG` nào thêm hai trường đó vào `asdict(self)`, nên nhánh dựng client thật chưa nối được với biến môi trường `docker-compose.yml:72`. Thuộc bước dựng engine story 1.7.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Lô upsert gửi trong đúng một request kèm `wait=True`, chưa chia lô phía tải lên.
  evidence: Embedding có chia lô theo `embedding_batch_num`, phần đẩy point lên Qdrant thì không. Với corpus 40 tài liệu của khóa luận thì chấp nhận được, nhưng nên là một quyết định được viết ra chứ không phải mặc định ngẫu nhiên.
  resolved: 2026-09-01 - phần tải lên chia theo cùng `embedding_batch_num` với phần embedding. Ba cửa vẫn kiểm hết trước khi ghi point đầu tiên nên ngữ nghĩa từ chối cả lô giữ nguyên; đứt giữa chừng thì chạy lại ghi đè đúng chỗ cũ vì point id là UUID5 của id upstream.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Hành vi last-write-wins của khóa đa nguồn chưa có test đặc tả, nên story 2.1 sẽ không biết mình đang đổi cái gì.
  evidence: `point_id` là UUID5 của id upstream, nên một entity xuất hiện ở hai tài liệu khác scope bị ghi đè khóa theo tài liệu nạp sau. Docstring `adapters/ingest_labels.py` thừa nhận và trỏ sang story 2.1, nhưng không có test nào ghim hành vi hiện tại làm mốc so sánh.
  resolved: 2026-09-01 - `test_dac_ta_hien_trang_khoa_da_nguon_last_write_wins` ghim hiện trạng: cùng một id upstream nạp dưới hai `ingest_label` khác scope cho ra một point mang khóa của lần ghi sau. Docstring nói rõ đây là đặc tả hiện trạng làm mốc so sánh, không phải khẳng định hành vi đúng, và trỏ story 2.1.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: `_bat_buoc_co_index` gọi hai round-trip (`collection_exists` + `get_collection`) cho mỗi lô upsert trên đường nóng.
  evidence: Ingest của upstream đi theo nhiều lô nhỏ nên chi phí này lặp lại liên tục. Có thể nhớ kết quả sau lần đầu thành công kèm đường vô hiệu hóa khi đổi collection, nhưng phải đo trên Qdrant thật mới biết có đáng không. Địa chỉ là story 2.3 (pipeline ingest tuần tự): đó là lần đầu có một khối lượng nạp thật để đo, trước đó mọi con số đều là suy đoán.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Vòng đời kết nối Qdrant - khi không tiêm sẵn client, mỗi instance adapter tự mở một `AsyncQdrantClient` riêng và không có chỗ nào gọi `close()`.
  evidence: Review story 1.3 chỉ ra comment của field `qdrant_client` hứa "ba namespace dùng chung một kết nối" trong khi nhánh không tiêm thì mở ba kết nối. Comment đã sửa cho khớp code; việc tiêm một client dùng chung và đóng nó lúc tắt tiến trình thuộc story 1.7, cùng chỗ gọi `initialize()`.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Epic 5 (break-glass) sẽ bị `filter_max_conditions=1` của strict mode chặn nếu đường truy vấn phụ cần lọc theo cả khóa quyền lẫn grant.
  evidence: Đã kiểm trên Qdrant thật ngày 2026-09-01: filter hai điều kiện bị từ chối 400 kể cả khi cả hai đều đặt trên field đã có index. Đây là hàng rào cố ý cho NFR-06, nhưng story 5.3 (đường truy vấn phụ theo grant) phải quyết tường minh là nới `filter_max_conditions` hay gộp grant vào chính khóa quyền. Gộp vào khóa giữ được luật một field và là hướng nên xét trước.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: Cạnh graph chưa có nguồn cấp vai slot: `upsert_edge` chấp nhận cạnh thiếu `slot`, chờ prompt trích xuất 8 vai của story 2.4.
  evidence: `_merge_edges_then_upsert` của upstream chỉ gửi `weight` và `source_id`. Cấm cạnh thiếu vai ngay bây giờ là chặn chính đường e2e của cổng M1, nên story 1.4 chỉ kiểm vai khi có khai. Hệ quả cần story 2.4 quyết tường minh: sau khi trích xuất gắn đủ 8 vai thì cạnh thiếu `slot` có thành lỗi không, và tầng che xử thế nào với cạnh chưa có vai. `test_canh_khong_khai_vai_van_ghi_duoc` ghim hiện trạng làm mốc so sánh.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: Năm khóa cấu hình `neo4j_uri`, `neo4j_username`, `neo4j_password`, `neo4j_health_retries`, `neo4j_health_delay` chưa có nơi nào sinh ra; gọi `initialize()` lúc khởi động và đóng driver lúc tắt cũng chưa có chỗ.
  evidence: Cùng hình dạng với khoản nợ của adapter Qdrant. Ba khóa chỉ xuất hiện trong chính `adapters/neo4j.py`; biến `NEO4J_URI/USERNAME/PASSWORD` mới chỉ có trong env của service `api` (`docker-compose.yml:66-70`), chưa subclass `HyperGraphRAG` nào đưa chúng vào `asdict(self)`. `Neo4jACLGraphStorage.close()` đã có (và cố ý không đóng driver được tiêm từ ngoài) nhưng chưa ai gọi. Tất cả thuộc bước dựng engine story 1.7.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: Khóa của node entity trong graph cũng là last-write-wins như point Qdrant; hai kho lệch nhau khi một entity xuất hiện ở nhiều tài liệu khác scope.
  evidence: `upsert_node` ghi `filter_key` từ nhãn ingest đang mở, nên entity nạp lần sau đè khóa của lần trước - cùng cơ chế và cùng khoản nợ "hợp nhất khóa đa nguồn" của story 2.1. Story 1.4 để nguyên và dùng chính hành vi này trong `test_node_degree_co_theo_quyen` (nạp HE-01 sau cùng để khóa của `App01` là runbook), nên story 2.1 đổi luật hợp nhất thì phải sửa cả setup của test đó.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: Cả hai adapter cho phép ghi dưới ngữ cảnh vai người dùng, không chỉ dưới ngữ cảnh hệ thống của ingest.
  resolved: 2026-09-01 - `adapters/ingest_labels.ingest_key_for_write()` là cửa chung của cả hai đường ghi: sai ngữ cảnh là `IngestOutsideSystemContext` (code `INGEST_OUTSIDE_SYSTEM_CONTEXT`). `current_ingest_key()` giữ nguyên nghĩa "nhãn nào đang mở" cho fixture canh rò nhãn. Có test ở cả hai adapter.
  evidence: `upsert_node`/`upsert_edge` (graph) và `upsert` (vector) chỉ đòi có ngữ cảnh cộng nhãn ingest đang mở; một ngữ cảnh vai cũng qua được, và khi đó `space` lấy theo ngữ cảnh đó. AD-3 nói ingest chạy dưới ngữ cảnh hệ thống tường minh, nhưng chưa chỗ nào ép. Chốt một luật cho *cả hai* adapter cùng lúc (thêm cửa `bypass_filter` ở đường ghi, hoặc quyết định tường minh là không thêm) thuộc story 2.3 khi pipeline ingest thật ra đời; sửa lệch một adapter là tạo ra hai luật.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: Cạnh graph định danh theo cặp (hyperedge, entity), chưa tính vai slot; một entity điền hai vai của cùng một hyperedge thì vai ghi sau đè vai ghi trước.
  evidence: `MERGE (a)-[r:SLOT]->(b)` không mang `slot` trong pattern. Đưa `slot` vào khóa MERGE sẽ tách thành nhiều cạnh cho cùng một cặp, và như vậy `node_degree` đếm khác ngữ nghĩa của `NetworkXStorage` upstream - một quyết định phải cân cùng lúc với lúc trích xuất thật sự gắn đủ 8 vai (story 2.4), không phải sửa lẻ ở adapter.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: Không có ràng buộc duy nhất trên `id` trong một `space`: cùng một id ghi một lần dưới vai hyperedge và một lần dưới vai entity sẽ thành hai node.
  evidence: `MERGE (n:{space}:{nhan} {id: $id})` khóa theo *cả* nhãn, nên hai nhãn khác nhau là hai node. Khi đó `get_node` (LIMIT 1) trả node nào là không xác định và `node_degree` gộp cạnh của cả hai. Neo4j Community có `CREATE CONSTRAINT ... REQUIRE n.id IS UNIQUE`, nhưng spec story 1.4 chốt "không index/constraint ngoài một index đủ cho đường lọc", nên việc thêm ràng buộc (và quyết định nó nên nổ hay nên gộp) thuộc bước dựng engine story 1.7.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: `delete_node` của `BaseGraphStorage` chưa override nên dội `NotImplementedError` trần của upstream, không có mã lỗi của dự án.
  evidence: `vendor/hypergraphrag/hypergraphrag.py:530` có gọi `delete_node`. Story 1.4 cố ý không làm đường xóa (Never của spec) vì chưa story nào cần, nhưng khi Epic 2 nạp lại corpus thì xóa theo `space` sẽ cần một đường có kiểm quyền và có mã lỗi ổn định.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-adapter-neo4j-voi-where-injection-va-cau-truc-hai-phia.md`
  summary: Adapter graph dùng session autocommit cho từng câu, không dùng transaction có quản lý, không truyền `database=`, và health-check chỉ chạy một lần cho mỗi instance.
  evidence: `_chay` mở `driver.session()` rồi `session.run` cho mỗi câu, nên không có retry của driver cho lỗi thoáng qua (`TransientError`, đổi leader). Neo4j Community chỉ có một database nên `database=` chưa cần, nhưng nó là mặc định ngầm. Neo4j restart giữa phiên thì `_da_san_sang` vẫn True và mọi lời gọi sau đó dội lỗi driver thô. Ba thứ này cùng thuộc vòng đời kết nối của story 1.7.
  tien_do: 2026-09-01 - phần health-check đã tự mở lại: `_chay` bắt `ServiceUnavailable`, đặt lại cờ sẵn sàng rồi ném tiếp (lời gọi này vẫn hỏng - thử lại ngay tại chỗ là giấu mất một sự cố thật), nên lời gọi sau chờ Neo4j lên thay vì dội lỗi driver thô mãi. Transaction có quản lý và `database=` vẫn treo ở 1.7.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-adapter-kv-va-tat-cache-llm.md`
  summary: Adapter KV chưa có nơi nào đăng ký; `working_dir` và hằng `ENABLE_LLM_CACHE` chưa ai đọc, và chưa có chỗ gọi `index_done_callback()` lúc tắt tiến trình.
  evidence: Cùng hình dạng với khoản nợ cấu hình của hai adapter kia. `JsonACLKVStorage` chỉ xuất hiện trong chính `adapters/kv.py` và trong test; upstream resolve KV qua cùng registry `_get_storage_class()` mà story 1.5 cố ý không mở. Dữ liệu chỉ xuống đĩa ở `index_done_callback`, nên tiến trình tắt giữa chừng là mất phần chưa flush. Tất cả thuộc bước dựng engine story 1.7.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-adapter-kv-va-tat-cache-llm.md`
  summary: Bằng chứng "cache LLM tắt" hiện đi qua monkeypatch `hypergraphrag.hypergraphrag.JsonKVStorage`, chưa đi qua cơ chế đăng ký thật là override `_get_storage_class()`.
  evidence: Test hiện tại chứng minh đúng thứ cần chứng minh - lớp hai nổ ngay trong `HyperGraphRAG.__post_init__` khi cờ còn bật - nhưng nó vá một tên module thay vì đi đường mà sản phẩm sẽ đi. Spec 1.5 cấm chạm `_get_storage_class()` vì đó là việc của 1.7; khi 1.7 dựng subclass thật thì cùng assert đó phải chạy lại trên cơ chế thật.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-adapter-kv-va-tat-cache-llm.md`
  summary: Chunk id của upstream là md5 nội dung, nên hai tài liệu khác `scope` có đoạn trùng nội dung sinh cùng một id; ngữ nghĩa chỉ-chèn của `upsert` giữ nhãn của lần nạp *đầu*, có thể là nhãn rộng hơn.
  evidence: `compute_mdhash_id(content)` không mang `scope`. Đây là ca ngược của khoản nợ last-write-wins ở đường vector và đường graph (khóa của lần ghi *sau* thắng), nên hai kho có thể lệch nhau ngay trong cùng một đợt nạp. Cùng địa chỉ với "hợp nhất khóa đa nguồn" của story 2.1; story 1.5 chỉ ghim hiện trạng bằng test đặc tả làm mốc so sánh.
  tien_do: 2026-09-01 - `test_dac_ta_hien_trang_cung_id_hai_nhan_first_write_wins` ghim hiện trạng: nạp `chunk-trung` dưới `noi_bo:runbook` rồi nạp lại dưới `khach_hang_a:bao_cao_su_co` cho ra một bản ghi giữ nhãn *rộng* của lần đầu, và `tech_support` vẫn đọc được nó. Phần còn treo là luật hợp nhất, vẫn ở story 2.1.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-adapter-kv-va-tat-cache-llm.md`
  summary: Hai tiến trình cùng ghi một file kho KV thì bản ghi của người ghi trước biến mất; `index_done_callback` ghi đè cả file thay vì hợp nhất với bản trên đĩa.
  evidence: Mỗi instance giữ `_kho` nạp lười của riêng nó, nên hai instance (hai tiến trình, hoặc engine per-request của đường lùi trong spine) cùng flush một `space` là mất dữ liệu im lặng. Ghi nguyên tử (file tạm rồi `replace`) chặn được ca đứt giữa chừng nhưng không chặn ca hai người ghi. Quyết định (khóa file, hợp nhất trước khi ghi, hay một tiến trình ingest duy nhất) thuộc vòng đời kết nối của story 1.7.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-adapter-kv-va-tat-cache-llm.md`
  summary: `_tra` sao chép bản ghi một tầng trước khi gọi tầng che; ruột che thật của story 1.6 mà biến đổi một giá trị lồng nhau sẽ ghi ngược vào kho trong bộ nhớ.
  evidence: Hôm nay không chạm tới được: bản ghi chunk của upstream chỉ có trường vô hướng (`tokens`, `content`, `full_doc_id`, `chunk_order_index`), và `mask` còn là stub trả nguyên trạng. Nhưng "kết quả đã che rò ngược vào kho" là một mặt fail-open thật, và nó chỉ mở ra đúng lúc story 1.6 viết ruột che - đó cũng là chỗ quyết định sao chép sâu hay chốt rằng tầng che không được biến đổi tại chỗ.
  tien_do: 2026-09-01 - `test_tripwire_ket_qua_da_che_khong_duoc_ro_nguoc_vao_kho` đánh `xfail(strict=True)`: hôm nay nó đỏ thật (dấu che của `tech_support` nằm lại trong kho, ngữ cảnh hệ thống đọc sau thấy `***`), nên khoản nợ không còn chỉ nằm trong ledger. Story 1.6 chọn xong đường nào thì test xanh và `strict=True` buộc gỡ marker.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-adapter-kv-va-tat-cache-llm.md`
  summary: Adapter KV đọc và ghi file bằng `read_text`/`write_text` đồng bộ ngay trong method async.
  evidence: Kho KV của upstream vốn là file JSON và corpus khóa luận nhỏ (40 tài liệu), nên ở M1 việc này chấp nhận được và đã ghi thành một câu trong docstring. Luật "async toàn tuyến" của AGENTS.md nói về driver kho, nhưng lần `get_by_id` đầu tiên của một truy vấn vẫn nạp cả file và chặn event loop. Đo lại rồi quyết `asyncio.to_thread` hay giữ nguyên khi corpus thật vào kho, Epic 2.
