"""Wrapper LLM/embedding: token thật, chi phí theo danh mục, kiểm space, ghi audit.

Seam đo của FR-30 (story 2.2). Engine chỉ nhận hàm đã bọc ở đây - `EngineACL`
từ chối hàm trần lúc dựng - nên "mọi lời gọi LLM/embedding đều ghi token, chi
phí và model" là một tính chất cấu trúc chứ không phải một quy ước.

Vì sao gọi SDK provider thay vì bọc hàm của upstream: `openai_complete_if_cache`
(`vendor/hypergraphrag/llm.py`) chỉ trả `content` và bỏ `usage`. Bọc nó thì
phải đếm lại bằng tiktoken, tức một con số ước lượng cho một FR đòi "chi phí
thực tế". Gọi SDK trực tiếp cho token đúng như hóa đơn, và `vendor/` vẫn không
bị sửa: engine nhận wrapper qua chính hai field `llm_model_func` /
`embedding_func` mà upstream để ngỏ.

Thứ tự của một lời gọi, và vì sao thứ tự đó không đổi được:

1. đọc ngữ cảnh quyền - thiếu là `PermissionContextMissing` dội thẳng lên,
   LLM không được gọi ngoài ngữ cảnh (fail-closed);
2. kiểm provider theo space (AD-12): space `real` chỉ nhận provider cục bộ,
   vi phạm là `ProviderNotAllowedForSpace` **trước khi gửi bất kỳ byte nào**;
3. `stream=True` bị từ chối (chưa có đường đếm token trên stream);
4. gọi provider; SDK hỏng thì lỗi dội nguyên lên và **không** có sự kiện chi
   phí - không có `usage` thì không có số, ghi 0 token cho một lời gọi hỏng là
   làm sai mẫu số của ngoại suy. Phản hồi thiếu `usage` cũng là lỗi
   (`ProviderUsageMissing`), không phải một hàng 0 token;
5. ghi sự kiện chi phí ở tầng observation: port audit hỏng thì WARNING, nội
   dung vẫn trả về.

Chi phí là một hàng một lời gọi, không cộng dồn trong tiến trình; Postgres
cộng bằng SUM (FR-25 đọc lũy kế từ đó). Không cache, không retry riêng ngoài
retry sẵn có của SDK.
"""

import asyncio
import os
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Mapping, Protocol, Sequence

import numpy as np
import ollama
from hypergraphrag.utils import EmbeddingFunc
from openai import AsyncOpenAI

from adapters.model_catalog import (
    LOAI_EMBEDDING,
    LOAI_LLM,
    DanhMucModel,
    MucModel,
    danh_muc_mac_dinh,
)
from core.audit import (
    EVENT_EMBEDDING_COST,
    EVENT_LLM_COST,
    TIER_OBSERVATION,
    AuditPort,
    SuKienAudit,
    ghi_quan_sat,
    thoi_diem_utc,
)
from core.ids import la_space_real
from core.permission import PermissionContext, current_context

# --- Mã lỗi -----------------------------------------------------------------


class ProviderNotAllowedForSpace(PermissionError):
    """Space `real` gọi một provider không cục bộ (AD-12, NFR-05)."""

    code = "PROVIDER_NOT_ALLOWED_FOR_SPACE"


class LLMStreamNotSupported(ValueError):
    """Upstream truyền `stream=True`: chưa có đường đếm token trên stream."""

    code = "LLM_STREAM_NOT_SUPPORTED"


class ModelProviderMismatch(ValueError):
    """Model thuộc một nhà cung cấp khác với provider được tiêm."""

    code = "MODEL_PROVIDER_MISMATCH"


class ProviderConfigMissing(ValueError):
    """Thiếu biến môi trường mà danh mục nói provider cần (key, host, tên model)."""

    code = "PROVIDER_CONFIG_MISSING"


class ProviderUsageMissing(RuntimeError):
    """Phản hồi provider không mang `usage` hay nội dung: không có số để ghi.

    Một lời gọi không đếm được thì là lỗi nhìn thấy được, không phải một hàng
    audit 0 token làm sai mẫu số của ngoại suy FR-30.
    """

    code = "PROVIDER_USAGE_MISSING"


