---
name: linmo-db-script-consolidate
description: 【⛔ 已于 2026-10-15 晚整条退役 —— 仅当用户明确要考古/回滚旧「散脚本+ORDER+保序切段」路线时才读】把灵猫企管（linmo-pig-full）`pig/db` 的散 SQL 初始化脚本**合并/重组为少量按功能命名的文件**，并**验证合并前后初始化结果等价**。当用户说「把 db 脚本合并」「按功能合并成单独的文件」「pig/db 去重合并」「脚本太多整理一下」「把 pig/db 移到 bak 再合并」「验证合并是否等价」「pig/db 落后 db_bak」「consolidate_db 报未登记 ORDER 拒绝生成」，或需要收敛/重排 `pig/db` 而**不能改变初始化语义**时使用。覆盖：① 动手前必跑的**依赖分析**（判断「按 SQL 类型分组」是否可行）；② **保序切段**生成器模式（段间拼接严格等于原 ORDER）；③ 合并必做的两处**状态复位**（`USE` / `DELIMITER` 跨脚本泄漏）；④ loader「含 `DROP DATABASE` 即拒绝」对生成物的**误伤**与 `@generated-by` 解法；⑤ **双临时容器等价性实测法**（8 项计数 + 全库 `mysqldump` diff）；⑥ 下游链路清点（pom / `DbUpgradeService` / merged 层退役 / 文档与测试同步）；⑦ **日后维护的漂移判据**（生成器硬失败 ⇒ `pig/db` 正文一起落后；`merge_integrity_check` 第 4 项会假绿，禁作判据）。
agent_created: true
---

# pig/db 初始化脚本：合并 / 重组 / 保序切段 + 等价性实测

> ## ⛔ 2026-10-15 晚起：本技能**整条前提已失效，默认不要执行**
>
> `pig/db` 已由「散脚本 + ORDER + 保序切段合并生成物」整条换成 **3 份 `mysqldump --databases` 三库全量快照**
> （`pig{,_config,_dw}YYYYMMDD.sql`，各含 `CREATE DATABASE`/`USE`，自含建库）+ 三件套（`Dockerfile` / `initdb-loader.sh` / `README.md`）。
> 换代提交：`3e7e4a1d`（切快照）→ `29fa8b7b`（退役 `pig/db_bak`）。**`pig/db_bak/` 已删除**，
> `tools/consolidate_db.py` 跑必 `FileNotFoundError: pig/db_bak/initdb-loader.sh`。
>
> - 🔴 **别再跑** `tools/consolidate_db.py`、别再找 `initdb-loader.sh` 的 `ORDER=(...)`（新版 loader 里 `grep -i order` 命中 **0**），
>   也别再重建 `pig/db_bak/`。本文件以下全部内容**只作考古**（历史事故与判据仍有参考价值）。
> - **现行语义**：loader 用 `find ... -name '*.sql' -not -path '*/manual/*' -not -path '*/merged/*' | LC_ALL=C sort`
>   按**相对路径字典序自动导入**；非自含增量脚本必须**排在全部 dump 之后**（靠 `zz_` 前缀，如 `zz_menu_20261015_schedule.sql`）。
> - **换快照** = 导新 dump、删旧 dump，**三件套不用改**。判「`pig/db` 是否最新」= dump 文件名日期 + 运行库表数/关键行数核对
>   （**不是** `consolidate_db.py`）。细则：仓库 `.workbuddy/memory/topics-db-initdb-order.md` **§I12**。
> - 相关：`tools/merge_integrity_check.py` 第 4 项已于 2026-10-15 适配快照路线（本文件 §7 里「第 4 项会假绿，禁作判据」的结论**已过时**）。

> 2026-10-14 首次实战：把 `pig/db`（176 散脚本 + 12 功能域子目录）收敛为
> `pig/db/{01_base_schema, 02_ai_platform, 03_enterprise_core, 04_agents_business,
> 05_dw_connector_kb, 06_menu_perm_patch}.sql`，`pig/db_bak/` 作归档兼合并源。
> 等价性实测 **dump diff = 0 行**。

---

## 0. 🔴 第一步永远是「依赖分析」，不是动手切文件

