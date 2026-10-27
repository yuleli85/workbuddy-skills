# zh-ppt：中文 PPT 制作技能

写一份 JSON 稿子，一条命令出 PowerPoint 能直接改的 .pptx。字多自动缩字号、长表格自动拆页、放不下会提醒，还能逐页出图核对。

## 装

1. 把整个 `zh-ppt` 文件夹放到技能目录：
   - Claude Code：`~/.claude/skills/zh-ppt`（只给某个项目用就放 `项目/.claude/skills/zh-ppt`）
   - 其他支持 Agent Skills（SKILL.md）的工具：放到它的技能目录
2. 装依赖（要 Node 18 以上）：`cd ~/.claude/skills/zh-ppt && npm install`
3. 可选，用来出图核对：装 LibreOffice，再 `pip install pymupdf`

## 试一下

```bash
node scripts/build.js examples/最小示例.json                       # 每种页型各一页
node scripts/build.js examples/智能体自进化.json                     # 11 页完整示例
python3 scripts/render.py examples/智能体自进化-功能与特征分析.pptx    # 出 PDF 和逐页图片
```

装好后直接跟 AI 说「把这份材料做成 PPT」就会用上这个技能。

## 目录

- `SKILL.md`：给 AI 看的做法和规矩
- `references/页型.md`：每种页型的字段
- `scripts/build.js`：稿子 → .pptx
- `scripts/render.py`：.pptx → PDF ＋ 逐页图片
- `scripts/lib/`：页型、配色、放字的实现
- `examples/`：示例稿子

## 依赖

pptxgenjs（生成 PPT）、react-icons ＋ react ＋ sharp（把 Font Awesome 图标转成图片），都是 MIT 或 Apache-2.0 开源许可。
