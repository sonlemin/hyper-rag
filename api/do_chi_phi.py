"""Nạp tài liệu bằng pipeline ingest và đo thô chi phí LLM/embedding (FR-30 bậc 1).

    uv run python -m api.do_chi_phi eval/data                      # nạp cả thư mục
    uv run python -m api.do_chi_phi eval/data/01-cap-quyen-gitlab.txt  # nạp từng file
    uv run python -m api.do_chi_phi --xoa-space --space synth      # xóa sạch một space
    uv run python -m api.do_chi_phi --xoa-space --space real /duong/dan/real  # kèm đối chiếu .space
    uv run python -m api.do_chi_phi eval/data --xuat-json eval/so_do_nap/nap-that.json

Từ story 2.3 script không tự mở ngữ cảnh hệ thống hay đợt nữa: nó quét đường
dẫn bằng `core.ingest_scan` rồi giao cho `api.dot_nap.chay_lan_nap` - đúng lõi
mà màn nạp web (story 2.7) dùng, nên hai lối vào không thể trôi khỏi nhau.
Nhãn quyền của mỗi tài liệu đọc từ frontmatter `scope`/`content_type` của chính
file; file hỏng bị từ chối kèm mã, không chặn file kế; re-ingest ghi đè sạch.

In số fact hợp lệ / bị loại của từng tài liệu (story 2.4, cùng số đi vào sự
kiện `extract_doc`), rồi tổng token và USD đọc từ `audit_log` cho **từng tài
liệu** (theo mốc thời gian bắt đầu/kết thúc mà pipeline ghi lại) rồi cả đợt;
ngoại lệ giữa đợt (đối chiếu lệch, 429) vẫn in số đã tiêu rồi mới dội lên.
Nạp cả một thư mục thì thư mục đó phải khai space của chính nó trong file
`.space` (story 2.11); lệch với `--space` là từ chối trước khi mở kết nối nào.
`--xuat-json` ghi đúng số đó thành file có commit để `eval/ngoai_suy.py` đọc,
thay cho sáu hằng chép tay. Nằm ở `api/` vì `eval/` không import được hiện
thực Postgres. Script tốn tiền thật: chạy sau khi spec được duyệt.

Biến môi trường: bảy khóa kho (`adapters.engine.BIEN_MOI_TRUONG`), năm biến
Postgres (`api.audit_postgres.BIEN_POSTGRES`), ba biến model
(`adapters.llm_wrapper.BIEN_MOI_TRUONG_MODEL`) và key provider. Trên máy chủ,
host của các kho là IP container (`docker inspect`), key đọc từ `.env`;
`scripts/chay-may-chu.sh` dựng sẵn đủ bộ đó.
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from adapters.chunking import cau_hinh_chunk, chia_chunk, dem_token
from adapters.ingest import (
    TRANG_THAI_DA_NAP,
    TRANG_THAI_DA_XOA,
    TRANG_THAI_KHONG_DOI,
    KetQuaNap,
    SoTaiLieu,
    xoa_space,
)
from adapters.llm_wrapper import BIEN_LLM_MODEL
from adapters.model_catalog import (
    LOAI_EMBEDDING,
    LOAI_LLM,
    DanhMucModel,
    ModelUnknown,
    danh_muc_mac_dinh,
)
from adapters.policy_loader import load_policy
from adapters.trich_xuat import dung_prompt, khoi_tu_dien
from adapters.tu_dien_thuc_the import TuDienThucTheInvalid, tai_tu_dien_thuc_the
from api.audit_postgres import AuditPostgres, TongChiPhi
from api.dot_nap import (
    duong_dan_tu_dien,
    TRANG_THAI_DOT_XONG,
    LanNap,
    chay_lan_nap,
    dung_engine_tu_moi_truong,
    ghi_so_do_json,
    so_do_nap,
)
from api.nguon_thu_muc import (
    TEN_FILE_SPACE,
    SpaceKhaiKhongHopLe,
    SpaceKhongKhai,
    SpaceLechThuMuc,
    cac_file_nap,
    kiem_space_thu_muc,
    thu_muc_cha_chung,
)
from core.audit import thoi_diem_utc
from core.ingest_scan import KetQuaQuet, quet_cac_file

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-day-du.yaml"

# Tiền tố của dòng `lenh` ghi vào file số đo: người đọc chương 4 phải dựng lại
# được đúng lệnh đã sinh ra con số, không chỉ biết "một lần nạp nào đó".
TIEN_TO_LENH: str = "uv run python -m api.do_chi_phi"

# Cờ xem trước chi phí (story 2.13). Nêu tên trong thông điệp từ chối để người
# chạy biết đường xem trước tồn tại trước khi tiêu tiền.
CO_UOC_TINH: str = "--uoc-tinh"

# Thư mục file số đo của các đợt đã chạy. `--uoc-tinh` đọc nó để lấy tỷ lệ
# token ra/vào **đo được**, không dùng một hằng: đường cục bộ và đường API ngoài
# lệch nhau khoảng ba lần, nên một hằng chung cho cả hai là một con số không nói
# về đợt nào. Khoảng cụ thể của từng model **đọc lại từ file mỗi lần chạy**
# (`khoang_ty_le_da_do`), không chép vào bình luận này: một con số chép ở đây
# lỗi thời ngay ở đợt kế. Đọc *file dữ liệu*, không import `eval/`: chiều import
# cấm `api/` -> `eval/` (`tests/test_import_lint.py`).
THU_MUC_SO_DO: Path = REPO_ROOT / "eval" / "so_do_nap"


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Nạp tài liệu qua pipeline ingest và đo chi phí LLM/embedding")
    p.add_argument("duong_dan", nargs="*", type=Path, help="một thư mục, hoặc các file .md/.txt theo thứ tự")
    p.add_argument(
        "--space",
        default="synth",
        help=f"không gian dữ liệu (mặc định synth); nạp cả một thư mục thì phải"
        f" khớp tên space thư mục khai trong {TEN_FILE_SPACE}",
    )
    p.add_argument("--xoa-space", action="store_true", help="xóa sạch space rồi thoát, không nạp gì")
    p.add_argument("--ep-ghi-de", action="store_true", help="re-ingest cả tài liệu không đổi (cùng sha256 và nhãn)")
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH, help="bảng chính sách lấy policy_version")
    p.add_argument(
        "--xuat-json",
        type=Path,
        default=None,
        metavar="FILE",
        help="ghi số đo của đợt (token/USD theo model) thành JSON; file này có commit",
    )
    p.add_argument(
        CO_UOC_TINH,
        action="store_true",
        help="in số lời gọi và tiền dự kiến rồi thoát; không gọi LLM, không chạm kho",
    )
    p.add_argument(
        "--model",
        default=None,
        help=f"model LLM để ước tính (mặc định đọc {BIEN_LLM_MODEL}); chỉ dùng với {CO_UOC_TINH}",
    )
    ts = p.parse_args(argv)
    if not ts.xoa_space and not ts.duong_dan:
        p.error("cần một thư mục hoặc ít nhất một file, hoặc --xoa-space")
    if ts.xoa_space and len(ts.duong_dan) > 1:
        p.error("--xoa-space nhận nhiều nhất một thư mục, để đối chiếu .space")
    if ts.xoa_space and ts.duong_dan and not ts.duong_dan[0].is_dir():
        p.error("--xoa-space chỉ nhận một *thư mục* (để đọc .space), không nhận file")
    if ts.xoa_space and ts.xuat_json:
        p.error("--xuat-json cần một đợt nạp, không đi cùng --xoa-space")
    # Hai rào liên cờ của `--uoc-tinh`. Chúng không phải chuyện gọn dòng lệnh:
    # `--xuat-json` ghi đè mẫu số của bảng ngoại suy FR-30, và một lần xem trước
    # mà ghi ra file số đo là ghi một đợt chưa chạy đè lên một đợt đã trả tiền.
    # `--xoa-space` thì ngược chiều hẳn với "xem trước": nó là lệnh phá.
    if ts.uoc_tinh and ts.xuat_json:
        p.error(f"{CO_UOC_TINH} không đi cùng --xuat-json: xem trước không tiêu tiền nên"
                " nó không có số đo nào để ghi, và ghi đè file số đo bằng một đợt chưa"
                " chạy là mất mẫu số của bảng ngoại suy FR-30")
    if ts.uoc_tinh and ts.xoa_space:
        p.error(f"{CO_UOC_TINH} không đi cùng --xoa-space: một lệnh xem trước và một"
                " lệnh xóa sạch space là hai chiều ngược nhau")
    if ts.uoc_tinh and not ts.duong_dan:
        p.error(f"{CO_UOC_TINH} cần đúng nguồn của đợt sắp chạy: một thư mục hoặc"
                " danh sách file")
    if ts.model and not ts.uoc_tinh:
        p.error(f"--model chỉ dùng với {CO_UOC_TINH}; đợt nạp thật đọc model từ"
                f" {BIEN_LLM_MODEL} như wrapper đọc, không từ dòng lệnh")
    return ts


# ---------------------------------------------------------------------------
# Xem trước chi phí trước khi tiêu tiền (story 2.13)
# ---------------------------------------------------------------------------


class SoDoNapKhongDocDuoc(RuntimeError):
    """Không tra được tỷ lệ token ra/vào cho model của đợt sắp chạy.

    Không phải một lỗi chặn: `--uoc-tinh` vẫn in phần nó đếm được (số lời gọi và
    token vào) rồi nói thẳng là phần token ra chưa ước được. Lớp này chỉ để nơi
    gọi phân biệt "chưa đo lần nào" với "đọc file hỏng".
    """

    code = "SO_DO_NAP_KHONG_DOC_DUOC"


@dataclass(frozen=True)
class TyLeTokenRa:
    """Tỷ lệ token ra / token vào **đo được** của một model, kèm nguồn của nó."""

    model: str
    ty_le: float
    nguon: str
    ngay: str
    token_vao: int
    token_ra: int


def cac_so_do_nap(thu_muc: Path | None = None) -> list[dict]:
    """Mọi file số đo đọc được, mới nhất trước; file hỏng bị bỏ qua lặng lẽ.

    Bỏ qua lặng lẽ là đúng ở đây và chỉ ở đây: đây là đường *xem trước*, không
    phải đường đọc mẫu số của chương 4 (`eval/ngoai_suy.py` mới là chỗ một file
    hỏng phải làm cả lệnh đỏ). Một file rách không được biến `--uoc-tinh` thành
    một lệnh không chạy được, vì khi ấy người ta bỏ luôn bước xem trước.
    """
    thu_muc = THU_MUC_SO_DO if thu_muc is None else Path(thu_muc)
    if not thu_muc.is_dir():
        return []
    ra: list[dict] = []
    for f in sorted(thu_muc.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(d, dict) and isinstance(d.get("theo_model"), list):
            ra.append({**d, "_ten_file": f.name})
    ra.sort(key=lambda d: str(d.get("ngay") or ""), reverse=True)
    return ra


def ty_le_token_ra(model: str, thu_muc: Path | None = None) -> TyLeTokenRa | None:
    """Tỷ lệ token ra/vào của **chính model đó**, từ đợt nạp gần nhất; không có thì `None`.

    Của chính model đó chứ không phải một trung bình chung: Qwen cục bộ cho 1,04
    còn DeepSeek cho 0,38-0,39, lệch nhau gần ba lần. Một tỷ lệ chung là một con
    số không nói về đợt nào, và ước sai gần ba lần trên khoản đắt nhất của hóa
    đơn (giá token ra gấp ba giá token vào ở DeepSeek).

    Chưa đo lần nào cho model đó thì trả `None`, và nơi gọi in ra rằng phần token
    ra chưa ước được. Đó là câu trung thực nhất nói được; một hằng chọn đại cho
    một model chưa chạy bao giờ đọc y như một số đo.
    """
    for d in cac_so_do_nap(thu_muc):
        for dong in d["theo_model"]:
            if not isinstance(dong, dict) or dong.get("model") != model:
                continue
            if dong.get("loai") != LOAI_LLM:
                continue
            vao, ra = dong.get("token_vao"), dong.get("token_ra")
            if not isinstance(vao, int) or not isinstance(ra, int) or vao <= 0:
                continue
            return TyLeTokenRa(
                model=model,
                ty_le=ra / vao,
                nguon=d["_ten_file"],
                ngay=str(d.get("ngay") or "?"),
                token_vao=vao,
                token_ra=ra,
            )
    return None


# Số đợt tối đa nêu tên trong dòng "embedding chiếm bao nhiêu". Không có trần
# thì dòng đó dài thêm mỗi lần nạp, và một dòng dài dần là một dòng người ta
# thôi đọc. Ba đợt gần nhất đủ để thấy con số ổn định hay không; phần còn lại
# gộp thành một khoảng.
SO_DOT_NEU_TEN_EMBEDDING: int = 3


def khoang_ty_le_da_do(thu_muc: Path | None = None) -> dict[str, tuple[float, float]]:
    """`{model: (tỷ lệ nhỏ nhất, lớn nhất)}` trên mọi đợt đã đo. Đọc lại từ file.

    Dùng cho một câu duy nhất: nói vì sao token ra **không** ước bằng một hằng
    chung. Câu đó từng chép cứng "Qwen 1,04 và DeepSeek 0,38-0,39", và nó sai
    ngay ở đợt DeepSeek thứ ba (0,42). Một câu giải thích mà tự nó lỗi thời thì
    người đọc mất luôn lý do tin phần còn lại của dòng.
    """
    gom: dict[str, list[float]] = {}
    for d in cac_so_do_nap(thu_muc):
        for dong in d["theo_model"]:
            if not isinstance(dong, dict) or dong.get("loai") != LOAI_LLM:
                continue
            vao, ra = dong.get("token_vao"), dong.get("token_ra")
            if isinstance(vao, int) and isinstance(ra, int) and vao > 0:
                gom.setdefault(str(dong.get("model")), []).append(ra / vao)
    return {m: (min(v), max(v)) for m, v in sorted(gom.items())}


def phan_embedding_da_do(thu_muc: Path | None = None) -> list[tuple[str, float]]:
    """`[(tên file, phần USD của embedding)]` của những đợt **có trả tiền**.

    Embedding không được ước, và đây là câu thay thế: số lời gọi embedding phụ
    thuộc số entity và hyperedge mà LLM sắp sinh ra, tức phụ thuộc đúng thứ chưa
    chạy. Một con số bịa cho nó tệ hơn một dòng nói thẳng là chưa ước, nhưng một
    dòng nói thẳng kèm phần nó đã chiếm ở các đợt đã đo thì dùng được.

    Đợt 0 USD (đường cục bộ) bị loại: phần trăm trên một tổng bằng 0 không có
    nghĩa, và một đợt miễn phí không nói gì về hóa đơn của đợt sắp chạy.
    """
    ra: list[tuple[str, float]] = []
    for d in cac_so_do_nap(thu_muc):
        tong = (d.get("tong") or {}).get("chi_phi_usd")
        if not isinstance(tong, (int, float)) or tong <= 0:
            continue
        emb = sum(
            float(dong.get("chi_phi_usd") or 0.0)
            for dong in d["theo_model"]
            if isinstance(dong, dict) and dong.get("loai") == LOAI_EMBEDDING
        )
        ra.append((d["_ten_file"], emb / tong))
    return ra


@dataclass(frozen=True)
class UocTinhDot:
    """Ước tính một đợt nạp: hàm thuần trên kết quả quét, **không** gọi LLM.

    Nó chỉ hứa phần nó đo được, và ba giới hạn dưới đây đi thẳng vào `dong_in()`
    chứ không nằm trong tài liệu:

    - **Số lời gọi LLM là số đếm chính xác**: đúng bằng số chunk mà đường nạp sẽ
      cắt ra, bằng chính `adapters/chunking.py` mà `EngineACL.ainsert` dùng.
    - **Token vào đếm thật** trên chuỗi prompt sắp gửi, nhưng thiếu phần bọc hội
      thoại của provider (~25-30%).
    - **Token ra là ước theo tỷ lệ đo được** của model đó ở đợt gần nhất, không
      theo một hằng; chưa đo lần nào thì không ước.

    Embedding không có mặt trong con số tiền, chỉ có mặt trong một dòng nói phần
    nó đã chiếm ở các đợt đã trả tiền - **đọc lại từ file mỗi lần chạy**, không
    chép cứng: ba đợt DeepSeek tính tới 05/09 cho 1,9%, 2,3% và 2,3%, và một câu
    "hai đợt" viết cứng ở đây sẽ sai ngay ở đợt thứ ba.
    """

    model: str
    space: str
    so_tai_lieu: int
    so_tu_choi: int
    so_loi_goi: int
    token_vao: int
    ty_le: TyLeTokenRa | None
    token_ra_uoc: int | None
    chi_phi_usd: float | None
    chi_phi_vao_usd: float
    phan_embedding: tuple[tuple[str, float], ...]
    khoang_ty_le: Mapping[str, tuple[float, float]]

    def _vi_sao_khong_hang(self) -> str:
        """Câu giải thích "không dùng một hằng chung", dựng từ chính các đợt đã đo."""
        if len(self.khoang_ty_le) < 2:
            return ""
        phan = ", ".join(
            f"{m} {a:.2f}" if a == b else f"{m} {a:.2f}-{b:.2f}"
            for m, (a, b) in self.khoang_ty_le.items()
        )
        return f", không theo một hằng chung: {phan}"

    def dong_in(self) -> str:
        dong = [
            f"ước tính đợt nạp vào space {self.space!r} trên {self.model}:"
            f" {self.so_tai_lieu} tài liệu qua cửa quét"
            + (f" ({self.so_tu_choi} file bị từ chối)" if self.so_tu_choi else "")
            + f", {self.so_loi_goi} lời gọi LLM (số đếm chính xác, bằng số chunk),"
            f" {self.token_vao} token vào (đếm thật bằng bộ tách của đường nạp)."
        ]
        if self.ty_le is None or self.token_ra_uoc is None or self.chi_phi_usd is None:
            dong.append(
                f"  Token ra **chưa ước được**: không có đợt nạp nào đã đo"
                f" {self.model} trong {THU_MUC_SO_DO.name}/. Riêng token vào là"
                f" khoảng {self.chi_phi_vao_usd:.6f} USD theo đơn giá danh mục;"
                " phần token ra là ẩn số, và ở DeepSeek nó đắt gấp ba token vào."
            )
        else:
            dong.append(
                f"  Token ra ước {self.token_ra_uoc} theo tỷ lệ ra/vào"
                f" **{self.ty_le.ty_le:.3f} đo được** ở {self.ty_le.nguon}"
                f" ({self.ty_le.token_ra}/{self.ty_le.token_vao}, đợt"
                f" {self.ty_le.ngay[:10]}){self._vi_sao_khong_hang()}."
            )
            dong.append(
                f"  Khoảng **{self.chi_phi_usd:.6f} USD** theo đơn giá danh mục"
                f" (riêng token vào {self.chi_phi_vao_usd:.6f})."
            )
        if self.phan_embedding:
            neu_ten = self.phan_embedding[:SO_DOT_NEU_TEN_EMBEDDING]
            phan = ", ".join(f"{p:.1%} ({ten})" for ten, p in neu_ten)
            con_lai = len(self.phan_embedding) - len(neu_ten)
            if con_lai:
                khac = [p for _, p in self.phan_embedding[len(neu_ten):]]
                phan += (
                    f"; {con_lai} đợt cũ hơn trong khoảng"
                    f" {min(khac):.1%}-{max(khac):.1%}"
                )
            dong.append(
                f"  Embedding **không được ước**: số lời gọi của nó phụ thuộc số"
                " entity và hyperedge mà LLM sắp sinh ra, tức phụ thuộc đúng thứ"
                f" chưa chạy. Ở {len(self.phan_embedding)} đợt đã trả tiền nó chiếm"
                f" {phan} tổng USD."
            )
        else:
            dong.append(
                "  Embedding **không được ước** và chưa có đợt trả tiền nào để"
                " nói nó chiếm bao nhiêu."
            )
        dong.append(
            "  Con số tiền là **cùng bậc, không bảo đảm chiều**: token vào đếm"
            " thiếu phần bọc hội thoại của provider (~25-30%), token ra là ước"
            " theo một đợt khác. Đừng đọc nó như một trần chi."
        )
        return "\n".join(dong)


def uoc_tinh_dot(
    quet: KetQuaQuet,
    model: str,
    *,
    space: str = "?",
    danh_muc: DanhMucModel | None = None,
    thu_muc_so_do: Path | None = None,
) -> UocTinhDot:
    """Ước tính một đợt từ kết quả quét. Hàm thuần: không gọi LLM, không chạm kho.

    **Đọc cả khối từ điển thực thể** (story 2.12): nó nằm trong prompt nên nó
    vào token vào, và nó được lọc theo `scope` của **từng tài liệu** đúng như
    đường nạp lọc. Bỏ nó đi thì xem trước của một space có từ điển thấp hơn thực
    tế một cách có hệ thống - nhỏ ở đây (vài chục token mỗi lời gọi) nhưng lệch
    đúng chiều mà cờ này tồn tại để cảnh báo, và nó lệch *thầm*.
    """
    danh_muc = danh_muc_mac_dinh() if danh_muc is None else danh_muc
    muc = danh_muc.muc(model, loai=LOAI_LLM)
    cau_hinh = cau_hinh_chunk()
    tu_dien = _tu_dien_cua_space(space)
    khoi_theo_scope: dict[str, str] = {}
    so_loi_goi = token_vao = 0
    for t in quet.chap_nhan:
        if t.scope not in khoi_theo_scope:
            khoi_theo_scope[t.scope] = (
                "" if tu_dien is None else khoi_tu_dien(tu_dien.muc_cho_scope(t.scope))
            )
        khoi = khoi_theo_scope[t.scope]
        for chunk in chia_chunk(t.noi_dung, cau_hinh):
            so_loi_goi += 1
            token_vao += dem_token(dung_prompt(chunk["content"], khoi), cau_hinh)
    ty_le = ty_le_token_ra(muc.ten, thu_muc_so_do)
    token_ra = round(token_vao * ty_le.ty_le) if ty_le is not None else None
    return UocTinhDot(
        model=muc.ten,
        space=space,
        so_tai_lieu=len(quet.chap_nhan),
        so_tu_choi=len(quet.tu_choi),
        so_loi_goi=so_loi_goi,
        token_vao=token_vao,
        ty_le=ty_le,
        token_ra_uoc=token_ra,
        chi_phi_usd=None if token_ra is None else muc.chi_phi_usd(token_vao, token_ra),
        chi_phi_vao_usd=muc.chi_phi_usd(token_vao, 0),
        phan_embedding=tuple(phan_embedding_da_do(thu_muc_so_do)),
        khoang_ty_le=khoang_ty_le_da_do(thu_muc_so_do),
    )


def _tu_dien_cua_space(space: str):
    """Từ điển của một space theo quy ước, hoặc `None`; hỏng thì cũng `None`.

    Đường **xem trước** không được chết vì một file cấu hình hỏng: đợt nạp thật
    sẽ dội đúng lỗi đó ở `trich_xuat_chunks` trước lời gọi LLM đầu tiên, và ở
    đây một traceback chỉ làm người chạy bỏ luôn bước xem trước - tức bỏ đúng
    thứ cờ này dựng ra.
    """
    try:
        duong_dan = duong_dan_tu_dien(space)
    except (TypeError, ValueError):
        # `space` mặc định của hàm ước tính là `"?"` (nơi gọi không truyền), và
        # nó không phải một space hợp lệ. Không có space thì không có quy ước
        # nào để tra, và đó là "không từ điển" chứ không phải một lỗi.
        return None
    if duong_dan is None:
        return None
    try:
        return tai_tu_dien_thuc_the(duong_dan)
    except TuDienThucTheInvalid as loi:
        print(f"cảnh báo: không đọc được từ điển {duong_dan}: {loi}", file=sys.stderr)
        return None


def model_cua_moi_truong(moi_truong=None) -> str | None:
    """Tên model LLM mà đợt nạp sẽ dùng, đọc từ đúng biến mà wrapper đọc."""
    nguon = os.environ if moi_truong is None else moi_truong
    ten = str(nguon.get(BIEN_LLM_MODEL) or "").strip()
    return ten or None


def _so_tai_lieu_cua_space(engine, space: str) -> str:
    """Số tài liệu trong sổ của một space, dạng chuỗi để in; hỏng thì nói hỏng.

    Đọc thuần, và **không** được làm hỏng lệnh xóa: nếu sổ không đọc được thì
    câu trả lời là "không đọc được sổ", không phải một traceback trước khi xóa.
    """
    try:
        return str(len(SoTaiLieu.mo(engine.working_dir, space).cac_doc_key()))
    except Exception as loi:  # noqa: BLE001 - in ra rồi đi tiếp, không chặn xóa
        return f"không đọc được sổ ({type(loi).__name__}: {loi})"


def in_tong(tieu_de: str, tong: TongChiPhi) -> None:
    print(f"\n{tieu_de}")
    print(f"{'model':<28}{'provider':<12}{'lần':>6}{'token vào':>12}{'token ra':>10}{'USD':>12}")
    for d in tong.theo_model:
        print(
            f"{d.model:<28}{d.nha_cung_cap:<12}{d.so_lan:>6}{d.token_vao:>12}{d.token_ra:>10}"
            f"{d.chi_phi_usd:>12.6f}"
        )
    print(
        f"{'TỔNG':<28}{'':<12}{tong.so_lan:>6}{tong.token_vao:>12}{tong.token_ra:>10}"
        f"{tong.chi_phi_usd:>12.6f}"
    )


def in_ket_qua(kq: KetQuaNap) -> None:
    for tc in kq.tu_choi:
        print(f"TỪ CHỐI {tc.ten}: {tc.ma} - {tc.ly_do}")
    for t in kq.tai_lieu:
        so = (
            f"{t.so_chunk} chunk, {t.so_hyperedge} hyperedge, {t.so_entity} entity,"
            f" {t.so_fact_hop_le} fact hợp lệ, {t.so_fact_loai} fact loại, {t.so_chunk_hong} chunk hỏng"
        )
        if t.trang_thai == TRANG_THAI_DA_NAP:
            print(f"{'RE-INGEST' if t.re_ingest else 'NẠP'} {t.doc_key}: {so}")
        elif t.trang_thai == TRANG_THAI_DA_XOA:
            print(f"XÓA {t.doc_key}: {so}")
        elif t.trang_thai == TRANG_THAI_KHONG_DOI:
            print(f"KHÔNG ĐỔI {t.doc_key}: giữ nguyên ({so})")
        else:
            print(f"{t.trang_thai.upper()} {t.doc_key}: {t.ma} - {t.ly_do}")


def _in_dot(lan: LanNap) -> None:
    """Đầu ra console của một đợt: kết quả từng tài liệu, bảng theo tài liệu, bảng cả đợt."""
    in_ket_qua(lan.ket_qua)
    for c in lan.chi_phi_tai_lieu:
        in_tong(f"Tài liệu {c.doc_key} ({c.bat_dau} -> {c.ket_thuc or 'chưa xong'}):", c.tong)
    if lan.chi_phi is not None:
        in_tong(f"Cả đợt (thoi_diem >= {lan.bat_dau}):", lan.chi_phi)


def _xuat_json(ts: argparse.Namespace, lan: LanNap, argv: list[str]) -> None:
    """Ghi file số đo, chỉ khi đợt chạy trọn.

    Đợt dừng giữa chừng vẫn tiêu tiền thật, nhưng số của nó là số của *một
    phần* corpus; ghi đè lên file mà `eval/ngoai_suy.py` đọc là làm bảng ngoại
    suy của chương 4 nhỏ đi mà không ai biết vì sao. Nên đợt lỗi thì in một
    dòng nói không ghi, còn console vẫn có đủ số để đọc bằng mắt.
    """
    if lan.trang_thai != TRANG_THAI_DOT_XONG:
        print(
            f"\nkhông ghi {ts.xuat_json}: đợt dừng ở trạng thái {lan.trang_thai!r}"
            f" ({lan.ma_loi}); số đo của một đợt dở không thay được số đo cũ",
            flush=True,
        )
        return
    so_do = so_do_nap(lan, lenh=f"{TIEN_TO_LENH} {' '.join(argv)}")
    # Một đợt *chạy trọn* vẫn ra file vô nghĩa được: LLM trả `{"facts": []}` cho
    # mọi tài liệu thì mỗi tài liệu mang `KHONG_CO_FACT`, đợt vẫn `xong`, mà
    # `so_tai_lieu` là 0 - và `eval/ngoai_suy.py` chia cho nó. Cửa này chặn ở
    # nơi rẻ nhất: đừng ghi đè nguồn số của chương 4 bằng một file không dùng
    # được, bản cũ vẫn hơn.
    thieu = []
    if so_do["so_tai_lieu"] <= 0:
        thieu.append("không tài liệu nào nạp được (so_tai_lieu = 0)")
    if not so_do["theo_model"]:
        thieu.append("không lời gọi LLM/embedding nào trong cửa sổ của đợt")
    if thieu:
        print(
            f"\nkhông ghi {ts.xuat_json}: {'; '.join(thieu)}."
            " File số đo là mẫu số của bảng ngoại suy FR-30, nên bản cũ được giữ nguyên.",
            flush=True,
        )
        return
    dich = ghi_so_do_json(ts.xuat_json, so_do)
    print(f"\nghi số đo đợt vào {dich}", flush=True)


def quet_nguon(duong_dan) -> KetQuaQuet:
    """Quét nguồn của một đợt: cùng một lõi cho đường nạp và đường xem trước.

    Không gọi `quet_thu_muc`: nó duyệt **mọi** file nên `.space` sẽ thành một
    dòng `DINH_DANG_LA` giả trong danh sách từ chối. Quét đúng danh sách ứng
    viên đã bỏ file ẩn, qua cùng lõi kiểm.

    Dùng chung là điều kiện để `--uoc-tinh` nói về đúng đợt sắp chạy: một bản
    quét thứ hai ở nhánh xem trước sẽ trôi khỏi bản của nhánh nạp, và khi đó số
    lời gọi in ra không phải số lời gọi sắp gọi.
    """
    duong_dan = list(duong_dan)
    if len(duong_dan) == 1 and Path(duong_dan[0]).is_dir():
        return quet_cac_file(cac_file_nap(duong_dan[0]))
    return quet_cac_file(duong_dan)


def in_uoc_tinh(ts: argparse.Namespace) -> int:
    """Nhánh `--uoc-tinh`: in rồi thoát 0. Không mở kết nối nào, không gọi LLM.

    Chạy trong `main()` **trước** `asyncio.run(chay(...))`, cùng chỗ với
    `_rao_space` và cùng lý do: `chay()` mở `AuditPostgres` ở dòng đầu, và một
    lệnh xem trước không được đòi Postgres đang chạy mới xem được.
    """
    model = ts.model or model_cua_moi_truong()
    if not model:
        print(
            f"không biết ước tính trên model nào: đặt {BIEN_LLM_MODEL} (đợt nạp"
            f" thật đọc đúng biến đó) hoặc truyền --model. Không có mặc định:"
            " một model đoán hộ cho một con số tiền nói về đợt khác",
            file=sys.stderr,
        )
        return 1
    try:
        uoc = uoc_tinh_dot(quet_nguon(ts.duong_dan), model, space=ts.space)
    except (ModelUnknown, FileNotFoundError) as loi:
        print(f"{getattr(loi, 'code', type(loi).__name__)}: {loi}", file=sys.stderr)
        return 1
    if uoc.so_tai_lieu == 0:
        # "0 lời gọi, 0 USD" rồi thoát 0 đọc y như một đợt miễn phí, và đó là
        # câu trả lời sai cho câu hỏi duy nhất mà cờ này trả lời.
        print(
            f"không tài liệu nào qua được cửa quét ({uoc.so_tu_choi} file bị từ"
            " chối): ước tính sẽ là 0 lời gọi và 0 USD, đọc y như một đợt miễn"
            " phí thay vì một thư mục nguồn sai",
            file=sys.stderr,
        )
        return 1
    print(uoc.dong_in())
    return 0


async def chay(ts: argparse.Namespace, argv: list[str] | None = None) -> TongChiPhi:
    policy = load_policy(ts.policy)
    audit = await AuditPostgres.mo()
    try:
        await audit.khoi_tao()
        if ts.xoa_space:
            # Bảng "Cả đợt" in cho *mọi* nhánh, đúng như bản trước story 2.7
            # (nó nằm trong `finally` nên nhánh xóa cũng có): xóa space là một
            # thao tác có thể tốn tiền embedding lúc `khoi_tao()` lại collection,
            # và một nhánh im lặng là một nhánh không ai đọc được đã tiêu gì.
            bat_dau = thoi_diem_utc()
            engine = dung_engine_tu_moi_truong(audit, space=ts.space)
            try:
                # In số tài liệu sắp mất **trước** khi mất. Một lệnh xóa không
                # nói nó sắp xóa bao nhiêu là một lệnh mà người chạy chỉ biết
                # mình gõ nhầm space sau khi đã xóa xong.
                print(
                    f"[{thoi_diem_utc()}] sắp xóa sạch space {ts.space!r}:"
                    f" {_so_tai_lieu_cua_space(engine, ts.space)} tài liệu trong sổ",
                    flush=True,
                )
                await xoa_space(engine, space=ts.space, policy_version=policy.policy_version, audit=audit)
                print(f"[{thoi_diem_utc()}] đã xóa sạch space {ts.space!r}", flush=True)
            finally:
                await engine.dong()
            tong = await audit.tong_chi_phi(ts.space, tu=bat_dau)
            in_tong(f"Cả đợt (thoi_diem >= {bat_dau}):", tong)
            return tong

        quet = quet_nguon(ts.duong_dan)
        lan = await chay_lan_nap(
            quet,
            space=ts.space,
            policy_version=policy.policy_version,
            audit=audit,
            ep_ghi_de=ts.ep_ghi_de,
        )
        _in_dot(lan)
        if ts.xuat_json:
            _xuat_json(ts, lan, list(argv or []))
        if lan.ngoai_le is not None:
            # Số đã in xong; giờ mới để lỗi dội lên như trước story 2.7.
            raise lan.ngoai_le
        return lan.chi_phi
    finally:
        await audit.dong()


def _rao_space(ts: argparse.Namespace) -> None:
    """Thư mục nguồn phải khai space của chính nó và khai đúng cờ `--space`.

    Chạy trong `main()` chứ không trong `chay()`: `chay()` mở Postgres ở dòng
    đầu, và một lần gõ nhầm cờ không đáng phải mở kết nối nào - "trước lời gọi
    kho đầu tiên" của I/O Matrix nghĩa là *trước*, không phải "trước lời gọi
    LLM".

    Ba ca, không phải một:

    - **Một thư mục** (nạp hoặc `--xoa-space`): đối chiếu `.space` của nó. Nhánh
      xóa cần rào này hơn nhánh nạp: `--xoa-space --space synth` khi định gõ
      `real` xóa sạch corpus của Đo 2 và Đo 3, không hỏi lại câu nào.
    - **Danh sách file rời cùng một thư mục cha** đã khai `.space`: đối chiếu
      luôn. Đây là ca `real/*.md --space synth` mà shell bung ra, tức đúng lệnh
      nguy hiểm nhất lại đi lọt vì nó không còn hình dạng "một thư mục".
    - **Danh sách file rời không có `.space` nào**: chạy như trước. Đó là ca soát
      một tài liệu lẻ, và I/O Matrix của spec khai nó tường minh.
    """
    if ts.duong_dan and ts.duong_dan[0].is_dir() and len(ts.duong_dan) == 1:
        kiem_space_thu_muc(ts.duong_dan[0], ts.space)
        return
    if not ts.duong_dan:
        return
    cha = thu_muc_cha_chung(ts.duong_dan)
    if cha is not None and (cha / TEN_FILE_SPACE).exists():
        kiem_space_thu_muc(cha, ts.space)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    ts = _tham_so(argv)
    try:
        _rao_space(ts)
    except (SpaceKhongKhai, SpaceLechThuMuc, SpaceKhaiKhongHopLe) as loi:
        print(f"{loi.code}: {loi}", file=sys.stderr)
        raise SystemExit(1) from None
    if ts.uoc_tinh:
        # Trước `asyncio.run(chay(...))`: xem trước không mở Postgres, không mở
        # kho, không gọi LLM. Rào `.space` vẫn chạy trước nó - xem trước một đợt
        # với cờ `--space` sai là in một con số cho một space khác.
        raise SystemExit(in_uoc_tinh(ts))
    asyncio.run(chay(ts, argv))


if __name__ == "__main__":
    main()
