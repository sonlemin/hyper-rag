"""Hoán bảng chính sách lúc chạy: kho trong tiến trình và hai tuyến admin (3.2).

Đặc tả viết trước cơ chế (FR-27). Mọi hàng I/O Matrix của story về đường reload
nằm ở đây; hàng về validator đơn điệu nằm ở `tests/test_chinh_sach.py`.

Không Postgres và không kho tri thức: bảng `users` và port audit đều là bản giả,
đúng khuôn mà `tests/test_xac_thuc.py` đặt. Cái đang được chấm là **thứ tự** của
một lần hoán (nạp -> ghi audit -> mới thay) và hai cửa quyền, không phải một
driver.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from adapters.policy_loader import load_policy
from api import main as api_main
from api.che_do_do import BIEN_CHE_DO_DO
from api.chinh_sach import (
    ID_MAC_DINH,
    MA_DANH_MUC_RONG,
    MA_ID_KHONG_CO,
    MA_POLICY_CHI_CHE_DO_DO,
    POLICY_VAN_HANH,
    SPACE_TOAN_HE,
    KhoChinhSach,
    LoiChinhSach,
    danh_muc,
    kiem_cong_cau_hinh_do,
)
from api.xac_thuc import BIEN_KHOA_KY, MA_THIEU_QUYEN, MA_THIEU_QUYEN_ADMIN
from core.audit import EVENT_POLICY_SWAP, TIER_MUTATION
from core.identity import DanhTinh, ngu_canh_cua
from core.ids import validate_space
from core.policy import PolicyInvalid
from tests.fixtures import oracle
from tests.test_xac_thuc import (
    KHOA_TEST,
    MAT_KHAU,
    AuditGia,
    EngineGia,
    KhoGia,
    _dong,
)

# Ba tài khoản seed thật, và ba tổ hợp cờ khác nhau. `demo01` là chỗ **duy
# nhất** chứng minh được cửa chỉ-`admin` từ chối qua HTTP: `ts01` không có cờ
# nào nên nó cũng bị cửa demo-hoặc-admin chặn, và `dev01` có cả hai nên nó
# không phân biệt được hai cửa.
TEN_GO = {"ts01": "TS01", "dev01": "DEV01", "demo01": "DEMO01"}


@pytest.fixture
def kho_gia():
    return KhoGia(
        {
            TEN_GO["ts01"]: _dong("ts01"),
            TEN_GO["dev01"]: _dong("dev01", role="devops", demo=True, admin=True),
            TEN_GO["demo01"]: _dong("demo01", demo=True, admin=False),
        }
    )


@pytest.fixture
def audit_gia():
    return AuditGia()


@pytest.fixture
def client(monkeypatch, kho_gia, audit_gia):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    # Story 3.8: ba bảng đo chỉ hoán sang được trên tiến trình đo. Bộ này chấm
    # đường hoán nên nó chạy như tiến trình đo; ca cờ tắt có fixture riêng dưới.
    monkeypatch.setenv(BIEN_CHE_DO_DO, "1")

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        # Story 3.3 nối engine vào lifespan; bộ này chấm đường hoán policy nên
        # engine chỉ cần mở và đóng được.
        return EngineGia()

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        yield c


def _token(client, tai_khoan: str) -> str:
    kq = client.post(
        "/auth/login", json={"tai_khoan": TEN_GO[tai_khoan], "mat_khau": MAT_KHAU}
    )
    assert kq.status_code == 200, kq.text
    return kq.json()["token"]


def _bearer(client, tai_khoan: str) -> dict:
    return {"Authorization": "Bearer " + _token(client, tai_khoan)}


# --- Danh mục id ---------------------------------------------------------


def test_danh_muc_suy_tu_glob_va_co_dung_bon_id():
    """Danh mục **đóng**, quét từ `config/policy-*.yaml`, không viết tay."""
    bang = danh_muc()
    assert set(bang) == {"day-du", "nhi-phan", "tat-phan-quyen", "toi-thieu-l1"}
    assert ID_MAC_DINH in bang
    for ma, duong_dan in bang.items():
        assert duong_dan.name == "policy-" + ma + ".yaml"


def test_danh_muc_bo_qua_file_khong_dung_hinh_dang_id(tmp_path):
    """Một `policy-Thu Nghiem.yaml` không thành một id: hình dạng id là cơ chế."""
    (tmp_path / "policy-day-du.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "policy-Thu Nghiem.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "policy-.yaml").write_text("x", encoding="utf-8")
    assert set(danh_muc(tmp_path)) == {"day-du"}


# --- Hoán ở tầng kho -----------------------------------------------------


def _kho() -> KhoChinhSach:
    return KhoChinhSach.nap(ID_MAC_DINH)


def test_hoan_doi_policy_version_va_ghi_mot_su_kien_mutation():
    """Hàng "Reload đúng": `policy_version` mới cộng một sự kiện audit mutation."""
    kho = _kho()
    audit = AuditGia()
    cu = kho.hien_tai()
    ma_moi, moi = asyncio.run(
        kho.hoan("nhi-phan", audit=audit, act="dev01", role="devops", che_do_do=True)
    )

    assert ma_moi == "nhi-phan" and kho.ma == "nhi-phan"
    assert kho.ma_va_policy() == (ma_moi, moi)
    assert kho.hien_tai() is moi
    assert moi.policy_version == oracle.bam_file_chinh_sach(oracle.POLICY_NHI_PHAN)
    assert moi.policy_version != cu.policy_version

    assert len(audit.su_kien) == 1
    sk = audit.su_kien[0]
    assert sk.tier == TIER_MUTATION and sk.event == EVENT_POLICY_SWAP
    assert sk.space == SPACE_TOAN_HE
    assert (sk.act, sk.role) == ("dev01", "devops")
    # `policy_version` của hàng là bảng đang hiệu lực **lúc** sự kiện xảy ra,
    # tức bảng cũ; bảng mới nằm ở `chi_tiet`, nên một hàng nói đủ hai đầu.
    assert sk.policy_version == cu.policy_version
    assert sk.chi_tiet["policy_id_cu"] == ID_MAC_DINH
    assert sk.chi_tiet["policy_id_moi"] == "nhi-phan"
    assert sk.chi_tiet["policy_version_moi"] == moi.policy_version


@pytest.mark.parametrize(
    "ma", ["../../etc/passwd", "khong-co", "", "day_du", "/etc/passwd", "day-du/../x"]
)
def test_id_la_hay_duong_dan_bi_tu_choi_va_khong_in_duong_dan_he_thong(ma):
    """Hàng "Reload id lạ hoặc đường dẫn": 400, và thân không in đường dẫn."""
    kho = _kho()
    audit = AuditGia()
    with pytest.raises(LoiChinhSach) as loi:
        asyncio.run(kho.hoan(ma, audit=audit))
    assert loi.value.ma == MA_ID_KHONG_CO
    assert loi.value.http == 400
    thong_diep = loi.value.thong_diep
    assert "/" not in thong_diep and "config" not in thong_diep
    assert "etc" not in thong_diep and "passwd" not in thong_diep
    # Không chạm đĩa ngoài `config/`, và bảng đang chạy không đổi.
    assert kho.ma == ID_MAC_DINH
    assert audit.su_kien == []


def test_file_hong_thi_policy_dang_chay_giu_nguyen(tmp_path):
    """Hàng "Reload file hỏng": 400 `POLICY_INVALID`, không rơi về policy rỗng."""
    tot = tmp_path / "policy-day-du.yaml"
    tot.write_text(
        oracle.POLICY_DAY_DU.read_text(encoding="utf-8"), encoding="utf-8"
    )
    hong = tmp_path / "policy-hong.yaml"
    hong.write_text("version: 1\nroles:\n  devops:\n   scopes: [x]\n", encoding="utf-8")

    kho = KhoChinhSach.nap("day-du", tmp_path)
    cu = kho.hien_tai()
    audit = AuditGia()
    with pytest.raises(LoiChinhSach) as loi:
        asyncio.run(kho.hoan("hong", audit=audit, che_do_do=True))
    assert loi.value.ma == PolicyInvalid.code
    assert loi.value.http == 400
    # Thân nói **bảng nào** hỏng và hỏng ở đâu trong bảng, không nói cây thư mục
    # của máy chủ - cùng luật với ca id lạ ngay trên.
    thong_diep = loi.value.thong_diep
    assert "policy-hong.yaml" in thong_diep and "devops" in thong_diep
    assert str(tmp_path) not in thong_diep
    assert "/" not in thong_diep
    assert kho.hien_tai() is cu and kho.ma == "day-du"
    assert audit.su_kien == [], "audit không được ghi cho một lần hoán không xảy ra"


def test_audit_hong_thi_hoan_khong_co_hieu_luc():
    """Hàng "Audit hỏng lúc hoán": lỗi dội lên và bảng đang chạy giữ nguyên.

    Tầng mutation của AD-16: ghi hỏng là thao tác hỏng. Một hệ đã hoán sang bảng
    B trong khi sổ audit nói nó chạy bảng A là một khoảng thời gian không ai
    giải thích được sau này.
    """
    kho = _kho()
    cu = kho.hien_tai()
    audit = AuditGia()
    audit.no = RuntimeError("postgres chết")
    with pytest.raises(RuntimeError):
        asyncio.run(kho.hoan("nhi-phan", audit=audit, che_do_do=True))
    assert kho.hien_tai() is cu and kho.ma == ID_MAC_DINH


def test_ngu_canh_dung_truoc_giu_tron_policy_cu_qua_mot_lan_hoan():
    """Hàng "Request đang chạy giữa lúc hoán": ngữ cảnh giữ trọn bản cũ.

    `PermissionContext` frozen chép `policy_version` và hai bảng khóa lúc dựng,
    nên phần khó không nằm ở `core/`. Nó nằm ở chỗ nơi gọi đọc `hien_tai()`
    **đúng một lần** ở đầu request rồi truyền object đó xuống - đọc lại giữa
    chừng là hai adapter thấy hai bản chính sách trong cùng một request.
    """
    kho = _kho()
    danh_tinh = DanhTinh(tai_khoan="ts01", vai="tech_support", khong_gian="synth")
    # Một lần đọc, ở đầu "request".
    policy = kho.hien_tai()
    ctx = ngu_canh_cua(danh_tinh, policy)
    khoa_truoc = ctx.keys_for("hyperedges")

    asyncio.run(kho.hoan("nhi-phan", audit=AuditGia(), che_do_do=True))

    assert ctx.policy_version == policy.policy_version
    assert ctx.keys_for("hyperedges") == khoa_truoc
    # Và bản mới thật sự khác: nếu không thì ca này xanh một cách rỗng.
    moi = ngu_canh_cua(danh_tinh, kho.hien_tai())
    assert moi.policy_version != ctx.policy_version
    assert moi.keys_for("hyperedges") != khoa_truoc


def test_hai_lan_hoan_dong_thoi_noi_duoi_nhau_chu_khong_dan_nhau():
    """Ba bước của một lần hoán chạy dưới một khóa, nên hai lần hoán nối tiếp.

    Không có khóa thì hai lần hoán đan nhau ở `await ghi_bien_doi`: cả hai đọc
    cùng một `policy_id_cu`, ghi hai hàng audit nói cùng một chuyện, và bảng
    thắng là bảng gán sau chứ không phải bảng ghi sau. Sổ audit khi đó mô tả một
    lịch sử không xảy ra - đúng thứ tầng mutation của AD-16 sinh ra để chặn.

    Port audit ở đây **nhường điều khiển** trong `ghi` (một `sleep(0)`), tức mô
    phỏng đúng chỗ mà một pool asyncpg thật nhường. Không có nó thì hai coroutine
    chạy tuần tự vì may mắn và ca này xanh cả khi khóa bị gỡ.
    """

    class AuditNhuong(AuditGia):
        async def ghi(self, su_kien):
            await asyncio.sleep(0)
            await super().ghi(su_kien)

    kho = _kho()
    audit = AuditNhuong()

    async def chay():
        return await asyncio.gather(
            kho.hoan("nhi-phan", audit=audit, che_do_do=True),
            kho.hoan("tat-phan-quyen", audit=audit, che_do_do=True),
        )

    asyncio.run(chay())

    assert len(audit.su_kien) == 2
    day_chuyen = [
        (s.chi_tiet["policy_id_cu"], s.chi_tiet["policy_id_moi"]) for s in audit.su_kien
    ]
    # Hàng thứ hai phải khai `policy_id_cu` là bảng mà hàng thứ nhất vừa đặt.
    assert day_chuyen[0][0] == ID_MAC_DINH
    assert day_chuyen[1][0] == day_chuyen[0][1], day_chuyen
    # Và bảng đang chạy là bảng của hàng audit cuối, không phải của lần gán cuối.
    assert kho.ma == day_chuyen[1][1]
    assert kho.hien_tai().policy_version == audit.su_kien[1].chi_tiet[
        "policy_version_moi"
    ]


def test_danh_muc_rong_ra_ma_rieng_chu_khong_phai_thong_diep_cut(tmp_path):
    """`config/` không mount được là một ca khác "gõ sai id", nên nó có mã riêng.

    Không có nhánh này thì người gọi nhận đúng chuỗi "danh mục là " cụt ngang,
    một câu không nói được gì cho người đang tìm hiểu vì sao endpoint hỏng.
    """
    # Kho trỏ vào một thư mục rỗng: bảng đang chạy vẫn có (nó đã nạp xong),
    # nhưng danh mục thì không còn gì - đúng hình dạng của một volume `config/`
    # chưa mount trong container.
    kho = KhoChinhSach(ID_MAC_DINH, load_policy(oracle.POLICY_DAY_DU), tmp_path)
    with pytest.raises(LoiChinhSach) as loi:
        asyncio.run(kho.hoan("day-du", audit=AuditGia()))
    assert loi.value.ma == MA_DANH_MUC_RONG
    assert loi.value.http == 500
    with pytest.raises(LoiChinhSach) as loi2:
        kho.danh_muc()
    assert loi2.value.ma == MA_DANH_MUC_RONG


def test_space_cua_su_kien_hoan_khong_phai_mot_space_that():
    """`"*"` là một dấu, không phải một tên không gian - và đó là cơ chế.

    Nếu `SPACE_TOAN_HE` lỡ thành một chuỗi mà `validate_space` nhận thì nó là
    một space thật, và mọi truy vấn audit của space đó đếm nhầm một hàng không
    thuộc về nó. Nối hai đầu ấy lại bằng một phép kiểm thay vì một quy ước.
    """
    with pytest.raises(ValueError):
        validate_space(SPACE_TOAN_HE)


def test_hoan_sang_chinh_bang_dang_chay_van_ghi_audit():
    """Một lần gọi có hiệu lực là một lần cần bản ghi, kể cả khi kết quả trùng."""
    kho = _kho()
    audit = AuditGia()
    asyncio.run(kho.hoan(ID_MAC_DINH, audit=audit))
    assert len(audit.su_kien) == 1
    assert audit.su_kien[0].chi_tiet["policy_id_cu"] == ID_MAC_DINH
    assert audit.su_kien[0].chi_tiet["policy_id_moi"] == ID_MAC_DINH


def test_bon_cau_hinh_deu_hoan_duoc_qua_kho():
    """FR-28: bốn cấu hình đo hoán qua lại được mà không khởi động lại tiến trình."""
    kho = _kho()
    audit = AuditGia()
    ban = {}
    for ma in kho.danh_muc():
        ma_moi, p = asyncio.run(kho.hoan(ma, audit=audit, che_do_do=True))
        assert ma_moi == ma
        ban[ma] = p.policy_version
    assert len(set(ban.values())) == 4, ban
    assert len(audit.su_kien) == 4


# --- Hai tuyến admin qua HTTP --------------------------------------------


def test_get_policy_tra_id_version_va_danh_muc(client):
    kq = client.get("/admin/policy", headers=_bearer(client, "dev01"))
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert than["id"] == ID_MAC_DINH
    assert than["policy_version"] == load_policy(oracle.POLICY_DAY_DU).policy_version
    assert than["danh_muc"] == sorted(danh_muc())
    assert than["che_do_do"] is True, "fixture `client` chạy như tiến trình đo (story 3.8)"
    assert set(than) == {"id", "policy_version", "danh_muc", "che_do_do"}


def test_post_policy_bang_admin_doi_version_va_ghi_audit(client, audit_gia):
    """Hàng "Reload đúng" qua HTTP: 200, version mới, một sự kiện mutation.

    Không restart tiến trình: cùng `TestClient`, `GET` sau đó đọc bản mới.
    """
    truoc = client.get("/admin/policy", headers=_bearer(client, "dev01")).json()
    kq = client.post(
        "/admin/policy", json={"id": "nhi-phan"}, headers=_bearer(client, "dev01")
    )
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert than["id"] == "nhi-phan"
    assert than["policy_version"] != truoc["policy_version"]
    assert than["policy_version"] == load_policy(oracle.POLICY_NHI_PHAN).policy_version

    sau = client.get("/admin/policy", headers=_bearer(client, "dev01")).json()
    assert sau["id"] == "nhi-phan"
    assert sau["policy_version"] == than["policy_version"]

    swap = [s for s in audit_gia.su_kien if s.event == EVENT_POLICY_SWAP]
    assert len(swap) == 1
    assert swap[0].tier == TIER_MUTATION
    assert swap[0].act == "dev01"


def test_tai_khoan_demo_khong_admin_bi_tu_choi_bang_ma_rieng(client, audit_gia):
    """Hàng "Reload bởi tài khoản chỉ có `demo`": 403 và **mã khác** cửa kia.

    `demo01` qua được cửa demo-hoặc-admin (`/auth/tai-khoan` trả 200) mà không
    qua được cửa chỉ-admin. Hai mã khác nhau, vì một tài khoản demo bị chặn ở
    đây phải đọc được rằng nó thiếu đúng cờ `admin`.
    """
    dau = _bearer(client, "demo01")
    assert client.get("/auth/tai-khoan", headers=dau).status_code == 200

    for tuyen, goi in (
        (client.get, {}),
        (client.post, {"json": {"id": "nhi-phan"}}),
    ):
        kq = tuyen("/admin/policy", headers=dau, **goi)
        assert kq.status_code == 403, kq.text
        assert kq.json()["error"]["code"] == MA_THIEU_QUYEN_ADMIN
        assert kq.json()["error"]["code"] != MA_THIEU_QUYEN

    assert [s for s in audit_gia.su_kien if s.event == EVENT_POLICY_SWAP] == []
    assert (
        client.get("/admin/policy", headers=_bearer(client, "dev01")).json()["id"]
        == ID_MAC_DINH
    )


def test_tai_khoan_khong_co_co_nao_cung_bi_tu_choi(client):
    """`ts01` không có cờ nào: cùng 403, cùng mã của cửa chỉ-admin."""
    kq = client.post(
        "/admin/policy", json={"id": "nhi-phan"}, headers=_bearer(client, "ts01")
    )
    assert kq.status_code == 403
    assert kq.json()["error"]["code"] == MA_THIEU_QUYEN_ADMIN


def test_khong_token_thi_khong_vao_duoc_hai_tuyen(client):
    """Hai tuyến nằm trong `cua_dong`, nên cửa đứng ở tuyến chứ không ở thân hàm."""
    for kq in (
        client.get("/admin/policy"),
        client.post("/admin/policy", json={"id": "nhi-phan"}),
    ):
        assert kq.status_code == 401
        assert kq.json()["error"]["code"] == "TOKEN_KHONG_HOP_LE"


@pytest.mark.parametrize(
    "than",
    [{"id": "../../etc/passwd"}, {"id": "khong-co"}, {}, {"id": 7}, {"duong_dan": "x"}],
    ids=["duong_dan", "id_la", "thieu_id", "id_khong_chuoi", "khoa_la"],
)
def test_post_id_la_ra_400_va_khong_in_duong_dan(client, than, audit_gia):
    kq = client.post("/admin/policy", json=than, headers=_bearer(client, "dev01"))
    assert kq.status_code == 400, kq.text
    loi = kq.json()["error"]
    assert loi["code"] == MA_ID_KHONG_CO
    assert "/" not in loi["message"] and "config" not in loi["message"]
    assert [s for s in audit_gia.su_kien if s.event == EVENT_POLICY_SWAP] == []


def test_than_khong_phai_json_cung_ra_dung_ma_do(client):
    """Thân hỏng không được thoát ra khỏi envelope `{error:{code,message}}`."""
    kq = client.post(
        "/admin/policy",
        content=b"khong phai json",
        headers={**_bearer(client, "dev01"), "content-type": "application/json"},
    )
    assert kq.status_code == 400
    assert kq.json()["error"]["code"] == MA_ID_KHONG_CO


def test_id_policy_mac_dinh_doc_tu_moi_truong():
    """Biến môi trường trỏ id; vắng hay rỗng thì rơi về bảng vận hành."""
    from api.chinh_sach import ma_policy_mac_dinh

    assert ma_policy_mac_dinh({}) == ID_MAC_DINH
    assert ma_policy_mac_dinh({"HYPER_RAG_POLICY_ID": "  "}) == ID_MAC_DINH
    assert ma_policy_mac_dinh({"HYPER_RAG_POLICY_ID": "nhi-phan"}) == "nhi-phan"
    # `api/main.py` chỉ import lại (story 3.6): đường nạp đọc cùng cửa.
    assert api_main.ma_policy_mac_dinh is ma_policy_mac_dinh


def test_lifespan_nap_policy_truoc_khi_mo_ket_noi_nao(monkeypatch, kho_gia):
    """Id policy gõ sai là lỗi cấu hình: hỏng ở giây đầu, trước mọi kết nối."""
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    monkeypatch.setenv("HYPER_RAG_POLICY_ID", "khong-co-bang-nay")
    da_mo = []

    async def _mo():
        da_mo.append(1)
        return kho_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    with pytest.raises(LoiChinhSach) as loi:
        with TestClient(api_main.app):
            pass
    assert loi.value.ma == MA_ID_KHONG_CO
    assert da_mo == [], "phải từ chối trước khi mở kết nối nào"


def test_lifespan_dung_bang_khai_trong_moi_truong(monkeypatch, kho_gia, audit_gia):
    """FR-28 ở tầng vận hành: đổi biến môi trường là đổi bảng, không sửa code."""
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    monkeypatch.setenv("HYPER_RAG_POLICY_ID", "tat-phan-quyen")
    monkeypatch.setenv(BIEN_CHE_DO_DO, "1")

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return EngineGia()

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        than = c.get("/admin/policy", headers=_bearer(c, "dev01")).json()
    assert than["id"] == "tat-phan-quyen"
    assert (
        than["policy_version"]
        == load_policy(oracle.POLICY_TAT_PHAN_QUYEN).policy_version
    )


# --- Story 3.8: cổng cấu hình đo theo cờ `HYPER_RAG_CHE_DO_DO` ---------------

BA_BANG_DO = ("nhi-phan", "tat-phan-quyen", "toi-thieu-l1")


def test_bang_van_hanh_la_day_du_va_ba_bang_con_lai_la_bang_do():
    """Danh mục bốn id chia thành một bảng vận hành và ba bảng đo, suy từ glob."""
    assert POLICY_VAN_HANH == frozenset({ID_MAC_DINH})
    assert set(danh_muc()) - POLICY_VAN_HANH == set(BA_BANG_DO)
    for ma in BA_BANG_DO:
        with pytest.raises(LoiChinhSach) as loi:
            kiem_cong_cau_hinh_do(ma, che_do_do=False)
        assert loi.value.ma == MA_POLICY_CHI_CHE_DO_DO and loi.value.http == 400
        assert "HYPER_RAG_CHE_DO_DO" in loi.value.thong_diep
        assert "/" not in loi.value.thong_diep
        kiem_cong_cau_hinh_do(ma, che_do_do=True)
    kiem_cong_cau_hinh_do(ID_MAC_DINH, che_do_do=False)


@pytest.mark.parametrize("ma", BA_BANG_DO)
def test_co_tat_thi_hoan_sang_bang_do_bi_tu_choi_truoc_audit(ma):
    """Hàng "Hoán cấu hình đo khi cờ tắt": 400 `POLICY_CHI_CHE_DO_DO`, bảng giữ
    nguyên, **không hàng `policy_swap`** - từ chối trước `load_policy` và audit."""
    kho = _kho()
    cu = kho.hien_tai()
    audit = AuditGia()
    with pytest.raises(LoiChinhSach) as loi:
        asyncio.run(kho.hoan(ma, audit=audit))
    assert loi.value.ma == MA_POLICY_CHI_CHE_DO_DO and loi.value.http == 400
    assert kho.hien_tai() is cu and kho.ma == ID_MAC_DINH
    assert audit.su_kien == []
    # Mặc định của `hoan` là tắt: một nơi gọi không khai gì chỉ hoán được bảng
    # vận hành - fail-closed, cùng chiều với `nap`.
    asyncio.run(kho.hoan(ID_MAC_DINH, audit=audit))
    assert len(audit.su_kien) == 1


def test_co_tat_id_la_van_la_ma_id_khong_co():
    """Cổng đo đứng **sau** danh mục: id lạ vẫn `POLICY_ID_KHONG_CO`, không đổi mã theo cờ."""
    with pytest.raises(LoiChinhSach) as loi:
        asyncio.run(_kho().hoan("khong-co", audit=AuditGia()))
    assert loi.value.ma == MA_ID_KHONG_CO


def test_co_tat_nap_bang_do_bi_tu_choi_truoc_khi_doc_file(tmp_path):
    """`KhoChinhSach.nap` với một id đo khi cờ tắt không chạm file: file hỏng cũng
    chỉ ra `POLICY_CHI_CHE_DO_DO`, không `POLICY_INVALID`."""
    (tmp_path / "policy-day-du.yaml").write_text(
        oracle.POLICY_DAY_DU.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "policy-nhi-phan.yaml").write_text("hong", encoding="utf-8")
    with pytest.raises(LoiChinhSach) as loi:
        KhoChinhSach.nap("nhi-phan", tmp_path)
    assert loi.value.ma == MA_POLICY_CHI_CHE_DO_DO
    assert KhoChinhSach.nap("day-du", tmp_path).ma == "day-du"
    with pytest.raises(PolicyInvalid):
        KhoChinhSach.nap("nhi-phan", tmp_path, che_do_do=True)


@pytest.fixture
def client_co_tat(monkeypatch, kho_gia, audit_gia):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    monkeypatch.setenv(BIEN_CHE_DO_DO, "0")

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return EngineGia()

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        yield c


@pytest.mark.parametrize("ma", BA_BANG_DO)
def test_http_co_tat_hoan_bang_do_ra_400_va_bang_giu_nguyen(client_co_tat, audit_gia, ma):
    """Qua HTTP với `HYPER_RAG_CHE_DO_DO=0`: admin thật vẫn bị 400, bảng và audit không đổi."""
    dau = _bearer(client_co_tat, "dev01")
    kq = client_co_tat.post("/admin/policy", json={"id": ma}, headers=dau)
    assert kq.status_code == 400, kq.text
    assert kq.json()["error"]["code"] == MA_POLICY_CHI_CHE_DO_DO
    than = client_co_tat.get("/admin/policy", headers=dau).json()
    assert than["id"] == ID_MAC_DINH and than["che_do_do"] is False
    assert [s for s in audit_gia.su_kien if s.event == EVENT_POLICY_SWAP] == []
    # Hoán sang chính bảng vận hành thì vẫn được, và vẫn ghi audit.
    assert client_co_tat.post("/admin/policy", json={"id": ID_MAC_DINH}, headers=dau).status_code == 200
    assert len([s for s in audit_gia.su_kien if s.event == EVENT_POLICY_SWAP]) == 1


def test_http_co_bat_hoan_du_bon_bang(client, audit_gia):
    """Hàng "Hoán khi cờ bật": bốn id đều 200 như 3.2, bốn hàng `policy_swap`."""
    dau = _bearer(client, "dev01")
    for ma in (*BA_BANG_DO, ID_MAC_DINH):
        kq = client.post("/admin/policy", json={"id": ma}, headers=dau)
        assert kq.status_code == 200, (ma, kq.text)
        assert kq.json()["id"] == ma
    assert len([s for s in audit_gia.su_kien if s.event == EVENT_POLICY_SWAP]) == 4
    assert client.get("/admin/policy", headers=dau).json()["id"] == ID_MAC_DINH


@pytest.mark.parametrize("ma", BA_BANG_DO)
def test_lifespan_chet_voi_id_do_khi_co_tat(monkeypatch, kho_gia, ma):
    """Hàng "Khởi động với id đo mà cờ tắt": chết ở giây đầu, trước mọi kết nối."""
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    monkeypatch.setenv("HYPER_RAG_POLICY_ID", ma)
    monkeypatch.setenv(BIEN_CHE_DO_DO, "0")
    da_mo = []

    async def _mo():
        da_mo.append(1)
        return kho_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    with pytest.raises(LoiChinhSach) as loi:
        with TestClient(api_main.app):
            pass
    assert loi.value.ma == MA_POLICY_CHI_CHE_DO_DO
    assert da_mo == [], "phải từ chối trước khi mở kết nối nào"


def test_lifespan_doc_co_do_truoc_khi_nap_policy(monkeypatch, kho_gia):
    """Cờ đọc **trước** policy: một cờ gõ sai nổ `CHE_DO_DO_KHONG_HOP_LE` kể cả khi
    id policy cũng sai - và hai lỗi đều trước mọi kết nối."""
    from api.che_do_do import CheDoDoKhongHopLe

    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)
    monkeypatch.setenv("HYPER_RAG_POLICY_ID", "khong-co-bang-nay")
    monkeypatch.setenv(BIEN_CHE_DO_DO, "yes")
    da_mo = []

    async def _mo():
        da_mo.append(1)
        return kho_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo)
    with pytest.raises(CheDoDoKhongHopLe):
        with TestClient(api_main.app):
            pass
    assert da_mo == []
