"""Từ chối hai tầng không phân biệt được (story 3.5, FR-16).

Đặc tả viết trước cơ chế (FR-27): mọi hàng I/O Matrix của story nằm ở đây, cộng
bốn mệnh đề mà không hàng nào của bảng phát biểu được một mình.

- **Ba lý do, một thân response, bằng nhau từng byte.** Phép so chạy trên
  `response.content` chứ không trên từng field: một phép so field bỏ lọt thứ tự
  khóa, khoảng trắng của serializer, và cả một khóa thứ sáu nếu nó bằng nhau ở
  cả ba lượt. Byte là thứ người dò đọc.
- **Lý do chỉ có trong audit.** Ba chuỗi lý do không xuất hiện trong thân
  response của bất kỳ lượt nào, và mỗi lượt từ chối sinh đúng một hàng `refusal`
  mang lý do khác nhau.
- **Ngữ cảnh rỗng không tốn lời gọi LLM thứ hai.** Đo trên engine thật với ba
  adapter thật và một vai không có khóa nào: đúng một lời gọi (trích từ khóa).
- **Lỗi hệ thống khác từ chối.** Đầu ra LLM không đọc được ra 502 mang mã ổn
  định, thân lỗi không có khóa `refused`, và **không** hàng `refusal` nào được
  ghi - nếu có thì hai cột của Đo 2 (PRD 5.2) đếm cả lỗi nội bộ.

Ba lớp, ba loại chứng cứ khác nhau. Lớp hàm thuần (`adapters/tra_loi.py`) chấm
luật đọc khung ngữ cảnh, luật đọc đầu ra LLM, và **chính prompt**. Lớp engine
chấm ba nhánh, số lời gọi LLM và tham số của lời gọi. Lớp HTTP chấm envelope và
audit. Không lớp nào assert trên **văn bản** câu trả lời của LLM (chốt brief §6).

Hai ca của lớp đầu chấm prompt như một mặt tấn công chứ như một chuỗi văn bản,
vì bản đầu của story để hai lỗ ở đúng đó. Một, prompt mô tả **sai định dạng dấu
che** nên nó không dặn được gì về `[owner:<tên nhóm thật>]`, tức tên nhóm phụ
trách chép ra `answer` được; ví dụ dấu che nay dựng từ chính hàm của
`core/masking.py` và có test ràng hai bên. Hai, prompt **nói với model** rằng
ngữ cảnh đã lọc theo quyền, mà `cau_tra_loi` là văn bản tự do - phép so byte
của story chỉ phủ lượt **từ chối**, nên một câu "phần này bạn không có quyền
xem" trong một lượt *trả lời* không ca nào khác bắt được.
"""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.llm_wrapper import LLMStreamNotSupported
from adapters.tra_loi import (
    CAU_HONG_UPSTREAM,
    DANH_SACH_DAU_CHE,
    DAU_PROMPT_TRA_LOI,
    KHOA_CAU_TRA_LOI,
    KHOA_KHONG_CO_DAP_AN,
    LY_DO_CO_NO_ANSWER,
    LY_DO_NGU_CANH_RONG,
    LY_DO_TU_CHOI,
    LY_DO_TU_KHOA_RONG,
    PROMPT_TRA_LOI,
    THAM_SO_LLM,
    DauRaTraLoiKhongDoc,
    KetQuaHoiDap,
    NguCanhTruyHoiLa,
    doc_dau_ra,
    dung_prompt,
    ngu_canh_rong,
)
from api import main as api_main
from api.hoi_dap import (
    CT_LY_DO,
    DANH_MUC_LY_DO,
    KHOA_ENVELOPE,
    KHOA_META,
    MA_DAU_RA_LLM_KHONG_DOC_DUOC,
    TEMPLATE_TU_CHOI,
)
from adapters.neo4j import Neo4jUnavailable
from adapters.qdrant import QdrantIndexMissing
from adapters.thu_lai import ChanNhipQuaLau
from api.hoi_dap import MA_KHO_KHONG_SAN_SANG, MA_LLM_LOI, MA_LLM_QUA_HAN
from api.xac_thuc import BIEN_KHOA_KY
from core.audit import EVENT_QUERY, EVENT_REFUSAL, TIER_OBSERVATION
from core.masking import (
    MASK_REASON_L2_ONLY,
    MASK_REASON_NO_KEY,
    MASK_REASON_OWNER,
    MASK_REASON_POLICY,
    dau_che,
    dau_che_lan_can_khong_khoa,
    dau_che_owner,
)
from core.permission import KIND_USER, PermissionContext, use_context
from tests.test_xac_thuc import (
    KHOA_TEST,
    MAT_KHAU,
    TEN_GO,
    AuditGia,
    EngineGia,
    KhoGia,
    _dong,
)

GOC = Path(__file__).resolve().parent.parent
CAU_HOI = "App01 trả lỗi 502 thì xử lý thế nào"


# --- Lớp 1: hàm thuần của `adapters/tra_loi.py` --------------------------------


def khung_ngu_canh(entities: str = "", relations: str = "", sources: str = "") -> str:
    """Khung mà `_build_query_context` trả về, chép đúng f-string `operate.py:719-731`.

    Bản chép này có một test canh ngay dưới: ba nhãn và dấu rào phải còn nguyên
    văn trong thân hàm vendor, nếu không thì `ngu_canh_rong` đang đọc một khung
    không còn tồn tại.
    """
    return f"""
-----Entities-----
```csv
{entities}
```
-----Relationships-----
```csv
{relations}
```
-----Sources-----
```csv
{sources}
```
"""


def _than_ham_vendor(ten: str) -> str:
    nguon = (GOC / "vendor" / "hypergraphrag" / "operate.py").read_text(encoding="utf-8")
    dau = nguon.index(f"async def {ten}(")
    ke = nguon.find("\nasync def ", dau + 1)
    return nguon[dau : ke if ke > 0 else len(nguon)]


def test_khung_ngu_canh_cua_bo_test_van_la_khung_cua_vendor():
    """Bản chép khung trong file này phải khớp `_build_query_context` thật.

    `ngu_canh_rong` đứng trên một giả định về hình dạng chuỗi của `vendor/`, và
    `vendor/` thì không sửa được nhưng **nâng cấp được**. Một bản upstream mới
    đổi nhãn hay đổi dấu rào mà bộ test không thấy là một nhánh từ chối lặng lẽ
    ngừng nhận diện được ngữ cảnh rỗng - đúng loại hỏng không ai phát hiện, vì
    triệu chứng của nó là hệ *trả lời* thay vì *từ chối*.
    """
    than = _than_ham_vendor("_build_query_context")
    for dau in ("-----Entities-----", "-----Relationships-----", "-----Sources-----", "```csv"):
        assert dau in than, f"khung ngữ cảnh của vendor không còn {dau!r}"
    # Và đường ra duy nhất của nó vẫn là f-string ấy: không một `return None` nào,
    # tức nhánh `context is None` của `kg_query` vẫn là code chết.
    assert "return None" not in than


