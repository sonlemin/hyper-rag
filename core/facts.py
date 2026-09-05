"""Lược đồ fact 8 vai slot, mã loại, id mờ và câu render (story 2.4, FR-02/FR-04).

Một fact là một object JSON `{vai: giá trị}` với khóa nằm trong danh mục
`core.slots.SLOT_ROLES`. Đây là chỗ *duy nhất* nói fact hợp lệ trông thế nào:
prompt trích xuất (`adapters/trich_xuat.py`) mô tả lược đồ này cho LLM, bộ
validator ở đây kiểm đầu ra, và bộ test đối chiếu cả hai bằng cùng một hằng.
Tên vai không viết lại ở đâu khác.

Ba thứ sống ở đây, và vì sao chúng ở `core/`:

- **Lược đồ và mã loại.** Bản ghi sai lược đồ bị loại *kèm mã*, không bao giờ
  loại thầm lặng: FR-02 đòi đếm được tỷ lệ loại, và một bản ghi biến mất mà
  không ai đếm là một con số sai ở báo cáo. Mã ổn định để pipeline gom theo mã
  và test assert trên mã, không trên thông điệp.
- **Id mờ của hyperedge.** `id_fact(slots)` là `he-` cộng 24 hex của sha256
  trên JSON chuẩn hóa của slot. Id này vừa là id node graph, vừa là payload
  `hyperedge_name` của kho vector, vừa là thứ upstream đổ vào cột `hyperedge`
  của bảng Relationships gửi LLM ở mức L1 (`operate.py:944,953`). Trước 2.4
  chỗ đó là nguyên văn câu fact, tức một vai ở L1 nhận trọn `cause` và
  `remediation` mà đường graph vừa che (lỗ rò ledger 1.6/1.7). Id không mang
  nội dung nên lỗ đóng ở cả global và local mode mà tầng che không đổi chữ ký.
  Băm theo *nội dung* (giá trị đã chuẩn hóa, thứ tự vai cố định) nên cùng một
  fact ở hai tài liệu là một node - đúng thứ re-ingest và hợp nhất khóa cần.
- **Câu render.** `cau_fact(slots)` là câu tiếng Việt dựng từ slot đã điền,
  dùng làm `content` nhúng của point hyperedge (recall vector không mất) và để
  dựng lại content khi re-ingest từ cạnh của graph. Payload không giữ nó
  (adapter Qdrant chặn `content` từ 1.3), node hyperedge không giữ nó, audit
  không giữ nó.

Từ story 2.12 có thêm `ap_bi_danh(slots, bang)`, phần *kiểm được* của chuẩn hóa
thực thể (FR-32): nó chạy giữa `kiem_fact` và `id_fact` để hai cách viết của
cùng một thực thể cho cùng một id. Nó ở đây chứ không ở `adapters/` vì nó đứng
đúng giữa hai hàm trên và dùng chung `chuan_hoa_gia_tri` với chúng; phần *đọc*
bảng từ điển (YAML, ràng scope, dấu người xác nhận) thì ở
`adapters/tu_dien_thuc_the.py`.

Chỉ stdlib và chính `core/` (import-lint canh).
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from core.slots import SLOT_ROLE_SET, SLOT_ROLES

# Độ dài tối đa một giá trị slot (ký tự, sau chuẩn hóa). Slot là một cụm ngắn
# trích sát văn bản; dài hơn là LLM chép cả đoạn vào một vai, thứ vừa làm entity
# vô nghĩa vừa kéo nguyên văn chunk vào kho ở ngưỡng L1.
GIA_TRI_TOI_DA: int = 300

# Tiền tố id node hyperedge. Không trùng tiền tố id vector của upstream (`rel-`,
# `ent-`, `chunk-`, `doc-`) để một id đọc ra là biết nó thuộc kho nào.
TIEN_TO_ID_FACT: str = "he-"
SO_HEX_ID_FACT: int = 24

# Mã loại ở cấp *fact*: loại một bản ghi, chunk vẫn tiếp.
MA_KHONG_PHAI_OBJECT: str = "KHONG_PHAI_OBJECT"
MA_VAI_LA: str = "VAI_LA"
MA_THIEU_SUBJECT: str = "THIEU_SUBJECT"
MA_IT_HON_HAI_VAI: str = "IT_HON_HAI_VAI"
MA_GIA_TRI_SAI_KIEU: str = "GIA_TRI_SAI_KIEU"
MA_GIA_TRI_RONG: str = "GIA_TRI_RONG"
MA_GIA_TRI_QUA_DAI: str = "GIA_TRI_QUA_DAI"
MA_LOAI_FACT: frozenset[str] = frozenset(
    {
        MA_KHONG_PHAI_OBJECT,
        MA_VAI_LA,
        MA_THIEU_SUBJECT,
        MA_IT_HON_HAI_VAI,
        MA_GIA_TRI_SAI_KIEU,
        MA_GIA_TRI_RONG,
        MA_GIA_TRI_QUA_DAI,
    }
)

# Mã loại ở cấp *chunk*: cả phản hồi bị loại, không có bản ghi nào để đếm.
MA_KHONG_PHAI_JSON: str = "KHONG_PHAI_JSON"
MA_THIEU_FACTS: str = "THIEU_FACTS"
MA_LOAI_CHUNK: frozenset[str] = frozenset({MA_KHONG_PHAI_JSON, MA_THIEU_FACTS})

# Khóa của object phản hồi mang danh sách fact.
KHOA_FACTS: str = "facts"

# Vai bắt buộc: một fact không có chủ thể thì không nói về cái gì.
VAI_BAT_BUOC: str = "subject"
SO_VAI_TOI_THIEU: int = 2

# Nhãn tiếng Việt của từng vai, khóa đúng bằng `SLOT_ROLE_SET` (test canh).
# Dùng ở câu render và ở prompt; nhãn hiển thị của `web/` map từ đây.
TEN_VAI_TIENG_VIET: Mapping[str, str] = MappingProxyType(
    {
        "subject": "chủ thể",
        "symptom": "triệu chứng",
        "cause": "nguyên nhân",
        "condition": "điều kiện",
        "remediation": "cách xử lý",
        "source": "nguồn",
        "time": "thời gian",
        "owner": "người phụ trách",
    }
)


def chuan_hoa_gia_tri(gia_tri: str) -> str:
    """NFC, gộp khoảng trắng, bỏ dấu nháy kép bao quanh, cắt hai đầu.

    Cùng ba bước với `core.ids.normalize_id` cộng bước gộp khoảng trắng, để
    giá trị đã qua đây đi vào `normalize_id` (id entity) là một phép đồng nhất:
    id fact và id entity không thể lệch nhau vì một dấu cách. Chuỗi rỗng trả
    về rỗng thay vì nổ, để `kiem_fact` gắn đúng mã `GIA_TRI_RONG`.
    """
    ten = " ".join(unicodedata.normalize("NFC", gia_tri).split())
    while len(ten) >= 2 and ten[0] == '"' and ten[-1] == '"':
        ten = ten[1:-1].strip()
    return ten


def kiem_fact(obj) -> tuple[dict[str, str] | None, str | None]:
    """Kiểm một bản ghi: `(slots đã chuẩn hóa, None)` hoặc `(None, mã loại)`.

    Thứ tự kiểm: hình dạng object, tên vai, kiểu và độ dài từng giá trị, rồi
    hai luật cấu trúc (có `subject`, ít nhất hai vai). Sai một điều là loại cả
    fact với mã của điều sai *đầu tiên* gặp theo thứ tự đó; không có nhánh
    "sửa hộ" nào (bỏ vai rỗng rồi giữ phần còn lại), vì sửa hộ là một quyết
    định về nội dung mà validator không có quyền đưa ra.
    """
    if not isinstance(obj, Mapping):
        return None, MA_KHONG_PHAI_OBJECT
    slots: dict[str, str] = {}
    for vai, gia_tri in obj.items():
        if vai not in SLOT_ROLE_SET:
            return None, MA_VAI_LA
        if not isinstance(gia_tri, str):
            return None, MA_GIA_TRI_SAI_KIEU
        gon = chuan_hoa_gia_tri(gia_tri)
        # Không có ký tự chữ/số nào (`"""`, `---`, `...`) cũng là rỗng: một
        # entity tên `---` không nói về gì và không nhúng được thành gì.
        if not gon or not any(ch.isalnum() for ch in gon):
            return None, MA_GIA_TRI_RONG
        if len(gon) > GIA_TRI_TOI_DA:
            return None, MA_GIA_TRI_QUA_DAI
        slots[vai] = gon
    if VAI_BAT_BUOC not in slots:
        return None, MA_THIEU_SUBJECT
    if len(slots) < SO_VAI_TOI_THIEU:
        return None, MA_IT_HON_HAI_VAI
    return slots, None


def ap_bi_danh(
    slots: Mapping[str, str], bang: Mapping[str, str]
) -> dict[str, str]:
    """Thay giá trị slot là **bí danh** bằng tên chuẩn của nó, đúng một bước.

    Đây là phần *kiểm được* của chuẩn hóa thực thể (story 2.12, FR-32). Từ điển
    cũng đi vào prompt, nhưng lời dặn trong prompt là gợi ý: LLM được phép bỏ
    qua nó, và khi đó `App01` với `app01.company.vn` lại thành hai id entity.
    Phép áp ở đây chạy **sau** `kiem_fact` và **trước** `id_fact`, nên hai cách
    viết cho đúng một `id_fact` bất kể LLM trả về cách nào.

    Ba luật, mỗi luật là một quyết định:

    - **Khớp trọn giá trị, không khớp chuỗi con.** Vai mang thực thể (`subject`,
      `owner`, `source`) là một cụm ngắn nên khớp trọn là đủ; vai mệnh đề
      (`cause`, `remediation`) là một mệnh đề trong chính nhãn tay của bộ vàng
      2.5, và thay chuỗi con bên trong nó là viết lại câu của người gán nhãn.
    - **Đúng một bước.** `bang` là bảng đã kiểm của
      `adapters/tu_dien_thuc_the.py`, nơi từ chối một bí danh cũng là tên chuẩn
      của mục khác. Không lặp cho tới điểm bất động ở đây: một bảng do người sửa
      dần sẽ có ngày tạo vòng lặp, và một phép áp nhiều bước làm kết quả phụ
      thuộc thứ tự duyệt.
    - **Khóa tra đi qua `chuan_hoa_gia_tri`.** Cùng hàm mà `kiem_fact` và
      `_json_chuan_hoa` dùng, và nó đồng nhất với `core.ids.normalize_id`. Bảng
      tra bằng một hàm khác là một bí danh trượt vì một dấu cách.

    Hàm thuần: trả dict mới, không sửa `slots`. `bang` rỗng là hàm đồng nhất -
    đó là ca "không khai từ điển" của I/O Matrix, và nó phải không đổi một byte.
    """
    if not bang:
        return dict(slots)
    ra: dict[str, str] = {}
    for vai, gia_tri in slots.items():
        if isinstance(gia_tri, str):
            ra[vai] = bang.get(chuan_hoa_gia_tri(gia_tri), gia_tri)
        else:
            ra[vai] = gia_tri
    return ra


@dataclass(frozen=True)
class KetQuaPhanTich:
    """Kết quả đọc một phản hồi LLM cho một chunk.

    `facts` là các fact hợp lệ (slot đã chuẩn hóa), `loai_theo_ma` đếm mọi
    thứ bị loại (cả cấp fact lẫn cấp chunk), `chunk_hong` nói cả chunk bị loại
    (không parse được, thiếu `facts`), `so_ban_ghi` là số bản ghi thô LLM trả
    (0 khi chunk hỏng). Bất biến: `len(facts) + tổng mã cấp fact == so_ban_ghi`.
    """

    facts: tuple[dict[str, str], ...] = ()
    loai_theo_ma: Mapping[str, int] = field(default_factory=dict)
    chunk_hong: bool = False
    so_ban_ghi: int = 0

    def __post_init__(self):
        object.__setattr__(self, "facts", tuple(dict(f) for f in self.facts))
        object.__setattr__(self, "loai_theo_ma", MappingProxyType(dict(self.loai_theo_ma)))


def _bo_rao_ma(text: str) -> str:
    """Gỡ một lớp rào ```json ... ``` nếu có; JSON mode sạch thì không đổi gì."""
    gon = text.strip()
    if gon.startswith("```"):
        dong = gon.split("\n")
        if len(dong) >= 2 and dong[-1].strip() == "```":
            gon = "\n".join(dong[1:-1]).strip()
    return gon


