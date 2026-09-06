"""Sinh câu trả lời từ ngữ cảnh truy hồi, kèm cờ no-answer có cấu trúc (story 3.5, FR-16).

Bước sinh câu trả lời được lấy về cho dự án. Cho tới story 3.3 nó là
`vendor/hypergraphrag/operate.py::kg_query` gọi `PROMPTS["rag_response"]`, và
prompt ấy không dùng được cho FR-16 vì ba lý do đọc thẳng từ mã nguồn vendor:

- Tín hiệu no-answer duy nhất của nó là văn xuôi tiếng Anh (`prompt.py:199`,
  "If you don't know the answer, just say so"). FR-16 đòi **một cờ có cấu
  trúc**, và đoán cờ từ văn bản trả về là đặt an toàn lên chính thứ chốt brief
  §6 cấm assert.
- Nó còn *cho phép* LLM "incorporating any relevant general knowledge"
  (`prompt.py:196`), tức khuyến khích đúng hành vi bịa mà FR-16 cấm.
- Ba đường thay thế đều đóng: sửa `vendor/` là cấm (AGENTS.md); mutate
  `PROMPTS` lúc chạy là đổi prompt bằng side effect, tức một prompt không đọc
  được từ mã nguồn; và ép LLM trả JSON bằng cách bọc ngoài thì vẫn là prompt
  tiếng Anh của người khác trong một báo cáo phương pháp tiếng Việt.

Đường còn lại - và nó **không** làm tăng chi phí - là lấy ngữ cảnh bằng
`QueryParam(only_need_context=True)` (`operate.py:596-597` thoát *trước* lời gọi
LLM thứ hai) rồi tự gọi LLM bằng prompt của dự án. Số lời gọi mỗi lượt trả lời
vẫn là 2; lượt từ chối vì ngữ cảnh rỗng tụt xuống 1.

Module ở `adapters/` chứ không ở `api/` vì hai lý do, cả hai là ràng buộc chứ
không phải sở thích. Một, `api/` không được import `vendor/`
(`tests/test_import_lint.py`), mà hằng `PROMPTS["fail_response"]` và luật đọc
khung ngữ cảnh đều là kiến thức về `vendor/`. Hai, prompt là **dữ liệu của
phương pháp khóa luận** - nó phải đọc được ở đúng một chỗ, cạnh prompt trích
xuất của story 2.4, chứ không nằm rải trong một handler HTTP.

Ba hàm ở đây đều **thuần**: `ngu_canh_rong` đọc một chuỗi, `doc_dau_ra` đọc một
chuỗi, `dung_prompt` ghép hai chuỗi. Lời gọi LLM nằm ở `adapters/engine.py`,
nơi đã cầm `self.llm_model_func`. Story 5.3 thêm một hàm thuần thứ tư,
`hop_nhat_ngu_canh`: ghép các dòng của đường phụ theo grant break-glass vào khối
Relationships của khung, khử trùng theo id hyperedge.
"""

import csv
import io
import json
import logging
import re
from dataclasses import dataclass
from typing import Mapping

from hypergraphrag.prompt import PROMPTS

from adapters.trich_dan import TrichDan, TrichDanNgoaiQuyen
from core.ids import normalize_id
from core.masking import (
    MASK_REASON_L2_ONLY,
    MASK_REASON_NO_KEY,
    MASK_REASON_OWNER,
    MASK_REASON_POLICY,
    dau_che,
    dau_che_lan_can_khong_khoa,
    dau_che_owner,
    dau_che_truong,
)

# Câu hỏng đóng hộp của upstream, **re-export chứ không chép**. `kg_query` trả
# nguyên chuỗi này ở ba chỗ còn sống (`operate.py:573,576,581`), cả ba là ca
# "LLM không trích được từ khóa" - `:568` (`json.JSONDecodeError`) không tới
# được vì khối `try` bao quanh nó chỉ chứa regex và tách chuỗi, còn `:599`
# (`context is None`) là code chết vì `_build_query_context` không có một
# `return None` nào. Chép chuỗi vào đây thay vì đọc `PROMPTS` là mở đường cho
# một bản upstream mới đổi câu ấy mà nhánh nhận diện không đổi theo, và khi đó
# một lỗi nội bộ lại đi ra thành `answer` như trước story này.
CAU_HONG_UPSTREAM: str = PROMPTS["fail_response"]

logger = logging.getLogger(__name__)

# --- Ba lý do từ chối ----------------------------------------------------------

# Ba giá trị, khai thành hằng vì hai trong ba là **cột của một phép đo**: PRD
# 5.2 đòi Đo 2 báo cáo tách "từ chối qua cờ LLM" với "từ chối qua nhánh ngữ
# cảnh rỗng không gọi LLM", không đếm gộp để khỏi bơm độ chính xác của cờ.
# Giá trị thứ ba đứng riêng đúng vì nó **không** thuộc cột nào: nó là ca hệ
# thống không trích nổi từ khóa, và trộn nó vào một trong hai cột kia là bơm
# một con số của Đo 2 bằng một lỗi nội bộ.
LY_DO_NGU_CANH_RONG: str = "ngu_canh_rong"
LY_DO_CO_NO_ANSWER: str = "co_no_answer"
LY_DO_TU_KHOA_RONG: str = "tu_khoa_rong"
LY_DO_TU_CHOI: frozenset[str] = frozenset(
    {LY_DO_NGU_CANH_RONG, LY_DO_CO_NO_ANSWER, LY_DO_TU_KHOA_RONG}
)

# --- Lược đồ đầu ra ------------------------------------------------------------

