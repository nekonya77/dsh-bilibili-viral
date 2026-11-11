#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MESSAGE="${1:-chore: update Bilibili viral radar}"
cd "$ROOT"

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
if git diff --cached --quiet; then
  echo "没有需要提交的改动"
  exit 0
fi

git commit -m "$MESSAGE"
git push origin main
echo "✓ 已推送 main"
