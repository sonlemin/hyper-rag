"""Thử lại khi provider chặn nhịp, ở tầng `adapters/` (story 2.13).

Khuôn 429/5xx/lỗi mạng đã có test từ story 2.8, nhưng chúng chấm nó **qua**
`eval/do_trich_xuat.py` (`tests/test_cham_trich_xuat.py`) và vì vậy chỉ chấm
đường *đo*. Story 2.13 hạ khuôn xuống `adapters/thu_lai.py` để đường *nạp* dùng
lại, và ba thứ mới cần được khóa ở đây:

- một bản dùng chung: hai đường gọi cùng một hàm, không hai bản trôi khỏi nhau;
- **đúng một lớp trên mỗi đường gọi**: `_trich_mot_chunk` có, `bo_embedding` có,
  `bo_llm` **không** - bọc `bo_llm` cho 4x4 = 16 lần thử và kéo dài chính cửa sổ
  chặn nhịp mà retry sinh ra để đi qua;
- đơn vị thử lại bằng đơn vị lời gọi: một 429 trên chunk thứ 12 thử lại chunk
  thứ 12, không thử lại cả tài liệu (trả tiền lại cho mọi chunk đã xong).

Không test nào ngủ thật (`sleep=` là điểm tiêm) và không test nào gọi provider.
"""

import asyncio

import pytest

from adapters.thu_lai import (
    SO_LAN_THU,
    ChanNhipQuaLau,
    giay_cho_lai,
    goi_co_thu_lai,
    ma_http_cua,
    nen_thu_lai,
)


class _PhanHoi:
    def __init__(self, headers=None):
        self.headers = headers or {}


class _LoiHttp(Exception):
    """Ngoại lệ hình dạng SDK: `status_code` cộng `response.headers`."""

    def __init__(self, ma: int, retry_after=None):
        super().__init__(f"http {ma}")
        self.status_code = ma
        self.response = _PhanHoi({"retry-after": str(retry_after)} if retry_after else {})


async def _ngu(_giay):
    """Thay `asyncio.sleep`: không ngủ thật, để test chạy trong mili giây."""
    return None


# ---------------------------------------------------------------------------
# Một bản dùng chung
# ---------------------------------------------------------------------------


def test_eval_dung_lai_dung_khuon_cua_adapters_khong_giu_ban_thu_hai():
    """`eval/do_trich_xuat.py` re-export, không định nghĩa lại.

    Hai bản của cùng một luật thử lại sẽ trôi khỏi nhau, và khi đó đường đo và
    đường nạp thử lại khác nhau trên cùng một mã 429 mà không ai thấy.
    """
    import adapters.thu_lai as goc
    import eval.do_trich_xuat as harness

    for ten in ("nen_thu_lai", "giay_cho_lai", "ma_http_cua", "la_loi_mang_tam_thoi"):
        assert getattr(harness, ten) is getattr(goc, ten), ten
    assert harness.ChanNhipQuaLau is goc.ChanNhipQuaLau
    assert harness.SO_LAN_THU == goc.SO_LAN_THU


def test_core_khong_thay_tenacity():
    """`adapters/thu_lai.py` nằm ở `adapters/` chứ không `core/`: nó dùng tenacity."""
    from pathlib import Path

    goc = Path(__file__).resolve().parent.parent
    assert not list((goc / "core").rglob("thu_lai.py"))


# ---------------------------------------------------------------------------
# Luật thử lại (giữ nguyên hành vi của story 2.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "loi, mong_doi",
    [
        (_LoiHttp(429), True),
        (_LoiHttp(500), True),
        (_LoiHttp(503), True),
        (_LoiHttp(400), False),
        (_LoiHttp(401), False),
        (_LoiHttp(404), False),
        (ConnectionResetError("reset"), True),
        (TimeoutError("timeout"), True),
        (ValueError("prompt sai"), False),
    ],
)
def test_nen_thu_lai(loi, mong_doi):
    assert nen_thu_lai(loi) is mong_doi


def test_ma_http_doc_duoc_ca_ba_ten_truong():
    class _Ma:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    assert ma_http_cua(_Ma(status_code=429)) == 429
    assert ma_http_cua(_Ma(status=503)) == 503
    assert ma_http_cua(_Ma(code="429")) == 429
    assert ma_http_cua(_Ma(code="timeout")) is None


def test_giay_cho_lai_doc_retry_after():
    assert giay_cho_lai(_LoiHttp(429, retry_after=7)) == 7.0
    assert giay_cho_lai(_LoiHttp(429)) is None


def test_retry_after_qua_tran_la_bo_cuoc_khong_kep_xuong_tran():
    """Kẹp `Retry-After` xuống trần rồi thử lại sớm là tệ hơn cả không thử lại.

    Bốn lần thử đốt hết trong ba phút vào một endpoint còn đang chặn, nên đợt
    vừa hỏng vừa làm cửa sổ chặn dài thêm.
    """
    lan = {"n": 0}

    async def ham(_):
        lan["n"] += 1
        raise _LoiHttp(429, retry_after=3600)

    with pytest.raises(ChanNhipQuaLau) as loi:
        asyncio.run(goi_co_thu_lai(ham, "p", sleep=_ngu))
    assert loi.value.code == "CHAN_NHIP_QUA_LAU"
    assert lan["n"] == 1, "không thử lại lần nào sau khi bỏ cuộc"