# Hai khóa của đầu ra LLM. Hằng vì cả prompt lẫn bộ đọc đều nhắc tới chúng, và
# hai bản viết tay lệch nhau một chữ là một cờ không bao giờ bật được.
KHOA_KHONG_CO_DAP_AN: str = "khong_co_dap_an"
KHOA_CAU_TRA_LOI: str = "cau_tra_loi"

# Tham số của lời gọi sinh câu trả lời. Cùng ba knob với
# `adapters/trich_xuat.THAM_SO_LLM` và cùng lý do: `temperature=0` để NFR-02
# giữ được tính lặp lại, `response_format` json_object vì cờ phải parse được,
# `max_tokens` hữu hạn để một lượt sinh lặp không tiêu hết ngân sách. `max_tokens`
# nhỏ hơn hẳn của đường nạp (8192): một câu trả lời cho người đọc không dài bằng
# một danh sách fact của cả một chunk, và trần này là trần *tiền*.
THAM_SO_LLM: Mapping[str, object] = {
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "max_tokens": 2048,
}


class DauRaTraLoiKhongDoc(Exception):
    """Đầu ra LLM không đọc được theo lược đồ hai khóa.

    **Đây là lỗi hệ thống, không phải một lý do từ chối.** Nơi gọi phải đổi nó
    thành 5xx; suy diễn nó thành một lượt từ chối là dựng nhánh từ chối thứ tư
    và là hệ nói dối về chính trạng thái của nó - đúng thứ làm hai cột của Đo 2
    đếm nhầm.
    """


class NguCanhTruyHoiLa(DauRaTraLoiKhongDoc):
    """Đường truy hồi trả về một thứ không phải chuỗi ngữ cảnh.

    Kế thừa `DauRaTraLoiKhongDoc` chứ không đứng riêng, và đó là quyết định về
    **mã lỗi**: cả hai là cùng một mệnh đề - "một tầng dưới trả về thứ tầng này
    không đọc được" - nên chúng ra cùng một 5xx ổn định thay vì mở thêm một mã
    trên bề mặt API. Lớp riêng thì log và test còn phân biệt được hai nguồn.

    Vì sao phải có nó: `ngu_canh_rong` trả `True` cho mọi giá trị không phải
    `str` (một `None`, một object), nên không có cửa này thì một lỗi nội bộ của
    đường truy hồi lặng lẽ thành một lượt từ chối **được đo** và bơm một trong
    hai cột của Đo 2.
    """


@dataclass(frozen=True)
class KetQuaTraLoi:
    """Đầu ra LLM đã đọc: cờ no-answer cộng câu trả lời."""

    khong_co_dap_an: bool
    cau_tra_loi: str


@dataclass(frozen=True)
class KetQuaHoiDap:
    """Kết quả một lượt hỏi: **hoặc** một câu trả lời, **hoặc** một lý do từ chối.

    Bất biến XOR kiểm ngay lúc dựng, và nó là chỗ luật "không có nhánh thứ tư"
    sống dưới dạng cơ chế: một kết quả mang cả hai (hay không mang gì) không tồn
    tại được, nên handler không phải đoán xem trường nào thắng. Nhờ vậy phép
    dựng envelope chỉ còn một dòng `refused=ly_do_tu_choi is not None` và không
    có ca nào `answer` khác `None` mà `refused` là `True`.

    **Câu trả lời rỗng cũng bị chặn ở đây**, không chỉ ở `doc_dau_ra`. Hai chỗ
    kiểm cùng một điều nghe như thừa, nhưng chúng canh hai đường khác nhau:
    `doc_dau_ra` canh thứ LLM trả về, còn cửa này canh **bất biến mà handler dựa
    vào**. Thiếu nó thì `KetQuaHoiDap(cau_tra_loi="")` dựng được, và một nơi gọi
    thứ hai - một engine giả trong test, một nhánh tương lai - cho ra
    `answer: ""` kèm `refused: false`, tức một lượt trả lời rỗng mà người dùng
    đọc thành một lượt từ chối không có template.

    `trich_dan` (story 3.4) là tuple `TrichDan` theo thứ tự xuất hiện trong ngữ
    cảnh, và **lượt từ chối thì rỗng** - bất biến kiểm ở đây, không ở handler:
    một lượt từ chối mang citation là một envelope từ chối khác byte với hai
    lượt kia, tức chính kênh dò mà FR-16 dựng ra để bịt (phép so byte của
    `tests/test_tu_choi.py`). Lượt trả lời không bắt buộc có citation: ngữ
    cảnh không phải khung vendor cho danh sách id rỗng, và lượt ấy vẫn trả lời.
    """

    cau_tra_loi: str | None = None
    ly_do_tu_choi: str | None = None
    trich_dan: tuple[TrichDan, ...] = ()

    def __post_init__(self):
        if not isinstance(self.trich_dan, tuple) or not all(
            isinstance(td, TrichDan) for td in self.trich_dan
        ):
            raise TypeError("trich_dan phải là tuple các TrichDan")
        if self.ly_do_tu_choi is not None and self.trich_dan:
            raise ValueError(
                "lượt từ chối không mang citation: envelope từ chối phải bằng"
                " nhau từng byte giữa mọi lý do (FR-16)"
            )
        co_tra_loi = self.cau_tra_loi is not None
        co_ly_do = self.ly_do_tu_choi is not None
        if co_tra_loi == co_ly_do:
            raise ValueError(
                "KetQuaHoiDap mang đúng một trong hai: câu trả lời hoặc lý do từ"
                f" chối; nhận được cau_tra_loi={self.cau_tra_loi!r},"
                f" ly_do_tu_choi={self.ly_do_tu_choi!r}"
            )
        if co_tra_loi and not isinstance(self.cau_tra_loi, str):
            raise TypeError(
                f"cau_tra_loi phải là chuỗi, nhận được {type(self.cau_tra_loi).__name__}"
            )
        if co_tra_loi and not self.cau_tra_loi.strip():
            raise ValueError(
                "cau_tra_loi rỗng: một lượt trả lời không có chữ nào là một lượt"
                " từ chối chưa khai lý do, không phải một câu trả lời"
            )
        if co_ly_do and self.ly_do_tu_choi not in LY_DO_TU_CHOI:
            raise ValueError(
                f"lý do từ chối {self.ly_do_tu_choi!r} không có trong danh mục"
                f" {sorted(LY_DO_TU_CHOI)}"
            )


