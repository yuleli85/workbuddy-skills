# lark-cli 文档操作速查（本流程相关）

> 以 `lark-cli docs --help` 实测输出为准（2026-10-30）。

## 子命令一览

```
lark-cli docs
  +create                创建文档
  +fetch                 拉取文档内容
  +update                更新文档（str_replace / block_* / append / overwrite）
  +search                搜索文档 / Wiki / 表格
  +history-list          历史版本列表
  +history-revert        回滚到历史版本
  +media-*               图片/附件
  +resource-*            封面等资源
  +script                文档草稿工作区、解析与体检
  +whiteboard-update     白板
```

## +fetch

```bash
lark-cli docs +fetch --doc <url_or_token> \
  --scope full \
  --doc-format markdown \
  --detail simple > remote.md
```

关键参数：

| 参数 | 说明 |
|---|---|
| `--doc` | 文档 URL 或 token（**不是 `--doc-token`**） |
| `--scope` | `full` / `outline` / `range` / `keyword` / `section`，默认 `full` |
| `--doc-format` | `xml`（默认，含 DocxXML 结构）/ `markdown` / `im-markdown` |
| `--detail` | `simple`（默认）/ `with-ids`（带 block_id）/ `full`（含样式与编辑元数据） |
| `--keyword` | 配 `--scope keyword`，支持 `foo|bar` 的 OR 分支 |
| `--start-block-id` / `--end-block-id` | 配 `--scope range` 或 `section`；`-1` 表示到文档末尾 |
| `--max-depth` | outline 的标题层级上限；其他 scope 的子树深度，`-1` 不限 |
| `--context-before` / `--context-after` | range/keyword/section 场景取上下文兄弟块 |

> ⚠️ **返回的是 JSON**，内容在 `data.document.content`。直接当文本看会看到大量 `\n` 转义。
> ⚠️ `--scope section --start-block-id <h1_id>` **不包含该 h1 之后的全部内容**。要按章节取内容，用 `--scope keyword --keyword "<标题>"`。

## +update

```bash
# 追加（整轮文档写飞书的标准动作）
lark-cli docs +update --doc <url_or_token> \
  --command append \
  --doc-format markdown \
  --content @./relative-file.md
```

```bash
# 整段替换（修加粗漂移用）
lark-cli docs +update --doc <url_or_token> \
  --command block_replace \
  --block-id <block_id> \
  --doc-format xml \
  --content @fix.xml
```

```bash
# 单段文本替换
lark-cli docs +update --doc <url_or_token> \
  --command str_replace \
  --pattern "<旧文本>" \
  --doc-format xml \
  --content "<新内容>"
```

关键参数：

| 参数 | 说明 |
|---|---|
| `--command` | `str_replace` / `block_delete` / `block_insert_after` / `block_copy_insert_after` / `block_replace` / `block_move_after` / `overwrite` / `append` |
| `--content` | 支持 `@file`、`-`（stdin，一次一个 flag） |
| `--doc-format` | `xml`（默认，精确富文本编辑）/ `markdown`（用户提供的 md 或纯 append/overwrite） |
| `--block-id` | 目标块 ID，逗号分隔可批量 |
| `--start-block-id` / `--end-block-id` | 兄弟块范围；`-1` 到末尾，`0` 到开头 |
| `--revision-id` | 基准版本，`-1` 表示最新（默认） |
| `--dry-run` | 只打印请求不执行 —— **写 XML 前务必先 dry-run 看标签有没有被转义** |

> ⚠️ `--doc-format` 必须与 `--content` 匹配。给 markdown 格式的 `--doc-format xml` 会渲染异常。
> ⚠️ `block_replace` 报 `degrade_code=1011 Instruction produced no document changes` = **该段内容已经和目标一致**，重复调用无意义。

## 其它

```bash
# 删除临时测试文档（high-risk-write，必须带 --yes）
lark-cli drive +delete --file-token <id> --type docx --yes
```

```bash
# 读领域指南（首次使用建议先读）
lark-cli skills read lark-doc
lark-cli skills read lark-doc/references/lark-doc-xml.md
lark-cli skills read lark-doc/references/lark-doc-md.md
```

## 写飞书前的三项本地校验

1. **表格管道数一致性** —— 连续 `|` 行的 `|` 数量必须相同
2. **加粗 `**` 奇偶配对** —— 每段 `**` 个数必须为偶数
3. **code span 内不得含裸 `|`** —— 否则表格结构被破坏

另外：写 markdown 时 `$` 与 `<` 建议转义（`\$` `\<`）；`~` **不要**转义（实测 `~~text~~` 原样写入会渲染成真删除线，转义反而变成字面 `~~text~~`）。
