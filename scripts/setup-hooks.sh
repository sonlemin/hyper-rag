#!/usr/bin/env bash
# Cai hook CI cho repo: tro git vao .githooks/ (chay mot lan sau khi clone).
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
chmod +x "$REPO_ROOT/.githooks/post-commit" "$REPO_ROOT/scripts/ci-remote.sh" "$REPO_ROOT/scripts/e2e-web.sh"
git -C "$REPO_ROOT" config core.hooksPath .githooks
echo "[ci] da cai core.hooksPath=.githooks; moi commit se chay CI tren test server"
