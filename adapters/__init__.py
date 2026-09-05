"""Tầng adapter storage của hyper-rag-copilot.

Được import core/ và vendor/. Chiều import do `tests/test_import_lint.py` canh:
tầng này không import `api/`, `redteam/`, `web/`, `tests/`.

Nội dung hiện có:

- `qdrant`         adapter vector, pre-filter theo khóa (1.3)
- `neo4j`          adapter graph, WHERE-injection và cấu trúc hai phía (1.4)
- `kv`             adapter chunk/tài liệu gốc, ngưỡng L2 và tắt cache LLM (1.5)
- `ingest_labels`  phạm vi nhãn ingest - khóa quyền của đường ghi (1.3)
- `mask_contract`  hợp đồng tầng che nhìn từ phía adapter (1.3, 1.4)
- `policy_loader`  nửa I/O của `core/policy.py` (1.2)
- `sensitivity_loader` bảng hạng độ nhạy đóng băng, đầu vào của luật hợp
                   nhất khóa đa nguồn (2.1)
- `doi_chieu`      sổ đợt ingest và bước đối chiếu khóa giữa các kho (2.1)
- `engine`         subclass `HyperGraphRAG`: registry 3 adapter, khóa cấu hình
                   kho, vòng đời kết nối (1.7)
- `identity_seed`  nửa I/O của `core/identity.py`; seed tài khoản kèm hash
                   bcrypt, nhóm và cờ demo/admin từ version 2 (1.7, 3.1)
- `nhom_phu_trach` bảng loại nội dung -> nhóm phụ trách; nguồn duy nhất của tên
                   nhóm trong dấu che `owner` (3.1)

Còn thiếu, vào ở các story sau: pipeline ingest (2.3), adapter audit port (3.6).
"""
