"""Thử lại khi provider chặn nhịp: một bản dùng chung cho cả hai đường gọi.

Khuôn này sinh ra ở `eval/do_trich_xuat.py` (story 2.8) cho *đường đo*, nơi 40
lời gọi tuần tự trên một key dùng chung đủ để chạm 429. Story 2.13 hạ nó xuống
`adapters/` vì *đường nạp* cần đúng luật đó: một đợt 50 tài liệu qua API ngoài
là hàng trăm lời gọi LLM và embedding, và cho tới 2.13 một lời gọi 429 giữa đợt
làm mất cả đợt (`TaskGroup` hủy anh em, `ainsert` dội lên, phần đã trả tiền
không dùng được).

**Module này là thư viện, không phải một tầng tự động.** Nơi gọi quyết định gắn
retry ở đâu, và luật là **đúng một lớp trên mỗi đường gọi**:

- đường nạp: `adapters/trich_xuat.py::_trich_mot_chunk` (LLM) và
  `adapters/llm_wrapper.py::bo_embedding` (embedding);
- đường đo của story 2.6: `eval/do_trich_xuat.py::goi_llm_co_thu_lai`.

`adapters/llm_wrapper.py::bo_llm` **không** được bọc: cả hai đường đi qua nó
trước khi tới lớp của mình, nên một lớp nữa ở đó cho 4x4 = 16 lần thử, và một
cửa sổ chặn nhịp kéo dài thêm chứ không ngắn đi. `adapters/ingest.py::ainsert`
cũng không: thử lại cả tài liệu là trả tiền lại cho mọi chunk đã xong.

Đọc mã HTTP theo *hình dạng* chứ không theo lớp ngoại lệ: module này không
import SDK của provider nào (openai, ollama, httpx). Biết tên lớp ngoại lệ của
từng SDK là một chỗ nữa phải sửa mỗi lần đổi provider.

**Story 3.3 thêm ngân sách, và nó là một giá trị chứ không phải một hằng của
module.** Đường truy hồi HTTP đi qua đúng `bo_embedding` mà đường nạp đi qua,
nhưng nó chờ được vài giây chứ không vài phút; nên số lần thử, trần chờ và trần
cho một lời gọi gộp thành `NganSachThuLai`, và hai bản có tên là `NGAN_SACH_NAP`
với `NGAN_SACH_TRUY_HOI`. Cùng story thêm trần cho **một** lời gọi (trước đó
không có, nên một socket treo giữ cả đợt đứng vô hạn) và nhận 408/425 là mã
đáng thử lại.
"""

import asyncio
import math
import socket
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

__all__ = [
    "LOI_MANG_TAM_THOI",
    "MA_DANG_THU_LAI",
    "MA_RATE_LIMIT",
    "NGAN_SACH_NAP",
    "NGAN_SACH_TRUY_HOI",
    "SO_LAN_THU",
    "SO_LAN_THU_TRUY_HOI",
    "TEN_TRUONG_MA_HTTP",
    "BIEN_DO_JITTER_GIAY",
    "TRAN_CHO_GIAY",
    "TRAN_CHO_TRUY_HOI_GIAY",
    "TRAN_LLM_TRUY_HOI_GIAY",
    "TRAN_MOT_LOI_GOI_NAP_GIAY",
    "TRAN_MOT_LOI_GOI_TRUY_HOI_GIAY",
    "ChanNhipQuaLau",
    "NganSachThuLai",
    "cho_bao_lau",
    "giay_cho_lai",
    "goi_co_thu_lai",
    "goi_mot_lan_co_tran",
    "TEN_DA_BO",
    "tu_choi_ten_da_bo",
    "la_loi_mang_tam_thoi",
    "ma_http_cua",
    "nen_thu_lai",
]