class ProviderKwargUnknown(ValueError):
    """Upstream gửi một kwarg sinh mà provider này không có chỗ đặt.

    Chuyển mù xuống SDK là hoặc `TypeError` trần, hoặc tệ hơn, một tham số bị
    lặng lẽ bỏ qua (Ollama đọc tham số sinh từ `options=`, không từ kwargs
    phẳng). Từ chối có mã để chỗ sai hiện đúng tên tham số.
    """

    code = "PROVIDER_KWARG_UNKNOWN"


class EmbeddingShapeMismatch(RuntimeError):
    """Provider trả sai số vector hoặc sai số chiều so với danh mục.

    Số chiều là kích thước collection Qdrant; một vector lệch chiều lọt xuống
    adapter là lỗi của Qdrant nói về kích thước, không nói về model.
    """

    code = "EMBEDDING_SHAPE_MISMATCH"


# --- Kết quả và hợp đồng provider -------------------------------------------


@dataclass(frozen=True)
class KetQuaLLM:
    noi_dung: str
    token_vao: int
    token_ra: int


@dataclass(frozen=True)
class KetQuaEmbedding:
    vector: Sequence[Sequence[float]]
    token_vao: int


class NhaCungCapLLM(Protocol):
    """Một provider LLM: tên khớp danh mục, cờ cục bộ, và một lời gọi trả token."""

    ten: str
    cuc_bo: bool

    async def hoan_thanh(
        self, model: str, messages: list[dict], **kwargs: Any
    ) -> KetQuaLLM: ...


class NhaCungCapEmbedding(Protocol):
    ten: str
    cuc_bo: bool

    async def nhung(self, model: str, texts: list[str]) -> KetQuaEmbedding: ...


def _sao_chep_bang(gia_tri):
    """Bản sao dict/list thường của một bảng (có thể là `MappingProxyType` lồng nhau) để SDK tuần tự hóa."""
    if isinstance(gia_tri, Mapping):
        return {k: _sao_chep_bang(v) for k, v in gia_tri.items()}
    if isinstance(gia_tri, (list, tuple)):
        return [_sao_chep_bang(v) for v in gia_tri]
    return gia_tri


def _so_token(gia_tri, ten: str, ncc: str) -> int:
    if gia_tri is None:
        raise ProviderUsageMissing(f"phản hồi của {ncc!r} thiếu {ten}")
    return int(gia_tri)


class OpenAITuongThich:
    """DeepSeek và OpenAI qua `AsyncOpenAI(base_url, api_key)`; token từ `response.usage`.

    `client` tiêm được để test dịch phản hồi SDK mà không mở mạng; mặc định tự
    dựng từ `api_key`/`base_url`. `extra_body` (story 2.4) là bảng tham số
    riêng của provider lấy từ danh mục model (ví dụ `thinking: {type: disabled}`
    của DeepSeek), chuyển nguyên vẹn thành `extra_body=` của SDK ở mỗi lời gọi
    chat; `None` là không gửi tham số đó.
    """

    cuc_bo: bool = False

    def __init__(
        self,
        *,
        ten: str,
        api_key: str | None = None,
        base_url: str | None = None,
        client=None,
        extra_body: Mapping[str, Any] | None = None,
    ):
        self.ten = ten
        self.extra_body = None if extra_body is None else _sao_chep_bang(extra_body)
        self._client = (
            AsyncOpenAI(api_key=api_key, base_url=base_url) if client is None else client
        )

    async def hoan_thanh(self, model: str, messages: list[dict], **kwargs) -> KetQuaLLM:
        if self.extra_body is not None:
            # Gộp với `extra_body` của nơi gọi (nếu có), của danh mục thắng ở
            # khóa trùng; không đè im lặng cả bảng của nơi gọi.
            kwargs = {
                **kwargs,
                "extra_body": {
                    **_sao_chep_bang(kwargs.get("extra_body") or {}),
                    **_sao_chep_bang(self.extra_body),
                },
            }
        response = await self._client.chat.completions.create(
            model=model, messages=messages, **kwargs
        )
        choices = getattr(response, "choices", None)
        if not choices:
            raise ProviderUsageMissing(f"phản hồi của {self.ten!r} không có choices")
        usage = getattr(response, "usage", None)
        if usage is None:
            raise ProviderUsageMissing(f"phản hồi của {self.ten!r} thiếu usage")
        return KetQuaLLM(
            noi_dung=choices[0].message.content or "",
            token_vao=_so_token(getattr(usage, "prompt_tokens", None), "usage.prompt_tokens", self.ten),
            token_ra=_so_token(
                getattr(usage, "completion_tokens", None), "usage.completion_tokens", self.ten
            ),
        )

    async def san_sang(self) -> bool:
        """API ngoài không có phép thăm dò rẻ; sẵn sàng hay không lộ ra ở lời gọi đầu."""
        return True

    async def nhung(self, model: str, texts: list[str]) -> KetQuaEmbedding:
        response = await self._client.embeddings.create(
            model=model, input=texts, encoding_format="float"
        )
        usage = getattr(response, "usage", None)
        if usage is None:
            raise ProviderUsageMissing(f"phản hồi embedding của {self.ten!r} thiếu usage")
        data = getattr(response, "data", None)
        if data is None:
            raise ProviderUsageMissing(f"phản hồi embedding của {self.ten!r} không có data")
        return KetQuaEmbedding(
            vector=[dp.embedding for dp in data],
            token_vao=_so_token(getattr(usage, "prompt_tokens", None), "usage.prompt_tokens", self.ten),
        )


