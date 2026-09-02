"""Màn nạp tài liệu `api/man_nap.py` (story 2.7): ba endpoint JSON và trang HTML.

Viết trước cơ chế (FR-27). Không Postgres, không kho, không LLM: `mo_audit` và
`chay_lan_nap` thay bằng bản giả, nên test chỉ đo phần màn tự làm - nhận file,
làm sạch tên, quét, mở đúng một đợt, và dựng ảnh chụp đợt cho trang.

Các hàng I/O Matrix phủ ở đây: nạp một đợt, file bị từ chối, tên file đi vòng,
tên file lạ, không chọn file, re-ingest, 0 fact hợp lệ, đối chiếu lệch, đợt
đang chạy, tải lại trang giữa chừng, poll id lạ.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import api.man_nap as mod
from adapters.doi_chieu import StoreKeyMismatch
from adapters.ingest import (
    MA_KHONG_CO_FACT,
    TRANG_THAI_DA_NAP,
    TRANG_THAI_KHONG_DOI,
    TRANG_THAI_LOI,
    TrangThaiTaiLieu,
)
from api.audit_postgres import DongChiPhi, TongChiPhi
from api.dot_nap import MA_DOT_BI_HUY, TRANG_THAI_DOT_LOI, TRANG_THAI_DOT_XONG
from core.ingest_scan import KICH_THUOC_TOI_DA, KetQuaQuet

THAN = "Quy trinh cap quyen GitLab cho nhan vien moi."
FILE_HOP_LE = f"---\nscope: noi_bo\ncontent_type: runbook\n---\n{THAN}".encode("utf-8")


def _file(ten: str, noi_dung: bytes = FILE_HOP_LE):
    return ("files", (ten, noi_dung, "text/markdown"))


class AuditGia:
    def __init__(self):
        self.da_dong = False

    async def dong(self):
        self.da_dong = True


@pytest.fixture(autouse=True)
def _don_dot():
    """Mỗi test một sổ đợt sạch: đợt sống trong bộ nhớ tiến trình, không DB."""
    mod.QUAN_LY.xoa_het()
    yield
    mod.QUAN_LY.xoa_het()


@pytest.fixture
def audit(monkeypatch) -> AuditGia:
    a = AuditGia()

    async def mo_audit():
        return a

    monkeypatch.setattr(mod, "mo_audit", mo_audit)
    return a


def _gan_chay(monkeypatch, than):
    """Thay `chay_lan_nap`; `than(lan, quet)` viết trạng thái vào chính `lan`."""
    goi: list[dict] = []

    async def chay_lan_nap(quet, *, space, policy_version, audit, lan, ep_ghi_de=False):
        goi.append(dict(quet=quet, space=space, ep_ghi_de=ep_ghi_de, lan=lan))
        than(lan, quet)
        return lan

    monkeypatch.setattr(mod, "chay_lan_nap", chay_lan_nap)
    return goi


def _xong(lan, quet, tai_lieu=None):
    lan.ket_qua.tu_choi.extend(quet.tu_choi)
    lan.ket_qua.tai_lieu.extend(
        tai_lieu
        if tai_lieu is not None
        else [
            TrangThaiTaiLieu(
                doc_key=t.doc_key,
                trang_thai=TRANG_THAI_DA_NAP,
                so_chunk=1,
                so_hyperedge=4,
                so_entity=5,
                so_fact_hop_le=4,
                bat_dau="2026-09-02T10:00:00+00:00",
                ket_thuc="2026-09-02T10:00:30+00:00",
            )
            for t in quet.chap_nhan
        ]
    )
    lan.trang_thai = TRANG_THAI_DOT_XONG
    lan.ket_thuc = "2026-09-02T10:00:30+00:00"
    lan.chi_phi = TongChiPhi(
        so_lan=2,
        token_vao=1000,
        token_ra=300,
        chi_phi_usd=0.0012,
        theo_model=(DongChiPhi("deepseek-v4-flash", "deepseek", 2, 1000, 300, 0.0012),),
    )


@pytest.fixture
def client(audit) -> TestClient:
    with TestClient(mod.app) as c:
        yield c


def _than_trinh_duyet_chua_chon_file(*, kem_file: bool = False) -> dict:
    """Thân multipart đúng như trình duyệt gửi khi bấm Nạp mà chưa chọn file.

    Không dùng `files=` của httpx được: nó bỏ hẳn thuộc tính `filename` khi tên
    rỗng, nên part thành một trường chữ chứ không phải một part file - tức là
    không tái hiện đúng ca cần canh. Trình duyệt thì gửi `filename=""`, và
    Starlette dựng nó thành một `UploadFile` tên rỗng.
    """
    than = (
        b'--B\r\nContent-Disposition: form-data; name="files"; filename=""\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n\r\n"
    )
    if kem_file:
        than += (
            b'--B\r\nContent-Disposition: form-data; name="files"; filename="a.md"\r\n'
            b"Content-Type: text/markdown\r\n\r\n" + FILE_HOP_LE + b"\r\n"
        )
    than += b'--B\r\nContent-Disposition: form-data; name="space"\r\n\r\nsynth\r\n--B--\r\n'
    return {"content": than, "headers": {"Content-Type": "multipart/form-data; boundary=B"}}


def _no_bang_gia(p):
    raise RuntimeError("bảng chính sách hỏng")


def _cho_xong(client, dot_id: str, lan_thu: int = 200) -> dict:
    """Poll tới khi đợt rời trạng thái `dang_chay`; đợt chạy nền trên loop của app."""
    for _ in range(lan_thu):
        r = client.get(f"/api/dot/{dot_id}")
        assert r.status_code == 200, r.text
        if r.json()["trang_thai"] != mod.TRANG_THAI_DOT_DANG_CHAY:
            return r.json()
    raise AssertionError("đợt không kết thúc sau nhiều lần poll")


# --- Trang -------------------------------------------------------------------


def test_nguon_trang_la_html_thuan_khong_tai_nguyen_ngoai(client):
    """Chỉ canh *nguồn trang* (`GET /` trả một hằng), không canh hành vi JS."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "<form" in html and "/api/dot/moi-nhat" in html
    # Không CDN, không thư viện ngoài (Boundaries: HTML + JS thuần trong `api/`).
    assert "http://" not in html and "https://" not in html
    assert "<script src=" not in html and "<link" not in html


