---
name: linmo-finance-agent-no-data-triage
description: 排查灵猫企管（linmo-pig-full）「财务智能体没有数据 / 该账套尚未生成真实财务报告 / dashboard/refresh 返回 PYTHON_RESULT_UNVERIFIED」并修到「能定位到唯一剩余阻塞」。覆盖六层：L0 账套 OpenAPI 429 限流（最常见、最快判据）、L1 编码登记 SQL 守卫错配（静默 no-op）、L2 ai_app_config 无 Key/未启用、L3 Dify 工作流 HTTP 节点指向已下线主机、L4 上游账套系统迁址、L5 聚合节点现金流校验口径错配（净额+截止日 vs 整月毛额，节点全绿也必空）。触发词：财务智能体没有数据 / 财务页面空 / 该账套尚未生成真实财务报告 / PYTHON_RESULT_UNVERIFIED / finance-data-v2 / 账套授权核验失败 / 429 / cash movement mismatch / CASH_FLOW_UNVERIFIED。
agent_created: true
---

# 财务智能体「没有数据」五层排查

适用：`部门汇报 → 财务智能体` 无正文、空态「该账套尚未生成真实财务报告」，或
`POST /admin/ai/finance/books/dashboard/refresh` 返回 `500 PYTHON_RESULT_UNVERIFIED`。

🔴 **本链路有 5 层，L0/L3/L4 在外部**。别看到一层就动手 —— 按 L0→L1→L2→L3→L4 顺序逐层排除，
每层都有**确定性判据**。2026-10-10 曾误判为「只有一层」，2026-10-11 实测证明是四层叠加，
2026-10-19 又补出 L0（限流），是当期真正的根因。

---

## L0 — 账套 OpenAPI 429 限流（**先查这层，30 秒定性**）

**判据**：`ai_finance_run` 里连续多条 `UNKNOWN / PYTHON_RESULT_UNVERIFIED`，且 Dify 侧
`workflow_node_executions` 的第一个 http-request（title「确认授权账套」）是 `exception`：

```bash
DSN=$(grep -E '^DIFY_DB_DSN=' deploy/.env.dev | head -1 | cut -d= -f2-)
$PSQL "$DSN" -A -F$'\t' -c \
 "SELECT title,status,left(outputs::text,200) FROM workflow_node_executions
  WHERE workflow_run_id='<最近一次 failed 的 run_id>' ORDER BY index LIMIT 3;"
# 命中特征：status_code=0 / body={"ok":false,"error":{"code":"TRANSPORT_ERROR"}}
#           / error_message="Request failed with status code 429"
```

**要点**（2026-10-19 实测，别再走弯路）：

- 429 时整轮 **0.8~2s 就 failed**（不是超时、不是域名不通）；凭证/域名/Key 全都是对的。
- **同一个图、同一套 env**，10:50 能跑通、10:53 全部 429 ⇒ 就是配额，不要怀疑 `c_wz_nt` 密钥过期。
  每次 run 会打 **11 个**账套接口，连跑几次就把配额打光。
- `/books/{book}/cash-flow?days=N` 会穿透到工作流 → 必挂（实测 9s 后 502）。**做对话/实时页面不要用这个接口**，
  改用预加载快照 `GET /admin/ai/finance/books/dashboard`（含 30 天现金流 + runway + 最近报告状态，不发上游请求）。
- **别指望「重发一次就好」**：冷却期内连试 4 次全 429。要么等窗口，要么给 11 个 HTTP 节点加
  `retry_enabled + retry_interval≥3000` 退避。
- 发布草稿**不能**修 429。草稿能跑通多半只是碰上了没被限流的窗口。

---

## 第 0 步：固定变量（本机开发环境）

```bash
cd <repo>
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' deploy/.env.dev | head -1 | cut -d= -f2-)        # MySQL root
TOK=$(cat output/pig-token.txt)                                                       # PIG admin token
TOK_I=$(grep -E '^INTERNAL_AI_TOKEN=' deploy/.env.dev | head -1 | cut -d= -f2-)        # 内部令牌
DSN=$(grep -E '^DIFY_DB_DSN=' deploy/.env.dev | head -1 | cut -d= -f2-)                # Dify PG
PSQL=/opt/homebrew/opt/postgresql@16/bin/psql
```

---

## L1 — 编码登记 SQL 的守卫错配（**静默 no-op，最阴**）

