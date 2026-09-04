"""Ảnh chụp đồ thị dạng **rút gọn**: giữ hình dạng, bỏ mọi giá trị (story 2.11).

Vấn đề nó giải: ba tỷ lệ n-ngôi của space `real` là ba con số của chương 4, mà
ảnh chụp đầy đủ tính ra chúng **không commit được** - nó dump nguyên văn giá trị
mọi slot của tài liệu công ty. Không có ảnh chụp trong repo thì ba tỷ lệ chỉ còn
là hằng chép tay, và `tests/test_ty_le_n_ngoi.py` mất chỗ đứng: với `synth` và
`khao_sat` nó *tính lại* từ ảnh chụp nên một lần nạp lại làm số trôi là test đỏ,
còn với `real` thì không gì báo.

Bản rút gọn giữ đúng thứ ba định nghĩa đếm của ADR-012 cần và không hơn:

- **Số vai được điền** của mỗi hyperedge (tỷ lệ 1) - giữ nguyên cấu trúc `slots`,
  chỉ thay giá trị.
- **Hạng độ nhạy** (tỷ lệ 2) - giữ nguyên `khoa`, và `scope`/`content_type` của
  từng tài liệu, vì hạng suy từ chúng.
- **Quan hệ trùng nhau giữa các id** (tỷ lệ 3) - cùng một entity ra cùng một
  băm, nên phép "entity này còn xuất hiện ở hyperedge không nhạy cảm nào không"
  cho đúng kết quả như trên ảnh đầy đủ.

Cái nó bỏ là **giá trị**: không tên entity, không tên file, không câu fact. Từ
một bản rút gọn không dựng lại được một câu nào.

**Muối là bắt buộc, thiếu muối là từ chối.** Băm trần một tên entity ngắn
(`App01`, `Redis`, tên một khách hàng) là dò ngược được bằng danh sách ứng viên:
kẻ đọc chỉ cần băm từng ứng viên rồi so. Muối giữ ngoài repo (`extra/`), nên
người đọc repo tính lại được ba tỷ lệ mà vẫn không dựng lại được một tên nào.
Mất muối **không** mất khả năng kiểm: ba tỷ lệ chỉ phụ thuộc quan hệ bằng nhau
giữa các id, không phụ thuộc giá trị băm.

**File tự khai nó là bản rút gọn** ở hai chỗ, để không ai đọc nhầm thành ảnh đầy
đủ: `space` mang hậu tố `_rut_gon` (nó đi thẳng vào tiêu đề cột của trang ba tỷ
lệ và vào `BaTyLe.space`), và **mọi** id trong file mang tiền tố `rg-`. Hai chỗ
đó không thêm khóa nào vào lược đồ, nên `eval.cau_hoi.doc_anh_do_thi` và
`eval.ty_le_n_ngoi.ba_ty_le` dùng lại được **không sửa một dòng**.

Chỉ stdlib: đây là hàm thuần trên dict, không chạm kho và không import tầng nào.
"""

import hashlib
from pathlib import Path
from typing import Mapping

# Hậu tố `space` của bản rút gọn. `real` -> `real_rut_gon`. Đây là lời tự khai
# **đọc được bằng máy**: `BaTyLe.space` mang nó, nên tiêu đề cột của trang ba tỷ
# lệ và mọi dòng console đều nói ra rằng cột đó dựng trên bản rút gọn.
HAU_TO_RUT_GON: str = "_rut_gon"

# Tiền tố chung của mọi id trong bản rút gọn, cộng một chữ cho từng loại. Một
# giá trị lẻ chép ra khỏi file vẫn tự khai nó là băm của bản rút gọn, không phải
# một id thật của graph.
TIEN_TO_HYPEREDGE: str = "rg-h-"
TIEN_TO_ENTITY: str = "rg-e-"
TIEN_TO_DOC: str = "rg-d-"

# Độ dài băm cắt ngắn, tính bằng ký tự hex. 16 hex là 64 bit: với một space vài
# nghìn entity, xác suất trùng là cỡ 1e-13, và `rut_gon_anh` vẫn kiểm trùng
# tường minh thay vì tin vào con số đó. Ngắn để file đọc được bằng mắt.
SO_HEX: int = 16

