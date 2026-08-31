"""1.2-UNIT-002/003: bảng chính sách dạng dữ liệu (FR-09, AD-4, AD-6, NFR-06).

Hai luận điểm được kiểm ở đây. Một, `allowed_keys` dựng đúng cho từng namespace
và `policy_version` bằng sha256 nội dung file, đối chiếu với oracle tính độc
lập. Hai, mọi file hỏng đều bị từ chối nạp kèm lỗi chỉ được chỗ sai - không bao
giờ có policy rỗng hay mặc định ngầm.

Ca "đổi bảng chính sách" chỉ trỏ loader sang file thứ hai, không sửa dòng code
nào (chốt 3 của brief §6).
"""

import dataclasses

import pytest

from adapters.policy_loader import load_policy
from core.policy import NAMESPACES, PolicyInvalid
from core.slots import OWNER_SLOT, POLICY_MASKABLE_SLOTS
from tests.fixtures import du_lieu_dung_tay, oracle

HAI_VAI = ("devops", "tech_support")

# Bảng nhỏ nhất còn hợp lệ, dùng làm gốc cho các ca hỏng: một hàng L2 và một
# hàng L1 để `masked_slots` có chỗ khai hợp lệ.
YAML_HOP_LE = """\
version: 1
roles:
  devops:
    scopes: [noi_bo]
    disclosure: {runbook: L2, bao_cao_su_co: L1}
    masked_slots: {}
"""


def ghi_policy(tmp_path, noi_dung: str, ten: str = "policy.yaml"):
    """Ghi một bảng chính sách tạm ra đĩa và trả đường dẫn."""
    duong_dan = tmp_path / ten
    duong_dan.write_text(noi_dung, encoding="utf-8")
    return duong_dan


# --- Nạp policy hợp lệ ---------------------------------------------------


@pytest.mark.parametrize(
    "duong_dan", [oracle.POLICY_TOI_GIAN, oracle.POLICY_NHI_PHAN], ids=["toi_gian", "nhi_phan"]
)
def test_allowed_keys_khop_oracle(duong_dan):
    """Đủ 3 namespace, mỗi namespace khớp tập khóa oracle tính riêng."""
    policy = load_policy(duong_dan)
    bang = oracle.doc_bang_chinh_sach(duong_dan)
    for vai in HAI_VAI:
        thuc_te = policy.allowed_keys(vai)
        ky_vong = oracle.allowed_keys_ky_vong(bang, vai)
        assert set(thuc_te) == set(NAMESPACES)
        for namespace in NAMESPACES:
            assert set(thuc_te[namespace]) == ky_vong[namespace], (vai, namespace)


def test_chunk_va_entity_chi_nhan_khoa_l2():
    """NFR-06: `chunks`/`entities` chỉ lấy khóa vai đạt L2, `hyperedges` từ L1."""
    policy = load_policy(oracle.POLICY_TOI_GIAN)
    khoa = policy.allowed_keys("tech_support")
    assert khoa["chunks"] == khoa["entities"] == frozenset({"noi_bo:runbook"})
    assert khoa["hyperedges"] == frozenset({"noi_bo:runbook", "noi_bo:bao_cao_su_co"})
    assert "noi_bo:bi_mat_ha_tang" not in khoa["hyperedges"]


def test_masked_slots_la_map_theo_loai_noi_dung():
    """AD-3: map loại nội dung -> tập slot, không phải tập phẳng."""
    policy = load_policy(oracle.POLICY_TOI_GIAN)
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    for vai in HAI_VAI:
        thuc_te = {loai: set(s) for loai, s in policy.masked_slots(vai).items()}
        assert thuc_te == oracle.masked_slots_ky_vong(bang, vai), vai


def test_slot_owner_khong_nam_trong_bang():
    """`owner` là luật tổng quát hóa ở tầng che (AD-9), không khai trong YAML."""
    policy = load_policy(oracle.POLICY_TOI_GIAN)
    for vai in HAI_VAI:
        for slots in policy.masked_slots(vai).values():
            assert "owner" not in slots


