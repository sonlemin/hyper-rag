"""1.2-UNIT-002/003: bảng chính sách dạng dữ liệu (FR-09, AD-4, AD-6, NFR-06).

Hai luận điểm được kiểm ở đây. Một, `allowed_keys` dựng đúng cho từng namespace
và `policy_version` bằng sha256 nội dung file, đối chiếu với oracle tính độc
lập. Hai, mọi file hỏng đều bị từ chối nạp kèm lỗi chỉ được chỗ sai - không bao
giờ có policy rỗng hay mặc định ngầm.

Ca "đổi bảng chính sách" chỉ trỏ loader sang file thứ hai, không sửa dòng code
nào (chốt 3 của brief §6).
"""

import dataclasses
import logging

import pytest

from adapters.policy_loader import load_policy
from core.policy import NAMESPACES, TRAN_KHOA_MOI_VAI, PolicyInvalid
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

# Bảng hạng đi kèm `YAML_HOP_LE`. Từ story 3.2 validator đơn điệu đòi bảng chính
# sách khai **đúng** tập loại nội dung có hạng, nên một bảng hai dòng chỉ hợp lệ
# trên một bảng hạng hai dòng. Tiêm qua tham số chứ không nới luật: hệ chạy thật
# đọc `config/hang-do-nhay.yaml`, và đó là file đóng băng trước ingest.
HANG_NHO = {"runbook": 10, "bao_cao_su_co": 20}

# 13 loại của `config/hang-do-nhay.yaml`, viết tay ở đây làm đối chứng: bốn cấu
# hình đo phải khai đủ đúng tập này, và một danh sách suy từ chính file cấu hình
# thì test chỉ chứng minh file nhất quán với chính nó.
MUOI_BA_LOAI = (
    "faq",
    "tai_lieu_san_pham",
    "sop",
    "troubleshooting",
    "runbook",
    "known_issue",
    "vong_doi_ticket",
    "canh_bao",
    "bao_cao_su_co",
    "postmortem",
    "log",
    "cmdb",
    "bi_mat_ha_tang",
)


def ghi_policy(tmp_path, noi_dung: str, ten: str = "policy.yaml"):
    """Ghi một bảng chính sách tạm ra đĩa và trả đường dẫn."""
    duong_dan = tmp_path / ten
    duong_dan.write_text(noi_dung, encoding="utf-8")
    return duong_dan


def nap_policy(tmp_path, noi_dung: str, *, hang=None, ten: str = "policy.yaml"):
    """Ghi rồi nạp một bảng tạm trên một bảng hạng nhỏ; mặc định `HANG_NHO`."""
    return load_policy(
        ghi_policy(tmp_path, noi_dung, ten), hang=HANG_NHO if hang is None else hang
    )


# --- Nạp policy hợp lệ ---------------------------------------------------


@pytest.mark.parametrize(
    "duong_dan", [oracle.POLICY_DAY_DU, oracle.POLICY_NHI_PHAN], ids=["day_du", "nhi_phan"]
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


# Bảy loại mà `tech_support` đạt L2 trong bảng đầy đủ, và ba loại nó dừng ở L1.
# Kỳ vọng viết tay: suy nó từ chính file cấu hình là chứng minh file nhất quán
# với chính nó.
TS_L2 = frozenset(
    {
        "faq",
        "tai_lieu_san_pham",
        "sop",
        "troubleshooting",
        "runbook",
        "known_issue",
        "vong_doi_ticket",
    }
)
TS_L1 = frozenset({"canh_bao", "bao_cao_su_co", "postmortem"})

# Cột `devops` của cấu hình 3, viết tay. Nó **phải** được ghim tuyệt đối chứ
# không chỉ suy ra: `bi_mat_ha_tang` ở L1 là thứ mà chính YAML gọi là "quyết
# định (1), không phải hệ quả của A4" (ADR-014), và không có dòng này thì sửa nó
# thành L2 rồi bỏ `masked_slots` vẫn xanh cả suốt - một quyết định của khóa luận
# đổi được mà không ai xem lại diff.
DEVOPS_L1 = frozenset({"bi_mat_ha_tang"})
DEVOPS_CHE = {"bi_mat_ha_tang": {"source", "remediation"}}


def test_chunk_va_entity_chi_nhan_khoa_l2():
    """NFR-06: `chunks`/`entities` chỉ lấy khóa vai đạt L2, `hyperedges` từ L1."""
    policy = load_policy(oracle.POLICY_DAY_DU)
    khoa = policy.allowed_keys("tech_support")
    l2 = frozenset("noi_bo:" + loai for loai in TS_L2)
    assert khoa["chunks"] == khoa["entities"] == l2
    assert khoa["hyperedges"] == l2 | frozenset("noi_bo:" + loai for loai in TS_L1)
    # Ba loại L0 của `tech_support` vắng mặt ở cả ba namespace.
    for loai in ("log", "cmdb", "bi_mat_ha_tang"):
        assert not any("noi_bo:" + loai in k for k in khoa.values()), loai


def test_masked_slots_la_map_theo_loai_noi_dung():
    """AD-3: map loại nội dung -> tập slot, không phải tập phẳng."""
    policy = load_policy(oracle.POLICY_DAY_DU)
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_DAY_DU)
    for vai in HAI_VAI:
        thuc_te = {loai: set(s) for loai, s in policy.masked_slots(vai).items()}
        assert thuc_te == oracle.masked_slots_ky_vong(bang, vai), vai