# Tham số sinh theo kiểu OpenAI -> tên trong `options` của Ollama (SDK 0.6:
# `AsyncClient.chat(model, messages, *, format, options, keep_alive, ...)`).
# `response_format` đi vào `format`, không vào `options`.
_OPTIONS_OLLAMA: dict[str, str] = {
    "max_tokens": "num_predict",
    "temperature": "temperature",
    "top_p": "top_p",
    "seed": "seed",
    "stop": "stop",
}
_KWARGS_OLLAMA_GIU_NGUYEN: frozenset[str] = frozenset({"keep_alive", "options"})


def _kwargs_ollama(kwargs: Mapping[str, Any], ten: str) -> dict[str, Any]:
    """Dịch kwargs sinh của upstream sang chữ ký `AsyncClient.chat`; lạ thì từ chối."""
    ket_qua: dict[str, Any] = {}
    options: dict[str, Any] = dict(kwargs.get("options") or {})
    for khoa, gia_tri in kwargs.items():
        if khoa in _OPTIONS_OLLAMA:
            options[_OPTIONS_OLLAMA[khoa]] = gia_tri
        elif khoa == "response_format":
            ket_qua["format"] = _format_ollama(gia_tri, ten)
        elif khoa in _KWARGS_OLLAMA_GIU_NGUYEN:
            if khoa != "options":
                ket_qua[khoa] = gia_tri
        else:
            raise ProviderKwargUnknown(
                f"provider {ten!r} không biết đặt kwarg {khoa!r} vào đâu"
                f" (biết: {sorted(_OPTIONS_OLLAMA | {'response_format': ''})})"
            )
    if options:
        ket_qua["options"] = options
    return ket_qua


def _format_ollama(response_format, ten: str):
    """`{"type": "json_object"}` -> `"json"`; `json_schema` -> chính lược đồ (dict)."""
    if isinstance(response_format, Mapping):
        kieu = response_format.get("type")
        if kieu == "json_object":
            return "json"
        if kieu == "json_schema":
            schema = (response_format.get("json_schema") or {}).get("schema")
            if isinstance(schema, Mapping):
                return dict(schema)
    raise ProviderKwargUnknown(
        f"provider {ten!r} không dịch được response_format {response_format!r}"
    )


# Thời hạn (giây) cho phép thăm dò `san_sang()` của Ollama: một daemon treo
# không được giữ pipeline treo theo; quá hạn là "chưa sẵn sàng".
THOI_HAN_SAN_SANG: float = 5.0


