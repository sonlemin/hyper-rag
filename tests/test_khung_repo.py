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


def test_ep_phien_ban_dependency():
    """Chốt pitfall spike 29/08: qdrant-client >=1.12 và pydantic >=2."""
    from importlib.metadata import version

    import pydantic

    qdrant_raw = version("qdrant-client")
    qdrant_ver = tuple(int(p) for p in qdrant_raw.split(".")[:2])
    assert qdrant_ver >= (1, 12), f"qdrant-client {qdrant_raw} < 1.12"
    assert pydantic.VERSION.startswith("2."), f"pydantic {pydantic.VERSION} < 2"


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
