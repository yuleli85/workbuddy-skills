---
name: pig-quartz-job-toggle
description: 在灵猫企管（linmo-pig-full / PIG）里「开启 / 暂停 / 改执行周期 / 立刻执行一次」任意一个 `sys_job` 定时任务，并把改动固化进 `pig/db_bak` 种子、实跑验证。当用户说「XX 定时任务请开启」「XX 任务每天只跑 N 次」「改一下这个任务的 cron」「为什么这个任务是暂停」「定时任务不跑 / 不生效」「打开定时任务」「关闭/暂停某任务」，或需要在「定时任务总览」/「系统管理 → 定时任务」页之外用命令行完成同类操作时使用。覆盖：① 任务定位与现状核查（sys_job / QRTZ_TRIGGERS / sys_job_log 三处对照）；② **取 token（267 私仓编排不发布 redis 宿主端口，pig_login 必须打薄壳）**；③ 改状态/周期的正误两种路径（`refresh-jobs` vs `start-job` 的枚举坑）；④ 立刻执行一次取真实报错；⑤ 种子固化 + `consolidate_db.py --verify` + 临时容器全新 initdb 实测；⑥ 提交与出站门禁。
agent_created: true
---

# PIG 定时任务：开启 / 暂停 / 改周期 / 立刻执行一次

## 0. 先记住三条（不记住必踩）

1. 🔴 **`job_status` 取值**：`1` = 已发布（**只是登记，不会调度**）｜`2` = 运行中｜`3` = 暂停｜`4` = 删除。对外说「开启」= 终态 `2` **且** `QRTZ_TRIGGERS` 里该任务触发器为 `WAITING`。**只看 DB 里的 `job_status=2` 不算开启** —— 没有触发器照样不跑。
2. 🔴 **改 cron 必须走 `POST /sys-job/refresh-jobs`**。只 `UPDATE sys_job.cron_expression` 不会动触发器里的 cron（`QRTZ_CRON_TRIGGERS.CRON_EXPRESSION`），任务仍按旧周期跑。
   - `refresh-jobs`：对 status `2`/`3` → `addOrUpateJob`（**建/重排触发器，cron 才生效**）；对 `1`/`4` → `removeJob`。
   - `start-job/{id}`：源码里把 `JOB_LOG_STATUS_FAIL`（`"1"`）当成 `JOB_STATUS_RELEASE` 来比 ⇒ **只有当前 status=`1` 时才走 `addOrUpateJob`**；status=`3` 时走 `resumeJob`，**触发器不存在就必然报「恢复任务失败」**，且它照样把状态改成 `2` ⇒ 出现「库说运行中、实际没触发器」的假态。
   - ⇒ 正确顺序：**先改 DB（cron + status=2）→ 再 `refresh-jobs`**。
3. 🔴 **种子里的「开启」值写 `job_status='1'`**（本仓惯例，见 `pig/db_bak/ops/ops_agent.sql` 簇 9）：新库没有 Quartz 触发器，写 `2` 只会在启动时留一行「恢复任务失败」；写 `1` 让运维点一次「启动」才真建触发器。

## 1. 现状核查（只读，先判后动）

```bash
cd <repo>
M() { docker exec deploy-mysql-1 sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"$1\"" 2>&1 | grep -v Warning; }
# ① 任务本体
M "SELECT job_id, job_name, cron_expression, misfire_policy, job_status, job_execute_status,
          class_name, method_name, remark FROM pig.sys_job WHERE job_id=<ID>\G"
# ② Quartz 实态（关键：trigger_state / next_fire_time / 触发器里的 cron）
M "SELECT t.trigger_name, t.trigger_state, c.cron_expression,
          FROM_UNIXTIME(t.next_fire_time/1000) next_fire, FROM_UNIXTIME(t.prev_fire_time/1000) prev_fire
   FROM pig.QRTZ_TRIGGERS t LEFT JOIN pig.QRTZ_CRON_TRIGGERS c
     ON c.trigger_name=t.trigger_name AND c.trigger_group=t.trigger_group
   WHERE t.trigger_name LIKE '%<任务名关键词>%';"
# ③ 最近执行结果（列名是 job_log_status 不是 status！）
M "SELECT job_id, job_name, job_log_status, LEFT(job_message,60), LEFT(exception_info,80),
          LEFT(create_time,19) FROM pig.sys_job_log WHERE job_id=<ID> ORDER BY create_time DESC LIMIT 5;"
```

