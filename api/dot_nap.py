"""Một đợt nạp: chạy pipeline rồi gom chi phí theo tài liệu (story 2.7).

Lõi dùng chung của `api/do_chi_phi.py` (dòng lệnh) và `api/man_nap.py` (màn
web). Không biết HTTP, không biết argparse: nhận một `KetQuaQuet` đã quét cùng
một port audit, trả một `LanNap` mang trạng thái từng tài liệu và số tiền.

Ba luật của module:

- **Không dựng đường ingest thứ hai.** Đợt gọi đúng `adapters.ingest.nap_cac_tai_lieu`
  mà CLI đang gọi; mọi thứ về khóa một tiến trình, sổ tài liệu, re-ingest và
  đối chiếu nằm nguyên ở đó.
- **Chi phí chỉ đọc từ `audit_log`**, theo cửa sổ nửa mở `[bat_dau, ket_thuc)`
  của từng tài liệu mà pipeline ghi lại. Không có bộ đếm thứ hai: hai bộ đếm
  là hai con số rồi sẽ lệch, và số nào đúng thì không ai biết.
- **Luôn gom chi phí, kể cả khi đợt nổ giữa chừng.** Lệch đối chiếu hay 429 của
  provider không xóa phần tiền đã tiêu. Ngoại lệ vì thế được ghi vào `LanNap`
  (mã ổn định + thông điệp) chứ không nuốt mất; ai cần dội nó lên thì đọc
  `LanNap.ngoai_le` - màn web thì không, script thì có.

Tiến trình per-document không cần cơ chế mới: `nap_cac_tai_lieu` append
`TrangThaiTaiLieu` vào `KetQuaNap` **trước** mỗi lần nạp, nên giữ tham chiếu
tới chính `LanNap.ket_qua` là đọc được tiến trình ở bất kỳ lúc nào. Tài liệu
"đang chạy" là mục có `bat_dau` mà chưa có `ket_thuc`.
"""

import asyncio
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from adapters.engine import EngineACL, cau_hinh_kho_tu_moi_truong
from adapters.ingest import MA_KHONG_CO_FACT, KetQuaNap, nap_cac_tai_lieu
from adapters.llm_wrapper import ham_tu_moi_truong
from adapters.model_catalog import DanhMucModel, danh_muc_mac_dinh
from api.audit_postgres import TongChiPhi
from core.audit import thoi_diem_utc
from core.ids import validate_space
from core.ingest_scan import KetQuaQuet

logger = logging.getLogger(__name__)

# Trạng thái một đợt. Ba giá trị, không hơn: đang chạy, xong, hoặc dừng vì lỗi.
# Trạng thái *từng tài liệu* là chuyện khác và sống ở `adapters.ingest`.
TRANG_THAI_DOT_DANG_CHAY: str = "dang_chay"
TRANG_THAI_DOT_XONG: str = "xong"
TRANG_THAI_DOT_LOI: str = "loi"

# Mã lỗi của đợt bị hủy (tiến trình màn tắt giữa chừng). Có mã riêng vì "bị
# hủy" khác hẳn "pipeline nổ": tiền đã tiêu vẫn thật, nhưng không có gì hỏng.
MA_DOT_BI_HUY: str = "DOT_BI_HUY"

# Lược đồ file số đo `--xuat-json`. `eval/ngoai_suy.py` khai lại cùng con số ở
# `VERSION_SO_DO_NAP` (chiều import cấm `eval` -> `api`, nên không dùng chung
# được một hằng); `tests/test_dot_nap.py` canh hai bên bằng nhau.
VERSION_SO_DO: int = 1

# Đuôi file tạm của bước ghi nguyên tử, cùng quy ước với sổ tài liệu.
DUOI_TAM: str = ".tmp"


@dataclass(frozen=True)
class ChiPhiTaiLieu:
    """Tiền của đúng một tài liệu: cửa sổ thời gian của nó và tổng trong cửa sổ đó."""

    doc_key: str
    bat_dau: str
    ket_thuc: str
    tong: TongChiPhi


@dataclass
class LanNap:
    """Một đợt nạp đang sống: trạng thái, kết quả pipeline, mốc, lỗi, tiền.

    `ket_qua` là chính object mà pipeline append trạng thái vào, nên đọc nó
    giữa chừng là thấy tiến trình; không có callback, không có hàng đợi sự
    kiện. `ngoai_le` giữ nguyên exception cho người gọi nào muốn dội lên.
    """

    dot_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    space: str = "synth"
    trang_thai: str = TRANG_THAI_DOT_DANG_CHAY
    ket_qua: KetQuaNap = field(default_factory=KetQuaNap)
    bat_dau: str = ""
    ket_thuc: str = ""
    ma_loi: str | None = None
    thong_diep_loi: str = ""
    ngoai_le: BaseException | None = None
    chi_phi: TongChiPhi | None = None
    chi_phi_tai_lieu: list[ChiPhiTaiLieu] = field(default_factory=list)

    def dang_chay(self) -> bool:
        return self.trang_thai == TRANG_THAI_DOT_DANG_CHAY


