---
name: git-lost-files-recovery
description: 排查「仓库/工作区里的文件不见了」并从 git 历史恢复，同时判定哪些是真丢了。当用户说「查看文件是否丢失」「文件丢了/不见了」「交付文档没了」「output 里的东西没了」「恢复被删的文件」「清理时误删」「这文件还在吗」时使用。覆盖：建立"应有文件清单"、判定是否曾入库、用删除提交的父提交取回、识别 .gitignore 整目录忽略造成的不可恢复区、恢复后复扫文档死链。
agent_created: true
---

# 仓库文件丢失排查与恢复

## 何时用

用户报告"文件找不到了"，或你要在动手清理/迁移前确认"会不会丢东西"。

**不要**直接按用户给的单个文件名去 `find` —— 先做"应有 vs 实有"的差集，因为用户通常只说得出一个，实际丢的是一批。

---

## 一、四条判据（必背，决定 90% 的结论）

| # | 判据 | 含义 |
|---|---|---|
| 1 | `git ls-tree <删除提交> -- <path>` **恒返回 0 行** | 该提交已经删掉了文件；必须用 **`<删除提交>^`**（父提交）才能列出删除前清单。这是最容易踩的坑 |
| 2 | `git log --all --format=%H -1 -- <path>` 有值 | 该路径**曾进入过版本库** ⇒ 内容可从历史取回 |
| 3 | 同上命令无输出 | **从未入库** ⇒ git 里没有，只能找副本，否则永久丢失 |
| 4 | `.gitignore` 中有**整目录**规则（如 `output/`、`dist/`） | 该目录下**规则生效后新增的文件永不入库**。目录内老文件仍被跟踪（不受影响），但新文件"删了就真没了" |

推论：**"曾入库"≠"现在能恢复"的前提是它被删了；"从未入库 + 被 gitignore"= 最高危。**

---

## 二、执行步骤

### Step 0 · 先排除"多份 clone"造成的假丢失
```bash
ls -ld ~/work/*<项目名>* ~/work/*/<项目名>* 2>/dev/null   # 注意子目录也要看
```
> 本机常见第二份 clone 在 `~/work/pig/<项目名>`。若确实有两份，先比对 `git log` —— 早期初始提交的那份**不含后期产物**，不能当恢复源。

**坑**：`ls -ld ~/work/*linmo* ~/work/*pig*` 会因两个模式都匹配同一目录而输出两行看似"两份"的结果。用 `ls -la ~/work/` 看真实条目数。

### Step 1 · 建立"应有文件清单"
不要靠记忆。从**文档索引**和**工作日志**里正则提取路径，得到"系统认为存在"的集合：
```python
pat = re.compile(r'(?<![/\w])((?:output|docs|tools|deploy)/[^\s`\'"()<>\[\]，。；：、,;:|*]+?\.(?:md|sql|py|sh|json|ts|vue|png|ya?ml|conf|bat|txt))')
# 来源：docs/00-*索引*.md、docs/*.md、.workbuddy/memory/*.md
```
> 排除 `node_modules`/`dist`/`build`（用户硬约定，glob 与 find 都适用）。

### Step 2 · 逐项判定（存在？曾入库？）
```bash
for f in <清单>; do
  [ -e "$f" ] && { echo "存在 $f"; continue; }
  c=$(git log --all --format='%H' -1 -- "$f")
  [ -n "$c" ] && echo "🟢可恢复 $f" || echo "🔴从未入库 $f"