用户说「按功能合并」时，**先判断能不能按 SQL 类型（结构/菜单/种子/补丁）跨域聚拢** ——
在这个仓库里答案通常是**不能**，且必须用数据说话，否则做出来的东西会打断初始化依赖。

```bash
cd /Users/shan/works/linmo-pig-full
/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 - <<'PY'
import re, pathlib, collections, heapq
root = pathlib.Path('pig/db')          # 或 pig/db_bak
txt = (root/'initdb-loader.sh').read_text(encoding='utf-8', errors='replace')
m = re.search(r'^ORDER=\((.*?)^\)', txt, re.S|re.M)
order = [l.split('#')[0].strip() for l in m.group(1).splitlines() if l.split('#')[0].strip()]
idx = {p.name: p for p in root.rglob('*.sql')
       if p.relative_to(root).parts[0] not in ('manual','merged')}
def code(f):
    t = idx[f].read_text(encoding='utf-8', errors='replace')
    t = re.sub(r'--[^\n]*', '', t)
    return re.sub(r'/\*.*?\*/', '', t, flags=re.S)
W = re.compile(r'\b(?:INSERT\s+(?:IGNORE\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE)\s+`?([A-Za-z_0-9]+)`?', re.I)
def classify(f):
    c = code(f)
    if re.search(r'\bCREATE\s+(TABLE|VIEW|INDEX|TRIGGER)\b', c, re.I): return 'schema'
    if re.search(r'\bALTER\s+TABLE\b', c, re.I): return 'schema'
    tg = set(t.lower() for t in W.findall(c))
    if tg & {'sys_menu','sys_role_menu'}: return 'menu'
    if tg & {'sys_job'}: return 'jobpatch'
    return 'seed'
cls = {f: classify(f) for f in order}
writes = {f: set(t.lower() for t in W.findall(code(f))) for f in order}
# 拓扑排序：类型优先 + 同表保序
pos = {f:i for i,f in enumerate(order)}
succ = collections.defaultdict(set); indeg = collections.Counter({f:0 for f in order})
for t in set().union(*writes.values()):
    wl = [f for f in order if t in writes[f]]
    for a,b in zip(wl, wl[1:]):
        if b not in succ[a]: succ[a].add(b); indeg[b] += 1
GP = {'schema':0,'menu':1,'jobpatch':2,'seed':3}
h = [(GP[cls[f]], pos[f], f) for f in order if indeg[f]==0]; heapq.heapify(h)
out = []
while h:
    _,_,f = heapq.heappop(h); out.append(f)
    for g in sorted(succ[f], key=lambda x: pos[x]):
        indeg[g] -= 1
        if indeg[g] == 0: heapq.heappush(h, (GP[cls[g]], pos[g], g))
runs = []
for f in out:
    if runs and runs[-1][0]==cls[f]: runs[-1][1] += 1
    else: runs.append([cls[f],1])
print("类型分布:", dict(collections.Counter(cls.values())))
print(f"拓扑后连续段数 = {len(runs)}（若 >5 ⇒ 无法按类型分块，只能保序切段）")
sm = [f for f in order if 'sys_menu' in writes[f]]
print(f"写 sys_menu 的脚本 = {len(sm)}，类型分布 = {dict(collections.Counter(cls[f] for f in sm))}")
PY
```

**判据**：
- 连续段数 **≤ 4~5** ⇒ 可以按类型分组（罕见）。
- 连续段数 **几十** ⇒ **不可行**，走 §1 保序切段。2026-10-14 实测：68 个写 `sys_menu` 的脚本
  （schema 29 + menu 39）完全交错 ⇒ 拓扑后 **42 段 / 41 次类型切换**；强行聚拢有 **344 对
  顺序倒置**，含真实依赖（`ai_app_default_model.sql` 归位 `model_code` 依赖
  `ai_dify_app_seed.sql` 已插入的行）。

**顺便查「去重」有没有对象**：文件级完全重复通常**一个都没有**（176 个脚本 md5 两两不同），
语义级"重复"（`sys_menu` 被 50 个脚本分别 INSERT）是**功能分散，不是冗余** ——
别自动合并它。用 md5 分组即可确认：