def test_nguon_trang_nhan_hang_trang_thai_tu_python(client):
    """JS so sánh bằng chính chuỗi pipeline ghi ra, không bằng bản chép tay.

    Đổi `TRANG_THAI_DA_NAP` trong `adapters/ingest.py` mà JS còn so với chuỗi
    cũ thì mọi tài liệu đã nạp hiện thành LỖI trên trang, và không có gì đỏ.
    """
    html = client.get("/").text
    assert f'"da_nap": "{TRANG_THAI_DA_NAP}"' in html
    assert f'"dot_dang_chay": "{mod.TRANG_THAI_DOT_DANG_CHAY}"' in html
    assert f'"dot_xong": "{TRANG_THAI_DOT_XONG}"' in html
    # Không còn chuỗi trạng thái viết tay trong JS.
    assert "=== 'dang_chay'" not in html and "=== 'da_nap'" not in html


# --- Hàng "nạp một đợt" -------------------------------------------------------


def test_nap_mot_dot_tra_201_va_theo_duoc_tung_tai_lieu(client, monkeypatch):
    goi = _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md"), _file("b.md"), _file("c.txt")])
    assert r.status_code == 201, r.text
    dot_id = r.json()["dot_id"]

    anh = _cho_xong(client, dot_id)
    assert anh["trang_thai"] == TRANG_THAI_DOT_XONG
    assert [t["doc_key"] for t in anh["tai_lieu"]] == ["a.md", "b.md", "c.txt"]
    assert all(t["trang_thai"] == TRANG_THAI_DA_NAP for t in anh["tai_lieu"])
    assert anh["chi_phi"]["chi_phi_usd"] == pytest.approx(0.0012)
    # `doc_key` là tên file, cùng quy ước với CLI.
    assert [t.doc_key for t in goi[0]["quet"].chap_nhan] == ["a.md", "b.md", "c.txt"]


