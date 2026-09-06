"""Bộ vàng trích xuất: lược đồ, loader và mẫu số của R2 (story 2.5, FR-02).

`eval/bo_vang_trich_xuat.json` là nhãn tay cho 10 tài liệu lõi trong
`eval/data/`. Module này đọc nó, kiểm nó bằng *chính* `core.facts` và
`core.slots` mà đường trích xuất thật dùng, rồi trả mẫu số cho phép chấm
precision/recall của story 2.6.

Bốn điều quyết định mọi thứ ở đây:

- **Đơn vị chấm là slot đã điền** (PRD 2.6). Một fact 8 vai và một fact 2 vai
  không cùng khối lượng thông tin, nên đếm theo fact làm phép đo mù với chuyện
  bỏ sót vai - đúng thứ mà ma trận lẫn lộn A13 hỏi. `mau_so_slot()` vì thế
  cộng số slot, không cộng số fact.
- **Tài liệu few-shot bị loại khỏi mẫu số.** `adapters/trich_xuat.VI_DU_DAU_RA`
  lấy fact nguyên từ `01-cap-quyen-gitlab.txt` và `05-bao-cao-su-co-inc-1208.txt`,
  nên prompt đã "thấy" hai tài liệu đó; chấm trên chúng là chấm trí nhớ chứ
  không phải trích xuất, và ngưỡng 60% của R2 bị bơm căng. Luật PRD 2.6 cho
  tối đa 2 tài liệu few-shot, loader ép trần đó.
- **Nhãn viết ở dạng đã chuẩn hóa sẵn.** Mọi fact vàng phải qua
  `core.facts.kiem_fact` mà giá trị *không đổi*, nên `id_fact` của nhãn vàng là
  đúng id node hyperedge mà pipeline sinh ra cho cùng tập slot. Nó chỉ bắt
  được ca **khớp tuyệt đối**, tức cả tập slot trùng từng chữ - hiếm, vì cách
  diễn đạt của LLM khó trùng nguyên văn ở mọi vai cùng lúc. Ca thường gặp
  (đúng `subject`, thiếu hoặc lẫn vai, chữ trôi một hai từ) là luật ghép của
  story 2.6 ở `eval/cham_trich_xuat.py`, không phải việc của module này. Xung
  đột định dạng `time` giữa prompt và nhãn đã đóng ở 2.6: ví dụ của prompt nay
  cũng phải là đoạn nguyên văn của thân tài liệu few-shot, cùng luật với nhãn.
- **Mọi giá trị slot phải là một đoạn có thật trong thân tài liệu.** So sau khi
  NFC, gộp khoảng trắng và `casefold()`, nên nhãn viết thường một chữ hoa đầu
  câu vẫn hợp lệ còn viết lại chữ thì không. Đây là chỗ luật "trích sát câu,
  không suy diễn" được *ép*, thay vì chỉ nằm trong một dòng hướng dẫn: một nhãn
  diễn giải lại văn bản làm mẫu số đo chính cách viết của người gán chứ không
  đo cái mà hệ phải trích ra.

Quy ước gán nhãn (viết ra để lần soát sau đọc cùng một luật với lần gán):

- `subject` là chủ thể mà fact nói về; nó được phép lấy từ chủ đề của tài liệu
  khi câu nguồn dùng đại từ hoặc lược chủ ngữ, miễn vẫn là một đoạn có thật ở
  đâu đó trong thân.
- Trong runbook, mệnh đề mở bằng "khi/nếu/quá ... trở lên" và mọi ngưỡng số là
  `condition`. `cause` chỉ dùng cho nguyên nhân gốc được *nêu thẳng* trong văn
  bản, tức gần như chỉ có ở báo cáo sự cố. Đây là cặp vai hay lẫn nhất (A13 kỹ
  thuật 1), nên nó phải có một luật chứ không phải cảm tính từng câu.
- `time` nhận cả thời điểm, tần suất và *thời hạn lưu giữ* ("giữ 90 ngày"):
  `GOI_Y_VAI` của prompt đã nói "thời điểm, khoảng thời gian hay tần suất".
- `source` là tài liệu, SOP, ticket hay hệ thống được dẫn làm nguồn (Jira,
  SOP-12, Vault), không phải nơi kết quả được ghi ra.
- `owner` là người hoặc nhóm chịu trách nhiệm, kể cả người phê duyệt.
- Một câu nói hai việc thì thành hai fact, không ghép chữ của hai mệnh đề rời
  nhau thành một giá trị.

Module thuần: đọc file trên đĩa, không chạm kho, không gọi LLM, không tốn tiền.
Chỉ import `core/`, `adapters/sensitivity_loader` (bảng hạng độ nhạy) và
`adapters/policy_loader` (bảng chính sách, cho luật phủ loại nội dung của story
2.8), không import `api/` (import-lint).
"""

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

