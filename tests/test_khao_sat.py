"""50 bản ghi khảo sát phải khớp bảng thiết kế của chúng (story 2.10, FR-27).

Viết **trước** khi chuyển bản ghi từ `extra/khao-sat-50/*/dung/` vào
`eval/khao_sat/`. Luật một-một giống hệt luật mà story 2.5 đặt cho bộ vàng
trích xuất và story 2.8 đặt cho corpus, và vì cùng một lý do: một file không có
mục là một bản ghi không ai duyệt thiết kế, một mục không có file là một lỗ
trong mẫu số của ba tỷ lệ n-ngôi.

Vì sao bảng phải có trước: `core/ingest_scan.py` cố ý **không** whitelist
`content_type`, nên một chữ gõ sai trong frontmatter đi lọt tới ingest rồi mới
nổ `SensitivityRankUnknown` - sau khi đã trả tiền LLM cho phần đầu của lô 50.

Ba nhóm assert:

- **Một-một với thư mục.** Thừa file, thiếu file, lệch nhãn, gõ sai loại.
- **Hình dạng mẫu số.** Hạn ngạch 25/15/10 theo ba bộ phận, ba scope, và mẫu số
  nhạy cảm không rỗng.
- **Ràng buộc kiến trúc.** Mọi loại nội dung có hạng độ nhạy (AD-5), và không
  `doc_key` nào trùng với `eval/corpus/` hay `eval/data/`.

Không có test nào ở đây chạm kho hay gọi LLM.
"""

import hashlib
import re
from pathlib import Path

import pytest
import yaml

from adapters.sensitivity_loader import DUONG_DAN_MAC_DINH as HANG_MAC_DINH
from adapters.sensitivity_loader import tai_hang_do_nhay
from api.nguon_thu_muc import cac_file_nap
from core.ingest_scan import TaiLieuNguon, quet_cac_file
from core.keys import filter_key
from eval.cau_hoi import doc_anh_do_thi
from eval.ty_le_n_ngoi import NGUONG_NHAY_CAM

GOC_REPO = Path(__file__).resolve().parent.parent
BANG_THIET_KE = GOC_REPO / "eval" / "khao_sat_thiet_ke.yaml"
THU_MUC_KHAO_SAT = GOC_REPO / "eval" / "khao_sat"
THU_MUC_CORPUS = GOC_REPO / "eval" / "corpus"
THU_MUC_BO_VANG = GOC_REPO / "eval" / "data"
ANH_KHAO_SAT = GOC_REPO / "eval" / "anh_do_thi" / "khao_sat.json"

# Cùng ba scope với corpus 2.8, cố ý: phép đối chiếu "khớp cỡ" của story 2.10
# chỉ đọc được nếu hai tập nói cùng một thứ tiếng về nhãn quyền.
SCOPE_HOP_LE: frozenset[str] = frozenset({"noi_bo", "khach_hang_a", "khach_hang_b"})
SCOPE_KHACH_HANG: frozenset[str] = frozenset({"khach_hang_a", "khach_hang_b"})

# Hạn ngạch chốt trong `extra/khao-sat-50/README.md`, suy từ tỷ lệ 50/50 nội bộ
# và khách hàng của corpus 2.8. Viết tay ở đây: một bộ phận co lại còn 5 bản ghi
# trong khi bộ phận khác phình ra vẫn giữ tổng 50, và khi đó "phủ ba bộ phận"
# thành một câu đúng về hình thức mà sai về chất liệu.
HAN_NGACH: dict[str, int] = {"tech_support": 25, "devops": 15, "data_center": 10}
SO_BAN_GHI = sum(HAN_NGACH.values())

# Mẫu số phải chia đôi nội bộ / khách hàng, đúng tỷ lệ của corpus 2.8 (20 nội
# bộ / 20 khách hàng trên 40 tài liệu). Đây là điều kiện để phép đối chiếu phân
# bố mức nhạy cảm giữa hai space nói được điều gì.
SO_NOI_BO = 25
SO_KHACH_HANG = 25

KHOA_MUC: frozenset[str] = frozenset(
    {"ma", "ten", "scope", "content_type", "bo_phan", "ghi_chu"}
)
KHOA_GOC: frozenset[str] = frozenset({"version", "han_ngach", "bo_phan", "ban_ghi"})
KHOA_BO_PHAN: frozenset[str] = frozenset({"id", "ten", "mo_ta"})

# Mã bản ghi đọc ra bộ phận: `ts-d-01`, `dv-07`, `dc-10`. Một mã tự do là một mã
# mà bảng phân rã theo bộ phận phải tra ngược.
MAU_MA = re.compile(r"^(ts-d|dv|dc)-\d{2}$")
TIEN_TO_MA: dict[str, str] = {"tech_support": "ts-d", "devops": "dv", "data_center": "dc"}

# Tên file phải *đọc ra* mã của chính mục đó, để `ma` và `ten` không trôi khỏi
# nhau. Hai bộ phận nội bộ mang mã ngay đầu tên file (`dv-07-...`); Tech Support
# giữ mã ticket trong tên (`ts-tk-0142-...`) theo README của thư mục nguồn, còn
# `ma` của nó là số thứ tự `ts-d-NN` - hai thứ khác nhau nên buộc bằng **thứ tự**:
# mục `ts-d-NN` thứ N phải là file `ts-tk-*` thứ N theo số ticket tăng dần.
MAU_TEN_TECH_SUPPORT = re.compile(r"^ts-tk-(\d{4})-[a-z0-9-]+\.md$")

