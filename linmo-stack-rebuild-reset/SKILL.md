---
name: linmo-stack-rebuild-reset
description: 灵猫企管（linmo-pig-full）本机 Docker 全栈的「重新打包 + 重置数据库 + 重启服务 + 探活验证」闭环。当用户说「重新打包」「重置数据库」「清库重来」「重启服务」「服务起不来」「重新构建镜像」「初始化数据库」「initdb 重放」「让新代码立即生效」，或重置后页面「数据没更新 / 经营总览是空的 / 事项中心全 0 / 数据停在旧日期」，或需要在本地把 pig-boot/pig-ui/pig-pc-ui/python-ai/mysql/redis 全栈从干净状态重建并验证可用时使用。覆盖：① 增量判断（先决定到底要不要重建/重置，别盲目全量重跑）；② 镜像重建（含 pcui profile 陷阱与 docker-credential PATH 修复）；③ 数据库重置（**重置前必做「一次性容器 initdb 预检」——抓 ORDER 撞序导致的 `ERROR 1146` 与位置化 INSERT 列数不匹配的 `ERROR 1136`，见 §2.0** → 备份 → 删卷 → 手建 mysql 容器 → initdb 重放 → 校验）；④ 重置后五件必做收尾（回灌 ops_*/pig_dw 运行时业务数据 + 启动 Quartz 定时任务 + 重生成模拟数据域 + 回灌 ai_app_config/快照 + 复核权限点-角色绑定，漏做则数据不更新 / 配置丢失 / 页面报无权访问）；⑤ compose 拉起 6 容器；⑥ 端到端验证（含 PIG 登录密码 AES 加密）；⑦ 报告与记忆落盘。
agent_created: true
---

# 灵猫企管全栈：重新打包 / 重置数据库 / 重启服务

## 0. 本机拓扑（先记住，别靠猜）

| 项 | 实际值 |
|---|---|
| 编排 | compose 工程 `linmo-pig` → `deploy/docker-compose.dev.yml` |
| 启动参数 | `--env-file deploy/.env.dev --env-file deploy/.env` + **`--profile pcui`** |
| docker 客户端 | **`/Applications/Docker.app/Contents/Resources/bin/docker`**（唯一可靠路径，见下方坑） |
| 构建前必备 | `export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"`（否则报 `docker-credential-desktop not found`） |
| MySQL | **手工 `docker run` 的容器**（仅 dev 编排如此；私仓镜像版编排里 mysql 是 compose 服务 `deploy-mysql-1`，见 §0.0b），卷 `linmo-mysql-data`，网络别名 `mysql`，root 口令 `root`。镜像：**唯一链路 `linmo/pig-mysql:8.0`**（`pig/db/Dockerfile` —— 2026-10-14 起 `pig/db` 下是 **6 个「保序切段」合并脚本** `01~06*.sql`，源脚本与依赖顺序在 `pig/db_bak/`）。⚠️ 旧的 `linmo/pig-mysql-merged:8.0` 已废弃 |
| 端口 | 3306 / 6380(redis) / 9999(boot) / 8090(ai) / 8888(ui) / 8890(pc-ui) |

### 🔴 0.0 先确认你操作的是哪个副本（2026-10-12 实测，差点在错目录上重建）

本机同时存在 **4 个 linmo-pig-full 克隆**，Docker 栈只认其中一个：

| 目录 | 分支 | 是不是 compose 工作目录 |
|---|---|---|
| **`/Users/shan/work/linmo-pig-full`** | **`dev`**（2026-10-15 复核；`feature/liyuying-client` 已于 10-14 回退） | ✅ 是（本文所有命令都在此执行） |
| `/Users/shan/works/linmo-pig-full` | **`dev`** | ❌ 非 compose 工作目录，但是**活跃开发副本 / 记忆主目录**（`pig/db` 收敛 6 合并脚本、三端死文件清理等都出自这里） |
| `/Users/shan/dev-full/linmo-pig-full` | `liyuying-full` | ❌ |
| `/Users/shan/work/pig/linmo-pig-full` | `main` | ❌ |

### 🔴 0.0b 两套编排 ⇒ 两套容器名（2026-10-15 实测，本文正文命令按「dev 编排」写）

| 编排 | 容器名 | 说明 |
|---|---|---|
| `deploy/docker-compose.dev.yml` | `linmo-mysql` / `linmo-redis` / `linmo-pig-boot` / `linmo-python-ai` / `linmo-pig-ui` / `linmo-pig-pc-ui` | **本文正文默认这套** |
| `deploy/docker-compose.yml`（及个人拷贝，**私仓镜像版**，只拉镜像不 build） | **`deploy-<svc>-1`**：`deploy-mysql-1` / `deploy-redis-1` / `deploy-pig-1` / `deploy-python-ai-1` / `deploy-nginx-1` / `deploy-nginx-pcui-1` | 项目名 = 目录名 `deploy`；**不发布 redis/mysql 宿主端口** |
| `deploy/docker-compose-liyuying-v1.yml`（**一体化 / 本地构建版**，`name: linmo-pig`，4 处 `build:`，**零 TAG**） | 同 dev 版：`linmo-redis` / `linmo-pig-boot` / `linmo-python-ai` / `linmo-pig-ui` / `linmo-pig-pc-ui` / `linmo-env-applier` | ⚠️ **历史旧名是点号版 `docker-compose.liyuying-v1.yml`**（`git log --follow` 可证 e4abb694/f9cefead 曾用该名）；有人给的命令写旧名时**要映射到连字符版**——判据：该文件消费 `${DIFY_DB_DSN:-}`/`${DIFY_CONSOLE_PASSWORD:-}` 与 `--build`、不引用 `${TAG}` |

### 🔴 0.0c v1 一体化版**不自带 mysql** ⇒ 必须先 bootstrap 发布栈的 `deploy-mysql-1`（2026-10-15 实测）

v1 编排的 mysql 服务是**注释掉的**：它靠 external 网络 `deploy_backend` 直连发布栈的 `deploy-mysql-1`
（`MYSQL_HOST: ${MYSQL_HOST:-deploy-mysql-1}`、`ADMIN_MYSQL_HOST` 同）。所以：

```bash
cd deploy
# ① 先起 mysql（发布编排，项目名 deploy ⇒ 容器 deploy-mysql-1；卷 mysql-data 显式 name=linmo-mysql-data，复用不建空库）
docker compose --env-file .env.liyuying --env-file .env -f docker-compose.yml up -d mysql
# ② 再起 v1 一体化栈
docker compose --env-file .env.liyuying --env-file .env -f docker-compose-liyuying-v1.yml up -d --build
# ③ 本机约定要带 PC 端（`--profile pcui`，v1 里 pig-pc-ui 也在该 profile 下）
docker compose --env-file .env.liyuying --env-file .env -f docker-compose-liyuying-v1.yml --profile pcui up -d --build pig-pc-ui
```

⚠️ **引擎重启后 `docker ps -a` 可能全空**（容器与 compose 项目都没了，但卷/镜像还在）⇒
此时 v1 单独 `up` 必然让后端连不上库；务必先做 ①。判据：`docker ps -a` / `docker compose ls -a` 均为空、`docker network ls` 里 `deploy_backend` 仍在。
⚠️ `deploy/.env` 里的 `TAG` 只有**镜像版**消费，但 ① 的 `${TAG:-54}DB` 也要它 ⇒ 起 mysql 前先确认 `TAG=267`（54 已失效）。
⚠️ 用户给的 `>> .env` 追加命令若键已存在会造成重复行 ⇒ 先 `sed -E 's/=.*/=<hidden>/' .env` 看现状，**已存在就别再追加**。

### 🔴 0.0d DB 卷被重建后：**别在 initdb 导入完成前读 information_schema**（2026-10-15 实测，差点误报「数据丢失」）

`267DB` 镜像自带 `/docker-entrypoint-initdb.d/zz-import-all.sh`，会在**临时服务器**里依次导入
`/opt/pig-db/{01..06}*.sql` 共 6 个合并脚本（日志形如 `[pig-initdb] [4/6] 04_agents_business.sql`）。
这段导入通常耗时 **25~40s**；`docker compose up -d` 主服务**不等它**，所以：

```bash
# ✅ 唯一可靠的「库已完整」判据：等这条日志
docker logs deploy-mysql-1 2>&1 | grep '初始化完成'
# [pig-initdb] 初始化完成：成功导入 6 个脚本，拒绝 0 个
# 之后才会打印 ready for connections (port 3306)
```

❌ 反面案例（2026-10-15）：容器 15:55:53 起、15:55:56 读 `information_schema` 得到
「178 表 / sys_menu 392 / **无菜单 9911** / `sys_db_migration` 0 行」，据此判定「旧库被清、数据丢失」，
并开始找备份；实际 15:56:30 导入完成，最终 **257 表 / sys_menu 477 / 菜单 9911 在位 / ai_app_config 62 行**。
⇒ **中途态与「空库」在早读时无法区分**，一律先等 `初始化完成` 日志（或 `information_schema` 表数连续两次读数稳定）。
⚠️ 顺带：`docker volume inspect <卷> --format '{{.CreatedAt}}'` 只说明卷被重建过，**不等于数据丢失**——
数据来源是**镜像里的 initdb 脚本**，不是旧卷。

### 🔴 0.0e 全库被外部清理（镜像 0 个 / 卷被 prune）后的自愈（2026-10-15 实测）

现象：`docker images` **0 个**、`docker volume ls` 断崖式减少、`docker ps -a` 空，但
**Build Cache 仍在**（`docker system df` 里 65GB/1380 条）⇒ `up -d --build` 依然全 CACHED、秒级完成。
用 `docker events --since 40m --until 1s --filter type=volume` 可取证是**谁在何时 destroy 的**（本机实测
是他项目卷 + 匿名卷成批 destroy，与本会话命令无关 ⇒ 并行会话/用户手动的 Docker Desktop 清理）。

此时需要**重新拉基础镜像**（本仓库走 `docker.m.daocloud.io/library/`，daocloud 会间歇 502）：

```bash
# 7 个基础镜像：maven:3.9-eclipse-temurin-17 / eclipse-temurin:17-jre / node:22-alpine /
#              nginx:1.27-alpine / python:3.11-slim / redis:7-alpine / docker:27-cli
docker pull -q docker.m.daocloud.io/library/<img>          # 先试 daocloud，失败再换源
# 备用源（实测可用，按需换）：
#   hub.rat.dev/library/<img>        ← redis:7-alpine 实测 OK
#   docker.1ms.run/library/<img>     ← docker:27-cli 实测 OK（hub.rat.dev 对该镜像 403）
#   docker.nju.edu.cn / docker.1panel.live / dockerproxy.net 可达但实测解析失败
# 拉到后**改回 compose 期望的 tag**（compose 只认 ${REGISTRY:-docker.m.daocloud.io/library/}）：
docker tag hub.rat.dev/library/redis:7-alpine docker.m.daocloud.io/library/redis:7-alpine
```
- daocloud 的 `502 Bad Gateway` 常见于 **referrers API**（`.../v2/library/redis/referrers/...`）⇒ 层其实已下载、
  只差清单校验，**重试 2~4 次常能过**；持续失败再换源。
- ⚠️ 报 `no matching manifest for linux/arm64/v8` 的是**私仓 267 系列**（amd64-only）⇒ 必须
  `docker pull --platform linux/amd64 192.168.110.172:8443/team/linmo-pig:267DB`。

### 🔴 0.0f 「基线库 vs 备份」量化差异 ⇒ 决定要不要恢复（2026-10-15 实测）

DB 卷重建后库 = **镜像基线**（6 个合并脚本的种子数据），**不含 runtime 追加数据**
（用户建的账号/菜单、控制台填的 Dify App Key、`ai_usage_log` 等）。本仓在 `backup/YYYYMMDD/` 留过
`pig<日期>.sql` 全量 dump，可用来量化缺口：

```bash
# 备份内各表行数（mysqldump 一行一表 extended insert ⇒ 数 "),(" 个数 +1）
python3 - <<'PY'
import re
p='backup/20261014/pig20261014.sql'
want=['sys_user','sys_role','sys_menu','sys_job','ai_app_config','ai_usage_log']
found={}
for line in open(p, encoding='utf-8', errors='ignore'):
    m=re.match(r'INSERT INTO `([a-z_0-9]+)`', line)
    if m and m.group(1) in want and m.group(1) not in found:
        found[m.group(1)]=line.count('),(')+1
print(found)
PY
# 运行库同口径
docker exec deploy-mysql-1 sh -c 'mysql -uroot -proot -N -e "use pig; select count(*) from sys_user;"'
```

实测对照（2026-10-15）：基线与 11:51 dump 的差距 = `sys_user` 1/3、`sys_role` 2/3、`sys_menu` 477/497、
`ai_app_config` 62/81（enabled 12、有 key 7）、`ai_usage_log` 0/1140。
⇒ **恢复属于「改数据」的决定，必须让用户拍板**；给出命令而不是直接跑：

```bash
# 恢复（幂等性由 dump 内的 DROP TABLE IF EXISTS + CREATE TABLE 保证）
docker exec -i deploy-mysql-1 sh -c 'mysql -uroot -proot pig' < backup/20261014/pig20261014.sql
# 再重放基线之后的迁移（否则源码超前 schema ⇒ /admin/internal/ai-config 500）
docker exec -i deploy-mysql-1 sh -c 'mysql -uroot -proot pig' < pig/db_bak/ai/ai_model_config_key_20261014.sql
docker exec -i deploy-mysql-1 sh -c 'mysql -uroot -proot pig' < pig/db_bak/kb/kb_workspace_20261014.sql
# 重启受影响的消费端（python-ai 30s 轮询也会自愈，重启更快）
docker compose --env-file .env.liyuying --env-file .env -f docker-compose-liyuying-v1.yml up -d --force-recreate --no-deps pig-gateway python-ai
```

🔴 **动手前先自动判容器名，别写死**（本轮实测：裸用 `linmo-python-ai` 会报 `No such container`）：

```bash
docker ps --format '{{.Names}}' | grep -E 'python-ai'    # 取实际名，后续命令代入
# 或按服务名 / 镜像名自动解析：
docker ps --format '{{.Names}}\t{{.Image}}' | grep 'python-ai'
```

⚠️ 两套编排下 `redis://127.0.0.1:6380` 只有 dev 版可用；私仓版必须走 `docker exec deploy-redis-1 redis-cli -n 5`。详见记忆 `topics-deploy-git-frontend.md §S8`。

🔴 **私仓版的三个 Mac 侧硬约束（2026-10-15 实测）**：

1. **镜像 amd64-only ⇒ 拉取必须带 platform**。裸 `docker pull 192.168.110.172:8443/team/linmo-pig:<TAG>{UI,PCUI,AI,DB}` 在 Apple Silicon 上必报
   `no matching manifest for linux/arm64/v8 in the manifest list entries`（**不是**网络/认证问题，别去查 registry）。
   正确写法：`docker pull --platform linux/amd64 <img>`（compose 内已为各服务声明 `platform: linux/amd64`，所以 `up -d` 用本地镜像即可）。
   返回 `Image is up to date` 即该 TAG 无更新构建 —— 想确认「私仓有没有新代码」用这招，比看镜像时间戳准。
2. **`.env` 必须显式给 `REDIS_URL=redis://redis:6379/0`**（容器服务名）。该编排不发布 redis 宿主端口，
   缺它就会落到 `deploy/.env.liyuying` 里的宿主机值 `redis://192.168.110.19:6380/0` ⇒ 容器内不可达（实测 6380 无监听），
   python-ai 的用量上报 / 配置缓存**静默失能**。判别：`docker logs deploy-python-ai-1 2>&1 | grep 'redis connected'`，应打印 `redis connected: redis://redis:6379/0`。
3. **升级动作**（私仓版个人拷贝，项目名固定 `deploy`、与文件所在目录名同名 ⇒ 换克隆目录也不会丢数据卷）：
   ```bash
   cd <clone>/deploy
   cat > .env <<'EOF'          # 覆盖前先 cp 备份：deploy/.env 是被 gitignore 的运行态文件
   TAG=<n>
   DIFY_DB_DSN=postgresql://postgres:<pw>@192.168.110.172:5433/dify
   DIFY_CONSOLE_PASSWORD=<pw>
   REDIS_URL=redis://redis:6379/0
   EOF
   docker compose --env-file .env.liyuying --env-file .env -f docker-compose.liyuying.yml up -d
   ```
   `--build` 对该文件是**空操作**（无 build 段，只拉镜像）；`up -d` 会**保持未变更的服务 Running**（实测 `deploy-pig-1`/`deploy-mysql-1` 不被重建），
   只重建 redis / python-ai / 两个 nginx。数据卷名是 `linmo-mysql-data` / `linmo-redis-data`（固定名，不随项目名变化 ⇒ 安全）。

🔴 **运行栈与源码改动必须同分支**：2026-10-14 起两个副本**都是 `dev`**（旧的「运行栈在 feature、改动在 dev」场景已终结）。仍要**重建前先判是否落后**，否则只重建不合并 ⇒ 镜像里仍是旧代码：

