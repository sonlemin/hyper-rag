"""Citation theo quyền (story 3.4, FR-14, FR-15).

Đặc tả viết trước cơ chế (FR-27): mọi hàng I/O Matrix của story nằm ở đây, cộng
bốn mệnh đề mà không hàng nào phát biểu được một mình.

- **Citation đứng trên ngữ cảnh truy hồi cộng cửa quyền của adapter, không trên
  `answer`.** Mọi assert của file so tập citation với oracle (`tests/fixtures/
  oracle.py`, độc lập với `core/`), với dấu che trong ngữ cảnh, và với câu
  Cypher đã gửi. Không assert nào đọc văn bản câu trả lời (chốt brief §6).
- **Một luật một chỗ.** `masked_slots` của citation và dấu che của `mask` cùng
  đọc `core.masking.vai_phai_che`; ca đột biến thay hàm ấy và đòi **cả hai**
  đổi theo - nếu một bên tự tính lại thì bên đó không đổi, và test đỏ.
- **L0 vô hình tuyệt đối.** Kiểm ở tầng truy hồi bằng oracle: id của hyperedge
  L0 đưa thẳng vào cửa quyền của adapter dưới vai không thấy nó thì vắng mặt,
  và số citation không đếm nó.
- **Lượt từ chối không đổi một byte so với 3.5.** `KetQuaHoiDap` cấm "từ chối
  mà có citation" lúc dựng, envelope từ chối vẫn `citations: []`, và audit
  `query` mang tuple rỗng.

Ba lớp. Lớp hàm thuần (`adapters/trich_dan.py`, `adapters/tra_loi.py`,
`core/masking.py`) chấm bộ đọc cột `hyperedge`, hai hàm suy mức và tập che, và
hình dạng `TrichDan`. Lớp engine chạy cổng M1 thật (ba adapter, LLM giả) và
chấm citation với oracle, Cypher của cửa quyền, thứ tự và số lời gọi LLM. Lớp
HTTP chấm envelope, serializer và audit - với engine giả **và** với engine M1
thật qua hai tài khoản seed.
"""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypergraphrag.utils import list_of_list_to_csv, process_combine_contexts

from adapters import engine as engine_mod
from adapters.tra_loi import (
    LY_DO_NGU_CANH_RONG,
    KetQuaHoiDap,
    id_hyperedge_trong,
)
from adapters.trich_dan import (
    KHOA_TRICH_DAN,
    MUC_TRICH_DAN,
    TrichDan,
    TrichDanNgoaiQuyen,
    dung_danh_sach,
    dung_trich_dan,
)
from api import main as api_main
from api.hoi_dap import (
    KHOA_ENVELOPE,
    MA_TRICH_DAN_NGOAI_QUYEN,
    dict_trich_dan,
    dung_envelope,
    graph_rong,
)
from api.xac_thuc import BIEN_KHOA_KY
from core.audit import EVENT_QUERY, EVENT_REFUSAL
from core.masking import (
    OWNER_GROUP_FIELD,
    MaskItemOutOfPermission,
    dau_che,
    dau_che_owner,
    mask,
    muc_tiet_lo,
    vai_phai_che,
)
from core.permission import use_context
from core.slots import OWNER_SLOT, SLOT_ROLES
from tests.fixtures import oracle
from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.gia_lap_neo4j import canh_moi_bien_deu_bi_loc
from tests.ho_tro_m1 import CAU_HOI, chunk_trong, cong_m1, ten_hyperedge_ky_vong
from tests.nap_kho import ten_hyperedge
from tests.ngu_canh import vai
from tests.test_tu_choi import khung_ngu_canh
from tests.test_xac_thuc import KHOA_TEST, MAT_KHAU, TEN_GO, AuditGia, EngineGia, KhoGia, _dong

GOC = Path(__file__).resolve().parent.parent
ADR_016 = GOC / "docs" / "adr" / "ADR-016-citation-tu-tang-truy-hoi-va-dau-che-trong-answer.md"

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

HAI_VAI = ("devops", "tech_support")


# --- Lớp 1: hàm thuần ------------------------------------------------------------


def _bang_quan_he(*hang) -> str:
    """Khối Relationships đúng như nhánh đơn của vendor dựng (`csv.writer`)."""
    return list_of_list_to_csv([["id", "hyperedge", "related_entities"], *hang])


def test_doc_id_o_cot_hyperedge_khu_trung_giu_thu_tu():
    """Cột `hyperedge` là nguồn duy nhất; trùng thì giữ lần đầu, thứ tự giữ nguyên."""
    khoi = _bang_quan_he([0, "he-b", "x|y"], [1, "he-a", "z"], [2, "he-b", "w"])
    assert id_hyperedge_trong(khung_ngu_canh(relations=khoi)) == ("he-b", "he-a")


