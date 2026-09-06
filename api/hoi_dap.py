"""Endpoint hỏi đáp: token -> ngữ cảnh quyền -> engine -> envelope AD-8 (story 3.3).

Đây là **module `api/` duy nhất** chạm kho tri thức trên đường phục vụ, và là
module `api/` duy nhất dựng một `PermissionContext`. Cả hai điều đó là cố ý, và
cả hai đều có test canh: `tests/test_api_khong_cham_tang_che.py` đòi mọi module
`api/` cầm một đường tới kho phải khai kèm lý do, và đòi đúng một module dựng
ngữ cảnh quyền. Tuyến HTTP thì nằm ở `api/main.py` - nhờ vậy `main.py` vẫn
không import một cái tên nào của tầng ngữ cảnh quyền, và phép kiểm ấy giữ
nguyên ý nghĩa thay vì bị xóa đi ở story này.

Bốn luật của module, cả bốn là cơ chế chứ không phải quy ước.

**Năm khóa cấp một của envelope là hợp đồng đóng băng**: `answer`, `refused`,
`citations`, `graph`, `meta` (AD-8). Một serializer duy nhất dựng nó -
`dung_envelope` - và nó **đếm lại** tập khóa trước khi trả, nên một tuyến mới
của Epic 3 không dựng được một hình dạng thứ hai bằng cách ghép dict tay. Đổi
năm khóa này sau M2 phải đi qua correct-course.

**Vai, không gian và tài khoản thật chỉ đến từ token.** `ThanHoiDap` khai
`extra="forbid"`, nên `{"cau_hoi": "x", "role": "devops"}` là 400 trước khi có
lời gọi LLM nào. Không phải vì `role` trong thân sẽ được đọc - nó sẽ bị bỏ qua
- mà vì một thân *im lặng bỏ qua* một trường quyền là một API dạy người gọi
rằng trường đó có thể có tác dụng, và là chỗ để một phiên bản sau vô tình đọc
nó.

**Ngữ cảnh quyền dựng đúng một lần mỗi request**, qua `core.identity.ngu_canh_cua`
(cửa duy nhất hợp lệ, `tests/test_import_lint.py` canh), rồi `use_context(...)`
bọc **trọn** lời gọi `aquery`. Bảng chính sách đọc một lần ở đầu request và
truyền xuống dưới dạng object: đọc lại giữa chừng là hai adapter thấy hai bản
chính sách trong cùng một request, đúng thứ AD-3 sinh ra để chặn.

**Tiến trình phục vụ không bao giờ mở ngữ cảnh hệ thống.** Module này không
import `core.system_context` và `mo_engine` **không** gọi `khoi_tao()`. Đó
không phải một chỗ chưa làm: `khoi_tao()` dựng collection, payload index và
ràng buộc graph, tức việc của đường nạp. Cửa duy nhất mở cờ bỏ-filter nằm ở
`core/system_context.py` với một danh sách trắng import canh giữ, và thêm một
module `api/` vào đó là mở đúng cánh cửa mà NFR-10 đóng. Bỏ bước thì phát biểu
mạnh hơn một phép kiểm: **tiến trình phục vụ không có đường import nào tới một
ngữ cảnh hệ thống**. Cái giá phải nói ra: một stack mới dựng phải chạy một đợt
nạp trước truy vấn đầu tiên, và nếu chưa thì collection vắng cho
`KHO_KHONG_SAN_SANG` chứ không tự tạo - cái giá đó vốn đã có, vì một kho rỗng
không trả lời được gì.

`citations` rỗng và `graph` rỗng ở story này là **hình dạng đã chốt**, không
phải nội dung còn thiếu: nội dung citation là story 3.4, nội dung graph là 3.7.
`refused` luôn `False` trên đường trả lời: nhánh từ chối byte-identical của
FR-16 là story 3.5, và một nhánh từ chối nửa vời ở đây là hai serializer cho
cùng một envelope.
"""

import logging
import time

from pydantic import BaseModel, ConfigDict

