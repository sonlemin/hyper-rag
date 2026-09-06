"""Đường truy vấn phụ theo grant và vòng đời hết hạn (story 5.3, FR-20, FR-27, Đo 1 lớp f).

Đặc tả viết trước cơ chế: mọi hàng I/O Matrix của spec 5.3 nằm ở đây, chia ba
lớp. Lớp 1 là hàm thuần `hop_nhat_ngu_canh` trên cả hai hình dạng khối
Relationships của vendor (CSV chuẩn và hybrid). Lớp 2 là engine M1 thật: chuỗi
ngữ cảnh mà `EngineACL.ngu_canh_hoi_dap` dựng, so với đường `aquery` không grant
(chốt brief §6: assert trên ngữ cảnh truy hồi, không trên `answer`). Lớp 3 là
HTTP với `KhoBreakGlassGia` cộng `chen_grant`, gồm ca xin -> duyệt -> hỏi nối
ba story 5.1/5.2/5.3.

Bốn mệnh đề mà không hàng nào phát biểu được một mình:

- **Grant là một thành phần của ngữ cảnh quyền đi qua cùng tầng che**, không
  phải một đường đọc thứ hai: cùng một `mask`, cùng cửa fail-closed, nên bảng
  chính sách hạ hyperedge về L0 là grant câm, không phải nới.
- **Đường phụ luôn chèn nhưng không bao giờ mở**: id mà adapter không thấy
  câm ở chính `get_node_edges`, ngữ cảnh byte-identical với lượt không grant.
- **Ngữ cảnh đóng băng theo lượt**: grant hết hạn giữa lượt thì lượt vẫn dùng
  trọn, lượt kế không.
- **Tuyến break-glass không đọc grant**: xin lại hyperedge đã được cấp vẫn là
  409 `GRANT_CON_HAN` của 5.1, không thành 400 vì "đã thấy đủ".

Fixture M1: với `tech_support`, HE-02 (`bao_cao_su_co`) ở L1, HE-01 (`runbook`)
ở L2, HE-03 (`bi_mat_ha_tang`) ở L0, HE-04 khác scope. Spec gọi HE-01 là "L0 với
tech_support" ở hàng "Không kênh gián tiếp"; theo `config/policy-day-du.yaml`
đó là HE-03, và ca dưới dùng HE-03 - oracle là bảng, không phải câu chữ spec.
"""

import asyncio
import json

import asyncpg
import pytest

from adapters.tra_loi import (
    CAU_HONG_UPSTREAM,
    _HEADER_RELATIONSHIPS,
    _KHOI_RELATIONSHIPS,
    _cac_khoi_csv,
    hop_nhat_ngu_canh,
    id_hyperedge_trong,
    ngu_canh_rong,
)
from adapters.trich_dan import TrichDanNgoaiQuyen
from api.break_glass import MA_GRANT_CON_HAN
from api.hoi_dap import CT_GRANT_IDS, KHOA_ENVELOPE, MA_KHO_KHONG_SAN_SANG
from core.audit import (
    EVENT_BREAKGLASS_APPROVE,
    EVENT_BREAKGLASS_REQUEST,
    EVENT_FILTER,
    EVENT_PERMISSION_MISMATCH,
    EVENT_QUERY,
    EVENT_REFUSAL,
)
from core.masking import dau_che, dau_che_owner
from core.permission import PermissionContextMissing, use_context
from core.slots import OWNER_SLOT, SLOT_ROLES
from tests.fixtures import oracle
from pathlib import Path

from tests.fixtures.du_lieu_dung_tay import HYPEREDGES, THEO_ID
from tests.gia_lap_llm import phan_hoi_hai_luot
from tests.gia_lap_neo4j import canh_moi_bien_deu_bi_loc
from tests.ho_tro_break_glass import chen_grant
from tests.ho_tro_m1 import CAU_HOI, cong_m1, hoi, hoi_co_grant, ten_hyperedge_ky_vong, ten_hyperedge_trong
from tests.nap_kho import ten_hyperedge
from tests.ngu_canh import ngu_canh_ingest, vai
from tests.test_break_glass_duyet import DUONG, _client, _duyet, _h, _kho_gia, _token, _xin
from tests.test_xac_thuc import AuditGia, EngineGia

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")

HE01, HE02, HE03, HE04 = (ten_hyperedge(THEO_ID[i]) for i in ("HE-01", "HE-02", "HE-03", "HE-04"))
TS = "tech_support"
GOC = Path(__file__).resolve().parent.parent


# --- Lớp 1: hàm thuần `hop_nhat_ngu_canh` --------------------------------------


def _khung(quan_he: str, thuc_the: str = "id,entity,type,description\r\n", nguon: str = "id,content\r\n") -> str:
    """Khung ba nhãn ba khối đúng hình dạng `operate.py:719-731`."""
    return (
        "\n-----Entities-----\n```csv\n" + thuc_the + "\n```\n"
        "-----Relationships-----\n```csv\n" + quan_he + "\n```\n"
        "-----Sources-----\n```csv\n" + nguon + "\n```\n"
    )


