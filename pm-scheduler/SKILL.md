---
name: pm-scheduler
description: 产品经理智能体：从飞书多维表格读取当天新需求（新提交 + 待评审草稿），自动拆解任务、生成排期方案，用户确认后写回开发任务表。触发词：产品需求排期 / 今天的需求 / 需求排期 / PM 排期 / 需求转任务…
agent_created: true
---

# PM 排期智能体（pm-scheduler）

把「一个飞书 Base 链接」变成「当天需求的排期方案」，确认后写回任务表。

## 输入

一个飞书 Base URL（或 base_token + 表 id）。用 `lark-cli base +url-resolve --url '<url>' --as user` 解析；URL 未带表坐标时用 `+table-list` 找表：优先找名为「需求表」的表，「开发任务表」用于负载检查与写回。

## 硬性约束（防误写）

1. **只读阶段绝不写表**；写回必须发生在用户对排期方案明确确认之后。
2. 写回只允许：在开发任务表 `+record-batch-create` 新任务；把对应需求 `+record-batch-update` 状态改为「已确认」。禁止删除/改写已有记录。
3. 排期日期一律由 `scripts/plan_schedule.py` 计算（避周末、限并发），不手工拍脑袋。

## 工作流

### Step 1 识别当天需求
拉需求表全量（<500 行直接 `+record-list --format ndjson`；注意记录是扁平 JSON，字段名是中文键）。当天需求 = 满足其一：
- 提交日期 = 今天
- 需求状态为「待评审」或空（草稿行）

### Step 2 负载检查
开发任务表中 `任务状态 ∈ {未开始, 开发中, 联调中, 待验收}` 的记录数 / 各负责人未完成任务数 → 决定 `--capacity`（默认 2，负载高则降到 1）与起始日（避开与现有截止日冲突）。

### Step 3 需求拆解与估时
按需求描述（含 wiki 链接时用 lark-doc 读取）拆成 1~5 个可独立交付的开发任务，每个估 1~3 天；优先级继承需求表「优先级」字段（缺省 P1）。产出任务清单 JSON：

```json
[{"name":"任务名","req":"需求名","priority":"P0","days":2}]
```

### Step 4 生成排期
```bash
/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 \
  ~/.workbuddy/skills/pm-scheduler/scripts/plan_schedule.py \
  --input tasks.json --start <明天或下一个工作日> --capacity 2
```

### Step 5 呈报方案（停止点）
向用户展示排期表 + 拆解依据，明确问「确认后写回任务表？」。**在此停止等确认。**

### Step 6 确认后写回
`+record-batch-create` 到开发任务表，每条：
```json
{"任务名称":"...","任务状态":["未开始"],"开始日期":"YYYY-MM-DD","截止日期":"YYYY-MM-DD",
 "任务详细说明":"来自需求：xxx","关联需求":[{"id":"<需求record_id>"}],"所属版本":[{"id":"<版本record_id>"}]}
```
（日期字段传 "YYYY-MM-DD" 即可，Base 自动转 datetime；所属版本按需求表「所属版本」文本在版本迭代表中匹配。）随后 `+record-batch-update` 把需求状态改为 `["已确认"]`。写完回读 count 验收。

## 参考实例

当前默认 Base（灵猫企管研发库）`LnkHbF2dPa74snsdhNUc4HHanjc`：
- 需求表 `tbluhfgrvwYOYRkB`（需求名称/描述/状态/优先级/提交日期/所属版本/关联任务）
- 开发任务表 `tblcj90Pd2ywoGic`（任务名称/状态/开始/截止日期/当日进度/负责人/所属版本/关联需求）
- 版本迭代表 `tblftUoJgQVqvOpq`、项目表 `tbln301I810egO3M`