from adapters.engine import (
    EngineACL,
    QueryModeKhongHoTro,
    cau_hinh_kho_tu_moi_truong,
    ket_noi_chua_dong,
)
from adapters.llm_wrapper import ham_tu_moi_truong
from adapters.neo4j import Neo4jUnavailable
from adapters.qdrant import QdrantIndexMissing
from adapters.thu_lai import (
    NGAN_SACH_TRUY_HOI,
    ChanNhipQuaLau,
    la_loi_mang_tam_thoi,
    ma_http_cua,
)
from api.xac_thuc import ClaimNguoiHoi, LoiXacThuc
from core.audit import (
    EVENT_QUERY,
    TIER_OBSERVATION,
    AuditPort,
    SuKienAudit,
    ghi_quan_sat,
    thoi_diem_utc,
)
from core.identity import DanhTinh, RoleUnknown, ngu_canh_cua
from core.permission import (
    KIND_USER,
    PermissionContext,
    PermissionContextMissing,
    use_context,
)
from core.policy import Policy

logger = logging.getLogger(__name__)

# --- Envelope ------------------------------------------------------------------

# Năm khóa cấp một, theo thứ tự AD-8. Tuple chứ không set: thứ tự là thứ người
# đọc một phản hồi curl thấy, và một envelope đổi thứ tự khóa giữa hai tuyến là
# một hợp đồng đọc khó hơn mà không được gì.
KHOA_ENVELOPE: tuple[str, ...] = ("answer", "refused", "citations", "graph", "meta")

# Ba trường của `meta`, **tập đóng và liệt kê tường minh**. Không có thời gian
# xử lý, không có timestamp, không có số đếm: `meta` đi ra trong cả lượt trả lời
# lẫn lượt từ chối của story 3.5, và bất cứ trường nào đổi theo *lý do* từ chối
# là một kênh dò phá đúng tính chất byte-identical mà FR-16 dựng ra. Thời gian
# truy vấn vì thế vào audit (`chi_tiet`), không vào response.
KHOA_META: tuple[str, ...] = ("role", "space", "policy_version")

# Hai khóa của `graph`, **tập đóng** như `meta`. Hai khóa chứ không phải một
# dict rỗng: panel đồ thị của FR-19 đọc `nodes`/`edges`, và một client phải viết
# hai đường đọc cho "chưa có đồ thị" với "đồ thị rỗng" là một client sẽ quên một
# đường. Nội dung là story 3.7; hình dạng chốt ở đây.
KHOA_GRAPH: tuple[str, ...] = ("nodes", "edges")


def graph_rong() -> dict:
    """Đồ thị rỗng, một object mới mỗi lần: hằng dict dùng chung là hằng sửa được."""
    return {"nodes": [], "edges": []}


# --- Mã lỗi --------------------------------------------------------------------

# Sáu mã của module này. Ba mã còn lại trên đường hỏi đáp đến từ tầng dưới và
# giữ nguyên `code` của chúng, đúng luật "test assert trên `code`":
# `TOKEN_KHONG_HOP_LE` (`api/xac_thuc.py`), `ROLE_UNKNOWN` (`core/identity.py`)
# và `PERMISSION_CONTEXT_MISSING` (`core/permission.py`).
MA_CAU_HOI_RONG: str = "CAU_HOI_RONG"
MA_CAU_HOI_QUA_DAI: str = "CAU_HOI_QUA_DAI"
MA_THAN_YEU_CAU_LA: str = "THAN_YEU_CAU_LA"
MA_LLM_LOI: str = "LLM_LOI"
MA_LLM_QUA_HAN: str = "LLM_QUA_HAN"
MA_KHO_KHONG_SAN_SANG: str = "KHO_KHONG_SAN_SANG"

# Mã của lớp thứ ba NFR-10 (khoản ledger 1.2). Hai lớp đầu là
# `tests/test_import_lint.py` (phía module) và `core.permission.use_context`
# (`SystemContextNested`, ngữ cảnh hệ thống sinh ra giữa chừng); lớp này chặn
# một ngữ cảnh hệ thống **đến từ ngoài** đúng tại tầng handler.
MA_NGU_CANH_KHONG_PHAI_VAI: str = "NGU_CANH_KHONG_PHAI_VAI"

# Thông điệp cố định. Không ghép đường dẫn, tên container hay tên biến môi
# trường vào thân lỗi: `POST /hoi-dap` là endpoint mở nhất của hệ, và cấu trúc
# máy chủ không phải thứ đi ra theo một lỗi 503.
THONG_DIEP_CAU_HOI_RONG: str = "câu hỏi rỗng"
THONG_DIEP_THAN_LA: str = (
    "thân yêu cầu chỉ nhận trường `cau_hoi`; vai, không gian và chế độ truy vấn"
    " lấy từ token, không nhận từ thân"
)
THONG_DIEP_LLM_LOI: str = "không gọi được mô hình ngôn ngữ"
THONG_DIEP_LLM_QUA_HAN: str = "mô hình ngôn ngữ không trả lời trong thời hạn"
THONG_DIEP_KHO: str = "kho tri thức chưa sẵn sàng"
THONG_DIEP_NGU_CANH_SAI: str = "ngữ cảnh quyền của request không phải ngữ cảnh vai"

