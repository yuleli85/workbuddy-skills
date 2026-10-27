---
name: git-quick-commit
description: git 拉取/提交/推送的快速通道 —— 一次调用跑完全部体检与同步，并自动处理「远端已前移导致 push 被拒」与 loose ref 丢失。当用户说「提交一下」「提交本地变更」「更新到最新并提交」「push 一下」「代码提交」「提交并推送」「commit 一下」「把这个改动提交了」「拉取最新的代码」「拉取代码」「同步最新代码」「更新代码」时使用。覆盖：① 单命令体检（分支 / 工作区 / 领先落后 / 脱跟踪复检）；② 拉取（fetch+仅快进，绝不擅自 merge）；③ add -A → commit → push 全链；④ push 被拒自动 fetch+merge+重试（绝不 force）；⑤ 分支 ref 与 HEAD 不一致时自动重建；⑥ 明确与 pull-merge-sync-five-layers 的分工：本技能管「拉取/提交推送」快线，那个管「拉取后五层对齐」重流程；⑦ 切分支（`checkout`/`switch`）被本地未提交改动挡住时的「保命三步」，不丢在途工作。
agent_created: true
---

# git 拉取 / 提交 / 推送快速通道

## 核心：一条命令替代「多轮试探」

**慢的不是 git 命令本身，是往返次数。** 一次提交若靠逐步试探（先 status、再 fetch、再 diff、
再试 push、再处理拒绝…）会吃掉 6~10 轮工具调用；本技能把全部体检压进**一次调用**，
末尾直接给出「可安全直提」或「需人工介入」的结论。

```bash
S=~/.workbuddy/skills/git-quick-commit/scripts/git-fast.sh

# —— 拉取 ——
bash $S --pull                           # fetch --all + 快进当前分支（只做 ff，绝不擅自 merge）
bash $S --pull-all                       # 同上，并把其它「只落后、不领先」的本地分支一并快进

# —— 提交 / 推送 ——
bash $S                                  # 只体检（只读，不改动任何东西）
bash $S -m "fix(ops): 修复 xxx"           # 体检 + 暂存全部 + 提交 + 推送
bash $S -m "fix(ops): 修复 xxx" --paths "pig-ui/src/views/ops/a.vue"
                                          # 只提交指定路径（并行会话活跃时用这个）
bash $S -m "docs(memory): xxx" --no-push  # 只提交，不推送
bash $S --push-only                       # 已有本地提交，只推上去
```

体检段固定输出四块：**位置**（分支/上游）、**工作区**（含未跟踪）、**与远端差距**（未推送/未合入）、
**脱跟踪复检**（若仓库根有 `.git-fast.conf`）。

## 拉取模式（`--pull` / `--pull-all`）

**设计原则：只做快进，绝不替用户做合并决策。**

| 情况 | 脚本行为 |
|---|---|
| 当前分支只落后 | 打印落后的提交清单 → `git pull --ff-only` → 报告新 HEAD |
| 当前分支已最新 | 报「已是最新（本地未推送 N 个）」，不做任何改动 |
| **双向分叉**（本地领先 N + 落后 M） | **停下**，提示需人工 merge/rebase —— 不擅自合并（合并策略是用户的决策） |
| 落后但有未提交改动 | 停下，提示先提交或 stash；若改的是**远端也改了的共享日志** ⇒ 走下方「预并入」小节 |
| `--pull-all` 其它本地分支 | 仅快进「只落后、不领先」的；有本地独有提交的分支**跳过不动** |

`--pull-all` 的用途：重新 clone / 长期只用一个分支后，本地 `dev`、`main` 之类引用常停在很久以前
（实测：本地 `dev` 落后 533 个提交，而远端早就在跑）。这类「只落后」的分支可以零风险快进。
实现用 `git fetch origin <b>:<b>`（无 `+` 前缀 ⇒ 非快进会被 git 自己拒绝），**不改工作区、不需切换分支**。

拉取结束后同样会跑**脱跟踪复检** —— merge/pull 是把 `.env` 之类带回版本库的高发路径。

### 特殊情况：只落后（可 ff）、但工作区有未提交的**共享日志**改动

`is-ancestor` 为真时 ff 本应零冲突，可一旦工作区改的正是**远端也改了的文件**
（`.workbuddy/memory/YYYY-MM-DD.md` 这类「双方各自在文末追加当天日志」最典型），
ff 会被「未提交改动」挡住，直接 merge 又必然冲突（2026-10-06 16:15 实测场景）。