python-ai 按固定语义码找 Key：`finance-data-v2 / finance-daily-v1 / finance-weekly-v1 /
finance-monthly-v1 / finance-quarterly-v1 / finance-yearly-v1`；而 Dify 自动同步按「应用名规范化」
生成 `v1-1 / v1-1-1 / …` 这类遗留码。正名脚本是 `pig/db/ai/ops_finance_app_code_register.sql`。

**判据（一票）**：

```bash
docker exec -e MYSQL_PWD="$PW" linmo-mysql mysql -uroot -B pig -e \
  "SELECT id,app_code,app_name,dify_app_id FROM ai_app_config WHERE app_code LIKE 'finance-%' AND del_flag='0' ORDER BY id;"
# 必须恰好 6 行；少于 6 行 = L1 复发
```

**复发原因（务必记住）**：旧守卫写成 `WHERE id = N AND dify_app_id = 'X'`，而两值**是错配的**
（实测 id 86=年报 / 87=季报 / 88=月报 / 89=日报 / 90=周报，**id 92 是 AIHOT 资讯助手**；
旧脚本按 `v1-1-1/2/3/4` 的语义顺序猜成 87/88/89/92）⇒ `AND` 不成立 ⇒ **WHERE 静默不命中、不报错、不告警**。

**修法**：守卫**只按稳定的 `dify_app_id` 命中**（幂等脚本永远不要用「自增 id + 看着像的 uuid」双条件）：

```sql
UPDATE ai_app_config SET app_code='finance-yearly-v1', base_url='http://192.168.110.172/v1', remark='…'
WHERE dify_app_id = '0974b185-a567-4cb3-9814-49f92a66eb2a' AND del_flag='0';
```

**落库**：走自带 SQL 执行台（自动备份 + 落 `sys_db_sql_console_log`）：

```bash
python3 -c "import json;sql=open('pig/db/ai/ops_finance_app_code_register.sql',encoding='utf-8').read();open('/tmp/p.json','w',encoding='utf-8').write(json.dumps({'sql':sql,'allowWrite':True}))"
curl -s -X POST -H "Authorization: Bearer $TOK" -H "TENANT-ID: 1" \
  -H "Content-Type: application/json; charset=utf-8" --data-binary @/tmp/p.json \
  "http://localhost:9999/admin/db/upgrade/sql/execute"
```

---

## L2 — 无 Service API Key 或未启用

**判据**：

```bash
curl -s -H "X-Internal-Token: $TOK_I" "http://localhost:8090/internal/v1/finance/health?probe=true"
# 目标：status=ready && app_key_configured=true && dify_reachable=true
# blocked 或 *_key_configured=false ⇒ 就是本层
```

🔴 `AiConfigSyncService.snapshot()` 只下发 **`enabled='1'`** 的应用 ⇒ **补 Key 必须同时启用**，
否则 python 侧根本看不到这个 app_code。

**修法（不需要 Dify 控制台口令）**——Dify PG 的 `api_tokens` 明文存 Service API Key：

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
    NO_PROXY='*' no_proxy='*' DIFY_DB_DSN="$DSN" \
  /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 \
  tools/dify_backfill_keys_from_db.py --only 43 --only 86 --only 87 --only 88 --only 89 --only 90 --enable
```

- 该工具经 `PUT /admin/ai/apps/{id}` 由服务端 AES-256-GCM 落库（Key 明文只在请求体内，满足 C-01）；
  写回后自动用 Dify Service API `GET /v1/parameters` 复验，**全 `HTTP 200` 才算 Key 有效**。
- `--only` 收 id 或 app_code（可重复）；`--dry-run` 先预览。
- 🔴 **`PUT /ai/apps/{id}` 会静默改字段**（`appType` 空→`chat`、`modelCode` 空→默认模型，且 `update()` **不改 `app_code`**）
  ⇒ 要么用上面的工具（它带全原值），要么自己 PUT 时**带全原值**。**改 app_code 只能走 SQL**。

⏳ 配置快照 **约 30–60s** 才刷到 python（`refresh_seconds:30`）。改完别立刻断言失败；也可
`docker restart linmo-python-ai` 强制全量拉。

---

## L3 — Dify 工作流 HTTP 节点指向已下线主机

**判据**：health 已 ready，但 `refresh` 仍在**极短时间**（<1s）返回 502/`PYTHON_RESULT_UNVERIFIED`。

🔴 真因被消毒了：python `finance.py` 把一切上游异常收成 `FINANCE_RESULT_UNVERIFIED`
（防外泄含 Authorization 的报错体）⇒ **只看 PIG 的 `error_code` 永远查不到真因**。

**直连 Dify 复现**（Key 取 L2 那 6 个应用中的一个，注意 `base_url` 已含 `/v1`）：

```bash
python3 - <<'PY'
import json,urllib.request
url="http://192.168.110.172/v1/workflows/run"
body={"inputs":{"as_of":"2026-10-10","trend_days":"90","viewer_role":"finance_manager"},
      "response_mode":"blocking","user":"finance:1"}
