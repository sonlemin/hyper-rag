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
Nhóm (11) là cite-row, slab bôi đen và dòng hạn chế L1 (story 4.4): ba chuỗi mới
cùng năm chuỗi đã treo từ 4.1 được dùng thật, hai bảng nhãn hiển thị của `web/`
có khóa đúng bằng `core.slots.SLOT_ROLES` và bằng `config/hang-do-nhay.yaml`,
ngữ pháp dấu che của `web/` dựng ra đúng chuỗi mà `core.masking` dựng ra, và
không file nào trong `web/src` in id hyperedge thật.
Nhóm (12) là "xem như" (story 4.5): chín chuỗi mới có mặt và được dùng thật,
bảng mô tả vùng quyền có khóa đúng bằng khóa `NHAN_VAI` và `NHAN_VAI` phủ đủ vai
của bốn bảng chính sách, ba tuyến cùng tên trường ghim hai chiều với
`api/main.py`, và `maxLength` của ô hỏi bằng `api.hoi_dap.DAI_CAU_HOI_TOI_DA`.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
import yaml

from api.hoi_dap import (
    DAI_CAU_HOI_TOI_DA,
    KHOA_ENVELOPE,
    KHOA_META,
    TEMPLATE_TU_CHOI,
    ThanHoiDap,
)
from api.xac_thuc import MA_DANG_NHAP_SAI
from core import masking
from core.slots import OWNER_SLOT, SLOT_ROLES

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
    # Bốn cặp của cite-row và dòng hạn chế L1 (story 4.4). Chữ của hàng L1 là
    # `level-l1-ink` chứ không `level-l1` như DESIGN.md viết, vì `level-l1` trên
    # nền trắng chỉ đạt 4,87:1 khi hàng chưa hover nhưng tụt xuống 4,08:1 trên
    # nền hover `primary-tint` - cùng lý lẽ đã đổi badge L1 sang `level-l1-ink`
    # ở story 4.1.
    #
    # Cặp trắng trên `level-l1` phủ **hai** bề mặt, và một trong hai chưa tồn
    # tại ở trạng thái mà cặp này mô tả. Số vuông của hàng L1 dùng nó đúng như
    # đo (4,87:1). Nút xin break-glass thì ở story 4.4 **luôn** `disabled` với
    # `opacity: 0.6`, nên chữ hợp thành trên nền `note_l1` chỉ còn khoảng
    # 2,42:1; WCAG 1.4.3 miễn cho điều khiển vô hiệu nên đó không phải một lỗi
    # hình, nhưng con số 4,87 dưới đây là của **trạng thái bật** mà Epic 5 mở.
    # Giữ cặp ở đây chính vì thế: nó là phép canh sẵn cho ngày nút hết mờ, chứ
    # không phải một phát biểu về màn hình hôm nay.
    ("#FFFFFF", "level-l1"),
    ("level-l1-ink", "surface-card"),
    ("level-l1-ink", "primary-tint"),
    ("ink-muted", "primary-tint"),
    # Bốn cặp của "xem như" (story 4.5), theo luật retro 4.1 "không còn cặp
    # chữ/nền nào không ai chấm". Mốc đổi vai nằm thẳng trên nền khối cuộn
    # (7,53:1); dòng "về dev01 · DevOps" của mục thoát nằm trên nền hổ phách
    # (5,00:1); hai dòng của mục vai **đang chọn** nằm trên `primary-tint-soft`
    # (14,08:1 và 5,09:1). Nhãn tiêu đề dropdown cố ý **không** dùng
    # `ink-faint` như mockup: 3,06:1 trên nền trắng, dưới sàn 4,5:1.
    ("level-l1-ink", "surface-stream"),
    ("ink-muted", "level-l1-bg"),
    ("ink", "primary-tint-soft"),
    ("ink-muted", "primary-tint-soft"),
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


def test_muc_trich_dan_cua_web_khop_gia_tri_phia_api():
    """Hai mức mà một citation mang được, so **giá trị** với `adapters/`.

    Cùng khuôn với `test_trich_dan_ts_khai_du_sau_khoa_dong` ngay dưới, và vì
    cùng một lý do: `MUC_TRICH_DAN` ở `hoi_dap.ts` là một bản chép tay, e2e mock
    trọn tuyến nên nó xanh với bất kỳ tập nào, và phía `api/` không biết `web/`
    nhận gì. Phép canh cũ chỉ hỏi chuỗi `"MUC_TRICH_DAN"` có xuất hiện trong
    thân `la_trich_dan`, tức nó chấm việc hằng **được dùng** chứ không chấm việc
    hằng **đúng**.

    Phía `api/` tập ấy **dẫn xuất** từ `NAMESPACE_MIN_LEVEL[hyperedges]` chứ
    không viết tay, nên hạ ngưỡng ấy là ở đó có thêm một mức hợp lệ trong khi
    `web/` từ chối mọi citation mang mức mới thành `ENVELOPE_LA` - tức mọi lượt
    trả lời thành một hộp đỏ. So theo **tập** vì phía `api/` là `frozenset`;
    thứ tự của mảng TS không mang nghĩa gì ngoài thứ tự đọc.
    """
    from adapters.trich_dan import MUC_TRICH_DAN

    ts = HOI_DAP_TS.read_text(encoding="utf-8")
    assert set(_hang_mang(ts, "MUC_TRICH_DAN")) == set(MUC_TRICH_DAN)


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


# --- (11) Cite-row, slab bôi đen và dòng hạn chế L1 (story 4.4) --------------

# Ba chuỗi mới của khối nguồn và của nút xin break-glass, cộng **năm chuỗi đã
# treo từ 4.1**: chúng nằm trong bảng Voice and Tone từ đầu nhưng tới story này
# mới có bề mặt dùng. Một khóa microcopy không ai dùng là một câu chữ mà bảng
# Voice and Tone và màn hình nói khác nhau mà không ai thấy.
KHOA_MICROCOPY_CITE = frozenset(
    {
        "slab_owner",
        "khoi_nguon",
        "tooltip_chua_kha_dung",
        "slab_che",
        "dong_han_che_l1",
        "nut_xin_truy_cap",
        "tooltip_badge_muc",
        "placeholder_l1_trich_dan",
    }
)

