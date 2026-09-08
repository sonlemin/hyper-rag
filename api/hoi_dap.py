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
bọc **trọn** lời gọi `hoi_dap`. Bảng chính sách đọc một lần ở đầu request và
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

`graph` rỗng trên đường `/hoi-dap` là **hình dạng đã chốt**; nội dung graph đi
ra qua `POST /do-thi` (story 3.7, `api/do_thi.py`) bằng cùng serializer, và
`dung_envelope` kiểm từng node/edge như nó kiểm citation. `citations` có nội
dung từ story 3.4: mỗi mục là
một dict **sáu khóa đóng** (`adapters.trich_dan.KHOA_TRICH_DAN`), dựng ở engine
từ ngữ cảnh truy hồi cộng cửa quyền của adapter graph, và `dung_envelope` kiểm
từng mục như nó kiểm `meta`. Handler chỉ chuyển `TrichDan` sang dict; nó không
dựng, không lọc, không đếm citation nào. Một id trong ngữ cảnh mà adapter không
thấy là 500 `TRICH_DAN_NGOAI_QUYEN`, không phải một citation bị bỏ lặng lẽ.

**Nhánh từ chối byte-identical của FR-16 vào ở story 3.5.** Ba lý do -
`ngu_canh_rong`, `co_no_answer`, `tu_khoa_rong` - đi ra qua **đúng một** lời gọi
`dung_envelope`, cùng lời gọi mà đường trả lời dùng, nên thân response của ba
lượt từ chối bằng nhau từng byte khi vai và bảng chính sách giữ nguyên. Lý do
chỉ vào audit (`refusal`, tầng observation), không vào response: một trường đổi
theo lý do là đúng kênh dò mà FR-16 dựng ra để bịt. Đầu ra LLM không đọc được
thì **không** phải một lý do thứ tư - nó là 502 mang mã ổn định.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict

