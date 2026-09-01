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

from adapters.ingest_labels import IngestOutsideSystemContext, ingest_key_for_write
# Hợp đồng che dùng chung với hai adapter kia: một luật, một chỗ.
from adapters.mask_contract import kiem_ket_qua_che
from core.ids import validate_space
from core.keys import FILTER_KEY_FIELD
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
        # Dữ liệu trong bộ nhớ theo từng `space`, nạp lười lúc chạm tới lần
        # đầu. Upstream chốt một file duy nhất lúc `__post_init__` nên một thư
        # mục làm việc là một kho phẳng; ở đây `space` là thuộc tính của
        # request nên nó phải tính theo từng lời gọi (AD-12).
        self._kho: dict[str, dict] = {}
        # `space` có dữ liệu chưa ghi xuống đĩa. Ghi ở `index_done_callback`,
        # đúng ngữ nghĩa upstream (`storage.py:36`).
        self._ban: set[str] = set()

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
        """
        if context.bypass_filter:
            return None
        return context.keys_for(KV_PERMISSION_NAMESPACE)

    @staticmethod
    def _khong_thay_gi(khoa_duoc_phep) -> bool:
        """Tập khóa rỗng: mọi mục vắng mặt, và không chạm đĩa để biết điều đó.

        Nạp file rồi lọc ra hết cũng cho cùng kết quả, nhưng nó biến "không có
        quyền" thành một lần đọc kho bình thường. Nhánh đúng là không chạm.
        """
        return khoa_duoc_phep is not None and not khoa_duoc_phep

    @staticmethod
    def _khoa_cua(id: str, ban_ghi: dict) -> str:
        """Khóa quyền của một bản ghi; vắng là hỏng dữ liệu, không phải "không che"."""
        khoa = ban_ghi.get(FILTER_KEY_FIELD)
        if not khoa:
            raise RecordFilterKeyMissing(
                f"bản ghi {id!r} không mang {FILTER_KEY_FIELD!r}: không biết"
                " vai nào được đọc nó, và không tra được `masked_slots` nên"
                " cũng không che được"
            )
        return khoa

    def _ton_tai(self, du_lieu: dict, id: str, khoa_duoc_phep) -> bool:
        """Mục này có tồn tại *với lời gọi hiện tại* không.

        Đây là chỗ luật vắng mặt im lặng lan sang `all_keys` và `filter_keys`:
        một mục ngoài quyền trả lời "không tồn tại", cùng câu trả lời với một
        id chưa từng được nạp. Trả lời trung thực "đã có trong kho" là kể ra
        rằng fact đó tồn tại.
        """
        ban_ghi = du_lieu.get(id)
        if ban_ghi is None:
            return False
        if khoa_duoc_phep is None:
            return True
        return self._khoa_cua(id, ban_ghi) in khoa_duoc_phep

    def _tra(self, du_lieu: dict, id: str, context, khoa_duoc_phep) -> dict | None:
        """Cửa duy nhất trả nội dung ra ngoài: lọc rồi che (AD-9).

        Gom vào một chỗ để không method đọc nào quên gọi tầng che. Ngữ cảnh hệ
        thống đọc thô nên không che; mọi ca còn lại đều đi qua `mask` với khóa
        của chính bản ghi đó, không phải khóa của một mục nào khác.

        Bản sao nông là đủ cho thứ nó bảo vệ: khóa quyền nằm ở tầng ngoài cùng
        của bản ghi, nên nơi gọi không đổi được nhãn quyền trong kho. Giá trị
        lồng bên trong là nội dung của chính bản ghi, thứ nơi gọi được phép
        tiêu thụ.
        """
        ban_ghi = du_lieu.get(id)
        if ban_ghi is None:
            return None
        ban_ghi = dict(ban_ghi)
        if khoa_duoc_phep is None:
            return ban_ghi
        khoa = self._khoa_cua(id, ban_ghi)
        if khoa not in khoa_duoc_phep:
            return None
        return kiem_ket_qua_che(mask(ban_ghi, context, khoa), ban_ghi, f"mục {id!r}")

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
        return self._tra(self._du_lieu(context.space), id, context, khoa_duoc_phep)

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
        ket_qua = [self._tra(du_lieu, id, context, khoa_duoc_phep) for id in ids]
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
        return [id for id in du_lieu if self._ton_tai(du_lieu, id, khoa_duoc_phep)]

    async def filter_keys(self, data: list[str]) -> set[str]:
        """Tập id *chưa* tồn tại, đúng ngữ nghĩa upstream (`storage.py:54`).

        Mục ngoài quyền tính là chưa tồn tại. Trả lời khác đi thì một vai hẹp
        quyền hỏi được kho "id này có chưa" và nhận câu trả lời trung thực về
        một tài liệu nó không được đọc.
        """
        context = current_context()
        khoa_duoc_phep = self._khoa_duoc_phep(context)
        if self._khong_thay_gi(khoa_duoc_phep):
            return set(data)
        du_lieu = self._du_lieu(context.space)
        return {id for id in data if not self._ton_tai(du_lieu, id, khoa_duoc_phep)}

    # --- Ghi ---------------------------------------------------------------

    async def upsert(self, data: dict[str, dict]) -> dict[str, dict]:
        """Chèn các khóa mới, mỗi bản ghi mang khóa của phạm vi nhãn đang mở.

        Hai cửa phải qua trước khi chạm kho: có ngữ cảnh (để biết `space`) và
        có nhãn ingest dưới ngữ cảnh hệ thống (để biết khóa). Cả hai kiểm
        trước khi ghi bản ghi đầu tiên, nên hỏng cửa nào cũng là từ chối cả lô.

        Nhãn ingest ghi **sau** nội dung của người gọi, nên một `filter_key`
        nhét sẵn trong dict đầu vào bị đè chứ không thắng: đường ghi là chỗ duy
        nhất đặt khóa quyền, và dữ liệu tự khai quyền cho mình là đúng thứ toàn
        bộ tầng này dựng ra để chống.

        Giữ ngữ nghĩa upstream: chỉ khóa *mới* được chèn, phần đã có giữ
        nguyên, và trả về đúng phần vừa chèn. Trả bản sao chứ không trả chính
        các dict đang nằm trong kho - nơi gọi sửa `ket_qua[id]["filter_key"]`
        mà đổi được nhãn quyền trong kho là một đường fail-open im lặng.
        """
        if not data:
            return {}
        context = current_context()
        khoa = ingest_key_for_write()
        du_lieu = self._du_lieu(context.space)
        moi = {
            id: {**deepcopy(ban_ghi), FILTER_KEY_FIELD: khoa}
            for id, ban_ghi in data.items()
            if id not in du_lieu
        }
        if moi:
            du_lieu.update(moi)
            self._ban.add(context.space)
        return deepcopy(moi)

    async def drop(self) -> None:
        """Xóa sạch kho của một `space`, chỉ pipeline ingest gọi được.

        Upstream chỉ gán `_data = {}` và không kiểm gì (`storage.py:62`), nhưng
        đây là đường ghi phá hủy và `space` lấy theo ngữ cảnh, nên nó đi cùng
        luật với `upsert`: chạy dưới ngữ cảnh vai người dùng nghĩa là chính
        người hỏi xóa được kho của không gian mình đang đọc.

        Không phải đường xóa theo `space` mà pipeline Epic 2 cần - khoản đó là
        nợ có địa chỉ, không mở ở đây.
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
