---
name: dify-mcp-tool-failure-triage
description: 排查「Dify 里的某个应用被当成 MCP 工具调用时失败」——如「MCP 服务端内部错误」「Can't operate on closed transaction inside context manager」「工具调用 401/404/超时」。把「应用本身健康」「MCP 端点路由」「MCP 传输层 bug」三层严格分开，给出可执行的修复或替代入口。当用户贴出这类报错、说「XX 智能问答工具调用失败」「MCP 服务端内部错误」「这个 MCP 服务怎么配置才能调」「某个智能体工具调不通」时使用。
agent_created: true
---

# Dify MCP 工具调用失败排查

## 0. 一句话判据（先做这个，30 秒定性）

**直接对 MCP 端点发一次 `tools/call`，看失败耗时：**

| 失败耗时 | 含义 |
|---|---|
| **< 200ms** | 代码级确定性 bug（事务被提前关、参数校验、end_user 缺失）。重试无用，别浪费时间 |
| **10s+** | 超时 / 资源 / 上游慢。看 `tool_mcp_providers.timeout` 和 SSRF 代理 |
| **立即 404/405** | 路由或 URL 形态错 |
| **立即 401** | 鉴权没配对 |

> 这条判据是我踩过坑总结的：症状文本完全一样，但根因可能相反。
> 别只读报错文本就下结论——**先量耗时**。

---

## 1. 正确 URL 形态（最容易搞错）

Dify ≥1.6 的**应用级 MCP Server** 是 Streamable HTTP，路径：

```
http://<host>/mcp/server/<server_code>/mcp      ← 正确
```

**不是** `/mcp`、`/mcp/`、`/mcp/server/<code>/sse`（旧 SSE 已废弃）。
`server_code` 从 `app_mcp_servers.server_code` 取（12 位大小写混合）。

探测脚本（用 GET 看状态码即可区分）：

```bash
C=<server_code>
for U in "/mcp" "/mcp/" "/mcp/server/$C/sse" "/mcp/server/$C/mcp"; do
  echo -n "GET $U -> "
  curl --noproxy '*' -s -o /dev/null -w "%{http_code}\n" -m 5 \
    -H 'Accept: text/event-stream, application/json' "http://<host>$U"
done
```

判读：
- `/mcp/server/$C/mcp` 返回 **405 = 路由存在**（只是 GET 不允许），✅ 用这条
- **404 = 路由未注册**（版本太老 / nginx `location /mcp` 没指向 api）
- **200** = 意外，说明后端对 GET 也响应了

→ 别再把 `/mcp` 根路径的 404 当成「这个版本不支持 MCP」，那条根路径从来就不挂载。

握手验证：

```bash
curl --noproxy '*' -s -X POST "http://<host>/mcp/server/$C/mcp" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"diag","version":"1"}}}'
```

成功会返回 `serverInfo.name=Dify` 和 `version`，**顺手就把 Dify 版本确认了**。

---

## 2. 证明应用本身健康（对照组）

绕开 MCP 直接打服务 API：

```bash
curl --noproxy '*' -s -o /dev/null -w "HTTP %{http_code} | %{time_total}s\n" \
  -X POST 'http://<host>/v1/chat-messages' \
  -H 'Authorization: Bearer app-<key>' -H 'Content-Type: application/json' \
  -d '{"inputs":{},"query":"<用户原问题>","response_mode":"blocking","user":"diag"}' --max-time 120
```

- 200 ⇒ 应用/数据源都好，问题在 MCP 传输层，**别去翻工作流节点**
- 非 200 ⇒ 转 `dify-remote-workflow-debug`

> ⚠️ 本机有 `HTTP_PROXY` 且 LAN 不在 `NO_PROXY` 内，探 LAN 必须加 `--noproxy '*'`，
> 否则拿到代理的假 502。

---

## 3. 已知确定性 bug：`Can't operate on closed transaction inside context manager`

