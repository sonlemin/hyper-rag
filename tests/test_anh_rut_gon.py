"""Ảnh chụp rút gọn: giữ ba tỷ lệ, bỏ mọi giá trị (story 2.11).

Đây là chỗ đứng để `tests/test_ty_le_n_ngoi.py` khóa được ba tỷ lệ của space
`real` bằng cách **tính lại**, thay vì ba hằng chép tay mà không nguồn nào trong
repo kiểm được. Nên tính chất phải chấm là hai vế cùng lúc:

- **Đủ để đếm.** Ba tỷ lệ trên bản rút gọn bằng đúng ba tỷ lệ trên bản đầy đủ.
  Không bằng thì bản rút gọn vô dụng, dù nó kín tới đâu.
- **Không đủ để dựng lại.** Không giá trị slot, không tên tài liệu nào còn
  trong file; và băm có muối nên một danh sách ứng viên không dò ngược được.

Cộng rào ghi file **hai chiều**: dạng đầy đủ của space dữ liệu thật không vào
được cây repo, dạng rút gọn thì vào được.

Không chạm kho: mọi ca chạy trên dict ảnh chụp dựng tay hoặc trên ảnh chụp đã
commit của `synth`.
"""

import json
from pathlib import Path

import pytest

from adapters.sensitivity_loader import DUONG_DAN_MAC_DINH as HANG_MAC_DINH
from adapters.sensitivity_loader import tai_hang_do_nhay
from eval.anh_rut_gon import (
    DO_DAI_MUOI_TOI_THIEU,
    HAU_TO_RUT_GON,
    TIEN_TO_DOC,
    TIEN_TO_ENTITY,
    TIEN_TO_HYPEREDGE,
    BamTrung,
    MuoiKhongHopLe,
    bam,
    doc_muoi,
    la_space_rut_gon,
    rut_gon_anh,
    space_goc,
)
from eval.cau_hoi import doc_anh_do_thi
from eval.chup_do_thi import ly_do_tu_choi_dich, ten_file_mac_dinh
from eval.ty_le_n_ngoi import ba_ty_le

GOC_REPO = Path(__file__).resolve().parent.parent
ANH_SYNTH = GOC_REPO / "eval" / "anh_do_thi" / "synth.json"

MUOI = "muoi-thu-nghiem-dai-du-32-ky-tu-0123456789"


@pytest.fixture(scope="module")
def hang() -> dict[str, int]:
    return dict(tai_hang_do_nhay(HANG_MAC_DINH).hang)


