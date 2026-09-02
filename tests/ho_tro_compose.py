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


def doc_env(ten_file: str) -> dict[str, str]:
    """Một file `.env.*` tham số môi trường ở gốc repo, đã parse thành dict.

    Chỉ dạng `KEY=VALUE`, bỏ dòng trống và dòng `#`. Không dùng cho `.env` gốc
    (secret, gitignore): test không được đọc secret.
    """
    ket_qua: dict[str, str] = {}
    for dong in (REPO_ROOT / ten_file).read_text(encoding="utf-8").splitlines():
        dong = dong.strip()
        if not dong or dong.startswith("#") or "=" not in dong:
            continue
        khoa, gia_tri = dong.split("=", 1)
        ket_qua[khoa.strip()] = gia_tri.strip()
    return ket_qua
