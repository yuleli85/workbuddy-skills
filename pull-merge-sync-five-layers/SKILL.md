---
name: pull-merge-sync-five-layers
description: 从并行分支/队友拉取代码后，把「代码 → 构建 → 数据库 → 缓存 → 页面」五层重新对齐，并识别「merge 静默丢代码」。当用户说「拉取到最新的代码」「更新到最新并提交」「pull 完构建失败」「合并后 CI 报找不到符号 / MISSING_EXPORT」「拉取后页面报错 / 功能没出来」「重建并重启」「要不要跑数据库升级」「跑完升级菜单反而少了」「某目录下子功能合并后都不见了」时使用。覆盖：① merge/rebase 把同名文件整段覆盖导致的构建期硬失败（含 `git log -S` 查不到 merge 引入删除的坑）；② rebase 的三类坑（GIT_EDITOR 拉起导致静默 SIGTERM、被 gitignore 的软链被删、每轮都要重跑）；也覆盖「`git pull` 被挡（`error: Your local changes ... would be overwritten` / `untracked working tree files would be overwritten` / `Aborting`）」时的四步判据链（可快进 → 逐文件 numstat 归零 → 未跟踪 `cmp` 逐字节 → 行集合差判是否只是浓缩重述）与「mv 备份 + checkout 让路 + --ff-only」处置法；③ 拉取后必查的数据库迁移（备份→执行→复检 pending→清 Redis 权限缓存），以及「段位多 owner + 只跑变更集 ⇒ 菜单/授权静默消失」与「ID 段撞车误隐藏」两类的定位与修法（`tools/menu_sync_audit.py` 秒级定位到 文件:行号；含「先枚举全段 owner、别只补报障那几条」与「临时表 + CHECK 约束做失败即停哨兵」）；④ 用 Playwright 实渲染 + 失败请求/console 报错双扫收口；⑤ 被 gitignore 的未跟踪同名文件被 merge **静默覆盖**（本地 .env 真实配置凭空变短/变成占位符、状态却显示干净）的预防与「长度指纹」复原法，含从脱跟踪前提交 + 仓库记忆里的硬编码线索双路找回落库真值。当用户说「合并后本地 .env 内容变了」「本地配置被覆盖了」「配置文件变短了 / 变成 <set-me> 了」「合并完我的密钥不见了」时使用；也覆盖「构建报 `sh: cross-env: command not found`（`node_modules` 整族缺失的判定与补装）」，以及「`docker compose` 第一步就报 `mapping key "nginx" already defined`（本地未提交的 compose 改动里重复了服务名）的 10 秒判据与『改唯一名、别删块』修法」。也覆盖「拉取前发现某个目录整个消失了 / 目录被删了 / db_bak 没了 / 工作区出现一大片 D 加一个新未跟踪目录」这类『半截重构』的三问识别法与「保全 → 让路 → 新目录原样保留（禁提交）」处置法。
agent_created: true
---

# 并行分支拉取后的「五层对齐」

## 核心原则

**拉取不是「同步完就完了」。** 只要你的分支和队友分支长期并行，一次 pull 会同时动五层，
而**每一层都会静默失败**：git 层不报冲突（merge 自动解决）、构建层报错但被当作"环境问题"、
数据库层不跑也不报（老库不会自动收新脚本）、缓存层留着旧菜单权限、页面层只是某块空白。

**判据：五层全部验证过，才算拉取完成。** 任何一层没验证，都要在交付里明确写出来。

---

## 第 0 层 · 动手前（防并行会话抹掉你的提交）

```bash
git status --short
git rev-parse --abbrev-ref HEAD
git reflog -12 | cat                      # 并行会话会 reset，先留证据
git fetch origin && git rev-list --left-right --count origin/<branch>...HEAD
git log --oneline HEAD..origin/<branch>   # 远端到底多了什么
```

- 工作区有改动 → **先本地提交再 rebase**（脏树 rebase 会被拒，stash 容易丢）。
- 🔴 **`git merge-base HEAD origin/<b>` == HEAD ⇒ 必为 fast-forward，冲突在数学上不可能**
  （远端是本地超集）。这比 `--is-ancestor` + `rev-list --count` 更早给出结论，**先跑它**。
- 🔴 **但 fast-forward 一样要求「脏树让路」**：只要 ff 会改写的文件里有一个是你本地 `M` 的，
  `git merge` 直接拒绝（`Your local changes ... would be overwritten`）。安全套路（**不要**用
  `git checkout --` 丢弃、也不要用无路径的全量 `stash`）：
  ```bash
  # 0) 全量备份（含未跟踪），记 md5；备份目录别删
  cp <M 文件> <?? 文件> /tmp/wip-backup-$(date +%s)/
  # 1) 先算交集：dev 改的文件 ∩ 本地 M 的文件 —— 只有交集里的才需要让路
  comm -12 <(git diff --name-only HEAD origin/<b> | sort) <(git diff --name-only | sort)
  # 2) 按路径精确 stash（未跟踪文件不挡 ff ⇒ 不用 -u，也不用管它们）
  git stash push -m wip-<主题> -- <交集文件>
  git merge origin/<b>            # ff
  git stash pop                   # 交集内会 add/add 冲突
  # 3) 解冲突后把索引复位，让 WIP 回到「已改未暂存」原状（不替用户提交）
  git reset -q
  ```
  实测：两个冲突文件都是**纯新增块 add/add**（一方在文件尾加块 A、另一方加块 B）⇒ **取并集**、
  并给重复的编号标签重新编号；`bash -n` / 语法检查 + 自检脚本（如 `merge_integrity_check.py`
  的「新增 SQL 登记」项）复跑确认。`stash pop` 报冲突后 **stash 条目会保留**（是安全网，别急着 drop）。
  - 🔴 **「同一文件两侧各自在文件尾追加」这类冲突，有一条比 stash 更省的走法**（stash 栈里已有长期条目时尤其推荐，避免 `pop` 到别人的条目）：该文件在 ff 的 incoming diff 里 ⇒ `cp` 备份 → `git checkout HEAD -- <file>` 让路 → ff → 从备份里切出**本地新增段**（用 `git show HEAD:<file>` 与备份 `diff` 得到行区间，如 `sed -n '296,330p'`）`cat >>` 拼到新文件尾。两侧都是「在 base 同一位置之后各加小节」时结果天然是**并集**，不必再解冲突标记；收尾仍要复扫行首 `^<<<<<<<` / `^>>>>>>>` 并回读小节点名，确认远端与本地的节都在。
- 🔴 **在途 WIP 属别人/需用户决策时，脚本里的 `git add .` 一律不执行**：先用 `ps` 确认本工作区
  是否还有在跑的会话，再看 WIP 的 mtime 与是否有同批的说明文档；若同一份日报里已写明
  「改动未提交 ⇒ 待用户决定是否入库」，就**只按路径精确 add 自己的留档文件**。红线优先于脚本写法。
- 🔴 **在途改动先做「三分类」，再决定提交什么**（无人值守轮尤其重要）：
  1. **真源码** —— 逐文件 `git diff -- <f>` 读语义，**确认是特性而不是调试残留**；
  2. **记忆/日报** —— `--paths` 精确提交；
  3. **红线文件**（`.env*` 等）—— 只 `cp` 备份，**绝不提交**。推前门禁：
     `git diff --name-status origin/<b>..HEAD | grep -E '\.env'`；若命中的是**远端早已入库**的 env 文件，
     用 `git rev-parse HEAD:<f>` 与 `git rev-parse origin/<远程分支>:<f>` 比 blob —— **相同 ⇒ 非本地泄露**
     （可放行，但必须在报告里点名上报）；不同才停下来。
  ```bash
  # ① 三分类：源码 / 记忆 / 红线
  git diff --name-only | grep -vE '^\.workbuddy/|\.env'          # 真源码
  git diff --name-only | grep -E  '^\.workbuddy/'                # 记忆
  git diff --name-only | grep -E  '(^|/)\.env'                   # 红线（只备份）
  # ② 判调试残留：与远端/HEAD 比 blob，三端同改一行且是「加后缀」形态 ⇒ 试色/调试痕迹
  for f in $(git diff --name-only -- '*'); do
    echo "$f  worktree=$(git hash-object $f) HEAD=$(git rev-parse HEAD:$f)"; done
  ```
  🔴 **实测形态**：在途的 `pig-{ui,pc-ui,mob-ui}/…/RdPanel.vue` 三端同改 1 行
  `研发部概况 → 研发部概况2`（`chart-title` 同步加 `2`），而远端/HEAD 三端均为旧值
  ⇒ 典型**试色/调试残留**。正解 = `cp` 备份 → `git checkout --` 还原 → **不提交**；
  提交会把痕迹（页面标题「研发部概况2」）**永久化**。判据：痕迹是「无语义的机械后缀/占位词」
  且**远端与 HEAD 一致为旧值** ⇒ 残留；反之与远端有实质语义差异（新字段/新分支/新文案）
  ⇒ 真特性，照常提交。
- 🔴 `git commit` **提交所有已暂存的改动** ⇒ 想拆成多个提交时，必须「`git add <精确路径>` 后
  **立刻** commit」，否则早先 `git rm --cached` 之类的已暂存项会被顺手带进前一个提交
  （补救：`git commit --amend` 补 message）。另：被 gitignore 的**已跟踪**文件要重新暂存
  须 `git add -f`，普通 `git add` 会直接报错并中断 `&&` 链。
- `ahead/behind` 显示远端只多 merge 提交、`git diff HEAD...origin/<branch>` 为空 ⇒ 远端只是把
  你的提交又合了一遍，**直接 rebase 你的本地提交即可**，不用怕。（但**仍要跑第 1 层的校验**：
  「远端只多 merge 提交」恰恰是最容易出现「整段覆盖」的形态。）
- 🔴 **「更新到最新并提交」前先穷尽核查，别只看 `git status`**。至少四查：
  `git status --porcelain -uall`（含未跟踪）、`git diff --cached`（暂存区）、
  `git log --branches --not --remotes`（**任何**本地分支的未推送提交）、
  `git rev-list --left-right --count origin/<b>...HEAD`。
  全空 ⇒ 本轮 git 层就是**空操作**，如实告知用户，**别为了「有产出」硬造提交**。
