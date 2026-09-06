"""Loader từ điển thực thể: lược đồ, ràng scope và bốn phép từ chối (story 2.12).

Test viết trước cơ chế (FR-27). Bốn ca từ chối của I/O Matrix có mặt ở đây, và
mỗi ca assert trên `code` chứ không trên thông điệp (AD-8) - nhưng cũng assert
rằng thông điệp **nêu tên mục** gây lỗi, vì một từ điển vài trăm dòng do người
sửa dần thì "có xung đột" mà không nói ở đâu là một thông điệp không dùng được.

Không test nào chạm kho, gọi LLM hay đọc file trong `config/`: mọi từ điển ở đây
viết ra `tmp_path`.
"""

import pytest

from adapters.tu_dien_thuc_the import (
    ENTITY_DICTIONARY_KEY,
    SCOPE_CHUNG,
    TuDienThucTheInvalid,
    tai_tu_dien_thuc_the,
    tu_dien_cho,
)
from core.facts import ap_bi_danh


def _ghi(tmp_path, noi_dung: str, ten: str = "td.yaml"):
    p = tmp_path / ten
    p.write_text(noi_dung, encoding="utf-8")
    return p


HOP_LE = """
version: 1
muc:
  - chuan: App01
    scope: khach_hang_a
    bi_danh: [app01.company.vn, APP-01, app-01]
    xac_nhan: "sonlm 2026-09-05"
  - chuan: Phòng IT
    scope: "*"
    bi_danh: [phòng IT]
    xac_nhan: "sonlm 2026-09-05"
"""


# ---------------------------------------------------------------------------
# Lược đồ và hình dạng
# ---------------------------------------------------------------------------


def test_nap_duoc_mot_tu_dien_hop_le(tmp_path):
    td = tai_tu_dien_thuc_the(_ghi(tmp_path, HOP_LE))
    assert [m.chuan for m in td.muc] == ["App01", "Phòng IT"]
    assert td.muc[0].bi_danh == ("app01.company.vn", "APP-01", "app-01")
    assert td.muc[1].scope == SCOPE_CHUNG
    # `version` là sha256 của chính file: hai file khác một dấu cách là hai từ
    # điển khác nhau, cùng luật với `policy_version` và bảng hạng độ nhạy.
    assert len(td.version) == 64


def test_version_la_sha256_cua_file(tmp_path):
    a = tai_tu_dien_thuc_the(_ghi(tmp_path, HOP_LE, "a.yaml"))
    b = tai_tu_dien_thuc_the(_ghi(tmp_path, HOP_LE + "\n", "b.yaml"))
    assert a.version != b.version


@pytest.mark.parametrize(
    "noi_dung",
    [
        "version: 2\nmuc: []\n",
        "version: 1\nmuc: []\n",
        "version: 1\n",
        "version: 1\nmuc: {}\n",
        "version: 1\nmuc: [1]\n",
        "version: 1\nmuc: []\nla: 1\n",
        "- a\n- b\n",
        ": :\n  x\n",
    ],
)
def test_moi_cach_hong_ve_luoc_do_cho_mot_loai_loi(tmp_path, noi_dung):
    """Một loại lỗi cho mọi cách hỏng: phản ứng đúng cho tất cả là sửa file."""
    with pytest.raises(TuDienThucTheInvalid) as e:
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    assert e.value.code == "TU_DIEN_THUC_THE_INVALID"


def test_file_thieu_cung_mot_loai_loi(tmp_path):
    with pytest.raises(TuDienThucTheInvalid) as e:
        tai_tu_dien_thuc_the(tmp_path / "khong-co.yaml")
    assert e.value.code == "TU_DIEN_THUC_THE_INVALID"


