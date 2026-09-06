"""Lõi một đợt nạp `api/dot_nap.py` (story 2.7): trạng thái đợt, chi phí, số đo JSON.

Viết trước cơ chế (FR-27). Không Postgres, không kho, không LLM: port audit và
engine thay bằng bản giả, `nap_cac_tai_lieu` thay bằng hàm giả đúng hợp đồng
của pipeline thật (append `TrangThaiTaiLieu` vào `KetQuaNap` *trước* khi nạp).

Các hàng I/O Matrix phủ ở đây: nạp một đợt, đối chiếu lệch, tiến trình khác
giữ khóa, chi phí theo tài liệu, xuất số đo, đọc số đo.
"""

import asyncio
import json
from pathlib import Path

import pytest

import api.dot_nap as mod
from adapters.doi_chieu import StoreKeyMismatch
from adapters.ingest import (
    TRANG_THAI_DA_NAP,
    TRANG_THAI_KHONG_DOI,
    TRANG_THAI_LOI,
    IngestAlreadyRunning,
    KetQuaNap,
    TrangThaiTaiLieu,
)
from api.audit_postgres import DongChiPhi, TongChiPhi
from core.ingest_scan import KetQuaQuet, TaiLieuNguon, TuChoi

# --- Bản giả -----------------------------------------------------------------


def _tong(*dong: DongChiPhi) -> TongChiPhi:
    return TongChiPhi(
        so_lan=sum(d.so_lan for d in dong),
        token_vao=sum(d.token_vao for d in dong),
        token_ra=sum(d.token_ra for d in dong),
        chi_phi_usd=sum(d.chi_phi_usd for d in dong),
        theo_model=tuple(dong),
    )


DONG_LLM = DongChiPhi(
    model="deepseek-v4-flash",
    nha_cung_cap="deepseek",
    so_lan=2,
    token_vao=1000,
    token_ra=300,
    chi_phi_usd=0.0012,
)
DONG_EMBEDDING = DongChiPhi(
    model="text-embedding-3-small",
    nha_cung_cap="openai",
    so_lan=1,
    token_vao=800,
    token_ra=0,
    chi_phi_usd=0.000016,
)


class AuditGia:
    """Port audit giả: nhớ mọi cửa sổ được hỏi, trả cùng một tổng."""

    def __init__(self, tong: TongChiPhi | None = None):
        self.cua_so: list[tuple[str, str | None, str | None]] = []
        self._tong = _tong(DONG_LLM, DONG_EMBEDDING) if tong is None else tong

    async def tong_chi_phi(self, space, *, tu=None, den=None) -> TongChiPhi:
        self.cua_so.append((space, tu, den))
        return self._tong


class EngineGia:
    def __init__(self):
        self.da_dong = False

    async def dong(self):
        self.da_dong = True


def _tai_lieu(ten: str) -> TaiLieuNguon:
    return TaiLieuNguon(doc_key=ten, scope="noi_bo", content_type="runbook", noi_dung="than")


def _quet(*ten: str, tu_choi: tuple[TuChoi, ...] = ()) -> KetQuaQuet:
    return KetQuaQuet(tuple(_tai_lieu(t) for t in ten), tu_choi)


def _gan_engine(monkeypatch) -> EngineGia:
    """Engine giả **ghi lại `space`** nó được gọi với.

    Nuốt lặng `**_` là để `chay_lan_nap` bỏ `space=space` mà không test nào đỏ -
    tức toàn bộ đường tra từ điển thực thể theo tên space (story 2.12) ngắt được
    trong im lặng. `engine.space_da_nhan` là chỗ các test khẳng định nó còn nối.
    """
    engine = EngineGia()
    engine.space_da_nhan = []

    def gia(audit, *, space=None):
        engine.space_da_nhan.append(space)
        return engine

    monkeypatch.setattr(mod, "dung_engine_tu_moi_truong", gia)
    return engine


