"""Đề xuất bí danh thực thể từ một ảnh chụp đã commit (story 2.12, FR-32).

**Đây là một cửa, không phải một lời hứa.** Công cụ này gom ứng viên bí danh rồi
ghi ra `eval/de_xuat/<space>.yaml`; nó **không** chạm `config/tu-dien-thuc-the/`.
Từ điển đang chạy chỉ nhận mục mang dấu `xac_nhan` của người (loader
`adapters/tu_dien_thuc_the.py` từ chối mục thiếu dấu đó), và file đề xuất còn cố
ý mang một lược đồ **khác** - khóa gốc `de_xuat` chứ không `muc`, mỗi mục có
`ly_do` và `so_lan` mà lược đồ từ điển không nhận - nên một lần `cp` thẳng file
này vào `config/` là loader nổ, không phải một bảng gộp thực thể lặng lẽ chạy.

Ba luật gom ứng viên, tất định, hàm thuần, không gọi LLM:

1. **Biến thể hoa/thường.** `Phòng IT` và `phòng IT` là hai id entity hôm nay.
2. **Hậu tố tên miền.** `app01.company.vn` và `App01`: phần trước dấu chấm đầu
   tiên khớp một entity khác, và chuỗi có dạng tên máy.
3. **Dấu nối và khoảng trắng.** `APP-01`, `app_01` và `app01`.

Cả ba gộp về **một khóa gom** rồi nhóm theo khóa đó, nên một nhóm có thể tới từ
nhiều luật cùng lúc; `ly_do` của mục liệt kê đúng những luật đã thật sự tách hai
cách viết trong nhóm đó.

**Ràng theo scope.** Ứng viên chỉ gom trong phạm vi *một* scope. Gộp `web01` của
khách hàng A với `web01` của khách hàng B là hỏng đúng chỗ Composition-Risk đo,
nên công cụ không bao giờ đề xuất `scope: "*"`; nó chỉ **ghi chú** khi cùng một
nhóm xuất hiện ở nhiều scope, và người xác nhận quyết có nâng lên `*` hay không.

**Đọc thuần.** Đầu vào là một ảnh chụp đã commit cộng một model tùy chọn; không
chạm kho, không cần biến môi trường nào. Bước hỏi LLM là **tùy chọn** và tốn
tiền: vắng `--model` thì file đề xuất chỉ có phần tất định, và mỗi mục mang
`llm: null` để người đọc biết chưa ai hỏi.
"""

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from adapters.model_catalog import LOAI_LLM, ModelUnknown, danh_muc_mac_dinh
from eval.anh_rut_gon import la_space_rut_gon
from eval.rao_ghi_repo import SPACE_GHI_TRONG_REPO
from eval.cau_hoi import AnhDoThi, doc_anh_do_thi

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
THU_MUC_ANH: Path = REPO_ROOT / "eval" / "anh_do_thi"
THU_MUC_DE_XUAT: Path = REPO_ROOT / "eval" / "de_xuat"

# Lược đồ file đề xuất. Version riêng, không dùng chung với từ điển: hai file
# hai vòng đời, và một `version: 1` chung dễ đọc thành "cùng một lược đồ".
VERSION_DE_XUAT: int = 1

# Giá trị dài hơn thế không phải một thực thể mà là một mệnh đề (`cause`,
# `remediation` trong chính bộ vàng nhãn tay), và gộp bí danh trên mệnh đề là
# viết lại câu của người gán nhãn. 64 ký tự rộng gấp ba trung vị `subject` của
# bộ vàng (19 ký tự) nên nó không cắt mất ứng viên thật nào.
DAI_TOI_DA_UNG_VIEN: int = 64

# Dạng tên máy: có dấu chấm, và mọi đoạn chỉ gồm chữ, số, gạch ngang. Dùng để
# tách `app01.company.vn` thành `app01` mà không đụng "phòng 3.2" hay "v1.4".
# Nhãn cuối phải là chữ cái (`vn`, `com`, `local`), không phải số: nếu không thì
# `v1.4` thành `v1` và hai phiên bản khác nhau gộp làm một.
_TEN_MAY = re.compile(r"\A[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\Z")

# Ký tự bị bỏ khi dựng khóa gom: gạch ngang, gạch dưới, khoảng trắng.
_BO_KHI_GOM = re.compile(r"[\s_-]+")

