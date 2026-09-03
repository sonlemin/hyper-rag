"""Ngoại suy chi phí LLM cho cả khóa luận, đủ 6 khoản của FR-30 (story 2.6).

Hàm thuần: nhận số đo thật của một lần nạp cộng một bảng giả định có tên, tra
đơn giá ở `config/danh-muc-model.yaml`, trả bảng 6 khoản, tổng và một dòng đối
chiếu với mức báo động 60 USD (PRD mục 4.3). Không gọi LLM, không đọc môi
trường, không chạm kho - chạy lại là ra đúng con số cũ.

Sáu khoản đúng theo câu chữ của FR-30 ("phép ngoại suy cộng đủ các khoản,
không chỉ trích xuất"):

1. `nap_corpus` - dựng corpus ~40 tài liệu (trích xuất + embedding);
2. `sinh_t7` - sinh câu trả lời ở T7: 52 câu × 3 cấu hình × các vai đo (cấu
   hình tham chiếu thứ 4 của FR-28 chỉ đo recall tất định nên không vào đây);
3. `judge_do2` - judge của Đo 2 qua nhiều vòng chỉnh rubric, chạy trên model
   khác model sinh (GPT-4o);
4. `vong_so_chunk` - vòng so có/không chặn chunk của mục 5.3 (sinh + judge);
5. `gpt4o_dung_cuoi` - dựng lại corpus bằng GPT-4o ở bản cuối;
6. `ensemble_a13` - ensemble A13 nếu dùng: một model thứ hai chạy trên cả
   corpus, GPT-4o làm trọng tài ở phần bất đồng.

**Ranh giới đo / đoán, đếm theo đúng một cách.** Cờ `đo` chỉ dành cho khoản mà
**token và đơn giá cùng đến từ một lần chạy thật của chính model đó**; hiện chỉ
có khoản 1 (`nap_corpus`). Khoản 5 và 6 dùng token đo được của DeepSeek nhưng
áp đơn giá GPT-4o, tức thêm một giả định về việc hai model sinh cùng lượng
token, nên chúng mang cờ `giả định`. Ba khoản còn lại nhân số lời gọi đã biết
với một cỡ prompt giả định, vì T7 chưa chạy và chưa có ngữ cảnh truy hồi thật
để đếm token.

Từ lần nạp thật 03/09/2026, khoản 1 không còn là phép ngoại suy: file số đo đo
đúng 40 tài liệu của `eval/corpus/`, bằng `so_tai_lieu_corpus`, nên hệ số nhân
bằng 1 và cả token lẫn tiền là số đọc thẳng từ `audit_log`. Đó là lý do có
`test_so_do_nap_dung_bang_corpus_dich`: corpus lớn lên mà file số đo vẫn đo 40
tài liệu thì hệ số nhân khác 1 trở lại, và khoản 1 lặng lẽ quay về ngoại suy
trong khi mọi tài liệu vẫn gọi nó là số đo.

Cờ `đo` nói về *nguồn* của token và đơn giá, không nói "không còn giả định nào":
với khoản `đo`, đơn giá và token trên một tài liệu đều là số đã đo; với khoản
`giả định` thì chính token hoặc chính đơn giá là thứ được đoán. Vì thế mỗi khoản đều liệt kê giả
định của nó ở `Khoan.gia_dinh` và bảng in cột đó cạnh cột `nguon`: một con số
đoán trình bày như số đo là cách nhanh nhất để mất niềm tin ở chương 4.

Đơn giá là **cận trên chưa đối chiếu hóa đơn** (ledger 2.2): DeepSeek ghi mức
peak và giá cache-miss, OpenAI mức Standard. Ước cao an toàn hơn ước thấp cho
một mức báo động, nhưng mọi con số ở đây phải nói rõ điều đó.
"""

import json
import math
from dataclasses import dataclass, fields
from pathlib import Path

from adapters.model_catalog import (
    LOAI_EMBEDDING,
    LOAI_LLM,
    DanhMucModel,
    MucModel,
    danh_muc_mac_dinh,
)

# Mức báo động ngân sách API của PRD mục 4.3: chạm là dừng và tính lại.
MUC_BAO_DONG_USD: float = 60.0

GHI_CHU_DON_GIA: str = (
    "Đơn giá lấy từ config/danh-muc-model.yaml và là cận trên chưa đối chiếu hóa"
    " đơn: DeepSeek ghi mức peak cùng giá cache-miss (off-peak bằng nửa, token"
    " cache-hit rẻ hơn nhiều), OpenAI ghi mức Standard. Con số ngoại suy vì thế"
    " cao hơn chi phí thật, an toàn cho mức báo động 60 USD nhưng không dùng"
    " thay cho hóa đơn."
)