```bash
cd /Users/shan/work/linmo-pig-full
git branch --show-current                        # 必须是 dev
export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH
GIT_SSH_COMMAND="ssh -o UseKeychain=yes -o IdentitiesOnly=yes -i /Users/shan/.ssh/pub -o BatchMode=yes" \
  git fetch origin --prune
git rev-list --left-right --count HEAD...origin/dev   # 「0 0」= 已同步；左>0=本地独有；右>0=落后，需 --ff-only
```
合并前**预演冲突**（两侧改动取交集，比 `merge-tree --write-tree` 更可靠）：
```bash
MB=$(git merge-base HEAD origin/dev)
comm -12 <(git diff --name-only $MB..HEAD | sort) <(git diff --name-only $MB..origin/dev | sort)
```
实测多数轮次**只有 `.workbuddy/memory/<日期>.md`（日报）冲突** ⇒ 解：
```bash
tools/merge_memory_log.py --from-index .workbuddy/memory/<日期>.md          # dry-run 看「零丢失校验」
tools/merge_memory_log.py --from-index .workbuddy/memory/<日期>.md --write  # 通过后写盘
git add .workbuddy/memory/<日期>.md && git commit --no-edit
```
**合并前先 `cp` 备份 `deploy/.env.dev` / `.env` / `.env.head`**（历史上曾因脱跟踪被合并删除），完成后 `cmp` 比对 md5。

#### 🔴 ff-only 场景：工作区脏、但脏内容其实已在提交中（2026-10-14 实测）

运行栈里常挂着「上一次 `cp` 同步过来的源码」，而 `origin/dev` 已含同样内容 ⇒ **先比内容，再决定丢不丢**：

```bash
export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH
for f in <脏文件…>; do git diff --stat origin/dev -- "$f" | tail -1; done   # 空输出 = 内容一致 ⇒ 直接 git checkout -- 丢弃
for f in <未跟踪文件…>; do diff -q "$f" <(git show origin/dev:"<path>") >/dev/null && echo "SAME $f"; done  # 全 SAME 才 rm -rf
```
- 有差异的多半是**早期版**（实例：`deploy/docker-compose.dev.yml` 缺后补的 6 个 `XDY_*`）⇒ 同样丢弃，ff 会给到新版。
- 未跟踪目录不删就 ff 会报 `untracked working tree files would be overwritten`。
- **日报不能只看行数**：分别取 `<运行栈版>` 与 `git show origin/dev:<该文件>`，按 `^## ` 切段后做两道判据 ——
  ① 段落**标题集合**差集（`comm -23`）必须为空；② 逐行摘出「非空且非标题」的行，确认都能在提交版**对应段落**里找到子串。
  **两项都 0 缺失**才允许由提交版替代（2026-10-14 实测 663 行/44 段 vs 713 行/47 段，均 0 缺失）。动手前先把运行栈版 `cp` 到 `output/` 备份。

⚠️ 另注：Bash 工具里**未加引号**的 `${v%%|*}`（如 `$(docker inspect ${v%%|*} …)`）曾被判 `Bad substitution: v%%` 且**整条命令静默不执行**——现象是「以为 recreate 跑了、其实没跑」。加引号 `"${v%%|*}"` 或改逐项变量即可。
⚠️ feature 分支的 `deploy/.env.dev` / `.env.mac` **仍被跟踪**（与 dev 的脱跟踪状态不同，属存量欠账）⇒ `git-fast.sh` 每次会报「应 `git rm --cached`」，**别在重建轮里顺手改**。

**会话 cwd 未必是正确目录** —— WorkBuddy 的 Workspace Folder 可能是 `works/`（复数）那份副本。
动手前**必须先验**（容器 label 是权威判据）：

```bash
/Applications/Docker.app/Contents/Resources/bin/docker inspect linmo-pig-boot \
  --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'   # 期望 …/work/linmo-pig-full/deploy
cd /Users/shan/work/linmo-pig-full   # 后续一切命令都在这
```
⚠️ 在错目录上跑 `compose build` 会重建出「另一份代码」的镜像并覆盖 tag，`up` 后表现为「改了却没变 / 变回去」。

### 🔴 docker 路径的两个坑（2026-10-06 实测）
1. `docker` **不在 zsh 默认 PATH** ⇒ 裸 `docker ps` 报 `command not found`，**这不代表 Docker 挂了**。
2. `/usr/local/bin/docker` 是**指向 macOS AppTranslocation 临时目录的软链**（`/private/var/folders/.../AppTranslocation/...`），**会随 Docker.app 迁移失效**。旧记录「用 `/usr/local/bin/docker`」已不可靠 ⇒ 统一用 `/Applications/Docker.app/Contents/Resources/bin/docker`。
3. 另有一种假象：同一条命令上一秒能跑、下一秒 `command not found` ⇒ 先确认是不是 PATH 没导出，别误判成编排问题。

### 🔴 0.0g 现行运行栈可能是 **v1 一体化拓扑**（2026-10-16 实测；先 `docker ps` + `compose ls` 判，别默认 dev）

`docker ps` 见 `linmo-pig-boot|pig-ui|pig-pc-ui|python-ai` + **`deploy-mysql-1`**、`compose ls` 见
`linmo-pig`（config = `deploy/docker-compose-liyuying-v1.yml`）+ `deploy` → 就是 **v1 一体化 + 借私仓 mysql**（见 §0.0c）：

```bash
cd /Users/shan/work/linmo-pig-full          # 运行栈侧（容器 label 的 working_dir 为权威）
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose --env-file deploy/.env.liyuying --env-file deploy/.env \
  -f deploy/docker-compose-liyuying-v1.yml --profile pcui build                    # 4 个 build: target
docker compose ... --profile pcui up -d --force-recreate --no-deps pig-gateway     # 服务名 pig-gateway（容器 linmo-pig-boot）
docker compose ... --profile pcui up -d --force-recreate --no-deps python-ai pig-ui pig-pc-ui
```

该拓扑 MySQL 是**私仓镜像**（`192.168.110.172:8443/team/linmo-pig:267DB`）⇒ **没有本地 `linmo/pig-mysql:8.0` 可重建**，
`pig/db` 的新脚本只能走「**增量落库**」路径（用户没说「重置数据库」时本来也不该删卷）。

🔴🔴 **增量落库必须显式给库名，否则静默半失败**（2026-10-16 实测，7 个脚本里 4 个首轮失败）：

```bash
# ✅ 唯一正确写法：末尾带 pig
docker exec -i deploy-mysql-1 sh -c 'exec mysql -uroot -proot pig' < pig/db/<file>.sql
# ❌ 不带库名：脚本内**没有** `USE pig;` 的文件会报 `ERROR 1046 No database selected`
#    ⇒ 该脚本整体没生效，但循环里看着像「跑过了」，极易漏掉（`20261016_ops_assignee_current.sql` 就是这种）
```
- 判据：**先 grep 脚本有没有自带 `USE`**（`grep -c '^USE ' pig/db/<file>.sql`），没有就必须靠命令行给库名。
- **别忘幂等复核**：先跑一遍「计数基线 → 重放 → 计数」比对，只有「首轮失败那个脚本」的计数该变；其余零变化才算幂等成立。
- 落完登记 `sys_db_migration`（`INSERT ... ON DUPLICATE KEY UPDATE`，`checksum=sha256`、`file_size`、`executed_by=<标记>`）⇒ 在线升级页不会再列它们。
- ⚠️ **不要顺手重放菜单清理类脚本**（`zz_menu_*_dead_menu_cleanup.sql`）：它的删除效果早已在库，重放会把刚用 `*_post_restore_*.sql` 恢复的入口**再删一次**。判定法：先查该脚本要删的 `menu_id` 是否已为 0 行。

---

### 🔴 0.0h 增量落库时，**带守卫的迁移脚本会「静默跳过」**（2026-10-17 实测，两次踩到）

`pig/db/*.sql` 里有大量脚本把条件写进 `WHERE`/`NOT EXISTS` 做幂等守卫，**不满足条件时执行成功、零报错、但什么都没改**，
只凭「mysql 退出码 0」会误判「已生效」：

| 脚本 | 守卫 | 现象 |
|---|---|---|
| `20261016_retire_eight_quartz_features.sql` | 只删 `job_status='1'` 的行 | 运行中（status 2）的 6 个任务一条没删，却看着跑过了 |
| `20261017_hr_daily_summary_0710.sql` | UPDATE 带 `NOT EXISTS (SELECT 1 FROM qrtz_triggers WHERE job_name='<旧名>')` | 9606 名称/cron 完全没变 |

✅ 正解（退役/改名一类脚本的固定动作）：
```bash
# ① 按 FK 顺序删触发器（直接删 qrtz_triggers 会被 qrtz_cron_triggers 的外键拦住 → 1451）
docker exec -i deploy-mysql-1 sh -c 'exec mysql -uroot -proot pig' <<'SQL'
DELETE FROM qrtz_fired_triggers  WHERE job_name IN (<名…>);
DELETE FROM qrtz_cron_triggers   WHERE trigger_name IN (<名…>);
DELETE FROM qrtz_simple_triggers WHERE trigger_name IN (<名…>);
DELETE FROM qrtz_triggers        WHERE job_name IN (<名…>);
DELETE FROM qrtz_job_details     WHERE job_name IN (<名…>);
UPDATE sys_job SET job_status='1' WHERE job_id IN (<被退役的 id…>);
SQL
# ② 再重放脚本 → 此时守卫满足，才会真删/真改
# ③ 重放后必须逐项查库确认（行数/名称/cron），别只看命令是否报错
```
⚠️ **`docker exec` 必须带 `-i`**，否则 heredoc 传不进 stdin，输出为空且 `| grep -v` 让它看起来"没报错"。
⚠️ 判断「脚本是否已经生效」一律用**改动前后的库内计数/字段比对**（`sys_job` 行数、`sys_menu` 活行、`sys_role_menu` 行数），
不要用退出码、也不要用「脚本里写着的目标值」。

---

## 0.5 先做增量判断（**动手前必做，能省掉 90% 的无谓重建**）

自动化/用户说「重新构建 + 重置数据库 + 重启，让新代码立即生效」时，**先证明"没生效"，再动手**。四个判据：

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"; cd /Users/shan/work/linmo-pig-full

# ① 源码 vs 镜像：找「最近一次非 docs 改动」的时间，与镜像 Created 相对照
#    🔴 2026-10-14 订正：「镜像 Created 早于提交时间」**不能**判定镜像过期！
#       本仓常态是「改完 → 构建 → 验收 → 提交」⇒ 镜像时间戳天然早于提交时间。
#       实测：pig-boot 镜像 21:11 / 提交 21:14；pig-ui|pig-pc-ui 镜像 20:51 / 提交 20:53，
#       三者内容其实**都已是最新**，差点白跑一轮全量重建。
#       ⇒ ① 只能用来「起疑」，定性一律用 §0.6 的内容级特征串。
git log -1 --format='%h %ad %s' --date=format:'%F %H:%M:%S'          # 最近提交
git log --since="<上次重建时间>" --name-only --format='@@%h %s' | \
  python3 -c "import sys;[print(l.rstrip()) for l in sys.stdin if l.startswith('@@') or (l.strip() and not l.startswith(('docs/','output/','.workbuddy/')))]"
for i in linmo/pig-mysql:8.0 linmo/pig-boot:1.0.0 linmo/pig-ui:1.0.0 linmo/pig-pc-ui:1.0.0 linmo/python-ai-service:1.2.0; do
  printf '%-32s %s\n' "$i" "$(docker image inspect $i --format '{{.Created}}')"
done

# ② 并行会话在途工作（本仓最常见的「别动手」信号）
git status --short          # 非空 = 有会话正在改代码，此刻重置库/重建会撞车

# ③ 库是否已按最新 SQL 重放过：卷的建表时间 vs pig/db 最后改动时间
docker exec linmo-mysql sh -c 'mysql -uroot -proot -N -e "select max(create_time) from information_schema.tables where table_schema=\"pig\";"'

# ④ 🔴 容器跑的是不是当前 tag 的镜像 —— **用产物内容 md5，禁止用 image ID**
#    ⛔ 旧法（ID 比对）在 Docker 29 下**恒假报 DIFF**，已被推翻 ⇒ 详见 §0.7b。
#    只看 {{.State.StartedAt}} 也会骗人 —— `docker restart` 会刷新它却不换容器（2026-10-07 实测）。
docker exec linmo-pig-boot   md5sum /app/app.jar | cut -d' ' -f1
docker run --rm --entrypoint sh linmo/pig-boot:1.0.0 -c 'md5sum /app/app.jar' | cut -d' ' -f1
docker exec linmo-python-ai  sh -c 'md5sum app/main.py app/core/scheduler_registry.py | md5sum' | cut -d' ' -f1
docker run --rm --entrypoint sh linmo/python-ai-service:1.2.0 -c 'md5sum app/main.py app/core/scheduler_registry.py | md5sum' | cut -d' ' -f1
#    两侧相等 = 运行态就是当前 tag 的镜像内容（本轮实测：boot f0f241bd… / ai 8e35d49c… 双向一致）。
#    前端两侧没有可直接 md5 的单一产物 ⇒ 改用容器内特征串（§0.6）判「是否含最新代码」。
# 🔴 DIFF 要**两分**，别一律当「镜像落后」去重跑 build（2026-10-10 实测）：
#    · DIFF 且 ⑤ 显示「宿主脚本数 == 镜像脚本数 + 逐文件 md5 差异 0」⇒ 只是**容器建于镜像重建之前**
#      ⇒ 与镜像新鲜度无关，**不需要 `docker build`**；「重置库」本身会 `rm -f` 容器 + `volume rm` +
#        重新 `docker run`，必然换到新镜像；`up -d --force-recreate` 覆盖其余服务即可。
#    · DIFF 且 ⑤ 有差异/数量不等 ⇒ 才是真「镜像落后」，须重建镜像。

# ⑤ 🔴 MySQL 镜像内的 initdb 脚本集 vs 本机（「重置数据库」场景独有的隐藏缺口）
#    🆕 2026-10-14 起 `pig/db` 下**只有 6 个「保序切段」合并脚本**（01~06*.sql，无子目录、
#       无 manual/、无 merged/）⇒ 直接数即可，不再需要递归 find 与 -path 排除。
find pig/db -type f -name '*.sql' | wc -l
docker run --rm --entrypoint sh linmo/pig-mysql:8.0 -c 'find /opt/pig-db -type f -name "*.sql" | wc -l'
#    ⚠️ 两边都应为 **6**。镜像数远小于 6 ⇒ 镜像还是合并前的老镜像 ⇒ 需 `docker build` 重建。
# 🔴 数量相等 ≠ 内容一致：必须**逐文件 md5 比对**（2026-10-09 实测：宿主 121 = 镜像 121，但
#    perm_guard_agent_monitor_menus.sql 内容 DIFF ⇒ 只比数量的判据会漏掉「重置后丢权限守卫」）
docker run --rm -v /Users/shan/work/linmo-pig-full/pig/db:/h:ro --entrypoint sh linmo/pig-mysql:8.0 -c '
cd /h
for f in *.sql; do
  a=$(md5sum "$f"|cut -d" " -f1); b=$(md5sum "/opt/pig-db/$f" 2>/dev/null|cut -d" " -f1)
  [ "$a" = "$b" ] || echo "DIFF $f"
