"""Import-lint: chiều import là luật (spine, AGENTS.md).

Quy tắc canh giữ:
- ``core/`` chỉ stdlib (không third-party, không tầng nào khác).
- ``adapters/`` không import ``api``, ``redteam``.
- ``redteam/`` không import ``api``.
- ``eval/`` (harness Đo 1-3) không import ``api``: nó chạy ngoài tiến trình phục
  vụ, tiêm engine và audit port như ``tests/`` (AD-15). Từ story 2.8 nó cũng
  không import ``vendor``: luật chia chunk của upstream đi qua
  ``adapters/chunking.py``, ngoại lệ duy nhất là smoke của story 1.1.
- Không tầng nào import ``tests`` hay ``vendor`` trực tiếp ngoài luật cho phép
  (``adapters`` được import ``hypergraphrag`` từ vendor).
- Chỉ module ingest trong danh sách trắng được import ``core.system_context``
  (constructor cờ bỏ-filter, AD-3). Danh sách trắng hiện rỗng vì pipeline
  ingest chưa tồn tại; story 2.3 thêm đúng một dòng vào đây.
- ``tests/fixtures/`` (dữ liệu dựng tay và oracle quyền) không gọi vào hệ:
  oracle dùng chung hàm với ``core/`` thì test chỉ chứng minh hệ nhất quán với
  chính nó.

Quét bằng AST trên mọi file .py của từng package; import tương đối trong cùng
package được phép. Test này chạy CI từ story 1.1, các story sau thêm code là
bị canh ngay.
"""

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CAM_IMPORT = {
    "core": {"adapters", "api", "redteam", "web", "tests", "hypergraphrag", "vendor"},
    "adapters": {"api", "redteam", "web", "tests"},
    "api": {"web", "tests"},
    "redteam": {"api", "web", "tests"},
    # `eval/` không import `vendor/` (story 2.8, khoản ledger 2.6). Luật chia
    # chunk của vendor đi qua `adapters/chunking.py`, đó là chỗ duy nhất parity
    # với upstream được canh; một `eval/` tự import `hypergraphrag` là một bản
    # sao thứ hai của luật đó trôi tự do.
    "eval": {"api", "web", "tests", "hypergraphrag", "vendor"},
}

# Miễn trừ tường minh kèm lý do, thay vì nới luật ở trên. Đúng một dòng, cùng
# hình dạng với `CHO_PHEP_SYSTEM_CONTEXT` và `CHO_PHEP_AINSERT`:
# `eval/smoke_upstream.py` là smoke của story 1.1, chạy *engine upstream* trên
# storage mặc định để chứng minh vendor còn chạy được - nó không phải một đường
# đo, không dùng luật chunk của dự án, và AGENTS.md đã ghi nó là ngoại lệ duy
# nhất của chiều import `eval/`.
CHO_PHEP_VENDOR: frozenset[str] = frozenset({"eval/smoke_upstream.py"})

# Miễn trừ chỉ áp cho **đúng các gốc vendor**, không phải cho mọi luật chiều
# import của package. Không có hàng rào này thì một dòng danh sách trắng thêm vào
# vì lý do vendor cũng lặng lẽ mở luôn `api`, `web` và `tests` cho chính file đó.
GOC_VENDOR: frozenset[str] = frozenset({"hypergraphrag", "vendor"})


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
    """adapters/api/redteam/eval không import ngược tầng bị cấm."""
    vi_pham = []
    for package, cam in CAM_IMPORT.items():
        if package == "core":
            continue
        for root, py in _goc_import_tuyet_doi(package):
            duong_dan = py.relative_to(REPO_ROOT).as_posix()
            duoc_mien = root in GOC_VENDOR and duong_dan in CHO_PHEP_VENDOR
            if root in cam and not duoc_mien:
                vi_pham.append(f"{duong_dan}: import {root}")
    assert not vi_pham, "Vi phạm chiều import:\n" + "\n".join(vi_pham)