# Trần dưới của độ dài muối. Một muối ba ký tự là không có muối: kẻ đọc dò cả
# không gian muối rồi mới dò danh sách ứng viên, và phép dò thứ hai mới là phép
# đắt. 16 ký tự là mức mà phép dò thứ nhất đã không làm được.
DO_DAI_MUOI_TOI_THIEU: int = 16


class MuoiKhongHopLe(ValueError):
    """Không có muối, hoặc muối quá ngắn để có tác dụng.

    **Từ chối, không băm trần.** Một bản rút gọn băm trần trông y hệt một bản có
    muối - cùng hình dạng file, cùng ba con số - nên không có bước nào sau đó để
    ai đó nhận ra. Đây là chỗ duy nhất chặn được.

    `code` ổn định để test assert trên `code` (AD-8).
    """

    code = "MUOI_KHONG_HOP_LE"


class BamTrung(RuntimeError):
    """Hai giá trị khác nhau ra cùng một băm cắt ngắn.

    Từ chối cả đợt. Một va chạm gộp hai entity thành một, và tỷ lệ 3 đếm đúng
    trên quan hệ bằng nhau giữa các entity - tức con số sai theo đúng chiều mà
    Composition-Risk đo.
    """

    code = "BAM_TRUNG"


def doc_muoi(duong_dan: str | Path) -> str:
    """Đọc muối từ file ngoài repo; thiếu file hay muối quá ngắn là lỗi có mã."""
    duong_dan = Path(duong_dan)
    if not duong_dan.exists():
        raise MuoiKhongHopLe(
            f"không có file muối {duong_dan}: bản rút gọn cần muối, và thiếu muối"
            " là **từ chối** chứ không băm trần - băm trần một tên entity ngắn là"
            " dò ngược được bằng danh sách ứng viên. Muối giữ ngoài repo; tạo nó"
            " bằng `python3 -c \"import secrets;print(secrets.token_hex(32))\"`"
        )
    try:
        muoi = duong_dan.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as loi:
        raise MuoiKhongHopLe(f"không đọc được {duong_dan}: {loi}") from None
    if len(muoi) < DO_DAI_MUOI_TOI_THIEU:
        raise MuoiKhongHopLe(
            f"{duong_dan}: muối dài {len(muoi)} ký tự, cần ít nhất"
            f" {DO_DAI_MUOI_TOI_THIEU} - một muối ngắn là không có muối"
        )
    return muoi


def bam(muoi: str, loai: str, gia_tri: str) -> str:
    """Băm có muối, cắt ngắn, mang tiền tố của loại. Hàm thuần.

    `loai` đi vào phần được băm chứ không chỉ vào tiền tố: một tên file và một
    tên entity viết giống nhau là hai thứ khác nhau, và cho chúng cùng một băm
    là dựng một quan hệ bằng nhau không có thật.
    """
    if not muoi or len(muoi) < DO_DAI_MUOI_TOI_THIEU:
        raise MuoiKhongHopLe(
            f"muối dài {len(muoi)} ký tự, cần ít nhất {DO_DAI_MUOI_TOI_THIEU}"
        )
    than = f"{muoi}\x00{loai}\x00{gia_tri}".encode("utf-8")
    return hashlib.sha256(than).hexdigest()[:SO_HEX]


def la_space_rut_gon(space: str) -> bool:
    """`space` của một bản rút gọn (kết thúc bằng `_rut_gon`)."""
    return isinstance(space, str) and space.endswith(HAU_TO_RUT_GON)


def space_goc(space: str) -> str:
    """Tên space thật đứng sau một `space` rút gọn; trả nguyên nếu không phải."""
    return space[: -len(HAU_TO_RUT_GON)] if la_space_rut_gon(space) else space