import yaml

from adapters.policy_loader import cac_bang_chinh_sach as _quet_bang_chinh_sach
from adapters.policy_loader import load_policy
from adapters.sensitivity_loader import SensitivityRanksInvalid, bang_hang_mac_dinh
from core import facts
from core.ingest_scan import MA_DINH_DANG_LA, TaiLieuNguon, quet_thu_muc
from core.policy import PolicyInvalid
from core.slots import SLOT_ROLES

_GOC = Path(__file__).resolve().parent

# Bảng chính sách vận hành của repo (cấu hình 3 của FR-28).
POLICY_MAC_DINH: Path = _GOC.parent / "config" / "policy-day-du.yaml"

# Số bảng chính sách tối thiểu để phép quét được coi là còn chạy. Guard cho
# chính phép quét: một glob viết sai cho danh sách rỗng và luật phủ khi đó xanh
# mãi mà không đọc file nào.
TOI_THIEU_SO_BANG_CHINH_SACH: int = 2

# Bảng thiết kế corpus - **nguồn chuẩn** của loại nội dung có mặt trên dữ liệu
# thật. Corpus và bộ vàng nằm chung space `synth`, nên "dữ liệu thật" của luật
# phủ là hợp của hai bộ.
CORPUS_THIET_KE_MAC_DINH: Path = _GOC / "corpus_thiet_ke.yaml"

DUONG_DAN_MAC_DINH: Path = _GOC / "bo_vang_trich_xuat.json"
THU_MUC_DATA_MAC_DINH: Path = _GOC / "data"

VERSION_HO_TRO: int = 1

# Lược đồ đóng: khóa lạ ở cấp gốc, cấp tài liệu hay cấp fact bị từ chối. Một
# `few_shot` viết thành `fewshot` mà file vẫn nạp được nghĩa là một tài liệu
# lặng lẽ rơi vào mẫu số, tức một con số sai ở chương 4.
KHOA_GOC: frozenset[str] = frozenset({"version", "tai_lieu"})
KHOA_TAI_LIEU: frozenset[str] = frozenset(
    {"doc_key", "scope", "content_type", "few_shot", "facts"}
)
KHOA_FACT: frozenset[str] = frozenset({"slots", "cau_nguon"})

# Trần few-shot của PRD 2.6: lấy ví dụ từ tối đa 2 trong ~10 tài liệu bộ vàng,
# để mẫu số còn đủ lớn sau khi loại chúng.
TOI_DA_FEW_SHOT: int = 2


class BoVangKhongHopLe(ValueError):
    """Bộ vàng không dùng được làm mẫu số; mọi cách hỏng là một loại lỗi.

    Gom hết lỗi rồi ném một lần: người sửa nhãn phải thấy toàn bộ danh sách
    trong một lượt chạy, không sửa một dòng rồi chạy lại để lộ ra dòng kế.

    `code` là mã ổn định để nơi gọi và test bắt trên `code` chứ không trên
    thông điệp (AD-8); `loi` là danh sách từng lỗi một, đã kèm `doc_key`.
    """

    code = "BO_VANG_KHONG_HOP_LE"

    def __init__(self, loi: Sequence[str]):
        self.loi: tuple[str, ...] = tuple(loi)
        super().__init__("bộ vàng trích xuất không hợp lệ:\n- " + "\n- ".join(self.loi))


