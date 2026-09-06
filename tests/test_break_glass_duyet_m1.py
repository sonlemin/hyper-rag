"""Lớp 4 của story 5.2: HTTP với engine M1 thật qua ba tài khoản seed (AC-1, AC-2, vùng rỗng khi hoán bảng).

Tách khỏi `tests/test_break_glass_duyet.py` để cả hai dưới 1000 dòng; helper
HTTP, engine giả và kho giả nhập từ file ấy, cùng cách `tests/test_break_glass.py`
nhập từ `tests/test_xac_thuc.py`.
"""

import asyncio

import pytest

from api.break_glass import (
    MA_GRANT_CON_HAN,
    MA_HYPEREDGE_DA_THAY_DU,
    MA_HYPEREDGE_KHONG_XIN_DUOC,
    MA_KHONG_PHAI_OWNER,
    MA_VUNG_CAP_RONG,
    vung_cap_cua,
)
from core.audit import (
    EVENT_BREAKGLASS_APPROVE,
    EVENT_BREAKGLASS_REQUEST,
    EVENT_EMBEDDING_COST,
    EVENT_LLM_COST,
)
from core.break_glass import TRANG_THAI_CHO_DUYET
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES
from tests.nap_kho import ten_hyperedge
from tests.ngu_canh import vai
from tests.test_break_glass_duyet import (
    DUONG,
    HE02,
    HE03,
    _cap,
    _client,
    _duyet,
    _engine,
    _h,
    _hang_cho,
    _kho_gia,
    _su_kien,
    _token,
    _tu_choi,
    _xin,
)
from tests.test_xac_thuc import AuditGia

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

def test_http_ac1_ts01_xin_he02_demo01_duyet_tren_engine_m1_that(monkeypatch, workspace_dir, khong_gian, policy, bang, kho_break_glass_gia):
    """AC-1: grant bind (ts01, tech_support), `hyperedge_ids == [HE-02]` với k=0 lẫn k=1; xin lại ra 409 `GRANT_CON_HAN`."""
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        ts, demo = _token(client, "ts01"), _token(client, "demo01")
        yc = _xin(client, ts, HE02)
        assert yc["nhom_duyet"] == oracle.nhom_ky_vong("bao_cao_su_co") == "Tech Support"
        hc = _hang_cho(client, demo).json()["yeu_cau"]
        assert [y["id"] for y in hc] == [yc["id"]] and hc[0]["vung_cap"] == [HE02]
        driver.xoa_nhat_ky()
        kq = _duyet(client, demo, yc["id"])
        assert kq.status_code == 200, kq.text
        assert [lg.loai for lg in driver.cac_cau_doc()] == ["doc:trich_dan_cua"], "k=0: không câu lân cận nào"
        g = kq.json()["grant"]
        assert (g["act"], g["role"], g["hyperedge_ids"], g["cap_boi"], g["request_id"]) == ("ts01", "tech_support", [HE02], "demo01", yc["id"])
        # k=1 gọi thẳng `vung_lan_can` dưới ngữ cảnh người xin: HE-01 chung App01 rớt ở (b) và (c).
        assert asyncio.run(vung_cap_cua(engine, vai(policy, "tech_support", khong_gian), HE02, 1)) == (HE02,)
        lai = client.post(DUONG, json={"hyperedge_id": HE02, "ly_do": "xin lại"}, headers=_h(ts))
        assert lai.status_code == 409 and lai.json()["error"]["code"] == MA_GRANT_CON_HAN
    assert llm.so_lan == 0
    assert engine.so_audit.cac_su_kien(EVENT_LLM_COST) == [] and engine.so_audit.cac_su_kien(EVENT_EMBEDDING_COST) == []
    assert [sk.event for sk in _su_kien(audit)] == [EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_APPROVE]
    assert _su_kien(audit)[1].act == "demo01" and _su_kien(audit)[1].hyperedge_ids == (HE02,)


