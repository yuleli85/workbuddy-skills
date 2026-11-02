---
name: linmo-dify-daily-report-triage
description: 排查灵猫企管（linmo-pig-full / PIG）「Dify 定时任务失败 / 智能体日报不更新 / 采集成片 503」并定位到唯一根因层级。当用户说「XX 智能体没有数据」「日报没更新」「Dify 定时任务承载不了」「采集全是失败」「dify_circuit_open」「app_key_not_configured」「Insufficient Balance」时使用。覆盖四层：L1 熔断级联、L2 采集门禁、L3 应用 Key/启用位、L4 Dify 侧外部故障（模型余额 / 钉钉凭据）。
agent_created: true
---

# 灵猫企管 · Dify 定时任务 / 日报不更新 分层排查

## 何时用
报「经营/研发/行业/人事智能体没有数据」「日报没更新」「Dify 定时任务服务器承载不了」「采集全失败」。

## 先记住这三条本仓事实（省掉一半弯路）
1. **"承载不了" 的最常见形态不是机器小，而是「无效重试打穿全局熔断器」**：
   声明 `daily` 但永远失败的采集源（凭据缺失/未配置）被每 5 分钟重试 ⇒ python-ai 熔断器
   （连续 5 次失败 = OPEN，全局单例）被打开 ⇒ 所有正常链路一起 503。
2. **`sys_menu.visible` 本仓 = `0` 隐藏 / `1` 显示**（与 RuoYi 默认相反）。
3. **`pig-ui` 的 `/ops/task/index` 是重定向壳**（→ `/#/ops/home/index?status=PENDING`）；
   真页面在 `pig-pc-ui`。「事项中心没数据」先分清是哪端。

## L1 · 熔断 / 采集成功率（先跑，最常命中）

```bash
# ① 成功率 + 失败原因分布（今天）
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" pig -e \
 "SELECT status,COUNT(*) FROM ops_sync_log WHERE started_at>=CURDATE() GROUP BY status;
  SELECT connector_code,COUNT(*) n,SUM(status=\"SUCCESS\") ok,LEFT(MAX(fail_reason),60)
    FROM ops_sync_log WHERE started_at>=CURDATE() GROUP BY 1 HAVING ok=0 ORDER BY n DESC;"'

# ② 熔断器状态（必须 closed）
curl -s http://127.0.0.1:8090/health   # 看 circuit.state / failures

# ③ 按小时看曲线（证明修复生效）
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" pig -e \
 "SELECT DATE_FORMAT(started_at,\"%H:%i\") t,COUNT(*) n,SUM(status=\"SUCCESS\") ok \
  FROM ops_sync_log WHERE started_at>=CURDATE() GROUP BY 1 ORDER BY 1"'
```

判读：
- 失败原因成片 `503 [dify_circuit_open]` ⇒ **L1 级联**，继续 L2。
- 单个源 `502 ... 凭据缺失` ⇒ 连接器未配 Key（配置问题，不是代码 bug）。
- 只有个别源失败且原因各异 ⇒ 数据源自身问题，正常。

## L2 · 采集门禁（daily 源是否被反复捶打）

```bash
# 每个连接器今天试了多少次；daily 源应 ≈ 1 次/天
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" pig -e \
 "SELECT connector_code,COUNT(*) n,SUM(status=\"SUCCESS\") ok,MAX(started_at) FROM ops_sync_log \
  WHERE started_at>=CURDATE()-INTERVAL 1 DAY GROUP BY 1 ORDER BY n DESC LIMIT 12"'
```

- 某源每天 100~300 次且 ok=0 ⇒ 门禁失效。本仓已修：
  `OpsSyncTriggerJob.isDue` 参考时间取 `max(last_sync_time, 最近尝试时间)`，数据来自
  `OpsSyncLogMapper.selectLastAttemptPerConnector()`（`GROUP BY connector_code` 取 `MAX(started_at)`）。
- 另需 `python-ai-service/app/core/retry.py::is_permanent()`：**4xx（除 429）不计熔断、不重试**，
  否则一个 403/404 应用就能把全局熔断器打开。
- 注意：`ops_collect.py` 里 `request_id=req.request_id or batch_no` 之类的拼装键有长度上限
  （`ai_usage_log.request_id` = `VARCHAR(128)`），超长会让**整批**用量回滚。

## L3 · 应用 Key / 启用位（`app_key_not_configured`）

```bash
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" pig -e \
 "SELECT job_id,job_name,method_params_value FROM sys_job WHERE job_id IN (9606,9608,9609,9610,9614,9615);
  SELECT app_code,enabled,model_code FROM ai_app_config WHERE app_code LIKE \"industry%\" OR app_code LIKE \"wf-%\""'
```

- 报 `app_key_not_configured` 时，看任务参数里的 `app` 是否在 `ai_app_config` 且 `enabled=1`。
  **已知坑**：9610 行业日报指向 `industry-digest`（`enabled=0` 且无 Key），而启用版本是 `dify-04cab81b`。
- `ai_app_config` 存在**同 `app_code` 重复行**（`wf-daily-brief` / `business-brief`），取 Key 非确定。