```bash
find pig/db_bak -name '*.sql' -not -path '*/manual/*' -not -path '*/merged/*' \
  -exec md5 -q {} \; -exec echo "  {}" \; | paste - - | sort | uniq -D -w32
```

---

## 1. 保序切段（唯一能保证语义不变的合并方式）

**核心不变式**：把 `ORDER` **切成连续段**，段间拼接后**严格等于原 ORDER**。
只要成立，初始化结果与合并前**逐字节相同**（连 AUTO_INCREMENT 插入顺序都一致）。

生成器：`tools/consolidate_db.py`（已在本仓，直接复用/改造）。关键设计：

| 要点 | 做法 |
|---|---|
| 源/目标 | 源 `pig/db_bak/`（散脚本 + 其 `initdb-loader.sh`），目标 `pig/db/` |
| 切段表 | `SEGMENTS = [(输出名, ORDER 起, ORDER 止, 主题)]`，必须**连续、无重叠、全覆盖**（脚本内自检） |
| 段头 | 写「本文件由谁生成 / 覆盖 ORDER 第 x~y 个 / ORDER 指纹 / 包含脚本清单」 |
| 块头 | `-- [k/N] <文件名>` + `-- 源：<相对路径>` + **从源 ORDER 提取的依赖注释**（最有价值的部分，别丢） |
| 块尾 | **无条件追加** `DELIMITER ;` + `` USE `pig`; ``（见 §2） |
| 自检 | `--verify` 回读所有块头，断言顺序 == ORDER |

```bash
/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 tools/consolidate_db.py --verify
# 期望：合计 N 脚本 == ORDER 条目数；[OK] 自检通过
```

---

## 2. 🔴 合并必做的两处「状态复位」（否则静默错库/解析崩）

原 loader 是 **`mysql_exec "$DB" < "$SRC_DIR/$f"` —— 每个脚本一次独立 mysql 进程**，
所以 `USE` / `DELIMITER` **天然不跨脚本泄漏**。合并后多个脚本进**同一次调用**，
必须显式复位。**每脚本块后无条件追加**：

```sql
DELIMITER ;      -- 复位被 `DELIMITER $$`（存储过程/触发器）改过的分隔符
USE `pig`;       -- 复位被切走的库
```

本仓已知切库脚本（体检命令见下）：`pig_config.sql`→pig_config、`pig_dw_ddl.sql`→pig_dw、
**`20261010_media_dwd.sql`→pig_dw 且结尾不回切**（正是内存 §I8 那个坑）。

体检命令（合并前跑一次，列全待复位项）：

```bash
cd /Users/shan/works/linmo-pig-full && /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 - <<'PY'
import re, pathlib
bak = pathlib.Path('pig/db_bak')
txt = (bak/'initdb-loader.sh').read_text(encoding='utf-8', errors='replace')
m = re.search(r'^ORDER=\((.*?)^\)', txt, re.S|re.M)
order = [l.split('#')[0].strip() for l in m.group(1).splitlines() if l.split('#')[0].strip()]
idx = {p.name: p for p in bak.rglob('*.sql') if p.relative_to(bak).parts[0] not in ('manual','merged')}
def strip(t): return re.sub(r'/\*.*?\*/','',re.sub(r'--[^\n]*','',t),flags=re.S)
for f in order:
    raw = idx[f].read_text(encoding='utf-8', errors='replace')
    c = strip(raw).strip()
    if c and not c.endswith(';'): print("① 结尾非分号:", f)
    ds = re.findall(r'(?im)^\s*DELIMITER\s+(\S+)', raw)
    if ds and ds[-1] != ';': print("② DELIMITER 未复位:", f, ds[-1])
    us = re.findall(r'(?im)^\s*USE\s+`?([A-Za-z_0-9]+)`?\s*;?', raw)
    if [x for x in us if x != 'pig']: print("③ 切库:", f, sorted(set(us)), "最后 USE =", us[-1] if us else None)
PY
```
（2026-10-14 实测：① 仅 1 个（末行是注释，无害）；② 0 个；③ 3 个。）

---

## 3. 🔴 loader 的「含 DROP DATABASE 即拒绝」会误伤合并文件

