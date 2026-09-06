"""Vùng cấp hai pha, duyệt, từ chối, cấp chủ động (story 5.2, FR-20, FR-27, AD-14, AD-16, ĐG5).

Đặc tả viết trước cơ chế: mọi hàng I/O Matrix của spec 5.2 nằm ở đây, cộng bốn
mệnh đề mà không hàng nào phát biểu được một mình.

- **Vùng cấp tính dưới vai xin, hai pha, biên là biên import.** Pha một là
  `k` câu `hyperedge_ke_can` (năm biến của pattern qua ba mệnh đề lọc quyền,
  chấm bằng `canh_moi_bien_deu_bi_loc`) cộng một câu `trich_dan_cua`; pha hai
  là `core.break_glass.loc_vung_cap`, hàm thuần. `k = 0` là không câu lân cận
  nào; trên M1, HE-01 (L2, DevOps) chung entity App01 với HE-02 rớt ở (b) và (c).
- **Owner từ bảng `users`, và không bao giờ là chính người xin.** Khác nhóm,
  chính người xin, tài khoản không có dòng: một thân 403 byte-identical, bảng
  và audit không đổi.
- **UPDATE có điều kiện là nguồn sự thật, grant cùng transaction.** Đã hủy/đã
  duyệt là 409 không grant; grant còn hạn là 409 và yêu cầu **vẫn chờ**; audit
  hỏng là 500 và không grant.
- **`expires_at` không đến từ tiến trình `api`.** Bản giả và bản thật đều trả
  hai mốc từ kho; câu INSERT của bản thật không nhận tham số datetime nào
  (`tests/test_break_glass_postgres.py`).

Ba lớp ở đây: hàm thuần, engine M1 thật (`vung_lan_can`, `hyperedge_ke_can`),
HTTP với `KhoBreakGlassGia` + `EngineGia`. Lớp thứ tư (HTTP với engine M1 thật
qua ba tài khoản seed) ở `tests/test_break_glass_duyet_m1.py`, dùng chung các
helper của file này. Bản Postgres thật ở `tests/test_break_glass_postgres.py`.
"""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from adapters.neo4j import Neo4jUnavailable
from adapters.trich_dan import TrichDan, TrichDanNgoaiQuyen
from api import main as api_main
from api.break_glass import (
    CT_GRANT_ID,
    CT_K,
    CT_NGUOI_NHAN,
    CT_NHOM_DUYET,
    CT_REQUEST_ID,
    CT_THOI_HAN_PHUT,
    CT_TRANG_THAI,
    CT_VAI_NHAN,
    KHOA_GRANT,
    KHOA_YEU_CAU,
    MA_GRANT_CON_HAN,
    MA_HYPEREDGE_DA_THAY_DU,
    MA_HYPEREDGE_KHONG_XIN_DUOC,
    MA_KHONG_PHAI_OWNER,
    MA_LY_DO_QUA_DAI,
    MA_LY_DO_RONG,
    MA_NGUOI_NHAN_KHONG_HOP_LE,
    MA_VUNG_CAP_RONG,
    MA_YEU_CAU_KHONG_CO,
    MA_YEU_CAU_KHONG_CON_CHO,
    MA_NHOM_DUYET_KHONG_CO,
    DAI_LY_DO_TOI_DA,
    SO_YEU_CAU_TOI_DA,
    Grant,
    YeuCauBreakGlass,
    dict_grant,
    ma_grant,
    ma_yeu_cau,
    su_kien_duyet,
)
from api.hoi_dap import MA_AUDIT_GHI_HONG, MA_KHO_KHONG_SAN_SANG, MA_THAN_YEU_CAU_LA, MA_TRICH_DAN_NGOAI_QUYEN
from api.xac_thuc import BIEN_KHOA_KY
from core.audit import (
    EVENT_BREAKGLASS_APPROVE,
    EVENT_BREAKGLASS_CANCEL,
    EVENT_BREAKGLASS_GRANT,
    EVENT_BREAKGLASS_REJECT,
    EVENT_BREAKGLASS_REQUEST,
    EVENT_EMBEDDING_COST,
    EVENT_LLM_COST,
    EVENTS,
    TIER_MUTATION,
    thoi_diem_utc,
)
from core.break_glass import (
    K_MAC_DINH,
    MUC_XIN_DUOC,
    THOI_HAN_PHUT,
    TRANG_THAI_CHO_DUYET,
    TRANG_THAI_DA_DUYET,
    TRANG_THAI_DA_HUY,
    TRANG_THAI_TU_CHOI,
    UngVienVung,
    loc_vung_cap,
    xu_ly_duoc,
)
from core.identity import RoleUnknown
from core.permission import use_context
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.gia_lap_neo4j import canh_moi_bien_deu_bi_loc
from tests.ho_tro_break_glass import KhoBreakGlassGia, chen_grant
from tests.ho_tro_m1 import cong_m1
from tests.nap_kho import ten_hyperedge
from tests.ngu_canh import ngu_canh_ingest, vai
from tests.test_xac_thuc import KHOA_TEST, MAT_KHAU, AuditGia, EngineGia, KhoGia, _dong

GOC = Path(__file__).resolve().parent.parent
ADR_020 = GOC / "docs" / "adr" / "ADR-020-vung-cap-hai-pha-va-duyet.md"

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

DUONG = "/break-glass/yeu-cau"
HANG_CHO = "/break-glass/hang-cho"
GRANT = "/break-glass/grant"
# Ba tài khoản seed: `demo01` là owner Tech Support không phải người xin.
TEN_GO = {"ts01": "TS01", "dev01": "DEV01", "demo01": "DEMO01"}
BA_SU_KIEN_MOI = (EVENT_BREAKGLASS_APPROVE, EVENT_BREAKGLASS_REJECT, EVENT_BREAKGLASS_GRANT)
SU_KIEN_BG = BA_SU_KIEN_MOI + (EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_CANCEL)


# --- Lớp 1: hàm thuần --------------------------------------------------------------


def _uv(id_he, level="L1", scope="noi_bo", content_type="bao_cao_su_co", nhom="Tech Support"):
    return UngVienVung(id=id_he, scope=scope, content_type=content_type, level=level, nhom=nhom)


def test_ba_bo_loc_thuan_chi_muc_dung_ca_ba_vao_goc_dung_dau():
    """Hàng "Ba bộ lọc thuần": khác scope / L2 / L0 / khác nhóm rớt; đúng cả ba vào; gốc đầu, còn lại theo id."""
    goc = _uv("HE-02")
    ung_vien = [
        _uv("HE-09"),  # đúng cả ba
        _uv("HE-05", scope="khach_hang_a"),  # (a)
        _uv("HE-01", level="L2", content_type="runbook", nhom="DevOps"),  # (b) và (c)
        _uv("HE-06", level="L0"),  # (b)
        _uv("HE-03", content_type="bi_mat_ha_tang", nhom="DevOps"),  # (c)
        _uv("HE-07", nhom=None),  # (c): không nhóm
        _uv("HE-02"),  # chính gốc, không lặp
        _uv("HE-08"),
        _uv("HE-08"),  # trùng, chỉ một lần
    ]
    assert loc_vung_cap(goc, ung_vien) == ("HE-02", "HE-08", "HE-09")
    assert loc_vung_cap(goc, iter(ung_vien)) == ("HE-02", "HE-08", "HE-09"), "nhận iterator một lượt"
    assert loc_vung_cap(goc, []) == ("HE-02",)
    # Gốc cũng phải qua (b): gốc L2 hay L0, hay gốc không có nhóm, là vùng rỗng.
    assert loc_vung_cap(_uv("HE-02", level="L2"), ung_vien) == ()
    assert loc_vung_cap(_uv("HE-02", level="L0"), ung_vien) == ()
    assert loc_vung_cap(_uv("HE-02", nhom=None), ung_vien) == ()
    # Mức xin được là tham số, không phải hằng chôn trong hàm.
    assert loc_vung_cap(_uv("HE-02", level="L2"), [_uv("HE-01", level="L2")], muc_xin_duoc="L2") == ("HE-01", "HE-02")[::-1]
    assert MUC_XIN_DUOC == "L1"


