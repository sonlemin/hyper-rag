"""Thí nghiệm CT-03: node entity là điểm hợp nhất đa nguồn (story 2.10, bằng chứng ĐG3).

    HYPER_RAG_MODULE=eval.ct03 scripts/chay-may-chu.sh ct03 --space synth

**Câu hỏi của thí nghiệm.** Node entity là điểm hợp nhất: một tên entity xuất
hiện ở hai tài liệu thì chỉ có **một** node trong graph, và mọi trường của node
đó là kết quả gộp từ cả hai tài liệu. Upstream gộp bằng `GRAPH_FIELD_SEP.join`
(`operate.py:181-196`), pipeline của dự án gộp khóa quyền bằng
`core.keys.hop_nhat_khoa` (FR-11, AD-5). Nếu hai tài liệu khác hạng quyền thì
node hợp nhất là chỗ nội dung của tài liệu hạn chế có thể đi ra qua tài liệu
công khai. Adapter đóng đường `description` bằng ngưỡng L2 (`_che_mo_ta`,
NFR-06 và FR-05); thí nghiệm này là bằng chứng rằng **có vật liệu thật** cho ca
đó trong kho, chứ không phải một rủi ro giả định trên giấy.

**Phát hiện của lần chạy 04/09/2026 trên space `synth`.** `description` của mọi
node entity là **chuỗi rỗng**, nên đường mà `_che_mo_ta` canh hiện chưa có gì
chảy qua. Đây **không phải một lỗ**: Design Notes của `spec-2-4` chốt tường minh
"`description` entity rỗng - entity là giá trị slot, mô tả LLM viết lại chỉ nhân
đôi cùng chuỗi và mở thêm một mặt rò ở L2". CT-03 là lần đầu quyết định đó được
xác nhận trên dữ liệu thật thay vì suy từ prompt. Phép hợp nhất thì có thật và
đo được ở ba trường khác của cùng node, nên trang in cả bốn trường thay vì chỉ
`description`:

- `source_id` - danh sách chunk nguồn, ghép bằng `<SEP>` từ mọi tài liệu chạm
  tới entity. Đây là chỗ phép gộp đa nguồn nhìn thấy được hôm nay.
- `filter_key` - khóa quyền đã hợp nhất. `None` là ca hợp nhất **khác scope**
  của AD-5: node ở lại mà không vai nào chạm tới.
- `entity_type` - một giá trị duy nhất, dù entity điền nhiều vai slot khác nhau
  ở các hyperedge khác nhau.

Trang nói thẳng cả hai vế: trường mà spec chỉ tên đang rỗng theo thiết kế, và
phép hợp nhất vẫn đo được. Đọc `description` rỗng thành "không có rủi ro" là đọc
sai; nó nghĩa là kênh đó đang tắt theo một quyết định của story 2.4, và story
2.12 mở nó ra thì mặt rò L2 quay lại - khoản nợ có địa chỉ trong ledger.

**Đọc thuần.** Không `initialize()` (nó dựng ràng buộc, tức ghi), không nạp,
không xóa, không gọi LLM. Cùng hạng với `eval/chup_do_thi.py`: một harness đo
chạy ngoài tiến trình phục vụ, `tests/test_import_lint.py` giữ danh sách trắng
đúng một dòng cho file này.

**Ranh giới ngữ cảnh phải nói ra thành lỗi**, không thành một trang rỗng: chạy ngoài cờ hệ thống thì `get_node` chỉ lặng lẽ
trả `None` cho mọi id (không khóa để đọc), nên module tự dội
`IngestOutsideSystemContext` trước khi chạm kho. Đây là một thí nghiệm, không
phải một endpoint: nó không đục lỗ tầng che nào, và không có đường nào từ API
tới đây.

**Hai nguồn, một trang.** Danh sách entity đa nguồn suy từ ảnh chụp đồ thị đã
commit (hàm thuần, có test); bốn trường của node đọc từ Neo4j. Ảnh chụp cho biết
*nên* hỏi những entity nào và chúng đến từ tài liệu nào; kho cho biết node hợp
nhất của chúng thật ra mang gì.

**Vì sao dưới cờ hệ thống** (bổ sung cho đoạn trên): thí nghiệm phải đọc bốn
trường *nguyên văn*; dưới một vai người dùng, `_che_mo_ta` trả dấu che và
`get_node` trả `None` cho mọi id ngoài quyền, nên trang sẽ không chứng minh
được gì.
"""

import argparse
import asyncio
import html
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from neo4j.exceptions import Neo4jError

from adapters.engine import BIEN_MOI_TRUONG, cau_hinh_kho_tu_moi_truong
from adapters.ingest_labels import bat_buoc_ngu_canh_he_thong
from adapters.kv import WORKING_DIR_KEY
from adapters.neo4j import (
    DESCRIPTION_FIELD,
    ENTITY_TYPE_FIELD,
    NEO4J_PASSWORD_KEY,
    NEO4J_URI_KEY,
    Neo4jACLGraphStorage,
)
from adapters.policy_loader import load_policy
from core.facts import TEN_VAI_TIENG_VIET
from eval.rao_ghi_repo import SPACE_GHI_TRONG_REPO
from core.keys import FILTER_KEY_FIELD
from core.permission import use_context
from core.policy import PolicyInvalid
from core.system_context import system_context
from eval.cau_hoi import (
    DUONG_DAN_ANH_MAC_DINH,
    AnhDoThi,
    AnhDoThiKhongHopLe,
    doc_anh_do_thi,
)