# Hai cờ nguồn của một khoản. `đo` chỉ dành cho khoản mà **cả token lẫn đơn giá**
# lấy từ một lần chạy thật của đúng model đó; nhân số tài liệu lên là phép nhân
# trên số đo, vẫn là `đo`. Áp đơn giá của model A lên token đo được của model B
# là một giả định (hai model không sinh cùng lượng token), nên khoản đó mang cờ
# `giả định` và giả định được nêu tên trong `Khoan.gia_dinh`.
NGUON_DO: str = "đo"
NGUON_GIA_DINH: str = "giả định"

# Tên model mặc định của từng đường. Đây là *tham số của phép ngoại suy*, không
# phải cấu hình vận hành: đổi tên ở đây không đổi `LLM_MODEL` của compose.
MODEL_TRICH_XUAT: str = "deepseek-v4-flash"
MODEL_EMBEDDING: str = "text-embedding-3-small"
MODEL_SINH: str = "deepseek-v4-flash"
MODEL_JUDGE: str = "gpt-4o"
MODEL_DUNG_CUOI: str = "gpt-4o"
MODEL_ENSEMBLE: str = "gpt-4o-mini"


@dataclass(frozen=True)
class SoDoNap:
    """Số đo thật của một lần nạp: tổng token và tiền của `so_tai_lieu` tài liệu.

    Token embedding không có token ra (`text-embedding-3-small` chỉ tính token
    vào), nên chỉ một trường. Mọi phép ngoại suy chia cho `so_tai_lieu` để ra
    mức mỗi tài liệu rồi nhân lên. Khi `so_tai_lieu` bằng đúng số tài liệu của
    corpus đích - trạng thái từ lần nạp thật 03/09/2026 - hệ số nhân bằng 1 và
    khoản 1 là số đo trực tiếp, không còn giả định nào về cỡ tài liệu.
    """

    so_tai_lieu: int
    token_vao_llm: int
    token_ra_llm: int
    chi_phi_llm_usd: float
    token_embedding: int
    chi_phi_embedding_usd: float


# --- Số đo lần nạp thật: đọc từ file, không chép tay ---------------------------

# Lược đồ file số đo mà `api/do_chi_phi.py --xuat-json` ghi ra. Con số này phải
# bằng `api.dot_nap.VERSION_SO_DO`; hai bên khai riêng vì chiều import cấm
# `eval/` gọi sang `api/`, và `tests/test_dot_nap.py` canh chúng bằng nhau.
VERSION_SO_DO_NAP: int = 1

# File số đo của lần nạp thật, có commit. Trước story 2.7 sáu con số này là hằng
# chép tay từ bảng chi phí in ra console: không ai canh chúng còn khớp
# `audit_log`. Nay chúng là đầu ra của chính lần nạp.
DUONG_DAN_SO_DO_NAP: Path = Path(__file__).resolve().parent / "so_do_nap" / "nap-that.json"

KHOA_BAT_BUOC: tuple[str, ...] = (
    "version", "ngay", "lenh", "space", "so_tai_lieu", "theo_model", "tong",
)
KHOA_DONG_MODEL: tuple[str, ...] = ("model", "loai", "token_vao", "token_ra", "chi_phi_usd")
KHOA_TONG: tuple[str, ...] = ("so_lan", "token_vao", "token_ra", "chi_phi_usd")

# Hai loại model mà phép ngoại suy biết cộng. Một `loai` lạ **không** được rơi
# vào nhánh LLM: nó sẽ âm thầm thổi phồng token trích xuất, tức thổi phồng đúng
# khoản mà cả bảng chương 4 nhân lên 40 lần.
LOAI_HOP_LE: frozenset[str] = frozenset({LOAI_LLM, LOAI_EMBEDDING})

# Sai số cho phép khi đối chiếu khối `tong` với tổng cộng lại từ `theo_model`.
# Chỉ để chịu phần dôi của phép cộng dấu phẩy động, không để chịu một con số sai.
SAI_SO_USD: float = 1e-9


class SoDoNapKhongHopLe(ValueError):
    """File số đo nạp thiếu khóa, sai kiểu, sai giá trị, hoặc mang lược đồ lạ.

    Thông điệp luôn mang **tên file** cùng lý do: bảng ngoại suy của chương 4
    đọc file này, nên một lỗi ở đây phải chỉ được ngay file nào phải nạp lại.

    Mọi đường thoát của `doc_so_do_nap` đi qua lớp này. Đó không phải chuyện
    hình thức: `SoDoNapKhongHopLe` là con của `ValueError`, nên một `ValueError`
    trần lọt ra từ cửa đọc sẽ **không** bị `except SoDoNapKhongHopLe` của
    `eval/xem_do_trich_xuat.py` bắt, và báo cáo chết bằng traceback.
    """

    code = "SO_DO_NAP_KHONG_HOP_LE"


