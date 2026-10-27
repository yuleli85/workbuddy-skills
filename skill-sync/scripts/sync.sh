#!/usr/bin/env bash
# skill-sync: 跨设备同步 WorkBuddy 用户级技能（git 底座）
# 用法: bash ~/.workbuddy/skills/skill-sync/scripts/sync.sh
set -uo pipefail

SKILLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${SKILLS_REMOTE:-origin}"
BRANCH="${SKILLS_BRANCH:-main}"
cd "$SKILLS_DIR" || exit 2

say() { printf '%s\n' "$*"; }

# --- 前置检查 -------------------------------------------------------------
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  say "RESULT: ERROR"
  say "REASON: $SKILLS_DIR 不是 git 仓库。新设备请先按 skill-sync/SKILL.md 的「新设备首次接入」操作。"
  exit 2
fi
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  say "RESULT: ERROR"
  say "REASON: 未配置远端 ${REMOTE}。请执行: git remote add origin <私有仓库地址>"
  exit 2
fi

# --- 1. 拉取远端 ----------------------------------------------------------
BEFORE="$(git rev-parse HEAD 2>/dev/null || echo none)"
if ! git fetch "$REMOTE" "$BRANCH" --quiet; then
  say "RESULT: ERROR"
  say "REASON: git fetch 失败（网络不可达 / 凭据失效）。检查后重试，或重新 gh auth login。"
  exit 1
fi
INCOMING="$(git rev-list --count HEAD.."$REMOTE/$BRANCH" 2>/dev/null || echo '?')"

if [ "$INCOMING" != "0" ]; then
  if ! git rebase --autostash "$REMOTE/$BRANCH"; then
    git rebase --abort 2>/dev/null
    git stash pop 2>/dev/null
    say "RESULT: CONFLICT"
    say "REASON: 本地与远端改动冲突，rebase 已安全回退（本地未动）。"
    say "修复: 手动 git pull --rebase origin main 解决冲突后重跑本脚本。"
    exit 1
  fi
fi

# --- 2. 本地变更 → 提交并推送 ---------------------------------------------
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  HOST="$(hostname -s 2>/dev/null || hostname)"
  git commit -m "sync: skills update from ${HOST} $(date +%F)" --quiet
  if ! git push "$REMOTE" "$BRANCH" --quiet; then
    say "RESULT: ERROR"
    say "REASON: git push 失败（网络 / 凭据 / 远端又有新提交）。可重跑一次本脚本。"
    exit 1
  fi
  PUSHED="$(git diff --name-only "$BEFORE" HEAD -- 2>/dev/null | wc -l | tr -d ' ')"
else
  PUSHED=0
fi

# --- 3. 摘要 --------------------------------------------------------------
say "RESULT: OK"
say "PULLED: ${INCOMING} 个远端提交"
say "PUSHED: ${PUSHED} 个本地文件变更"
say "SKILLS: $(ls -d -- */ 2>/dev/null | wc -l | tr -d ' ') 个技能目录"
