---
name: linmo-prompt-inventory-export
description: 把灵猫企管（linmo-pig-full）全仓的 AI 提示词抽出来、按分层结构导出成一份文档，并写入飞书 wiki/docx。当用户说「导出所有提示词」「最近 N 天用到的提示词」「提示词台账」「把 AI 提示词整理成文档发飞书」「看看系统里都有哪些 prompt」时使用。覆盖四类来源（Dify DSL / 代码内置 / DDL 表 / 运行用量）与飞书写入的两个坑。
agent_created: true
---

# 灵猫企管 · AI 提示词全量导出

## 0. 先定口径（问一次，别猜）

"最近 N 天用到的提示词"有两种理解，动手前必须确认：

| 口径 | 数据依据 | 适用 |
|---|---|---|
| A 全量 + 标注用量（推荐） | 四类来源全抽，每个应用标注近 N 天调用次数 | 想要台账 |
| B 严格按调用记录 | 只导 `ai_usage_log` 命中的应用 | 审计"实际在跑什么" |
| C 只导 enabled 应用 | `ai_app_config.enabled=1` | 覆盖广但含测试应用 |

**先跑一次用量统计再问**，因为 `ai_usage_log` 的记录往往远少于预期（本机 2026-10-28/10-29 两次实测近 7 天都只有 9 条 / 5 个应用，最晚一条停在 10-27 07:30）——先把这个数字摆给用户，口径自然就清楚了。

**默认口径**：自动化/无人在场时按 A（全量 + 标注用量）执行，并在文档里显式写出「7 天真实被调用的只有 N 个」。⚠️ 若重解析得到的 `llm_nodes` / `chars` 与上轮完全一致，说明提示词正文没变，**只刷用量、不要重写 L2/L3 正文**（§8）；但 30 天用量若变了，L2 标题里的调用次数仍要改 ⇒ 实际仍走 §8.1 整体重建。

📌 **用量数据现状（2026-11-01）**：`ai_usage_log` 在停更 15 天（10-15 19:57 → 10-30）后**已于 10-31 16:24 恢复写入**，近 7 天首次出现非零值（3 应用 / 12 次 / 56,298 tokens），但覆盖面仍极窄。每次跑都要**先查 `MAX(create_time)`**，别沿用「反正 0 条」的旧结论；`usage7` 为空 / 非空走的就是 `gen_doc.py` 里两套分支（L0 第 2 条、L1.1、L4.3 都分了支）。

**7 天用量为 0 条时（2026-10-31 实测）**：`ai_usage_log` 会静默停在某个日期（当时停在 10-15 19:57，而 `ai_chat_message` 写到 10-28、`sys_job_log` 到当天）。**不要写成「这 7 天没人用」**，也不要换口径糊过去。正确做法：① 先跑一张交叉证据（`ai_usage_log` / `ai_chat_message` / `ai_app_config` / `sys_log` / `sys_job_log` 各自的 `MAX(create_time)`）；② 文档里写明「0 条 = 上报断链 或 该表被回滚/清理，库内无法区分」，并列出 30 天历史作为参照；③ 把「数据源不可信」列为待办，而不是把 0 当成结论。`gen_doc.py` 的 L0/1.1 已内置该分支（`usage7` 为空时自动出说明块）。

## 1. 提示词藏在四处（只扫一处必漏）

| 来源 | 位置 | 数量级（2026-10） |
|---|---|---|
| Dify 工作流 DSL | `deploy/dify/workflows/*.yml`（30） | LLM 节点在 `workflow.graph.nodes[].data`，`type: llm` + `prompt_template[]` |
| 同上 · 补充目录 | `deploy/dify/workflows/matter-mcp-20261019/`、`tools/dify/*.yml`（13）、`docs/dify/*.yml`（4） | **`linmo-master` 意图识别、kb-qa-* 知识库问答只在这里** |
| 代码内置 | Java：`MasterNativeChatService.systemPrompt()`、`VoicePromptBuilder.build()`、`MarketAskService.buildQuery()`、`LogAiModelClient.SAFETY_PREFIX`、`AnalysisPrompt.TEMPLATE`；Python：`app/master/{matter,memory}.py`、`app/hr/extraction.py` | 9 段，改它们要发版 |
| 运行库 | `pig` 库 `ai_usage_log` / `ai_app_config` / `ai_app_config_history` | 只给"用没用过"，不含 prompt 正文 |

`ai_usage_log` 字段口径（2026-10-29 复核）：`total_tokens` **有值**（7 天实测 69,481），但 `prompt_tokens` / `completion_tokens` / `cost_cents` **恒为 0** ⇒ 能报 token 总量，算不出单价与费用；`status` 多为 `ok`，`latency_ms` 可直接用来筛慢链路。

