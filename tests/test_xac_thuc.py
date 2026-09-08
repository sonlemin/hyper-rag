"""Xác thực JWT và cửa quyền demo/admin (story 3.1, FR-17, FR-18 nền).

Sáu hàng I/O Matrix của story: đăng nhập đúng, tài khoản không tồn tại, mật
khẩu sai, token thiếu/hết hạn/sai chữ ký, tài khoản thường gọi API demo/admin,
và thiếu khóa ký thì từ chối khởi động.

Bộ test này **không cần Postgres**: bảng `users` được thay bằng một bản giả cài
qua `api.main.mo_kho_tai_khoan`, đúng khuôn mà `api.man_nap.mo_audit` đặt.
Đường Postgres thật có bộ riêng mang marker `postgres` ở cuối file.

Hai điều mà bộ này canh và không test nào khác canh được:

- **hai ca đăng nhập sai ra thân byte giống hệt nhau.** So bằng
  `response.content`, không so từng field: một thông điệp ghép tên tài khoản
  vào là đủ để liệt kê tài khoản nào có thật, và một phép so field sẽ không
  thấy điều đó.
- **`exp` cách `iat` đúng 12 giờ.** TTL là hằng trong `api/xac_thuc.py` chứ
  không phải biến môi trường, nên chỗ duy nhất nó sai được là code.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from adapters.identity_seed import IdentitySeedInvalid, nap_tai_khoan
from adapters.nhom_phu_trach import NhomPhuTrachInvalid
from api import main as api_main
from api.xac_thuc import (
    BIEN_KHOA_KY,
    HASH_GIA,
    TTL_GIO,
    ActClaim,
    ClaimNguoiHoi,
    JwtSecretMissing,
    LoiXacThuc,
    doi_demo_hoac_admin,
    doc_token,
    khoa_ky,
    phat_token,
    so_mat_khau,
    token_tu_header,
)

# Khóa ký của bộ test: đủ dài để qua cửa `DAI_KHOA_TOI_THIEU`, và cố ý không
# phải khóa thật của `.env` - một bộ test đọc khóa thật là một bộ test hỏng ở
# máy chưa có `.env`.
KHOA_TEST = "khoa-ky-cua-bo-test-" + "x" * 32

# Mật khẩu thô của hai tài khoản seed. Chúng sống ở `.env` gốc repo (đã
# gitignore) và **không** vào git, nên bộ test dựng seed giả của riêng nó thay
# vì đọc file thật: một test đọc mật khẩu thật là một test không chạy được ở
# máy vừa clone.
MAT_KHAU = "matkhau-cua-bo-test"


class KhoGia:
    """Bản giả của `api.tai_khoan.KhoTaiKhoan`: một dict trong bộ nhớ.

    Đủ hình dạng cho đường đăng nhập - `tra` trả `None` cho tài khoản lạ - và
    không hơn. Bảng thật có bộ test riêng mang marker `postgres`.

    `dong_bo` **giữ lại** danh sách nó nhận chứ không chỉ đếm: không giữ thì
    `dong_bo(())` trong lifespan là một đột biến mà cả bộ test không thấy, và
    hậu quả thật của nó là một container `healthy`, `/health` xanh, bảng `users`
    rỗng, còn triệu chứng duy nhất là mọi lần đăng nhập trả `DANG_NHAP_SAI` -
    đúng cái mã cố ý không nói ra ca nào.
    """

    def __init__(self, dong_theo_ten):
        self.theo_ten = dict(dong_theo_ten)
        self.da_dong_bo = 0
        self.muc_da_dong_bo = None
        self.da_dong = False
        self.no_o_dong_bo = None

    async def dong_bo(self, cac_muc=None):
        self.da_dong_bo += 1
        self.muc_da_dong_bo = tuple(cac_muc or ())
        if self.no_o_dong_bo is not None:
            raise self.no_o_dong_bo
        return len(self.muc_da_dong_bo)

    async def tra(self, account):
        return self.theo_ten.get(account)

    async def dong(self):
        self.da_dong = True


def _dong(account, *, role="tech_support", demo=False, admin=False, hash_mk=None):
    from api.tai_khoan import DongUser

    import bcrypt

    # `is None` chứ không `or`: ca đang cần chấm là **hash rỗng**, và một `or`
    # ở đây lặng lẽ thay chuỗi rỗng bằng một hash thật.
    if hash_mk is None:
        hash_mk = bcrypt.hashpw(MAT_KHAU.encode(), bcrypt.gensalt(rounds=4)).decode()
    return DongUser(
        account=account,
        mat_khau_hash=hash_mk,
        role=role,
        group_name="Tech Support",
        khong_gian="synth",
        demo=demo,
        admin=admin,
    )


# Tên gõ vào khi đăng nhập, và `account` mà bảng trả về. Hai chuỗi cố ý **khác
# nhau** (khác chữ hoa thường): nếu chúng bằng nhau thì đột biến `sub=ten` thay
# cho `sub=dong.account` không test nào phân biệt được, và `sub` là thứ audit
# ghi làm `real_account` (AD-3) cùng thứ Epic 4 chép sang token xem-như.
TEN_GO = {"ts01": "TS01", "dev01": "DEV01", "demo01": "DEMO01"}


@pytest.fixture
def kho_gia():
    """Ba tài khoản của seed thật, đủ ba tổ hợp cờ.

    `demo01` (demo mà **không** admin) vào ở story 4.5: nó là tài khoản duy
    nhất chứng minh được qua HTTP rằng cửa của ba tuyến xem như là phép **hoặc**
    chứ không phép **và**. Với hai tài khoản kia thì một đột biến đổi `or` thành
    `and` vẫn xanh, vì chúng chỉ phân biệt được "có cả hai" với "không có gì".
    """
    return KhoGia(
        {
            TEN_GO["ts01"]: _dong("ts01"),
            TEN_GO["dev01"]: _dong("dev01", role="devops", demo=True, admin=True),
            TEN_GO["demo01"]: _dong("demo01", role="tech_support", demo=True, admin=False),
        }
    )


class AuditGia:
    """Port audit giả: ghi vào một danh sách, hoặc dội nếu `no` được đặt.

    Cùng hình dạng tối thiểu của `core.audit.AuditPort` (một `ghi` async) cộng
    một `dong` để lifespan đóng được.
    """

    def __init__(self):
        self.su_kien = []
        self.no: BaseException | None = None
        self.da_dong = False

    async def ghi(self, su_kien):
        if self.no is not None:
            raise self.no
        self.su_kien.append(su_kien)

    async def dong(self):
        self.da_dong = True


@pytest.fixture
def audit_gia():
    return AuditGia()


class EngineGia:
    """Engine giả của lifespan: đủ để mở, đóng và trả lời một câu hỏi.

    Story 3.3 nối engine tri thức vào lifespan, nên mọi fixture chạy lifespan
    thật phải thay `api.hoi_dap.mo_engine` - bản thật đọc `LLM_MODEL`,
    `QDRANT_URL` và một API key từ môi trường, ba thứ mà bộ test cố ý không có
    (`tests/conftest.py::khong_key_provider_trong_moi_truong`).

    `cau_hoi` giữ lại mọi câu đã nhận: đó là cách ca "thân sai thì không có lời
    gọi nào" chứng minh được mệnh đề của nó.

    Story 3.5 làm engine mọc `hoi_dap`, cửa mà handler gọi từ nay, và bản giả
    phải điều khiển được **ba nhánh**: `ly_do=None` cho một lượt trả lời,
    `ly_do` mang một trong ba giá trị của `adapters.tra_loi` cho một lượt từ
    chối, và `loi` cho mọi ca hỏng (gồm cả `DauRaTraLoiKhongDoc`). `aquery` giữ
    nguyên vì `tests/ho_tro_m1.py::hoi` và `eval/` vẫn đi đường đó.

    `param` giữ lại tham số của từng lời gọi: đó là cách ca "handler không tự
    dựng `QueryParam`" đọc được vế của nó mà không phải thay method.

    `trich_dan` (story 3.4) là tuple `TrichDan` mà lượt trả lời mang; mặc định
    rỗng để mọi ca của 3.3/3.5 giữ nguyên kỳ vọng `citations: []`.

    `do_thi` (story 3.7) là `adapters.do_thi.DoThi` mà `POST /do-thi` trả;
    mặc định đồ thị rỗng. `ids` giữ lại danh sách id của từng lời gọi, và
    `ngu_canh` ghi ngữ cảnh đọc **bên trong** lời gọi như hai method kia.

    `trich_dan` theo id (story 5.1): `trich_dan_theo_id` trả `trich_dan_tra`,
    một dict `{id: TrichDan}` điều khiển được (mặc định rỗng, tức mọi id đều
    vô hình); `ids` và `ngu_canh` ghi lại như `do_thi`.

    `hyperedge_da_thay` (story 3.8): tập thấy mà lượt trả lời mang, thứ audit
    `query` ghi; `None` là "bằng dãy id của `trich_dan`" - đúng hành vi mà
    `KetQuaHoiDap` suy khi không ai khai, nên mọi ca cũ giữ nguyên kỳ vọng.
    """

    def __init__(
        self,
        tra_loi: str = "câu trả lời giả",
        loi: BaseException | None = None,
        ly_do: str | None = None,
        trich_dan: tuple = (),
        do_thi=None,
        trich_dan_tra: dict | None = None,
        hyperedge_da_thay: tuple | None = None,
    ):
        from adapters.do_thi import DoThi

        self.tra_loi = tra_loi
        self.loi = loi
        self.ly_do = ly_do
        self.trich_dan = trich_dan
        self.hyperedge_da_thay = hyperedge_da_thay
        self.do_thi_tra = DoThi() if do_thi is None else do_thi
        self.trich_dan_tra = {} if trich_dan_tra is None else dict(trich_dan_tra)
        # Story 5.2: lân cận một bước của từng id (chỉ dùng khi k > 0), và
        # nhật ký `(ids, k)` của từng lời gọi `vung_lan_can`.
        self.ke_can_tra: dict = {}
        self.vung: list = []
        self.ids: list = []
        self.cau_hoi: list[str] = []
        self.param: list = []
        self.ngu_canh: list = []
        self.da_dong = False

    def _ghi_lai(self, query, param) -> None:
        from core.permission import current_context

        self.cau_hoi.append(query)
        self.param.append(param)
        # Đọc ngữ cảnh **bên trong** lời gọi: đó là chỗ duy nhất chứng minh
        # `use_context` bọc trọn lời gọi thay vì chỉ bọc phần dựng.
        self.ngu_canh.append(current_context())

    async def aquery(self, query, param=None):
        self._ghi_lai(query, param)
        if self.loi is not None:
            raise self.loi
        return self.tra_loi

    async def hoi_dap(self, cau_hoi, param=None):
        from adapters.tra_loi import KetQuaHoiDap

        self._ghi_lai(cau_hoi, param)
        if self.loi is not None:
            raise self.loi
        if self.ly_do is not None:
            return KetQuaHoiDap(ly_do_tu_choi=self.ly_do)
        return KetQuaHoiDap(
            cau_tra_loi=self.tra_loi,
            trich_dan=self.trich_dan,
            hyperedge_da_thay=() if self.hyperedge_da_thay is None else tuple(self.hyperedge_da_thay),
        )

    async def do_thi(self, ids):
        from core.permission import current_context

        self.ids.append(list(ids))
        self.ngu_canh.append(current_context())
        if self.loi is not None:
            raise self.loi
        return self.do_thi_tra

    async def trich_dan_theo_id(self, ids):
        from core.permission import current_context

        self.ids.append(list(ids))
        self.ngu_canh.append(current_context())
        if self.loi is not None:
            raise self.loi
        return {i: self.trich_dan_tra[i] for i in ids if i in self.trich_dan_tra}

    async def vung_lan_can(self, ids, k):
        """Story 5.2: các id vào cộng `ke_can_tra[id]` khi `k > 0`; ghi lại `(ids, k)` ở `vung`."""
        from core.permission import current_context

        ids = list(ids)
        self.vung.append((ids, k))
        self.ngu_canh.append(current_context())
        if self.loi is not None:
            raise self.loi
        hop = list(ids)
        if k > 0:
            for i in ids:
                hop.extend(x for x in self.ke_can_tra.get(i, ()) if x not in hop)
        return {i: self.trich_dan_tra[i] for i in hop if i in self.trich_dan_tra}

    async def dong(self):
        self.da_dong = True


@pytest.fixture
def engine_gia():
    return EngineGia()


def _cam_audit(monkeypatch, audit_gia):
    async def _mo():
        return audit_gia

    monkeypatch.setattr(api_main, "mo_audit", _mo)


def _cam_engine(monkeypatch, engine_gia):
    async def _mo(audit):
        return engine_gia

    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo)


@pytest.fixture
def client(monkeypatch, kho_gia, audit_gia, engine_gia):
    """`TestClient` chạy lifespan thật, trên bảng `users`, audit và engine giả."""
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo():
        return kho_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    _cam_audit(monkeypatch, audit_gia)
    _cam_engine(monkeypatch, engine_gia)
    with TestClient(api_main.app) as c:
        yield c


def _token(client, tai_khoan: str) -> str:
    kq = client.post(
        "/auth/login", json={"tai_khoan": TEN_GO[tai_khoan], "mat_khau": MAT_KHAU}
    )
    assert kq.status_code == 200, kq.text
    return kq.json()["token"]


# --- Hàng "Đăng nhập đúng" --------------------------------------------------


def test_dang_nhap_dung_tra_jwt_mang_dung_claim_cua_chinh_tai_khoan(client):
    """Claims mang đúng vai, không gian và hai cờ của chính tài khoản đó."""
    for ten, vai, demo, admin in (
        ("ts01", "tech_support", False, False),
        ("dev01", "devops", True, True),
    ):
        kq = client.post(
            "/auth/login", json={"tai_khoan": TEN_GO[ten], "mat_khau": MAT_KHAU}
        )
        assert kq.status_code == 200
        assert kq.json()["token_type"] == "bearer"
        claim = jwt.decode(kq.json()["token"], KHOA_TEST, algorithms=["HS256"])
        # `sub` lấy từ **dòng bảng**, không từ chuỗi người gọi gõ vào: đó là thứ
        # audit ghi làm `real_account`, và nó phải là định danh chuẩn của tài
        # khoản chứ không phải cách viết của lần đăng nhập này.
        assert claim["sub"] == ten != TEN_GO[ten]
        assert claim["role"] == vai
        assert claim["space"] == "synth"
        assert (claim["demo"], claim["admin"]) == (demo, admin)
        # Hash mật khẩu không bao giờ ra khỏi đường này, kể cả trong một trường
        # phụ mà không ai đọc.
        assert "hash" not in kq.text


def test_exp_cach_iat_dung_12_gio(client):
    claim = jwt.decode(_token(client, "ts01"), KHOA_TEST, algorithms=["HS256"])
    assert claim["exp"] - claim["iat"] == TTL_GIO * 3600 == 12 * 3600


def test_token_dang_nhap_khong_mang_claim_act(client):
    """Token **đăng nhập** không mang `act`, kể cả của một tài khoản demo/admin.

    Story 3.1 viết ca này là "không có `act` ở đâu cả"; từ 4.5 `act` tồn tại,
    nên mệnh đề thu về đúng chỗ nó còn phải đúng: `act` là dấu của một phiên
    **đang mượn vai**, và một token vừa đăng nhập chưa mượn vai nào. Nếu đường
    đăng nhập cũng gắn `act` thì `POST /auth/thoat-xem-nhu` nhận mọi phiên, và
    `web/` vẽ chip "Đang xem như" cho một người vừa đăng nhập bằng vai của
    chính họ.

    Payload vì thế còn **đúng bảy khóa** của story 3.1.
    """
    claim = jwt.decode(_token(client, "dev01"), KHOA_TEST, algorithms=["HS256"])
    assert "act" not in claim
    assert set(claim) == {"sub", "role", "space", "demo", "admin", "iat", "exp"}


def test_token_dung_duoc_o_endpoint_doc_claim(client):
    kq = client.get("/auth/toi", headers={"Authorization": f"Bearer {_token(client, 'ts01')}"})
    assert kq.status_code == 200
    assert kq.json() == {
        "tai_khoan": "ts01",
        "vai": "tech_support",
        "khong_gian": "synth",
        "demo": False,
        "admin": False,
        # Khóa thứ sáu của story 4.5: `null` với một phiên thường. `web/` đọc
        # đúng trường này để biết có đang mượn vai không, chứ không suy từ một
        # trạng thái nhớ ở client.
        "act": None,
    }


# --- Hai hàng đăng nhập sai: một mã, một thân byte --------------------------


def test_hai_ca_dang_nhap_sai_tra_than_byte_giong_het_nhau(client):
    """Hàng "Tài khoản không tồn tại" và hàng "Mật khẩu sai" không phân biệt được.

    So `content` chứ không so field: chỗ duy nhất hai ca lệch được là câu chữ,
    và một thông điệp ghép tên tài khoản vào là đủ để liệt kê tài khoản có thật.
    """
    la = client.post("/auth/login", json={"tai_khoan": "khong-co", "mat_khau": MAT_KHAU})
    sai = client.post(
        "/auth/login", json={"tai_khoan": TEN_GO["ts01"], "mat_khau": "sai"}
    )
    # Mật khẩu dài hơn 72 byte làm `bcrypt.checkpw` dội `ValueError` trên
    # bcrypt 5.x. Không bắt thì ca này ra 500 trần nằm ngoài envelope, và nó
    # phân biệt được với hai ca trên - tức phá đúng bất biến đang đo.
    dai = client.post(
        "/auth/login", json={"tai_khoan": TEN_GO["ts01"], "mat_khau": "x" * 73}
    )
    assert la.status_code == sai.status_code == dai.status_code == 401
    assert la.json()["error"]["code"] == "DANG_NHAP_SAI"
    assert la.content == sai.content == dai.content
    assert "ts01" not in la.text and "khong-co" not in la.text


def test_dong_bang_mang_hash_rac_cung_ra_dang_nhap_sai(client, kho_gia):
    """Hash không parse được trong `users.mat_khau_hash` là một ca vận hành thật.

    `checkpw` dội `ValueError` cho nó. Và hash **rỗng** thì tệ hơn: nếu nhánh
    cuối chỉ hỏi `hash_mk is not None`, một dòng rỗng sẽ so với `HASH_GIA` và
    đăng nhập được bằng chính mật khẩu bí mật của hằng đó.
    """
    kho_gia.theo_ten["rac"] = _dong("rac", hash_mk="khong-phai-hash")
    kho_gia.theo_ten["rong"] = _dong("rong", hash_mk="")
    mau = client.post(
        "/auth/login", json={"tai_khoan": "khong-co", "mat_khau": MAT_KHAU}
    )
    for ten in ("rac", "rong"):
        kq = client.post("/auth/login", json={"tai_khoan": ten, "mat_khau": MAT_KHAU})
        assert kq.status_code == 401, ten
        assert kq.content == mau.content, ten


@pytest.mark.parametrize(
    "than",
    [
        pytest.param({"tai_khoan": "ts01"}, id="thieu_mat_khau"),
        pytest.param({"mat_khau": MAT_KHAU}, id="thieu_tai_khoan"),
        pytest.param({"tai_khoan": 1, "mat_khau": 2}, id="sai_kieu"),
        pytest.param([], id="than_khong_phai_mapping"),
    ],
)
def test_than_request_hong_cung_ra_dang_nhap_sai(client, than):
    """Không để FastAPI tự sinh 422: đó là một thân phản hồi ngoài envelope.

    Và nó là một cách phân biệt "gõ sai tên trường" với "gõ sai mật khẩu" mà
    người ngoài đọc được.
    """
    kq = client.post("/auth/login", json=than)
    assert kq.status_code == 401
    assert kq.json()["error"]["code"] == "DANG_NHAP_SAI"


def test_than_khong_phai_json_cung_ra_dang_nhap_sai(client):
    kq = client.post(
        "/auth/login", content=b"khong-phai-json", headers={"content-type": "application/json"}
    )
    assert kq.status_code == 401
    assert kq.json()["error"]["code"] == "DANG_NHAP_SAI"


def test_tai_khoan_la_van_chay_mot_phep_bcrypt(monkeypatch):
    """Nhánh "không tìm thấy tài khoản" không được trả về sớm.

    bcrypt cố ý chậm: một nhánh trả về ngay nhanh hơn nhánh so hash vài chục
    mili giây, và chênh đó đủ để liệt kê tài khoản tồn tại. Đếm số lời gọi
    `checkpw` chứ không đo thời gian - một assert thời gian là một test đỏ
    ngẫu nhiên trên máy CI đang bận.
    """
    import bcrypt

    from api import xac_thuc

    so_lan = []
    that = bcrypt.checkpw
    monkeypatch.setattr(
        xac_thuc.bcrypt,
        "checkpw",
        lambda mk, h: (so_lan.append(h), that(mk, h))[1],
    )
    assert so_mat_khau("bat_ky", None) is False
    assert len(so_lan) == 1
    assert so_lan[0] == HASH_GIA.encode()


def test_so_mat_khau_khong_chay_tren_event_loop(client, monkeypatch):
    """bcrypt cost 12 là ~0,2-0,3 giây CPU đồng bộ; nó không được chặn event loop.

    Gọi thẳng trong một handler `async def` là mọi request khác của tiến trình
    đứng chờ suốt thời gian đó - kể cả `/health`, tức container rơi khỏi
    `healthy` vì một người gõ sai mật khẩu.

    Chấm bằng `asyncio.get_running_loop()` chứ không bằng thời gian và cũng
    không bằng `threading.main_thread()`: một assert thời gian là một test đỏ
    ngẫu nhiên trên CI đang bận, còn `TestClient` vốn chạy app trong một thread
    riêng nên phép so với main thread không phân biệt được gì. Chỉ thread đang
    chạy event loop mới thấy một loop đang chạy.
    """
    from api import main as mod

    tren_loop = []
    that = mod.so_mat_khau

    def _ghi(mk, h):
        try:
            asyncio.get_running_loop()
            tren_loop.append(True)
        except RuntimeError:
            tren_loop.append(False)
        return that(mk, h)

    monkeypatch.setattr(mod, "so_mat_khau", _ghi)
    assert _token(client, "ts01")
    assert tren_loop == [False], (
        "phép bcrypt chạy ngay trên thread của event loop"
    )


def test_hash_gia_la_mot_hash_bcrypt_that():
    """Một chuỗi không phải hash làm `checkpw` dội ngay, tức là lại nhanh hơn."""
    import bcrypt

    assert bcrypt.checkpw(b"khong-ai-biet", HASH_GIA.encode()) is False


def test_hash_rong_khong_bao_gio_dang_nhap_duoc_bang_mat_khau_cua_hash_gia(monkeypatch):
    """Hash rỗng phải được coi như "không có tài khoản", không phải một chuỗi để so.

    Công thức cũ `(hash_mk or HASH_GIA)` cộng `hash_mk is not None` cho một
    dòng bảng có hash rỗng đi so với `HASH_GIA` rồi trả `True` nếu mật khẩu
    trùng plaintext của hằng đó. Plaintext thật là một chuỗi ngẫu nhiên không
    ai biết nên lỗ không khai thác được từ ngoài, nhưng nó là một nhánh
    fail-open thật, và không đo được nếu không thay `HASH_GIA` bằng một hash
    có plaintext biết trước - đúng việc ca này làm.
    """
    import bcrypt

    from api import xac_thuc

    biet_truoc = "mat-khau-cua-hash-gia"
    monkeypatch.setattr(
        xac_thuc,
        "HASH_GIA",
        bcrypt.hashpw(biet_truoc.encode(), bcrypt.gensalt(rounds=4)).decode(),
    )
    assert xac_thuc.so_mat_khau(biet_truoc, None) is False
    assert xac_thuc.so_mat_khau(biet_truoc, "") is False
    assert xac_thuc.so_mat_khau(biet_truoc, "   ") is False


def test_so_mat_khau_dung_thi_that():
    import bcrypt

    h = bcrypt.hashpw(MAT_KHAU.encode(), bcrypt.gensalt(rounds=4)).decode()
    assert so_mat_khau(MAT_KHAU, h) is True
    assert so_mat_khau("khac", h) is False


# --- Hàng "Token thiếu, hết hạn, hoặc sai chữ ký" ---------------------------


def _token_het_han() -> str:
    return phat_token(
        sub="ts01",
        role="tech_support",
        space="synth",
        demo=False,
        admin=False,
        khoa=KHOA_TEST,
        phat_luc=datetime.now(timezone.utc) - timedelta(hours=TTL_GIO + 1),
    )


def test_ba_ca_token_hong_deu_mot_ma(client):
    """Thiếu, hết hạn, sai chữ ký: cùng `TOKEN_KHONG_HOP_LE`, không nói ca nào."""
    sai_chu_ky = phat_token(
        sub="ts01", role="tech_support", space="synth", demo=False, admin=False,
        khoa="khoa-khac-" + "y" * 32,
    )
    cac_ca = {
        "thieu": {},
        "het_han": {"Authorization": f"Bearer {_token_het_han()}"},
        "sai_chu_ky": {"Authorization": f"Bearer {sai_chu_ky}"},
        "rac": {"Authorization": "Bearer khong-phai-token"},
        "sai_luoc_do": {"Authorization": f"Basic {_token(client, 'ts01')}"},
    }
    than = set()
    for ten, header in cac_ca.items():
        kq = client.get("/auth/toi", headers=header)
        assert kq.status_code == 401, ten
        assert kq.json()["error"]["code"] == "TOKEN_KHONG_HOP_LE", ten
        than.add(kq.content)
    assert len(than) == 1, "năm ca token hỏng phải ra cùng một thân"


def test_token_ky_bang_thuat_toan_khac_bi_tu_choi():
    """`algorithms` là danh sách một phần tử: nhận `none` là nhận token tự ký."""
    tho = jwt.encode({"sub": "ts01", "role": "devops", "space": "synth"}, key="", algorithm="none")
    with pytest.raises(LoiXacThuc) as loi:
        doc_token(tho, KHOA_TEST)
    assert loi.value.ma == "TOKEN_KHONG_HOP_LE"


def test_token_thieu_claim_bat_buoc_bi_tu_choi():
    """Một token đúng chữ ký mà thiếu `role` là một token không dùng được."""
    tho = jwt.encode(
        {"sub": "ts01", "space": "synth", "iat": 0, "exp": 9999999999},
        KHOA_TEST,
        algorithm="HS256",
    )
    with pytest.raises(LoiXacThuc) as loi:
        doc_token(tho, KHOA_TEST)
    assert loi.value.ma == "TOKEN_KHONG_HOP_LE"


@pytest.mark.parametrize(
    "header", [None, "", "Bearer", "Bearer   ", "Token abc", "abc"]
)
def test_header_hong_khong_tach_ra_token(header):
    assert token_tu_header(header) is None


# --- Hàng "Tài khoản thường gọi API demo/admin" ----------------------------


def test_tai_khoan_thuong_bi_tu_choi_o_api_demo_admin(client):
    """403 `THIEU_QUYEN_DEMO_ADMIN`, và nó khác 401 của ca token hỏng."""
    kq = client.get(
        "/auth/tai-khoan", headers={"Authorization": f"Bearer {_token(client, 'ts01')}"}
    )
    assert kq.status_code == 403
    assert kq.json()["error"]["code"] == "THIEU_QUYEN_DEMO_ADMIN"


def test_tai_khoan_demo_admin_qua_cua(client):
    kq = client.get(
        "/auth/tai-khoan", headers={"Authorization": f"Bearer {_token(client, 'dev01')}"}
    )
    assert kq.status_code == 200
    ra = kq.json()["tai_khoan"]
    assert {m["tai_khoan"] for m in ra} == {m.ten for m in nap_tai_khoan()}
    # Danh mục, không phải bản sao của bảng: không hash nào ra khỏi đây.
    assert "mat_khau_hash" not in kq.text and "$2b$" not in kq.text


@pytest.mark.parametrize(
    "demo,admin,qua",
    [(False, False, False), (True, False, True), (False, True, True), (True, True, True)],
)
def test_cua_demo_hoac_admin_la_phep_hoac(demo, admin, qua):
    """Hai cờ riêng, phép **hoặc**; API ghi đè policy sẽ có cửa `admin` riêng."""
    claim = ClaimNguoiHoi(sub="x", role="y", space="synth", demo=demo, admin=admin)
    if qua:
        assert doi_demo_hoac_admin(claim) is claim
    else:
        with pytest.raises(LoiXacThuc) as loi:
            doi_demo_hoac_admin(claim)
        assert loi.value.ma == "THIEU_QUYEN_DEMO_ADMIN"
        assert loi.value.http == 403


def test_health_khong_doi_token(client):
    """Healthcheck của compose nằm ngoài mọi cửa."""
    assert client.get("/health").json() == {"status": "ok"}


# --- Ba tuyến "xem như" (story 4.5, FR-18, AD-10) ---------------------------

TUYEN_XEM_NHU = "/auth/xem-nhu"
TUYEN_THOAT = "/auth/thoat-xem-nhu"
TUYEN_VAI = "/auth/vai"
BA_TUYEN = (TUYEN_XEM_NHU, TUYEN_THOAT, TUYEN_VAI)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _giai(token: str) -> dict:
    return jwt.decode(token, KHOA_TEST, algorithms=["HS256"])


def _xem_nhu(client, token: str, vai: str):
    return client.post(TUYEN_XEM_NHU, json={"vai": vai}, headers=_bearer(token))


def test_doi_vai_hop_le_giu_sub_va_hai_co_doi_role_va_them_act(client):
    """Hàng "Đổi vai hợp lệ": `role` là vai giả, `sub` và hai cờ nguyên vẹn.

    Bốn khẳng định, và mỗi cái chặn một cách hỏng khác nhau:

    - `role` đổi - nếu không thì cả tính năng không làm gì;
    - `sub` **không** đổi - tám chỗ ghi `act=ngu_canh.real_account` và phép tra
      grant break-glass theo cặp `(act, role)` đều đọc nó, nên đổi `sub` sang
      vai giả là làm chúng đổi nghĩa im lặng;
    - `demo`/`admin` chép nguyên - suy hai cờ từ vai giả là một phiên tự khóa
      mình lại trong vai vừa mượn, không thoát ra được;
    - `act` mang **cả** `sub` lẫn `role` của người thật - chip "vai thật" và mục
      "Thoát xem như · về dev01 · DevOps" đọc chính nó, và không còn chỗ nào
      khác trong token giữ vai thật.
    """
    cu = _token(client, "dev01")
    kq = _xem_nhu(client, cu, "tech_support")
    assert kq.status_code == 200, kq.text
    assert kq.json()["token_type"] == "bearer"
    moi = _giai(kq.json()["token"])
    assert moi["role"] == "tech_support"
    assert moi["sub"] == "dev01"
    assert (moi["demo"], moi["admin"]) == (True, True)
    assert moi["act"] == {"sub": "dev01", "role": "devops"}
    assert moi["space"] == _giai(cu)["space"]


def test_token_xem_nhu_khong_keo_dai_phien(client):
    """`exp` **bằng** `exp` của token đang cầm, không phải một mốc 12 giờ mới.

    Không có luật này thì một vòng bấm nút mỗi 11 giờ là một phiên không bao giờ
    hết hạn - tức TTL 12 giờ của story 3.1 mất hiệu lực qua một tuyến mà không
    ai nhìn. `iat` thì vẫn là bây giờ: token này thật sự vừa được ký.
    """
    cu = _token(client, "dev01")
    goc = _giai(cu)
    moi = _giai(_xem_nhu(client, cu, "sale_ba").json()["token"])
    assert moi["exp"] == goc["exp"]
    assert moi["exp"] - moi["iat"] <= TTL_GIO * 3600


def test_doi_tiep_vai_khac_van_giu_nguyen_act_cua_nguoi_that(client):
    """Hàng "Đổi tiếp vai khác": `act` **vẫn** là `{dev01, devops}`.

    Xem như một vai khác từ trong một lượt xem như vẫn là cùng một người thật.
    Nếu `act` bị ghi đè bằng claim của token đang cầm thì sau hai lần đổi, "vai
    thật" thành `tech_support` và thoát xem như trả về sai vai - một phiên không
    còn đường về.
    """
    b1 = _xem_nhu(client, _token(client, "dev01"), "tech_support").json()["token"]
    b2 = _xem_nhu(client, b1, "sale_ba")
    assert b2.status_code == 200, b2.text
    claim = _giai(b2.json()["token"])
    assert claim["role"] == "sale_ba"
    assert claim["act"] == {"sub": "dev01", "role": "devops"}


def test_thoat_xem_nhu_ve_vai_that_va_bo_han_claim_act(client):
    """Hàng "Thoát xem như": `role` về `devops`, **không** còn claim `act`.

    `act` phải biến mất chứ không thành `null`: nó là dấu duy nhất của một phiên
    đang mượn vai, và một `act` còn sót lại là chip hổ phách còn trên topbar sau
    khi người dùng đã bấm ✕.
    """
    cu = _token(client, "dev01")
    muon = _xem_nhu(client, cu, "tech_support").json()["token"]
    kq = client.post(TUYEN_THOAT, headers=_bearer(muon))
    assert kq.status_code == 200, kq.text
    claim = _giai(kq.json()["token"])
    assert claim["role"] == "devops"
    assert "act" not in claim
    assert claim["sub"] == "dev01"
    assert claim["exp"] == _giai(cu)["exp"]


def test_thoat_khi_vai_that_khong_con_trong_bang_la_400_khong_phat_token(client, monkeypatch):
    """Hoán bảng lúc đang mượn vai rồi thoát: 400 `VAI_KHONG_CO`, phiên giữ nguyên.

    Ca có thật vì cả hai tuyến mở cho cùng một tài khoản `admin`. Không có phép
    kiểm này thì thoát ra phát một token mang một vai **không tồn tại**: token
    ấy hợp lệ về chữ ký nên nó qua `_claim`, rồi **mọi lượt sau đó** dội
    `RoleUnknown` ở `ngu_canh_cua_claim` và người dùng không có đường nào ra
    ngoài đăng xuất. Đường xin đã có phép kiểm này từ đầu; đường thoát thì
    không, và đó là chỗ hở.

    Dựng bằng một bảng chỉ có `tech_support`: `dev01` mượn vai ấy, rồi bảng
    hoán sang bảng không còn `devops`.
    """
    goc = _token(client, "dev01")
    muon = _xem_nhu(client, goc, "tech_support").json()["token"]

    # Bảng mới: cùng nội dung, **bỏ hàng `devops`** - tức vai thật biến mất.
    kho = client.app.state.kho_chinh_sach
    ma, policy = kho.ma_va_policy()
    bo_devops = type(policy)(
        version=policy.version,
        policy_version=policy.policy_version + "-khong-devops",
        roles={k: v for k, v in policy.roles.items() if k != "devops"},
    )
    monkeypatch.setattr(kho, "_hien_tai", (ma, bo_devops))
    assert "devops" not in client.app.state.kho_chinh_sach.hien_tai().roles

    kq = client.post(TUYEN_THOAT, headers=_bearer(muon))
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == "VAI_KHONG_CO"
    assert "token" not in kq.json()
    # Cùng **một thân** với đường xin: hai cửa cho cùng một sự thật.
    la = _xem_nhu(client, goc, "khong_co_that")
    assert kq.content == la.content


def test_thoat_khi_khong_muon_vai_la_400_va_khong_phat_token(client):
    """Hàng "Thoát khi không mượn vai": 400 `KHONG_DANG_XEM_NHU`, không token.

    Không phải một 200 im lặng: `web/` dựng mục thoát theo đúng claim `act`, nên
    một request như thế nghĩa là hai bên đã lệch nhau, và một 200 giấu chỗ lệch.
    """
    kq = client.post(TUYEN_THOAT, headers=_bearer(_token(client, "dev01")))
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == "KHONG_DANG_XEM_NHU"
    assert "token" not in kq.json()


def test_vai_khong_co_trong_bang_la_400_va_khong_phat_token(client):
    """Hàng "Vai không có trong bảng": 400 `VAI_KHONG_CO`, thân không dội tên vai.

    Danh mục vai là **bảng chính sách đang chạy** (AD-4), nên phép kiểm đứng ở
    chính `Policy.roles` chứ không ở một danh sách chép ở `api/`. Không dội lại
    chuỗi người gọi gửi: danh mục đọc được qua `GET /auth/vai` sau cửa quyền,
    nên ghép tên vào thông điệp chỉ thêm một đường phản chiếu đầu vào.
    """
    kq = _xem_nhu(client, _token(client, "dev01"), "khong_co_that")
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == "VAI_KHONG_CO"
    assert "khong_co_that" not in kq.text
    assert "token" not in kq.json()


@pytest.mark.parametrize(
    "than",
    [
        pytest.param({}, id="thieu_truong"),
        pytest.param({"vai": 3}, id="sai_kieu"),
        pytest.param({"vai": ""}, id="rong"),
        pytest.param([], id="than_khong_phai_mapping"),
    ],
)
def test_than_xem_nhu_sai_hinh_la_than_yeu_cau_la(client, than):
    """Hàng "Thân sai hình": 400 `THAN_YEU_CAU_LA` cho cả bốn cách hỏng.

    Cùng mã mà handler `RequestValidationError` phát cho mọi tuyến khai một thân
    pydantic, nên client không phải đọc hai hình dạng lỗi cho cùng một ca.
    """
    kq = client.post(TUYEN_XEM_NHU, json=than, headers=_bearer(_token(client, "dev01")))
    assert kq.status_code == 400, kq.text
    assert kq.json()["error"]["code"] == "THAN_YEU_CAU_LA"


def test_than_xem_nhu_khong_phai_json_cung_ra_than_yeu_cau_la(client):
    kq = client.post(
        TUYEN_XEM_NHU,
        content=b"khong-phai-json",
        headers={**_bearer(_token(client, "dev01")), "content-type": "application/json"},
    )
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == "THAN_YEU_CAU_LA"


def test_tai_khoan_thuong_bi_tu_choi_o_ca_ba_tuyen_xem_nhu(client, audit_gia):
    """Hàng "Tài khoản thường": 403 `THIEU_QUYEN_DEMO_ADMIN`, **một thân** cho cả ba.

    Cả hai vế của FR-18 có test: nút không vẽ cho tài khoản thiếu cờ *và* API
    từ chối. Vế thứ hai là vế duy nhất kiểm được ở đây, và nó phải đúng dù `web/`
    có ẩn nút hay không - ẩn một nút không phải một cơ chế quyền.

    Và **không hàng audit nào**: một request bị cửa quyền chặn chưa đổi vai của
    ai, nên một hàng `role_swap` cho nó là một dòng nói dối trong sổ.
    """
    token = _token(client, "ts01")
    truoc = len(audit_gia.su_kien)
    than = [
        client.post(TUYEN_XEM_NHU, json={"vai": "devops"}, headers=_bearer(token)),
        client.post(TUYEN_THOAT, headers=_bearer(token)),
        client.get(TUYEN_VAI, headers=_bearer(token)),
    ]
    for kq in than:
        assert kq.status_code == 403, kq.text
        assert kq.json()["error"]["code"] == "THIEU_QUYEN_DEMO_ADMIN"
    assert than[0].content == than[1].content == than[2].content
    assert not [s for s in audit_gia.su_kien[truoc:] if s.event == "role_swap"]


def test_demo_khong_admin_van_qua_cua_ba_tuyen(client):
    """Cửa là phép **hoặc**, và `demo01` là chỗ duy nhất chứng minh được qua HTTP.

    Với `ts01` (không cờ nào) và `dev01` (cả hai cờ), một đột biến đổi `or`
    thành `and` vẫn xanh cả bộ. Với tài khoản này thì không.
    """
    token = _token(client, "demo01")
    assert client.get(TUYEN_VAI, headers=_bearer(token)).status_code == 200
    kq = _xem_nhu(client, token, "devops")
    assert kq.status_code == 200, kq.text
    assert client.post(TUYEN_THOAT, headers=_bearer(kq.json()["token"])).status_code == 200


def test_dang_xem_nhu_van_thoat_duoc_du_vai_gia_khong_co_co_nao(client):
    """Hai cờ đọc từ **claim**, không suy từ vai giả.

    `sale_ba` không có cờ nào trong seed và không có cờ nào trong bảng chính
    sách; nếu cửa quyền suy `demo`/`admin` từ vai đang mang thì một phiên mượn
    vai ấy tự khóa mình lại và không có đường về ngoài đăng xuất.
    """
    muon = _xem_nhu(client, _token(client, "dev01"), "sale_ba").json()["token"]
    assert client.get(TUYEN_VAI, headers=_bearer(muon)).status_code == 200
    kq = client.post(TUYEN_THOAT, headers=_bearer(muon))
    assert kq.status_code == 200
    assert _giai(kq.json()["token"])["role"] == "devops"


def test_ba_tuyen_deu_doi_token(client):
    """Ba tuyến nằm trong `cua_dong`, nên chúng đòi token bằng cơ chế framework."""
    for tuyen in BA_TUYEN:
        goi = client.get if tuyen == TUYEN_VAI else client.post
        kq = goi(tuyen)
        assert kq.status_code == 401, tuyen
        assert kq.json()["error"]["code"] == "TOKEN_KHONG_HOP_LE", tuyen


def test_danh_muc_vai_bang_khoa_cua_bang_chinh_sach_dang_chay(client):
    """Hàng "Danh mục vai": đúng bằng khóa của `Policy.roles`, đã sắp xếp.

    Suy từ bảng đang chạy chứ không so với một tuple gõ tay ở đây: cả hai vế
    phải là một, và một danh sách chép tay trong test chỉ chứng minh test nhất
    quán với chính nó. Phép so tuyệt đối `== sorted(...)` chứ không "chứa": một
    vai lọt vào danh mục mà bảng không có là một dòng dropdown bấm vào ra 400.
    """
    kq = client.get(TUYEN_VAI, headers=_bearer(_token(client, "demo01")))
    assert kq.status_code == 200, kq.text
    assert kq.json() == {"vai": sorted(client.app.state.kho_chinh_sach.hien_tai().roles)}
    # Và mọi vai trả về xem như được thật: danh mục là một danh mục dùng được,
    # không một danh sách để đọc.
    for vai in kq.json()["vai"]:
        assert _xem_nhu(client, _token(client, "dev01"), vai).status_code == 200, vai


def test_danh_muc_vai_doc_bang_dang_chay_chu_khong_bang_mac_dinh(client, monkeypatch):
    """Hoán bảng lúc chạy thì danh mục đổi theo - **bảng đang chạy**, không bảng mặc định.

    Bản đầu của ca trên dựng kỳ vọng bằng `load_policy(duong_dan_policy_mac_dinh())`,
    nên một handler đọc bảng mặc định thay vì `kho_chinh_sach.hien_tai()` vẫn
    xanh - đúng thứ tên ca test hứa lại là thứ nó không kiểm. Ở đây bảng đang
    chạy **khác** bảng mặc định, nên hai đường đọc cho hai kết quả khác nhau.

    Hoán qua đúng `POST /admin/policy` chứ không gán thẳng `app.state`: đó là
    đường duy nhất mà một bảng đổi được lúc chạy, và ca này phải đứng trên nó.
    """
    from api import chinh_sach

    # Ba bảng đo chỉ hoán sang được trên tiến trình đo (story 3.8, ADR-022).
    monkeypatch.setattr(client.app.state, "che_do_do", True)
    admin = _bearer(_token(client, "dev01"))
    hoan = client.post("/admin/policy", json={"id": "tat-phan-quyen"}, headers=admin)
    assert hoan.status_code == 200, hoan.text
    assert hoan.json()["id"] != chinh_sach.ID_MAC_DINH

    dang_chay = client.app.state.kho_chinh_sach.hien_tai()
    kq = client.get(TUYEN_VAI, headers=admin)
    assert kq.json() == {"vai": sorted(dang_chay.roles)}
    # Hoán về để không rò trạng thái sang ca khác của cùng fixture.
    client.post("/admin/policy", json={"id": chinh_sach.ID_MAC_DINH}, headers=admin)


def test_danh_muc_vai_khong_lo_scope_hay_muc_tiet_lo(client):
    """Chỉ **tên vai**: một tài khoản demo không cần đọc bảng quyền để bấm nút."""
    kq = client.get(TUYEN_VAI, headers=_bearer(_token(client, "dev01")))
    assert set(kq.json()) == {"vai"}
    for cam in ("scopes", "disclosure", "masked_slots", "noi_bo", "L2"):
        assert cam not in kq.text, cam


def test_mot_lan_doi_vai_ghi_dung_mot_hang_role_swap(client, audit_gia):
    """Hàng "Audit một lần đổi": một hàng mutation, `act` là tài khoản **thật**.

    `act='dev01'` và `role='tech_support'` là chính câu AD-10 đòi: sổ nói được
    ai thật sự đứng sau một lượt hỏi mang vai giả. `chi_tiet` mang cả ba tên vai
    vì đổi từ Tech Support sang Sale/BA của một tài khoản DevOps là **ba** tên,
    không phải hai.
    """
    from core.audit import TIER_MUTATION

    truoc = len(audit_gia.su_kien)
    _xem_nhu(client, _token(client, "dev01"), "tech_support")
    hang = [s for s in audit_gia.su_kien[truoc:] if s.event == "role_swap"]
    assert len(hang) == 1
    s = hang[0]
    assert s.tier == TIER_MUTATION
    assert (s.act, s.role) == ("dev01", "tech_support")
    assert s.space == "synth"
    assert dict(s.chi_tiet) == {
        "vai_cu": "devops",
        "vai_moi": "tech_support",
        "vai_that": "devops",
        "xem_nhu": True,
    }


def test_hang_audit_cua_lan_doi_thu_hai_va_cua_lan_thoat(client, audit_gia):
    """Ba tên vai tách nhau ra ở đúng ca chúng khác nhau, và lượt thoát mang `xem_nhu: False`."""
    b1 = _xem_nhu(client, _token(client, "dev01"), "tech_support").json()["token"]
    truoc = len(audit_gia.su_kien)
    b2 = _xem_nhu(client, b1, "sale_ba").json()["token"]
    client.post(TUYEN_THOAT, headers=_bearer(b2))
    hang = [s for s in audit_gia.su_kien[truoc:] if s.event == "role_swap"]
    assert len(hang) == 2
    assert dict(hang[0].chi_tiet) == {
        "vai_cu": "tech_support",
        "vai_moi": "sale_ba",
        "vai_that": "devops",
        "xem_nhu": True,
    }
    assert (hang[0].act, hang[0].role) == ("dev01", "sale_ba")
    assert dict(hang[1].chi_tiet) == {
        "vai_cu": "sale_ba",
        "vai_moi": "devops",
        "vai_that": "devops",
        "xem_nhu": False,
    }
    assert (hang[1].act, hang[1].role) == ("dev01", "devops")


@pytest.mark.parametrize("tuyen", [TUYEN_XEM_NHU, TUYEN_THOAT])
def test_audit_hong_la_500_va_khong_token_moi(client, audit_gia, tuyen):
    """Audit hỏng là **không có token mới** - ngược hẳn `auth_login` best-effort.

    Một lượt mượn vai không dấu vết là đúng lỗ FR-23 sinh ra để bịt, và ở đây
    không có gì để giữ byte-identical: cửa quyền đã qua rồi.
    """
    cu = _token(client, "dev01")
    muon = _xem_nhu(client, cu, "tech_support").json()["token"]
    audit_gia.no = RuntimeError("postgres chết")
    kq = (
        client.post(tuyen, json={"vai": "sale_ba"}, headers=_bearer(muon))
        if tuyen == TUYEN_XEM_NHU
        else client.post(tuyen, headers=_bearer(muon))
    )
    assert kq.status_code == 500, kq.text
    assert kq.json()["error"]["code"] == "AUDIT_GHI_HONG"
    assert "token" not in kq.json()


def test_auth_toi_khai_act_khi_dang_muon_vai(client):
    """`GET /auth/toi` là nguồn **duy nhất** để `web/` biết phiên đang mượn vai."""
    muon = _xem_nhu(client, _token(client, "dev01"), "tech_support").json()["token"]
    kq = client.get("/auth/toi", headers=_bearer(muon))
    assert kq.json() == {
        "tai_khoan": "dev01",
        "vai": "tech_support",
        "khong_gian": "synth",
        "demo": True,
        "admin": True,
        "act": {"tai_khoan": "dev01", "vai": "devops"},
    }


@pytest.mark.parametrize(
    "act",
    [
        pytest.param("dev01", id="khong_phai_map"),
        pytest.param({"sub": "dev01"}, id="thieu_role"),
        pytest.param({"role": "devops"}, id="thieu_sub"),
        pytest.param({"sub": "", "role": "devops"}, id="sub_rong"),
        pytest.param({"sub": 1, "role": 2}, id="sai_kieu"),
    ],
)
def test_act_hong_trong_token_la_token_khong_hop_le(act):
    """`act` có mặt mà không đọc được là **từ chối cả token**, cùng mã ba ca kia.

    Bỏ qua lặng lẽ thì một phiên mượn vai thành một phiên thường mang vai giả:
    mục "Thoát xem như" biến mất khỏi giao diện, và hàng audit của lượt sau
    không còn nối được về người thật. Vắng mặt thì vẫn là ca thường, nên `act`
    **không** nằm trong `options={"require": ...}`.
    """
    luc = datetime.now(timezone.utc).replace(microsecond=0)
    tho = jwt.encode(
        {
            "sub": "dev01",
            "role": "tech_support",
            "space": "synth",
            "demo": True,
            "admin": True,
            "act": act,
            "iat": luc,
            "exp": luc + timedelta(hours=1),
        },
        KHOA_TEST,
        algorithm="HS256",
    )
    with pytest.raises(LoiXacThuc) as loi:
        doc_token(tho, KHOA_TEST)
    assert loi.value.ma == "TOKEN_KHONG_HOP_LE"


def test_phat_token_khong_act_thi_payload_van_bay_khoa():
    """`phat_token` vắng `act` cho **đúng bảy khóa**, tức đường đăng nhập không đổi."""
    tho = phat_token(
        sub="dev01", role="devops", space="synth", demo=True, admin=True, khoa=KHOA_TEST
    )
    assert set(jwt.decode(tho, KHOA_TEST, algorithms=["HS256"])) == {
        "sub",
        "role",
        "space",
        "demo",
        "admin",
        "iat",
        "exp",
    }


def test_phat_token_chep_het_han_thay_vi_phat_moc_moi():
    """`het_han` đặt `exp` bằng mốc truyền vào, không cộng thêm TTL."""
    het = int(datetime.now(timezone.utc).timestamp()) + 600
    claim = jwt.decode(
        phat_token(
            sub="dev01",
            role="tech_support",
            space="synth",
            demo=True,
            admin=True,
            khoa=KHOA_TEST,
            act=ActClaim(sub="dev01", role="devops"),
            het_han=het,
        ),
        KHOA_TEST,
        algorithms=["HS256"],
    )
    assert claim["exp"] == het
    assert claim["exp"] - claim["iat"] < TTL_GIO * 3600


def test_phat_token_tu_choi_het_han_vuot_tran_ttl():
    """Trần TTL là một **cơ chế trong `phat_token`**, không một quy ước ở nơi gọi.

    Hàm public và `het_han` đi thẳng vào `exp`, nên một nơi gọi thứ hai truyền
    `iat + 24h` phát ra một phiên dài gấp đôi mà không phép canh nào thấy - câu
    "xem như không bao giờ kéo dài phiên" khi ấy chỉ còn là chữ trong docstring.
    Cùng tinh thần mà story này áp cho `maxLength` của ô hỏi: chặn ở chỗ giá trị
    đi qua, không ở chỗ người ta nhớ.

    `ValueError` chứ không một mã HTTP: đây là lỗi của người viết code, không
    của người gọi API.
    """
    luc = datetime.now(timezone.utc).replace(microsecond=0)
    tran = int((luc + timedelta(hours=TTL_GIO)).timestamp())

    def ky(het: int) -> str:
        return phat_token(
            sub="dev01",
            role="tech_support",
            space="synth",
            demo=True,
            admin=True,
            khoa=KHOA_TEST,
            phat_luc=luc,
            het_han=het,
        )

    # Đúng trần thì qua (thoát xem như của một token vừa phát chạm đúng ca này).
    assert jwt.decode(ky(tran), KHOA_TEST, algorithms=["HS256"])["exp"] == tran
    with pytest.raises(ValueError):
        ky(tran + 1)
    with pytest.raises(ValueError):
        ky(int((luc + timedelta(hours=TTL_GIO * 2)).timestamp()))


def test_than_xem_nhu_thua_khoa_bi_tu_choi(client):
    """`extra="forbid"`: một tên thừa không được nhận rồi bỏ qua im lặng.

    Cùng lý do với `api.hoi_dap.ThanHoiDap`. Ở đúng tuyến này thì những tên
    người ta sẽ thử - `act`, `sub`, `exp`, `space` - là thứ quyết định token mới
    mang gì, và cả bốn phải đến từ claim đang cầm chứ không từ thân request.
    Nhận rồi bỏ qua không sai lúc chạy, nhưng nó dạy người gọi rằng trường đó
    có nghĩa.
    """
    for than in (
        {"vai": "sale_ba", "them": 1},
        {"vai": "sale_ba", "act": {"sub": "admin", "role": "admin"}},
        {"vai": "sale_ba", "exp": 9999999999},
    ):
        kq = client.post(TUYEN_XEM_NHU, json=than, headers=_bearer(_token(client, "dev01")))
        assert kq.status_code == 400, (than, kq.text)
        assert kq.json()["error"]["code"] == "THAN_YEU_CAU_LA"


def test_audit_qua_han_cung_la_500_va_khong_token_moi(client, audit_gia, monkeypatch):
    """Đường **quá hạn** của `asyncio.wait_for`, không chỉ đường port dội lỗi.

    Hai cách audit hỏng, và chỉ một trong hai có ca: một port dội ngay, và một
    port **treo**. Cái sau là ca vận hành thật hơn (Postgres còn sống nhưng
    pool cạn), và nó đi qua một nhánh code khác - `TimeoutError` của `wait_for`,
    không phải exception của port. Cả hai phải ra 500 `AUDIT_GHI_HONG` và
    không token mới.
    """
    import asyncio as _asyncio

    async def treo(_su_kien):
        await _asyncio.sleep(3600)

    monkeypatch.setattr(audit_gia, "ghi", treo)
    # Trần chờ hạ xuống để ca chạy trong một nhịp test, không phải 10 giây thật.
    monkeypatch.setattr(api_main.hoi_dap, "THOI_HAN_BIEN_DOI", 0.05)
    kq = _xem_nhu(client, _token(client, "dev01"), "tech_support")
    assert kq.status_code == 500, kq.text
    assert kq.json()["error"]["code"] == "AUDIT_GHI_HONG"
    assert "token" not in kq.json()


def test_ky_token_hong_thi_khong_de_lai_hang_audit(client, audit_gia, monkeypatch):
    """Chiều còn lại của cặp: **ký hỏng là không có hàng `role_swap`**.

    Story phát biểu "ghi hỏng là không có token mới" và có ca; chiều ngược lại
    thì hở, và nó hở theo chiều xấu hơn - một hàng audit cho một lần đổi vai
    **chưa từng xảy ra**, tức sổ kiểm toán nói dối. Đóng bằng thứ tự: ký trước,
    ghi audit, rồi mới trả.

    Ca dựng bằng chính đường hỏng có thật: `phat_token` dội `ValueError` khi
    `het_han` vượt trần TTL.
    """
    # Lấy token **trước** khi thay `phat_token`: `/auth/login` cũng ký qua nó.
    goc = _token(client, "dev01")
    truoc = len([s for s in audit_gia.su_kien if s.event == "role_swap"])

    def ky_hong(**_kw):
        raise ValueError("ký hỏng")

    monkeypatch.setattr(api_main, "phat_token", ky_hong)
    # `TestClient` dội lại ngoại lệ của server thay vì cho `_loi_khong_xac_dinh`
    # dựng envelope 500 (mặc định `raise_server_exceptions=True`), nên ca này
    # bắt chính ngoại lệ ấy. Điều đang chấm không phải mã HTTP - nó là thứ
    # **không** có trong sổ sau khi lời gọi hỏng.
    with pytest.raises(ValueError):
        _xem_nhu(client, goc, "tech_support")
    sau = [s for s in audit_gia.su_kien if s.event == "role_swap"]
    assert len(sau) == truoc, "ký hỏng không được để lại hàng role_swap nào"


def test_doc_token_tra_ve_het_han_cua_chinh_token():
    """`ClaimNguoiHoi.het_han` là `exp` của chính token; đường phát thứ hai chép nó."""
    tho = phat_token(
        sub="ts01", role="tech_support", space="synth", demo=False, admin=False, khoa=KHOA_TEST
    )
    claim = doc_token(tho, KHOA_TEST)
    assert claim.het_han == jwt.decode(tho, KHOA_TEST, algorithms=["HS256"])["exp"]
    assert claim.act is None


# --- Token xem như đi **quá** `/auth/*` -------------------------------------


def test_token_xem_nhu_doi_ca_ngu_canh_quyen_va_lam_grant_ngu(
    client, engine_gia, kho_break_glass_gia
):
    """Câu trung tâm của story - "mọi tầng sau chỉ nhìn token" - đo trên một lượt thật.

    Mọi ca khác của file này dừng ở `/auth/*`: chúng so claim và đếm hàng audit,
    tức chúng chấm **đường phát token** chứ không chấm hệ quả của nó. Một sửa
    đổi rất dễ ai đó làm với lý do "người trình diễn mất break-glass khi đổi
    vai" - cho `doc_grant_ids` rơi về `claim.act.role` khi có `act` - vẫn xanh
    cả bộ. Ở đây thì không.

    Ba khẳng định, đo **bên trong** lời gọi engine (`EngineGia` ghi
    `current_context()` ngay trong thân method, chỗ duy nhất chứng minh
    `use_context` bọc trọn lời gọi):

    1. `PermissionContext.role` là **vai mượn**, không vai thật - tức bảng chính
       sách được tra theo vai giả và mọi khóa lọc đi theo nó;
    2. `real_account` **vẫn là tài khoản thật** - đó là `act` của mọi hàng audit
       và là khóa tra grant, hai thứ không được đổi nghĩa vì một lần đổi vai;
    3. grant của cặp `(dev01, devops)` **ngủ** dưới token mượn vai và **sống
       lại** sau khi thoát. Đó là hành vi EXPERIENCE.md đã chốt, không một tác
       dụng phụ: một grant cấp cho vai thật không được đi theo người ta sang một
       vai khác.
    """
    from api.hoi_dap import CT_VAI_THAT
    from tests.ho_tro_break_glass import chen_grant

    asyncio.run(
        chen_grant(kho_break_glass_gia, act="dev01", role="devops", hyperedge_ids=["HE-01"])
    )

    def hoi(token: str):
        kq = client.post("/hoi-dap", json={"cau_hoi": "câu hỏi"}, headers=_bearer(token))
        assert kq.status_code == 200, kq.text
        return engine_gia.ngu_canh[-1], kq.json()

    goc = _token(client, "dev01")
    nc_goc, than_goc = hoi(goc)
    assert (nc_goc.role, nc_goc.real_account) == ("devops", "dev01")
    assert nc_goc.grant_ids == ("HE-01",), "grant của vai thật phải có hiệu lực"
    assert than_goc["meta"]["role"] == "devops"

    muon = _xem_nhu(client, goc, "tech_support").json()["token"]
    nc_muon, than_muon = hoi(muon)
    assert nc_muon.role == "tech_support", "ngữ cảnh quyền tra theo **vai mượn**"
    assert nc_muon.real_account == "dev01", "`sub` không đổi, nên audit và grant giữ nghĩa"
    assert nc_muon.grant_ids == (), "grant của cặp `(dev01, devops)` phải ngủ"
    assert than_muon["meta"]["role"] == "tech_support"

    ve = client.post(TUYEN_THOAT, headers=_bearer(muon)).json()["token"]
    nc_ve, _ = hoi(ve)
    assert (nc_ve.role, nc_ve.grant_ids) == ("devops", ("HE-01",)), "thoát ra thì grant sống lại"
    # Và hàng `query` của lượt mượn vai nói ra nó chạy dưới một vai mượn.
    assert CT_VAI_THAT in _hang_query(client)[1].chi_tiet


def _hang_query(client):
    """Ba hàng `query` của ca trên, theo thứ tự lượt hỏi."""
    return [s for s in client.app.state.audit.su_kien if s.event == "query"]


def test_hang_audit_cua_luot_muon_vai_mang_dau_vai_that(client, engine_gia, audit_gia):
    """Ba hàng của một lượt mượn vai mang `chi_tiet.vai_that`; lượt thường thì không.

    Không có dấu này thì một lượt của `dev01` đang mượn `truong_nhom` ghi
    `act='dev01'`, `role='truong_nhom'` - **không khác** một lượt của một tài
    khoản `truong_nhom` thật - và hậu kiểm FR-23 phải ghép hàng `query` với
    hàng `role_swap` gần nhất theo cửa sổ thời gian, thứ hỏng lặng lẽ khi hai
    phiên chạy song song. Cùng khuôn `grant_ids` của story 5.3.

    Hình dạng hàng của một lượt **không** mượn vai giữ nguyên **từng khóa**:
    sáu đợt nạp và mọi hàng đã ghi không được đổi hình vì một trường mới.
    """
    from api.hoi_dap import CT_VAI_THAT

    goc = _token(client, "dev01")
    client.post("/hoi-dap", json={"cau_hoi": "câu hỏi"}, headers=_bearer(goc))
    thuong = [s for s in audit_gia.su_kien if s.event == "query"][-1]
    assert CT_VAI_THAT not in thuong.chi_tiet, dict(thuong.chi_tiet)

    muon = _xem_nhu(client, goc, "sale_ba").json()["token"]
    client.post("/hoi-dap", json={"cau_hoi": "câu hỏi"}, headers=_bearer(muon))
    hang = [s for s in audit_gia.su_kien if s.event == "query"][-1]
    assert hang.chi_tiet[CT_VAI_THAT] == "devops"
    assert (hang.act, hang.role) == ("dev01", "sale_ba")
    # Hình dạng cũ cộng đúng một khóa, không hơn.
    assert set(hang.chi_tiet) - set(thuong.chi_tiet) == {CT_VAI_THAT}


def test_hang_tu_choi_cua_luot_muon_vai_cung_mang_dau(client, engine_gia, audit_gia):
    """Cùng dấu ở hàng `refusal`: một lượt từ chối của vai mượn vẫn phải truy được về người thật."""
    from api.hoi_dap import CT_VAI_THAT
    from adapters.tra_loi import LY_DO_NGU_CANH_RONG

    engine_gia.ly_do = LY_DO_NGU_CANH_RONG
    goc = _token(client, "dev01")
    muon = _xem_nhu(client, goc, "sale_ba").json()["token"]
    client.post("/hoi-dap", json={"cau_hoi": "câu hỏi"}, headers=_bearer(muon))
    hang = [s for s in audit_gia.su_kien if s.event == "refusal"][-1]
    assert hang.chi_tiet[CT_VAI_THAT] == "devops"


# --- Hàng "Thiếu khóa ký" ---------------------------------------------------


def test_thieu_khoa_ky_thi_tu_choi_kem_ma_on_dinh():
    with pytest.raises(JwtSecretMissing) as loi:
        khoa_ky({})
    assert loi.value.code == "JWT_SECRET_MISSING"
    with pytest.raises(JwtSecretMissing):
        khoa_ky({BIEN_KHOA_KY: "   "})


def test_khoa_ky_ngan_bi_tu_choi():
    """HS256 lấy nguyên chuỗi làm khóa HMAC, nên khóa ngắn dò được ngoại tuyến."""
    with pytest.raises(JwtSecretMissing) as loi:
        khoa_ky({BIEN_KHOA_KY: "ngan"})
    assert loi.value.code == "JWT_SECRET_MISSING"


def test_khong_tu_sinh_khoa_moi_lan_goi():
    """Hai lời gọi cho cùng một khóa: khóa ngẫu nhiên mỗi lần là token chết im lặng."""
    assert khoa_ky({BIEN_KHOA_KY: KHOA_TEST}) == khoa_ky({BIEN_KHOA_KY: KHOA_TEST})


def test_lifespan_tu_choi_khoi_dong_khi_thieu_khoa_ky(monkeypatch, kho_gia):
    """Thiếu `JWT_SECRET` là hỏng ở giây đầu, không phải ở lần đăng nhập đầu.

    Và nó hỏng **trước** khi mở kết nối nào: ở đây bản giả đếm số lần được mở,
    và số đó phải là 0.
    """
    monkeypatch.delenv(BIEN_KHOA_KY, raising=False)
    da_mo = []

    async def _mo():
        da_mo.append(1)
        return kho_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    with pytest.raises(JwtSecretMissing):
        with TestClient(api_main.app):
            pass
    assert da_mo == [], "phải từ chối trước khi mở kết nối nào"


def test_lifespan_dong_bo_dung_noi_dung_seed_va_dong_pool(monkeypatch, kho_gia, audit_gia, kho_break_glass_gia):
    """Khởi động: đổ seed một chiều từ file xuống bảng. Tắt: đóng pool.

    Chấm **nội dung** chứ không chỉ đếm số lần gọi. Đột biến `dong_bo(())`
    trong lifespan để lại một container `healthy`, `/health` xanh, bảng `users`
    rỗng, và triệu chứng duy nhất là mọi lần đăng nhập trả `DANG_NHAP_SAI` -
    đúng cái mã cố ý không nói ra ca nào, tức chẩn đoán sai hướng.
    """
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo():
        return kho_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    _cam_audit(monkeypatch, audit_gia)
    engine_gia = EngineGia()
    _cam_engine(monkeypatch, engine_gia)
    with TestClient(api_main.app):
        assert kho_gia.da_dong_bo == 1
        da = kho_gia.muc_da_dong_bo
        cho = nap_tai_khoan()
        assert da is not None and len(da) == len(cho) > 0
        khoa = lambda cac: {  # noqa: E731
            (
                m.ten,
                m.tai_khoan.danh_tinh.vai,
                m.tai_khoan.nhom,
                m.tai_khoan.demo,
                m.tai_khoan.admin,
                m.mat_khau_hash,
            )
            for m in cac
        }
        assert khoa(da) == khoa(cho)
    assert kho_gia.da_dong is True
    assert audit_gia.da_dong is True, "port audit đã mở mà không ai đóng"
    assert kho_break_glass_gia.da_dong is True, "kho break-glass đã mở mà không ai đóng"
    # Engine đóng **trước** audit và trước pool, thứ tự ngược của thứ tự mở:
    # không đóng nó là một pool Neo4j cộng một client Qdrant sống qua lần tắt
    # tiến trình, và là phần kho KV chưa flush mất luôn (story 1.7).
    assert engine_gia.da_dong is True, "engine đã mở mà không ai đóng"


def test_lifespan_mo_kho_that_su_chay_ddl(monkeypatch):
    """`mo_kho_tai_khoan` phải chạy DDL, và bỏ `khoi_tao()` phải đỏ.

    Mọi ca khác monkeypatch chính hàm này, nên không ca nào chấm ruột nó. Bỏ
    `await kho.khoi_tao()` là bảng `users` không tồn tại ở lần deploy đầu và
    `dong_bo` nổ giữa lifespan - xa chỗ gây ra.
    """
    da_lam = []

    class KhoDoiKhoiTao:
        async def khoi_tao(self):
            da_lam.append("khoi_tao")

        async def dong(self):
            da_lam.append("dong")

    async def _mo(cau_hinh=None):
        return KhoDoiKhoiTao()

    monkeypatch.setattr(api_main.KhoTaiKhoan, "mo", classmethod(lambda cls: _mo()))
    asyncio.run(api_main.mo_kho_tai_khoan())
    assert da_lam == ["khoi_tao"]


def test_lifespan_mo_audit_that_su_chay_ddl(monkeypatch):
    """`mo_audit` phải chạy DDL, và bỏ `khoi_tao()` phải đỏ.

    Bản sao của ca ngay trên cho port audit: mọi ca lifespan khác monkeypatch
    chính `mo_audit`, nên không ca nào chấm ruột nó. Bỏ `await audit.khoi_tao()`
    là bảng `audit_log` không tồn tại ở lần deploy đầu và lần hoán policy đầu
    tiên nổ ở tầng mutation - tức một thao tác admin hỏng vì một DDL chưa chạy,
    xa chỗ gây ra.
    """
    da_lam = []

    class AuditDoiKhoiTao:
        async def khoi_tao(self):
            da_lam.append("khoi_tao")

        async def dong(self):
            da_lam.append("dong")

    async def _mo(cau_hinh=None):
        return AuditDoiKhoiTao()

    monkeypatch.setattr(
        api_main.AuditPostgres, "mo", classmethod(lambda cls, *a, **k: _mo())
    )
    asyncio.run(api_main.mo_audit())
    assert da_lam == ["khoi_tao"]


def test_lifespan_mo_kho_break_glass_that_su_chay_ddl(monkeypatch, kho_break_glass_gia):
    """`mo_kho_break_glass` phải chạy DDL (story 5.1), cùng lý do với hai ca trên.

    Bỏ `await kho.khoi_tao()` là hai bảng `breakglass_*` không tồn tại ở lần
    deploy đầu và lần xin đầu tiên nổ giữa một transaction, xa chỗ gây ra.
    """
    da_lam = []

    class KhoDoiKhoiTao:
        async def khoi_tao(self):
            da_lam.append("khoi_tao")

        async def dong(self):
            da_lam.append("dong")

    async def _mo(cau_hinh=None):
        return KhoDoiKhoiTao()

    monkeypatch.setattr(
        api_main.break_glass.KhoBreakGlass, "mo", classmethod(lambda cls, *a, **k: _mo())
    )
    # `mo_goc`: bản thật, vì fixture autouse của conftest đã thay tên trong module.
    asyncio.run(kho_break_glass_gia.mo_goc())
    assert da_lam == ["khoi_tao"]


def test_mo_kho_break_glass_hong_o_ddl_van_dong_pool(monkeypatch, kho_break_glass_gia):
    """Pool break-glass đã mở phải đóng khi `khoi_tao()` dội, không treo lại."""

    class KhoNoDDL:
        def __init__(self):
            self.da_dong = False

        async def khoi_tao(self):
            raise RuntimeError("DDL break-glass hỏng")

        async def dong(self):
            self.da_dong = True

    kho = KhoNoDDL()

    async def _tra(*a, **k):
        return kho

    monkeypatch.setattr(api_main.break_glass.KhoBreakGlass, "mo", classmethod(lambda cls, *a, **k: _tra()))
    with pytest.raises(RuntimeError):
        asyncio.run(kho_break_glass_gia.mo_goc())
    assert kho.da_dong is True


def test_mo_audit_hong_o_ddl_van_dong_pool():
    """Pool audit đã mở phải đóng khi `khoi_tao()` dội, không treo lại."""

    class AuditNoDDL:
        def __init__(self):
            self.da_dong = False

        async def khoi_tao(self):
            raise RuntimeError("DDL audit hỏng")

        async def dong(self):
            self.da_dong = True

    audit = AuditNoDDL()

    async def chay():
        goc = api_main.AuditPostgres.mo
        try:
            api_main.AuditPostgres.mo = classmethod(lambda cls, *a, **k: _tra())
            with pytest.raises(RuntimeError):
                await api_main.mo_audit()
        finally:
            api_main.AuditPostgres.mo = goc

    async def _tra():
        return audit

    asyncio.run(chay())
    assert audit.da_dong is True


@pytest.mark.parametrize(
    "cho_no", ["khoi_tao", "nap_tai_khoan", "dong_bo", "mo_audit", "mo_kho_break_glass", "mo_engine"]
)
def test_khoi_dong_hong_o_bat_ky_buoc_nao_cung_dong_pool(
    monkeypatch, kho_gia, audit_gia, kho_break_glass_gia, cho_no
):
    """Pool đã mở phải đóng ở mọi đường thoát của bước khởi động.

    Bốn bước hỏng được thật: DDL hỏng, seed hỏng (`IdentitySeedInvalid`), DB
    rớt giữa transaction đồng bộ, và - từ story 3.3 - dựng engine hỏng (thiếu
    key provider, `QDRANT_URL` sai, `config/hang-do-nhay.yaml` hỏng). Ba bước
    sau nằm **ngoài** `try/finally` của `yield`, nên không có `try` riêng thì
    pool asyncpg treo lại trong một tiến trình sắp chết.

    Bước engine là bước **cuối** trước `yield`, nên nó là bước duy nhất mà cả
    pool tài khoản lẫn port audit đều đã mở: ca này vì thế chấm cả hai được
    đóng, không chỉ một.
    """
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    if cho_no == "khoi_tao":
        class KhoNoDDL:
            def __init__(self):
                self.da_dong = False

            async def khoi_tao(self):
                raise RuntimeError("DDL hỏng")

            async def dong(self):
                self.da_dong = True

        kho = KhoNoDDL()

        async def _mo_lop(cls):
            return kho

        monkeypatch.setattr(api_main.KhoTaiKhoan, "mo", classmethod(_mo_lop))
        with pytest.raises(RuntimeError):
            asyncio.run(api_main.mo_kho_tai_khoan())
        assert kho.da_dong is True
        return

    async def _mo():
        return kho_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    _cam_audit(monkeypatch, audit_gia)
    if cho_no == "nap_tai_khoan":
        def _no():
            raise IdentitySeedInvalid("seed hỏng")

        monkeypatch.setattr(api_main, "nap_tai_khoan", _no)
        loi = IdentitySeedInvalid
    elif cho_no == "mo_audit":
        # Port audit mở **sau** khi pool tài khoản đã mở và seed đã đổ; pool
        # tài khoản phải đóng, và audit chưa mở nên không có gì để đóng.
        async def _no_audit():
            raise RuntimeError("audit không mở được")

        monkeypatch.setattr(api_main, "mo_audit", _no_audit)
        loi = RuntimeError
    elif cho_no == "mo_kho_break_glass":
        # Kho thứ tư mở **sau** audit (story 5.1): pool tài khoản và port audit
        # đều đã mở và phải đóng; kho break-glass chưa mở nên không có gì để đóng.
        async def _no_bg():
            raise RuntimeError("kho break-glass không mở được")

        monkeypatch.setattr(api_main, "mo_kho_break_glass", _no_bg)
        loi = RuntimeError
    elif cho_no == "mo_engine":
        async def _no_engine(audit):
            raise RuntimeError("engine không dựng được")

        monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _no_engine)
        loi = RuntimeError
    else:
        kho_gia.no_o_dong_bo = RuntimeError("DB rớt giữa transaction")
        loi = RuntimeError

    with pytest.raises(loi):
        with TestClient(api_main.app):
            pass
    assert kho_gia.da_dong is True, "pool đã mở mà không ai đóng"
    if cho_no in ("mo_kho_break_glass", "mo_engine"):
        assert audit_gia.da_dong is True, "port audit đã mở mà không ai đóng"
    if cho_no == "mo_engine":
        assert kho_break_glass_gia.da_dong is True, "kho break-glass đã mở mà không ai đóng"
    else:
        assert kho_break_glass_gia.da_dong is False, "kho break-glass chưa mở mà lại bị đóng"


def test_lifespan_nap_bang_nhom_ngay_luc_khoi_dong(monkeypatch, kho_gia):
    """Bảng nhóm hỏng phải giết tiến trình ở giây đầu, không ở giữa một truy hồi.

    `bang_nhom_mac_dinh` nạp lười ở lần đọc đầu, tức lần đầu một bản ghi đi qua
    tầng che. Không gọi nó trong lifespan thì một `config/nhom-phu-trach.yaml`
    hỏng để container lên `healthy` rồi nổ giữa chừng - cùng lý do với việc
    kiểm khóa ký trước khi mở kết nối nào.
    """
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    da_mo = []

    async def _mo():
        da_mo.append(1)
        return kho_gia

    def _no():
        raise NhomPhuTrachInvalid("bảng nhóm hỏng")

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    monkeypatch.setattr(api_main, "bang_nhom_mac_dinh", _no)
    with pytest.raises(NhomPhuTrachInvalid):
        with TestClient(api_main.app):
            pass
    assert da_mo == [], "phải từ chối trước khi mở kết nối nào"


def test_seed_hong_luc_phuc_vu_ra_envelope_chu_khong_500_tran(monkeypatch, client):
    """`GET /auth/tai-khoan` đọc lại seed mỗi lời gọi, nên nó hỏng *sau* khởi động.

    Ai đó sửa file trên máy chủ, hay volume `config/` rớt. Để
    `IdentitySeedInvalid` thoát ra là một 500 trần nằm ngoài envelope
    `{error: {code, message}}` mà test assert lên (AD-8), và nó in nguyên đường
    dẫn file cấu hình ra cho người gọi.
    """
    tok = _token(client, "dev01")

    def _no():
        raise IdentitySeedInvalid("/duong/dan/bi/lo/tai-khoan.yaml: hỏng")

    monkeypatch.setattr(api_main, "nap_tai_khoan", _no)
    kq = client.get("/auth/tai-khoan", headers={"Authorization": f"Bearer {tok}"})
    assert kq.status_code == 500
    assert kq.json()["error"]["code"] == api_main.MA_SEED_KHONG_DOC_DUOC
    assert "/duong/dan" not in kq.text, "đường dẫn cấu hình không ra ngoài"


# --- Seed thật: cờ quyền, cost bcrypt, mật khẩu ----------------------------


def test_co_demo_va_admin_cua_seed_that_duoc_ghim_bang_gia_tri():
    """Ca 403 ở trên chấm bản giả, nên seed thật không bị gì canh.

    Đột biến `admin: true` cho `ts01` trong `config/tai-khoan.yaml` được loader
    nhận và cả bộ test xanh - tức một tài khoản thường lặng lẽ thành quản trị.
    """
    cac_muc = nap_tai_khoan()
    assert {m.ten for m in cac_muc if m.tai_khoan.admin} == {"dev01"}
    assert {m.ten for m in cac_muc if m.tai_khoan.demo} == {"dev01", "demo01"}
    assert {m.ten for m in cac_muc} == {"ts01", "dev01", "demo01"}


def test_seed_that_co_dung_mot_tai_khoan_bat_mot_co():
    """Phép "demo **hoặc** admin" phải chấm được trên **cấu hình sẽ chạy**.

    `test_cua_demo_hoac_admin_la_phep_hoac` chấm bốn tổ hợp trên một
    `ClaimNguoiHoi` dựng tay. Seed thật thì chỉ có "cả hai" (`dev01`) và "không
    có gì" (`ts01`), nên qua HTTP không ca nào phân biệt được phép **hoặc** với
    phép **và**: `demo and admin` cho đúng cùng kết quả trên cả hai tài khoản.
    `demo01` là ca thứ ba, và nó là ca duy nhất bắt được đột biến đó.
    """
    mot_co = [
        m.ten
        for m in nap_tai_khoan()
        if m.tai_khoan.demo is not m.tai_khoan.admin
    ]
    assert mot_co == ["demo01"], mot_co


def test_tai_khoan_demo_khong_admin_qua_cua_bang_chinh_co_cua_seed_that(
    monkeypatch,
):
    """`demo01` gọi `/auth/tai-khoan` ra 200, và hai cờ lấy từ seed thật.

    Ca đi qua HTTP chứ không gọi thẳng `doi_demo_hoac_admin`: cửa quyền phải
    chứng minh được ở chỗ nó thật sự đứng, tức trên một token do
    `POST /auth/login` phát ra từ một dòng bảng mang đúng hai cờ của
    `config/tai-khoan.yaml`. Bảng `users` vẫn là bản giả (bộ này không cần
    Postgres), nhưng **hai cờ thì không giả**: chúng đọc từ chính seed, nên đổi
    `demo: false` cho `demo01` trong file cấu hình là ca này đỏ.
    """
    muc = next(m for m in nap_tai_khoan() if m.ten == "demo01")
    assert (muc.tai_khoan.demo, muc.tai_khoan.admin) == (True, False)

    ten_go = "DEMO01"
    kho = KhoGia(
        {
            ten_go: _dong(
                muc.ten,
                role=muc.tai_khoan.danh_tinh.vai,
                demo=muc.tai_khoan.demo,
                admin=muc.tai_khoan.admin,
            )
        }
    )
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    _cam_audit(monkeypatch, AuditGia())
    _cam_engine(monkeypatch, EngineGia())

    async def _mo():
        return kho

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    with TestClient(api_main.app) as c:
        kq = c.post("/auth/login", json={"tai_khoan": ten_go, "mat_khau": MAT_KHAU})
        assert kq.status_code == 200, kq.text
        tok = kq.json()["token"]
        claim = jwt.decode(tok, KHOA_TEST, algorithms=["HS256"])
        assert (claim["demo"], claim["admin"]) == (True, False)
        ra = c.get("/auth/tai-khoan", headers={"Authorization": f"Bearer {tok}"})
    assert ra.status_code == 200, ra.text
    assert {m["tai_khoan"] for m in ra.json()["tai_khoan"]} == {
        m.ten for m in nap_tai_khoan()
    }


def _cost(hash_mk: str) -> int:
    """Cost (log2 số vòng) đọc từ chính chuỗi hash: `$2b$<cost>$...`."""
    return int(hash_mk.split("$")[2])


def test_cost_cua_hash_gia_bang_cost_cua_seed_that():
    """Cả lập luận chống kênh dò thời gian đứng trên đúng đẳng thức này.

    `HASH_GIA` là hash mà nhánh "không có tài khoản" so vào. Nếu seed dùng cost
    13 còn `HASH_GIA` cost 12 thì nhánh không-có-tài-khoản nhanh hơn gấp đôi, và
    chênh đó đủ để liệt kê tài khoản tồn tại - đúng thứ hai hàng I/O Matrix
    dựng ra để chống. Không gì canh đẳng thức này ngoài ca ở đây.
    """
    cost_gia = _cost(HASH_GIA)
    for m in nap_tai_khoan():
        assert _cost(m.mat_khau_hash) == cost_gia, m.ten


# --- Bảng `users` thật ------------------------------------------------------


@pytest.mark.postgres
def test_bang_users_that_dong_bo_va_tra_dung_dong():
    """DDL idempotent, `dong_bo` chạy lại không nhân đôi, `tra` trả `None` cho tài khoản lạ."""
    from api.tai_khoan import KhoTaiKhoan

    async def chay():
        kho = await KhoTaiKhoan.mo()
        try:
            await kho.khoi_tao()
            await kho.khoi_tao()  # idempotent
            cac_muc = nap_tai_khoan()
            await kho.dong_bo(cac_muc)
            await kho.dong_bo(cac_muc)
            dong = [await kho.tra(m.ten) for m in cac_muc]
            return cac_muc, dong, await kho.tra("khong-co-tai-khoan-nay")
        finally:
            await kho.dong()

    cac_muc, dong, la = asyncio.run(chay())
    assert la is None
    for m, d in zip(cac_muc, dong):
        assert d is not None
        assert d.account == m.ten
        assert d.mat_khau_hash == m.mat_khau_hash
        assert d.role == m.tai_khoan.danh_tinh.vai
        assert d.group_name == m.tai_khoan.nhom
        assert d.khong_gian == m.tai_khoan.danh_tinh.khong_gian
        assert (d.demo, d.admin) == (m.tai_khoan.demo, m.tai_khoan.admin)


@pytest.mark.postgres
def test_dong_bo_that_su_cap_nhat_dong_da_co_va_khong_xoa_dong_la():
    """`ON CONFLICT DO UPDATE` là đường đổi mật khẩu và thu hồi quyền **duy nhất**.

    Không có API đổi mật khẩu (Never của story), nên sửa `config/tai-khoan.yaml`
    rồi khởi động lại là cách duy nhất. Nếu câu SQL im lặng thành `DO NOTHING`,
    hay bỏ riêng `admin = EXCLUDED.admin`, thì một tài khoản giữ quyền quản trị
    qua một lần deploy được coi là đã thu hồi - và ca `dong_bo` hai lần với
    **cùng** một danh sách không thấy điều đó.

    Vế thứ hai: dòng không có trong seed phải **còn lại** sau `dong_bo`. Xóa nó
    là xóa chủ sở hữu của những hàng `audit_log` và (từ Epic 5) `breakglass_*`
    trỏ tới nó, và một seed gõ sót một dòng khi đó thành một phép xóa im lặng.
    """
    from dataclasses import replace

    from api.tai_khoan import KhoTaiKhoan

    la = "tk-la-cua-test-3-1"
    goc = nap_tai_khoan()
    dau = goc[0]

    # Mục đã đổi: hash khác, và hai cờ đảo chiều so với seed.
    khac = replace(
        dau,
        mat_khau_hash="$2b$12$" + "a" * 53,
        tai_khoan=replace(
            dau.tai_khoan,
            nhom="Nhom Da Doi",
            demo=not dau.tai_khoan.demo,
            admin=not dau.tai_khoan.admin,
        ),
    )

    async def chay():
        kho = await KhoTaiKhoan.mo()
        try:
            await kho.khoi_tao()
            await kho.dong_bo(goc)
            async with kho._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (account, mat_khau_hash, role, group_name,"
                    " khong_gian, demo, admin) VALUES ($1,$2,$3,$4,$5,$6,$7)"
                    " ON CONFLICT (account) DO NOTHING",
                    la, "$2b$12$" + "b" * 53, "devops", "DevOps", "synth", False, False,
                )
            await kho.dong_bo((khac,))
            return await kho.tra(khac.ten), await kho.tra(la)
        finally:
            async with kho._pool.acquire() as conn:
                await conn.execute("DELETE FROM users WHERE account = $1", la)
            await kho.dong_bo(goc)
            await kho.dong()

    sau, dong_la = asyncio.run(chay())
    assert sau is not None
    assert sau.mat_khau_hash == khac.mat_khau_hash, "hash không được cập nhật"
    assert sau.group_name == "Nhom Da Doi", "group_name không được cập nhật"
    assert sau.demo == khac.tai_khoan.demo, "cờ demo không được cập nhật"
    assert sau.admin == khac.tai_khoan.admin, "cờ admin không được cập nhật"
    assert dong_la is not None, "`dong_bo` không được xóa tài khoản vắng mặt trong seed"


def test_mat_khau_seed_that_dang_nhap_duoc():
    """Hash trong `config/tai-khoan.yaml` khớp mật khẩu trong `.env`.

    Ca duy nhất chạm cả hai nửa của cặp seed, và là chỗ duy nhất bắt được việc
    ai đó sửa hash mà quên sửa mật khẩu (hay ngược lại) - hai file, một cặp,
    và chỉ một nửa vào git.

    Đọc **đúng một biến** qua cửa chung `eval.nap_bien_tu_env`, không source cả
    `.env`: key LLM thật không được lọt vào môi trường bộ test (AGENTS.md).
    Máy vừa clone chưa có `.env` thì bỏ qua chứ không đỏ; máy dev và máy chủ
    đều có nên ca này chạy thật ở cả hai chỗ.
    """
    from eval import GOC_REPO, nap_bien_tu_env

    if not (GOC_REPO / ".env").exists():
        pytest.skip("`.env` gốc repo chưa có; mật khẩu demo không vào git")
    # Lặp trên chính seed, không trên một tuple gõ tay: thêm một tài khoản thứ
    # ba mà không ai đòi biến `DEMO_MAT_KHAU_<TÊN>` của nó là một tài khoản
    # không đăng nhập được, và không gì đỏ.
    for muc in nap_tai_khoan():
        bien = f"DEMO_MAT_KHAU_{muc.ten.upper()}"
        mk = nap_bien_tu_env(bien)
        assert mk, f"`.env` phải khai {bien} (xem .env.example)"
        assert so_mat_khau(mk, muc.mat_khau_hash) is True, muc.ten
        assert so_mat_khau(mk + "x", muc.mat_khau_hash) is False, muc.ten