- 三处口径对不上时的判决：`sys_job.job_status=3` 但触发器 `PAUSED` = 真正暂停；`job_status=2` 但**无触发器** = 假运行态（见 §0.2）。
- MySQL 容器名随机器而异（macOS 发布栈 `linmo-mysql`、Windows/私仓栈 `deploy-mysql-1`），`docker inspect -f '{{.State.Running}}'` 逐个探。

## 2. 取 token（267 私仓编排必看）

`tools/pig_login.py` 默认连 `redis://127.0.0.1:6380/5` 读验证码；**私仓镜像版编排不发布 redis（也不发布 mysql）宿主端口** ⇒ 必 `Connection refused`。

解法：把 `pig_login.REDIS` 换成「走 `docker exec deploy-redis-1 redis-cli -n 5`」的薄壳，其余（AES 加密、取验证码、换 token、解锁）全部复用，**不要重写登录逻辑**。脚本写到 `$HOME/<dir>/token_helper.py`（`/tmp` 不跨调用）：

```python
import os, sys, subprocess
from pathlib import Path
REPO = Path("<repo>"); sys.path.insert(0, str(REPO / "tools"))
os.environ.setdefault("PIG_BASE_URL", "http://127.0.0.1:9999/admin")
os.environ.setdefault("MYSQL_CONTAINER", "deploy-mysql-1")
import pig_login

class RedisViaDockerExec:                      # 只实现 pig_login 用到的 get/delete
    def _cli(self, *a):
        return subprocess.run(["docker","exec","deploy-redis-1","redis-cli","-n","5",*a],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    def get(self, key):
        p = self._cli("GET", key); out = p.stdout.rstrip("\n")
        return None if (p.returncode != 0 or out == "") else out.encode("utf-8", "replace")
    def delete(self, *keys):
        try: return int(self._cli("DEL", *keys).stdout.strip())
        except Exception: return 0

pig_login.REDIS = RedisViaDockerExec()
print(pig_login.encrypt_password("x"))         # 需要 node 在 PATH（受管 node 目录）
```

跑法（**node 必须在 PATH**，`enc_pwd.js` 复现前端 AES）：

```bash
PATH=/Users/shan/.workbuddy/binaries/node/versions/22.22.2-3/bin:$PATH \
  /Users/shan/.workbuddy/binaries/python/envs/default/bin/python $HOME/<dir>/token_helper.py admin 123456
# 期望 TOKEN_OK len=36（PIG 是 opaque token 不是 JWT）
```

## 3. 改状态 / 周期（执行）

```sql
USE `pig`;
UPDATE `sys_job`
   SET `cron_expression`='0 30 8,17 * * ?',   -- 每天 2 次；Quartz 6 段式，秒 分 时 日 月 周
       `job_status`='2',                      -- 开启；暂停写 '3'
       `update_by`='admin', `update_time`=NOW(),
       `remark`='…【说明何时为何改、当前已知阻塞】…'   -- remark 是 varchar(500)，改完必被后续人看到，别留空
 WHERE `job_id`=9301;
```

```bash
TOKEN=$(cat $HOME/<dir>/token.txt)
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:9999/admin/sys-job/refresh-jobs   # 期望 {"code":0,"ok":true}
sleep 3
# 复核：trigger_state 必须 WAITING（不是 PAUSED），next_fire 必须是新 cron 的下一个时刻
```

- **暂停**：`POST /sys-job/shutdown-job/{id}`（⚠️ 有副作用：会把「未启动(1)」错置成「暂停(3)」并留触发器）。要回到基线用 `UPDATE sys_job SET job_status='1'` + 重启 pig-boot，**别手删 `qrtz_triggers`**（FK `qrtz_cron_triggers` 报 1451）。
- **立刻执行一次**：`POST /sys-job/run-job/{id}` → 查 `sys_job_log`。`job_log_status=1` 时 `exception_info` 只有一句「定时任务springBeanTaskInvok业务执行失败」，**真原因必须去应用日志找**：
  ```bash
  docker logs deploy-pig-1 --since 5m 2>&1 | grep -E "定时同步失败|ConnectException|Exception"
  ```

## 4. 判「这个任务开了会不会真出数」（最容易漏的一步）

Bean 存在 ≠ 能跑通。很多任务的取数端是**外部连接器**，先确认可达再开：