def test_dot_xong_dong_port_audit(client, audit, monkeypatch):
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md")])
    _cho_xong(client, r.json()["dot_id"])
    assert audit.da_dong is True


def test_khong_hien_than_tai_lieu_len_trang(client, monkeypatch):
    """Đợt chạy dưới cờ system nên trang đứng ngoài mọi tầng che: chỉ metadata."""
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    assert THAN not in str(anh)


# --- Hàng "file bị từ chối" ---------------------------------------------------


def test_file_bi_tu_choi_kem_ma_va_ly_do_file_ke_van_nap(client, monkeypatch):
    _gan_chay(monkeypatch, _xong)
    r = client.post(
        "/api/nap",
        files=[
            _file("x.pdf", b"%PDF-1.4"),
            _file("rong.md", b"   "),
            _file("thieu.md", b"khong co frontmatter"),
            _file("nhi-phan.txt", b"\xff\xfe\x00\x01"),
            _file("a.md"),
        ],
    )
    anh = _cho_xong(client, r.json()["dot_id"])
    tu_choi = {t["ten"]: t["ma"] for t in anh["tu_choi"]}
    assert tu_choi == {
        "x.pdf": "DINH_DANG_LA",
        "rong.md": "FILE_RONG",
        "thieu.md": "THIEU_METADATA",
        "nhi-phan.txt": "KHONG_PHAI_UTF8",
    }
    assert all(t["ly_do"] for t in anh["tu_choi"])
    assert [t["doc_key"] for t in anh["tai_lieu"]] == ["a.md"]


# --- Hàng "tên file đi vòng" và "tên file lạ" --------------------------------


@pytest.mark.parametrize(
    "vao,ra",
    [
        ("../../etc/passwd", "passwd"),
        ("/etc/shadow", "shadow"),
        ("a.md", "a.md"),
        ("..\\..\\win.md", "win.md"),
        ("thu muc/con/b.txt", "b.txt"),
    ],
)
def test_ten_an_toan_chi_giu_phan_ten(vao, ra):
    assert mod.ten_an_toan(vao) == ra


@pytest.mark.parametrize("ten", ["", ".", "..", "/", "   ", "../..", "\\"])
def test_ten_file_la_bi_tu_choi_co_ma(ten):
    with pytest.raises(mod.LoiMan) as e:
        mod.ten_an_toan(ten)
    assert e.value.ma == "TEN_FILE_LA"


def test_ten_di_vong_chi_lay_phan_ten_khi_nap(client, monkeypatch):
    goi = _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("../../etc/passwd.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    assert [t["doc_key"] for t in anh["tai_lieu"]] == ["passwd.md"]
    assert [t.doc_key for t in goi[0]["quet"].chap_nhan] == ["passwd.md"]


def test_ten_file_la_tra_400_va_khong_mo_dot(client, monkeypatch):
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("..")])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TEN_FILE_LA"
    assert client.get("/api/dot/moi-nhat").status_code == 404


# --- Hàng "không chọn file" ---------------------------------------------------


def test_khong_chon_file_tra_400_khong_mo_dot(client, monkeypatch):
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", data={"space": "synth"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "KHONG_CO_FILE"
    assert client.get("/api/dot/moi-nhat").status_code == 404


def test_part_filename_rong_van_la_khong_chon_file(client, monkeypatch):
    """Trình duyệt gửi một part `filename=""` khi bấm Nạp mà chưa chọn file.

    Test trên gửi request *không có part nào*, tức nó không đi qua đường này.
    Không lọc part rỗng trước thì hàng matrix "không chọn file" hiện ra mã
    `TEN_FILE_LA` - đúng lỗi, sai câu trả lời.
    """
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", **_than_trinh_duyet_chua_chon_file())
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "KHONG_CO_FILE"
    assert client.get("/api/dot/moi-nhat").status_code == 404


def test_part_rong_lan_giua_khong_chan_file_that(client, monkeypatch):
    """Part rỗng đi kèm một file thật thì bị bỏ qua, file thật vẫn nạp."""
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", **_than_trinh_duyet_chua_chon_file(kem_file=True))
    assert r.status_code == 201, r.text
    anh = _cho_xong(client, r.json()["dot_id"])
    assert [t["doc_key"] for t in anh["tai_lieu"]] == ["a.md"]


