"""Ba tỷ lệ n-ngôi tính bằng hàm thuần trên một ảnh chụp đồ thị (story 2.10).

Ba định nghĩa đếm chốt ở `docs/adr/ADR-012-dinh-nghia-dem-ba-ty-le-n-ngoi.md`
**trước** phép đếm đầu tiên, và module này là bản mã của đúng ba định nghĩa đó:

1. **Overall N-ary** - hyperedge có từ `TOI_THIEU_VAI_N_NGOI` vai slot được điền
   trở lên, chia cho tổng số hyperedge. Đếm *vai*, không đếm entity: hai giá trị
   cùng vai `symptom` là hai giá trị của một chiều, không phải hai chiều.
2. **Sensitive N-ary** - trong số hyperedge nhạy cảm (hạng độ nhạy từ
   `NGUONG_NHAY_CAM` trở lên), bao nhiêu phần là n-ngôi.
3. **Composition-Risk** - trong số hyperedge nhạy cảm, bao nhiêu phần có **mọi**
   entity cấu thành còn xuất hiện ở ít nhất một hyperedge không nhạy cảm.

Hai tỷ lệ sau dùng chung mẫu số, cố ý: chúng đọc cạnh nhau mới nói được điều
gì. Mẫu số nhạy cảm rỗng thì tỷ lệ là `None`, không phải `0` - "không có ca nào
để đo" và "đo được và bằng không" là hai câu khác nhau, và một trang báo cáo in
`0%` cho ca đầu là một trang nói dối.

**Hàm thuần, không I/O.** Đầu vào là một `AnhDoThi` đã kiểm cộng bảng hạng độ
nhạy đã nạp; đầu ra là số. Không đọc file, không chạm kho, không gọi LLM. Nhờ
vậy cùng một ảnh chụp đã commit luôn cho cùng ba con số, và người đọc repo tính
lại được mà không cần kho đang chạy. Phần đọc file nằm ở `eval/xem_ty_le.py`.
"""

from dataclasses import dataclass
from typing import Mapping, Sequence

from eval.cau_hoi import AnhDoThi, HyperedgeAnh

# Số vai slot tối thiểu để một hyperedge tính là n-ngôi (ADR-012 khoản 1). Hai
# vai là một quan hệ nhị phân, đúng thứ đồ thị tri thức thường đã làm được; giả
# định của khóa luận chỉ có nội dung khi ngưỡng đặt ở chỗ đồ thị nhị phân bắt
# đầu phải tách fact ra.
TOI_THIEU_VAI_N_NGOI: int = 3

# Hạng độ nhạy từ số này trở lên là "nhạy cảm" (ADR-012 khoản 2). 20 là hạng
# `bao_cao_su_co` trong `config/hang-do-nhay.yaml`, một trong ba hạng **đóng
# băng** từ story 2.1 - chọn một số đóng băng nghĩa là ngưỡng không trôi khi
# story 3.2 khai thêm loại nội dung.
NGUONG_NHAY_CAM: int = 20

# Tiền tố nhãn của ca **không khóa** trong bảng phân bố theo loại nội dung.
# Hyperedge không mang khóa (hợp nhất khác scope, AD-5) không có `content_type`
# của riêng nó; hạng của nó suy từ `doc_key`. Gộp nó vào ô của loại nội dung suy
# ra là nói dối hai lần: bảng đọc thành "có N hyperedge loại `postmortem`" trong
# khi một phần trong đó là ca không loại nào, và phép so hai space cộng chung
# hai thứ khác bản chất vào một ô.
NHAN_KHONG_KHOA: str = "(không khóa, hạng suy từ doc_key)"


class HangKhongXacDinh(ValueError):
    """Không suy được hạng độ nhạy cho một hyperedge, từ cả hai nguồn.

    Từ chối **cả đợt** thay vì gán một hạng mặc định. Mặc định về phía không
    nhạy cảm là fail-open (một fact nhạy cảm rơi ra khỏi mẫu số); mặc định về
    phía nhạy cảm là bơm mẫu số bằng những ca không ai kiểm được. Cả hai đều là
    một con số sai mà không có gì nói ra.

    `code` ổn định để test assert trên `code` (AD-8).
    """

    code = "HANG_KHONG_XAC_DINH"