# Độ dài tối đa của câu hỏi, tính bằng ký tự. Hằng có tên chứ không phải một số
# nằm trong một lời gọi: nó là một ngân sách (mỗi ký tự đi vào prompt trích từ
# khóa, tức tiền thật), và một ngân sách phải đọc được ở một chỗ. 4000 ký tự là
# rộng gấp nhiều lần mọi câu hỏi trong `eval/bo_cau_hoi.json` và vẫn nhỏ hơn
# hẳn cửa sổ ngữ cảnh, nên nó chặn ca dán cả một tài liệu vào ô hỏi chứ không
# chặn một câu hỏi dài thật.
DAI_CAU_HOI_TOI_DA: int = 4000

# Số lời gọi mà **một** truy vấn hybrid phát ra, đọc từ `vendor/` chứ không
# đoán. Hai con số này là toàn bộ chỗ mà trần độ trễ của một request khác trần
# của một lời gọi, và bản đầu của story 3.3 đoán sai con số thứ hai (nó đếm một
# lời gọi embedding mỗi request và ra 162 giây).
#
# LLM: `vendor/hypergraphrag/operate.py::kg_query` gọi `use_model_func` hai lần -
# trích từ khóa (`:541`) và sinh câu trả lời (`:606`).
# Embedding: `_build_query_context` đi vào cả hai nhánh của mode `hybrid`, nên
# `entities_vdb.query` (`operate.py:743`) và `hyperedges_vdb.query` (`:938`) đều
# chạy, và mỗi `query` của `adapters/qdrant.py` nhúng đúng một chuỗi
# (`_embed_theo_lo([query])`), tức đúng một lời gọi embedding.
SO_LOI_GOI_LLM_MOI_TRUY_VAN: int = 2
SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN: int = 2


def tran_mot_truy_van_giay(ngan_sach=NGAN_SACH_TRUY_HOI) -> float:
    """Trần lý thuyết của **một** request, suy từ số lời gọi thật.

    Hàm chứ không hằng, và suy chứ không chép: đây là con số mà chương 4 phát
    biểu cho NFR-08, nên nó phải tính lại được từ hai chỗ đã khai - ngân sách
    (`adapters/thu_lai.py`) và số lời gọi của `vendor/kg_query` (hai hằng ngay
    trên). Một con số viết tay ở đây lỗi thời ngay lần đầu ai đó đổi một trong
    hai, và bản đầu của story 3.3 lỗi thời ngay lúc viết.

    Đường LLM **không** có lớp thử lại (luật đúng một lớp; nơi gọi nằm trong
    `vendor/kg_query`), nên nó góp đúng một trần mỗi lời gọi. Đường embedding
    có, nên nó góp `so_lan_thu` lần thử cộng `so_lan_thu - 1` khoảng chờ giữa
    chúng - và khoảng chờ đó **nằm trọn trong** `tran_cho_giay` kể cả phần
    jitter, nên con số này là một trần đúng chứ không một trần xấp xỉ.

    Hôm nay: 2 x 60 + 2 x (2 x 20 + 1 x 2) = **204 giây**. Là trần, không phải
    kỳ vọng.
    """
    mot_embedding = (
        ngan_sach.so_lan_thu * ngan_sach.tran_moi_loi_goi_giay
        + (ngan_sach.so_lan_thu - 1) * ngan_sach.tran_cho_giay
    )
    return (
        SO_LOI_GOI_LLM_MOI_TRUY_VAN * ngan_sach.tran_llm_giay
        + SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN * mot_embedding
    )


# Tên trường của `chi_tiet` trong sự kiện audit. Hằng vì `eval/` và báo cáo
# NFR-08 sẽ đọc đúng tên này bằng SQL trên cột jsonb.
CT_MILI_GIAY: str = "mili_giay"


class LoiHoiDap(LoiXacThuc):
    """Lỗi của đường hỏi đáp; cùng hình dạng `{error: {code, message}}`.

    Kế thừa `LoiXacThuc` để dùng lại đúng một exception handler của
    `api/main.py`, cùng tiền lệ với `api.chinh_sach.LoiChinhSach` - hai handler
    cho hai lớp lỗi cùng hình dạng là hai chỗ để envelope trôi dạt.
    """


