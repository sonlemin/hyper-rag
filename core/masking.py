"""Tầng che dùng chung theo chính sách slot (AD-9, FR-10, FR-12).

Một luật che, một chỗ, dùng chung cho cả ba adapter. Story 1.2 chốt chữ ký để
story 1.3-1.5 gọi được ngay trong đường trả về; story 1.6 thay ruột mà không
mở lại adapter nào.

Chữ ký ba tham số: (kết quả, ngữ cảnh quyền, khóa hyperedge). Khóa hyperedge là
thứ cho phép tra `masked_slots` theo đúng loại nội dung của mục đang che - mức
tiết lộ không nằm trên dữ liệu, nó tính từ bảng chính sách lúc truy vấn, nên
đổi YAML là đổi hành vi che chứ không phải sửa code (FR-09).

**Hai đường che, vì có hai hình dạng bản ghi.** Hyperedge trong kho là node hai
phía: giá trị của một slot nằm ở *entity* nối vào, không nằm trong thuộc tính
của node hyperedge. Nên tầng che phải đọc được cả hai hình dạng:

- bản ghi "dict theo slot", khóa của bản ghi chính là tên vai slot - hình dạng
  của fixture, của oracle, và của mọi tầng sau lắp fact lại thành một dict;
- bản ghi "cạnh có vai", tự khai vai của nó ở trường `slot` và mang tên node
  lân cận điền vào vai đó - hình dạng mà `get_node_edges` dựng.

Đường thứ hai mới là đường rò thật ở Epic 1: `operate.py:923` ghép tên lân cận
bằng `"|"` rồi đổ thẳng vào cột `related_entities` của bảng Relationships gửi
cho LLM. Che nội dung slot ở kho vector mà để tên đỉnh chảy qua đường graph là
che hụt đúng thứ mà FR-05 gọi là nội dung nhạy cảm.

**Hàm thuần, không biến đổi đầu vào tại chỗ.** Khi có gì để che, hàm dựng một
bản ghi mới; khi đọc thô nó trả lại chính đối tượng vào, và đó là chủ ý - ngữ
cảnh hệ thống không sinh ra bản sao nào để rồi vứt đi. Cả hai nhánh đều không
gán vào đối tượng vào, vì kho KV giữ bản gốc chưa che trong bộ nhớ dùng chung
cho mọi vai: một phép gán tại chỗ ở đây là dấu che của vai hẹp nằm lại trong
kho và vai rộng quyền đọc sau đó nhận bản đã bị che. Adapter KV còn sao chép
sâu một lần nữa trước khi gọi - hai lớp cho một mặt fail-open thật.

**Dấu che không mang số lượng.** Hai entity cùng điền vào một slot đang bị che
cho ra đúng một chuỗi giống nhau, nên nhìn từ ngoài không đếm được có bao nhiêu
giá trị bị che. Đó là chủ ý: "có 3 nguyên nhân bị che" tự nó đã là thông tin về
nội dung bị che. Cái giá là upstream khử trùng danh sách cạnh (`operate.py:893`
gom `tuple(e)` vào một `set`) nên vài cạnh đã che rụng bớt - đổi lại bằng một
dấu che có số thứ tự là mua lại đúng đường rò vừa bịt.

**Che không bỏ khóa khỏi bản ghi.** Che là thay giá trị. Bỏ khóa thì upstream
lọc rụng im lặng bản ghi mất `content` (`operate.py:860`) và nổ `KeyError` khi
mất `distance` (`operate.py:953`) - xa chỗ gây ra vài tầng.
"""

from typing import Any, Mapping

from core.keys import split_key
from core.permission import PermissionContext
from core.slots import OWNER_SLOT, SLOT_ROLE_SET, SLOT_ROLES

