"""Bảng nhóm phụ trách và dấu che `owner` mang tên nhóm (story 3.1, ADR-011).

Bốn hàng I/O Matrix của story: bảng hỏng là từ chối cả file, che `owner` khi
tra được nhóm, che `owner` khi loại nội dung không khai nhóm, và hyperedge
không có vai `owner` vẫn nhận được dấu che mang tên nhóm.

Kỳ vọng lấy từ `tests/fixtures/oracle.py` - bản đọc YAML viết độc lập, không đi
qua loader của `adapters/` - đúng luật của Epic 1: dùng chung hàm với hệ thì
test chỉ chứng minh hệ nhất quán với chính nó.
"""

import pytest

from adapters.nhom_phu_trach import (
    DUONG_DAN_MAC_DINH,
    BangNhomPhuTrach,
    NhomPhuTrachInvalid,
    bang_nhom_mac_dinh,
    nap_nhom,
    tai_nhom_phu_trach,
)
from adapters.sensitivity_loader import bang_hang_mac_dinh
from core.masking import (
    OWNER_GROUP_FIELD,
    OwnerGroupInvalid,
    dau_che,
    dau_che_owner,
    la_dau_che,
    mask,
)
from core.slots import OWNER_SLOT, SLOT_ROLES
from adapters.policy_loader import load_policy
from tests.fixtures import du_lieu_dung_tay, oracle
from tests.ngu_canh import vai as ngu_canh_vai


def _context(vai: str):
    return ngu_canh_vai(load_policy(oracle.POLICY_TOI_GIAN), vai, "synth")


def _khoa(he) -> str:
    return oracle.khoa_ky_vong(he["scope"], he["content_type"])


# --- Bảng: hình dạng, và mọi cách hỏng là một mã ----------------------------


def test_bang_phu_dung_13_loai_noi_dung():
    """Bảng khai đủ 13 loại của `config/hang-do-nhay.yaml`, không thừa loại nào.

    Không bắt buộc về mặt cơ chế (loại chưa khai rơi về `[owner:group]`), nhưng
    một loại thiếu là một dấu che câm ở đúng chỗ FR-14 cần nói ra nhóm, nên nó
    phải là một quyết định chứ không phải một hàng bị quên.
    """
    nhom = nap_nhom()
    assert set(nhom) == set(bang_hang_mac_dinh().hang)
    assert len(nhom) == 13
    assert dict(nhom) == oracle.doc_bang_nhom()


def test_bang_mac_dinh_nap_mot_lan_cho_moi_tien_trinh():
    """Đóng băng trong một tiến trình, cùng luật với bảng hạng độ nhạy."""
    assert bang_nhom_mac_dinh() is bang_nhom_mac_dinh()
    assert bang_nhom_mac_dinh().version == tai_nhom_phu_trach(DUONG_DAN_MAC_DINH).version


def test_version_la_sha256_cua_chinh_file():
    """Đổi một tên nhóm là đổi văn bản ngữ cảnh mọi vai đọc được, nên có phiên bản."""
    assert bang_nhom_mac_dinh().version == oracle.bam_file_chinh_sach(DUONG_DAN_MAC_DINH)


