"""Hợp đồng giữa `scripts/chay-may-chu.sh` và `docker-compose.yml` (story 2.7).

Script chạy trên *host* của máy chủ, còn màn nạp chạy trong container: hai bên
phải trỏ vào cùng một `HYPER_RAG_WORKING_DIR` thì sổ tài liệu và khóa file mới
là một. Cái nối hai bên là volume `hyper_rag_api_data` cộng đường dẫn con bên
trong nó, và đường dẫn con ấy được viết hai chỗ - compose và script. Đây là
chỗ canh chúng còn khớp.

Không cần Docker, không cần máy chủ: test đọc hai file.
"""

import os
import re
import stat
from pathlib import Path

import pytest

from tests.ho_tro_compose import doc_compose

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "chay-may-chu.sh"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _gan(noi_dung: str, ten: str) -> str:
    """Giá trị của một phép gán `TEN="..."` hay `TEN=...` trong script bash."""
    khop = re.search(rf'^{ten}="?([^"\n]+)"?$', noi_dung, re.MULTILINE)
    assert khop, f"script không gán {ten}"
    return khop.group(1)


def test_script_chay_duoc():
    assert SCRIPT.exists()
    assert os.stat(SCRIPT).st_mode & stat.S_IXUSR, "script phải có cờ thực thi"


def test_thu_muc_lam_viec_cua_script_khop_compose(script):
    """`<mountpoint volume>/<đường dẫn con>` phải bằng `HYPER_RAG_WORKING_DIR` của container.

    Compose khai `api_data:/data` và `HYPER_RAG_WORKING_DIR: /data/hyper-rag`,
    nên phần sau điểm mount là `hyper-rag`. Đổi một trong hai chỗ mà quên chỗ
    kia là CLI trên host và màn trong container dùng hai sổ tài liệu khác nhau
    trên cùng một Neo4j/Qdrant - đúng cái mà story 2.7 hợp nhất lại.
    """
    compose = doc_compose()
    api = compose["services"]["api"]
    working = api["environment"]["HYPER_RAG_WORKING_DIR"]
    (mount,) = [v.split(":", 1)[1] for v in api["volumes"] if v.startswith("api_data:")]
    con = str(Path(working).relative_to(mount))

    assert _gan(script, "DUONG_DAN_CON") == con
    ten_volume = compose["volumes"]["api_data"]["name"]
    assert _gan(script, "VOLUME_API").endswith(f":-{ten_volume}}}") or _gan(
        script, "VOLUME_API"
    ) == ten_volume


def test_script_khong_ghi_secret_vao_repo(script):
    """Script `source .env`; nó không được in hay chép giá trị nào ra ngoài."""
    assert "source .env" in script
    for xau in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "NEO4J_PASSWORD", "POSTGRES_PASSWORD"):
        assert f"echo {xau}" not in script and f"${xau}" not in script


def test_script_goi_dung_diem_vao_cua_du_an(script):
    """Điểm vào mặc định giữ nguyên `api.do_chi_phi`, đổi được qua một biến.

    Story 2.9 thêm một lệnh thứ hai chạy trên máy chủ (`eval.chup_do_thi`, đọc
    đồ thị để gán nhãn truy hồi vàng). Nó cần đúng khối môi trường mà script
    này dựng - IP ba container cộng `HYPER_RAG_WORKING_DIR` lấy từ mountpoint
    của volume - nên đường ra là một biến, không phải một bản sao thứ hai của
    script. Mặc định phải bất động: mọi lệnh nạp đã ghi trong AGENTS.md và
    trong spec 2.7/2.8 không truyền biến nào.
    """
    assert _gan(script, "MODULE_MAC_DINH") == "api.do_chi_phi"
    assert 'MODULE="${HYPER_RAG_MODULE:-$MODULE_MAC_DINH}"' in script
    assert 'uv run python -m "$MODULE"' in script
    assert "python -m api.do_chi_phi" not in script, "điểm vào không được ghim cứng nữa"


def test_module_diem_vao_la_danh_sach_cho_phep(script):
    """Danh sách cho phép, không chuỗi tự do: `python -m <gì cũng được>` từ môi
    trường là một cửa chạy code mà script này không cần đến. Số module hợp lệ
    là một con số đóng, khai thẳng rẻ hơn.

    Story 2.10 thêm `eval.ct03` (thí nghiệm mô tả entity đa nguồn, đọc thuần,
    không tốn tiền). Story 3.8 thêm `eval.do3_tho` (Đo 3 thô, một lời gọi LLM
    trích từ khóa mỗi ô). Thêm một module là sửa **một** hằng ở đây và một hằng
    trong script, không phải nới luật thành chuỗi tự do.
    """
    assert (
        _gan(script, "MODULE_CHO_PHEP")
        == "api.do_chi_phi eval.chup_do_thi eval.ct03 eval.do3_tho"
    )
    assert "khong nam trong danh sach cho phep" in script