done
```
分类成四档再报告：**永久丢失 / 可恢复·交付物 / 可恢复·数据快照 / 临时产物（无需恢复）**。

### Step 3 · 定位删除提交并取父提交
```bash
c=$(git log --all --format='%H' -1 -- <path>)       # = 删除提交
git ls-tree -r --name-only "$c^" -- <path> | wc -l  # 删除前文件数 ← 关键
git log --all --oneline -1 -- <path>                # 看提交信息（常是 "清理中间产物"）
```
一并查 `.gitignore` 的引入提交：`git log --oneline -3 -- .gitignore`。

### Step 4 · 恢复（**只写磁盘，不动 git 索引**）
```bash
D=<删除提交>
git archive "$D^" <path> | tar -x -C /tmp/restore     # 提取到临时目录
```
再用 Python 比对后拷贝，条件：
- **跳过工作区已存在的文件**（避免用旧版本覆盖新内容）
- **跳过"过程产物"目录**（截图、探针）——按用户意图定
- 注意 `_*` 前缀：**只在 output 根目录排除**，子目录内的 `_raw.json`、`_回滚-*.sql` 往往是有价值的

> ⚠️ **不要用 `git checkout <commit> -- <path>`**：它会把文件重新纳入索引，等于把 gitignore 的目录又带回版本库。
> 若已误用，`git reset -- <path>` 只能取消暂存，跟踪关系仍在 —— 需 `git rm --cached -r <path>` 收拾。

### Step 5 · 复扫文档死链
恢复后，`docs/` 里指向这些文件的引用会**自动变有效**。剩下的通常是：
- `archive/` 内文档漏写目录前缀（`docs/x.md` 应为 `docs/archive/x.md`）
- 文档改名后的旧名引用
- **叙述性引用**（"历史上有过一份 `docs/旧名.md`"）—— 这类不是死链，去掉反引号或改成非路径写法即可

### Step 6 · 报告与防复发
报告必须含：永久丢失清单（点明影响）、可恢复清单与来源提交、复跑命令、根因、**防复发建议**。
防复发建议的核心一句：**已被整目录 gitignore 的目录不要再放不可再生的东西**；交付文档移出该目录，或入库时 `git add -f`。

---

## 三、延伸：gitignored 的**配置文件**丢了怎么办（如 `deploy/.env`）

场景：某文件被 `.gitignore` 忽略、且从未真正入库（或曾入库但内容早被本地增补）⇒ 从 git 取不回**当前版本**。

典型是 `deploy/.env` 这类**覆盖文件**：只写少量覆盖键，其余键由主 env 文件或编排默认值提供 —— 但它往往是把服务指向**本机**而非**发布栈**的关键。丢了以后 `docker compose --env-file deploy/.env ...` 会**直接报错**（`couldn't find env file`），所有文档里的标准入口全部失效。

### 判据：**容器实际值 ≠ 编排默认值 ⇒ 必由该覆盖文件贡献**

```bash
# 1) 拿容器实际注入值
docker inspect <容器> --format '{{range .Config.Env}}{{println .}}{{end}}'
```
```python
# 2) 解析编排里所有 ${VAR} / ${VAR:-default}，与容器值比对
re.finditer(r'\$\{([A-Z_][A-Z0-9_]*)(?::?-([^}]*))?\}', compose_text)
# 需写进覆盖文件的键 = 容器值 ≠ 编排默认值，且 ≠ 主 env 文件的值
```

要点：
- **只写差集**。别凭印象把主 env 文件已有的键再抄一遍 —— 后者覆盖前者，抄错反而更糟。
- **同值不算覆盖**：容器值恰好等于编排默认值时无法区分来源，不必写（写不写等价）。
- **别凭印象塞键**：例如 `REDIS_HOST` 的编排默认值本就是正确的容器名，写了不仅无用还可能引入错误。
- 重建后先校验再重启：
  `docker compose --env-file A --env-file B -f X.yml config | grep <KEY>` —— 看插值结果对不对，**确认无误再 `up`/`restart`**。
- 文件权限设 `600`（含口令/DSN）。
- ⚠️ 反推不到的部分：**被编排引用、但两个 env-file 都没提供、且未进容器**的键（只用于 compose 插值，容器里看不到）。这类键缺失会让重建时落到默认值 —— 必须向用户确认或查项目文档，不要臆造。

### 先读再跑：项目自带的启停脚本往往是过期的

