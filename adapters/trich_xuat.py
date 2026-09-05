"""Trích xuất fact 8 vai slot tiếng Việt: một lời gọi LLM mỗi chunk, ghi ba kho (story 2.4).

Thay `extract_entities` của upstream trên đường nạp của `EngineACL.ainsert`.
Upstream trích "entity + hyper-relation" bằng prompt tiếng Anh dạng tuple, có
gleaning nhiều lượt, và tên hyperedge là nguyên văn câu fact. Bản này:

- **Prompt tiếng Việt, đầu ra JSON theo lược đồ `core/facts.py`.** Tên vai lấy
  từ `core.slots.SLOT_ROLES`, nhãn từ `core.facts.TEN_VAI_TIENG_VIET`; không
  có bảng tên vai thứ hai. Prompt chứa chữ "json" và một ví dụ đầu ra vì JSON
  mode của DeepSeek đòi thế.
- **Đúng một lời gọi mỗi chunk**: `temperature=0`, `response_format`
  json_object, `max_tokens` hữu hạn. Không gleaning, không lượt tự kiểm - đó là
  knob của story 2.6 khi có bộ vàng để đo. Tắt suy luận của provider đi bằng
  `extra_body` trong danh mục model, không phải ở đây.
- **Bản ghi sai lược đồ bị loại và đếm theo mã** (`ThongKeTrichXuat`), pipeline
  phát sự kiện `extract_doc` từ số này. Không loại thầm lặng.
- **Hyperedge là nhãn mờ** `core.facts.id_fact(slots)`: id node graph, payload
  `hyperedge_name` và nội dung tới LLM đều là id đó; `content` nhúng là câu
  render `cau_fact`. Entity là giá trị slot (`normalize_id`), `description`
  rỗng, `entity_type` là vai *phổ biến nhất* của entity qua các fact đã nạp
  (luật `Counter` của `_merge_nodes_then_upsert` upstream) - một nhãn hiển thị
  cho bảng Entities, **không** phải tập vai và không dùng để suy luật che; luật
  che đọc vai ở từng cạnh. Mỗi (hyperedge, entity, vai) là một cạnh mang `slot`.

Phần gộp node dùng lại `_merge_hyperedges_then_upsert` và
`_merge_nodes_then_upsert` của `hypergraphrag.operate` (import, không chép):
chúng đọc node cũ dưới cờ system rồi cộng weight / hợp `source_id` / gộp
`description`, đúng luật mà pipeline re-ingest (2.3) đã dựa vào. Cạnh thì có
hàm riêng vì `_merge_edges_then_upsert` của upstream không biết `slot`.

**Weight và `source_id` của cạnh lấy từ node hyperedge đã gộp.** Id hyperedge
là băm của tập slot, nên tập cạnh của một hyperedge được quyết bởi chính id:
mọi cạnh của nó xuất hiện đúng ở những chunk mà hyperedge xuất hiện. Vì thế
`weight`/`source_id` của từng cạnh bằng của hyperedge sau gộp, không cần đọc
lại cạnh cũ - và `get_edge` (gộp theo cặp) không cần trả từng cạnh một.

Thứ tự ghi: graph (hyperedge, entity, cạnh) trước, vector sau - node graph là
kho nhớ được trạng thái không khóa (2.1/2.3), và cạnh cần hai đầu có sẵn.
"""

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Mapping

from hypergraphrag.operate import (
    _merge_hyperedges_then_upsert,
    _merge_nodes_then_upsert,
)
from hypergraphrag.utils import compute_mdhash_id

from adapters.neo4j import SLOT_FIELD
from adapters.thu_lai import goi_co_thu_lai
from core.facts import (
    GIA_TRI_TOI_DA,
    KHOA_FACTS,
    TEN_VAI_TIENG_VIET,
    cau_fact,
    id_fact,
    phan_tich_phan_hoi,
)
from core.ids import normalize_id
from core.slots import SLOT_ROLES

logger = logging.getLogger(__name__)


def _in_thu_lai(thong_diep: str, **_) -> None:
    """Dòng "đang thử lại" của đường nạp đi vào log, không ra stdout.

    Đường nạp chạy trong container (`api/man_nap.py`) cũng như trên CLI; một
    `print` ở tầng adapter thì màn nạp web không thấy được và CLI thì trộn nó
    vào bảng số. `WARNING` vì một lần thử lại là chuyện đáng đọc lại sau đợt.
    """
    logger.warning("%s", thong_diep.strip())