合计 51 个 DSL 文件 → 44 个 LLM 节点 / 约 4.9 万字符（去重后主应用 33、变体 8）。

## 2. 步骤

```bash
S=~/.workbuddy/skills/linmo-prompt-inventory-export/scripts

# 2.1 解析全部 DSL -> /tmp/prompts_dsl.json（需 pyyaml，本机 6.0.3 可用）
python3 $S/extract_prompts2.py          # 输出 files/llm_nodes/chars 与 NO-LLM 清单

# 2.2 取用量（见 §3 起库）
#     导出 /tmp/usage_7d.tsv /usage_30d.tsv /app_config.tsv，列顺序见 gen_doc.py 的 read_tsv

# 2.3 生成分层 markdown -> output/prompts-export-<日期>/
python3 $S/gen_doc.py

# 2.4 切段（切点只落在代码块外的 ##/###/####）
python3 $S/split_doc.py
```

`gen_doc.py` 里的口径常量（`TODAY` / `WIN` / 分组 `GROUPS` / `PRIMARY` 主版本表）按当期改。**`PRIMARY` 必须维护**：`ops-assignee-match`、`ops-insight-plan`、`industry-peer-search` 各有 3~4 份历史/镜像副本，不指定主版本会重复展开全文。

## 3. 起读库（MySQL 容器可能整个不在）

现象：`docker ps -a` 只剩 `linmo-pig-boot`、MySQL 容器消失，但 `docker volume ls` 里 `linmo-mysql-data` 还在。此时 `pig-boot` 日志会刷 `Communications link failure`。

```bash
D=/usr/local/bin/docker          # 本机 PATH 里没有 docker，必须绝对路径
$D volume create tm-mysql-snap-$(date +%m%d)
$D run --rm -v linmo-mysql-data:/from:ro -v tm-mysql-snap-$(date +%m%d):/to alpine \
   sh -c 'cp -a /from/. /to/ && du -sh /to'      # 352MB，秒级
$D run -d --name tm-mysql-reader -v tm-mysql-snap-$(date +%m%d):/var/lib/mysql \
   -e LANG=C.UTF-8 -e MYSQL_ROOT_PASSWORD=root \
   docker.1ms.run/library/mysql:8.0 --lower_case_table_names=1
```

**三条硬约束**：
1. **挂快照卷，绝不挂生产卷**（InnoDB recovery 会改写数据目录）。
2. `--lower_case_table_names=1` 必须与数据目录一致，否则起不来；`LANG=C.UTF-8` 不加则中文读成 `?`。
3. 镜像用 `docker.1ms.run/library/mysql:8.0`；裸 `mysql:8.0` 会因 `docker-credential-desktop` 缺失拉不下来。

用完 `$D rm -f tm-mysql-reader`。

## 4. 匹配应用名（最容易翻车的一步）

**DSL 里的 `app.name` 不是 app_code**，而是「`ops-insight-plan 跨智能体候选方案`」「`wf-daily-brief 聚合日报`」这种 code + 中文名。用全名去对 `ai_usage_log.app` 会**全部落空**，表现为"本地是否有 DSL"整列都是"无（仅线上）"。

```python
def app_code(entry):
    parts = (entry.get("app_name") or "").strip().split()
    return parts[0] if len(parts) > 1 and parts[0].isascii() else entry.get("app_name")
```

分组也要**先按文件路径**（`deploy/dify/workflows/hr_*` → 人事域）再按名字，否则 `hr_daily_brief.yml`（app 名 `wf-daily-brief`）会被归错。

### 4.1 名字天然对不上的三类（2026-11-01 已修进 `gen_doc.py`）

| 现象 | 例子 | 处理 |
|---|---|---|
| `app.name` 只有中文名，没有 code 前缀 | `项目智能体·实时管理分析` ↔ `ai_usage_log.app = project-agent-live-summary` | 往 `ALIAS` 加一行 |
| 大小写不同 | `GitHub 代码仓库健康度与风险分析` ↔ `github` | `norm()` 转小写后匹配，自动命中 |
| 本地有 DSL 但 0 个 LLM 节点 | `项目智能体·禅道全项目采集`（`project-agent-zentao-collect`） | `dsl_state()` 报「有（无 LLM 节点）」，不报「无（仅线上）」 |

`gen_doc.py` 现在有 `ALIAS` / `norm()` / `usage_key()` / `u7_of()` / `u30_of()` / `dsl_state()` 一套，**新增用量应用时先看这 6 个是否命中**，别再手改表格。症状识别：L1.3 显示调用次数但 L1.1/L2 标题显示「无调用记录」⇒ 就是这里漏了。