def chuan_so_sanh(van_ban: str) -> str:
    """Dạng dùng để so nhãn với thân tài liệu: NFC, gộp khoảng trắng, `casefold`.

    Bỏ phân biệt hoa thường vì nhãn thường lấy một cụm đứng đầu câu ("Sự cố
    mức nghiêm trọng" -> `sự cố mức nghiêm trọng`); gộp khoảng trắng vì một
    nhãn có thể vắt qua hai dòng của văn bản gốc. Không bỏ dấu câu: dấu câu là
    một phần của "trích sát", và bỏ nó mở đường cho nhãn ghép hai mệnh đề.
    """
    return " ".join(unicodedata.normalize("NFC", van_ban).split()).casefold()


@dataclass(frozen=True)
class FactVang:
    """Một fact gán nhãn tay: slot đã chuẩn hóa cộng câu nguồn của nó."""

    slots: Mapping[str, str]
    cau_nguon: str

    def __post_init__(self):
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))

    def __hash__(self) -> int:
        """Băm theo `id_fact` vì `MappingProxyType` không băm được.

        Story 2.6 sẽ đưa fact vàng vào `set`/`dict` để ghép với đầu ra pipeline,
        nên một dataclass frozen mà `hash()` nổ là một cái bẫy đặt sẵn. Hai fact
        cùng tập slot băm bằng nhau, đúng ngữ nghĩa của `id_fact`.
        """
        return hash(self.id_fact)

    @property
    def id_fact(self) -> str:
        """Id node hyperedge pipeline sinh ra cho đúng tập slot này (ca khớp tuyệt đối)."""
        return facts.id_fact(self.slots)

    @property
    def so_slot(self) -> int:
        return len(self.slots)

    def vai_da_dien(self) -> tuple[str, ...]:
        """Vai đã điền, theo thứ tự danh mục `SLOT_ROLES` (bảng của trang soát nhãn)."""
        return tuple(vai for vai in SLOT_ROLES if vai in self.slots)


@dataclass(frozen=True)
class TaiLieuVang:
    """Một tài liệu đã gán nhãn, kèm thân văn bản đọc từ `eval/data/`."""

    doc_key: str
    scope: str
    content_type: str
    few_shot: bool
    facts: tuple[FactVang, ...]
    than: str

    @property
    def so_slot(self) -> int:
        return sum(f.so_slot for f in self.facts)


@dataclass(frozen=True)
class BoVang:
    """Bộ vàng đã kiểm: dữ liệu và mẫu số, không có luật ghép nhãn nào.

    Luật ghép nhãn vàng với đầu ra pipeline (khớp tuyệt đối theo `id_fact`,
    khớp một phần theo `subject`) là của story 2.6. Ở đây chỉ giữ dữ liệu, để
    đổi luật ghép không phải đụng vào mẫu số.
    """

    version: int
    tai_lieu: tuple[TaiLieuVang, ...]

    def tai_lieu_cham(self) -> tuple[TaiLieuVang, ...]:
        """Tài liệu vào mẫu số: mọi tài liệu *không* dùng làm few-shot."""
        return tuple(t for t in self.tai_lieu if not t.few_shot)

    def tai_lieu_few_shot(self) -> tuple[TaiLieuVang, ...]:
        return tuple(t for t in self.tai_lieu if t.few_shot)

    def mau_so_slot(self) -> int:
        """Mẫu số của precision/recall: tổng slot đã điền của tài liệu chấm."""
        return sum(t.so_slot for t in self.tai_lieu_cham())

    def dem_theo_vai(self, chi_cham: bool = False) -> dict[str, int]:
        """Số fact có điền từng vai, đủ 8 khóa kể cả vai đếm 0 (hàng của ma trận 2.6)."""
        nguon = self.tai_lieu_cham() if chi_cham else self.tai_lieu
        dem = {vai: 0 for vai in SLOT_ROLES}
        for t in nguon:
            for f in t.facts:
                for vai in f.slots:
                    dem[vai] += 1
        return dem

    def id_fact_trung_cheo_tai_lieu(self) -> dict[str, tuple[str, ...]]:
        """Id fact xuất hiện ở từ hai tài liệu trở lên: id -> tên các tài liệu.

        `id_fact` băm tập slot đã chuẩn hóa, nên hai tài liệu gán *cùng* một tập
        slot là **một** node hyperedge phía pipeline trong khi mẫu số ở đây đếm
        hai lần. Không từ chối: hai tài liệu nói cùng một quy định là dữ liệu
        hợp lệ, và luật đếm (một lần hay theo tài liệu) phải quyết cùng lúc với
        luật ghép của story 2.6. Nhưng cũng không im lặng - trang soát nhãn in
        danh sách này ra, để ca đầu tiên xuất hiện lúc corpus lớn lên ở 2.8 là
        thấy được chứ không phải một con số lệch không ai truy ra.
        """
        cho: dict[str, list[str]] = {}
        for t in self.tai_lieu:
            for f in t.facts:
                cho.setdefault(f.id_fact, []).append(t.doc_key)
        return {i: tuple(ds) for i, ds in sorted(cho.items()) if len(ds) > 1}

    def so_fact(self, chi_cham: bool = False) -> int:
        nguon = self.tai_lieu_cham() if chi_cham else self.tai_lieu
        return sum(len(t.facts) for t in nguon)


