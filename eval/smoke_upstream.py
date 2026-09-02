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

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "eval" / "data"
WORK_DIR = REPO_ROOT / "eval" / "expr" / "smoke_upstream"

QUESTION = "Ai phê duyệt quyền ghi vào nhánh chính (main) và điều kiện là gì?"


def buoc(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%SZ')}] {msg}", flush=True)


def nap_key_tu_env() -> None:
    """Đọc OPENAI_API_KEY từ .env gốc repo; chỉ nhận dòng KEY=VALUE."""
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if line.startswith("OPENAI_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    os.environ.setdefault("OPENAI_API_KEY", value)
                    break
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
    for path in sorted(DATA_DIR.glob("*.txt")):
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
