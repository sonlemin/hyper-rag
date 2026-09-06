"""Thí nghiệm CT-03: phần thuần có test, phần chạm kho mang marker `neo4j`.

Cùng luật mà story 2.9 đặt cho `eval/chup_do_thi.py`: mọi thứ suy được từ ảnh
chụp là hàm thuần và chạy trong bộ test mặc định; chỉ lời gọi `get_node` thật
mới cần container, và nó nằm sau `pytest.mark.neo4j` để `uv run pytest` vẫn
xanh trên máy không có stack.

Ba nhóm assert:

- **Tìm entity đa nguồn** - hàm thuần trên ảnh chụp, gồm hàng "CT-03 không vật
  liệu" của I/O Matrix.
- **Đọc mô tả** - cửa cờ hệ thống dội lỗi *trước* lời gọi kho đầu tiên, và phép
  đếm mảnh mô tả.
- **Trang** - hình dạng HTML dựng từ kết quả đã đọc, không cần kho.
"""

import asyncio
import os
from pathlib import Path

import pytest

from adapters.ingest_labels import IngestOutsideSystemContext
from core.permission import use_context
from core.system_context import system_context
from eval.cau_hoi import AnhDoThi, HyperedgeAnh, TaiLieuAnh, doc_anh_do_thi
from eval.ct03 import (
    GRAPH_FIELD_SEP,
    SPACE_GHI_TRONG_REPO,
    EntityDaNguon,
    KhongCoVatLieu,
    MoTaEntity,
    dem_manh,
    doc_mo_ta,
    dung_html,
    duong_dan_html,
    entity_da_nguon,
    ly_do_tu_choi_space,
    sap_theo_bang_chung,
    thieu_bien_moi_truong,
    thong_ke,
)
from tests.ngu_canh import vai

GOC_REPO = Path(__file__).resolve().parent.parent
ANH_SYNTH = GOC_REPO / "eval" / "anh_do_thi" / "synth.json"

# Số khóa đếm trên `eval/anh_do_thi/synth.json` ngày 05/09/2026, sau đợt nạp
# lại `9c4a1ba7` của story 2.12 (số cũ của story 2.10 là **46**). Viết tay: 0
# entity đa nguồn nghĩa là CT-03 không có vật liệu và cả thí nghiệm mất bằng
# chứng, nên số này phải có chỗ đỏ khi một lần nạp lại làm nó tụt.
#
# Nó **tăng** 46 -> 56, và một phần của mức tăng đọc được thẳng: chuẩn hóa bí
# danh gộp ba cách viết của App01 về một id, nên `App01` nay là một entity đa
# nguồn (`k1-01`, `k1-02`, `k1-08`, `k1-09`) thay vì ba entity mỗi cái một tài
# liệu. Phần còn lại là hai tài liệu corpus mới cộng dao động của một lần chạy.
SYNTH_ENTITY_DA_NGUON = 56

# Ba ca mở trang CT-03, viết **một** lần và dùng ở cả hai test chấm thứ tự.
# Trước story 2.12 chúng được chép hai bản: một trong test chạy trên ảnh chụp
# (chạy ở mọi máy) và một trong test chạy trên Neo4j thật (chỉ chạy trên máy
# chủ, marker `neo4j`). Đợt nạp lại 05/09 đổi thứ tự, bản chạy trên dev được
# sửa còn bản kia thì không, và cả suốt vẫn xanh trên máy dev - CI trên máy chủ
# mới bắt. Một hằng dùng chung là chỗ duy nhất chặn được kiểu trôi đó.
#
# Thứ tự này đổi ở đợt nạp lại 05/09: `Trần Thị Hạnh` lên hạng vì `k1-08` và
# `k1-09` (hai tài liệu bí danh) cùng nêu tên bà, nên bà thành entity đa nguồn
# 5 tài liệu. Số của story 2.10 là ["nhóm Hạ tầng", "cảnh báo mức nghiêm
# trọng", "người trực"].
BA_CA_MO_TRANG_SYNTH: list[str] = [
    "cảnh báo mức nghiêm trọng",
    "Trần Thị Hạnh",
    "nhóm Hạ tầng",
]

# 19 entity mà khóa quyền hợp nhất thành **không khóa** (khác scope, AD-5) và 6
# entity mang vai `time`, đọc từ kho ngày 05/09/2026 bằng `eval.ct03` trên máy
# chủ. Chép vào đây để test thứ tự chạy được mà không cần container; bản trên
# kho thật do test marker `neo4j` canh.
KHAC_SCOPE_SYNTH: frozenset[str] = frozenset(
    {
        "12/08/2026 lúc 09:20",
        "INC-1208",
        "SOP-12",
        "Trần Thị Hạnh",
        "cảnh báo",
        "cảnh báo mức nghiêm trọng",
        "dịch vụ",
        "gửi ra ngoài phải có phê duyệt của Giám đốc Kỹ thuật",
        "hệ giám sát",
        "lưu trong kho khóa Vault",
        "mỗi 90 ngày",
        "mỗi tháng",
        "người trực",
        "người vận hành",
        "nhóm Hạ tầng",
        "trang thanh toán của App01",
        "trả giới hạn bộ nhớ PHP-FPM về mức cũ rồi nạp lại cấu hình theo SOP-12",
        "tài liệu hạn chế",
        "được xoay vòng bằng tác vụ tự động của Vault",
    }
)
TIME_SYNTH: frozenset[str] = frozenset(
    {
        "12 tháng",
        "12/08/2026 lúc 09:20",
        "2 ngày làm việc",
        "mỗi 90 ngày",
        "mỗi tháng",
        "từ ngày 27/07",
    }
)