# Space riêng của khảo sát. 50 bản ghi **không bao giờ** nạp vào `synth`: hai
# tập nằm chung một space là hai mẫu số trộn vào nhau và không tách lại được.
SPACE_KHAO_SAT = "khao_sat"


class BangThietKeHong(AssertionError):
    """Bảng thiết kế không đọc được thành một bảng hợp lệ.

    Có tên riêng vì lược đồ hỏng và thư mục lệch bảng là hai chuyện khác nhau:
    một `KeyError` giữa `doi_chieu` chỉ nói tên một khóa, còn thông điệp ở đây
    nói được mục nào và thiếu gì.
    """


def _kiem_lang(dieu_kien, thong_diep: str) -> None:
    if not dieu_kien:
        raise BangThietKeHong(thong_diep)


def doc_bang(duong_dan: Path = BANG_THIET_KE) -> dict:
    """Đọc bảng thiết kế và kiểm *lược đồ* của nó trước khi ai đó đọc nội dung."""
    raw = yaml.safe_load(duong_dan.read_text(encoding="utf-8"))
    _kiem_lang(isinstance(raw, dict), "gốc bảng thiết kế phải là một khối ánh xạ")
    _kiem_lang(set(raw) == KHOA_GOC, f"khóa gốc lệch: {sorted(set(raw) ^ KHOA_GOC)}")
    _kiem_lang(raw["version"] == 1, f"version phải là 1, nhận được {raw['version']!r}")

    _kiem_lang(
        isinstance(raw["han_ngach"], dict) and raw["han_ngach"] == HAN_NGACH,
        f"`han_ngach` phải là {HAN_NGACH}, nhận được {raw['han_ngach']!r}",
    )
    _kiem_lang(
        isinstance(raw["bo_phan"], list) and raw["bo_phan"],
        "`bo_phan` phải là một danh sách không rỗng",
    )
    for i, b in enumerate(raw["bo_phan"]):
        _kiem_lang(isinstance(b, dict), f"bộ phận thứ {i} không phải một khối ánh xạ")
        thieu = sorted(KHOA_BO_PHAN - set(b))
        _kiem_lang(not thieu, f"bộ phận {b.get('id')!r} thiếu khóa {thieu}")
        la = sorted(set(b) - KHOA_BO_PHAN)
        _kiem_lang(not la, f"bộ phận {b.get('id')!r} có khóa lạ {la}")

    _kiem_lang(
        isinstance(raw["ban_ghi"], list) and raw["ban_ghi"],
        "`ban_ghi` phải là một danh sách không rỗng",
    )
    for i, m in enumerate(raw["ban_ghi"]):
        _kiem_lang(isinstance(m, dict), f"mục thứ {i} không phải một khối ánh xạ")
        _kiem_lang(isinstance(m.get("ten"), str) and m["ten"], f"mục thứ {i} thiếu `ten`")
    return raw


def doi_chieu(bang: dict, nguon: dict[str, TaiLieuNguon]) -> list[str]:
    """Mọi cách lệch giữa bảng thiết kế và thư mục, gom thành một danh sách.

    Gom hết rồi trả một lần: người sửa mẫu số phải thấy toàn bộ danh sách trong
    một lượt chạy, không sửa một dòng rồi chạy lại để lộ ra dòng kế.
    """
    loi: list[str] = []
    bo_phan_da_khai = {b["id"] for b in bang["bo_phan"]}
    khai: dict[str, dict] = {}
    ma_da_thay: dict[str, str] = {}
    for muc in bang["ban_ghi"]:
        la = set(muc) ^ KHOA_MUC
        if la:
            loi.append(f"mục {muc.get('ten')!r}: khóa lệch {sorted(la)}")
            continue
        ten = muc["ten"]
        if ten in khai:
            loi.append(f"bảng thiết kế khai {ten!r} hai lần")
            continue
        khai[ten] = muc
        ma = muc["ma"]
        if ma in ma_da_thay:
            loi.append(f"{ten}: mã {ma!r} đã dùng cho {ma_da_thay[ma]!r}")
        else:
            ma_da_thay[ma] = ten
        if not MAU_MA.match(str(ma)):
            loi.append(f"{ten}: mã {ma!r} không theo mẫu {MAU_MA.pattern}")
        if muc["bo_phan"] not in bo_phan_da_khai:
            loi.append(f"{ten}: bộ phận {muc['bo_phan']!r} chưa khai ở khối `bo_phan`")
        elif not str(ma).startswith(TIEN_TO_MA[muc["bo_phan"]] + "-"):
            loi.append(
                f"{ten}: mã {ma!r} không đọc ra bộ phận {muc['bo_phan']!r}"
                f" (phải bắt đầu bằng {TIEN_TO_MA[muc['bo_phan']]!r})"
            )
        elif muc["bo_phan"] == "tech_support":
            if not MAU_TEN_TECH_SUPPORT.match(ten):
                loi.append(
                    f"{ten}: tên file Tech Support phải theo mẫu"
                    f" {MAU_TEN_TECH_SUPPORT.pattern}"
                )
        elif not ten.startswith(f"{ma}-"):
            # Hai bộ phận nội bộ: `ma` phải là tiền tố của `ten`, nếu không hai
            # trường của cùng một mục nói về hai bản ghi khác nhau.
            loi.append(f"{ten}: tên file không bắt đầu bằng mã {ma!r}")
        if muc["scope"] not in SCOPE_HOP_LE:
            loi.append(f"{ten}: scope {muc['scope']!r} không thuộc {sorted(SCOPE_HOP_LE)}")
        if muc["content_type"] not in _hang():
            # Nêu tên loại ở đây thay vì để một `KeyError` nổ ở test khác: cửa
            # quét không whitelist `content_type` nên đây là chỗ duy nhất bắt
            # được một chữ gõ sai trước lúc tiêu tiền cho lô 50 bản ghi.
            loi.append(
                f"{ten}: content_type {muc['content_type']!r} không có hạng độ nhạy"
                f" trong {sorted(_hang())}"
            )

    thua = sorted(set(nguon) - set(khai))
    if thua:
        loi.append(f"file trong `eval/khao_sat/` chưa có mục trong bảng thiết kế: {thua}")
    thieu = sorted(set(khai) - set(nguon))
    if thieu:
        loi.append(f"mục trong bảng thiết kế không có file tương ứng: {thieu}")

    for ten in sorted(set(khai) & set(nguon)):
        muc, tai_lieu = khai[ten], nguon[ten]
        for truong in ("scope", "content_type"):
            trong_bang = muc[truong]
            trong_file = getattr(tai_lieu, truong)
            if trong_bang != trong_file:
                loi.append(
                    f"{ten}: {truong} trong bảng là {trong_bang!r} còn trong"
                    f" frontmatter là {trong_file!r}"
                )
    return loi