def _so(gia_tri, ten: str, duong_dan: Path, *, duong: bool = False) -> float:
    """Một trường số của file: phải là số thật, hữu hạn, không âm.

    `json.loads` nhận `NaN`, `Infinity` và `-Infinity` theo mặc định, và `NaN`
    cho `False` ở mọi phép so sánh nên nó lọt qua một cửa chỉ hỏi `< 0` rồi đầu
    độc mọi tổng sau. `bool` bị loại riêng vì `True` là một `int` hợp lệ với
    `isinstance` mà không phải một con số ai định ghi.
    """
    if isinstance(gia_tri, bool) or not isinstance(gia_tri, (int, float)):
        raise SoDoNapKhongHopLe(
            f"{duong_dan.name}: trường {ten!r} phải là số, nhận được {gia_tri!r}"
        )
    x = float(gia_tri)
    if not math.isfinite(x):
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: trường {ten!r} không hữu hạn ({gia_tri!r})")
    if x < 0:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: trường {ten!r} âm ({gia_tri!r})")
    if duong and x <= 0:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: trường {ten!r} phải dương, nhận được {gia_tri!r}")
    return x


def _khop(a: float, b: float) -> bool:
    return abs(a - b) <= SAI_SO_USD + SAI_SO_USD * abs(b)


def doc_so_do_nap(duong_dan: str | Path | None = None) -> SoDoNap:
    """Đọc file số đo của một lần nạp thật thành `SoDoNap`; không ném `ValueError` trần.

    Cộng theo `loai` của từng dòng model: mọi dòng `embedding` vào khoản
    embedding, mọi dòng `llm` vào khoản LLM. Nhờ thế đổi model trích xuất hay
    thêm một model thứ hai trong cùng đợt không phải sửa hàm này.

    Khối `tong` của file được **đối chiếu** với tổng cộng lại từ `theo_model`:
    hai con số trong cùng một file có commit mà lệch nhau thì ít nhất một cái
    sai, và không có lý do để đoán cái nào.
    """
    duong_dan = DUONG_DAN_SO_DO_NAP if duong_dan is None else Path(duong_dan)
    try:
        raw = json.loads(duong_dan.read_text(encoding="utf-8"))
    except OSError as loi:
        raise SoDoNapKhongHopLe(f"{duong_dan}: không đọc được file số đo nạp: {loi}") from loi
    except UnicodeDecodeError as loi:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: không phải UTF-8: {loi}") from loi
    except json.JSONDecodeError as loi:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: không phải JSON hợp lệ: {loi}") from loi
    if not isinstance(raw, dict):
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: gốc file phải là một object JSON")
    thieu = [k for k in KHOA_BAT_BUOC if k not in raw]
    if thieu:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: thiếu khóa {thieu}")
    if raw["version"] != VERSION_SO_DO_NAP:
        raise SoDoNapKhongHopLe(
            f"{duong_dan.name}: version {raw['version']!r} lạ, chỉ đọc được {VERSION_SO_DO_NAP}"
        )
    if not isinstance(raw["theo_model"], list) or not raw["theo_model"]:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: `theo_model` phải là danh sách không rỗng")

    tv_llm = tr_llm = t_emb = 0
    usd_llm = usd_emb = 0.0
    tong_lan = tong_vao = tong_ra = 0
    tong_usd = 0.0
    for i, dong in enumerate(raw["theo_model"]):
        if not isinstance(dong, dict):
            raise SoDoNapKhongHopLe(f"{duong_dan.name}: `theo_model[{i}]` không phải object")
        thieu = [k for k in KHOA_DONG_MODEL if k not in dong]
        if thieu:
            raise SoDoNapKhongHopLe(f"{duong_dan.name}: `theo_model[{i}]` thiếu khóa {thieu}")
        if dong["loai"] not in LOAI_HOP_LE:
            raise SoDoNapKhongHopLe(
                f"{duong_dan.name}: `theo_model[{i}].loai` là {dong['loai']!r},"
                f" chỉ cộng được {sorted(LOAI_HOP_LE)}"
            )
        tv = int(_so(dong["token_vao"], f"theo_model[{i}].token_vao", duong_dan))
        tr = int(_so(dong["token_ra"], f"theo_model[{i}].token_ra", duong_dan))
        usd = _so(dong["chi_phi_usd"], f"theo_model[{i}].chi_phi_usd", duong_dan)
        tong_vao += tv
        tong_ra += tr
        tong_usd += usd
        if "so_lan" in dong:
            tong_lan += int(_so(dong["so_lan"], f"theo_model[{i}].so_lan", duong_dan))
        if dong["loai"] == LOAI_EMBEDDING:
            t_emb += tv
            usd_emb += usd
        else:
            tv_llm += tv
            tr_llm += tr
            usd_llm += usd

    tong = raw["tong"]
    if not isinstance(tong, dict):
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: `tong` phải là một object JSON")
    thieu = [k for k in KHOA_TONG if k not in tong]
    if thieu:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: `tong` thiếu khóa {thieu}")
    lech = []
    for ten, cong in (("token_vao", tong_vao), ("token_ra", tong_ra)):
        if int(_so(tong[ten], f"tong.{ten}", duong_dan)) != cong:
            lech.append(f"tong.{ten}={tong[ten]!r} nhưng cộng theo_model ra {cong}")
    if not _khop(_so(tong["chi_phi_usd"], "tong.chi_phi_usd", duong_dan), tong_usd):
        lech.append(f"tong.chi_phi_usd={tong['chi_phi_usd']!r} nhưng cộng theo_model ra {tong_usd}")
    if tong_lan and int(_so(tong["so_lan"], "tong.so_lan", duong_dan)) != tong_lan:
        lech.append(f"tong.so_lan={tong['so_lan']!r} nhưng cộng theo_model ra {tong_lan}")
    if lech:
        raise SoDoNapKhongHopLe(f"{duong_dan.name}: khối `tong` lệch với `theo_model`: {'; '.join(lech)}")

    return SoDoNap(
        # `so_tai_lieu` là mẫu số của phép chia "tiền trên một tài liệu"; 0 làm
        # cả bảng ngoại suy vô nghĩa (hoặc nổ `ZeroDivisionError`), nên nó bị
        # chặn ở đây chứ không ở `_kiem_so_do` với một `ValueError` trần.
        so_tai_lieu=int(_so(raw["so_tai_lieu"], "so_tai_lieu", duong_dan, duong=True)),
        token_vao_llm=tv_llm,
        token_ra_llm=tr_llm,
        chi_phi_llm_usd=usd_llm,
        token_embedding=t_emb,
        chi_phi_embedding_usd=usd_emb,
    )