# Số lần thử một lời gọi trước khi bỏ cuộc, kể cả lần đầu. Bốn vòng của 2.6
# chạy 8 lời gọi tuần tự nên 429 gần như không xảy ra; corpus 40 tài liệu là
# 40+ lời gọi liên tiếp trên một key dùng chung, xác suất chạm 429 khác hẳn.
SO_LAN_THU: int = 4
# Trần thời gian chờ giữa hai lần thử. `Retry-After` của provider được tôn
# trọng nhưng vẫn bị cắt ở đây: một header 3600 giây làm đợt treo cả giờ mà
# không in ra dòng nào.
TRAN_CHO_GIAY: float = 60.0
# Mã HTTP đáng thử lại: 429 (rate limit) và mọi 5xx (lỗi phía provider). Mã 4xx
# khác **không** thử lại - prompt sai, key sai hay model sai thì thử lại chỉ
# tốn thêm thời gian và vẫn hỏng y như cũ.
MA_RATE_LIMIT: int = 429
# Hai mã 4xx còn lại **cũng** là ca thử lại đúng, và trước story 3.3 chúng rơi
# nhầm vào nhánh "4xx khác thì không" cùng chỗ với 400 và 401. 408 Request
# Timeout là provider tự nói "lời gọi này chưa xong, gửi lại đi"; 425 Too Early
# là một dạng chặn nhịp khác. Một đợt 73 lời gọi mất trắng vì một cái mà lần
# thử thứ hai gần chắc đi qua (khoản ledger 2.13).
MA_QUA_HAN_YEU_CAU: int = 408
MA_QUA_SOM: int = 425
MA_DANG_THU_LAI: frozenset[int] = frozenset(
    {MA_QUA_HAN_YEU_CAU, MA_QUA_SOM, MA_RATE_LIMIT}
)

# Ba tên mà các SDK khác nhau dùng cho cùng một thứ. `openai` phơi
# `status_code`, `httpx`/`ollama` có nơi dùng `status`, và một số lớp lỗi bọc lại
# dùng `code`. Đọc cả ba thay vì chọn một: bỏ sót tên nghĩa là mọi 429 của
# provider đó rơi vào nhánh "không thử lại" mà không có dấu hiệu gì.
TEN_TRUONG_MA_HTTP: tuple[str, ...] = ("status_code", "status", "code")


def ma_http_cua(loi: BaseException) -> int | None:
    """Mã HTTP của một ngoại lệ provider, nếu đọc được; không thì `None`."""
    for doi_tuong in (loi, getattr(loi, "response", None)):
        for ten in TEN_TRUONG_MA_HTTP:
            ma = getattr(doi_tuong, ten, None)
            if isinstance(ma, bool):
                continue
            if isinstance(ma, int):
                return ma
            # `code` của nhiều SDK là chuỗi ("429"); một chuỗi không phải số thì
            # bỏ qua chứ không nổ, vì `code` cũng hay mang tên lỗi ("timeout").
            if isinstance(ma, str) and ma.strip().isdigit():
                return int(ma.strip())
    return None


# Lỗi mạng tạm thời: kết nối bị reset, timeout đọc, DNS trượt. Chúng **không**
# mang mã HTTP nào - lời gọi chưa bao giờ tới được tầng HTTP - nên luật "chỉ thử
# lại khi có mã 429/5xx" bỏ sót trọn nhóm này, và một trục trặc mạng thoáng qua
# giết cả một đợt đã trả tiền được nửa. Bắt theo kiểu chuẩn của stdlib chứ không
# theo tên lớp SDK: `httpx.ConnectError` và `openai.APIConnectionError` đều bọc
# một `OSError` hoặc một `TimeoutError`.
LOI_MANG_TAM_THOI: tuple[type[BaseException], ...] = (
    ConnectionError,  # gồm ConnectionReset/Aborted/Refused
    TimeoutError,  # gồm asyncio.TimeoutError từ Python 3.11
    socket.gaierror,  # DNS trượt
    socket.timeout,  # bí danh của TimeoutError, giữ cho rõ ý
)


def la_loi_mang_tam_thoi(loi: BaseException) -> bool:
    """Lỗi mạng thoáng qua, kể cả khi nó bị SDK bọc trong `__cause__`.

    Duyệt cả chuỗi nguyên nhân: `openai.APIConnectionError` không phải
    `OSError`, nhưng `raise ... from` giữ `ConnectionResetError` gốc ở
    `__cause__`, và đó là chỗ duy nhất đọc được mà không import SDK.
    """
    da_qua: set[int] = set()
    hien_tai: BaseException | None = loi
    while hien_tai is not None and id(hien_tai) not in da_qua:
        da_qua.add(id(hien_tai))
        if isinstance(hien_tai, LOI_MANG_TAM_THOI):
            return True
        hien_tai = hien_tai.__cause__ or hien_tai.__context__
    return False


