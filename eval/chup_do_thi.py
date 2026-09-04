"""Chụp ảnh đồ thị một space thành file JSON có commit (story 2.9).

    HYPER_RAG_MODULE=eval.chup_do_thi scripts/chay-may-chu.sh chup --space synth
    HYPER_RAG_MODULE=eval.chup_do_thi scripts/chay-may-chu.sh chup --space synth --ghi-de

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

**Ba rào ở phía ghi file**, vì ảnh chụp là file có commit và là neo của mọi id
trong nhãn truy hồi vàng: chỉ space trong `SPACE_GHI_TRONG_REPO` được ghi vào
cây repo ở dạng **đầy đủ** (dữ liệu thật phải `--dich` ra ngoài, hoặc `--rut-gon`
vào trong); file đã có thì đòi `--ghi-de` và bản cũ giữ thành `.bak.json`; và
loader phải nhận file **trước khi** nó thay bản cũ, không phải sau.

`--rut-gon` (story 2.11) ghi một bản **không mang giá trị nào**: mọi id entity
và `doc_key` thay bằng băm có muối, giữ khóa lọc, nhãn quyền và quan hệ bằng
nhau giữa các id. Đó là dạng duy nhất của space dữ liệu thật đi vào repo được,
và là chỗ đứng để `tests/test_ty_le_n_ngoi.py` tính lại ba tỷ lệ của `real` thay
vì tin ba hằng chép tay. Xem `eval/anh_rut_gon.py`.

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
import shutil
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
from eval.anh_rut_gon import HAU_TO_RUT_GON, MuoiKhongHopLe, doc_muoi, rut_gon_anh
from eval.cau_hoi import (
    DUONG_DAN_ANH_MAC_DINH,
    VERSION_ANH,
    AnhDoThiKhongHopLe,
    AnhDoThiRong,
    doc_anh_do_thi,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-toi-gian.yaml"

# Namespace graph của upstream; cùng chuỗi mà `EngineACL` truyền xuống adapter.
NAMESPACE_GRAPH: str = "chunk_entity_relation"

# Space được phép ghi ảnh chụp vào cây repo. **Danh sách cho phép, không danh
# sách cấm** (vòng review 03/09): script chạy dưới cờ system và dump nguyên văn
# giá trị mọi slot của mọi hyperedge, gồm cả `bi_mat_ha_tang`. Một
# `--space real` ghi vào `eval/anh_do_thi/real.json` là đưa dữ liệu công ty vào
# lịch sử git, đúng thứ Policy của AGENTS.md cấm. Muốn chụp space khác thì phải
# `--dich` ra ngoài cây repo, và khi đó người chạy đã tự khai là mình biết mình
# đang cầm cái gì.
#
# Story 2.10 thêm `khao_sat`: 50 bản ghi khảo sát ba tỷ lệ n-ngôi là tài liệu
# **giả lập** dựng trong repo (`eval/khao_sat/`), không phải dữ liệu công ty,
# nên ảnh chụp của nó dump được vào cây repo mà không rò gì. Nó *phải* có commit
# vì nó là nguồn duy nhất của ba con số mà chương 4 báo cáo, và ADR-012 đòi
# người đọc repo tính lại được ba tỷ lệ mà không cần kho đang chạy.
SPACE_GHI_TRONG_REPO: frozenset[str] = frozenset({"synth", "khao_sat"})

# Muối của bản rút gọn, giữ **ngoài repo** (`extra/` đã gitignore). Đây chỉ là
# đường mặc định trên máy dev; trên máy chủ `extra/` không được đồng bộ (xem
# `scripts/ci-remote.sh`), nên ở đó phải truyền `--muoi` trỏ vào một bản chép
# ngoài cây repo. Thiếu file là **từ chối**, không băm trần.
MUOI_MAC_DINH: Path = REPO_ROOT / "extra" / "khao-sat-50" / "muoi-anh-rut-gon.txt"

# Đuôi bản lưu khi `--ghi-de`, cùng khuôn với `eval/ket_qua_do/<vòng>.bak.json`
# của story 2.6: rác của một lần chạy, đã vào `.gitignore`, không commit.
DUOI_BAN_CU: str = ".bak.json"

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


def ly_do_tu_choi_dich(
    space: str, dich: Path, goc_repo: Path | None = None, *, rut_gon: bool = False
) -> str | None:
    """Lý do từ chối ghi ảnh chụp của `space` vào `dich`, hoặc `None` nếu được.

    Chặn đúng một ca: space ngoài danh sách cho phép, ở dạng **đầy đủ**, mà đích
    lại nằm trong cây repo. Ảnh chụp đầy đủ là file có commit và thân của nó là
    nguyên văn mọi giá trị slot; hai thứ đó cộng lại thì một lần `--space real`
    là một lần rò dữ liệu công ty vào git, không có bước nào ở giữa để ai đó kịp
    nhận ra.

    Bản **rút gọn** đi vào repo được với mọi space, kể cả `real`: nó không mang
    một giá trị slot nào, chỉ mang số vai được điền và quan hệ bằng nhau giữa
    các id đã băm có muối (story 2.11). Đó là đường duy nhất để ba tỷ lệ của
    `real` có một nguồn trong repo tính lại được, thay vì ba hằng chép tay.
    """
    if rut_gon:
        return None
    if space in SPACE_GHI_TRONG_REPO:
        return None
    goc = (REPO_ROOT if goc_repo is None else Path(goc_repo)).resolve()
    try:
        Path(dich).resolve().relative_to(goc)
    except ValueError:
        return None
    return (
        f"từ chối ghi ảnh chụp **đầy đủ** của space {space!r} vào {dich} (trong cây"
        f" repo): chỉ {sorted(SPACE_GHI_TRONG_REPO)} được commit ở dạng đầy đủ. Ảnh"
        " chụp đầy đủ mang nguyên văn giá trị mọi slot, gồm cả tài liệu hạn chế,"
        " nên một space dữ liệu thật phải ghi ra ngoài repo bằng --dich, hoặc vào"
        " repo bằng --rut-gon (bản rút gọn không mang giá trị nào)"
    )


def khoa_da_kiem(ids, khoa_tho) -> dict[str, str | None]:
    """Khóa lọc theo id, sau khi tách hai trạng thái mà kho trả về.

    `CHUA_GHI` và `KHONG_KHOA` **không** phải một thứ, và gộp chúng thành
    `khoa: null` là để trần lý thuyết giải thích một nhãn chết bằng câu "hợp
    nhất khác scope (AD-5)" - một câu nói sai nguyên nhân (vòng review 03/09).

    - `KHONG_KHOA` (`None`) là ca AD-5 thật: node ở lại, không vai nào chạm tới.
      Nó vào ảnh chụp, vì trần lý thuyết tụt đúng vì những ca này.
    - `CHUA_GHI` là sổ tài liệu nói có mà graph nói không: hoặc một đợt nạp chết
      giữa chừng, hoặc sổ và kho không cùng một `HYPER_RAG_WORKING_DIR`. Ghi một
      ảnh chụp thiếu là để nhãn trỏ vào chỗ trống, nên **từ chối cả đợt**.
    """
    vang = [i for i in ids if khoa_tho.get(i, CHUA_GHI) is CHUA_GHI]
    if vang:
        raise AnhDoThiKhongHopLe(
            [
                f"{len(vang)} hyperedge có trong sổ tài liệu mà không có trong graph:"
                f" {vang[:5]}{' ...' if len(vang) > 5 else ''} - sổ và kho lệch nhau"
                " (đợt nạp chết giữa chừng, hoặc hai HYPER_RAG_WORKING_DIR khác nhau)"
            ]
        )
    return {i: khoa_tho[i] for i in ids}


def dung_anh(
    *,
    space: str,
    ngay_do: str,
    policy_version: str,
    tai_lieu,
    doc_key_theo_id,
    slots_theo_id,
    khoa_theo_id,
) -> dict:
    """Ghép ba nguồn thành đúng hình dạng file ảnh chụp. Hàm thuần, không I/O.

    Tách khỏi phần chạm kho để bộ test canh được hình dạng file mà không cần
    Neo4j: hình dạng này là hợp đồng của nhãn tay, và nó phải có test riêng.

    `tai_lieu` là sổ tại thời điểm chụp (`doc_key`, `sha256` thân, `scope`,
    `content_type`). Nó là dấu vết xuất xứ: không có nó thì sau này không ai
    đối chiếu được ảnh chụp với bản corpus nào sinh ra nó, và một lần sửa tài
    liệu mà quên chụp lại đi qua im lặng.

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
    muc_tai_lieu = sorted(
        (dict(m) for m in tai_lieu), key=lambda m: m["doc_key"]
    )
    return {
        "version": VERSION_ANH,
        "space": space,
        "ngay_do": ngay_do,
        "policy_version": policy_version,
        "so_tai_lieu": len(muc_tai_lieu),
        "so_hyperedge": len(hyperedge),
        "so_hyperedge_da_nguon": sum(1 for h in hyperedge if len(h["doc_key"]) > 1),
        "tai_lieu": muc_tai_lieu,
        "hyperedge": hyperedge,
    }