@dataclass(frozen=True)
class GiaDinh:
    """Mọi giả định của phép ngoại suy, có tên và có giá trị mặc định ghi rõ.

    Cỡ prompt của các khoản chưa chạy là ước lượng, không phải số đo: ngữ cảnh
    truy hồi của một câu hỏi gồm vài hyperedge đã che cộng vài chunk, nên
    khoảng 3000 token vào và 500 token ra cho một lời gọi sinh là cỡ hợp lý cho
    mức trần; judge đọc câu hỏi, câu trả lời và rubric nên ước 2500 vào / 400
    ra. Ai đó đo được số thật ở T7 thì thay đúng một tham số ở đây.
    """

    # Khoản 1 và 5: corpus của story 2.8, đúng số mục trong
    # `eval/corpus_thiet_ke.yaml` (`tests/test_cham_trich_xuat.py` khóa hai bên
    # bằng nhau). Khi lần nạp thật chạy trên đủ 40 tài liệu thì `ti_le` bằng 1 và
    # khoản `nap_corpus` thôi là phép nhân: nó trở thành số đo.
    so_tai_lieu_corpus: int = 40
    # Khoản 2: 52 câu × 3 cấu hình đo × số vai người hỏi thật dùng (devops,
    # tech_support của `config/policy-toi-gian.yaml`).
    so_cau: int = 52
    so_cau_hinh: int = 3
    so_vai: int = 2
    token_vao_sinh: int = 3000
    token_ra_sinh: int = 500
    # Khoản 3: bộ vàng 30 câu, chấm lại sau mỗi vòng chỉnh rubric.
    so_cau_judge: int = 30
    so_vong_rubric: int = 3
    token_vao_judge: int = 2500
    token_ra_judge: int = 400
    # Khoản 4: tập câu N5 thuộc bộ vàng có nhãn chạm vùng L1, chạy ở vai Tech
    # Support, hai cấu hình (có/không chặn chunk), mỗi câu một lượt sinh và một
    # lượt judge.
    so_cau_so_chunk: int = 10
    so_cau_hinh_so_chunk: int = 2
    # Khoản 6: model thứ hai chạy trên cả corpus, GPT-4o làm trọng tài ở phần
    # hai model bất đồng.
    ty_le_bat_dong: float = 0.3