def test_ngu_canh_rong_tren_khung_that_ba_khoi_deu_rong():
    """Hàng "Ngữ cảnh rỗng" của I/O Matrix, ở mức hàm thuần.

    `_get_node_data:743-745` và `_get_edge_data:938-940` trả `"", "", ""` khi kho
    vector không cho kết quả nào, nên ngữ cảnh rỗng là **ba khối trắng trong một
    cái khung còn nguyên**, không phải một chuỗi rỗng và tuyệt đối không phải
    `None`.
    """
    assert ngu_canh_rong(khung_ngu_canh()) is True
    assert ngu_canh_rong(khung_ngu_canh("\n \n", "  ", "\t")) is True
    assert ngu_canh_rong("") is True
    assert ngu_canh_rong("   \n ") is True
    assert ngu_canh_rong(None) is True


@pytest.mark.parametrize(
    "khoi",
    [("id,entity\n1,App01", "", ""), ("", "id,he\n1,x", ""), ("", "", "id,content\n1,x")],
    ids=["entities", "relationships", "sources"],
)
def test_mot_khoi_co_noi_dung_la_ngu_canh_khong_rong(khoi):
    """Một khối có nội dung là đủ để **không** rỗng, kể cả hai khối kia trắng.

    Ba tham số chứ không một: `_build_query_context` gộp ba nguồn độc lập, và
    một phép kiểm chỉ nhìn khối đầu sẽ từ chối một lượt mà nhánh global có dữ
    liệu.
    """
    assert ngu_canh_rong(khung_ngu_canh(*khoi)) is False


@pytest.mark.parametrize(
    "sources, rong",
    [
        ("", True),
        ("id,content\n1,\"chay ```bash\nsystemctl restart nginx\n``` roi thoi\"", False),
        ("```bash\nsystemctl restart nginx\n```", False),
    ],
    ids=["rong", "co_rao_giua_noi_dung", "rao_ngay_dau_khoi"],
)
def test_noi_dung_khoi_sources_co_rao_ma_van_doc_dung(sources, rong):
    """Khối Sources chứa được một dấu rào, và phép tách phải chịu được điều đó.

    `text_units_context` mang **nguyên văn chunk**, và corpus `.md` có khối lệnh
    có rào. Phép ghép rào-mở-với-rào-đóng-gần-nhất của bản đầu cắt khối Sources
    ngay tại dấu rào bên trong; ca `rao_ngay_dau_khoi` là ca nó đọc cả khung
    thành rỗng, tức một lượt **có dữ liệu** bị từ chối và bị đếm vào một cột của
    Đo 2.

    Ba nhãn của khung là cái neo đúng: dấu rào xuất hiện lại được trong nội
    dung, ba nhãn thì không.
    """
    assert ngu_canh_rong(khung_ngu_canh("", "", sources)) is rong


def test_chuoi_khong_phai_khung_thi_khong_coi_la_rong():
    """Chuỗi không mang khối csv nào -> `False`, tức để lời gọi LLM chạy.

    Đây là ca "khung của vendor đổi hình dạng". Chọn `False` chứ không `True`:
    hai bên đều an toàn về rò rỉ (nội dung đã che ở adapter), nhưng `True` biến
    một bản upstream mới thành một hệ từ chối mọi câu hỏi mà không ai thấy.
    """
    assert ngu_canh_rong("một chuỗi bất kỳ") is False


def test_cau_hong_upstream_doc_tu_prompts_chu_khong_chep():
    """`CAU_HONG_UPSTREAM` là chính hằng của vendor, không một bản chép."""
    from hypergraphrag.prompt import PROMPTS

    assert CAU_HONG_UPSTREAM == PROMPTS["fail_response"]
    assert CAU_HONG_UPSTREAM is PROMPTS["fail_response"]


def test_ba_cho_song_cua_fail_response_deu_la_tu_khoa_rong():
    """Ba `return PROMPTS["fail_response"]` còn sống của `kg_query` là ca thiếu từ khóa.

    Sổ nợ 3.3 khai "năm chỗ"; điều tra của story 3.5 bác con số đó. `:568`
    (`json.JSONDecodeError`) không tới được vì khối `try` bao quanh nó chỉ chứa
    regex và tách chuỗi, còn `:599` (`context is None`) là code chết. Ca này giữ
    phát biểu ấy sống dưới dạng một phép đếm chứ không một câu văn.
    """
    than = _than_ham_vendor("kg_query")
    assert than.count('return PROMPTS["fail_response"]') == 5, (
        "số chỗ trả fail_response trong kg_query đổi; đọc lại ba chỗ sống"
    )
    # Ba trong năm nằm ngay sau một `logger.warning` về từ khóa rỗng. Đó là ba
    # chỗ sống, và cả ba là cùng một ca: LLM không trích được từ khóa.
    assert than.count("keywords is empty") == 3
    # Chỗ thứ tư nằm trong `except json.JSONDecodeError`, và khối `try` bao quanh
    # nó chỉ chứa regex cùng tách chuỗi - không lời gọi `json` nào - nên nhánh ấy
    # không tới được.
    assert "except json.JSONDecodeError" in than
    dau_try = than.index("    try:")
    assert "json." not in than[dau_try : than.index("except json.JSONDecodeError")]
    # Chỗ thứ năm là nhánh `context is None`, code chết vì `_build_query_context`
    # không có `return None` (ca ở trên).
    assert "if context is None:" in than


def test_doc_dau_ra_hai_hinh_dang_hop_le():
    """Hai ví dụ của Design Notes, đọc được thành `KetQuaTraLoi`."""
    co = doc_dau_ra(
        json.dumps(
            {KHOA_KHONG_CO_DAP_AN: False, KHOA_CAU_TRA_LOI: "App01 hết dung lượng ổ đĩa."},
            ensure_ascii=False,
        )
    )
    assert co.khong_co_dap_an is False and co.cau_tra_loi
    khong = doc_dau_ra(json.dumps({KHOA_KHONG_CO_DAP_AN: True, KHOA_CAU_TRA_LOI: ""}))
    assert khong.khong_co_dap_an is True and khong.cau_tra_loi == ""
    # Một lớp rào ```json của provider không phải một đầu ra hỏng.
    assert doc_dau_ra(
        '```json\n{"' + KHOA_KHONG_CO_DAP_AN + '": true, "' + KHOA_CAU_TRA_LOI + '": ""}\n```'
    ).khong_co_dap_an is True


