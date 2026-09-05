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
"""

import asyncio
import math
import socket
from typing import Any, Awaitable, Callable

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

__all__ = [
    "LOI_MANG_TAM_THOI",
    "MA_RATE_LIMIT",
    "SO_LAN_THU",
    "TEN_TRUONG_MA_HTTP",
    "TRAN_CHO_GIAY",
    "ChanNhipQuaLau",
    "cho_bao_lau",
    "giay_cho_lai",
    "goi_co_thu_lai",
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
        return ma == MA_RATE_LIMIT or 500 <= ma < 600
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


_LUI_LUY_THUA = wait_exponential(multiplier=1, min=1, max=TRAN_CHO_GIAY)


def cho_bao_lau(retry_state) -> float:
    """Chờ theo `Retry-After` nếu provider nói, không thì lùi lũy thừa."""
    loi = retry_state.outcome.exception() if retry_state.outcome else None
    giay = giay_cho_lai(loi) if loi is not None else None
    if giay is not None:
        if giay > TRAN_CHO_GIAY:
            raise ChanNhipQuaLau(
                f"provider đòi chờ {giay:.0f} giây, quá trần {TRAN_CHO_GIAY:.0f} giây"
                " của đợt. Không thử lại sớm hơn: chờ ngắn hơn provider yêu cầu"
                " chỉ ăn tiếp một lần chặn nhịp. Chạy lại sau khi cửa sổ chặn"
                " hết; phần đã trả tiền vẫn nằm trong `audit_log`."
            ) from loi
        return giay
    return _LUI_LUY_THUA(retry_state)


async def goi_co_thu_lai(
    ham: Callable[..., Awaitable[Any]],
    *tham_so_vi_tri,
    so_lan_thu: int = SO_LAN_THU,
    sleep=None,
    in_ra=None,
    ten: str = "lời gọi",
    **tham_so,
):
    """Gọi `ham`, thử lại đúng 429/5xx/lỗi mạng, ném nguyên lỗi cuối cùng.

    Ném nguyên lỗi (`reraise=True`) chứ không bọc thành `RetryError`: nơi gọi
    đang bắt theo loại lỗi thật, và một `RetryError` che mất mã HTTP là che mất
    thứ duy nhất nói được vì sao đợt dừng.

    Lời gọi hỏng **không** ghi sự kiện chi phí (wrapper chỉ ghi khi thành công),
    nên mọi mốc `audit.moc()` chụp trước vòng thử lại vẫn neo đúng một sự kiện
    của lần thử thành công.

    `sleep=` và `in_ra=` là điểm tiêm cho test: không ngủ thật, không in thật.
    """
    lan = 0
    async for thu in AsyncRetrying(
        stop=stop_after_attempt(so_lan_thu),
        wait=cho_bao_lau,
        retry=retry_if_exception(nen_thu_lai),
        reraise=True,
        **({"sleep": sleep} if sleep is not None else {}),
    ):
        with thu:
            lan += 1
            if lan > 1 and in_ra is not None:
                in_ra(f"    thử lại {ten} lần {lan}/{so_lan_thu}", flush=True)
            return await ham(*tham_so_vi_tri, **tham_so)
    raise AssertionError("AsyncRetrying thoát mà không trả kết quả và không ném")
