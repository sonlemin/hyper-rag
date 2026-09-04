"""Ba tỷ lệ n-ngôi của `khao_sat` và `real` in cạnh ba tỷ lệ của `synth`.

Chạy: `uv run python -m eval.xem_ty_le [đích] [--anh-real FILE]`, mặc định ghi
`eval/expr/ty_le_n_ngoi.html`. Không chạm kho, không gọi LLM: nó đọc ảnh chụp
đồ thị và bảng hạng độ nhạy, rồi gọi hàm thuần của `eval/ty_le_n_ngoi.py`.
Chạy hai lần trên cùng bộ ảnh chụp cho cùng ba con số.

Vì sao trang này in **từ hai cột trở lên, không bao giờ một**: một mình cột
`khao_sat` không trả lời câu hỏi nào. Câu hỏi của story 2.10 là hai tập dựng độc
lập về thời điểm và mục đích có khớp cỡ hay không, nên chênh lệch giữa các cột
mới là kết quả, còn từng cột chỉ là số liệu. Cột đầu (`synth`) là **mốc**: mọi
chênh tính so với nó, vì nó là tập duy nhất có precision trích xuất đã đo.

Cột thứ ba `real` (story 2.11) là **tùy chọn** và không có đường dẫn mặc định:
ảnh chụp của space `real` dump nguyên văn giá trị mọi slot của tài liệu công ty
nên nó nằm ngoài cây repo. Thiếu cờ `--anh-real` thì trang in hai cột như cũ.

Ba điều trang phải nói ra ở đầu, không đẩy xuống chân trang:

- Ba tỷ lệ là tỷ lệ trên tập fact **hệ trích được**, không phải tập fact có
  trong bản ghi. Precision ghép cặp đo ở story 2.6 là 70,7%.
- Mẫu số của cột `khao_sat` là 50 bản ghi **giả lập**, nên ba tỷ lệ mất vai trò
  mỏ neo độc lập cho corpus 2.8.
- Cột `real` đo trên tài liệu thật nhưng trích bằng **một bộ trích xuất khác**
  (Qwen 2.5 7B cục bộ, precision chưa đo), nên chênh của nó trộn hai nguyên nhân.

Trang này **không in id hay giá trị slot** của bất kỳ hyperedge nào; điểm lộ duy
nhất của cột `real` là chuỗi `content_type`/`scope`, tức nhãn phân loại. Nó vẫn
nằm trong `.gitignore` như mọi trang của `eval/expr/`.
"""

import argparse
import html
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

from adapters.sensitivity_loader import DUONG_DAN_MAC_DINH as HANG_MAC_DINH
from adapters.sensitivity_loader import SensitivityRanksInvalid, tai_hang_do_nhay
from eval.anh_rut_gon import la_space_rut_gon, space_goc
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
    loai_chung,
)

_GOC = Path(__file__).resolve().parent
DUONG_DAN_HTML: Path = _GOC / "expr" / "ty_le_n_ngoi.html"
ANH_SYNTH: Path = _GOC / "anh_do_thi" / "synth.json"
ANH_KHAO_SAT: Path = _GOC / "anh_do_thi" / "khao_sat.json"

