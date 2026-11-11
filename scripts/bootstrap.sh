#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

cd "$ROOT"

if [ ! -x "$VENV/bin/python" ]; then
  echo "→ 创建 .venv"
  "$PYTHON" -m venv "$VENV"
fi

echo "→ 安装 Python 依赖"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install -r requirements.txt

echo "→ 环境检查"
"$VENV/bin/python" -m bili_viral doctor

cat <<'EOF'

✓ 环境就绪。后续命令用：
  .venv/bin/python -m bili_viral collect --days 7 --open

B站字幕需要 Chrome 已登录 bilibili.com；首次读取 cookies 约 60 秒。
EOF