- 🔴 **stash 是否已过期：用「双向补丁」判定**
  ```bash
  git stash show -p stash@{0} | git apply --check      # 正向：能上 ⇒ 内容还没进代码
  git stash show -p stash@{0} | git apply -R --check   # 反向：能上 ⇒ 内容已在代码里
  ```
  **双向都失败** = 它依赖的基础版本已被后续提交改写 ⇒ 已过期、无价值（典型：拉取前暂存的
  「页面精简」补丁，几天后这些精简早已落库，补丁再也打不上）。
  清理前**先留档**：`git stash show -p stash@{0} > <dir>/xxx.patch`，并记下
  `git rev-parse stash@{0}`；`git stash drop` 后该对象在 GC 前仍可 `git stash apply <hash>` 找回。
- 🔴🔴 **最危险的一类在途：`D` 是「整目录未跟踪删除」+ 同批冒出「新未跟踪目录」= 有人做了半截重构。**
  实测形态：`git status --porcelain` = **211 个 ` D pig/db_bak/**` + 1 个 `?? pig/merged_db/`**，
  被删目录在磁盘上已整目录消失，mtime 仅比本轮触发早 13 分钟。**先做三问，再决定「让路」还是「原地不动」**：
  ```bash
  # ① 远端有这个目录吗？（远端没有 ⇒ 是本地未提交的尝试，不是拉取带入的）
  git ls-tree --name-only origin/<b> pig/ ; git ls-tree --name-only origin/<b> pig/<新目录>/ 2>&1 | head -3
  # ② 新目录内容 == 被删目录的某个子目录？（逐字节相同 ⇒ 本质是「目录移动 + 删父目录其余」）
  #    逐个关键文件比头部/大小/mtime，或 diff <(git show HEAD:<被删目录>/<子>/README.md) <新目录>/README.md
  # ③ 引用被删目录的工具，路径改了吗？（没改 ⇒ 重构必然未完成）
  grep -rn '<被删目录名>' tools/ db/ --include='*.py' --include='*.sh' | head
  ```
  🔴 **决定性判据 = 把「引用该目录的工具」真跑一次**（如 `python3 tools/consolidate_db.py`）：
  本轮它直接 `FileNotFoundError: pig/db_bak/initdb-loader.sh` ⇒ **该删除已打断生成链** ⇒
  **绝不可提交**（提交=把坏状态推上远端，所有克隆都失效），也**别急着 `checkout --` 丢弃**。
  正解「**保全 → 让路 → 原样保留**」五步：
  ```bash
  git diff -- <被删目录> > $HOME/bak/<主题>-delete-<n>.patch   # ① 删除存补丁（9.4MB 也要存）
  tar czf $HOME/bak/<新目录>-snapshot.tgz <新目录>              # ② 新产物快照（双保险）
  git checkout -- <被删目录>                                   # ③ 恢复让路（ff 才过得了）
  git merge --ff-only origin/<b>                               # ④ 快进
  # ⑤ 新目录**保持未跟踪、原样留**（不属于本轮：别 add、别删、别提交）
  ```
  收尾：复跑那个工具确认链路复活（如 `ORDER 192 == 192`），并在报告/日报里**点名待用户决策**
  「此重构是否继续 + 成组完成清单（改工具路径 → 移动目录 → 删老目录 → 重跑生成 → 修 README → 一次提交）」。
  ⚠️ 反面做法（本轮明确排除）：把它当「本地变更」提交 —— 只会得到「新老目录内容重复 + 生成链断裂」的半成品。

- 🔴 **「ff/pull 被 `local changes` 拒绝」≠ 那些文件真有价值 —— 先跑三方比对，再决定丢弃。**
  报错形态（2026-10-15 works 侧实测）：
  ```
  error: Your local changes to the following files would be overwritten by merge:
      .workbuddy/memory/2026-10-15.md   （列 8 个文件）
  Please commit your changes or stash them before you merge.  Aborting
  ```
  ⚠️ 第一反应既别是 `stash`（红线：勿 pop/stash），也别无脑 `commit`。
  **判据 = 三方 diff 的「本地独有行」计数**（本地磁盘 vs `origin/<b>` 版）：
  ```bash
  for f in <报错列出的每个文件>; do
    git show origin/<b>:"$f" > $HOME/bak/remote.tmp
    dl=$(diff "$f" $HOME/bak/remote.tmp | grep -c '^<')   # 本地独有行
    dr=$(diff "$f" $HOME/bak/remote.tmp | grep -c '^>')   # 远端独有行
    echo "$f  本地独有 $dl / 远端独有 $dr"
    [ "$dl" -gt 0 ] && diff "$f" $HOME/bak/remote.tmp | grep '^<' | head -12
  done
  ```
  - **`dl=0` ⇒ 本地版是远端的子集/旧版 ⇒ 直接 `git checkout -- <f>` 让路，零信息损失。**
  - **`dl>0` ⇒ 逐 hunk 看**：本轮唯一命中者（automation memory，`dl=3`）核对后发现
    「本地独有内容在远端**同文存在、只是位置不同**」（远端把同一段搬了家）⇒ **仍属零损失**。
    快捷验证：把本地独有行拿去远端版 `grep -F`，命中即非真独有。
  - 报告口径：**「7/8 文件零本地独有行；第 8 个的『独有行』在远端同文存在」** —— 比「已丢弃本地改动」可信得多，
    也是事后追责的唯一凭据。
  - 🔴 顺带收获：同一命令可查「**远端动过哪些不该动的文件**」——
    `git diff --stat <旧HEAD> origin/<b> -- deploy/.env.deploy pig/db_bak` 本轮证明远端**没碰** `.env.deploy`、
    却**改了 `pig/db_bak` 21 个文件** ⇒ 那 211 个本地删除**不阻塞 ff**，但**必须复位**（否则 ff 完仍是断链态）。
  - 备份纪律：`git diff > $HOME/bak/uncommitted-all.patch` + `tar czf $HOME/bak/<目录>-full.tgz <目录>`
    （含未跟踪的备份子目录）；⚠️ 含 `.env*` 的 patch **只能落 `$HOME`，永不出站**。

- 🔴 **同一台机器上的两个 checkout 会被同一操作各自波及**：本轮 works 侧与 work 侧
  **同日各出现一次「211 个 `D pig/db_bak/**` + 一个 `?? pig/merged_db/`”** ⇒ 处置一套
  （保全 → 让路 → ff → **复跑生成链确认复活**），但**必须分别执行**（各自 HEAD/工作区独立）。
  收工验证：`md5 -q <侧A>/<file> <侧B>/<file>` 判两侧副本是否归一（本轮两侧日报首次达成 md5 一致，
  消掉了长期存在的「两侧副本行数不一致」遗留问题）。

## 第 1 层 · 代码：merge 会「静默整段覆盖同名文件」

**这是并行分支协作最贵的一类事故**，因为 git 不报冲突、测试不一定覆盖、只在**构建期**炸。
已见的两种形态：

| 形态 | 症状 |
|---|---|
| 后端 `@ConfigurationProperties` 类丢字段 | CI 报「找不到符号 `getXxx()`」，使用方与配置都在库 |
| 前端 `api/xxx.ts` 丢导出 | `vite build` 报 `[MISSING_EXPORT] "opsHomeBrief" is not exported by ...` |

### 动手前先「预判冲突」，别 merge 完再回滚

```bash
git merge-tree --write-tree origin/<branch> HEAD
```

**判读只有两种**（需 git ≥ 2.38）：
- 输出**仅一行 tree OID** ⇒ **无冲突**，可安心 merge；
- 出现若干 `100644 <blob> <stage> <path>` 行 + `CONFLICT (content): Merge conflict in <path>`
  ⇒ 冲突文件被一次性列全，再决定怎么合。

🔴 **它的退出码恒为 0，不能拿 RC 判「有没有冲突」**（2026-10-17 实测复现），只认 stdout 文本；
首行那串 40 位十六进制是**结果树 OID**，不是文件名清单，别误读。想直接拿冲突文件名列表就加
`--name-only`：`git merge-tree --write-tree --name-only origin/<branch> HEAD` ⇒ 冲突文件各占一行，
末尾仍会追加 `Auto-merging <path>` / `CONFLICT (...)` 提示行。

比「先 merge、坏了再 `--abort`」安全，也让你**提前看清哪几个文件是双方都碰过的**。

### 🔴🔴 「本次 merge 的真实改动面」必须用 merge-base 算，别用 `HEAD..branch`

**`git diff --name-status HEAD origin/<branch>` 在长期分叉的分支上是「假象放大器」**：它会把你
自己领先的 N 个提交**反向**呈现成海量 `D`（删除）/`M`。实测（2026-10-15，linmo-pig-full）：
队友 `ashu` 只领先 `dev` **1 个提交**，但 `diff HEAD origin/ashu` 输出了**上百行 `D`**
（`.workbuddy/memory/*`、`deploy/.env.*`、`docs/*` 全被列成「删除」）——看着像要删库，
实际那条命令只是把 dev 领先的 **113 个提交**倒着读了一遍。

```bash
MB=$(git merge-base origin/<branch> HEAD)
git diff --name-status $MB origin/<branch>          # ✅ 这才是本次 merge 真正带入的面
git diff --name-status --diff-filter=D $MB origin/<branch>   # ✅ 真正会被删的文件（常为空）
```

**判据**：先 `git rev-list --left-right --count origin/<b>...HEAD` 看两侧规模。
左值（dev 领先）一旦是两位数，`HEAD..branch` 的 diff 就**必须**改用 `MB..branch` 重算。
另：`HEAD^1` 也**不能**用于「合并前对照」（在合并提交上 `HEAD^1` 指的是合并提交本身）——
动手前先记下 pre-merge sha。

### 🔴 「目录改名」冲突：`CONFLICT (file location)` 往往只需 `git add`

当**本侧把某目录改名**（如 `pig/db/manual/` → `pig/db_bak/manual/`）、而队友在**旧路径下新增文件**时，
git 报：

```
CONFLICT (file location): pig/db/manual/xxx.sql added in origin/<b> inside a directory
  that was renamed in HEAD, suggesting it should perhaps be moved to pig/db_bak/manual/xxx.sql
```

⚠️ **别急着 `git checkout --theirs` 或手工 `mv`**。先量形态：

```bash
git ls-files -u -- <冲突路径>      # 看有几级 stage
```

