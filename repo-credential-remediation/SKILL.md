---
name: repo-credential-remediation
description: 把「真实凭据进入版本库」这类问题**从诊断修到零残留并验证**的闭环 —— 脱跟踪含密 env、模板脱敏、去掉 compose/config 里的真值兜底、脚本硬编码改环境变量、脱敏历史日志、修 .gitignore 失效，最后用同一套扫描器复跑对比。当用户说「修复这些安全问题」「把密钥清理掉」「这些凭据问题逐个修掉」「修复本地代码合并问题」并已有一份凭据清单时使用。也覆盖「远端已前移 + 有并行会话在改文件时如何安全合并推送」。
agent_created: true
---

# 凭据入库问题 —— 修复闭环

**前置**：已有一份凭据问题清单（通常来自 `repo-source-scan`）。本技能负责**动手修 + 验证**。

## 0. 铁律

1. **处置顺序不可逆：轮换密钥 → 脱跟踪 → 清历史。** 顺序反了等于白做。
   轮换与历史清洗**永不擅自执行**——前者要改线上配置、后者要全员重新 clone。只做「工作区/索引层」的修复并明确告知。
2. **`git rm --cached`，不是 `git rm`**。目标是「移出版本库、保留本地文件」，删掉本地文件会打断正在跑的开发环境。
3. **动手前先备份 + 记录跟踪状态**：`mkdir -p /tmp/<repo>-env-backup && cp -p <files> …`；`git ls-files --error-unmatch <f>` 逐个确认。
4. **不做「一刀切」**。同一个字符串在不同位置风险完全不同（见下「三档分类」），先分类再动手。

## 1. 三档分类（决定怎么修）

| 档 | 特征 | 处置 |
|---|---|---|
| **A 真凭据** | 第三方 App/API Key、平台 `sk-`、控制台口令、加密根口令（jasypt/AES/JWT）、DB 账号口令、内部服务令牌 | **必须移出仓库或改占位符**；脚本改读环境变量 + 缺值 fail-fast |
| **B 公开约定值** | 被烘焙进前端产物的对称键（`VITE_*` 与后端同名同值）、上游同名的 OAuth client（`id:id`） | **不删值**：文档标注「开发约定值、非生产密钥、生产必须覆盖」，扫描器白名单登记并打印 |
| **C 上游模板** | 第三方官方仓库的 `.env.example` 副本（如 Dify 的 `difyai123456`） | **原样保留**，扫描器按目录排除并单列一条 |

## 2. 五类载体与各自修法

### ① 含密 env 文件（`.env` / `.env.dev` / `.env.head` / `.env.mac`）
```bash
mkdir -p /tmp/<repo>-env-backup && cp -p deploy/.env.* /tmp/<repo>-env-backup/   # 先备份
git rm --cached deploy/.env.dev deploy/.env.head deploy/.env.mac deploy/dev/.env  # 保留本地
```
- `.gitignore` 里**原本就有规则也要做这一步** —— 规则对**已跟踪**文件无效，这是最容易被忽略的坑。
- 补 `.gitignore` 缺失的规则（本次缺 `.env.head` / `.env.mac` / `docker/.env` / `dify-docker/.env`）。

### ② 模板文件（`.env.example` / `.env.template`）
模板**继续入库**，但**只放占位符**。改法：
- 真值 → `<set-me>` / `<your-host>` / `{}` / 空
- 顺手纠正模板头部的错误自述（本次模板头部写着「本文件含真实密钥，不要提交」，与它被 `!` 白名单放行的事实矛盾）
- ⚠️ 改完要**回读**：模板是「变量契约」，漏一个键会让新机器起不来。
- ⚠️ 如果某个值删掉会让本地开发环境中断（如 python-ai 的 admin 端点口令），
  要**同时**把真值补进那个**未跟踪**的 `.env.dev`，并在 `.env.example` 里补同名占位符。

### ③ compose / 配置里的「真值兜底默认值」
```yaml
# 改成不泄密且不破坏解析的写法
DIFY_APP_KEYS: ${DIFY_APP_KEYS:-{}}      # 空 map ⇒ 日志明示未配置，比拿着失效 Key 收 401 好定位
MYSQL_PASSWORD: ${MYSQL_PASSWORD:-change-me}
```
- **慎用 `${VAR:?必填}`**：`docker compose` 的**任何**子命令都会做插值，
  加了 `:?` 会让「只停其中几个服务」的运维命令也报错。
