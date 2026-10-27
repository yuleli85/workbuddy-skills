---
name: dify-github-bridge-bringup
description: 让 Dify 工作流「GitHub 提交抓取」重新取到数 —— 把 linmo-pig-full 的本地 GitHub API 兼容桥从「未播种」修到可用，并对齐 Dify 侧接线。当用户报「未能连上 GitHub API（status=0）」「GitHub 提交抓取 节点异常」「GITHUB_API_BASE / GITHUB_AUTH 配不通」「桥 health 是 degraded / available:false」「换了机器/重建容器后取数没了」时使用。覆盖：① 四态排障判据（status=0 / 401 / 503 未配置令牌 / 503 缺 HEAD）；② 播种令牌与 repo.bundle 到卷；③ 端到端验证矩阵（含数据一致性逐 sha 比对）；④ Dify 侧环境变量与 SSRF 白名单；⑤ 三种拓扑备选方案。
agent_created: true
---

# Dify「GitHub 提交抓取」桥：修复到可用

## 0. 先认清架构（**不要再参考 8799 那套，已废弃**）

| 项 | 现状 |
|---|---|
| 桥位置 | **在 `python-ai-service` 容器内**：`app/routers/bridge.py` + `app/services/github_bridge.py` |
| 对外端点 | `http://<宿主>:8090/internal/v1/bridge/*`（8090 绑定 `0.0.0.0`） |
| 关键子路径 | `/health`、`/repos/{owner}/{repo}/commits`（GitHub REST 兼容 + `Link` 分页 + `x-ratelimit-*`） |
| 令牌 | 环境变量 `GITHUB_BRIDGE_TOKEN` 优先；为空则读文件 `GITHUB_BRIDGE_TOKEN_FILE`（默认 `/bridge-secrets/token`） |
| 仓库数据 | `/repo-git`（卷 `linmo-ghbridge-git`）；缺 HEAD 时从 `/bridge-secrets/repo.bundle` 自举 `git clone --bare` |
| 令牌/快照卷 | `linmo-ghbridge-secrets` |
| fail-closed | 没令牌 → 拒绝服务（8090 对局域网发布，匿名可读 = 泄露私有仓提交历史），**这是刻意设计不是 bug** |
| 只读不 fetch | 桥只做 `git log`，**新鲜度 = 本机 clone 的新鲜度** |

> 旧世代（**已废弃，别再用**）：独立进程 `tools/github_commits_bridge.py` + `tools/github_bridge_start.cmd`，
> 跑在宿主机 **8799**、令牌在 `%USERPROFILE%\.linmo-bridge\token`、仅 Windows 脚本。
> 仓库里 `tools/dify/github-commits-fetch.workflow.yml` 的报错文案仍指向它（过期，会误导航）。

### 🔴 动手修桥之前，先判「现行链路到底走不走桥」（2026-10-15 实测）

**当前生产链路是直连 GitHub API，不走桥。** 证据链（全部可复现）：

1. 本机 `deploy-python-ai-1` 的桥是 `{"status":"degraded","available":false,"reason":"未配置令牌…fail-closed"}`，
   且该容器的 `Mounts` 为空（令牌卷/`/repo-git` 卷都没挂）。
2. 但 `ops_sync_log` 里 `github*` 三个连接器**每 15 分钟 SUCCESS**，`pulled_count` 有值。
   —— 若 Dify 指向桥，桥 fail-closed 必然让工作流 HTTP 节点 401/503，同步应 FAILED。
3. 库里条数与**真实 GitHub 分支逐条吻合**：`rev-list --count origin/main` = 1491 = 库内 linmo-pig-full 条数。

⇒ Dify 侧 `GITHUB_API_BASE` 指向的是**能直连 GitHub 的地址**（`ops_connector.base_url` 也写成
`https://api.github.com/repos/<owner>/<repo>`），`GITHUB_AUTH` 里有可用 PAT。
**桥现在是「换机器/内网无外网时的备用路径」，不是主路径。**

所以排障顺序要反过来：先看 `ops_connector.workflow_inputs` 的 **`sha`（分支）** 与工作流的
**`truncated`（400000 字符截断）**——这两个才是当前最常见的「同步全绿但没数据」根因，
判据见 `linmo-generic-ingest-source` §4.6。**只有确认取数真的打到桥**（工作流报
`status=0` / `401 Bad credentials` / `503 未配置令牌`），才进下面的 §1~§4。