def _hang() -> dict[str, int]:
    return dict(tai_hang_do_nhay(HANG_MAC_DINH).hang)


def _quet(thu_muc: Path = THU_MUC_KHAO_SAT) -> dict[str, TaiLieuNguon]:
    # Xem chú thích cùng tên trong `tests/test_corpus.py`: `.space` của story
    # 2.11 là file ẩn, không phải một tài liệu bị từ chối.
    kq = quet_cac_file(cac_file_nap(thu_muc))
    assert not kq.tu_choi, [f"{t.ten}: {t.ma} - {t.ly_do}" for t in kq.tu_choi]
    return {t.doc_key: t for t in kq.chap_nhan}


@pytest.fixture(scope="module")
def bang() -> dict:
    return doc_bang()


@pytest.fixture(scope="module")
def nguon() -> dict[str, TaiLieuNguon]:
    return _quet()


# ---------------------------------------------------------------------------
# Một-một với thư mục
# ---------------------------------------------------------------------------


def test_khao_sat_khop_bang_thiet_ke(bang, nguon):
    """Hàng "Bản ghi lệch bảng thiết kế" của I/O Matrix, chiều thuận."""
    assert doi_chieu(bang, nguon) == []
    assert len(bang["ban_ghi"]) == SO_BAN_GHI
    assert len(nguon) == SO_BAN_GHI


def test_moi_ban_ghi_deu_qua_duoc_cua_quet(nguon):
    """Không file nào bị `core.ingest_scan` từ chối - fixture đã assert, đây là chỗ nói ra.

    Lần nạp thật phải ra 50 bản ghi NẠP và 0 file bị từ chối; một file hỏng
    frontmatter phải biết ở CI, không phải sau khi đã trả tiền cho 49 file kia.
    """
    assert len(nguon) == SO_BAN_GHI
    assert all(t.noi_dung.strip() for t in nguon.values())


def test_them_file_chua_khai_la_do(bang, nguon):
    """Hàng "thêm file chưa khai": file thứ 51 phải bị nêu tên."""
    them = dict(nguon)
    them["zz-99-chua-khai.md"] = TaiLieuNguon(
        doc_key="zz-99-chua-khai.md", scope="noi_bo", content_type="faq", noi_dung="x"
    )
    loi = doi_chieu(bang, them)
    assert any("zz-99-chua-khai.md" in d and "chưa có mục" in d for d in loi), loi


def test_muc_khai_ma_thieu_file_la_do(bang, nguon):
    """Hàng "mục khai thiếu file": mục thiếu phải bị nêu tên."""
    bo = dict(nguon)
    mat = bang["ban_ghi"][0]["ten"]
    del bo[mat]
    loi = doi_chieu(bang, bo)
    assert any(mat in d and "không có file" in d for d in loi), loi


def test_frontmatter_lech_bang_la_do(bang, nguon):
    """Frontmatter lệch bảng: thông điệp phải nêu **hai** giá trị, không chỉ "lệch"."""
    ten = bang["ban_ghi"][0]["ten"]
    lech = dict(nguon)
    goc = lech[ten]
    lech[ten] = TaiLieuNguon(
        doc_key=goc.doc_key,
        scope=goc.scope,
        content_type="postmortem" if goc.content_type != "postmortem" else "faq",
        noi_dung=goc.noi_dung,
    )
    loi = doi_chieu(bang, lech)
    assert any(
        ten in d and repr(goc.content_type) in d and "frontmatter" in d for d in loi
    ), loi


def test_loai_noi_dung_go_sai_bi_bat_truoc_khi_nap(bang, nguon):
    """`runbok` phải đỏ ở CI, kèm danh sách hạng - không đợi tới lúc ingest nổ."""
    hang = set(_hang())
    go_sai = dict(nguon)
    ten = bang["ban_ghi"][0]["ten"]
    goc = go_sai[ten]
    go_sai[ten] = TaiLieuNguon(
        doc_key=goc.doc_key, scope=goc.scope, content_type="runbok", noi_dung=goc.noi_dung
    )
    assert "runbok" not in hang
    loi = doi_chieu(bang, go_sai)
    assert any(ten in d and "runbok" in d for d in loi), loi


