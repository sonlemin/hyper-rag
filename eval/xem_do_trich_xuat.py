"""Trang HTML báo cáo vòng lặp precision và điểm quyết R2 (story 2.6).

Chạy: `uv run python -m eval.xem_do_trich_xuat [đường-dẫn-đích]`, mặc định ghi
`eval/expr/do_trich_xuat.html` và in bảng tổng cùng verdict R2 ra console.

Trang dựng *hoàn toàn* từ `eval/ket_qua_do/*.json` (fact thô đã lưu) cộng bộ
vàng: không lời gọi LLM nào, nên đổi luật chấm rồi render lại là miễn phí. Đó
là lý do file kết quả giữ phản hồi thô chứ không giữ điểm.

Năm thứ trang này làm mà một dòng precision tổng không làm được:

1. **Hai chỉ số cạnh nhau** (ghép cặp / mức tài liệu). Chênh giữa chúng là phần
   LLM gom fact khác nhãn tay; đọc một mình chỉ số ghép cặp là nhầm "gom khác
   độ hạt" thành "bỏ sót".
2. **Ma trận lẫn lộn từng vòng, dựng từ chỉ số mức tài liệu.** Câu hỏi của A13
   không phải "đúng bao nhiêu phần trăm" mà "lỗi dồn vào đâu": lỗi dồn vào một
   cặp vai thì sửa phản ví dụ của prompt, lỗi rải đều mới đáng đổi model.
3. **Bảng theo từng vai và mẫu số phụ bỏ `subject`.** `subject` bắt buộc theo
   lược đồ và chiếm 28,5% mẫu số, nên nó kéo mọi con số tổng lên mà không nói
   gì về chất lượng dán vai.
4. **Từng tài liệu, từng cặp fact.** Mỗi ô mang màu của loại kết quả (khớp
   chặt, khớp lỏng, lẫn vai, thiếu, thừa) để soát bằng mắt.
5. **Verdict R2 đủ bốn cột**, nói rõ cột nào là cổng chính thức. Biên hiện chỉ
   vài điểm, nên in mỗi cột cổng là giấu đúng chỗ mỏng. Ngưỡng và hàm verdict
   sống ở `eval/cham_trich_xuat.py`; trang chỉ *in* chúng.

Chỉ stdlib, khuôn CSS lấy từ `eval/xem_bo_vang.py`.
"""

import argparse
import html
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.facts import TEN_VAI_TIENG_VIET
from core.slots import SLOT_ROLES
from eval.bo_vang import BoVang, BoVangKhongHopLe, doc_bo_vang
from eval.cham_trich_xuat import (
    CHI_SO_GHEP_CAP,
    CHI_SO_MUC_TAI_LIEU,
    CONG_R2_CHI_SO,
    CONG_R2_MAU_SO,
    COT_MA_TRAN,
    HANG_MA_TRAN,
    KHOP_CHAT,
    NGUONG_R2,
    VAI_BO_KHOI_MAU_SO_PHU,
    VAI_THIEU,
    VAI_THUA,
    VERDICT_DAT,
    VERDICT_DUOI,
    ChiSo,
    KetQuaCham,
    cap_vai_lan_nhieu_nhat,
    cham_moi_muc_tai_lieu,
    cham_moi_tai_lieu,
    gop,
    ma_tran_lan_lon,
    mau_so_phu,
    theo_vai,
    verdict_r2,
)
from eval.do_trich_xuat import THU_MUC_KET_QUA, KetQuaDoKhongHopLe, doc_moi_vong
from eval.ngoai_suy import (
    GHI_CHU_DON_GIA,
    SO_DO_NAP_THAT,
    BangNgoaiSuy,
    dong_bang,
    ngoai_suy,
    so_vn,
)

DUONG_DAN_HTML: Path = Path(__file__).resolve().parent / "expr" / "do_trich_xuat.html"

LENH_CHAY_VONG: str = (
    "uv run python -m eval.do_trich_xuat --vong v1-deepseek --model deepseek-v4-flash"
)

# Câu này đi kèm mọi chỗ in tổng ngoại suy: 4,00 USD là *phần sắp tiêu*, không
# phải lũy kế. Phần đã tiêu từ 2.2 đến 2.6 nằm ở `audit_log` (các lần nạp) và ở
# chính bốn file vòng đo, chưa có chỗ nào cộng lại (khoản ledger có địa chỉ 7-5).
GHI_CHU_CHUA_CONG: str = (
    "Tổng trên là phần sắp tiêu, CHƯA cộng phần đã tiêu từ story 2.2 đến 2.6"
    " (các lần nạp thật ghi ở bảng audit_log, bốn vòng đo ghi trong"
    " eval/ket_qua_do/*.json)."
)

