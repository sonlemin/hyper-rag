"""Tầng che dùng chung theo chính sách slot (story 1.6, FR-10, FR-12, AD-9).

Hai kịch bản `1.6-UNIT-001` và `1.6-UNIT-002` của test-design cộng mọi hàng I/O
Matrix của spec, cộng phần chốt hình dạng mà story 1.2 để lại (chữ ký ba tham
số, danh sách đóng các method phải che, danh mục 8 vai slot).

Kỳ vọng lấy từ `tests/fixtures/oracle.py` - bộ tính độc lập, không import
`core/` - nên một lỗi cùng kiểu ở hai bên không tự triệt tiêu nhau. Dấu che
cũng viết tay ở oracle và được đối chiếu với hằng của `core/` trong đúng một
test, cùng khuôn đã dùng cho tám vai slot.

Hàm che là hàm thuần: không kho, không mạng, không container.
"""

import inspect

import pytest

from hypergraphrag.base import BaseGraphStorage, BaseKVStorage, BaseVectorStorage

from core.masking import (
    MASK_NAMESPACE,
    MASKED_READ_METHODS,
    NEIGHBOR_FIELD,
    SLOT_FIELD,
    MaskItemOutOfPermission,
    SlotRoleUnknown,
    dau_che,
    mask,
    NEIGHBOR_NO_KEY_FIELD,
    dau_che_lan_can_khong_khoa,
    la_dau_che,
)
from core.permission import user_context
from core.slots import OWNER_SLOT, SLOT_ROLES
from core.system_context import system_context
from tests.fixtures import du_lieu_dung_tay, oracle


def _context(vai: str = "tech_support", duong_dan=None):
    from adapters.policy_loader import load_policy

    policy = load_policy(duong_dan or oracle.POLICY_TOI_GIAN)
    return user_context(
        policy=policy, role=vai, space="synth", real_account="tk_" + vai
    )


def _khoa(he) -> str:
    """Khóa lọc của một hyperedge fixture, ghép tay như oracle ghép."""
    return he["scope"] + ":" + he["content_type"]


# --- Hình dạng chốt từ story 1.2, không đổi khi thay ruột -------------------


def test_chu_ky_ba_tham_so():
    """Chữ ký cố định từ T1: (kết quả, context, khóa hyperedge).

    Story 1.6 thay ruột mà không mở lại adapter nào, nên chữ ký là hợp đồng
    chứ không phải chi tiết cài đặt.
    """
    tham_so = list(inspect.signature(mask).parameters.values())
    assert len(tham_so) == 3
    assert all(
        p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and p.default is p.empty
        for p in tham_so
    )


def test_danh_sach_dong_doc_duoc_o_runtime():
    """Danh sách đóng các method phải che, đọc được để adapter phản chiếu.

    Sáu tên, một cho mỗi đường dữ liệu ra khỏi kho: `query` của đường vector,
    ba method của đường graph, và hai method đọc chunk của đường KV mà story
    1.5 thêm vào (`get_by_id`, `get_by_ids`).
    """
    assert MASKED_READ_METHODS == frozenset(
        {
            "query",
            "get_node",
            "get_edge",
            "get_node_edges",
            "get_by_id",
            "get_by_ids",
        }
    )
    assert isinstance(MASKED_READ_METHODS, frozenset)


def test_moi_method_trong_danh_sach_ton_tai_o_upstream():
    """Neo danh sách đóng vào interface thật của fork, không để trôi dạt."""
    interface = (BaseVectorStorage, BaseGraphStorage, BaseKVStorage)
    for ten in MASKED_READ_METHODS:
        assert any(hasattr(lop, ten) for lop in interface), ten


def test_tam_vai_slot_dung_mot_noi():
    """Danh mục 8 vai slot snake_case, khớp bản viết tay của oracle."""
    assert SLOT_ROLES == oracle.TAM_VAI_SLOT
    assert len(SLOT_ROLES) == 8
    assert all(s == s.lower() and " " not in s for s in SLOT_ROLES)
    assert OWNER_SLOT in SLOT_ROLES


# --- Oracle: kỳ vọng tính độc lập ------------------------------------------


