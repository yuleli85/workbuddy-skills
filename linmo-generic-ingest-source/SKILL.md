---
name: linmo-generic-ingest-source
description: 给灵猫企管（linmo-pig-full / PIG）接入一个新的外部数据源，走「万能入湖」契约通道（POST /admin/internal/ops/generic-ingest），不写 Java、不写建表 SQL。适用于用户说「把 X 的数据采集/同步到灵猫系统」「接入一个新数据源」「落到 pig_dw」「万能入湖」「契约驱动建表」，或需要排查入湖报 404 / 401 / 400 契约未登记 / 字段传了却 NULL / 空值导致记录静默丢失。也覆盖「xdy-collector 采集器怎么配置 / 怎么换推送目标（--base）/ 定时器怎么挂 / 为什么定时任务只推本地」。覆盖：契约卡登记（dw_schema_card + 固化进 pig/db）、端点与 /admin 上下文路径、X-Internal-Token 取法（6 级优先级链）、幂等键与 ON DUPLICATE KEY 语义、overflow 列、空值/类型三大坑、采集器六配置面与 run_pipeline 参数透传坑、端到端验证与 dw_ingest_log 核对。
agent_created: true
---

# 给灵猫企管接入一个新数据源（万能入湖）

**核心结论：接入新源 = 登记一张契约卡 + 推 JSON。不用写 Java，不用写建表 SQL。**
官方 SOP 在灵猫仓库 `docs/18-万能数据收集-接入指南.md`，设计在 `docs/17`，
验收脚本 `tools/verify_generic_ingest.py`。本文只记**实操中会踩的坑**。

## 0. 先确认运行时（别猜）

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -E 'pig-boot|mysql'   # 期望 linmo-pig-boot:9999 / linmo-mysql:3306
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9999/admin/actuator/health
```

契约一览（只读，同时验证令牌与路由）：

```bash
TOKEN=$(grep -m1 '^INTERNAL_AI_TOKEN=' /Users/shan/work/linmo-pig-full/deploy/.env.dev | cut -d= -f2- | tr -d '"'"'"' \r')
curl -s http://127.0.0.1:9999/admin/internal/ops/generic-ingest/contracts -H "X-Internal-Token: $TOKEN" | head -c 600
```

## 1. 🔴 三个必踩的坑

### 坑 1：URL 少了 `/admin` ⇒ Tomcat 404（不是"功能没上线"）
`pig-boot/application.yml` 里 `server.servlet.context-path: /admin`。
正确 URL：`http://127.0.0.1:9999/admin/internal/ops/generic-ingest`。
`docs/18` 里给 Dify 用的示例 URL **漏了这段**，照抄会得到一页 Tomcat 404 HTML。
判据：404 且响应体是 `<!doctype html>…HTTP Status 404` ⇒ 路由前缀写错；
404 且响应体是 JSON ⇒ 才是真没这个接口。

### 坑 2：空字符串 `""` 让整条记录**静默丢失**
`GenericIngestService.convert()` 对 `decimal` 类型执行 `new BigDecimal(str(v)...)`，
收到 `""` 抛 `NumberFormatException` ⇒ 该条 `failed++`，**HTTP 仍返回 200**，
只在响应体的 `failed` 和 `errors[]` 里体现。批量推几百条时极易漏看。

**对策（上传侧负责）**：空值字段**整个键删掉**，别传 `""`。落库是 `NULL`，
语义也更对 —— 源数据没返回 ≠ 该指标为 0。

```python
rec = {k: v for k, v in row.items() if v is not None and str(v).strip() != ""}
```

### 坑 3：数值列别声明 `bigint`
计数类字段在源数据里常以 `"0.0"` 出现，`convert()` 对 int 走 `Long.parseLong("0.0")` ⇒ 崩。
**统一 `decimal(38,18)`**（MySQL scale 上限 30，精度上限 65，合法）。
比率类字段小数位可能到 17 位（float 尾数），`decimal(24,6)` 会截断。
查询时自己 `CAST(value AS DECIMAL(20,4))`。

## 2. 登记契约卡

唯一键是 `schema_code`，所以 `INSERT ... ON DUPLICATE KEY UPDATE` 天然幂等。

