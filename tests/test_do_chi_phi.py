"""Script `api/do_chi_phi.py` sau story 2.3: tham số và rẽ nhánh vào pipeline.

Không Postgres, không kho, không LLM: mọi cửa ra ngoài (`AuditPostgres.mo`,
`ham_tu_moi_truong`, `EngineACL`, ba hàm pipeline) thay bằng bản giả qua
monkeypatch, để chỉ đo phần script tự làm - đọc tham số và gọi đúng hàm với
đúng đối số.
"""

import asyncio
from pathlib import Path

import pytest

import api.do_chi_phi as mod
from adapters.ingest import TRANG_THAI_DA_XOA, KetQuaNap, TrangThaiTaiLieu
from api.audit_postgres import TongChiPhi


def test_tham_so_thieu_duong_dan_la_loi():
    with pytest.raises(SystemExit):
        mod._tham_so([])


def test_tham_so_xoa_space_khong_di_cung_duong_dan():
    with pytest.raises(SystemExit):
        mod._tham_so(["--xoa-space", "eval/data"])


def test_tham_so_mac_dinh():
    ts = mod._tham_so(["eval/data", "--ep-ghi-de"])
    assert ts.space == "synth" and ts.ep_ghi_de is True and ts.xoa_space is False
    assert ts.duong_dan == [Path("eval/data")]


class _AuditGia:
    def __init__(self):
        self.da_dong = False
        self.cua_so: list[tuple] = []

    async def khoi_tao(self):
        pass

    async def tong_chi_phi(self, space, *, tu=None, den=None):
        self.cua_so.append((tu, den))
        return TongChiPhi(so_lan=0, token_vao=0, token_ra=0, chi_phi_usd=0.0, theo_model=())

    async def dong(self):
        self.da_dong = True


class _EngineGia:
    def __init__(self, **kw):
        self.kw = kw
        self.da_dong = False

    async def dong(self):
        self.da_dong = True


def _gia_lap(monkeypatch, tmp_path):
    goi: list[tuple] = []
    audit = _AuditGia()

    async def mo(cau_hinh=None):
        return audit

    class _Ham:
        llm = object()
        embedding = object()
        llm_max_token = 8

    class _Policy:
        policy_version = "pv"

    monkeypatch.setattr(mod.AuditPostgres, "mo", mo)
    monkeypatch.setattr(mod, "ham_tu_moi_truong", lambda audit: _Ham())
    monkeypatch.setattr(mod, "EngineACL", _EngineGia)
    monkeypatch.setattr(mod, "cau_hinh_kho_tu_moi_truong", lambda: {})
    monkeypatch.setattr(mod, "load_policy", lambda p: _Policy())

    async def nap_thu_muc(engine, thu_muc, *, space, policy_version, audit, ket_qua=None, ep_ghi_de=False):
        goi.append(("thu_muc", Path(thu_muc), space, ep_ghi_de))
        ket_qua.tai_lieu.append(
            TrangThaiTaiLieu(
                doc_key="a.md",
                trang_thai="da_nap",
                bat_dau="2026-09-02T00:00:00+00:00",
                ket_thuc="2026-09-02T00:01:00+00:00",
            )
        )
        return ket_qua

    async def nap_cac_file(engine, cac_file, *, space, policy_version, audit, ket_qua=None, ep_ghi_de=False):
        goi.append(("file", [Path(f) for f in cac_file], space, ep_ghi_de))
        return ket_qua

    async def xoa_space(engine, *, space, policy_version, audit):
        goi.append(("xoa", space))

    monkeypatch.setattr(mod, "nap_thu_muc", nap_thu_muc)
    monkeypatch.setattr(mod, "nap_cac_file", nap_cac_file)
    monkeypatch.setattr(mod, "xoa_space", xoa_space)
    return goi, audit


def test_mot_thu_muc_thi_nap_thu_muc(monkeypatch, tmp_path):
    goi, audit = _gia_lap(monkeypatch, tmp_path)
    (tmp_path / "corpus").mkdir()
    mod.main([str(tmp_path / "corpus"), "--space", "synth", "--ep-ghi-de"])
    assert goi == [("thu_muc", tmp_path / "corpus", "synth", True)]
    assert audit.da_dong
    # Bảng từng tài liệu hỏi đúng đoạn [bắt đầu, kết thúc) - patch 25: dòng
    # theo model và dòng tổng cùng một cửa sổ, không còn phép trừ ở cấp tổng.
    assert ("2026-09-02T00:00:00+00:00", "2026-09-02T00:01:00+00:00") in audit.cua_so


def test_cac_file_thi_nap_cac_file_giu_thu_tu(monkeypatch, tmp_path):
    goi, _ = _gia_lap(monkeypatch, tmp_path)
    b = tmp_path / "b.md"
    a = tmp_path / "a.md"
    b.write_text("x")
    a.write_text("y")
    mod.main([str(b), str(a)])
    assert goi == [("file", [b, a], "synth", False)]


def test_mot_file_khong_phai_thu_muc_thi_nap_cac_file(monkeypatch, tmp_path):
    """Đối chứng cho phép rẽ `is_dir()`: đảo điều kiện là test này đỏ."""
    goi, _ = _gia_lap(monkeypatch, tmp_path)
    a = tmp_path / "a.md"
    a.write_text("y")
    mod.main([str(a)])
    assert goi[0][0] == "file"


def test_xoa_space_goi_dung_ham(monkeypatch, tmp_path, capsys):
    goi, _ = _gia_lap(monkeypatch, tmp_path)
    mod.main(["--xoa-space", "--space", "test_x"])
    assert goi == [("xoa", "test_x")]
    assert "đã xóa sạch space" in capsys.readouterr().out


def test_in_ket_qua_in_xoa_theo_hang(capsys):
    kq = KetQuaNap(tai_lieu=[TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_DA_XOA, so_hyperedge=2)])
    mod.in_ket_qua(kq)
    assert "XÓA a.md" in capsys.readouterr().out
