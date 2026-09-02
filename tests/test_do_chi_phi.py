"""Script `api/do_chi_phi.py` sau story 2.7: tham số, rẽ nhánh, và `--xuat-json`.

Không Postgres, không kho, không LLM: mọi cửa ra ngoài (`AuditPostgres.mo`,
`dung_engine_tu_moi_truong`, `chay_lan_nap`, `xoa_space`) thay bằng bản giả qua
monkeypatch, để chỉ đo phần script tự làm - đọc tham số, quét đúng đường dẫn,
gọi đúng lõi đợt, in đúng bảng, và ghi file số đo đúng lúc.
"""

import json
from pathlib import Path

import pytest

import api.do_chi_phi as mod
from adapters.ingest import TRANG_THAI_DA_NAP, TRANG_THAI_DA_XOA, KetQuaNap, TrangThaiTaiLieu
from api.audit_postgres import DongChiPhi, TongChiPhi
from api.dot_nap import (
    TRANG_THAI_DOT_LOI,
    TRANG_THAI_DOT_XONG,
    ChiPhiTaiLieu,
    LanNap,
)

TONG = TongChiPhi(
    so_lan=3,
    token_vao=1000,
    token_ra=300,
    chi_phi_usd=0.0012,
    theo_model=(
        DongChiPhi("deepseek-v4-flash", "deepseek", 2, 1000, 300, 0.0012),
        DongChiPhi("text-embedding-3-small", "openai", 1, 800, 0, 0.000016),
    ),
)


def test_tham_so_thieu_duong_dan_la_loi():
    with pytest.raises(SystemExit):
        mod._tham_so([])


def test_tham_so_xoa_space_khong_di_cung_duong_dan():
    with pytest.raises(SystemExit):
        mod._tham_so(["--xoa-space", "eval/data"])


def test_tham_so_xuat_json_khong_di_cung_xoa_space():
    """Xóa space không phải một đợt nạp, nên nó không có số đo nào để xuất."""
    with pytest.raises(SystemExit):
        mod._tham_so(["--xoa-space", "--xuat-json", "x.json"])


def test_tham_so_mac_dinh():
    ts = mod._tham_so(["eval/data", "--ep-ghi-de"])
    assert ts.space == "synth" and ts.ep_ghi_de is True and ts.xoa_space is False
    assert ts.duong_dan == [Path("eval/data")]
    assert ts.xuat_json is None


class _AuditGia:
    def __init__(self):
        self.da_dong = False
        self.cua_so: list[tuple] = []

    async def khoi_tao(self):
        pass

    async def tong_chi_phi(self, space, *, tu=None, den=None):
        self.cua_so.append((space, tu, den))
        return TONG

    async def dong(self):
        self.da_dong = True


class _EngineGia:
    def __init__(self):
        self.da_dong = False

    async def dong(self):
        self.da_dong = True


def _gia_lap(monkeypatch, *, lan: LanNap | None = None):
    """Thay mọi cửa ra ngoài; trả (nhật ký lời gọi, audit giả, engine giả)."""
    goi: list[tuple] = []
    audit = _AuditGia()
    engine = _EngineGia()

    async def mo(cau_hinh=None):
        return audit

    class _Policy:
        policy_version = "pv"

    monkeypatch.setattr(mod.AuditPostgres, "mo", mo)
    monkeypatch.setattr(mod, "load_policy", lambda p: _Policy())
    monkeypatch.setattr(mod, "dung_engine_tu_moi_truong", lambda a: engine)

    mac_dinh = LanNap(space="synth")
    mac_dinh.trang_thai = TRANG_THAI_DOT_XONG
    mac_dinh.bat_dau, mac_dinh.ket_thuc = "2026-09-02T10:00:00+00:00", "2026-09-02T10:05:00+00:00"
    mac_dinh.ket_qua.tai_lieu.append(
        TrangThaiTaiLieu(
            doc_key="a.md",
            trang_thai=TRANG_THAI_DA_NAP,
            so_hyperedge=4,
            bat_dau="2026-09-02T10:00:00+00:00",
            ket_thuc="2026-09-02T10:01:00+00:00",
        )
    )
    mac_dinh.chi_phi = TONG
    mac_dinh.chi_phi_tai_lieu = [
        ChiPhiTaiLieu("a.md", "2026-09-02T10:00:00+00:00", "2026-09-02T10:01:00+00:00", TONG)
    ]
    ket = mac_dinh if lan is None else lan

    async def chay_lan_nap(quet, *, space, policy_version, audit, lan=None, ep_ghi_de=False, tao_engine=None):
        goi.append(("nap", tuple(t.doc_key for t in quet.chap_nhan), space, ep_ghi_de))
        return ket

    async def xoa_space(e, *, space, policy_version, audit):
        goi.append(("xoa", space))

    monkeypatch.setattr(mod, "chay_lan_nap", chay_lan_nap)
    monkeypatch.setattr(mod, "xoa_space", xoa_space)
    return goi, audit, engine