**推荐路径 —— 预并入，让冲突退化成平凡冲突**：

1. 取远端版本，把它的**新增段**按「段标题里的时间戳」并入本地文件的对应位置
   （不是简单拼到末尾 —— 否则段落时序错乱）；
2. **双向集合校验**：远端非空行集合 ⊆ 结果，缺失必须为 **0**，否则停下人工处理；
3. 提交本地全部变更（`-m … --no-push`）→ `git merge origin/<br>`；
4. 此时冲突块**远端侧通常为空**（相同内容已被 git 对齐）⇒ 校验 ours 不缺远端行后
   `git checkout --ours <file>` → `git add` → `git commit --no-edit` → `--push-only`。

本项目现成工具（**别手抄段落、也别重复造轮子**）：
`python tools/merge_memory_log.py --from-index <path> --write`（merge 冲突态读 index stage 2/3）；
未跟踪文件挡 pull 的场景见该脚本的 `--ours` / `--theirs` 用法。

**收尾判据**：merge 后 `git diff --name-only origin/<br> HEAD` 若**不含**「远端独有文件」，
即一次性证明远端改动已逐字落盘（有它 = 被旧版盖回，要回读核对）。

## 切分支被本地改动挡住（`checkout` / `switch`）

**症状**：`git checkout origin/dev` → `error: Your local changes to the following files would be overwritten by checkout` + 文件清单 + `Aborting`。
注意这是**切分支**，不是 merge ⇒ 脚本的 worktree 隔离推送**不覆盖**这条路径，按下面手工做（3 步，全程无损）。

**先做两个判据，再动手**（别一上来 `git checkout -f`）：

1. **两边是不是真分叉** —— 用计数，别只看 `--is-ancestor`（顺序写反必得相反结论）：
   ```bash
   git fetch origin
   git rev-list --count origin/dev..HEAD   # 0 ⇒ 当前分支无独有提交
   git rev-list --count HEAD..origin/dev   # 0 ⇒ 目标分支无新东西
   ```
   两边一 0 一 N ⇒ 单向超集，分支之间**零冲突**，挡住你的只可能是未提交改动。
2. **未提交改动值不值得留** —— 看是什么，不要默认「未提交 = 垃圾」：
   ```bash
   git diff --stat
   git diff -U0 | grep -E '^[+-](def |class |    def )'   # 新增了哪些函数/类
   git show origin/dev:<file> | grep -c '<新符号名>'        # 目标分支是否已含（0 = 这是新东西）
   ```

**处置：保命三步**

```bash
git switch -c wip/<topic>          # ① 新建分支承接改动（工作区原样带过去，一个字节不丢）
bash $S -m "wip: <描述>" --paths "<仅本次改动的路径>" --no-push
                                   # ② 提交，--paths 避开并行会话/本机数据（如 .workbuddy/），--no-push 别污染远端
git switch -c dev origin/dev       # ③ 建本地跟踪分支，而不是 `git checkout origin/dev`（那会进 detached HEAD，提交易丢）
```

未跟踪文件（`.workbuddy/`、临时脚本）**不受影响、切完仍在原地** —— 除非目标分支恰好跟踪了同名路径，那会改报
`untracked working tree file would be overwritten`，此时要先并入或改名。

**反例（会丢工作，别做）**：`git checkout -f <branch>`、`git checkout -- .`、`git stash drop`。

**收尾**：`git status -sb` 干净（只剩预期未跟踪项）、`git branch -vv` 里三个分支引用正确 ⇒ 交付时明确告知
「改动完整保留在 `wip/<topic>` @ `<sha>`，尚未合入 `<目标分支>`」，需要时 `git cherry-pick <sha>`。
⚠️ 双方都改过同一文件（主脚本/主 README 最常见）时 cherry-pick 大概率冲突，别承诺「直接能合」。

## 判据：什么时候用本技能，什么时候升级