def test_danh_sach_trang_vendor_dung_mot_dong_va_van_con_that():
    """Miễn trừ vendor của `eval/` phải đúng một dòng, và dòng đó phải trỏ file có thật.

    Một danh sách trắng trỏ vào file đã xóa là một luật đã hết tác dụng mà
    không ai biết; một danh sách trắng dài ra là luật đã bị nới bằng cách thêm
    dòng thay vì bằng một quyết định.
    """
    assert len(CHO_PHEP_VENDOR) == 1
    for duong_dan in CHO_PHEP_VENDOR:
        assert (REPO_ROOT / duong_dan).is_file(), duong_dan


def test_mien_tru_vendor_khong_mo_cua_cho_luat_khac(tmp_path, monkeypatch):
    """File trong danh sách trắng vẫn phải bị bắt khi nó import `api`.

    Danh sách trắng là miễn trừ cho *một luật*, không phải một tấm vé đi qua mọi
    luật chiều import của package.
    """
    goc = tmp_path / "eval"
    goc.mkdir()
    (goc / "smoke_upstream.py").write_text(
        "import hypergraphrag" + chr(10) + "import api" + chr(10), encoding="utf-8"
    )
    monkeypatch.setattr("tests.test_import_lint.REPO_ROOT", tmp_path)
    monkeypatch.setitem(CAM_IMPORT, "eval", {"api", "hypergraphrag", "vendor"})
    with pytest.raises(AssertionError) as loi:
        test_khong_import_nguoc()
    thong_diep = str(loi.value)
    assert "import api" in thong_diep
    # ...và đúng dòng vendor thì vẫn được miễn, nếu không test trên xanh vì lý do sai.
    assert "import hypergraphrag" not in thong_diep


def test_eval_ngoai_smoke_khong_cham_vendor():
    """Mọi file `eval/` trừ smoke phải đi qua `adapters/chunking.py` để chạm luật vendor."""
    cham = sorted(
        {
            py.relative_to(REPO_ROOT).as_posix()
            for root, py in _goc_import_tuyet_doi("eval")
            if root in {"hypergraphrag", "vendor"}
        }
    )
    assert cham == sorted(CHO_PHEP_VENDOR), cham


# 1.2-UNIT-004: constructor context hệ thống là cửa duy nhất mở cờ bỏ-filter,
# nên nó sống một file riêng để quét được bằng tên module.
GOI_QUET = ("core", "adapters", "api", "redteam", "eval")
MODULE_SYSTEM_CONTEXT = "core.system_context"
FILE_SYSTEM_CONTEXT = "core/system_context.py"
# Danh sách trắng: đường dẫn tương đối gốc repo của module ingest được phép.
# Rỗng ở story 1.2; story 2.2 tạm đặt script đo thô `api/do_chi_phi.py`; story
# 2.3 thay bằng module pipeline thật và script gọi pipeline. Vẫn đúng một dòng.
CHO_PHEP_SYSTEM_CONTEXT: frozenset[str] = frozenset({"adapters/ingest.py"})

# Cùng luật với danh sách trắng ở trên nhưng cho *lối vào ghi tri thức*:
# `ainsert`/`insert` của engine chỉ được gọi từ pipeline (story 2.3). Gọi thẳng
# ở chỗ khác là một đường nạp không có sổ tài liệu, không có khóa tiến trình,
# không có kiểm space real - tức mọi luật của pipeline bị đi vòng.
# `eval/smoke_upstream.py` là smoke của story 1.1 chạy *engine upstream* trên
# storage mặc định (không phải ba kho ACL), nên nó không phải một đường nạp
# của dự án; miễn tường minh kèm lý do thay vì nới luật.
CHO_PHEP_AINSERT: frozenset[str] = frozenset({"adapters/ingest.py", "eval/smoke_upstream.py"})
# `.ainsert(` bắt vô điều kiện; `.insert(` chỉ khi đối tượng nhận là một tên
# mang `engine`/`rag` (`list.insert`, `sys.path.insert` là chuyện khác).
TEN_GOI_NAP_LUON = frozenset({"ainsert"})
TEN_GOI_NAP_THEO_DOI_TUONG = frozenset({"insert"})
DAU_HIEU_ENGINE = ("engine", "rag")