def test_slot_owner_khong_nam_trong_bang():
    """`owner` là luật tổng quát hóa ở tầng che (AD-9), không khai trong YAML."""
    policy = load_policy(oracle.POLICY_DAY_DU)
    for vai in HAI_VAI:
        for slots in policy.masked_slots(vai).values():
            assert "owner" not in slots


def test_policy_version_bang_sha256_file():
    """`policy_version` = hash nội dung file, cùng cơ chế với loader đầy đủ."""
    policy = load_policy(oracle.POLICY_DAY_DU)
    assert policy.policy_version == oracle.bam_file_chinh_sach(oracle.POLICY_DAY_DU)


def test_policy_frozen():
    """Policy bất biến sau khi nạp."""
    policy = load_policy(oracle.POLICY_DAY_DU)
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.policy_version = "gia_mao"


def test_doi_bang_chinh_sach_khong_sua_code():
    """Trỏ loader sang file thứ hai: khóa và `policy_version` đổi theo (chốt 3)."""
    day_du = load_policy(oracle.POLICY_DAY_DU)
    nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)
    assert day_du.policy_version != nhi_phan.policy_version
    assert day_du.allowed_keys("tech_support") != nhi_phan.allowed_keys("tech_support")
    # Baseline nhị phân ép L1 xuống L0: tech_support mất đúng vùng L1 của bảng
    # đầy đủ, và không còn hàng nào ở L1 nên không còn gì để che.
    assert nhi_phan.allowed_keys("tech_support")["hyperedges"] == frozenset(
        "noi_bo:" + loai for loai in TS_L2
    )
    assert nhi_phan.masked_slots("tech_support") == {}


def test_nap_lai_cung_file_cho_ket_qua_giong_nhau():
    """Nạp nóng hai lần trên cùng file ra cùng `policy_version` (NFR-04)."""
    a = load_policy(oracle.POLICY_DAY_DU)
    b = load_policy(oracle.POLICY_DAY_DU)
    assert a.policy_version == b.policy_version
    assert a.allowed_keys("devops") == b.allowed_keys("devops")


# --- Mọi ca hỏng trong I/O Matrix đều bị từ chối -------------------------


def test_yaml_hong_cu_phap_neu_vi_tri(tmp_path):
    """YAML sai thụt lề: PolicyInvalid kèm vị trí, không trả policy rỗng."""
    xau = "version: 1\nroles:\n  devops:\n   scopes: [noi_bo]\n     disclosure: {}\n"
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
    assert "line" in str(loi.value).lower() or "dòng" in str(loi.value).lower()


def test_thieu_truong_disclosure_neu_ten_vai(tmp_path):
    """Thiếu trường bắt buộc: lỗi nêu tên vai và tên trường."""
    xau = "version: 1\nroles:\n  devops:\n    scopes: [noi_bo]\n"
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
    assert "devops" in str(loi.value) and "disclosure" in str(loi.value)


def test_thieu_truong_scopes_neu_ten_vai(tmp_path):
    """`scopes` cũng là trường bắt buộc: không có nó thì không tính được khóa."""
    xau = "version: 1\nroles:\n  devops:\n    disclosure: {runbook: L2}\n"
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
    assert "devops" in str(loi.value) and "scopes" in str(loi.value)