@dataclass(frozen=True)
class Khoan:
    """Một khoản chi phí: quy mô, token hai chiều, tiền, và nó đo hay đoán.

    `so_luong` đi kèm `don_vi` chứ không phải một cột "lần" mù đơn vị: khoản nạp
    corpus đếm *tài liệu*, khoản sinh câu trả lời đếm *lời gọi*, và trộn hai đơn
    vị trong một cột là mời người đọc cộng nhầm. `gia_dinh` liệt kê từng giả
    định có tên của khoản, để cờ `nguon` không phải gánh cả câu chuyện.
    """

    ten: str
    mo_ta: str
    model: str
    so_luong: int
    don_vi: str
    token_vao: int
    token_ra: int
    chi_phi_usd: float
    nguon: str
    gia_dinh: tuple[str, ...] = ()


@dataclass(frozen=True)
class BangNgoaiSuy:
    khoan: tuple[Khoan, ...]
    tong_usd: float
    muc_bao_dong_usd: float = MUC_BAO_DONG_USD

    def __post_init__(self):
        if self.muc_bao_dong_usd <= 0:
            raise ValueError(
                f"mức báo động phải dương, nhận được {self.muc_bao_dong_usd!r}"
            )
        tong = sum(k.chi_phi_usd for k in self.khoan)
        if abs(tong - self.tong_usd) > 1e-9:
            raise ValueError(
                f"tổng {self.tong_usd} không khớp tổng các khoản {tong}:"
                " một khoản bị bỏ quên hoặc cộng hai lần"
            )

    @property
    def vuot_bao_dong(self) -> bool:
        """Chạm mức báo động cũng là chạm: PRD viết "chạm là dừng và tính lại"."""
        return self.tong_usd >= self.muc_bao_dong_usd

    @property
    def phan_tram_bao_dong(self) -> float:
        return 100 * self.tong_usd / self.muc_bao_dong_usd

    def khoan_theo_ten(self, ten: str) -> Khoan:
        for k in self.khoan:
            if k.ten == ten:
                return k
        raise KeyError(f"không có khoản {ten!r} (đang có {[k.ten for k in self.khoan]})")


def _muc(danh_muc: DanhMucModel, ten: str, loai: str | None = LOAI_LLM) -> MucModel:
    return danh_muc.muc(ten, loai=loai)


DON_VI_LOI_GOI: str = "lời gọi"
DON_VI_TAI_LIEU: str = "tài liệu"


def _khoan_goi(
    *,
    ten: str,
    mo_ta: str,
    muc: MucModel,
    so_lan: int,
    token_vao_moi_lan: int,
    token_ra_moi_lan: int,
    nguon: str = NGUON_GIA_DINH,
    gia_dinh: tuple[str, ...] = (),
) -> Khoan:
    """Một khoản dạng 'N lời gọi cùng cỡ' - dùng cho mọi khoản chưa chạy."""
    tv, tr = so_lan * token_vao_moi_lan, so_lan * token_ra_moi_lan
    return Khoan(
        ten=ten,
        mo_ta=mo_ta,
        model=muc.ten,
        so_luong=so_lan,
        don_vi=DON_VI_LOI_GOI,
        token_vao=tv,
        token_ra=tr,
        chi_phi_usd=muc.chi_phi_usd(tv, tr),
        nguon=nguon,
        gia_dinh=gia_dinh + (
            f"cỡ một lời gọi: {token_vao_moi_lan} token vào / {token_ra_moi_lan} token ra",
        ),
    )


def _kiem_so_do(do: SoDoNap) -> None:
    if do.so_tai_lieu <= 0:
        raise ValueError("số đo nạp phải có ít nhất một tài liệu để chia trung bình")
    xau = [
        ten
        for ten in (
            "token_vao_llm",
            "token_ra_llm",
            "chi_phi_llm_usd",
            "token_embedding",
            "chi_phi_embedding_usd",
        )
        # Kiểm hữu hạn chứ không chỉ kiểm âm: `NaN` cho False ở mọi phép so
        # sánh nên nó lọt qua một cửa chỉ hỏi `< 0`, rồi đầu độc mọi tổng sau.
        if not math.isfinite(getattr(do, ten)) or getattr(do, ten) < 0
    ]
    if xau:
        raise ValueError(f"số đo nạp có trường âm hoặc không hữu hạn: {xau}")