def _gan_nap(monkeypatch, than):
    """Thay `nap_cac_tai_lieu` bằng `than(ket_qua, cac_tai_lieu)`; giữ đúng hợp đồng."""

    async def nap_cac_tai_lieu(engine, cac_tai_lieu, *, space, policy_version, audit,
                               tu_choi=(), ket_qua=None, ep_ghi_de=False):
        ket_qua = KetQuaNap() if ket_qua is None else ket_qua
        ket_qua.tu_choi.extend(tu_choi)
        than(ket_qua, list(cac_tai_lieu))
        return ket_qua

    monkeypatch.setattr(mod, "nap_cac_tai_lieu", nap_cac_tai_lieu)


def _mot_tai_lieu_da_nap(ket_qua: KetQuaNap, cac_tai_lieu: list[TaiLieuNguon]) -> None:
    for i, tl in enumerate(cac_tai_lieu):
        ket_qua.tai_lieu.append(
            TrangThaiTaiLieu(
                doc_key=tl.doc_key,
                trang_thai=TRANG_THAI_DA_NAP,
                so_hyperedge=3,
                so_fact_hop_le=3,
                bat_dau=f"2026-09-02T10:0{i}:00+00:00",
                ket_thuc=f"2026-09-02T10:0{i}:30+00:00",
            )
        )


def _chay(quet, audit, *, space="synth", **kw) -> mod.LanNap:
    return asyncio.run(
        mod.chay_lan_nap(quet, space=space, policy_version="pv", audit=audit, **kw)
    )


# --- Hàng "nạp một đợt" -------------------------------------------------------


def test_dot_xong_giu_trang_thai_tung_tai_lieu_va_tu_choi(monkeypatch):
    _gan_engine(monkeypatch)
    _gan_nap(monkeypatch, _mot_tai_lieu_da_nap)
    audit = AuditGia()
    tc = TuChoi("x.pdf", "DINH_DANG_LA", "đuôi '.pdf' không nhận")
    lan = _chay(_quet("a.md", "b.md", tu_choi=(tc,)), audit)

    assert lan.trang_thai == mod.TRANG_THAI_DOT_XONG
    assert lan.ma_loi is None and lan.ngoai_le is None
    assert [t.doc_key for t in lan.ket_qua.tai_lieu] == ["a.md", "b.md"]
    assert [t.ten for t in lan.ket_qua.tu_choi] == ["x.pdf"]
    assert lan.bat_dau and lan.ket_thuc


def test_dot_moi_co_id_rieng(monkeypatch):
    _gan_engine(monkeypatch)
    _gan_nap(monkeypatch, _mot_tai_lieu_da_nap)
    audit = AuditGia()
    a = _chay(_quet("a.md"), audit)
    b = _chay(_quet("a.md"), audit)
    assert a.dot_id and b.dot_id and a.dot_id != b.dot_id


# --- Hàng "đối chiếu lệch" và "tiến trình khác giữ khóa" ----------------------


def test_doi_chieu_lech_thi_dot_loi_nhung_van_gom_chi_phi(monkeypatch):
    """Ngoại lệ giữa đợt không xóa phần tiền đã tiêu; mã lỗi ổn định vào `LanNap`."""
    _gan_engine(monkeypatch)

    def than(ket_qua, cac_tai_lieu):
        ket_qua.tai_lieu.append(
            TrangThaiTaiLieu(
                doc_key="a.md",
                trang_thai=TRANG_THAI_LOI,
                ma=StoreKeyMismatch.code,
                ly_do="vân tay 1a2b",
                bat_dau="2026-09-02T10:00:00+00:00",
                ket_thuc="2026-09-02T10:00:30+00:00",
            )
        )
        raise StoreKeyMismatch("khóa lệch ở vân tay 1a2b")

    _gan_nap(monkeypatch, than)
    audit = AuditGia()
    lan = _chay(_quet("a.md"), audit)

    assert lan.trang_thai == mod.TRANG_THAI_DOT_LOI
    assert lan.ma_loi == "STORE_KEY_MISMATCH"
    assert "1a2b" in lan.thong_diep_loi
    assert isinstance(lan.ngoai_le, StoreKeyMismatch)
    assert lan.chi_phi is not None and lan.chi_phi.chi_phi_usd > 0
    assert [c.doc_key for c in lan.chi_phi_tai_lieu] == ["a.md"]