@dataclass(frozen=True)
class TyLe:
    """Một tỷ lệ kèm tử số và mẫu số tường minh.

    Ba tỷ lệ luôn đi cùng hai con số sinh ra chúng: một phần trăm không kèm mẫu
    số là con số mà người đọc chương 4 không kiểm lại được, và "44% của 50" với
    "44% của 9" là hai phát biểu rất khác nhau.
    """

    ten: str
    tu_so: int
    mau_so: int

    @property
    def ti_le(self) -> float | None:
        """`None` khi mẫu số rỗng - không chia cho 0, và không trả 0."""
        return None if self.mau_so == 0 else self.tu_so / self.mau_so

    def mo_ta(self) -> str:
        """Một dòng đọc được: `tử/mẫu (phần trăm)`, hoặc lý do không tính được."""
        if self.mau_so == 0:
            return f"{self.tu_so}/0 - không tính được, mẫu số 0"
        return f"{self.tu_so}/{self.mau_so} ({self.ti_le:.1%})"


@dataclass(frozen=True)
class BaTyLe:
    """Ba tỷ lệ của một space, kèm danh sách id để trang soát chỉ đúng ca nào."""

    space: str
    ngay_do: str
    so_hyperedge: int
    so_tai_lieu: int
    overall_n_ary: TyLe
    sensitive_n_ary: TyLe
    composition_risk: TyLe
    id_n_ngoi: tuple[str, ...]
    id_nhay_cam: tuple[str, ...]
    id_composition_risk: tuple[str, ...]
    # `{hạng: số hyperedge}`, đầu vào của phép đối chiếu phân bố mức nhạy cảm
    # giữa hai space. Đếm trên hyperedge chứ không trên tài liệu: hai tài liệu
    # cùng loại có thể cho số fact rất khác nhau.
    phan_bo_hang: Mapping[int, int]
    phan_bo_loai: Mapping[str, int]
    # Ba số **chẩn đoán**, không phải tỷ lệ thứ tư và không vào báo cáo như một
    # kết quả. Chúng có mặt để một `Composition-Risk` bằng 0 đọc được: 0 vì
    # không entity nào của ca nhạy cảm lộ ở nơi khác, hay 0 vì luôn còn đúng một
    # mảnh không lộ. Nới định nghĩa từ "mọi" sang "có ít nhất một" là đổi ADR-012
    # chứ không phải đọc ba số này thay cho tỷ lệ 3.
    #
    # `so_nhay_cam_lo_mot_phan` đếm ca lộ **một phần thật**: có entity lộ mà
    # không lộ hết. Ca lộ hết chính là tử số của tỷ lệ 3, nên gộp nó vào đây là
    # một con số cộng chung "gần thành rủi ro" với "đã là rủi ro"; hôm nay tử số
    # bằng 0 nên hai cách đếm cho cùng một số, và đó đúng là lúc dễ chép nhầm
    # cách đọc nhất.
    so_nhay_cam_lo_mot_phan: int = 0
    # Mẫu số của `trung_binh_phan_entity_lo`: ca nhạy cảm có **ít nhất một**
    # entity lộ. Nó rộng hơn số trên đúng phần ca lộ hết.
    so_nhay_cam_co_entity_lo: int = 0
    # Trung bình phần entity lộ, tính **trên `so_nhay_cam_co_entity_lo`** chứ
    # không trên mọi ca nhạy cảm: câu nó trả lời là "khi một ca đã hở, nó hở bao
    # nhiêu", và trộn những ca hở 0% vào làm câu đó thành một câu khác. `None`
    # khi mẫu số rỗng, cùng luật với `TyLe.ti_le` - "không có ca nào để đo" và
    # "đo được và bằng không" là hai câu khác nhau.
    trung_binh_phan_entity_lo: float | None = None

    def bo_ba(self) -> tuple[TyLe, TyLe, TyLe]:
        return (self.overall_n_ary, self.sensitive_n_ary, self.composition_risk)


def so_vai_da_dien(h: HyperedgeAnh) -> int:
    """Số vai slot có ít nhất một giá trị. `dung_anh` đã bỏ vai rỗng, nhưng đếm
    lại ở đây để hàm đúng cả với ảnh chụp dựng tay trong test."""
    return sum(1 for gia_tri in h.slots.values() if gia_tri)


def la_n_ngoi(h: HyperedgeAnh) -> bool:
    """ADR-012 khoản 1: từ 3 vai được điền trở lên."""
    return so_vai_da_dien(h) >= TOI_THIEU_VAI_N_NGOI