def test_policy_version_bang_sha256_file():
    """`policy_version` = hash nội dung file, cùng cơ chế với loader đầy đủ."""
    policy = load_policy(oracle.POLICY_TOI_GIAN)
    assert policy.policy_version == oracle.bam_file_chinh_sach(oracle.POLICY_TOI_GIAN)


def test_policy_frozen():
    """Policy bất biến sau khi nạp."""
    policy = load_policy(oracle.POLICY_TOI_GIAN)
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.policy_version = "gia_mao"


def test_doi_bang_chinh_sach_khong_sua_code():
    """Trỏ loader sang file thứ hai: khóa và `policy_version` đổi theo (chốt 3)."""
    toi_gian = load_policy(oracle.POLICY_TOI_GIAN)
    nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)
    assert toi_gian.policy_version != nhi_phan.policy_version
    assert toi_gian.allowed_keys("tech_support") != nhi_phan.allowed_keys("tech_support")
    # Baseline nhị phân ép L1 xuống L0: tech_support mất hẳn báo cáo sự cố,
    # và không còn hàng nào ở L1 nên không còn gì để che.
    assert nhi_phan.allowed_keys("tech_support")["hyperedges"] == frozenset(
        {"noi_bo:runbook"}
    )
    assert nhi_phan.masked_slots("tech_support") == {}


def test_nap_lai_cung_file_cho_ket_qua_giong_nhau():
    """Nạp nóng hai lần trên cùng file ra cùng `policy_version` (NFR-04)."""
    a = load_policy(oracle.POLICY_TOI_GIAN)
    b = load_policy(oracle.POLICY_TOI_GIAN)
    assert a.policy_version == b.policy_version
    assert a.allowed_keys("devops") == b.allowed_keys("devops")


# --- Mọi ca hỏng trong I/O Matrix đều bị từ chối -------------------------


def test_yaml_hong_cu_phap_neu_vi_tri(tmp_path):
    """YAML sai thụt lề: PolicyInvalid kèm vị trí, không trả policy rỗng."""
    xau = "version: 1\nroles:\n  devops:\n   scopes: [noi_bo]\n     disclosure: {}\n"
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "line" in str(loi.value).lower() or "dòng" in str(loi.value).lower()


def test_thieu_truong_disclosure_neu_ten_vai(tmp_path):
    """Thiếu trường bắt buộc: lỗi nêu tên vai và tên trường."""
    xau = "version: 1\nroles:\n  devops:\n    scopes: [noi_bo]\n"
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "devops" in str(loi.value) and "disclosure" in str(loi.value)


def test_thieu_truong_scopes_neu_ten_vai(tmp_path):
    """`scopes` cũng là trường bắt buộc: không có nó thì không tính được khóa."""
    xau = "version: 1\nroles:\n  devops:\n    disclosure: {runbook: L2}\n"
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "devops" in str(loi.value) and "scopes" in str(loi.value)


def test_muc_la_neu_tap_hop_le(tmp_path):
    """Mức `L3`: lỗi nêu tập hợp lệ L0/L1/L2."""
    xau = YAML_HOP_LE.replace("bao_cao_su_co: L1", "bao_cao_su_co: L3")
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    thong_diep = str(loi.value)
    assert "L3" in thong_diep
    assert all(muc in thong_diep for muc in ("L0", "L1", "L2"))


def test_slot_la_neu_cac_slot_khai_duoc(tmp_path):
    """`masked_slots` chứa `nguyen_nhan`: lỗi nêu đúng tập slot khai được.

    Liệt kê đủ 8 slot là sai chỉ dẫn: nhánh ngay trên từ chối `owner`, nên gợi
    ý nó cho người sửa YAML chỉ đẩy họ sang một lỗi khác.
    """
    xau = YAML_HOP_LE.replace(
        "masked_slots: {}", "masked_slots: {bao_cao_su_co: [nguyen_nhan]}"
    )
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    thong_diep = str(loi.value)
    assert "nguyen_nhan" in thong_diep
    assert all(slot in thong_diep for slot in POLICY_MASKABLE_SLOTS)
    assert OWNER_SLOT not in thong_diep.split("khai được là")[-1]


