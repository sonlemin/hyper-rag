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
from api.nguon_thu_muc import TEN_FILE_SPACE

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


def test_tham_so_xoa_space_nhan_nhieu_nhat_mot_thu_muc():
    """`--xoa-space` nay nhận **một thư mục** để đối chiếu `.space` của nó.

    Nhiều hơn một, hay một file thay vì thư mục, vẫn là lỗi tham số: cả hai đều
    là dấu người chạy tưởng mình đang gõ một lệnh nạp.
    """
    with pytest.raises(SystemExit):
        mod._tham_so(["--xoa-space", "eval/data", "eval/corpus"])
    with pytest.raises(SystemExit):
        mod._tham_so(["--xoa-space", "eval/data/01-cap-quyen-gitlab.txt"])
    ts = mod._tham_so(["--xoa-space", "--space", "synth", "eval/data"])
    assert ts.xoa_space and ts.duong_dan == [Path("eval/data")]


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
    # **Ghi lại `space`** thay vì nuốt lặng `**_`: nhánh xóa cũng phải tra đúng
    # space (story 2.12), và một bản giả nuốt tham số là chỗ mắt xích đó đứt mà
    # không test nào đỏ.
    engine.space_da_nhan = []

    def _gia(a, *, space=None):
        engine.space_da_nhan.append(space)
        return engine

    monkeypatch.setattr(mod, "dung_engine_tu_moi_truong", _gia)

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


def _corpus(tmp_path: Path, *ten: str, space: str | None = "synth") -> Path:
    """Thư mục nguồn dựng tay; `space=None` là thư mục **chưa khai** space."""
    thu_muc = tmp_path / "corpus"
    thu_muc.mkdir(exist_ok=True)
    for t in ten:
        (thu_muc / t).write_text("---\nscope: noi_bo\ncontent_type: runbook\n---\nthan", encoding="utf-8")
    if space is not None:
        (thu_muc / TEN_FILE_SPACE).write_text(f"{space}\n", encoding="utf-8")
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
    # Nhánh xóa cũng phải dựng engine **theo đúng space** (story 2.12).
    assert engine.space_da_nhan == ["test_x"]


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


# ---------------------------------------------------------------------------
# Rào space của thư mục nguồn (story 2.11)
# ---------------------------------------------------------------------------


def test_thu_muc_khai_dung_space_thi_chay_binh_thuong(monkeypatch, tmp_path):
    """Hàng "Nạp đúng space" của I/O Matrix."""
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space="real")
    mod.main([str(thu_muc), "--space", "real"])
    assert goi == [("nap", ("a.md",), "real", False)]


def test_thu_muc_khai_space_khac_co_thi_tu_choi_truoc_moi_ket_noi(monkeypatch, tmp_path, capsys):
    """Hàng "Nạp lệch space": từ chối, nêu **cả hai** giá trị, không gọi lõi nạp.

    Ba space cùng tồn tại từ story 2.11, nên gõ nhầm một cờ là nạp tài liệu công
    ty vào mẫu số của Đo 2 và Đo 3 - một lần *thêm* im lặng mà không có gì đỏ.
    """
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space="real")
    with pytest.raises(SystemExit) as thoat:
        mod.main([str(thu_muc), "--space", "synth"])
    assert thoat.value.code == 1
    loi = capsys.readouterr().err
    assert "SPACE_LECH_THU_MUC" in loi
    assert "'real'" in loi and "'synth'" in loi
    assert goi == [], "không lời gọi lõi nạp nào được phép xảy ra"


def test_thu_muc_chua_khai_space_thi_tu_choi_va_neu_ten_file(monkeypatch, tmp_path, capsys):
    """Hàng "Thư mục chưa khai space": không đoán mặc định `synth`."""
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space=None)
    with pytest.raises(SystemExit):
        mod.main([str(thu_muc)])
    loi = capsys.readouterr().err
    assert "SPACE_KHONG_KHAI" in loi and TEN_FILE_SPACE in loi
    assert goi == []


def test_file_space_khong_xuat_hien_trong_danh_sach_tu_choi(monkeypatch, tmp_path, capsys):
    """Hàng "File `.space` lọt vào quét": nó là file ẩn, không phải `DINH_DANG_LA`."""
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md")
    (thu_muc / ".DS_Store").write_text("rac", encoding="utf-8")
    mod.main([str(thu_muc)])
    assert goi == [("nap", ("a.md",), "synth", False)]
    assert "DINH_DANG_LA" not in capsys.readouterr().out