class OllamaCucBo:
    """Ollama qua `ollama.AsyncClient`; token từ `prompt_eval_count` / `eval_count`.

    Kwargs sinh của upstream (`max_tokens`, `temperature`...) đi vào `options=`
    theo `_OPTIONS_OLLAMA`; `response_format` thành `format=`; kwarg lạ là
    `ProviderKwargUnknown`, không chuyển mù.

    `client` tiêm được, cùng lý do với `OpenAITuongThich`.
    """

    cuc_bo: bool = True

    def __init__(self, *, ten: str, host: str | None = None, client=None):
        self.ten = ten
        self._client = ollama.AsyncClient(host=host) if client is None else client

    async def san_sang(self) -> bool:
        """Ollama có trả lời không: một `list()` rẻ, hỏng vì bất cứ gì là chưa sẵn sàng.

        Pipeline ingest hỏi câu này trước khi chạm kho trên space `real`
        (AD-12): không có nhánh fallback sang API ngoài, nên "chưa sẵn sàng"
        phải nhìn thấy được trước lời gọi tốn tiền đầu tiên.
        """
        try:
            await asyncio.wait_for(self._client.list(), timeout=THOI_HAN_SAN_SANG)
        except Exception:
            # `TimeoutError` của `wait_for` cũng là `Exception`: treo là chưa sẵn sàng.
            return False
        return True

    async def hoan_thanh(self, model: str, messages: list[dict], **kwargs) -> KetQuaLLM:
        response = await self._client.chat(
            model=model, messages=messages, **_kwargs_ollama(kwargs, self.ten)
        )
        message = getattr(response, "message", None)
        if message is None:
            raise ProviderUsageMissing(f"phản hồi của {self.ten!r} không có message")
        return KetQuaLLM(
            noi_dung=message.content or "",
            token_vao=_so_token(
                getattr(response, "prompt_eval_count", None), "prompt_eval_count", self.ten
            ),
            token_ra=_so_token(getattr(response, "eval_count", None), "eval_count", self.ten),
        )

    async def nhung(self, model: str, texts: list[str]) -> KetQuaEmbedding:
        response = await self._client.embed(model=model, input=texts)
        embeddings = getattr(response, "embeddings", None)
        if embeddings is None:
            raise ProviderUsageMissing(f"phản hồi embedding của {self.ten!r} không có embeddings")
        return KetQuaEmbedding(
            vector=list(embeddings),
            token_vao=_so_token(
                getattr(response, "prompt_eval_count", None), "prompt_eval_count", self.ten
            ),
        )


# --- Dấu nhận wrapper ---------------------------------------------------------

# Thuộc tính gắn lên hàm/`EmbeddingFunc` đã bọc. `limit_async_func_call` của
# upstream dùng `functools.wraps`, và `wraps` sao chép `__dict__` của thứ nó bọc,
# nên dấu sống sót qua lớp giới hạn đồng thời đó. Giá trị là một sentinel so
# bằng `is`, để một thuộc tính trùng tên đặt tay không qua được cửa.
DAU_WRAPPER: str = "_hyper_rag_wrapper"
_DAU = object()
# Provider đứng sau hàm bọc, gắn cùng chỗ với dấu wrapper và sống sót qua
# `functools.wraps` theo cùng cách. Pipeline ingest (2.3) đọc nó để hỏi
# `cuc_bo`/`san_sang()` trước khi chạm kho trên space `real`.
DAU_NHA_CUNG_CAP: str = "_hyper_rag_ncc"


def _theo_chuoi_boc(ham):
    """Duyệt chuỗi bọc: `__wrapped__` của `functools.wraps`, `.func` của `partial`.

    Giới hạn số bước để một chuỗi vòng không treo cửa kiểm.
    """
    for _ in range(16):
        if ham is None:
            return
        yield ham
        if isinstance(ham, partial):
            ham = ham.func
        else:
            ham = getattr(ham, "__wrapped__", None)