# Mười ca **bằng chứng yếu** trên `synth`: năm mốc thời gian, cộng năm chuỗi là
# *câu* chứ không phải tên thực thể. Khóa cả tập để luật yếu không âm thầm rộng
# ra (hạ nhầm thực thể thật khỏi đầu trang) hay hẹp lại (để câu mệnh lệnh mở
# trang).
#
# **Không phải `TIME_SYNTH | {...}`**, và chỗ khác nhau đáng đọc: `mỗi tháng`
# mang `entity_type` là `time` trên node, nhưng `la_gia_tri_yeu` đọc **vai
# trong ảnh chụp** trước - và ở đó `mỗi tháng` còn điền một vai khác, nên nó
# không yếu. `entity_type` của node là giá trị của lần ghi cuối, không phải một
# tổng kết; viết `TIME_SYNTH | ...` là để một luật đã có tên bị thay bằng một
# xấp xỉ của nó.
YEU_SYNTH: frozenset[str] = frozenset(
    {
        "12 tháng",
        "12/08/2026 lúc 09:20",
        "2 ngày làm việc",
        "mỗi 90 ngày",
        "từ ngày 27/07",
        "gửi ra ngoài phải có phê duyệt của Giám đốc Kỹ thuật",
        "gửi tới hộp thư của nhóm Tích hợp cũ",
        "phải bổ sung phiếu thay đổi trong 24 giờ kể từ khi dịch vụ phục hồi",
        "trả giới hạn bộ nhớ PHP-FPM về mức cũ rồi nạp lại cấu hình theo SOP-12",
        "được xoay vòng bằng tác vụ tự động của Vault",
    }
)


def _he(id_he, doc_key, slots, khoa="noi_bo:runbook") -> HyperedgeAnh:
    return HyperedgeAnh(
        id=id_he,
        doc_key=tuple(doc_key),
        khoa=khoa,
        slots={vai_slot: tuple(gt) for vai_slot, gt in slots.items()},
    )


def _anh(hyperedge, tai_lieu=(("a.md", "noi_bo", "runbook"),), space="thu") -> AnhDoThi:
    return AnhDoThi(
        version=2,
        space=space,
        ngay_do="2026-09-04T00:00:00+00:00",
        policy_version="x" * 8,
        tai_lieu=tuple(
            TaiLieuAnh(doc_key=d, sha256="0" * 64, scope=s, content_type=c)
            for d, s, c in tai_lieu
        ),
        hyperedge=tuple(hyperedge),
    )


class _GraphGia:
    """`get_node` giả: trả đúng dict mà adapter trả dưới cờ hệ thống, hoặc `None`."""

    def __init__(self, theo_ten):
        self.theo_ten = theo_ten
        self.da_hoi: list[str] = []

    async def get_node(self, node_id):
        self.da_hoi.append(node_id)
        return self.theo_ten.get(node_id)


# ---------------------------------------------------------------------------
# Tìm entity đa nguồn: hàm thuần
# ---------------------------------------------------------------------------


def test_entity_o_hai_tai_lieu_la_da_nguon():
    ds = entity_da_nguon(
        _anh(
            [
                _he("h1", ["a.md"], {"subject": ["App01"], "cause": ["x"]}),
                _he("h2", ["b.md"], {"subject": ["App01"], "symptom": ["y"]}),
            ]
        )
    )
    assert [e.ten for e in ds] == ["App01"]
    e = ds[0]
    assert e.doc_key == ("a.md", "b.md")
    assert e.hyperedge == ("h1", "h2")
    assert e.vai == ("subject",)
    assert e.so_nguon == 2
    assert dict(e.hyperedge_theo_doc_key) == {"a.md": ("h1",), "b.md": ("h2",)}


def test_entity_chi_o_mot_tai_lieu_khong_tinh():
    """Nhiều hyperedge trong **cùng** một tài liệu không phải đa nguồn.

    Chiều mà CT-03 hỏi là nguồn, không phải số fact: mô tả gộp từ hai fact của
    cùng một tài liệu không băng qua ranh giới quyền nào.
    """
    with pytest.raises(KhongCoVatLieu) as loi:
        entity_da_nguon(
            _anh(
                [
                    _he("h1", ["a.md"], {"subject": ["App01"]}),
                    _he("h2", ["a.md"], {"subject": ["App01"], "cause": ["z"]}),
                ]
            )
        )
    assert loi.value.code == "CT03_KHONG_VAT_LIEU"


def test_khong_vat_lieu_thi_tu_choi_ca_dot_khong_dung_trang_rong():
    """Hàng "CT-03 không vật liệu" của I/O Matrix."""
    with pytest.raises(KhongCoVatLieu) as loi:
        entity_da_nguon(_anh([_he("h1", ["a.md"], {"subject": ["chi-mot"]})]))
    assert "không dựng trang" in str(loi.value)


