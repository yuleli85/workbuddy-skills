#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把单行 markdown 转成飞书 XML（含 <b> / <code> 显式标签）。

关键：转义顺序必须是「先抽 code 占位 → 再拆 ** → 最后转义文本」，
否则 <b> 标签自身会被转义成 &lt;b&gt;。

用法：
  python3 convert_md_line_to_xml.py --line "**A**说明，**B**" --out fix.xml
  cat line.txt | python3 convert_md_line_to_xml.py --stdin --out fix.xml
"""

import argparse
import re
import sys

CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"(\*\*.+?\*\*)", re.S)
# markdown 行首的结构标记：列表符 / 引用符。飞书 XML 里由 block 结构承载，
# 文本节点内不再重复出现，所以转换时必须剥掉，否则会出现 "- - 内容" 这种双前缀。
PREFIX_RE = re.compile(r"^(\s*)(?:[-*+]\s+|\d+[.)]\s+|>\s+)")


def esc(text: str) -> str:
    """转义 XML 文本节点内容。顺序：& 最先。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def strip_prefix(line: str) -> str:
    """剥掉 markdown 行首的列表符 / 引用符，保留缩进。"""
    m = PREFIX_RE.match(line)
    if m:
        return m.group(1) + line[m.end():]
    return line


def build(line: str, keep_prefix: bool = False) -> str:
    """markdown 单行 -> XML 片段。

    keep_prefix=True 时保留行首列表符（默认剥离，因为飞书 XML 由 block 结构承载）。
    """
    if not keep_prefix:
        line = strip_prefix(line)

    codes = []

    def stash(m):
        codes.append(m.group(1))
        return "\x00C%d\x00" % (len(codes) - 1)

    # 1) 先抽 code span
    tmp = CODE_RE.sub(stash, line)

    # 2) 再拆加粗段
    out = []
    for part in BOLD_RE.split(tmp):
        if part.startswith("**") and part.endswith("**") and len(part) >= 4:
            out.append("<b>" + esc(part[2:-2]) + "</b>")
        else:
            out.append(esc(part))

    res = "".join(out)

    # 3) 最后还原 code span
    for k, cd in enumerate(codes):
        res = res.replace("\x00C%d\x00" % k, "<code>" + esc(cd) + "</code>")

    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", help="要转换的单行 markdown")
    ap.add_argument("--stdin", action="store_true", help="从标准输入读取整行")
    ap.add_argument("--out", help="输出文件路径（默认打印到 stdout）")
    ap.add_argument(
        "--keep-prefix",
        action="store_true",
        help="保留 markdown 行首列表符（默认剥离；飞书 XML 由 block 结构承载列表符）",
    )
    args = ap.parse_args()

    if args.stdin:
        line = sys.stdin.read().rstrip("\n")
    elif args.line is not None:
        line = args.line
    else:
        ap.error("需要 --line 或 --stdin")

    xml = build(line, keep_prefix=args.keep_prefix)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(xml)
        print("written: %s" % args.out)
    else:
        print(xml)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
