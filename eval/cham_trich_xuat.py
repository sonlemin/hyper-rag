"""Phép chấm trích xuất: hai chỉ số, ma trận lẫn lộn A13, verdict R2 (story 2.6).

Bộ vàng 2.5 cho mẫu số (151 slot đã điền trên 8 tài liệu chấm); module này là
phép chấm đọc mẫu số đó. Hàm thuần: không chạm kho, không gọi LLM, không đọc
môi trường - runner tốn tiền sống ở `eval/do_trich_xuat.py`. Nhờ vậy đổi luật
chấm là chạy lại phép tính trên fact thô đã lưu, không phải trả tiền lại cho
cùng một câu trả lời của LLM.

**Hai chỉ số, đo cạnh nhau, hỏi hai câu khác nhau.**

- *Ghép cặp* (`cham_tai_lieu`): ghép fact pipeline với fact vàng một-một, neo ở
  `subject`, rồi chấm từng vai bên trong cặp. Nó hỏi "hệ có dựng lại đúng ranh
  giới từng fact không". Đây là cổng R2 chính thức.
- *Mức tài liệu* (`cham_muc_tai_lieu`): mù độ hạt. Một slot vàng tính đúng khi
  giá trị của nó xuất hiện ở **đúng vai** tại bất kỳ fact nào của cùng tài
  liệu. Nó hỏi "hệ có dán đúng 8 vai không", đúng câu hỏi của R2 và của A13.

Chênh giữa hai chỉ số chính là phần LLM gom fact khác nhãn tay - và đó là lý do
**ma trận lẫn lộn A13 dựng từ chỉ số mức tài liệu**. Ma trận của chỉ số ghép
cặp chỉ nhìn được bên trong một cặp đã ghép: nó cấu trúc-tính không thấy được
lẫn vai xuyên fact, và dồn trọn slot của mọi fact không ghép được vào cột
"thiếu", tức trộn bỏ sót thật với gom fact khác nhãn tay. Đọc ma trận đó rồi
kết luận "hệ bỏ sót" là kết luận ngược chiều với dữ liệu (vòng review 1).

**Ba luật chung cho cả hai chỉ số.**

- **Khớp lỏng là số chính.** Nhãn vàng là đoạn có thật trong thân tài liệu
  (luật nạp 2.5) và prompt cũng dạy LLM "trích sát văn bản", nên hai bên là hai
  đoạn của cùng một câu; quan hệ tự nhiên giữa chúng là chuỗi con, không phải
  bằng nhau. Khớp chặt vẫn đếm riêng để thấy độ trôi câu chữ.
- **Mỗi giá trị pred tiêu thụ đúng một lần trong phạm vi phép so của nó** (một
  cặp với chỉ số ghép cặp, một tài liệu với chỉ số mức tài liệu). Không có luật
  này thì một giá trị dài nuốt cả câu ăn *điểm* ở nhiều vai vàng cùng lúc, và
  precision vượt quá 1. Luật áp cho phần tính điểm; phần *quy lỗi* của chỉ số
  mức tài liệu thì không tiêu thụ (xem `cham_muc_tai_lieu`).
- **Đúng vai thắng trước mọi mức khớp.** Bốn lượt ghép: (đúng vai, chặt),
  (đúng vai, lỏng), (lẫn vai, chặt), (lẫn vai, lỏng). Một giá trị khớp chặt ở
  vai sai không được ăn trước một giá trị khớp lỏng ở vai đúng - thế là biến
  một TP thành FN cộng FP, tức phép chấm tự tạo ra một ca lẫn vai không có.

**TP đòi đúng vai.** Đúng chữ mà sai vai không phải là điểm: nó là một ô ngoài
đường chéo của ma trận, tính FN cho vai vàng và FP cho vai pred. Toàn bộ giá
trị của story này nằm ở chỗ phân biệt được hai loại lỗi đó.

Ma trận lẫn lộn là bảng (8 vai + hàng `thừa`) × (8 vai + cột `thiếu`). Đường
chéo là TP; ô `(v, w)` là lẫn vai; ô `(v, thiếu)` là *vắng hẳn* (giá trị vàng
không xuất hiện ở đâu trong tài liệu); ô `(thừa, w)` là giá trị pred không khớp
nhãn nào. Bất biến sổ sách: tổng hàng `v` luôn bằng số slot vàng của vai `v`
(không slot vàng nào rơi ra ngoài ma trận). Tổng cột bằng số slot pred của vai
đó ở chỉ số ghép cặp, và *lớn hơn hoặc bằng* ở chỉ số mức tài liệu - vì lượt
quy lỗi của chỉ số đó cố ý không tiêu thụ, để một giá trị nuốt cả câu bị nhiều
slot vàng cùng chỉ mặt.

Ngưỡng R2 và hàm verdict sống ở đây cùng phép chấm, không nằm trong module dựng
HTML: một ngưỡng đặt trong lớp trình bày là một ngưỡng không có test.

Chỉ import `core/` và `eval.bo_vang` (dùng lại `chuan_so_sanh`), không `api`.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from core.facts import VAI_BAT_BUOC, id_fact
from core.slots import SLOT_ROLE_SET, SLOT_ROLES
from eval.bo_vang import BoVang, chuan_so_sanh

# Hai nhãn ngoài danh mục 8 vai, dùng làm hàng/cột biên của ma trận. Tiếng Việt
# vì chúng chỉ xuất hiện trong báo cáo cho người đọc, không phải khóa dữ liệu.
VAI_THIEU: str = "thiếu"
VAI_THUA: str = "thừa"

HANG_MA_TRAN: tuple[str, ...] = SLOT_ROLES + (VAI_THUA,)
COT_MA_TRAN: tuple[str, ...] = SLOT_ROLES + (VAI_THIEU,)

# Hai kiểu khớp giá trị.
KHOP_CHAT: str = "chat"
KHOP_LONG: str = "long"

# Tên hai chỉ số, dùng làm nhãn cột trong báo cáo.
CHI_SO_GHEP_CAP: str = "ghép cặp"
CHI_SO_MUC_TAI_LIEU: str = "mức tài liệu"

# Vai bị loại khỏi mẫu số phụ: `subject` bắt buộc theo lược đồ nên mọi fact
# ghép được đều ăn điểm ở đó (28,5% mẫu số), tức nó không phân biệt được prompt
# tốt với prompt tồi. Mẫu số phụ là phép đo trên 7 vai còn lại.
VAI_BO_KHOI_MAU_SO_PHU: str = "subject"

# --- Cổng R2 -----------------------------------------------------------------

# Ngưỡng kích hoạt đường lùi R2 (PRD mục 6.1): precision dưới 60% ở T2 thì bậc 1
# là chuyển GPT-4o toàn phần cộng tăng few-shot.
NGUONG_R2: float = 0.60

# Cổng chính thức: precision của chỉ số *ghép cặp* trên *mẫu số tổng*. Đơn vị
# của PRD là "slot đã điền" và `subject` là một slot đã điền, nên mẫu số tổng là
# cách đọc đúng câu chữ của PRD. Ba cột còn lại vẫn in verdict để thấy ngay
# quyết định có đổi theo cột không - biên hiện chỉ vài điểm.
CONG_R2_CHI_SO: str = CHI_SO_GHEP_CAP
CONG_R2_MAU_SO: str = "mẫu số tổng"

VERDICT_DAT: str = "ĐẠT"
VERDICT_DUOI: str = "DƯỚI"
VERDICT_KHONG_CHAM_DUOC: str = "KHÔNG CHẤM ĐƯỢC"


def verdict_r2(precision: float | None, nguong: float = NGUONG_R2) -> str:
    """`ĐẠT` khi precision >= ngưỡng, `DƯỚI` khi nhỏ hơn, `KHÔNG CHẤM ĐƯỢC` khi `None`.

    Đúng bằng ngưỡng là **đạt**: PRD viết "dưới 60% thì kích hoạt", nên 60,0%
    không kích hoạt. `None` (vòng không có slot pred nào) không phải là "dưới
    ngưỡng" - không có phép chia nào xảy ra, nên in nó thành `DƯỚI` là dựng ra
    một kết quả R2 chưa từng đo được.
    """
    if precision is None:
        return VERDICT_KHONG_CHAM_DUOC
    return VERDICT_DAT if precision >= nguong else VERDICT_DUOI


def _slots(fact) -> dict[str, str]:
    """Nhận cả `FactVang` lẫn dict slot trần, kiểm cùng luật với `core.facts.kiem_fact`.

    Cả hai phía của phép chấm đều là fact *đã hợp lệ*: nhãn vàng qua cửa nạp của
    `eval/bo_vang.py`, fact pipeline qua `kiem_fact`. Nên một fact thiếu
    `subject`, mang vai lạ hay có giá trị rỗng tới được đây nghĩa là nơi gọi bỏ
    qua một cửa - và nếu lặng lẽ chấm nó thì nó thành FN hoặc FP, tức một con số
    sai mà không ai truy ra nguyên nhân.
    """
    ra = dict(getattr(fact, "slots", fact))
    la = sorted(set(ra) - SLOT_ROLE_SET)
    if la:
        raise ValueError(
            f"fact mang vai ngoài danh mục `core.slots.SLOT_ROLES`: {la}."
            " Fact hợp lệ đi qua `core.facts.kiem_fact` không bao giờ có vai lạ;"
            " một vai lạ tới đây là dấu hiệu nơi gọi bỏ qua bước kiểm"
        )
    for vai, gia_tri in ra.items():
        if not isinstance(gia_tri, str):
            raise TypeError(
                f"giá trị của vai {vai!r} phải là chuỗi, nhận được {type(gia_tri).__name__}"
            )
        if not chuan_so_sanh(gia_tri):
            raise ValueError(f"vai {vai!r} mang giá trị rỗng: {gia_tri!r}")
    if VAI_BAT_BUOC not in ra:
        raise ValueError(
            f"fact thiếu vai bắt buộc {VAI_BAT_BUOC!r} (luật của `core.facts.kiem_fact`);"
            f" nhận được {sorted(ra)}"
        )
    return ra


def khop_gia_tri(a: str, b: str) -> str | None:
    """`KHOP_CHAT`, `KHOP_LONG` hay `None`, so trên dạng `chuan_so_sanh`.

    Dùng đúng phép chuẩn hóa mà bộ vàng dùng để canh nhãn với thân tài liệu
    (NFC, gộp khoảng trắng, casefold): hai bên phải được so bằng cùng một
    thước, không thì phép chấm đo cả sự khác nhau giữa hai phép chuẩn hóa.
    """
    x, y = chuan_so_sanh(a), chuan_so_sanh(b)
    if not x or not y:
        return None
    if x == y:
        return KHOP_CHAT
    if x in y or y in x:
        return KHOP_LONG
    return None


# ---------------------------------------------------------------------------
# Đơn vị chấm: một slot đã điền
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotDo:
    """Một slot đã điền, kèm fact nó thuộc về - đơn vị chấm của cả hai chỉ số.

    `id_fact` và `stt` chỉ để sắp thứ tự tất định: hai lần chạy trên cùng dữ
    liệu phải cho cùng một tập ghép, không phụ thuộc thứ tự LLM trả fact.
    """

    vai: str
    gia_tri: str
    id_fact: str
    stt: int


def _slot_cua(danh_sach: Sequence[Mapping[str, str]]) -> list[SlotDo]:
    ra: list[SlotDo] = []
    for stt, slots in enumerate(danh_sach):
        idf = id_fact(slots)
        for vai in SLOT_ROLES:
            if vai in slots:
                ra.append(SlotDo(vai=vai, gia_tri=slots[vai], id_fact=idf, stt=stt))
    return ra


def _thu_tu(s: SlotDo) -> tuple:
    return (SLOT_ROLES.index(s.vai), s.id_fact, s.stt, s.gia_tri)


def _ghep_slot(
    vang: Sequence[SlotDo], pred: Sequence[SlotDo], chi_dung_vai: bool = False
) -> tuple[list[tuple[int, int, str]], list[int], list[int]]:
    """Ghép slot vàng với slot pred; trả (cặp đã ghép, vàng còn lại, pred còn lại).

    Bốn lượt theo đúng luật của spec: (đúng vai, chặt), (đúng vai, lỏng),
    (lẫn vai, chặt), (lẫn vai, lỏng). Mỗi slot pred tiêu thụ đúng một lần.
    Đây là *nơi duy nhất* cài luật ghép, dùng chung cho cả hai chỉ số: hai bản
    cài đặt là hai chỗ để chúng lệch nhau.

    `chi_dung_vai=True` chạy đúng hai lượt đầu - chỉ số mức tài liệu dùng nó,
    vì ở đó phần lẫn vai không tiêu thụ (xem `cham_muc_tai_lieu`).
    """
    con_lai = set(range(len(pred)))
    da_ghep: set[int] = set()
    tt_vang = sorted(range(len(vang)), key=lambda i: _thu_tu(vang[i]))
    tt_pred = sorted(range(len(pred)), key=lambda j: _thu_tu(pred[j]))
    ghep: list[tuple[int, int, str]] = []
    for dung_vai in ((True,) if chi_dung_vai else (True, False)):
        for kieu in (KHOP_CHAT, KHOP_LONG):
            for i in tt_vang:
                if i in da_ghep:
                    continue
                for j in tt_pred:
                    if j not in con_lai:
                        continue
                    if dung_vai != (pred[j].vai == vang[i].vai):
                        continue
                    if khop_gia_tri(vang[i].gia_tri, pred[j].gia_tri) != kieu:
                        continue
                    ghep.append((i, j, kieu))
                    da_ghep.add(i)
                    con_lai.discard(j)
                    break
    ghep.sort()
    return (
        ghep,
        [i for i in range(len(vang)) if i not in da_ghep],
        [j for j in range(len(pred)) if j in con_lai],
    )


# ---------------------------------------------------------------------------
# Chỉ số và sổ đếm
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChiSo:
    """Precision/recall/F1 ở hai mức khớp, trên một mẫu số slot đã điền.

    `so_vang` là mẫu số của recall (slot vàng), `so_pred` là mẫu số của
    precision (slot pipeline trả). `chat`/`long` là số slot TP theo hai mức.
    Mẫu số bằng 0 thì chỉ số là `None` chứ không phải 0: "không có gì để chấm"
    khác "chấm được và bằng 0", và báo cáo in `-` cho ca đầu.
    """

    so_vang: int = 0
    so_pred: int = 0
    chat: int = 0
    long: int = 0

    @property
    def tp(self) -> int:
        return self.chat + self.long

    @property
    def fn(self) -> int:
        return self.so_vang - self.tp

    @property
    def fp(self) -> int:
        return self.so_pred - self.tp

    @property
    def precision(self) -> float | None:
        return self.tp / self.so_pred if self.so_pred else None

    @property
    def recall(self) -> float | None:
        return self.tp / self.so_vang if self.so_vang else None

    @property
    def precision_chat(self) -> float | None:
        return self.chat / self.so_pred if self.so_pred else None

    @property
    def recall_chat(self) -> float | None:
        return self.chat / self.so_vang if self.so_vang else None

    @property
    def f1(self) -> float | None:
        return _f1(self.precision, self.recall)

    def __add__(self, khac: "ChiSo") -> "ChiSo":
        return ChiSo(
            so_vang=self.so_vang + khac.so_vang,
            so_pred=self.so_pred + khac.so_pred,
            chat=self.chat + khac.chat,
            long=self.long + khac.long,
        )


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or (p + r) == 0:
        return None
    return 2 * p * r / (p + r)


@dataclass(frozen=True)
class KetQuaCham:
    """Sổ đếm của phép chấm, cộng được để gộp nhiều tài liệu hay nhiều vòng.

    Giữ đếm thô (theo vai, theo ô ma trận) chứ không giữ tỉ lệ: tỉ lệ của một
    tập gộp không phải trung bình các tỉ lệ thành phần, và cộng hai `KetQuaCham`
    phải cho đúng con số như chấm một lượt trên hợp hai tập.
    """

    vang_theo_vai: Mapping[str, int] = field(default_factory=dict)
    pred_theo_vai: Mapping[str, int] = field(default_factory=dict)
    chat_theo_vai: Mapping[str, int] = field(default_factory=dict)
    long_theo_vai: Mapping[str, int] = field(default_factory=dict)
    o_ma_tran: Mapping[tuple[str, str], int] = field(default_factory=dict)
    so_fact_vang: int = 0
    so_fact_pred: int = 0
    so_cap: int = 0
    so_fact_vang_khong_ghep: int = 0
    so_fact_pred_khong_ghep: int = 0
    # Ba loại slot vàng cùng rơi vào cột `thiếu` của ma trận nhưng nói ba
    # chuyện khác nhau; chỉ số ghép cặp không phân loại được (mọi slot của một
    # fact không ghép đều vào đó) nên nó để `None`, và báo cáo in `-`.
    #   - `so_vang_han`: giá trị không xuất hiện ở bất kỳ giá trị pred nào -
    #     **bỏ sót thật**, con số mang kết luận của chương 4;
    #   - `so_trung_nhan`: nhãn tay lặp đúng cùng (vai, giá trị) nhiều lần hơn
    #     số lần pipeline trả nó;
    #   - `so_ung_vien_da_dung`: giá trị *khác* của cùng vai đã tiêu thụ mất
    #     slot pred duy nhất khớp được (nhãn "dọn log" và "dọn log cũ" cùng
    #     tranh một `remediation`).
    so_vang_han: int | None = None
    so_trung_nhan: int | None = None
    so_ung_vien_da_dung: int | None = None

    def __post_init__(self):
        for ten in ("vang_theo_vai", "pred_theo_vai", "chat_theo_vai", "long_theo_vai"):
            day_du = {vai: int(getattr(self, ten).get(vai, 0)) for vai in SLOT_ROLES}
            object.__setattr__(self, ten, MappingProxyType(day_du))
        object.__setattr__(self, "o_ma_tran", MappingProxyType(dict(self.o_ma_tran)))

    @property
    def chi_so(self) -> ChiSo:
        return ChiSo(
            so_vang=sum(self.vang_theo_vai.values()),
            so_pred=sum(self.pred_theo_vai.values()),
            chat=sum(self.chat_theo_vai.values()),
            long=sum(self.long_theo_vai.values()),
        )

    @property
    def so_lan_vai(self) -> int:
        """Số slot vàng khớp chữ nhưng lệch vai - phần lỗi *dán sai vai*."""
        return sum(
            n for (h, c), n in self.o_ma_tran.items() if h != c and h in SLOT_ROLE_SET and c in SLOT_ROLE_SET
        )

    @property
    def so_o_thieu(self) -> int:
        """Tổng cột `thiếu` của ma trận - **không** phải "bỏ sót thật".

        Với chỉ số mức tài liệu, cột này gộp ba loại mà `so_vang_han`,
        `so_trung_nhan` và `so_ung_vien_da_dung` tách ra; với chỉ số ghép cặp nó
        còn gộp cả trọn bộ slot của mọi fact vàng không ghép được. In con số này
        dưới đầu cột "vắng hẳn" là đặt hai nghĩa dưới một nhãn.
        """
        return sum(n for (h, c), n in self.o_ma_tran.items() if c == VAI_THIEU)

    def __add__(self, khac: "KetQuaCham") -> "KetQuaCham":
        o = dict(self.o_ma_tran)
        for k, n in khac.o_ma_tran.items():
            o[k] = o.get(k, 0) + n

        def cong(a: int | None, b: int | None) -> int | None:
            # `None` là "chỉ số này không phân loại được", và nó lan: cộng một
            # sổ có phân loại với một sổ không có thì tổng cũng không có.
            return None if a is None or b is None else a + b

        return KetQuaCham(
            vang_theo_vai=_cong_vai(self.vang_theo_vai, khac.vang_theo_vai),
            pred_theo_vai=_cong_vai(self.pred_theo_vai, khac.pred_theo_vai),
            chat_theo_vai=_cong_vai(self.chat_theo_vai, khac.chat_theo_vai),
            long_theo_vai=_cong_vai(self.long_theo_vai, khac.long_theo_vai),
            o_ma_tran=o,
            so_fact_vang=self.so_fact_vang + khac.so_fact_vang,
            so_fact_pred=self.so_fact_pred + khac.so_fact_pred,
            so_cap=self.so_cap + khac.so_cap,
            so_fact_vang_khong_ghep=self.so_fact_vang_khong_ghep + khac.so_fact_vang_khong_ghep,
            so_fact_pred_khong_ghep=self.so_fact_pred_khong_ghep + khac.so_fact_pred_khong_ghep,
            so_vang_han=cong(self.so_vang_han, khac.so_vang_han),
            so_trung_nhan=cong(self.so_trung_nhan, khac.so_trung_nhan),
            so_ung_vien_da_dung=cong(self.so_ung_vien_da_dung, khac.so_ung_vien_da_dung),
        )


def _cong_vai(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, int]:
    return {vai: a.get(vai, 0) + b.get(vai, 0) for vai in SLOT_ROLES}


class _So:
    """Bộ đếm dựng dần một `KetQuaCham` (đếm theo vai và theo ô ma trận)."""

    def __init__(self):
        self.vang = {vai: 0 for vai in SLOT_ROLES}
        self.pred = {vai: 0 for vai in SLOT_ROLES}
        self.chat = {vai: 0 for vai in SLOT_ROLES}
        self.long = {vai: 0 for vai in SLOT_ROLES}
        self.o: dict[tuple[str, str], int] = {}

    def cong_o(self, hang: str, cot: str) -> None:
        self.o[(hang, cot)] = self.o.get((hang, cot), 0) + 1

    def khop(self, vai_vang: str, vai_pred: str, kieu: str) -> None:
        if vai_vang == vai_pred:
            (self.chat if kieu == KHOP_CHAT else self.long)[vai_vang] += 1
        self.cong_o(vai_vang, vai_pred)

    def ket_qua(self, **them) -> KetQuaCham:
        return KetQuaCham(
            vang_theo_vai=self.vang,
            pred_theo_vai=self.pred,
            chat_theo_vai=self.chat,
            long_theo_vai=self.long,
            o_ma_tran=self.o,
            **them,
        )


# ---------------------------------------------------------------------------
# Chỉ số 1: ghép cặp (cổng R2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapDaGhep:
    """Một cặp (fact vàng, fact pipeline) đã ghép và kết quả chấm trong cặp.

    `khop` là vai vàng khớp *đúng vai* kèm kiểu khớp; `lan_vai` là các cặp
    (vai vàng, vai pred) khớp chữ mà lệch vai; `thieu` là vai vàng không tìm
    thấy giá trị nào; `thua` là vai pred không khớp giá trị vàng nào.
    """

    id_vang: str
    id_pred: str
    vang: Mapping[str, str]
    pred: Mapping[str, str]
    khop: Mapping[str, str]
    lan_vai: tuple[tuple[str, str], ...]
    thieu: tuple[str, ...]
    thua: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "vang", MappingProxyType(dict(self.vang)))
        object.__setattr__(self, "pred", MappingProxyType(dict(self.pred)))
        object.__setattr__(self, "khop", MappingProxyType(dict(self.khop)))


@dataclass(frozen=True)
class ChamTaiLieu:
    """Kết quả chỉ số *ghép cặp* cho một tài liệu."""

    doc_key: str
    cap: tuple[CapDaGhep, ...]
    vang_khong_ghep: tuple[Mapping[str, str], ...]
    pred_khong_ghep: tuple[Mapping[str, str], ...]
    ket_qua: KetQuaCham


def _cham_cap(vang: Mapping[str, str], pred: Mapping[str, str]):
    """Ghép từng giá trị trong một cặp; trả (khop, lan_vai, thieu, thua)."""
    sv, sp = _slot_cua([vang]), _slot_cua([pred])
    ghep, con_vang, con_pred = _ghep_slot(sv, sp)
    khop: dict[str, str] = {}
    lan: list[tuple[str, str]] = []
    for i, j, kieu in ghep:
        if sv[i].vai == sp[j].vai:
            khop[sv[i].vai] = kieu
        else:
            lan.append((sv[i].vai, sp[j].vai))
    thieu = tuple(sv[i].vai for i in con_vang)
    thua = tuple(sp[j].vai for j in con_pred)
    return khop, tuple(sorted(lan, key=lambda x: (SLOT_ROLES.index(x[0]), SLOT_ROLES.index(x[1])))), thieu, thua


def _diem_chong_lap(vang: Mapping[str, str], pred: Mapping[str, str]) -> tuple[int, int]:
    """Điểm chồng lấn của một cặp ứng viên: (số slot đúng vai, số slot khớp bất kỳ).

    Số slot đúng vai đứng trước vì đó chính là thứ phép chấm đo; số khớp bất kỳ
    phá hòa giữa hai fact pipeline cùng số vai đúng nhưng khác lượng nội dung
    trùng. Hòa cả hai thì trọng tài là `id_fact` nhỏ hơn (tất định, không phụ
    thuộc thứ tự LLM trả).
    """
    khop, lan, _, _ = _cham_cap(vang, pred)
    return len(khop), len(khop) + len(lan)


def cham_tai_lieu(vang: Iterable, pred: Iterable, doc_key: str = "") -> ChamTaiLieu:
    """Chỉ số *ghép cặp* cho một tài liệu: ghép một-một theo `subject` rồi chấm từng cặp.

    `vang` nhận `FactVang` hoặc dict slot; `pred` là fact hợp lệ mà pipeline
    trả (đã qua `core.facts.kiem_fact`). Ứng viên của một cặp là hai fact có
    `subject` khớp nhau theo `khop_gia_tri` - dùng đúng luật khớp của giá trị,
    vì `subject` cũng là một đoạn trích và cũng trôi câu chữ như mọi vai khác.
    Chọn cặp theo điểm chồng lấn giảm dần, mỗi fact chỉ vào một cặp.
    """
    ds_vang = [_slots(f) for f in vang]
    ds_pred = [_slots(f) for f in pred]
    id_vang = [id_fact(s) for s in ds_vang]
    id_pred = [id_fact(s) for s in ds_pred]

    ung_vien = []
    for i, v in enumerate(ds_vang):
        for j, p in enumerate(ds_pred):
            if khop_gia_tri(v.get("subject", ""), p.get("subject", "")) is None:
                continue
            diem = _diem_chong_lap(v, p)
            ung_vien.append((-diem[0], -diem[1], id_pred[j], id_vang[i], i, j))
    ung_vien.sort()

    da_vang: set[int] = set()
    da_pred: set[int] = set()
    cap: list[CapDaGhep] = []
    for _, _, _, _, i, j in ung_vien:
        if i in da_vang or j in da_pred:
            continue
        da_vang.add(i)
        da_pred.add(j)
        khop, lan, thieu, thua = _cham_cap(ds_vang[i], ds_pred[j])
        cap.append(
            CapDaGhep(
                id_vang=id_vang[i],
                id_pred=id_pred[j],
                vang=ds_vang[i],
                pred=ds_pred[j],
                khop=khop,
                lan_vai=lan,
                thieu=thieu,
                thua=thua,
            )
        )
    cap.sort(key=lambda c: (c.id_vang, c.id_pred))

    vang_le = tuple(MappingProxyType(s) for i, s in enumerate(ds_vang) if i not in da_vang)
    pred_le = tuple(MappingProxyType(s) for j, s in enumerate(ds_pred) if j not in da_pred)
    return ChamTaiLieu(
        doc_key=doc_key,
        cap=tuple(cap),
        vang_khong_ghep=vang_le,
        pred_khong_ghep=pred_le,
        ket_qua=_so_dem_cap(cap, vang_le, pred_le),
    )


def _so_dem_cap(
    cap: Sequence[CapDaGhep],
    vang_le: Sequence[Mapping[str, str]],
    pred_le: Sequence[Mapping[str, str]],
) -> KetQuaCham:
    """Gom mọi slot của một tài liệu vào sổ đếm, kể cả slot của fact không ghép."""
    so = _So()
    for c in cap:
        for vai in c.vang:
            so.vang[vai] += 1
        for vai in c.pred:
            so.pred[vai] += 1
        for vai, kieu in c.khop.items():
            so.khop(vai, vai, kieu)
        for v, w in c.lan_vai:
            so.cong_o(v, w)
        for vai in c.thieu:
            so.cong_o(vai, VAI_THIEU)
        for vai in c.thua:
            so.cong_o(VAI_THUA, vai)
    # Fact không ghép: mọi slot vàng là FN, mọi slot pred là FP. Chúng vào đúng
    # hai ô biên, nên bất biến tổng hàng / tổng cột vẫn đúng. Đây cũng chính là
    # chỗ chỉ số ghép cặp trộn "bỏ sót thật" với "gom fact khác nhãn tay" - lý
    # do ma trận A13 phải đọc từ chỉ số mức tài liệu.
    for s in vang_le:
        for vai in s:
            so.vang[vai] += 1
            so.cong_o(vai, VAI_THIEU)
    for s in pred_le:
        for vai in s:
            so.pred[vai] += 1
            so.cong_o(VAI_THUA, vai)
    return so.ket_qua(
        so_fact_vang=len(cap) + len(vang_le),
        so_fact_pred=len(cap) + len(pred_le),
        so_cap=len(cap),
        so_fact_vang_khong_ghep=len(vang_le),
        so_fact_pred_khong_ghep=len(pred_le),
    )


# ---------------------------------------------------------------------------
# Chỉ số 2: mức tài liệu (nguồn của ma trận A13)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KhopMucTaiLieu:
    """Một slot vàng đã tìm được giá trị của nó trong đầu ra của tài liệu.

    `dung_vai` phân biệt hai loại hoàn toàn khác nhau: đúng vai là TP, lệch vai
    là một ô lẫn lộn của ma trận A13 (FN cho vai vàng, và vai pred đó là một hố
    nuốt).
    """

    vai_vang: str
    vai_pred: str
    gia_tri_vang: str
    gia_tri_pred: str
    kieu: str

    @property
    def dung_vai(self) -> bool:
        return self.vai_vang == self.vai_pred


@dataclass(frozen=True)
class ChamMucTaiLieu:
    """Kết quả chỉ số *mức tài liệu* cho một tài liệu, tách bốn loại kết cục.

    `khop` chỉ gồm ca **đúng vai** (TP); `lan_vai` là slot vàng tìm thấy giá trị
    của mình nhưng ở vai khác. Ba tuple còn lại là ba nghĩa khác nhau của cùng
    một cột `thiếu`, và trộn chúng là trộn kết luận của chương 4:

    - `vang_han`: giá trị không xuất hiện ở bất kỳ giá trị pred nào - **bỏ sót
      thật**;
    - `trung_nhan`: nhãn tay lặp *đúng cùng* (vai, giá trị) nhiều lần hơn số lần
      pipeline trả nó;
    - `ung_vien_da_dung`: một giá trị vàng *khác* của cùng vai đã tiêu thụ mất
      slot pred duy nhất khớp được (nhãn "dọn log" và "dọn log cũ" cùng tranh
      một `remediation` dài).

    `pred_thua` là slot pred không khớp nhãn nào - **không** kể slot đã bị quy
    vào một ô lẫn vai: một giá trị dán sai vai đã có chỗ của nó trong ma trận,
    đếm tiếp vào hàng `thừa` là cùng một giá trị hiện hai lần.
    """

    doc_key: str
    khop: tuple[KhopMucTaiLieu, ...]
    lan_vai: tuple[KhopMucTaiLieu, ...]
    vang_han: tuple[tuple[str, str], ...]
    trung_nhan: tuple[tuple[str, str], ...]
    ung_vien_da_dung: tuple[tuple[str, str], ...]
    pred_thua: tuple[tuple[str, str], ...]
    ket_qua: KetQuaCham


def cham_muc_tai_lieu(vang: Iterable, pred: Iterable, doc_key: str = "") -> ChamMucTaiLieu:
    """Chỉ số *mức tài liệu*: giá trị vàng tính đúng nếu đúng vai ở bất kỳ fact nào.

    Mù độ hạt fact một cách cố ý. LLM gom nhiều câu vào ít fact hơn nhãn tay là
    hiện tượng đã biết từ 2.4; chỉ số ghép cặp phạt chuyện đó hai lần (fact
    không ghép được thì cả bó slot của nó vào FN) trong khi câu hỏi của R2 và
    của A13 là "vai có được dán đúng không".

    Hai lượt, và ranh giới giữa chúng là chỗ dễ sai nhất của cả story:

    1. **Lượt tính điểm, có tiêu thụ, chỉ đúng vai** (chặt trước lỏng sau). Mỗi
       slot pred ăn điểm nhiều nhất một lần, nên precision không bao giờ vượt 1
       và một nhãn vàng lặp ba lần không lấy được ba điểm từ một slot pred.
    2. **Lượt quy lỗi, không tiêu thụ.** Slot vàng còn lại đi tìm giá trị của
       mình trong *mọi* giá trị pred của tài liệu, kể cả giá trị đã ăn điểm ở
       lượt 1. Tìm thấy ở vai khác thì đó là **lẫn vai xuyên fact**, ô `(v, w)`
       của ma trận A13. Không tiêu thụ ở lượt này là cố ý: một `remediation`
       nuốt cả câu phải bị *nhiều* slot vàng cùng chỉ mặt, vì đó chính là dấu
       hiệu "hố nuốt" mà A13 cần thấy. Cái giá là tổng cột của ma trận có thể
       lớn hơn số slot pred của vai đó; tổng hàng thì vẫn khít.

    Cột "thiếu" của ma trận vì thế gộp ba loại, và chúng được đếm riêng:
    `vang_han` (không thấy ở đâu - **bỏ sót thật**), `trung_nhan` (nhãn tay lặp
    cùng một giá trị nhiều hơn số lần pipeline trả nó) và `ung_vien_da_dung`
    (một nhãn khác cùng vai đã tiêu thụ mất slot pred duy nhất khớp được). Hai
    loại sau không được ghi vào đường chéo - cộng điểm hai lần cho một slot pred
    làm precision vượt 1 - nhưng đọc chúng thành bỏ sót cũng sai: giá trị *có*
    trong đầu ra.
    """
    sv = _slot_cua([_slots(f) for f in vang])
    sp = _slot_cua([_slots(f) for f in pred])
    ghep, con_vang, con_pred = _ghep_slot(sv, sp, chi_dung_vai=True)

    so = _So()
    for s in sv:
        so.vang[s.vai] += 1
    for s in sp:
        so.pred[s.vai] += 1

    khop = tuple(
        KhopMucTaiLieu(
            vai_vang=sv[i].vai,
            vai_pred=sp[j].vai,
            gia_tri_vang=sv[i].gia_tri,
            gia_tri_pred=sp[j].gia_tri,
            kieu=kieu,
        )
        for i, j, kieu in ghep
    )
    for k in khop:
        so.khop(k.vai_vang, k.vai_pred, k.kieu)

    tt_pred = sorted(range(len(sp)), key=lambda j: _thu_tu(sp[j]))
    lan: list[KhopMucTaiLieu] = []
    vang_han: list[tuple[str, str]] = []
    trung: list[tuple[str, str]] = []
    da_quy_loi: set[int] = set()
    ung_vien_da_dung: list[tuple[str, str]] = []
    for i in con_vang:
        ung_vien = [(j, khop_gia_tri(sv[i].gia_tri, sp[j].gia_tri)) for j in tt_pred]
        khac_vai = [(j, k) for j, k in ung_vien if k is not None and sp[j].vai != sv[i].vai]
        if khac_vai:
            # Chặt trước lỏng sau, rồi thứ tự vai - cùng luật với lượt 1.
            khac_vai.sort(key=lambda x: (x[1] != KHOP_CHAT, SLOT_ROLES.index(sp[x[0]].vai)))
            j, kieu = khac_vai[0]
            lan.append(
                KhopMucTaiLieu(
                    vai_vang=sv[i].vai,
                    vai_pred=sp[j].vai,
                    gia_tri_vang=sv[i].gia_tri,
                    gia_tri_pred=sp[j].gia_tri,
                    kieu=kieu,
                )
            )
            so.cong_o(sv[i].vai, sp[j].vai)
            da_quy_loi.add(j)
            continue
        so.cong_o(sv[i].vai, VAI_THIEU)
        cung_vai = [j for j, k in ung_vien if k is not None]
        if not cung_vai:
            vang_han.append((sv[i].vai, sv[i].gia_tri))
        elif any(
            chuan_so_sanh(sp[j].gia_tri) == chuan_so_sanh(sv[i].gia_tri) for j in cung_vai
        ):
            trung.append((sv[i].vai, sv[i].gia_tri))
        else:
            ung_vien_da_dung.append((sv[i].vai, sv[i].gia_tri))
    thua = [j for j in con_pred if j not in da_quy_loi]
    for j in thua:
        so.cong_o(VAI_THUA, sp[j].vai)

    return ChamMucTaiLieu(
        doc_key=doc_key,
        khop=khop,
        lan_vai=tuple(lan),
        vang_han=tuple(vang_han),
        trung_nhan=tuple(trung),
        ung_vien_da_dung=tuple(ung_vien_da_dung),
        pred_thua=tuple((sp[j].vai, sp[j].gia_tri) for j in thua),
        ket_qua=so.ket_qua(
            so_fact_vang=len({s.id_fact for s in sv}),
            so_fact_pred=len({s.id_fact for s in sp}),
            so_vang_han=len(vang_han),
            so_trung_nhan=len(trung),
            so_ung_vien_da_dung=len(ung_vien_da_dung),
        ),
    )


# ---------------------------------------------------------------------------
# Chấm cả bộ
# ---------------------------------------------------------------------------


def _chuan_bi(bo: BoVang, pred_theo_tai_lieu: Mapping[str, Iterable]) -> dict[str, list]:
    """Kiểm tập tài liệu rồi *vật chất hóa* fact của từng tài liệu thành list.

    Vật chất hóa vì hai chỉ số duyệt cùng một bảng: đưa vào một generator thì
    lượt chấm thứ hai thấy rỗng và mọi con số của nó bằng 0 - im lặng, không lỗi.

    Thiếu một tài liệu là thiếu một phần mẫu số (recall bị chia cho một mẫu số
    nhỏ hơn thật); thừa một tài liệu few-shot là chấm trên chính ví dụ của
    prompt. Cả hai là lỗi, không phải chuyện im lặng bỏ qua.
    """
    can = {t.doc_key for t in bo.tai_lieu_cham()}
    co = set(pred_theo_tai_lieu)
    thieu, thua = sorted(can - co), sorted(co - can)
    if thieu or thua:
        few = {t.doc_key for t in bo.tai_lieu_few_shot()}
        ghi_chu = " (tài liệu few-shot không được chấm)" if set(thua) & few else ""
        raise ValueError(
            f"tập tài liệu chấm lệch bộ vàng: thiếu {thieu}, thừa {thua}{ghi_chu}"
        )
    return {k: list(v) for k, v in pred_theo_tai_lieu.items()}


def cham_moi_tai_lieu(
    bo: BoVang, pred_theo_tai_lieu: Mapping[str, Iterable]
) -> dict[str, ChamTaiLieu]:
    """Chỉ số ghép cặp cho từng tài liệu chấm; khóa của kết quả là `doc_key`."""
    pred = _chuan_bi(bo, pred_theo_tai_lieu)
    return {
        t.doc_key: cham_tai_lieu(t.facts, pred[t.doc_key], doc_key=t.doc_key)
        for t in bo.tai_lieu_cham()
    }


def cham_moi_muc_tai_lieu(
    bo: BoVang, pred_theo_tai_lieu: Mapping[str, Iterable]
) -> dict[str, ChamMucTaiLieu]:
    """Chỉ số mức tài liệu cho từng tài liệu chấm."""
    pred = _chuan_bi(bo, pred_theo_tai_lieu)
    return {
        t.doc_key: cham_muc_tai_lieu(t.facts, pred[t.doc_key], doc_key=t.doc_key)
        for t in bo.tai_lieu_cham()
    }


def gop(cham: Iterable) -> KetQuaCham:
    """Cộng sổ đếm của nhiều tài liệu (nhận `ChamTaiLieu` hay `ChamMucTaiLieu`).

    Gấp từ phần tử đầu chứ không từ `KetQuaCham()` rỗng: sổ rỗng để ba bộ đếm
    phân loại là `None` ("không phân loại được"), và `None` lan qua phép cộng,
    nên khởi tạo bằng nó sẽ xóa mất phân loại của cả tập.
    """
    tong: KetQuaCham | None = None
    for c in cham:
        kq = c.ket_qua if hasattr(c, "ket_qua") else c
        tong = kq if tong is None else tong + kq
    return tong if tong is not None else KetQuaCham()


def cham_bo(bo: BoVang, pred_theo_tai_lieu: Mapping[str, Iterable]) -> KetQuaCham:
    """Sổ đếm gộp của chỉ số ghép cặp; `chi_so.so_vang` bằng đúng `bo.mau_so_slot()`."""
    return gop(cham_moi_tai_lieu(bo, pred_theo_tai_lieu).values())


def cham_bo_muc_tai_lieu(bo: BoVang, pred_theo_tai_lieu: Mapping[str, Iterable]) -> KetQuaCham:
    """Sổ đếm gộp của chỉ số mức tài liệu; cùng mẫu số vàng với chỉ số ghép cặp."""
    return gop(cham_moi_muc_tai_lieu(bo, pred_theo_tai_lieu).values())


# ---------------------------------------------------------------------------
# Ba cách đọc sổ đếm
# ---------------------------------------------------------------------------


def ma_tran_lan_lon(kq: KetQuaCham) -> dict[str, dict[str, int]]:
    """Ma trận đầy đủ (8 vai + `thừa`) × (8 vai + `thiếu`), kể cả ô bằng 0.

    In cả ô 0 vì một ô rỗng là một thông tin: cặp vai đó không lẫn lần nào.
    Ma trận A13 phải dựng từ `cham_bo_muc_tai_lieu` (xem docstring đầu file).
    """
    return {
        hang: {cot: kq.o_ma_tran.get((hang, cot), 0) for cot in COT_MA_TRAN}
        for hang in HANG_MA_TRAN
    }


def cap_vai_lan_nhieu_nhat(kq: KetQuaCham, so_dong: int = 5) -> list[tuple[str, str, int]]:
    """Các cặp (vai vàng, vai pred) lẫn nhiều nhất, giảm dần - câu trả lời của A13."""
    cap = [
        (h, c, n)
        for (h, c), n in kq.o_ma_tran.items()
        if h != c and h in SLOT_ROLE_SET and c in SLOT_ROLE_SET and n
    ]
    cap.sort(key=lambda x: (-x[2], SLOT_ROLES.index(x[0]), SLOT_ROLES.index(x[1])))
    return cap[:so_dong]


def theo_vai(kq: KetQuaCham) -> dict[str, ChiSo]:
    """Chỉ số của từng vai; đủ 8 khóa kể cả vai không có slot nào.

    TP của vai `v` là ô `(v, v)`, nên FN của nó gồm cả phần lẫn sang vai khác
    và FP của nó gồm cả phần vai khác lẫn sang nó - đúng cách đọc một ma trận
    lẫn lộn theo hàng và theo cột.
    """
    return {
        vai: ChiSo(
            so_vang=kq.vang_theo_vai[vai],
            so_pred=kq.pred_theo_vai[vai],
            chat=kq.chat_theo_vai[vai],
            long=kq.long_theo_vai[vai],
        )
        for vai in SLOT_ROLES
    }


def mau_so_phu(kq: KetQuaCham, bo_vai: str = VAI_BO_KHOI_MAU_SO_PHU) -> ChiSo:
    """Chỉ số trên mẫu số đã bỏ một vai (mặc định `subject`).

    `subject` bắt buộc theo `core.facts.kiem_fact` và chiếm 28,5% mẫu số, nên
    một prompt chỉ cần bám đúng chủ thể đã ăn hơn một phần tư điểm. Mẫu số phụ
    là con số nói về 7 vai còn lại - phần thật sự phân biệt prompt tốt với
    prompt tồi (ledger 2.5).
    """
    if bo_vai not in SLOT_ROLE_SET:
        raise ValueError(
            f"vai {bo_vai!r} không có trong danh mục `core.slots.SLOT_ROLES`: {list(SLOT_ROLES)}"
        )
    tong = ChiSo()
    for vai, cs in theo_vai(kq).items():
        if vai == bo_vai:
            continue
        tong = tong + cs
    return tong