def doc_so_tai_lieu(working_dir, space: str) -> tuple[dict[str, set[str]], list[dict]]:
    """`({id hyperedge: {doc_key}}, [mục tài liệu])` đọc từ sổ tài liệu của space.

    `MucTaiLieu.hyperedge` là `{id graph: id vector}`, nên chiều `doc_key` lấy
    từ **khóa** của dict đó chứ không phải giá trị. Đọc nhầm một chiều là ảnh
    chụp gán sai tài liệu cho mọi hyperedge mà vẫn tự khớp với chính nó.
    """
    so = SoTaiLieu.mo(working_dir, space)
    theo_id: dict[str, set[str]] = {}
    tai_lieu: list[dict] = []
    for doc_key in so.cac_doc_key():
        muc = so.muc(doc_key)
        tai_lieu.append(
            {
                "doc_key": doc_key,
                "sha256": muc.sha256,
                "scope": muc.scope,
                "content_type": muc.content_type,
            }
        )
        for id_he in muc.hyperedge:
            theo_id.setdefault(id_he, set()).add(doc_key)
    return theo_id, tai_lieu


async def chup(space: str, policy_version: str, cau_hinh: dict) -> dict:
    """Đọc graph rồi trả dict ảnh chụp; đóng driver dù hỏng ở đâu."""
    working_dir = cau_hinh[WORKING_DIR_KEY]
    doc_key_theo_id, tai_lieu = doc_so_tai_lieu(working_dir, space)
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

    print(f"{len(tai_lieu)} tài liệu trong sổ, {len(ids)} hyperedge")
    return dung_anh(
        space=space,
        ngay_do=thoi_diem_utc(),
        policy_version=policy_version,
        tai_lieu=tai_lieu,
        doc_key_theo_id=doc_key_theo_id,
        slots_theo_id=slots_theo_id,
        khoa_theo_id=khoa_da_kiem(ids, khoa_tho),
    )