## 5. 写入飞书

```bash
# 解析 wiki URL -> obj_token / obj_type（docx）
lark-cli wiki +node-get --node-token '<wiki_url>' --as user --format json

# 逐段追加（每段 ≤12K 字符，切点见 split_doc.py）
lark-cli docs +update --doc <obj_token> --command append --doc-format markdown \
  --content '@./output/prompts-export-<日期>/part-01.md' --as user --format json

# 顺带改标题（wiki 节点走 drive，不要重建节点）
lark-cli drive +update-title --url '<wiki_url>' --title '<标题>' --as user --format json
```

**两个坑**：
1. 🔴 **空 docx 首次 `append` 会返回 `result=success` 但内容不落库**（2026-10-28 实测：6 段里第 1 段凭空消失，后 5 段正常）。兜底：先 fetch 拿文档开头那几个 block 的 id，再用
   `--command block_replace --start-block-id <first> --end-block-id <last> --content '@./part-01.md'`
   把第一段替换进去；顺带能清掉文档里原有的测试残留块。
2. `--content @file` **只接受 cwd 下相对路径**，绝对路径报 `unsafe file path`；判断成功看 `ok == true`，不是 `code == 0`。

Markdown 里的 `<`、`*`、`|` 在**代码块内是字面量**，提示词一律包进 ` ```text ` 即可；表格 cell 内的 `|` 才需要转义。

## 6. 验收（不看这几项就等于没验）

```python
# 与源 markdown 对齐：<pre> 块数 == 源码块数、<table> == 源表数、H1~H3 无重复
pres = re.findall(r'<pre[^>]*>(.*?)</pre>', xml, re.S)
```
- `<pre>` 数 = 源 ` ``` ` 块数（73）
- `<table>` 数：正文 6 张（L0 / L1.2 / L1.3 / L4.1 / L4.2，+L1.1）+ 顶部时间线 3 张 ⇒ **近 7 天用量为 0 时 = 9**（L1.1 退化成 blockquote 提示）、**有数据时 = 10**（L1.1 变表格，2026-11-01 实测）
- `<pre>` 数掉一截 ⇒ 正文被误删；`h2` 顺序应为 时间线 / L0 / L1 / L2 / L3 / L4
- `换行测试` 之类残留 = 0
- 文档总字符数若比预期少一整段 ⇒ 命中 §5 的坑 1
- 表行数抽查：时间线应用表 = 1 + 应用数（10-31 是 15 行数据）、L1.3 = 34 行、L1.1b = 1 + 30 天应用数

## 7. 线上 Dify 取不到时的说辞

`192.168.110.172` console `/console/api/login` 返 **401**（`deploy/.env` 里的口令可能已失效）、`5433` 从开发机不通、本机无 postgres 镜像。此时**不要假装导全了**：在文档 L4「未覆盖范围」里列清楚——七智能体对话（rd/project/finance/market/hr/newmedia/industry-chat）、Dify 上无本地 DSL 的其余应用、以及"线上与本地版本的差异未 diff"。补齐方式是 `tools/reset_dify_password.py` 重置口令后用 `GET /console/api/apps` + `/workflows/draft` 拉回。

## 8. 已有页面的「滚动刷新」（每周复跑就走这条）

页面是**单一权威视图**，每次刷新只换数据，不要追加第二份时间线（否则会堆成 3、4 份）。

判定是否只刷用量：重跑 `extract_prompts2.py`，若 `llm_nodes` / `chars` 与上轮相同（2026-10-28 与 10-29 都是 44 / 48,673）⇒ 正文没变，**不要重建 L2/L3**，只改顶部 + 表序 + 标题。

🔴 **但「正文没变」不等于「只刷顶部」**：L2 每个 `####` 标题里带「30 天内调用 N 次」，只要 30 天用量变了（哪怕正文一字未改，2026-11-01 就是这种情况），这些标题也得改 ⇒ 实际只能走 §8.1 整体重建。判断题改成：**正文变 OR 30 天用量变** ⇒ 整体重建；两者都不变才走「只刷顶部 + 标题」。

```bash
# 1) 备份当前正文（出问题能对照，注意 /tmp 不跨调用持久）
lark-cli docs +fetch --doc <token> --doc-format xml --detail with-ids \
  --scope range --start-block-id 0 --end-block-id -1 --as user --format json > /tmp/doc.json
#    ⚠️ 正文在 data.document.content（不是 data.content）；返回是 fragment，包 <r> 再 ElementTree
# 2) 改标题（wiki 节点走 drive）
# 3) block_replace 引言块 -> 新的生成时间/窗口说明（会换 id，下一步锚点要重取）
# 4) block_insert_after <引言块 id> 插入新时间线章节（xml，含 callout + 2 表 + ol）
# 5) 复核插入落地后，block_delete --start-block-id <旧h2> --end-block-id <旧章节最后一个 li>
```