# Từ điển thực thể theo **quy ước tên space** (story 2.12, FR-32): space `X`
# dùng `config/tu-dien-thuc-the/X.yaml` nếu file đó có, không thì chạy không từ
# điển. Quy ước sống ở `api/` chứ không ở `adapters/` một cách có chủ đích: tầng
# adapter giữ luật "khóa cấu hình vắng nghĩa là **không có** từ điển, không có
# mặc định ngầm", còn đây là chỗ *một* quy ước của repo được áp cho **cả hai
# lối vào** - CLI `api.do_chi_phi` và màn nạp web đều đi qua `chay_lan_nap`.
#
# Vì sao không phải một biến môi trường và không phải một cờ dòng lệnh: đổi từ
# điển là đổi id entity và id hyperedge, tức re-ingest. Hai môi trường hai từ
# điển là hai kho không so được với nhau; và một cờ chỉ có ở CLI nghĩa là màn
# web nạp cùng tài liệu đó ra id khác, tức hai cửa cho hai kho.
THU_MUC_TU_DIEN: Path = Path(__file__).resolve().parent.parent / "config" / "tu-dien-thuc-the"


def duong_dan_tu_dien(space: str | None, thu_muc: Path | None = None) -> Path | None:
    """File từ điển của một space theo quy ước, hoặc `None` nếu không có.

    `None` cho cả ca không truyền space: đoán một từ điển cho một space không
    biết tên là đúng thứ luật ràng-theo-scope cấm.
    """
    if not space:
        return None
    # `space` đi thẳng vào một đường dẫn, nên nó phải qua cùng cửa hình dạng mà
    # cả hệ dùng: `--space ../../etc` mà không kiểm là một lệnh nạp đọc được một
    # YAML bất kỳ ngoài `config/tu-dien-thuc-the/`.
    validate_space(space)
    f = (THU_MUC_TU_DIEN if thu_muc is None else Path(thu_muc)) / f"{space}.yaml"
    return f if f.is_file() else None


def dung_engine_tu_moi_truong(audit, *, space: str | None = None) -> EngineACL:
    """`EngineACL` với provider thật, cấu hình kho đọc từ môi trường.

    Một hàm có tên vì cả script lẫn màn cần đúng một cách dựng engine; hai bản
    sao là hai bộ tham số sẽ trôi khỏi nhau.

    `space` chỉ dùng để tra từ điển thực thể theo quy ước tên file. Không truyền
    thì engine chạy **không** từ điển, đúng hành vi trước story 2.12.
    """
    ham = ham_tu_moi_truong(audit=audit)
    tu_dien = duong_dan_tu_dien(space)
    return EngineACL(
        **cau_hinh_kho_tu_moi_truong(),
        llm_model_func=ham.llm,
        embedding_func=ham.embedding,
        llm_model_max_token_size=ham.llm_max_token,
        entity_dictionary_path=None if tu_dien is None else str(tu_dien),
    )


async def chi_phi_theo_tai_lieu(audit, space: str, ket_qua: KetQuaNap) -> list[ChiPhiTaiLieu]:
    """Tiền của từng tài liệu đã chạy, đọc từ `audit_log` theo cửa sổ của nó.

    Bỏ qua tài liệu chưa có `bat_dau`: nó chưa từng chạy nên không có cửa sổ
    nào để hỏi, và hỏi một cửa sổ rỗng là mời một dòng 0 USD vô nghĩa vào bảng.
    Tài liệu đang dở (`ket_thuc` rỗng) hỏi cửa sổ mở, đúng cách
    `api/do_chi_phi.py` đang làm.
    """
    dong: list[ChiPhiTaiLieu] = []
    for t in ket_qua.tai_lieu:
        if not t.bat_dau:
            continue
        tong = await audit.tong_chi_phi(space, tu=t.bat_dau, den=t.ket_thuc or None)
        dong.append(ChiPhiTaiLieu(doc_key=t.doc_key, bat_dau=t.bat_dau, ket_thuc=t.ket_thuc, tong=tong))
    return dong


