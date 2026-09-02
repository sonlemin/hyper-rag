"""Nạp tài liệu bằng pipeline ingest và đo thô chi phí LLM/embedding (FR-30 bậc 1).

    uv run python -m api.do_chi_phi eval/data                      # nạp cả thư mục
    uv run python -m api.do_chi_phi eval/data/01-cap-quyen-gitlab.txt  # nạp từng file
    uv run python -m api.do_chi_phi --xoa-space --space synth      # xóa sạch một space
    uv run python -m api.do_chi_phi eval/data --xuat-json eval/so_do_nap/nap-that.json

Từ story 2.3 script không tự mở ngữ cảnh hệ thống hay đợt nữa: nó quét đường
dẫn bằng `core.ingest_scan` rồi giao cho `api.dot_nap.chay_lan_nap` - đúng lõi
mà màn nạp web (story 2.7) dùng, nên hai lối vào không thể trôi khỏi nhau.
Nhãn quyền của mỗi tài liệu đọc từ frontmatter `scope`/`content_type` của chính
file; file hỏng bị từ chối kèm mã, không chặn file kế; re-ingest ghi đè sạch.

In số fact hợp lệ / bị loại của từng tài liệu (story 2.4, cùng số đi vào sự
kiện `extract_doc`), rồi tổng token và USD đọc từ `audit_log` cho **từng tài
liệu** (theo mốc thời gian bắt đầu/kết thúc mà pipeline ghi lại) rồi cả đợt;
ngoại lệ giữa đợt (đối chiếu lệch, 429) vẫn in số đã tiêu rồi mới dội lên.
`--xuat-json` ghi đúng số đó thành file có commit để `eval/ngoai_suy.py` đọc,
thay cho sáu hằng chép tay. Nằm ở `api/` vì `eval/` không import được hiện
thực Postgres. Script tốn tiền thật: chạy sau khi spec được duyệt.

Biến môi trường: bảy khóa kho (`adapters.engine.BIEN_MOI_TRUONG`), năm biến
Postgres (`api.audit_postgres.BIEN_POSTGRES`), ba biến model
(`adapters.llm_wrapper.BIEN_MOI_TRUONG_MODEL`) và key provider. Trên máy chủ,
host của các kho là IP container (`docker inspect`), key đọc từ `.env`;
`scripts/chay-may-chu.sh` dựng sẵn đủ bộ đó.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from adapters.ingest import (
    TRANG_THAI_DA_NAP,
    TRANG_THAI_DA_XOA,
    TRANG_THAI_KHONG_DOI,
    KetQuaNap,
    xoa_space,
)
from adapters.policy_loader import load_policy
from api.audit_postgres import AuditPostgres, TongChiPhi
from api.dot_nap import (
    TRANG_THAI_DOT_XONG,
    LanNap,
    chay_lan_nap,
    dung_engine_tu_moi_truong,
    ghi_so_do_json,
    so_do_nap,
)
from core.audit import thoi_diem_utc
from core.ingest_scan import quet_cac_file, quet_thu_muc

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_MAC_DINH = REPO_ROOT / "config" / "policy-toi-gian.yaml"

# Tiền tố của dòng `lenh` ghi vào file số đo: người đọc chương 4 phải dựng lại
# được đúng lệnh đã sinh ra con số, không chỉ biết "một lần nạp nào đó".
TIEN_TO_LENH: str = "uv run python -m api.do_chi_phi"


def _tham_so(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Nạp tài liệu qua pipeline ingest và đo chi phí LLM/embedding")
    p.add_argument("duong_dan", nargs="*", type=Path, help="một thư mục, hoặc các file .md/.txt theo thứ tự")
    p.add_argument("--space", default="synth", help="không gian dữ liệu (mặc định synth)")
    p.add_argument("--xoa-space", action="store_true", help="xóa sạch space rồi thoát, không nạp gì")
    p.add_argument("--ep-ghi-de", action="store_true", help="re-ingest cả tài liệu không đổi (cùng sha256 và nhãn)")
    p.add_argument("--policy", type=Path, default=POLICY_MAC_DINH, help="bảng chính sách lấy policy_version")
    p.add_argument(
        "--xuat-json",
        type=Path,
        default=None,
        metavar="FILE",
        help="ghi số đo của đợt (token/USD theo model) thành JSON; file này có commit",
    )
    ts = p.parse_args(argv)
    if not ts.xoa_space and not ts.duong_dan:
        p.error("cần một thư mục hoặc ít nhất một file, hoặc --xoa-space")
    if ts.xoa_space and ts.duong_dan:
        p.error("--xoa-space không đi cùng đường dẫn nạp")
    if ts.xoa_space and ts.xuat_json:
        p.error("--xuat-json cần một đợt nạp, không đi cùng --xoa-space")
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


def _in_dot(lan: LanNap) -> None:
    """Đầu ra console của một đợt: kết quả từng tài liệu, bảng theo tài liệu, bảng cả đợt."""
    in_ket_qua(lan.ket_qua)
    for c in lan.chi_phi_tai_lieu:
        in_tong(f"Tài liệu {c.doc_key} ({c.bat_dau} -> {c.ket_thuc or 'chưa xong'}):", c.tong)
    if lan.chi_phi is not None:
        in_tong(f"Cả đợt (thoi_diem >= {lan.bat_dau}):", lan.chi_phi)


def _xuat_json(ts: argparse.Namespace, lan: LanNap, argv: list[str]) -> None:
    """Ghi file số đo, chỉ khi đợt chạy trọn.

    Đợt dừng giữa chừng vẫn tiêu tiền thật, nhưng số của nó là số của *một
    phần* corpus; ghi đè lên file mà `eval/ngoai_suy.py` đọc là làm bảng ngoại
    suy của chương 4 nhỏ đi mà không ai biết vì sao. Nên đợt lỗi thì in một
    dòng nói không ghi, còn console vẫn có đủ số để đọc bằng mắt.
    """
    if lan.trang_thai != TRANG_THAI_DOT_XONG:
        print(
            f"\nkhông ghi {ts.xuat_json}: đợt dừng ở trạng thái {lan.trang_thai!r}"
            f" ({lan.ma_loi}); số đo của một đợt dở không thay được số đo cũ",
            flush=True,
        )
        return
    so_do = so_do_nap(lan, lenh=f"{TIEN_TO_LENH} {' '.join(argv)}")
    # Một đợt *chạy trọn* vẫn ra file vô nghĩa được: LLM trả `{"facts": []}` cho
    # mọi tài liệu thì mỗi tài liệu mang `KHONG_CO_FACT`, đợt vẫn `xong`, mà
    # `so_tai_lieu` là 0 - và `eval/ngoai_suy.py` chia cho nó. Cửa này chặn ở
    # nơi rẻ nhất: đừng ghi đè nguồn số của chương 4 bằng một file không dùng
    # được, bản cũ vẫn hơn.
    thieu = []
    if so_do["so_tai_lieu"] <= 0:
        thieu.append("không tài liệu nào nạp được (so_tai_lieu = 0)")
    if not so_do["theo_model"]:
        thieu.append("không lời gọi LLM/embedding nào trong cửa sổ của đợt")
    if thieu:
        print(
            f"\nkhông ghi {ts.xuat_json}: {'; '.join(thieu)}."
            " File số đo là mẫu số của bảng ngoại suy FR-30, nên bản cũ được giữ nguyên.",
            flush=True,
        )
        return
    dich = ghi_so_do_json(ts.xuat_json, so_do)
    print(f"\nghi số đo đợt vào {dich}", flush=True)


async def chay(ts: argparse.Namespace, argv: list[str] | None = None) -> TongChiPhi:
    policy = load_policy(ts.policy)
    audit = await AuditPostgres.mo()
    try:
        await audit.khoi_tao()
        if ts.xoa_space:
            # Bảng "Cả đợt" in cho *mọi* nhánh, đúng như bản trước story 2.7
            # (nó nằm trong `finally` nên nhánh xóa cũng có): xóa space là một
            # thao tác có thể tốn tiền embedding lúc `khoi_tao()` lại collection,
            # và một nhánh im lặng là một nhánh không ai đọc được đã tiêu gì.
            bat_dau = thoi_diem_utc()
            engine = dung_engine_tu_moi_truong(audit)
            try:
                await xoa_space(engine, space=ts.space, policy_version=policy.policy_version, audit=audit)
                print(f"[{thoi_diem_utc()}] đã xóa sạch space {ts.space!r}", flush=True)
            finally:
                await engine.dong()
            tong = await audit.tong_chi_phi(ts.space, tu=bat_dau)
            in_tong(f"Cả đợt (thoi_diem >= {bat_dau}):", tong)
            return tong

        if len(ts.duong_dan) == 1 and ts.duong_dan[0].is_dir():
            quet = quet_thu_muc(ts.duong_dan[0])
        else:
            quet = quet_cac_file(ts.duong_dan)
        lan = await chay_lan_nap(
            quet,
            space=ts.space,
            policy_version=policy.policy_version,
            audit=audit,
            ep_ghi_de=ts.ep_ghi_de,
        )
        _in_dot(lan)
        if ts.xuat_json:
            _xuat_json(ts, lan, list(argv or []))
        if lan.ngoai_le is not None:
            # Số đã in xong; giờ mới để lỗi dội lên như trước story 2.7.
            raise lan.ngoai_le
        return lan.chi_phi
    finally:
        await audit.dong()


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    asyncio.run(chay(_tham_so(argv), argv))


if __name__ == "__main__":
    main()
