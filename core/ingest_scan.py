"""Quét thư mục nguồn của pipeline ingest: nhận gì, từ chối gì, vì sao (story 2.3).

Hàm thuần, chỉ stdlib, không chạm kho nào. Đầu vào là file trên đĩa, đầu ra là
hai danh sách: tài liệu chấp nhận (đã tách frontmatter, sẵn sàng đưa vào
`ainsert`) và từ chối kèm tên file với mã lý do. Không có nhánh im lặng: một
file không vào được danh sách chấp nhận thì phải có mặt ở danh sách từ chối,
và một file hỏng không chặn file kế (Epic 2: "từ chối kèm tên file và lý do,
không im lặng bỏ qua").

Frontmatter là khối `key: value` giữa hai dòng `---` ở đầu file. Cố ý không
dùng YAML: hai khóa bắt buộc (`scope`, `content_type`) là hai chuỗi phẳng, và
`core/` chỉ stdlib. Khóa lạ trong frontmatter được bỏ qua; giá trị đi qua đúng
luật của `core.keys.filter_key` (không rỗng, không chứa dấu phân tách), nên một
nhãn không dựng được khóa lọc bị chặn ở cửa quét chứ không ở lần ghi đầu tiên.

`doc_key` là tên file: sổ tài liệu của pipeline tra theo nó để biết một lần nạp
là mới hay là re-ingest. Hai file cùng tên ở hai thư mục là một tài liệu về
mặt sổ - quy ước có chủ đích cho corpus 40 tài liệu nằm trong một thư mục.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core.keys import filter_key

# Đuôi file được nhận (Epic 2: chỉ markdown và text thuần).
DUOI_HOP_LE: tuple[str, ...] = (".md", ".txt")

# Mã lý do từ chối - hợp đồng với màn nạp (2.7) và với test: assert trên mã.
MA_DINH_DANG_LA: str = "DINH_DANG_LA"
MA_FILE_RONG: str = "FILE_RONG"
MA_THIEU_METADATA: str = "THIEU_METADATA"
MA_KHONG_PHAI_UTF8: str = "KHONG_PHAI_UTF8"
MA_KHONG_DOC_DUOC: str = "KHONG_DOC_DUOC"
MA_QUA_LON: str = "QUA_LON"
# Pipeline dùng thêm mã này cho ca hai file cùng nội dung (doc_id trùng): quét
# không biết, nhưng mã sống cạnh các mã kia để danh mục có một chỗ.
MA_TRUNG_NOI_DUNG: str = "TRUNG_NOI_DUNG"

# Trần kích thước một file nguồn. Corpus là tài liệu văn bản ngắn; một file
# lớn hơn thế gần chắc là nhầm (log, dump) và đọc trọn vào bộ nhớ rồi gửi LLM
# là tốn tiền cho một lỗi. Kiểm bằng `stat` trước khi đọc.
KICH_THUOC_TOI_DA: int = 2 * 1024 * 1024

DAU_FRONTMATTER: str = "---"
KHOA_SCOPE: str = "scope"
KHOA_CONTENT_TYPE: str = "content_type"


@dataclass(frozen=True)
class TaiLieuNguon:
    """Một tài liệu đã qua cửa quét: nhãn quyền và phần thân, không còn frontmatter."""

    doc_key: str
    scope: str
    content_type: str
    noi_dung: str


@dataclass(frozen=True)
class TuChoi:
    """Một file bị từ chối: tên, mã ổn định, và một câu lý do cho người đọc."""

    ten: str
    ma: str
    ly_do: str


@dataclass(frozen=True)
class KetQuaQuet:
    chap_nhan: tuple[TaiLieuNguon, ...] = ()
    tu_choi: tuple[TuChoi, ...] = ()


def tach_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Tách khối frontmatter ở đầu văn bản; không có thì map rỗng và thân nguyên.

    Khối phải mở bằng `---` ở dòng đầu và đóng bằng `---` ở một dòng sau; thiếu
    dòng đóng thì coi như không có frontmatter (cả văn bản là thân), để một
    file markdown mở đầu bằng đường kẻ ngang không bị nuốt mất nửa đầu.
    """
    dong = text.split("\n")
    if not dong or dong[0].strip() != DAU_FRONTMATTER:
        return {}, text
    for i in range(1, len(dong)):
        if dong[i].strip() == DAU_FRONTMATTER:
            meta: dict[str, str] = {}
            for d in dong[1:i]:
                khoa, dau, gia_tri = d.partition(":")
                if dau:
                    meta[khoa.strip()] = _bo_nhay(gia_tri.strip())
            return meta, "\n".join(dong[i + 1 :])
    return {}, text