def test_muc_la_neu_tap_hop_le(tmp_path):
    """Mức `L3`: lỗi nêu tập hợp lệ L0/L1/L2."""
    xau = YAML_HOP_LE.replace("bao_cao_su_co: L1", "bao_cao_su_co: L3")
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
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
        nap_policy(tmp_path, xau)
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
        nap_policy(tmp_path, xau)
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
        nap_policy(tmp_path, xau)
    assert "L1" in str(loi.value) and muc in str(loi.value)


def test_masked_slots_tro_loai_noi_dung_khong_khai(tmp_path):
    """Che một loại nội dung không có trong `disclosure` là lỗi gõ nhầm."""
    xau = YAML_HOP_LE.replace("masked_slots: {}", "masked_slots: {ha_tang: [cause]}")
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
    assert "ha_tang" in str(loi.value)


def test_file_rong_bi_tu_choi(tmp_path):
    """File rỗng: từ chối nạp, không chạy với policy rỗng."""
    with pytest.raises(PolicyInvalid):
        nap_policy(tmp_path, "")


def test_thieu_khoi_roles(tmp_path):
    """Không có `roles`: từ chối nạp."""
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, "version: 1\n")
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
        nap_policy(tmp_path, xau)
    assert "trùng" in str(loi.value)


@pytest.mark.parametrize("version", ["99", "'1'", "abc"])
def test_version_sai_bi_tu_choi(tmp_path, version):
    """Schema chốt ở version 1; số khác hoặc kiểu khác là không đọc được."""
    xau = YAML_HOP_LE.replace("version: 1", "version: " + version)
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
    assert "version" in str(loi.value)


def test_thieu_version(tmp_path):
    """Thiếu `version` thì không biết đang đọc lược đồ nào."""
    xau = YAML_HOP_LE.replace("version: 1\n", "")
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
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
        nap_policy(tmp_path, xau)
    assert dau_hieu in str(loi.value)


def test_ten_vai_khong_phai_chuoi(tmp_path):
    """Tên vai là số thì mọi tra cứu vai sau đó đều lệch kiểu."""
    xau = "version: 1\nroles:\n  3:\n    scopes: [noi_bo]\n    disclosure: {runbook: L2}\n"
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau)
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
        nap_policy(tmp_path, xau)
    assert "khóa lọc" in str(loi.value)


def test_muc_mac_dinh_la_l0(tmp_path):
    """Loại nội dung chưa ai khai chính sách thì vô hình, không mở toang."""
    policy = nap_policy(tmp_path, YAML_HOP_LE)
    assert policy.level("devops", "loai_chua_ai_khai") == "L0"
    for namespace in NAMESPACES:
        assert "noi_bo:loai_chua_ai_khai" not in policy.allowed_keys("devops")[namespace]


def test_schema_khong_hard_code_enum_vai(tmp_path):
    """Thêm vai mới chỉ là sửa YAML, không sửa code (FR-09).

    Vai mới khai đúng tập loại nội dung của bảng hạng như mọi vai khác: validator
    đơn điệu không có ngoại lệ cho vai mới, và một vai được miễn khai đủ là một
    vai mà mặc định L0 ngầm quay lại.
    """
    them = YAML_HOP_LE + (
        "  vai_moi_toanh:\n"
        "    scopes: [khach_hang_x]\n"
        "    disclosure: {runbook: L1, bao_cao_su_co: L1}\n"
        "    masked_slots: {runbook: [cause], bao_cao_su_co: [cause, source]}\n"
    )
    policy = nap_policy(tmp_path, them)
    khoa = policy.allowed_keys("vai_moi_toanh")
    assert khoa["hyperedges"] == frozenset(
        {"khach_hang_x:runbook", "khach_hang_x:bao_cao_su_co"}
    )
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


def test_tach_khoa_la_nghich_dao_cua_ghep_khoa():
    """Vòng tròn: tách rồi ghép lại phải ra đúng chuỗi cũ, trên dữ liệu thật."""
    from core.keys import filter_key, split_key

    for he in du_lieu_dung_tay.HYPEREDGES:
        khoa = filter_key(he["scope"], he["content_type"])
        assert split_key(khoa) == (he["scope"], he["content_type"])
        assert filter_key(*split_key(khoa)) == khoa


