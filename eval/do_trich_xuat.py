"""Runner một vòng đo trích xuất: gọi LLM thật, lưu *fact thô* thành file có commit (story 2.6).

    uv run python -m eval.do_trich_xuat --vong v1-deepseek --model deepseek-v4-flash

Đây là file **tốn tiền thật** của story 2.6; phép chấm
(`eval/cham_trich_xuat.py`), phép ngoại suy (`eval/ngoai_suy.py`) và trang báo
cáo (`eval/xem_do_trich_xuat.py`) đều là hàm thuần đọc file mà nó ghi ra.

Vì sao lưu phản hồi thô chứ không lưu điểm: luật ghép còn phải sửa vài lần
(story 2.8, Epic 7). File chỉ giữ điểm thì mỗi lần sửa luật là một lần trả tiền
lại cho đúng câu trả lời cũ của LLM. File giữ nguyên văn phản hồi từng chunk
nên `doc_ket_qua()` dựng lại được cả fact hợp lệ lẫn mã loại bằng chính
`core.facts.phan_tich_phan_hoi` - đổi lược đồ fact là render lại, không phải
chạy lại.

Ba thứ nữa nằm trong file để một vòng đọc được mà không cần tra git: **nguyên
văn prompt** đã dùng (prompt là biến đang được chỉnh, nên một vòng không ghi
prompt là một con số không truy được về nguyên nhân), tham số LLM, và tham số
chia chunk. Cộng token/USD từng lời gọi lấy *qua wrapper* (`adapters/
llm_wrapper.bo_llm` ghi sự kiện chi phí), không tự đếm bằng tiktoken.

Chỉ chạy trên tài liệu **chấm** của bộ vàng (hiện là 8 trong 10 tài liệu lõi;
số đó đọc từ `BoVang.tai_lieu_cham()`, không chép cứng ở đâu): hai tài liệu
few-shot nằm trong ví dụ của prompt nên chạy chúng vừa tốn tiền vừa không có
chỗ nào dùng số.

**File kết quả chép nguyên văn thân tài liệu** vào JSON có commit, để một vòng
đọc lại được mà không cần tra thư mục dữ liệu. Với `eval/data` (dữ liệu dựng
tay) thì không sao; trỏ runner vào một bộ vàng dựng từ tài liệu công ty rồi
commit là đưa thẳng thân tài liệu vào lịch sử git. Bộ vàng của space `real`
phải là bản đã khử (NFR-05), và file vòng đo của nó không được commit.

Ngữ cảnh quyền là ngữ cảnh **người dùng thường** (`core.permission.user_context`),
không phải ngữ cảnh hệ thống: harness không chạm kho nào, và danh sách trắng
import-lint của `core.system_context` chỉ có pipeline ingest.
"""

import argparse
import asyncio
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from adapters.chunking import TRUONG_CHUNK, cau_hinh_chunk, chia_chunk, dem_token
from adapters.llm_wrapper import (
    CT_CHI_PHI_USD,
    CT_TOKEN_RA,
    CT_TOKEN_VAO,
    bo_llm,
    nha_cung_cap_tu_moi_truong,
)
from adapters.llm_wrapper import ProviderConfigMissing  # noqa: F401 - dùng ở `main`
from adapters.model_catalog import LOAI_LLM, ModelUnknown, danh_muc_mac_dinh
from adapters.policy_loader import load_policy
from adapters.thu_lai import (  # noqa: F401 - re-export: hợp đồng của test 2.8
    LOI_MANG_TAM_THOI,
    MA_RATE_LIMIT,
    SO_LAN_THU,
    TEN_TRUONG_MA_HTTP,
    TRAN_CHO_GIAY,
    ChanNhipQuaLau,
    giay_cho_lai,
    goi_co_thu_lai,
    la_loi_mang_tam_thoi,
    ma_http_cua,
    nen_thu_lai,
)
from adapters.trich_xuat import (
    PROMPT_KHONG_TU_DIEN,
    PROMPT_TRICH_XUAT,
    THAM_SO_LLM,
    CHO_TU_DIEN,
    dung_prompt,
    khoi_tu_dien,
)
from adapters.tu_dien_thuc_the import TuDienThucThe, tai_tu_dien_thuc_the
from core.audit import SuKienAudit, kiem_thoi_diem, thoi_diem_utc
from core.facts import KetQuaPhanTich, id_fact, phan_tich_phan_hoi
from core.permission import use_context, user_context
from eval import nap_bien_tu_env
from eval.bo_vang import BoVangKhongHopLe, doc_bo_vang

REPO_ROOT = Path(__file__).resolve().parent.parent
THU_MUC_KET_QUA: Path = Path(__file__).resolve().parent / "ket_qua_do"
POLICY_MAC_DINH: Path = REPO_ROOT / "config" / "policy-toi-gian.yaml"

VERSION_KET_QUA: int = 1
DUOI_FILE: str = ".json"

# Cờ ghi đè, nêu tên trong thông điệp từ chối. Mặc định là *không* ghi đè: một
# file kết quả là tiền đã tiêu, mất nó là phải tiêu lại.
CO_GHI_DE: str = "--ghi-de"

# Tên vòng đi thẳng vào tên file, nên nó có luật hình dạng chứ không phải chuỗi
# tự do: `--vong ../x` ghi ra ngoài thư mục kết quả, `--vong ""` tạo một file
# tên `.json` mà `doc_ket_qua` không đọc lại được.
_TEN_VONG_HOP_LE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Thư mục cứu hộ: khi một lần chạy hỏng giữa chừng, phản hồi *đã trả tiền* của
# các tài liệu xong trước đó nằm ở đây thay vì bay mất. Đặt trong một thư mục
# con chứ không cạnh file kết quả, vì `doc_moi_vong` quét `*.json` không đệ quy:
# một file cứu hộ nằm cạnh sẽ làm cả trang báo cáo chết vì một lần chạy hỏng.
# Tên có mốc thời gian nên hai lần hỏng cùng tên vòng không đè lên nhau.
THU_MUC_CHUA_XONG: str = "chua-xong"

