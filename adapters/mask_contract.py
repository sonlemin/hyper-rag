"""Hợp đồng của tầng che, nhìn từ phía adapter (AD-9).

`core/masking.py` chốt chữ ký; file này chốt hai điều mà *mọi* adapter phải
làm giống nhau khi gọi hàm che, và chốt ở một chỗ để hai adapter không trôi dạt
thành hai luật:

- che mà không có khóa của hyperedge thì không phải là che. Khóa vắng nghĩa là
  `masked_slots` không tra trúng gì, tức là không che gì - đúng kiểu mặc định
  fail-open mà cả Epic 1 dựng ra để chống;
- `mask` dựng một bản ghi mới có cùng tập khóa, không loại bản ghi khỏi kết
  quả. Muốn giấu hẳn một mục thì chính method đọc phải lọc mục đó ra, vì một
  `None` lọt vào danh sách kết quả sẽ nổ tận trong `vendor/`, xa chỗ gây ra vài
  tầng. Story 1.6 chốt chiều "dựng bản mới" chứ không phải "sửa tại chỗ": kho
  KV giữ bản gốc chưa che dùng chung cho mọi vai.

Story 1.3 phát hiện hai luật này ở đường vector; story 1.4 gặp lại nguyên vẹn
ở đường graph. Chúng sống ở đây thay vì trong `core/` vì đây là chuyện của tầng
adapter (`core/` giữ ngân sách 500-800 dòng và không biết gì về kho).
"""


class MaskContractViolated(RuntimeError):
    """Tầng che trả về một giá trị rỗng hoặc mất trường thay cho một bản ghi.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp
    (AD-8, Consistency Conventions).
    """

    code = "MASK_CONTRACT_VIOLATED"


class HyperedgeKeyMissing(RuntimeError):
    """Một bản ghi rời adapter mà không truy ra được khóa hyperedge để che.

    Chỉ xảy ra khi dữ liệu trong kho hỏng (mục ghi không qua adapter, hoặc cạnh
    nối sai phía trong đồ thị hai phía), nên đây là hỏng dữ liệu chứ không phải
    ca vận hành bình thường. Vẫn phải nổ.
    """

    code = "HYPEREDGE_KEY_MISSING"


def kiem_ket_qua_che(da_che, truoc_khi_che: dict, mo_ta: str) -> dict:
    """Chốt hợp đồng sau mỗi lời gọi `mask`: không rỗng, không mất trường."""
    if not da_che:
        raise MaskContractViolated(
            f"tầng che trả {da_che!r} cho {mo_ta}: muốn giấu hẳn một mục thì"
            " method đọc phải lọc nó khỏi kết quả, không đưa giá trị rỗng ra"
        )
    thieu = set(truoc_khi_che) - set(da_che)
    if thieu:
        raise MaskContractViolated(
            f"tầng che bỏ mất trường {sorted(thieu)} của {mo_ta}: che là thay"
            " nội dung, không phải bỏ khóa khỏi bản ghi"
        )
    return da_che