done | wc -l | xargs echo "差异文件数="'
```

**判定规则**：
- 🔴🔴 **`git fetch` 必须在「运行栈副本」里跑，别在 `works/` 里 fetch 完去 `work/` 快进**（2026-10-25 实测）：
  两副本**各有独立的 `origin/*` ref**。只在 `works/` fetch 后到 `work/` 里 `merge --ff-only origin/dev`，用的是 `work/` 里**旧的** ref
  ⇒ 命令成功、HEAD 前移、看着像追平，实际仍落后（本轮 193985a0 vs 真 tip 9d4e1bc9，差 12 提交）。
  **判据**：ff 之后立刻 `git log -1 origin/dev` 与「另一副本/`git ls-remote` 的 tip」对比，一致才算追平。
- 🔴 **`tools/gen_pig_merged.py` 必须用受管 python 3.13 绝对路径**（2026-10-25 实测）：裸 `python3` 报
  `TypeError: write_text() got an unexpected keyword argument 'newline'`（走的是 shim/旧解释器）⇒
  统一 `/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 tools/gen_pig_merged.py --check`。
- 🔴 **`pig/db` 里「未登记 `sys_db_migration`」≠「没生效」，要查库内效果**（2026-10-25 实测）：本轮 13 个未登记脚本中，
  `zz_20261024_maozai_org_users`（14 用户/5 部门/10 岗位）、`20261016_ops_peer_company`（表）、`zz_20261024_ops_policy_interpretation`（2 条 sys_job）
  在库里**全是 0** ⇒ 确实没施过；而 `zz_20261024_console_hotfix` / `doc_menu_dynamic_host` 的效果早已在库。
  ⇒ 正解：先用**该脚本的目标产物**（表/列/菜单/`sys_job` 行/字段值）查库，缺才施；施完再登记。
  ⚠️ `manifest.tsv` 里 `20261016_ops_assignee_explain_audit.sql` / `_receipt_reconcile.sql` 属 **`05_manual`（自动=no）** ——
  前者是只读 SELECT 诊断、后者是需人工绑定变量的收据恢复模板，**不执行不算漏施**。
- 🔴 **合并提交（merge commit）也会带源码，别被 `git log --name-only` 漏掉**（2026-10-19 实测）：
  `git log` 对 merge commit 默认**不展开**任何文件（除非冲突）。本轮 `affd6e78 fix: merge dev into feature/liyuying-client`
  实际带入 `OpsAgentController.java(+57)` + 新增 `OpsCommitPersonService/Mapper(+XML)`，而按普通日志看只像「记忆文件合并」⇒
  「后端零改动、boot 不用重建」的结论直接错。**判镜像落后时必须逐 merge 做 `git diff <merge>^1 <merge> --stat`**，
  或直接 `git log --since=<镜像时刻> --full-history -m --name-only`。
- 🔴 **「git 提交时间戳」不是有效判据**（2026-10-10 实测证伪）：当天提交层 `44e4f4f0→35125fc3` 的差异**只有 `.workbuddy`/`docs`/`output`**（零源码），若只看它必误判「无需重建」，实际同时漏掉两类落后 ——
  **(a) 未提交在途源码**（并行会话「pc 端七类彻底七分」改了 `AgentReport.vue` + `agents/registry.ts` + `agents/specs/*.ts` 但尚未 commit）、
  **(b) 镜像内脚本内容漂移**（`ui_audit_menu_fix_20261009.sql` md5 DIFF，镜像 124 vs 宿主 125）。
  ⇒ 先把「工作区里有没有比镜像更新的文件」查出来（**必须含未跟踪/未提交文件**）：
  ```bash
  find pig pig-ui/src pig-mob-ui/src pig-pc-ui/src python-ai-service/app deploy tools docs \
    -type f -newermt '<镜像构建时刻>' -not -path '*/node_modules/*' -not -path '*/dist/*' -not -path '*/target/*'
  git status --short          # 未提交在途 ≠ 阻塞「重建/重启」，只阻塞「重置库」与「git 提交」
  ```
  ⚠️ **判定「在途 ⇒ 需重建」后，必须在报告里显式标注该源码尚未提交** —— 重建会把半成品带上线（2026-10-10 实例：pc-ui `eb52af478b31` 即含未提交的七分重构），复验责任交回用户。
  ⚠️ 有 cache 时**全量重建 5 镜像仅约 2m16s** ⇒ 判据模糊时宁可全量重建，别只挑「时间戳落后」的那几个。
- 🔴 **⑤ 两个脚本数必须相等，且逐文件 md5 差异数必须为 0**（2026-10-06 立判据 / 2026-10-09 加固）：`pig/db/**/*.sql`
  新增**或改动**后，MySQL 镜像**不会**自动跟随（脚本是 `COPY` 进镜像的）⇒ 不重建就重置 = 建出**缺表、缺约束**
  的库（实测缺 `ai_app_config_snapshot` 表与 `model_code NOT NULL`）**或丢脚本语义更新**（实测丢
  `perm_guard_agent_monitor_menus.sql` 的权限守卫增量）。**服务镜像全绿 ≠ 可以重置**；「数量相等」是必要非充分条件。
- 镜像时间 > 最近一次相关源码改动时间，**且 ④ 的镜像 ID 比对为 SAME** ⇒ **该服务已生效，不要重建**。
  ⚠️ 不要用「容器启动时间 > 镜像时间」当判据（`restart` 会刷新 StartedAt）；2026-10-07 实测：6 容器 StartedAt 全是
  10:33 却跑着旧镜像 ⇒ 若只看时间戳会误报「无需重建」，实际必须 `up -d --force-recreate`。
- `git status --short` 非空（有并行会话在途）⇒ **不要重置数据库**（会抹掉对方刚造的数据），也不要抢着提交（见 §5）。
  ⚠️ **例外**：只显示 `M deploy/.env.dev` 时**不构成阻塞**（本仓运行态覆盖属预期态，见 §5 红线），可正常重置。
- 全部要素都已生效 ⇒ 只做 §4 端到端验证 + §5 记忆落盘，**如实报"无需重建"**（本仓惯例：空操作要如实报，不为「有产出」硬造动作）。

**⑥ 🔴 大量未提交 WIP 时怎么判（2026-10-10 16:55 实测）**：本仓常有多会话并行，`git status` 会有几十个 ` M`/`??` 源码文件。
判据不是「有没有 WIP」，而是**逐文件 mtime vs 该服务镜像 `Created`**：
```bash
G=/Library/Developer/CommandLineTools/usr/bin/git; cd /Users/shan/work/linmo-pig-full
$G status --porcelain | awk '{print $2}' | grep -vE '^(\.workbuddy/|output/|docs/)' > /tmp/wip.txt
while read -r f; do [ -e "$f" ] && stat -f '%Sm %N' -t '%F %H:%M:%S' "$f"; done < /tmp/wip.txt | sort -r | head -25
```
最新前端 mtime < ui/pc-ui 镜像 Created、最新 java/yml mtime < boot 镜像 Created ⇒ **镜像已含 WIP**。
再跑一次 `compose build`：**3s 内全 CACHED + 镜像 `Created` 未刷新 = 「镜像 == 当前源码」的反证**（COPY 缓存键是内容摘要，
源码变了必然重建）。⚠️ **别用「ID 不变」当判据**（attestation 会让 ID 每次都变，见 §1 ③）。**不要在 WIP 未提交时做任何 git 提交/回滚**（会吞并行会话文件）。
⚠️ 同一条理由对 `pig/db` 也适用，但**必须比对 `initdb-loader.sh`**（它是 `.sh` 不在 `*.sql` 循环里）：
`md5 -q pig/db/initdb-loader.sh` vs 镜像内 `md5sum /opt/pig-db/initdb-loader.sh`（2026-10-10 实测双 `71e582e5…`）。
🔴 **mtime 会集体骗人（2026-10-10 实测）**：若三端前端 + 后端 + python 的 mtime **全部落在同一秒**（如众数 `21:54:32`），
那是 **git 操作（checkout / stash pop / rebase）批量刷新的**，**不代表内容已变** ⇒ 必须回到「内容级」判据
（`compose build` 是否全 CACHED + 镜像 `Created` 是否刷新 + 产物特征串），否则会误判「镜像落后」而白跑一轮全量重建。

## 0.6 🔴 「新代码到底有没有在跑」的终极判据：内容级特征串（2026-10-14 实测）

时间戳（镜像 `Created` / 提交时间 / 文件 mtime）**全是间接证据**，会被「先 build 后 commit」「git 批量刷 mtime」「全 CACHED 重建仍换 ID」反复骗。
**唯一直接证据 = 在「正在运行的容器」里找一个只在某个版本存在的字符串。**

挑串原则：选源码里**新增/删除**过的、够独特的字面量当「DNA 探针」；并用**旧串必须消失**做反向验证。

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

# —— 前端：直接在容器产物里 grep（nginx 镜像带 busybox grep；/data 就是 dist 根）——
docker exec linmo-pig-ui    sh -c 'printf "新串="; grep -rl "周期切换"     /data/assets | wc -l;
                                   printf " 旧串="; grep -rl "分档提交汇总" /data/assets | wc -l'

# —— 后端：⚠️ 三个坑，任一踩中都会「假报没有」——
#   ① 运行时镜像**没有 `unzip` 也没有 `jar`** ⇒ 容器内解压必失败；若写成 `|| echo 0` 就**假报 0**
#   ② jar 路径是 `/app/app.jar`（**不是** /pig-boot/app.jar）
#   ③ 业务模块是 **`BOOT-INF/lib/<module>-x.y.z.jar` 嵌套 jar** ⇒ 必须**二次解压**才看得到 class
#   正解 = 先把 jar 拷到宿主，再用 python zipfile 逐层解
docker cp linmo-pig-boot:/app/app.jar output/_live.jar
python3 - <<'PY'
import zipfile, io
o = zipfile.ZipFile("output/_live.jar")
z = zipfile.ZipFile(io.BytesIO(o.read("BOOT-INF/lib/pig-ops-4.1.0.jar")))   # ← 嵌套 jar，名随版本变
for n in z.namelist():
    if n.endswith("OpsAgentController.class"):
        b = z.read(n)
        for label, s in [("新串1", "本期提交没有可读的说明"), ("新串2", "；最近做了：")]:
            print(("✅ 有 " if s.encode() in b else "❌ 无 ") + label)
PY
rm -f output/_live.jar      # 217MB，验完就删（output/ 已 gitignore）
```

实战结论（2026-10-14）：前端新串命中 / 旧串消失、后端 class 常量池命中 ⇒ 当时 5 个镜像内容**全是最新**；
用户说的「新代码没生效」实际只发生在**容器**层面（tag 已前移、容器仍挂旧镜像 ID）⇒ 只需 `--force-recreate`，**不需要重建镜像**。

## 0.7 🔴 全 CACHED 重建仍会换镜像 ID ⇒ 标签↔容器漂移是「常态」而非异常

`compose build` 全 CACHED 也常产生**新的镜像 ID**（attestation / 新 manifest）⇒ tag 指向新 ID，而容器仍挂旧 ID。
`docker compose up -d` 按 **tag 名**判等 ⇒ 认为「已是最新」，**不会换容器**。所以：
- 只要跑过 `build`，就必须复跑 §0.5 ④ 的 ID 比对；DIFF 就 `--force-recreate --no-deps`。
- 重启顺序：**先后端 `pig-gateway`（等 healthy ~40s），再 `pig-ui` / `pig-pc-ui` / `python-ai`**
  （python-ai 起太早会连不上 PIG ⇒ 配置自愈退化成 `ConnectError`；虽 30s 后会自愈，但验收时会看到红的中间态）。
- ⚠️ 别用 `grep -v CACHED` 判「哪些步骤真执行」：`--progress plain` 里缓存步骤占**两行**
  （`#8 [build 3/9] RUN npm run build` + `#8 CACHED`），`^#N (RUN|COPY)` 匹配不到第一行 ⇒ **恒输出空**、必然误判。按 `#N [stage] CMD` 与其后 `#N CACHED|DONE` **配对**判。

### 🔴 0.7b Docker 29：**别再用 image ID 判「容器是否跑最新镜像」**（2026-10-15 实测，推翻 §0.5④ 旧法）

Docker 29（本机 Engine `29.7.2`）下：

```bash
docker inspect <容器> --format '{{.Image}}'                 # → sha256:4f2ec…（旧 ID 形态）
docker image inspect <tag> --format '{{.Id}}'               # → sha256:54f08…
```
两者**恒不相等**，而且容器报的那个 ID 在 `docker image inspect <id>` 里**查不到**（"不存在"，
`docker run <id>` 会去 registry 拉 `4f2ec…:latest` 而报 `pull access denied`）⇒ **ID 比对必然假报 DIFF**。

✅ 唯一可靠判据 = **产物内容 md5（容器态 vs 标签镜像态）**：

```bash
D=/Applications/Docker.app/Contents/Resources/bin/docker
# 后端
$D exec linmo-pig-boot md5sum /app/app.jar | cut -d' ' -f1
$D run --rm --entrypoint sh linmo/pig-boot:1.0.0 -c 'md5sum /app/app.jar' | cut -d' ' -f1
# python-ai
$D exec linmo-python-ai sh -c 'md5sum app/main.py app/core/scheduler_registry.py | md5sum'
$D run --rm --entrypoint sh linmo/python-ai-service:1.2.0 -c 'md5sum app/main.py app/core/scheduler_registry.py | md5sum'
```
两值相等 ⇒ 容器跑的就是当前 tag 的内容，**不需要 force-recreate**（本轮实测 boot `f0f241bd…`、python-ai `8e35d49c…`，两边一致）。
`docker ps` 里 IMAGE 列显示成一串 hex（而非 `repo:tag`）**不代表有问题**，只说明该 tag 已被后续构建指到更"新"的 manifest。

### 🔴 0.8 本地构建后「python-ai 退化成 `source=fallback`」= 源码超前运行库 schema（2026-10-15 实测）

**症状链**：`curl :8090/health` → `source=fallback`、`last_sync_ok=False`、`last_error: ConnectError …`（**误导！**），
日志里 `dify app sync: 上报 PIG 失败：All connection attempts failed`、`pig_credentials … 解析生效实例出错（ConnectError）`。

**别去查网络**（DNS/TCP 都是通的；`GET /admin/internal/v1/health` 返回 **424** 就是白名单预期值、说明链路正常）。真因在服务端：

```bash
docker logs --since 10m <pig-boot> | grep -A3 'GlobalBizExceptionHandler'   # 看 ex= 后面第一段
# 典型：Unknown column 'api_key_cipher' in 'field list'
#   at …AiModelConfigService.listEnabled → AiConfigSyncService.snapshot
```

即**今天合并进来的代码要求新列，而运行库（持久化卷）从没重放过那条迁移**。定位与修复：

```bash
cd /Users/shan/work/linmo-pig-full
# ① 找「今日合并提交」带入的 db_bak 迁移（只认 DDL）
git show --stat --format='%h %ad %s' --date=format:'%F %H:%M' <今日合并commit> -- pig/db_bak
# ② 逐个重放（这些迁移都写成幂等：CREATE TABLE IF NOT EXISTS / information_schema 判存后 ALTER，且零密钥）
docker exec -i deploy-mysql-1 sh -c 'mysql -uroot -proot pig' < pig/db_bak/ai/ai_model_config_key_20261014.sql
docker exec -i deploy-mysql-1 sh -c 'mysql -uroot -proot pig' < pig/db_bak/kb/kb_workspace_20261014.sql
```
③ **不用重启 python-ai**：它按 `refresh_seconds=30` 自轮询，下一轮就 `source=pig`（实测 15:14:31 恢复 `apps=59 models=4`）。
④ 收尾核验：`docker logs --since 2m <pig-boot> | grep -icE "Unknown column|BadSqlGrammar"` 应为 **0**。

---

## 1. 重新打包

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd /Users/shan/work/linmo-pig-full

# ① MySQL 镜像必须单独重建（initdb 脚本是 COPY 进镜像的，不重建 = 重置库时用的是旧脚本）
docker build -t linmo/pig-mysql:8.0 \
  --build-arg REGISTRY=docker.m.daocloud.io/library/ pig/db
docker run --rm --entrypoint sh linmo/pig-mysql:8.0 -c 'ls -1 /opt/pig-db/*.sql | wc -l'   # 期望 6（2026-10-14 起 pig/db 为 6 个合并脚本；判据是「与宿主 6 个文件名 + md5 一致」而非固定数）

# ①′ ⚠️ 已废弃（2026-10-14）：`pig/db/merged/` 三文件层随 `pig/db_bak/merged/` 归档，
#    `tools/db-merged-init.sh` / `tools/gen_db_merged.py` 停用。`pig/db` 本身即 6 个
#    「保序切段」合并脚本 ⇒ 直接走 ① 重建镜像 + 重建数据卷即可（原来的「快 ~4 倍」优势已消失）。
#    留档（勿再用）：bash tools/db-merged-init.sh --reset --yes

# ② 4 个服务镜像（注意 --profile pcui，否则 pc-ui 静默保留旧镜像）
docker compose -f deploy/docker-compose.dev.yml \
  --env-file deploy/.env.dev --env-file deploy/.env \
  --profile pcui build

