#!/usr/bin/env bash
# CI toi gian cua khoa luan (khong GitHub Actions): dong bo repo len test server
# qua SSH, kiem compose config roi chay `uv run pytest` tai do, append ket qua
# + hash commit vao ~/ci-logs/ci.log tren server. Goi tu .githooks/post-commit.
# Bo qua mot lan: SKIP_CI=1 git commit ...
# Neu cay lam viec ban (co thay doi chua commit), dong log mang nhan DIRTY:
# ket qua khong chung nhan cho commit sach.
set -uo pipefail

SERVER="${CI_SERVER:-root@103.69.194.185}"
SSH_KEY="${CI_SSH_KEY:-$HOME/.ssh/hyper_rag_server}"
REMOTE_DIR="${CI_REMOTE_DIR:-/root/hyper-rag-copilot}"

REPO_ROOT="$(git rev-parse --show-toplevel)" || exit 1
if [ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT/.git" ]; then
    echo "[ci] khong xac dinh duoc goc repo, dung lai" >&2
    exit 1
fi
COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)" || exit 1
DIRTY=""
if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    DIRTY=" DIRTY"
    echo "[ci] canh bao: cay lam viec ban, dong log se mang nhan DIRTY"
fi
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

# Chong hai commit lien tiep chay CI cheo nhau (rsync de len nhau)
exec 9>"$HOME/.ci-remote.lock"
if ! flock -n 9; then
    echo "[ci] mot lan CI khac dang chay, bo qua lan nay"
    exit 0
fi

echo "[ci] dong bo $COMMIT len $SERVER:$REMOTE_DIR"
rsync -az --delete \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'spikes' \
    --exclude 'extra' \
    --exclude 'eval/expr' \
    --exclude 'hypergraphrag.log' \
    -e "ssh ${SSH_OPTS[*]}" \
    "$REPO_ROOT"/ "$SERVER:$REMOTE_DIR"/ || {
    echo "[ci] rsync that bai, bo qua lan chay nay" >&2
    exit 1
}

ssh "${SSH_OPTS[@]}" "$SERVER" \
    "COMMIT='$COMMIT' REMOTE_DIR='$REMOTE_DIR' DIRTY='$DIRTY' bash -s" <<'REMOTE'
set -u
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$HOME/ci-logs"
cd "$REMOTE_DIR" || { echo "[ci] khong vao duoc $REMOTE_DIR tren server" >&2; exit 1; }
st=PASS
# Kiem compose + env truoc: sua doi compose/.env.server hong phai bi bat o CI,
# khong doi den luc up tay moi lo.
if ! docker compose --env-file .env --env-file .env.server config --quiet; then
    echo "[ci] docker compose config FAIL" >&2
    st=FAIL
elif ! uv run pytest; then
    st=FAIL
else
    # Bo test can kho that (marker `neo4j` va `qdrant`): chi may chu nay co
    # container cua compose. Chay o day de nhung thu chi server that tra loi
    # duoc - Cypher hop le, payload index, hnsw_config, strict mode - duoc CI
    # giu xanh, khong phai mot lan chay tay. Bien *_REQUIRED bien "bo qua"
    # thanh "do": thieu bien moi truong ma van xanh la mot ket qua noi doi.
    ip_container() {
        docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1" 2>/dev/null
    }
    NEO4J_IP="$(ip_container hyper-rag-copilot-neo4j-1)"
    QDRANT_IP="$(ip_container hyper-rag-copilot-qdrant-1)"
    POSTGRES_IP="$(ip_container hyper-rag-copilot-postgres-1)"
    if [ -z "$NEO4J_IP" ] || [ -z "$QDRANT_IP" ] || [ -z "$POSTGRES_IP" ]; then
        # Thieu container la FAIL, khong phai "bo qua": mot dong PASS ma bo
        # marker chua chay la mot ket qua noi doi (cung ly do voi *_REQUIRED).
        thieu=""
        [ -z "$NEO4J_IP" ] && thieu="$thieu neo4j"
        [ -z "$QDRANT_IP" ] && thieu="$thieu qdrant"
        [ -z "$POSTGRES_IP" ] && thieu="$thieu postgres"
        echo "[ci] thieu container dang chay:$thieu - bo test kho that khong chay duoc" >&2
        st=FAIL
    else
        # Chi export dung bien bo test can, khong source ca .env: key LLM that
        # nam trong .env va khong duoc lot vao moi truong cua bo test (test phai
        # chay khong mang, khong key).
        doc_bien() { grep -E "^$2=" "$1" | head -n 1 | cut -d= -f2-; }
        export NEO4J_PASSWORD="$(doc_bien .env NEO4J_PASSWORD)"
        export POSTGRES_PASSWORD="$(doc_bien .env POSTGRES_PASSWORD)"
        export POSTGRES_USER="$(doc_bien .env.server POSTGRES_USER)"
        export POSTGRES_DB="$(doc_bien .env.server POSTGRES_DB)"
        if ! NEO4J_REQUIRED=1 NEO4J_URI="bolt://$NEO4J_IP:7687" \
             QDRANT_REQUIRED=1 QDRANT_URL="http://$QDRANT_IP:6333" \
             POSTGRES_REQUIRED=1 POSTGRES_HOST="$POSTGRES_IP" \
             uv run pytest -m "neo4j or qdrant or postgres"; then
            st=FAIL
        fi
    fi
fi
line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $COMMIT $st$DIRTY"
echo "$line" >> "$HOME/ci-logs/ci.log"
echo "[ci] $line"
[ "$st" = PASS ]
REMOTE
rc=$?
if [ $rc -ne 0 ]; then
    echo "[ci] FAIL (commit van duoc giu, sua roi commit tiep)" >&2
fi
exit $rc