def test_module_doc_sau_khi_source_env(script):
    """`MODULE=` phải nằm **sau** hai lệnh `source`.

    Gán trước thì một khai báo `HYPER_RAG_MODULE` trong `.env.server` bị bỏ qua
    im lặng, và người chạy tưởng mình đang chụp (đọc thuần) trong khi thật ra
    đang nạp - tức đang tiêu tiền LLM.
    """
    assert script.index("source .env.server") < script.index(
        'MODULE="${HYPER_RAG_MODULE:-$MODULE_MAC_DINH}"'
    )


def test_lenh_khong_kem_tham_so_van_chay_duoc(script):
    """`chup` không kèm tham số là một lệnh hợp lệ, nên cửa đếm tham số là `-lt 1`."""
    assert '[ "$#" -lt 1 ]' in script
    assert '[ "$#" -lt 2 ]' not in script
    assert "tham so cua api.do_chi_phi" not in script, "dòng usage còn ghim module cũ"


# --- Story 2.11: lớp cấu hình cục bộ và container thứ tư -------------------


def test_lop_cuc_bo_source_sau_env_server(script):
    """`.env.local-llm` phải `source` **sau** `.env.server`, nếu không nó vô nghĩa.

    Đây là cả lý do đường cục bộ là một file chứ không phải hai biến trên dòng
    lệnh: `set -a` + `source` ghi đè mọi biến truyền từ ngoài, im lặng. Đặt lớp
    này trước `.env.server` là dựng lại đúng cái bẫy đó, chỉ khác chỗ đứng.
    """
    assert script.index("source .env.server") < script.index('source "$FILE_CUC_BO"')
    assert _gan(script, "FILE_CUC_BO") == ".env.local-llm"


def test_lop_cuc_bo_chi_bat_khi_duoc_yeu_cau(script):
    """Mặc định là tắt: đường sản phẩm (`synth`, DeepSeek) không được đổi ngầm."""
    assert 'CUC_BO="${HYPER_RAG_CUC_BO:-0}"' in script
    assert 'if [ "$CUC_BO" = "1" ]; then' in script


def test_thieu_file_cuc_bo_la_fail_chu_khong_chay_tiep(script):
    """Thiếu `.env.local-llm` mà vẫn chạy tiếp là chạy Qwen bằng cấu hình DeepSeek."""
    assert 'thieu $REMOTE_DIR/$FILE_CUC_BO' in script


def test_tra_ip_container_ollama_khi_chay_cuc_bo(script):
    """`OLLAMA_HOST` phải dựng từ IP container như ba kho kia.

    `.env.server` khai `http://ollama:11434`, tên chỉ phân giải được bên trong
    network compose; script này chạy trên host. Và `export` phải nằm **sau**
    mọi lệnh `source`, nếu không lớp cấu hình ghi đè lại chính nó.
    """
    assert "ip_container ollama" in script
    assert 'export OLLAMA_HOST="http://$OLLAMA_IP:11434"' in script
    assert script.index('source "$FILE_CUC_BO"') < script.index("export OLLAMA_HOST")


def test_thieu_container_ollama_la_fail_chu_khong_roi_ve_api_ngoai(script):
    """Space `real` không có nhánh fallback (AD-12): thiếu ollama là dừng cả đợt."""
    assert "ollama(profile local-llm)" in script
    assert 'if [ -n "$thieu" ]; then' in script


def test_cuc_bo_chi_nhan_0_hoac_1(script):
    """`HYPER_RAG_CUC_BO=true` rơi về nhánh 0 rồi chạy DeepSeek trên thư mục tài
    liệu công ty. Wrapper chặn lại (fail-closed, AD-12) nhưng thông điệp khi đó
    nói về provider, không nói về một biến gõ sai giá trị."""
    assert 'if [ "$CUC_BO" != "0" ] && [ "$CUC_BO" != "1" ]; then' in script
    assert "khong hop le: chi nhan 0 hoac 1" in script


def test_cuc_bo_chi_di_voi_space_real(script):
    """Bật đường cục bộ cho một space khác là trích xuất `synth` bằng Qwen, tức
    làm bẩn mẫu số của Đo 2 và Đo 3 bằng một bộ trích xuất khác hẳn."""
    assert '*" --space real "*|*" --space=real "*' in script
    assert "chi di voi --space real (AD-12)" in script
