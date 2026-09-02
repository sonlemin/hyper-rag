"""Bộ quét thư mục nguồn của pipeline ingest (story 2.3, hàng "Quét thư mục").

Viết trước cơ chế (FR-27). Bộ quét là hàm thuần trong `core/` (chỉ stdlib):
nhận `.md`/`.txt` UTF-8 có nội dung và có frontmatter `scope`/`content_type`,
từ chối mọi thứ khác kèm tên file và mã lý do. Một file hỏng không chặn file
kế: quét là gom kết quả, không ném.

Fixture `tests/fixtures/corpus_2_3/`: 3 file hợp lệ (2 `.md` + 1 `.txt`, hai
scope) và 4 file hỏng, mỗi file hỏng đúng một mã lý do.
"""

from pathlib import Path

import pytest

from core.ingest_scan import (
    DUOI_HOP_LE,
    KICH_THUOC_TOI_DA,
    MA_DINH_DANG_LA,
    MA_FILE_RONG,
    MA_KHONG_DOC_DUOC,
    MA_KHONG_PHAI_UTF8,
    MA_QUA_LON,
    MA_THIEU_METADATA,
    KetQuaQuet,
    TaiLieuNguon,
    TuChoi,
    quet_cac_file,
    quet_thu_muc,
    tach_frontmatter,
)

CORPUS = Path(__file__).resolve().parent / "fixtures" / "corpus_2_3"


def test_quet_thu_muc_chap_nhan_ba_file_theo_thu_tu_ten():
    """3 file hợp lệ theo thứ tự tên, mỗi cái mang scope/content_type từ frontmatter."""
    kq = quet_thu_muc(CORPUS)
    assert isinstance(kq, KetQuaQuet)
    assert [t.doc_key for t in kq.chap_nhan] == [
        "01-runbook-app01.md",
        "02-su-co-inc-1208.md",
        "03-runbook-khach-hang-a.txt",
    ]
    nhan = {(t.scope, t.content_type) for t in kq.chap_nhan}
    assert nhan == {("noi_bo", "runbook"), ("noi_bo", "bao_cao_su_co"), ("khach_hang_a", "runbook")}
    for t in kq.chap_nhan:
        assert isinstance(t, TaiLieuNguon)
        # Nội dung là phần thân, không mang frontmatter: frontmatter mà lọt vào
        # `ainsert` thì LLM trích "scope" thành một entity.
        assert "scope:" not in t.noi_dung and "---" not in t.noi_dung
        assert t.noi_dung.strip()


def test_quet_thu_muc_tu_choi_bon_file_kem_ten_va_ma():
    """4 từ chối, mỗi cái đúng mã; không im lặng, không ném."""
    kq = quet_thu_muc(CORPUS)
    theo_ten = {tc.ten: tc for tc in kq.tu_choi}
    assert set(theo_ten) == {
        "04-tai-lieu.pdf",
        "05-file-rong.md",
        "06-thieu-frontmatter.md",
        "07-khong-utf8.txt",
    }
    assert theo_ten["04-tai-lieu.pdf"].ma == MA_DINH_DANG_LA
    assert theo_ten["05-file-rong.md"].ma == MA_FILE_RONG
    assert theo_ten["06-thieu-frontmatter.md"].ma == MA_THIEU_METADATA
    assert theo_ten["07-khong-utf8.txt"].ma == MA_KHONG_PHAI_UTF8
    for tc in kq.tu_choi:
        assert isinstance(tc, TuChoi)
        assert tc.ly_do.strip(), "mỗi từ chối phải nói lý do bằng lời"


def test_ma_ly_do_on_dinh():
    """Mã là hợp đồng cho màn web 2.7 và test: assert trên mã, không trên thông điệp."""
    assert (MA_DINH_DANG_LA, MA_FILE_RONG, MA_THIEU_METADATA, MA_KHONG_PHAI_UTF8) == (
        "DINH_DANG_LA",
        "FILE_RONG",
        "THIEU_METADATA",
        "KHONG_PHAI_UTF8",
    )
    assert set(DUOI_HOP_LE) == {".md", ".txt"}


def test_tach_frontmatter_hai_nhanh():
    """Có frontmatter thì tách ra map + thân; không có thì map rỗng, thân nguyên."""
    meta, than = tach_frontmatter("---\nscope: noi_bo\ncontent_type: runbook\n---\nThân.\n")
    assert meta == {"scope": "noi_bo", "content_type": "runbook"}
    assert than == "Thân.\n"
    meta2, than2 = tach_frontmatter("Không có frontmatter.")
    assert meta2 == {} and than2 == "Không có frontmatter."