| 场景 | 走哪条 |
|---|---|
| 只想知道/拿到最新代码（不需要构建） | **本技能** `--pull` / `--pull-all` |
| 工作区有改动要提交；本地有提交要推 | **本技能**（快线） |
| push 被拒（远端已前移） | 本技能**自动** fetch+merge+重试，不必切流程 |
| 拉进来的代码要「构建 → 数据库 → 缓存 → 页面」全对齐 | 升级到 `pull-merge-sync-five-layers` |
| merge 出现冲突、需联合合并（尤其日志 / 共享文件） | 升级到 `pull-merge-sync-five-layers` 第 1 层 |
| 多人同一工作目录并行写同一批文件 | 提交前**必须**读体检的工作区列表；发现不属于本次任务的路径就改用 `--paths` 精确提交 |

**一句话边界**：本技能"只搬代码、不动环境"；一旦需要重新构建/刷库/清缓存才算生效，就升级。
（拉取本身不等于生效：Java/python-ai/前端/`pig/db/**/*.sql` 的改动都要重建容器；SQL 脚本走升级页
还要注意「只有 MODIFIED 时按钮是灰的」那个已知缺陷。）

## 脚本已内置处理的坑（不必再手工做）

1. **push 被拒** `! [rejected] ... fetch first` —— 并行会话下是常态。自动 `fetch → merge → 重试`
   （默认 3 轮，可用 `GIT_FAST_RETRY` 调），**绝不 `--force`**。
   若 merge 被**本地未提交改动**挡住（`Your local changes to the following files would be overwritten by merge`），
   脚本自动改走 **worktree 隔离推送**：在 `origin/<br>` 的干净副本上 merge 本地 HEAD，再 `push origin HEAD:<br>`
   —— 主工作区**一个字节都不动**、在途文件零风险（已实测：远端拿到提交、在途改动保留、无残留 worktree）。
   本地分支会停在原提交（落后一提交），**等对方提交后自然 ff，不要去强改**。
2. **loose ref 丢失** —— commit/merge 后分支 ref 指向与 HEAD 不一致时自动重建
   （否则 push 报 `src refspec does not match any`）。
3. **脱跟踪回归** —— 读仓库根 `.git-fast.conf`，逐条复检「必须保持未跟踪」的路径，
   专治 merge/rebase 把 `.env` 之类带回版本库。
4. **未推送残留** —— 体检段直接列出未推送提交，消除「以为推了其实没推」。
5. **本地分支陈旧** —— `--pull-all` 把「只落后、不领先」的本地分支快进到远端，避免
   `git checkout dev` 拿到几个月前的代码。
6. **`--paths` 指向被 `.gitignore` 忽略的目录会静默空提交** —— git 打印 `The following paths are ignored … output`，
   脚本随后仍输出「无内容可提交（工作区为空）」+「推送成功 / Everything up-to-date」，
   极易误判成「已提交并推送」。**常见于把报告/截图写进 `output/` 类被忽略目录**（本仓 `linmo-pig-full` 即是）⇒
   这类产物本就**不进版本库**，交付走 `present_files` 即可，别浪费一轮提交；若确需入库要先 `-f` 或改 `.gitignore`（并确认这是你要的）。

## ⚠️ 头号误伤：`add -A` 会裹走并行会话正在写的文件

**实测踩过**：工作区除自己的文件外，还有另一个会话正在编辑的 `MarketReport.vue`；
`-m` 模式一把 `add -A` 就把它裹进提交，**而提交信息里完全没提它**。该文件改动本身是完整的
（不是半成品），但这种「信息与内容不符」的提交会给日后回溯埋雷。

**三层防御**：
1. 提交前先看体检的**工作区列表** —— 这是唯一能看见「夹带」的时机；
2. 出现不属于本次任务的路径 ⇒ 改用 `--paths "<只属于本次的路径>"` 精确提交；
3. 脚本自身也会在**跨多个顶层模块**时打印警告，看到就停下来核对。

**已经夹带、且已推送怎么办**：**不要 `--force` 重写共享历史** —— 那可能直接抹掉并行会话的工作。
接受现状，并把它写进交付说明；只有**尚未推送**时才能 `git reset --soft HEAD~1` 拆开重来。

## 提交信息规范

沿用仓库既有惯例（`git log` 可验）：

| 前缀 | 用途 |
|---|---|
| `feat(<scope>):` | 新功能（scope 例：`ops-agent` / `pig-pc-ui` / `db`） |
| `fix(<scope>):` | 修复 |
| `docs(memory):` | 记忆 / 日志类 |
| `merge:` | 合并提交 |

**一条提交只做一件事。** 多个不相关改动要拆开时，先 `git add <精确路径>` 手动暂存，再调脚本 ——
脚本默认 `add -A`，会把暂存区之外的改动一并带上。

