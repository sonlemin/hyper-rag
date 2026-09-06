"""Kho chính sách của tiến trình phục vụ: nạp nóng 4 cấu hình đo (AD-6, FR-28).

Đây là chỗ một tiến trình đang chạy đổi từ bảng chính sách A sang bảng B mà
không khởi động lại và không chạm một byte dữ liệu nào: mức tiết lộ tính **lúc
truy vấn**, không ghi lên kho, nên hoán bảng là hoán một object trong bộ nhớ.

Ba luật của module này, và cả ba đều là cơ chế chứ không phải quy ước.

**Danh mục id là danh mục đóng, suy từ chính glob `config/policy-*.yaml`.**
Endpoint nhận một id (`day-du`, `nhi-phan`, `tat-phan-quyen`, `toi-thieu-l1`),
không nhận đường dẫn: một tham số đường dẫn tự do trên một endpoint admin là
một đường đọc file tùy ý của tiến trình phục vụ, và `../../etc/passwd` là ca rẻ
nhất để thấy điều đó. Phép quét và hình dạng id sống ở
`adapters/policy_loader.py` chứ không ở đây, vì `eval/` cũng phải quét đúng tập
file ấy mà không import được `api/`.

**Không đường dẫn hệ thống nào ra khỏi module này**, cả ở ca id lạ lẫn ca file
hỏng. Thông điệp của `PolicyInvalid` mang đường dẫn tuyệt đối vì nó viết cho
người vận hành đọc log; thân một phản hồi 400 thì không, nên `hoan` cắt phần
thư mục và chỉ giữ tên file.

**Thứ tự của một lần hoán: nạp -> ghi audit -> mới thay.** Nạp trước nên một
file hỏng không bao giờ thay được bảng đang chạy (fail-closed đúng chiều: hệ
tiếp tục với bảng cũ, không rơi về policy rỗng). Ghi audit trước khi thay nên
audit hỏng là thao tác hỏng, đúng nghĩa tầng mutation của AD-16: một khoảng
thời gian mà hệ chạy bảng B nhưng sổ audit nói nó chạy bảng A là một khoảng
không ai giải thích được sau này.

**`hien_tai()` đọc nguyên tử.** Một lần đọc thuộc tính trả về một object bất
biến, nên một request dựng ngữ cảnh quyền giữa lúc hoán vẫn thấy trọn vẹn một
bảng - không nửa nọ nửa kia. Điều kiện là nơi gọi đọc **đúng một lần** ở đầu
request rồi truyền object đó xuống; đọc lại giữa chừng là hai adapter thấy hai
bản chính sách trong cùng một request, đúng thứ AD-3 sinh ra để chặn.

`redteam/` và `eval/` **không** đi qua module này: chúng gọi thẳng
`adapters/policy_loader.load_policy`, nằm dưới lớp này (AD-15). Nơi tiêm kịch
bản red-team tự nạp và khôi phục policy trong try/finally, và việc đó không đi
qua API ghi đè nên nó không mở một đường vòng quyền admin cho tài khoản demo.
"""

import asyncio
import os
from pathlib import Path
from typing import Mapping

from adapters.policy_loader import (
    THU_MUC_CAU_HINH,
    cac_bang_chinh_sach,
    la_id_policy,
    load_policy,
)
from api.xac_thuc import LoiXacThuc
from core.audit import (
    EVENT_POLICY_SWAP,
    SPACE_TIEN_TRINH,
    TIER_MUTATION,
    AuditPort,
    SuKienAudit,
    ghi_bien_doi,
    thoi_diem_utc,
)
from core.policy import Policy, PolicyInvalid

# Id của bảng vận hành. Cũng là mặc định của biến môi trường ở lifespan: một
# tiến trình khởi động mà không ai khai id policy phải chạy bảng đầy đủ, không
# phải một cấu hình đo.
ID_MAC_DINH: str = "day-du"

