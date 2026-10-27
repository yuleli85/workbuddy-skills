---
name: scheduler-board
version: 1.0.0
description: WorkBuddy 定时任务（自动化）的看板与耗时分析 —— 按执行时间排序、分组管理、统计每个任务每次执行了多久。当用户说「定时任务看板」「看看定时任务」「定时任务耗时」「哪个任务跑得最慢」「任务排班」「定时任务分组」「自动化执行统计」「定时任务都跑了多久」「下次什么时候执行」时使用。覆盖：① 只读解析 ~/.workbuddy/workbuddy.db 的 automations / automation_runs / automation_runtime_state；② 生成可交互 HTML 看板（5 种分组视图 + 拖拽归组 + 7 种排序 + 超时阈值 + 耗时趋势）；③ 直接输出 Markdown 摘要贴进对话；④ 输出 JSON 供其它脚本消费。⚠️ 纯只读，绝不修改、启停或删除任何自动化。
agent_created: true
---

# 定时任务看板 · 排序 / 分组 / 耗时统计

## 一条命令

```bash
sched-board --open          # 全局命令（~/.local/bin/sched-board），任意目录可用
sched-board --mode summary  # 直接出摘要

S=~/.workbuddy/skills/scheduler-board/scripts/board.sh

bash $S --open              # 生成 HTML 并直接用浏览器打开（最常用）
bash $S                     # 只生成，路径 out/index.html
bash $S --mode summary      # 打一份 Markdown 摘要，直接贴进对话
bash $S --mode json         # 原始 JSON，喂给其它脚本
```

生成物固定在 `~/.workbuddy/skills/scheduler-board/out/index.html`（单文件、数据内嵌、离线可开）。

## 什么时候用哪种模式

| 用户意图 | 用法 |
|---|---|
| 「把定时任务打开我看看」「看板」 | `bash $S --open`，再用 present_files 展示 `out/index.html` |
| 「哪个任务最慢 / 跑了多久 / 统计一下」 | `bash $S --mode summary`，把摘要作为回答主体 |
| 「有没有超时的 / 卡住的」 | `bash $S --mode summary --threshold 300`（阈值秒） |
| 「导出给别的脚本 / 我自己处理」 | `bash $S --mode json` |
| 想把摘要发给别人 | summary 后另存 md，或看板里「导出 CSV」 |

`--top N` 控制摘要里最耗时任务的条数（默认 5）。

## 生成后怎么交付（别漏）

- **看板模式**：跑完后必须调 `present_files` 把 `out/index.html` 展示出来，看板才会出现在结果区。
  只执行 `--open` 然后口头说「已打开」是不够的 —— 会话里看不到产物。
  两者可以都要：先 `--open`（用户想立刻看），再 `present_files`（留存交付物）。
- **摘要模式**：把输出的 Markdown 直接作为回答主体，不要改写成散文。
- **JSON 模式**：不要整段贴进回答，除非用户明确要；按需摘关键字段。

## 统计口径（别搞错）

数据库里的 `automation_runs.runs_json` 每条含 `startedAt` / `finishedAt`（毫秒），单次耗时 = 两者之差。

⚠️ **有 `success:false` 且 `error:"Automation is already running"`、耗时 0 秒的记录，那是「撞锁跳过」，不是执行失败**。引擎已单独标记为 `skipped`：

- 耗时统计（平均 / 中位 / P90 / 最长 / 累计）只用真实执行记录
- 成功率分母只算真实执行
- 页面显示为灰色的「跳过」/`+N跳`，摘要里写成「撞锁跳过 N 次」

如果绕开本引擎自己写 SQL，务必先剔除这类记录，否则会得出「成功率 14%」这种错得离谱的结论。

## 看板里有什么

- **5 种分组视图**：自定义（可新建 / 重命名 / 解散 / 拖拽归组，配置存浏览器 localStorage）/ 按时段 / 按目录 / 按周期 / 不分组
- **7 种排序**：下次执行、上次执行、平均耗时、最近耗时、最长耗时、累计耗时、执行次数、任务名，点表头切升降序
- **筛选**：仅超时、仅最近失败、仅未执行、仅启用中；超时阈值可调（3/5/10/20/30 分钟）
- **单任务详情**：次数 / 平均 / 中位 / P90 / 最长 / 最短 / 累计 / 成功率，逐次执行记录，最近 24 次耗时折线 + 阈值参考线
- **导出**：CSV（带 BOM，Excel 直接开）、分组配置 JSON（可跨机器导入）

## 硬约束

- **只读**。本技能只执行 `SELECT`，从不写库。要启停/改 cron，走 `automation_update` 或 `pig-quartz-job-toggle`，不要在这里动。
- 数据库默认 `~/.workbuddy/workbuddy.db`。别用 `sqlite3` 命令行去改它。
- 新增/删除自动化后，数据要重跑一次 `board.sh` 才反映；看板上的「刷新数据」按钮只是提示，不能自己取数。

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| `找不到 WorkBuddy 数据库` | WorkBuddy 从没启动过，或路径变了。用 `--db` 指定，或确认 `~/.workbuddy/workbuddy.db` 存在 |
| `unable to open database file` | WAL 库拿不到 `-shm` 读写权限（沙箱常见）。引擎已自动兜底：复制库到临时目录再读，无需干预 |
| 任务数为 0 | 确实没建自动化；或库刚初始化。先 `--mode json` 看 `tasks` 是否为空 |
| 看板打开是旧数据 | 数据是生成时快照。重跑 `board.sh`，浏览器 Cmd+R |
| 分组没了 | 分组存 localStorage，换浏览器 / 清缓存会丢。用看板「导出分组」备份，换环境后「导入分组」 |

## 组合用法

```bash
# 只看最近一次超过 5 分钟的任务
bash $S --mode summary --threshold 300 | sed -n '/超过/,/^$/p'

# 定时刷新：交给自动化，每天早上跑一次
bash $S >/dev/null && echo "看板已更新"
```