def phan_tich_phan_hoi(text) -> KetQuaPhanTich:
    """Đọc phản hồi của một chunk: parse JSON, tìm `facts`, kiểm từng bản ghi.

    Không parse được hay không phải object là `KHONG_PHAI_JSON`; object mà
    thiếu `facts` hoặc `facts` không phải danh sách là `THIEU_FACTS`. Hai mã đó
    loại cả chunk và đếm một lần. Danh sách rỗng là chunk *hợp lệ* không có
    fact, không phải chunk hỏng - LLM được phép nói "đoạn này không có gì".
    """
    if not isinstance(text, str):
        return KetQuaPhanTich(chunk_hong=True, loai_theo_ma={MA_KHONG_PHAI_JSON: 1})
    try:
        raw = json.loads(_bo_rao_ma(text))
    except (json.JSONDecodeError, RecursionError):
        return KetQuaPhanTich(chunk_hong=True, loai_theo_ma={MA_KHONG_PHAI_JSON: 1})
    if not isinstance(raw, dict):
        return KetQuaPhanTich(chunk_hong=True, loai_theo_ma={MA_THIEU_FACTS: 1})
    ban_ghi = raw.get(KHOA_FACTS)
    if not isinstance(ban_ghi, list):
        return KetQuaPhanTich(chunk_hong=True, loai_theo_ma={MA_THIEU_FACTS: 1})
    facts: list[dict[str, str]] = []
    dem: dict[str, int] = {}
    for obj in ban_ghi:
        slots, ma = kiem_fact(obj)
        if ma is not None:
            dem[ma] = dem.get(ma, 0) + 1
        else:
            facts.append(slots)
    return KetQuaPhanTich(facts=tuple(facts), loai_theo_ma=dem, so_ban_ghi=len(ban_ghi))