BANG_HONG = {
    "goc_khong_phai_mapping": "- version: 1\n",
    "goc_rong": "",
    "khoa_la_o_goc": "version: 1\nnhom: {runbook: DevOps}\ngroups: {runbook: X}\n",
    "version_sai": "version: 2\nnhom: {runbook: DevOps}\n",
    "version_thieu": "nhom: {runbook: DevOps}\n",
    "version_la_bool": "version: true\nnhom: {runbook: DevOps}\n",
    "khoi_rong": "version: 1\nnhom: {}\n",
    "khoi_khong_phai_bang": "version: 1\nnhom: [runbook]\n",
    # Một loại nội dung không có hạng là một hàng không bao giờ tra trúng: dấu
    # che vẫn rơi về hằng cũ và không ai biết vì sao.
    "loai_noi_dung_la": "version: 1\nnhom: {runbok: DevOps}\n",
    "ten_nhom_rong": 'version: 1\nnhom: {runbook: ""}\n',
    "ten_nhom_khong_phai_chuoi": "version: 1\nnhom: {runbook: 12}\n",
    "ten_nhom_co_khoang_trang": 'version: 1\nnhom: {runbook: " DevOps "}\n',
    # Dấu che nhận diện bằng cách **dựng lại**; một tên mang dấu ngoặc làm phép
    # dựng và phép nhận diện đọc ngược nhau.
    "ten_nhom_co_ngoac": 'version: 1\nnhom: {runbook: "DevOps]"}\n',
    "ten_nhom_co_hai_cham": 'version: 1\nnhom: {runbook: "noi_bo:DevOps"}\n',
    "khoa_trung": "version: 1\nnhom:\n  runbook: DevOps\n  runbook: Data Center\n",
    # Hai ca mà `core.ids.normalize_id` viết lại tên nhóm, nên chuỗi dựng lại
    # từ bảng không khớp chuỗi đã chuẩn hóa ở vị trí id.
    "ten_nhom_khong_nfc": (
        "version: 1\nnhom: {runbook: \"Ha\u0300 tâ\u0300ng\"}\n"
    ),
    "ten_nhom_boc_nhay_kep": 'version: 1\nnhom: {runbook: \'"DevOps"\'}\n',
    "yaml_hong": "version: 1\nnhom: {\n",
}


@pytest.mark.parametrize("ten", sorted(BANG_HONG))
def test_bang_hong_thi_tu_choi_ca_file(tmp_path, ten):
    """Mọi cách hỏng ra một mã `NHOM_PHU_TRACH_INVALID`, không nạp bảng rỗng."""
    xau = tmp_path / f"{ten}.yaml"
    xau.write_text(BANG_HONG[ten], encoding="utf-8")
    with pytest.raises(NhomPhuTrachInvalid) as loi:
        tai_nhom_phu_trach(xau)
    assert loi.value.code == "NHOM_PHU_TRACH_INVALID"
    assert ten in str(loi.value), "thông điệp phải kèm tên file"


def test_bang_thieu_file(tmp_path):
    with pytest.raises(NhomPhuTrachInvalid) as loi:
        tai_nhom_phu_trach(tmp_path / "khong-co.yaml")
    assert loi.value.code == "NHOM_PHU_TRACH_INVALID"


def test_thong_diep_neu_ten_muc_hong(tmp_path):
    """Lỗi phải nói **mục nào**, không chỉ nói file nào.

    Người sửa file đang nhìn vào 13 dòng; một thông điệp chỉ nói "bảng hỏng"
    bắt họ dò tay từng dòng.
    """
    xau = tmp_path / "nhom.yaml"
    xau.write_text('version: 1\nnhom: {runbook: DevOps, cmdb: ""}\n', encoding="utf-8")
    with pytest.raises(NhomPhuTrachInvalid) as loi:
        tai_nhom_phu_trach(xau)
    assert "cmdb" in str(loi.value)


def test_bang_bat_bien():
    """Bảng đã kiểm không sửa được tại chỗ: nó là cấu hình đóng băng của hệ."""
    with pytest.raises(TypeError):
        bang_nhom_mac_dinh().nhom["runbook"] = "X"
    assert isinstance(bang_nhom_mac_dinh(), BangNhomPhuTrach)


# --- Dấu che `owner` mang tên nhóm -----------------------------------------


def test_dau_che_owner_vang_nhom_bang_dung_hang_cu():
    """Không tra được nhóm thì `[owner:group]`, đúng hành vi trước story 3.1."""
    assert dau_che_owner(None) == "[owner:group]"
    assert dau_che_owner(None) == dau_che(OWNER_SLOT)