def test_tien_trinh_khac_giu_khoa_thi_dot_loi_voi_ma_cua_khoa(monkeypatch):
    _gan_engine(monkeypatch)

    def than(ket_qua, cac_tai_lieu):
        raise IngestAlreadyRunning("một tiến trình ingest khác đang giữ khóa")

    _gan_nap(monkeypatch, than)
    lan = _chay(_quet("a.md"), AuditGia())
    assert lan.trang_thai == mod.TRANG_THAI_DOT_LOI
    assert lan.ma_loi == "INGEST_ALREADY_RUNNING"
    assert lan.ket_qua.tai_lieu == []


def test_engine_luon_dong_ke_ca_khi_dot_no(monkeypatch):
    engine = _gan_engine(monkeypatch)

    def than(ket_qua, cac_tai_lieu):
        raise RuntimeError("kho rớt")

    _gan_nap(monkeypatch, than)
    lan = _chay(_quet("a.md"), AuditGia())
    assert engine.da_dong is True
    # Ngoại lệ không có `code` thì lấy tên lớp: mã rỗng là mã không assert được.
    assert lan.ma_loi == "RuntimeError"


# --- Hàng "chi phí theo tài liệu" --------------------------------------------


def test_chi_phi_theo_tai_lieu_hoi_dung_cua_so_nua_mo(monkeypatch):
    _gan_engine(monkeypatch)
    _gan_nap(monkeypatch, _mot_tai_lieu_da_nap)
    audit = AuditGia()
    lan = _chay(_quet("a.md", "b.md"), audit)

    assert [(c.doc_key, c.bat_dau, c.ket_thuc) for c in lan.chi_phi_tai_lieu] == [
        ("a.md", "2026-09-02T10:00:00+00:00", "2026-09-02T10:00:30+00:00"),
        ("b.md", "2026-09-02T10:01:00+00:00", "2026-09-02T10:01:30+00:00"),
    ]
    assert ("synth", "2026-09-02T10:00:00+00:00", "2026-09-02T10:00:30+00:00") in audit.cua_so
    # Cửa sổ cả đợt mở từ mốc bắt đầu đợt, không có mốc đóng.
    assert ("synth", lan.bat_dau, None) in audit.cua_so


def test_tai_lieu_chua_co_moc_bat_dau_khong_hoi_chi_phi(monkeypatch):
    """Tài liệu bị từ chối ở cửa quét chưa từng chạy thì không có cửa sổ nào để hỏi."""
    _gan_engine(monkeypatch)

    def than(ket_qua, cac_tai_lieu):
        ket_qua.tai_lieu.append(TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_LOI))

    _gan_nap(monkeypatch, than)
    audit = AuditGia()
    lan = _chay(_quet("a.md"), audit)
    assert lan.chi_phi_tai_lieu == []
    assert len(audit.cua_so) == 1  # chỉ cửa sổ cả đợt


def test_tai_lieu_dang_chay_hoi_cua_so_mo(monkeypatch):
    """Dừng giữa chừng: tài liệu có `bat_dau` mà chưa có `ket_thuc` hỏi cửa sổ mở."""
    _gan_engine(monkeypatch)

    def than(ket_qua, cac_tai_lieu):
        ket_qua.tai_lieu.append(
            TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_LOI, bat_dau="2026-09-02T10:00:00+00:00")
        )
        raise RuntimeError("rớt")

    _gan_nap(monkeypatch, than)
    audit = AuditGia()
    _chay(_quet("a.md"), audit)
    assert ("synth", "2026-09-02T10:00:00+00:00", None) in audit.cua_so


# --- Hàng "xuất số đo" -------------------------------------------------------


def _lan_da_nap(monkeypatch, *ten: str) -> mod.LanNap:
    _gan_engine(monkeypatch)
    _gan_nap(monkeypatch, _mot_tai_lieu_da_nap)
    return _chay(_quet(*ten), AuditGia())