def entity_cua(h: HyperedgeAnh) -> frozenset[str]:
    """`E(h)`: tập entity nối vào hyperedge qua mọi vai."""
    return frozenset(e for gia_tri in h.slots.values() for e in gia_tri)


def hang_cua_hyperedge(
    h: HyperedgeAnh, hang: Mapping[str, int], loai_theo_doc_key: Mapping[str, str]
) -> int:
    """Hạng độ nhạy của một hyperedge, theo ADR-012 khoản 2.

    Nguồn thứ nhất là loại nội dung trong khóa lọc `{scope}:{content_type}` của
    chính hyperedge. Nguồn thứ hai, dùng khi hyperedge **không mang khóa** (ca
    hợp nhất khác scope của AD-5), là hạng **cao nhất** trong các loại nội dung
    của những `doc_key` sinh ra nó.

    Chiều hạn chế nhất, không phải chiều thấp nhất: toàn bộ tầng quyền của hệ
    chọn chiều đó (`core.keys.hop_nhat_khoa`), và một phép đếm chọn chiều ngược
    lại sẽ xếp một fact ghép từ runbook cộng postmortem vào nhóm không nhạy cảm.

    Thiếu cả hai nguồn là `HangKhongXacDinh`, tức từ chối cả đợt.
    """
    loai = h.content_type
    if loai is not None:
        if loai not in hang:
            raise HangKhongXacDinh(
                f"hyperedge {h.id}: loại nội dung {loai!r} (từ khóa {h.khoa!r})"
                f" không có hạng độ nhạy trong bảng {sorted(hang)}"
            )
        return hang[loai]

    ung_vien: list[int] = []
    thieu: list[str] = []
    for doc_key in h.doc_key:
        loai_dk = loai_theo_doc_key.get(doc_key)
        if loai_dk is None:
            thieu.append(doc_key)
        elif loai_dk not in hang:
            raise HangKhongXacDinh(
                f"hyperedge {h.id}: tài liệu {doc_key!r} khai loại {loai_dk!r}"
                f" không có hạng độ nhạy trong bảng {sorted(hang)}"
            )
        else:
            ung_vien.append(hang[loai_dk])
    if not ung_vien:
        raise HangKhongXacDinh(
            f"hyperedge {h.id} không có khóa lọc, và không tài liệu nào trong"
            f" {list(h.doc_key)} tra được loại nội dung (thiếu {thieu}):"
            " không suy được hạng độ nhạy, từ chối cả đợt thay vì đoán một hạng"
        )
    return max(ung_vien)


def loai_theo_doc_key(anh: AnhDoThi) -> Mapping[str, str]:
    """`{doc_key: content_type}` đọc từ sổ tài liệu đã chụp cùng đồ thị."""
    return {t.doc_key: t.content_type for t in anh.tai_lieu}


