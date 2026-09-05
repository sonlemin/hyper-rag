"""Lược đồ fact 8 vai, mã loại, id mờ và câu render của `core/facts.py` (story 2.4).

Viết trước cơ chế (FR-27), thuần `core/`: không kho, không LLM. Mỗi hàng lược
đồ trong I/O Matrix của spec là một ca; mã loại được đọc từ chính hằng của
`core/`, không viết tay ở test.
"""

import json
import re
import unicodedata

import pytest

from core.facts import (
    GIA_TRI_TOI_DA,
    MA_GIA_TRI_QUA_DAI,
    MA_GIA_TRI_RONG,
    MA_GIA_TRI_SAI_KIEU,
    MA_IT_HON_HAI_VAI,
    MA_KHONG_PHAI_JSON,
    MA_KHONG_PHAI_OBJECT,
    MA_LOAI_CHUNK,
    MA_LOAI_FACT,
    MA_THIEU_FACTS,
    MA_THIEU_SUBJECT,
    MA_VAI_LA,
    TEN_VAI_TIENG_VIET,
    TIEN_TO_ID_FACT,
    ap_bi_danh,
    cau_fact,
    chuan_hoa_gia_tri,
    id_fact,
    kiem_fact,
    phan_tich_phan_hoi,
)
from core.slots import SLOT_ROLE_SET, SLOT_ROLES

FACT_DU = {
    "subject": "App01",
    "symptom": "trang thanh toán trả lỗi 502",
    "cause": "chỉnh sai giới hạn bộ nhớ PHP-FPM",
    "condition": "traffic vượt 5000 request mỗi phút",
    "remediation": "trả giới hạn bộ nhớ về mức cũ",
    "source": "báo cáo sự cố INC-1208",
    "time": "2026-08-12 09:20",
    "owner": "Trần Thị Hạnh",
}


# --- Danh mục vai --------------------------------------------------------------


def test_ten_vai_tieng_viet_khop_danh_muc_8_vai():
    """Nhãn tiếng Việt map đúng từ danh mục `core.slots`, không có vai thứ chín."""
    assert set(TEN_VAI_TIENG_VIET) == SLOT_ROLE_SET
    assert all(isinstance(v, str) and v.strip() for v in TEN_VAI_TIENG_VIET.values())


def test_ma_loai_fact_va_ma_loai_chunk_roi_nhau():
    assert MA_LOAI_FACT & MA_LOAI_CHUNK == frozenset()
    assert {MA_KHONG_PHAI_JSON, MA_THIEU_FACTS} == MA_LOAI_CHUNK
    assert {
        MA_KHONG_PHAI_OBJECT,
        MA_VAI_LA,
        MA_THIEU_SUBJECT,
        MA_IT_HON_HAI_VAI,
        MA_GIA_TRI_SAI_KIEU,
        MA_GIA_TRI_RONG,
        MA_GIA_TRI_QUA_DAI,
    } == MA_LOAI_FACT


# --- kiem_fact: từng hàng I/O Matrix -------------------------------------------


def test_fact_du_8_vai_hop_le_va_gia_tri_duoc_chuan_hoa():
    slots, ma = kiem_fact({**FACT_DU, "owner": "  Trần  Thị   Hạnh "})
    assert ma is None
    assert set(slots) == SLOT_ROLE_SET
    assert slots["owner"] == "Trần Thị Hạnh"


def test_fact_hai_vai_hop_le_fr_04():
    """Quan hệ 2 ngôi là fact 2 slot, không nhánh riêng."""
    slots, ma = kiem_fact({"subject": "VPN", "condition": "làm việc ngoài văn phòng"})
    assert ma is None and set(slots) == {"subject", "condition"}


@pytest.mark.parametrize(
    "obj, ma",
    [
        ({"subject": "x", "root_cause": "y"}, MA_VAI_LA),
        ({"cause": "x"}, MA_THIEU_SUBJECT),
        ({"subject": "x"}, MA_IT_HON_HAI_VAI),
        ({"subject": "x", "cause": ["a", "b"]}, MA_GIA_TRI_SAI_KIEU),
        ({"subject": "x", "cause": None}, MA_GIA_TRI_SAI_KIEU),
        ({"subject": "x", "cause": ""}, MA_GIA_TRI_RONG),
        ({"subject": "x", "cause": '""'}, MA_GIA_TRI_RONG),
        ({"subject": "x", "cause": '"""'}, MA_GIA_TRI_RONG),
        ({"subject": "x", "cause": "---"}, MA_GIA_TRI_RONG),
        ({"subject": "x", "cause": " ... "}, MA_GIA_TRI_RONG),
        ({"subject": "x", "cause": "a" * (GIA_TRI_TOI_DA + 100)}, MA_GIA_TRI_QUA_DAI),
        (["subject", "x"], MA_KHONG_PHAI_OBJECT),
        ("subject: x", MA_KHONG_PHAI_OBJECT),
    ],
    ids=[
        "vai_la",
        "thieu_subject",
        "chi_mot_vai",
        "gia_tri_list",
        "gia_tri_null",
        "gia_tri_rong",
        "gia_tri_chi_co_nhay",
        "gia_tri_ba_nhay",
        "gia_tri_chi_gach",
        "gia_tri_chi_cham",
        "gia_tri_qua_dai",
        "fact_la_list",
        "fact_la_chuoi",
    ],
)
def test_fact_sai_luoc_do_bi_loai_kem_ma_khong_nem(obj, ma):
    slots, ma_thay = kiem_fact(obj)
    assert slots is None and ma_thay == ma
    assert ma in MA_LOAI_FACT


