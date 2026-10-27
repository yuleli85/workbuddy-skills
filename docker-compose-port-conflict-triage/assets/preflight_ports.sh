#!/usr/bin/env bash
# ============================================================
# 灵猫企管 —— 宿主端口占用前置检查（起容器之前跑）
#
# 【解决什么问题】
#   本仓有两套并行编排，**8888 / 9999 / 8090 三个宿主端口完全重叠**：
#     ① deploy/docker-compose.yml      project=deploy      私仓镜像版（拉镜像部署）
#     ② deploy/docker-compose.dev.yml  project=linmo-pig   本地构建版（容器内编译）
#   两套同时存在，或宿主机上另有手工容器 / 别的项目占着这些端口时，
#   `up -d` 会在「Container xxx Starting」阶段抛出：
#       Bind for 0.0.0.0:9999 failed: port is already allocated
#
#   这条报错的三个坑（正是本脚本要补的）：
#     · **不说占用者是谁** —— 只给端口号，不给容器名 / 进程名；
#     · **compose 在第一个服务失败即中止** —— 后面 8888/8090 是否也冲突根本看不到；
#     · **看起来像「刚才还好好的」** —— 上一次失败的容器处于 Created/Exited，
#       本次 `up` 照样给出 "Recreate → Recreated"，具备很强的误导性。
#
# 【用法】
#   tools/preflight_ports.sh                    # 体检 dev 编排（默认带 pcui profile）
#   tools/preflight_ports.sh --stack deploy     # 体检发布编排
#   tools/preflight_ports.sh --both             # 两套都体检（CI 的 up 之前推荐）
#   tools/preflight_ports.sh --who 9999         # 只查某个端口是谁占的
#   tools/preflight_ports.sh --no-profile       # 不带 pcui profile（不检查 8890）
#
# 【退出码】
#   0 = 全部端口要么空闲、要么被**本编排自己的**容器占着（up 会重建它，属正常）
#   1 = 存在外部占用（别的项目的容器 / 宿主进程）—— up 一定会失败
#   2 = 环境问题（docker 不可用、编排无法解析）
#
# 【为什么「本项目自己的容器占着」不算冲突】
#   compose 对配置/镜像变化过的服务走 Recreate：先 stop+rm 旧容器（此时端口释放），
#   再 create+start 新容器。所以只看 `ss` 有没有监听会**全员假报警**。
# ============================================================

set -uo pipefail   # 刻意不用 -e：要一次性收集完所有问题再报，而不是撞到第一个就退

# ------------------------------------------------------------
# 0. 定位仓库根 + docker 可执行文件
#    （本机 docker 可能不在 PATH 上，Docker Desktop 装在 /Applications 下）
# ------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

find_docker() {
  if command -v docker >/dev/null 2>&1; then command -v docker; return; fi
  for c in /Applications/Docker.app/Contents/Resources/bin/docker \
           /usr/local/bin/docker /usr/bin/docker; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  echo ""
}

DOCKER="$(find_docker)"
if [ -z "$DOCKER" ]; then
  echo "[preflight] 找不到 docker 可执行文件 —— 本机没装 Docker 或没在 PATH 上。" >&2
  exit 2
fi

if ! "$DOCKER" info >/dev/null 2>&1; then
  echo "[preflight] docker daemon 不可达（Docker Desktop 没启动？）。" >&2
  exit 2
fi

# ------------------------------------------------------------
# 1. 两套编排的已知契约（与 compose 文件一一对应，改编排时同步改这里）
#    PROJECT 必须与 compose 里的 `name:` 一致 —— 这是判断
#    「占端口的容器是不是我们自己」的唯一依据。
# ------------------------------------------------------------
PROJECT_DEV="linmo-pig"        # deploy/docker-compose.dev.yml 的 name:
PROJECT_DEPLOY="deploy"        # deploy/docker-compose.yml 无 name: ⇒ 默认取目录名 deploy

# 兜底端口表：只在「解析不出 compose 端口」时使用（值 = compose 里 HOST_*_PORT 的默认值）
FALLBACK_DEV_PORTS="9999 8888 8090 6380 8890"
FALLBACK_DEPLOY_PORTS="9999 8888 8090"

# ------------------------------------------------------------
# 2. 参数
# ------------------------------------------------------------
STACK="dev"
WITH_PROFILE=1
WHO_PORT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --stack)      STACK="${2:-dev}"; shift 2 ;;
    --both)       STACK="both"; shift ;;
    --who)        WHO_PORT="${2:-}"; shift 2 ;;
    --no-profile) WITH_PROFILE=0; shift ;;
    -h|--help)    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            echo "[preflight] 未知参数：$1（-h 看用法）" >&2; exit 2 ;;
  esac
done

# ------------------------------------------------------------
# 3. 工具函数
# ------------------------------------------------------------