**四条硬约束**：
1. **先插后删**。顺序反了文档会短暂空窗；插完必须 fetch 确认再删。
2. `block_replace` 会让块**换 id**，插完引言块后锚点必须重新 fetch。
   🔴 **插入用 `--block-id`，不是 `--start-block-id`**：`block_insert_after` 传 `--start-block-id` 直接报
   `validation: --start-block-id and --end-block-id are only supported with --command block_replace or block_delete`（2026-11-02 实录）。
3. `block_replace` 只替换目标块本身，子块（`<li>` 等）随之替换；`--start/--end` 做范围替换时 end 用**最后一个 `li` 的 id**。
4. `<ol>` 容器本身没有 id，可操作 block 是里面的 `<li>`；range delete 后要数块数（本次 374→364，正好减 10）。

### 8.1 正文也变了（`llm_nodes`/`chars` 与上轮不同）⇒ 整体重建 L0~L4

2026-10-30 实测流程（chars 48,988→49,167 走的就是这条，全程无空窗）：

```bash
# a) block_replace 引言块 -> intro.md（一句话说明本次刷新）
# b) block_insert_after <新引言 id> --content @part-00-timeline.md   # 时间线也重建
# c) 先 append 新正文（落在文档末尾，此时旧正文还在，因此不空窗）：
#    part-01b.md = part-01.md 去掉 H1 与引言后、从 `## L0` 切到 `## L2` 之前（L0+L1）
#    part-01c.md = 从 `## L2` 起的余下部分；再 part-02..06
# d) 最后 range delete 旧段落：[旧时间线 h2] .. [旧末尾 ol 的最后一个 li]
```

- **别用 `overwrite`** 全量重写：会丢标题/富文本，且 136K 字符一次调用超限。
- **`block_replace` 范围替换也不要吞 part-01**：12,778 字符已到上限边缘，拆段更稳。2026-10-31 的 part-01 涨到 13,323 字符（新增 1.1b 后），按 `## L2` 再切成 `part-01b`（L0+L1，约 6.8K）+ `part-01c`（L2 起，约 6.4K）两次 append，两段都 < 7K。
- 验收四件套：`<pre>` == 源 fenced 块数（73；注意用 `^`{3,}` 正则数，`count('```')` 会因 4 反引号围栏多算 1）｜`<table>` == 正文 6 + 时间线 3 = 9｜`h2` 顺序 = 时间线/L0/L1/L2/L3/L4｜`h4` 数 == 源 `####` 数（33）。
- 表行数逐张核：时间线应用表 8 行、明细 17 行、变更 4 行、L1.3 全量 33 行。

### 8.2 脚本日期已参数化（2026-10-30 改）

`gen_doc.py` 读 `EXPORT_DATE` / `TODAY` / `WINSTART` 环境变量；`split_doc.py` 接受 `argv[1]` 或 `EXPORT_DATE`。不用再手改两处硬编码路径，直接：

```bash
EXPORT_DATE=20261106 TODAY=2026-11-06 WINSTART=2026-10-07 python3 $S/gen_doc.py
python3 $S/split_doc.py 20261106
```

⚠️ `split_doc.py` 会**重写 part-01..06**；若已手工生成 `part-01b.md`，重跑后会以新 part-01 为准，需重新切 `part-01b.md`。

## 9. zsh 变量不拆词（本机踩过）

`M="docker exec deploy-mysql-1 mysql -uroot -proot -N -B"` 后 `$M -e "..."` 在 zsh **不拆词**，整串当命令名 ⇒ 静默 0 行输出（若再 `2>/dev/null` 就完全没线索）。要么写完整命令，要么 `eval`。

## 10. docker exec 直查也必须带 LANG=C.UTF-8（2026-10-29 踩过）

容器**在跑**时直接 `docker exec deploy-mysql-1 mysql ... > /tmp/app_config.tsv` 不起临时容器，绕开了 §3 —— 但导含中文列（`app_name`）的 TSV 时**必须 `docker exec -e LANG=C.UTF-8`**，否则输出是 latin1 乱字节，`gen_doc.py` 的 `read_tsv` 直接 `UnicodeDecodeError: invalid start byte 0xb7` 崩掉。`app_config.tsv` 必验，`usage_*.tsv`（纯 ASCII 列）可省。