def test_ma_ban_ghi_trung_la_do(bang, nguon):
    """Mã bản ghi là khóa mà file nhãn dùng; hai mục cùng mã là hai nhãn chồng nhau."""
    lech = {
        "version": bang["version"],
        "han_ngach": bang["han_ngach"],
        "bo_phan": bang["bo_phan"],
        "ban_ghi": [dict(m) for m in bang["ban_ghi"]],
    }
    lech["ban_ghi"][1]["ma"] = lech["ban_ghi"][0]["ma"]
    loi = doi_chieu(lech, nguon)
    assert any("đã dùng cho" in d for d in loi), loi


# ---------------------------------------------------------------------------
# Hình dạng mẫu số
# ---------------------------------------------------------------------------


def test_han_ngach_ba_bo_phan(bang):
    """25 Tech Support / 15 DevOps / 10 Data Center, đúng README của thư mục nguồn."""
    dem: dict[str, int] = {}
    for m in bang["ban_ghi"]:
        dem[m["bo_phan"]] = dem.get(m["bo_phan"], 0) + 1
    assert dem == HAN_NGACH, dem
    assert sum(dem.values()) == SO_BAN_GHI


def test_ba_bo_phan_deu_duoc_khai_va_deu_co_ban_ghi(bang):
    ids = [b["id"] for b in bang["bo_phan"]]
    assert sorted(ids) == sorted(HAN_NGACH), ids
    assert len(ids) == len(set(ids)), ids
    for b in bang["bo_phan"]:
        assert isinstance(b["ten"], str) and b["ten"].strip()
        assert isinstance(b["mo_ta"], str) and b["mo_ta"].strip()


def test_chia_doi_noi_bo_va_khach_hang(bang):
    """25 nội bộ / 25 khách hàng, đúng tỷ lệ 50/50 mà corpus 2.8 có.

    Không có luật này thì mẫu số trôi về một phía và phép đối chiếu phân bố mức
    nhạy cảm giữa hai space đo mất một chiều.
    """
    scope = [m["scope"] for m in bang["ban_ghi"]]
    assert scope.count("noi_bo") == SO_NOI_BO
    assert sum(1 for s in scope if s in SCOPE_KHACH_HANG) == SO_KHACH_HANG
    assert set(scope) == SCOPE_HOP_LE


def test_moi_ban_ghi_dung_mot_scope_don_tri(nguon):
    """AD-4: scope đơn trị mỗi tài liệu; frontmatter chỉ mang một giá trị."""
    for t in nguon.values():
        assert t.scope in SCOPE_HOP_LE
        assert filter_key(t.scope, t.content_type).count(":") == 1


def test_mau_so_nhay_cam_khong_rong(bang):
    """Có bản ghi hạng từ 20 trở lên, và ở cả ba scope không phải chỉ một.

    Hai tỷ lệ trong ba tỷ lệ lấy "số hyperedge nhạy cảm" làm mẫu số (ADR-012).
    Mẫu số rỗng thì chúng là `None` và cả khảo sát mất hai phần ba nội dung.
    """
    hang = _hang()
    nhay = [m for m in bang["ban_ghi"] if hang[m["content_type"]] >= NGUONG_NHAY_CAM]
    assert nhay, "không bản ghi nào từ hạng 20: hai trong ba tỷ lệ sẽ không tính được"
    assert {m["scope"] for m in nhay} == SCOPE_HOP_LE, sorted(
        {m["scope"] for m in nhay}
    )


def test_ban_ghi_khong_nhay_cam_du_de_composition_risk_co_nghia(bang):
    """Phải có cả bản ghi dưới hạng 20, nếu không tử số tỷ lệ 3 luôn là 0.

    Composition risk hỏi "mọi entity của ca nhạy cảm có còn lộ ở một hyperedge
    không nhạy cảm hay không". Tập `KHÔNG_NHẠY` rỗng thì câu trả lời luôn là
    không, và tỷ lệ 3 là 0 vì hình dạng mẫu số chứ không vì hình dạng tri thức.
    """
    hang = _hang()
    khong_nhay = [m for m in bang["ban_ghi"] if hang[m["content_type"]] < NGUONG_NHAY_CAM]
    assert len(khong_nhay) >= 10, len(khong_nhay)


# ---------------------------------------------------------------------------
# Ràng buộc kiến trúc
# ---------------------------------------------------------------------------


def test_moi_loai_cua_khao_sat_deu_co_hang_do_nhay(bang):
    """Thiếu một hạng là ingest từ chối **cả lô** với `SensitivityRankUnknown`."""
    thieu = sorted({m["content_type"] for m in bang["ban_ghi"]} - set(_hang()))
    assert not thieu, f"loại nội dung của khảo sát chưa có hạng độ nhạy: {thieu}"