def test_khai_slot_owner_bi_tu_choi(tmp_path):
    """`owner` là luật tổng quát hóa luôn áp (AD-9), khai vào bảng là gõ nhầm."""
    xau = YAML_HOP_LE.replace(
        "masked_slots: {}", "masked_slots: {bao_cao_su_co: [owner]}"
    )
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert OWNER_SLOT in str(loi.value)


@pytest.mark.parametrize("muc", ["L0", "L2"])
def test_che_chi_khai_duoc_cho_hang_l1(tmp_path, muc):
    """Che là khái niệm của riêng L1 (FR-10, AD-9).

    L0 thì hyperedge vắng mặt hẳn nên không có gì để che; L2 thì chỉ còn luật
    `owner` ở tầng che. Cho khai `masked_slots` ở hai mức đó là mở đường cho
    hai ngữ nghĩa che cùng tồn tại.
    """
    xau = YAML_HOP_LE.replace("bao_cao_su_co: L1", "bao_cao_su_co: " + muc).replace(
        "masked_slots: {}", "masked_slots: {bao_cao_su_co: [cause]}"
    )
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "L1" in str(loi.value) and muc in str(loi.value)


def test_masked_slots_tro_loai_noi_dung_khong_khai(tmp_path):
    """Che một loại nội dung không có trong `disclosure` là lỗi gõ nhầm."""
    xau = YAML_HOP_LE.replace("masked_slots: {}", "masked_slots: {ha_tang: [cause]}")
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "ha_tang" in str(loi.value)


def test_file_rong_bi_tu_choi(tmp_path):
    """File rỗng: từ chối nạp, không chạy với policy rỗng."""
    with pytest.raises(PolicyInvalid):
        load_policy(ghi_policy(tmp_path, ""))


def test_thieu_khoi_roles(tmp_path):
    """Không có `roles`: từ chối nạp."""
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, "version: 1\n"))
    assert "roles" in str(loi.value)


def test_file_khong_ton_tai(tmp_path):
    """Trỏ vào file không có: `PolicyInvalid` kèm tên file, không lỗi hệ điều hành."""
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(tmp_path / "khong-co.yaml")
    assert "khong-co.yaml" in str(loi.value)


def test_duong_dan_la_thu_muc(tmp_path):
    """Trỏ nhầm vào thư mục cũng ra đúng một loại lỗi."""
    with pytest.raises(PolicyInvalid):
        load_policy(tmp_path)


def test_file_khong_phai_utf8(tmp_path):
    """Byte không giải mã được UTF-8: `PolicyInvalid`, không `UnicodeDecodeError`."""
    duong_dan = tmp_path / "latin.yaml"
    duong_dan.write_bytes("version: 1\nroles:\n  d\xe9vops: {}\n".encode("latin-1"))
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(duong_dan)
    assert "UTF-8" in str(loi.value)


def test_khoa_trung_bi_tu_choi(tmp_path):
    """YAML mặc định lấy bản cuối; ở đây khai trùng vai là mất im lặng một hàng quyền."""
    xau = YAML_HOP_LE + (
        "  devops:\n"
        "    scopes: [khac]\n"
        "    disclosure: {runbook: L0}\n"
    )
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "trùng" in str(loi.value)


@pytest.mark.parametrize("version", ["99", "'1'", "abc"])
def test_version_sai_bi_tu_choi(tmp_path, version):
    """Schema chốt ở version 1; số khác hoặc kiểu khác là không đọc được."""
    xau = YAML_HOP_LE.replace("version: 1", "version: " + version)
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "version" in str(loi.value)


def test_thieu_version(tmp_path):
    """Thiếu `version` thì không biết đang đọc lược đồ nào."""
    xau = YAML_HOP_LE.replace("version: 1\n", "")
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "version" in str(loi.value)


