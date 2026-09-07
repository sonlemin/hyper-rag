"""Đo 3 thô: recall truy hồi tất định trên nhãn vàng, bốn cấu hình, hai lớp (story 3.8).

Đây là **bản thô** mà cổng M2 đòi ("script recall tối thiểu, đủ phát hiện sớm
vấn đề recall trước T7"); harness đầy đủ - bootstrap, đồ thị hai đường, đối
chiếu FR-11 - thuộc story 7.3. Bản thô làm đúng ba việc: với mỗi cấu hình
trong `config/policy-*.yaml` và mỗi câu có nhãn (22 câu N3+N5), lấy **chuỗi ngữ
cảnh truy hồi** dưới ngữ cảnh quyền của `vai_hoi`, đếm hyperedge kỳ vọng có
mặt theo hai lớp của PRD 5.3, và **lưu nguyên văn ngữ cảnh** từng ô để câu "vì
sao mất" đọc được mà không chạy lại.

Hai lớp đếm, định nghĩa trước phép đếm đầu tiên (PRD 5.3):

- **tồn tại** - id hyperedge kỳ vọng xuất hiện ở cột `hyperedge` của khối
  Relationships (đọc bằng `adapters.tra_loi.id_hyperedge_trong`, cùng bộ đọc
  với citation). Bản đã che tính là xuất hiện; đây là lớp mang luận điểm.
- **trả lời được** - thêm điều kiện: không slot nào trong `slot_dap_an` của
  nhãn bị `masked_slots` của vai che ở loại nội dung của hyperedge đó (loại
  đọc từ ảnh chụp). `owner` không tính là bị che (AD-9), cùng luật với
  `eval.cau_hoi._tran_mot_cau`.

Phép đo đi qua `EngineACL.ngu_canh_hoi_dap` (đường mà `/hoi-dap` dùng, không
grant nên bằng `aquery(only_need_context=True)`), tức **một** lời gọi LLM trích
từ khóa cộng embedding cho mỗi ô, không lời gọi sinh câu trả lời. Từ khóa LLM
trích không tất định tuyệt đối giữa hai lần chạy; bản thô chấp nhận biên độ đó
và ghi lại nguyên văn ngữ cảnh để 7.3 so. Chuỗi hỏng của vendor
(`CAU_HONG_UPSTREAM`) ghi thành `tu_khoa_rong` với 0/0, không dừng vòng.

Ba rào, cùng khuôn `eval/chup_do_thi.py`: chỉ space trong
`eval.rao_ghi_repo.SPACE_GHI_TRONG_REPO` được ghi (file ngữ cảnh mang nguyên
văn giá trị slot và **có commit**); file đã có đòi `--ghi-de`; thiếu biến môi
trường kho là dừng trước khi mở engine. Engine dựng từ `adapters/` (`eval/`
không import `api/`), không `khoi_tao()`, không `ainsert`, không xóa.

Chi phí đi qua đúng seam đo của FR-30 (`eval.do_trich_xuat.GomChiPhi` nhận sự
kiện của wrapper), ghi vào file kết quả; harness không có Postgres nên nó
không vào `audit_log`, như vòng đo 2.6.

Chạy trên máy chủ:
    HYPER_RAG_MODULE=eval.do3_tho scripts/chay-may-chu.sh do3 --space synth
Xem trước: `--uoc-tinh` (không mở kết nối). Dựng trang: `--xem` đọc file kết
quả đã có và ghi `eval/expr/do3_tho.html` (không commit).
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from adapters.engine import BIEN_MOI_TRUONG, EngineACL, cau_hinh_kho_tu_moi_truong
from adapters.kv import WORKING_DIR_KEY
from adapters.llm_wrapper import CT_CHI_PHI_USD, CT_TOKEN_RA, CT_TOKEN_VAO, ham_tu_moi_truong
from adapters.thu_lai import NGAN_SACH_NAP
from adapters.neo4j import NEO4J_PASSWORD_KEY, NEO4J_URI_KEY
from adapters.policy_loader import cac_bang_chinh_sach, load_policy
from adapters.tra_loi import CAU_HONG_UPSTREAM, id_hyperedge_trong
from core.audit import EVENT_EMBEDDING_COST, EVENT_LLM_COST, SuKienAudit, thoi_diem_utc
from core.permission import use_context, user_context
from core.policy import Policy
from eval.cau_hoi import (
    AnhDoThi,
    BoCauHoi,
    NhanCau,
    NhanTruyHoi,
    doc_anh_do_thi,
    doc_bo_cau_hoi,
    doc_nhan_truy_hoi,
)
from eval.do_trich_xuat import GomChiPhi
from eval.rao_ghi_repo import SPACE_GHI_TRONG_REPO

REPO_ROOT = Path(__file__).resolve().parent.parent
# Thư mục riêng, không dùng `eval/ket_qua_do/`: `eval.do_trich_xuat.doc_moi_vong` đọc
# mọi `*.json` ở đó theo lược đồ vòng đo trích xuất, và một file Đo 3 nằm đó làm
# `eval.xem_do_trich_xuat` từ chối dựng trang.
THU_MUC_KET_QUA = REPO_ROOT / "eval" / "ket_qua_do3"
THU_MUC_EXPR = REPO_ROOT / "eval" / "expr"
VERSION_KET_QUA = 1

# Thứ tự bốn cấu hình theo PRD 5.3: (1) trần, (2) baseline, (3) vận hành, (4)
# tham chiếu. Id phải khớp danh mục `config/policy-*.yaml`; một id lạ trong
# danh mục là dừng, vì bảng kết quả không có cột cho nó.
THU_TU_PRD: Mapping[str, int] = {
    "tat-phan-quyen": 1,
    "nhi-phan": 2,
    "day-du": 3,
    "toi-thieu-l1": 4,
}
# Cặp cấu hình mà phát biểu của Đo 3 so: recall(3) > recall(2) trên N3+N5.
CAU_HINH_PHAT_BIEU: tuple[str, str] = ("day-du", "nhi-phan")

# Biến môi trường bắt buộc để mở engine truy hồi (cùng ba biến với ảnh chụp,
# cộng model). `EMBEDDING_MODEL`/`LLM_MODEL` do `ham_tu_moi_truong` tự kiểm.
BIEN_BAT_BUOC: tuple[str, ...] = (
    BIEN_MOI_TRUONG[NEO4J_URI_KEY],
    BIEN_MOI_TRUONG[NEO4J_PASSWORD_KEY],
    BIEN_MOI_TRUONG[WORKING_DIR_KEY],
)

LY_DO_TU_KHOA_RONG = "tu_khoa_rong"


class Do3ThoTuChoi(ValueError):
    """Một rào của module từ chối chạy; thông điệp nói vì sao, mã thoát ở `main`."""


@dataclass(frozen=True)
class KetQuaCau:
    """Một ô của bảng: một câu dưới một cấu hình."""

    cau_id: str
    nhom: str
    vai: str
    tong: int
    ton_tai: int
    tra_loi_duoc: int
    co_mat: tuple[str, ...]
    vang: tuple[str, ...]
    ly_do: tuple[str, ...]
    tu_khoa_rong: bool
    so_hyperedge_ngu_canh: int


def cham_cau(
    hang,
    nhan_cau: NhanCau,
    theo_id_he,
    ids_trong: Sequence[str],
    *,
    nhom: str,
    tu_khoa_rong: bool = False,
) -> KetQuaCau:
    """Chấm một câu: hai lớp đếm trên ngữ cảnh **đã lấy được**. Hàm thuần.

    `hang` là `RolePolicy` của vai hỏi; `theo_id_he` là `anh.theo_id`;
    `ids_trong` là dãy id ở khối Relationships. Ca `tu_khoa_rong` (vendor trả
    câu hỏng thay cho khung) là 0/0 kèm một lý do duy nhất, vì không có ngữ
    cảnh nào để đếm - và nó **không** phải "mất vì quyền".
    """
    tap = set(ids_trong)
    co_mat: list[str] = []
    vang: list[str] = []
    ly_do: list[str] = []
    ton_tai = tra_loi = 0
    if tu_khoa_rong:
        return KetQuaCau(
            cau_id=nhan_cau.cau_id, nhom=nhom, vai=hang.name, tong=len(nhan_cau.hyperedge),
            ton_tai=0, tra_loi_duoc=0, co_mat=(), vang=tuple(h.id for h in nhan_cau.hyperedge),
            ly_do=(f"{LY_DO_TU_KHOA_RONG}: vendor không trích được từ khóa, không có ngữ cảnh",),
            tu_khoa_rong=True, so_hyperedge_ngu_canh=0,
        )
    for he in nhan_cau.hyperedge:
        if he.id not in tap:
            vang.append(he.id)
            moc = theo_id_he.get(he.id)
            if moc is None:
                ly_do.append(f"{he.id} không có trong ảnh chụp (nhãn chết)")
            elif moc.khoa is None:
                ly_do.append(f"{he.id} vắng: không mang khóa lọc (hợp nhất khác scope, AD-5)")
            elif moc.scope not in hang.scopes:
                ly_do.append(f"{he.id} vắng: scope {moc.scope!r} ngoài scopes của vai")
            elif hang.level(moc.content_type) == "L0":
                ly_do.append(f"{he.id} vắng: loại {moc.content_type!r} ở L0 với vai")
            else:
                ly_do.append(
                    f"{he.id} vắng dù vai được thấy ({hang.level(moc.content_type)}):"
                    " truy hồi không kéo về trong top-k"
                )
            continue
        co_mat.append(he.id)
        ton_tai += 1
        moc = theo_id_he.get(he.id)
        loai = moc.content_type if moc is not None else None
        bi_che = set(hang.masked_slots.get(loai, ())) & set(he.slot_dap_an) if loai else set()
        if bi_che:
            ly_do.append(
                f"{he.id} có mặt nhưng slot đáp án {sorted(bi_che)} bị che ở mức"
                f" {hang.level(loai)}"
            )
            continue
        tra_loi += 1
    return KetQuaCau(
        cau_id=nhan_cau.cau_id, nhom=nhom, vai=hang.name, tong=len(nhan_cau.hyperedge),
        ton_tai=ton_tai, tra_loi_duoc=tra_loi, co_mat=tuple(co_mat), vang=tuple(vang),
        ly_do=tuple(ly_do), tu_khoa_rong=False, so_hyperedge_ngu_canh=len(tap),
    )


def tong_hop(cac_cau: Sequence[KetQuaCau]) -> dict:
    """Tổng của một cấu hình: cả tập cộng theo nhóm N3/N5."""
    def _tong(ds):
        tong = sum(c.tong for c in ds)
        return {
            "so_cau": len(ds),
            "tong": tong,
            "ton_tai": sum(c.ton_tai for c in ds),
            "tra_loi_duoc": sum(c.tra_loi_duoc for c in ds),
            "recall_ton_tai": round(sum(c.ton_tai for c in ds) / tong, 4) if tong else 0.0,
            "recall_tra_loi_duoc": round(sum(c.tra_loi_duoc for c in ds) / tong, 4) if tong else 0.0,
        }

    nhom = sorted({c.nhom for c in cac_cau})
    return {
        "tat_ca": _tong(cac_cau),
        "theo_nhom": {n: _tong([c for c in cac_cau if c.nhom == n]) for n in nhom},
        "so_cau_tu_khoa_rong": sum(1 for c in cac_cau if c.tu_khoa_rong),
    }


def mat_giua_hai_cau_hinh(
    theo_cau_hinh: Mapping[str, Sequence[KetQuaCau]], co: str, mat: str
) -> list[dict]:
    """Câu nào có hyperedge **có mặt** ở cấu hình `co` mà **vắng** ở `mat`, kèm lý do ở `mat`.

    Đây là bảng "câu nào mất ở cấu hình 2 và vì sao" mà PRD 5.3 đòi, ở dạng thô.
    """
    theo_id_co = {c.cau_id: c for c in theo_cau_hinh.get(co, ())}
    ra: list[dict] = []
    for c in theo_cau_hinh.get(mat, ()):
        goc = theo_id_co.get(c.cau_id)
        if goc is None:
            continue
        roi = sorted(set(goc.co_mat) - set(c.co_mat))
        if roi:
            ra.append({"cau_id": c.cau_id, "nhom": c.nhom, "vai": c.vai, "mat": roi,
                       "ly_do": [l for l in c.ly_do if any(i in l for i in roi)]})
    return ra


def thu_tu_cau_hinh(danh_muc: Mapping[str, Path]) -> list[str]:
    la = sorted(set(danh_muc) - set(THU_TU_PRD))
    if la:
        raise Do3ThoTuChoi(
            f"danh mục policy có id không có cột trong bảng Đo 3: {la}; thêm vào"
            " THU_TU_PRD của eval/do3_tho.py trước khi đo"
        )
    thieu = sorted(set(CAU_HINH_PHAT_BIEU) - set(danh_muc))
    if thieu:
        raise Do3ThoTuChoi(
            f"danh mục policy thiếu cấu hình của phát biểu Đo 3: {thieu}; bảng \"câu mất ở"
            " baseline\" không dựng được"
        )
    return sorted(danh_muc, key=lambda m: THU_TU_PRD[m])


def thieu_bien_moi_truong(moi_truong=None) -> list[str]:
    nguon = os.environ if moi_truong is None else moi_truong
    return [ten for ten in BIEN_BAT_BUOC if not str(nguon.get(ten) or "").strip()]


def ly_do_tu_choi_space(space: str) -> str | None:
    if space in SPACE_GHI_TRONG_REPO:
        return None
    return (
        f"từ chối đo space {space!r}: file ngữ cảnh mang nguyên văn giá trị slot và"
        f" có commit, chỉ {sorted(SPACE_GHI_TRONG_REPO)} được ghi vào cây repo"
        " (eval/rao_ghi_repo.py). Space dữ liệu thật đo ở harness 7.3 với đích ngoài repo"
    )


def ten_file(space: str) -> tuple[Path, Path]:
    return (
        THU_MUC_KET_QUA / f"do3-tho-{space}.json",
        THU_MUC_KET_QUA / f"do3-tho-{space}-ngu-canh.json",
    )


def chi_phi_tu(so_audit: GomChiPhi) -> dict:
    """Token và USD gộp từ sự kiện chi phí của wrapper; không tự đếm lại."""
    llm = [s for s in so_audit.su_kien if s.event == EVENT_LLM_COST]
    emb = [s for s in so_audit.su_kien if s.event == EVENT_EMBEDDING_COST]

    def _cong(ds: list[SuKienAudit], khoa: str) -> float:
        # Khóa thiếu là lỗi, không phải 0: một hợp đồng `chi_tiet` đổi tên khóa
        # phải làm đợt đo hỏng chứ không ghi `usd: 0.0` vào file có commit.
        return sum(float(s.chi_tiet[khoa]) for s in ds)

    return {
        "so_loi_goi_llm": len(llm),
        "so_loi_goi_embedding": len(emb),
        "token_vao": int(_cong(llm, CT_TOKEN_VAO) + _cong(emb, CT_TOKEN_VAO)),
        "token_ra": int(_cong(llm, CT_TOKEN_RA)),
        "usd": round(_cong(llm, CT_CHI_PHI_USD) + _cong(emb, CT_CHI_PHI_USD), 6),
    }


def dung_engine(so_audit: GomChiPhi) -> EngineACL:
    """Engine truy hồi từ môi trường: **một composition riêng của `eval/`**, chép khuôn `api.hoi_dap.mo_engine`.

    `eval/` không import `api/`, nên đây là bản thứ hai và phải khai chỗ khác
    (vòng review 3.8), cùng cách `mo_engine` khai khác biệt với
    `api.dot_nap.dung_engine_tu_moi_truong`:

    - **ngân sách nạp** (`NGAN_SACH_NAP`, 4 lần thử, trần chờ 60 giây) thay ngân
      sách truy hồi: đây là một đợt đo 88 lời gọi tuần tự, một 429 phải chờ chứ
      không phải 502 ngay như một request người dùng; ngân sách chỉ đổi cách thử
      lại, không đổi chuỗi ngữ cảnh;
    - không `lay_audit` (harness không có Postgres cho hàng `filter`);
    - không từ điển thực thể (chỉ dùng lúc trích xuất), không `khoi_tao()`.

    Mọi tham số truy hồi khác (`top_k`, `max_token_for_*`) là mặc định của
    `QueryParam()` như `EngineACL.hoi_dap` dựng; nếu đường phục vụ đổi chúng
    (phương án (a) của ADR-022 để mở) thì file này phải đổi theo, và không test
    nào canh - đó là giới hạn đã khai của bản thô.
    """
    ham = ham_tu_moi_truong(audit=so_audit, ngan_sach=NGAN_SACH_NAP)
    return EngineACL(
        **cau_hinh_kho_tu_moi_truong(),
        llm_model_func=ham.llm,
        embedding_func=ham.embedding,
        llm_model_max_token_size=ham.llm_max_token,
    )


async def chay(
    *,
    space: str,
    bo: BoCauHoi,
    nhan: NhanTruyHoi,
    anh: AnhDoThi,
    policies: Mapping[str, Policy],
    thu_tu: Sequence[str],
    engine,
    in_ra: Callable[..., None] = print,
    ghi_tam: Callable[[dict, dict], None] | None = None,
) -> tuple[dict[str, list[KetQuaCau]], dict[str, dict[str, str]]]:
    """Vòng đo: mỗi cấu hình × mỗi câu có nhãn, trả kết quả và ngữ cảnh nguyên văn.

    `engine` chỉ cần `ngu_canh_hoi_dap(cau_hoi)`; nơi gọi đóng nó. Câu hỏi
    chạy **tuần tự**: mỗi ô là một lời gọi LLM, và chạy song song là tự tái tạo
    429. `ghi_tam(ket_qua, ngu_canh_luu)` được gọi **sau mỗi ô** (vòng review
    3.8, khuôn `chua-xong/` của 2.6): một ô thứ 80 nổ vì mạng không được làm
    mất 79 ô đã trả tiền.
    """
    theo_id_cau = bo.theo_id
    theo_id_he = anh.theo_id
    ket_qua: dict[str, list[KetQuaCau]] = {}
    ngu_canh_luu: dict[str, dict[str, str]] = {}
    for ma in thu_tu:
        policy = policies[ma]
        ket_qua[ma] = []
        ngu_canh_luu[ma] = {}
        for n in nhan.nhan:
            cau = theo_id_cau[n.cau_id]
            hang = policy.role(cau.vai_hoi)
            ngu_canh_quyen = user_context(
                policy=policy, role=cau.vai_hoi, space=space, real_account=f"{cau.vai_hoi}01"
            )
            with use_context(ngu_canh_quyen):
                chuoi = await engine.ngu_canh_hoi_dap(cau.cau_hoi)
            if not isinstance(chuoi, str):
                raise Do3ThoTuChoi(
                    f"{ma}/{n.cau_id}: đường truy hồi trả {type(chuoi).__name__} thay vì chuỗi"
                )
            hong = chuoi == CAU_HONG_UPSTREAM
            kq = cham_cau(
                hang, n, theo_id_he, () if hong else id_hyperedge_trong(chuoi),
                nhom=cau.nhom, tu_khoa_rong=hong,
            )
            ket_qua[ma].append(kq)
            ngu_canh_luu[ma][n.cau_id] = chuoi
            if ghi_tam is not None:
                ghi_tam(ket_qua, ngu_canh_luu)
            in_ra(
                f"  [{ma}] {n.cau_id} ({cau.vai_hoi}): tồn tại {kq.ton_tai}/{kq.tong},"
                f" trả lời được {kq.tra_loi_duoc}/{kq.tong}, {kq.so_hyperedge_ngu_canh} hyperedge"
                + (" - TU_KHOA_RONG" if hong else ""),
                flush=True,
            )
    return ket_qua, ngu_canh_luu


def dung_ket_qua(
    *,
    space: str,
    anh: AnhDoThi,
    policies: Mapping[str, Policy],
    thu_tu: Sequence[str],
    ket_qua: Mapping[str, Sequence[KetQuaCau]],
    chi_phi: dict,
    model: dict,
) -> dict:
    """Dict tổng hợp ghi ra file có commit. Hàm thuần."""
    cau_hinh = {}
    for ma in thu_tu:
        cau_hinh[ma] = {
            "thu_tu_prd": THU_TU_PRD[ma],
            "policy_version": policies[ma].policy_version,
            **tong_hop(ket_qua[ma]),
            "cau": [asdict(c) for c in ket_qua[ma]],
        }
    co, mat = CAU_HINH_PHAT_BIEU
    return {
        "version": VERSION_KET_QUA,
        "space": space,
        "ngay_do": thoi_diem_utc(),
        "anh_do_thi": {"space": anh.space, "so_hyperedge": anh.so_hyperedge, "ngay_do": anh.ngay_do},
        "so_cau_co_nhan": len(next(iter(ket_qua.values()), ())),
        "model": model,
        "chi_phi": chi_phi,
        "cau_hinh": cau_hinh,
        "mat_o_baseline_so_voi_van_hanh": mat_giua_hai_cau_hinh(ket_qua, co, mat),
        "ghi_chu": (
            "Bản thô của Đo 3 (story 3.8): từ khóa do LLM trích không tất định tuyệt đối"
            " giữa hai lần chạy; harness 7.3 đo lại có đối chứng. Số của cấu hình 1"
            " (tat-phan-quyen) là phần thực nghiệm thật (a) của PRD 5.3."
        ),
    }


def in_bang(kq: dict, in_ra: Callable[..., None] = print) -> None:
    in_ra(f"\nĐo 3 thô - space {kq['space']}, {kq['so_cau_co_nhan']} câu có nhãn")
    in_ra(f"{'cấu hình':<18}{'tồn tại':>14}{'trả lời được':>16}{'N3 tồn tại':>13}{'N5 tồn tại':>13}")
    for ma, c in kq["cau_hinh"].items():
        t = c["tat_ca"]
        n3 = c["theo_nhom"].get("N3", {})
        n5 = c["theo_nhom"].get("N5", {})
        in_ra(
            f"({c['thu_tu_prd']}) {ma:<14}{t['ton_tai']:>3}/{t['tong']:<3} {t['recall_ton_tai']:>6.1%}"
            f"{t['tra_loi_duoc']:>6}/{t['tong']:<3} {t['recall_tra_loi_duoc']:>6.1%}"
            f"{n3.get('ton_tai', 0):>6}/{n3.get('tong', 0):<6}{n5.get('ton_tai', 0):>6}/{n5.get('tong', 0):<6}"
        )
    mat = kq["mat_o_baseline_so_voi_van_hanh"]
    in_ra(f"\nCâu mất ở nhi-phan so với day-du: {len(mat)}")
    for m in mat:
        in_ra(f"  {m['cau_id']} ({m['vai']}): mất {len(m['mat'])} - " + "; ".join(m["ly_do"]))
    cp = kq["chi_phi"]
    in_ra(
        f"\nChi phí: {cp['so_loi_goi_llm']} lời gọi LLM, {cp['so_loi_goi_embedding']} embedding,"
        f" {cp['token_vao']}+{cp['token_ra']} token, {cp['usd']:.6f} USD"
    )


def dung_html(kq: dict) -> str:
    h = html.escape
    dong = []
    for ma, c in kq["cau_hinh"].items():
        t = c["tat_ca"]
        dong.append(
            f"<tr><td>({c['thu_tu_prd']}) {h(ma)}</td><td>{t['ton_tai']}/{t['tong']}"
            f" ({t['recall_ton_tai']:.1%})</td><td>{t['tra_loi_duoc']}/{t['tong']}"
            f" ({t['recall_tra_loi_duoc']:.1%})</td><td>{c['so_cau_tu_khoa_rong']}</td></tr>"
        )
    chi_tiet = []
    for ma, c in kq["cau_hinh"].items():
        chi_tiet.append(f"<h3>{h(ma)}</h3><table><tr><th>câu</th><th>vai</th><th>tồn tại</th><th>trả lời được</th><th>lý do</th></tr>")
        for cau in c["cau"]:
            chi_tiet.append(
                f"<tr><td>{h(cau['cau_id'])}</td><td>{h(cau['vai'])}</td><td>{cau['ton_tai']}/{cau['tong']}</td>"
                f"<td>{cau['tra_loi_duoc']}/{cau['tong']}</td><td>{'<br>'.join(h(l) for l in cau['ly_do'])}</td></tr>"
            )
        chi_tiet.append("</table>")
    mat = "".join(
        f"<li><b>{h(m['cau_id'])}</b> ({h(m['vai'])}): {', '.join(h(i) for i in m['mat'])}"
        f"<br><small>{'; '.join(h(l) for l in m['ly_do'])}</small></li>"
        for m in kq["mat_o_baseline_so_voi_van_hanh"]
    )
    return f"""<!doctype html><meta charset="utf-8"><title>Đo 3 thô - {h(kq['space'])}</title>