# Biến môi trường trỏ id policy mặc định. **Không phải secret**, nên nó sống ở
# `.env.server`/`.env.laptop` cùng các tham số môi trường khác.
BIEN_ID_POLICY: str = "HYPER_RAG_POLICY_ID"

MA_ID_KHONG_CO: str = "POLICY_ID_KHONG_CO"

# Danh mục rỗng là một ca **khác** id lạ, và nó có mã riêng: `config/` không
# mount được trong container cho một danh mục rỗng, và khi đó thông điệp của ca
# id lạ cụt ngang ở chữ "danh mục là " - một câu không nói được gì cho người
# đang tìm hiểu vì sao endpoint hỏng.
MA_DANH_MUC_RONG: str = "POLICY_DANH_MUC_RONG"

# Space của sự kiện hoán policy. Bảng chính sách là cấu hình của **cả** tiến
# trình chứ không của một không gian tri thức, mà `SuKienAudit` đòi `space`
# không rỗng. Từ story 3.6 hằng và luật của nó sống ở `core/audit.py`
# (`SPACE_TIEN_TRINH`: hàng thuộc tiến trình, mọi tổng theo space không trả nó,
# cửa đọc là `AuditPostgres.su_kien_tien_trinh`); tên cũ giữ lại làm re-export.
SPACE_TOAN_HE: str = SPACE_TIEN_TRINH


def ma_policy_mac_dinh(moi_truong: Mapping[str, str] | None = None) -> str:
    """Id bảng chính sách mà tiến trình khởi động với; mặc định `day-du`.

    Đọc từ môi trường chứ không hard-code vì FR-28 đòi chạy được cả bốn cấu
    hình đo; mặc định là bảng vận hành chứ không phải một cấu hình đo, vì một
    tiến trình khởi động mà không ai khai id phải chạy thứ an toàn nhất trong
    bốn thứ, không phải thứ đầu bảng chữ cái.

    Ở đây chứ không ở `api/main.py` (story 3.6): đường nạp (`api/do_chi_phi.py`,
    `api/man_nap.py`) cũng phải đọc đúng cửa này để `policy_version` của các
    hàng audit ingest là bảng mà tiến trình đang chạy, không phải một hằng
    đường dẫn - `main.py` chỉ import lại.
    """
    nguon = os.environ if moi_truong is None else moi_truong
    gia_tri = nguon.get(BIEN_ID_POLICY)
    # `strip()` trên một giá trị không phải chuỗi là `AttributeError` giữa
    # lifespan, xa chỗ gây ra. Một biến môi trường luôn là chuỗi, nhưng hàm này
    # nhận `moi_truong` từ bộ test nên nó phải chịu được một map bất kỳ.
    return (gia_tri.strip() if isinstance(gia_tri, str) else "") or ID_MAC_DINH


def duong_dan_policy_mac_dinh(moi_truong: Mapping[str, str] | None = None) -> Path:
    """Đường dẫn của bảng mà tiến trình này chạy: `duong_dan_cua(ma_policy_mac_dinh())`.

    Cửa duy nhất mà đường nạp lấy bảng mặc định; không module nào giữ một hằng
    đường dẫn policy riêng nữa.
    """
    return duong_dan_cua(ma_policy_mac_dinh(moi_truong))


class LoiChinhSach(LoiXacThuc):
    """Lỗi của đường hoán policy; cùng hình dạng `{error: {code, message}}`.

    Kế thừa `LoiXacThuc` để dùng lại đúng một exception handler của `api/main.py`
    - hai handler cho hai lớp lỗi cùng hình dạng là hai chỗ để envelope trôi dạt.
    """


