"""Danh mục model YAML và loader (story 2.2): đổi bảng không sửa code.

Cùng kỷ luật với `tests/test_hop_nhat_khoa.py` cho bảng hạng độ nhạy: file
chốt của repo phải nạp được, mọi cách hỏng cho một mã lỗi, và tên model / giá
không có bản thứ hai trong code Python.
"""

import hashlib
import re
from pathlib import Path

import pytest

from adapters.model_catalog import (
    DUONG_DAN_MAC_DINH,
    LOAI_EMBEDDING,
    LOAI_LLM,
    ModelCatalogInvalid,
    ModelUnknown,
    danh_muc_mac_dinh,
    tai_danh_muc_model,
)
from tests.gia_lap_llm import (
    DUONG_DAN_DANH_MUC_GIA,
    MODEL_EMBEDDING_GIA,
    MODEL_LLM_CUC_BO_GIA,
    MODEL_LLM_GIA,
    danh_muc_gia,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

GOC = """\
version: 1
nha_cung_cap:
  ncc:
    cuc_bo: false
    base_url: null
    bien_api_key: NCC_KEY
  local:
    cuc_bo: true
    bien_host: LOCAL_HOST
models:
  m-llm:
    loai: llm
    nha_cung_cap: ncc
    gia_vao_usd_1m: 0.1
    gia_ra_usd_1m: 0.2
    max_token: 1000
  m-emb:
    loai: embedding
    nha_cung_cap: ncc
    gia_vao_usd_1m: 0.01
    gia_ra_usd_1m: 0
    so_chieu: 4
    max_token: 100
"""


def _nap(tmp_path, noi_dung: str):
    f = tmp_path / "dm.yaml"
    f.write_text(noi_dung, encoding="utf-8")
    return tai_danh_muc_model(f)


# --- File chốt của repo ------------------------------------------------------


def test_file_mac_dinh_nap_duoc_va_co_ca_hai_loai():
    dm = danh_muc_mac_dinh()
    loai = {m.loai for m in dm.models.values()}
    assert loai == {LOAI_LLM, LOAI_EMBEDDING}
    for m in dm.models.values():
        assert m.nha_cung_cap in dm.nha_cung_cap
        assert m.cuc_bo == dm.nha_cung_cap[m.nha_cung_cap].cuc_bo
        if m.loai == LOAI_EMBEDDING:
            assert m.so_chieu and m.so_chieu > 0
        else:
            assert m.so_chieu is None
    assert dm.version == hashlib.sha256(DUONG_DAN_MAC_DINH.read_bytes()).hexdigest()


def test_file_mac_dinh_co_nguon_gia_va_ngay_tra_trong_header():
    """Ask-First của spec: giá tra ở đâu, ngày nào, phải nằm ngay trong file."""
    dau = DUONG_DAN_MAC_DINH.read_text(encoding="utf-8").split("version:")[0]
    assert "https://" in dau, "header thiếu nguồn giá"
    assert re.search(r"20\d\d-\d\d-\d\d", dau), "header thiếu ngày tra"


def test_file_mac_dinh_co_provider_cuc_bo_cho_space_real():
    """AD-12: space `real` chỉ gọi provider cục bộ, nên danh mục phải có một."""
    dm = danh_muc_mac_dinh()
    cuc_bo = {ten for ten, n in dm.nha_cung_cap.items() if n.cuc_bo}
    assert cuc_bo, "không có nhà cung cấp cục bộ nào"
    loai_cuc_bo = {m.loai for m in dm.models.values() if m.cuc_bo}
    assert loai_cuc_bo == {LOAI_LLM, LOAI_EMBEDDING}


def test_ten_model_va_gia_khong_nam_trong_code_python():
    """Never của spec: tên model và giá chỉ ở YAML.

    Giá quét theo đúng chuỗi viết trong file (`0.60` chứ không phải `0.6`),
    bỏ `0`; ranh giới số để `0.2` (ngưỡng cosine) không bị nhận nhầm là `0.02`.
    """
    dm = danh_muc_mac_dinh()
    ten_model = set(dm.models)
    van_ban_yaml = DUONG_DAN_MAC_DINH.read_text(encoding="utf-8")
    gia = {
        g for g in re.findall(r"gia_(?:vao|ra)_usd_1m:\s*([0-9.]+)", van_ban_yaml) if float(g) != 0
    }
    assert gia, "danh mục không có giá nào khác 0 để quét"
    for goi in ("core", "adapters", "api"):
        for py in (REPO_ROOT / goi).rglob("*.py"):
            van_ban = py.read_text(encoding="utf-8")
            for ten in ten_model:
                assert f'"{ten}"' not in van_ban and f"'{ten}'" not in van_ban, (
                    f"{py.relative_to(REPO_ROOT)} viết cứng tên model {ten!r}"
                )
            for g in gia:
                assert not re.search(rf"(?<![\d.]){re.escape(g)}(?![\d.])", van_ban), (
                    f"{py.relative_to(REPO_ROOT)} viết cứng đơn giá {g}"
                )


def test_danh_muc_gia_nap_duoc_qua_loader():
    dm = danh_muc_gia()
    assert dm.muc(MODEL_LLM_GIA, loai=LOAI_LLM).cuc_bo is False
    assert dm.muc(MODEL_LLM_CUC_BO_GIA, loai=LOAI_LLM).cuc_bo is True
    assert dm.muc(MODEL_EMBEDDING_GIA, loai=LOAI_EMBEDDING).so_chieu == 8
    assert dm.version == hashlib.sha256(DUONG_DAN_DANH_MUC_GIA.read_bytes()).hexdigest()


# --- Tra cứu và tính chi phí -------------------------------------------------


def test_chi_phi_theo_don_gia_tren_1m_token(tmp_path):
    dm = _nap(tmp_path, GOC)
    m = dm.muc("m-llm")
    assert m.chi_phi_usd(1_000_000, 0) == pytest.approx(0.1)
    assert m.chi_phi_usd(0, 1_000_000) == pytest.approx(0.2)
    assert m.chi_phi_usd(12, 34) == pytest.approx((12 * 0.1 + 34 * 0.2) / 1e6)
    assert m.chi_phi_usd(0, 0) == 0


def test_model_la_hoac_sai_loai_la_model_unknown(tmp_path):
    dm = _nap(tmp_path, GOC)
    with pytest.raises(ModelUnknown) as loi:
        dm.muc("khong-co")
    assert loi.value.code == "MODEL_UNKNOWN"
    with pytest.raises(ModelUnknown) as loi:
        dm.muc("m-emb", loai=LOAI_LLM)
    assert loi.value.code == "MODEL_UNKNOWN"
    assert dm.muc("m-emb").loai == LOAI_EMBEDDING


def test_version_la_sha256_noi_dung_file(tmp_path):
    dm = _nap(tmp_path, GOC)
    assert dm.version == hashlib.sha256(GOC.encode("utf-8")).hexdigest()
    dm2 = _nap(tmp_path, GOC + "\n")
    assert dm2.version != dm.version


# --- Mọi cách hỏng: một mã lỗi -----------------------------------------------


def _thay(goc: str, cu: str, moi: str) -> str:
    assert cu in goc, f"mẫu {cu!r} không có trong file gốc"
    return goc.replace(cu, moi, 1)


HONG = {
    "khoa_goc_la": GOC + "gia: 1\n",
    "version_sai": _thay(GOC, "version: 1", "version: 2"),
    "version_bool": _thay(GOC, "version: 1", "version: true"),
    "version_float": _thay(GOC, "version: 1", "version: 1.0"),
    "loai_khong_phai_chuoi": _thay(GOC, "loai: llm", "loai: [llm]"),
    "provider_khong_phai_chuoi": _thay(GOC, "nha_cung_cap: ncc\n    gia_vao_usd_1m: 0.1", "nha_cung_cap: {a: 1}\n    gia_vao_usd_1m: 0.1"),
    "gia_nan": _thay(GOC, "gia_vao_usd_1m: 0.1", "gia_vao_usd_1m: .nan"),
    "gia_inf": _thay(GOC, "gia_ra_usd_1m: 0.2", "gia_ra_usd_1m: .inf"),
    "khong_co_models": GOC.split("models:")[0],
    "loai_la": _thay(GOC, "loai: llm", "loai: chat"),
    "provider_chua_khai": _thay(GOC, "nha_cung_cap: ncc\n    gia_vao_usd_1m: 0.1", "nha_cung_cap: khac\n    gia_vao_usd_1m: 0.1"),
    "gia_am": _thay(GOC, "gia_vao_usd_1m: 0.1", "gia_vao_usd_1m: -0.1"),
    "gia_bool": _thay(GOC, "gia_vao_usd_1m: 0.1", "gia_vao_usd_1m: true"),
    "gia_chuoi": _thay(GOC, "gia_vao_usd_1m: 0.1", "gia_vao_usd_1m: '0.1'"),
    "thieu_gia_ra": _thay(GOC, "    gia_ra_usd_1m: 0.2\n", ""),
    "embedding_thieu_so_chieu": _thay(GOC, "    so_chieu: 4\n", ""),
    "llm_co_so_chieu": _thay(GOC, "    max_token: 1000\n", "    max_token: 1000\n    so_chieu: 4\n"),
    "so_chieu_khong_duong": _thay(GOC, "so_chieu: 4", "so_chieu: 0"),
    "max_token_khong_nguyen": _thay(GOC, "max_token: 1000", "max_token: 1000.5"),
    "khoa_model_la": _thay(GOC, "    max_token: 1000\n", "    max_token: 1000\n    gia_khac: 1\n"),
    "model_trung": GOC + "  m-llm:\n    loai: llm\n    nha_cung_cap: ncc\n    gia_vao_usd_1m: 1\n    gia_ra_usd_1m: 1\n    max_token: 1\n",
    "provider_api_thieu_bien_key": _thay(GOC, "    bien_api_key: NCC_KEY\n", ""),
    "provider_cuc_bo_thieu_host": _thay(GOC, "    bien_host: LOCAL_HOST\n", ""),
    "provider_cuc_bo_co_key": _thay(GOC, "    bien_host: LOCAL_HOST\n", "    bien_host: LOCAL_HOST\n    bien_api_key: X\n"),
    "cuc_bo_khong_bool": _thay(GOC, "cuc_bo: true", "cuc_bo: yes_please"),
    "model_cuc_bo_co_gia": GOC + "  m-local:\n    loai: llm\n    nha_cung_cap: local\n    gia_vao_usd_1m: 0.5\n    gia_ra_usd_1m: 0\n    max_token: 1\n",
    "yaml_hong": "version: 1\nnha_cung_cap: [\n",
    "goc_khong_phai_bang": "- a\n- b\n",
}


@pytest.mark.parametrize("ten", sorted(HONG))
def test_file_hong_la_model_catalog_invalid(tmp_path, ten):
    with pytest.raises(ModelCatalogInvalid) as loi:
        _nap(tmp_path, HONG[ten])
    assert loi.value.code == "MODEL_CATALOG_INVALID"
    assert "dm.yaml" in str(loi.value)


def test_file_thieu_va_khong_utf8(tmp_path):
    with pytest.raises(ModelCatalogInvalid):
        tai_danh_muc_model(tmp_path / "khong-co.yaml")
    f = tmp_path / "bin.yaml"
    f.write_bytes(b"\xff\xfe version: 1")
    with pytest.raises(ModelCatalogInvalid):
        tai_danh_muc_model(f)


def test_doi_chung_file_goc_cua_bo_hong_nap_duoc(tmp_path):
    """Mọi ca hỏng ở trên đều là một đột biến của một file nạp được."""
    dm = _nap(tmp_path, GOC)
    assert set(dm.models) == {"m-llm", "m-emb"}
    assert dm.nha_cung_cap["local"].cuc_bo is True
    assert dm.nha_cung_cap["ncc"].bien_api_key == "NCC_KEY"


def test_model_cuc_bo_gia_0_hop_le(tmp_path):
    dm = _nap(
        tmp_path,
        GOC + "  m-local:\n    loai: llm\n    nha_cung_cap: local\n    gia_vao_usd_1m: 0\n    gia_ra_usd_1m: 0\n    max_token: 1\n",
    )
    assert dm.muc("m-local").cuc_bo is True
    assert dm.muc("m-local").chi_phi_usd(1000, 1000) == 0


# --- Story 2.4: `extra_body` tùy chọn, chỉ cho nhà cung cấp API ngoài -------------


def test_extra_body_tuy_chon_va_giu_nguyen_hinh_dang(tmp_path):
    dm = _nap(tmp_path, _thay(GOC, "    max_token: 1000\n", "    max_token: 1000\n    extra_body:\n      thinking:\n        type: disabled\n"))
    assert dm.muc("m-llm").extra_body == {"thinking": {"type": "disabled"}}
    assert dm.muc("m-emb").extra_body is None, "model không khai thì không có tham số"
    with pytest.raises(TypeError):
        dm.muc("m-llm").extra_body["thinking"] = {}


def test_extra_body_trong_danh_muc_gia():
    from tests.gia_lap_llm import MODEL_LLM_GIA, MODEL_LLM_TAT_SUY_LUAN_GIA

    dm = danh_muc_gia()
    assert dm.muc(MODEL_LLM_TAT_SUY_LUAN_GIA, loai=LOAI_LLM).extra_body == {"thinking": {"type": "disabled"}}
    assert dm.muc(MODEL_LLM_GIA).extra_body is None


def test_file_mac_dinh_deepseek_tat_suy_luan_bang_extra_body():
    """Tắt suy luận bằng cấu hình, không bằng code (spec 2.4): model DeepSeek khai `thinking.type = disabled`."""
    dm = danh_muc_mac_dinh()
    co = [m for m in dm.models.values() if m.nha_cung_cap == "deepseek" and m.loai == LOAI_LLM]
    assert co, "danh mục không còn model DeepSeek nào"
    for m in co:
        assert m.extra_body == {"thinking": {"type": "disabled"}}
    van_ban = DUONG_DAN_MAC_DINH.read_text(encoding="utf-8")
    assert "thinking_mode" in van_ban, "chú thích phải trỏ nguồn tài liệu DeepSeek"


@pytest.mark.parametrize(
    "ten, noi_dung",
    [
        (
            "provider_cuc_bo_co_extra_body",
            GOC + "  m-local:\n    loai: llm\n    nha_cung_cap: local\n    gia_vao_usd_1m: 0\n"
            "    gia_ra_usd_1m: 0\n    max_token: 1\n    extra_body: {thinking: {type: disabled}}\n",
        ),
        ("extra_body_khong_phai_bang", _thay(GOC, "    max_token: 1000\n", "    max_token: 1000\n    extra_body: [1]\n")),
        ("extra_body_rong", _thay(GOC, "    max_token: 1000\n", "    max_token: 1000\n    extra_body: {}\n")),
        # Vòng review 2.4: chỉ model llm của API ngoài; có *khóa* (kể cả null) ở
        # chỗ khác là từ chối; giá trị phải tuần tự hóa JSON được.
        ("embedding_co_extra_body", GOC + "    extra_body: {thinking: {type: disabled}}\n"),
        (
            "provider_cuc_bo_extra_body_null",
            GOC + "  m-local:\n    loai: llm\n    nha_cung_cap: local\n    gia_vao_usd_1m: 0\n"
            "    gia_ra_usd_1m: 0\n    max_token: 1\n    extra_body: null\n",
        ),
        ("extra_body_khong_json", _thay(GOC, "    max_token: 1000\n", "    max_token: 1000\n    extra_body: {ngay: 2026-09-02}\n")),
    ],
)
def test_extra_body_sai_la_model_catalog_invalid(tmp_path, ten, noi_dung):
    with pytest.raises(ModelCatalogInvalid) as loi:
        _nap(tmp_path, noi_dung)
    assert loi.value.code == "MODEL_CATALOG_INVALID"