def nen_thu_lai(loi: BaseException) -> bool:
    """429, 5xx và lỗi mạng tạm thời đáng thử lại; 4xx khác thì không.

    Một 400 vì prompt sai hay 401 vì key sai lặp lại y nguyên ở lần thử thứ
    hai, nên thử lại chỉ làm người chạy chờ lâu hơn để nhận cùng một lỗi.
    """
    if isinstance(loi, asyncio.CancelledError):
        return False
    ma = ma_http_cua(loi)
    if ma is not None:
        return ma in MA_DANG_THU_LAI or 500 <= ma < 600
    return la_loi_mang_tam_thoi(loi)


def giay_cho_lai(loi: BaseException) -> float | None:
    """`Retry-After` của provider, tính bằng giây; không có hay xấu thì `None`.

    Chỉ nhận dạng số giây. Dạng ngày HTTP cũng hợp lệ theo RFC nhưng phân tích
    nó cần biết lệch đồng hồ giữa hai máy, và đoán sai chiều thì hoặc chờ vô
    ích hàng giờ, hoặc gọi lại ngay và ăn tiếp một 429.
    """
    phan_hoi = getattr(loi, "response", None)
    headers = getattr(phan_hoi, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        giay = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(giay) or giay < 0:
        return None
    return giay


class ChanNhipQuaLau(RuntimeError):
    """Provider đòi chờ lâu hơn trần; đợt bỏ cuộc thay vì thử lại sớm.

    Kẹp `Retry-After` xuống trần rồi thử lại ngay là điều tệ hơn cả không thử
    lại: bốn lần thử đốt hết trong ba phút vào một endpoint còn đang chặn, nên
    đợt vừa hỏng vừa làm cửa sổ chặn dài thêm.

    `code` ổn định để test và CLI assert trên `code` (AD-8).
    """

    code = "CHAN_NHIP_QUA_LAU"


# Biên độ jitter cộng vào mỗi lần lùi lũy thừa, tính bằng giây.
#
# **Không có jitter là một lỗi, không phải một thiếu tinh chỉnh.**
# `adapters/trich_xuat._trich_mot_chunk` chạy song song dưới một `TaskGroup`,
# nên khi provider chặn nhịp thì *mọi* chunk đang bay cùng ăn 429 trong cùng
# một khoảnh khắc, cùng tính ra cùng một thời gian chờ, rồi cùng gọi lại đúng
# lúc - tức chúng tự tái tạo đúng cái burst vừa bị chặn. Jitter phá pha đó.
#
# Cộng chứ không nhân: `Retry-After` của provider (khi có) vẫn được tôn trọng
# nguyên vẹn ở nhánh trên của `cho_bao_lau`, jitter chỉ áp cho nhánh lùi lũy
# thừa - nhánh mà hệ tự đoán thời gian chờ.
BIEN_DO_JITTER_GIAY: float = 3.0

# --- Ngân sách: hai đường gọi, hai bộ số ---------------------------------------
#
# **Một con số chung cho hai đường là sai theo cả hai chiều** (story 3.3). Đường
# nạp và đường truy hồi dùng chung `bo_embedding`, nhưng chúng chờ được những
# khoảng thời gian khác hẳn nhau: một đợt nạp Qwen cục bộ sinh 5,7 token mỗi
# giây nên một lời gọi *hợp lệ* dài tới vài phút, còn đường truy hồi thì có
# người ngồi chờ. Một trần chung hoặc cắt nhầm đợt cục bộ, hoặc để một request
# HTTP treo ba phút trước khi trả lỗi.
#
# Nên ngân sách là một **giá trị có tên**, tiêm ở nơi dựng hàm, chứ không phải
# một hằng của module mà cả hai đường phải chịu chung.

# Trần cho **một** lời gọi của đường nạp. Không có trần thì một socket treo
# (không đứt, chỉ không trả byte nào) giữ cả đợt đứng mà không in dòng nào -
# triệu chứng khó đọc nhất, vì nó nhìn giống một đợt đang chạy. `SO_LAN_THU` và
# `TRAN_CHO_GIAY` **không** che ca này: chúng đo thời gian *giữa* hai lần thử.
TRAN_MOT_LOI_GOI_NAP_GIAY: float = 600.0

# Ba số của đường truy hồi. Chúng nhỏ hơn hẳn đường nạp vì đơn vị đo khác: một
# đợt nạp đo bằng giờ và mất cả đợt là mất tiền thật, còn một câu hỏi đo bằng
# giây và người hỏi đã bỏ đi từ giây thứ mười.
SO_LAN_THU_TRUY_HOI: int = 2
TRAN_CHO_TRUY_HOI_GIAY: float = 2.0
TRAN_MOT_LOI_GOI_TRUY_HOI_GIAY: float = 20.0
# Trần cho một lời gọi **LLM** của đường truy hồi. Tách khỏi trần trên vì hai
# lời gọi khác nhau: embedding là một request ngắn có lớp thử lại, còn lời gọi
# sinh câu trả lời của `kg_query` sinh hàng trăm token và **không** có lớp thử
# lại nào (luật "đúng một lớp trên mỗi đường gọi": `bo_llm` cố ý không bọc, và
# nơi gọi nằm trong `vendor/kg_query` nên không có chỗ nào khác để gắn).
TRAN_LLM_TRUY_HOI_GIAY: float = 60.0


@dataclass(frozen=True)
class NganSachThuLai:
    """Ngân sách của **một** đường gọi: thử mấy lần, chờ bao lâu, trần mỗi lời gọi.

    Bốn số đi cùng nhau vì chúng chỉ đọc được cùng nhau: "2 lần thử" không nói
    gì nếu trần chờ là 60 giây, và một trần cho một lời gọi không nói gì nếu số
    lần thử là 4. Đóng băng vì một ngân sách đổi giữa chừng là hai lời gọi của
    cùng một đường chạy dưới hai luật khác nhau.

    `tran_moi_loi_goi_giay` là trần cho **một** lần thử trong `goi_co_thu_lai`;
    `tran_llm_giay` là trần cho một lời gọi LLM **không** có lớp thử lại, và nó
    là `None` ở đường nạp vì đường đó đã có trần ở lớp thử lại của
    `adapters/trich_xuat._trich_mot_chunk` - hai lớp timeout lồng nhau trên cùng
    một lời gọi là hai chỗ để đọc sai nguyên nhân một lần cắt.
    """

    ten: str
    so_lan_thu: int
    tran_cho_giay: float
    tran_moi_loi_goi_giay: float | None = None
    tran_llm_giay: float | None = None

    def __post_init__(self):
        if not isinstance(self.ten, str) or not self.ten.strip():
            raise ValueError("ngân sách phải có tên: nó đi vào thông điệp thử lại")
        # `isinstance(True, int)` đúng và `True >= 1`, nên không chặn `bool` ở
        # đây là nhận `so_lan_thu=True` thành một ngân sách **một lần thử** mà
        # người viết tưởng mình đã bật một cờ. Ba trường số thực dưới đã chặn.
        if (
            isinstance(self.so_lan_thu, bool)
            or not isinstance(self.so_lan_thu, int)
            or self.so_lan_thu < 1
        ):
            raise ValueError(
                f"so_lan_thu = {self.so_lan_thu!r}: phải là số nguyên >= 1 (lần"
                " đầu cũng tính là một lần thử)"
            )
        for ten, gia_tri, cho_none in (
            ("tran_cho_giay", self.tran_cho_giay, False),
            ("tran_moi_loi_goi_giay", self.tran_moi_loi_goi_giay, True),
            ("tran_llm_giay", self.tran_llm_giay, True),
        ):
            if gia_tri is None and cho_none:
                continue
            if not isinstance(gia_tri, (int, float)) or isinstance(gia_tri, bool):
                raise TypeError(f"{ten} phải là số giây, nhận được {gia_tri!r}")
            if not math.isfinite(gia_tri) or gia_tri <= 0:
                raise ValueError(f"{ten} = {gia_tri!r}: phải là số giây dương hữu hạn")


# Ngân sách của đường **nạp**. Hai số đầu là hai hằng mà sáu đợt nạp đã trả tiền
# chạy dưới, nên chúng không đổi; số thứ ba là trần mới của story 3.3.
NGAN_SACH_NAP: NganSachThuLai = NganSachThuLai(
    ten="nạp",
    so_lan_thu=SO_LAN_THU,
    tran_cho_giay=TRAN_CHO_GIAY,
    tran_moi_loi_goi_giay=TRAN_MOT_LOI_GOI_NAP_GIAY,
    tran_llm_giay=None,
)

# Ngân sách của đường **truy hồi** (story 3.3). Trần của **một lời gọi**, không
# phải của một request: một request gọi LLM và embedding mấy lần là chuyện của
# `vendor/kg_query`, và module này không biết - nên con số cho một request suy
# ở `api/hoi_dap.py::tran_mot_truy_van_giay`, từ số lời gọi thật, chứ không
# viết tay ở đây. (Bản đầu của story 3.3 viết "khoảng 160 giây" ngay chỗ này và
# nó sai: nó đếm một lời gọi embedding mỗi request, trong khi hybrid gọi
# `entities_vdb.query` **và** `hyperedges_vdb.query`.) Đó là **trần**, không
# phải kỳ vọng: NFR-08 cố ý không đặt SLA cứng.
NGAN_SACH_TRUY_HOI: NganSachThuLai = NganSachThuLai(
    ten="truy hồi",
    so_lan_thu=SO_LAN_THU_TRUY_HOI,
    tran_cho_giay=TRAN_CHO_TRUY_HOI_GIAY,
    tran_moi_loi_goi_giay=TRAN_MOT_LOI_GOI_TRUY_HOI_GIAY,
    tran_llm_giay=TRAN_LLM_TRUY_HOI_GIAY,
)


def _lui_luy_thua(tran_cho_giay: float):
    """Bộ lùi lũy thừa có jitter, và **tổng của nó nằm trong `tran_cho_giay`**.

    Jitter phải nằm *trong* ngân sách chứ không cộng thêm bên ngoài, và bản đầu
    của story 3.3 làm sai đúng chỗ đó: với `tran_cho_giay = 2` thì
    `wait_exponential(max=2) + wait_random(0, 3)` ngủ tới 5 giây, trong khi
    `cho_bao_lau` của cùng module dội `ChanNhipQuaLau` khi provider **xin** 3
    giây vì "quá trần 2 giây". Một module vừa từ chối chờ 3 giây vừa tự ngủ 5
    giây thì trần nó khai không phải là trần nó giữ - và dấu hiệu là bộ test
    phải nới thành `<= tran + BIEN_DO_JITTER_GIAY` mới qua.

    Nên biên độ jitter cắt theo trần: nhiều nhất `BIEN_DO_JITTER_GIAY`, và
    nhiều nhất một nửa trần khi trần nhỏ hơn thế (giữ lại một nửa cho phần lùi
    lũy thừa, nếu không thì với trần nhỏ mọi lần chờ gần như thuần ngẫu nhiên).
    Phần lũy thừa lấy nốt chỗ còn lại, nên tổng luôn `<= tran_cho_giay`.

    **Không cache.** Bản đầu nhớ theo trần trong một dict cấp module không
    chặn, không khóa, không có phép loại bỏ - và nó nói mình bảo vệ đường nóng
    trong khi `goi_co_thu_lai` vẫn cấp phát một lambda mới mỗi lời gọi ngay
    cạnh đó. Hai quyết định cãi nhau, và số ngân sách của cả hệ đếm trên đầu
    ngón tay: dựng lại một object không trạng thái ở mỗi *lần thử lại* (không
    phải mỗi lời gọi) rẻ hơn hẳn một cache không ai dọn.
    """
    bien_do = min(BIEN_DO_JITTER_GIAY, tran_cho_giay / 2)
    return wait_exponential(
        multiplier=1, min=0, max=tran_cho_giay - bien_do
    ) + wait_random(0, bien_do)


def cho_bao_lau(retry_state, ngan_sach: NganSachThuLai = NGAN_SACH_NAP) -> float:
    """Chờ theo `Retry-After` nếu provider nói, không thì lùi lũy thừa.

    `ngan_sach` mặc định là đường nạp để chữ ký cũ (một tham số) còn gọi được;
    `goi_co_thu_lai` luôn truyền tường minh ngân sách của chính đường gọi.

    Giá trị trả về **không bao giờ vượt `tran_cho_giay`**, cả ở nhánh
    `Retry-After` (quá trần là `ChanNhipQuaLau`, không kẹp xuống rồi thử sớm)
    lẫn ở nhánh tự đoán.
    """
    tran = ngan_sach.tran_cho_giay
    loi = retry_state.outcome.exception() if retry_state.outcome else None
    giay = giay_cho_lai(loi) if loi is not None else None
    if giay is not None:
        if giay > tran:
            raise ChanNhipQuaLau(
                f"provider đòi chờ {giay:.0f} giây, quá trần {tran:.0f} giây"
                f" của ngân sách {ngan_sach.ten!r}. Không thử lại sớm hơn: chờ"
                " ngắn hơn provider yêu cầu chỉ ăn tiếp một lần chặn nhịp. Chạy"
                " lại sau khi cửa sổ chặn hết; phần đã trả tiền vẫn nằm trong"
                " `audit_log`."
            ) from loi
        return giay
    return _lui_luy_thua(tran)(retry_state)


# Keyword điều khiển **đã bỏ** ở story 3.3, và tên thay thế của chúng. Không có
# bảng này thì một nơi gọi cũ truyền `_so_lan_thu=1` bị `**tham_so` nuốt rồi
# **đẩy thẳng xuống provider** - đúng cái mà quy ước tiền tố gạch dưới sinh ra
# để chặn, chỉ khác là lần này chính module tự mở cửa cho nó khi đổi chữ ký.
#
# Chỉ tên **có gạch dưới** nằm ở đây. `so_lan_thu` trần thì không, và đó là một
# phân biệt có nội dung: nó chưa bao giờ là tham số điều khiển của hàm này, nó
# là một keyword của provider và `test_tham_so_dieu_khien_khong_nuot_kwarg_cua_provider`
# chứng minh nó đi thẳng xuống. Tên trần của *lớp trên* (`eval.do_trich_xuat`)
# có bảng riêng của nó, vì ở đó nó thật sự là một tham số điều khiển vừa bị bỏ.
TEN_DA_BO: dict[str, str] = {
    "_so_lan_thu": "_ngan_sach (adapters.thu_lai.NganSachThuLai)",
    "_tran_cho_giay": "_ngan_sach (adapters.thu_lai.NganSachThuLai)",
}


def tu_choi_ten_da_bo(tham_so: dict, bang: dict[str, str]) -> None:
    """Từ chối keyword điều khiển đã bỏ thay vì để nó trôi xuống provider.

    Public và nhận bảng tiêm vào: `eval/do_trich_xuat.py` bỏ một tên **trần**
    (`so_lan_thu`) nên nó có bảng riêng, nhưng phép từ chối thì chỉ có một bản.
    """
    for ten, thay_bang in bang.items():
        if ten in tham_so:
            raise TypeError(
                f"tham số {ten!r} đã bỏ ở story 3.3; dùng {thay_bang} thay cho"
                " nó. Không nhận im lặng: mọi keyword lạ của hàm này đi thẳng"
                " xuống provider."
            )


async def goi_mot_lan_co_tran(
    ham: Callable[..., Awaitable[Any]],
    *tham_so_vi_tri,
    _tran_giay: float | None = None,
    **tham_so,
):
    """Gọi `ham` một lần, cắt ở `_tran_giay`; `None` là không cắt.

    Trần cho **một** lời gọi, khác hẳn `TRAN_CHO_GIAY` - thứ đo thời gian *giữa*
    hai lần thử. Một socket treo không đứt và không trả byte nào không chạm tới
    lớp thử lại, nên không có hàm này thì nó giữ cả đợt đứng vô hạn.

    Quá hạn dội `TimeoutError`, thứ `nen_thu_lai` đã coi là đáng thử lại: một
    lời gọi treo là ứng viên tốt nhất cho một lần thử lại.

    `_tran_giay` mang tiền tố gạch dưới vì cùng lý do với bốn tham số điều
    khiển của `goi_co_thu_lai`: hàm này nằm trên đúng đường chuyển tiếp mà quy
    ước đó sinh ra để bảo vệ, và mọi keyword khác đi thẳng xuống provider. Một
    tên trần `tran_giay` là một tham số provider trùng tên bị wrapper nuốt lặng
    lẽ. Nó cũng **keyword-only**: một tham số vị trí thứ hai là một tham số vị
    trí của provider bị ăn mất.
    """
    if _tran_giay is None:
        return await ham(*tham_so_vi_tri, **tham_so)
    async with asyncio.timeout(_tran_giay):
        return await ham(*tham_so_vi_tri, **tham_so)


async def goi_co_thu_lai(
    ham: Callable[..., Awaitable[Any]],
    *tham_so_vi_tri,
    _ngan_sach: NganSachThuLai = NGAN_SACH_NAP,
    _sleep=None,
    _in_ra=None,
    _ten: str = "lời gọi",
    **tham_so,
):
    """Gọi `ham`, thử lại đúng 408/425/429/5xx/lỗi mạng, ném nguyên lỗi cuối cùng.

    Ném nguyên lỗi (`reraise=True`) chứ không bọc thành `RetryError`: nơi gọi
    đang bắt theo loại lỗi thật, và một `RetryError` che mất mã HTTP là che mất
    thứ duy nhất nói được vì sao đợt dừng.

    Lời gọi hỏng **không** ghi sự kiện chi phí (wrapper chỉ ghi khi thành công),
    nên mọi mốc `audit.moc()` chụp trước vòng thử lại vẫn neo đúng một sự kiện
    của lần thử thành công.

    **Bốn tham số điều khiển mang tiền tố gạch dưới, và đó không phải quy ước
    thẩm mỹ.** Mọi keyword khác đi thẳng xuống `ham`, tức xuống provider. Đặt
    tên chúng là `ten`, `sleep`, `in_ra`, `ngan_sach` thì một provider có tham
    số trùng tên - `stream`, `timeout`, `stop` đều là tên thật của OpenAI API và
    `sleep` không phải một cái tên xa lạ - sẽ bị wrapper **nuốt lặng lẽ**: lời
    gọi đi với cấu hình khác cấu hình người viết ghi ra, không lỗi, không dấu
    hiệu. Tiền tố gạch dưới đóng cửa đó bằng chính không gian tên: không API
    provider nào đặt tên tham số bắt đầu bằng `_`.

    `_ngan_sach` gộp cả ba số của một đường gọi (số lần thử, trần chờ giữa hai
    lần, trần cho một lời gọi) thành **một** giá trị có tên, thay cho `_so_lan_thu`
    trần của story 2.13: đường nạp và đường truy hồi chờ được những khoảng thời
    gian khác hẳn nhau, và ba tham số rời nhau là ba chỗ để một nơi gọi truyền
    hai số của đường này cộng một số của đường kia.

    `_sleep=` và `_in_ra=` là điểm tiêm cho test: không ngủ thật, không in thật.
    """
    tu_choi_ten_da_bo(tham_so, TEN_DA_BO)
    lan = 0
    async for thu in AsyncRetrying(
        stop=stop_after_attempt(_ngan_sach.so_lan_thu),
        wait=lambda trang_thai: cho_bao_lau(trang_thai, _ngan_sach),
        retry=retry_if_exception(nen_thu_lai),
        reraise=True,
        **({"sleep": _sleep} if _sleep is not None else {}),
    ):
        with thu:
            lan += 1
            if lan > 1 and _in_ra is not None:
                _in_ra(
                    f"    thử lại {_ten} lần {lan}/{_ngan_sach.so_lan_thu}", flush=True
                )
            return await goi_mot_lan_co_tran(
                ham,
                *tham_so_vi_tri,
                _tran_giay=_ngan_sach.tran_moi_loi_goi_giay,
                **tham_so,
            )
    raise AssertionError("AsyncRetrying thoát mà không trả kết quả và không ném")
