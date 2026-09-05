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

from dataclasses import dataclass, field, replace
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

# Ba vai **mang thực thể**, dùng cho một số **chẩn đoán** cạnh tỷ lệ 3 (story
# 2.12). `E(h)` của ADR-012 đếm mọi giá trị slot là một entity, kể cả `cause` và
# `remediation` vốn là mệnh đề trong chính nhãn tay của bộ vàng 2.5 - và một
# mệnh đề gần như không bao giờ lặp lại nguyên văn ở một tài liệu khác, nên nó
# một mình chặn được ca đó khỏi tử số. Ba vai dưới đây là phần của `E(h)` mà
# chuẩn hóa bí danh thật sự chạm tới. Con số tính trên chúng **không thay** tỷ
# lệ chính thức; nó nói cho người đọc chương 4 biết số 0 của tỷ lệ 3 đến từ định
# nghĩa đếm hay từ hình dạng tri thức.
VAI_THUC_THE: tuple[str, ...] = ("subject", "owner", "source")


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
    # --- Ba số **dấu vân tay của bộ trích xuất** (story 2.11) ------------------
    #
    # Chúng không phải kết quả và không vào báo cáo như một tỷ lệ. Chúng có mặt
    # vì tỷ lệ 1 bằng **100%** đọc được theo hai cách rất khác nhau: "tri thức
    # này n-ngôi tuyệt đối" hoặc "bộ trích xuất không bao giờ trả một fact dưới
    # 3 vai". Ba số này tách hai cách đọc đó ra, và chúng phải tính từ chính ảnh
    # chụp chứ không chép tay, nếu không lần nạp sau chúng nói về lần nạp trước.
    #
    # `{số vai được điền: số hyperedge}`. Một cột không có hyperedge 2 vai nào,
    # trong khi hai cột kia có 10-20%, là dấu của trần dưới do bộ trích xuất đặt.
    phan_bo_so_vai: Mapping[int, int] = field(default_factory=dict)
    # `{vai: số hyperedge điền vai đó}`. So giữa hai cột thì vai nào lệch nhiều
    # nhất chỉ ra chỗ bộ trích xuất tự điền thay vì đọc ra từ tài liệu.
    phan_bo_vai: Mapping[str, int] = field(default_factory=dict)
    # Số hyperedge có **một entity xuất hiện ở hai vai trở lên**. Một fact lành
    # hiếm khi lấy cùng một thực thể làm hai chiều; tỷ lệ này cao là dấu bộ trích
    # xuất nhồi vai cho đủ. Trùng *trong* một vai không tính: đó là LLM lặp một
    # giá trị, một hiện tượng khác.
    so_entity_lap_vai: int = 0
    # --- Chẩn đoán của story 2.12 ---------------------------------------------
    #
    # Composition-Risk tính lại trên **chỉ ba vai mang thực thể** (`VAI_THUC_THE`)
    # thay vì trên cả `E(h)`. Không phải tỷ lệ thứ tư và không thay tỷ lệ 3: nó
    # trả lời câu "số 0 kia đến từ định nghĩa đếm hay từ tri thức". `E(h)` gồm cả
    # `cause` và `remediation`, hai vai mà bộ vàng nhãn tay ghi thành mệnh đề, và
    # một mệnh đề gần như không bao giờ lặp nguyên văn ở tài liệu khác - nên
    # riêng nó đã chặn được ca đó khỏi tử số dù mọi thực thể đều lộ.
    composition_risk_vai_thuc_the: TyLe = field(
        default_factory=lambda: TyLe("Composition-Risk (vai thực thể)", 0, 0)
    )
    id_composition_risk_vai_thuc_the: tuple[str, ...] = ()
    # Phép lộ có bị **siết theo scope** không (story 2.12, ca 3 của ADR-012).
    # Ghi vào kết quả chứ không chỉ là tham số của hàm: hai lần chạy khác cờ này
    # cho hai con số cùng tên, và một bảng không nói ra mình dùng cờ nào là một
    # bảng không đối chiếu lại được.
    siet_theo_scope: bool = True

    def bo_ba(self) -> tuple[TyLe, TyLe, TyLe]:
        return (self.overall_n_ary, self.sensitive_n_ary, self.composition_risk)

    def vai_da_dien_nhieu_nhat(self, moc: "BaTyLe") -> tuple[str, float, float] | None:
        """Vai lệch nhiều nhất so với cột mốc: `(vai, tỷ lệ của mình, của mốc)`.

        Trả vai mà cột này điền **nhiều hơn** mốc nhiều nhất - chiều đó mới là
        chiều đáng ngờ: một bộ trích xuất bỏ sót thì thiếu vai, còn một bộ trích
        xuất tự bịa thì thừa vai. `None` khi một trong hai cột rỗng.
        """
        if not self.so_hyperedge or not moc.so_hyperedge:
            return None
        ung_vien = []
        for vai in set(self.phan_bo_vai) | set(moc.phan_bo_vai):
            a = self.phan_bo_vai.get(vai, 0) / self.so_hyperedge
            b = moc.phan_bo_vai.get(vai, 0) / moc.so_hyperedge
            ung_vien.append((a - b, vai, a, b))
        if not ung_vien:
            return None
        chenh, vai, a, b = max(ung_vien)
        return (vai, a, b) if chenh > 0 else None

    def phan_hyperedge_hai_vai(self) -> float | None:
        """Phần hyperedge chỉ có 2 vai được điền; `None` khi không có hyperedge nào."""
        if not self.so_hyperedge:
            return None
        return self.phan_bo_so_vai.get(2, 0) / self.so_hyperedge

    def so_vai_pho_bien_nhat(self) -> int | None:
        """Số vai được điền hay gặp nhất (mode); hòa thì lấy số nhỏ hơn."""
        if not self.phan_bo_so_vai:
            return None
        return max(self.phan_bo_so_vai.items(), key=lambda kv: (kv[1], -kv[0]))[0]

    def phan_entity_lap_vai(self) -> float | None:
        if not self.so_hyperedge:
            return None
        return self.so_entity_lap_vai / self.so_hyperedge


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