req=urllib.request.Request(url,method="POST",data=json.dumps(body).encode())
req.add_header("Authorization","Bearer <DIFY_FINANCE_APP_KEY>")   # finance-data-v2 的 Key，真实值从 linmo-pig-full 的 deploy/.env 取（DIFY_FINANCE_APP_KEY）
req.add_header("Content-Type","application/json")
with urllib.request.urlopen(req,timeout=120) as r: d=json.loads(r.read())
print("status:",d["data"]["status"]); print("error:",d["data"].get("error"))
PY
```

**节点级定位（一击命中）**：

```bash
$PSQL "$DSN" -A -F$'\t' -c \
 "SELECT node_id,title,node_type,status,error,outputs FROM workflow_node_executions \
  WHERE workflow_run_id='<上一步没用上就查最近 run 的 id>' ORDER BY created_at;"
```

典型案例：`books`（HTTP 节点，title「确认授权账套」）`status=exception`、
`error="503 Service Unavailable"`、`outputs.error_type=HttpRequestNodeError` ⇒ 传输层失败（域名没了）。

**统计写死次数 / 判断影响面**：

```bash
$PSQL "$DSN" -A -F$'\t' -c "SELECT a.name,(SELECT count(*) FROM regexp_matches(w.graph,'cwgl\.mzlc\.me','g')) \
 FROM workflows w JOIN apps a ON a.id=w.app_id WHERE a.id IN ('edf53528-…','2c856761-…','441663d9-…', \
 '9b747a6f-…','f575cee4-…','37ffda48-…','0974b185-…') ORDER BY a.name;"
# 2026-10-11 实测：只有「财务真实数据接入 V2」命中 11 次；周/月/季/年报 4 个报告应用命中 0 次
#   ⇒ 报告应用只是「文字增强层」，消费数据应用的输出 ⇒ 只要 V2 通，全部卡片与周期报告都能恢复
```

**修法（需人工拍板，别擅自改生产工作流）**：确认账套系统**当前可达地址**（见 L4）后，批量把 11 个节点的
`https://cwgl.mzlc.me` 改成新 base（建议把 host 抽成 Dify 环境变量 `c_wz_base`，避免下次迁移再改 11 处），
**发布** draft（控制台或 `tools/dify_workflow_publish.py --app-id … --force`），再重跑。

---

## L4 — 上游账套系统迁址 / 下线

**判据**：

```bash
dig +short cwgl.mzlc.me @192.168.110.1      # 公司 DNS；NXDOMAIN = 域名已撤
dig +short cwgl.mzlc.me @223.5.5.5          # 公网对照
dig +short pc.mzlc.me @192.168.110.1        # 对照「正常域名」（应能解析）
```

**新地址线索在运行库 `ops_connector`**（不在 `.env`、不在 docs）：

```bash
docker exec -e MYSQL_PWD="$PW" linmo-mysql mysql -uroot -B pig -e \
 "SELECT connector_code,connector_name,base_url,connect_status,last_sync_time FROM ops_connector WHERE connector_code LIKE '%yzt%';"
# 2026-10-11 实测：yzt-openapi / 灵猫云账通 / http://192.168.110.105:3200/api/v1
#   但 connect_status=PENDING、last_sync_time=NULL、无凭据行 ⇒ 该地址也需人工确认
```

**历史运行分界**（判断「什么时候开始坏的」）：

```bash
$PSQL "$DSN" -A -F$'\t' -c "SELECT status,COUNT(*),MIN(created_at),MAX(created_at) \
 FROM workflow_runs WHERE workflow_id='<V2 工作流 id>' GROUP BY status;"
# 2026-10-11 实测：succeeded 271（10-06 07:52 ~ 10-08 03:05）/ failed 1020（10-08 01:45 起）
```

