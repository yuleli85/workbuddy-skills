---
name: pig-db-online-upgrade-triage
description: 排查并修复灵猫企管（linmo-pig-full / PIG）「数据库在线升级中途失败」，把半升级的库修到 pending 归零并跑完。适用于用户说「升级中途失败」「在线升级报错/停在中途」「sys_db_migration 有 FAILED 行」「XX 表 doesn't exist 导致升级中断」「执行了 db upgrade 但没跑完」「定时任务列表出现两个同 job_id」，或贴出 `GET/POST /admin/db/upgrade/{pending,backup,execute}` 的结果。覆盖：从 sys_db_migration + /pending 还原「已执行/待执行/MODIFIED」三态、按字典序推演真实执行序、预判缺表风险（目标表 − 脚本自建表 − 库内已有表）、用自带 SQL 执行台补建依赖对象后续跑、菜单缓存清理、sys_job 复合主键撞车识别。
agent_created: true
---

# PIG 在线升级「中途失败」排查与修复

目标：把**半升级**的库修到 `/db/upgrade/pending` 三态归零（`pendingCount=0 / modifiedCount=0`），且不伪造、不越权、留痕可回溯。

## 0. 先分清两条路径（判据不可互推）

| 路径 | 排序依据 | 触发方式 |
|---|---|---|
| **initdb**（全新库） | `pig/db/initdb-loader.sh` 的 **`ORDER` 数组**（人工维护的依赖序） | mysql 数据卷首次创建 |
| **在线升级**（老库） | `DbUpgradeService.execute()` 的 **`Comparator.comparing(ScriptFile::name)`（纯字典序）** | `POST /admin/db/upgrade/execute` |

🔴 **ORDER 对 ≠ 在线升级对。** 本次实测：`hr_chart_data_seed_20261010.sql`（`'h'`）依赖 4 张表，建表的 `yzt_connector.sql`（`'y'`）字典序**排最后** ⇒ 老库升级必挂，而 initdb 因 ORDER 正确反而不受影响。

## 1. 取现场（三件事）

```bash
cd <repo>
# ① 待执行三态（head 看 summary 即可）
TOK=$(cat output/pig-token.txt)      # 失效则用 tools/ 里的登录脚本重新取
curl -s -H "Authorization: Bearer $TOK" -H "TENANT-ID: 1" \
  http://localhost:9999/admin/db/upgrade/pending > /tmp/pending.json

# ② 失败行 + 报错原文
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' deploy/.env.dev | cut -d= -f2-)
docker exec -e MYSQL_PWD="$PW" linmo-mysql mysql -uroot -B pig -e \
 "SELECT script_name,status,file_size,LEFT(error_msg,300),create_time,executed_by
  FROM sys_db_migration WHERE status<>'SUCCESS'"

# ③ 时间线（区分「基线登记」与「真执行」）
docker exec -e MYSQL_PWD="$PW" linmo-mysql mysql -uroot -B pig -e \
 "SELECT DATE(create_time) d,status,COUNT(*) FROM sys_db_migration GROUP BY d,status ORDER BY d;"
```

**关键判读**
- `executed_by=admin` + 单独时间戳 = 控制台真执行；**同一秒上百行** = `ensureBaseline()` 的**只记账不执行** ⇒ 「登记表 SUCCESS」≠「库里真有这张表」。
- 框架**失败即 break**：`results` 里最后一条 `ok:false` 就是断点，其后脚本都没跑。
- 🔴 **`FAILED` 计数为 0 却中断** ⇒ 别急着重跑：先看日志有没有 `Table '<别的库>.<本库的表>' doesn't exist`（如 `pig_dw.sys_db_migration` / `pig_dw.ai_app_config`）。命中就是**脚本 `USE <别的库>` 污染了连接池**（§5 末条）—— 此时**登记表连失败行都不会有**，因为「写失败行」这条 INSERT 自己也打到了别的库上。
- 🔴 **`status=SUCCESS` 且 `cost_ms=0`** ⇒ 基线登记，**从未真跑过**；若它又出现在 `modified` 里，则本次是它的**首次真执行**，最容易踩出隐藏缺陷（先看它有没有 `USE <别的库>`）。
- 某个「本该插入 N 行」的种子脚本少 1 行时，先查脚本自身的 `WHERE NOT EXISTS(<键>)` 幂等守卫（如 `20261012_perm_register_missing.sql` 的 `NOT EXISTS(permission)` 会跳过已以别的 `menu_id` 登记过的权限点），**别改脚本**。

## 2. 推演真实执行序 + 预判缺表（决定「继续跑」还是「先补依赖」）

对待执行集合（`pending` ∪ `modified`）先排序，再逐脚本做缺表判定：

```
真缺表 = (解析 INTO/REPLACE INTO/UPDATE/DELETE FROM/FROM/JOIN/ALTER TABLE 的目标表)
        − (该脚本自己 CREATE TABLE 的表)      # 自建表是假阳性
        − (information_schema 里已存在的表)
```