# Đuôi của bản lưu file kết quả cũ khi `--ghi-de` (story 2.8). `doc_moi_vong`
# **bỏ qua** đuôi này: một bản cũ nằm cạnh mà bị đọc như một vòng nữa thì trang
# báo cáo có hai cột mang cùng tên vòng, và không ai biết cột nào là bản mới.
DUOI_BAN_CU: str = ".bak" + DUOI_FILE

# Ước lượng token ra cho mỗi lời gọi, dùng ở `--uoc-tinh`. Không phải số đo:
# token ra chỉ biết được sau khi model trả lời. Giá trị lấy trần trên bốn vòng
# đã đo của story 2.6 (262-363 token ra mỗi chunk), làm tròn lên.
#
# Đừng đọc hằng này thành "ước tính luôn nói quá": chiều của *tổng* không bảo
# đảm, vì token **vào** lại đếm thiếu phần bọc hội thoại của provider khoảng
# 25-30%. Hai sai số ngược chiều nhau, nên `--uoc-tinh` cho một con số cùng bậc
# chứ không cho một trần chi - `dong_in()` nói thẳng điều đó ở đầu ra.
TOKEN_RA_UOC_MOI_CHUNK: int = 400

# Cờ dòng lệnh của bước ước tính; nêu tên trong thông điệp để người dùng biết
# đường xem trước trước khi tiêu tiền.
CO_UOC_TINH: str = "--uoc-tinh"

# Lược đồ đóng ba cấp. Khóa lạ bị từ chối cùng một lý do với bộ vàng 2.5: một
# khóa viết sai chính tả mà file vẫn nạp được nghĩa là một con số lặng lẽ sai.
KHOA_GOC: frozenset[str] = frozenset(
    {
        "version",
        "vong",
        "model",
        "nha_cung_cap",
        "thoi_diem",
        "danh_muc_version",
        "prompt",
        "tham_so_llm",
        "chunk",
        "tai_lieu",
    }
)
KHOA_TAI_LIEU: frozenset[str] = frozenset({"doc_key", "chunks"})
# Khóa **chỉ có trong file cứu hộ**: tài liệu đang chạy dở lúc vòng hỏng. Cố ý
# nằm ngoài `KHOA_TAI_LIEU`, nên `doc_ket_qua` từ chối một file cứu hộ bị đổi
# tên thành file kết quả - đó đúng là điều phải xảy ra, vì tài liệu đó thiếu
# chunk và mọi tổng tính trên nó đều sai.
KHOA_DANG_DO: str = "dang_do"
KHOA_CHUNK: frozenset[str] = frozenset(
    {"stt", "van_ban", "phan_hoi", "token_vao", "token_ra", "chi_phi_usd"}
)

# Cách chia chunk ghi vào file kết quả để một vòng chạy sau khi đổi kích thước
# chunk không bị so thẳng với vòng trước mà không ai thấy. Luật chia sống ở
# `adapters/chunking.py` (`TRUONG_CHUNK`, `cau_hinh_chunk`, `chia_chunk`):
# `eval/` chỉ import `core/` và `adapters/` theo chiều import của AGENTS.md, và
# hai bản cài đặt luật chia là hai chỗ để chúng lệch nhau.

VAI_MAC_DINH: str = "devops"
SPACE_MAC_DINH: str = "synth"
TAI_KHOAN: str = "eval-do-trich-xuat"


class KetQuaDoKhongHopLe(ValueError):
    """File kết quả vòng đo không đọc được thành một vòng hợp lệ."""

    code = "KET_QUA_DO_KHONG_HOP_LE"


class KetQuaDoDaCo(FileExistsError):
    """Tên vòng đã có file kết quả; ghi đè phải là một quyết định tường minh."""

    code = "KET_QUA_DO_DA_CO"


# ---------------------------------------------------------------------------
# Lược đồ file kết quả
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkDo:
    """Một lời gọi LLM: chunk vào, phản hồi nguyên văn ra, token và tiền của nó."""

    stt: int
    van_ban: str
    phan_hoi: str
    token_vao: int
    token_ra: int
    chi_phi_usd: float

    def phan_tich(self) -> KetQuaPhanTich:
        return phan_tich_phan_hoi(self.phan_hoi)


@dataclass(frozen=True)
class TaiLieuDo:
    doc_key: str
    chunks: tuple[ChunkDo, ...]


