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
    MA_DANG_THU_LAI,
    NGAN_SACH_NAP,
    NGAN_SACH_TRUY_HOI,
    SO_LAN_THU,
    ChanNhipQuaLau,
    NganSachThuLai,
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
        # Hai mã 4xx của story 3.3: 408 là provider tự nói "gửi lại đi", 425 là
        # một dạng chặn nhịp khác. Trước đó cả hai rơi vào nhánh "4xx khác thì
        # không" cùng chỗ với 400 và 401 (khoản ledger 2.13).
        (_LoiHttp(408), True),
        (_LoiHttp(425), True),
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


def test_ma_dang_thu_lai_la_danh_muc_dong_ba_ma():
    """Ba mã 4xx đáng thử lại, khai một chỗ; 4xx còn lại thì không."""
    assert MA_DANG_THU_LAI == {408, 425, 429}
    for ma in (400, 401, 403, 404, 422):
        assert nen_thu_lai(_LoiHttp(ma)) is False


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
        asyncio.run(goi_co_thu_lai(ham, "p", _sleep=_ngu))
    assert loi.value.code == "CHAN_NHIP_QUA_LAU"
    assert lan["n"] == 1, "không thử lại lần nào sau khi bỏ cuộc"


def test_thu_lai_dung_so_lan_roi_nem_nguyen_loi_cuoi():
    lan = {"n": 0}

    async def ham(_):
        lan["n"] += 1
        raise _LoiHttp(429)

    with pytest.raises(_LoiHttp):
        asyncio.run(goi_co_thu_lai(ham, "p", _sleep=_ngu))
    assert lan["n"] == SO_LAN_THU


def test_thanh_cong_o_lan_thu_hai_tra_ket_qua():
    lan = {"n": 0}

    async def ham(prompt):
        lan["n"] += 1
        if lan["n"] == 1:
            raise _LoiHttp(503)
        return f"ok:{prompt}"

    assert asyncio.run(goi_co_thu_lai(ham, "p", _sleep=_ngu)) == "ok:p"
    assert lan["n"] == 2


def test_4xx_khac_khong_thu_lai():
    lan = {"n": 0}

    async def ham(_):
        lan["n"] += 1
        raise _LoiHttp(400)

    with pytest.raises(_LoiHttp):
        asyncio.run(goi_co_thu_lai(ham, "p", _sleep=_ngu))
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


# ---------------------------------------------------------------------------
# Không có lớp thử lại thứ hai ở dưới (vòng review 05/09)
# ---------------------------------------------------------------------------


def test_sdk_openai_khong_tu_thu_lai():
    """SDK provider phải dựng với `max_retries=0`.

    Mặc định của `openai` là 2, tức nó tự thử lại 429/5xx **bên trong** một lời
    gọi. Cộng lớp của `adapters/thu_lai.py` thì một lời gọi thành 4 x 3 = 12
    request, và tệ hơn: `Retry-After` cùng trần `TRAN_CHO_GIAY` bị SDK đi vòng,
    nên `ChanNhipQuaLau` không nổ đúng lúc nó phải nổ - đúng thứ docstring của
    wrapper viết ra để chặn.
    """
    from adapters.llm_wrapper import SDK_KHONG_TU_THU_LAI, OpenAITuongThich

    assert SDK_KHONG_TU_THU_LAI == 0
    ncc = OpenAITuongThich(ten="deepseek", api_key="x", base_url="https://vi-du")
    assert ncc._client.max_retries == SDK_KHONG_TU_THU_LAI


def test_lui_luy_thua_co_jitter():
    """Không có jitter thì các chunk song song tự tái tạo đúng burst vừa bị chặn.

    `_trich_mot_chunk` chạy dưới một `TaskGroup`, nên khi provider chặn nhịp thì
    mọi chunk đang bay cùng ăn 429 trong cùng một khoảnh khắc, cùng tính ra cùng
    một thời gian chờ, rồi cùng gọi lại đúng lúc.
    """
    from adapters import thu_lai

    class _TrangThai:
        attempt_number = 2
        idle_for = 0.0
        outcome = None

    cho = {thu_lai.cho_bao_lau(_TrangThai()) for _ in range(40)}
    assert len(cho) > 1, "hai lần lùi lũy thừa liên tiếp không được bằng nhau"
    # Trần **không cộng** biên độ jitter: jitter nằm trong ngân sách (story 3.3).
    assert max(cho) <= thu_lai.TRAN_CHO_GIAY


