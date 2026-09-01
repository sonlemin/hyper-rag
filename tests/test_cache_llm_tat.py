"""1.5-UNIT-001: cache LLM tắt hẳn, hai lớp và một lý do (AD-18).

Lý do nằm ở `compute_args_hash(mode, query)` (`utils.py:106`): khóa cache
không có vai. Hai vai hỏi cùng một câu dùng chung một ô cache, nên câu trả lời
sinh cho vai rộng quyền hơn được phát lại nguyên văn cho vai hẹp hơn, trước cả
khi truy hồi kịp chạy. Bộ này ghim chính sự thật đó chứ không chỉ ghim cờ, để
ai muốn bật lại cache thì phải đọc lý do trước.

Hai lớp tắt:

1. cấu hình - `enable_llm_cache=False` làm `llm_response_cache is None`, và
   `hashing_kv=None` đi xuống hàm LLM; `handle_cache`/`save_to_cache` của
   upstream trả sớm khi thấy `None`;
2. mã - adapter KV từ chối được dựng cho namespace `llm_response_cache`, nên
   một cờ bật nhầm ở story 1.7 là nổ lúc dựng engine chứ không phải im lặng
   chạy cache qua adapter của mình.

Không mạng, không key LLM: engine chỉ được *dựng*, không truy vấn.
"""

import asyncio

import pytest
from hypergraphrag import HyperGraphRAG
from hypergraphrag.utils import CacheData, compute_args_hash, handle_cache, save_to_cache

from adapters.kv import ENABLE_LLM_CACHE, LLM_CACHE_NAMESPACE, JsonACLKVStorage, LLMCacheDisabled

CAU_HOI = "App01 trả lỗi 502 thì xử lý thế nào"


def llm_ghi_lai(da_goi: list):
    """Hàm LLM giả ghi lại kwargs mà upstream ghép vào lời gọi."""

    async def llm(prompt, **kwargs):
        da_goi.append(kwargs)
        return "trả lời giả"

    return llm


def dung_engine(workspace_dir, da_goi, **kwargs) -> HyperGraphRAG:
    """Engine upstream nguyên bản; story 1.7 mới nối adapter vào."""
    return HyperGraphRAG(
        working_dir=str(workspace_dir),
        llm_model_func=llm_ghi_lai(da_goi),
        **kwargs,
    )


# --- Lý do: khóa cache không mang vai ---------------------------------------


def test_khoa_cache_tinh_tu_dung_hai_thu_khong_thu_nao_mang_vai():
    """`kg_query` tính khóa cache từ đúng `mode` và câu hỏi (`operate.py:496`).

    Đây là lý do phải tắt chứ không phải cấu hình lại: không có chỗ nào trong
    khóa để nhét vai vào mà không sửa `vendor/`.

    Đọc thẳng lời gọi bằng AST, không so hai lần gọi cùng tham số với nhau:
    `compute_args_hash` khai là `def compute_args_hash(*args)` nên chữ ký của
    nó không nói gì, và hai lần gọi cùng tham số thì bằng nhau dù cơ chế quyền
    đúng hay sai. Thứ quyết định là *danh sách tham số tại chỗ gọi*, và đó là
    thứ đỏ được: thêm một tham số thứ ba, hay bỏ hẳn lời gọi, đều làm test này
    đỏ ở chỗ nói đúng nguyên nhân.
    """
    import ast
    import inspect

    from hypergraphrag import operate

    goi = [
        n
        for n in ast.walk(ast.parse(inspect.getsource(operate)))
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "compute_args_hash"
    ]
    assert goi, "upstream không còn gọi compute_args_hash: đọc lại AD-18"
    for n in goi:
        tham_so = [ast.unparse(a) for a in n.args]
        assert tham_so == ["query_param.mode", "query"], (
            f"lời gọi ở operate.py:{n.lineno} truyền {tham_so}: đầu vào của"
            " khóa cache đã đổi, đọc lại AD-18 trước khi bật cache"
        )


def test_khoa_cache_doi_theo_mode_va_cau_hoi():
    """Đối chứng của test trên: hai thứ đi vào khóa thật sự đổi được khóa.

    Không có ca này thì phép quét AST xanh cả khi `compute_args_hash` trở
    thành một hàm trả hằng, và lúc đó "hai vai chung một ô cache" vẫn đúng
    nhưng vì một lý do khác hẳn.
    """
    khoa = compute_args_hash("hybrid", CAU_HOI)
    assert compute_args_hash("naive", CAU_HOI) != khoa
    assert compute_args_hash("hybrid", CAU_HOI + "?") != khoa