## 失败处置

| 脚本输出 | 处置 |
|---|---|
| 裸 `git fetch/push` 报 `Permission denied (publickey)`（macOS：私钥带口令 + ssh-agent 无常驻身份） | **先给 git 指定 SSH 命令，别急着换 HTTPS 或换远端**：`export GIT_SSH_COMMAND="ssh -o UseKeychain=yes -o IdentitiesOnly=yes -i ~/.ssh/<key> -o BatchMode=yes"` —— macOS 的 `UseKeychain` 会从**登录 keychain 取私钥口令**，认证通后 `git-fast.sh` 全流程照跑。判定是否为「口令型私钥」：`ssh-keygen -y -f <key>` 报 `incorrect passphrase` 即是。**三个别试的方向**：① keychain 里的 HTTPS PAT 常已失效（`remote: Invalid username or token`）；② 无口令私钥多半**未授权到该仓库**（`Server accepts key` 后又 denied 的其实是别的 key）；③ `~/.ssh/agent/s.*` 这类旧 socket 能 `connect` 却**永不回包**（协议请求超时 ⇒ 把脚本挂住几分钟，`ssh-add -l` 也会挂） |
| 想先判断「这轮到底要不要 merge」 | `git merge-base --is-ancestor HEAD origin/<b>`：**为真 = 只落后 ⇒ `git merge --ff-only` 即可，冲突在几何上不可能存在**（别一上来手工 merge；此时「修复合并问题」多为空操作，如实报、勿硬造提交）；为假 = 真分叉，才走 `merge-tree` 预判 + 手工 merge。⚠️ **`--is-ancestor A B` 问的是「A 是否是 B 的祖先」，顺序写反必得相反结论**：判「要不要 ff」= `--is-ancestor HEAD origin/<b>`；判「X 是否已并入当前分支」= `--is-ancestor X HEAD`（如 `--is-ancestor origin/dev HEAD`）。交叉验证一律用计数：`git rev-list --count HEAD..origin/<b>` 为 0 ⇒ 只落后/已并入 |
| 想验证「合并/快进后编译没问题」但源码树其实没变 | 树没变时 `docker compose ... build <svc...>` 会**全程 CACHED**，几秒内仍打印每个镜像 `Built` —— 这本身就是「无编译问题」的证明，**不必 touch 文件去触发重编**。真要跑常规编译验证：`docker compose --env-file deploy/.env.dev -f deploy/docker-compose.dev.yml build pig-ui pig-pc-ui pig-gateway python-ai`（后端走多阶段 Maven，25 模块 BUILD SUCCESS 才算过） |
| `双向分叉…需人工 merge/rebase` | 先看两边各改了什么（`git log HEAD..origin/<b>` 与 `git log origin/<b>..HEAD`），再决定 merge 还是 rebase；合并后按「联合合并」保留双方内容 |
| 想知道「合下去会不会冲突」但**不想动工作区** | `git merge-tree --write-tree --name-only HEAD origin/<b>`（git ≥2.38）：干净时只打印一行结果树 OID，有冲突时才追加冲突文件清单。**只读、可用索引、不写工作区** ⇒ 拿它做合并前的「零副作用预判」 |
| 双向分叉且远端独有的内容集中在 `*.md`（memory/docs） | 别只看「有无冲突标记」—— 三方文本合并能**无冲突却语义错**（旧版整段盖回新版）⇒ 合并后对 memory/docs 逐个**回读校验**双方章节都在，必要处手工做语义联合 |
| 本地主干分支（`dev`/`main`）引用很旧 | 用 `--pull-all`：`git fetch origin <b>:<b>`（无 `+`）**不改工作区、不切分支**，只快进「只落后」的分支。**注意它不改当前分支的代码** ⇒ 别把「主干快进了」误报成「我的分支更新了」 |
| `有未提交改动，先提交或 stash 再拉` | 先跑 `-m` 提交，或 `git stash` 后拉、再 `git stash pop` |
| `git checkout <分支>` 报 `Your local changes … would be overwritten by checkout` | 这是**切分支**、不是 merge ⇒ 脚本的 worktree 隔离方案**不覆盖**。走「切分支被本地改动挡住」小节的**保命三步**：`git switch -c wip/<topic>` 承接改动 → `-m "wip: …" --paths "<...>" --no-push` 提交 → `git switch -c <br> origin/<br>` 建本地跟踪分支。**别 `git checkout -f` / `git checkout -- .`**；也别 `git checkout origin/<br>`（detached HEAD，提交易丢） |
| `merge 冲突，需人工解决` + 冲突文件列表 | 打开冲突文件做**联合合并**（双方内容都保留、别整段取一边），`git add` 后 `git-fast.sh --push-only` |
| `Your local changes ... would be overwritten by merge`（在途文件挡住 merge） | **不要 stash、不要 checkout**（会吞掉并行会话未提交的工作）。脚本已自动改走 worktree 隔离推送；若打印 `worktree 内 push 仍被拒` ⇒ 远端又动了，直接重跑脚本即可。手工备选：`git worktree add --detach <tmp> origin/<br> && git -C <tmp> merge <本地HEAD> && git -C <tmp> push origin HEAD:<br>`，完成后 `git worktree remove <tmp>`。**判据：主工作区 `git status` 行数与操作前一致** |
| `untracked working tree file would be overwritten by merge`（**该文件尚未被跟踪**） | 与上一行要区分：这不是「在途改动」，而是**远端新增了某路径、本地同名文件还没入库**（`.workbuddy/memory/*.md` 日志目录最常见，双方各自在追加当天日志）。**worktree 方案解决不了**。正确处置 = **先把远端版本内容并入本地文件（并集）→ `git add` → 提交 → 再 merge**；随后 `git merge` 必然在该文件报 **add/add** 冲突，按并集（此时 ours 已含远端内容，取 ours 即可）解决 |
| 想把「更新+提交」压成一条命令 | 只有**无真冲突**时 `git-fast.sh -m "msg" --paths ...` 才够用；一旦有真冲突，脚本的 fetch+merge 重试会中止。正确姿势：`-m "msg" --paths ... --no-push` 先落提交 → 手工 `git merge origin/<br>` → 解决冲突 → `git commit --no-edit` → `--push-only` |
| `Your local changes ... would be overwritten by merge`（挡住的文件是**已跟踪 + 只改本地不提交**的运行态配置，如 `deploy/.env.dev`） | 先判远端这轮动没动它：`git diff --name-only HEAD origin/<b> -- <file>`。**为空** ⇒ 该文件不该挡住 merge（脚本会自动处理；手工则 `cp` 备份 → merge → 回填）；**非空** ⇒ `git merge` 必中止，正解 = `git diff -- <file> > /tmp/p.patch` → `git checkout -- <file>` → `git merge` → `git apply --3way /tmp/p.patch`（前提：远端新增行与本地被覆盖行**不相邻**，补丁才能干净应用，两方改动都保住）。**别 `git stash`**（会吞掉并行会话的在途文件）。**更省事的先手判定**：动手前先比「**非注释行的 key=value**」（工作区版 vs `git show origin/<b>:<file>`）—— 若键集与取值完全相同（只有注释文字不同，本仓常见）⇒ 直接 `git checkout -- <file>` 丢弃本地覆盖即可，**不必走补丁回放**；合并后再确认运行态取值仍是目标值即可 |
| 用完 `git apply --3way` 之后 | ⚠️ 它**会顺手把改动写进 index**（`git status` 首列出现 `M `）。若该文件属「只改本地不提交」⇒ 提交前必须 `git restore --staged <file>`，否则 `.env*` 会被裹进提交、推送门禁直接吃掉这次提交 |
| 脏文件挡住 merge，但**它的内容恰好就是远端版本**（最常见：运行态覆盖过的 `deploy/.env.dev`，远端也正好把同一行改成了同一值） | 这是上两行的**零风险特例**，一行判定即可：`git hash-object <worktree-file>` == `git rev-parse origin/<b>:<file>`（blob 相同 ⇒ 字节相同）。处置 = `cp` 备份 → `git checkout -- <file>` 彻底释放工作区 → `git merge origin/<b>` → 用 **`git hash-object` 现文件 + `cmp 备份 现值`** 双证确认落盘内容与备份逐字节一致。**不必打补丁、不必 stash、不必回填**；出站再用 `git diff --stat origin/<b> HEAD -- '<path-glob>'` 确认**没有向远端引入任何新 `.env` 内容**（为空即证）。 |
| 想知道「远端这轮到底改没改某个文件」 | ⚠️ **别只看 `git log HEAD..origin/<b> -- <path>`**：它带 TREESAME 历史简化，对**确实被改过**的文件可能返回**空**（2026-10-09 实测 `deploy/.env.dev`：`git log` 空、`git diff` 有差异）。可靠三法：① `git diff --name-only HEAD origin/<b>`（全量清单）；② `git diff HEAD origin/<b> -- <path>`；③ 直接比 blob —— `git rev-parse HEAD:<path>` vs `git rev-parse origin/<b>:<path>`。需要完整历史时加 `--full-history`。 |
| push 被拒 → merge → push **又**被拒 | 并行会话活跃时这是**常态而非异常**（同一份 `YYYY-MM-DD.md` 日报每轮必撞 content 冲突）。按「提交 → merge → 双方都保留 → 脚本集合差集双向 0/0 校验 → 合并提交 → push」循环重跑即可，不要怀疑流程；**一次 push 成功是例外** |
| 冲突解决完，怎么证明「远端内容没被吃掉」 | 别用 `sed` 抽段 + 目测 diff（边界行错位会报**假差异**）⇒ 写脚本做集合校验：远端侧文件的**非空行集合 ⊆ 合并结果**（Python 集合差集），打印缺失行数；对改写过的判据则校验**关键词覆盖**。结论用脚本输出，不用人眼。**另有一条覆盖全仓的整体判据**：合并提交后跑 `git diff --name-only origin/<br> HEAD` —— 若输出的文件恰好就是「本轮自己改过的那几个」，即一次性证明远端**全部**代码/配置改动已逐字落盘（无旧版整段盖回）；比逐文件目测可靠得多，且能顺带发现「merge 后误把某个远端文件回退」 |
| 全仓扫「冲突标记」报出 1 处、但精确路径看着可疑 | 先看**路径是否在打包产物目录**：本仓 `pig-pc-ui/desktop/release/**`（Electron `*-arm64.app`、`.asar`、`.dylib`）内的二进制会含 `<<<<<<< ` 字节序列 ⇒ **恒定假阳性**。扫描时把 `pig-pc-ui/desktop/release` 连同 `node_modules`/`dist`/`build`/`target`/`.git` 一起排除，并对命中做**扩展名过滤**（只信 `.vue/.ts/.js/.java/.py/.sql/.md/.json/.yml`），才可下「0 冲突」结论 |
| `重试 N 轮仍被拒` | 有人在持续推同一分支：先 `git log --oneline HEAD..origin/<分支>` 看对方在做什么再决定 |
| `提交失败` | 多因 hook 拦截（commit-msg 校验等），按 hook 提示改后重跑 |
| `无内容可提交` / `已是最新` | **先分两种，别一律当空操作**：① 体检段「未推送: 0 个」⇒ 真空操作，**如实告知用户，不要为了「有产出」硬造提交或假报同步**；② 体检段显示「**未推送: N 个**」⇒ 工作区为空但**已有本地提交待推**（并行自动化/另一会话**已经替你 commit 了**，本仓 `.workbuddy/memory` 类自动化每轮 `add -A` 极易发生）⇒ 脚本照常 push 是**正确行为**，但要**回读核对该提交内容 == 本次改动**（`git show --stat <sha>` + `git ls-tree -r --name-only <sha> -- <你的路径>`），确认「无夹带」再向用户宣称已提交（2026-10-09 实测：`03e23a9e` 28 文件、`d98fa9c4` 1 文件，均与本次改动逐字一致） |
| 脚本**整条调用没有任何回显 / 返回空输出**（看不到 `== 完成 ==`，更看不到 `推送成功`） | ⚠️ 这是**静默半程**：`提交完成` 可能已落库、`push` 那一步却没跑。**绝不能凭「提交完成」推定已推送**。一行复核即可定案：`git rev-list --left-right --count HEAD...origin/<b>`（左侧 >0 = 有本地提交未推）或 `git ls-remote origin <b>` 对比 `git rev-parse HEAD`。实测 2026-10-16：`2d34e982` 已提交、`origin/dev` 仍停在 `79267007`（1/0），补一次 `git push origin dev` 才真正落地。⇒ **每轮收尾固定做「三方核对」：`git rev-parse HEAD` == 本地 `origin/<b>` == `git ls-remote origin <b>`**（`git rev-list` 只反映本地 remote-tracking ref，必须靠 `ls-remote` 直连远端才算数）|