def test_oracle_ky_vong_che_dung_theo_bang():
    """Oracle tính đúng kỳ vọng che, để mọi assert dưới đây có đối chứng."""
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    he02 = du_lieu_dung_tay.THEO_ID["HE-02"]
    he03 = du_lieu_dung_tay.THEO_ID["HE-03"]

    # tech_support ở L1 với báo cáo sự cố: che theo bảng cộng owner (AD-9).
    assert oracle.slot_phai_che(bang, "tech_support", he02) == {
        "cause",
        "source",
        "remediation",
        "owner",
    }
    # devops ở L2 với chính hyperedge đó: chỉ còn owner bị tổng quát hóa.
    assert oracle.slot_phai_che(bang, "devops", he02) == {"owner"}
    # Bí mật hạ tầng: devops còn thấy (L1), tech_support thì không (L0).
    thay_devops = oracle.hyperedge_thay_duoc(
        bang, "devops", du_lieu_dung_tay.HYPEREDGES
    )
    thay_ts = oracle.hyperedge_thay_duoc(
        bang, "tech_support", du_lieu_dung_tay.HYPEREDGES
    )
    assert thay_devops == ["HE-01", "HE-02", "HE-03", "HE-04"]
    # HE-04 cùng loại nội dung với HE-02 nhưng khác scope: tech_support không
    # thấy, chứng minh nửa trái của khóa lọc có tác dụng thật.
    assert thay_ts == ["HE-01", "HE-02"]
    assert oracle.slot_phai_che(bang, "devops", he03) == {"source", "remediation", "owner"}
    # Hyperedge ngoài quyền thì không có gì để che, không phải "che owner".
    assert oracle.slot_phai_che(bang, "tech_support", he03) == set()
    # HE-04 không có slot owner: luật owner không bịa ra slot không tồn tại.
    assert oracle.slot_phai_che(bang, "devops", du_lieu_dung_tay.THEO_ID["HE-04"]) == set()


def test_hai_ban_ngu_nghia_che_hoi_tu():
    """Bảng chính sách trong hệ và oracle phải nói cùng một điều.

    Quan hệ ghim ở đây là hợp đồng mà ruột che cài: cái hệ đọc từ bảng
    (`slots_to_mask`) hợp với luật `owner` của AD-9, giao với tập slot thật của
    hyperedge, đúng bằng kỳ vọng oracle. Hai bản lệch nhau thì test đỏ ở đây
    chứ không đỏ ở một assert Đo 1 nào đó ba story sau.
    """
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    for vai in ("devops", "tech_support"):
        ctx = _context(vai)
        thay_duoc = set(
            oracle.hyperedge_thay_duoc(bang, vai, du_lieu_dung_tay.HYPEREDGES)
        )
        for he in du_lieu_dung_tay.HYPEREDGES:
            ky_vong = oracle.slot_phai_che(bang, vai, he)
            if he["id"] not in thay_duoc:
                assert ky_vong == set(), (vai, he["id"])
                continue
            theo_he = (
                set(ctx.slots_to_mask(he["content_type"])) | {OWNER_SLOT}
            ) & set(he["slots"])
            assert theo_he == ky_vong, (vai, he["id"])


def test_oracle_va_core_khai_cung_bang_hang():
    """Oracle chép hằng từ `core/` nên phải có test đối chiếu, như đã làm với 8 slot.

    Hai bản cùng sai một kiểu thì mọi test khác vẫn xanh - đây là chỗ duy nhất
    bắt được việc đó. Dấu che vào cùng danh sách ấy từ story 1.6.
    """
    from core.policy import LEVEL_ORDER, NAMESPACE_MIN_LEVEL

    assert oracle.THU_TU_MUC == dict(LEVEL_ORDER)
    assert oracle.MUC_TOI_THIEU_THEO_NAMESPACE == dict(NAMESPACE_MIN_LEVEL)
    for slot in SLOT_ROLES:
        assert dau_che(slot) == oracle.dau_che_ky_vong(slot), slot


# --- 1.6-UNIT-001: bản ghi theo slot, vai L1 -------------------------------