_GOC = Path(__file__).resolve().parent
REPO_ROOT = _GOC.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-toi-gian.yaml"
THU_MUC_HTML: Path = _GOC / "expr"


def duong_dan_html(space: str) -> Path:
    """Trang của một space. Tên mang space, vì một tên cố định là ghi đè im lặng.

    Chạy `--space khao_sat` sau `--space synth` với một `ct03.html` dùng chung
    thì trang thứ hai đè mất trang thứ nhất, và ảnh PNG đã chụp từ trang trước
    không còn gì đối chiếu lại được. Đây là bằng chứng ĐG3, nên nó không được
    biến mất vì một lần chạy lệnh khác space.
    """
    return THU_MUC_HTML / f"ct03-{space}.html"

# Cùng namespace graph mà `EngineACL` truyền xuống adapter.
NAMESPACE_GRAPH: str = "chunk_entity_relation"

# Dấu upstream dùng để nối mô tả của cùng một entity qua nhiều hyperedge
# (`vendor/hypergraphrag/utils.py`). Tách theo dấu này là cách đọc ra "mô tả này
# ghép từ mấy mảnh"; nó là hằng của vendor nên chép lại kèm lý do thay vì import
# ngược (`eval/` không được chạm `vendor/`).
GRAPH_FIELD_SEP: str = "<SEP>"

# Trường mang danh sách chunk nguồn của một node, do upstream ghép bằng
# `GRAPH_FIELD_SEP`. Chuỗi thô chứ không phải hằng của `core/`: `adapters/neo4j.py`
# cũng viết thẳng `"source_id"` ở các câu Cypher, nên nó là tên field của
# upstream chứ không phải một quy ước của dự án.
SOURCE_ID_FIELD: str = "source_id"

# Vai slot mà một giá trị của nó gần như luôn là một mốc hay một khoảng thời
# gian, và tên entity dạng số thuần (ngày, giờ, tỷ lệ, số lần). Hai thứ này là
# **bằng chứng yếu** cho CT-03: "12 tháng" xuất hiện ở hai tài liệu chỉ nói hai
# tài liệu cùng nhắc một khoảng thời gian, không nói hai vùng quyền gặp nhau ở
# một thực thể. Chúng vẫn ở lại trang - loại chúng là chọn dữ liệu cho đẹp -
# nhưng xuống cuối, xem `thu_tu_bang_chung`.
VAI_GIA_TRI_YEU: frozenset[str] = frozenset({"time"})
MAU_SO_THUAN = re.compile(r"^[\d\s./:%,+\-]*\d[\d\s./:%,+\-]*$")

# Số từ mà trên đó một "tên entity" không còn là tên một thực thể mà là một câu.
# Giá trị của `remediation` và `condition` chưa chuẩn hóa hay ra những chuỗi như
# "trả giới hạn bộ nhớ PHP-FPM về mức cũ rồi nạp lại cấu hình theo SOP-12" (14 từ)
# hay "gửi ra ngoài phải có phê duyệt của Giám đốc Kỹ thuật" (10 từ). Chúng *đúng*
# là entity đa nguồn theo dữ liệu, nhưng hai tài liệu cùng chứa một câu hướng dẫn
# giống nhau nói hai tài liệu chép cùng một câu, không nói hai vùng quyền gặp nhau
# ở một thực thể - đó là ca chuẩn hóa thực thể của story 2.12, không phải bằng
# chứng ĐG3.
#
# **Đếm từ chứ không hạ theo vai `condition`/`remediation`.** Hạ theo vai bắt
# đúng hai câu trên nhưng cũng hạ nhầm những thực thể thật chỉ tình cờ điền vào
# hai vai đó: "cổng thanh toán của khách hàng B", "trưởng nhóm vận hành khách
# hàng A", "trình duyệt và ứng dụng đối tác" đều là thực thể thật.
#
# Ngưỡng 8 đọc từ chính dữ liệu: trên `synth` có một khoảng trống rõ giữa 9 từ
# và 12 từ, và hai chuỗi trên 8 từ mà vẫn là *tên* ("thời hạn xử lý là 2 ngày làm
# việc", "cấp theo yêu cầu có thời hạn 8 giờ", 9 từ) đã bị hạ bằng vai `time`
# hoặc sẽ được chuẩn hóa ở 2.12. Đặt ngưỡng thấp hơn là hạ nhầm thực thể thật;
# cao hơn là để hai câu mệnh lệnh mở trang.
SO_TU_TOI_DA_CUA_TEN: int = 8

# Vật mà module này ghi ra: trang CT-03, dump nguyên văn **tên entity** của mọi
# ca đa nguồn, và ảnh PNG chụp lại trang thì **có commit**. Một `--space real`
# rồi chụp màn hình là đưa tên thực thể của dữ liệu công ty vào lịch sử git.
# Muốn chạy space khác thì phải `--dich` ra ngoài cây repo.
#
# Danh sách và lý do của nó ở `eval/rao_ghi_repo.py`, dùng chung với
# `eval/chup_do_thi.py` và `eval/de_xuat_bi_danh.py` (retro Epic 2).

