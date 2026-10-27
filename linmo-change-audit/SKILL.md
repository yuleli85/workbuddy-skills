---
name: linmo-change-audit
description: 对 linmo-pig-full（灵猫企管）做「某一天谁改了什么」的只读审计，按「本地环境变量 / 数据库 / 代码功能」三类出结构化报告。当用户说「审计当前项目今天造成的变更」「统计今天的环境变量/数据库/代码变化」「出变更审计报告」「看看今天谁改了什么」「按归属口径审计」时使用。覆盖：身份口径（同一邮箱多署名）、数据库快照+应用审计表用法、5 个会让人误判的证据陷阱、以及"未提交改动一律标未确认"的归属纪律。
agent_created: true
---

# linmo-pig-full 变更审计（只读）— 环境变量 / 数据库 / 代码

面向「统计某一天由谁造成的变更」这类审计请求。产出是一份**结构化只读报告**，不是修改。

## 0. 铁律（先读，否则结论会错）

- **只读**：不改文件、不写库、不跑迁移、不装依赖。审计报告放回复里；**不要顺手"修"任何东西**。
- 先跑 `date '+%Y-%m-%d %H:%M:%S %Z (%z)'` 确认时区（本机 = CST / UTC+8），报告写明**统计窗口 00:00:00–23:59:59** 与**审计截止时刻**；当日未结束 ⇒ 声明是"截至时刻的部分统计"。
- 先看根 `AGENTS.md` 与根 `MEMORY.md`（`MEMORY.md` 是"可入库的短契约"，**活判据在 `.workbuddy/memory/`**）。
- 排除 `node_modules`/`dist`/`build`。
- 🔴 本机 `grep` 是 brokered shim：**不支持 `\|`/`\b`/`\s` ⇒ 静默 0 匹配（假阴性）**。一律 `grep -E` 或用 Grep 工具。这条在审计里最致命 —— 会把"文件里明明有"报成"没有"。
- 🔴 zsh **不做词分割**：`M="docker exec … mysql"; $M -e "…"` 会 `command not found`（RC=127）。用函数：`m() { docker exec linmo-mysql mysql -uroot -proot -N -B "$@"; }`。

## 1. 身份口径（先钉死，否则整张表都是错的）

```bash
G=/Library/Developer/CommandLineTools/usr/bin/git    # /usr/bin/git 被 Xcode license 拦（Exit 69）
for d in /Users/shan/work/linmo-pig-full /Users/shan/works/linmo-pig-full; do
  echo "== $d"; $G -C "$d" rev-parse --abbrev-ref HEAD
  $G -C "$d" config --get user.name; $G -C "$d" config --get user.email
  $G -C "$d" log -60 --format='%h|A:%an <%ae>|%aI|C:%cn <%ce>|%cI|%s' | grep -E '\|<日期>'
done
```

- 本机身份 = `user.name=yule85` / `user.email=563899691@qq.com`。
  🔴 **同一邮箱在今日提交中以 `yule85` / `yuleli` / `yue​li85` 三种 `user.name` 出现** ⇒ **按邮箱归并**，不要按署名归并，否则会把同一个人拆成三个。
- 他人（今日提交也不算"当前用户"）：`sinclair <tpyzlxy@gmail.com>`、`liviSin <12417489+livi-sin@user.noreply.gitee.com>`。
- 🔴 **本机有多个仓库副本**：Docker 栈只认 `/Users/shan/work/linmo-pig-full`（判据 = 容器 label `com.docker.compose.project.working_dir`）；`/Users/shan/works/…`（**复数**）是孤立 clone。**两个都要看，但报告必须写明哪个是"栈归属"**，否则会把两套历史混成一套。
- 统计"当前用户今日提交"用 `--format='%h|%ae|%s'` 再 grep 邮箱；⚠️ **只写 `%h|%s` 会漏掉邮箱字段 ⇒ 假 0**（实测踩过）。
- 判断某提交是否"功能变更"：`git log -1 --format='%p'` 数父提交个数（=2 是合并，代码内容来自他人）+ `git show --stat --format='' --name-only <sha> | grep -vE '^\.workbuddy/' | grep -c .`（非 memory 文件数）。

## 2. 环境变量

```bash
$G -C "$d" log --since='<日期> 00:00:00 +0800' --format='%h|%an|%aI|%s' -- deploy/    # 谁动了 deploy/
$G -C "$d" show <sha> -- deploy/.env.dev | grep -oE '^[+-][A-Za-z_][A-Za-z0-9_]*='    # 只取变量名
$G -C "$d" diff <日内首提交>^ HEAD -- deploy/.env.dev | grep -oE '^[+-][A-Za-z_][A-Za-z0-9_]*='
$G -C "$d" rev-parse <rev>:deploy/.env.dev                                            # blob hash 比对
docker exec linmo-pig-boot sh -c 'env' | awk -F= '{n=$1;v=substr($0,length(n)+2);print n"\t"(length(v)==0?"EMPTY":"SET")}'
```