# Tham số của *mọi* lời gọi trích xuất. Đi thẳng vào kwargs của hàm LLM đã bọc:
# OpenAI/DeepSeek nhận nguyên, Ollama dịch qua `_kwargs_ollama`.
THAM_SO_LLM: Mapping[str, object] = {
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "max_tokens": 8192,
}

# Gợi ý cho LLM về từng vai, khóa đúng bằng danh mục (test canh). Nhãn ngắn
# nằm ở `core.facts.TEN_VAI_TIENG_VIET`; đây là phần diễn giải chỉ prompt cần.
GOI_Y_VAI: Mapping[str, str] = {
    "subject": "hệ thống, dịch vụ, tài khoản, quy trình hay đối tượng mà fact nói về",
    "symptom": "hiện tượng quan sát được (lỗi, cảnh báo, hành vi bất thường)",
    "cause": "nguyên nhân gốc được nêu trong văn bản",
    "condition": "điều kiện, ngữ cảnh hay ngưỡng để fact áp dụng",
    "remediation": "hành động xử lý, khắc phục hay quy định phải làm",
    "source": "tài liệu, SOP, ticket hay hệ thống được dẫn làm nguồn",
    "time": "thời điểm, khoảng thời gian hay tần suất",
    "owner": "người hoặc nhóm chịu trách nhiệm",
}

# Chỗ chèn chunk. Dùng `replace` thay `str.format` vì cả prompt lẫn văn bản
# nguồn đều có dấu ngoặc nhọn (JSON, mã cấu hình).
_CHO_VAN_BAN: str = "<<VAN_BAN>>"

# Ví dụ đầu ra. Mọi giá trị slot ở đây phải là **đoạn có thật, nguyên văn**
# trong thân `eval/data/01-cap-quyen-gitlab.txt` hoặc
# `eval/data/05-bao-cao-su-co-inc-1208.txt` (test `test_trich_xuat.py` canh):
# prompt dạy "trích sát văn bản" nhưng ví dụ mạnh hơn lời dặn, nên một ví dụ
# viết lại câu dạy LLM chuẩn hóa lại chữ - và bản chuẩn hóa đó không còn khớp
# nổi nhãn vàng, thứ bị luật nạp 2.5 ép phải trích sát thân tài liệu. Story 2.6
# đo được chuyện đó ở vai `time`: prompt cũ ghi "2026-08-12 09:20" trong khi
# tài liệu viết "12/08/2026 lúc 09:20". Hai tài liệu trên vì thế là few-shot và
# bị loại khỏi mẫu số của R2 (PRD 2.6); đổi ví dụ sang tài liệu khác là đổi cả
# cờ `few_shot` của bộ vàng.
VI_DU_DAU_RA: str = json.dumps(
    {
        KHOA_FACTS: [
            {
                "subject": "App01",
                "symptom": "trang thanh toán của App01 trả lỗi 502",
                "cause": "chỉnh sai giới hạn bộ nhớ của pool PHP-FPM",
                "time": "12/08/2026 lúc 09:20",
                "remediation": "trả giới hạn bộ nhớ PHP-FPM về mức cũ",
                "owner": "Trần Thị Hạnh",
            },
            {"subject": "tài khoản GitLab", "condition": "không hoạt động 90 ngày", "remediation": "khóa tự động"},
        ]
    },
    ensure_ascii=False,
    indent=2,
)

_DANH_MUC_VAI: str = "\n".join(
    f'- "{vai}" ({TEN_VAI_TIENG_VIET[vai]}): {GOI_Y_VAI[vai]}' for vai in SLOT_ROLES
)

PROMPT_TRICH_XUAT: str = f"""Bạn là bộ trích xuất tri thức vận hành IT nội bộ. Đọc đoạn văn bản tiếng Việt ở cuối và liệt kê mọi fact trong đó thành JSON.

Mỗi fact là một object; khóa của object chỉ được lấy từ đúng 8 vai sau, giữ nguyên tên khóa tiếng Anh:
{_DANH_MUC_VAI}

Luật:
- Mỗi fact bắt buộc có "subject" và ít nhất một vai khác. Quan hệ hai ngôi là một fact hai vai.
- Chỉ ghi vai có thông tin trong văn bản. Vai không có thì bỏ hẳn khóa, không ghi null, không ghi chuỗi rỗng.
- Giá trị là chuỗi ngắn (tối đa {GIA_TRI_TOI_DA} ký tự), trích sát văn bản, không suy diễn, không thêm lời giải thích.
- Tách thành nhiều fact khi văn bản nói về nhiều chủ thể hoặc nhiều tình huống khác nhau.
- Không có fact nào thì trả {{"{KHOA_FACTS}": []}}.

Đầu ra là một object json duy nhất dạng {{"{KHOA_FACTS}": [...]}}, không có văn bản nào khác ngoài JSON.

Ví dụ đầu ra:
{VI_DU_DAU_RA}

Văn bản:
{_CHO_VAN_BAN}
"""