def test_http_ac2_dev01_va_ts01_deu_403_tren_engine_that(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    """AC-2: dev01 duyệt/từ chối yêu cầu Tech Support, ts01 tự duyệt: ba 403, bảng và audit không đổi; dev01 xin HE-03 không ai duyệt được."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        ts, dev, demo = _token(client, "ts01"), _token(client, "dev01"), _token(client, "demo01")
        yc = _xin(client, ts, HE02)
        yc_dev = _xin(client, dev, HE03, "dev xin")
        so_truoc = len(audit.su_kien)
        ba = [_duyet(client, dev, yc["id"]), _tu_choi(client, dev, yc["id"]), _duyet(client, ts, yc["id"])]
        assert [kq.status_code for kq in ba] == [403] * 3 and len({kq.content for kq in ba}) == 1
        assert ba[0].json()["error"]["code"] == MA_KHONG_PHAI_OWNER
        # Yêu cầu HE-03 của dev01: nhóm DevOps, chỉ dev01 là DevOps, mà tự duyệt bị cấm.
        assert _duyet(client, dev, yc_dev["id"]).status_code == 403
        assert _duyet(client, demo, yc_dev["id"]).status_code == 403
    assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == kho_break_glass_gia.yeu_cau[yc_dev["id"]].trang_thai == TRANG_THAI_CHO_DUYET
    assert kho_break_glass_gia.grants == [] and audit.su_kien[so_truoc:] == []


def test_http_hoan_policy_lam_vung_rong_tren_engine_that(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    """Hàng "Vùng rỗng lúc duyệt": hoán `tat-phan-quyen` (HE-02 thành L2 với vai xin) -> 409, về `day-du` -> 200."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        ts, dev, demo = _token(client, "ts01"), _token(client, "dev01"), _token(client, "demo01")
        yc = _xin(client, ts, HE02)
        assert client.post("/admin/policy", json={"id": "tat-phan-quyen"}, headers=_h(dev)).status_code == 200
        kq = _duyet(client, demo, yc["id"])
        assert kq.status_code == 409 and kq.json()["error"]["code"] == MA_VUNG_CAP_RONG
        assert kho_break_glass_gia.yeu_cau[yc["id"]].trang_thai == TRANG_THAI_CHO_DUYET
        assert _hang_cho(client, demo).json()["yeu_cau"][0]["vung_cap"] == []
        assert client.post("/admin/policy", json={"id": "day-du"}, headers=_h(dev)).status_code == 200
        assert _duyet(client, demo, yc["id"]).status_code == 200


def test_http_cap_chu_dong_tren_engine_that_theo_oracle(monkeypatch, workspace_dir, khong_gian, policy, bang, kho_break_glass_gia):
    """Với mỗi gốc: người nhận thấy L1 và owner đúng nhóm -> 201; L2 -> 400; vô hình -> 404; owner sai -> 403."""
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        demo, dev = _token(client, "demo01"), _token(client, "dev01")
        for he in HYPEREDGES:
            id_he = ten_hyperedge(he)
            muc = oracle.muc_ky_vong(bang, "tech_support", he["content_type"])
            nhom = oracle.nhom_ky_vong(he["content_type"])
            for owner, nhom_owner in ((demo, "Tech Support"), (dev, "DevOps")):
                kq = _cap(client, owner, {"act": "ts01", "role": "tech_support", "hyperedge_id": id_he})
                if he["id"] not in oracle.hyperedge_thay_duoc(bang, "tech_support", HYPEREDGES):
                    assert kq.status_code == 404 and kq.json()["error"]["code"] == MA_HYPEREDGE_KHONG_XIN_DUOC, id_he
                elif muc == "L2":
                    assert kq.status_code == 400 and kq.json()["error"]["code"] == MA_HYPEREDGE_DA_THAY_DU, id_he
                elif nhom != nhom_owner:
                    assert kq.status_code == 403 and kq.json()["error"]["code"] == MA_KHONG_PHAI_OWNER, id_he
                else:
                    assert kq.status_code == 201, (id_he, kq.text)
                    assert kq.json()["grant"]["hyperedge_ids"] == [id_he]
    assert [g.hyperedge_ids for g in kho_break_glass_gia.grants] == [(HE02,)]
    assert llm.so_lan == 0
