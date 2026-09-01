"""1.2-UNIT-001: ngữ cảnh quyền fail-closed (NFR-10, AD-3).

Test viết trước cơ chế (FR-27): đọc contextvar chưa ai set phải là lỗi nhìn
thấy được, không phải một truy vấn chạy không filter. Kèm hai tính chất mà
story 1.3-1.6 dựa vào: context bất biến, và hai truy vấn async song song không
lẫn ngữ cảnh của nhau (rủi ro contextvar đứt qua pipeline async của upstream).

Không cần mạng, không key LLM, không container.
"""

import asyncio
import dataclasses
import inspect

import pytest

from core.ids import SPACE_MAX_LEN
from core.permission import (
    PermissionContext,
    PermissionContextMissing,
    SystemContextForbidden,
    SystemContextRawRead,
    current_context,
    use_context,
    user_context,
)
from core.policy import NAMESPACES
from core.system_context import system_context
from tests.fixtures import oracle

# Tám trường của AD-3, đúng thứ tự khai trong spine.
TAM_TRUONG = (
    "kind",
    "space",
    "role",
    "real_account",
    "allowed_keys",
    "masked_slots",
    "grant_ids",
    "policy_version",
)


def test_thieu_ngu_canh_thi_raise():
    """Chưa ai set contextvar thì đọc là lỗi, không có kết quả không filter."""
    with pytest.raises(PermissionContextMissing):
        current_context()


def test_ma_loi_fail_closed():
    """Mã lỗi ổn định để tầng API trả `PERMISSION_CONTEXT_MISSING` (AD-8)."""
    assert PermissionContextMissing.code == "PERMISSION_CONTEXT_MISSING"


def test_khong_co_duong_bo_filter():
    """`current_context()` không nhận tham số mặc định nào để đi vòng fail-closed."""
    assert list(inspect.signature(current_context).parameters) == []