# --- Prompt --------------------------------------------------------------------

# Hai chỗ chèn. Không dùng `str.format`, cùng lý do với `adapters/trich_xuat.py`:
# ngữ cảnh là ba bảng CSV có dấu ngoặc nhọn, và một `format` trên nó nổ ở ký tự
# đầu tiên.
_CHO_NGU_CANH: str = "<<NGU_CANH>>"
_CHO_CAU_HOI: str = "<<CAU_HOI>>"

# Dòng đầu của prompt, tách thành hằng để bộ test và bản giả LLM nhận diện được
# **lượt sinh câu trả lời** bằng một mốc chỉ prompt này có. Trước đây bản giả dò
# chuỗi `khong_co_dap_an`, mà đó là một chuỗi người hỏi gõ được vào câu hỏi: một
# câu hỏi chứa nguyên văn tên khóa ấy làm lượt *trích từ khóa* bị nhận nhầm
# thành lượt trả lời, và ca test khi đó đo nhầm nhánh mà vẫn xanh.
DAU_PROMPT_TRA_LOI: str = (
    "Bạn là trợ lý hỏi đáp trên kho tri thức vận hành IT nội bộ."
)

# Hai ví dụ, một cho mỗi giá trị của cờ. Cả hai đều cần: một ví dụ chỉ có nhánh
# trả lời dạy LLM rằng nhánh kia là ngoại lệ, và cờ no-answer là nhánh mà FR-16
# đứng lên.
# Ví dụ thứ ba (story 3.4, ADR-016): một dấu che nằm **đúng chỗ** trong câu trả
# lời, dựng từ chính `dau_che` chứ không viết tay - đó là hình dạng mà luật
# "chép nguyên dấu che" mô tả, và một ví dụ nói được điều mà một câu luật không
# nói hết: dấu che đứng thay giá trị, câu vẫn trọn vẹn, không có lời bình nào.
VI_DU_DAU_RA: str = "\n".join(
    json.dumps(muc, ensure_ascii=False)
    for muc in (
        {
            KHOA_KHONG_CO_DAP_AN: False,
            KHOA_CAU_TRA_LOI: "App01 trả lỗi 502 do giới hạn bộ nhớ của pool PHP-FPM bị chỉnh sai.",
        },
        {KHOA_KHONG_CO_DAP_AN: True, KHOA_CAU_TRA_LOI: ""},
        {
            KHOA_KHONG_CO_DAP_AN: False,
            KHOA_CAU_TRA_LOI: f"App01 trả lỗi 502 do {dau_che('cause')}, đã khắc phục bằng cách khởi động lại pool PHP-FPM.",
        },
    )
)

# Tên trường và tên nhóm **giả** chỉ dùng để dựng ví dụ dấu che. Chúng không
# phải một tên có thật trong `config/nhom-phu-trach.yaml`: prompt là văn bản
# cố định gửi cho mọi vai, và một tên nhóm thật nằm sẵn trong nó là một tên mà
# model có thể chép ra ở một lượt mà ngữ cảnh không hề mang nhóm ấy.
_TRUONG_VI_DU: str = "description"
_NHOM_VI_DU: str = "TenNhom"

# Ví dụ dấu che, **dựng từ chính hàm của `core/masking.py`** chứ không viết tay.
# Đây là chỗ bản đầu của story 3.5 sai nặng nhất: prompt mô tả dấu che là
# `[tên_vai: che]` trong khi dấu thật là `[cause:masked]` - không khoảng trắng
# sau dấu hai chấm, lý do bằng tiếng Anh - nên model đọc `masked` như nội dung.
#
# Luật đi kèm đổi ở story 3.4 (ADR-016). 3.5 cấm chép dấu che vào câu trả lời,
# vì khi đó `[owner:DevOps]` chép ra `answer` là tên nhóm phụ trách rò qua
# endpoint mở nhất của hệ. Từ 3.4 nhóm phụ trách đã ra qua `citations[].owner_group`
# cho đúng cùng vai và cùng hyperedge, nên dấu che trong `answer` không lộ thêm
# gì; ngược lại, một câu trả lời *bỏ trống* chỗ bị che đọc như fact thiếu một
# vế, còn dấu che tại chỗ là thứ Epic 4 bôi đen được và nối được vào citation.
# Luật mới: **chép nguyên dấu che vào đúng chỗ, không đoán, không bỏ**.
#
# `adapters/` được phép import `core/`, nên hai bên không trôi khỏi nhau được:
# đổi `MASK_REASON_*` hay đổi `dau_che_truong` là prompt đổi theo trong cùng một
# lần chạy, và `tests/test_tu_choi.py` còn ràng thêm một lần nữa bằng phép so
# với chính các hàm ấy.
_VI_DU_DAU_CHE: tuple[str, ...] = (
    dau_che("cause"),
    dau_che_owner(None),
    dau_che_owner(_NHOM_VI_DU),
    dau_che_truong(_TRUONG_VI_DU, MASK_REASON_L2_ONLY),
    dau_che_lan_can_khong_khoa(),
)
DANH_SACH_DAU_CHE: str = ", ".join(_VI_DU_DAU_CHE)