def entity_vai_thuc_the(h: HyperedgeAnh) -> frozenset[str]:
    """Phần của `E(h)` nằm ở ba vai mang thực thể (`VAI_THUC_THE`).

    **Không** phải một `E(h)` thứ hai: định nghĩa đóng băng của ADR-012 giữ
    nguyên và tỷ lệ chính thức vẫn tính trên `entity_cua`. Đây là đầu vào của
    một dòng chẩn đoán.
    """
    return frozenset(
        e for vai in VAI_THUC_THE for e in h.slots.get(vai, ())
    )


def scope_cua_hyperedge(
    h: HyperedgeAnh, scope_theo_doc_key: Mapping[str, str]
) -> frozenset[str]:
    """Các scope mà một hyperedge thuộc về (story 2.12, ca 3 của ADR-012).

    Cùng hai nguồn với `hang_cua_hyperedge`: khóa lọc của chính hyperedge trước,
    rồi sổ tài liệu cho ca **không khóa** (hợp nhất khác scope, AD-5). Khác ở
    chỗ trả một **tập**: một hyperedge không khóa tồn tại vì tài liệu của cả hai
    scope, nên nó nằm trong tầm nhìn của cả hai.

    Trả tập rỗng khi không suy được scope nào. Nơi gọi coi tập rỗng là "không
    thấy mảnh nào lộ" - phía an toàn, vì tử số của tỷ lệ 3 là phía *có* rủi ro.
    """
    if h.scope is not None:
        return frozenset({h.scope})
    return frozenset(
        s for dk in h.doc_key if (s := scope_theo_doc_key.get(dk)) is not None
    )


def scope_theo_doc_key(anh: AnhDoThi) -> Mapping[str, str]:
    """`{doc_key: scope}` đọc từ sổ tài liệu đã chụp cùng đồ thị."""
    return {t.doc_key: t.scope for t in anh.tai_lieu}


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