`pig/db/initdb-loader.sh` 有内容级兜底 `grep -qiE 'DROP[[:space:]]+DATABASE'`（防全量 dump 清库）。
**合并后会误伤整份文件** —— 命中源常常是**搬进块头的 ORDER 注释**（本仓是
`sync_172_20261006.sql` 那条「两者不含 DROP DATABASE / TRUNCATE」），**源脚本本身干净**。

**解法（已落地）**：生成物文件头加 ASCII 标记 + loader 识别跳过：

```bash
# 生成器：文件第一行
-- @generated-by: tools/consolidate_db.py — DO NOT EDIT MANUALLY

# loader：
is_generated() { head -5 "$SRC_DIR/$1" 2>/dev/null | grep -q '@generated-by:'; }
...
if ! is_generated "$f" && grep -qiE 'DROP[[:space:]]+DATABASE' "$SRC_DIR/$f"; then 拒绝
```

⇒ **生成物**（生成器已逐源脚本校验）跳过内容兜底；**任何往 `pig/db` 直接丢的散脚本仍被拦**。

---

## 4. ✅ 等价性实测法（唯一可信的验收，10 分钟）

**双临时容器 + 独立卷，绝不碰 `linmo-mysql` 与在用数据卷。**

```bash
D=/Applications/Docker.app/Contents/Resources/bin/docker
REPO=/Users/shan/works/linmo-pig-full
W=$HOME/linmo-initdb-check; rm -rf "$W"; mkdir -p "$W/a" "$W/b"
cp "$REPO/pig/db_bak/initdb-loader.sh" "$W/a/zz-import-all.sh"
cp "$REPO/pig/db/initdb-loader.sh"     "$W/b/zz-import-all.sh"
chmod +x "$W/a/zz-import-all.sh" "$W/b/zz-import-all.sh"     # 🔴 不加可执行位 = entrypoint 报 126

run() { $D run -d --name "$1" -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=pig \
  -e PIG_SQL_DIR=/opt/pig-db -v "$2":/var/lib/mysql -v "$3":/opt/pig-db:ro \
  -v "$4":/docker-entrypoint-initdb.d:ro mysql:8.0 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_general_ci \
  --lower_case_table_names=1 --default-time-zone=+08:00 >/dev/null; }
run tmp-initdb-a tmp-initdb-vol-a "$REPO/pig/db_bak" "$W/a"
run tmp-initdb-b tmp-initdb-vol-b "$REPO/pig/db"     "$W/b"
# 等两边日志出现 MySQL init process done（~30~110s），再等 mysqladmin ping（done 之后才起正式 server）
```

对账（**计数 + 全库数据级 diff，缺一不可**）：

```bash
CS="SELECT 'BASE_TABLE',COUNT(*) FROM information_schema.tables WHERE table_schema='pig' AND table_type='BASE TABLE'
UNION ALL SELECT 'VIEW',COUNT(*) FROM information_schema.tables WHERE table_schema='pig' AND table_type='VIEW'
UNION ALL SELECT 'sys_menu',COUNT(*) FROM pig.sys_menu
UNION ALL SELECT 'sys_role_menu',COUNT(*) FROM pig.sys_role_menu
UNION ALL SELECT 'sys_job',COUNT(*) FROM pig.sys_job
UNION ALL SELECT 'oauth',COUNT(*) FROM pig.sys_oauth_client_details
UNION ALL SELECT 'ai_app_config',COUNT(*) FROM pig.ai_app_config
UNION ALL SELECT 'ops_connector',COUNT(*) FROM pig.ops_connector;"
for c in a b; do $D exec tmp-initdb-$c mysql -uroot -proot -N -B -e "$CS" > $W/count-$c.txt; done
paste $W/count-a.txt $W/count-b.txt | awk -F'\t' '{printf "%-16s A=%-8s B=%-8s %s\n",$1,$2,$4,($2==$4?"OK":"<<< DIFF")}'

for c in a b; do
  $D exec tmp-initdb-$c sh -c "mysqldump -uroot -proot --no-create-info --skip-comments \
    --skip-extended-insert --order-by-primary --set-gtid-purged=OFF --databases pig 2>/dev/null" \
  | sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}/<TS>/g' | grep -a '^INSERT INTO' > $W/dump-$c.txt
done
diff $W/dump-a.txt $W/dump-b.txt > $W/dump.diff; echo "diff 行数: $(wc -l < $W/dump.diff)"
```