def test_xu_ly_duoc_cung_luat_huy_duoc():
    assert xu_ly_duoc(TRANG_THAI_CHO_DUYET) is True
    for tt in (TRANG_THAI_DA_HUY, TRANG_THAI_DA_DUYET, TRANG_THAI_TU_CHOI):
        assert xu_ly_duoc(tt) is False
    with pytest.raises(ValueError):
        xu_ly_duoc("la")


def _yc(**sua) -> YeuCauBreakGlass:
    luc = thoi_diem_utc()
    goc = dict(
        id=ma_yeu_cau(), act="ts01", role="tech_support", space="synth", hyperedge_id="HE-02",
        scope="noi_bo", content_type="bao_cao_su_co", nhom_duyet="Tech Support", ly_do="lý do",
        k=K_MAC_DINH, thoi_han_phut=THOI_HAN_PHUT, trang_thai=TRANG_THAI_CHO_DUYET, tao_luc=luc, cap_nhat=luc,
    )
    goc.update(sua)
    return YeuCauBreakGlass(**goc)


def _grant(**sua) -> Grant:
    tao = datetime.fromisoformat(thoi_diem_utc())
    goc = dict(
        id=ma_grant(), request_id="bg-000000000001", act="ts01", role="tech_support", space="synth",
        hyperedge_ids=("HE-02",), expires_at=(tao + timedelta(minutes=60)).isoformat(),
        cap_boi="demo01", tao_luc=tao.isoformat(),
    )
    goc.update(sua)
    return Grant(**goc)


def test_yeu_cau_hai_truong_moi_phai_khop_trang_thai():
    assert _yc(trang_thai=TRANG_THAI_DA_DUYET, xu_ly_boi="demo01").xu_ly_boi == "demo01"
    assert _yc(trang_thai=TRANG_THAI_TU_CHOI, xu_ly_boi="demo01", ly_do_tu_choi="sai ticket").ly_do_tu_choi == "sai ticket"
    for sua in (
        {"xu_ly_boi": "demo01"},  # còn chờ mà đã có người xử lý
        {"trang_thai": TRANG_THAI_DA_DUYET},  # đã duyệt mà không ai duyệt
        {"trang_thai": TRANG_THAI_TU_CHOI, "xu_ly_boi": "demo01"},  # từ chối không lý do
        {"trang_thai": TRANG_THAI_DA_DUYET, "xu_ly_boi": "demo01", "ly_do_tu_choi": "x"},
        {"trang_thai": TRANG_THAI_TU_CHOI, "xu_ly_boi": " ", "ly_do_tu_choi": "x"},
    ):
        with pytest.raises(ValueError):
            _yc(**sua)


def test_grant_va_than_grant_dung_khoa_dong():
    g = _grant()
    assert g.id.startswith("gr-") and len(g.id) == 15 and int(g.id[3:], 16) >= 0
    than = dict_grant(g)
    assert tuple(than) == KHOA_GRANT == (
        "id", "request_id", "act", "role", "space", "hyperedge_ids", "expires_at", "cap_boi", "tao_luc",
    )
    assert than["hyperedge_ids"] == ["HE-02"] and isinstance(than["hyperedge_ids"], list)
    assert dict_grant(_grant(request_id=None))["request_id"] is None
    for sua in (
        {"id": "bg-000000000001"}, {"request_id": "gr-1"}, {"hyperedge_ids": ()},
        {"hyperedge_ids": ("HE-02", "HE-02")}, {"hyperedge_ids": ["HE-02"]},
        {"expires_at": "2000-01-01T00:00:00+00:00"}, {"cap_boi": ""}, {"tao_luc": "hôm qua"},
    ):
        with pytest.raises((ValueError, TypeError)):
            _grant(**sua)


def test_ba_hang_audit_moi_la_mutation_tam_khoa_khong_ly_do(policy, khong_gian):
    assert set(BA_SU_KIEN_MOI) <= EVENTS
    assert BA_SU_KIEN_MOI == ("breakglass_approve", "breakglass_reject", "breakglass_grant")
    owner = vai(policy, "tech_support", khong_gian)
    yc = _yc(trang_thai=TRANG_THAI_DA_DUYET, xu_ly_boi="tech_support01", ly_do="mật khẩu abc")
    g = _grant(request_id=yc.id, hyperedge_ids=("HE-02", "HE-09"))
    sk = su_kien_duyet(
        EVENT_BREAKGLASS_APPROVE, owner, hyperedge_ids=g.hyperedge_ids, nguoi_nhan="ts01",
        vai_nhan="tech_support", nhom_duyet="Tech Support", k=0, thoi_han_phut=60, yc=yc, grant=g,
    )
    assert sk.tier == TIER_MUTATION and sk.event == EVENT_BREAKGLASS_APPROVE
    assert (sk.act, sk.role, sk.space) == ("tech_support01", "tech_support", khong_gian)
    assert sk.hyperedge_ids == ("HE-02", "HE-09")
    assert dict(sk.chi_tiet) == {
        CT_REQUEST_ID: yc.id, CT_TRANG_THAI: TRANG_THAI_DA_DUYET, CT_GRANT_ID: g.id,
        CT_NGUOI_NHAN: "ts01", CT_VAI_NHAN: "tech_support", CT_K: 0, CT_THOI_HAN_PHUT: 60,
        CT_NHOM_DUYET: "Tech Support",
    }
    assert "ly_do" not in sk.chi_tiet and "ly_do_tu_choi" not in sk.chi_tiet
    # Cấp chủ động: không yêu cầu, `request_id`/`trang_thai` là None; từ chối: không grant.
    sk2 = su_kien_duyet(
        EVENT_BREAKGLASS_GRANT, owner, hyperedge_ids=("HE-02",), nguoi_nhan="ts01", vai_nhan="tech_support",
        nhom_duyet="Tech Support", k=0, thoi_han_phut=60, grant=_grant(request_id=None),
    )
    assert dict(sk2.chi_tiet)[CT_REQUEST_ID] is None and dict(sk2.chi_tiet)[CT_TRANG_THAI] is None
    assert dict(sk2.chi_tiet)[CT_GRANT_ID].startswith("gr-")
    sk3 = su_kien_duyet(
        EVENT_BREAKGLASS_REJECT, owner, hyperedge_ids=("HE-02",), nguoi_nhan="ts01", vai_nhan="tech_support",
        nhom_duyet="Tech Support", k=0, thoi_han_phut=60, yc=_yc(trang_thai=TRANG_THAI_TU_CHOI, xu_ly_boi="x", ly_do_tu_choi="bí mật"),
    )
    assert dict(sk3.chi_tiet)[CT_GRANT_ID] is None
    assert "bí mật" not in json.dumps(dict(sk3.chi_tiet), ensure_ascii=False)