```sql
INSERT INTO pig.dw_schema_card
  (schema_code, schema_version, display_name, owner, db_name, table_name,
   idempotent_key, retention_days, fields_json, status, remark, create_time)
VALUES ('<source>_<entity>', 'v1', '<中文名>', '<owner>', 'pig_dw', 'ods_<source>_<entity>',
        '["<业务键>"]', 180, '<fields_json>', 'PUBLISHED', '<备注>', NOW())
ON DUPLICATE KEY UPDATE schema_version=VALUES(schema_version), fields_json=VALUES(fields_json),
  status=VALUES(status), remark=VALUES(remark), update_time=NOW();
```

执行（**SQL 必须走 stdin**，写成 `mysql -e "...json..."` 会被外层引号吃掉 JSON 里的 `\"`）：

```bash
docker exec -i linmo-mysql sh -c "MYSQL_PWD=root mysql -uroot --default-character-set=utf8mb4" < sql/xxx_contracts.sql
```

**硬性约束**（服务端强制校验）：
- `db_name` 只能是 `pig_dw`；`table_name` 必须 `ods_` 开头；标识符只允许 `[A-Za-z0-9_]{1,64}`。
- `idempotent_key` 是 JSON 数组。没有业务键就用 `["__sha256__"]`（按内容指纹去重）。
- 每张契约**最多一个** `overflow: true` 的 json 列。**必须留一个** —— 契约外字段只会往
  overflow 列塞；没有这一列时，契约外字段**被静默丢弃**。
- `required: true` 的字段缺失 ⇒ 该条 `failed`（不影响同批其他条）。建议只标幂等键字段。
- `type` 枚举：`string`(默认) / `int` / `decimal` / `bool` / `datetime` / `json` / `text`。
  `len > 4000` 自动变 `text`。`datetime` 接受 `yyyy-MM-dd`、`yyyy-MM-dd HH:mm:ss`、带 `T`；
  空串安全返回 NULL。
- **字段名区分大小写匹配**，JSON 里的键必须与契约 `name` 完全一致。
- 单库 `ods_` 表上限 50 张（表爆炸保护）。

**同时固化进灵猫仓库** `pig/db/ops/<date>_<name>.sql`（万能入湖的建表脚本归 `ops/` 域；
2026-10-13 起 `pig/db/` 已按功能域分子目录，新脚本不要放顶层），否则清库重放就丢了
（配套 skill：`pig-db-config-seed`；放好后记得登记 `pig/db/initdb-loader.sh` 的 `ORDER`）。

## 3. 推送

```
POST {base}/admin/internal/ops/generic-ingest
Headers: Content-Type: application/json
         X-Internal-Token: <INTERNAL_AI_TOKEN>
Body: {"schemaCode":"x","schemaVersion":"v1","scope":"人看的范围描述","records":[{...}]}
```

- 令牌用 `X-Internal-Token`；用 `Authorization: Bearer <普通JWT>` 会被安全过滤器判
  **424**（前端会显示成"登录状态已过期"，极具误导性）。
- 令牌两端都用 `deploy/.env.dev` 的 `INTERNAL_AI_TOKEN`。
- **`records: []` 会被 400 拒收**（避免把"没采到"记成"数据没了"）⇒ 无数据时直接跳过，别发空批次。
- 分块建议 500/批。网络错误/5xx 退避重试；**4xx 不重试**（确定性失败）。
- 响应体：`{code, data:{inserted, duplicated, failed, rowCount, ddlExecuted, errors[]}}`。
  `ddlExecuted` 里有 `CREATE TABLE`/`ALTER ADD` ⇒ 表是刚刚自动建出来的。
  **`failed > 0` 必须当告警处理，不能当成整体成功。**

可复制的参考实现：`/Users/shan/WorkBuddy/2026-10-09-18-06-59/xdy-collector/push_to_linmo.py`
（水位线增量 + 分块 + 重试 + 前置体检 + 幂等验证，仅标准库）。

### 3.1 现成采集器 `xdy-collector` 的配置面与优先级（2026-10-14 实测）