**判据**：计数 8 项全等 **且** `dump.diff` 为空。
**保序切段应做到 diff = 0 行**（2026-10-14 实测：251 表 / 2 视图 / 菜单 476 / role_menu 485 /
job 39 / oauth 10 / ai_app_config 62 / ops_connector 19；各 2584 条 INSERT，diff 0 行）。
⚠️ 时间戳必须归一（`create_time` 默认 `CURRENT_TIMESTAMP`，两边必然不同）。
⚠️ 若换成「按类型重排」的合并，需容忍 `ops_ext_hr_employee` / `ops_assignee_profile_version`
的 AUTO_INCREMENT 取值差异（内存 §I7）—— 那本身就是**语义已变**的信号，优先查依赖。

收尾：`$D rm -f tmp-initdb-a tmp-initdb-b; $D volume rm tmp-initdb-vol-a tmp-initdb-vol-b`。

---

## 5. 下游链路清点（合并后逐条确认，别漏）

| 项 | 结论（2026-10-14 实测） |
|---|---|
| `pig-boot/pom.xml` 的 `copy-db-scripts` | **不用改**：`directory=${basedir}/../db`（= pig/db）+ `<include>**/*.sql</include>`；排除 `manual/`/`merged/` 自然失效但无害 |
| `DbUpgradeService`（`classpath*:db/**/*.sql`） | **不用改**：仍扫到合并后的文件。顺带消除「loader `EXCLUDED` 3 条 vs Java 1 条」的不一致 |
| **`sys_db_migration` 幂等** | 🔴 **要处理**：文件名 176 → 6 ⇒ 现网库升级页会把 6 个文件当「新脚本」**整批重跑**。上现网前把它们作为 baseline 写入（`status='SUCCESS', cost_ms=0`）。写进 `pig/db/README.md` |
| merged 层（若存在） | 退役：`tools/gen_db_merged.py` / `tools/db-merged-init.sh` 加废弃头注释，`pig/db/merged/` 随 bak 归档，镜像 tag 停用 |
| 文档同步 | 根 `AGENTS.md`（**C-11 红线落点**！）、`pig/AGENTS.md`、`pig-ui/AGENTS.md`、`.claude/skills/*`、`docs/10-Docker打包与更新手册.md` |
| 测试 | `tools/tests/test_initdb_connector_order.py` 读的是 ORDER ⇒ **改指 `pig/db_bak/initdb-loader.sh`** |
| 镜像验收 | `docker build -t <tmp> --build-arg REGISTRY=docker.m.daocloud.io/library/ pig/db` → 验证 `/opt/pig-db` 只有新文件 + `/docker-entrypoint-initdb.d` 只有 loader + 可执行位 OK → `docker rmi -f` |

**给负责人的一句总结**：改脚本一律改 `pig/db_bak/<域>/` 源脚本 + 在其 `ORDER` 登记 →
`python tools/consolidate_db.py --verify` → 提交两者；**永远不要直接编辑 `pig/db/*.sql`**。

---

## 6. 实战踩坑（照抄教训）

- 🔴 **同一条消息里对同一文件发多个 `Edit` 会静默丢失**（本次 3 个 Edit 丢了第 3 个，
  报 success 但未生效）⇒ 逐个改、改完**回读校验**。
- 🔴 **`git commit -- <paths>` / `git add -- <paths>` 不管删除**：本次有 194 个文件删除，
  `git-quick-commit` 的 `--paths` 模式（内部 `git add --`）会漏 ⇒ 用**全量模式**（`git add -A`）。
- 🔴 **推送被 `Permission denied (publickey)` 拦** = 沙箱读不到 `~/.ssh` ⇒ 用非沙箱执行，
  且带 `GIT_SSH_COMMAND="ssh -o UseKeychain=yes -o IdentitiesOnly=yes -i /Users/shan/.ssh/pub -o BatchMode=yes"`。
- 🔴 **别用 `grep -oE '...\.sql' initdb-loader.sh | wc -l` 数 ORDER**：会把 `EXCLUDED`、注释、
  段内引用一并计入。权威 = 只解析 `ORDER=(…)` 再 `split('#')[0]`（与 `menu_sync_audit.py::_parse_array` 同源）。