class _So:
    """Sổ băm một chiều, kèm phép kiểm va chạm ngay lúc cấp."""

    def __init__(self, muoi: str, loai: str, tien_to: str):
        self._muoi, self._loai, self._tien_to = muoi, loai, tien_to
        self._theo_gia_tri: dict[str, str] = {}
        self._nguoc: dict[str, str] = {}

    def __call__(self, gia_tri: str) -> str:
        co = self._theo_gia_tri.get(gia_tri)
        if co is not None:
            return co
        ma = self._tien_to + bam(self._muoi, self._loai, gia_tri)
        chu_cu = self._nguoc.get(ma)
        if chu_cu is not None and chu_cu != gia_tri:
            raise BamTrung(
                f"hai giá trị {self._loai} khác nhau ra cùng băm {ma!r}:"
                f" tăng SO_HEX rồi chụp lại. Không gộp: một va chạm gộp hai"
                " entity thành một và làm sai đúng tỷ lệ Composition-Risk"
            )
        self._theo_gia_tri[gia_tri] = ma
        self._nguoc[ma] = gia_tri
        return ma


def rut_gon_anh(anh: Mapping, muoi: str) -> dict:
    """Bản rút gọn của một dict ảnh chụp đầy đủ. Hàm thuần, không I/O.

    Giữ nguyên: `version`, `ngay_do`, `policy_version`, `khoa` của từng
    hyperedge, `scope`/`content_type`/`sha256` của từng tài liệu, ba số đếm, cấu
    trúc `slots` (vai nào được điền, mấy giá trị mỗi vai), và quan hệ trùng nhau
    giữa mọi id.

    Thay bằng băm có muối: id hyperedge, `doc_key`, và mọi id entity trong
    `slots`.

    Id hyperedge cũng bị băm dù nó **đã** là một băm (`core.facts.id_fact`):
    băm đó không có muối và nó băm đúng cái dict slot mà bản rút gọn đang giấu,
    nên để nguyên là để lại một cửa xác nhận bằng danh sách ứng viên - đúng cửa
    mà luật muối tồn tại để đóng.

    Đổi `space` thành `<space>_rut_gon`: lời tự khai đi vào `BaTyLe.space` rồi
    ra tiêu đề cột của trang ba tỷ lệ, nên không ai đọc nhầm nó thành ảnh đầy đủ.
    """
    bam_he = _So(muoi, "hyperedge", TIEN_TO_HYPEREDGE)
    bam_e = _So(muoi, "entity", TIEN_TO_ENTITY)
    bam_d = _So(muoi, "doc_key", TIEN_TO_DOC)

    space = str(anh["space"])
    if la_space_rut_gon(space):
        raise ValueError(
            f"{space!r} đã là một bản rút gọn: rút gọn hai lần là băm lên băm,"
            " và quan hệ bằng nhau thì giữ nguyên nên không ai phát hiện ra"
        )

    tai_lieu = [
        {
            "doc_key": bam_d(m["doc_key"]),
            "sha256": m["sha256"],
            "scope": m["scope"],
            "content_type": m["content_type"],
        }
        for m in anh["tai_lieu"]
    ]
    hyperedge = [
        {
            "id": bam_he(h["id"]),
            "doc_key": sorted(bam_d(d) for d in h["doc_key"]),
            "khoa": h["khoa"],
            "slots": {vai: sorted(bam_e(e) for e in gt) for vai, gt in h["slots"].items()},
        }
        for h in anh["hyperedge"]
    ]
    # Sắp lại theo id đã băm: thứ tự của ảnh đầy đủ là thứ tự id thật, và giữ nó
    # là để lộ thứ tự từ điển của những id đó - một mẩu thông tin nhỏ nhưng
    # không có lý do gì để cho đi.
    hyperedge.sort(key=lambda h: h["id"])
    tai_lieu.sort(key=lambda m: m["doc_key"])
    return {
        "version": anh["version"],
        "space": space + HAU_TO_RUT_GON,
        "ngay_do": anh["ngay_do"],
        "policy_version": anh["policy_version"],
        "so_tai_lieu": len(tai_lieu),
        "so_hyperedge": len(hyperedge),
        "so_hyperedge_da_nguon": sum(1 for h in hyperedge if len(h["doc_key"]) > 1),
        "tai_lieu": tai_lieu,
        "hyperedge": hyperedge,
    }