NHAN_TS = SRC / "nhan.ts"
DAU_CHE_TS = SRC / "app" / "dau_che.ts"
KHOI_NGUON_TSX = SRC / "app" / "KhoiNguon.tsx"
DONG_HAN_CHE_TSX = SRC / "app" / "DongHanChe.tsx"

HANG_DO_NHAY = GOC / "config" / "hang-do-nhay.yaml"
GLOB_POLICY = "policy-*.yaml"


def _hang_chuoi_o(tho: str, ten: str, nguon: str) -> str:
    """Giá trị của một `export const <ten> = "..."` trong một file TS bất kỳ."""
    m = re.search(rf'export const {ten}(?::[^=]*)? = "([^"]*)"', tho)
    assert m, f"{nguon} phải khai hằng {ten}"
    return m.group(1)


def _khoa_bang_ts(tho: str, ten: str) -> tuple[str, ...]:
    """Khóa của một `export const <ten>: Record<string, string> = { a: "...", }`.

    Đọc văn bản thô chứ không chạy TypeScript: máy chủ CI không có node, và cả
    file test này đứng trên đúng nguyên tắc đó.
    """
    m = re.search(rf"export const {ten}(?::[^=]*)? = \{{(.*?)\n\}};", tho, re.S)
    assert m, f"nhan.ts phải khai bảng {ten}"
    return tuple(re.findall(r"^\s*([a-z_][a-z0-9_]*):", m.group(1), re.M))


def _duoc_dung(khoa: str, tho: str) -> bool:
    """Một khóa microcopy được **đọc thật**, không chỉ tình cờ xuất hiện.

    Đúng hai cách đọc microcopy tồn tại trong `web/`: `MICROCOPY.<khóa>` cho
    chuỗi không có chỗ trống, và `dien("<khóa>"` / `cac_manh("<khóa>"` cho chuỗi
    có. Vế nới lỏng cũ (`'"<khóa>"' in tho`, bất kỳ đâu) là đúng dạng mà vòng
    review 4.3 đã bỏ và ghi lý do ở `test_man_chat_dung_bon_chuoi_chat_tu_microcopy`:
    với `khoi_nguon` thì riêng `className="khoi_nguon"` đã làm test xanh kể cả
    khi không dòng nào gọi `dien("khoi_nguon", ...)`, và với `slab_che` thì một
    `data-slab="slab_che"` cũng thế.
    """
    return any(
        mau in tho for mau in (f"MICROCOPY.{khoa}", f'dien("{khoa}"', f'cac_manh("{khoa}"')
    )


def test_microcopy_cite_du_khoa_va_duoc_dung_that(microcopy):
    thieu = KHOA_MICROCOPY_CITE - set(microcopy)
    assert not thieu, sorted(thieu)
    tho = "\n".join(f.read_text(encoding="utf-8") for f in _file_giao_dien())
    khong_dung = sorted(k for k in KHOA_MICROCOPY_CITE if not _duoc_dung(k, tho))
    assert not khong_dung, f"khóa microcopy không nơi nào dùng: {khong_dung}"


def test_bo_do_microcopy_duoc_dung_khong_nhan_ten_khoa_tran():
    """Chấm chính bộ dò: một tên khóa nằm trong `className` hay `data-*` không
    phải là một lần đọc microcopy."""
    assert _duoc_dung("khoi_nguon", 'dien("khoi_nguon", { n: 2 })')
    assert _duoc_dung("tu_choi", "<p>{MICROCOPY.tu_choi}</p>")
    assert _duoc_dung("meta_luot", 'cac_manh("meta_luot", gia_tri)')
    assert not _duoc_dung("khoi_nguon", '<div className="khoi_nguon" data-khoi-nguon>')
    assert not _duoc_dung("slab_che", '<span data-slab="slab_che" />')


def test_bang_nhan_slot_cua_web_co_khoa_dung_bang_core():
    """Bảng nhãn hiển thị 8 vai có khóa **đúng bằng** `core.slots.SLOT_ROLES`.

    Ghim **khóa**, không ghim giá trị: nhãn `remediation` của `web/` là "hành
    động khắc phục" (EXPERIENCE.md) còn của `core/facts.py` là "cách xử lý", và
    chỗ lệch đó là **cố ý** - nhãn ở `core/` đi vào `PROMPT_TRICH_XUAT` đã đóng
    băng cùng ba vòng đo đã trả tiền (`tests/test_cham_trich_xuat.py` so
    `PROMPT_KHONG_TU_DIEN` từng byte). Thêm một vai vào `core/` mà quên bảng này
    là một slab hiện ra tên vai tiếng Anh giữa câu trả lời.
    """
    khoa = _khoa_bang_ts(NHAN_TS.read_text(encoding="utf-8"), "NHAN_SLOT")
    assert khoa == SLOT_ROLES


def test_bang_nhan_loai_cua_web_co_khoa_dung_bang_config():
    """Bảng nhãn loại nội dung có khóa **đúng bằng** `config/hang-do-nhay.yaml`.

    Thêm một loại nội dung vào bảng hạng mà quên bảng này là một cite-row hiện
    khóa snake_case giữa danh sách nguồn; ở đây nó đỏ và nêu đúng khóa thiếu.
    """
    hang = yaml.safe_load(HANG_DO_NHAY.read_text(encoding="utf-8"))["ranks"]
    khoa = _khoa_bang_ts(NHAN_TS.read_text(encoding="utf-8"), "NHAN_LOAI")
    assert set(khoa) == set(hang), sorted(set(hang) ^ set(khoa))


def test_bang_nhan_scope_cua_web_co_khoa_dung_bang_policy():
    """Bảng nhãn scope có khóa đúng bằng **hợp** `scopes:` của mọi bảng chính sách.

    Nguồn ghim là `config/policy-*.yaml` chứ không phải corpus, và lý do là một
    phát biểu kiểm được chứ không phải một lựa chọn tiện tay: scope là thành
    phần trái của khóa lọc (AD-4), nên một scope mà không bảng nào cho vai nào
    chạm tới thì không vai nào có khóa cho nó, mọi tài liệu của nó là L0 với tất
    cả, và **không citation nào mang được nó** ra tới cite-row. Tập scope hiện
    được lên một hàng nguồn vì thế đúng bằng hợp đó.

    Mở một scope mới cho một vai mà quên bảng này là một cite-row hiện
    `khach_hang_c` giữa danh sách nguồn; ở đây nó đỏ và nêu đúng khóa thiếu.
    """
    tu_policy: set[str] = set()
    for f in sorted((GOC / "config").glob(GLOB_POLICY)):
        bang = yaml.safe_load(f.read_text(encoding="utf-8"))
        for vai in bang["roles"].values():
            tu_policy.update(vai["scopes"])
    assert tu_policy, "không đọc được scope nào từ config/policy-*.yaml"
    khoa = _khoa_bang_ts(NHAN_TS.read_text(encoding="utf-8"), "NHAN_SCOPE")
    assert set(khoa) == tu_policy, sorted(set(khoa) ^ tu_policy)


