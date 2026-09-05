"""Wrapper LLM/embedding: token thật, chi phí, kiểm space, audit (story 2.2).

Đặc tả viết trước cơ chế (FR-27), theo từng hàng I/O Matrix của spec. Không
mạng, không key: provider là bản giả trả token cố định, audit là sổ bộ nhớ.
Hai ca cuối chạy qua engine thật (`aquery` của upstream) để chứng minh dấu
wrapper sống qua lớp bọc của upstream và cổng M1 đi qua wrapper thật.
"""

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from functools import partial

import numpy as np
import pytest
from hypergraphrag.utils import EmbeddingFunc, limit_async_func_call

from adapters.engine import EngineACL, LLMNotWrapped
from adapters.llm_wrapper import (
    BIEN_EMBEDDING_MODEL,
    EmbeddingShapeMismatch,
    HamModel,
    KetQuaEmbedding,
    ProviderUsageMissing,
    BIEN_LLM_MODEL,
    BIEN_OLLAMA_HOST,
    CT_CHI_PHI_USD,
    CT_DANH_MUC_VERSION,
    CT_MODEL,
    CT_NHA_CUNG_CAP,
    CT_TOKEN_RA,
    CT_TOKEN_VAO,
    LLMStreamNotSupported,
    ModelProviderMismatch,
    OllamaCucBo,
    OpenAITuongThich,
    ProviderConfigMissing,
    ProviderKwargUnknown,
    ProviderNotAllowedForSpace,
    bo_embedding,
    bo_llm,
    cau_hinh_model_tu_moi_truong,
    ham_tu_moi_truong,
    la_wrapper,
    nha_cung_cap_tu_moi_truong,
)
from adapters.model_catalog import ModelUnknown, danh_muc_mac_dinh
from core.audit import EVENT_EMBEDDING_COST, EVENT_LLM_COST, TIER_OBSERVATION
from core.ids import SPACE_REAL, SPACE_THAT_KHU, la_space_real, validate_space
from core.permission import PermissionContextMissing, use_context
from tests.gia_lap_llm import (
    MODEL_EMBEDDING_CUC_BO_GIA,
    MODEL_EMBEDDING_GIA,
    MODEL_LLM_CUC_BO_GIA,
    MODEL_LLM_GIA,
    NCC_CUC_BO_GIA,
    EmbeddingGia,
    LLMGia,
    NhaCungCapGia,
    SoAuditBoNho,
    danh_muc_gia,
)
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.gia_lap_qdrant import QdrantGhiLai, embedding_gia
from tests.ho_tro_m1 import cong_m1, dung_engine, hoi
from tests.ngu_canh import ngu_canh_ingest, vai

pytestmark = pytest.mark.usefixtures("ma_hoa_offline")


def _llm(so_audit, ncc=None, model=MODEL_LLM_GIA):
    ncc = NhaCungCapGia() if ncc is None else ncc
    return ncc, bo_llm(nha_cung_cap=ncc, model=model, audit=so_audit, danh_muc=danh_muc_gia())


def _emb(so_audit, ncc=None, model=MODEL_EMBEDDING_GIA):
    ncc = EmbeddingGia() if ncc is None else ncc
    return ncc, bo_embedding(nha_cung_cap=ncc, model=model, audit=so_audit, danh_muc=danh_muc_gia())


# --- Space `real` là luật của core/ -------------------------------------------


@pytest.mark.parametrize(
    "space, ky_vong",
    [
        (SPACE_REAL, True),
        ("test_3fa9c1d2_real", True),
        ("synth", False),
        ("test_3fa9c1d2_synth", False),
        ("realtime", False),
        ("real_synth", False),
        ("TEST_REAL", True),
        ("x_Real", True),
        ("REAL", True),
    ],
)
def test_la_space_real_theo_doan_cuoi_ten(space, ky_vong):
    assert la_space_real(space) is ky_vong


def test_la_space_real_van_kiem_hinh_dang_space():
    with pytest.raises(ValueError):
        la_space_real("real space")


# --- Tên space `that_khu` (story 2.13) ----------------------------------------


def test_space_that_khu_khong_khop_luat_real_va_van_hop_le():
    """`that_khu` chạy provider API ngoài **có chủ đích**, nên tên nó phải lọt rào.

    Story 2.13 nạp cùng 50 tài liệu đã khử của space `real` bằng DeepSeek. Bản
    **đã khử** được phép ra API ngoài (NFR-05 cho hai đường ngang nhau, khử
    trước hoặc chạy cục bộ); ràng buộc "chỉ provider cục bộ" của AD-12 gắn với
    space `real` chứ không với bộ dữ liệu. Nên tên space mới:

    - phải hợp lệ theo `validate_space` (chữ đầu, rồi chữ/số/gạch dưới - **không**
      gạch ngang, nên `that-khu` không dùng được);
    - **không** được khớp `la_space_real`, nếu không `_kiem_space` của wrapper
      dội `ProviderNotAllowedForSpace` trước byte đầu tiên và cả đợt không chạy;
    - phải đọc ra khác `real` bằng mắt, để không ai nhầm hai space với nhau.
    """
    assert SPACE_THAT_KHU == "that_khu"
    assert validate_space(SPACE_THAT_KHU) == SPACE_THAT_KHU
    assert la_space_real(SPACE_THAT_KHU) is False
    assert SPACE_THAT_KHU != SPACE_REAL