@pytest.mark.parametrize(
    "tho",
    [
        "Xin lỗi, tôi không biết.",
        json.dumps({KHOA_KHONG_CO_DAP_AN: True}),
        json.dumps({KHOA_CAU_TRA_LOI: "x"}),
        json.dumps({KHOA_KHONG_CO_DAP_AN: 1, KHOA_CAU_TRA_LOI: "x"}),
        json.dumps({KHOA_KHONG_CO_DAP_AN: "true", KHOA_CAU_TRA_LOI: "x"}),
        json.dumps({KHOA_KHONG_CO_DAP_AN: False, KHOA_CAU_TRA_LOI: "   "}),
        json.dumps({KHOA_KHONG_CO_DAP_AN: False, KHOA_CAU_TRA_LOI: 7}),
        json.dumps([{KHOA_KHONG_CO_DAP_AN: True, KHOA_CAU_TRA_LOI: ""}]),
        None,
    ],
    ids=[
        "khong_phai_json",
        "thieu_cau_tra_loi",
        "thieu_co",
        "co_la_so_1",
        "co_la_chuoi",
        "false_ma_rong",
        "cau_tra_loi_khong_phai_chuoi",
        "json_la_mang",
        "khong_phai_chuoi",
    ],
)
def test_dau_ra_khong_doc_duoc_thi_doi_chu_khong_doan(tho):
    """Bốn ca của Design Notes, và ca cuối là ca đáng nói.

    `false` mà `cau_tra_loi` rỗng là một cờ **tự mâu thuẫn**. Đoán hộ nó thành
    một lượt từ chối là dựng nhánh từ chối thứ tư trên một đầu ra hỏng, tức trộn
    lỗi hệ thống vào đúng hai cột mà Đo 2 đếm.

    `1` bị từ chối chứ không thành `True`: `isinstance(1, bool)` là `False` trong
    Python, và một phép truthy ở đây là một cờ bật được bằng một con số.
    """
    with pytest.raises(DauRaTraLoiKhongDoc):
        doc_dau_ra(tho)


def test_ket_qua_hoi_dap_mang_dung_mot_trong_hai():
    """Bất biến XOR, kiểm lúc dựng: không có ca "có cả câu trả lời lẫn lý do".

    Đây là chỗ luật "không có nhánh thứ tư" sống dưới dạng cơ chế. Không có nó
    thì handler phải đoán trường nào thắng, và một lượt `refused: true` mang
    `answer` khác `None` là một envelope tự mâu thuẫn mà serializer vẫn nhận.
    """
    assert KetQuaHoiDap(cau_tra_loi="x").ly_do_tu_choi is None
    assert KetQuaHoiDap(ly_do_tu_choi=LY_DO_CO_NO_ANSWER).cau_tra_loi is None
    with pytest.raises(ValueError):
        KetQuaHoiDap()
    with pytest.raises(ValueError):
        KetQuaHoiDap(cau_tra_loi="x", ly_do_tu_choi=LY_DO_CO_NO_ANSWER)
    with pytest.raises(ValueError):
        KetQuaHoiDap(ly_do_tu_choi="mot_ly_do_la")
    with pytest.raises(TypeError):
        KetQuaHoiDap(cau_tra_loi=7)


def test_ket_qua_hoi_dap_tu_choi_cau_tra_loi_rong():
    """Bất biến XOR chưa đủ: một câu trả lời rỗng cũng phải bị chặn ở đây.

    `is not None` một mình cho `KetQuaHoiDap(cau_tra_loi="")` dựng được, và nó ra
    `answer: ""` kèm `refused: false` - một lượt trả lời rỗng mà người dùng đọc
    thành một lượt từ chối không có template. `doc_dau_ra` chặn ca đó từ phía
    LLM, nhưng bất biến mà handler dựa vào thì phải tự đứng được.
    """
    for rong in ("", "   ", "\n\t"):
        with pytest.raises(ValueError):
            KetQuaHoiDap(cau_tra_loi=rong)


def test_co_bat_kem_van_ban_thi_tu_choi_chu_khong_doi():
    """Ca gương của ca thứ tư, xử **khác** ca thứ tư, và đó là chủ đích.

    `khong_co_dap_an: true` kèm `cau_tra_loi` không rỗng cũng tự mâu thuẫn,
    nhưng nó đi qua: hàm nhận cờ và bỏ văn bản đi. Hai ca xử khác nhau vì hai
    hướng hỏng khác nhau. Cờ bật kèm văn bản: cả hai cách đọc dẫn tới một hành vi
    *an toàn* (từ chối), nên chọn cái an toàn thay vì làm hỏng cả một lượt hỏi.
    Cờ tắt kèm văn bản rỗng: cả hai cách đọc đều không an toàn - hoặc `answer`
    rỗng, hoặc bơm một cột của Đo 2 bằng một đầu ra hỏng - nên nó là 5xx.

    Ghim bằng test vì nó là một bất đối xứng, và một bất đối xứng không ghim là
    thứ vòng sau "sửa cho nhất quán".
    """
    kq = doc_dau_ra(
        json.dumps(
            {KHOA_KHONG_CO_DAP_AN: True, KHOA_CAU_TRA_LOI: "App01 hết ổ đĩa."},
            ensure_ascii=False,
        )
    )
    assert kq.khong_co_dap_an is True
    assert kq.cau_tra_loi == "App01 hết ổ đĩa."
    # Và văn bản ấy **không** đi tiếp: nơi gọi chỉ đọc cờ.
    assert KetQuaHoiDap(ly_do_tu_choi=LY_DO_CO_NO_ANSWER).cau_tra_loi is None


def test_ba_ly_do_la_mot_danh_muc_dong_va_mot_nguon():
    """`api/` và `adapters/` nói cùng ba chuỗi, và không có bản viết tay thứ hai."""
    assert set(DANH_MUC_LY_DO) == LY_DO_TU_CHOI == {
        "ngu_canh_rong",
        "co_no_answer",
        "tu_khoa_rong",
    }
    assert len(DANH_MUC_LY_DO) == 3