def test_adr_020_co_that_va_noi_bon_quyet_dinh():
    van_ban = ADR_020.read_text(encoding="utf-8")
    for tu in (
        "hyperedge_ke_can", "loc_vung_cap", "group_name", "KHONG_PHAI_OWNER", "VUNG_CAP_RONG",
        "NGUOI_NHAN_KHONG_HOP_LE", "make_interval", "breakglass_approve", "breakglass_reject",
        "breakglass_grant", "transaction",
    ):
        assert tu in van_ban, tu


# --- Lớp 2: engine M1 thật ---------------------------------------------------------


def _engine(workspace_dir, khong_gian, policy):
    return asyncio.run(cong_m1(workspace_dir, khong_gian, policy))


def _vung(engine, ngu_canh, ids, k):
    async def chay():
        with use_context(ngu_canh):
            return await engine.vung_lan_can(ids, k)

    return asyncio.run(chay())


def _ke_can(engine, ngu_canh, ids):
    async def chay():
        with use_context(ngu_canh):
            return await engine.chunk_entity_relation_graph.hyperedge_ke_can(ids)

    return asyncio.run(chay())


HE01, HE02, HE03, HE04 = (ten_hyperedge(THEO_ID[i]) for i in ("HE-01", "HE-02", "HE-03", "HE-04"))


def test_vung_k0_chi_goc_khong_cau_ke_can(workspace_dir, khong_gian, policy):
    """Hàng "Vùng k=0": `{HE-02}`, 0 câu `hyperedge_ke_can`, một câu `trich_dan_cua`, không LLM."""
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    ctx = vai(policy, "tech_support", khong_gian)
    driver.xoa_nhat_ky()
    ra = _vung(engine, ctx, [HE02], 0)
    assert list(ra) == [HE02] and ra[HE02].level == "L1" and ra[HE02].owner_group == "Tech Support"
    assert [lg.loai for lg in driver.cac_cau_doc()] == ["doc:trich_dan_cua"]
    assert llm.so_lan == 0
    assert _vung(engine, ctx, [], 0) == {} and _vung(engine, ctx, [], 3) == {}
    for k_sai in (-1, True, 1.0):
        with pytest.raises(ValueError):
            _vung(engine, ctx, [HE02], k_sai)


def test_vung_k1_tren_m1_he01_chung_app01_roi_o_hai_bo_loc(workspace_dir, khong_gian, policy, bang):
    """Hàng "Vùng k=1 trên M1": thô `{HE-02, HE-01}`; sau ba bộ lọc chỉ HE-02; một câu `hyperedge_ke_can` đủ năm biến."""
    from api.break_glass import vung_cap_cua

    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    ctx = vai(policy, "tech_support", khong_gian)
    driver.xoa_nhat_ky()
    tho = _ke_can(engine, ctx, [HE02])
    assert tho == (HE01,), "HE-01 và HE-02 chung subject App01; HE-03/HE-04 rời"
    cau = driver.cac_cau_doc()
    assert [lg.loai for lg in cau] == ["doc:hyperedge_ke_can"]
    canh_moi_bien_deu_bi_loc(cau[0].cypher)
    for bien in ("g", "r1", "e", "r2", "h"):
        assert f"{bien}.space = $space" in cau[0].cypher, bien
    assert set(cau[0].params["keys"]) == oracle.allowed_keys_ky_vong(bang, "tech_support")["hyperedges"]
    assert cau[0].params["ids"] == [HE02]
    # Hợp qua `vung_lan_can`: HE-01 có mặt ở L2 (DevOps); sau ba bộ lọc chỉ còn gốc.
    driver.xoa_nhat_ky()
    ra = _vung(engine, ctx, [HE02], 1)
    assert set(ra) == {HE02, HE01} and ra[HE01].level == "L2" and ra[HE01].owner_group == "DevOps"
    assert [lg.loai for lg in driver.cac_cau_doc()] == ["doc:hyperedge_ke_can", "doc:trich_dan_cua"]
    assert asyncio.run(vung_cap_cua(engine, ctx, HE02, 1)) == (HE02,)
    assert asyncio.run(vung_cap_cua(engine, ctx, HE02, 0)) == (HE02,)
    # k=2: biên sau bước một là {HE-01}; bước hai từ HE-01 chỉ về HE-02 (đã có), hợp không đổi.
    driver.xoa_nhat_ky()
    assert set(_vung(engine, ctx, [HE02], 2)) == {HE02, HE01}
    assert [lg.loai for lg in driver.cac_cau_doc()] == ["doc:hyperedge_ke_can"] * 2 + ["doc:trich_dan_cua"]
    assert llm.so_lan == 0
    assert engine.so_audit.cac_su_kien(EVENT_LLM_COST) == [] and engine.so_audit.cac_su_kien(EVENT_EMBEDDING_COST) == []


def test_ke_can_khong_tra_goc_va_hyperedge_ngoai_quyen_vang(workspace_dir, khong_gian, policy):
    """HE-03 (L0 với tech_support) không bao giờ có mặt; id vào không có trong kết quả; ngữ cảnh hệ thống bị từ chối."""
    from adapters.do_thi import DoThiNgoaiQuyen

    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    ts = vai(policy, "tech_support", khong_gian)
    assert _ke_can(engine, ts, [HE02, HE01]) == ()
    assert _ke_can(engine, ts, [HE03]) == () and _ke_can(engine, ts, ["HE-KHONG-CO"]) == ()
    # devops thấy cả bốn: từ HE-01 tới HE-02 và ngược lại; HE-03/HE-04 không chung entity với ai.
    dev = vai(policy, "devops", khong_gian)
    assert _ke_can(engine, dev, [HE01]) == (HE02,) and _ke_can(engine, dev, [HE03]) == ()
    assert _vung(engine, ts, [HE03], 1) == {}, "gốc vô hình: vùng rỗng, không lỗi"
    with pytest.raises((DoThiNgoaiQuyen, TrichDanNgoaiQuyen)):
        _ke_can(engine, ngu_canh_ingest(khong_gian, policy), [HE02])
    with pytest.raises((DoThiNgoaiQuyen, TrichDanNgoaiQuyen)):
        _vung(engine, ngu_canh_ingest(khong_gian, policy), [HE02], 1)


# --- Lớp 3: HTTP với kho giả + engine giả --------------------------------------------


def _td(id_he, level, scope="noi_bo", content_type="bao_cao_su_co", nhom="Tech Support", che=("cause", "owner")):
    return TrichDan(id=id_he, level=level, scope=scope, content_type=content_type, masked_slots=tuple(che) if level == "L1" else ("owner",), owner_group=nhom)