def test_khoa_trung_trong_mot_muc_bi_tu_choi(tmp_path):
    """Mặc định của YAML là lấy bản cuối; ở đây một tên chuẩn biến mất im lặng."""
    noi_dung = """
version: 1
muc:
  - chuan: A
    chuan: B
    scope: noi_bo
    bi_danh: [a]
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid) as e:
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    assert e.value.code == "TU_DIEN_THUC_THE_INVALID"


def test_khoa_la_trong_mot_muc_bi_tu_choi(tmp_path):
    """`bidanh:` viết thiếu chữ mà file vẫn nạp được là một mục không gộp gì."""
    noi_dung = """
version: 1
muc:
  - chuan: A
    scope: noi_bo
    bi_danh: [a]
    xac_nhan: "sonlm 2026-09-05"
    ghi_chu: gì đó
"""
    with pytest.raises(TuDienThucTheInvalid, match="khóa lạ"):
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))


def test_bi_danh_rong_bi_tu_choi(tmp_path):
    noi_dung = """
version: 1
muc:
  - chuan: A
    scope: noi_bo
    bi_danh: []
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid, match="không gộp gì"):
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))


def test_scope_chua_dau_phan_tach_bi_tu_choi(tmp_path):
    """`noi_bo:runbook` làm scope thì không bao giờ khớp scope tách từ khóa lọc."""
    noi_dung = """
version: 1
muc:
  - chuan: A
    scope: "noi_bo:runbook"
    bi_danh: [a]
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid, match="dấu phân tách"):
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))


def test_gia_tri_dai_hon_gioi_han_slot_bi_tu_choi(tmp_path):
    """Giá trị dài hơn `GIA_TRI_TOI_DA` bị `kiem_fact` loại, nên nó không bao giờ
    tra trúng bảng - một mục như thế là một mục chết."""
    dai = "x" * 400
    noi_dung = f"""
version: 1
muc:
  - chuan: A
    scope: noi_bo
    bi_danh: ["{dai}"]
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid, match="quá"):
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))


# ---------------------------------------------------------------------------
# Bốn phép từ chối của I/O Matrix
# ---------------------------------------------------------------------------


def test_muc_thieu_dau_xac_nhan_bi_tu_choi_kem_ten_muc(tmp_path):
    """I/O Matrix: "Mục thiếu dấu xác nhận" -> từ chối nạp kèm tên mục."""
    noi_dung = """
version: 1
muc:
  - chuan: App01
    scope: khach_hang_a
    bi_danh: [app01.company.vn]
"""
    with pytest.raises(TuDienThucTheInvalid) as e:
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    assert e.value.code == "TU_DIEN_THUC_THE_INVALID"
    assert "App01" in str(e.value)
    assert "xac_nhan" in str(e.value)


def test_xac_nhan_rong_cung_la_thieu_dau_xac_nhan(tmp_path):
    """`xac_nhan: ""` không phải một dấu xác nhận, chỉ là một khóa có mặt."""
    noi_dung = """
version: 1
muc:
  - chuan: App01
    scope: khach_hang_a
    bi_danh: [app01.company.vn]
    xac_nhan: "  "
"""
    with pytest.raises(TuDienThucTheInvalid, match="xac_nhan"):
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))


def test_mot_bi_danh_hai_ten_chuan_bi_tu_choi_kem_cap_xung_dot(tmp_path):
    """I/O Matrix: "Một bí danh hai tên chuẩn" -> từ chối kèm cặp xung đột."""
    noi_dung = """
version: 1
muc:
  - chuan: App01
    scope: khach_hang_a
    bi_danh: [app01]
    xac_nhan: "sonlm 2026-09-05"
  - chuan: Ứng dụng 01
    scope: khach_hang_a
    bi_danh: [app01]
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid) as e:
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    assert e.value.code == "TU_DIEN_THUC_THE_INVALID"
    assert "App01" in str(e.value) and "Ứng dụng 01" in str(e.value)
    assert "app01" in str(e.value)


def test_mot_bi_danh_hai_ten_chuan_van_xung_dot_qua_scope_chung(tmp_path):
    """Một mục `*` và một mục scope thật cùng áp lên một tài liệu.

    Bỏ qua ca này là để hai mục mâu thuẫn cùng chạy và kết quả phụ thuộc thứ tự
    duyệt - đúng thứ luật "bảng phải là một hàm" cấm.
    """
    noi_dung = """