# ③ 🔴 别用 CreatedSince 判「是否刚重建」：cache 全命中时它保留的是**层时间戳**
#    2026-10-08 实测：前端重建仅 853ms、镜像显示「19 hours ago」，但镜像 ID 已变 + 产物特征串命中
#    真判据 = **镜像 `Created` 时间是否刷新** + 产物特征串（见下）
# 🔴 2026-10-10 订正：{{.ID}} **不能**作重建判据 —— containerd/attestation 下每次 build 都会重新生成
#    manifest，**即使全层 CACHED、Created 未变，ID 也会变**（本轮实测 4 镜像 ID 全变、耗时仅 2.5s、
#    Created 全部未刷新 ⇒ 实际零重建）。权威组合 = `Created` 未刷新 + `build` 全 CACHED + 产物特征串。
docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}' | grep linmo
```

### 🔴 坑
- 🔴🔴 **`Created` / `CreatedAt` 会「回退」，不能当镜像新旧的判据**（2026-10-12 实测，最反直觉的一条）：
  `pig-ui:1.0.0` 重建前 `Created` = 18:37:58，跑完一次**全 CACHED** 的 `compose build` 后**变成 14:32:34**。
  根因：buildkit 在全缓存时会**复用旧的 config blob**，其 `created` 字段就是当年那次构建的时间 ⇒
  **"时间戳变小"≠"镜像变旧"**，而是"内容与 14:32 那次完全一致"。
  📌 2026-10-25 又一实例：`pig-ui:1.0.0` 本轮真重建后 `Created` **仍停在前一天 15:18:51**（同因：复用旧 config blob），
  但镜像内 `grep -rl "API_HOST" /data/assets` = 1 命中 ⇒ 内容是最新的。**`Created` 只用于起疑，定性一律靠产物内容。**
  ⇒ 判「镜像是否落后于源码」的**唯一可靠口径 = 容器内产物特征串**（前端 grep `/data`、后端 `docker cp app.jar` + 取内层 jar 的 class），
  或 `docker run --rm --entrypoint sh <镜像> -c 'ls/cat/grep …'` 直接读镜像内文件（比 `Created` 可靠得多）。
  ```bash
  # 镜像内直接核验（不依赖任何时间戳）
  docker run --rm --entrypoint sh linmo/python-ai-service:1.2.0 -c \
    'ls app/yzt/; wc -l app/industry/tech.py; wc -c app/yzt/sync.py'   # 与宿主源码逐值比
  docker exec linmo-pig-pc-ui sh -c 'grep -rl "业务接入" /data | head -1'   # 前端产物（root 是 /data！）
  ```
- 🔴 **`--profile pcui` 不能省**：`.env` / `.env.dev` 里**没有** `COMPOSE_PROFILES`，不带 `--profile pcui` 时 `docker compose build` 完全不碰 `pig-pc-ui`。症状 = `linmo/pig-pc-ui:1.0.0` 时间戳仍是旧的，前端改动看不到。
- **`--force-recreate` 只重建容器不重建镜像** ⇒ up 早于 build 会静默停在旧镜像且仍 healthy。判据：`docker inspect -f '{{.Image}}' <容器>` == `docker image inspect -f '{{.Id}}' <镜像>`。
- **验证"新代码真的进了产物"别猜**：挑一处本次改动的**特征字符串**，在容器内 grep 构建产物。前端 nginx 的 root 是 **`/data/`**（不是 `/usr/share/nginx/html`，后者只有 `index.html`/`50x.html`，直接 grep 会假 0）：
  ```bash
  docker exec linmo-pig-pc-ui sh -c "grep -rl '尚未登记' /data | head"
  ```
- 🔴 **后端「新代码是否真生效」的字节码级判据**（2026-10-09 实测有效）：容器内**没有 unzip**，但可以 `docker cp` 出 fat jar，用 python 的 zipfile 取内层 `pig-ops-*.jar` 里的目标 class，**按常量池特征串**对比新旧实现 ——
  比 grep 源码/构建产物可靠（class 已编译，不受节点 `target/` 陈旧影响）：
  ```bash
  docker cp linmo-pig-boot:/app/app.jar /tmp/container-app.jar
  python3 - <<'PY'
  import zipfile, io
  z=zipfile.ZipFile('/tmp/container-app.jar')
  n=[x for x in z.namelist() if 'pig-ops' in x and x.endswith('.jar')][0]
  z2=zipfile.ZipFile(io.BytesIO(z.read(n)))
  b=z2.read('com/pig4cloud/pig/ops/service/OpsAgentLiveStatsService.class')
  for t in [b'JSONTokener', b'JSONConfig', b'JSONArray', b'parseArray']:
      print(t.decode(), '->', b.count(t))     # 旧实现留 JSONTokener/JSONConfig；新实现留 JSONArray/parseArray
  PY
  rm -f /tmp/container-app.jar
  ```
  ⚠️ 别用「宿主 `pig/*/target/*.jar` 的时间戳」当判据：Docker 是多阶段构建、在容器内编译，**不落宿主 target**。
- MySQL 镜像新旧判据：脚本**逐文件 md5**（数量相等会骗人，见 §0.5 ⑤）。缺 `ai_dify_app_seed.sql` 等 = 旧镜像。
- 🔴 **`docker.m.daocloud.io` 会 502 掉 `compose build`，且失败点跟"要不要重建"无关**（2026-10-12 实测，连试 2 次）：
  buildkit 在 **`load metadata`** 阶段就要向 registry 发 manifest HEAD（**即使所有层都会 CACHED、本地 base 镜像都在**）⇒
  `#N ERROR: unexpected status from HEAD request to https://docker.m.daocloud.io/v2/library/python/manifests/3.11-slim: 502 Bad Gateway`
  同款还有 `maven:3.9-eclipse-temurin-17` / `eclipse-temurin:17-jre`；**整个 build 0.9s 即以 rc=1 退出**，
  日志里 `target pig-gateway: failed to solve` / `target python-ai: failed to solve` 极具误导性（看着像代码/镜像错）。
  ⇒ 判读三步：① 看错误是不是 `unexpected status from HEAD request … Bad Gateway/502`（是 = **外部镜像源故障**，别去改 Dockerfile/代码）；
  ② 别把 rc≠0 当成"没重建成功⇒代码没生效"——**镜像是否已是当前源码要用 Created + 源码 mtime + CACHED 三判据单独判**（§0.5）；
  ③ 处置：重试（瞬时）→ 仍 502 就换源 `--build-arg REGISTRY=docker.1ms.run/library/`（本地已有 `docker.1ms.run/library/node:22-alpine`，实测该源可用）
  或用 `docker.1panel.live/library/`；⚠️ 换源会改变 FROM ⇒ 全量非 CACHED 重建、耗时数分钟。
  ⚠️ 另注：本机**没有** `python:3.11-slim`（只有 `…/python:3.12-slim`）⇒ 想靠 `DOCKER_BUILDKIT=0` 走本地 base 离线重建，**python-ai 这个 target 仍然过不去**；
  `pig-ui`/`pig-pc-ui`/`pig-gateway` 三个 target 的 base（nginx/node/maven/temurin）本地齐备，经典构建器可离线完成。
- ④ ✅ **实测有效的最省事绕法（2026-10-12）**：不换源，而是给本地已有的 base 镜像**补一个带 registry 前缀的 tag**，buildkit 就会认为「源在本地」而不发 HEAD：
  ```bash
  docker tag mysql:8.0 docker.m.daocloud.io/library/mysql:8.0
  # 按 Dockerfile 里 FROM 的 base 逐个补；前缀与 REGISTRY 变量保持一致
  ```
  本轮据此**离线重建成功**了 `pig/db`（MySQL，152 个 initdb 脚本入镜像）。受「本机无 `python:3.11-slim`」限制，`python-ai` target 仍过不去；其余 target 本地 base 齐备即可跑通。
  ⚠️ 判据提醒：绕法只解决「能不能 build」，**"镜像是否已是当前源码"仍要单独判**（Created + 源码 mtime + 全 CACHED，见 §0.5）。

---

## 2. 重置数据库

### 🔴 2.0 重置前预检：全新 initdb 能不能一次跑完（一次性容器，全程不碰在用卷）

> **首选**：仓库自带 `tools/diff_initdb_vs_live.py` —— 起临时容器跑**完整 initdb**、等日志出现「初始化完成」
> 后与现网库**逐行**比对（退出 0 = 脚本可重现现网；1 = 有差异；2 = 环境/执行失败）。它是这类检查的权威口径
> （`tools/verify_mysql_initdb.py` 的 EXPECT 计数已过时，别用，见本节末）。
> 下面是**它不可用 / 需要看原始 initdb 日志**时的等价手搓版本（也是抓 `ERROR 1146 / 1136` 的唯一途径）。

**为什么必做**：`initdb-loader.sh` 的契约是「任一脚本导入失败 ⇒ 立即中止（半初始化的库比彻底失败更难排查）」。
而它会把**没登记进 `ORDER` 的 `.sql` 按字典序追加到末尾自动执行** —— 包括 dev 自认为「一次性、手工执行」的脚本
（`sync_172_*` / `ops_simu_*` / 声明「已停用」的 `feishu_connector.sql` 等）。所以「重置前库能建出来」这件事
**不能靠 `tools/merge_integrity_check.py` 断言**（它只检查「本次新带入的脚本是否登记」），必须真跑一遍。
2026-10-08 实测：同一批 SQL 里就藏着两处必崩（第 80/119 步 `ERROR 1146` 表不存在；修掉后又暴露第 118/119 步
`ERROR 1136` 列数不匹配）。**这两类坑只有实跑才会暴露，且都会让「重置数据库」在第 N 步停住。**

```bash
D=/Applications/Docker.app/Contents/Resources/bin/docker; R=/Users/shan/work/linmo-pig-full
mkdir -p /tmp/initdb-check && cp "$R/pig/db/initdb-loader.sh" /tmp/initdb-check/zz-import-all.sh
chmod +x /tmp/initdb-check/zz-import-all.sh     # 🔴 必须 chmod：bind-mount 会丢执行位，entrypoint 直接退 126「bad interpreter」
$D rm -f tmp-initdb-check >/dev/null 2>&1; $D volume rm tmp-initdb-vol >/dev/null 2>&1
$D volume create tmp-initdb-vol >/dev/null
$D run -d --name tmp-initdb-check -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=pig -e PIG_SQL_DIR=/opt/pig-db \
  -v tmp-initdb-vol:/var/lib/mysql \
  -v "$R/pig/db":/opt/pig-db:ro \
  -v /tmp/initdb-check:/docker-entrypoint-initdb.d:ro \
  mysql:8.4 --character-set-server=utf8mb4 --collation-server=utf8mb4_general_ci \
  --lower_case_table_names=1 --default-time-zone=+08:00
sleep 110
$D logs tmp-initdb-check 2>&1 | grep '\[pig-initdb\]' | tail -6   # 期望 [N/N] + 「初始化完成：成功导入 N 个脚本，拒绝 0 个」
$D logs tmp-initdb-check 2>&1 | grep -iE 'ERROR|失败|中止'          # 期望空
```

- **失败怎么读**：日志里会直接给 `[pig-initdb] 错误：<文件> 导入失败 —— 初始化中止` 与底层 MySQL 错误。
  按两类归因：① `ERROR 1146 Table ... doesn't exist` = **执行顺序反了**（某脚本跑在它依赖的建表脚本之前）
  ⇒ 登记/调整 `initdb-loader.sh` 的 `ORDER`；② `ERROR 1136 Column count doesn't match` = 某脚本用了
  mysqldump 的**位置化** `INSERT ... VALUES`，而该表后来被 `ALTER` 加过列 ⇒ 改成**显式列名**（一劳永逸）。
- **抽检**（别只看「跑完」，浅坑是「跑完但语义不对」）：
  `$D exec tmp-initdb-check mysql -uroot -proot -N -B pig -e "<QUERY>"`，重点看
  ① `ops_connector` 里 `connector_type='DATA'` 且 `del_flag='0'` 的行 **`mode` 是否为空**（空 ⇒
  `OpsSyncTriggerJob` 口径 `mode IN ('DIFY','LOCAL')` 匹配不到 ⇒ 定时采集与「立即同步」**静默不触发**；
  `mode` 无默认值、只由 `ops_connector_recategorize_20261006.sql` 逐行赋值 ⇒ **连接器种子脚本必须排在它之前**）；
  ② 关键表是否都在（`ops_connector_credential` / `ops_im_contact` / `ops_ext_yzt_attendance` / `im_connector_template`）。
- **收尾**：`$D rm -f tmp-initdb-check; $D volume rm tmp-initdb-vol`。
- ⚠️ `tools/verify_mysql_initdb.py` 的 EXPECT 计数（表 200 / 菜单）**已过时**（2026-10-08 实测
  BASE TABLE 238 + 2 VIEW、菜单 433）⇒ 它会在正确的库上报失败，别拿它当判据（可更新 EXPECT，但要先确认真值）。

### 🔴 2.0b `pig/merged` 路线：`zz_` 之间的依赖靠「头部声明」，不是文件名

- **现象**：预检报 `ERROR 1146 Table 'pig.ai_master_chain' doesn't exist`，日志停在 `03_menu_perm.sql` 的某一段。
- **根因**：`tools/gen_pig_merged.py` 原先用 `sorted()` **字典序**排段，`zz_..._approval_modes`（a）必然排在
  `zz_..._tool_calling`（t）之前。而前者是 `ALTER TABLE ai_master_chain`，后者才 `CREATE TABLE`
  ⇒ 全新库 initdb 直接中止（2026-10-19 实测，若没预检就直接删卷，会得到半初始化的库）。
- **已修**：生成器新增 `order_by_prerequisite()`，扫描每个 `zz_*.sql` 头部 6KB 内出现的其它 `zz_*.sql`
  文件引用并做稳定拓扑排序。⇒ **新脚本要排序，就在头部写明「前置条件：`zz_xxx.sql` 已执行」**，写得越直白排得越准。
- 🔴🔴 **这个修复会「再次消失」，动手前先验它还在**（2026-10-20 实测第二轮复发）：
  ```bash
  grep -n 'order_by_prerequisite' tools/gen_pig_merged.py   # 无输出 = 只有字典序 ⇒ 必须先补回
  ```
  上轮加过但**没提交**，随后被远端重生成的 merged 覆盖 ⇒ 本轮预检又报同一个 `1146`。
  ⇒ 判定链：`gen_pig_merged.py --check` 通过 **不代表段序正确**（它只比内容 sha，不比顺序）；
  唯一能暴露段序错误的是**预检（一次性容器真跑 initdb）**。所以「先预检再删卷」不是可选项。
  ⇒ 补回后 **务必提交生成器 + 重生成的 `pig/merged/*`**，否则下轮重置还会踩。
- **兜底**：任何「对可能还不存在的表做 ALTER」的幂等守卫，必须同时判 `information_schema.tables` 与
  `information_schema.columns`；只判列会得到 `count=0 ⇒ 执行 ALTER ⇒ 1146`。
- 改完 `pig/db` 后**必须重跑生成器**再 build mysql 镜像，否则镜像里还是旧段序。

### 🔴 2.0c 改过 `pig/db/*.sql` ⇒ 后端镜像必须一起重建

`BOOT-INF/classes/db/` 是升级页比对 checksum 的基准。只重建 mysql 镜像、复用旧 pig-boot，会让
`/admin/db/upgrade/pending` 报 `MODIFIED (modifiedCount=1)`，看着像「脚本被篡改」。修法：

```bash
$D compose ... build pig-gateway                     # Maven ~40s 增量
$D compose ... up -d --force-recreate --no-deps pig-gateway
# 复核 jar 内脚本字节：BOOT-INF/classes/db/<file> 的 size/sha256 应与 pig/db 源文件一致
```


**不可逆，先备份。** 用 `docker exec` 走容器内的 mysqldump（宿主机没有 mysql 客户端也能跑）：

```bash
D=/Applications/Docker.app/Contents/Resources/bin/docker
BK="output/db-backup/$(date +%Y-%m-%d-%H%M)"; mkdir -p "$BK"
$D exec linmo-mysql sh -c 'exec mysqldump -uroot -proot --all-databases --single-transaction --routines --triggers --events --set-gtid-purged=OFF' > "$BK/all-databases.sql"
# 硬校验（不过就中止）
grep -q 'CREATE TABLE `sys_user`' "$BK/all-databases.sql" && grep -q 'INSERT INTO `sys_user`' "$BK/all-databases.sql" && echo OK
```

重置（顺序不能颠倒）：

> 🆕 **现行口径（2026-10-19）**：`pig/db` = 三库快照 + 散增量（约 40 个 SQL），由
> `tools/gen_pig_merged.py` 生成 `pig/merged/`（01 快照 / 02 增量 / 03 菜单权限 / 04 后置 / 05 人工，
> 共 30 段自动执行），**MySQL 镜像以 `pig/merged` 为构建上下文**。下面「6 个合并脚本 / db_bak」是
> 2026-10-14 的旧路线描述，已退役；v1 一体化拓扑走的是「按 merged 重打 267DB + 删 deploy-mysql-1 与卷」。

```bash
$D volume rm linmo-mysql-data                    # ① 删卷 = 抹掉数据
$D run -d --name linmo-mysql --network linmo-net --network-alias mysql \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=pig -e TZ=Asia/Shanghai \
  -v linmo-mysql-data:/var/lib/mysql --restart unless-stopped \
  linmo/pig-mysql:8.0 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_general_ci \
  --lower_case_table_names=1 --default-time-zone=+08:00

# ② 等 initdb（约 40s）
for i in $(seq 1 56); do
  $D logs linmo-mysql 2>&1 | grep -q 'MySQL init process done' && { echo 完成; break; }
  sleep 5
done
$D logs linmo-mysql 2>&1 | grep -E '\[pig-initdb\]' | tail -3
```

**期望**：`初始化完成：成功导入 N 个脚本，拒绝 0 个`（2026-10-08 基线 = 导入 **107**，即宿主 109 个脚本中 2 个被加载器**主动排除**：
`hr_agent_rename_employee_ext.sql`、`hr_agent_rename_ext_prefix.sql` —— 含 `DROP DATABASE` + 开发数据快照，日志会写明原因，**不是缺陷，不要试图补跑**）。

```bash
# ③ 校验
$D exec linmo-mysql sh -c 'mysql -uroot -proot -N -e "
select table_schema,count(*) from information_schema.tables
where table_schema not in (\"mysql\",\"information_schema\",\"performance_schema\",\"sys\") group by 1;"'
# 期望：pig 226（2026-10-08 基线，随脚本集增长）/ pig_config 12 / pig_dw 9
# 注：220 比 219 多出的通常是**运行时自建表**（如 ai_app_config_snapshot，由 Python 侧配置同步建），不是缺陷。
```

### 🔴 坑
- **mysql 容器是手工建的**，`docker compose down` 不会动它，但 `docker compose up` 也不会建它 ⇒ 重置后必须手工 run 回来，参数照抄上面（网络别名 `mysql` 必须对，boot 靠它解析）。
- 若 `docker ps -a` 突然**只剩 mysql 或全空**：Docker Desktop 侧容器列表丢失（`docker info` 里 `Containers: 0`）。**镜像与卷都在**，先核卷再操作，别急着重建数据：
  ```bash
  docker run --rm -v linmo-mysql-data:/v alpine sh -c 'ls -1 /v | wc -l; du -sh /v'
  ```
- 重置前务必确认 `.env.dev` 里的 `REGISTRY` 前缀（`docker.m.daocloud.io/library/`），否则拉基础镜像超时。
- 🔴🔴 **必须先 `docker rm -f linmo-mysql` 再 `docker volume rm linmo-mysql-data`**（2026-10-10 实测）：
  只删卷会报 `volume is in use - [<container-id>]`，随后的 `docker run --name linmo-mysql` 又报
  `Conflict. The container name "/linmo-mysql" is already in use` ⇒ **两步都失败但命令各自看似正常**。正确顺序：先删容器、再删卷。
- 🔴🔴 **`docker run -d` 传错 server 参数不会返回非 0 ⇒ `||` 兜底静默失效**（2026-10-10 实测踩坑）：
  参数拼成 `--lower_case_tables_names`（少一个 `_`）时，`docker run -d` **仍然 exit 0、容器照样启动**，
  但 mysqld 立刻报
  `[ERROR] [MY-000067] unknown variable 'lower_case_tables_names=1'` +
  `[ERROR] [MY-013236] The designated data directory /var/lib/mysql/ is unusable` 并中止 ⇒
  `restart unless-stopped` 反复重启，留下**半初始化 datadir**（比彻底失败更难查）。
  ⇒ **起完 mysql 必须 `docker logs linmo-mysql` 看一眼**（有无 `unknown variable` / `unusable`），别只看容器 Up；
  已踩则 `docker rm -f linmo-mysql && docker volume rm linmo-mysql-data` 从头来。
  ⚠️ 同理别在 `docker run` 后面挂 `|| docker run <正确参数>` 这种兜底写法当保险。
- **重置会连带抹掉运行时数据**（快照表、临时配置），若另一会话正在做功能验证 ⇒ 先别重置（见 §0.5 ②）。

---

## 2.5 🔴 重置后必做的五件收尾（2026-10-06 起实测：漏做 ⇒ 服务全绿但页面数据为空 / 永远不更新 / 配置丢失 / 页面报无权访问）

删卷重置只重建「SQL 种子里有的东西」。下面五项都在种子之外：

### ① 回灌运行时业务数据（实测丢了 39 张表 / 3729 行）
`ops_*`（`ops_decision`/`ops_insight`/`ops_metric`/`ops_ext_task|project|commit`/`ops_simu_*`/`ops_sync_log`/`ops_kb_solution`，以及 `ops_connector` 的运行期新增行）与 `pig_dw.*`（dwd/dws/ads 6 张）的业务数据**不在 `pig/db/**/*.sql` 里**，删卷即丢。

```bash
# 先备份当前（空）库，再生成回灌 SQL。--ignore-all 必须带（幂等，可重复跑）
python3 tools/restore_tables_from_backup.py \
  --backup output/db-backup/<TS>/all-databases.sql \
  --out    output/db-backup/restore-ops-from-<TS>.sql --ignore-all \
  --table pig.ops_decision pig.ops_insight pig.ops_metric pig.ops_ext_task pig.ops_ext_project \
          pig.ops_ext_commit pig.ops_sync_log pig.ops_kb_solution pig.ops_connector \
          pig.ops_simu_crm_follow_up pig.ops_simu_crm_opportunity pig.ops_simu_crm_contact \
          pig.ops_simu_crm_account pig.ops_simu_crm_lead pig.ops_simu_crm_contract pig.ops_simu_crm_campaign \
          pig_dw.dwd_code_commit pig_dw.dwd_project pig_dw.dwd_work_item \
          pig_dw.ads_project_risk_board pig_dw.dw_etl_batch pig_dw.ads_data_quality_daily