LY_DO_HOA_THUONG: str = "hoa/thường"
LY_DO_TEN_MIEN: str = "hậu tố tên miền"
LY_DO_DAU_NOI: str = "dấu nối / khoảng trắng"


class DeXuatKhongGhiDuoc(ValueError):
    """Không ghi được file đề xuất, và lý do là một quyết định chứ không lỗi I/O.

    `code` ổn định để test assert trên `code` (AD-8).
    """

    code = "DE_XUAT_KHONG_GHI_DUOC"


def bo_dau_ten_may(ten: str) -> str:
    """`app01.company.vn` -> `app01`; chuỗi không phải tên máy thì giữ nguyên."""
    return ten.split(".", 1)[0] if _TEN_MAY.match(ten) else ten


def khoa_gom(ten: str) -> str:
    """Khóa gom của một entity: ba luật ứng viên rút về một chuỗi.

    NFC trước casefold: tiếng Việt gõ tổ hợp và gõ dựng sẵn phải rơi vào cùng
    một khóa, cùng lý do mà `core.ids.normalize_id` chuẩn hóa NFC.
    """
    gon = unicodedata.normalize("NFC", ten).strip().casefold()
    return _BO_KHI_GOM.sub("", bo_dau_ten_may(gon))


def ly_do_cua_nhom(bien_the: Sequence[str]) -> tuple[str, ...]:
    """Những bước **thật sự cần** để gộp nhóm này, không phải cả ba luật.

    Ba bước chạy nối tiếp nhau (casefold, bỏ hậu tố tên miền, bỏ dấu nối), nên
    một bước "cần" khi và chỉ khi nó **làm giảm** số cách viết còn lại. Một nhóm
    chỉ khác hoa/thường vì thế mang đúng một lý do; liệt kê cả ba cho mọi nhóm
    là một trường không mang tin, và nó là bug của bản đầu tiên - ba phép so
    chạy trên chuỗi thô nên hai biến thể khác hoa/thường vẫn khác nhau sau khi
    bỏ hậu tố tên miền, và mọi nhóm nhận đủ ba nhãn.
    """
    tho = [unicodedata.normalize("NFC", t).strip() for t in bien_the]

    def gom(hoa: bool, mien: bool, noi: bool) -> int:
        ra = set()
        for t in tho:
            x = t.casefold() if hoa else t
            x = bo_dau_ten_may(x) if mien else x
            ra.add(_BO_KHI_GOM.sub("", x) if noi else x)
        return len(ra)

    # "Cần" theo nghĩa **bỏ đi thì nhóm vỡ**, không theo nghĩa "bước này làm giảm
    # số cách viết". Hai định nghĩa khác nhau ở ca `App01` / `app01.company.vn`:
    # casefold một mình không giảm gì (hai chuỗi vẫn khác nhau ở phần đuôi), mà
    # bỏ nó đi thì nhóm không gộp được nữa - nên nó vẫn là một bước cần.
    return tuple(
        ten
        for ten, thieu in (
            (LY_DO_HOA_THUONG, gom(False, True, True)),
            (LY_DO_TEN_MIEN, gom(True, False, True)),
            (LY_DO_DAU_NOI, gom(True, True, False)),
        )
        if thieu > 1
    )


def scope_cua_hyperedge(h, scope_theo_doc_key: Mapping[str, str]) -> frozenset[str]:
    """Scope mà một hyperedge thuộc về: từ khóa lọc, hoặc từ các `doc_key`.

    Cùng hình dạng với `eval.ty_le_n_ngoi.hang_cua_hyperedge`: nguồn thứ nhất là
    khóa lọc của chính hyperedge, nguồn thứ hai (ca không khóa của AD-5) là các
    tài liệu sinh ra nó. Khác ở chỗ trả **tập**: một hyperedge hợp nhất khác
    scope thuộc về cả hai, và ứng viên bí danh phải thấy nó ở cả hai.
    """
    if h.scope is not None:
        return frozenset({h.scope})
    return frozenset(
        s for dk in h.doc_key if (s := scope_theo_doc_key.get(dk)) is not None
    )


@dataclass(frozen=True)
class NhomUngVien:
    """Một nhóm biến thể trong **một** scope, kèm số lần xuất hiện của từng biến thể."""

    scope: str
    chuan: str
    bi_danh: tuple[str, ...]
    ly_do: tuple[str, ...]
    so_lan: Mapping[str, int]
    # Scope khác cũng có đúng nhóm này. Chỉ là ghi chú cho người xác nhận: công
    # cụ không tự nâng lên `*` vì gộp hai khoang thuê bao là hỏng đúng chỗ tỷ lệ
    # Composition-Risk đo.
    cung_nhom_o_scope: tuple[str, ...] = ()