def _json_chuan_hoa(slots: Mapping[str, str]) -> str:
    """JSON `{vai: giá trị chuẩn hóa}` theo thứ tự `SLOT_ROLES`, không khoảng trắng.

    Thứ tự vai lấy từ danh mục chứ không sắp theo chữ cái, để id không đổi nếu
    một ngày ai đó đổi cách sắp xếp mặc định của `json.dumps`.
    """
    la = set(slots) - SLOT_ROLE_SET
    if la:
        raise ValueError(f"vai ngoài danh mục 8 vai: {sorted(la)}")
    chuan: dict[str, str] = {}
    for vai in SLOT_ROLES:
        if vai in slots:
            gia_tri = slots[vai]
            if not isinstance(gia_tri, str):
                raise TypeError(f"giá trị của vai {vai!r} phải là chuỗi, nhận được {type(gia_tri).__name__}")
            chuan[vai] = chuan_hoa_gia_tri(gia_tri)
    return json.dumps(chuan, ensure_ascii=False, separators=(",", ":"))


def id_fact(slots: Mapping[str, str]) -> str:
    """Id node hyperedge, mờ: `he-` + 24 hex đầu của sha256(JSON chuẩn hóa).

    24 hex là 96 bit: đủ để hai fact khác nhau trong một kho vài chục nghìn
    hyperedge không trùng, và ngắn để đọc được trong log. Id không mang chữ nào
    của giá trị slot; đó là toàn bộ lý do nó tồn tại.
    """
    bam = hashlib.sha256(_json_chuan_hoa(slots).encode("utf-8")).hexdigest()
    return TIEN_TO_ID_FACT + bam[:SO_HEX_ID_FACT]


def cau_fact(slots: Mapping[str, str | Sequence[str]]) -> str:
    """Câu tiếng Việt dựng từ slot đã điền, theo thứ tự `SLOT_ROLES`.

    Nhận cả giá trị đơn lẫn danh sách giá trị cho một vai (hình dạng mà
    `slot_cua_hyperedge` của adapter graph trả về khi dựng lại content). Vai
    vắng hay rỗng bị bỏ; không slot nào thì chuỗi rỗng, nơi gọi tự quyết.
    Không phải văn tự nhiên trau chuốt: đây là văn bản để nhúng và để người đọc
    log nhận ra fact, không phải câu trả lời cho người dùng.
    """
    phan: list[str] = []
    for vai in SLOT_ROLES:
        if vai not in slots:
            continue
        gia_tri = slots[vai]
        if isinstance(gia_tri, str):
            van_ban = chuan_hoa_gia_tri(gia_tri)
        else:
            van_ban = ", ".join(chuan_hoa_gia_tri(str(g)) for g in gia_tri if str(g).strip())
        if not van_ban:
            continue
        phan.append(f"{TEN_VAI_TIENG_VIET[vai]}: {van_ban}")
    return "; ".join(phan)