def test_doc_duoc_ca_hai_hinh_dang_cua_khoi_relationships():
    """Nhánh `hybrid` viết lại bảng bằng `process_combine_contexts` (`",\\t"`, không quote).

    Cùng một bộ đọc phải cho cùng dãy id trên cả hai hình dạng, và giá trị có
    dấu phẩy ở cột **sau** `hyperedge` không làm cột `hyperedge` đọc sai.
    """
    hl = _bang_quan_he([0, "he-1", "a, b|c"], [1, "he-2", 'd "e" f'])
    ll = _bang_quan_he([0, "he-3", "g"], [1, "he-1", "h"])
    hybrid = process_combine_contexts(hl, ll)
    assert ",\t" in hybrid, "bộ test dựng nhầm, không phải hình dạng hybrid của vendor"
    assert id_hyperedge_trong(khung_ngu_canh(relations=hl)) == ("he-1", "he-2")
    assert id_hyperedge_trong(khung_ngu_canh(relations=hybrid)) == ("he-1", "he-2", "he-3")


def test_ten_entity_mo_dau_bang_nhay_kep_khong_nuot_dong_ke():
    """Đọc từng dòng: một `"` mở ở `related_entities` không làm mất id của dòng sau.

    Ở dạng hybrid dấu nháy không còn được quote lại, nên một bộ đọc cả khối sẽ
    coi `"` ấy là mở một ô nhiều dòng và nuốt các dòng kế - mất citation lặng
    lẽ. Ca này đỏ với bộ đọc cả khối và xanh với bộ đọc từng dòng.
    """
    hl = _bang_quan_he([0, "he-1", '"ten co nhay|x'], [1, "he-2", "y"])
    hybrid = process_combine_contexts(hl, "")
    assert id_hyperedge_trong(khung_ngu_canh(relations=hybrid)) == ("he-1", "he-2")


@pytest.mark.parametrize(
    "chuoi",
    [
        "không phải khung",
        "",
        None,
        khung_ngu_canh(relations="id,khac\n0,x"),
        khung_ngu_canh(),
        khung_ngu_canh(relations="id,hyperedge,related_entities"),
    ],
    ids=["chuoi_thuong", "rong", "none", "thieu_cot", "khung_rong", "chi_header"],
)
def test_khong_phai_khung_hay_khong_co_dong_thi_rong(chuoi):
    """Hàng "Ngữ cảnh không phải khung vendor": danh sách id rỗng, không nổ."""
    assert id_hyperedge_trong(chuoi) == ()


def _ctx(policy, ten_vai: str, khong_gian: str):
    return vai(policy, ten_vai, khong_gian)


def test_muc_tiet_lo_suy_tu_allowed_keys_va_khop_oracle(policy, bang, khong_gian):
    """`level` đọc từ tập khóa của ngữ cảnh, không tra lại bảng, và bằng `muc_ky_vong`."""
    for ten_vai in HAI_VAI:
        ctx = _ctx(policy, ten_vai, khong_gian)
        for he in HYPEREDGES:
            khoa = oracle.khoa_ky_vong(he["scope"], he["content_type"])
            if he["id"] not in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES):
                with pytest.raises(MaskItemOutOfPermission):
                    muc_tiet_lo(ctx, khoa)
                continue
            assert muc_tiet_lo(ctx, khoa) == oracle.muc_ky_vong(bang, ten_vai, he["content_type"])


def test_vai_phai_che_la_bang_khai_hop_owner(policy, bang, khong_gian):
    """Luật = phần bảng khai (đọc độc lập qua oracle) hợp `owner`; loại chưa khai chỉ còn `owner`."""
    for ten_vai in HAI_VAI:
        ctx = _ctx(policy, ten_vai, khong_gian)
        khai = oracle.masked_slots_ky_vong(bang, ten_vai)
        for loai in bang["roles"][ten_vai]["disclosure"]:
            assert vai_phai_che(ctx, loai) == frozenset(khai.get(loai, set())) | {OWNER_SLOT}, (ten_vai, loai)
        assert vai_phai_che(ctx, "loai_khong_ai_khai") == frozenset({OWNER_SLOT})
    assert any(khai for khai in (oracle.masked_slots_ky_vong(bang, v) for v in HAI_VAI)), "bảng không khai gì để kiểm"


def test_mask_va_citation_cung_doc_mot_ham_dot_bien(monkeypatch, policy, khong_gian):
    """Đột biến: thay `vai_phai_che` thì **cả** dấu che lẫn `masked_slots` đổi theo.

    Nếu `mask` hay `dung_trich_dan` tự tính lại luật thay vì gọi hàm chung thì
    bên đó không đổi, và một trong hai assert dưới đỏ. Đây là cơ chế giữ cho
    citation không trôi khỏi dấu che, thay cho một câu trong docstring.
    """
    ctx = _ctx(policy, "devops", khong_gian)
    he = THEO_ID["HE-01"]
    khoa = oracle.khoa_ky_vong(he["scope"], he["content_type"])
    truoc_che = mask(dict(he["slots"]), ctx, khoa)
    truoc_td = dung_trich_dan(ctx, "x", khoa, he["slots"], None)
    assert truoc_che["condition"] == he["slots"]["condition"]
    assert truoc_td.masked_slots == ("owner",)

    import core.masking as m

    monkeypatch.setattr(m, "vai_phai_che", lambda c, ct: frozenset({"condition", OWNER_SLOT}))
    sau_che = mask(dict(he["slots"]), ctx, khoa)
    sau_td = dung_trich_dan(ctx, "x", khoa, he["slots"], None)
    assert sau_che["condition"] == dau_che("condition"), "mask không gọi vai_phai_che"
    assert sau_td.masked_slots == ("condition", "owner"), "citation không gọi vai_phai_che"