- ℹ️ `git` 会把「整目录改名」自动识别为 `rename pig/{db => db_bak}/x.sql (100%)` ⇒
  用 `mv` + `git add -A` 即可，**不需要逐个 `git mv`**，历史自然保留。

---

## 7. 🔴 日后维护：怎么判「`pig/db` 是不是已经落后 `pig/db_bak`」

生成器对**未登记 ORDER** 是**硬失败**（不是警告）：

```
[ERR] db_bak 执行集里有未登记 ORDER 的脚本：['xxx.sql', 'yyy.sql']
```

⇒ 只要有人往 `pig/db_bak/` 加了脚本却忘了登记 ORDER，**整条生成链就静默停摆**：
`pig/db` 不只是「少了这几个新脚本」，它的**正文也会一起落后**（后面提交到 `db_bak` 的
内容修正同样进不去）。2026-10-14 实测两个后果同时发生：

1. `kb_qa_schema_faq_sync_20261014.sql` / `..._phases_20261014.sql`（`kb_faq` 台账列）根本没进 `pig/db`；
2. `industry_peer_search_20261008.sql` 的 **`ops_connector` id `…0017` → `…0018`** 事故修正
   （写死 0017 会命中 crm-sim 的 `ON DUPLICATE KEY UPDATE`，覆盖它却不新增本行）
   早已提交在 `db_bak`，却从未进 `pig/db` ⇒ 新建库 / 镜像会**重踩**该事故。

### 判据（权威，两步）

```bash
cd <repo>
# ① 生成器能否跑通？无参数运行 = 只校验，ERR 即证明有未登记脚本（不会写任何文件）
/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 tools/consolidate_db.py
# ② 跑通之后，生成物是否与源一致？空 = 一致
/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 tools/consolidate_db.py --verify
git diff --stat -- pig/db
```

⚠️ **禁止用 `tools/merge_integrity_check.py` 第 4 项判这件事** —— 它只检查
`_last_merge_added_sql()`（**最近一次合并**新增的文件）⇒ 本轮它 4/4 全绿，
却完全掩盖了「生成器硬失败 + 正文漂移」这个更大的洞。

### 修法与验收

1. `pig/db_bak/initdb-loader.sh` 的 `ORDER=(…)` 末尾补登记（附依赖注释，说明为何可置末尾）；
2. `tools/consolidate_db.py` 的 `SEGMENTS` 末段上界随 ORDER 条目数同步改（`119~176 → 119~178`），
   桶内文档串「N 个执行集脚本」也一起改；
3. `--verify` 通过后**逐块核对 `git diff -- pig/db`**：本轮的合理 diff 只有
   「`[k/58] → [k/60]` 重编号」+ 「新追加的 2 个块」+ 「那 1 处 0017→0018」。**出现别的正文改动 = 源被改过，要追。**

## 7.1 🔴 更糟的一种：`pig/db_bak/` 被「整目录删除」（或源路径被改）

2026-10-15 实测形态：工作区出现 **211 个 ` D pig/db_bak/**` + 一个新的未跟踪目录 `pig/merged_db/`
（内容 = `pig/db_bak/merged/` 的**逐字节副本**）⇒ 有人在做「把 merged 层提升为 `pig/merged_db/`、
退役 `db_bak`」的**半截重构**，但**忘了同步改生成器**（`consolidate_db.py` 源路径仍指 `pig/db_bak`、
`merged_db/README.md` 标题仍写 `pig/db/merged`）。

判据同 §7，但失败形态不同 —— 生成器**直接崩**，连 ORDER 都读不到：

```
FileNotFoundError: [Errno 2] No such file or directory: '<repo>/pig/db_bak/initdb-loader.sh'
```

⇒ 🔴 **把「无参跑一次 `consolidate_db.py`」当体检用**：拉取前 / 让路前 / 提交前各跑一次，
3 秒就能暴露「源目录没了」这类会静默毁掉所有克隆的问题。

