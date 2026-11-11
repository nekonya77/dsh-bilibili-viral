#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TYPE="${1:-patch}"
MESSAGE="${2:-release}"
cd "$ROOT"

case "$TYPE" in
  patch|minor|major) ;;
  *) echo "用法: scripts/release.sh [patch|minor|major] [说明]" >&2; exit 1 ;;
esac

./scripts/ship.sh "chore: prepare $MESSAGE"
npm version "$TYPE" -m "chore: release v%s"
VERSION="$(node -p "require('./package.json').version")"
git push origin main
git push origin "v$VERSION"
echo "✓ 已发布 v$VERSION，等待 GitHub Actions 创建 Release"