def test_rao_fail_closed_van_nguyen_cho_space_khac_ket_thuc_bang_real():
    """Nới cho `that_khu` không được nới cho một tên kết thúc `_real`.

    Phía an toàn là phía dương: một tên kết thúc `_real` mà không định là real
    thì chỉ mất quyền gọi API ngoài, còn chiều ngược lại là gửi dữ liệu thật ra
    ngoài.
    """
    assert la_space_real("that_khu_real") is True
    assert la_space_real("khu_real") is True
    assert la_space_real("that_khu") is False


# --- I/O Matrix: LLM và embedding trên synth ----------------------------------


def test_llm_tren_synth_tra_noi_dung_va_dung_mot_su_kien_llm_cost(khong_gian, policy):
    so = SoAuditBoNho()
    ncc, llm = _llm(so)
    ngu_canh = vai(policy, "devops", khong_gian)

    async def chay():
        with use_context(ngu_canh):
            return await llm("hỏi gì đó", hashing_kv=None, keyword_extraction=True)

    noi_dung = asyncio.run(chay())
    assert noi_dung == ncc.llm.phan_hoi
    su_kien = so.cac_su_kien()
    assert len(su_kien) == 1
    sk = su_kien[0]
    assert sk.event == EVENT_LLM_COST and sk.tier == TIER_OBSERVATION
    assert sk.space == khong_gian
    assert sk.act == ngu_canh.real_account and sk.role == "devops"
    assert sk.policy_version == policy.policy_version
    assert sk.hyperedge_ids == ()
    ct = sk.chi_tiet
    assert ct[CT_MODEL] == MODEL_LLM_GIA
    assert ct[CT_NHA_CUNG_CAP] == ncc.ten
    assert ct[CT_TOKEN_VAO] == 12 and ct[CT_TOKEN_RA] == 34
    assert ct[CT_CHI_PHI_USD] == pytest.approx((12 * 1.0 + 34 * 2.0) / 1e6)
    assert ct[CT_DANH_MUC_VERSION] == danh_muc_gia().version
    # Hai kwargs của upstream bị nuốt, không tới provider.
    _, _, kwargs = ncc.loi_goi[0]
    assert "hashing_kv" not in kwargs and "keyword_extraction" not in kwargs


def test_llm_dung_messages_dung_hinh_dang_upstream(khong_gian, policy):
    """system_prompt -> role system; history đứng giữa; prompt là message cuối."""
    so = SoAuditBoNho()
    ncc, llm = _llm(so)
    lich_su = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            await llm("câu hỏi", system_prompt="hệ thống", history_messages=lich_su, temperature=0)

    asyncio.run(chay())
    model, messages, kwargs = ncc.loi_goi[0]
    assert model == MODEL_LLM_GIA
    assert messages == [
        {"role": "system", "content": "hệ thống"},
        *lich_su,
        {"role": "user", "content": "câu hỏi"},
    ]
    assert kwargs == {"temperature": 0}
    assert ncc.llm.prompts == ["câu hỏi"]
    assert ncc.llm.prompts_sinh_cau_tra_loi == ["câu hỏi"]


def test_embedding_tra_ndarray_va_mot_su_kien_embedding_cost(khong_gian, policy):
    so = SoAuditBoNho()
    ncc, emb = _emb(so, EmbeddingGia(token_vao=20))
    assert isinstance(emb, EmbeddingFunc)
    assert emb.embedding_dim == 8

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            return await emb(["một", "hai", "ba"])

    vec = asyncio.run(chay())
    assert isinstance(vec, np.ndarray) and vec.shape == (3, 8)
    su_kien = so.cac_su_kien()
    assert len(su_kien) == 1 and su_kien[0].event == EVENT_EMBEDDING_COST
    ct = su_kien[0].chi_tiet
    assert ct[CT_TOKEN_VAO] == 20 and ct[CT_TOKEN_RA] == 0
    assert ct[CT_CHI_PHI_USD] == pytest.approx(20 * 0.5 / 1e6)
    assert ct[CT_MODEL] == MODEL_EMBEDDING_GIA


# --- I/O Matrix: space real ----------------------------------------------------


def _space_real(session_prefix) -> str:
    return f"{session_prefix}_real"


def test_space_real_provider_api_ngoai_khong_duoc_goi(session_prefix, policy):
    so = SoAuditBoNho()
    ncc, llm = _llm(so)
    ncc_e, emb = _emb(so)
    ngu_canh = vai(policy, "devops", _space_real(session_prefix))

    async def chay():
        with use_context(ngu_canh):
            with pytest.raises(ProviderNotAllowedForSpace) as loi:
                await llm("hỏi")
            with pytest.raises(ProviderNotAllowedForSpace) as loi_e:
                await emb(["x"])
        return loi.value.code, loi_e.value.code

    assert asyncio.run(chay()) == ("PROVIDER_NOT_ALLOWED_FOR_SPACE",) * 2
    assert ncc.so_lan == 0 and ncc_e.so_lan == 0, "provider bị gọi trước cửa kiểm space"
    assert so.su_kien == []


