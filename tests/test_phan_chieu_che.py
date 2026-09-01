"""Test phản chiếu: mọi method đọc của adapter phải được khai vào một nhóm (AD-9).

Danh sách đóng `core.masking.MASKED_READ_METHODS` chỉ có nghĩa khi có ai đó
canh rằng không method đọc nào nằm ngoài mọi nhóm. Không có test này thì thêm
một method đọc public mới vào adapter là thêm một đường ra khỏi kho không đi
qua tầng che, và không gì đỏ.

Ba nhóm, không có nhóm thứ tư:

- `MASKED_READ_METHODS` - trả nội dung, bắt buộc qua `mask` trước khi rời
  adapter;
- `XU_LY_RIENG` - method đọc *không* trả nội dung, nên che không áp dụng: số
  đếm co theo quyền, `has_*` trả False cho mục ngoài quyền. Mỗi tên ở đây kèm
  một câu nói cơ chế thay thế là gì;
- `GHI` - đường ghi, không phải đường đọc.

Quét bằng cách phản chiếu chính lớp adapter, đối chiếu với interface của
`vendor/`: method nào adapter override mà không nằm trong ba nhóm là đỏ. Nhờ
vậy đổi tên một method bên upstream, hay thêm một method đọc mới bên mình, đều
bị bắt tại đây.

Adapter KV của story 1.5 thêm đúng một dòng vào `CAC_ADAPTER`; story 1.7 gom
ba adapter lại ở cổng M1.
"""

import inspect
import re

import pytest
from hypergraphrag.base import BaseGraphStorage, BaseKVStorage, BaseVectorStorage

from adapters.neo4j import Neo4jACLGraphStorage
from adapters.qdrant import QdrantVectorDBStorage
from core.masking import MASKED_READ_METHODS

# Method đọc không trả nội dung: che không áp dụng, nhưng quyền thì có. Mỗi
# dòng nói rõ cơ chế thay thế, để "không che" là một quyết định chứ không phải
# một chỗ bị quên.
XU_LY_RIENG = {
    # Số đếm là tín hiệu xếp hạng đi thẳng vào ngữ cảnh trả về; nó co theo
    # quyền bằng WHERE trên chính biến lân cận, không bằng che.
    "node_degree",
    "edge_degree",
    # Trả bool: mục ngoài quyền là `False`, không phải lỗi và không phải True.
    "has_node",
    "has_edge",
}

GHI = {"upsert", "upsert_node", "upsert_edge", "delete_node", "drop"}

# Method của `StorageNameSpace` không đọc dữ liệu người dùng.
VONG_DOI = {"index_done_callback", "query_done_callback", "embed_nodes"}

# Method riêng của adapter, ngoài hợp đồng upstream, không chạm dữ liệu người
# dùng: dựng kho và đóng kết nối.
NGOAI_HOP_DONG = {"initialize", "close"}

CAC_ADAPTER = [
    (QdrantVectorDBStorage, BaseVectorStorage),
    (Neo4jACLGraphStorage, BaseGraphStorage),
    # story 1.5: (KVStorage của mình, BaseKVStorage)
]

MOI_INTERFACE = (BaseVectorStorage, BaseGraphStorage, BaseKVStorage)


def _method_public_cua(lop) -> set[str]:
    """Method public do chính lớp đó định nghĩa, không tính thừa kế."""
    return {
        ten
        for ten, gia_tri in vars(lop).items()
        if not ten.startswith("_") and inspect.isroutine(gia_tri)
    }


@pytest.mark.parametrize(
    "adapter,interface", CAC_ADAPTER, ids=lambda x: getattr(x, "__name__", str(x))
)
def test_moi_method_public_cua_adapter_deu_duoc_khai(adapter, interface):
    """*Mọi* method public của adapter phải nằm trong một nhóm.

    Quét toàn bộ method public chứ không chỉ những cái override interface: ca
    nguy hiểm nhất là một method đọc **mới toanh** mà upstream không có, ví dụ
    một `get_all_nodes` tiện tay thêm cho endpoint đồ thị. Nó không override gì
    nên một phép quét theo interface sẽ không thấy, trong khi nó vẫn là một
    đường dữ liệu ra khỏi kho.
    """
    da_khai = MASKED_READ_METHODS | XU_LY_RIENG | GHI | VONG_DOI | NGOAI_HOP_DONG
    chua_khai = _method_public_cua(adapter) - da_khai
    assert not chua_khai, (
        f"{adapter.__name__} có method public chưa khai vào nhóm nào:"
        f" {sorted(chua_khai)}. Trả nội dung thì thêm vào MASKED_READ_METHODS"
        " (core/masking.py) và cho nó đi qua `mask`; không trả nội dung thì"
        " thêm vào XU_LY_RIENG kèm một câu nói cơ chế quyền thay thế."
    )


_GOI_RIENG = re.compile(r"self\.(_\w+)\(")


def _co_duong_toi_mask(adapter, ten: str, sau: int = 1) -> bool:
    """Method có gọi tầng che không, trực tiếp hoặc qua một cửa dùng chung.

    Đi sâu một tầng là đủ và vẫn tổng quát: cả hai adapter đều gom lời gọi che
    vào một hàm riêng (`_che`, `_ban_ghi`), nên khóa cứng tên hàm đó ở đây là
    biến một quy ước của hôm nay thành luật của mai sau.
    """
    nguon = inspect.getsource(getattr(adapter, ten))
    if "mask(" in nguon:
        return True
    if sau <= 0:
        return False
    return any(
        hasattr(adapter, goi) and _co_duong_toi_mask(adapter, goi, sau - 1)
        for goi in set(_GOI_RIENG.findall(nguon))
    )


@pytest.mark.parametrize(
    "adapter,interface", CAC_ADAPTER, ids=lambda x: getattr(x, "__name__", str(x))
)
def test_method_phai_che_ma_adapter_co_thi_goi_mask(adapter, interface):
    """Method nằm trong danh sách đóng mà adapter có thì phải gọi `mask`.

    Đọc mã nguồn của chính method: nó phải gọi tầng che, dù trực tiếp hay qua
    một cửa dùng chung (`_che`). Assert trên nguồn là thô, nhưng nó bắt được
    đúng thứ cần bắt - một method trả nội dung mà không có đường nào tới hàm
    che - và bắt ngay lúc thêm method, không đợi tới một test Đo 1 nào đó.
    """
    thieu = [
        ten
        for ten in sorted(MASKED_READ_METHODS)
        if ten in _method_public_cua(adapter) and not _co_duong_toi_mask(adapter, ten)
    ]
    assert not thieu, f"{adapter.__name__}: method trả nội dung không qua tầng che: {thieu}"


def test_danh_sach_dong_khong_giao_nhau():
    """Ba nhóm rời nhau: một method chỉ có một cách xử lý."""
    assert not (MASKED_READ_METHODS & XU_LY_RIENG)
    assert not (MASKED_READ_METHODS & GHI)
    assert not (XU_LY_RIENG & GHI)


def test_moi_ten_trong_nhom_ton_tai_o_upstream():
    """Neo ba nhóm vào interface thật của fork, không để trôi dạt."""
    for ten in MASKED_READ_METHODS | XU_LY_RIENG | GHI:
        assert any(hasattr(lop, ten) for lop in MOI_INTERFACE), ten