---

## 1. 四态排障判据（第一步永远是这一张表）

| 现象 | 含义 | 动作 |
|---|---|---|
| 工作流报 **`status=0`** | **地址不通**（TCP 连不上） | 查 `GITHUB_API_BASE` 的主机/端口；确认该主机 8090 在听；确认 Dify 能路由到它；确认 Dify 的 squid 放行了私网 |
| **401 `Bad credentials`** | 令牌不匹配 | 比对 `~/.linmo-bridge/token` ↔ Dify 的 `GITHUB_AUTH`（注意 `Bearer ` 前缀） |
| **503「未配置令牌」** | 卷里没有令牌文件 | 走 §2 播种令牌 |
| **503「挂载点不存在 / 缺 HEAD」** | git 卷没数据 | 走 §2 播种 bundle（桥会自举 clone） |
| health 200 但 **`available:false`** | 有牌不亮 | `reason` 字段是中文的运维可读原因，照着做 |

```bash
# 一秒钟看桥自己的判断（reason 会说人话）
curl -s http://127.0.0.1:8090/internal/v1/bridge/health
```

---

## 2. 播种（本机侧修复）

```bash
D=/usr/local/bin/docker
REPO=/Users/shan/work/linmo-pig-full

# ① 令牌：落「仓库外」+ 卷内（绝不写进 deploy/.env* 这类 git 跟踪文件）
TOK="brg_$(python3 -c 'import secrets;print(secrets.token_hex(12))')"
mkdir -p ~/.linmo-bridge && printf '%s' "$TOK" > ~/.linmo-bridge/token && chmod 600 ~/.linmo-bridge/token
$D exec -i linmo-python-ai sh -c 'cat > /bridge-secrets/token && chmod 600 /bridge-secrets/token' <<< "$TOK"

# ② repo.bundle：单文件快照（Windows→WSL2 的 9p bind mount 会丢 objects/refs ⇒ 不许直接挂 .git）
cd "$REPO" && git bundle create /tmp/linmo-repo.bundle --all
git bundle verify /tmp/linmo-repo.bundle | tail -2      # 期望 "records a complete history"
$D cp /tmp/linmo-repo.bundle linmo-python-ai:/bridge-secrets/repo.bundle

# ③ 重启：token() 一旦读到空值会**缓存**，改完令牌文件不重启不生效
$D restart linmo-python-ai
```

**验证自举成功**（首次调用才克隆，若 503 就先调一次再调一次）：

```bash
curl -s -H "Authorization: Bearer $TOK" \
  'http://127.0.0.1:8090/internal/v1/bridge/repos/mzlc-linmo/linmo-pig-full/commits?per_page=3'
```

### 🔴 坑
- 令牌**不要**写 `deploy/.env.dev`（git 跟踪文件 ⇒ 凭据入库；本仓 `.env*` 已是存量欠账，别再加）。
- `docker cp` 到 `/bridge-secrets/...` 会**写进卷**（容器路径是卷挂载点），所以能持久化。
- 容器里要有 `git`（`linmo-python-ai` 已有 2.47.3）；没有的话得 `apt-get install git` 重建镜像。
- 宿主机 `grep` 是 shim，判定类结论用 Python/`grep -E`，别用 BRE 交替。

---

## 3. 验证矩阵（照抄，别只跑 health）

```bash
TOK=$(cat ~/.linmo-bridge/token)
LAN=$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)      # macOS 局域网 IP
B="http://$LAN:8090/internal/v1/bridge/repos/mzlc-linmo/linmo-pig-full/commits"

curl -s -o /dev/null -w 'health %{http_code}\n' "http://$LAN:8090/internal/v1/bridge/health"
curl -s -o /dev/null -w 'no-auth %{http_code}\n' "$B"                          # 期望 401
curl -s -D /tmp/h.txt -o /tmp/b.json -w 'auth %{http_code}\n' \
  -H "Authorization: Bearer $TOK" "$B?per_page=5"
grep -iE '^link:|^x-ratelimit' /tmp/h.txt                                      # 期望 rel="next" + 5000
```