class ThanHoiDap(BaseModel):
    """Thân của `POST /hoi-dap`: **đúng một** trường.

    `extra="forbid"` là nội dung của model, không phải một tinh chỉnh. Bốn tên
    mà một client có thể thử - `role`, `space`, `kind`, `mode` - đều là thứ
    quyết định người hỏi thấy gì hoặc engine chạy nhánh nào, và cả bốn phải đến
    từ token hoặc từ hằng của server. Nhận rồi bỏ qua thì không sai lúc chạy
    nhưng nó dạy người gọi rằng trường đó có nghĩa, và nó là chỗ để một phiên
    bản sau đọc nó thật.

    Không kiểm độ dài ở đây: `pydantic` sẽ trả một `RequestValidationError`
    chung với ca thừa trường, tức hai ca khác nhau ra cùng một `code`. Độ dài
    kiểm ở `tra_loi` để nó có mã riêng (`CAU_HOI_QUA_DAI`).
    """

    model_config = ConfigDict(extra="forbid")

    cau_hoi: str


def dung_meta(ngu_canh: PermissionContext) -> dict:
    """Ba trường `meta`, lấy **từ ngữ cảnh quyền** chứ không từ claim.

    Khác biệt có thật: `role` và `space` của claim là thứ token khai, còn của
    ngữ cảnh là thứ bảng chính sách đã phân giải được - và `policy_version` chỉ
    tồn tại ở phía ngữ cảnh. Đọc cả ba từ một nguồn nên không có ca `meta` khai
    một vai mà truy hồi chạy dưới vai khác.
    """
    return {
        "role": ngu_canh.role,
        "space": ngu_canh.space,
        "policy_version": ngu_canh.policy_version,
    }


def dung_envelope(*, answer, refused: bool, citations: list, graph: dict, meta: dict) -> dict:
    """Envelope AD-8, và là **chỗ duy nhất** dựng nó.

    Kiểm lại tập khóa của chính nó trước khi trả: một serializer không tự kiểm
    thì luật "năm khóa cấp một" chỉ sống trong văn xuôi, và tuyến thứ hai của
    Epic 3 sẽ ghép một dict tay thiếu hoặc thừa một khóa mà không ai thấy cho
    tới lúc một client vỡ.

    `answer` nhận `None` vì lượt từ chối của story 3.5 khai `answer: null`;
    trên đường trả lời nó luôn là chuỗi.
    """
    if answer is not None and not isinstance(answer, str):
        raise TypeError(f"answer phải là chuỗi hoặc None, nhận được {type(answer).__name__}")
    if not isinstance(refused, bool):
        raise TypeError(f"refused phải là bool, nhận được {type(refused).__name__}")
    if not isinstance(citations, list):
        raise TypeError(
            f"citations phải là list, nhận được {type(citations).__name__}"
        )
    if not isinstance(graph, dict) or set(graph) != set(KHOA_GRAPH):
        raise ValueError(
            f"graph là tập trường đóng {list(KHOA_GRAPH)}, nhận được"
            f" {sorted(graph) if isinstance(graph, dict) else type(graph).__name__}"
        )
    thieu = [k for k in KHOA_META if k not in meta]
    thua = [k for k in meta if k not in KHOA_META]
    if thieu or thua:
        raise ValueError(
            f"meta là tập trường đóng {list(KHOA_META)}: thiếu {thieu}, thừa {thua}."
            " Một trường đổi theo lý do từ chối là một kênh dò (AD-8, FR-16)."
        )
    envelope = {
        "answer": answer,
        "refused": refused,
        "citations": citations,
        "graph": graph,
        "meta": meta,
    }
    # `raise` chứ không `assert`, cùng luật với bốn phép kiểm trên: `python -O`
    # bỏ mọi `assert`, và khi đó phép canh **năm khóa cấp một** biến mất trong
    # khi ba phép canh nông hơn ở lại - tức hợp đồng quan trọng nhất của
    # serializer là hợp đồng duy nhất tắt được bằng một cờ dòng lệnh.
    if tuple(envelope) != KHOA_ENVELOPE:
        raise ValueError(
            f"envelope phải mang đúng năm khóa {list(KHOA_ENVELOPE)} theo thứ"
            f" tự đó, dựng ra {list(envelope)}"
        )
    return envelope


# --- Engine của tiến trình phục vụ ---------------------------------------------


