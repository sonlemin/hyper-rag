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
