"""Khóa lọc quyền: một field keyword, hai thành phần (AD-4, NFR-06).

`key = "{scope}:{content_type}"` là hàm thuần của thuộc tính dữ liệu, tính lúc
ingest. Nó cố ý không đọc bảng chính sách: nhờ vậy đổi bảng chính sách không
chạm payload đã ghi, đó là điều làm cho hot-swap (NFR-04) và độ trễ hiệu lực
quyền một truy vấn (NFR-09) thành có thể.

Bảng chính sách chỉ ánh xạ vai người hỏi ra *tập* khóa được phép, ở `policy.py`.
"""

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
