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
    TIEN_TO_SHA,
    VERSION_ANH_RUT_GON_DOC_DUOC,
    BamTrung,
    MuoiKhongHopLe,
    bam,
    doc_muoi,
    id_cua_muoi,
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
    """Giữ `khoa`, `scope`, `content_type`, `version` và ba số đếm.

    **`sha256` thì không giữ** - xem test dưới. Nó là băm không muối của nguyên
    văn một tài liệu công ty, và `ba_ty_le` không đọc nó lần nào.
    """
    assert anh_rut["version"] == anh_day_du["version"]
    assert anh_rut["ngay_do"] == anh_day_du["ngay_do"]
    assert anh_rut["policy_version"] == anh_day_du["policy_version"]
    for k in ("so_tai_lieu", "so_hyperedge", "so_hyperedge_da_nguon"):
        assert anh_rut[k] == anh_day_du[k]
    assert sorted(h["khoa"] or "" for h in anh_rut["hyperedge"]) == sorted(
        h["khoa"] or "" for h in anh_day_du["hyperedge"]
    )
    for truong in ("scope", "content_type"):
        assert sorted(m[truong] for m in anh_rut["tai_lieu"]) == sorted(
            m[truong] for m in anh_day_du["tai_lieu"]
        )


def test_sha256_than_tai_lieu_cung_di_qua_muoi(anh_day_du, anh_rut):
    """`sha256` là băm **không muối** của nguyên văn một tài liệu công ty.

    Ai có một bản nghi ngờ chỉ cần băm nó rồi so - đúng cửa xác nhận bằng danh
    sách ứng viên mà luật muối tồn tại để đóng, và nó nằm trong một file **có
    commit**. `ba_ty_le` không đọc trường này lần nào nên nó không mất gì; đối
    chiếu với thư mục nguồn vẫn làm được bằng cách băm thân rồi băm qua muối.
    """
    cu = {m["sha256"] for m in anh_day_du["tai_lieu"]}
    moi = {m["sha256"] for m in anh_rut["tai_lieu"]}
    assert cu & moi == set(), "băm thân gốc còn nằm trong bản rút gọn"
    assert len(moi) == len(cu), "băm một-một, không gộp hai tài liệu"
    assert all(s.startswith(TIEN_TO_SHA) for s in moi)


def test_muoi_id_co_mat_va_khong_lo_muoi(anh_rut):
    """Hai lần chụp bằng hai muối khác nhau cho hai file khác nhau hoàn toàn mà
    vẫn cùng ba tỷ lệ; không có vân tay thì một lần đổi muối trông y hệt một lần
    nạp lại."""
    assert anh_rut["muoi_id"] == id_cua_muoi(MUOI)
    assert MUOI not in json.dumps(anh_rut, ensure_ascii=False)
    assert id_cua_muoi(MUOI) != id_cua_muoi(MUOI + "-khac")