# Ba biến môi trường không có mặc định nào an toàn, cùng bộ với
# `eval/chup_do_thi.py`. `scripts/chay-may-chu.sh` dựng sẵn đủ bộ.
BIEN_BAT_BUOC: tuple[str, ...] = (
    BIEN_MOI_TRUONG[NEO4J_URI_KEY],
    BIEN_MOI_TRUONG[NEO4J_PASSWORD_KEY],
    BIEN_MOI_TRUONG[WORKING_DIR_KEY],
)


class KhongCoVatLieu(ValueError):
    """Ảnh chụp không có entity nào đa nguồn: không dựng trang, từ chối cả đợt.

    Hàng "CT-03 không vật liệu" của I/O Matrix. Một trang rỗng trông y hệt một
    trang chứng minh rằng rủi ro không tồn tại, mà thật ra nó chỉ nói ảnh chụp
    này không có ca nào - hai câu rất khác nhau khi trang là bằng chứng ĐG3.

    `code` ổn định để test assert trên `code` (AD-8).
    """

    code = "CT03_KHONG_VAT_LIEU"


@dataclass(frozen=True)
class EntityDaNguon:
    """Một entity xuất hiện trong hyperedge của từ hai `doc_key` trở lên."""

    ten: str
    doc_key: tuple[str, ...]
    hyperedge: tuple[str, ...]
    vai: tuple[str, ...]
    # `{doc_key: (id hyperedge, ...)}` - chiều để trang chỉ đúng fact nào của
    # tài liệu nào đã góp một mảnh vào mô tả gộp.
    hyperedge_theo_doc_key: Mapping[str, tuple[str, ...]]

    @property
    def so_nguon(self) -> int:
        return len(self.doc_key)


@dataclass(frozen=True)
class MoTaEntity:
    """Một entity đa nguồn cộng bốn trường mà node hợp nhất của nó đang giữ."""

    entity: EntityDaNguon
    mo_ta: str | None
    khoa: str | None
    # Số mảnh mà upstream đã ghép vào `description` (tách theo `GRAPH_FIELD_SEP`).
    so_manh: int
    # Ba trường còn lại của cùng node hợp nhất. `nguon` là chỗ phép gộp đa nguồn
    # nhìn thấy được khi `description` rỗng; `loai` là một giá trị duy nhất dù
    # entity điền nhiều vai.
    nguon: str | None = None
    so_chunk_nguon: int = 0
    loai: str | None = None
    # `True` khi node không có trong graph, phân biệt với node có mà mô tả rỗng.
    vang_trong_graph: bool = False

    @property
    def thieu_trong_graph(self) -> bool:
        return self.vang_trong_graph

    @property
    def thieu_truong_mo_ta(self) -> bool:
        """Node có trong graph mà **không có** trường `description`.

        Khác hẳn `mo_ta_rong`: "trường có, giá trị rỗng" là quyết định của story
        2.4; "không có trường" là một node hình dạng khác, ví dụ node vai
        hyperedge (`operate.py:153` chỉ ghi `role`, `weight`, `source_id`) hay
        một node do đường ghi khác sinh ra. Gộp hai ca lại là trang khẳng định
        "chuỗi rỗng theo quyết định 2.4" cho một node mà quyết định đó không nói
        gì về nó.
        """
        return not self.vang_trong_graph and self.mo_ta is None

    @property
    def mo_ta_rong(self) -> bool:
        """Node có trường `description` mà giá trị rỗng - phát hiện 04/09/2026."""
        return (
            not self.vang_trong_graph
            and self.mo_ta is not None
            and not self.mo_ta.strip()
        )

    @property
    def gop_da_nguon(self) -> bool:
        """Node này có đúng là điểm hợp nhất đo được không.

        Hai dấu hiệu độc lập, lấy cái nào có: mô tả ghép từ nhiều mảnh, hoặc
        `source_id` ghép từ nhiều chunk. Ảnh chụp đã nói entity này đến từ nhiều
        tài liệu; đây là phép xác nhận từ phía kho.
        """
        return self.so_manh > 1 or self.so_chunk_nguon > 1

    @property
    def khac_scope(self) -> bool:
        """Khóa quyền hợp nhất thành **không khóa**: ca khác scope của AD-5.

        Bằng chứng mạnh nhất của CT-03. Nó nói hai vùng quyền khác nhau gặp nhau
        ở đúng thực thể này, tới mức không vai nào còn chạm được node - tức phép
        hợp nhất không phải một chi tiết cài đặt mà là thứ đổi được quyền.
        """
        return not self.vang_trong_graph and self.khoa is None

    @property
    def la_gia_tri_yeu(self) -> bool:
        """Mốc thời gian, số thuần, hay một câu: vẫn là entity đa nguồn, nhưng yếu.

        Ba dấu hiệu, lấy cái nào có:

        - **Vai yếu**, hôm nay chỉ `time`. Nguồn là **vai trong ảnh chụp**, tức
          mọi vai mà entity này thật sự điền; `entity_type` của node chỉ dùng khi
          ảnh chụp không có vai nào. Hai lý do: node mang đúng **một**
          `entity_type` dù entity điền nhiều vai ở nhiều hyperedge (giá trị còn
          lại của lần ghi cuối, không phải một tổng kết), và node vắng trong
          graph có `loai` là `None` - dựa vào nó là để nhánh chết lặng ở đúng ca
          mà ảnh chụp vẫn trả lời được.
        - **Số thuần.** "12", "09:20", "5000".
        - **Câu chứ không phải tên.** Quá `SO_TU_TOI_DA_CUA_TEN` từ.

        Không loại khỏi trang - loại là chọn dữ liệu cho đẹp - chỉ xếp xuống cuối.
        """
        vai = set(self.entity.vai) or ({self.loai} if self.loai else set())
        if vai and vai <= VAI_GIA_TRI_YEU:
            return True
        if MAU_SO_THUAN.match(self.entity.ten):
            return True
        return len(self.entity.ten.split()) > SO_TU_TOI_DA_CUA_TEN