def test_citation_khop_dau_che_that_tren_tung_hyperedge(policy, bang, khong_gian):
    """`masked_slots` bằng đúng tập khóa mà `mask` đã thay giá trị trên bản ghi."""
    for ten_vai in HAI_VAI:
        ctx = _ctx(policy, ten_vai, khong_gian)
        for he in HYPEREDGES:
            if he["id"] not in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES):
                continue
            khoa = oracle.khoa_ky_vong(he["scope"], he["content_type"])
            da_che = mask(dict(he["slots"]), ctx, khoa)
            bi_thay = {s for s, v in he["slots"].items() if da_che[s] != v}
            td = dung_trich_dan(ctx, he["id"], khoa, he["slots"], None)
            assert set(td.masked_slots) == bi_thay == oracle.slot_phai_che(bang, ten_vai, he)
            assert td.level == oracle.muc_ky_vong(bang, ten_vai, he["content_type"])


def test_hyperedge_khong_co_owner_va_loai_chua_khai_nhom(policy, khong_gian):
    """Hai hàng I/O Matrix: không vai `owner` thì `owner` không vào `masked_slots`;
    bảng nhóm không có hàng thì `owner_group: null` mà `masked_slots` vẫn đúng."""
    ctx = _ctx(policy, "devops", khong_gian)
    he4 = THEO_ID["HE-04"]
    td = dung_trich_dan(
        ctx, "HE-04", oracle.khoa_ky_vong(he4["scope"], he4["content_type"]), he4["slots"], "Tech Support"
    )
    assert "owner" not in td.masked_slots and td.masked_slots == ()
    assert td.owner_group == "Tech Support"
    ctx_ts = _ctx(policy, "tech_support", khong_gian)
    he2 = THEO_ID["HE-02"]
    td2 = dung_trich_dan(ctx_ts, "HE-02", "noi_bo:bao_cao_su_co", he2["slots"], None)
    assert td2.owner_group is None
    assert td2.masked_slots == ("cause", "remediation", "source", "owner")


def test_masked_slots_theo_thu_tu_slot_roles(policy, khong_gian):
    ctx = _ctx(policy, "tech_support", khong_gian)
    td = dung_trich_dan(ctx, "x", "noi_bo:bao_cao_su_co", reversed(SLOT_ROLES), None)
    assert td.masked_slots == tuple(v for v in SLOT_ROLES if v in td.masked_slots)
    assert list(td.masked_slots) == sorted(td.masked_slots, key=SLOT_ROLES.index)


@pytest.mark.parametrize(
    "sua",
    [
        {"level": "L0"},
        {"level": "L3"},
        {"masked_slots": ("owner", "cause")},
        {"masked_slots": ("cause", "cause")},
        {"masked_slots": ("la",)},
        {"masked_slots": ["cause"]},
        {"id": ""},
        {"owner_group": ""},
        {"owner_group": 3},
    ],
    ids=["l0", "l3", "sai_thu_tu", "lap", "vai_la", "list", "id_rong", "nhom_rong", "nhom_so"],
)
def test_trich_dan_tu_kiem_hinh_dang_luc_dung(sua):
    goc = dict(id="he-1", level="L1", scope="noi_bo", content_type="runbook", masked_slots=("cause", "owner"), owner_group=None)
    TrichDan(**goc)
    with pytest.raises((ValueError, TypeError)):
        TrichDan(**{**goc, **sua})


def test_muc_trich_dan_khong_co_l0():
    assert MUC_TRICH_DAN == frozenset({"L1", "L2"})


def test_ket_qua_hoi_dap_cam_tu_choi_ma_co_citation():
    td = TrichDan(id="he-1", level="L1", scope="noi_bo", content_type="runbook", masked_slots=(), owner_group=None)
    KetQuaHoiDap(cau_tra_loi="ok", trich_dan=(td,))
    KetQuaHoiDap(ly_do_tu_choi=LY_DO_NGU_CANH_RONG)
    with pytest.raises(ValueError):
        KetQuaHoiDap(ly_do_tu_choi=LY_DO_NGU_CANH_RONG, trich_dan=(td,))
    with pytest.raises(TypeError):
        KetQuaHoiDap(cau_tra_loi="ok", trich_dan=[td])
    with pytest.raises(TypeError):
        KetQuaHoiDap(cau_tra_loi="ok", trich_dan=({"id": "x"},))


