#!/usr/bin/env bash
# 定时任务看板 · 一键入口
#   board.sh                 生成 HTML（out/index.html）
#   board.sh --open          生成并用浏览器打开
#   board.sh --mode summary  打一份 Markdown 摘要
#   board.sh --mode json     输出原始 JSON
set -euo pipefail

# 解析软链，保证从任意位置（如 ~/.local/bin/sched-board）调用都能找到引擎
SELF="$0"
while [ -L "$SELF" ]; do
  TARGET="$(readlink "$SELF")"
  case "$TARGET" in
    /*) SELF="$TARGET" ;;
    *)  SELF="$(dirname "$SELF")/$TARGET" ;;
  esac
done
DIR="$(cd "$(dirname "$SELF")" && pwd)"

PY="/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "${PY:-}" ]; then
  echo "找不到 python3，请安装后重试（或用 PYTHON=/path/to/python3 board.sh）" >&2
  exit 1
fi

exec "$PY" "$DIR/build_board.py" "$@"