def test_1_6_unit_001_vai_l1_che_dung_slot_bang_khai():
    """Slot phải che thành dấu che; slot công khai giữ nguyên văn.

    Đây là hàng đầu của I/O Matrix và là lý do tồn tại của cả story: vai
    `tech_support` thấy hyperedge `bao_cao_su_co` ở mức L1 phải biết rằng sự cố
    tồn tại mà không đọc được nguyên nhân, nguồn và cách xử lý.
    """
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ctx = _context("tech_support")

    da_che = mask(dict(he["slots"]), ctx, _khoa(he))

    assert da_che == oracle.ban_ghi_slot_ky_vong(bang, "tech_support", he)
    # Nói lại bằng lời, để test đỏ chỉ thẳng vào chỗ hỏng chứ không chỉ vào một
    # phép so hai dict dài.
    for slot in ("cause", "source", "remediation", "owner"):
        assert da_che[slot] != he["slots"][slot], slot
    for slot in ("subject", "symptom", "time"):
        assert da_che[slot] == he["slots"][slot], slot
    # Che không được bỏ khóa khỏi bản ghi (`kiem_ket_qua_che` canh cùng luật).
    assert set(da_che) == set(he["slots"])


def test_nguyen_van_slot_bi_che_khong_con_o_bat_ky_dau_nao_trong_ban_ghi():
    """Che một phần rồi để nguyên văn nằm ở giá trị khác là che hụt."""
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ctx = _context("tech_support")
    da_che = mask(dict(he["slots"]), ctx, _khoa(he))
    con_lai = " ".join(str(v) for v in da_che.values())
    for slot in ("cause", "source", "remediation", "owner"):
        assert he["slots"][slot] not in con_lai, slot


# --- 1.6-UNIT-002: vai L2 chỉ tổng quát hóa owner --------------------------


def test_1_6_unit_002_vai_l2_khong_che_thua_tru_owner():
    """L2 giữ nguyên sáu slot còn lại; `owner` vẫn tổng quát hóa (AD-9)."""
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ctx = _context("devops")

    da_che = mask(dict(he["slots"]), ctx, _khoa(he))

    assert da_che == oracle.ban_ghi_slot_ky_vong(bang, "devops", he)
    assert da_che[OWNER_SLOT] == dau_che(OWNER_SLOT)
    for slot in set(he["slots"]) - {OWNER_SLOT}:
        assert da_che[slot] == he["slots"][slot], slot


def test_owner_khong_bao_gio_khai_trong_bang_ma_van_bi_che():
    """Luật `owner` đến từ AD-9, không từ YAML: bảng không được nhắc tới nó."""
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    for vai, cau_hinh in bang["roles"].items():
        for slots in (cau_hinh.get("masked_slots") or {}).values():
            assert OWNER_SLOT not in slots, vai
    he = du_lieu_dung_tay.THEO_ID["HE-01"]  # runbook, L2 với cả hai vai
    for vai in ("devops", "tech_support"):
        da_che = mask(dict(he["slots"]), _context(vai), _khoa(he))
        assert da_che[OWNER_SLOT] == dau_che(OWNER_SLOT), vai


def test_hai_ly_do_che_phan_biet_duoc_tu_ben_ngoai():
    """Dấu che máy đọc được: tầng trên phân biệt "bảng khai" với "luôn che"."""
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    da_che = mask(dict(he["slots"]), _context("tech_support"), _khoa(he))
    assert da_che["cause"] == "[cause:masked]"
    assert da_che[OWNER_SLOT] == "[owner:group]"


# --- Hyperedge thiếu slot ---------------------------------------------------


def test_hyperedge_thieu_slot_thi_khong_bia_ra_khoa():
    """HE-04 không có `owner`: che không được thêm khóa vào bản ghi."""
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    he = du_lieu_dung_tay.THEO_ID["HE-04"]
    assert OWNER_SLOT not in he["slots"], "fixture phải giữ ca biên thiếu owner"
    ctx = _context("devops")

    da_che = mask(dict(he["slots"]), ctx, _khoa(he))

    assert OWNER_SLOT not in da_che
    assert set(da_che) == set(he["slots"])
    assert da_che == oracle.ban_ghi_slot_ky_vong(bang, "devops", he)


# --- Cạnh mang vai: đường rò thật của Epic 1 --------------------------------