def test_tach_khoa_tra_dung_loai_noi_dung_cho_tang_che():
    """Tầng che nhận khóa hyperedge nhưng tra `masked_slots` theo loại nội dung."""
    from core.keys import split_key

    assert split_key("noi_bo:bao_cao_su_co") == ("noi_bo", "bao_cao_su_co")
    assert split_key("khach_hang_a:runbook")[1] == "runbook"


@pytest.mark.parametrize(
    "hong",
    ["", "noi_bo", ":runbook", "noi_bo:", " noi_bo:runbook", "noi_bo:runbook "],
)
def test_tach_khoa_tu_choi_chuoi_khong_phai_khoa(hong):
    """Chuỗi không do `filter_key` sinh ra thì nổ, không trả về một nửa vô nghĩa."""
    from core.keys import split_key

    with pytest.raises(ValueError):
        split_key(hong)


@pytest.mark.parametrize("xau", [None, 3, ("noi_bo", "runbook")])
def test_tach_khoa_tu_choi_sai_kieu(xau):
    """Cùng luật lỗi với `filter_key`: sai kiểu là `TypeError`."""
    from core.keys import split_key

    with pytest.raises(TypeError):
        split_key(xau)


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


def test_bon_cau_hinh_do_cung_vai_cung_loai_noi_dung():
    """Bốn file chỉ khác cột mức (và cấu hình 1 khác cả `scopes`) - FR-28.

    Nếu một cấu hình đo lỡ đổi cả tập vai hay tập loại nội dung thì chênh lệch
    đo được không còn quy về một biến chính sách nữa. Cấu hình 1 là ngoại lệ có
    khai: nó mở thêm scope `khach_hang_b`, vì trần recall tính trên *toàn bộ*
    nhãn và nhãn có cặp ở scope đó.
    """
    bang = {p: oracle.doc_bang_chinh_sach(p) for p in oracle.BON_CAU_HINH}
    assert len(bang) == 4
    for duong_dan, b in bang.items():
        assert set(b["roles"]) == set(HAI_VAI), duong_dan
        for vai in HAI_VAI:
            assert set(b["roles"][vai]["disclosure"]) == set(MUOI_BA_LOAI), (
                duong_dan,
                vai,
            )
    goc = bang[oracle.POLICY_DAY_DU]
    for duong_dan in (oracle.POLICY_NHI_PHAN, oracle.POLICY_TOI_THIEU_L1):
        for vai in HAI_VAI:
            assert bang[duong_dan]["roles"][vai]["scopes"] == goc["roles"][vai]["scopes"]


def test_cau_hinh_2_la_dung_phep_l1_thanh_l0_tren_cau_hinh_3():
    """Baseline nhị phân đúng nghĩa `L1 -> L0`: không nâng mức nào lên."""
    goc = oracle.doc_bang_chinh_sach(oracle.POLICY_DAY_DU)
    nhi_phan = oracle.doc_bang_chinh_sach(oracle.POLICY_NHI_PHAN)
    for vai in HAI_VAI:
        for loai, muc in goc["roles"][vai]["disclosure"].items():
            moi = nhi_phan["roles"][vai]["disclosure"][loai]
            assert moi == ("L0" if muc == "L1" else muc), (vai, loai)
    for vai in HAI_VAI:
        assert not (nhi_phan["roles"][vai].get("masked_slots") or {}), vai


def test_cau_hinh_4_la_dung_phep_l0_thanh_l1_che_ca_bay_slot():
    """Tối-thiểu-L1: mọi ô L0 lên L1 và che **cả 7 slot** khai được."""
    goc = oracle.doc_bang_chinh_sach(oracle.POLICY_DAY_DU)
    bon = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_THIEU_L1)
    bay_slot = set(POLICY_MASKABLE_SLOTS)
    assert len(bay_slot) == 7 and OWNER_SLOT not in bay_slot
    for vai in HAI_VAI:
        che = bon["roles"][vai].get("masked_slots") or {}
        for loai, muc in goc["roles"][vai]["disclosure"].items():
            moi = bon["roles"][vai]["disclosure"][loai]
            assert moi == ("L1" if muc == "L0" else muc), (vai, loai)
            if muc == "L0":
                assert set(che[loai]) == bay_slot, (vai, loai)
            elif muc == "L1":
                # Ô đã L1 giữ nguyên tập che của cấu hình 3.
                assert set(che[loai]) == set(
                    (goc["roles"][vai].get("masked_slots") or {})[loai]
                ), (vai, loai)