def _dong_quan_he(ngu_canh: str) -> list[str]:
    """Các dòng (kể cả header) của khối Relationships, bỏ dòng trắng."""
    return [d for d in _cac_khoi_csv(ngu_canh)[_KHOI_RELATIONSHIPS].splitlines() if d.strip()]


def _dong_cua(ngu_canh: str, id_he: str) -> list[str]:
    import csv
    import io

    return [
        d for d in _dong_quan_he(ngu_canh)[1:]
        if len(h := [o.strip() for o in next(csv.reader(io.StringIO(d)), [])]) > 1 and h[1] == id_he
    ]


CSV_CHUAN = (
    "id,hyperedge,related_entities\r\n"
    "0,he-a,\"App01|[cause:masked]|x\"\r\n"
    "1,he-b,App01|SOP-12\r\n"
    "2,he-a,\"App01|[cause:masked]\"\r\n"
)
HYBRID = (
    "id,\thyperedge,\trelated_entities\n"
    "1,\the-a,App01|[cause:masked]|x\n"
    "2,\the-b,App01|SOP-12\n"
)


@pytest.mark.parametrize("quan_he", [CSV_CHUAN, HYBRID], ids=["csv_chuan", "hybrid"])
def test_hop_nhat_bo_dong_trung_id_noi_dong_phu_id_danh_tiep_giu_nguyen_dong_khac(quan_he):
    """Hàng "Khử trùng" ở mức hàm thuần, trên cả hai hình dạng khối."""
    goc = _khung(quan_he)
    ra = hop_nhat_ngu_canh(goc, [[0, "he-a", "App01|chỉnh sai giới hạn|x"]])
    dong = _dong_quan_he(ra)
    assert dong[0] == _dong_quan_he(goc)[0], "header giữ nguyên văn"
    assert len(_dong_cua(ra, "he-a")) == 1, "đúng một dòng he-a, bản đầy đủ"
    assert _dong_cua(ra, "he-a") == ["2,he-a,App01|chỉnh sai giới hạn|x" if quan_he is CSV_CHUAN else "3,he-a,App01|chỉnh sai giới hạn|x"]
    assert "[cause:masked]" not in ra
    assert _dong_cua(ra, "he-b") == _dong_cua(goc, "he-b"), "dòng khác giữ nguyên văn"
    # `id` đánh tiếp sau số lớn nhất còn lại (CSV chuẩn: 1 -> 2 ; hybrid: 2 -> 3).
    assert _dong_cua(ra, "he-a")[0].startswith("2," if quan_he is CSV_CHUAN else "3,")
    assert id_hyperedge_trong(ra) == ("he-b", "he-a")
    # Hai khối kia không đổi một byte.
    assert ra.split("-----Relationships-----")[0] == goc.split("-----Relationships-----")[0]
    assert ra.split("-----Sources-----")[1] == goc.split("-----Sources-----")[1]


def test_hop_nhat_khong_dong_phu_hay_khong_phai_khung_thi_tra_nguyen():
    goc = _khung(CSV_CHUAN)
    assert hop_nhat_ngu_canh(goc, []) is goc
    assert hop_nhat_ngu_canh(CAU_HONG_UPSTREAM, [[0, "he-a", "x"]]) == CAU_HONG_UPSTREAM
    assert hop_nhat_ngu_canh("không phải khung", [[0, "he-a", "x"]]) == "không phải khung"
    assert hop_nhat_ngu_canh(None, [[0, "he-a", "x"]]) is None


@pytest.mark.parametrize(
    "header",
    ["a,b", "id,hyperedge", "hyperedge,id,related_entities", "id,hyperedge,related_entities,them"],
    ids=["khong_doc_duoc", "thieu_cot", "sai_thu_tu", "thua_cot"],
)
def test_hop_nhat_header_khac_vendor_tra_nguyen_kem_warning(caplog, header):
    """Header đọc được mà khác đúng `_HEADER_RELATIONSHIPS`: giữ nguyên, **không lặng lẽ**."""
    import logging

    la = _khung(header + "\r\n1,2,3\r\n")
    with caplog.at_level(logging.WARNING, logger="adapters.tra_loi"):
        assert hop_nhat_ngu_canh(la, [[0, "he-a", "x"]]) == la
    assert any("Relationships" in r.getMessage() for r in caplog.records)


def test_header_relationships_ghim_voi_vendor_o_ca_hai_nhanh():
    """`_HEADER_RELATIONSHIPS` là header mà cả hai nhánh vendor dựng (`operate.py:788` và `:987`)."""
    dong = (GOC / "vendor" / "hypergraphrag" / "operate.py").read_text(encoding="utf-8").splitlines()
    ky_vong = "[" + ", ".join(f'"{c}"' for c in _HEADER_RELATIONSHIPS) + "]"
    assert dong[788 - 1].strip() == ky_vong and dong[987 - 1].strip() == ky_vong
    assert sum(d.strip() == ky_vong for d in dong) == 2, "đúng hai nhánh dựng header ấy"