def test_hai_file_trung_ten_tu_choi_ca_dot(client, monkeypatch):
    """Cùng `doc_key` hai lần trong một đợt: trang hiện hai dòng cho một tài liệu."""
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md"), _file("thu/muc/a.md")])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TEN_FILE_TRUNG"
    assert "a.md" in r.json()["error"]["message"]
    assert client.get("/api/dot/moi-nhat").status_code == 404


# `""` không có trong danh sách: FastAPI coi một trường form rỗng là "chưa gửi"
# và rơi về `Form(default=...)`, nên chuỗi rỗng không bao giờ tới được cửa kiểm.
@pytest.mark.parametrize("space", ["synth-2", "1synth", "SYNTH!", "a" * 200, "synth "])
def test_space_la_tra_400_khong_mo_dot(client, monkeypatch, space):
    """`space` là tên collection Qdrant và nhãn Neo4j; màn không có đường xóa.

    Gõ nhầm mà cho 201 là mở một không gian mới trong hai kho mà chỉ CLI dọn
    được; `synth-2` thì trước đây còn cho 201 rồi đợt chết với `ma_loi` là
    `"ValueError"`.
    """
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md")], data={"space": space})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "SPACE_LA"
    assert client.get("/api/dot/moi-nhat").status_code == 404


def test_space_hop_le_di_thang_vao_dot(client, monkeypatch):
    goi = _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md")], data={"space": "real"})
    assert r.status_code == 201 and r.json()["space"] == "real"
    _cho_xong(client, r.json()["dot_id"])
    assert goi[0]["space"] == "real"


