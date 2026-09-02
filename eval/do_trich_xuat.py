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

from adapters.chunking import TRUONG_CHUNK, cau_hinh_chunk, chia_chunk
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
from adapters.trich_xuat import PROMPT_TRICH_XUAT, THAM_SO_LLM, dung_prompt
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
    """Mọi vòng trong một thư mục, sắp theo tên file (v0 trước v1)."""
    thu_muc = Path(thu_muc)
    if not thu_muc.is_dir():
        return []
    return [doc_ket_qua(p) for p in sorted(thu_muc.glob(f"*{DUOI_FILE}"))]


def ghi_ket_qua(duong_dan: str | Path, du_lieu: Mapping, ghi_de: bool = False) -> Path:
    """Ghi một vòng; file đã có mà không có cờ ghi đè là `KetQuaDoDaCo`."""
    duong_dan = Path(duong_dan)
    if duong_dan.exists() and not ghi_de:
        raise KetQuaDoDaCo(
            f"{duong_dan.name} đã có trong {duong_dan.parent}: một vòng là tiền đã"
            f" tiêu, không ghi đè lặng lẽ. Đổi tên vòng, hoặc chạy lại với {CO_GHI_DE}"
        )
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


def kiem_ten_vong(vong: str) -> str:
    """Tên vòng phải là một tên file an toàn; trả lại chính nó."""
    if not isinstance(vong, str) or not _TEN_VONG_HOP_LE.match(vong):
        raise KetQuaDoKhongHopLe(
            f"tên vòng {vong!r} không hợp lệ: bắt đầu bằng chữ hoặc số, sau đó chỉ"
            " chữ, số, dấu chấm, gạch ngang và gạch dưới (tên vòng là tên file)"
        )
    return vong


async def chay_vong(
    *,
    vong: str,
    model: str,
    thu_muc_ket_qua: Path = THU_MUC_KET_QUA,
    policy_path: Path = POLICY_MAC_DINH,
    space: str = SPACE_MAC_DINH,
    vai: str = VAI_MAC_DINH,
    ghi_de: bool = False,
    in_ra=print,
    dung_llm=None,
) -> Path:
    """Chạy một vòng trên mọi tài liệu chấm của bộ vàng, ghi file kết quả, trả đường dẫn.

    `dung_llm` là seam tiêm: nhận `(muc_model, danh_muc, audit)` và trả hàm LLM
    đã bọc. Mặc định dựng provider thật từ môi trường (tốn tiền); test tiêm một
    provider giả để chạy được toàn bộ đường đi mà không có key và không có mạng.
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

    def dung_du_lieu(tai_lieu: list[dict]) -> dict:
        return {
            "version": VERSION_KET_QUA,
            "vong": vong,
            "model": muc.ten,
            "nha_cung_cap": muc.nha_cung_cap,
            "thoi_diem": thoi_diem_utc(),
            "danh_muc_version": danh_muc.version,
            "prompt": PROMPT_TRICH_XUAT,
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
                for i, dp in enumerate(chia_chunk(t.than, cau_hinh)):
                    van_ban = dp["content"]
                    moc = audit.moc()
                    phan_hoi = await llm(dung_prompt(van_ban), **THAM_SO_LLM)
                    chi_tiet = audit.su_kien_cua_loi_goi(moc).chi_tiet
                    chunks.append(
                        {
                            "stt": i,
                            "van_ban": van_ban,
                            "phan_hoi": phan_hoi,
                            **_so_chi_phi(chi_tiet, t.doc_key, i),
                        }
                    )
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
                tai_lieu.append({"doc_key": t.doc_key, "chunks": chunks})
                # Ghi tăng dần sau *mỗi tài liệu*: một lần chạy hỏng ở tài liệu
                # thứ sáu không được làm bay mất năm tài liệu đã trả tiền.
                _ghi_nguyen_tu(tam, dung_du_lieu(tai_lieu))
    except BaseException:
        if tai_lieu:
            # Không hứa "chạy tiếp phần còn lại": chưa có cờ nào làm việc đó, và
            # chạy lại là trả tiền lại cho cả tập.
            in_ra(
                f"LỖI giữa chừng: phản hồi đã trả tiền của {len(tai_lieu)}/"
                f"{len(bo.tai_lieu_cham())} tài liệu nằm ở {tam}. Đó *không* phải"
                " file kết quả hợp lệ (thiếu tài liệu) và không có đường chạy tiếp"
                " phần còn lại: chạy lại vòng này là trả tiền lại cho cả tập. Giữ"
                " file đó làm bằng chứng, hoặc bổ sung tay phần thiếu rồi đổi tên"
                " thành một tên vòng mới.",
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
    p.add_argument(CO_GHI_DE, action="store_true", help="ghi đè file kết quả đã có")
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    ts = _tham_so(sys.argv[1:] if argv is None else argv)
    try:
        asyncio.run(
            chay_vong(
                vong=ts.vong,
                model=ts.model,
                thu_muc_ket_qua=ts.thu_muc,
                policy_path=ts.policy,
                space=ts.space,
                vai=ts.vai,
                ghi_de=ts.ghi_de,
            )
        )
    except (KetQuaDoDaCo, KetQuaDoKhongHopLe) as loi:
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