def _module_tuyet_doi(node: ast.ImportFrom, goi_cha: tuple[str, ...]) -> str:
    """Tên module tuyệt đối của một ``from ... import``, kể cả import tương đối.

    ``goi_cha`` là các thành phần package của thư mục chứa file. level=1 là
    chính package đó, level=2 lùi một bậc, và cứ thế.
    """
    if node.level == 0:
        return node.module or ""
    lui = node.level - 1
    goc = goi_cha[: len(goi_cha) - lui] if lui <= len(goi_cha) else ()
    return ".".join(goc + ((node.module,) if node.module else ()))


def _import_system_context(py: Path, goi_cha: tuple[str, ...]) -> bool:
    """File này có với tới constructor context hệ thống dưới bất kỳ dạng nào không.

    Ba dạng: ``import core.system_context``, ``from ... import system_context``
    (tuyệt đối lẫn tương đối), và tên module dạng chuỗi - ``import_module`` hay
    ``__import__`` đều đi qua một chuỗi hằng.
    """
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == MODULE_SYSTEM_CONTEXT for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = _module_tuyet_doi(node, goi_cha)
            if module == MODULE_SYSTEM_CONTEXT:
                return True
            if module == "core" and any(
                a.name == "system_context" for a in node.names
            ):
                return True
        elif isinstance(node, ast.Constant) and node.value == MODULE_SYSTEM_CONTEXT:
            return True
    return False


def _quet_system_context(
    cho_phep: frozenset[str], goc: Path = REPO_ROOT
) -> list[str]:
    """Đường dẫn các file với tới context hệ thống mà không nằm trong danh sách trắng.

    `goc` mặc định là gốc repo, tức là thứ luật này canh giữ thật. Nó là tham
    số để test của chính bộ dò dựng được một cây giả trong `tmp_path`: kiểm
    nhánh danh sách trắng bằng cách ghi một file vào `core/` thật rồi xóa đi là
    để lại một file trong thư mục mà AGENTS.md bắt trình diff nếu tiến trình bị
    giết giữa chừng, và là làm hai test khác của chính file này đỏ giả khi suite
    chạy song song.
    """
    vi_pham = []
    for package in GOI_QUET:
        thu_muc = goc / package
        if not thu_muc.is_dir():
            continue
        for py in thu_muc.rglob("*.py"):
            duong_dan = str(py.relative_to(goc))
            if duong_dan == FILE_SYSTEM_CONTEXT or duong_dan in cho_phep:
                continue
            if _import_system_context(py, py.relative_to(goc).parts[:-1]):
                vi_pham.append(duong_dan)
    return vi_pham


def test_chi_ingest_duoc_import_context_he_thong():
    """AD-3: module ngoài ingest import constructor kind=system là CI fail."""
    assert (
        REPO_ROOT / FILE_SYSTEM_CONTEXT
    ).exists(), "core/system_context.py phải là file riêng để canh được"
    vi_pham = _quet_system_context(CHO_PHEP_SYSTEM_CONTEXT)
    assert not vi_pham, (
        "import core.system_context ngoài danh sách trắng ingest:\n" + "\n".join(vi_pham)
    )