@pytest.fixture(scope="module")
def anh_day_du() -> dict:
    """Ảnh chụp `synth` đã commit, đọc thô. Dùng nó chứ không dựng tay: phép so
    "ba tỷ lệ bằng nhau" chỉ có nghĩa trên một đồ thị đủ rối."""
    return json.loads(ANH_SYNTH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def anh_rut(anh_day_du) -> dict:
    return rut_gon_anh(anh_day_du, MUOI)


# ---------------------------------------------------------------------------
# Đủ để đếm
# ---------------------------------------------------------------------------


def test_ba_ty_le_bang_nhau_tren_hai_dang(anh_day_du, anh_rut, hang, tmp_path):
    """Tính chất chính: bản rút gọn cho **đúng** ba con số của bản đầy đủ.

    Cả ba số chẩn đoán của Composition-Risk cũng phải bằng: chúng đếm trên quan
    hệ bằng nhau giữa các entity, đúng thứ băm một-một giữ lại.
    """
    a = tmp_path / "day-du.json"
    b = tmp_path / "rut-gon.json"
    a.write_text(json.dumps(anh_day_du, ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(anh_rut, ensure_ascii=False), encoding="utf-8")

    day_du = ba_ty_le(doc_anh_do_thi(a), hang)
    rut = ba_ty_le(doc_anh_do_thi(b), hang)

    assert rut.bo_ba() == day_du.bo_ba()
    assert rut.so_hyperedge == day_du.so_hyperedge
    assert rut.so_tai_lieu == day_du.so_tai_lieu
    assert rut.phan_bo_hang == day_du.phan_bo_hang
    assert rut.phan_bo_loai == day_du.phan_bo_loai
    assert rut.so_nhay_cam_lo_mot_phan == day_du.so_nhay_cam_lo_mot_phan
    assert rut.so_nhay_cam_co_entity_lo == day_du.so_nhay_cam_co_entity_lo
    assert rut.trung_binh_phan_entity_lo == day_du.trung_binh_phan_entity_lo


def test_loader_nhan_ban_rut_gon_khong_sua_mot_dong(anh_rut, tmp_path):
    """`doc_anh_do_thi` dùng lại được: lược đồ đóng, không thêm khóa nào."""
    f = tmp_path / "rut-gon.json"
    f.write_text(json.dumps(anh_rut, ensure_ascii=False), encoding="utf-8")
    anh = doc_anh_do_thi(f)
    assert anh.space.endswith(HAU_TO_RUT_GON)
    assert anh.so_hyperedge == anh_rut["so_hyperedge"]


def test_giu_nguyen_khoa_nhan_quyen_va_so_dem(anh_day_du, anh_rut):
    """Giữ `khoa`, `scope`, `content_type`, `sha256`, `version` và ba số đếm."""
    assert anh_rut["version"] == anh_day_du["version"]
    assert anh_rut["ngay_do"] == anh_day_du["ngay_do"]
    assert anh_rut["policy_version"] == anh_day_du["policy_version"]
    for k in ("so_tai_lieu", "so_hyperedge", "so_hyperedge_da_nguon"):
        assert anh_rut[k] == anh_day_du[k]
    assert sorted(h["khoa"] or "" for h in anh_rut["hyperedge"]) == sorted(
        h["khoa"] or "" for h in anh_day_du["hyperedge"]
    )
    for truong in ("sha256", "scope", "content_type"):
        assert sorted(m[truong] for m in anh_rut["tai_lieu"]) == sorted(
            m[truong] for m in anh_day_du["tai_lieu"]
        )


def test_giu_nguyen_so_vai_va_so_gia_tri_moi_vai(anh_day_du, anh_rut):
    """Tỷ lệ 1 đếm số vai được điền, nên cấu trúc `slots` phải bất động."""
    hinh_dang = lambda anh: sorted(
        tuple(sorted((vai, len(gt)) for vai, gt in h["slots"].items()))
        for h in anh["hyperedge"]
    )
    assert hinh_dang(anh_rut) == hinh_dang(anh_day_du)


def test_quan_he_trung_nhau_giua_cac_id_duoc_giu(anh_day_du, anh_rut):
    """Cùng một entity ra cùng một băm, và hai entity khác nhau không gộp.

    Đây là tính chất mà tỷ lệ 3 đứng lên: "mọi entity của ca nhạy cảm còn xuất
    hiện ở một hyperedge không nhạy cảm" là một phép hỏi về quan hệ bằng nhau,
    không về giá trị.
    """
    def cap(anh):
        ra = set()
        for h in anh["hyperedge"]:
            for gt in h["slots"].values():
                ra |= set(gt)
        return ra

    goc, rut = cap(anh_day_du), cap(anh_rut)
    assert len(goc) == len(rut), "số entity phân biệt phải bằng nhau"

    # Và quan hệ "hai hyperedge dùng chung một entity" giữ nguyên từng cặp.
    def do_thi(anh):
        return sorted(
            tuple(sorted(set(e for gt in h["slots"].values() for e in gt)))
            for h in anh["hyperedge"]
        )

    anh_map = {}
    for hg, hr in zip(
        sorted(anh_day_du["hyperedge"], key=lambda h: h["id"]),
        sorted(anh_rut["hyperedge"], key=lambda h: h["id"]),
    ):
        anh_map[hg["id"]] = hr["id"]
    assert len(set(anh_map.values())) == len(anh_map)
    assert len(do_thi(anh_rut)) == len(do_thi(anh_day_du))


# ---------------------------------------------------------------------------
# Không đủ để dựng lại
# ---------------------------------------------------------------------------


def test_khong_gia_tri_slot_hay_ten_tai_lieu_nao_con_lai(anh_day_du, anh_rut):
    """Quét nguyên văn file: không một giá trị nào của bản đầy đủ còn trong bản rút gọn."""
    van_ban = json.dumps(anh_rut, ensure_ascii=False)
    con_lai = []
    for m in anh_day_du["tai_lieu"]:
        if m["doc_key"] in van_ban:
            con_lai.append(m["doc_key"])
    for h in anh_day_du["hyperedge"]:
        if h["id"] in van_ban:
            con_lai.append(h["id"])
        for gt in h["slots"].values():
            con_lai += [e for e in gt if e in van_ban]
    assert not con_lai, sorted(set(con_lai))[:10]


def test_moi_id_mang_tien_to_tu_khai(anh_rut):
    """Một giá trị lẻ chép ra khỏi file vẫn tự khai nó là băm của bản rút gọn."""
    for m in anh_rut["tai_lieu"]:
        assert m["doc_key"].startswith(TIEN_TO_DOC)
    for h in anh_rut["hyperedge"]:
        assert h["id"].startswith(TIEN_TO_HYPEREDGE)
        assert all(d.startswith(TIEN_TO_DOC) for d in h["doc_key"])
        for gt in h["slots"].values():
            assert all(e.startswith(TIEN_TO_ENTITY) for e in gt)


def test_space_tu_khai_la_ban_rut_gon(anh_day_du, anh_rut):
    """`space` mang hậu tố, nên `BaTyLe.space` và tiêu đề cột đều nói ra điều đó."""
    assert anh_rut["space"] == anh_day_du["space"] + HAU_TO_RUT_GON
    assert la_space_rut_gon(anh_rut["space"])
    assert space_goc(anh_rut["space"]) == anh_day_du["space"]
    assert not la_space_rut_gon(anh_day_du["space"])


def test_id_hyperedge_cung_bi_bam(anh_day_du, anh_rut):
    """Id hyperedge **đã** là một băm, nhưng là băm **không muối** của đúng dict
    slot mà bản rút gọn đang giấu.

    Để nguyên là để lại một cửa xác nhận bằng danh sách ứng viên: ai có một bản
    fact nghi ngờ chỉ cần băm nó rồi so. Đó đúng là cửa mà luật muối tồn tại để
    đóng, nên id hyperedge cũng đi qua băm có muối.
    """
    cu = {h["id"] for h in anh_day_du["hyperedge"]}
    moi = {h["id"] for h in anh_rut["hyperedge"]}
    assert cu & moi == set()
    assert len(moi) == len(cu)


def test_bam_phu_thuoc_muoi(anh_day_du):
    """Hai muối khác nhau cho hai bộ băm khác nhau - đó là cả tác dụng của muối."""
    a = rut_gon_anh(anh_day_du, MUOI)
    b = rut_gon_anh(anh_day_du, MUOI + "-khac")
    assert {h["id"] for h in a["hyperedge"]} & {h["id"] for h in b["hyperedge"]} == set()


def test_bam_khac_nhau_theo_loai():
    """Một tên file và một tên entity viết giống nhau không được ra cùng băm.

    Cho chúng cùng một băm là dựng một quan hệ bằng nhau không có thật, và tỷ lệ
    3 đọc quan hệ bằng nhau.
    """
    assert bam(MUOI, "entity", "App01") != bam(MUOI, "doc_key", "App01")


# ---------------------------------------------------------------------------
# Muối: thiếu là từ chối, không băm trần
# ---------------------------------------------------------------------------


def test_thieu_file_muoi_la_tu_choi(tmp_path):
    with pytest.raises(MuoiKhongHopLe) as loi:
        doc_muoi(tmp_path / "chua-co.txt")
    assert loi.value.code == "MUOI_KHONG_HOP_LE"
    assert "chua-co.txt" in str(loi.value)


def test_muoi_qua_ngan_la_tu_choi(tmp_path):
    """Một muối ba ký tự là không có muối: dò cả không gian muối rẻ hơn hẳn dò
    danh sách ứng viên, nên nó không đóng được cửa nào."""
    f = tmp_path / "muoi.txt"
    f.write_text("abc", encoding="utf-8")
    with pytest.raises(MuoiKhongHopLe):
        doc_muoi(f)


def test_muoi_du_dai_thi_doc_duoc(tmp_path):
    f = tmp_path / "muoi.txt"
    f.write_text(" " + "x" * DO_DAI_MUOI_TOI_THIEU + "\n", encoding="utf-8")
    assert doc_muoi(f) == "x" * DO_DAI_MUOI_TOI_THIEU


def test_bam_tu_choi_muoi_rong():
    with pytest.raises(MuoiKhongHopLe):
        bam("", "entity", "App01")


def test_rut_gon_hai_lan_la_loi(anh_rut):
    """Rút gọn một bản rút gọn là băm lên băm; quan hệ bằng nhau giữ nguyên nên
    không ai phát hiện ra, mà file thì mất đường tra ngược bằng muối."""
    with pytest.raises(ValueError):
        rut_gon_anh(anh_rut, MUOI)


def test_bam_trung_la_tu_choi_ca_dot(monkeypatch):
    """Va chạm băm gộp hai entity thành một, tức làm sai đúng tỷ lệ 3."""
    import eval.anh_rut_gon as mod

    monkeypatch.setattr(mod, "SO_HEX", 1)
    anh = {
        "version": 2, "space": "thu", "ngay_do": "n", "policy_version": "p",
        "tai_lieu": [{"doc_key": "a.md", "sha256": "0" * 64, "scope": "noi_bo",
                      "content_type": "runbook"}],
        "hyperedge": [
            {"id": f"he-{i}", "doc_key": ["a.md"], "khoa": "noi_bo:runbook",
             "slots": {"subject": [f"E{i}"]}}
            for i in range(40)
        ],
    }
    with pytest.raises(BamTrung) as loi:
        mod.rut_gon_anh(anh, MUOI)
    assert loi.value.code == "BAM_TRUNG"


# ---------------------------------------------------------------------------
# Rào ghi file, hai chiều
# ---------------------------------------------------------------------------


def test_ban_day_du_cua_space_that_khong_vao_duoc_cay_repo():
    """Chiều một: `--space real` dạng đầy đủ, đích trong repo -> từ chối."""
    dich = GOC_REPO / "eval" / "anh_do_thi" / "real.json"
    ly_do = ly_do_tu_choi_dich("real", dich)
    assert ly_do and "đầy đủ" in ly_do and "--rut-gon" in ly_do


def test_ban_rut_gon_cua_space_that_vao_duoc_cay_repo():
    """Chiều hai: cùng space, cùng đích, nhưng `--rut-gon` -> nhận.

    Đây là nửa còn lại của rào. Không có test này thì siết rào thành "real không
    bao giờ vào repo" vẫn xanh, và ba tỷ lệ của `real` lại quay về hằng chép tay.
    """
    dich = GOC_REPO / "eval" / "anh_do_thi" / "real_rut_gon.json"
    assert ly_do_tu_choi_dich("real", dich, rut_gon=True) is None


def test_ban_day_du_ghi_vao_ten_file_cua_ban_rut_gon_van_bi_tu_choi():
    """Ca xấu nhất của cặp rào: bản **đầy đủ** ghi dưới **tên file** của bản rút gọn.

    `.gitignore` phân biệt hai dạng bằng tên file, nên ở tổ hợp này nó mở cửa -
    `real_rut_gon.json` khớp dòng phủ định và git nhận nó. Thứ duy nhất còn đứng
    giữa một file dump nguyên văn giá trị slot và `git add` là rào này, nên nó
    phải xét **cờ `--rut-gon`**, không phải tên file.
    """
    dich = GOC_REPO / "eval" / "anh_do_thi" / "real_rut_gon.json"
    ly_do = ly_do_tu_choi_dich("real", dich, rut_gon=False)
    assert ly_do and "đầy đủ" in ly_do


def test_ban_day_du_van_ra_ngoai_repo_duoc(tmp_path):
    assert ly_do_tu_choi_dich("real", tmp_path / "real.json") is None


def test_ten_file_mac_dinh_khop_loi_tu_khai_trong_file():
    """Tên file và `space` bên trong phải mang cùng một token.

    `.gitignore` phân biệt hai dạng bằng **tên file**, còn người soát đọc lời tự
    khai bên trong; hai thứ lệch nhau là chỗ máy đọc một đằng người đọc một nẻo.
    """
    assert ten_file_mac_dinh("real", rut_gon=False).name == "real.json"
    assert ten_file_mac_dinh("real", rut_gon=True).name == f"real{HAU_TO_RUT_GON}.json"


def test_gitignore_chan_ban_day_du_va_mo_ban_rut_gon():
    """Hai dòng `.gitignore` phải đúng chiều, không chỉ có mặt.

    Dòng phủ định phải nằm **sau** dòng chặn, nếu không git bỏ qua nó và bản rút
    gọn không bao giờ được thêm - triệu chứng là một file "đã ghi" mà
    `git status` không thấy.
    """
    t = (GOC_REPO / ".gitignore").read_text(encoding="utf-8")
    chan = "eval/anh_do_thi/real*.json"
    mo = "!eval/anh_do_thi/*_rut_gon.json"
    assert chan in t and mo in t
    assert t.index(chan) < t.index(mo)