# Cột `real` **không có mặc định**, và đó là một quyết định chứ không phải một
# thiếu sót: ảnh chụp *đầy đủ* của space `real` dump nguyên văn giá trị mọi slot
# của tài liệu công ty, nên nó không bao giờ nằm trong cây repo
# (`eval/chup_do_thi.py` từ chối ghi nó vào đây). Một đường dẫn mặc định trong
# `eval/anh_do_thi/` là một lời mời chép file đó vào đúng chỗ mà git đang theo
# dõi - kể cả khi bản rút gọn đã nằm sẵn ở đó, vì hai file chỉ khác nhau một
# hậu tố tên.
#
# Cờ `--anh-real` nhận **cả hai dạng**: ảnh đầy đủ (ngoài repo) và ảnh rút gọn
# (`real_rut_gon`, có commit). Ba tỷ lệ ra bằng nhau trên hai dạng - đó chính là
# tính chất làm bản rút gọn dùng được - còn tiêu đề cột thì khác, nên người đọc
# trang luôn biết mình đang nhìn dạng nào.
SPACE_REAL: str = "real"

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
    SPACE_REAL: (
        "HYPER_RAG_CUC_BO=1 scripts/chay-may-chu.sh nap <thư mục real ngoài repo>"
        " --space real --xuat-json eval/so_do_nap/nap-real.json"
        " && HYPER_RAG_CUC_BO=1 HYPER_RAG_MODULE=eval.chup_do_thi"
        " scripts/chay-may-chu.sh chup --space real --rut-gon"
        " --muoi /root/hyper-rag-data/muoi-anh-rut-gon.txt"
        " (rồi scp eval/anh_do_thi/real_rut_gon.json về và commit; bản **đầy đủ**"
        " thì --dich ra ngoài cây repo và không bao giờ commit)"
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


def _chenh(gia_tri: float | None) -> str:
    if gia_tri is None:
        return '<td class="so khong-tinh">không so được</td>'
    return f'<td class="so">{gia_tri:+.1%}</td>'


def _bang_ba_ty_le(*bo: BaTyLe) -> str:
    """Ba hàng tỷ lệ, N cột số, N-1 cột chênh - mọi chênh so với **cột đầu**.

    Cột đầu (`synth`) là mốc của cả trang: nó là tập duy nhất có precision trích
    xuất đã đo. So `real` với `khao_sat` thay vì với mốc là so hai tập mà **cả
    hai** đều chưa neo vào gì.
    """
    hang = []
    for d in doi_chieu(*bo):
        o = "".join(_o(c) for c in d.cot)
        ch = "".join(_chenh(d.chenh_voi_moc(i)) for i in range(1, len(d.cot)))
        hang.append(f"<tr><td><b>{html.escape(d.ten)}</b></td>{o}{ch}</tr>")
    dau_cot = "".join(f"<th>{html.escape(b.space)}</th>" for b in bo)
    dau_chenh = "".join(
        f"<th>chênh {html.escape(b.space)} - {html.escape(bo[0].space)}</th>" for b in bo[1:]
    )
    return f"<table><tr><th>Tỷ lệ</th>{dau_cot}{dau_chenh}</tr>{''.join(hang)}</table>"


def _bang_phan_bo_hang(bo: Sequence[BaTyLe], ten_hang: Mapping[int, str]) -> str:
    hang = []
    for r in hop_hang(*bo):
        lop = ' class="nhay"' if r >= NGUONG_NHAY_CAM else ""
        o = []
        for b in bo:
            v = b.phan_bo_hang.get(r, 0)
            o.append(
                f'<td class="so">{v} ({v / b.so_hyperedge:.1%})</td>'
                if b.so_hyperedge
                else f'<td class="so">{v}</td>'
            )
        hang.append(
            f"<tr{lop}><td>{r}</td><td><code>{html.escape(ten_hang.get(r, '?'))}</code></td>"
            f"{''.join(o)}</tr>"
        )
    tong = "".join(f'<td class="so">{b.so_hyperedge}</td>' for b in bo)
    hang.append(f'<tr class="tong"><td colspan="2">TỔNG hyperedge</td>{tong}</tr>')
    nhay = "".join(
        f'<td class="so">'
        f"{sum(v for r, v in b.phan_bo_hang.items() if r >= NGUONG_NHAY_CAM)}</td>"
        for b in bo
    )
    hang.append(
        f'<tr class="tong"><td colspan="2">Nhạy cảm (hạng &ge; {NGUONG_NHAY_CAM})</td>'
        f"{nhay}</tr>"
    )
    dau = "".join(f"<th>{html.escape(b.space)}</th>" for b in bo)
    return f"<table><tr><th>Hạng</th><th>Loại nội dung</th>{dau}</tr>{''.join(hang)}</table>"


def _bang_phan_bo_loai(bo: Sequence[BaTyLe]) -> str:
    hang = []
    for loai in hop_loai(*bo):
        o = "".join(
            f'<td class="so">{b.phan_bo_loai.get(loai, 0)}</td>' for b in bo
        )
        hang.append(f"<tr><td><code>{html.escape(loai)}</code></td>{o}</tr>")
    dau = "".join(f"<th>{html.escape(b.space)}</th>" for b in bo)
    return f"<table><tr><th>Loại nội dung</th>{dau}</tr>{''.join(hang)}</table>"


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


def _khoi_lech_truc_loai(bo: Sequence[BaTyLe], ten_hang) -> str:
    """Cảnh báo các cột không cùng trục loại nội dung.

    Bảng đặt các phân bố cạnh nhau như thể chúng đo trên cùng một trục. Chúng
    không: khảo sát cố ý không phủ đủ 13 loại, và tập tài liệu thật càng không.
    Chênh lệch của một tỷ lệ vì vậy trộn hai nguyên nhân - hình dạng tri thức
    khác nhau, và tập loại nội dung khác nhau - và trang phải nói ra điều đó ở
    chỗ người ta đọc con số.

    Với hai cột, "phần riêng của mỗi cột" đúng bằng hiệu hai chiều mà story 2.10
    in ra; công thức chung là "nằm ngoài phần giao của **mọi** cột".
    """
    chung = loai_chung(*bo)
    rieng = [(b.space, sorted(_loai_cua(b) - chung)) for b in bo]
    if not any(ds for _, ds in rieng):
        return ""
    phan = []
    for ten, ds in rieng:
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
        '<div class="canh-bao"><b>Các cột không cùng trục loại nội dung.</b> '
        + "; ".join(phan)
        + ". Chênh lệch của mỗi tỷ lệ vì vậy trộn hai nguyên nhân: hình dạng tri"
        " thức khác nhau, và tập loại nội dung khác nhau. Đây là một quyết định"
        " đã khai trong <code>eval/khao_sat_thiet_ke.yaml</code>, trong bảng thiết"
        " kế của space <code>real</code> và trong ADR-012, không phải một lỗ phát"
        " hiện muộn.</div>"
    )