def dem_entity_theo_scope(anh: AnhDoThi) -> dict[str, dict[str, int]]:
    """`{scope: {entity: số lần điền vai}}`, đơn vị đếm của bảng phân bố vai."""
    scope_theo_doc_key = {t.doc_key: t.scope for t in anh.tai_lieu}
    dem: dict[str, dict[str, int]] = {}
    for h in anh.hyperedge:
        scopes = scope_cua_hyperedge(h, scope_theo_doc_key)
        gia_tri = [e for ds in h.slots.values() for e in ds]
        for s in scopes:
            o = dem.setdefault(s, {})
            for e in gia_tri:
                o[e] = o.get(e, 0) + 1
    return dem


def nhom_lien_scope(anh: AnhDoThi) -> tuple[tuple[str, ...], ...]:
    """Nhóm biến thể mà **không scope nào** giữ đủ hai cách viết. Không đề xuất.

    Ca thật nó bắt trên `synth`: `Trực ban Tech Support` chỉ xuất hiện ở
    `khach_hang_b` còn `trực ban Tech Support` chỉ ở `noi_bo`. Gộp chúng là một
    phép gộp **xuyên scope**, đúng thứ luật ràng theo scope cấm, nên công cụ
    không đưa nó vào `de_xuat`. Nhưng im lặng cũng sai: người xác nhận đọc "4
    nhóm" trong khi phép gom toàn cục thấy 5, và chênh lệch đó phải có tên.

    Trả danh sách biến thể của từng nhóm, sắp cho ổn định giữa hai lần chạy.
    """
    dem = dem_entity_theo_scope(anh)
    scope_cua: dict[str, set[str]] = {}
    for s, o in dem.items():
        for e in o:
            if len(e) <= DAI_TOI_DA_UNG_VIEN:
                scope_cua.setdefault(e, set()).add(s)
    gom: dict[str, list[str]] = {}
    for e in scope_cua:
        gom.setdefault(khoa_gom(e), []).append(e)
    ra = []
    for k, bien_the in gom.items():
        if len(bien_the) < 2:
            continue
        # Nhóm nào đã có đủ hai biến thể trong *một* scope thì đã được đề xuất.
        if any(
            sum(1 for e in bien_the if s in scope_cua[e]) > 1
            for s in {x for e in bien_the for x in scope_cua[e]}
        ):
            continue
        ra.append(tuple(sorted(bien_the)))
    return tuple(sorted(ra))


def ung_vien_bi_danh(anh: AnhDoThi) -> tuple[NhomUngVien, ...]:
    """Mọi nhóm ứng viên của một ảnh chụp. Hàm thuần, không I/O, không LLM.

    Tên chuẩn đề xuất là biến thể **hay gặp nhất** trong scope đó; hòa thì lấy
    chuỗi ngắn hơn, rồi theo thứ tự chữ. Chọn theo tần suất chứ không theo "cách
    viết đẹp": nhãn vàng của story 2.5 trích sát văn bản, nên một tên chuẩn ít
    gặp kéo `subject` của đa số fact rời khỏi nhãn - và R2 là cổng mà story này
    phải đi qua trước khi nạp lại.
    """
    dem = dem_entity_theo_scope(anh)

    # `{scope: {khóa gom: [biến thể]}}`, chỉ giữ nhóm từ hai biến thể trở lên.
    nhom_theo_scope: dict[str, dict[str, list[str]]] = {}
    for s, o in dem.items():
        gom: dict[str, list[str]] = {}
        for e in o:
            if len(e) > DAI_TOI_DA_UNG_VIEN:
                continue
            gom.setdefault(khoa_gom(e), []).append(e)
        nhom_theo_scope[s] = {k: v for k, v in gom.items() if len(v) > 1}

    # Khóa gom nào có mặt ở nhiều scope - chỉ để ghi chú, không để gộp.
    scope_cua_khoa: dict[str, list[str]] = {}
    for s, gom in nhom_theo_scope.items():
        for k in gom:
            scope_cua_khoa.setdefault(k, []).append(s)

    ra: list[NhomUngVien] = []
    for s in sorted(nhom_theo_scope):
        for k in sorted(nhom_theo_scope[s]):
            bien_the = nhom_theo_scope[s][k]
            o = dem[s]
            chuan = min(bien_the, key=lambda t: (-o[t], len(t), t))
            bi_danh = tuple(sorted(t for t in bien_the if t != chuan))
            ra.append(
                NhomUngVien(
                    scope=s,
                    chuan=chuan,
                    bi_danh=bi_danh,
                    ly_do=ly_do_cua_nhom(bien_the),
                    so_lan={t: o[t] for t in sorted(bien_the)},
                    cung_nhom_o_scope=tuple(
                        x for x in sorted(scope_cua_khoa[k]) if x != s
                    ),
                )
            )
    return tuple(ra)