from adapters.do_thi import (
    KHOA_CANH,
    KHOA_NODE_ENTITY,
    KHOA_NODE_HYPEREDGE,
    DoThi,
    NodeHyperedge,
    do_thi_tu_dict,
)
from adapters.trich_dan import KHOA_TRICH_DAN, MUC_TRICH_DAN, TrichDan, TrichDanNgoaiQuyen
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
from adapters.tra_loi import (
    LY_DO_CO_NO_ANSWER,
    LY_DO_NGU_CANH_RONG,
    LY_DO_TU_KHOA_RONG,
    SO_LAN_HOI_LAI_TU_KHOA_HONG,
    DauRaTraLoiKhongDoc,
)
from api.xac_thuc import ClaimNguoiHoi, LoiXacThuc
from core.audit import (
    AuditPort,
    CT_REQUEST_ID,
    EVENT_PERMISSION_MISMATCH,
    EVENT_QUERY,
    EVENT_REFUSAL,
    SuKienAudit,
    TIER_MUTATION,
    TIER_OBSERVATION,
    ghi_bien_doi,
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


# --- Từ chối (FR-16, story 3.5) ------------------------------------------------

# Wording template từ chối, **chốt ở story 3.5 kèm `docs/adr/ADR-015`**, và là
# hằng duy nhất mang câu này trong repo. Nó đóng câu hỏi mở 2 của
# `ux-designs/.../EXPERIENCE.md:79` (chỗ wording còn mang dấu `[ASSUMPTION]`) và
# action item Epic 3 của sonlm.
#
# Vì sao nó **không** đi vào `answer`: envelope của một lượt từ chối khai
# `answer: null` (AD-8), tức máy đọc cờ `refused` chứ không đọc một câu tiếng
# Việt. Câu này là hợp đồng của tầng **render** - màn chat của Epic 4 hiện đúng
# nó, không tự soạn lại - và nó sống ở đây vì `api/` là tầng cuối cùng còn thấy
# cả hình dạng envelope lẫn ý nghĩa của `refused`.
#
# Không ghép gì đổi theo lý do vào nó: không vai, không nhóm phụ trách, không
# tên scope, không số đếm. Một chữ đổi theo lý do là đúng kênh dò mà FR-16 dựng
# ra để bịt, và người dò không cần đọc `answer` mới thấy - độ dài chuỗi là đủ.
TEMPLATE_TU_CHOI: str = "Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi này."

# Ba lý do từ chối (`LY_DO_NGU_CANH_RONG`, `LY_DO_CO_NO_ANSWER`,
# `LY_DO_TU_KHOA_RONG`) **nhập từ `adapters/tra_loi.py` chứ không chép lại**:
# nơi *quyết* lý do là `EngineACL.hoi_dap`, và một bản viết tay thứ hai ở đây là
# một chuỗi lệch một chữ mà không phép so nào bắt được - hàng audit vẫn ghi, chỉ
# là ghi một giá trị không ai truy vấn tới. Hai giá trị đầu là hai cột mà Đo 2
# (PRD 5.2) và story 7.4 đếm tách; giá trị thứ ba đứng riêng để một lỗi nội bộ
# của bước trích từ khóa không bơm vào cột nào. Chúng nằm trong `__all__` của
# module này để nơi đọc audit không phải biết cả hai tầng.
DANH_MUC_LY_DO: tuple[str, ...] = (
    LY_DO_NGU_CANH_RONG,
    LY_DO_CO_NO_ANSWER,
    LY_DO_TU_KHOA_RONG,
)


# --- Mã lỗi --------------------------------------------------------------------

# Bảy mã của module này: sáu từ story 3.3, cộng `DAU_RA_LLM_KHONG_DOC_DUOC` của
# 3.5 khai ngay dưới. Ba mã còn lại trên đường hỏi đáp đến từ tầng dưới và
# giữ nguyên `code` của chúng, đúng luật "test assert trên `code`":
# `TOKEN_KHONG_HOP_LE` (`api/xac_thuc.py`), `ROLE_UNKNOWN` (`core/identity.py`)
# và `PERMISSION_CONTEXT_MISSING` (`core/permission.py`).
MA_CAU_HOI_RONG: str = "CAU_HOI_RONG"
MA_CAU_HOI_QUA_DAI: str = "CAU_HOI_QUA_DAI"
MA_THAN_YEU_CAU_LA: str = "THAN_YEU_CAU_LA"
MA_LLM_LOI: str = "LLM_LOI"
MA_LLM_QUA_HAN: str = "LLM_QUA_HAN"
MA_KHO_KHONG_SAN_SANG: str = "KHO_KHONG_SAN_SANG"

# Mã thứ bảy, vào ở story 3.5. Nó là **lỗi hệ thống**, không phải một lý do từ
# chối: đầu ra LLM không đọc được theo lược đồ hai khóa của `adapters/tra_loi.py`
# ra 502 mang mã này, và không bao giờ suy diễn thành một envelope từ chối. 502
# chứ không 500 vì nguồn hỏng là provider, cùng họ với `LLM_LOI`; suy diễn nó
# thành từ chối là dựng nhánh từ chối thứ tư và là hệ nói dối về trạng thái của
# chính nó, đúng thứ làm hai cột của Đo 2 (PRD 5.2) đếm nhầm.
MA_DAU_RA_LLM_KHONG_DOC_DUOC: str = "DAU_RA_LLM_KHONG_DOC_DUOC"

# Mã thứ tám, vào ở story 3.4, **re-export** từ lớp ngoại lệ của `adapters/`
# chứ không chép chuỗi: ngữ cảnh truy hồi mang một id hyperedge mà cửa quyền
# của adapter graph không xác nhận dưới vai này. 500 vì nó là một lệch giữa
# tầng lọc và cửa quyền của chính hệ, không phải lỗi của provider hay của kho.
MA_TRICH_DAN_NGOAI_QUYEN: str = TrichDanNgoaiQuyen.code

# Mã thứ chín, vào ở story 3.6: hàng `refusal` ở tầng **mutation** (cờ chế độ đo
# bật, `api/che_do_do.py`) không ghi được. 500 chứ không 200 kèm WARNING: trong
# cửa sổ đo, một lượt từ chối không có bản ghi là một hàng của Đo 2 biến mất
# lặng lẽ, và hệ phải nói ra điều đó thay vì trả một envelope trông như đã đếm.
MA_AUDIT_GHI_HONG: str = "AUDIT_GHI_HONG"

# Mã thứ mười, vào ở story 3.7: `POST /do-thi` nhận nhiều id hơn `SO_ID_TOI_DA`.
# 400 trước khi chạm kho, cùng họ với `CAU_HOI_QUA_DAI` - một ngân sách có tên
# chứ không phải một con số trong lời gọi.
MA_DANH_SACH_ID_QUA_DAI: str = "DANH_SACH_ID_QUA_DAI"

# Số id hyperedge tối đa của một lượt lấy đồ thị. Đo trên máy chủ 06/09 (story
# 3.4): một lượt `devops` trên `synth` mang 97 citation, tức toàn bộ hyperedge
# trong ngữ cảnh (top_k 60 x hai nhánh hybrid, cắt theo 4000 token). 200 rộng
# gấp đôi con số đó nên nó chặn ca dán một danh sách id tùy ý chứ không chặn
# một lượt thật; kiểm trên danh sách **chưa khử trùng**, vì đó là thứ đi qua
# đường mạng.
SO_ID_TOI_DA: int = 200

# Trần chờ (giây) cho một lần ghi `refusal` ở tầng mutation. `ghi_bien_doi` của
# `core/` không có hạn (đúng nghĩa "ghi hỏng là thao tác hỏng"), nhưng một
# Postgres treo giữ kết nối mở mà không trả lời sẽ giữ request treo theo; quá
# hạn cũng là 500 `AUDIT_GHI_HONG`. Rộng hơn `THOI_HAN_QUAN_SAT` vì đây là hàng
# phải có chứ không phải hàng được phép mất.
THOI_HAN_BIEN_DOI: float = 10.0

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
THONG_DIEP_DAU_RA_LLM: str = "mô hình ngôn ngữ trả về đầu ra không đọc được"
THONG_DIEP_NGU_CANH_SAI: str = "ngữ cảnh quyền của request không phải ngữ cảnh vai"
THONG_DIEP_TRICH_DAN: str = "không dựng được trích dẫn theo quyền cho lượt này"
THONG_DIEP_AUDIT_HONG: str = "không ghi được sổ audit cho lượt này"
# Thông điệp của `POST /do-thi` khi một mục trong `hyperedge_ids` rỗng hay toàn
# khoảng trắng - nhánh duy nhất mà `api/do_thi.py` tự phát 400 `THAN_YEU_CAU_LA`
# (mục không phải chuỗi và trường thừa đã bị pydantic chặn qua handler chung).
THONG_DIEP_THAN_DO_THI: str = "`hyperedge_ids` phải là danh sách chuỗi không rỗng"

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
# LLM: hai lời gọi, và từ story 3.5 chúng đến từ **hai chỗ** chứ không còn cùng
# một hàm vendor. Một, trích từ khóa trong `vendor/.../operate.py::kg_query:541`.
# Hai, sinh câu trả lời bằng prompt của dự án ở `EngineACL.hoi_dap` - lời gọi
# `:606` của vendor không còn chạy, vì `hoi_dap` lấy ngữ cảnh bằng
# `only_need_context=True` và `:596-597` thoát *trước* nó. Con số vì thế không
# đổi lúc 3.5, nhưng lý do của nó đổi, và một bản upstream mới bỏ lời gọi `:606`
# đi cũng sẽ không đổi con số này nữa. Tên hằng vì thế **không** nói "vendor":
# chỉ một trong hai lời gọi còn là của vendor.
# Embedding: `_build_query_context` đi vào cả hai nhánh của mode `hybrid`, nên
# `entities_vdb.query` (`operate.py:743`) và `hyperedges_vdb.query` (`:938`) đều
# chạy, và mỗi `query` của `adapters/qdrant.py` nhúng đúng một chuỗi
# (`_embed_theo_lo([query])`), tức đúng một lời gọi embedding.
SO_LOI_GOI_LLM_NEN: int = 2
SO_LOI_GOI_EMBEDDING_NEN: int = 2

# Hai con số **của một lượt**, suy từ hai hằng nền cộng phép hỏi lại của story
# 4.7 - không chép tay. Và hai hằng cộng thêm **khác nhau**, vì một lần thử hỏng
# không tốn cùng những thứ mà một lượt trọn vẹn tốn.
#
# `EngineACL.ngu_canh_hoi_dap` gọi lại `aquery` đúng
# `SO_LAN_HOI_LAI_TU_KHOA_HONG` lần khi đường truy hồi trả `CAU_HONG_UPSTREAM`.
# Đọc `vendor/hypergraphrag/operate.py` để biết một lần gọi lại như thế tốn gì:
# mọi đường trả `PROMPTS["fail_response"]` mà `only_need_context=True` với tới
# được nằm ở `:568` (JSONDecodeError), `:573`, `:576` và `:581` (thiếu từ khóa),
# **tất cả trước** lời gọi `_build_query_context` ở `:584`; đường `:599` không
# với tới được vì `:596-597` trả về trước. Cả hai lời gọi embedding thì sinh ra
# *bên trong* `_build_query_context` (`:743`, `:938`).
#
# Hệ quả: một lần thử hỏng tốn **đúng một lời gọi LLM (trích từ khóa) và không
# một lời gọi embedding nào** - nó thoát trước khi có gì để nhúng. LLM 2 + 1 =
# **3**; embedding **giữ 2**.
#
# Là **trần**, không kỳ vọng: một lượt bình thường vẫn tốn 2 và 2, và lượt từ
# chối vì ngữ cảnh rỗng chỉ tốn 1 lời gọi LLM.
SO_LOI_GOI_LLM_MOI_TRUY_VAN: int = SO_LOI_GOI_LLM_NEN + SO_LAN_HOI_LAI_TU_KHOA_HONG
SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN: int = SO_LOI_GOI_EMBEDDING_NEN


def tran_mot_truy_van_giay(ngan_sach=NGAN_SACH_TRUY_HOI) -> float:
    """Trần lý thuyết của **một** request, suy từ số lời gọi thật.

    Hàm chứ không hằng, và suy chứ không chép: đây là con số mà chương 4 phát
    biểu cho NFR-08, nên nó phải tính lại được từ hai chỗ đã khai - ngân sách
    (`adapters/thu_lai.py`) và số lời gọi của `vendor/kg_query` (hai hằng ngay
    trên). Một con số viết tay ở đây lỗi thời ngay lần đầu ai đó đổi một trong
    hai, và bản đầu của story 3.3 lỗi thời ngay lúc viết.

    Đường LLM **không** có lớp thử lại 429/5xx, nên nó góp đúng một trần mỗi
    lời gọi - kể cả lời gọi của phép hỏi lại ở story 4.7, vốn là một lời gọi
    thứ ba chứ không phải một lần thử lại *bên trong* một lời gọi, và vì thế nó
    đi vào `SO_LOI_GOI_LLM_MOI_TRUY_VAN` chứ không vào công thức dưới. Đường embedding
    có, nên nó góp `so_lan_thu` lần thử cộng `so_lan_thu - 1` khoảng chờ giữa
    chúng - và khoảng chờ đó **nằm trọn trong** `tran_cho_giay` kể cả phần
    jitter, nên con số này là một trần đúng chứ không một trần xấp xỉ.

    Hôm nay: 3 x 60 + 2 x (2 x 20 + 1 x 2) = **264 giây**. Là trần, không phải
    kỳ vọng. Con số lên từ 204 ở story 4.7 vì phép hỏi lại khi đường truy hồi
    trả `CAU_HONG_UPSTREAM` thêm **một lời gọi LLM và không lời gọi embedding
    nào** (lần thử hỏng thoát ở `operate.py:568-581`, trước
    `_build_query_context`); nó là **hệ quả phải nói ra**, không một dấu hiệu
    hỏng, và nó vẫn không được áp ở đâu lúc chạy.
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
# Lý do từ chối, và **chỉ** ở đây. AD-8: nó không có mặt trong response, nên
# đây là chỗ duy nhất Đo 2 đọc được hai cột "từ chối qua cờ LLM" và "từ chối qua
# nhánh ngữ cảnh rỗng" tách nhau.
CT_LY_DO: str = "ly_do"
# Mã lỗi của hàng `permission_mismatch` (story 3.6); hôm nay chỉ một giá trị,
# `TRICH_DAN_NGOAI_QUYEN`, nhưng khóa có tên để lệch quyền thứ hai (Epic 5) ghi
# cùng hàng.
CT_MA: str = "ma"
# Dãy id hyperedge của grant break-glass mà lượt này chạy dưới (story 5.3),
# **chỉ có mặt khi ngữ cảnh mang grant**, ở cả ba hàng `query`, `refusal`,
# `permission_mismatch` (`_kem_grant`): hàng của mọi lượt không grant giữ
# nguyên hình dạng cũ, và hậu kiểm FR-20 đọc được lượt nào đã dùng quyền nâng.
# Không vào response (AD-8).
CT_GRANT_IDS: str = "grant_ids"

# Vai **thật** của người đang mượn vai (story 4.5), **chỉ có mặt khi lượt chạy
# dưới một token xem như**, ở cả ba hàng `query`, `refusal`,
# `permission_mismatch` - cùng khuôn và cùng lý do với `grant_ids` ngay trên.
#
# Vì sao cần: một lượt của `dev01` đang mượn `truong_nhom` ghi `act='dev01'`,
# `role='truong_nhom'`, tức **không khác một tài khoản `truong_nhom` thật**.
# Không có dấu này thì hậu kiểm FR-23 phải ghép hàng `query` với hàng
# `role_swap` gần nhất theo cửa sổ thời gian, và một cửa sổ thời gian là thứ
# hỏng lặng lẽ khi hai phiên chạy song song. Cùng tên khóa với `chi_tiet` của
# `role_swap` (`vai_that`), nên hai loại hàng đọc bằng một cái tên.
CT_VAI_THAT: str = "vai_that"


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

    Từng citation kiểm như `meta` (story 3.4): dict đúng sáu khóa
    `KHOA_TRICH_DAN`, `level` trong `MUC_TRICH_DAN`, `masked_slots` là list
    chuỗi, `owner_group` là chuỗi hoặc `None`. Sai hình là `ValueError` ngay
    tại đây, fail-closed: một citation thừa một khóa là một kênh nữa để nội
    dung rò ra ngoài tầng che.

    Từng node và edge của `graph` kiểm cùng cách (story 3.7): node theo `kind`
    đúng tập khóa đóng của loại đó, id node không trùng, mọi edge nối một node
    hyperedge có mặt tới một node entity có mặt - kiểm bằng cách **dựng lại**
    `adapters.do_thi.DoThi`, không viết bộ kiểm thứ hai.
    """
    if answer is not None and not isinstance(answer, str):
        raise TypeError(f"answer phải là chuỗi hoặc None, nhận được {type(answer).__name__}")
    if not isinstance(refused, bool):
        raise TypeError(f"refused phải là bool, nhận được {type(refused).__name__}")
    if not isinstance(citations, list):
        raise TypeError(
            f"citations phải là list, nhận được {type(citations).__name__}"
        )
    for td in citations:
        _kiem_trich_dan(td)
    if refused and citations:
        raise ValueError("lượt từ chối không mang citation (FR-16)")
    if not isinstance(graph, dict) or set(graph) != set(KHOA_GRAPH):
        raise ValueError(
            f"graph là tập trường đóng {list(KHOA_GRAPH)}, nhận được"
            f" {sorted(graph) if isinstance(graph, dict) else type(graph).__name__}"
        )
    _kiem_do_thi(graph)
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


def _kiem_trich_dan(td) -> None:
    """Một citation phải là dict đúng `KHOA_TRICH_DAN` và dựng lại được thành `TrichDan`.

    Kiểm bằng cách **dựng lại** chứ không viết một bộ kiểm thứ hai: bản đầu của
    story kiểm tay và yếu hơn `TrichDan.__post_init__` (bỏ lọt vai ngoài danh
    mục, sai thứ tự `SLOT_ROLES`, trùng, `owner_group` toàn khoảng trắng, `level`
    không hashable). Hai bộ kiểm là hai chỗ để lệch nhau; một bộ, ở `adapters/`,
    và serializer gọi lại nó. Mọi lỗi ra `ValueError` mang thông điệp rõ.
    """
    if not isinstance(td, dict):
        raise ValueError(f"citation phải là dict, nhận được {type(td).__name__}")
    thieu = [k for k in KHOA_TRICH_DAN if k not in td]
    thua = [k for k in td if k not in KHOA_TRICH_DAN]
    if thieu or thua:
        raise ValueError(
            f"citation là tập trường đóng {list(KHOA_TRICH_DAN)}: thiếu {thieu},"
            f" thừa {thua}. Một trường thêm vào citation là một kênh rò ngoài tầng che."
        )
    if not isinstance(td["masked_slots"], list):
        raise ValueError("masked_slots của citation phải là list tên vai")
    try:
        TrichDan(**{**td, "masked_slots": tuple(td["masked_slots"])})
    except (TypeError, ValueError) as loi:
        raise ValueError(f"citation sai hình dạng: {loi}") from loi


def dict_trich_dan(td: TrichDan) -> dict:
    """`TrichDan` -> dict đúng thứ tự `KHOA_TRICH_DAN`, `masked_slots` thành list.

    Đây là toàn bộ việc `api/` làm với một citation: chuyển kiểu. Không lọc,
    không thêm, không đọc lại quyền - ba thứ đó đã xong ở `adapters/`. `asdict`
    giữ tuple cho `masked_slots`; JSON không phân biệt, nhưng `dung_envelope`
    kiểm bằng `list` cho khớp thứ người gọi đọc lại từ thân response.
    """
    tho = asdict(td)
    return {k: (list(tho[k]) if k == "masked_slots" else tho[k]) for k in KHOA_TRICH_DAN}


def _kiem_do_thi(graph: dict) -> None:
    """`graph` phải dựng lại được thành `adapters.do_thi.DoThi`, không hơn không kém.

    Cùng thủ pháp với `_kiem_trich_dan`: một bộ kiểm ở `adapters/`
    (`do_thi_tu_dict`), serializer gọi lại nó và bộ test đọc thân response bằng
    đúng hàm ấy. Mọi lệch là `ValueError` ngay tại đây, fail-closed - một node
    thừa một khóa là một kênh nữa ra ngoài tầng che.
    """
    do_thi_tu_dict(graph)


def dict_do_thi(do_thi: DoThi) -> dict:
    """`DoThi` -> dict hai khóa `KHOA_GRAPH`, node và edge đúng thứ tự khóa đóng.

    Toàn bộ việc `api/` làm với đồ thị: chuyển kiểu. Không lọc, không thêm,
    không đọc lại quyền. Node đi ra theo tập khóa của loại nó, `kind` ở vị trí
    thứ hai như spec khai.
    """
    nodes = []
    for n in do_thi.nodes:
        tho = asdict(n)
        khoa = KHOA_NODE_HYPEREDGE if isinstance(n, NodeHyperedge) else KHOA_NODE_ENTITY
        nodes.append({k: tho[k] for k in khoa})
    return {
        "nodes": nodes,
        "edges": [{k: getattr(c, k) for k in KHOA_CANH} for c in do_thi.edges],
    }


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
            # Port cho sự kiện `filter` của adapter KV (story 3.6): một hàm
            # trả port chứ không phải port, vì `asdict(self)` deepcopy field.
            lay_audit=lambda: audit,
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


def ngu_canh_cua_claim(
    claim: ClaimNguoiHoi,
    policy: Policy,
    request_id: str | None = None,
    grant_ids: tuple[str, ...] = (),
) -> PermissionContext:
    """Ngữ cảnh quyền của một request, dựng **đúng một lần**, từ token và bảng.

    Ba trường của `DanhTinh` lấy trọn từ claim đã ký: không đọc lại seed (một
    phép đọc thứ hai là một chỗ để hai nguồn lệch nhau giữa lúc token còn sống)
    và không đọc gì từ thân request. `grant_ids` (story 5.3) là dãy id hyperedge
    mà `doc_grant_ids` vừa đọc từ kho grant cho đúng cặp `(sub, role)` của
    claim trong space của claim - **không** bao giờ từ thân hay từ claim
    (`ThanHoiDap` cấm trường ấy từ 3.3). Mặc định rỗng: ba tuyến break-glass
    dựng ngữ cảnh người xin qua đây và cố ý không đọc grant.

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
        ngu_canh = ngu_canh_cua(danh_tinh, policy, request_id=request_id, grant_ids=grant_ids)
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


async def doc_grant_ids(kho, claim: ClaimNguoiHoi) -> tuple[str, ...]:
    """Dãy id hyperedge của grant break-glass còn hạn của người hỏi (story 5.3).

    Đọc từ `KhoBreakGlass.grant_hieu_luc` cho cặp `(claim.sub, claim.role)`
    trong `claim.space` - đúng ba trường mà grant bind, nên grant ở vai khác
    ngủ. Gọi **trước** khi dựng ngữ cảnh, để `grant_ids` là một thành phần của
    ngữ cảnh đóng băng của lượt: grant hết hạn giữa lượt thì lượt vẫn chạy trọn
    với ngữ cảnh đã dựng, lượt kế không.

    Kho hỏng là 503 `KHO_KHONG_SAN_SANG` qua `api.break_glass.loi_kho`, **không**
    lặng lẽ hạ về `()`: một lượt chạy không grant vì kho rớt trông y như một
    lượt bình thường, và người vừa được duyệt sẽ tin rằng grant không có tác
    dụng. Import tại chỗ vì `api.break_glass` nhập module này ở đầu file.
    """
    from api.break_glass import loi_kho

    try:
        return tuple(await kho.grant_hieu_luc(claim.sub, claim.role, claim.space))
    except Exception as loi:
        da_biet = loi_kho(loi)
        if da_biet is None:
            raise
        logger.warning("kho grant break-glass hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None


def loi_truy_hoi(loi: BaseException) -> "LoiHoiDap | None":
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


def _kem_grant(
    chi_tiet: dict, ngu_canh: PermissionContext, vai_that: str | None = None
) -> dict:
    """`chi_tiet` cộng hai dấu **chỉ khi** lượt này có chúng.

    Một luật cho cả ba hàng của một lượt - `query`, `refusal`,
    `permission_mismatch`: hậu kiểm FR-20 đọc được lượt nào chạy dưới quyền
    nâng và hậu kiểm FR-23 đọc được lượt nào chạy dưới một vai mượn, dù lượt ấy
    trả lời, từ chối hay hỏng ở cửa quyền. Hàng của một lượt thường giữ nguyên
    hình dạng cũ **từng khóa**, nên sáu đợt nạp và mọi hàng đã ghi không đổi.

    `vai_that` đến từ `claim.act.role` ở nơi gọi chứ không từ ngữ cảnh: thêm một
    trường vào `PermissionContext` là một thay đổi `core/` thứ hai cho một dữ
    liệu mà không tầng nào dưới `api/` đọc - tầng che không tra nó, adapter
    không lọc theo nó, và nó chỉ đi vào một hàng sổ. Kênh đúng vì thế là tham số
    của ba hàm ghi audit, cả ba đều đã nhận `ngu_canh` từ cùng một nơi gọi.
    """
    if ngu_canh.grant_ids:
        chi_tiet = {**chi_tiet, CT_GRANT_IDS: list(ngu_canh.grant_ids)}
    if vai_that is not None:
        chi_tiet = {**chi_tiet, CT_VAI_THAT: vai_that}
    return chi_tiet


async def _ghi_audit_truy_van(
    audit: AuditPort,
    ngu_canh: PermissionContext,
    mili_giay: float,
    hyperedge_ids: tuple[str, ...],
    vai_that: str | None = None,
) -> None:
    """Sự kiện `query` ở tầng **observation**: audit hỏng không làm câu hỏi hỏng.

    `hyperedge_ids` là dãy id **node** hyperedge của **tập thấy** - mọi
    hyperedge trong ngữ cảnh đã lọc mà LLM đọc (`KetQuaHoiDap.hyperedge_da_thay`),
    đúng thứ tự ngữ cảnh. Story 3.4 ghi dãy id citation; story 3.8 (ADR-022)
    tách hai tập: `citations` của response là tập **dùng** (thu hẹp theo
    `nguon` của model), audit giữ tập thấy để hậu kiểm không phụ thuộc vào một
    danh sách do model khai. Tập dùng luôn là tập con của dãy này, nên phép so
    chuỗi "mọi `citations[].id` nằm trong `hyperedge_ids`" vẫn đứng. Quy ước ở
    `core/audit.py` nói "cùng id với citation" theo nghĩa cùng **loại** id
    (node, không phải vector). Lượt từ chối ghi tuple rỗng. Không đếm số mục bị
    lọc: đó là hàng `filter` của adapter KV (3.6), đứng cạnh hàng này và nối
    bằng `request_id`.

    `chi_tiet` mang mili giây, thứ NFR-08 đọc, cộng `request_id` để nối với
    `llm_cost`/`embedding_cost`/`filter` của cùng lượt. Cả hai vào audit chứ
    không vào `meta`, vì `meta` phải byte-identical giữa mọi lý do từ chối (AD-8).
    Khóa thứ ba `grant_ids` (story 5.3) **chỉ khi** ngữ cảnh mang grant: hàng
    của lượt không grant giữ nguyên hình dạng, hàng của lượt có grant nói lượt
    ấy chạy dưới những id nào; `hyperedge_ids` vẫn là dãy id tập thấy.
    """
    chi_tiet = _kem_grant(
        {CT_MILI_GIAY: round(mili_giay, 3), CT_REQUEST_ID: ngu_canh.request_id},
        ngu_canh,
        vai_that,
    )
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
            hyperedge_ids=hyperedge_ids,
            chi_tiet=chi_tiet,
        ),
    )


async def _ghi_audit_lech_quyen(
    audit: AuditPort,
    ngu_canh: PermissionContext,
    loi: TrichDanNgoaiQuyen,
    vai_that: str | None = None,
) -> None:
    """Sự kiện `permission_mismatch` (story 3.6), tầng observation, best-effort.

    Lượt hỏng vẫn **không** ghi `query` (mẫu số NFR-08 không trộn thời gian của
    một lần hỏng) và không ghi `refusal`; hàng này là dấu vết riêng cho hậu kiểm
    FR-20 của ca lệch giữa tầng lọc và cửa quyền. `hyperedge_ids` là các id
    thiếu - id node, cùng quy ước với `query`; thân lỗi thì không mang chúng.
    """
    await ghi_quan_sat(
        audit,
        SuKienAudit(
            tier=TIER_OBSERVATION,
            event=EVENT_PERMISSION_MISMATCH,
            space=ngu_canh.space,
            policy_version=ngu_canh.policy_version,
            thoi_diem=thoi_diem_utc(),
            act=ngu_canh.real_account,
            role=ngu_canh.role,
            hyperedge_ids=tuple(loi.ids),
            chi_tiet=_kem_grant(
                {CT_MA: MA_TRICH_DAN_NGOAI_QUYEN, CT_REQUEST_ID: ngu_canh.request_id},
                ngu_canh,
                vai_that,
            ),
        ),
    )


async def _ghi_audit_tu_choi(
    audit: AuditPort,
    ngu_canh: PermissionContext,
    ly_do: str,
    che_do_do: bool,
    vai_that: str | None = None,
) -> None:
    """Sự kiện `refusal`, tầng **theo cờ chế độ đo**, mang lý do trong `chi_tiet`.

    Đây là **chỗ duy nhất** lý do từ chối được ghi ra. Response của cả ba nhánh
    giống nhau từng byte (FR-16), nên nếu không có hàng này thì không ai phân
    biệt được một lượt từ chối vì cờ LLM với một lượt từ chối vì ngữ cảnh rỗng -
    và PRD 5.2 đòi Đo 2 báo cáo **tách hai cột**, "không đếm gộp để khỏi bơm độ
    chính xác của cờ".

    Cờ tắt (3.5): observation, cùng luật với `query` - một Postgres chết không
    được biến một lượt từ chối thành một 500, `ghi_quan_sat` nuốt lỗi của port
    thành một dòng WARNING và envelope không đổi một byte. Cờ bật (3.6, ADR-017):
    **mutation** qua `ghi_bien_doi`, ghi hỏng là 500 `AUDIT_GHI_HONG` - trong
    cửa sổ đo, hàng này là chính mẫu số của hai cột Đo 2, và một hàng được phép
    mất là một hàng harness không tin được. Thân 200 của hai chế độ giống nhau
    từng byte; chỉ `tier` của hàng đổi.

    Sự kiện này đứng **cạnh** `query`, không thay nó: một lượt từ chối vẫn là một
    lượt hỏi có độ trễ, và NFR-08 đo trên mọi lượt chứ không riêng lượt trả lời.
    """
    su_kien = SuKienAudit(
        tier=TIER_MUTATION if che_do_do else TIER_OBSERVATION,
        event=EVENT_REFUSAL,
        space=ngu_canh.space,
        policy_version=ngu_canh.policy_version,
        thoi_diem=thoi_diem_utc(),
        act=ngu_canh.real_account,
        role=ngu_canh.role,
        chi_tiet=_kem_grant(
            {CT_LY_DO: ly_do, CT_REQUEST_ID: ngu_canh.request_id},
            ngu_canh,
            vai_that,
        ),
    )
    if not che_do_do:
        await ghi_quan_sat(audit, su_kien)
        return
    try:
        await asyncio.wait_for(ghi_bien_doi(audit, su_kien), timeout=THOI_HAN_BIEN_DOI)
    except Exception as loi:
        logger.error("audit mutation refusal không ghi được (%s: %s)", type(loi).__name__, loi)
        raise LoiHoiDap(500, MA_AUDIT_GHI_HONG, THONG_DIEP_AUDIT_HONG) from None


async def tra_loi(
    cau_hoi: str,
    *,
    claim: ClaimNguoiHoi,
    policy: Policy,
    engine: EngineACL,
    audit: AuditPort,
    che_do_do: bool,
    kho,
) -> dict:
    """Một lượt hỏi: kiểm đầu vào, đọc grant, dựng ngữ cảnh một lần, truy hồi, trả envelope.

    Thứ tự cố định và không đổi được: kiểm đầu vào **trước** khi dựng ngữ cảnh
    (một câu hỏi rỗng không đáng một phép tra bảng chính sách), đọc grant
    break-glass (story 5.3, `kho` là `KhoBreakGlass`) **trước** khi dựng ngữ
    cảnh để `grant_ids` đóng băng cùng lượt, dựng ngữ cảnh **trước** khi chạm
    engine (một vai lạ là 403 mà không chạm kho), và `use_context` bọc **trọn**
    `hoi_dap` - kể cả phần `vendor/` gọi lại wrapper LLM, thứ đọc
    `current_context()` để kiểm space.

    `policy` là object đã đọc, không phải kho chính sách: nơi gọi đọc
    `hien_tai()` **một lần** ở đầu request rồi truyền xuống. Nhận một kho ở đây
    là mở đường cho một lời gọi `hien_tai()` thứ hai sau một `await`, tức hai
    bản chính sách trong cùng một request.

    Audit ghi ở nhánh **thành công**, và từ story 3.5 "thành công" gồm cả một
    lượt từ chối: `query` ghi cho cả hai loại lượt (một lượt từ chối vẫn có độ
    trễ mà NFR-08 đo), cộng một `refusal` mang lý do khi có từ chối. Ca **lỗi**
    thì vẫn không ghi gì - một `query` ghi kèm cho mỗi lần chạm 502 trộn thời
    gian của một lượt trả lời thật với thời gian của một lần hỏng, đúng thứ làm
    mẫu số NFR-08 vô nghĩa. Ngoại lệ duy nhất (3.6): lệch quyền hai tầng ghi
    một hàng `permission_mismatch` observation - dấu vết, không phải mẫu số.
    Sự kiện lọc của adapter KV (3.6) không ghi ở đây: nó phát từ chính adapter
    qua port `lay_audit`, và nối với hàng `query` bằng `request_id`.

    **Một chỗ dựng envelope cho cả ba nhánh từ chối lẫn nhánh trả lời.** Kết quả
    của engine là một `KetQuaHoiDap` mang đúng một trong hai trường (bất biến
    kiểm lúc dựng), nên `refused` suy ra bằng một phép so `None` và `answer` đi
    thẳng vào serializer. Hai đường ghép thân response là hai cơ hội để một
    trường lạc vào một trong hai, và khi đó phép so byte của FR-16 hỏng ở đúng
    chỗ không ai đọc.
    """
    # Bấm giờ **từ đầu lượt**, trước cả phép kiểm đầu vào: `mili_giay` là số
    # NFR-08 đọc, và NFR-08 nói về độ trễ mà người hỏi chịu - bấm sau phép dựng
    # ngữ cảnh là báo một con số nhỏ hơn thời gian thật của chính lượt đó.
    bat_dau = time.perf_counter()
    sach = kiem_cau_hoi(cau_hoi)
    # Grant break-glass còn hạn của cặp `(sub, role)` trong space (story 5.3):
    # đọc một lần, trước khi dựng ngữ cảnh, kho hỏng là 503 chứ không phải
    # một lượt không grant.
    grant_ids = await doc_grant_ids(kho, claim)
    # Một id cho mỗi lượt (story 3.6), đi trong `PermissionContext` xuống tận
    # wrapper LLM và adapter KV: `query`, `refusal`, `filter`, `llm_cost`,
    # `embedding_cost`, `permission_mismatch` của lượt này nối được với nhau.
    # Không vào response (AD-8).
    ngu_canh = ngu_canh_cua_claim(claim, policy, request_id=uuid.uuid4().hex, grant_ids=grant_ids)
    # Vai **thật** của người đang mượn vai (story 4.5), `None` với một lượt
    # thường. Nó chỉ đi vào ba hàng audit và **không** vào ngữ cảnh quyền: tầng
    # che không tra nó, adapter không lọc theo nó, và `meta` của response không
    # mang nó (AD-8 - một lượt mượn vai phải nhìn giống hệt một lượt của vai ấy
    # từ phía client, đó là chính điều "xem như" dựng ra để làm).
    vai_that = claim.act.role if claim.act is not None else None
    try:
        with use_context(ngu_canh):
            # Gọi **không** truyền `param`: `EngineACL.hoi_dap` dựng một
            # `QueryParam()` mới của chính nó khi `param is None` (một bản sao
            # mỗi lời gọi, vì `_build_query_context` ghi lên `mode` của bất kỳ
            # instance nào nó nhận). Nhờ vậy `api/` không phải import
            # `hypergraphrag.base` - chiều import của `api/` là `core/`,
            # `adapters/`, `redteam/`, và `vendor/` không nằm trong đó.
            #
            # Ba tham số mà người gọi **không** đặt được, và cả ba là quyết
            # định của server: `mode` (`EngineACL.aquery` từ chối mọi giá trị
            # ngoài danh mục trước khi chạm `vendor/`, và `hoi_dap` đi qua đúng
            # cửa đó), `only_need_context` (`hoi_dap` luôn bật), và `stream` -
            # giữ `False` vì wrapper chưa đếm được token trên stream, nay do
            # chính `hoi_dap` từ chối tường minh (khoản ledger 2.2, UX-DR4).
            #
            # `hoi_dap` chứ không `aquery` (story 3.5): nó lấy ngữ cảnh bằng
            # `only_need_context=True` rồi tự sinh câu trả lời bằng prompt của dự
            # án, và trả về một kết quả **có cấu trúc** thay vì một chuỗi. Đường
            # `aquery` giữ nguyên cho `eval/` và `tests/ho_tro_m1.py::hoi`.
            ket_qua = await engine.hoi_dap(sach)
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
    except TrichDanNgoaiQuyen as loi:
        # Story 3.4: ngữ cảnh mang một id hyperedge mà cửa quyền của adapter
        # graph không xác nhận. Lệch giữa tầng lọc và cửa quyền là lỗi cấu trúc
        # của hệ -> 500 mang mã ổn định, trước lời gọi LLM sinh câu trả lời và
        # không hàng `refusal`. Số id thiếu chỉ vào log: thân lỗi không được kể
        # ra ngữ cảnh có bao nhiêu mục.
        logger.warning("citation ngoài quyền: %s", loi)
        await _ghi_audit_lech_quyen(audit, ngu_canh, loi, vai_that)
        raise LoiHoiDap(500, MA_TRICH_DAN_NGOAI_QUYEN, THONG_DIEP_TRICH_DAN) from None
    except DauRaTraLoiKhongDoc as loi:
        # **Lỗi hệ thống, không phải một lý do từ chối.** Bắt trước nhánh chung
        # bên dưới vì `loi_truy_hoi` trả `None` cho nó (nó không mang mã HTTP
        # nào và không đến từ SDK kho), tức nó sẽ dội lên thành một 500 không
        # tên. Nguyên văn đầu ra hỏng chỉ vào log: nó là văn bản do LLM sinh ra
        # từ ngữ cảnh đã lọc, và một thân lỗi mang nó là một đường rò đi vòng
        # qua cả tầng che lẫn cả envelope.
        logger.warning("đầu ra LLM không đọc được: %s", loi)
        raise LoiHoiDap(
            502, MA_DAU_RA_LLM_KHONG_DOC_DUOC, THONG_DIEP_DAU_RA_LLM
        ) from None
    except Exception as loi:
        da_biet = loi_truy_hoi(loi)
        if da_biet is None:
            raise
        # Log nguyên lỗi, trả một thông điệp cố định: người vận hành cần biết
        # host nào không lên, người gọi thì không.
        logger.warning("truy hồi hỏng (%s): %s", type(loi).__name__, loi)
        raise da_biet from None
    mili_giay = (time.perf_counter() - bat_dau) * 1000.0
    # `KetQuaHoiDap` đã cấm "từ chối mà có citation" lúc dựng, nên dãy id này
    # tự rỗng ở lượt từ chối mà không cần một nhánh `if` thứ hai ở đây.
    citations = [dict_trich_dan(td) for td in ket_qua.trich_dan]
    tu_choi = ket_qua.ly_do_tu_choi is not None
    # `refusal` **trước** `query`: khi cờ chế độ đo bật và hàng `refusal` không
    # ghi được, lượt này là một lượt hỏng (500) và luật "ca lỗi không ghi
    # `query`" của NFR-08 phải giữ - ghi `query` trước là để lại một hàng thời
    # gian cho một lượt không trả lời được.
    if tu_choi:
        await _ghi_audit_tu_choi(audit, ngu_canh, ket_qua.ly_do_tu_choi, che_do_do, vai_that)
    # Audit ghi **tập thấy**, response mang tập dùng (story 3.8): hậu kiểm
    # không đứng trên một danh sách do model khai.
    await _ghi_audit_truy_van(audit, ngu_canh, mili_giay, ket_qua.hyperedge_da_thay, vai_that)
    return dung_envelope(
        # `None` ở lượt từ chối, và đó là hợp đồng chứ không một chỗ chưa điền:
        # câu người dùng đọc là `TEMPLATE_TU_CHOI`, do tầng render dựng từ cờ
        # `refused`. Ghép câu ấy vào `answer` ở đây là đặt một chuỗi tiếng Việt
        # vào chỗ mà máy đọc cờ, và là một chỗ thứ hai để wording trôi.
        answer=ket_qua.cau_tra_loi,
        # Suy từ **một** trường, không từ hai. `KetQuaHoiDap` đã cấm ca "có cả
        # câu trả lời lẫn lý do" ngay lúc dựng, nên không có ca `answer` khác
        # `None` mà `refused` là `True`.
        refused=tu_choi,
        citations=citations,
        graph=graph_rong(),
        meta=dung_meta(ngu_canh),
    )


__all__ = [
    "CT_GRANT_IDS",
    "CT_LY_DO",
    "CT_MA",
    "CT_MILI_GIAY",
    "MA_AUDIT_GHI_HONG",
    "MA_DANH_SACH_ID_QUA_DAI",
    "SO_ID_TOI_DA",
    "THONG_DIEP_THAN_DO_THI",
    "THOI_HAN_BIEN_DOI",
    "DAI_CAU_HOI_TOI_DA",
    "DANH_MUC_LY_DO",
    "KHOA_ENVELOPE",
    "KHOA_GRAPH",
    "KHOA_META",
    "LY_DO_CO_NO_ANSWER",
    "LY_DO_NGU_CANH_RONG",
    "LY_DO_TU_KHOA_RONG",
    "MA_CAU_HOI_QUA_DAI",
    "MA_CAU_HOI_RONG",
    "MA_DAU_RA_LLM_KHONG_DOC_DUOC",
    "MA_KHO_KHONG_SAN_SANG",
    "MA_LLM_LOI",
    "MA_LLM_QUA_HAN",
    "MA_NGU_CANH_KHONG_PHAI_VAI",
    "MA_THAN_YEU_CAU_LA",
    "MA_TRICH_DAN_NGOAI_QUYEN",
    "SO_LOI_GOI_EMBEDDING_MOI_TRUY_VAN",
    "SO_LOI_GOI_EMBEDDING_NEN",
    "SO_LOI_GOI_LLM_MOI_TRUY_VAN",
    "SO_LOI_GOI_LLM_NEN",
    "TEMPLATE_TU_CHOI",
    "LoiHoiDap",
    "ThanHoiDap",
    "dict_do_thi",
    "dict_trich_dan",
    "doc_grant_ids",
    "dung_envelope",
    "dung_meta",
    "graph_rong",
    "kiem_cau_hoi",
    "loi_truy_hoi",
    "mo_engine",
    "ngu_canh_cua_claim",
    "tra_loi",
    "tran_mot_truy_van_giay",
]