def test_dau_che_owner_mang_ten_nhom():
    assert dau_che_owner("DevOps") == "[owner:DevOps]"
    assert dau_che_owner("Tech Support") == oracle.dau_che_ky_vong("owner", "faq")


@pytest.mark.parametrize("xau", ["", "  ", " DevOps ", "Dev]Ops", "a:b", "[x", 12, True])
def test_ten_nhom_hong_thi_khong_dung_duoc_dau_che(xau):
    with pytest.raises(OwnerGroupInvalid) as loi:
        dau_che_owner(xau)
    assert loi.value.code == "OWNER_GROUP_INVALID"


def test_la_dau_che_nhan_ra_dau_che_nhom_khi_duoc_truyen_tap_nhom():
    """Nhận diện bằng cách **dựng lại**, nên nó cần tập nhóm đang hiệu lực.

    Không có tham số thì `get_node` chạy Cypher với một id không tồn tại, trả
    `None`, và `operate.py:1039` nổ `TypeError` - landmine mà story 1.6 đã gỡ
    một lần cho dấu che theo slot.
    """
    dau = dau_che_owner("DevOps")
    assert la_dau_che(dau, ()) is False
    assert la_dau_che(dau, bang_nhom_mac_dinh().ten_nhom) is True
    # Một tên entity thật bắt đầu bằng `[owner:` không được nhận nhầm: nhận
    # nhầm nghĩa là một fact có thật biến mất, thay bằng một node rỗng.
    assert la_dau_che("[owner:Không Có Nhóm Này]", bang_nhom_mac_dinh().ten_nhom) is False


def test_la_dau_che_doi_tap_nhom_chu_khong_co_mac_dinh():
    """Quên tập nhóm là `TypeError` ở dòng gọi, không phải `False` im lặng.

    Mặc định `()` chạy được và đúng cho mọi nơi gọi không quan tâm tới nhóm,
    nhưng nó là hình dạng fail-open: người gọi quên chỉ thấy `False`, và cái
    giá trả sau vài tầng là `operate.py:1039` nổ `TypeError` giữa `vendor/`.
    Bắt buộc thì chỗ quên hỏng ngay lúc người viết còn đang nhìn vào nó.

    sonlm chốt điều này khi duyệt diff `core/` của story 3.1.
    """
    with pytest.raises(TypeError):
        la_dau_che(dau_che_owner("DevOps"))


def test_dau_che_nhom_khong_trung_dau_che_cua_vai_slot_nao():
    """Bốn lý do che phải phân biệt được, kể cả khi so bằng chuỗi."""
    theo_slot = {dau_che(s) for s in SLOT_ROLES if s != OWNER_SLOT}
    for nhom in bang_nhom_mac_dinh().ten_nhom:
        assert dau_che_owner(nhom) not in theo_slot


# --- Tầng che: ba hàng I/O Matrix ------------------------------------------


def test_che_owner_khi_tra_duoc_nhom():
    """Hàng "Che `owner` khi tra được nhóm": khóa `noi_bo:runbook`."""
    he = du_lieu_dung_tay.THEO_ID["HE-01"]
    assert he["content_type"] == "runbook" and he["scope"] == "noi_bo"
    ban_ghi = dict(he["slots"]) | {OWNER_GROUP_FIELD: oracle.nhom_ky_vong("runbook")}

    da_che = mask(ban_ghi, _context("devops"), _khoa(he))

    assert da_che[OWNER_SLOT] == oracle.dau_che_ky_vong("owner", "runbook")
    assert da_che[OWNER_SLOT] == "[owner:DevOps]"
    assert he["slots"][OWNER_SLOT] not in " ".join(str(v) for v in da_che.values())


def test_che_owner_khi_loai_noi_dung_khong_khai_nhom():
    """Hàng "khóa ngoài bảng nhóm": rơi về `[owner:group]`, không ra nguyên văn."""
    he = du_lieu_dung_tay.THEO_ID["HE-01"]
    da_che = mask(dict(he["slots"]), _context("devops"), _khoa(he))
    assert da_che[OWNER_SLOT] == "[owner:group]"
    assert he["slots"][OWNER_SLOT] != da_che[OWNER_SLOT]