def thu_tu_bang_chung(m: MoTaEntity) -> tuple:
    """Khóa sắp xếp của trang: mạnh nhất trước, yếu nhất sau.

    Trang này là bằng chứng ĐG3 trước hội đồng, nên thứ đọc được trong màn hình
    đầu tiên phải là ca mạnh nhất. Thứ tự chữ cái - thứ tự cũ - mở trang bằng
    "12 tháng" và "12/08/2026 lúc 09:20", hai ca yếu nhất trong 46.

    Bốn tầng, giảm dần theo sức nặng của điều chúng chứng minh:

    1. **Giá trị yếu xuống cuối** (mốc thời gian, số thuần). Đây là tầng ngoài
       cùng chứ không phải tầng trong: một mốc thời gian hợp nhất thành không
       khóa vẫn là một mốc thời gian, và để nó mở trang là mất chỗ mạnh nhất.
    2. **Hợp nhất thành không khóa** (AD-5, khác scope). Bằng chứng mạnh nhất:
       hai vùng quyền gặp nhau tới mức không vai nào còn chạm được node.
    3. **Nhiều tài liệu nguồn hơn**. Càng nhiều tài liệu chạm vào, phép hợp nhất
       càng khó gọi là ngẫu nhiên.
    4. **Nhiều vai slot hơn**. Một entity điền `subject` ở tài liệu này và
       `symptom` ở tài liệu kia là ca `entity_type` một giá trị nói không đủ.

    Tên entity là tầng cuối, chỉ để hai lần chạy cho cùng một trang.
    """
    return (
        m.la_gia_tri_yeu,
        not m.khac_scope,
        -m.entity.so_nguon,
        -len(m.entity.vai),
        m.entity.ten,
    )


def sap_theo_bang_chung(ds: Sequence[MoTaEntity]) -> tuple[MoTaEntity, ...]:
    """`ds` sắp lại theo `thu_tu_bang_chung`. Hàm thuần, ổn định."""
    return tuple(sorted(ds, key=thu_tu_bang_chung))


def entity_da_nguon(anh: AnhDoThi) -> tuple[EntityDaNguon, ...]:
    """Entity xuất hiện ở hyperedge của từ hai tài liệu trở lên. Hàm thuần.

    Hyperedge **không** phải là chiều đa nguồn ở đây: trên corpus 2.8 không
    hyperedge nào đa nguồn (`so_hyperedge_da_nguon` là 0, vì `id_fact` băm tập
    slot mà LLM trích ra hai tập khác nhau cho cùng một sự thật). Chiều đa nguồn
    thật sự sống ở **entity**: cùng một tên entity được nối vào hyperedge của
    nhiều tài liệu, và chính node entity đó là nơi upstream gộp mô tả.

    Sắp xếp mọi thứ để hai lần chạy trên cùng ảnh chụp cho cùng một trang.
    """
    theo_ten: dict[str, dict[str, set[str]]] = {}
    vai_theo_ten: dict[str, set[str]] = {}
    for h in anh.hyperedge:
        for vai, gia_tri in h.slots.items():
            for e in gia_tri:
                cua_e = theo_ten.setdefault(e, {})
                for doc_key in h.doc_key:
                    cua_e.setdefault(doc_key, set()).add(h.id)
                vai_theo_ten.setdefault(e, set()).add(vai)

    ket_qua = []
    for ten in sorted(theo_ten):
        theo_dk = theo_ten[ten]
        if len(theo_dk) < 2:
            continue
        moi_he = sorted({i for ds in theo_dk.values() for i in ds})
        ket_qua.append(
            EntityDaNguon(
                ten=ten,
                doc_key=tuple(sorted(theo_dk)),
                hyperedge=tuple(moi_he),
                vai=tuple(sorted(vai_theo_ten[ten])),
                hyperedge_theo_doc_key={
                    dk: tuple(sorted(ds)) for dk, ds in sorted(theo_dk.items())
                },
            )
        )
    if not ket_qua:
        raise KhongCoVatLieu(
            f"ảnh chụp space {anh.space!r} không có entity nào xuất hiện ở từ hai"
            " tài liệu trở lên: không có vật liệu cho CT-03, nên không dựng trang."
            " Một trang rỗng đọc y hệt một trang chứng minh rủi ro không tồn tại"
        )
    return tuple(ket_qua)