def test_canh_mang_vai_bi_che_thi_ten_lan_can_bi_che():
    """`get_node_edges` dựng bản ghi cạnh; tên lân cận điền vào slot bị che.

    Đường rò thật của Epic 1; lý do đầy đủ ở docstring `core/masking.py`.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ctx = _context("tech_support")
    ban_ghi = {
        "node_id": "rel-HE-02",
        NEIGHBOR_FIELD: he["slots"]["cause"],
        SLOT_FIELD: "cause",
    }

    da_che = mask(ban_ghi, ctx, _khoa(he))

    assert da_che[NEIGHBOR_FIELD] == dau_che("cause")
    assert da_che["node_id"] == "rel-HE-02"
    assert da_che[SLOT_FIELD] == "cause"


def test_canh_mang_vai_khong_bi_che_thi_nguyen_trang():
    """Slot công khai: tên lân cận là nội dung được phép thấy."""
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ban_ghi = {
        "node_id": "rel-HE-02",
        NEIGHBOR_FIELD: he["slots"]["subject"],
        SLOT_FIELD: "subject",
    }
    assert mask(ban_ghi, _context("tech_support"), _khoa(he)) == ban_ghi


def test_canh_mang_vai_owner_bi_che_ca_o_l2():
    """Luật `owner` áp cả trên đường cạnh, không chỉ trên bản ghi theo slot."""
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ban_ghi = {
        "node_id": "rel-HE-02",
        NEIGHBOR_FIELD: he["slots"][OWNER_SLOT],
        SLOT_FIELD: OWNER_SLOT,
    }
    da_che = mask(ban_ghi, _context("devops"), _khoa(he))
    assert da_che[NEIGHBOR_FIELD] == dau_che(OWNER_SLOT)


def test_canh_khong_khai_vai_thi_khong_no():
    """Cạnh chưa mang vai slot vẫn ghi được (story 1.4); che phải chịu được nó.

    Prompt trích xuất 8 vai thuộc story 2.4, nên `slot=None` là hiện trạng của
    đường e2e cổng M1 chứ không phải dữ liệu hỏng.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ban_ghi = {"node_id": "rel-HE-02", NEIGHBOR_FIELD: "App01", SLOT_FIELD: None}
    assert mask(ban_ghi, _context("tech_support"), _khoa(he)) == ban_ghi


# --- Bản ghi không mang slot nào -------------------------------------------


@pytest.mark.parametrize(
    "ban_ghi",
    [
        pytest.param(dict(du_lieu_dung_tay.CHUNK_THEO_ID["chunk-HE-02"]), id="chunk_kv"),
        pytest.param(
            {"id": "rel-HE-02", "role": "hyperedge", "weight": 1.0, "source_id": "HE-02"},
            id="node_hyperedge",
        ),
        pytest.param(
            {"id": "rel-HE-02", "hyperedge_name": "rel-HE-02", "distance": 0.87},
            id="point_vector",
        ),
    ],
)
def test_ban_ghi_khong_mang_slot_nao_thi_nguyen_trang(ban_ghi):
    """Không có gì tra trúng thì không che gì - và cũng không hỏng gì.

    Ba hình dạng bản ghi thật của ba adapter. Che theo văn bản tự do
    (`content` của chunk, `description` của entity, `hyperedge_name` của kho
    vector) không tách được theo slot ở Epic 1; đó là khoản nợ có địa chỉ, ghi
    trong ledger, không đoán ở đây.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    assert mask(ban_ghi, _context("devops"), _khoa(he)) == ban_ghi


# --- Ngữ cảnh hệ thống -------------------------------------------------------


def test_ngu_canh_he_thong_doc_tho_va_khong_tra_bang():
    """Ingest đọc thô: trả nguyên trạng, không hỏi tập khóa, không hỏi bảng.

    `keys_for` trên ngữ cảnh hệ thống là `SystemContextRawRead`, nên nếu ruột
    che lỡ tra bảng thì test này đỏ bằng một lỗi chứ không bằng một so sánh.
    Đây cũng là điều làm `_merge_nodes_then_upsert` của upstream an toàn: nó
    đọc `get_node` rồi ghi thẳng `description` cũ vào bản mới.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ctx = system_context(space="synth", policy_version="bam-gia")
    goc = dict(he["slots"])
    assert mask(goc, ctx, _khoa(he)) == goc
    # Kể cả khóa mà không vai nào thấy: đọc thô là đọc thô.
    assert mask(goc, ctx, "khoa:khong_ai_khai") == goc


# --- Cửa fail-closed ---------------------------------------------------------