def test_bang_nhan_cua_web_tra_nguyen_khoa_khi_khoa_la():
    """Khóa lạ hiện nguyên khóa, đúng khuôn `nhan_vai` của 4.2.

    Một nhãn đoán là một chỗ UI nói khác với dữ liệu server trả về.
    """
    tho = NHAN_TS.read_text(encoding="utf-8")
    for ham, bang in (
        ("nhan_slot", "NHAN_SLOT"),
        ("nhan_loai", "NHAN_LOAI"),
        ("nhan_scope", "NHAN_SCOPE"),
    ):
        m = re.search(rf"export function {ham}\([^)]*\)[^{{]*\{{(.*?)\n\}}", tho, re.S)
        assert m, f"nhan.ts phải export hàm `{ham}`"
        assert f"{bang}[" in m.group(1) and "??" in m.group(1), m.group(1)


def test_ngu_phap_dau_che_cua_web_khop_core():
    """Dấu che của `web/` dựng ra **đúng chuỗi** mà `core.masking` dựng ra.

    `web/` nhận diện dấu che bằng cách **dựng lại**, đúng khuôn
    `core.masking.la_dau_che`, chứ không bằng một regex tự do: một tên entity
    thật bắt đầu bằng `[owner:` sẽ qua được một phép so tiền tố, và khi đó một
    mảnh văn bản có thật biến thành một slab đen.

    Ba hằng cộng hình dạng `[{trường}:{lý do}]` khóa trọn tập chuỗi hợp lệ: bảy
    vai ra `masked`, `owner` ra `group`, và `[owner:<nhóm>]` cho nhóm của chính
    lượt đang render. Đổi hình dạng dấu che ở `core/` là test này đỏ trước khi
    ai mở trình duyệt.
    """
    ts = DAU_CHE_TS.read_text(encoding="utf-8")
    assert _hang_chuoi_o(ts, "LY_DO_CHINH_SACH", "dau_che.ts") == masking.MASK_REASON_POLICY
    assert _hang_chuoi_o(ts, "LY_DO_OWNER", "dau_che.ts") == masking.MASK_REASON_OWNER
    assert _hang_chuoi_o(ts, "VAI_OWNER", "dau_che.ts") == OWNER_SLOT
    # Hình dạng `dau_che_truong`, ghim từ **cả hai phía** trong cùng một test.
    assert masking.dau_che_truong("vai", "ly_do") == "[vai:ly_do]"
    assert "`[${vai}:${ly_do}]`" in ts, ts
    # Và `web/` lấy danh mục vai từ chính bảng nhãn đã ghim với `SLOT_ROLES`,
    # không gõ lại tám tên.
    assert "VAI_SLOT" in ts


# Hai họ dấu che mà `web/` **cố ý không** đổi thành slab, nêu đích danh để một
# `MASK_REASON_*` thứ năm mọc ở `core/` là đỏ chứ không âm thầm đi qua.
#
# Cả hai đều tới được `answer` thật: chúng nằm trong `_VI_DU_DAU_CHE` của
# `adapters/tra_loi.py` mà prompt v2 dạy model chép nguyên dấu che vào câu trả
# lời. Để nguyên văn là **quyết định của khối `Always`** đã đóng băng trong spec
# 4.4 ("`[<vai>:masked]` cho 7 vai, `[owner:group]`, `[owner:<nhóm>]`... mọi
# chuỗi ngoặc vuông khác là chữ thường"), không phải một chỗ bỏ sót: `l2_only`
# mang tên trường `description` và `no_key` mang tên trường `neighbor_id`, hai
# thứ không phải vai slot nên chúng không có nhãn tiếng Việt trong `NHAN_SLOT`
# và một slab "[description: che]" sẽ nói bằng nửa tiếng Anh giữa câu.
HO_DAU_CHE_DE_NGUYEN_VAN = frozenset({"l2_only", "no_key"})


def test_web_phu_ba_ho_dau_che_cua_vai_slot_va_loai_dung_hai_ho_con_lai():
    """`web/` dựng đủ ba họ dấu che của vai slot, và **chỉ** ba họ ấy.

    Dựng tập kỳ vọng bằng Python từ chính bốn cửa của `core/masking.py` thay vì
    gõ lại chuỗi: `dau_che` (7 vai ra `masked`, `owner` ra `group`),
    `dau_che_owner` (nhóm), `dau_che_lan_can_khong_khoa` (`no_key`) và
    `dau_che_truong(..., MASK_REASON_L2_ONLY)`. Hai họ sau nằm trong
    `HO_DAU_CHE_DE_NGUYEN_VAN` và test đọc chính frozenset ấy, nên thêm một lý
    do che thứ năm ở `core/` là test này đỏ và người thêm phải quyết một lần
    rằng `web/` bôi đen nó hay để nguyên - thay vì để một dấu che mới lặng lẽ
    hiện ra nguyên văn `[x:y]` giữa một câu trả lời trên máy chiếu.
    """
    ts = DAU_CHE_TS.read_text(encoding="utf-8")

    # Ba họ phải phủ: bảy vai `masked`, `owner` ra `group`, `owner` mang nhóm.
    ly_do_phu = set()
    for slot in SLOT_ROLES:
        dau = masking.dau_che(slot)
        assert dau.startswith("[") and dau.endswith("]"), dau
        ly_do_phu.add(dau[1:-1].split(":", 1)[1])
    assert ly_do_phu == {masking.MASK_REASON_POLICY, masking.MASK_REASON_OWNER}, ly_do_phu
    # `dau_che_owner` là cửa thứ ba, và `web/` dựng nó bằng cùng hình dạng.
    assert masking.dau_che_owner("DevOps") == "[owner:DevOps]"
    assert "dau_che_owner(nhom)" in ts, ts

    # Hai họ để nguyên văn, dựng từ chính `core/` chứ không gõ lại chuỗi.
    de_nguyen = {
        masking.dau_che_lan_can_khong_khoa(),
        masking.dau_che_truong("description", masking.MASK_REASON_L2_ONLY),
    }
    ly_do_de_nguyen = {d[1:-1].split(":", 1)[1] for d in de_nguyen}
    assert ly_do_de_nguyen == HO_DAU_CHE_DE_NGUYEN_VAN, ly_do_de_nguyen
    # Và `web/` thật sự không dựng chúng: không lý do nào của hai họ ấy xuất
    # hiện trong một chuỗi của `dau_che.ts`.
    for ly_do in HO_DAU_CHE_DE_NGUYEN_VAN:
        assert f'"{ly_do}"' not in ts, f"{ly_do} không được thành một họ slab"
    # Quyết định ấy phải được **viết ra** ngay trong file, không chỉ sống ở đây.
    assert "l2_only" in ts and "no_key" in ts, "dau_che.ts phải khai vì sao loại hai họ"


