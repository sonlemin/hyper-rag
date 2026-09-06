"""Audit port trong `core/`: hình dạng sự kiện và luật hai tầng (story 2.2, AD-16).

Đặc tả viết trước cơ chế (FR-27). Không mạng, không kho: port là sổ bộ nhớ.
"""

import asyncio
import logging

import pytest

from core.audit import (
    EVENT_EMBEDDING_COST,
    EVENT_LLM_COST,
    EVENTS,
    TIER_MUTATION,
    TIER_OBSERVATION,
    TIERS,
    SuKienAudit,
    ghi_bien_doi,
    ghi_quan_sat,
    thoi_diem_utc,
)
from tests.gia_lap_llm import SoAuditBoNho


def su_kien(**doi) -> SuKienAudit:
    goc = dict(
        tier=TIER_OBSERVATION,
        event=EVENT_LLM_COST,
        space="synth",
        policy_version="v1",
        thoi_diem=thoi_diem_utc(),
        act="dev01",
        role="devops",
        hyperedge_ids=(),
        chi_tiet={"token_vao": 1},
    )
    goc.update(doi)
    return SuKienAudit(**goc)


# --- Danh mục và hình dạng ---------------------------------------------------


def test_danh_muc_su_kien_va_tang_la_hang_trong_core():
    """Danh mục là hằng trong core/, và ca này là **danh sách đóng**.

    2.2 hai sự kiện chi phí, 2.3 ba sự kiện ingest, 2.4 `extract_doc`, 3.2
    `policy_swap`, 3.3 `query`, 3.5 `refusal`, 3.6 bốn sự kiện để đủ hai tầng:
    `filter`, `auth_login`, `startup`, `permission_mismatch`. Mười ba, và thêm
    một là phải sửa dòng này kèm lý do (mục Ask First của spec 3.6). Story 5.1
    thêm hai, cả hai tầng mutation và khai trong Always của spec 5.1:
    `breakglass_request`, `breakglass_cancel` - một yêu cầu xin đọc phần bị che
    không có dấu vết là đúng thứ FR-20 sinh ra để thay. Mười lăm.
    """
    from core.audit import (
        EVENT_AUTH_LOGIN,
        EVENT_BREAKGLASS_CANCEL,
        EVENT_BREAKGLASS_REQUEST,
        EVENT_DELETE_DOC,
        EVENT_DELETE_SPACE,
        EVENT_EXTRACT_DOC,
        EVENT_FILTER,
        EVENT_INGEST_DOC,
        EVENT_PERMISSION_MISMATCH,
        EVENT_POLICY_SWAP,
        EVENT_QUERY,
        EVENT_REFUSAL,
        EVENT_STARTUP,
    )

    assert EVENTS == {
        EVENT_LLM_COST,
        EVENT_EMBEDDING_COST,
        EVENT_INGEST_DOC,
        EVENT_DELETE_DOC,
        EVENT_DELETE_SPACE,
        EVENT_EXTRACT_DOC,
        EVENT_POLICY_SWAP,
        EVENT_QUERY,
        EVENT_REFUSAL,
        EVENT_FILTER,
        EVENT_AUTH_LOGIN,
        EVENT_STARTUP,
        EVENT_PERMISSION_MISMATCH,
        EVENT_BREAKGLASS_REQUEST,
        EVENT_BREAKGLASS_CANCEL,
    }
    assert (EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_CANCEL) == ("breakglass_request", "breakglass_cancel")
    assert (EVENT_FILTER, EVENT_AUTH_LOGIN, EVENT_STARTUP, EVENT_PERMISSION_MISMATCH) == (
        "filter", "auth_login", "startup", "permission_mismatch"
    )
    assert (EVENT_INGEST_DOC, EVENT_DELETE_DOC, EVENT_DELETE_SPACE) == ("ingest_doc", "delete_doc", "delete_space")
    assert EVENT_EXTRACT_DOC == "extract_doc"
    assert EVENT_POLICY_SWAP == "policy_swap"
    assert EVENT_QUERY == "query"
    assert TIERS == {TIER_MUTATION, TIER_OBSERVATION}


def test_thoi_diem_utc_la_iso_8601_co_mui_gio():
    from datetime import datetime, timezone

    t = datetime.fromisoformat(thoi_diem_utc())
    assert t.tzinfo is not None and t.utcoffset() == timezone.utc.utcoffset(None)


def test_su_kien_hop_le_bat_bien_va_chi_tiet_dong_bang():
    sk = su_kien()
    with pytest.raises(Exception):
        sk.tier = TIER_MUTATION  # type: ignore[misc]
    with pytest.raises(TypeError):
        sk.chi_tiet["token_vao"] = 2  # type: ignore[index]
    assert sk.chi_tiet["token_vao"] == 1


@pytest.mark.parametrize(
    "doi, lop_loi",
    [
        ({"tier": "audit"}, ValueError),
        ({"event": "su_kien_la"}, ValueError),
        ({"thoi_diem": "2026-09-02 10:00"}, ValueError),
        ({"thoi_diem": "2026-09-02T10:00:00"}, ValueError),  # thiếu múi giờ
        ({"thoi_diem": "2026-09-02T10:00:00+07:00"}, ValueError),  # không phải UTC
        ({"thoi_diem": 1725270000}, TypeError),
        ({"hyperedge_ids": ["HE-01"]}, TypeError),
        ({"chi_tiet": [("token_vao", 1)]}, TypeError),
        ({"space": ""}, ValueError),
        ({"policy_version": ""}, ValueError),
    ],
    ids=[
        "tier_la",
        "event_ngoai_danh_muc",
        "thoi_diem_khong_iso",
        "thoi_diem_thieu_mui_gio",
        "thoi_diem_khong_utc",
        "thoi_diem_sai_kieu",
        "hyperedge_ids_khong_tuple",
        "chi_tiet_khong_map",
        "space_rong",
        "policy_version_rong",
    ],
)
def test_su_kien_hong_bi_tu_choi_luc_dung(doi, lop_loi):
    with pytest.raises(lop_loi):
        su_kien(**doi)


