"""Khung FastAPI tối thiểu cho story 1.1: chỉ GET /health.

JWT, handlers, ingest, audit... vào từ các story sau.
"""

from fastapi import FastAPI

app = FastAPI(title="hyper-rag-copilot")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
