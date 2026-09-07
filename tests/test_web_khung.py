"""Khung web (story 4.1): token, microcopy, điều hướng và ghim phiên bản của `web/`.

Máy chủ CI không có node, nên mọi phép canh ở đây **chỉ đọc file** dưới `web/`
bằng stdlib cộng PyYAML (đọc frontmatter DESIGN.md). Không import gì từ `web/`,
không chạy `next`, không cần `node_modules`.

Vì sao token và microcopy là JSON chứ không phải TS: để chính file này đối chiếu
được chúng với nguồn chuẩn (frontmatter DESIGN.md, hằng `api.hoi_dap.TEMPLATE_TU_CHOI`)
mà không cần một trình phân tích TypeScript. Một bản chép lệch một hex, một chuỗi
UI mang em dash, một route không có mục sidebar - cả ba đỏ ở `uv run pytest`
trước khi ai mở trình duyệt.

Mười nhóm test. Bảy nhóm đầu đúng thứ tự spec 4.1:
(1) `tokens.json` bằng frontmatter DESIGN.md từng giá trị;
(2) tương phản WCAG >= 4.5:1 cho các cặp chữ/nền đã khai;
(3) sàn chữ 13px ở token và ở mọi `.css`/`.ts`/`.tsx` của `web/src`;
(4) microcopy không em dash, không "không chỉ", và nguyên văn theo bảng Voice and Tone;
(5) `tu_choi` bằng đúng hằng phía `api/`;
(6) mục sidebar và route `web/src/app/*/page.tsx` khớp một-một (trừ trang mẫu
    và màn đăng nhập, và trang mẫu chỉ mở cho phiên có cờ `admin`, ai khác 404);
(7) `package.json` ghim `next`, `cytoscape`, `engines.node`, danh sách dependency đóng.
Nhóm (8) là luật khung: không `localStorage`, không gọi thẳng `:8000`, một cửa
fetch duy nhất, rewrite `/api/*`, route mở `/dang-nhap`, và mọi `var(--x)` trong
`web/src` phải là biến mà `bien_css.ts` sinh ra.
Nhóm (9) là màn đăng nhập và vòng đời phiên (story 4.2): tám chuỗi mới có mặt và
được dùng thật, `/dang-nhap` có `page.tsx` và cố ý không có mục sidebar, luật
phân loại lỗi `la_het_phien` chỉ khai 401, và ngoài `phien.ts` không file nào
chạm `sessionStorage` hay khóa token.
Nhóm (10) là chat console (story 4.3): hai chuỗi mới có mặt và được dùng thật,
bốn hằng hợp đồng của `web/src/api/hoi_dap.ts` khớp đúng nguồn `api/hoi_dap.py`
cùng `api/main.py`, và không file nào trong `web/src` đặt trần thời gian cho một
lượt hỏi.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from api.hoi_dap import KHOA_ENVELOPE, KHOA_META, TEMPLATE_TU_CHOI, ThanHoiDap
from api.xac_thuc import MA_DANG_NHAP_SAI

GOC = Path(__file__).resolve().parent.parent
WEB = GOC / "web"
SRC = WEB / "src"
DESIGN = (
    GOC
    / "_bmad-output"
    / "planning-artifacts"
    / "ux-designs"
    / "ux-hyper_graph_rag-2026-08-30"
    / "DESIGN.md"
)

# Năm khối token mà `web/src/design/tokens.json` phải chép nguyên từ frontmatter.
KHOI_TOKEN = ("colors", "typography", "rounded", "spacing", "components")

# Sàn cỡ chữ (DESIGN.md Typography, EXPERIENCE.md Accessibility Floor).
SAN_PX = 13.0

# Các cặp (chữ, nền) phải đạt 4.5:1. Tên là khóa của `colors`, riêng `#FFFFFF`
# là chữ trắng trên topbar và nút chính.
CAP_TUONG_PHAN = (
    ("#FFFFFF", "primary-deep"),
    ("#FFFFFF", "primary"),
    ("redact-ink", "redact-bg"),
    ("level-l1-ink", "level-l1-bg"),
    ("level-l2", "level-l2-bg"),
    ("danger", "danger-bg"),
    ("ink", "surface-card"),
    ("ink-muted", "surface-card"),
    ("ink", "surface-app"),
    # Ba cặp của màn đăng nhập 4.2 (retro 4.1: không còn cặp chữ/nền nào không
    # ai chấm): dòng phụ dưới thương hiệu, thông báo hết phiên, và chính chữ
    # thương hiệu.
    ("ink-muted", "surface-app"),
    ("ink-muted", "surface-nav"),
    ("primary-deep", "surface-app"),
    # Bong bóng câu hỏi của màn chat 4.3: chữ `ink` trên nền `primary-tint`
    # (`components.turn-question` khai nền và viền nhưng không khai chữ, nên
    # phép canh theo component không phủ cặp này).
    ("ink", "primary-tint"),
    # Dòng meta của một lượt lỗi nằm thẳng trên nền khối cuộn, không trong bong
    # bóng trắng.
    ("ink-muted", "surface-stream"),
)

# Route không có mục sidebar và cố ý như vậy. Đây là danh mục ngoại lệ **có tên**
# của nhóm (6): trang mẫu chỉ mở cho phiên `admin` (ai khác nhận 404), còn màn
# đăng nhập là cửa vào chứ không phải một surface để điều hướng tới - một mục
# "Đăng nhập" trong sidebar chỉ hiện được cho người đã đăng nhập rồi.
ROUTE_KHONG_CO_MUC = {"/mau", "/dang-nhap"}


# --- Đọc nguồn -------------------------------------------------------------


def _frontmatter_design() -> dict:
    tho = DESIGN.read_text(encoding="utf-8")
    assert tho.startswith("---\n"), "DESIGN.md phải mở đầu bằng frontmatter YAML"
    ket = tho.index("\n---\n", 4)
    return yaml.safe_load(tho[4:ket])


def _json(duong: Path) -> dict:
    return json.loads(duong.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tokens() -> dict:
    return _json(SRC / "design" / "tokens.json")


@pytest.fixture(scope="module")
def microcopy() -> dict:
    return _json(SRC / "microcopy.json")


# --- (1) tokens.json bằng frontmatter DESIGN.md ---------------------------


def _lech(a, b, duong: str = "") -> list[str]:
    """Mọi đường khóa mà hai cây khác nhau, để thông điệp đỏ nêu đúng chỗ."""
    if isinstance(a, dict) and isinstance(b, dict):
        ra: list[str] = []
        for k in sorted(set(a) | set(b)):
            d = f"{duong}.{k}" if duong else k
            if k not in a:
                ra.append(f"{d}: thiếu trong tokens.json")
            elif k not in b:
                ra.append(f"{d}: thừa trong tokens.json")
            else:
                ra.extend(_lech(a[k], b[k], d))
        return ra
    if a != b or type(a) is not type(b):
        return [f"{duong}: DESIGN.md={a!r} tokens.json={b!r}"]
    return []


def test_tokens_json_bang_frontmatter_design_md(tokens):
    """Năm khối token chép **bằng nhau về giá trị** với frontmatter, kể cả kiểu.

    `15px` là chuỗi ở cả hai bên, `'700'` cũng vậy - đổi một bên thành số là lệch.
    """
    fm = _frontmatter_design()
    nguon = {k: fm[k] for k in KHOI_TOKEN}
    assert set(tokens) == set(KHOI_TOKEN), sorted(tokens)
    lech = _lech(nguon, tokens)
    assert not lech, "tokens.json lệch DESIGN.md:\n  " + "\n  ".join(lech)


def test_tham_chieu_trong_components_deu_phan_giai_duoc(tokens):
    """Mọi `{colors.x}` / `{rounded.x}` trong `components` trỏ vào khóa có thật."""
    hong = []
    for ten, muc in tokens["components"].items():
        for thuoc_tinh, gia_tri in muc.items():
            for khoi, khoa in re.findall(r"\{(\w+)\.([\w-]+)\}", str(gia_tri)):
                if khoa not in tokens.get(khoi, {}):
                    hong.append(f"components.{ten}.{thuoc_tinh} -> {{{khoi}.{khoa}}}")
    assert not hong, hong


# --- (2) tương phản WCAG ---------------------------------------------------


def _kenh(c: int) -> float:
    v = c / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def do_sang(hex_mau: str) -> float:
    h = hex_mau.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _kenh(r) + 0.7152 * _kenh(g) + 0.0722 * _kenh(b)


def ty_le_tuong_phan(chu: str, nen: str) -> float:
    """Tỷ lệ tương phản WCAG 2.x giữa hai màu hex sáu chữ số."""
    a, b = do_sang(chu), do_sang(nen)
    sang, toi = max(a, b), min(a, b)
    return (sang + 0.05) / (toi + 0.05)


def _hex(tokens: dict, ten: str) -> str:
    """Nhận `#hex`, tên màu trần, hay tham chiếu `{colors.x}` của khối components."""
    if ten.startswith("#"):
        return ten
    m = re.fullmatch(r"\{colors\.([\w-]+)\}", ten)
    return tokens["colors"][m.group(1) if m else ten]


@pytest.mark.parametrize("chu,nen", CAP_TUONG_PHAN)
def test_tuong_phan_toi_thieu_4_5(tokens, chu, nen):
    ty_le = ty_le_tuong_phan(_hex(tokens, chu), _hex(tokens, nen))
    assert ty_le >= 4.5, f"{chu} trên {nen}: {ty_le:.2f}:1 < 4.5:1"


def test_moi_cap_chu_nen_cua_components_deu_tu_4_5(tokens):
    """Mọi component khai cả `foreground` lẫn `background` màu đặc phải đạt sàn.

    Đây là phép canh trên **cặp mà component thật sự render**, không chỉ trên
    danh sách cặp đích danh ở trên: review 4.1 tìm ra `badge-level-l1` từng khai
    chữ `level-l1` trên nền `level-l1-bg` (4,44:1) trong khi chín cặp đích danh
    đều xanh. Nền rgba (chip vai trên topbar) không quy về một màu đặc nên bỏ qua
    có tên.
    """
    hong = []
    for ten, c in tokens["components"].items():
        chu, nen = c.get("foreground"), c.get("background")
        if not (chu and nen) or not nen.startswith(("#", "{")):
            continue
        ty_le = ty_le_tuong_phan(_hex(tokens, chu), _hex(tokens, nen))
        if ty_le < 4.5:
            hong.append(f"{ten}: {chu} trên {nen} = {ty_le:.2f}:1")
    assert not hong, hong


def test_ham_tuong_phan_dung_moc_wcag():
    """Chấm chính bộ đo: trắng/đen là 21:1, và một cặp biết trước là dưới sàn."""
    assert round(ty_le_tuong_phan("#FFFFFF", "#000000"), 2) == 21.0
    assert ty_le_tuong_phan("#8795A3", "#FFFFFF") < 4.5  # ink-faint, DESIGN.md nói rõ


# --- (3) sàn 13px ----------------------------------------------------------


def _px(gia_tri: str) -> float:
    m = re.fullmatch(r"\s*([\d.]+)px\s*", str(gia_tri))
    assert m, f"cỡ chữ phải là `<số>px`, nhận {gia_tri!r}"
    return float(m.group(1))


def test_moi_font_size_trong_token_tu_13px(tokens):
    for ten, muc in tokens["typography"].items():
        if "fontSize" in muc:
            assert _px(muc["fontSize"]) >= SAN_PX, f"typography.{ten}.fontSize"


def _file_giao_dien() -> list[Path]:
    return sorted(p for p in SRC.rglob("*") if p.suffix in {".css", ".tsx", ".ts"})


# Ba dạng khai cỡ chữ bị quét: `font-size: 12px` (CSS), `fontSize: "12px"` hay
# `fontSize: 12` không đơn vị (style inline, React hiểu là px), và shorthand
# `font: 700 12px/1.4 ...` (CSS).
MAU_CO_CHU = (
    re.compile(r"font-?[sS]ize\s*[:=]\s*['\"]?\s*([\d.]+)px"),
    re.compile(r"fontSize\s*:\s*['\"]?\s*(\d+(?:\.\d+)?)\b(?!\s*px)"),
    re.compile(r"\bfont\s*:\s*[^;]*?([\d.]+)px"),
)


def test_khong_font_size_duoi_13px_trong_web_src():
    vi_pham = []
    for f in _file_giao_dien():
        for so_dong, dong in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for mau in MAU_CO_CHU:
                for px in mau.findall(dong):
                    if float(px) < SAN_PX:
                        vi_pham.append(f"{f.relative_to(GOC)}:{so_dong}: {px}px")
    assert not vi_pham, vi_pham


def test_bo_do_co_chu_bat_ca_ba_dang():
    """Chấm chính bộ dò: ba dạng viết đều bị bắt, và giá trị hợp lệ không bị."""
    mau_thu = ["font-size: 12px", "fontSize: 12", 'fontSize: "12.5px"', "font: 700 12px/1.4 Arial"]
    for dong in mau_thu:
        assert any(float(px) < SAN_PX for m in MAU_CO_CHU for px in m.findall(dong)), dong
    assert not any(float(px) < SAN_PX for m in MAU_CO_CHU for px in m.findall("fontSize: 13.5"))


# --- (4) và (5) microcopy --------------------------------------------------

# Chín chuỗi của màn đăng nhập, nút đăng xuất và lối ra khỏi trạng thái lỗi (4.2). Chúng **không** nằm
# trong bảng Voice and Tone (bảng chỉ khai câu lỗi đăng nhập và câu hết phiên),
# nên phép canh của chúng là "có mặt, là chuỗi, và được dùng thật".
KHOA_MICROCOPY_DANG_NHAP = frozenset(
    {
        "dang_nhap_tieu_de",
        "o_tai_khoan",
        "o_mat_khau",
        "nut_dang_nhap",
        "dang_gui_dang_nhap",
        "lien_he_quan_tri",
        "nut_dang_xuat",
        "khong_giu_duoc_phien",
        "lien_ket_ve_dang_nhap",
    }
)

# 18 chuỗi của bảng Voice and Tone (EXPERIENCE.md, 16 hàng) cộng bốn chuỗi khung
# 4.1 và chín chuỗi màn đăng nhập 4.2.
KHOA_MICROCOPY_BAT_BUOC = KHOA_MICROCOPY_DANG_NHAP | {
    "placeholder_l1_trich_dan",
    "slab_che",
    "dong_han_che_l1",
    "nut_xin_truy_cap",
    "tu_choi",
    "dang_truy_van",
    "do_thi_trong",
    "hang_cho_trong",
    "phien_het_han",
    "tooltip_node_mo",
    "tooltip_badge_muc",
    "chip_xem_nhu",
    "divider_doi_vai",
    "break_glass_cho",
    "break_glass_da_cap",
    "nut_hoi_lai",
    "loi_dang_nhap",
    "banner_offline",
    "dang_nhap_de_bat_dau",
    "loi_he_thong",
    "thu_gon_menu",
    "mo_rong_menu",
}


def test_microcopy_du_khoa_va_moi_gia_tri_la_chuoi(microcopy):
    thieu = KHOA_MICROCOPY_BAT_BUOC - set(microcopy)
    assert not thieu, sorted(thieu)
    for khoa, gia_tri in microcopy.items():
        assert re.fullmatch(r"[a-z0-9_]+", khoa), f"khóa {khoa!r} không snake_case"
        assert isinstance(gia_tri, str) and gia_tri.strip(), khoa


def test_microcopy_khong_em_dash_khong_khong_chi(microcopy):
    """Quy ước CLAUDE.md áp cho mọi chuỗi UI (UX-DR14)."""
    xau = [k for k, v in microcopy.items() if "—" in v or "không chỉ" in v.lower()]
    assert not xau, xau


def test_microcopy_cho_trong_dung_dang_ten(microcopy):
    """Chỗ trống chỉ có dạng `{ten}` snake_case; `{}` rỗng hay `%s` là lỗi."""
    for khoa, gia_tri in microcopy.items():
        assert "%s" not in gia_tri and "{}" not in gia_tri, khoa
        for ten in re.findall(r"\{([^}]*)\}", gia_tri):
            assert re.fullmatch(r"[a-z][a-z0-9_]*", ten), f"{khoa}: {{{ten}}}"


EXPERIENCE = DESIGN.parent / "EXPERIENCE.md"

# Chuỗi phải xuất hiện **nguyên văn** trong bảng Voice and Tone của EXPERIENCE.md
# (các ô không có chỗ trống). Chỗ trống `{x}` thì bảng viết `[x]` nên không so được.
KHOA_GHIM_THEO_EXPERIENCE = ("phien_het_han", "loi_dang_nhap", "hang_cho_trong", "do_thi_trong", "tu_choi")


def test_microcopy_khop_nguyen_van_bang_voice_and_tone(microcopy):
    tho = EXPERIENCE.read_text(encoding="utf-8")
    bat_dau = tho.index("## Voice and Tone")
    ket_thuc = tho.index("\n## ", bat_dau + 1)
    bang = tho[bat_dau:ket_thuc]
    lech = [k for k in KHOA_GHIM_THEO_EXPERIENCE if f'"{microcopy[k]}"' not in bang]
    assert not lech, f"microcopy khác bảng Voice and Tone ở {lech}"


def test_microcopy_tu_choi_bang_hang_phia_api(microcopy):
    """Bản chép thứ hai của template FR-16 phải khớp hằng `api.hoi_dap.TEMPLATE_TU_CHOI`.

    `answer` là `null` trên dây (AD-8) nên câu người dùng đọc phải sống ở `web/`;
    đây là phép kiểm giữ hai bản không lệch nhau mà khoản ledger 3.5 đòi.
    """
    assert microcopy["tu_choi"] == TEMPLATE_TU_CHOI


# --- (6) sidebar và route khớp một-một --------------------------------------


def _route_cua_page(page: Path) -> str:
    rel = page.parent.relative_to(SRC / "app").as_posix()
    return "/" if rel == "." else "/" + rel


def test_moi_muc_sidebar_co_route_va_nguoc_lai():
    muc = _json(SRC / "khung" / "dieu_huong.json")
    assert isinstance(muc, list) and muc, "dieu_huong.json phải là danh sách không rỗng"
    for m in muc:
        assert set(m) >= {"khoa", "duong_dan", "nhan", "icon", "phim_tat"}, m
        assert "—" not in m["nhan"]
    duong_dan_muc = {m["duong_dan"] for m in muc}
    route_co_page = {_route_cua_page(p) for p in (SRC / "app").rglob("page.tsx")}
    thieu_page = duong_dan_muc - route_co_page
    assert not thieu_page, f"mục sidebar không có page.tsx: {sorted(thieu_page)}"
    thieu_muc = route_co_page - duong_dan_muc - ROUTE_KHONG_CO_MUC
    assert not thieu_muc, f"route không có mục sidebar: {sorted(thieu_muc)}"


def test_hom_nay_sidebar_dung_mot_muc_hoi_dap():
    """Thêm mục là Ask First của spec 4.1; test ghim để một mục chết không lọt."""
    muc = _json(SRC / "khung" / "dieu_huong.json")
    assert [(m["khoa"], m["duong_dan"]) for m in muc] == [("hoi_dap", "/")]


def test_trang_mau_chi_mo_cho_admin_va_khong_con_proxy():
    """Trang mẫu đọc phiên từ `usePhien()` và `notFound()` khi không có cờ `admin`.

    Quyết định 07/09/2026: rào theo `NODE_ENV` bỏ đi vì máy chủ là nơi duy nhất
    sonlm mở giao diện, nên trang phải xem được ở đó; `src/proxy.ts` (rào cũ)
    phải không còn, vì một proxy chặn `/mau` sẽ chặn luôn admin.
    """
    tho = (SRC / "app" / "mau" / "page.tsx").read_text(encoding="utf-8")
    assert "usePhien()" in tho and "notFound()" in tho
    assert re.search(r"if \(!phien\?\.admin\) notFound\(\)", tho), tho
    assert "NODE_ENV" not in tho
    assert not (SRC / "proxy.ts").exists(), "rào proxy cũ chặn cả admin"


# --- (7) ghim phiên bản -----------------------------------------------------


def test_package_json_ghim_next_cytoscape_va_node():
    pkg = _json(WEB / "package.json")
    assert pkg["dependencies"]["next"] == "16.3.3"
    assert pkg["dependencies"]["cytoscape"] == "3.34.2"
    assert pkg["engines"]["node"] == ">=20.9"
    assert "@playwright/test" in pkg["devDependencies"]
    assert (WEB / "package-lock.json").exists()
    assert (WEB / ".nvmrc").read_text(encoding="utf-8").strip().startswith("20")


def test_khong_dependency_ngoai_danh_sach_cho_phep():
    """Ask First của spec 4.1: mọi gói mới phải đi qua sonlm."""
    pkg = _json(WEB / "package.json")
    assert set(pkg["dependencies"]) == {"next", "react", "react-dom", "cytoscape"}
    dev = set(pkg["devDependencies"])
    la = {d for d in dev if d not in {"typescript", "@playwright/test"} and not d.startswith("@types/")}
    assert not la, sorted(la)
    for khoa in ("peerDependencies", "optionalDependencies", "overrides"):
        assert khoa not in pkg, f"package.json không được có {khoa}"


# --- (8) Luật khung ----------------------------------------------------------


def test_web_khong_doc_local_storage_va_khong_goi_thang_cong_8000():
    xau = []
    for f in _file_giao_dien():
        tho = f.read_text(encoding="utf-8")
        if "localStorage" in tho:
            xau.append(f"{f.relative_to(GOC)}: localStorage")
        # Cả `http://host:8000` lẫn `//host:8000` (URL tương đối giao thức).
        if re.search(r"(https?:)?//[^\s'\"/]+:8000\b", tho):
            xau.append(f"{f.relative_to(GOC)}: gọi thẳng cổng 8000")
    assert not xau, xau


# Mọi cách mở một kết nối HTTP từ trình duyệt; chỉ `goi.ts` được dùng, và nó
# chỉ dùng `fetch`.
MAU_KENH_HTTP = re.compile(r"\b(fetch\(|XMLHttpRequest|EventSource|sendBeacon)")


def test_goi_ts_la_cua_fetch_duy_nhat():
    """`web/src/api/goi.ts` là một cửa gọi API; không file nào khác mở kênh HTTP."""
    goi_fetch = [
        str(f.relative_to(GOC))
        for f in _file_giao_dien()
        if MAU_KENH_HTTP.search(f.read_text(encoding="utf-8"))
    ]
    assert goi_fetch == ["web/src/api/goi.ts"], goi_fetch


def test_khung_app_co_route_mo_chua_dang_nhap():
    """`ROUTE_MO` của `KhungApp.tsx` phải chứa `/dang-nhap`: màn đăng nhập (4.2)
    không được gate bởi chính phiên mà nó sắp tạo, và không gọi `/auth/toi`.

    Hằng `DUONG_DANG_NHAP` **sống ở `phien.ts`** từ story 4.3: màn chat là nơi
    thứ hai điều hướng về màn đăng nhập vì hết phiên, và một bản chép thứ hai
    của đường dẫn ấy là một bản viết sai mà không phép so nào bắt.
    """
    phien = (SRC / "api" / "phien.ts").read_text(encoding="utf-8")
    assert 'DUONG_DANG_NHAP = "/dang-nhap"' in phien
    tho = (SRC / "khung" / "KhungApp.tsx").read_text(encoding="utf-8")
    assert re.search(r"export const ROUTE_MO = \[DUONG_DANG_NHAP", tho)


# Hai bảng tên biến chép từ `bien_css.ts` (`TIEN_TO`, `HAU_TO_CHU`) làm hằng: test
# dựng lại tập biến từ `tokens.json` bằng chính quy ước đó, không đọc file TS.
TIEN_TO_BIEN = {"colors": "mau", "rounded": "bo", "spacing": "khoang"}
HAU_TO_CHU = {
    "fontFamily": "font",
    "fontSize": "co",
    "lineHeight": "cao-dong",
    "fontWeight": "dam",
    "letterSpacing": "gian-chu",
}


def _bien_css_sinh_ra(tokens: dict) -> set[str]:
    ra = set()
    for khoi, tien_to in TIEN_TO_BIEN.items():
        ra |= {f"--{tien_to}-{k}" for k in tokens[khoi]}
    for ten, muc in tokens["typography"].items():
        ra |= {f"--chu-{ten}-{HAU_TO_CHU[t]}" for t in muc}
    return ra


def test_moi_var_trong_web_src_la_bien_bien_css_sinh_ra(tokens):
    """Một `var(--mau-primry)` gõ sai lặng lẽ thành giá trị rỗng trong trình
    duyệt; ở đây nó đỏ. Bỏ qua mẫu chèn `${...}` (tên dựng lúc chạy từ token)."""
    co = _bien_css_sinh_ra(tokens)
    la = []
    for f in _file_giao_dien():
        for so_dong, dong in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for ten in re.findall(r"var\((--[\w-]+)", dong):
                if "${" in dong:
                    continue
                if ten not in co:
                    la.append(f"{f.relative_to(GOC)}:{so_dong}: {ten}")
    assert not la, la


def test_next_config_rewrite_api_ve_api_noi_bo():
    tho = (WEB / "next.config.ts").read_text(encoding="utf-8")
    assert "standalone" in tho
    assert "/api/:path*" in tho and "API_NOI_BO" in tho and "http://api:8000" in tho


# --- (9) Màn đăng nhập và vòng đời phiên (story 4.2) ------------------------

# Ngoài `phien.ts`, chỉ một file được chạm kho của trình duyệt, và nó chạm vì
# một lý do không phải phiên: `SidebarDieuHuong.tsx` nhớ trạng thái gập. Danh
# mục này là **đóng**; thêm một tên vào đây là một quyết định, không phải một
# lần sửa cho test xanh.
NGOAI_LE_SESSION_STORAGE = {"web/src/khung/SidebarDieuHuong.tsx"}

# File duy nhất được đọc, ghi hay xóa token phiên.
FILE_GIU_TOKEN = "web/src/api/phien.ts"

# Chú thích không phải mã: `goi.ts` và `KhungApp.tsx` **nói về** sessionStorage
# trong docstring mà không chạm nó. Bỏ chú thích trước khi quét, nếu không luật
# này phạt đúng những chỗ giải thích luật.
MAU_CHU_THICH_KHOI = re.compile(r"/\*.*?\*/", re.S)
# `//` mở chú thích, trừ khi nó là phần của một URL (`http://`).
MAU_CHU_THICH_DONG = re.compile(r"(?<![:\w])//.*$", re.M)


def _bo_chu_thich(tho: str) -> str:
    return MAU_CHU_THICH_DONG.sub("", MAU_CHU_THICH_KHOI.sub("", tho))


def test_bo_chu_thich_bo_dung_hai_dang_va_giu_url():
    """Chấm chính bộ dò: hai dạng chú thích biến mất, URL và mã ở lại."""
    assert "x" not in _bo_chu_thich("// x\n")
    assert "x" not in _bo_chu_thich("/* nhieu\n dong x */\n")
    assert "http://api:8000" in _bo_chu_thich('const a = "http://api:8000";')
    assert "sessionStorage" in _bo_chu_thich("window.sessionStorage.getItem(K);")


def test_microcopy_man_dang_nhap_du_khoa_va_duoc_dung_that(microcopy):
    """Chín chuỗi mới có mặt và mỗi chuỗi được một file `.tsx` dùng.

    Một khóa microcopy không ai dùng là một câu chữ mà bảng Voice and Tone và
    màn hình nói khác nhau mà không ai thấy.
    """
    thieu = KHOA_MICROCOPY_DANG_NHAP - set(microcopy)
    assert not thieu, sorted(thieu)
    tho = "\n".join(f.read_text(encoding="utf-8") for f in _file_giao_dien())
    khong_dung = sorted(k for k in KHOA_MICROCOPY_DANG_NHAP if f"MICROCOPY.{k}" not in tho)
    assert not khong_dung, f"khóa microcopy không nơi nào dùng: {khong_dung}"


def test_route_dang_nhap_co_page_va_co_ten_trong_ngoai_le_sidebar():
    """`/dang-nhap` phải có `page.tsx` thật và nằm trong `ROUTE_KHONG_CO_MUC`.

    Bỏ nó khỏi danh mục ngoại lệ là `test_moi_muc_sidebar_co_route_va_nguoc_lai`
    đỏ và nêu đúng tên route.
    """
    assert (SRC / "app" / "dang-nhap" / "page.tsx").exists()
    assert "/dang-nhap" in ROUTE_KHONG_CO_MUC


def test_la_het_phien_chi_khai_dung_401():
    """Luật phân loại lỗi khai **một chỗ** và chỉ nhận đúng 401.

    Hôm nay hai nơi rẽ nhánh theo 401 (`KhungApp`, màn đăng nhập) và các story
    4.3-4.6 sẽ thêm nữa. Một bản chép viết nhầm thành `>= 400` đá người dùng ra
    màn đăng nhập giữa một lượt hỏi; ở đây nó đỏ.
    """
    tho = (SRC / "api" / "phien.ts").read_text(encoding="utf-8")
    m = re.search(r"export function la_het_phien\([^)]*\)[^{]*\{(.*?)\n\}", tho, re.S)
    assert m, "phien.ts phải export hàm `la_het_phien`"
    than = m.group(1)
    assert set(re.findall(r"\b\d{3}\b", than)) == {"401"}, than
    # Cấm đúng thứ phải cấm - một phép so **khoảng** với status - chứ không cấm
    # ký tự `>` (nó cấm luôn arrow function và generic, và bản cũ bỏ sót `<`).
    assert not re.search(r"status\s*[<>]=?", than), than
    assert not re.search(r"[<>]=?\s*\d{3}", than), than


# Mọi cách viết một phép so status với 401 bằng tay.
MAU_SO_401 = re.compile(r"status\s*===?\s*401|401\s*===?\s*[\w.?\[\]\"']*status")


def test_khong_file_nao_ngoai_phien_ts_tu_so_401():
    """Luật phân loại lỗi khai một chỗ, và đây là phép canh trên **cả `web/src`**.

    Nơi duy nhất được phép điều hướng tới `/dang-nhap` vì một lỗi là nhánh
    `la_het_phien`; 403 và 5xx báo tại chỗ và giữ nguyên URL (spec 4.2, Never).
    Một bản chép `if (l.status === 401)` ở story 4.3-4.6 là chỗ mà bản sau viết
    nhầm thành `>= 400` rồi đá người dùng ra ngoài giữa một lượt hỏi.
    """
    xau = [
        str(f.relative_to(GOC))
        for f in _file_giao_dien()
        if str(f.relative_to(GOC)) != FILE_GIU_TOKEN
        and MAU_SO_401.search(_bo_chu_thich(f.read_text(encoding="utf-8")))
    ]
    assert not xau, xau
    khung = (SRC / "khung" / "KhungApp.tsx").read_text(encoding="utf-8")
    assert "la_het_phien(" in khung, "KhungApp phải dùng hàm chung, không tự so status"


def test_bo_do_401_bat_ca_hai_chieu_viet():
    """Chấm chính bộ dò, để nó không thành một regex không bao giờ khớp."""
    assert MAU_SO_401.search("if (l.status === 401) {")
    assert MAU_SO_401.search("if (401 === loi.status) {")
    assert not MAU_SO_401.search("la_het_phien(loi)")


def test_chi_phien_ts_cham_session_storage_va_khoa_token():
    """Ngoài `phien.ts` không file nào chạm `sessionStorage` hay khóa token.

    Token đi qua đúng một cửa thì `dang_xuat` và nhánh hết phiên xóa được nó ở
    một chỗ; hai chỗ đọc kho là hai chỗ quên xóa.
    """
    xau = []
    for f in _file_giao_dien():
        rel = str(f.relative_to(GOC))
        tho = _bo_chu_thich(f.read_text(encoding="utf-8"))
        if "sessionStorage" in tho and rel != FILE_GIU_TOKEN and rel not in NGOAI_LE_SESSION_STORAGE:
            xau.append(f"{rel}: sessionStorage")
        if "hyper_rag_token" in tho and rel != FILE_GIU_TOKEN:
            xau.append(f"{rel}: khóa token")
    assert not xau, xau


def test_man_dang_nhap_khong_doc_token_va_khong_tu_dieu_huong():
    """Màn đăng nhập không đọc kho để tự đá đi khi đã có token (Ask First 4.2).

    Một màn tự điều hướng làm người dùng không đăng nhập lại được bằng tài khoản
    khác, và khi token trong kho đã hỏng thì nó là một vòng lặp.
    """
    tho = (SRC / "app" / "dang-nhap" / "ManDangNhap.tsx").read_text(encoding="utf-8")
    assert "doc_token" not in tho, "màn đăng nhập không đọc token"
    assert "ghi_token(" in tho, "ghi token qua đúng cửa `phien.ts`"


def test_dang_xuat_chi_xoa_token_phia_trinh_duyet():
    """`dang_xuat()` sống ở `phien.ts` và không gọi tuyến API nào.

    `api/` không có danh sách đen JWT (giới hạn đã nhận ở ADR-022), nên đăng
    xuất chỉ là xóa token phía trình duyệt; token cũ vẫn hợp lệ tới hết TTL.
    """
    tho = (SRC / "api" / "phien.ts").read_text(encoding="utf-8")
    m = re.search(r"export function dang_xuat\([^)]*\)[^{]*\{(.*?)\n\}", tho, re.S)
    assert m, "phien.ts phải export hàm `dang_xuat`"
    assert "xoa_token()" in m.group(1)
    assert "goi(" not in m.group(1) and "goi<" not in m.group(1)


# --- (9b) Hợp đồng `POST /auth/login` giữa `web/` và `api/` -----------------

MAN_DANG_NHAP = SRC / "app" / "dang-nhap" / "ManDangNhap.tsx"


def _hang_chuoi(tho: str, ten: str) -> str:
    """Giá trị của một `export const <ten> = "..."` trong nguồn TypeScript."""
    m = re.search(rf'export const {ten} = "([^"]*)"', tho)
    assert m, f"phien.ts phải khai hằng {ten}"
    return m.group(1)


def test_ba_truong_cua_auth_login_khop_nguon_api():
    """Ba tên trường của `POST /auth/login` khớp đúng literal mà `api/main.py` đọc và phát.

    Đây là chỗ hợp đồng hai bên **không** có ai canh nếu chỉ nhìn từng phía: e2e
    mock trọn tuyến nên nó xanh với bất kỳ tên trường nào, còn phía `api/` không
    biết `web/` gửi gì. Và nó chết **im lặng theo chiều xấu nhất**: `api/main.py`
    ánh xạ thân sai trường về đúng 401 `DANG_NHAP_SAI`, nên màn đăng nhập nói
    "Sai tài khoản hoặc mật khẩu" cho một mật khẩu đúng.

    Cùng khuôn với `test_microcopy_tu_choi_bang_hang_phia_api`: một bản chép ở
    `web/` chỉ được tồn tại khi có một phép so giữ nó khớp nguồn.
    """
    ts = (SRC / "api" / "phien.ts").read_text(encoding="utf-8")
    tai_khoan = _hang_chuoi(ts, "TRUONG_TAI_KHOAN")
    mat_khau = _hang_chuoi(ts, "TRUONG_MAT_KHAU")
    token = _hang_chuoi(ts, "TRUONG_TOKEN")
    tuyen = _hang_chuoi(ts, "TUYEN_DANG_NHAP")

    py = (GOC / "api" / "main.py").read_text(encoding="utf-8")
    assert f'@cua_mo.post("{tuyen}")' in py, tuyen
    assert f'than.get("{tai_khoan}")' in py, tai_khoan
    assert f'than.get("{mat_khau}")' in py, mat_khau
    assert f'return {{"{token}": token' in py, token

    # Và màn đăng nhập dựng thân bằng chính ba hằng đó, không literal chép tay.
    man = MAN_DANG_NHAP.read_text(encoding="utf-8")
    assert f"[TRUONG_TAI_KHOAN]:" in man and f"[TRUONG_MAT_KHAU]:" in man, man
    assert "goi<unknown>(TUYEN_DANG_NHAP" in man
    assert f'"{tai_khoan}"' not in man and f'"{mat_khau}"' not in man


def test_ma_dang_nhap_sai_bang_hang_phia_api():
    """Mã mà màn đăng nhập đọc ra "sai tài khoản hoặc mật khẩu" phải là mã `api/` phát.

    `la_sai_thong_tin` đòi **cả** 401 lẫn mã này; một mã lệch làm mọi lần gõ sai
    mật khẩu hiện ra thành "Hệ thống gặp lỗi, thử lại sau".
    """
    ts = (SRC / "api" / "phien.ts").read_text(encoding="utf-8")
    assert _hang_chuoi(ts, "MA_DANG_NHAP_SAI") == MA_DANG_NHAP_SAI


def test_man_dang_nhap_phan_biet_401_dang_nhap_voi_401_ha_tang():
    """Màn đăng nhập rẽ nhánh bằng `la_sai_thong_tin`, không bằng `la_het_phien`.

    Một 401 của proxy (thân HTML, `goi.ts` gán mã `MANG`) đọc thành "bạn gõ sai
    mật khẩu" là bắt người dùng gõ lại mãi một mật khẩu đúng.
    """
    man = MAN_DANG_NHAP.read_text(encoding="utf-8")
    assert "la_sai_thong_tin(" in man
    assert "la_het_phien(" not in _bo_chu_thich(man)


# --- (10) Chat console (story 4.3) ------------------------------------------

# Hai chuỗi mới của composer. Chúng **không** nằm trong bảng Voice and Tone (bốn
# chuỗi chat của bảng - placeholder, "Đang truy vấn...", hai dòng meta - đã có
# từ 4.1), nên phép canh của chúng là "có mặt, là chuỗi, và được dùng thật".
KHOA_MICROCOPY_CHAT = frozenset({"nut_gui", "nhan_o_hoi"})

# Cửa duy nhất của tuyến hỏi đáp phía `web/`.
HOI_DAP_TS = SRC / "api" / "hoi_dap.ts"
MAN_CHAT = SRC / "app" / "ManChat.tsx"


def _hang_mang(tho: str, ten: str) -> tuple[str, ...]:
    """Giá trị của một `export const <ten> = ["a", "b"] as const;` trong TypeScript."""
    m = re.search(rf"export const {ten}[^=]*= \[(.*?)\]", tho, re.S)
    assert m, f"hoi_dap.ts phải khai hằng {ten} dạng mảng"
    return tuple(re.findall(r'"([^"]*)"', m.group(1)))


def test_microcopy_chat_du_khoa_va_duoc_dung_that(microcopy):
    """Hai chuỗi mới có mặt và mỗi chuỗi được một file `.tsx` dùng.

    Cùng luật với chín chuỗi màn đăng nhập: một khóa microcopy không ai dùng là
    một câu chữ mà bảng Voice and Tone và màn hình nói khác nhau mà không ai thấy.
    """
    thieu = KHOA_MICROCOPY_CHAT - set(microcopy)
    assert not thieu, sorted(thieu)
    tho = "\n".join(f.read_text(encoding="utf-8") for f in _file_giao_dien())
    khong_dung = sorted(k for k in KHOA_MICROCOPY_CHAT if f"MICROCOPY.{k}" not in tho)
    assert not khong_dung, f"khóa microcopy không nơi nào dùng: {khong_dung}"


def test_man_chat_dung_bon_chuoi_chat_tu_microcopy(microcopy):
    """Màn chat lấy bốn câu chữ của lượt từ `microcopy.json`, không tự soạn.

    `tu_choi` là chỗ nặng nhất: một câu viết tay trong `.tsx` lệch với hằng
    `api.hoi_dap.TEMPLATE_TU_CHOI` mà không ai thấy (khoản ledger của 3.5, đóng
    ở 4.1 bằng cách chấp nhận hai bản **có máy canh**).

    Đòi đúng `MICROCOPY.<khóa>`, không nhận một vế "hay có chuỗi `"<khóa>"` ở
    đâu đó": tên khóa trùng với nhãn của kiểu `KetCuc` (`loai: "tu_choi"`), nên
    vế ấy khớp ngay cả khi không dòng nào đọc microcopy.
    """
    tho = MAN_CHAT.read_text(encoding="utf-8")
    thieu = [
        khoa
        for khoa in ("tu_choi", "dang_truy_van", "placeholder_o_hoi", "loi_he_thong")
        if f"MICROCOPY.{khoa}" not in tho
    ]
    assert not thieu, thieu
    # Hai dòng meta đi qua `cac_manh` để tô đậm tên vai mà câu vẫn ở JSON.
    assert 'khoa="meta_luot"' in tho and 'khoa="meta_luot_tu_choi"' in tho
    assert "cac_manh(" in tho


def test_hop_dong_hoi_dap_khop_nguon_api():
    """Bốn hằng hợp đồng của `web/src/api/hoi_dap.ts` khớp đúng nguồn `api/`.

    Cùng khuôn với `test_ba_truong_cua_auth_login_khop_nguon_api` của 4.2, và vì
    cùng một lý do: e2e mock trọn tuyến nên nó xanh với bất kỳ tên nào, còn phía
    `api/` không biết `web/` gửi gì. `ThanHoiDap` khai `extra="forbid"`, nên một
    tên trường lệch là 422 cho **mọi** câu hỏi - màn chat chết ngay lượt đầu.
    """
    ts = HOI_DAP_TS.read_text(encoding="utf-8")
    tuyen = _hang_chuoi(ts, "TUYEN_HOI_DAP")
    truong = _hang_chuoi(ts, "TRUONG_CAU_HOI")

    py = (GOC / "api" / "main.py").read_text(encoding="utf-8")
    assert f'@cua_dong.post("{tuyen}")' in py, tuyen
    assert set(ThanHoiDap.model_fields) == {truong}, truong

    assert _hang_mang(ts, "KHOA_ENVELOPE") == KHOA_ENVELOPE
    assert _hang_mang(ts, "KHOA_META") == KHOA_META


def test_trich_dan_ts_khai_du_sau_khoa_dong():
    """Kiểu citation phía `web/` khai đủ sáu khóa của `adapters/trich_dan.py`.

    Story 4.3 chỉ **đếm** `citations`, nhưng khai đủ ở đây để 4.4 lắp cite-row
    vào mà không phải đổi hợp đồng.
    """
    from adapters.trich_dan import KHOA_TRICH_DAN

    ts = HOI_DAP_TS.read_text(encoding="utf-8")
    assert _hang_mang(ts, "KHOA_TRICH_DAN") == KHOA_TRICH_DAN


# Mọi cách đặt một trần thời gian phía trình duyệt cho một lượt hỏi.
MAU_TRAN_THOI_GIAN = re.compile(r"\bsetTimeout\b|\bsetInterval\b|\bAbortSignal\b|\bAbortController\b")


def test_khong_file_nao_trong_web_src_dat_tran_thoi_gian():
    """Không timeout cứng phía UI (NFR-08 không đặt SLA), và đây là phép quét.

    Một đợt hỏi thật đã đo tới hàng chục giây; một `setTimeout` thêm vào "cho
    chắc" cắt đúng những câu chậm nhất, tức đúng những câu đáng xem trong buổi
    demo. Luật rẻ để viết và đắt để phát hiện lại, nên nó là một phép quét chứ
    không phải một dòng văn xuôi. Chú thích bị bỏ trước khi quét, nếu không luật
    này phạt đúng những chỗ giải thích luật.
    """
    xau = [
        str(f.relative_to(GOC))
        for f in _file_giao_dien()
        if MAU_TRAN_THOI_GIAN.search(_bo_chu_thich(f.read_text(encoding="utf-8")))
    ]
    assert not xau, xau


def test_bo_do_tran_thoi_gian_bat_ca_bon_cach_viet():
    """Chấm chính bộ dò, để nó không thành một regex không bao giờ khớp."""
    assert MAU_TRAN_THOI_GIAN.search("const t = setTimeout(huy, 30000);")
    assert MAU_TRAN_THOI_GIAN.search("setInterval(poll, 5000)")
    assert MAU_TRAN_THOI_GIAN.search("signal: AbortSignal.timeout(30000)")
    assert MAU_TRAN_THOI_GIAN.search("new AbortController()")
    assert not MAU_TRAN_THOI_GIAN.search("await goi(TUYEN_HOI_DAP, { than })")


def test_man_chat_di_qua_luat_het_phien_chung():
    """401 giữa một lượt đi qua `la_het_phien`, và URL hết phiên là một hàm.

    Đây là nhánh **duy nhất** của màn chat được điều hướng; `test_khong_file_nao_ngoai_phien_ts_tu_so_401`
    canh chiều còn lại (không ai tự so status). `duong_het_phien()` chứ không
    một chuỗi ghép tay: `KhungApp` và màn chat phải về **đúng một** URL.
    """
    tho = MAN_CHAT.read_text(encoding="utf-8")
    assert "la_het_phien(" in tho
    assert "duong_het_phien()" in tho
    khung = (SRC / "khung" / "KhungApp.tsx").read_text(encoding="utf-8")
    assert "duong_het_phien()" in khung
    phien = (SRC / "api" / "phien.ts").read_text(encoding="utf-8")
    assert re.search(r"export function duong_het_phien\(", phien)


def test_route_goc_boc_man_chat():
    """`/` là server component mỏng bọc `ManChat`, giữ tiêu đề từ `dieu_huong.json`."""
    tho = (SRC / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "ManChat" in tho and "dieu_huong" in tho
    assert '"use client"' not in tho, "page.tsx là server component"
    assert MAN_CHAT.read_text(encoding="utf-8").startswith('"use client"')


def test_microcopy_ts_chi_mot_mau_cho_trong():
    """`dien()` và `cac_manh()` dùng **một** mẫu chỗ trống, khai một lần.

    Docstring của `cac_manh` khẳng định nó nhận cùng tập chỗ trống với `dien`;
    hai regex chép nhau là hai regex lệch nhau ở lần sửa đầu tiên, và khi đó một
    chuỗi microcopy điền được ở một hàm mà không điền được ở hàm kia - triệu
    chứng là một `{vai}` trần hiện trên màn chat.
    """
    tho = (SRC / "microcopy.ts").read_text(encoding="utf-8")
    assert tho.count("[a-z][a-z0-9_]*") == 1, "mẫu chỗ trống phải khai đúng một lần"
    assert "function mau_cho_trong(" in tho
    goi = [d for d in tho.splitlines() if "mau_cho_trong()" in d and "function" not in d]
    assert len(goi) == 2, goi


def test_var_css_cua_globals_da_duoc_phu():
    """Phép quét `var(--x)` đã phủ `globals.css`, và đây là phép canh giữ nó phủ.

    `_file_giao_dien()` lấy cả `.css`, nên `test_moi_var_trong_web_src_la_bien_bien_css_sinh_ra`
    đã chấm từng tên biến trong `globals.css`; không cần một phép quét thứ hai.
    Test này chỉ khẳng định file ấy còn nằm trong tập quét - thu `_file_giao_dien`
    về `.ts`/`.tsx` là một lần sửa im lặng làm mất phép canh kia.
    """
    duong = [f.relative_to(GOC).as_posix() for f in _file_giao_dien()]
    assert "web/src/app/globals.css" in duong, duong