def _engine_gia(**them) -> EngineGia:
    tra = {
        "HE-01": _td("HE-01", "L2", content_type="runbook", nhom="DevOps"),
        "HE-02": _td("HE-02", "L1"),
        "HE-03": _td("HE-03", "L1", content_type="bi_mat_ha_tang", nhom="DevOps"),
    }
    tra.update(them)
    return EngineGia(trich_dan_tra=tra)


class KhoGiaHaiKhoa(KhoGia):
    """`KhoGia` tra được cả theo tên gõ (đường đăng nhập) lẫn theo `account` (đường owner).

    `KhoGia` khóa dict theo tên gõ (`TS01`) cố ý khác `account` (`ts01`) để bắt
    đột biến `sub=ten`; bảng `users` thật thì hai chuỗi là một cột. Bốn tuyến
    5.2 tra `users` bằng `claim.sub` (là `account`), nên bản giả ở đây tra theo
    cả hai, và gỡ một dòng khỏi dict vẫn là gỡ khỏi cả hai đường.
    """

    async def tra(self, account):
        dong = self.theo_ten.get(account)
        if dong is None:
            dong = next((d for d in self.theo_ten.values() if d.account == account), None)
        return dong


def _kho_gia(khong_gian: str = "synth", them=()) -> KhoGia:
    dong = {
        TEN_GO["ts01"]: replace(_dong("ts01"), khong_gian=khong_gian),
        TEN_GO["dev01"]: replace(_dong("dev01", role="devops", demo=True, admin=True), khong_gian=khong_gian, group_name="DevOps"),
        TEN_GO["demo01"]: replace(_dong("demo01", demo=True), khong_gian=khong_gian),
    }
    dong.update(dict(them))
    return KhoGiaHaiKhoa(dong)


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


def _h(token):
    return {"Authorization": "Bearer " + token}


def _xin(client, token, id_he="HE-02", ly_do="xin"):
    kq = client.post(DUONG, json={"hyperedge_id": id_he, "ly_do": ly_do}, headers=_h(token))
    assert kq.status_code == 201, kq.text
    return kq.json()


def _duyet(client, token, id_yc):
    return client.post(f"{DUONG}/{id_yc}/duyet", headers=_h(token))


def _tu_choi(client, token, id_yc, than=None):
    return client.post(f"{DUONG}/{id_yc}/tu-choi", json={"ly_do": "không đúng ticket"} if than is None else than, headers=_h(token))


def _cap(client, token, than):
    return client.post(GRANT, json=than, headers=_h(token))


def _hang_cho(client, token):
    return client.get(HANG_CHO, headers=_h(token))


def _su_kien(audit, *events):
    return [sk for sk in audit.su_kien if sk.event in (events or SU_KIEN_BG)]


def _tao_yc_ts01(client, kho_bg) -> dict:
    ts = _token(client, "ts01")
    yc = _xin(client, ts)
    assert kho_bg.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET
    return yc


def test_http_demo01_duyet_yeu_cau_he02_cua_ts01_200_grant_va_mot_hang_audit(monkeypatch, kho_break_glass_gia):
    audit, engine = AuditGia(), _engine_gia()
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        engine.vung.clear()
        kq = _duyet(client, demo, yc["id"])
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert tuple(than) == ("yeu_cau", "grant")
    y, g = than["yeu_cau"], than["grant"]
    assert tuple(y) == KHOA_YEU_CAU and tuple(g) == KHOA_GRANT
    assert (y["trang_thai"], y["xu_ly_boi"], y["ly_do_tu_choi"]) == (TRANG_THAI_DA_DUYET, "demo01", None)
    assert y["cap_nhat"] >= y["tao_luc"] and {k: v for k, v in y.items() if k not in ("trang_thai", "xu_ly_boi", "cap_nhat")} == {k: v for k, v in yc.items() if k not in ("trang_thai", "xu_ly_boi", "cap_nhat")}
    assert g["id"].startswith("gr-") and len(g["id"]) == 15
    assert (g["request_id"], g["act"], g["role"], g["space"], g["cap_boi"]) == (yc["id"], "ts01", "tech_support", "synth", "demo01")
    assert g["hyperedge_ids"] == ["HE-02"]
    het, tao = datetime.fromisoformat(g["expires_at"]), datetime.fromisoformat(g["tao_luc"])
    assert het - tao == timedelta(minutes=THOI_HAN_PHUT)
    # Vùng tính dưới ngữ cảnh **người xin** (ts01/tech_support), k = 0, đúng gốc; owner chỉ thấy id.
    assert engine.vung == [(["HE-02"], 0)]
    assert engine.ngu_canh[-1].real_account == "ts01" and engine.ngu_canh[-1].role == "tech_support"
    # Kho: yêu cầu đã đổi, một grant còn hạn cho cặp (ts01, tech_support).
    assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_DA_DUYET
    assert [dict_grant(x) for x in kho_break_glass_gia.grants] == [g]
    assert asyncio.run(kho_break_glass_gia.co_grant_con_han("ts01", "tech_support", "HE-02", "synth")) is True
    # Một hàng `breakglass_approve`, tầng mutation, act/role của owner, vùng cấp, tám khóa, không lý do.
    moi = audit.su_kien[so_truoc:]
    assert [sk.event for sk in moi] == [EVENT_BREAKGLASS_APPROVE]
    sk = moi[0]
    assert sk.tier == TIER_MUTATION and (sk.act, sk.role, sk.space) == ("demo01", "tech_support", "synth")
    assert sk.hyperedge_ids == ("HE-02",)
    assert dict(sk.chi_tiet) == {
        CT_REQUEST_ID: yc["id"], CT_TRANG_THAI: TRANG_THAI_DA_DUYET, CT_GRANT_ID: g["id"], CT_NGUOI_NHAN: "ts01",
        CT_VAI_NHAN: "tech_support", CT_K: 0, CT_THOI_HAN_PHUT: 60, CT_NHOM_DUYET: "Tech Support",
    }


def test_http_sau_duyet_ts01_xin_lai_409_grant_con_han(monkeypatch, kho_break_glass_gia):
    """Đường xin của 5.1 đọc được grant mà 5.2 ghi."""
    with _client(monkeypatch, _kho_gia(), AuditGia(), _engine_gia()) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        assert _duyet(client, _token(client, "demo01"), yc["id"]).status_code == 200
        lai = client.post(DUONG, json={"hyperedge_id": "HE-02", "ly_do": "xin lại"}, headers=_h(_token(client, "ts01")))
    assert lai.status_code == 409 and lai.json()["error"]["code"] == MA_GRANT_CON_HAN


def test_http_khong_phai_owner_va_tu_duyet_403_mot_than_khong_doi_gi(monkeypatch, kho_break_glass_gia):
    """dev01 (DevOps) duyệt/từ chối yêu cầu Tech Support; ts01 tự duyệt; tài khoản không có dòng `users`."""
    audit = AuditGia()
    kho_users = _kho_gia()
    with _client(monkeypatch, kho_users, audit, _engine_gia()) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        ts, dev = _token(client, "ts01"), _token(client, "dev01")
        so_truoc = len(audit.su_kien)
        ba = [_duyet(client, dev, yc["id"]), _tu_choi(client, dev, yc["id"]), _duyet(client, ts, yc["id"]), _tu_choi(client, ts, yc["id"])]
        # Token còn sống mà dòng `users` biến mất: cũng 403, cùng thân.
        del kho_users.theo_ten[TEN_GO["dev01"]]
        ba.append(_duyet(client, dev, yc["id"]))
    assert [kq.status_code for kq in ba] == [403] * 5
    assert len({kq.content for kq in ba}) == 1 and ba[0].json()["error"]["code"] == MA_KHONG_PHAI_OWNER
    assert "ts01" not in ba[0].text and "Tech Support" not in ba[0].text
    assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET
    assert kho_break_glass_gia.grants == [] and audit.su_kien[so_truoc:] == []


