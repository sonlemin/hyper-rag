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

# tiktoken tai bang BPE qua mang o lan dem token dau tien
# (vendor/hypergraphrag/utils.py:158,168 goi `tiktoken.encoding_for_model`).
# Ca duong ingest (`chunking_by_token_size`) lan duong truy van
# (`truncate_list_by_token_size`) di qua do, ma container nay khong co mang ra
# ngoai trong thiet ke trien khai - nen tai san luc build va ghim vao image.
#
# Hai ten model lay tu chinh cho khai chung, khong viet tay ban thu hai: mot
# ten la default cua ham upstream, mot ten la field cua engine. Doi mot trong
# hai o do ma quen o day thi buoc nay am tham lam ap ten cu, nen
# `tests/test_khung_repo.py` ghim dung hai nguon ay.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" && uv run --no-sync python -c "\
import inspect, tiktoken; \
from hypergraphrag.utils import encode_string_by_tiktoken; \
from adapters.engine import EngineACL; \
ten = { \
  inspect.signature(encode_string_by_tiktoken).parameters['model_name'].default, \
  EngineACL.__dataclass_fields__['tiktoken_model_name'].default, \
}; \
[tiktoken.encoding_for_model(m).encode('warm') for m in sorted(ten)]; \
print('tiktoken warm:', sorted(ten))"

EXPOSE 8000
# --limit-concurrency 16 (story 3.8, ADR-022): tran dong thoi cua tien trinh
# phuc vu, thay cho mot semaphore trong ung dung (trang thai ngoai Postgres,
# AD-7) hay mot tran nhip theo tai khoan (chot nhan o ADR-022). Vuot tran thi
# uvicorn tra 503 van ban tran, khong envelope - gioi han da khai. Moi luot
# /hoi-dap la hai loi goi LLM tra tien, nen 16 request dang bay la tran tien
# cua mot khoanh khac. Service `api` giu CMD nay (khong `command` trong compose,
# `tests/test_compose_ha_tang.py` canh); `man-nap` co `command` rieng.
CMD ["uv", "run", "--no-sync", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "16"]