def la_wrapper(ham) -> bool:
    """Hàm này có phải wrapper của dự án, kể cả sau khi upstream bọc thêm lớp.

    `functools.wraps` để lại `__wrapped__` và sao chép `__dict__`, còn `partial`
    (upstream bind `hashing_kv` bằng partial rồi mới `wraps`) giữ hàm gốc ở
    `.func` và không sao chép `__dict__`, nên phải đi theo cả hai.
    """
    return any(getattr(h, DAU_WRAPPER, None) is _DAU for h in _theo_chuoi_boc(ham))


def nha_cung_cap_cua(ham):
    """Provider đứng sau một hàm đã bọc (kể cả sau lớp bọc của upstream), hoặc `None`."""
    for h in _theo_chuoi_boc(ham):
        ncc = getattr(h, DAU_NHA_CUNG_CAP, None)
        if ncc is not None:
            return ncc
    return None


# --- Sự kiện chi phí -----------------------------------------------------------

# Tên trường trong `chi_tiet`. Hiện thực Postgres cộng theo đúng các tên này,
# nên chúng là hợp đồng giữa wrapper và `api/audit_postgres.py`.
CT_MODEL: str = "model"
CT_NHA_CUNG_CAP: str = "nha_cung_cap"
CT_TOKEN_VAO: str = "token_vao"
CT_TOKEN_RA: str = "token_ra"
CT_CHI_PHI_USD: str = "chi_phi_usd"
CT_DANH_MUC_VERSION: str = "danh_muc_version"


def su_kien_chi_phi(
    event: str,
    ngu_canh: PermissionContext,
    muc: MucModel,
    danh_muc: DanhMucModel,
    token_vao: int,
    token_ra: int,
) -> SuKienAudit:
    """Một hàng chi phí cho một lời gọi, tier observation."""
    return SuKienAudit(
        tier=TIER_OBSERVATION,
        event=event,
        space=ngu_canh.space,
        policy_version=ngu_canh.policy_version,
        thoi_diem=thoi_diem_utc(),
        act=ngu_canh.real_account,
        role=ngu_canh.role,
        hyperedge_ids=(),
        chi_tiet={
            CT_MODEL: muc.ten,
            CT_NHA_CUNG_CAP: muc.nha_cung_cap,
            CT_TOKEN_VAO: token_vao,
            CT_TOKEN_RA: token_ra,
            CT_CHI_PHI_USD: muc.chi_phi_usd(token_vao, token_ra),
            CT_DANH_MUC_VERSION: danh_muc.version,
        },
    )


def _kiem_space(ngu_canh: PermissionContext, nha_cung_cap) -> None:
    if la_space_real(ngu_canh.space) and not nha_cung_cap.cuc_bo:
        raise ProviderNotAllowedForSpace(
            f"space {ngu_canh.space!r} là không gian dữ liệu thật, chỉ gọi được"
            f" provider cục bộ; {nha_cung_cap.ten!r} là API ngoài (AD-12)"
        )


def _kiem_khop_provider(muc: MucModel, nha_cung_cap) -> None:
    if nha_cung_cap.ten != muc.nha_cung_cap or bool(nha_cung_cap.cuc_bo) != muc.cuc_bo:
        raise ModelProviderMismatch(
            f"model {muc.ten!r} thuộc nhà cung cấp {muc.nha_cung_cap!r}"
            f" (cuc_bo={muc.cuc_bo}), nhưng provider tiêm vào là"
            f" {nha_cung_cap.ten!r} (cuc_bo={bool(nha_cung_cap.cuc_bo)})"
        )


def _kiem_hinh_dang(ket_qua: KetQuaEmbedding, so_van_ban: int, muc: MucModel) -> None:
    vector = ket_qua.vector
    if len(vector) != so_van_ban:
        raise EmbeddingShapeMismatch(
            f"model {muc.ten!r} trả {len(vector)} vector cho {so_van_ban} văn bản"
        )
    for i, v in enumerate(vector):
        if len(v) != muc.so_chieu:
            raise EmbeddingShapeMismatch(
                f"model {muc.ten!r}: vector thứ {i} có {len(v)} chiều, danh mục khai {muc.so_chieu}"
            )


# --- Hai hàm bọc ---------------------------------------------------------------


