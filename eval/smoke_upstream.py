"""Smoke E2E chạy tay (ngoài CI): engine upstream trả lời câu hỏi tiếng Việt.

Bằng chứng story 1.1 / kịch bản 1.1-E2E-001: fork ghim d587cdf chạy trên
Python 3.12, nạp 3-5 tài liệu tiếng Việt dựng tay trong eval/data/ rồi trả
lời một câu hỏi có nội dung từ tài liệu.

Dùng storage mặc định của upstream (JsonKV + NanoVectorDB + NetworkX) nên
không cần 3 kho Docker; LLM theo cấu hình spike đã chứng minh
(gpt-4o-mini + text-embedding-3-small, mặc định của upstream).

Chạy: uv run python eval/smoke_upstream.py
Key đọc từ .env gốc repo (OPENAI_API_KEY); thiếu key thì báo tên biến và thoát.
"""

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.ingest_scan import tach_frontmatter
from eval import nap_bien_tu_env

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "eval" / "data"
WORK_DIR = REPO_ROOT / "eval" / "expr" / "smoke_upstream"

QUESTION = "Ai phê duyệt quyền ghi vào nhánh chính (main) và điều kiện là gì?"


TAI_LIEU_BANG_CHUNG_1_1: tuple[str, ...] = (
    "01-cap-quyen-gitlab.txt",
    "02-vpn-va-mat-khau.txt",
    "03-truc-su-co.txt",
    "04-sao-luu-du-lieu.txt",
)


def chon_tai_lieu(thu_muc: Path) -> list[Path]:
    """Bon tai lieu cua lan chay bang chung 1.1, ghim theo ten.

    Story 2.5 mo rong `eval/data/` len 10 file lam bo vang trich xuat, con
    smoke nay phai tai tao duoc dung lan chay da bao cao o story 1.1 (4 tai
    lieu; `05-*` them o story 2.4). Ghim ten thay vi cat theo thu tu: mot file
    `00-*.txt` them vao thu muc se day `01-cap-quyen-gitlab.txt` - tai lieu duy
    nhat tra loi duoc QUESTION - ra khoi tap nap ma guard "3-5 tai lieu" van
    qua, tuc smoke xanh tren mot cau tra loi sai.
    """
    return [thu_muc / ten for ten in TAI_LIEU_BANG_CHUNG_1_1]


def buoc(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%SZ')}] {msg}", flush=True)


def nap_key_tu_env() -> None:
    """Doc OPENAI_API_KEY tu .env goc repo qua cua chung `eval.nap_bien_tu_env`.

    Story 2.6 gom luat doc `.env` ve mot noi: hai ban chep cua cung mot luat doc
    secret la hai cho de chung lech nhau.
    """
    nap_bien_tu_env("OPENAI_API_KEY")
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "LOI: thieu bien OPENAI_API_KEY (khai trong .env goc repo hoac export truoc khi chay)",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    buoc("Buoc 1: nap OPENAI_API_KEY tu .env goc repo")
    nap_key_tu_env()

    buoc(f"Buoc 2: doc tai lieu tieng Viet trong {DATA_DIR.relative_to(REPO_ROOT)}")
    docs = []
    for path in chon_tai_lieu(DATA_DIR):
        # Từ story 2.3 file trong eval/data/ mang frontmatter scope/content_type
        # cho pipeline ingest; smoke upstream chỉ cần phần thân.
        _, text = tach_frontmatter(path.read_text(encoding="utf-8"))
        text = text.strip()
        docs.append(text)
        buoc(f"  - {path.name}: {len(text)} ky tu")
    if not (3 <= len(docs) <= 5):
        print(f"LOI: can 3-5 tai lieu trong eval/data/, thay {len(docs)}", file=sys.stderr)
        sys.exit(1)

    buoc("Buoc 3: khoi tao HyperGraphRAG storage mac dinh (khong can 3 kho Docker)")
    from hypergraphrag import HyperGraphRAG, QueryParam  # import cham: sau khi co key

    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True)
    rag = HyperGraphRAG(working_dir=str(WORK_DIR))

    buoc(f"Buoc 4: insert {len(docs)} tai lieu (goi LLM trich xuat, mat vai phut)")
    rag.insert(docs)
    buoc(f"  insert xong; file trong working_dir: {sorted(p.name for p in WORK_DIR.iterdir())}")

    buoc(f"Buoc 5: query (hybrid): {QUESTION}")
    answer = rag.query(QUESTION, param=QueryParam(mode="hybrid"))

    print("\n--- CAU TRA LOI ---\n")
    print(answer)
    print("\n--- HET ---")
    buoc("Smoke xong. Doi chieu tay: cau tra loi phai neu CTO/Giam doc Ky thuat va dieu kien Senior.")


if __name__ == "__main__":
    main()