# 列出占用某宿主端口的**运行中容器**：每行 "容器名<TAB>compose项目<TAB>compose服务"
containers_on_port() {
  "$DOCKER" ps --filter "publish=$1" \
    --format '{{.Names}}{{"\t"}}{{.Label "com.docker.compose.project"}}{{"\t"}}{{.Label "com.docker.compose.service"}}' 2>/dev/null
}

# 宿主进程监听（排除 docker-proxy：它只是容器的端口代理，由容器检查覆盖）
host_listener_on_port() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -lptnH 2>/dev/null | awk -v P="$p" '
      { n = split($4, a, ":"); if (a[n] == P) print }' | grep -v docker-proxy | head -1
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 { print $1, $2 }' | grep -v docker-proxy | head -1
    return
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -lnt 2>/dev/null | awk -v P="$p" '
      { n = split($4, a, ":"); if (a[n] == P) print }' | head -1
    return
  fi
  echo ""
}

# 从 `docker compose config --format json` 里抽出发布到宿主机的端口（去重、升序）
compose_published_ports() {
  local json
  json="$("$DOCKER" compose "${COMPOSE_ARGS[@]}" config --format json 2>/dev/null)" || return 1
  [ -n "$json" ] || return 1

  local ports=""
  if command -v python3 >/dev/null 2>&1; then
    ports="$(printf '%s' "$json" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
out = set()
for _, s in (d.get("services") or {}).items():
    for p in (s.get("ports") or []):
        pub = p.get("published")
        if pub:
            out.add(str(pub))
print(" ".join(sorted(out, key=lambda x: int(x))))
' 2>/dev/null)"
  fi
  # python3 不可用时的退化路径：JSON 是 pretty-print 的，`"published": "9999"` 可稳定提取
  if [ -z "$ports" ]; then
    ports="$(printf '%s' "$json" \
      | grep -o '"published"[[:space:]]*:[[:space:]]*"[0-9]*"' \
      | grep -o '[0-9]*' | sort -u -n | tr '\n' ' ')"
  fi
  [ -n "${ports// /}" ] || return 1
  echo "$ports"
}

# ------------------------------------------------------------
# 4. --who 模式：只回答「谁占着这个端口」
# ------------------------------------------------------------
if [ -n "$WHO_PORT" ]; then
  echo "=== 端口 $WHO_PORT 的占用者 ==="
  hit="$(containers_on_port "$WHO_PORT")"
  if [ -n "$hit" ]; then
    printf '%s\n' "$hit" | while IFS=$'\t' read -r name proj svc; do
      printf '  容器 : %s\n  编排 : %s\n  服务 : %s\n' "$name" "${proj:-<无标签：手工 docker run 创建>}" "${svc:-<无>}"
    done
  else
    echo "  （没有容器发布该端口）"
  fi
  lsn="$(host_listener_on_port "$WHO_PORT")"
  if [ -n "$lsn" ]; then
    # Docker Desktop 的端口转发进程（macOS 上是 com.docke / vpnkit，Linux 上是 docker-proxy）
    # 只是在替容器守端口，不是真的「宿主进程占用」，容器已经claim 过就不再重复报。
    case "$lsn" in
      *com.docke*|*vpnkit*|*docker-proxy*)
        [ -n "$hit" ] || printf '  宿主进程监听 : %s（容器端口转发）\n' "$lsn" ;;
      *) printf '  宿主进程监听 : %s\n' "$lsn" ;;
    esac
  fi
  [ -z "$hit" ] && [ -z "$lsn" ] && echo "  => 空闲"
  exit 0
fi

# ------------------------------------------------------------
# 5. 主流程：逐套编排检查
# ------------------------------------------------------------
TOTAL_FOREIGN=0