- 有真缺表 ⇒ **不能直接重跑**（字典序会把依赖方排前面，必重挂）。
- 无真缺表 ⇒ 直接 `POST /db/upgrade/execute` 即可。
- 🔴 **两个最常见的解析假阳性，先排除再下结论**：`CREATE TEMPORARY TABLE`（临时表不入 `information_schema`）与 `CREATE TABLE <bak> LIKE <src>`（会被误读成目标表 `<bak>.LIKE`）。本仓 2026-10-13 实测 28 个脚本报 3 处「缺表」，核实后全是这两类。
- 🔴 **顺带判一件事**：待执行脚本里**哪些自身没有 `USE` 语句**（本仓实测 28 个里有 8 个）。它们完全依赖会话默认库 ⇒ 是「§5 连接池污染」的**第一批受害者**，其失败与自身内容无关。
- 🔴 同时看脚本里的 **清理型语句**（`DELETE ... WHERE <键>`）：`loadRecords()` 只读 `status='SUCCESS'`，**校验和未变的老脚本不会重跑** ⇒ 它的 DELETE 被跳过会造成状态残留（本轮 `pig_dw_menu_quartz.sql` 的 `DELETE job_id=9605` 被跳过）。

## 3. 修复：备份 → 用自带 SQL 执行台补依赖 → 重跑

```bash
# ① 升级前逻辑备份（落容器 /app/backups，保 5 份）
curl -s -X POST -H "Authorization: Bearer $TOK" -H "TENANT-ID: 1" \
  http://localhost:9999/admin/db/upgrade/backup

# ② 只补「真缺表」的建表语句（从提供方脚本精确抽取，逐条 assert 以 ; 结尾，
#    并断言不含 DROP DATABASE / GRANT / CREATE USER）
#    写入 /tmp/fix-ddl.sql 后用 python 生成 payload，避免手写转义：
python3 -c "import json;s=open('/tmp/fix-ddl.sql',encoding='utf-8').read();open('/tmp/p.json','w',encoding='utf-8').write(json.dumps({'sql':s,'allowWrite':True}))"
curl -s -X POST -H "Authorization: Bearer $TOK" -H "TENANT-ID: 1" -H "Content-Type: application/json; charset=utf-8" \
  --data-binary @/tmp/p.json http://localhost:9999/admin/db/upgrade/sql/execute

# ③ 继续跑完
curl -s -X POST -H "Authorization: Bearer $TOK" -H "TENANT-ID: 1" \
  http://localhost:9999/admin/db/upgrade/execute > /tmp/exec.json
```

**SQL 执行台参数（`DbSqlConsoleService`）**：`MAX_SQL_LENGTH=200000`、`MAX_STATEMENTS=20`、`MAX_ROWS=500`；`allowWrite=true` **且**账号需真持有 `sys_db_console_write`；永久黑名单 = `DROP DATABASE/SCHEMA`、`CREATE DATABASE/SCHEMA`、`CREATE/DROP/ALTER USER|ROLE`、`SET PASSWORD`、`GRANT/REVOKE`、`SHUTDOWN/SET GLOBAL`（命中即**整批拒绝**，不会半跑）；每次调用自动备份 + 写 `sys_db_sql_console_log`（被拒的也记 `mode=BLOCKED`）。

🔴 **payload 必须是纯 JSON**：别把 `python3 - <<EOF` 的 `print` 一起重定向进 payload 文件，会得到 `请求体格式错误，无法解析`。

🔴 **两条备份纪律**（备份是 §3 的第 ① 步，但两处都容易做假）：
1. **升级器自带的 `backup` 端点用的是「当前连接默认库」**（`WHERE table_schema = DATABASE()`）—— 池一旦被污染（§5 末条），它会**安静地备份别的库**：2026-10-13 实测返回 `{"tables":14}`，而 `pig` 有 254 张表、`pig_dw` 恰好 14 张 ⇒ 那份备份毫无价值。**拿它当备份前先核对 `tables` 数量是否与 `pig` 同量级**；不确定就改用 mysqldump：
   ```bash
   docker exec linmo-mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" \
     --single-transaction --routines --triggers --default-character-set=utf8mb4 \
     --databases pig pig_dw pig_config' > output/db-backup/pig-3schema-$(date +%Y%m%d-%H%M).sql
   # 自校验：grep -c '^DROP TABLE IF EXISTS' 应 = 三库表数之和
   ```
2. 备份落 `output/`（被 gitignore），**别提交进仓库**。

🔴 **修完框架层代码后必须重建镜像并重启**：脏连接**已在运行中的连接池里**（实测中断后 4 分钟备份端点仍在用脏连接），只重放 SQL 不会自愈。先 `--force-recreate` 旧镜像止血，再重建 + 重启一次。

## 4. 验收清单（逐项打勾才算修好）