<style>body{{font-family:system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:4px 8px;vertical-align:top;font-size:13px}}th{{background:#f3f3f3}}</style>
<h1>Đo 3 thô - space {h(kq['space'])}</h1>
<p>{h(kq['ghi_chu'])} Ngày đo {h(kq['ngay_do'])}, {kq['so_cau_co_nhan']} câu có nhãn, ảnh chụp {kq['anh_do_thi']['so_hyperedge']} hyperedge.</p>
<table><tr><th>cấu hình</th><th>recall tồn tại</th><th>recall trả lời được</th><th>câu tu_khoa_rong</th></tr>{''.join(dong)}</table>
<h2>Câu mất ở nhi-phan (2) so với day-du (3)</h2><ul>{mat or '<li>không câu nào</li>'}</ul>
<h2>Từng câu × cấu hình</h2>{''.join(chi_tiet)}
"""


def _ghi_json(dich: Path, du_lieu) -> None:
    dich.parent.mkdir(parents=True, exist_ok=True)
    tam = dich.with_suffix(dich.suffix + ".tmp")
    tam.write_text(json.dumps(du_lieu, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tam, dich)


def _tham_so(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Đo 3 thô: recall truy hồi tất định trên nhãn vàng, 4 cấu hình (tốn tiền: 1 lời gọi LLM mỗi ô).")
    p.add_argument("--space", default="synth")
    p.add_argument("--anh", type=Path, default=None, help="ảnh chụp đồ thị (mặc định eval/anh_do_thi/<space>.json)")
    p.add_argument("--thu-muc-policy", type=Path, default=None, dest="thu_muc_policy")
    p.add_argument("--ghi-de", action="store_true", dest="ghi_de")
    p.add_argument("--uoc-tinh", action="store_true", dest="uoc_tinh", help="chỉ in số lời gọi, không mở kết nối")
    p.add_argument("--xem", action="store_true", help="đọc file kết quả đã có, ghi eval/expr/do3_tho.html")
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None, *, tao_engine=None, in_ra=print) -> int:
    ts = _tham_so(sys.argv[1:] if argv is None else argv)
    ly_do = ly_do_tu_choi_space(ts.space)
    if ly_do:
        print(ly_do, file=sys.stderr)
        return 2
    f_kq, f_nc = ten_file(ts.space)
    if ts.xem:
        if not f_kq.exists():
            print(f"{f_kq} chưa có: chạy đo trước", file=sys.stderr)
            return 1
        kq = json.loads(f_kq.read_text(encoding="utf-8"))
        if kq.get("version") != VERSION_KET_QUA or "cau_hinh" not in kq:
            print(f"{f_kq}: version {kq.get('version')!r} lạ hay thiếu khóa, không dựng trang", file=sys.stderr)
            return 1
        THU_MUC_EXPR.mkdir(parents=True, exist_ok=True)
        # Tên mang space (luật của CT-03): một tên cố định là ghi đè im lặng khi
        # chạy space thứ hai.
        dich = THU_MUC_EXPR / f"do3_tho-{ts.space}.html"
        dich.write_text(dung_html(kq), encoding="utf-8")
        in_bang(kq, in_ra)
        in_ra(f"đã ghi {dich}")
        return 0
    try:
        anh = doc_anh_do_thi(ts.anh) if ts.anh else doc_anh_do_thi(REPO_ROOT / "eval" / "anh_do_thi" / f"{ts.space}.json")
        bo = doc_bo_cau_hoi()
        nhan = doc_nhan_truy_hoi(bo=bo, anh=anh)
        danh_muc = cac_bang_chinh_sach(ts.thu_muc_policy)
        thu_tu = thu_tu_cau_hinh(danh_muc)
        policies = {ma: load_policy(danh_muc[ma]) for ma in thu_tu}
    except Do3ThoTuChoi as loi:
        print(str(loi), file=sys.stderr)
        return 2
    except ValueError as loi:
        print(f"nguồn đo không hợp lệ: {loi}", file=sys.stderr)
        return 1
    so_o = len(nhan.nhan) * len(thu_tu)
    if ts.uoc_tinh:
        in_ra(
            f"Đo 3 thô trên {ts.space}: {len(nhan.nhan)} câu × {len(thu_tu)} cấu hình = {so_o} ô,"
            f" {so_o} lời gọi LLM trích từ khóa (không có lời gọi sinh câu trả lời)."
            " Embedding không ước: số lời gọi của nó phụ thuộc số từ khóa LLM trích ra."
        )
        return 0
    if (f_kq.exists() or f_nc.exists()) and not ts.ghi_de:
        print(f"{f_kq} đã có: thêm --ghi-de để thay (đợt cũ đã tốn tiền)", file=sys.stderr)
        return 1
    thieu = thieu_bien_moi_truong()
    if thieu and tao_engine is None:
        print("thiếu biến môi trường bắt buộc: " + ", ".join(thieu) + " - chạy qua scripts/chay-may-chu.sh", file=sys.stderr)
        return 1
    so_audit = GomChiPhi()
    try:
        engine = dung_engine(so_audit) if tao_engine is None else tao_engine(so_audit)
    except Exception as loi:  # noqa: BLE001 - mọi lỗi cấu hình đều là "không dựng được engine"
        print(f"không dựng được engine truy hồi ({type(loi).__name__}): {loi}", file=sys.stderr)
        return 1
    # File dở dang: ghi sau mỗi ô, xóa khi đợt xong. Tên mang `-chua-xong` và
    # `.gitignore` chặn nó: phần đã trả tiền của một đợt hỏng không vào lịch sử.
    f_tam = f_nc.with_name(f_nc.name.replace(".json", "-chua-xong.json"))

    def _ghi_tam(kq_tam, nc_tam):
        _ghi_json(f_tam, {"version": VERSION_KET_QUA, "space": ts.space, "dang_do": True,
                          "ket_qua": {m: [asdict(c) for c in ds] for m, ds in kq_tam.items()},
                          "ngu_canh": nc_tam})

    async def _chay():
        try:
            return await chay(space=ts.space, bo=bo, nhan=nhan, anh=anh, policies=policies,
                              thu_tu=thu_tu, engine=engine, in_ra=in_ra, ghi_tam=_ghi_tam)
        finally:
            dong = getattr(engine, "dong", None)
            if dong is not None:
                await dong()

    try:
        ket_qua, ngu_canh = asyncio.run(_chay())
    except Do3ThoTuChoi as loi:
        print(str(loi), file=sys.stderr)
        return 1
    except Exception as loi:  # noqa: BLE001 - provider, kho, mạng: phần đã trả tiền nằm ở f_tam
        print(
            f"đợt dừng giữa chừng ({type(loi).__name__}): {loi}\nphần đã chạy nằm ở {f_tam}",
            file=sys.stderr,
        )
        return 1
    # Ghi đè giữ bản cũ thành .bak.json (khuôn chup_do_thi/do_trich_xuat): đợt cũ
    # đã tốn tiền và đã commit không được mất vì một lần chạy lại.
    for f in (f_kq, f_nc):
        if f.exists():
            os.replace(f, f.with_name(f.name.replace(".json", ".bak.json")))
    model = {"llm": os.environ.get("LLM_MODEL"), "embedding": os.environ.get("EMBEDDING_MODEL")}
    kq = dung_ket_qua(space=ts.space, anh=anh, policies=policies, thu_tu=thu_tu,
                      ket_qua=ket_qua, chi_phi=chi_phi_tu(so_audit), model=model)
    _ghi_json(f_kq, kq)
    _ghi_json(f_nc, {"version": VERSION_KET_QUA, "space": ts.space, "ngay_do": kq["ngay_do"], "ngu_canh": ngu_canh})
    if f_tam.exists():
        f_tam.unlink()
    in_bang(kq, in_ra)
    in_ra(f"đã ghi {f_kq} và {f_nc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