def ly_do_tu_choi_space(space: str, dich, anh_space: str, goc_repo=None) -> str | None:
    """Lý do từ chối một lần chạy CT-03, hoặc `None` nếu chạy được. Hàm thuần.

    Hai cửa, tách khỏi `main` để chấm được cả hai chiều mà không cần kho:

    - **Ảnh chụp lệch `--space`.** Ảnh chụp quyết định *hỏi entity nào*, kho trả
      lời *node đó mang gì*. Hai bên khác space thì trang liệt kê entity của kho
      này bằng danh sách của kho kia, và mọi entity sẽ "vắng trong graph" - một
      trang trông như kho hỏng trong khi chỉ là gõ nhầm một tham số.
    - **Space ngoài danh sách cho phép mà đích lại nằm trong cây repo.** Trang
      dump nguyên văn tên entity và ảnh PNG của nó có commit; xem
      `SPACE_GHI_TRONG_REPO`.
    """
    if anh_space != space:
        return (
            f"ảnh chụp là của space {anh_space!r} còn --space là {space!r}: hai bên"
            " phải cùng một space, nếu không trang liệt kê entity của kho này bằng"
            " danh sách của kho kia"
        )
    if space in SPACE_GHI_TRONG_REPO:
        return None
    goc = (REPO_ROOT if goc_repo is None else Path(goc_repo)).resolve()
    try:
        Path(dich).resolve().relative_to(goc)
    except ValueError:
        return None
    return (
        f"từ chối ghi trang CT-03 của space {space!r} vào {dich} (trong cây repo):"
        f" chỉ {sorted(SPACE_GHI_TRONG_REPO)} được phép. Trang mang nguyên văn tên"
        " entity và ảnh chụp màn hình của nó có commit, nên một space dữ liệu thật"
        " phải ghi ra ngoài repo bằng --dich"
    )


def dem_manh(mo_ta: str | None) -> int:
    """Số mảnh mô tả mà upstream đã ghép, tách theo `GRAPH_FIELD_SEP`."""
    if not mo_ta:
        return 0
    return len([m for m in mo_ta.split(GRAPH_FIELD_SEP) if m.strip()])


def thieu_bien_moi_truong(moi_truong=None) -> list[str]:
    """Tên các biến bắt buộc chưa đặt (rỗng tính là chưa đặt), giữ thứ tự khai."""
    nguon = os.environ if moi_truong is None else moi_truong
    return [ten for ten in BIEN_BAT_BUOC if not str(nguon.get(ten) or "").strip()]


async def doc_mo_ta(
    ds: Sequence[EntityDaNguon], graph: Neo4jACLGraphStorage
) -> tuple[MoTaEntity, ...]:
    """Đọc `description` của từng entity qua `get_node`, giữ nguyên thứ tự.

    Cửa cờ hệ thống ở ngay đầu, **trước** lời gọi kho đầu tiên: ngoài cờ đó
    `get_node` không có khóa nào để đọc và trả `None` cho mọi id, tức trang sẽ
    dựng ra một danh sách "không tìm thấy" thay vì nói rằng lời gọi sai ngữ cảnh.
    """
    bat_buoc_ngu_canh_he_thong("đọc mô tả entity đa nguồn cho thí nghiệm CT-03")
    ket_qua = []
    for e in ds:
        node = await graph.get_node(e.ten)
        node = node if node is not None else {}
        mo_ta = node.get(DESCRIPTION_FIELD)
        nguon = node.get(SOURCE_ID_FIELD)
        ket_qua.append(
            MoTaEntity(
                entity=e,
                mo_ta=mo_ta,
                khoa=node.get(FILTER_KEY_FIELD),
                so_manh=dem_manh(mo_ta),
                nguon=nguon,
                so_chunk_nguon=dem_manh(nguon),
                loai=node.get(ENTITY_TYPE_FIELD),
                vang_trong_graph=not node,
            )
        )
    return tuple(ket_qua)


async def chay(anh: AnhDoThi, space: str, policy_version: str, cau_hinh: dict):
    """Ghép ảnh chụp với kho; đóng driver dù hỏng ở đâu."""
    ds = entity_da_nguon(anh)
    graph = Neo4jACLGraphStorage(
        namespace=NAMESPACE_GRAPH, global_config=cau_hinh, embedding_func=None
    )
    try:
        with use_context(system_context(space=space, policy_version=policy_version)):
            return await doc_mo_ta(ds, graph)
    finally:
        await graph.close()


@dataclass(frozen=True)
class ThongKe:
    """Sáu phép đếm mà cả console lẫn bảng HTML đọc. **Một** nguồn, không hai.

    Trước đây `main` dựng lại năm phép lọc mà `dung_html` đã có, nên một lần sửa
    điều kiện ở một bên là hai bên nói hai con số khác nhau về cùng một lần chạy
    - và console là thứ vào log CI còn bảng là thứ vào ảnh chụp cho hội đồng.
    """

    tong: int
    gop_da_nguon: int
    nhieu_manh: int
    mo_ta_rong: int
    thieu_truong_mo_ta: int
    khong_khoa: int
    nhieu_vai: int
    vang_trong_graph: int