def test_hyperedge_da_nguon_cung_dem_moi_doc_key():
    """Một hyperedge gắn hai `doc_key` thì entity của nó là đa nguồn ngay lập tức."""
    ds = entity_da_nguon(_anh([_he("h1", ["a.md", "b.md"], {"subject": ["chung"]})]))
    assert ds[0].doc_key == ("a.md", "b.md")
    assert dict(ds[0].hyperedge_theo_doc_key) == {"a.md": ("h1",), "b.md": ("h1",)}


def test_ket_qua_sap_xep_on_dinh():
    """Chạy lại cho cùng kết quả: trang là bằng chứng, nó không được đổi thứ tự mỗi lần."""
    anh = _anh(
        [
            _he("h2", ["b.md"], {"subject": ["Zed"], "cause": ["App01"]}),
            _he("h1", ["a.md"], {"subject": ["App01"], "cause": ["Zed"]}),
        ]
    )
    a = entity_da_nguon(anh)
    b = entity_da_nguon(anh)
    assert a == b
    assert [e.ten for e in a] == ["App01", "Zed"]
    assert a[0].vai == ("cause", "subject")


def test_anh_chup_synth_co_vat_lieu_cho_ct03():
    """AC: graph `synth` phải có entity đa nguồn, nếu không thí nghiệm mất bằng chứng."""
    ds = entity_da_nguon(doc_anh_do_thi(ANH_SYNTH))
    assert len(ds) == SYNTH_ENTITY_DA_NGUON
    assert any(e.so_nguon >= 3 for e in ds), "cần ít nhất một entity ở ba tài liệu"
    ten = {e.ten for e in ds}
    assert "App01" in ten and "INC-1208" in ten


# ---------------------------------------------------------------------------
# Đọc mô tả: cửa cờ hệ thống và phép đếm mảnh
# ---------------------------------------------------------------------------


def test_dem_manh_theo_dau_ghep_cua_upstream():
    assert GRAPH_FIELD_SEP == "<SEP>"
    assert dem_manh(None) == 0
    assert dem_manh("") == 0
    assert dem_manh("một mảnh") == 1
    assert dem_manh(f"a{GRAPH_FIELD_SEP}b{GRAPH_FIELD_SEP}c") == 3
    assert dem_manh(f"a{GRAPH_FIELD_SEP}   {GRAPH_FIELD_SEP}b") == 2


def test_doc_mo_ta_ngoai_co_he_thong_la_loi_khong_phai_rong(policy):
    """Hàng "CT-03 chạy ngoài cờ system" của I/O Matrix.

    Dưới ngữ cảnh vai người dùng, `get_node` không có khóa để đọc và trả `None`
    cho mọi id, tức trang sẽ dựng ra một danh sách "không tìm thấy" thay vì nói
    lời gọi sai ngữ cảnh. Cửa phải dội **trước** lời gọi kho đầu tiên.
    """
    graph = _GraphGia({"App01": {"description": "x"}})
    e = EntityDaNguon(
        ten="App01",
        doc_key=("a.md", "b.md"),
        hyperedge=("h1", "h2"),
        vai=("subject",),
        hyperedge_theo_doc_key={"a.md": ("h1",), "b.md": ("h2",)},
    )
    with use_context(vai(policy, "devops", "thu")):
        with pytest.raises(IngestOutsideSystemContext) as loi:
            asyncio.run(doc_mo_ta([e], graph))
    # Assert trên `code`, không trên chuỗi thông điệp (AD-8, khoản ledger 2.10
    # trả ở story 3.3): một phép kiểm `"CT-03" in str(...)` vỡ khi ai đó sửa câu
    # chữ, và nó không phân biệt được hai ngoại lệ cùng nhắc tên thí nghiệm.
    assert loi.value.code == "INGEST_OUTSIDE_SYSTEM_CONTEXT"
    assert graph.da_hoi == [], "không được chạm kho trước khi kiểm ngữ cảnh"


def _entity(ten="App01", vai_slot=("subject",)) -> EntityDaNguon:
    return EntityDaNguon(
        ten=ten,
        doc_key=("a.md", "b.md"),
        hyperedge=("h1", "h2"),
        vai=tuple(vai_slot),
        hyperedge_theo_doc_key={"a.md": ("h1",), "b.md": ("h2",)},
    )


def test_doc_mo_ta_duoi_co_he_thong_tra_nguyen_van():
    """Bốn trường của node hợp nhất đều ra nguyên văn dưới cờ hệ thống."""
    graph = _GraphGia(
        {
            "App01": {
                "description": f"mảnh A{GRAPH_FIELD_SEP}mảnh B",
                "filter_key": "khach_hang_a:runbook",
                "source_id": f"chunk-1{GRAPH_FIELD_SEP}chunk-2{GRAPH_FIELD_SEP}chunk-3",
                "entity_type": "subject",
            }
        }
    )
    with use_context(system_context(space="thu", policy_version="v")):
        ds = asyncio.run(doc_mo_ta([_entity()], graph))
    assert len(ds) == 1
    m = ds[0]
    assert m.mo_ta == f"mảnh A{GRAPH_FIELD_SEP}mảnh B"
    assert m.so_manh == 2
    assert m.so_chunk_nguon == 3
    assert m.khoa == "khach_hang_a:runbook"
    assert m.loai == "subject"
    assert not m.thieu_trong_graph and not m.mo_ta_rong
    assert m.gop_da_nguon