def _corpus(tmp_path: Path, *ten: str) -> Path:
    thu_muc = tmp_path / "corpus"
    thu_muc.mkdir(exist_ok=True)
    for t in ten:
        (thu_muc / t).write_text("---\nscope: noi_bo\ncontent_type: runbook\n---\nthan", encoding="utf-8")
    return thu_muc


def test_mot_thu_muc_thi_quet_thu_muc(monkeypatch, tmp_path):
    goi, audit, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "b.md", "a.md")
    mod.main([str(thu_muc), "--space", "synth", "--ep-ghi-de"])
    # Quét thư mục sắp theo tên, đúng luật của `core.ingest_scan.quet_thu_muc`.
    assert goi == [("nap", ("a.md", "b.md"), "synth", True)]
    assert audit.da_dong


def test_cac_file_thi_quet_theo_thu_tu_truyen_vao(monkeypatch, tmp_path):
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", "b.md")
    mod.main([str(thu_muc / "b.md"), str(thu_muc / "a.md")])
    assert goi == [("nap", ("b.md", "a.md"), "synth", False)]


def test_mot_file_khong_phai_thu_muc_thi_quet_cac_file(monkeypatch, tmp_path):
    """Đối chứng cho phép rẽ `is_dir()`: đảo điều kiện là test này đỏ."""
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md")
    mod.main([str(thu_muc / "a.md")])
    assert goi == [("nap", ("a.md",), "synth", False)]


def test_xoa_space_goi_dung_ham_va_dong_engine(monkeypatch, tmp_path, capsys):
    goi, audit, engine = _gia_lap(monkeypatch)
    mod.main(["--xoa-space", "--space", "test_x"])
    assert goi == [("xoa", "test_x")]
    ra = capsys.readouterr().out
    assert "đã xóa sạch space" in ra
    # Đầu ra console không đổi so với bản trước story 2.7: ở đó bảng "Cả đợt"
    # nằm trong `finally` nên nhánh xóa cũng in nó.
    assert "Cả đợt (thoi_diem >= " in ra
    assert engine.da_dong and audit.da_dong


def test_in_bang_theo_tai_lieu_va_bang_ca_dot(monkeypatch, tmp_path, capsys):
    _gia_lap(monkeypatch)
    mod.main([str(_corpus(tmp_path, "a.md") / "a.md")])
    ra = capsys.readouterr().out
    assert "NẠP a.md" in ra
    assert "Tài liệu a.md (2026-09-02T10:00:00+00:00 -> 2026-09-02T10:01:00+00:00):" in ra
    assert "Cả đợt (thoi_diem >= 2026-09-02T10:00:00+00:00):" in ra
    assert "deepseek-v4-flash" in ra and "text-embedding-3-small" in ra


def test_ngoai_le_giua_dot_van_in_so_roi_moi_doi_len(monkeypatch, tmp_path, capsys):
    lan = LanNap(space="synth")
    lan.trang_thai, lan.ma_loi = TRANG_THAI_DOT_LOI, "STORE_KEY_MISMATCH"
    lan.bat_dau = "2026-09-02T10:00:00+00:00"
    lan.chi_phi = TONG
    lan.ngoai_le = RuntimeError("khóa lệch ở vân tay 1a2b")
    _gia_lap(monkeypatch, lan=lan)
    with pytest.raises(RuntimeError):
        mod.main([str(_corpus(tmp_path, "a.md") / "a.md")])
    assert "Cả đợt" in capsys.readouterr().out


def test_xuat_json_ghi_file_co_lenh_va_khoa_bat_buoc(monkeypatch, tmp_path, capsys):
    _gia_lap(monkeypatch)
    dich = tmp_path / "so_do" / "nap-that.json"
    a = _corpus(tmp_path, "a.md") / "a.md"
    mod.main([str(a), "--xuat-json", str(dich)])

    so_do = json.loads(dich.read_text(encoding="utf-8"))
    assert so_do["version"] == 1 and so_do["space"] == "synth" and so_do["so_tai_lieu"] == 1
    assert so_do["lenh"].startswith(mod.TIEN_TO_LENH) and "--xuat-json" in so_do["lenh"]
    assert {d["model"]: d["loai"] for d in so_do["theo_model"]} == {
        "deepseek-v4-flash": "llm",
        "text-embedding-3-small": "embedding",
    }
    assert f"ghi số đo đợt vào {dich}" in capsys.readouterr().out


