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
    assert "python -m api.do_chi_phi" in script
