"""Trang HTML tĩnh để soát bộ 52 câu, bộ vàng 30 câu và nhãn truy hồi vàng (story 2.9).

Chạy: `uv run python -m eval.xem_cau_hoi [đường-dẫn-đích]`, mặc định ghi
`eval/expr/bo_cau_hoi.html`.

Ba file JSON là mẫu số của Đo 2 và Đo 3: một nhãn sai là một con số sai trong
chương 4. Đọc JSON thô để soát 22 câu × nhiều hyperedge là cách chắc chắn bỏ
sót, nên trang này làm bốn việc mà file JSON không làm được:

1. **Dựng lại câu fact của từng hyperedge được nhãn nhắc tới**
   (`core.facts.cau_fact` trên slot của ảnh chụp), để người soát đọc "fact này
   có trả lời được câu hỏi kia không" thay vì đọc một id băm.
2. **Tô đậm slot mang đáp án** trong bảng 8 vai của từng hyperedge - đó là thứ
   quyết định lớp "recall trả lời được" của PRD 5.3.
3. **In trần lý thuyết của hai vai đo cạnh nhau**, kèm lý do của mọi câu trần 0.
   Chênh giữa hai vai phải đọc ra được từ `scopes` và `disclosure`, không từ
   nhãn tay; đó là điều trang này để người soát kiểm bằng mắt.
4. **Đặt bảng phân bố 7 nhóm × 2 vai ở đầu trang**, để phân bố PRD mục 5 là thứ
   nhìn thấy chứ không phải thứ tin.

Chỉ stdlib cộng loader của dự án: không framework, không server, không tài
nguyên ngoài. `eval/expr/` đã gitignore nên trang không vào lịch sử git - bằng
chứng cho hội đồng là ba file JSON cộng bộ test.
"""

import argparse
import html
import sys
from pathlib import Path

from adapters.policy_loader import load_policy
from core.facts import TEN_VAI_TIENG_VIET
from core.policy import PolicyInvalid
from core.slots import SLOT_ROLES
from eval.cau_hoi import (
    HAN_CHE,
    NHOM,
    PHAN_BO,
    VAI_HOI_CUA_CAU,
    AnhDoThi,
    AnhDoThiKhongHopLe,
    BoCauHoi,
    BoCauHoiKhongHopLe,
    NhanKhongHopLe,
    NhanTroiId,
    NhanTruyHoi,
    doc_anh_do_thi,
    doc_bo_cau_hoi,
    doc_nhan_truy_hoi,
    tran_theo_vai,
    tran_theo_vai_hoi,
)

DUONG_DAN_HTML: Path = Path(__file__).resolve().parent / "expr" / "bo_cau_hoi.html"

_CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, "Segoe UI", sans-serif; margin: 0; padding: 24px;
       background: #f6f7f9; color: #16191d; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 14px 0 8px; }
.tong { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
        padding: 16px; margin-bottom: 24px; }
.muc-luc a { display: inline-block; margin: 2px 10px 2px 0; }
.cau { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
       padding: 16px; margin-bottom: 16px; }