def test_so_do_nap_mang_du_khoa_cua_hop_dong(monkeypatch):
    lan = _lan_da_nap(monkeypatch, "a.md", "b.md")
    so_do = mod.so_do_nap(lan, lenh="uv run python -m api.do_chi_phi eval/data")

    assert so_do["version"] == mod.VERSION_SO_DO
    assert so_do["space"] == "synth"
    assert so_do["so_tai_lieu"] == 2
    assert so_do["lenh"].startswith("uv run python -m api.do_chi_phi")
    assert so_do["ngay"] == lan.ket_thuc
    assert so_do["dot_id"] == lan.dot_id
    theo_model = {d["model"]: d for d in so_do["theo_model"]}
    assert theo_model["deepseek-v4-flash"]["loai"] == "llm"
    assert theo_model["text-embedding-3-small"]["loai"] == "embedding"
    assert theo_model["deepseek-v4-flash"]["token_vao"] == 1000
    assert so_do["tong"]["chi_phi_usd"] == pytest.approx(0.0012 + 0.000016)


def test_so_do_nap_dem_so_tai_lieu_la_so_thuc_su_nap(monkeypatch):
    """`KHÔNG ĐỔI` không tốn tiền nên không được vào mẫu số của phép chia."""
    _gan_engine(monkeypatch)

    def than(ket_qua, cac_tai_lieu):
        ket_qua.tai_lieu += [
            TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_DA_NAP),
            TrangThaiTaiLieu(doc_key="b.md", trang_thai=TRANG_THAI_KHONG_DOI),
            TrangThaiTaiLieu(doc_key="c.md", trang_thai=TRANG_THAI_LOI, ma="KHONG_CO_FACT"),
        ]

    _gan_nap(monkeypatch, than)
    lan = _chay(_quet("a.md", "b.md", "c.md"), AuditGia())
    assert mod.so_do_nap(lan, lenh="x")["so_tai_lieu"] == 1


def test_so_do_nap_model_ngoai_danh_muc_la_loi_khong_phai_loai_rong(monkeypatch):
    """Không biết loại thì không xuất được: `eval/ngoai_suy` cộng theo `loai`."""
    from adapters.model_catalog import ModelUnknown

    _gan_engine(monkeypatch)
    _gan_nap(monkeypatch, _mot_tai_lieu_da_nap)
    la = DongChiPhi("model-la", "ai do", 1, 10, 5, 0.001)
    lan = _chay(_quet("a.md"), AuditGia(_tong(la)))
    with pytest.raises(ModelUnknown):
        mod.so_do_nap(lan, lenh="x")


def test_ghi_so_do_json_khong_de_lai_file_tam(monkeypatch, tmp_path):
    lan = _lan_da_nap(monkeypatch, "a.md")
    dich = tmp_path / "sau" / "nap-that.json"
    mod.ghi_so_do_json(dich, mod.so_do_nap(lan, lenh="x"))

    assert json.loads(dich.read_text(encoding="utf-8"))["version"] == mod.VERSION_SO_DO
    assert sorted(p.name for p in dich.parent.iterdir()) == ["nap-that.json"]


def test_ghi_so_do_json_hong_giua_chung_khong_pha_ban_cu(monkeypatch, tmp_path):
    """Ghi nguyên tử: file cũ còn nguyên khi lần ghi mới nổ."""
    lan = _lan_da_nap(monkeypatch, "a.md")
    dich = tmp_path / "nap-that.json"
    mod.ghi_so_do_json(dich, {"version": mod.VERSION_SO_DO, "cu": True})

    class KhongSerialize:
        pass

    with pytest.raises(TypeError):
        mod.ghi_so_do_json(dich, {"version": mod.VERSION_SO_DO, "x": KhongSerialize()})
    assert json.loads(dich.read_text(encoding="utf-8")) == {"version": mod.VERSION_SO_DO, "cu": True}
    assert sorted(p.name for p in dich.parent.iterdir()) == ["nap-that.json"]


# --- Hàng "đọc số đo": vòng tròn khép với `eval/ngoai_suy` ---------------------


