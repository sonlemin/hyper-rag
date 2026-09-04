#!/usr/bin/env bash
# Chay lenh cua du an tren may chu voi dung moi truong cua stack compose.
# Ban trong repo cua /root/hyper-rag-data/chay_2_6.sh (story 2.7 dua no vao git:
# script sinh ra so do cua chuong 4 ma khong nam trong lich su la mot buoc khong
# tai tao duoc).
#
#   scripts/chay-may-chu.sh nap eval/data
#   scripts/chay-may-chu.sh nap eval/data --ep-ghi-de --xuat-json eval/so_do_nap/nap-that.json
#   scripts/chay-may-chu.sh xoa --xoa-space --space synth
#   HYPER_RAG_MODULE=eval.chup_do_thi scripts/chay-may-chu.sh chup --space synth
#   HYPER_RAG_MODULE=eval.ct03 scripts/chay-may-chu.sh ct03 --space synth
#   HYPER_RAG_CUC_BO=1 scripts/chay-may-chu.sh nap /root/hyper-rag-data/real --space real
#
# Tham so dau la *ten buoc* (chi de doc log), phan con lai di thang vao module
# diem vao. Chay tren may chu, trong /root/hyper-rag-copilot.
#
# DIEM VAO (story 2.9): mac dinh `api.do_chi_phi`, doi duoc bang HYPER_RAG_MODULE.
# Story 2.10 them `eval.ct03` (doc thuan, khong ton tien) vao danh sach cho phep.
# Truoc 2.9 ten module ghim cung trong script, nen `eval.chup_do_thi` - lenh doc
# do thi de gan nhan truy hoi vang - phai tu dung lai ca khoi moi truong nay.
# Mot ban sao thu hai cua khoi do la mot bo tham so se troi khoi ban nay.
#
# DUONG CUC BO (story 2.11): HYPER_RAG_CUC_BO=1 them mot lop `.env.local-llm`
# (LLM_MODEL/EMBEDDING_MODEL cua Ollama) va tra them IP container `ollama`.
# Lop nay `source` SAU .env.server nen no thang, va do la ly do no la mot file
# chu khong phai hai bien tren dong lenh: `set -a` + `source` ghi de moi bien
# truyen tu ngoai, im lang. Space `real` chi chay provider cuc bo (AD-12), nen
# chay nham cau hinh mac dinh la gui tai lieu cong ty ra API ngoai.
#
# Bien doc SAU `source .env.server` (vong review 03/09): gan truoc thi mot khai
# bao HYPER_RAG_MODULE trong .env.server bi bo qua im lang va nguoi chay tuong
# minh dang chup trong khi that ra dang nap - tuc dang tieu tien.
# Danh sach cho phep chu khong phai chuoi tu do: so module hop le la mot con so
# dong, va `python -m <chuoi bat ky>` tu moi truong la mot cua chay code khong
# can den.
#
# THU MUC LAM VIEC (story 2.7, cho de vo nhat): kho KV va so tai lieu song trong
# HYPER_RAG_WORKING_DIR. Container `api`/`man-nap` dung volume `hyper_rag_api_data`
# mount o /data, va compose dat HYPER_RAG_WORKING_DIR=/data/hyper-rag. Script nay
# chay tren *host*, nen no phai tro vao dung thu muc do qua mountpoint cua volume;
# neu khong, CLI va man nhin cung Neo4j/Qdrant nhung khac so tai lieu va khac
# flock - nap qua man khi so trong ma kho day se ra DA_CO_TRONG_KHO hoac de lai
# rac. `tests/test_scripts_may_chu.py` canh hai ben con khop.
# `-e` cố ý: `source .env` hỏng, `docker volume inspect` trượt hay `cd` trượt
# đều phải dừng ngay. Không có nó thì script chạy tiếp với môi trường nửa vời
# và lỗi nổ muộn ở tầng driver, nơi thông điệp không nói được nguyên nhân.
set -euo pipefail

REMOTE_DIR="${HYPER_RAG_REPO:-/root/hyper-rag-copilot}"
VOLUME_API="${HYPER_RAG_VOLUME:-hyper_rag_api_data}"
MODULE_MAC_DINH="api.do_chi_phi"
FILE_CUC_BO=".env.local-llm"
MODULE_CHO_PHEP="api.do_chi_phi eval.chup_do_thi eval.ct03"
# Duong dan con ben trong volume, khop HYPER_RAG_WORKING_DIR cua docker-compose.yml
# (`api_data:/data` + `/data/hyper-rag`).
DUONG_DAN_CON="hyper-rag"