def test_dung_danh_sach_giu_thu_tu_ngu_canh_va_doi_thieu_thanh_loi(policy, khong_gian):
    ctx = _ctx(policy, "devops", khong_gian)
    tu_adapter = {"b": ("noi_bo:runbook", ("subject", "owner")), "a": ("noi_bo:bi_mat_ha_tang", ("subject", "source"))}
    ds = dung_danh_sach(ctx, ("a", "b"), tu_adapter, lambda ct: {"runbook": "DevOps"}.get(ct))
    assert [td.id for td in ds] == ["a", "b"]
    assert ds[0].level == "L1" and ds[0].masked_slots == ("source",) and ds[0].owner_group is None
    assert ds[1].level == "L2" and ds[1].masked_slots == ("owner",) and ds[1].owner_group == "DevOps"
    with pytest.raises(TrichDanNgoaiQuyen) as loi:
        dung_danh_sach(ctx, ("a", "he-x"), tu_adapter, lambda ct: None)
    assert loi.value.code == "TRICH_DAN_NGOAI_QUYEN" == MA_TRICH_DAN_NGOAI_QUYEN
    assert "he-x" not in str(loi.value), "thông điệp lỗi không kể id ngữ cảnh ra"
    assert loi.value.ids == ("he-x",), "id thiếu đi theo ngoại lệ cho hàng permission_mismatch (3.6)"



def test_id_trong_ngu_canh_da_chuan_hoa_va_khu_trung_sau_chuan_hoa():
    """Patch review: id trả về đã `normalize_id`, khử trùng **sau** chuẩn hóa, khớp khóa dict của adapter."""
    khoi = _bang_quan_he([0, "  he-a ", "x"], [1, '"he-a"', "y"], [2, "he-a", "z"])
    assert id_hyperedge_trong(khung_ngu_canh(relations=khoi)) == ("he-a",)


def test_o_hyperedge_khong_chuan_hoa_duoc_la_ma_on_dinh():
    """Ô chỉ toàn dấu nháy: `normalize_id` từ chối -> `TrichDanNgoaiQuyen`, không `ValueError` trần."""
    khoi = _bang_quan_he([0, '""""', "x"])
    with pytest.raises(TrichDanNgoaiQuyen):
        id_hyperedge_trong(khung_ngu_canh(relations=khoi))


def test_hai_moc_vendor_cua_cot_hyperedge_khong_troi():
    """Grep `operate.py`: `"description": k[1]` ở :906 và `e["description"]` vào cột ở :794.

    Cùng khuôn với `tests/test_hoi_dap.py::test_so_loi_goi_embedding_moi_truy_van_khop_vendor`:
    docstring của `id_hyperedge_trong` trích hai số dòng, và một bản upstream
    mới dời chúng mà không ai thấy là docstring nói dối.
    """
    dong = (GOC / "vendor" / "hypergraphrag" / "operate.py").read_text(encoding="utf-8").splitlines()
    assert '"description": k[1]' in dong[906 - 1], dong[906 - 1]
    assert 'e["description"]' in dong[794 - 1], dong[794 - 1]
    assert dong[788 - 1].strip() == '["id", "hyperedge", "related_entities"]'
    assert dong[987 - 1].strip() == '["id", "hyperedge", "related_entities"]'
    assert '"hyperedge": k["hyperedge_name"]' in dong[953 - 1]


def test_dung_danh_sach_nhan_generator_mot_luot(policy, khong_gian):
    """Patch review: `ids` là iterator một lượt thì không được cạn ở vòng quét `thieu`."""
    ctx = _ctx(policy, "devops", khong_gian)
    tu_adapter = {"a": ("noi_bo:runbook", ("subject", "owner"))}
    ds = dung_danh_sach(ctx, (i for i in ["a"]), tu_adapter, lambda ct: None)
    assert [td.id for td in ds] == ["a"]
    with pytest.raises(TrichDanNgoaiQuyen):
        dung_danh_sach(ctx, (i for i in ["a", "x"]), tu_adapter, lambda ct: None)


@pytest.mark.parametrize(
    "khoa,cac_vai",
    [("khong-co-dau-hai-cham", ("subject",)), ("noi_bo:runbook", ("subject", "vai_la")), ("noi_bo:runbook", (None,))],
    ids=["khoa_khong_tach", "vai_la", "vai_none"],
)
def test_du_lieu_kho_hong_ra_ma_on_dinh(policy, khong_gian, khoa, cac_vai):
    """Khóa không tách được hay vai ngoài danh mục là `TrichDanNgoaiQuyen`, không `ValueError` trần."""
    ctx = _ctx(policy, "devops", khong_gian)
    with pytest.raises(TrichDanNgoaiQuyen):
        dung_trich_dan(ctx, "x", khoa, cac_vai, None)
    with pytest.raises(TrichDanNgoaiQuyen):
        dung_danh_sach(ctx, ("x",), {"x": (khoa, cac_vai)}, lambda ct: None)


def test_ngu_canh_he_thong_khong_dung_citation(policy, khong_gian):
    """Dưới cờ system: `TrichDanNgoaiQuyen` mang thông điệp rõ, không `SystemContextRawRead`."""
    from core.permission import SystemContextRawRead
    from tests.ngu_canh import ngu_canh_ingest

    ctx = ngu_canh_ingest(khong_gian, policy)
    for goi in (
        lambda: dung_trich_dan(ctx, "x", "noi_bo:runbook", ("subject",), None),
        lambda: dung_danh_sach(ctx, ("x",), {"x": ("noi_bo:runbook", ("subject",))}, lambda ct: None),
    ):
        with pytest.raises(TrichDanNgoaiQuyen) as loi:
            goi()
        assert "ngữ cảnh hệ thống" in str(loi.value)
        assert not isinstance(loi.value, SystemContextRawRead)