def test_space_real_provider_cuc_bo_goi_binh_thuong_chi_phi_0(session_prefix, policy):
    so = SoAuditBoNho()
    ncc, llm = _llm(so, NhaCungCapGia(ten=NCC_CUC_BO_GIA, cuc_bo=True), MODEL_LLM_CUC_BO_GIA)
    ncc_e, emb = _emb(
        so, EmbeddingGia(ten=NCC_CUC_BO_GIA, cuc_bo=True, token_vao=7), MODEL_EMBEDDING_CUC_BO_GIA
    )

    async def chay():
        with use_context(vai(policy, "devops", _space_real(session_prefix))):
            return await llm("hỏi"), await emb(["x"])

    noi_dung, vec = asyncio.run(chay())
    assert noi_dung == ncc.llm.phan_hoi and vec.shape == (1, 8)
    assert [sk.event for sk in so.su_kien] == [EVENT_LLM_COST, EVENT_EMBEDDING_COST]
    for sk in so.su_kien:
        assert sk.chi_tiet[CT_CHI_PHI_USD] == 0
        assert sk.chi_tiet[CT_NHA_CUNG_CAP] == NCC_CUC_BO_GIA
    assert so.su_kien[0].chi_tiet[CT_TOKEN_VAO] == 12
    assert so.su_kien[1].chi_tiet[CT_TOKEN_VAO] == 7


# --- I/O Matrix: fail-closed, port hỏng, provider hỏng, stream ----------------


def test_khong_ngu_canh_thi_provider_khong_duoc_goi():
    so = SoAuditBoNho()
    ncc, llm = _llm(so)
    ncc_e, emb = _emb(so)

    async def chay():
        with pytest.raises(PermissionContextMissing) as l1:
            await llm("hỏi")
        with pytest.raises(PermissionContextMissing) as l2:
            await emb(["x"])
        return l1.value.code, l2.value.code

    assert asyncio.run(chay()) == ("PERMISSION_CONTEXT_MISSING",) * 2
    assert ncc.so_lan == 0 and ncc_e.so_lan == 0
    assert so.su_kien == []


def test_port_audit_hong_thi_noi_dung_van_ve_va_co_warning(khong_gian, policy, caplog):
    so = SoAuditBoNho(loi=ConnectionError("postgres không tới được"))
    ncc, llm = _llm(so)

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            return await llm("hỏi")

    with caplog.at_level(logging.WARNING, logger="core.audit"):
        noi_dung = asyncio.run(chay())
    assert noi_dung == ncc.llm.phan_hoi
    canh_bao = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(canh_bao) == 1
    assert EVENT_LLM_COST in canh_bao[0] and "postgres không tới được" in canh_bao[0]


def test_provider_hong_thi_khong_su_kien_va_loi_doi_nguyen(khong_gian, policy):
    class LoiSDK(RuntimeError):
        pass

    so = SoAuditBoNho()
    _, llm = _llm(so, NhaCungCapGia(loi=LoiSDK("429")))
    _, emb = _emb(so, EmbeddingGia(loi=LoiSDK("500")))

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(LoiSDK):
                await llm("hỏi")
            with pytest.raises(LoiSDK):
                await emb(["x"])

    asyncio.run(chay())
    assert so.su_kien == [], "ghi chi phí cho lời gọi hỏng là làm sai mẫu số FR-30"


def test_stream_true_bi_tu_choi_truoc_khi_goi_provider(khong_gian, policy):
    so = SoAuditBoNho()
    ncc, llm = _llm(so)

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(LLMStreamNotSupported) as loi:
                await llm("hỏi", system_prompt="s", stream=True)
            # `stream=False` là đường bình thường, không phải một cờ lạ.
            await llm("hỏi", system_prompt="s", stream=False)
        return loi.value.code

    assert asyncio.run(chay()) == "LLM_STREAM_NOT_SUPPORTED"
    assert ncc.so_lan == 1
    assert "stream" not in ncc.loi_goi[0][2]


# --- Dựng wrapper: model lạ, provider lệch --------------------------------------


def test_model_la_thi_dung_wrapper_that_bai():
    so = SoAuditBoNho()
    with pytest.raises(ModelUnknown) as loi:
        bo_llm(nha_cung_cap=NhaCungCapGia(), model="khong-co", audit=so, danh_muc=danh_muc_gia())
    assert loi.value.code == "MODEL_UNKNOWN"
    # Sai loại cũng là model lạ: một model embedding không dựng được hàm LLM.
    with pytest.raises(ModelUnknown):
        bo_llm(nha_cung_cap=NhaCungCapGia(), model=MODEL_EMBEDDING_GIA, audit=so, danh_muc=danh_muc_gia())
    with pytest.raises(ModelUnknown):
        bo_embedding(nha_cung_cap=EmbeddingGia(), model=MODEL_LLM_GIA, audit=so, danh_muc=danh_muc_gia())