def test_prompt_tra_loi_doc_duoc_va_dung_json_mode():
    """Prompt là dữ liệu của phương pháp: hai khóa, chữ "json", hai chỗ chèn.

    `response_format` json_object của DeepSeek đòi chữ "json" xuất hiện trong
    prompt; thiếu nó là provider từ chối cả lời gọi, và đó là một lỗi chỉ hiện
    ra khi đã tiêu tiền.
    """
    assert PROMPT_TRA_LOI.startswith(DAU_PROMPT_TRA_LOI)
    assert KHOA_KHONG_CO_DAP_AN in PROMPT_TRA_LOI
    assert KHOA_CAU_TRA_LOI in PROMPT_TRA_LOI
    assert "json" in PROMPT_TRA_LOI.lower()
    assert THAM_SO_LLM["temperature"] == 0
    assert THAM_SO_LLM["response_format"] == {"type": "json_object"}
    assert isinstance(THAM_SO_LLM["max_tokens"], int) and THAM_SO_LLM["max_tokens"] > 0


def test_prompt_mo_ta_dau_che_dung_dinh_dang_that_cua_tang_che():
    """Ví dụ dấu che trong prompt **dựng từ chính hàm của `core/masking.py`**.

    Bản đầu của story viết tay `[tên_vai: che]` - sai cả ba chỗ: có khoảng trắng
    sau dấu hai chấm, lý do bằng tiếng Việt, và không có `no_key` lẫn
    `l2_only`. Hai hệ quả thật: model đọc `masked` như nội dung, và nó không được
    dặn gì về `[owner:<tên nhóm thật>]`, tức nó chép được tên nhóm phụ trách vào
    `cau_tra_loi` và nhóm rò ra qua `answer`.

    Ca này ràng hai bên lại: mỗi dấu che trong prompt phải **bằng** kết quả gọi
    đúng hàm sinh ra nó, và cả bốn lý do của `core/masking.py` phải có mặt. Đổi
    `MASK_REASON_*` hay đổi `dau_che_truong` mà prompt không đổi theo là đỏ ở
    đây.
    """
    for dau in (
        dau_che("cause"),
        dau_che_owner(None),
        dau_che_lan_can_khong_khoa(),
    ):
        assert dau in DANH_SACH_DAU_CHE, f"prompt thiếu ví dụ dấu che {dau}"
        assert dau in PROMPT_TRA_LOI
    for ly_do in (
        MASK_REASON_POLICY,
        MASK_REASON_OWNER,
        MASK_REASON_L2_ONLY,
        MASK_REASON_NO_KEY,
    ):
        assert f":{ly_do}]" in PROMPT_TRA_LOI, f"prompt không dạy lý do {ly_do!r}"
    # Ca `[owner:<tên nhóm>]` là ca nguy nhất, và nó phải có mặt dưới đúng hình
    # dạng của nó: một dấu che mà phần sau dấu hai chấm trông như nội dung.
    assert dau_che_owner("TenNhom") in PROMPT_TRA_LOI
    # Và bản mô tả sai của bản đầu không được sống lại.
    assert "[tên_vai: che]" not in PROMPT_TRA_LOI
    assert ": che]" not in PROMPT_TRA_LOI


def test_prompt_cam_chep_dau_che_va_cam_nhac_toi_quyen():
    """Hai luật mà prompt **phải** có, và một câu nó không được có.

    Luật một: cấm chép bất kỳ chuỗi dạng dấu che vào `cau_tra_loi`. Không có nó
    thì `[owner:DevOps]` đi thẳng ra `answer`.

    Luật hai: cấm nhắc tới quyền, hạn chế, hay việc thiếu dữ liệu. Đây là chỗ
    bản đầu hở: nó **nói với model** rằng ngữ cảnh đã lọc theo quyền của người
    hỏi, và `cau_tra_loi` là văn bản tự do, nên model viết được "phần này bạn
    không có quyền xem" - đúng phép phân biệt FR-16 dựng ra để bịt. Phép so byte
    của story chỉ phủ **lượt từ chối**, không phủ lượt trả lời, nên lỗ này không
    một ca nào khác bắt được.
    """
    assert f'không chép bất kỳ chuỗi dạng đó vào "{KHOA_CAU_TRA_LOI}"' in PROMPT_TRA_LOI
    assert "Không viết gì" in PROMPT_TRA_LOI and "về quyền" in PROMPT_TRA_LOI
    # Câu của bản đầu, và mọi biến thể dạy model rằng ngữ cảnh bị lọc theo quyền.
    for cam in (
        "đã được lọc theo quyền",
        "lọc theo quyền của người hỏi",
        "không được đọc",
        "không được phép",
    ):
        assert cam not in PROMPT_TRA_LOI, f"prompt còn dạy model về phân quyền: {cam!r}"


def test_dung_prompt_chen_nguyen_van_va_kin_ca_hai_chieu():
    """Ngữ cảnh và câu hỏi vào nguyên văn, và **một lượt thay duy nhất**.

    Hai lượt `replace` nối nhau hở về cả hai chiều. Chiều bản đầu đã thấy: một
    câu hỏi chứa `<<NGU_CANH>>`. Chiều bản đầu **chưa** thấy, và là chiều nguy
    hơn: một `<<CAU_HOI>>` nằm trong ngữ cảnh, tức trong một tài liệu đã nạp -
    văn bản tài liệu khi đó lái được chỗ câu hỏi rơi vào prompt. Ca này chấm cả
    hai bằng cách đếm số lần mỗi mảnh xuất hiện.
    """
    ngu_canh = khung_ngu_canh("id,entity\n1,{App01}")
    p = dung_prompt(CAU_HOI, ngu_canh)
    assert ngu_canh in p and CAU_HOI in p
    assert "<<NGU_CANH>>" not in p and "<<CAU_HOI>>" not in p

    # Chiều một: câu hỏi mang chỗ chèn ngữ cảnh.
    hiem = dung_prompt("<<NGU_CANH>> là gì", ngu_canh)
    assert hiem.count("-----Entities-----") == 1
    assert "<<NGU_CANH>> là gì" in hiem

    # Chiều hai: **ngữ cảnh** mang chỗ chèn câu hỏi. Câu hỏi phải xuất hiện đúng
    # một lần, ở đúng chỗ của nó.
    ban = khung_ngu_canh("id,entity\n1,<<CAU_HOI>>")
    hiem2 = dung_prompt(CAU_HOI, ban)
    assert hiem2.count(CAU_HOI) == 1
    assert "<<CAU_HOI>>" in hiem2, (
        "chỗ chèn nằm trong tài liệu phải đi ra nguyên văn, không được điền câu hỏi"
    )


# --- Lớp 2: ba nhánh của `EngineACL.hoi_dap` -----------------------------------