# Danh sách đóng, sống cạnh interface. Method đọc public mới của adapter mà
# chưa khai vào đây là CI fail (`tests/test_phan_chieu_che.py`, chạy trên cả ba
# adapter). Các method đọc ngoài danh sách được xử lý tường minh chỗ khác, và
# lý do khai ngay cạnh từng adapter trong test đó: `node_degree`/`edge_degree`
# co theo filter quyền, `has_node`/`has_edge` trả False cho mục ngoài quyền,
# `all_keys`/`filter_keys` của đường KV chỉ trả id nên chúng lọc theo tập khóa
# thay vì che.
MASKED_READ_METHODS: frozenset[str] = frozenset(
    {"query", "get_node", "get_edge", "get_node_edges", "get_by_id", "get_by_ids"}
)

# Namespace mà cửa fail-closed hỏi. `allowed_keys["chunks"]` và
# `allowed_keys["entities"]` đều là tập con của `allowed_keys["hyperedges"]` vì
# ngưỡng L2 chặt hơn L1 trên cùng tập scope, nên một câu hỏi duy nhất đúng cho
# cả ba đường đọc. Quan hệ bao hàm đó được canh ở
# `tests/test_tang_che.py::test_mot_cua_fail_closed_dung_cho_ca_ba_duong_doc`,
# cùng chỗ canh rằng tên này còn là một namespace có thật của bảng chính sách.
MASK_NAMESPACE: str = "hyperedges"

# Tên hai trường của bản ghi "cạnh có vai". Chúng là hợp đồng giữa tầng che và
# adapter graph, nên chúng sống ở đây và adapter nhập lại - một hằng, một chỗ.
# `slot` cố ý không trùng với bất kỳ tên nào trong 8 vai; `neighbor_id` cố ý
# không phải `source`, vì `source` *là* một trong 8 vai và hai nghĩa trùng tên
# trong một dict là một lỗi chờ sẵn.
SLOT_FIELD: str = "slot"
NEIGHBOR_FIELD: str = "neighbor_id"

# Dấu che, dạng máy đọc được `[{slot}:{lý do}]`. Tầng trên đọc ra được vai nào
# đã bị che và vì lý do gì mà không phải đoán từ một chuỗi sao. Nhãn tiếng Việt
# hiển thị ("[nguyên nhân: đã che]") map từ đây nhưng sống ở `web/`, không ở
# `core/`.
#
# Hai lý do vì hai luật khác nguồn: `masked` là luật của bảng chính sách (loại
# nội dung này đang ở L1 và bảng khai vai đó phải che), `group` là luật AD-9
# (slot `owner` luôn tổng quát hóa về mức vai/nhóm, kể cả ở L2). Trộn chúng
# thành một chuỗi là mất khả năng phân biệt "đổi bảng thì hết che" với
# "luôn che".
MASK_REASON_POLICY: str = "masked"
MASK_REASON_OWNER: str = "group"

# Lý do thứ ba, cho trường **không** phải slot. `description` của một node
# entity là văn bản LLM viết lại từ chính giá trị slot đã sinh ra nó
# (`operate.py:177-210`, và `:194-196` còn gộp mô tả qua nhiều hyperedge bằng
# `GRAPH_FIELD_SEP.join`), nên nó là nội dung nhạy cảm - nhưng nhìn từ một node
# lẻ ta không biết node đó điền vào vai nào, vì cùng một entity điền vào những
# vai khác nhau ở những hyperedge khác nhau. Vậy lý do đúng không phải một vai
# slot mà là ngưỡng: mô tả entity chỉ vào ngữ cảnh khi vai đạt L2 với nguồn
# (NFR-06, FR-05).
MASK_REASON_L2_ONLY: str = "l2_only"


class MaskItemOutOfPermission(RuntimeError):
    """Một bản ghi tới tầng che mang khóa nằm ngoài tập L1+ của vai.

    Nghĩa là filter phía trên đã hỏng: adapter nào cũng lọc theo tập khóa
    trước khi gọi tầng che, nên chuyện này không có ca vận hành hợp lệ. Che nó
    bằng luật của một loại nội dung mà vai không được thấy là fail-open im
    lặng - `masked_slots` không khai gì cho loại đó, nên kết quả sẽ đúng là
    "không che gì".

    `code` là mã lỗi API ổn định để test assert trên `code`, không trên thông
    điệp (AD-8, Consistency Conventions).
    """

    code = "MASK_ITEM_OUT_OF_PERMISSION"