MAU_SO_TONG: str = "mẫu số tổng"
MAU_SO_PHU: str = f"mẫu số phụ (bỏ {VAI_BO_KHOI_MAU_SO_PHU})"

_CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, "Segoe UI", sans-serif; margin: 0; padding: 24px;
       background: #f6f7f9; color: #16191d; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 18px 0 8px; }
h3 { font-size: 15px; margin: 14px 0 6px; }
.khoi { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
        padding: 16px; margin-bottom: 20px; }
.cuon { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; font-size: 13px; }
th, td { border: 1px solid #dfe3e8; padding: 4px 7px; vertical-align: top; text-align: left; }
th { background: #eef1f4; font-weight: 600; }
td.so { text-align: right; font-variant-numeric: tabular-nums; }
td.trong { background: #fafbfc; }
.chat { background: #cdeccd; }
.long { background: #e6f4c8; }
.lan { background: #ffd8a8; }
.thieu { background: #ffd0cf; }
.thua { background: #d4e4ff; }
.cheo { background: #eef7ee; font-weight: 600; }
.nhan { display: inline-block; font-size: 12px; padding: 2px 8px; border-radius: 10px;
        background: #e8eaee; margin-left: 6px; }
.dat { background: #d9f0dd; }
.duoi { background: #ffd0cf; }
.khong-cham { background: #e8eaee; color: #4a5058; }
.cong { outline: 2px solid #16191d; }
.chu-thich span { margin-right: 14px; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
code { font-size: 12px; color: #5a6069; }
p.ghi-chu { font-size: 13px; color: #4a5058; }
details { margin: 6px 0; }
summary { cursor: pointer; font-size: 14px; }
"""


def _so_hoac_gach(x: int | None) -> str:
    """`-` khi chỉ số không phân loại được cột `thiếu` (chỉ số ghép cặp)."""
    return "-" if x is None else str(x)


def _pc(x: float | None) -> str:
    """Phần trăm theo quy ước tiếng Việt (dấu phẩy), `-` khi không chấm được."""
    return "-" if x is None else so_vn(100 * x, 1) + "%"


def _o(noi_dung: str, lop: str = "") -> str:
    lop = f' class="{lop}"' if lop else ""
    return f"<td{lop}>{noi_dung}</td>"


def _cuon(bang: str) -> str:
    return f'<div class="cuon">{bang}</div>'


# ---------------------------------------------------------------------------
# Gom số của một vòng
# ---------------------------------------------------------------------------


class VongDaCham:
    """Một vòng đã chấm bằng cả hai chỉ số - chấm đúng một lần cho cả trang."""

    def __init__(self, vong, bo: BoVang):
        self.vong = vong
        pred = vong.facts_theo_tai_lieu()
        self.cap_theo_doc = cham_moi_tai_lieu(bo, pred)
        self.muc_theo_doc = cham_moi_muc_tai_lieu(bo, pred)
        self.cap: KetQuaCham = gop(self.cap_theo_doc.values())
        self.muc: KetQuaCham = gop(self.muc_theo_doc.values())

    def chi_so(self, ten_chi_so: str, mau_so: str) -> ChiSo:
        kq = self.cap if ten_chi_so == CHI_SO_GHEP_CAP else self.muc
        return kq.chi_so if mau_so == MAU_SO_TONG else mau_so_phu(kq)

COT_VERDICT: tuple[tuple[str, str], ...] = (
    (CHI_SO_GHEP_CAP, MAU_SO_TONG),
    (CHI_SO_GHEP_CAP, MAU_SO_PHU),
    (CHI_SO_MUC_TAI_LIEU, MAU_SO_TONG),
    (CHI_SO_MUC_TAI_LIEU, MAU_SO_PHU),
)


def _la_cong(chi_so: str, mau_so: str) -> bool:
    return chi_so == CONG_R2_CHI_SO and mau_so == MAU_SO_TONG


# ---------------------------------------------------------------------------
# Bảng so các vòng, verdict
# ---------------------------------------------------------------------------


def _bang_so_vong(da_cham: list[VongDaCham]) -> str:
    hang = []
    for d in da_cham:
        v = d.vong
        for ten_chi_so, kq in ((CHI_SO_GHEP_CAP, d.cap), (CHI_SO_MUC_TAI_LIEU, d.muc)):
            cs = kq.chi_so
            phu = mau_so_phu(kq)
            dau = ten_chi_so == CHI_SO_GHEP_CAP
            hang.append(
                "<tr>"
                + (
                    f'<td rowspan="2"><b>{html.escape(v.vong)}</b></td>'
                    f'<td rowspan="2">{html.escape(v.model)}</td>'
                    if dau
                    else ""
                )
                + _o(html.escape(ten_chi_so) + (' <span class="nhan cong">cổng R2</span>' if dau else ""))
                + _o(str(cs.so_pred), "so")
                + _o(_pc(cs.precision), "so")
                + _o(_pc(cs.recall), "so")
                + _o(_pc(cs.f1), "so")
                + _o(_pc(cs.precision_chat), "so")
                + _o(_pc(cs.recall_chat), "so")
                + _o(_pc(phu.precision), "so")
                + _o(_pc(phu.recall), "so")
                + _o(str(kq.so_lan_vai), "so")
                + (
                    f'<td class="so" data-vong="{html.escape(v.vong)}"'
                    f' data-chi-so="{html.escape(ten_chi_so)}" data-o="o-thieu">'
                    f"{kq.so_o_thieu}</td>"
                )
                + (
                    f'<td class="so" data-vong="{html.escape(v.vong)}"'
                    f' data-chi-so="{html.escape(ten_chi_so)}" data-o="vang-han">'
                    f"{_so_hoac_gach(kq.so_vang_han)}</td>"
                )
                + (
                    f'<td rowspan="2" class="so">{v.so_hop_le()}/{v.so_fact_tho()}</td>'
                    f'<td rowspan="2" class="so">{_pc(v.ty_le_loai())}</td>'
                    f'<td rowspan="2">{html.escape(str(v.loai_theo_ma() or "{}"))}</td>'
                    f'<td rowspan="2" class="so">{v.token_vao()}+{v.token_ra()}</td>'
                    f'<td rowspan="2" class="so">{so_vn(v.chi_phi_usd())}</td>'
                    if dau
                    else ""
                )
                + "</tr>"
            )
    return _cuon(
        '<table data-bang="so-vong">'
        "<tr><th>Vòng</th><th>Model</th><th>Chỉ số</th><th>slot pred</th>"
        "<th>P (lỏng)</th><th>R (lỏng)</th><th>F1</th>"
        "<th>P chặt</th><th>R chặt</th>"
        f"<th>P bỏ {VAI_BO_KHOI_MAU_SO_PHU}</th><th>R bỏ {VAI_BO_KHOI_MAU_SO_PHU}</th>"
        "<th>lẫn vai</th><th>ô cột <i>thiếu</i></th><th>trong đó vắng hẳn</th>"
        "<th>fact hợp lệ/thô</th><th>tỷ lệ bản ghi bị loại</th><th>loại theo mã</th>"
        "<th>token</th><th>USD</th></tr>" + "".join(hang) + "</table>"
    )


def _bang_verdict(da_cham: list[VongDaCham]) -> str:
    dau = "".join(
        f'<th{" class=\"cong\"" if _la_cong(c, m) else ""}>{html.escape(c)}<br>'
        f"<small>{html.escape(m)}</small></th>"
        for c, m in COT_VERDICT
    )
    hang = []
    for d in da_cham:
        o = []
        for c, m in COT_VERDICT:
            cs = d.chi_so(c, m)
            vd = verdict_r2(cs.precision)
            lop = {VERDICT_DAT: "dat", VERDICT_DUOI: "duoi"}.get(vd, "khong-cham")
            if _la_cong(c, m):
                lop += " cong"
            o.append(
                f'<td class="{lop} so" data-vong="{html.escape(d.vong.vong)}"'
                f' data-chi-so="{html.escape(c)}" data-mau-so="{html.escape(m)}">'
                f"{_pc(cs.precision)}<br><b>{vd}</b></td>"
            )
        hang.append(
            f"<tr><th>{html.escape(d.vong.vong)}<br><small>{html.escape(d.vong.model)}</small></th>"
            + "".join(o)
            + "</tr>"
        )
    return (
        f'<table data-bang="verdict"><tr><th>Vòng</th>{dau}</tr>' + "".join(hang) + "</table>"
        f'<p class="ghi-chu">Cổng R2 chính thức là ô viền đậm: precision của chỉ số'
        f" <b>{html.escape(CONG_R2_CHI_SO)}</b> trên <b>{html.escape(CONG_R2_MAU_SO)}</b>."
        " Đơn vị của PRD là slot đã điền và <code>subject</code> là một slot đã điền,"
        " nên mẫu số tổng là cách đọc đúng câu chữ. Ba cột còn lại in kèm vì biên"
        " giữa chúng chỉ vài điểm - giấu chúng là giấu đúng chỗ mỏng."
        f" Ngưỡng {_pc(NGUONG_R2)} của PRD mục 6.1: dưới ngưỡng thì bậc 1 là chuyển"
        " GPT-4o toàn phần cộng tăng few-shot, GPT-4o vẫn dưới thì bậc 2 là rút lược"
        " đồ về 5 vai. Trang này chỉ in số; áp bậc nào là quyết định của sonlm, ghi"
        " ADR trước khi story 2.8 và 2.9 chốt.</p>"
    )


# ---------------------------------------------------------------------------
# Ma trận, theo vai, từng tài liệu
# ---------------------------------------------------------------------------


def _bang_ma_tran(kq: KetQuaCham, ten_vong: str = "") -> str:
    ma_tran = ma_tran_lan_lon(kq)
    dau = "".join(f"<th>{html.escape(cot)}</th>" for cot in COT_MA_TRAN)
    hang = []
    for h in HANG_MA_TRAN:
        o = []
        for c in COT_MA_TRAN:
            n = ma_tran[h][c]
            lop = "cheo" if h == c else ("trong" if n == 0 else "")
            if h != c and n:
                lop = "thieu" if c == VAI_THIEU else ("thua" if h == VAI_THUA else "lan")
            o.append(_o(str(n) if n else "", lop + " so"))
        hang.append(f"<tr><th>{html.escape(h)}</th>{''.join(o)}</tr>")
    top = cap_vai_lan_nhieu_nhat(kq)
    dong_top = ", ".join(f"<code>{v} → {w}</code> {n}" for v, w, n in top) or "không có ô nào"
    return _cuon(
        f'<table data-bang="ma-tran" data-vong="{html.escape(ten_vong)}">'
        f"<tr><th>vàng \\ pred</th>{dau}</tr>" + "".join(hang) + "</table>"
    ) + (
        '<p class="ghi-chu">Dựng từ chỉ số <b>mức tài liệu</b> (Always của spec):'
        " ma trận của chỉ số ghép cặp không thấy được lẫn vai xuyên fact. Hàng là vai"
        " của nhãn vàng, cột là vai mà pipeline dán. Đường chéo là TP; ô ngoài đường"
        " chéo trong vùng vai×vai là lẫn vai (đúng chữ, sai vai); cột"
        f" <code>{VAI_THIEU}</code> là giá trị vàng không xuất hiện ở bất kỳ giá trị"
        f" pred nào - bỏ sót thật; hàng <code>{VAI_THUA}</code> là giá trị pipeline"
        " không khớp nhãn nào ở đúng vai. Tổng một hàng bằng số slot vàng của vai đó;"
        " tổng một cột có thể lớn hơn số slot pred của vai đó, vì lượt quy lỗi cố ý"
        " không tiêu thụ - một giá trị nuốt cả câu phải bị nhiều slot vàng cùng chỉ"
        f" mặt. Cặp lẫn nhiều nhất: {dong_top}.</p>"
    )


def _bang_theo_vai(kq: KetQuaCham) -> str:
    hang = []
    for vai, cs in theo_vai(kq).items():
        hang.append(
            "<tr>"
            + _o(f"<code>{vai}</code> ({html.escape(TEN_VAI_TIENG_VIET[vai])})")
            + _o(str(cs.so_vang), "so")
            + _o(str(cs.so_pred), "so")
            + _o(str(cs.tp), "so")
            + _o(str(cs.chat), "so")
            + _o(str(cs.fn), "so")
            + _o(str(cs.fp), "so")
            + _o(_pc(cs.precision), "so")
            + _o(_pc(cs.recall), "so")
            + _o(_pc(cs.f1), "so")
            + "</tr>"
        )
    phu = mau_so_phu(kq)
    hang.append(
        "<tr>"
        + _o(f"<b>{html.escape(MAU_SO_PHU)}</b>")
        + _o(str(phu.so_vang), "so")
        + _o(str(phu.so_pred), "so")
        + _o(str(phu.tp), "so")
        + _o(str(phu.chat), "so")
        + _o(str(phu.fn), "so")
        + _o(str(phu.fp), "so")
        + _o(_pc(phu.precision), "so")
        + _o(_pc(phu.recall), "so")
        + _o(_pc(phu.f1), "so")
        + "</tr>"
    )
    return _cuon(
        "<table><tr><th>Vai</th><th>slot vàng</th><th>slot pred</th><th>TP</th>"
        "<th>trong đó khớp chặt</th><th>FN</th><th>FP</th>"
        "<th>P</th><th>R</th><th>F1</th></tr>" + "".join(hang) + "</table>"
    )


def _bang_cap(cham) -> str:
    """Bảng từng cặp fact của một tài liệu, tô theo loại kết quả từng ô."""
    dau = "".join(
        f"<th>{vai}<br><small>{html.escape(TEN_VAI_TIENG_VIET[vai])}</small></th>"
        for vai in SLOT_ROLES
    )
    hang = []
    for c in cham.cap:
        lan_theo_vang = dict(c.lan_vai)
        lan_theo_pred = {w: v for v, w in c.lan_vai}
        o_vang, o_pred = [], []
        for vai in SLOT_ROLES:
            if vai in c.khop:
                lop = "chat" if c.khop[vai] == KHOP_CHAT else "long"
                o_vang.append(_o(html.escape(c.vang[vai]), lop))
                o_pred.append(_o(html.escape(c.pred[vai]), lop))
                continue
            if vai in c.vang:
                lop = "lan" if vai in lan_theo_vang else "thieu"
                ghi = f" <code>-&gt; {lan_theo_vang[vai]}</code>" if vai in lan_theo_vang else ""
                o_vang.append(_o(html.escape(c.vang[vai]) + ghi, lop))
            else:
                o_vang.append(_o("", "trong"))
            if vai in c.pred:
                lop = "lan" if vai in lan_theo_pred else "thua"
                o_pred.append(_o(html.escape(c.pred[vai]), lop))
            else:
                o_pred.append(_o("", "trong"))
        hang.append(f"<tr><th>vàng</th>{''.join(o_vang)}</tr>")
        hang.append(f"<tr><th>pred</th>{''.join(o_pred)}</tr>")
    for s in cham.vang_khong_ghep:
        o = [
            _o(html.escape(s[vai]), "thieu") if vai in s else _o("", "trong")
            for vai in SLOT_ROLES
        ]
        hang.append(f"<tr><th>vàng (không ghép)</th>{''.join(o)}</tr>")
    for s in cham.pred_khong_ghep:
        o = [
            _o(html.escape(s[vai]), "thua") if vai in s else _o("", "trong")
            for vai in SLOT_ROLES
        ]
        hang.append(f"<tr><th>pred (không ghép)</th>{''.join(o)}</tr>")
    return _cuon(f"<table><tr><th></th>{dau}</tr>" + "".join(hang) + "</table>")


def _bang_muc_tai_lieu(cham) -> str:
    """Từng slot vàng của một tài liệu ở chỉ số mức tài liệu: đúng vai, lẫn vai, vắng hẳn."""
    hang = []
    for k in cham.khop:
        hang.append(
            "<tr>"
            + _o(f"<code>{k.vai_vang}</code>")
            + _o(html.escape(k.gia_tri_vang), "chat" if k.kieu == KHOP_CHAT else "long")
            + _o(f"<code>{k.vai_pred}</code>")
            + _o(html.escape(k.gia_tri_pred))
            + _o("khớp chặt" if k.kieu == KHOP_CHAT else "khớp lỏng")
            + "</tr>"
        )
    for k in cham.lan_vai:
        hang.append(
            "<tr>"
            + _o(f"<code>{k.vai_vang}</code>")
            + _o(html.escape(k.gia_tri_vang), "lan")
            + _o(f"<code>{k.vai_pred}</code>", "lan")
            + _o(html.escape(k.gia_tri_pred))
            + _o("lẫn vai")
            + "</tr>"
        )
    for vai, gia_tri in cham.trung_nhan:
        hang.append(
            "<tr>"
            + _o(f"<code>{vai}</code>")
            + _o(html.escape(gia_tri), "thieu")
            + _o("")
            + _o("")
            + _o("nhãn vàng lặp đúng giá trị này, pipeline chỉ trả một lần")
            + "</tr>"
        )
    for vai, gia_tri in cham.ung_vien_da_dung:
        hang.append(
            "<tr>"
            + _o(f"<code>{vai}</code>")
            + _o(html.escape(gia_tri), "thieu")
            + _o("")
            + _o("")
            + _o("một nhãn khác cùng vai đã tiêu thụ mất slot pred khớp được")
            + "</tr>"
        )
    for vai, gia_tri in cham.vang_han:
        hang.append(
            "<tr>"
            + _o(f"<code>{vai}</code>")
            + _o(html.escape(gia_tri), "thieu")
            + _o("")
            + _o("")
            + _o("<b>vắng hẳn</b>")
            + "</tr>"
        )
    for vai, gia_tri in cham.pred_thua:
        hang.append(
            "<tr>"
            + _o("")
            + _o("")
            + _o(f"<code>{vai}</code>", "thua")
            + _o(html.escape(gia_tri), "thua")
            + _o("thừa (FP)")
            + "</tr>"
        )
    return _cuon(
        "<table><tr><th>vai vàng</th><th>giá trị vàng</th><th>vai pred</th>"
        "<th>giá trị pred</th><th>kết quả</th></tr>" + "".join(hang) + "</table>"
    )


def _khoi_tai_lieu(d: VongDaCham) -> str:
    phan = []
    for doc_key in sorted(d.cap_theo_doc):
        cap = d.cap_theo_doc[doc_key]
        muc = d.muc_theo_doc[doc_key]
        cs_cap, cs_muc = cap.ket_qua.chi_so, muc.ket_qua.chi_so
        phan.append(
            f"<details><summary><b>{html.escape(doc_key)}</b> - ghép cặp:"
            f" {cap.ket_qua.so_cap} cặp, {cap.ket_qua.so_fact_vang_khong_ghep} fact vàng"
            f" không ghép, P {_pc(cs_cap.precision)} / R {_pc(cs_cap.recall)};"
            f" mức tài liệu: P {_pc(cs_muc.precision)} / R {_pc(cs_muc.recall)},"
            f" {len(muc.lan_vai)} lẫn vai, {len(muc.vang_han)} vắng hẳn,"
            f" {len(muc.trung_nhan) + len(muc.ung_vien_da_dung)} nhãn hết chỗ</summary>"
            "<h4>Chỉ số ghép cặp</h4>"
            + _bang_cap(cap)
            + "<h4>Chỉ số mức tài liệu</h4>"
            + _bang_muc_tai_lieu(muc)
            + "</details>"
        )
    return "".join(phan)


CHU_THICH = (
    '<p class="chu-thich"><span class="chat">khớp chặt</span>'
    '<span class="long">khớp lỏng (chuỗi con)</span>'
    '<span class="lan">lẫn vai</span>'
    '<span class="thieu">thiếu / vắng hẳn (FN)</span>'
    '<span class="thua">thừa (FP)</span></p>'
)


# ---------------------------------------------------------------------------
# Ngoại suy
# ---------------------------------------------------------------------------


def _bang_ngoai_suy(bang: BangNgoaiSuy) -> str:
    hang = []
    for k in bang.khoan:
        hang.append(
            "<tr>"
            + _o(f"<code>{html.escape(k.ten)}</code>")
            + _o(html.escape(k.mo_ta))
            + _o(html.escape(k.model))
            + _o(f"{k.so_luong} {html.escape(k.don_vi)}", "so")
            + _o(str(k.token_vao), "so")
            + _o(str(k.token_ra), "so")
            + _o(so_vn(k.chi_phi_usd), "so")
            + _o(html.escape(k.nguon))
            + _o("; ".join(html.escape(g) for g in k.gia_dinh))
            + "</tr>"
        )
    hang.append(
        "<tr>"
        + _o("<b>TỔNG</b>")
        + _o("") * 5
        + _o(f"<b>{so_vn(bang.tong_usd)}</b>", "so")
        + _o("") * 2
        + "</tr>"
    )
    trang_thai = "CHẠM/VƯỢT" if bang.vuot_bao_dong else "chưa chạm"
    return _cuon(
        "<table><tr><th>Khoản</th><th>Mô tả</th><th>Model</th><th>Quy mô</th>"
        "<th>token vào</th><th>token ra</th><th>USD</th><th>nguồn</th>"
        "<th>giả định có tên</th></tr>" + "".join(hang) + "</table>"
    ) + (
        f'<p class="ghi-chu">Mức báo động {bang.muc_bao_dong_usd:.0f} USD (PRD mục'
        f" 4.3): <b>{trang_thai}</b>, {so_vn(bang.phan_tram_bao_dong, 1)}% mức báo động."
        f" {html.escape(GHI_CHU_CHUA_CONG)} {html.escape(GHI_CHU_DON_GIA)}</p>"
    )


# ---------------------------------------------------------------------------
# Dựng trang
# ---------------------------------------------------------------------------


def dung_html(bo: BoVang, da_cham: list[VongDaCham], bang: BangNgoaiSuy) -> str:
    luc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    khoi = [
        '<div class="khoi"><h1>Vòng lặp precision trích xuất và điểm quyết R2</h1>'
        f'<p class="ghi-chu">Dựng lúc {luc} từ {len(da_cham)} file trong'
        " <code>eval/ket_qua_do/</code>; không lời gọi LLM nào.</p>"
        f"<p>Mẫu số: <b>{bo.mau_so_slot()} slot đã điền</b> trên"
        f" {len(bo.tai_lieu_cham())} tài liệu chấm"
        f" ({len(bo.tai_lieu_few_shot())} tài liệu few-shot bị loại:"
        f" {html.escape(', '.join(t.doc_key for t in bo.tai_lieu_few_shot()))}).</p>"
        f"<h2>So các vòng</h2>{_bang_so_vong(da_cham)}"
        '<p class="ghi-chu">Đơn vị chấm là slot đã điền (PRD 2.6). "P (lỏng)" là số'
        " chính: một giá trị khớp khi nó bằng hoặc là chuỗi con của giá trị bên kia,"
        " và phải nằm ở <i>đúng vai</i>. Hai chỉ số hỏi hai câu khác nhau - ghép cặp"
        " hỏi hệ có dựng lại đúng ranh giới từng fact không, mức tài liệu hỏi hệ có"
        " dán đúng 8 vai không - và chênh giữa chúng là phần LLM gom fact khác nhãn"
        " tay. Cột <b>lẫn vai</b> và <b>trong đó vắng hẳn</b> tách hai loại lỗi: dán sai"
        " vai khác hẳn không trích ra. Cột <b>ô cột <i>thiếu</i></b> là tổng cột"
        " <code>thiếu</code> của ma trận, và nó <i>không</i> phải bỏ sót: với chỉ số"
        " mức tài liệu nó gộp thêm nhãn tay lặp và ứng viên đã bị tiêu thụ, với chỉ"
        " số ghép cặp nó gộp cả trọn bộ slot của mọi fact vàng không ghép được - nên"
        " chỉ số ghép cặp để trống cột <i>vắng hẳn</i>.</p></div>",
        f'<div class="khoi"><h2>Verdict R2 (ngưỡng {_pc(NGUONG_R2)})</h2>'
        + _bang_verdict(da_cham)
        + "</div>",
    ]
    for d in da_cham:
        v = d.vong
        khoi.append(
            f'<div class="khoi"><h2>Vòng {html.escape(v.vong)}'
            f'<span class="nhan">{html.escape(v.model)}</span>'
            f'<span class="nhan">{v.so_chunk()} chunk</span>'
            f'<span class="nhan">{so_vn(v.chi_phi_usd())} USD</span></h2>'
            f"<h3>Ma trận lẫn lộn A13 (chỉ số mức tài liệu)</h3>{_bang_ma_tran(d.muc, v.vong)}"
            f"<h3>Theo từng vai - chỉ số ghép cặp (cổng R2)</h3>{_bang_theo_vai(d.cap)}"
            f"<h3>Theo từng vai - chỉ số mức tài liệu</h3>{_bang_theo_vai(d.muc)}"
            f"<h3>Từng tài liệu</h3>{CHU_THICH}" + _khoi_tai_lieu(d) + "</div>"
        )
    khoi.append(
        '<div class="khoi"><h2>Ngoại suy chi phí FR-30</h2>'
        + _bang_ngoai_suy(bang)
        + "</div>"
    )
    return (
        '<!doctype html>\n<html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Vòng lặp precision và R2</title>"
        f"<style>{_CSS}</style></head><body>" + "".join(khoi) + "</body></html>\n"
    )


def _tham_so(argv):
    p = argparse.ArgumentParser(
        description="Chấm mọi vòng đo trong eval/ket_qua_do/ và dựng trang báo cáo (không gọi LLM)"
    )
    p.add_argument("dich", nargs="?", type=Path, default=None, help="đường dẫn file HTML đích")
    p.add_argument(
        "--thu-muc",
        dest="thu_muc_ket_qua",
        type=Path,
        default=None,
        help="thư mục chứa file vòng đo (cùng tên cờ với eval.do_trich_xuat)",
    )
    return p.parse_args(list(argv))


def main(
    dich: Path | None = None,
    thu_muc_ket_qua: Path | None = None,
    argv: list[str] | None = None,
) -> int:
    """Dựng trang và in bảng tổng; thiếu dữ liệu hay bộ vàng hỏng thì trả 1."""
    if argv is not None:
        ts = _tham_so(argv)
        dich = dich or ts.dich
        thu_muc_ket_qua = thu_muc_ket_qua or ts.thu_muc_ket_qua
    thu_muc = Path(thu_muc_ket_qua) if thu_muc_ket_qua is not None else THU_MUC_KET_QUA
    try:
        vong = doc_moi_vong(thu_muc)
    except KetQuaDoKhongHopLe as loi:
        print(str(loi), file=sys.stderr)
        return 1
    if not vong:
        print(
            f"chưa có vòng đo nào trong {thu_muc}. Chạy một vòng trước (tốn tiền thật):\n"
            f"  {LENH_CHAY_VONG}",
            file=sys.stderr,
        )
        return 1
    try:
        bo = doc_bo_vang()
    except BoVangKhongHopLe as loi:
        print(str(loi), file=sys.stderr)
        return 1

    da_cham: list[VongDaCham] = []
    for v in vong:
        try:
            da_cham.append(VongDaCham(v, bo))
        except ValueError as loi:
            # Một vòng cũ chấm trên tập tài liệu khác (corpus đã đổi) không được
            # chặn báo cáo của các vòng còn dùng được; bỏ vòng đó và nói rõ.
            print(f"BỎ QUA vòng {v.vong}: {loi}", file=sys.stderr)
    if not da_cham:
        print("không vòng nào chấm được trên bộ vàng hiện tại", file=sys.stderr)
        return 1

    bang = ngoai_suy(SO_DO_NAP_THAT)
    dich = Path(dich) if dich is not None else DUONG_DAN_HTML
    try:
        dich.parent.mkdir(parents=True, exist_ok=True)
        dich.write_text(dung_html(bo, da_cham, bang), encoding="utf-8")
    except OSError as loi:
        print(f"không ghi được {dich}: {loi}", file=sys.stderr)
        return 1

    _in_console(bo, da_cham, bang)
    print(f"ghi {dich}")
    return 0


def _in_console(bo: BoVang, da_cham: list[VongDaCham], bang: BangNgoaiSuy) -> None:
    print(f"mẫu số {bo.mau_so_slot()} slot trên {len(bo.tai_lieu_cham())} tài liệu chấm")
    print(
        f"{'vòng':<18}{'model':<19}{'chỉ số':<14}{'P':>8}{'R':>8}{'F1':>8}"
        f"{'P chặt':>9}{'P bỏ subj':>11}{'lẫn vai':>9}{'ô thiếu':>9}{'vắng hẳn':>10}"
    )
    for d in da_cham:
        for ten, kq in ((CHI_SO_GHEP_CAP, d.cap), (CHI_SO_MUC_TAI_LIEU, d.muc)):
            cs: ChiSo = kq.chi_so
            phu = mau_so_phu(kq)
            print(
                f"{d.vong.vong:<18}{d.vong.model:<19}{ten:<14}{_pc(cs.precision):>8}"
                f"{_pc(cs.recall):>8}{_pc(cs.f1):>8}{_pc(cs.precision_chat):>9}"
                f"{_pc(phu.precision):>11}{kq.so_lan_vai:>9}{kq.so_o_thieu:>9}"
                f"{_so_hoac_gach(kq.so_vang_han):>10}"
            )
    print(
        f"\nVerdict R2 (ngưỡng {_pc(NGUONG_R2)}; cổng chính thức ="
        f" {CONG_R2_CHI_SO} / {CONG_R2_MAU_SO}):"
    )
    for d in da_cham:
        for c, m in COT_VERDICT:
            cs = d.chi_so(c, m)
            dau = " <-- cổng R2" if _la_cong(c, m) else ""
            print(
                f"  - {d.vong.vong} ({d.vong.model}) {c} / {m}:"
                f" {_pc(cs.precision)} -> {verdict_r2(cs.precision)}{dau}"
            )
    print()
    for dong in dong_bang(bang):
        print(dong)
    print(GHI_CHU_CHUA_CONG)


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