- 看 bean 的 `@Value("${lingmao.<x>.connector-url:http://127.0.0.1:PORT}")`：
  ```bash
  grep -rn "connector-url" pig --include=*.java | grep -v target
  ```
- 探活要在**运行任务的容器内**探（`127.0.0.1` 在容器里指向容器自身，不是宿主）：
  ```bash
  docker exec deploy-pig-1 sh -c 'curl -s -m 2 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8767/health'  # 000 = 打不通
  ```
- 确认 bean 真在部署产物里：
  ```bash
  python3 - <<'PY'
  import zipfile, io
  z = zipfile.ZipFile("pig/pig-boot/target/pig-boot.jar")
  for n in [x for x in z.namelist() if "BOOT-INF/lib/pig-enterprise" in x]:
      print(n, [y for y in zipfile.ZipFile(io.BytesIO(z.read(n))).namelist() if "SyncJob.class" in y])
  PY
  ```
- 还要核**数据面**：`gh_*`/`zt_*` 等旧链路表是不是全 0 行、新链路 `ops_ext_*` 是不是有数（判断「采到了但没进旧表」还是「根本没采」）。
- ⚠️ 已知坑：`connector/{zentao,github}-service` 已于 `b84bea14` 删除 ⇒ 9301/9302 启动即 `ConnectException`。开之前先跟用户讲清楚，并把已知阻塞写进 `remark`。

## 5. 固化进种子（不固化 = 下次重置库静默回退）

1. 改 `pig/db_bak/<域>/<原注册脚本>.sql` 的 `cron_expression` / `job_status` / `remark`，**并在文件头加日期化的变更说明**（别删原有理由，保留备查）。
2. 顺手查 `DELETE` 范围：若写成 `WHERE job_id BETWEEN 9300 AND 9399`，**单独重跑该脚本会连带删掉同段其它任务**（如禅道脚本删掉 GitHub 的 9302）⇒ 收窄为 `= <自己的 id>`。
3. 重新生成 + 自检（`pig/db` 是生成物，禁止手改）：
   ```bash
   python3 tools/consolidate_db.py --verify   # 期望 RC=0 + 「自检通过」+ 合计 = ORDER 条目数
   git diff --stat pig/db                     # 只应看到包含该脚本那一个合并文件
   ```
4. **实跑一次全新 initdb**（临时容器 + 临时卷，绝不碰在用库）：
   ```bash
   mkdir -p /tmp/initdb-check && cp pig/db/initdb-loader.sh /tmp/initdb-check/zz-import-all.sh && chmod +x /tmp/initdb-check/zz-import-all.sh
   docker volume create tmp-initdb-vol
   docker run -d --name tmp-initdb-check -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=pig -e PIG_SQL_DIR=/opt/pig-db \
     -v tmp-initdb-vol:/var/lib/mysql -v <repo>/pig/db:/opt/pig-db:ro -v /tmp/initdb-check:/docker-entrypoint-initdb.d:ro \
     mysql:8.4 --character-set-server=utf8mb4 --collation-server=utf8mb4_general_ci --lower_case_table_names=1 --default-time-zone=+08:00
   # ~60~110s 后
   docker logs tmp-initdb-check 2>&1 | grep '\[pig-initdb\]' | tail -3   # 期望「初始化完成：成功导入 6 个脚本，拒绝 0 个」
   docker exec tmp-initdb-check sh -c 'mysql -uroot -proot -e "SELECT job_id,cron_expression,job_status FROM pig.sys_job WHERE job_id IN (<ID>);"'
   docker rm -f tmp-initdb-check && docker volume rm tmp-initdb-vol && rm -rf /tmp/initdb-check
   ```
   构造 `docker run` 前**先 `mkdir` 日志/挂载目录并 `chmod +x`**，否则 entrypoint 退 126。

## 6. 提交与出站门禁

```bash
export GIT_SSH_COMMAND="ssh -o UseKeychain=yes -o IdentitiesOnly=yes -i /Users/shan/.ssh/pub -o BatchMode=yes"
bash ~/.workbuddy/skills/git-quick-commit/scripts/git-fast.sh -m "feat(ops): …" \
  --paths "pig/db_bak/<域>/<脚本>.sql pig/db/<合并文件>.sql"
git diff --name-only origin/dev..HEAD | grep -E '(^|/)\.env' || echo GATE_CLEAR   # 命中 .env* 即停
```