def test_hyperedge_khong_co_vai_owner_van_nhan_dau_che_mang_ten_nhom():
    """Hàng "Hyperedge không có vai `owner`" (229/281 hyperedge của `synth`).

    Thêm khóa, không bỏ khóa nào: hợp đồng `adapters/mask_contract.py` chỉ cấm
    **mất** trường. Cái giá là hệ lộ thêm bộ phận nào giữ tài liệu, và đó là
    quyết định của ADR-011 chứ không phải hệ quả phụ.
    """
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    he = du_lieu_dung_tay.THEO_ID["HE-04"]
    assert OWNER_SLOT not in he["slots"], "fixture phải giữ ca biên thiếu owner"
    loai = he["content_type"]
    ban_ghi = dict(he["slots"]) | {OWNER_GROUP_FIELD: oracle.nhom_ky_vong(loai)}

    da_che = mask(ban_ghi, _context("devops"), _khoa(he))

    assert da_che[OWNER_SLOT] == oracle.dau_che_ky_vong("owner", loai)
    # Đúng **một** khóa được thêm, và nó là `owner`. Trường vận chuyển còn lại
    # trong kết quả của `mask` vì hợp đồng cấm mất trường; adapter gỡ nó ở đầu
    # ra (`Neo4jACLGraphStorage._che`), nên kỳ vọng của oracle - bản ghi *rời
    # adapter* - không mang nó.
    assert set(da_che) - set(ban_ghi) == {OWNER_SLOT}
    assert not set(ban_ghi) - set(da_che), "che không bỏ khóa nào"
    ra_ngoai = {k: v for k, v in da_che.items() if k != OWNER_GROUP_FIELD}
    assert ra_ngoai == oracle.ban_ghi_slot_ky_vong(bang, "devops", he, co_nhom=True)


def test_ban_ghi_khong_mang_truong_nhom_thi_khong_bia_ra_khoa_owner():
    """Chunk của kho KV và point của kho vector giữ nguyên hình dạng cũ.

    Chỉ nơi gọi mới biết một bản ghi có phải một hyperedge hay không, nên điều
    kiện thêm khóa là *trường nhóm có mặt*, không phải *bản ghi có vai owner*.
    """
    he = du_lieu_dung_tay.THEO_ID["HE-02"]
    chunk = dict(du_lieu_dung_tay.CHUNK_THEO_ID["chunk-HE-02"])
    assert mask(chunk, _context("devops"), _khoa(he)) == chunk


def test_nhom_cua_tai_khoan_seed_nam_trong_bang_nhom():
    """`users.group_name` dùng chung danh mục giá trị với bảng nhóm (SPINE :223).

    Hai nguồn khác nhau nói cùng một danh mục: `config/tai-khoan.yaml` khai
    nhóm của *người*, `config/nhom-phu-trach.yaml` khai nhóm phụ trách *loại
    nội dung*. Không ràng buộc bằng cơ chế được - một người có thể thuộc một
    bộ phận không sở hữu loại tài liệu nào - nhưng hai bảng trôi khỏi nhau thì
    câu "liên hệ Tech Support" của FR-14 trỏ tới một nhóm không tài khoản nào
    thuộc về. Ca này bắt việc đó ở CI, và một ngoại lệ có thật sau này là một
    dòng miễn trừ kèm lý do, không phải một lần xóa test.
    """
    from adapters.identity_seed import nap_tai_khoan

    ten_nhom = set(bang_nhom_mac_dinh().ten_nhom)
    la = {m.tai_khoan.nhom for m in nap_tai_khoan()} - ten_nhom
    assert not la, f"nhóm của tài khoản seed không có trong bảng nhóm: {sorted(la)}"