$D exec -i linmo-mysql mysql -uroot -proot < output/db-backup/restore-ops-from-<TS>.sql
```

- 🔴 **必须 `--ignore-all`**：`ops_insight` 有唯一键 `uk_ops_insight_no`，重置后库里可能已有一行同编号（如市场日报汇总）⇒ 普通 INSERT 直接 `ERROR 1062` 中断整批。副作用：**种子里已有的行不会被备份版覆盖**（IGNORE 静默跳过）⇒ 若怀疑某行被运行时手工修过（如 `sys_job.method_params_value`、`ai_app_config.enabled`），必须**单独比对备份版与本库版**，别假定回灌已还原。
- 🔴🔴 **回灌后必做「按业务键的全列比对」，不能只比行数（2026-10-12 实测真中两处）**：
  · `sys_job.9601.method_params_value`：种子=**NULL**、重置前=`'{}'`（运行时修好的）⇒ IGNORE 不覆盖 ⇒ 不修就复现「每 5 分钟一次 spring bean 反射异常」；修完须再 `refresh-jobs`，判据 `sys_job_log` 新条目 `job_log_status=0`。
  · `ai_app_config.enabled` + `api_key_cipher`：重置后 75 行 `enabled='0'`，重置前 65 行启用（种子里这些行本就写 `'0'`，`'1'`+密钥是运行时同步的成果）⇒ 按备份还原 39 行后，共同 app_code 的 `(enabled, has_key)` 与重置前 **0 差异**，python-ai 下发应用 29→62。
  · ⚠️ **`ai_app_config` 绝不能按 `id` 还原 —— 本分支的 id→app 映射会整体位移（2026-10-12 实测位移约 22 号：备份 id=64 是 `zentao-tasks-fetch`，现库 id=64 是 `kb-qa-public`）**，按 id 还原会把配置张冠李戴。一律按 **`app_code`** 比对与还原；枚举 SQL 见下：
  · ⚠️ **`app_code` 不是唯一键 —— 有「一活一删」的重复行，单列 join 会交叉错配**（2026-10-13 实测：`business-brief` / `wf-daily-brief` 各 2 行）。
    `UPDATE c JOIN b ON c.app_code=b.app_code SET c.<所有列含 del_flag>=b.<同列>` 会产生 2×2 的笛卡尔匹配、**逐行结果不确定**，实测把活行的密文换成了已删行的密文、`del_flag` 也被写乱。
    ⇒ 处置：**按 `app_code` 分组，唯一键走 `app_code` 的 UPDATE；重复键改为「`DELETE` 本库该 app_code 全部行 → 从备份逐行 `INSERT` 重建」**。
    ⇒ 判据用**多重集差集**而非逐列比对：`(app_code, del_flag, enabled, ifnull(api_key_cipher,'#'))` 四元组在「现库 ∪ 备份」里出现的次数必须成对（只在一边出现 = 漏/多）。
    本次达标值：`ai_app_config=101` / `live=65` / `enabled='1'` 73 —— 与备份**完全一致**。
  ```bash
  # 备份侧：解析 dump 的 INSERT 元组（列序取 CREATE TABLE 反引号列名），现库侧：SELECT app_code,enabled,api_key_cipher
  # 比对 (app_code -> enabled, has_key) 二元组；仅备份有的 app_code 要甄别是否被 ai_tenant_app_uk.sql §2 定点去重删除（官方预期）
  ```
- 🟢 **首选回灌写法（2026-10-19 实测，40 表 / 9873 行一次零错）：显式列名 + 逐表 `USE`**。
  自写生成器（`output/db_restore_gen.py`，gitignored，可现场重写）：解析 dump 的 `CREATE TABLE` 取**源列序**、
  `information_schema` 取**现库列序**、按顶层括号切分 `VALUES` 元组，只输出**两边都有的列** ⇒
  尾部追加列（`generation_max_attempts` 类）自动降级为默认值，**永不 1136**；每张表前打 `USE \`db\`;`，
  逐行 `INSERT IGNORE`。生成后自检「任何 INSERT 之前是否出现过 USE」必须为 0（见下方纪律）。
  优于 `tools/restore_tables_from_backup.py`（后者输出**位置化** INSERT，且一张表多条语句时行数统计只报最后一段）。
- 🔴 **别手写表清单，按 dump 自动发现**（手写清单会漏表；2026-10-09 实测从 26 张扩到 **82 张 / 11215 行**）：
  ```bash
  # ① dump 里出现过 INSERT 的表
  python3 - "$BK/all-databases.sql" > /tmp/dump_tables.txt <<'PY'
  import re,sys
  s=open(sys.argv[1],encoding='utf-8',errors='replace').read()
  print('\n'.join(sorted(set(re.findall(r"INSERT INTO `([a-z_0-9]+)`", s)))))
  PY
  # ② 现库逐表精确行数（一次 SQL 拿全，避免 200+ 次 exec）
  $D exec linmo-mysql sh -c 'mysql -uroot -proot -N -B -e "
  SET SESSION group_concat_max_len=1000000;
  SELECT GROUP_CONCAT(CONCAT(\"SELECT \\\"\",table_schema,\".\",table_name,\"\\\" k, COUNT(*) c FROM \`\",table_schema,\"\`.\`\",table_name,\"\`\") SEPARATOR \" UNION ALL \")
  INTO @s FROM information_schema.tables WHERE table_schema IN (\"pig\",\"pig_dw\") AND table_type=\"BASE TABLE\";
  PREPARE st FROM @s; EXECUTE st;"' 2>/dev/null
  # ③ 对照：现库 = 0 行 且 dump 有 INSERT 的表 = 待回灌（qrtz_* / sys_log* 排除，它们是触发器与纯日志）
  ```
- 🔴🔴 **上面这个 `GROUP_CONCAT` + `PREPARE` 取行数的写法会静默截断，别信它**（2026-10-13 实测）：
  同一条在 `group_concat_max_len=1000000` 下，275 张表只回了 **161 行**，被漏掉的表全部被当成「现 = 0」
  ⇒ 待补灌表数从 54 虚增到 116、还会诱导你去 `DROP` 本已存在的表（见下条事故）。
  **改用「宿主生成 UNION 查询」**（把表清单先查出来，在宿主拼 SQL 再喂回去，完全不经过 GROUP_CONCAT）：
  ```bash
  $D exec linmo-mysql sh -c 'mysql -uroot -proot -N -B -e "select table_schema,table_name from information_schema.tables where table_schema in (\"pig\",\"pig_dw\",\"pig_config\") and table_type=\"BASE TABLE\";"' 2>/dev/null > /tmp/tbls.txt
  python3 -c "
  names=[l.rstrip().split('\t') for l in open('/tmp/tbls.txt') if '\t' in l]
  print(' UNION ALL '.join(\"SELECT '%s.%s' k,COUNT(*) c FROM \`%s\`.\`%s\`\"%(s,t,s,t) for s,t in names)+';')" > /tmp/q.sql
  $D exec -i linmo-mysql sh -c 'exec mysql -uroot -proot -N -B' < /tmp/q.sql 2>/dev/null > /tmp/now_counts.txt
  wc -l < /tmp/now_counts.txt     # 必须等于 /tmp/tbls.txt 的行数，不等就是又截断了
  ```
- 🟢 **首选工具（2026-10-14 起）：`assets/parse_dump.py`** —— 在宿主侧按**顶层括号**精确切分 dump 的
  `VALUES` 元组，一次拿全「每表行数 / `sys_job` 明细 / `ai_app_config` 全部行 / 任意表 DDL」，**彻底绕开
  GROUP_CONCAT 的静默截断**。本 skill 的收尾比对一律用它，不要再手搓正则或走 SQL 侧拼接：
  ```bash
  A=/Users/shan/.workbuddy/skills/linmo-stack-rebuild-reset/assets/parse_dump.py
  python3 "$A" <备份>/all-databases.sql counts                      # → db.table<TAB>行数（136 行）
  python3 "$A" <备份>/all-databases.sql jobs                        # → job_id/status/params/cron/name
  python3 "$A" <备份>/all-databases.sql apps                        # → ai_app_config 全列（stderr 打汇总）
  python3 "$A" <备份>/all-databases.sql ddl pig_dw ods_xdy_work      # → 带 USE 的 CREATE TABLE（补缺表用）
  ```
- 🔴🔴 **「现库 = 0 行」只是第一遍兜底，必须再做「逐表行数全量比对」**（2026-10-10 实测漏 4 张 / 155 行）：
  种子已提供**部分行**的表，重置后**非 0** ⇒ 被 0 行判据漏掉，实际比备份少：
  `ai_app_config` 49↔**101**、`ops_connector` 18↔**21**、`ops_ext_task` 224↔**321**、`ops_ext_daily_report` 21↔**27**。
  正确判据 = **从备份 dump 解析每张表的行数**，与重置后**逐表比**，凡「现 < 备份」即补灌（下面这段直接复用）：
  ```bash
  # ① 解析 dump：按库范围精确数每张表 INSERT 的行数（数顶层括号组，别按行数）
  python3 - "$BK/all-databases.sql" <<'PY' > /tmp/dump_counts.tsv
  import re,sys
  s=open(sys.argv[1],encoding='utf-8',errors='replace').read()
  cur=None; counts={}; lines=s.split('\n')
  def rows_of(stmt):
      k=stmt.find('VALUES')
      if k<0: return 0
      body=stmt[k+6:]; depth=0; inq=False; esc=False; n=0
      for ch in body:
          if esc: esc=False; continue
          if inq:
              if ch=='\\': esc=True
              elif ch=="'": inq=False
          else:
              if ch=="'": inq=True
              elif ch=='(':
                  if depth==0: n+=1
                  depth+=1
              elif ch==')': depth-=1
      return n
  for li,l in enumerate(lines):
      if l.startswith('-- Current Database: `'):
          cur=l[l.find('`')+1:l.rfind('`')]
      m=re.match(r'INSERT INTO `([a-z_0-9]+)`', l)
      if m and cur in ('pig','pig_dw'):
          buf=l; j=li
          while not buf.rstrip().endswith(';'):
              j+=1
              if j>=len(lines): break
              buf+='\n'+lines[j]
          counts[(cur,m.group(1))]=counts.get((cur,m.group(1)),0)+rows_of(buf)
  for k in sorted(counts): print(f"{k[0]}.{k[1]}\t{counts[k]}")
  PY
  # ② 现库逐表精确行数（同 §2.5 ① 的 PREPARE 一次性查全）→ /tmp/now.txt
  # ③ 比对：现 < 备份 ⇒ 待补灌（排除 qrtz_* / sys_log / sys_job_log，它们是运行时重建的触发器和纯日志）
  # 🔴 「现 > 备份」**不等于异常**，必须甄别原因再下结论（2026-10-10 实测）：
  #    本轮唯一差异是 `pig.sys_role_menu` 备份 404 → 现 **443（+39）**，根因是新增的
  #    `20261010_admin_perm_guard.sql` 把 role 1 补授到**全部未删除菜单** —— 这正是上一轮
  #    403 的修复。**新增「授权守卫 / 补种 / 回填」类脚本都会让现库行数反超备份**。
  #    判定法：先看「+多」的表是否被本轮新增脚本显式写过（grep 该表名于 `pig/db/**/*.sql` 的
  #    新增文件），是 ⇒ 预期、记入报告即可；否 ⇒ 才是真异常（如回灌把整表 REPLACE 掉）。
  #    ⚠️ 反向同理：`sys_role_menu` 被**备份回灌**反而会把新脚本刚建好的全量授权**打回旧态**
  #      （2026-10-10 14:03 那轮 403 的成因）⇒ 回灌表清单里**尽量排除 `sys_role_menu`**，
  #      或确保守卫脚本在回灌之后重跑。
  ```
- 🔴 **运行期自建表必须先从 dump 补 DDL**（2026-10-10 实测）：`restore_tables_from_backup.py` **只产 INSERT、不产 `CREATE TABLE`**；
  「万能入湖」契约建出的 `pig_dw.ods_xdy_account_trend`(581) / `ods_xdy_work`(22) 在全新库里**根本不存在** ⇒
  直接从 dump 抽该表 `CREATE TABLE` 建表后再灌，否则整段报 1146。
  同轮实测 `ops_connector` 备份/现库**列数均 29** ⇒ 无 `ERROR 1136`，无需桥接（**先比 `information_schema.columns` 再决定**）。
- 🔴 **zsh 不做词分割**（2026-10-09 实测踩坑）：`--table $TABLES` 会把整串当**一个**参数 ⇒ 生成的 SQL **「合计 0 行」而脚本仍 exit 0**（极易被当成「备份里没数据」）。必须写 **`--table ${=TABLES}`**。
- 🔴🔴 **手写回灌 SQL 时「DROP 限定名 + CREATE/INSERT 非限定名」= 真删表事故**（2026-10-13 实测，**删掉了 117 张表**）：
  mysqldump 的 `CREATE TABLE`/`INSERT INTO` 都是**非限定名**，必须靠 `USE <库>;` 给上下文；而 `DROP TABLE IF EXISTS pig.xxx;` 是**限定名、没有默认库也照删**。
  两者混写时 `mysql` 会对 `DROP` **成功执行**、对 `CREATE/INSERT` 报 `ERROR 1046 No database selected`，而**加不加 `--force` 都会静默继续** ⇒ 结果就是「表删了、没建回来」（150 表 → 149 表的塌陷，且日志里只有一堆 1046 看着像无害）。
  ⇒ 三条纪律：① 生成脚本时**每张表前显式 `USE \`<库>\`;`**（或全部改用限定名）；② **执行前做结构自检** —— 逐行扫「任何 `INSERT/CREATE/DROP` 之前是否出现过 `USE`」，为 0 才允许执行；③ 已踩则立刻**二次重置**（删容器 + 删卷 + 重建，~15s）回到干净库，不要试图逐表手工补。
  自检片段（生成后立刻跑，成本几秒）：
  ```python
  db=None; bad=0
  for ln in out:
      if ln.startswith('USE '): db=ln
      elif re.match(r'(INSERT|CREATE TABLE|DROP TABLE)', ln):
          if db is None: bad+=1; print('!! 缺 USE：', ln[:80])
  print('无 USE 的语句数 =', bad)   # 必须为 0
  ```