实测（2026-10-15，6 个 SQL 文件）：**只有 stage 3（theirs），没有 stage 1/2**，
且**工作区文件已落在新路径、内容就是队友版、无冲突标记**（`grep -c '^<<<<<<<'` = 0）
⇒ 这是 git 已经替你搬好了，**直接 `git add <路径>` 收编即可**，不需要任何手工搬运。
真正需要人工的只有**内容冲突**（如 `README.md` 被双方各改一段 ⇒ 取并集）。

### 🔴 冲突标记扫描一律 `grep -E`

本机 PATH 上的 `grep` 是 shim，**不支持 BRE 的 `\|` 交替**（静默 0 匹配）。用
`grep -nE '^(<<<<<<<|=======$|>>>>>>>)'`；`grep -c 'a\|b'` 会给你**假的 0**，
进而误判「内容丢了 / 没冲突」。本轮因此在「冲突标记扫描」与「主题文件承接核查」上**连踩两次**。

🔴 **预演有效的前提是「预演到 merge 之间 HEAD 没被动过」**：并行会话活跃时，预演报「零冲突」而真 merge 出冲突
是常见的（2026-10-07 实测：预演时 HEAD=`acd1ea02` 零冲突，真合并时 HEAD 已被推到 `47b11da2`，实出 3 处冲突）。
⇒ **merge 指令发出前紧挨着再跑一次** `git reflog -3` / `git rev-parse HEAD`，与预演时不一致就重跑预演。

🔴 **判「远端分支是否已并入」必须先 `git fetch origin`**，否则陈旧引用会给出**相反结论**
（实测：本地 `origin/dev` 停在 `1c01f805` 判「已并入」，fetch 后实际 `4304f8fb` 判「未并入且差 105 提交」）。
判据：`git merge-base --is-ancestor origin/<b> HEAD`（A=远端、B=HEAD，**方向别写反**）+ `git rev-list --count HEAD..origin/<b>`。

🔴 **`HEAD^1` 在「已提交的合并」上 = 合并提交本身**，拿它做「合并前对照」会得出「合并无改动」的假象。
做「合并带来了什么」的对照，用**动手前记下的 pre-merge sha**：`git diff <pre-merge-sha> HEAD -- <file>`。

### 🔴 合并后必跑：「双边归属矩阵」——一眼判定是否真有覆盖风险

`merge-tree` / merge 的输出只告诉你「冲不冲突」，**不告诉你「谁改的」**。而「静默覆盖」
恰恰只在**双方都改过同一文件**时才可能发生。所以合并后对每个改动文件跑：

```bash
MB=$(git merge-base <本地旧sha> origin/<branch>)
for f in $(git diff --cached --name-only); do
  lc=$(git diff --quiet $MB <本地旧sha> -- "$f" && echo no || echo YES)      # 本地改了吗
  dc=$(git diff --quiet $MB origin/<branch> -- "$f" && echo no || echo YES)  # 远端改了吗
  printf "%-70s local=%-4s remote=%s\n" "$f" "$lc" "$dc"
done
```

**判读**：
- `local=no / remote=YES` ⇒ 合并即**纯取远端版**，本地无可丢内容 ⇒ **零覆盖风险**，不必逐个 grep；
- `local=YES / remote=no` ⇒ 同理反向；
- `local=YES / remote=YES` ⇒ **只有这几个文件需要重点校验**，也正好解释冲突为何出在它身上。

实测一次 27 文件的 dev 合并：**26 个是 `local=no`**，唯一双边 YES 的就是日志文件 ⇒ 30 秒得出
「本次不可能丢码」，再对这 1 个文件做联合合并 + 回读校验即可收口。
**旁证判据**：`git rev-parse $MB:<可疑文件>` 若等于「本地旧版 blob」，即证明本地从未改过它
（实测 `connector/index.vue` 在 merge-base 的 blob 恰为本地旧版 `0a6072b`，与队友日志记载吻合）。

### 🔴🔴 `git pull` 被拒（`local changes would be overwritten` / `untracked would be overwritten`）——先判「是否已是同一批内容」，再让路

只有当本地提交落点靠前（`merge-base --is-ancestor HEAD origin/<b>` 为真，即**只落后**）才会撞这个；
但报错里的「本地改动」**经常就是远端已经推上去的那份内容的另一个副本**（多 checkout 机器尤其常见）。
**不要**直接 `stash`/`reset --hard`/`cherry-pick` 上来 —— 先跑四步判据链：

```bash
git merge-base --is-ancestor HEAD origin/dev && echo "可纯快进"
# ① 已跟踪改动：逐文件算与目标的差异行数，归零即「同内容」
for f in $(git diff --name-only); do echo "$(git diff --numstat origin/dev -- "$f") <- $f"; done
# ② 未跟踪挡路文件：与目标同路径逐字节比
cmp -s "$p" <(git show "origin/dev:$p")
# ③ 剩下的真差异文件：做「行集合差」，判是否只是浓缩重述
git diff origin/dev -- "$f" | grep '^+' | grep -v '^+++' | sed 's/^+//' | LC_ALL=C sort -u > /tmp/loc
git show "origin/dev:$f" | LC_ALL=C sort -u > /tmp/org
LC_ALL=C comm -23 /tmp/loc /tmp/org | wc -l        # 0 ⇒ 零信息丢失，可放心让路
```

- **① ② 全命中 + ③ 独有行 0** ⇒ 让路 + `git merge --ff-only origin/<b>` 即可，比 `stash`/`merge` 都快且零损失。
  实测一次：11 个已跟踪「改动」里 9 个逐字节相同、44 个未跟踪 `backup/**` 全同、剩 2 个日报只是**精简版留档**，
  14 行「独有行」全是远端完整版事实的浓缩重述 ⇒ 纯快进 +15，零丢失。
- **让路一律用 `mv` 到备份，不用 `rm`**：`mv backup/func_db $HOME/.linmo-bak/rN/untracked/`，
  已跟踪改动先 `cp` 一份再 `git checkout -- <paths>`（未跟踪文件不能进 `git commit -- <paths>`）。
- **③ 若判出真独有事实** ⇒ **必须先回填再快进**（把本地独有块按时间序插进远端版），别让路。
- ⚠️ **报错只列「会被覆盖」的文件，不代表本地干净**：同一轮可能还有并行会话刚推的新提交在等你并进来。
  实测一次：提交记忆时队友恰好推了 49 文件（新 SQL + 后端测试 + 前端页面）⇒ 脚本自动 `fetch` + `merge`
  ⇒ **merge 落在构建之后，必须复跑编译**（对齐第 2 层），别拿「刚才已经全绿」交付。

### 🔴 push 被拒（`! [rejected] ... fetch first`）是并行会话的常态，不是异常

含义：你 merge/commit 期间**队友又推了**。定式（**绝不 `--force` / `--force-with-lease`**）：

```bash
git fetch origin && git log --oneline HEAD..origin/<b> && git diff --stat HEAD...origin/<b>
git merge origin/<b> --no-edit     # 若远端也碰了同一文件 ⇒ 回上面的「归属矩阵」+ 联合合并
git push origin <b>
```

可能**要跑多轮**（实测第一轮被拒、第二轮才成）。每轮都按第 1 层校验重跑一遍，
别拿「上一轮已经验过」当理由跳过 —— 新一轮 merge 可能又带进新的双边改动。

### 🔴🔴 最反直觉的一条：「变基/合并成功」≠「合并正确」

**当你的本地提交恰好没碰那个被改坏的文件时，rebase 会「无冲突通过」** —— 远端带进来的
删除/新增被**原样保留**，冲突根本不会浮现。此时 `Successfully rebased` 是**真话，但不安全**：
你 push 出去的就是那个坏状态。实测过一次「3 个本地提交 × 2 个坏文件 → 零冲突」，
若不显式校验，等于把两处坏状态直接推上去。

⇒ **合并/变基后必须显式校验语义完整性，不能以「无冲突」为依据。** 最小校验集（约 30 秒）：

```bash
git show HEAD:path/to/api.ts | grep -cE "export function (A|B|C)"   # 期望 3，不是 0
git ls-files <本应脱跟踪的文件>       # 期望空（非空 = 又被 merge 带回版本库）
ls -la <本应是指向 ../x 的软链>        # 期望 '->'，而不是普通文件
```
再补一次真实构建（`build <前端服务>`）作为终局判据 —— 静态 grep 只能证明「没丢」，
构建才能证明「能用」。

**同一处修复被反复抹掉时，要「一次修全 + 上锁」。** 实测同一文件同一批导出**连续两天被抹**
（队友基于旧版只补回其中 1 个，merge 时又用他的版本覆盖了你的版本 ⇒ 另 3 个又丢）。所以：
① 修复时按上面的「集合级比对（`comm -23`）」**把所有被删导出一次补齐**，别只补构建报错里那一个；
② 把「这些导出/字段勿删」写进该模块的 `AGENTS.md`，让下一次的队友看得见。

### 🔴🔴 merge 不只「静默丢代码」，还会「静默多代码」—— 合并产物级重复声明

自动合并（`ort`）在双方**各自新增了相邻行**时，会把两份都留下 ⇒ 同一个作用域里出现两条一样的声明，
**git 不报冲突**，但 esbuild/vite 直接 `PARSE_ERROR: Duplicate ...`，TS 报
`Cannot redeclare block-scoped variable`。实测（2026-10-07，`views/ops/industry/index.vue` 双端各一）：
`HEAD` 1 条 + 队友 1 条 → 合并后 **2 条** `const router = useRouter();`。

⇒ 合并后必扫「**新增**顶层重复声明」（只报「HEAD 没有、合并后有」的，老重复可能是既有代码）：

```bash
# 只扫 <script setup> 段，统计每个顶层声明的出现次数
python3 - <<'PY'
import re,subprocess,os
pat=re.compile(r'^(?:const|let|var|function|async function)\s+([A-Za-z_$][\w$]*)')
def dups(txt):
    body=(re.search(r'<script[^>]*setup[^>]*>(.*?)</script>',txt,re.S) or [None,txt])[1]
    d={}
    for l in body.splitlines():
        m=pat.match(l)
        if m: d[m.group(1)]=d.get(m.group(1),0)+1
    return {k:v for k,v in d.items() if v>1}
for f in subprocess.run(['git','diff','--name-only','HEAD'],capture_output=True,text=True).stdout.split():
    if f.endswith(('.vue','.ts')) and os.path.exists(f):
        now=dups(open(f,encoding='utf-8').read())
        old=dups(subprocess.run(['git','show',f'HEAD:{f}'],capture_output=True,text=True).stdout)
        if {k:v for k,v in now.items() if k not in old}: print(f, now)   # 新增重复 = 合并产物
PY
```