def test_cau_hinh_1_mo_ca_ba_scope_va_moi_o_l2():
    """Trần recall phải là trần thật: cả 13 loại **và** cả 3 scope (PRD 5.3)."""
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TAT_PHAN_QUYEN)
    for vai in HAI_VAI:
        assert set(bang["roles"][vai]["scopes"]) == {
            "noi_bo",
            "khach_hang_a",
            "khach_hang_b",
        }, vai
        assert set(bang["roles"][vai]["disclosure"].values()) == {"L2"}, vai
        assert not (bang["roles"][vai].get("masked_slots") or {}), vai


@pytest.mark.parametrize(
    "duong_dan", oracle.BON_CAU_HINH, ids=lambda p: p.stem.removeprefix("policy-")
)
def test_bon_cau_hinh_deu_qua_validator_va_duoi_tran_khoa(duong_dan):
    """AD-5: "cả 4 cấu hình đo của FR-28 phải qua validator". Và AC của story.

    Trần 50 khóa là cảnh báo chứ không phải phép từ chối, nên nó không tự canh
    được ở đây - test đếm lại và ghim con số cao nhất (39, ở cấu hình 1).
    """
    policy = load_policy(duong_dan)
    assert policy.policy_version == oracle.bam_file_chinh_sach(duong_dan)
    for vai, hang in policy.roles.items():
        assert set(hang.disclosure) == set(MUOI_BA_LOAI), (duong_dan, vai)
        for namespace, khoa in hang.allowed_keys.items():
            assert len(khoa) <= 39, (duong_dan, vai, namespace, len(khoa))


def test_cau_hinh_1_la_cho_tran_khoa_cao_nhat():
    """39 khóa = 3 scope × 13 loại; ba cấu hình kia thấp hơn hẳn."""
    cao_nhat = {
        p: max(len(k) for r in load_policy(p).roles.values() for k in r.allowed_keys.values())
        for p in oracle.BON_CAU_HINH
    }
    assert cao_nhat[oracle.POLICY_TAT_PHAN_QUYEN] == 39
    assert cao_nhat[oracle.POLICY_TAT_PHAN_QUYEN] < TRAN_KHOA_MOI_VAI
    for p, so in cao_nhat.items():
        if p != oracle.POLICY_TAT_PHAN_QUYEN:
            assert so < cao_nhat[oracle.POLICY_TAT_PHAN_QUYEN], p


# --- Validator đơn điệu của AD-5 (story 3.2) ----------------------------


def _bang(disclosure: dict, che: dict | None = None, scopes="[noi_bo]") -> str:
    """Một bảng một vai, sinh từ dict, để ca hỏng đọc được ngay ở chỗ khai."""
    dong = "\n".join(f"      {loai}: {muc}" for loai, muc in disclosure.items())
    khoi_che = "\n".join(
        f"      {loai}: [{', '.join(slots)}]" for loai, slots in (che or {}).items()
    )
    return (
        "version: 1\nroles:\n  devops:\n"
        f"    scopes: {scopes}\n"
        f"    disclosure:\n{dong}\n"
        + (f"    masked_slots:\n{khoi_che}\n" if khoi_che else "    masked_slots: {}\n")
    )


HANG_BA = {"faq": 2, "runbook": 10, "bao_cao_su_co": 20}


def test_dao_chieu_dieu_kien_1_neu_cap_loai_kem_hai_hang_va_hai_muc(tmp_path):
    """Hàng I/O Matrix "Đảo chiều điều kiện (1)": `faq` L0 mà `runbook` L2."""
    xau = _bang({"faq": "L0", "runbook": "L2", "bao_cao_su_co": "L0"})
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau, hang=HANG_BA)
    thong_diep = str(loi.value)
    assert "faq" in thong_diep and "runbook" in thong_diep
    assert "2" in thong_diep and "10" in thong_diep
    assert "L0" in thong_diep and "L2" in thong_diep


def test_dao_chieu_dieu_kien_2_neu_cap_loai_va_tap_slot_chenh(tmp_path):
    """Hàng "Đảo chiều điều kiện (2)": loại hạng cao che ít slot hơn hạng thấp."""
    xau = _bang(
        {"faq": "L1", "runbook": "L1", "bao_cao_su_co": "L1"},
        {
            "faq": ["cause", "source"],
            "runbook": ["cause"],
            "bao_cao_su_co": ["cause", "source"],
        },
    )
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau, hang=HANG_BA)
    thong_diep = str(loi.value)
    assert "faq" in thong_diep and "runbook" in thong_diep
    assert "source" in thong_diep