async def chay_lan_nap(
    quet: KetQuaQuet,
    *,
    space: str,
    policy_version: str,
    audit,
    lan: LanNap | None = None,
    ep_ghi_de: bool = False,
    tao_engine=None,
) -> LanNap:
    """Chạy một đợt trên kết quả quét đã có, rồi gom chi phí; không bao giờ ném.

    Engine dựng ở đây và đóng ở đây, kể cả khi đợt nổ: một engine không đóng là
    một pool Neo4j và một client Qdrant sống mãi trong tiến trình màn.
    """
    lan = LanNap(space=space) if lan is None else lan
    lan.space, lan.trang_thai, lan.bat_dau = space, TRANG_THAI_DOT_DANG_CHAY, thoi_diem_utc()
    # Seam tiêm giữ chữ ký cũ `(audit)`; đường thật thêm `space` để tra từ điển
    # thực thể theo quy ước tên file (story 2.12).
    engine = (
        dung_engine_tu_moi_truong(audit, space=space)
        if tao_engine is None
        else tao_engine(audit)
    )
    try:
        try:
            await nap_cac_tai_lieu(
                engine,
                quet.chap_nhan,
                space=space,
                policy_version=policy_version,
                audit=audit,
                tu_choi=quet.tu_choi,
                ket_qua=lan.ket_qua,
                ep_ghi_de=ep_ghi_de,
            )
            lan.trang_thai = TRANG_THAI_DOT_XONG
        except asyncio.CancelledError:
            # Hủy là chuyện của người gọi (tiến trình tắt), không phải một lỗi
            # của đợt: ghi trạng thái để đợt không kẹt ở `dang_chay`, rồi **dội
            # tiếp** để phép hủy lan tới nơi cần.
            lan.trang_thai = TRANG_THAI_DOT_LOI
            lan.ma_loi = MA_DOT_BI_HUY
            lan.thong_diep_loi = "đợt bị hủy giữa chừng"
            raise
        except Exception as loi:
            lan.trang_thai = TRANG_THAI_DOT_LOI
            # `code` là mã ổn định của dự án; ngoại lệ không có mã thì tên lớp,
            # vì một ô mã rỗng là một ô không assert được và không tra được.
            lan.ma_loi = getattr(loi, "code", None) or type(loi).__name__
            lan.thong_diep_loi = str(loi)
            lan.ngoai_le = loi
        finally:
            lan.ket_thuc = thoi_diem_utc()
            try:
                lan.chi_phi_tai_lieu = await chi_phi_theo_tai_lieu(audit, space, lan.ket_qua)
                lan.chi_phi = await audit.tong_chi_phi(space, tu=lan.bat_dau)
            except Exception:  # noqa: BLE001
                # Postgres rớt *cùng lúc* pipeline lỗi: một ngoại lệ ở đây thay
                # chỗ lỗi gốc và hàm ném dù docstring hứa không ném. Bảng tiền
                # thiếu là mất một tiện nghi; mất mã lỗi gốc là mất chẩn đoán.
                logger.exception("không gom được chi phí của đợt %s", lan.dot_id)
    finally:
        try:
            await engine.dong()
        except Exception:  # noqa: BLE001
            logger.exception("không đóng được engine của đợt %s", lan.dot_id)
    return lan


def dong_chi_phi_dict(dong) -> dict:
    """Một `DongChiPhi` dạng dict. Một bản duy nhất cho cả file số đo lẫn màn.

    Trước đây `api/man_nap.py` và hàm xuất JSON mỗi bên chép một danh sách
    trường của `DongChiPhi`; thêm một trường vào `TongChiPhi` mà quên một bên là
    hai đầu ra lệch nhau lặng lẽ.
    """
    return {
        "model": dong.model,
        "nha_cung_cap": dong.nha_cung_cap,
        "so_lan": dong.so_lan,
        "token_vao": dong.token_vao,
        "token_ra": dong.token_ra,
        "chi_phi_usd": dong.chi_phi_usd,
    }


def tong_chi_phi_dict(tong) -> dict | None:
    """Một `TongChiPhi` dạng dict (kèm các dòng theo model); `None` giữ nguyên `None`."""
    if tong is None:
        return None
    return {
        "so_lan": tong.so_lan,
        "token_vao": tong.token_vao,
        "token_ra": tong.token_ra,
        "chi_phi_usd": tong.chi_phi_usd,
        "theo_model": [dong_chi_phi_dict(d) for d in tong.theo_model],
    }


def _dong_so_do(dong, danh_muc: DanhMucModel) -> dict:
    """Một dòng model của file số đo, có thêm `loai` tra từ danh mục.

    `loai` phải có mặt vì `eval/ngoai_suy.py` cộng LLM và embedding thành hai
    khoản khác nhau; model lạ thì `danh_muc.muc` ném `ModelUnknown` chứ không
    trả một ô rỗng - một file số đo không phân loại được là một file không
    dùng được, và biết điều đó lúc ghi rẻ hơn lúc đọc.
    """
    d = dong_chi_phi_dict(dong)
    # `loai` chèn ngay sau `model` để file đọc được từ trên xuống; phần còn lại
    # giữ nguyên thứ tự của `dong_chi_phi_dict`.
    return {"model": d["model"], "loai": danh_muc.muc(dong.model).loai,
            **{k: v for k, v in d.items() if k != "model"}}