# ---------------------------------------------------------------------------
# Bước hỏi LLM (tùy chọn, tốn tiền)
# ---------------------------------------------------------------------------

def _canh_bao(thong_diep: str) -> None:
    print(thong_diep, file=sys.stderr)


PROMPT_DE_XUAT: str = """Bạn đang soát một bảng gộp bí danh thực thể cho đồ thị tri thức vận hành IT tiếng Việt.

Dưới đây là các nhóm cách viết mà một phép gom tất định cho là **cùng một thực thể**. Với mỗi nhóm, trả lời chúng có thật sự là một thực thể hay không.

Trả về một object json duy nhất dạng {"nhan_xet": [{"stt": <số>, "cung_mot_thuc_the": true|false, "ly_do": "<một câu ngắn>"}]}, không có văn bản nào khác ngoài JSON.

Các nhóm:
<<NHOM>>
"""

THAM_SO_LLM_DE_XUAT: Mapping[str, object] = {
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "max_tokens": 4096,
}


def dung_prompt_de_xuat(nhom: Sequence[NhomUngVien]) -> str:
    """Prompt hỏi LLM về cả danh sách nhóm trong **một** lời gọi.

    Một lời gọi cho mỗi nhóm là vài trăm lời gọi cho một bảng vài trăm nhóm, và
    câu hỏi ở đây không cần ngữ cảnh riêng cho từng nhóm.
    """
    dong = "\n".join(
        f"{i + 1}. scope={n.scope} | " + " | ".join((n.chuan,) + n.bi_danh)
        for i, n in enumerate(nhom)
    )
    return PROMPT_DE_XUAT.replace("<<NHOM>>", dong)


def doc_nhan_xet(van_ban: str, so_nhom: int, in_ra=None) -> dict[int, dict]:
    """`{stt (0-based): nhận xét}` đọc từ phản hồi LLM; phản hồi hỏng cho dict rỗng.

    Không nổ khi LLM trả rác: bước này là **gợi ý** cho người xác nhận, và một
    phản hồi hỏng không được làm mất phần tất định đã tính xong. Mục không có
    nhận xét mang `llm: null`, đúng như khi chưa hỏi lần nào.
    """
    def than_phien(ly_do: str) -> dict[int, dict]:
        # "Đã hỏi, LLM trả rác" và "chưa hỏi lần nào" ghi ra file **y hệt nhau**
        # (`llm: null` ở mọi mục), nên nếu không nói ra ở đây thì tiền đã tiêu
        # cho một lời gọi mà không dấu vết nào cho biết.
        (in_ra or _canh_bao)(
            f"cảnh báo: đã gọi LLM nhưng phản hồi không dùng được ({ly_do});"
            " mọi mục sẽ mang `llm: null` y như khi chưa hỏi"
        )
        return {}

    try:
        raw = json.loads(van_ban)
    except (json.JSONDecodeError, TypeError) as loi:
        return than_phien(f"không phải JSON: {loi}")
    ds = raw.get("nhan_xet") if isinstance(raw, dict) else None
    if not isinstance(ds, list):
        return than_phien("thiếu khóa `nhan_xet` hoặc nó không phải danh sách")
    ra: dict[int, dict] = {}
    for m in ds:
        if not isinstance(m, dict):
            continue
        stt = m.get("stt")
        if not isinstance(stt, int) or isinstance(stt, bool):
            continue
        if not 1 <= stt <= so_nhom:
            continue
        ra[stt - 1] = {
            "cung_mot_thuc_the": bool(m.get("cung_mot_thuc_the")),
            "ly_do": str(m.get("ly_do", "")).strip(),
        }
    return ra