def _engine_m1(workspace_dir, khong_gian, policy):
    from tests.gia_lap_llm import phan_hoi_hai_luot
    from tests.ho_tro_m1 import cong_m1

    engine, qdrant, neo4j, llm = asyncio.run(cong_m1(workspace_dir, khong_gian, policy))
    llm.theo_prompt = phan_hoi_hai_luot()
    return engine, llm


def _vai_khong_khoa(khong_gian: str, policy) -> PermissionContext:
    """Ngữ cảnh của một vai mà bảng chính sách không cho **khóa nào**.

    Dựng thẳng `PermissionContext` chứ không qua `ngu_canh_cua`: bốn bảng chính
    sách đang có trong `config/` đều cho cả hai vai ít nhất một khóa chạm được
    fixture, nên một ca "chặn sạch" phải dựng bằng tay. Nó vẫn là một ngữ cảnh
    **vai** thật - `bypass_filter` là `False` - nên ba adapter lọc nó đúng như
    lọc một vai đến từ token.
    """
    return PermissionContext(
        kind=KIND_USER,
        space=khong_gian,
        role="tech_support",
        real_account="ts01",
        allowed_keys={
            "chunks": frozenset(),
            "entities": frozenset(),
            "hyperedges": frozenset(),
        },
        masked_slots={},
        grant_ids=(),
        policy_version=policy.policy_version,
    )


@pytest.mark.usefixtures("ma_hoa_offline")
def test_vai_bi_chan_sach_tu_choi_va_chi_ton_mot_loi_goi_llm(
    workspace_dir, khong_gian, policy
):
    """AC-2, đo trên engine thật với ba adapter thật.

    Một vai không có khóa nào thì cả `_get_node_data` lẫn `_get_edge_data` trả
    `"", "", ""`, khung ngữ cảnh về ba khối trắng, và `hoi_dap` dừng **trước**
    lời gọi sinh câu trả lời. Nhật ký LLM vì thế có đúng một prompt, prompt
    trích từ khóa - đó là nhánh tất định mà FR-16 đòi ("ngữ cảnh truy hồi rỗng
    thì render template không gọi LLM").

    Ca L0 không có nhánh nhận diện riêng, và đó là cố ý: L0 vô hình nên tầng ứng
    dụng không có tín hiệu "đã chặn thứ gì đó". Nó đi ra bằng đúng nhánh này.
    """
    engine, llm = _engine_m1(workspace_dir, khong_gian, policy)

    async def chay():
        with use_context(_vai_khong_khoa(khong_gian, policy)):
            return await engine.hoi_dap(CAU_HOI)

    ket_qua = asyncio.run(chay())
    assert ket_qua.ly_do_tu_choi == LY_DO_NGU_CANH_RONG
    assert ket_qua.cau_tra_loi is None
    assert llm.so_lan == 1, f"tốn thêm lời gọi LLM: {llm.prompts}"
    assert KHOA_KHONG_CO_DAP_AN not in llm.prompts[0]


@pytest.mark.usefixtures("ma_hoa_offline")
def test_vai_co_khoa_tra_loi_va_ton_dung_hai_loi_goi_llm(
    workspace_dir, khong_gian, policy
):
    """Hàng "Có đáp án": hai lời gọi, và lời gọi thứ hai là prompt của **dự án**.

    `prompts_sinh_cau_tra_loi` rỗng là phép kiểm rằng `rag_response` của vendor
    không còn được đi: nó chỉ nhận lời gọi có `system_prompt`, thứ mà đường của
    dự án không truyền.
    """
    from tests.ngu_canh import vai

    engine, llm = _engine_m1(workspace_dir, khong_gian, policy)

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            return await engine.hoi_dap(CAU_HOI)

    ket_qua = asyncio.run(chay())
    assert ket_qua.ly_do_tu_choi is None
    assert isinstance(ket_qua.cau_tra_loi, str) and ket_qua.cau_tra_loi
    assert llm.so_lan == 2, f"số lời gọi LLM: {llm.prompts}"
    assert llm.prompts[1].startswith(DAU_PROMPT_TRA_LOI)
    assert llm.prompts_sinh_cau_tra_loi == []
    # `THAM_SO_LLM` phải **thật sự** xuống tới lời gọi, không chỉ tồn tại như một
    # hằng. Xóa `**THAM_SO_LLM` khỏi `hoi_dap` mà không có ca này thì cả bộ test
    # vẫn xanh, vì bản giả chọn phản hồi theo nội dung prompt chứ không theo
    # kwargs - trong khi với provider thật, mất `response_format` json_object là
    # **mọi** câu trả lời được thành 502, và mất `max_tokens` là mất trần tiền.
    # Cùng khuôn với ca của đường nạp ở `tests/test_trich_xuat.py`.
    kw = llm.kwargs[1]
    assert kw["temperature"] == 0
    assert kw["response_format"] == {"type": "json_object"}
    assert isinstance(kw["max_tokens"], int) and kw["max_tokens"] > 0
    assert kw == {**THAM_SO_LLM, **{k: v for k, v in kw.items() if k not in THAM_SO_LLM}}


@pytest.mark.usefixtures("ma_hoa_offline")
def test_co_no_answer_va_dau_ra_hong_tren_engine_that(
    workspace_dir, khong_gian, policy
):
    """Hai nhánh còn lại của lượt có ngữ cảnh, đo trên cùng engine thật.

    Cờ bật -> `co_no_answer`. Đầu ra không đọc được -> `DauRaTraLoiKhongDoc` dội
    lên **nguyên**, không thành một lý do thứ tư.
    """
    from tests.gia_lap_llm import phan_hoi_hai_luot, phan_hoi_tu_khoa
    from tests.ngu_canh import vai

    engine, llm = _engine_m1(workspace_dir, khong_gian, policy)
    ngu_canh = vai(policy, "devops", khong_gian)

    llm.theo_prompt = phan_hoi_hai_luot(khong_co_dap_an=True, cau_tra_loi="")

    async def chay():
        with use_context(ngu_canh):
            return await engine.hoi_dap(CAU_HOI)

    assert asyncio.run(chay()).ly_do_tu_choi == LY_DO_CO_NO_ANSWER

    # Đầu ra hỏng: LLM trả đúng định dạng từ khóa cho **cả hai** lượt.
    llm.theo_prompt = lambda _prompt: phan_hoi_tu_khoa()
    with pytest.raises(DauRaTraLoiKhongDoc):
        asyncio.run(chay())