def test_gia_tri_dung_300_ky_tu_van_hop_le():
    slots, ma = kiem_fact({"subject": "x", "cause": "a" * GIA_TRI_TOI_DA})
    assert ma is None and len(slots["cause"]) == GIA_TRI_TOI_DA


# --- phan_tich_phan_hoi: cả chunk --------------------------------------------


@pytest.mark.parametrize("text", ["đây là văn bản tự do", "", "   ", "{'facts': []}"])
def test_chunk_khong_json_loai_ca_chunk(text):
    kq = phan_tich_phan_hoi(text)
    assert kq.chunk_hong is True and kq.facts == ()
    assert dict(kq.loai_theo_ma) == {MA_KHONG_PHAI_JSON: 1}
    assert kq.so_ban_ghi == 0


@pytest.mark.parametrize("text", ["{}", '{"fact": []}', '{"facts": "x"}', "[]", '"facts"'])
def test_chunk_thieu_facts_loai_ca_chunk(text):
    kq = phan_tich_phan_hoi(text)
    assert kq.chunk_hong is True and kq.facts == ()
    assert dict(kq.loai_theo_ma) == {MA_THIEU_FACTS: 1}


def test_chunk_khong_co_fact_hop_le_khong_phai_chunk_hong():
    kq = phan_tich_phan_hoi('{"facts": []}')
    assert kq.chunk_hong is False and kq.facts == () and kq.so_ban_ghi == 0
    assert dict(kq.loai_theo_ma) == {}


def test_chunk_bao_ma_json_van_doc_duoc():
    """JSON mode của provider thường sạch, nhưng một lớp rào ```json vô hại thì không đáng loại cả chunk."""
    kq = phan_tich_phan_hoi('```json\n{"facts": [{"subject": "a", "cause": "b"}]}\n```')
    assert kq.chunk_hong is False and len(kq.facts) == 1


def test_phan_tich_dem_tung_ma_va_giu_fact_hop_le():
    text = json.dumps(
        {
            "facts": [
                FACT_DU,
                {"subject": "x", "root_cause": "y"},
                {"cause": "x"},
                {"subject": "x", "cause": ""},
                {"subject": "x", "cause": ""},
                "không phải object",
                {"subject": "VPN", "condition": "ngoài văn phòng"},
            ]
        },
        ensure_ascii=False,
    )
    kq = phan_tich_phan_hoi(text)
    assert kq.chunk_hong is False
    assert kq.so_ban_ghi == 7
    assert [f["subject"] for f in kq.facts] == ["App01", "VPN"]
    assert dict(kq.loai_theo_ma) == {
        MA_VAI_LA: 1,
        MA_THIEU_SUBJECT: 1,
        MA_GIA_TRI_RONG: 2,
        MA_KHONG_PHAI_OBJECT: 1,
    }
    assert sum(kq.loai_theo_ma.values()) + len(kq.facts) == kq.so_ban_ghi


# --- id_fact: id mờ ------------------------------------------------------------


def test_id_fact_la_he_cong_24_hex_va_khong_mang_gia_tri():
    id_he = id_fact(FACT_DU)
    assert id_he.startswith(TIEN_TO_ID_FACT) and TIEN_TO_ID_FACT == "he-"
    assert re.fullmatch(r"he-[0-9a-f]{24}", id_he)
    for gia_tri in FACT_DU.values():
        assert gia_tri not in id_he


def test_id_fact_on_dinh_theo_noi_dung_khong_theo_hinh_thuc():
    """NFC/NFD, khoảng trắng thừa và thứ tự khóa không đổi id; đổi một giá trị thì đổi id."""
    nfd = {k: unicodedata.normalize("NFD", v) for k, v in FACT_DU.items()}
    rong = {k: f"  {v}   ".replace(" ", "  ", 1) for k, v in FACT_DU.items()}
    dao = dict(reversed(list(FACT_DU.items())))
    assert id_fact(nfd) == id_fact(rong) == id_fact(dao) == id_fact(FACT_DU)
    assert id_fact({**FACT_DU, "cause": "khác"}) != id_fact(FACT_DU)
    assert id_fact({"subject": "VPN", "condition": "a"}) != id_fact({"subject": "VPN", "cause": "a"})


def test_id_fact_tu_choi_vai_la_va_gia_tri_sai_kieu():
    with pytest.raises(ValueError):
        id_fact({"subject": "x", "root_cause": "y"})
    with pytest.raises(TypeError):
        id_fact({"subject": "x", "cause": 1})


# --- cau_fact: câu render --------------------------------------------------------