def test_file_xuat_ra_doc_lai_duoc_bang_eval_ngoai_suy(monkeypatch, tmp_path):
    """Vòng tròn khép: cái `--xuat-json` ghi ra phải là cái `eval/` đọc vào.

    Hai bên không import nhau (chiều import cấm `eval` -> `api`), nên chỗ duy
    nhất chứng minh hai định dạng còn khớp là một test chạy cả hai.
    """
    from eval.ngoai_suy import doc_so_do_nap

    lan = _lan_da_nap(monkeypatch, "a.md", "b.md")
    dich = tmp_path / "nap-that.json"
    mod.ghi_so_do_json(dich, mod.so_do_nap(lan, lenh="x"))

    do = doc_so_do_nap(dich)
    assert do.so_tai_lieu == 2
    assert (do.token_vao_llm, do.token_ra_llm) == (1000, 300)
    assert do.chi_phi_llm_usd == pytest.approx(0.0012)
    assert do.token_embedding == 800
    assert do.chi_phi_embedding_usd == pytest.approx(0.000016)


def test_hai_version_so_do_khai_cung_mot_so():
    """`api/` ghi và `eval/` đọc; hai hằng lệch nhau là file mới bị từ chối im lặng."""
    from eval.ngoai_suy import VERSION_SO_DO_NAP

    assert mod.VERSION_SO_DO == VERSION_SO_DO_NAP


def test_dung_engine_tu_moi_truong_bat_thieu_bien_va_neu_ten_khoa(monkeypatch):
    """Điểm dựng engine chung: thiếu biến thì lỗi phải **nêu tên biến**.

    Cả màn lẫn script đi qua hàm này, nên một lỗi mù ở đây là hai lối vào cùng
    chết mà không ai biết phải đặt biến nào trên máy chủ.
    """
    for bien in ("LLM_MODEL", "EMBEDDING_MODEL", "NEO4J_URI", "QDRANT_URL"):
        monkeypatch.delenv(bien, raising=False)
    with pytest.raises(Exception) as e:
        mod.dung_engine_tu_moi_truong(AuditGia())
    assert "LLM_MODEL" in str(e.value) and "EMBEDDING_MODEL" in str(e.value)


def test_gom_chi_phi_hong_khong_che_mat_ma_loi_goc(monkeypatch):
    """Postgres rớt *cùng lúc* pipeline lỗi: mã lỗi gốc phải sống sót.

    Hai `await` gom chi phí nằm trong `finally`; để chúng ném là thay chỗ lỗi
    gốc bằng lỗi của Postgres, và `chay_lan_nap` ném dù docstring hứa không ném.
    """
    engine = _gan_engine(monkeypatch)

    def than(ket_qua, cac_tai_lieu):
        raise StoreKeyMismatch("khóa lệch ở vân tay 1a2b")

    _gan_nap(monkeypatch, than)

    class AuditNo:
        async def tong_chi_phi(self, *a, **kw):
            raise RuntimeError("postgres rớt")

    lan = _chay(_quet("a.md"), AuditNo())
    assert lan.trang_thai == mod.TRANG_THAI_DOT_LOI
    assert lan.ma_loi == "STORE_KEY_MISMATCH"
    assert lan.chi_phi is None and lan.chi_phi_tai_lieu == []
    assert engine.da_dong is True


def test_dot_bi_huy_khong_ket_o_dang_chay_va_phep_huy_van_lan(monkeypatch):
    """`CancelledError` không được nuốt: đợt ghi mã hủy rồi dội tiếp, engine vẫn đóng."""
    engine = _gan_engine(monkeypatch)

    async def nap_cac_tai_lieu(*a, **kw):
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "nap_cac_tai_lieu", nap_cac_tai_lieu)
    lan = mod.LanNap(space="synth")

    async def chay():
        t = asyncio.create_task(
            mod.chay_lan_nap(_quet("a.md"), space="synth", policy_version="pv",
                             audit=AuditGia(), lan=lan)
        )
        await asyncio.sleep(0)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(chay())
    assert lan.trang_thai == mod.TRANG_THAI_DOT_LOI
    assert lan.ma_loi == mod.MA_DOT_BI_HUY
    assert lan.dang_chay() is False
    assert engine.da_dong is True