def test_khong_trung_doc_key_voi_corpus_va_bo_vang():
    """`doc_key` là tên file và sổ tài liệu tra theo nó.

    50 bản ghi nạp vào space `khao_sat` còn corpus và bộ vàng nằm ở `synth`, nên
    trùng tên hôm nay chưa ghi đè lên nhau. Luật vẫn cứng, vì một lần gõ nhầm
    `--space synth` mà tên lại trùng thì đó là re-ingest im lặng đè mất một tài
    liệu của mẫu số Đo 2/Đo 3, và không có gì đỏ để báo.
    """
    khao_sat = {m["ten"] for m in doc_bang()["ban_ghi"]}
    corpus = {p.name for p in cac_file_nap(THU_MUC_CORPUS)}
    bo_vang = {p.name for p in cac_file_nap(THU_MUC_BO_VANG)}
    assert khao_sat & corpus == set(), sorted(khao_sat & corpus)
    assert khao_sat & bo_vang == set(), sorted(khao_sat & bo_vang)


def test_moi_ban_ghi_giu_dau_tai_lieu_dung():
    """Dấu "TÀI LIỆU DỰNG" phải còn trên từng file.

    Mẫu số là bản ghi **giả lập** (quyết định 03/09/2026). Người mở một file lẻ
    trong `eval/khao_sat/` phải đọc được điều đó ngay ở dòng đầu, không phải đi
    tìm trong `kiem-ke.md` của một thư mục không commit.
    """
    thieu = [
        p.name
        for p in cac_file_nap(THU_MUC_KHAO_SAT)
        if "TÀI LIỆU DỰNG" not in p.read_text(encoding="utf-8")
    ]
    assert not thieu, thieu


def test_space_khao_sat_tach_khoi_synth():
    """Space của khảo sát khai một nơi, và nó không phải `synth`.

    Ràng buộc "50 bản ghi không bao giờ nạp vào `synth`" là một luật, nên nó
    phải có một chỗ để đọc bằng máy. `eval/chup_do_thi.py` cho phép ghi ảnh
    chụp của đúng hai space vào cây repo, và `khao_sat` phải là một trong hai.
    """
    from eval.chup_do_thi import SPACE_GHI_TRONG_REPO

    assert SPACE_KHAO_SAT != "synth"
    assert SPACE_KHAO_SAT in SPACE_GHI_TRONG_REPO


# ---------------------------------------------------------------------------
# Ảnh chụp buộc vào 50 bản ghi trên đĩa
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def anh():
    return doc_anh_do_thi(ANH_KHAO_SAT)


def test_anh_chup_khop_mot_mot_voi_thu_muc_ban_ghi(anh, nguon):
    """Cùng luật một-một mà 2.9 đặt cho `synth`, nay cho `khao_sat`.

    Space `khao_sat` nạp đúng `eval/khao_sat/`. Không canh thì xóa, thêm hay đổi
    tên một bản ghi vẫn để `uv run pytest` xanh, trong khi ảnh chụp - nguồn của
    ba tỷ lệ - đã nói về một kho không còn tồn tại.
    """
    trong_anh = {t.doc_key for t in anh.tai_lieu}
    assert trong_anh == set(nguon), (
        f"thừa trong ảnh {sorted(trong_anh - set(nguon))},"
        f" thiếu {sorted(set(nguon) - trong_anh)}"
    )
    assert anh.space == SPACE_KHAO_SAT
    assert len(trong_anh) == SO_BAN_GHI


def test_sha256_va_nhan_quyen_cua_anh_chup_khop_ban_ghi_tren_dia(anh, nguon):
    """**Đây là chỗ duy nhất canh được bằng máy luật Never của story 2.10.**

    "Không sửa nội dung bản ghi sau khi đã thấy con số của bất kỳ tỷ lệ nào" là
    một luật về hành vi con người, nên nó cần một dấu vết máy đọc được. Ảnh chụp
    mang sha256 **thân** từng bản ghi tại thời điểm nạp; sửa một chữ trong
    `eval/khao_sat/` mà không nạp lại là test đỏ ngay, chứ không phải một ba tỷ
    lệ lặng lẽ nói về một corpus khác với corpus đang nằm trong repo.
    """
    lech = [
        t.doc_key
        for t in anh.tai_lieu
        if hashlib.sha256(nguon[t.doc_key].noi_dung.encode("utf-8")).hexdigest() != t.sha256
        or (nguon[t.doc_key].scope, nguon[t.doc_key].content_type)
        != (t.scope, t.content_type)
    ]
    assert not lech, (
        f"bản ghi đã đổi sau lần nạp gần nhất: {lech}."
        " Ba tỷ lệ đã đếm trên bản cũ - hoặc hoàn nguyên nội dung, hoặc nạp lại"
        " và đếm lại cả hai space (ADR-012, điều kiện đổi)"
    )


def test_nhan_quyen_cua_anh_chup_khop_bang_thiet_ke(anh, bang):
    """Ảnh chụp, frontmatter và bảng thiết kế phải nói cùng một điều.

    Hai test trên buộc ảnh chụp vào *file trên đĩa*; test này buộc nó vào **bảng
    thiết kế**, tức nguồn chuẩn. Thiếu nó thì một mục bảng sửa sai cùng lúc với
    frontmatter vẫn xanh cả ba chiều.
    """
    theo_ten = {m["ten"]: m for m in bang["ban_ghi"]}
    lech = [
        t.doc_key
        for t in anh.tai_lieu
        if (theo_ten[t.doc_key]["scope"], theo_ten[t.doc_key]["content_type"])
        != (t.scope, t.content_type)
    ]
    assert not lech, lech


# ---------------------------------------------------------------------------
# Trục loại nội dung mà khảo sát phủ
# ---------------------------------------------------------------------------