class SlotRoleUnknown(ValueError):
    """Tên vai slot ngoài danh mục 8 vai của `core/` tới được tầng che.

    Hai đường dẫn tới đây và cả hai đều là hỏng. `dau_che` là hàm public mà
    `web/` ánh xạ nhãn tiếng Việt từ đó, nên một tên lạ sinh ra một dấu che
    không tầng nào đọc được. Còn một bản ghi cạnh khai `slot` ngoài danh mục
    là một vai mà `masked_slots` không bao giờ tra trúng, tức là nội dung của
    nó không bao giờ bị che - bỏ qua im lặng ở đó chính là fail-open.

    Khác `adapters.neo4j.SlotRoleInvalid`, cửa canh đường *ghi*: cửa này canh
    đường *đọc*, và nó phải tồn tại riêng vì dữ liệu có thể đã nằm trong kho từ
    trước khi cửa ghi có mặt.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp.
    """

    code = "SLOT_ROLE_UNKNOWN"


def dau_che_truong(ten_truong: str, ly_do: str) -> str:
    """Dấu che của một trường bất kỳ: `[{tên trường}:{lý do}]`.

    Dùng cho trường không phải vai slot - hôm nay chỉ có `description` của node
    entity. Tên trường thay chỗ tên vai vì đó đúng là thứ người đọc cần biết:
    trường nào của bản ghi đã bị thay, và vì luật nào.
    """
    return f"[{ten_truong}:{ly_do}]"


def dau_che(slot: str) -> str:
    """Dấu che của một vai slot, kèm lý do bị che.

    Public vì `web/` ánh xạ nhãn hiển thị từ chính danh mục này; tên ngoài
    danh mục 8 vai là lỗi, không phải một dấu che lạ.
    """
    if slot not in SLOT_ROLE_SET:
        raise SlotRoleUnknown(
            f"vai slot {slot!r} không có trong danh mục 8 vai của core/:"
            " không dựng được dấu che cho một vai không ai khai"
        )
    ly_do = MASK_REASON_OWNER if slot == OWNER_SLOT else MASK_REASON_POLICY
    return dau_che_truong(slot, ly_do)


def la_dau_che(gia_tri) -> bool:
    """Giá trị này có đúng là một dấu che *theo slot* do tầng che sinh ra không.

    Cần vì dấu che đi vào **vị trí id**: `get_node_edges` thay tên node lân cận
    bằng dấu che, rồi `operate.py:1036` mang chính chuỗi đó đi hỏi `get_node`.
    Adapter phải nhận ra "id này là thứ tôi vừa sinh ra" để trả về một node đã
    che thay vì `None` (`operate.py:1024-1047` trải `{**n, ...}` mà không lọc
    `None`).

    Nhận diện bằng cách **dựng lại**, không bằng `startswith("[")`: danh mục
    chỉ có 8 vai nên hỏi thẳng "chuỗi này có đúng bằng dấu che của một vai nào
    không". Cùng thủ pháp với `core.keys.split_key`, và cùng lý do - một tên
    entity thật bắt đầu bằng dấu ngoặc vuông không được nhận nhầm thành dấu
    che, vì nhận nhầm nghĩa là một fact có thật biến mất khỏi ngữ cảnh, thay
    bằng một node rỗng.

    Không tự parse lại hình dạng dấu che: một bộ nhận diện viết riêng là bản
    thứ hai của cùng một luật, và hai bản thì trôi dạt được. Ở đây `dau_che` là
    nguồn duy nhất, nên đổi hình dạng dấu che không thể làm hỏng phép nhận diện.
    """
    return isinstance(gia_tri, str) and any(
        gia_tri == dau_che(slot) for slot in SLOT_ROLES
    )