def dung_prompt(van_ban: str) -> str:
    """Prompt cho một chunk: nhét nguyên văn chunk vào chỗ chèn."""
    return PROMPT_TRICH_XUAT.replace(_CHO_VAN_BAN, van_ban)


@dataclass
class ThongKeTrichXuat:
    """Kết quả trích xuất một tài liệu, đếm được (FR-02).

    `so_loai` là số *fact* bị loại; chunk hỏng (`so_chunk_hong`) không có bản
    ghi để đếm vào đó nhưng vẫn có mã trong `loai_theo_ma`. `ty_le_loai` là
    tỉ số fact loại trên fact thô.
    """

    so_chunk: int = 0
    so_chunk_hong: int = 0
    so_fact_tho: int = 0
    so_hop_le: int = 0
    so_loai: int = 0
    # Bản ghi hợp lệ trùng `id_fact` với một bản ghi khác *trong cùng chunk*:
    # vẫn đếm vào `so_hop_le` (LLM đã trả nó) nhưng chỉ góp weight một lần.
    so_trung_trong_chunk: int = 0
    loai_theo_ma: dict[str, int] = field(default_factory=dict)

    @property
    def ty_le_loai(self) -> float:
        return self.so_loai / self.so_fact_tho if self.so_fact_tho else 0.0

    def chi_tiet(self) -> dict:
        """Phần số liệu cho `chi_tiet` của sự kiện `extract_doc`."""
        return {
            "so_chunk": self.so_chunk,
            "so_chunk_hong": self.so_chunk_hong,
            "so_fact_tho": self.so_fact_tho,
            "so_hop_le": self.so_hop_le,
            "so_loai": self.so_loai,
            "so_trung_trong_chunk": self.so_trung_trong_chunk,
            "loai_theo_ma": dict(sorted(self.loai_theo_ma.items())),
            "ty_le_loai": self.ty_le_loai,
        }

    def _cong(self, kq) -> None:
        self.so_chunk += 1
        self.so_chunk_hong += int(kq.chunk_hong)
        self.so_fact_tho += kq.so_ban_ghi
        self.so_hop_le += len(kq.facts)
        for ma, n in kq.loai_theo_ma.items():
            self.loai_theo_ma[ma] = self.loai_theo_ma.get(ma, 0) + n
        self.so_loai = self.so_fact_tho - self.so_hop_le


async def _trich_mot_chunk(use_llm_func, chunk_key: str, chunk: dict):
    """Một lời gọi LLM cho một chunk, rồi đọc phản hồi theo lược đồ.

    **Đây là lớp thử lại duy nhất của đường nạp phía LLM** (story 2.13). Đơn vị
    thử lại bằng đúng đơn vị lời gọi: một 429 trên chunk thứ 12 thử lại chunk
    thứ 12, không thử lại cả tài liệu (trả tiền lại cho 11 chunk đã xong) và
    không nhân lên ở `bo_llm` (4x4 = 16 lần thử, kéo dài chính cửa sổ chặn nhịp).

    `TaskGroup` ở `trich_xuat_chunks` giữ nguyên nghĩa: chỉ khi cả bốn lần thử
    đều hỏng thì lỗi mới dội ra ngoài và hủy các chunk anh em.
    """
    van_ban = await goi_co_thu_lai(
        use_llm_func,
        dung_prompt(chunk["content"]),
        _ten=f"chunk {chunk_key}",
        _in_ra=_in_thu_lai,
        **THAM_SO_LLM,
    )
    return chunk_key, phan_tich_phan_hoi(van_ban)


async def _ghi_canh_slot(graph, he_id: str, entity_id: str, slot: str, node_he: dict) -> None:
    """Một cạnh (hyperedge, entity, vai) mang weight/source_id của hyperedge đã gộp.

    Lý do lấy từ node hyperedge thay vì đọc lại cạnh: docstring đầu file.
    """
    await graph.upsert_edge(
        he_id,
        entity_id,
        edge_data={
            "weight": node_he["weight"],
            "source_id": node_he["source_id"],
            SLOT_FIELD: slot,
        },
    )