位置 `~/WorkBuddy/2026-10-09-18-06-59/xdy-collector/` —— **仓库外**、不在任何 compose；
`install_schedule.sh` 装 LaunchAgent `com.linmo.xdy-collector`（本机已装：**09:00 + 21:00**，
`ProgramArguments` 只有 `/bin/zsh` + `run_pipeline.sh`，**不带任何参数**）。

六个配置面：

| 面 | 位置 | 管什么 |
|---|---|---|
| 静态配置 | `config.json` | 采集窗口/平台/分页；`linmo.base_url`·`ctx_path`·`chunk_size`·`timeout`·`retry`·`env_file` |
| 凭据 | 环境变量 / `~/.linmo-collector.env` / `config.json.linmo.env_file` | `INTERNAL_AI_TOKEN` |
| 采集水位线 | `state.json` | `last_refresh_date`（`data update` 非幂等，每天限一次） |
| 推送水位线 | `data/state_push.json` | `last_max_date`（增量断点，重推时回退 6 天） |
| 调度 | `~/Library/LaunchAgents/com.linmo.xdy-collector.plist` | 触发时刻（`install_schedule.sh --hours 9,21`） |
| CLI | 命令行参数 | 一次性覆盖 |

优先级链：

- **推送目标**：`--base` → `config.json.linmo.base_url` → 内置 `http://127.0.0.1:9999`；
  之后 `resolve_base()` 自动补 `ctx_path=/admin`。⚠️ **没有环境变量这一跳**。
- **令牌**（6 跳）：`--token` → `$LINMO_INTERNAL_TOKEN` → `$INTERNAL_AI_TOKEN`
  → `~/.linmo-collector.env` → `$LINMO_ENV_FILE` → `config.json.linmo.env_file`
  → 3 个硬编码绝对路径。本机实际命中第 6 跳（`/Users/shan/work/linmo-pig-full/deploy/.env.dev`；
  `~/.linmo-collector.env` **不存在**）。
- **窗口**：`collect.py --days` → `config.json.days`(7)；**平台**：`config.json.platforms`（空=自动全采）；
  **作品表**：`config.json.include_works` AND NOT `--no-works`。

🔴 三个坑：

1. **`run_pipeline.sh "$@"` 是「假通用」透传**：它把参数同时喂给 `collect.py` 与 `push_to_linmo.py`，
   而两脚本参数集**只有 `--no-works` 交集**（collect：`--refresh/--days/--no-works`；
   push：`--full/--dry-run/--check-only/--no-works/--since-days/--token/--base`）。
   传任何其他参数，必有一方 argparse `unrecognized arguments` 报错退出 ⇒ **要带参数就直调脚本**。
2. **推送目标无环境变量入口 + launchd 不带参数** ⇒ 定时任务的推送目标 = `config.json` 的**唯一值**，
   无法按环境切换。要「一次采集多环境」必须先给脚本补 `LINMO_BASE_URL` 环境变量支持（容器化改造项）。
3. 令牌链含 **硬编码绝对路径** ⇒ 换机器/用户名即断。搬机器先建 `~/.linmo-collector.env`
   （`INTERNAL_AI_TOKEN=xxx`）。配套：`~/.xdy-cli.yaml` 权限是 `644` 且含 access key，建议 `chmod 600`。

万能确认命令（**只读**，一次验路由+令牌+契约+各表行数）：

```bash
cd ~/WorkBuddy/2026-10-09-18-06-59/xdy-collector
python3 push_to_linmo.py --check-only --base http://<目标IP>:9999   # 换目标推前先体检
python3 push_to_linmo.py --base http://<目标IP>:9999 --full         # 再推（幂等，可重复跑）
python3 push_to_linmo.py --dry-run --since-days 3                   # 安全预览"会推多少条"
```

`--check-only` 打印的各契约 `行数` 可直接分辨两台环境（实测：本地 `ods_xdy_work`=29 vs `172`=0）。

## 4. 验证（必做，别只看 HTTP 200）

