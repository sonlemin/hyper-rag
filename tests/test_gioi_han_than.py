"""Trần thân request ở tầng ASGI (story 3.8, ADR-022, khoản ledger 3.3).

Ba hàng của I/O Matrix: thân quá lớn có `Content-Length` là 413 mà handler
không chạy; thân chunked (không header) vượt trần cũng 413 khi đọc; thân dưới
trần đi qua và gặp đúng trần theo ký tự của tuyến (`CAU_HOI_QUA_DAI`). Cộng ca
gắn thật vào `api.main.app` và ca hàm thuần đọc header.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api.gioi_han_than import (
    MA_THAN_QUA_LON,
    TRAN_THAN_BYTE,
    GioiHanThan,
    doc_content_length,
    than_413,
)
from api.hoi_dap import DAI_CAU_HOI_TOI_DA, MA_CAU_HOI_QUA_DAI
from api.xac_thuc import BIEN_KHOA_KY
from tests.test_hoi_dap import KHOA_TEST, _bearer
from tests.test_xac_thuc import AuditGia, EngineGia, KhoGia, _dong


def test_doc_content_length_ba_dang():
    assert doc_content_length([(b"content-length", b"12")]) == 12
    assert doc_content_length([(b"Content-Length", b" 7 ")]) == 7
    assert doc_content_length([(b"content-length", b"abc")]) is None
    assert doc_content_length([(b"content-length", b"-1")]) is None
    assert doc_content_length([(b"x", b"1")]) is None


def test_than_413_la_envelope_dong():
    than = json.loads(than_413())
    assert set(than) == {"error"} and set(than["error"]) == {"code", "message"}
    assert than["error"]["code"] == MA_THAN_QUA_LON
    assert str(TRAN_THAN_BYTE) in than["error"]["message"]


def test_tran_phai_la_so_nguyen_duong():
    for xau in (0, -1, True, "64"):
        with pytest.raises(ValueError):
            GioiHanThan(lambda *a: None, tran_byte=xau)


# --- Middleware thuần trên một app ASGI giả -----------------------------------


def _chay(app, headers, body_chunks):
    """Chạy một request HTTP qua middleware với thân cắt thành nhiều `http.request`."""
    da_gui = []
    da_goi_app = []

    async def app_trong(scope, receive, send):
        da_goi_app.append(scope["path"])
        tong = b""
        while True:
            m = await receive()
            tong += m.get("body", b"")
            if not m.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": str(len(tong)).encode()})

    mw = app if isinstance(app, GioiHanThan) else GioiHanThan(app_trong, tran_byte=app)
    if not isinstance(app, GioiHanThan):
        mw.app = app_trong
    chunks = list(body_chunks)

    async def receive():
        body = chunks.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(chunks)}

    async def send(m):
        da_gui.append(m)

    scope = {"type": "http", "method": "POST", "path": "/x", "headers": headers}
    asyncio.run(mw(scope, receive, send))
    return da_gui, da_goi_app


def test_content_length_qua_tran_la_413_va_app_khong_chay():
    """Hàng "Thân quá lớn có Content-Length": 413 ngay, không đọc một byte thân."""
    da_gui, da_goi_app = _chay(10, [(b"content-length", b"11")], [b"x" * 11])
    assert da_goi_app == []
    assert da_gui[0]["status"] == 413
    assert json.loads(da_gui[1]["body"])["error"]["code"] == MA_THAN_QUA_LON


def test_chunked_vuot_tran_giua_luc_doc_la_413():
    """Hàng "Thân quá lớn chunked": không header, đếm byte, vượt trần là 413."""
    da_gui, da_goi_app = _chay(10, [], [b"x" * 6, b"y" * 6])
    assert da_goi_app == ["/x"], "app được gọi, và nó là chỗ dội ra khi đọc"
    assert da_gui[0]["status"] == 413


def test_header_noi_doi_nho_hon_that_van_bi_dem_byte():
    da_gui, _ = _chay(10, [(b"content-length", b"3")], [b"x" * 20])
    assert da_gui[0]["status"] == 413


def test_than_duoi_tran_di_qua_nguyen_ven():
    da_gui, da_goi_app = _chay(10, [(b"content-length", b"9")], [b"x" * 4, b"y" * 5])
    assert da_goi_app == ["/x"]
    assert da_gui[0]["status"] == 200 and da_gui[1]["body"] == b"9"


def test_scope_khong_phai_http_di_thang():
    goi = []

    async def app_trong(scope, receive, send):
        goi.append(scope["type"])

    asyncio.run(GioiHanThan(app_trong)({"type": "lifespan"}, None, None))
    assert goi == ["lifespan"]


# --- Gắn thật vào api.main.app ---------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    kho = KhoGia({"TS01": _dong("ts01")})
    engine = EngineGia()

    async def _mo_kho():
        return kho

    async def _mo_audit():
        return AuditGia()

    async def _mo_engine(audit):
        return engine

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        yield c, engine


def test_app_that_than_qua_tran_ra_413_truoc_handler_va_truoc_xac_thuc(client):
    c, engine = client
    than = json.dumps({"cau_hoi": "x" * (TRAN_THAN_BYTE + 100)})
    kq = c.post("/hoi-dap", content=than, headers={"content-type": "application/json"})
    assert kq.status_code == 413
    assert kq.json()["error"]["code"] == MA_THAN_QUA_LON
    assert engine.cau_hoi == []


def test_app_that_than_duoi_tran_gap_dung_tran_ky_tu(client):
    """Hàng "Thân dưới trần": 4001 ký tự qua middleware, rồi 400 `CAU_HOI_QUA_DAI` như cũ."""
    c, engine = client
    kq = c.post(
        "/hoi-dap",
        json={"cau_hoi": "a" * (DAI_CAU_HOI_TOI_DA + 1)},
        headers=_bearer(c, "ts01"),
    )
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == MA_CAU_HOI_QUA_DAI
    assert engine.cau_hoi == []


def test_app_that_gan_dung_mot_lop_middleware():
    ten = [m.cls.__name__ for m in api_main.app.user_middleware]
    assert ten.count("GioiHanThan") == 1


# --- Cửa hai trên app thật (vòng review 3.8) ------------------------------------
#
# FastAPI đọc thân dưới `except Exception` -> 400 "error parsing the body"; bản
# đầu của middleware dội một `Exception` trần từ `receive` nên trên app thật
# cửa hai ra 400 `TUYEN_KHONG_CO`, và mọi ca app thật trước đó đều có
# `Content-Length` (TestClient tự đặt) nên chỉ chấm cửa một. Ba ca dưới gửi
# thân **chunked** (generator) hoặc header nói dối thẳng vào `api_main.app`.


def _chunked(n: int):
    def _sinh():
        yield b'{"cau_hoi": "'
        yield b"a" * n
        yield b'"}'
    return _sinh()


def test_app_that_chunked_vuot_tran_ra_413_tren_tuyen_pydantic(client):
    """Hàng "Thân quá lớn chunked" trên `/hoi-dap` thật: 413 `THAN_QUA_LON`, không phải 400."""
    c, engine = client
    kq = c.post(
        "/hoi-dap", content=_chunked(TRAN_THAN_BYTE + 100),
        headers={**_bearer(c, "ts01"), "content-type": "application/json", "transfer-encoding": "chunked"},
    )
    assert kq.status_code == 413, kq.text
    assert kq.json()["error"]["code"] == MA_THAN_QUA_LON
    assert engine.cau_hoi == []


def test_app_that_chunked_vuot_tran_tren_tuyen_doc_tay_login(client):
    """`dang_nhap` đọc thân bằng tay trong `try/except Exception`: phải để 413 đi qua, không nuốt thành 401."""
    c, _ = client
    kq = c.post(
        "/auth/login", content=_chunked(TRAN_THAN_BYTE + 100),
        headers={"content-type": "application/json", "transfer-encoding": "chunked"},
    )
    assert kq.status_code == 413, kq.text
    assert kq.json()["error"]["code"] == MA_THAN_QUA_LON


@pytest.mark.parametrize("duong", ["/do-thi", "/break-glass/yeu-cau", "/admin/policy"])
def test_app_that_tran_phu_moi_tuyen(client, duong):
    c, _ = client
    kq = c.post(duong, content=b"x" * (TRAN_THAN_BYTE + 1), headers={**_bearer(c, "ts01"), "content-type": "application/json"})
    assert kq.status_code == 413 and kq.json()["error"]["code"] == MA_THAN_QUA_LON


def test_app_that_header_noi_doi_nho_hon_than_van_413():
    """Gọi thẳng ASGI với `content-length: 3` mà thân 70 KB: cửa hai đếm byte và ra 413."""
    da_gui = []
    than = b"x" * (TRAN_THAN_BYTE + 100)
    chunks = [than[: len(than) // 2], than[len(than) // 2 :]]

    async def receive():
        return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}

    async def send(m):
        da_gui.append(m)

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/auth/login", "raw_path": b"/auth/login", "query_string": b"", "root_path": "",
        "headers": [(b"content-length", b"3"), (b"content-type", b"application/json"), (b"host", b"t")],
        "client": ("127.0.0.1", 1), "server": ("t", 80), "app": api_main.app,
    }
    asyncio.run(api_main.app(scope, receive, send))
    assert da_gui[0]["status"] == 413
    assert json.loads(da_gui[1]["body"])["error"]["code"] == MA_THAN_QUA_LON