def test_danh_sach_file_roi_khong_bi_rao_space(monkeypatch, tmp_path):
    """Hàng "Nạp danh sách file rời": không có thư mục nào để khai, chạy như cũ."""
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space=None)
    mod.main([str(thu_muc / "a.md"), "--space", "real"])
    assert goi == [("nap", ("a.md",), "real", False)]


def test_xoa_space_khong_bi_rao_space(monkeypatch, tmp_path):
    """`--xoa-space` không nhận đường dẫn nào, nên không có thư mục nào để đối chiếu."""
    goi, _, _ = _gia_lap(monkeypatch)
    mod.main(["--xoa-space", "--space", "real"])
    assert goi == [("xoa", "real")]


def test_file_space_hong_la_loi_co_ma(monkeypatch, tmp_path, capsys):
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md")
    (thu_muc / TEN_FILE_SPACE).write_text("synth\nkhao_sat\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        mod.main([str(thu_muc)])
    assert "SPACE_KHAI_KHONG_HOP_LE" in capsys.readouterr().err
    assert goi == []


def test_xoa_space_lech_thu_muc_thi_tu_choi(monkeypatch, tmp_path, capsys):
    """Nhánh xóa cần rào `.space` hơn nhánh nạp.

    `--xoa-space --space synth` khi định gõ `real` xóa sạch corpus của Đo 2 và
    Đo 3, không hỏi lại câu nào và không hoàn lại được.
    """
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space="real")
    with pytest.raises(SystemExit) as thoat:
        mod.main(["--xoa-space", "--space", "synth", str(thu_muc)])
    assert thoat.value.code == 1
    assert "SPACE_LECH_THU_MUC" in capsys.readouterr().err
    assert goi == [], "không được gọi xóa"


def test_xoa_space_dung_thu_muc_thi_chay(monkeypatch, tmp_path):
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space="real")
    mod.main(["--xoa-space", "--space", "real", str(thu_muc)])
    assert goi == [("xoa", "real")]


def test_xoa_space_in_so_tai_lieu_truoc_khi_xoa(monkeypatch, tmp_path, capsys):
    """Một lệnh xóa không nói nó sắp xóa bao nhiêu là một lệnh mà người chạy chỉ
    biết mình gõ nhầm space sau khi đã xóa xong."""
    _gia_lap(monkeypatch)
    monkeypatch.setattr(mod, "_so_tai_lieu_cua_space", lambda engine, space: "50")
    mod.main(["--xoa-space", "--space", "synth"])
    ra = capsys.readouterr().out
    assert "sắp xóa sạch space 'synth'" in ra and "50 tài liệu" in ra


def test_so_tai_lieu_hong_khong_chan_lenh_xoa(monkeypatch, tmp_path, capsys):
    """Sổ không đọc được thì nói "không đọc được sổ", không dội traceback."""
    _gia_lap(monkeypatch)
    mod.main(["--xoa-space", "--space", "test_khong_co"])
    assert "sắp xóa sạch" in capsys.readouterr().out


def test_glob_cung_thu_muc_cha_van_bi_rao(monkeypatch, tmp_path, capsys):
    """`real/*.md --space synth`: shell bung glob thành danh sách file rời, nên
    nhánh "một thư mục" không chạy - đúng lệnh nguy hiểm nhất đi lọt qua rào."""
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", "b.md", space="real")
    with pytest.raises(SystemExit):
        mod.main([str(thu_muc / "a.md"), str(thu_muc / "b.md"), "--space", "synth"])
    assert "SPACE_LECH_THU_MUC" in capsys.readouterr().err
    assert goi == []


def test_glob_cung_thu_muc_cha_dung_space_thi_chay(monkeypatch, tmp_path):
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", "b.md", space="real")
    mod.main([str(thu_muc / "b.md"), str(thu_muc / "a.md"), "--space", "real"])
    assert goi == [("nap", ("b.md", "a.md"), "real", False)]


def test_file_roi_khong_co_space_van_chay_nhu_cu(monkeypatch, tmp_path):
    """Hàng I/O Matrix "Nạp danh sách file rời": thư mục cha không khai gì thì
    rào không áp - đó là ca soát một tài liệu lẻ."""
    goi, _, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space=None)
    mod.main([str(thu_muc / "a.md"), "--space", "real"])
    assert goi == [("nap", ("a.md",), "real", False)]