@dataclass(frozen=True)
class KetQuaVong:
    """Một vòng đo đã nạp; mọi con số dẫn xuất tính lại từ phản hồi thô."""

    vong: str
    model: str
    nha_cung_cap: str
    thoi_diem: str
    danh_muc_version: str
    prompt: str
    tham_so_llm: Mapping[str, object]
    chunk: Mapping[str, object]
    tai_lieu: tuple[TaiLieuDo, ...]
    version: int = VERSION_KET_QUA

    def __post_init__(self):
        object.__setattr__(self, "tham_so_llm", MappingProxyType(dict(self.tham_so_llm)))
        object.__setattr__(self, "chunk", MappingProxyType(dict(self.chunk)))

    def _moi_chunk(self):
        for t in self.tai_lieu:
            for c in t.chunks:
                yield c

    def facts_theo_tai_lieu(self) -> dict[str, list[dict[str, str]]]:
        """Fact hợp lệ của từng tài liệu, đọc lại từ phản hồi thô, đã gộp trùng.

        Gộp theo `id_fact` trong phạm vi một tài liệu, đúng như pipeline gộp:
        `adapters/trich_xuat.py` cho cùng một tập slot đúng *một* node hyperedge
        dù nó xuất hiện ở mấy chunk. Chunk có vùng chồng lấn 100 token, nên một
        fact nằm vắt qua ranh giới chunk bị LLM trả hai lần; không gộp thì bản
        thứ hai thành FP oan và precision của tài liệu dài tụt vì một chuyện
        không phải lỗi trích xuất.
        """
        ra: dict[str, list[dict[str, str]]] = {}
        for t in self.tai_lieu:
            da_thay: set[str] = set()
            gom: list[dict[str, str]] = []
            for c in t.chunks:
                for f in c.phan_tich().facts:
                    idf = id_fact(f)
                    if idf in da_thay:
                        continue
                    da_thay.add(idf)
                    gom.append(dict(f))
            ra[t.doc_key] = gom
        return ra

    def so_fact_trung_chunk(self) -> int:
        """Số bản ghi hợp lệ bị gộp vì trùng `id_fact` với một bản ghi trước đó."""
        tong = 0
        for t in self.tai_lieu:
            da_thay: set[str] = set()
            for c in t.chunks:
                for f in c.phan_tich().facts:
                    idf = id_fact(f)
                    tong += idf in da_thay
                    da_thay.add(idf)
        return tong

    def loai_theo_ma(self) -> dict[str, int]:
        dem: dict[str, int] = {}
        for c in self._moi_chunk():
            for ma, n in c.phan_tich().loai_theo_ma.items():
                dem[ma] = dem.get(ma, 0) + n
        return dict(sorted(dem.items()))

    def so_chunk(self) -> int:
        return sum(1 for _ in self._moi_chunk())

    def so_chunk_hong(self) -> int:
        return sum(1 for c in self._moi_chunk() if c.phan_tich().chunk_hong)

    def so_fact_tho(self) -> int:
        return sum(c.phan_tich().so_ban_ghi for c in self._moi_chunk())

    def so_hop_le(self) -> int:
        return sum(len(c.phan_tich().facts) for c in self._moi_chunk())

    def ty_le_loai(self) -> float | None:
        """Tỉ lệ bản ghi bị loại; `None` khi không có bản ghi thô nào.

        Trả 0.0 cho ca đó là nói dối theo chiều nguy hiểm nhất: một vòng mà mọi
        chunk đều hỏng sẽ đọc thành "0% bị loại", tức hoàn hảo.
        """
        tho = self.so_fact_tho()
        return (tho - self.so_hop_le()) / tho if tho else None

    def token_vao(self) -> int:
        return sum(c.token_vao for c in self._moi_chunk())

    def token_ra(self) -> int:
        return sum(c.token_ra for c in self._moi_chunk())

    def chi_phi_usd(self) -> float:
        return sum(c.chi_phi_usd for c in self._moi_chunk())


def doc_ket_qua(duong_dan: str | Path) -> KetQuaVong:
    """Nạp một file kết quả vòng; mọi cách hỏng là `KetQuaDoKhongHopLe`."""
    duong_dan = Path(duong_dan)
    try:
        raw = json.loads(duong_dan.read_text(encoding="utf-8"))
    except OSError as loi:
        raise KetQuaDoKhongHopLe(f"{duong_dan.name}: không đọc được ({loi})") from None
    except UnicodeDecodeError as loi:
        raise KetQuaDoKhongHopLe(f"{duong_dan.name}: không phải UTF-8 ({loi})") from None
    except json.JSONDecodeError as loi:
        raise KetQuaDoKhongHopLe(f"{duong_dan.name}: JSON hỏng ({loi})") from None

    def loi(thong_diep: str):
        return KetQuaDoKhongHopLe(f"{duong_dan.name}: {thong_diep}")

    if not isinstance(raw, dict):
        raise loi(f"gốc file phải là object, nhận được {type(raw).__name__}")
    _kiem_khoa(raw, KHOA_GOC, "cấp gốc", loi)
    # `True == 1` trong Python, nên một `"version": true` lọt qua phép so bằng.
    if isinstance(raw["version"], bool) or raw["version"] != VERSION_KET_QUA:
        raise loi(f"version phải là {VERSION_KET_QUA}, nhận được {raw['version']!r}")
    for khoa in ("vong", "model", "nha_cung_cap", "thoi_diem", "danh_muc_version", "prompt"):
        if not isinstance(raw[khoa], str) or not raw[khoa].strip():
            raise loi(f"`{khoa}` phải là chuỗi không rỗng, nhận được {raw[khoa]!r}")
    try:
        # Cùng luật với mọi mốc thời gian của dự án (Consistency Conventions):
        # UTC, ISO-8601. Một vòng ghi giờ địa phương là hai vòng không so được.
        kiem_thoi_diem(raw["thoi_diem"])
    except (TypeError, ValueError) as e:
        raise loi(f"`thoi_diem` không hợp lệ: {e}") from None
    ten_file = duong_dan.name[: -len(DUOI_FILE)] if duong_dan.name.endswith(DUOI_FILE) else duong_dan.stem
    if raw["vong"] != ten_file:
        raise loi(f"`vong` là {raw['vong']!r} nhưng tên file là {ten_file!r}")
    for khoa in ("tham_so_llm", "chunk"):
        if not isinstance(raw[khoa], dict) or not raw[khoa]:
            raise loi(f"`{khoa}` phải là một bảng không rỗng")
    if not isinstance(raw["tai_lieu"], list) or not raw["tai_lieu"]:
        raise loi("`tai_lieu` phải là danh sách không rỗng")

    tai_lieu: list[TaiLieuDo] = []
    da_thay: set[str] = set()
    for muc in raw["tai_lieu"]:
        if not isinstance(muc, dict):
            raise loi(f"mỗi tài liệu phải là object, nhận được {type(muc).__name__}")
        _kiem_khoa(muc, KHOA_TAI_LIEU, "cấp tài liệu", loi)
        doc_key = muc["doc_key"]
        if not isinstance(doc_key, str) or not doc_key.strip():
            raise loi(f"`doc_key` phải là chuỗi không rỗng, nhận được {doc_key!r}")
        if doc_key in da_thay:
            raise loi(f"{doc_key}: khai hai lần")
        da_thay.add(doc_key)
        if not isinstance(muc["chunks"], list) or not muc["chunks"]:
            raise loi(f"{doc_key}: `chunks` phải là danh sách không rỗng")
        chunks: list[ChunkDo] = []
        for c in muc["chunks"]:
            if not isinstance(c, dict):
                raise loi(f"{doc_key}: mỗi chunk phải là object")
            _kiem_khoa(c, KHOA_CHUNK, f"chunk của {doc_key}", loi)
            for khoa in ("stt", "token_vao", "token_ra"):
                if isinstance(c[khoa], bool) or not isinstance(c[khoa], int) or c[khoa] < 0:
                    raise loi(f"{doc_key}: `{khoa}` phải là số nguyên không âm, nhận được {c[khoa]!r}")
            for khoa in ("van_ban", "phan_hoi"):
                if not isinstance(c[khoa], str):
                    raise loi(f"{doc_key}: `{khoa}` phải là chuỗi, nhận được {type(c[khoa]).__name__}")
            gia = c["chi_phi_usd"]
            # `math.isfinite` chứ không chỉ `>= 0`: `NaN` và `Infinity` qua được
            # `json.loads` và đầu độc mọi tổng sau đó mà không nổ ở đâu cả.
            if (
                isinstance(gia, bool)
                or not isinstance(gia, (int, float))
                or not math.isfinite(gia)
                or gia < 0
            ):
                raise loi(f"{doc_key}: `chi_phi_usd` phải là số hữu hạn không âm, nhận được {gia!r}")
            chunks.append(ChunkDo(**{k: c[k] for k in KHOA_CHUNK}))
        tai_lieu.append(TaiLieuDo(doc_key=doc_key, chunks=tuple(chunks)))

    return KetQuaVong(
        version=raw["version"],
        vong=raw["vong"],
        model=raw["model"],
        nha_cung_cap=raw["nha_cung_cap"],
        thoi_diem=raw["thoi_diem"],
        danh_muc_version=raw["danh_muc_version"],
        prompt=raw["prompt"],
        tham_so_llm=raw["tham_so_llm"],
        chunk=raw["chunk"],
        tai_lieu=tuple(tai_lieu),
    )