def test_danh_muc_ly_do_che_cua_core_van_du_bon():
    """Bốn `MASK_REASON_*` của `core/masking.py`, không hơn.

    `test_web_phu_ba_ho_dau_che_cua_vai_slot_va_loai_dung_hai_ho_con_lai` đứng
    trên phép chia "ba họ bôi đen, hai họ để nguyên". Một hằng thứ năm ở `core/`
    không rơi vào bên nào cả, và không phép so nào ở trên thấy nó. Ở đây thì có.
    """
    ly_do = {ten: v for ten, v in vars(masking).items() if ten.startswith("MASK_REASON_")}
    assert set(ly_do) == {
        "MASK_REASON_POLICY",
        "MASK_REASON_OWNER",
        "MASK_REASON_L2_ONLY",
        "MASK_REASON_NO_KEY",
    }, sorted(ly_do)


def test_vai_slot_cua_web_dan_xuat_tu_bang_nhan():
    """`VAI_SLOT` dẫn xuất từ `NHAN_SLOT`, không phải một danh sách chép tay.

    Hai bản của danh mục 8 vai trong cùng một thư mục là hai bản trôi khỏi nhau
    ở lần sửa đầu tiên; `test_bang_nhan_slot_cua_web_co_khoa_dung_bang_core` chỉ
    canh được một bản.
    """
    tho = NHAN_TS.read_text(encoding="utf-8")
    assert re.search(r"export const VAI_SLOT[^=]*= Object\.keys\(NHAN_SLOT\)", tho), tho


def test_ma_hien_thi_la_ma_hien_thi_chu_khong_phai_id_that():
    """Tên nguồn trên cite-row là `HE-nn` đánh theo thứ tự citation trong lượt."""
    ts = HOI_DAP_TS.read_text(encoding="utf-8")
    assert _hang_chuoi_o(ts, "TIEN_TO_MA_HIEN_THI", "hoi_dap.ts") == "HE-"
    assert re.search(r"export function ma_hien_thi\(", ts), ts
    assert "padStart(2" in ts, "hai chữ số, tràn thì nhiều hơn"


# Mọi cách một id hyperedge lọt vào DOM qua một chỗ chèn JSX: `{c.id}` trần,
# cắt ngắn (`{c.id.slice(0, 8)}`), ép kiểu (`{String(c.id)}`), hay lồng trong
# một template (`` {`nguồn ${c.id}`} ``). Bộ dò cũ chỉ khớp dạng trần, tức nó
# bắt đúng ca mà không ai viết và bỏ qua ba ca mà người ta thật sự viết khi
# muốn "chỉ hiện vài ký tự đầu cho gọn" - và một id cắt ngắn vẫn là một id.
MAU_IN_ID = re.compile(r"\{[^{}]*\b[A-Za-z_]\w*\.id\b[^{}]*\}")

# `key={...}` là khóa React, không phải nội dung DOM. Bỏ **riêng đoạn ấy** rồi
# mới quét phần còn lại: `continue` cả dòng (bản cũ) làm một id thật in ra trên
# đúng dòng có `key={` vẫn lọt, và JSX một dòng thì đó là chuyện thường.
MAU_KHOA_REACT = re.compile(r"\bkey=\{[^{}]*\}")

# Danh mục **đóng** những biến có trường `id` mà `id` ấy không phải id
# hyperedge. Đúng một tên: `luot` là một lượt chat và `Luot.id` là một bộ đếm
# `number` sinh ở client (`dem_ref`), không bao giờ đến từ server.
# `test_luot_id_van_la_so_nen_ngoai_le_con_dung` giữ phát biểu ấy đúng, nên đây
# là một ngoại lệ **có máy canh** chứ không phải một lần nới cho test xanh.
BIEN_ID_KHONG_PHAI_HYPEREDGE = ("luot",)

MAU_ID_NGOAI_LE = re.compile(
    r"\b(?:" + "|".join(BIEN_ID_KHONG_PHAI_HYPEREDGE) + r")\.id\b"
)


def _bo_khoa_react(dong: str) -> str:
    return MAU_ID_NGOAI_LE.sub("", MAU_KHOA_REACT.sub("", dong))


def test_luot_id_van_la_so_nen_ngoai_le_con_dung():
    """`Luot.id` là `number`, nên `luot.id` không thể là một id hyperedge.

    Ngoại lệ `BIEN_ID_KHONG_PHAI_HYPEREDGE` đứng trên đúng phát biểu này. Đổi
    `Luot.id` sang `string` (ví dụ để lấy một id do server cấp) là ngoại lệ ấy
    hết đúng, và ở đây nó đỏ thay vì để một id thật đi ra DOM qua một cái tên
    đã được miễn quét.
    """
    tho = MAN_CHAT.read_text(encoding="utf-8")
    m = re.search(r"type Luot = \{(.*?)\n\};", tho, re.S)
    assert m, "ManChat.tsx phải khai kiểu `Luot`"
    assert re.search(r"^\s*id: number;", m.group(1), re.M), m.group(1)