```bash
# 4.1 幂等：同一批推两次，第二次应 inserted=0、duplicated=N、表行数不变
# 4.2 落库核对
docker exec -i linmo-mysql sh -c "MYSQL_PWD=root mysql -uroot --default-character-set=utf8mb4 -t" <<'SQL'
SELECT COUNT(*) FROM pig_dw.ods_<source>_<entity>;
SELECT * FROM pig_dw.ods_<source>_<entity> LIMIT 3;
SELECT batch_no, schema_code, status, total, inserted, duplicated, failed, ddl_executed
  FROM pig.dw_ingest_log WHERE schema_code='<source>_<entity>' ORDER BY id DESC LIMIT 5;
SELECT schema_code, last_ddl, column_count, row_count, last_ingest_at FROM pig.dw_table_registry;
SQL
```

- `ON DUPLICATE KEY UPDATE` 的驱动返回值语义：`1 = 插入`、`2 = 更新(命中已有行)`。
  服务端据此把 2 计成 `duplicated` —— 所以"重推全变 duplicated"是**正确**的幂等表现。
- 表上自动多三列：`__batch`（批次号）、`__ingested_at`、`__sha256`。
- `dw_ingest_log` 唯一键是 `(batch_no, schema_code)`；服务端未传 batchNo 时会自己生成
  `<yyyyMMdd>-<HHmmss>-<4位随机>`（撞键会整批 500）。
- 入湖成功后服务端会发 `DwSourceDataChangedEvent`，自动 ETL 进 DWD/DWS，**新源零成本接入数仓**。

## 4.5 只读探针：直接问 Dify 采集工作流「此刻到底看到什么」（2026-10-15 实测）

排障时最想要的是**取数范围的原始输出**（哪些项目/仓库、多少条），而 PIG 的 `ops_sync_log` 只给
`pulled_count` 这种数字、镜像表又被 upsert 去重过 —— 都推不出「名单」。直接跑一次工作流拿 outputs：

```bash
docker exec deploy-python-ai-1 sh -c 'curl -s -m 240 -X POST \
  http://127.0.0.1:8090/internal/v1/workflow/run \
  -H "Content-Type: application/json" -H "X-Internal-Token: $INTERNAL_AI_TOKEN" \
  -d "{\"app\":\"<dify应用code>\",\"inputs\":{\"page_size\":100},\"user\":\"probe\"}"'
```

- 🔴 **必须不带 `sceneTag`**：`OpsCollectAdapter.handles()` 只在「`app` == `ops_collect_app`」或
  「`sceneTag` == `ops_collect_scene`」时接管。不传标签 ⇒ `handles` 为假 ⇒ 纯转发，**只读，不回写任何镜像表**
  （传了标签就会真的走 mapper + 回推，变成一次真同步）。token 头名是 `X-Internal-Token`，
  容器内直接引用 `$INTERNAL_AI_TOKEN`，值不会出现在输出里。
- 输出里 `projects_json` / `tasks_json` / `coverage_json`（部分工作流）就是全量名单；
  `coverage.execution_ids` 能看出到底轮询了哪几个执行。
- 禅道全项目采集（`project-agent-zentao-collect`）的**范围判据**：项目取
  `GET /api.php/v1/projects?page=1&limit=200`（**不筛状态**，`total > len(rows)` 直接失败）；
  只有 status ∈ `{wait, wait_confirm, doing}` 的项目，其执行才轮到任务分页；未知状态**报错而非跳过**。
  ⇒ 「用户说只有 3 个项目、系统里有 7 个」多数是 ① 采集账号权限看不到 ② 那些项目已 closed
  ③ 镜像里有**已不在禅道**的残留行（入湖只有 upsert、没有 reconcile，删不掉）。

⚠️ §4.5 的命令**必须保持单引号** `sh -c '…$INTERNAL_AI_TOKEN…'`（token 在容器内展开，不回显）。
若 payload 里有引号难写，改用「宿主写 payload 文件 + 容器内 `-d @-`」，**不要**改成
`docker exec … sh -c "…\$INTERNAL_AI_TOKEN…"` —— 双引号包裹时 `\$` 会被宿主吃掉，报 `invalid internal token`（2026-10-15 实测踩到）。

## 4.6 GitHub 仓库采集的两个必查项（2026-10-15 实测）

判「某 GitHub 仓库的数据是不是真的在同步」，只看 `connect_status=CONNECTED` 与 `pulled_count>0` 会误判 ——
**两个静默失能点**都要看：