def test_model_thuoc_provider_khac_bi_tu_choi_luc_dung():
    """Model của `gia` tiêm provider cục bộ (hay ngược lại) là cấu hình sai, nổ sớm."""
    so = SoAuditBoNho()
    with pytest.raises(ModelProviderMismatch) as loi:
        bo_llm(
            nha_cung_cap=NhaCungCapGia(ten=NCC_CUC_BO_GIA, cuc_bo=True),
            model=MODEL_LLM_GIA,
            audit=so,
            danh_muc=danh_muc_gia(),
        )
    assert loi.value.code == "MODEL_PROVIDER_MISMATCH"
    with pytest.raises(ModelProviderMismatch):
        bo_embedding(
            nha_cung_cap=EmbeddingGia(),
            model=MODEL_EMBEDDING_CUC_BO_GIA,
            audit=so,
            danh_muc=danh_muc_gia(),
        )


# --- Dấu wrapper và cửa của engine ---------------------------------------------


def test_dau_wrapper_song_qua_limit_async_func_call_va_partial():
    so = SoAuditBoNho()
    _, llm = _llm(so)
    _, emb = _emb(so)
    assert la_wrapper(llm) and la_wrapper(emb)
    # Đúng lớp bọc mà `HyperGraphRAG.__post_init__` áp lên hai hàm.
    assert la_wrapper(limit_async_func_call(16)(partial(llm, hashing_kv=None)))
    assert la_wrapper(limit_async_func_call(16)(emb))
    # Hàm trần, bản giả trần, và một thuộc tính trùng tên đặt tay đều không qua.
    assert not la_wrapper(LLMGia())
    assert not la_wrapper(embedding_gia())
    assert not la_wrapper(None)

    async def tran(prompt, **kw):
        return ""

    tran._hyper_rag_wrapper = True
    assert not la_wrapper(tran)


@pytest.mark.parametrize("truong", ["llm_model_func", "embedding_func"])
def test_engine_tu_choi_ham_chua_boc(workspace_dir, truong):
    so = SoAuditBoNho()
    _, llm = _llm(so)
    _, emb = _emb(so)
    tham_so = {"llm_model_func": llm, "embedding_func": emb}
    tham_so[truong] = LLMGia() if truong == "llm_model_func" else embedding_gia()
    with pytest.raises(LLMNotWrapped) as loi:
        EngineACL(
            working_dir=str(workspace_dir),
            tao_qdrant_client=lambda: QdrantGhiLai(),
            tao_neo4j_driver=lambda: Neo4jGhiLai(),
            **tham_so,
        )
    assert loi.value.code == "LLM_NOT_WRAPPED"
    assert truong in str(loi.value)


def test_engine_mac_dinh_upstream_cung_bi_tu_choi(workspace_dir):
    """Quên truyền hai hàm là nổ, không phải một engine gọi API ngoài không đếm."""
    with pytest.raises(LLMNotWrapped):
        EngineACL(
            working_dir=str(workspace_dir),
            tao_qdrant_client=lambda: QdrantGhiLai(),
            tao_neo4j_driver=lambda: Neo4jGhiLai(),
        )


def test_engine_dung_xong_hai_ham_van_nhan_ra_la_wrapper(workspace_dir):
    """Sau `__post_init__` của upstream (partial + limit_async_func_call) dấu vẫn còn."""
    engine = dung_engine(workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), LLMGia())
    assert la_wrapper(engine.llm_model_func)
    assert la_wrapper(engine.embedding_func)
    assert engine.embedding_func.embedding_dim == 8


# --- E2E: cổng M1 đi qua wrapper thật -----------------------------------------


def test_aquery_only_need_context_phat_dung_mot_llm_cost(workspace_dir, khong_gian, policy):
    async def chay():
        engine, _, _, llm = await cong_m1(workspace_dir, khong_gian, policy)
        ngu_canh = vai(policy, "devops", khong_gian)
        await hoi(engine, ngu_canh)
        return engine.so_audit, llm.so_lan, ngu_canh

    so, so_lan, ngu_canh = asyncio.run(chay())
    llm_cost = so.cac_su_kien(EVENT_LLM_COST)
    assert len(llm_cost) == 1 and so_lan == 1
    assert llm_cost[0].space == khong_gian
    assert llm_cost[0].act == ngu_canh.real_account and llm_cost[0].role == "devops"
    # Hai collection vector được hỏi là hai lượt embed, mỗi lượt một sự kiện.
    emb_cost = so.cac_su_kien(EVENT_EMBEDDING_COST)
    assert len(emb_cost) >= 2
    assert all(sk.role == "devops" for sk in emb_cost)


def test_nap_kho_duoi_ngu_canh_he_thong_ghi_su_kien_khong_act(workspace_dir, khong_gian, policy):
    """Ingest: embedding chạy dưới ngữ cảnh hệ thống, sự kiện mang act/role None."""
    so = SoAuditBoNho()

    async def chay():
        from tests.nap_kho import nap_ba_kho

        engine = dung_engine(workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), LLMGia(), so_audit=so)
        await nap_ba_kho(engine, khong_gian=khong_gian, policy=policy)

    asyncio.run(chay())
    emb = so.cac_su_kien(EVENT_EMBEDDING_COST)
    assert emb, "nạp kho không embed gì"
    assert all(sk.act is None and sk.role is None and sk.space == khong_gian for sk in emb)
    assert so.cac_su_kien(EVENT_LLM_COST) == []