def test_mo_ta_rong_khac_voi_node_vang(policy):
    """Hai trạng thái phải phân biệt được: node không có, và node có mà mô tả rỗng.

    Phát hiện 04/09/2026 trên space `synth` là **mọi** node entity có
    `description` rỗng - quyết định của story 2.4, không phải một lỗ. Gộp hai
    trạng thái thành một là đọc phát hiện đó thành "ảnh chụp lệch kho", một câu
    khác hẳn.
    """
    graph = _GraphGia(
        {
            "rong": {
                "description": "",
                "filter_key": None,
                "source_id": f"chunk-1{GRAPH_FIELD_SEP}chunk-2",
                "entity_type": "source",
            }
        }
    )
    with use_context(system_context(space="thu", policy_version="v")):
        ds = asyncio.run(doc_mo_ta([_entity("rong"), _entity("mat")], graph))
    co, mat = ds
    assert co.mo_ta_rong and not co.thieu_trong_graph
    assert co.so_manh == 0
    # Mô tả rỗng nhưng `source_id` hai chunk: node vẫn là điểm hợp nhất đo được.
    assert co.gop_da_nguon and co.so_chunk_nguon == 2
    assert co.khoa is None
    assert mat.thieu_trong_graph and not mat.mo_ta_rong


def test_entity_vang_trong_graph_duoc_neu_ra_chu_khong_bo_qua():
    """Ảnh chụp và kho lệch nhau phải hiện lên, không biến mất khỏi danh sách."""
    graph = _GraphGia({})
    with use_context(system_context(space="thu", policy_version="v")):
        ds = asyncio.run(doc_mo_ta([_entity("mat")], graph))
    assert ds[0].thieu_trong_graph and ds[0].so_manh == 0
    assert not ds[0].gop_da_nguon


def test_bien_moi_truong_bat_buoc_du_ba_cai():
    thieu = thieu_bien_moi_truong({})
    assert len(thieu) == 3
    assert thieu == thieu_bien_moi_truong({k: "  " for k in thieu})
    assert thieu_bien_moi_truong({k: "x" for k in thieu}) == []


# ---------------------------------------------------------------------------
# Trang
# ---------------------------------------------------------------------------


def _mo_ta(ten, mo_ta, doc_key=("a.md", "b.md"), nguon=None, vang=False) -> MoTaEntity:
    e = EntityDaNguon(
        ten=ten,
        doc_key=tuple(doc_key),
        hyperedge=("h1", "h2"),
        vai=("subject",),
        hyperedge_theo_doc_key={dk: ("h1",) for dk in doc_key},
    )
    return MoTaEntity(
        entity=e,
        mo_ta=mo_ta,
        khoa="noi_bo:runbook",
        so_manh=dem_manh(mo_ta),
        nguon=nguon,
        so_chunk_nguon=dem_manh(nguon),
        loai="subject",
        vang_trong_graph=vang,
    )


def test_trang_liet_ke_mo_ta_va_danh_sach_nguon():
    """AC: trang liệt kê từng entity đa nguồn kèm `description` và các `doc_key`."""
    anh = _anh([_he("h1", ["a.md"], {"subject": ["App01"]})])
    trang = dung_html(anh, [_mo_ta("App01", f"nói về a{GRAPH_FIELD_SEP}nói về b")])
    assert "App01" in trang
    assert "nói về a" in trang and "nói về b" in trang
    assert "a.md" in trang and "b.md" in trang
    assert "2 mảnh mô tả" in trang
    assert trang.startswith("<!doctype html>")


def test_trang_thoat_html_trong_mo_ta():
    """Mô tả là văn bản LLM sinh; một dấu `<` trong đó không được thành thẻ."""
    anh = _anh([_he("h1", ["a.md"], {"subject": ["x"]})])
    trang = dung_html(anh, [_mo_ta("x", "<script>alert(1)</script>")])
    assert "<script>alert(1)</script>" not in trang
    assert "&lt;script&gt;" in trang


def test_trang_neu_ro_entity_vang_trong_graph():
    anh = _anh([_he("h1", ["a.md"], {"subject": ["mat"]})])
    trang = dung_html(anh, [_mo_ta("mat", None, vang=True)])
    assert "ảnh chụp và kho lệch nhau" in trang


def test_trang_noi_ra_phat_hien_mo_ta_rong_va_van_chi_ra_phep_gop():
    """Trang không được để một `description` rỗng đọc thành "không có rủi ro"."""
    anh = _anh([_he("h1", ["a.md"], {"subject": ["x"]})])
    m = _mo_ta("x", "", nguon=f"chunk-1{GRAPH_FIELD_SEP}chunk-2")
    trang = dung_html(anh, [m])
    assert "chuỗi rỗng" in trang
    assert "chưa có gì chảy qua" in trang
    assert "2 chunk nguồn" in trang
    assert "chunk-1" in trang and "chunk-2" in trang


