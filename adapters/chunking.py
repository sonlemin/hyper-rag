"""Chia chunk: đúng một bản của luật mà `EngineACL.ainsert` dùng (story 2.6).

Harness đo của `eval/` phải chia chunk *y hệt* đường nạp thật, nếu không con số
precision đo trên một cách cắt còn kho chạy trên một cách cắt khác. Luật đó nằm
ở `hypergraphrag.operate.chunking_by_token_size` cộng ba tham số của
`EngineACL`, và `vendor/` chỉ `adapters/` mới được import (AGENTS.md, chiều
import). Module này là chỗ duy nhất nối hai thứ đó lại, để `eval/` gọi được mà
không phải import vendor.

Ba tham số đọc từ **default của dataclass field**, không dựng instance: dựng
`EngineACL` là mở kết nối tới ba kho, còn thứ cần ở đây chỉ là ba con số.
"""

from dataclasses import fields
from typing import Mapping

from hypergraphrag.operate import chunking_by_token_size

from adapters.engine import EngineACL

# Ba field của `EngineACL` quyết định cách cắt. Ghi ra tên để test parity chỉ
# mặt được đúng field nào đổi, thay vì so hai kết quả rồi đoán.
TRUONG_CHUNK: tuple[str, ...] = (
    "chunk_token_size",
    "chunk_overlap_token_size",
    "tiktoken_model_name",
)


def cau_hinh_chunk() -> dict[str, object]:
    """Ba tham số chia chunk, lấy từ default của dataclass field `EngineACL`."""
    mac_dinh = {f.name: f.default for f in fields(EngineACL)}
    return {ten: mac_dinh[ten] for ten in TRUONG_CHUNK}


def chia_chunk(than: str, cau_hinh: Mapping[str, object] | None = None) -> list[dict]:
    """Chia đúng như `EngineACL.ainsert` chia, kể cả bước `strip()` của upstream."""
    cau_hinh = cau_hinh_chunk() if cau_hinh is None else cau_hinh
    return chunking_by_token_size(
        than.strip(),
        overlap_token_size=cau_hinh["chunk_overlap_token_size"],
        max_token_size=cau_hinh["chunk_token_size"],
        tiktoken_model=cau_hinh["tiktoken_model_name"],
    )


def dem_token(than: str, cau_hinh: Mapping[str, object] | None = None) -> int:
    """Số token của một đoạn văn bản theo đúng bộ tách của đường nạp thật.

    Dùng `chia_chunk` với trần chunk rất lớn và overlap 0 để cả đoạn ra đúng một
    mảnh. Nằm ở đây chứ không ở `eval/` (story 2.13): `api/do_chi_phi.py` cần
    đúng phép đếm này cho `--uoc-tinh`, và `api/` không được import `eval/`
    (chiều import của AGENTS.md, nay canh bằng `tests/test_import_lint.py`).
    Module này đã là chỗ duy nhất nối luật chunk của vendor với phần còn lại,
    nên đếm token ở đây không mở thêm một cửa thứ hai sang `vendor/`.
    """
    goc = dict(cau_hinh_chunk() if cau_hinh is None else cau_hinh)
    goc["chunk_token_size"] = 10**7
    goc["chunk_overlap_token_size"] = 0
    return sum(int(d["tokens"]) for d in chia_chunk(than, goc))