def test_ten_nhom_trong_bang_that_la_diem_bat_dong_cua_normalize_id():
    """Mọi tên nhóm đang chạy phải sống sót qua `core.ids.normalize_id`.

    `get_node` chuẩn hóa id **trước** khi hỏi `la_dau_che`, còn `la_dau_che`
    dựng lại dấu che từ chính bảng này. Hai phép đó phải cho cùng một chuỗi,
    nếu không `get_node` trả `None` cho chính dấu che nó vừa sinh ra.
    """
    from core.ids import normalize_id

    for ten in bang_nhom_mac_dinh().ten_nhom:
        assert normalize_id(ten) == ten, ten


def test_bang_hang_hong_thi_van_ra_ma_cua_module_nay(tmp_path, monkeypatch):
    """Một mã lỗi cho mọi cách hỏng, kể cả cách hỏng đến từ bảng hạng.

    Không bọc lại thì `SENSITIVITY_RANKS_INVALID` thoát ra từ một cửa mà người
    gọi đang bắt `NhomPhuTrachInvalid`, và nó đi qua mọi handler.
    """
    from adapters import nhom_phu_trach as mod
    from adapters.sensitivity_loader import SensitivityRanksInvalid

    def _no():
        raise SensitivityRanksInvalid("bảng hạng hỏng")

    monkeypatch.setattr(mod, "bang_hang_mac_dinh", _no)
    xau = tmp_path / "nhom.yaml"
    xau.write_text("version: 1\nnhom: {runbook: DevOps}\n", encoding="utf-8")
    with pytest.raises(NhomPhuTrachInvalid) as loi:
        tai_nhom_phu_trach(xau)
    assert loi.value.code == "NHOM_PHU_TRACH_INVALID"
    assert "bảng hạng" in str(loi.value)


# --- Khe tiêm: bảng nhóm đọc từ `global_config` -----------------------------
#
# Trả khoản ledger "bảng nhóm phụ trách không cấu hình được qua `global_config`,
# khác bảng hạng độ nhạy đứng ngay cạnh nó". Bốn ca dưới đây chấm cả hai nửa của
# khe tiêm: cửa `bang_nhom_cho` cho bảng nào, và adapter graph dùng bảng nào.

BANG_NHOM_KHAC = "version: 1\nnhom: {runbook: Nhom Cua Test}\n"


def _ghi(tmp_path, ten: str, noi_dung: str):
    duong = tmp_path / ten
    duong.write_text(noi_dung, encoding="utf-8")
    return duong


def test_cau_hinh_tro_sang_bang_nhom_khac_thi_adapter_dung_bang_do(tmp_path):
    """Đúng hình dạng `bang_hang_cho`: một engine trỏ sang file khác thì dùng file đó."""
    from adapters.nhom_phu_trach import NHOM_PHU_TRACH_KEY, bang_nhom_cho
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.ho_tro_neo4j import dung_adapter

    duong = _ghi(tmp_path, "nhom.yaml", BANG_NHOM_KHAC)
    cau_hinh = {NHOM_PHU_TRACH_KEY: str(duong)}

    assert bang_nhom_cho(cau_hinh).nhom_cua("runbook") == "Nhom Cua Test"
    adapter = dung_adapter(Neo4jGhiLai(), **cau_hinh)
    assert adapter._nhom_phu_trach("noi_bo:runbook") == "Nhom Cua Test"
    # Tập nhóm mà `la_dau_che` dựng lại cũng phải là của bảng đang chạy: lấy
    # bảng của repo ở đó nghĩa là `get_node` không nhận ra chính dấu che mà
    # `_che` vừa sinh, rồi `vendor/.../operate.py:1039` nổ `TypeError`.
    assert adapter._bang_nhom.ten_nhom == frozenset({"Nhom Cua Test"})