def test_su_kien_he_thong_khong_co_act_va_role():
    """Ngữ cảnh ingest không có tài khoản: hai trường là None, không phải chuỗi rỗng."""
    sk = su_kien(act=None, role=None)
    assert sk.act is None and sk.role is None


# --- Hai tầng ------------------------------------------------------------------


def test_mutation_ghi_dong_bo_va_loi_port_doi_len():
    so = SoAuditBoNho(loi=RuntimeError("postgres chết"))
    with pytest.raises(RuntimeError):
        asyncio.run(ghi_bien_doi(so, su_kien(tier=TIER_MUTATION)))

    so_tot = SoAuditBoNho()
    asyncio.run(ghi_bien_doi(so_tot, su_kien(tier=TIER_MUTATION)))
    assert len(so_tot.su_kien) == 1


def test_observation_best_effort_port_hong_thi_warning(caplog):
    so = SoAuditBoNho(loi=RuntimeError("postgres chết"))
    with caplog.at_level(logging.WARNING, logger="core.audit"):
        asyncio.run(ghi_quan_sat(so, su_kien(tier=TIER_OBSERVATION)))
    canh_bao = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(canh_bao) == 1
    assert EVENT_LLM_COST in canh_bao[0].getMessage()
    assert "postgres chết" in canh_bao[0].getMessage()


def test_observation_thanh_cong_khong_warning(caplog):
    so = SoAuditBoNho()
    with caplog.at_level(logging.WARNING, logger="core.audit"):
        asyncio.run(ghi_quan_sat(so, su_kien(tier=TIER_OBSERVATION)))
    assert so.cac_su_kien(EVENT_LLM_COST)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_observation_khong_nuot_huy_task():
    """`CancelledError` là BaseException: tầng quan sát không được giấu nó."""
    so = SoAuditBoNho(loi=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ghi_quan_sat(so, su_kien(tier=TIER_OBSERVATION)))


def test_moi_tang_tu_choi_su_kien_khai_sai_tang():
    """`tier` khai tại nơi gọi phải khớp hàm nơi gọi dùng, không có chuyển đổi ngầm."""
    so = SoAuditBoNho()
    with pytest.raises(ValueError):
        asyncio.run(ghi_bien_doi(so, su_kien(tier=TIER_OBSERVATION)))
    with pytest.raises(ValueError):
        asyncio.run(ghi_quan_sat(so, su_kien(tier=TIER_MUTATION)))
    assert so.su_kien == []


# --- Vòng review: thời hạn, kiểu của từng trường, kiem_thoi_diem public ------


def test_observation_qua_han_la_warning_va_di_tiep(caplog):
    """Postgres treo không được giữ lời gọi LLM treo theo: quá hạn là WARNING."""

    class PortTreo:
        def __init__(self):
            self.bi_huy = False

        async def ghi(self, su_kien):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.bi_huy = True
                raise

    port = PortTreo()

    async def chay():
        bat_dau = asyncio.get_running_loop().time()
        with caplog.at_level(logging.WARNING, logger="core.audit"):
            await ghi_quan_sat(port, su_kien(), thoi_han=0.05)
        return asyncio.get_running_loop().time() - bat_dau

    mat = asyncio.run(chay())
    assert mat < 2, "ghi_quan_sat chờ port treo thay vì cắt theo thời hạn"
    assert port.bi_huy, "lần ghi quá hạn phải bị hủy, không để chạy nền vô chủ"
    canh_bao = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(canh_bao) == 1 and "quá hạn" in canh_bao[0] and EVENT_LLM_COST in canh_bao[0]


def test_thoi_han_mac_dinh_la_vai_giay():
    from core.audit import THOI_HAN_QUAN_SAT

    assert 0 < THOI_HAN_QUAN_SAT <= 10


@pytest.mark.parametrize(
    "doi",
    [
        {"hyperedge_ids": ("HE-01", 2)},
        {"hyperedge_ids": (None,)},
        {"act": 7},
        {"role": ["devops"]},
    ],
    ids=["hyperedge_id_khong_chuoi", "hyperedge_id_none", "act_khong_chuoi", "role_khong_chuoi"],
)
def test_kieu_tung_truong_bi_kiem_luc_dung(doi):
    with pytest.raises(TypeError):
        su_kien(**doi)


def test_kiem_thoi_diem_public_tra_datetime_utc():
    from datetime import timezone

    from core.audit import kiem_thoi_diem

    t = kiem_thoi_diem("2026-09-02T10:00:00+00:00")
    assert t.utcoffset() == timezone.utc.utcoffset(None)
    with pytest.raises(ValueError):
        kiem_thoi_diem("2026-09-02T10:00:00")
    with pytest.raises(TypeError):
        kiem_thoi_diem(None)  # type: ignore[arg-type]