def _kiem_gia_dinh(gia_dinh: GiaDinh) -> None:
    """Giả định phải không âm và hữu hạn; `so_tai_lieu_corpus` phải dương.

    Cho phép `0` ở các tham số khác vì tắt một khoản là câu hỏi hợp lệ ("bỏ
    ensemble thì còn bao nhiêu" là `ty_le_bat_dong=0`); riêng số tài liệu corpus
    thì không, vì corpus rỗng làm cả bảng vô nghĩa. `ty_le_bat_dong` thêm trần
    1: hai model không bất đồng ở hơn 100% nội dung.
    """
    xau = [
        f.name
        for f in fields(GiaDinh)
        if not math.isfinite(getattr(gia_dinh, f.name)) or getattr(gia_dinh, f.name) < 0
    ]
    if xau:
        raise ValueError(f"giả định phải là số không âm hữu hạn: {xau}")
    if gia_dinh.so_tai_lieu_corpus <= 0:
        raise ValueError("`so_tai_lieu_corpus` phải dương")
    if gia_dinh.ty_le_bat_dong > 1:
        raise ValueError(
            f"`ty_le_bat_dong` là tỉ lệ, không quá 1; nhận được {gia_dinh.ty_le_bat_dong}"
        )


def ngoai_suy(
    do: SoDoNap,
    danh_muc: DanhMucModel | None = None,
    gia_dinh: GiaDinh = GiaDinh(),
) -> BangNgoaiSuy:
    """Bảng 6 khoản FR-30 từ một số đo nạp và một bảng giả định."""
    _kiem_so_do(do)
    _kiem_gia_dinh(gia_dinh)
    danh_muc = danh_muc_mac_dinh() if danh_muc is None else danh_muc
    ti_le = gia_dinh.so_tai_lieu_corpus / do.so_tai_lieu

    trich = _muc(danh_muc, MODEL_TRICH_XUAT)
    dung_cuoi = _muc(danh_muc, MODEL_DUNG_CUOI)
    ensemble = _muc(danh_muc, MODEL_ENSEMBLE)

    # 1. Nạp corpus: số đo thật, nhân theo tỉ lệ tài liệu. Hệ số bằng 1 kể từ
    # lần nạp thật 40 tài liệu, nên khoản này là số đo trực tiếp.
    nap = Khoan(
        ten="nap_corpus",
        mo_ta=(
            f"dựng corpus {gia_dinh.so_tai_lieu_corpus} tài liệu (trích xuất +"
            + (
                " embedding), đo trực tiếp trên chính lần nạp corpus"
                if ti_le == 1
                else f" embedding), suy từ {do.so_tai_lieu} tài liệu đã nạp thật"
            )
        ),
        model=f"{trich.ten} + {MODEL_EMBEDDING}",
        so_luong=round(gia_dinh.so_tai_lieu_corpus),
        don_vi=DON_VI_TAI_LIEU,
        token_vao=round((do.token_vao_llm + do.token_embedding) * ti_le),
        token_ra=round(do.token_ra_llm * ti_le),
        chi_phi_usd=(do.chi_phi_llm_usd + do.chi_phi_embedding_usd) * ti_le,
        nguon=NGUON_DO,
        gia_dinh=(
            ()
            if ti_le == 1
            else (
                f"{gia_dinh.so_tai_lieu_corpus} tài liệu của corpus 2.8 cùng cỡ và"
                f" cùng loại văn bản với {do.so_tai_lieu} tài liệu đã đo",
            )
        ),
    )

    # 2. Sinh câu trả lời T7.
    so_lan_sinh = gia_dinh.so_cau * gia_dinh.so_cau_hinh * gia_dinh.so_vai
    sinh = _khoan_goi(
        ten="sinh_t7",
        mo_ta=(
            f"sinh câu trả lời T7: {gia_dinh.so_cau} câu ×"
            f" {gia_dinh.so_cau_hinh} cấu hình × {gia_dinh.so_vai} vai"
        ),
        muc=_muc(danh_muc, MODEL_SINH),
        so_lan=so_lan_sinh,
        token_vao_moi_lan=gia_dinh.token_vao_sinh,
        token_ra_moi_lan=gia_dinh.token_ra_sinh,
    )

    # 3. Judge Đo 2 qua nhiều vòng chỉnh rubric. Nhân cả `so_vai` như khoản
    # sinh: sinh ở hai vai thì có hai bộ câu trả lời phải chấm, và bỏ hệ số đó
    # làm khoản đắt nhất của bảng nhỏ đi một nửa.
    so_lan_judge = (
        gia_dinh.so_cau_judge
        * gia_dinh.so_cau_hinh
        * gia_dinh.so_vai
        * gia_dinh.so_vong_rubric
    )
    judge = _khoan_goi(
        ten="judge_do2",
        mo_ta=(
            f"judge Đo 2: {gia_dinh.so_cau_judge} câu bộ vàng ×"
            f" {gia_dinh.so_cau_hinh} cấu hình × {gia_dinh.so_vai} vai ×"
            f" {gia_dinh.so_vong_rubric} vòng rubric"
        ),
        muc=_muc(danh_muc, MODEL_JUDGE),
        so_lan=so_lan_judge,
        token_vao_moi_lan=gia_dinh.token_vao_judge,
        token_ra_moi_lan=gia_dinh.token_ra_judge,
        gia_dinh=("judge chấm mọi câu trả lời đã sinh, tức cả ba cấu hình và cả hai vai",),
    )

    # 4. Vòng so có/không chặn chunk (5.3): mỗi câu một lượt sinh và một lượt judge.
    so_cap = gia_dinh.so_cau_so_chunk * gia_dinh.so_cau_hinh_so_chunk
    sinh_chunk = _khoan_goi(
        ten="_tam_sinh",
        mo_ta="",
        muc=_muc(danh_muc, MODEL_SINH),
        so_lan=so_cap,
        token_vao_moi_lan=gia_dinh.token_vao_sinh,
        token_ra_moi_lan=gia_dinh.token_ra_sinh,
    )
    judge_chunk = _khoan_goi(
        ten="_tam_judge",
        mo_ta="",
        muc=_muc(danh_muc, MODEL_JUDGE),
        so_lan=so_cap,
        token_vao_moi_lan=gia_dinh.token_vao_judge,
        token_ra_moi_lan=gia_dinh.token_ra_judge,
    )
    so_chunk = Khoan(
        ten="vong_so_chunk",
        mo_ta=(
            f"vòng so có/không chặn chunk (5.3): {gia_dinh.so_cau_so_chunk} câu N5"
            f" × {gia_dinh.so_cau_hinh_so_chunk} cấu hình, mỗi câu một lượt sinh"
            " và một lượt judge"
        ),
        model=f"{MODEL_SINH} + {MODEL_JUDGE}",
        so_luong=sinh_chunk.so_luong + judge_chunk.so_luong,
        don_vi=DON_VI_LOI_GOI,
        token_vao=sinh_chunk.token_vao + judge_chunk.token_vao,
        token_ra=sinh_chunk.token_ra + judge_chunk.token_ra,
        chi_phi_usd=sinh_chunk.chi_phi_usd + judge_chunk.chi_phi_usd,
        nguon=NGUON_GIA_DINH,
        gia_dinh=sinh_chunk.gia_dinh + judge_chunk.gia_dinh,
    )

    # 5. GPT-4o dựng cuối: cùng token trích xuất, khác đơn giá; embedding không
    # đổi model nên tính lại y nguyên phần embedding.
    tv_cuoi = round(do.token_vao_llm * ti_le)
    tr_cuoi = round(do.token_ra_llm * ti_le)
    dung_cuoi_khoan = Khoan(
        ten="gpt4o_dung_cuoi",
        mo_ta=(
            f"dựng lại corpus {gia_dinh.so_tai_lieu_corpus} tài liệu bằng"
            f" {dung_cuoi.ten} ở bản cuối (bậc 1 của R2 cũng dùng khoản này)"
        ),
        model=f"{dung_cuoi.ten} + {MODEL_EMBEDDING}",
        so_luong=round(gia_dinh.so_tai_lieu_corpus),
        don_vi=DON_VI_TAI_LIEU,
        token_vao=tv_cuoi + round(do.token_embedding * ti_le),
        token_ra=tr_cuoi,
        chi_phi_usd=dung_cuoi.chi_phi_usd(tv_cuoi, tr_cuoi)
        + do.chi_phi_embedding_usd * ti_le,
        # Token là số đo của `deepseek-v4-flash`, đơn giá là của `gpt-4o`: đây
        # là một *giả định* về việc hai model sinh cùng lượng token, không phải
        # một khoản đã đo. Vòng đo `v1-gpt-4o` cho thấy giả định đó lệch không
        # nhiều (5927+2173 so với 8122+2906 của DeepSeek trên cùng 8 tài liệu),
        # nhưng lệch theo chiều nào thì tùy tokenizer.
        nguon=NGUON_GIA_DINH,
        gia_dinh=(
            f"{dung_cuoi.ten} sinh cùng lượng token với {trich.ten} trên cùng tài liệu",
            f"{gia_dinh.so_tai_lieu_corpus} tài liệu cùng cỡ với tài liệu đã đo",
        ),
    )

    # 6. Ensemble A13: model thứ hai chạy cả corpus, GPT-4o làm trọng tài ở
    # phần bất đồng.
    tv_ens = round(do.token_vao_llm * ti_le)
    tr_ens = round(do.token_ra_llm * ti_le)
    tv_trong_tai = round(tv_ens * gia_dinh.ty_le_bat_dong)
    tr_trong_tai = round(tr_ens * gia_dinh.ty_le_bat_dong)
    ensemble_khoan = Khoan(
        ten="ensemble_a13",
        mo_ta=(
            f"ensemble A13 nếu dùng: {ensemble.ten} chạy cả corpus, {dung_cuoi.ten}"
            f" làm trọng tài trên {gia_dinh.ty_le_bat_dong:.0%} phần bất đồng"
        ),
        model=f"{ensemble.ten} + {dung_cuoi.ten}",
        so_luong=round(gia_dinh.so_tai_lieu_corpus * (1 + gia_dinh.ty_le_bat_dong)),
        don_vi=DON_VI_TAI_LIEU,
        token_vao=tv_ens + tv_trong_tai,
        token_ra=tr_ens + tr_trong_tai,
        chi_phi_usd=ensemble.chi_phi_usd(tv_ens, tr_ens)
        + dung_cuoi.chi_phi_usd(tv_trong_tai, tr_trong_tai),
        nguon=NGUON_GIA_DINH,
        gia_dinh=(
            f"{ensemble.ten} và {dung_cuoi.ten} sinh cùng lượng token với {trich.ten}",
            f"hai model bất đồng ở {gia_dinh.ty_le_bat_dong:.0%} nội dung",
        ),
    )

    khoan = (nap, sinh, judge, so_chunk, dung_cuoi_khoan, ensemble_khoan)
    return BangNgoaiSuy(khoan=khoan, tong_usd=sum(k.chi_phi_usd for k in khoan))


