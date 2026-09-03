"""Ba tỷ lệ n-ngôi của `khao_sat` in cạnh ba tỷ lệ của `synth` (story 2.10).

Chạy: `uv run python -m eval.xem_ty_le [đích]`, mặc định ghi
`eval/expr/ty_le_n_ngoi.html`. Không chạm kho, không gọi LLM: nó đọc hai ảnh
chụp đồ thị **đã commit** và bảng hạng độ nhạy, rồi gọi hàm thuần của
`eval/ty_le_n_ngoi.py`. Chạy hai lần trên cùng hai ảnh chụp cho cùng ba con số.

Vì sao trang này in **hai cột chứ không một**: một mình cột `khao_sat` không
trả lời câu hỏi nào. Câu hỏi của story 2.10 là hai tập dựng độc lập về thời
điểm và mục đích có khớp cỡ hay không, nên chênh lệch giữa hai cột mới là kết
quả, còn từng cột chỉ là số liệu.

Hai điều trang phải nói ra ở đầu, không đẩy xuống chân trang:

- Ba tỷ lệ là tỷ lệ trên tập fact **hệ trích được**, không phải tập fact có
  trong bản ghi. Precision ghép cặp đo ở story 2.6 là 70,7%.
- Mẫu số của cột `khao_sat` là 50 bản ghi **giả lập**, nên ba tỷ lệ mất vai trò
  mỏ neo độc lập cho corpus 2.8.
"""

import argparse
import html
import sys
from pathlib import Path
from typing import Mapping

from adapters.sensitivity_loader import DUONG_DAN_MAC_DINH as HANG_MAC_DINH
from adapters.sensitivity_loader import SensitivityRanksInvalid, tai_hang_do_nhay
from eval.cau_hoi import AnhDoThiKhongHopLe, doc_anh_do_thi
from eval.ty_le_n_ngoi import (
    NGUONG_NHAY_CAM,
    NHAN_KHONG_KHOA,
    TOI_THIEU_VAI_N_NGOI,
    BaTyLe,
    HangKhongXacDinh,
    ba_ty_le,
    doi_chieu,
    dong_tom_tat,
    hop_hang,
    hop_loai,
)

_GOC = Path(__file__).resolve().parent
DUONG_DAN_HTML: Path = _GOC / "expr" / "ty_le_n_ngoi.html"
ANH_SYNTH: Path = _GOC / "anh_do_thi" / "synth.json"
ANH_KHAO_SAT: Path = _GOC / "anh_do_thi" / "khao_sat.json"

# Vòng đo chốt của story 2.6 và precision *ghép cặp* trên mẫu số tổng của nó -
# cổng R2 chính thức (`eval/cham_trich_xuat.py`). Ghi ra trang vì ba tỷ lệ đứng
# trên tập fact mà hệ trích được, và người đọc phải thấy con số đó cùng lúc với
# ba tỷ lệ chứ không ở một trang khác.
#
# **Hằng chứ không tính lại tại đây**, kèm một test buộc nó bằng nguồn: chấm lại
# cả bốn vòng đo là công việc của `eval.xem_do_trich_xuat` (nó đọc `eval/data/`,
# `eval/bo_vang_trich_xuat.json` và bốn file trong `eval/ket_qua_do/`), và kéo
# cả dây đó vào một trang chỉ cần *một* con số là buộc trang ba tỷ lệ hỏng theo
# mỗi lần bộ vàng hỏng. Luật số chép tay của story 2.7/2.8 vẫn giữ nguyên: số ở
# đây không được lệch nguồn, và chỗ canh là
# `tests/test_ty_le_n_ngoi.py::test_precision_ghep_cap_khop_vong_chot`.
VONG_CHOT_2_6: str = "v1-deepseek"
PRECISION_GHEP_CAP: float = 0.707

# Lệnh sinh ra ảnh chụp còn thiếu. In nguyên văn ra stderr thay vì một câu
# "thiếu file": người chạy phải dựng lại được bước trước mà không đi tra tài liệu.
LENH_CHUP: Mapping[str, str] = {
    "synth": "HYPER_RAG_MODULE=eval.chup_do_thi scripts/chay-may-chu.sh chup --space synth",
    "khao_sat": (
        "scripts/chay-may-chu.sh nap eval/khao_sat --space khao_sat"
        " --xuat-json eval/so_do_nap/nap-khao-sat.json"
        " && HYPER_RAG_MODULE=eval.chup_do_thi scripts/chay-may-chu.sh chup --space khao_sat"
    ),
}

_CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, "Segoe UI", sans-serif; margin: 0; padding: 24px;
       background: #f6f7f9; color: #16191d; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 18px 0 8px; }
.khoi { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
        padding: 16px; margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #dfe3e8; padding: 6px 8px; vertical-align: top;
         text-align: left; }
th { background: #eef1f4; font-weight: 600; }
td.so { text-align: right; font-variant-numeric: tabular-nums; }
tr.tong td { background: #fbfbfc; font-weight: 600; }
td.nhay { background: #fff3bf; }
.canh-bao { background: #fff8e6; border: 1px solid #f0d48a; border-radius: 6px;
            padding: 10px 12px; margin: 10px 0; font-size: 13px; }
.khong-tinh { color: #a33; }
code { font-size: 12px; color: #5a6069; }
.chu { color: #5a6069; font-size: 13px; }
"""


def _o(t) -> str:
    if t.mau_so == 0:
        return f'<td class="so khong-tinh">{html.escape(t.mo_ta())}</td>'
    return f'<td class="so">{html.escape(t.mo_ta())}</td>'


def _bang_ba_ty_le(trai: BaTyLe, phai: BaTyLe) -> str:
    hang = []
    for d in doi_chieu(trai, phai):
        if d.chenh is None:
            chenh = '<td class="so khong-tinh">không so được</td>'
        else:
            chenh = f'<td class="so">{d.chenh:+.1%}</td>'
        hang.append(f"<tr><td><b>{html.escape(d.ten)}</b></td>{_o(d.trai)}{_o(d.phai)}{chenh}</tr>")
    return (
        f"<table><tr><th>Tỷ lệ</th><th>{html.escape(trai.space)}</th>"
        f"<th>{html.escape(phai.space)}</th><th>chênh (phải - trái)</th></tr>"
        f"{''.join(hang)}</table>"
    )


def _bang_phan_bo_hang(trai: BaTyLe, phai: BaTyLe, ten_hang: Mapping[int, str]) -> str:
    hang = []
    for r in hop_hang(trai, phai):
        a = trai.phan_bo_hang.get(r, 0)
        b = phai.phan_bo_hang.get(r, 0)
        lop = ' class="nhay"' if r >= NGUONG_NHAY_CAM else ""
        ta = f"{a} ({a / trai.so_hyperedge:.1%})" if trai.so_hyperedge else str(a)
        tb = f"{b} ({b / phai.so_hyperedge:.1%})" if phai.so_hyperedge else str(b)
        hang.append(
            f"<tr{lop}><td>{r}</td><td><code>{html.escape(ten_hang.get(r, '?'))}</code></td>"
            f'<td class="so">{ta}</td><td class="so">{tb}</td></tr>'
        )
    hang.append(
        f'<tr class="tong"><td colspan="2">TỔNG hyperedge</td>'
        f'<td class="so">{trai.so_hyperedge}</td><td class="so">{phai.so_hyperedge}</td></tr>'
    )
    nhay_a = sum(v for r, v in trai.phan_bo_hang.items() if r >= NGUONG_NHAY_CAM)
    nhay_b = sum(v for r, v in phai.phan_bo_hang.items() if r >= NGUONG_NHAY_CAM)
    hang.append(
        f'<tr class="tong"><td colspan="2">Nhạy cảm (hạng &ge; {NGUONG_NHAY_CAM})</td>'
        f'<td class="so">{nhay_a}</td><td class="so">{nhay_b}</td></tr>'
    )
    return (
        f"<table><tr><th>Hạng</th><th>Loại nội dung</th>"
        f"<th>{html.escape(trai.space)}</th><th>{html.escape(phai.space)}</th></tr>"
        f"{''.join(hang)}</table>"
    )


def _bang_phan_bo_loai(trai: BaTyLe, phai: BaTyLe) -> str:
    hang = []
    for loai in hop_loai(trai, phai):
        a = trai.phan_bo_loai.get(loai, 0)
        b = phai.phan_bo_loai.get(loai, 0)
        hang.append(
            f"<tr><td><code>{html.escape(loai)}</code></td>"
            f'<td class="so">{a}</td><td class="so">{b}</td></tr>'
        )
    return (
        f"<table><tr><th>Loại nội dung</th><th>{html.escape(trai.space)}</th>"
        f"<th>{html.escape(phai.space)}</th></tr>{''.join(hang)}</table>"
    )


def _khoi_chan_doan(b: BaTyLe) -> str:
    nhay = b.composition_risk.mau_so
    if b.trung_binh_phan_entity_lo is None:
        tb = "không tính được, không ca nào có entity lộ"
    else:
        tb = (
            f"khi một ca đã hở thì trung bình <b>{b.trung_binh_phan_entity_lo:.1%}</b>"
            f" số entity của nó là lộ (trung bình trên {b.so_nhay_cam_co_entity_lo} ca"
            " có ít nhất một entity lộ, không phải trên mọi ca nhạy cảm)"
        )
    return (
        f"<p><b>{html.escape(b.space)}</b>: {b.so_nhay_cam_lo_mot_phan}/{nhay} ca nhạy"
        f" cảm lộ <i>một phần</i> (có entity lộ mà không lộ hết),"
        f" {b.so_nhay_cam_co_entity_lo}/{nhay} có ít nhất một entity lộ, và"
        f" {b.composition_risk.tu_so}/{nhay} lộ hết - chính là tử số của tỷ lệ 3."
        f" {tb}.</p>"
    )


def _loai_cua(b: BaTyLe) -> set[str]:
    """Loại nội dung *thật* có mặt, bỏ nhãn của ca không khóa."""
    return {t for t in b.phan_bo_loai if not t.startswith(NHAN_KHONG_KHOA)}


def _khoi_lech_truc_loai(trai: BaTyLe, phai: BaTyLe, ten_hang) -> str:
    """Cảnh báo hai cột không cùng trục loại nội dung.

    Bảng hai cột đặt hai phân bố cạnh nhau như thể chúng đo trên cùng một trục.
    Chúng không: khảo sát cố ý không phủ đủ 13 loại. Chênh lệch của một tỷ lệ vì
    vậy trộn hai nguyên nhân - hình dạng tri thức khác nhau, và tập loại nội dung
    khác nhau - và trang phải nói ra điều đó ở chỗ người ta đọc con số.
    """
    chi_trai = sorted(_loai_cua(trai) - _loai_cua(phai))
    chi_phai = sorted(_loai_cua(phai) - _loai_cua(trai))
    if not chi_trai and not chi_phai:
        return ""
    phan = []
    for ten, ds in ((trai.space, chi_trai), (phai.space, chi_phai)):
        if ds:
            nhay = [t for t in ds if ten_hang.get(t, 0) >= NGUONG_NHAY_CAM]
            mo_ta = ", ".join(f"<code>{html.escape(t)}</code>" for t in ds)
            them = (
                f" (trong đó <b>{len(nhay)}</b> loại nhạy cảm: "
                + ", ".join(f"<code>{html.escape(t)}</code>" for t in nhay)
                + ")"
                if nhay
                else ""
            )
            phan.append(f"chỉ <b>{html.escape(ten)}</b> có {mo_ta}{them}")
    return (
        '<div class="canh-bao"><b>Hai cột không cùng trục loại nội dung.</b> '
        + "; ".join(phan)
        + ". Chênh lệch của mỗi tỷ lệ vì vậy trộn hai nguyên nhân: hình dạng tri"
        " thức khác nhau, và tập loại nội dung khác nhau. Đây là một quyết định"
        " đã khai trong <code>eval/khao_sat_thiet_ke.yaml</code> và trong ADR-012,"
        " không phải một lỗ phát hiện muộn.</div>"
    )


def dung_html(trai: BaTyLe, phai: BaTyLe, ten_hang: Mapping[int, str]) -> str:
    """Dựng toàn bộ trang từ hai kết quả đã tính. Hàm thuần, không I/O."""
    hang_theo_ten = {ten: r for r, ten in ten_hang.items()}
    tom_tat = "".join(
        f"<p><b>{html.escape(b.space)}</b> ({b.so_tai_lieu} tài liệu,"
        f" {b.so_hyperedge} hyperedge, chụp {html.escape(b.ngay_do)}):<br>"
        + "<br>".join(html.escape(d) for d in dong_tom_tat(b))
        + "</p>"
        for b in (trai, phai)
    )
    return (
        '<!doctype html>\n<html lang="vi"><head><meta charset="utf-8">'
        "<title>Ba tỷ lệ n-ngôi: khao_sat cạnh synth</title>"
        f"<style>{_CSS}</style></head><body>"
        '<div class="khoi">'
        "<h1>Ba tỷ lệ n-ngôi</h1>"
        f'<div class="canh-bao"><b>Hai điều phải đọc trước ba con số.</b><br>'
        f"1. Ba tỷ lệ tính trên tập fact mà <b>hệ trích được</b>, không phải tập fact"
        f" có trong bản ghi. Precision ghép cặp của vòng đo chốt (story 2.6) là"
        f" {PRECISION_GHEP_CAP:.1%}, nên tập đếm đã lệch khỏi tập thật chừng đó.<br>"
        f"2. Mẫu số của cột <code>khao_sat</code> là 50 bản ghi <b>giả lập</b>"
        f" (quyết định 03/09/2026: doanh nghiệp không lưu báo cáo sự cố ở dạng dùng"
        f" được). Ba tỷ lệ vì vậy <b>mất vai trò mỏ neo độc lập</b> cho corpus 2.8:"
        f" hai tập cùng một bên dựng. Chúng còn dùng được để kiểm tính nhất quán nội"
        f" bộ giữa hai vật dựng khác thời điểm và khác mục đích.</div>"
        f'<p class="chu">Định nghĩa đếm chốt ở <code>docs/adr/ADR-012</code>:'
        f" n-ngôi là hyperedge có từ {TOI_THIEU_VAI_N_NGOI} vai slot được điền trở lên;"
        f" nhạy cảm là hạng độ nhạy từ {NGUONG_NHAY_CAM} (<code>bao_cao_su_co</code>)"
        f" trở lên; composition risk là ca nhạy cảm mà <b>mọi</b> entity cấu thành đều"
        f" còn xuất hiện ở ít nhất một hyperedge không nhạy cảm. Trang này đọc hai ảnh"
        f" chụp đã commit, không chạm kho.</p>"
        f"{tom_tat}"
        "<h2>Ba tỷ lệ, hai cột cạnh nhau</h2>"
        f"{_bang_ba_ty_le(trai, phai)}"
        "<h2>Phân bố mức nhạy cảm theo hạng</h2>"
        f'<p class="chu">Đếm trên hyperedge, không trên tài liệu: hai tài liệu cùng'
        " loại có thể cho số fact rất khác nhau. Hàng tô vàng là vùng nhạy cảm.</p>"
        f"{_bang_phan_bo_hang(trai, phai, ten_hang)}"
        "<h2>Phân bố theo loại nội dung</h2>"
        f"{_khoi_lech_truc_loai(trai, phai, hang_theo_ten)}"
        f"{_bang_phan_bo_loai(trai, phai)}"
        "<h2>Ba số chẩn đoán của Composition-Risk</h2>"
        f'<p class="chu">Không phải tỷ lệ thứ tư và không vào báo cáo như một kết quả.'
        " Chúng chỉ để đọc được một Composition-Risk bằng 0: 0 vì không mảnh nào lộ,"
        " hay 0 vì luôn còn đúng một mảnh không lộ.</p>"
        f"{_khoi_chan_doan(trai)}{_khoi_chan_doan(phai)}"
        "</div></body></html>\n"
    )


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="In ba tỷ lệ n-ngôi của space khao_sat cạnh space synth (đọc thuần)"
    )
    p.add_argument(
        "dich",
        nargs="?",
        type=Path,
        default=None,
        help=f"file HTML đích (mặc định {DUONG_DAN_HTML})",
    )
    p.add_argument(
        "--anh-synth",
        type=Path,
        default=ANH_SYNTH,
        dest="anh_synth",
        metavar="FILE",
        help="ảnh chụp đồ thị corpus (mặc định eval/anh_do_thi/synth.json)",
    )
    p.add_argument(
        "--anh-khao-sat",
        type=Path,
        default=ANH_KHAO_SAT,
        dest="anh_khao_sat",
        metavar="FILE",
        help="ảnh chụp đồ thị khảo sát (mặc định eval/anh_do_thi/khao_sat.json)",
    )
    p.add_argument(
        "--hang",
        type=Path,
        default=HANG_MAC_DINH,
        metavar="FILE",
        help="bảng hạng độ nhạy (mặc định config/hang-do-nhay.yaml)",
    )
    return p.parse_args(argv)


def ly_do_tu_choi_anh(duong_dan, space: str, anh) -> str | None:
    """Lý do từ chối một ảnh chụp cho cột `space`, hoặc `None` nếu nhận được.

    Chặn đúng một ca mà loader không thấy: file hợp lệ nhưng **của space khác**.
    Trỏ nhầm `--anh-khao-sat` vào `synth.json` cho ra một trang hai cột giống hệt
    nhau, ba chênh lệch bằng 0, và một kết luận "khớp cỡ tuyệt đối" - kết quả sai
    nguy hiểm nhất mà story này có thể sinh ra, vì nó trông y hệt một kết quả rất
    tốt. `eval/ct03.py` đã có cùng rào cho `--space`; đây là bản của trang hai cột.

    Hàm thuần để test chấm được hai chiều mà không cần dựng file.
    """
    if anh.space == space:
        return None
    return (
        f"{duong_dan} là ảnh chụp của space {anh.space!r} nhưng đang được dùng cho"
        f" cột {space!r}: hai cột phải là hai space khác nhau, nếu không trang in"
        " một space hai lần và ba chênh lệch bằng 0 vì hai cột là một, chứ không"
        " vì hai tập khớp cỡ"
    )


def _doc(duong_dan: Path, space: str):
    """Đọc một ảnh chụp, kiểm nó đúng space của cột; thiếu file thì nói luôn lệnh dựng lại."""
    if not Path(duong_dan).exists():
        raise AnhDoThiKhongHopLe(
            [
                f"{duong_dan} chưa có: chưa nạp và chưa chụp space {space!r}."
                f" Dựng lại bằng: {LENH_CHUP.get(space, '(xem AGENTS.md)')}"
            ]
        )
    anh = doc_anh_do_thi(duong_dan)
    ly_do = ly_do_tu_choi_anh(duong_dan, space, anh)
    if ly_do:
        raise AnhDoThiKhongHopLe([ly_do])
    return anh


def main(argv: list[str] | None = None) -> int:
    """In ba tỷ lệ hai space; ảnh chụp thiếu hay lạ thì in lý do ra stderr và trả 1.

    Không có nhánh nào dựng bảng bằng một cột: một trang chỉ có `khao_sat` là
    một trang không trả lời câu hỏi khớp cỡ, và in nó ra rồi thoát 0 là để người
    đọc tưởng bước đối chiếu đã chạy.
    """
    ts = _tham_so(sys.argv[1:] if argv is None else list(argv))
    try:
        hang = dict(tai_hang_do_nhay(ts.hang).hang)
        anh_synth = _doc(ts.anh_synth, "synth")
        anh_khao_sat = _doc(ts.anh_khao_sat, "khao_sat")
        trai = ba_ty_le(anh_synth, hang)
        phai = ba_ty_le(anh_khao_sat, hang)
    except (AnhDoThiKhongHopLe, HangKhongXacDinh, SensitivityRanksInvalid) as loi:
        print(str(loi), file=sys.stderr)
        return 1

    ten_hang = {v: k for k, v in hang.items()}
    dich = Path(ts.dich) if ts.dich is not None else DUONG_DAN_HTML
    try:
        dich.parent.mkdir(parents=True, exist_ok=True)
        dich.write_text(dung_html(trai, phai, ten_hang), encoding="utf-8")
    except OSError as loi:
        print(f"không ghi được {dich}: {loi}", file=sys.stderr)
        return 1

    for b in (trai, phai):
        print(
            f"space {b.space}: {b.so_tai_lieu} tài liệu, {b.so_hyperedge} hyperedge,"
            f" chụp {b.ngay_do}"
        )
        for d in dong_tom_tat(b):
            print(f"  {d}")
        tb = (
            "không tính được"
            if b.trung_binh_phan_entity_lo is None
            else f"{b.trung_binh_phan_entity_lo:.1%}"
        )
        print(
            f"  chẩn đoán: {b.so_nhay_cam_lo_mot_phan} ca lộ một phần,"
            f" {b.so_nhay_cam_co_entity_lo} ca có ít nhất một entity lộ,"
            f" trung bình phần entity lộ trên nhóm đó {tb}"
        )
    for d in doi_chieu(trai, phai):
        chenh = "không so được" if d.chenh is None else f"{d.chenh:+.1%}"
        print(f"chênh {d.ten}: {chenh} ({trai.space} -> {phai.space})")
    chi_trai = sorted(_loai_cua(trai) - _loai_cua(phai))
    chi_phai = sorted(_loai_cua(phai) - _loai_cua(trai))
    if chi_trai or chi_phai:
        print(
            f"cảnh báo: hai cột không cùng trục loại nội dung - chỉ {trai.space} có"
            f" {chi_trai}, chỉ {phai.space} có {chi_phai}"
        )
    print(
        "ba tỷ lệ tính trên tập fact hệ trích được (precision ghép cặp"
        f" {PRECISION_GHEP_CAP:.1%} của vòng {VONG_CHOT_2_6}), mẫu số khao_sat là"
        " bản ghi giả lập"
    )
    print(f"ghi {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