**这个报错在 Dify 1.17.1（含 main）上是可复现的确定性 bug，不是竞态，重试 100% 无用。**

判据：`tools/call` 在 **30–70ms** 内返回 `error.code=-32603`，且 `tools/list` / `initialize` 都正常。

### 根因（两处代码）

`api/controllers/mcp/mcp.py` 用事务上下文包住整个请求：

```python
with sessionmaker(db.engine, expire_on_commit=False).begin() as session:
    ...
    return self._process_mcp_message(..., session, protocol_version)
```

`api/core/app/apps/advanced_chat/app_generator.py`（`_generate()`，「首次会话」分支）在同一个 session 上提前提交：

```python
if is_first_conversation:
    conversation.override_model_configs = workflow.features
    session.commit()                 # ← 关闭了外层事务
    session.refresh(conversation)    # ← InvalidRequestError
```

**为什么必然走「首次会话」**：MCP 工具参数只有 `query`（`prepare_tool_arguments` 不注入 `conversation_id`），每次调用都是新会话。

**为什么 `/v1/chat-messages` 没事**：它用 `db.session`，没有 `.begin()` 上下文，commit 后会自动开新事务。

### 修法（只改 MCP 控制器，不动业务代码）

把 `.begin()` 上下文换成普通 session + `finally close`：

```python
session = sessionmaker(db.engine, expire_on_commit=False)()
try:
    ...
    return self._process_mcp_message(..., session, protocol_version)
finally:
    session.close()
```

现成脚本：工作区 `fix_dify_mcp_transaction.sh`（幂等、带 dry-run 与 revert）。
离线验证方法：拿官方 `1.17.1` 的 `api/controllers/mcp/mcp.py` 跑一次替换 + `py_compile`。

⚠️ 不要改成 `session.flush()` 来「避免提交」——流式模式下会话行需要被 worker 进程看见，
不提交会破坏队列链路。只在 MCP 这层改 session 管理才安全。

### 实机落地步骤（2026-10-19 在 1.17.1 上验证通过）

```bash
# 1) 先核对容器内代码与替换块是否逐字符一致，别盲改
sshpass -p '<pwd>' ssh -o StrictHostKeyChecking=no <user>@<host> \
  'echo "<pwd>" | sudo -S -p "" docker exec docker-api-1 sed -n "70,100p" /app/api/controllers/mcp/mcp.py'

# 2) 推补丁脚本（本地 base64 → 远端解码，绕开引号地狱）
B64=$(base64 -i patch_mcp.py | tr -d '\n')
sshpass -p '<pwd>' ssh <user>@<host> "echo '$B64' | base64 -d > /tmp/_patch_mcp.py"

# 3) 进容器执行（脚本内置 match_count!=1 即中止 + py_compile）
sshpass -p '<pwd>' ssh <user>@<host> \
  'echo "<pwd>" | sudo -S -p "" docker cp /tmp/_patch_mcp.py docker-api-1:/tmp/ && \
   echo "<pwd>" | sudo -S -p "" docker exec docker-api-1 python3 /tmp/_patch_mcp.py'

# 4) 重启 + 等健康（实测约 30s）
docker restart docker-api-1
# 轮询 docker inspect -f '{{.State.Health.Status}}' 直到 healthy

# 5) 验收：tools/call 必须 200 且耗时 10s+（毫秒级成功才是异常）
```

**踩坑记录**

- 普通用户往往**不在 docker 组**，必须 `echo <pwd> | sudo -S -p "" docker …`；直接 `docker ps` 报 permission denied。
- 宿主机上可能同时跑着别的业务容器（如 `deployapp-*`），**按镜像名 `langgenius/dify-api` 认，别按名字猜**。
- `docker logs` 时间戳是 **UTC**，和你本地差 8 小时，判断「补丁前/后」时必须换算。
- 补丁只落在容器可写层，**`--force-recreate` 或换镜像就丢**。在宿主机留
  `/opt/dify-mcp-fix/{patch_mcp.py,apply.sh}`（apply 幂等，已打过不重启），重建后跑一次即可。