def doc_bo_vang(
    duong_dan: str | Path | None = None, thu_muc_data: str | Path | None = None
) -> BoVang:
    """Đọc và kiểm bộ vàng; mọi cách hỏng là `BoVangKhongHopLe` ném một lần.

    `duong_dan` mặc định là `eval/bo_vang_trich_xuat.json`, `thu_muc_data` là
    `eval/data/`. Hai tham số có mặt để test dựng bộ vàng nhỏ trong `tmp_path`;
    bộ vàng thật không bao giờ bị sửa để tạo ca lỗi.
    """
    duong_dan = Path(duong_dan) if duong_dan is not None else DUONG_DAN_MAC_DINH
    thu_muc_data = Path(thu_muc_data) if thu_muc_data is not None else THU_MUC_DATA_MAC_DINH

    raw = _doc_json(duong_dan)
    nguon = _quet_data(thu_muc_data)

    loi: list[str] = []
    _kiem_goc(raw, loi)
    if loi:
        raise BoVangKhongHopLe(loi)

    tai_lieu, da_khai = _dung_tai_lieu(raw["tai_lieu"], nguon, loi)
    _kiem_toan_bo(tai_lieu, da_khai, nguon, loi)
    if loi:
        raise BoVangKhongHopLe(loi)
    return BoVang(version=raw["version"], tai_lieu=tuple(tai_lieu))


# --------------------------------------------------------------------------
# Đọc hai nguồn
# --------------------------------------------------------------------------


def _doc_json(duong_dan: Path) -> dict:
    try:
        van_ban = duong_dan.read_text(encoding="utf-8")
    except OSError as e:
        raise BoVangKhongHopLe([f"không đọc được {duong_dan}: {e}"]) from None
    except UnicodeDecodeError as e:
        raise BoVangKhongHopLe([f"{duong_dan} không phải UTF-8: {e}"]) from None
    try:
        return json.loads(van_ban)
    except json.JSONDecodeError as e:
        raise BoVangKhongHopLe([f"JSON hỏng ở {duong_dan}: {e}"]) from None


def _quet_data(thu_muc: Path) -> dict[str, TaiLieuNguon]:
    """Tài liệu nguồn theo `doc_key`, đọc bằng đúng cửa quét của pipeline ingest.

    Dùng `core.ingest_scan` chứ không tự parse frontmatter: bộ vàng phải nhìn
    thấy đúng thứ pipeline nhìn thấy, kể cả luật tách frontmatter và luật từ
    chối file.

    File sai *đuôi* (`MA_DINH_DANG_LA`) bị bỏ qua im lặng: `.gitkeep`,
    `.DS_Store`, file backup của trình soạn thảo không phải tài liệu và không
    ai định gán nhãn cho chúng - để chúng làm hỏng cả bộ vàng là biến một hạt
    rác thành một bộ test đỏ. Mọi mã từ chối khác (file rỗng, thiếu
    frontmatter, không phải UTF-8, quá lớn) vẫn là lỗi: đó là những file *có ý*
    là tài liệu nhưng hỏng, và im lặng bỏ chúng là im lặng thu hẹp mẫu số.
    """
    try:
        kq = quet_thu_muc(thu_muc)
    except FileNotFoundError as e:
        raise BoVangKhongHopLe([str(e)]) from None
    that_su_hong = [t for t in kq.tu_choi if t.ma != MA_DINH_DANG_LA]
    if that_su_hong:
        raise BoVangKhongHopLe(
            [f"{t.ten}: cửa quét ingest từ chối ({t.ma}) - {t.ly_do}" for t in that_su_hong]
        )
    return {t.doc_key: t for t in kq.chap_nhan}