- 定位「丢了哪些表」用**逐表行数比对**（重置前备份 vs 重置后备份），不要看文件总量。回灌后**逐表与基线核对**（本次 15 张关键表全等）。
- 🔴 **`ops_connector` 段会撞新 schema 列（2026-10-09 实测 ERROR 1136 中断后续段导入）**：现库 schema 落后于种子时（旧库 `ops_connector` 无 `im_provider`/`mode` 列），`restore_tables_from_backup.py` 生成的位置化 `INSERT ... VALUES` 列数对不上新库 ⇒ mysql 在该段报错即停，**其后的 `ops_simu_crm_*` 与 `pig_dw` 段全部没导入**（行数非 0 是种子给的，别被迷惑）。处置：① 剔除 `ops_connector` 段后重导其余段；② 备份独有行（如 `zentao-copy`/`feishu`/`dingtalk`/`wecom`/`industry-media-pool`）用「备份 dump 里的旧 DDL 建临时表 → 导入 → 显式列名 `INSERT INTO ops_connector (<旧26列>) SELECT ... FROM _bak`」桥接（新列 `im_provider`/`mode` 落默认/NULL）。**教训：回灌永远优先显式列名，位置化 INSERT 是隐患**。
  ⚠️ 反向也要查：备份取自**新 schema 库**时列数本就相等 ⇒ 不报错是正常的（2026-10-09 实测备份 DDL 29 列 = 现库 29 列，全程无 1136）。**先比对两边的 `information_schema.columns` 再决定要不要桥接**。
- ⚠️ `ops_simu_*`「能不能回灌」取决于**备份时是否已生成过模拟数据**：早期记录说「备份里本来就是 0 行」是在**重置后未重生成**的备份上得出的。2026-10-09 实测：备份（当天 07:07 建库后又跑过模拟器）**带着** 4 域 899 行 ⇒ 回灌即可，无需重生成（项目域 `plan_start = 今天 + 偏移`，**只要备份与恢复同一业务日就不会过期**）。判断法：`tools/seed_ops_simu.py`（无参=只诊断）看各域行数，全非 0 就跳过 ③。

### ② 恢复 Quartz 触发器（不做 ⇒ 数据永不自动更新）

🔴 **正确姿势是 `POST /sys-job/refresh-jobs`，不是逐个 `start-job`**（2026-10-07 订正）：

| 入口 | status=1(已发布) | status=2(运行中) | status=3(暂停) |
|---|---|---|---|
| 启动时 `PigInitQuartzJob` | `removeJob` | **`resumeJob`（要求触发器已存在，不会新建）** | `pauseJob` |
| `POST /sys-job/refresh-jobs` | `removeJob` | **`addOrUpdateJob`（会新建）** | **`addOrUpdateJob`** |
| `POST /sys-job/start-job/{id}` | 走新建分支* | `resumeJob` + 置状态 2 | `resumeJob` + 置状态 2 |

\* `SysJobController.startJob` 里写错：拿 `PigQuartzEnum.JOB_LOG_STATUS_FAIL`（值同为 `"1"`）去比 `jobStatus`，对 status=1 的行**恰好为真**才走了新建分支。
⇒ 结论：**只重启服务（PigInitQuartzJob）不会给 status=2 的行建触发器**；种子把 9601~9609 置 1、9610 置 2 ⇒ 出现「库里运行中、Quartz 里没触发器」的静默不一致。

- 🔴 **但 `refresh-jobs` 不是万能：SQL 明确写「不刷新/启动全部任务」时，改用「单行三步」**（2026-10-12 实测）：
  有些脚本（如 `ops_hr_daily_reporting_20261012.sql`）注释里会写「只暂停 9606，保存新 cron，再启动；**不刷新/启动全部任务**」——
  此时**不要**图省事跑 `refresh-jobs`（它会对全部行 `addOrUpdateJob`，把不相关的运行态一起重登记）。等价且外科式的三步：
  ```bash
  B=http://127.0.0.1:9999/admin; TOK=$(...)      # 登录见 §4
  # ① status=1（已发布）的新任务：start-job 恰好走「新建」分支（见上表 * 的枚举 bug）⇒ 一次即可注册
  curl -s --noproxy '*' -X POST -H "Authorization: Bearer $TOK" $B/sys-job/start-job/2026101201
  # ② status=2（运行中）且只改 cron 的任务：暂停 → 保存 → 启动（PUT 时 status=3 才走 addOrUpdateJob 刷新触发器）
  curl -s -H "Authorization: Bearer $TOK" $B/sys-job/9606 > /tmp/job.json     # 取全行
  curl -s --noproxy '*' -X POST -H "Authorization: Bearer $TOK" $B/sys-job/shutdown-job/9606
  curl -s --noproxy '*' -X PUT  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
       -d "$(python3 -c "import json;d=json.load(open('/tmp/job.json'))['data'];keep=('jobId','jobName','jobGroup','jobOrder','jobType','className','methodName','methodParamsValue','cronExpression','misfirePolicy','jobStatus','jobExecuteStatus','remark');print(json.dumps({k:d.get(k) for k in keep}))")" $B/sys-job
  curl -s --noproxy '*' -X POST -H "Authorization: Bearer $TOK" $B/sys-job/start-job/9606
  ```
  ⚠️ 只 `shutdown` 后直接 `start`（不 PUT）**不会**刷新已存在触发器的 cron（`startJob` 对 status=3 只 `resumeJob`）。
  判据：`qrtz_triggers.NEXT_FIRE_TIME` 换成新 cron 的时间点（本轮 9606 `0 45 9` → `0 0 10`，next fire 第二天 10:00 ✅）。
- 🔴 **增量 SQL 也可「只施 delta」而不重置库**（2026-10-12 实测）：用户只说「重新构建/重启」时**不要顺手删卷**（会抹运行期数据）。
  本轮合并带入的 4 个脚本都自带幂等守卫（`CREATE TABLE IF NOT EXISTS` / `ON DUPLICATE KEY UPDATE` / `INSERT IGNORE`）⇒
  直接用 `docker exec -i linmo-mysql mysql -uroot -proot pig < pig/db/<file>.sql` 逐个施（顺序照 `initdb-loader.sh` 的 `ORDER`），
  再按需 `start-job` / 单行三步，即可让新表+新菜单+新任务在运行库就位。**前置**：先 `mysqldump --all-databases` 备份（14MB 级，秒级）；
  **别忘**清 `gl:menu_details*`/`gl:user_details*`（新菜单不生效的头号原因）。

```bash
# 判据：应为「已启动任务数」而非 0
$D exec linmo-mysql sh -c 'mysql -uroot -proot -N -e "use pig; select count(*) from qrtz_triggers;"'

TOK=$(cat output/pig-token.txt | tr -d '\n')   # 登录见 §4 —— ⚠️ 不要用 tools/pig_login_enc.py（缺 redis 模块会在 import 阶段就失败），用 §4 的内联 node AES + curl
# ① 先刷新：为所有 status 2/3 的行建/重建触发器（这一步就能覆盖 9601~9610）
curl -s --noproxy '*' -X POST -H "Authorization: Bearer $TOK" http://127.0.0.1:9999/admin/sys-job/refresh-jobs
# ② 再按「重置前状态」把该跑的行拉到运行中（本仓常态 = 9601~9610 运行，9301/9302 暂停）
for id in 9601 9602 9603 9604 9605 9606 9607 9608 9609 9610; do
  curl -s --noproxy '*' -o /dev/null -w "start-job/$id %{http_code}\n" -X POST \
    -H "Authorization: Bearer $TOK" http://127.0.0.1:9999/admin/sys-job/start-job/$id
done
```

- 🔴 **重置前状态不是「全都该启动」**：从备份的 `sys_job` 读 `job_status`（列序：`job_id, job_name, job_group, job_order, job_type, execute_path, class_name, method_name, method_params_value, cron_expression, misfire_policy, **job_status = 第 12 列 / 0-based f[11]**`，值带引号 ⇒ 判 `"'2'"` 不是 `"2"`）。2026-10-07 实测基线 = **10 运行（9601~9610）+ 2 暂停（9301/9302）** ⇒ `qrtz_triggers` = **12**。
- ⚠️ 别把 `tools/restore_tables_from_backup.py` 的产物导进临时库做「只看状态」——产物自带 `USE \`pig\`;` ⇒ 会直接写回 `pig`（`--ignore-all` 时静默无效果，看似「没反应」）。要读备份里的表，先 `INSERT IGNORE` 到 `_bak` 再**检查 `_bak` 是否真的非空**。

- 🔴 **接口路径**：controller 是 `@RequestMapping("/sys-job")`，前端写 `/job/sys-job/...` 但 `adaptationUrl()` 会**丢掉 `job` 段** ⇒ 真实路径 **`/admin/sys-job/start-job/{id}`**。
- 期望：`sys_job.job_status` → **2**，`qrtz_triggers` 出现 9601~9609 共 9 行且 `next_fire_time` 排定。
- 🔴 **`method_params_value` 与 job 类方法签名必须配对**：非空 → `getDeclaredMethod(name, String.class)`；为空 → `getDeclaredMethod(name)` **无参**。留空而类里只有 `trigger(String)` ⇒ 每次触发记「定时任务 spring bean 反射异常方法未找到」。`pig-ops` 7 个 job 原本都只有 `trigger(String)`，仅 `DwEtlJob`(9605，params 为空) 补了无参重载。
- 🔴 **已知存量缺陷（2026-10-09 复测，重置不修复）**：**9601 `经营智能体-采集触发`（cron `0 */5 * * * ?`）每 5 分钟必失败** —— `sys_job` 9601 的 `method_params_value` 是 **NULL**，而 `OpsSyncTriggerJob` 只有 `trigger(String params)`（`pig/pig-ops/.../job/OpsSyncTriggerJob.java`）。判据：`sys_job_log` 里 9601 连续 `job_log_status=1` + `exception_info='定时任务spring bean反射异常方法未找到,执行任务：opsSyncTrigger'`（备份 dump 里已有 **78 次** ⇒ **非任何一轮重置引入**，别当成本轮回归）。9603/9606/9613 等带非空 params 或已补无参重载的都正常。
  **不要**在「重建+重置」这类自动化里顺手改它（属产品语义决策：无参时该采集全部还是空跑）——**如实报**并把修法交给用户：给 `OpsSyncTriggerJob` 加 `public String trigger() { return trigger(null); }`，或给 9601 补 `method_params_value='{}'`；两者改完都要**重建 pig-boot + 同步 `pig/db` 种子**，否则下轮重置又回退。
  - ✅ **2026-10-14 复核：该缺陷已在代码层修复，上文「P1 未改」作废。** `pig/pig-ops/src/main/java/com/pig4cloud/pig/ops/job/OpsSyncTriggerJob.java` 现已有 `public String trigger()`（第 52 行，与 `trigger(String)` 并存），`DwEtlJob` 同款（`DwEtlJob.java:89`）。判据（30 秒可复验）：`grep -nE 'public String trigger' <class>.java` 应出现**两个**重载。⇒ **收尾时可以直接 `start-job 9601`，不必再回避它**；仍留 `method_params_value=NULL` 只是「无参=采集全部还是空跑」的语义未拍板，不再造成异常日志。
- 🔴 **「重置前状态」≠「健康状态」：备份里 `qrtz_triggers` 可能是 0 行**（2026-10-14 实测）。本轮备份 dump 里只有 `INSERT INTO \`qrtz_locks\``，`qrtz_triggers`/`qrtz_job_details` **一条 INSERT 都没有** ⇒ 上一轮「只换 mysql 镜像、不重置库」之后触发器**从未注册**，`job_status=2` 的行实际根本没在跑，而 `sys_job` 表看上去一切正常。
  ⇒ 判据：`grep -c 'INSERT INTO \`qrtz_triggers\`' <备份dump>`（0 = 重置前就没注册）。
  ⇒ 处置：**不要**以备份的触发器数为「目标状态」照抄；直接按本仓常态拉起（`refresh-jobs` + `start-job 9601~9610`，9301/9302 保持暂停）并在报告里**如实说明这是修复而非回退**。期望 `qrtz_triggers` = 11（9601~9610 + 9614，WAITING）+ 2（9301/9302，PAUSED）= **13**。
- 🔴 **2026-10-12 实测补全：改完为什么"不生效"** —— 光 `UPDATE sys_job SET method_params_value='{}'` **不够**。Quartz JDBC JobStore 把**排程当时的 `SysJob` 序列化快照**存在 `qrtz_job_details.JOB_DATA` 列里，而 `PigInitQuartzJob` 启动**只 `resumeJob`、从不刷新 JobDataMap** ⇒ 改了 `sys_job` 表但触发器仍拿旧参数跑。**正解 = `POST /admin/sys-job/refresh-jobs`**（内部走 `addOrUpateJob` 重新登记）。判据：refresh 后 `sys_job_log` 连续两次 `job_log_status=0`（本轮 12:00 / 12:05 两次通过）。
  ⇒ 推广判据：**任何「改 `sys_job` 行参数」的场景都要走 refresh-jobs**，别只改表或只重启服务；只重启只能给 `status=2/3` 的行补触发器，不会更新已存在触发器的 JobDataMap。
- ⚠️ **给 job 方法加「无参重载」时的编译坑（2026-10-12 实测）**：新写的 Javadoc 里若出现 `{@code 0 */5 * * * ?}` 这类**含 `*/` 的 cron 字面量**，`*/` 会**提前闭合注释块** ⇒ `mvn` 报一串极具误导性的假错（`illegal start of type` / `illegal character: '\u21d2'`），看着像语法都被写坏了。**cron 一律用纯文本描述，不要放进 `{@code}`**。
- 立即验证（**注意 9601 会失败，改用 9603/9605**）：`run-job/9603` 让 `ops_metric` 补上当日快照（否则页面 `statDate` 停在上次采集日）；`run-job/9605` 跑数仓。另外**只有 `0 */5` 表达式的 job（9601/9613）会在重启后几分钟内自己触发**，其余（9602~9610）是定点 cron（07:15 / 10:00 / 18:30…）⇒ 重启后 `sys_job_log` 里看不到它们的新记录属**正常**，别据此判定失败。

- 🔴 **「新增一条 sys_job 任务」的场景（2026-10-10 实测，与重置无关但同一坑）**：新行**写 `'2'` 是不够的** —— 启动阶段只摘/恢复/暂停、**从不新增**，写 `'2'` 后点「启动」走 `resumeJob` 分支**静默不注册**，现象是「列表里有这一行，点立刻执行返 code=1」，日志 `Couldn't store trigger ... The job (OPS.<job_name>) referenced by the trigger does not exist.`。两条等效路**二选一、不可混用**：①**建行写 `'1'` + 点一次「启动」**（`ops_agent.sql` 簇 9 的既有口径，本次 9614/9615 照此）；②**写 `'2'` + `refresh-jobs`**。另：落 SQL 时 `ON DUPLICATE KEY UPDATE` **不要更新 `job_status`**（否则重放把 `'2'` 打回 `'1'`，下次重启被 removeJob 摘掉）；`job_order` 是 `char(1)`（写 `'20'` 报 `ERROR 1406 Data too long`）；job key = `(job_name, job_group)` ⇒ **改 `job_name` 等于换任务、会丢注册**。
- 🔴 **重置后 `sys_job` 会比「重置前」少行（2026-10-12 实测：备份 38 → 种子 37）——这些是种子缺口，不是回灌错**：
  · `9614 新媒体智能体-运营日报` / `9615 研发智能体-研发日报`：本分支 `pig/db` **没有任何脚本定义**（`grep -rn 9614 pig/db/**/*.sql` 无命中）。
  · `9616 经营智能体-日报JEV预热`：`ops_agent.sql` 用 **9605** 登记 JEV，而 `pig_dw_menu_quartz.sql` 先 `DELETE FROM sys_job WHERE job_id = 9605` 再插自己的 `9605 经营智能体-数仓加工` ⇒ **JEV 整行被挤掉**；重置前库里的 9616 是历史运行时改名产物。
  · 处置：按备份 `INSERT IGNORE` 补回这三行（业务键 = `job_id`），**并如实报「应补可重放脚本 + 登记 ORDER」，否则每轮重置都要靠回灌**。
- 🔴 **种子 ORDER 会覆盖别的脚本对 `sys_job` 的 UPDATE（2026-10-12 实测）**：`ops_hr_daily_reporting_20261012.sql`（ORDER **437** 行）把 `9606` 改成 `0 0 10 * * ?`，但 `ops_daily_brief_job.sql`（ORDER **584** 行）又把它写回 `0 45 9 * * ?` ⇒ **重置后 9606 必然回退**。判据：重置后拿 `sys_job` 逐行与备份比对 `cron_expression`；修法是调 ORDER 或让后者承担最终值。
- 🔴 **数仓 9605「跑成功但 DWD 还是空」**：`DwEtlJob.trigger("")` 走 `DwAutoEtlCoordinator` 智能兜底，**20h 内且无新数据变化会跳过**，日志 `[DW-ETL] 数仓归集跳过：距上次加工 Nmin（不足陈旧阈值 20h），且无新数据变化`，而 `sys_job_log` 仍记「执行成功」⇒ 极易误判成「跑过了但没数据」。强制重算：`UPDATE sys_job SET method_params_value='yyyy-MM-dd' WHERE job_id=9605` → `run-job/9605`（`trigger(String)` 绕过兜底直连 `DwEtlService.run(date)`）→ **跑完把该字段清空**。