# --- Lớp 2: engine cổng M1 thật ----------------------------------------------------


def _engine(workspace_dir, khong_gian, policy):
    from tests.gia_lap_llm import phan_hoi_hai_luot

    engine, client, driver, llm = asyncio.run(cong_m1(workspace_dir, khong_gian, policy))
    llm.theo_prompt = phan_hoi_hai_luot()
    return engine, client, driver, llm


def _hoi_dap(engine, policy, ten_vai, khong_gian):
    async def chay():
        with use_context(vai(policy, ten_vai, khong_gian)):
            return await engine.hoi_dap(CAU_HOI)

    return asyncio.run(chay())


def _ngu_canh(engine, policy, ten_vai, khong_gian):
    from tests.ho_tro_m1 import hoi

    return asyncio.run(hoi(engine, vai(policy, ten_vai, khong_gian)))


def _ky_vong(bang, ten_vai) -> dict[str, dict]:
    """Citation kỳ vọng của một vai, tính thuần từ oracle và fixture."""
    ra = {}
    for he in HYPEREDGES:
        if he["id"] not in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES):
            continue
        ra[ten_hyperedge(he)] = {
            "id": ten_hyperedge(he),
            "level": oracle.muc_ky_vong(bang, ten_vai, he["content_type"]),
            "scope": he["scope"],
            "content_type": he["content_type"],
            "masked_slots": [v for v in SLOT_ROLES if v in oracle.slot_phai_che(bang, ten_vai, he)],
            "owner_group": oracle.nhom_ky_vong(he["content_type"]),
        }
    return ra


def test_ac1_hai_vai_cung_cau_citation_dung_oracle(workspace_dir, khong_gian, policy, bang):
    """AC-1 và ba hàng đầu I/O Matrix, trên engine M1 thật.

    Mỗi vai nhận đúng tập hyperedge mà oracle nói vai đó thấy từ L1 trở lên;
    mức từng citation bằng `muc_ky_vong`; `masked_slots` của citation L1 bằng
    `slot_phai_che` cộng `owner` nếu hyperedge có vai đó; L2 chỉ còn `owner`.
    Tập của `tech_support` là tập con thật sự của `devops`, và HE-03 (L0 với
    `tech_support`) không vào số đếm.
    """
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    theo_vai = {}
    for ten_vai in HAI_VAI:
        kq = _hoi_dap(engine, policy, ten_vai, khong_gian)
        assert kq.ly_do_tu_choi is None
        thay = {td.id: dict_trich_dan(td) for td in kq.trich_dan}
        assert thay == _ky_vong(bang, ten_vai), ten_vai
        assert set(thay) == ten_hyperedge_ky_vong(bang, ten_vai)
        theo_vai[ten_vai] = set(thay)
    assert theo_vai["tech_support"] < theo_vai["devops"]
    he3 = ten_hyperedge(THEO_ID["HE-03"])
    assert he3 in theo_vai["devops"] and he3 not in theo_vai["tech_support"]
    assert len(theo_vai["tech_support"]) == len(_ky_vong(bang, "tech_support"))


def test_hang_dau_io_matrix_viet_thang(workspace_dir, khong_gian, policy, bang):
    """`devops`: HE-01 (runbook, L2) chỉ che `owner`; HE-03 (bi_mat_ha_tang, L1) che
    theo bảng cộng `owner`, nhóm DevOps; HE-04 không có vai `owner` nên không che gì."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    thay = {td.id: td for td in _hoi_dap(engine, policy, "devops", khong_gian).trich_dan}
    he1 = thay[ten_hyperedge(THEO_ID["HE-01"])]
    assert (he1.level, he1.masked_slots, he1.owner_group) == ("L2", ("owner",), "DevOps")
    he3 = thay[ten_hyperedge(THEO_ID["HE-03"])]
    assert he3.level == "L1"
    assert set(he3.masked_slots) == oracle.slot_phai_che(bang, "devops", THEO_ID["HE-03"])
    assert "owner" in he3.masked_slots and he3.owner_group == "DevOps"
    he4 = thay[ten_hyperedge(THEO_ID["HE-04"])]
    assert he4.masked_slots == () and he4.owner_group == oracle.nhom_ky_vong("bao_cao_su_co")


def test_ac4_doi_ngau_namespace_he03_o_l1(workspace_dir, khong_gian, policy, bang):
    """AC 4: `devops` có citation HE-03 ở L1 **và** không thấy `chunk-HE-03`.

    Vế "có mặt" đỏ là lỗi truy hồi (citation thiếu một fact vai được thấy),
    không phải rò; vế "vắng" đỏ mới là rò (NFR-06).
    """
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    he3 = THEO_ID["HE-03"]
    assert oracle.muc_ky_vong(bang, "devops", he3["content_type"]) == "L1"
    kq = _hoi_dap(engine, policy, "devops", khong_gian)
    ids = [td.id for td in kq.trich_dan]
    assert ten_hyperedge(he3) in ids, (
        "citation HE-03 vắng: đây là LỖI TRUY HỒI (fact vai được thấy ở L1 không"
        " vào citation), không phải một dấu hiệu rò"
    )
    ngu_canh = _ngu_canh(engine, policy, "devops", khong_gian)
    assert "chunk-HE-03" not in chunk_trong(ngu_canh), "RÒ: chunk L2 lọt vào vai ở L1"


def test_citation_theo_thu_tu_xuat_hien_va_khop_dau_che_trong_ngu_canh(workspace_dir, khong_gian, policy):
    """Thứ tự citation = thứ tự cột `hyperedge`; dấu che trong ngữ cảnh khớp `masked_slots`."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    ngu_canh = _ngu_canh(engine, policy, "tech_support", khong_gian)
    kq = _hoi_dap(engine, policy, "tech_support", khong_gian)
    assert [td.id for td in kq.trich_dan] == list(id_hyperedge_trong(ngu_canh))
    for td in kq.trich_dan:
        for v in td.masked_slots:
            dau = dau_che_owner(td.owner_group) if v == OWNER_SLOT else dau_che(v)
            assert dau in ngu_canh, f"citation nói che {v} mà ngữ cảnh không có dấu {dau}"


