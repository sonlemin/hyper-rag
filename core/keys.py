"""Khóa lọc quyền: một field keyword, hai thành phần (AD-4, NFR-06).

`key = "{scope}:{content_type}"` là hàm thuần của thuộc tính dữ liệu, tính lúc
ingest. Nó cố ý không đọc bảng chính sách: nhờ vậy đổi bảng chính sách không
chạm payload đã ghi, đó là điều làm cho hot-swap (NFR-04) và độ trễ hiệu lực
quyền một truy vấn (NFR-09) thành có thể.

Bảng chính sách chỉ ánh xạ vai người hỏi ra *tập* khóa được phép, ở `policy.py`.

Từ story 2.1 file này còn giữ luật **hợp nhất khóa đa nguồn** (FR-11): một id
xuất hiện trong nhiều tài liệu khác quyền nhận đúng một khóa, tính bằng hàm
thuần `hop_nhat_khoa`. Luật ở đây, không ở adapter: ba đường ghi đi qua một cửa
chung (`adapters/ingest_labels.ingest_key_for_write`) nên chúng không thể lệch
nhau về *quyết định*, và bước đối chiếu hai kho chỉ còn phải bắt lệch do sự cố.
"""

from typing import Mapping

KEY_SEPARATOR: str = ":"

# Tên field mang khóa lọc trong payload Qdrant và trên node Neo4j. Sống cạnh
# hàm dựng khóa vì hai thứ này là một hợp đồng: đổi tên field mà quên đổi chỗ
# đọc là mọi truy vấn lọc trượt, và filter trượt thì hoặc không ai thấy gì,
# hoặc ai cũng thấy tất. Một hằng, hai kho đọc chung (story 1.3 và 1.4).
#
# Đây cũng là *một* field duy nhất mà filter được phép chạm: `match_any` trên
# một field keyword, không AND đa điều kiện (FR-07, research về HNSW có lọc).
FILTER_KEY_FIELD: str = "filter_key"


def filter_key(scope: str, content_type: str) -> str:
    """Ghép khóa lọc từ scope và loại nội dung của một tài liệu.

    Ghép bằng bản đã cắt khoảng trắng: khóa lệch một dấu cách ghi vào payload là
    một mục vĩnh viễn không ai lọc trúng. Sai kiểu là `TypeError`, sai giá trị
    (rỗng, chứa dấu phân tách) là `ValueError` - hai lỗi khác nhau vì hai
    nguyên nhân khác nhau.
    """
    da_cat = []
    for ten, gia_tri in (("scope", scope), ("content_type", content_type)):
        if not isinstance(gia_tri, str):
            raise TypeError(f"{ten} phải là chuỗi, nhận được {type(gia_tri).__name__}")
        gon = gia_tri.strip()
        if not gon:
            raise ValueError(f"{ten} rỗng, không dựng được khóa lọc")
        if KEY_SEPARATOR in gon:
            raise ValueError(f"{ten} chứa dấu phân tách {KEY_SEPARATOR!r}: {gon}")
        da_cat.append(gon)
    return da_cat[0] + KEY_SEPARATOR + da_cat[1]


def split_key(key: str) -> tuple[str, str]:
    """Tách khóa lọc ngược lại thành `(scope, content_type)`.

    Tầng che nhận khóa của hyperedge (AD-9) nhưng tra `masked_slots` theo loại
    nội dung, nên phép tách này có thật và cần đúng một bản. Mỗi nơi tự
    `split(":")` một kiểu là đúng thứ mà việc gom tên field vào một hằng ở
    trên định tránh.

    Luật lỗi giống `filter_key`: sai kiểu là `TypeError`, sai dạng là
    `ValueError`. Kiểm bằng cách dựng lại khóa từ hai nửa vừa tách - nếu chuỗi
    vào không phải do `filter_key` sinh ra thì nó không khớp, và ta biết ngay
    thay vì trả về một nửa vô nghĩa.
    """
    if not isinstance(key, str):
        raise TypeError(f"khóa lọc phải là chuỗi, nhận được {type(key).__name__}")
    scope, dau, content_type = key.partition(KEY_SEPARATOR)
    if not dau:
        raise ValueError(f"khóa lọc {key!r} thiếu dấu phân tách {KEY_SEPARATOR!r}")
    if filter_key(scope, content_type) != key:
        raise ValueError(f"khóa lọc {key!r} không đúng dạng scope:content_type")
    return scope, content_type


# --- Hợp nhất khóa đa nguồn (story 2.1, FR-11) ---------------------------


