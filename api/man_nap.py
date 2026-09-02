"""Màn nạp tài liệu tối giản cho vòng lặp tuần 2 (story 2.7).

App FastAPI **thứ hai**, không phải `api/main.py`: một trang HTML thuần và ba
endpoint JSON, chạy thành service compose riêng bind `127.0.0.1:8100` của máy
chủ (vào bằng SSH tunnel). Màn không có xác thực - JWT là story 3.1 - nên nó
không được lộ ra ngoài bằng bất kỳ đường nào, và không nằm trong đường demo.

Bốn khối mà trang phải hiện, đúng theo Epic 2 context: tiến trình từng tài
liệu (tài liệu đang xử lý có chỉ báo, không ô nào trắng đơ), file bị từ chối
kèm lý do, số fact trích được / bị loại, và kết quả đối chiếu hai kho của đợt.

Ba luật của màn:

- **Không dựng đường ingest thứ hai.** File tải lên được ghi vào một thư mục
  tạm rồi đi qua đúng `core.ingest_scan.quet_cac_file` và
  `adapters.ingest.nap_cac_tai_lieu` mà `api/do_chi_phi.py` gọi. `doc_key` là
  tên file, cùng quy ước với CLI, nên nạp lại cùng tên là re-ingest ghi đè.
- **Chỉ metadata lên trang.** Đợt chạy dưới cờ system nên nó đọc thô được mọi
  khóa; trang thì đứng ngoài mọi tầng che. Vì thế ảnh chụp đợt chỉ mang tên
  file, mã, số đếm, token/USD và thông điệp lỗi - không thân tài liệu, không
  giá trị slot, không id join nguyên văn.
- **Cửa vào có kiểm, dù chỉ chạy trên loopback.** `Origin` lạ bị chặn (multipart
  là simple request nên không có preflight CORS: trong lúc SSH tunnel mở, một
  trang bất kỳ POST được vào đây), `space` đi qua `core.ids.validate_space` vì
  màn không có đường xóa, và trần kích thước cắt ngay ở vòng đọc. Hệ quả của
  luật `Origin`: tunnel phải đúng cổng 8100 ở phía laptop.
- **Một đợt tại một thời điểm.** Đang chạy thì `POST /api/nap` trả 409 chứ
  không xếp hàng; `KhoaIngest` (flock trên `HYPER_RAG_WORKING_DIR`) vẫn là chốt
  cuối giữa màn và CLI, nên hai bên phải trỏ cùng thư mục làm việc.

Đợt sống trong bộ nhớ tiến trình: restart mất lịch sử đợt, dữ liệu đã nạp thì
không. Đó là đánh đổi có chủ đích - một bảng Postgres cho lịch sử đợt là một
lược đồ phải bảo trì cho một màn dùng vài tuần.
"""

import asyncio
import json
import logging
import tempfile
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from adapters.ingest import (
    TRANG_THAI_DA_NAP,
    TRANG_THAI_DA_XOA,
    TRANG_THAI_KHONG_DOI,
    TRANG_THAI_TU_CHOI,
)
from adapters.policy_loader import load_policy
from api.audit_postgres import AuditPostgres
from api.dot_nap import (
    MA_DOT_BI_HUY,
    TRANG_THAI_DOT_DANG_CHAY,
    TRANG_THAI_DOT_LOI,
    TRANG_THAI_DOT_XONG,
    LanNap,
    chay_lan_nap,
    tong_chi_phi_dict,
)
from core.audit import thoi_diem_utc
from core.ids import validate_space
from core.ingest_scan import KICH_THUOC_TOI_DA, quet_cac_file

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-toi-gian.yaml"

SPACE_MAC_DINH: str = "synth"

# Trần số đợt giữ trong bộ nhớ. Tiến trình màn sống suốt thời gian stack lên;
# một dict không trần là một chỗ rò bộ nhớ chậm mà không ai để ý.
TRAN_SO_DOT: int = 20

# Đọc file tải lên theo khối, không nuốt cả file vào RAM. Trần kích thước là
# `core.ingest_scan.KICH_THUOC_TOI_DA`, và màn **cắt ngay ở vòng đọc**: ghi
# nhiều nhất trần+1 byte rồi thôi đọc phần còn lại của part đó. Một byte dôi
# ra là đủ để `stat` của cửa quét thấy vượt trần và trả đúng mã `QUA_LON`
# sẵn có, nên không cần đường xử lý mới và "file kế vẫn nạp" giữ nguyên.
KHOI_DOC: int = 1024 * 1024