def test_hop_nhat_khoi_rong_nhan_header_vendor_va_luot_khong_con_rong():
    """Hàng "Không có ở đường chính" ở ca cực đoan: kho vector không cho gì cả."""
    rong = _khung("", "", "")
    assert ngu_canh_rong(rong)
    ra = hop_nhat_ngu_canh(rong, [[7, "he-a", "App01|x"]])
    assert _dong_quan_he(ra) == ["id,hyperedge,related_entities", "0,he-a,App01|x"]
    assert not ngu_canh_rong(ra) and id_hyperedge_trong(ra) == ("he-a",)


def test_hop_nhat_dong_phu_sai_so_cot_la_loi():
    with pytest.raises(ValueError):
        hop_nhat_ngu_canh(_khung(CSV_CHUAN), [["he-a", "x"]])


# --- Lớp 2: engine M1 thật ----------------------------------------------------------


def _engine(workspace_dir, khong_gian, policy):
    engine, client, driver, llm = asyncio.run(cong_m1(workspace_dir, khong_gian, policy))
    llm.theo_prompt = phan_hoi_hai_luot()
    return engine, client, driver, llm


def _ngu_canh(engine, nc) -> str:
    return asyncio.run(hoi(engine, nc))


def _ngu_canh_grant(engine, nc) -> str:
    return asyncio.run(hoi_co_grant(engine, nc))


def _hoi_dap(engine, nc):
    async def chay():
        with use_context(nc):
            return await engine.hoi_dap(CAU_HOI)

    return asyncio.run(chay())


def _gia_tri_che_o_l1(bang, he) -> dict[str, str]:
    """Giá trị của các vai mà bảng che ở L1 với `tech_support`, trừ `owner`."""
    return {v: he["slots"][v] for v in oracle.slot_phai_che(bang, TS, he) if v != OWNER_SLOT}


def test_mo_dung_vung_grant_he02_lo_gia_tri_that_tru_owner_va_citation_l2(workspace_dir, khong_gian, policy, bang):
    """Hàng "Mở đúng vùng": giá trị thật của vai bị che vào ngữ cảnh; `owner` vẫn `[owner:Tech Support]`; citation `L2`, `masked_slots == ["owner"]`."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    he02 = THEO_ID["HE-02"]
    che = _gia_tri_che_o_l1(bang, he02)
    assert "cause" in che, "fixture phải che `cause` ở L1 thì ca này mới đo được gì"
    khong = _ngu_canh(engine, vai(policy, TS, khong_gian))
    co = _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,)))
    assert _ngu_canh_grant(engine, vai(policy, TS, khong_gian)) == khong, "không grant thì hai đường một chuỗi"
    for v, gia_tri in che.items():
        assert gia_tri not in khong and dau_che(v) in khong, v
        assert gia_tri in co and dau_che(v) not in co, v
    assert he02["slots"]["owner"] not in co
    assert dau_che_owner(oracle.nhom_ky_vong("bao_cao_su_co")) in co
    # Tập hyperedge không đổi: grant không mở hyperedge nào ngoài id được cấp.
    assert ten_hyperedge_trong(co) == ten_hyperedge_trong(khong) == ten_hyperedge_ky_vong(bang, TS)
    assert HE03 not in co and HE04 not in co
    for he in (THEO_ID["HE-03"], THEO_ID["HE-04"]):
        assert not any(g in co for g in he["slots"].values() if g != "App01")
    # Citation nói đúng mức đã áp.
    truoc = {td.id: td for td in _hoi_dap(engine, vai(policy, TS, khong_gian)).trich_dan}
    sau = {td.id: td for td in _hoi_dap(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,))).trich_dan}
    assert truoc[HE02].level == "L1" and set(truoc[HE02].masked_slots) == oracle.slot_phai_che(bang, TS, he02)
    assert sau[HE02].level == "L2" and sau[HE02].masked_slots == (OWNER_SLOT,)
    assert sau[HE02].owner_group == truoc[HE02].owner_group == "Tech Support"
    assert {i: (td.level, td.masked_slots) for i, td in sau.items() if i != HE02} == {
        i: (td.level, td.masked_slots) for i, td in truoc.items() if i != HE02
    }


def test_khu_trung_dung_mot_dong_he02_ban_day_du_dong_khac_khong_doi(workspace_dir, khong_gian, policy):
    """Hàng "Khử trùng": HE-02 có ở đường chính (đã che) lẫn đường phụ -> một dòng, bản đầy đủ."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    khong = _ngu_canh(engine, vai(policy, TS, khong_gian))
    co = _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,)))
    assert len(_dong_cua(khong, HE02)) >= 1, "đường chính phải truy hồi được HE-02 thì ca này mới đo khử trùng"
    assert len(_dong_cua(co, HE02)) == 1
    assert THEO_ID["HE-02"]["slots"]["cause"] in _dong_cua(co, HE02)[0]
    khac = lambda nc: sorted(d for d in _dong_quan_he(nc)[1:] if d not in _dong_cua(nc, HE02))
    assert khac(co) == khac(khong)