def test_khong_file_nao_trong_web_src_in_id_hyperedge():
    """Id hyperedge thật **không bao giờ** vào DOM (epic 4: chỉ mã hiển thị `HE-nn`)."""
    xau = []
    for f in _file_giao_dien():
        for so_dong, dong in enumerate(
            _bo_chu_thich(f.read_text(encoding="utf-8")).splitlines(), 1
        ):
            if MAU_IN_ID.search(_bo_khoa_react(dong)):
                xau.append(f"{f.relative_to(GOC)}:{so_dong}: {dong.strip()}")
    assert not xau, xau
    # Và khối nguồn - nơi duy nhất render citation - không chạm `.id` một lần nào.
    assert ".id" not in _bo_chu_thich(KHOI_NGUON_TSX.read_text(encoding="utf-8"))


def test_bo_do_in_id_bat_dung_cho():
    """Chấm chính bộ dò, để nó không thành một regex không bao giờ khớp."""
    for dong in (
        "<span>{c.id}</span>",
        "title={trich_dan.id}",
        "<span>{c.id.slice(0, 8)}</span>",
        "<span>{String(c.id)}</span>",
        "<span>{`nguồn ${c.id}`}</span>",
        # Một id thật in ra trên **đúng dòng** có một `key={...}` hợp lệ.
        "<li key={i}>{c.id}</li>",
    ):
        assert MAU_IN_ID.search(_bo_khoa_react(dong)), dong
    for dong in (
        "<span>{ma_hien_thi(i)}</span>",
        "<div className='luot' key={luot.id}>",
        "<CiteRow key={ma_hien_thi(i)} trich_dan={c} so={i} />",
        # Hai dòng thật của `ManChat.tsx`: `luot.id` là bộ đếm lượt chat, không
        # phải một id hyperedge (ngoại lệ có tên, có test canh).
        "mo_nguon={luot.mo_nguon ?? luot.id === id_tra_loi_moi_nhat}",
        "dat_mo_nguon={(mo) => dat_mo_nguon(luot.id, mo)}",
    ):
        assert not MAU_IN_ID.search(_bo_khoa_react(dong)), dong
    # Nhưng ngoại lệ chỉ miễn đúng tên ấy: một `trich_dan.id` trên cùng dòng
    # với một `luot.id` vẫn phải bị bắt.
    assert MAU_IN_ID.search(_bo_khoa_react("<b key={luot.id}>{trich_dan.id}</b>"))


def test_la_envelope_kiem_tung_citation():
    """Phép kiểm thứ tư của 4.3 (`Array.isArray`) nay siết hình **từng** citation.

    Từ 4.4 mỗi citation thành một hàng mang badge mức, nên một `level` lạ vẽ ra
    một badge sai về quyền. Fail-closed ở đây rẻ hơn một hàng nói dối.
    """
    ts = HOI_DAP_TS.read_text(encoding="utf-8")
    assert re.search(r"export function la_trich_dan\(", ts), ts
    assert "t.citations.every(la_trich_dan)" in ts, ts
    # Sáu khóa và hai mức đi qua chính hai hằng đã ghim với `adapters/`, không
    # gõ lại tên khóa trong thân hàm.
    m = re.search(r"export function la_trich_dan\(.*?\n\}", ts, re.S)
    than = m.group(0)
    assert "KHOA_TRICH_DAN" in than and "MUC_TRICH_DAN" in than, than
    # Và `id` phải là chuỗi không rỗng, không chỉ "có khóa". Predicate hứa
    # `id: string` cho mọi nơi gọi sau nó; `null`, `0` và `""` đều lọt phép kiểm
    # `khoa in t`, và 4.6 khóa vòng đồ thị lên chính trường đó.
    assert "chuoi_that(t.id)" in than, than


def test_man_chat_lap_ba_khoi_va_khong_dung_nhanh_tu_choi():
    """Ba khối mới nằm ở nhánh `tra_loi`; nhánh `tu_choi` không đổi một byte.

    Lượt từ chối phải giữ DOM **byte-identical** với 4.3: không khối nguồn,
    không dòng hạn chế, meta không có vế trích dẫn (L0 vô hình tuyệt đối).
    """
    tho = MAN_CHAT.read_text(encoding="utf-8")
    assert "KhoiNguon" in tho and "DongHanChe" in tho and "tach_slab(" in tho
    m = re.search(r'if \(luot\.ket_cuc\.loai === "tu_choi"\) \{(.*?)\n  \}', tho, re.S)
    assert m, "màn chat phải còn nhánh `tu_choi` riêng"
    nhanh = m.group(1)
    for cam in ("KhoiNguon", "DongHanChe", "tach_slab", "citations"):
        assert cam not in nhanh, f"nhánh từ chối không được nhắc {cam}: {nhanh}"


def test_dong_han_che_co_nut_khoa_va_khong_goi_api():
    """Nút xin truy cập khẩn cấp `disabled` kèm tooltip, và không gọi tuyến nào.

    Epic 5 chỉ bật nó lên; một `goi(` ở đây là một tuyến break-glass gọi sớm.
    """
    tho = DONG_HAN_CHE_TSX.read_text(encoding="utf-8")
    assert "disabled" in tho
    assert "MICROCOPY.tooltip_chua_kha_dung" in tho
    assert "MICROCOPY.nut_xin_truy_cap" in tho
    sach = _bo_chu_thich(tho)
    assert "goi(" not in sach and "goi<" not in sach and "fetch(" not in sach


def test_dong_han_che_bo_owner_khoi_phep_dem():
    """`owner` không vào phép đếm của dòng hạn chế L1.

    `masked_slots` ở L2 cũng mang `owner` (`vai_phai_che_hieu_luc` luôn thêm
    nó), nên đếm cả `owner` là nói "người phụ trách bị hạn chế" trong đúng câu
    vừa nêu tên nhóm phụ trách. Hằng loại trừ phải là `VAI_OWNER` chung, không
    một chuỗi `"owner"` gõ tay ở đây.
    """
    tho = DONG_HAN_CHE_TSX.read_text(encoding="utf-8")
    assert "VAI_OWNER" in tho, tho
    assert '"owner"' not in _bo_chu_thich(tho), tho


# --- (12) "Xem như": API đổi vai và UI (story 4.5) ---------------------------

# Chín chuỗi mới. Bốn chuỗi khung của điều khiển, và năm dòng mô tả vùng quyền
# lấy **nguyên văn** từ mockup `screen-role-switcher.html`. Hai chuỗi
# `chip_xem_nhu` và `divider_doi_vai` đã có từ 4.1 (chúng nằm trong bảng Voice
# and Tone) và story này là nơi dùng thật, nên chúng nằm trong danh sách.
KHOA_MICROCOPY_XEM_NHU = frozenset(
    {
        "nut_xem_nhu",
        "tieu_de_menu_vai",
        "thoat_xem_nhu",
        "ve_vai_that",
        "mo_ta_vai_devops",
        "mo_ta_vai_tech_support",
        "mo_ta_vai_sale_ba",
        "mo_ta_vai_truong_nhom",
        "mo_ta_vai_admin",
        "chip_xem_nhu",
        "divider_doi_vai",
    }
)