async def hoi_llm(nhom: Sequence[NhomUngVien], model: str, *, dung_llm=None, in_ra=print):
    """Một lời gọi LLM cho cả danh sách; trả `{stt: nhận xét}`."""
    from adapters.llm_wrapper import bo_llm, nha_cung_cap_tu_moi_truong
    from eval.do_trich_xuat import GomChiPhi, goi_llm_co_thu_lai

    danh_muc = danh_muc_mac_dinh()
    muc = danh_muc.muc(model, loai=LOAI_LLM)
    audit = GomChiPhi()
    llm = (
        dung_llm(muc, danh_muc, audit)
        if dung_llm is not None
        else bo_llm(
            nha_cung_cap=nha_cung_cap_tu_moi_truong(muc, danh_muc),
            model=muc.ten,
            audit=audit,
            danh_muc=danh_muc,
        )
    )
    van_ban = await goi_llm_co_thu_lai(
        llm, dung_prompt_de_xuat(nhom), in_ra=in_ra, **THAM_SO_LLM_DE_XUAT
    )
    return doc_nhan_xet(van_ban, len(nhom))


# ---------------------------------------------------------------------------
# Ghi file đề xuất
# ---------------------------------------------------------------------------


def dung_de_xuat(
    anh: AnhDoThi,
    nhom: Sequence[NhomUngVien],
    *,
    anh_chup: str,
    model: str | None = None,
    nhan_xet: Mapping[int, dict] | None = None,
    lien_scope: Sequence[Sequence[str]] = (),
) -> dict:
    """Nội dung file đề xuất, dạng dict để `yaml.safe_dump` ghi ra.

    Lược đồ **khác** lược đồ từ điển một cách cố ý: khóa gốc `de_xuat` chứ không
    `muc`, và mỗi mục thiếu `xac_nhan` mà thừa `ly_do`/`so_lan`/`llm`. Copy
    thẳng file này vào `config/tu-dien-thuc-the/` là loader nổ ngay ở khóa gốc,
    chứ không phải một bảng gộp thực thể chạy mà không ai xác nhận.
    """
    nx = dict(nhan_xet or {})
    return {
        "version": VERSION_DE_XUAT,
        "space": anh.space,
        "ngay_anh_chup": anh.ngay_do,
        "anh_chup": anh_chup,
        "model": model,
        "so_nhom": len(nhom),
        # Nhóm chỉ tồn tại **giữa** các scope: ghi ra để người xác nhận thấy
        # chênh lệch với một phép gom toàn cục, nhưng nằm ngoài `de_xuat` vì gộp
        # chúng là gộp xuyên scope.
        "nhom_lien_scope": [list(g) for g in lien_scope],
        "de_xuat": [
            {
                "chuan": n.chuan,
                "scope": n.scope,
                "bi_danh": list(n.bi_danh),
                "ly_do": list(n.ly_do),
                "so_lan": dict(n.so_lan),
                "cung_nhom_o_scope": list(n.cung_nhom_o_scope),
                "llm": nx.get(i),
            }
            for i, n in enumerate(nhom)
        ],
    }


# Vật mà module này ghi ra: file đề xuất bí danh, liệt kê **nguyên văn tên
# entity**, nên với space dữ liệu thật nó là nội dung tài liệu công ty. Rào ở
# đây chứ không chỉ ở `.gitignore`: thứ tự hai dòng trong `.gitignore` là một
# hàng rào mà một lần sửa file đó vô hiệu hóa được, và `git add -f` thì đi thẳng
# qua nó.
#
# Danh sách và lý do của nó ở `eval/rao_ghi_repo.py`, dùng chung với
# `eval/chup_do_thi.py` và `eval/ct03.py` (retro Epic 2).