def ghi_anh(dich: Path, anh: dict, *, ghi_de: bool = False) -> Path:
    """Ghi ảnh chụp **sau khi** loader đã nhận nó, và chỉ khi được phép ghi đè.

    Hai rào, cả hai theo khuôn story 2.6/2.7 đã đặt cho file đo có commit:

    - **Kiểm trước, thay sau.** Ghi ra file tạm rồi `doc_anh_do_thi` trên chính
      file tạm đó; chỉ khi loader nhận thì mới `os.replace`. Trước đó thứ tự
      ngược lại, nên một ảnh chụp hỏng mà không rỗng đè mất bản tốt rồi mới nổ.
    - **Không ghi đè lặng.** File đã có mà không `--ghi-de` là từ chối; có
      `--ghi-de` thì bản cũ giữ lại thành `<tên>.bak.json` trước khi thay. Ảnh
      chụp là neo của 41 cặp nhãn tay, một lần chạy nhầm không được phép làm
      mất nó.
    """
    dich = Path(dich)
    if dich.exists() and not ghi_de:
        raise FileExistsError(
            f"{dich} đã có: thêm --ghi-de để thay nó. Ảnh chụp là nguồn chuẩn của"
            " mọi id trong nhãn truy hồi vàng, nên nó không bị ghi đè lặng lẽ"
        )
    dich.parent.mkdir(parents=True, exist_ok=True)
    tam = dich.with_name(dich.name + ".tam")
    try:
        tam.write_text(json.dumps(anh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        doc_anh_do_thi(tam)
        if dich.exists():
            shutil.copy2(dich, dich.with_name(dich.name + DUOI_BAN_CU))
        os.replace(tam, dich)
    finally:
        tam.unlink(missing_ok=True)
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
        help=f"file ảnh chụp (mặc định {DUONG_DAN_ANH_MAC_DINH.parent}/<space>.json)",
    )
    p.add_argument("--ghi-de", action="store_true", dest="ghi_de", help="thay ảnh chụp đã có")
    p.add_argument(
        "--rut-gon",
        action="store_true",
        dest="rut_gon",
        help="ghi bản rút gọn: mọi id entity và doc_key thay bằng băm có muối,"
        " giữ khóa lọc và quan hệ bằng nhau. Đây là dạng duy nhất của space dữ"
        " liệu thật được commit; cần --muoi",
    )
    p.add_argument(
        "--muoi",
        type=Path,
        default=MUOI_MAC_DINH,
        metavar="FILE",
        help=f"file muối cho --rut-gon, giữ ngoài repo (mặc định {MUOI_MAC_DINH})",
    )
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH, help="bảng chính sách")
    return p.parse_args(argv)


