---
name: lark-bold-drift-fix
description: 修复飞书（Feishu/Lark）文档中因 markdown 加粗解析缺陷导致的「加粗边界漂移」——同一段内多个 `**加粗**` 被错误合并成一个大加粗块。当出现这些信号时使用：文档是用 `lark-cli docs +update --doc-format markdown` 写入的；线上渲染出来的加粗范围和本地 markdown 源对不上（例如 `**A**说明，**B**` 变成整句加粗）；需要批量比对本地 markdown 与飞书线上内容的加粗段数量并逐段修复；需要在写入飞书时避免该缺陷（改用 XML `<b>` 显式标签或源码层加空格规避）。也适用于「刚 append 完长文档、发现部分段落整段加粗」这类场景。
---

# 飞书加粗边界漂移修复（lark-bold-drift-fix）

## 概述

飞书文档服务在用 `docs +update --doc-format markdown` 写入时，存在一个**加粗合并缺陷**：同一段内出现 ≥2 个 `**加粗**` 段，且两段之间的分隔文本形如「CJK 字符 + 全角标点」，解析器会把它们**合并成一个大加粗块**。

- **文字零丢失** —— 只是强调范围失真，不是数据损坏。
- **危害**：精心设计的「关键词加粗 + 其余不加粗」的可读性排版会变成整段加粗，文档观感明显退化。
- **解法**：写入端改用 XML `<b>` 显式标签（10/10 保真）；已漂移的段落用 `block_replace` + XML 逐段修复。

## 触发判定

先跑一次比对脚本确认是否中招，**不要凭印象判断**：

```bash
python3 scripts/detect_drift.py --local <本地.md> --remote <远端导出的.md>
```

会输出漂移段落清单（行号、本地加粗段数、远端加粗段数、本地原文）。

## 缺陷规律（8 组探针实测，非推测）

**会触发合并**（两个加粗段被并成一个）：

| 模式 | 结果 |
|---|---|
| `**A**x，**B**` | `**Ax，B**` |
| `**A**说"x"，**B**` | 合并 |
| `**A**x；**B**` / `**A**x。**B**` / `**A**x、**B**` | 合并 |
| `**A**x，**B**x，**C**` | 三段**全部**合并（向后吞并） |

**不触发**（保持独立）：

| 模式 | 原因 |
|---|---|
| `**A**x**B**` | 两段之间无标点 |
| `**A**，**B**` | 标点两侧相邻，段落本身也只有加粗 |
| `**A**x， **B**` | `B` **前有半角空格** |
| `**A** x，**B**` | `A` **后有半角空格** |
| `**A**"x"，**B**` | 引号紧贴，不构成「CJK+全角标点」组合 |

> 归纳：分隔文本若同时含 CJK 字符与全角标点（`，。；：、！？」`），且加粗段两侧没有空格，就会被吞并。

## 修复流程

### 步骤 1：取远端 block_id

```bash
lark-cli docs +fetch --doc <doc_url_or_token> --doc-format xml --detail with-ids > remote.json
```

- `--doc-format xml` + `--detail with-ids` 才有 `block_id`（`--detail simple` 只给内容）。
- 返回值是 **JSON**，内容在 `data.document.content`，要用 `json.load` 解析，不能当纯文本用。
- `--scope` 可选值：`full / outline / range / keyword / section`；`keyword` 需配 `--keyword`。

### 步骤 2：本地 markdown 行 → XML

用 `scripts/convert_md_line_to_xml.py`（本技能自带）：

```bash
python3 scripts/convert_md_line_to_xml.py --line "$(cat local_line.txt)" --out fix.xml
```

**转义顺序是硬约束**，写错会让 `<b>` 变成 `&lt;b&gt;`：

1. 先把 `` `code` `` 抽成占位符
2. 再按 `**...**` 拆分
3. 最后才对纯文本做 `&` `<` `>` 转义
4. 最后把 code 占位符还原成 `<code>...</code>`

### 步骤 3：逐段替换

```bash
lark-cli docs +update \
  --doc <doc_url_or_token> \
  --command block_replace \
  --block-id <block_id> \
  --doc-format xml \
  --content @fix.xml
```

`str_replace` + `--doc-format xml` 也能修单段（`--command str_replace --pattern "<旧文本>" --content "<新 XML>"`）。

### 步骤 4：复验

重新 fetch，比对本地与远端的加粗段数量必须**逐段相等**。

## 写入端预防（推荐）

写长文档前二选一：

1. **改用 XML 格式，显式 `<b>` 标签** —— 最可靠，10/10 保真。代价是要自己转一遍 markdown。
2. **markdown 源码层规避** —— 在可能触发合并的两个加粗段之间插一个**半角空格**：`**A**x， **B**`。改动小，但要在写前扫描全文。

写完后**必须做一次全量比对**（本地每段的 `**` 计数 vs 远端每段的加粗段数）。

## 踩坑清单

| 现象 | 原因 | 处理 |
|---|---|---|
| `<b>` 渲染成字面 `&lt;b&gt;` | 转义顺序错了，标签被转义 | 抽 code → 拆 `**` → 最后转义文本 |
| `degrade_code=1011 Instruction produced no document changes` | **该段其实已经修好了**，重复调用无变化 | 不要重试，重新 fetch 复验 |
| `drive +delete` 返回 `confirmation_required` | high-risk-write 需显式确认 | 加 `--yes` |
| `docs +fetch` 结果是一堆 `\n` 转义 | 返回的是 JSON | `json.load` 后取 `data.document.content` |
| `--scope section --start-block-id <h1_id>` 拿不到该 h1 之后的全部内容 | scope 语义限制 | 用 `--scope keyword --keyword "<标题>"` 逐个取各段 |
| 修复段落里含行内 code，脚本检测不到漂移 | 正则被反引号打断 | 检测与转换都要做 code-aware 处理 |

## 配套脚本

| 脚本 | 用途 |
|---|---|
| `scripts/convert_md_line_to_xml.py` | 单行 markdown → XML（code-aware，`<b>`/`<code>` 显式标签） |
| `scripts/detect_drift.py` | 比对本地/远端 markdown，列出加粗段数不一致的段落 |

## 资源

- `references/defect-notes.md` —— 探针实验原始记录与全部模式对照表
- `references/feishu-cli-cheatsheet.md` —— 本流程用到的 lark-cli 命令速查
