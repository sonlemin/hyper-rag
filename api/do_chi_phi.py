"""Đo thô chi phí LLM/embedding của một lần nạp tài liệu (FR-30 bậc 1, story 2.2).

    uv run python -m api.do_chi_phi eval/data/01-cap-quyen-gitlab.txt eval/data/02-vpn-va-mat-khau.txt

Dựng `EngineACL` từ môi trường với provider thật (`LLM_MODEL`,
`EMBEDDING_MODEL`, key theo danh mục) và `AuditPostgres` làm audit port, rồi
`ainsert` từng file dưới ngữ cảnh hệ thống cộng một nhãn ingest mỗi tài liệu,
đúng cách `tests/nap_kho.py` nạp fixture: mở một đợt, đối chiếu hai kho ở cuối.
In tổng token và USD đọc từ `audit_log` cho **từng tài liệu** (FR-30 bậc 1 cần
chi phí trên một tài liệu) rồi cả đợt; ngoại lệ giữa đợt (đối chiếu lệch, 429)
vẫn in số đã tiêu.

Mọi file được đọc và kiểm (UTF-8, không rỗng) **trước** khi mở pool và trước
lời gọi tốn tiền đầu tiên: một file hỏng ở vị trí thứ hai không được làm mất
tiền của file thứ nhất.

Không phải pipeline ingest (2.3): không quét thư mục, không ghi tiến trình. Nó
ở `api/` chứ không ở `eval/` vì `eval/` không import được hiện thực Postgres.
Script tốn tiền thật: chạy sau khi spec được duyệt, không chạy lặp.

Biến môi trường: bảy khóa kho (`adapters.engine.BIEN_MOI_TRUONG`), năm biến
Postgres (`api.audit_postgres.BIEN_POSTGRES`), ba biến model
(`adapters.llm_wrapper.BIEN_MOI_TRUONG_MODEL`) và key provider. Trên máy chủ,
host của các kho là IP container (`docker inspect`), key đọc từ `.env`.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from adapters.doi_chieu import doi_chieu_dot, dot_ingest, kho_cua_engine
from adapters.engine import EngineACL, cau_hinh_kho_tu_moi_truong
from adapters.ingest_labels import ingest_label
from adapters.llm_wrapper import ham_tu_moi_truong
from adapters.policy_loader import load_policy
from api.audit_postgres import AuditPostgres, TongChiPhi
from core.audit import thoi_diem_utc
from core.permission import use_context
from core.system_context import system_context

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-toi-gian.yaml"


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Đo thô chi phí LLM/embedding khi ainsert tài liệu")
    p.add_argument("files", nargs="+", type=Path, help="file văn bản để nạp, theo thứ tự")
    p.add_argument("--space", default="synth", help="không gian dữ liệu (mặc định synth)")
    p.add_argument("--scope", default="noi_bo", help="scope của nhãn ingest cho mọi file")
    p.add_argument("--content-type", default="runbook", help="loại nội dung của nhãn ingest")
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH, help="bảng chính sách lấy policy_version")
    return p.parse_args(argv)


def doc_tai_lieu(files: list[Path]) -> list[tuple[Path, str]]:
    """Đọc và kiểm mọi file trước khi tốn tiền; hỏng cái nào thoát nêu tên cái đó."""
    ket_qua = []
    for f in files:
        if not f.is_file():
            sys.exit(f"không có file {f}")
        try:
            noi_dung = f.read_bytes().decode("utf-8")
        except UnicodeDecodeError as loi:
            sys.exit(f"file {f} không phải UTF-8: {loi}")
        if not noi_dung.strip():
            sys.exit(f"file {f} rỗng hoặc toàn khoảng trắng")
        ket_qua.append((f, noi_dung))
    return ket_qua


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


async def _tong_tu(audit: AuditPostgres, space: str, moc: str, moc_ket: str | None = None):
    """Tổng từ mốc `moc`; nếu có `moc_ket` thì trừ phần từ mốc sau để ra một đoạn."""
    tong = await audit.tong_chi_phi(space, tu=moc)
    if moc_ket is None:
        return tong
    sau = await audit.tong_chi_phi(space, tu=moc_ket)
    return TongChiPhi(
        so_lan=tong.so_lan - sau.so_lan,
        token_vao=tong.token_vao - sau.token_vao,
        token_ra=tong.token_ra - sau.token_ra,
        chi_phi_usd=tong.chi_phi_usd - sau.chi_phi_usd,
        theo_model=tong.theo_model,
    )


async def chay(ts: argparse.Namespace) -> TongChiPhi:
    tai_lieu = doc_tai_lieu(ts.files)
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
        try:
            with use_context(system_context(space=ts.space, policy_version=policy.policy_version)):
                await engine.khoi_tao()
                with dot_ingest() as so:
                    for f, noi_dung in tai_lieu:
                        moc = thoi_diem_utc()
                        print(f"[{moc}] nạp {f} ({len(noi_dung.encode('utf-8'))} byte)", flush=True)
                        with ingest_label(scope=ts.scope, content_type=ts.content_type):
                            await engine.ainsert(noi_dung)
                        in_tong(f"Tài liệu {f} (từ {moc}):", await audit.tong_chi_phi(ts.space, tu=moc))
                    await doi_chieu_dot(so, kho=kho_cua_engine(engine))
                print(f"[{thoi_diem_utc()}] đối chiếu hai kho: khớp", flush=True)
        finally:
            # Ngoại lệ giữa đợt (đối chiếu lệch, 429) vẫn phải cho biết đã tiêu bao nhiêu.
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
