"""Trần kích thước thân request ở tầng ASGI (story 3.8, ADR-022, khoản ledger 3.3).

Trước story này mọi trần của một thân request nằm **sau** khi pydantic đã dựng
xong nó trong bộ nhớ: `api/hoi_dap.py::kiem_cau_hoi` (4000 ký tự) chạy trong
thân handler, `api/break_glass.py::kiem_ly_do` cũng vậy, và nắp `max_length`
trên field pydantic chỉ chặn sau khi cả thân đã được đọc và giải mã. Một
`cau_hoi` vài megabyte được nhận trọn vẹn rồi mới bị từ chối bằng
`CAU_HOI_QUA_DAI`. Khoản ledger 3.3 (mở rộng ở 5.1, 5.2) đòi **một** trần ở
tầng vận chuyển phủ cả `/hoi-dap`, `/do-thi` và bảy tuyến break-glass cùng lúc:
đặt riêng từng endpoint là nhiều bản của một luật.

**Middleware ASGI thuần, không `BaseHTTPMiddleware`.** `BaseHTTPMiddleware` của
Starlette đọc cả thân vào bộ nhớ để dựng `Request` trước khi gọi tiếp, tức nó
làm đúng việc mà module này tồn tại để chặn. Ở đây có hai cửa, theo thứ tự:

1. Header `content-length` lớn hơn trần -> 413 ngay, handler không chạy, không
   đọc một byte thân nào.
2. Không header (chunked) hay header nói dối -> bọc `receive` và **đếm byte**;
   vượt trần giữa lúc đọc thì dội `ThanQuaLon`, middleware bắt lại và trả 413
   nếu response chưa bắt đầu.

Thân 413 là envelope `{error: {code, message}}` đúng Consistency Conventions,
mã `THAN_QUA_LON`, thông điệp cố định (không dội lại kích thước người gọi gửi
ngoài con số trần). Trần 64 KB: thân lớn nhất hợp lệ của hệ là `POST /do-thi`
với 200 id `he-` + 24 hex (~7 KB), và `POST /hoi-dap` với 4000 ký tự UTF-8
tiếng Việt (~12 KB); 64 KB gấp năm lần thân hợp lệ lớn nhất nên không tuyến nào
đang có bị chạm, và mọi trần theo ký tự phía sau vẫn chạy như cũ.

Gắn ở `api/main.py` bằng `app.add_middleware(GioiHanThan)`: nó đứng **trong**
`ServerErrorMiddleware` và **ngoài** `ExceptionMiddleware` của Starlette.
`ThanQuaLon` dội từ `receive` là một `HTTPException(413)` (xem docstring lớp),
nên trên app thật nó được `ExceptionMiddleware` giao cho handler
`api.main._tuyen_khong_co` và ra thân `than_413()` từ đó; nhánh bắt ở
`__call__` chỉ còn phục vụ app ASGI trần không có handler. Không gắn vào `api/man_nap.py`:
màn tải file lên là đường ghi hợp lệ hàng megabyte, sống sau loopback cộng SSH
tunnel (ADR-022 quyết định 4), và trần cho nó là một quyết định khác.

Module chỉ stdlib cộng kiểu của Starlette qua duck typing: không import
`fastapi`, không chạm kho, không dựng ngữ cảnh quyền.
"""

import json
from typing import Awaitable, Callable, MutableMapping

from starlette.exceptions import HTTPException as StarletteHTTPException

# Trần thân request, byte. Hằng module, không phải biến môi trường: một trần an
# ninh đọc từ môi trường là một trần đổi được mà không ai xem lại diff (cùng
# luật với TTL token ở `api/xac_thuc.py`).
TRAN_THAN_BYTE: int = 65536

MA_THAN_QUA_LON: str = "THAN_QUA_LON"
THONG_DIEP_THAN_QUA_LON: str = f"thân yêu cầu vượt trần {TRAN_THAN_BYTE} byte"

Scope = MutableMapping[str, object]
Receive = Callable[[], Awaitable[MutableMapping[str, object]]]
Send = Callable[[MutableMapping[str, object]], Awaitable[None]]


