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
  evidence: Review story 1.2 chỉ ra loader chạy trong container sẽ không tìm thấy `config/policy-*.yaml`. Story 1.2 cố ý không chạm handler hay endpoint (Never của spec), nhưng Epic 3 dựng ngữ cảnh quyền ở đầu request thì phải có đường nạp policy thật.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Chặn `use_context` lồng nhau đưa ngữ cảnh hệ thống vào giữa một request người dùng.
  evidence: `use_context(system_context(...))` lồng trong ngữ cảnh vai hiện không có gì cản, là đường leo quyền im lặng. NFR-10 giao việc từ chối `kind=system` trên đường truy vấn cho tầng handler API, nên chốt ở Epic 3 cùng test tầng handler.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Tripwire buộc story 1.6 phải chạm ruột hàm che, tránh CI xanh trong khi `mask()` vẫn no-op sau khi adapter đã gọi nó.
  evidence: Từ story 1.3 adapter gọi `mask()` trong đường trả về; stub trả nguyên trạng nên suite vẫn xanh dù không che gì. `test_grant_rong_tra_nguyen_trang` khóa hình dạng chứ không khóa hành vi.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Test phản chiếu cho các method đọc ngoài danh sách đóng (`node_degree`, `edge_degree`, `has_node`, `has_edge`) - hiện chỉ được giải thích trong comment.
  evidence: AD-9 giao test phản chiếu phủ cả 3 adapter cho story 1.7, nhưng cách xử lý riêng của 4 method này chưa có gì ghim, story 1.3-1.5 dễ bỏ quên.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Gọi `QdrantVectorDBStorage.initialize()` ở bước khởi động engine (story 1.7), và tiêm một `AsyncQdrantClient` dùng chung cho cả ba namespace vector.
  evidence: Upstream không có hook khởi tạo storage nào chạy trước lần upsert đầu (`index_done_callback` chạy sau), nên collection và payload index phải do phía mình gọi. Story 1.3 cố ý không nối vào `HyperGraphRAG` (Never của spec); chưa ai gọi `initialize()` thì upsert thật sẽ dừng ở `QdrantIndexMissing` - đúng thiết kế, nhưng phải có chỗ gọi.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Chạy lại đúng cặp assert của `tests/test_adapter_qdrant.py` trên Qdrant thật (container) ở cổng M1 story 1.7.
  evidence: Local mode duyệt vét cạn và bỏ qua payload index, nên nó chứng minh được ngữ nghĩa lọc chứ không chứng minh được pre-filter chạy trong HNSW có index. Lớp bọc `tests/gia_lap_qdrant.py` bù phần `payload_schema` cho nhánh kiểm index; phần còn lại chỉ Qdrant thật mới trả lời được.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-ngu-canh-quyen-fail-closed-va-chinh-sach-dang-du-lieu.md`
  summary: Khoản nợ "kiểm contextvar quyền sống qua pipeline async thật của upstream" chuyển điểm kiểm từ story 1.3 sang story 1.7.
  evidence: Ledger ghi điểm kiểm tự nhiên là 1.3, nhưng spec 1.3 cấm nối adapter vào `HyperGraphRAG` (việc đó thuộc 1.7). Story 1.3 chỉ kiểm được contextvar qua `asyncio.gather` do adapter tự phát lúc embed theo lô, chưa đi qua `aquery`.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Chốt `hnsw_config` (`payload_m`, `m`) lúc tạo collection, hoặc ghi rõ là khoản kiểm ở cổng M1, để cạnh HNSW theo tenant thật sự được dựng.
  evidence: `initialize()` chỉ đặt `VectorParams` cộng payload index `is_tenant=True`. Toàn bộ lý do của AD-4 và của `QdrantIndexMissing` là "extra HNSW edge chỉ dựng cho field đã có index lúc build", nhưng chưa có tham số nào bật đường đó, nên cửa chặn ghi-trước-index đang bảo vệ một cơ chế chưa được cấu hình. Chỉ Qdrant thật mới kiểm được.
  resolved: 2026-09-01 - `initialize()` truyền `hnsw_config=HnswConfigDiff(payload_m=16, m=16)`. Giữ `m` khác 0 có chủ đích: khuyến nghị `m=0` của hướng dẫn tenant chỉ đúng khi mọi truy vấn đều có filter tenant, còn ngữ cảnh hệ thống ở đây đọc thô không filter nên tắt index toàn cục là biến đường ingest thành full scan. Lý do nằm trong comment cạnh hai hằng. Local mode nhận rồi bỏ qua, nên hiệu lực thật vẫn là khoản kiểm ở cổng M1.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Guardrail `filter_max_conditions` (strict mode Qdrant) trong PRD addendum chưa có chỗ nào cấu hình.
  evidence: Addendum chốt nó là hàng rào phía server chống filter đa điều kiện. Hiện chỉ có quy ước trong code adapter và helper assert `khoa_trong_filter` trong test; không có gì phía server ngăn một đường code tương lai gửi filter hai điều kiện.
  resolved: 2026-09-01 - `initialize()` truyền `strict_mode_config` với `enabled=True`, `filter_max_conditions=1`, `unindexed_filtering_retrieve=False`, `unindexed_filtering_update=False`. Comment ghi rõ Epic 5 (break-glass) nếu cần filter hai điều kiện thì phải nới chỗ này có chủ đích. Hiệu lực thật kiểm ở cổng M1 cùng khoản trên.

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
  evidence: Ingest của upstream đi theo nhiều lô nhỏ nên chi phí này lặp lại liên tục. Có thể nhớ kết quả sau lần đầu thành công kèm đường vô hiệu hóa khi đổi collection, nhưng phải đo trên Qdrant thật mới biết có đáng không.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-adapter-qdrant-voi-pre-filter-theo-khoa.md`
  summary: Vòng đời kết nối Qdrant - khi không tiêm sẵn client, mỗi instance adapter tự mở một `AsyncQdrantClient` riêng và không có chỗ nào gọi `close()`.
  evidence: Review story 1.3 chỉ ra comment của field `qdrant_client` hứa "ba namespace dùng chung một kết nối" trong khi nhánh không tiêm thì mở ba kết nối. Comment đã sửa cho khớp code; việc tiêm một client dùng chung và đóng nó lúc tắt tiến trình thuộc story 1.7, cùng chỗ gọi `initialize()`.
