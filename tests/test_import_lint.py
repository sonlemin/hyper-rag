"""Import-lint: chiều import là luật (spine, AGENTS.md).

Quy tắc canh giữ:
- ``core/`` chỉ stdlib (không third-party, không tầng nào khác).
- ``adapters/`` không import ``api``, ``redteam``.
- ``redteam/`` không import ``api``.
- Không tầng nào import ``tests`` hay ``vendor`` trực tiếp ngoài luật cho phép
  (``adapters`` được import ``hypergraphrag`` từ vendor).

Quét bằng AST trên mọi file .py của từng package; import tương đối trong cùng
package được phép. Test này chạy CI từ story 1.1, các story sau thêm code là
bị canh ngay.
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CAM_IMPORT = {
    "core": {"adapters", "api", "redteam", "web", "tests", "hypergraphrag", "vendor"},
    "adapters": {"api", "redteam", "web", "tests"},
    "api": {"web", "tests"},
    "redteam": {"api", "web", "tests"},
}


def _goc_import_tuyet_doi(package: str) -> list[tuple[str, Path]]:
    """Cặp (tên module gốc, file) của mọi import tuyệt đối trong package."""
    roots: list[tuple[str, Path]] = []
    for py in (REPO_ROOT / package).rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots += [(alias.name.split(".")[0], py) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.append((node.module.split(".")[0], py))
    return roots


def test_core_chi_stdlib():
    """core/ chỉ được import stdlib hoặc chính nó."""
    cho_phep = set(sys.stdlib_module_names) | {"core"}
    vi_pham = [
        f"{py.relative_to(REPO_ROOT)}: import {root}"
        for root, py in _goc_import_tuyet_doi("core")
        if root not in cho_phep
    ]
    assert not vi_pham, "core/ import ngoài stdlib:\n" + "\n".join(vi_pham)


def test_khong_import_nguoc():
    """adapters/api/redteam không import ngược tầng bị cấm."""
    vi_pham = []
    for package, cam in CAM_IMPORT.items():
        if package == "core":
            continue
        for root, py in _goc_import_tuyet_doi(package):
            if root in cam:
                vi_pham.append(f"{py.relative_to(REPO_ROOT)}: import {root}")
    assert not vi_pham, "Vi phạm chiều import:\n" + "\n".join(vi_pham)
