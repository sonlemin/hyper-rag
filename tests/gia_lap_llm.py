"""LLM giả cho đường truy vấn của upstream (story 1.7).

Bộ Đo 1 nền phải chạy không mạng và không key LLM, nhưng `kg_query` **bắt
buộc** gọi một lần LLM trước khi chạm kho nào: `use_model_func(hint_prompt)`
(`operate.py:541`) trích từ khóa, và không có từ khóa thì hàm trả sớm bằng
`PROMPTS["fail_response"]`. Nên đường e2e cần một hàm LLM trả lời đúng định
dạng mà bộ parser của fork này đọc được.

Định dạng đó **không phải JSON**. Fork HyperGraphRAG thay prompt trích xuất từ
khóa của LightRAG bằng chính `PROMPTS["entity_extraction"]`
(`operate.py:525-541`) và tự parse các bản ghi dạng
`("entity"<|>...)##("hyper-relation"<|>...)<|COMPLETE|>`:

- bản ghi 5 trường mở đầu bằng `"entity"` cho từ khóa mức thấp (đi vào
  `entities_vdb.query`);
- bản ghi 3 trường mở đầu bằng `"hyper-relation"` cho từ khóa mức cao (đi vào
  `hyperedges_vdb.query`).

Thiếu một trong hai nhánh là `kg_query` bỏ luôn nhánh đó, nên bản giả này luôn
trả đủ cả hai. Dấu phân tách lấy thẳng từ `PROMPTS`, không viết cứng: đổi dấu
phân tách bên upstream mà bản giả không đổi theo thì test sẽ đỏ ở chỗ nói đúng
nguyên nhân.

Từ khóa cố ý **trung tính**: chúng chỉ là chuỗi đem đi embed, và embedding giả
(`tests/gia_lap_qdrant.embedding_gia`) cho cosine ≥ 0.354 với mọi chuỗi, nên
tập kết quả do *bộ lọc quyền* quyết định chứ không do nội dung câu hỏi. Nếu từ
khóa quyết định được kết quả thì test bảo mật đang đo nhầm thứ.

Đếm lời gọi là một phần của hợp đồng: với `only_need_context=True` phải có
**đúng một** lời gọi LLM (lời gọi trích từ khóa), không có lời gọi sinh câu trả
lời (`operate.py:596` trả thẳng chuỗi ngữ cảnh, bỏ `:606`). Đó là cách bộ test
chứng minh mình assert trên ngữ cảnh truy hồi chứ không trên câu trả lời LLM
(chốt brief §6).
"""

from hypergraphrag.prompt import PROMPTS

TD: str = PROMPTS["DEFAULT_TUPLE_DELIMITER"]
RD: str = PROMPTS["DEFAULT_RECORD_DELIMITER"]
CD: str = PROMPTS["DEFAULT_COMPLETION_DELIMITER"]

# Từ khóa trung tính, không lấy từ nội dung nhạy cảm của fixture: một giá trị
# slot lọt vào đây là bộ test tự mớm câu trả lời cho chính nó.
TU_KHOA_ENTITY: str = "APP01"
TU_KHOA_HYPEREDGE: str = "su co ung dung"


def _ban_ghi_entity(ten: str) -> str:
    """Bản ghi 5 trường; `operate.py:557` chỉ đọc trường thứ hai."""
    return f'("entity"{TD}"{ten}"{TD}"KHAC"{TD}"tu khoa muc thap"{TD}"1.0")'


def _ban_ghi_hyperedge(cau: str) -> str:
    """Bản ghi 3 trường; `operate.py:555` chỉ đọc trường thứ hai."""
    return f'("hyper-relation"{TD}"{cau}"{TD}"1.0")'


def phan_hoi_tu_khoa(
    entity: str = TU_KHOA_ENTITY, hyperedge: str = TU_KHOA_HYPEREDGE
) -> str:
    """Chuỗi trả lời đúng định dạng mà `kg_query` parse được."""
    return (
        _ban_ghi_entity(entity) + RD + _ban_ghi_hyperedge(hyperedge) + CD
    )


class LLMGia:
    """Hàm LLM giả có ghi nhật ký prompt, gọi được như `llm_model_func`.

    Chữ ký khớp hợp đồng của upstream: `use_model_func(prompt)` lúc trích từ
    khóa và `use_model_func(query, system_prompt=..., stream=...)` lúc sinh câu
    trả lời. `hashing_kv` đi vào qua `partial` của
    `HyperGraphRAG.__post_init__` nên nó cũng phải nuốt được.

    Cố ý **không** phải dataclass: `HyperGraphRAG.__post_init__` chạy
    `asdict(self)` trên chính engine, và `dataclasses.asdict` đệ quy vào mọi
    field là dataclass. Một hàm LLM giả dạng dataclass sẽ bị trải thành dict
    trong `global_config`, tức bộ đồ đo tự đổi hình dạng của thứ nó đang đo.
    """

    def __init__(self, phan_hoi: str | None = None):
        self.phan_hoi = phan_hoi if phan_hoi is not None else phan_hoi_tu_khoa()
        self.prompts: list[str] = []
        # Lời gọi có `system_prompt` là lời gọi *sinh câu trả lời*. Đếm riêng,
        # vì một lời gọi như vậy trong bộ Đo 1 nghĩa là test đang đi qua đường
        # câu trả lời LLM chứ không dừng ở ngữ cảnh truy hồi.
        self.prompts_sinh_cau_tra_loi: list[str] = []
        # Kwargs của từng lời gọi, giữ nguyên. `HyperGraphRAG.__post_init__`
        # bind `hashing_kv=self.llm_response_cache` bằng `partial`
        # (`hypergraphrag.py:242-248`), nên đây là chỗ *duy nhất* nhìn thấy giá
        # trị thật đi xuống hàm LLM. Không ghi lại thì khẳng định "cache LLM
        # tắt" (AD-18) dừng ở thuộc tính của engine chứ không tới được đường
        # truy vấn.
        self.kwargs: list[dict] = []

    async def __call__(self, prompt, system_prompt=None, **kwargs) -> str:
        self.prompts.append(prompt)
        self.kwargs.append(dict(kwargs))
        if system_prompt is not None:
            self.prompts_sinh_cau_tra_loi.append(prompt)
        return self.phan_hoi

    @property
    def so_lan(self) -> int:
        return len(self.prompts)

    def xoa_nhat_ky(self) -> None:
        self.prompts.clear()
        self.prompts_sinh_cau_tra_loi.clear()
        self.kwargs.clear()


class MaHoaOffline:
    """Bộ đếm token thay `tiktoken`, dùng qua fixture `ma_hoa_offline`.

    Lý do và phạm vi áp dụng nằm ở docstring của fixture trong
    `tests/conftest.py`. Ở đây chỉ là phép đếm: byte UTF-8, tất định, không
    mạng.
    """

    @staticmethod
    def encode(noi_dung: str) -> list[int]:
        return list(noi_dung.encode("utf-8"))

    @staticmethod
    def decode(tokens: list[int]) -> str:
        return bytes(tokens).decode("utf-8", errors="ignore")