PROMPT_TRA_LOI: str = f"""{DAU_PROMPT_TRA_LOI} Đọc phần ngữ cảnh rồi trả lời câu hỏi ở cuối, đầu ra là json.

Ngữ cảnh là ba bảng CSV do hệ truy hồi dựng: thực thể, quan hệ và đoạn văn bản nguồn.

Luật:
- Chỉ dùng thông tin có trong ngữ cảnh. Không thêm tri thức chung, không suy đoán, không bịa tên hệ thống, số hiệu hay mốc thời gian.
- Ngữ cảnh không chứa đáp án thì đặt "{KHOA_KHONG_CO_DAP_AN}" là true và để "{KHOA_CAU_TRA_LOI}" là chuỗi rỗng. Không tự soạn lời từ chối, không giải thích vì sao thiếu, không gợi ý hỏi ai.
- Ngữ cảnh chứa đáp án thì đặt "{KHOA_KHONG_CO_DAP_AN}" là false và viết câu trả lời tiếng Việt vào "{KHOA_CAU_TRA_LOI}", ngắn gọn và bám sát ngữ cảnh.
- Trong ngữ cảnh có thể có những chuỗi dạng [tên:lý_do], ví dụ: {DANH_SACH_DAU_CHE}. Đó là dấu che, đứng ở chỗ giá trị gốc đã bị thay, không phải nội dung. Không đoán giá trị gốc. Khi câu trả lời cần nhắc tới phần đó thì **chép nguyên dấu che vào đúng chỗ trong "{KHOA_CAU_TRA_LOI}"**, giữ nguyên từng ký tự, không bỏ trống, không viết lại thành lời, không ghép thêm chữ nào vào trong dấu.
- Không tự bình luận trong "{KHOA_CAU_TRA_LOI}" về quyền, về phân quyền, về việc bị chặn hay bị giới hạn, về việc ngữ cảnh thiếu dữ liệu, hay về chính ngữ cảnh này: không viết bằng lời của mình những câu như "phần này bị hạn chế" hay "không có dữ liệu về". Một dấu che chép nguyên như luật trên không phải một lời bình. Chỉ viết nội dung trả lời câu hỏi.

Đầu ra là một object json duy nhất mang đúng hai khóa "{KHOA_KHONG_CO_DAP_AN}" (true hoặc false) và "{KHOA_CAU_TRA_LOI}" (chuỗi), không có văn bản nào khác ngoài json.

Ví dụ đầu ra:
{VI_DU_DAU_RA}

Ngữ cảnh:
{_CHO_NGU_CANH}

Câu hỏi:
{_CHO_CAU_HOI}
"""

# Một lượt thay duy nhất cho cả hai chỗ chèn. Hai lượt `replace` nối nhau hở cả
# **hai** chiều, không chỉ chiều đã ghi ở bản đầu: thay ngữ cảnh trước thì một
# `<<CAU_HOI>>` nằm trong chính tài liệu đã nạp sẽ được lượt sau điền câu hỏi
# vào, tức văn bản tài liệu lái được chỗ câu hỏi rơi vào prompt. `re.sub` với
# một hàm thay thế **không quét lại** phần vừa chèn, nên cả hai chiều đóng bằng
# một cơ chế thay vì bằng một thứ tự khéo.
_TACH_CHO_CHEN = re.compile(
    "|".join(re.escape(c) for c in (_CHO_NGU_CANH, _CHO_CAU_HOI))
)


def dung_prompt(cau_hoi: str, ngu_canh: str) -> str:
    """Prompt của một lượt trả lời: **một lượt thay** cho cả hai chỗ chèn.

    Hai lượt `replace` nối nhau hở về cả hai chiều, và bản đầu của story chỉ
    nhìn thấy một. Chiều đã thấy: một câu hỏi chứa nguyên văn `<<NGU_CANH>>`.
    Chiều chưa thấy, và là chiều nguy hơn: một `<<CAU_HOI>>` nằm **trong ngữ
    cảnh** - tức trong một tài liệu đã nạp - được lượt sau điền câu hỏi vào, nên
    nội dung tài liệu lái được chỗ câu hỏi rơi vào prompt.

    `re.sub` với một hàm thay thế quét prompt **đúng một lần** và không quét lại
    phần vừa chèn, nên cả hai chiều đóng bằng một cơ chế chứ không bằng một thứ
    tự khéo. Không dùng `str.format` vì ngữ cảnh là ba bảng CSV có dấu ngoặc
    nhọn.
    """
    thay = {_CHO_NGU_CANH: ngu_canh, _CHO_CAU_HOI: cau_hoi}
    return _TACH_CHO_CHEN.sub(lambda m: thay[m.group(0)], PROMPT_TRA_LOI)


# --- Ngữ cảnh rỗng -------------------------------------------------------------

# Ba nhãn và hai dấu rào của khung mà `_build_query_context` trả về
# (`operate.py:719-731`). Ba nhãn là thứ chia khung thành ba khúc, và chúng là
# cái neo đáng tin hơn dấu rào: dấu rào **xuất hiện lại được trong nội dung**
# (một tài liệu `.md` của corpus có khối lệnh có rào, và nội dung ấy đi thẳng
# vào khối Sources), còn ba nhãn thì không.
_NHAN_KHUNG: tuple[str, ...] = (
    "-----Entities-----",
    "-----Relationships-----",
    "-----Sources-----",
)
_MO_KHOI: str = "```csv"
_DONG_KHOI: str = "```"