def _bo_the(s: str) -> str:
    """Bỏ thẻ HTML để một dòng bằng chứng dùng lại được ở console.

    Một bản console viết tay là một bản thứ hai của cùng ba câu, và hai bản sẽ
    trôi khỏi nhau - đúng lúc người đọc console tin rằng nó nói cùng thứ với
    trang.
    """
    return re.sub(r"<[^>]+>", "", s).replace("&ge;", ">=")


def _phan_tram(gia_tri: float | None) -> str:
    return "không tính được" if gia_tri is None else f"{gia_tri:.1%}"


def dau_van_tay_bo_trich_xuat(cot: BaTyLe, moc: BaTyLe) -> list[str]:
    """Ba bằng chứng **đo được** rằng hai cột đến từ hai bộ trích xuất khác nhau.

    Mọi con số tính từ chính hai ảnh chụp, không chép tay: một cảnh báo mang số
    chép tay nói về lần nạp trước chứ không về file đang mở, và đó đúng là kiểu
    sai mà người đọc không có cách nào nhận ra.

    Ba dấu, chọn vì mỗi dấu chỉ vào một cơ chế khác nhau:

    1. **Trần dưới của số vai.** Tỷ lệ 1 đếm hyperedge có từ 3 vai. Một cột
       không có hyperedge 2 vai *nào* trong khi cột mốc có hàng chục thì tỷ lệ 1
       bằng 100% là một hằng đúng theo định nghĩa, không phải một phép đo.
    2. **Vai bị điền thừa.** Vai mà cột này điền nhiều hơn mốc nhiều nhất. Một
       bộ trích xuất bỏ sót thì *thiếu* vai; thừa vai đều tay trên mọi fact là
       dấu nó tự điền thay vì đọc ra.
    3. **Entity lặp giữa các vai.** Một fact lành hiếm khi lấy cùng một thực thể
       làm hai chiều; tỷ lệ này cao là dấu nhồi vai cho đủ.
    """
    dong: list[str] = []
    hai_vai, hai_vai_moc = cot.phan_hyperedge_hai_vai(), moc.phan_hyperedge_hai_vai()
    if hai_vai is not None and hai_vai_moc is not None:
        dong.append(
            f"<b>Không một hyperedge 2 vai nào</b> ({_phan_tram(hai_vai)} so với"
            f" {_phan_tram(hai_vai_moc)} ở <code>{html.escape(moc.space)}</code>)."
            f" Số vai hay gặp nhất là <b>{cot.so_vai_pho_bien_nhat()}</b>, ở cột mốc"
            f" là {moc.so_vai_pho_bien_nhat()}. Ngưỡng n-ngôi là 3 vai, nên một tập"
            " không bao giờ xuống dưới 3 cho tỷ lệ 1 bằng 100% <i>theo định"
            " nghĩa</i>."
            if hai_vai == 0
            else f"Hyperedge 2 vai: {_phan_tram(hai_vai)} so với"
            f" {_phan_tram(hai_vai_moc)} ở <code>{html.escape(moc.space)}</code>."
        )
    lech = cot.vai_da_dien_nhieu_nhat(moc)
    if lech is not None:
        vai, a, b = lech
        dong.append(
            f"Vai <code>{html.escape(vai)}</code> được điền ở <b>{_phan_tram(a)}</b>"
            f" số hyperedge, so với {_phan_tram(b)} ở"
            f" <code>{html.escape(moc.space)}</code>."
        )
    lap, lap_moc = cot.phan_entity_lap_vai(), moc.phan_entity_lap_vai()
    if lap is not None and lap_moc is not None:
        dong.append(
            f"Hyperedge có một entity xuất hiện ở hai vai trở lên:"
            f" <b>{_phan_tram(lap)}</b> so với {_phan_tram(lap_moc)} ở"
            f" <code>{html.escape(moc.space)}</code>."
        )
    return dong