def test_cypher_cua_cua_quyen_loc_du_ba_bien_va_dung_tap_khoa(workspace_dir, khong_gian, policy, bang):
    """Method mới lọc bằng đúng ba mệnh đề của `get_node_edges`: `h`, `r`, `e` đều ràng."""
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    for ten_vai in HAI_VAI:
        driver.xoa_nhat_ky()
        _hoi_dap(engine, policy, ten_vai, khong_gian)
        cau = [lg for lg in driver.cac_cau_doc() if lg.loai == "doc:trich_dan_cua"]
        assert len(cau) == 1, f"{ten_vai}: cửa quyền phải chạy đúng một lần mỗi lượt"
        canh_moi_bien_deu_bi_loc(cau[0].cypher)
        for bien in ("h", "r", "e"):
            assert f"{bien}.space = $space" in cau[0].cypher
        assert set(cau[0].params["keys"]) == oracle.allowed_keys_ky_vong(bang, ten_vai)["hyperedges"]
        assert cau[0].params["space"] == khong_gian


def test_l0_vang_o_tang_truy_hoi_theo_oracle(workspace_dir, khong_gian, policy, bang):
    """Đưa thẳng id của hyperedge L0 vào cửa quyền dưới vai không thấy nó: vắng mặt.

    Không dựa vào việc ngữ cảnh không mang id ấy (đó là tầng lọc); ca này hỏi
    chính cửa quyền, và cửa ấy phải nói "không" cho mọi id mà oracle xếp L0.
    """
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    graph = engine.chunk_entity_relation_graph
    ten = [ten_hyperedge(he) for he in HYPEREDGES]

    async def chay(ten_vai):
        with use_context(vai(policy, ten_vai, khong_gian)):
            return await graph.trich_dan_cua(ten)

    for ten_vai in HAI_VAI:
        ra = asyncio.run(chay(ten_vai))
        assert set(ra) == ten_hyperedge_ky_vong(bang, ten_vai), ten_vai
        for he in HYPEREDGES:
            if oracle.muc_ky_vong(bang, ten_vai, he["content_type"]) == "L0":
                assert ten_hyperedge(he) not in ra
        for id_he, (khoa, cac_vai) in ra.items():
            he = next(h for h in HYPEREDGES if ten_hyperedge(h) == id_he)
            assert khoa == oracle.khoa_ky_vong(he["scope"], he["content_type"])
            assert set(cac_vai) == set(he["slots"])
    with use_context(vai(policy, "tech_support", khong_gian)):
        assert asyncio.run(graph.trich_dan_cua([])) == {}


def test_id_adapter_khong_thay_la_loi_truoc_loi_goi_llm(monkeypatch, workspace_dir, khong_gian, policy):
    """Hàng "Id trong ngữ cảnh mà adapter không thấy": `TrichDanNgoaiQuyen`, LLM chỉ
    tốn lời gọi trích từ khóa, không lời gọi sinh câu trả lời."""
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    goc = engine_mod.id_hyperedge_trong
    monkeypatch.setattr(engine_mod, "id_hyperedge_trong", lambda nc: goc(nc) + ("he-x",))
    with pytest.raises(TrichDanNgoaiQuyen):
        _hoi_dap(engine, policy, "devops", khong_gian)
    assert llm.so_lan == 1, f"đã trả tiền cho lời gọi sinh câu trả lời: {llm.prompts}"


def test_ngu_canh_khong_phai_khung_van_tra_loi_voi_citation_rong(monkeypatch, workspace_dir, khong_gian, policy):
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)

    async def _aquery(query, param=None):
        return "một chuỗi không phải khung của vendor"

    monkeypatch.setattr(engine, "aquery", _aquery)
    driver.xoa_nhat_ky()
    kq = _hoi_dap(engine, policy, "devops", khong_gian)
    assert kq.ly_do_tu_choi is None and kq.trich_dan == ()
    assert not [lg for lg in driver.cac_cau_doc() if lg.loai == "doc:trich_dan_cua"]