### ③ 重生成「模拟数据」域（不做 ⇒ 项目/财务/行业智能体页永远「暂无数据」）

`ops_simu_project_gantt|milestone`、`ops_simu_fin_daily`、`ops_simu_industry_item`、`ops_simu_crm_*` 是**后端模拟器按域现生成**的，`pig/db/**/*.sql` 里只有建表 DDL、**没有任何种子行**。⚠️ 但「备份回灌对它无效」只在**备份取自未重生成过的库**时成立 —— 2026-10-09 实测备份里带着完整 4 域 899 行 ⇒ **先跑无参 `tools/seed_ops_simu.py` 诊断**：行数全非 0 就说明①已带回，**跳过本步**（避免无谓重生成）。确有空域才走 API 补：

```bash
# 只诊断：列出域与各表行数（空域会直接给出补数据命令）
python3 tools/seed_ops_simu.py

# 重置后补空域（幂等：模拟器内部 deleteBySource + insert）
python3 tools/seed_ops_simu.py --domain project finance industry
# market 域必须显式 --accounts（preset 默认 1 万客户/12 万跟进，演示库用 27 客户档）
python3 tools/seed_ops_simu.py --domain market --accounts 27
```

- 页面表现：`/ops/agent/index` 点「项目智能体」→「暂无项目甘特数据：可在「模拟数据管理」触发 project 域」；财务/行业同款文案。**这是「数据未生成」而非前端 bug**（接口 200、`data.empty=true`），别去改前端。
- 判据：`GET /admin/ops/simu/domains` 各行数；或 `GET /admin/ops/agent/project/overview` 的 `data.empty` 由 `true` 变缺省。
- 🔴 **七智能体「取数端点」口径（2026-10-10 实测，乱试会得 3 个假 404）** —— 只有 3 个在 `OpsAgentController` 下：
  | 域 | 端点 |
  |---|---|
  | project | `GET /admin/ops/agent/project/overview` |
  | finance | `GET /admin/ops/agent/finance/overview?days=30` |
  | newmedia | `GET /admin/ops/agent/newmedia/overview` |
  | hr | `GET /admin/ops/agent/hr/overview?days=30`（**独立 controller** `OpsHrAgentController`） |
  | industry | `GET /admin/ops/agent/industry/panel`、`/admin/ops/agent/industry/intel/overview?period=30` |
  | market | `GET /admin/ops/market/overview?days=30&refreshAi=false`（**不在 `/ops/agent/` 下**） |
  | rd | **没有独立 overview** ⇒ `GET /admin/ops/home/overview?agentCode=rd` |
  期望：全部 `200` 且 `data.empty` 不为 `true`。`/ops/agent/{code}/panel` 对多数域是 404，别当缺陷。
- 🔴 **market 千万别裸跑**：`CrmSimPreset.defaults()` 是 1 万客户 / 12 万跟进，不带 `--accounts` 会把演示库撑大（本工具已内置拒绝执行）。
- 项目域的 `plan_start = 今天 + 偏移`，所以**生成数据带当天日期**，重置后必须重生成才不「过期」——不要试图固化成静态种子 SQL。
- 🔴 **`newmedia` 域不吃模拟器，重置后必「空窗」**（2026-10-14 实测）：`pig_dw.dwd_media_account_daily` / `dwd_media_work` 是 **DW ETL 派生表** —— `pig/db/06_menu_perm_patch.sql` 只 `CREATE TABLE`、**无 INSERT**，所以重置库只建空表 ⇒ 接口走 `empty=true` 分支，输出「上游尚未入湖：…需 xdy-collector 先推送」（`OpsAgentController.java:336-351`）。补数据两条路：① 等本机 launchd `com.linmo.xdy-collector`（每天 **09:00 / 21:00** 跑 `~/WorkBuddy/2026-10-09-18-06-59/xdy-collector/run_pipeline.sh`）推送 + 自动 ETL；② 立即手动 —— **先查 `pig_dw.ods_xdy_account_trend` 行数**：**>0 就只需 `POST /admin/ops/dw/etl/run`**（`ops_dw_exec`，幂等，DELETE+INSERT 重算）；**=0 才需要跑 `run_pipeline.sh`**。
  - 判据：`SELECT COUNT(*) FROM pig_dw.dwd_media_account_daily;`（空 ⇒ 页面空态）；上游 `SELECT COUNT(*) FROM pig_dw.ods_xdy_account_trend;`
  - ⚠️ 采集器 `push_to_linmo.py` 的 `base_url` **只指 `127.0.0.1:9999`** ⇒ 线上/远程环境收不到推送，会**持续**空。诊断「ODS 有量、DWD 无」时**别去查采集器**——那是 ETL 未重算。

### ④ 回灌「AI 应用配置」与「配置快照」（不做 ⇒ AI 控制台少一批应用 / 用户自建的回滚快照全丢）

`ai_app_config` 只有**部分**在种子里（2026-10-07 实测：种子 58~59 行，运行时同步/手工新增后为 **70** 行）；
`ai_app_config_snapshot`（用户点「快照与回滚」攒下来的）**完全不在种子**里 ⇒ 删卷即丢。§2.5 ① 的表清单没列它们，
**必须单独补**：

```bash
python3 tools/restore_tables_from_backup.py \
  --backup output/db-backup/<TS>/all-databases.sql \
  --out    output/db-backup/restore-ai-cfg-<TS>.sql --ignore-all \
  --table pig.ai_app_config pig.ai_app_config_snapshot
$D exec -i linmo-mysql mysql -uroot -proot < output/db-backup/restore-ai-cfg-<TS>.sql
# 判据：ai_app_config 回到 70 / ai_app_config_snapshot 非 0
```

- 🔴 列名坑：该表**没有** `app_key` 列（是 `api_key_cipher` / `dataset_key_cipher`）⇒ 想「按 key 判断是否丢失」时
  用 `left(api_key_cipher,6)`，别写 `app_key`（会直接 1146/1054 报错，但被 `2>/dev/null` 吞掉 ⇒ 假报 0 行）。
- 验证方式：`GET /admin/ai/apps/page` 应 200，`total` ≈ 67（分页接口按 `del_flag=0` 过滤，比表行数少）；
  记录里 `apiKeyMask` 形如 `app-****FvcX` ⇒ **密文回灌且能正常解密**。另 `GET /admin/ai/apps/snapshots` 应 200。
- 控制器实际路径 = **`/admin/ai/apps/**`**（`AiAppConfigController @RequestMapping("/ai/apps")`；`/admin/ai/app`、`/admin/ai-app` 都是 404）。
- 🔴 **2026-10-14 实测：`ai_app_config` 回灌不能按 `id` 整行搬** —— 该表有**两条函数式唯一键**
  `uk_app_tenant_live(app_code,tenant_id)` 与 `uk_dify_app_live(tenant_id,dify_app_id)`（都带 `del_flag='0'` 条件），
  且**分支间 `id → app` 映射会漂移** ⇒ 整行 `REPLACE/INSERT` 必撞 `ERROR 1062`。
  正确口径：**按 `app_code` 只同步运行期字段**
  （`enabled / api_key_cipher / dataset_key_cipher / base_url / model_code / dify_status /
  dify_updated_at / sync_source / sync_time / version / update_time`），`del_flag`/`dify_app_id` 不动；
  一个 `app_code` 有多条活行时用
  `ROW_NUMBER() OVER (PARTITION BY app_code ORDER BY sync_time DESC, id DESC)` 取第一条。
  判据：`app_code` 级不一致 = 0；且 **`ai_app_config` 里 `enabled=1` 的条数应 == python-ai `/health`
  的 `config.apps` 长度**（本次两者都是 **64**）—— 这是最快的交叉校验。
- 🔴 **`ai_app_config` 现状基线（2026-10-14）**：总 89 / 活 76 / `enabled=1` **64** / 有密钥 **63**、
  无重复 `dify_app_id`。老文档里的「回到 70」是旧口径，**以 python-ai `/health` 的 `apps` 长度为准**。
  （2026-10-21 快照换代后基线 = 总 **101** / 活 82 / enabled **70** / 有密钥 **63** / python-ai apps **61**。）
- 🔴🔴 **补插缺失 app 行时绝不能带 `id` 列**（2026-10-21 实测，症状极隐蔽）：快照换代后 `id → app_code`
  映射整体位移（备份 `id=111` 是 `aqiang-20261016`，现库 `id=111` 是 `dify-5ada4452`）⇒
  `INSERT IGNORE ... (id,...)` 撞**主键**被静默跳过，**命令零报错、行数一点没变**，极易误判成「已经补进去了」。
  ✅ 做法：生成 INSERT 时剔除 `id`，让 AUTO_INCREMENT 分配；执行后必须用
  `select count(*),sum(del_flag='0'),sum(enabled='1'),sum(api_key_cipher is not null) from ai_app_config` 逐项对备份。
  ⚠️ 余下补不进去的唯一常见原因 = `uk_dify_app_live(tenant_id,dify_app_id)` 撞键（同一 Dify 应用被两个
  app_code 引用，历史脏数据）⇒ 保留先到者、在报告里如实写明「少 N 行 + 原因」，不要强行改 `del_flag` 凑数。

### ⑤ 复核「权限点 → 角色」绑定（不做 ⇒ 页面报「XX 无权访问」/ 接口 403）

`sys_role_menu` 只是**种子里的一份快照**：事后通过 UI「角色管理 → 授权」加的绑定不在种子里，重置即回退。
更隐蔽的一种：**建权限点的脚本故意不授权**（`20260930_finance_agent.sql` 注释写死 `No automatic role grant`）⇒
「权限点存在、但任何角色都没有」⇒ 接口恒 403，且**重置前后一个样** —— 别误判成「重置弄丢的」。

```bash
# 判据：库里存在、却没有任何角色绑定的权限点（menu_type=1）
$D exec linmo-mysql sh -c 'mysql -uroot -proot -N -e "use pig;
SELECT m.menu_id,m.permission FROM sys_menu m
LEFT JOIN sys_role_menu rm ON rm.menu_id=m.menu_id
WHERE m.menu_type=1 AND m.del_flag=0 AND rm.menu_id IS NULL;"'
```

- 命中即「有权限点、没授权」⇒ 页面表现为「XX 无权访问」，接口返回 `403 {"msg":"权限不足，不允许访问"}`。
  🔴 该文案出自 `GlobalBizExceptionHandler` 的 `AccessDeniedException` 分支，**不是**前端 i18n ⇒
  在前端源码/构建产物里 grep「无权访问」**恒 0 命中**，别因此以为问题在后端别处。
- 修法：`INSERT INTO sys_role_menu(role_id,menu_id)` 授给目标角色 → 清 Redis `gl:*` 权限缓存 → **重新登录换 token**
  （旧 token 的 authorities 不会自动刷新）→ 复测接口由 403 变 200；并**补一个可重放 `pig/db/**/*.sql` + 登记
  `initdb-loader.sh` + 重建 MySQL 镜像**，否则下次重置又丢。
- 样例：2026-10-07 `ai_finance_view/run/edit/handle/admin`（menu_id 96801~96805）零绑定 ⇒ 财务智能体页签恒 403。

### ⑥ 🔴 写「合并脚本迁移基线」（2026-10-14 起必做；不做 ⇒ 在线升级页把 6 个脚本整批重跑）

`pig/db` 自 2026-10-14 收敛为 **6 个合并脚本**后，在线升级页
（`DbUpgradeService` 扫 `classpath*:db/**/*.sql`，按 `sys_db_migration.script_name + checksum` 判幂等）
会把这 6 个当成「新脚本」**全量重跑** —— 慢，且 `20261010_media_dwd.sql` 等有**非幂等副作用**。

```bash
# 生成器从**实际 pig/db/*.sql** 算 sha256 + file_size，避免手抄漂移（脚本在 output/，gitignored）
python3 output/db-backup/gen_migration_baseline.py --out output/db-backup/migration-baseline.sql
$D exec -i linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" pig' < output/db-backup/migration-baseline.sql
# 判据：6 个文件全部 status=SUCCESS / cost_ms=0 / executed_by=baseline，且 FAILED 计数 = 0
```

- 🔴 **`02_ai_platform.sql` 的现有已知缺口**：在**已填充运行期数据**的库上重跑它必炸
  `ERROR 1062 Duplicate entry '<tenant>-<uuid>' for key 'ai_app_config.uk_dify_app_live'`。
  根因 = `ai_dify_app_seed.sql`（02 内）的守卫是 `NOT EXISTS(app_code + tenant_id)`，
  **不查 `dify_app_id`**；当运行期行以**另一个 `app_code`** 占了同一 `dify_app_id`（实例：
  运行期 `zentao-tasks-fetch` vs 种子 `dify-70b5cd41` 共用 `70b5cd41-…`）⇒ 守卫放行、撞唯一键。
  **全新 initdb 不受影响**（空表）；只有「在已填充库上重跑」才炸。基线登记可规避；
  根治须改 `pig/db_bak/ai/ai_dify_app_seed.sql` 守卫（追加 `dify_app_id` 维度）→ 重跑
  `tools/consolidate_db.py` → 提交 `pig/db_bak/` + `pig/db/`（**勿直接编辑生成物**）。
- 该基线**只在库里记账、不落 `.sql`** ⇒ 属于「重置后收尾」而非种子；每次重置库后都要重写一遍。
- 🔴🔴 **checksum 会随 `pig/db` 每次重生成而必然失配，且「回灌备份」也救不回来**（2026-10-14 实测）：
  本轮 `sys_db_migration` 里 6 条基线是从备份回灌进来的，看着「已在」，但 checksum **6/6 全不符** ——
  因为 `pig/db` 在 22:20 被 `tools/consolidate_db.py` 重生成过（ORDER 补登记 + 正文修正），
  文件内容变了（`06_menu_perm_patch.sql` 字节数 1840000 → 1847902）。
  ⇒ **判据不是「台账里有这 6 行」，而是逐条比 `checksum` + `file_size`**：
  ```bash
  $D exec linmo-mysql sh -c 'mysql -uroot -proot -N -B pig -e "select script_name,checksum,file_size from sys_db_migration where script_name like \"0%_%.sql\";"' > /tmp/mig_db.txt
  for f in pig/db/0*.sql; do printf '%s|%s|%s\n' "$(basename $f)" "$(shasum -a 256 $f|cut -d' ' -f1)" "$(stat -f %z $f)"; done   # 与 /tmp/mig_db.txt 逐条比
  ```
  ⇒ **凡是重生成过 `pig/db` 的那一轮，第 ⑥ 项必须重跑**（`gen_migration_baseline.py` 是 `INSERT … ON DUPLICATE KEY UPDATE`，会自动纠正 checksum）；不跑的话在线升级页会同时列出 6 条「已变更」待重跑。

---

## 2.7 🔴 构建/工具环境的三个必踩坑（2026-10-14 实测）

**① 全缓存重建后 `标签 ↔ 容器` 会漂移，`up -d` 不换容器**
`compose build` 即使**全层 CACHED**，BuildKit 也会生成**新的镜像 ID**（新 config blob）⇒
`linmo/pig-*:1.0.0` 标签指向新 ID，而**容器仍挂在旧 ID**；此时 `compose up -d` 判定
「Running」**不会**重建。对齐办法：

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file deploy/.env.dev --env-file deploy/.env \
  --profile pcui up -d --force-recreate --no-deps pig-gateway python-ai pig-ui pig-pc-ui
# 判据：5 个容器 容器.Image == 镜像.Id 全部 SAME
```

（服务名 `redis / pig-gateway / python-ai / pig-pc-ui / pig-ui / env-applier`；**`pig-gateway` ≠ 容器 `linmo-pig-boot`**。）

**② `tools/local_env.py` 优先读 `deploy/.env.aqiang`（个人文件），其 `HOST_REDIS_PORT=6379` ≠ 本机实际 6380**
⇒ `tools/pig_login.py` 等默认连 6379，报 `redis.exceptions.ConnectionError: Error 61 …
127.0.0.1:6379 Connection refused`。**跑工具前先覆盖**：

```bash
HOST_REDIS_PORT=6380 python3 tools/pig_login.py admin 123456
```

**③ `tools/verify_mysql_initdb.py` 报 `❌ initdb 执行完成 状态=timeout 耗时=301 秒` 是假失败**
它的等待上限 300s 比本机 initdb 实际耗时短；**loader 日志已打印「初始化完成：成功导入 6 个脚本，
拒绝 0 个」即已成功**。判 initdb 健康**看 loader 日志行**，不看这一项断言。

---

## 2.8 🔴 改后端「正则清洗 / 文本处理」代码的两个必踩坑（2026-10-14 实测）

**① Java 源码注释里出现裸 `\u` 会直接编译失败**
Java 的 `\u` 是 **Unicode 转义**，在**词法分析之前**处理 —— 连注释里的 `\u` 也算。
注释里顺手写「避开编译期的 `\u` 预处理」这类话（`\u` 后面不是 4 位 hex）⇒
`[ERROR] …OpsAgentController.java:[1049,65] 非法的 Unicode 逃逸`。
- **规避**：注释/文案里不要出现裸 `\u`（改写「Unicode 转义预处理」）；正则里表达汉字区间用
  `[\x{4e00}-\x{9fa5}]`（`\x{...}` 不被预处理），**别写** 裸 `\u4e00`。
- 改完全文件自查：`grep -n '\\u' <file>` 的命中应只剩合法的 `\uXXXX`。

**② Python 预演 Java `\b` 文本清洗时必须加 `re.ASCII`**
`\b` / `\w` 的**字符集不同**：Java `\b` 是**纯 ASCII** 词边界，Python 3 默认 `\w` **含中文** ⇒
英文与中文粘连（如 `远程dev并`）时 Python 认为 `dev` 仍在「词内」⇒ **漏删**，Java 则照删。
两级预演会给出**假一致**结论。**预演脚本一律** `re.compile(pat, re.ASCII)`，或把边界显式写成
`(?<![A-Za-z0-9_])` / `(?![A-Za-z0-9_])`。判据：同一段输入在两边的输出**逐字符相同**才算对齐。

---

## 2.6 🔴 重置后必查：`sys_job` 的 `job_id` 撞号（2026-10-07 全新建库实测）

`sys_job` 主键是 **复合键 `(job_id, job_name, job_group)`** ⇒ **`job_id` 本身没有唯一约束**。
两个脚本给不同名字的行用同一个 `job_id` 时，**两行都会入库、initdb 报告"成功"**，但
`getById(jobId)` 变成 `selectOne` 撞两行：

```
POST /admin/sys-job/start-job/9610 → 500
{"msg":"Expected one result (or null) to be returned by selectOne(), but found: 2"}
```

该 id 的 `start-job` / `run-job` / `shutdown-job` **三个接口全废**（前端「定时任务」页点不动）。
**只在全新建库时出现**（旧运行库往往只有其中一行）⇒ 是重置独有的坑。

```bash
# 判据：应为空。非空即撞号，先修再启动任务
$D exec linmo-mysql sh -c 'mysql -uroot -proot -N -e "use pig;\
  select job_id,count(*) c from sys_job group by job_id having c>1;"'