## L4 · 直接探针工作流（区分"本仓问题"与"Dify 侧问题"）

```bash
T=$(docker exec linmo-pig-boot sh -c 'echo $INTERNAL_AI_TOKEN')
curl -s -m 120 -X POST http://127.0.0.1:8090/internal/v1/workflow/run \
  -H "Content-Type: application/json" -H "X-Internal-Token: $T" \
  -d '{"app":"wf-daily-brief","inputs":{},"workflow_inputs":{},"user":"ops-cron","scene_tag":"","response_mode":"blocking","request_id":"probe-1"}'
```

判读（**这些属 Dify 侧，本仓不可修，如实报"需外部处理"**）：
| 响应 | 归属 | 处置 |
|---|---|---|
| `402 Insufficient Balance` | 模型账号余额 | Dify / 模型账号充值或换 Key |
| `429 AccountQuotaExceeded`「monthly usage quota…reset at …」 | **本地模型网关（192.168.110.172:3000，new-api）某上游账号额度用尽**，不是本仓问题 | 把该应用 LLM 节点切到仍有额度的模型（实测 `deepseek-v4.1-flash` 渠道正常；`qwen3.5-35b-a3b` 的账号 2132152069 当月 429 + `AgentPlan 订阅失效`）。判据：同模型的其他应用近日有成功运行 ⇒ 渠道是间歇性/分账号的，换节点模型比等额度快 |
| `{"code":"industry_busy"}`（429 / 中文「已有行业任务执行中」） | **不是"正在跑"，多数是 Redis 永久锁**：`ops:industry:execution` 被隔离逻辑 `persist` 成 TTL=-1 | `docker exec linmo-redis redis-cli TTL ops:industry:execution` 见 `-1` ⇒ 确认 Dify 侧无 `running` 运行后 `DEL`；根治见 2026-10-19 修复（QUARANTINE 改 `expire 1800`） |
| `查询钉钉通讯录失败（HTTP 0）… exit 255` | Dify 应用内钉钉凭据 | Dify 应用 / 钉钉自建应用 |
| `status=succeeded` 但缺 `content_md` | Dify 工作流是旧版（带写库节点） | 更新为标准链路版 DSL |
| `{"started":false,"reason":"already_running"}` | 幂等缓存命中（C-06） | 换 `request_id` 重试 |

## 日报落库是否成功

```bash
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" pig -e \
 "SELECT category,MAX(report_date),MAX(create_time),CHAR_LENGTH(MAX(content_md)) FROM ops_ext_daily_report GROUP BY 1"'
# 任务侧看执行结果
... "SELECT job_id,job_log_status,job_message FROM sys_job_log WHERE create_time>=CURDATE() AND job_id IN (9606,9608,9610,9615)"'
```
`job_log_status=1` = 失败（`OpsDailyBriefJob.fail()` 返回 `"1"`，原因在应用日志 `log.warn`）。
**注意**：容器 `--force-recreate` 后 `docker logs` 会丢历史（容器内 `/app/logs` 非独立卷）。

## L5 · 项目智能体「数据更新失败 / 来源表不存在」横幅（feishu-project 专项）

页面文案 `SOURCE_TABLE_UNAVAILABLE`（"来源表不存在或当前应用没有读取权限"）不是查表得出的，
而是 `OpsProjectRefreshService.failureCode()` 对最新一条 TASK_SYNC 日志的 fail_reason 做关键词归类：
含 `1254041`（飞书 bitable「数据不存在/应用不可见」）⇒ 该码。排查链：

1. 数据源：`SELECT data_sources FROM ops_agent WHERE agent_code='project'`（缺省回落 zentao）。
2. 最新日志：`ops_sync_log WHERE connector_code=<源> AND sync_type='TASK_SYNC' ORDER BY id DESC`。
3. 正式链路三件套是否齐：`ops_connector_credential`（connector_id=306021）app_id/app_secret 非空；
   `sys_job 9613` job_status 非 3（3=暂停）；应用已被加为该多维表格的协作者（缺这个就是 1254041）。
4. **快速恢复数据**：本机 lark-cli 用户身份通道 `python tools/collect_feishu_project_via_lark.py --push`
   （--dry 先验 5 表可读；需 httpx+cryptography，装在 `/Users/shan/.workbuddy/binaries/python/envs/default`），
   落库走 `/admin/internal/ops/project-source-snapshot`，批次号 `-LARK` 结尾。
5. 验收：Playwright 开 `/#/ops/agent/index?agentCode=project`（8890），断言横幅出现
   「最后成功同步」且 `GET /admin/ops/project/sync-status` 返回 `freshness=FRESH, failureCode=null`。

注意：库被重建/快照回灌后，横幅可能展示**历史**失败日志（并非实时故障）——先看日志时间戳是不是旧的。

## 验收口径（改完必跑）
1. `circuit.state=closed`；2. 分时段采集成功率 ≥ 90%；3. daily 失败源当日尝试 ≈ 1 次（不再是 100+）；
4. 日报类任务 `job_log_status=0` 且 `ops_ext_daily_report` 有当日行。