def test_trang_goi_ten_ca_hop_nhat_khac_scope():
    """`filter_key` `None` phải đọc ra AD-5, không phải một ô trống."""
    anh = _anh([_he("h1", ["a.md"], {"subject": ["x"]})])
    m = _mo_ta("x", "")
    m = MoTaEntity(
        entity=m.entity,
        mo_ta="",
        khoa=None,
        so_manh=0,
        nguon=f"chunk-1{GRAPH_FIELD_SEP}chunk-2",
        so_chunk_nguon=2,
        loai="source",
    )
    trang = dung_html(anh, [m])
    assert "AD-5" in trang
    assert "không khóa" in trang


def test_trang_noi_vi_sao_description_doi_l2():
    """Trang là bằng chứng ĐG3: nó phải nói ra cơ chế, không chỉ trưng dữ liệu."""
    anh = _anh([_he("h1", ["a.md"], {"subject": ["x"]})])
    trang = dung_html(anh, [_mo_ta("x", "y")])
    assert "L2" in trang and "_che_mo_ta" in trang
    assert "cờ hệ thống" in trang


# ---------------------------------------------------------------------------
# Kho thật
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_doc_mo_ta_tren_neo4j_that():
    """Cùng đường mà `scripts/chay-may-chu.sh ct03` chạy, trên kho thật.

    Không nạp gì và không xóa gì: nó đọc `get_node` của những entity mà ảnh chụp
    đã commit nói là đa nguồn. Bỏ qua khi thiếu container, `fail` khi CI khai
    `NEO4J_REQUIRED` mà vẫn thiếu biến - "bỏ qua" và "chạy xanh" phải phân biệt
    được.
    """
    from adapters.engine import BIEN_MOI_TRUONG, cau_hinh_kho_tu_moi_truong
    from adapters.neo4j import NEO4J_PASSWORD_KEY, NEO4J_URI_KEY

    uri = os.environ.get(BIEN_MOI_TRUONG[NEO4J_URI_KEY])
    mat_khau = os.environ.get(BIEN_MOI_TRUONG[NEO4J_PASSWORD_KEY])
    if not uri or not mat_khau:
        if os.environ.get("NEO4J_REQUIRED"):
            pytest.fail("NEO4J_REQUIRED được đặt nhưng thiếu NEO4J_URI/NEO4J_PASSWORD")
        pytest.skip("thiếu NEO4J_URI/NEO4J_PASSWORD: bỏ qua test cần container")

    from eval.ct03 import chay

    anh = doc_anh_do_thi(ANH_SYNTH)
    ds = asyncio.run(chay(anh, anh.space, "policy-test", cau_hinh_kho_tu_moi_truong()))
    assert len(ds) == SYNTH_ENTITY_DA_NGUON
    assert not [m for m in ds if m.thieu_trong_graph], (
        "entity có trong ảnh chụp mà không có trong graph: chụp lại trước khi dùng"
        " trang CT-03 làm bằng chứng"
    )
    assert all(m.gop_da_nguon for m in ds), (
        "có entity đa nguồn theo ảnh chụp mà node của nó không là điểm hợp nhất"
        " đo được: CT-03 không có gì để chứng minh"
    )
    # Phát hiện 04/09/2026, khóa lại ở đây: `description` của **mọi** node là
    # chuỗi rỗng nên đường mà ngưỡng L2 canh chưa có gì chảy qua. Đây là quyết
    # định của story 2.4 (Design Notes: mô tả entity chỉ nhân đôi giá trị slot và
    # mở thêm một mặt rò ở L2), nay được xác nhận trên dữ liệu thật. Story 2.12
    # sinh mô tả entity thì test này đỏ, và người sửa phải đọc lại CT-03 cùng
    # khoản ledger của nó chứ không phải sửa con số.
    assert all(m.mo_ta_rong for m in ds), [m.entity.ten for m in ds if not m.mo_ta_rong]
    khac_scope = {m.entity.ten for m in ds if m.khoa is None}
    assert khac_scope == KHAC_SCOPE_SYNTH, sorted(khac_scope ^ KHAC_SCOPE_SYNTH)
    thoi_gian = {m.entity.ten for m in ds if m.loai == "time"}
    assert thoi_gian == TIME_SYNTH, sorted(thoi_gian ^ TIME_SYNTH)
    # Ba ca mở trang: cùng kỳ vọng với `test_thu_tu_tren_anh_chup_synth_that`,
    # nhưng ở đây `khoa` và `loai` đến từ kho chứ không từ hằng chép tay.
    from eval.ct03 import sap_theo_bang_chung as _sap

    assert [m.entity.ten for m in _sap(ds)][:3] == BA_CA_MO_TRANG_SYNTH


# ---------------------------------------------------------------------------
# Thứ tự của trang: mạnh nhất trước
# ---------------------------------------------------------------------------


def _m(
    ten,
    mo_ta="",
    *,
    khoa="noi_bo:runbook",
    nguon=2,
    vai=("subject",),
    loai="subject",
    vang=False,
):
    """Một `MoTaEntity` dựng tay. `nguon` là số tài liệu nguồn."""
    e = EntityDaNguon(
        ten=ten,
        doc_key=tuple(f"d{i}.md" for i in range(nguon)),
        hyperedge=("h1",),
        vai=tuple(vai),
        hyperedge_theo_doc_key={f"d{i}.md": ("h1",) for i in range(nguon)},
    )
    return MoTaEntity(
        entity=e,
        mo_ta=mo_ta,
        khoa=None if vang else khoa,
        so_manh=dem_manh(mo_ta),
        nguon=None if vang else f"c1{GRAPH_FIELD_SEP}c2",
        so_chunk_nguon=0 if vang else 2,
        loai=None if vang else loai,
        vang_trong_graph=vang,
    )