async def mo_engine(audit: AuditPort) -> EngineACL:
    """Engine truy hồi của tiến trình; hàm riêng để test thay bằng bản giả.

    Cùng khuôn với `api.main.mo_kho_tai_khoan` và `api.main.mo_audit`: một điểm
    nối tên được, thay vì một lời gọi nằm giữa lifespan mà không có cách nào
    chen vào.

    Composition chép đúng `api.dot_nap.dung_engine_tu_moi_truong` với **hai**
    khác biệt, cả hai có lý do:

    - **không** `entity_dictionary_path`: từ điển thực thể chỉ dùng lúc trích
      xuất (nó đổi id entity của thứ được *ghi*), nên một từ điển trên đường
      đọc là một cấu hình không có tác dụng nào ngoài việc trông như có;
    - **ngân sách truy hồi** thay ngân sách nạp: đường nạp chờ được vài phút,
      một câu hỏi thì không (khoản ledger 2.13).

    **Không gọi `khoi_tao()`.** Xem docstring đầu file.

    Dựng `EngineACL` **không mở socket nào** - cả `AsyncQdrantClient` lẫn driver
    Neo4j đều mở pool lười - nên thêm engine vào lifespan không bắt ba kho phải
    khỏe trước khi một người đăng nhập được. Kết nối thật mở ở lời gọi đầu tiên.

    Dựng hỏng *sau* khi hai kết nối đã mở thì đóng chúng rồi dội **lỗi nguyên
    vẹn**: `EngineACL.__post_init__` là hàm đồng bộ nên nó không tự đóng được,
    nó chỉ gắn phần còn mở lên chính ngoại lệ, và đây là chỗ async duy nhất đọc
    dấu đó (khoản ledger 1.7). Không bọc lỗi vào một lớp mới: `api/man_nap.py`
    bắt theo `code` và bộ test bắt theo loại.
    """
    ham = ham_tu_moi_truong(audit=audit, ngan_sach=NGAN_SACH_TRUY_HOI)
    try:
        return EngineACL(
            **cau_hinh_kho_tu_moi_truong(),
            llm_model_func=ham.llm,
            embedding_func=ham.embedding,
            llm_model_max_token_size=ham.llm_max_token,
        )
    except BaseException as loi:
        con_mo = ket_noi_chua_dong(loi)
        if con_mo is not None:
            await con_mo.dong()
        raise


# --- Một lượt hỏi ---------------------------------------------------------------


def kiem_cau_hoi(cau_hoi: str) -> str:
    """Câu hỏi đã cắt khoảng trắng; rỗng hay quá dài là hai mã lỗi khác nhau.

    Hai mã chứ không một: "bạn chưa gõ gì" và "bạn dán quá nhiều" là hai việc
    khác nhau người gọi phải làm, và một mã chung buộc client đọc thông điệp
    tiếng Việt để phân biệt.

    Đo trên bản **chưa cắt**: một câu hỏi 4001 ký tự trong đó 10 ký tự là dấu
    cách vẫn là một câu hỏi 4001 ký tự đi qua đường mạng và đi vào bộ nhớ.
    """
    if not isinstance(cau_hoi, str):
        raise LoiHoiDap(400, MA_THAN_YEU_CAU_LA, THONG_DIEP_THAN_LA)
    if len(cau_hoi) > DAI_CAU_HOI_TOI_DA:
        raise LoiHoiDap(
            400,
            MA_CAU_HOI_QUA_DAI,
            f"câu hỏi dài {len(cau_hoi)} ký tự, tối đa {DAI_CAU_HOI_TOI_DA}",
        )
    sach = cau_hoi.strip()
    if not sach:
        raise LoiHoiDap(400, MA_CAU_HOI_RONG, THONG_DIEP_CAU_HOI_RONG)
    return sach