def ngu_canh_rong(chuoi) -> bool:
    """Ba khối ```csv``` của khung ngữ cảnh đều rỗng?

    `_build_query_context` **không bao giờ** trả `None`: đường ra duy nhất của
    nó là một f-string ba nhãn ba khối (`operate.py:719-731`), nên nhánh
    `context is None` của `kg_query` (`:598-599`) là code chết. Ngữ cảnh rỗng
    biểu hiện ở tầng dưới - `_get_node_data:743-745` và `_get_edge_data:938-940`
    trả `"", "", ""` khi kho vector không cho kết quả nào - tức thành ba khối
    chỉ có khoảng trắng bên trong một cái khung vẫn còn nguyên. Đó là toàn bộ
    lý do hàm này đọc chuỗi chứ không so với `None`.

    Đây cũng là chỗ ca L0 chặn sạch đi ra: bộ lọc quyền chạy *trong* hai hàm
    trên, nên một vai không có khóa nào nhận đúng cái khung rỗng ấy. Không có
    nhánh nhận diện L0 riêng, và đó là cố ý (FR-16: L0 vô hình nên tầng ứng
    dụng không có tín hiệu "đã chặn thứ gì đó").

    Chuỗi không mang khối ```csv``` nào thì hàm trả `False`, tức để lời gọi LLM
    chạy. Nó là ca "khung của vendor đổi hình dạng", và chọn `False` vì hai bên
    đều an toàn về mặt rò rỉ - nội dung đã che ở adapter - trong khi `True` biến
    một bản upstream mới thành một hệ từ chối mọi câu hỏi mà không ai thấy.
    """
    if not isinstance(chuoi, str) or not chuoi.strip():
        return True
    khoi = _cac_khoi_csv(chuoi)
    if not khoi:
        return False
    return all(not k.strip() for k in khoi)


def _cac_khoi_csv(chuoi: str) -> list[str]:
    """Nội dung ba khối ```csv ... ``` của khung, hoặc rỗng nếu không phải khung."""
    return [chuoi[dau:cuoi] for dau, cuoi in _vi_tri_khoi(chuoi)]


def _vi_tri_khoi(chuoi: str) -> list[tuple[int, int]]:
    """Vị trí (đầu, cuối) của thân ba khối ```csv ... ``` trong chuỗi, hoặc rỗng nếu không phải khung.

    Tách khỏi `_cac_khoi_csv` ở story 5.3 vì `hop_nhat_ngu_canh` phải **thay**
    đúng thân khối Relationships tại chỗ và giữ nguyên văn mọi byte khác của
    khung; một hàm chỉ trả nội dung thì không nói được thân ấy nằm ở đâu.

    Neo vào **ba nhãn** chứ không vào dấu rào, và đó là chỗ bản đầu của story
    sai. Lý lẽ cũ ("quét chuỗi để tránh chỗ regex đọc sai khi mô tả chứa
    backtick") không đứng: một regex non-greedy cho ra đúng cùng danh sách. Mối
    nguy thật khác hẳn - **nội dung của khối Sources chứa được một dấu rào**,
    vì `text_units_context` mang nguyên văn chunk và corpus `.md` có khối lệnh
    có rào. Khi đó phép ghép rào-mở-với-rào-đóng-gần-nhất cắt khối Sources ở
    ngay dấu rào bên trong, và nếu phần trước nó chỉ có khoảng trắng thì cả
    khung bị đọc thành rỗng - tức một lượt có dữ liệu bị từ chối, và bị đếm vào
    một cột của Đo 2.

    Cách đúng: chia khung theo ba nhãn trước, rồi trong mỗi khúc lấy từ dấu rào
    mở **đầu tiên** tới dấu rào **cuối cùng**. Rào cuối của một khúc luôn là rào
    đóng của chính khối ấy, vì nhãn kế tiếp mở khúc sau.

    Thiếu một nhãn, hay ba nhãn sai thứ tự, thì trả danh sách rỗng: đó là ca
    "chuỗi này không phải khung của vendor", và `ngu_canh_rong` xử nó bằng cách
    để lời gọi LLM chạy.
    """
    vi_tri = [chuoi.find(nhan) for nhan in _NHAN_KHUNG]
    if any(v < 0 for v in vi_tri) or vi_tri != sorted(vi_tri):
        return []
    ra: list[tuple[int, int]] = []
    for i, (nhan, dau_nhan) in enumerate(zip(_NHAN_KHUNG, vi_tri)):
        het = vi_tri[i + 1] if i + 1 < len(vi_tri) else len(chuoi)
        khuc_dau = dau_nhan + len(nhan)
        mo = chuoi.find(_MO_KHOI, khuc_dau, het)
        if mo < 0:
            return []
        than_dau = mo + len(_MO_KHOI)
        dong = chuoi.rfind(_DONG_KHOI, than_dau, het)
        ra.append((than_dau, het if dong < 0 else dong))
    return ra


# --- Id hyperedge trong ngữ cảnh (story 3.4) -----------------------------------

