"""Bộ vàng trích xuất: lược đồ, loader và mẫu số (story 2.5, FR-02, R2).

Viết trước `eval/bo_vang.py` và trước file JSON (FR-27: test là đặc tả). Ba
nhóm ca:

- **Ca hợp lệ chạy trên bộ vàng thật** (`eval/bo_vang_trich_xuat.json` cộng
  `eval/data/`). Đây là mẫu số của ngưỡng 60% ở R2, nên nó phải được canh bằng
  chính bộ test chứ không bằng một lần đọc tay: 10 tài liệu, đúng hai tài liệu
  few-shot, đủ ba loại nội dung, đủ 8 vai, mẫu số bằng tổng slot đã điền của
  đúng 8 tài liệu chấm, và mọi giá trị slot là đoạn có thật trong thân.
- **Ca lỗi dựng JSON nhỏ trong `tmp_path`**. Mỗi hàng I/O Matrix của spec là
  một test, cộng một ca cho mỗi guard của loader - guard không có ca chạy vào
  thì xóa nó đi bộ test vẫn xanh. Bộ vàng thật không được sửa để tạo ca lỗi.
- **Tripwire few-shot**: tập `{01, 05}` phải suy ra được từ chính
  `adapters.trich_xuat.VI_DU_DAU_RA`, không phải một hằng chép tay.

Bộ test không chạm kho, không gọi LLM, không cần mạng.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from core import facts
from core.ingest_scan import tach_frontmatter
from core.slots import SLOT_ROLES, SLOT_ROLE_SET
from eval.bo_vang import (
    TOI_DA_FEW_SHOT,
    BoVangKhongHopLe,
    chuan_so_sanh,
    doc_bo_vang,
    loai_cua_bang_chinh_sach,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hai tài liệu few-shot chốt trước khi có bất kỳ con số nào (spec 2.5,
# Boundaries). Hằng này là thứ *được kiểm*, không phải thứ dùng làm bằng chứng:
# `test_tripwire_few_shot_suy_ra_tu_vi_du_cua_prompt` suy tập này ra từ chính
# ví dụ trong prompt trích xuất.
FEW_SHOT = frozenset({"01-cap-quyen-gitlab.txt", "05-bao-cao-su-co-inc-1208.txt"})


# --------------------------------------------------------------------------
# Ca hợp lệ: bộ vàng thật
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bo_vang():
    """Bộ vàng thật của repo, nạp một lần cho cả module."""
    return doc_bo_vang()


def test_bo_vang_that_nap_duoc_va_du_muoi_tai_lieu(bo_vang):
    assert len(bo_vang.tai_lieu) == 10
    assert len({t.doc_key for t in bo_vang.tai_lieu}) == 10


def test_dung_hai_tai_lieu_few_shot_va_dung_hai_tai_lieu_do(bo_vang):
    """Luật few-shot của PRD 2.6: tối đa 2, và phải là đúng hai tài liệu prompt đã thấy."""
    assert {t.doc_key for t in bo_vang.tai_lieu_few_shot()} == FEW_SHOT


def _token(van_ban: str) -> list[str]:
    return [t for t in re.split(r"[^0-9\w]+", chuan_so_sanh(van_ban), flags=re.UNICODE) if t]


def test_tripwire_few_shot_suy_ra_tu_vi_du_cua_prompt(bo_vang):
    """Tài liệu nào là few-shot phải đọc ra được từ `VI_DU_DAU_RA`, không chép tay.

    Với mỗi fact trong ví dụ của prompt, tính tỉ lệ token của các giá trị slot
    có mặt trong thân từng tài liệu bộ vàng. Tài liệu prompt lấy ví dụ ra đạt
    1.0 và bỏ xa phần còn lại; hợp các tài liệu đó phải đúng bằng tập đang gắn
    `few_shot`. Đổi ví dụ prompt sang một tài liệu khác mà quên đổi cờ
    `few_shot` là test này đỏ - chính là ca ô nhiễm đánh giá mà PRD F8 sợ.

    So theo token chứ không theo chuỗi con vì luật ở đây là "tài liệu nào chứa
    *phần lớn* chữ của ví dụ", một phép đo mức độ chồng lấn: ví dụ gồm nhiều
    vai lấy từ nhiều câu khác nhau của cùng một tài liệu, nên không có một
    chuỗi con nào chứa trọn nó. Từ story 2.6 mọi giá trị của ví dụ đã là đoạn
    nguyên văn của thân tài liệu (`test_trich_xuat.py::
    test_moi_gia_tri_cua_vi_du_prompt_la_doan_co_that_trong_than_few_shot`),
    nên tỉ lệ của tài liệu nguồn là 1.0 - nhưng luật vẫn là token, vì cái test
    này hỏi "ví dụ lấy từ tài liệu nào", không hỏi "ví dụ có trích sát không".
    """
    from adapters.trich_xuat import VI_DU_DAU_RA

    than = {t.doc_key: set(_token(t.than)) for t in bo_vang.tai_lieu}
    nguon_vi_du = set()
    for fact in json.loads(VI_DU_DAU_RA)[facts.KHOA_FACTS]:
        tk = [t for gia_tri in fact.values() for t in _token(gia_tri)]
        diem = sorted(
            ((sum(1 for x in tk if x in than[k]) / len(tk), k) for k in than), reverse=True
        )
        assert diem[0][0] == 1.0, f"không tài liệu nào chứa trọn ví dụ: {diem[:2]}"
        assert diem[0][0] > diem[1][0], f"ví dụ khớp hai tài liệu ngang nhau: {diem[:2]}"
        nguon_vi_du.add(diem[0][1])
    assert nguon_vi_du == {t.doc_key for t in bo_vang.tai_lieu_few_shot()}


def test_tai_lieu_cham_la_phan_bu_cua_few_shot(bo_vang):
    cham = {t.doc_key for t in bo_vang.tai_lieu_cham()}
    assert len(cham) == 8
    assert cham & FEW_SHOT == set()
    assert cham | FEW_SHOT == {t.doc_key for t in bo_vang.tai_lieu}


def test_mau_so_la_tong_slot_da_dien_cua_dung_tam_tai_lieu_cham(bo_vang):
    """Đơn vị chấm là slot đã điền (PRD 2.6), mẫu số loại hai tài liệu few-shot."""
    cho_doi = sum(len(f.slots) for t in bo_vang.tai_lieu_cham() for f in t.facts)
    assert bo_vang.mau_so_slot() == cho_doi
    tong = sum(len(f.slots) for t in bo_vang.tai_lieu for f in t.facts)
    assert bo_vang.mau_so_slot() < tong, "mẫu số phải nhỏ hơn tổng: few-shot bị loại"


def test_phu_du_loai_noi_dung_cua_bang_chinh_sach(bo_vang):
    """Dữ liệu thật của `synth` phải phủ mọi loại mà bảng chính sách khai.

    Luật là một phép **bao hàm**, và mẫu đối chiếu đổi ở story 3.2: câu hỏi vẫn
    là "bảng chính sách có mất ca nào trên dữ liệu thật không", nhưng dữ liệu
    thật của space `synth` nay là corpus 42 tài liệu cộng 10 tài liệu bộ vàng
    chứ không còn là riêng bộ vàng. Đối chiếu với riêng bộ vàng thì bảng đầy đủ
    13 loại đòi gán nhãn tay 10 tài liệu mới và đổi mẫu số 151 slot của cổng R2.
    """
    from eval.bo_vang import loai_cua_bang_chinh_sach, loai_cua_corpus

    cua_bo = {t.content_type for t in bo_vang.tai_lieu}
    assert loai_cua_bang_chinh_sach() <= cua_bo | loai_cua_corpus()


def test_luat_phu_quet_ca_bon_bang_chinh_sach():
    """Luật phủ soi **mọi** `config/policy-*.yaml`, không riêng bảng vận hành.

    Khoản ledger 2.8: `POLICY_MAC_DINH` trỏ đúng một file, nên một cấu hình đo
    khai một loại nội dung không có ca nào trên dữ liệu thật sẽ đi qua im lặng.

    Khẳng định là một **đẳng thức với bảng hạng**, không phải "mỗi file là tập
    con của hợp bốn file" - vế sau luôn đúng theo định nghĩa và không canh gì.
    """
    from adapters.sensitivity_loader import bang_hang_mac_dinh
    from eval.bo_vang import cac_bang_chinh_sach, loai_cua_bang_chinh_sach

    cac_bang = cac_bang_chinh_sach()
    assert len(cac_bang) == 4, [p.name for p in cac_bang]
    co_hang = set(bang_hang_mac_dinh().hang)
    assert loai_cua_bang_chinh_sach() == co_hang
    # Và từng file một, vì validator đòi *mỗi* bảng khai đủ - hợp bốn file bằng
    # 13 loại vẫn đúng khi một file khai 12 còn file kia khai loại thứ 13.
    for duong_dan in cac_bang:
        assert loai_cua_bang_chinh_sach(duong_dan) == co_hang, duong_dan


def test_luat_phu_khong_thay_the_mau_so_cua_cong_r2():
    """Luật phủ nói về hình dạng truy hồi; cổng R2 vẫn đứng trên 3 loại bộ vàng.

    Đọc luật phủ thành "precision đã đo trên 13 loại" là đọc sai, và chỗ dễ đọc
    sai nhất là chương 4. Ghim khoảng cách đó bằng một con số: bảng chính sách
    khai 13 loại, bộ vàng có nhãn tay cho **3**.
    """
    from eval.bo_vang import doc_bo_vang, loai_cua_bang_chinh_sach

    cua_bo = {t.content_type for t in doc_bo_vang().tai_lieu}
    assert cua_bo == {"runbook", "bao_cao_su_co", "bi_mat_ha_tang"}
    assert len(loai_cua_bang_chinh_sach()) == 13


def test_moi_hang_policy_mac_dinh_deu_nap_duoc():
    """Tám hằng `POLICY_MAC_DINH` phải trỏ vào một file nạp được, cả tám.

    Hai trong tám (`api/do_chi_phi.py`, `eval/ct03.py`) **không có gì canh**: đổi
    chúng thành một tên file không tồn tại thì cả bộ test vẫn xanh, vì hai module
    ấy chỉ nạp policy trên đường chạy thật (chạm kho, tốn tiền hoặc cần máy chủ).
    Một cái tên nói dối ở đó là một cấu hình đọc nhầm phát hiện được ở đúng lúc
    đang chạy trên máy chủ.

    Import chính module chứ không đọc AST: cái phải đúng là giá trị hằng lúc
    chạy, không phải một chuỗi trong mã nguồn.
    """
    from adapters.policy_loader import load_policy

    import api.do_chi_phi
    import api.man_nap
    import eval.bo_vang
    import eval.cau_hoi
    import eval.chup_do_thi
    import eval.ct03
    import eval.do_trich_xuat
    from tests.fixtures import oracle

    hang = {
        "api.do_chi_phi": api.do_chi_phi.POLICY_MAC_DINH,
        "api.man_nap": api.man_nap.POLICY_MAC_DINH,
        "eval.bo_vang": eval.bo_vang.POLICY_MAC_DINH,
        "eval.cau_hoi": eval.cau_hoi.POLICY_MAC_DINH,
        "eval.chup_do_thi": eval.chup_do_thi.POLICY_MAC_DINH,
        "eval.ct03": eval.ct03.POLICY_MAC_DINH,
        "eval.do_trich_xuat": eval.do_trich_xuat.POLICY_MAC_DINH,
        "tests.fixtures.oracle": oracle.POLICY_DAY_DU,
    }
    assert len(hang) == 8
    for ten, duong_dan in hang.items():
        assert duong_dan.exists(), (ten, duong_dan)
        load_policy(duong_dan)  # không ném
    # Cả tám trỏ vào **cùng** một bảng: bảng vận hành. Tám đường nạp policy mà
    # hai đường đọc hai bảng khác nhau là hai bộ số không so được với nhau.
    assert len(set(hang.values())) == 1, hang


def test_glob_bang_chinh_sach_rong_la_loi_chu_khong_phai_luat_phu_rong(tmp_path):
    """Guard của chính phép quét: glob hỏng cho danh sách rỗng và luật hết nghĩa."""
    from eval.bo_vang import cac_bang_chinh_sach

    with pytest.raises(BoVangKhongHopLe) as loi:
        cac_bang_chinh_sach(tmp_path)
    assert "phép quét" in str(loi.value)


def test_moi_loai_noi_dung_cua_bo_vang_deu_co_hang_do_nhay(bo_vang):
    """Chiều ngược lại: một loại không có hạng là một lô ingest bị từ chối."""
    from adapters.sensitivity_loader import bang_hang_mac_dinh

    cua_bo = {t.content_type for t in bo_vang.tai_lieu}
    assert cua_bo <= set(bang_hang_mac_dinh().hang)


def test_bang_chinh_sach_day_du_khong_lam_bo_vang_do():
    """Khai đủ 13 loại **không** được biến bộ vàng 10 tài liệu thành không hợp lệ.

    Khoản ledger 2.5 mà story 2.8 đóng một nửa và 3.2 đóng nốt. Luật đời đầu đòi
    bộ vàng phủ *mọi* loại của bảng hạng, nên một dòng thêm vào
    `config/hang-do-nhay.yaml` là một lượt gán nhãn 10 tài liệu mới; luật 2.8
    dời cái bẫy sang bảng chính sách, và story 3.2 đúng là story khai đủ 13 loại
    ở đó. Mẫu đối chiếu nay là corpus, nên bộ vàng ba loại vẫn hợp lệ.
    """
    from adapters.sensitivity_loader import bang_hang_mac_dinh
    from eval.bo_vang import doc_bo_vang, loai_cua_bang_chinh_sach

    bo = doc_bo_vang()  # không ném
    cua_bo = {t.content_type for t in bo.tai_lieu}
    assert len(cua_bo) == 3
    assert len(loai_cua_bang_chinh_sach()) == len(bang_hang_mac_dinh().hang) == 13


def test_moi_vai_co_it_nhat_mot_fact_trong_ca_bo(bo_vang):
    dem = bo_vang.dem_theo_vai()
    assert set(dem) == SLOT_ROLE_SET
    thieu = sorted(vai for vai, n in dem.items() if n == 0)
    assert not thieu, f"vai không có fact nào: {thieu}"


def test_moi_vai_co_mat_ca_trong_tam_tai_lieu_cham(bo_vang):
    """Ma trận lẫn lộn của 2.6 chạy trên tài liệu chấm, nên hàng rỗng phải chặn ở đây.

    Loader chỉ đòi phủ 8 vai trên *cả bộ* (I/O Matrix). Nếu một vai chỉ xuất
    hiện ở tài liệu few-shot thì loader vẫn nhận, mà ma trận lẫn lộn vẫn có
    hàng rỗng - nên luật chặt hơn đứng ở đây, cạnh bộ vàng thật.
    """
    dem = bo_vang.dem_theo_vai(chi_cham=True)
    thieu = sorted(vai for vai, n in dem.items() if n == 0)
    assert not thieu, f"vai vắng ở tài liệu chấm: {thieu}"


def test_id_fact_tinh_duoc_va_khong_trung_trong_cung_tai_lieu(bo_vang):
    """`id_fact` là chỗ ghép nhãn vàng với hyperedge pipeline sinh ra (2.6)."""
    for t in bo_vang.tai_lieu:
        ids = [f.id_fact for f in t.facts]
        assert all(i.startswith(facts.TIEN_TO_ID_FACT) for i in ids)
        assert len(set(ids)) == len(ids), f"{t.doc_key}: id fact trùng"


def test_fact_vang_bam_duoc_va_vao_set_duoc(bo_vang):
    """2.6 sẽ đưa fact vàng vào `set`/`dict`; `MappingProxyType` không băm được."""
    moi_fact = [f for t in bo_vang.tai_lieu for f in t.facts]
    assert len({hash(f) for f in moi_fact}) == len({f.id_fact for f in moi_fact})
    assert len(set(moi_fact)) == len(moi_fact)


def test_moi_fact_qua_kiem_fact_ma_gia_tri_khong_doi(bo_vang):
    """Nhãn viết ở dạng đã chuẩn hóa sẵn, nên `kiem_fact` là phép đồng nhất."""
    for t in bo_vang.tai_lieu:
        for f in t.facts:
            slots, ma = facts.kiem_fact(dict(f.slots))
            assert ma is None, f"{t.doc_key}: {ma}"
            assert slots == dict(f.slots)


def test_moi_gia_tri_slot_la_doan_co_that_trong_than(bo_vang):
    """Luật "trích sát câu, không suy diễn": nhãn không được viết lại văn bản."""
    for t in bo_vang.tai_lieu:
        than = chuan_so_sanh(t.than)
        for f in t.facts:
            for vai, gia_tri in f.slots.items():
                assert chuan_so_sanh(gia_tri) in than, f"{t.doc_key} {vai}: {gia_tri!r}"


def test_moi_cau_nguon_co_mat_nguyen_van_trong_than_tai_lieu(bo_vang):
    for t in bo_vang.tai_lieu:
        than = (REPO_ROOT / "eval" / "data" / t.doc_key).read_text(encoding="utf-8")
        _, than = tach_frontmatter(than)
        for f in t.facts:
            assert f.cau_nguon in than, f"{t.doc_key}: {f.cau_nguon!r}"


def test_nhan_quyen_cua_bo_vang_khop_frontmatter(bo_vang):
    for t in bo_vang.tai_lieu:
        meta, _ = tach_frontmatter(
            (REPO_ROOT / "eval" / "data" / t.doc_key).read_text(encoding="utf-8")
        )
        assert (t.scope, t.content_type) == (meta["scope"], meta["content_type"])


# --------------------------------------------------------------------------
# Ca lỗi: bộ vàng nhỏ dựng trong tmp_path
# --------------------------------------------------------------------------

# Bộ tối thiểu hợp lệ: ba loại nội dung, 8 vai phủ đủ. Mỗi ca lỗi bên dưới sửa
# đúng một chỗ của bộ này, nên thông điệp lỗi quy được về chỗ đã sửa.
_THAN = {
    "a-runbook.txt": (
        "runbook",
        [
            "Tai khoan VPN bi khoa 30 phut khi nhap sai 5 lan.",
            "Muon mo khoa som phai goi hotline IT.",
        ],
    ),
    "b-su-co.txt": (
        "bao_cao_su_co",
        [
            "Ngay 12/08/2026 luc 09:20 App01 tra loi 502 do sai cau hinh.",
            "Nguoi phu trach la Tran Thi Hanh.",
        ],
    ),
    "c-ha-tang.txt": (
        "bi_mat_ha_tang",
        [
            "Khoa SSH quan tri luu trong kho khoa Vault.",
            "Dai mang quan tri tach khoi dai mang nguoi dung.",
        ],
    ),
}


def _bo_toi_thieu() -> dict:
    return {
        "version": 1,
        "tai_lieu": [
            {
                "doc_key": "a-runbook.txt",
                "scope": "noi_bo",
                "content_type": "runbook",
                "few_shot": False,
                "facts": [
                    {
                        "slots": {
                            "subject": "Tai khoan VPN",
                            "condition": "nhap sai 5 lan",
                            "remediation": "goi hotline IT",
                        },
                        "cau_nguon": _THAN["a-runbook.txt"][1][0],
                    }
                ],
            },
            {
                "doc_key": "b-su-co.txt",
                "scope": "noi_bo",
                "content_type": "bao_cao_su_co",
                "few_shot": True,
                "facts": [
                    {
                        "slots": {
                            "subject": "App01",
                            "symptom": "tra loi 502",
                            "cause": "sai cau hinh",
                            "time": "12/08/2026 luc 09:20",
                            "owner": "Tran Thi Hanh",
                        },
                        "cau_nguon": _THAN["b-su-co.txt"][1][0],
                    }
                ],
            },
            {
                "doc_key": "c-ha-tang.txt",
                "scope": "noi_bo",
                "content_type": "bi_mat_ha_tang",
                "few_shot": False,
                "facts": [
                    {
                        "slots": {"subject": "Khoa SSH quan tri", "source": "kho khoa Vault"},
                        "cau_nguon": _THAN["c-ha-tang.txt"][1][0],
                    }
                ],
            },
        ],
    }


@pytest.fixture()
def kho(tmp_path):
    """Thư mục `data` cùng đường dẫn JSON cho một bộ vàng nhỏ trong `tmp_path`."""
    data = tmp_path / "data"
    data.mkdir()
    for ten, (content_type, dong) in _THAN.items():
        (data / ten).write_text(
            f"---\nscope: noi_bo\ncontent_type: {content_type}\n---\n" + "\n".join(dong) + "\n",
            encoding="utf-8",
        )
    return data, tmp_path / "bo_vang.json"


def _nap(kho, bo):
    data, duong_dan = kho
    duong_dan.write_text(json.dumps(bo, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc_bo_vang(duong_dan=duong_dan, thu_muc_data=data)


def test_bo_toi_thieu_hop_le_nap_duoc(kho):
    """Cột mốc của các ca lỗi: bộ chưa sửa gì phải nạp được."""
    bo = _nap(kho, _bo_toi_thieu())
    assert len(bo.tai_lieu) == 3
    assert bo.mau_so_slot() == 3 + 2  # hai tài liệu chấm; b-su-co là few-shot
    assert len(bo.tai_lieu_few_shot()) == 1


# --- lược đồ cấp gốc -------------------------------------------------------


def test_goc_khong_phai_object_bi_tu_choi(kho):
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, [{"doc_key": "a-runbook.txt"}])
    assert "gốc file phải là một object" in str(loi.value)


def test_version_sai_bi_tu_choi_kem_gia_tri(kho):
    bo = _bo_toi_thieu()
    bo["version"] = 2
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "version" in str(loi.value) and "2" in str(loi.value)


def test_khoa_la_o_cap_goc_bi_tu_choi_kem_ten_khoa(kho):
    bo = _bo_toi_thieu()
    bo["ghi_chu"] = "x"
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "ghi_chu" in str(loi.value)


def test_danh_sach_tai_lieu_rong_bi_tu_choi(kho):
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, {"version": 1, "tai_lieu": []})
    assert "tai_lieu" in str(loi.value)


# --- lược đồ cấp tài liệu --------------------------------------------------


def test_khoa_thieu_o_cap_tai_lieu_bi_tu_choi_kem_ten_khoa(kho):
    bo = _bo_toi_thieu()
    del bo["tai_lieu"][0]["few_shot"]
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "few_shot" in str(loi.value) and "a-runbook.txt" in str(loi.value)


def test_khoa_la_o_cap_tai_lieu_bi_tu_choi_va_khong_sinh_loi_gia(kho):
    """Một mục hỏng chỉ sinh một lỗi: nó vẫn tính là *đã khai* `doc_key` đó."""
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["fewshot"] = True
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "fewshot" in str(loi.value)
    assert not [d for d in loi.value.loi if "chưa có mục vàng" in d]


def test_doc_key_khong_phai_chuoi_bao_dung_ly_do_sai_kieu(kho):
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["doc_key"] = 7
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "phải là chuỗi không rỗng" in str(loi.value)
    assert "không có file" not in str(loi.value)


def test_few_shot_khong_phai_bool_bi_tu_choi(kho):
    """`"false"` là chuỗi truthy: không kiểm kiểu thì tài liệu lặng lẽ rời mẫu số."""
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["few_shot"] = "false"
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "few_shot" in str(loi.value) and "'false'" in str(loi.value)


def test_doc_key_khai_hai_lan_bi_tu_choi(kho):
    """Khai hai lần mà không chặn là cộng đôi mẫu số của đúng một tài liệu."""
    bo = _bo_toi_thieu()
    bo["tai_lieu"].append(json.loads(json.dumps(bo["tai_lieu"][0])))
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "khai hai lần" in str(loi.value) and "a-runbook.txt" in str(loi.value)


def test_facts_rong_bi_tu_choi(kho):
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"] = []
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "`facts`" in str(loi.value) and "a-runbook.txt" in str(loi.value)


def test_fact_mang_khoa_thu_ba_bi_tu_choi(kho):
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"][0]["ghi_chu"] = "x"
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "đúng hai khóa" in str(loi.value)


# --- lược đồ cấp fact ------------------------------------------------------


@pytest.mark.parametrize(
    "slots, ma",
    [
        ({"subject": "Tai khoan VPN", "root_cause": "y"}, facts.MA_VAI_LA),
        ({"cause": "nhap sai 5 lan", "time": "z"}, facts.MA_THIEU_SUBJECT),
        ({"subject": "Tai khoan VPN"}, facts.MA_IT_HON_HAI_VAI),
        ({"subject": "Tai khoan VPN", "cause": ["y"]}, facts.MA_GIA_TRI_SAI_KIEU),
        ({"subject": "Tai khoan VPN", "cause": ""}, facts.MA_GIA_TRI_RONG),
        ({"subject": "Tai khoan VPN", "cause": "y" * 400}, facts.MA_GIA_TRI_QUA_DAI),
    ],
    ids=["vai_la", "thieu_subject", "mot_vai", "sai_kieu", "rong", "qua_dai"],
)
def test_fact_sai_luoc_do_tu_choi_ca_file_kem_ma_cua_core_facts(kho, slots, ma):
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"][0]["slots"] = slots
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert ma in str(loi.value)
    assert "a-runbook.txt" in str(loi.value)


def test_gia_tri_chua_chuan_hoa_bi_tu_choi_kem_hai_gia_tri(kho):
    """Nhãn phải viết ở dạng đã chuẩn hóa, nếu không `id_fact` của nhãn lệch id pipeline."""
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"][0]["slots"]["subject"] = "  Tai  khoan VPN  "
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "'  Tai  khoan VPN  '" in str(loi.value) and "'Tai khoan VPN'" in str(loi.value)


def test_gia_tri_viet_lai_khong_co_trong_than_bi_tu_choi(kho):
    """Luật trích sát câu: viết lại một cụm cho gọn hơn là loại, kèm vai và giá trị."""
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"][0]["slots"]["remediation"] = "goi tong dai IT"
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "remediation='goi tong dai IT'" in str(loi.value)
    assert "a-runbook.txt fact#0" in str(loi.value)


def test_gia_tri_khac_hoa_thuong_va_khac_khoang_trang_van_hop_le(kho):
    """Nhãn lấy cụm đứng đầu câu ("Tai khoan" -> "tai khoan") là hợp lệ."""
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"][0]["slots"]["subject"] = "tai khoan VPN"
    assert _nap(kho, bo).tai_lieu[0].facts[0].slots["subject"] == "tai khoan VPN"


def test_cau_nguon_khong_co_trong_than_bi_tu_choi(kho):
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"][0]["cau_nguon"] = "Tai khoan VPN bi khoa 31 phut khi nhap sai 5 lan."
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "a-runbook.txt" in str(loi.value) and "31 phut" in str(loi.value)


def test_hai_fact_trung_id_trong_mot_tai_lieu_bi_tu_choi_kem_id(kho):
    bo = _bo_toi_thieu()
    fact = bo["tai_lieu"][0]["facts"][0]
    # Cùng giá trị, khác thứ tự khóa: `id_fact` băm theo thứ tự `SLOT_ROLES`
    # nên hai bản ghi này là một node hyperedge.
    bo["tai_lieu"][0]["facts"].append(
        {"slots": dict(reversed(list(fact["slots"].items()))), "cau_nguon": fact["cau_nguon"]}
    )
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert facts.id_fact(fact["slots"]) in str(loi.value)


# --- khớp với thư mục dữ liệu và luật cả bộ --------------------------------


def test_file_chua_gan_nhan_bi_tu_choi_kem_ten(kho):
    data, _ = kho
    (data / "d-them.txt").write_text(
        "---\nscope: noi_bo\ncontent_type: runbook\n---\nMot cau.\n", encoding="utf-8"
    )
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, _bo_toi_thieu())
    assert "d-them.txt" in str(loi.value)


def test_file_sai_duoi_duoc_bo_qua_im_lang(kho):
    """`.gitkeep`/`.DS_Store`/file backup không phải tài liệu, không ai gán nhãn cho chúng."""
    data, _ = kho
    (data / ".gitkeep").write_text("", encoding="utf-8")
    (data / "a-runbook.txt~").write_text("rac cua trinh soan thao", encoding="utf-8")
    assert len(_nap(kho, _bo_toi_thieu()).tai_lieu) == 3


def test_file_hong_khac_sai_duoi_van_la_loi(kho):
    """File *có ý* là tài liệu nhưng hỏng thì không được im lặng thu hẹp mẫu số."""
    data, _ = kho
    (data / "e-thieu-metadata.txt").write_text("Khong co frontmatter.\n", encoding="utf-8")
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, _bo_toi_thieu())
    assert "e-thieu-metadata.txt" in str(loi.value) and "THIEU_METADATA" in str(loi.value)


def test_doc_key_thua_khong_co_file_bi_tu_choi_kem_ten(kho):
    bo = _bo_toi_thieu()
    bo["tai_lieu"].append(
        {
            "doc_key": "z-khong-co.txt",
            "scope": "noi_bo",
            "content_type": "runbook",
            "few_shot": False,
            "facts": [{"slots": {"subject": "x", "cause": "y"}, "cau_nguon": "Mot cau."}],
        }
    )
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "z-khong-co.txt" in str(loi.value)


def test_nhan_quyen_lech_frontmatter_bi_tu_choi_kem_hai_gia_tri(kho):
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["content_type"] = "bao_cao_su_co"
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "bao_cao_su_co" in str(loi.value) and "runbook" in str(loi.value)


def test_qua_hai_tai_lieu_few_shot_bi_tu_choi(kho):
    """Luật PRD 2.6: few-shot lấy từ tối đa 2 tài liệu, để mẫu số còn đủ lớn."""
    bo = _bo_toi_thieu()
    for t in bo["tai_lieu"]:
        t["few_shot"] = True
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert f"3 tài liệu khai `few_shot`, tối đa {TOI_DA_FEW_SHOT}" in str(loi.value)


def test_khong_con_tai_lieu_cham_bi_tu_choi(kho):
    """Mẫu số 0 làm mọi phép chia của 2.6 vô nghĩa, chặn ngay ở cửa nạp."""
    bo = _bo_toi_thieu()
    bo["tai_lieu"] = bo["tai_lieu"][:2]
    for t in bo["tai_lieu"]:
        t["few_shot"] = True
    data, _ = kho
    (data / "c-ha-tang.txt").unlink()
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "mẫu số bằng 0" in str(loi.value)


def test_vai_vang_mat_ca_bo_bi_tu_choi_kem_ten_vai(kho):
    bo = _bo_toi_thieu()
    del bo["tai_lieu"][1]["facts"][0]["slots"]["symptom"]
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "symptom" in str(loi.value)


def test_loai_noi_dung_thieu_bi_tu_choi_kem_ten_loai(kho, monkeypatch):
    """Loại nội dung mà **cả corpus lẫn bộ vàng** đều không có: từ chối kèm tên.

    Corpus thật phủ 13/13 nên ca này phải dựng: corpus giả thiếu
    `bi_mat_ha_tang`, và bộ vàng cũng bỏ tài liệu loại đó. Bảng chính sách vẫn
    là bảng thật, nên cái đang được kiểm là đúng phép trừ của luật phủ.
    """
    monkeypatch.setattr(
        "eval.bo_vang.loai_cua_corpus", lambda *a, **k: {"runbook", "bao_cao_su_co"}
    )
    data, _ = kho
    (data / "c-ha-tang.txt").unlink()
    bo = _bo_toi_thieu()
    bo["tai_lieu"] = [t for t in bo["tai_lieu"] if t["doc_key"] != "c-ha-tang.txt"]
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "bi_mat_ha_tang" in str(loi.value)


def test_loai_chi_co_trong_corpus_van_du_de_luat_phu_xanh(kho, monkeypatch):
    """Đối chứng: một loại chỉ có ở corpus vẫn là một ca có trên dữ liệu thật.

    Đây chính là điều làm cho bảng đầy đủ của 3.2 không kéo theo một lượt gán
    nhãn tay: `bi_mat_ha_tang` biến khỏi bộ vàng mà luật vẫn xanh vì corpus có.
    """
    monkeypatch.setattr(
        "eval.bo_vang.loai_cua_corpus",
        lambda *a, **k: set(loai_cua_bang_chinh_sach()),
    )
    data, _ = kho
    (data / "c-ha-tang.txt").unlink()
    bo = _bo_toi_thieu()
    bo["tai_lieu"] = [t for t in bo["tai_lieu"] if t["doc_key"] != "c-ha-tang.txt"]
    for t in bo["tai_lieu"]:
        t["few_shot"] = False
    # Bộ nhỏ này vẫn hỏng vì một lý do khác (tài liệu bỏ đi giữ fact `source`
    # duy nhất), nên assert đúng thứ đang được đo: **không** còn lỗi phủ loại.
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert "bi_mat_ha_tang" not in str(loi.value)
    assert "bảng chính sách" not in str(loi.value)


def test_gom_moi_loi_roi_nem_mot_lan(kho):
    """Người sửa bộ vàng phải thấy hết lỗi trong một lượt, không sửa từng cái một.

    Hai lỗi ở hai cấp khác nhau (một fact sai lược đồ, một `doc_key` không có
    file) và *đúng* hai lỗi: cố ý không làm hỏng fact nào đang giữ vai duy
    nhất, để con số 2 là con số của phép gom chứ không phải của hiệu ứng dây
    chuyền sang luật phủ vai.
    """
    bo = _bo_toi_thieu()
    bo["tai_lieu"][0]["facts"].append(
        {
            "slots": {"subject": "Tai khoan VPN", "root_cause": "y"},
            "cau_nguon": _THAN["a-runbook.txt"][1][0],
        }
    )
    bo["tai_lieu"].append(
        {
            "doc_key": "z-khong-co.txt",
            "scope": "noi_bo",
            "content_type": "runbook",
            "few_shot": False,
            "facts": [{"slots": {"subject": "x", "cause": "y"}, "cau_nguon": "Mot cau."}],
        }
    )
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    assert len(loi.value.loi) == 2
    assert loi.value.code == "BO_VANG_KHONG_HOP_LE"
    assert "a-runbook.txt fact#1" in loi.value.loi[0] and facts.MA_VAI_LA in loi.value.loi[0]
    assert "z-khong-co.txt" in loi.value.loi[1]


def test_json_hong_file_thieu_va_khong_phai_utf8_deu_la_mot_loai_loi(kho, tmp_path):
    data, duong_dan = kho
    duong_dan.write_text("{khong phai json", encoding="utf-8")
    with pytest.raises(BoVangKhongHopLe) as loi:
        doc_bo_vang(duong_dan=duong_dan, thu_muc_data=data)
    assert loi.value.code == "BO_VANG_KHONG_HOP_LE"
    with pytest.raises(BoVangKhongHopLe):
        doc_bo_vang(duong_dan=tmp_path / "khong-co.json", thu_muc_data=data)
    duong_dan.write_bytes(b"\xff\xfe{}")
    with pytest.raises(BoVangKhongHopLe) as loi:
        doc_bo_vang(duong_dan=duong_dan, thu_muc_data=data)
    assert "UTF-8" in str(loi.value)


def test_thu_muc_du_lieu_khong_ton_tai_la_loi_cua_bo_vang(kho, tmp_path):
    _, duong_dan = kho
    duong_dan.write_text(json.dumps(_bo_toi_thieu()), encoding="utf-8")
    with pytest.raises(BoVangKhongHopLe):
        doc_bo_vang(duong_dan=duong_dan, thu_muc_data=tmp_path / "khong-co")


# --------------------------------------------------------------------------
# Trang soát nhãn
# --------------------------------------------------------------------------


def test_trang_soat_nhan_co_bang_fact_cua_tung_tai_lieu(tmp_path):
    """Ghim riêng nửa "bảng fact": số hàng và id fact chỉ có ở bảng, không chỗ nào khác."""
    from eval.xem_bo_vang import main

    dich = tmp_path / "bo_vang.html"
    assert main(dich=dich) == 0
    html = dich.read_text(encoding="utf-8")
    bo = doc_bo_vang()
    for t in bo.tai_lieu:
        assert html.count(f"<td>{t.facts[0].so_slot}</td></tr>") >= 1
        for f in t.facts:
            assert f"<code>{f.id_fact}</code>" in html
    # Đúng một hàng cho mỗi fact của mọi tài liệu.
    assert sum(html.count(f"<code>{f.id_fact}</code>") for t in bo.tai_lieu for f in t.facts) == (
        bo.so_fact()
    )


def test_trang_soat_nhan_co_than_tai_lieu_day_du_va_to_sang_gia_tri_slot(tmp_path):
    """Ghim riêng nửa "thân tài liệu": gỡ dấu tô sáng ra phải được đúng thân gốc.

    Không kiểm bằng "một câu có mặt đâu đó trong trang": cột câu nguồn của bảng
    fact đỡ được phép kiểm đó, nên bỏ hẳn khối thân đi test vẫn xanh. Ở đây lấy
    đúng khối `<pre class="than">` của từng tài liệu, gỡ thẻ `<mark>` và giải mã
    thực thể HTML, rồi so bằng với thân tài liệu.
    """
    import html as _html

    from eval.xem_bo_vang import main

    dich = tmp_path / "bo_vang.html"
    assert main(dich=dich) == 0
    trang = dich.read_text(encoding="utf-8")
    bo = doc_bo_vang()
    khoi = re.findall(r'<pre class="than">(.*?)</pre>', trang, flags=re.DOTALL)
    assert len(khoi) == len(bo.tai_lieu)
    for t, k in zip(bo.tai_lieu, khoi):
        assert _html.unescape(re.sub(r"</?mark[^>]*>", "", k)) == t.than.strip()
        # Mọi giá trị slot phải được tô sáng ở đâu đó trong chính khối đó, và
        # tên vai phải nằm trong `title` của một dấu tô sáng nào đó.
        da_to = chuan_so_sanh(
            " ".join(
                _html.unescape(x) for x in re.findall(r"<mark[^>]*>(.*?)</mark>", k, re.DOTALL)
            )
        )
        vai_trong_title = {
            v
            for tieu_de in re.findall(r'<mark title="([^"]*)"', k)
            for v in _html.unescape(tieu_de).split(", ")
        }
        for f in t.facts:
            for vai, gia_tri in f.slots.items():
                assert vai in vai_trong_title, f"{t.doc_key}: {vai} không có dấu tô sáng nào"
                assert (
                    chuan_so_sanh(gia_tri) in da_to
                ), f"{t.doc_key} {vai}: {gia_tri!r} không được tô sáng"


def test_trang_soat_nhan_in_mau_so_va_du_tam_vai(tmp_path, capsys):
    from eval.xem_bo_vang import main

    dich = tmp_path / "bo_vang.html"
    assert main(dich=dich) == 0
    html = dich.read_text(encoding="utf-8")
    bo = doc_bo_vang()
    for vai in SLOT_ROLES:
        assert f"<code>{vai}</code>" in html
    assert f"<td><b>{bo.mau_so_slot()}</b></td>" in html
    assert "few-shot" in html
    # Mục fact trùng giữa hai tài liệu: hiện không có ca nào, trang phải nói ra
    # điều đó chứ không bỏ trống (ca đầu tiên xuất hiện ở 2.8 phải thấy được).
    assert "Fact trùng giữa hai tài liệu" in html
    assert "Không có" in html
    assert str(bo.mau_so_slot()) in capsys.readouterr().out


def test_trang_soat_nhan_bo_vang_hong_thi_in_ly_do_va_thoat_ma_1(tmp_path, monkeypatch, capsys):
    from eval import xem_bo_vang

    def hong(*a, **k):
        raise BoVangKhongHopLe(["a.txt: vai lạ VAI_LA"])

    monkeypatch.setattr(xem_bo_vang, "doc_bo_vang", hong)
    assert xem_bo_vang.main(dich=tmp_path / "x.html") == 1
    assert "VAI_LA" in capsys.readouterr().err
    assert not (tmp_path / "x.html").exists()


def test_trang_soat_nhan_khong_ghi_duoc_file_thi_tra_1_khong_ne_traceback(tmp_path, capsys):
    from eval.xem_bo_vang import main

    chan = tmp_path / "chan"
    chan.write_text("khong phai thu muc", encoding="utf-8")
    assert main(dich=chan / "sau" / "bo_vang.html") == 1
    assert "không ghi được" in capsys.readouterr().err


def test_chay_bang_python_m_eval_xem_bo_vang(tmp_path):
    """`python -m eval.xem_bo_vang` chạy được từ gốc repo (cần `eval/__init__.py`).

    Ghi vào `tmp_path` chứ không vào `eval/expr/bo_vang.html` thật: một bộ test
    không được sửa file của repo mỗi lần chạy.
    """
    dich = tmp_path / "bo_vang.html"
    kq = subprocess.run(
        [sys.executable, "-m", "eval.xem_bo_vang", str(dich)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert kq.returncode == 0, kq.stderr
    assert dich.exists()


# --------------------------------------------------------------------------
# Smoke upstream vẫn tái tạo được bằng chứng story 1.1
# --------------------------------------------------------------------------


def test_smoke_upstream_ghim_dung_bon_tai_lieu_cua_bang_chung_1_1():
    """`eval/data/` nay 10 file; smoke 1.1 phải nạp đúng tập cũ, không cắt theo thứ tự.

    Cắt `[:5]` theo thứ tự tên là một cái bẫy: thêm một file `00-*.txt` đẩy
    `01-cap-quyen-gitlab.txt` - tài liệu duy nhất trả lời được `QUESTION` - ra
    khỏi tập nạp, mà guard "3-5 tài liệu" vẫn qua và smoke vẫn xanh trên một
    câu trả lời sai.
    """
    from eval.smoke_upstream import DATA_DIR, chon_tai_lieu

    chon = chon_tai_lieu(DATA_DIR)
    assert 3 <= len(chon) <= 5
    assert Path("01-cap-quyen-gitlab.txt").name in {p.name for p in chon}
    assert all(p.exists() for p in chon), "file ghim theo tên phải còn trong eval/data/"
    assert "05-bao-cao-su-co-inc-1208.txt" not in {p.name for p in chon}


# --------------------------------------------------------------------------
# Fact trùng giữa hai tài liệu: báo ra, không từ chối
# --------------------------------------------------------------------------


def test_bo_vang_that_khong_co_id_fact_trung_cheo_tai_lieu(bo_vang):
    """Trên 10 tài liệu hiện tại, mỗi fact vàng chỉ thuộc một tài liệu.

    Ghim làm đặc tả hiện trạng: mẫu số đang không đếm đôi slot nào. Ca trùng là
    hợp lệ về dữ liệu (hai tài liệu nói cùng một quy định) nên loader không cấm,
    nhưng nó đổi phép chấm - pipeline ra *một* node hyperedge còn mẫu số đếm
    hai - nên phải thấy được ngay khi corpus lớn lên ở 2.8.
    """
    assert bo_vang.id_fact_trung_cheo_tai_lieu() == {}


def test_hai_tai_lieu_cung_mot_fact_duoc_bao_ra_chu_khong_bi_tu_choi(kho):
    """Hai tài liệu gán cùng một tập slot: bộ vẫn nạp được, và trùng được liệt kê.

    Không từ chối vì hai tài liệu nói cùng một quy định là dữ liệu hợp lệ; luật
    đếm (một lần hay theo tài liệu) chốt cùng luật ghép ở 2.6/2.8. Điều phải
    giữ là nó không im lặng: mẫu số đếm hai lần trong khi pipeline chỉ ra một
    node hyperedge.
    """
    data, _ = kho
    (data / "d-them.txt").write_text(
        "---\nscope: noi_bo\ncontent_type: runbook\n---\n"
        + "\n".join(_THAN["a-runbook.txt"][1])
        + "\n",
        encoding="utf-8",
    )
    bo = _bo_toi_thieu()
    trung = dict(bo["tai_lieu"][0])  # chính fact của a-runbook.txt
    trung["doc_key"] = "d-them.txt"
    bo["tai_lieu"].append(trung)

    kq = _nap(kho, bo)

    id_trung = kq.id_fact_trung_cheo_tai_lieu()
    assert list(id_trung) == [facts.id_fact(bo["tai_lieu"][0]["facts"][0]["slots"])]
    assert set(next(iter(id_trung.values()))) == {"a-runbook.txt", "d-them.txt"}
    # Đặc tả hiện trạng: mẫu số cộng cả hai lần (3 + 2 của bộ tối thiểu, cộng 3).
    assert kq.mau_so_slot() == 3 + 2 + 3


# --- Vòng review 2.8: nhánh "loại không có hạng" phải bắt được đột biến ----


def test_loai_noi_dung_khong_co_hang_do_nhay_bi_tu_choi_kem_ten_loai(kho):
    """Xóa nhánh này khỏi `_kiem_loai_noi_dung` mà cả bộ vẫn xanh là một lỗ.

    Bộ vàng thật phủ đúng ba loại đều có hạng, nên nhánh đó chưa từng chạy. Ca
    dựng tay ở đây làm nó chạy: một tài liệu mang `content_type` không có trong
    `config/hang-do-nhay.yaml` là một lô ingest bị `SensitivityRankUnknown` từ
    chối trọn vẹn, nên nó phải đỏ ở cửa nạp bộ vàng chứ không đỏ sau khi trả tiền.
    """
    from adapters.sensitivity_loader import bang_hang_mac_dinh

    la = "loai_khong_co_hang"
    assert la not in bang_hang_mac_dinh().hang

    data, duong_dan = kho
    (data / "d-la.txt").write_text(
        f"---\nscope: noi_bo\ncontent_type: {la}\n---\nMay chu App09 chay dich vu bao cao.\n",
        encoding="utf-8",
    )
    bo = _bo_toi_thieu()
    bo["tai_lieu"].append(
        {
            "doc_key": "d-la.txt",
            "scope": "noi_bo",
            "content_type": la,
            "few_shot": False,
            "facts": [
                {
                    "slots": {"subject": "App09", "remediation": "chay dich vu bao cao"},
                    "cau_nguon": "May chu App09 chay dich vu bao cao.",
                }
            ],
        }
    )
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    thong_diep = str(loi.value)
    assert la in thong_diep
    assert "hạng độ nhạy" in thong_diep and "SensitivityRankUnknown" in thong_diep


def test_bang_hang_hong_van_bao_ca_loi_phu_theo_bang_chinh_sach(kho, monkeypatch):
    """`except SensitivityRanksInvalid` trước đây `return` trần, nuốt luôn phép kiểm kia.

    Gom hết lỗi rồi ném một lần là luật của cả module: người sửa nhãn phải thấy
    toàn bộ danh sách trong một lượt chạy.
    """
    from adapters.sensitivity_loader import SensitivityRanksInvalid

    def hong():
        raise SensitivityRanksInvalid("bảng hạng hỏng cố ý")

    monkeypatch.setattr("eval.bo_vang.bang_hang_mac_dinh", hong)
    monkeypatch.setattr(
        "eval.bo_vang.loai_cua_corpus", lambda *a, **k: {"runbook", "bao_cao_su_co"}
    )
    bo = _bo_toi_thieu()
    # Bỏ tài liệu `bi_mat_ha_tang` để phép phủ theo bảng chính sách cũng hỏng.
    bo["tai_lieu"] = [t for t in bo["tai_lieu"] if t["content_type"] != "bi_mat_ha_tang"]
    for t in bo["tai_lieu"]:
        t["few_shot"] = False
    with pytest.raises(BoVangKhongHopLe) as loi:
        _nap(kho, bo)
    thong_diep = str(loi.value)
    assert "bảng hạng hỏng cố ý" in thong_diep
    assert "bảng chính sách" in thong_diep, "lỗi thứ hai bị nuốt mất"
