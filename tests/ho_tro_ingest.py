"""Đồ nghề cho bộ test pipeline ingest (story 2.3, đổi sang fact 8 vai ở 2.4).

Ba thứ ở đây:

- `viet_tai_lieu` ghi một file nguồn có frontmatter vào thư mục tạm;
- `llm_theo_fact` dựng `LLMGia` trả lời *xác định* theo chunk: bảng
  `{đoạn văn trong thân tài liệu: [slots_dict, ...]}`. Prompt trích xuất của
  dự án (`adapters/trich_xuat.py`) nhét nguyên văn chunk vào, nên tìm đoạn văn
  trong prompt là đủ để biết đang trích chunk nào; câu trả lời là JSON
  `{"facts": [...]}` đúng lược đồ mà `core/facts.py` đọc. Prompt không khớp
  đoạn nào là prompt của đường truy vấn (trích từ khóa), trả phản hồi từ khóa
  của `LLMGia` như cũ;
- vài hàm đọc thô hai kho giả để chấm: node theo vai, point theo collection.

Từ story 2.4 id node hyperedge là nhãn mờ `core.facts.id_fact(slots)` và id
node entity là chính giá trị slot đã `normalize_id` (không upper-case, không
nháy). Bốn hàm `ten_*`/`id_vector_*` là bản ghi lại của đúng hai luật đó để
test khỏi viết tay ở từng chỗ.
"""

import json
from pathlib import Path

from hypergraphrag.prompt import GRAPH_FIELD_SEP
from hypergraphrag.utils import compute_mdhash_id

from core.facts import id_fact
from core.ids import normalize_id, point_id
from tests.gia_lap_llm import (
    MODEL_EMBEDDING_CUC_BO_GIA,
    MODEL_LLM_CUC_BO_GIA,
    NCC_CUC_BO_GIA,
    EmbeddingGia,
    LLMGia,
    NhaCungCapGia,
    SoAuditBoNho,
    phan_hoi_tu_khoa,
)
from tests.gia_lap_neo4j import Neo4jGhiLai
from tests.gia_lap_qdrant import QdrantGhiLai
from tests.ho_tro_m1 import dung_engine

SEP = GRAPH_FIELD_SEP

# Phản hồi "chunk không có fact" đúng lược đồ: dùng làm `mac_dinh` khi test cần
# một chunk trả 0 bản ghi hợp lệ.
KHONG_FACT: str = json.dumps({"facts": []})


def viet_tai_lieu(thu_muc: Path, ten: str, *, scope: str, content_type: str, than: str) -> Path:
    """Một file nguồn có frontmatter; trả đường dẫn."""
    thu_muc.mkdir(parents=True, exist_ok=True)
    f = thu_muc / ten
    f.write_text(
        f"---\nscope: {scope}\ncontent_type: {content_type}\n---\n{than}\n",
        encoding="utf-8",
    )
    return f


def phan_hoi_fact(cac_fact: list) -> str:
    """JSON `{"facts": [...]}` cho một chunk; phần tử giữ nguyên để test nhét bản ghi sai lược đồ."""
    return json.dumps({"facts": list(cac_fact)}, ensure_ascii=False)


def llm_theo_fact(bang: dict[str, list], mac_dinh: str | None = None) -> LLMGia:
    """LLM giả: chunk chứa đoạn văn nào thì trả đúng tập fact (JSON) của đoạn đó.

    Prompt không khớp đoạn nào thì trả `mac_dinh`; mặc định là phản hồi từ khóa
    của `LLMGia` (cho đường truy vấn). Muốn dựng ca "chunk không có fact" thì
    truyền `mac_dinh=KHONG_FACT`; ca "chunk không parse được" thì truyền một
    chuỗi không phải JSON.
    """

    def theo_prompt(prompt: str) -> str:
        for doan, cac_fact in bang.items():
            if doan in prompt:
                return cac_fact if isinstance(cac_fact, str) else phan_hoi_fact(cac_fact)
        return phan_hoi_tu_khoa() if mac_dinh is None else mac_dinh

    return LLMGia(theo_prompt=theo_prompt)


def ten_entity(gia_tri: str) -> str:
    """Id node graph của một entity: chính giá trị slot đã chuẩn hóa."""
    return normalize_id(gia_tri)