# 9 trong 13 loại nội dung của `config/hang-do-nhay.yaml`. Bốn loại **cố ý** vắng
# (`cmdb`, `faq`, `log`, `tai_lieu_san_pham`) vì ba bộ phận của khảo sát không
# giữ chúng: Tech Support giữ phiếu ticket, DevOps và Data Center giữ runbook,
# SOP và báo cáo sự cố. Hai trong bốn loại vắng là loại **nhạy cảm** (`log` hạng
# 24, `cmdb` hạng 26), nên trục loại nội dung của `khao_sat` hẹp hơn của `synth`
# ở đúng vùng mà tỷ lệ 2 và 3 lấy làm mẫu số.
#
# Khóa tập này lại để thêm một bản ghi là phải **quyết lại**, không phải lặng lẽ
# làm hai cột của bảng đối chiếu so được nhiều hơn hoặc ít hơn trước.
LOAI_KHAO_SAT_PHU: frozenset[str] = frozenset(
    {
        "bao_cao_su_co",
        "bi_mat_ha_tang",
        "canh_bao",
        "known_issue",
        "postmortem",
        "runbook",
        "sop",
        "troubleshooting",
        "vong_doi_ticket",
    }
)
LOAI_KHAO_SAT_VANG: frozenset[str] = frozenset({"cmdb", "faq", "log", "tai_lieu_san_pham"})


def test_tap_loai_noi_dung_cua_khao_sat_la_mot_quyet_dinh_da_khoa(bang):
    """9/13 loại, và bốn loại vắng phải đúng bốn loại đã khai."""
    co = {m["content_type"] for m in bang["ban_ghi"]}
    assert co == LOAI_KHAO_SAT_PHU, sorted(co ^ LOAI_KHAO_SAT_PHU)
    moi_loai = set(_hang())
    assert co | LOAI_KHAO_SAT_VANG == moi_loai, sorted((co | LOAI_KHAO_SAT_VANG) ^ moi_loai)
    assert len(co) == 9 and len(moi_loai) == 13


def test_hai_loai_vang_la_loai_nhay_cam_va_dieu_do_duoc_noi_ra(bang):
    """`log` và `cmdb` vắng, cả hai đều hạng >= 20.

    Đây là điều làm cho phép đối chiếu hai cột không phải một phép so trên cùng
    một trục, và nó phải là một khẳng định có test chứ không một câu trong tài
    liệu. Bảng thiết kế và ADR-012 đều phải nói ra.
    """
    hang = _hang()
    nhay_vang = sorted(t for t in LOAI_KHAO_SAT_VANG if hang[t] >= NGUONG_NHAY_CAM)
    assert nhay_vang == ["cmdb", "log"], nhay_vang
    van_ban = BANG_THIET_KE.read_text(encoding="utf-8")
    for t in sorted(LOAI_KHAO_SAT_VANG):
        assert t in van_ban, f"bảng thiết kế phải khai vì sao thiếu {t}"
    adr = (GOC_REPO / "docs" / "adr" / "ADR-012-dinh-nghia-dem-ba-ty-le-n-ngoi.md").read_text(
        encoding="utf-8"
    )
    assert "cmdb" in adr and "log" in adr


# ---------------------------------------------------------------------------
# Số đo của đợt nạp thật
# ---------------------------------------------------------------------------


def test_so_do_nap_khao_sat_khop_dot_05_09():
    """Khóa số của `eval/so_do_nap/nap-khao-sat.json`, cùng khuôn với `nap-that.json`.

    File có commit mà không mã nào đọc và không test nào khóa là một file trôi
    được: **0,065978 USD** của đợt nạp lại 05/09 (`3b0f428f`) được chép tay vào
    spec, sprint-status và ledger, nên nó cần đúng một chỗ để đối chiếu. Đây
    cũng là chỗ nói ra rằng đợt chạy **trọn** (50 tài liệu, không đợt dở nào ghi
    được file này). Đợt 04/09 (`32293e26`) tiêu 0,066651 USD.
    """
    import json

    duong_dan = GOC_REPO / "eval" / "so_do_nap" / "nap-khao-sat.json"
    do = json.loads(duong_dan.read_text(encoding="utf-8"))
    assert do["version"] == 1
    assert do["space"] == SPACE_KHAO_SAT
    assert do["so_tai_lieu"] == SO_BAN_GHI
    # Đợt 05/09/2026 của story 2.12 (nạp lại sau khi sửa ba khiếm khuyết đã
    # khai). Đợt 04/09 là `32293e26e25f450bb7004ed3d4c63826`, 67.917 + 26.710
    # token, 0,06514068 USD; giữ số cũ trong bình luận để so chứ không xóa.
    assert do["dot_id"] == "3b0f428fe2db407b9d16dd200763ccbd"
    llm = [d for d in do["theo_model"] if d["loai"] == "llm"]
    emb = [d for d in do["theo_model"] if d["loai"] == "embedding"]
    assert len(llm) == 1 and len(emb) == 1
    assert (llm[0]["so_lan"], llm[0]["token_vao"], llm[0]["token_ra"]) == (50, 67912, 26214)
    assert llm[0]["chi_phi_usd"] == pytest.approx(0.06448376)
    assert emb[0]["token_vao"] == 74703
    assert emb[0]["chi_phi_usd"] == pytest.approx(0.00149406)
    assert do["tong"]["chi_phi_usd"] == pytest.approx(0.06597782)
    # Một lời gọi LLM mỗi tài liệu: 50 bản ghi, mỗi bản ghi đúng một chunk.
    assert llm[0]["so_lan"] == do["so_tai_lieu"]