同时扫**同一 import 标识符被导两次**（`import {A} from` 出现两行）—— 同因，同修法。

### 🔴 双方都改了「同一个后端方法的路径」时，按**合并态**的实际映射定前端 URL

两条线各自给同一方法改名，auto-merge 会把两边路径都留着（不同路径 → 不撞车、不报 Ambiguous mapping），
**但前端该打哪个路径不能按任一侧推**。实测形态（行业概览四路径，2026-10-07）：

| | 我方 | 队友 | **合并态** |
|---|---|---|---|
| days 口径（Agent 控制器） | `/industry/panel` | `/industry/overview` | `/industry/panel`（取我方） |
| period 口径（Intel 控制器） | `/overview` | `/intel/overview` | `/intel/overview`（取队友） |

判法（**合并在途/合并后直接看工作区**）：

```bash
grep -nE '@(Get|Post)Mapping' pig/pig-ops/src/main/java/**/controller/Ops*Controller.java
```

然后让前端 `api/*.ts` 的 URL 与之一一对应；**取错一侧 ⇒ 要么 404，要么留下一侧永不调用的死函数**
（后者更隐蔽，构建全绿、只有运行时才 404）。判据：**每个被引用的接口函数，其 URL 必须在合并态控制器里存在**。

再提醒一条同类经验：**合并带进来的「自检脚本」本身也可能是错的** —— 用
`git merge-base HEAD MERGE_HEAD` 的**第一条**算「本次新增文件」的自检，在多 merge-base 仓库里会把
`base→HEAD` 的**历史文件**全报成「本次新增」（实测 10 个 SQL 全假报 FAIL）。**先核对它的判据是否成立，
再采信它的结论**；正解是按「`git diff --diff-filter=A HEAD origin/<b> -- <dir>`」自己算一遍。

### 🔴 关键坑：`git log -S` **查不到** merge 引入的删除

`git log -S <符号> -- <file>` 默认不遍历 merge 提交，而这类删除恰恰是「合并冲突解决时选了对方版本」
造成的 ⇒ **`-S` 返回空，你会以为这符号从来不存在**。正确查法：

```bash
# ① 直接比对「拉取前 vs 拉取后」的该文件（最可靠）
git diff <old-sha>..<new-sha> -- path/to/api.ts

# ② 需要看是哪个 merge 干的
git log --full-history -S "<符号>" -- path/to/api.ts

# ③ 集合级比对：被删掉的导出一次列全（推荐，避免漏掉第 2、第 3 个）
git show <old-sha>:path/to/api.ts | grep -oE "^export function \w+" | sed 's/export function //' | sort > /tmp/old.txt
grep -oE "^export function \w+" path/to/api.ts | sed 's/export function //' | sort > /tmp/new.txt
comm -23 /tmp/old.txt /tmp/new.txt     # 只存在于旧版 = 被抹掉的
```

### 修法原则

**看消费方还在不在，再看供给方（后端端点 / 服务端实现）是否仍存在**：
- 消费方在 + 供给方在 ⇒ **按原样补回**（最优，最小改动，不引入行为变化）。
- 消费方在 + 供给方已删 ⇒ 修消费方（删引用或改调新接口）。
- 消费方已删 ⇒ 不用管。

> 注意 `git log -S` 的另一个陷阱：**它也不区分"改名"和"删除"**。配合 `git show <old>:<file>` 看原文再决定。

### 🔴🔴 拉取时「逐提交核对」—— 净变化为 0 的隐蔽回滚

**同一个人的连续两次提交之间，也会发生「静默整段覆盖」。** 不限于跨分支 merge。

实证：队友 14:25 提交 `A`（给某组件加了一段过滤/修复），14:38 提交 `B`（提交信息只写
「另一个无关页面的 CSS」）却把 `A` 的那段改了回去 —— **因为他的工作区里残留着 `A` 之前的
旧版文件**。结果：`git diff <拉取前> <拉取后> -- 该文件` **净变化为 0**，在 fast-forward 的
diff 里**完全看不见**；`git log -S` 也查不到（一加一减，该符号从未"新增"也未"删除"）。

**这是最隐蔽的一类：拉取成功、无冲突、diff 干净、构建也能过，但修复没了。**

**定式（拉取后 30 秒，逐提交看，不是只看合并后的总 diff）**：

```bash
# ① 逐个提交列出它动了哪些文件
git log --stat --format='%h %ad %an %s' --date=format:'%m-%d %H:%M' HEAD..origin/<branch>

# ② 对「提交信息与改动文件不匹配」的可疑提交，直接展开
git show <可疑sha> --stat     # 列出的文件与提交信息描述的功能相符吗？
git show <可疑sha>            # 展开看具体改了什么

# ③ 判据：某文件净变化为 0，但期间有提交动过它 ⇒ 一加一减，查回滚
git diff <old-sha>..<new-sha> -- <可疑文件>    # 空输出 = 净变化 0
```

**读法**：`git log --stat` 里某个提交的**文件列表与提交信息描述的功能不匹配**（例如写着
「改 CSS」，却列出某个 Vue 组件 + 某个文档），就是高危信号；若那几行正好**一加一减**，
即为回滚。修复按上面的「修法原则」按原样补回，并用
`diff <(git show <原修复sha>:<file>) <file>` 断言**字节一致**。

> **为什么 fast-forward 也危险**：直觉认为「本地 0 提交 = 纯快进 = 零风险」，这**只对
> "覆盖你本地改动"成立**；远端历史自身可能已经把某个修复回滚掉了，快进会把这个坏状态
> 原样搬进你的工作区。所以「本地 0 提交」只能免掉第 1 层的「双边归属矩阵」，
> **不能免掉逐提交核对**。

### 🔴🔴 merge 会覆盖「被 gitignore 的未跟踪同名文件」—— 本地真实配置被静默抹掉

**比丢代码更严重**：丢的是**从不入库、无处可复原**的本地真值（含密钥的 `.env`），
而 git **既不报错也不提示**，`git status` 全程干净。

**机制**：`git merge` 对未跟踪文件的保护**只覆盖「未被忽略」的那类**（报
`untracked working tree files would be overwritten by merge` 并拒绝）。
**一旦该文件被 `.gitignore` 匹配，这层保护直接失效** ⇒ 远端同名文件直接落盘、覆盖本地。
所以「文件在 `.gitignore` 里」≠「merge 时安全」，恰恰相反：**被忽略才是危险的那一类**。

实证（2026-10-05，linmo-pig-full）：`deploy/.env.dev`（未跟踪 + `.gitignore:16` 忽略，
含 9 个真实密钥、17558B）在 push 被拒后的自动 merge 里，被远端同名占位版（13714B）
**静默覆盖**；`git status` 无任何异常，只有比对文件大小才发现（17558 → 13714）。

**同族第二形态：「上游把已跟踪文件退出索引 + 写进 `.gitignore`」⇒ 快进会静默删除工作区副本**
（2026-10-14 实证，linmo-pig-full）。不同于上面的「覆盖」，这里是「**删除**」：
上文机制只描述「未跟踪 + 被忽略」的文件被覆盖；而当上游提交形如
`A .gitignore(+3) / D deploy/.env.dev / D deploy/.env.deploy / D deploy/.env.aqiang`
（即 `git rm --cached` 之后又加了忽略规则）时，**本地这三个文件仍是「已跟踪且干净」**，
所以 fast-forward 会当作正常的文件删除，直接把工作区副本 `unlink` ——
`git status` 同样全程干净，只有 `[ -f ]` 能发现（21148B → `MISSING`）。
**判据（比上面更早，自查成本最低）**：合并/快进**前**看 incoming 的 name-status，
凡出现 `D <你的本地 env 路径>` ⇒ 先 `cp` 备份、快进后**原样 `cp` 还原**；
还原后应满足 `git check-ignore <f>` 命中 + `git ls-files --error-unmatch <f>` 报 NO
（即「未跟踪 + 已忽略」，与上游意图一致，也不会再被 `git add .` 带走）。

> ⚠️ **2026-10-14 更新（`.env.dev` 角色反转）**：`deploy/.env.dev` 已由用户授权**入库为共享配置**
> （本机开发栈 `docker compose --env-file deploy/.env.dev` 实际加载、Jenkins 也读取）；
> `.githooks/pre-commit`、`.gitignore`、`.git-fast.conf` 同批改为「放行」。
> ⇒ 下文「远端带着 `deploy/.env.dev` ⇒ 危险」**只适用于个人未追踪件**
> （`deploy/.env`、`deploy/.env.head`、`deploy/.env.mac`、`python-ai-service/.env`）：
> 对 `.env.dev`，远端有它是**预期态**，不要按「危险」处置。判据以 `docs/deploy-env-review-convention.md` 为准。

**预防（三道，越靠前越重要）**：
1. 🔴 **根因是「含密 env 进了版本库」**——`.gitignore` 只是补丁。别提交含密 env。
2. 把「必须保持未跟踪」的路径写进仓库的 `.git-fast.conf`（`git-quick-commit` 会逐条复检），
   ⚠️ 但它**只是体检告警，拦不住 merge 覆盖**。
3. **合并前先预判 + 备份**：确认远端是否带着这个文件，是就先把自己的备份出来。
   ```bash
   git ls-tree origin/<branch> -- deploy/.env      # 非空 ⇒ 远端带了这个文件；.env.dev 属预期态，其余个人 env 才危险
   for f in $(grep -v '^#' .git-fast.conf); do cp -a "$f" "$f.bak-$(date +%m%d%H%M)" 2>/dev/null; done
   ```

