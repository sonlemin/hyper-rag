"""Hợp đồng triển khai của `docker-compose.yml` (story 1.1, AC-1.1-1, AC-1.1-2).

`docker compose config --quiet` chạy trong CI chỉ bắt được lỗi cú pháp và biến
thiếu. Nó không thấy ai gỡ `condition: service_healthy`, xóa một healthcheck,
hay bỏ `profiles` của ollama - ba thay đổi im lặng làm `api` lên trước kho
(bẫy E1-OPS-01) hoặc kéo ollama vào cấu hình mặc định. Đây là chỗ canh giữ
ba điều đó.

Không cần container, không cần mạng: test đọc file, không dựng stack.
"""

import pytest

from adapters.llm_wrapper import BIEN_EMBEDDING_MODEL, BIEN_LLM_MODEL, BIEN_MOI_TRUONG_MODEL
from adapters.model_catalog import LOAI_EMBEDDING, LOAI_LLM, danh_muc_mac_dinh
from tests.ho_tro_compose import KHO_PHAI_CHO, doc_compose, doc_env


@pytest.fixture(scope="module")
def compose() -> dict:
    return doc_compose()


# --- Thứ tự khởi động: api chờ đủ ba kho healthy ---------------------------


def test_api_cho_du_ba_kho(compose):
    """`api` khai `depends_on` đủ ba kho, không thiếu cái nào."""
    depends_on = compose["services"]["api"]["depends_on"]
    assert set(depends_on) == set(KHO_PHAI_CHO)


@pytest.mark.parametrize("kho", KHO_PHAI_CHO)
def test_api_cho_dieu_kien_healthy_chu_khong_chi_started(compose, kho):
    """Điều kiện phải là `service_healthy`.

    `service_started` cũng qua được `compose config` nhưng nó chỉ nói container
    đã chạy, không nói kho đã trả lời được. Đó đúng là ca mà `api` lên trước
    Neo4j trên máy chủ 15 GB RAM.
    """
    assert compose["services"]["api"]["depends_on"][kho]["condition"] == (
        "service_healthy"
    )


@pytest.mark.parametrize("kho", KHO_PHAI_CHO)
def test_moi_kho_co_healthcheck(compose, kho):
    """Không có healthcheck thì `service_healthy` không bao giờ đạt được.

    Cặp với test trên: một điều kiện `service_healthy` trỏ tới một service
    không khai healthcheck là hợp đồng chết, compose sẽ treo chứ không bảo vệ
    thứ tự.
    """
    healthcheck = compose["services"][kho].get("healthcheck")
    assert healthcheck, f"service {kho!r} không khai healthcheck"
    assert healthcheck.get("test"), f"healthcheck của {kho!r} rỗng"


def test_api_cung_co_healthcheck(compose):
    """`api` tự nó cũng phải khai healthcheck, `/health` là nguồn của nó."""
    assert compose["services"]["api"]["healthcheck"]["test"]


# --- Profile local-llm không bật mặc định ----------------------------------


def test_ollama_nam_trong_profile_local_llm(compose):
    """Ollama chỉ chạy khi gọi tên profile, không lên ở cấu hình mặc định."""
    assert compose["services"]["ollama"]["profiles"] == ["local-llm"]


def test_khong_service_nao_khac_mang_profile(compose):
    """Đối chứng: mọi service còn lại phải lên ở cấu hình mặc định.

    Không có test này thì gắn nhầm `profiles` lên `api` hay một kho vẫn xanh,
    và cả stack im lặng biến mất khỏi `docker compose up`.
    """
    co_profile = {
        ten for ten, dv in compose["services"].items() if dv.get("profiles")
    }
    assert co_profile == {"ollama"}


# --- Cổng ra ngoài: chỉ 8000 --------------------------------------------


def test_chi_api_publish_cong_ra_ngoai(compose):
    """Ba kho và ollama không bao giờ publish cổng (chốt 31/08/2026).

    Cùng một hợp đồng với quyết định phơi cổng trong ledger: 8000 công khai có
    chủ đích, 7474/7687/6333/5432/11434 chỉ trong network nội bộ của compose.
    """
    co_ports = {
        ten for ten, dv in compose["services"].items() if dv.get("ports")
    }
    assert co_ports == {"api"}
    assert compose["services"]["api"]["ports"] == ["8000:8000"]


# --- Story 2.2: biến chọn model có nguồn trong compose và trỏ vào danh mục ---

FILE_THAM_SO = (".env.server", ".env.laptop")


def test_compose_khai_du_bien_chon_model_wrapper_doc(compose):
    """Mỗi biến mà `adapters/llm_wrapper.py` đọc phải có nguồn trong service `api`."""
    env = compose["services"]["api"]["environment"]
    thieu = [b for b in BIEN_MOI_TRUONG_MODEL if b not in env]
    assert not thieu, f"biến {thieu} chưa có nguồn trong docker-compose.yml"


@pytest.mark.parametrize("ten_file", FILE_THAM_SO)
def test_file_tham_so_chon_model_co_trong_danh_muc(ten_file):
    """`LLM_MODEL`/`EMBEDDING_MODEL` của mỗi môi trường phải là mục thật, đúng loại.

    Loader từ chối model lạ lúc dựng wrapper, tức lúc tiến trình `api` lên.
    Bắt ở đây để một tên gõ sai trong `.env.server` đỏ ở CI, không đỏ lúc
    `docker compose up` trên máy chủ.
    """
    env = doc_env(ten_file)
    dm = danh_muc_mac_dinh()
    assert dm.muc(env[BIEN_LLM_MODEL], loai=LOAI_LLM)
    assert dm.muc(env[BIEN_EMBEDDING_MODEL], loai=LOAI_EMBEDDING)


def test_bien_ket_noi_moi_provider_co_nguon_trong_compose(compose):
    """Biến mà danh mục chỉ cho mỗi provider (key API, host cục bộ) phải có trong `api`.

    Tên biến lấy từ chính YAML (`bien_api_key`/`bien_host`), không từ hằng
    trong code: đổi `bien_host` trong danh mục mà compose thiếu là đỏ ở đây.
    """
    env = compose["services"]["api"]["environment"]
    dm = danh_muc_mac_dinh()
    can = {n.bien_host if n.cuc_bo else n.bien_api_key for n in dm.nha_cung_cap.values()}
    thieu = sorted(b for b in can if b not in env)
    assert not thieu, f"biến {thieu} chưa có nguồn trong docker-compose.yml"
