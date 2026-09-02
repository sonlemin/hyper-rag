"""Harness đo và dữ liệu đánh giá của khóa luận (Đo 1-3, bộ vàng, CT-03).

Là một package để `python -m eval.xem_bo_vang` và `import eval.bo_vang` chạy
được từ gốc repo. Không nằm trong `[tool.hatch.build.targets.wheel]`: harness
chạy tại chỗ trong repo, không đóng gói vào wheel sản phẩm.

Luật import (canh bằng `tests/test_import_lint.py`): `eval/` không import
`api/`, `web/`, `tests/`. Nó chạy ngoài tiến trình phục vụ và tự tiêm engine
cùng audit port giống `tests/` (AD-15).
"""