def test_lenh_trong_so_do_nap_dung_space_khao_sat():
    """Dòng `lenh` phải dựng lại được đúng đợt đã sinh ra con số."""
    import json

    do = json.loads(
        (GOC_REPO / "eval" / "so_do_nap" / "nap-khao-sat.json").read_text(encoding="utf-8")
    )
    assert "--space khao_sat" in do["lenh"]
    assert "eval/khao_sat" in do["lenh"]
    assert "--space synth" not in do["lenh"]


# ---------------------------------------------------------------------------
# Ba khiếm khuyết đã khai của mẫu số - **đã sửa 05/09/2026, story 2.12**
# ---------------------------------------------------------------------------
#
# Chỗ này từng có **bốn test khóa hiện trạng**: bốn tên file mang nhãn loại mâu
# thuẫn `content_type`, mọi mốc thời gian nằm ở tương lai so với ngày dựng, và
# hai tập gần như không giao nhau trên trục thời gian. Chúng không nói "như thế
# này là đúng"; chúng nói "hôm nay lệch đúng chừng này, và một lần sửa lén sẽ bị
# bắt". Docstring của chúng dặn story 2.12 **xóa hẳn** chứ không cập nhật số
# trong chúng, và đây là lần đó.
#
# Ba phép sửa, tất cả trong lần nạp lại của story 2.12 (05/09/2026):
#
# - Bốn tên file đổi để mang đúng `content_type` khai (`dv-10`, `dc-03` thành
#   `canh-bao-`; `dv-13`, `dv-14` thành `bi-mat-ha-tang-`). Đổi tên là đổi
#   `doc_key`.
# - Mọi mốc nghiệp vụ lùi đúng **49 ngày** (bảy tuần chẵn, giữ nguyên thứ trong
#   tuần), nên mốc muộn nhất 20/10/2026 thành 01/09/2026 - trước ngày dựng
#   03/09/2026. Dấu "Sinh ngày 03/09/2026" ở đầu mỗi file không dịch: nó là ngày
#   dựng tài liệu, không phải một mốc nghiệp vụ.
# - Năm dòng lệnh mang tên CLI thật của doanh nghiệp đổi sang `cloudctl`.
#
# Lời khai đầy đủ cùng lý do giữ lại nó nằm ở đầu `eval/khao_sat_thiet_ke.yaml`.
# Thứ **còn** canh ba phép sửa này là ba test ở khối "Ảnh chụp" phía trên: chúng
# buộc ảnh chụp khớp một-một với thư mục và khớp sha256 thân từng file, nên
# `khao_sat` phải nạp lại và chụp lại thì bộ test mới xanh trở lại.


# --- Hằng và trợ giúp của bốn luật hướng tới ở cuối file --------------------

# Ngày dựng 50 bản ghi, in ở khối chú thích đầu mỗi file. Mọi mốc **nghiệp vụ**
# phải nằm trước hoặc bằng nó.
NGAY_DUNG_BAN_GHI = "2026-09-03"
MAU_NGAY = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

# Nhãn loại đứng ngay sau mã trong tên file của hai bộ phận nội bộ.
NHAN_DAN_DAU = re.compile(r"^(?:dv|dc)-\d{2}-([a-z]+)-")

# Ba mốc mà hai tập cùng có, đếm lại sau phép lùi 49 ngày của story 2.12 (số cũ
# cũng là ba mốc, nhưng là {12/08, 03/09, 18/09}). Cả ba là trùng hợp chứ không
# phải một sự việc chung: 12/08 là "lần diễn tập gần nhất" nhắc thoáng trong
# `dv-07`, 15/08 là ngày của INC-1611 bên corpus đụng một mốc ticket, 03/09 là
# ngày dựng in ở dấu tài liệu.
MOC_CHUNG_VOI_SYNTH: frozenset[str] = frozenset(
    {"2026-08-12", "2026-08-15", "2026-09-03"}
)


def _moc_ngay(thu_muc: Path) -> set[str]:
    """Mọi mốc `dd/mm/yyyy` trong thư mục, trả dạng ISO để so được bằng chuỗi."""
    ra: set[str] = set()
    for f in cac_file_nap(thu_muc):
        for d, m, y in MAU_NGAY.findall(f.read_text(encoding="utf-8")):
            ra.add(f"{y}-{m}-{d}")
    return ra



# ---------------------------------------------------------------------------
# Ba luật **hướng tới**, thay ba test khóa hiện trạng đã xóa
# ---------------------------------------------------------------------------
#
# Xóa ba test khóa hiện trạng mà không thay gì là để ba khiếm khuyết quay lại
# lặng lẽ ở lần sửa sau. Ba test dưới đây khóa **trạng thái đúng** chứ không
# khóa độ lệch: chúng nói "phải như thế này", không nói "hôm nay lệch chừng này".