def thong_ke(ds: Sequence[MoTaEntity]) -> ThongKe:
    """Đếm một lần, dùng ở cả hai chỗ. Hàm thuần.

    `khong_khoa` gọi thẳng `MoTaEntity.khac_scope` chứ không viết lại điều kiện
    của nó: một bản thứ hai của cùng một luật là chỗ hai bên trôi khỏi nhau, và
    luật đó ("có node, và khóa là None") đã có tên rồi.
    """
    return ThongKe(
        tong=len(ds),
        gop_da_nguon=sum(1 for m in ds if m.gop_da_nguon),
        nhieu_manh=sum(1 for m in ds if m.so_manh > 1),
        mo_ta_rong=sum(1 for m in ds if m.mo_ta_rong),
        thieu_truong_mo_ta=sum(1 for m in ds if m.thieu_truong_mo_ta),
        khong_khoa=sum(1 for m in ds if m.khac_scope),
        nhieu_vai=sum(1 for m in ds if len(m.entity.vai) > 1),
        vang_trong_graph=sum(1 for m in ds if m.thieu_trong_graph),
    )


# ---------------------------------------------------------------------------
# Trang HTML
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, "Segoe UI", sans-serif; margin: 0; padding: 24px;
       background: #f6f7f9; color: #16191d; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 0 0 6px; }
.khoi { background: #fff; border: 1px solid #d8dce2; border-radius: 8px;
        padding: 16px; margin-bottom: 16px; }