def ngu_canh_cua_claim(claim: ClaimNguoiHoi, policy: Policy) -> PermissionContext:
    """Ngữ cảnh quyền của một request, dựng **đúng một lần**, từ token và bảng.

    Ba trường của `DanhTinh` lấy trọn từ claim đã ký: không đọc lại seed (một
    phép đọc thứ hai là một chỗ để hai nguồn lệch nhau giữa lúc token còn sống)
    và không đọc gì từ thân request.

    Cửa cuối cùng là lớp thứ ba của NFR-10: kết quả phải là ngữ cảnh **vai**.
    Hôm nay `ngu_canh_cua` không có nhánh nào trả về ngữ cảnh hệ thống, nên cửa
    này là phòng vệ - nhưng nó là phòng vệ *chạy được*, và nó đứng đúng chỗ mà
    khoản ledger 1.2 chỉ ra: tầng handler, chỗ một ngữ cảnh hệ thống **đến từ
    ngoài** sẽ đi vào nếu có ai nối một đường như thế.
    """
    try:
        danh_tinh = DanhTinh(
            tai_khoan=claim.sub, vai=claim.role, khong_gian=claim.space
        )
        ngu_canh = ngu_canh_cua(danh_tinh, policy)
    except RoleUnknown as loi:
        # 403 chứ không 500: token hợp lệ, nhưng vai nó khai không có trong bảng
        # đang chạy. Thông điệp **không** ghép tên vai hay tên tài khoản vào -
        # nó là một cách liệt kê danh mục vai của bảng chính sách từ bên ngoài.
        logger.warning("vai không có trong bảng chính sách đang chạy: %s", loi)
        raise LoiHoiDap(
            403, RoleUnknown.code, "vai của tài khoản không có trong bảng chính sách"
        ) from None
    except (TypeError, ValueError) as loi:
        # `DanhTinh` từ chối chuỗi rỗng, khoảng trắng bao quanh và `space` sai
        # hình dạng. Một token ký đúng vẫn mang được ba thứ đó (nó được ký bởi
        # chính hệ này ở một phiên bản seed khác), nên đây không phải ca không
        # xảy ra.
        logger.warning("claim không dựng được danh tính: %s", loi)
        raise LoiHoiDap(400, MA_THAN_YEU_CAU_LA, "token mang danh tính không hợp lệ") from None
    if ngu_canh.kind != KIND_USER:
        raise LoiHoiDap(500, MA_NGU_CANH_KHONG_PHAI_VAI, THONG_DIEP_NGU_CANH_SAI)
    return ngu_canh


def _loi_truy_hoi(loi: BaseException) -> "LoiHoiDap | None":
    """Ngoại lệ của đường truy hồi -> một mã lỗi ổn định của dự án, hoặc `None`.

    Bốn nhánh, và **thứ tự là nội dung**: nhận diện lỗi *kho* cạn kiệt trước
    rồi mới hỏi mã HTTP.

    1. **Lỗi kho** -> 503. Ba nguồn, không một: hai ngoại lệ của chính dự án
       (`QDRANT_INDEX_MISSING`, `NEO4J_UNAVAILABLE`), *và* mọi ngoại lệ sinh ra
       từ hai SDK kho. Nhánh thứ ba là chỗ sửa một giả định sai của bản đầu:
       `qdrant_client.http.exceptions.UnexpectedResponse` **có** `.status_code`,
       và `adapters/qdrant.py` chỉ bọc *một số* đường vào `QdrantIndexMissing` -
       nên hỏi mã HTTP trước là báo một Qdrant trả 500 thành "không gọi được mô
       hình ngôn ngữ", tức chỉ sai người vận hành đi tìm sai chỗ. Căn cứ phân
       biệt là **module gốc của lớp ngoại lệ** (`qdrant_client.*`, `neo4j.*`,
       `grpc.*`), đọc qua `__module__` chứ không import SDK nào vào `api/`.
    2. `TimeoutError` -> 504: trần cho một lời gọi đã nổ, tức một lời gọi treo,
       khác hẳn một lời gọi bị từ chối.
    3. còn lại mà **đọc được một mã HTTP** -> 502: sau khi ngân sách truy hồi
       cạn thì lỗi provider dội nguyên lên, và mã của nó là thứ nói được đó là
       lỗi phía LLM. `ChanNhipQuaLau` vào cùng nhánh vì nó *là* một 429 đã bỏ
       cuộc.
    4. **lỗi mạng tạm thời** -> 503, nhận diện bằng
       `adapters.thu_lai.la_loi_mang_tam_thoi` chứ không bằng một `isinstance`
       trên `ConnectionError`/`OSError`: `openai.APIConnectionError` không phải
       `OSError`, nó giữ lỗi gốc ở `__cause__`, nên một phép `isinstance` để
       lọt trọn nhóm đó ra ngoài cả bốn nhánh. Hàm kia đi hết chuỗi
       `__cause__`/`__context__`. Nhánh này gộp một ca không phân biệt được từ
       đây - một `ConnectionError` tới Qdrant và một tới provider trông giống
       hệt nhau - và chọn 503, vì lỗi provider *có* mã HTTP đã bị nhánh 3 bắt.

    Ngoài bốn nhánh là `None`: nơi gọi để lỗi dội nguyên, vì bịa một mã cho một
    ngoại lệ chưa ai xếp loại là làm mất chính thông tin cần để xếp loại nó lần
    sau. Handler `api.main._loi_khong_xac_dinh` lo phần hình dạng của nó.
    """
    if isinstance(loi, (QdrantIndexMissing, Neo4jUnavailable)) or _tu_sdk_kho(loi):
        return LoiHoiDap(503, MA_KHO_KHONG_SAN_SANG, THONG_DIEP_KHO)
    if isinstance(loi, TimeoutError):
        return LoiHoiDap(504, MA_LLM_QUA_HAN, THONG_DIEP_LLM_QUA_HAN)
    if isinstance(loi, ChanNhipQuaLau) or ma_http_cua(loi) is not None:
        return LoiHoiDap(502, MA_LLM_LOI, THONG_DIEP_LLM_LOI)
    if la_loi_mang_tam_thoi(loi):
        return LoiHoiDap(503, MA_KHO_KHONG_SAN_SANG, THONG_DIEP_KHO)
    return None


