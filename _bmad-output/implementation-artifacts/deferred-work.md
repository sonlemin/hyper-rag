# Deferred work

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-dung-stack-docker-va-truy-van-dau-tien.md`
  summary: Ghim tag image ollama cụ thể (hiện `OLLAMA_TAG=latest`) khi bật profile `local-llm` lần đầu.
  evidence: Mọi image khác đều ghim chặt phiên bản; profile local-llm chưa từng chạy ở story 1.1 nên chưa có cơ sở kiểm chứng tag nào, ghim mù còn rủi ro hơn.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-dung-stack-docker-va-truy-van-dau-tien.md`
  summary: Chốt cách phơi cổng 8000 (bind 127.0.0.1 + reverse proxy, hoặc quy tắc UFW) trước khi API trả dữ liệu thật.
  evidence: Compose đang bind `8000:8000` trên máy chủ công cộng; story 1.1 chỉ có `/health` nên chấp nhận được, nhưng từ Epic 3 (JWT, dữ liệu thật) cần quyết định tường minh.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-dung-stack-docker-va-truy-van-dau-tien.md`
  summary: Thêm test import-lint canh chiều import (core/ chỉ stdlib, không import ngược) khi core/ có nội dung ở story 1.2.
  evidence: Epic-1 context ghi "Test import-lint chạy CI" nhưng story 1.1 core/ còn rỗng, luật mới nằm trong docstring, chưa có gì canh giữ.