# Nguồn được phép POST vào màn. Màn là endpoint **không xác thực** tiêu tiền
# thật, mà multipart là simple request nên trình duyệt không hỏi preflight:
# trong lúc SSH tunnel mở, bất kỳ trang nào cũng POST được vào
# `http://localhost:8100/api/nap`. Không có `Origin` thì cho qua (curl, và
# form gửi từ chính trang này ở một số trình duyệt cũ).
GOC_CHO_PHEP: frozenset[str] = frozenset(
    {"http://localhost:8100", "http://127.0.0.1:8100"}
)


class LoiMan(Exception):
    """Lỗi của màn, mang mã ổn định và mã HTTP; test assert trên `ma`."""

    def __init__(self, http: int, ma: str, thong_diep: str):
        super().__init__(thong_diep)
        self.http, self.ma, self.thong_diep = http, ma, thong_diep


MA_KHONG_CO_FILE: str = "KHONG_CO_FILE"
MA_TEN_FILE_LA: str = "TEN_FILE_LA"
MA_DOT_DANG_CHAY: str = "DOT_DANG_CHAY"
MA_DOT_KHONG_CO: str = "DOT_KHONG_CO"
MA_TEN_FILE_TRUNG: str = "TEN_FILE_TRUNG"
MA_SPACE_LA: str = "SPACE_LA"
MA_ORIGIN_LA: str = "ORIGIN_LA"
MA_LOI_MAN: str = "LOI_MAN"


def ten_an_toan(ten: str | None) -> str:
    """Tên file dùng làm `doc_key`: chỉ phần tên, không đường dẫn.

    Trình duyệt gửi `filename` do người dùng kiểm soát, nên nó có thể là
    `../../etc/passwd`. Cắt về phần cuối theo cả `/` lẫn `\\` (client Windows
    gửi dấu ngược, mà `Path` trên Linux không coi đó là dấu phân tách), rồi từ
    chối tên rỗng, `.` và `..` - ba thứ đó không phải tên tài liệu, và một tên
    rỗng làm `doc_key` rỗng trong sổ tài liệu.
    """
    tho = (ten or "").replace("\\", "/")
    sach = Path(tho).name.strip()
    if not sach or sach in (".", ".."):
        raise LoiMan(400, MA_TEN_FILE_LA, f"tên file {ten!r} không dùng làm tên tài liệu được")
    return sach


class QuanLyDot:
    """Sổ đợt trong bộ nhớ tiến trình: đợt mới nhất, và tối đa `TRAN_SO_DOT` đợt.

    Cũng giữ tham chiếu mạnh tới task nền của đợt đang chạy. `asyncio` chỉ giữ
    tham chiếu *yếu* tới task đang chạy, nên một task không ai cầm có thể bị thu
    gom giữa chừng và đợt biến mất không dấu vết.
    """

    def __init__(self, tran: int = TRAN_SO_DOT):
        self._tran = tran
        self.cac_dot: "OrderedDict[str, LanNap]" = OrderedDict()
        self._task: set = set()

    def xoa_het(self) -> None:
        self.cac_dot.clear()

    def giu_task(self, task) -> None:
        self._task.add(task)
        task.add_done_callback(self._task.discard)

    def dang_chay(self) -> LanNap | None:
        for lan in reversed(self.cac_dot.values()):
            if lan.dang_chay():
                return lan
        return None

    def moi_nhat(self) -> LanNap | None:
        return next(reversed(self.cac_dot.values()), None) if self.cac_dot else None

    def them(self, lan: LanNap) -> LanNap:
        self.cac_dot[lan.dot_id] = lan
        while len(self.cac_dot) > self._tran:
            self.cac_dot.popitem(last=False)
        return lan

    def tra(self, dot_id: str) -> LanNap:
        lan = self.cac_dot.get(dot_id)
        if lan is None:
            raise LoiMan(404, MA_DOT_KHONG_CO, f"không có đợt {dot_id!r} trong bộ nhớ tiến trình")
        return lan


QUAN_LY = QuanLyDot()


async def mo_audit() -> AuditPostgres:
    """Mở port audit cho một đợt; hàm riêng để test thay bằng bản giả."""
    audit = await AuditPostgres.mo()
    await audit.khoi_tao()
    return audit


# --- Ảnh chụp một đợt cho trang ----------------------------------------------


