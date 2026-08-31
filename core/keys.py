"""Khóa lọc quyền: một field keyword, hai thành phần (AD-4, NFR-06).

`key = "{scope}:{content_type}"` là hàm thuần của thuộc tính dữ liệu, tính lúc
ingest. Nó cố ý không đọc bảng chính sách: nhờ vậy đổi bảng chính sách không
chạm payload đã ghi, đó là điều làm cho hot-swap (NFR-04) và độ trễ hiệu lực
quyền một truy vấn (NFR-09) thành có thể.

Bảng chính sách chỉ ánh xạ vai người hỏi ra *tập* khóa được phép, ở `policy.py`.
"""

KEY_SEPARATOR: str = ":"


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
