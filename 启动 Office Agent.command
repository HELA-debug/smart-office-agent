#!/bin/sh
# macOS：双击这个文件即可启动（第一次可能提示「无法打开，因为来自身份不明的开发者」，
# 右键 → 打开 → 再点「打开」就行）。
cd "$(dirname "$0")" || exit 1

# 优先用项目自带的运行环境：跟 PATH 无关，之前启动过就一定在
if [ -x ".venv/bin/python" ] && .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  exec .venv/bin/python scripts/launch.py "$@"
fi

if ! command -v python3 >/dev/null 2>&1; then
  cat scripts/messages/no-python.txt
  read -r _
  open "https://www.python.org/downloads/" 2>/dev/null
  exit 1
fi

exec python3 scripts/launch.py "$@"