⚠️ **此时绝不做两件事**：① 别把这个删除当「本地变更」提交（只会得到「新老目录内容重复 + 生成链断裂」
的半成品）；② 别为了恢复而在 `git checkout -- pig/db_bak` 之后把 `pig/merged_db/` 一并删掉。
正解 = 「记删除补丁 + 快照新目录 → `git checkout -- pig/db_bak` 让路 → 提交/快进 →
**新目录保持未跟踪、原样保留**」，并把「此重构是否继续 + 成组完成清单（改生成器源路径与 `SEGMENTS`
→ 移动目录 → 删老目录 → 重跑生成 → 修 README 标题 → 一次提交）」交用户决策。
参见 skill `pull-merge-sync-five-layers` 第 0 层的同条判据。

## 8. 按日盘点「某天新增了哪些脚本」+ 提取交付（2026-10-15 实测）

**触发**：用户说「把 db_bak 今天新的脚本提取出来」「今天加了哪些初始化脚本」。

### 8.1 🔴 别用 mtime —— 它会被任何一次 `git checkout` 洗掉
`pig/db_bak/` 是**目录级**操作的常客（`git checkout -- pig/db_bak` 恢复、ff 合并、切分支）。
一旦发生，整目录 mtime 会被刷成**同一时刻**，`find -newermt` 会返回「全部文件」或「零文件」，
两种都是假答案。**唯一可信口径 = 提交史**：

```bash
# 今天新增(A)的脚本，按提交分组展示
git log --since="YYYY-MM-DD 00:00:00" --date=format:'%m-%d %H:%M' \
        --pretty=format:'@@%h|%ad|%s' --diff-filter=A --name-only -- pig/db_bak
# 只数个数
git log --since="YYYY-MM-DD 00:00:00" --diff-filter=A --name-only --pretty=format: -- pig/db_bak \
  | grep -E '\.sql$' | sort -u | wc -l
# 确认没有「今天新增但未提交」的
git status --porcelain -- pig/db_bak
```
注意 `--since` 按 **committer date** 过滤；`--date=format:` 只改**显示**，两者不要搞混。
（顺带：跨分支并入的提交也按自身提交时间计入，这正是想要的口径。）

### 8.2 盘出来之后必须分成两类 —— 否则会误判「漏登记 ORDER」
| 类 | 位置 | 是否在 `loader` 的 `ORDER` | 是否进 `pig/db` 生成物 | 处置 |
|---|---|---|---|---|
| **A 执行集** | `db_bak/<域>/*.sql` | 应在，且**不在** `EXCLUDED` | 应在（重跑生成器后） | 缺任一 ⇒ 真「漏登记」，须补 |
| **B 手工脚本** | `db_bak/manual/*.sql` | **不在 `ORDER`、也不在 `EXCLUDED`** | **不在**（生成器 `leftovers` 检查只扫执行集） | **正常**，别去补 ORDER；其自述即「按需人工执行」 |

核实 A 类是否「三处齐」：`grep -n '<文件名>' pig/db_bak/initdb-loader.sh`（拿 `ORDER` 行号）
+ `grep -l '<文件名>' pig/db/*.sql`（拿落进哪个合并文件）。`manual/` 三类典型用途：
**只读审计**（不改表/不清缓存）、**本机历史数据清理**（明确授权 + 只本机）、**真人联调冒烟**（占位符待填）。
凡见到 `manual/` 脚本，回报告里要显式标注「不参与 initdb」，避免使用者当初始化脚本执行。

### 8.3 提取交付的落地形态
- 落 `output/`（被 gitignore ⇒ 交付必须走 `present_files`），**保留 `db_bak` 下的相对子目录结构**，
  目录名带日期：`output/db_bak_new_YYYYMMDD/`。
- 同目录生成 `00_INDEX.md`：每个脚本一行 = 相对路径 / 大小 / 行数 / 提交短哈希 + 时间 + 提交标题 /
  `ORDER` 行号或「不在 ORDER」/ 已并入哪个 `pig/db/*.sql`；再附各脚本**头部注释首段摘要**（脚本自身的
  说明往往比提交标题更准确）+ md5。**A/B 两类分表**。
- 再打一个 zip 便于整体下载。拷出后**不动源目录、不提交**（纯读取）。

**校验纪律**：拷完用 `find . -type f -name '*.sql' | wc -l` 与 8.1 的数量对账。
