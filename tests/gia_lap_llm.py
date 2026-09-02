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

from pathlib import Path
from typing import Callable

from adapters.llm_wrapper import KetQuaEmbedding, KetQuaLLM
from adapters.model_catalog import DanhMucModel, tai_danh_muc_model
from core.audit import SuKienAudit
from hypergraphrag.prompt import PROMPTS
from tests.gia_lap_qdrant import vector_tu_chuoi

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

    def __init__(self, phan_hoi: str | None = None, theo_prompt: Callable[[str], str] | None = None):
        self.phan_hoi = phan_hoi if phan_hoi is not None else phan_hoi_tu_khoa()
        # Story 2.3: đường ingest thật gọi LLM một lần cho mỗi chunk, và bộ test
        # pipeline cần mỗi chunk ra một tập fact *xác định*. `theo_prompt` nhận
        # nguyên văn prompt (upstream nhét chunk vào đó) và trả câu trả lời;
        # `None` là hành vi cũ, một phản hồi cho mọi lời gọi.
        self.theo_prompt = theo_prompt
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
        if self.theo_prompt is not None:
            return self.theo_prompt(prompt)
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


# --- Story 2.2: provider giả, sổ audit bộ nhớ, danh mục model giả -----------
#
# Wrapper của `adapters/llm_wrapper.py` bọc một *provider* (thứ trả nội dung
# kèm token), không bọc hàm LLM. Hai bản giả dưới đây là provider; `LLMGia` ở
# trên vẫn là chỗ ghi nhật ký prompt, `NhaCungCapGia` chỉ dịch messages về
# lại lời gọi `llm(prompt, system_prompt=...)` mà bộ test đã quen đọc.

DUONG_DAN_DANH_MUC_GIA: Path = (
    Path(__file__).resolve().parent / "fixtures" / "danh-muc-model-gia.yaml"
)
MODEL_LLM_GIA: str = "llm-gia"
MODEL_EMBEDDING_GIA: str = "embedding-gia"
MODEL_LLM_CUC_BO_GIA: str = "llm-cuc-bo-gia"
MODEL_EMBEDDING_CUC_BO_GIA: str = "embedding-cuc-bo-gia"
NCC_GIA: str = "gia"
NCC_CUC_BO_GIA: str = "ollama_gia"


def danh_muc_gia() -> DanhMucModel:
    """Danh mục giả, nạp qua đúng loader của hệ."""
    return tai_danh_muc_model(DUONG_DAN_DANH_MUC_GIA)


class NhaCungCapGia:
    """Provider LLM giả: chuyển messages về `LLMGia`, trả token cố định.

    `loi` khác None thì lời gọi ném đúng exception đó thay vì trả kết quả -
    dựng ca "provider hỏng". `cuc_bo` và `ten` chỉnh được để dựng ca space
    `real` với provider cục bộ/API ngoài.
    """

    def __init__(
        self,
        llm: LLMGia | None = None,
        *,
        ten: str = NCC_GIA,
        cuc_bo: bool = False,
        token_vao: int = 12,
        token_ra: int = 34,
        loi: BaseException | None = None,
        san_sang: bool = True,
    ):
        self.llm = llm if llm is not None else LLMGia()
        self.ten = ten
        self.cuc_bo = cuc_bo
        self.token_vao = token_vao
        self.token_ra = token_ra
        self.loi = loi
        # Câu trả lời của `san_sang()`: pipeline ingest hỏi nó trên space `real`
        # (story 2.3); `False` dựng ca "ollama chết".
        self._san_sang = san_sang
        self.loi_goi: list[tuple[str, list[dict], dict]] = []

    async def san_sang(self) -> bool:
        return self._san_sang

    async def hoan_thanh(self, model: str, messages: list[dict], **kwargs) -> KetQuaLLM:
        self.loi_goi.append((model, list(messages), dict(kwargs)))
        if self.loi is not None:
            raise self.loi
        system_prompt = None
        con_lai = list(messages)
        if con_lai and con_lai[0]["role"] == "system":
            system_prompt = con_lai.pop(0)["content"]
        prompt = con_lai.pop()["content"]
        noi_dung = await self.llm(
            prompt, system_prompt=system_prompt, history_messages=con_lai, **kwargs
        )
        return KetQuaLLM(noi_dung=noi_dung, token_vao=self.token_vao, token_ra=self.token_ra)

    @property
    def so_lan(self) -> int:
        return len(self.loi_goi)


class EmbeddingGia:
    """Provider embedding giả: vector hash của `tests/gia_lap_qdrant`, token cố định."""

    def __init__(
        self,
        *,
        ten: str = NCC_GIA,
        cuc_bo: bool = False,
        token_vao: int | None = None,
        loi: BaseException | None = None,
        san_sang: bool = True,
    ):
        self.ten = ten
        self.cuc_bo = cuc_bo
        self.token_vao = token_vao
        self.loi = loi
        self._san_sang = san_sang
        self.loi_goi: list[tuple[str, list[str]]] = []

    async def san_sang(self) -> bool:
        return self._san_sang

    async def nhung(self, model: str, texts: list[str]) -> KetQuaEmbedding:
        self.loi_goi.append((model, list(texts)))
        if self.loi is not None:
            raise self.loi
        token = self.token_vao if self.token_vao is not None else sum(
            len(t.split()) for t in texts
        )
        return KetQuaEmbedding(vector=[vector_tu_chuoi(t) for t in texts], token_vao=token)

    @property
    def so_lan(self) -> int:
        return len(self.loi_goi)


class SoAuditBoNho:
    """Audit port trong bộ nhớ: giữ mọi sự kiện theo thứ tự ghi.

    `loi` khác None thì `ghi` ném exception đó - dựng ca "port audit hỏng".
    """

    def __init__(self, *, loi: BaseException | None = None):
        self.su_kien: list[SuKienAudit] = []
        self.loi = loi

    async def ghi(self, su_kien: SuKienAudit) -> None:
        if self.loi is not None:
            raise self.loi
        self.su_kien.append(su_kien)

    def cac_su_kien(self, event: str | None = None) -> list[SuKienAudit]:
        return [sk for sk in self.su_kien if event is None or sk.event == event]

    def xoa(self) -> None:
        self.su_kien.clear()
