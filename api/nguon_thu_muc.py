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

Chỉ import `core/`: đây là hàm thuần trên hệ thống file, không chạm kho nào.
"""

from pathlib import Path

from core.ids import validate_space

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


def la_file_an(duong_dan: Path) -> bool:
    """Tên bắt đầu bằng dấu chấm.

    Luật là "file ẩn", không phải "đúng tên `.space`": `.DS_Store`, `.gitkeep`
    và file tạm của trình soạn thảo cũng không phải tài liệu, và để chúng thành
    một dòng `DINH_DANG_LA` trong danh sách từ chối là dạy người đọc bỏ qua
    danh sách đó.
    """
    return duong_dan.name.startswith(".")


def cac_file_nap(thu_muc: Path) -> list[Path]:
    """File ứng viên trong thư mục, theo thứ tự tên, đã bỏ file ẩn.

    Giữ nguyên luật của `core.ingest_scan.quet_thu_muc`: chỉ file ngay trong
    thư mục, không đệ quy, sắp theo tên. Thư mục không tồn tại là lỗi của người
    gọi, cùng ngoại lệ với lõi quét.
    """
    thu_muc = Path(thu_muc)
    if not thu_muc.is_dir():
        raise FileNotFoundError(f"không có thư mục {thu_muc}")
    return sorted(
        (p for p in thu_muc.iterdir() if p.is_file() and not la_file_an(p)),
        key=lambda p: p.name,
    )


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