## 配套：启用脱跟踪复检

在仓库根放 `.git-fast.conf`，每行一个「必须保持未跟踪」的路径或 glob，`#` 开头为注释：

```
# 必须保持未跟踪（会被 dev 侧合并反复带回版本库）
python-ai-service/.env
```

体检时会逐条报 `未被跟踪 v` 或 `已被跟踪 x`。

## 维护注意

- **同一文件不要在一次消息里并发下多个 Edit**：实测会出现「工具报成功但内容没落地」
  （多个 Edit 各读旧快照再写回，后写者覆盖前者）。改同一文件时**逐个改、改完回读校验**。
- 脚本头部的 `# ---` 之后是维护注释，`--help` 只打印 `# ---` 之前的部分。
- bash 坑：双引号里**中文全角字符紧跟在 `$VAR` 之后会被并入变量名**（`"$PATHS）"` ⇒ `set -u` 报
  unbound variable）。变量后紧跟中文/全角符号时一律写 `${VAR}`。
- **`--paths` 只吃一个参数**：多个路径要用**同一对引号、空格分隔**（`--paths "a.md b.md"`）。
  写成两个独立参数（`--paths a.md b.md`）脚本会把第二个当未知参数，报
  `未知参数: b.md（-h 看用法）` —— 见这条报错直接改引号，别去翻路径是不是写错了。