def _bo_nhay(gia_tri: str) -> str:
    """Gỡ một cặp nháy đơn/kép bao quanh giá trị frontmatter (`scope: "noi_bo"`)."""
    if len(gia_tri) >= 2 and gia_tri[0] == gia_tri[-1] and gia_tri[0] in ("'", '"'):
        return gia_tri[1:-1].strip()
    return gia_tri


def doc_tai_lieu(duong_dan: Path, doc_key: str | None = None) -> TaiLieuNguon | TuChoi:
    """Đọc và kiểm một file; trả tài liệu hoặc lý do từ chối, không ném.

    Thứ tự kiểm là thứ tự rẻ tới đắt và cụ thể tới chung: đuôi file (không cần
    mở), kích thước (`stat`, chưa đọc), đọc được, rỗng, mã hóa, rồi frontmatter
    và thân. Mỗi file dừng ở lý do đầu tiên gặp phải - một `.pdf` rỗng là
    `DINH_DANG_LA`, không phải hai lỗi. UTF-8 có BOM được nhận (`utf-8-sig`).
    """
    ten = duong_dan.name if doc_key is None else doc_key
    if duong_dan.suffix.lower() not in DUOI_HOP_LE:
        return TuChoi(ten, MA_DINH_DANG_LA, f"đuôi {duong_dan.suffix!r} không nằm trong {list(DUOI_HOP_LE)}")
    try:
        kich_thuoc = duong_dan.stat().st_size
    except OSError as loi:
        return TuChoi(ten, MA_KHONG_DOC_DUOC, f"không đọc được file: {loi}")
    if kich_thuoc > KICH_THUOC_TOI_DA:
        return TuChoi(ten, MA_QUA_LON, f"{kich_thuoc} byte, vượt trần {KICH_THUOC_TOI_DA} byte")
    try:
        raw = duong_dan.read_bytes()
    except OSError as loi:
        return TuChoi(ten, MA_KHONG_DOC_DUOC, f"không đọc được file: {loi}")
    if not raw.strip():
        return TuChoi(ten, MA_FILE_RONG, "file rỗng hoặc toàn khoảng trắng")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as loi:
        return TuChoi(ten, MA_KHONG_PHAI_UTF8, f"không phải UTF-8: {loi}")
    meta, than = tach_frontmatter(text)
    scope = meta.get(KHOA_SCOPE, "")
    content_type = meta.get(KHOA_CONTENT_TYPE, "")
    thieu = [k for k, v in ((KHOA_SCOPE, scope), (KHOA_CONTENT_TYPE, content_type)) if not v.strip()]
    if thieu:
        return TuChoi(ten, MA_THIEU_METADATA, f"frontmatter thiếu {thieu}")
    try:
        filter_key(scope, content_type)
    except (TypeError, ValueError) as loi:
        return TuChoi(ten, MA_THIEU_METADATA, f"nhãn không dựng được khóa lọc: {loi}")
    if not than.strip():
        return TuChoi(ten, MA_FILE_RONG, "thân tài liệu rỗng sau frontmatter")
    return TaiLieuNguon(doc_key=ten, scope=scope.strip(), content_type=content_type.strip(), noi_dung=than)


def quet_cac_file(cac_file: Iterable[Path]) -> KetQuaQuet:
    """Quét một danh sách file theo đúng thứ tự truyền vào."""
    chap_nhan: list[TaiLieuNguon] = []
    tu_choi: list[TuChoi] = []
    for f in cac_file:
        kq = doc_tai_lieu(Path(f))
        if isinstance(kq, TaiLieuNguon):
            chap_nhan.append(kq)
        else:
            tu_choi.append(kq)
    return KetQuaQuet(tuple(chap_nhan), tuple(tu_choi))


def quet_thu_muc(thu_muc: Path) -> KetQuaQuet:
    """Quét mọi file ngay trong thư mục, theo thứ tự tên; không đệ quy.

    Thư mục không tồn tại là lỗi của người gọi (`FileNotFoundError`), không
    phải "không có tài liệu nào": hai thứ đó nhìn giống nhau ở kết quả mà khác
    nhau hoàn toàn về nguyên nhân.
    """
    thu_muc = Path(thu_muc)
    if not thu_muc.is_dir():
        raise FileNotFoundError(f"không có thư mục {thu_muc}")
    return quet_cac_file(sorted((p for p in thu_muc.iterdir() if p.is_file()), key=lambda p: p.name))