def test_chay_lan_nap_truyen_space_xuong_ham_dung_engine(monkeypatch):
    """`space` phải tới hàm dựng engine, nếu không từ điển thực thể không được tra.

    Quy ước của story 2.12 là `config/tu-dien-thuc-the/<space>.yaml`, và mắt
    xích đầu tiên của nó là đúng tham số này. Bỏ nó đi thì mọi đợt nạp chạy
    **không** từ điển và không con số nào trong bộ test đổi.
    """
    engine = _gan_engine(monkeypatch)
    _gan_nap(monkeypatch, _mot_tai_lieu_da_nap)
    _chay(_quet("a.md"), AuditGia(), space="khao_sat")
    assert engine.space_da_nhan == ["khao_sat"]


# --- Story 3.3: dựng engine hỏng cũng không được rò kết nối -------------------


class _KetNoiDemDong:
    def __init__(self):
        self.so_lan_dong = 0

    async def close(self):
        self.so_lan_dong += 1


def _loi_mang_ket_noi(client, driver, *, tu_mo_qdrant=True, tu_mo_neo4j=True):
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


def test_dung_engine_hong_thi_dong_ket_noi_da_mo_va_danh_dot_la_loi():
    """`api/man_nap.py` là một FastAPI **chạy dài**, nên ca này là một ca rò thật.

    `_chay_nen` gọi `chay_lan_nap` mỗi lần có người tải tài liệu lên, nên một
    cấu hình sai thật - `QDRANT_URL` có mà `NEO4J_URI` thiếu - là **mỗi đợt rò
    thêm một client Qdrant** nếu phép dựng engine nằm ngoài khối phục hồi. Lời
    khai cũ "dot_nap chạy một lượt rồi thoát" chỉ đúng với CLI.

    Hai vế: hai kết nối `tu_mo=True` được đóng, và đợt được đánh `loi` chứ
    không ném - màn nạp đọc `ma_loi`/`thong_diep_loi` để hiện lên trang.
    """
    client, driver = _KetNoiDemDong(), _KetNoiDemDong()
    audit = AuditGia()

    def _tao_engine_no(_audit):
        raise _loi_mang_ket_noi(client, driver)

    lan = asyncio.run(
        mod.chay_lan_nap(
            _quet("a.md"),
            space="synth",
            policy_version="pv",
            audit=audit,
            tao_engine=_tao_engine_no,
        )
    )
    assert client.so_lan_dong == 1 and driver.so_lan_dong == 1
    assert lan.trang_thai == mod.TRANG_THAI_DOT_LOI
    assert lan.ma_loi == "RuntimeError"
    assert lan.ket_thuc, "đợt hỏng vẫn phải có mốc kết thúc"


def test_dung_engine_hong_khong_dong_ket_noi_tiem_tu_ngoai():
    """Luật sở hữu giữ nguyên: kết nối tiêm thuộc về người tiêm."""
    client, driver = _KetNoiDemDong(), _KetNoiDemDong()

    def _tao_engine_no(_audit):
        raise _loi_mang_ket_noi(client, driver, tu_mo_qdrant=False, tu_mo_neo4j=False)

    lan = asyncio.run(
        mod.chay_lan_nap(
            _quet("a.md"),
            space="synth",
            policy_version="pv",
            audit=AuditGia(),
            tao_engine=_tao_engine_no,
        )
    )
    assert (client.so_lan_dong, driver.so_lan_dong) == (0, 0)
    assert lan.trang_thai == mod.TRANG_THAI_DOT_LOI


def test_dung_engine_hong_giu_ma_on_dinh_cua_ngoai_le():
    """Ngoại lệ có `code` thì đợt mang đúng mã ấy, không mang tên lớp.

    Cùng luật với nhánh pipeline hỏng ngay dưới nó: `api/man_nap.py` hiện
    `ma_loi` lên trang, và một ô mã rỗng là một ô không tra được.
    """

    class _LoiCoMa(RuntimeError):
        code = "PROVIDER_CONFIG_MISSING"

    def _tao_engine_no(_audit):
        raise _LoiCoMa("thiếu key")

    lan = asyncio.run(
        mod.chay_lan_nap(
            _quet("a.md"),
            space="synth",
            policy_version="pv",
            audit=AuditGia(),
            tao_engine=_tao_engine_no,
        )
    )
    assert lan.ma_loi == "PROVIDER_CONFIG_MISSING"
    assert isinstance(lan.ngoai_le, _LoiCoMa)