def _kiem_khoa(muc: Mapping, cho_phep: frozenset[str], o_dau: str, loi) -> None:
    thieu, la = sorted(cho_phep - set(muc)), sorted(set(muc) - cho_phep)
    if thieu or la:
        raise loi(f"{o_dau}: khóa thiếu {thieu}, khóa lạ {la}")


def doc_moi_vong(thu_muc: str | Path = THU_MUC_KET_QUA) -> list[KetQuaVong]:
    """Mọi vòng trong một thư mục, sắp theo tên file (v0 trước v1).

    Bỏ qua bản lưu `*.bak.json` mà `--ghi-de` để lại: nó là *bản cũ* của một
    vòng đã bị thay, nên đọc nó lên thành một vòng nữa là dựng một cột báo cáo
    trùng tên với cột bên cạnh.
    """
    thu_muc = Path(thu_muc)
    if not thu_muc.is_dir():
        return []
    return [
        doc_ket_qua(p)
        for p in sorted(thu_muc.glob(f"*{DUOI_FILE}"))
        if not p.name.endswith(DUOI_BAN_CU)
    ]


def duong_dan_ban_cu(duong_dan: Path) -> Path:
    """Tên bản lưu của một file kết quả: `<vòng>.json` -> `<vòng>.bak.json`."""
    ten = duong_dan.name
    goc = ten[: -len(DUOI_FILE)] if ten.endswith(DUOI_FILE) else ten
    return duong_dan.with_name(goc + DUOI_BAN_CU)


def ghi_ket_qua(duong_dan: str | Path, du_lieu: Mapping, ghi_de: bool = False) -> Path:
    """Ghi một vòng; file đã có mà không có cờ ghi đè là `KetQuaDoDaCo`.

    Ghi đè **giữ bản cũ** thành `<vòng>.bak.json` trước khi thay (story 2.8):
    `--ghi-de` xóa vĩnh viễn một vòng đã trả tiền, và cái giá của một bản lưu là
    vài chục KB. Sao lưu hỏng thì không ghi đè - lỗi lan lên nguyên trạng, file
    cũ còn nguyên.
    """
    duong_dan = Path(duong_dan)
    if duong_dan.exists():
        if not ghi_de:
            raise KetQuaDoDaCo(
                f"{duong_dan.name} đã có trong {duong_dan.parent}: một vòng là tiền đã"
                f" tiêu, không ghi đè lặng lẽ. Đổi tên vòng, hoặc chạy lại với {CO_GHI_DE}"
            )
        ban_cu = duong_dan_ban_cu(duong_dan)
        if ban_cu.exists():
            # Lần `--ghi-de` thứ hai đè luôn bản lưu của lần thứ nhất, tức chính
            # cơ chế chống mất "một vòng là tiền đã tiêu" tự hỏng ở lần thứ hai.
            # Không tự đặt tên thứ ba (`.bak2`, mốc thời gian): người chạy phải
            # nhìn thấy mình đang có hai bản và quyết bỏ bản nào.
            raise KetQuaDoDaCo(
                f"{ban_cu} đã có: một lần {CO_GHI_DE} trước đã lưu bản cũ ở đó, và"
                f" ghi đè tiếp sẽ xóa nó. Dọn hoặc đổi tên {ban_cu.name} rồi chạy lại."
            )
        os.replace(duong_dan, ban_cu)
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    _ghi_nguyen_tu(duong_dan, du_lieu)
    return duong_dan