def test_luot_tu_choi_tren_engine_that_khong_mang_citation(workspace_dir, khong_gian, policy):
    """`co_no_answer`: ngữ cảnh có id nhưng kết quả từ chối thì citation rỗng."""
    from tests.gia_lap_llm import phan_hoi_hai_luot

    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    llm.theo_prompt = phan_hoi_hai_luot(khong_co_dap_an=True, cau_tra_loi="")
    kq = _hoi_dap(engine, policy, "devops", khong_gian)
    assert kq.ly_do_tu_choi is not None and kq.trich_dan == ()


def test_owner_group_lay_tu_bang_nhom_cua_chinh_adapter(workspace_dir, khong_gian, policy, tmp_path):
    """Trỏ `owner_groups_path` sang bảng khác: `owner_group` đổi theo **cùng** bảng
    đã sinh dấu che trong ngữ cảnh, không phải bảng chốt của repo."""
    import yaml

    from tests.gia_lap_llm import LLMGia, phan_hoi_hai_luot
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine
    from tests.nap_kho import nap_ba_kho

    bang = yaml.safe_load(oracle.NHOM_PHU_TRACH.read_text(encoding="utf-8"))
    bang["nhom"]["runbook"] = "NhomKhac"
    del bang["nhom"]["bao_cao_su_co"]
    f = tmp_path / "nhom.yaml"
    f.write_text(yaml.safe_dump(bang, allow_unicode=True), encoding="utf-8")
    engine = dung_engine(
        workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), LLMGia(theo_prompt=phan_hoi_hai_luot()),
        owner_groups_path=str(f),
    )
    asyncio.run(nap_ba_kho(engine, khong_gian=khong_gian, policy=policy))
    thay = {td.id: td for td in _hoi_dap(engine, policy, "devops", khong_gian).trich_dan}
    assert thay[ten_hyperedge(THEO_ID["HE-01"])].owner_group == "NhomKhac"
    he2 = thay[ten_hyperedge(THEO_ID["HE-02"])]
    assert he2.owner_group is None and he2.masked_slots == ("owner",)
    ngu_canh = _ngu_canh(engine, policy, "devops", khong_gian)
    assert dau_che_owner("NhomKhac") in ngu_canh and dau_che_owner(None) in ngu_canh


# --- Lớp 3: HTTP ---------------------------------------------------------------------


def _td(id_he="he-1", **sua) -> TrichDan:
    goc = dict(id=id_he, level="L1", scope="noi_bo", content_type="runbook", masked_slots=("cause", "owner"), owner_group="DevOps")
    return TrichDan(**{**goc, **sua})


@pytest.mark.parametrize(
    "citation",
    [
        {k: v for k, v in dict_trich_dan(_td()).items() if k != "owner_group"},
        {**dict_trich_dan(_td()), "thua": 1},
        {**dict_trich_dan(_td()), "level": "L0"},
        {**dict_trich_dan(_td()), "level": "L3"},
        {**dict_trich_dan(_td()), "masked_slots": "cause"},
        {**dict_trich_dan(_td()), "id": ""},
        "he-1",
        {**dict_trich_dan(_td()), "masked_slots": ["la"]},
        {**dict_trich_dan(_td()), "masked_slots": ["owner", "cause"]},
        {**dict_trich_dan(_td()), "masked_slots": ["cause", "cause"]},
        {**dict_trich_dan(_td()), "owner_group": "  "},
        {**dict_trich_dan(_td()), "level": ["L1"]},
    ],
    ids=["thieu_khoa", "thua_khoa", "l0", "l3", "masked_khong_list", "id_rong", "khong_dict",
         "vai_la", "sai_thu_tu", "trung", "nhom_trang", "level_khong_hashable"],
)
def test_serializer_tu_choi_citation_sai_hinh(citation):
    """Hàng "Serializer nhận citation sai hình": `ValueError` ngay tại `dung_envelope`."""
    meta = {"role": "devops", "space": "synth", "policy_version": "v"}
    dung_envelope(answer="ok", refused=False, citations=[dict_trich_dan(_td())], graph=graph_rong(), meta=meta)
    with pytest.raises(ValueError):
        dung_envelope(answer="ok", refused=False, citations=[citation], graph=graph_rong(), meta=meta)
    with pytest.raises(ValueError):
        dung_envelope(answer=None, refused=True, citations=[dict_trich_dan(_td())], graph=graph_rong(), meta=meta)


def test_dict_trich_dan_dung_sau_khoa_dung_thu_tu():
    d = dict_trich_dan(_td())
    assert tuple(d) == KHOA_TRICH_DAN
    assert d["masked_slots"] == ["cause", "owner"] and isinstance(d["masked_slots"], list)


def _client(monkeypatch, kho, audit, engine):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo_kho():
        return kho

    async def _mo_audit():
        return audit

    async def _mo_engine(_audit):
        return engine

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    return TestClient(api_main.app)


def _kho_gia(khong_gian: str = "synth") -> KhoGia:
    from dataclasses import replace

    return KhoGia(
        {
            TEN_GO["ts01"]: replace(_dong("ts01"), khong_gian=khong_gian),
            TEN_GO["dev01"]: replace(_dong("dev01", role="devops", demo=True, admin=True), khong_gian=khong_gian),
        }
    )