@pytest.mark.parametrize(
    "xau,dau_hieu",
    [
        ("version: 1\nroles:\n  devops:\n    scopes: [noi_bo]\n    disclosure: {runbook: [L2]}\n", "L2"),
        ("version: 1\nroles:\n  devops:\n    scopes: [noi_bo]\n    disclosure: {runbook: {a: b}}\n", "L2"),
    ],
    ids=["muc_la_danh_sach", "muc_la_anh_xa"],
)
def test_muc_phi_vo_huong_bi_tu_choi(tmp_path, xau, dau_hieu):
    """Mức không phải chuỗi phải ra `PolicyInvalid`, không `TypeError` unhashable."""
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert dau_hieu in str(loi.value)


def test_ten_vai_khong_phai_chuoi(tmp_path):
    """Tên vai là số thì mọi tra cứu vai sau đó đều lệch kiểu."""
    xau = "version: 1\nroles:\n  3:\n    scopes: [noi_bo]\n    disclosure: {runbook: L2}\n"
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "chuỗi" in str(loi.value)


@pytest.mark.parametrize(
    "xau",
    [
        "version: 1\nroles:\n  devops:\n    scopes: ['noi:bo']\n    disclosure: {runbook: L2}\n",
        "version: 1\nroles:\n  devops:\n    scopes: [noi_bo]\n    disclosure: {'run:book': L0}\n",
    ],
    ids=["scope_co_dau_phan_tach", "loai_noi_dung_co_dau_phan_tach"],
)
def test_hinh_dang_khoa_hong_bi_bat_luc_nap(tmp_path, xau):
    """Khóa hỏng phải nổ ở loader, không nổ giữa một request.

    Ca thứ hai ở mức L0 nên không lọt vào tập khóa nào - vẫn phải bị bắt, nếu
    không thì nâng nó lên L1 sau này là hệ chết ở chỗ khác.
    """
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, xau))
    assert "khóa lọc" in str(loi.value)


def test_muc_mac_dinh_la_l0(tmp_path):
    """Loại nội dung chưa ai khai chính sách thì vô hình, không mở toang."""
    policy = load_policy(ghi_policy(tmp_path, YAML_HOP_LE))
    assert policy.level("devops", "loai_chua_ai_khai") == "L0"
    for namespace in NAMESPACES:
        assert "noi_bo:loai_chua_ai_khai" not in policy.allowed_keys("devops")[namespace]


def test_schema_khong_hard_code_enum_vai(tmp_path):
    """Thêm vai mới chỉ là sửa YAML, không sửa code (FR-09)."""
    them = YAML_HOP_LE + (
        "  vai_moi_toanh:\n"
        "    scopes: [khach_hang_x]\n"
        "    disclosure: {loai_noi_dung_moi: L1}\n"
        "    masked_slots: {loai_noi_dung_moi: [cause]}\n"
    )
    policy = load_policy(ghi_policy(tmp_path, them))
    khoa = policy.allowed_keys("vai_moi_toanh")
    assert khoa["hyperedges"] == frozenset({"khach_hang_x:loai_noi_dung_moi"})
    assert khoa["chunks"] == frozenset()


# --- Hàm thuần của core dùng chung với bảng chính sách (AD-4) ------------


def test_khoa_loc_la_ham_thuan_cua_du_lieu():
    """`{scope}:{content_type}`, không đọc bảng chính sách."""
    from core.keys import filter_key

    for he in du_lieu_dung_tay.HYPEREDGES:
        assert filter_key(he["scope"], he["content_type"]) == oracle.khoa_ky_vong(
            he["scope"], he["content_type"]
        )


def test_khoa_loc_tu_choi_dau_vao_hong():
    """Rỗng hoặc chứa dấu phân tách là lỗi lập trình, không im lặng ghép bừa."""
    from core.keys import filter_key

    for scope, loai in (("", "runbook"), ("noi_bo", "  "), ("noi:bo", "runbook")):
        with pytest.raises(ValueError):
            filter_key(scope, loai)