def test_retry_after_khong_bi_jitter_lam_lech():
    """Jitter chỉ áp cho nhánh hệ **tự đoán**, không cho `Retry-After` provider nói."""
    from adapters import thu_lai

    class _KetQua:
        @staticmethod
        def exception():
            return _LoiHttp(429, retry_after=7)

    class _TrangThai:
        attempt_number = 2
        idle_for = 0.0
        outcome = _KetQua()

    assert {thu_lai.cho_bao_lau(_TrangThai()) for _ in range(20)} == {7.0}


def test_keyword_dieu_khien_da_bo_bi_tu_choi_chu_khong_nuot():
    """Một tên điều khiển bị xóa phải **từ chối**, không rơi xuống provider.

    Đây là ca mà chính lần đổi chữ ký của story 3.3 mở ra: `_so_lan_thu` biến
    mất, nên một nơi gọi cũ truyền nó bị `**tham_so` nuốt rồi đẩy thẳng xuống
    API của provider - đúng cái mà quy ước tiền tố gạch dưới sinh ra để chặn.
    """
    from adapters.thu_lai import TEN_DA_BO

    async def ham(**kw):
        return "ok"

    for ten in TEN_DA_BO:
        with pytest.raises(TypeError) as loi:
            asyncio.run(goi_co_thu_lai(ham, **{ten: 1}))
        assert ten in str(loi.value) and "_ngan_sach" in str(loi.value)


def test_eval_tu_choi_so_lan_thu_tran_cua_rieng_no():
    """Lớp mỏng của `eval/` bỏ một tên **trần**, và nó có bảng từ chối riêng.

    Phân biệt có nội dung: ở tầng `adapters/`, `so_lan_thu` trần chưa bao giờ là
    tham số điều khiển và phải đi thẳng xuống provider (ca ngay dưới chứng minh);
    ở `goi_llm_co_thu_lai` thì nó vừa là một tham số điều khiển bị bỏ.
    """
    from eval.do_trich_xuat import TEN_DA_BO_DO, goi_llm_co_thu_lai

    async def llm(prompt, **kw):
        return "ok"

    assert set(TEN_DA_BO_DO) == {"so_lan_thu"}
    with pytest.raises(TypeError) as loi:
        asyncio.run(goi_llm_co_thu_lai(llm, "p", so_lan_thu=2))
    assert "ngan_sach" in str(loi.value)


def test_tran_mot_loi_goi_cung_mang_tien_to_gach_duoi():
    """`goi_mot_lan_co_tran` nằm trên đúng đường chuyển tiếp mà quy ước bảo vệ.

    Hai tham số điều khiển của nó phải nằm trong không gian tên mà không API
    provider nào dùng, y hệt bốn tham số của `goi_co_thu_lai`; và trần phải là
    **keyword-only**, vì một tham số vị trí thứ hai là một tham số vị trí của
    provider bị ăn mất.
    """
    import inspect

    from adapters.thu_lai import goi_mot_lan_co_tran

    tham_so = inspect.signature(goi_mot_lan_co_tran).parameters
    assert tham_so["_tran_giay"].kind is inspect.Parameter.KEYWORD_ONLY
    nhan: dict = {}

    async def ham(*a, **kw):
        nhan["a"], nhan["kw"] = a, dict(kw)
        return "ok"

    kq = asyncio.run(
        goi_mot_lan_co_tran(ham, "vi_tri", tran_giay=9, timeout=5, _tran_giay=5.0)
    )
    assert kq == "ok"
    # `tran_giay` trần đi **thẳng xuống provider**, không bị wrapper nuốt.
    assert nhan == {"a": ("vi_tri",), "kw": {"tran_giay": 9, "timeout": 5}}


def test_tham_so_dieu_khien_khong_nuot_kwarg_cua_provider():
    """`ten`, `sleep`, `in_ra`, `so_lan_thu` **không** được là tên tham số của wrapper.

    Mọi keyword khác đi thẳng xuống provider. Nếu bốn tham số điều khiển mang
    tên trần thì một provider có tham số trùng tên bị wrapper nuốt lặng lẽ, và
    lời gọi đi với cấu hình khác cấu hình người viết ghi ra - không lỗi, không
    dấu hiệu nào.
    """
    nhan: dict = {}

    async def ham(**kw):
        nhan.update(kw)
        return "ok"

    kq = asyncio.run(
        goi_co_thu_lai(ham, ten="tên của provider", sleep=5, in_ra="x", so_lan_thu=99)
    )
    assert kq == "ok"
    assert nhan == {"ten": "tên của provider", "sleep": 5, "in_ra": "x", "so_lan_thu": 99}