class ThanQuaLon(StarletteHTTPException):
    """Thân request vượt trần khi đang đọc (đường chunked hay header nói dối).

    Kế thừa `HTTPException` của Starlette **có chủ đích** (vòng review 3.8):
    FastAPI đọc thân trong `get_request_handler` dưới một `except Exception`
    đổi mọi ngoại lệ lạ thành `HTTPException(400, "error parsing the body")`,
    và chỉ cho `HTTPException` đi qua nguyên vẹn (`fastapi/routing.py`, nhánh
    `except HTTPException: raise`). Một `Exception` trần dội từ `receive` vì
    thế không bao giờ tới middleware trên app thật mà thành 400
    `TUYEN_KHONG_CO`. Là `HTTPException(413)` thì nó đi qua FastAPI, tới
    `ExceptionMiddleware` và handler `api.main._tuyen_khong_co`, nơi mã 413
    được ánh xạ thành thân `THAN_QUA_LON`. Handler đọc thân bằng tay
    (`request.json()` trong `try/except Exception`) phải `except ThanQuaLon:
    raise` trước nhánh nuốt.
    """

    code = MA_THAN_QUA_LON

    def __init__(self, chi_tiet: str):
        super().__init__(status_code=413, detail=chi_tiet)


def than_413() -> bytes:
    """Thân JSON của phản hồi 413, một bản cho cả hai cửa."""
    return json.dumps(
        {"error": {"code": MA_THAN_QUA_LON, "message": THONG_DIEP_THAN_QUA_LON}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def doc_content_length(headers) -> int | None:
    """Giá trị `content-length` nếu có và là số nguyên không âm; không thì `None`.

    Header hỏng (không phải số) coi như vắng: cửa hai vẫn đếm byte thật, nên một
    header nói dối theo chiều nào cũng không qua được trần.
    """
    for ten, gia_tri in headers:
        if ten.lower() == b"content-length":
            try:
                so = int(gia_tri.decode("latin-1").strip())
            except ValueError:
                return None
            return so if so >= 0 else None
    return None


class GioiHanThan:
    """Middleware ASGI: 413 khi thân request vượt `TRAN_THAN_BYTE`."""

    def __init__(self, app, tran_byte: int = TRAN_THAN_BYTE):
        if not isinstance(tran_byte, int) or isinstance(tran_byte, bool) or tran_byte <= 0:
            raise ValueError(f"tran_byte phải là số nguyên dương, nhận {tran_byte!r}")
        self.app = app
        self.tran_byte = tran_byte

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        khai = doc_content_length(scope.get("headers") or ())
        if khai is not None and khai > self.tran_byte:
            await self._gui_413(send)
            return

        da_gui_dau: list[bool] = [False]
        da_doc: list[int] = [0]

        async def receive_dem():
            thong_diep = await receive()
            if thong_diep.get("type") == "http.request":
                da_doc[0] += len(thong_diep.get("body") or b"")
                if da_doc[0] > self.tran_byte:
                    raise ThanQuaLon(
                        f"đã đọc {da_doc[0]} byte, trần {self.tran_byte}"
                    )
            return thong_diep

        async def send_theo_doi(thong_diep):
            if thong_diep.get("type") == "http.response.start":
                da_gui_dau[0] = True
            await send(thong_diep)

        try:
            await self.app(scope, receive_dem, send_theo_doi)
        except ThanQuaLon:
            if da_gui_dau[0]:
                # Response đã bắt đầu thì không đổi được mã nữa; dội lên cho
                # ServerErrorMiddleware đóng kết nối thay vì gửi một thân thứ hai.
                raise
            await self._gui_413(send)

    async def _gui_413(self, send: Send) -> None:
        than = than_413()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(than)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": than, "more_body": False})


__all__ = [
    "GioiHanThan",
    "MA_THAN_QUA_LON",
    "THONG_DIEP_THAN_QUA_LON",
    "TRAN_THAN_BYTE",
    "ThanQuaLon",
    "doc_content_length",
    "than_413",
]