# --------------------------------------------------------------------------
# Kiểm lược đồ
# --------------------------------------------------------------------------


def _kiem_goc(raw, loi: list[str]) -> None:
    if not isinstance(raw, dict):
        loi.append(f"gốc file phải là một object, nhận được {type(raw).__name__}")
        return
    la = set(raw) - KHOA_GOC
    if la:
        loi.append(f"khóa lạ ở cấp gốc: {sorted(la)}")
    if raw.get("version") != VERSION_HO_TRO:
        loi.append(f"version phải là {VERSION_HO_TRO}, nhận được {raw.get('version')!r}")
    if not isinstance(raw.get("tai_lieu"), list) or not raw["tai_lieu"]:
        loi.append("`tai_lieu` phải là một danh sách không rỗng")


def _dung_tai_lieu(
    danh_sach: Iterable, nguon: Mapping[str, TaiLieuNguon], loi: list[str]
) -> tuple[list[TaiLieuVang], set[str]]:
    """Dựng danh sách tài liệu vàng; trả kèm tập `doc_key` *đã khai* trong file.

    Tập đã khai gồm cả những mục bị bỏ giữa chừng vì lỗi. Nếu không giữ nó thì
    một mục hỏng sinh hai lỗi cho cùng một nguyên nhân gốc - lỗi thật, cộng
    một lỗi giả "file chưa có mục vàng" - và người sửa đuổi theo cái thứ hai.
    """
    ra: list[TaiLieuVang] = []
    da_khai: set[str] = set()
    for i, muc in enumerate(danh_sach):
        if not isinstance(muc, dict):
            loi.append(f"tài liệu thứ {i} phải là một object, nhận được {type(muc).__name__}")
            continue
        doc_key = muc.get("doc_key")
        ten = doc_key if isinstance(doc_key, str) and doc_key.strip() else f"<tài liệu thứ {i}>"
        thieu = KHOA_TAI_LIEU - set(muc)
        la = set(muc) - KHOA_TAI_LIEU
        if thieu or la:
            loi.append(f"{ten}: khóa thiếu {sorted(thieu)}, khóa lạ {sorted(la)}")
            if isinstance(doc_key, str):
                da_khai.add(doc_key)
            continue
        sai_kieu = [
            f"{khoa}={muc[khoa]!r}"
            for khoa in ("doc_key", "scope", "content_type")
            if not isinstance(muc[khoa], str) or not muc[khoa].strip()
        ]
        if sai_kieu:
            loi.append(f"{ten}: phải là chuỗi không rỗng - " + ", ".join(sai_kieu))
            if isinstance(doc_key, str):
                da_khai.add(doc_key)
            continue
        if not isinstance(muc["few_shot"], bool):
            # `"false"` là chuỗi truthy: không kiểm kiểu thì tài liệu đó lặng lẽ
            # rời khỏi mẫu số mà không ai thấy.
            loi.append(f"{ten}: `few_shot` phải là true/false, nhận được {muc['few_shot']!r}")
            da_khai.add(ten)
            continue
        if ten in da_khai:
            loi.append(f"{ten}: doc_key khai hai lần")
            continue
        da_khai.add(ten)
        goc = nguon.get(ten)
        if goc is None:
            loi.append(f"{ten}: có mục vàng nhưng không có file trong thư mục dữ liệu")
            continue
        if (muc["scope"], muc["content_type"]) != (goc.scope, goc.content_type):
            loi.append(
                f"{ten}: nhãn quyền lệch frontmatter - bộ vàng ghi"
                f" scope={muc['scope']!r}/content_type={muc['content_type']!r},"
                f" file ghi scope={goc.scope!r}/content_type={goc.content_type!r}"
            )
            continue
        cac_fact = _dung_facts(ten, muc["facts"], goc.noi_dung, loi)
        ra.append(
            TaiLieuVang(
                doc_key=ten,
                scope=goc.scope,
                content_type=goc.content_type,
                few_shot=muc["few_shot"],
                facts=tuple(cac_fact),
                than=goc.noi_dung,
            )
        )
    return ra, da_khai