def test_khong_kenh_gian_tiep_grant_he03_l0_ngu_canh_byte_identical(workspace_dir, khong_gian, policy, bang):
    """Hàng "Không kênh gián tiếp": grant cho hyperedge L0 chèn bằng helper -> câm, không lỗi, không tên."""
    assert oracle.muc_ky_vong(bang, TS, THEO_ID["HE-03"]["content_type"]) == "L0"
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    khong = _ngu_canh(engine, vai(policy, TS, khong_gian))
    driver.xoa_nhat_ky()
    co = _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(HE03, "he-khong-ton-tai", HE03)))
    assert co == khong
    assert HE03 not in co and THEO_ID["HE-03"]["slots"]["condition"] not in co
    # Câm vì **bị lọc**, không vì không hỏi: đường phụ đã hỏi đúng một câu
    # `trich_dan_cua` mang cả hai id (đã khử trùng), câu ấy ràng mọi biến của
    # pattern bằng space và khóa quyền, và không câu `get_node_edges` nào cho
    # HE-03 được gửi sau đó.
    cua = [lg for lg in driver.cac_cau_doc() if lg.loai == "doc:trich_dan_cua"]
    assert len(cua) == 1 and set(cua[0].params["ids"]) == {HE03, "he-khong-ton-tai"} and len(cua[0].params["ids"]) == 2
    canh_moi_bien_deu_bi_loc(cua[0].cypher)
    assert not [lg for lg in driver.cac_cau_doc() if lg.loai == "doc:get_node_edges" and lg.params.get("id") in (HE03, "he-khong-ton-tai")]


def test_grant_mang_id_entity_khong_dung_dong_phu_khong_lo_ten_o_cot_hyperedge(workspace_dir, khong_gian, policy):
    """Patch review: một id entity chèn tay vào bảng grant có cạnh trong graph, nhưng không phải hyperedge -> không dòng phụ."""
    entity = THEO_ID["HE-02"]["slots"]["subject"]  # "App01": id node entity của M1 là giá trị slot
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    khong = _ngu_canh(engine, vai(policy, TS, khong_gian))
    driver.xoa_nhat_ky()
    co = _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(entity,)))
    assert co == khong and _dong_cua(co, entity) == []
    assert not [lg for lg in driver.cac_cau_doc() if lg.loai == "doc:get_node_edges" and lg.params.get("id") == entity]


def test_duong_phu_get_node_edges_di_qua_menh_de_loc_va_dong_phu_sap_xep_ten(workspace_dir, khong_gian, policy, bang):
    """Câu `get_node_edges` của đường phụ ràng mọi biến; tên lân cận trong dòng phụ sắp xếp chuỗi (tất định)."""
    engine, _, driver, _ = _engine(workspace_dir, khong_gian, policy)
    he02 = THEO_ID["HE-02"]
    driver.xoa_nhat_ky()
    co = _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,)))
    cau = [lg for lg in driver.cac_cau_doc() if lg.loai == "doc:get_node_edges" and lg.params.get("id") == HE02]
    assert cau, "đường phụ phải hỏi cạnh của HE-02"
    for lg in cau:
        canh_moi_bien_deu_bi_loc(lg.cypher)
    (dong,) = _dong_cua(co, HE02)
    ten = dong.split(",", 2)[2].strip('"').split("|")
    # Dưới grant chỉ `owner` bị che: mọi giá trị khác ra nguyên văn, sắp xếp chuỗi.
    ky_vong = sorted(
        {v for s, v in he02["slots"].items() if s != OWNER_SLOT}
        | {dau_che_owner(oracle.nhom_ky_vong(he02["content_type"]))}
    )
    assert ten == ky_vong