**数据一致性（关键，必须做）**：桥的 `ref` 默认 `HEAD` ⇒ 与 `git rev-list HEAD`（**不是** `--all`）逐 sha 比对：

```bash
# 桥侧
curl -s -H "Authorization: Bearer $TOK" "$B?since=$S&until=$U&per_page=100&page=1" \
  | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>JSON.parse(s).forEach(c=>console.log(c.sha)))' | sort > /tmp/bridge_shas.txt
# 本地同口径
git rev-list HEAD --since=$S --until=$U | sort > /tmp/local_head.txt
diff /tmp/bridge_shas.txt /tmp/local_head.txt && echo "一致 ✅"
```

> 若与 `--all` 比对会多出别的分支的提交（例：`origin/dev-feature-gaoliang`）—— 那是**设计**，不是丢数。
> 要改口径：`GITHUB_BRIDGE_REF=refs/heads/main`（写 `deploy/.env.dev` 后重启 python-ai）。

---

## 4. Dify 侧接线（在 Dify 主机/控制台做）

**情况 A：Dify 与本机不是同一台机器**（本机现状：Dify 在 `192.168.110.172`，桥在 `192.168.110.19`）

| 变量 | 值 |
|---|---|
| `GITHUB_API_BASE` | `http://<本机局域网IP>:8090/internal/v1/bridge` |
| `GITHUB_AUTH` | `Bearer <令牌>`（secret 类型） |

并在 Dify 主机 `dify-docker/.env` 放行该网段后重建 `ssrf_proxy`：

```bash
SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.110.0/24      # squid 默认拦私有地址
docker compose -f dify-docker/docker-compose.yaml up -d ssrf_proxy
```

> 🔴 **`host.docker.internal:8090` 只在「Dify 与本机共用同一台 Docker 主机」时成立**；
> Dify 一旦迁到别的机器，它就解析成 Dify 主机自己 ⇒ `status=0`。本仓 compose 注释与历史记忆都写着这份旧结论，注意别照搬。
> 🔴 也不要用容器名（`linmo-python-ai`）—— 会被 ssrf_proxy 拦 403。

**情况 B：共用一台 Docker 主机** ⇒ `GITHUB_API_BASE=http://host.docker.internal:8090/internal/v1/bridge`（并确保 python-ai 在该主机上跑）。

**情况 C：不想依赖本地进程** ⇒ 拿 PAT 走官方 API，不改图：
`GITHUB_API_BASE=https://api.github.com`、`GITHUB_AUTH=Bearer github_pat_xxx`。

在 Dify 主机上的验证（期望 200）：

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer <令牌>' \
  'http://<本机IP>:8090/internal/v1/bridge/repos/mzlc-linmo/linmo-pig-full/commits?per_page=1'
```

---

## 5. 数据刷新（桥不变，但要喂新数据）

桥不 fetch ⇒ 内容 = 本机 clone 快照。刷新两步：

```bash
cd /Users/shan/work/linmo-pig-full && git pull            # 或走 git-quick-commit 技能
git bundle create /tmp/linmo-repo.bundle --all
docker cp /tmp/linmo-repo.bundle linmo-python-ai:/bridge-secrets/repo.bundle
# 无需重启：_last_fetch_failed 或 refs 缺失时才自举；常规用 bundle 增量 fetch
```

> 桥对**已有** git_dir 会走 `git fetch <bundle> '+refs/heads/*:refs/heads/*' --force` 增量更新；
> git_dir 缺 HEAD 时才 `git clone --bare`。所以只换 bundle 文件即可，不必删卷。

---

## 6. 收尾

- 报告落 `output/<主题>-YYYY-MM-DD.md`（`output/` 已被 `.gitignore` 忽略，不污染工作区）。
- 记忆：追加 `.workbuddy/memory/YYYY-MM-DD.md`（append-only + 回读校验「缺失行数 0」）。
- 提交记忆：`bash ~/.workbuddy/skills/git-quick-commit/scripts/git-fast.sh -m "..." --paths "a.md b.md"`。
- 红线：不动任何 `.env*`（本仓 `deploy/.env.dev`/`.env.head`/`.env.mac` 仍被跟踪，属存量欠账）。