- 🔴 **`--paths` 里不要放「已经被 `git rm` / 已经不存在」的路径**（2026-10-15 实测）：
  脚本内部是 `git add -- <paths...>`，其中一条 pathspec 匹配不到任何文件会让**整条 add 失败**
  （`fatal: pathspec 'x' did not match any files`），于是**只有先前已暂存的内容进了提交** ——
  表现是「提交成功但只改了 1 个文件」，剩下的修改仍留在工作区（` M` 未暂存）。
  判据 = 提交后立刻 `git status --porcelain`；非空就再补一次提交（只列仍存在的文件）。
  删除文件用 `git rm` 先暂存好，`--paths` 里**不必**再列它。
- 🔴 **「已暂存删除 + 同路径未跟踪副本」= `git rm --cached` 痕迹，提交前必须验远端（2026-10-16 实测）**：
  工作区同时出现 `D <path>`（已暂存删除）与 `?? <path>`（同路径未跟踪）时**先别提交** —— 用
  `git cat-file -e origin/<branch>:<path>` 逐个验证；若远端**仍有**该文件，说明它是「上游要保留」的，
  提交这条删除等于把远端刚补回的文件再删掉（本仓实测：20 个暂存删除全部命中此坑）。
  修法：`git reset --hard origin/<branch>` 让路（文件回位），再只提交真正属于自己的改动。
  判「能否安全重置」：`git diff --name-status <local-tip> origin/<branch> | awk '$1=="D"'` ——
  **输出为空即远端严格超集 ⇒ 重置零损失**（再配一条「非删除类改动 diff 为空」的抽样即可结案）。