def ba_ty_le(anh: AnhDoThi, hang: Mapping[str, int]) -> BaTyLe:
    """Ba tỷ lệ của một ảnh chụp. Hàm thuần: cùng đầu vào là cùng đầu ra.

    Một lượt qua danh sách hyperedge tính hạng, một lượt dựng chỉ mục entity ->
    có xuất hiện ở hyperedge không nhạy cảm nào không, rồi một lượt chấm
    composition risk. Không sắp xếp lại gì ngoài id trả ra, vì ảnh chụp đã sắp
    sẵn và thứ tự đó là thứ người soát đọc.
    """
    theo_doc_key = loai_theo_doc_key(anh)
    hang_cua: dict[str, int] = {
        h.id: hang_cua_hyperedge(h, hang, theo_doc_key) for h in anh.hyperedge
    }

    nhay_cam = [h for h in anh.hyperedge if hang_cua[h.id] >= NGUONG_NHAY_CAM]
    n_ngoi = [h for h in anh.hyperedge if la_n_ngoi(h)]

    # Entity nào còn lộ ở ít nhất một hyperedge **không** nhạy cảm. Dựng một lần
    # rồi tra, thay vì quét lại toàn bộ đồ thị cho từng ca nhạy cảm.
    lo_o_khong_nhay: set[str] = set()
    for h in anh.hyperedge:
        if hang_cua[h.id] < NGUONG_NHAY_CAM:
            lo_o_khong_nhay |= entity_cua(h)

    rui_ro: list[str] = []
    lo_mot_phan = 0
    phan_lo: list[float] = []
    for h in nhay_cam:
        e = entity_cua(h)
        if not e:
            # `E(h)` rỗng bị loại tường minh khỏi cả tử số lẫn hai số chẩn đoán:
            # mệnh đề "mọi e đều lộ" đúng một cách rỗng (ADR-012), và một ca
            # không có entity nào thì "hở bao nhiêu phần" không có nghĩa.
            continue
        da_lo = len(e & lo_o_khong_nhay)
        if da_lo == len(e):
            rui_ro.append(h.id)
        elif da_lo:
            lo_mot_phan += 1
        if da_lo:
            phan_lo.append(da_lo / len(e))

    phan_bo_hang: dict[int, int] = {}
    phan_bo_loai: dict[str, int] = {}
    nguoc = {v: k for k, v in hang.items()}
    for h in anh.hyperedge:
        r = hang_cua[h.id]
        phan_bo_hang[r] = phan_bo_hang.get(r, 0) + 1
        if h.content_type is None:
            # Ca không khóa: hạng suy từ `doc_key`, không phải loại nội dung của
            # chính hyperedge. Nhãn riêng, không dồn vào ô của loại suy ra.
            ten_loai = f"{NHAN_KHONG_KHOA} {nguoc.get(r, f'hạng {r}')}"
        else:
            ten_loai = h.content_type
        phan_bo_loai[ten_loai] = phan_bo_loai.get(ten_loai, 0) + 1

    return BaTyLe(
        space=anh.space,
        ngay_do=anh.ngay_do,
        so_hyperedge=anh.so_hyperedge,
        so_tai_lieu=anh.so_tai_lieu,
        overall_n_ary=TyLe("Overall N-ary", len(n_ngoi), anh.so_hyperedge),
        sensitive_n_ary=TyLe(
            "Sensitive N-ary",
            sum(1 for h in nhay_cam if la_n_ngoi(h)),
            len(nhay_cam),
        ),
        composition_risk=TyLe("Composition-Risk", len(rui_ro), len(nhay_cam)),
        id_n_ngoi=tuple(h.id for h in n_ngoi),
        id_nhay_cam=tuple(h.id for h in nhay_cam),
        id_composition_risk=tuple(rui_ro),
        phan_bo_hang=dict(sorted(phan_bo_hang.items())),
        phan_bo_loai=dict(sorted(phan_bo_loai.items())),
        so_nhay_cam_lo_mot_phan=lo_mot_phan,
        so_nhay_cam_co_entity_lo=len(phan_lo),
        trung_binh_phan_entity_lo=(sum(phan_lo) / len(phan_lo)) if phan_lo else None,
    )


@dataclass(frozen=True)
class DongDoiChieu:
    """Một hàng của bảng đối chiếu hai space: cùng tỷ lệ, hai cột, một chênh lệch."""

    ten: str
    trai: TyLe
    phai: TyLe

    @property
    def chenh(self) -> float | None:
        """Chênh lệch điểm phần trăm (phải trừ trái); `None` nếu một bên không tính được."""
        a, b = self.trai.ti_le, self.phai.ti_le
        return None if a is None or b is None else b - a


def doi_chieu(trai: BaTyLe, phai: BaTyLe) -> tuple[DongDoiChieu, ...]:
    """Ba hàng đối chiếu, giữ nguyên thứ tự ba tỷ lệ của ADR-012.

    Đây là phép "khớp cỡ" của story 2.10, và nó chỉ nói được điều gì khi cả hai
    cột cùng có mặt kèm chênh lệch: một bảng chỉ in cột `khao_sat` là một bảng
    không trả lời câu hỏi nào.
    """
    return tuple(
        DongDoiChieu(a.ten, a, b) for a, b in zip(trai.bo_ba(), phai.bo_ba())
    )


def hop_hang(*bo: BaTyLe) -> tuple[int, ...]:
    """Tập hạng có mặt ở bất kỳ space nào, sắp tăng - trục của bảng phân bố."""
    co: set[int] = set()
    for b in bo:
        co |= set(b.phan_bo_hang)
    return tuple(sorted(co))


def hop_loai(*bo: BaTyLe) -> tuple[str, ...]:
    co: set[str] = set()
    for b in bo:
        co |= set(b.phan_bo_loai)
    return tuple(sorted(co))


def dong_tom_tat(b: BaTyLe) -> Sequence[str]:
    """Ba dòng console của một space, mỗi dòng kèm tử số và mẫu số."""
    return [f"{t.ten}: {t.mo_ta()}" for t in b.bo_ba()]