def bo_llm(
    *,
    nha_cung_cap: NhaCungCapLLM,
    model: str,
    audit: AuditPort,
    danh_muc: DanhMucModel | None = None,
) -> Callable[..., Any]:
    """Hàm LLM cho `llm_model_func` của engine, chữ ký khớp hàm upstream.

    Model không có trong danh mục là lỗi ở đây, lúc dựng, không phải lúc gọi.
    """
    danh_muc = danh_muc_mac_dinh() if danh_muc is None else danh_muc
    muc = danh_muc.muc(model, loai=LOAI_LLM)
    _kiem_khop_provider(muc, nha_cung_cap)

    async def llm(prompt, system_prompt=None, history_messages=None, **kwargs) -> str:
        ngu_canh = current_context()
        _kiem_space(ngu_canh, nha_cung_cap)
        # Hai kwargs của upstream mà provider không hiểu, nuốt như hàm upstream.
        kwargs.pop("hashing_kv", None)
        kwargs.pop("keyword_extraction", None)
        if kwargs.pop("stream", False):
            raise LLMStreamNotSupported(
                "wrapper chưa đếm được token trên stream; gọi với stream=False"
            )
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(history_messages or [])
        messages.append({"role": "user", "content": prompt})
        ket_qua = await nha_cung_cap.hoan_thanh(muc.ten, messages, **kwargs)
        await ghi_quan_sat(
            audit,
            su_kien_chi_phi(
                EVENT_LLM_COST, ngu_canh, muc, danh_muc, ket_qua.token_vao, ket_qua.token_ra
            ),
        )
        return ket_qua.noi_dung

    setattr(llm, DAU_WRAPPER, _DAU)
    setattr(llm, DAU_NHA_CUNG_CAP, nha_cung_cap)
    return llm


def bo_embedding(
    *,
    nha_cung_cap: NhaCungCapEmbedding,
    model: str,
    audit: AuditPort,
    danh_muc: DanhMucModel | None = None,
) -> EmbeddingFunc:
    """`EmbeddingFunc` cho `embedding_func` của engine; số chiều lấy từ danh mục."""
    danh_muc = danh_muc_mac_dinh() if danh_muc is None else danh_muc
    muc = danh_muc.muc(model, loai=LOAI_EMBEDDING)
    _kiem_khop_provider(muc, nha_cung_cap)

    async def func(texts: list[str]) -> np.ndarray:
        ngu_canh = current_context()
        _kiem_space(ngu_canh, nha_cung_cap)
        van_ban = list(texts)
        ket_qua = await nha_cung_cap.nhung(muc.ten, van_ban)
        _kiem_hinh_dang(ket_qua, len(van_ban), muc)
        await ghi_quan_sat(
            audit,
            su_kien_chi_phi(
                EVENT_EMBEDDING_COST, ngu_canh, muc, danh_muc, ket_qua.token_vao, 0
            ),
        )
        return np.array(ket_qua.vector)

    ham = EmbeddingFunc(
        embedding_dim=muc.so_chieu, max_token_size=muc.max_token, func=func
    )
    setattr(ham, DAU_WRAPPER, _DAU)
    setattr(ham, DAU_NHA_CUNG_CAP, nha_cung_cap)
    return ham


# --- Dựng từ môi trường --------------------------------------------------------

# Biến môi trường mà đường sản phẩm đọc để chọn model. Nguồn của chúng là
# `docker-compose.yml` (service `api`) và `.env.server`/`.env.laptop`; test
# `tests/test_compose_ha_tang.py` canh cả hai đầu.
BIEN_LLM_MODEL: str = "LLM_MODEL"
BIEN_EMBEDDING_MODEL: str = "EMBEDDING_MODEL"
BIEN_OLLAMA_HOST: str = "OLLAMA_HOST"
BIEN_MOI_TRUONG_MODEL: tuple[str, ...] = (
    BIEN_LLM_MODEL,
    BIEN_EMBEDDING_MODEL,
    BIEN_OLLAMA_HOST,
)