# Tiền tố khóa mô tả vùng quyền, khai một lần ở đây và một lần ở
# `MenuXemNhu.tsx`; hai ca dưới ghim chúng khớp nhau.
TIEN_TO_MO_TA_VAI = "mo_ta_vai_"

PHIEN_TS = SRC / "api" / "phien.ts"
XEM_NHU_TS = SRC / "api" / "xem_nhu.ts"
MENU_XEM_NHU_TSX = SRC / "khung" / "MenuXemNhu.tsx"
TOPBAR_TSX = SRC / "khung" / "Topbar.tsx"
KHUNG_APP_TSX = SRC / "khung" / "KhungApp.tsx"


def test_microcopy_xem_nhu_du_khoa_va_duoc_dung_that(microcopy):
    """Chín chuỗi mới cộng hai chuỗi treo từ 4.1, mỗi chuỗi được đọc thật.

    Cùng luật với ba nhóm trước: một khóa microcopy không ai dùng là một câu chữ
    mà bảng Voice and Tone và màn hình nói khác nhau mà không ai thấy. Năm dòng
    mô tả vùng quyền đọc qua một khóa **dựng lúc chạy** (`mo_ta_vai_${vai}`) nên
    chúng không khớp `MICROCOPY.<khóa>`; ca dưới chấm riêng chúng bằng phép so
    danh mục với `NHAN_VAI`.
    """
    thieu = KHOA_MICROCOPY_XEM_NHU - set(microcopy)
    assert not thieu, sorted(thieu)
    tho = "\n".join(f.read_text(encoding="utf-8") for f in _file_giao_dien())
    khong_dung = sorted(
        k
        for k in KHOA_MICROCOPY_XEM_NHU
        if not k.startswith(TIEN_TO_MO_TA_VAI) and not _duoc_dung(k, tho)
    )
    assert not khong_dung, f"khóa microcopy không nơi nào dùng: {khong_dung}"


def test_bang_mo_ta_vung_quyen_co_khoa_dung_bang_nhan_vai(microcopy):
    """Mỗi vai của `NHAN_VAI` có đúng một dòng mô tả, và không dòng nào thừa.

    Hai chiều, và mỗi chiều chặn một ca khác nhau. Thiếu một mô tả là một dòng
    dropdown trống nghĩa trên máy chiếu; thừa một mô tả là một khóa chết mà
    `test_microcopy_xem_nhu_du_khoa_va_duoc_dung_that` cố ý miễn quét (chúng đọc
    qua một khóa dựng lúc chạy), tức đúng chỗ một chuỗi bỏ quên sống được.
    """
    tu_nhan = {
        f"{TIEN_TO_MO_TA_VAI}{v}"
        for v in _khoa_bang_ts(PHIEN_TS.read_text(encoding="utf-8"), "NHAN_VAI")
    }
    tu_microcopy = {k for k in microcopy if k.startswith(TIEN_TO_MO_TA_VAI)}
    assert tu_nhan == tu_microcopy, sorted(tu_nhan ^ tu_microcopy)
    assert tu_nhan, "không đọc được vai nào từ `NHAN_VAI`"


def test_nhan_vai_phu_du_vai_cua_bon_bang_chinh_sach():
    """`NHAN_VAI` phủ **mọi** vai mà bốn `config/policy-*.yaml` khai.

    Danh mục vai đến từ bảng chính sách đang chạy (`GET /auth/vai` trả
    `sorted(Policy.roles)`), nên một vai có trong YAML mà không có nhãn ở đây
    hiện nguyên khóa `truong_nhom` giữa dropdown - đúng ca mà luật khóa-lạ của
    `nhan_vai` cho phép, nhưng không phải thứ được lên máy chiếu.

    Phép bao hàm chứ không đẳng thức: `NHAN_VAI` được phép mang thêm một vai mà
    hôm nay chưa bảng nào khai (một vai sắp thêm), còn chiều ngược lại thì
    không. Chiều kia có `test_bang_mo_ta_vung_quyen_co_khoa_dung_bang_nhan_vai`
    giữ cho mọi nhãn còn một dòng mô tả.
    """
    tu_policy: set[str] = set()
    for f in sorted((GOC / "config").glob(GLOB_POLICY)):
        tu_policy.update(yaml.safe_load(f.read_text(encoding="utf-8"))["roles"])
    assert tu_policy, "không đọc được vai nào từ config/policy-*.yaml"
    nhan = set(_khoa_bang_ts(PHIEN_TS.read_text(encoding="utf-8"), "NHAN_VAI"))
    assert not (tu_policy - nhan), sorted(tu_policy - nhan)


