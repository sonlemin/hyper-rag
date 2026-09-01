"""Hợp đồng triển khai của `docker-compose.yml` (story 1.1, AC-1.1-1, AC-1.1-2).

`docker compose config --quiet` chạy trong CI chỉ bắt được lỗi cú pháp và biến
thiếu. Nó không thấy ai gỡ `condition: service_healthy`, xóa một healthcheck,
hay bỏ `profiles` của ollama - ba thay đổi im lặng làm `api` lên trước kho
(bẫy E1-OPS-01) hoặc kéo ollama vào cấu hình mặc định. Đây là chỗ canh giữ
ba điều đó.

Không cần container, không cần mạng: test đọc file, không dựng stack.
"""

import pytest

from tests.ho_tro_compose import KHO_PHAI_CHO, doc_compose


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