def test_xuat_json_khong_ghi_khi_dot_dung_giua_chung(monkeypatch, tmp_path, capsys):
    """Số của một đợt dở không được ghi đè số đo cũ mà chương 4 đang đứng trên."""
    lan = LanNap(space="synth")
    lan.trang_thai, lan.ma_loi = TRANG_THAI_DOT_LOI, "STORE_KEY_MISMATCH"
    lan.bat_dau, lan.chi_phi = "2026-09-02T10:00:00+00:00", TONG
    _gia_lap(monkeypatch, lan=lan)
    dich = tmp_path / "nap-that.json"
    dich.write_text('{"version": 1, "cu": true}', encoding="utf-8")

    mod.main([str(_corpus(tmp_path, "a.md") / "a.md"), "--xuat-json", str(dich)])
    assert json.loads(dich.read_text(encoding="utf-8")) == {"version": 1, "cu": True}
    assert "không ghi" in capsys.readouterr().out


def test_xuat_json_khong_ghi_khi_khong_tai_lieu_nao_nap_duoc(monkeypatch, tmp_path, capsys):
    """Đợt chạy trọn vẫn ra file vô nghĩa được: LLM trả `{"facts": []}` cho mọi tài liệu.

    Khi đó mỗi tài liệu mang `KHONG_CO_FACT`, đợt vẫn `xong`, mà `so_tai_lieu`
    là 0 - và `eval/ngoai_suy.py` chia cho nó.
    """
    from adapters.ingest import MA_KHONG_CO_FACT, TRANG_THAI_LOI

    lan = LanNap(space="synth")
    lan.trang_thai = TRANG_THAI_DOT_XONG
    lan.bat_dau, lan.ket_thuc = "2026-09-02T10:00:00+00:00", "2026-09-02T10:05:00+00:00"
    lan.ket_qua.tai_lieu.append(
        TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_LOI, ma=MA_KHONG_CO_FACT)
    )
    lan.chi_phi = TONG
    _gia_lap(monkeypatch, lan=lan)
    dich = tmp_path / "nap-that.json"
    dich.write_text('{"version": 1, "cu": true}', encoding="utf-8")

    mod.main([str(_corpus(tmp_path, "a.md") / "a.md"), "--xuat-json", str(dich)])
    assert json.loads(dich.read_text(encoding="utf-8")) == {"version": 1, "cu": True}
    ra = capsys.readouterr().out
    assert "không ghi" in ra and "so_tai_lieu = 0" in ra


def test_xuat_json_khong_ghi_khi_khong_co_dong_model_nao(monkeypatch, tmp_path, capsys):
    """Không lời gọi LLM/embedding nào trong cửa sổ đợt: file sẽ không có mẫu số nào."""
    lan = LanNap(space="synth")
    lan.trang_thai = TRANG_THAI_DOT_XONG
    lan.bat_dau, lan.ket_thuc = "2026-09-02T10:00:00+00:00", "2026-09-02T10:05:00+00:00"
    lan.ket_qua.tai_lieu.append(TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_DA_NAP))
    lan.chi_phi = TongChiPhi(so_lan=0, token_vao=0, token_ra=0, chi_phi_usd=0.0, theo_model=())
    _gia_lap(monkeypatch, lan=lan)
    dich = tmp_path / "nap-that.json"

    mod.main([str(_corpus(tmp_path, "a.md") / "a.md"), "--xuat-json", str(dich)])
    assert not dich.exists()
    assert "không lời gọi LLM/embedding nào" in capsys.readouterr().out


def test_in_ket_qua_in_xoa_theo_hang(capsys):
    kq = KetQuaNap(tai_lieu=[TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_DA_XOA, so_hyperedge=2)])
    mod.in_ket_qua(kq)
    assert "XÓA a.md" in capsys.readouterr().out


def test_in_ket_qua_in_so_fact_hop_le_va_loai(capsys):
    """Story 2.4: dòng NẠP in số fact hợp lệ / bị loại; dòng lỗi `KHONG_CO_FACT` in lý do phân biệt."""
    from adapters.ingest import MA_KHONG_CO_FACT, TRANG_THAI_LOI

    kq = KetQuaNap(
        tai_lieu=[
            TrangThaiTaiLieu(
                doc_key="a.md", trang_thai=TRANG_THAI_DA_NAP, so_hyperedge=2, so_fact_hop_le=2, so_fact_loai=1, so_chunk_hong=1
            ),
            TrangThaiTaiLieu(
                doc_key="b.md", trang_thai=TRANG_THAI_LOI, ma=MA_KHONG_CO_FACT, ly_do="3 bản ghi đều bị loại", so_fact_loai=3
            ),
        ]
    )
    mod.in_ket_qua(kq)
    ra = capsys.readouterr().out
    assert "NẠP a.md" in ra and "2 fact hợp lệ" in ra and "1 fact loại" in ra and "1 chunk hỏng" in ra
    assert "LOI b.md" in ra and "KHONG_CO_FACT" in ra and "3 bản ghi đều bị loại" in ra
