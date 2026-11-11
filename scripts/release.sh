#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TYPE="${1:-patch}"
MESSAGE="${2:-release}"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

case "$TYPE" in
  patch|minor|major) ;;
  *) echo "用法: scripts/release.sh [patch|minor|major] [说明]" >&2; exit 1 ;;
esac

./scripts/ship.sh "chore: prepare $MESSAGE"
npm version "$TYPE" -m "chore: release v%s"
VERSION="$(node -p "require('./package.json').version")"

if [ -n "${GITHUB_TOKEN:-}" ] || [ -n "${GH_TOKEN:-}" ]; then
  python3 scripts/api_sync.py --tag "v$VERSION" "chore: release v$VERSION"
else
  git push origin main
  git push origin "v$VERSION"
fi
echo "✓ 已发布 v$VERSION，等待 GitHub Actions 创建 Release"