def danh_muc(thu_muc: str | Path | None = None) -> dict[str, Path]:
    """Danh mục **đóng** id -> đường dẫn; rỗng là một mã lỗi riêng.

    Phép quét ở `adapters/policy_loader.cac_bang_chinh_sach`; ở đây chỉ thêm
    luật "rỗng là hỏng". Một danh mục rỗng nghĩa là `config/` không có file nào
    - trong container thì đó là một volume chưa mount, không phải một người gõ
    sai id - nên nó phải nói ra chính điều đó thay vì đi tiếp thành một thông
    điệp "danh mục là " cụt ngang.
    """
    goc = Path(thu_muc) if thu_muc is not None else THU_MUC_CAU_HINH
    bang = cac_bang_chinh_sach(goc)
    if not bang:
        raise LoiChinhSach(
            500,
            MA_DANH_MUC_RONG,
            "không có bảng chính sách nào trong thư mục cấu hình",
        )
    return bang


def duong_dan_cua(ma: str, thu_muc: str | Path | None = None) -> Path:
    """Đường dẫn của một id trong danh mục; id lạ là `POLICY_ID_KHONG_CO` (400).

    Thân phản hồi **không** in đường dẫn hệ thống, kể cả ở ca id lạ: nó là một
    endpoint mở cho người dùng gọi, và cấu trúc thư mục của máy chủ không phải
    thứ đi ra theo một lỗi 400. Nó in danh mục id hợp lệ, thứ vừa hữu ích vừa
    đã công khai qua `GET /admin/policy`.
    """
    bang = danh_muc(thu_muc)
    if not la_id_policy(ma) or ma not in bang:
        raise LoiChinhSach(
            400,
            MA_ID_KHONG_CO,
            "id bảng chính sách không có trong danh mục; danh mục là "
            + ", ".join(sorted(bang)),
        )
    return bang[ma]


def _khong_lo_duong_dan(loi: PolicyInvalid, duong_dan: Path) -> str:
    """Thông điệp của loader, thay đường dẫn tuyệt đối bằng đúng tên file.

    `load_policy` gắn `f"{duong_dan}: ..."` vào mọi lỗi lược đồ, và `duong_dan`
    là đường dẫn tuyệt đối. Hàm này thay **chuỗi đó**, không cắt theo dấu hai
    chấm: phần sau dấu hai chấm còn mang tên vai và tên loại nội dung, và cắt
    theo dấu phân tách là cắt nhầm ngay khi thông điệp có dấu thứ hai.
    """
    return str(loi).replace(str(duong_dan), duong_dan.name)