def test_ca_khac_scope_len_dau():
    """Hợp nhất thành không khóa (AD-5) là bằng chứng mạnh nhất, nên nó mở trang."""
    ds = sap_theo_bang_chung(
        [_m("bình thường"), _m("khác scope", khoa=None), _m("cũng thường")]
    )
    assert [m.entity.ten for m in ds][0] == "khác scope"


def test_nhieu_nguon_hon_dung_truoc():
    ds = sap_theo_bang_chung([_m("ít", nguon=2), _m("nhiều", nguon=6)])
    assert [m.entity.ten for m in ds] == ["nhiều", "ít"]


def test_nhieu_vai_hon_dung_truoc_khi_bang_nguon():
    ds = sap_theo_bang_chung(
        [
            _m("một vai", nguon=3, vai=("subject",)),
            _m("hai vai", nguon=3, vai=("subject", "symptom")),
        ]
    )
    assert [m.entity.ten for m in ds] == ["hai vai", "một vai"]


def test_moc_thoi_gian_va_so_thuan_xuong_cuoi():
    """Kể cả khi nó hợp nhất thành không khóa.

    Đây là tầng ngoài cùng chứ không phải tầng trong: một mốc thời gian hợp nhất
    thành không khóa vẫn là một mốc thời gian, và để nó mở trang là mất chỗ mạnh
    nhất của bằng chứng ĐG3. Trang cũ mở bằng "12 tháng" và "12/08/2026 lúc
    09:20" đúng vì luật này chưa có.
    """
    ds = sap_theo_bang_chung(
        [
            _m("12/08/2026 lúc 09:20", khoa=None, nguon=3, vai=("time",), loai="time"),
            _m("12 tháng", vai=("time",), loai="time"),
            _m("300", vai=("condition",), loai="condition"),
            _m("thực thể thường", nguon=2),
        ]
    )
    ten = [m.entity.ten for m in ds]
    assert ten[0] == "thực thể thường"
    assert set(ten[1:]) == {"12/08/2026 lúc 09:20", "12 tháng", "300"}
    assert ten[1] == "12/08/2026 lúc 09:20", "trong nhóm yếu vẫn giữ đúng bốn tầng"


def test_thu_tu_on_dinh_giua_hai_lan_chay():
    ds = [_m("b", nguon=3), _m("a", nguon=3), _m("c", nguon=3)]
    assert sap_theo_bang_chung(ds) == sap_theo_bang_chung(list(reversed(ds)))


def test_khong_ca_nao_bi_loai_khoi_trang():
    """Sắp lại, không lọc: loại ca yếu là chọn dữ liệu cho đẹp."""
    ds = [_m("12 tháng", loai="time"), _m("x", khoa=None), _m("y")]
    assert len(sap_theo_bang_chung(ds)) == 3


def test_trang_sap_lai_va_noi_ra_luat_sap():
    anh = _anh([_he("h1", ["a.md"], {"subject": ["x"]})])
    trang = dung_html(anh, [_m("12 tháng", loai="time"), _m("nhóm Hạ tầng", khoa=None, nguon=6)])
    assert trang.index("nhóm Hạ tầng") < trang.index("12 tháng")
    assert "sức nặng của bằng chứng" in trang
    assert "Không ca nào bị loại" in trang


def test_thu_tu_tren_anh_chup_synth_that():
    """Ba ca mở trang trên dữ liệu thật, khóa bằng tên.

    Kỳ vọng viết tay: một test chỉ đòi "ca khác scope đứng trước" vẫn xanh khi
    trang mở bằng một mốc thời gian không khóa. Ba tên này là thứ hội đồng đọc
    đầu tiên, nên chúng phải là một quyết định có chỗ đỏ khi trôi.
    """
    from eval.ct03 import thu_tu_bang_chung

    ds = entity_da_nguon(doc_anh_do_thi(ANH_SYNTH))
    # Xếp bằng đúng khóa của trang, nhưng chỉ với phần suy được từ ảnh chụp:
    # `khoa` và `loai` đến từ kho nên phần đó do test marker `neo4j` canh.
    gia = [
        MoTaEntity(
            entity=e,
            mo_ta="",
            khoa=None if e.ten in KHAC_SCOPE_SYNTH else "noi_bo:runbook",
            so_manh=0,
            nguon=f"c1{GRAPH_FIELD_SEP}c2",
            so_chunk_nguon=2,
            loai="time" if e.ten in TIME_SYNTH else "subject",
        )
        for e in ds
    ]
    ten = [m.entity.ten for m in sorted(gia, key=thu_tu_bang_chung)]
    # Ba tên lấy từ `BA_CA_MO_TRANG_SYNTH`, cùng hằng mà test chạy trên Neo4j
    # thật dùng: hai bản chép tay là hai bản sẽ trôi khỏi nhau, và bản chỉ chạy
    # trên máy chủ là bản trôi mà không ai thấy.
    assert ten[:3] == BA_CA_MO_TRANG_SYNTH
    # Mười ca yếu chiếm trọn phần đuôi, không ca nào lọt lên nhóm mạnh.
    assert set(ten[-len(YEU_SYNTH):]) == YEU_SYNTH, ten[-len(YEU_SYNTH):]
    assert {m.entity.ten for m in gia if m.la_gia_tri_yeu} == YEU_SYNTH


