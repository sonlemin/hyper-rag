"""Trang HTML tĩnh để soát nhãn bộ vàng trích xuất (story 2.5).

Chạy: `uv run python -m eval.xem_bo_vang [đường-dẫn-đích]`, mặc định ghi
`eval/expr/bo_vang.html`.

Bộ vàng là mẫu số của ngưỡng 60% ở R2: sai một nhãn là sai một con số trong
chương 4. Đọc JSON thô để soát từng fact là cách chắc chắn bỏ sót, nên trang
này làm hai việc mà file JSON không làm được:

1. **Tô sáng mọi giá trị slot ngay trong thân tài liệu.** Luật nạp bắt mọi giá
   trị phải là một đoạn có thật trong thân, nên tô được - và chỉ khi tô được
   thì người soát mới đối chiếu được *từng vai* thay vì đọc một câu nguồn rồi
   tin phần còn lại. Một fact sáu vai chỉ dẫn một câu nguồn thì năm vai kia
   không kiểm được bằng mắt.
2. **Đặt bảng fact theo 8 vai ngay dưới thân tài liệu** kèm câu nguồn, id fact
   và dấu few-shot, để không phải nhảy giữa hai file.

Chỉ stdlib: không framework, không server, không tài nguyên ngoài. Trang là một
file mở bằng trình duyệt, và `eval/expr/` đã gitignore nên nó không vào lịch sử
git - bằng chứng cho hội đồng là chính file JSON cộng bộ test.
"""

import html
import re
import sys
import unicodedata
from pathlib import Path

from core.facts import TEN_VAI_TIENG_VIET
from core.slots import SLOT_ROLES
from eval.bo_vang import BoVang, BoVangKhongHopLe, TaiLieuVang, doc_bo_vang

DUONG_DAN_HTML: Path = Path(__file__).resolve().parent / "expr" / "bo_vang.html"

_CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, "Segoe UI", sans-serif; margin: 0; padding: 24px;
       background: #f6f7f9; color: #16191d; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 0 0 8px; }
.tong { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
        padding: 16px; margin-bottom: 24px; }
.tong table { border-collapse: collapse; }
.tong td { padding: 2px 16px 2px 0; }
.muc-luc a { display: inline-block; margin: 2px 10px 2px 0; }
.tai-lieu { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
            padding: 16px; margin-bottom: 20px; }