def test_file_vuot_tran_bi_cat_o_vong_doc_va_tu_choi_qua_lon(client, monkeypatch):
    """Trần 2 MiB cắt ngay ở vòng đọc, không ghi trọn file rồi mới `stat`.

    Một byte dôi ra là đủ để cửa quét trả đúng mã `QUA_LON` sẵn có, và file kế
    vẫn nạp - không cần đường xử lý mới.
    """
    _gan_chay(monkeypatch, _xong)
    to = b"---\nscope: noi_bo\ncontent_type: runbook\n---\n" + b"x" * (KICH_THUOC_TOI_DA + 4096)
    r = client.post("/api/nap", files=[_file("to.md", to), _file("a.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    assert [(t["ten"], t["ma"]) for t in anh["tu_choi"]] == [("to.md", "QUA_LON")]
    assert [t["doc_key"] for t in anh["tai_lieu"]] == ["a.md"]


@pytest.mark.parametrize("goc", sorted(mod.GOC_CHO_PHEP))
def test_origin_cua_chinh_man_duoc_nhan(client, monkeypatch, goc):
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md")], headers={"Origin": goc})
    assert r.status_code == 201


def test_origin_la_bi_tu_choi_403(client, monkeypatch):
    """Màn là POST không xác thực tiêu tiền thật, và multipart không có preflight.

    Trong lúc SSH tunnel mở, bất kỳ trang nào sonlm mở trong cùng trình duyệt
    đều POST được vào `http://localhost:8100/api/nap`.
    """
    _gan_chay(monkeypatch, _xong)
    r = client.post(
        "/api/nap", files=[_file("a.md")], headers={"Origin": "https://trang-la.example"}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ORIGIN_LA"
    assert client.get("/api/dot/moi-nhat").status_code == 404


def test_khong_co_origin_thi_cho_qua(client, monkeypatch):
    """curl và client không phải trình duyệt không gửi `Origin`; chúng không bị chặn."""
    _gan_chay(monkeypatch, _xong)
    assert client.post("/api/nap", files=[_file("a.md")]).status_code == 201


def test_kiem_origin_la_ham_thuan(client):
    mod.kiem_origin(None)
    mod.kiem_origin("")
    for goc in mod.GOC_CHO_PHEP:
        mod.kiem_origin(goc)
    with pytest.raises(mod.LoiMan) as e:
        mod.kiem_origin("http://localhost:9999")
    assert e.value.ma == "ORIGIN_LA" and e.value.http == 403


# --- Hàng "re-ingest", "không đổi", "0 fact hợp lệ" ---------------------------


def test_re_ingest_mang_co_va_trang_hien_ghi_de(client, monkeypatch):
    def than(lan, quet):
        _xong(
            lan,
            quet,
            [
                TrangThaiTaiLieu(
                    doc_key="a.md", trang_thai=TRANG_THAI_DA_NAP, re_ingest=True, so_hyperedge=4
                )
            ],
        )

    _gan_chay(monkeypatch, than)
    r = client.post("/api/nap", files=[_file("a.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    # Hàng matrix "trang hiện GHI ĐÈ" phủ ở mức *ảnh chụp*: cờ `re_ingest` là
    # thứ quyết định nhãn. Một assert `"GHI ĐÈ" in client.get("/").text` sẽ xanh
    # bất kể `veTaiLieu` làm gì với cờ đó, vì `GET /` trả một hằng.
    assert anh["tai_lieu"][0]["re_ingest"] is True
    assert anh["tai_lieu"][0]["trang_thai"] == TRANG_THAI_DA_NAP


def test_khong_doi_hien_nguyen_trang_thai(client, monkeypatch):
    def than(lan, quet):
        _xong(lan, quet, [TrangThaiTaiLieu(doc_key="a.md", trang_thai=TRANG_THAI_KHONG_DOI, re_ingest=True)])

    _gan_chay(monkeypatch, than)
    r = client.post("/api/nap", files=[_file("a.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    assert anh["tai_lieu"][0]["trang_thai"] == TRANG_THAI_KHONG_DOI


def test_khong_co_fact_mang_ma_va_ly_do_dot_van_xong(client, monkeypatch):
    def than(lan, quet):
        _xong(
            lan,
            quet,
            [
                TrangThaiTaiLieu(
                    doc_key="a.md",
                    trang_thai=TRANG_THAI_LOI,
                    ma=MA_KHONG_CO_FACT,
                    ly_do="LLM trả 0 bản ghi; phần đã ghi trong đợt được dọn",
                    so_fact_loai=0,
                    bat_dau="2026-09-02T10:00:00+00:00",
                    ket_thuc="2026-09-02T10:00:10+00:00",
                ),
                TrangThaiTaiLieu(doc_key="b.md", trang_thai=TRANG_THAI_DA_NAP, so_hyperedge=2),
            ],
        )

    _gan_chay(monkeypatch, than)
    r = client.post("/api/nap", files=[_file("a.md"), _file("b.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    assert anh["trang_thai"] == TRANG_THAI_DOT_XONG
    assert anh["tai_lieu"][0]["ma"] == MA_KHONG_CO_FACT and anh["tai_lieu"][0]["ly_do"]


# --- Hàng "đối chiếu lệch" ----------------------------------------------------


def test_doi_chieu_lech_dot_loi_hien_ma_va_phan_da_tieu(client, monkeypatch):
    def than(lan, quet):
        lan.ket_qua.tai_lieu.append(
            TrangThaiTaiLieu(
                doc_key="a.md",
                trang_thai=TRANG_THAI_LOI,
                ma=StoreKeyMismatch.code,
                ly_do="khóa lệch ở vân tay 1a2b3c",
                bat_dau="2026-09-02T10:00:00+00:00",
                ket_thuc="2026-09-02T10:00:20+00:00",
            )
        )
        lan.trang_thai = TRANG_THAI_DOT_LOI
        lan.ma_loi = StoreKeyMismatch.code
        lan.thong_diep_loi = "khóa lệch ở vân tay 1a2b3c"
        lan.ket_thuc = "2026-09-02T10:00:20+00:00"
        lan.chi_phi = TongChiPhi(1, 500, 100, 0.0006, ())

    _gan_chay(monkeypatch, than)
    r = client.post("/api/nap", files=[_file("a.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    assert anh["trang_thai"] == TRANG_THAI_DOT_LOI
    assert anh["ma_loi"] == "STORE_KEY_MISMATCH"
    assert anh["doi_chieu"]["sach"] is False and anh["doi_chieu"]["ma"] == "STORE_KEY_MISMATCH"
    assert anh["chi_phi"]["chi_phi_usd"] == pytest.approx(0.0006)


def test_dot_xong_sach_thi_khoi_doi_chieu_bao_sach(client, monkeypatch):
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("a.md")])
    anh = _cho_xong(client, r.json()["dot_id"])
    assert anh["doi_chieu"] == {"sach": True, "so_tai_lieu": 1, "ma": None, "thong_diep": ""}


# --- Hàng "đợt đang chạy", "tải lại trang", "poll id lạ" ----------------------


def _gan_chay_treo(monkeypatch):
    """Đợt không bao giờ xong: trạng thái `dang_chay` quan sát được tất định."""

    async def chay_lan_nap(quet, *, space, policy_version, audit, lan, ep_ghi_de=False):
        lan.ket_qua.tu_choi.extend(quet.tu_choi)
        for t in quet.chap_nhan:
            lan.ket_qua.tai_lieu.append(
                TrangThaiTaiLieu(doc_key=t.doc_key, trang_thai=TRANG_THAI_LOI, bat_dau="2026-09-02T10:00:00+00:00")
            )
            break  # tài liệu đầu đang chạy, các tài liệu sau chưa tới lượt
        await asyncio.Event().wait()
        return lan

    monkeypatch.setattr(mod, "chay_lan_nap", chay_lan_nap)


def test_dot_dang_chay_thi_post_lan_hai_tra_409(client, monkeypatch):
    _gan_chay_treo(monkeypatch)
    r1 = client.post("/api/nap", files=[_file("a.md")])
    assert r1.status_code == 201
    r2 = client.post("/api/nap", files=[_file("b.md")])
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "DOT_DANG_CHAY"
    # Đợt đang chạy không bị đụng.
    assert client.get("/api/dot/moi-nhat").json()["dot_id"] == r1.json()["dot_id"]


def test_tai_lai_trang_bam_lai_dot_dang_chay(client, monkeypatch):
    _gan_chay_treo(monkeypatch)
    r = client.post("/api/nap", files=[_file("a.md"), _file("b.md")])
    moi = client.get("/api/dot/moi-nhat")
    assert moi.status_code == 200
    anh = moi.json()
    # Hàng matrix "tải lại trang giữa chừng": phủ ở mức ảnh chụp - `moi-nhat`
    # trả *đúng đợt đang chạy*, thứ mà trang tải lại sẽ bám vào.
    assert anh["dot_id"] == r.json()["dot_id"]
    assert anh["trang_thai"] == mod.TRANG_THAI_DOT_DANG_CHAY
    # Tài liệu đang xử lý có chỉ báo đang chạy, không ô nào trắng đơ.
    assert anh["tai_lieu"][0]["dang_chay"] is True
    assert anh["tai_lieu"][0]["ma"] is None


def test_hong_truoc_khi_chay_thi_dot_khong_ket_o_dang_chay(client, monkeypatch):
    """Chỗ đã giữ phải trả lại: một lỗi giữa POST và task nền không được khóa màn.

    Cửa 409 giữ chỗ *trước* khi đọc file (không có `await` xen giữa phép kiểm
    và phép giữ), nên nếu bước sau đó nổ thì đợt vừa giữ phải chuyển sang `loi`,
    không thì mọi lần nạp sau đều 409 cho tới khi restart tiến trình.
    """
    _gan_chay(monkeypatch, _xong)
    monkeypatch.setattr(mod, "load_policy", _no_bang_gia)
    r = client.post("/api/nap", files=[_file("a.md")])
    # Theo hợp đồng `{error: {code, message}}`, không phải một 500 trần: JS đọc
    # `d.error.code` nên một thân không phải JSON làm trang vỡ ở `r.json()`.
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "RuntimeError"
    assert "bảng chính sách hỏng" in r.json()["error"]["message"]

    hong = client.get("/api/dot/moi-nhat").json()
    assert hong["trang_thai"] == TRANG_THAI_DOT_LOI and hong["ma_loi"] == "RuntimeError"
    # Và màn nạp tiếp được ngay, không cần restart.
    monkeypatch.undo()
    _gan_chay(monkeypatch, _xong)
    r = client.post("/api/nap", files=[_file("b.md")])
    assert r.status_code == 201


def test_chay_nen_bi_huy_thi_dot_khong_ket_o_dang_chay(monkeypatch):
    """Tắt tiến trình màn: `CancelledError` phải lan tiếp, đợt không kẹt `dang_chay`.

    Nuốt nó là chặn phép hủy lan lên (`asyncio.run` treo lúc tắt) và ghi một
    đợt `loi` giả cho một thứ không hỏng.
    """
    a = AuditGia()

    async def mo_audit():
        return a

    async def treo(*args, **kw):
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "mo_audit", mo_audit)
    monkeypatch.setattr(mod, "chay_lan_nap", treo)
    lan = mod.LanNap(space="synth")

    async def chay():
        t = asyncio.create_task(
            mod._chay_nen(lan, KetQuaQuet(), policy_version="pv", ep_ghi_de=False)
        )
        await asyncio.sleep(0)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(chay())
    assert lan.trang_thai == TRANG_THAI_DOT_LOI
    assert lan.ma_loi == MA_DOT_BI_HUY
    assert lan.dang_chay() is False
    # `finally` vẫn chạy: port audit của đợt bị hủy không được để hở.
    assert a.da_dong is True


def test_task_nen_duoc_giu_tham_chieu_manh(client, monkeypatch):
    """`asyncio` chỉ giữ tham chiếu yếu tới task đang chạy; đợt bị thu gom là đợt biến mất."""
    _gan_chay_treo(monkeypatch)
    client.post("/api/nap", files=[_file("a.md")])
    assert len(mod.QUAN_LY._task) == 1


def test_doi_chieu_chua_co_ket_luan_khi_dot_con_chay(client, monkeypatch):
    """Đợt vừa bắt đầu không được nói "sạch trên 0 tài liệu".

    Tính đúng đắn của khối 4 phải nằm trong JSON: để `sach` là `True` lúc đợt
    còn chạy thì nó chỉ đúng nhờ một nhánh JavaScript không có test nào chạy vào.
    """
    _gan_chay_treo(monkeypatch)
    r = client.post("/api/nap", files=[_file("a.md")])
    anh = client.get(f"/api/dot/{r.json()['dot_id']}").json()
    assert anh["trang_thai"] == mod.TRANG_THAI_DOT_DANG_CHAY
    assert anh["doi_chieu"]["sach"] is None


def test_moi_nhat_khi_chua_co_dot_nao_la_404(client):
    r = client.get("/api/dot/moi-nhat")
    assert r.status_code == 404 and r.json()["error"]["code"] == "DOT_KHONG_CO"


def test_poll_id_la_tra_404_co_ma(client):
    r = client.get("/api/dot/khong-co")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "DOT_KHONG_CO"


def test_dot_cu_van_tra_ve_duoc_sau_khi_dot_moi_chay(client, monkeypatch):
    _gan_chay(monkeypatch, _xong)
    a = client.post("/api/nap", files=[_file("a.md")]).json()["dot_id"]
    _cho_xong(client, a)
    b = client.post("/api/nap", files=[_file("b.md")]).json()["dot_id"]
    _cho_xong(client, b)
    assert client.get(f"/api/dot/{a}").status_code == 200
    assert client.get("/api/dot/moi-nhat").json()["dot_id"] == b


def test_so_dot_trong_bo_nho_co_tran(client, monkeypatch):
    """Tiến trình màn sống lâu; sổ đợt không có trần là một chỗ rò bộ nhớ."""
    _gan_chay(monkeypatch, _xong)
    for _ in range(mod.TRAN_SO_DOT + 3):
        _cho_xong(client, client.post("/api/nap", files=[_file("a.md")]).json()["dot_id"])
    assert len(mod.QUAN_LY.cac_dot) == mod.TRAN_SO_DOT


# --- Không có đường nào ngoài ba endpoint ------------------------------------


def test_man_khong_co_endpoint_hoi_dap_hay_xoa(client):
    duong = {(r.path, tuple(sorted(r.methods))) for r in mod.app.routes if hasattr(r, "methods")}
    assert duong == {
        ("/", ("GET",)),
        ("/api/nap", ("POST",)),
        ("/api/dot/moi-nhat", ("GET",)),
        ("/api/dot/{dot_id}", ("GET",)),
    }