**恢复定式（已被覆盖时，按序做）**：
```bash
# ① 先另存「被覆盖后」的现场，别急着重写（它可能本身就是要保留的占位版）
cp deploy/.env.dev /tmp/envdev_overwritten.txt && wc -c /tmp/envdev_overwritten.txt
# ② 取该文件「被脱跟踪那一次提交」的父提交 —— 通常就是最后一版真值
git log --oneline --all -- deploy/.env.dev          # 找到 "fix(security): 清理…" 那条
git show <清理提交>^:deploy/.env.dev > /tmp/envdev_hist.txt && wc -c /tmp/envdev_hist.txt
# ③ 长度指纹比对：逐个敏感键比「丢失版长度 vs 历史版长度」
#    历史版常已有 8 成以上真值；用「长度 + 前 6 位前缀」确认是同一个值，比肉眼可靠
# ④ 历史里仍缺的个别键，去「把硬编码改成环境变量」的那次提交**之前**找：
git grep -n "<口令特征串>" <那次提交>^ -- tools/ *.bat *.sh
```
实测：8/9 个密钥在历史里完整复原（长度逐一吻合，如 `INTERNAL_AI_TOKEN` 25、
`MAIL_ENCRYPTION_KEY` 44、`DIFY_APP_KEYS` 51 全对得上），剩余 1 个（`ADMIN_MYSQL_PASSWORD`）
由仓库 `.workbuddy/memory/` 里记载的硬编码线索（`unlock()` 的 `password="yuleXXX"`，
长度 7、前缀 `yule12` 恰好吻合）补回 —— **9/9 全部复原、键数 52 与原文件一致**。

**判据（缺一不可）**：
- 出一张**长度指纹表**（`变量 → 期望长度 → 实际长度 → ✅`），全绿才算复原；
- 确认无 `<set-me>` / 空值之类**占位符残留**；
- `git ls-files --error-unmatch <file>` 复检文件仍未跟踪。

**收尾**：`git rm --cached <file>` 脱跟踪（本地文件保留）→ `git check-ignore -v <file>` 复检忽略生效
→ **体检远端那份历史值**（`git show <sha>:<file>` 逐个敏感键看是占位符还是真值）
⇒ 全占位则**不需要轮换密钥**，含真值则必须轮换并把结论写进交付。

## 第 2 层 · 构建：区分「真错误」与「环境/接口问题」

### 🔴 前端 `sh: <bin>: command not found` = **依赖没装**，不是代码坏了

`npm run build` 报 `sh: cross-env: command not found`（或 `vite` / `vue-tsc` / `rimraf`）时，
**先查依赖目录，别去改代码**：这几乎总是 `node_modules` 缺失/残缺，而不是合并把代码改坏了。

```bash
ls -d <web>/node_modules/.bin/<bin>   # 报错里那个可执行文件在不在
```

**为什么会缺**：`node_modules` 被 gitignore ⇒ 任何一次环境重置 / 全链路重建 / 换 checkout
都会让它整族消失，而源码、lock、构建脚本一点没变。

**补装姿势（本仓 linmo-pig-full）**：

| 端 | 有 `package-lock.json`？ | 命令 |
| --- | --- | --- |
| `pig-ui` / `pig-mob-ui` | 有 | `npm ci --no-audit --no-fund` |
| `pig-pc-ui` | **无**（且 `package.json` 里 `name` 实为 `pig-mob-ui`） | `npm install --no-audit --no-fund` |

- registry 已由各端 `.npmrc` 固定为 `registry.npmmirror.com`（lockfile 的 `resolved` 也指向该镜像，
  否则 npm 12+ 的 `allow-remote=none` 会报 `EALLOWREMOTE`）⇒ **不要**临时改 registry。
- node 用受管版本（`/Users/shan/.workbuddy/binaries/node/versions/*/bin`），装上约 10~25s、461 包，之后
  `✓ built` 即可。
- 同类「假编译失败」还有：Python 侧缺三方依赖报 `No module named '<三方包>'`（补依赖）；
  只有 `No module named 'app.<本仓包>'` 才是真缺陷。

### 🔴🔴 编译全绿 ≠ 服务能起：查「调用方 import 了一个从未入库的包」

**只在 Python（或任何动态语言）侧发生，是本类合并最高频的漏网形态。** 队友分支提交了
**调用方**（顶层 `from app.<新包> import ...`）却没提交**被调包** ⇒ 静态检查（`compileall`、
`mvn`、三端 `vite build`、甚至「跨模块导入」自检）**全都通过**，只有真 import 才炸。

真实案例（2026-10-07）：`app/services/ops_collect.py` 顶层 `from app.industry import registry`，
而 `app/industry/` 在 **16 个 ref、磁盘、运行容器中全都不存在** ⇒ `app/main.py` 顶层 import 它
⇒ python-ai **启动即 `ModuleNotFoundError`**，Java + 三端构建却全绿。

```bash
# ① 收尾必跑：真 import（缺包立刻暴露）
cd python-ai-service && python -c "import app.main"
# ② 对「被 import 的本仓包」逐个核存在于哪些 ref
git ls-tree -r --name-only origin/dev | grep -E 'app/<pkg>/'
# ③ 让测试替你把关：顶层 import 坏时，pytest 收集阶段就会 ERROR
python -m pytest -q
```

- 🔴 **`tools/merge_integrity_check.py` 的「Python 跨模块导入」项查不出**「引用了一个从未入库的包」——它只比对两侧都存在的模块。
- **处置原则：不改队友的调用方文件，改新建被调包的「最小占位」** —— 让调用方与远端分支**逐字节一致**，
  避免下一轮合并再冲突；占位需满足：`handles()`/判定函数恒返回「不接管」⇒ 行为**回落到合并前那条路径**，
  并留一个 `register()` 之类的扩展点供队友补真实现。
- 别把「缺的是可选三方依赖（`playwright`/`bcrypt`/`openpyxl`）」误判成合并搞坏了代码 ——
  报错是 `No module named '<第三方包>'` 时先补依赖再复跑；报错是 `No module named 'app.<本仓包>'` 才是真缺陷。

```bash
docker compose --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml --profile <p> --progress plain build <svc> \
  > output/build-logs/<svc>.log 2>&1
grep -nE "error|Error|ERROR|✗|Could not resolve|failed" output/build-logs/<svc>.log | head -40
```

- **一定落盘再 grep**：`| tail -60` 会把真正的报错行截掉（多阶段构建里错误在中间）。
- 前端构建失败优先看 `MISSING_EXPORT` / `Could not resolve`（第 1 层）与模板解析错误。
- 多服务一次 build 时，某个失败会让其余 `CANCELED` —— **别把 CANCELED 当成失败**。
- 跑完**逐个比对运行中容器是否真的用了新镜像**（否则「重建了但没生效」）：

```bash
for s in <c>:<image>:<tag> ...; do
  c=${s%%:*}; img=${s#*:}
  a=$(docker inspect $c --format '{{.Image}}' | cut -c8-19); b=$(docker inspect $img --format '{{.Id}}' | cut -c8-19)
    [ "$a" = "$b" ] && echo "$c = $img ✓" || echo "$c 不一致"
done
```

### 🔴 先判「镜像落后于源码」，再决定要不要建 —— 别整仓全建

拉完代码不要凭感觉「全建一遍」。用**时间戳比对**精确定位需要重建的服务：

```bash
# 受影响源码的最后提交时间
git log -1 --format='%ad %h' --date=format:'%m-%d %H:%M' -- <改动的源文件>
# 镜像构建时间（UTC；换算 +8 才是北京时间）
docker image inspect <img> --format '{{.Created}}'
```

镜像时间 < 源码提交时间 ⇒ **该服务必须重建**；否则纯属浪费。
典型映射（本项目）：`*.vue / src/**` → 对应前端镜像；`pig/db/**/*.sql` 与任何 Java 源码 →
`pig-gateway`（boot 打包，**前端是构建产物镜像、后端打进 app.jar，都不能靠挂载生效**）。

同时注意**网络共用**这一类「隐形依赖」：判据不是「有没有 `deploy-*` 容器」，
而是容器**挂了哪些网络**（本项目 boot / python-ai 同时挂 `deploy_backend` + `linmo-net`，
而 mysql / redis / 前端只在 `linmo-net`）：

```bash
docker network ls
docker inspect <c> --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
```

### 🔴🔴 重建容器：`up -d --force-recreate <svc>` 的三个静默副作用

**① 连带重建 depends_on 依赖链。** compose 的 `up <svc>` 语义是「启动 svc **及其依赖**」，
加上 `--force-recreate` 就变成「整条依赖链的容器全部重建」。只想重建前端，却把
`pig-gateway`（Java 后端）与 `python-ai` 一起重启 —— 后端要 80~90s 才 healthy，
这期间经前端的 `/api/*` **全部 502**。
**定式：只重建单个服务时加 `--no-deps`。** 判据：`docker inspect <各容器> --format '{{.State.StartedAt}}'`
若多个容器启动时间戳相同（秒级一致）⇒ 就是被连带重建了。

**② 漏带项目的 env 文件 ⇒ 拓扑漂移（症状是全站 502，但看着像「前端坏了」）。**
`--env-file` 的语义是**替换**默认的 `deploy/.env` 自动加载，**不是追加**。只写
`--env-file deploy/.env.dev` 时，compose 里 `${MYSQL_HOST:-deploy-mysql-1}` 这类插值会
回落到**默认值** —— 而默认值常指向另一套拓扑（发布栈），本机没跑 ⇒ 容器内
`MYSQL_HOST=deploy-mysql-1`（解析不了）⇒ boot 报
`java.net.UnknownHostException: deploy-mysql-1` + `Communications link failure`，
且 **Druid 是后台线程建连、启动不失败** ⇒ 容器看着起来了、日志也有 `Started PigBootApplication`，
但全站 502。**这类故障最容易误判成「重建前端把后端搞坏了」，实际是 env 没带全。**

**判据（30 秒）**：

```bash
# ① 容器内实际生效的 DB 主机，必须等于真实容器在网络里的别名
docker inspect <容器> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E "MYSQL_HOST|DATASOURCE_URL"
# ② nginx 侧：502 + connect() failed (111: Connection refused)
docker logs <前端容器> --tail 30 | grep -E "connect\(\) failed|502"
# ③ 容器间连通性（在容器内测，别在宿主机测）
docker exec <前端容器> sh -c 'getent hosts <后端服务名>; wget -qS -O /dev/null --timeout=5 http://<后端>:<port>/actuator/health'
```

**定式（顺序不能反 —— 后一个 `--env-file` 优先级更高）**：

```bash
docker compose --project-name <proj> \
  --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml \
  up -d --force-recreate --no-deps <svc>       # 只动这一个
```

**③ `--wait` 在无 tty 环境下可能被 SIGTERM（exit 137）**：容器其实已经起来了，
只是命令返回被中断 —— **别据此判定「重建失败」**。直接查真实状态：