version: 1
muc:
  - chuan: App01
    scope: "*"
    bi_danh: [app01]
    xac_nhan: "sonlm 2026-09-05"
  - chuan: Ứng dụng 01
    scope: khach_hang_a
    bi_danh: [app01]
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid, match="hai tên chuẩn"):
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))


def test_hai_scope_khac_nhau_dung_chung_mot_bi_danh_thi_khong_sao(tmp_path):
    """`web01` của khách A và `web01` của khách B là hai thực thể, không xung đột.

    Đây là nửa còn lại của luật ràng theo scope: nó phải **cho phép** cùng một
    chuỗi mang hai nghĩa ở hai khoang thuê bao, chứ không chỉ cấm gộp chúng.
    """
    noi_dung = """
version: 1
muc:
  - chuan: Web01 của A
    scope: khach_hang_a
    bi_danh: [web01]
    xac_nhan: "sonlm 2026-09-05"
  - chuan: Web01 của B
    scope: khach_hang_b
    bi_danh: [web01]
    xac_nhan: "sonlm 2026-09-05"
"""
    td = tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    assert td.bang_cho_scope("khach_hang_a") == {"web01": "Web01 của A"}
    assert td.bang_cho_scope("khach_hang_b") == {"web01": "Web01 của B"}


def test_bi_danh_cung_la_ten_chuan_bi_tu_choi(tmp_path):
    """I/O Matrix: "Bí danh cũng là tên chuẩn" -> từ chối; phép áp đúng một bước."""
    noi_dung = """
version: 1
muc:
  - chuan: App01
    scope: noi_bo
    bi_danh: [app01]
    xac_nhan: "sonlm 2026-09-05"
  - chuan: app01
    scope: noi_bo
    bi_danh: [ứng dụng 01]
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid) as e:
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    assert e.value.code == "TU_DIEN_THUC_THE_INVALID"
    assert "một bước" in str(e.value)


def test_muc_tu_lay_ten_chuan_cua_minh_lam_bi_danh_bi_tu_choi(tmp_path):
    """Ca riêng của luật trên, cấm vì một luật đọc được đáng hơn một ngoại lệ."""
    noi_dung = """
version: 1
muc:
  - chuan: App01
    scope: noi_bo
    bi_danh: [App01, app-01]
    xac_nhan: "sonlm 2026-09-05"
"""
    with pytest.raises(TuDienThucTheInvalid, match="một bước"):
        tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))


# ---------------------------------------------------------------------------
# Ràng theo scope, và cửa đọc cấu hình
# ---------------------------------------------------------------------------


def test_bang_cho_scope_chi_lay_muc_dung_scope_va_muc_chung(tmp_path):
    td = tai_tu_dien_thuc_the(_ghi(tmp_path, HOP_LE))
    a = td.bang_cho_scope("khach_hang_a")
    b = td.bang_cho_scope("khach_hang_b")
    assert a["app01.company.vn"] == "App01"
    assert a["phòng IT"] == "Phòng IT"
    # Bí danh của khách A **không** áp cho khách B; mục `*` thì áp cho cả hai.
    assert "app01.company.vn" not in b
    assert b["phòng IT"] == "Phòng IT"


def test_scope_none_chi_nhan_muc_chung(tmp_path):
    """Không biết scope thì chỉ mục `*` áp: đoán scope là gộp hai khách hàng."""
    td = tai_tu_dien_thuc_the(_ghi(tmp_path, HOP_LE))
    assert dict(td.bang_cho_scope(None)) == {"phòng IT": "Phòng IT"}


def test_khoa_tra_di_qua_chuan_hoa_gia_tri(tmp_path):
    """Bí danh khai với khoảng trắng thừa vẫn tra trúng giá trị slot đã chuẩn hóa."""
    noi_dung = """