def test_vang_khoa_thi_dung_dung_bang_cua_repo():
    """Vắng khóa là bảng chốt của repo, và là **đúng đối tượng đã nhớ**.

    Nạp lại một bản sao cũng cho cùng nội dung, nên một ca so nội dung sẽ không
    thấy đường chạy hôm nay đọc thêm một file ở mỗi lần dựng adapter.
    """
    from adapters.nhom_phu_trach import bang_nhom_cho
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.ho_tro_neo4j import dung_adapter

    assert bang_nhom_cho(None) is bang_nhom_mac_dinh()
    assert bang_nhom_cho({}) is bang_nhom_mac_dinh()
    assert dung_adapter(Neo4jGhiLai())._bang_nhom is bang_nhom_mac_dinh()


def test_bang_nhom_doi_chieu_voi_bang_hang_cua_cung_cau_hinh(tmp_path):
    """Loại nội dung đối chiếu với bảng hạng **của chính cấu hình đó**.

    Đây là lỗi tiềm ẩn mà khe tiêm phải sửa cùng lúc: `_kiem` vốn gọi thẳng
    `bang_hang_mac_dinh()`, nên một engine trỏ `sensitivity_ranks_path` sang
    file khác thì bảng nhóm của nó bị chấm bằng bảng hạng *của repo*. Loại nội
    dung chỉ có ở bảng mới bị từ chối nạp, và hai bảng của một adapter chạy trên
    hai nguồn khác nhau.
    """
    from adapters.nhom_phu_trach import (
        NHOM_PHU_TRACH_KEY,
        bang_nhom_cho,
        tai_nhom_phu_trach,
    )
    from adapters.sensitivity_loader import SENSITIVITY_RANKS_KEY
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.ho_tro_neo4j import dung_adapter

    loai_moi = "loai_moi_cua_test"
    assert loai_moi not in bang_hang_mac_dinh().hang
    hang = _ghi(tmp_path, "hang.yaml", f"version: 1\nranks: {{runbook: 10, {loai_moi}: 99}}\n")
    nhom = _ghi(tmp_path, "nhom.yaml", f"version: 1\nnhom: {{{loai_moi}: Nhom Moi}}\n")
    cau_hinh = {SENSITIVITY_RANKS_KEY: str(hang), NHOM_PHU_TRACH_KEY: str(nhom)}

    assert bang_nhom_cho(cau_hinh).nhom_cua(loai_moi) == "Nhom Moi"
    assert dung_adapter(Neo4jGhiLai(), **cau_hinh)._nhom_phu_trach(
        f"noi_bo:{loai_moi}"
    ) == "Nhom Moi"
    # Cùng file nhóm ấy, đối chiếu với bảng hạng của repo, phải bị từ chối: đó
    # là phép đo cho thấy ca trên thật sự đọc bảng hạng của cấu hình.
    with pytest.raises(NhomPhuTrachInvalid) as loi:
        tai_nhom_phu_trach(nhom)
    assert loai_moi in str(loi.value)


def test_bang_hang_hep_khong_lam_bang_nhom_cua_repo_hong(tmp_path):
    """Trỏ riêng `sensitivity_ranks_path` không kéo theo bảng nhóm của repo.

    Bảng nhóm của repo giữ nguyên cặp của nó với `config/hang-do-nhay.yaml`, nên
    một bảng hạng hẹp - thứ bộ test và `eval/` vẫn dựng để đảo thứ tự hai loại -
    không từ chối 13 hàng vì một lý do không liên quan tới chúng. Phép đối chiếu
    bắt lỗi gõ trong một file so với bảng hạng mà file đó được viết ra để đi
    cùng; nó không phải một phép ràng buộc giữa hai file bất kỳ.
    """
    from adapters.nhom_phu_trach import bang_nhom_cho
    from adapters.sensitivity_loader import SENSITIVITY_RANKS_KEY

    hang = _ghi(tmp_path, "hang.yaml", "version: 1\nranks: {runbook: 10}\n")
    assert bang_nhom_cho({SENSITIVITY_RANKS_KEY: str(hang)}) is bang_nhom_mac_dinh()