def _ghi_nguyen_tu(duong_dan: Path, du_lieu: Mapping) -> None:
    """Ghi qua file tạm rồi `os.replace`: một lần chạy bị giết giữa chừng không
    được để lại một file JSON cụt mà `doc_ket_qua` từ chối, trong khi bản đầy đủ
    thì đã mất."""
    tam = duong_dan.with_name(duong_dan.name + ".dang-ghi")
    tam.write_text(
        json.dumps(dict(du_lieu), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    os.replace(tam, duong_dan)


# ---------------------------------------------------------------------------
# Phần tốn tiền
# ---------------------------------------------------------------------------


class GomChiPhi:
    """`AuditPort` trong bộ nhớ: giữ sự kiện chi phí của từng lời gọi.

    Harness không có Postgres (và không được import `api/`), nhưng token và
    tiền phải đi qua đúng seam đo của FR-30 thay vì được đếm lại ở đây. Wrapper
    ghi một sự kiện mỗi lời gọi *thành công*; lời gọi hỏng không có sự kiện,
    nên số lời gọi trong sổ luôn khớp số phản hồi lưu được.
    """

    def __init__(self):
        self.su_kien: list[SuKienAudit] = []

    async def ghi(self, su_kien: SuKienAudit) -> None:
        self.su_kien.append(su_kien)

    def moc(self) -> int:
        """Số sự kiện đã ghi - chụp trước một lời gọi để neo sự kiện của nó."""
        return len(self.su_kien)

    def su_kien_cua_loi_goi(self, moc: int) -> SuKienAudit:
        """Sự kiện chi phí *của đúng lời gọi vừa rồi*, tính từ mốc trước lời gọi.

        Không lấy `su_kien[-1]`: `ghi_quan_sat` nuốt lỗi của port ở tầng
        observation, nên một lời gọi không ghi được sự kiện sẽ khiến lời gọi sau
        nhận token và USD của lời gọi trước - sai số im lặng, đúng loại sai số
        làm hỏng một bảng chi phí.
        """
        moi = self.su_kien[moc:]
        if len(moi) != 1:
            raise RuntimeError(
                f"lời gọi vừa rồi ghi {len(moi)} sự kiện chi phí, cần đúng 1:"
                " không neo được token/USD vào chunk nào"
            )
        return moi[0]


# ---------------------------------------------------------------------------
# Thử lại khi provider chặn nhịp (story 2.8, hạ xuống `adapters/` ở 2.13)
# ---------------------------------------------------------------------------
#
# Khuôn 429/5xx/lỗi mạng sống ở `adapters/thu_lai.py` từ story 2.13: đường *nạp*
# cần đúng luật đó và `api/` không import được `eval/`. Ở đây còn lại đúng một
# lớp mỏng - `goi_llm_co_thu_lai` neo tên "LLM" vào thông điệp thử lại và giữ
# chữ ký cũ mà runner gọi. Tên nào của khuôn cũng được re-export nguyên vẹn: nó
# là hợp đồng của `tests/test_cham_trich_xuat.py`, và một tên đổi chỗ ở đây là
# một test đỏ không nói về hành vi nào.


async def goi_llm_co_thu_lai(
    llm,
    prompt: str,
    *,
    so_lan_thu: int = SO_LAN_THU,
    sleep=None,
    in_ra=print,
    **tham_so,
) -> str:
    """Gọi LLM, thử lại đúng 429 và 5xx, ném nguyên lỗi cuối cùng."""
    return await goi_co_thu_lai(
        llm,
        prompt,
        _so_lan_thu=so_lan_thu,
        _sleep=sleep,
        _in_ra=in_ra,
        _ten="LLM",
        **tham_so,
    )


def kiem_ten_vong(vong: str) -> str:
    """Tên vòng phải là một tên file an toàn; trả lại chính nó."""
    if not isinstance(vong, str) or not _TEN_VONG_HOP_LE.match(vong):
        raise KetQuaDoKhongHopLe(
            f"tên vòng {vong!r} không hợp lệ: bắt đầu bằng chữ hoặc số, sau đó chỉ"
            " chữ, số, dấu chấm, gạch ngang và gạch dưới (tên vòng là tên file)"
        )
    if vong.endswith(DUOI_BAN_CU[: -len(DUOI_FILE)]):
        # Hình dạng tên cho phép dấu chấm, nên `--vong v1.bak` ghi ra
        # `v1.bak.json` - đúng đuôi mà `doc_moi_vong` bỏ qua. Một vòng đã trả
        # tiền vắng mặt khỏi mọi báo cáo mà không ai biết là kiểu hỏng tệ nhất
        # của một harness đo: nó không đỏ, nó chỉ thiếu.
        raise KetQuaDoKhongHopLe(
            f"tên vòng {vong!r} kết thúc bằng {DUOI_BAN_CU[: -len(DUOI_FILE)]!r}:"
            f" file sinh ra sẽ mang đuôi {DUOI_BAN_CU} mà `doc_moi_vong` bỏ qua,"
            " nên vòng này sẽ không bao giờ xuất hiện trong báo cáo. Đổi tên vòng."
        )
    return vong


def _khoi_tu_dien_cua_vong(tu_dien_path, bo) -> str:
    """Khối từ điển dùng cho **cả vòng**, hoặc chuỗi rỗng khi không khai từ điển.

    Đường nạp lọc từ điển theo scope của từng tài liệu; một vòng đo thì ghi đúng
    **một** chuỗi vào trường `prompt` của file kết quả. Nên nếu bộ vàng trải trên
    nhiều scope mà từ điển cho ra hai khối khác nhau, vòng này **từ chối chạy**
    thay vì ghi một `prompt` chỉ đúng với một phần tài liệu - một file kết quả tự
    khai sai prompt của chính nó là thứ không ai phát hiện lại được sau khi tiền
    đã tiêu.

    Ca chạy được là từ điển toàn mục `SCOPE_CHUNG`, đúng hình dạng của
    `config/tu-dien-thuc-the/synth.yaml`.
    """
    if tu_dien_path is None:
        return ""
    tu_dien: TuDienThucThe = tai_tu_dien_thuc_the(tu_dien_path)
    theo_scope = {
        t.scope: khoi_tu_dien(tu_dien.muc_cho_scope(t.scope)) for t in bo.tai_lieu_cham()
    }
    khac_nhau = set(theo_scope.values())
    if len(khac_nhau) > 1:
        raise KetQuaDoKhongHopLe(
            f"từ điển {tu_dien_path} cho ra {len(khac_nhau)} khối prompt khác nhau"
            f" trên các scope của bộ vàng ({sorted(theo_scope)}): một file kết quả"
            " chỉ giữ được một chuỗi `prompt`, nên vòng này sẽ tự khai sai prompt"
            " của chính nó. Dùng từ điển toàn mục scope `*` cho vòng đo, hoặc đo"
            " riêng từng scope thành hai vòng"
        )
    return khac_nhau.pop() if khac_nhau else ""


async def chay_vong(
    *,
    vong: str,
    model: str,
    thu_muc_ket_qua: Path = THU_MUC_KET_QUA,
    policy_path: Path = POLICY_MAC_DINH,
    space: str = SPACE_MAC_DINH,
    vai: str = VAI_MAC_DINH,
    ghi_de: bool = False,
    tu_dien_path: str | Path | None = None,
    in_ra=print,
    dung_llm=None,
    sleep=None,
) -> Path:
    """Chạy một vòng trên mọi tài liệu chấm của bộ vàng, ghi file kết quả, trả đường dẫn.

    `dung_llm` là seam tiêm: nhận `(muc_model, danh_muc, audit)` và trả hàm LLM
    đã bọc. Mặc định dựng provider thật từ môi trường (tốn tiền); test tiêm một
    provider giả để chạy được toàn bộ đường đi mà không có key và không có mạng.

    `sleep` là seam tiêm thứ hai, **không phải một tùy chọn vận hành**: nó đi
    thẳng vào `tenacity.AsyncRetrying` để test chạy được nhánh thử lại mà không
    ngủ thật. Không có cờ dòng lệnh nào đặt nó, và không nên có - đường chạy
    thật phải chờ đúng thời gian provider yêu cầu.

    `tu_dien_path` là từ điển thực thể của story 2.12. Vắng nó thì prompt bằng
    đúng từng byte bản của story 2.6 và vòng đo so được thẳng với `v1-deepseek`;
    có nó thì mỗi lời gọi mang thêm khối từ điển, và đó là prompt mà đợt nạp
    `synth` sẽ chạy - đúng thứ mà ràng buộc "đổi prompt là đo lại R2 trước khi
    thay" đòi phải đo.
    """
    kiem_ten_vong(vong)
    dich = Path(thu_muc_ket_qua) / f"{vong}{DUOI_FILE}"
    if dich.exists() and not ghi_de:
        raise KetQuaDoDaCo(
            f"{dich.name} đã có: vòng này đã chạy và đã tốn tiền. Đổi tên vòng,"
            f" hoặc chạy lại với {CO_GHI_DE}"
        )

    bo = doc_bo_vang()
    if not bo.tai_lieu_cham():
        raise KetQuaDoKhongHopLe(
            "bộ vàng không còn tài liệu chấm nào: một vòng đo trên 0 tài liệu ghi ra"
            " file mà chính loader của nó từ chối"
        )
    danh_muc = danh_muc_mac_dinh()
    muc = danh_muc.muc(model, loai=LOAI_LLM)
    audit = GomChiPhi()
    llm = (dung_llm or _llm_that)(muc, danh_muc, audit)

    policy = load_policy(policy_path)
    ngu_canh = user_context(
        policy=policy, role=vai, space=space, real_account=TAI_KHOAN
    )
    cau_hinh = cau_hinh_chunk()
    khoi = _khoi_tu_dien_cua_vong(tu_dien_path, bo)
    prompt_vong = PROMPT_TRICH_XUAT.replace(CHO_TU_DIEN, khoi)

    def dung_du_lieu(tai_lieu: list[dict]) -> dict:
        return {
            "version": VERSION_KET_QUA,
            "vong": vong,
            "model": muc.ten,
            "nha_cung_cap": muc.nha_cung_cap,
            "thoi_diem": thoi_diem_utc(),
            "danh_muc_version": danh_muc.version,
            "prompt": prompt_vong,
            "tham_so_llm": dict(THAM_SO_LLM),
            "chunk": cau_hinh,
            "tai_lieu": tai_lieu,
        }

    # Tạo trước cả hai thư mục: lời gọi LLM đầu tiên đã tốn tiền, không được để
    # phần ghi cứu hộ nổ vì thư mục chưa có.
    dich.parent.mkdir(parents=True, exist_ok=True)
    thu_muc_tam = dich.parent / THU_MUC_CHUA_XONG
    thu_muc_tam.mkdir(parents=True, exist_ok=True)
    tam = thu_muc_tam / f"{vong}-{thoi_diem_utc().replace(':', '').replace('.', '')}.json"
    tai_lieu: list[dict] = []
    try:
        with use_context(ngu_canh):
            for t in bo.tai_lieu_cham():
                chunks: list[dict] = []
                # Mục của tài liệu vào danh sách **trước** lời gọi đầu tiên và
                # mang cờ `dang_do`, để file cứu hộ ghi ra giữa chừng nói được
                # tài liệu nào đang dở. Cờ bị gỡ khi tài liệu chạy xong, nên
                # file kết quả cuối cùng không bao giờ mang nó.
                muc_tai_lieu = {"doc_key": t.doc_key, "chunks": chunks, KHOA_DANG_DO: True}
                tai_lieu.append(muc_tai_lieu)
                for i, dp in enumerate(chia_chunk(t.than, cau_hinh)):
                    van_ban = dp["content"]
                    moc = audit.moc()
                    phan_hoi = await goi_llm_co_thu_lai(
                        llm,
                        dung_prompt(van_ban, khoi),
                        sleep=sleep,
                        in_ra=in_ra,
                        **THAM_SO_LLM,
                    )
                    chi_tiet = audit.su_kien_cua_loi_goi(moc).chi_tiet
                    chunks.append(
                        {
                            "stt": i,
                            "van_ban": van_ban,
                            "phan_hoi": phan_hoi,
                            **_so_chi_phi(chi_tiet, t.doc_key, i),
                        }
                    )
                    # Ghi tăng dần sau *mỗi chunk*, không phải sau mỗi tài liệu
                    # (story 2.8): một tài liệu 5 chunk hỏng ở chunk thứ 5 từng
                    # làm bay mất bốn lời gọi đã trả tiền.
                    _ghi_nguyen_tu(tam, dung_du_lieu(tai_lieu))
                    kq = phan_tich_phan_hoi(phan_hoi)
                    in_ra(
                        f"  {t.doc_key} chunk {i}: {len(kq.facts)} fact hợp lệ /"
                        f" {kq.so_ban_ghi} thô, {chi_tiet[CT_TOKEN_VAO]}+{chi_tiet[CT_TOKEN_RA]} token",
                        flush=True,
                    )
                if not chunks:
                    # Thân rỗng -> 0 chunk -> file ghi ra tự vi phạm lược đồ của
                    # chính nó. Dừng ở đây, nói đúng tài liệu nào.
                    raise KetQuaDoKhongHopLe(
                        f"{t.doc_key}: chia chunk ra 0 chunk (thân rỗng?), không có gì để đo"
                    )
                del muc_tai_lieu[KHOA_DANG_DO]
    except BaseException:
        xong = [m for m in tai_lieu if not m.get(KHOA_DANG_DO)]
        dang_do = [m for m in tai_lieu if m.get(KHOA_DANG_DO)]
        if any(m["chunks"] for m in tai_lieu):
            # Ghi lần cuối trước khi in: ca 0 chunk ném *trước* một lần ghi nào
            # của tài liệu đó, và một lỗi lúc ghi cứu hộ không được che mất lỗi
            # gốc đã làm vòng dừng.
            try:
                _ghi_nguyen_tu(tam, dung_du_lieu(tai_lieu))
            except Exception:
                in_ra(f"LỖI: không ghi được file cứu hộ {tam}", flush=True)
            # Luôn nêu tên tài liệu đang dở, kể cả khi nó hỏng ngay ở chunk
            # đầu (`chunks` rỗng) - đó là ca thường gặp nhất, và bỏ nó đi thì
            # thông điệp hứa "nói được vòng dừng ở đâu" mà không nói.
            do_dang = (
                f" cộng {dang_do[0]['doc_key']} đang dở ở"
                f" {len(dang_do[0]['chunks'])} chunk đã trả tiền"
                if dang_do
                else ""
            )
            # Không hứa "chạy tiếp phần còn lại": chưa có cờ nào làm việc đó, và
            # chạy lại là trả tiền lại cho cả tập.
            in_ra(
                f"LỖI giữa chừng: phản hồi đã trả tiền của {len(xong)}/"
                f"{len(bo.tai_lieu_cham())} tài liệu{do_dang} nằm ở {tam}. Đó *không*"
                " phải file kết quả hợp lệ (thiếu tài liệu, và tài liệu dở dang mang"
                f" cờ `{KHOA_DANG_DO}`) và không có đường chạy tiếp phần còn lại: chạy"
                " lại vòng này là trả tiền lại cho cả tập. Giữ file đó làm bằng chứng,"
                " hoặc bổ sung tay phần thiếu rồi đổi tên thành một tên vòng mới.",
                flush=True,
            )
        raise

    du_lieu = dung_du_lieu(tai_lieu)
    ghi_ket_qua(dich, du_lieu, ghi_de=ghi_de)
    tam.unlink(missing_ok=True)
    kq = doc_ket_qua(dich)
    in_ra(
        f"vòng {vong} ({muc.ten}): {len(kq.tai_lieu)} tài liệu, {kq.so_chunk()} chunk,"
        f" {kq.so_hop_le()} fact hợp lệ / {kq.so_fact_tho()} thô,"
        f" loại {kq.loai_theo_ma() or '{}'}, {kq.token_vao()}+{kq.token_ra()} token,"
        f" {kq.chi_phi_usd():.6f} USD"
    )
    in_ra(f"ghi {dich}")
    return dich


def _so_chi_phi(chi_tiet: Mapping, doc_key: str, stt: int) -> dict:
    """Ba con số chi phí của một lời gọi, đã kiểm; thiếu hay xấu là dừng ngay.

    Sự kiện chi phí do wrapper dựng nên thiếu khóa là chuyện "không bao giờ xảy
    ra" - nhưng nếu xảy ra thì `KeyError` giữa chừng làm mất phản hồi của cả
    những tài liệu đã trả tiền, và một số âm lọt vào file kết quả thì mọi tổng
    sau đó sai mà không ai thấy.
    """
    thieu = [k for k in (CT_TOKEN_VAO, CT_TOKEN_RA, CT_CHI_PHI_USD) if k not in chi_tiet]
    if thieu:
        raise KetQuaDoKhongHopLe(
            f"{doc_key} chunk {stt}: sự kiện chi phí thiếu khóa {thieu}"
        )
    tv, tr = chi_tiet[CT_TOKEN_VAO], chi_tiet[CT_TOKEN_RA]
    gia = chi_tiet[CT_CHI_PHI_USD]
    if not isinstance(tv, int) or not isinstance(tr, int) or tv < 0 or tr < 0:
        raise KetQuaDoKhongHopLe(
            f"{doc_key} chunk {stt}: token phải là số nguyên không âm, nhận được {tv!r}/{tr!r}"
        )
    if not isinstance(gia, (int, float)) or not math.isfinite(gia) or gia < 0:
        raise KetQuaDoKhongHopLe(
            f"{doc_key} chunk {stt}: chi phí phải là số hữu hạn không âm, nhận được {gia!r}"
        )
    return {"token_vao": int(tv), "token_ra": int(tr), "chi_phi_usd": float(gia)}


# ---------------------------------------------------------------------------
# Ước tính trước khi tiêu tiền (story 2.8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UocTinhVong:
    """Ước tính của một vòng: hàm thuần, không gọi LLM, không tốn tiền.

    Token *vào* đếm trên chính chuỗi prompt sắp gửi, bằng bộ tách token mà
    `adapters/chunking.py` dùng. Nó **thấp hơn** số provider tính khoảng 25-30%
    vì provider còn cộng phần bọc hội thoại của riêng nó (đối chứng: bốn vòng
    của 2.6 cho 741-1015 token vào mỗi chunk, ước tính ở đây cho ~734). Token
    *ra* là ước lượng có tên (`TOKEN_RA_UOC_MOI_CHUNK`), lấy trần trên bốn vòng
    đó vì nó chỉ biết được sau khi model trả lời.

    Nói cách khác đây là một con số *cùng bậc*, đủ để trả lời "sắp gọi bao nhiêu
    lời và tốn khoảng bao nhiêu", không phải một hóa đơn.
    """

    model: str
    so_tai_lieu: int
    so_loi_goi: int
    token_vao: int
    token_ra_uoc: int
    chi_phi_usd: float

    def dong_in(self) -> str:
        return (
            f"ước tính vòng trên {self.model}: {self.so_tai_lieu} tài liệu chấm,"
            f" {self.so_loi_goi} lời gọi (số đếm chính xác),"
            f" {self.token_vao} token vào + {self.token_ra_uoc} token ra,"
            f" khoảng {self.chi_phi_usd:.6f} USD theo đơn giá danh mục.\n"
            "  Con số tiền là **cùng bậc, không bảo đảm chiều**: token vào đếm"
            " thiếu phần bọc hội thoại của provider (~25-30%), token ra là ước"
            f" lượng {TOKEN_RA_UOC_MOI_CHUNK}/chunk. Đừng đọc nó như một trần chi."
        )


def uoc_tinh_vong(
    model: str, *, bo=None, danh_muc=None, tu_dien_path=None
) -> UocTinhVong:
    """Số lời gọi và tiền dự kiến của một vòng; **không** gọi LLM.

    `tu_dien_path` phải là **cùng** từ điển mà vòng thật sẽ chạy: khối từ điển
    nằm trong prompt nên nó vào token vào, và một ước tính đọc prompt khác prompt
    sắp gửi là một ước tính của một vòng khác. Nó cũng chạy đúng phép từ chối
    "nhiều khối prompt khác nhau", nên cờ xem trước bắt được cấu hình hỏng
    *trước* khi ai đó gõ lệnh thật.
    """
    bo = doc_bo_vang() if bo is None else bo
    if not bo.tai_lieu_cham():
        # "0 lời gọi, 0,000000 USD" rồi thoát 0 đọc y như một vòng miễn phí, và
        # đó là câu trả lời sai cho câu hỏi duy nhất mà cờ này trả lời.
        raise KetQuaDoKhongHopLe(
            "bộ vàng không còn tài liệu chấm nào: ước tính sẽ là 0 lời gọi và"
            " 0 USD, đọc y như một vòng miễn phí thay vì một bộ vàng hỏng"
        )
    danh_muc = danh_muc_mac_dinh() if danh_muc is None else danh_muc
    muc = danh_muc.muc(model, loai=LOAI_LLM)
    cau_hinh = cau_hinh_chunk()
    khoi = _khoi_tu_dien_cua_vong(tu_dien_path, bo)
    so_loi_goi = token_vao = 0
    for t in bo.tai_lieu_cham():
        for dp in chia_chunk(t.than, cau_hinh):
            so_loi_goi += 1
            token_vao += dem_token(dung_prompt(dp["content"], khoi), cau_hinh)
    token_ra = so_loi_goi * TOKEN_RA_UOC_MOI_CHUNK
    return UocTinhVong(
        model=muc.ten,
        so_tai_lieu=len(bo.tai_lieu_cham()),
        so_loi_goi=so_loi_goi,
        token_vao=token_vao,
        token_ra_uoc=token_ra,
        chi_phi_usd=muc.chi_phi_usd(token_vao, token_ra),
    )


def _llm_that(muc, danh_muc, audit):
    """Provider thật từ môi trường - đường tốn tiền, mặc định của `chay_vong`."""
    ncc = danh_muc.nha_cung_cap_cua(muc)
    if not ncc.cuc_bo and nap_bien_tu_env(ncc.bien_api_key) is None:
        # Không đọc được key thì nói ngay, trước lời gọi đầu tiên; giá trị key
        # không bao giờ được in ra.
        print(
            f"cảnh báo: không lấy được {ncc.bien_api_key} từ môi trường hay .env gốc repo",
            file=sys.stderr,
        )
    nha_cung_cap = nha_cung_cap_tu_moi_truong(muc, danh_muc)
    return bo_llm(nha_cung_cap=nha_cung_cap, model=muc.ten, audit=audit, danh_muc=danh_muc)


def _tham_so(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Chạy một vòng đo trích xuất trên các tài liệu chấm của bộ vàng"
            " (mọi tài liệu không phải few-shot). Tốn tiền thật."
        )
    )
    p.add_argument("--vong", required=True, help="tên vòng, cũng là tên file kết quả")
    p.add_argument("--model", required=True, help="tên model trong config/danh-muc-model.yaml")
    p.add_argument("--space", default=SPACE_MAC_DINH)
    p.add_argument("--vai", default=VAI_MAC_DINH)
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH)
    p.add_argument("--thu-muc", type=Path, default=THU_MUC_KET_QUA)
    p.add_argument(
        "--tu-dien",
        type=Path,
        default=None,
        dest="tu_dien",
        help=(
            "từ điển thực thể chuẩn (story 2.12); vắng thì prompt bằng đúng bản"
            " của story 2.6 và vòng so thẳng được với v1-deepseek"
        ),
    )
    p.add_argument(
        CO_GHI_DE,
        action="store_true",
        help=f"ghi đè file kết quả đã có (bản cũ giữ lại thành `<vòng>{DUOI_BAN_CU}`)",
    )
    p.add_argument(
        CO_UOC_TINH,
        action="store_true",
        help="in số lời gọi và tiền dự kiến rồi thoát; không gọi LLM, không tốn tiền",
    )
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    ts = _tham_so(sys.argv[1:] if argv is None else argv)
    try:
        if ts.uoc_tinh:
            # Nhánh không tốn tiền: in rồi thoát 0, không chạm thư mục kết quả
            # và không kiểm `--ghi-de`. Xem trước phải chạy được cả khi file
            # kết quả đã có, vì đó đúng là lúc người ta muốn xem trước nhất.
            print(uoc_tinh_vong(ts.model, tu_dien_path=ts.tu_dien).dong_in())
            return 0
        asyncio.run(
            chay_vong(
                vong=ts.vong,
                model=ts.model,
                thu_muc_ket_qua=ts.thu_muc,
                policy_path=ts.policy,
                space=ts.space,
                vai=ts.vai,
                ghi_de=ts.ghi_de,
                tu_dien_path=ts.tu_dien,
            )
        )
    except (KetQuaDoDaCo, KetQuaDoKhongHopLe, ChanNhipQuaLau) as loi:
        print(f"{type(loi).__name__}: {loi}", file=sys.stderr)
        return 1
    except ModelUnknown as loi:
        # Tên model gõ sai là chuyện của người dùng dòng lệnh, không phải một
        # traceback: nêu thẳng danh sách model có trong danh mục.
        print(f"{ModelUnknown.code}: {loi}", file=sys.stderr)
        return 1
    except ProviderConfigMissing as loi:
        print(f"{ProviderConfigMissing.code}: {loi}", file=sys.stderr)
        return 1
    except BoVangKhongHopLe as loi:
        # Bộ vàng hỏng là chuyện sửa file rồi chạy lại, không phải traceback -
        # và nó phải nổ *trước* lời gọi LLM đầu tiên.
        print(str(loi), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