# ---------------------------------------------------------------------------
# Hai cửa của một lần chạy: ảnh chụp lệch space, và space ghi trong repo
# ---------------------------------------------------------------------------


def test_anh_chup_lech_space_bi_tu_choi(tmp_path):
    """Gõ nhầm `--space` cho một trang liệt kê entity của kho khác.

    Mọi entity sẽ "vắng trong graph", nên trang trông như kho hỏng trong khi chỉ
    là một tham số sai. Cửa nằm ở hàm thuần chứ không trong `main`, để chấm được
    cả hai chiều mà không cần kho.
    """
    ly_do = ly_do_tu_choi_space("khao_sat", tmp_path / "x.html", "synth")
    assert ly_do and "synth" in ly_do and "khao_sat" in ly_do
    assert ly_do_tu_choi_space("synth", tmp_path / "x.html", "synth") is None


def test_khong_ghi_trang_cua_space_la_vao_cay_repo(tmp_path):
    """Rào dữ liệu thật, cùng hình dạng với `chup_do_thi.SPACE_GHI_TRONG_REPO`.

    Trang dump nguyên văn **tên entity** và ảnh PNG chụp lại trang thì có commit.
    Một `--space real` ở story 2.11 rồi chụp là đưa tên thực thể của dữ liệu công
    ty vào lịch sử git.
    """
    from eval.ct03 import REPO_ROOT as GOC

    trong_repo = GOC / "eval" / "expr" / "ct03-real.html"
    ly_do = ly_do_tu_choi_space("real", trong_repo, "real")
    assert ly_do and "real" in ly_do and str(trong_repo) in ly_do
    # Space trong danh sách cho phép thì được, và space lạ ghi ra ngoài repo cũng được.
    assert ly_do_tu_choi_space("synth", trong_repo, "synth") is None
    assert ly_do_tu_choi_space("khao_sat", trong_repo, "khao_sat") is None
    assert ly_do_tu_choi_space("real", tmp_path / "real.html", "real") is None


def test_ba_cong_cu_dung_chung_mot_danh_sach_space():
    """Ba công cụ ghi vật có commit phải nói cùng một điều, và bằng **một** bản.

    Ảnh chụp đồ thị, trang CT-03 và file đề xuất bí danh cùng là vật có commit
    sinh ra từ một space. Để ba danh sách lệch nhau là một space chụp được mà
    không dựng trang được, hoặc tệ hơn, một space dữ liệu thật lọt qua đúng một
    trong ba cửa.

    Tới story 2.12 luật này sống ở **ba** bản `frozenset` chép tay và test cũ
    chỉ ghim được hai; bản thứ ba (`de_xuat_bi_danh`, thêm ở 2.12) không có gì
    canh. Retro Epic 2 gom cả ba về `eval/rao_ghi_repo.py`. Test khẳng định
    phép gom đó còn nguyên: ba tên phải trỏ vào **cùng một object**, nên một
    lần chép lại giá trị ở một module là đỏ ngay, không đợi ba giá trị trôi xa
    nhau rồi mới thấy.
    """
    from eval.chup_do_thi import SPACE_GHI_TRONG_REPO as CUA_ANH
    from eval.de_xuat_bi_danh import SPACE_GHI_TRONG_REPO as CUA_DE_XUAT
    from eval.rao_ghi_repo import SPACE_GHI_TRONG_REPO as NGUON

    assert SPACE_GHI_TRONG_REPO is NGUON
    assert CUA_ANH is NGUON
    assert CUA_DE_XUAT is NGUON
    assert NGUON == frozenset({"synth", "khao_sat"})


def test_hai_space_du_lieu_that_khong_bao_gio_vao_danh_sach():
    """`real` và `that_khu` chứa tài liệu công ty, kể cả bản đã khử (ADR-013).

    Chúng vào repo được ở dạng rút gọn có muối, và đó là một đường khác không
    đi qua danh sách này. Một ngày nào đó ai đó thêm `that_khu` vào đây "cho
    tiện chụp" thì đây là dòng đỏ lên.
    """
    from eval.rao_ghi_repo import SPACE_GHI_TRONG_REPO as NGUON

    assert "real" not in NGUON and "that_khu" not in NGUON


def test_duong_dan_html_mang_ten_space():
    """Một tên cố định là ghi đè im lặng khi chạy space thứ hai."""
    a, b = duong_dan_html("synth"), duong_dan_html("khao_sat")
    assert a != b
    assert a.name == "ct03-synth.html" and b.name == "ct03-khao_sat.html"
    assert a.parent == b.parent


# ---------------------------------------------------------------------------
# Luật bằng chứng yếu: câu chứ không phải tên
# ---------------------------------------------------------------------------