if [ "$#" -lt 1 ]; then
    echo "dung: HYPER_RAG_MODULE=<$(echo "$MODULE_CHO_PHEP" | tr ' ' '|')> $0 <ten-buoc> [tham so cua module...]" >&2
    echo "  vi du: $0 nap eval/corpus --xuat-json eval/so_do_nap/nap-that.json" >&2
    echo "  vi du: HYPER_RAG_MODULE=eval.chup_do_thi $0 chup --space synth" >&2
    exit 2
fi

export PATH="$HOME/.local/bin:$PATH"
cd "$REMOTE_DIR" || { echo "khong vao duoc $REMOTE_DIR" >&2; exit 1; }

for f in .env .env.server; do
    [ -r "$f" ] || { echo "thieu $REMOTE_DIR/$f (khong doc duoc)" >&2; exit 1; }
done

# .env (secret) + .env.server (tham so). Chi o day, khong bao gio trong bo test.
set -a
# shellcheck disable=SC1091
source .env
# shellcheck disable=SC1091
source .env.server
set +a

CUC_BO="${HYPER_RAG_CUC_BO:-0}"
if [ "$CUC_BO" = "1" ]; then
    [ -r "$FILE_CUC_BO" ] || { echo "thieu $REMOTE_DIR/$FILE_CUC_BO (khong doc duoc)" >&2; exit 1; }
    set -a
    # shellcheck disable=SC1091
    source "$FILE_CUC_BO"
    set +a
fi

MODULE="${HYPER_RAG_MODULE:-$MODULE_MAC_DINH}"
hop_le=0
for m in $MODULE_CHO_PHEP; do
    [ "$m" = "$MODULE" ] && hop_le=1
done
if [ "$hop_le" -ne 1 ]; then
    echo "HYPER_RAG_MODULE=$MODULE khong nam trong danh sach cho phep: $MODULE_CHO_PHEP" >&2
    exit 2
fi

ip_container() {
    docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" "hyper-rag-copilot-$1-1" 2>/dev/null
}

MOUNTPOINT="$(docker volume inspect -f '{{.Mountpoint}}' "$VOLUME_API")" || {
    echo "khong doc duoc mountpoint cua volume $VOLUME_API (stack da len chua?)" >&2
    exit 1
}

# IP rong thi export "bolt://:7687" roi de loi no muon o tang driver, noi thong
# diep khong noi duoc container nao thieu. Bat o day, cung tinh than voi
# scripts/ci-remote.sh ("thieu container la FAIL, khong phai bo qua").
# `|| true` la co y: duoi `set -e`, mot lenh thay the that bai trong phep gan se
# thoat ngay va khong ai doc duoc dong loi ben duoi.
NEO4J_IP="$(ip_container neo4j || true)"
QDRANT_IP="$(ip_container qdrant || true)"
POSTGRES_IP="$(ip_container postgres || true)"
thieu=""
if [ -z "$NEO4J_IP" ]; then thieu="$thieu neo4j"; fi
if [ -z "$QDRANT_IP" ]; then thieu="$thieu qdrant"; fi
if [ -z "$POSTGRES_IP" ]; then thieu="$thieu postgres"; fi
# Container thu tu, chi khi chay duong cuc bo. Thieu no la FAIL chu khong phai
# roi ve API ngoai: space `real` khong co nhanh fallback (AD-12), va mot
# `OLLAMA_HOST` con tro `http://ollama:11434` tu .env.server thi chi hong o
# tang driver, noi thong diep khong noi duoc profile local-llm chua len.
OLLAMA_IP=""
if [ "$CUC_BO" = "1" ]; then
    OLLAMA_IP="$(ip_container ollama || true)"
    if [ -z "$OLLAMA_IP" ]; then thieu="$thieu ollama(profile local-llm)"; fi
fi
if [ -n "$thieu" ]; then
    echo "khong lay duoc IP container dang chay:$thieu - stack chua len?" >&2
    exit 1
fi

export NEO4J_URI="bolt://$NEO4J_IP:7687"
export NEO4J_USERNAME=neo4j
export QDRANT_URL="http://$QDRANT_IP:6333"
export POSTGRES_HOST="$POSTGRES_IP"
export HYPER_RAG_WORKING_DIR="$MOUNTPOINT/$DUONG_DAN_CON"
if [ "$CUC_BO" = "1" ]; then
    export OLLAMA_HOST="http://$OLLAMA_IP:11434"
fi

buoc="$1"; shift
echo "[$(date -u +%FT%TZ)] BAT DAU $buoc (module=$MODULE, working_dir=$HYPER_RAG_WORKING_DIR, cuc_bo=$CUC_BO, llm=${LLM_MODEL:-?}, embedding=${EMBEDDING_MODEL:-?})"
# `set -e` khong duoc lam mat dong KET THUC: ma thoat cua lan chay la thu can doc.
rc=0
uv run python -m "$MODULE" "$@" || rc=$?
echo "[$(date -u +%FT%TZ)] KET THUC $buoc rc=$rc"
exit $rc
