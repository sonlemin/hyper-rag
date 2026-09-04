"""Corpus dựng ~40 tài liệu phải khớp bảng thiết kế của nó (story 2.8, FR-27).

Viết **trước** tài liệu. Luật một-một giống hệt luật mà story 2.5 đặt cho bộ
vàng trích xuất, và vì cùng một lý do: một file không có mục là một tài liệu
không ai duyệt thiết kế, một mục không có file là một lỗ trong thứ mà mọi phép
đo sau đứng lên.

Vì sao phải có test này chứ không dựa vào cửa quét: `core/ingest_scan.py` cố ý
**không** whitelist `content_type` (nó chỉ đòi nhãn dựng được khóa lọc), nên
`runbok` viết thiếu chữ đi lọt tới ingest rồi mới nổ `SensitivityRankUnknown` -
sau khi đã trả tiền LLM cho phần đầu của lô. Bắt ở CI rẻ hơn nhiều so với sửa
`core/`.

Ba nhóm assert:

- **Một-một với thư mục.** Thừa file, thiếu file, lệch nhãn.
- **Hình dạng corpus.** 21 lõi / 19 nhiễu, ba kịch bản, ba scope trong đó hai
  scope khách hàng (RT-01), phủ đủ 12 loại tài liệu của A8.
- **Ràng buộc kiến trúc.** Mọi loại có hạng độ nhạy (AD-5) và số khóa lọc của
  vai nhiều khóa nhất dưới trần 50 của AD-4.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from adapters.policy_loader import load_policy
from adapters.sensitivity_loader import DUONG_DAN_MAC_DINH as HANG_MAC_DINH
from adapters.sensitivity_loader import SensitivityRanksInvalid, tai_hang_do_nhay
from api.nguon_thu_muc import cac_file_nap
from core.ingest_scan import TaiLieuNguon, quet_cac_file
from core.keys import filter_key

GOC_REPO = Path(__file__).resolve().parent.parent
BANG_THIET_KE = GOC_REPO / "eval" / "corpus_thiet_ke.yaml"
THU_MUC_CORPUS = GOC_REPO / "eval" / "corpus"
POLICY_TOI_GIAN = GOC_REPO / "config" / "policy-toi-gian.yaml"

# Ba scope của corpus. `noi_bo` là tri thức nội bộ, hai scope còn lại là hồ sơ
# hai khách hàng - chiều khách hàng nằm *trong* scope theo AD-4, không phải một
# trường thứ hai.
SCOPE_HOP_LE: frozenset[str] = frozenset({"noi_bo", "khach_hang_a", "khach_hang_b"})
SCOPE_KHACH_HANG: frozenset[str] = frozenset({"khach_hang_a", "khach_hang_b"})

# 12 loại tài liệu của PRD addendum A8, viết tay ở đây chứ không suy từ bảng
# hạng: bảng hạng có 13 loại (thêm `bi_mat_ha_tang`), và điều mà AC đòi là
# corpus phủ đủ *danh sách A8*, không phải phủ đủ file cấu hình.
LOAI_A8: frozenset[str] = frozenset(
    {
        "sop",
        "runbook",
        "bao_cao_su_co",
        "cmdb",
        "log",
        "canh_bao",
        "vong_doi_ticket",
        "faq",
        "known_issue",
        "troubleshooting",
        "postmortem",
        "tai_lieu_san_pham",
    }
)

SO_LOI = 21
SO_NHIEU = 19
SO_TAI_LIEU = SO_LOI + SO_NHIEU

# Trần AD-4: một vai vượt 50 khóa lọc buộc đo lại recall/độ trễ trước khi tiến.
TRAN_KHOA_MOI_VAI = 50

KHOA_MUC: frozenset[str] = frozenset(
    {"ten", "scope", "content_type", "kich_ban", "vai_tro", "ghi_chu"}
)
KHOA_GOC: frozenset[str] = frozenset(
    {"version", "so_dinh_hyperedge_demo", "kich_ban", "tai_lieu"}
)
VAI_TRO_HOP_LE: frozenset[str] = frozenset({"loi", "nhieu"})
KICH_BAN_NHIEU = "nhieu"
KHOA_KICH_BAN: frozenset[str] = frozenset({"id", "ten", "mo_ta", "scope_chinh"})

# Ba kịch bản của A8, mỗi kịch bản 7 tài liệu lõi (21 = 3 x 7). Kỳ vọng viết tay:
# một kịch bản co lại còn 3 tài liệu trong khi kịch bản khác phình ra vẫn giữ
# tổng 21, và khi đó "phủ 3 kịch bản" thành một câu đúng về hình thức.
SO_LOI_MOI_KICH_BAN = 7

# Số đỉnh của hyperedge demo App01, chốt 03/09/2026 bằng phép đếm trên đồ thị đã
# nạp thật (PRD mục lục giả định 6.3 khoản 4). Viết tay ở đây: hai ứng viên của
# giả định là 5 và 6, nên một test chỉ đòi "số nguyên dương" cho phép đổi 5 thành
# 6 mà vẫn xanh - tức cho phép mở lại một giả định đã đóng mà không ai thấy.
# Đổi số này nghĩa là phải đếm lại trên đồ thị và sửa PRD trong cùng một commit.
SO_DINH_HYPEREDGE_DEMO = 8
PRD = (
    GOC_REPO
    / "_bmad-output"
    / "planning-artifacts"
    / "prds"
    / "prd-hyper_graph_rag-2026-08-29"
    / "prd.md"
)


# ---------------------------------------------------------------------------
# Loader và phép đối chiếu - hàm thuần, dùng lại được cho ca dựng tay
# ---------------------------------------------------------------------------


class BangThietKeHong(AssertionError):
    """Bảng thiết kế không đọc được thành một bảng hợp lệ.

    Có tên riêng vì lược đồ hỏng và corpus lệch bảng là hai chuyện khác nhau:
    một `KeyError` giữa `doi_chieu` chỉ nói "\'id\'", còn thông điệp ở đây nói
    được mục nào và thiếu gì.
    """


def _kiem_lang(dieu_kien, thong_diep: str) -> None:
    if not dieu_kien:
        raise BangThietKeHong(thong_diep)


def doc_bang(duong_dan: Path = BANG_THIET_KE) -> dict:
    """Đọc bảng thiết kế và kiểm *lược đồ* của nó trước khi ai đó đọc nội dung.

    Mọi cách hỏng là `BangThietKeHong` kèm câu nói được chỗ hỏng: mục không phải
    dict, `kich_ban` không phải list, một kịch bản thiếu khóa. Không có tầng này
    thì `doi_chieu` ném `KeyError`/`TypeError` giữa chừng và người sửa bảng phải
    đọc traceback để đoán mình gõ sai chỗ nào.
    """
    raw = yaml.safe_load(duong_dan.read_text(encoding="utf-8"))
    _kiem_lang(isinstance(raw, dict), "gốc bảng thiết kế phải là một khối ánh xạ")
    _kiem_lang(set(raw) == KHOA_GOC, f"khóa gốc lệch: {sorted(set(raw) ^ KHOA_GOC)}")
    _kiem_lang(raw["version"] == 1, f"version phải là 1, nhận được {raw['version']!r}")

    _kiem_lang(
        isinstance(raw["kich_ban"], list) and raw["kich_ban"],
        "`kich_ban` phải là một danh sách không rỗng",
    )
    for i, k in enumerate(raw["kich_ban"]):
        _kiem_lang(isinstance(k, dict), f"kịch bản thứ {i} không phải một khối ánh xạ")
        thieu = sorted(KHOA_KICH_BAN - set(k))
        _kiem_lang(not thieu, f"kịch bản {k.get('id')!r} thiếu khóa {thieu}")
        la = sorted(set(k) - KHOA_KICH_BAN)
        _kiem_lang(not la, f"kịch bản {k.get('id')!r} có khóa lạ {la}")
        _kiem_lang(
            k["scope_chinh"] is None or k["scope_chinh"] in SCOPE_HOP_LE,
            f"kịch bản {k['id']!r}: scope_chinh {k['scope_chinh']!r} ngoài"
            f" {sorted(SCOPE_HOP_LE)}",
        )

    _kiem_lang(
        isinstance(raw["tai_lieu"], list) and raw["tai_lieu"],
        "`tai_lieu` phải là một danh sách không rỗng",
    )
    for i, m in enumerate(raw["tai_lieu"]):
        _kiem_lang(isinstance(m, dict), f"mục thứ {i} không phải một khối ánh xạ")
        _kiem_lang(isinstance(m.get("ten"), str) and m["ten"], f"mục thứ {i} thiếu `ten`")
    return raw


def doi_chieu(bang: dict, nguon: dict[str, TaiLieuNguon]) -> list[str]:
    """Mọi cách lệch giữa bảng thiết kế và thư mục, gom thành danh sách.

    Gom hết rồi trả một lần: người sửa corpus phải thấy toàn bộ danh sách trong
    một lượt chạy, không sửa một dòng rồi chạy lại để lộ ra dòng kế.
    """
    loi: list[str] = []
    kich_ban_da_khai = {k["id"] for k in bang["kich_ban"]}
    khai: dict[str, dict] = {}
    for muc in bang["tai_lieu"]:
        la = set(muc) ^ KHOA_MUC
        if la:
            loi.append(f"mục {muc.get('ten')!r}: khóa lệch {sorted(la)}")
            continue
        ten = muc["ten"]
        if ten in khai:
            loi.append(f"bảng thiết kế khai {ten!r} hai lần")
            continue
        khai[ten] = muc
        if muc["vai_tro"] not in VAI_TRO_HOP_LE:
            loi.append(f"{ten}: vai_tro {muc['vai_tro']!r} không thuộc {sorted(VAI_TRO_HOP_LE)}")
        if muc["kich_ban"] not in kich_ban_da_khai:
            loi.append(f"{ten}: kịch bản {muc['kich_ban']!r} chưa khai ở khối `kich_ban`")
        if (muc["kich_ban"] == KICH_BAN_NHIEU) != (muc["vai_tro"] == "nhieu"):
            loi.append(
                f"{ten}: vai_tro {muc['vai_tro']!r} và kịch bản {muc['kich_ban']!r}"
                " không đi cùng nhau"
            )
        if muc["scope"] not in SCOPE_HOP_LE:
            loi.append(f"{ten}: scope {muc['scope']!r} không thuộc {sorted(SCOPE_HOP_LE)}")
        if muc["content_type"] not in _hang():
            # Nêu tên loại ở đây thay vì để `hang[m["content_type"]]` ném
            # `KeyError` ở một test khác: cửa quét không whitelist `content_type`
            # nên đây là chỗ duy nhất bắt được một chữ gõ sai trước lúc tiêu tiền.
            loi.append(
                f"{ten}: content_type {muc['content_type']!r} không có hạng độ nhạy"
                f" trong {sorted(_hang())}"
            )

    thua = sorted(set(nguon) - set(khai))
    if thua:
        loi.append(f"file trong `eval/corpus/` chưa có mục trong bảng thiết kế: {thua}")
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


def _quet(thu_muc: Path = THU_MUC_CORPUS) -> dict[str, TaiLieuNguon]:
    # `cac_file_nap` chứ không `quet_thu_muc`: từ story 2.11 mỗi thư mục nguồn
    # mang một file `.space` khai space của chính nó, và lõi quét của `core/`
    # duyệt **mọi** file nên nó thấy `.space` là một `DINH_DANG_LA`. Đây là đúng
    # danh sách ứng viên mà `api.do_chi_phi` đưa vào lõi quét.
    kq = quet_cac_file(cac_file_nap(thu_muc))
    assert not kq.tu_choi, [
        f"{t.ten}: {t.ma} - {t.ly_do}" for t in kq.tu_choi
    ]
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


def test_corpus_khop_bang_thiet_ke(bang, nguon):
    """Hàng "Corpus khớp bảng thiết kế" của I/O Matrix."""
    assert doi_chieu(bang, nguon) == []
    assert len(bang["tai_lieu"]) == SO_TAI_LIEU
    assert len(nguon) == SO_TAI_LIEU


def test_moi_file_deu_qua_duoc_cua_quet(nguon):
    """Không file nào bị `core.ingest_scan` từ chối - fixture đã assert, đây là chỗ nói ra.

    Lần nạp thật phải ra 40 tài liệu NẠP và 0 file bị từ chối; nếu một file
    hỏng frontmatter thì phải biết ở CI, không phải sau khi đã trả tiền.
    """
    assert len(nguon) == SO_TAI_LIEU
    assert all(t.noi_dung.strip() for t in nguon.values())


def test_them_file_chua_khai_la_do(bang, nguon):
    """Hàng "Thêm file chưa khai": file thứ 41 phải bị nêu tên."""
    them = dict(nguon)
    them["z-99-chua-khai.md"] = TaiLieuNguon(
        doc_key="z-99-chua-khai.md", scope="noi_bo", content_type="faq", noi_dung="x"
    )
    loi = doi_chieu(bang, them)
    assert any("z-99-chua-khai.md" in d and "chưa có mục" in d for d in loi), loi


def test_muc_khai_ma_thieu_file_la_do(bang, nguon):
    """Hàng "Mục khai mà thiếu file": mục thiếu phải bị nêu tên."""
    bo = dict(nguon)
    mat = bang["tai_lieu"][0]["ten"]
    del bo[mat]
    loi = doi_chieu(bang, bo)
    assert any(mat in d and "không có file" in d for d in loi), loi


def test_frontmatter_lech_bang_la_do(bang, nguon):
    """Hàng "Frontmatter lệch bảng": thông điệp phải nêu **hai** giá trị."""
    ten = bang["tai_lieu"][0]["ten"]
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
    """Hàng "Loại nội dung gõ sai": `runbok` phải đỏ ở CI, kèm bảng hạng.

    Cửa quét không whitelist `content_type` nên ca này chỉ có một chỗ bắt được
    trước khi tiêu tiền, và đó là đây.
    """
    hang = set(tai_hang_do_nhay(HANG_MAC_DINH).hang)
    go_sai = dict(nguon)
    ten = bang["tai_lieu"][0]["ten"]
    goc = go_sai[ten]
    go_sai[ten] = TaiLieuNguon(
        doc_key=goc.doc_key, scope=goc.scope, content_type="runbok", noi_dung=goc.noi_dung
    )
    assert "runbok" not in hang
    loi = doi_chieu(bang, go_sai)
    assert any(ten in d and "runbok" in d for d in loi), loi
    la = sorted({t.content_type for t in go_sai.values()} - hang)
    assert la == ["runbok"], f"loại lạ so với bảng hạng {sorted(hang)}"


# ---------------------------------------------------------------------------
# Hình dạng corpus
# ---------------------------------------------------------------------------


def test_dem_21_loi_va_19_nhieu(bang):
    vai_tro = [m["vai_tro"] for m in bang["tai_lieu"]]
    assert vai_tro.count("loi") == SO_LOI
    assert vai_tro.count("nhieu") == SO_NHIEU


def test_ba_kich_ban_deu_co_tai_lieu_loi(bang):
    """Ba kịch bản của A8: web sập, đầy ổ cứng, SSL. Mỗi cái phải có tài liệu thật."""
    khai = [k["id"] for k in bang["kich_ban"] if k["id"] != KICH_BAN_NHIEU]
    assert len(khai) == 3, khai
    for kb in khai:
        so = [m for m in bang["tai_lieu"] if m["kich_ban"] == kb]
        assert so, f"kịch bản {kb} không có tài liệu nào"


def test_ba_scope_va_it_nhat_hai_khach_hang(bang):
    """RT-01 chỉ thử được nếu corpus có tài liệu ở **cả hai** scope khách hàng.

    Biên cách ly là `devops` chạm `khach_hang_a` chứ không chạm `khach_hang_b`
    (`config/policy-toi-gian.yaml`), nên `khach_hang_b` rỗng là kịch bản đỏ ở T3
    không có gì để chạy.
    """
    co = {m["scope"] for m in bang["tai_lieu"]}
    assert co == SCOPE_HOP_LE
    assert len(co & SCOPE_KHACH_HANG) >= 2
    for scope in SCOPE_HOP_LE:
        assert [m for m in bang["tai_lieu"] if m["scope"] == scope], scope


def test_moi_tai_lieu_dung_mot_scope_don_tri(nguon):
    """AD-4: scope đơn trị mỗi tài liệu; frontmatter chỉ có một giá trị."""
    for t in nguon.values():
        assert t.scope in SCOPE_HOP_LE
        assert filter_key(t.scope, t.content_type).count(":") == 1


def test_phu_du_12_loai_tai_lieu_cua_a8(bang):
    co = {m["content_type"] for m in bang["tai_lieu"]}
    thieu = sorted(LOAI_A8 - co)
    assert not thieu, f"loại tài liệu của A8 không có trong corpus: {thieu}"


def test_bien_cach_ly_khach_hang_co_ca_tai_lieu_han_che_nhat(bang):
    """`khach_hang_b` phải có ít nhất một tài liệu hạng cao nhất.

    Ca thử của RT-01 chỉ có nghĩa khi thứ nằm sau biên là thứ đáng giá; một
    `khach_hang_b` chỉ toàn FAQ không chứng minh được gì.
    """
    hang = tai_hang_do_nhay(HANG_MAC_DINH).hang
    cao_nhat = max(hang.values())
    cua_b = [m for m in bang["tai_lieu"] if m["scope"] == "khach_hang_b"]
    assert any(hang[m["content_type"]] == cao_nhat for m in cua_b)


def test_khong_trung_doc_key_voi_bo_vang():
    """`doc_key` là tên file và sổ tài liệu tra theo nó; corpus và bộ vàng cùng space `synth`.

    Trùng tên là re-ingest ghi đè một tài liệu bộ vàng bằng một tài liệu corpus.
    """
    bo_vang = {p.name for p in cac_file_nap(GOC_REPO / "eval" / "data")}
    corpus = {m["ten"] for m in doc_bang()["tai_lieu"]}
    assert bo_vang & corpus == set()


# ---------------------------------------------------------------------------
# Ràng buộc kiến trúc
# ---------------------------------------------------------------------------


def test_moi_loai_cua_corpus_deu_co_hang_do_nhay(bang):
    """Hàng "Bảng hạng thiếu loại của corpus": ingest từ chối **cả lô** nếu thiếu."""
    hang = set(tai_hang_do_nhay(HANG_MAC_DINH).hang)
    thieu = sorted({m["content_type"] for m in bang["tai_lieu"]} - hang)
    assert not thieu, f"loại nội dung của corpus chưa có hạng độ nhạy: {thieu}"


def test_hai_loai_cung_hang_thi_loader_tu_choi_ca_file(tmp_path):
    """Hàng "Hai loại cùng hạng": `SensitivityRanksInvalid`, không chạy bảng nửa vời."""
    f = tmp_path / "hang.yaml"
    f.write_text(
        "version: 1\nranks:\n  runbook: 10\n  sop: 10\n", encoding="utf-8"
    )
    with pytest.raises(SensitivityRanksInvalid) as loi:
        tai_hang_do_nhay(f)
    assert loi.value.code == "SENSITIVITY_RANKS_INVALID"


def test_so_khoa_loc_moi_vai_duoi_tran_ad4(bang):
    """AD-4: vai vượt 50 khóa buộc đo lại recall/độ trễ trước khi tiến.

    Khóa lọc là `{scope}:{content_type}`, nên số khóa của một vai là số cặp
    (scope vai đó chạm × loại nội dung có mặt trong scope đó). Đếm trên corpus
    thật cộng bộ vàng, vì hai bộ nằm chung space `synth`.
    """
    from eval.bo_vang import doc_bo_vang

    theo_scope: dict[str, set[str]] = {}
    for m in bang["tai_lieu"]:
        theo_scope.setdefault(m["scope"], set()).add(m["content_type"])
    for t in doc_bo_vang().tai_lieu:
        theo_scope.setdefault(t.scope, set()).add(t.content_type)

    policy = load_policy(POLICY_TOI_GIAN)
    dem = {
        ten: sum(len(theo_scope.get(s, set())) for s in vai.scopes)
        for ten, vai in policy.roles.items()
    }
    assert dem, "bảng chính sách phải có ít nhất một vai"
    nhieu_nhat = max(dem.values())
    assert nhieu_nhat < TRAN_KHOA_MOI_VAI, dem


def test_so_dinh_hyperedge_demo_ghim_dung_con_so_da_chot(bang):
    """Giả định 6.3.4 đóng bằng **một** số đếm trên đồ thị đã nạp thật: 8 đỉnh.

    Kỳ vọng viết tay, không phải "một số nguyên dương": hai ứng viên của giả
    định là 5 và 6, nên luật lỏng cho phép đổi số mà vẫn xanh - tức cho phép mở
    lại một giả định đã đóng mà không ai thấy. Đổi số này nghĩa là phải đếm lại
    trên đồ thị đã nạp thật và sửa PRD trong cùng một commit.

    Số đo được là 8 chứ không phải một trong hai ứng viên, vì hyperedge demo
    điền đủ cả 8 vai slot. Nó là số của **một cấu hình trích xuất cụ thể**, không
    phải hằng số của lược đồ: hyperedge thứ hai của cùng tài liệu chỉ 4 đỉnh, và
    bản `k1-03` trước khi sửa cho khớp bộ vàng ra hai hyperedge 5 đỉnh. Độ nhạy
    đó có khoản ledger riêng.
    """
    assert bang["so_dinh_hyperedge_demo"] == SO_DINH_HYPEREDGE_DEMO
    assert isinstance(bang["so_dinh_hyperedge_demo"], int)
    assert not isinstance(bang["so_dinh_hyperedge_demo"], bool)


def test_prd_muc_luc_gia_dinh_mang_dung_con_so_do():
    """Con số phải ghi ở **hai** chỗ và hai chỗ phải nói cùng một điều.

    Bảng thiết kế là nơi harness đọc, PRD là nơi hội đồng đọc; hai bên lệch nhau
    thì một trong hai đang nói sai mà không có gì đỏ.
    """
    khoan = [
        d
        for d in PRD.read_text(encoding="utf-8").splitlines()
        if d.startswith("4. Số đỉnh của hyperedge demo")
    ]
    assert len(khoan) == 1, "PRD phải có đúng một khoản 4 trong mục lục giả định 6.3"
    assert f"{SO_DINH_HYPEREDGE_DEMO} đỉnh" in khoan[0], khoan[0]
    assert "ĐÃ CHỐT" in khoan[0], "khoản 4 phải ghi rõ giả định đã đóng"


def test_moi_kich_ban_dung_bay_tai_lieu_loi(bang):
    """21 lõi chia đều ba kịch bản.

    Không có luật này thì một kịch bản co lại còn 3 tài liệu trong khi kịch bản
    khác phình ra vẫn giữ tổng 21, và "phủ 3 kịch bản" thành một câu đúng về
    hình thức mà sai về chất liệu.
    """
    dem = {
        k["id"]: len([m for m in bang["tai_lieu"] if m["kich_ban"] == k["id"]])
        for k in bang["kich_ban"]
        if k["id"] != KICH_BAN_NHIEU
    }
    assert set(dem.values()) == {SO_LOI_MOI_KICH_BAN}, dem
    assert sum(dem.values()) == SO_LOI


def test_khoi_kich_ban_du_khoa_va_scope_chinh_hop_le(bang):
    """`doc_bang` đã kiểm; test này là chỗ nói ra luật cho người đọc."""
    for k in bang["kich_ban"]:
        assert set(k) == KHOA_KICH_BAN, k.get("id")
        assert isinstance(k["ten"], str) and k["ten"].strip()
        assert isinstance(k["mo_ta"], str) and k["mo_ta"].strip()
        assert k["scope_chinh"] is None or k["scope_chinh"] in SCOPE_HOP_LE
    ids = [k["id"] for k in bang["kich_ban"]]
    assert len(ids) == len(set(ids)), ids


def test_moi_tai_lieu_ra_dung_mot_chunk(nguon):
    """Một tài liệu dài hơn một chunk là nhiều lời gọi LLM cho một tài liệu.

    Cỡ chunk lấy từ `adapters.chunking` chứ không chép hằng: đổi ba tham số của
    `EngineACL` mà corpus vẫn "đúng một chunk" theo một hằng cũ là một phép đếm
    lời gọi sai ở mọi bảng chi phí sau đó.
    """
    from adapters.chunking import chia_chunk

    nhieu = {ten: len(chia_chunk(t.noi_dung)) for ten, t in nguon.items()}
    assert set(nhieu.values()) == {1}, {k: v for k, v in nhieu.items() if v != 1}


@pytest.mark.parametrize(
    "hong,dau_hieu",
    [
        ({"kich_ban": "web_sap"}, "danh sách"),
        ({"kich_ban": []}, "không rỗng"),
        ({"kich_ban": ["web_sap"]}, "khối ánh xạ"),
        ({"tai_lieu": "k1-01.md"}, "danh sách"),
        ({"tai_lieu": ["k1-01.md"]}, "khối ánh xạ"),
        ({"version": 2}, "version"),
    ],
)
def test_luoc_do_bang_hong_cho_thong_diep_doc_duoc(tmp_path, bang, hong, dau_hieu):
    """Lược đồ hỏng phải là một câu, không phải `KeyError`/`TypeError` giữa chừng."""
    import copy

    raw = copy.deepcopy(bang)
    raw.update(hong)
    dich = tmp_path / "corpus_thiet_ke.yaml"
    dich.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(BangThietKeHong) as loi:
        doc_bang(dich)
    assert dau_hieu in str(loi.value)


def test_kich_ban_thieu_khoa_cho_thong_diep_neu_ten(tmp_path, bang):
    import copy

    raw = copy.deepcopy(bang)
    del raw["kich_ban"][0]["mo_ta"]
    dich = tmp_path / "corpus_thiet_ke.yaml"
    dich.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(BangThietKeHong) as loi:
        doc_bang(dich)
    assert "mo_ta" in str(loi.value) and raw["kich_ban"][0]["id"] in str(loi.value)


def test_scope_chinh_la_bi_tu_choi(tmp_path, bang):
    import copy

    raw = copy.deepcopy(bang)
    raw["kich_ban"][0]["scope_chinh"] = "khach_hang_z"
    dich = tmp_path / "corpus_thiet_ke.yaml"
    dich.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(BangThietKeHong) as loi:
        doc_bang(dich)
    assert "khach_hang_z" in str(loi.value)


def test_content_type_khong_co_hang_duoc_neu_ten_thay_vi_keyerror(bang, nguon):
    """Trước đây `hang[m["content_type"]]` ném `KeyError` ở một test khác."""
    import copy

    hong = copy.deepcopy(bang)
    hong["tai_lieu"][0]["content_type"] = "runbok"
    loi = doi_chieu(hong, nguon)
    assert any("runbok" in d and "hạng độ nhạy" in d for d in loi), loi


def test_mot_fact_o_hai_tai_lieu_van_con_trung_nguyen_van(bang, nguon):
    """Ca "một fact ở hai tài liệu" của I/O Matrix phải còn thật trong thân file.

    Spec, `ghi_chu` của bảng thiết kế và ledger đều dựa vào câu quy định 24 giờ
    trùng nguyên văn giữa SOP-12 và SOP bàn giao ca trực. Không test nào đọc
    thân hai file đó, nên sửa một chữ là ca biến mất trong im lặng - và cùng lúc
    ba tài liệu vẫn khẳng định nó tồn tại.
    """
    sop = sorted(m["ten"] for m in bang["tai_lieu"] if m["content_type"] == "sop")
    assert len(sop) >= 2, sop
    # Tìm trên **mọi** cặp SOP, không chỉ hai file đầu: ca này thuộc về corpus,
    # không thuộc về hai cái tên file cụ thể.
    trung: list[tuple[str, str, str]] = []
    for i, a in enumerate(sop):
        for b in sop[i + 1 :]:
            dong_b = {d.strip() for d in nguon[b].noi_dung.splitlines() if d.strip()}
            for d in nguon[a].noi_dung.splitlines():
                if d.strip() and d.strip() in dong_b:
                    trung.append((a, b, d.strip()))
    assert trung, (
        "không còn câu nào trùng nguyên văn giữa hai tài liệu `sop`:"
        f" ca 'một fact ở hai tài liệu' đã biến mất khỏi corpus ({sop})"
    )
    assert any(len(c) > 40 for _, _, c in trung), (
        f"câu trùng phải là một quy định thật, không phải một dòng ngắn: {trung}"
    )


# ---------------------------------------------------------------------------
# INC-1208: corpus và bộ vàng phải là hai góc nhìn của MỘT sự thật
# ---------------------------------------------------------------------------

# Mã sự cố dùng chung giữa hai bộ. `eval/data/05-...` (scope `noi_bo`, bộ vàng)
# và các tài liệu kịch bản 1 (scope khách hàng) nạp chung space `synth`, nên hai
# bên mô tả cùng một sự cố. Bộ vàng là bên **không đổi được** (nhãn tay đã khóa,
# `cau_nguon` phải còn nguyên văn), nên nó là nguồn của mọi mỏ neo dưới đây.
MA_SU_CO_CHUNG = "INC-1208"
BO_VANG_INC_1208 = GOC_REPO / "eval" / "data" / "05-bao-cao-su-co-inc-1208.txt"

# Giờ trong ngày: `09:20` hoặc `21 giờ 05`. Cố ý **không** bắt "24 giờ" hay
# "40 phút" - đó là khoảng thời gian, không phải mốc, và bắt nhầm chúng làm test
# đỏ vì một câu đúng.
_GIO = re.compile(r"\b(\d{1,2})\s*(?::|giờ\s+)(\d{2})\b")


@dataclass(frozen=True)
class MoNeo:
    """Ba mỏ neo của INC-1208, đọc từ bộ vàng chứ không chép cứng vào test."""

    bat_dau: str
    phuc_hoi: str
    nguoi_phu_trach: str
    phut_bat_dau: int
    phut_phuc_hoi: int


def doc_mo_neo(duong_dan: Path = BO_VANG_INC_1208) -> MoNeo:
    """Rút ba mỏ neo khỏi thân tài liệu vàng; thân đổi thì mỏ neo đổi theo.

    Đọc chứ không chép: chép cứng "09:20" vào test nghĩa là sửa bộ vàng xong thì
    corpus vẫn xanh trong khi nó đã nói ngược lại bộ vàng - đúng cái lỗi mà test
    này sinh ra để chặn.
    """
    than = duong_dan.read_text(encoding="utf-8")
    gio = _GIO.findall(than)
    assert len(gio) >= 2, f"bộ vàng phải nêu ít nhất giờ bắt đầu và giờ phục hồi: {gio}"
    phut = [int(h) * 60 + int(m) for h, m in gio]
    i_dau, i_cuoi = phut.index(min(phut)), phut.index(max(phut))
    ten = re.search(r"Người phụ trách xử lý sự cố là ([^,\.]+)", than)
    assert ten, "bộ vàng phải nêu người phụ trách xử lý sự cố"
    return MoNeo(
        bat_dau=f"{int(gio[i_dau][0]):02d}:{gio[i_dau][1]}",
        phuc_hoi=f"{int(gio[i_cuoi][0]):02d}:{gio[i_cuoi][1]}",
        nguoi_phu_trach=ten.group(1).strip(),
        phut_bat_dau=min(phut),
        phut_phuc_hoi=max(phut),
    )


@pytest.fixture(scope="module")
def mo_neo() -> MoNeo:
    return doc_mo_neo()


def _tai_lieu_nhac_su_co(nguon: dict[str, TaiLieuNguon]) -> dict[str, TaiLieuNguon]:
    return {k: v for k, v in nguon.items() if MA_SU_CO_CHUNG in v.noi_dung}


def test_mo_neo_doc_duoc_tu_bo_vang(mo_neo):
    """Nếu phép rút mỏ neo hỏng thì hai test dưới xanh vì lý do sai."""
    assert mo_neo.phut_phuc_hoi > mo_neo.phut_bat_dau
    assert mo_neo.nguoi_phu_trach
    assert MA_SU_CO_CHUNG in BO_VANG_INC_1208.read_text(encoding="utf-8")


def test_corpus_nhac_inc_1208_mang_du_ba_mo_neo_cua_bo_vang(nguon, mo_neo):
    """Cùng một mã sự cố ở hai scope thì phải là cùng một sự thật.

    Trước story 2.8 corpus ghi INC-1208 phục hồi lúc 21 giờ 05 do một người khác
    xử lý, trong khi bộ vàng ghi 10:00 và Trần Thị Hạnh - hai sự thật cùng một
    mã, nạp chung space `synth`.
    """
    nhac = _tai_lieu_nhac_su_co(nguon)
    assert len(nhac) >= 3, f"kịch bản 1 phải có nhiều hơn một tài liệu nhắc {MA_SU_CO_CHUNG}"
    thieu = {
        ten: [
            neo
            for neo in (mo_neo.bat_dau, mo_neo.phuc_hoi, mo_neo.nguoi_phu_trach)
            if neo not in t.noi_dung
        ]
        for ten, t in nhac.items()
    }
    assert not {k: v for k, v in thieu.items() if v}, thieu


def test_moc_gio_cua_tai_lieu_inc_1208_nam_trong_khung_su_co(nguon, mo_neo):
    """Mốc log ngoài khung là bằng chứng nói ngược chính báo cáo mà nó chống lưng."""
    ngoai: dict[str, list[str]] = {}
    for ten, t in _tai_lieu_nhac_su_co(nguon).items():
        for h, m in _GIO.findall(t.noi_dung):
            if not mo_neo.phut_bat_dau <= int(h) * 60 + int(m) <= mo_neo.phut_phuc_hoi:
                ngoai.setdefault(ten, []).append(f"{h}:{m}")
    assert not ngoai, (
        f"mốc giờ ngoài khung {mo_neo.bat_dau}-{mo_neo.phuc_hoi} của bộ vàng: {ngoai}"
    )


def test_cmdb_cua_app01_ghi_dung_nguoi_phu_trach_cua_bo_vang(bang, nguon, mo_neo):
    """Bản ghi CMDB là nơi mọi tài liệu khác tra tên, nên nó phải mang đúng tên đó.

    Tìm tài liệu qua bảng thiết kế (kịch bản `web_sap`, loại `cmdb`) chứ không
    chép tên file: đổi tên file mà quên test là test lặng lẽ không canh gì.
    """
    cmdb = [
        m["ten"]
        for m in bang["tai_lieu"]
        if m["kich_ban"] == "web_sap" and m["content_type"] == "cmdb"
    ]
    assert len(cmdb) == 1, cmdb
    assert mo_neo.nguoi_phu_trach in nguon[cmdb[0]].noi_dung