def test_kg_query_tra_cau_hong_thi_tu_khoa_rong_khong_goi_llm_them(
    monkeypatch, workspace_dir
):
    """Hàng "Không trích được từ khóa", và **thứ tự** của phép nhận diện.

    `kg_query` trả `CAU_HONG_UPSTREAM` *thay cho* cả cái khung, nên nếu
    `ngu_canh_rong` được hỏi trước thì nó thấy "không có khối csv nào", trả
    `False`, và một lỗi nội bộ đi thẳng vào một lời gọi LLM trả tiền. Ca này ghim
    đúng thứ tự đó bằng cách đếm lời gọi.
    """
    from tests.gia_lap_llm import LLMGia
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine

    llm = LLMGia()
    engine = dung_engine(workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), llm)

    async def _aquery(query, param=None):
        return CAU_HONG_UPSTREAM

    monkeypatch.setattr(engine, "aquery", _aquery)
    ket_qua = asyncio.run(engine.hoi_dap(CAU_HOI))
    assert ket_qua.ly_do_tu_choi == LY_DO_TU_KHOA_RONG
    assert llm.so_lan == 0


@pytest.mark.usefixtures("ma_hoa_offline")
def test_tu_khoa_rong_tren_duong_kg_query_that(workspace_dir, khong_gian, policy):
    """Nhánh `tu_khoa_rong` đi qua **`kg_query` thật**, không qua một `aquery` bị thay.

    Ca ngay trên monkeypatch chính `aquery`, nên phép so
    `ngu_canh == CAU_HONG_UPSTREAM` ở đó không được kiểm trên đường thật - một
    chuỗi lệch một dấu chấm vẫn xanh. Ở đây LLM giả trả một chuỗi mà bộ parser
    của `kg_query` không rút ra được từ khóa nào, nên `kg_query:571-581` trả
    `fail_response` **trước khi chạm kho nào**, và đó đúng là ca của nhánh này.

    `llm.so_lan == 1` là vế thứ hai: một lượt từ chối vì thiếu từ khóa không được
    tốn lời gọi sinh câu trả lời.
    """
    from tests.ngu_canh import vai

    engine, llm = _engine_m1(workspace_dir, khong_gian, policy)
    llm.theo_prompt = None
    llm.phan_hoi = "không có bản ghi nào ở định dạng mà parser đọc được"

    async def chay():
        with use_context(vai(policy, "devops", khong_gian)):
            return await engine.hoi_dap(CAU_HOI)

    ket_qua = asyncio.run(chay())
    assert ket_qua.ly_do_tu_choi == LY_DO_TU_KHOA_RONG
    assert llm.so_lan == 1, f"nhánh từ khóa rỗng vẫn gọi LLM lần hai: {llm.prompts}"


def test_aquery_tra_ve_khong_phai_chuoi_la_loi_he_thong(monkeypatch, workspace_dir):
    """`aquery` trả một thứ không phải chuỗi là **lỗi hệ thống**, không phải từ chối.

    `ngu_canh_rong` trả `True` cho mọi giá trị không phải `str`, nên không có
    phép kiểm kiểu tường minh thì một `None` (hay một object) từ đường truy hồi
    lặng lẽ thành một lượt từ chối `ngu_canh_rong` **được đo** - tức bơm một
    trong hai cột mà Đo 2 (PRD 5.2) đếm bằng một lỗi nội bộ.
    """
    from tests.gia_lap_llm import LLMGia
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine

    llm = LLMGia()
    engine = dung_engine(workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), llm)
    for tra_ve in (None, 7, {"ngu_canh": "x"}):

        async def _aquery(query, param=None, _tra_ve=tra_ve):
            return _tra_ve

        monkeypatch.setattr(engine, "aquery", _aquery)
        with pytest.raises(NguCanhTruyHoiLa):
            asyncio.run(engine.hoi_dap(CAU_HOI))
    # Cùng họ với `DauRaTraLoiKhongDoc`, nên nó ra cùng một mã 5xx ổn định thay
    # vì mở thêm một mã trên bề mặt API.
    assert issubclass(NguCanhTruyHoiLa, DauRaTraLoiKhongDoc)
    assert llm.so_lan == 0


def test_hoi_dap_tu_choi_stream_tuong_minh(workspace_dir):
    """Phép canh `stream` phải sống lại ở đây, vì đường mới làm mất cửa cũ.

    Trước story 3.5, `kg_query:606` truyền `stream=query_param.stream` xuống
    wrapper và `bo_llm` dội `LLMStreamNotSupported`. Đường mới thoát ở `:596-597`
    nên lời gọi ấy không chạy nữa, và bỏ qua `param.stream` im lặng là biến một
    tham số vô hiệu thành một tham số trông như có tác dụng (khoản ledger 2.2,
    UX-DR4). Handler không truyền `param` nên nó không tới được từ HTTP; cửa này
    canh nơi gọi trong mã dự án.
    """
    from hypergraphrag.base import QueryParam

    from tests.gia_lap_llm import LLMGia
    from tests.gia_lap_neo4j import Neo4jGhiLai
    from tests.gia_lap_qdrant import QdrantGhiLai
    from tests.ho_tro_m1 import dung_engine

    llm = LLMGia()
    engine = dung_engine(workspace_dir, QdrantGhiLai(), Neo4jGhiLai(), llm)
    with pytest.raises(LLMStreamNotSupported):
        asyncio.run(engine.hoi_dap(CAU_HOI, QueryParam(stream=True)))
    # Từ chối **trước** khi chạm kho hay LLM: một lượt bị từ chối vì cấu hình
    # không được tiêu tiền.
    assert llm.so_lan == 0


@pytest.mark.usefixtures("ma_hoa_offline")
def test_duong_ngu_canh_tho_chay_y_nguyen(workspace_dir, khong_gian, policy):
    """AC-4: `aquery(..., only_need_context=True)` trả nguyên chuỗi ngữ cảnh.

    `eval/` và `tests/ho_tro_m1.py::hoi` đứng trên đường này, và toàn bộ bộ Đo 1
    assert trên chuỗi ấy (chốt brief §6). Story 3.5 thêm một method mới thay vì
    sửa `aquery` đúng để câu này còn đúng.
    """
    from tests.ho_tro_m1 import hoi
    from tests.ngu_canh import vai

    engine, llm = _engine_m1(workspace_dir, khong_gian, policy)

    async def chay():
        return await hoi(engine, vai(policy, "devops", khong_gian))

    ngu_canh = asyncio.run(chay())
    assert isinstance(ngu_canh, str)
    assert "-----Entities-----" in ngu_canh
    assert llm.so_lan == 1, "đường ngữ cảnh thô không được sinh câu trả lời"


# --- Lớp 3: envelope và audit qua HTTP -----------------------------------------