def test_moi_moc_nghiep_vu_khong_o_tuong_lai_so_voi_ngay_dung():
    """Mốc nghiệp vụ muộn nhất phải `<=` ngày dựng tài liệu.

    Bản ghi sinh 03/09/2026 mà sự việc bên trong chạy tới 20/10 là một trục thời
    gian không thể đúng, và `time` là một trong 8 vai được trích. Story 2.12 lùi
    mọi mốc 49 ngày; test này là chỗ luật đó ở lại.

    Dấu "Sinh ngày 03/09/2026" trong khối chú thích đầu mỗi file **không** phải
    một mốc nghiệp vụ, nên nó bị loại khỏi phép đếm - loại bằng chính chuỗi nhận
    dạng khối đó, không bằng một danh sách ngoại lệ chép tay.
    """
    ra: set[str] = set()
    for f in cac_file_nap(THU_MUC_KHAO_SAT):
        for dong in f.read_text(encoding="utf-8").splitlines():
            if "Sinh ngày" in dong:
                continue
            for d, m, y in MAU_NGAY.findall(dong):
                ra.add(f"{y}-{m}-{d}")
    assert ra, "50 bản ghi phải có mốc thời gian để đo"
    assert max(ra) <= NGAY_DUNG_BAN_GHI, sorted(ra)[-3:]


def test_nhan_dan_dau_ten_file_khop_content_type_khai(bang):
    """Tên file không được nói một đằng còn `content_type` khai một nẻo.

    `core.ingest_scan` đọc frontmatter chứ không đọc tên file, nên một tên lệch
    không làm con số nào sai - nó làm **người soát** sai: `doc_key` là tên file
    và nó đứng ở cột đầu của ảnh chụp, bảng phân bố và trang CT-03.

    Chỉ chấm nhãn nào **là một loại nội dung có thật**: một tên bắt đầu bằng
    `dv-07-runbook-...` phải khai `runbook`, còn `dv-01-postmortem-...` phải khai
    `postmortem`; một tên bắt đầu bằng một chữ không phải tên loại (`dv-10-canh-`)
    thì không có gì để đối chiếu và test không bịa ra một luật cho nó.
    """
    from adapters.sensitivity_loader import tai_hang_do_nhay, DUONG_DAN_MAC_DINH

    loai_co_that = set(tai_hang_do_nhay(DUONG_DAN_MAC_DINH).hang)
    lech = {}
    for m in bang["ban_ghi"]:
        mm = NHAN_DAN_DAU.match(m["ten"])
        if mm and mm.group(1) in loai_co_that and mm.group(1) != m["content_type"]:
            lech[m["ten"]] = m["content_type"]
    assert not lech, (
        f"tên file nói một đằng, `content_type` khai một nẻo: {lech}."
        " Đổi tên file (và nhớ nạp lại: `doc_key` đổi theo)"
    )


def test_khong_ten_chuong_trinh_dong_lenh_that_trong_ban_ghi():
    """Tên CLI của doanh nghiệp chủ quản không được có trong `eval/khao_sat/`.

    50 bản ghi là **bản dựng tay** nên không nội dung nghiệp vụ nào rò; thứ rò
    là **danh tính người thuê khóa luận**. Bảng bí danh của story 2.11 gán tên
    đó thành một bí danh cho 50 tài liệu thật, nên để nó nguyên ở đây là hai bộ
    dữ liệu trong repo khai hai luật khác nhau cho cùng một chuỗi.

    Tên đọc từ **bảng bí danh ngoài repo**, không viết vào test: viết nó vào một
    file có commit là đúng lỗi mà test này dựng ra để chặn. Thiếu bảng thì bỏ
    qua - trên máy chủ CI `extra/` không được đồng bộ.
    """
    import json

    bang = GOC_REPO / "extra" / "khao-sat-50" / "bang-bi-danh.json"
    if not bang.is_file():
        pytest.skip("không có bảng bí danh (extra/ không đồng bộ) - bỏ qua")
    to_chuc = json.loads(bang.read_text(encoding="utf-8")).get("to_chuc", {})
    ten = sorted({t.lower() for t in to_chuc if len(t) >= 4})
    assert ten, "bảng bí danh phải có mục `to_chuc` để đối chiếu"
    dinh = {}
    for f in cac_file_nap(THU_MUC_KHAO_SAT):
        than = f.read_text(encoding="utf-8").lower()
        co = [t for t in ten if t in than]
        if co:
            dinh[f.name] = co
    assert not dinh, f"tên tổ chức thật còn trong bản ghi dựng: {dinh}"


def test_hai_tap_giao_nhau_bao_nhieu_tren_truc_thoi_gian():
    """Lời khai về giới hạn trục thời gian, **viết lại** theo mốc sau khi lùi 49 ngày.

    Test cũ khóa lời khai "hai tập gần như không giao nhau, 3/30 mốc chung".
    Docstring của nó **không** dặn xóa, và phép lùi 49 ngày đổi chính lời khai đó
    - nên nó được viết lại chứ không bỏ trắng. Phép đối chiếu hai cột của story
    2.10 không đọc trục thời gian, nên đây không phải một lỗi của ba tỷ lệ; nó là
    một giới hạn phải nhớ nếu ai đó sau này muốn một phép đo có chiều thời gian.
    """
    cua_khao_sat = _moc_ngay(THU_MUC_KHAO_SAT)
    cua_synth = _moc_ngay(THU_MUC_CORPUS) | _moc_ngay(THU_MUC_BO_VANG)
    chung = cua_khao_sat & cua_synth
    assert chung == MOC_CHUNG_VOI_SYNTH, sorted(chung)
    assert len(chung) * 5 < len(cua_khao_sat), (
        f"{len(chung)}/{len(cua_khao_sat)} mốc chung - hai trục thời gian không"
        " còn rời nhau như lời khai"
    )