.nhan { display: inline-block; font-size: 12px; padding: 2px 8px; border-radius: 10px;
        background: #e8eaee; margin-left: 6px; }
.nhan.vang { background: #ffe6cc; }
.nhan.n7 { background: #f3d6d6; }
.hoi { font-size: 16px; font-weight: 600; margin: 6px 0; }
.dap-an { background: #fbfbfc; border-left: 3px solid #9ab; padding: 8px 12px;
          margin: 8px 0; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #dfe3e8; padding: 5px 7px; vertical-align: top;
         text-align: left; }
th { background: #eef1f4; font-weight: 600; }
td.trong { background: #fafbfc; }
td.dap { background: #fff3bf; font-weight: 600; }
td.cau-fact { color: #4a5058; font-style: italic; }
code { font-size: 12px; color: #5a6069; }
.canh-bao { background: #fff8e6; border: 1px solid #f0d48a; border-radius: 6px;
            padding: 10px 12px; margin: 8px 0; font-size: 13px; }
.khong-khoa { color: #a33; }
.nhan.han-che { background: #f3d6d6; }
tr.vai-hoi td { background: #eef7ee; font-weight: 600; }
"""


def _bang_phan_bo(bo: BoCauHoi) -> str:
    vai = sorted(bo.theo_vai())
    dau = "".join(f"<th>{html.escape(v)}</th>" for v in vai)
    hang = []
    for nhom in NHOM:
        cua_nhom = bo.theo_nhom()[nhom]
        vang = sum(1 for c in cua_nhom if c.bo_vang)
        o = "".join(
            f"<td>{sum(1 for c in cua_nhom if c.vai_hoi == v)}</td>" for v in vai
        )
        hang.append(
            f"<tr><td><b>{nhom}</b></td><td>{len(cua_nhom)}</td>"
            f"<td>{PHAN_BO[nhom]}</td>{o}<td>{vang}</td></tr>"
        )
    tong_vang = len(bo.bo_vang())
    o_tong = "".join(f"<td>{len(bo.theo_vai()[v])}</td>" for v in vai)
    hang.append(
        f"<tr><td><b>TỔNG</b></td><td><b>{len(bo.cau)}</b></td>"
        f"<td><b>{sum(PHAN_BO.values())}</b></td>{o_tong}<td><b>{tong_vang}</b></td></tr>"
    )
    return (
        f"<table><tr><th>Nhóm</th><th>Câu</th><th>PRD mục 5</th>{dau}"
        f"<th>Bộ vàng</th></tr>{''.join(hang)}</table>"
    )


def _hang_tran(ten: str, t) -> str:
    return (
        f"<tr><td><code>{html.escape(ten)}</code></td><td>{t.tong}</td>"
        f"<td>{t.ton_tai} ({t.ti_le_ton_tai():.1%})</td>"
        f"<td>{t.tra_loi_duoc} ({t.ti_le_tra_loi_duoc():.1%})</td>"
        f"<td>{len(t.cau_tran_khong())}</td><td>{len(t.canh_bao())}</td></tr>"
    )


def _bang_tran(tran, tran_hoi) -> str:
    """Hai bảng trần trong một: mỗi vai trên mọi câu, rồi theo đúng vai hỏi.

    Bảng trên để *so hai vai*; bảng dưới là mẫu số mà Đo 3 sẽ chạy, vì mỗi câu
    chỉ được hỏi bởi một vai. Chỉ in một bảng thì con số kia bị đọc nhầm.
    """
    hang = "".join(_hang_tran(v, t) for v, t in sorted(tran.items()))
    hang += f'<tr class="vai-hoi">{_hang_tran(VAI_HOI_CUA_CAU, tran_hoi)[4:]}'
    return (
        "<table><tr><th>Vai đo</th><th>Cặp câu-hyperedge</th>"
        "<th>Trần lớp <i>tồn tại</i></th><th>Trần lớp <i>trả lời được</i></th>"
        f"<th>Câu trần 0</th><th>Cảnh báo</th></tr>{hang}</table>"
    )


def _bang_slot(he, slot_dap_an: tuple[str, ...]) -> str:
    dau = "".join(
        f"<th>{vai}<br><small>{html.escape(TEN_VAI_TIENG_VIET[vai])}</small></th>"
        for vai in SLOT_ROLES
    )
    o = []
    for vai in SLOT_ROLES:
        gia_tri = he.slots.get(vai)
        if not gia_tri:
            o.append('<td class="trong"></td>')
            continue
        lop = ' class="dap"' if vai in slot_dap_an else ""
        o.append(f"<td{lop}>{html.escape(', '.join(gia_tri))}</td>")
    return f"<table><tr>{dau}</tr><tr>{''.join(o)}</tr></table>"


def _khoi_hyperedge(ky_vong, anh: AnhDoThi) -> str:
    he = anh.theo_id.get(ky_vong.id)
    if he is None:
        return (
            f'<p class="khong-khoa">{html.escape(ky_vong.id)}: không có trong ảnh chụp</p>'
        )
    khoa = (
        f'<span class="nhan">{html.escape(he.khoa)}</span>'
        if he.khoa
        else '<span class="nhan khong-khoa">không khóa (AD-5)</span>'
    )
    return (
        f'<p><code>{html.escape(he.id)}</code>{khoa}'
        f'<span class="nhan">{html.escape(", ".join(he.doc_key))}</span>'
        f'<span class="nhan">slot đáp án: {html.escape(", ".join(ky_vong.slot_dap_an))}</span></p>'
        f'<p class="cau-fact">{html.escape(he.cau())}</p>'
        f"{_bang_slot(he, ky_vong.slot_dap_an)}"
    )


def _khoi_cau(cau, nhan: NhanTruyHoi, anh: AnhDoThi, tran, tran_hoi) -> str:
    nhan_html = ""
    if cau.bo_vang:
        nhan_html += '<span class="nhan vang">bộ vàng</span>'
    if cau.nhom == "N7":
        nhan_html += '<span class="nhan n7">không có đáp án</span>'
        nhan_html += (
            f'<span class="nhan">vùng đáp án: {html.escape(", ".join(cau.neo_loai))}</span>'
        )
    for h in cau.han_che:
        nhan_html += f'<span class="nhan han-che">{html.escape(h)}</span>'
    than = [
        f'<div class="cau" id="cau-{html.escape(cau.id)}">'
        f'<h2><code>{html.escape(cau.id)}</code>{nhan_html}'
        f'<span class="nhan">{html.escape(cau.nhom)}</span>'
        f'<span class="nhan">vai hỏi: {html.escape(cau.vai_hoi)}</span>'
        f'<span class="nhan">{html.escape(cau.kich_ban)}</span></h2>'
        f'<p class="hoi">{html.escape(cau.cau_hoi)}</p>'
    ]
    if cau.bo_vang:
        y = "".join(f"<li>{html.escape(y)}</li>" for y in cau.y_chinh)
        than.append(
            f'<div class="dap-an">{html.escape(cau.dap_an)}</div>'
            f"<p>Ý chính chấm rubric &quot;đủ ý&quot;:</p><ul>{y}</ul>"
        )
    muc = nhan.theo_cau.get(cau.id)
    if muc is not None:
        than.append(f"<p><b>{len(muc.hyperedge)} hyperedge kỳ vọng</b></p>")
        than += [_khoi_hyperedge(k, anh) for k in muc.hyperedge]
        bang = list(sorted(tran.items())) + [(f"{VAI_HOI_CUA_CAU} = {cau.vai_hoi}", tran_hoi)]
        for vai, t in bang:
            tc = next((x for x in t.cau if x.cau_id == cau.id), None)
            if tc is None:
                continue
            ly_do = (
                "<br>".join(html.escape(l) for l in tc.ly_do) or "không có gì bị chặn"
            )
            than.append(
                f'<div class="canh-bao"><b>{html.escape(vai)}</b>: trần tồn tại'
                f" {tc.ton_tai}/{tc.tong}, trần trả lời được {tc.tra_loi_duoc}/{tc.tong}"
                f"<br>{ly_do}</div>"
            )
    than.append("</div>")
    return "".join(than)


def dung_html(bo: BoCauHoi, nhan: NhanTruyHoi, anh: AnhDoThi, tran, tran_hoi) -> str:
    """Dựng toàn bộ trang từ ba file đã kiểm cộng bảng trần đã tính."""
    muc_luc = "".join(
        f'<a href="#cau-{html.escape(c.id)}">{html.escape(c.id)}</a>' for c in bo.cau
    )
    canh_bao = "".join(
        f'<div class="canh-bao"><b>{html.escape(vai)}</b> - {len(t.cau_tran_khong())} câu'
        f" trần 0, {len(t.canh_bao())} câu mất điểm"
        + ("<br>" + "<br>".join(html.escape(c) for c in t.canh_bao()) if t.canh_bao() else "")
        + "</div>"
        for vai, t in list(sorted(tran.items())) + [(VAI_HOI_CUA_CAU, tran_hoi)]
    )
    tong = f"""<div class="tong">
<h1>Bộ 52 câu, bộ vàng 30 câu và nhãn truy hồi vàng</h1>
<p>Ảnh chụp đồ thị: space <b>{html.escape(anh.space)}</b>,
{anh.so_hyperedge} hyperedge, {len(anh.da_nguon())} đa nguồn, chụp
{html.escape(anh.ngay_do)}. Nhãn phủ {len(nhan.nhan)} câu N3+N5 với
{nhan.so_cap()} cặp câu-hyperedge.</p>
<h2>Phân bố 7 nhóm × vai người hỏi</h2>
{_bang_phan_bo(bo)}
<h2>Trần lý thuyết theo vai đo</h2>
<p>Trần là <b>phép tính</b> từ nhãn cộng ảnh chụp cộng bảng chính sách, không
phải nhãn tay. Nhãn cố ý <b>không</b> lọc theo mức tiết lộ: mức tiết lộ là biến
duy nhất của Đo 3.</p>
{_bang_tran(tran, tran_hoi)}
{canh_bao}
<h2>Mục lục</h2>
<p class="muc-luc">{muc_luc}</p>
</div>"""
    khoi = "".join(_khoi_cau(c, nhan, anh, tran, tran_hoi) for c in bo.cau)
    return (
        '<!doctype html>\n<html lang="vi"><head><meta charset="utf-8">'
        "<title>Bộ câu hỏi và nhãn truy hồi vàng</title>"
        f"<style>{_CSS}</style></head><body>{tong}{khoi}</body></html>\n"
    )


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Trang soát bộ câu hỏi, bộ vàng 30 câu và nhãn truy hồi vàng"
    )
    p.add_argument(
        "dich",
        nargs="?",
        type=Path,
        default=None,
        help=f"file HTML đích (mặc định {DUONG_DAN_HTML})",
    )
    p.add_argument(
        "--bo-cau-hoi",
        type=Path,
        default=None,
        dest="bo_cau_hoi",
        metavar="FILE",
        help="bộ 52 câu (mặc định eval/bo_cau_hoi.json)",
    )
    p.add_argument(
        "--nhan",
        type=Path,
        default=None,
        metavar="FILE",
        help="nhãn truy hồi vàng (mặc định eval/nhan_truy_hoi_vang.json)",
    )
    p.add_argument(
        "--anh",
        type=Path,
        default=None,
        metavar="FILE",
        help="ảnh chụp đồ thị (mặc định eval/anh_do_thi/synth.json)",
    )
    p.add_argument(
        "--policy",
        type=Path,
        default=None,
        metavar="FILE",
        help="bảng chính sách dùng để tính trần (mặc định config/policy-toi-gian.yaml)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dựng trang; ba file hỏng, bảng chính sách hỏng hay không ghi được thì in lý do và trả 1.

    `PolicyInvalid` nằm trong danh sách bắt: `load_policy` ném nó, và
    `tran_theo_vai` cũng ném nó khi một vai của seed danh tính vắng trong bảng
    chính sách - đúng ca mà người soát dễ gặp nhất khi hoán bảng để thử một
    cấu hình đo. Một traceback ở đó là một thông điệp không ai đọc được.
    """
    ts = _tham_so(sys.argv[1:] if argv is None else list(argv))
    try:
        anh = doc_anh_do_thi(ts.anh)
        bo = doc_bo_cau_hoi(ts.bo_cau_hoi)
        policy = load_policy(ts.policy) if ts.policy else None
        nhan = doc_nhan_truy_hoi(ts.nhan, bo=bo, anh=anh, policy=policy)
        tran = tran_theo_vai(nhan, anh, policy=policy)
        tran_hoi = tran_theo_vai_hoi(bo, nhan, anh, policy=policy)
    except (
        AnhDoThiKhongHopLe,
        BoCauHoiKhongHopLe,
        NhanKhongHopLe,
        NhanTroiId,
        PolicyInvalid,
    ) as loi:
        print(str(loi), file=sys.stderr)
        return 1

    dich = Path(ts.dich) if ts.dich is not None else DUONG_DAN_HTML
    try:
        dich.parent.mkdir(parents=True, exist_ok=True)
        dich.write_text(dung_html(bo, nhan, anh, tran, tran_hoi), encoding="utf-8")
    except OSError as loi:
        print(f"không ghi được {dich}: {loi}", file=sys.stderr)
        return 1

    dem = {nhom: len(ds) for nhom, ds in bo.theo_nhom().items()}
    print(
        f"{len(bo.cau)} câu ({' · '.join(f'{k} {v}' for k, v in dem.items())}),"
        f" {len(bo.bo_vang())} câu bộ vàng"
    )
    print(
        f"nhãn: {len(nhan.nhan)} câu N3+N5, {nhan.so_cap()} cặp câu-hyperedge;"
        f" ảnh chụp {anh.so_hyperedge} hyperedge / {anh.so_tai_lieu} tài liệu"
        f" của space {anh.space}"
    )
    for ten, t in list(sorted(tran.items())) + [(VAI_HOI_CUA_CAU, tran_hoi)]:
        print(
            f"trần {ten}: tồn tại {t.ton_tai}/{t.tong} ({t.ti_le_ton_tai():.1%}),"
            f" trả lời được {t.tra_loi_duoc}/{t.tong} ({t.ti_le_tra_loi_duoc():.1%}),"
            f" {len(t.cau_tran_khong())} câu trần 0, {len(t.canh_bao())} câu mất điểm"
        )
    for h in HAN_CHE:
        ds = [c.id for c in bo.cau if h in c.han_che]
        print(f"dấu {h}: {len(ds)} câu {ds}")
    print(f"ghi {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