@pytest.mark.parametrize("xau", [None, 3, ["noi_bo"]])
def test_khoa_loc_tu_choi_sai_kieu(xau):
    """Sai kiểu là `TypeError`, không phải `AttributeError` lộ ruột."""
    from core.keys import filter_key

    with pytest.raises(TypeError):
        filter_key(xau, "runbook")


def test_khoa_loc_ghep_bang_ban_da_cat_khoang_trang():
    """Khóa lệch một dấu cách ghi vào payload là mục không bao giờ lọc trúng."""
    from core.keys import filter_key

    assert filter_key(" noi_bo ", "runbook ") == "noi_bo:runbook"


def test_chuan_hoa_id_bo_dau_nhay_cua_upstream():
    """Upstream bọc tên node bằng dấu nháy kép; chuẩn hóa một nơi duy nhất."""
    from core.ids import normalize_id

    assert normalize_id('"App01"') == "App01"
    assert normalize_id("  App01  ") == "App01"
    assert normalize_id("App01") == "App01"


def test_point_id_ghim_bang_gia_tri_chu():
    """Ghim bằng chuỗi chữ, không tính lại bằng chính hằng số đang kiểm.

    Tính vế phải bằng `ID_NAMESPACE` thì đổi hằng số đó test vẫn xanh, trong khi
    đổi nó là mọi point id đã ghi thành sai và phải re-ingest toàn bộ.
    """
    import uuid

    from core.ids import ID_NAMESPACE, point_id

    assert str(ID_NAMESPACE) == "93cef57c-8531-53de-a55f-dbe2449c3d9d"
    assert point_id("App01") == "ac132846-c819-53ed-97c5-a470b19f0793"
    assert point_id('"App01"') == point_id("App01")
    assert uuid.UUID(point_id("App01")).version == 5


def test_chuan_hoa_id_gom_ca_unicode():
    """NFD và NFC của cùng một tên tiếng Việt phải ra một id, một point id."""
    import unicodedata

    from core.ids import normalize_id, point_id

    nfc = "Máy chủ Hà Nội"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    assert normalize_id(nfd) == normalize_id(nfc) == nfc
    assert point_id(nfd) == point_id(nfc)


def test_hai_cau_hinh_do_cung_vai_cung_loai_noi_dung():
    """Hai file chỉ khác cột mức - đó là điều làm cho Đo 3 so sánh được.

    Nếu baseline nhị phân lỡ đổi cả tập vai hay tập loại nội dung thì chênh
    lệch đo được không còn quy về một biến chính sách nữa.
    """
    toi_gian = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    nhi_phan = oracle.doc_bang_chinh_sach(oracle.POLICY_NHI_PHAN)
    assert set(toi_gian["roles"]) == set(nhi_phan["roles"]) == set(HAI_VAI)
    for vai in HAI_VAI:
        assert set(toi_gian["roles"][vai]["disclosure"]) == set(
            nhi_phan["roles"][vai]["disclosure"]
        )
        assert toi_gian["roles"][vai]["scopes"] == nhi_phan["roles"][vai]["scopes"]
    # Baseline nhị phân đúng nghĩa `L1 -> L0`: không nâng mức nào lên.
    for vai in HAI_VAI:
        for loai, muc in toi_gian["roles"][vai]["disclosure"].items():
            moi = nhi_phan["roles"][vai]["disclosure"][loai]
            assert moi == ("L0" if muc == "L1" else muc), (vai, loai)


def test_khoa_mang_du_hai_scope_cua_devops():
    """Nửa trái của khóa lọc được kiểm thật, không chỉ nửa phải."""
    policy = load_policy(oracle.POLICY_TOI_GIAN)
    devops = policy.allowed_keys("devops")["hyperedges"]
    tech_support = policy.allowed_keys("tech_support")["hyperedges"]
    assert "khach_hang_a:bao_cao_su_co" in devops
    # Cùng loại nội dung, khác scope: tech_support thấy bản nội bộ, không thấy
    # bản của khách hàng A. Đó là biên cách ly khách hàng của RT-01.
    assert "noi_bo:bao_cao_su_co" in tech_support
    assert not any(k.startswith("khach_hang_a:") for k in tech_support)
