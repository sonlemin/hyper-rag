"""Hợp đồng triển khai của `docker-compose.yml` (story 1.1, AC-1.1-1, AC-1.1-2).

`docker compose config --quiet` chạy trong CI chỉ bắt được lỗi cú pháp và biến
thiếu. Nó không thấy ai gỡ `condition: service_healthy`, xóa một healthcheck,
hay bỏ `profiles` của ollama - ba thay đổi im lặng làm `api` lên trước kho
(bẫy E1-OPS-01) hoặc kéo ollama vào cấu hình mặc định. Đây là chỗ canh giữ
ba điều đó.

Không cần container, không cần mạng: test đọc file, không dựng stack.
"""

from pathlib import Path

import pytest

from adapters.identity_seed import nap_tai_khoan
from adapters.llm_wrapper import BIEN_EMBEDDING_MODEL, BIEN_LLM_MODEL, BIEN_MOI_TRUONG_MODEL
from adapters.model_catalog import LOAI_EMBEDDING, LOAI_LLM, danh_muc_mac_dinh
from tests.ho_tro_compose import KHO_PHAI_CHO, doc_compose, doc_env

# Hai service chay ma Python cua du an: cung image, cung bien, khac cong.
SERVICE_PYTHON = ("api", "man-nap")


@pytest.fixture(scope="module")
def compose() -> dict:
    return doc_compose()


# --- Thứ tự khởi động: api chờ đủ ba kho healthy ---------------------------


@pytest.mark.parametrize("dv", SERVICE_PYTHON)
def test_service_python_cho_du_ba_kho(compose, dv):
    """`api` và `man-nap` khai `depends_on` đủ ba kho, không thiếu cái nào."""
    assert set(compose["services"][dv]["depends_on"]) == set(KHO_PHAI_CHO)