def mask(result: Any, context: PermissionContext, hyperedge_key: str) -> Any:
    """Che nội dung theo chính sách slot trước khi kết quả rời adapter.

    Ngữ cảnh hệ thống đọc thô: trả nguyên trạng, không tra bảng chính sách.
    Ingest cần điều này - `_merge_nodes_then_upsert` của upstream đọc
    `get_node` rồi ghi thẳng `description` cũ vào bản mới (`operate.py:194`),
    nên một mô tả đã che chạy qua đó sẽ ghi đè mô tả thật trong graph.

    Ngoài ra, ba bước. Tách loại nội dung từ khóa hyperedge; kiểm khóa còn nằm
    trong quyền của vai (fail-closed); rồi thay giá trị của những slot phải
    che, theo cả hai hình dạng bản ghi mô tả ở đầu file.

    Cửa fail-closed ở đây *chính là* điều kiện nền mà `core/permission.py` nói
    tới cho `grant_ids` ("vai hiện tại còn thấy hyperedge từ L1 trở lên"): khóa
    đã có trong tay đúng ở chỗ này. Epic 5 dựng đường nâng quyền thì nới đúng
    cửa này, không mở một đường bỏ che thứ hai ở tầng khác.

    Tập slot phải che là phần bảng khai cho loại nội dung đó, hợp với `owner`.
    Hai luật khác nguồn nên chúng gặp nhau ở đây chứ không trộn sẵn trong bảng:
    validator của story 1.2 chặn `owner` xuất hiện trong `masked_slots`, và
    `slots_to_mask` chỉ trả về phần YAML khai. Bảng chỉ khai được `masked_slots`
    cho loại nội dung đang ở L1, nên ở L2 tập này rỗng và chỉ còn `owner`.
    """
    if context.bypass_filter:
        return result
    if not isinstance(result, Mapping):
        raise TypeError(
            f"tầng che nhận một bản ghi dạng ánh xạ, nhận được {type(result).__name__}:"
            " che là thay giá trị theo tên trường, không phải biến đổi văn bản"
        )
    _, content_type = split_key(hyperedge_key)
    if hyperedge_key not in context.keys_for(MASK_NAMESPACE):
        raise MaskItemOutOfPermission(
            f"bản ghi mang khóa {hyperedge_key!r} tới tầng che nhưng vai"
            f" {context.role!r} không thấy khóa đó từ mức L1 trở lên: filter"
            " phía trên đã hỏng, và che tiếp là fail-open im lặng"
        )
    phai_che = set(context.slots_to_mask(content_type)) | {OWNER_SLOT}

    da_che = dict(result)
    # Đường một: khóa của bản ghi chính là tên vai slot.
    for slot in phai_che:
        if slot in da_che:
            da_che[slot] = dau_che(slot)
    # Đường hai: bản ghi tự khai vai của nó và mang tên node lân cận điền vào
    # vai đó. Cạnh chưa khai vai vẫn ghi được ở story 1.4 (prompt trích xuất 8
    # vai thuộc story 2.4), nên `slot` vắng hoặc None là hiện trạng hợp lệ.
    # Một tên *khác* thì không: nó không tra trúng `masked_slots` bao giờ, nên
    # bỏ qua im lặng là để nguyên văn đi ra.
    vai_canh = da_che.get(SLOT_FIELD)
    if vai_canh is not None:
        if not isinstance(vai_canh, str) or vai_canh not in SLOT_ROLE_SET:
            raise SlotRoleUnknown(
                f"bản ghi cạnh khai {SLOT_FIELD}={vai_canh!r}, ngoài danh mục 8"
                " vai của core/: tầng che không tra được luật nào cho nó"
            )
        if vai_canh in phai_che and NEIGHBOR_FIELD in da_che:
            da_che[NEIGHBOR_FIELD] = dau_che(vai_canh)
    return da_che