async def trich_xuat_chunks(
    chunks: dict[str, dict],
    graph,
    entity_vdb,
    hyperedge_vdb,
    global_config: dict,
) -> ThongKeTrichXuat:
    """Trích fact từ mọi chunk (LLM song song), gom theo id, ghi graph rồi hai collection.

    Trả `ThongKeTrichXuat` kể cả khi không có fact hợp lệ nào; khi đó không ghi
    gì và nơi gọi (`EngineACL.ainsert`) quyết định dừng sớm. Chunk hỏng hay bản
    ghi sai lược đồ không làm lời gọi nổ - chúng được đếm.
    """
    use_llm_func = global_config["llm_model_func"]
    thong_ke = ThongKeTrichXuat()
    # `TaskGroup` chứ không `gather`: một lời gọi hỏng (429, key sai) hủy các
    # lời gọi anh em thay vì để chúng chạy hết rồi mới báo - mỗi lời gọi là
    # tiền thật. Lỗi đầu tiên dội lên nguyên dạng để pipeline đọc `code`.
    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_trich_mot_chunk(use_llm_func, k, c)) for k, c in sorted(chunks.items())]
    except ExceptionGroup as nhom:
        raise nhom.exceptions[0] from nhom
    ket_qua = [t.result() for t in tasks]

    # Gom theo id fact: hyperedge -> bản ghi từng lần xuất hiện; entity -> vai
    # theo từng lần điền; cạnh -> tập (he, entity, vai).
    slot_cua_he: dict[str, dict[str, str]] = {}
    ban_ghi_he: dict[str, list[dict]] = defaultdict(list)
    ban_ghi_entity: dict[str, list[dict]] = defaultdict(list)
    canh: set[tuple[str, str, str]] = set()
    for chunk_key, kq in ket_qua:
        thong_ke._cong(kq)
        da_thay_trong_chunk: set[str] = set()
        for slots in kq.facts:
            he_id = id_fact(slots)
            slot_cua_he.setdefault(he_id, slots)
            # Cùng fact lặp trong một chunk góp weight đúng một lần (một lần
            # xuất hiện trong chunk đó); lặp qua *hai* chunk thì mỗi chunk một.
            if he_id in da_thay_trong_chunk:
                thong_ke.so_trung_trong_chunk += 1
            else:
                da_thay_trong_chunk.add(he_id)
                ban_ghi_he[he_id].append({"weight": 1.0, "source_id": chunk_key})
            for vai, gia_tri in slots.items():
                entity_id = normalize_id(gia_tri)
                ban_ghi_entity[entity_id].append(
                    {"entity_type": vai, "description": "", "source_id": chunk_key}
                )
                canh.add((he_id, entity_id, vai))

    if not slot_cua_he:
        logger.warning(
            "trích xuất: %d chunk, %d chunk hỏng, %d bản ghi thô, 0 fact hợp lệ (%s)",
            thong_ke.so_chunk,
            thong_ke.so_chunk_hong,
            thong_ke.so_fact_tho,
            dict(sorted(thong_ke.loai_theo_ma.items())) or "không có gì bị loại",
        )
        return thong_ke

    # Graph: hyperedge, entity, rồi cạnh (cạnh cần hai đầu có sẵn).
    node_he: dict[str, dict] = {}
    for he_id in sorted(ban_ghi_he):
        node_he[he_id] = await _merge_hyperedges_then_upsert(he_id, ban_ghi_he[he_id], graph, global_config)
    node_entity: dict[str, dict] = {}
    for entity_id in sorted(ban_ghi_entity):
        node_entity[entity_id] = await _merge_nodes_then_upsert(
            entity_id, ban_ghi_entity[entity_id], graph, global_config
        )
    for he_id, entity_id, vai in sorted(canh):
        await _ghi_canh_slot(graph, he_id, entity_id, vai, node_he[he_id])

    # Vector: cùng hình dạng `operate.py:461-479`, chỉ khác nội dung nhúng.
    await hyperedge_vdb.upsert(
        {
            compute_mdhash_id(he_id, prefix="rel-"): {
                "content": cau_fact(slot_cua_he[he_id]),
                "hyperedge_name": he_id,
            }
            for he_id in sorted(node_he)
        }
    )
    await entity_vdb.upsert(
        {
            compute_mdhash_id(entity_id, prefix="ent-"): {
                "content": entity_id,
                "entity_name": entity_id,
            }
            for entity_id in sorted(node_entity)
        }
    )
    logger.info(
        "trích xuất: %d chunk, %d fact hợp lệ / %d thô, %d hyperedge, %d entity, %d cạnh",
        thong_ke.so_chunk,
        thong_ke.so_hop_le,
        thong_ke.so_fact_tho,
        len(node_he),
        len(node_entity),
        len(canh),
    )
    return thong_ke