def test_http_duyet_da_huy_va_da_duyet_409_khong_grant_khong_audit(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        ts, demo = _token(client, "ts01"), _token(client, "demo01")
        a = _xin(client, ts, "HE-02")
        assert client.post(f"{DUONG}/{a['id']}/huy", headers=_h(ts)).status_code == 200
        b = _xin(client, ts, "HE-02", "lần hai")
        assert _duyet(client, demo, b["id"]).status_code == 200
        so_truoc = len(audit.su_kien)
        so_grant = len(kho_break_glass_gia.grants)
        bon = [_duyet(client, demo, a["id"]), _tu_choi(client, demo, a["id"]), _duyet(client, demo, b["id"]), _tu_choi(client, demo, b["id"])]
    assert [kq.status_code for kq in bon] == [409] * 4
    assert {kq.json()["error"]["code"] for kq in bon} == {MA_YEU_CAU_KHONG_CON_CHO}
    assert len(kho_break_glass_gia.grants) == so_grant and audit.su_kien[so_truoc:] == []
    assert kho_break_glass_gia.yeu_cau[a["id"]].trang_thai == TRANG_THAI_DA_HUY
    assert kho_break_glass_gia.yeu_cau[b["id"]].trang_thai == TRANG_THAI_DA_DUYET


def test_http_id_la_khong_tien_to_khac_space_404_than_cua_5_1(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    kho_users = _kho_gia(them={"DEMO01K": replace(_dong("demo01", demo=True), khong_gian="khac")})
    with _client(monkeypatch, kho_users, audit, _engine_gia()) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        demo, demo_khac = _token(client, "demo01"), _token(client, "demo01", "DEMO01K")
        so_truoc = len(audit.su_kien)
        id_la = _duyet(client, demo, "bg-000000000000")
        kho_break_glass_gia.no = RuntimeError("không được chạm kho")
        khong_tien_to = _duyet(client, demo, "abc")
        khong_tien_to_tc = _tu_choi(client, demo, "abc")
        kho_break_glass_gia.no = None
        khac_space = _duyet(client, demo_khac, yc["id"])
        khac_space_tc = _tu_choi(client, demo_khac, yc["id"])
    for kq in (id_la, khong_tien_to, khong_tien_to_tc, khac_space, khac_space_tc):
        assert kq.status_code == 404 and kq.content == id_la.content
    assert id_la.json()["error"]["code"] == MA_YEU_CAU_KHONG_CO
    assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET
    assert audit.su_kien[so_truoc:] == [] and kho_break_glass_gia.grants == []


def test_http_grant_con_han_409_yeu_cau_van_cho(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="tech_support", hyperedge_ids=["HE-02"], con_han_phut=10))
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        kq = _duyet(client, demo, yc["id"])
    assert kq.status_code == 409 and kq.json()["error"]["code"] == MA_GRANT_CON_HAN
    assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET, "rollback: yêu cầu vẫn chờ"
    assert len(kho_break_glass_gia.grants) == 1 and audit.su_kien[so_truoc:] == []


def test_http_vung_rong_409_yeu_cau_van_cho(monkeypatch, kho_break_glass_gia):
    """Gốc thành L2 với vai xin (bảng hoán), hay adapter không còn thấy gốc: 409 `VUNG_CAP_RONG`, không grant."""
    audit, engine = AuditGia(), _engine_gia()
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        engine.trich_dan_tra["HE-02"] = _td("HE-02", "L2")
        l2 = _duyet(client, demo, yc["id"])
        del engine.trich_dan_tra["HE-02"]
        vang = _duyet(client, demo, yc["id"])
        engine.trich_dan_tra["HE-02"] = _td("HE-02", "L1", nhom=None)
        khong_nhom = _duyet(client, demo, yc["id"])
    for kq in (l2, vang, khong_nhom):
        assert kq.status_code == 409 and kq.json()["error"]["code"] == MA_VUNG_CAP_RONG
    assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET
    assert kho_break_glass_gia.grants == [] and audit.su_kien[so_truoc:] == [] and kho_break_glass_gia.so_lan_duyet == 0


def test_http_vung_k1_qua_engine_gia_loc_ung_vien(monkeypatch, kho_break_glass_gia):
    """Yêu cầu mang k=1 (chèn thẳng): grant phủ ứng viên qua ba bộ lọc, ứng viên khác nhóm/L2 rớt; vùng ghi vào audit."""
    audit, engine = AuditGia(), _engine_gia(**{
        "HE-09": _td("HE-09", "L1"),
        "HE-10": _td("HE-10", "L1", scope="khach_hang_a"),
    })
    engine.ke_can_tra["HE-02"] = ["HE-01", "HE-09", "HE-10", "HE-03"]
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        yc = _yc(k=1)
        kho_break_glass_gia.yeu_cau[yc.id] = yc
        kq = _duyet(client, _token(client, "demo01"), yc.id)
    assert kq.status_code == 200, kq.text
    assert kq.json()["grant"]["hyperedge_ids"] == ["HE-02", "HE-09"]
    assert engine.vung == [(["HE-02"], 1)]
    assert _su_kien(audit, EVENT_BREAKGLASS_APPROVE)[0].hyperedge_ids == ("HE-02", "HE-09")
    assert dict(_su_kien(audit, EVENT_BREAKGLASS_APPROVE)[0].chi_tiet)[CT_K] == 1


def test_http_grant_con_han_phu_id_lan_can_cung_chan_409(monkeypatch, kho_break_glass_gia):
    """k=1: cặp đang có grant chứa HE-09 (không phải gốc) -> duyệt và cấp cùng 409 `GRANT_CON_HAN`, yêu cầu vẫn chờ."""
    audit, engine = AuditGia(), _engine_gia(**{"HE-09": _td("HE-09", "L1")})
    engine.ke_can_tra["HE-02"] = ["HE-09"]
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        yc = _yc(k=1)
        kho_break_glass_gia.yeu_cau[yc.id] = yc
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="tech_support", hyperedge_ids=["HE-09"], con_han_phut=10))
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        kq = _duyet(client, demo, yc.id)
        assert kq.status_code == 409 and kq.json()["error"]["code"] == MA_GRANT_CON_HAN
        assert kho_break_glass_gia.yeu_cau[yc.id].trang_thai == TRANG_THAI_CHO_DUYET
        # Cấp chủ động chỉ phủ gốc (k = K_MAC_DINH = 0) thì không đụng HE-09: 201.
        assert _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"}).status_code == 201
    assert len(kho_break_glass_gia.grants) == 2 and [sk.event for sk in audit.su_kien[so_truoc:]] == [EVENT_BREAKGLASS_GRANT]