def ten_hyperedge(slots: dict) -> str:
    """Id node graph của một hyperedge: nhãn mờ `he-<băm slot>`."""
    return id_fact(slots)


def id_vector_entity(gia_tri: str) -> str:
    return compute_mdhash_id(ten_entity(gia_tri), prefix="ent-")


def id_vector_hyperedge(slots: dict) -> str:
    return compute_mdhash_id(ten_hyperedge(slots), prefix="rel-")


def id_chunk(than: str) -> str:
    """Id chunk của upstream cho một tài liệu vừa một chunk (md5 nội dung đã strip)."""
    return compute_mdhash_id(than.strip(), prefix="chunk-")


class MoiTruong:
    """Engine cộng hai kho giả và sổ audit, giữ lại để test chọc thẳng vào kho."""

    def __init__(self, engine, client, driver, llm, so_audit):
        self.engine = engine
        self.client = client
        self.driver = driver
        self.llm = llm
        self.so_audit = so_audit

    # --- đọc thô kho giả ----------------------------------------------------

    def node(self, space: str, id_node: str):
        return self.driver.nodes.get((space, id_node))

    def cac_node_vai(self, space: str, vai: str) -> dict[str, dict]:
        return {
            id_node: dict(n.props)
            for (sp, id_node), n in self.driver.nodes.items()
            if sp == space and n.props.get("role") == vai
        }

    def canh_cua(self, space: str, id_node: str) -> list:
        return [c for c in self.driver.canh if c.space == space and id_node in (c.src, c.tgt)]

    async def points(self, space: str, namespace: str) -> dict[str, dict]:
        """`point_id -> payload` của mọi point trong collection."""
        ten = f"{space}_{namespace}"
        if not await self.client._that.collection_exists(collection_name=ten):
            return {}
        diem, _ = await self.client._that.scroll(collection_name=ten, limit=1000, with_payload=True)
        return {str(d.id): dict(d.payload or {}) for d in diem}

    async def co_point(self, space: str, namespace: str, id_upstream: str) -> bool:
        return point_id(id_upstream) in await self.points(space, namespace)

    def kv(self, namespace: str, space: str) -> dict:
        kho = self.engine.text_chunks if namespace == "text_chunks" else self.engine.full_docs
        return kho._du_lieu(space)

    def van_ban_da_nhung(self) -> list[str]:
        """Mọi văn bản đã đi qua provider embedding giả, theo thứ tự gọi."""
        from adapters.llm_wrapper import nha_cung_cap_cua

        ncc = nha_cung_cap_cua(self.engine.embedding_func)
        return [t for _, texts in ncc.loi_goi for t in texts]


def dung_moi_truong(workspace_dir, llm: LLMGia, **them) -> MoiTruong:
    """Engine cổng M1 với LLM giả theo fact."""
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    so_audit = SoAuditBoNho()
    engine = dung_engine(workspace_dir, client, driver, llm, so_audit=so_audit, **them)
    return MoiTruong(engine, client, driver, llm, so_audit)


def dung_moi_truong_cuc_bo(workspace_dir, llm: LLMGia, *, llm_san_sang=True, emb_san_sang=True) -> MoiTruong:
    """Engine với hai provider *cục bộ* giả, cho ca space `real`.

    Ca "provider API ngoài trên space real" dùng `dung_moi_truong` thường: hai
    provider giả mặc định của nó khai `cuc_bo=False`.
    """
    client = QdrantGhiLai()
    driver = Neo4jGhiLai()
    so_audit = SoAuditBoNho()
    ncc_llm = NhaCungCapGia(llm, ten=NCC_CUC_BO_GIA, cuc_bo=True, san_sang=llm_san_sang)
    ncc_emb = EmbeddingGia(ten=NCC_CUC_BO_GIA, cuc_bo=True, san_sang=emb_san_sang)
    engine = dung_engine(
        workspace_dir,
        client,
        driver,
        llm,
        so_audit=so_audit,
        ncc_llm=ncc_llm,
        ncc_embedding=ncc_emb,
        model_llm=MODEL_LLM_CUC_BO_GIA,
        model_embedding=MODEL_EMBEDDING_CUC_BO_GIA,
    )
    return MoiTruong(engine, client, driver, llm, so_audit)