def _khoi_bo_trich_xuat_khac(bo: Sequence[BaTyLe]) -> str:
    """Cảnh báo cột `real` trích bằng một bộ trích xuất khác, **kèm bằng chứng**.

    Ngang hạng với cảnh báo lệch trục loại, và cùng lý do: nó đổi cách đọc chính
    con số chứ không phải một ghi chú phương pháp. `synth` và `khao_sat` trích
    bằng DeepSeek với precision ghép cặp đã đo ở story 2.6; `real` chỉ chạy được
    provider cục bộ (AD-12) nên nó trích bằng Qwen 2.5 7B, và precision của
    đường đó chưa đo lần nào.

    Câu "precision chưa đo" một mình là không đủ, và đó là bài học của lần đọc
    04/09: cột `real` ra **100%** ở cả hai tỷ lệ đầu, và một người đọc thấy 100%
    mà không có số đối chiếu sẽ đọc thành một kết quả rất tốt. Nên khối này in
    ba dấu vân tay đo được của bộ trích xuất ngay cạnh con số, và phát biểu
    thẳng kết luận: cột `real` **không** khôi phục được mỏ neo Composition-Risk
    mà story 2.10 mất.
    """
    cot = [b for b in bo if space_goc(b.space) == SPACE_REAL]
    if not cot:
        return ""
    moc = bo[0]
    bang_chung = "".join(f"<li>{d}</li>" for d in dau_van_tay_bo_trich_xuat(cot[0], moc))
    return (
        '<div class="canh-bao"><b>Cột <code>real</code> dùng một bộ trích xuất'
        " khác, và ba tỷ lệ của nó là hiện tượng của bộ trích xuất chứ không phải"
        " của tri thức.</b> Space <code>real</code> chỉ chạy provider cục bộ"
        " (AD-12), nên tài liệu thật được trích bằng <b>Qwen 2.5 7B cục bộ</b>,"
        f" còn <code>synth</code> và <code>khao_sat</code> trích bằng DeepSeek với"
        f" precision ghép cặp <b>{PRECISION_GHEP_CAP:.1%}</b> đã đo ở story 2.6."
        " Precision của đường Qwen <b>chưa đo lần nào</b>: bộ vàng trích xuất của"
        " story 2.5 đo DeepSeek trên corpus dựng, không có bộ vàng nào cho"
        " <code>real</code>."
        f"<br>Ba dấu vân tay đo được từ chính hai ảnh chụp:<ol>{bang_chung}</ol>"
        "<b>Kết luận: cột <code>real</code> không khôi phục được mỏ neo"
        " Composition-Risk mà story 2.10 mất.</b> Nó đo trên tài liệu thật, đúng"
        " thứ PRD muốn, nhưng ba con số của nó nói về chênh lệch giữa hai bộ trích"
        " xuất nhiều hơn nói về hình dạng tri thức doanh nghiệp.</div>"
    )


