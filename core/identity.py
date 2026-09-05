"""Danh tính người hỏi, và đường từ danh tính sang ngữ cảnh quyền (story 1.7).

Trước story này, mọi ngữ cảnh quyền trong repo đều do test tự dựng bằng cách
gọi thẳng `user_context(role=..., real_account=...)` với vai viết trong chính
test. Điều đó đủ để kiểm adapter, nhưng nó không trả lời được câu hỏi của cổng
M1: *ai* là người hỏi, và vai của người đó đến từ đâu. Module này chốt câu trả
lời tối giản cho M1 - một bản ghi ba trường - và chốt luôn rằng chỉ có **một**
đường đi từ nó sang `PermissionContext`.

Tối giản là có chủ đích, không phải chưa làm xong. Thứ M1 cần chứng minh là ngữ
cảnh quyền *phát từ một danh tính* chứ không phải từ một hằng nằm trong test,
nên `DanhTinh` chỉ mang đúng ba thứ mà `user_context` đòi.

Story 3.1 thêm `TaiKhoan` **bọc** `DanhTinh` chứ không mở rộng nó: nhóm phụ
trách và hai cờ demo/admin là thuộc tính của *người*, không phải của ngữ cảnh
quyền, và một trường thừa trong `DanhTinh` là một trường đi theo mọi lời gọi
truy hồi mà không ai dùng. Hash mật khẩu thì không vào đây một chút nào - nó
dừng ở `adapters/identity_seed.py` và bảng `users` (AD-7), vì `core/` chỉ
stdlib nên nó không so được hash, và một trường hash ở đây lọt vào mọi `repr()`
của tầng trên. JWT và phiên đăng nhập ở `api/xac_thuc.py`.

Không có `grant_ids` ở đây: đường nâng quyền break-glass thuộc Epic 5, và một
trường rỗng nằm sẵn trong seed là một chỗ để ai đó điền vào trước khi cơ chế
kiểm nó tồn tại.

Hàm thuần, chỉ stdlib, không đọc file: nửa I/O (đọc YAML seed) nằm ở
`adapters/identity_seed.py`, cùng khuôn với cặp `core/policy.py` và
`adapters/policy_loader.py`.
"""

from dataclasses import dataclass

from core.ids import validate_space
from core.permission import PermissionContext, user_context
from core.policy import Policy


class RoleUnknown(ValueError):
    """Danh tính trỏ tới một vai không có trong bảng chính sách.

    `Policy.role` dội `KeyError` trần, và một `KeyError` không có `code` thì
    tầng API không đổi được thành `{error: {code, message}}` mà test assert lên
    (AD-8, Consistency Conventions). Cửa này đứng đúng chỗ hai nguồn gặp nhau -
    seed danh tính và bảng chính sách - nên nó là chỗ duy nhất biết đủ để nói
    tài khoản nào trỏ tới vai nào.

    Fail-closed: một vai lạ **không** thành một ngữ cảnh không thấy gì. Ngữ
    cảnh rỗng chạy tiếp được và trông giống hệt "người này không được xem gì",
    nên nó giấu mất một seed sai cho tới lúc có người hỏi vì sao mình không
    thấy tài liệu nào.
    """

    code = "ROLE_UNKNOWN"


@dataclass(frozen=True)
class DanhTinh:
    """Một tài khoản demo: ai, vai gì, đọc không gian nào.

    Đóng băng vì một danh tính đổi vai giữa chừng là leo quyền im lặng: ngữ
    cảnh quyền đã phát ra vẫn giữ vai cũ, còn lần phát sau lại ra vai mới, và
    audit không nhìn thấy chỗ nào đổi.

    `khong_gian` nằm trong danh tính chứ không phải trong request: cách ly theo
    `space` (AD-12) là thuộc tính của người hỏi, không phải một tham số mà
    người hỏi tự chọn. Bộ test đổi nó bằng `dataclasses.replace` để cách ly dữ
    liệu từng phiên, và đó là chỗ duy nhất nó được đổi - `replace` chạy lại
    `__post_init__` nên nó không đi vòng qua cửa kiểm nào.
    """

    tai_khoan: str
    vai: str
    khong_gian: str

    def __post_init__(self):
        for ten, gia_tri in (
            ("tai_khoan", self.tai_khoan),
            ("vai", self.vai),
            ("khong_gian", self.khong_gian),
        ):
            if not isinstance(gia_tri, str):
                raise TypeError(
                    f"{ten} phải là chuỗi, nhận được {type(gia_tri).__name__}"
                )
            if not gia_tri.strip():
                raise ValueError(f"{ten} rỗng, danh tính không định danh được")
            if gia_tri != gia_tri.strip():
                # `" ts01 "` là một tài khoản khác `"ts01"` mà nhìn không ra:
                # audit ghi một chuỗi, người đọc log thấy một chuỗi khác, và
                # `vai` lệch một dấu cách thì không tra trúng bảng chính sách.
                # Cắt hộ cũng sai - seed nói một đằng, hệ chạy một nẻo - nên
                # cửa này từ chối thay vì sửa.
                raise ValueError(
                    f"{ten} = {gia_tri!r} có khoảng trắng bao quanh: một danh"
                    " tính lệch một dấu cách là một danh tính khác"
                )
        # `khong_gian` đi thẳng vào tên collection Qdrant và nhãn Neo4j, nên nó
        # có luật riêng chặt hơn "chuỗi không rỗng" và luật đó sống ở
        # `core/ids.py`. Kiểm ngay lúc dựng danh tính chứ không đợi
        # `user_context`: seed nạp lúc khởi động, còn `user_context` chạy lúc có
        # người hỏi - một `khong_gian` sai ký tự phải hỏng ở bước nạp seed, chỗ
        # người sửa file còn đang nhìn vào file.
        validate_space(self.khong_gian)