def test_khong_co_o_duong_chinh_grant_van_dua_he02_vao_va_luot_khong_rong(monkeypatch, workspace_dir, khong_gian, policy):
    """Hàng "Không có ở đường chính": câu hỏi không truy hồi được HE-02 -> đường phụ vẫn chèn."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    goc = _ngu_canh(engine, vai(policy, TS, khong_gian))
    thieu = "\n".join(d for d in goc.splitlines() if HE02 not in d)
    assert HE02 not in thieu and not ngu_canh_rong(thieu)
    rong = _khung("", "", "")
    for khong_co in (thieu, rong):
        async def _aquery(query, param=None, _tra=khong_co):
            return _tra

        monkeypatch.setattr(engine, "aquery", _aquery)
        assert _ngu_canh_grant(engine, vai(policy, TS, khong_gian)) == khong_co
        co = _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,)))
        assert len(_dong_cua(co, HE02)) == 1 and THEO_ID["HE-02"]["slots"]["cause"] in co
        assert not ngu_canh_rong(co)
        kq = _hoi_dap(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,)))
        assert kq.ly_do_tu_choi is None and {td.id: td.level for td in kq.trich_dan}[HE02] == "L2"


def test_grant_hai_id_he02_l1_va_he01_da_l2_moi_id_mot_dong_id_danh_tiep(workspace_dir, khong_gian, policy, bang):
    """Patch review: grant hai id cùng lúc - mỗi id đúng một dòng, `id` cột đánh tiếp, HE-01 (đã L2) citation như không grant."""
    import csv
    import io

    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    assert oracle.muc_ky_vong(bang, TS, "runbook") == "L2"
    khong = _ngu_canh(engine, vai(policy, TS, khong_gian))
    co = _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(HE02, HE01)))
    assert len(_dong_cua(co, HE02)) == 1 and len(_dong_cua(co, HE01)) == 1
    dong = _dong_quan_he(co)[1:]
    assert len(dong) == len(set(dong)), "không dòng trùng"
    so = [int(next(csv.reader(io.StringIO(d)))[0].strip()) for d in dong]
    # Hai dòng phụ đứng cuối (thứ tự grant_ids đã chuẩn hóa), số đánh tiếp sau số lớn nhất còn lại.
    assert so[-2:] == [max(so[:-2]) + 1, max(so[:-2]) + 2] if len(so) > 2 else so == [0, 1]
    truoc = {td.id: td for td in _hoi_dap(engine, vai(policy, TS, khong_gian)).trich_dan}
    sau = {td.id: td for td in _hoi_dap(engine, vai(policy, TS, khong_gian, grant_ids=(HE02, HE01))).trich_dan}
    assert (sau[HE01].level, sau[HE01].masked_slots) == (truoc[HE01].level, truoc[HE01].masked_slots) == ("L2", (OWNER_SLOT,))
    assert (sau[HE02].level, sau[HE02].masked_slots) == ("L2", (OWNER_SLOT,)) and truoc[HE02].level == "L1"
    assert set(sau) == set(truoc) == set(id_hyperedge_trong(khong)) | {HE01, HE02}


def test_ha_nen_policy_nhi_phan_he02_l0_grant_cam_khong_mask_item_out_of_permission(workspace_dir, khong_gian, policy):
    """Hàng "Hạ nền": bảng hoán sang `nhi-phan` (HE-02 thành L0) -> grant câm, không lỗi."""
    from adapters.policy_loader import load_policy

    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    nhi_phan = load_policy(oracle.POLICY_NHI_PHAN)
    bang_np = oracle.doc_bang_chinh_sach(oracle.POLICY_NHI_PHAN)
    assert oracle.muc_ky_vong(bang_np, TS, "bao_cao_su_co") == "L0"
    khong = _ngu_canh(engine, vai(nhi_phan, TS, khong_gian))
    co = _ngu_canh_grant(engine, vai(nhi_phan, TS, khong_gian, grant_ids=(HE02,)))
    assert co == khong and HE02 not in co
    kq = _hoi_dap(engine, vai(nhi_phan, TS, khong_gian, grant_ids=(HE02,)))
    assert all(td.id != HE02 for td in kq.trich_dan)


def test_thieu_ngu_canh_va_ngu_canh_he_thong(workspace_dir, khong_gian, policy):
    """Hàng "Thiếu ngữ cảnh": ngoài `use_context` là `PermissionContextMissing`; hệ thống bị từ chối như `dung_danh_sach`."""
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)
    with pytest.raises(PermissionContextMissing):
        asyncio.run(engine.ngu_canh_hoi_dap(CAU_HOI))
    driver.xoa_nhat_ky()
    with pytest.raises(TrichDanNgoaiQuyen):
        asyncio.run(hoi_co_grant(engine, ngu_canh_ingest(khong_gian, policy)))
    assert driver.cac_cau_doc() == [], "từ chối trước khi chạm kho"
    assert llm.so_lan == 0


def test_tu_khoa_rong_dung_truoc_duong_phu(monkeypatch, workspace_dir, khong_gian, policy):
    """Nhánh 1 của `hoi_dap` đứng trước đường phụ: chuỗi hỏng của vendor đi ra nguyên, không câu kho nào."""
    engine, _, driver, llm = _engine(workspace_dir, khong_gian, policy)

    async def _aquery(query, param=None):
        return CAU_HONG_UPSTREAM

    monkeypatch.setattr(engine, "aquery", _aquery)
    driver.xoa_nhat_ky()
    assert _ngu_canh_grant(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,))) == CAU_HONG_UPSTREAM
    assert driver.cac_cau_doc() == []
    assert _hoi_dap(engine, vai(policy, TS, khong_gian, grant_ids=(HE02,))).ly_do_tu_choi == "tu_khoa_rong"
    assert llm.so_lan == 0


def test_do_thi_voi_grant_node_he02_l2_entity_tung_che_nay_masked_false(workspace_dir, khong_gian, policy, bang):
    """Hàng "`/do-thi` với grant" ở mức engine: node HE-02 `L2`, node che chỉ còn `owner`."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    he02 = THEO_ID["HE-02"]

    def do_thi(nc):
        async def chay():
            with use_context(nc):
                return await engine.do_thi([HE02])

        return asyncio.run(chay())

    truoc, sau = do_thi(vai(policy, TS, khong_gian)), do_thi(vai(policy, TS, khong_gian, grant_ids=(HE02,)))
    he_truoc = next(n for n in truoc.nodes if n.kind == "hyperedge")
    he_sau = next(n for n in sau.nodes if n.kind == "hyperedge")
    assert (he_truoc.level, he_sau.level) == ("L1", "L2")
    che_truoc = {n.id for n in truoc.nodes if n.kind == "entity" and n.masked}
    che_sau = {n.id for n in sau.nodes if n.kind == "entity" and n.masked}
    assert che_truoc == {f"{HE02}#{v}" for v in oracle.slot_phai_che(bang, TS, he02)}
    assert che_sau == {f"{HE02}#{OWNER_SLOT}"}
    nhan_sau = {n.label for n in sau.nodes if n.kind == "entity" and not n.masked}
    assert set(_gia_tri_che_o_l1(bang, he02).values()) <= nhan_sau
    assert he02["slots"]["owner"] not in nhan_sau and he02["slots"]["cause"] in he_sau.label