- 🔴 **「已跟踪目录被 `rm` 直删 + 同族新目录出现」= 换代重构在途，先存 tar 再决定（2026-10-16 实测）**：
  工作区出现 ` D <dir>/…`（**仅工作区删除、索引未动**，注意状态位是「空格+D」而非「D+空格」）并伴随一个 `?? <newdir>/` 时，用**三问**定性：
  ① 被删目录的原始来源是否仍在（本轮：`backup/20261015/` 三库原始 dump 未动）？
  ② 新目录是否与被删目录**同源**（强旁证：`git commit` 输出会自行报 `rename 旧/a.sql => 新/b.sql (99%)`）？
  ③ `ls ~/.Trash` 是否为空（**为空 ⇒ 是 `rm` 直删、无系统回收站兜底**）？
  三问齐 ⇒ 内容可重生成、可回滚，才可把该删除随「提交所有变更」入库；**动手前必存 tar**：
  `git archive HEAD <path> -o $HOME/.linmo-bak/<name>.tar && tar -tf <tar> | wc -l`（与 `git ls-tree -r --name-only HEAD <path> | wc -l` 对上才算保住）。
  回滚 = `tar -xf <tar> -C <repo-root>` 或 `git revert <commit>`。
  反例提示：若新目录**无法独立再生**（脚本/源数据也一并被删），则该删除**不得**随手提交。