def _goi_nap(py: Path) -> list[int]:
    """Số dòng của mọi lời gọi `<x>.ainsert(...)` / `<x>.insert(...)` trong file."""
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))

    def la_goi_nap(node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr in TEN_GOI_NAP_LUON:
            return True
        if node.func.attr not in TEN_GOI_NAP_THEO_DOI_TUONG:
            return False
        goc = node.func.value
        ten = (getattr(goc, "id", None) or getattr(goc, "attr", None) or "").lower()
        return any(dau in ten for dau in DAU_HIEU_ENGINE)

    return sorted(node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and la_goi_nap(node))


def test_ainsert_chi_duoc_goi_tu_pipeline_ingest():
    """`.ainsert(`/`.insert(` ngoài `tests/` chỉ ở `adapters/ingest.py` (story 2.3)."""
    assert (REPO_ROOT / "adapters" / "ingest.py").exists()
    vi_pham = []
    for package in GOI_QUET:
        thu_muc = REPO_ROOT / package
        if not thu_muc.is_dir():
            continue
        for py in thu_muc.rglob("*.py"):
            duong_dan = str(py.relative_to(REPO_ROOT))
            if duong_dan in CHO_PHEP_AINSERT:
                continue
            vi_pham += [f"{duong_dan}:{dong}" for dong in _goi_nap(py)]
    assert not vi_pham, "gọi ainsert/insert ngoài pipeline ingest:\n" + "\n".join(vi_pham)
    assert _goi_nap(REPO_ROOT / "adapters" / "ingest.py"), "pipeline phải là nơi gọi ainsert"


def test_bo_do_ainsert_bat_dung_va_khong_bat_nham(tmp_path):
    py = tmp_path / "x.py"
    py.write_text(
        "import sys\n"
        "async def f(engine, rag, xs):\n"
        "    await engine.ainsert('x')\n"          # 3: ainsert luôn bắt
        "    rag.insert(['y'])\n"                  # 4: insert trên tên mang `rag`
        "    self.engine.insert('z')\n"            # 5: insert trên thuộc tính mang `engine`
        "    sys.path.insert(0, 'p')\n"            # không bắt: đối tượng nhận là `path`
        "    xs.insert(0, 1)\n"                    # không bắt: list.insert
        "    ainsert('z')\n",                      # không bắt: tên trần
        encoding="utf-8",
    )
    assert _goi_nap(py) == [3, 4, 5]


# Bốn cách với tới module, viết như code thật để AST nhìn thấy đúng thứ cần bắt.
CACH_VOI_TOI = {
    "import_tuyet_doi": "import core.system_context\n",
    "from_module": "from core.system_context import system_context\n",
    "from_goi_cha": "from core import system_context\n",
    "import_tuong_doi": "from .system_context import system_context\n",
    "lui_mot_bac": "from .. import system_context\n",
    "ten_dang_chuoi": "import importlib\nm = importlib.import_module('core.system_context')\n",
}


@pytest.mark.parametrize("ten", sorted(CACH_VOI_TOI))
def test_bo_do_bat_moi_cach_voi_toi(tmp_path, ten):
    """Chính bộ dò phải có test, nếu không nó trả False mãi mà suite vẫn xanh."""
    py = tmp_path / "x.py"
    py.write_text(CACH_VOI_TOI[ten], encoding="utf-8")
    goi_cha = ("core", "ingest") if ten == "lui_mot_bac" else ("core",)
    assert _import_system_context(py, goi_cha) is True


def test_bo_do_khong_bat_nham_file_sach(tmp_path):
    """File không chạm tới module thì phải im, kể cả khi nhắc tên gần giống."""
    py = tmp_path / "x.py"
    py.write_text(
        "from core.permission import user_context\n"
        "import core.policy\n"
        "GHI_CHU = 'system context la ngoai le co dac ta'\n",
        encoding="utf-8",
    )
    assert _import_system_context(py, ("core",)) is False


def test_danh_sach_trang_duoc_bo_qua(tmp_path):
    """Thêm một dòng vào danh sách trắng là đủ để module ingest hợp lệ.

    Dựng cây giả trong `tmp_path` chứ không ghi vào `core/` thật. Ghi vào cây mã
    nguồn thì `finally` không sống sót qua một lần giết tiến trình, và trong lúc
    file còn nằm đó thì `test_chi_ingest_duoc_import_context_he_thong` quét
    trúng nó - một lần đỏ giả chỉ xuất hiện khi suite chạy song song, tức là
    loại lỗi khó tái hiện nhất.
    """
    (tmp_path / "core").mkdir()
    duong_dan = "core/_gia_lap_ingest.py"
    (tmp_path / duong_dan).write_text(
        "from core.system_context import system_context\n", encoding="utf-8"
    )

    # Đúng một vi phạm, không phải "có chứa": cây giả chỉ có một file, nên một
    # phép quét trả về nhiều hơn thế là bộ dò đang đọc cái gì khác.
    assert _quet_system_context(frozenset(), goc=tmp_path) == [duong_dan]
    assert _quet_system_context(frozenset({duong_dan}), goc=tmp_path) == []


# Hai luật danh sách trắng quanh PermissionContext. Sentinel lúc chạy trong
# `core/permission.py` là phòng vệ, hai luật này mới là hàng rào: chúng phát biểu
# được thành một câu và không có biến thể cú pháp nào lách được, nên không phải
# đuổi theo từng dạng biểu thức (`kind="system"`, `kind=KIND_SYSTEM`,
# `kind=_SystemKind("system")`, `kind=bien_bat_ky`...).
CHO_PHEP_DUNG_CONTEXT = frozenset({"core/permission.py", "core/system_context.py"})
MODULE_PERMISSION = "core.permission"


def _dung_thang_context(py: Path) -> list[int]:
    """Số dòng của mọi lời gọi dựng thẳng `PermissionContext(...)` trong file.

    Bắt ba dạng: gọi thẳng, gọi qua module (`permission.PermissionContext(...)`),
    và gọi qua bí danh (`from ... import PermissionContext as PC` rồi `PC(...)`).
    Bí danh phải giải được vì nó là tập đóng đọc ngay trong file, không phải một
    dạng biểu thức mới. Không quan tâm truyền `kind` gì: đường hợp lệ duy nhất
    là hai factory.
    """
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    ten_goi = {"PermissionContext"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            ten_goi |= {
                a.asname
                for a in node.names
                if a.name == "PermissionContext" and a.asname
            }
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        in ten_goi
    ]


def _cham_rieng_tu_permission(py: Path, goi_cha: tuple[str, ...] = ()) -> list[str]:
    """Tên bắt đầu bằng gạch dưới được lấy ra từ `core.permission` trong file.

    Hai đường: import thẳng (`from core.permission import _SystemKind`) và truy
    cập thuộc tính trên chính module (`permission._SYSTEM_KIND`). Đây là thứ
    chặn mọi sentinel hiện tại và tương lai của module đó rò ra ngoài `core/`.
    """
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    cham = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if _module_tuyet_doi(node, goi_cha) == MODULE_PERMISSION:
                cham += [a.name for a in node.names if a.name.startswith("_")]
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            goc = node.value
            ten_goc = getattr(goc, "id", None) or getattr(goc, "attr", None)
            if ten_goc == "permission":
                cham.append(node.attr)
    return cham


def test_chi_hai_factory_duoc_dung_context():
    """Ngoài `user_context` và `system_context`, không ai dựng thẳng ngữ cảnh quyền.

    Luật này chặt hơn "cấm kind=system": nó cũng chặn việc tự chế một context
    người dùng với `allowed_keys` bịa ra, đi vòng qua bảng chính sách.
    """
    vi_pham = []
    for package in GOI_QUET:
        thu_muc = REPO_ROOT / package
        if not thu_muc.is_dir():
            continue
        for py in thu_muc.rglob("*.py"):
            duong_dan = str(py.relative_to(REPO_ROOT))
            if duong_dan in CHO_PHEP_DUNG_CONTEXT:
                continue
            vi_pham += [f"{duong_dan}:{dong}" for dong in _dung_thang_context(py)]
    assert not vi_pham, (
        "dựng thẳng PermissionContext ngoài hai factory của core/:\n"
        + "\n".join(vi_pham)
    )


def test_khong_ai_ngoai_core_cham_rieng_tu_cua_permission():
    """Ngoài `core/`, không ai import tên riêng tư của `core.permission`."""
    vi_pham = []
    for package in GOI_QUET:
        if package == "core":
            continue
        thu_muc = REPO_ROOT / package
        if not thu_muc.is_dir():
            continue
        for py in thu_muc.rglob("*.py"):
            goi_cha = py.relative_to(REPO_ROOT).parts[:-1]
            for ten in _cham_rieng_tu_permission(py, goi_cha):
                vi_pham.append(f"{py.relative_to(REPO_ROOT)}: {ten}")
    assert not vi_pham, (
        "chạm tên riêng tư của core.permission từ ngoài core/:\n" + "\n".join(vi_pham)
    )


# Đúng file đi vòng đã lách được hai lớp cũ: sentinel import ra rồi dựng lại,
# nên cả `ast.Constant "system"` lẫn `ast.Name KIND_SYSTEM` đều không khớp.
FILE_DI_VONG = """\
from core.permission import PermissionContext, _SystemKind


def lach():
    return PermissionContext(kind=_SystemKind("system"), space="synth", role=None,
                             real_account=None, allowed_keys=None, masked_slots={},
                             grant_ids=(), policy_version="v")
"""

# Biến thể chỉ đổi cách viết: luật danh sách trắng không quan tâm.
FILE_DI_VONG_KHAC = """\
from core import permission

KIND = permission._SYSTEM_KIND


def lach(kind=KIND):
    return permission.PermissionContext(kind=kind, space="synth", role=None,
                                        real_account=None, allowed_keys=None,
                                        masked_slots={}, grant_ids=(),
                                        policy_version="v")
"""


# Bí danh: đổi tên lúc import rồi gọi bằng tên mới.
FILE_DI_VONG_BI_DANH = """\
from core.permission import PermissionContext as PC
from core.permission import _SYSTEM_KIND as K


def lach():
    return PC(kind=K, space="synth", role=None, real_account=None,
              allowed_keys=None, masked_slots={}, grant_ids=(), policy_version="v")
"""


@pytest.mark.parametrize(
    "noi_dung",
    [FILE_DI_VONG, FILE_DI_VONG_KHAC, FILE_DI_VONG_BI_DANH],
    ids=["import_sentinel", "qua_module", "bi_danh"],
)
def test_bo_do_bat_moi_duong_di_vong(tmp_path, noi_dung):
    """Cả hai nhánh phát hiện phải có test chạy vào, không để guard chưa từng chạy."""
    py = tmp_path / "thu_di_vong.py"
    py.write_text(noi_dung, encoding="utf-8")
    assert _dung_thang_context(py), "không bắt được lời gọi dựng thẳng"
    assert _cham_rieng_tu_permission(py, ("adapters",)), "không bắt được tên riêng tư"


def test_bo_do_khong_bat_nham_duong_hop_le(tmp_path):
    """Gọi factory và import tên công khai thì phải im."""
    py = tmp_path / "hop_le.py"
    py.write_text(
        "from core.permission import current_context, user_context\n"
        "from core.policy import NAMESPACES\n"
        "def dung(policy):\n"
        "    return user_context(policy=policy, role='devops', space='synth',\n"
        "                        real_account='dev01')\n",
        encoding="utf-8",
    )
    assert _dung_thang_context(py) == []
    assert _cham_rieng_tu_permission(py, ("adapters",)) == []


def test_oracle_khong_goi_core():
    """Oracle quyền phải đứng độc lập: dùng chung hàm với hệ là mất đối chứng."""
    cam = {"core", "adapters", "api", "redteam", "hypergraphrag", "vendor"}
    vi_pham = []
    for py in (REPO_ROOT / "tests" / "fixtures").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            goc = None
            if isinstance(node, ast.Import):
                goc = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                goc = [node.module.split(".")[0]]
            for root in goc or []:
                if root in cam:
                    vi_pham.append(f"{py.relative_to(REPO_ROOT)}: import {root}")
    assert not vi_pham, "fixture/oracle gọi vào hệ:\n" + "\n".join(vi_pham)