`*-start.sh` / `*-restart.sh` 常见问题：容器名沿用旧命名（如 `pig-mysql` 而实际是 `linmo-mysql`）、把本该是容器的服务当宿主机进程再起一份 ⇒ 抢端口、与真实拓扑冲突。
**动手前先 `docker ps` 对齐实际容器名与编排 service 名**（`container_name` 与 service 名常不一致，例如 service `pig-gateway` 的容器叫 `linmo-pig-boot`）。

### 重启方式的选择

- **`docker compose ... restart`** = 原地 stop+start，**不重建容器、不改拓扑** ⇒ 缺配置时最安全。
- **`up -d` / `--force-recreate`** 会按编排重新解析环境 ⇒ 缺覆盖文件时会静默回落到错误默认值（典型症状：服务不崩、但全站 502 / 连不上库）。
- 带 `profiles` 的 service 必须显式 `--profile <名>` 才会纳入。
- 探活：**4xx 常常是正常的**（未认证伪装码、令牌过期）；真实判据是容器 healthcheck = `healthy`，以及业务响应里出现的是**业务错误码**而不是网关错误（502/504）。

---

## 四、坑清单

1. `git ls-tree <删除提交>` 恒为 0 —— 必须用 `^`。
2. `ls -ld` 多模式匹配造成的"假多 clone"。
3. `find -maxdepth 4` 找不到深层文件（`output/db-backup/2026-09-29/pre-reset.sql` 是第 5 层）→ 别设太浅。
4. `_*` 规则误伤子目录内有效文件。
5. `git archive` 只对**曾入库**的路径有效；从未入库的路径会静默产出 0 文件。
6. 中文文件名在 shell 变量/循环里注意引号；输出乱码不影响判定结果（看退出码）。
7. 恢复后 `git status` 若显示大量 `??`，说明目标目录**没有**被 gitignore —— 那是另一回事（别顺手 add）。

---

## 五、最小命令集

```bash
# 1 是否曾入库（有值=可恢复）
git log --all --format='%H' -1 -- <path>

# 2 删除提交的父提交里有多少文件
c=$(git log --all --format='%H' -1 -- <path>); git ls-tree -r --name-only "$c^" -- <path> | wc -l

# 3 取回（不碰索引）
git archive "$c^" <path> | tar -x -C /tmp/restore

# 4 谁引入的 gitignore 整目录规则
git log --oneline -- .gitignore
```

---

## 六、变体：改动其实在**另一个分支**（"代码怎么没了"）

**症状**：`git status` 干净，当前分支 grep 不到那个函数/文件，用户以为改动丢了、准备重做。

**先别重做 —— 大概率是被提交到别的分支了。** 最快的证据是 reflog：

```bash
git reflog -15                                   # 看 "commit:" 与 "checkout: moving from X to Y"
git branch -a                                    # 所有本地/远端分支
git log --all -S "函数名或特征字符串" --oneline     # 精确定位哪个提交引入了它
```

reflog 里出现 `checkout: moving from A to B`、且当前分支 grep 不到 → 改动在 A 上。

**验证合并是否安全（完全不动当前工作区）**：

```bash
# 1 预判冲突：只输出一个 tree OID = 无冲突（有冲突会列出文件名且退出码非 0）
git merge-tree --write-tree --name-only <目标分支> <来源分支> | head

# 2 在临时 worktree 里真合并 + 跑测试
git worktree add /tmp/check <来源分支>
cd /tmp/check && git merge <目标分支> --no-edit && <跑测试>
cd - && git worktree remove /tmp/check
```

**别凭"两边都改过同一文件"就断言有冲突** —— git 按行合并，改的位置不重叠就自动合。
实测：一方新增函数、另一方改别的函数，429 行 vs 154 行的改动也能干净合并（60 项测试全过）。

**落地**（目标分支是来源分支的父时最干净）：

```bash
git merge <来源分支> --ff-only      # 快进，不留 merge commit
```

注意目标分支是否在跟踪远端：本地 `dev` 跟踪 `origin/dev` 时，合并后本地会**领先远端**，
push 前先跟用户确认（那可能是同事的分支）。