def test_thu_lai_dung_so_lan_roi_nem_nguyen_loi_cuoi():
    lan = {"n": 0}

    async def ham(_):
        lan["n"] += 1
        raise _LoiHttp(429)

    with pytest.raises(_LoiHttp):
        asyncio.run(goi_co_thu_lai(ham, "p", sleep=_ngu))
    assert lan["n"] == SO_LAN_THU


def test_thanh_cong_o_lan_thu_hai_tra_ket_qua():
    lan = {"n": 0}

    async def ham(prompt):
        lan["n"] += 1
        if lan["n"] == 1:
            raise _LoiHttp(503)
        return f"ok:{prompt}"

    assert asyncio.run(goi_co_thu_lai(ham, "p", sleep=_ngu)) == "ok:p"
    assert lan["n"] == 2


def test_4xx_khac_khong_thu_lai():
    lan = {"n": 0}

    async def ham(_):
        lan["n"] += 1
        raise _LoiHttp(400)

    with pytest.raises(_LoiHttp):
        asyncio.run(goi_co_thu_lai(ham, "p", sleep=_ngu))
    assert lan["n"] == 1


# ---------------------------------------------------------------------------
# Đúng một lớp trên mỗi đường gọi
# ---------------------------------------------------------------------------


def test_trich_mot_chunk_thu_lai_va_don_vi_thu_lai_la_mot_loi_goi():
    """Một 429 trên một chunk thử lại **chunk đó**, không cả tài liệu.

    Thử lại cả tài liệu là trả tiền lại cho mọi chunk đã xong, nên đơn vị thử
    lại phải bằng đơn vị lời gọi.
    """
    from adapters.trich_xuat import _trich_mot_chunk

    lan = {"n": 0}

    async def llm(prompt, **kw):
        lan["n"] += 1
        if lan["n"] < 3:
            raise _LoiHttp(429)
        return '{"facts": []}'

    khoa, kq = asyncio.run(
        _trich_mot_chunk(llm, "chunk-12", {"content": "một câu"})
    )
    assert khoa == "chunk-12"
    assert lan["n"] == 3, "thử lại đúng lời gọi của chunk đó"
    assert kq.facts == ()


def test_bo_llm_khong_bo_them_mot_lop_thu_lai(policy, khong_gian):
    """**Cái bẫy của story này.** `bo_llm` không được bọc.

    Đường nạp đi qua `bo_llm` rồi `_trich_mot_chunk`; đường đo đi qua `bo_llm`
    rồi `goi_llm_co_thu_lai`. Một lớp nữa ở `bo_llm` nhân số lần thử của **cả
    hai** đường lên 4x4 = 16, và một cửa sổ chặn nhịp kéo dài thêm chứ không
    ngắn đi.
    """
    from adapters.llm_wrapper import bo_llm
    from core.permission import use_context

    from tests.gia_lap_llm import SoAuditBoNho
    from tests.ngu_canh import vai

    class _Ncc:
        ten = "deepseek"
        cuc_bo = False

        def __init__(self):
            self.lan = 0

        async def hoan_thanh(self, model, messages, **kw):
            self.lan += 1
            raise _LoiHttp(429)

    ncc = _Ncc()
    llm = bo_llm(nha_cung_cap=ncc, model="deepseek-v4-flash", audit=SoAuditBoNho())
    with use_context(vai(policy, "devops", khong_gian)):
        with pytest.raises(_LoiHttp):
            asyncio.run(llm("p"))
    assert ncc.lan == 1, "bo_llm gọi provider đúng một lần, không tự thử lại"


def test_bo_embedding_thu_lai_dung_mot_lop(policy, khong_gian):
    """Embedding là phần **đông** lời gọi của một đợt nạp (159/209 ở `khao_sat`).

    Nó không đi qua lớp thử lại nào khác, nên lớp của nó nằm ở `bo_embedding`.
    """
    from adapters.llm_wrapper import KetQuaEmbedding, bo_embedding
    from core.permission import use_context

    from tests.gia_lap_llm import SoAuditBoNho
    from tests.ngu_canh import vai

    class _Ncc:
        ten = "openai"
        cuc_bo = False

        def __init__(self):
            self.lan = 0

        async def nhung(self, model, van_ban):
            self.lan += 1
            if self.lan < 3:
                raise _LoiHttp(429)
            return KetQuaEmbedding(
                vector=[[0.0] * 1536 for _ in van_ban], token_vao=3
            )

    ncc = _Ncc()
    ham = bo_embedding(
        nha_cung_cap=ncc, model="text-embedding-3-small", audit=SoAuditBoNho()
    )
    with use_context(vai(policy, "devops", khong_gian)):
        v = asyncio.run(ham.func(["a", "b"]))
    assert ncc.lan == 3
    assert v.shape == (2, 1536)