.nhan { display: inline-block; font-size: 12px; padding: 2px 8px; border-radius: 10px;
        background: #e8eaee; margin-left: 6px; }
.nhan.nhieu { background: #ffe6cc; }
.mo-ta { background: #fbfbfc; border-left: 3px solid #9ab; padding: 8px 12px;
         margin: 8px 0; white-space: pre-wrap; }
.manh { background: #fff8e6; border-left: 3px solid #f0d48a; padding: 6px 10px;
        margin: 6px 0; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #dfe3e8; padding: 5px 7px; vertical-align: top;
         text-align: left; }
th { background: #eef1f4; font-weight: 600; }
code { font-size: 12px; color: #5a6069; }
.canh-bao { background: #fff8e6; border: 1px solid #f0d48a; border-radius: 6px;
            padding: 10px 12px; margin: 8px 0; font-size: 13px; }
.thieu { color: #a33; }
.rong { color: #a33; font-style: italic; }
.chu { color: #5a6069; font-size: 13px; }
"""


def _khoi_entity(m: MoTaEntity) -> str:
    e = m.entity
    lop = "nhan nhieu" if e.so_nguon > 2 else "nhan"
    nguon = "".join(
        f"<tr><td><code>{html.escape(dk)}</code></td>"
        f"<td>{', '.join(f'<code>{html.escape(i)}</code>' for i in ids)}</td></tr>"
        for dk, ids in e.hyperedge_theo_doc_key.items()
    )
    vai = ", ".join(html.escape(TEN_VAI_TIENG_VIET.get(v, v)) for v in e.vai)
    khoa = "không khóa (hợp nhất khác scope, AD-5)" if m.khoa is None else m.khoa
    than = [
        f'<div class="khoi"><h2>{html.escape(e.ten)}'
        f'<span class="{lop}">{e.so_nguon} tài liệu nguồn</span>'
        f'<span class="nhan">{len(e.hyperedge)} hyperedge</span>'
        f'<span class="nhan">{m.so_chunk_nguon} chunk nguồn</span>'
        f'<span class="nhan">{m.so_manh} mảnh mô tả</span></h2>'
        f'<p class="chu">Xuất hiện ở {len(e.vai)} vai slot: {vai}.'
        f" <code>entity_type</code> của node: <code>{html.escape(str(m.loai))}</code>"
        f" - <b>một</b> giá trị cho cả {len(e.vai)} vai.</p>"
    ]
    if m.thieu_trong_graph:
        than.append(
            '<p class="thieu">không có node entity nào mang tên này trong graph:'
            " ảnh chụp và kho lệch nhau (đợt nạp chết giữa chừng, hoặc chụp trước"
            " một lần nạp lại)</p>"
        )
    else:
        than.append(
            "<table>"
            "<tr><th>Trường của node hợp nhất</th><th>Giá trị</th></tr>"
            f"<tr><td><code>{DESCRIPTION_FIELD}</code></td><td>"
            + (
                '<span class="thieu">node không có trường này</span>'
                if m.thieu_truong_mo_ta
                else '<span class="rong">chuỗi rỗng - quyết định của story 2.4, không'
                " phải một lỗ</span>"
                if m.mo_ta_rong
                else f'<div class="mo-ta">{html.escape(m.mo_ta or "")}</div>'
            )
            + "</td></tr>"
            f"<tr><td><code>{FILTER_KEY_FIELD}</code></td>"
            f'<td><code>{html.escape(str(khoa))}</code></td></tr>'
            f"<tr><td><code>{SOURCE_ID_FIELD}</code></td><td>{m.so_chunk_nguon} chunk"
            "</td></tr></table>"
        )
        manh = [x.strip() for x in (m.mo_ta or "").split(GRAPH_FIELD_SEP) if x.strip()]
        if len(manh) > 1:
            than.append(
                f'<p class="chu">{len(manh)} mảnh mô tả đã ghép (tách theo'
                f" <code>{html.escape(GRAPH_FIELD_SEP)}</code>):</p>"
            )
            than += [f'<div class="manh">{html.escape(x)}</div>' for x in manh]
        chunk = [x.strip() for x in (m.nguon or "").split(GRAPH_FIELD_SEP) if x.strip()]
        if len(chunk) > 1:
            than.append(
                f'<p class="chu">{len(chunk)} chunk nguồn đã ghép - đây là phép hợp'
                " nhất đa nguồn nhìn thấy được trên node này:</p>"
            )
            than += [f'<div class="manh">{html.escape(x)}</div>' for x in chunk]
    than.append(
        "<table><tr><th>Tài liệu nguồn</th><th>Hyperedge của tài liệu đó</th></tr>"
        f"{nguon}</table></div>"
    )
    return "".join(than)


def dung_html(anh: AnhDoThi, ds: Sequence[MoTaEntity]) -> str:
    """Dựng toàn bộ trang từ kết quả đã đọc. Hàm thuần, không I/O.

    Sắp lại theo `thu_tu_bang_chung` ngay ở đây chứ không đòi nơi gọi sắp: trang
    là bằng chứng, và thứ tự của nó là một tính chất của trang.
    """
    ds = sap_theo_bang_chung(ds)
    ds = sap_theo_bang_chung(ds)
    tk = thong_ke(ds)
    canh_bao = ""
    if tk.vang_trong_graph:
        canh_bao = (
            f'<div class="canh-bao thieu">{tk.vang_trong_graph} entity có trong ảnh'
            " chụp mà không có trong graph: ảnh chụp và kho lệch nhau, chụp lại trước"
            " khi dùng trang này làm bằng chứng.</div>"
        )
    if tk.thieu_truong_mo_ta:
        canh_bao += (
            f'<div class="canh-bao thieu">{tk.thieu_truong_mo_ta} node <b>không có</b>'
            " trường <code>description</code> (khác với có mà rỗng): đó là node hình"
            " dạng khác, ví dụ node vai hyperedge. Quyết định của story 2.4 không nói"
            " gì về chúng.</div>"
        )
    phat_hien = ""
    if tk.mo_ta_rong:
        phat_hien = (
            f'<div class="canh-bao"><b>Phát hiện:</b> {tk.mo_ta_rong}/{tk.tong} entity'
            " có node trong graph mà <code>description</code> là <b>chuỗi rỗng</b>, nên"
            " đường mà ngưỡng L2 canh hiện <b>chưa có gì chảy qua</b>. Đây không phải"
            " một lỗ: story 2.4 chốt để mô tả entity rỗng vì nó chỉ nhân đôi giá trị"
            " slot và mở thêm một mặt rò ở L2; CT-03 là lần đầu quyết định đó được"
            " xác nhận trên dữ liệu thật. Đọc điều này thành &quot;không có rủi"
            " ro&quot; là đọc sai: cơ chế hợp nhất vẫn chạy và đo được ở ba trường"
            " khác của cùng node, và story 2.12 sinh mô tả entity thì mặt rò L2 quay"
            " lại.</div>"
        )
    hang = "".join(_khoi_entity(m) for m in ds)
    return (
        '<!doctype html>\n<html lang="vi"><head><meta charset="utf-8">'
        "<title>CT-03: node entity là điểm hợp nhất đa nguồn</title>"
        f"<style>{_CSS}</style></head><body>"
        '<div class="khoi">'
        "<h1>CT-03 - node entity là điểm hợp nhất đa nguồn</h1>"
        f"<p>Space <b>{html.escape(anh.space)}</b>, ảnh chụp"
        f" {html.escape(anh.ngay_do)}: {anh.so_tai_lieu} tài liệu,"
        f" {anh.so_hyperedge} hyperedge, <b>{tk.tong} entity đa nguồn</b>"
        " (xuất hiện ở hyperedge của từ hai tài liệu trở lên).</p>"
        "<table><tr><th>Đo được trên kho</th><th>Số entity</th></tr>"
        f"<tr><td>Node là điểm hợp nhất đo được (mô tả nhiều mảnh <b>hoặc</b>"
        f" <code>source_id</code> nhiều chunk)</td><td>{tk.gop_da_nguon}/{tk.tong}</td></tr>"
        f"<tr><td><code>description</code> ghép từ nhiều mảnh</td>"
        f"<td>{tk.nhieu_manh}/{tk.tong}</td></tr>"
        f"<tr><td><code>description</code> có mà rỗng</td>"
        f"<td>{tk.mo_ta_rong}/{tk.tong}</td></tr>"
        f"<tr><td><code>description</code> không có trên node</td>"
        f"<td>{tk.thieu_truong_mo_ta}/{tk.tong}</td></tr>"
        f"<tr><td>Khóa quyền hợp nhất thành <b>không khóa</b> (khác scope, AD-5)</td>"
        f"<td>{tk.khong_khoa}/{tk.tong}</td></tr>"
        f"<tr><td>Điền từ hai vai slot trở lên mà chỉ mang <b>một</b>"
        f" <code>entity_type</code></td><td>{tk.nhieu_vai}/{tk.tong}</td></tr>"
        "</table>"
        '<div class="canh-bao">Một tên entity xuất hiện ở hai tài liệu thì graph'
        " chỉ có <b>một</b> node, và mọi trường của node đó là kết quả gộp:"
        " upstream ghép bằng <code>GRAPH_FIELD_SEP.join</code>"
        " (<code>operate.py:181-196</code>), pipeline của dự án gộp khóa quyền bằng"
        " <code>core.keys.hop_nhat_khoa</code> (FR-11, AD-5). Đây là lý do"
        " <code>description</code> của node entity đòi ngưỡng <b>L2</b> chứ không"
        " phải L1 như đường đi tới node (<code>adapters/neo4j.py::_che_mo_ta</code>,"
        " NFR-06 và FR-05). Trang này chạy dưới cờ hệ thống để đọc nguyên văn: nó"
        " là bằng chứng rằng vật liệu cho ca đó <b>có thật trong kho</b>, không"
        " phải một đường truy vấn người dùng.</div>"
        '<p class="chu">Danh sách xếp theo <b>sức nặng của bằng chứng</b>, không'
        " theo thứ tự chữ cái: ca hợp nhất thành không khóa (AD-5) trước, rồi tới"
        " entity có nhiều tài liệu nguồn nhất, rồi tới entity điền nhiều vai nhất;"
        " mốc thời gian và số thuần xuống cuối vì chúng nói hai tài liệu cùng nhắc"
        " một khoảng thời gian chứ không nói hai vùng quyền gặp nhau ở một thực"
        " thể. Không ca nào bị loại khỏi trang.</p>"
        f"{phat_hien}{canh_bao}</div>{hang}</body></html>\n"
    )


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CT-03: node entity là điểm hợp nhất đa nguồn, đọc thuần dưới cờ hệ thống"
    )
    p.add_argument("--space", default="synth", help="không gian dữ liệu (mặc định synth)")
    p.add_argument(
        "--anh",
        type=Path,
        default=None,
        metavar="FILE",
        help=f"ảnh chụp đồ thị (mặc định {DUONG_DAN_ANH_MAC_DINH})",
    )
    p.add_argument(
        "--dich",
        type=Path,
        default=None,
        metavar="FILE",
        help="file HTML đích (mặc định eval/expr/ct03-<space>.html)",
    )
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH, help="bảng chính sách")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Chạy thí nghiệm; mọi cách hỏng có tên đều thành một dòng stderr và mã 1.

    Danh sách bắt gồm cả `PolicyInvalid` và `Neo4jError`: hai thứ này hỏng
    thường nhất trong thực tế (hoán bảng chính sách để thử, hoặc stack chưa lên
    hẳn), và một traceback ở đó là một thông điệp không ai đọc được - trong khi
    mọi lệnh khác của `eval/` đều trả một dòng và mã 1.
    """
    ts = _tham_so(sys.argv[1:] if argv is None else list(argv))
    duong_dan_anh = (
        ts.anh if ts.anh is not None else DUONG_DAN_ANH_MAC_DINH.with_name(f"{ts.space}.json")
    )
    dich = Path(ts.dich) if ts.dich is not None else duong_dan_html(ts.space)
    thieu = thieu_bien_moi_truong()
    if thieu:
        print(
            "thiếu biến môi trường bắt buộc: " + ", ".join(thieu)
            + " - stack compose đã lên chưa? `scripts/chay-may-chu.sh` dựng sẵn đủ bộ",
            file=sys.stderr,
        )
        return 1
    try:
        anh = doc_anh_do_thi(duong_dan_anh)
        ly_do = ly_do_tu_choi_space(ts.space, dich, anh.space)
        if ly_do:
            print(f"{duong_dan_anh}: {ly_do}" if anh.space != ts.space else ly_do, file=sys.stderr)
            return 1
        policy = load_policy(ts.policy)
        cau_hinh = cau_hinh_kho_tu_moi_truong()
        ds = asyncio.run(chay(anh, ts.space, policy.policy_version, cau_hinh))
    except (AnhDoThiKhongHopLe, KhongCoVatLieu, PolicyInvalid) as loi:
        print(str(loi), file=sys.stderr)
        return 1
    except Neo4jError as loi:
        print(f"lỗi Neo4j khi đọc space {ts.space!r}: {loi}", file=sys.stderr)
        return 1

    ds = sap_theo_bang_chung(ds)
    tt = thong_ke(ds)
    try:
        dich.parent.mkdir(parents=True, exist_ok=True)
        dich.write_text(dung_html(anh, ds), encoding="utf-8")
    except OSError as loi:
        print(f"không ghi được {dich}: {loi}", file=sys.stderr)
        return 1

    print(
        f"space {ts.space}: {tt.tong} entity đa nguồn,"
        f" {tt.gop_da_nguon} node là điểm hợp nhất đo được,"
        f" {tt.nhieu_manh} có mô tả nhiều mảnh, {tt.mo_ta_rong} có mô tả rỗng,"
        f" {tt.thieu_truong_mo_ta} không có trường mô tả,"
        f" {tt.khong_khoa} hợp nhất thành không khóa (AD-5),"
        f" {tt.vang_trong_graph} vắng trong graph"
    )
    for m in ds[:10]:
        print(
            f"  {m.entity.ten} <- {list(m.entity.doc_key)}"
            f" ({m.so_chunk_nguon} chunk nguồn, {m.so_manh} mảnh mô tả,"
            f" khóa {m.khoa}, loại {m.loai})"
        )
    if len(ds) > 10:
        print(f"  ... còn {len(ds) - 10} entity, xem trang HTML")
    print(f"ghi {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
