"""Chuẩn hóa id node và sinh point id Qdrant - một nơi duy nhất.

Upstream bọc tên node bằng dấu nháy kép (`"App01"`) khi ghi ra graph. Nếu mỗi
adapter tự gỡ theo cách riêng thì id ở Neo4j và ở Qdrant lệch nhau, và test
NFR-03 (so id join chéo hai kho) mất ý nghĩa. Cả hai adapter gọi hàm ở đây.
"""

import re
import unicodedata
import uuid

# Namespace UUID5 cố định của dự án, đặt cạnh hàm chuẩn hóa theo spine.
# Sinh một lần bằng uuid5(NAMESPACE_DNS, "hyper-rag-copilot.node-id") rồi ghim
# thành hằng: đổi giá trị này là đổi mọi point id đã ghi, phải re-ingest.
ID_NAMESPACE: uuid.UUID = uuid.UUID("93cef57c-8531-53de-a55f-dbe2449c3d9d")


def normalize_id(raw: str) -> str:
    """Chuẩn hóa Unicode về NFC, bỏ khoảng trắng thừa và dấu nháy kép bao quanh.

    Bước NFC không phải làm cho đẹp: tiếng Việt gõ dạng tổ hợp (NFD) và dạng
    dựng sẵn (NFC) là hai chuỗi byte khác nhau, để nguyên thì cùng một thực thể
    ra hai id và hai UUID5 - đúng thứ module này sinh ra để chống.
    """
    if not isinstance(raw, str):
        raise TypeError(f"id phải là chuỗi, nhận được {type(raw).__name__}")
    ten = unicodedata.normalize("NFC", raw).strip()
    while len(ten) >= 2 and ten[0] == '"' and ten[-1] == '"':
        ten = ten[1:-1].strip()
    if not ten:
        raise ValueError(f"id rỗng sau khi chuẩn hóa: {raw!r}")
    return ten


def point_id(raw: str) -> str:
    """Point id Qdrant = UUID5 từ id đã chuẩn hóa; id gốc giữ trong payload."""
    return str(uuid.uuid5(ID_NAMESPACE, normalize_id(raw)))


# Tập ký tự của `space`. Chữ cái mở đầu rồi chữ, số, gạch dưới - đủ cho quy ước
# hiện có (`synth`, `test_3fa9c1d2_synth`) và an toàn ở cả hai kho: tên
# collection Qdrant là `{space}_{namespace}`, còn nhãn Neo4j của story 1.4 phải
# viết được mà không cần dấu nháy ngược. Không cho dấu cách, dấu chấm, gạch
# ngang: mỗi thứ đó là một ca phải trích dẫn ở đâu đó, và trích dẫn sai một chỗ
# là truy vấn trỏ nhầm không gian dữ liệu.
_SPACE_HOP_LE = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
SPACE_MAX_LEN: int = 64

# Không gian dữ liệu thật đã khử nhạy cảm (AD-12, story 2.11). Luật của nó nằm ở
# đây, cạnh hình dạng của `space`, vì "space nào là real" là một tính chất của
# tên không gian chứ không phải của từng nơi gọi tự đoán: wrapper LLM (2.2) hỏi
# để chặn provider API ngoài, adapter kho (2.11) sẽ hỏi cùng câu đó.
SPACE_REAL: str = "real"

# Không gian chứa **cùng tập tài liệu đã khử** của `real` nhưng trích bằng
# provider API ngoài **có chủ đích** (story 2.13, ADR-013). Tên nằm cạnh
# `SPACE_REAL` chứ không ở `eval/`: nó tồn tại để *không* khớp `la_space_real`,
# và một hằng đặt ở tầng trên thì luật và ca kiểm luật ở hai tầng khác nhau -
# `tests/test_wrapper_llm.py` phải import từ module dựng HTML để chấm một luật
# của `core/`. Ở đây thì hằng và luật đọc được cùng một chỗ.
#
# NFR-05 cấm gửi tài liệu **chưa khử** ra API ngoài và cho hai đường ngang nhau
# (khử trước, hoặc chạy cục bộ); ràng buộc "chỉ provider cục bộ" của AD-12 gắn
# với **tên space**, không với bộ dữ liệu. Nên tên này phải hợp lệ theo
# `validate_space` và phải trả `False` ở `la_space_real` - hai điều đó là hợp
# đồng, không phải một sự trùng hợp, và test khóa cả hai.
SPACE_THAT_KHU: str = "that_khu"


def la_space_real(space: str) -> bool:
    """`space` có thuộc không gian dữ liệu thật không.

    Đúng khi `space` là `real` hoặc đoạn cuối của nó là `real` (không phân
    biệt hoa thường), theo quy ước
    prefix gấp *vào trong* tên không gian (`test_3fa9c1d2_synth`, xem
    `tests/conftest.py::session_prefix`): loại của một không gian là đoạn cuối
    tên nó. Phía an toàn là phía dương - một tên kết thúc bằng `_real` mà không
    định là real thì chỉ mất quyền gọi API ngoài, còn chiều ngược lại là gửi
    dữ liệu thật ra ngoài.
    """
    validate_space(space)
    # Không phân biệt hoa thường: `validate_space` cho phép chữ hoa, và
    # `TEST_REAL` mà không phải real là một không gian thật gọi API ngoài.
    thuong = space.lower()
    return thuong == SPACE_REAL or thuong.endswith(f"_{SPACE_REAL}")


def validate_space(space: str) -> str:
    """Kiểm `space` trước khi nó thành tên collection và nhãn graph (AD-12).

    Cách ly theo `space` là chiều cách ly dữ liệu của hệ, nên hình dạng của nó
    là chuyện của `core/`, không phải của từng adapter tự đoán. Trả lại chính
    chuỗi đó để nơi gọi dùng được trực tiếp; không cắt khoảng trắng, vì một
    `space` lệch một dấu cách là hai không gian khác nhau chứ không phải một.
    """
    if not isinstance(space, str):
        raise TypeError(f"space phải là chuỗi, nhận được {type(space).__name__}")
    if len(space) > SPACE_MAX_LEN:
        raise ValueError(f"space dài quá {SPACE_MAX_LEN} ký tự: {space!r}")
    if not _SPACE_HOP_LE.match(space):
        raise ValueError(
            f"space {space!r} không hợp lệ: bắt đầu bằng chữ cái, sau đó chỉ"
            " chữ, số và gạch dưới"
        )
    return space