def ly_do_tu_choi_dich(
    dich: Path, space: str = "?", goc_repo: Path | None = None
) -> str | None:
    """Lý do từ chối ghi file đề xuất vào `dich`, hoặc `None` nếu được.

    Hai ca, cùng một chuyện: một file đề xuất không được nằm ở chỗ nó thành dữ
    liệu công ty trong git.

    1. **Ghi vào `config/`.** Một đề xuất nằm trong `config/tu-dien-thuc-the/`
       là một bảng gộp thực thể đã ở đúng chỗ mà engine đọc, và chỉ còn thiếu
       một người quên chưa xóa nó đi.
    2. **Space ngoài `SPACE_GHI_TRONG_REPO`, ghi vào cây repo.** Cùng hình dạng
       với rào của `eval/chup_do_thi.py` và `eval/ct03.py`: `--space real --dich
       eval/de_xuat/real.yaml` ghi nguyên văn tên entity của tài liệu công ty
       vào một file mà git nhận được.
    """
    goc = (REPO_ROOT if goc_repo is None else Path(goc_repo)).resolve()
    duong_dan = Path(dich).resolve()
    try:
        duong_dan.relative_to(goc / "config")
    except ValueError:
        pass
    else:
        return (
            f"từ chối ghi file đề xuất vào {dich}: `config/` là chỗ của từ điển"
            " đang chạy, và mọi mục ở đó phải mang dấu `xac_nhan` của người. Đề"
            f" xuất ghi vào {THU_MUC_DE_XUAT.relative_to(REPO_ROOT)}/<space>.yaml,"
            " rồi người xác nhận chép sang từng mục một"
        )
    if space in SPACE_GHI_TRONG_REPO:
        return None
    try:
        duong_dan.relative_to(goc)
    except ValueError:
        return None
    return (
        f"từ chối ghi đề xuất của space {space!r} vào {dich} (trong cây repo):"
        f" chỉ {sorted(SPACE_GHI_TRONG_REPO)} được commit. File đề xuất liệt kê"
        " **nguyên văn tên entity**, nên với space dữ liệu thật nó là nội dung"
        " tài liệu công ty - ghi ra ngoài repo bằng --dich"
    )


DUOI_BAN_CU: str = ".bak.yaml"