def test_ba_tuyen_xem_nhu_khop_nguon_api():
    """Ba tuyến và hai tên trường khớp đúng literal mà `api/main.py` khai.

    Cùng khuôn với `test_ba_truong_cua_auth_login_khop_nguon_api` của 4.2 và
    `test_hop_dong_hoi_dap_khop_nguon_api` của 4.3, và vì cùng một lý do: e2e
    mock trọn tuyến nên nó xanh với bất kỳ tên nào, còn phía `api/` không biết
    `web/` gửi gì. Chết im lặng ở đây là nút "Xem như" bấm vào ra 404
    `TUYEN_KHONG_CO` mà giao diện đọc thành "Hệ thống gặp lỗi".
    """
    ts = PHIEN_TS.read_text(encoding="utf-8")
    xem_nhu = _hang_chuoi(ts, "TUYEN_XEM_NHU")
    thoat = _hang_chuoi(ts, "TUYEN_THOAT_XEM_NHU")
    vai = _hang_chuoi(ts, "TUYEN_VAI")
    truong_vai = _hang_chuoi(ts, "TRUONG_VAI")
    truong_danh_muc = _hang_chuoi(ts, "TRUONG_DANH_MUC_VAI")
    khoa_act = _hang_chuoi(ts, "KHOA_ACT")

    py = (GOC / "api" / "main.py").read_text(encoding="utf-8")
    assert f'@cua_dong.post("{xem_nhu}")' in py, xem_nhu
    assert f'@cua_dong.post("{thoat}")' in py, thoat
    assert f'@cua_dong.get("{vai}")' in py, vai

    # Ba tên trường, ghim vào **hợp đồng** chứ không vào định dạng. Bản đầu ghim
    # `f'"{khoa_act}": ('` - tức đúng cách xuống dòng của một biểu thức - nên
    # một lần format lại thành một dòng làm test đỏ trong khi hợp đồng không đổi
    # gì. Ở đây `api/` được import và hỏi bằng chính đối tượng của nó.
    from api.main import ThanXemNhu, toi

    assert set(ThanXemNhu.model_fields) == {truong_vai}, truong_vai

    # `GET /auth/vai` và `GET /auth/toi` không khai model, nên hỏi hợp đồng của
    # chúng bằng cách **gọi handler** thay vì so một chuỗi trong nguồn: một lần
    # format lại không được làm test đỏ khi hợp đồng không đổi gì.
    class _ClaimGia:
        sub, role, space, demo, admin, act = "x", "y", "synth", True, True, None

    than_toi = asyncio.run(toi(_ClaimGia()))
    assert khoa_act in than_toi and than_toi[khoa_act] is None, than_toi

    from api.main import danh_muc_vai

    class _Kho:
        @staticmethod
        def hien_tai():
            return type("P", (), {"roles": {"b": None, "a": None}})()

    class _Req:
        app = type("A", (), {"state": type("S", (), {"kho_chinh_sach": _Kho()})()})()

    than_vai = asyncio.run(danh_muc_vai(_Req(), _ClaimGia()))
    assert than_vai == {truong_danh_muc: ["a", "b"]}, than_vai

    # Và `xem_nhu.ts` dựng thân bằng chính hằng đó, không literal chép tay.
    goi_ts = XEM_NHU_TS.read_text(encoding="utf-8")
    assert "[TRUONG_VAI]:" in goi_ts, goi_ts
    assert f'"{xem_nhu}"' not in goi_ts and f'"{thoat}"' not in goi_ts


def test_khoa_act_cua_auth_toi_la_bat_buoc_trong_la_phien():
    """`la_phien` đòi `act` **có mặt**; vắng mặt không được đọc thành `null`.

    `null` là một trạng thái thật ("không mượn vai nào"), vắng mặt là hợp đồng
    đã trôi. Đọc cái sau thành cái trước là chip hổ phách biến mất khỏi topbar
    và mục "Thoát xem như" biến mất khỏi menu **trong khi phiên vẫn đang mang
    một vai giả** - trạng thái nguy hiểm nhất mà màn này có thể ở. Cùng luật với
    `api.xac_thuc._doc_act`, chỗ một `act` có mặt mà không đọc được là từ chối
    cả token.
    """
    ts = PHIEN_TS.read_text(encoding="utf-8")
    m = re.search(r"export function la_phien\(.*?\n\}", ts, re.S)
    assert m, "phien.ts phải export `la_phien`"
    assert "KHOA_ACT in t" in m.group(0), m.group(0)
    assert "la_act(" in m.group(0), m.group(0)


def test_web_khong_giu_vai_dang_muon_o_kho_thu_hai():
    """Vai đang mượn sống **chỉ** trong token; không kho bền thứ hai (Ask First).

    Luật một cửa của 4.2 áp nguyên: một bản chép của "đang là vai gì" bên trình
    duyệt là một giá trị lệch được với token, và khi nó lệch thì màn hình nói
    một vai còn máy chủ trả lời theo vai khác. Phép canh
    `test_khong_file_nao_ngoai_phien_ts_cham_kho_phien` đã cấm mọi file ngoài
    `phien.ts` chạm `sessionStorage`; ở đây thêm vế "và `phien.ts` cũng không
    mọc một khóa thứ hai".
    """
    ts = PHIEN_TS.read_text(encoding="utf-8")
    khoa = re.findall(r'(?:setItem|getItem|removeItem)\(([^,)]+)', ts)
    assert khoa, "phien.ts phải còn là nơi duy nhất chạm kho"
    assert set(k.strip() for k in khoa) == {"KHOA_TOKEN"}, khoa
    # Và `xem_nhu.ts` đi qua đúng cửa ấy chứ không tự ghi.
    goi_ts = XEM_NHU_TS.read_text(encoding="utf-8")
    assert "ghi_token(" in goi_ts
    assert "sessionStorage" not in goi_ts and "localStorage" not in goi_ts


def test_menu_xem_nhu_la_menu_chu_khong_phai_modal():
    """`role="menu"` và **không** `aria-modal`: ⌘K phải còn chạy khi menu mở.

    Ca e2e của 4.1 ghim phím tắt bị chặn khi có
    `[role="dialog"][aria-modal="true"]`, và **chỉ** khi ấy. Một dropdown chọn
    vai gắn `aria-modal` là ⌘K chết trong đúng nhịp demo mà nó sinh ra để phục
    vụ. Esc đóng và trả focus về nút mở là hai vế còn lại của hợp đồng dropdown
    (DESIGN.md Interaction).
    """
    tho = MENU_XEM_NHU_TSX.read_text(encoding="utf-8")
    sach = _bo_chu_thich(tho)
    assert 'role="menu"' in sach
    assert "aria-modal" not in sach, "dropdown không được là modal"
    assert 'aria-haspopup="menu"' in sach and "aria-expanded" in sach
    assert '"Escape"' in sach and "nut.current?.focus()" in sach


def test_menu_xem_nhu_khong_chep_danh_sach_vai():
    """Danh mục vai đến từ `GET /auth/vai`, không một mảng chép ở `web/`.

    Đây là lời hứa của AD-4 phát biểu thành một phép quét: thêm một vai vào YAML
    phải là dropdown dài thêm một dòng mà không sửa một dòng TypeScript nào. Một
    mảng tên vai trong `MenuXemNhu.tsx` là chỗ lời hứa ấy chết mà không ai thấy,
    vì bảng chính sách vẫn nạp được và API vẫn trả đủ.
    """
    sach = _bo_chu_thich(MENU_XEM_NHU_TSX.read_text(encoding="utf-8"))
    for vai in ("devops", "tech_support", "sale_ba", "truong_nhom", "admin"):
        assert f'"{vai}"' not in sach, f"tên vai {vai!r} chép cứng trong menu"
    assert "danh_muc_vai(" in sach