# --- Lớp 3: HTTP với kho giả + `chen_grant` -------------------------------------


def _hoi_http(client, token):
    return client.post("/hoi-dap", json={"cau_hoi": CAU_HOI}, headers=_h(token))


def _citation(kq, id_he):
    assert kq.status_code == 200, kq.text
    return {c["id"]: c for c in kq.json()["citations"]}[id_he]


def _query(audit):
    return [sk for sk in audit.su_kien if sk.event == EVENT_QUERY]


def test_http_ac1_xin_duyet_hoi_lai_ba_story_noi_nhau_va_het_han(monkeypatch, workspace_dir, khong_gian, policy, bang, kho_break_glass_gia):
    """AC-1 và AC-2: trước duyệt `L1` che nhiều vai; sau duyệt `L2` che `owner`, audit `query` mang `grant_ids`; hết hạn thì lượt kế về `L1`."""
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        ts, demo = _token(client, "ts01"), _token(client, "demo01")
        truoc = _citation(_hoi_http(client, ts), HE02)
        assert truoc["level"] == "L1" and truoc["masked_slots"] == [v for v in SLOT_ROLES if v in oracle.slot_phai_che(bang, TS, THEO_ID["HE-02"])]
        assert CT_GRANT_IDS not in _query(audit)[-1].chi_tiet
        yc = _xin(client, ts, HE02)
        assert _duyet(client, demo, yc["id"]).status_code == 200
        # Tuyến break-glass không đọc grant: xin lại vẫn là 409 của 5.1, không phải 400 "đã thấy đủ".
        lai = client.post(DUONG, json={"hyperedge_id": HE02, "ly_do": "xin lại"}, headers=_h(ts))
        assert lai.status_code == 409 and lai.json()["error"]["code"] == MA_GRANT_CON_HAN
        so_truoc = len(audit.su_kien)
        kq = _hoi_http(client, ts)
        sau = _citation(kq, HE02)
        assert sau["level"] == "L2" and sau["masked_slots"] == [OWNER_SLOT] and sau["owner_group"] == "Tech Support"
        assert tuple(kq.json()) == KHOA_ENVELOPE, "response không thêm trường"
        assert kq.json()["meta"] == {"role": TS, "space": khong_gian, "policy_version": policy.policy_version}
        assert _query(audit)[-1].chi_tiet[CT_GRANT_IDS] == [HE02]
        assert _query(audit)[-1].hyperedge_ids == tuple(c["id"] for c in kq.json()["citations"])
        assert {sk.event for sk in audit.su_kien[so_truoc:]} <= {EVENT_QUERY, EVENT_REFUSAL, EVENT_FILTER}
        # Grant ở vai khác ngủ: dev01 (devops) không nhận gì từ grant của cặp (ts01, tech_support).
        assert asyncio.run(kho_break_glass_gia.grant_hieu_luc("ts01", "devops", khong_gian)) == ()
        # Hết hạn (helper): lượt kế về L1, không `grant_ids`, không hàng audit lạ.
        kho_break_glass_gia.grants.clear()
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role=TS, hyperedge_ids=[HE02], con_han_phut=-1, space=khong_gian))
        assert asyncio.run(kho_break_glass_gia.grant_hieu_luc("ts01", TS, khong_gian)) == ()
        so_truoc = len(audit.su_kien)
        het = _citation(_hoi_http(client, ts), HE02)
        assert het == truoc and CT_GRANT_IDS not in _query(audit)[-1].chi_tiet
        assert {sk.event for sk in audit.su_kien[so_truoc:]} <= {EVENT_QUERY, EVENT_REFUSAL, EVENT_FILTER}
    assert [sk.event for sk in audit.su_kien if sk.event.startswith("breakglass")] == [EVENT_BREAKGLASS_REQUEST, EVENT_BREAKGLASS_APPROVE]
    assert llm.so_lan == 6, "ba lượt trả lời, mỗi lượt hai lời gọi; đường phụ không tốn lời gọi nào"


