"""Bộ 52 câu, bộ vàng 30 câu và nhãn truy hồi vàng (story 2.9, Đo 2 và Đo 3).

Viết trước `eval/cau_hoi.py` và trước ba file JSON (FR-27: test là đặc tả).
Bốn nhóm ca:

- **Ca hợp lệ chạy trên ba file thật** (`eval/anh_do_thi/synth.json`,
  `eval/bo_cau_hoi.json`, `eval/nhan_truy_hoi_vang.json`). Ba file đó là mẫu số
  của Đo 2 và Đo 3, nên phân bố 7 nhóm, 30 câu bộ vàng, trọn 6 câu N7 và luật
  một-một của nhãn đều được canh bằng bộ test chứ không bằng một lần đọc tay.
- **Ca lỗi dựng JSON nhỏ trong `tmp_path`**, một test cho mỗi hàng I/O Matrix
  của spec. Ba file thật không bao giờ bị sửa để tạo ca lỗi.
- **Trần lý thuyết theo vai**: phép tính thuần từ nhãn cộng ảnh chụp cộng bảng
  chính sách. Ca trần 0 là *cảnh báo*, không phải lỗi - đó là trạng thái đúng
  cho tới story 3.2.
- **Trang soát nhãn**: dựng được vào `tmp_path`, thiếu file thì thoát 1.

Bộ test không chạm kho, không gọi LLM, không cần mạng: nó đọc ảnh chụp đã
commit chứ không đọc Neo4j.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from adapters.identity_seed import nap_danh_tinh
from adapters.policy_loader import load_policy
from core.keys import filter_key
from core.slots import SLOT_ROLES, SLOT_ROLE_SET
from eval.cau_hoi import (
    NHOM,
    NHOM_CO_NHAN,
    PHAN_BO,
    SO_CAU_BO_VANG,
    TONG_CAU,
    AnhDoThiKhongHopLe,
    AnhDoThiRong,
    BoCauHoiKhongHopLe,
    NhanKhongHopLe,
    NhanTroiId,
    doc_anh_do_thi,
    doc_bo_cau_hoi,
    doc_nhan_truy_hoi,
    tran_theo_vai,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY = REPO_ROOT / "config" / "policy-toi-gian.yaml"

# Hai vai của `config/danh-tinh-demo.yaml`. Hằng này là thứ *được kiểm*
# (`test_hai_vai_do_lay_tu_seed_danh_tinh`), không phải nguồn: seed là nguồn.
HAI_VAI = ("devops", "tech_support")


# --------------------------------------------------------------------------
# Khuôn dựng ba file nhỏ trong tmp_path
# --------------------------------------------------------------------------


def _he(id_he: str, doc_key, subject: str, **slots):
    """Một mục hyperedge của ảnh chụp; `subject` luôn có vì lược đồ fact đòi nó.

    Mặc định có thêm `cause` để nhãn khuôn (`slot_dap_an: [cause]`) hợp lệ:
    loader đòi mọi slot đáp án phải là vai mà chính hyperedge đó có điền.
    """
    khoa = slots.pop("khoa", filter_key("noi_bo", "runbook"))
    slots.setdefault("cause", "nguyên nhân thử")
    return {
        "id": id_he,
        "doc_key": list(doc_key),
        "khoa": khoa,
        "slots": {"subject": [subject], **{k: [v] for k, v in slots.items()}},
    }


def _ghi(tmp_path: Path, ten: str, du_lieu) -> Path:
    dich = tmp_path / ten
    dich.write_text(json.dumps(du_lieu, ensure_ascii=False), encoding="utf-8")
    return dich


def _anh(tmp_path: Path, hyperedge=None, **doi) -> Path:
    he = [_he("he-aaa", ["t1.md"], "App01")] if hyperedge is None else hyperedge
    du_lieu = {
        "version": 1,
        "space": "synth",
        "ngay_do": "2026-09-03T00:00:00+00:00",
        "so_hyperedge": len(he),
        "so_hyperedge_da_nguon": sum(1 for h in he if len(h["doc_key"]) > 1),
        "hyperedge": he,
    }
    du_lieu.update(doi)
    return _ghi(tmp_path, "anh.json", du_lieu)


def _mot_cau(i: int, nhom: str, bo_vang: bool) -> dict:
    return {
        "id": f"{nhom.lower()}-{i:02d}",
        "nhom": nhom,
        "cau_hoi": f"Câu hỏi thử số {i} của nhóm {nhom}?",
        "vai_hoi": HAI_VAI[i % 2],
        "kich_ban": "nhieu",
        "bo_vang": bo_vang,
        "dap_an": "Đáp án tay." if bo_vang else "",
        "y_chinh": ["ý chính"] if bo_vang else [],
    }


def _cac_cau(phan_bo=None, so_bo_vang=None) -> list[dict]:
    """52 câu đúng phân bố; bộ vàng = trọn N7 cộng phần đầu của các nhóm khác."""
    phan_bo = dict(PHAN_BO) if phan_bo is None else dict(phan_bo)
    so_bo_vang = SO_CAU_BO_VANG if so_bo_vang is None else so_bo_vang
    cau = []
    for nhom, so in phan_bo.items():
        for i in range(1, so + 1):
            cau.append(_mot_cau(i, nhom, bo_vang=False))
    # Trọn N7 trước, rồi *xoay vòng* qua các nhóm khác cho tới đủ số - luật của
    # loader đòi mọi nhóm có ít nhất một câu bộ vàng, nên lấy tuần tự theo nhóm
    # sẽ bỏ trắng ba nhóm cuối.
    thu_tu = [c for c in cau if c["nhom"] == "N7"]
    con_lai = {nhom: [c for c in cau if c["nhom"] == nhom] for nhom in NHOM if nhom != "N7"}
    while any(con_lai.values()):
        for nhom in list(con_lai):
            if con_lai[nhom]:
                thu_tu.append(con_lai[nhom].pop(0))
    for c in thu_tu[:so_bo_vang]:
        c["bo_vang"] = True
        c["dap_an"] = "Đáp án tay."
        c["y_chinh"] = ["ý chính"]
    return cau


def _bo_cau(tmp_path: Path, cau=None, **doi) -> Path:
    du_lieu = {"version": 1, "cau": _cac_cau() if cau is None else cau}
    du_lieu.update(doi)
    return _ghi(tmp_path, "cau.json", du_lieu)


def _cac_nhan(cau: list[dict], id_he="he-aaa", doc_key="t1.md", subject="App01",
              slot_dap_an=("cause",)) -> list[dict]:
    """Một nhãn cho mọi câu N3/N5, đúng luật một-một."""
    return [
        {
            "cau_id": c["id"],
            "hyperedge": [
                {
                    "id": id_he,
                    "doc_key": doc_key,
                    "neo_subject": subject,
                    "slot_dap_an": list(slot_dap_an),
                }
            ],
        }
        for c in cau
        if c["nhom"] in NHOM_CO_NHAN
    ]


def _nhan(tmp_path: Path, nhan=None, cau=None, **doi) -> Path:
    du_lieu = {"version": 1, "nhan": _cac_nhan(cau or _cac_cau()) if nhan is None else nhan}
    du_lieu.update(doi)
    return _ghi(tmp_path, "nhan.json", du_lieu)


def _bo_ba(tmp_path: Path):
    """Ba file nhỏ hợp lệ, khớp nhau; điểm xuất phát của mọi ca lỗi."""
    cau = _cac_cau()
    return (
        _anh(tmp_path),
        _bo_cau(tmp_path, cau),
        _nhan(tmp_path, _cac_nhan(cau)),
    )


# --------------------------------------------------------------------------
# Ba file thật của repo
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def anh():
    return doc_anh_do_thi()


@pytest.fixture(scope="module")
def bo():
    return doc_bo_cau_hoi()


@pytest.fixture(scope="module")
def nhan(bo, anh):
    return doc_nhan_truy_hoi(bo=bo, anh=anh)


def test_anh_do_thi_that_nap_duoc_va_dung_space(anh):
    assert anh.space == "synth"
    assert anh.so_hyperedge == len(anh.hyperedge) > 0
    assert len({h.id for h in anh.hyperedge}) == anh.so_hyperedge


def test_moi_hyperedge_cua_anh_co_subject_va_vai_hop_le(anh):
    """Ảnh chụp là nguồn chuẩn của id, nên nó phải mang đúng lược đồ 8 vai."""
    for h in anh.hyperedge:
        assert set(h.slots) <= SLOT_ROLE_SET, h.id
        assert h.slots.get("subject"), f"{h.id} không có subject"


def test_bo_cau_hoi_that_dung_phan_bo(bo):
    assert len(bo.cau) == TONG_CAU == sum(PHAN_BO.values()) == 52
    dem = {nhom: len(ds) for nhom, ds in bo.theo_nhom().items()}
    assert dem == dict(PHAN_BO)
    assert len({c.id for c in bo.cau}) == TONG_CAU


def test_bo_vang_dung_ba_muoi_cau_va_tron_sau_cau_n7(bo):
    vang = bo.bo_vang()
    assert len(vang) == SO_CAU_BO_VANG == 30
    n7 = [c for c in bo.cau if c.nhom == "N7"]
    assert len(n7) == 6
    assert all(c.bo_vang for c in n7), "bộ vàng phải chứa trọn 6 câu N7 (PRD 2.6)"


def test_moi_nhom_deu_co_it_nhat_mot_cau_bo_vang(bo):
    theo_nhom = {}
    for c in bo.bo_vang():
        theo_nhom.setdefault(c.nhom, []).append(c)
    assert set(theo_nhom) == set(NHOM)


def test_moi_cau_bo_vang_co_dap_an_va_y_chinh(bo):
    for c in bo.bo_vang():
        assert c.dap_an.strip(), c.id
        assert c.y_chinh, c.id
    for c in bo.cau:
        if not c.bo_vang:
            assert c.dap_an == "" and c.y_chinh == (), c.id


def test_hai_vai_do_lay_tu_seed_danh_tinh(bo):
    """Vai người hỏi không được là một chuỗi tự do: nó phải có trong seed."""
    tu_seed = {dt.vai for dt in nap_danh_tinh()}
    assert tu_seed == set(HAI_VAI)
    assert {c.vai_hoi for c in bo.cau} <= tu_seed
    assert {c.vai_hoi for c in bo.cau} == tu_seed, "cả hai vai phải có câu hỏi"


def test_nhan_phu_dung_hai_muoi_hai_cau_n3_n5(bo, nhan):
    co_nhan = {n.cau_id for n in nhan.nhan}
    can_nhan = {c.id for c in bo.cau if c.nhom in NHOM_CO_NHAN}
    assert len(can_nhan) == PHAN_BO["N3"] + PHAN_BO["N5"] == 22
    assert co_nhan == can_nhan


def test_moi_id_trong_nhan_ton_tai_trong_anh_chup(nhan, anh):
    trong_anh = {h.id for h in anh.hyperedge}
    for n in nhan.nhan:
        for he in n.hyperedge:
            assert he.id in trong_anh, f"{n.cau_id}: {he.id}"


def test_moi_neo_mo_ta_khop_dung_mot_hyperedge(nhan, anh):
    """Neo hai lớp: `doc_key` + `neo_subject` phải xác định đúng một hyperedge."""
    for n in nhan.nhan:
        for he in n.hyperedge:
            ung_vien = anh.tim_theo_neo(he.doc_key, he.neo_subject)
            assert [h.id for h in ung_vien] == [he.id], f"{n.cau_id}: {he.id}"


def test_moi_slot_dap_an_nam_trong_danh_muc_tam_vai(nhan):
    for n in nhan.nhan:
        for he in n.hyperedge:
            assert he.slot_dap_an, f"{n.cau_id}: {he.id} không nêu slot đáp án"
            assert set(he.slot_dap_an) <= SLOT_ROLE_SET


def test_nhan_phu_ca_ba_kich_ban_va_ca_hai_khach_hang(nhan, anh):
    """Nhãn phải chạm cả `khach_hang_b` - scope mà **không vai nào** chạm tới.

    Đó là biên cách ly của RT-01 và là phần khó nhất của Đo 3. Một bộ nhãn chỉ
    gồm tài liệu mà vai đang hỏi thấy được là một bộ nhãn đã tự lọc theo quyền.
    """
    theo_id = anh.theo_id
    scope = {theo_id[he.id].scope for n in nhan.nhan for he in n.hyperedge}
    assert {"noi_bo", "khach_hang_a", "khach_hang_b"} <= scope


def test_nhan_dung_ca_tai_lieu_corpus_lan_tai_lieu_bo_vang(nhan):
    """Nhãn liệt kê hyperedge trong **toàn** space `synth`, kể cả từ `eval/data`.

    Đó là đồ thị mà Đo 3 chạy trên; bỏ 10 tài liệu bộ vàng ra khỏi tầm nhìn của
    nhãn là đo trên một kho khác kho thật.
    """
    doc = {he.doc_key for n in nhan.nhan for he in n.hyperedge}
    assert any(d.endswith(".txt") for d in doc), "không nhãn nào chạm eval/data"
    assert any(d.endswith(".md") for d in doc), "không nhãn nào chạm eval/corpus"


def test_so_cap_cau_hyperedge_la_mau_so_tho_cua_do_ba(nhan):
    assert nhan.so_cap() == sum(len(n.hyperedge) for n in nhan.nhan) == 41


def test_co_cau_n5_bo_vang_hoi_boi_tech_support_cham_vung_l1(bo, nhan, anh):
    """Tập câu của vòng so có/không chặn chunk (PRD 5.3) phải tồn tại.

    PRD chốt trước tập đó là "các câu N5 thuộc bộ vàng 30 câu có nhãn chạm vùng
    L1, chạy ở vai Tech Support". Nếu bộ câu không có câu nào như vậy thì một
    phép đo đã hứa trong PRD không có đầu vào.
    """
    policy = load_policy(POLICY)
    hang = policy.role("tech_support")
    theo_id = anh.theo_id
    hop_le = [
        c
        for c in bo.bo_vang()
        if c.nhom == "N5" and c.vai_hoi == "tech_support"
        for he in nhan.theo_cau[c.id].hyperedge
        if hang.level(theo_id[he.id].content_type or "") == "L1"
    ]
    assert hop_le, "không câu N5 bộ vàng nào của tech_support chạm vùng L1"


def test_nhan_khong_loc_theo_muc_tiet_lo(nhan, anh):
    """Nhãn phải chứa cả hyperedge mà *không vai nào* thấy được hôm nay.

    Đây là chốt của spec: lọc nhãn theo mức tiết lộ thì cả bốn cấu hình của Đo 3
    đều ra recall 100% và phép đo mất nghĩa. Bằng chứng rẻ nhất là có ít nhất
    một hyperedge được nhãn nhắc tới mà cả `devops` lẫn `tech_support` đều
    không chạm tới - nếu không có, nhãn đã bị lọc mất phần khó.
    """
    tran = tran_theo_vai(nhan, anh, policy=load_policy(POLICY))
    tong = sum(t.tong for t in tran.values()) // len(tran)
    thay = max(t.ton_tai for t in tran.values())
    assert thay < tong, "mọi hyperedge của nhãn đều thấy được: nhãn đã bị lọc theo quyền"


# --------------------------------------------------------------------------
# I/O Matrix: ảnh chụp
# --------------------------------------------------------------------------


def test_anh_chup_rong_bi_tu_choi(tmp_path):
    """Hàng "Ảnh chụp rỗng": nêu space và số 0, không trả một ảnh chụp trống."""
    duong_dan = _anh(tmp_path, hyperedge=[], so_hyperedge=0)
    with pytest.raises(AnhDoThiRong) as loi:
        doc_anh_do_thi(duong_dan)
    assert "synth" in str(loi.value) and "0" in str(loi.value)
    assert loi.value.code == "ANH_DO_THI_RONG"


def test_anh_chup_lech_so_dem_bi_tu_choi(tmp_path):
    duong_dan = _anh(tmp_path, so_hyperedge=99)
    with pytest.raises(AnhDoThiKhongHopLe):
        doc_anh_do_thi(duong_dan)


def test_anh_chup_vai_la_bi_tu_choi(tmp_path):
    he = _he("he-aaa", ["t1.md"], "App01")
    he["slots"]["nguyen_nhan"] = ["x"]
    with pytest.raises(AnhDoThiKhongHopLe) as loi:
        doc_anh_do_thi(_anh(tmp_path, [he]))
    assert "nguyen_nhan" in str(loi.value)


def test_anh_chup_thieu_file_neu_ten_file(tmp_path):
    with pytest.raises(AnhDoThiKhongHopLe) as loi:
        doc_anh_do_thi(tmp_path / "khong-co.json")
    assert "khong-co.json" in str(loi.value)


def test_hyperedge_khong_khoa_van_vao_anh_chup(tmp_path):
    """`khoa: null` là ca hợp nhất khác scope (AD-5), không phải dữ liệu hỏng."""
    he = _he("he-aaa", ["t1.md", "t2.md"], "App01", khoa=None)
    anh = doc_anh_do_thi(_anh(tmp_path, [he]))
    assert anh.hyperedge[0].khoa is None
    assert anh.hyperedge[0].scope is None
    assert len(anh.da_nguon()) == 1


# --------------------------------------------------------------------------
# I/O Matrix: bộ câu hỏi
# --------------------------------------------------------------------------


def test_bo_cau_hoi_nho_hop_le_nap_duoc(tmp_path):
    _, cau, _ = _bo_ba(tmp_path)
    bo = doc_bo_cau_hoi(cau)
    assert len(bo.cau) == TONG_CAU
    assert len(bo.bo_vang()) == SO_CAU_BO_VANG


def test_phan_bo_lech_bi_tu_choi_kem_hai_so(tmp_path):
    """Hàng "Phân bố lệch": nêu nhóm và hai số."""
    phan_bo = dict(PHAN_BO)
    phan_bo["N3"] -= 1
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, _cac_cau(phan_bo, so_bo_vang=SO_CAU_BO_VANG)))
    thong_diep = str(loi.value)
    assert "N3" in thong_diep and "11" in thong_diep and "12" in thong_diep
    assert loi.value.code == "BO_CAU_HOI_KHONG_HOP_LE"


def test_bo_vang_thieu_mot_cau_n7_bi_tu_choi(tmp_path):
    """Hàng "Bộ vàng thiếu N7": nêu đúng câu N7 bị bỏ."""
    cau = _cac_cau()
    bo_ra = next(c for c in cau if c["nhom"] == "N7")
    bo_ra.update(bo_vang=False, dap_an="", y_chinh=[])
    # Bù một câu khác để tổng vẫn đúng 30, nên lỗi duy nhất là câu N7 bị bỏ.
    them = next(c for c in cau if not c["bo_vang"] and c["nhom"] != "N7")
    them.update(bo_vang=True, dap_an="Đáp án tay.", y_chinh=["ý chính"])
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert bo_ra["id"] in str(loi.value)


def test_cau_bo_vang_khong_co_dap_an_bi_tu_choi(tmp_path):
    """Hàng "Câu bộ vàng không có đáp án": nêu id câu."""
    cau = _cac_cau()
    hong = next(c for c in cau if c["bo_vang"])
    hong["dap_an"] = "   "
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert hong["id"] in str(loi.value)


def test_cau_khong_phai_bo_vang_ma_co_dap_an_bi_tu_choi(tmp_path):
    """Chiều ngược lại: đáp án tay nằm ngoài 30 câu là mẫu số Đo 2 nở ra âm thầm."""
    cau = _cac_cau()
    hong = next(c for c in cau if not c["bo_vang"])
    hong["dap_an"] = "Đáp án tay."
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert hong["id"] in str(loi.value)


def test_so_cau_bo_vang_lech_bi_tu_choi(tmp_path):
    cau = _cac_cau(so_bo_vang=SO_CAU_BO_VANG - 1)
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert "29" in str(loi.value) and "30" in str(loi.value)


def test_mot_nhom_khong_co_cau_bo_vang_nao_bi_tu_choi(tmp_path):
    """"Sáu nhóm còn lại đều có ít nhất một câu" là luật, không phải khuyến nghị."""
    cau = _cac_cau(so_bo_vang=0)
    n7 = [c for c in cau if c["nhom"] == "N7"]
    khac = [c for c in cau if c["nhom"] not in ("N7", "N6")]
    for c in n7 + khac[: SO_CAU_BO_VANG - len(n7)]:
        c.update(bo_vang=True, dap_an="Đáp án tay.", y_chinh=["ý chính"])
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert "N6" in str(loi.value)


def test_id_cau_trung_bi_tu_choi(tmp_path):
    cau = _cac_cau()
    cau[1]["id"] = cau[0]["id"]
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert cau[0]["id"] in str(loi.value)


def test_vai_hoi_ngoai_seed_danh_tinh_bi_tu_choi(tmp_path):
    cau = _cac_cau()
    cau[0]["vai_hoi"] = "sale_ba"
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert "sale_ba" in str(loi.value)


def test_kich_ban_ngoai_bang_thiet_ke_corpus_bi_tu_choi(tmp_path):
    """Kịch bản lấy từ `eval/corpus_thiet_ke.yaml`, không phải chuỗi tự do."""
    cau = _cac_cau()
    cau[0]["kich_ban"] = "web_sap_2"
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert "web_sap_2" in str(loi.value)


def test_khoa_la_o_cap_cau_bi_tu_choi(tmp_path):
    cau = _cac_cau()
    cau[0]["ghi_chu"] = "x"
    with pytest.raises(BoCauHoiKhongHopLe) as loi:
        doc_bo_cau_hoi(_bo_cau(tmp_path, cau))
    assert "ghi_chu" in str(loi.value)


def test_version_la_bi_tu_choi(tmp_path):
    with pytest.raises(BoCauHoiKhongHopLe):
        doc_bo_cau_hoi(_bo_cau(tmp_path, version=2))


# --------------------------------------------------------------------------
# I/O Matrix: nhãn truy hồi vàng
# --------------------------------------------------------------------------


def test_nhan_nho_hop_le_nap_duoc(tmp_path):
    duong_anh, duong_cau, duong_nhan = _bo_ba(tmp_path)
    nhan = doc_nhan_truy_hoi(
        duong_nhan, bo=doc_bo_cau_hoi(duong_cau), anh=doc_anh_do_thi(duong_anh)
    )
    assert len(nhan.nhan) == PHAN_BO["N3"] + PHAN_BO["N5"]


def test_nhan_tro_id_la_bi_tu_choi(tmp_path):
    """Hàng "Nhãn trỏ id lạ": id không có trong ảnh chụp *và* neo không cứu được."""
    cau = _cac_cau()
    nhan = _cac_nhan(cau)
    nhan[0]["hyperedge"][0].update(id="he-khong-co", neo_subject="Chủ thể không có")
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    assert "he-khong-co" in str(loi.value) and nhan[0]["cau_id"] in str(loi.value)
    assert loi.value.code == "NHAN_KHONG_HOP_LE"


def test_id_troi_nhung_neo_con_khop_bao_id_moi(tmp_path):
    """Hàng "Id trôi nhưng neo còn khớp": nêu câu, id cũ và id mới đề xuất."""
    cau = _cac_cau()
    nhan = _cac_nhan(cau)
    nhan[0]["hyperedge"][0]["id"] = "he-cu-da-troi"
    with pytest.raises(NhanTroiId) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    thong_diep = str(loi.value)
    assert nhan[0]["cau_id"] in thong_diep
    assert "he-cu-da-troi" in thong_diep and "he-aaa" in thong_diep
    assert loi.value.code == "NHAN_TROI_ID"


def test_neo_mo_ta_khop_nhieu_hyperedge_bao_mo_ho(tmp_path):
    """Hàng "Neo mô tả khớp nhiều hyperedge": nêu các id ứng viên."""
    cau = _cac_cau()
    he = [
        _he("he-aaa", ["t1.md"], "App01", cause="x"),
        _he("he-bbb", ["t1.md"], "App01", symptom="y"),
    ]
    with pytest.raises(NhanTroiId) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, _cac_nhan(cau)),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path, he)),
        )
    assert "he-aaa" in str(loi.value) and "he-bbb" in str(loi.value)


def test_cau_ngoai_n3_n5_co_nhan_bi_tu_choi(tmp_path):
    """Hàng "Câu ngoài N3/N5 có nhãn": PRD cố ý tiết kiệm công T2."""
    cau = _cac_cau()
    nhan = _cac_nhan(cau)
    ngoai = next(c for c in cau if c["nhom"] == "N1")
    nhan.append({"cau_id": ngoai["id"], "hyperedge": list(nhan[0]["hyperedge"])})
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    assert ngoai["id"] in str(loi.value)


def test_cau_n3_thieu_nhan_bi_tu_choi(tmp_path):
    """Chiều ngược lại của luật một-một: một câu N3 không nhãn là một lỗ mẫu số."""
    cau = _cac_cau()
    nhan = _cac_nhan(cau)
    thieu = nhan.pop(0)
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    assert thieu["cau_id"] in str(loi.value)


def test_slot_dap_an_sai_ten_bi_tu_choi_kem_tam_vai(tmp_path):
    """Hàng "Slot đáp án sai tên": liệt kê 8 vai hợp lệ."""
    cau = _cac_cau()
    nhan = _cac_nhan(cau, slot_dap_an=("nguyen_nhan",))
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    thong_diep = str(loi.value)
    assert "nguyen_nhan" in thong_diep
    for vai in SLOT_ROLES:
        assert vai in thong_diep


def test_slot_dap_an_khong_co_trong_hyperedge_bi_tu_choi(tmp_path):
    """Slot đáp án phải là vai mà chính hyperedge đó có điền, không phải vai rỗng."""
    cau = _cac_cau()
    nhan = _cac_nhan(cau, slot_dap_an=("time",))
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path, [_he("he-aaa", ["t1.md"], "App01", cause="x")])),
        )
    assert "time" in str(loi.value)


def test_cau_id_khong_co_trong_bo_cau_hoi_bi_tu_choi(tmp_path):
    cau = _cac_cau()
    nhan = _cac_nhan(cau)
    nhan[0]["cau_id"] = "n3-99"
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    assert "n3-99" in str(loi.value)


def test_hai_nhan_cho_cung_mot_cau_bi_tu_choi(tmp_path):
    cau = _cac_cau()
    nhan = _cac_nhan(cau)
    nhan.append(dict(nhan[0]))
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    assert nhan[0]["cau_id"] in str(loi.value)


def test_nhan_rong_hyperedge_bi_tu_choi(tmp_path):
    cau = _cac_cau()
    nhan = _cac_nhan(cau)
    nhan[0]["hyperedge"] = []
    with pytest.raises(NhanKhongHopLe) as loi:
        doc_nhan_truy_hoi(
            _nhan(tmp_path, nhan),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path)),
        )
    assert nhan[0]["cau_id"] in str(loi.value)


# --------------------------------------------------------------------------
# Trần lý thuyết theo vai
# --------------------------------------------------------------------------


def test_tran_theo_vai_tinh_cho_dung_hai_vai_cua_seed(nhan, anh):
    tran = tran_theo_vai(nhan, anh, policy=load_policy(POLICY))
    assert set(tran) == set(HAI_VAI)


def test_tran_cua_devops_khong_thap_hon_tech_support(nhan, anh):
    """Chênh giữa hai vai phải giải thích được bằng `scopes`, không bằng nhãn tay.

    `devops` chạm `noi_bo` cộng `khach_hang_a`, `tech_support` chỉ chạm
    `noi_bo`, và bảng chính sách cho `devops` mức tiết lộ không thấp hơn ở mọi
    loại nội dung đã khai. Nên trần của `devops` là một tập cha.
    """
    tran = tran_theo_vai(nhan, anh, policy=load_policy(POLICY))
    assert tran["devops"].ton_tai >= tran["tech_support"].ton_tai
    assert tran["devops"].tra_loi_duoc >= tran["tech_support"].tra_loi_duoc


def test_tran_khong_bao_gio_vuot_tong_va_tra_loi_duoc_khong_vuot_ton_tai(nhan, anh):
    for t in tran_theo_vai(nhan, anh, policy=load_policy(POLICY)).values():
        assert 0 <= t.tra_loi_duoc <= t.ton_tai <= t.tong
        for c in t.cau:
            assert 0 <= c.tra_loi_duoc <= c.ton_tai <= c.tong


def test_tran_bang_khong_la_canh_bao_chu_khong_phai_loi(tmp_path):
    """Hàng "Trần lý thuyết bằng 0": tính ra 0 và in cảnh báo, không ném."""
    cau = _cac_cau()
    he = [_he("he-aaa", ["t1.md"], "App01", cause="x", khoa=filter_key("noi_bo", "log"))]
    tran = tran_theo_vai(
        doc_nhan_truy_hoi(
            _nhan(tmp_path, _cac_nhan(cau)),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path, he)),
        ),
        doc_anh_do_thi(_anh(tmp_path, he)),
        policy=load_policy(POLICY),
    )
    for vai, t in tran.items():
        assert t.ton_tai == 0, vai
        assert t.canh_bao(), f"{vai}: trần 0 mà không có cảnh báo nào"
        assert any("loại nội dung" in c or "log" in c for c in t.canh_bao())


def test_hyperedge_khong_khoa_khong_vao_tran_cua_vai_nao(tmp_path):
    cau = _cac_cau()
    he = [_he("he-aaa", ["t1.md", "t2.md"], "App01", cause="x", khoa=None)]
    tran = tran_theo_vai(
        doc_nhan_truy_hoi(
            _nhan(tmp_path, _cac_nhan(cau)),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path, he)),
        ),
        doc_anh_do_thi(_anh(tmp_path, he)),
        policy=load_policy(POLICY),
    )
    assert all(t.ton_tai == 0 for t in tran.values())


def test_slot_bi_che_lam_mat_lop_tra_loi_duoc_chu_khong_mat_lop_ton_tai(tmp_path):
    """Hai lớp recall của PRD 5.3 tách bạch ngay ở phép tính trần.

    `tech_support` ở L1 với `bao_cao_su_co` và bảng chính sách che `cause`:
    hyperedge vẫn *tồn tại* trong ngữ cảnh nhưng slot mang đáp án bị che, nên
    lớp "trả lời được" mất còn lớp "tồn tại" thì không.
    """
    cau = _cac_cau()
    he = [
        _he(
            "he-aaa",
            ["t1.md"],
            "App01",
            cause="x",
            khoa=filter_key("noi_bo", "bao_cao_su_co"),
        )
    ]
    tran = tran_theo_vai(
        doc_nhan_truy_hoi(
            _nhan(tmp_path, _cac_nhan(cau)),
            bo=doc_bo_cau_hoi(_bo_cau(tmp_path, cau)),
            anh=doc_anh_do_thi(_anh(tmp_path, he)),
        ),
        doc_anh_do_thi(_anh(tmp_path, he)),
        policy=load_policy(POLICY),
    )
    ts = tran["tech_support"]
    assert ts.ton_tai == ts.tong > 0
    assert ts.tra_loi_duoc == 0
    assert tran["devops"].tra_loi_duoc == tran["devops"].tong


# --------------------------------------------------------------------------
# Trang soát nhãn
# --------------------------------------------------------------------------


def _chay_xem(*args):
    return subprocess.run(
        [sys.executable, "-m", "eval.xem_cau_hoi", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_trang_soat_dung_duoc_va_in_phan_bo(tmp_path):
    dich = tmp_path / "bo_cau_hoi.html"
    kq = _chay_xem(str(dich))
    assert kq.returncode == 0, kq.stderr
    assert "52" in kq.stdout and "30" in kq.stdout
    trang = dich.read_text(encoding="utf-8")
    assert "<html" in trang
    for nhom in NHOM:
        assert nhom in trang
    for vai in HAI_VAI:
        assert vai in trang


def test_trang_soat_thieu_file_thi_neu_ten_file_va_thoat_mot(tmp_path):
    kq = _chay_xem(
        str(tmp_path / "x.html"), "--bo-cau-hoi", str(tmp_path / "khong-co.json")
    )
    assert kq.returncode == 1
    assert "khong-co.json" in kq.stderr
    assert not (tmp_path / "x.html").exists()


# --------------------------------------------------------------------------
# Đường chụp ảnh đồ thị (phần thuần, không chạm kho)
# --------------------------------------------------------------------------


def test_dung_anh_gom_doc_key_va_dem_da_nguon():
    from eval.chup_do_thi import dung_anh

    anh = dung_anh(
        space="synth",
        ngay_do="2026-09-03T00:00:00+00:00",
        doc_key_theo_id={"he-b": {"t2.md"}, "he-a": {"t1.md", "t0.md"}},
        slots_theo_id={"he-a": {"cause": ["x"], "subject": ["App01"]}, "he-b": {"subject": ["Log01"]}},
        khoa_theo_id={"he-a": "noi_bo:runbook", "he-b": None},
    )
    assert [h["id"] for h in anh["hyperedge"]] == ["he-a", "he-b"]
    assert anh["hyperedge"][0]["doc_key"] == ["t0.md", "t1.md"]
    assert list(anh["hyperedge"][0]["slots"]) == ["subject", "cause"], "thứ tự SLOT_ROLES"
    assert anh["so_hyperedge"] == 2 and anh["so_hyperedge_da_nguon"] == 1


def test_dung_anh_rong_thi_nem_anh_do_thi_rong():
    from eval.chup_do_thi import dung_anh

    with pytest.raises(AnhDoThiRong) as loi:
        dung_anh(
            space="synth",
            ngay_do="2026-09-03T00:00:00+00:00",
            doc_key_theo_id={},
            slots_theo_id={},
            khoa_theo_id={},
        )
    assert "synth" in str(loi.value)


def test_chup_thieu_bien_moi_truong_neu_ten_bien():
    """Hàng "Chụp đồ thị" ca hỏng: nêu tên biến môi trường, không ghi file."""
    from eval.chup_do_thi import BIEN_BAT_BUOC, thieu_bien_moi_truong

    thieu = thieu_bien_moi_truong({})
    assert thieu == list(BIEN_BAT_BUOC)
    assert "NEO4J_URI" in thieu and "HYPER_RAG_WORKING_DIR" in thieu
    assert thieu_bien_moi_truong({b: "x" for b in BIEN_BAT_BUOC}) == []