def _dung_facts(ten: str, danh_sach, than: str, loi: list[str]) -> list[FactVang]:
    if not isinstance(danh_sach, list) or not danh_sach:
        loi.append(f"{ten}: `facts` phải là một danh sách không rỗng")
        return []
    than_so_sanh = chuan_so_sanh(than)
    ra: list[FactVang] = []
    id_da_thay: dict[str, int] = {}
    for j, muc in enumerate(danh_sach):
        nhan = f"{ten} fact#{j}"
        if not isinstance(muc, dict) or set(muc) != KHOA_FACT:
            loi.append(f"{nhan}: mỗi fact phải là object đúng hai khóa {sorted(KHOA_FACT)}")
            continue
        slots = muc["slots"]
        chuan, ma = facts.kiem_fact(slots)
        if ma is not None:
            loi.append(f"{nhan}: sai lược đồ fact, mã {ma} (slots={slots!r})")
            continue
        # Nhãn phải viết ở dạng đã chuẩn hóa: nếu `kiem_fact` phải sửa gì thì
        # `id_fact` của nhãn vàng vẫn khớp pipeline, nhưng thứ người soát đọc
        # trên trang HTML không còn là thứ được chấm. Từ chối, nêu cả hai.
        lech = [
            f"{vai}: {slots[vai]!r} -> {chuan[vai]!r}" for vai in chuan if slots[vai] != chuan[vai]
        ]
        if lech:
            loi.append(f"{nhan}: giá trị chưa chuẩn hóa - " + "; ".join(lech))
            continue
        ngoai_van = [
            f"{vai}={chuan[vai]!r}"
            for vai in chuan
            if chuan_so_sanh(chuan[vai]) not in than_so_sanh
        ]
        if ngoai_van:
            loi.append(
                f"{nhan}: giá trị không phải đoạn có thật trong thân tài liệu"
                f" (nhãn phải trích sát câu, không viết lại) - " + "; ".join(ngoai_van)
            )
            continue
        cau = muc["cau_nguon"]
        if not isinstance(cau, str) or not cau.strip():
            loi.append(f"{nhan}: `cau_nguon` phải là chuỗi không rỗng")
            continue
        if cau not in than:
            loi.append(f"{nhan}: câu nguồn không có nguyên văn trong thân tài liệu: {cau!r}")
            continue
        fact = FactVang(slots=chuan, cau_nguon=cau)
        truoc = id_da_thay.get(fact.id_fact)
        if truoc is not None:
            loi.append(f"{nhan}: trùng fact#{truoc} trong cùng tài liệu, id {fact.id_fact}")
            continue
        id_da_thay[fact.id_fact] = j
        ra.append(fact)
    return ra


def _kiem_toan_bo(
    tai_lieu: Sequence[TaiLieuVang],
    da_khai: set[str],
    nguon: Mapping[str, TaiLieuNguon],
    loi: list[str],
) -> None:
    """Sáu luật ở mức cả bộ: khớp thư mục, trần few-shot, còn tài liệu chấm, phủ vai, và hai phép bao hàm về loại nội dung (story 2.8)."""
    thieu = sorted(set(nguon) - da_khai)
    if thieu:
        loi.append(f"file trong thư mục dữ liệu chưa có mục vàng: {thieu}")

    few = [t.doc_key for t in tai_lieu if t.few_shot]
    if len(few) > TOI_DA_FEW_SHOT:
        loi.append(
            f"{len(few)} tài liệu khai `few_shot`, tối đa {TOI_DA_FEW_SHOT} (PRD 2.6):"
            f" {sorted(few)}"
        )
    if tai_lieu and not [t for t in tai_lieu if not t.few_shot]:
        # `mau_so_slot()` trả 0 và mọi phép chia của 2.6 nổ hoặc trả vô nghĩa.
        loi.append("không còn tài liệu chấm nào: mọi tài liệu đều khai `few_shot`, mẫu số bằng 0")

    da_dien = {vai for t in tai_lieu for f in t.facts for vai in f.slots}
    vai_thieu = [vai for vai in SLOT_ROLES if vai not in da_dien]
    if vai_thieu:
        loi.append(
            f"vai không có fact nào trong cả bộ: {vai_thieu}"
            " - ma trận lẫn lộn của 2.6 sẽ có hàng rỗng"
        )

    _kiem_loai_noi_dung(tai_lieu, loi)


