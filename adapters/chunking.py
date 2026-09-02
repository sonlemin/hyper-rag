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