@dataclass(frozen=True)
class HamModel:
    """Cặp hàm đã bọc cộng ngữ cảnh tối đa của LLM, để engine không đọc cấu hình chết.

    `llm_max_token` đi vào `llm_model_max_token_size` của `HyperGraphRAG`
    (`operate.py:62` dùng nó để cắt mô tả gộp trước khi tóm tắt).
    """

    llm: Callable[..., Any]
    embedding: EmbeddingFunc
    llm_max_token: int


def cau_hinh_model_tu_moi_truong(moi_truong: Mapping[str, str] | None = None) -> dict[str, str]:
    """Ba biến chọn model, cùng luật với `cau_hinh_kho_tu_moi_truong`.

    Biến rỗng tính là chưa đặt; khoảng trắng bao quanh bị cắt. Trả dict theo
    tên biến để nơi gọi tra bằng chính hằng ở trên.
    """
    nguon = os.environ if moi_truong is None else moi_truong
    cau_hinh: dict[str, str] = {}
    for ten_bien in BIEN_MOI_TRUONG_MODEL:
        gia_tri = nguon.get(ten_bien)
        if gia_tri is None:
            continue
        gon = str(gia_tri).strip()
        if gon:
            cau_hinh[ten_bien] = gon
    return cau_hinh


def nha_cung_cap_tu_moi_truong(
    muc: MucModel,
    danh_muc: DanhMucModel,
    moi_truong: Mapping[str, str] | None = None,
):
    """Provider thật cho một mục model, key/host đọc từ biến mà danh mục chỉ định.

    Thiếu key là lỗi ở đây, trước khi engine dựng: một client OpenAI với
    `api_key=None` chỉ nổ ở lời gọi đầu tiên, với thông điệp nói về HTTP 401.
    """
    nguon = os.environ if moi_truong is None else moi_truong
    ncc = danh_muc.nha_cung_cap_cua(muc)
    if ncc.cuc_bo:
        host = (nguon.get(ncc.bien_host) or "").strip() or None
        return OllamaCucBo(ten=ncc.ten, host=host)
    api_key = (nguon.get(ncc.bien_api_key) or "").strip()
    if not api_key:
        raise ProviderConfigMissing(
            f"nhà cung cấp {ncc.ten!r} cần biến môi trường {ncc.bien_api_key}"
            f" (model {muc.ten!r}); key chỉ đọc từ .env gốc repo"
        )
    return OpenAITuongThich(
        ten=ncc.ten, api_key=api_key, base_url=ncc.base_url, extra_body=muc.extra_body
    )


def ham_tu_moi_truong(
    *,
    audit: AuditPort,
    danh_muc: DanhMucModel | None = None,
    moi_truong: Mapping[str, str] | None = None,
) -> HamModel:
    """Hàm LLM, `EmbeddingFunc` đã bọc và ngữ cảnh LLM, từ `LLM_MODEL`/`EMBEDDING_MODEL`."""
    danh_muc = danh_muc_mac_dinh() if danh_muc is None else danh_muc
    cau_hinh = cau_hinh_model_tu_moi_truong(moi_truong)
    thieu = [b for b in (BIEN_LLM_MODEL, BIEN_EMBEDDING_MODEL) if b not in cau_hinh]
    if thieu:
        raise ProviderConfigMissing(f"thiếu biến môi trường chọn model: {thieu}")
    muc_llm = danh_muc.muc(cau_hinh[BIEN_LLM_MODEL], loai=LOAI_LLM)
    muc_emb = danh_muc.muc(cau_hinh[BIEN_EMBEDDING_MODEL], loai=LOAI_EMBEDDING)
    return HamModel(
        llm=bo_llm(
            nha_cung_cap=nha_cung_cap_tu_moi_truong(muc_llm, danh_muc, moi_truong),
            model=muc_llm.ten,
            audit=audit,
            danh_muc=danh_muc,
        ),
        embedding=bo_embedding(
            nha_cung_cap=nha_cung_cap_tu_moi_truong(muc_emb, danh_muc, moi_truong),
            model=muc_emb.ten,
            audit=audit,
            danh_muc=danh_muc,
        ),
        llm_max_token=muc_llm.max_token,
    )