- `docker-worker-1` 是独立容器，没打补丁也不影响——worker 不服务 MCP 路由。


---

## 4. 表单配置要点（「修改 MCP 服务 (HTTP)」对话框）

| 字段 | 值 |
|---|---|
| 服务端点 URL | `http://<host>/mcp/server/<code>/mcp` |
| 服务器标识符 | 小写+数字+下划线/连字符，≤24 字符 |
| 认证 | **关掉「使用动态客户端注册」**（Dify 应用级 MCP 无鉴权，裸请求即 200） |
| 超时 | **≥120s**。默认/旧值 30s 对 15s 级的问答太紧 |

> `tool_mcp_providers.authed=t` 只说明握手成功过，不代表 `tools/call` 能用。

---

## 5. 查库定位（只读）

```bash
DSN=$(grep '^DIFY_DB_DSN=' deploy/.env | cut -d= -f2- | tr -d '"')
/opt/homebrew/opt/postgresql@16/bin/psql "$DSN" -tAc "<sql>"   # 不在默认 PATH
```

```sql
select a.name, m.server_code, m.status, m.parameters
  from app_mcp_servers m join apps a on a.id=m.app_id;

select id, name, server_identifier, authed, timeout, updated_at
  from tool_mcp_providers;

select app_id, agent_mode from app_model_configs where agent_mode like '%"mcp"%';
```

- `app_mcp_servers.status=active` 只代表**配置开了**，不代表端点可用
- 表结构坑：`app_mcp_servers` 的列是 `parameters`，**没有** `parameters_dict`（那是 ORM 属性名）
- `server_url` 是加密存储，读不出明文，别浪费时间解密

### 5.1 反查被 UI 遮罩的 MCP URL（很好用）

控制台把 URL 显示成 `http://host/******`，但表里同时存了 `server_url_hash`，
它是 **URL 的 SHA-256（小写 hex）**，不加密。拿候选地址算一遍就能确认真实值：

```bash
H=$(psql "$DSN" -tAc "select server_url_hash from tool_mcp_providers where server_identifier='finance';" | tr -d ' \n')
python3 - "$H" <<'PY'
import sys, hashlib
target = sys.argv[1]
for c in ["http://<host>/mcp/server/<code>/mcp", "http://<host>/mcp", "..."]:
    print("✅" if hashlib.sha256(c.encode()).hexdigest() == target else "  ", c)
PY
```

命中即证明「用户以为没配好，其实配得完全正确」，可直接排除配置因素。

---

## 6. 替代方案（不想打补丁时）

把应用包成 **OpenAPI 自定义工具**，直接打 `/v1/chat-messages`：

1. 控制台 → 工具 → 自定义 → 创建
2. 粘贴 OpenAPI schema（`servers.url` 指向 `/v1`，`operationId` 必填）
3. 认证选 API Key → Header `Authorization` → `Bearer app-xxx`

优点：零改代码、不怕升级覆盖。
代价：只有一问一答，没有 MCP 的结构化输出。

---

## 7. 次生坑

- **工具名带空格/中文**（Dify 用 `app.name` 当 tool name）。MCP 协议允许，但部分客户端
  function-calling 要求 `^[a-zA-Z0-9_-]{1,64}$`，会被过滤。报「工具不存在」时改应用名。
- **SSRF 代理**：MCP 客户端走 ssrf_proxy 时可能拦内网地址。但若报错文本来自 MCP server
  内部（如本次的事务错误），说明连通性没问题，别往这个方向查。

---

## 收尾

- 全程只读，不改 Dify 库；改配置走控制台。
- 结论分三段给：**应用是否健康 / 端点是否通 / 传输层是否有 bug**，不要混成一句「服务端异常」。
- 曾被推翻的旧结论：把该事务错误判为「并发竞态、重试就好」——**错**。已用 4/4 稳定失败 + 代码定位推翻。
