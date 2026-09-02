"""Harness đo và dữ liệu đánh giá của khóa luận (Đo 1-3, bộ vàng, CT-03).

Là một package để `python -m eval.xem_bo_vang` và `import eval.bo_vang` chạy
được từ gốc repo. Không nằm trong `[tool.hatch.build.targets.wheel]`: harness
chạy tại chỗ trong repo, không đóng gói vào wheel sản phẩm.

Luật import (canh bằng `tests/test_import_lint.py`): `eval/` không import
`api/`, `web/`, `tests/`. Nó chạy ngoài tiến trình phục vụ và tự tiêm engine
cùng audit port giống `tests/` (AD-15).
"""


import os
from pathlib import Path

GOC_REPO: Path = Path(__file__).resolve().parent.parent


def nap_bien_tu_env(ten_bien: str, goc: Path | None = None) -> str | None:
    """Đọc một biến từ `.env` gốc repo vào môi trường nếu chưa có; trả giá trị.

    Một nơi duy nhất đọc secret cho cả `eval/`: hai bản chép luật đọc `.env` là
    hai chỗ để chúng lệch nhau (một bản hiểu `export KEY=`, bản kia không).
    Không bao giờ in giá trị ra, kể cả khi hỏng.
    """
    if os.environ.get(ten_bien):
        return os.environ[ten_bien]
    env_file = (goc or GOC_REPO) / ".env"
    if not env_file.exists():
        return None
    try:
        noi_dung = env_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for dong in noi_dung.splitlines():
        dong = dong.strip()
        if dong.startswith("export "):
            dong = dong[len("export ") :].lstrip()
        if dong.startswith(f"{ten_bien}="):
            gia_tri = dong.split("=", 1)[1].strip().strip("'\"")
            if gia_tri:
                os.environ[ten_bien] = gia_tri
                return gia_tri
            return None
    return None