def test_khoa_ngoai_quyen_cua_vai_la_fail_closed():
    """Khóa lọt tới tầng che mà ngoài tập L1+ nghĩa là filter phía trên hỏng.

    Che nó bằng luật của một loại nội dung mà vai không được thấy là fail-open
    im lặng: `masked_slots` không khai gì cho `bi_mat_ha_tang` với
    `tech_support` nên "không che gì" sẽ là kết quả.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-03"]
    ctx = _context("tech_support")
    assert _khoa(he) == "noi_bo:bi_mat_ha_tang"
    with pytest.raises(MaskItemOutOfPermission) as loi:
        mask(dict(he["slots"]), ctx, _khoa(he))
    assert loi.value.code == "MASK_ITEM_OUT_OF_PERMISSION"


def test_khoa_sai_dang_la_value_error_cua_core_keys():
    """Khóa không phải dạng `scope:content_type` nổ ngay ở phép tách."""
    ctx = _context("tech_support")
    with pytest.raises(ValueError):
        mask({"subject": "App01"}, ctx, "khong-co-dau-phan-tach")


def test_mot_cua_fail_closed_dung_cho_ca_ba_duong_doc():
    """`chunks`/`entities` ⊆ `hyperedges` nên hỏi một namespace là đủ.

    Đây là điều kiện làm cho cửa fail-closed chỉ cần một câu hỏi duy nhất. Nó
    đúng vì ngưỡng L2 chặt hơn L1 trên cùng tập scope, nhưng "đúng hôm nay"
    khác "được canh giữ" - nên canh ở đây.
    """
    from core.policy import LEVEL_ORDER, NAMESPACE_MIN_LEVEL

    # Bất biến thật nằm ở bảng ngưỡng, không ở hai file fixture: ngưỡng của
    # namespace mà cửa che hỏi phải là ngưỡng *thấp nhất* trong bảng, vì chỉ
    # khi đó tập khóa của nó chứa tập của mọi namespace khác. Hạ ngưỡng
    # `chunks` xuống L1, hay nâng `hyperedges` lên L2, là đỏ ngay ở đây chứ
    # không đỏ ở một assert Đo 1 nào đó vài story sau.
    nguong = {ns: LEVEL_ORDER[muc] for ns, muc in NAMESPACE_MIN_LEVEL.items()}
    assert MASK_NAMESPACE in nguong
    assert nguong[MASK_NAMESPACE] == min(nguong.values())

    # Rồi vẫn quét hai bảng fixture: bất biến đúng trên giấy mà sai trên dữ
    # liệu thật là chuyện đã xảy ra một lần ở story 1.5.
    bang_toi_gian = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    bang_nhi_phan = oracle.doc_bang_chinh_sach(oracle.POLICY_NHI_PHAN)
    assert MASK_NAMESPACE in oracle.MUC_TOI_THIEU_THEO_NAMESPACE
    for bang in (bang_toi_gian, bang_nhi_phan):
        for vai in bang["roles"]:
            duoc_phep = oracle.allowed_keys_ky_vong(bang, vai)
            assert duoc_phep["chunks"] <= duoc_phep[MASK_NAMESPACE], vai
            assert duoc_phep["entities"] <= duoc_phep[MASK_NAMESPACE], vai


# --- Hàm thuần: không biến đổi đầu vào tại chỗ -----------------------------


def test_mask_khong_bien_doi_dau_vao_tai_cho():
    """Bản ghi vào không được đổi; kho KV dùng chung một bản gốc cho mọi vai."""
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    goc = dict(he["slots"])
    ban_sao_de_so = dict(goc)

    da_che = mask(goc, _context("tech_support"), _khoa(he))

    assert goc == ban_sao_de_so
    assert da_che is not goc


# --- Đổi bảng là đổi hành vi che, không sửa code ---------------------------


def test_doi_bang_chinh_sach_la_doi_hanh_vi_che():
    """Chốt 3 của brief §6: baseline nhị phân `L1 -> L0` không cần sửa code.

    Cùng một hyperedge, cùng một vai, hai file YAML: bảng tối giản cho L1 nên
    che theo slot, bảng nhị phân cho L0 nên hyperedge vắng mặt hẳn và tầng che
    fail-closed thay vì trả về nội dung không che.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    goc = dict(he["slots"])

    da_che = mask(goc, _context("tech_support", oracle.POLICY_TOI_GIAN), _khoa(he))
    assert da_che["cause"] == dau_che("cause")

    with pytest.raises(MaskItemOutOfPermission):
        mask(goc, _context("tech_support", oracle.POLICY_NHI_PHAN), _khoa(he))


# --- Quét toàn bộ fixture × toàn bộ vai ------------------------------------