# ---------------------------------------------------------------------------
# Ngân sách và trần cho một lời gọi (story 3.3)
# ---------------------------------------------------------------------------


def test_hai_ngan_sach_co_ten_va_khac_nhau_ba_so():
    """Một con số chung cho hai đường là sai theo cả hai chiều.

    Đợt nạp Qwen cục bộ sinh 5,7 token mỗi giây nên một lời gọi *hợp lệ* dài
    tới vài phút; đường truy hồi thì có người ngồi chờ. Ca này ghim cả hai bộ số
    bằng giá trị, vì chúng là ngân sách độ trễ mà chương 4 sẽ phát biểu.

    Hai số đầu của đường nạp **không đổi**: sáu đợt nạp đã trả tiền chạy dưới
    chúng.
    """
    assert (NGAN_SACH_NAP.so_lan_thu, NGAN_SACH_NAP.tran_cho_giay) == (4, 60.0)
    assert NGAN_SACH_NAP.tran_moi_loi_goi_giay == 600.0
    # Đường nạp **không** đặt trần ở `bo_llm`: nó đã có một trần ở lớp thử lại
    # của `_trich_mot_chunk`, và hai lớp timeout lồng nhau là hai chỗ để đọc sai
    # nguyên nhân một lần cắt.
    assert NGAN_SACH_NAP.tran_llm_giay is None
    assert (NGAN_SACH_TRUY_HOI.so_lan_thu, NGAN_SACH_TRUY_HOI.tran_cho_giay) == (2, 2.0)
    assert NGAN_SACH_TRUY_HOI.tran_moi_loi_goi_giay == 20.0
    assert NGAN_SACH_TRUY_HOI.tran_llm_giay == 60.0


def test_moi_lan_cho_deu_nam_trong_tran_cua_ngan_sach():
    """Trần chờ là một **trần**, kể cả phần jitter.

    Bản đầu của story 3.3 cộng jitter *bên ngoài* ngân sách:
    `wait_exponential(max=2) + wait_random(0, 3)` ngủ tới 5 giây trong khi
    `cho_bao_lau` của cùng module dội `ChanNhipQuaLau` khi provider **xin** 3
    giây vì "quá trần 2 giây". Một module vừa từ chối chờ 3 giây vừa tự ngủ 5
    giây thì trần nó khai không phải trần nó giữ - và dấu hiệu là chính bộ test
    phải nới thành `<= tran + BIEN_DO_JITTER_GIAY` mới qua.

    Ca này chấm cả hai ngân sách trên nhiều lần thử: jitter vẫn còn (hai lần
    chờ liên tiếp không bằng nhau - xem ca dưới), nhưng nó nằm **trong** trần.
    """
    from adapters import thu_lai

    class _TrangThai:
        idle_for = 0.0
        outcome = None

    for ns in (NGAN_SACH_NAP, NGAN_SACH_TRUY_HOI):
        bo = thu_lai._lui_luy_thua(ns.tran_cho_giay)
        for lan in range(1, 10):
            _TrangThai.attempt_number = lan
            cho = [bo(_TrangThai()) for _ in range(50)]
            assert max(cho) <= ns.tran_cho_giay, (ns.ten, lan, max(cho))
            assert min(cho) >= 0


def test_ngan_sach_tu_choi_so_vo_ly():
    """Ngân sách sai là lỗi lúc dựng, không phải một hành vi lạ lúc chạy."""
    for kw in (
        {"so_lan_thu": 0},
        {"so_lan_thu": 1.5},
        {"tran_cho_giay": 0},
        {"tran_cho_giay": -1},
        {"tran_moi_loi_goi_giay": 0},
        {"ten": "  "},
    ):
        with pytest.raises((ValueError, TypeError)):
            NganSachThuLai(
                **{
                    "ten": "thu",
                    "so_lan_thu": 2,
                    "tran_cho_giay": 1.0,
                    "tran_moi_loi_goi_giay": 5.0,
                    **kw,
                }
            )