def ba_ty_le(
    anh: AnhDoThi, hang: Mapping[str, int], *, siet_theo_scope: bool = True
) -> BaTyLe:
    """Ba tỷ lệ của một ảnh chụp. Hàm thuần: cùng đầu vào là cùng đầu ra.

    Một lượt qua danh sách hyperedge tính hạng, một lượt dựng chỉ mục entity ->
    có xuất hiện ở hyperedge không nhạy cảm nào không, rồi một lượt chấm
    composition risk. Không sắp xếp lại gì ngoài id trả ra, vì ảnh chụp đã sắp
    sẵn và thứ tự đó là thứ người soát đọc.

    `siet_theo_scope` là **ca 3 của phần "Điều kiện đổi định nghĩa" trong
    ADR-012**, mở ngày 05/09/2026 (mục bổ sung của story 2.12). Định nghĩa gốc
    hỏi "mọi entity còn xuất hiện ở một hyperedge không nhạy cảm" mà không đòi
    hyperedge đó nằm trong tầm nhìn của ai: nó vì vậy đếm cả phép ghép mà không
    ai thực hiện được, ví dụ mảnh lộ ở một tài liệu `khach_hang_b` trong khi ca
    nhạy cảm thuộc `khach_hang_a`. Bật cờ này thì chỉ mục lộ dựng **theo từng
    scope**, và một ca nhạy cảm chỉ tra chỉ mục của scope mình.

    Cờ tồn tại vì chính ADR đó đòi "số cũ giữ lại để so": chạy với `False` cho
    lại đúng con số trước khi siết, và mục bổ sung của ADR dựng bằng hai lần
    chạy đó chứ không bằng hai con số chép tay. `E(h)`, ngưỡng n-ngôi và ngưỡng
    nhạy cảm **không** đổi.
    """
    theo_doc_key = loai_theo_doc_key(anh)
    theo_scope = scope_theo_doc_key(anh)
    hang_cua: dict[str, int] = {
        h.id: hang_cua_hyperedge(h, hang, theo_doc_key) for h in anh.hyperedge
    }

    nhay_cam = [h for h in anh.hyperedge if hang_cua[h.id] >= NGUONG_NHAY_CAM]
    n_ngoi = [h for h in anh.hyperedge if la_n_ngoi(h)]

    # Entity nào còn lộ ở ít nhất một hyperedge **không** nhạy cảm. Dựng một lần
    # rồi tra, thay vì quét lại toàn bộ đồ thị cho từng ca nhạy cảm.
    #
    # Khi siết theo scope thì chỉ mục là `{scope: tập entity}` và một ca nhạy cảm
    # tra **hợp** các scope của chính nó (một hyperedge không khóa thuộc về mọi
    # scope sinh ra nó, nên nó nhìn thấy phần lộ của cả hai - phía an toàn là
    # phía đếm nhiều rủi ro hơn).
    lo_chung: set[str] = set()
    lo_theo_scope: dict[str, set[str]] = {}
    for h in anh.hyperedge:
        if hang_cua[h.id] >= NGUONG_NHAY_CAM:
            continue
        e = entity_cua(h)
        lo_chung |= e
        for sc in scope_cua_hyperedge(h, theo_scope):
            lo_theo_scope.setdefault(sc, set()).update(e)

    def tap_lo(h: HyperedgeAnh) -> set[str]:
        if not siet_theo_scope:
            return lo_chung
        ra: set[str] = set()
        for sc in scope_cua_hyperedge(h, theo_scope):
            ra |= lo_theo_scope.get(sc, set())
        return ra

    rui_ro: list[str] = []
    rui_ro_vai_thuc_the: list[str] = []
    lo_mot_phan = 0
    phan_lo: list[float] = []
    for h in nhay_cam:
        lo = tap_lo(h)
        e = entity_cua(h)
        e_tt = entity_vai_thuc_the(h)
        if e_tt and e_tt <= lo:
            rui_ro_vai_thuc_the.append(h.id)
        if not e:
            # `E(h)` rỗng bị loại tường minh khỏi cả tử số lẫn hai số chẩn đoán:
            # mệnh đề "mọi e đều lộ" đúng một cách rỗng (ADR-012), và một ca
            # không có entity nào thì "hở bao nhiêu phần" không có nghĩa.
            continue
        da_lo = len(e & lo)
        if da_lo == len(e):
            rui_ro.append(h.id)
        elif da_lo:
            lo_mot_phan += 1
        if da_lo:
            phan_lo.append(da_lo / len(e))

    phan_bo_so_vai: dict[int, int] = {}
    phan_bo_vai: dict[str, int] = {}
    lap_vai = 0
    for h in anh.hyperedge:
        n_vai = so_vai_da_dien(h)
        phan_bo_so_vai[n_vai] = phan_bo_so_vai.get(n_vai, 0) + 1
        for vai, gia_tri in h.slots.items():
            if gia_tri:
                phan_bo_vai[vai] = phan_bo_vai.get(vai, 0) + 1
        # Khử trùng **trong** từng vai trước khi đếm: chỉ số này khai là "một
        # entity ở hai vai trở lên", còn hai giá trị trùng nhau trong cùng một
        # vai là một chuyện khác hẳn (LLM lặp một giá trị), và trộn hai thứ vào
        # một con số làm câu cảnh báo nói sai thứ nó đang đo.
        tat_ca = [e for gia_tri in h.slots.values() for e in set(gia_tri)]
        if len(tat_ca) != len(set(tat_ca)):
            lap_vai += 1

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
        phan_bo_so_vai=dict(sorted(phan_bo_so_vai.items())),
        phan_bo_vai=dict(sorted(phan_bo_vai.items())),
        so_entity_lap_vai=lap_vai,
        composition_risk_vai_thuc_the=TyLe(
            "Composition-Risk (vai thực thể)",
            len(rui_ro_vai_thuc_the),
            len(nhay_cam),
        ),
        id_composition_risk_vai_thuc_the=tuple(rui_ro_vai_thuc_the),
        siet_theo_scope=siet_theo_scope,
    )