| 检查点 | 判据 | 症状 |
|---|---|---|
| **分支（`sha`）** | `ops_connector.workflow_inputs` 里**有没有 `sha`** | 缺失 ⇒ 取**默认分支**（`ls-remote --symref origin HEAD` 看是 main 还是别的）。开发分支上的提交**一条都不会进**，且日志全绿 |
| **输出截断** | 工作流 outputs 的 `truncated` 字段 + report 里那句「共 N 条…只输出前 M 条」 | Dify code 节点单次输出上限 **400000 字符** ⇒ `commits_json` 被**静默截断**；`python-ai` 侧**不读** `truncated`（`grep -rn truncated python-ai-service/app` 无采集相关命中）|

- 🔴 **`ops_sync_log.pulled_count` 每轮恒定不变** = 截断（或无增量）的特征。别把它当「稳定」——
  `github` 连接器长期 `pulled 953 / skip 953`，真相是 1491 条里**只有最新的 953 条**能出得来。
  `cursor_before`「永不推进」是假象：它取的是**本批数据的 min 时间**，不是持久化游标。
- 截断取的是**按时间倒序的前 N 条** ⇒ 丢的永远是**最老**那批。所以「给缺 `sha` 的连接器补个 `sha=dev`」
  是**危险操作**：分支切过去会一次性丢掉该分支最老的若干百条（实测 `dev` 1726 条 → 只出 1104 条）。
  **正确顺序：先按时间切成小窗口分批补（工作流 report 自己就建议「把时间范围切小分批抓取」），再改 `sha`。**
- 核对方法（逐条对齐）：`rev-list --count origin/<分支>` ↔ 工作流探测的 `commit_count` ↔ 库内
  `SELECT repo, COUNT(*) FROM ops_ext_commit GROUP BY repo`。三者一致才算「这条仓库真的同步对了」。
- 多仓库的正确接法 = **一个仓库一个连接器**（`github` / `github-linmo-desktop` / `github-daily-agent-digest`），
  在 python-ai 侧靠 `_SPECS["github-*"] = _SPECS["github"]` 别名注册复用同一份 CollectSpec（`ops_collect.py`）；
  连接器各自的 `workflow_inputs` 才是「采哪个仓、哪个分支」的唯一真源。

## 5. 定时怎么挂

- **优先 WorkBuddy 自动化** —— 本机 shell 注册不了 launchd（见下）。
- launchd 在 WorkBuddy 的 shell 里 `launchctl bootstrap` 报 `Input/output error (errno 5)`，
  `crontab` 报 `operation not permitted`（plist 本身合法）。要装就让用户在自己的终端跑
  `launchctl bootstrap gui/$(id -u) <plist>`，或重新登录由 launchd 自动加载。
  ⚠️ **别用 `launchctl bootout` 试探已有 agent** —— 卸掉就装不回来了。
- 调度器必须是**幂等可重跑**的；写操作（如向客户端下发任务）用状态文件做「每天一次」守卫。

## 6. 排障对照

| 现象 | 根因 | 处置 |
|---|---|---|
| Tomcat 404 HTML | 少了 `/admin` | 补上下文路径 |
| `424` + "登录状态已过期" | 用 `Authorization: Bearer` 调内部端点 | 改 `X-Internal-Token` |
| `401 内部令牌无效` | 令牌不一致 | 两端都用 `deploy/.env.dev` 的值 |
| `400 契约未登记：x` | 没登记 / `status != PUBLISHED` | 执行登记 SQL |
| `400 契约版本不匹配` | 请求带了旧 `schemaVersion` | 同步到契约卡的版本 |
| `400 非法标识符` | 表名/字段名含中文、横线、大写以外字符 | 只用 `[A-Za-z0-9_]` |
| `400 records 为空` | 发了空批次 | 无数据就跳过 |
| `400 ods_ 表数量已达上限 50` | 表爆炸保护 | 废弃契约置 `DEPRECATED` |
| 字段传了却是 NULL | JSON 键名与契约 `name` 大小写不一致 | 逐字对齐 |
| 数字变字符串 / 前导零丢 | 声明数值但源是带格式串 | 改 `string` 或上传前规范化 |
| 行数少了但 HTTP 200 | 有必填缺失或空串喂 decimal | 看响应体 `failed` + `errors[]` |
