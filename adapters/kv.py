"""Adapter KV: điểm chèn quyền của cổng đọc chunk (AD-18, FR-05, NFR-06).

Hai đường truy hồi kia có điểm chèn quyền từ story 1.3 và 1.4, nhưng lúc trả
lời upstream không hỏi collection `chunks` một lần nào. Nó đọc `source_id` của
entity và hyperedge rồi gọi thẳng `text_chunks_db.get_by_id(c_id)`
(`operate.py:843`, `:1073`), lắp nguyên văn chunk vào ngữ cảnh gửi cho LLM. Một
vai chỉ đạt L1 với một loại nội dung vẫn thấy hyperedge của nó, mà thấy
hyperedge là đọc được `source_id`, và `source_id` đủ để dựng lời gọi lấy chunk.
Không có file này thì luật chunk-chỉ-L2 bị né hoàn toàn.

Hợp đồng với upstream giữ nguyên - 6 method của `BaseKVStorage`, file JSON
trong thư mục làm việc - nên `vendor/` không phải sửa một dòng nào. Phần quyền
nằm ở hai chỗ, cùng khuôn với hai adapter kia:

- lúc `upsert`, khóa `{scope}:{content_type}` lấy từ phạm vi nhãn ingest đang
  mở (`adapters/ingest_labels.py`) và ghi vào chính bản ghi;
- lúc đọc, tập khóa lấy từ `context.keys_for("chunks")` và mục nào không mang
  khóa trong tập đó thì **vắng mặt im lặng**.

Vắng mặt im lặng, không phải mã lỗi: `get_by_id` trả `None` là ngôn ngữ mà
upstream đã hiểu, cả hai chỗ tiêu thụ đều lọc `None` ra trước khi dựng ngữ
cảnh. Luật đó áp cả cho `filter_keys` (mục ngoài quyền tính là *chưa tồn tại*)
và `all_keys` (chỉ id trong quyền): hai method này không trả nội dung nên
không che, nhưng chúng vẫn trả lời câu hỏi "có tồn tại không", và đó cũng là rò.

`text_chunks` và `full_docs` dùng chung một ngưỡng. Chunk và tài liệu gốc là
văn bản chạy, không tách theo slot được, nên không có mức trung gian để che -
đúng lý do NFR-06 đặt chúng ở L2. Nguyên văn tài liệu nhạy cảm ít nhất phải
ngang chunk cắt ra từ nó, và một luật cho cả hai giữ cho không có hai cách
tính quyền cho cùng một loại nội dung.

**Sự kiện lọc** (story 3.6, AD-16, ADR-017). Đây là tầng post-filter duy nhất
của hệ, nên nó là chỗ duy nhất có con số "bao nhiêu mục bị loại". Hàng `filter`
tầng observation đi qua port `audit` (tiêm bằng keyword lúc dựng, `None` là
không phát), `chi_tiet` mang namespace và số đếm theo mức (`adapters.
cua_khoa_doc.muc_bi_loai`), `hyperedge_ids` rỗng, không id chunk, không nội
dung. **Gom theo lượt**: vendor xin chunk từng cái (`get_by_id` ở
`operate.py:843,1073`), nên khi ngữ cảnh mang `request_id` adapter chỉ **cộng
dồn** số bị loại vào một sổ trong bộ nhớ khóa theo id lượt, và `EngineACL.
hoi_dap` gọi `xa_loc(request_id)` sau khi lấy xong ngữ cảnh để phát **đúng một
hàng mỗi namespace** có mục bị loại - hàng chục INSERT tuần tự cho một lượt, mỗi
INSERT chờ tới `THOI_HAN_QUAN_SAT` khi Postgres treo, là thứ luật này chặn.
Ngữ cảnh không mang `request_id` (đường `aquery` của `eval/`, bộ test adapter
lẻ) thì phát ngay mỗi lời gọi để không mất số. Sổ của một lượt hỏng giữa chừng
bị bỏ (`bo_so_loc`) chứ không nằm lại. Nhánh "không thấy gì" (tập khóa rỗng)
không chạm kho nên không biết mục có tồn tại hay không, và vì thế không đếm -
đếm ở đó là bịa một con số. Không một số đếm nào về lọc đi vào kết quả trả về
(AD-8).

Cache LLM thì không có adapter: khóa cache của upstream là `(mode, câu hỏi)` và
không có vai (`utils.py:106`), nên hai vai hỏi cùng một câu dùng chung một ô.
Đó là quyết định cam kết của AD-18 chứ không phải một mặc định đổi được bằng
một cờ, nên dựng adapter cho namespace `llm_response_cache` là lỗi.

**I/O đồng bộ trong method async, có chủ đích ở M1.** `read_text`/`json.dump`
chặn vòng lặp sự kiện, đi ngược luật async toàn tuyến mà hai adapter kia giữ
bằng driver async. Chấp nhận ở đây vì kho KV của upstream vốn là một file JSON
nạp trọn vào bộ nhớ (`storage.py:28-30`), và corpus khóa luận là 40 tài liệu
nên cả file nằm dưới ngưỡng mà một lần đọc đồng bộ thành vấn đề. Đổi sang
aiofiles hay chuyển kho sang Postgres là một quyết định riêng, không phải một
chỗ bị quên: spine chốt KV nằm ở file JSON trong thư mục làm việc.
"""

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from hypergraphrag.base import BaseKVStorage

