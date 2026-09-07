#!/usr/bin/env bash
# Chay lint (tsc) + Playwright cua web/ tren may dev. Goi tu .githooks/post-commit
# khi commit cham web/, hoac chay tay. Ma thoat khac 0 la FAIL; khong co node hay
# chua `npm ci` cung la FAIL (khong phai bo qua).
set -uo pipefail
GOC="$(git rev-parse --show-toplevel)" || exit 1
cd "$GOC/web" || exit 1
if [ -z "${NVM_BIN:-}" ] && [ -d "$HOME/.nvm/versions/node" ]; then
    NODE_MOI="$(ls -d "$HOME"/.nvm/versions/node/v20* 2>/dev/null | tail -1)"
    [ -n "$NODE_MOI" ] && export PATH="$NODE_MOI/bin:$PATH"
fi
command -v node >/dev/null || { echo "[e2e] FAIL: khong co node (>=20.9) tren PATH" >&2; exit 1; }
[ -d node_modules ] || { echo "[e2e] FAIL: chua 'npm ci' trong web/" >&2; exit 1; }
echo "[e2e] tsc --noEmit"
npm run --silent lint || exit 1
echo "[e2e] playwright test (API_NOI_BO=${API_NOI_BO:-<khong dat, ca health that se skip>})"
npm run --silent test:e2e
