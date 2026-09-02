"""Nạp tài liệu bằng pipeline ingest và đo thô chi phí LLM/embedding (FR-30 bậc 1).

    uv run python -m api.do_chi_phi eval/data                      # nạp cả thư mục
    uv run python -m api.do_chi_phi eval/data/01-cap-quyen-gitlab.txt  # nạp từng file
    uv run python -m api.do_chi_phi --xoa-space --space synth      # xóa sạch một space

Từ story 2.3 script không tự mở ngữ cảnh hệ thống hay đợt nữa: nó dựng
`EngineACL` từ môi trường với provider thật và `AuditPostgres`, rồi gọi
`adapters.ingest` (nạp thư mục / danh sách file / xóa space). Nhãn quyền của
mỗi tài liệu đọc từ frontmatter `scope`/`content_type` của chính file; file
hỏng bị từ chối kèm mã, không chặn file kế; re-ingest ghi đè sạch.

In số fact hợp lệ / bị loại của từng tài liệu (story 2.4, cùng số đi vào sự
kiện `extract_doc`), rồi tổng token và USD đọc từ `audit_log` cho **từng tài
liệu** (theo mốc thời gian bắt đầu/kết thúc mà pipeline ghi lại) rồi cả đợt;
ngoại lệ giữa đợt (đối chiếu lệch, 429) vẫn in số đã tiêu. Nằm ở `api/` vì `eval/` không import được
hiện thực Postgres. Script tốn tiền thật: chạy sau khi spec được duyệt.

Biến môi trường: bảy khóa kho (`adapters.engine.BIEN_MOI_TRUONG`), năm biến
Postgres (`api.audit_postgres.BIEN_POSTGRES`), ba biến model
(`adapters.llm_wrapper.BIEN_MOI_TRUONG_MODEL`) và key provider. Trên máy chủ,
host của các kho là IP container (`docker inspect`), key đọc từ `.env`.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from adapters.engine import EngineACL, cau_hinh_kho_tu_moi_truong
from adapters.ingest import (
    TRANG_THAI_DA_NAP,
    TRANG_THAI_DA_XOA,
    TRANG_THAI_KHONG_DOI,
    KetQuaNap,
    nap_cac_file,
    nap_thu_muc,
    xoa_space,
)
from adapters.llm_wrapper import ham_tu_moi_truong
from adapters.policy_loader import load_policy
from api.audit_postgres import AuditPostgres, TongChiPhi
from core.audit import thoi_diem_utc

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-toi-gian.yaml"


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Nạp tài liệu qua pipeline ingest và đo chi phí LLM/embedding")
    p.add_argument("duong_dan", nargs="*", type=Path, help="một thư mục, hoặc các file .md/.txt theo thứ tự")
    p.add_argument("--space", default="synth", help="không gian dữ liệu (mặc định synth)")
    p.add_argument("--xoa-space", action="store_true", help="xóa sạch space rồi thoát, không nạp gì")
    p.add_argument("--ep-ghi-de", action="store_true", help="re-ingest cả tài liệu không đổi (cùng sha256 và nhãn)")
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH, help="bảng chính sách lấy policy_version")
    ts = p.parse_args(argv)
    if not ts.xoa_space and not ts.duong_dan:
        p.error("cần một thư mục hoặc ít nhất một file, hoặc --xoa-space")
    if ts.xoa_space and ts.duong_dan:
        p.error("--xoa-space không đi cùng đường dẫn nạp")
    return ts


def in_tong(tieu_de: str, tong: TongChiPhi) -> None:
    print(f"\n{tieu_de}")
    print(f"{'model':<28}{'provider':<12}{'lần':>6}{'token vào':>12}{'token ra':>10}{'USD':>12}")
    for d in tong.theo_model:
        print(
            f"{d.model:<28}{d.nha_cung_cap:<12}{d.so_lan:>6}{d.token_vao:>12}{d.token_ra:>10}"
            f"{d.chi_phi_usd:>12.6f}"
        )
    print(
        f"{'TỔNG':<28}{'':<12}{tong.so_lan:>6}{tong.token_vao:>12}{tong.token_ra:>10}"
        f"{tong.chi_phi_usd:>12.6f}"
    )


async def _tong_tu(audit: AuditPostgres, space: str, moc: str, moc_ket: str | None = None) -> TongChiPhi:
    """Tổng của đoạn `[moc, moc_ket)`; cả dòng theo model lẫn dòng tổng cùng một cửa sổ."""
    return await audit.tong_chi_phi(space, tu=moc, den=moc_ket)


def in_ket_qua(kq: KetQuaNap) -> None:
    for tc in kq.tu_choi:
        print(f"TỪ CHỐI {tc.ten}: {tc.ma} - {tc.ly_do}")
    for t in kq.tai_lieu:
        so = (
            f"{t.so_chunk} chunk, {t.so_hyperedge} hyperedge, {t.so_entity} entity,"
            f" {t.so_fact_hop_le} fact hợp lệ, {t.so_fact_loai} fact loại, {t.so_chunk_hong} chunk hỏng"
        )
        if t.trang_thai == TRANG_THAI_DA_NAP:
            print(f"{'RE-INGEST' if t.re_ingest else 'NẠP'} {t.doc_key}: {so}")
        elif t.trang_thai == TRANG_THAI_DA_XOA:
            print(f"XÓA {t.doc_key}: {so}")
        elif t.trang_thai == TRANG_THAI_KHONG_DOI:
            print(f"KHÔNG ĐỔI {t.doc_key}: giữ nguyên ({so})")
        else:
            print(f"{t.trang_thai.upper()} {t.doc_key}: {t.ma} - {t.ly_do}")


async def chay(ts: argparse.Namespace) -> TongChiPhi:
    policy = load_policy(ts.policy)
    audit = await AuditPostgres.mo()
    try:
        await audit.khoi_tao()
        ham = ham_tu_moi_truong(audit=audit)
        engine = EngineACL(
            **cau_hinh_kho_tu_moi_truong(),
            llm_model_func=ham.llm,
            embedding_func=ham.embedding,
            llm_model_max_token_size=ham.llm_max_token,
        )
        bat_dau = thoi_diem_utc()
        kq = KetQuaNap()
        try:
            chung = dict(space=ts.space, policy_version=policy.policy_version, audit=audit)
            if ts.xoa_space:
                await xoa_space(engine, **chung)
                print(f"[{thoi_diem_utc()}] đã xóa sạch space {ts.space!r}", flush=True)
            elif len(ts.duong_dan) == 1 and ts.duong_dan[0].is_dir():
                await nap_thu_muc(engine, ts.duong_dan[0], ket_qua=kq, ep_ghi_de=ts.ep_ghi_de, **chung)
            else:
                await nap_cac_file(engine, ts.duong_dan, ket_qua=kq, ep_ghi_de=ts.ep_ghi_de, **chung)
        finally:
            # Ngoại lệ giữa đợt (đối chiếu lệch, 429) vẫn phải cho biết đã tiêu bao nhiêu.
            in_ket_qua(kq)
            for t in kq.tai_lieu:
                if t.bat_dau:
                    in_tong(f"Tài liệu {t.doc_key} ({t.bat_dau} -> {t.ket_thuc or 'chưa xong'}):",
                            await _tong_tu(audit, ts.space, t.bat_dau, t.ket_thuc or None))
            tong = await audit.tong_chi_phi(ts.space, tu=bat_dau)
            in_tong(f"Cả đợt (thoi_diem >= {bat_dau}):", tong)
            await engine.dong()
        return tong
    finally:
        await audit.dong()


def main(argv: list[str] | None = None) -> None:
    asyncio.run(chay(_tham_so(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    main()