| 项 | 期望 |
|---|---|
| `GET /db/upgrade/pending` | `pendingCount=0` 且 `modifiedCount=0` 且 `executed==total` |
| `sys_db_migration` | `FAILED` 计数 = 0 |
| `/db/upgrade/execute` 返回 | `success=true`，无 `ok:false` |
| 数据面 | 种子脚本声明的行数在目标表里**逐值对齐**（用文件头的「快照范围」注释对账） |
| 菜单类脚本 | 动过 `sys_menu`/`sys_role_menu` ⇒ 清 Redis db5 `gl:menu_details::*` + `gl:user_details::*`（TTL=-1 永不过期） |
| 权限链 | `sys_menu` 中 `menu_id>=6000` 且无 `sys_role_menu` 的孤儿数 = 0 |
| 运行态日志 | 无 `Table '<别的库>.<本库的表>' doesn't exist`；无随之而来的 Quartz 触发器扫描报错 / `xxx queue unavailable` 类连带报错 |
| 库对象完好 | `pig` / `pig_dw` / `pig_config` 三库表数与升级前一致（本次实测 254 / 14 / 12，前后不变） |

## 5. 常见衍生坑

- 🔴 **新首因（2026-10-13 实测）：脚本 `USE <别的库>` 且结尾不回切 ⇒ 污染连接池。** 判别信号三连：① `sys_db_migration` **零 FAILED 却中断**；② 日志 `Table 'pig_dw.sys_db_migration' doesn't exist` / `pig_dw.ai_app_config` 之类；③ 紧接着 `pig_dw.sys_log does not exist`、Quartz `scanning for the next triggers` 报错、`FinanceWorker: Financial queue unavailable` —— **故障半径远超升级本身**。机理：`DbUpgradeService.runScript()` 用池连接执行后直接 `close()` 归还，**不恢复默认库** ⇒ 下一次 `getConnection()` 拿到脏连接：`upsert()` 的非限定 INSERT 打飞（`upsert` 自带 catch **只记日志不抛** ⇒ 所以连 FAILED 行都没有、升级却继续往下走），随后**自身没有 `USE` 的脚本**整体失败 ⇒ `break`。
  - 修法（框架层，已落地）：`appCatalog()` 从 JDBC URL 末段解析库名、`appConnection()` 借出归一、`runScript()` 的 `finally` 归还前归一，统一发 `USE \`pig\``。**别用 `Statement#setCatalog`** —— 驱动对「执行 `USE` 语句」造成的库切换不更新本地 catalog 缓存。
  - `DbSqlConsoleService` 已用 `^\s*USE\s` 拒绝 `USE`，所以**污染口只有升级执行器一个**。
  - 新脚本若必须切库，**结尾补 `USE \`pig\`;`**（`pig_dw_ddl.sql` / `pig_config.sql` 就是这惯例）。
- 🔴 **`upsert()` 静默吞错**（`catch` 只 `log.error`）是把「登记丢失」藏起来的原因：升级照跑、`pending` 却把该脚本标成 `MODIFIED` 每轮重跑。日志里见到 `登记脚本执行记录失败` 必须立刻查。
- 🔴 **`sys_job` 主键是 `(job_id, job_name, job_group)` 复合键** ⇒ 同 `job_id` 不同名/不同组**并存不报错**，`ON DUPLICATE KEY UPDATE` **静默落空**（插了新行）。表现为「定时任务列表出现两个同 id」。判定「新行 vs 被更新」看 **`create_time`**，别只看 `update_time`。
- **`job_status` 语义**：`1 未发布 / 2 运行中 / 3 暂停 / 4 删除`。SQL 里写 `'1'` 进库的是**未发布**，本项目约定要**到页面手动点「启动」**才会调度；🔴 **「改 job_status 再点启动」与「改 job_status 再 `POST /sys-job/refresh-jobs`」两条路混用会互相抵消**，选一条。
- **升级本身不需要重启服务**（框架跑在运行中的 app 内，执行完即生效）；🔴 **但本次这类「改了 Java」或「池已被污染」的场景必须重建 `linmo/pig-boot` 镜像并重启**，见 §3 末条。
- **未新增 `pig/db/**/*.sql` 时无需重跑 `tools/gen_db_merged.py`**（`merged/` 三文件层只在 pig/db 有新脚本时才变）。
- **根治方向（需拍板，勿擅自改）**：① 给脚本加 `-- @requires:` 声明 + 拓扑排序；② seed 类脚本用 `zz_` 前缀把字典序推后；③ 维持现状 + 依赖本流程手工补依赖。

## 6. 交付

产出一份 `output/YYYYMMDD-数据库在线升级-失败排查与修复报告.md`：失败点 / 三层根因（触发条件 · 真因 · 放大器）/ 修复动作 / N 个待执行脚本结果表 / 验收核验表 / 副作用与遗留 / 复现命令 / 线上需另跑的动作清单。用 `present_files` 交付。
