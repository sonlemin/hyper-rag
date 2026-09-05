"""Một cửa dùng chung cho luật "tập khóa đọc của một lời gọi".

Cùng vai trò với `adapters/mask_contract.py`, cho luật đứng ngay cạnh nó. Ba
adapter đều phải trả lời cùng một câu trước mỗi lần đọc kho, và câu trả lời có
**ba** nhánh chứ không hai:

1. **Đọc thô.** Ngữ cảnh hệ thống (`bypass_filter`) không mang `allowed_keys`;
   pipeline ingest chạy dưới cờ này. Hỏi `keys_for` ở đây là lỗi lập trình và
   `core.permission` dội `SystemContextRawRead` đúng vì thế.
2. **Không thấy gì.** Vai có ngữ cảnh nhưng tập khóa của namespace rỗng. Nhánh
   đúng là **không chạm kho**. Gửi `IN []` xuống Neo4j, hay nạp file rồi lọc ra
   hết ở KV, đều cho *đúng kết quả* nhưng biến "không có quyền" thành một lần
   đọc kho bình thường - và một đường đọc bình thường là chỗ một lần sửa sau
   này nới ra được mà không ai thấy.
3. **Lọc theo tập khóa.** Tập không rỗng đi vào mệnh đề lọc của kho.

Tập rỗng và "đọc thô" vì vậy **không được là cùng một giá trị**: chúng có nghĩa
ngược hẳn nhau.

**Vì sao gom.** Trước story này luật sống ở ba hình dạng, mỗi adapter một kiểu:
`Neo4jACLGraphStorage._co_khoa_de_doc` trả `bool` gộp nhánh 1 với nhánh 3;
`JsonACLKVStorage` tách làm hai hàm `_khoa_duoc_phep` (trả `frozenset | None`)
cộng `_khong_thay_gi`; còn `QdrantVectorDBStorage.query` viết thẳng trong thân
hàm, không hằng và không method. Cả ba hành xử đúng và cả ba có test, nhưng
retro Epic 1 (F5) chỉ ra rủi ro cụ thể: Epic 5 nới quyền cho break-glass phải
sửa **ba chỗ có ba hình dạng khác nhau**, và bỏ sót một chỗ là fail-open im lặng
ở đúng đường đó. Retro Epic 2 gặp lại đúng khiếm khuyết ở `eval/`
(`SPACE_GHI_TRONG_REPO` ba bản), nên đây là mẫu lặp chứ không phải một ca lẻ.

Tầng che thì đã gom được về một cửa từ story 1.3 (`adapters/mask_contract.py`)
và giữ nguyên suốt hai epic. Module này là cùng một phép gom, cho luật đứng ngay
cạnh nó.

**Không đổi hành vi.** Ba adapter giữ nguyên method của mình làm lớp mỏng gọi
xuống đây, nên mọi test cũ chạy không sửa. Cái đổi là chỗ *luật* sống.

Chỉ stdlib cộng `core/`. Không biết gì về kho, đúng chiều import của AD-1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class NguCanhDoc(Protocol):
    """Phần `PermissionContext` mà cửa này cần. Đủ để test dựng một bản giả."""

    @property
    def bypass_filter(self) -> bool: ...

    def keys_for(self, namespace: str) -> frozenset[str]: ...


@dataclass(frozen=True, slots=True)
class KhoaDoc:
    """Kết quả phân giải tập khóa đọc cho một namespace.

    `doc_tho=True` thì `khoa` luôn rỗng, và **không được đọc `khoa`** như một
    tập khóa: ngữ cảnh hệ thống không có tập khóa nào, nó bỏ qua bộ lọc. Dùng
    `doc_tho` để rẽ nhánh trước, đúng thứ tự mà `core.permission.keys_for` bắt.
    """

    doc_tho: bool
    khoa: frozenset[str]

    @property
    def khong_thay_gi(self) -> bool:
        """Vai có ngữ cảnh nhưng không khóa nào: mọi mục vắng mặt.

        Đây là nhánh **không chạm kho**. Nó khác `doc_tho` ở chỗ ngược hẳn: một
        bên thấy tất, một bên không thấy gì.
        """
        return not self.doc_tho and not self.khoa

    @property
    def loc_theo(self) -> frozenset[str] | None:
        """Tập khóa để dựng mệnh đề lọc, hoặc `None` nghĩa là không lọc.

        Hình dạng cũ của adapter KV, giữ lại vì nó là hình dạng đúng cho một
        đường đọc *có* lọc từng bản ghi. Trả `None` ở nhánh đọc thô chứ không
        trả tập rỗng: tập rỗng có nghĩa ngược lại.
        """
        return None if self.doc_tho else self.khoa


def khoa_doc(context: NguCanhDoc, namespace: str) -> KhoaDoc:
    """Phân giải tập khóa đọc của `context` trong `namespace`.

    Không gọi `keys_for` khi `bypass_filter`: ngữ cảnh hệ thống không mang
    `allowed_keys` và `core.permission.keys_for` dội `SystemContextRawRead`
    đúng vì thế. Thứ tự hai dòng dưới đây là một phần của hợp đồng, không phải
    một tinh chỉnh.

    `keys_for` vẫn dội `KeyError` cho một namespace không có trong ngữ cảnh, và
    cửa này **không** nuốt lỗi đó: một namespace gõ sai phải nổ ra chứ không
    được lặng lẽ thành "không thấy gì".
    """
    if context.bypass_filter:
        return KhoaDoc(doc_tho=True, khoa=frozenset())
    return KhoaDoc(doc_tho=False, khoa=context.keys_for(namespace))
