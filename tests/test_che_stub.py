"""1.2-UNIT-005: stub tầng che và danh sách đóng method phải che (AD-9).

Story này chỉ chốt chữ ký và danh mục để story 1.3-1.5 gọi được từ đầu; ruột
hàm che viết ở story 1.6 mà không mở lại adapter. Vì vậy test ở đây khóa chặt
hình dạng chứ chưa khóa hành vi che.

Danh sách method phải che được đối chiếu với chính interface của upstream:
method nào đổi tên bên `vendor/` là test đỏ ngay, không trôi dạt âm thầm.
"""

import inspect

from hypergraphrag.base import BaseGraphStorage, BaseKVStorage, BaseVectorStorage

from core.masking import MASKED_READ_METHODS, mask
from core.permission import user_context
from core.slots import OWNER_SLOT, SLOT_ROLES
from tests.fixtures import du_lieu_dung_tay, oracle


def _context(vai: str = "tech_support"):
    from adapters.policy_loader import load_policy

    policy = load_policy(oracle.POLICY_TOI_GIAN)
    return user_context(
        policy=policy, role=vai, space="synth", real_account="tk_" + vai
    )


def test_chu_ky_ba_tham_so():
    """Chữ ký cố định từ T1: (kết quả, context, khóa hyperedge)."""
    tham_so = list(inspect.signature(mask).parameters.values())
    assert len(tham_so) == 3
    assert all(
        p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and p.default is p.empty
        for p in tham_so
    )


def test_grant_rong_tra_nguyen_trang():
    """Stub trả nguyên trạng để adapter gọi được ngay từ story 1.3."""
    ctx = _context()
    assert ctx.grant_ids == ()
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    khoa = he["scope"] + ":" + he["content_type"]
    ket_qua = dict(he["slots"])
    assert mask(ket_qua, ctx, khoa) == ket_qua


def test_danh_sach_dong_doc_duoc_o_runtime():
    """Danh sách đóng 4 method phải che, đọc được để adapter phản chiếu."""
    assert MASKED_READ_METHODS == frozenset(
        {"query", "get_node", "get_edge", "get_node_edges"}
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


def test_oracle_ky_vong_che_dung_theo_bang():
    """Oracle tính đúng kỳ vọng che, để story 1.6 có đối chứng sẵn.

    Chưa chấm hành vi của `mask` (ruột còn rỗng), chỉ chốt con số kỳ vọng mà
    story 1.6 phải làm cho khớp.
    """
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

    Quan hệ ghim ở đây là hợp đồng mà story 1.6 phải cài: cái hệ đọc từ bảng
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
    bắt được việc đó.
    """
    from core.policy import LEVEL_ORDER, NAMESPACE_MIN_LEVEL

    assert oracle.THU_TU_MUC == dict(LEVEL_ORDER)
    assert oracle.MUC_TOI_THIEU_THEO_NAMESPACE == dict(NAMESPACE_MIN_LEVEL)
