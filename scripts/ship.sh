#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MESSAGE="${1:-chore: update Bilibili viral radar}"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ ! -d .git ]; then
  echo "✗ 当前目录不是 git 仓库" >&2
  exit 1
fi

echo "→ Python 单测"
python3 -m unittest discover -s tests -v

echo "→ bundle 校验"
node scripts/validate-bundle.mjs

echo "→ npm pack 干跑"
npm pack --dry-run >/dev/null

git add -A
if ! git diff --cached --quiet; then
  git commit -m "$MESSAGE"
fi

if [ -n "${GITHUB_TOKEN:-}" ] || [ -n "${GH_TOKEN:-}" ]; then
  echo "→ 通过 GitHub API 同步（api.github.com）"
  python3 scripts/api_sync.py "$MESSAGE"
else
  echo "→ 通过 git push 同步"
  git push origin main
fi