- 🔴 **绝不裸跑 `git diff`/`git show` 看 `.env*`**（会打印真实密钥/口令到会话里）。一律 `grep -oE` 只留变量名，或只用 `--stat`。敏感值在报告里统一标 **「已隐藏」**。
- 🔴 **`create_by` / `update_by` 不是可信的操作者**：脚本里能写死字符串。本项目实例：权限登记 SQL 写 `'admin'`、密钥回填 SQL 写 `'key-backfill-20261012'` ⇒ 表里看到的"操作者"其实是脚本字面量。看到 `create_by=admin` 先去读 SQL 文件确认。
- 🔴 **merge / ff 会静默顶掉工作区 `.env*`**（2026-10-12 实测）：某人 08:57 往 `.env.dev` 加了 `PIG_KB_QA_REPORT_URL`，11:47/11:49 两次合并把它**静默恢复成旧 blob（净零）**。判据只用 **blob hash**（`git rev-parse <rev>:path`）—— 不要用 mtime，**也不要**用"`git status` 是否显示 ` M`"倒推。
- 被跟踪的 `.env*`：`deploy/.env.dev` / `.env.example` / `.env.mac` / `.env.template` / `finance.env.example`；`deploy/.env`（gitignored）与 `deploy/.env.head`（未跟踪）是本地必备，只能靠 mtime 判"今天有没有被改"。
- 无环境变量历史快照 ⇒ 容器 env 的**值**是否变化只能写「无法确认」，报告里只列**变量名 + 空/非空**（本机基线：pig-boot 98 个变量 / 14 个空；python-ai 105 / 10 空）。

## 3. 数据库（只读）

```bash
m() { docker exec linmo-mysql mysql -uroot -proot -N -B "$@"; }   # ⚠️ 必须函数，zsh 不词分割
m -e "SELECT @@version,@@global.time_zone,@@system_time_zone,NOW();"   # 确认库时区（本机 +08:00）
m -e "SHOW VARIABLES LIKE 'log_bin'; SHOW VARIABLES LIKE 'general_log';"
```

证据源与适用面：

| 证据源 | 能回答 | 注意 |
|---|---|---|
| 表内 `create_time`/`update_time`/`create_by` | 写入时刻 | `update_by` 可能是脚本字面量；**`sys_job.update_time` 被运行期刷新覆盖**（每次执行都 bump）⇒ 无法据此定位人工修改 |
| `pig.sys_log` | 应用侧操作（登录/导出/同步/`refresh-jobs`） | **直连 SQL 不产生记录** |
| `pig.sys_security_event` | 403 / `UNAUTHORIZED_ACCESS` | 权限类故障**修前**最硬的数据库证据（含 username / request_uri / occur_time） |
| `pig.sys_job_log` | 定时任务执行成败 | 系统生成，非人工；是"修复是否生效"的验收证据 |
| `pig.ai_app_config_history` | AI 应用配置变更版本 | **直连 SQL 不产生快照** |
| `pig.sys_db_sql_console_log` | 应用内 SQL 控制台执行 | 直连 SQL 不记录；今日 0 条 ⇒ 说明没走控制台 |
| `output/db-backup/<ts>/all-databases.sql` | 前后**集合**差异（含删除） | 见陷阱 2 |
| `log_bin`（本机 ON / ROW） | 理论可枚举逐行变更 | 容器内**无 `mysqlbinlog`** ⇒ 本机**不可解码** |

三个必踩的坑：

1. 🔴 **`information_schema.TABLES.UPDATE_TIME` 陈旧不可用**：实测 `sys_job_log` 显示 `11:50`，而表里明明有 `13:45` 的行。**弃用**，改用表内自带时间列。
2. 🔴 **快照基线会被"种子重放"污染**：本项目 DB 在 **2026-10-11 22:01:55** 被种子重放过一次（大量行 `create_time = 2026-10-11 22:01:54~55`）。拿 21:59 的快照去比，会把 `10-11 22:00~24:00` 的变化（**含日志表被截断**）误算成"今日删除"。做法：先查有无成片的"重放时刻"行；再做**闭账校验** —— `重放后行数 + 今日新增行数 == 当前行数`（例：sys_job_log 27 + 193 = 220 ⇒ 那个 −96 是基线假象，不是今日删除）。
3. 🔴 **直连 `docker exec mysql < file>` 不产生任何应用审计记录** ⇒ 「某个 SQL 文件到底有没有对运行库执行」**只能**靠目标表的行内时间戳或快照差异证明，**不能**靠 `sys_log` 里没有记录来反推"没执行"。

集合差异的最小实现（python + docker 只读查询）：解析 mysqldump 的 `INSERT INTO \`表\` VALUES (…),(…);`，按主键求集合差 —— `live − dump` = 新增，`dump − live` = 已删。
⚠️ mysqldump 的**元组跨行、字符串内含逗号** ⇒ **不能用 `split(',')` 当解析器**，要写括号/引号感知的扫描器（引号内 `\,` 是转义）。

## 4. 代码

```bash
$G -C "$d" log --since='<日期> 00:00:00 +0800' --no-merges --format='=== %h | %ae | %aI | %s' --name-status
$G -C "$d" diff --stat                              # 未提交（已跟踪文件）
$G -C "$d" status --porcelain | grep -E '^\?\?'     # 未跟踪
```

- 按**功能领域**归类，并**区分**：功能变更 / 纯 memory·文档 / 合并提交（内容其实来自他人）/ 纯格式·注释·重命名。
- ⚠️ `.workbuddy/memory/**` 的提交是**记忆台账**，不是功能变化。本项目当日大量提交属此类（25 个提交里 8 个纯 memory + 10 个合并），**别把提交数当功能数**。
- 🔴 **未提交改动没有任何 git 时间与作者记录** ⇒ 必须单列「归属或时间未确认」，只能用 mtime + 会话记录 + DB 侧时间戳作旁证，并标明确认程度。

## 5. 出报告

按用户给定格式；**必写**：统计窗口与截止时刻、身份判定方式、比较基线、证据来源、限制。汇总用**「变更项数」而不是文件数**，且每一项都能从前文逐项核对。最后交代当天最重要的已确认变化 + 审计限制。