def test_cau_dai_dang_menh_lenh_xuong_cuoi():
    """Giá trị `remediation`/`condition` chưa chuẩn hóa là một câu, không phải tên.

    Hai tài liệu cùng chứa "trả giới hạn bộ nhớ PHP-FPM về mức cũ rồi nạp lại
    cấu hình theo SOP-12" nói hai tài liệu chép cùng một câu hướng dẫn, không nói
    hai vùng quyền gặp nhau ở một thực thể. Chúng không khóa nên luật cũ đẩy
    chúng lên đầu trang - đúng chỗ hội đồng đọc trước.
    """
    dai = _m(
        "trả giới hạn bộ nhớ PHP-FPM về mức cũ rồi nạp lại cấu hình theo SOP-12",
        khoa=None,
        nguon=4,
        vai=("remediation",),
        loai="remediation",
    )
    ten_that = _m("nhóm Hạ tầng", khoa=None, nguon=2, loai="owner")
    assert dai.la_gia_tri_yeu and not ten_that.la_gia_tri_yeu
    assert [m.entity.ten for m in sap_theo_bang_chung([dai, ten_that])][0] == "nhóm Hạ tầng"


def test_vai_yeu_xet_ca_vai_tu_anh_chup_khong_chi_entity_type():
    """Node mang **một** `entity_type` dù entity điền nhiều vai ở nhiều hyperedge.

    Hỏi riêng `entity_type` là bỏ sót theo cả hai chiều: một entity mà ảnh chụp
    chỉ thấy ở vai `time` vẫn yếu dù node ghi `entity_type` là `subject`, và
    ngược lại.
    """
    # Ảnh chụp nói `time`, node nói `subject`: vẫn yếu.
    assert _m("12 tháng", vai=("time",), loai="subject").la_gia_tri_yeu
    # Node nói `time`, ảnh chụp cũng chỉ thấy `time`: yếu.
    assert _m("mỗi quý", vai=("time",), loai="time").la_gia_tri_yeu
    # Có một vai mạnh thì không còn yếu vì vai nữa.
    assert not _m("App01", vai=("subject", "time"), loai="time").la_gia_tri_yeu


def test_node_vang_trong_graph_van_cham_duoc_luat_yeu():
    """`loai` là `None` khi node vắng; nhánh lọc không được chết lặng ở đó."""
    vang = _m("12 tháng", vai=("time",), vang=True)
    assert vang.loai is None
    assert vang.la_gia_tri_yeu, "phải chấm được bằng vai từ ảnh chụp"
    manh = _m("nhóm Hạ tầng", vai=("owner",), vang=True)
    assert not manh.la_gia_tri_yeu


# ---------------------------------------------------------------------------
# Thiếu hẳn trường mô tả khác với trường rỗng
# ---------------------------------------------------------------------------


def test_thieu_truong_mo_ta_khac_mo_ta_rong_va_khac_node_vang():
    """Ba trạng thái, ba câu khác nhau; gộp là trang khẳng định sai về một node."""
    rong = _m("rong", "")
    thieu = _m("thieu", None)
    vang = _m("vang", None, vang=True)
    assert (rong.mo_ta_rong, rong.thieu_truong_mo_ta, rong.thieu_trong_graph) == (
        True, False, False,
    )
    assert (thieu.mo_ta_rong, thieu.thieu_truong_mo_ta, thieu.thieu_trong_graph) == (
        False, True, False,
    )
    assert (vang.mo_ta_rong, vang.thieu_truong_mo_ta, vang.thieu_trong_graph) == (
        False, False, True,
    )


def test_trang_khong_gan_quyet_dinh_2_4_cho_node_thieu_truong():
    """"Chuỗi rỗng theo quyết định 2.4" chỉ đúng với node **có** trường mà rỗng."""
    anh = _anh([_he("h1", ["a.md"], {"subject": ["x"]})])
    trang = dung_html(anh, [_m("thieu", None)])
    assert "node không có trường này" in trang
    assert "không có</b> trường" in trang


# ---------------------------------------------------------------------------
# Console và bảng HTML đọc cùng một phép đếm
# ---------------------------------------------------------------------------


def test_thong_ke_goi_thang_property_khac_scope():
    ds = [
        _m("a", "", khoa=None),
        _m("b", ""),
        _m("c", None, vang=True),
    ]
    tk = thong_ke(ds)
    assert tk.tong == 3
    assert tk.khong_khoa == sum(1 for m in ds if m.khac_scope) == 1
    assert tk.vang_trong_graph == 1
    assert tk.mo_ta_rong == 2


def test_bang_html_va_dong_console_doc_cung_mot_nguon(tmp_path, capsys):
    """Sáu phép đếm sống một chỗ, nên hai đầu ra không trôi khỏi nhau được."""
    ds = [_m("a", "", khoa=None, nguon=3), _m("b", ""), _m("c", None, vang=True)]
    anh = _anh([_he("h1", ["a.md"], {"subject": ["x"]})])
    tk = thong_ke(ds)
    trang = dung_html(anh, ds)
    assert f"{tk.khong_khoa}/{tk.tong}" in trang
    assert f"{tk.mo_ta_rong}/{tk.tong}" in trang
    assert f"{tk.thieu_truong_mo_ta}/{tk.tong}" in trang