def cac_bang_chinh_sach(thu_muc: str | Path | None = None) -> list[Path]:
    """Mọi file `config/policy-<id>.yaml`, quét chứ không liệt kê tên.

    Phép quét và hình dạng id sống ở `adapters/policy_loader`, không ở đây: cùng
    một định nghĩa "một bảng chính sách" phải phục vụ cả luật phủ này lẫn danh
    mục id của endpoint hoán policy. Hai bản riêng thì một
    `config/policy-Thu Nghiem.yaml` bị luật phủ bắt tuân thủ trong khi API không
    bao giờ hoán sang được.

    Guard riêng của luật phủ: một phép quét trả về dưới hai file nghĩa là glob
    hỏng, và khi đó luật này xanh mãi mà không đọc file nào.
    """
    goc = Path(thu_muc) if thu_muc is not None else POLICY_MAC_DINH.parent
    cac_bang = sorted(_quet_bang_chinh_sach(goc).values())
    if len(cac_bang) < TOI_THIEU_SO_BANG_CHINH_SACH:
        raise BoVangKhongHopLe(
            [
                f"chỉ tìm thấy {[p.name for p in cac_bang]} trong {goc}: phép quét"
                " bảng chính sách hỏng, và khi đó luật phủ loại nội dung không canh gì"
            ]
        )
    return cac_bang


def loai_cua_bang_chinh_sach(path: str | Path | None = None) -> set[str]:
    """Tập loại nội dung được *khai* trong bảng chính sách.

    Hợp của cột `disclosure` qua mọi vai. `path` là `None` thì quét **cả bốn**
    cấu hình đo của FR-28 và hợp lại: bảng vận hành và ba bảng đo không buộc
    phải khai cùng một tập, và một loại chỉ có ở một cấu hình đo vẫn là một ca
    mà phép đo của cấu hình đó sẽ mất nếu dữ liệu thật không có tài liệu nào.
    """
    cac_bang = [Path(path)] if path is not None else cac_bang_chinh_sach()
    ra: set[str] = set()
    for duong_dan in cac_bang:
        policy = load_policy(duong_dan)
        ra |= {loai for vai in policy.roles.values() for loai in vai.disclosure}
    return ra