def test_tran_mot_loi_goi_cat_mot_lan_goi_treo():
    """Một socket treo (không đứt, chỉ không trả byte nào) phải bị cắt.

    `SO_LAN_THU` và `TRAN_CHO_GIAY` **không** che ca này: chúng đo thời gian
    *giữa* hai lần thử, không đo một lần thử. Không có trần thì cả đợt đứng vô
    hạn mà không in dòng nào - triệu chứng khó đọc nhất, vì nó nhìn giống một
    đợt đang chạy (khoản ledger 2.13).

    Trần đặt rất nhỏ để ca chạy trong mili giây; thứ đang chấm là *có cắt hay
    không*, không phải giá trị của trần.
    """
    lan = {"n": 0}

    async def treo():
        lan["n"] += 1
        await asyncio.sleep(30)

    ns = NganSachThuLai(
        ten="thu", so_lan_thu=2, tran_cho_giay=1.0, tran_moi_loi_goi_giay=0.01
    )
    with pytest.raises(TimeoutError):
        asyncio.run(goi_co_thu_lai(treo, _ngan_sach=ns, _sleep=_ngu))
    # Quá hạn **là** một lỗi đáng thử lại: một lời gọi treo là ứng viên tốt nhất
    # cho một lần thử lại, và `TimeoutError` đã nằm trong `LOI_MANG_TAM_THOI`.
    assert lan["n"] == 2


def test_khong_tran_thi_khong_cat():
    """`tran_moi_loi_goi_giay=None` là không cắt: trần là một quyết định, không mặc định."""
    ns = NganSachThuLai(ten="thu", so_lan_thu=1, tran_cho_giay=1.0)

    async def cham():
        await asyncio.sleep(0.02)
        return "ok"

    assert asyncio.run(goi_co_thu_lai(cham, _ngan_sach=ns, _sleep=_ngu)) == "ok"


def test_ngan_sach_truy_hoi_thu_it_lan_hon_va_cho_ngan_hon():
    """Đường truy hồi hỏng **trong** trần đã phát biểu, không sau ba phút.

    Bốn lần thử với trần chờ 60 giây - đúng cho một đợt nạp - là một request
    treo tới ba phút trước khi trả lỗi, trong khi người dùng đã bỏ đi từ giây
    thứ mười (khoản ledger 2.13). Đếm số lần thử thật và tổng thời gian *chờ*
    mà lớp thử lại yêu cầu, không ngủ thật.
    """
    cho = []

    async def _ghi_cho(giay):
        cho.append(giay)

    lan = {"n": 0}

    async def ham():
        lan["n"] += 1
        raise _LoiHttp(429)

    with pytest.raises(_LoiHttp):
        asyncio.run(goi_co_thu_lai(ham, _ngan_sach=NGAN_SACH_TRUY_HOI, _sleep=_ghi_cho))
    assert lan["n"] == NGAN_SACH_TRUY_HOI.so_lan_thu == 2
    # **Không nới** bằng `+ BIEN_DO_JITTER_GIAY`: jitter nằm trong ngân sách,
    # nên trần đã khai là trần thật.
    assert cho and max(cho) <= NGAN_SACH_TRUY_HOI.tran_cho_giay


def test_retry_after_qua_tran_cua_ngan_sach_truy_hoi_bo_cuoc_som():
    """Trần chờ đi theo ngân sách, không theo một hằng chung của module.

    `Retry-After: 30` là chấp nhận được với đợt nạp (trần 60) và quá lâu với một
    câu hỏi (trần 2). Cùng một lỗi, hai kết cục, và đó chính là điều "hai ngân
    sách" nghĩa là.
    """
    from adapters import thu_lai

    class _KetQua:
        @staticmethod
        def exception():
            return _LoiHttp(429, retry_after=30)

    class _TrangThai:
        attempt_number = 2
        idle_for = 0.0
        outcome = _KetQua()

    assert thu_lai.cho_bao_lau(_TrangThai(), NGAN_SACH_NAP) == 30.0
    with pytest.raises(ChanNhipQuaLau) as loi:
        thu_lai.cho_bao_lau(_TrangThai(), NGAN_SACH_TRUY_HOI)
    assert loi.value.code == "CHAN_NHIP_QUA_LAU"


def test_tham_so_ngan_sach_van_mang_tien_to_gach_duoi():
    """`ngan_sach` trần là một tham số của provider bị wrapper nuốt lặng lẽ.

    Cùng luật với bốn tham số điều khiển cũ: mọi keyword khác đi thẳng xuống
    `ham`, nên tên điều khiển phải nằm trong không gian tên mà không API provider
    nào dùng.
    """
    nhan: dict = {}

    async def ham(**kw):
        nhan.update(kw)
        return "ok"

    assert asyncio.run(goi_co_thu_lai(ham, ngan_sach="cua provider")) == "ok"
    assert nhan == {"ngan_sach": "cua provider"}