# Vị trí và tên cột của khối Relationships trong khung ba nhãn. Cả hai nhánh
# của vendor dựng bảng với đúng header này (`operate.py:788` local, `:987`
# global), và cột `hyperedge` mang **id node hyperedge**: nhánh global đổ
# `k["hyperedge_name"]` (payload point Qdrant, `:953`), nhánh local đổ
# `"description": k[1]` (`:906`) rồi `e["description"]` vào cột (`:794`), tức
# id lân cận mà `get_node_edges(entity)` trả về. Từ story 2.4 id ấy là `he-` +
# 24 hex, không mang chữ nào của slot. `tests/test_trich_dan.py` grep hai mốc
# `:906` và `:794` để chúng không trôi theo một bản upstream mới.
_KHOI_RELATIONSHIPS: int = 1
_COT_HYPEREDGE: str = "hyperedge"
_COT_ID: str = "id"
# Header của khối Relationships mà cả hai nhánh vendor dựng (`operate.py:788`,
# `:987`). Chỉ dùng khi khối **rỗng** (kho vector không cho kết quả nào) mà
# đường phụ vẫn có dòng để chèn - khi đó không có header nào trong khung để
# đọc lại, và một dòng phụ không header là một bảng mà LLM không đọc được.
_HEADER_RELATIONSHIPS: tuple[str, ...] = (_COT_ID, _COT_HYPEREDGE, "related_entities")


def _doc_dong(dong_tho: str) -> list[str]:
    """Một dòng CSV -> danh sách ô đã cắt khoảng trắng (đọc từng dòng, xem `id_hyperedge_trong`)."""
    hang = next(csv.reader(io.StringIO(dong_tho)), [])
    return [o.strip() for o in hang]


def _id_chuan_hoac_none(o: str) -> str | None:
    try:
        return normalize_id(o)
    except ValueError:
        return None


def id_hyperedge_trong(ngu_canh) -> tuple[str, ...]:
    """Id hyperedge ở cột `hyperedge` của khối Relationships, khử trùng, giữ thứ tự.

    Đây là cột **duy nhất** khớp đúng với thứ LLM sắp đọc, và là lý do citation
    không thu thập ở adapter (Design Notes spec 3.4): nhánh local lấy hyperedge
    qua `get_node_edges`, không qua kho vector, và cả hai nhánh còn bị
    `truncate_list_by_token_size` cắt *sau* adapter - "adapter đã trả" khác
    "LLM đã thấy".

    Id đọc ra chỉ là **khóa tra**, không phải sự thật: khóa quyền, mức, vai và
    nhóm đều đến từ adapter graph dưới ngữ cảnh vai. Hàm vì thế đọc dễ dãi và
    để cửa quyền phía sau xử: một id không tồn tại thành `TrichDanNgoaiQuyen`
    chứ không thành một citation.

    Hai hình dạng của khối, cùng một bộ đọc. Nhánh đơn (`local`/`global`) là
    CSV chuẩn của `csv.writer`. Nhánh `hybrid` đi qua
    `utils.process_combine_contexts:296-330`, thứ **viết lại** bảng: header
    ghép bằng `",\\t"`, mỗi dòng là `f"{{i}},\\t{{item}}"` với `item` là các
    cột sau `id` ghép bằng dấu phẩy trần, không quote lại. `csv.reader` đọc
    được cả hai vì cột `hyperedge` đứng ngay sau `id` và id `he-…` không mang
    dấu phẩy; phần thừa là một tab đầu ô, cắt bằng `strip`. Một id mang dấu
    phẩy sẽ bị cắt đôi ở dạng hybrid - và khi đó nó không tra trúng gì, tức
    5xx chứ không một citation sai.

    Đọc **từng dòng một** chứ không đọc cả khối bằng một `csv.reader`: ở dạng
    hybrid dấu nháy kép không còn được quote lại, nên một tên entity mở đầu
    bằng `"` ở cột `related_entities` sẽ làm bộ đọc cả khối nuốt các dòng kế
    cho tới dấu nháy đóng - tức mất citation **lặng lẽ**. Đọc từng dòng thì ô
    đó hỏng trong phạm vi một dòng, còn cột `hyperedge` đứng trước nó vẫn
    nguyên. Giá phải trả là một giá trị có xuống dòng bên trong ô sẽ đọc sai,
    nhưng id entity đi qua `core.facts.chuan_hoa_gia_tri` (gộp khoảng trắng)
    nên không có xuống dòng nào, và sai ở đây là 5xx chứ không phải một
    citation thiếu.

    Id trả về **đã qua `normalize_id`** và khử trùng *sau* chuẩn hóa, đúng
    khóa mà `Neo4jACLGraphStorage.trich_dan_cua` dùng cho dict trả về: chuẩn
    hóa một lần ở đây thì hai bên không lệch nhau vì một dấu cách hay một cặp
    nháy kép bao quanh. Ô mà `normalize_id` từ chối (rỗng sau chuẩn hóa, ví dụ
    chỉ toàn dấu nháy) là `TrichDanNgoaiQuyen`: nó vẫn là "ngữ cảnh mang một
    thứ ở cột `hyperedge` mà không tra được", và lên tới HTTP phải là một 500
    mang mã chứ không một `ValueError` không tên.

    Chuỗi không phải khung vendor (thiếu nhãn, sai thứ tự, thiếu header hay
    thiếu cột) cho tuple rỗng: lượt vẫn trả lời, `citations: []`.
    """
    if not isinstance(ngu_canh, str):
        return ()
    khoi = _cac_khoi_csv(ngu_canh)
    if len(khoi) <= _KHOI_RELATIONSHIPS:
        return ()
    dong: list[list[str]] = []
    for dong_tho in khoi[_KHOI_RELATIONSHIPS].strip().splitlines():
        if not dong_tho.strip():
            continue
        hang = _doc_dong(dong_tho)
        if hang:
            dong.append(hang)
    if not dong or _COT_HYPEREDGE not in dong[0]:
        return ()
    cot = dong[0].index(_COT_HYPEREDGE)
    ra: list[str] = []
    for hang in dong[1:]:
        if len(hang) <= cot or not hang[cot]:
            continue
        try:
            chuan = normalize_id(hang[cot])
        except ValueError as loi:
            raise TrichDanNgoaiQuyen(
                "ngữ cảnh mang một ô ở cột `hyperedge` không chuẩn hóa được"
                " thành id: không tra được citation cho lượt này"
            ) from loi
        if chuan not in ra:
            ra.append(chuan)
    return tuple(ra)


