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

Ba adapter đều nằm trong `CAC_ADAPTER` từ story 1.5; story 1.7 gom chúng lại ở
cổng M1.

Đây là kịch bản `1.6-INT-002` của test-design: quét bằng introspection thật
trên cả ba adapter, không so với một danh sách cứng (bẫy TC-5).
"""

import inspect
import re

import pytest
from hypergraphrag.base import BaseGraphStorage, BaseKVStorage, BaseVectorStorage

from adapters.kv import JsonACLKVStorage
from adapters.neo4j import Neo4jACLGraphStorage
from adapters.qdrant import QdrantVectorDBStorage
from core.masking import MASKED_READ_METHODS

# Method đọc không trả nội dung: che không áp dụng, nhưng quyền thì có. Mỗi
# dòng nói rõ cơ chế thay thế, để "không che" là một quyết định chứ không phải
# một chỗ bị quên.
# Khai theo *từng adapter*, không phải một tập phẳng: lý do miễn luật che của
# một method chỉ đúng cho cái kho đã nghĩ ra nó. Gộp chung thì thêm `all_keys`
# cho đường KV cũng lặng lẽ miễn luật cho một `all_keys` mai sau của adapter
# Qdrant hay Neo4j, và cái đó chưa ai xét.
# Một câu chung cho `khoa_hien_co` của cả ba adapter, viết ra một lần rồi khai
# lại cho từng adapter: luật miễn trừ giống nhau vì cơ chế giống nhau, nhưng ô
# khai vẫn phải là ô của từng adapter (xem lý do ngay dưới).
_LY_DO_KHOA_HIEN_CO = (
    "chỉ trả trường khóa quyền, không trả nội dung nên không có gì để che;"
    " cửa của read-merge-write (FR-11) và của bước đối chiếu hai kho, và nó"
    " từ chối chạy ngoài ngữ cảnh hệ thống (IngestOutsideSystemContext)"
)

XU_LY_RIENG_THEO_ADAPTER = {
    "QdrantVectorDBStorage": {
        "khoa_hien_co": _LY_DO_KHOA_HIEN_CO,
        # Chỉ trả tập id đã hợp nhất ra không khóa, không trả nội dung; cùng
        # cửa hệ thống với `khoa_hien_co` vì "có id này không" cũng là rò.
        "so_khong_khoa": (
            "chỉ trả tập id không khóa của một space, không trả nội dung;"
            " từ chối ngoài ngữ cảnh hệ thống"
        ),
        # Payload không mang nội dung (`content` bị chặn lúc ghi); đọc thô dưới
        # cờ system cho đường dựng lại của re-ingest, từ chối ngoài ngữ cảnh đó.
        "payload_cua": "đọc thô dưới cờ system cho đường dựng lại, từ chối ngoài ngữ cảnh hệ thống",
    },
    "Neo4jACLGraphStorage": {
        "khoa_hien_co": _LY_DO_KHOA_HIEN_CO,
        # Chỉ trả khóa của các hyperedge nối tới một entity, không trả nội
        # dung: nguồn để pipeline re-ingest gấp lại khóa entity chung (2.3), và
        # nó từ chối chạy ngoài ngữ cảnh hệ thống (IngestOutsideSystemContext).
        "khoa_lan_can_hyperedge": (
            "chỉ trả trường khóa của hyperedge lân cận, không trả nội dung;"
            " đường đọc-để-ghi của re-ingest, từ chối ngoài ngữ cảnh hệ thống"
        ),
        # Trả `{vai: [id entity]}` của một hyperedge - tức tên entity theo vai,
        # là nội dung - nhưng chỉ chạy dưới cờ system (2.4): đường dựng lại
        # `content` của hyperedge chung khi re-ingest (`cau_fact`), cùng cửa
        # AD-3 với `payload_cua`; ngoài ngữ cảnh hệ thống là
        # IngestOutsideSystemContext, không có nhánh vai người dùng nào tới được.
        "slot_cua_hyperedge": (
            "đọc slot của hyperedge dưới cờ system cho đường dựng lại content"
            " khi re-ingest, từ chối ngoài ngữ cảnh hệ thống"
        ),
        # Cửa quyền của citation (3.4): trả **tên vai và khóa quyền** của những
        # hyperedge mà vai còn thấy, không trả giá trị slot hay tên entity nên
        # không có gì để che; quyền có mặt dưới dạng đúng ba mệnh đề lọc của
        # `get_node_edges` (hyperedge, cạnh, lân cận), hyperedge ngoài quyền
        # vắng mặt khỏi kết quả và `tests/test_trich_dan.py` chấm Cypher của nó
        # bằng `canh_moi_bien_deu_bi_loc`.
        "trich_dan_cua": (
            "chỉ trả khóa quyền và tên vai của hyperedge còn thấy được, không trả"
            " nội dung; lọc bằng đúng ba mệnh đề của get_node_edges, mục ngoài"
            " quyền vắng mặt"
        ),
        # Số đếm là tín hiệu xếp hạng đi thẳng vào ngữ cảnh trả về; nó co theo
        # quyền bằng WHERE trên chính biến lân cận, không bằng che.
        "node_degree": "đếm sau filter, số đếm co theo quyền",
        "edge_degree": "tổng hai node_degree nên co theo cùng luật",
        # Trả bool: mục ngoài quyền là `False`, không phải lỗi và không phải True.
        "has_node": "trả False cho mục ngoài quyền",
        "has_edge": "trả False cho cạnh ngoài quyền",
    },
    "JsonACLKVStorage": {
        # Hai method này chỉ trả id, không trả nội dung, nên không có gì để
        # che. Quyền vẫn có mặt dưới dạng luật vắng mặt im lặng, vì trả lời
        # "có tồn tại không" cũng là một đường rò.
        "all_keys": "chỉ kể id mà vai đạt L2, mục ngoài quyền vắng mặt",
        "filter_keys": "mục ngoài quyền tính là chưa tồn tại",
        "khoa_hien_co": _LY_DO_KHOA_HIEN_CO,
        # Hai cửa của sổ lọc theo lượt (story 3.6): không đọc kho, không trả gì.
        # `xa_loc` phát một hàng audit `filter` chỉ mang số đếm theo mức của
        # chính ngữ cảnh đang mở; `bo_so_loc` xóa sổ của một lượt hỏng.
        "xa_loc": "phát hàng audit số đếm bị loại của lượt, không trả nội dung",
        "bo_so_loc": "bỏ sổ đếm của lượt hỏng, không đọc kho, không trả gì",
    },
}

# Hợp của mọi khai báo, chỉ dùng cho các test nói về ba nhóm nói chung.
XU_LY_RIENG = {
    ten for theo_adapter in XU_LY_RIENG_THEO_ADAPTER.values() for ten in theo_adapter
}

GHI = {
    "upsert",
    "upsert_node",
    "upsert_edge",
    "delete_node",
    "drop",
    # Đường xóa/ghi thẳng của pipeline re-ingest (story 2.3), cả ba adapter.
    "xoa",
    "xoa_tat_ca",
    "ghi_thang",
    "xoa_node",
    "dat_lai_entity",
    "dat_lai_hyperedge",
}

# Method của `StorageNameSpace` không đọc dữ liệu người dùng.
VONG_DOI = {"index_done_callback", "query_done_callback", "embed_nodes"}

# Method riêng của adapter, ngoài hợp đồng upstream, không chạm dữ liệu người
# dùng: dựng kho và đóng kết nối.
NGOAI_HOP_DONG = {"initialize", "close"}

# Method của riêng dự án, upstream không có. Chúng vẫn phải nằm trong một nhóm
# như mọi method public khác - luật che không miễn cho ai - nhưng phép neo vào
# interface của `vendor/` thì không áp dụng được cho chúng.
NGOAI_UPSTREAM = frozenset(
    {
        "khoa_hien_co",
        "so_khong_khoa",
        "khoa_lan_can_hyperedge",
        "slot_cua_hyperedge",
        "trich_dan_cua",
        "xa_loc",
        "bo_so_loc",
        "xoa",
        "xoa_tat_ca",
        "ghi_thang",
        "xoa_node",
        "dat_lai_entity",
        "dat_lai_hyperedge",
        "payload_cua",
    }
)

CAC_ADAPTER = [
    (QdrantVectorDBStorage, BaseVectorStorage),
    (Neo4jACLGraphStorage, BaseGraphStorage),
    (JsonACLKVStorage, BaseKVStorage),
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
    rieng = XU_LY_RIENG_THEO_ADAPTER.get(adapter.__name__)
    assert rieng is not None, (
        f"{adapter.__name__} chưa có ô trong XU_LY_RIENG_THEO_ADAPTER: khai một"
        " ô rỗng nếu adapter này không miễn luật che cho method đọc nào."
    )
    da_khai = MASKED_READ_METHODS | set(rieng) | GHI | VONG_DOI | NGOAI_HOP_DONG
    chua_khai = _method_public_cua(adapter) - da_khai
    assert not chua_khai, (
        f"{adapter.__name__} có method public chưa khai vào nhóm nào:"
        f" {sorted(chua_khai)}. Trả nội dung thì thêm vào MASKED_READ_METHODS"
        " (core/masking.py) và cho nó đi qua `mask`; không trả nội dung thì"
        " thêm vào ô của chính adapter này trong XU_LY_RIENG_THEO_ADAPTER kèm"
        " một câu nói cơ chế quyền thay thế."
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


def test_moi_mien_luat_che_deu_co_ly_do_viet_ra():
    """Mỗi tên trong `XU_LY_RIENG_THEO_ADAPTER` kèm một câu nói cơ chế thay thế.

    "Không che" phải là một quyết định đọc được, không phải một chỗ bị quên.
    Khai theo từng adapter mà để giá trị rỗng thì luật này mất tác dụng.
    """
    thieu = [
        f"{ten_adapter}.{ten}"
        for ten_adapter, theo_adapter in XU_LY_RIENG_THEO_ADAPTER.items()
        for ten, ly_do in theo_adapter.items()
        if not (ly_do or "").strip()
    ]
    assert not thieu, f"miễn luật che mà không nói cơ chế thay thế: {thieu}"


def test_moi_adapter_deu_co_o_khai_rieng():
    """Adapter mới phải khai ô của nó, kể cả khi ô đó rỗng."""
    for adapter, _ in CAC_ADAPTER:
        assert adapter.__name__ in XU_LY_RIENG_THEO_ADAPTER


def test_moi_ten_trong_nhom_ton_tai_o_upstream():
    """Neo ba nhóm vào interface thật của fork, không để trôi dạt.

    Trừ đi tập tên **của riêng dự án**: những method upstream không có nên
    không neo vào đâu được. Tập đó là tường minh và ngắn, nên thêm một tên vào
    đây vẫn là một quyết định đọc được, không phải một chỗ luật này bị nới ra.
    """
    for ten in (MASKED_READ_METHODS | XU_LY_RIENG | GHI) - NGOAI_UPSTREAM:
        assert any(hasattr(lop, ten) for lop in MOI_INTERFACE), ten


def test_ten_ngoai_upstream_dung_la_ngoai_upstream():
    """Chiều ngược: tên trong tập miễn trừ phải thật sự không có ở upstream.

    Không có test này thì một tên upstream *có* lọt vào tập miễn trừ sẽ lặng lẽ
    thoát khỏi phép neo ở trên, và đó đúng là cách luật neo mất tác dụng.
    """
    for ten in NGOAI_UPSTREAM:
        assert not any(hasattr(lop, ten) for lop in MOI_INTERFACE), ten
