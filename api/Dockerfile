# Image api: Python 3.12 + uv, cai dependency tu uv.lock (frozen).
# Build context la goc repo (xem docker-compose.yml).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Cai dependency truoc de tan dung layer cache
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy cac package can cho api (khong copy tests/, eval/, spikes/...)
COPY vendor ./vendor
COPY core ./core
COPY adapters ./adapters
COPY api ./api
COPY redteam ./redteam
# Bang chinh sach la du lieu cau hinh (AD-6), khong phai code, nhung loader doc
# no luc chay: khong copy thi container khong tim thay `config/policy-*.yaml`.
COPY config ./config
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