from adapters.cua_khoa_doc import khoa_doc, muc_bi_loai
from adapters.doi_chieu import ghi_vao_so, ten_kho_kv, ten_kho_vector
from adapters.ingest_labels import (
    IngestLabelMissing,
    IngestOutsideSystemContext,
    bat_buoc_ngu_canh_he_thong,
    current_ingest_key,
    ingest_keys_for_write,
)
# Hợp đồng che dùng chung với hai adapter kia: một luật, một chỗ.
from adapters.mask_contract import kiem_ket_qua_che
from adapters.sensitivity_loader import bang_hang_cho
from core.audit import (
    CT_REQUEST_ID,
    EVENT_FILTER,
    TIER_OBSERVATION,
    AuditPort,
    SuKienAudit,
    ghi_quan_sat,
    thoi_diem_utc,
)
from core.ids import normalize_id, validate_space
from core.keys import CHUA_GHI, FILTER_KEY_FIELD, hop_nhat_khoa
from core.masking import mask
from core.permission import current_context

# Khóa cấu hình đọc từ `global_config` (upstream truyền `asdict(HyperGraphRAG)`).
WORKING_DIR_KEY = "working_dir"

# Namespace cache LLM của upstream. Adapter từ chối được dựng cho nó.
LLM_CACHE_NAMESPACE = "llm_response_cache"

# Hằng cấu hình cho bước dựng engine ở story 1.7. Lớp thứ nhất của việc tắt
# cache; lớp thứ hai là `LLMCacheDisabled` ngay dưới đây. Hai lớp vì một cờ
# quên đặt phải nổ chứ không phải im lặng chạy cache qua adapter của mình.
ENABLE_LLM_CACHE: bool = False

# Danh mục **đóng** các namespace mà adapter này phục vụ, đúng tên upstream
# dựng chúng (`hypergraphrag.py:208,213`). Danh sách cho phép chứ không phải
# danh sách cấm: một namespace lạ sẽ lặng lẽ mượn ngưỡng của `chunks` mà không
# ai từng quyết định điều đó, và nó còn đi thẳng vào tên file kho - `..` trong
# namespace là một đường thoát khỏi thư mục làm việc. Cấm từng cái xấu là đuổi
# theo vô hạn; cho phép đúng hai cái đã biết thì đóng cả hai lỗ bằng một luật.
KV_NAMESPACES: tuple[str, ...] = ("text_chunks", "full_docs")

# Đường KV hỏi tập khóa của namespace `chunks`: ngưỡng L2 (NFR-06). Không phải
# `hyperedges` - tập đó là ngưỡng L1 của đường graph, và dùng nhầm nó chính là
# lỗ mà file này bịt. Adapter không tự suy mức và không đọc bảng chính sách.
KV_PERMISSION_NAMESPACE = "chunks"

# Đuôi file tạm của bước ghi nguyên tử. Nằm cạnh file thật để `os.replace` là
# một phép đổi tên trong cùng hệ thống file.
DUOI_TAM = ".dang-ghi"

# Hai khóa `chi_tiet` của sự kiện `filter`. Hằng vì `eval/` và harness Đo 3 đọc
# đúng tên này bằng SQL trên cột jsonb.
CT_NAMESPACE: str = "namespace"
CT_BI_LOAI: str = "bi_loai"


class LLMCacheDisabled(RuntimeError):
    """Dựng kho KV cho namespace cache LLM của upstream.

    `code` là mã lỗi ổn định để test assert trên `code`, không trên thông điệp
    (AD-8, Consistency Conventions).
    """

    code = "LLM_CACHE_DISABLED"


class KVNamespaceInvalid(ValueError):
    """Dựng kho KV cho một namespace ngoài danh mục đóng.

    Hai hậu quả nếu để lọt, nên nó là lỗi chứ không phải một mặc định: namespace
    lạ mượn ngưỡng quyền của `chunks` mà không ai quyết định, và nó đi thẳng
    vào tên file kho nên `../` thoát được khỏi thư mục làm việc.
    """

    code = "KV_NAMESPACE_INVALID"


class KVStoreCorrupt(RuntimeError):
    """File kho không đọc được thành một bảng bản ghi.

    JSON hỏng, gốc không phải object, hay một bản ghi không phải object đều cho
    lỗi thô (`JSONDecodeError`, `AttributeError`) ở một chỗ nào đó sâu trong
    `vendor/`, xa nguyên nhân vài tầng. Đổi thành một mã lỗi của dự án ngay tại
    cửa nạp, nơi còn biết file nào hỏng.
    """

    code = "KV_STORE_CORRUPT"


