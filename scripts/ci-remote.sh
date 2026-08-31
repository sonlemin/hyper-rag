#!/usr/bin/env bash
# CI toi gian cua khoa luan (khong GitHub Actions): dong bo repo len test server
# qua SSH, chay `uv run pytest` tai do, append ket qua + hash commit vao
# ~/ci-logs/ci.log tren server. Goi tu .githooks/post-commit sau moi commit.
# Bo qua mot lan: SKIP_CI=1 git commit ...
set -uo pipefail

SERVER="${CI_SERVER:-root@103.69.194.185}"
SSH_KEY="${CI_SSH_KEY:-$HOME/.ssh/hyper_rag_server}"
REMOTE_DIR="${CI_REMOTE_DIR:-/root/hyper-rag-copilot}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

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

# shellcheck disable=SC2016
ssh "${SSH_OPTS[@]}" "$SERVER" "COMMIT='$COMMIT' REMOTE_DIR='$REMOTE_DIR' bash -s" <<'REMOTE'
set -u
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$HOME/ci-logs"
cd "$REMOTE_DIR"
if uv run pytest; then st=PASS; else st=FAIL; fi
line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $COMMIT $st"
echo "$line" >> "$HOME/ci-logs/ci.log"
echo "[ci] $line"
[ "$st" = PASS ]
REMOTE
rc=$?
if [ $rc -ne 0 ]; then
    echo "[ci] FAIL (commit van duoc giu, sua roi commit tiep)" >&2
fi
exit $rc