def test_moi_hyperedge_moi_vai_khop_oracle():
    """Bốn hyperedge × hai vai, không ca nào rơi ngoài đối chứng.

    Hyperedge mà vai không thấy thì không có "kết quả che" nào cả - lời gọi
    phải fail-closed, vì một bản ghi như vậy không được phép rời adapter.
    """
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    for vai in ("devops", "tech_support"):
        ctx = _context(vai)
        thay_duoc = set(
            oracle.hyperedge_thay_duoc(bang, vai, du_lieu_dung_tay.HYPEREDGES)
        )
        for he in du_lieu_dung_tay.HYPEREDGES:
            goc = dict(he["slots"])
            if he["id"] not in thay_duoc:
                with pytest.raises(MaskItemOutOfPermission):
                    mask(goc, ctx, _khoa(he))
                continue
            assert mask(goc, ctx, _khoa(he)) == oracle.ban_ghi_slot_ky_vong(
                bang, vai, he
            ), (vai, he["id"])


# --- Vai slot lạ và đầu vào sai kiểu: hai cửa fail-closed nhỏ ---------------


def test_dau_che_tu_choi_ten_ngoai_danh_muc_8_vai():
    """`dau_che` là hàm public mà `web/` ánh xạ nhãn hiển thị từ đó.

    Một tên lạ sinh ra một dấu che không tầng nào đọc được, nên nó là lỗi chứ
    không phải một chuỗi lạ đi tiếp.
    """
    for slot in SLOT_ROLES:
        assert dau_che(slot).startswith("[" + slot + ":")
    for xau in ("nguyen_nhan", "Cause", "", "owner "):
        with pytest.raises(SlotRoleUnknown) as loi:
            dau_che(xau)
        assert loi.value.code == "SLOT_ROLE_UNKNOWN"


def test_canh_khai_vai_ngoai_danh_muc_thi_no_chu_khong_bo_qua():
    """Vai lạ không bao giờ tra trúng `masked_slots`, nên im lặng là fail-open."""
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ban_ghi = {
        "node_id": "rel-HE-02",
        NEIGHBOR_FIELD: he["slots"]["cause"],
        SLOT_FIELD: "nguyen_nhan",
    }
    with pytest.raises(SlotRoleUnknown) as loi:
        mask(ban_ghi, _context("tech_support"), _khoa(he))
    assert loi.value.code == "SLOT_ROLE_UNKNOWN"


@pytest.mark.parametrize(
    "ket_qua",
    [
        pytest.param("một chuỗi", id="chuoi"),
        pytest.param([{"cause": "x"}], id="list_ban_ghi"),
        pytest.param(None, id="none"),
        pytest.param(42, id="so"),
    ],
)
def test_ket_qua_khong_phai_anh_xa_la_type_error(ket_qua):
    """Che là thay giá trị theo tên trường, không phải biến đổi văn bản.

    Ba adapter đều truyền vào một dict; một list bản ghi hay một chuỗi tới đây
    nghĩa là nơi gọi hiểu sai hợp đồng, và im lặng trả nguyên trạng ở ca đó là
    một đường không che gì.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    with pytest.raises(TypeError):
        mask(ket_qua, _context("tech_support"), _khoa(he))


def test_dau_che_khong_mang_so_luong():
    """Hai giá trị khác nhau của cùng một slot cho đúng một dấu che.

    Cố ý: một dấu che có số thứ tự sẽ nói "có 3 nguyên nhân bị che", mà số
    lượng cũng là thông tin về nội dung bị che. Cái giá là upstream khử trùng
    danh sách cạnh nên vài cạnh đã che rụng bớt - ghim luật ở đây để lần sau
    không ai "sửa" nó thành dấu che có số.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    ctx = _context("tech_support")
    mot = mask(
        {"node_id": "rel-HE-02", NEIGHBOR_FIELD: "nguyên nhân A", SLOT_FIELD: "cause"},
        ctx,
        _khoa(he),
    )
    hai = mask(
        {"node_id": "rel-HE-02", NEIGHBOR_FIELD: "nguyên nhân B", SLOT_FIELD: "cause"},
        ctx,
        _khoa(he),
    )
    assert mot[NEIGHBOR_FIELD] == hai[NEIGHBOR_FIELD] == dau_che("cause")


# --- Luật che cứng cho lân cận không khóa (AD-9, AD-5; story 2.1) ----------