@pytest.fixture
def kho_gia():
    return KhoGia(
        {
            TEN_GO["ts01"]: _dong("ts01"),
            TEN_GO["dev01"]: _dong("dev01", role="devops", demo=True, admin=True),
        }
    )


@pytest.fixture
def audit_gia():
    return AuditGia()


@pytest.fixture
def engine_gia():
    return EngineGia()


@pytest.fixture
def client(monkeypatch, kho_gia, audit_gia, engine_gia):
    monkeypatch.setenv(BIEN_KHOA_KY, KHOA_TEST)

    async def _mo_kho():
        return kho_gia

    async def _mo_audit():
        return audit_gia

    async def _mo_engine(audit):
        return engine_gia

    monkeypatch.setattr(api_main, "mo_kho_tai_khoan", _mo_kho)
    monkeypatch.setattr(api_main, "mo_audit", _mo_audit)
    monkeypatch.setattr(api_main.hoi_dap, "mo_engine", _mo_engine)
    with TestClient(api_main.app) as c:
        yield c


def _bearer(client, tai_khoan: str) -> dict:
    kq = client.post(
        "/auth/login", json={"tai_khoan": TEN_GO[tai_khoan], "mat_khau": MAT_KHAU}
    )
    assert kq.status_code == 200, kq.text
    return {"Authorization": "Bearer " + kq.json()["token"]}


def _hoi(client, tai_khoan: str = "ts01"):
    return client.post(
        "/hoi-dap", json={"cau_hoi": CAU_HOI}, headers=_bearer(client, tai_khoan)
    )


def _su_kien(audit_gia, event: str) -> list:
    return [sk for sk in audit_gia.su_kien if sk.event == event]


def test_ba_nhanh_tu_choi_cho_than_bang_nhau_tung_byte(client, engine_gia, audit_gia):
    """AC-1, và là mệnh đề trung tâm của cả story.

    Cùng tài khoản, cùng bảng chính sách, ba lý do lần lượt xảy ra: thân response
    của cả ba **bằng nhau từng byte**. So `response.content` chứ không so từng
    field - một phép so field bỏ lọt thứ tự khóa và khoảng trắng của serializer,
    và người dò thì đọc byte.

    Vế thứ hai: mỗi lượt sinh đúng một hàng `refusal` mang lý do **khác nhau**.
    Không có nó thì "byte giống hệt" đọc được thành "hệ không biết mình vừa từ
    chối vì cái gì", và hai cột của Đo 2 (PRD 5.2) không có nguồn.
    """
    than: list[bytes] = []
    for ly_do in DANH_MUC_LY_DO:
        audit_gia.su_kien.clear()
        engine_gia.ly_do = ly_do
        kq = _hoi(client)
        assert kq.status_code == 200, kq.text
        than.append(kq.content)
        hang = _su_kien(audit_gia, EVENT_REFUSAL)
        assert len(hang) == 1
        assert hang[0].chi_tiet[CT_LY_DO] == ly_do
        assert hang[0].tier == TIER_OBSERVATION
        assert hang[0].role == "tech_support" and hang[0].act == "ts01"
        # Lượt từ chối vẫn là một lượt hỏi có độ trễ: NFR-08 đo trên mọi lượt.
        assert len(_su_kien(audit_gia, EVENT_QUERY)) == 1

    assert len(set(than)) == 1, (
        "ba lượt từ chối cho ba thân khác nhau: đó là kênh dò mà FR-16 dựng ra"
        f" để bịt.\n  " + "\n  ".join(t.decode() for t in than)
    )


def test_envelope_tu_choi_dung_nam_khoa_answer_null_refused_true(client, engine_gia):
    """Hình dạng của một lượt từ chối, và nó đi qua **đúng** serializer của 3.3.

    `answer` là `null` chứ không phải câu template: máy đọc cờ `refused`, còn câu
    người dùng đọc là `TEMPLATE_TU_CHOI` do tầng render dựng. Ghép câu ấy vào
    `answer` là một chỗ thứ hai để wording trôi.
    """
    engine_gia.ly_do = LY_DO_NGU_CANH_RONG
    than = _hoi(client).json()
    assert tuple(than) == KHOA_ENVELOPE
    assert than["answer"] is None
    assert than["refused"] is True
    assert than["citations"] == []
    assert than["graph"] == {"nodes": [], "edges": []}
    assert tuple(than["meta"]) == KHOA_META


def test_ly_do_tu_choi_khong_bao_gio_ra_response(client, engine_gia):
    """AD-8: lý do chỉ vào audit. Chấm trên **byte thô**, không trên field.

    Một lý do lọt ra dưới dạng một trường lồng, một chuỗi trong `answer`, hay một
    header đều là cùng một lỗ; phép so trên byte thân response bắt cả ba.
    """
    for ly_do in DANH_MUC_LY_DO:
        engine_gia.ly_do = ly_do
        kq = _hoi(client)
        # Vòng trong chấm **cả ba** chuỗi ở mỗi lượt, không chỉ chuỗi của lượt
        # đó: một handler ghép nhầm một hằng cố định cũng là một lỗ.
        for chuoi in DANH_MUC_LY_DO:
            assert chuoi.encode() not in kq.content


def test_dau_ra_llm_khong_doc_duoc_ra_5xx_va_khong_ghi_refusal(client, engine_gia, audit_gia):
    """AC-3: lỗi hệ thống khác từ chối, và nó **không** để lại một hàng `refusal`.

    Vế thứ hai là vế dễ quên và là vế đắt: một hàng `refusal` ghi kèm ở đây làm
    hai cột của Đo 2 đếm cả lỗi nội bộ, và con số đó là con số chương 4 phát biểu
    về khả năng từ chối của hệ.
    """
    engine_gia.loi = DauRaTraLoiKhongDoc("LLM trả một câu tiếng Anh")
    kq = _hoi(client)
    assert kq.status_code == 502, kq.text
    than = kq.json()
    assert tuple(than) == ("error",)
    assert than["error"]["code"] == MA_DAU_RA_LLM_KHONG_DOC_DUOC
    assert "refused" not in kq.text
    assert _su_kien(audit_gia, EVENT_REFUSAL) == []
    assert _su_kien(audit_gia, EVENT_QUERY) == []
    # Thân lỗi không mang nguyên văn đầu ra LLM: nó là văn bản sinh từ ngữ cảnh
    # đã lọc, và một thân lỗi mang nó đi vòng qua cả tầng che lẫn envelope.
    assert "tiếng Anh" not in kq.text