def loai_cua_corpus(path: str | Path = CORPUS_THIET_KE_MAC_DINH) -> set[str]:
    """Tập loại nội dung có tài liệu thật trong corpus dựng (bảng thiết kế 2.8).

    Đọc **bảng thiết kế**, không quét thư mục: bảng là nguồn chuẩn và
    `tests/test_corpus.py` đã canh một-một giữa nó với `eval/corpus/`.
    """
    duong_dan = Path(path)
    try:
        raw = yaml.safe_load(duong_dan.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as loi:
        raise BoVangKhongHopLe(
            [f"không đọc được bảng thiết kế corpus {duong_dan}: {loi}"]
        ) from None
    muc = (raw or {}).get("tai_lieu")
    if not isinstance(muc, list) or not muc:
        raise BoVangKhongHopLe(
            [f"bảng thiết kế corpus {duong_dan} không có khối `tai_lieu` dùng được"]
        )
    return {m["content_type"] for m in muc if isinstance(m, dict) and m.get("content_type")}


def _kiem_loai_noi_dung(tai_lieu: Sequence[TaiLieuVang], loi: list[str]) -> None:
    """Hai phép bao hàm, không phải một đẳng thức (story 2.8, mở rộng ở 3.2).

    Câu hỏi mà luật phủ hỏi là **"bảng chính sách có mất ca nào trên dữ liệu
    thật không"**. Lúc story 2.8 viết luật, dữ liệu thật của space `synth` là 10
    tài liệu bộ vàng, nên mẫu đối chiếu là chính bộ vàng. Hôm nay `synth` có 52
    tài liệu và `eval/corpus_thiet_ke.yaml` phủ đủ 13/13 loại, nên mẫu đối chiếu
    là **corpus cộng bộ vàng**. Đối chiếu tiếp với riêng bộ vàng thì story 3.2
    (khai đủ 13 loại) buộc phải gán nhãn tay 10 tài liệu mới và đổi mẫu số 151
    slot của cổng R2 - tức luật cũ dời cái bẫy chứ không gỡ.

    Hai luật, mỗi luật trả lời một câu hỏi khác nhau:

    - **Phủ đủ bảng chính sách, trên dữ liệu thật.** Loại nội dung mà *bất kỳ*
      cấu hình nào trong bốn cấu hình đo khai phải có tài liệu trong space
      `synth` (corpus hoặc bộ vàng), nếu không phép đo mất ca tương ứng.
    - **Mọi loại của bộ vàng phải có hạng.** Chiều ngược lại vẫn bắt buộc: một
      tài liệu vàng mang loại không có hạng độ nhạy là một tài liệu không nạp
      được (`SensitivityRankUnknown` từ chối cả lô lúc ingest).

    **Luật này nói về phép đo nào, và không nói về phép đo nào.** Corpus không
    có nhãn trích xuất tay, nên "không mất ca trên dữ liệu thật" ở đây là phát
    biểu về *hình dạng truy hồi*: có tài liệu thuộc loại đó trong kho để một
    khóa lọc chạm tới. Cổng R2 của story 2.6 là chuyện khác và vẫn chỉ đứng trên
    **3 loại** của bộ vàng (`runbook`, `bao_cao_su_co`, `bi_mat_ha_tang`), vì
    precision ghép cặp cần nhãn tay từng slot. Đọc luật này thành "precision đã
    được đo trên 13 loại" là đọc sai; muốn thế thì phải gán nhãn thêm và đổi mẫu
    số 151 slot, đúng cái giá mà story 3.2 chọn không trả.
    """
    cua_bo = {t.content_type for t in tai_lieu}
    try:
        co_hang = set(bang_hang_mac_dinh().hang)
    except SensitivityRanksInvalid as e:
        # Không `return` ở đây: bảng hạng hỏng không được nuốt luôn phép kiểm
        # phủ theo bảng chính sách bên dưới. Gom hết lỗi rồi ném một lần là luật
        # của cả module (`BoVangKhongHopLe.loi` là một danh sách).
        loi.append(f"không nạp được bảng hạng độ nhạy để đối chiếu loại nội dung: {e}")
        co_hang = None
    if co_hang is not None:
        khong_hang = sorted(cua_bo - co_hang)
        if khong_hang:
            loi.append(
                f"loại nội dung của bộ vàng không có hạng độ nhạy: {khong_hang}"
                " - ingest sẽ từ chối cả lô bằng SensitivityRankUnknown"
            )
    try:
        cua_policy = loai_cua_bang_chinh_sach()
    except (PolicyInvalid, OSError) as e:
        loi.append(f"không nạp được bảng chính sách để đối chiếu loại nội dung: {e}")
        return
    except BoVangKhongHopLe as e:
        # `BoVangKhongHopLe.loi` là một **danh sách**, và `str(e)` của nó là cả
        # một khối nhiều dòng. Nhét nguyên khối vào một chuỗi lỗi khác cho một
        # thông điệp lồng một repr list; nối phẳng vào đúng danh sách đang gom.
        loi.extend(e.loi)
        return
    try:
        cua_du_lieu = cua_bo | loai_cua_corpus()
    except BoVangKhongHopLe as e:
        loi.extend(e.loi)
        return
    loai_thieu = sorted(cua_policy - cua_du_lieu)
    if loai_thieu:
        loi.append(
            f"loại nội dung có trong một bảng chính sách mà không có tài liệu nào"
            f" trong space `synth` (corpus hay bộ vàng): {loai_thieu} - bảng chính"
            " sách mất ca tương ứng trên dữ liệu thật"
        )