def anh_chup(lan: LanNap) -> dict:
    """Trạng thái đợt dạng JSON cho trang; **chỉ metadata**, không nội dung.

    Tài liệu "đang chạy" là mục có `bat_dau` mà chưa có `ket_thuc` (pipeline
    append trạng thái *trước* khi nạp). Trong lúc đó `trang_thai` của nó còn là
    `loi` theo mặc định phòng thủ của pipeline, nên trang phải đọc cờ
    `dang_chay` chứ không đọc `trang_thai` - nếu không mọi tài liệu đang chạy
    hiện thành lỗi đỏ.
    """
    chi_phi_theo_doc = {c.doc_key: c.tong for c in lan.chi_phi_tai_lieu}
    tai_lieu = []
    for t in lan.ket_qua.tai_lieu:
        dang = lan.dang_chay() and bool(t.bat_dau) and not t.ket_thuc
        tai_lieu.append(
            {
                "doc_key": t.doc_key,
                "trang_thai": t.trang_thai,
                "dang_chay": dang,
                "ma": None if dang else t.ma,
                "ly_do": "" if dang else t.ly_do,
                "re_ingest": t.re_ingest,
                "so_chunk": t.so_chunk,
                "so_hyperedge": t.so_hyperedge,
                "so_entity": t.so_entity,
                "so_fact_hop_le": t.so_fact_hop_le,
                "so_fact_loai": t.so_fact_loai,
                "so_chunk_hong": t.so_chunk_hong,
                "bat_dau": t.bat_dau,
                "ket_thuc": t.ket_thuc,
                "chi_phi": tong_chi_phi_dict(chi_phi_theo_doc.get(t.doc_key)),
            }
        )
    return {
        "dot_id": lan.dot_id,
        "space": lan.space,
        "trang_thai": lan.trang_thai,
        "bat_dau": lan.bat_dau,
        "ket_thuc": lan.ket_thuc,
        "ma_loi": lan.ma_loi,
        "thong_diep_loi": lan.thong_diep_loi,
        "tu_choi": [{"ten": tc.ten, "ma": tc.ma, "ly_do": tc.ly_do} for tc in lan.ket_qua.tu_choi],
        "tai_lieu": tai_lieu,
        "chi_phi": tong_chi_phi_dict(lan.chi_phi),
        "doi_chieu": {
            # Pipeline chạy `doi_chieu_dot` ngay sau mỗi `ainsert`; lệch là cả
            # đợt dừng. Nên "sạch" đúng bằng "đợt không dừng vì lỗi" - nhưng chỉ
            # *sau khi đợt dừng*. Đợt còn chạy thì chưa có kết luận nào, và trả
            # `True` ở đó là nói "sạch trên 0 tài liệu" ngay lúc vừa bấm Nạp;
            # `None` để tính đúng đắn của khối 4 nằm trong JSON chứ không nằm
            # trong một nhánh JavaScript không có test.
            "sach": None if lan.dang_chay() else lan.trang_thai != TRANG_THAI_DOT_LOI,
            "so_tai_lieu": len(lan.ket_qua.da_nap()),
            "ma": lan.ma_loi,
            "thong_diep": lan.thong_diep_loi,
        },
    }


# --- App ---------------------------------------------------------------------

