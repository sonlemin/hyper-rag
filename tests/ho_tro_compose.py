"""Đọc `docker-compose.yml` cho các test hợp đồng triển khai (story 1.1).

Parse chứ không tìm chuỗi: một dòng bị comment lại vẫn qua được phép tìm
chuỗi, và khi đó test khẳng định một hợp đồng triển khai không còn tồn tại.

Helper để một bản ở đây vì hai bộ test hỏi cùng một file: `test_engine_acl.py`
hỏi phía biến môi trường của engine, `test_compose_ha_tang.py` hỏi phía thứ tự
khởi động và profile.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ba kho mà `api` phải chờ healthy trước khi khởi động (AD-11).
KHO_PHAI_CHO = ("neo4j", "qdrant", "postgres")


def doc_compose() -> dict:
    """`docker-compose.yml` ở gốc repo, đã parse."""
    return yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