# ---------------------------------------------------------------------------
# Dải sai số của ba tỷ lệ trên nhiều lần chạy cùng một cấu hình (story 2.12)
# ---------------------------------------------------------------------------


class ThieuMauDoDai(ValueError):
    """Đo dải với ít hơn hai mẫu.

    Một mẫu cho biên độ 0, và một trang in "biên độ 0,0 điểm" đọc y như một phép
    đo đã chạy và cho kết quả tuyệt vời - trong khi nó chỉ nói rằng chưa ai chạy
    lần thứ hai. Từ chối chứ không trả một dải rỗng.

    `code` ổn định để test assert trên `code` (AD-8).
    """

    code = "THIEU_MAU_DO_DAI"


@dataclass(frozen=True)
class DaiTyLe:
    """Dải quan sát được của **một** tỷ lệ trên N lần chạy cùng một cấu hình.

    "Cùng một cấu hình" nghĩa là cùng thư mục nguồn, cùng model, cùng prompt,
    cùng từ điển - khác đúng một thứ: lần chạy. Hàm này **không kiểm được** điều
    đó (một `BaTyLe` không mang cấu hình), nên nơi gọi phải khai `ten_cau_hinh`
    và chịu trách nhiệm về nó; đó là lý do tham số đầu tiên là một cái tên chứ
    không phải một tùy chọn.

    `bien_do` là max trừ min, tính bằng **điểm phần trăm** khi in ra. Nó là con
    số mà mọi chênh lệch khác của báo cáo phải được so lại: một chênh lệch nhỏ
    hơn biên độ của chính phép đo thì không đọc thành kết luận định lượng được.
    """

    ten: str
    ten_cau_hinh: str
    gia_tri: tuple[float, ...]
    mau_so: tuple[int, ...]

    @property
    def so_mau(self) -> int:
        return len(self.gia_tri)

    @property
    def nho_nhat(self) -> float:
        return min(self.gia_tri)

    @property
    def lon_nhat(self) -> float:
        return max(self.gia_tri)

    @property
    def bien_do(self) -> float:
        """Max trừ min. Không phải độ lệch chuẩn: với 2-3 mẫu, biên độ quan sát
        được là phát biểu duy nhất còn trung thực."""
        return self.lon_nhat - self.nho_nhat

    @property
    def trung_binh(self) -> float:
        return sum(self.gia_tri) / len(self.gia_tri)

    def mo_ta(self) -> str:
        """Một dòng đọc được, kèm **số mẫu** - một dải không nói nó dựng trên mấy
        lần chạy là một dải không đọc được."""
        return (
            f"{self.nho_nhat:.1%} - {self.lon_nhat:.1%}"
            f" (biên độ {self.bien_do * 100:.1f} điểm, trung bình"
            f" {self.trung_binh:.1%}, {self.so_mau} lần chạy)"
        )

    def nho_hon_bien_do(self, chenh: float | None) -> bool:
        """Một chênh lệch có nằm **trong** biên độ của chính phép đo không.

        `True` nghĩa là chênh đó không đọc thành một kết luận định lượng được:
        hai lần chạy cùng đầu vào đã lệch nhau chừng ấy. `None` (không tính
        được) trả `True`, cùng chiều thận trọng.
        """
        return True if chenh is None else abs(chenh) < self.bien_do