def test_loader_nhan_muoi_id_nhung_van_dong_voi_khoa_la(anh_rut, tmp_path):
    """`muoi_id` là khóa **tùy chọn**, không phải một lược đồ mở."""
    from eval.cau_hoi import AnhDoThiKhongHopLe

    f = tmp_path / "co-muoi-id.json"
    f.write_text(json.dumps(anh_rut, ensure_ascii=False), encoding="utf-8")
    assert doc_anh_do_thi(f).space.endswith(HAU_TO_RUT_GON)

    la = dict(anh_rut, khoa_la_hoan_toan=1)
    g = tmp_path / "khoa-la.json"
    g.write_text(json.dumps(la, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AnhDoThiKhongHopLe):
        doc_anh_do_thi(g)


def test_version_khop_loader():
    """Hằng chép lại phải bằng hằng thật của loader.

    `eval/anh_rut_gon.py` cố ý chỉ stdlib nên nó không import `eval.cau_hoi`;
    đây là chỗ canh hai hằng còn bằng nhau, để nâng `VERSION_ANH` mà quên đọc
    lại luật rút gọn là test đỏ.
    """
    from eval.cau_hoi import VERSION_ANH

    assert VERSION_ANH_RUT_GON_DOC_DUOC == VERSION_ANH


def test_version_la_thi_tu_choi(anh_day_du):
    """Chép `version` nguyên văn mà không kiểm là một cửa hỏng lặng: lược đồ lên
    3 kèm một trường mới thì bản rút gọn khai 3 mà thiếu trường đó."""
    with pytest.raises(ValueError):
        rut_gon_anh(dict(anh_day_du, version=99), MUOI)


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

    Chấm bằng cách **dựng ánh xạ rồi so hai đồ thị sau khi đổi tên**, không so
    hai con số `len`: bản trước `zip` hai danh sách sắp theo hai thứ tự không
    liên quan (id gốc và id băm) rồi so hai `len`, nên một hàm rút gọn hoán vị
    nhầm entity giữa các hyperedge vẫn xanh - đúng lỗi nguy hiểm nhất mà hàm này
    có thể mắc, vì nó giữ mọi con số và chỉ đổi *ai đi với ai*.
    """
    goc = {h["id"]: h for h in anh_day_du["hyperedge"]}
    rut = {h["id"]: h for h in anh_rut["hyperedge"]}
    assert len(goc) == len(anh_day_du["hyperedge"])
    assert len(rut) == len(anh_rut["hyperedge"])

    # Ánh xạ id hyperedge: suy từ chính cấu trúc, không từ thứ tự. Hai hyperedge
    # khớp nhau khi cùng bộ (khóa, tập vai, số giá trị mỗi vai, số doc_key) - đủ
    # để ghép một-một trên ảnh chụp thật, và nếu không đủ thì test dừng chứ
    # không đoán.
    def van_tay(h):
        return (
            h["khoa"] or "",
            tuple(sorted((vai, len(gt)) for vai, gt in h["slots"].items())),
            len(h["doc_key"]),
        )

    nhom_goc, nhom_rut = {}, {}
    for h in goc.values():
        nhom_goc.setdefault(van_tay(h), []).append(h)
    for h in rut.values():
        nhom_rut.setdefault(van_tay(h), []).append(h)
    assert set(nhom_goc) == set(nhom_rut)
    for k in nhom_goc:
        assert len(nhom_goc[k]) == len(nhom_rut[k])

    # Ánh xạ entity gốc -> entity băm, dựng từ những nhóm chỉ có **một** ứng
    # viên (ghép chắc chắn), rồi kiểm nó một-một.
    anh_xa: dict[str, str] = {}
    for k, ds in nhom_goc.items():
        if len(ds) != 1:
            continue
        a, b = ds[0], nhom_rut[k][0]
        for vai in a["slots"]:
            for x, y in zip(sorted(a["slots"][vai]), sorted(b["slots"][vai])):
                cu_ = anh_xa.setdefault(x, y)
                assert cu_ == y, f"entity {x!r} ra hai băm khác nhau"
    assert anh_xa, "không ghép được cặp nào: ảnh chụp quá đồng dạng để chấm"
    assert len(set(anh_xa.values())) == len(anh_xa), "hai entity gộp thành một băm"

    # Và đồ thị sau khi đổi tên phải trùng đồ thị băm, trên phần đã ghép được.
    def canh(h, doi=lambda x: x):
        return frozenset(
            (vai, doi(e)) for vai, gt in h["slots"].items() for e in gt
        )

    da_cham = 0
    for k, ds in nhom_goc.items():
        if len(ds) != 1:
            continue
        a, b = ds[0], nhom_rut[k][0]
        if not all(e in anh_xa for gt in a["slots"].values() for e in gt):
            continue
        assert canh(a, anh_xa.get) == canh(b), f"cạnh của {a['id']} bị hoán vị"
        da_cham += 1
    assert da_cham >= 10, f"chỉ chấm được {da_cham} hyperedge, quá ít để nói gì"


def test_hoan_vi_entity_giua_cac_hyperedge_bi_bat():
    """Đối chứng của test trên: một bản rút gọn hoán vị entity phải bị bắt.

    Không có ca này thì phép chấm ở trên có thể lại rơi về so hai con số mà
    không ai nhận ra.
    """
    anh = {
        "version": VERSION_ANH_RUT_GON_DOC_DUOC,
        "space": "thu",
        "ngay_do": "n",
        "policy_version": "p",
        "tai_lieu": [
            {"doc_key": "a.md", "sha256": "0" * 64, "scope": "noi_bo",
             "content_type": "runbook"},
        ],
        "hyperedge": [
            {"id": "he-1", "doc_key": ["a.md"], "khoa": "noi_bo:runbook",
             "slots": {"subject": ["E1"], "cause": ["E2"]}},
            {"id": "he-2", "doc_key": ["a.md"], "khoa": "noi_bo:bao_cao_su_co",
             "slots": {"subject": ["E3"], "cause": ["E4"]}},
        ],
    }
    that = rut_gon_anh(anh, MUOI)
    # Hoán vị `subject` của hai hyperedge: mọi số đếm giữ nguyên.
    hoan_vi = json.loads(json.dumps(that))
    a, b = hoan_vi["hyperedge"][0], hoan_vi["hyperedge"][1]
    a["slots"]["subject"], b["slots"]["subject"] = b["slots"]["subject"], a["slots"]["subject"]
    assert that["so_hyperedge"] == hoan_vi["so_hyperedge"]

    def canh(anh_):
        return sorted(
            (h["khoa"], tuple(sorted((v, tuple(sorted(g))) for v, g in h["slots"].items())))
            for h in anh_["hyperedge"]
        )

    assert canh(that) != canh(hoan_vi), "phép so phải thấy được một hoán vị"


# ---------------------------------------------------------------------------
# Không đủ để dựng lại
# ---------------------------------------------------------------------------


def test_khong_gia_tri_slot_hay_ten_tai_lieu_nao_con_lai(anh_day_du, anh_rut):
    """Quét nguyên văn **cả file**: không một giá trị nào của bản đầy đủ còn lại.

    Vùng quét là cả file, không phải một phép chiếu vài trường - đây là phép
    kiểm mạnh nhất của một file **có commit** dựng từ tài liệu công ty, và thu
    hẹp vùng quét là mở đúng chỗ nó canh.

    Thứ được thu hẹp là **danh sách chuỗi đi tìm**, không phải vùng quét: bản rút
    gọn cố ý giữ nguyên `khoa`, `scope`, `content_type` và `version` (chúng là
    thứ `ba_ty_le` cần và chúng không mang nội dung tài liệu nào), nên một entity
    trùng đúng một trong những giá trị *được phép giữ* đó không phải một rò rỉ.
    Ca thật: entity tên `ticket` nằm trong `content_type` `vong_doi_ticket`. Danh
    sách được phép đọc từ **chính bản đầy đủ**, không viết cứng, nên thêm một
    `content_type` mới không làm phép kiểm này báo sai.
    """
    van_ban = json.dumps(anh_rut, ensure_ascii=False)
    # Giá trị **được phép** còn nguyên trong bản rút gọn, đọc từ bản đầy đủ.
    duoc_giu = {str(anh_day_du["version"]), anh_day_du["ngay_do"], anh_day_du["policy_version"]}
    for m in anh_day_du["tai_lieu"]:
        duoc_giu |= {m["scope"], m["content_type"]}
    for h in anh_day_du["hyperedge"]:
        if h["khoa"]:
            duoc_giu |= {h["khoa"], *h["khoa"].split(":")}
    duoc_giu |= set(anh_day_du["hyperedge"][0]["slots"]) if anh_day_du["hyperedge"] else set()

    def con_trong_file(gia_tri: str) -> bool:
        """Chuỗi còn trong file, và nó **không** phải một giá trị được phép giữ.

        Chỉ tha đúng ca "trùng khít hoặc là chuỗi con của một giá trị được phép":
        một entity dài chứa tên tài liệu vẫn là rò rỉ dù nó cũng chứa chữ
        `runbook`.
        """
        if gia_tri not in van_ban:
            return False
        return not any(gia_tri in g for g in duoc_giu)

    con_lai = []
    for m in anh_day_du["tai_lieu"]:
        if con_trong_file(m["doc_key"]):
            con_lai.append(m["doc_key"])
        # `sha256` cũng là một giá trị của tài liệu thật, không phải metadata vô
        # hại: nó là băm không muối của nguyên văn thân.
        if con_trong_file(m["sha256"]):
            con_lai.append(m["sha256"])
    for h in anh_day_du["hyperedge"]:
        if con_trong_file(h["id"]):
            con_lai.append(h["id"])
        for gt in h["slots"].values():
            con_lai += [e for e in gt if con_trong_file(e)]
    assert not con_lai, sorted(set(con_lai))[:10]


def test_moi_id_mang_tien_to_tu_khai(anh_rut):
    """Một giá trị lẻ chép ra khỏi file vẫn tự khai nó là băm của bản rút gọn."""
    for m in anh_rut["tai_lieu"]:
        assert m["doc_key"].startswith(TIEN_TO_DOC)
        assert m["sha256"].startswith(TIEN_TO_SHA)
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
        "version": VERSION_ANH_RUT_GON_DOC_DUOC, "space": "thu", "ngay_do": "n",
        "policy_version": "p",
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


# ---------------------------------------------------------------------------
# Cùng cặp rào cho space `that_khu` (story 2.13)
# ---------------------------------------------------------------------------


def test_ban_day_du_cua_that_khu_khong_vao_duoc_cay_repo():
    """Chiều một, cho space thứ hai của tài liệu công ty.

    `that_khu` chứa **cùng 50 tài liệu đã khử** của `real`, chỉ khác bộ trích
    xuất. Đã khử không có nghĩa là công khai: nội dung vẫn là văn bản công ty,
    nên bản đầy đủ không vào git dù nó đi được ra API ngoài.
    """
    dich = GOC_REPO / "eval" / "anh_do_thi" / "that_khu.json"
    ly_do = ly_do_tu_choi_dich("that_khu", dich)
    assert ly_do and "đầy đủ" in ly_do and "--rut-gon" in ly_do


def test_ban_rut_gon_cua_that_khu_vao_duoc_cay_repo():
    """Chiều hai: nửa còn lại của rào.

    Không có test này thì siết rào thành "that_khu không bao giờ vào repo" vẫn
    xanh, và cột thứ tư của trang ba tỷ lệ lại quay về hằng chép tay.
    """
    dich = GOC_REPO / "eval" / "anh_do_thi" / "that_khu_rut_gon.json"
    assert ly_do_tu_choi_dich("that_khu", dich, rut_gon=True) is None


def test_ban_day_du_that_khu_ghi_vao_ten_file_rut_gon_van_bi_tu_choi():
    """Tổ hợp xấu nhất: bản đầy đủ dưới tên file của bản rút gọn.

    `.gitignore` phân biệt hai dạng bằng tên file, nên ở tổ hợp này nó mở cửa;
    thứ duy nhất còn đứng giữa một file dump nguyên văn giá trị slot và
    `git add` là rào này, và nó phải xét **cờ**, không phải tên file.
    """
    dich = GOC_REPO / "eval" / "anh_do_thi" / "that_khu_rut_gon.json"
    ly_do = ly_do_tu_choi_dich("that_khu", dich, rut_gon=False)
    assert ly_do and "đầy đủ" in ly_do


def test_gitignore_chan_ban_day_du_that_khu_va_mo_ban_rut_gon():
    """Hai dòng đúng chiều, cùng khuôn với cặp dòng của `real`."""
    t = (GOC_REPO / ".gitignore").read_text(encoding="utf-8")
    chan = "eval/anh_do_thi/that_khu*.json"
    mo = "!eval/anh_do_thi/*_rut_gon.json"
    assert chan in t and mo in t
    assert t.index(chan) < t.index(mo)


def test_ten_file_mac_dinh_cua_that_khu_khop_loi_tu_khai():
    assert ten_file_mac_dinh("that_khu", rut_gon=False).name == "that_khu.json"
    assert (
        ten_file_mac_dinh("that_khu", rut_gon=True).name
        == f"that_khu{HAU_TO_RUT_GON}.json"
    )


# ---------------------------------------------------------------------------
# Đường nối `--rut-gon` trong `main()` (vòng review 05/09)
# ---------------------------------------------------------------------------


def _moi_truong_kho(monkeypatch, tmp_path):
    """Ba biến bắt buộc của `chup_do_thi`, trỏ vào chỗ không ai chạm."""
    from adapters.kv import WORKING_DIR_KEY
    from adapters.neo4j import NEO4J_PASSWORD_KEY, NEO4J_URI_KEY
    from adapters.engine import BIEN_MOI_TRUONG

    for khoa, gia_tri in (
        (NEO4J_URI_KEY, "bolt://khong-dung-toi:7687"),
        (NEO4J_PASSWORD_KEY, "x"),
        (WORKING_DIR_KEY, str(tmp_path)),
    ):
        monkeypatch.setenv(BIEN_MOI_TRUONG[khoa], gia_tri)


ANH_GIA = {
    "version": 2,
    "space": "real",
    "ngay_do": "2026-09-05T00:00:00+00:00",
    "policy_version": "p" * 8,
    "so_tai_lieu": 1,
    "so_hyperedge": 1,
    "so_hyperedge_da_nguon": 0,
    "tai_lieu": [
        {"doc_key": "bi-mat.md", "sha256": "a" * 64, "scope": "noi_bo",
         "content_type": "bao_cao_su_co"},
    ],
    "hyperedge": [
        {"id": "he-abc", "doc_key": ["bi-mat.md"], "khoa": "noi_bo:bao_cao_su_co",
         "slots": {"subject": ["GIA TRI SLOT THAT"], "cause": ["NGUYEN NHAN THAT"]}},
    ],
}


def _chay_main(monkeypatch, tmp_path, argv):
    """Chạy `chup_do_thi.main` với phần chạm kho bị thay; trả (mã, file đích)."""
    import eval.chup_do_thi as mod

    _moi_truong_kho(monkeypatch, tmp_path)

    async def chup_gia(space, policy_version, cau_hinh):
        return json.loads(json.dumps(ANH_GIA))

    monkeypatch.setattr(mod, "chup", chup_gia)
    return mod.main(argv)


def test_main_voi_rut_gon_ghi_ban_rut_gon(monkeypatch, tmp_path):
    """Đường nối `--rut-gon` trong `main()` phải có test chạy qua nó.

    Trước ca này, xóa dòng `rut_gon_anh` hoặc chuyển nó xuống **sau** `ghi_anh`
    làm ảnh **đầy đủ** rơi vào đúng tên file mà `.gitignore` cho phép commit -
    và mọi test khác vẫn xanh, vì chúng chấm hàm thuần chứ không chấm đường nối.
    """
    muoi = tmp_path / "muoi.txt"
    muoi.write_text(MUOI, encoding="utf-8")
    dich = tmp_path / "real_rut_gon.json"
    ma = _chay_main(
        monkeypatch, tmp_path,
        [f"--space", "real", "--rut-gon", "--muoi", str(muoi), "--dich", str(dich)],
    )
    assert ma == 0
    ra = json.loads(dich.read_text(encoding="utf-8"))
    assert ra["space"].endswith(HAU_TO_RUT_GON)
    assert ra["muoi_id"] == id_cua_muoi(MUOI)
    van_ban = dich.read_text(encoding="utf-8")
    for gia_tri in ("GIA TRI SLOT THAT", "NGUYEN NHAN THAT", "bi-mat.md", "a" * 64):
        assert gia_tri not in van_ban, f"{gia_tri!r} còn trong file ghi ra"


def test_main_khong_co_co_rut_gon_thi_tu_choi_va_khong_ghi(monkeypatch, tmp_path):
    """Ca ngược: cùng space, cùng đích, thiếu cờ -> trả 1 và không ghi gì."""
    dich = tmp_path / "real_rut_gon.json"
    ma = _chay_main(monkeypatch, tmp_path, ["--space", "real", "--dich", str(dich)])
    assert ma == 1
    assert not dich.exists()


def test_main_rut_gon_ma_ten_dich_sai_thi_tu_choi(monkeypatch, tmp_path, capsys):
    """`--rut-gon --dich synth.json` ghi đè mỏ neo id của nhãn truy hồi vàng."""
    muoi = tmp_path / "muoi.txt"
    muoi.write_text(MUOI, encoding="utf-8")
    dich = tmp_path / "synth.json"
    ma = _chay_main(
        monkeypatch, tmp_path,
        ["--space", "real", "--rut-gon", "--muoi", str(muoi), "--dich", str(dich)],
    )
    assert ma == 1
    assert not dich.exists()
    assert "_rut_gon.json" in capsys.readouterr().err


def test_main_thieu_muoi_thi_tu_choi_truoc_khi_cham_kho(monkeypatch, tmp_path, capsys):
    """Thiếu muối là từ chối, và từ chối **trước** khi đọc graph."""
    import eval.chup_do_thi as mod

    _moi_truong_kho(monkeypatch, tmp_path)
    da_goi = []

    async def chup_gia(*a, **k):
        da_goi.append(1)
        return json.loads(json.dumps(ANH_GIA))

    monkeypatch.setattr(mod, "chup", chup_gia)
    ma = mod.main(
        ["--space", "real", "--rut-gon", "--muoi", str(tmp_path / "chua-co.txt"),
         "--dich", str(tmp_path / "real_rut_gon.json")]
    )
    assert ma == 1
    assert da_goi == [], "không được chạm kho khi đã thiếu muối"
    assert "MUOI_KHONG_HOP_LE" in capsys.readouterr().err