.nhan { display: inline-block; font-size: 12px; padding: 2px 8px; border-radius: 10px;
        background: #e8eaee; margin-left: 6px; }
.nhan.few { background: #ffe6cc; }
.nhan.cham { background: #d9f0dd; }
pre.than { background: #fbfbfc; border: 1px solid #e4e7eb; border-radius: 6px;
           padding: 12px; white-space: pre-wrap; margin: 12px 0; font-size: 14px; }
pre.than mark { background: #fff3bf; border-bottom: 2px solid #f0c000; padding: 0 1px; }
table.fact { border-collapse: collapse; width: 100%; font-size: 13px; }
table.fact th, table.fact td { border: 1px solid #dfe3e8; padding: 5px 7px;
                               vertical-align: top; text-align: left; }
table.fact th { background: #eef1f4; font-weight: 600; }
table.fact td.trong { background: #fafbfc; }
td.cau { color: #4a5058; font-style: italic; }
code { font-size: 12px; color: #5a6069; }
"""


def _bang_tong(bo: BoVang) -> str:
    dem = bo.dem_theo_vai()
    dem_cham = bo.dem_theo_vai(chi_cham=True)
    mau_so = bo.mau_so_slot()
    hang_vai = "".join(
        f"<tr><td><code>{vai}</code> ({html.escape(TEN_VAI_TIENG_VIET[vai])})</td>"
        f"<td>{dem[vai]}</td><td>{dem_cham[vai]}</td>"
        f"<td>{dem_cham[vai] / mau_so:.1%}</td></tr>"
        for vai in SLOT_ROLES
    )
    few = bo.tai_lieu_few_shot()
    ten_few = ", ".join(t.doc_key for t in few) or "(không có)"
    trung = bo.id_fact_trung_cheo_tai_lieu()
    trung_html = (
        "".join(
            f"<code>{i}</code>: {html.escape(', '.join(ds))}<br>" for i, ds in trung.items()
        )
        if trung
        else "Không có: mỗi fact vàng chỉ thuộc một tài liệu, nên mẫu số không "
        "đếm đôi. Có ca thì pipeline ra một node hyperedge còn mẫu số đếm hai; "
        "luật đếm chốt ở 2.6/2.8."
    )
    muc_luc = "".join(
        f'<a href="#doc-{i}">{html.escape(t.doc_key)}</a>' for i, t in enumerate(bo.tai_lieu)
    )
    return f"""<div class="tong">
<h1>Bộ vàng trích xuất - bảng soát nhãn</h1>
<table>
<tr><td>Tài liệu</td><td><b>{len(bo.tai_lieu)}</b></td></tr>
<tr><td>Tài liệu chấm (vào mẫu số)</td><td><b>{len(bo.tai_lieu_cham())}</b></td></tr>
<tr><td>Tài liệu few-shot (loại khỏi mẫu số)</td>
    <td><b>{len(few)}</b>: {html.escape(ten_few)}</td></tr>
<tr><td>Fact vàng</td><td><b>{bo.so_fact()}</b> (chấm: {bo.so_fact(chi_cham=True)})</td></tr>
<tr><td><b>Mẫu số: slot đã điền của tài liệu chấm</b></td><td><b>{mau_so}</b></td></tr>
</table>
<p>Prompt trích xuất 2.4 lấy ví dụ đầu ra từ {len(few)} tài liệu trên, nên chấm
điểm trên chúng là chấm trí nhớ của prompt; PRD 2.6 loại chúng khỏi mẫu số.
Phần tô vàng trong thân tài liệu là giá trị slot của nhãn - mọi giá trị đều
phải là một đoạn có thật trong thân, nên chỗ nào không tô được là nhãn sai.</p>
<h2>Số fact có điền từng vai</h2>
<table class="fact"><tr><th>Vai</th><th>Cả bộ</th><th>Tài liệu chấm</th>
<th>Phần của mẫu số</th></tr>{hang_vai}</table>
<h2>Fact trùng giữa hai tài liệu</h2>
<p>{trung_html}</p>
<h2>Mục lục</h2>
<p class="muc-luc">{muc_luc}</p>
</div>"""


def _vung_gia_tri(t: TaiLieuVang) -> list[tuple[int, int, set[str]]]:
    """Các đoạn của thân tài liệu ứng với một giá trị slot, đã gộp chỗ chồng nhau.

    Khoảng trắng trong nhãn khớp mọi khoảng trắng của thân (nhãn có thể vắt qua
    hai dòng), và so không phân biệt hoa thường - cùng luật với phép kiểm lúc
    nạp. Hai giá trị chồng nhau (`phòng IT` nằm trong một cách xử lý dài hơn)
    gộp thành một đoạn mang cả hai tên vai.
    """
    tho: list[tuple[int, int, str]] = []
    for f in t.facts:
        for vai, gia_tri in f.slots.items():
            mau = re.compile(
                r"\s+".join(re.escape(p) for p in unicodedata.normalize("NFC", gia_tri).split()),
                re.IGNORECASE,
            )
            tho += [(m.start(), m.end(), vai) for m in mau.finditer(t.than)]
    gop: list[tuple[int, int, set[str]]] = []
    for dau, cuoi, vai in sorted(tho):
        if gop and dau <= gop[-1][1]:
            truoc = gop[-1]
            gop[-1] = (truoc[0], max(truoc[1], cuoi), truoc[2] | {vai})
        else:
            gop.append((dau, cuoi, {vai}))
    return gop


def _than_to_sang(t: TaiLieuVang) -> str:
    phan: list[str] = []
    vi_tri = 0
    for dau, cuoi, vai in _vung_gia_tri(t):
        phan.append(html.escape(t.than[vi_tri:dau]))
        tieu_de = ", ".join(sorted(vai))
        phan.append(
            f'<mark title="{html.escape(tieu_de)}">{html.escape(t.than[dau:cuoi])}</mark>'
        )
        vi_tri = cuoi
    phan.append(html.escape(t.than[vi_tri:]))
    return "".join(phan).strip()


def _bang_fact(t: TaiLieuVang) -> str:
    dau = "".join(
        f"<th>{vai}<br><small>{html.escape(TEN_VAI_TIENG_VIET[vai])}</small></th>"
        for vai in SLOT_ROLES
    )
    hang = []
    for f in t.facts:
        da_dien = set(f.vai_da_dien())
        o = [
            f"<td>{html.escape(f.slots[vai])}</td>" if vai in da_dien else '<td class="trong"></td>'
            for vai in SLOT_ROLES
        ]
        hang.append(
            f"<tr>{''.join(o)}<td class=\"cau\">{html.escape(f.cau_nguon)}</td>"
            f"<td><code>{f.id_fact}</code></td><td>{f.so_slot}</td></tr>"
        )
    return (
        f'<table class="fact"><tr>{dau}<th>Câu nguồn</th><th>id fact</th><th>slot</th></tr>'
        + "".join(hang)
        + "</table>"
    )


def dung_html(bo: BoVang) -> str:
    """Dựng toàn bộ trang từ một `BoVang` đã kiểm."""
    khoi = []
    for i, t in enumerate(bo.tai_lieu):
        nhan = (
            '<span class="nhan few">few-shot - loại khỏi mẫu số</span>'
            if t.few_shot
            else '<span class="nhan cham">chấm</span>'
        )
        khoi.append(
            f'<div class="tai-lieu" id="doc-{i}"><h2>{html.escape(t.doc_key)}{nhan}'
            f'<span class="nhan">scope: {html.escape(t.scope)}</span>'
            f'<span class="nhan">{html.escape(t.content_type)}</span>'
            f'<span class="nhan">{len(t.facts)} fact / {t.so_slot} slot</span></h2>'
            f'<pre class="than">{_than_to_sang(t)}</pre>'
            f"{_bang_fact(t)}</div>"
        )
    return (
        '<!doctype html>\n<html lang="vi"><head><meta charset="utf-8">'
        "<title>Bộ vàng trích xuất</title>"
        f"<style>{_CSS}</style></head><body>"
        + _bang_tong(bo)
        + "".join(khoi)
        + "</body></html>\n"
    )


def main(dich: Path | None = None, argv: list[str] | None = None) -> int:
    """Dựng trang; bộ vàng hỏng hay không ghi được file thì in lý do và trả 1.

    `dich` là tham số cho test; dòng lệnh truyền đường dẫn đích ở `argv[0]` để
    dựng trang vào một thư mục tạm mà không đụng file của repo.
    """
    if dich is None and argv:
        dich = Path(argv[0])
    try:
        bo = doc_bo_vang()
    except BoVangKhongHopLe as loi:
        print(str(loi), file=sys.stderr)
        return 1
    dich = Path(dich) if dich is not None else DUONG_DAN_HTML
    try:
        dich.parent.mkdir(parents=True, exist_ok=True)
        dich.write_text(dung_html(bo), encoding="utf-8")
    except OSError as loi:
        print(f"không ghi được {dich}: {loi}", file=sys.stderr)
        return 1
    print(
        f"{len(bo.tai_lieu)} tài liệu, {len(bo.tai_lieu_cham())} tài liệu chấm,"
        f" {bo.so_fact()} fact; mẫu số (slot đã điền của tài liệu chấm): {bo.mau_so_slot()}"
    )
    print(f"ghi {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