def _hoi(client, tai_khoan: str):
    kq = client.post("/auth/login", json={"tai_khoan": TEN_GO[tai_khoan], "mat_khau": MAT_KHAU})
    assert kq.status_code == 200, kq.text
    return client.post("/hoi-dap", json={"cau_hoi": CAU_HOI}, headers={"Authorization": "Bearer " + kq.json()["token"]})


def test_ac2_audit_query_mang_id_cua_citations(monkeypatch):
    """AC-2: hàng `query` mang `hyperedge_ids` đúng bằng dãy `id` của citations."""
    audit = AuditGia()
    engine = EngineGia(trich_dan=(_td("he-2"), _td("he-1", level="L2", masked_slots=("owner",))))
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        kq = _hoi(client, "dev01")
    assert kq.status_code == 200, kq.text
    than = kq.json()
    assert tuple(than) == KHOA_ENVELOPE
    assert than["citations"] == [dict_trich_dan(td) for td in engine.trich_dan]
    assert [tuple(c) for c in than["citations"]] == [KHOA_TRICH_DAN] * 2
    query = [sk for sk in audit.su_kien if sk.event == EVENT_QUERY]
    assert len(query) == 1
    assert query[0].hyperedge_ids == ("he-2", "he-1")


def test_ac2_luot_tu_choi_khong_doi_mot_byte_va_audit_rong(monkeypatch):
    """Thân của lượt từ chối bằng từng byte bản 3.5 (citations rỗng), audit `query` rỗng."""
    audit = AuditGia()
    engine = EngineGia(ly_do=LY_DO_NGU_CANH_RONG)
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        kq = _hoi(client, "ts01")
    than = kq.json()
    assert than["citations"] == [] and than["refused"] is True and than["answer"] is None
    ky_vong = json.dumps(
        {"answer": None, "refused": True, "citations": [], "graph": {"nodes": [], "edges": []}, "meta": than["meta"]},
        separators=(",", ":"),
    ).encode()
    assert kq.content == ky_vong
    query = [sk for sk in audit.su_kien if sk.event == EVENT_QUERY]
    assert len(query) == 1 and query[0].hyperedge_ids == ()


def test_trich_dan_ngoai_quyen_ra_500_ma_on_dinh_khong_refusal(monkeypatch):
    """Hàng "Id trong ngữ cảnh mà adapter không thấy" ở tầng HTTP: 500 mã ổn định,
    không hàng `refusal`, không hàng `query`, thân không lộ id."""
    audit = AuditGia()
    engine = EngineGia(loi=TrichDanNgoaiQuyen("ngữ cảnh mang 1 id he-x lạ"))
    with _client(monkeypatch, _kho_gia(), audit, engine) as client:
        kq = _hoi(client, "ts01")
    assert kq.status_code == 500
    assert kq.json()["error"]["code"] == MA_TRICH_DAN_NGOAI_QUYEN == "TRICH_DAN_NGOAI_QUYEN"
    assert "he-x" not in kq.text and "refused" not in kq.json()
    assert [sk for sk in audit.su_kien if sk.event in (EVENT_REFUSAL, EVENT_QUERY)] == []


def test_http_hai_tai_khoan_seed_tren_engine_m1_that(monkeypatch, workspace_dir, khong_gian, policy, bang):
    """Manual check của spec, chạy trên máy dev: `dev01` và `ts01` qua `/hoi-dap`.

    Citation của response khớp oracle từng vai, và `hyperedge_ids` của hàng
    `query` khớp dãy `id` của chính response ấy.
    """
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        for tai_khoan, ten_vai in (("dev01", "devops"), ("ts01", "tech_support")):
            audit.su_kien.clear()
            kq = _hoi(client, tai_khoan)
            assert kq.status_code == 200, kq.text
            than = kq.json()
            assert than["refused"] is False
            assert {c["id"]: c for c in than["citations"]} == _ky_vong(bang, ten_vai)
            query = [sk for sk in audit.su_kien if sk.event == EVENT_QUERY]
            assert query[0].hyperedge_ids == tuple(c["id"] for c in than["citations"])
            assert query[0].role == ten_vai


# --- Tài liệu -----------------------------------------------------------------------


def test_adr_016_ghi_ba_quyet_dinh_cua_story():
    """ADR-016 tồn tại và nói đủ ba điều spec 3.4 giao cho nó."""
    assert ADR_016.exists(), ADR_016
    van_ban = ADR_016.read_text(encoding="utf-8")
    for cum in ("owner_group", "chép nguyên dấu che", "masked_slots", "answer", "TRICH_DAN_NGOAI_QUYEN"):
        assert cum in van_ban, f"ADR-016 thiếu {cum!r}"


def test_bao_ghi_owner_group_o_adapter_khong_lo_ra_ngoai():
    """`OWNER_GROUP_FIELD` là đường vận chuyển nội bộ; citation mang `owner_group` là
    trường **có cấu trúc** cùng tên nhưng đến từ `TrichDan`, không từ bản ghi che."""
    assert OWNER_GROUP_FIELD == "owner_group"
    assert "owner_group" in KHOA_TRICH_DAN