# 定位：哪个脚本用了这个 id（跨分支合并最容易撞）
grep -rn "VALUES (<撞号>," pig/db/**/*.sql
```

- **处置**：改动面小的那一侧让位，换一个空号（`9611/9612/9613…`），并**一并更新注释 / docs 里的引用**；
  只改 SQL 不改实时库，运行库仍会撞号 ⇒ 别忘 `UPDATE sys_job SET job_id=<新号> WHERE job_name='<作业名>'`。
- **改完必须重建 MySQL 镜像**，否则下次 initdb 又把撞号带回来（校验：镜像内 `VALUES (旧号` 命中 0）。
- 2026-10-07 实例：`20261006_project_agent_sync_schedule.sql`（项目智能体-禅道数据采集）与
  `ops_intel_digest_job.sql`（行业智能体-情报研判日报）**都用 9610** ⇒ 让项目侧改成 **9613**
  （行业侧 9610 被前端文案 / Dify 工作流 / `application.yml` / 多处 docs 写死，不宜动）。

---

## 2.9 🔴 `compose build` 部分失败 ≠ 全部没建（2026-10-26 实测）

一次 `compose build`（4 个 target）里 `pig-gateway` 因 **apt-get（debian 源）`exit code 100`** 失败、整条命令 rc≠0，
但日志前段已经有 `naming to docker.io/linmo/pig-ui:1.0.0 done` / `pig-pc-ui … done` ⇒ **其它 target 的镜像是成功导出的**，
`python-ai` 则停在 pip 步骤未导出。判据与处置：

```bash
# ① 别只看 rc：逐 target 查镜像 Created/ID 是否已刷，或直接看 build 日志里的 "naming to … done"
docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}' | grep -E 'pig-boot|pig-ui|pig-pc-ui|python-ai'
# ② 失败的 target 单独重试（层已缓存，通常 10s 内过）
docker compose --env-file deploy/.env.liyuying --env-file deploy/.env \
  -f deploy/docker-compose-liyuying-v1.yml --profile pcui build pig-gateway
```

⚠️ **后台跑 build 时不要 `| tail -20`**（2026-10-26 实测）：整条日志被 tail 吞住，看不到进度，只能靠镜像
`Created` 是否刷新来猜，极易把「还在慢慢下依赖」误判成「卡死」。要么 `--progress plain > 日志文件 &` 再 `tail -f`，要么直接看
bg 任务的 stdout 落盘文件。

⚠️ **python-ai 的 `pip install` 是 `--no-cache-dir` + 无 cache 挂载**：一旦中止，下次**从头下载**。
本机到 `mirrors.aliyun.com` 实测约 **70 kB/s**（2026-10-26：构建 929s 才进 `Installing collected packages`）⇒
若本批 python-ai **只改了 Dockerfile 的构建期源、应用代码零改动**，正确做法是**不重建**（`up -d --force-recreate --no-deps python-ai`
用现存镜像即可），并在报告里如实说明；要用新镜像就换时段或 `--build-arg PIP_INDEX_URL=<更快的源>`。

---

## 3. 重启服务

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd /Users/shan/work/linmo-pig-full
docker compose -f deploy/docker-compose.dev.yml \
  --env-file deploy/.env.dev --env-file deploy/.env \
  --profile pcui up -d

# 等 boot 健康（约 15~60s）
for i in $(seq 1 36); do
  st=$(docker inspect linmo-pig-boot --format '{{.State.Health.Status}}')
  echo "[$((i*5))s] $st"; [ "$st" = healthy ] && break; sleep 5
done
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

**期望**：6 容器全 `healthy`（mysql 无 healthcheck），6 端口全 LISTEN。

- 🔴🔴 **`up -d --force-recreate --wait` 可能被中途打断，留下半残状态（2026-10-11 实测）**：
  一次前台长跑被中断后现场为 —— `linmo-pig-boot` **Exited(143)**、`linmo-redis` 停在 **Created**、
  另有一个重命名中间容器 `4578f80961cb_linmo-pig-boot`（Created），而 `docker ps` 里它们**全部不可见**
  （只有 `docker ps -a` 才看得到）⇒ 端口 9999 / 6380 **无监听**，但如果不查 `ps -a` 会误以为「服务都起来了」。
  **收尾必做**：`up` 之后**必须** `docker ps -a` 复核 6 个容器 + 逐端口 `lsof -nP -iTCP:<port> -sTCP:LISTEN`。
  修复：`docker rm -f <重命名中间容器> linmo-pig-boot linmo-redis` → 重跑
  `docker compose ... up -d --wait`（此时**不要**再加 `--force-recreate`，否则又全量重建容器）。
  ⚠️ 重启类任务优先用 `up -d --wait`（幂等、容器已在且镜像未变时几乎零动作）；只有确实要换镜像时才 `--force-recreate`。

### 🔴 坑
- 🔴🔴 **引擎重启后容器全空时，redis 必须比后端先起**（2026-10-24 实测）：`up -d --force-recreate --no-deps pig-gateway` 会在 redis 容器尚未创建时反复
  `java.net.UnknownHostException: Failed to resolve 'linmo-redis'`（`restart: unless-stopped` 循环重启，`docker inspect .State.Health.Status` 卡在 **starting 200s+**，
  极易误判成「后端启动慢/挂死」）。boot 日志里 3 次 `Application run failed` 全是这个原因，不是代码问题。
  ✅ 正确顺序 = **mysql → redis → pig-gateway（等 healthy）→ python-ai / pig-ui / pig-pc-ui → env-applier**；
  redis 起来后 boot 约 **18s** 即 healthy。判据：`docker logs <boot> | grep 'Failed to resolve'` 命中即为此坑。
- 后端探活真实路径是 **`/admin/`**（容器 healthcheck 用的就是它）；`/admin/actuator/health` 返 **404**，别据此判断后端挂了。`/admin/` 返 **424** 是白名单鉴权层的**预期值**，不是故障。
- 卷名是**固定 name**（`linmo-mysql-data` / `linmo-redis-data`），compose 里写了 `name:`，所以 redis 数据不会因重建容器而丢。
- 🔴 **每轮都要做「容器↔镜像 ID 比对」，`up` 一律带 `--force-recreate`**：只 `restart` 不比对会让容器长期跑旧镜像而仍 healthy。
  2026-10-08 实测事故：`linmo-pig-ui` 容器**整个缺失**（8888 无人监听）、`linmo-pig-pc-ui` 跑悬挂镜像 ID，两项都因此前只 restart 而潜伏 ⇒ 单纯「重启服务」的自动化任务必须顺手做这一步比对。
- **改完菜单/参数后清 Redis 缓存**（`gl:menu_details*` TTL=-1 永不过期，旧快照会让新菜单不生效）：
  ```bash
  docker exec linmo-redis sh -c 'for p in "gl:menu_details*" "gl:user_details*"; do redis-cli -n 5 --scan --pattern "$p" | xargs -r redis-cli -n 5 DEL; done'
  ```

---

## 4. 端到端验证（必做，否则等于没验证）

```bash
# 健康
curl -s --noproxy '*' http://127.0.0.1:8090/health                    # {"status":"UP",...}
curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8090/internal/v1/health
curl -s --noproxy '*' -o /dev/null -w 'ui=%{http_code}\n'   http://127.0.0.1:8888/
curl -s --noproxy '*' -o /dev/null -w 'pcui=%{http_code}\n' http://127.0.0.1:8890/
curl -s --noproxy '*' -o /dev/null -w 'ai=%{http_code}\n'   http://127.0.0.1:9999/admin/   # 期望 424
```

### 🔴 登录密码必须 AES 加密（否则永远 `bad_credentials`）

`pig-auth` 的 `PasswordDecoderFilter` 对 `password` 参数做 **AES-CFB / NoPadding（IV = key）** 解密，
密钥 = `security.encodeKey`，运行时由容器环境变量 `SECURITY_ENCODEKEY` 覆盖（**必须 16 字节**）。
**明文密码的解密结果必然错 ⇒ 报 `{"msg":"用户名不存在或者密码错误","data":"bad_credentials"}`，
这是解密失败，不是密码错。**

> 🔴 **`tools/pig_login_enc.py` 现已不可用（2026-10-12 实测）**：它 `from pig_login import main`，而 `tools/pig_login.py:38` 有 `import redis`
> ⇒ 环境无 `redis` 模块时**在 import 阶段即 `ModuleNotFoundError`、什么都不做**（旧记录"只打印一行读库失败、可忽略"**已不成立**）；
> 此时 `output/pig-token.txt` 里是**上一轮的旧 token**（若 Redis 会话未过期**照样能用**，极易误判成"新登录成功"）。
> ⇒ **改用下面的内联 node AES + curl**（零依赖、必得新 token）；要沿用该脚本先 `pip install redis`，或给 `tools/pig_login.py` 的 redis 导入加 try/except 兜底。

```bash
D=/Applications/Docker.app/Contents/Resources/bin/docker
NODE=/Users/shan/.workbuddy/binaries/node/versions/22.22.2-3/bin/node
K=$($D inspect linmo-pig-boot --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep '^SECURITY_ENCODEKEY=' | cut -d= -f2-)
ENC=$(K="$K" $NODE -e 'const c=require("crypto");const k=Buffer.from(process.env.K);
  const x=c.createCipheriv("aes-128-cfb",k,k);
  process.stdout.write(Buffer.concat([x.update(Buffer.from("123456")),x.final()]).toString("base64"));')

TOK=$(curl -s --noproxy '*' -X POST -u 'test:test' \
  --data-urlencode username=admin --data-urlencode "password=$ENC" \
  --data-urlencode grant_type=password --data-urlencode scope=server \
  http://127.0.0.1:9999/admin/oauth2/token | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')

# 业务校验（注意 context-path 已是 /admin，别再叠一层）
curl -s --noproxy '*' -H "Authorization: Bearer $TOK" http://127.0.0.1:9999/admin/user/info
curl -s --noproxy '*' -H "Authorization: Bearer $TOK" -H 'TENANT-ID: 1' \
  http://127.0.0.1:9999/admin/menu -o /tmp/menu.json
# 确定性口径（别用目测/别用 grep 数）：
python3 - <<'PY'
import json; d=json.load(open('/tmp/menu.json')); data=d.get('data') or []
def c(ns):
    n=len(ns)
    for x in ns: n+=c(x.get('children') or [])
    return n
print('顶级=%d 节点总数=%d' % (len(data), c(data)))
PY
```

**期望值（2026-10-06 15:55 实测，库冻结于当日 14:19 initdb）：顶级 6 / 节点总数 125**，
顶级名称 = `router.systemManagement / router.baseTools / 经营中心 / 企业管理 / router.platformDevelopment / AI 控制台`，
`经营中心` 下含 `/ops/**` 15+ 项（总览/报告/项目/智能体/灵猫AI/事项/分析/市场/行业/知识库/数据接入…）。
> 2026-10-09 实测基线已变为 **顶级 8 / 节点 142**（dev 合并带入新菜单）⇒ 该数随种子增长，**判据是「较上轮基线的增长可用当轮合并解释」，而非固定值**。

> ⚠️ 旧记录写的「顶级 7 / 节点总数 133」**勿再引用**（口径不明，实测复现不出）。
> ⚠️ 也**别拿库行数跟 API 节点数比**：`sys_menu` 未删 380 行（`menu_type` 0=125 / 1=255，`visible='1'` 隐藏 364），
> API 只返回可构树的那部分 ⇒ 两个数字本来就不该相等。

**免加密捷径**（仅测试用）：把 `sys_oauth_client_details.additional_information` 设为含 `enc_flag=0`，
该 client 即走明文（见 `PasswordDecoderFilter.isEncClient()`）。

### 🔴 坑
- 路径别叠 `/admin/admin/...`，context-path 已经吃掉一层。
- 默认凭据：`admin / 123456`；client 用 `test:test`（Basic）。
- sandbox 内 curl 走本机 IP 要加 `--noproxy '*'`。
- python-ai 启动后 30~90s 内 `/health` 里 `config.source=fallback` / `ConnectError` 是**启动竞态**（boot 还没就绪），自愈后变为 `source=pig`，不是故障。⚠️ 2026-10-10 实测**约 60s 才转 pig**（旧记录写「30s 后自愈」偏乐观）⇒ 启动后立刻复验见 fallback 属正常，**等 60~90s 再下结论**。

---

## 5. 收尾

- 报告落 `output/rebuild-reset-YYYY-MM-DD.md`。
- 备份留在 `output/db-backup/<TS>/all-databases.sql`；回滚 = `docker exec -i linmo-mysql sh -c 'exec mysql -uroot -proot' < <备份>`。
- 记忆：追加 `.workbuddy/memory/YYYY-MM-DD.md`（**append-only**，用 Python `'a'`/读取后拼接，并回读校验「原内容缺失行数 == 0」）；自动化专属记忆写 `.workbuddy/memory/automations/<automation-id>/memory.md`。
- 🔴 **两个副本（`work/` 运行栈 与 `works/` 记忆主目录）的同一份日报，禁止用 `cp` 单向覆盖**（2026-10-27 实测踩坑）：两侧段落集合不同，`cp` 会把目标侧独有段整段冲掉（本轮冲掉 work 侧「第 120 轮分支同步自动化」整段，靠 `git show HEAD:<file>` 才取回）。
  ✅ 正解 = **按 `## ` 段落做并集**：① `wc -c` 对比目标文件与 `git show HEAD:<file>`，相等说明目标侧无本地未提交内容、可安全以 HEAD 版为基底；不等则先备份目标文件再人工合；② 以「目标侧 HEAD 版」为基底，追加源侧独有段与本轮新段；③ 写后校验两侧段数一致、标题差集为空。
- **`git status --short` 非空（并行会话在途）时：不要提交、不要 stash/checkout**（会吞对方文件）。若要提交自己的记忆文件，用 `bash ~/.workbuddy/skills/git-quick-commit/scripts/git-fast.sh -m "..." --paths "a.md b.md"`（**`--paths` 是单参数、空格分隔**，只交自己那几个路径）。
- 红线：**不要动任何 `.env*`**（`deploy/.env.dev`/`.env.head`/`.env.mac` 仍被跟踪，属存量欠账，re-track / 脱跟踪 / 改写均需用户拍板）；推送前门禁 `git diff --name-only origin/<br>..HEAD | grep -E '(^|/)\.env'` 命中即停。

---

## 附：菜单「没出来」类问题的一条捷径（2026-10-16 实测）

页面/接口/前端产物都排查正常但用户说「菜单/页面没出来」时，**先查授权面再怀疑环境**：

```sql
-- 1) 菜单是否只授了管理员
select rm.menu_id, group_concat(r.role_code) from pig.sys_role_menu rm
join pig.sys_role r on r.role_id=rm.role_id
where rm.menu_id in (<父目录id>,<页面id>) group by rm.menu_id;
-- 2) 目标角色有哪些账号
select u.username, r.role_code from pig.sys_user u
join pig.sys_user_role ur on ur.user_id=u.user_id join pig.sys_role r on r.role_id=ur.role_id;
```

要点：
- **父目录（menu_type=0 的目录）必须与子页面一起授权**，否则前端按 parent_id 组树时整组消失；
- 授权 SQL 用 `INSERT IGNORE ... SELECT role_id FROM sys_role WHERE role_code='XXX'` —— **role_id 是雪花号跨环境不同，禁止硬编码**；
- 修复后：清 Redis db5 双缓存 + **用户必须退出重登**（菜单树登录时一次性下发）；
- 验证非管理员视角不必猜密码：临时把同角色某个账号的 password 更新为 admin 的 bcrypt 哈希（先备份原哈希、验证后逐字符恢复），再 Playwright 登录。
