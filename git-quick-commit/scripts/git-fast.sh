#!/usr/bin/env bash
# git-fast.sh —— 代码拉取/提交/推送快速通道（一次调用跑完体检 + 同步 + 提交 + 推送）
#
# 用法:
#   git-fast.sh                     仅体检（默认，只读，不改动任何东西）
#   git-fast.sh --pull              fetch --all + 快进当前分支（只做 ff，绝不擅自 merge）
#   git-fast.sh --pull-all          同上，并把其它「只落后、不领先」的本地分支一并快进
#   git-fast.sh -m "msg"            体检 + 暂存全部改动 + 提交 + 推送
#   git-fast.sh -m "msg" --paths "a/b.ts c/d.ts"
#                                   只提交指定路径（并行会话活跃时强烈建议）
#   git-fast.sh -m "msg" --no-push  同上，但只提交不推送
#   git-fast.sh --push-only         跳过提交，只把已有本地提交推上去
#
# 环境变量:
#   GIT_FAST_RETRY    push 被拒后的最大自动重试轮数（默认 3）
#
# 仓库级配置（可选）: <repo>/.git-fast.conf
#   每行一个「必须保持未跟踪」的路径或 glob，'#' 开头为注释。
#   体检时逐条复检，被跟踪即报错 —— 专治 merge/rebase 把 .env 之类带回版本库。
# ---
# 维护注意: 双引号里「中文全角字符紧跟在 $VAR 之后」会被 bash 并入变量名
#   （已踩: `"$PATHS）"` ⇒ 变量名被解析成 `PATHS）`，set -u 下报 unbound variable）
#   ⇒ 变量后面若紧跟中文/全角符号，一律写成 ${VAR}。
set -uo pipefail

MSG=""
PATHS=""
CHECK_ONLY=1
PUSH_ONLY=0
PULL=0
PULL_ALL=0
DO_PUSH=1
RETRY="${GIT_FAST_RETRY:-3}"

# 🔴 macOS 本机 SSH 私钥带口令：不带这串会停在「Enter passphrase」把整条命令挂死
#    （自动化/后台跑必踩，2026-10-15 实测 exit 137）。用户已另配时以用户的为准。
if [ -z "${GIT_SSH_COMMAND:-}" ] && [ -f "$HOME/.ssh/pub" ]; then
  export GIT_SSH_COMMAND="ssh -o UseKeychain=yes -o IdentitiesOnly=yes -i $HOME/.ssh/pub -o BatchMode=yes"
fi