- 若确实需要 `:?`（如内部令牌），要**同步更新文档里记录的命令**（补 `--env-file`），否则会静默打断既有流程。
- 改完必须 `docker compose -f <f> config` 复验；对有 `:?` 的文件要**带 `--env-file` 再验一次**。
- 若兜底值被写死是为了兜「重装脚本把 .env 覆盖掉」⇒ 那是**部署脚本该修**（备份+合并），
  不能靠往版本库塞密钥来兜——在注释里写清这一点。

### ④ 脚本 / 代码里的硬编码凭据
```python
X = os.environ.get("X", "")
if not X:
    sys.stderr.write("❌ 缺少 X 环境变量（真值见 deploy/.env.dev）\n"); raise SystemExit(2)
```
- **必须 fail-fast + 提示取值来源**，不能静默用错值。
- 记得补 `import os`（`assert` 式检查：`grep -qE '^import os$'`）。
- Windows `.bat` 里从 `%PY_APP%\.env` 读：用 `for /f "usebackq eol=# tokens=1,* delims=="`。
  ⚠️ 写 `.bat` 必须 `encode('gbk')` 校验后再 `write_bytes`（见 `repo-source-scan` 的工程纪律）。

### ⑤ 历史日志 / 文档 / 记忆文件
按字面量逐条脱敏（`app-****（已脱敏）`），**保留「这里原本有个 key」的信息**而不留值。
注意：这类文件常被**并行会话**同时追加 ⇒ 提交前用「删除行是否 100% 含密钥字面量」判定是否可安全提交：
```python
removed = [l[1:] for l in diff.split('\n') if l.startswith('-') and not l.startswith('---')]
pure = removed and all(any(s in l for s in SECRETS) for l in removed)
```

## 3. 验证（缺一不可）

```bash
# 每类凭据都要复扫，期望 0
for p in '<真 key>' '<控制台口令>' '<DB 口令>' '<内部令牌>'; do
  echo "$p → $(git grep -lF "$p" | wc -l)"
done
python3 tools/source_scan.py                      # 复跑体检，P0 应归零
python3 -m compileall -q <svc> tools             # 语法
python3 tools/check_python_ai_imports.py          # 导入门禁（若适用）
docker compose -f <f> config                      # 解析
bash -n <每个改动的 shell>
```
- **有第三方模块缺失时用桩模块验证 fail-fast**，别因为 `ModuleNotFoundError` 就跳过验证：
  ```python
  import sys, types, runpy
  m = types.ModuleType('pymysql'); m.connect = lambda **k: None; sys.modules['pymysql'] = m
  sys.argv = [sys.argv[1]]; runpy.run_path(sys.argv[1], run_name='__main__')
  ```
- **改过 SQL 里的 `md5` 列**（Nacos 配置表）必须**先对未改动的行做 md5 自洽校验**确认算法，
  改完再验一次（本例：md5 = 内容原文反转义后的 UTF-8 md5，7/7 自洽）。

## 4. 并行会话在场时如何安全提交 / 推送

**症状**：`git push` 被拒 → 自动 merge 报 `Your local changes to the following files would be overwritten by merge`，
而那个文件是**别人正在改的**。

**❌ 不要**：`git stash` / `git checkout --` / `git add -A` —— 任何一种都会动到对方的在途工作。

**✅ 用临时 worktree 在干净副本上合并后推送**（主工作区零改动）：
```bash
git fetch origin <branch>
git worktree add --detach /tmp/sync-wt origin/<branch>
cd /tmp/sync-wt && git merge --no-edit <my-commit>     # 干净副本上不会有本地修改挡住
git push origin HEAD:<branch>
cd - && git worktree remove /tmp/sync-wt && git worktree prune
```
- 推送前先 `git diff --stat HEAD...origin/<branch>` 看远端改了哪些文件，判断冲突面。
- 推送后 `<branch>` 的本地 ref 仍停在旧提交（这是正常的「落后」状态），对方的在途文件毫发无损。

**只提交自己的改动**：`git status --short` 里先按文件名/内容判断归属，
再用 `git-fast.sh --paths "<空格分隔的路径>"`（它执行的是 `git add -- <paths>`，不会 `add -A`）。
已经 `git rm --cached` / `git mv` 过的条目保持已暂存状态会被一起提交——这正是想要的。

## 5. 交付时必须说清的「未做项」

| 项 | 为什么不做 | 给用户的下一步 |
|---|---|---|
| 密钥轮换 | 要改线上/第三方控制台配置 | 列出每个待轮换的键 + 影响面 |
| 历史清洗 | 重写共享历史，全员要重新 clone | 说明必须先轮换，且要团队协调 |
| mock→真接口（伪功能） | 需要后端契约，属功能开发 | 标注「看着能用但没落库」的具体页面与动作 |
| 超长文件拆分 / 三端漂移甄别 | 重构范畴，回归面大 | 给数量与样例，排期处理 |