- `git-fast.sh` **不带 `GIT_SSH_COMMAND` 会卡在 SSH 口令提示**（表现为 Exit 137）。先 export，见上。
- 🔴 用 `--paths` 精确提交，**绝不 `git add .`**（工作区常有并行会话在途改动 + `.env.*` 运行态覆盖）。

---

## 7. 远端环境排查「哪些任务没运行」（2026-10-26 在 172 实测）

场景：用户甩一个定时任务页链接，问「哪些任务没运行，能修的帮我修」。按下面四步走，别一上来就全量启动。

### 7.1 三步定位「真·没运行」

1. `GET /admin/sys-job/page?current=1&size=100` 看 `job_status` 分布（1=未运行 / 2=运行 / 3=暂停）。
2. `GET /admin/sys-job/stats?days=7` 拿近 7 天执行次数与失败数。**交叉比对**：`status=2` 但 `stats` 里无记录 ⇒ 名义运行实为空转；`status=2` 但失败率 100% ⇒ 在跑但全错。
3. `GET /admin/sys-job/job-log?current=1&size=N&jobId=xx` 看该任务**是否从未执行过**（total=0 = 从 seed 导入起就没跑过）。

> 🔴 **job-log 是升序返回**（最早在前）。想看「最近一次」必须跳到最后一页：`current = ceil(total/size)`。只看第 1 页会误判成「最后一次执行停在很久以前」。

### 7.2 关键判据：拿本机库当基线，区分「设计如此」vs「环境漂移」

远端一堆 `status=1` 的任务，绝大多数是**设计上就没启用的模块**（设备采集/生产周报月报/库存对账/合规报表/SSO 票据清理等），不是故障。盲启只会刷一堆失败日志。

**判据**：本机运行库是同源 seed，把同 `job_id` 的状态拉出来对照 ——

```sql
select job_id,job_name,job_status,cron_expression from sys_job where job_id in (...);
```

- 本机 `2`、远端 `1` ⇒ **漂移**，应 `start-job` 修复。
- 本机也 `1` ⇒ 未启用模块，**不动**。

**特例别误伤**：cron = `0 0 0 1 1 ? 2099` 是刻意设定的「永不执行」占位（如 `2026102403`），正常现象。

### 7.3 启动后必须 `run-job` 验一次，且它是「注册探针」

`POST /admin/sys-job/start-job/{id}` 之后立刻 `POST /admin/sys-job/run-job/{id}`，等 15~45s 再查 job-log：

- **run-job 成功 = JobDetail 已在 Quartz 注册**（未注册时 run-job 会直接报错）⇒ **不需要再 `refresh-jobs`**。
- 出现「执行成功」才算真修好；出现「执行失败」⇒ `shutdown-job` 回退，别把失败任务留在运行态。
- 失败任务要**先回退再排查**，不留脏状态。

### 7.4 已知根因速查

| 任务 | 根因 | 判据 |
|---|---|---|
| 9301 禅道同步 / 9302 GitHub 同步（100% 失败） | **独立 Python 连接器未部署**。配置项 `lingmao.zentao.connector-url`（默认 `:8768`）、`lingmao.github.connector-url`（默认 `:8767`） | `curl` 这两个端口返回 `000`（无监听）。修法=部署连接器+配地址+密钥只存连接器侧（C-01），再 `start-job`；本机基线这两条同为 `3` 暂停 |
| `opsDailyBriefTrigger` 系列（9606/9610 等） | 链路：`python-ai /internal/v1/workflow/run` → Dify 工作流 → 落库 `/internal/hr/daily-report/report`。任一环失败 | 先排除：`ai_app_config` 里 app 存在且 `enabled=1`；`python-ai:8090/health` 的 `circuit.state=closed` 且 `open_apps=[]` |

> 🔴 **拿不到真因时的硬卡点**：`Job.fail()` 只把详情写进**后端容器日志**，`sys_job_log.exception_info` 恒为一句摘要「定时任务springBeanTaskInvok业务执行失败,任务：xxx」。要定位必须有后端容器日志权限，否则只能报告「已排除 A/B，需日志」。

### 7.5 收尾

- 变更只作用于**运行库**；要固化需同步写 `pig/db` 增量 SQL，否则下次重置库会回到原状态 —— 交付时**必须提醒用户**。
- 报告里给「变更清单 + 回退方法」（`start-job` / `shutdown-job` 互为逆操作）。