def test_thieu_mot_loai_co_hang_bi_tu_choi_ca_file(tmp_path):
    """Hàng "Thiếu một loại có hạng": nêu tên loại thiếu, từ chối cả file."""
    xau = _bang({"faq": "L2", "runbook": "L2"})
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau, hang=HANG_BA)
    assert "bao_cao_su_co" in str(loi.value)


def test_khai_mot_loai_khong_co_hang_bi_tu_choi_ca_file(tmp_path):
    """Hàng "Khai một loại không có hạng": nêu tên loại lạ."""
    xau = _bang(
        {"faq": "L2", "runbook": "L2", "bao_cao_su_co": "L2", "loai_la_hoac": "L2"}
    )
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau, hang=HANG_BA)
    assert "loai_la_hoac" in str(loi.value)


def test_bang_don_dieu_tren_ba_loai_van_nap_duoc(tmp_path):
    """Đối chứng dương của bốn ca trên: chuỗi không tăng thì nạp được."""
    policy = nap_policy(
        tmp_path,
        _bang(
            {"faq": "L2", "runbook": "L1", "bao_cao_su_co": "L0"},
            {"runbook": ["cause"]},
        ),
        hang=HANG_BA,
    )
    assert policy.level("devops", "runbook") == "L1"


def test_vai_vuot_tran_khoa_van_nap_duoc_va_co_mot_dong_canh_bao(tmp_path, caplog):
    """Hàng "Vai vượt 50 khóa": nạp được, một dòng WARNING nêu vai/namespace/số.

    Dựng 51 khóa bằng 51 scope trên một loại nội dung L2 - trục scope là trục rẻ
    nhất để vượt trần mà không phải bịa 51 loại nội dung, và trần đếm trên tích
    của hai trục nên hai cách vượt là một.
    """
    scopes = "[" + ", ".join(f"s{i:02d}" for i in range(51)) + "]"
    xau = _bang(
        {"faq": "L2", "runbook": "L2", "bao_cao_su_co": "L2"}, scopes=scopes
    )
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        policy = nap_policy(tmp_path, xau, hang=HANG_BA)
    assert len(policy.allowed_keys("devops")["hyperedges"]) == 153
    dong = [r.getMessage() for r in caplog.records]
    assert dong, "vượt trần mà không có dòng cảnh báo nào"
    assert all("devops" in d for d in dong)
    assert {ns for ns in NAMESPACES if any(repr(ns) in d for d in dong)} == set(NAMESPACES)
    assert any(str(TRAN_KHOA_MOI_VAI) in d for d in dong)


def test_duoi_tran_khoa_thi_khong_canh_bao_gi(tmp_path, caplog):
    """Đối chứng: bảng nhỏ không được sinh cảnh báo, nếu không cảnh báo hết nghĩa."""
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        nap_policy(tmp_path, YAML_HOP_LE)
    assert not caplog.records


def test_thieu_bang_hang_la_tu_choi_chu_khong_phai_bo_qua_kiem():
    """Validator tắt được bằng cách quên một tham số là validator không canh gì."""
    from core.policy import build_policy

    with pytest.raises(PolicyInvalid) as loi:
        build_policy({"version": 1, "roles": {}}, policy_version="x", hang={})
    assert "hạng" in str(loi.value)


def test_bang_hang_hong_lam_load_policy_hong_chu_khong_bo_qua_validator(
    tmp_path, monkeypatch
):
    """Bảng hạng hỏng ra `PolicyInvalid` kèm tên file, không ra một loại lỗi thứ hai."""
    from adapters.sensitivity_loader import SensitivityRanksInvalid

    def no(*a, **k):
        raise SensitivityRanksInvalid("bảng hạng hỏng có chủ đích")

    monkeypatch.setattr("adapters.policy_loader.bang_hang_mac_dinh", no)
    with pytest.raises(PolicyInvalid) as loi:
        load_policy(ghi_policy(tmp_path, YAML_HOP_LE))
    assert "hạng" in str(loi.value) and "policy.yaml" in str(loi.value)