# --- Hợp nhất đường phụ theo grant (story 5.3) ---------------------------------


def hop_nhat_ngu_canh(ngu_canh, hang_phu) -> str:
    """Ghép các dòng của đường phụ vào khối Relationships, khử trùng theo id hyperedge.

    `hang_phu` là dãy dòng cùng hình dạng với dòng của vendor
    (`[id, hyperedge, related_entities]`, `operate.py:987-997`), mỗi dòng cho
    một hyperedge được cấp mà `get_node_edges` còn trả cạnh. Ba việc, theo thứ
    tự: **bỏ** mọi dòng của khối có cột `hyperedge` trùng một id được cấp (bản
    đã che của đường chính nhường chỗ cho bản đầy đủ), **nối** các dòng phụ
    bằng CSV chuẩn (`csv.writer`, cột `id` đánh tiếp sau số lớn nhất còn lại),
    và **giữ nguyên văn** mọi dòng khác cùng hai khối kia - hàm chỉ thay đúng
    thân khối Relationships mà `_vi_tri_khoi` chỉ ra.

    Cả hai hình dạng của khối đi qua được, cùng lý do với `id_hyperedge_trong`:
    dạng CSV chuẩn của nhánh đơn và dạng hybrid của `process_combine_contexts`
    (header ghép `",\t"`, dòng không quote lại). Đọc **từng dòng** để một ô
    hỏng chỉ hỏng trong phạm vi dòng ấy; dòng không đọc được id thì giữ nguyên
    chứ không bỏ. Khối rỗng (kho vector không cho kết quả) nhận header của
    vendor rồi mới nhận dòng phụ - đó là ca "câu hỏi không truy hồi được
    hyperedge được cấp", và nó phải cho một lượt **không rỗng**. Chuỗi không
    phải khung vendor hay `hang_phu` rỗng: trả nguyên chuỗi vào, không đổi một
    byte. Khối có nội dung mà header (sau strip, cùng thứ tự) khác đúng
    `_HEADER_RELATIONSHIPS` - thiếu cột, thêm cột, đổi tên - cũng trả nguyên
    nhưng kèm một dòng WARNING: đó là dấu hiệu vendor đổi bảng, không được
    thành một đường phụ ngừng chèn mà không ai thấy.

    Hàm thuần, không hỏi quyền: dòng phụ là thứ adapter graph đã lọc và đã che
    dưới ngữ cảnh vai (`EngineACL.ngu_canh_hoi_dap`), ở đây chỉ còn ghép.
    """
    hang_phu = [[str(o) for o in h] for h in hang_phu]
    if not isinstance(ngu_canh, str) or not hang_phu:
        return ngu_canh
    vi_tri = _vi_tri_khoi(ngu_canh)
    if len(vi_tri) <= _KHOI_RELATIONSHIPS:
        return ngu_canh
    dau, cuoi = vi_tri[_KHOI_RELATIONSHIPS]
    dong_tho = [d for d in ngu_canh[dau:cuoi].splitlines() if d.strip()]
    if dong_tho:
        header = _doc_dong(dong_tho[0])
        if tuple(header) != _HEADER_RELATIONSHIPS:
            # Không lặng lẽ: một bản vendor đổi header là đường phụ ngừng chèn
            # mà không ai thấy, và lượt vẫn trả lời như thường.
            logger.warning(
                "hop_nhat_ngu_canh: header khối Relationships %r khác %r, giữ nguyên ngữ cảnh",
                header, list(_HEADER_RELATIONSHIPS),
            )
            return ngu_canh
        dong_header, dong_cu = dong_tho[0], dong_tho[1:]
    else:
        header = list(_HEADER_RELATIONSHIPS)
        dong_header, dong_cu = _dong_csv(header), []
    if any(len(h) != len(header) for h in hang_phu):
        raise ValueError(
            f"dòng phụ phải có đúng {len(header)} cột như header {header}"
        )
    cot_he, cot_id = header.index(_COT_HYPEREDGE), header.index(_COT_ID)
    id_cap = {_id_chuan_hoac_none(h[cot_he]) for h in hang_phu} - {None}
    giu: list[str] = []
    so_cu: list[int] = []
    for d in dong_cu:
        hang = _doc_dong(d)
        if len(hang) > cot_he and _id_chuan_hoac_none(hang[cot_he]) in id_cap:
            continue
        giu.append(d)
        if len(hang) > cot_id and hang[cot_id].isdecimal():
            so_cu.append(int(hang[cot_id]))
    ke = max(so_cu) + 1 if so_cu else 0
    moi = []
    for i, h in enumerate(hang_phu):
        h[cot_id] = str(ke + i)
        moi.append(_dong_csv(h))
    than_moi = "\n" + "\n".join([dong_header, *giu, *moi]) + "\n"
    return ngu_canh[:dau] + than_moi + ngu_canh[cuoi:]