# --- Dựng từ môi trường ---------------------------------------------------------


def test_cau_hinh_model_tu_moi_truong_cung_luat_voi_cau_hinh_kho():
    cau_hinh = cau_hinh_model_tu_moi_truong(
        {BIEN_LLM_MODEL: " m1 ", BIEN_EMBEDDING_MODEL: "", BIEN_OLLAMA_HOST: "http://ollama:11434"}
    )
    assert cau_hinh == {BIEN_LLM_MODEL: "m1", BIEN_OLLAMA_HOST: "http://ollama:11434"}
    assert cau_hinh_model_tu_moi_truong({}) == {}


def test_nha_cung_cap_tu_moi_truong_theo_danh_muc_that():
    """Provider API cần key ở đúng biến danh mục chỉ; cục bộ chỉ cần host."""
    dm = danh_muc_mac_dinh()
    for muc in dm.models.values():
        ncc = dm.nha_cung_cap_cua(muc)
        if ncc.cuc_bo:
            p = nha_cung_cap_tu_moi_truong(muc, dm, {ncc.bien_host: "http://ollama:11434"})
            assert isinstance(p, OllamaCucBo) and p.cuc_bo is True and p.ten == ncc.ten
            # Không host thì để SDK tự chọn mặc định, không nổ.
            assert isinstance(nha_cung_cap_tu_moi_truong(muc, dm, {}), OllamaCucBo)
        else:
            with pytest.raises(ProviderConfigMissing) as loi:
                nha_cung_cap_tu_moi_truong(muc, dm, {})
            assert loi.value.code == "PROVIDER_CONFIG_MISSING"
            assert ncc.bien_api_key in str(loi.value)
            p = nha_cung_cap_tu_moi_truong(muc, dm, {ncc.bien_api_key: "sk-test"})
            assert isinstance(p, OpenAITuongThich) and p.cuc_bo is False and p.ten == ncc.ten


def test_ham_tu_moi_truong_dung_ca_hai_ham_da_boc():
    """Với danh mục thật và key giả: hai hàm dựng được, đều mang dấu wrapper, không mạng."""
    dm = danh_muc_mac_dinh()
    llm_model = next(m for m in dm.models.values() if m.loai == "llm" and not m.cuc_bo)
    emb_model = next(m for m in dm.models.values() if m.loai == "embedding" and not m.cuc_bo)
    moi_truong = {
        BIEN_LLM_MODEL: llm_model.ten,
        BIEN_EMBEDDING_MODEL: emb_model.ten,
        dm.nha_cung_cap_cua(llm_model).bien_api_key: "sk-a",
        dm.nha_cung_cap_cua(emb_model).bien_api_key: "sk-b",
    }
    ham = ham_tu_moi_truong(audit=SoAuditBoNho(), danh_muc=dm, moi_truong=moi_truong)
    assert isinstance(ham, HamModel)
    assert la_wrapper(ham.llm) and la_wrapper(ham.embedding)
    assert ham.embedding.embedding_dim == emb_model.so_chieu
    assert ham.llm_max_token == llm_model.max_token
    with pytest.raises(ProviderConfigMissing):
        ham_tu_moi_truong(audit=SoAuditBoNho(), danh_muc=dm, moi_truong={})
    with pytest.raises(ModelUnknown):
        ham_tu_moi_truong(
            audit=SoAuditBoNho(), danh_muc=dm, moi_truong={**moi_truong, BIEN_LLM_MODEL: "la"}
        )


# --- Vòng review: dịch phản hồi SDK, usage thiếu, hình dạng vector ------------

REPO_ROOT = Path(__file__).resolve().parent.parent


class _OpenAIGia:
    """Client OpenAI giả: trả đúng đối tượng được tiêm, ghi lại tham số gọi."""

    def __init__(self, chat_response=None, embedding_response=None):
        self.goi = []
        chat = self

        class _Completions:
            async def create(_, **kwargs):
                chat.goi.append(("chat", kwargs))
                return chat_response

        class _Embeddings:
            async def create(_, **kwargs):
                chat.goi.append(("embed", kwargs))
                return embedding_response

        self.chat = SimpleNamespace(completions=_Completions())
        self.embeddings = _Embeddings()


def _chat_response(noi_dung="xin chào", prompt=12, completion=34, usage=True, choices=True):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=noi_dung))] if choices else [],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion) if usage else None,
    )


def _embedding_response(vectors, prompt=20, usage=True):
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=list(v), index=i) for i, v in enumerate(vectors)],
        usage=SimpleNamespace(prompt_tokens=prompt) if usage else None,
    )


def test_openai_tuong_thich_dich_dung_usage_va_noi_dung():
    client = _OpenAIGia(chat_response=_chat_response(prompt=12, completion=34))
    ncc = OpenAITuongThich(ten="ncc", client=client)
    kq = asyncio.run(ncc.hoan_thanh("m", [{"role": "user", "content": "hỏi"}], temperature=0))
    # Đảo hai dòng prompt/completion trong provider là đỏ ở đây: 12 != 34.
    assert (kq.noi_dung, kq.token_vao, kq.token_ra) == ("xin chào", 12, 34)
    assert client.goi == [("chat", {"model": "m", "messages": [{"role": "user", "content": "hỏi"}], "temperature": 0})]