def test_cau_fact_mang_du_gia_tri_theo_thu_tu_vai():
    cau = cau_fact(FACT_DU)
    vi_tri = [cau.index(FACT_DU[vai]) for vai in SLOT_ROLES]
    assert vi_tri == sorted(vi_tri), "giá trị ra theo đúng thứ tự SLOT_ROLES"
    for vai in SLOT_ROLES:
        assert TEN_VAI_TIENG_VIET[vai] in cau


def test_cau_fact_nhan_danh_sach_gia_tri_moi_vai():
    """Đường dựng lại hyperedge chung đọc `slot_cua_hyperedge` dạng `{vai: [id...]}`."""
    cau = cau_fact({"subject": ["App01"], "cause": ["a", "b"]})
    assert "App01" in cau and "a" in cau and "b" in cau
    assert cau_fact({}) == ""


def test_cau_fact_khong_doi_khi_id_khong_doi():
    assert cau_fact(FACT_DU) == cau_fact(dict(reversed(list(FACT_DU.items()))))


# --- chuan_hoa_gia_tri ---------------------------------------------------------------


def test_chuan_hoa_gia_tri_nfc_gop_khoang_trang_bo_nhay_bao():
    assert chuan_hoa_gia_tri("  a \n\t b  ") == "a b"
    assert chuan_hoa_gia_tri(unicodedata.normalize("NFD", "Hạnh")) == "Hạnh"
    assert chuan_hoa_gia_tri('"App01"') == "App01"
    assert chuan_hoa_gia_tri('""') == ""


# --- ap_bi_danh (story 2.12, FR-32) --------------------------------------------------


def test_ap_bi_danh_bang_rong_la_ham_dong_nhat():
    """Ca "không khai từ điển" của I/O Matrix: không đổi một byte."""
    slots = {"subject": "App01", "cause": "sai giới hạn bộ nhớ"}
    assert ap_bi_danh(slots, {}) == slots
    assert ap_bi_danh(slots, {}) is not slots


def test_ap_bi_danh_thay_bi_danh_bang_ten_chuan():
    bang = {"app01.company.vn": "App01", "APP-01": "App01"}
    assert ap_bi_danh({"subject": "app01.company.vn"}, bang)["subject"] == "App01"
    assert ap_bi_danh({"subject": "APP-01"}, bang)["subject"] == "App01"
    # Giá trị không có trong bảng giữ nguyên: bảng là danh sách trắng, không
    # phải một phép chuẩn hóa chung cho mọi chuỗi.
    assert ap_bi_danh({"subject": "App02"}, bang)["subject"] == "App02"


def test_hai_cach_viet_cho_dung_mot_id_fact():
    """Điều kiện nghiệm thu của FR-32, phát biểu ở mức `core/`."""
    bang = {"app01.company.vn": "App01"}
    a = ap_bi_danh({"subject": "App01", "symptom": "lỗi 502"}, bang)
    b = ap_bi_danh({"subject": "app01.company.vn", "symptom": "lỗi 502"}, bang)
    assert id_fact(a) == id_fact(b)


def test_ap_bi_danh_tra_qua_chuan_hoa_gia_tri():
    """Khóa tra đi qua đúng hàm mà `kiem_fact` và `_json_chuan_hoa` dùng.

    Bảng tra bằng một hàm khác là một bí danh trượt vì một dấu cách - và
    `chuan_hoa_gia_tri` đồng nhất với `core.ids.normalize_id`, hàm sinh id
    entity, nên id fact và id entity không thể thấy hai tên khác nhau.
    """
    bang = {"phòng IT": "Phòng IT"}
    assert ap_bi_danh({"owner": "  phòng    IT "}, bang)["owner"] == "Phòng IT"
    assert ap_bi_danh({"owner": '"phòng IT"'}, bang)["owner"] == "Phòng IT"


def test_ap_bi_danh_chi_khop_tron_gia_tri_khong_khop_chuoi_con():
    """Vai mệnh đề không bị viết lại.

    `cause` và `remediation` là mệnh đề trong chính nhãn tay của bộ vàng 2.5;
    thay chuỗi con bên trong chúng là viết lại câu của người gán nhãn, và bản
    viết lại đó không còn khớp nhãn nào.
    """
    bang = {"app01": "App01"}
    slots = {"subject": "X", "cause": "app01 hết bộ nhớ"}
    assert ap_bi_danh(slots, bang)["cause"] == "app01 hết bộ nhớ"


def test_ap_bi_danh_chi_ap_dung_mot_buoc():
    """Bảng đã kiểm không có chuỗi hai bước, nhưng hàm vẫn phải chỉ đi một bước.

    Nếu ai đó gọi thẳng hàm này với một bảng dựng tay có chuỗi, kết quả phải là
    một bước - tất định, không phụ thuộc thứ tự duyệt và không lặp vô hạn.
    """
    bang = {"a": "b", "b": "c"}
    assert ap_bi_danh({"subject": "a"}, bang)["subject"] == "b"


def test_ap_bi_danh_khong_sua_slots_goc():
    slots = {"subject": "app01"}
    ap_bi_danh(slots, {"app01": "App01"})
    assert slots == {"subject": "app01"}