def test_http_luot_tu_choi_va_lech_quyen_duoi_grant_mang_grant_ids_khong_grant_giu_nguyen(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    """Patch review: `refusal` (co_no_answer) và `permission_mismatch` mang `grant_ids` cùng luật với `query`."""
    engine, _, _, llm = _engine(workspace_dir, khong_gian, policy)
    llm.theo_prompt = phan_hoi_hai_luot(khong_co_dap_an=True)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        ts = _token(client, "ts01")
        kq = _hoi_http(client, ts)
        assert kq.status_code == 200 and kq.json()["refused"] is True
        (tu_choi,) = [sk for sk in audit.su_kien if sk.event == EVENT_REFUSAL]
        assert set(tu_choi.chi_tiet) == {"ly_do", "request_id"} and tu_choi.chi_tiet["ly_do"] == "co_no_answer"
        assert set(_query(audit)[-1].chi_tiet) == {"mili_giay", "request_id"}
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role=TS, hyperedge_ids=[HE02], space=khong_gian))
        audit.su_kien.clear()
        kq = _hoi_http(client, ts)
        assert kq.status_code == 200 and kq.json()["refused"] is True
        (tu_choi,) = [sk for sk in audit.su_kien if sk.event == EVENT_REFUSAL]
        assert tu_choi.chi_tiet[CT_GRANT_IDS] == [HE02] and tu_choi.chi_tiet["ly_do"] == "co_no_answer"
        assert _query(audit)[-1].chi_tiet[CT_GRANT_IDS] == [HE02]
        # Lệch quyền dưới grant: hàng `permission_mismatch` cũng mang `grant_ids`.
        from adapters import engine as engine_mod

        goc = engine_mod.id_hyperedge_trong
        monkeypatch.setattr(engine_mod, "id_hyperedge_trong", lambda nc: goc(nc) + ("he-x",))
        audit.su_kien.clear()
        assert _hoi_http(client, ts).status_code == 500
        (lech,) = [sk for sk in audit.su_kien if sk.event == EVENT_PERMISSION_MISMATCH]
        assert lech.chi_tiet[CT_GRANT_IDS] == [HE02] and lech.hyperedge_ids == ("he-x",)
        assert [sk for sk in audit.su_kien if sk.event in (EVENT_QUERY, EVENT_REFUSAL)] == []