version: 1
muc:
  - chuan: "Phòng   IT"
    scope: noi_bo
    bi_danh: ["  phòng    IT  "]
    xac_nhan: "sonlm 2026-09-05"
"""
    td = tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    bang = td.bang_cho_scope("noi_bo")
    assert bang == {"phòng IT": "Phòng IT"}
    assert ap_bi_danh({"subject": "phòng  IT"}, bang) == {"subject": "Phòng IT"}


def test_tu_dien_cho_tra_none_khi_khong_khai(tmp_path):
    """I/O Matrix: `entity_dictionary_path` rỗng -> không có từ điển, không mặc định."""
    assert tu_dien_cho(None) is None
    assert tu_dien_cho({}) is None
    assert tu_dien_cho({ENTITY_DICTIONARY_KEY: ""}) is None
    assert tu_dien_cho({ENTITY_DICTIONARY_KEY: None}) is None


def test_tu_dien_cho_nap_file_duoc_tro_toi(tmp_path):
    duong_dan = _ghi(tmp_path, HOP_LE)
    td = tu_dien_cho({ENTITY_DICTIONARY_KEY: str(duong_dan)})
    assert td is not None and len(td.muc) == 2


def test_muc_cho_scope_giu_thu_tu_file(tmp_path):
    """Khối prompt đọc theo thứ tự người viết, không theo thứ tự chữ cái."""
    noi_dung = """
version: 1
muc:
  - chuan: Zeta
    scope: noi_bo
    bi_danh: [zeta cu]
    xac_nhan: "sonlm 2026-09-05"
  - chuan: Alpha
    scope: noi_bo
    bi_danh: [alpha cu]
    xac_nhan: "sonlm 2026-09-05"