**这一层不能在仓库内修复**。产出「需人工确认」的清单：① 账套系统当前可达地址；
② Dify 主机（192.168.110.172）能否访问它；③ 谁改 Dify 工作流并发布。

---

## L5 — 聚合节点现金流校验口径错配（**2026-10-31 新增：这是「一直没数据」的真因**）

L0~L4 全绿、`refresh` 返回 200、16 个节点全 succeeded，页面照样空 ⇒ 怀疑本层。

**判据（一票）**：节点 15「核对金额、整理角色指标与异常」的输出里 `checks` 为
`cash_balance=true, cash_inflow=false, cash_outflow=false`，且卡片只剩 2 张
`today_receipts / today_payments` 全 `pending`、`cash_flow.points=[]`、alerts 有 `CASH_FLOW_UNVERIFIED`。

**根因**：代码用「凭证**净额**、截止 `as_of`」去和总览 `funds.inflow/outflow` 做**硬相等**，而总览是
「**整月毛额**」。两处系统性差额：
1. 内部转账（现金↔银行，同一凭证同时有 1001/1002）被 `net=debit-credit` 对冲成 0，总览却双边各记一次；
   2026-10-31 实测 4 笔「提取本周备用金」各 2,000 = 8,000；
2. `as_of` 截止日之后的凭证被排除，总览按整月统计（实测 10-31 付出 559）。

⇒ 永远不相等 ⇒ `raise 'cash movement mismatch'` ⇒ `cash_flow` 永久 `pending` ⇒ 空态。

**定性复算（30 秒）**：拿该 run 节点 12/13（`operations`/`month_operations`）的 `body.data.rows`，按
`Σdebit(1001/1002) / Σcredit(1001/1002)`、区间 `month_start..month_end` 求和，应**分毫不差**等于
`overview.funds.inflow/outflow`。对不上才需要怀疑上游数据本身。

**离线回放验证（改代码前必做，比发布后试快 10 倍）**：把节点 15 的 `graph->nodes[].data.code` 导出成 `.py`，
`exec` 后调用 `main(context_json=节点2的 context_json, <source>_status=200, <source>_body=节点N的 body)`，
source 依次为 `books(3) overview(5) balance(7) trial(8) operations(12) month_operations(13)`。
原版应复现 `partial`，补丁版应得 `ready`。

**修法**（三处，改完必须**发布** draft）：
```python
month_in_gross = month_out_gross = 0                       # 新增
if ctx['month_start'] <= voucher_date <= ctx['month_end']:  # 整月
    month_in_gross += debit; month_out_gross += credit      # 毛额
inflow_ok  = month_in_gross  == cents(overview['funds']['inflow'])
outflow_ok = month_out_gross == cents(overview['funds']['outflow'])
```
并把内部转账单列进 `supplemental_facts`（否则用户会问「趋势图里怎么没有这笔」）。
可粘贴成品见 `linmo-pig-full/output/finance-node15-patched-20261031.py`。

⚠️ 当前发布版聚合代码**只产 2 张卡**（今日收/付）+ 90 天趋势；历史出现过的 6 张卡
（区间账面利润/营业成本/可用现金…）不在这一版里，别拿旧截图比对来误判「又坏了」。

## 收尾必做

1. **副作用**：L2 修好后 `isFinanceReady()` 由 false→true，快照预加载器
   （`FINANCE_SNAPSHOT_REFRESH_MINUTES=5`）与每日任务会**真的发起取数**；上游不通期间持续产生 502/503 日志。
   `ai_finance_run` 因**按天幂等键**只 +1 行/天。若嫌噪声可临时把 6 行 `enabled` 置回 `0`（但上游恢复后就不用了）。
2. **防复发**：改了 `pig/db/**/*.sql` 必须登记 `initdb-loader.sh` ORDER；本文件是 **MODIFIED 幂等脚本**，
   在线升级会重跑（无害）。
3. **落档**：`docs/finance/README.md` 补当期补记；判据写 `topics-domain-judgments.md`（财务那节 = **§D16**，
   注意不要与市场页的 §D13 撞号）；报告写 `output/`。
4. **别碰**：`.env.dev` 的**内容**（2026-10-14 起它是**授权入库的共享配置** —— 可以读、可以 `grep` 取值，但不要修改或覆盖；它同时是本机 compose `--env-file` 与 Jenkins 的读取源）、Dify 侧工作流（除非用户明确授权）、账套系统。