def test_lan_can_khong_khoa_bi_che_o_moi_muc_tiet_lo():
    """Cờ không-khóa che tên lân cận bất kể mức tiết lộ, cùng hình dạng `owner`.

    Đo ở mức **L2**, chỗ `masked_slots` rỗng và không luật bảng nào còn hiệu
    lực: nếu luật này là một hàng trong bảng chính sách thì ở đây nó không che
    gì. Nó là luật AD-9 nên nó vẫn che.

    `subject` cố ý không nằm trong `masked_slots` của bất kỳ vai nào, nên tên
    lân cận này lẽ ra ra nguyên văn - đúng ca phân biệt hai luật.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-01"]  # runbook: L2 với tech_support
    ket_qua = mask(
        {
            "node_id": "rel-HE-01",
            NEIGHBOR_FIELD: "App01",
            SLOT_FIELD: "subject",
            NEIGHBOR_NO_KEY_FIELD: True,
        },
        _context("tech_support"),
        _khoa(he),
    )
    assert ket_qua[NEIGHBOR_FIELD] == dau_che_lan_can_khong_khoa()
    assert "App01" not in ket_qua.values()


def test_lan_can_co_khoa_o_slot_khong_bi_che_van_ra_nguyen_van():
    """Đối chứng: cờ tắt thì luật này không chạm gì.

    Không có ca này thì một luật che *mọi* lân cận cũng làm test trên xanh, và
    khi đó tầng che vừa cắt mất đúng phần nội dung mà vai được đọc.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-01"]
    ket_qua = mask(
        {
            "node_id": "rel-HE-01",
            NEIGHBOR_FIELD: "App01",
            SLOT_FIELD: "subject",
            NEIGHBOR_NO_KEY_FIELD: False,
        },
        _context("tech_support"),
        _khoa(he),
    )
    assert ket_qua[NEIGHBOR_FIELD] == "App01"


def test_luat_khong_khoa_thang_luat_bang_khi_ca_hai_ap_dung():
    """Lân cận vừa không khóa vừa điền vào slot đang bị che: lý do là "không khóa".

    Hai lý do khác nguồn nên chúng phải phân biệt được: `masked` hết hiệu lực
    khi đổi bảng chính sách, `no_key` thì không. Trộn chúng là mất đúng khả
    năng phân biệt mà đầu `core/masking.py` đã dặn.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]  # bao_cao_su_co: L1 với tech_support
    ket_qua = mask(
        {
            "node_id": "rel-HE-02",
            NEIGHBOR_FIELD: "chỉnh sai giới hạn bộ nhớ PHP-FPM",
            SLOT_FIELD: "cause",  # nằm trong masked_slots của tech_support
            NEIGHBOR_NO_KEY_FIELD: True,
        },
        _context("tech_support"),
        _khoa(he),
    )
    assert ket_qua[NEIGHBOR_FIELD] == dau_che_lan_can_khong_khoa()
    assert ket_qua[NEIGHBOR_FIELD] != dau_che("cause")


def test_ngu_canh_he_thong_van_doc_tho_lan_can_khong_khoa():
    """Cờ system đọc thô, như mọi luật che khác - ingest cần tên thật.

    `_merge_nodes_then_upsert` của upstream đọc rồi ghi lại chính giá trị đó
    (`operate.py:194`), nên một dấu che chạy qua đường ingest sẽ ghi đè dữ liệu
    thật trong graph.
    """
    ket_qua = mask(
        {
            "node_id": "rel-HE-01",
            NEIGHBOR_FIELD: "App01",
            SLOT_FIELD: "subject",
            NEIGHBOR_NO_KEY_FIELD: True,
        },
        system_context(space="synth", policy_version="v"),
        _khoa(du_lieu_dung_tay.THEO_ID["HE-01"]),
    )
    assert ket_qua[NEIGHBOR_FIELD] == "App01"


def test_dau_che_lan_can_khong_trung_dau_che_cua_vai_slot_nao():
    """Bốn lý do che phải phân biệt được, kể cả khi so bằng chuỗi.

    `la_dau_che` nhận diện bằng cách dựng lại, nên một dấu che mới trùng dấu
    che của một vai slot sẽ làm hai luật khác nguồn không phân biệt được nữa.
    """
    dau = dau_che_lan_can_khong_khoa()
    assert dau not in {dau_che(slot) for slot in SLOT_ROLES}
    assert la_dau_che(dau), "dấu che mới phải tra ngược được qua get_node"