def ten_file_mac_dinh(space: str, *, rut_gon: bool) -> Path:
    """Đích mặc định. Tên file mang **cùng** token với `space` mà file tự khai.

    `real` -> `real.json`; `real` rút gọn -> `real_rut_gon.json`, đúng bằng
    `space` bên trong file. Một tên file và một lời tự khai lệch nhau là chỗ
    người soát đọc một đằng và máy đọc một nẻo, và `.gitignore` phân biệt hai
    dạng bằng chính tên file này.
    """
    ten = f"{space}{HAU_TO_RUT_GON}" if rut_gon else space
    return DUONG_DAN_ANH_MAC_DINH.with_name(f"{ten}.json")


def main(argv: list[str] | None = None) -> int:
    ts = _tham_so(sys.argv[1:] if argv is None else list(argv))
    dich = ts.dich or ten_file_mac_dinh(ts.space, rut_gon=ts.rut_gon)
    ly_do = ly_do_tu_choi_dich(ts.space, dich, rut_gon=ts.rut_gon)
    if ly_do:
        print(ly_do, file=sys.stderr)
        return 1
    # Muối đọc **trước** khi chạm kho: thiếu muối là từ chối cả đợt, và một đợt
    # đọc graph rồi mới phát hiện thiếu muối là bắt người chạy đợi vô ích.
    muoi = None
    if ts.rut_gon:
        try:
            muoi = doc_muoi(ts.muoi)
        except MuoiKhongHopLe as loi:
            print(f"{loi.code}: {loi}", file=sys.stderr)
            return 1
    thieu = thieu_bien_moi_truong()
    if thieu:
        print(
            "thiếu biến môi trường bắt buộc: " + ", ".join(thieu)
            + " - stack compose đã lên chưa? `scripts/chay-may-chu.sh` dựng sẵn đủ bộ",
            file=sys.stderr,
        )
        return 1
    if dich.exists() and not ts.ghi_de:
        print(
            f"{dich} đã có: thêm --ghi-de để thay nó (bản cũ giữ thành"
            f" {dich.name}{DUOI_BAN_CU})",
            file=sys.stderr,
        )
        return 1
    policy = load_policy(ts.policy)
    cau_hinh = cau_hinh_kho_tu_moi_truong()
    try:
        anh = asyncio.run(chup(ts.space, policy.policy_version, cau_hinh))
        if muoi is not None:
            anh = rut_gon_anh(anh, muoi)
        ghi_anh(dich, anh, ghi_de=ts.ghi_de)
    except (AnhDoThiKhongHopLe, FileExistsError) as loi:
        print(str(loi), file=sys.stderr)
        return 1
    da_doc = doc_anh_do_thi(dich)
    print(
        f"{da_doc.so_tai_lieu} tài liệu, {da_doc.so_hyperedge} hyperedge,"
        f" {len(da_doc.da_nguon())} đa nguồn,"
        f" {sum(1 for h in da_doc.hyperedge if h.khoa is None)} không khóa"
    )
    print(f"ghi {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