def dai_ba_ty_le(ten_cau_hinh: str, *bo: BaTyLe) -> tuple[DaiTyLe, ...]:
    """Dải của ba tỷ lệ trên N lần chạy **cùng một cấu hình**. Hàm thuần.

    Ba dải trả về theo đúng thứ tự ba tỷ lệ của ADR-012. Mẫu số rỗng ở bất kỳ
    mẫu nào là từ chối: "không tính được" không có chỗ trong một phép lấy min và
    max, và trộn nó vào bằng cách coi như 0 là bịa một mẫu.
    """
    if len(bo) < 2:
        raise ThieuMauDoDai(
            f"đo dải cần ít nhất hai lần chạy, nhận {len(bo)}: một mẫu cho biên"
            " độ 0, và một trang in 'biên độ 0,0 điểm' đọc y như một phép đo đã"
            " chạy chứ không như một phép đo chưa có mẫu thứ hai"
        )
    ra: list[DaiTyLe] = []
    for cot in zip(*(b.bo_ba() for b in bo)):
        thieu = [t for t in cot if t.ti_le is None]
        if thieu:
            raise ThieuMauDoDai(
                f"tỷ lệ {cot[0].ten!r} có {len(thieu)}/{len(cot)} mẫu mẫu số rỗng:"
                " không lấy min/max trên một giá trị không tính được"
            )
        ra.append(
            DaiTyLe(
                ten=cot[0].ten,
                ten_cau_hinh=ten_cau_hinh,
                gia_tri=tuple(t.ti_le for t in cot),
                mau_so=tuple(t.mau_so for t in cot),
            )
        )
    return tuple(ra)


# ---------------------------------------------------------------------------
# Hạn chế một ảnh chụp về đúng tập tài liệu chung (story 2.13)
# ---------------------------------------------------------------------------


class KhongCoTaiLieuChung(ValueError):
    """Hai ảnh chụp không có `doc_key` nào chung: không có phép đối chứng nào.

    Từ chối thay vì trả một ảnh rỗng. Một `AnhDoThi` không hyperedge nào cho ba
    tỷ lệ `None`, và một khối đối chứng in ba dòng "không so được" đọc như một
    kết quả chứ không như một lỗi cấu hình.

    Ca thật nó bắt: hai ảnh chụp bằng **hai muối khác nhau**. Khi đó mọi
    `doc_key` đã băm là hai tập rời nhau hoàn toàn, dù hai space chứa đúng cùng
    một thư mục nguồn.

    `code` ổn định để test assert trên `code` (AD-8).
    """

    code = "KHONG_CO_TAI_LIEU_CHUNG"


def tai_lieu_chung(*anh: AnhDoThi) -> frozenset[str]:
    """Tập `doc_key` có mặt trong sổ tài liệu của **mọi** ảnh chụp truyền vào.

    Với hai ảnh **rút gọn cùng muối**, `doc_key` là băm có muối của cùng một tên
    file, nên phép giao này tính được ngay trong repo mà không cần ảnh đầy đủ và
    không cần kho đang chạy. Đó là lợi ích thứ hai của luật cùng muối.
    """
    if not anh:
        return frozenset()
    tap = [a.doc_key for a in anh]
    return frozenset(set.intersection(*(set(t) for t in tap)))


def han_che_theo_tai_lieu(anh: AnhDoThi, doc_key_giu) -> AnhDoThi:
    """Ảnh chụp thu về đúng tập `doc_key` cho trước. Hàm thuần, không I/O.

    Vì sao nó tồn tại: story 2.13 so cột `real` với cột `that_khu` để đo chênh
    giữa hai bộ trích xuất trên **cùng một tập tài liệu**. Hai thư mục nguồn
    đúng là cùng 50 file từng byte, nhưng hai *kho* thì không - Qwen làm mất 9
    tài liệu ở đợt `real`, nên cột đó chỉ có 41. So 41 với 50 là trộn vào phép
    đo chênh thêm 9 tài liệu chỉ có ở một vế, và trang lại tự khẳng định hai vế
    bằng nhau. Hàm này là chỗ phép hạn chế sống, tách khỏi module dựng HTML để
    nó có test riêng.

    **Giữ một hyperedge khi *mọi* `doc_key` của nó nằm trong tập giữ**, không
    phải khi có một cái nằm trong. Một hyperedge hợp nhất từ một tài liệu được
    giữ và một tài liệu bị bỏ tồn tại *vì cả hai*, nên đếm nó là đếm một fact
    quy được một phần cho tài liệu ngoài tập so. Trên hai ảnh của story 2.13 hai
    luật cho cùng một con số (không hyperedge nào đa nguồn), nên lựa chọn này là
    một quyết định ghi trước chứ không phải một phép tối ưu con số.

    Ba số đếm dẫn xuất (`so_tai_lieu`, `so_hyperedge`, `so_hyperedge_da_nguon`)
    là property tính từ hai tuple nên chúng tự đúng theo; `space` giữ nguyên để
    tiêu đề cột vẫn nói ra dạng file đang dùng.
    """
    giu = frozenset(doc_key_giu)
    tai_lieu = tuple(t for t in anh.tai_lieu if t.doc_key in giu)
    if not tai_lieu:
        raise KhongCoTaiLieuChung(
            f"hạn chế ảnh chụp {anh.space!r} về {len(giu)} `doc_key` cho ra 0 tài"
            " liệu: hai ảnh không chung tài liệu nào. Ca hay gặp nhất là hai ảnh"
            " rút gọn chụp bằng **hai muối khác nhau** - khi đó mọi `doc_key` đã"
            " băm là hai tập rời nhau dù thư mục nguồn là một"
        )
    hyperedge = tuple(h for h in anh.hyperedge if set(h.doc_key) <= giu)
    return replace(anh, tai_lieu=tai_lieu, hyperedge=hyperedge)