class SensitivityRankUnknown(ValueError):
    """Loại nội dung không có hạng độ nhạy trong bảng cấu hình.

    Từ chối cả lô chứ không đoán một hạng mặc định: đoán thấp là nới quyền cho
    một loại nội dung chưa ai xét, đoán cao là giấu mất dữ liệu mà không ai
    biết. Cả hai đều im lặng, còn một lô bị từ chối thì nhìn thấy được.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp
    (AD-8, Consistency Conventions).
    """

    code = "SENSITIVITY_RANK_UNKNOWN"


class _ChuaGhi:
    """Kiểu của sentinel "id này chưa từng vào kho". Không tự nó là giá trị."""

    __slots__ = ()

    def __repr__(self) -> str:
        # Sentinel rơi vào một thông điệp lỗi mà in ra `<object object at 0x…>`
        # là một thông điệp không giúp được ai.
        return "CHUA_GHI"


# Hai sentinel, hai trạng thái khác nhau, và khác nhau là điều kiện để luật
# đúng. `CHUA_GHI` nghĩa là kho chưa có id này; `KHONG_KHOA` nghĩa là id đã có
# và đã hợp nhất ra "không khóa". Gộp chúng làm một thì lần nạp thứ ba (cùng
# scope với lần đầu) cấp lại khóa cho một id đa nguồn khác scope - đúng lỗ mà
# story này đóng.
#
# `KHONG_KHOA` là `None` chứ không phải một chuỗi khóa đặc biệt: một khóa
# `"__none__"` sẽ là một giá trị hợp lệ trong `match_any`, và chỉ cần một vai
# vô ý được cấp nó là mọi artifact đa nguồn khác scope đổ ra. Mỗi kho có nghĩa
# riêng cho `None` (vector xóa point, KV vô hình với mọi vai, graph giữ node
# cấu trúc không khóa), nhưng nguồn quyết định thì chỉ một.
CHUA_GHI: _ChuaGhi = _ChuaGhi()
KHONG_KHOA: None = None


def hop_nhat_khoa(khoa_cu, khoa_moi: str, *, hang: Mapping[str, int]) -> str | None:
    """Khóa của một id sau khi tài liệu mang `khoa_moi` chạm vào nó (FR-11).

    Hàm thuần, không I/O và không đọc bảng chính sách: `hang` là bảng hạng độ
    nhạy đã nạp, truyền vào như một tham số bình thường. Nhờ vậy luật này kiểm
    được mà không cần file, và bảng hạng đóng băng trước ingest là một quyết
    định của tầng cấu hình chứ không phải của luật.

    Ba nhánh, không có nhánh thứ tư:

    - `khoa_cu is CHUA_GHI` - id mới, khóa của tài liệu đang nạp thắng;
    - `khoa_cu is KHONG_KHOA` - trạng thái hút, mọi lần nạp sau vẫn không khóa.
      Nguồn khác scope đã chạm vào id này vẫn còn đó, nên cấp lại một khóa là
      để lộ đúng thứ vừa giấu đi;
    - hai khóa thật - cùng scope thì lấy hạng độ nhạy cao hơn, khác scope thì
      "không khóa".

    Kết quả không phụ thuộc thứ tự nạp, và đó là tính chất làm cho một đợt ingest
    chạy lại cho ra cùng một kho.
    """
    loai_moi = _loai_co_hang(khoa_moi, hang)
    if khoa_cu is CHUA_GHI:
        return khoa_moi
    if khoa_cu is KHONG_KHOA:
        return KHONG_KHOA
    if not isinstance(khoa_cu, str):
        raise TypeError(
            f"khóa cũ phải là chuỗi, CHUA_GHI hoặc KHONG_KHOA, nhận được"
            f" {type(khoa_cu).__name__}"
        )
    loai_cu = _loai_co_hang(khoa_cu, hang)
    scope_cu, _ = split_key(khoa_cu)
    scope_moi, _ = split_key(khoa_moi)
    if scope_cu != scope_moi:
        return KHONG_KHOA
    return khoa_cu if hang[loai_cu] >= hang[loai_moi] else khoa_moi


def _loai_co_hang(khoa: str, hang: Mapping[str, int]) -> str:
    """Loại nội dung của một khóa, sau khi chắc chắn nó có hạng độ nhạy."""
    _, content_type = split_key(khoa)
    if content_type not in hang:
        raise SensitivityRankUnknown(
            f"loại nội dung {content_type!r} không có hạng độ nhạy trong bảng"
            f" cấu hình (đang có {sorted(hang)}): không so được 'hạn chế nhất'"
        )
    return content_type