@pytest.mark.parametrize("dv", SERVICE_PYTHON)
@pytest.mark.parametrize("kho", KHO_PHAI_CHO)
def test_service_python_cho_dieu_kien_healthy_chu_khong_chi_started(compose, dv, kho):
    """Điều kiện phải là `service_healthy`.

    `service_started` cũng qua được `compose config` nhưng nó chỉ nói container
    đã chạy, không nói kho đã trả lời được. Đó đúng là ca mà `api` lên trước
    Neo4j trên máy chủ 15 GB RAM.
    """
    assert compose["services"][dv]["depends_on"][kho]["condition"] == (
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


@pytest.mark.parametrize("dv", SERVICE_PYTHON)
def test_service_python_cung_co_healthcheck(compose, dv):
    """Hai service của dự án tự chúng cũng phải khai healthcheck."""
    assert compose["services"][dv]["healthcheck"]["test"]


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


def test_chi_hai_service_python_publish_cong(compose):
    """Ba kho và ollama không bao giờ publish cổng (chốt 31/08/2026).

    Cùng một hợp đồng với quyết định phơi cổng trong ledger: 8000 công khai có
    chủ đích, 7474/7687/6333/5432/11434 chỉ trong network nội bộ của compose.
    """
    co_ports = {
        ten for ten, dv in compose["services"].items() if dv.get("ports")
    }
    assert co_ports == set(SERVICE_PYTHON)
    assert compose["services"]["api"]["ports"] == ["8000:8000"]


def test_man_nap_chi_bind_loopback_cua_may_chu(compose):
    """Story 2.7: màn nạp không có xác thực, nên nó không được lộ ra ngoài.

    Ghim cả *danh sách* cổng chứ không chỉ một phần tử: thêm một dòng
    `"8100:8100"` bên cạnh dòng loopback là phơi màn ra Internet, mà một phép
    kiểm "có chứa 127.0.0.1:8100:8100" thì vẫn xanh.
    """
    assert compose["services"]["man-nap"]["ports"] == ["127.0.0.1:8100:8100"]


def test_man_nap_dung_chung_image_bien_va_volume_voi_api(compose):
    """Cùng image, cùng biến, cùng volume `api_data`: một thư mục làm việc duy nhất.

    Hai `HYPER_RAG_WORKING_DIR` khác nhau là hai sổ tài liệu khác nhau trên
    cùng Neo4j/Qdrant - nạp qua màn khi sổ trống mà kho đầy ra `DA_CO_TRONG_KHO`
    hoặc để lại rác, và `KhoaIngest` không còn là chốt chung giữa màn và CLI.
    """
    api, man = compose["services"]["api"], compose["services"]["man-nap"]
    assert man["build"] == api["build"]
    assert man["environment"] == api["environment"]
    assert man["volumes"] == api["volumes"] == ["api_data:/data"]


def test_man_nap_chay_dung_app_thu_hai(compose):
    """`command` trỏ `api.man_nap:app`, không phải `api.main:app` của service `api`."""
    lenh = " ".join(compose["services"]["man-nap"]["command"])
    assert "api.man_nap:app" in lenh and "8100" in lenh
    assert "command" not in compose["services"]["api"], "service `api` giữ CMD của image"


# --- Story 2.2: biến chọn model có nguồn trong compose và trỏ vào danh mục ---

# Ba file tham số môi trường. `.env.local-llm` (story 2.11) không đi vào
# `docker compose --env-file`: nó là lớp đắp lên `.env.server` cho *một lần chạy
# CLI* trên đường cục bộ. Nhưng nó khai cùng hai biến chọn model, nên nó chịu
# cùng một luật: tên model phải là mục thật trong danh mục, đúng loại.
FILE_THAM_SO = (".env.server", ".env.laptop", ".env.local-llm")


@pytest.mark.parametrize("dv", SERVICE_PYTHON)
def test_compose_khai_du_bien_chon_model_wrapper_doc(compose, dv):
    """Mỗi biến mà `adapters/llm_wrapper.py` đọc phải có nguồn trong service Python."""
    env = compose["services"][dv]["environment"]
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


# --- Story 2.11: đường cục bộ của space `real` -----------------------------


def test_file_cuc_bo_chi_khai_model_ollama():
    """`.env.local-llm` phải trỏ vào provider **cục bộ**, không phải API ngoài.

    Đây là cả lý do file tồn tại. Một `.env.local-llm` khai `deepseek-v4-flash`
    vẫn qua được test trên (tên có trong danh mục, đúng loại) mà lại gửi tài
    liệu công ty ra API ngoài - `_kiem_space` của wrapper chặn được, nhưng chặn
    ở đó là chặn sau khi người chạy đã tưởng mình cấu hình đúng.
    """
    env = doc_env(".env.local-llm")
    dm = danh_muc_mac_dinh()
    for bien, loai in ((BIEN_LLM_MODEL, LOAI_LLM), (BIEN_EMBEDDING_MODEL, LOAI_EMBEDDING)):
        muc = dm.muc(env[bien], loai=loai)
        assert muc.cuc_bo, f"{bien}={env[bien]!r} không phải model cục bộ"


def test_file_cuc_bo_khong_ghim_ollama_host():
    """`OLLAMA_HOST` không được khai ở đây.

    `http://ollama:11434` chỉ phân giải được trong network compose, còn
    `scripts/chay-may-chu.sh` chạy trên host. Khai ở đây là ghi đè đúng cái mà
    script vừa tra ra từ IP container - và lỗi chỉ nổ ở tầng driver.
    """
    assert "OLLAMA_HOST" not in doc_env(".env.local-llm")


# Biến mang secret. Chúng chỉ sống trong `.env` gốc repo (đã gitignore); ba file
# tham số môi trường có commit thì không được chứa cái nào (Consistency
# Conventions "Cấu hình"). Story 3.1 thêm khóa ký JWT và mật khẩu của từng tài
# khoản seed.
#
# Phần mật khẩu **dẫn xuất từ chính seed**, không gõ tay: thêm một tài khoản mà
# quên thêm một dòng ở đây là một mật khẩu được phép nằm trong một file có
# commit, và không gì đỏ. Cùng lý do với vòng lặp của
# `tests/test_xac_thuc.py::test_mat_khau_seed_that_dang_nhap_duoc`.
BIEN_SECRET = {
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "NEO4J_PASSWORD",
    "POSTGRES_PASSWORD",
    "QDRANT_API_KEY",
    "JWT_SECRET",
} | {f"DEMO_MAT_KHAU_{m.ten.upper()}" for m in nap_tai_khoan()}


def test_file_cuc_bo_khong_chua_secret():
    """Cùng luật với `.env.server`: secret chỉ sống trong `.env` gốc (gitignore)."""
    env = doc_env(".env.local-llm")
    assert not (BIEN_SECRET & set(env)), sorted(BIEN_SECRET & set(env))


# --- Story 3.1: khóa ký JWT ------------------------------------------------


@pytest.mark.parametrize("ten_file", FILE_THAM_SO)
def test_file_tham_so_khong_chua_secret(ten_file):
    """Không file tham số nào mang secret, kể cả khóa ký JWT.

    Ba file này có commit. Một `JWT_SECRET=` ở đây là khóa ký của hệ nằm trong
    lịch sử git, và mọi token từng phát ký được lại từ đó.
    """
    lo = BIEN_SECRET & set(doc_env(ten_file))
    assert not lo, f"{ten_file} mang secret: {sorted(lo)}"


def test_compose_doi_khoa_ky_jwt_tu_env_goc_khong_co_mac_dinh():
    """`JWT_SECRET` khai bằng `:?`, không phải `:-`.

    Khóa ký không có mặc định và hệ không tự sinh: một khóa ngẫu nhiên mỗi lần
    khởi động làm mọi token đã phát chết im lặng, và trong lúc gỡ lỗi nó trông
    giống hệt "token sai chữ ký". `:?` bắt `docker compose ... config --quiet`
    đỏ ngay trên máy chủ nếu `.env` thiếu biến đó, thay vì để container lên rồi
    hỏng ở lần đăng nhập đầu.
    """
    tho = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "${JWT_SECRET:?" in tho, "compose phải đòi JWT_SECRET, không cho mặc định"
    assert "${JWT_SECRET:-" not in tho


def test_compose_khai_id_policy_mac_dinh_va_hai_file_tham_so_deu_co():
    """`HYPER_RAG_POLICY_ID` là tham số môi trường, không phải secret (story 3.2).

    Khai `:-day-du` chứ không `:?`, ngược với `JWT_SECRET` ngay trên và có lý
    do: thiếu khóa ký là một hệ không xác thực được ai, còn thiếu id policy chỉ
    có nghĩa "chạy bảng vận hành" - và đó đúng là thứ an toàn nhất trong bốn
    cấu hình. Hai file tham số vẫn phải khai tường minh, để đọc một file là
    biết môi trường đó chạy bảng nào mà không phải suy từ một mặc định.
    """
    from api.chinh_sach import BIEN_ID_POLICY, ID_MAC_DINH, danh_muc

    goc = Path(__file__).resolve().parent.parent
    tho = (goc / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${" + BIEN_ID_POLICY + ":-" + ID_MAC_DINH + "}" in tho
    assert "${" + BIEN_ID_POLICY + ":?" not in tho
    hop_le = set(danh_muc())
    for ten_file in (".env.server", ".env.laptop"):
        env = doc_env(ten_file)
        assert BIEN_ID_POLICY in env, ten_file
        assert env[BIEN_ID_POLICY] in hop_le, (ten_file, env[BIEN_ID_POLICY])


@pytest.mark.parametrize("dv", SERVICE_PYTHON)
def test_hai_service_python_deu_thay_id_policy(compose, dv):
    """Cùng khối biến với `api`, cùng lý do với khóa ký: không tách một biến ra."""
    from api.chinh_sach import BIEN_ID_POLICY

    assert BIEN_ID_POLICY in compose["services"][dv]["environment"]


@pytest.mark.parametrize("dv", SERVICE_PYTHON)
def test_hai_service_python_deu_thay_khoa_ky(compose, dv):
    """Cả `api` lẫn `man-nap` cùng khối biến, nên cả hai cùng đòi khóa ký.

    `man-nap` chưa dùng tới nó (màn không có xác thực, và đó là lý do nó chỉ
    bind loopback), nhưng hai service neo cùng một YAML anchor: tách riêng một
    biến ở đây là mở đường cho hai khối biến trôi dạt.
    """
    assert "JWT_SECRET" in compose["services"][dv]["environment"]


def test_compose_khai_co_che_do_do_mac_dinh_tat_va_hai_file_tham_so_deu_co():
    """`HYPER_RAG_CHE_DO_DO` là tham số môi trường (story 3.6, ADR-017), mặc định `0`.

    `:-0` chứ không `:?`: một tiến trình không ai khai cờ phải chạy như 3.5,
    không phải chết và không phải một cửa sổ đo. Hai file tham số khai tường
    minh một giá trị mà `doc_che_do_do` nhận, để đọc một file là biết môi
    trường đó có đang là cửa sổ đo hay không.
    """
    from api.che_do_do import BIEN_CHE_DO_DO, GIA_TRI_TAT, doc_che_do_do

    goc = Path(__file__).resolve().parent.parent
    tho = (goc / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${" + BIEN_CHE_DO_DO + ":-" + GIA_TRI_TAT + "}" in tho
    assert "${" + BIEN_CHE_DO_DO + ":?" not in tho
    for ten_file in (".env.server", ".env.laptop"):
        env = doc_env(ten_file)
        assert BIEN_CHE_DO_DO in env, ten_file
        doc_che_do_do(env)  # không ném: giá trị là 0 hoặc 1


@pytest.mark.parametrize("dv", SERVICE_PYTHON)
def test_hai_service_python_deu_thay_co_che_do_do(compose, dv):
    from api.che_do_do import BIEN_CHE_DO_DO

    assert BIEN_CHE_DO_DO in compose["services"][dv]["environment"]