class ThieuCotDoiChieu(ValueError):
    """Đối chiếu gọi với ít hơn hai cột.

    Một bảng một cột không trả lời câu hỏi nào của story 2.10, và in nó ra rồi
    thoát 0 là để người đọc tưởng bước đối chiếu đã chạy.
    """

    code = "THIEU_COT_DOI_CHIEU"


@dataclass(frozen=True)
class DongDoiChieu:
    """Một hàng của bảng đối chiếu: cùng một tỷ lệ, N cột, N-1 chênh lệch.

    Cột đầu là **mốc**; mọi chênh lệch tính so với nó. Story 2.10 chỉ có hai cột
    nên `trai`/`phai`/`chenh` đủ mô tả một hàng; story 2.11 thêm cột `real` và
    một hàng phải mang được nhiều hơn hai ô. Ba tên cũ giữ lại thành thuộc tính
    dẫn xuất: chúng là hợp đồng của trang hai cột và của test đã khóa số.
    """

    ten: str
    cot: tuple[TyLe, ...]

    @property
    def trai(self) -> TyLe:
        """Cột mốc."""
        return self.cot[0]

    @property
    def phai(self) -> TyLe:
        """Cột thứ hai - cột duy nhất được so ở trang hai cột của story 2.10."""
        return self.cot[1]

    def chenh_voi_moc(self, i: int) -> float | None:
        """Chênh lệch điểm phần trăm giữa cột `i` và cột mốc; `None` nếu một bên
        không tính được (mẫu số rỗng)."""
        a, b = self.cot[0].ti_le, self.cot[i].ti_le
        return None if a is None or b is None else b - a

    @property
    def chenh(self) -> float | None:
        """Chênh lệch của cột thứ hai so với mốc (phải trừ trái)."""
        return self.chenh_voi_moc(1)


def doi_chieu(*bo: BaTyLe) -> tuple[DongDoiChieu, ...]:
    """Ba hàng đối chiếu N space, giữ nguyên thứ tự ba tỷ lệ của ADR-012.

    Đây là phép "khớp cỡ" của story 2.10, và nó chỉ nói được điều gì khi có từ
    hai cột trở lên kèm chênh lệch: một bảng chỉ in cột `khao_sat` là một bảng
    không trả lời câu hỏi nào. Chữ ký cũ `doi_chieu(trai, phai)` là ca hai cột
    của chữ ký này, không phải một hàm khác.
    """
    if len(bo) < 2:
        raise ThieuCotDoiChieu(
            f"đối chiếu cần ít nhất hai space, nhận {len(bo)}:"
            " một cột đứng một mình không trả lời được câu hỏi khớp cỡ"
        )
    return tuple(
        DongDoiChieu(cot[0].ten, tuple(cot)) for cot in zip(*(b.bo_ba() for b in bo))
    )


def loai_chung(*bo: BaTyLe) -> frozenset[str]:
    """Loại nội dung *thật* (bỏ nhãn ca không khóa) có mặt ở **mọi** cột.

    Trục chung của phép so. Phần riêng của mỗi cột là phần nằm ngoài tập này;
    với hai cột nó đúng bằng hiệu hai chiều mà story 2.10 in ra.
    """
    tap = [
        {t for t in b.phan_bo_loai if not t.startswith(NHAN_KHONG_KHOA)} for b in bo
    ]
    return frozenset(set.intersection(*tap)) if tap else frozenset()


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