def test_openai_tuong_thich_embedding_giu_thu_tu_va_usage():
    vec = [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]
    client = _OpenAIGia(embedding_response=_embedding_response(vec, prompt=20))
    ncc = OpenAITuongThich(ten="ncc", client=client)
    kq = asyncio.run(ncc.nhung("e", ["a", "b", "c"]))
    assert [list(v) for v in kq.vector] == vec
    assert kq.token_vao == 20
    assert client.goi[0][1]["input"] == ["a", "b", "c"] and client.goi[0][1]["model"] == "e"


@pytest.mark.parametrize(
    "response",
    [_chat_response(usage=False), _chat_response(choices=False),
     SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="x"))],
                     usage=SimpleNamespace(prompt_tokens=None, completion_tokens=3))],
    ids=["usage_none", "choices_rong", "prompt_tokens_none"],
)
def test_openai_phan_hoi_thieu_usage_la_loi_co_ma(response):
    ncc = OpenAITuongThich(ten="ncc", client=_OpenAIGia(chat_response=response))
    with pytest.raises(ProviderUsageMissing) as loi:
        asyncio.run(ncc.hoan_thanh("m", [{"role": "user", "content": "x"}]))
    assert loi.value.code == "PROVIDER_USAGE_MISSING"


def test_openai_embedding_thieu_usage_la_loi_co_ma():
    ncc = OpenAITuongThich(ten="ncc", client=_OpenAIGia(embedding_response=_embedding_response([[1.0]], usage=False)))
    with pytest.raises(ProviderUsageMissing) as loi:
        asyncio.run(ncc.nhung("e", ["a"]))
    assert loi.value.code == "PROVIDER_USAGE_MISSING"


class _OllamaGia:
    def __init__(self, chat_response=None, embed_response=None):
        self._chat, self._embed, self.goi = chat_response, embed_response, []

    async def chat(self, **kwargs):
        self.goi.append(("chat", kwargs))
        return self._chat

    async def embed(self, **kwargs):
        self.goi.append(("embed", kwargs))
        return self._embed


def test_ollama_cuc_bo_dich_dung_prompt_eval_count_va_eval_count():
    resp = SimpleNamespace(message=SimpleNamespace(content="trả lời"), prompt_eval_count=7, eval_count=9)
    ncc = OllamaCucBo(ten="ollama", client=_OllamaGia(chat_response=resp))
    kq = asyncio.run(ncc.hoan_thanh("q", [{"role": "user", "content": "x"}]))
    assert (kq.noi_dung, kq.token_vao, kq.token_ra) == ("trả lời", 7, 9)
    assert ncc.cuc_bo is True

    emb = SimpleNamespace(embeddings=[[1.0, 2.0], [3.0, 4.0]], prompt_eval_count=5)
    ncc_e = OllamaCucBo(ten="ollama", client=_OllamaGia(embed_response=emb))
    kq_e = asyncio.run(ncc_e.nhung("e", ["a", "b"]))
    assert [list(v) for v in kq_e.vector] == [[1.0, 2.0], [3.0, 4.0]] and kq_e.token_vao == 5


@pytest.mark.parametrize(
    "resp",
    [SimpleNamespace(message=SimpleNamespace(content="x"), prompt_eval_count=None, eval_count=1),
     SimpleNamespace(message=SimpleNamespace(content="x"), prompt_eval_count=1, eval_count=None),
     SimpleNamespace(message=None, prompt_eval_count=1, eval_count=1)],
    ids=["prompt_eval_none", "eval_none", "message_none"],
)
def test_ollama_phan_hoi_thieu_usage_la_loi_co_ma(resp):
    ncc = OllamaCucBo(ten="ollama", client=_OllamaGia(chat_response=resp))
    with pytest.raises(ProviderUsageMissing) as loi:
        asyncio.run(ncc.hoan_thanh("q", [{"role": "user", "content": "x"}]))
    assert loi.value.code == "PROVIDER_USAGE_MISSING"
    ncc_e = OllamaCucBo(
        ten="ollama", client=_OllamaGia(embed_response=SimpleNamespace(embeddings=[[1.0]], prompt_eval_count=None))
    )
    with pytest.raises(ProviderUsageMissing):
        asyncio.run(ncc_e.nhung("e", ["a"]))


class _EmbeddingSaiHinh:
    ten, cuc_bo = "gia", False

    def __init__(self, vector):
        self._vector = vector

    async def nhung(self, model, texts):
        return KetQuaEmbedding(vector=self._vector, token_vao=1)