def so_vn(x: float, chu_so: int = 4) -> str:
    """Số theo quy ước tiếng Việt: dấu phẩy thập phân.

    Tài liệu, ledger và sprint-status đều viết `70,7%`; một bảng in `70.7%` bắt
    người đọc tự dịch giữa hai quy ước trên cùng một con số.
    """
    return f"{x:.{chu_so}f}".replace(".", ",")


def dong_bang(bang: BangNgoaiSuy) -> list[str]:
    """Bảng ngoại suy dạng dòng chữ, cho console; trang HTML dựng bảng riêng."""
    rong_ten = max([len("khoản")] + [len(k.ten) for k in bang.khoan]) + 2
    rong_model = max([len("model")] + [len(k.model) for k in bang.khoan]) + 2
    rong_quy_mo = max([len("quy mô")] + [len(f"{k.so_luong} {k.don_vi}") for k in bang.khoan]) + 2
    dong = [
        f"{'khoản':<{rong_ten}}{'model':<{rong_model}}{'quy mô':<{rong_quy_mo}}"
        f"{'token vào':>11}{'token ra':>10}{'USD':>10}  nguồn",
    ]
    for k in bang.khoan:
        quy_mo = f"{k.so_luong} {k.don_vi}"
        dong.append(
            f"{k.ten:<{rong_ten}}{k.model:<{rong_model}}{quy_mo:<{rong_quy_mo}}"
            f"{k.token_vao:>11}{k.token_ra:>10}{so_vn(k.chi_phi_usd):>10}  {k.nguon}"
        )
    dong.append(
        f"{'TỔNG':<{rong_ten + rong_model + rong_quy_mo}}"
        f"{'':>11}{'':>10}{so_vn(bang.tong_usd):>10}"
    )
    dong.append(
        f"Mức báo động {bang.muc_bao_dong_usd:.0f} USD:"
        f" {'CHẠM/VƯỢT' if bang.vuot_bao_dong else 'chưa chạm'}"
        f" ({so_vn(bang.phan_tram_bao_dong, 1)}% mức báo động)"
    )
    dong.append(GHI_CHU_DON_GIA)
    return dong


__all__ = [
    "MUC_BAO_DONG_USD",
    "so_vn",
    "GHI_CHU_DON_GIA",
    "NGUON_DO",
    "NGUON_GIA_DINH",
    "VERSION_SO_DO_NAP",
    "DUONG_DAN_SO_DO_NAP",
    "SoDoNapKhongHopLe",
    "doc_so_do_nap",
    "SoDoNap",
    "GiaDinh",
    "Khoan",
    "BangNgoaiSuy",
    "ngoai_suy",
    "dong_bang",
]