```bash
docker ps --filter "name=<c>" --format '{{.Names}} | {{.Status}} | {{.Ports}}'
docker inspect <c> --format '{{.State.Health.Status}}'
```

`--wait` 要等 healthcheck 通过（Java 服务 80~90s），很容易撞上工具超时，
建议 **up 不带 `--wait`，另起轮询**。

**④ 🔴 容器名会随编排切换而变，别背名字**：本机在跑栈会在两套编排间来回切 ——
「旧一体化编排」= `linmo-pig-boot / linmo-pig-ui / linmo-pig-pc-ui / linmo-python-ai / linmo-redis / linmo-env-applier`，
「私仓镜像版 / 个人版编排」= `deploy-nginx / nginx-pcui / pig / python-ai / mysql / redis`（两套有时并存）。
⇒ **任何「按容器名」的操作前（`docker exec`、`docker inspect` 取镜像做 python 冒烟）一律先**
`docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'` **实测取名**，
别沿用上一轮记忆里的容器名（曾把 `linmo-python-ai` 与 `deploy-python-ai-1` 记反，白跑一轮冒烟）。

> **元教训**：这三个坑的答案**都已经写在仓库自己的 `deploy/.env` 注释里**
> （原话：「本机拓扑覆盖 —— 别删，删了 compose up 就换拓扑」、
> 「不覆盖的后果（已实测踩过）…」）。**重建前先读目标环境的 env 文件注释** ——
> 它记录的就是上一轮踩过的坑，比任何通用经验都准、也最容易被跳过。

### 🔴 「本地未提交的 compose 改动」会自己制造解析失败 —— 不是 merge 冲突

症状：`docker compose ... up/build` **第一步就停**，报

```
failed to parse .../deploy/docker-compose.yml: yaml: construct errors:
  line 120: line 147: mapping key "nginx" already defined at line 129
```

这既不是冲突标记、也不是依赖/网络问题 —— 是 **YAML 同一 mapping 下出现重复键**：有人往
`services:` 里**又加了一个同名服务**（想「多开一个入口」），却复用了键名。此时 `git status`
只会显示一行 ` M deploy/docker-compose.yml`，**看起来完全像正常本地改动** ⇒ 极易被当成
「合并带来的问题」往错方向查（去翻 merge 冲突、去查依赖）。

**10 秒判据**（不启任何容器、只看一个文件）：

```bash
docker compose --env-file deploy/.env.dev -f <compose.yml> config -q      # 静默通过 = OK
docker compose --env-file deploy/.env.dev -f <compose.yml> config --services
```

**修法**：给新增服务起**唯一名**，保持原意图不变 —— 2026-10-14 实例：新增块与已有块同用
`nginx:` 键，改名 `nginx-pcui:`（`8888 → pig-ui`、`8890 → pig-pc-ui`），顺手修掉从上一块
复制过来的错注释（写的「宿主 8888」实际是 `8890`）。

**别做**：① 把整个新增块删掉（用户本意就是「加一个入口」，删了等于丢功能）；
② 当 merge 冲突去 `git checkout --ours/--theirs`（它压根没经过 merge，取边会真的丢改动）。

## 第 3 层 · 数据库：老库**不会**自动收到新脚本

脚本通常进**两处**（MySQL 镜像供 initdb + 应用包供在线升级页比对 checksum）⇒ 改脚本要重打包应用，
且老库需要**主动触发**升级。

```bash
TOK=$(cat output/pig-token.txt)   # 项目自带的令牌自愈脚本
curl -s --noproxy '*' -H "Authorization: Bearer $TOK" "http://localhost:8888/admin/db/upgrade/pending"
```

🔴 **该接口的 `data` 常是 dict**（形如 `{summary:{total,pendingCount,modifiedCount}, scripts:[...]}`），
不是数组 —— 直接 `len(data)` 会得到「剩余 2 条」这种假结论。
**必须同时看 `summary.pendingCount` 和 `summary.modifiedCount`**：`pendingCount` 是「从没跑过的」，
`modifiedCount` 是「跑过但内容变了、会重跑」的。只看前者会漏掉整整一类待办（见下方按钮坑）。

执行链（**先备份，再执行，失败即停**）：

```bash
curl -s --noproxy '*' -X POST -H "Authorization: Bearer $TOK" .../admin/db/upgrade/backup   # 返回 {file,size,tables}
docker cp <app-container>:<backup-dir>/<file> output/db-backup/<date>/                       # 必须拷出容器
curl -s --noproxy '*' -X POST -H "Authorization: Bearer $TOK" .../admin/db/upgrade/execute
```

- `execute` 跑的可能**多于 pending 列表**（`MODIFIED` 状态的脚本也会重跑）—— 正常。
- 失败即停：修脚本后重跑即可（幂等约定），不要手工跳脚本。
- 复检 `summary.pendingCount == 0`，并抽查 `information_schema.tables` 确认新表真的建出来了。

### 🔴🔴 两侧各在「不同位置」补登同一批 ORDER 条目 ⇒ merge 不报冲突，却静默产生**重复条目**

- 现象（2026-10-14 实测踩中）：并行会话与我方都在 `pig/db_bak/initdb-loader.sh` 的 ORDER 里补登**同一批**脚本，但**位置不同**（一在 `kb_qa_schema.sql` 中段、一在 ORDER 末尾）⇒ git 逐行合并时**两处都保留** ⇒ 重复条目。
- ⚠️ **`git diff --diff-filter=U` 看不到它** —— 该文件根本不在冲突列表里。**「无冲突」≠「合并正确」。**
- 判据（输出必须为空）：
  ```bash
  grep -oE '^\t[^ #].*\.sql$' pig/db_bak/initdb-loader.sh | sed 's/^\t//' | sort | uniq -d
  ```
- 推广：凡「ORDER / 清单 / 注册表」类文件，合并后都要单独跑一次去重，别只信 `git status`。

### 🔴🔴 生成物冲突（`pig/db/0N_*.sql`）**绝不手工解** —— 取一侧占位后重生成

- `pig/db/0N_*.sql` 是 `tools/consolidate_db.py` 从 `pig/db_bak/` 保序切段的产物 ⇒ 段号是**位置的函数**，冲突常表现为整段重编号（本次 `06_menu_perm_patch.sql` 118 个冲突标记，全是重编号，无实质分歧）。
- 正确顺序：
  1. **先定 ORDER**（含各处新增条目的相对位置）—— 永远别去改生成物；
  2. `git checkout --theirs -- pig/db/0*.sql` 取一侧占位 + `git add`（内容稍后被覆盖，只为让 index 干净）；
  3. 同步 `tools/consolidate_db.py` 的 `SEGMENTS`，使各段**连续覆盖 `1..N`**（生成器会校验）；
  4. 重跑 `python tools/consolidate_db.py --verify`，确认自检行「N 个脚本块的顺序与 ORDER 严格一致」；
  5. 验收：`git diff --stat pig/db` 只应出现**预期的那几段**变化，其余若只有 `[k/58]→[k/60]` 类重编号即正常。
- `.workbuddy/memory/YYYY-MM-DD.md` 冲突别手工抄段 ⇒ 走 `python tools/merge_memory_log.py --from-index <file> --write`（**先 dry-run**，看「零丢失校验通过（ours X 行 / theirs X 行 全部保留）」那行）。
- 合并收尾三连：`tools/merge_integrity_check.py`（4/4）+ `tools/consolidate_db.py --verify` + 确认「本轮自己改的代码 `git diff <自己的提交>` 为空」（保证已构建的镜像仍对得上）。

### 🔴🔴 改了 `pig/db/**/*.sql` ⇒ 重建 boot 后它一定变 `MODIFIED`，而升级页按钮可能**点不动**

改任何一个已在迁移表登记过的 `.sql`（哪怕只加一句 `USE pig;`），**磁盘校验和就与登记值不同**
⇒ 重建 boot 后升级页把它判成 `MODIFIED`。此时典型状态：

```json
{"total":72,"executed":72,"pendingCount":0,"modifiedCount":1}
```

**坑**：升级页的按钮写成 `:disabled="pendingCount === 0"`，而 `pendingCount` 只取
`summary.pendingCount`（**不含 `modifiedCount`**）⇒ 出现「表格里赫然一行红色『已变更』，
按钮却是灰的、文案写『立即升级（0 个待执行）』」—— **MODIFIED 脚本永远无法从 UI 执行**，
校验和也永不刷新，页面永远停在「已变更」。
**且后端并无此限制**（`DbUpgradeService` 注释明确「MODIFIED 同样按口径执行，不额外要求人工确认」）
⇒ 是前端统计口径漏了一项，两份 `components/UpgradePanel.vue`（pig-ui / pc-pc-ui）**内容一致、同源同坑**。

- 判定：打开升级页，取按钮 `disabled` 属性 + 表格里是否有 `已变更` 行；两者同时为真即命中。
- 绕行：直接调 `POST /admin/db/upgrade/execute`（先 `backup`）—— 它本来就会跑 MODIFIED。
- 修法（若获授权）：把禁用条件与文案改成 `pendingCount + modifiedCount`，并同步确认弹窗里的
  数量文案，避免"执行 3 个"却提示"0 个待执行"。改完**两个前端都要重建**。

### 🔴🔴 「跑完升级，菜单/功能反而**少了**」——段位多 owner + 只跑变更集

**症状**：升完级后有人说「XX 目录下好几个子功能不见了」，但页面代码都在、新库 initdb 也正常。

**机制（必须记住）**：

```
脚本 A：DELETE FROM sys_menu WHERE menu_id BETWEEN 6000 AND 6099  ← 整段重建（固定清单重插）
脚本 B / C：往同一段增量追加几条菜单（各自的 checksum 长期不变）
升级页执行口径：只跑 PENDING + MODIFIED，**按文件名字典序**
⇒ A 被改过一次（哪怕只改注释）就重跑一整段 DELETE；B/C 没变 ⇒ 不重跑
⇒ B/C 追加的东西**永久消失**（菜单 + 对应的 sys_role_menu 授权）
```

**⚠️ 最坑**：`initdb`（新库）顺序受控，所以**新库里是好的** ——
「我跑一遍全新初始化没问题」**不能**作为这段没问题的证据，问题只在**老库升级路径**上。

**定位（秒级，别手工翻 SQL）**：