@pytest.mark.parametrize(
    "loi, http, ma",
    [
        (QdrantIndexMissing("collection chưa có"), 503, MA_KHO_KHONG_SAN_SANG),
        (Neo4jUnavailable("neo4j chưa lên"), 503, MA_KHO_KHONG_SAN_SANG),
        (TimeoutError("llm treo"), 504, MA_LLM_QUA_HAN),
        (ChanNhipQuaLau("provider đòi chờ 3600 giây"), 502, MA_LLM_LOI),
    ],
    ids=["qdrant_vang", "neo4j_chet", "treo", "chan_nhip"],
)
def test_loi_kho_hay_llm_giua_luot_khong_gia_dang_tu_choi(
    client, engine_gia, audit_gia, loi, http, ma
):
    """Hàng cuối của I/O Matrix: mã của story 3.3 giữ **nguyên** sau story này.

    Đường lỗi nay đi qua `EngineGia.hoi_dap` chứ không còn `aquery`, nên bốn mã
    ấy phải được chấm lại ở đây chứ không chỉ ở `tests/test_hoi_dap.py`: một
    nhánh `except` đặt sai chỗ trong `tra_loi` biến một 503 thành một lượt từ
    chối, và khi đó hệ nói dối về trạng thái của chính nó đúng lúc kho đang chết.

    Vế thứ hai, và là vế của story này: **không** hàng `refusal` nào được ghi.
    """
    engine_gia.loi = loi
    kq = _hoi(client)
    assert kq.status_code == http, kq.text
    assert tuple(kq.json()) == ("error",)
    assert kq.json()["error"]["code"] == ma
    assert "refused" not in kq.text
    assert _su_kien(audit_gia, EVENT_REFUSAL) == []


def test_audit_hong_o_luot_tu_choi_van_tra_envelope_khong_doi(client, engine_gia, audit_gia):
    """Hàng "Audit hỏng ở lượt từ chối": 200, envelope không đổi một byte.

    So với chính lượt từ chối lúc audit khỏe: `ghi_quan_sat` là best-effort, nên
    một Postgres chết làm mất một hàng số liệu chứ không làm mất một câu trả lời -
    và tuyệt đối không được đổi thân response, vì khi đó "audit đang hỏng" thành
    một tín hiệu đọc được từ ngoài.
    """
    engine_gia.ly_do = LY_DO_CO_NO_ANSWER
    khoe = _hoi(client).content
    audit_gia.no = RuntimeError("postgres chết")
    kq = _hoi(client)
    assert kq.status_code == 200, kq.text
    assert kq.content == khoe


def test_hai_vai_khac_nhau_o_meta_va_khong_o_dau_khac(client, engine_gia):
    """Byte-identical đo **giữa lý do**, không giữa vai, và ca này nói ra chỗ đó.

    `meta` mang `role`, `space`, `policy_version`, nên hai vai nhận hai thân khác
    nhau ở lượt từ chối - đúng như ở lượt trả lời. Đó không phải kênh dò: người
    hỏi vốn đã biết vai của chính mình. Cái phải giống nhau là **bốn khóa còn
    lại**, và ca này chấm đúng chừng đó.
    """
    engine_gia.ly_do = LY_DO_NGU_CANH_RONG
    ts = _hoi(client, "ts01").json()
    dev = _hoi(client, "dev01").json()
    assert ts["meta"]["role"] != dev["meta"]["role"]
    assert {k: v for k, v in ts.items() if k != "meta"} == {
        k: v for k, v in dev.items() if k != "meta"
    }


def test_luot_tra_loi_van_refused_false_va_khong_co_hang_refusal(client, engine_gia, audit_gia):
    """Hàng "Có đáp án" giữ nguyên nghĩa cũ sau story này."""
    than = _hoi(client).json()
    assert than["refused"] is False
    assert than["answer"] == engine_gia.tra_loi
    assert _su_kien(audit_gia, EVENT_REFUSAL) == []
    assert len(_su_kien(audit_gia, EVENT_QUERY)) == 1


# --- Wording template ----------------------------------------------------------


def test_template_tu_choi_dung_nguyen_van_va_khong_ghep_gi():
    """Wording chốt ở story này kèm `docs/adr/ADR-015`, và nó là một hằng trần.

    Không chỗ chèn, không `%s`, không `{}`: một template ghép được là một template
    ghép vai, nhóm phụ trách hay tên scope vào, và khi đó độ dài chuỗi một mình
    đã là kênh dò - người dò không cần đọc nội dung.
    """
    assert TEMPLATE_TU_CHOI == "Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi này."
    for cam in ("{", "}", "%s", "%(", "<<"):
        assert cam not in TEMPLATE_TU_CHOI
    for cam in ("vai", "nhóm", "scope", "quyền", "L0", "L1"):
        assert cam not in TEMPLATE_TU_CHOI


def test_template_tu_choi_chi_co_mot_ban_trong_ma_nguon():
    """Một hằng số duy nhất phía `api/`; không bản chép thứ hai trong code.

    Quét mọi file `.py` của bốn tầng code: chuỗi chỉ được xuất hiện ở
    `api/hoi_dap.py` (nơi khai) và ở chính file test này (nơi ghim nguyên văn).
    Bản thứ hai của một wording là chỗ hai bên lệch nhau mà không ai biết, và
    ADR-015 khi đó chỉ chốt được một trong hai.
    """
    cho_phep = {"api/hoi_dap.py", "tests/test_tu_choi.py"}
    thay = set()
    for tang in ("core", "adapters", "api", "eval", "redteam", "tests"):
        thu_muc = GOC / tang
        if not thu_muc.is_dir():
            continue
        for py in thu_muc.rglob("*.py"):
            if TEMPLATE_TU_CHOI in py.read_text(encoding="utf-8"):
                thay.add(str(py.relative_to(GOC)))
    assert thay == cho_phep, f"wording template từ chối xuất hiện ở {sorted(thay)}"


def test_adr_015_chot_dung_wording_dang_chay():
    """ADR chốt wording phải mang **đúng** chuỗi mà code đang dùng.

    Action item Epic 3 của sonlm đòi một ADR năm dòng cho câu này. Một ADR chốt
    một chuỗi khác chuỗi đang chạy là tệ hơn không có ADR nào: nó làm vòng sau
    tin rằng câu đã được quyết.
    """
    adr = GOC / "docs" / "adr" / "ADR-015-wording-template-tu-choi-fr-16.md"
    assert adr.exists(), "story 3.5 phải để lại ADR wording template từ chối"
    noi_dung = adr.read_text(encoding="utf-8")
    assert TEMPLATE_TU_CHOI in noi_dung
    for ly_do in DANH_MUC_LY_DO:
        assert ly_do in noi_dung, f"ADR không nhắc lý do {ly_do}"