@dataclass(frozen=True)
class TaiKhoan:
    """Một tài khoản đăng nhập được: danh tính, nhóm phụ trách, hai cờ quyền.

    Bọc `DanhTinh` chứ không mở rộng nó (story 3.1). `DanhTinh` là thứ đi vào
    `user_context` và vào `real_account` của audit; ba trường ấy đúng bằng thứ
    ngữ cảnh quyền cần, và một trường thừa ở đó là một trường đi theo mọi lời
    gọi truy hồi mà không ai dùng.

    **Hash mật khẩu không có mặt ở đây.** Nó sống ở loader `adapters/` và ở
    bảng `users` của Postgres, hai chỗ đã có I/O. `core/` chỉ stdlib (AD-1),
    nên một trường hash trong bản ghi này là một giá trị mà `core/` cầm mà
    không so được, và là một giá trị lọt vào mọi `repr()` của tầng trên.

    `nhom` là **nhóm phụ trách của người**, cùng danh mục với tên nhóm trong
    `config/nhom-phu-trach.yaml` (SPINE `:223`: `users.group_name` dùng chung
    giá trị với slot `owner`). Nó **không** phải một trục quyền: quyền vẫn là
    vai × loại nội dung × scope (AD-4), và `ngu_canh_cua` không đọc trường này.

    `demo` và `admin` là hai cờ riêng, không phải hai mức của một thang (spine
    `:105`): Admin là vai quản trị của PRD 1.5, tài khoản demo là tài khoản
    trình diễn. Chúng gắn theo tài khoản thật và chép nguyên vẹn sang token
    xem-như của Epic 4, nên trộn chúng thành một trường là mất đúng phép phân
    biệt mà AD-10 dựa vào.

    Đóng băng cùng lý do với `DanhTinh`: một tài khoản đổi cờ `admin` giữa
    chừng là leo quyền im lặng.
    """

    danh_tinh: DanhTinh
    nhom: str
    demo: bool = False
    admin: bool = False

    def __post_init__(self):
        if not isinstance(self.danh_tinh, DanhTinh):
            raise TypeError(
                "danh_tinh phải là DanhTinh, nhận được"
                f" {type(self.danh_tinh).__name__}"
            )
        if not isinstance(self.nhom, str):
            raise TypeError(f"nhom phải là chuỗi, nhận được {type(self.nhom).__name__}")
        if not self.nhom.strip():
            raise ValueError("nhom rỗng: tài khoản phải khai một nhóm phụ trách")
        if self.nhom != self.nhom.strip():
            # Cùng luật với ba trường của `DanhTinh`: tên nhóm đi vào bảng
            # `users`, vào claim của token và vào câu trả lời FR-14, nên một
            # dấu cách thừa là một nhóm khác mà nhìn không ra.
            raise ValueError(
                f"nhom = {self.nhom!r} có khoảng trắng bao quanh: một tên nhóm"
                " lệch một dấu cách là một tên nhóm khác"
            )
        for ten, gia_tri in (("demo", self.demo), ("admin", self.admin)):
            # `1` và `"true"` đều truthy, và một seed khai `admin: 1` chạy được
            # là một tài khoản được cấp quyền quản trị bởi một lỗi gõ.
            if not isinstance(gia_tri, bool):
                raise TypeError(
                    f"{ten} phải là bool, nhận được {type(gia_tri).__name__}"
                )

    @property
    def tai_khoan(self) -> str:
        """Tên tài khoản, tức khóa chính của bảng `users` và `sub` của token."""
        return self.danh_tinh.tai_khoan


def ngu_canh_cua(danh_tinh: DanhTinh, policy: Policy) -> PermissionContext:
    """Ngữ cảnh quyền của một danh tính, tính từ bảng chính sách đang hiệu lực.

    Hàm thuần: một phép tra bảng, không đọc kho, không đọc file. Đi qua đúng
    factory `core.permission.user_context` chứ không dựng thẳng
    `PermissionContext` - luật danh sách trắng của `tests/test_import_lint.py`
    canh điều đó, và lý do là nó cũng chặn việc tự chế một ngữ cảnh với
    `allowed_keys` bịa ra, đi vòng qua bảng chính sách.

    Vai không có trong bảng là `RoleUnknown`: một tài khoản seed trỏ tới vai
    không tồn tại phải hỏng ở đây, chứ không thành một ngữ cảnh không thấy gì
    mà cũng không ai biết vì sao.
    """
    if not isinstance(danh_tinh, DanhTinh):
        raise TypeError(
            "ngu_canh_cua cần một DanhTinh, nhận được"
            f" {type(danh_tinh).__name__}"
        )
    try:
        return user_context(
            policy=policy,
            role=danh_tinh.vai,
            space=danh_tinh.khong_gian,
            real_account=danh_tinh.tai_khoan,
        )
    except KeyError:
        raise RoleUnknown(
            f"tài khoản {danh_tinh.tai_khoan!r} khai vai {danh_tinh.vai!r},"
            " không có trong bảng chính sách đang hiệu lực"
        ) from None