class RecordFilterKeyMissing(RuntimeError):
    """Một bản ghi rời kho mà không mang khóa quyền.

    Chỉ xảy ra khi có ai đó ghi vào file này không qua adapter, nên đây là hỏng
    dữ liệu chứ không phải ca vận hành bình thường. Vẫn phải nổ: che một mục
    bằng khóa rỗng nghĩa là không che gì, đúng kiểu mặc định fail-open mà cả
    epic này dựng ra để chống. Cùng luật với `PointFilterKeyMissing` của đường
    vector.

    Tên và mã nói "bản ghi" chứ không nói "chunk": cùng một lớp lỗi phục vụ cả
    `text_chunks` lẫn `full_docs`, và mã lỗi là hợp đồng mà test assert lên
    (AD-8) nên nó phải đúng cho cả hai namespace.
    """

    code = "RECORD_FILTER_KEY_MISSING"


@dataclass
class JsonACLKVStorage(BaseKVStorage):
    """`BaseKVStorage` của upstream, ruột là file JSON có lọc theo khóa quyền."""

    # Bước đối chiếu hai kho hỏi thuộc tính này (`adapters/doi_chieu.py`).
    # `False` vì ca hợp nhất ra "không khóa" giữ bản ghi lại với
    # `filter_key=null`, nên "vắng" ở đây đúng là chưa từng ghi. Không chú
    # kiểu: annotation sẽ biến nó thành field của dataclass.
    VANG_LA_MO_HO = False

    # Port audit cho sự kiện `filter` (story 3.6). Field có mặc định nên
    # `BaseKVStorage` của upstream dựng được như cũ; engine bind nó qua
    # `partial` ở `_get_storage_class`, cùng khuôn với `qdrant_client`.
    audit: AuditPort | None = None

    def __post_init__(self):
        if self.namespace == LLM_CACHE_NAMESPACE:
            raise LLMCacheDisabled(
                f"không dựng kho cho namespace {LLM_CACHE_NAMESPACE!r}: khóa"
                " cache của upstream là (mode, câu hỏi) và không có vai, nên"
                " một câu trả lời sinh cho vai rộng quyền được phát lại nguyên"
                " văn cho vai hẹp hơn trước cả khi truy hồi chạy. Cache LLM tắt"
                f" hẳn theo AD-18; dựng engine với enable_llm_cache="
                f"{ENABLE_LLM_CACHE!r}"
            )
        if self.namespace not in KV_NAMESPACES:
            raise KVNamespaceInvalid(
                f"namespace {self.namespace!r} không có trong danh mục đóng"
                f" {list(KV_NAMESPACES)}: adapter này chỉ bọc hai kho KV ấy, và"
                " một namespace lạ vừa mượn ngưỡng quyền của"
                f" {KV_PERMISSION_NAMESPACE!r} vừa đi thẳng vào tên file kho"
            )
        cau_hinh = self.global_config or {}
        thu_muc = cau_hinh.get(WORKING_DIR_KEY)
        if not thu_muc:
            raise ValueError(
                f"thiếu {WORKING_DIR_KEY!r} trong global_config: adapter KV"
                " không biết ghi file kho vào đâu"
            )
        self._thu_muc = Path(thu_muc)
        # Bảng hạng độ nhạy, nạp lúc dựng adapter: cùng nguồn với hai adapter
        # kia, nên ba đường ghi không chạy trên hai bảng hạng khác nhau.
        self._bang_hang = bang_hang_cho(cau_hinh)
        # Dữ liệu trong bộ nhớ theo từng `space`, nạp lười lúc chạm tới lần
        # đầu. Upstream chốt một file duy nhất lúc `__post_init__` nên một thư
        # mục làm việc là một kho phẳng; ở đây `space` là thuộc tính của
        # request nên nó phải tính theo từng lời gọi (AD-12).
        self._kho: dict[str, dict] = {}
        # `space` có dữ liệu chưa ghi xuống đĩa. Ghi ở `index_done_callback`,
        # đúng ngữ nghĩa upstream (`storage.py:36`).
        self._ban: set[str] = set()
        # Sổ cộng dồn số mục bị loại theo lượt (story 3.6): `request_id` ->
        # mức -> số. Chỉ sống giữa lời gọi đọc đầu tiên và `xa_loc`/`bo_so_loc`
        # của cùng lượt.
        self._so_loc: dict[str, dict[str, int]] = {}

    # --- Kho theo `space` --------------------------------------------------

    def _duong_dan(self, space: str) -> Path:
        """`kv_store_{space}_{namespace}.json` trong thư mục làm việc.

        Gấp `space` vào tên file là thứ giữ cách ly không gian của AD-12 đúng
        ở cả ba kho. Không có nó thì khoang `synth` và khoang `real` (story
        2.11) dùng chung một file chunk. `validate_space` của `core/` đã bảo
        đảm chuỗi này viết được vào tên file mà không cần thoát ký tự;
        `namespace` an toàn nhờ danh mục đóng kiểm lúc dựng adapter.
        """
        return self._thu_muc / f"kv_store_{validate_space(space)}_{self.namespace}.json"

    def _du_lieu(self, space: str) -> dict:
        """Dữ liệu của một `space`, nạp từ đĩa đúng một lần cho mỗi instance.

        Kiểm hình dạng ngay tại cửa nạp, một lần cho cả kho: mọi đường đọc và
        ghi đều đi qua đây, nên một file hỏng cho cùng một mã lỗi dù nó được
        phát hiện từ `get_by_id` hay từ `upsert`.
        """
        if space not in self._kho:
            self._kho[space] = self._doc_file(self._duong_dan(space))
        return self._kho[space]

    @staticmethod
    def _doc_file(duong_dan: Path) -> dict:
        """Đọc một file kho thành bảng bản ghi, hoặc `KVStoreCorrupt`."""
        if not duong_dan.exists():
            return {}
        try:
            noi_dung = json.loads(duong_dan.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as loi:
            raise KVStoreCorrupt(
                f"file kho {duong_dan.name!r} không parse được: {loi}"
            ) from loi
        if not isinstance(noi_dung, dict):
            raise KVStoreCorrupt(
                f"file kho {duong_dan.name!r} có gốc là"
                f" {type(noi_dung).__name__}, phải là một bảng id -> bản ghi"
            )
        hong = [id for id, ban_ghi in noi_dung.items() if not isinstance(ban_ghi, dict)]
        if hong:
            raise KVStoreCorrupt(
                f"file kho {duong_dan.name!r}: bản ghi {sorted(hong)[:5]} không"
                " phải object, không tra được khóa quyền trên chúng"
            )
        return noi_dung

    # --- Tập khóa và luật vắng mặt im lặng ---------------------------------

    @staticmethod
    def _khoa_duoc_phep(context) -> frozenset[str] | None:
        """Tập khóa của lời gọi, hoặc `None` nghĩa là đọc thô.

        Ngữ cảnh hệ thống không mang `allowed_keys` và hỏi nó là lỗi lập
        trình, nên "đọc thô" phải là một giá trị riêng chứ không phải một tập
        rỗng: tập rỗng ở đây có nghĩa ngược hẳn - vai không thấy gì cả.

        Luật sống ở `adapters/cua_khoa_doc.py` (retro Epic 1 F5); hai method
        này giữ nguyên chữ ký vì đường đọc KV lọc từng bản ghi nên nó cần đúng
        hình dạng `frozenset | None`.
        """
        return khoa_doc(context, KV_PERMISSION_NAMESPACE).loc_theo

    @staticmethod
    def _khong_thay_gi(khoa_duoc_phep) -> bool:
        """Tập khóa rỗng: mọi mục vắng mặt, và không chạm đĩa để biết điều đó.

        Nạp file rồi lọc ra hết cũng cho cùng kết quả, nhưng nó biến "không có
        quyền" thành một lần đọc kho bình thường. Nhánh đúng là không chạm.

        Nhận *giá trị* chứ không nhận context, vì bốn điểm gọi đều đã có
        `khoa_duoc_phep` trong tay và hỏi lại context là hỏi hai lần một câu.
        """
        return khoa_duoc_phep is not None and not khoa_duoc_phep

    @staticmethod
    def _khoa_cua(id: str, ban_ghi: dict) -> str | None:
        """Khóa quyền của một bản ghi, hoặc `None` khi bản ghi là "không khóa".

        Hai ca trông giống nhau mà nghĩa ngược nhau, nên chúng được phân biệt
        bằng chính sự có mặt của trường:

        - trường **vắng** (hoặc rỗng) là hỏng dữ liệu: chỉ xảy ra khi có ai đó
          ghi vào file này không qua adapter, và che một mục bằng khóa rỗng
          nghĩa là không che gì;
        - trường có mặt mang `null` là kết quả hợp nhất khóa đa nguồn khác
          scope (story 2.1): bản ghi ở lại kho, vô hình với mọi vai, đọc thô
          được dưới cờ system.
        """
        if FILTER_KEY_FIELD not in ban_ghi:
            raise RecordFilterKeyMissing(
                f"bản ghi {id!r} không mang {FILTER_KEY_FIELD!r}: không biết"
                " vai nào được đọc nó, và không tra được `masked_slots` nên"
                " cũng không che được"
            )
        khoa = ban_ghi[FILTER_KEY_FIELD]
        if khoa is not None and not khoa:
            raise RecordFilterKeyMissing(
                f"bản ghi {id!r} mang {FILTER_KEY_FIELD!r} rỗng: 'không khóa'"
                f" là {FILTER_KEY_FIELD}=null, không phải chuỗi rỗng"
            )
        return khoa

    def _ton_tai(self, du_lieu: dict, id: str, khoa_duoc_phep, context, bi_loai=None) -> bool:
        """Mục này có tồn tại *với lời gọi hiện tại* không.

        Đây là chỗ luật vắng mặt im lặng lan sang `all_keys` và `filter_keys`:
        một mục ngoài quyền trả lời "không tồn tại", cùng câu trả lời với một
        id chưa từng được nạp. Trả lời trung thực "đã có trong kho" là kể ra
        rằng fact đó tồn tại.

        Bản ghi "không khóa" vô hình với **mọi** vai, không phải với riêng vai
        nào: nó là mục mà không khóa nào đúng cho nó, nên không tập khóa nào
        chứa được nó. Fail-closed, và không cần một nhánh riêng - `None` không
        nằm trong bất kỳ tập khóa nào.
        """
        ban_ghi = du_lieu.get(id)
        if ban_ghi is None:
            return False
        if khoa_duoc_phep is None:
            return True
        khoa = self._khoa_cua(id, ban_ghi)
        if khoa in khoa_duoc_phep:
            return True
        self._dem_bi_loai(bi_loai, context, khoa)
        return False

    def _tra(self, du_lieu: dict, id: str, context, khoa_duoc_phep, bi_loai=None) -> dict | None:
        """Cửa duy nhất trả nội dung ra ngoài: lọc rồi che (AD-9).

        Gom vào một chỗ để không method đọc nào quên gọi tầng che. Ngữ cảnh hệ
        thống đọc thô nên không che; mọi ca còn lại đều đi qua `mask` với khóa
        của chính bản ghi đó, không phải khóa của một mục nào khác.

        Sao chép **sâu** trước khi che, và đây là đường duy nhất trong ba
        adapter cần nó: kho KV giữ bản gốc chưa che trong bộ nhớ dùng chung cho
        mọi vai, còn Qdrant và Neo4j dựng bản ghi mới từ từng dòng driver. Một
        tầng che biến đổi giá trị lồng nhau tại chỗ sẽ để dấu che của vai hẹp
        nằm lại trong kho, và vai rộng quyền đọc sau đó nhận bản đã bị che -
        sai theo chiều ngược, nhưng vẫn sai và vẫn im lặng. `core.masking.mask`
        là hàm thuần nên hôm nay chuyện đó không xảy ra; bản sao sâu là lớp thứ
        hai, đứng độc lập với việc ai viết ruột che.

        Bản sao cũng chặn nơi gọi sửa nhãn quyền của bản ghi trong kho.
        """
        trong_kho = du_lieu.get(id)
        if trong_kho is None:
            return None
        if khoa_duoc_phep is None:
            return deepcopy(trong_kho)
        khoa = self._khoa_cua(id, trong_kho)
        # Bản ghi "không khóa" (`khoa is None`) rơi vào đúng nhánh này mà không
        # cần một điều kiện riêng: `None` không nằm trong tập khóa nào, nên nó
        # vắng mặt với mọi vai. Fail-closed bằng chính luật đã có.
        if khoa not in khoa_duoc_phep:
            # Điểm đếm chính xác duy nhất toàn hệ của một mục bị loại (3.6).
            self._dem_bi_loai(bi_loai, context, khoa)
            return None
        # Sao chép sau cửa quyền, không trước: bản ghi mà lời gọi này không được
        # đọc thì không đáng một lần sao chép rồi vứt.
        ban_ghi = deepcopy(trong_kho)
        return kiem_ket_qua_che(mask(ban_ghi, context, khoa), ban_ghi, f"mục {id!r}")

    # --- Sự kiện lọc (story 3.6) -------------------------------------------

    @staticmethod
    def _dem_bi_loai(bi_loai, context, khoa) -> None:
        """Cộng một mục bị loại vào mức của vai với mục đó; `bi_loai=None` là không đếm."""
        if bi_loai is None:
            return
        muc = muc_bi_loai(context, khoa)
        bi_loai[muc] = bi_loai.get(muc, 0) + 1

    async def _phat_loc(self, context, bi_loai: dict) -> None:
        """Số bị loại của lời gọi vừa xong: cộng vào sổ của lượt, hoặc phát ngay.

        Chỉ làm gì khi tổng > 0 và có port: một lời gọi không loại gì không đáng
        một hàng, và "không port" (bộ test adapter lẻ, đường nạp) là không phát
        chứ không lỗi. Ngữ cảnh hệ thống không bao giờ tới đây vì nó không loại
        gì (`khoa_duoc_phep is None` đi thẳng ở cả hai cửa trên). Ngữ cảnh mang
        `request_id` thì gom vào sổ, `xa_loc` phát một hàng cho cả lượt; không
        mang thì phát ngay.
        """
        if self.audit is None or not bi_loai:
            return
        if context.request_id is not None:
            so = self._so_loc.setdefault(context.request_id, {})
            for muc, n in bi_loai.items():
                so[muc] = so.get(muc, 0) + n
            return
        await self._ghi_loc(context, bi_loai)

    async def xa_loc(self, request_id: str) -> None:
        """Phát **một** hàng `filter` cho lượt `request_id` rồi xóa sổ của nó.

        Gọi dưới chính ngữ cảnh vai của lượt (hàng mang `act`/`role`/`space` của
        ngữ cảnh hiện tại). Lượt không loại gì thì không hàng nào.
        """
        bi_loai = self._so_loc.pop(request_id, None)
        if bi_loai:
            await self._ghi_loc(current_context(), bi_loai)

    def bo_so_loc(self, request_id: str) -> None:
        """Bỏ sổ của một lượt hỏng giữa chừng, không phát gì."""
        self._so_loc.pop(request_id, None)

    async def _ghi_loc(self, context, bi_loai: dict) -> None:
        """Một hàng `filter` observation. `ghi_quan_sat` nuốt lỗi port thành WARNING."""
        await ghi_quan_sat(
            self.audit,
            SuKienAudit(
                tier=TIER_OBSERVATION,
                event=EVENT_FILTER,
                space=context.space,
                policy_version=context.policy_version,
                thoi_diem=thoi_diem_utc(),
                act=context.real_account,
                role=context.role,
                hyperedge_ids=(),
                chi_tiet={
                    CT_NAMESPACE: self.namespace,
                    CT_BI_LOAI: dict(sorted(bi_loai.items())),
                    CT_REQUEST_ID: context.request_id,
                },
            ),
        )

    # --- Đọc ---------------------------------------------------------------

    async def get_by_id(self, id):
        """Một mục, hoặc `None` khi không tồn tại *hoặc* ngoài quyền.

        Hai ca cho cùng một câu trả lời là cố ý: phân biệt được chúng từ ngoài
        là trả lời câu hỏi "fact này có tồn tại không" cho người không được
        đọc nó.
        """
        context = current_context()
        khoa_duoc_phep = self._khoa_duoc_phep(context)
        if self._khong_thay_gi(khoa_duoc_phep):
            return None
        bi_loai: dict[str, int] = {}
        ket_qua = self._tra(self._du_lieu(context.space), id, context, khoa_duoc_phep, bi_loai)
        await self._phat_loc(context, bi_loai)
        return ket_qua

    async def get_by_ids(self, ids, fields=None):
        """List cùng độ dài đầu vào, `None` đúng vị trí của mục vắng mặt.

        Hợp đồng upstream là độ dài giữ nguyên (`storage.py:42`), nên mục ngoài
        quyền không được rơi ra khỏi list mà phải thành `None` tại chỗ của nó.

        Chiếu `fields` sau khi đã lọc và che, không trước: chiếu trước là một
        đường đọc thứ hai đi vòng qua tầng che.
        """
        context = current_context()
        khoa_duoc_phep = self._khoa_duoc_phep(context)
        if self._khong_thay_gi(khoa_duoc_phep):
            return [None for _ in ids]
        du_lieu = self._du_lieu(context.space)
        bi_loai: dict[str, int] = {}
        ket_qua = [self._tra(du_lieu, id, context, khoa_duoc_phep, bi_loai) for id in ids]
        await self._phat_loc(context, bi_loai)
        if fields is None:
            return ket_qua
        return [
            None if ban_ghi is None else {k: v for k, v in ban_ghi.items() if k in fields}
            for ban_ghi in ket_qua
        ]

    async def all_keys(self) -> list[str]:
        """Id các mục mà lời gọi hiện tại đọc được, giữ thứ tự nạp."""
        context = current_context()
        khoa_duoc_phep = self._khoa_duoc_phep(context)
        if self._khong_thay_gi(khoa_duoc_phep):
            return []
        du_lieu = self._du_lieu(context.space)
        bi_loai: dict[str, int] = {}
        ket_qua = [id for id in du_lieu if self._ton_tai(du_lieu, id, khoa_duoc_phep, context, bi_loai)]
        await self._phat_loc(context, bi_loai)
        return ket_qua

    async def filter_keys(self, data: list[str]) -> set[str]:
        """Tập id *chưa* tồn tại, đúng ngữ nghĩa upstream (`storage.py:54`).

        Mục ngoài quyền tính là chưa tồn tại. Trả lời khác đi thì một vai hẹp
        quyền hỏi được kho "id này có chưa" và nhận câu trả lời trung thực về
        một tài liệu nó không được đọc.

        **Dưới nhãn ingest** (ngữ cảnh hệ thống và có phạm vi nhãn đang mở) thì
        thêm một nhánh, và đó là chỗ story 2.3 đóng lỗ `ainsert` né luật hợp
        nhất ở đường chunk: `hypergraphrag.py:309-313` gọi `filter_keys` rồi
        *loại* id đã có khỏi lô trước khi `upsert` nhìn thấy, nên chunk trùng
        id giữa hai tài liệu khác quyền không bao giờ tới được cửa hợp nhất.
        Nay một id đã có mà khóa **sẽ đổi** sau hợp nhất với nhãn đang mở được
        báo là "chưa có", để `ainsert` đưa nó qua `upsert` (nơi nội dung giữ
        nguyên, chỉ khóa được hợp nhất). Id đã có và khóa không đổi vẫn báo "đã
        có", giữ đúng ngữ nghĩa chỉ-chèn của upstream cho nội dung.

        Ngoài nhãn ingest (đọc thô không nạp gì, bộ test adapter lẻ) giữ hành
        vi cũ: `IngestLabelMissing` là "không có nhãn", không phải lỗi ở đây.
        """
        context = current_context()
        khoa_duoc_phep = self._khoa_duoc_phep(context)
        if self._khong_thay_gi(khoa_duoc_phep):
            return set(data)
        du_lieu = self._du_lieu(context.space)
        bi_loai: dict[str, int] = {}
        chua_co = {id for id in data if not self._ton_tai(du_lieu, id, khoa_duoc_phep, context, bi_loai)}
        if khoa_duoc_phep is not None:
            await self._phat_loc(context, bi_loai)
            return chua_co
        try:
            khoa_moi = current_ingest_key()
        except IngestLabelMissing:
            return chua_co
        hang = self._bang_hang.hang
        for id in data:
            if id in chua_co or id not in du_lieu:
                continue
            khoa_cu = self._khoa_cua(id, du_lieu[id])
            if hop_nhat_khoa(khoa_cu, khoa_moi, hang=hang) != khoa_cu:
                chua_co.add(id)
        return chua_co

    # --- Ghi ---------------------------------------------------------------

    async def khoa_hien_co(self, ids: list[str]) -> dict[str, object]:
        """Khóa quyền mà kho đang giữ cho từng id, không đọc gì khác.

        Bước đọc của read-merge-write (FR-11) và cửa mà bước đối chiếu hai kho
        hỏi. Chỉ trả trường khóa nên tầng che không áp dụng; chạy dưới cờ system
        vì bị lọc theo khóa của tài liệu đang nạp thì nó không bao giờ thấy khóa
        khác scope cần hợp nhất.

        Ba trạng thái, đúng ba trạng thái mà `core.keys.hop_nhat_khoa` phân
        biệt: `CHUA_GHI` (id chưa có trong kho), `KHONG_KHOA` (bản ghi ở lại mà
        không khóa nào đúng cho nó), hoặc một khóa thật.
        """
        bat_buoc_ngu_canh_he_thong("đọc khóa hiện có của kho KV")
        du_lieu = self._du_lieu(current_context().space)
        return {
            id: (
                CHUA_GHI
                if id not in du_lieu
                else self._khoa_cua(id, du_lieu[id])
            )
            for id in ids
        }

    async def upsert(self, data: dict[str, dict]) -> dict[str, dict]:
        """Chèn khóa mới; khóa của bản ghi đã có thì hợp nhất lại (FR-11).

        Hai cửa phải qua trước khi chạm kho: có ngữ cảnh (để biết `space`) và
        có nhãn ingest dưới ngữ cảnh hệ thống, với loại nội dung có hạng độ
        nhạy (để hợp nhất được). Cả hai kiểm trước khi ghi bản ghi đầu tiên,
        nên hỏng cửa nào cũng là từ chối cả lô.

        Nhãn ingest ghi **sau** nội dung của người gọi, nên một `filter_key`
        nhét sẵn trong dict đầu vào bị đè chứ không thắng: đường ghi là chỗ duy
        nhất đặt khóa quyền, và dữ liệu tự khai quyền cho mình là đúng thứ toàn
        bộ tầng này dựng ra để chống.

        Giữ ngữ nghĩa upstream cho **nội dung**: chỉ khóa mới được chèn, nội
        dung của bản ghi đã có giữ nguyên, và trả về đúng phần vừa chèn. Nhưng
        *khóa quyền* thì không đi theo ngữ nghĩa đó, và đây là chỗ story 2.1
        đổi: id chunk của upstream là md5 nội dung (`compute_mdhash_id`), không
        mang `scope`, nên hai tài liệu khác quyền có đoạn trùng nội dung sinh
        cùng một id - ngữ nghĩa chỉ-chèn khi đó giữ nhãn *rộng* của lần nạp đầu
        và lần nạp sau không siết lại được. Nay mọi id trong lô đều đi qua phép
        hợp nhất, kể cả id đã có.

        Trả bản sao chứ không trả chính các dict đang nằm trong kho - nơi gọi
        sửa `ket_qua[id]["filter_key"]` mà đổi được nhãn quyền trong kho là một
        đường fail-open im lặng.
        """
        if not data:
            return {}
        context = current_context()
        bat_buoc_ngu_canh_he_thong("ghi tri thức")
        du_lieu = self._du_lieu(context.space)
        khoa_theo_id = ingest_keys_for_write(
            await self.khoa_hien_co(list(data)), hang=self._bang_hang.hang
        )
        # Ghi sổ **ý định** trước khi chạm kho, cùng luật với hai adapter kia:
        # hỏng giữa chừng thì id phải nằm trong sổ mà khóa vắng ở kho, chứ
        # không vô hình với bước đối chiếu cuối đợt (NFR-03).
        for id in data:
            ghi_vao_so(
                id_join=self._id_join(id),
                kho=ten_kho_kv(self.namespace),
                id_trong_kho=id,
                kho_doi=self._kho_doi(),
            )
        moi = {}
        for id, ban_ghi in data.items():
            khoa = khoa_theo_id[id]
            if id in du_lieu:
                if du_lieu[id].get(FILTER_KEY_FIELD) != khoa:
                    du_lieu[id][FILTER_KEY_FIELD] = khoa
                    self._ban.add(context.space)
            else:
                moi[id] = {**deepcopy(ban_ghi), FILTER_KEY_FIELD: khoa}
        if moi:
            du_lieu.update(moi)
            self._ban.add(context.space)
        return deepcopy(moi)

    @staticmethod
    def _id_join(id: str) -> str:
        """Id dùng để nối một bản ghi KV với point vector tương ứng của nó.

        **Cùng một phép chuẩn hóa** với `QdrantVectorDBStorage._id_join`, và đó
        là điều kiện để phép so tồn tại: id chunk ở hai kho là cùng một chuỗi
        *sau khi chuẩn hóa*, nên hai bên chuẩn hóa khác nhau thì một id cần NFC
        (hay có khoảng trắng thừa, hay bọc nháy kép) tách thành hai id join
        mỗi bên một kho - và khi đó phép so biến mất im lặng.
        """
        return normalize_id(id)

    def _kho_doi(self) -> str | None:
        """Kho mà mọi id của namespace này *cũng* phải có mặt (NFR-03).

        `text_chunks` có bản sao vector ở collection `chunks`. `full_docs` thì
        không: tài liệu gốc không được nạp vào kho vector nào, nên khai một kho
        đôi cho nó là dựng ra một lệch giả ở mọi đợt.
        """
        if self.namespace == "text_chunks":
            return ten_kho_vector("chunks")
        return None

    async def xoa(self, ids: list[str]) -> list[str]:
        """Gỡ các bản ghi theo id khỏi kho của `space` hiện tại; trả phần đã gỡ.

        Đường xóa của re-ingest và xóa tài liệu (story 2.3): chunk không còn tài
        liệu nào dùng thì rời kho. Cùng cửa AD-3 với `upsert`; id không có
        trong kho bỏ qua chứ không nổ, vì "xóa cái đã vắng" là trạng thái đích
        đã đạt. Xuống đĩa ở `index_done_callback`, cùng nhịp với ghi.
        """
        bat_buoc_ngu_canh_he_thong("xóa bản ghi KV")
        if not ids:
            return []
        space = validate_space(current_context().space)
        du_lieu = self._du_lieu(space)
        da_xoa = [id for id in ids if id in du_lieu]
        for id in da_xoa:
            del du_lieu[id]
        if da_xoa:
            self._ban.add(space)
        return da_xoa

    async def xoa_tat_ca(self) -> None:
        """Xóa sạch kho của `space` hiện tại và gỡ file của nó khỏi đĩa.

        `drop` (bộ nhớ) rồi flush (để một tiến trình khác đang đọc file thấy
        kho rỗng chứ không thấy bản cũ) rồi unlink: sau đó file vắng mặt và lần
        nạp kế đọc `{}`. Đường xóa theo `space` mà `drop` từng ghi là nợ.
        """
        await self.drop()
        space = validate_space(current_context().space)
        await self.index_done_callback()
        self._duong_dan(space).unlink(missing_ok=True)
        self._kho.pop(space, None)

    async def drop(self) -> None:
        """Xóa sạch kho của một `space` trong bộ nhớ, chỉ pipeline ingest gọi được.

        Upstream chỉ gán `_data = {}` và không kiểm gì (`storage.py:62`), nhưng
        đây là đường ghi phá hủy và `space` lấy theo ngữ cảnh, nên nó đi cùng
        luật với `upsert`: chạy dưới ngữ cảnh vai người dùng nghĩa là chính
        người hỏi xóa được kho của không gian mình đang đọc. Đường xóa cả
        `space` kể cả file trên đĩa là `xoa_tat_ca`.
        """
        context = current_context()
        if not context.bypass_filter:
            raise IngestOutsideSystemContext(
                "xóa kho KV phải chạy dưới ngữ cảnh hệ thống của pipeline"
                " ingest (AD-3), không phải dưới ngữ cảnh vai người dùng"
            )
        space = validate_space(context.space)
        self._kho[space] = {}
        self._ban.add(space)

    async def index_done_callback(self) -> None:
        """Ghi mọi `space` đang bẩn xuống đĩa, đúng nhịp upstream đã có.

        Ghi ra file tạm rồi `os.replace`, không ghi đè thẳng. File này là nơi
        *duy nhất* giữ khóa quyền của chunk đã nạp, nên một lần ghi đứt giữa
        chừng không được để lại một kho cụt: `os.replace` là nguyên tử trong
        cùng một hệ thống file, nên hoặc file cũ còn nguyên, hoặc file mới đã
        đủ. File tạm bị dọn ở cả hai nhánh - sót lại một file `.dang-ghi` là
        một kho ma mà lần chạy sau không ai đọc và không ai xóa.

        Không hỏi ngữ cảnh: đây là method vòng đời, nó không đọc dữ liệu người
        dùng và upstream gọi nó ở chỗ không còn ngữ cảnh của một lời gọi nào
        (`hypergraphrag.py:_insert_done`).
        """
        for space in sorted(self._ban):
            duong_dan = self._duong_dan(space)
            duong_dan.parent.mkdir(parents=True, exist_ok=True)
            tam = duong_dan.with_name(duong_dan.name + DUOI_TAM)
            try:
                with tam.open("w", encoding="utf-8") as f:
                    json.dump(self._kho[space], f, indent=2, ensure_ascii=False)
                os.replace(tam, duong_dan)
            finally:
                tam.unlink(missing_ok=True)
        self._ban.clear()
