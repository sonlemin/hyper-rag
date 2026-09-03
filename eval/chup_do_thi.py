"""Chụp ảnh đồ thị một space thành file JSON có commit (story 2.9).

    HYPER_RAG_MODULE=eval.chup_do_thi scripts/chay-may-chu.sh chup --space synth

Nhãn truy hồi vàng của Đo 3 gán tay theo *id hyperedge*, mà id chỉ sống trong
Neo4j trên máy chủ. Gán nhãn thẳng vào một kho đang chạy là gán vào một thứ
không ai đọc lại được từ repo: người chấm sau, hội đồng, và chính bộ test đều
không có cách kiểm nhãn còn đúng hay không. Nên bước đầu tiên là chụp đồ thị
thành một file, rồi nhãn đứng trên ảnh chụp đó.

Ba nguồn hợp lại thành một mục ảnh chụp:

- **Sổ tài liệu** (`so_tai_lieu_{space}.json` trong `HYPER_RAG_WORKING_DIR`) nói
  hyperedge nào đến từ tài liệu nào. Graph không giữ `doc_key`, nó chỉ giữ
  `source_id` mức chunk, nên sổ là nguồn duy nhất của chiều này - và cũng là
  chỗ ca "một fact ở hai tài liệu" đếm được.
- **`slot_cua_hyperedge`** của adapter Neo4j trả `{vai: [id entity]}` cho từng
  hyperedge. Node hyperedge không mang giá trị slot nào, giá trị sống ở entity
  và cạnh, nên đọc cạnh là cách duy nhất lắp fact lại thành thứ người soát nhãn
  đọc được.
- **`khoa_hien_co`** trả khóa lọc của node. `null` là ca hợp nhất khác scope
  (AD-5): node ở lại nhưng không vai nào chạm tới. Nó phải vào ảnh chụp chứ
  không bị bỏ, vì trần lý thuyết của Đo 3 tính đúng bằng những ca đó.

**Đọc thuần.** Không `initialize()` (nó dựng ràng buộc, tức ghi), không nạp,
không xóa. Đây là script `eval/` đầu tiên chạm kho thật, nên nó chỉ được phép
đọc; mọi đường ghi vẫn đi qua `api/`.

Chạy dưới cờ ngữ cảnh hệ thống: hai method trên đều đòi cờ đó
(`bat_buoc_ngu_canh_he_thong`) vì chúng trả nội dung và bỏ mệnh đề lọc. Đây là
một harness đo chạy ngoài tiến trình phục vụ, cùng hạng với pipeline ingest,
không phải một đường truy vấn người dùng - `tests/test_import_lint.py` giữ danh
sách trắng đúng một dòng cho file này.

Không gọi LLM, không tốn tiền API.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from adapters.engine import BIEN_MOI_TRUONG, cau_hinh_kho_tu_moi_truong
from adapters.ingest import SoTaiLieu
from adapters.kv import WORKING_DIR_KEY
from adapters.neo4j import NEO4J_PASSWORD_KEY, NEO4J_URI_KEY, Neo4jACLGraphStorage
from adapters.policy_loader import load_policy
from core.audit import thoi_diem_utc
from core.keys import CHUA_GHI
from core.permission import use_context
from core.slots import SLOT_ROLES
from core.system_context import system_context
from eval.cau_hoi import (
    DUONG_DAN_ANH_MAC_DINH,
    VERSION_HO_TRO,
    AnhDoThiRong,
    doc_anh_do_thi,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-toi-gian.yaml"

# Namespace graph của upstream; cùng chuỗi mà `EngineACL` truyền xuống adapter.
NAMESPACE_GRAPH: str = "chunk_entity_relation"

# Ba biến môi trường không có mặc định nào an toàn. Thiếu chúng thì lỗi nổ ở
# tầng driver ("không phân giải được tên máy") hoặc ở tầng file ("không có sổ
# tài liệu"), hai thông điệp nói sai nguyên nhân. `scripts/chay-may-chu.sh`
# dựng sẵn đủ bộ này từ IP container.
BIEN_BAT_BUOC: tuple[str, ...] = (
    BIEN_MOI_TRUONG[NEO4J_URI_KEY],
    BIEN_MOI_TRUONG[NEO4J_PASSWORD_KEY],
    BIEN_MOI_TRUONG[WORKING_DIR_KEY],
)


def thieu_bien_moi_truong(moi_truong=None) -> list[str]:
    """Tên các biến bắt buộc chưa đặt (rỗng tính là chưa đặt), giữ thứ tự khai."""
    nguon = os.environ if moi_truong is None else moi_truong
    return [ten for ten in BIEN_BAT_BUOC if not str(nguon.get(ten) or "").strip()]


def dung_anh(
    *,
    space: str,
    ngay_do: str,
    doc_key_theo_id,
    slots_theo_id,
    khoa_theo_id,
) -> dict:
    """Ghép ba nguồn thành đúng hình dạng file ảnh chụp. Hàm thuần, không I/O.

    Tách khỏi phần chạm kho để bộ test canh được hình dạng file mà không cần
    Neo4j: hình dạng này là hợp đồng của nhãn tay, và nó phải có test riêng.

    Sắp xếp mọi thứ (id, `doc_key`, id entity trong từng vai, thứ tự vai theo
    `SLOT_ROLES`) để hai lần chụp trên cùng một kho cho **cùng một file**: một
    ảnh chụp đổi thứ tự mỗi lần chạy là một diff git vô nghĩa, và người soát
    không đọc được cái gì đã thật sự đổi.
    """
    hyperedge = []
    for id_he in sorted(doc_key_theo_id):
        slots = slots_theo_id.get(id_he) or {}
        hyperedge.append(
            {
                "id": id_he,
                "doc_key": sorted(doc_key_theo_id[id_he]),
                "khoa": khoa_theo_id.get(id_he),
                "slots": {vai: sorted(slots[vai]) for vai in SLOT_ROLES if slots.get(vai)},
            }
        )
    if not hyperedge:
        raise AnhDoThiRong(
            f"space {space!r} không có hyperedge nào (0 mục trong sổ tài liệu):"
            " chưa nạp gì thì không có gì để chụp, và một ảnh chụp rỗng ghi đè"
            " lên ảnh cũ là mất nguồn chuẩn của mọi id trong nhãn truy hồi vàng"
        )
    return {
        "version": VERSION_HO_TRO,
        "space": space,
        "ngay_do": ngay_do,
        "so_hyperedge": len(hyperedge),
        "so_hyperedge_da_nguon": sum(1 for h in hyperedge if len(h["doc_key"]) > 1),
        "hyperedge": hyperedge,
    }


def doc_so_tai_lieu(working_dir, space: str) -> tuple[dict[str, set[str]], list[str]]:
    """`{id hyperedge: {doc_key}}` cộng danh sách `doc_key` đã đọc, từ sổ tài liệu."""
    so = SoTaiLieu.mo(working_dir, space)
    theo_id: dict[str, set[str]] = {}
    doc_keys = so.cac_doc_key()
    for doc_key in doc_keys:
        muc = so.muc(doc_key)
        for id_he in muc.hyperedge:
            theo_id.setdefault(id_he, set()).add(doc_key)
    return theo_id, doc_keys


async def chup(space: str, policy_version: str, cau_hinh: dict) -> dict:
    """Đọc graph rồi trả dict ảnh chụp; đóng driver dù hỏng ở đâu."""
    working_dir = cau_hinh[WORKING_DIR_KEY]
    doc_key_theo_id, doc_keys = doc_so_tai_lieu(working_dir, space)
    ids = sorted(doc_key_theo_id)

    graph = Neo4jACLGraphStorage(
        namespace=NAMESPACE_GRAPH, global_config=cau_hinh, embedding_func=None
    )
    try:
        with use_context(system_context(space=space, policy_version=policy_version)):
            khoa_tho = await graph.khoa_hien_co(ids)
            slots_theo_id = {i: await graph.slot_cua_hyperedge(i) for i in ids}
    finally:
        await graph.close()

    vang_khoi_graph = [i for i in ids if khoa_tho.get(i) is CHUA_GHI]
    if vang_khoi_graph:
        # Sổ nói có, graph nói không: hoặc một đợt nạp chết giữa chừng, hoặc
        # sổ và kho không cùng một `HYPER_RAG_WORKING_DIR`. Cả hai đều làm nhãn
        # trỏ vào chỗ trống, nên nói ra ngay chứ không ghi một ảnh chụp thiếu.
        print(
            f"CẢNH BÁO: {len(vang_khoi_graph)} hyperedge có trong sổ tài liệu mà"
            f" không có trong graph: {vang_khoi_graph[:5]}",
            file=sys.stderr,
        )
    khoa_theo_id = {i: (None if khoa_tho.get(i) is CHUA_GHI else khoa_tho.get(i)) for i in ids}

    print(f"{len(doc_keys)} tài liệu trong sổ, {len(ids)} hyperedge")
    return dung_anh(
        space=space,
        ngay_do=thoi_diem_utc(),
        doc_key_theo_id=doc_key_theo_id,
        slots_theo_id=slots_theo_id,
        khoa_theo_id=khoa_theo_id,
    )


def ghi_anh(dich: Path, anh: dict) -> Path:
    """Ghi ảnh chụp, `indent=2` và `ensure_ascii=False` để diff git đọc được."""
    dich = Path(dich)
    dich.parent.mkdir(parents=True, exist_ok=True)
    dich.write_text(json.dumps(anh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dich


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Chụp ảnh đồ thị một space thành file JSON có commit (đọc thuần)"
    )
    p.add_argument("--space", default="synth", help="không gian dữ liệu (mặc định synth)")
    p.add_argument(
        "--dich",
        type=Path,
        default=None,
        metavar="FILE",
        help=f"file ảnh chụp (mặc định {DUONG_DAN_ANH_MAC_DINH.name} theo space)",
    )
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH, help="bảng chính sách")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ts = _tham_so(sys.argv[1:] if argv is None else list(argv))
    thieu = thieu_bien_moi_truong()
    if thieu:
        print(
            "thiếu biến môi trường bắt buộc: " + ", ".join(thieu)
            + " - stack compose đã lên chưa? `scripts/chay-may-chu.sh` dựng sẵn đủ bộ",
            file=sys.stderr,
        )
        return 1
    dich = ts.dich or DUONG_DAN_ANH_MAC_DINH.with_name(f"{ts.space}.json")
    policy = load_policy(ts.policy)
    cau_hinh = cau_hinh_kho_tu_moi_truong()
    try:
        anh = asyncio.run(chup(ts.space, policy.policy_version, cau_hinh))
    except AnhDoThiRong as loi:
        print(str(loi), file=sys.stderr)
        return 1
    ghi_anh(dich, anh)
    # Đọc lại bằng chính loader mà nhãn dùng: một file ghi ra mà loader từ chối
    # là một file không dùng được, và biết điều đó ngay tại đây rẻ hơn nhiều so
    # với biết nó lúc CI đỏ trên máy dev.
    da_doc = doc_anh_do_thi(dich)
    print(
        f"{da_doc.so_hyperedge} hyperedge, {len(da_doc.da_nguon())} đa nguồn,"
        f" {sum(1 for h in da_doc.hyperedge if h.khoa is None)} không khóa"
    )
    print(f"ghi {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
