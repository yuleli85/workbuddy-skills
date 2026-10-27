# 一次性任务 Prompt 骨架

到点的会话看不到你现在这个对话。这份骨架的唯一目的：**让它在没有任何上下文的情况下，仍然能自己把事做完、并且知道什么叫做完了。**

复制整段，把 `<...>` 换掉即可。

---

## 骨架

```markdown
# 任务
<一句话：对什么输入、做什么、产出什么、放在哪。>

# 硬约束
1. 全部步骤必须在单个回合内完成，不得分多次、不得留待下次、不得中途停下来等确认。
2. 绝不向用户提问，绝不请求确认。信息缺失时按「缺失信息处置」执行，事后在报告里注明即可。
3. 除 <允许写入的绝对路径> 外，不修改任何文件，不执行任何不可逆操作。

# 第 0 步 · 幂等保护（有副作用时必填）
若 <run.log 绝对路径> 中已含 DONE，说明本任务已完成，输出 ALREADY_DONE 并结束，不要重复执行。

# 步骤
1. <具体命令或动作，含绝对路径>
2. <...>
3. 校验：<机器可判的命令>

# 缺失信息处置
| 缺什么 | 怎么办 |
|---|---|
| <输入文件不存在> | 用 <默认路径>；也没有则跳过本项，在报告里标注 SKIPPED |
| <命令不可用> | 改用 <替代命令> |
| 任一步失败 | 继续执行后续步骤，把原因追加写入 <error.log>，不要停下来询问 |

# 终止判据
<命令，例如 test -s /path/out.xlsx 退出码为 0；或 行数 == 1240；或 退出码 == 0>

# 交付
只输出 <格式，例如一行：DONE <文件名> <行数>>。失败则输出 FAIL <原因>。不要输出过程解释。

# 自我清理（可选，防止台账残留）
本自动化 id 是 <automation_id>。全部完成后调用
automation_update(mode="update", id="<automation_id>", status="PAUSED")。
```

---

## 范例 A · 文件处理类

> 场景：明早 9 点，把昨天的订单导出成 Excel。

```markdown
# 任务
读取 /Users/shan/WorkBuddy/日常工作/orders.csv，筛选 order_date 为 2026-10-24 的行，
导出为 /Users/shan/WorkBuddy/日常工作/reports/orders-20261024.xlsx（工作表名 Orders）。

# 硬约束
1. 全部步骤必须在单个回合内完成，不得分多次、不得留待下次、不得中途停下来等确认。
2. 绝不向用户提问，绝不请求确认。信息缺失时按「缺失信息处置」执行。
3. 只允许写入 /Users/shan/WorkBuddy/日常工作/reports/ 目录下的文件。

# 第 0 步 · 幂等保护
若 /Users/shan/WorkBuddy/日常工作/reports/orders-20261024.xlsx 已存在且含 DONE 标记文件
.reports/orders-20261024.done，输出 ALREADY_DONE 并结束。

# 步骤
1. 确认源文件存在：test -f /Users/shan/WorkBuddy/日常工作/orders.csv
2. 用 python3 + openpyxl 读取、按 order_date 过滤、写出 xlsx。
3. 校验行数：读回 xlsx 的有效行数，与 CSV 中匹配行数比对。
4. 写完成标记：touch /Users/shan/WorkBuddy/日常工作/reports/.orders-20261024.done

# 缺失信息处置
| 缺什么 | 怎么办 |
|---|---|
| orders.csv 不存在 | 改读 /Users/shan/WorkBuddy/日常工作/orders-latest.csv；仍不存在则输出 FAIL 并结束 |
| 当天 0 行匹配 | 仍然生成只有表头的 xlsx，报告里标注 EMPTY，不要当成失败 |
| openpyxl 未安装 | 用 /Users/shan/.workbuddy/binaries/python/envs/default/bin/pip install openpyxl 安装后重试 |

# 终止判据
xlsx 存在，且读回行数 == CSV 匹配行数，且 .done 标记存在。

# 交付
只输出一行：DONE orders-20261024.xlsx <行数>。失败输出 FAIL <原因>。
```

## 范例 B · 发消息类（有副作用，必须有幂等）

> 场景：今天 18:00，把当日进度发到飞书群。

```markdown
# 任务
把 /Users/shan/WorkBuddy/日常工作/pm_daily_report_20261024.md 的内容发送到飞书群
chat_id=oc_xxxxxxxxxxxxx，发送身份为 user。

# 硬约束
1. 全部步骤必须在单个回合内完成，不得分多次、不得留待下次、不得中途停下来等确认。
2. 绝不向用户提问，绝不请求确认。
3. 只允许一次发送动作；不得额外发送测试消息。

# 第 0 步 · 幂等保护
若 /Users/shan/WorkBuddy/日常工作/once-runs/20261024-1800/sent.log 存在且非空，
说明已发送过，输出 ALREADY_SENT 并结束。

# 步骤
1. 确认待发文件存在且非空。
2. 用 lark-cli im +send --chat-id oc_xxxxxxxxxxxxx --file-type text --content "<文件内容>" --as user 发送。
3. 把返回的 message_id 写入 /Users/shan/WorkBuddy/日常工作/once-runs/20261024-1800/sent.log

# 缺失信息处置
| 缺什么 | 怎么办 |
|---|---|
| 报告文件不存在 | 改为发送一行"今日进度报告未生成，请人工确认"，并写入 sent.log 记录 DEGRADED |
| lark-cli 返回 401/403 | 把完整错误写入 once-runs/20261024-1800/error.log，输出 FAIL，不要重试超过 2 次 |
| 群 chat_id 无效 | 同上，输出 FAIL，不要改发到其它会话（绝不能猜群） |

# 终止判据
sent.log 中含 message_id，且 lark-cli 退出码为 0。

# 交付
只输出一行：SENT <message_id>。失败输出 FAIL <原因>。
```

> ⚠️ 对外发送类任务，「猜收件人」是比"没发"更严重的事故。缺失信息处置里必须写死"不要改发到其它会话"。

---

## 写 Prompt 时的三个自查

1. **把这句念一遍**：删掉当前对话，只读这段 Prompt，能不能独立完成？如果不能，缺什么就补进去。
2. **找一个"可以停下来的缝"**：任何"等结果""看情况""问一下"的措辞，都会变成悬停点，必须改写成默认分支。
3. **写不出终止判据 ⇒ 这件事还不该做成一次性任务**：回到 Step 0 拆任务。