def test_hashing_kv_none_thi_khong_co_duong_doc_ghi_cache():
    """Toàn bộ cơ chế mà `enable_llm_cache=False` dựa vào (`utils.py:450,509`)."""

    async def chay():
        doc = await handle_cache(None, compute_args_hash("hybrid", CAU_HOI), CAU_HOI)
        ghi = await save_to_cache(
            None,
            CacheData(
                args_hash=compute_args_hash("hybrid", CAU_HOI),
                content="trả lời của vai rộng quyền",
                prompt=CAU_HOI,
            ),
        )
        return doc, ghi

    doc, ghi = asyncio.run(chay())
    assert doc == (None, None, None, None)
    assert ghi is None


# --- Lớp 1: cấu hình engine -------------------------------------------------


def test_engine_tat_cache_thi_khong_dung_kho_cache(workspace_dir):
    """`enable_llm_cache=False`: `llm_response_cache is None`, không kho nào được dựng."""
    rag = dung_engine(workspace_dir, [], enable_llm_cache=ENABLE_LLM_CACHE)
    assert ENABLE_LLM_CACHE is False
    assert rag.llm_response_cache is None


def test_hashing_kv_truyen_xuong_ham_llm_la_none(workspace_dir):
    """`partial(llm_model_func, hashing_kv=...)` mang `None` xuống hàm LLM.

    Ghim ở đầu ra chứ không ở thuộc tính: đó là chỗ mà `handle_cache` thật sự
    đọc, và cũng là chỗ một thay đổi phía upstream sẽ lộ ra.
    """
    da_goi = []
    rag = dung_engine(workspace_dir, da_goi, enable_llm_cache=False)
    asyncio.run(rag.llm_model_func(CAU_HOI))
    assert len(da_goi) == 1
    assert da_goi[0]["hashing_kv"] is None


def test_cache_bat_thi_hashing_kv_khong_none(workspace_dir):
    """Đối chứng: với cờ bật, cùng đường đó mang một kho cache xuống.

    Không có ca này thì test trên xanh cả khi upstream bỏ hẳn tham số
    `hashing_kv`, và bộ test sẽ canh một cơ chế không còn tồn tại.
    """
    da_goi = []
    rag = dung_engine(workspace_dir, da_goi, enable_llm_cache=True)
    asyncio.run(rag.llm_model_func(CAU_HOI))
    assert rag.llm_response_cache is not None
    assert da_goi[0]["hashing_kv"] is rag.llm_response_cache


# --- Lớp 2: adapter từ chối dựng cho namespace cache ------------------------


def test_dung_adapter_cho_namespace_cache_la_loi(workspace_dir):
    """Cache LLM là quyết định cam kết, không phải mặc định đổi được bằng cờ."""
    with pytest.raises(LLMCacheDisabled) as loi:
        JsonACLKVStorage(
            namespace=LLM_CACHE_NAMESPACE,
            global_config={"working_dir": str(workspace_dir)},
            embedding_func=None,
        )
    assert loi.value.code == "LLM_CACHE_DISABLED"


def test_engine_bat_cache_voi_adapter_cua_minh_thi_no_luc_dung(workspace_dir, monkeypatch):
    """Cờ bật nhầm ở story 1.7: nổ ngay tại `__post_init__`, không chạy tiếp.

    Thay lớp KV mà `_get_storage_class()` trả về bằng adapter của mình - đúng
    thứ story 1.7 sẽ làm bằng override - rồi dựng engine với cờ bật. Không sửa
    `vendor/`, chỉ đổi tên mà module đó tra lúc chạy.
    """
    monkeypatch.setattr(
        "hypergraphrag.hypergraphrag.JsonKVStorage", JsonACLKVStorage, raising=True
    )
    with pytest.raises(LLMCacheDisabled):
        dung_engine(workspace_dir, [], enable_llm_cache=True)


def test_engine_tat_cache_voi_adapter_cua_minh_thi_dung_duoc(workspace_dir, monkeypatch):
    """Cùng phép thay lớp đó, cờ tắt: engine dựng xong, không kho cache nào.

    Cặp với test trên để chứng minh lỗi kia đến từ namespace cache chứ không
    phải từ việc adapter không dựng được nói chung.
    """
    monkeypatch.setattr(
        "hypergraphrag.hypergraphrag.JsonKVStorage", JsonACLKVStorage, raising=True
    )
    rag = dung_engine(workspace_dir, [], enable_llm_cache=False)
    assert rag.llm_response_cache is None
    assert isinstance(rag.text_chunks, JsonACLKVStorage)
    assert isinstance(rag.full_docs, JsonACLKVStorage)
