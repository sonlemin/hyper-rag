"""Endpoint hỏi đáp và envelope AD-8 (story 3.3, FR-13).

Đặc tả viết trước cơ chế (FR-27): mọi hàng I/O Matrix của story nằm ở đây, cộng
bốn mệnh đề mà không hàng nào của bảng phát biểu được một mình.

- **Hai vai hai ngữ cảnh.** Cùng một câu hỏi qua hai token cho hai
  `PermissionContext` khác nhau và hai `meta.role` khác nhau, trên cùng một hình
  dạng envelope. Đó là cổng M1 nói lại bằng HTTP.
- **`meta` là tập trường đóng.** So bằng tập khóa chứ không bằng "có chứa": một
  trường thừa ở đây - thời gian xử lý, một số đếm, một cờ - là một kênh dò phá
  đúng tính chất byte-identical mà lượt từ chối của story 3.5 sẽ dựa vào.
- **Đúng một `PermissionContext` mỗi request, và `kind` luôn là `user`.** Đếm
  bằng cách thay `api.hoi_dap.ngu_canh_cua`; hai lần dựng trong một request là
  hai lần tra bảng chính sách, và giữa chúng là một `await` mà một lần hoán
  policy chen vào được.
- **Lớp thứ ba của NFR-10** (khoản ledger 1.2): một ngữ cảnh `kind=system` **đến
  từ ngoài** bị handler từ chối, không truy hồi thô. Hai lớp đầu là import-lint
  (phía module) và `SystemContextNested` (ngữ cảnh sinh giữa chừng).

Không Postgres, không kho tri thức, không mạng: bảng `users`, port audit và
engine đều là bản giả, đúng khuôn mà `tests/test_xac_thuc.py` đặt. Cái đang được
chấm là **hợp đồng của handler**, không phải một driver; đường e2e qua ba
adapter thật đã có ở `tests/test_cong_m1.py`.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from api import hoi_dap
from api import main as api_main
from api.hoi_dap import (
    DAI_CAU_HOI_TOI_DA,
    KHOA_ENVELOPE,
    KHOA_META,
    MA_CAU_HOI_QUA_DAI,
    MA_CAU_HOI_RONG,
    MA_KHO_KHONG_SAN_SANG,
    MA_LLM_LOI,
    MA_LLM_QUA_HAN,
    MA_NGU_CANH_KHONG_PHAI_VAI,
    MA_THAN_YEU_CAU_LA,
    dung_envelope,
    graph_rong,
)
from api.xac_thuc import BIEN_KHOA_KY, MA_TOKEN_KHONG_HOP_LE
from adapters.neo4j import Neo4jUnavailable
from adapters.qdrant import QdrantIndexMissing
from adapters.thu_lai import ChanNhipQuaLau
from core.audit import EVENT_QUERY, TIER_OBSERVATION
from core.identity import RoleUnknown
from core.permission import KIND_USER, PermissionContextMissing
from tests.test_xac_thuc import (
    KHOA_TEST,
    MAT_KHAU,
    AuditGia,
    EngineGia,
    KhoGia,
    _dong,
)

TEN_GO = {"ts01": "TS01", "dev01": "DEV01"}
CAU_HOI = "App01 trả lỗi 502 thì xử lý thế nào"


@pytest.fixture
def kho_gia():
    return KhoGia(
        {
            TEN_GO["ts01"]: _dong("ts01"),
            TEN_GO["dev01"]: _dong("dev01", role="devops", demo=True, admin=True),
        }
    )


@pytest.fixture
def audit_gia():
    return AuditGia()


@pytest.fixture
def engine_gia():
    return EngineGia()


@pytest.fixture
def client(monkeypatch, kho_gia, audit_gia, engine_gia):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return engine_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        yield c


def _bearer(client, tai_khoan: str) -> dict:
    kq = client.post(
        "/auth/login", json={"tai_khoan": TEN_GO[tai_khoan], "mat_khau": MAT_KHAU}
    )
    assert kq.status_code == 200, kq.text
    return {"Authorization": "Bearer " + kq.json()["token"]}


def _hoi(client, tai_khoan: str, than=None):
    return client.post(
        "/hoi-dap",
        json={"cau_hoi": CAU_HOI} if than is None else than,
        headers=_bearer(client, tai_khoan),
    )


# --- Hàng "Hỏi hợp lệ" ---------------------------------------------------------


def test_hoi_hop_le_tra_dung_nam_khoa_envelope(client, engine_gia):
    """Hàng đầu của I/O Matrix, và là hợp đồng đóng băng của AD-8.

    So **tập khóa cấp một**, không phải "có chứa": một khóa thứ sáu ở đây là một
    hợp đồng khác, và nó phải đi qua correct-course chứ không qua một lần sửa
    handler.
    """
    kq = _hoi(client, "ts01")
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert tuple(than) == KHOA_ENVELOPE
    assert than["answer"] == engine_gia.tra_loi
    assert than["refused"] is False
    assert than["citations"] == []
    assert than["graph"] == graph_rong()
    assert engine_gia.cau_hoi == [CAU_HOI]


def test_meta_dung_ba_truong_va_khong_mang_gi_doi_theo_luot(client):
    """`meta` là **tập đóng**: đúng ba khóa, không thừa một cái nào.

    Vì sao chấm chặt tới mức so tập: `meta` đi ra trong cả lượt trả lời lẫn lượt
    từ chối byte-identical của story 3.5. Một trường đổi theo lý do từ chối -
    thời gian xử lý, số citation đã lọc, một cờ - là một kênh dò, và nó là loại
    lỗ mà không ai nhìn thấy khi đọc một phản hồi thành công.
    """
    meta = _hoi(client, "ts01").json()["meta"]
    assert tuple(meta) == KHOA_META
    assert meta["role"] == "tech_support"
    # `space` đối chiếu với chính claim của token, không chỉ "có mặt": cách ly
    # theo `space` (AD-12) là thuộc tính của người hỏi, và một `meta.space` lấy
    # từ chỗ khác là một envelope khai sai khoang thuê bao mà truy hồi vừa chạy.
    toi = client.get("/auth/toi", headers=_bearer(client, "ts01")).json()
    assert meta["space"] == toi["khong_gian"] == "synth"
    assert meta["policy_version"]
    for cam in ("thoi_gian", "mili_giay", "duration", "timestamp", "so_citation"):
        assert cam not in meta


def test_policy_version_bang_hash_bang_dang_chay(client):
    """`meta.policy_version` là hash của bảng tiến trình đang chạy, không một chuỗi rời."""
    dang_chay = api_main.app.state.kho_chinh_sach.hien_tai()
    assert _hoi(client, "ts01").json()["meta"]["policy_version"] == dang_chay.policy_version


# --- Hàng "Hai vai hai kết quả" -----------------------------------------------


def test_hai_vai_hai_ngu_canh_cung_hinh_dang_envelope(client, engine_gia):
    """Cổng M1 nói lại bằng HTTP: cùng câu hỏi, hai token, hai ngữ cảnh quyền.

    Chấm cả hai đầu. Đầu ngoài: `meta.role` khác nhau trên cùng năm khóa. Đầu
    trong: hai `PermissionContext` mà engine đọc được **bên trong** `hoi_dap`
    khác nhau ở vai, ở `allowed_keys`, và cả hai đều là ngữ cảnh vai.

    Đọc ngữ cảnh trong `EngineGia.hoi_dap` chứ không sau lời gọi là chỗ duy nhất
    chứng minh `use_context` bọc **trọn** `hoi_dap` - contextvar đã được reset
    khi handler trả về.
    """
    vai = []
    for tk in ("dev01", "ts01"):
        than = _hoi(client, tk).json()
        assert tuple(than) == KHOA_ENVELOPE
        vai.append(than["meta"]["role"])
    assert vai == ["devops", "tech_support"]

    a, b = engine_gia.ngu_canh
    assert (a.role, b.role) == ("devops", "tech_support")
    assert a.kind == b.kind == KIND_USER
    assert a.allowed_keys != b.allowed_keys, (
        "hai vai mà cùng tập khóa nghĩa là bảng chính sách không vào tới ngữ cảnh"
    )
    assert (a.real_account, b.real_account) == ("dev01", "ts01")


def test_ngu_canh_dung_dung_mot_lan_moi_request_va_kind_luon_la_user(
    client, monkeypatch, engine_gia
):
    """Đúng **một** `PermissionContext` mỗi request, và `kind` luôn `user`.

    Hai lần dựng trong một request là hai lần tra bảng chính sách, và giữa
    chúng là một `await` - tức một lần `POST /admin/policy` chen vào được, và
    khi đó nửa đầu request chạy bảng A còn nửa sau chạy bảng B (AD-3).

    Đếm bằng cách bọc chính cửa hợp lệ, không bằng cách đọc một biến đếm trong
    handler: cửa đó là thứ luật import-lint bắt buộc đi qua, nên một đường dựng
    thứ hai mà bộ đếm không thấy cũng là một đường mà import-lint không cho tồn
    tại.
    """
    goc = hoi_dap.ngu_canh_cua
    dem = []

    def _dem(danh_tinh, policy, **them):
        dem.append(danh_tinh)
        return goc(danh_tinh, policy, **them)

    monkeypatch.setattr(hoi_dap, "ngu_canh_cua", _dem)
    assert _hoi(client, "ts01").status_code == 200
    assert len(dem) == 1, f"dựng {len(dem)} ngữ cảnh trong một request"
    assert [n.kind for n in engine_gia.ngu_canh] == [KIND_USER]


# --- Hàng "Câu hỏi rỗng" và "Câu hỏi quá dài" ----------------------------------


@pytest.mark.parametrize("cau_hoi", ["", "   ", "\n\t "], ids=["rong", "dau_cach", "trang"])
def test_cau_hoi_rong_ra_400(client, engine_gia, cau_hoi):
    kq = _hoi(client, "ts01", {"cau_hoi": cau_hoi})
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == MA_CAU_HOI_RONG
    assert engine_gia.cau_hoi == [], "câu hỏi rỗng không đáng một lời gọi nào"


def test_cau_hoi_qua_dai_ra_400_va_mot_ma_khac(client, engine_gia):
    """Mã **khác** ca rỗng: "chưa gõ gì" và "dán quá nhiều" là hai việc khác nhau."""
    kq = _hoi(client, "ts01", {"cau_hoi": "x" * (DAI_CAU_HOI_TOI_DA + 1)})
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == MA_CAU_HOI_QUA_DAI
    assert engine_gia.cau_hoi == []


def test_cau_hoi_dung_bang_tran_van_qua(client, engine_gia):
    """Biên là `<=`, không phải `<`: một trần off-by-one là một trần khác trần đã khai."""
    assert _hoi(client, "ts01", {"cau_hoi": "x" * DAI_CAU_HOI_TOI_DA}).status_code == 200
    assert len(engine_gia.cau_hoi) == 1


# --- Hàng "Thân mang trường lạ" -----------------------------------------------


@pytest.mark.parametrize(
    "than",
    [
        {"cau_hoi": "x", "mode": "local"},
        {"cau_hoi": "x", "role": "devops"},
        {"cau_hoi": "x", "space": "real"},
        {"cau_hoi": "x", "kind": "system"},
        {"cau_hoi": "x", "grant_ids": ["g1"]},
        {},
        {"cau_hoi": 7},
    ],
    ids=["mode", "role", "space", "kind", "grant_ids", "thieu", "sai_kieu"],
)
def test_than_mang_truong_la_ra_400_truoc_moi_loi_goi(client, engine_gia, than):
    """Bốn tên quyền không bao giờ đến từ thân, và một thân sai không tốn một lời gọi.

    `extra="forbid"` chứ không phải "bỏ qua trường lạ": nhận rồi bỏ qua không
    sai lúc chạy nhưng nó dạy người gọi rằng trường đó có nghĩa, và nó là chỗ để
    một phiên bản sau đọc nó thật. `grant_ids` có mặt trong danh sách vì
    break-glass của Epic 5 sẽ là cám dỗ đầu tiên để nới cửa này.
    """
    kq = _hoi(client, "ts01", than)
    assert kq.status_code == 400, kq.text
    assert kq.json()["error"]["code"] == MA_THAN_YEU_CAU_LA
    assert engine_gia.cau_hoi == []


def test_than_400_khong_lo_duong_dan_hay_noi_dung_nguoi_goi_gui(client):
    """422 thô của FastAPI dội lại `loc`/`input`; envelope của mình thì không."""
    kq = _hoi(client, "ts01", {"cau_hoi": "x", "mode": "/etc/passwd"})
    than = kq.json()
    assert tuple(than) == ("error",)
    assert set(than["error"]) == {"code", "message"}
    thong_diep = than["error"]["message"]
    assert "/etc/passwd" not in thong_diep
    assert "hyper" not in thong_diep and "config" not in thong_diep


# --- Hàng "Không token" --------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [None, {"Authorization": "Bearer rac"}, {"Authorization": "Basic x"}],
    ids=["thieu", "token_rac", "sai_luoc_do"],
)
def test_khong_token_ra_401_truoc_ca_phep_kiem_than(client, engine_gia, headers):
    """Cửa đứng ở **tuyến** nên nó chạy trước cả lược đồ thân yêu cầu.

    Ca thân sai cộng token thiếu phải ra 401, không 400: nói "thân của bạn sai"
    cho một người chưa xác thực là trả lời một câu hỏi họ chưa được phép hỏi.
    """
    kq = client.post(
        "/hoi-dap", json={"cau_hoi": "x", "mode": "local"}, headers=headers or {}
    )
    assert kq.status_code == 401
    assert kq.json()["error"]["code"] == MA_TOKEN_KHONG_HOP_LE
    assert engine_gia.cau_hoi == []


# --- Hàng "Vai không có trong bảng" --------------------------------------------


def test_vai_la_ra_403_va_khong_cham_kho(monkeypatch, kho_gia, audit_gia, engine_gia):
    """Token hợp lệ mang một vai không có trong bảng đang chạy: 403, không chạm kho.

    Ca có thật chứ không giả định: token sống 12 giờ, nên một lần hoán policy
    sang bảng không có vai ấy, hay một lần sửa seed, để lại đúng tình huống này
    trên một token đã phát.

    Fail-closed: **không** thành một ngữ cảnh không thấy gì. Ngữ cảnh rỗng chạy
    tiếp được và trông giống hệt "người này không được xem gì".
    """
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    kho_gia.theo_ten["LA"] = _dong("la01", role="vai_khong_co_trong_bang")

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return engine_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        token = c.post("/auth/login", json={"tai_khoan": "LA", "mat_khau": MAT_KHAU})
        assert token.status_code == 200, token.text
        kq = c.post(
            "/hoi-dap",
            json={"cau_hoi": CAU_HOI},
            headers={"Authorization": "Bearer " + token.json()["token"]},
        )
    assert kq.status_code == 403, kq.text
    assert kq.json()["error"]["code"] == RoleUnknown.code
    assert engine_gia.cau_hoi == []
    # Thông điệp không liệt kê danh mục vai: một 403 là chỗ rẻ nhất để đếm xem
    # bảng chính sách đang chạy có những vai nào.
    assert "vai_khong_co_trong_bang" not in kq.json()["error"]["message"]


# --- Hàng lỗi của đường truy hồi -----------------------------------------------


@pytest.mark.parametrize(
    "loi, http, ma",
    [
        (PermissionContextMissing("mất ngữ cảnh"), 500, PermissionContextMissing.code),
        (QdrantIndexMissing("collection chưa có"), 503, MA_KHO_KHONG_SAN_SANG),
        (Neo4jUnavailable("neo4j chưa lên"), 503, MA_KHO_KHONG_SAN_SANG),
        (ConnectionRefusedError("qdrant chết"), 503, MA_KHO_KHONG_SAN_SANG),
        (TimeoutError("llm treo"), 504, MA_LLM_QUA_HAN),
        (ChanNhipQuaLau("provider đòi chờ 3600 giây"), 502, MA_LLM_LOI),
    ],
    ids=["thieu_ngu_canh", "qdrant_vang", "neo4j_chet", "mang_dut", "treo", "chan_nhip"],
)
def test_loi_truy_hoi_ra_dung_ma_on_dinh(client, engine_gia, loi, http, ma):
    """Mỗi kiểu hỏng một mã SCREAMING_SNAKE ổn định, và **không** giả dạng từ chối.

    Lỗi hệ thống khác từ chối, và đó không phải một chi tiết trình bày: một 502
    hiện thành một lượt "không tìm thấy thông tin" là hệ nói dối về chính trạng
    thái của nó, và nó còn làm mẫu số hai cột của Đo 2 đếm nhầm.
    """
    engine_gia.loi = loi
    kq = _hoi(client, "ts01")
    assert kq.status_code == http, kq.text
    than = kq.json()
    assert tuple(than) == ("error",)
    assert than["error"]["code"] == ma
    assert "refused" not in than


def test_loi_llm_mang_ma_http_ra_502(client, engine_gia):
    """Provider trả 429/5xx sau khi ngân sách truy hồi cạn: 502, đọc theo *hình dạng*.

    Không import SDK nào để nhận diện: `adapters.thu_lai.ma_http_cua` đọc
    `status_code`/`status`/`code` trên chính ngoại lệ và trên `response` của nó,
    đúng ba tên mà các SDK dùng.
    """

    class _LoiProvider(Exception):
        status_code = 429

    engine_gia.loi = _LoiProvider("rate limit")
    kq = _hoi(client, "ts01")
    assert kq.status_code == 502
    assert kq.json()["error"]["code"] == MA_LLM_LOI


def test_loi_cua_sdk_kho_mang_ma_http_van_la_503_khong_phai_502(client, engine_gia):
    """Thứ tự nhánh là nội dung: nhận diện lỗi **kho** trước khi hỏi mã HTTP.

    `qdrant_client.http.exceptions.UnexpectedResponse` **có** `.status_code`, và
    `adapters/qdrant.py` chỉ bọc *một số* đường vào `QdrantIndexMissing`. Hỏi mã
    HTTP trước là báo một Qdrant trả 500 thành "không gọi được mô hình ngôn
    ngữ", tức chỉ người vận hành đi tìm sai chỗ.

    Bản giả mang đúng hai dấu hiệu mà đường thật mang: một `status_code`, và một
    lớp sinh ra từ module của SDK kho.
    """
    class _LoiQdrant(Exception):
        status_code = 500

    _LoiQdrant.__module__ = "qdrant_client.http.exceptions"
    engine_gia.loi = _LoiQdrant("Unexpected Response: 500")
    kq = _hoi(client, "ts01")
    assert kq.status_code == 503, kq.text
    assert kq.json()["error"]["code"] == MA_KHO_KHONG_SAN_SANG

    # Chiều ngược lại giữ nguyên: lỗi **provider** mang mã HTTP vẫn là 502.
    class _LoiProvider(Exception):
        status_code = 500

    _LoiProvider.__module__ = "openai"
    engine_gia.loi = _LoiProvider("server error")
    assert _hoi(client, "ts01").json()["error"]["code"] == MA_LLM_LOI


def test_loi_mang_bi_sdk_boc_van_ra_503(client, engine_gia):
    """Lỗi mạng đã bọc phải được nhận, không rơi ra ngoài cả bốn nhánh.

    `openai.APIConnectionError` **không** phải `OSError`; nó giữ lỗi gốc ở
    `__cause__`. Một phép `isinstance(loi, (ConnectionError, OSError))` để lọt
    trọn nhóm đó, và khi đó một provider mất mạng cho một 500 trần thay vì một
    mã ổn định. `adapters.thu_lai.la_loi_mang_tam_thoi` đi hết chuỗi nguyên nhân.
    """
    class _LoiBoc(Exception):
        pass

    goc = ConnectionResetError("connection reset by peer")
    try:
        raise _LoiBoc("connection error") from goc
    except _LoiBoc as e:
        engine_gia.loi = e
    kq = _hoi(client, "ts01")
    assert kq.status_code == 503, kq.text
    assert kq.json()["error"]["code"] == MA_KHO_KHONG_SAN_SANG


def test_loi_la_khong_bi_bia_ma(client, engine_gia):
    """Ngoại lệ chưa ai xếp loại **không** được gán một mã bịa.

    Bịa một mã cho nó là làm mất chính thông tin cần để xếp loại nó lần sau, và
    là cách một lỗi cấu trúc của tiến trình hiện thành một "kho chưa sẵn sàng".
    """
    engine_gia.loi = ValueError("một lỗi chưa ai xếp loại")
    with pytest.raises(ValueError):
        _hoi(client, "ts01")


def test_than_loi_khong_mang_duong_dan_hay_ten_container(client, engine_gia):
    """Thân lỗi không mang đường dẫn hệ thống, tên container hay tên biến môi trường."""
    engine_gia.loi = QdrantIndexMissing(
        "collection 'synth_hyperedges' chưa tồn tại trên http://qdrant:6333"
    )
    thong_diep = _hoi(client, "ts01").json()["error"]["message"]
    for cam in ("qdrant", "6333", "http", "/", "QDRANT_URL", "synth"):
        assert cam not in thong_diep, f"thân lỗi lộ {cam!r}"


# --- Hàng "Audit hỏng" ---------------------------------------------------------


def test_audit_hong_khong_lam_hong_cau_tra_loi(client, audit_gia, engine_gia, caplog):
    """Sự kiện truy vấn là tầng **observation**: port hỏng thì WARNING, câu trả lời vẫn về.

    Một Postgres chết không được làm câu hỏi của người dùng chết theo (AD-16).
    """
    audit_gia.no = RuntimeError("audit_log chết")
    with caplog.at_level("WARNING"):
        kq = _hoi(client, "ts01")
    assert kq.status_code == 200
    assert kq.json()["answer"] == engine_gia.tra_loi
    assert any("audit observation" in r.getMessage() for r in caplog.records), caplog.text


def test_su_kien_query_ghi_thoi_gian_o_tang_observation(client, audit_gia):
    """AC cuối của story: thời gian truy vấn ghi qua audit làm số liệu NFR-08.

    `hyperedge_ids` rỗng ở đây vì `EngineGia` mặc định không mang citation nào;
    từ story 3.4 nó là dãy `id` của citations, và ca có citation nằm ở
    `tests/test_trich_dan.py`. Rỗng là đúng hình dạng, không phải một số giả vờ.
    """
    assert _hoi(client, "dev01").status_code == 200
    su_kien = [sk for sk in audit_gia.su_kien if sk.event == EVENT_QUERY]
    assert len(su_kien) == 1
    sk = su_kien[0]
    assert sk.tier == TIER_OBSERVATION
    assert (sk.act, sk.role) == ("dev01", "devops")
    assert sk.hyperedge_ids == ()
    assert isinstance(sk.chi_tiet[hoi_dap.CT_MILI_GIAY], float)
    assert sk.chi_tiet[hoi_dap.CT_MILI_GIAY] >= 0


def test_su_kien_query_ghi_tap_thay_khong_phai_tap_dung(monkeypatch, kho_gia, audit_gia):
    """Story 3.8: `hyperedge_ids` là `KetQuaHoiDap.hyperedge_da_thay`, không phải dãy id citation."""
    from tests.test_trich_dan import _td

    engine = EngineGia(trich_dan=(_td("he-1"),), hyperedge_da_thay=("he-1", "he-2"))
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return engine

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        kq = _hoi(c, "dev01")
    assert kq.status_code == 200, kq.text
    assert [x["id"] for x in kq.json()["citations"]] == ["he-1"]
    sk = [s for s in audit_gia.su_kien if s.event == EVENT_QUERY]
    assert len(sk) == 1 and sk[0].hyperedge_ids == ("he-1", "he-2")


def test_khong_ghi_su_kien_query_khi_truy_hoi_hong(client, audit_gia, engine_gia):
    """Một 502 không được vào mẫu số thời gian của NFR-08.

    Trộn thời gian của một lượt trả lời thật với thời gian của một lần chạm 502
    là làm mẫu số vô nghĩa; sự kiện của lượt hỏng là story 3.6.
    """
    engine_gia.loi = TimeoutError("treo")
    assert _hoi(client, "ts01").status_code == 504
    assert [sk for sk in audit_gia.su_kien if sk.event == EVENT_QUERY] == []


# --- Hàng "`mode` lạ ở tầng engine" -------------------------------------------


def test_mode_la_o_tang_engine_ra_ma_cua_du_an(workspace_dir):
    """`QueryParam(mode="local")` là một mã lỗi của dự án, không `UnboundLocalError`.

    Ca ở tầng engine chứ không tầng HTTP: thân request không mang `mode` được
    (`extra="forbid"`), nên chỗ duy nhất `mode` lạ đi vào là một nơi gọi trong
    repo. Cửa phải đứng **trước** khi chạm `vendor/`, vì
    `hypergraphrag.py:497` chỉ có nhánh `hybrid` và mọi mode khác rơi vào một
    biến chưa gán (khoản ledger 1.7).
    """
    from adapters.engine import MODE_HO_TRO, QueryModeKhongHoTro
    from hypergraphrag.base import QueryParam
    from tests.gia_lap_llm import LLMGia
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine

    client_q = QdrantGhiLai()
    driver = Neo4jGhiLai()
    engine = dung_engine(workspace_dir, client_q, driver, LLMGia())
    for mode in ("local", "global", "naive", ""):
        with pytest.raises(QueryModeKhongHoTro) as loi:
            asyncio.run(engine.aquery("x", QueryParam(mode=mode)))
        assert loi.value.code == "QUERY_MODE_KHONG_HO_TRO"
    assert MODE_HO_TRO == {"hybrid"}
    # Không lời gọi nào tới kho: cửa đứng trước `super().aquery`.
    assert client_q.cac_loi_goi("query_points") == []


# --- NFR-10 lớp thứ ba: ngữ cảnh hệ thống đến từ ngoài -------------------------


def test_ngu_canh_he_thong_den_tu_ngoai_bi_handler_tu_choi(
    client, monkeypatch, engine_gia
):
    """Lớp thứ ba và cuối của NFR-10 (khoản ledger 1.2), ở đúng tầng handler.

    Hai lớp đầu canh hai đường khác: `tests/test_import_lint.py` canh phía module
    (ai được import `core.system_context`), và `core.permission.use_context` dội
    `SystemContextNested` khi một ngữ cảnh hệ thống sinh ra **giữa chừng** một
    request. Cửa này chặn một ngữ cảnh hệ thống **đến từ ngoài**: handler dựng
    ngữ cảnh xong thì hỏi lại `kind`, và một thứ không phải ngữ cảnh vai không
    được đi tiếp tới kho.

    Đột biến dựng bằng cách thay chính cửa hợp lệ, tức đúng hình dạng mà một
    đường nối sai sẽ có; không dựng `PermissionContext(kind="system")` tay được,
    vì `core/permission.py` có sentinel chặn và `test_import_lint.py` cấm.
    """
    from core.system_context import system_context

    monkeypatch.setattr(
        hoi_dap,
        "ngu_canh_cua",
        lambda danh_tinh, policy, **_: system_context(
            space=danh_tinh.khong_gian, policy_version=policy.policy_version
        ),
    )
    kq = _hoi(client, "ts01")
    assert kq.status_code == 500
    assert kq.json()["error"]["code"] == MA_NGU_CANH_KHONG_PHAI_VAI
    assert engine_gia.cau_hoi == [], "không truy hồi dưới một ngữ cảnh không phải vai"


# --- Serializer envelope -------------------------------------------------------


def test_serializer_tu_kiem_tap_khoa_cua_meta():
    """`dung_envelope` từ chối một `meta` thiếu hoặc thừa trường.

    Không có phép tự kiểm này thì luật "meta là tập trường đóng" chỉ sống trong
    văn xuôi, và tuyến thứ hai của Epic 3 sẽ ghép một dict tay.
    """
    dung = {"role": "devops", "space": "synth", "policy_version": "abc"}
    assert tuple(dung_envelope(
        answer="x", refused=False, citations=[], graph=graph_rong(), meta=dict(dung)
    )) == KHOA_ENVELOPE
    for hong in ({**dung, "thoi_gian": 1}, {"role": "devops"}):
        with pytest.raises(ValueError):
            dung_envelope(
                answer="x", refused=False, citations=[], graph=graph_rong(), meta=hong
            )
    with pytest.raises(TypeError):
        dung_envelope(
            answer=7, refused=False, citations=[], graph=graph_rong(), meta=dict(dung)
        )
    # `refused` phải là **bool thật**, không phải một giá trị truthy: nhánh từ
    # chối của story 3.5 so hai thân byte-với-byte, và `1` với `True` không ra
    # cùng một byte JSON.
    for refused in (1, 0, "false", None):
        with pytest.raises(TypeError):
            dung_envelope(
                answer="x",
                refused=refused,
                citations=[],
                graph=graph_rong(),
                meta=dict(dung),
            )
    # Hai trường còn lại của hợp đồng cũng được canh, không chỉ ba trường kia.
    with pytest.raises(TypeError):
        dung_envelope(
            answer="x", refused=False, citations=(), graph=graph_rong(), meta=dict(dung)
        )
    for graph in ({}, {"nodes": []}, {"nodes": [], "edges": [], "thua": 1}, []):
        with pytest.raises(ValueError):
            dung_envelope(
                answer="x",
                refused=False,
                citations=[],
                graph=graph,
                meta=dict(dung),
            )


def test_graph_rong_la_object_moi_moi_lan():
    """Một hằng dict dùng chung là một hằng sửa được: hai lượt trả lời chia nhau nó."""
    a, b = graph_rong(), graph_rong()
    assert a == b and a is not b
    a["nodes"].append("x")
    assert graph_rong() == {"nodes": [], "edges": []}


def test_envelope_khong_stream(client, monkeypatch, workspace_dir, khong_gian, policy):
    """`QueryParam.stream` giữ `False` (khoản ledger 2.2, UX-DR4).

    Wrapper chưa có đường đếm token trên stream, nên nó dội
    `LLMStreamNotSupported`; và bật stream ở đây là bật nó cho một endpoint đo
    chi phí.

    Ba vế, vì quyết định nằm ở ba chỗ sau khi `api/` thôi import `vendor/` và
    story 3.5 tách một cửa engine thứ hai.

    Vế handler: nó gọi `hoi_dap(cau_hoi)` **không truyền `param`**, tức không có
    chỗ nào cho một `stream=True` đi vào từ ngoài.

    Vế `aquery`: `EngineACL.aquery` dựng `QueryParam()` của chính nó khi
    `param is None`, và ba trường của bản ấy là `stream=False`, `mode="hybrid"`,
    `only_need_context=False`. Đó là đường mà `eval/` và cổng M1 đi.

    Vế `hoi_dap`: nó cũng dựng bản mặc định ấy nhưng **bật** `only_need_context`
    trước khi vào `aquery` - đó là toàn bộ cách nó thoát trước lời gọi
    `rag_response` của vendor (`operate.py:596-597`) - và không đụng tới `stream`.
    """
    from hypergraphrag.base import QueryParam

    from core.permission import use_context

    from tests.gia_lap_llm import LLMGia, phan_hoi_hai_luot
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine
    from tests.ngu_canh import vai

    ban_ghi = []

    async def _hoi_dap(cau_hoi, param=None):
        from adapters.tra_loi import KetQuaHoiDap

        ban_ghi.append((cau_hoi, param))
        return KetQuaHoiDap(cau_tra_loi="ok")

    monkeypatch.setattr(api_main.app.state.engine, "hoi_dap", _hoi_dap)
    assert _hoi(client, "ts01").status_code == 200
    assert ban_ghi == [(CAU_HOI, None)], "handler không được tự dựng QueryParam"

    # Vế engine: bản mà `EngineACL.aquery` dựng khi nơi gọi không truyền gì.
    engine = dung_engine(
        workspace_dir,
        QdrantGhiLai(),
        Neo4jGhiLai(),
        LLMGia(theo_prompt=phan_hoi_hai_luot()),
    )
    tham_so = []

    async def _cha(self, query, param):
        tham_so.append(param)
        return "ok"

    monkeypatch.setattr(
        "hypergraphrag.HyperGraphRAG.aquery", _cha, raising=True
    )
    asyncio.run(engine.aquery("hỏi"))
    assert len(tham_so) == 1
    assert tham_so[0].stream is False
    assert tham_so[0].mode == "hybrid"
    assert tham_so[0].only_need_context is False

    # Vế `hoi_dap`: cùng ba trường, chỉ `only_need_context` bật lên. Bản giả của
    # `aquery` trả một chuỗi không phải khung ngữ cảnh nên `ngu_canh_rong` cho
    # `False` và lượt sinh câu trả lời chạy - đó là lý do LLM giả phải biết trả
    # JSON hai khóa ở đây.
    tham_so.clear()

    async def _chay_hoi_dap(param=None):
        # Lời gọi sinh câu trả lời đi qua wrapper LLM thật, và wrapper đọc
        # `current_context()` để kiểm space - nên nó phải chạy dưới một ngữ cảnh
        # vai, đúng như handler làm.
        with use_context(vai(policy, "devops", khong_gian)):
            return await engine.hoi_dap("hỏi", param)

    ket_qua = asyncio.run(_chay_hoi_dap())
    assert len(tham_so) == 1
    assert tham_so[0].stream is False
    assert tham_so[0].mode == "hybrid"
    assert tham_so[0].only_need_context is True
    assert ket_qua.cau_tra_loi and ket_qua.ly_do_tu_choi is None
    # Và nó **không** ghi lên instance mà nơi gọi đưa vào: `_build_query_context`
    # mutate `query_param.mode`, nên một `replace` thiếu ở đây là hai truy vấn
    # song song chia nhau một mảnh trạng thái.
    cua_toi = QueryParam()
    asyncio.run(_chay_hoi_dap(cua_toi))
    assert cua_toi.only_need_context is False


# --- Ngân sách: hai engine, hai bộ số -----------------------------------------


def test_tran_mot_truy_van_suy_tu_so_loi_goi_that_khong_doan():
    """Trần độ trễ của **một request**, suy từ số lời gọi thật.

    Bản đầu của story 3.3 viết "khoảng 160 giây" và nó sai: nó đếm **một** lời
    gọi embedding mỗi request, trong khi mode `hybrid` đi vào cả hai nhánh của
    `_build_query_context` nên `entities_vdb.query` (`vendor/operate.py:743`)
    **và** `hyperedges_vdb.query` (`:938`) đều chạy, mỗi cái một lời gọi
    embedding. Đây là con số chương 4 phát biểu cho NFR-08, nên nó không được
    là một con số đoán.

    Ca này chấm cả phép suy lẫn hai hằng đầu vào của nó; đổi một trong hai mà
    quên con số kia là đỏ ở đây.
    """
    from adapters.thu_lai import NGAN_SACH_TRUY_HOI
    from api.hoi_dap import (
        SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN,
        SO_LOI_GOI_LLM_MOI_TRUY_VAN,
        tran_mot_truy_van_giay,
    )

    assert SO_LOI_GOI_LLM_MOI_TRUY_VAN == 2
    assert SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN == 2
    ns = NGAN_SACH_TRUY_HOI
    mot_embedding = ns.so_lan_thu * ns.tran_moi_loi_goi_giay + (
        ns.so_lan_thu - 1
    ) * ns.tran_cho_giay
    assert mot_embedding == pytest.approx(42.0)
    assert tran_mot_truy_van_giay() == pytest.approx(204.0)
    # Là **trần** chứ không kỳ vọng, và nó là trần *đúng* chứ không xấp xỉ:
    # jitter nằm trong `tran_cho_giay` (story 3.3), nên không có phần cộng thêm
    # nào ngoài phép tính này.
    assert tran_mot_truy_van_giay() == pytest.approx(
        SO_LOI_GOI_LLM_MOI_TRUY_VAN * ns.tran_llm_giay
        + SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN * mot_embedding
    )


def test_so_loi_goi_embedding_moi_truy_van_khop_vendor():
    """Hai hằng số lời gọi phải khớp `vendor/`, không phải một lời hứa.

    Grep chính `vendor/hypergraphrag/operate.py`: `kg_query` gọi hàm LLM hai
    lần, và `_build_query_context` gọi đúng hai `*_vdb.query`. Một bản upstream
    mới đổi con số mà không ai thấy là đúng cách con số NFR-08 trôi.
    """
    import re
    from pathlib import Path

    from api.hoi_dap import (
        SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN,
        SO_LOI_GOI_LLM_MOI_TRUY_VAN,
    )

    goc = Path(__file__).resolve().parent.parent
    nguon = (goc / "vendor" / "hypergraphrag" / "operate.py").read_text(encoding="utf-8")
    # Hai lời gọi `*_vdb.query(...)` của đường đọc, mỗi cái nhúng đúng một chuỗi.
    assert len(re.findall(r"\bawait \w*_?vdb\.query\(", nguon)) == (
        SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN
    )
    # Hàm LLM của `kg_query`: trích từ khóa rồi sinh câu trả lời.
    than = nguon[nguon.index("async def kg_query("):nguon.index("async def _build_query_context(")]
    assert len(re.findall(r"\bawait use_model_func\(", than)) == (
        SO_LOI_GOI_LLM_MOI_TRUY_VAN
    )


def test_hai_duong_hai_ngan_sach_doc_thang_tu_hai_engine(monkeypatch, tmp_path):
    """AC: ngân sách của engine phục vụ khác engine nạp, và test **đọc thẳng** nó.

    Không đo bằng đồng hồ: một ca "request hỏng trong trần đã phát biểu" chạy
    thật phải chờ tới khi một trần nổ, tức một bộ test đo bằng đồng hồ treo
    tường. Thay vào đó hai hàm bọc mang ngân sách của chúng dưới một dấu sống
    sót qua chuỗi bọc của upstream, và ca này đọc đúng dấu đó trên hai engine
    dựng bằng hai đường sản phẩm thật.
    """
    from adapters.llm_wrapper import ngan_sach_cua, tran_loi_goi_cua
    from adapters.thu_lai import NGAN_SACH_NAP, NGAN_SACH_TRUY_HOI
    from api.dot_nap import dung_engine_tu_moi_truong
    from tests.gia_lap_llm import (
        MODEL_EMBEDDING_GIA,
        MODEL_LLM_GIA,
        DUONG_DAN_DANH_MUC_GIA,
        SoAuditBoNho,
    )

    # Danh mục giả cộng hai biến model giả: hai hàm dựng thật đọc môi trường,
    # và bộ test cố ý không có key provider nào (`tests/conftest.py`).
    monkeypatch.setenv("LLM_MODEL", MODEL_LLM_GIA)
    monkeypatch.setenv("EMBEDDING_MODEL", MODEL_EMBEDDING_GIA)
    monkeypatch.setenv("GIA_API_KEY", "khoa-gia")
    # Địa chỉ kho trỏ vào một host không tồn tại **có chủ đích**: xem phần
    # khẳng định "không mở socket nào" ở cuối ca.
    monkeypatch.setenv("QDRANT_URL", "http://khong-co-host-nay:6333")
    monkeypatch.setenv("NEO4J_URI", "bolt://khong-co-host-nay:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "khong-dung-toi")
    monkeypatch.setenv("HYPER_RAG_WORKING_DIR", str(tmp_path))
    # `danh_muc_mac_dinh()` đọc hằng đường dẫn ở **thời điểm gọi**, nên thay nó
    # là đủ cho cả hai đường dựng engine thật.
    monkeypatch.setattr(
        "adapters.model_catalog.DUONG_DAN_MAC_DINH", DUONG_DAN_DANH_MUC_GIA
    )

    so = SoAuditBoNho()
    nap = dung_engine_tu_moi_truong(so)
    phuc_vu = asyncio.run(hoi_dap.mo_engine(so))
    try:
        assert ngan_sach_cua(nap.embedding_func) is NGAN_SACH_NAP
        assert ngan_sach_cua(phuc_vu.embedding_func) is NGAN_SACH_TRUY_HOI
        assert NGAN_SACH_NAP.so_lan_thu == 4 and NGAN_SACH_NAP.tran_cho_giay == 60.0
        assert NGAN_SACH_TRUY_HOI.so_lan_thu == 2 and NGAN_SACH_TRUY_HOI.tran_cho_giay == 2.0
        # Trần cho một lời gọi LLM: đường nạp đã có trần ở lớp thử lại của
        # `_trich_mot_chunk`, nên `bo_llm` của nó không đặt thêm một lớp thứ hai.
        assert tran_loi_goi_cua(nap.llm_model_func) is None
        assert tran_loi_goi_cua(phuc_vu.llm_model_func) == 60.0
        # Đường phục vụ **không** nạp từ điển thực thể: nó đổi id entity của thứ
        # được *ghi*, nên trên đường đọc nó là một cấu hình không có tác dụng.
        assert phuc_vu.entity_dictionary_path is None
        # Port audit vào adapter KV (story 3.6): đường phục vụ có, đường nạp không.
        assert phuc_vu.text_chunks.audit is so and phuc_vu.full_docs.audit is so
        assert nap.text_chunks.audit is None and nap.full_docs.audit is None
        # **Dựng engine không mở socket nào**, và đây là chỗ khẳng định nó thay
        # vì nói suông. Cả hai engine trỏ vào một host không phân giải được;
        # nếu `__post_init__` mở kết nối thật thì hai dòng trên đã phải chờ DNS
        # trượt rồi nổ. Đọc thêm cờ nội bộ của driver Neo4j cho chắc: nó chưa
        # từng mở một phiên nào.
        assert phuc_vu._client_qdrant is not None
        assert phuc_vu._driver_neo4j is not None
        assert phuc_vu.chunk_entity_relation_graph._da_san_sang is False
    finally:
        asyncio.run(phuc_vu.dong())
        asyncio.run(nap.dong())


def _loi_mang_ket_noi(client, driver, *, tu_mo_qdrant=True, tu_mo_neo4j=True):
    """Một lỗi dựng engine mang sẵn dấu kết nối còn mở, như `__post_init__` gắn."""
    from adapters.engine import DAU_KET_NOI_CHUA_DONG, KetNoiChuaDong

    loi = RuntimeError("dựng engine hỏng sau khi đã mở kết nối")
    setattr(
        loi,
        DAU_KET_NOI_CHUA_DONG,
        KetNoiChuaDong(
            client_qdrant=client,
            tu_mo_qdrant=tu_mo_qdrant,
            driver_neo4j=driver,
            tu_mo_neo4j=tu_mo_neo4j,
        ),
    )
    return loi


class _KetNoiDemDong:
    """Kết nối giả chỉ đếm `close()`; đủ cho phép kiểm sở hữu."""

    def __init__(self, ten):
        self.ten = ten
        self.so_lan_dong = 0

    async def close(self):
        self.so_lan_dong += 1


def test_mo_engine_dong_phan_da_mo_roi_doi_lai_loi_goc(monkeypatch):
    """Nửa async của cơ chế chống rò: `mo_engine` đọc dấu và đóng đúng phần của engine.

    Ba mệnh đề trong một ca, và cả ba đỏ khi xóa khối `except BaseException`
    của `mo_engine`: kết nối `tu_mo=True` được đóng, kết nối **tiêm từ ngoài**
    thì không (đóng hộ là làm hỏng kết nối của người khác), và lỗi dội lên
    **nguyên loại** chứ không bị bọc - `api/man_nap.py` bắt theo `code` còn
    `tests/test_engine_acl.py` bắt theo loại.
    """
    tu_mo = _KetNoiDemDong("qdrant")
    tiem = _KetNoiDemDong("neo4j")

    def _no(*a, **kw):
        raise _loi_mang_ket_noi(tu_mo, tiem, tu_mo_qdrant=True, tu_mo_neo4j=False)

    monkeypatch.setattr(hoi_dap, "EngineACL", _no)
    monkeypatch.setattr(hoi_dap, "cau_hinh_kho_tu_moi_truong", lambda: {})
    monkeypatch.setattr(
        hoi_dap,
        "ham_tu_moi_truong",
        lambda **kw: type("H", (), {"llm": None, "embedding": None, "llm_max_token": 1})(),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(hoi_dap.mo_engine(AuditGia()))
    assert tu_mo.so_lan_dong == 1, "kết nối engine tự mở phải được đóng"
    assert tiem.so_lan_dong == 0, "kết nối tiêm từ ngoài thuộc về người tiêm"


def test_mo_engine_khong_dau_thi_khong_doan_gi(monkeypatch):
    """Lỗi không mang dấu (dựng hỏng *trước* khi mở gì) chỉ dội lên, không đoán."""

    def _no(*a, **kw):
        raise ValueError("thiếu khóa cấu hình")

    monkeypatch.setattr(hoi_dap, "EngineACL", _no)
    monkeypatch.setattr(hoi_dap, "cau_hinh_kho_tu_moi_truong", lambda: {})
    monkeypatch.setattr(
        hoi_dap,
        "ham_tu_moi_truong",
        lambda **kw: type("H", (), {"llm": None, "embedding": None, "llm_max_token": 1})(),
    )
    with pytest.raises(ValueError):
        asyncio.run(hoi_dap.mo_engine(AuditGia()))


def test_lifespan_khong_goi_khoi_tao(monkeypatch, kho_gia, audit_gia):
    """Đường phục vụ **chỉ đọc**: lifespan không dựng lược đồ kho.

    Không phải một chỗ chưa làm. `khoi_tao()` đòi ngữ cảnh hệ thống, và cửa duy
    nhất mở cờ bỏ-filter nằm ở `core/system_context.py` với một danh sách trắng
    import canh giữ - thêm một module `api/` vào đó là mở đúng cánh cửa mà
    NFR-10 đóng. Bỏ bước thay vì nới luật, và ca này giữ quyết định ấy sống.
    """
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    da_goi = []

    class EngineDemKhoiTao(EngineGia):
        async def khoi_tao(self):
            da_goi.append("khoi_tao")

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return EngineDemKhoiTao()

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app):
        pass
    assert da_goi == [], "lifespan của tiến trình phục vụ không được gọi khoi_tao()"


def test_loi_chua_xep_loai_van_ra_dung_envelope_loi(client, engine_gia):
    """Ngoại lệ chưa ai xếp loại vẫn ra `{error: {code, message}}` (AD-8).

    Hai chuyện tách nhau, và ca này chấm chuyện thứ hai. Chuyện thứ nhất -
    **không bịa một mã** cho một lỗi chưa ai xếp loại - do `loi_truy_hoi` giữ
    (nó trả `None`), và `::test_loi_la_khong_bi_bia_ma` chấm nó ở tầng hàm.
    Chuyện thứ hai là hình dạng: không có handler chung thì một `ValueError`
    lạ, và cả `TypeError`/`ValueError` của chính serializer envelope, cho một
    thân `Internal Server Error` trần - thân duy nhất trong cả tiến trình không
    mang `code` để test assert lên.
    """
    engine_gia.loi = ValueError("một lỗi chưa ai xếp loại")
    # `raise_server_exceptions=False`: mặc định `TestClient` dội lại ngoại lệ
    # của server cho người viết test thay vì để handler chạy, mà handler mới là
    # thứ ca này chấm. Client thật luôn đi qua handler.
    with TestClient(api_main.app, raise_server_exceptions=False) as c:
        kq = c.post(
            "/hoi-dap",
            json={"cau_hoi": CAU_HOI},
            headers=_bearer(c, "ts01"),
        )
    assert kq.status_code == 500
    than = kq.json()
    assert tuple(than) == ("error",)
    assert than["error"]["code"] == api_main.MA_LOI_KHONG_XAC_DINH
    # Thông điệp cố định: đường dẫn, tên host và tên biến môi trường không đi ra
    # theo một lỗi 500.
    assert than["error"]["message"] == api_main.THONG_DIEP_LOI_KHONG_XAC_DINH
    assert "chưa ai xếp loại" not in than["error"]["message"]


def test_than_yeu_cau_la_dung_thong_diep_chung_khong_cua_rieng_mot_tuyen(client):
    """Handler lược đồ thân phủ **mọi** tuyến, nên thông điệp phải chung.

    Hôm nay chỉ `/hoi-dap` khai một thân pydantic (hai tuyến kia tự đọc
    `await request.json()`), nhưng tuyến thứ hai khai một thân như thế sẽ trả
    lời bằng một câu nói về `cau_hoi` nếu thông điệp mượn của `api/hoi_dap.py`.
    """
    thong_diep = _hoi(client, "ts01", {"cau_hoi": "x", "la": 1}).json()["error"]["message"]
    assert thong_diep == api_main.THONG_DIEP_THAN_YEU_CAU_LA
    assert "cau_hoi" not in thong_diep


# --- Đi hết đường thật: handler + ngữ cảnh + ba adapter ------------------------


@pytest.mark.usefixtures("ma_hoa_offline")
def test_e2e_qua_ba_adapter_that_hai_vai_hai_ngu_canh_truy_hoi(
    monkeypatch, kho_gia, audit_gia, workspace_dir, khong_gian, policy
):
    """`POST /hoi-dap` đi hết đường thật, **không container**, hai vai hai kết quả.

    Mọi ca khác của file này dùng `EngineGia`, nên chúng chấm hợp đồng của
    handler mà không chấm việc handler ghép đúng `use_context` + engine + tầng
    che. Câu "nội dung ra khỏi handler này đã đi qua tầng che (AD-9)" - viết ở
    docstring module và ở dòng khai trong `CHAM_STORAGE_CO_LY_DO` - là văn xuôi
    cho tới khi có ca này.

    Engine dựng bằng `tests/ho_tro_m1.cong_m1`: ba **adapter thật** trên ba kết
    nối giả có ghi nhật ký, fixture của cổng M1 đã nạp sẵn. Nên đây là cùng
    đường mà `tests/test_cong_m1.py` chấm, chỉ khác là nó vào từ HTTP.

    Ba assert, theo thứ tự quan trọng. Một, mỗi request phát **một** filter
    Qdrant mang đúng tập khóa của vai đang hỏi - tức pre-filter tại tầng vector
    (chốt brief §6) sống qua cả đường HTTP. Hai, hai vai cho hai tập khóa khác
    nhau. Ba, mọi câu Cypher mang mệnh đề lọc.
    """
    from dataclasses import replace as _replace

    from tests.gia_lap_llm import phan_hoi_hai_luot
    from tests.gia_lap_neo4j import canh_moi_bien_deu_bi_loc
    from tests.ho_tro_m1 import cong_m1, khoa_theo_collection

    engine, qdrant, neo4j, llm = asyncio.run(cong_m1(workspace_dir, khong_gian, policy))
    # Từ story 3.5 một lượt `hoi_dap` là **hai** lời gọi LLM: trích từ khóa
    # (định dạng tuple của vendor) rồi sinh câu trả lời (JSON hai khóa của dự
    # án). LLM giả phải trả đúng định dạng cho từng lượt, nếu không lượt hai
    # thành `DAU_RA_LLM_KHONG_DOC_DUOC` và ca này đo nhầm thứ.
    llm.theo_prompt = phan_hoi_hai_luot()

    # Hai tài khoản seed, chuyển sang không gian cách ly của phiên test - đúng
    # cách `tests/test_cong_m1.py` làm, và là chỗ duy nhất `khong_gian` được đổi.
    kho_gia.theo_ten.clear()
    for ten, vai_, in (("ts01", "tech_support"), ("dev01", "devops")):
        kho_gia.theo_ten[ten.upper()] = _replace(
            _dong(ten, role=vai_), khong_gian=khong_gian
        )

    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return engine

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)

    khoa_theo_vai = {}
    with TestClient(api_main.app) as c:
        for tk in ("ts01", "dev01"):
            qdrant.xoa_nhat_ky()
            neo4j.xoa_nhat_ky()
            kq = c.post(
                "/hoi-dap", json={"cau_hoi": CAU_HOI}, headers=_bearer(c, tk)
            )
            assert kq.status_code == 200, kq.text
            than = kq.json()
            assert tuple(than) == KHOA_ENVELOPE
            assert isinstance(than["answer"], str) and than["answer"]
            assert than["refused"] is False
            assert than["meta"]["space"] == khong_gian
            # Đường `rag_response` của vendor không còn được đi: câu trả lời đến
            # từ prompt của dự án, và nó không truyền `system_prompt`.
            assert llm.prompts_sinh_cau_tra_loi == []
            theo_collection = khoa_theo_collection(qdrant)
            assert theo_collection, "không request Qdrant nào rời khỏi handler"
            khoa_theo_vai[tk] = theo_collection
            # Mọi câu Cypher mang mệnh đề lọc: nhìn vào kết quả thì không phân
            # biệt được pre-filter với lọc lại phía Python.
            cau_doc = neo4j.cac_cau_doc()
            assert cau_doc, f"vai {tk} không phát câu đọc graph nào"
            for lg in cau_doc:
                canh_moi_bien_deu_bi_loc(lg.cypher)

    chung = set(khoa_theo_vai["ts01"]) & set(khoa_theo_vai["dev01"])
    assert chung, "hai vai phải hỏi cùng ít nhất một collection để so được"
    assert any(
        khoa_theo_vai["ts01"][ten] != khoa_theo_vai["dev01"][ten] for ten in chung
    ), "hai vai đi ra cùng một tập khóa: bảng chính sách không tới được adapter"


def test_api_khong_import_system_context():
    """Phát biểu mạnh hơn một phép kiểm: `api/` không có đường import nào tới cờ hệ thống.

    Trùng chủ đề với `tests/test_import_lint.py::test_chi_ingest_duoc_import_context_he_thong`
    nhưng khác mệnh đề: ca kia nói "chỉ ba file được phép", ca này nói "và không
    file `api/` nào nằm trong ba file đó" - thứ story 3.3 phải giữ nguyên khi nó
    nối engine vào tiến trình phục vụ.
    """
    import ast
    from pathlib import Path

    from tests.test_import_lint import CHO_PHEP_SYSTEM_CONTEXT

    assert not [d for d in CHO_PHEP_SYSTEM_CONTEXT if d.startswith("api/")]
    goc = Path(__file__).resolve().parent.parent
    # Đọc AST chứ không grep chuỗi: docstring của `api/hoi_dap.py` **nhắc tên**
    # module đó đúng để nói vì sao nó không import - và một phép grep biến lời
    # giải thích ấy thành một test đỏ.
    for py in (goc / "api").rglob("*.py"):
        cay = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for n in ast.walk(cay):
            ten = None
            if isinstance(n, ast.ImportFrom):
                ten = n.module
            elif isinstance(n, ast.Import):
                ten = ",".join(a.name for a in n.names)
            assert ten is None or "system_context" not in ten, f"{py}: {ten}"


def test_duong_dan_khong_khop_tuyen_ra_envelope_chu_khong_detail_tran(client):
    """404/405 của router cũng là `{error: {code, message}}` (AD-8, kiểm tay 5.1).

    Ba ca: đường dẫn lạ, phương thức sai trên tuyến có thật, và id rỗng trong
    tuyến hủy break-glass (`/break-glass/yeu-cau//huy`, ca thấy trên máy chủ).
    Không ca nào dội lại đường dẫn người gọi gửi.
    """
    from api.main import MA_TUYEN_KHONG_CO

    for phuong_thuc, duong_dan, ma_http in (
        ("GET", "/khong-co-tuyen-nay", 404),
        ("DELETE", "/health", 405),
        ("POST", "/break-glass/yeu-cau//huy", 404),
    ):
        kq = client.request(phuong_thuc, duong_dan)
        assert kq.status_code == ma_http, (duong_dan, kq.text)
        assert kq.json() == {
            "error": {"code": MA_TUYEN_KHONG_CO, "message": kq.json()["error"]["message"]}
        }
        assert "detail" not in kq.json() and duong_dan not in kq.text
