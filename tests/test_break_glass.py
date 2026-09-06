"""API xin break-glass (story 5.1, FR-20, FR-27, AD-14, AD-16).

Đặc tả viết trước cơ chế: mọi hàng I/O Matrix của spec 5.1 nằm ở đây, cộng bốn
mệnh đề mà không hàng nào phát biểu được một mình.

- **Ba id vô hình là một thân byte-identical.** Hyperedge L0, id không tồn tại,
  id khác space cho cùng 404 `HYPEREDGE_KHONG_XIN_DUOC`, so bằng `content`;
  và dưới engine M1 thật, mỗi ca gửi đúng **một** câu Cypher - câu của
  `trich_dan_cua`, cửa quyền của citation - không lời gọi LLM/embedding.
- **Tập id xin được của một vai bằng đúng tập L1 của oracle.** Không id nào
  ngoài đó tạo được (L2 là 400, L0/khác space là 404).
- **Audit bên trong transaction.** Audit hỏng là 500 `AUDIT_GHI_HONG` và kho
  không có hàng; hàng `breakglass_request` là hàng duy nhất của lượt, tầng
  mutation, không `ly_do`.
- **Không nhận `act`/`role`/`space` từ thân.** Thân chỉ có hai trường, thừa
  một là 400 mà không chạm kho.

Bốn lớp: hàm thuần (`core/break_glass.py`, `api/break_glass.py`), engine M1
thật (`cong_m1`, `trich_dan_theo_id`), HTTP với `KhoBreakGlassGia` + `EngineGia`,
HTTP với engine M1 thật qua hai tài khoản seed. Bản Postgres thật ở
`tests/test_break_glass_postgres.py` (marker `postgres`).
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from adapters.neo4j import Neo4jUnavailable
from adapters.trich_dan import TrichDan, TrichDanNgoaiQuyen
from api import break_glass as bg
from api import main as api_main
from api.break_glass import (
    CT_K,
    CT_NHOM_DUYET,
    CT_REQUEST_ID,
    CT_THOI_HAN_PHUT,
    CT_TRANG_THAI,
    DAI_ID_TOI_DA,
    DAI_LY_DO_TOI_DA,
    KHOA_YEU_CAU,
    MA_GRANT_CON_HAN,
    MA_HYPEREDGE_DA_THAY_DU,
    MA_HYPEREDGE_KHONG_XIN_DUOC,
    MA_LY_DO_QUA_DAI,
    MA_LY_DO_RONG,
    MA_NHOM_DUYET_KHONG_CO,
    MA_YEU_CAU_DANG_CHO,
    MA_YEU_CAU_KHONG_CO,
    MA_YEU_CAU_KHONG_CON_CHO,
    SO_YEU_CAU_TOI_DA,
    YeuCauBreakGlass,
    dict_yeu_cau,
    kiem_hyperedge_id,
    kiem_ly_do,
    loi_kho,
    ma_yeu_cau,
    su_kien_break_glass,
)
from api.hoi_dap import (
    MA_AUDIT_GHI_HONG,
    MA_KHO_KHONG_SAN_SANG,
    MA_THAN_YEU_CAU_LA,
    MA_TRICH_DAN_NGOAI_QUYEN,
    LoiHoiDap,
)
from api.xac_thuc import BIEN_KHOA_KY
from core.audit import (
    EVENT_BREAKGLASS_CANCEL,
    EVENT_BREAKGLASS_REQUEST,
    EVENT_EMBEDDING_COST,
    EVENT_LLM_COST,
    EVENTS,
    TIER_MUTATION,
    thoi_diem_utc,
)
from core.break_glass import (
    K_MAC_DINH,
    THOI_HAN_PHUT,
    TRANG_THAI,
    TRANG_THAI_CHO_DUYET,
    TRANG_THAI_DA_DUYET,
    TRANG_THAI_DA_HUY,
    TRANG_THAI_TU_CHOI,
    huy_duoc,
)
from core.identity import RoleUnknown
from core.permission import use_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.ho_tro_break_glass import KhoBreakGlassGia, chen_grant
from tests.ho_tro_m1 import cong_m1
from tests.nap_kho import ten_hyperedge
from tests.ngu_canh import ngu_canh_ingest, vai
from tests.test_xac_thuc import KHOA_TEST, MAT_KHAU, TEN_GO, AuditGia, EngineGia, KhoGia, _dong

GOC = Path(__file__).resolve().parent.parent
ADR_019 = GOC / "docs" / "adr" / "ADR-019-api-xin-break-glass.md"

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

HAI_VAI = ("devops", "tech_support")
DUONG = "/break-glass/yeu-cau"


# --- Lớp 1: hàm thuần --------------------------------------------------------------


def test_bon_trang_thai_hai_hang_va_huy_duoc():
    assert TRANG_THAI == {TRANG_THAI_CHO_DUYET, TRANG_THAI_DA_HUY, TRANG_THAI_DA_DUYET, TRANG_THAI_TU_CHOI}
    assert (K_MAC_DINH, THOI_HAN_PHUT) == (0, 60)
    assert huy_duoc(TRANG_THAI_CHO_DUYET) is True
    for tt in (TRANG_THAI_DA_HUY, TRANG_THAI_DA_DUYET, TRANG_THAI_TU_CHOI):
        assert huy_duoc(tt) is False
    with pytest.raises(ValueError):
        huy_duoc("la")


def test_hai_hang_audit_moi_la_mutation_va_khong_mang_ly_do(policy, khong_gian):
    """Hai hằng trong danh mục đóng; sự kiện dựng ra ở tầng mutation, `chi_tiet` năm khóa, không `ly_do`."""
    assert {EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_CANCEL} <= EVENTS
    assert (EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_CANCEL) == ("breakglass_request", "breakglass_cancel")
    ctx = vai(policy, "tech_support", khong_gian)
    yc = _yc(act="tech_support01", ly_do="Khách VIP đang chờ, mật khẩu abc")
    for event in (EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_CANCEL):
        sk = su_kien_break_glass(event, ctx, yc)
        assert sk.tier == TIER_MUTATION and sk.event == event
        assert (sk.act, sk.role, sk.space, sk.policy_version) == ("tech_support01", "tech_support", khong_gian, policy.policy_version)
        assert sk.hyperedge_ids == ("HE-02",)
        assert dict(sk.chi_tiet) == {CT_REQUEST_ID: yc.id, CT_TRANG_THAI: yc.trang_thai, CT_K: 0, CT_THOI_HAN_PHUT: 60, CT_NHOM_DUYET: "Tech Support"}
        assert "ly_do" not in sk.chi_tiet and "VIP" not in json.dumps(dict(sk.chi_tiet), ensure_ascii=False)


def _yc(**sua) -> YeuCauBreakGlass:
    luc = thoi_diem_utc()
    goc = dict(
        id=ma_yeu_cau(), act="ts01", role="tech_support", space="synth", hyperedge_id="HE-02",
        scope="noi_bo", content_type="bao_cao_su_co", nhom_duyet="Tech Support", ly_do="lý do",
        k=K_MAC_DINH, thoi_han_phut=THOI_HAN_PHUT, trang_thai=TRANG_THAI_CHO_DUYET, tao_luc=luc, cap_nhat=luc,
    )
    goc.update(sua)
    return YeuCauBreakGlass(**goc)


def test_ma_yeu_cau_va_than_201_dung_khoa_dong():
    ma = ma_yeu_cau()
    assert ma.startswith("bg-") and len(ma) == 15 and int(ma[3:], 16) >= 0
    assert ma != ma_yeu_cau()
    yc = _yc()
    than = dict_yeu_cau(yc)
    assert tuple(than) == KHOA_YEU_CAU == (
        "id", "act", "role", "space", "hyperedge_id", "scope", "content_type", "nhom_duyet",
        "trang_thai", "k", "thoi_han_phut", "ly_do", "tao_luc", "cap_nhat",
    )
    assert than["k"] == 0 and than["thoi_han_phut"] == 60 and than["trang_thai"] == "cho_duyet"
    assert "ly_do_tu_choi" not in than and "xu_ly_boi" not in than


@pytest.mark.parametrize(
    "sua",
    [
        {"act": ""}, {"nhom_duyet": " "}, {"ly_do": ""}, {"ly_do": "x" * (DAI_LY_DO_TOI_DA + 1)},
        {"k": -1}, {"k": True}, {"thoi_han_phut": 0}, {"trang_thai": "la"},
        {"tao_luc": "2026-09-06T10:00:00"}, {"cap_nhat": "hôm qua"},
    ],
    ids=["act_rong", "nhom_rong", "ly_do_rong", "ly_do_dai", "k_am", "k_bool", "han_0", "trang_thai_la", "tao_luc_khong_utc", "cap_nhat_hong"],
)
def test_yeu_cau_tu_kiem_luc_dung(sua):
    with pytest.raises((ValueError, TypeError)):
        _yc(**sua)


def test_kiem_ly_do_ba_ma():
    assert kiem_ly_do("  Khách VIP đang chờ ") == "Khách VIP đang chờ"
    assert len(kiem_ly_do(" " + "x" * DAI_LY_DO_TOI_DA + " ")) == DAI_LY_DO_TOI_DA
    with pytest.raises(LoiHoiDap) as loi:
        kiem_ly_do("   ")
    assert (loi.value.http, loi.value.ma) == (400, MA_LY_DO_RONG)
    with pytest.raises(LoiHoiDap) as loi:
        kiem_ly_do("x" * (DAI_LY_DO_TOI_DA + 1))
    assert (loi.value.http, loi.value.ma) == (400, MA_LY_DO_QUA_DAI)
    # Thông điệp cố định: hai độ dài khác nhau cho cùng một chuỗi, không ghép số vào.
    with pytest.raises(LoiHoiDap) as loi2:
        kiem_ly_do("y" * (DAI_LY_DO_TOI_DA * 3))
    assert loi2.value.thong_diep == loi.value.thong_diep == bg.THONG_DIEP_LY_DO_QUA_DAI
    for xau in (7, "có NUL \x00 ở giữa"):
        with pytest.raises(LoiHoiDap) as loi:
            kiem_ly_do(xau)
        assert loi.value.ma == MA_THAN_YEU_CAU_LA
    assert kiem_hyperedge_id(' "HE-02" ') == "HE-02"
    assert len(kiem_hyperedge_id("h" * DAI_ID_TOI_DA)) == DAI_ID_TOI_DA
    for xau in ("", "   ", None, 3, "h" * (DAI_ID_TOI_DA + 1), "HE-\x0002"):
        with pytest.raises(LoiHoiDap) as loi:
            kiem_hyperedge_id(xau)
        assert loi.value.ma == MA_THAN_YEU_CAU_LA


def test_loi_kho_chi_nhan_dien_postgres_va_socket():
    assert loi_kho(asyncpg.exceptions.PostgresConnectionError("rớt")).ma == MA_KHO_KHONG_SAN_SANG
    assert loi_kho(ConnectionRefusedError()).http == 503
    boc = RuntimeError("bọc")
    boc.__cause__ = asyncpg.exceptions.InterfaceError("pool đóng")
    assert loi_kho(boc) is not None
    assert loi_kho(ValueError("x")) is None and loi_kho(LoiHoiDap(400, "X", "x")) is None


def test_adr_019_co_that_va_noi_ba_quyet_dinh():
    van_ban = ADR_019.read_text(encoding="utf-8")
    for tu in ("HYPEREDGE_KHONG_XIN_DUOC", "HYPEREDGE_DA_THAY_DU", "YEU_CAU_DANG_CHO", "GRANT_CON_HAN", "breakglass_request", "breakglass_cancel", "transaction"):
        assert tu in van_ban, tu


# --- Lớp 2: engine M1 thật ---------------------------------------------------------


def _engine(workspace_dir, khong_gian, policy):
    return asyncio.run(cong_m1(workspace_dir, khong_gian, policy))


def _trich_dan(engine, ngu_canh, ids):
    async def chay():
        with use_context(ngu_canh):
            return await engine.trich_dan_theo_id(ids)

    return asyncio.run(chay())


def _id_l1_ky_vong(bang, ten_vai) -> set[str]:
    return {
        ten_hyperedge(he)
        for he in HYPEREDGES
        if he["id"] in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES)
        and oracle.muc_ky_vong(bang, ten_vai, he["content_type"]) == "L1"
    }


BON_TEN = tuple(ten_hyperedge(he) for he in HYPEREDGES)


def test_trich_dan_theo_id_khop_oracle_va_id_vang_khong_loi(workspace_dir, khong_gian, policy, bang):
    """Mỗi vai: dict đúng bằng tập thấy được của oracle, mức và nhóm đúng, id lạ vắng mà không lỗi."""
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    for ten_vai in HAI_VAI:
        driver.xoa_nhat_ky()
        ra = _trich_dan(engine, vai(policy, ten_vai, khong_gian), BON_TEN + ("HE-KHONG-CO", BON_TEN[0]))
        thay = {ten_hyperedge(he) for he in HYPEREDGES if he["id"] in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES)}
        assert set(ra) == thay, ten_vai
        for id_he, td in ra.items():
            he = next(h for h in HYPEREDGES if ten_hyperedge(h) == id_he)
            assert isinstance(td, TrichDan) and td.id == id_he
            assert td.level == oracle.muc_ky_vong(bang, ten_vai, he["content_type"])
            assert (td.scope, td.content_type) == (he["scope"], he["content_type"])
            assert td.owner_group == oracle.nhom_ky_vong(he["content_type"])
        assert {i for i, td in ra.items() if td.level == "L1"} == _id_l1_ky_vong(bang, ten_vai)
        cau = [lg for lg in driver.cac_cau_doc() if lg.loai == "doc:trich_dan_cua"]
        assert len(cau) == 1 and set(cau[0].params["ids"]) == set(BON_TEN + ("HE-KHONG-CO",))
        assert set(cau[0].params["keys"]) == oracle.allowed_keys_ky_vong(bang, ten_vai)["hyperedges"]
    assert llm.so_lan == 0
    assert engine.so_audit.cac_su_kien(EVENT_LLM_COST) == [] and engine.so_audit.cac_su_kien(EVENT_EMBEDDING_COST) == []


def test_trich_dan_theo_id_rong_khong_cham_kho_va_tu_choi_ngu_canh_he_thong(workspace_dir, khong_gian, policy):
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    driver.xoa_nhat_ky()
    assert _trich_dan(engine, vai(policy, "devops", khong_gian), []) == {}
    assert driver.cac_cau_doc() == []
    with pytest.raises(TrichDanNgoaiQuyen):
        _trich_dan(engine, ngu_canh_ingest(khong_gian, policy), BON_TEN[:1])
    # Dãy rỗng dưới ngữ cảnh hệ thống vẫn bị từ chối: ngữ cảnh đọc trước nhánh rút gọn.
    driver.xoa_nhat_ky()
    with pytest.raises(TrichDanNgoaiQuyen):
        _trich_dan(engine, ngu_canh_ingest(khong_gian, policy), [])
    assert driver.cac_cau_doc() == []


def test_trich_dan_theo_id_khoa_khong_tach_duoc_la_ma_on_dinh(monkeypatch, workspace_dir, khong_gian, policy):
    """Adapter trả một khóa không có `:`: `TrichDanNgoaiQuyen` giữ nguyên nhân, không `ValueError` trần."""
    from adapters.trich_dan import dung_theo_id

    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    graph = engine.chunk_entity_relation_graph

    async def _hong(ids):
        return {i: ("khong-tach", ("subject",)) for i in ids}

    monkeypatch.setattr(graph, "trich_dan_cua", _hong)
    with pytest.raises(TrichDanNgoaiQuyen) as loi:
        _trich_dan(engine, vai(policy, "devops", khong_gian), ["A"])
    assert isinstance(loi.value.__cause__, (TypeError, ValueError))
    # Hàm thuần: id vắng thì vắng, id trùng chỉ một mục, ngữ cảnh hệ thống từ chối cả với dãy rỗng.
    ctx = vai(policy, "devops", khong_gian)
    ra = dung_theo_id(ctx, ["A", "x", "A"], {"A": ("noi_bo:runbook", ("subject",))}, lambda ct: "DevOps")
    assert list(ra) == ["A"] and ra["A"].owner_group == "DevOps" and ra["A"].level == "L2"
    with pytest.raises(TrichDanNgoaiQuyen):
        dung_theo_id(ngu_canh_ingest(khong_gian, policy), [], {}, lambda ct: None)


def test_ba_id_vo_hinh_cung_mot_cau_cypher_duoi_vai_tech_support(workspace_dir, khong_gian, policy):
    """HE-03 (L0), `HE-KHONG-CO`, HE-04 (khác space): mỗi ca một câu `trich_dan_cua`, kết quả rỗng như nhau."""
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    ctx = vai(policy, "tech_support", khong_gian)
    for id_he in (ten_hyperedge(THEO_ID["HE-03"]), "HE-KHONG-CO", ten_hyperedge(THEO_ID["HE-04"])):
        driver.xoa_nhat_ky()
        assert _trich_dan(engine, ctx, [id_he]) == {}
        assert [lg.loai for lg in driver.cac_cau_doc()] == ["doc:trich_dan_cua"]
    assert llm.so_lan == 0


# --- Lớp 3: HTTP với kho giả + engine giả --------------------------------------------


def _td(id_he, level, scope="noi_bo", content_type="bao_cao_su_co", nhom="Tech Support", che=("cause", "owner")):
    return TrichDan(id=id_he, level=level, scope=scope, content_type=content_type, masked_slots=tuple(che) if level == "L1" else ("owner",), owner_group=nhom)


def _engine_gia(**them) -> EngineGia:
    tra = {
        "HE-01": _td("HE-01", "L2", content_type="runbook", nhom="DevOps"),
        "HE-02": _td("HE-02", "L1"),
    }
    tra.update(them)
    return EngineGia(trich_dan_tra=tra)


def _kho_gia(khong_gian: str = "synth", them=()) -> KhoGia:
    dong = {
        TEN_GO["ts01"]: replace(_dong("ts01"), khong_gian=khong_gian),
        TEN_GO["dev01"]: replace(_dong("dev01", role="devops", demo=True, admin=True), khong_gian=khong_gian),
    }
    dong.update(dict(them))
    return KhoGia(dong)


def _client(monkeypatch, kho, audit, engine, **tuy_chon):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo_kho():
        return kho

    async def _mo_audit():
        return audit

    async def _mo_engine(_audit):
        return engine

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    return TestClient(api_main.app, **tuy_chon)


def _token(client, tai_khoan: str, ten_go: str | None = None) -> str:
    kq = client.post("/auth/login", json={"tai_khoan": ten_go or TEN_GO[tai_khoan], "mat_khau": MAT_KHAU})
    assert kq.status_code == 200, kq.text
    return kq.json()["token"]


def _xin(client, token, than):
    return client.post(DUONG, json=than, headers={"Authorization": "Bearer " + token})


def _huy(client, token, id_yc):
    return client.post(f"{DUONG}/{id_yc}/huy", headers={"Authorization": "Bearer " + token})


def _cua_toi(client, token):
    return client.get(DUONG, headers={"Authorization": "Bearer " + token})


def _su_kien_bg(audit):
    return [sk for sk in audit.su_kien if sk.event in (EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_CANCEL)]


def test_http_ts01_xin_he02_201_dung_than_va_mot_hang_audit(monkeypatch, kho_break_glass_gia):
    audit, engine = AuditGia(), _engine_gia()
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        token = _token(client, "ts01")
        so_truoc = len(audit.su_kien)
        policy_version = client.app.state.kho_chinh_sach.hien_tai().policy_version
        kq = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "Khách VIP đang chờ"})
    assert kq.status_code == 201, kq.text
    than = kq.json()
    assert tuple(than) == KHOA_YEU_CAU
    assert than["id"].startswith("bg-") and len(than["id"]) == 15
    assert (than["act"], than["role"], than["space"]) == ("ts01", "tech_support", "synth")
    assert (than["hyperedge_id"], than["scope"], than["content_type"]) == ("HE-02", "noi_bo", "bao_cao_su_co")
    assert (than["nhom_duyet"], than["trang_thai"], than["k"], than["thoi_han_phut"]) == ("Tech Support", "cho_duyet", 0, 60)
    assert than["ly_do"] == "Khách VIP đang chờ"
    assert than["tao_luc"] == than["cap_nhat"] and than["tao_luc"].endswith("+00:00")
    # Engine hỏi dưới ngữ cảnh vai, đúng id, không lời gọi hỏi đáp/đồ thị nào.
    assert engine.ids == [["HE-02"]] and engine.cau_hoi == []
    assert engine.ngu_canh[0].role == "tech_support" and not engine.ngu_canh[0].bypass_filter
    # Kho có đúng một hàng, và nó là thứ thân 201 chép ra.
    assert list(kho_break_glass_gia.yeu_cau) == [than["id"]]
    assert dict_yeu_cau(kho_break_glass_gia.yeu_cau[than["id"]]) == than
    # AC-2: hàng `breakglass_request` là hàng duy nhất của lượt, tầng mutation.
    moi = audit.su_kien[so_truoc:]
    assert [sk.event for sk in moi] == [EVENT_BREAKGLASS_REQUEST]
    sk = moi[0]
    assert sk.tier == TIER_MUTATION and sk.policy_version == policy_version
    assert (sk.act, sk.role, sk.space, sk.hyperedge_ids) == ("ts01", "tech_support", "synth", ("HE-02",))
    assert dict(sk.chi_tiet) == {CT_REQUEST_ID: than["id"], CT_TRANG_THAI: "cho_duyet", CT_K: 0, CT_THOI_HAN_PHUT: 60, CT_NHOM_DUYET: "Tech Support"}
    assert "VIP" not in json.dumps(dict(sk.chi_tiet), ensure_ascii=False)


def test_http_ba_id_vo_hinh_byte_identical_404_khong_hang_khong_audit(monkeypatch, kho_break_glass_gia):
    """Engine giả không biết HE-03/`HE-KHONG-CO`/HE-04 dưới vai này: cả ba vắng, cả ba một thân."""
    audit, engine = AuditGia(), _engine_gia()
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        token = _token(client, "ts01")
        so_truoc = len(audit.su_kien)
        ba = [_xin(client, token, {"hyperedge_id": i, "ly_do": "xin"}) for i in ("HE-03", "HE-KHONG-CO", "HE-04")]
    assert [kq.status_code for kq in ba] == [404] * 3
    assert ba[0].content == ba[1].content == ba[2].content
    assert ba[0].json()["error"]["code"] == MA_HYPEREDGE_KHONG_XIN_DUOC
    assert "HE-" not in ba[0].text
    assert kho_break_glass_gia.yeu_cau == {} and kho_break_glass_gia.so_lan_tao == 0
    assert audit.su_kien[so_truoc:] == []
    assert engine.ids == [["HE-03"], ["HE-KHONG-CO"], ["HE-04"]]


def test_http_l2_la_400_da_thay_du_khong_hang(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        token = _token(client, "ts01")
        so_truoc = len(audit.su_kien)
        kq = _xin(client, token, {"hyperedge_id": "HE-01", "ly_do": "xin"})
    assert kq.status_code == 400 and kq.json()["error"]["code"] == MA_HYPEREDGE_DA_THAY_DU
    assert kho_break_glass_gia.yeu_cau == {} and audit.su_kien[so_truoc:] == []


def test_http_xin_lai_khi_dang_cho_409_hai_tang(monkeypatch, kho_break_glass_gia):
    """Phép kiểm trước insert và "index duy nhất" (bỏ phép kiểm trước) ra cùng mã; đổi vai không mở thẻ thứ hai."""
    audit = AuditGia()
    kho_users = _kho_gia(them={"TS01B": replace(_dong("ts01"), role="devops")})
    with _client(monkeypatch, kho_users, audit, _engine_gia()) as client:
        token = _token(client, "ts01")
        assert _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "lần một"}).status_code == 201
        so_truoc = len(audit.su_kien)
        lai = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "lần hai"})
        assert lai.status_code == 409 and lai.json()["error"]["code"] == MA_YEU_CAU_DANG_CHO
        kho_break_glass_gia.bo_kiem_truoc = True
        race = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "chen nhau"})
        assert race.status_code == 409 and race.content == lai.content
        # Cùng `act` ở vai khác (cùng tài khoản `ts01`, token vai devops): vẫn 409.
        token_vai_khac = _token(client, "ts01", "TS01B")
        khac_vai = _xin(client, token_vai_khac, {"hyperedge_id": "HE-02", "ly_do": "vai khác"})
        assert khac_vai.status_code == 409 and khac_vai.json()["error"]["code"] == MA_YEU_CAU_DANG_CHO
    assert len(kho_break_glass_gia.yeu_cau) == 1 and _su_kien_bg(audit)[1:] == []


def test_http_grant_con_han_409_theo_cap_act_role_va_het_han_thi_tao_duoc(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        token = _token(client, "ts01")
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="tech_support", hyperedge_ids=["HE-02"], con_han_phut=10))
        kq = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"})
        assert kq.status_code == 409 and kq.json()["error"]["code"] == MA_GRANT_CON_HAN
        assert kho_break_glass_gia.yeu_cau == {}
        # Grant ở vai khác ngủ: không chặn xin ở vai hiện tại. Grant hết hạn cũng không.
        kho_break_glass_gia.grants.clear()
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="devops", hyperedge_ids=["HE-02"], con_han_phut=10))
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="tech_support", hyperedge_ids=["HE-02"], con_han_phut=-1))
        assert _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"}).status_code == 201


def test_http_huy_dang_cho_200_audit_cancel_va_xin_lai_duoc(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        token = _token(client, "ts01")
        tao = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"}).json()
        so_truoc = len(audit.su_kien)
        kq = _huy(client, token, tao["id"])
        assert kq.status_code == 200, kq.text
        than = kq.json()
        assert tuple(than) == KHOA_YEU_CAU and than["trang_thai"] == TRANG_THAI_DA_HUY
        assert than["cap_nhat"] >= than["tao_luc"] and {k: v for k, v in than.items() if k not in ("trang_thai", "cap_nhat")} == {k: v for k, v in tao.items() if k not in ("trang_thai", "cap_nhat")}
        moi = audit.su_kien[so_truoc:]
        assert [sk.event for sk in moi] == [EVENT_BREAKGLASS_CANCEL] and moi[0].tier == TIER_MUTATION
        assert dict(moi[0].chi_tiet)[CT_TRANG_THAI] == TRANG_THAI_DA_HUY and dict(moi[0].chi_tiet)[CT_REQUEST_ID] == tao["id"]
        assert moi[0].hyperedge_ids == ("HE-02",)
        lai = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin lại"})
        assert lai.status_code == 201 and lai.json()["id"] != tao["id"]
        # Hủy lần hai: 409, không audit.
        so_truoc = len(audit.su_kien)
        hai = _huy(client, token, tao["id"])
        assert hai.status_code == 409 and hai.json()["error"]["code"] == MA_YEU_CAU_KHONG_CON_CHO
        assert audit.su_kien[so_truoc:] == []


def test_http_huy_cua_nguoi_khac_va_id_la_404_byte_identical(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        ts, dev = _token(client, "ts01"), _token(client, "dev01")
        tao = _xin(client, ts, {"hyperedge_id": "HE-02", "ly_do": "xin"}).json()
        so_truoc = len(audit.su_kien)
        cua_nguoi_khac = _huy(client, dev, tao["id"])
        id_la = _huy(client, ts, "bg-000000000000")
        # Id không mang tiền tố `bg-`: 404 cùng thân, và không chạm kho.
        kho_break_glass_gia.no = RuntimeError("không được chạm kho")
        khong_tien_to = _huy(client, ts, "abc")
        kho_break_glass_gia.no = None
    assert cua_nguoi_khac.status_code == id_la.status_code == khong_tien_to.status_code == 404
    assert cua_nguoi_khac.content == id_la.content == khong_tien_to.content
    assert id_la.json()["error"]["code"] == MA_YEU_CAU_KHONG_CO
    assert kho_break_glass_gia.yeu_cau[tao["id"]].trang_thai == TRANG_THAI_CHO_DUYET
    assert audit.su_kien[so_truoc:] == []


def test_http_huy_khac_space_404_byte_identical_voi_id_la(monkeypatch, kho_break_glass_gia):
    """Cùng `act`, token của space khác: yêu cầu của space cũ không hủy được, thân như id lạ."""
    audit = AuditGia()
    kho_users = _kho_gia(them={"TS01K": replace(_dong("ts01"), khong_gian="khac")})
    with _client(monkeypatch, kho_users, audit, _engine_gia()) as client:
        ts = _token(client, "ts01")
        tao = _xin(client, ts, {"hyperedge_id": "HE-02", "ly_do": "xin"}).json()
        ts_khac = _token(client, "ts01", "TS01K")
        so_truoc = len(audit.su_kien)
        khac_space = _huy(client, ts_khac, tao["id"])
        id_la = _huy(client, ts, "bg-000000000000")
    assert khac_space.status_code == 404 and khac_space.content == id_la.content
    assert kho_break_glass_gia.yeu_cau[tao["id"]].trang_thai == TRANG_THAI_CHO_DUYET
    assert [sk.event for sk in _su_kien_bg(audit)] == [EVENT_BREAKGLASS_REQUEST], "không hàng cancel nào"
    assert audit.su_kien[so_truoc:] == []


@pytest.mark.parametrize(
    "than,ma",
    [
        ({"hyperedge_id": "HE-02", "ly_do": "   "}, MA_LY_DO_RONG),
        ({"hyperedge_id": "HE-02", "ly_do": "x" * (DAI_LY_DO_TOI_DA + 1)}, MA_LY_DO_QUA_DAI),
        ({"hyperedge_id": "HE-02"}, MA_THAN_YEU_CAU_LA),
        ({"ly_do": "xin"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "HE-02", "ly_do": "xin", "k": 3}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "HE-02", "ly_do": "xin", "role": "devops"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": ["HE-02"], "ly_do": "xin"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "  ", "ly_do": "xin"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "HE-02", "ly_do": 5}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "h" * (DAI_ID_TOI_DA + 1), "ly_do": "xin"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "HE-\x0002", "ly_do": "xin"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "HE-02", "ly_do": "xin\x00"}, MA_THAN_YEU_CAU_LA),
        ({"hyperedge_id": "HE-02", "ly_do": "x" * (DAI_LY_DO_TOI_DA * 4 + 1)}, MA_THAN_YEU_CAU_LA),
    ],
    ids=["ly_do_rong", "ly_do_dai", "thieu_ly_do", "thieu_id", "thua_k", "thua_role", "id_list", "id_rong", "ly_do_int", "id_qua_dai", "id_nul", "ly_do_nul", "ly_do_qua_tran_pydantic"],
)
def test_http_than_sai_400_khong_cham_kho(monkeypatch, kho_break_glass_gia, than, ma):
    engine = _engine_gia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        kq = _xin(client, _token(client, "ts01"), than)
    assert kq.status_code == 400, kq.text
    assert kq.json()["error"]["code"] == ma
    assert engine.ids == [] and kho_break_glass_gia.so_lan_tao == 0 and kho_break_glass_gia.yeu_cau == {}


def test_http_audit_hong_500_rollback_va_khoe_lai_thi_tao_duoc(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        token = _token(client, "ts01")
        audit.no = RuntimeError("audit_log chết")
        hong = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"})
        assert hong.status_code == 500 and hong.json()["error"]["code"] == MA_AUDIT_GHI_HONG
        assert kho_break_glass_gia.yeu_cau == {}, "audit hỏng mà bảng vẫn có hàng: không rollback"
        audit.no = None
        tao = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"})
        assert tao.status_code == 201
        # Hủy cũng vậy: audit hỏng thì trạng thái không đổi.
        audit.no = RuntimeError("audit_log chết")
        hong = _huy(client, token, tao.json()["id"])
        assert hong.status_code == 500 and hong.json()["error"]["code"] == MA_AUDIT_GHI_HONG
        assert kho_break_glass_gia.yeu_cau[tao.json()["id"]].trang_thai == TRANG_THAI_CHO_DUYET


def test_http_audit_qua_han_500_va_khong_hang(monkeypatch, kho_break_glass_gia):
    """Port audit treo lâu hơn trần `THOI_HAN_BIEN_DOI`: 500 `AUDIT_GHI_HONG`, kho không có hàng."""
    audit = AuditGia()

    async def _treo(su_kien):
        await asyncio.sleep(0.5)
        audit.su_kien.append(su_kien)

    monkeypatch.setattr(audit, "ghi", _treo)
    monkeypatch.setattr(bg, "THOI_HAN_BIEN_DOI", 0.05)
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        kq = _xin(client, _token(client, "ts01"), {"hyperedge_id": "HE-02", "ly_do": "xin"})
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_AUDIT_GHI_HONG
    assert kho_break_glass_gia.yeu_cau == {}


def test_http_danh_sach_cua_toi_moi_nhat_truoc_chi_cua_minh_toi_da_100(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    engine = _engine_gia(**{"HE-05": _td("HE-05", "L1", content_type="canh_bao", nhom="DevOps")})
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        ts, dev = _token(client, "ts01"), _token(client, "dev01")
        a = _xin(client, ts, {"hyperedge_id": "HE-02", "ly_do": "một"}).json()
        b = _xin(client, ts, {"hyperedge_id": "HE-05", "ly_do": "hai"}).json()
        assert _xin(client, dev, {"hyperedge_id": "HE-02", "ly_do": "của dev"}).status_code == 201
        kq = _cua_toi(client, ts)
        assert kq.status_code == 200
        ds = kq.json()["yeu_cau"]
        assert tuple(kq.json()) == ("yeu_cau",)
        assert [y["id"] for y in ds] == sorted([a["id"], b["id"]], key=lambda i: ({a["id"]: a, b["id"]: b}[i]["tao_luc"], i), reverse=True)
        assert {y["act"] for y in ds} == {"ts01"} and all(tuple(y) == KHOA_YEU_CAU for y in ds)
        assert len(_cua_toi(client, dev).json()["yeu_cau"]) == 1
        # Trần 100: chèn thẳng 150 hàng của ts01 vào kho giả.
        for i in range(150):
            yc = _yc(id=f"bg-{i:012x}", hyperedge_id=f"X-{i}", tao_luc="2026-01-01T00:00:00+00:00", cap_nhat="2026-01-01T00:00:00+00:00")
            kho_break_glass_gia.yeu_cau[yc.id] = yc
        assert len(_cua_toi(client, ts).json()["yeu_cau"]) == SO_YEU_CAU_TOI_DA == 100
    assert engine.cau_hoi == []


def test_http_khong_token_401_va_vai_la_403(monkeypatch, kho_break_glass_gia):
    engine = _engine_gia()
    kho_users = _kho_gia(them={"LA01": replace(_dong("la01"), role="vai_la")})
    with _client(monkeypatch, kho_users, AuditGia(), engine) as client:
        for kq in (
            client.post(DUONG, json={"hyperedge_id": "HE-02", "ly_do": "xin"}),
            client.get(DUONG),
            client.post(f"{DUONG}/bg-1/huy"),
        ):
            assert kq.status_code == 401 and kq.json()["error"]["code"] == "TOKEN_KHONG_HOP_LE"
        token = _token(client, "la01", "LA01")
        for kq in (
            _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"}),
            _cua_toi(client, token),
            _huy(client, token, "bg-1"),
        ):
            assert kq.status_code == 403 and kq.json()["error"]["code"] == RoleUnknown.code
    assert engine.ids == [] and kho_break_glass_gia.so_lan_tao == 0


def test_http_kho_khong_san_sang_503_neo4j_va_postgres(monkeypatch, kho_break_glass_gia):
    with _client(monkeypatch, _kho_gia(), AuditGia(), EngineGia(loi=Neo4jUnavailable("rớt"))) as client:
        kq = _xin(client, _token(client, "ts01"), {"hyperedge_id": "HE-02", "ly_do": "xin"})
    assert kq.status_code == 503 and kq.json()["error"]["code"] == MA_KHO_KHONG_SAN_SANG
    assert kho_break_glass_gia.so_lan_tao == 0
    with _client(monkeypatch, _kho_gia(), AuditGia(), _engine_gia()) as client:
        token = _token(client, "ts01")
        kho_break_glass_gia.no = asyncpg.exceptions.PostgresConnectionError("postgres rớt")
        ba = [
            _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"}),
            _huy(client, token, "bg-1"),
            _cua_toi(client, token),
        ]
    for kq in ba:
        assert kq.status_code == 503 and kq.json()["error"]["code"] == MA_KHO_KHONG_SAN_SANG
    assert "postgres" not in ba[0].text.lower()


def test_http_khong_nhom_duyet_500_khong_hang(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    engine = _engine_gia(**{"HE-02": _td("HE-02", "L1", nhom=None)})
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        token = _token(client, "ts01")
        so_truoc = len(audit.su_kien)
        kq = _xin(client, token, {"hyperedge_id": "HE-02", "ly_do": "xin"})
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_NHOM_DUYET_KHONG_CO
    assert kho_break_glass_gia.yeu_cau == {} and audit.su_kien[so_truoc:] == []


def test_http_cua_quyen_lech_500_mang_ma(monkeypatch, kho_break_glass_gia):
    with _client(monkeypatch, _kho_gia(), AuditGia(), EngineGia(loi=TrichDanNgoaiQuyen("khóa hỏng"))) as client:
        kq = _xin(client, _token(client, "ts01"), {"hyperedge_id": "HE-02", "ly_do": "xin"})
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_TRICH_DAN_NGOAI_QUYEN
    assert kho_break_glass_gia.so_lan_tao == 0


# --- Lớp 4: HTTP với engine M1 thật, hai tài khoản seed -----------------------------


def test_http_hai_tai_khoan_seed_tren_engine_m1_that(monkeypatch, workspace_dir, khong_gian, policy, bang, kho_break_glass_gia):
    """AC-1: tập id xin được của mỗi vai bằng đúng tập L1 của oracle; hai yêu cầu độc lập, khác `act`.

    Trên fixture với `policy-day-du.yaml`, `tech_support` thấy HE-02 ở L1 còn
    `devops` thấy HE-02 ở **L2** (và HE-03 ở L1), nên "dev01 xin HE-02" của
    spec ra 400 `HYPEREDGE_DA_THAY_DU` - đúng vế "không id nào ngoài tập L1 tạo
    được"; yêu cầu thứ hai của dev01 là HE-03.
    """
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    da_tao: dict[str, dict] = {}
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        for tai_khoan, ten_vai in (("ts01", "tech_support"), ("dev01", "devops")):
            token = _token(client, tai_khoan)
            ky_vong = _id_l1_ky_vong(bang, ten_vai)
            tao_duoc = set()
            for he in HYPEREDGES:
                id_he = ten_hyperedge(he)
                driver.xoa_nhat_ky()
                kq = _xin(client, token, {"hyperedge_id": id_he, "ly_do": f"{tai_khoan} xin"})
                assert [lg.loai for lg in driver.cac_cau_doc()] == ["doc:trich_dan_cua"], id_he
                muc = oracle.muc_ky_vong(bang, ten_vai, he["content_type"])
                if kq.status_code == 201:
                    tao_duoc.add(id_he)
                    than = kq.json()
                    assert (than["act"], than["role"], than["space"]) == (tai_khoan, ten_vai, khong_gian)
                    assert (than["scope"], than["content_type"]) == (he["scope"], he["content_type"])
                    assert than["nhom_duyet"] == oracle.nhom_ky_vong(he["content_type"])
                    da_tao[tai_khoan] = than
                elif he["id"] in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES) and muc == "L2":
                    assert kq.status_code == 400 and kq.json()["error"]["code"] == MA_HYPEREDGE_DA_THAY_DU, id_he
                else:
                    assert kq.status_code == 404 and kq.json()["error"]["code"] == MA_HYPEREDGE_KHONG_XIN_DUOC, id_he
            assert tao_duoc == ky_vong, ten_vai
            assert tao_duoc, f"{ten_vai} không có hyperedge L1 nào trên fixture: AC-1 không chấm được"
        # `dev01` xin HE-02 (L2 với devops): 400, và yêu cầu HE-02 của `ts01` không đổi.
        kq = _xin(client, _token(client, "dev01"), {"hyperedge_id": ten_hyperedge(THEO_ID["HE-02"]), "ly_do": "dev xin"})
        assert kq.status_code == 400 and kq.json()["error"]["code"] == MA_HYPEREDGE_DA_THAY_DU
    assert da_tao["ts01"]["hyperedge_id"] == ten_hyperedge(THEO_ID["HE-02"])
    assert da_tao["dev01"]["hyperedge_id"] == ten_hyperedge(THEO_ID["HE-03"])
    assert da_tao["ts01"]["id"] != da_tao["dev01"]["id"] and da_tao["ts01"]["act"] != da_tao["dev01"]["act"]
    assert len(kho_break_glass_gia.yeu_cau) == 2
    # Không lời gọi LLM/embedding nào trên cả đường; audit chỉ có hai hàng break-glass (+ auth_login).
    assert llm.so_lan == 0
    assert engine.so_audit.cac_su_kien(EVENT_LLM_COST) == [] and engine.so_audit.cac_su_kien(EVENT_EMBEDDING_COST) == []
    assert [sk.event for sk in _su_kien_bg(audit)] == [EVENT_BREAKGLASS_REQUEST] * 2
    assert {sk.act for sk in _su_kien_bg(audit)} == {"ts01", "dev01"}
    assert not [sk for sk in audit.su_kien if sk.event in ("query", "refusal")]


def test_http_ba_id_vo_hinh_tren_engine_that_byte_identical(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        token = _token(client, "ts01")
        so_truoc = len(audit.su_kien)
        ba = []
        for id_he in (ten_hyperedge(THEO_ID["HE-03"]), "HE-KHONG-CO", ten_hyperedge(THEO_ID["HE-04"])):
            driver.xoa_nhat_ky()
            ba.append(_xin(client, token, {"hyperedge_id": id_he, "ly_do": "xin"}))
            assert [lg.loai for lg in driver.cac_cau_doc()] == ["doc:trich_dan_cua"]
    assert [kq.status_code for kq in ba] == [404] * 3 and ba[0].content == ba[1].content == ba[2].content
    assert ba[0].content == json.dumps(
        {"error": {"code": MA_HYPEREDGE_KHONG_XIN_DUOC, "message": bg.THONG_DIEP_KHONG_XIN_DUOC}}, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert kho_break_glass_gia.yeu_cau == {} and audit.su_kien[so_truoc:] == [] and llm.so_lan == 0


def test_http_hoan_policy_doi_tap_xin_duoc(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    """`tat-phan-quyen`: mọi hyperedge L2 với `tech_support` nên không xin được cái nào; về `day-du` thì HE-02 xin được."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        ts, dev = _token(client, "ts01"), _token(client, "dev01")
        he2 = ten_hyperedge(THEO_ID["HE-02"])
        assert client.post("/admin/policy", json={"id": "tat-phan-quyen"}, headers={"Authorization": "Bearer " + dev}).status_code == 200
        kq = _xin(client, ts, {"hyperedge_id": he2, "ly_do": "xin"})
        assert kq.status_code == 400 and kq.json()["error"]["code"] == MA_HYPEREDGE_DA_THAY_DU
        assert client.post("/admin/policy", json={"id": "day-du"}, headers={"Authorization": "Bearer " + dev}).status_code == 200
        assert _xin(client, ts, {"hyperedge_id": he2, "ly_do": "xin"}).status_code == 201