```bash
python3 tools/menu_sync_audit.py --show 40     # 静态重放 pig/db/**/*.sql 与现网逐行比，标注 文件:行号
#   「仅脚本有，现网没有」= 脚本能建出来、现网没有 ⇒ 被吞掉
#   「仅现网有，脚本缺失」= 库里有、脚本没有 ⇒ 手工建的，迟早丢
python3 tools/diff_initdb_vs_live.py           # 权威复核：真起临时容器跑一遍 initdb 再比
```

**证据链（交付时必须给）**：`sys_db_migration` 的 `script_name + create_time` 时间线
（谁在什么时候跑过）＋ 两份整库备份的 `sys_menu` 差集（「全库 422→421，**唯一减少的就是这 7 条**」
这种句子最有说服力）。升级页的 backup 时点就是批次开始的时刻。

### 🔴🔴 别只补「报障的那几条」——同一坑往往有第二个受害者

**报障的人只看得见他熟悉的那个模块。** 先算出 **该段完整的 owner 集合**，再决定守卫范围：
把「现网该段全部行」减去「段位重建脚本 INSERT 里的 id 清单」，差集就是**下一轮会被吃掉的行**。

```bash
# ① 现网该段全部行
docker exec <mysql> sh -c 'mysql -uroot -p"$PW" -N -e \
  "SELECT menu_id,name,visible FROM pig.sys_menu WHERE menu_id BETWEEN 6000 AND 6099 ORDER BY menu_id;"'
# ② 段位重建脚本自有的 id 清单（python 正则抽 `^\s*\((\d{4}),`，别手抄）
# ③ 差集 = 需要纳入守卫的行
```
实证：2026-09-29 只报了 7 条（6063/6064/6071~6075），2026-09-30 复核发现
**6033~6035（市场智能体）由另一个脚本维护、且同样不会重跑** —— 不修的话，
下一次「立即升级」会把这 3 条也一起吃掉。

**修法（照抄结构，别只补数据）**：

1. 新增 `xxx_restore.sql`：把**该段全部非重建脚本自有行**（不是只有报障的那几条）+ 授权
   **幂等重新断言**（`ON DUPLICATE KEY UPDATE`）。
   🔴 **不要写 `DELETE sys_role_menu WHERE menu_id IN (…)`**：`sys_role_menu` 主键是
   `(role_id, menu_id)`，`INSERT IGNORE` 本身就够（不会撞主键）；而先 DELETE 会把
   **非超管角色的授权静默抹光**（本仓库已记录在案的坑，段位重建脚本为此专门做了临时表快照）。
2. **在守卫脚本末尾放哨兵**，让下次新增 owner 时**失败即停**而不是静默丢数据：

```sql
-- 临时表 + CHECK 约束 = 不用存储过程也能「失败即停」（MySQL 8.0.16+ 真报 ERROR 3819；
-- 更低版本 CHECK 被忽略 ⇒ 退化为「没有哨兵」，不会误报，安全降级）
DROP TEMPORARY TABLE IF EXISTS `tmp_guard_unmanaged`;
CREATE TEMPORARY TABLE `tmp_guard_unmanaged` (
    `menu_id` BIGINT NOT NULL PRIMARY KEY,
    CONSTRAINT `ck_6000_unmanaged_menu_must_extend_guard` CHECK (`menu_id` < 0)
) ENGINE = InnoDB;
INSERT INTO `tmp_guard_unmanaged` (`menu_id`)
SELECT `menu_id` FROM `sys_menu`
WHERE `menu_id` BETWEEN 6000 AND 6099 AND `del_flag` = '0'
  AND `menu_id` NOT IN (/* 重建脚本自有的 34 条 */)
  AND `menu_id` NOT IN (/* 守卫纳管的 10 条 */);
DROP TEMPORARY TABLE IF EXISTS `tmp_guard_unmanaged`;
```
   升级服务只对「对象已存在」族放行（1050/1060/1061/1826），CHECK 违例属真失败
   ⇒ 脚本记 FAILED 且**停止后续脚本**。**约束名本身就是处置指引**（一句话写在名字里）。
   哨兵必须放在脚本**最后**：让断言/恢复先落地，再判定。

3. **动手前先空跑**（`CREATE TEMPORARY TABLE` 不触发隐式提交，可整段回滚）：

```bash
python3 - <<'PY' > /tmp/dryrun.sql
import pathlib; print("START TRANSACTION;")
print(pathlib.Path('pig/db/<域>/xxx_restore.sql').read_text(encoding='utf-8'))
print("SELECT COUNT(*) FROM sys_menu WHERE menu_id BETWEEN 6000 AND 6099 AND del_flag='0';")
print("ROLLBACK;")
PY
docker exec -i <mysql> sh -c 'mysql -uroot -p"$PW" -N pig' < /tmp/dryrun.sql   # 无输出=无报错
# 回滚后复核：行数/关键 id 与跑之前一致，证明没留下副作用
```

4. 把它登记进 `initdb-loader.sh` 的 `ORDER`，**紧随段位重建脚本之后**（顺序受控，不靠字典序碰运气）。
   注意**升级路径按文件名字典序**，所以守卫脚本的**文件名必须排在重建脚本之后**
   （`ops_agent.sql` < `ops_center_menu_restore.sql` ✓，靠 `o`<`c` 的字母序）。
   🔴 **登记完必须实跑一次「全新 initdb」才算收口** —— `tools/merge_integrity_check.py` 只检查「本次新带入的
   文件是否登记」，**既有一行未登记的脚本照样能在字典序兜底段把初始化打断**（dev 自认为「一次性手工执行」的
   `sync_172_*` / `ops_simu_*` / 声明「已停用」的脚本也会被自动跑）。权威工具 `tools/diff_initdb_vs_live.py`；
   手搓等价版与两类报错的归因（`ERROR 1146` = 执行顺序反了；`ERROR 1136` = 位置化 `INSERT ... VALUES`
   撞上后来 ALTER 加的列）见技能 `linmo-stack-rebuild-reset` §2.0。
   2026-10-08 实测：一次合并带入的 SQL 里就藏着两处必崩（第 80/119、第 118/119 步各一处）。
5. 在段位重建脚本头部写清「本段不归你独占 + owner 清单 + 事故实证 + 改前必读」。
6. 清缓存后复跑 `menu_sync_audit.py` 收敛（判据：「仅脚本有，现网没有」应降到 0）。

**根治方向**：让一个 ID 段只有一个 owner —— 把增量行并进段位重建脚本的 INSERT，
删掉其它脚本里的同段菜单语句。代价是改老脚本 checksum（下次升级会重跑），收益是消除这类结构性风险。

**同类变体：ID 段撞车**。两个语义完全不同的模块用了同一段 ID（如灵猫管理端 6100~6112
与基础模块的「日志归档」6100~6112），一方无条件 `UPDATE … SET visible='0'` 就把另一方隐藏了。
判据：脚本的 `WHERE` 里**没有任何限定列的写法**（只按 menu_id 范围打）＋ 该 ID 段有别的脚本在用
（`grep -rn "<id>" pig/db/**/*.sql`）。修法：给 `WHERE` 加语义限定（`path/component LIKE ...`），
并顺手把已被误伤的行恢复。

## 第 4 层 · 缓存：改了菜单/参数必须清缓存，否则页面「还是旧的」

```bash
# ⚠️ 不要用 `for k in $(redis-cli keys ...)`：zsh 不按换行分词 ⇒ del 静默无效仍返回 0
docker exec <redis> redis-cli -n <db> EVAL \
  "local n=0 for _,k in ipairs(redis.call('keys', ARGV[1])) do redis.call('del', k) n=n+1 end return n" \
  0 'gl:menu_details::*'
# 同样处理 gl:user_details::* / site_config_details::*
```

清完**必须复探令牌**（`GET /user/info` → `code==0`），确认没把登录态一起清坏。

### 🔴 清完还要**验证重建出来的值**，别只看「删除成功」

删键成功 ≠ 页面会变。本轮实测：删掉 `gl:menu_details::1` 后调 `/admin/menu`，
新缓存的 JSON 里**仍然没有刚补回的那几个 id**（缓存由 DB 重建，但那一刻读到的不是预期内容）。
判据是「重建值里含不含目标 id」，不是「del 返回几」：

```bash
docker exec <redis> redis-cli -n 5 del 'gl:menu_details::1'
curl -s -H "Authorization: Bearer $TOK" "$BASE/admin/menu" -o /tmp/m.json
docker exec <redis> redis-cli -n 5 get 'gl:menu_details::1' | grep -c '607[0-9]'   # 应 >0
grep -c '<刚补回的 id>' /tmp/m.json                                                # 接口也要含
```
接口不含就**再删一次再调**（排除并发请求写入旧值），仍不含才去查后端过滤逻辑
（`SysMenuController#getUserMenu` → `findMenuByRoleId` 带 `@Cacheable(MENU_DETAILS, key=#roleId)`
→ mapper `listMenusByRoleId` 是 `sys_menu LEFT JOIN sys_role_menu WHERE role_id=?`：
**授权缺了菜单就不返回**，所以「菜单补回来了但页面没有」先查 `sys_role_menu`）。

⚠️ **升级页的 `execute` 不自带备份** —— 服务端只提供 `/db/upgrade/backup` 与 `/db/upgrade/execute`
两个独立端点，控制器注释明确写「强烈建议先调 /backup」。**先备份再执行，别指望它自己备**。

## 第 5 层 · 页面：实渲染 + 双扫（console 报错 / 失败请求）

只 `curl` HTML 只能证明 nginx 活着。用 Playwright（cookie 注入 token 免验证码）逐页渲染，
并**同时**采集 `console` error 与 `/admin/` 下 4xx/5xx 响应：

```js
const errors = [], bad = [];
page.on('console', m => m.type() === 'error' && errors.push(m.text().slice(0,220)));
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('response', r => { const u = r.url();
  if (u.includes('/admin/') && r.status() >= 400) bad.push(`${r.status()} ${u}`); });
await ctx.addCookies([{ name: 'token', value: TOKEN, url: BASE }]);   // 免滑块验证码
await page.goto(`${BASE}/?ddtk=pig#/path/index`, { waitUntil: 'load' });
await page.waitForTimeout(9000);
const txt = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
// 另外检查 /\bNaN\b/ 与 /\bundefined\b/ —— 后端计数经 JSON 回来是字符串，极易渲染成 NaN
```

**新链路必须带降级语义**：页面显示「AI 暂不可用 / degraded」是**正常降级**，不是崩溃；
但「console 报错」「4xx/5xx 请求」「NaN/undefined」三者任一非 0 都算没通过。

### 🔴 点页签 / 点按钮时的选择器坑（Element Plus）

Element Plus 的 `el-tabs` 用 **`v-show`** 隐藏非活动面板 ⇒ 非活动面板里的 `textarea`/`button`
**仍存在于 DOM**。用 `page.$('textarea')` 会抓到隐藏的那个，随后 `click()` 报
`element is not visible`（超时 30s），看起来像「功能坏了」，其实只是抓错元素。
定式：选择器一律带 `:visible` —— `await page.$('textarea:visible')`、
`await page.$('button:has-text("执行"):visible')`，切页签用
`await page.click('.el-tabs__item:has-text("SQL")')`。

**顺带的好处**：把「留痕/审计类列表」也截进图，能**同时证明拦截生效** ——
例如 SQL 执行台的留痕里能看到 `USE mysql;`、`DROP DATABASE pig;` 两条被拒记录
（mode=BLOCKED），比只截一张成功查询更有说服力。

### 🔴 「点击后应跳转」类改动：断言 `location.hash`，别只看截图

改「点 tab A 应跳到独立页 B」这种改动时，**截图看着像新页面也可能只是原页滚了位置**。
唯一可靠的断言是路由真的变了：

```js
const before = await page.evaluate(() => location.hash);
await page.locator('button', { hasText: /^市场智能体$/ }).first().click();
await page.waitForTimeout(4000);
const after = await page.evaluate(() => location.hash);   // 应 === '#/ops/market/index'
```

同时断言**目标页真的渲染出内容**（取该页独有的文案/元素），否则可能跳到一个空壳路由。
按钮匹配用**全字锚定** `hasText: /^市场智能体$/`——`hasText` 是子串匹配，
不加锚点会命中「新媒体运营智能体」等含相同词的其他 tab。

### 🔴 截图坑：内容在「内部滚动容器」里时 `fullPage` 只截到一屏

后台模板（pig-ui 等）把页面主体放在 `.layout-main-scroll`（`el-scrollbar__wrap`）这类
**内部滚动容器**中，`page.screenshot({ fullPage: true })` 只覆盖 **window** 的滚动高度
⇒ **下方区块完全截不到**，很容易误判成「页面就只有一屏 / 第二块没渲染」。

两个连带坑：
- 「选 `scrollHeight` 最大的元素来滚」会**选错** —— 内容高的 `.linmo-embedded`（sh=2777）
  不是滚动容器，真正可滚的是 `.layout-main-scroll`（`scrollHeight > clientHeight` **且** 可滚）。
- 容器 `scrollHeight` 会随首屏加载变化（同页先测得 1772、后测得 915）⇒ 别用数值当判据。

**定式**：要截哪个区块就**直接 `locator(该区块).screenshot()`** —— element screenshot
自带 `scrollIntoViewIfNeeded`，且元素大于视口时也能截全，比凑 window/容器滚动可靠得多。
验证「同页多区块共存」时，先用 DOM 断言（`querySelector` 各区块容器 + `pageerror` 计数）拿硬证据，
再用 element screenshot 出国图。

---

## 副本工程：一端改了，另一端**不会**自己跟上

有的工程是「主站 + 移植副本」（如 `pig-ui` 主站、`pig-pc-ui` 裁剪客户端，业务页由前者移植而来）。
队友只改主站时，副本会**静默落后**，表现为「同一个页面在 A 端口和 B 端口行为不一致」。

**定式**：只比**移植范围**目录，别全量 diff（两个产品本就不同，admin/权限体系差异是正常的）：

```bash
for d in views/linmo views/ops; do diff -rq pig-ui/src/$d pig-pc-ui/src/$d; done
diff <(ls pig-ui/public) <(ls pig-pc-ui/public)      # 🔴 静态资源不在 src 里，最容易漏
```

- 差异**逐个判断**：属于移植范围的业务页 ⇒ 同步；属于产品裁剪的 ⇒ 保留差异并写进交付。
- 🔴 **同步副本时必须连带清理"只在一端存在的旧逻辑"**：例如主站已删除某个跳转拦截函数，
  副本还留着 —— 同步组件后就会出现「拦截 + 新逻辑」打架。先 `grep -n <旧函数名> <副本文件>` 确认。
  （实例：`ops/agent/index.vue` 的 `onTabClickCapture` 两端口径不一致）
- 内容本应逐字节一致时，直接 `cp` 再 `diff -q` 断言，比逐处手工 Edit 安全。

### 🔴 提交前 10 秒判「N 端同源改动是否真同步」—— change-set 指纹法

**适用**：同一笔在途改动声称「三端/N 端同源」（本仓常态：`pig-ui` / `pig-pc-ui` / `pig-mob-ui`
的同一 `.vue` 由并行会话同时改完）。**逐文件读 diff 太慢，且看不出「某端漏了半处」。**

```bash
for f in pig-ui pig-pc-ui pig-mob-ui; do
  git diff -- $f/src/views/<模块>/<页面>.vue | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' > /tmp/d_$f.txt
done
md5 /tmp/d_*.txt                       # 三份必须**同一个 md5**
diff /tmp/d_pig-ui.txt /tmp/d_pig-pc-ui.txt && echo "UI==PC"
# 再核新符号出现次数也必须一致（漏半处时 md5 不同 / 计数不同）
for f in pig-ui pig-pc-ui pig-mob-ui; do
  printf "%s newFn=%s newRef=%s\n" $f \
    "$(grep -c '新函数名' $f/src/views/<模块>/<页面>.vue)" \
    "$(grep -c '新字段名' $f/src/views/<模块>/<页面>.vue)"
done
```

- 判据：**三份 change-set md5 相同 + 新符号计数逐项相同** ⇒ 三端真同步。任一项不同 ⇒ 落回上面
  「逐个判断」流程，别提交。
- ⚠️ 只对「内容本应一致」的路径有效；跨端**故意不同**的（财务页 `FinanceReport.vue` 等）不适用。
- 复现记录：2026-10-08 三端 `Matters.vue` 一笔改动，三份 change-set md5 同为
  `4f6d8b6e8112cf0ca688ed130a307149`、新符号计数 `2/4/9` 全一致，10 秒内确认后直接提交。

## 产物级验证：源码改了 ≠ 镜像里是新的

前端是**构建产物镜像**，「重建命令成功」不证明「新代码进去了」。要读**容器内压缩产物**：

```bash
docker exec <容器> sh -c 'grep -o ".\{0,28\}关键业务串.\{0,28\}" /data/assets/<chunk>.*.js | head -5'
```

- 🔴 **先确认 chunk 归属与大小写**：`agent.*.js` 与 `AgentReport.*.js` 可能是**两个不同 chunk**，
  在错的文件里 grep 会得到「不存在」的**假阴性**。先 `ls /data/assets/ | grep -iE "^agent"` 列全再搜。
- 🔴 **压缩后变量名会变**：pattern 别写死 `e.agentCode`，用宽松通配（`project"!==.\{0,20\}`），
  或直接搜**字符串常量**（emit 名、query 参数名、中文文案）—— 常量不会被压缩掉。
- 🔴 **对比式验证最有力**：修复前后各跑一次**同一探针**，比较 bodyText 布尔量
  （如「某关键词 ∈ bodyText」True→False），远比「有没有报错」能证伪。

## 并行会话会把你**未提交**的改动一并提交

同一工作目录被两个会话同时操作时，对方执行 `git add -A && git commit && push` 会
**把你的在途改动一起带走**。症状：准备提交时发现 `git status` 莫名干净、或改动"不见了"。

**先查归属，别急着重做**：

```bash
git log --oneline -5            # 有没有「message 陌生、但文件是我刚改的」提交？
git show <那个sha> --stat       # 文件列表里有我刚改的文件吗
```

**定式**：提交时**显式点名文件**（`git add <f1> <f2>`，不用 `-A`），并在交付里写明
「某改动已由并行会话的 `<sha>` 一并提交」—— 避免重复提交或误判丢失。

## rebase 的三个坑（这一层不解决，上面全白做）

1. 🔴 **`git rebase --continue` 会拉起 `$GIT_EDITOR`** ⇒ 无 tty 的沙箱里被 SIGTERM，
   **exit 137 且零输出** —— 极易误判成"被沙箱杀了"。
   定式：`GIT_EDITOR=true GIT_SEQUENCE_EDITOR=true git rebase --continue`。
2. 🔴 **rebase 的 checkout 阶段会删掉被 gitignore 的软链**（软链目标文件在索引里是「已删除」），
   且它**不出现在 `git status`**（被忽略）⇒ 服务/测试突然读不到配置。
   **rebase 后重建软链**，并把它写进「拉取后检查清单」。
3. 🔴 **每轮都要重跑 `fetch → rebase → push`**：并行会话会在你 rebase 期间又 push，
   `push` 被拒（non-fast-forward）不是失败，是提醒你再来一轮。

顺带：**`.env` 这类被 merge 反复带回版本库的文件**，每次拉取后都 `git ls-files <file>` 复检一次
（脱跟踪 + 软链的约定会被 merge 悄悄推翻，且会顺带把明文密钥带回库）。

## 收口清单（照抄）

- [ ] `git status` 干净、`rev-list --left-right --count` 为 `0 0`
- [ ] 五层各有一次**可复算**的证据（构建日志 / pending=0 / 缓存清理计数 / 页面截图+双扫=0）
- [ ] 运行中容器镜像 ID == 最新构建镜像 ID
- [ ] 探活避开根路径（后端与 AI 服务的 `/` 返 404 是正常）
- [ ] 明确写出：没验证的层、非本次引入的缺口（如某 App Key 未配）
- [ ] 有移植副本的工程：`views/` 与 `public/` 都做过一致性 diff，并说明哪些差异是**有意保留**的
- [ ] 「N 端同源」的在途改动提交前做过 **change-set 指纹**核验（各端 diff 的 md5 + 新符号计数全一致）
- [ ] 前端改动做过**产物级**校验（容器内 chunk grep 到特征串），不只依赖「重建成功」
- [ ] 提交信息里写清「根因 + 判据 + 验证方式」，供队友与未来的自己复算