def test_context_frozen(policy):
    """Context bất biến: hai adapter trong cùng request không thấy hai bản."""
    ctx = user_context(
        policy=policy, role="tech_support", space="synth", real_account="ts01"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.role = "devops"


def test_du_tam_truong(policy):
    """Đúng 8 trường của AD-3, gồm cả `real_account`."""
    assert tuple(f.name for f in dataclasses.fields(PermissionContext)) == TAM_TRUONG


def test_factory_dung_allowed_keys_theo_oracle(policy):
    """`allowed_keys` của factory khớp oracle tính độc lập, đủ 3 namespace."""
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    for vai in ("devops", "tech_support"):
        ctx = user_context(
            policy=policy, role=vai, space="synth", real_account="tk_" + vai
        )
        ky_vong = oracle.allowed_keys_ky_vong(bang, vai)
        assert set(ctx.allowed_keys) == set(NAMESPACES)
        for namespace in NAMESPACES:
            assert set(ctx.keys_for(namespace)) == ky_vong[namespace], (vai, namespace)


def test_factory_mang_masked_slots_dang_map(policy):
    """`masked_slots` là map loại nội dung -> tập slot, không phải tập phẳng (AD-3)."""
    bang = oracle.doc_bang_chinh_sach(oracle.POLICY_TOI_GIAN)
    ctx = user_context(
        policy=policy, role="tech_support", space="synth", real_account="ts01"
    )
    ky_vong = oracle.masked_slots_ky_vong(bang, "tech_support")
    assert {loai: set(s) for loai, s in ctx.masked_slots.items()} == ky_vong
    assert set(ctx.slots_to_mask("bao_cao_su_co")) == ky_vong["bao_cao_su_co"]
    assert set(ctx.slots_to_mask("runbook")) == set()


def test_vai_khac_nhau_thi_khoa_khac_nhau(policy):
    """Hai vai hỏi cùng lúc phải mang hai tập khóa khác nhau (nền của M1)."""
    devops = user_context(
        policy=policy, role="devops", space="synth", real_account="dev01"
    )
    ts = user_context(
        policy=policy, role="tech_support", space="synth", real_account="ts01"
    )
    assert devops.keys_for("hyperedges") != ts.keys_for("hyperedges")
    assert ts.keys_for("chunks") < devops.keys_for("chunks")


def test_vai_la_thi_tu_choi(policy):
    """Vai không có trong bảng chính sách không dựng được context."""
    with pytest.raises(KeyError):
        user_context(policy=policy, role="khong_co", space="synth", real_account="x")


def test_context_system_mang_co_bo_filter(policy):
    """Context hệ thống mang cờ bỏ-filter, không mang `allowed_keys` (AD-3)."""
    sys_ctx = system_context(space="synth", policy_version=policy.policy_version)
    user_ctx = user_context(
        policy=policy, role="devops", space="synth", real_account="dev01"
    )
    assert sys_ctx.kind == "system" and sys_ctx.bypass_filter is True
    assert sys_ctx.allowed_keys is None
    assert user_ctx.kind == "user" and user_ctx.bypass_filter is False


def test_doc_allowed_keys_tren_context_system_la_loi_lap_trinh(policy):
    """Adapter gặp cờ bỏ-filter phải đọc thô, không được hỏi tập khóa."""
    sys_ctx = system_context(space="synth", policy_version=policy.policy_version)
    with pytest.raises(SystemContextRawRead):
        sys_ctx.keys_for("hyperedges")


def test_khong_co_trang_thai_thu_ba(policy):
    """Chỉ hai trạng thái: có cờ bỏ-filter, hoặc bị lọc theo `allowed_keys`."""
    sys_ctx = system_context(space="synth", policy_version=policy.policy_version)
    user_ctx = user_context(
        policy=policy, role="devops", space="synth", real_account="dev01"
    )
    for ctx in (sys_ctx, user_ctx):
        assert ctx.bypass_filter is (ctx.allowed_keys is None)


def test_thoat_khoi_use_context_thi_lai_fail_closed(policy):
    """Ra khỏi phạm vi một request là trở về trạng thái thiếu ngữ cảnh."""
    ctx = user_context(
        policy=policy, role="devops", space="synth", real_account="dev01"
    )
    with use_context(ctx):
        assert current_context() is ctx
    with pytest.raises(PermissionContextMissing):
        current_context()


def test_hai_task_async_khong_lan_context(policy):
    """Hai truy vấn chạy song song giữ đúng ngữ cảnh của mình."""
    devops = user_context(
        policy=policy, role="devops", space="synth", real_account="dev01"
    )
    ts = user_context(
        policy=policy, role="tech_support", space="synth", real_account="ts01"
    )

    async def mot_truy_van(ctx, nhip):
        with use_context(ctx):
            for _ in range(nhip):
                await asyncio.sleep(0)
                assert current_context() is ctx
            return current_context().role

    async def chay():
        return await asyncio.gather(
            mot_truy_van(devops, 5), mot_truy_van(ts, 3), mot_truy_van(devops, 4)
        )

    assert asyncio.run(chay()) == ["devops", "tech_support", "devops"]


def test_task_con_khong_ro_ri_context_ra_ngoai(policy):
    """Task con set context không làm bẩn ngữ cảnh của nơi tạo ra nó."""
    ctx = user_context(
        policy=policy, role="devops", space="synth", real_account="dev01"
    )

    async def chay():
        async def task_con():
            with use_context(ctx):
                await asyncio.sleep(0)

        await asyncio.create_task(task_con())
        with pytest.raises(PermissionContextMissing):
            current_context()

    asyncio.run(chay())


# --- Bất biến của chính PermissionContext -------------------------------


def _truong_hop_le(**doi):
    """Bộ tham số dựng một context người dùng hợp lệ, cho phép đổi từng trường."""
    tham_so = dict(
        kind="user",
        space="synth",
        role="devops",
        real_account="dev01",
        allowed_keys={"chunks": frozenset(), "entities": frozenset(), "hyperedges": frozenset()},
        masked_slots={},
        grant_ids=(),
        policy_version="x",
    )
    tham_so.update(doi)
    return tham_so


def test_dung_thang_context_he_thong_bi_chan():
    """Cửa duy nhất phải là cửa duy nhất thật: chuỗi "system" trần không qua."""
    with pytest.raises(SystemContextForbidden):
        PermissionContext(**_truong_hop_le(kind="system", allowed_keys=None, role=None))


def test_kind_la_bi_chan():
    """Không có kind thứ ba bên cạnh user/system."""
    with pytest.raises(ValueError):
        PermissionContext(**_truong_hop_le(kind="admin"))


def test_co_bo_filter_phai_khop_voi_allowed_keys():
    """Hai nửa của bất biến "không có trạng thái thứ ba", canh cả hai chiều."""
    with pytest.raises(ValueError):
        PermissionContext(**_truong_hop_le(allowed_keys=None))


def test_grant_ids_phai_la_tuple():
    """Chuỗi trần bị `tuple()` cắt thành từng ký tự - phải chặn ở cửa."""
    with pytest.raises(TypeError):
        PermissionContext(**_truong_hop_le(grant_ids="g1"))


def test_factory_tu_choi_grant_ids_dang_chuoi(policy):
    with pytest.raises(TypeError):
        user_context(
            policy=policy,
            role="devops",
            space="synth",
            real_account="dev01",
            grant_ids="g1",
        )


@pytest.mark.parametrize("truong", ["space", "real_account"])
def test_factory_tu_choi_dinh_danh_rong(policy, truong):
    """Ngữ cảnh không định danh được thì audit và cách ly space đều vô nghĩa."""
    tham_so = dict(
        policy=policy, role="devops", space="synth", real_account="dev01"
    )
    tham_so[truong] = "  "
    with pytest.raises(ValueError):
        user_context(**tham_so)


# --- Hình dạng của `space` (AD-12) ---------------------------------------


@pytest.mark.parametrize("space", ["synth", "test_3fa9c1d2_synth", "khachHangA", "s1"])
def test_space_hop_le_thi_qua(policy, space):
    """Quy ước tên đang dùng ở fixture và ở compose phải còn hợp lệ."""
    assert (
        user_context(
            policy=policy, role="devops", space=space, real_account="dev01"
        ).space
        == space
    )
    assert system_context(space=space, policy_version="v").space == space


@pytest.mark.parametrize(
    "space",
    [
        "",
        "  ",
        " synth",
        "synth ",
        "1synth",
        "_synth",
        "synth-b",
        "synth.b",
        "a b",
        # Dài hơn giới hạn đúng một ký tự. Suy từ hằng của `core/` chứ không
        # viết 65: nới `SPACE_MAX_LEN` mà ca biên không đi theo là test này
        # lặng lẽ ngừng kiểm đúng thứ nó sinh ra để kiểm.
        "x" * (SPACE_MAX_LEN + 1),
    ],
)
def test_space_hong_thi_tu_choi_o_ca_hai_factory(policy, space):
    """`space` đi thẳng vào tên collection Qdrant và nhãn Neo4j (story 1.4).

    Một ký tự phải trích dẫn ở đâu đó là một chỗ trích dẫn sai làm truy vấn trỏ
    nhầm không gian dữ liệu, mà cách ly theo space chính là chiều cách ly dữ
    liệu của hệ. Cả hai cửa dựng ngữ cảnh đều phải chặn, không chỉ cửa người
    dùng: ingest cũng ghi vào đúng những cái tên đó.
    """
    with pytest.raises(ValueError):
        user_context(policy=policy, role="devops", space=space, real_account="dev01")
    with pytest.raises(ValueError):
        system_context(space=space, policy_version="v")


@pytest.mark.parametrize("xau", [None, 3, ["synth"]])
def test_space_sai_kieu_la_type_error(policy, xau):
    """Sai kiểu là `TypeError`, cùng luật với các hàm thuần khác của core."""
    with pytest.raises(TypeError):
        user_context(policy=policy, role="devops", space=xau, real_account="dev01")


@pytest.mark.parametrize("xau", [None, "khong-phai-context", 42])
def test_use_context_tu_choi_vat_la(xau):
    """Quấn nhầm thứ không phải ngữ cảnh quyền là lỗi ngay, không im lặng."""
    with pytest.raises(TypeError):
        with use_context(xau):
            pass


def test_ma_loi_cua_hai_ngoai_le_con_lai():
    """Consistency Conventions: mọi lỗi ra API đều có `code` ổn định."""
    assert SystemContextRawRead.code == "SYSTEM_CONTEXT_RAW_READ"
    assert SystemContextForbidden.code == "SYSTEM_CONTEXT_FORBIDDEN"


# --- Ranh giới truyền context qua thread (nền của story 1.3) -------------


def test_run_in_executor_mat_context_nen_fail_closed(policy):
    """`run_in_executor` không mang contextvar theo - phải fail-closed, không đọc thô.

    Ghim hành vi này ở đây để story 1.3 biết trước: đẩy phần đọc storage sang
    executor là mất ngữ cảnh quyền, và đường lùi engine per-request của spine là
    để dành cho đúng ca đó.
    """

    def doc_trong_thread():
        try:
            return current_context().role
        except PermissionContextMissing:
            return "fail-closed"

    async def chay():
        with use_context(
            user_context(
                policy=policy, role="devops", space="synth", real_account="dev01"
            )
        ):
            vong = asyncio.get_running_loop()
            return await vong.run_in_executor(None, doc_trong_thread)

    assert asyncio.run(chay()) == "fail-closed"


def test_to_thread_giu_context(policy):
    """`asyncio.to_thread` sao chép context nên ngữ cảnh quyền đi theo."""

    async def chay():
        with use_context(
            user_context(
                policy=policy, role="devops", space="synth", real_account="dev01"
            )
        ):
            return await asyncio.to_thread(lambda: current_context().role)

    assert asyncio.run(chay()) == "devops"


def test_khong_long_ngu_canh_he_thong_vao_giua_request(policy):
    """`use_context(system_context(...))` lồng trong ngữ cảnh vai bị chặn.

    Đây là đường leo quyền im lặng duy nhất mà hai trạng thái của
    `PermissionContext` để hở: mọi lời gọi bên trong đọc thô, không filter, mà
    nhìn từ ngoài vẫn là request của một vai.

    Lớp này khác lớp của NFR-10: tầng handler (Epic 3) từ chối một ngữ cảnh hệ
    thống *đến từ ngoài*, còn cửa này chặn một ngữ cảnh hệ thống *sinh ra giữa
    chừng*.
    """
    from core.permission import SystemContextNested

    ctx_vai = user_context(
        policy=policy, role="tech_support", space="synth", real_account="ts01"
    )
    ctx_he_thong = system_context(space="synth", policy_version=policy.policy_version)
    with use_context(ctx_vai):
        with pytest.raises(SystemContextNested) as loi:
            with use_context(ctx_he_thong):
                pass
        assert loi.value.code == "SYSTEM_CONTEXT_NESTED"
        # Ngữ cảnh vai không bị lời gọi hỏng đó làm xê dịch.
        assert current_context() is ctx_vai


def test_long_nguoc_lai_thi_duoc(policy):
    """Vai mở trong ngữ cảnh hệ thống là thu hẹp quyền, không phải leo quyền."""
    ctx_he_thong = system_context(space="synth", policy_version=policy.policy_version)
    with use_context(ctx_he_thong):
        with use_context(
            user_context(
                policy=policy, role="devops", space="synth", real_account="dev01"
            )
        ):
            assert current_context().bypass_filter is False
        assert current_context().bypass_filter is True