@pytest.mark.parametrize(
    "vector",
    [[[0.0] * 8], [[0.0] * 8, [0.0] * 8, [0.0] * 8], [[0.0] * 8, [0.0] * 7]],
    ids=["thieu_vector", "thua_vector", "sai_so_chieu"],
)
def test_embedding_sai_hinh_dang_bi_tu_choi_truoc_khi_tra(khong_gian, policy, vector):
    so = SoAuditBoNho()
    emb = bo_embedding(
        nha_cung_cap=_EmbeddingSaiHinh(vector), model=MODEL_EMBEDDING_GIA, audit=so, danh_muc=danh_muc_gia()
    )

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            with pytest.raises(EmbeddingShapeMismatch) as loi:
                await emb(["a", "b"])
        return loi.value.code

    assert asyncio.run(chay()) == "EMBEDDING_SHAPE_MISMATCH"
    assert so.su_kien == [], "sai hình dạng thì không có sự kiện chi phí"


def test_khong_test_nao_dung_provider_tu_os_environ():
    """Bộ test không mạng, không key: mọi lời gọi hai factory phải truyền `moi_truong=`.

    Fixture autouse trong conftest xóa key khỏi `os.environ`, còn test này canh
    ở tầng mã nguồn để một test mới không lặng lẽ dựa vào môi trường máy chạy.
    """
    ham = {"ham_tu_moi_truong", "nha_cung_cap_tu_moi_truong"}
    vi_pham = []
    for py in (REPO_ROOT / "tests").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            ten = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if ten not in ham:
                continue
            co_keyword = any(k.arg == "moi_truong" for k in node.keywords)
            co_vi_tri = ten == "nha_cung_cap_tu_moi_truong" and len(node.args) >= 3
            if not (co_keyword or co_vi_tri):
                vi_pham.append(f"{py.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not vi_pham, "gọi factory provider bằng os.environ:\n" + "\n".join(vi_pham)


def test_key_provider_khong_co_trong_moi_truong_luc_test():
    """Đối chứng của fixture autouse: dựng từ `os.environ` là thiếu key, không phải gọi mạng."""
    import os

    dm = danh_muc_mac_dinh()
    for ncc in dm.nha_cung_cap.values():
        if not ncc.cuc_bo:
            assert ncc.bien_api_key not in os.environ


# --- Ledger 2.2: kwargs sinh của upstream sang `options=` của Ollama ---------



def _ollama_ok():
    return _OllamaGia(
        chat_response=SimpleNamespace(
            message=SimpleNamespace(content="x"), prompt_eval_count=1, eval_count=1
        )
    )


def test_ollama_map_kwargs_sinh_sang_options_va_format():
    """`max_tokens`/`temperature` vào `options`, `response_format` json_object thành `format="json"`."""
    client = _ollama_ok()
    ncc = OllamaCucBo(ten="ollama", client=client)
    asyncio.run(
        ncc.hoan_thanh(
            "q",
            [{"role": "user", "content": "x"}],
            max_tokens=256,
            temperature=0,
            response_format={"type": "json_object"},
            keep_alive="5m",
        )
    )
    _, kwargs = client.goi[0]
    assert kwargs["model"] == "q" and kwargs["messages"] == [{"role": "user", "content": "x"}]
    assert kwargs["options"] == {"num_predict": 256, "temperature": 0}
    assert kwargs["format"] == "json"
    assert kwargs["keep_alive"] == "5m"
    assert "max_tokens" not in kwargs and "temperature" not in kwargs and "response_format" not in kwargs


def test_ollama_response_format_json_schema_thanh_dict_va_options_co_san_duoc_gop():
    client = _ollama_ok()
    ncc = OllamaCucBo(ten="ollama", client=client)
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    asyncio.run(
        ncc.hoan_thanh(
            "q",
            [{"role": "user", "content": "x"}],
            response_format={"type": "json_schema", "json_schema": {"name": "s", "schema": schema}},
            options={"num_ctx": 8192},
            temperature=0.5,
        )
    )
    _, kwargs = client.goi[0]
    assert kwargs["format"] == schema
    assert kwargs["options"] == {"num_ctx": 8192, "temperature": 0.5}


def test_ollama_khong_co_kwargs_thi_khong_them_options():
    client = _ollama_ok()
    asyncio.run(OllamaCucBo(ten="ollama", client=client).hoan_thanh("q", [{"role": "user", "content": "x"}]))
    assert set(client.goi[0][1]) == {"model", "messages"}


@pytest.mark.parametrize(
    "kwargs",
    [{"presence_penalty": 1.0}, {"response_format": {"type": "text"}}, {"response_format": "json"}],
    ids=["kwarg_la", "response_format_la", "response_format_khong_map"],
)
def test_ollama_kwarg_la_bi_tu_choi_truoc_khi_goi(kwargs):
    client = _ollama_ok()
    ncc = OllamaCucBo(ten="ollama", client=client)
    with pytest.raises(ProviderKwargUnknown) as loi:
        asyncio.run(ncc.hoan_thanh("q", [{"role": "user", "content": "x"}], **kwargs))
    assert loi.value.code == "PROVIDER_KWARG_UNKNOWN"
    assert client.goi == [], "provider bị gọi dù kwarg lạ"


def test_ollama_qua_wrapper_van_nhan_kwargs_da_map(session_prefix, policy):
    """Đường thật: upstream bind `llm_model_kwargs` bằng partial, wrapper chuyển tiếp."""
    client = _ollama_ok()
    so = SoAuditBoNho()
    ncc = OllamaCucBo(ten=NCC_CUC_BO_GIA, client=client)
    llm = bo_llm(nha_cung_cap=ncc, model=MODEL_LLM_CUC_BO_GIA, audit=so, danh_muc=danh_muc_gia())

    async def chay():
        with use_context(vai(policy, "devops", f"{session_prefix}_real")):
            return await llm("hỏi", hashing_kv=None, max_tokens=10)

    assert asyncio.run(chay()) == "x"
    assert client.goi[0][1]["options"] == {"num_predict": 10}
    assert so.cac_su_kien(EVENT_LLM_COST)[0].chi_tiet[CT_CHI_PHI_USD] == 0


# --- Story 2.3: `san_sang()` của Ollama ---------------------------------------


class _OllamaListGia:
    def __init__(self, kieu):
        self.kieu = kieu

    async def list(self):
        if self.kieu == "no":
            raise ConnectionError("giả lập: ollama không nghe")
        if self.kieu == "treo":
            import asyncio

            await asyncio.sleep(10)
        return {"models": []}


@pytest.mark.parametrize("kieu,ky_vong", [("ok", True), ("no", False), ("treo", False)])
def test_ollama_san_sang_tra_loi_nem_va_treo(monkeypatch, kieu, ky_vong):
    import adapters.llm_wrapper as mod

    monkeypatch.setattr(mod, "THOI_HAN_SAN_SANG", 0.05)
    ncc = OllamaCucBo(ten="ollama", client=_OllamaListGia(kieu))
    assert asyncio.run(ncc.san_sang()) is ky_vong


# --- Story 2.4: `extra_body` từ danh mục tới SDK OpenAI ---------------------------


def test_openai_tuong_thich_truyen_extra_body_nguyen_ven_khi_co():
    client = _OpenAIGia(chat_response=_chat_response())
    ncc = OpenAITuongThich(ten="ncc", client=client, extra_body={"thinking": {"type": "disabled"}})
    asyncio.run(ncc.hoan_thanh("m", [{"role": "user", "content": "hỏi"}], temperature=0))
    assert client.goi[0][1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert client.goi[0][1]["temperature"] == 0


def test_openai_tuong_thich_khong_extra_body_thi_khong_co_tham_so():
    client = _OpenAIGia(chat_response=_chat_response())
    ncc = OpenAITuongThich(ten="ncc", client=client)
    asyncio.run(ncc.hoan_thanh("m", [{"role": "user", "content": "hỏi"}]))
    assert "extra_body" not in client.goi[0][1]


def test_nha_cung_cap_tu_moi_truong_mang_extra_body_cua_muc():
    from tests.gia_lap_llm import MODEL_LLM_TAT_SUY_LUAN_GIA

    dm = danh_muc_gia()
    moi_truong = {"GIA_API_KEY": "k"}
    co = nha_cung_cap_tu_moi_truong(dm.muc(MODEL_LLM_TAT_SUY_LUAN_GIA), dm, moi_truong)
    khong = nha_cung_cap_tu_moi_truong(dm.muc(MODEL_LLM_GIA), dm, moi_truong)
    assert isinstance(co, OpenAITuongThich) and co.extra_body == {"thinking": {"type": "disabled"}}
    assert isinstance(khong, OpenAITuongThich) and khong.extra_body is None


def test_extra_body_di_tu_danh_muc_toi_chat_completions_create():
    """Đường đầy đủ: mục model có `extra_body` -> provider -> `create(..., extra_body=...)`."""
    from tests.gia_lap_llm import MODEL_LLM_TAT_SUY_LUAN_GIA

    dm = danh_muc_gia()
    ncc = nha_cung_cap_tu_moi_truong(dm.muc(MODEL_LLM_TAT_SUY_LUAN_GIA), dm, {"GIA_API_KEY": "k"})
    client = _OpenAIGia(chat_response=_chat_response())
    ncc._client = client
    asyncio.run(ncc.hoan_thanh(MODEL_LLM_TAT_SUY_LUAN_GIA, [{"role": "user", "content": "x"}], max_tokens=8))
    goi = client.goi[0][1]
    assert goi["extra_body"] == {"thinking": {"type": "disabled"}} and goi["max_tokens"] == 8
    # Bản gửi SDK là dict thường tuần tự hóa được, không phải MappingProxyType
    # của danh mục (so `==` với dict vẫn đúng nên phải kiểm kiểu tường minh).
    import json

    json.dumps(goi["extra_body"])
    assert type(goi["extra_body"]) is dict and type(goi["extra_body"]["thinking"]) is dict


def test_extra_body_cua_noi_goi_duoc_gop_khong_bi_de():
    """Vòng review 2.4: `extra_body` của nơi gọi gộp với của danh mục, khóa trùng thì danh mục thắng."""
    client = _OpenAIGia(chat_response=_chat_response())
    ncc = OpenAITuongThich(ten="ncc", client=client, extra_body={"thinking": {"type": "disabled"}})
    asyncio.run(
        ncc.hoan_thanh(
            "m", [{"role": "user", "content": "x"}], extra_body={"top_k": 5, "thinking": {"type": "enabled"}}
        )
    )
    assert client.goi[0][1]["extra_body"] == {"top_k": 5, "thinking": {"type": "disabled"}}
