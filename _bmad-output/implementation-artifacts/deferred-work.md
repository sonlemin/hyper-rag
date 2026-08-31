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