def ghi_de_xuat(
    dich: Path, du_lieu: dict, *, space: str = "?", ghi_de: bool = False
) -> Path:
    """Ghi file đề xuất; file đã có thì đòi `--ghi-de` và bản cũ giữ lại."""
    import yaml

    ly_do = ly_do_tu_choi_dich(dich, space)
    if ly_do is not None:
        raise DeXuatKhongGhiDuoc(ly_do)
    dich = Path(dich)
    if dich.exists() and not ghi_de:
        raise DeXuatKhongGhiDuoc(
            f"{dich} đã có: thêm --ghi-de (bản cũ giữ thành `{dich.name}{DUOI_BAN_CU}`)"
        )
    dich.parent.mkdir(parents=True, exist_ok=True)
    if dich.exists():
        dich.replace(dich.with_name(dich.name + DUOI_BAN_CU))
    dau = (
        "# ĐỀ XUẤT bí danh thực thể - **không phải** từ điển đang chạy (story 2.12).\n"
        "# Sinh bằng `python -m eval.de_xuat_bi_danh`. Lược đồ ở đây khác lược đồ\n"
        "# của `config/tu-dien-thuc-the/`: khóa gốc là `de_xuat`, và mục không có\n"
        "# `xac_nhan`. Người xác nhận chép sang từng mục một, thêm dấu\n"
        "# `xac_nhan: \"<tên> <ngày>\"`, và bỏ `ly_do`/`so_lan`/`llm`.\n"
    )
    dich.write_text(
        dau + yaml.safe_dump(du_lieu, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return dich


def la_anh_rut_gon(anh: AnhDoThi) -> bool:
    """Ảnh chụp có phải bản **rút gọn** không, đọc từ chính lời tự khai của nó.

    Hai dấu, lấy cái nào có: `muoi_id` (chỉ bản rút gọn mang) và hậu tố của
    `space`. Đọc hai dấu chứ không một: một file sửa tay bỏ `muoi_id` vẫn tự khai
    ở tên space, và ngược lại.
    """
    return anh.muoi_id is not None or la_space_rut_gon(anh.space)


def _duong_dan_tuong_doi(p) -> str:
    """Đường dẫn ảnh chụp ghi vào file đề xuất, tương đối với gốc repo nếu được.

    File đề xuất của `synth` và `khao_sat` **có commit**, và một đường dẫn tuyệt
    đối trong đó là tên thư mục home của người chạy - vừa vô nghĩa với người
    khác, vừa là một mẩu thông tin về máy lọt vào git.
    """
    try:
        return str(Path(p).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _tham_so(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Gom ứng viên bí danh thực thể từ một ảnh chụp đã commit và ghi"
            " eval/de_xuat/<space>.yaml. Không chạm config/, không chạm kho."
        )
    )
    p.add_argument("--space", default="synth", help="không gian dữ liệu (mặc định synth)")
    p.add_argument(
        "--anh",
        type=Path,
        default=None,
        help="ảnh chụp (mặc định eval/anh_do_thi/<space>.json)",
    )
    p.add_argument("--dich", type=Path, default=None, help="file đề xuất cần ghi")
    p.add_argument("--ghi-de", action="store_true", dest="ghi_de")
    p.add_argument(
        "--model",
        default=None,
        help="hỏi thêm LLM về từng nhóm (TỐN TIỀN); vắng thì chỉ phần tất định",
    )
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    ts = _tham_so(sys.argv[1:] if argv is None else argv)
    anh_path = ts.anh or THU_MUC_ANH / f"{ts.space}.json"
    dich = ts.dich or THU_MUC_DE_XUAT / f"{ts.space}.yaml"
    try:
        anh = doc_anh_do_thi(anh_path)
    except Exception as loi:  # loader tự nêu đủ lý do
        print(f"{type(loi).__name__}: {loi}", file=sys.stderr)
        return 1
    if anh.space != ts.space and not anh.space.startswith(f"{ts.space}_"):
        print(
            f"ảnh chụp {anh_path} khai space {anh.space!r} nhưng --space là"
            f" {ts.space!r}: đề xuất sẽ mang tên một space không sinh ra nó",
            file=sys.stderr,
        )
        return 1
    if la_anh_rut_gon(anh):
        print(
            f"từ chối: {anh_path} là ảnh chụp **rút gọn** (space {anh.space!r},"
            " mọi id entity đã là băm có muối). Gom bí danh trên băm là gom trên"
            " một tập chuỗi ngẫu nhiên: không cách viết nào giống cách viết nào,"
            " nên file đề xuất sẽ luôn rỗng và trông y như 'không có bí danh nào'."
            " Chạy trên ảnh **đầy đủ** của space đó, ngoài cây repo",
            file=sys.stderr,
        )
        return 1
    nhom = ung_vien_bi_danh(anh)
    lien_scope = nhom_lien_scope(anh)
    nhan_xet = None
    if ts.model:
        if not nhom:
            print("không nhóm ứng viên nào: bỏ qua lời gọi LLM (không tiêu tiền)")
        else:
            try:
                nhan_xet = asyncio.run(hoi_llm(nhom, ts.model))
            except ModelUnknown as loi:
                # Tên model gõ sai là lỗi của dòng lệnh, chưa tiêu đồng nào:
                # dừng để người chạy sửa rồi gọi lại.
                print(f"{ModelUnknown.code}: {loi}", file=sys.stderr)
                return 1
            except Exception as loi:  # noqa: BLE001
                # Mọi cách hỏng khác (mạng đứt, provider 5xx sau bốn lần thử) là
                # mất **phần LLM**, không phải mất cả lượt chạy: phần tất định đã
                # tính xong và nó là phần chính của file đề xuất. Ghi nó ra rồi
                # nói thẳng phần nào thiếu, thay vì để người chạy mất trắng một
                # lượt gom.
                print(
                    f"cảnh báo: bước hỏi LLM hỏng ({type(loi).__name__}: {loi});"
                    " vẫn ghi phần tất định, mọi mục mang `llm: null`",
                    file=sys.stderr,
                )
    try:
        ra = ghi_de_xuat(
            dich,
            dung_de_xuat(
                anh,
                nhom,
                anh_chup=_duong_dan_tuong_doi(anh_path),
                model=ts.model,
                nhan_xet=nhan_xet,
                lien_scope=lien_scope,
            ),
            space=ts.space,
            ghi_de=ts.ghi_de,
        )
    except DeXuatKhongGhiDuoc as loi:
        print(f"{DeXuatKhongGhiDuoc.code}: {loi}", file=sys.stderr)
        return 1
    print(f"{len(nhom)} nhóm ứng viên -> {ra}")
    for n in nhom:
        print(f"  [{n.scope}] {n.chuan} <= {', '.join(n.bi_danh)}  ({', '.join(n.ly_do)})")
    for g in lien_scope:
        print(f"  (liên scope, KHÔNG đề xuất) {' | '.join(g)}")
    print(
        "Đây là ĐỀ XUẤT. Từ điển đang chạy ở config/tu-dien-thuc-the/ chỉ nhận"
        " mục mang dấu `xac_nhan` của người."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