# Gốc module của hai SDK kho cộng lớp truyền tải của chúng. Đọc theo **tên
# module** chứ không theo lớp ngoại lệ, cùng thủ pháp và cùng lý do với
# `adapters/thu_lai.py`: biết tên lớp ngoại lệ của từng SDK là một chỗ nữa phải
# sửa mỗi lần đổi driver, và `api/` thì còn không được import chúng.
GOC_SDK_KHO: tuple[str, ...] = ("qdrant_client", "neo4j", "grpc", "httpcore")


def _tu_sdk_kho(loi: BaseException) -> bool:
    """Ngoại lệ này (hay một nguyên nhân của nó) đến từ SDK của một kho.

    Duyệt cả chuỗi `__cause__`/`__context__` vì cùng lý do với
    `la_loi_mang_tam_thoi`: driver bọc lỗi tầng dưới lại và lớp ngoài cùng
    thường là lớp của chính driver.
    """
    da_qua: set[int] = set()
    hien_tai: BaseException | None = loi
    while hien_tai is not None and id(hien_tai) not in da_qua:
        da_qua.add(id(hien_tai))
        goc = type(hien_tai).__module__.split(".")[0]
        if goc in GOC_SDK_KHO:
            return True
        hien_tai = hien_tai.__cause__ or hien_tai.__context__
    return False


async def _ghi_audit_truy_van(
    audit: AuditPort, ngu_canh: PermissionContext, mili_giay: float
) -> None:
    """Sự kiện `query` ở tầng **observation**: audit hỏng không làm câu hỏi hỏng.

    `hyperedge_ids` để rỗng cho tới story 3.4 - id thật của hyperedge chỉ nhìn
    thấy được ở một điểm duy nhất của đường truy hồi (`vendor/operate.py:931`),
    và khe thu thập nó là thiết kế của 3.4. Ghi một tuple rỗng là đúng hình dạng
    và không giả vờ có số.

    `chi_tiet` mang mili giây, thứ NFR-08 đọc. Nó vào audit chứ không vào `meta`
    vì `meta` phải byte-identical giữa mọi lý do từ chối (AD-8).
    """
    await ghi_quan_sat(
        audit,
        SuKienAudit(
            tier=TIER_OBSERVATION,
            event=EVENT_QUERY,
            space=ngu_canh.space,
            policy_version=ngu_canh.policy_version,
            thoi_diem=thoi_diem_utc(),
            act=ngu_canh.real_account,
            role=ngu_canh.role,
            chi_tiet={CT_MILI_GIAY: round(mili_giay, 3)},
        ),
    )


