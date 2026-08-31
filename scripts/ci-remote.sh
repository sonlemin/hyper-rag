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