# Không `/docs`, không `/redoc`, không `/openapi.json`: màn chỉ có ba endpoint
# và một trang, và nó chạy không xác thực - không cần thêm một mặt phơi ra.
app = FastAPI(title="hyper-rag-copilot - màn nạp", docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(LoiMan)
async def _loi_man(request: Request, loi: LoiMan) -> JSONResponse:
    """Mã lỗi API là `{error: {code, message}}` (Consistency Conventions)."""
    return JSONResponse(status_code=loi.http, content={"error": {"code": loi.ma, "message": loi.thong_diep}})


async def _chay_nen(lan: LanNap, quet, *, policy_version: str, ep_ghi_de: bool) -> None:
    """Một đợt chạy nền: mở audit, chạy pipeline, đóng audit. Không bao giờ ném."""
    audit = None
    try:
        audit = await mo_audit()
        await chay_lan_nap(
            quet,
            space=lan.space,
            policy_version=policy_version,
            audit=audit,
            lan=lan,
            ep_ghi_de=ep_ghi_de,
        )
    except asyncio.CancelledError:
        # Tiến trình màn đang tắt. Ghi trạng thái để đợt không kẹt ở `dang_chay`
        # rồi **dội tiếp**: nuốt `CancelledError` là chặn phép hủy lan lên và
        # ghi một đợt `loi` giả cho một thứ không hỏng.
        lan.trang_thai = TRANG_THAI_DOT_LOI
        lan.ma_loi = MA_DOT_BI_HUY
        lan.thong_diep_loi = "đợt bị hủy giữa chừng (tiến trình màn đang tắt)"
        raise
    except BaseException as loi:  # noqa: BLE001 - task nền nuốt lỗi là đợt treo mãi
        lan.trang_thai = TRANG_THAI_DOT_LOI
        lan.ma_loi = getattr(loi, "code", None) or type(loi).__name__
        lan.thong_diep_loi = str(loi)
        logger.exception("đợt %s dừng vì lỗi ngoài pipeline", lan.dot_id)
    finally:
        if lan.dang_chay():
            lan.trang_thai = TRANG_THAI_DOT_LOI
        if audit is not None:
            try:
                await audit.dong()
            except Exception:  # noqa: BLE001
                logger.exception("không đóng được port audit của đợt %s", lan.dot_id)


def kiem_origin(origin: str | None) -> None:
    """Từ chối request đến từ một trang khác (CSRF trên một endpoint tiêu tiền).

    Không có header `Origin` thì cho qua: đó là `curl` và các client không phải
    trình duyệt, thứ mà một trang lạ không điều khiển được.
    """
    if origin and origin not in GOC_CHO_PHEP:
        raise LoiMan(
            403,
            MA_ORIGIN_LA,
            f"Origin {origin!r} không được phép; màn chỉ nhận {sorted(GOC_CHO_PHEP)}",
        )


def _cac_ten(files: list[UploadFile]) -> list[str]:
    """Tên `doc_key` của từng part, đã làm sạch và đã chắc không trùng nhau.

    Hai file cùng tên trong một đợt thì file sau đè file trước trong thư mục
    tạm, rồi cùng một `doc_key` vào pipeline hai lần: trang hiện hai dòng cho
    một tài liệu và khối 3 cộng đôi số fact. Từ chối cả đợt rẻ hơn giải thích
    một bảng như thế.
    """
    ten = [ten_an_toan(f.filename) for f in files]
    trung = sorted({t for t in ten if ten.count(t) > 1})
    if trung:
        raise LoiMan(
            400,
            MA_TEN_FILE_TRUNG,
            f"hai file trở lên cùng tên sau khi cắt đường dẫn: {trung};"
            " tên file là doc_key nên một đợt không mang hai tài liệu cùng tên",
        )
    return ten


def _kiem_space(space: str) -> str:
    """`space` là tên collection Qdrant và nhãn Neo4j, không phải một ô chữ tự do.

    Màn không có đường xóa, nên một `space` gõ nhầm là một không gian mới nằm
    lại trong hai kho mà chỉ CLI dọn được. Kiểm bằng đúng luật của `core/`.
    """
    try:
        return validate_space(space)
    except (TypeError, ValueError) as loi:
        raise LoiMan(400, MA_SPACE_LA, f"space không hợp lệ: {loi}") from loi


async def _ghi_mot_part(f: UploadFile, dich: Path) -> None:
    """Ghi một part ra đĩa, dừng ở trần+1 byte.

    Đọc tiếp phần đuôi của một file vượt trần là tốn đĩa cho một thứ chắc chắn
    bị từ chối; một byte dôi ra là đủ để `stat` của cửa quét thấy vượt trần.
    """
    con_lai = KICH_THUOC_TOI_DA + 1
    with dich.open("wb") as ra:
        while con_lai > 0 and (khoi := await f.read(min(KHOI_DOC, con_lai))):
            ra.write(khoi)
            con_lai -= len(khoi)


@app.post("/api/nap", status_code=201)
async def nap(
    request: Request,
    # `UploadFile | str` chứ không chỉ `UploadFile`: trình duyệt gửi một part
    # `filename=""` khi chưa chọn file (Starlette dựng nó thành `UploadFile`
    # tên rỗng), còn một số client gửi cùng chỗ đó như một trường chữ. Kiểu
    # hẹp làm cả hai ca thành 422 - một mã không nằm trong hợp đồng của màn.
    files: list[UploadFile | str] | None = File(default=None),
    space: str = Form(default=SPACE_MAC_DINH),
    ep_ghi_de: bool = Form(default=False),
) -> dict:
    """Nhận file tải lên, quét, rồi mở đúng một đợt chạy nền.

    File được ghi vào một thư mục tạm rồi quét ngay tại chỗ: `quet_cac_file`
    đọc trọn thân tài liệu vào `TaiLieuNguon`, nên thư mục tạm không cần sống
    qua đợt và bị dọn trước khi đợt bắt đầu.
    """
    kiem_origin(request.headers.get("origin"))
    # Mọi phép kiểm dưới đây và việc *giữ chỗ* đợt phải nằm trọn trong một lượt
    # của event loop, không có `await` xen giữa: có `await` thì hai POST gần nhau
    # cùng qua được cửa 409, và cái thứ hai chỉ vỡ muộn hơn ở `KhoaIngest`.
    if QUAN_LY.dang_chay() is not None:
        raise LoiMan(409, MA_DOT_DANG_CHAY, "một đợt đang chạy; đợi nó xong rồi nạp tiếp")
    # Trình duyệt gửi một part `filename=""` khi người dùng bấm Nạp mà chưa chọn
    # file. Lọc nó ra *trước* khi hỏi "có file nào không", nếu không thì "không
    # chọn file" hiện ra mã `TEN_FILE_LA` thay vì `KHONG_CO_FILE`.
    # Lọc theo *hình dạng* chứ không theo lớp: pydantic trao lại
    # `starlette.datastructures.UploadFile`, mà `fastapi.UploadFile` là lớp con
    # của nó - một phép `isinstance(f, fastapi.UploadFile)` vì thế trả False cho
    # mọi file thật và biến đợt nào cũng thành `KHONG_CO_FILE`.
    files = [
        f
        for f in (files or [])
        if not isinstance(f, str) and (getattr(f, "filename", "") or "").strip()
    ]
    if not files:
        raise LoiMan(400, MA_KHONG_CO_FILE, "không có file nào trong yêu cầu")
    space = _kiem_space(space)
    # Làm sạch mọi tên *trước* khi ghi byte nào: một tên lạ là một file hỏng, và
    # không có lý do gì để nó chạm đĩa - hay để nó mở một đợt.
    ten = _cac_ten(files)
    lan = QUAN_LY.them(LanNap(space=space))

    try:
        with tempfile.TemporaryDirectory(prefix="man_nap_") as thu_muc:
            goc = Path(thu_muc)
            duong_dan = []
            for f, t in zip(files, ten):
                dich = goc / t
                await _ghi_mot_part(f, dich)
                duong_dan.append(dich)
            # `quet_cac_file` đọc trọn thân tài liệu vào `TaiLieuNguon`, nên thư
            # mục tạm không cần sống qua đợt và được dọn ngay tại đây.
            quet = quet_cac_file(duong_dan)
        policy = load_policy(POLICY_MAC_DINH)
    except Exception as loi:
        # Chỗ đã giữ phải được trả lại, nếu không màn kẹt ở "đang chạy" mãi. Và
        # câu trả lời phải theo hợp đồng `{error: {code, message}}`: một 500
        # trần làm JS vỡ ở `r.json()` thay vì hiện được lý do.
        lan.trang_thai = TRANG_THAI_DOT_LOI
        lan.ma_loi = getattr(loi, "code", None) or type(loi).__name__
        lan.thong_diep_loi = str(loi)
        lan.bat_dau = lan.ket_thuc = thoi_diem_utc()
        logger.exception("đợt %s hỏng trước khi chạy", lan.dot_id)
        raise LoiMan(500, lan.ma_loi, lan.thong_diep_loi) from loi

    QUAN_LY.giu_task(
        asyncio.create_task(
            _chay_nen(lan, quet, policy_version=policy.policy_version, ep_ghi_de=ep_ghi_de)
        )
    )
    return anh_chup(lan)


# Khai trước `/api/dot/{dot_id}`: FastAPI khớp route theo thứ tự khai, nên đảo
# hai dòng này lại thì `moi-nhat` bị nuốt thành một `dot_id`.
@app.get("/api/dot/moi-nhat")
async def dot_moi_nhat() -> dict:
    """Đợt gần nhất, để trang tải lại giữa chừng bám lại được đợt đang chạy."""
    lan = QUAN_LY.moi_nhat()
    if lan is None:
        raise LoiMan(404, MA_DOT_KHONG_CO, "chưa có đợt nào trong tiến trình màn")
    return anh_chup(lan)


@app.get("/api/dot/{dot_id}")
async def dot_theo_id(dot_id: str) -> dict:
    return anh_chup(QUAN_LY.tra(dot_id))


@app.get("/", response_class=HTMLResponse)
async def trang() -> HTMLResponse:
    return HTMLResponse(TRANG_HTML)


# --- Trang HTML --------------------------------------------------------------
#
# Nhúng thẳng vào module, không file tĩnh: một trang một file là thứ đọc được
# hết trong một lần cuộn, và không có tài nguyên ngoài nào để đi lạc khi image
# được build. Không CDN, không thư viện: container `api` không ra mạng.

_CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, "Segoe UI", sans-serif; margin: 0; padding: 24px;
       background: #f6f7f9; color: #16191d; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 0 0 8px; }
p.phu { color: #5a6069; margin: 0 0 18px; font-size: 13px; }
.hop { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
       padding: 16px; margin-bottom: 16px; }
button { font: inherit; padding: 6px 14px; border-radius: 6px; border: 1px solid #b7bec8;
         background: #eef1f4; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
label.o { display: inline-block; margin-right: 16px; }
input[type=text] { font: inherit; padding: 4px 8px; border: 1px solid #b7bec8; border-radius: 6px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #dfe3e8; padding: 5px 7px; text-align: left; vertical-align: top; }
th { background: #eef1f4; font-weight: 600; }
td.so { text-align: right; font-variant-numeric: tabular-nums; }
.nhan { display: inline-block; font-size: 12px; padding: 1px 7px; border-radius: 10px;
        background: #e8eaee; margin-right: 5px; }
.nhan.chay { background: #fff3bf; }
.nhan.nap { background: #d9f0dd; }
.nhan.giu { background: #e4e7eb; }
.nhan.loi { background: #ffd9d9; }
.nhan.ghide { background: #ffe6cc; }
.sach { color: #1f7a37; }
.lech { color: #a11; }
code { font-size: 12px; color: #5a6069; }
"""

_JS = """
// `TT` do Python nhung vao ngay truoc khoi nay (xem `_HANG_TRANG_THAI`): ten
// trang thai chi khai mot noi, o `adapters/ingest.py` va `api/dot_nap.py`.
const $ = (id) => document.getElementById(id);
// Quá số lần hỏng liên tiếp này thì dừng poll: đợt đã bị đẩy khỏi sổ (trần
// TRAN_SO_DOT) hoặc tiến trình màn đã restart, và quay mãi mỗi 3 giây chỉ làm
// trang trông như đang sống trong khi nó đã mất dấu.
const TRAN_HONG = 10;
let dotId = null, hen = null, hongLienTiep = 0;

function baoLoi(chu) { $('loi').textContent = chu; }

function henLai(ms) { if (hen) { clearTimeout(hen); } hen = setTimeout(poll, ms); }

// Phản hồi không phải JSON (500 trần của uvicorn, 502 của một proxy) không được
// thành một ngoại lệ nuốt im ở `r.json()`.
async function docJson(r) { try { return await r.json(); } catch (e) { return null; } }

function moTaLoi(r, d) {
  return (d && d.error) ? (d.error.code + ' - ' + d.error.message) : ('HTTP ' + r.status);
}

function nhan(lop, chu) { return '<span class="nhan ' + lop + '">' + chu + '</span>'; }

function nhanTrangThai(t) {
  if (t.dang_chay) return nhan('chay', 'ĐANG CHẠY');
  if (t.trang_thai === TT.da_nap) return nhan('nap', 'NẠP');
  if (t.trang_thai === TT.khong_doi) return nhan('giu', 'KHÔNG ĐỔI');
  if (t.trang_thai === TT.tu_choi) return nhan('loi', 'TỪ CHỐI');
  if (t.trang_thai === TT.da_xoa) return nhan('giu', 'XÓA');
  return nhan('loi', 'LỖI');
}

function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function usd(x) { return (x === null || x === undefined) ? '-' : x.toFixed(6).replace('.', ','); }

function veTaiLieu(d) {
  if (!d.tai_lieu.length) return '<p>chưa tài liệu nào vào lượt.</p>';
  let h = '<table><tr><th>tài liệu</th><th>trạng thái</th><th>chunk</th><th>hyperedge</th>'
        + '<th>entity</th><th>fact hợp lệ</th><th>fact loại</th><th>chunk hỏng</th>'
        + '<th>token vào</th><th>token ra</th><th>USD</th><th>ghi chú</th></tr>';
  for (const t of d.tai_lieu) {
    const cp = t.chi_phi;
    h += '<tr><td>' + esc(t.doc_key) + '</td><td>' + nhanTrangThai(t)
       + (t.re_ingest ? nhan('ghide', 'GHI ĐÈ') : '')
       + '</td><td class="so">' + t.so_chunk + '</td><td class="so">' + t.so_hyperedge
       + '</td><td class="so">' + t.so_entity + '</td><td class="so">' + t.so_fact_hop_le
       + '</td><td class="so">' + t.so_fact_loai + '</td><td class="so">' + t.so_chunk_hong
       + '</td><td class="so">' + (cp ? cp.token_vao : '-') + '</td><td class="so">'
       + (cp ? cp.token_ra : '-') + '</td><td class="so">' + (cp ? usd(cp.chi_phi_usd) : '-')
       + '</td><td>' + (t.ma ? '<code>' + esc(t.ma) + '</code> ' : '') + esc(t.ly_do) + '</td></tr>';
  }
  return h + '</table>';
}

function veTuChoi(d) {
  if (!d.tu_choi.length) return '<p>không file nào bị từ chối ở cửa quét.</p>';
  let h = '<table><tr><th>file</th><th>mã</th><th>lý do</th></tr>';
  for (const t of d.tu_choi) {
    h += '<tr><td>' + esc(t.ten) + '</td><td><code>' + esc(t.ma) + '</code></td><td>'
       + esc(t.ly_do) + '</td></tr>';
  }
  return h + '</table>';
}

function veFact(d) {
  let hl = 0, lo = 0, hong = 0, he = 0;
  for (const t of d.tai_lieu) { hl += t.so_fact_hop_le; lo += t.so_fact_loai; hong += t.so_chunk_hong; he += t.so_hyperedge; }
  const tong = hl + lo;
  const ty = tong ? (100 * lo / tong).toFixed(1).replace('.', ',') + '%' : '-';
  return '<p>' + hl + ' fact hợp lệ, ' + lo + ' fact bị loại (tỷ lệ loại ' + ty + '), '
       + hong + ' chunk không đọc được, ' + he + ' hyperedge đã ghi.</p>';
}

function veDoiChieu(d) {
  const dc = d.doi_chieu;
  // `sach === null` là "đợt còn chạy, chưa có kết luận" - do JSON quyết, không
  // do JavaScript suy ra từ trạng thái đợt.
  if (dc.sach === null || dc.sach === undefined)
    return '<p>chưa có kết luận; đối chiếu chạy sau mỗi tài liệu.</p>';
  if (dc.sach) return '<p class="sach">sạch trên ' + dc.so_tai_lieu + ' tài liệu đã nạp.</p>';
  return '<p class="lech">LỆCH - <code>' + esc(dc.ma) + '</code> ' + esc(dc.thong_diep) + '</p>';
}

function veChiPhi(d) {
  if (!d.chi_phi) return '<p>chưa có số; chi phí gom khi đợt kết thúc.</p>';
  let h = '<table><tr><th>model</th><th>provider</th><th>lần</th><th>token vào</th>'
        + '<th>token ra</th><th>USD</th></tr>';
  for (const m of d.chi_phi.theo_model) {
    h += '<tr><td>' + esc(m.model) + '</td><td>' + esc(m.nha_cung_cap) + '</td><td class="so">'
       + m.so_lan + '</td><td class="so">' + m.token_vao + '</td><td class="so">' + m.token_ra
       + '</td><td class="so">' + usd(m.chi_phi_usd) + '</td></tr>';
  }
  h += '<tr><th>TỔNG</th><th></th><th class="so">' + d.chi_phi.so_lan + '</th><th class="so">'
     + d.chi_phi.token_vao + '</th><th class="so">' + d.chi_phi.token_ra + '</th><th class="so">'
     + usd(d.chi_phi.chi_phi_usd) + '</th></tr>';
  return h + '</table>';
}

function moc(d) {
  // Phản hồi 201 trả ảnh chụp lúc đợt vừa được giữ chỗ, chưa có `bat_dau`.
  const a = d.bat_dau ? 'bắt đầu ' + esc(d.bat_dau) : 'chưa có mốc bắt đầu';
  return '<br>' + a + (d.ket_thuc ? ', kết thúc ' + esc(d.ket_thuc) : '');
}

function ve(d) {
  dotId = d.dot_id;
  const chay = d.trang_thai === TT.dot_dang_chay;
  $('dot').innerHTML = 'đợt <code>' + esc(d.dot_id) + '</code>, space <code>' + esc(d.space)
    + '</code>, trạng thái ' + (chay ? nhan('chay', 'ĐANG CHẠY')
      : d.trang_thai === TT.dot_xong ? nhan('nap', 'XONG') : nhan('loi', 'LỖI'))
    + (d.ma_loi ? ' <code>' + esc(d.ma_loi) + '</code> ' + esc(d.thong_diep_loi) : '')
    + moc(d);
  $('tai_lieu').innerHTML = veTaiLieu(d);
  $('tu_choi').innerHTML = veTuChoi(d);
  $('fact').innerHTML = veFact(d);
  $('doi_chieu').innerHTML = veDoiChieu(d);
  $('chi_phi').innerHTML = veChiPhi(d);
  $('nut').disabled = chay;
  // Đúng một hẹn giờ sống tại một thời điểm: không dọn cái cũ là hai vòng poll
  // chạy song song sau vài lần vẽ.
  if (hen) { clearTimeout(hen); hen = null; }
  if (chay) { hen = setTimeout(poll, 1500); }
}

function matDau(chu) { baoLoi('mất dấu đợt: ' + chu + '. Tải lại trang để xem đợt mới nhất.'); }

async function poll() {
  if (!dotId) return;
  const id = dotId;
  let r;
  try {
    r = await fetch('/api/dot/' + id);
  } catch (e) {
    hongLienTiep += 1;
    if (hongLienTiep > TRAN_HONG) { matDau('không gọi được màn (' + e + ')'); return; }
    henLai(3000);
    return;
  }
  // Một đợt mới đã lên ngôi trong lúc phản hồi này đang bay: bỏ nó, đừng vẽ
  // lại đợt cũ đè lên đợt đang chạy.
  if (id !== dotId) { return; }
  if (!r.ok) {
    hongLienTiep += 1;
    const d = await docJson(r);
    if (hongLienTiep > TRAN_HONG) { matDau(moTaLoi(r, d)); return; }
    henLai(3000);
    return;
  }
  const d = await docJson(r);
  if (!d || d.dot_id !== dotId) { return; }
  hongLienTiep = 0;
  ve(d);
}

async function bamLai() {
  try {
    const r = await fetch('/api/dot/moi-nhat');
    if (!r.ok) { return; }             // 404 lúc chưa có đợt nào là chuyện thường
    const d = await docJson(r);
    if (d) { ve(d); }
  } catch (e) {
    baoLoi('không gọi được màn: ' + e);
  }
}

async function gui(ev) {
  ev.preventDefault();
  if (hen) { clearTimeout(hen); hen = null; }
  dotId = null;                        // vô hiệu mọi phản hồi poll đang bay
  hongLienTiep = 0;
  baoLoi('');
  $('nut').disabled = true;
  let r;
  try {
    r = await fetch('/api/nap', { method: 'POST', body: new FormData($('form')) });
  } catch (e) {
    baoLoi('không gửi được: ' + e);
    $('nut').disabled = false;
    return;
  }
  const d = await docJson(r);
  if (!r.ok || !d) {
    baoLoi(moTaLoi(r, d));
    $('nut').disabled = false;
    return;
  }
  ve(d);
}

window.addEventListener('DOMContentLoaded', () => {
  $('form').addEventListener('submit', gui);
  bamLai();
});
"""

# Hằng trạng thái đưa xuống JS: trang so sánh bằng chính chuỗi mà pipeline
# ghi ra, không phải một bản chép tay trong JavaScript.
_HANG_TRANG_THAI: str = json.dumps(
    {
        "da_nap": TRANG_THAI_DA_NAP,
        "khong_doi": TRANG_THAI_KHONG_DOI,
        "da_xoa": TRANG_THAI_DA_XOA,
        "tu_choi": TRANG_THAI_TU_CHOI,
        "dot_dang_chay": TRANG_THAI_DOT_DANG_CHAY,
        "dot_xong": TRANG_THAI_DOT_XONG,
        "dot_loi": TRANG_THAI_DOT_LOI,
    },
    ensure_ascii=False,
)

TRANG_HTML: str = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Màn nạp tài liệu - hyper-rag-copilot</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Màn nạp tài liệu</h1>
<p class="phu">Chỉ chạy trên loopback của máy chủ, không xác thực, không nằm trong đường demo.
Nhận <code>.md</code> và <code>.txt</code> có frontmatter <code>scope</code> / <code>content_type</code>.
Tên file là <code>doc_key</code>: nạp lại cùng tên là ghi đè.</p>

<div class="hop">
  <form id="form">
    <label class="o">file <input type="file" name="files" multiple accept=".md,.txt"></label>
    <label class="o">space <input type="text" name="space" value="synth" size="8"></label>
    <label class="o"><input type="checkbox" name="ep_ghi_de" value="true"> ép ghi đè</label>
    <button id="nut" type="submit">Nạp</button>
  </form>
  <p class="lech" id="loi"></p>
</div>

<div class="hop"><h2>Đợt</h2><div id="dot">chưa có đợt nào.</div></div>
<div class="hop"><h2>1. Tiến trình từng tài liệu</h2><div id="tai_lieu"></div></div>
<div class="hop"><h2>2. File bị từ chối</h2><div id="tu_choi"></div></div>
<div class="hop"><h2>3. Fact trích được / bị loại</h2><div id="fact"></div></div>
<div class="hop"><h2>4. Đối chiếu hai kho</h2><div id="doi_chieu"></div></div>
<div class="hop"><h2>Chi phí cả đợt</h2><div id="chi_phi"></div></div>

<script>const TT = {_HANG_TRANG_THAI};
{_JS}</script>
</body>
</html>
"""

__all__ = ["app", "QUAN_LY", "QuanLyDot", "LoiMan", "anh_chup", "kiem_origin", "ten_an_toan"]