def dung_html(*bo: BaTyLe, ten_hang: Mapping[int, str]) -> str:
    """Dựng toàn bộ trang từ N kết quả đã tính. Hàm thuần, không I/O.

    Cột đầu là mốc của mọi phép chênh. Chữ ký cũ hai vị trí vẫn gọi được, chỉ
    `ten_hang` chuyển thành tham số từ khóa - nó là bảng tra, không phải một cột.
    """
    hang_theo_ten = {ten: r for r, ten in ten_hang.items()}
    tom_tat = "".join(
        f"<p><b>{html.escape(b.space)}</b> ({b.so_tai_lieu} tài liệu,"
        f" {b.so_hyperedge} hyperedge, chụp {html.escape(b.ngay_do)}):<br>"
        + "<br>".join(html.escape(d) for d in dong_tom_tat(b))
        + "</p>"
        for b in bo
    )
    ten_cot = " · ".join(b.space for b in bo)
    return (
        '<!doctype html>\n<html lang="vi"><head><meta charset="utf-8">'
        f"<title>Ba tỷ lệ n-ngôi: {html.escape(ten_cot)}</title>"
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
        f"{_khoi_bo_trich_xuat_khac(bo)}"
        f"{tom_tat}"
        f"<h2>Ba tỷ lệ, {len(bo)} cột cạnh nhau</h2>"
        f'<p class="chu">Mọi chênh lệch tính so với cột mốc'
        f" <code>{html.escape(bo[0].space)}</code>.</p>"
        f"{_bang_ba_ty_le(*bo)}"
        "<h2>Phân bố mức nhạy cảm theo hạng</h2>"
        f'<p class="chu">Đếm trên hyperedge, không trên tài liệu: hai tài liệu cùng'
        " loại có thể cho số fact rất khác nhau. Hàng tô vàng là vùng nhạy cảm.</p>"
        f"{_bang_phan_bo_hang(bo, ten_hang)}"
        "<h2>Phân bố theo loại nội dung</h2>"
        f"{_khoi_lech_truc_loai(bo, hang_theo_ten)}"
        f"{_bang_phan_bo_loai(bo)}"
        "<h2>Ba số chẩn đoán của Composition-Risk</h2>"
        f'<p class="chu">Không phải tỷ lệ thứ tư và không vào báo cáo như một kết quả.'
        " Chúng chỉ để đọc được một Composition-Risk bằng 0: 0 vì không mảnh nào lộ,"
        " hay 0 vì luôn còn đúng một mảnh không lộ.</p>"
        + "".join(_khoi_chan_doan(b) for b in bo)
        + "</div></body></html>\n"
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
        "--anh-real",
        type=Path,
        default=None,
        dest="anh_real",
        metavar="FILE",
        help="ảnh chụp đồ thị space real - **không có mặc định**, file này nằm"
        " ngoài cây repo (story 2.11); thiếu cờ thì trang in hai cột như cũ",
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

    Bản rút gọn của một space tính là **cùng space** với bản đầy đủ của nó
    (`real_rut_gon` hợp lệ cho cột `real`): hai dạng cho cùng ba con số, chỉ
    khác nhau ở chỗ dạng nào commit được.

    Chặn đúng một ca mà loader không thấy: file hợp lệ nhưng **của space khác**.
    Trỏ nhầm `--anh-khao-sat` vào `synth.json` cho ra một trang hai cột giống hệt
    nhau, ba chênh lệch bằng 0, và một kết luận "khớp cỡ tuyệt đối" - kết quả sai
    nguy hiểm nhất mà story này có thể sinh ra, vì nó trông y hệt một kết quả rất
    tốt. `eval/ct03.py` đã có cùng rào cho `--space`; đây là bản của trang hai cột.

    Hàm thuần để test chấm được hai chiều mà không cần dựng file.
    """
    if space_goc(anh.space) == space:
        return None
    return (
        f"{duong_dan} là ảnh chụp của space {anh.space!r} nhưng đang được dùng cho"
        f" cột {space!r}: mỗi cột phải là một space khác nhau, nếu không trang in"
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
    """In ba tỷ lệ hai hoặc ba space; ảnh chụp thiếu hay lạ thì in lý do ra stderr và trả 1.

    Không có nhánh nào dựng bảng bằng một cột: một trang chỉ có `khao_sat` là
    một trang không trả lời câu hỏi khớp cỡ, và in nó ra rồi thoát 0 là để người
    đọc tưởng bước đối chiếu đã chạy. Cột `real` là **tùy chọn** vì ảnh chụp của
    nó không nằm trong repo; thiếu cờ thì trang in đúng hai cột như story 2.10.
    """
    ts = _tham_so(sys.argv[1:] if argv is None else list(argv))
    try:
        hang = dict(tai_hang_do_nhay(ts.hang).hang)
        anh = [_doc(ts.anh_synth, "synth"), _doc(ts.anh_khao_sat, "khao_sat")]
        if ts.anh_real is not None:
            anh.append(_doc(ts.anh_real, SPACE_REAL))
        bo = tuple(ba_ty_le(a, hang) for a in anh)
    except (AnhDoThiKhongHopLe, HangKhongXacDinh, SensitivityRanksInvalid) as loi:
        print(str(loi), file=sys.stderr)
        return 1

    trai = bo[0]
    ten_hang = {v: k for k, v in hang.items()}
    dich = Path(ts.dich) if ts.dich is not None else DUONG_DAN_HTML
    try:
        dich.parent.mkdir(parents=True, exist_ok=True)
        dich.write_text(dung_html(*bo, ten_hang=ten_hang), encoding="utf-8")
    except OSError as loi:
        print(f"không ghi được {dich}: {loi}", file=sys.stderr)
        return 1

    for b in bo:
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
    for d in doi_chieu(*bo):
        for i, b in enumerate(bo[1:], start=1):
            gia_tri = d.chenh_voi_moc(i)
            chenh = "không so được" if gia_tri is None else f"{gia_tri:+.1%}"
            print(f"chênh {d.ten}: {chenh} ({trai.space} -> {b.space})")
    chung = loai_chung(*bo)
    rieng = [(b.space, sorted(_loai_cua(b) - chung)) for b in bo]
    if any(ds for _, ds in rieng):
        print(
            "cảnh báo: các cột không cùng trục loại nội dung - "
            + "; ".join(f"chỉ {ten} có {ds}" for ten, ds in rieng if ds)
        )
    print(
        "ba tỷ lệ tính trên tập fact hệ trích được (precision ghép cặp"
        f" {PRECISION_GHEP_CAP:.1%} của vòng {VONG_CHOT_2_6}), mẫu số khao_sat là"
        " bản ghi giả lập"
    )
    for b in bo:
        if space_goc(b.space) != SPACE_REAL:
            continue
        print(
            f"cảnh báo: cột {b.space} trích bằng Qwen 2.5 7B cục bộ (AD-12),"
            " precision chưa đo lần nào - ba tỷ lệ của nó là hiện tượng của bộ"
            " trích xuất, không phải của tri thức:"
        )
        for d in dau_van_tay_bo_trich_xuat(b, trai):
            print("  - " + _bo_the(d))
        print(
            f"  => cột {b.space} KHÔNG khôi phục được mỏ neo Composition-Risk mà"
            " story 2.10 mất"
        )
    print(f"ghi {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
