#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把导出文档切成若干段，切点只落在代码块外的标题行，单段控制在 ~11K 字符内"""
import os

import os, sys

# 日期目录可由 argv[1] / EXPORT_DATE 覆盖，避免每次改两处硬编码
DATE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EXPORT_DATE", "20261030")).replace("-", "")
SRC = f"/Users/shan/works/linmo-pig-full/output/prompts-export-{DATE}/灵猫企管-AI提示词导出-{DATE}.md"
OUTDIR = os.path.dirname(SRC)
LIMIT = 11000

lines = open(SRC, encoding="utf-8").read().split("\n")

parts = []
cur = []
size = 0
in_fence = False

for ln in lines:
    stripped = ln.lstrip()
    if stripped.startswith("```"):
        in_fence = not in_fence
    # 只在代码块外、且是 ### 级标题处允许切分
    can_split = (not in_fence) and (ln.startswith("### ") or ln.startswith("## ") or ln.startswith("#### "))
    if can_split and size >= LIMIT and cur:
        parts.append(cur)
        cur = []
        size = 0
    cur.append(ln)
    size += len(ln) + 1

if cur:
    parts.append(cur)

print(f"parts={len(parts)}")
for i, p in enumerate(parts, 1):
    body = "\n".join(p)
    # 第一段去掉一级标题（标题单独用 --title 设置）
    path = os.path.join(OUTDIR, f"part-{i:02d}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    head = next((x for x in p if x.strip()), "")
    print(f"  part-{i:02d}.md  {len(body):>6,} chars  start: {head[:60]}")