def _dong_csv(hang) -> str:
    """Một dòng CSV chuẩn từ danh sách ô, không ký tự xuống dòng ở cuối."""
    ra = io.StringIO()
    csv.writer(ra, lineterminator="").writerow(hang)
    return ra.getvalue()


# --- Đọc đầu ra LLM ------------------------------------------------------------


def _bo_rao_ma(text: str) -> str:
    """Gỡ một lớp rào ```json ... ``` nếu có; JSON mode sạch thì không đổi gì.

    Cùng luật với `core.facts._bo_rao_ma`. Chép sáu dòng chứ không mở một hàm
    riêng tư của `core/` ra: `core/` là tầng phải giải thích được từng dòng
    trước hội đồng, và nới một tên riêng thành công khai để một adapter đỡ phải
    viết sáu dòng là một cái giá sai chỗ.
    """
    gon = text.strip()
    if gon.startswith("```"):
        dong = gon.split("\n")
        if len(dong) >= 2 and dong[-1].strip() == "```":
            gon = "\n".join(dong[1:-1]).strip()
    return gon


def doc_dau_ra(chuoi) -> KetQuaTraLoi:
    """Đầu ra LLM -> `KetQuaTraLoi`, hoặc dội `DauRaTraLoiKhongDoc`.

    Bốn ca dội, và ca thứ tư là ca đáng nói: `khong_co_dap_an` bằng `false` mà
    `cau_tra_loi` rỗng là một cờ **tự mâu thuẫn**. Đoán hộ nó - coi như một lượt
    từ chối - là dựng nhánh từ chối thứ tư trên một đầu ra hỏng, tức lại trộn
    lỗi hệ thống vào phép đo. Nên nó là 5xx như ba ca kia.

    `khong_co_dap_an` phải là **bool thật**: `isinstance(1, bool)` là `False`
    trong Python, nên một `1` hay một chuỗi `"true"` bị từ chối ở đây thay vì
    lặng lẽ thành `True` qua một phép truthy.

    **Ca gương của ca thứ tư được xử khác, và đó là một bất đối xứng có chủ
    đích.** `khong_co_dap_an: true` kèm `cau_tra_loi` **không rỗng** cũng là một
    cờ tự mâu thuẫn, nhưng nó đi qua: hàm nhận cờ và bỏ văn bản đi, nên lượt ấy
    thành một lượt từ chối. Hai ca xử khác nhau vì hai hướng hỏng khác nhau.
    Cờ bật kèm văn bản: hai cách đọc đều dẫn tới một hành vi *an toàn* - từ chối
    - nên chọn cái an toàn và ném phần văn bản đi là đủ, không cần làm hỏng cả
    một lượt hỏi. Cờ tắt kèm văn bản rỗng: cả hai cách đọc đều **không** an toàn
    - hoặc trả một `answer` rỗng, hoặc suy diễn thành một lượt từ chối và bơm
    một cột của Đo 2 bằng một đầu ra hỏng - nên nó phải là 5xx.
    """
    if not isinstance(chuoi, str):
        raise DauRaTraLoiKhongDoc(
            f"đầu ra LLM phải là chuỗi, nhận được {type(chuoi).__name__}"
        )
    try:
        raw = json.loads(_bo_rao_ma(chuoi))
    except (json.JSONDecodeError, RecursionError):
        raise DauRaTraLoiKhongDoc("đầu ra LLM không phải json") from None
    if not isinstance(raw, dict):
        raise DauRaTraLoiKhongDoc(
            f"đầu ra LLM phải là một object json, nhận được {type(raw).__name__}"
        )
    thieu = [k for k in (KHOA_KHONG_CO_DAP_AN, KHOA_CAU_TRA_LOI) if k not in raw]
    if thieu:
        raise DauRaTraLoiKhongDoc(f"đầu ra LLM thiếu khóa {thieu}")
    co = raw[KHOA_KHONG_CO_DAP_AN]
    if not isinstance(co, bool):
        raise DauRaTraLoiKhongDoc(
            f"{KHOA_KHONG_CO_DAP_AN} phải là true hoặc false, nhận được {co!r}"
        )
    cau = raw[KHOA_CAU_TRA_LOI]
    if not isinstance(cau, str):
        raise DauRaTraLoiKhongDoc(
            f"{KHOA_CAU_TRA_LOI} phải là chuỗi, nhận được {type(cau).__name__}"
        )
    if not co and not cau.strip():
        raise DauRaTraLoiKhongDoc(
            f"{KHOA_KHONG_CO_DAP_AN} là false mà {KHOA_CAU_TRA_LOI} rỗng:"
            " cờ tự mâu thuẫn, không suy diễn thành một lượt từ chối"
        )
    return KetQuaTraLoi(khong_co_dap_an=co, cau_tra_loi=cau)


__all__ = [
    "CAU_HONG_UPSTREAM",
    "DANH_SACH_DAU_CHE",
    "DAU_PROMPT_TRA_LOI",
    "KHOA_CAU_TRA_LOI",
    "KHOA_KHONG_CO_DAP_AN",
    "LY_DO_CO_NO_ANSWER",
    "LY_DO_NGU_CANH_RONG",
    "LY_DO_TU_CHOI",
    "LY_DO_TU_KHOA_RONG",
    "PROMPT_TRA_LOI",
    "THAM_SO_LLM",
    "VI_DU_DAU_RA",
    "DauRaTraLoiKhongDoc",
    "KetQuaHoiDap",
    "KetQuaTraLoi",
    "NguCanhTruyHoiLa",
    "doc_dau_ra",
    "dung_prompt",
    "hop_nhat_ngu_canh",
    "id_hyperedge_trong",
    "ngu_canh_rong",
]