def so_do_nap(lan: LanNap, *, lenh: str, danh_muc: DanhMucModel | None = None) -> dict:
    """Số đo của một đợt, dạng dict sẵn sàng ghi JSON (`--xuat-json`).

    `so_tai_lieu` là số tài liệu **thật sự nạp** (`da_nap`), không phải số file
    gửi vào: tài liệu `KHÔNG ĐỔI` không gọi LLM nên nó không được vào mẫu số
    của phép chia "tiền trên một tài liệu" ở `eval/ngoai_suy.py`.

    Ba số **mẫu số của phép hao hụt** (story 2.11): `so_tai_lieu_gui` là số file
    qua được cửa quét, `so_tai_lieu_khong_fact` là số tài liệu LLM trả 0 fact
    hợp lệ (pipeline dọn sạch chúng), `so_tai_lieu_tu_choi` là số file bị cửa
    quét loại. Không có chúng thì "41 tài liệu" trong file không nói được là 41
    trên bao nhiêu, và tỷ lệ hao hụt của đường cục bộ - 18% ở đợt 04/09 - chỉ
    sống trong văn xuôi của spec, nơi không ai tính lại được nó.
    """
    danh_muc = danh_muc_mac_dinh() if danh_muc is None else danh_muc
    tong = lan.chi_phi
    return {
        "version": VERSION_SO_DO,
        "ngay": lan.ket_thuc or thoi_diem_utc(),
        "lenh": lenh,
        "space": lan.space,
        "dot_id": lan.dot_id,
        "so_tai_lieu": len(lan.ket_qua.da_nap()),
        "so_tai_lieu_gui": len(lan.ket_qua.tai_lieu),
        "so_tai_lieu_khong_fact": sum(
            1 for t in lan.ket_qua.tai_lieu if t.ma == MA_KHONG_CO_FACT
        ),
        "so_tai_lieu_tu_choi": len(lan.ket_qua.tu_choi),
        "theo_model": [_dong_so_do(d, danh_muc) for d in (tong.theo_model if tong else ())],
        "tong": {
            "so_lan": tong.so_lan if tong else 0,
            "token_vao": tong.token_vao if tong else 0,
            "token_ra": tong.token_ra if tong else 0,
            "chi_phi_usd": tong.chi_phi_usd if tong else 0.0,
        },
    }


def ghi_so_do_json(duong_dan, so_do: dict) -> Path:
    """Ghi file số đo nguyên tử (file tạm rồi `os.replace`), như sổ tài liệu.

    File này **có commit** và là nguồn của bảng ngoại suy, nên một lần ghi hỏng
    giữa chừng không được để lại bản cụt: bản cũ vẫn hơn một file JSON rách.
    """
    duong_dan = Path(duong_dan)
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    # `mkstemp` trong *cùng thư mục* (để `os.replace` không qua ranh giới hệ
    # thống file) và tên duy nhất mỗi lần: một tên tạm cố định thì hai tiến
    # trình ghi cùng lúc đè lên nhau ngay trước lúc rename.
    fd, ten_tam = tempfile.mkstemp(dir=duong_dan.parent, prefix=duong_dan.name + ".", suffix=DUOI_TAM)
    tam = Path(ten_tam)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(so_do, f, indent=2, ensure_ascii=False)
            f.write("\n")
            # `os.replace` nguyên tử về *tên*, không về *nội dung*: mất điện
            # giữa chừng vẫn để lại một file rỗng nếu dữ liệu còn nằm trong
            # page cache. `fsync` là chỗ đóng nốt lỗ đó.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tam, duong_dan)
    finally:
        tam.unlink(missing_ok=True)
    return duong_dan


__all__ = [
    "MA_DOT_BI_HUY",
    "TRANG_THAI_DOT_DANG_CHAY",
    "TRANG_THAI_DOT_XONG",
    "TRANG_THAI_DOT_LOI",
    "VERSION_SO_DO",
    "ChiPhiTaiLieu",
    "LanNap",
    "chay_lan_nap",
    "chi_phi_theo_tai_lieu",
    "dong_chi_phi_dict",
    "dung_engine_tu_moi_truong",
    "duong_dan_tu_dien",
    "tong_chi_phi_dict",
    "ghi_so_do_json",
    "so_do_nap",
]
