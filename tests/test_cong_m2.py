"""Kịch bản cổng M2 `scripts/cong-m2.sh` (story 3.8): hình dạng script, không chạy nó.

Script chạy trên máy chủ với kho thật và LLM thật (tốn tiền), nên ở đây chỉ canh
những điều đọc được từ văn bản: cú pháp bash, không secret, tên biến mật khẩu
suy từ chính seed, bảy bước có tên, `trap EXIT` hoán về bảng vận hành và cho
grant hết hạn, không gọi `python -m` module nào của dự án (script chỉ nói HTTP
và psql), và câu ghim/câu L0/câu N7 là câu **có thật** trong bộ câu hỏi 2.9.
"""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from api.chinh_sach import ID_MAC_DINH, POLICY_VAN_HANH
from eval.cau_hoi import doc_bo_cau_hoi

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "cong-m2.sh"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_chay_duoc_ve_cu_phap():
    assert SCRIPT.stat().st_mode & 0o111, "script phải có quyền thực thi"
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_bay_buoc_co_ten(script):
    for b in ("B0 health", "B1 dang nhap", "B2 cung cau hoi", "B3 vai L0", "B4 hoan 4 bang",
              "B5 break-glass", "B6 audit_log", "B7 tran than"):
        assert f'buoc "{b}' in script, f"thiếu bước {b!r}"


def test_khong_secret_va_mat_khau_suy_tu_seed(script):
    """Không chuỗi mật khẩu, không token; tên biến `DEMO_MAT_KHAU_<TÊN>` dựng từ tên tài khoản."""
    assert re.search(r"(?i)(password|mat_khau)\s*=\s*['\"][^$'\"]{6,}", script) is None
    assert "Bearer $" in script and not re.search(r"Bearer [A-Za-z0-9._-]{20,}", script)
    assert 'bien="DEMO_MAT_KHAU_$(echo "$tk" | tr' in script
    seed = yaml.safe_load((REPO_ROOT / "config" / "tai-khoan.yaml").read_text(encoding="utf-8"))
    ten = {m["tai_khoan"] for m in seed["tai_khoan"]}
    assert ten == {"ts01", "dev01", "demo01"}
    assert "for tk in ts01 dev01 demo01; do" in script
    assert "source .env" in script and "source .env.server" in script


def test_trap_exit_ve_bang_van_hanh_va_cho_grant_het_han(script):
    assert "trap don_dep EXIT" in script
    assert f'POLICY_VAN_HANH="{ID_MAC_DINH}"' in script and ID_MAC_DINH in POLICY_VAN_HANH
    assert 'J POST /admin/policy "$TOKEN_ADMIN" "{\\"id\\":\\"$POLICY_VAN_HANH\\"}"' in script
    assert "UPDATE breakglass_grants SET expires_at = now() WHERE id = '$GRANT_ID'" in script


def test_bon_bang_dung_danh_muc_va_cong_che_do_do_duoc_noi_ra(script):
    ma = sorted(p.name[len("policy-"):-len(".yaml")] for p in (REPO_ROOT / "config").glob("policy-*.yaml"))
    assert sorted(re.search(r'^BON_BANG="([^"]+)"$', script, re.M).group(1).split()) == ma
    assert "POLICY_CHI_CHE_DO_DO" in script and "HYPER_RAG_CHE_DO_DO=1" in script


def test_ba_cau_hoi_la_cau_that_hoac_cau_da_chay_o_5_3(script):
    bo = doc_bo_cau_hoi()
    cau = {c.cau_hoi: c for c in bo.cau}
    l0 = re.search(r"^CAU_L0='(.+)'$", script, re.M).group(1)
    n7 = re.search(r"^CAU_N7='(.+)'$", script, re.M).group(1)
    assert cau[l0].id == "n5-05" and "vai_hoi_khong_thay" in cau[l0].han_che and cau[l0].vai_hoi == "tech_support"
    assert cau[n7].id == "n7-06" and cau[n7].vai_hoi == "tech_support"
    # Câu ghim là câu của kiểm tay 5.3 (sprint-status 5-3), không phải câu trong bộ 52.
    assert "CAU_GHIM='Sự cố App01 lỗi 502 nguyên nhân là gì?'" in script


def test_script_chi_noi_http_va_psql(script):
    assert "python -m" not in script and "uv run" not in script
    assert "python3 -c" in script
    assert "docker compose --env-file .env --env-file .env.server exec -T postgres psql" in script


def test_grant_con_han_thi_cho_het_han_roi_xin_lai(script):
    """Hàng "xin break-glass lần hai trong 60 phút": không FAIL, không bỏ qua - cho grant cũ hết
    hạn bằng giờ Postgres rồi xin lại, để một lần PASS luôn là một lần đã kiểm break-glass
    (vòng review 3.8 đổi từ BỎ QUA)."""
    assert "GRANT_CON_HAN ]; then" in script
    assert "cho het han roi xin lai" in script
    assert "'$GOC' = ANY(hyperedge_ids) AND expires_at > now()" in script


def test_muc_break_glass_kiem_qua_do_thi_khong_qua_citation(script):
    """B5 đo mức gốc bằng `/do-thi` (tất định), không bằng danh sách citation do model chọn."""
    assert "muc_do_thi()" in script
    assert script.count('muc_do_thi "$TOKEN_TS" "$GOC"') >= 3
    assert 'next((c["level"] for c in d["citations"] if c["id"]=="\'"$GOC"\'"), "VANG")' in script


def test_phep_quan_sat_llm_tach_khoi_fail(script):
    assert "quan_sat()" in script
    assert 'quan_sat "hai answer' in script and 'quan_sat "dev01 hoi cung cau L0' in script
    assert 'kiem "hai answer khac nhau"' not in script


def test_cua_so_audit_theo_moc_t0_va_tran_than(script):
    assert 'T0="$(date -u +%FT%TZ)"' in script
    assert "thoi_diem > '$T0'" in script and "interval '10 minutes'" not in script
    assert "THAN_QUA_LON" in script and '"a"*70000' in script


def test_hai_than_tu_choi_so_bang_nhau_tung_byte(script):
    """Hàng "hai lượt từ chối cùng vai": so nguyên chuỗi thân, không so từng trường."""
    assert '[ "$T_L0" = "$T_N7" ]' in script
