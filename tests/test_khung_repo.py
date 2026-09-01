"""Test khung repo cho run xanh đầu tiên (story 1.1).

Chứng minh: các package Structural Seed import được, vendor ghim import được
trên Python 3.12 (rủi ro R3), api có GET /health. Không cần mạng, không cần
key LLM, không cần container.
"""

import importlib
import sys

import pytest


def test_python_312():
    assert sys.version_info[:2] == (3, 12)


@pytest.mark.parametrize("pkg", ["core", "adapters", "api", "redteam"])
def test_import_khung(pkg):
    importlib.import_module(pkg)


def test_import_vendor_hypergraphrag():
    """Fork ghim d587cdf import được trên 3.12 với dependency đã cắt gọn."""
    from hypergraphrag import HyperGraphRAG, QueryParam

    assert HyperGraphRAG is not None
    assert QueryParam is not None


def _major_minor(raw: str) -> tuple[int, int]:
    """Lấy (major, minor) từ chuỗi phiên bản, chịu được pre-release kiểu 1.13.0rc1."""
    parts = []
    for piece in raw.split(".")[:2]:
        digits = ""
        for ch in piece:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    while len(parts) < 2:
        parts.append(0)
    return (parts[0], parts[1])


def test_ep_phien_ban_dependency():
    """Chốt pitfall spike 29/08: qdrant-client >=1.12 và pydantic >=2."""
    from importlib.metadata import version

    import pydantic

    qdrant_raw = version("qdrant-client")
    assert _major_minor(qdrant_raw) >= (1, 12), f"qdrant-client {qdrant_raw} < 1.12"
    assert _major_minor(pydantic.VERSION)[0] >= 2, f"pydantic {pydantic.VERSION} < 2"


def test_api_health():
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_session_prefix_cach_ly(session_prefix):
    """Quy ước E1-DATA-01: prefix phiên tồn tại và đặt tên được collection."""
    assert session_prefix.startswith("test_")
    assert len(session_prefix) == len("test_") + 8
    collection = f"{session_prefix}_synth_chunks"
    assert collection.startswith(session_prefix)


def test_ten_model_tiktoken_chi_co_dung_hai_nguon():
    """Bước warm tiktoken của `api/Dockerfile` phải phủ đúng hai tên model đang dùng.

    `tiktoken.encoding_for_model` tải bảng BPE **qua mạng** ở lần gọi đầu
    (`vendor/hypergraphrag/utils.py:158,168`), mà container `api` không có mạng
    ra ngoài trong thiết kế triển khai. Dockerfile tải sẵn lúc build và lấy tên
    model từ chính hai chỗ khai chúng, không viết tay bản thứ hai.

    Test này ghim hai nguồn đó. Đổi default ở một trong hai mà bước warm không
    theo kịp thì bảng BPE của tên mới không nằm trong image, và lần đếm token
    đầu tiên trên máy chủ hỏng ở chỗ nói sai nguyên nhân.
    """
    import inspect

    from hypergraphrag.utils import encode_string_by_tiktoken

    from adapters.engine import EngineACL

    mac_dinh_upstream = inspect.signature(
        encode_string_by_tiktoken
    ).parameters["model_name"].default
    mac_dinh_engine = EngineACL.__dataclass_fields__["tiktoken_model_name"].default

    assert mac_dinh_upstream == "gpt-4o"
    assert mac_dinh_engine == "gpt-4o-mini"

    dockerfile = _doc_dockerfile()
    assert "TIKTOKEN_CACHE_DIR" in dockerfile, (
        "Dockerfile không đặt TIKTOKEN_CACHE_DIR: bảng BPE tải lúc build sẽ"
        " nằm ở thư mục tạm của bước build, không theo image sang lúc chạy"
    )
    assert "tiktoken.encoding_for_model" in dockerfile, (
        "Dockerfile không có bước tải sẵn bảng BPE"
    )
    # Hai tên không được viết tay trong Dockerfile: chúng phải suy từ code.
    for ten in (mac_dinh_upstream, mac_dinh_engine):
        assert f'"{ten}"' not in dockerfile and f"'{ten}'" not in dockerfile, (
            f"tên model {ten!r} viết tay trong Dockerfile: đó là bản thứ hai"
            " của cùng một hằng, lệch được mà không ai biết"
        )


def _doc_dockerfile() -> str:
    from pathlib import Path

    duong_dan = Path(__file__).resolve().parent.parent / "api" / "Dockerfile"
    return duong_dan.read_text(encoding="utf-8")