def test_http_grant_o_space_khac_khong_chan_xin_hay_cap_o_synth(monkeypatch, kho_break_glass_gia):
    """Grant khớp cặp trong **một space**: grant ở `khac` không nói gì về `synth`."""
    with _client(monkeypatch, _kho_gia(), AuditGia(), _engine_gia()) as client:
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="tech_support", hyperedge_ids=["HE-02"], con_han_phut=10, space="khac"))
        assert asyncio.run(kho_break_glass_gia.co_grant_con_han("ts01", "tech_support", "HE-02", "khac")) is True
        assert asyncio.run(kho_break_glass_gia.co_grant_con_han("ts01", "tech_support", "HE-02", "synth")) is False
        ts, demo = _token(client, "ts01"), _token(client, "demo01")
        yc = _xin(client, ts)
        assert _duyet(client, demo, yc["id"]).status_code == 200
        assert client.post(DUONG, json={"hyperedge_id": "HE-02", "ly_do": "xin"}, headers=_h(ts)).status_code == 409


def test_http_tu_choi_200_grant_null_audit_reject_chi_goc(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        kq = _tu_choi(client, demo, yc["id"], {"ly_do": "  không đúng ticket  "})
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert tuple(than) == ("yeu_cau", "grant") and than["grant"] is None
    y = than["yeu_cau"]
    assert tuple(y) == KHOA_YEU_CAU
    assert (y["trang_thai"], y["ly_do_tu_choi"], y["xu_ly_boi"]) == (TRANG_THAI_TU_CHOI, "không đúng ticket", "demo01")
    assert kho_break_glass_gia.grants == []
    moi = audit.su_kien[so_truoc:]
    assert [sk.event for sk in moi] == [EVENT_BREAKGLASS_REJECT] and moi[0].tier == TIER_MUTATION
    assert moi[0].hyperedge_ids == ("HE-02",) and (moi[0].act, moi[0].role) == ("demo01", "tech_support")
    ct = dict(moi[0].chi_tiet)
    assert (ct[CT_REQUEST_ID], ct[CT_TRANG_THAI], ct[CT_GRANT_ID], ct[CT_NGUOI_NHAN], ct[CT_VAI_NHAN]) == (yc["id"], TRANG_THAI_TU_CHOI, None, "ts01", "tech_support")
    assert "ticket" not in json.dumps(ct, ensure_ascii=False)
    # Sau từ chối, người xin xin lại được (index chỉ phủ hàng đang chờ).
    assert client.post(DUONG, json={"hyperedge_id": "HE-02", "ly_do": "xin lại"}, headers=_h(_token(client, "ts01"))).status_code == 201


@pytest.mark.parametrize(
    "than,ma",
    [
        ({"ly_do": "   "}, MA_LY_DO_RONG),
        ({"ly_do": "x" * (DAI_LY_DO_TOI_DA + 1)}, MA_LY_DO_QUA_DAI),
        ({}, MA_THAN_YEU_CAU_LA),
        ({"ly_do": "x", "k": 1}, MA_THAN_YEU_CAU_LA),
        ({"ly_do": 5}, MA_THAN_YEU_CAU_LA),
        ({"ly_do": "x\x00"}, MA_THAN_YEU_CAU_LA),
    ],
    ids=["rong", "dai", "thieu", "thua", "int", "nul"],
)
def test_http_tu_choi_than_sai_400_khong_cham_kho(monkeypatch, kho_break_glass_gia, than, ma):
    with _client(monkeypatch, _kho_gia(), AuditGia(), _engine_gia()) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        kho_break_glass_gia.no = RuntimeError("không được chạm kho")
        kq = _tu_choi(client, _token(client, "demo01"), yc["id"], than)
        kho_break_glass_gia.no = None
    assert kq.status_code == 400 and kq.json()["error"]["code"] == ma
    assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET


def test_http_cap_chu_dong_201_request_id_null_audit_grant(monkeypatch, kho_break_glass_gia):
    audit, engine = AuditGia(), _engine_gia()
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        kq = _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"})
    assert kq.status_code == 201, kq.text
    than = kq.json()
    assert tuple(than) == ("grant",)
    g = than["grant"]
    assert tuple(g) == KHOA_GRANT and g["request_id"] is None
    assert (g["act"], g["role"], g["space"], g["hyperedge_ids"], g["cap_boi"]) == ("ts01", "tech_support", "synth", ["HE-02"], "demo01")
    assert datetime.fromisoformat(g["expires_at"]) - datetime.fromisoformat(g["tao_luc"]) == timedelta(minutes=THOI_HAN_PHUT)
    # Mức của gốc hỏi dưới ngữ cảnh **người nhận**, vùng cũng vậy.
    assert engine.ids == [["HE-02"]] and engine.vung == [(["HE-02"], 0)]
    assert {c.real_account for c in engine.ngu_canh} == {"ts01"} and {c.role for c in engine.ngu_canh} == {"tech_support"}
    assert [dict_grant(x) for x in kho_break_glass_gia.grants] == [g] and kho_break_glass_gia.yeu_cau == {}
    moi = audit.su_kien[so_truoc:]
    assert [sk.event for sk in moi] == [EVENT_BREAKGLASS_GRANT] and moi[0].tier == TIER_MUTATION
    assert (moi[0].act, moi[0].role, moi[0].hyperedge_ids) == ("demo01", "tech_support", ("HE-02",))
    assert dict(moi[0].chi_tiet) == {
        CT_REQUEST_ID: None, CT_TRANG_THAI: None, CT_GRANT_ID: g["id"], CT_NGUOI_NHAN: "ts01",
        CT_VAI_NHAN: "tech_support", CT_K: 0, CT_THOI_HAN_PHUT: 60, CT_NHOM_DUYET: "Tech Support",
    }
    # Đường xin của 5.1 thấy grant này.
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        lai = client.post(DUONG, json={"hyperedge_id": "HE-02", "ly_do": "xin"}, headers=_h(_token(client, "ts01")))
    assert lai.status_code == 409 and lai.json()["error"]["code"] == MA_GRANT_CON_HAN


def test_http_cap_chu_dong_khong_nhom_duyet_500_khong_grant_khong_audit(monkeypatch, kho_break_glass_gia):
    audit, engine = AuditGia(), _engine_gia(**{"HE-02": _td("HE-02", "L1", nhom=None)})
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        kq = _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"})
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_NHOM_DUYET_KHONG_CO
    assert kho_break_glass_gia.grants == [] and audit.su_kien[so_truoc:] == [] and engine.vung == []


def test_http_cap_chu_dong_nguoi_nhan_khong_hop_le_400_mot_than(monkeypatch, kho_break_glass_gia):
    """Tài khoản lạ, khác space, vai lạ, chuỗi rỗng: một thân 400, không chạm cửa quyền, không grant."""
    audit, engine = AuditGia(), _engine_gia()
    kho_users = _kho_gia(them={"KHAC": replace(_dong("khac01"), khong_gian="khac")})
    with _client(monkeypatch, kho_users, audit, engine) as client:
        demo = _token(client, "demo01")
        so_truoc = len(audit.su_kien)
        bon = [
            _cap(client, demo, {"act": "ai_do", "role": "tech_support", "hyperedge_id": "HE-02"}),
            _cap(client, demo, {"act": "khac01", "role": "tech_support", "hyperedge_id": "HE-02"}),
            _cap(client, demo, {"act": "ts01", "role": "vai_la", "hyperedge_id": "HE-02"}),
            _cap(client, demo, {"act": "  ", "role": "tech_support", "hyperedge_id": "HE-02"}),
            _cap(client, demo, {"act": "ts01", "role": "", "hyperedge_id": "HE-02"}),
        ]
    assert [kq.status_code for kq in bon] == [400] * 5 and len({kq.content for kq in bon}) == 1
    assert bon[0].json()["error"]["code"] == MA_NGUOI_NHAN_KHONG_HOP_LE
    assert "ai_do" not in bon[0].text and "vai_la" not in bon[2].text
    assert engine.ids == [] and engine.vung == [] and kho_break_glass_gia.grants == [] and audit.su_kien[so_truoc:] == []


@pytest.mark.parametrize(
    "than",
    [
        {"act": "ts01", "role": "tech_support"},
        {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02", "k": 3},
        {"act": "ts01", "role": "tech_support", "hyperedge_id": "  "},
        {"act": "ts01", "role": "tech_support", "hyperedge_id": ["HE-02"]},
        {"act": ["ts01"], "role": "tech_support", "hyperedge_id": "HE-02"},
    ],
    ids=["thieu_id", "thua_k", "id_rong", "id_list", "act_list"],
)
def test_http_cap_chu_dong_than_sai_400_than_yeu_cau_la(monkeypatch, kho_break_glass_gia, than):
    engine = _engine_gia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        kq = _cap(client, _token(client, "demo01"), than)
    assert kq.status_code == 400 and kq.json()["error"]["code"] == MA_THAN_YEU_CAU_LA
    assert engine.ids == [] and kho_break_glass_gia.grants == []


def test_http_cap_chu_dong_goc_l2_400_vo_hinh_404_owner_sai_403_grant_con_han_409(monkeypatch, kho_break_glass_gia):
    audit, engine = AuditGia(), _engine_gia()
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        demo, dev = _token(client, "demo01"), _token(client, "dev01")
        so_truoc = len(audit.su_kien)
        l2 = _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-01"})
        assert l2.status_code == 400 and l2.json()["error"]["code"] == MA_HYPEREDGE_DA_THAY_DU
        vo_hinh = [_cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": i}) for i in ("HE-KHONG-CO", "HE-04")]
        assert [kq.status_code for kq in vo_hinh] == [404, 404] and vo_hinh[0].content == vo_hinh[1].content
        assert vo_hinh[0].json()["error"]["code"] == MA_HYPEREDGE_KHONG_XIN_DUOC
        # dev01 (DevOps) cấp HE-02 (Tech Support): 403; demo01 cấp cho chính mình: 403 (cùng luật cấm tự duyệt).
        owner_sai = _cap(client, dev, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"})
        tu_cap = _cap(client, demo, {"act": "demo01", "role": "tech_support", "hyperedge_id": "HE-02"})
        assert owner_sai.status_code == tu_cap.status_code == 403 and owner_sai.content == tu_cap.content
        assert owner_sai.json()["error"]["code"] == MA_KHONG_PHAI_OWNER
        # Engine giả không phân vai (HE-03 khai L1 cho mọi ngữ cảnh), nên ca này chỉ chấm cửa
        # owner: dev01 là DevOps, nhóm của `bi_mat_ha_tang`, cấp cho ts01 được -> 201.
        assert _cap(client, dev, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-03"}).status_code == 201
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="tech_support", hyperedge_ids=["HE-02"], con_han_phut=10))
        con_han = _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"})
        assert con_han.status_code == 409 and con_han.json()["error"]["code"] == MA_GRANT_CON_HAN
    assert len(kho_break_glass_gia.grants) == 2
    assert [sk.event for sk in audit.su_kien[so_truoc:]] == [EVENT_BREAKGLASS_GRANT]


def test_http_hang_cho_cua_demo01_thay_ts01_kem_vung_cap_khong_thay_devops(monkeypatch, kho_break_glass_gia):
    audit, engine = AuditGia(), _engine_gia()
    kho_users = _kho_gia(them={"LA01": replace(_dong("la01"), role="vai_la"), "MOCOI": replace(_dong("mocoi01"), group_name="Nhóm Không Ai")})
    with _client(monkeypatch, kho_users, audit, engine) as client:
        ts, dev, demo = _token(client, "ts01"), _token(client, "dev01"), _token(client, "demo01")
        a = _xin(client, ts, "HE-02")
        b = _xin(client, dev, "HE-03", "dev xin")
        so_truoc = len(audit.su_kien)
        engine.vung.clear()
        kq = _hang_cho(client, demo)
        assert kq.status_code == 200, kq.text
        assert tuple(kq.json()) == ("yeu_cau",)
        ds = kq.json()["yeu_cau"]
        assert [y["id"] for y in ds] == [a["id"]]
        assert tuple(ds[0]) == KHOA_YEU_CAU + ("vung_cap",) and ds[0]["vung_cap"] == ["HE-02"]
        assert engine.vung == [(["HE-02"], 0)] and engine.ngu_canh[-1].real_account == "ts01"
        # dev01 là DevOps: thấy yêu cầu HE-03 của chính mình trên hàng chờ (nhưng không duyệt được: 403).
        cua_dev = _hang_cho(client, dev).json()["yeu_cau"]
        assert [y["id"] for y in cua_dev] == [b["id"]] and cua_dev[0]["vung_cap"] == ["HE-03"]
        assert _duyet(client, dev, b["id"]).status_code == 403
        # Không nhóm nào khớp -> []; vai lạ -> 403 như mọi tuyến đóng.
        assert _hang_cho(client, _token(client, "mocoi01", "MOCOI")).json() == {"yeu_cau": []}
        la = _hang_cho(client, _token(client, "la01", "LA01"))
        assert la.status_code == 403 and la.json()["error"]["code"] == RoleUnknown.code
        # Hai yêu cầu của ts01, cũ nhất trước; yêu cầu đã duyệt rời hàng chờ.
        c = _yc(id="bg-00000000000c", hyperedge_id="HE-09", tao_luc="2026-01-01T00:00:00+00:00", cap_nhat="2026-01-01T00:00:00+00:00")
        kho_break_glass_gia.yeu_cau[c.id] = c
        assert [y["id"] for y in _hang_cho(client, demo).json()["yeu_cau"]] == [c.id, a["id"]]
        assert _duyet(client, demo, a["id"]).status_code == 200
        assert [y["id"] for y in _hang_cho(client, demo).json()["yeu_cau"]] == [c.id]
        # Gốc mà engine không thấy nữa (HE-09 không có trong engine giả): `vung_cap: []`, không lỗi.
        assert _hang_cho(client, demo).json()["yeu_cau"][0]["vung_cap"] == []
    assert not [sk for sk in audit.su_kien[so_truoc:] if sk.event not in (EVENT_BREAKGLASS_APPROVE, "auth_login")]


@pytest.mark.parametrize("sua", [{"role": "vai_da_bo"}, {"act": " ts01 "}], ids=["vai_la", "danh_tinh_hong"])
def test_http_hang_cu_hong_thi_vung_cap_rong_va_duyet_409(monkeypatch, kho_break_glass_gia, sua):
    """Hàng cũ mà ảnh chụp không dựng được ngữ cảnh (vai đã bỏ khỏi bảng, hay `DanhTinh` từ chối):
    hàng chờ vẫn trả cả danh sách, mục ấy `vung_cap: []`, không chạm engine; duyệt là 409 `VUNG_CAP_RONG`
    (không phải 403 vai lạ, mã ấy là của owner), từ chối vẫn được."""
    audit, engine = AuditGia(), _engine_gia()
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        ts = _token(client, "ts01")
        lanh = _xin(client, ts)  # một hàng lành đứng cạnh hàng hỏng
        yc = _yc(**sua, hyperedge_id="HE-02X")
        kho_break_glass_gia.yeu_cau[yc.id] = yc
        demo = _token(client, "demo01")
        engine.vung.clear()
        kq = _hang_cho(client, demo)
        assert kq.status_code == 200, kq.text
        theo_id = {y["id"]: y for y in kq.json()["yeu_cau"]}
        assert set(theo_id) == {lanh["id"], yc.id}
        assert theo_id[yc.id]["vung_cap"] == [] and theo_id[lanh["id"]]["vung_cap"] == ["HE-02"]
        assert engine.vung == [(["HE-02"], 0)], "hàng hỏng không tốn câu nào"
        so_truoc = len(audit.su_kien)
        d = _duyet(client, demo, yc.id)
        assert d.status_code == 409 and d.json()["error"]["code"] == MA_VUNG_CAP_RONG
        assert kho_break_glass_gia.yeu_cau[yc.id].trang_thai == TRANG_THAI_CHO_DUYET and kho_break_glass_gia.grants == []
        assert audit.su_kien[so_truoc:] == []
        assert _tu_choi(client, demo, yc.id).status_code == 200


def test_http_hang_cho_owner_khong_con_dong_users_thi_rong_khong_cham_engine(monkeypatch, kho_break_glass_gia):
    engine = _engine_gia()
    kho_users = _kho_gia()
    with _client(monkeypatch, kho_users, AuditGia(), engine) as client:
        _xin(client, _token(client, "ts01"))
        demo = _token(client, "demo01")
        del kho_users.theo_ten[TEN_GO["demo01"]]
        engine.vung.clear()
        engine.ids.clear()
        kq = _hang_cho(client, demo)
    assert kq.status_code == 200 and kq.json() == {"yeu_cau": []}
    assert engine.vung == [] and engine.ids == []


def test_http_hang_cho_cat_o_so_yeu_cau_toi_da(monkeypatch, kho_break_glass_gia):
    """Không phân trang (giới hạn đã khai ở ADR-020): 150 hàng chờ thì owner thấy đúng 100, cũ nhất trước."""
    engine = _engine_gia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        for i in range(150):
            yc = _yc(id=f"bg-{i:012x}", hyperedge_id=f"X-{i}", tao_luc=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00", cap_nhat="2026-01-01T00:00:00+00:00")
            kho_break_glass_gia.yeu_cau[yc.id] = yc
        ds = _hang_cho(client, _token(client, "demo01")).json()["yeu_cau"]
    assert len(ds) == SO_YEU_CAU_TOI_DA == 100
    assert [y["id"] for y in ds] == [f"bg-{i:012x}" for i in range(100)]
    assert len(engine.vung) == 100


def test_http_audit_hong_500_yeu_cau_van_cho_khong_grant(monkeypatch, kho_break_glass_gia):
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(), audit, _engine_gia()) as client:
        yc = _tao_yc_ts01(client, kho_break_glass_gia)
        demo = _token(client, "demo01")
        audit.no = RuntimeError("audit_log chết")
        ba = [
            _duyet(client, demo, yc["id"]),
            _tu_choi(client, demo, yc["id"]),
            _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"}),
        ]
        assert [kq.status_code for kq in ba] == [500] * 3
        assert {kq.json()["error"]["code"] for kq in ba} == {MA_AUDIT_GHI_HONG}
        assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET and kho_break_glass_gia.grants == []
        audit.no = None
        assert _duyet(client, demo, yc["id"]).status_code == 200


def test_http_kho_hong_503_ca_bon_tuyen_khong_llm(monkeypatch, kho_break_glass_gia):
    engine = EngineGia(loi=Neo4jUnavailable("rớt"))
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        yc = _yc()
        kho_break_glass_gia.yeu_cau[yc.id] = yc
        demo = _token(client, "demo01")
        neo = [
            _duyet(client, demo, yc.id),
            _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"}),
            _hang_cho(client, demo),
        ]
    for kq in neo:
        assert kq.status_code == 503 and kq.json()["error"]["code"] == MA_KHO_KHONG_SAN_SANG
    assert engine.cau_hoi == [] and kho_break_glass_gia.grants == []
    with _client(monkeypatch, _kho_gia(), AuditGia(), _engine_gia()) as client:
        demo = _token(client, "demo01")
        kho_break_glass_gia.no = asyncpg.exceptions.PostgresConnectionError("postgres rớt")
        pg = [
            _duyet(client, demo, "bg-1"),
            _tu_choi(client, demo, "bg-1"),
            _cap(client, demo, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"}),
            _hang_cho(client, demo),
        ]
        kho_break_glass_gia.no = None
    for kq in pg:
        assert kq.status_code == 503 and kq.json()["error"]["code"] == MA_KHO_KHONG_SAN_SANG
        assert "postgres" not in kq.text.lower()
    # Cửa quyền lệch: 500 mang mã, không grant.
    with _client(monkeypatch, _kho_gia(), AuditGia(), EngineGia(loi=TrichDanNgoaiQuyen("khóa hỏng"))) as client:
        yc = _yc()
        kho_break_glass_gia.yeu_cau[yc.id] = yc
        kq = _duyet(client, _token(client, "demo01"), yc.id)
    assert kq.status_code == 500 and kq.json()["error"]["code"] == MA_TRICH_DAN_NGOAI_QUYEN


def test_http_khong_token_401_vai_la_403_tren_bon_tuyen(monkeypatch, kho_break_glass_gia):
    engine = _engine_gia()
    kho_users = _kho_gia(them={"LA01": replace(_dong("la01"), role="vai_la")})
    with _client(monkeypatch, kho_users, AuditGia(), engine) as client:
        for kq in (
            client.get(HANG_CHO),
            client.post(f"{DUONG}/bg-1/duyet"),
            client.post(f"{DUONG}/bg-1/tu-choi", json={"ly_do": "x"}),
            client.post(GRANT, json={"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"}),
        ):
            assert kq.status_code == 401 and kq.json()["error"]["code"] == "TOKEN_KHONG_HOP_LE"
        token = _token(client, "la01", "LA01")
        for kq in (
            _hang_cho(client, token),
            _duyet(client, token, "bg-1"),
            _tu_choi(client, token, "bg-1"),
            _cap(client, token, {"act": "ts01", "role": "tech_support", "hyperedge_id": "HE-02"}),
        ):
            assert kq.status_code == 403 and kq.json()["error"]["code"] == RoleUnknown.code
    assert engine.ids == [] and engine.vung == [] and kho_break_glass_gia.grants == []
