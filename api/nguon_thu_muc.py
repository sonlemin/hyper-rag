"""Thư mục nguồn của một đợt nạp khai space của chính nó (story 2.11).

Từ story này có **ba** space cùng tồn tại - `synth` (mẫu số của Đo 2 và Đo 3),
`khao_sat` (mẫu số ba tỷ lệ n-ngôi) và `real` (tài liệu công ty đã khử). Cờ
`--space` của `api.do_chi_phi` nhận chuỗi tự do và mặc định là `synth`, nên một
lần gõ thiếu cờ là nạp 50 tài liệu công ty vào đúng corpus mà hai phép đo đang
đứng trên. Không có gì đỏ để báo: tên file hai bộ không trùng nên đó là *thêm*
chứ không *đè*, và ai đó phải chạy lại `uv run pytest` mới thấy ảnh chụp lệch.

Rào đặt ở đây: mỗi thư mục nguồn mang một file `.space` chứa đúng một dòng là
tên space của nó, và CLI đối chiếu với `--space` **trước** lời gọi LLM đầu tiên.

Vì sao không đặt trong `core.ingest_scan`: `api/man_nap.py` (màn nạp web, story
2.7) dùng chung lõi quét đó nhưng nhận file tải lên, không có thư mục nào để
khai. Một rào đặt trong `core/` đổi luôn hình dạng của lối vào web mà không ai
hỏi. Hai lối vào chia nhau lõi *quét*, không chia nhau lõi *chọn nguồn*.

Import `core/` cho luật `space`, và `adapters/` cho luật "bỏ file ẩn" - cả hai
đều là chiều hợp lệ. Không chạm kho nào.
"""

from pathlib import Path

from adapters.ingest import cac_file_nap, la_file_an
from core.ids import validate_space

__all__ = [
    "TEN_FILE_SPACE",
    "SpaceKhaiKhongHopLe",
    "SpaceKhongKhai",
    "SpaceLechThuMuc",
    "cac_file_nap",
    "doc_space_khai",
    "kiem_space_thu_muc",
    "la_file_an",
]

# Tên file khai space, đặt ngay trong thư mục nguồn. Bắt đầu bằng dấu chấm để
# nó rơi đúng vào luật loại file ẩn bên dưới, và để `ls` mặc định không trộn nó
# vào danh sách tài liệu khi người soát đếm bằng mắt.
TEN_FILE_SPACE: str = ".space"


class SpaceKhongKhai(RuntimeError):
    """Thư mục nguồn không có `.space`.

    Từ chối chứ **không** đoán mặc định. `synth` là mặc định của cờ `--space`,
    nên một nhánh "thiếu khai thì coi như synth" biến đúng cái ca nguy hiểm
    nhất - thư mục dữ liệu thật chưa khai - thành một lần nạp im lặng vào mẫu số
    của Đo 2 và Đo 3.
    """

    code = "SPACE_KHONG_KHAI"


class SpaceLechThuMuc(RuntimeError):
    """`--space` khác space mà thư mục nguồn tự khai."""

    code = "SPACE_LECH_THU_MUC"


class SpaceKhaiKhongHopLe(RuntimeError):
    """File `.space` có mà không đọc được thành đúng một tên space."""

    code = "SPACE_KHAI_KHONG_HOP_LE"


# `la_file_an` và `cac_file_nap` sống ở `adapters/ingest.py` và được import lên
# đây (chiều `api/` -> `adapters/` là chiều hợp lệ). Một bản sao thứ hai của
# luật "bỏ file ẩn" ở tầng này là hai bản sẽ trôi khỏi nhau, và khi đó CLI với
# `adapters.nap_thu_muc` nhìn thấy hai tập file khác nhau trên cùng thư mục.


def doc_space_khai(thu_muc: Path) -> str:
    """Space mà thư mục tự khai; thiếu file hay nội dung lạ đều là lỗi có mã."""
    duong_dan = Path(thu_muc) / TEN_FILE_SPACE
    if not duong_dan.exists():
        raise SpaceKhongKhai(
            f"thư mục nguồn {thu_muc} chưa khai space: tạo {duong_dan} chứa đúng"
            " một dòng là tên space (ví dụ `real`). Không có mặc định: cờ"
            " --space mặc định là 'synth', và đoán hộ ở đây là nạp im lặng vào"
            " mẫu số của Đo 2 và Đo 3"
        )
    try:
        raw = duong_dan.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as loi:
        raise SpaceKhaiKhongHopLe(f"không đọc được {duong_dan}: {loi}") from None
    dong = [d.strip() for d in raw.splitlines() if d.strip()]
    if len(dong) != 1:
        raise SpaceKhaiKhongHopLe(
            f"{duong_dan} phải có đúng một dòng là tên space, đọc được {len(dong)} dòng"
        )
    try:
        return validate_space(dong[0])
    except (TypeError, ValueError) as loi:
        raise SpaceKhaiKhongHopLe(f"{duong_dan}: {loi}") from None


def thu_muc_cha_chung(cac_duong_dan) -> Path | None:
    """Thư mục cha chung của một danh sách file, hoặc `None` nếu không có.

    Ca nó sinh ra để bắt: `api.do_chi_phi real/*.md --space synth`. Shell bung
    glob thành 50 đường dẫn file, nên nhánh "một thư mục" không chạy và rào
    `.space` không áp - tức đúng lệnh nguy hiểm nhất đi lọt qua cái rào dựng ra
    để chặn nó. Danh sách file rời **cùng một thư mục cha** là một thư mục xét
    về nguồn gốc, dù dòng lệnh không nói thế.
    """
    cha = {Path(d).resolve().parent for d in cac_duong_dan}
    return cha.pop() if len(cha) == 1 else None


def kiem_space_thu_muc(thu_muc: Path, space: str) -> str:
    """Đối chiếu `--space` với space thư mục tự khai; trả lại space nếu khớp.

    Thông điệp nêu **cả hai** giá trị: "space không khớp" mà không nói khớp với
    cái gì buộc người chạy đi mở file mới biết mình gõ nhầm bên nào.
    """
    khai = doc_space_khai(thu_muc)
    if khai != space:
        raise SpaceLechThuMuc(
            f"thư mục nguồn {thu_muc} khai space {khai!r} nhưng lệnh chạy với"
            f" --space {space!r}: từ chối trước lời gọi LLM đầu tiên. Sửa cờ,"
            f" hoặc sửa {Path(thu_muc) / TEN_FILE_SPACE} nếu thư mục đã đổi chủ"
        )
    return khai