class KhoChinhSach:
    """Bảng chính sách đang chạy của tiến trình, hoán được lúc chạy.

    Trạng thái là **một** thuộc tính giữ một tuple `(id, Policy)`, gán bằng một
    lệnh gán duy nhất. Hai thuộc tính rời nhau thì có một khoảnh khắc id đã đổi
    mà policy chưa, và một request rơi đúng vào đó sẽ ghi audit sai tên bảng.
    """

    def __init__(self, ma: str, policy: Policy, thu_muc: str | Path | None = None):
        self._hien_tai: tuple[str, Policy] = (ma, policy)
        self._thu_muc = thu_muc
        # Tuần tự hóa cả ba bước của một lần hoán. Không có khóa thì hai POST
        # song song đan nhau qua `await ghi_bien_doi`: cả hai đọc cùng một
        # `policy_id_cu`, ghi hai hàng audit nói cùng một chuyện, và bảng thắng
        # là bảng gán sau chứ không phải bảng ghi sau - đúng "khoảng thời gian
        # không ai giải thích được" mà module này tồn tại để chặn.
        self._khoa = asyncio.Lock()

    @classmethod
    def nap(cls, ma: str, thu_muc: str | Path | None = None) -> "KhoChinhSach":
        """Dựng kho từ một id; file hỏng là `PolicyInvalid` ngay lúc khởi động."""
        return cls(ma, load_policy(duong_dan_cua(ma, thu_muc)), thu_muc)

    @property
    def ma(self) -> str:
        return self._hien_tai[0]

    def hien_tai(self) -> Policy:
        """Bảng đang chạy. Đọc một lần ở đầu request rồi truyền object đi."""
        return self._hien_tai[1]

    def ma_va_policy(self) -> tuple[str, Policy]:
        """Cả id lẫn bảng, trong **một** phép đọc nguyên tử.

        Nơi gọi nào cần cả hai phải dùng hàm này, không phải `ma` rồi
        `hien_tai()`: hai phép đọc quanh một `await` là hai bản chính sách trong
        cùng một request, đúng thứ AD-3 sinh ra để chặn - và ở handler
        `POST /admin/policy` nó còn báo id của bảng này kèm `policy_version` của
        bảng kia.
        """
        return self._hien_tai

    def danh_muc(self) -> list[str]:
        return sorted(danh_muc(self._thu_muc))

    async def hoan(
        self,
        ma: str,
        *,
        audit: AuditPort,
        act: str | None = None,
        role: str | None = None,
    ) -> tuple[str, Policy]:
        """Hoán sang bảng `ma`: nạp, ghi audit mutation, rồi mới thay.

        Trả **cả cặp** `(id, Policy)` chứ không riêng bảng, để nơi gọi không
        phải đọc lại `ma` sau đó - một phép đọc thứ hai sau `await` là một cặp
        có thể đã bị một lần hoán khác chen vào giữa.

        Ba cách hỏng, ba kết cục, và không cách nào để lại một bảng nửa vời:

        - id lạ -> 400 `POLICY_ID_KHONG_CO`, không chạm đĩa ngoài `config/`;
        - file hỏng -> 400 `POLICY_INVALID`, **bảng đang chạy giữ nguyên**;
        - audit hỏng -> lỗi dội lên nơi gọi và hoán **không** có hiệu lực.

        Cả ba bước chạy dưới một `asyncio.Lock`, nên hai lần hoán đồng thời nối
        đuôi nhau: hàng audit thứ hai khai `policy_id_cu` là bảng mà lần hoán
        thứ nhất vừa đặt, và thứ tự trong sổ audit bằng thứ tự thật.

        Hoán sang chính bảng đang chạy vẫn ghi audit: một lần gọi có hiệu lực
        (dù kết quả trùng) là một lần cần bản ghi, và nhánh "im lặng khi trùng"
        là một lỗ trong lịch sử mà không ai nhìn thấy lúc đọc code.
        """
        duong_dan = duong_dan_cua(ma, self._thu_muc)
        async with self._khoa:
            try:
                moi = load_policy(duong_dan)
            except PolicyInvalid as loi:
                # Thông điệp của `PolicyInvalid` mở đầu bằng đường dẫn tuyệt đối
                # - đúng cho một dòng log, sai cho thân một phản hồi 400. Cắt
                # phần thư mục và giữ tên file: người gọi cần biết *bảng nào*
                # hỏng và hỏng ở đâu trong bảng, không cần biết cây thư mục của
                # máy chủ. Cùng luật với ca id lạ ở `duong_dan_cua`.
                raise LoiChinhSach(
                    400, PolicyInvalid.code, _khong_lo_duong_dan(loi, duong_dan)
                ) from None
            cu_ma, cu = self._hien_tai
            await ghi_bien_doi(
                audit,
                SuKienAudit(
                    tier=TIER_MUTATION,
                    event=EVENT_POLICY_SWAP,
                    space=SPACE_TOAN_HE,
                    # `policy_version` của một sự kiện là bảng đang hiệu lực lúc
                    # nó xảy ra, tức bảng **cũ**: lúc dòng audit này được ghi,
                    # bảng mới chưa thay. Bảng mới nằm ở `chi_tiet`, nên một
                    # hàng nói đủ cả hai đầu của phép hoán.
                    policy_version=cu.policy_version,
                    thoi_diem=thoi_diem_utc(),
                    act=act,
                    role=role,
                    chi_tiet={
                        "policy_id_cu": cu_ma,
                        "policy_id_moi": ma,
                        "policy_version_moi": moi.policy_version,
                    },
                ),
            )
            self._hien_tai = (ma, moi)
            return self._hien_tai