def test_dieu_khien_xem_nhu_chi_ve_cho_phien_demo_hoac_admin():
    """Nút chỉ vẽ khi `demo || admin`, đọc từ **claim** chứ không từ vai đang mang.

    Hai vế của FR-18, và chỉ vế này kiểm được ở `web/`: vế kia là ba tuyến API
    cùng từ chối (`tests/test_xac_thuc.py`). Ẩn một nút không phải một phép kiểm
    quyền, nhưng vẽ nó cho một tài khoản thường là mời người dùng bấm vào một
    403 - và khoản ledger 403 của 4.2 đóng bằng đúng quyết định "không vẽ".

    Phép **hoặc**, không phải **và**: `demo01` (demo mà không admin) phải thấy
    nút, và một `&&` ở đây là một tài khoản demo mất đúng tính năng của nó.
    """
    sach = _bo_chu_thich(TOPBAR_TSX.read_text(encoding="utf-8"))
    assert "phien.demo || phien.admin" in sach, sach
    assert "MenuXemNhu" in sach


def test_moc_doi_vai_la_muc_that_khong_suy_tu_vai_gui():
    """Divider là một **mục** trong danh sách, đếm theo số lần đổi vai.

    EXPERIENCE.md nói "mỗi lần đổi vai chèn một divider", nên ba ca phải ra ba
    divider mà một phép suy từ chênh lệch tên vai nuốt hết: đổi hai lần liên
    tiếp không hỏi câu nào, đổi đi rồi đổi về, và bấm lại đúng dòng đang có dấu
    ✓. Dãy `useCacLanDoiVai()` của khung là thứ duy nhất thấy cả ba.

    **Dãy tên vai, không một bộ đếm.** Một bộ đếm cộng với tên vai đọc từ
    `phien.vai` lúc chèn hỏng ở hai ca đo được: mốc mang tên vai **vừa rời đi**
    khi lần đọc phiên chưa xong, và hai lần đổi chồng nhau (lần đọc thứ nhất bị
    effect hủy) cho **một** mốc trên **hai** lần đổi thật. Tên vai đến thẳng từ
    lời gọi vừa thành công thì cả hai biến mất.

    `vai_gui` (4.3) **không** bị story này viết lại: nó vẫn là vai của phiên lúc
    gửi, dùng cho hai nấc chưa có envelope.
    """
    khung = KHUNG_APP_TSX.read_text(encoding="utf-8")
    # Dãy chứ không số: một `useState<number>` cho bộ đếm là đúng hình dạng đã
    # hỏng ở hai ca trên.
    assert "useState<readonly string[]>([])" in khung, khung
    assert "da_doi_vai(vai_moi: string)" in khung, khung
    tho = MAN_CHAT.read_text(encoding="utf-8")
    assert "useCacLanDoiVai()" in tho, tho
    assert re.search(r"type MocDoiVai = \{", tho), tho
    assert re.search(r"type Muc =", tho), tho
    assert 'cac_manh("divider_doi_vai"' in tho or 'dien("divider_doi_vai"' in tho
    # Và mốc đứng ở cấp danh sách, tức ngoài `.luot__o_tra_loi` (vùng live).
    m = re.search(r'className="luot__o_tra_loi" aria-live="polite">(.*?)</div>', tho, re.S)
    assert m, "ManChat phải còn ô trả lời mang vùng live"
    assert "MocDoiVai" not in m.group(1), m.group(1)
    # `vai_gui` còn nguyên vai trò của 4.3.
    assert "vai_gui: phien?.vai ?? \"\"" in tho, tho


def test_o_hoi_chan_truoc_cau_qua_dai_bang_hang_phia_api():
    """`maxLength` của ô hỏi **bằng** `api.hoi_dap.DAI_CAU_HOI_TOI_DA`.

    Đóng khoản ledger `CAU_HOI_QUA_DAI`/`THAN_QUA_LON` bằng một **cơ chế** chứ
    không một chuỗi lỗi: câu quá trần không rời trình duyệt, nên 400
    `CAU_HOI_QUA_DAI` không xảy ra và trần thân 64 KB của middleware không với
    tới được. Rẻ hơn một câu chữ cho một trạng thái chặn được từ đầu.

    Ghim **hai chiều** vì cả hai chiều hỏng im lặng: nới trần ở `api/` mà quên ở
    đây là một câu hợp lệ bị trình duyệt cắt cụt không báo gì; siết ở `api/` mà
    quên ở đây là lỗi cũ quay lại nguyên vẹn.
    """
    ts = HOI_DAP_TS.read_text(encoding="utf-8")
    m = re.search(r"export const DAI_CAU_HOI_TOI_DA = (\d+);", ts)
    assert m, "hoi_dap.ts phải khai hằng DAI_CAU_HOI_TOI_DA"
    assert int(m.group(1)) == DAI_CAU_HOI_TOI_DA
    # Và ô hỏi dùng chính hằng đó, không một con số gõ tay.
    tho = MAN_CHAT.read_text(encoding="utf-8")
    assert "maxLength={DAI_CAU_HOI_TOI_DA}" in tho, tho
    assert str(DAI_CAU_HOI_TOI_DA) not in _bo_chu_thich(tho), tho


def test_xem_nhu_khong_dat_tran_thoi_gian_va_khong_goi_fetch_thang():
    """Mã mới của 4.5 nằm trong đúng hai phép quét đã có của `web/`.

    Ca này không thêm luật nào: nó khẳng định `xem_nhu.ts` và `MenuXemNhu.tsx`
    thật sự nằm trong tập mà `test_khong_file_nao_trong_web_src_dat_tran_thoi_gian`
    và phép canh một-cửa-fetch quét, để một lần thu hẹp `_file_giao_dien()` không
    lặng lẽ bỏ chúng ra.
    """
    duong = [f.relative_to(GOC).as_posix() for f in _file_giao_dien()]
    for f in ("web/src/api/xem_nhu.ts", "web/src/khung/MenuXemNhu.tsx"):
        assert f in duong, duong
    for f in (XEM_NHU_TS, MENU_XEM_NHU_TSX):
        sach = _bo_chu_thich(f.read_text(encoding="utf-8"))
        assert not MAU_TRAN_THOI_GIAN.search(sach), f
        assert "fetch(" not in sach, f