def test_file_roi_hai_thu_muc_khac_nhau_khong_bi_rao(monkeypatch, tmp_path):
    """Không có thư mục cha chung thì không có `.space` nào để đối chiếu."""
    goi, _, _ = _gia_lap(monkeypatch)
    a = _corpus(tmp_path, "a.md", space="real")
    b = tmp_path / "khac"
    b.mkdir()
    (b / "b.md").write_text("---\nscope: noi_bo\ncontent_type: runbook\n---\nthan", encoding="utf-8")
    mod.main([str(a / "a.md"), str(b / "b.md"), "--space", "synth"])
    assert goi == [("nap", ("a.md", "b.md"), "synth", False)]


# ---------------------------------------------------------------------------
# Xem trước chi phí `--uoc-tinh` (story 2.13)
# ---------------------------------------------------------------------------


def _so_do(tmp_path: Path, ten: str, ngay: str, dong: list[dict], tong_usd: float) -> Path:
    """Một file số đo dựng tay, đủ hình dạng mà `cac_so_do_nap` đọc."""
    thu_muc = tmp_path / "so_do"
    thu_muc.mkdir(exist_ok=True)
    (thu_muc / ten).write_text(
        json.dumps(
            {
                "version": 1,
                "ngay": ngay,
                "lenh": "x",
                "space": "s",
                "dot_id": "d",
                "so_tai_lieu": 1,
                "theo_model": dong,
                "tong": {"so_lan": 1, "token_vao": 1, "token_ra": 1, "chi_phi_usd": tong_usd},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return thu_muc


def test_uoc_tinh_khong_di_cung_xuat_json():
    """Hàng "Xem trước sai cách dùng" của I/O Matrix.

    `--xuat-json` ghi mẫu số của bảng ngoại suy FR-30; một lần xem trước mà ghi
    ra file đó là ghi một đợt **chưa chạy** đè lên một đợt đã trả tiền.
    """
    with pytest.raises(SystemExit):
        mod._tham_so(["eval/data", "--uoc-tinh", "--xuat-json", "x.json"])


def test_uoc_tinh_khong_di_cung_xoa_space():
    with pytest.raises(SystemExit):
        mod._tham_so(["eval/data", "--uoc-tinh", "--xoa-space"])


def test_uoc_tinh_can_nguon_cua_dot_sap_chay():
    with pytest.raises(SystemExit):
        mod._tham_so(["--uoc-tinh"])


def test_model_chi_di_cung_uoc_tinh():
    """Đợt nạp thật đọc model từ `LLM_MODEL` như wrapper đọc, không từ dòng lệnh.

    Một `--model` áp cho đường nạp là hai nguồn sự thật cho cùng một lựa chọn,
    và bảng số của đợt sẽ khai model của biến môi trường trong khi lời gọi đi
    tới model của dòng lệnh.
    """
    with pytest.raises(SystemExit):
        mod._tham_so(["eval/data", "--model", "gpt-4o"])
    assert mod._tham_so(["eval/data", "--uoc-tinh", "--model", "gpt-4o"]).model == "gpt-4o"


def test_uoc_tinh_khong_cham_kho_khong_goi_llm(monkeypatch, tmp_path, capsys):
    """Hàng "Xem trước chi phí": in số rồi thoát 0, không mở kết nối nào.

    `_gia_lap` thay `AuditPostgres.mo` bằng một bản giả và đếm lời gọi; nhánh
    xem trước phải chạy mà **không** chạm nó, vì `chay()` mở Postgres ở dòng
    đầu và một lệnh xem trước không được đòi Postgres đang chạy mới xem được.
    """
    goi, audit, _ = _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", "b.md", space="that_khu")
    with pytest.raises(SystemExit) as ma:
        mod.main([str(thu_muc), "--space", "that_khu", "--uoc-tinh", "--model", "deepseek-v4-flash"])
    assert ma.value.code == 0
    assert goi == [], "không gọi lõi nạp"
    assert not audit.da_dong, "không mở rồi đóng Postgres - tức chưa mở lần nào"
    ra = capsys.readouterr().out
    assert "2 tài liệu" in ra and "lời gọi LLM" in ra and "USD" in ra


def test_uoc_tinh_van_bi_rao_space_chan(monkeypatch, tmp_path, capsys):
    """Rào `.space` chạy **trước** nhánh xem trước.

    Xem trước một đợt với cờ `--space` sai là in một con số cho một space khác,
    và đó đúng là lúc người ta tin con số nhất.
    """
    _gia_lap(monkeypatch)
    thu_muc = _corpus(tmp_path, "a.md", space="that_khu")
    with pytest.raises(SystemExit) as ma:
        mod.main([str(thu_muc), "--space", "real", "--uoc-tinh", "--model", "deepseek-v4-flash"])
    assert ma.value.code == 1
    assert "SPACE_LECH_THU_MUC" in capsys.readouterr().err


def test_uoc_tinh_thieu_model_la_loi_khong_doan_ho(monkeypatch, tmp_path, capsys):
    """Không có mặc định: một model đoán hộ cho một con số tiền nói về đợt khác."""
    _gia_lap(monkeypatch)
    monkeypatch.delenv(mod.BIEN_LLM_MODEL, raising=False)
    thu_muc = _corpus(tmp_path, "a.md", space="that_khu")
    with pytest.raises(SystemExit) as ma:
        mod.main([str(thu_muc), "--space", "that_khu", "--uoc-tinh"])
    assert ma.value.code == 1
    assert mod.BIEN_LLM_MODEL in capsys.readouterr().err


def test_uoc_tinh_doc_model_tu_bien_moi_truong_cua_duong_nap(monkeypatch, tmp_path, capsys):
    _gia_lap(monkeypatch)
    monkeypatch.setenv(mod.BIEN_LLM_MODEL, "deepseek-v4-flash")
    thu_muc = _corpus(tmp_path, "a.md", space="that_khu")
    with pytest.raises(SystemExit) as ma:
        mod.main([str(thu_muc), "--space", "that_khu", "--uoc-tinh"])
    assert ma.value.code == 0
    assert "deepseek-v4-flash" in capsys.readouterr().out


def test_uoc_tinh_khong_tai_lieu_nao_la_loi_khong_phai_dot_mien_phi(monkeypatch, tmp_path, capsys):
    """"0 lời gọi, 0 USD" rồi thoát 0 đọc y như một đợt miễn phí."""
    _gia_lap(monkeypatch)
    thu_muc = tmp_path / "rong"
    thu_muc.mkdir()
    (thu_muc / TEN_FILE_SPACE).write_text("that_khu\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ma:
        mod.main([str(thu_muc), "--space", "that_khu", "--uoc-tinh", "--model", "deepseek-v4-flash"])
    assert ma.value.code == 1
    assert "0 lời gọi" in capsys.readouterr().err


def test_so_loi_goi_llm_bang_so_chunk_chinh_xac(tmp_path):
    """Số lời gọi là **số đếm chính xác**, không phải một ước lượng.

    Nó bằng số chunk mà đường nạp sẽ cắt ra, tính bằng chính
    `adapters/chunking.py` mà `EngineACL.ainsert` dùng - nên nó không lệch được
    khỏi đợt thật trừ khi luật chia chunk đổi.
    """
    from adapters.chunking import cau_hinh_chunk, chia_chunk
    from core.ingest_scan import quet_cac_file

    thu_muc = _corpus(tmp_path, "a.md", "b.md", space="that_khu")
    quet = quet_cac_file(sorted(p for p in thu_muc.iterdir() if p.suffix == ".md"))
    uoc = mod.uoc_tinh_dot(quet, "deepseek-v4-flash", space="that_khu")
    thuc = sum(len(chia_chunk(t.noi_dung, cau_hinh_chunk())) for t in quet.chap_nhan)
    assert uoc.so_loi_goi == thuc == 2
    assert uoc.token_vao > 0


def test_ty_le_token_ra_lay_cua_chinh_model_do_va_cua_dot_gan_nhat(tmp_path):
    """Tỷ lệ ra/vào là số **đo được của chính model đó**, không phải một hằng chung.

    Qwen cục bộ cho 1,04 còn DeepSeek cho 0,38-0,39, lệch nhau gần ba lần; một
    tỷ lệ chung ước sai gần ba lần trên khoản đắt nhất của hóa đơn (token ra
    của DeepSeek đắt gấp ba token vào).
    """
    thu_muc = _so_do(
        tmp_path,
        "cu.json",
        "2026-01-01T00:00:00+00:00",
        [{"model": "deepseek-v4-flash", "loai": "llm", "token_vao": 100, "token_ra": 90,
          "chi_phi_usd": 1.0, "nha_cung_cap": "deepseek", "so_lan": 1}],
        1.0,
    )
    _so_do(
        tmp_path,
        "moi.json",
        "2026-02-01T00:00:00+00:00",
        [
            {"model": "deepseek-v4-flash", "loai": "llm", "token_vao": 1000, "token_ra": 400,
             "chi_phi_usd": 1.0, "nha_cung_cap": "deepseek", "so_lan": 1},
            {"model": "qwen2.5:7b", "loai": "llm", "token_vao": 100, "token_ra": 104,
             "chi_phi_usd": 0.0, "nha_cung_cap": "ollama", "so_lan": 1},
        ],
        1.0,
    )
    ds = mod.ty_le_token_ra("deepseek-v4-flash", thu_muc)
    assert ds is not None and ds.ty_le == pytest.approx(0.4) and ds.nguon == "moi.json"
    qw = mod.ty_le_token_ra("qwen2.5:7b", thu_muc)
    assert qw is not None and qw.ty_le == pytest.approx(1.04)
    assert mod.ty_le_token_ra("gpt-4o", thu_muc) is None


def test_chua_do_model_nao_thi_khong_uoc_token_ra_thay_vi_bia_mot_hang(tmp_path, capsys):
    """Một hằng chọn đại cho một model chưa chạy bao giờ đọc y như một số đo."""
    from core.ingest_scan import quet_cac_file

    thu_muc = _corpus(tmp_path, "a.md", space="that_khu")
    trong = tmp_path / "khong_co_so_do"
    trong.mkdir()
    quet = quet_cac_file([thu_muc / "a.md"])
    uoc = mod.uoc_tinh_dot(quet, "gpt-4o", space="that_khu", thu_muc_so_do=trong)
    assert uoc.token_ra_uoc is None and uoc.chi_phi_usd is None
    assert uoc.chi_phi_vao_usd > 0
    assert "chưa ước được" in uoc.dong_in()


def test_embedding_khong_uoc_ma_noi_phan_no_da_chiem(tmp_path):
    """Embedding không có con số ước, chỉ có phần nó đã chiếm ở các đợt đã đo.

    Số lời gọi embedding phụ thuộc số entity và hyperedge mà LLM **sắp** sinh
    ra, tức phụ thuộc đúng thứ chưa chạy. Một con số bịa cho nó tệ hơn một dòng
    nói thẳng là chưa ước.
    """
    thu_muc = _so_do(
        tmp_path,
        "a.json",
        "2026-02-01T00:00:00+00:00",
        [
            {"model": "deepseek-v4-flash", "loai": "llm", "token_vao": 1000, "token_ra": 400,
             "chi_phi_usd": 0.98, "nha_cung_cap": "deepseek", "so_lan": 1},
            {"model": "text-embedding-3-small", "loai": "embedding", "token_vao": 100,
             "token_ra": 0, "chi_phi_usd": 0.02, "nha_cung_cap": "openai", "so_lan": 1},
        ],
        1.0,
    )
    # Đợt 0 USD (đường cục bộ) bị loại: phần trăm trên một tổng bằng 0 vô nghĩa.
    _so_do(
        tmp_path,
        "cuc-bo.json",
        "2026-03-01T00:00:00+00:00",
        [{"model": "qwen2.5:7b", "loai": "llm", "token_vao": 10, "token_ra": 10,
          "chi_phi_usd": 0.0, "nha_cung_cap": "ollama", "so_lan": 1}],
        0.0,
    )
    phan = mod.phan_embedding_da_do(thu_muc)
    assert phan == [("a.json", pytest.approx(0.02))]


def test_phan_embedding_cua_hai_dot_deepseek_that_la_1_8_va_2_3_phan_tram():
    """Hai con số mà spec 2.13 nêu, tính lại từ chính hai file số đo đã commit.

    Chép tay chúng vào dòng in ra là để dòng đó nói về hai đợt cũ trong khi file
    đã đổi; tính lại từ nguồn là chỗ duy nhất giữ hai bên khớp nhau.
    """
    # Số của ba đợt nạp lại 05/09 (story 2.12). Trước đó là 1,9% và 2,3%.
    phan = dict(mod.phan_embedding_da_do())
    assert phan["nap-that.json"] == pytest.approx(0.018, abs=5e-4)
    assert phan["nap-khao-sat.json"] == pytest.approx(0.023, abs=5e-4)
    assert "nap-real.json" not in phan, "đợt 0 USD không có phần trăm nào có nghĩa"


def test_file_so_do_hong_khong_lam_hong_ca_lenh_xem_truoc(tmp_path):
    """Đây là đường *xem trước*, không phải đường đọc mẫu số của chương 4.

    Một file rách không được biến `--uoc-tinh` thành một lệnh không chạy được:
    khi ấy người ta bỏ luôn bước xem trước, tức bỏ đúng thứ story này dựng ra.
    """
    thu_muc = _so_do(
        tmp_path,
        "tot.json",
        "2026-02-01T00:00:00+00:00",
        [{"model": "deepseek-v4-flash", "loai": "llm", "token_vao": 100, "token_ra": 38,
          "chi_phi_usd": 1.0, "nha_cung_cap": "deepseek", "so_lan": 1}],
        1.0,
    )
    (thu_muc / "rach.json").write_text("{khong phai json", encoding="utf-8")
    assert [d["_ten_file"] for d in mod.cac_so_do_nap(thu_muc)] == ["tot.json"]


def test_dong_in_khong_chep_cung_so_dot_hay_khoang_ty_le(tmp_path):
    """Dòng in ra không được mang một con số chép cứng về các đợt đã đo.

    Vòng review 05/09: câu "hai đợt DeepSeek 1,9% và 2,3%" thành sai ngay ở đợt
    thứ ba, và khoảng "DeepSeek 0,38-0,39" thành sai khi đợt `that_khu` cho
    0,42. Cả hai nay đọc lại từ file, nên test này chấm chúng **theo file dựng
    tay**, không theo `eval/so_do_nap/` thật.
    """
    from core.ingest_scan import quet_cac_file

    thu_muc = _so_do(
        tmp_path,
        "a.json",
        "2026-02-01T00:00:00+00:00",
        [
            {"model": "deepseek-v4-flash", "loai": "llm", "token_vao": 1000, "token_ra": 400,
             "chi_phi_usd": 0.9, "nha_cung_cap": "deepseek", "so_lan": 1},
            {"model": "text-embedding-3-small", "loai": "embedding", "token_vao": 100,
             "token_ra": 0, "chi_phi_usd": 0.1, "nha_cung_cap": "openai", "so_lan": 1},
        ],
        1.0,
    )
    _so_do(
        tmp_path,
        "b.json",
        "2026-03-01T00:00:00+00:00",
        [{"model": "qwen2.5:7b", "loai": "llm", "token_vao": 100, "token_ra": 200,
          "chi_phi_usd": 0.0, "nha_cung_cap": "ollama", "so_lan": 1}],
        0.0,
    )
    khoang = mod.khoang_ty_le_da_do(thu_muc)
    assert khoang == {"deepseek-v4-flash": (0.4, 0.4), "qwen2.5:7b": (2.0, 2.0)}

    nguon = tmp_path / "a.md"
    nguon.write_text(
        "---\nscope: noi_bo\ncontent_type: runbook\n---\nthan tai lieu", encoding="utf-8"
    )
    dong = mod.uoc_tinh_dot(
        quet_cac_file([nguon]), "deepseek-v4-flash", thu_muc_so_do=thu_muc
    ).dong_in()
    assert "qwen2.5:7b 2.00" in dong, "khoảng tỷ lệ dựng từ file, không chép cứng"
    assert "0,38-0,39" not in dong and "1,04" not in dong
    assert "Ở 1 đợt đã trả tiền" in dong, "số đợt đếm từ file"


def test_dong_embedding_co_tran_so_dot_neu_ten(tmp_path):
    """Dòng "embedding chiếm bao nhiêu" không được dài thêm mỗi lần nạp."""
    from core.ingest_scan import quet_cac_file

    thu_muc = None
    for i in range(mod.SO_DOT_NEU_TEN_EMBEDDING + 2):
        thu_muc = _so_do(
            tmp_path,
            f"dot-{i}.json",
            f"2026-0{i + 1}-01T00:00:00+00:00",
            [
                {"model": "deepseek-v4-flash", "loai": "llm", "token_vao": 1000,
                 "token_ra": 400, "chi_phi_usd": 0.9, "nha_cung_cap": "deepseek", "so_lan": 1},
                {"model": "text-embedding-3-small", "loai": "embedding", "token_vao": 100,
                 "token_ra": 0, "chi_phi_usd": 0.1, "nha_cung_cap": "openai", "so_lan": 1},
            ],
            1.0,
        )
    nguon = tmp_path / "a.md"
    nguon.write_text(
        "---\nscope: noi_bo\ncontent_type: runbook\n---\nthan tai lieu", encoding="utf-8"
    )
    dong = mod.uoc_tinh_dot(
        quet_cac_file([nguon]), "deepseek-v4-flash", thu_muc_so_do=thu_muc
    ).dong_in()
    assert dong.count(".json)") == mod.SO_DOT_NEU_TEN_EMBEDDING
    assert "2 đợt cũ hơn trong khoảng" in dong