@pytest.mark.parametrize(
    "noi_dung,ma",
    [
        ("---\nscope: noi_bo\n---\nThân.", MA_THIEU_METADATA),
        ("---\ncontent_type: runbook\n---\nThân.", MA_THIEU_METADATA),
        ("---\nscope: noi_bo\ncontent_type:   \n---\nThân.", MA_THIEU_METADATA),
        # Dấu phân tách khóa lọc trong giá trị: khóa `a:b:c` tách sai.
        ("---\nscope: noi:bo\ncontent_type: runbook\n---\nThân.", MA_THIEU_METADATA),
        # Frontmatter đủ nhưng thân rỗng: không có gì để nạp.
        ("---\nscope: noi_bo\ncontent_type: runbook\n---\n   \n", MA_FILE_RONG),
        # File chỉ có khoảng trắng.
        ("   \n\n", MA_FILE_RONG),
    ],
    ids=["thieu_content_type", "thieu_scope", "content_type_rong", "co_dau_phan_tach", "than_rong", "toan_khoang_trang"],
)
def test_tu_choi_theo_noi_dung(tmp_path, noi_dung, ma):
    f = tmp_path / "a.md"
    f.write_text(noi_dung, encoding="utf-8")
    kq = quet_cac_file([f])
    assert kq.chap_nhan == ()
    assert [tc.ma for tc in kq.tu_choi] == [ma]
    assert kq.tu_choi[0].ten == "a.md"


def test_quet_thu_muc_bo_qua_thu_muc_con_va_khong_de_quy(tmp_path):
    """Chỉ file ngay trong thư mục; thư mục con không quét, không ném."""
    (tmp_path / "con").mkdir()
    (tmp_path / "con" / "x.md").write_text("---\nscope: a\ncontent_type: b\n---\nx", encoding="utf-8")
    (tmp_path / "y.txt").write_text("---\nscope: a\ncontent_type: b\n---\ny", encoding="utf-8")
    kq = quet_thu_muc(tmp_path)
    assert [t.doc_key for t in kq.chap_nhan] == ["y.txt"]
    assert kq.tu_choi == ()


def test_thu_muc_khong_ton_tai_la_loi():
    """Thư mục sai đường dẫn là lỗi của người gọi, không phải "0 tài liệu"."""
    with pytest.raises(FileNotFoundError):
        quet_thu_muc(CORPUS / "khong-co")


def test_khong_import_ngoai_stdlib():
    """`core/ingest_scan.py` chỉ stdlib - import-lint canh, ghim thêm ở đây để rõ ý."""
    import ast
    import sys

    nguon = (Path(__file__).resolve().parent.parent / "core" / "ingest_scan.py").read_text(encoding="utf-8")
    goc = set()
    for node in ast.walk(ast.parse(nguon)):
        if isinstance(node, ast.Import):
            goc |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            goc.add(node.module.split(".")[0])
    assert goc <= set(sys.stdlib_module_names) | {"core"}, goc


# --- Vòng review đối kháng 02/09/2026 ------------------------------------------


def test_file_khong_co_quyen_doc_la_khong_doc_duoc(tmp_path):
    import os

    if os.geteuid() == 0:
        pytest.skip("root đọc được mọi file")
    f = tmp_path / "a.md"
    f.write_text("---\nscope: a\ncontent_type: b\n---\nx", encoding="utf-8")
    f.chmod(0)
    try:
        kq = quet_cac_file([f])
    finally:
        f.chmod(0o644)
    assert [tc.ma for tc in kq.tu_choi] == [MA_KHONG_DOC_DUOC]


def test_bom_utf8_duoc_nhan(tmp_path):
    f = tmp_path / "a.md"
    f.write_bytes(b"\xef\xbb\xbf---\nscope: noi_bo\ncontent_type: runbook\n---\nTh\xc3\xa2n.\n")
    kq = quet_cac_file([f])
    assert kq.tu_choi == () and kq.chap_nhan[0].scope == "noi_bo" and kq.chap_nhan[0].noi_dung.strip() == "Thân."


@pytest.mark.parametrize("gia_tri", ['"noi_bo"', "'noi_bo'", "  \"noi_bo\"  "])
def test_gia_tri_frontmatter_co_nhay_duoc_bo_nhay(tmp_path, gia_tri):
    f = tmp_path / "a.md"
    f.write_text(f"---\nscope: {gia_tri}\ncontent_type: 'runbook'\n---\nx", encoding="utf-8")
    kq = quet_cac_file([f])
    assert kq.tu_choi == ()
    assert (kq.chap_nhan[0].scope, kq.chap_nhan[0].content_type) == ("noi_bo", "runbook")


def test_file_qua_lon_bi_tu_choi_truoc_khi_doc(tmp_path, monkeypatch):
    f = tmp_path / "a.md"
    f.write_bytes(b"---\nscope: a\ncontent_type: b\n---\n" + b"x" * (KICH_THUOC_TOI_DA + 1))
    goc = Path.read_bytes

    def khong_duoc_doc(self):
        raise AssertionError("file quá lớn phải bị chặn bằng stat, không được đọc")

    monkeypatch.setattr(Path, "read_bytes", khong_duoc_doc)
    try:
        kq = quet_cac_file([f])
    finally:
        monkeypatch.setattr(Path, "read_bytes", goc)
    assert [tc.ma for tc in kq.tu_choi] == [MA_QUA_LON]
    assert (MA_QUA_LON, MA_KHONG_DOC_DUOC) == ("QUA_LON", "KHONG_DOC_DUOC")