@pytest.mark.parametrize(
    "hang, dau_hieu",
    [
        ({"a": 10, "b": 10}, "cùng hạng"),
        ({"a": 10, "b": "20"}, "số nguyên"),
        ({"a": 10, "b": True}, "số nguyên"),
        ({}, "thiếu bảng hạng"),
    ],
    ids=["cung_hang", "hang_khong_phai_so", "hang_la_bool", "bang_rong"],
)
def test_bang_hang_tiem_vao_phai_la_thu_tu_toan_phan(tmp_path, hang, dau_hieu):
    """`build_policy` nhận `hang` tùy ý, nên nó phải tự canh ba luật của bảng hạng.

    Luật "không hai loại cùng hạng" sống ở `adapters/sensitivity_loader` cho
    **file** chốt của repo; `build_policy` thì nhận một map bất kỳ. Không kiểm
    lại ở đây thì hai loại ngang hạng làm kết quả validator phụ thuộc thứ tự
    dòng trong file chính sách - `sorted` ổn định nhưng không có tie-break.
    """
    xau = _bang({"a": "L2", "b": "L2"})
    with pytest.raises(PolicyInvalid) as loi:
        nap_policy(tmp_path, xau, hang=hang)
    assert dau_hieu in str(loi.value)


def test_hai_loai_cung_hang_khong_lam_ket_qua_phu_thuoc_thu_tu_dong():
    """Đột biến của chính ca trên: hai thứ tự viết phải cho **cùng** một kết cục.

    Không có phép kiểm bảng hạng thì `{"a":10,"b":10}` với `disclosure` viết
    `a,b` nạp được còn viết `b,a` bị từ chối. Ca này chấm đúng tính chất đó, để
    một lần "nới cho tiện" ở `build_policy` không lặng lẽ mở lại cửa ấy.
    """
    from core.policy import build_policy

    ket_cuc = []
    for thu_tu in (("a", "b"), ("b", "a")):
        raw = {
            "version": 1,
            "roles": {
                "devops": {
                    "scopes": ["noi_bo"],
                    "disclosure": {thu_tu[0]: "L0", thu_tu[1]: "L2"},
                }
            },
        }
        try:
            build_policy(raw, policy_version="v", hang={"a": 10, "b": 10})
            ket_cuc.append("nạp được")
        except PolicyInvalid:
            ket_cuc.append("từ chối")
    assert ket_cuc == ["từ chối", "từ chối"], ket_cuc


def test_cot_devops_cua_cau_hinh_3_ghim_tuyet_doi():
    """`devops` L2 ở 12 loại và **L1** ở `bi_mat_ha_tang` - một quyết định.

    A4 không ép `devops` xuống L0 ở đâu cả, kể cả `bi_mat_ha_tang` (phép kiểm
    CSP của retro Epic 2: 17 phép gán khả thi). Bảng chọn L1 ở đó, kế thừa từ
    bảng tối giản của story 1.2, và ADR-014 là chỗ quyết định ấy được ghi. Ghim
    tay ở đây vì đó là ranh giới duy nhất mà `devops` có: nới nó lên L2 là một
    vai đọc nguyên văn sổ tay hạ tầng, và nó phải là một diff ai cũng thấy.
    """
    policy = load_policy(oracle.POLICY_DAY_DU)
    devops = policy.role("devops")
    l1 = {loai for loai, muc in devops.disclosure.items() if muc == "L1"}
    assert l1 == DEVOPS_L1
    assert {loai for loai, muc in devops.disclosure.items() if muc == "L0"} == set()
    assert {loai for loai, muc in devops.disclosure.items() if muc == "L2"} == (
        set(MUOI_BA_LOAI) - DEVOPS_L1
    )
    assert {loai: set(s) for loai, s in devops.masked_slots.items()} == DEVOPS_CHE


def test_khoa_mang_du_hai_scope_cua_devops():
    """Nửa trái của khóa lọc được kiểm thật, không chỉ nửa phải."""
    policy = load_policy(oracle.POLICY_DAY_DU)
    devops = policy.allowed_keys("devops")["hyperedges"]
    tech_support = policy.allowed_keys("tech_support")["hyperedges"]
    assert "khach_hang_a:bao_cao_su_co" in devops
    # Cùng loại nội dung, khác scope: tech_support thấy bản nội bộ, không thấy
    # bản của khách hàng A. Đó là biên cách ly khách hàng của RT-01.
    assert "noi_bo:bao_cao_su_co" in tech_support
    assert not any(k.startswith("khach_hang_a:") for k in tech_support)