async def tra_loi(
    cau_hoi: str,
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    engine: EngineACL,
    audit: AuditPort,
) -> dict:
    """Một lượt hỏi: kiểm đầu vào, dựng ngữ cảnh một lần, truy hồi, trả envelope.

    Thứ tự cố định và không đổi được: kiểm đầu vào **trước** khi dựng ngữ cảnh
    (một câu hỏi rỗng không đáng một phép tra bảng chính sách), dựng ngữ cảnh
    **trước** khi chạm engine (một vai lạ là 403 mà không chạm kho), và
    `use_context` bọc **trọn** `aquery` - kể cả phần `vendor/` gọi lại wrapper
    LLM, thứ đọc `current_context()` để kiểm space.

    `policy` là object đã đọc, không phải kho chính sách: nơi gọi đọc
    `hien_tai()` **một lần** ở đầu request rồi truyền xuống. Nhận một kho ở đây
    là mở đường cho một lời gọi `hien_tai()` thứ hai sau một `await`, tức hai
    bản chính sách trong cùng một request.

    Audit ghi ở nhánh **thành công**: sự kiện của lượt từ chối và lượt lọc là
    story 3.6, và một `query` ghi kèm cho mọi ca lỗi ở đây sẽ trộn thời gian
    của một lượt trả lời thật với thời gian của một lần chạm 502 - đúng thứ
    làm mẫu số NFR-08 vô nghĩa.
    """
    # Bấm giờ **từ đầu lượt**, trước cả phép kiểm đầu vào: `mili_giay` là số
    # NFR-08 đọc, và NFR-08 nói về độ trễ mà người hỏi chịu - bấm sau phép dựng
    # ngữ cảnh là báo một con số nhỏ hơn thời gian thật của chính lượt đó.
    bat_dau = time.perf_counter()
    sach = kiem_cau_hoi(cau_hoi)
    ngu_canh = ngu_canh_cua_claim(claim, policy)
    try:
        with use_context(ngu_canh):
            # Gọi **không** truyền `param`: `EngineACL.aquery` dựng một
            # `QueryParam()` mới của chính nó khi `param is None` (một bản sao
            # mỗi lời gọi, vì `_build_query_context` ghi lên `mode` của bất kỳ
            # instance nào nó nhận). Nhờ vậy `api/` không phải import
            # `hypergraphrag.base` - chiều import của `api/` là `core/`,
            # `adapters/`, `redteam/`, và `vendor/` không nằm trong đó.
            #
            # Ba tham số mà người gọi **không** đặt được, và cả ba là quyết
            # định của server: `mode` (`EngineACL.aquery` từ chối mọi giá trị
            # ngoài danh mục trước khi chạm `vendor/`), `only_need_context`, và
            # `stream` - giữ `False` vì wrapper chưa đếm được token trên stream
            # (khoản ledger 2.2, UX-DR4).
            answer = await engine.aquery(sach)
    except PermissionContextMissing:
        # Fail-closed của AD-8: 500 với đúng `code` của `core/`, không bọc lại.
        # Nó nghĩa là contextvar quyền đứt giữa `use_context` và adapter, tức
        # một lỗi cấu trúc của tiến trình chứ không một lỗi của người hỏi.
        raise LoiHoiDap(
            500, PermissionContextMissing.code, "thiếu ngữ cảnh quyền cho lời gọi này"
        ) from None
    except QueryModeKhongHoTro:
        raise LoiHoiDap(
            500, QueryModeKhongHoTro.code, "chế độ truy vấn không được hỗ trợ"
        ) from None
    except Exception as loi:
        da_biet = _loi_truy_hoi(loi)
        if da_biet is None:
            raise
        # Log nguyên lỗi, trả một thông điệp cố định: người vận hành cần biết
        # host nào không lên, người gọi thì không.
        logger.warning("truy hồi hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None
    mili_giay = (time.perf_counter() - bat_dau) * 1000.0
    await _ghi_audit_truy_van(audit, ngu_canh, mili_giay)
    return dung_envelope(
        answer=answer,
        # Luôn `False` trên đường trả lời. Nhánh từ chối byte-identical của
        # FR-16 là story 3.5, và một nhánh nửa vời ở đây là hai serializer cho
        # cùng một envelope.
        refused=False,
        citations=[],
        graph=graph_rong(),
        meta=dung_meta(ngu_canh),
    )


__all__ = [
    "CT_MILI_GIAY",
    "DAI_CAU_HOI_TOI_DA",
    "KHOA_ENVELOPE",
    "KHOA_GRAPH",
    "SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN",
    "SO_LOI_GOI_LLM_MOI_TRUY_VAN",
    "tran_mot_truy_van_giay",
    "KHOA_META",
    "MA_CAU_HOI_QUA_DAI",
    "MA_CAU_HOI_RONG",
    "MA_KHO_KHONG_SAN_SANG",
    "MA_LLM_LOI",
    "MA_LLM_QUA_HAN",
    "MA_NGU_CANH_KHONG_PHAI_VAI",
    "MA_THAN_YEU_CAU_LA",
    "LoiHoiDap",
    "ThanHoiDap",
    "dung_envelope",
    "dung_meta",
    "graph_rong",
    "kiem_cau_hoi",
    "mo_engine",
    "ngu_canh_cua_claim",
    "tra_loi",
]