while [ $# -gt 0 ]; do
  case "$1" in
    -m|--message)
      [ $# -ge 2 ] || { echo "缺少 -m 的参数" >&2; exit 2; }
      MSG="$2"; CHECK_ONLY=0; shift 2 ;;
    --check)     CHECK_ONLY=1; shift ;;
    --pull)      PULL=1; CHECK_ONLY=0; DO_PUSH=0; shift ;;
    --pull-all)  PULL=1; PULL_ALL=1; CHECK_ONLY=0; DO_PUSH=0; shift ;;
    --push-only) PUSH_ONLY=1; CHECK_ONLY=0; shift ;;
    --no-push)   DO_PUSH=0; shift ;;
    --paths)
      [ $# -ge 2 ] || { echo "缺少 --paths 的参数" >&2; exit 2; }
      # 2026-10-16 修复：逗号/分号分隔会被整串当成一个 pathspec（git add fatal 后脚本仍继续提交暂存区 ⇒ 漏提交）。
      # 统一归一为空格分隔；并显式拒绝反引号等 shell 元字符防注入。
      PATHS="$(printf '%s' "$2" | tr ',;' '  ')"
      case "$PATHS" in *[\`$"\;"]*) echo "--paths 含非法字符" >&2; exit 2 ;; esac
      CHECK_ONLY=0; shift 2 ;;
    -h|--help)   awk 'NR>1 && /^# *---/ {exit} NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) echo "未知参数: $1（-h 看用法）" >&2; exit 2 ;;
  esac
done

RST=''; RED=''; GRN=''; YEL=''
if [ -t 1 ]; then RST='\033[0m'; RED='\033[31m'; GRN='\033[32m'; YEL='\033[33m'; fi
hdr() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }
ok()  { printf "  ${GRN}v${RST} %s\n" "$1"; }
warn(){ printf "  ${YEL}!${RST} %s\n" "$1"; }
bad() { printf "  ${RED}x${RST} %s\n" "$1"; }

TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || { bad "当前目录不在 git 仓库内"; exit 1; }
cd "$TOP" || exit 1
BR="$(git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD)"
UP="origin/$BR"
HAS_UP=0
git rev-parse --verify -q "$UP" >/dev/null 2>&1 && HAS_UP=1

# ---------- ref 自愈（并行 IDE/会话下 loose ref 会丢失）----------
heal_ref() {
  local short full cur
  short="$(git log -1 --format=%h 2>/dev/null)" || return 0
  [ -n "$short" ] || return 0
  full="$(git rev-parse "$short" 2>/dev/null)" || return 0
  [ -n "$full" ] || return 0
  cur="$(git rev-parse "$BR" 2>/dev/null || echo '')"
  if [ "$cur" != "$full" ]; then
    warn "分支 ref 与 HEAD 不一致（loose ref 丢失坑），重建 .git/refs/heads/$BR"
    mkdir -p ".git/refs/heads/$(dirname "$BR")"
    printf '%s\n' "$full" > ".git/refs/heads/$BR"
    if [ "$(git rev-parse "$BR" 2>/dev/null)" = "$full" ]; then
      ok "ref 已修复 -> $(printf '%.8s' "$full")"
    else
      bad "ref 修复失败，需人工处理"
    fi
  fi
}

# ---------- 脱跟踪复检（.git-fast.conf）----------
check_untrack() {
  [ -f .git-fast.conf ] || return 0
  hdr "脱跟踪复检（.git-fast.conf）"
  while IFS= read -r pat || [ -n "$pat" ]; do
    case "$pat" in ''|\#*) continue ;; esac
    if [ -n "$(git ls-files -- "$pat" 2>/dev/null)" ]; then
      bad "$pat 已被跟踪（应 git rm --cached 后重建）"
    else
      ok "$pat 未被跟踪"
    fi
  done < .git-fast.conf
}

# ---------- 拉取模式（fetch + 只允许快进；绝不擅自 merge）----------
if [ "$PULL" -eq 1 ]; then
  hdr "fetch --all --prune"
  git fetch --all --prune 2>&1 | sed 's/^/  /'
  ok "远端抓取完成"

  hdr "当前分支 $BR"
  if [ "$HAS_UP" -eq 0 ]; then
    warn "远端没有 ${UP}，无法快进"
  else
    A="$(git rev-list --count "$UP..HEAD" 2>/dev/null || echo 0)"
    B="$(git rev-list --count "HEAD..$UP" 2>/dev/null || echo 0)"
    if [ "$B" = "0" ]; then
      ok "已是最新（本地未推送 $A 个）"
    elif [ "$A" != "0" ]; then
      bad "双向分叉：本地领先 $A / 落后 $B ⇒ 脚本不擅自合并，需人工 merge/rebase"
    elif [ -n "$(git status --porcelain -uall)" ]; then
      bad "有未提交改动，先提交或 stash 再拉"
    else
      echo "  落后远端 $B 个："
      git log --oneline "HEAD..$UP" | head -15 | sed 's/^/    /'
      if git pull --ff-only >/tmp/_gitfast_pull.log 2>&1; then
        sed 's/^/  /' /tmp/_gitfast_pull.log
        heal_ref
        ok "快进完成 -> $(git log -1 --format='%h %s')"
      else
        sed 's/^/  /' /tmp/_gitfast_pull.log
        bad "快进失败，见上方输出"
        exit 1
      fi
    fi
  fi

  if [ "$PULL_ALL" -eq 1 ]; then
    hdr "其它本地分支（只快进「只落后」的）"
    git for-each-ref --format='%(refname:short)' refs/heads/ | while IFS= read -r b; do
      [ "$b" = "$BR" ] && continue
      if ! git rev-parse --verify -q "refs/remotes/origin/$b" >/dev/null 2>&1; then
        warn "$b 无远端同名分支，跳过"
        continue
      fi
      na="$(git rev-list --count "refs/remotes/origin/$b..refs/heads/$b" 2>/dev/null || echo 0)"
      nb="$(git rev-list --count "refs/heads/$b..refs/remotes/origin/$b" 2>/dev/null || echo 0)"
      if [ "$na" != "0" ]; then
        warn "$b 有本地独有提交（领先 $na），跳过"
      elif [ "$nb" = "0" ]; then
        ok "$b 已是最新"
      elif git fetch origin "$b:$b" >/dev/null 2>&1; then
        ok "$b 快进 $nb 个 -> $(git rev-parse --short "refs/heads/$b")"
      else
        bad "$b 快进失败"
      fi
    done
  else
    hdr "其它本地分支"
    echo "  提示: 加 --pull-all 可把「只落后、不领先」的本地分支一并快进"
  fi

  check_untrack
  hdr "完成"
  echo "  分支 $BR @ $(git log -1 --format='%h %s')"
  exit 0
fi

# ---------- 体检 ----------
hdr "位置"
echo "  仓库: $TOP"
echo "  分支: $BR"
if [ "$HAS_UP" -eq 1 ]; then
  echo "  上游: $UP"
else
  warn "远端没有 ${UP}（首次推送）"
fi

hdr "工作区（含未跟踪）"
ST="$(git status --porcelain -uall)"
if [ -z "$ST" ]; then
  ok "干净，无本地改动"
else
  printf '%s\n' "$ST" | sed 's/^/  /'
fi

hdr "与远端差距"
if [ "$HAS_UP" -eq 1 ]; then
  AHEAD="$(git rev-list --count "$UP..HEAD" 2>/dev/null || echo 0)"
  BEHIND="$(git rev-list --count "HEAD..$UP" 2>/dev/null || echo 0)"
  echo "  未推送: $AHEAD 个   远端未合入: $BEHIND 个"
  if [ "$AHEAD" != "0" ]; then git log --oneline "$UP..HEAD" | sed 's/^/    /'; fi
  if [ "$BEHIND" != "0" ]; then
    warn "远端领先，push 会被拒（本脚本会自动 fetch+merge 重试）"
    git log --oneline "HEAD..$UP" | head -10 | sed 's/^/    /'
  fi
else
  git log --oneline -5 | sed 's/^/  /'
fi

check_untrack

if [ "$CHECK_ONLY" -eq 1 ]; then
  hdr "结论"
  echo "  仅体检模式，未改动任何东西。"
  echo "  要提交: $0 -m \"<type>(<scope>): <描述>\""
  exit 0
fi

# ---------- 提交 ----------
if [ "$PUSH_ONLY" -eq 0 ]; then
  hdr "暂存与提交"
  if [ -n "$PATHS" ]; then
    # shellcheck disable=SC2086
    git add -- $PATHS
    echo "  （只暂存指定路径: ${PATHS}）"
  else
    git add -A
  fi
  if git diff --cached --quiet; then
    warn "无内容可提交（工作区为空）"
  else
    git status --short | sed 's/^/  /'
    MODS="$(git diff --cached --name-only | awk -F/ '{print $1}' | sort -u | tr '\n' ' ')"
    if [ "$(printf '%s' "$MODS" | wc -w | tr -d ' ')" -gt 1 ]; then
      warn "本次跨多个顶层模块：$MODS"
      warn "若其中含「别人正在写、非本次任务」的路径 ⇒ 改用 --paths 精确提交，别整锅端"
    fi
    if git commit -m "$MSG" >/tmp/_gitfast_commit.log 2>&1; then
      sed 's/^/  /' /tmp/_gitfast_commit.log
      ok "提交完成"
    else
      sed 's/^/  /' /tmp/_gitfast_commit.log
      bad "提交失败"
      exit 1
    fi
  fi
  heal_ref
fi

# ---------- 推送（含竞态自动重试）----------
if [ "$DO_PUSH" -eq 1 ]; then
  hdr "推送"
  if [ "$HAS_UP" -eq 0 ]; then
    out="$(git push -u origin "$BR" 2>&1)"; rc=$?
    printf '%s\n' "$out" | sed 's/^/  /'
    [ $rc -eq 0 ] && ok "推送成功（已建立上游）" || { bad "推送失败"; exit 1; }
  else
    n=0
    while :; do
      out="$(git push origin "$BR" 2>&1)"; rc=$?
      printf '%s\n' "$out" | sed 's/^/  /'
      [ $rc -eq 0 ] && { ok "推送成功"; break; }
      if printf '%s' "$out" | grep -qE 'fetch first|non-fast-forward|\[rejected\]'; then
        n=$((n + 1))
        if [ "$n" -gt "$RETRY" ]; then bad "重试 $RETRY 轮仍被拒，放弃"; exit 1; fi
        warn "远端已前移 —— 第 $n 轮: fetch -> merge -> 重试"
        git fetch origin "$BR" >/dev/null 2>&1 || { bad "fetch 失败"; exit 1; }
        if ! git merge "origin/$BR" --no-edit >/tmp/_gitfast_merge.log 2>&1; then
          sed 's/^/  /' /tmp/_gitfast_merge.log
          if grep -qE 'would be overwritten by merge|Please commit your changes or stash' /tmp/_gitfast_merge.log; then
            # 本地有未提交改动挡住 merge（多半是并行会话的在途文件）。
            # 禁忌: 绝不 stash / checkout —— 会吞掉对方未提交的工作。
            # 正解: worktree 隔离 —— 在 origin/BR 的干净副本上 merge 本地 HEAD，再直接 push HEAD:BR，
            #       主工作区一个字节都不动；本地分支稍后由对方提交时自然追上。
            warn "本地未提交改动挡住 merge（疑似并行会话在途文件）⇒ 改用 worktree 隔离合并推送"
            git merge --abort >/dev/null 2>&1 || true
            WT="$(mktemp -d "${TMPDIR:-/tmp}/gitfast-wt.XXXXXX")"; rmdir "$WT" 2>/dev/null || true
            HEAD_SHA="$(git rev-parse HEAD)"
            if git worktree add --detach "$WT" "origin/$BR" >/dev/null 2>&1; then
              if git -C "$WT" merge --no-edit "$HEAD_SHA" >/tmp/_gitfast_wt_merge.log 2>&1; then
                sed 's/^/  /' /tmp/_gitfast_wt_merge.log
                if git -C "$WT" push origin "HEAD:$BR" 2>&1 | sed 's/^/  /'; then
                  ok "worktree 隔离推送成功（主工作区零改动；本地 $BR 落后一提交，待对方提交后自然 ff）"
                  git worktree remove "$WT" --force >/dev/null 2>&1 || true
                  git worktree prune >/dev/null 2>&1 || true
                  break
                fi
                bad "worktree 内 push 仍被拒（远端又前移）⇒ 请重跑本脚本"
              else
                bad "worktree 内 merge 是真冲突，需人工解决："
                git -C "$WT" diff --name-only --diff-filter=U | sed 's/^/    冲突: /'
                echo "    worktree 已保留: $WT"
                exit 2
              fi
              git worktree remove "$WT" --force >/dev/null 2>&1 || true
              git worktree prune >/dev/null 2>&1 || true
            else
              bad "worktree 创建失败"
            fi
            echo "    备选: 手工 git worktree add --detach <tmp> origin/$BR && git -C <tmp> merge $HEAD_SHA && git -C <tmp> push origin HEAD:$BR"
            exit 2
          fi
          bad "merge 冲突，需人工解决："
          git diff --name-only --diff-filter=U | sed 's/^/    冲突: /'
          echo "    解完后: $0 --push-only"
          exit 2
        fi
        sed 's/^/  /' /tmp/_gitfast_merge.log
        heal_ref
        continue
      fi
      bad "推送失败（非竞态原因，见上方输出）"
      exit 1
    done
  fi
else
  warn "--no-push：已提交但未推送"
fi

hdr "完成"
echo "  分支 $BR @ $(git log -1 --format='%h %s')"