"""
    td = tai_tu_dien_thuc_the(_ghi(tmp_path, noi_dung))
    assert [m.chuan for m in td.muc_cho_scope("noi_bo")] == ["Zeta", "Alpha"]


# ---------------------------------------------------------------------------
# Từ điển đang chạy của space `synth`
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

GOC_REPO = Path(__file__).resolve().parent.parent
TU_DIEN_SYNTH = GOC_REPO / "config" / "tu-dien-thuc-the" / "synth.yaml"


def test_tu_dien_synth_nap_duoc_va_moi_muc_co_dau_xac_nhan():
    """File cấu hình thật phải qua được chính loader của nó.

    Một bảng cấu hình có commit mà không test nào nạp thử là một bảng chỉ hỏng
    lúc đợt nạp đã bắt đầu tiêu tiền.
    """
    td = tai_tu_dien_thuc_the(TU_DIEN_SYNTH)
    assert len(td.muc) == 5
    assert all(m.xac_nhan.strip() for m in td.muc)
    # Không mục nào mang scope chung: cả năm mục đều nói về một scope cụ thể.
    assert {m.scope for m in td.muc} == {"noi_bo", "khach_hang_b", "khach_hang_a"}


def test_bi_danh_cua_hai_tai_lieu_bi_danh_deu_tra_trung_bang():
    """`k1-08` và `k1-09` là ca FR-32 đọc được ngay trong repo (story 2.12).

    Hai tài liệu gọi cùng một máy chủ bằng hai cách viết, ở hai loại nội dung
    nằm hai bên ngưỡng nhạy cảm. Test này chấm đúng điều làm cho ca đó có nghĩa:
    cả hai cách viết tra trúng bảng của **đúng scope** đó, và cùng ra một tên
    chuẩn. Nó không cần kho, không cần ảnh chụp, không cần LLM.
    """
    from core.ingest_scan import quet_thu_muc

    bang = tai_tu_dien_thuc_the(TU_DIEN_SYNTH).bang_cho_scope("khach_hang_a")
    assert bang["app01.company.vn"] == bang["APP-01"] == "App01"

    than = {
        t.doc_key: t.noi_dung
        for t in quet_thu_muc(GOC_REPO / "eval" / "corpus").chap_nhan
    }
    khong_nhay = than["k1-08-troubleshooting-app01-loi-502.md"]
    nhay = than["k1-09-bao-cao-su-co-inc-1611.md"]
    # Mỗi vế chỉ mang **một** cách viết: nếu cả hai cách cùng có ở tài liệu không
    # nhạy cảm thì chuẩn hóa không còn nối được gì mà ca vẫn trông như có nối.
    assert "app01.company.vn" in khong_nhay and "APP-01" not in khong_nhay
    assert "APP-01" in nhay and "app01.company.vn" not in nhay


def test_hai_ve_cua_cap_bi_danh_nam_hai_ben_nguong_nhay_cam():
    """Vế nhạy cảm hạng >= 20, vế không nhạy cảm hạng < 20, và **cùng scope**.

    Cùng scope là điều kiện bắt buộc từ 05/09/2026: phép lộ của Composition-Risk
    đã siết theo scope (mục bổ sung ADR-012), nên một cặp bí danh bắc qua hai
    scope không nhích được tỷ lệ 3 dù có gộp.
    """
    import yaml as _yaml

    from adapters.sensitivity_loader import DUONG_DAN_MAC_DINH, tai_hang_do_nhay
    from eval.ty_le_n_ngoi import NGUONG_NHAY_CAM

    hang = tai_hang_do_nhay(DUONG_DAN_MAC_DINH).hang
    bang = _yaml.safe_load(
        (GOC_REPO / "eval" / "corpus_thiet_ke.yaml").read_text(encoding="utf-8")
    )
    muc = {m["ten"]: m for m in bang["tai_lieu"]}
    a = muc["k1-08-troubleshooting-app01-loi-502.md"]
    b = muc["k1-09-bao-cao-su-co-inc-1611.md"]
    assert a["scope"] == b["scope"] == "khach_hang_a"
    assert hang[a["content_type"]] < NGUONG_NHAY_CAM <= hang[b["content_type"]]


# ---------------------------------------------------------------------------
# Quy ước "một space, một file từ điển" ở `api/`
# ---------------------------------------------------------------------------


def test_quy_uoc_tu_dien_theo_ten_space(tmp_path):
    """`config/tu-dien-thuc-the/<space>.yaml` nếu có, không thì **không** từ điển.

    Quy ước sống ở `api/dot_nap.py` chứ không ở `adapters/`: tầng adapter giữ
    luật "khóa cấu hình vắng nghĩa là không có từ điển, không có mặc định ngầm",
    còn đây là chỗ *một* quy ước của repo được áp cho **cả hai lối vào** - CLI
    `api.do_chi_phi` và màn nạp web đều đi qua `chay_lan_nap`. Một cờ chỉ có ở
    CLI nghĩa là màn web nạp cùng tài liệu đó ra id entity khác.
    """
    from api.dot_nap import duong_dan_tu_dien

    (tmp_path / "synth.yaml").write_text("version: 1\n", encoding="utf-8")
    assert duong_dan_tu_dien("synth", tmp_path) == tmp_path / "synth.yaml"
    assert duong_dan_tu_dien("khao_sat", tmp_path) is None
    # Không biết space thì không đoán: đoán một từ điển cho một space không tên
    # là đúng thứ luật ràng-theo-scope cấm.
    assert duong_dan_tu_dien(None, tmp_path) is None
    assert duong_dan_tu_dien("", tmp_path) is None


def test_space_synth_co_tu_dien_ba_space_kia_thi_khong():
    """Trạng thái thật của repo, và nó là một khẳng định chứ không một sự tình cờ.

    `synth` có bảng đã xác nhận. `khao_sat` chưa có ai gom và xác nhận bí danh
    cho nó. `that_khu` và `real` thì từ điển của chúng là **nội dung tài liệu
    công ty** nên nó không bao giờ được nằm trong `config/` (cùng luật với bảng
    bí danh của story 2.11); một file `that_khu.yaml` xuất hiện ở đây là một lỗ
    rò, không phải một tiến bộ.
    """
    from api.dot_nap import duong_dan_tu_dien

    assert duong_dan_tu_dien("synth") is not None
    for space in ("khao_sat", "that_khu", "real"):
        assert duong_dan_tu_dien(space) is None, space


# ---------------------------------------------------------------------------
# Đường `space` -> `entity_dictionary_path` -> engine
# ---------------------------------------------------------------------------
#
# Ba test dưới đây có mặt vì vòng review 05/09 chứng minh được rằng bỏ
# `space=space` ở `api/dot_nap.py::chay_lan_nap`, hoặc bỏ hẳn tham số
# `entity_dictionary_path=` ở `dung_engine_tu_moi_truong`, thì **cả bộ test vẫn
# xanh**. Nghĩa là toàn bộ cơ chế FR-32 ngắt được mà không chỗ nào đỏ: đợt nạp
# chạy không từ điển và mọi con số vẫn "đúng" theo test.


class _LLMTrong:
    """Hàm LLM giả tối thiểu, chỉ để `EngineACL` dựng được."""

    def __init__(self):
        self.prompts: list[str] = []

    async def __call__(self, prompt, system_prompt=None, **kwargs):
        self.prompts.append(prompt)
        return '{"facts": []}'


def test_engine_that_su_nhan_duong_dan_tu_dien_cua_space(monkeypatch, tmp_path):
    """Chấm **giá trị trên engine thật**, không chấm việc hàm chạy xong.

    Gọi chính `api.dot_nap.dung_engine_tu_moi_truong` chứ không dựng một bản
    giả: đây là chỗ duy nhất quan sát được cả đường `space` -> quy ước tên file
    -> field `entity_dictionary_path` -> `asdict(self)` -> `trich_xuat_chunks`.
    Bỏ `space=space` ở `chay_lan_nap`, hay bỏ hẳn tham số
    `entity_dictionary_path=` ở hàm dựng engine, đều làm test này đỏ - trước
    vòng review 05/09 cả hai phép bỏ đó đi qua mà cả bộ test vẫn xanh.
    """
    import api.dot_nap as mod
    from adapters.llm_wrapper import HamModel
    from tests.gia_lap_llm import SoAuditBoNho
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import embedding_boc, llm_boc

    so_audit = SoAuditBoNho()
    monkeypatch.setattr(
        mod,
        "ham_tu_moi_truong",
        lambda audit: HamModel(
            llm=llm_boc(_LLMTrong(), so_audit),
            embedding=embedding_boc(so_audit),
            llm_max_token=8192,
        ),
    )
    # Hai khe tiêm kết nối là **field** của `EngineACL`, nên chúng đi vào qua
    # chính dict mà `cau_hinh_kho_tu_moi_truong` trả về - không phải sửa hàm
    # dựng engine để test chạy được.
    client, driver = QdrantGhiLai(), Neo4jGhiLai()
    monkeypatch.setattr(
        mod,
        "cau_hinh_kho_tu_moi_truong",
        lambda: {
            "working_dir": str(tmp_path),
            "tao_qdrant_client": lambda: client,
            "tao_neo4j_driver": lambda: driver,
        },
    )

    def dung(space):
        return mod.dung_engine_tu_moi_truong(so_audit, space=space)

    e = dung("synth")
    assert e.entity_dictionary_path == str(TU_DIEN_SYNTH)
    # Và giá trị đó thật sự nạp được thành một từ điển qua cửa của adapter.
    assert tu_dien_cho({ENTITY_DICTIONARY_KEY: e.entity_dictionary_path}) is not None

    e2 = dung("khao_sat")
    assert e2.entity_dictionary_path is None
    assert tu_dien_cho({ENTITY_DICTIONARY_KEY: e2.entity_dictionary_path}) is None

    # Không truyền `space` thì engine chạy **không** từ điển: đó là hành vi
    # trước story 2.12, và nó phải là một lựa chọn tường minh chứ không một
    # nhánh đoán.
    assert mod.dung_engine_tu_moi_truong(so_audit).entity_dictionary_path is None


def test_duong_dan_tu_dien_di_qua_validate_space():
    """`space` đi thẳng vào một đường dẫn, nên nó phải qua cửa hình dạng của `core/`.

    `--space ../../etc` mà không kiểm là một lệnh nạp đọc được một YAML bất kỳ
    ngoài `config/tu-dien-thuc-the/`.
    """
    import pytest as _pt

    from api.dot_nap import duong_dan_tu_dien

    for xau in ("../khac", "a/b", "synth/../..", "-synth"):
        with _pt.raises(ValueError):
            duong_dan_tu_dien(xau)


def test_phien_ban_tu_dien_di_vao_audit(monkeypatch, tmp_path):
    """`TuDienThucThe.version` phải tới được sự kiện `ingest_doc`.

    Không có nó thì không truy được tài liệu nào nạp bằng từ điển nào, mà đổi từ
    điển là đổi id entity và id hyperedge - tức re-ingest. Cùng vai trò với
    `sensitivity_ranks_version`, và chính `config/tu-dien-thuc-the/synth.yaml`
    khai là nó được ghi vào audit.
    """
    import asyncio

    from core.audit import EVENT_INGEST_DOC
    from tests.ho_tro_ingest import dung_moi_truong, llm_theo_fact, viet_tai_lieu
    from tests.ngu_canh import vai  # noqa: F401 - giữ khuôn import của bộ test

    than = "App01 trả lỗi 502 vì chỉnh sai giới hạn bộ nhớ."
    fact = {"subject": "App01", "symptom": "trả lỗi 502"}
    thu_muc = tmp_path / "nguon"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=than)

    from adapters.ingest import nap_thu_muc
    from adapters.policy_loader import load_policy

    policy = load_policy(GOC_REPO / "config" / "policy-day-du.yaml")
    mt = dung_moi_truong(
        tmp_path / "ws",
        llm_theo_fact({than: [fact]}),
        entity_dictionary_path=str(TU_DIEN_SYNTH),
    )
    asyncio.run(
        nap_thu_muc(
            mt.engine,
            thu_muc,
            space="thu",
            policy_version=policy.policy_version,
            audit=mt.so_audit,
        )
    )
    sk = mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)
    assert sk, "phải có sự kiện ingest_doc"
    ban = tai_tu_dien_thuc_the(TU_DIEN_SYNTH)
    assert sk[0].chi_tiet["entity_dictionary_version"] == ban.version
    assert sk[0].chi_tiet["sensitivity_ranks_version"]


def test_khong_tu_dien_thi_audit_ghi_none_chu_khong_chuoi_rong(tmp_path):
    """"Chạy không từ điển" và "có từ điển mà quên ghi" phải phân biệt được."""
    import asyncio

    from adapters.ingest import nap_thu_muc
    from adapters.policy_loader import load_policy
    from core.audit import EVENT_INGEST_DOC
    from tests.ho_tro_ingest import dung_moi_truong, llm_theo_fact, viet_tai_lieu

    than = "App01 trả lỗi 502 vì chỉnh sai giới hạn bộ nhớ."
    thu_muc = tmp_path / "nguon"
    viet_tai_lieu(thu_muc, "a.md", scope="noi_bo", content_type="runbook", than=than)
    policy = load_policy(GOC_REPO / "config" / "policy-day-du.yaml")
    mt = dung_moi_truong(
        tmp_path / "ws",
        llm_theo_fact({than: [{"subject": "App01", "symptom": "trả lỗi 502"}]}),
    )
    asyncio.run(
        nap_thu_muc(
            mt.engine,
            thu_muc,
            space="thu",
            policy_version=policy.policy_version,
            audit=mt.so_audit,
        )
    )
    sk = mt.so_audit.cac_su_kien(EVENT_INGEST_DOC)
    assert sk[0].chi_tiet["entity_dictionary_version"] is None