check_stack() {
  local stack="$1" label proj
  local -a files envs profiles

  case "$stack" in
    dev)
      label="dev 编排（本地构建版）"
      proj="$PROJECT_DEV"
      files=(-f deploy/docker-compose.dev.yml)
      envs=(--env-file deploy/.env.dev --env-file deploy/.env)
      profiles=()
      [ "$WITH_PROFILE" = "1" ] && profiles=(--profile pcui)
      ;;
    deploy)
      label="发布编排（私仓镜像版）"
      proj="$PROJECT_DEPLOY"
      files=(-f deploy/docker-compose.yml)
      envs=(--env-file deploy/.env)
      profiles=()
      ;;
    *)
      echo "[preflight] 未知编排：$stack（只支持 dev / deploy）" >&2
      return 2
      ;;
  esac

  # bash 3.2（macOS 自带）在 `set -u` 下会把**空数组**当未定义变量展开报错，
  # 所以这里不能用 `("${profiles[@]}" ...)` 一把拼 —— 逐个按长度判空追加。
  COMPOSE_ARGS=()
  if [ "${#profiles[@]}" -gt 0 ]; then COMPOSE_ARGS+=("${profiles[@]}"); fi
  COMPOSE_ARGS+=("${envs[@]}" "${files[@]}")

  echo
  echo "────────────────────────────────────────────────────────────"
  echo "  $label   project=$proj"
  echo "────────────────────────────────────────────────────────────"

  local ports
  if ! ports="$(compose_published_ports)" || [ -z "$ports" ]; then
    echo "  [警告] 解析不出编排的端口映射，改用内置默认表。"
    if [ "$stack" = "dev" ]; then ports="$FALLBACK_DEV_PORTS"; else ports="$FALLBACK_DEPLOY_PORTS"; fi
  fi
  echo "  本编排要占用的宿主端口：$ports"
  echo

  local p hit foreign_list=""
  for p in $ports; do
    hit="$(containers_on_port "$p")"
    if [ -n "$hit" ]; then
      local caught=0
      while IFS=$'\t' read -r name owner _svc; do
        [ -n "$name" ] || continue
        if [ "$owner" = "$proj" ]; then
          printf '  %-6s %-12s 容器 %s（本项目自有，up 会重建它）\n' "$p" "[自有]" "$name"
        else
          printf '  %-6s %-12s 容器 %s  来自 project=%s\n' \
            "$p" "[🔴 外部]" "$name" "${owner:-<无标签：手工 docker run 创建>}"
          foreign_list="$foreign_list$p:容器 $name (project=${owner:-无标签})"$'\n'
          caught=1
        fi
      done <<< "$hit"
      [ "$caught" = "1" ] && TOTAL_FOREIGN=$((TOTAL_FOREIGN + 1))
      continue
    fi

    local lsn
    lsn="$(host_listener_on_port "$p")"
    if [ -n "$lsn" ]; then
      printf '  %-6s %-12s 宿主进程：%s\n' "$p" "[🔴 外部]" "$lsn"
      foreign_list="$foreign_list$p:宿主进程 $lsn"$'\n'
      TOTAL_FOREIGN=$((TOTAL_FOREIGN + 1))
    else
      printf '  %-6s %-12s\n' "$p" "[空闲]"
    fi
  done

  if [ -n "$foreign_list" ]; then
    echo
    echo "  ⚠️  该编排有端口被外部占用 —— up -d 会在 Starting 阶段失败："
    printf '%s' "$foreign_list" | sed 's/^/      · /'
    echo
    echo "  处置（按顺序试）："
    echo "      1) 停掉另一套编排（本仓两套不可同时启动，8888/9999/8090 完全重叠）："
    echo "           $DOCKER compose -f deploy/docker-compose.yml rm -sf nginx pig python-ai"
    echo "         ⚠️ 保留 mysql —— dev 编排经外部网络 deploy_backend 直连 deploy-mysql-1。"
    echo "      2) 若是手工容器（无 project 标签）："
    echo "           $DOCKER rm -f <容器名>"
    echo "      3) 若是宿主进程："
    echo "           kill <pid>     # 或改用 HOST_*_PORT 错开端口（见 deploy/.env.dev）"
    echo "      4) 查完再确认一次："
    echo "           tools/preflight_ports.sh --who 9999"
    return 1
  fi

  echo
  echo "  ✅ 该编排的宿主端口全部可用（自有或空闲）。"
  return 0
}

# 先整体看一眼「两套编排是不是同时开着」—— 这是本仓最高频的撞端口原因
echo "=== 两套编排同时在跑吗？（running 容器按 project 归类）==="
RUNNING_PROJECTS="$("$DOCKER" ps --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u)"
printf '%s\n' "$RUNNING_PROJECTS" | sed 's/^/    project=/' | sed 's/project=$/project=<无标签：手工 docker run 创建>/'

if printf '%s' "$RUNNING_PROJECTS" | grep -qx "$PROJECT_DEV" \
   && printf '%s' "$RUNNING_PROJECTS" | grep -qx "$PROJECT_DEPLOY"; then
  echo
  echo "    🔴 检测到 $PROJECT_DEV 与 $PROJECT_DEPLOY **同时在跑** ——"
  echo "       这正是 9999/8888/8090 相互抢占的典型现场（见 deploy/docker-compose.yml 文件头）。"
fi

STATUS=0
case "$STACK" in
  dev)    check_stack dev    || STATUS=1 ;;
  deploy) check_stack deploy || STATUS=1 ;;
  both)   check_stack dev    || STATUS=1
          check_stack deploy || STATUS=1 ;;
esac

echo
echo "────────────────────────────────────────────────────────────"
if [ "$STATUS" = "0" ]; then
  echo "  preflight 通过：可以 up -d。"
else
  echo "  preflight 未通过：先清掉上面标 [🔴 外部] 的占用者，再 up -d。"
fi
echo "────────────────────────────────────────────────────────────"
exit "$STATUS"
