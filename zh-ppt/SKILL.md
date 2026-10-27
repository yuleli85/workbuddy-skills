---
name: zh-ppt
description: 做中文 PPT（.pptx）：汇报稿、方案、分析、培训课件、产品介绍等。先把内容写成一份 JSON 稿子（封面、流程、卡片、表格、对比、分步、分级、要点、图片、结尾等页型），一条命令生成 PowerPoint/WPS 能直接改的 .pptx，字多自动缩字号、长表格自动拆页、放不下会提醒，再逐页出图核对。用户说「做个 PPT」「出个幻灯片」「把这份材料做成演示稿」「汇报用的 PPT」时用。
---

# 中文 PPT 制作

把内容写成一份 JSON 稿子 → `build.js` 生成 .pptx → `render.py` 出图逐页核对 → 交付。
版面、配色、字号由脚本管，你只管**内容和页型**。

## 0. 第一次用：装依赖

```bash
cd <本技能目录> && npm install        # 要 Node 18 以上；装一次就行
```
出图核对另外要 LibreOffice 和 `pip install pymupdf`。没有也能生成 PPT，只是没法自己看图核对，交付时要说明。

## 1. 先定内容，再动手

1. 读完材料，先写一句话结论，这就是封面标题或最后一页的标题。
2. 列页：每页一个意思，**标题就是这一页的结论**（「成本能降三成」，不写「成本分析」）。标题 20 字左右，最长别超 25 字。
3. 页数：汇报 8～12 页，方案 10～15 页。超过 15 页先合并。
4. 给每页挑页型（见下表）。同一种页型别连用三页以上。
5. 数字、金额、日期要有出处；材料里没有的不编，留空或写「待补」并告诉用户。

## 2. 页型速查

| 页型 `type` | 用在哪 | 主要字段 |
|---|---|---|
| `cover` | 封面 | `title`、`subtitle`、`icon`、`meta`（落款） |
| `statement` | 一句话大字，强调一个结论 | `text`、`sub` |
| `flow` | 流程、闭环、步骤链（3～7 步） | `intro`、`steps[{name,icon,desc,key}]`、`note` |
| `cards` | 并列的几项：功能、特点、优势（2～10 项） | `items[{name,desc,icon,key}]`、`columns`、`numbered`、`style:"outline"`、`legend` |
| `table` | 多列对照、明细（行多自动拆页） | `columns[{name,width,color}]`、`rows`、`keyRows`、`numbered`、`note` |
| `panels` | 两三块大块内容，各带要点 | `items[{name,icon,desc,bullets}]` |
| `levels` | 成熟度、等级、阶梯（3～6 级） | `items[{level,state,human}]`、`target`、`note` |
| `compare` | 问题→对策、现状→改进（2～6 行） | `rows[{name,desc,answer}]`、`left`、`right` |
| `steps` | 分阶段计划、路线图（2～4 步） | `items[{name,tag,body,point}]` |
| `bullets` | 讲道理、列条件 | `items`（字符串或 `{text,sub:[]}`）、`callout` |
| `image` | 截图、示意图 | `path`（相对稿子）、`caption` |
| `closing` | 结尾：一句话总结＋最该记住的几项 | `title`、`subtitle`、`items[{name,desc,icon}]` |
| `custom` | 以上都不合适时自己画 | `script`（js 文件，见 `examples/自定义页.js`） |

每种页型的完整字段和写法：`references/页型.md`。整份稿子的样子：`examples/智能体自进化.json`（11 页完整分析）、`examples/最小示例.json`（每种页型各一页）。

通用写法：
- 任何一页都可以加 `section`（分节名，PowerPoint 左侧会分组）和 `notes`（演讲备注）。
- 文字里 `**两个星号**` 包起来的会加粗、用主色；`\n` 换行。
- `key: true` 标出重点项（橙色底）；`icon` 用 Font Awesome 的名字，如 `FaRocket`、`FaChartLine`（在 react-icons 网站 Font Awesome 5 里搜）。写错名字会提醒并改显示序号。
- 稿子顶层：`title`（文件标题）、`file`（输出文件名，不带后缀）、`theme`、`footer`（每页左下角小字，可不写）。

配色 `theme`：`"青绿"`（默认）、`"商务蓝"`、`"石墨橙"`；要贴合客户品牌色就写 `{"base": "商务蓝", "primary": "C8102E"}`，只改主色，其余照预设。可改的色名见 `references/页型.md` 末尾。

## 3. 生成

```bash
node <本技能目录>/scripts/build.js 稿子.json [输出.pptx]
```
- 输出「版面提醒」时（退出码 3）：照提醒删字、拆页或换页型，改完重跑，直到没有提醒。
- 提醒的三种：标题太长；某段字放不下；一组字整体缩得太小。缩字号是兜底，不是正常状态。

## 4. 出图核对（交付前必须做）

```bash
python3 <本技能目录>/scripts/render.py 输出.pptx [图片目录]
```
得到 PDF、每页一张图和「总览.png」。先看总览，再逐页看：
- 字有没有出框、挤在一起、一行只剩一个字；
- 同一页同类文字字号是否一致，重点项是否标对；
- 有没有空得太多的页（内容太少就和别的页合并，或换 `statement`）；
- 每页标题连起来读一遍，是不是一条完整的故事线。

注意：出图用的是 LibreOffice，没装微软雅黑时会换成别的中文字体，行距和 PowerPoint 略有出入；脚本估算按 PowerPoint 留了余量，图上略松是正常的。

## 5. 交付

- 交 .pptx；要 PDF 的一并交 `render.py` 出的 PDF。
- 文件名用中文、看得懂（`稿子里的 file`）。
- 文件里只放给观众看的内容：不写内部说明、待确认、改稿记录。
- 告诉用户：共几页、讲了什么（一两句），哪些数据是待补的。

## 常见的坑

- 字多就缩是兜底：卡片说明控制在 30 字内、表格单元格 60 字内，超了拆页。
- 表格适合 3～4 列；5 列以上改成卡片或拆两张表。
- 版面需要精确定制时用 `custom` 页型写 js，不要去改 `scripts/lib` 里的页型（改了会影响所有稿子）。
- 生成的是普通 .pptx，用户在 PowerPoint、WPS、Keynote 里都能直接改字、改色；主题色已写进文件，在「设计 → 变体 → 颜色」里能看到。