def test_http_khac_vai_grant_bind_devops_ts01_hoi_o_tech_support_khong_doc_duoc(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    """Hàng "Khác vai": grant `(ts01, devops)` ngủ khi ts01 hỏi ở `tech_support`."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    audit = AuditGia()
    asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role="devops", hyperedge_ids=[HE02], space=khong_gian))
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        td = _citation(_hoi_http(client, _token(client, "ts01")), HE02)
    assert td["level"] == "L1" and CT_GRANT_IDS not in _query(audit)[-1].chi_tiet


def test_http_hoan_policy_nhi_phan_luot_ke_cam_he02(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    """Hàng "Hạ nền" qua HTTP: hoán `nhi-phan` -> lượt kế không còn HE-02, không 500."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role=TS, hyperedge_ids=[HE02], space=khong_gian))
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        ts, dev = _token(client, "ts01"), _token(client, "dev01")
        assert _citation(_hoi_http(client, ts), HE02)["level"] == "L2"
        assert client.post("/admin/policy", json={"id": "nhi-phan"}, headers=_h(dev)).status_code == 200
        kq = _hoi_http(client, ts)
        assert kq.status_code == 200, kq.text
        assert HE02 not in {c["id"] for c in kq.json()["citations"]}
        assert client.post("/admin/policy", json={"id": "day-du"}, headers=_h(dev)).status_code == 200
        assert _citation(_hoi_http(client, ts), HE02)["level"] == "L2"


def test_http_request_dang_chay_giu_ngu_canh_dong_bang(monkeypatch, workspace_dir, khong_gian, policy, kho_break_glass_gia):
    """Hàng "Request đang chạy": grant hết hạn giữa lượt -> lượt dùng trọn ngữ cảnh; lượt kế không."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role=TS, hyperedge_ids=[HE02], space=khong_gian))
    goc = engine.hoi_dap

    async def _hoi_dap_het_han_giua_chung(cau_hoi, param=None):
        kho_break_glass_gia.grants.clear()
        return await goc(cau_hoi, param)

    monkeypatch.setattr(engine, "hoi_dap", _hoi_dap_het_han_giua_chung)
    audit = AuditGia()
    with _client(monkeypatch, _kho_gia(khong_gian), audit, engine) as client:
        ts = _token(client, "ts01")
        assert _citation(_hoi_http(client, ts), HE02)["level"] == "L2"
        assert _query(audit)[-1].chi_tiet[CT_GRANT_IDS] == [HE02]
        assert _citation(_hoi_http(client, ts), HE02)["level"] == "L1"
        assert CT_GRANT_IDS not in _query(audit)[-1].chi_tiet


def test_http_kho_grant_hong_503_ca_hai_tuyen_khong_loi_goi_nao(monkeypatch, kho_break_glass_gia):
    """Hàng "Kho grant hỏng": 503 `KHO_KHONG_SAN_SANG`, không chạm engine, thân không lộ postgres."""
    engine = EngineGia()
    with _client(monkeypatch, _kho_gia(), AuditGia(), engine) as client:
        ts = _token(client, "ts01")
        kho_break_glass_gia.no = asyncpg.exceptions.PostgresConnectionError("postgres rớt")
        hai = [_hoi_http(client, ts), client.post("/do-thi", json={"hyperedge_ids": ["he-1"]}, headers=_h(ts))]
        kho_break_glass_gia.no = None
        assert _hoi_http(client, ts).status_code == 200, "kho lên lại thì lượt kế chạy"
    for kq in hai:
        assert kq.status_code == 503 and kq.json()["error"]["code"] == MA_KHO_KHONG_SAN_SANG
        assert "postgres" not in kq.text.lower() and "grant" not in kq.text.lower()
    assert engine.cau_hoi == [CAU_HOI] and engine.ids == [], "hai lượt hỏng không chạm engine"


def test_http_do_thi_voi_grant_qua_http(monkeypatch, workspace_dir, khong_gian, policy, bang, kho_break_glass_gia):
    """Hàng "`/do-thi` với grant" qua HTTP: node HE-02 `L2`, node che chỉ còn `owner`, cùng envelope."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    he02 = THEO_ID["HE-02"]
    with _client(monkeypatch, _kho_gia(khong_gian), AuditGia(), engine) as client:
        ts = _token(client, "ts01")
        goi = lambda: client.post("/do-thi", json={"hyperedge_ids": [HE02]}, headers=_h(ts))
        truoc = goi().json()["graph"]
        asyncio.run(chen_grant(kho_break_glass_gia, act="ts01", role=TS, hyperedge_ids=[HE02], space=khong_gian))
        kq = goi()
        assert kq.status_code == 200 and kq.json()["citations"] == [] and kq.json()["answer"] is None
        sau = kq.json()["graph"]
    he = lambda g: next(n for n in g["nodes"] if n["kind"] == "hyperedge")
    che = lambda g: {n["id"] for n in g["nodes"] if n["kind"] == "entity" and n["masked"]}
    assert (he(truoc)["level"], he(sau)["level"]) == ("L1", "L2")
    assert che(truoc) == {f"{HE02}#{v}" for v in oracle.slot_phai_che(bang, TS, he02)}
    assert che(sau) == {f"{HE02}#{OWNER_SLOT}"}
    assert he02["slots"]["cause"] in {n["label"] for n in sau["nodes"]} and he02["slots"]["owner"] not in json.dumps(sau, ensure_ascii=False)


def test_kho_gia_grant_hieu_luc_cung_luat_ban_that(kho_break_glass_gia):
    """Bản giả: hợp, khử trùng, sắp xếp, bỏ hết hạn, bỏ khác vai và khác space; `no` dội nguyên."""
    kho = kho_break_glass_gia

    async def chay():
        assert await kho.grant_hieu_luc("ts01", TS, "synth") == ()
        await chen_grant(kho, act="ts01", role=TS, hyperedge_ids=["HE-09", "HE-02"])
        await chen_grant(kho, act="ts01", role=TS, hyperedge_ids=["HE-02", "HE-01"])
        await chen_grant(kho, act="ts01", role=TS, hyperedge_ids=["HE-05"], con_han_phut=-1)
        await chen_grant(kho, act="ts01", role="devops", hyperedge_ids=["HE-03"])
        await chen_grant(kho, act="ts01", role=TS, hyperedge_ids=["HE-07"], space="khac")
        assert await kho.grant_hieu_luc("ts01", TS, "synth") == ("HE-01", "HE-02", "HE-09")
        assert await kho.grant_hieu_luc("ts01", "devops", "synth") == ("HE-03",)
        kho.no = RuntimeError("rớt")
        with pytest.raises(RuntimeError):
            await kho.grant_hieu_luc("ts01", TS, "synth")

    asyncio.run(chay())


def test_moi_hyperedge_moi_vai_grant_chi_nang_dung_id_theo_oracle(workspace_dir, khong_gian, policy, bang):
    """Quét cả fixture: grant một id chỉ đổi citation của đúng id ấy, và chỉ khi vai thấy nó ở L1."""
    engine, *_ = _engine(workspace_dir, khong_gian, policy)
    for ten_vai in ("tech_support", "devops"):
        for he in HYPEREDGES:
            id_he = ten_hyperedge(he)
            muc = oracle.muc_ky_vong(bang, ten_vai, he["content_type"])
            thay = he["id"] in oracle.hyperedge_thay_duoc(bang, ten_vai, HYPEREDGES)
            kq = _hoi_dap(engine, vai(policy, ten_vai, khong_gian, grant_ids=(id_he,)))
            theo_id = {td.id: td for td in kq.trich_dan}
            if not thay:
                assert id_he not in theo_id, (ten_vai, id_he)
                continue
            assert id_he in theo_id, (ten_vai, id_he, "đường phụ luôn chèn hyperedge mà vai thấy")
            assert theo_id[id_he].level == "L2", (ten_vai, id_he, muc)
            assert set(theo_id[id_he].masked_slots) == ({OWNER_SLOT} & set(he["slots"])), (ten_vai, id_he)
