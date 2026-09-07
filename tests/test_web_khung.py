"""Khung web (story 4.1): token, microcopy, điều hướng và ghim phiên bản của `web/`.

Máy chủ CI không có node, nên mọi phép canh ở đây **chỉ đọc file** dưới `web/`
bằng stdlib cộng PyYAML (đọc frontmatter DESIGN.md). Không import gì từ `web/`,
không chạy `next`, không cần `node_modules`.

Vì sao token và microcopy là JSON chứ không phải TS: để chính file này đối chiếu
được chúng với nguồn chuẩn (frontmatter DESIGN.md, hằng `api.hoi_dap.TEMPLATE_TU_CHOI`)
mà không cần một trình phân tích TypeScript. Một bản chép lệch một hex, một chuỗi
UI mang em dash, một route không có mục sidebar - cả ba đỏ ở `uv run pytest`
trước khi ai mở trình duyệt.

Tám nhóm test. Bảy nhóm đầu đúng thứ tự spec 4.1:
(1) `tokens.json` bằng frontmatter DESIGN.md từng giá trị;
(2) tương phản WCAG >= 4.5:1 cho các cặp chữ/nền đã khai;
(3) sàn chữ 13px ở token và ở mọi `.css`/`.ts`/`.tsx` của `web/src`;
(4) microcopy không em dash, không "không chỉ", và nguyên văn theo bảng Voice and Tone;
(5) `tu_choi` bằng đúng hằng phía `api/`;
(6) mục sidebar và route `web/src/app/*/page.tsx` khớp một-một (trừ trang mẫu,
    và trang mẫu bị `src/proxy.ts` chặn 404 ở production);
(7) `package.json` ghim `next`, `cytoscape`, `engines.node`, danh sách dependency đóng.
Nhóm (8) là luật khung: không `localStorage`, không gọi thẳng `:8000`, một cửa
fetch duy nhất, rewrite `/api/*`, route mở `/dang-nhap`, và mọi `var(--x)` trong
`web/src` phải là biến mà `bien_css.ts` sinh ra.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from api.hoi_dap import TEMPLATE_TU_CHOI

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
)

# Route không có mục sidebar và cố ý như vậy: trang mẫu dev-only trả 404 ở
# production. Đây là ngoại lệ **có tên** duy nhất của nhóm (6).
ROUTE_KHONG_CO_MUC = {"/mau"}


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
    return ten if ten.startswith("#") else tokens["colors"][ten]


@pytest.mark.parametrize("chu,nen", CAP_TUONG_PHAN)
def test_tuong_phan_toi_thieu_4_5(tokens, chu, nen):
    ty_le = ty_le_tuong_phan(_hex(tokens, chu), _hex(tokens, nen))
    assert ty_le >= 4.5, f"{chu} trên {nen}: {ty_le:.2f}:1 < 4.5:1"


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

# 17 chuỗi của bảng Voice and Tone (EXPERIENCE.md) cộng bốn chuỗi khung 4.1.
KHOA_MICROCOPY_BAT_BUOC = {
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


def test_trang_mau_tu_choi_o_production():
    tho = (SRC / "app" / "mau" / "page.tsx").read_text(encoding="utf-8")
    assert "notFound()" in tho and "production" in tho


def test_proxy_chan_dung_tap_route_dev_only_o_production():
    """`src/proxy.ts` là rào thật cho trang dev-only (đo 07/09: `notFound()` trong
    page prerender tĩnh chỉ cho thân 404 với mã HTTP 200). Matcher phải bằng
    đúng tập `ROUTE_KHONG_CO_MUC` và có nhánh 404 theo `NODE_ENV`."""
    tho = (SRC / "proxy.ts").read_text(encoding="utf-8")
    m = re.search(r"matcher:\s*(\[[^\]]*\]|\"[^\"]+\")", tho)
    assert m, "proxy.ts phải export config.matcher"
    matcher = set(re.findall(r"\"([^\"]+)\"", m.group(1)))
    assert matcher == ROUTE_KHONG_CO_MUC
    assert "status: 404" in tho and "NODE_ENV" in tho


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
    không được gate bởi chính phiên mà nó sắp tạo, và không gọi `/auth/toi`."""
    tho = (SRC / "khung" / "KhungApp.tsx").read_text(encoding="utf-8")
    assert 'DUONG_DANG_NHAP = "/dang-nhap"' in tho
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
