#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在飞书 XML（detail=with-ids）里定位「加粗边界漂移」的块。

原理：XML 里 <b> 标签的数量就是实际渲染出的加粗段数。
把远端每个带 id 的文本块解析出（纯文本指纹, 加粗段数），
再与本地 markdown 的对应行比对，加粗段数不等即为漂移。

输出：修复计划 JSON，每条含 bid / tag / local / xml_inner。

用法：
  python3 locate_drift_blocks.py --local local.md --remote-xml remote_xml.json --out plan.json
"""

import argparse
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detect_drift import bold_segments, fingerprint, lines  # noqa: E402
from convert_md_line_to_xml import build as build_xml  # noqa: E402

TAG_RE = re.compile(r"<(\w+)([^>]*)>")
B_OPEN_RE = re.compile(r"<b>")
B_CLOSE_RE = re.compile(r"</b>")

# 飞书 XML 里文本承载块都是叶子块（内部不再嵌套 p/li/h*），
# 因此非贪婪正则即可安全切出每个块的 inner。
BLOCK_RE = re.compile(
    r'<(p|li|h[1-6]|td|th)\s[^>]*id="([^"]+)"[^>]*>(.*?)</\1>', re.S
)


def strip_tags(fragment: str) -> str:
    """把 XML 片段转成纯文本（<b>/<code> 去标签，实体反转义）。"""
    t = re.sub(r"<[^>]+>", "", fragment)
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return t


def iter_blocks(xml: str):
    """产出 (block_id, tag, inner_xml) —— 匹配带 id 的文本承载块。"""
    for m in BLOCK_RE.finditer(xml):
        yield m.group(2), m.group(1), m.group(3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", required=True)
    ap.add_argument("--remote-xml", required=True, help="docs +fetch --doc-format xml --detail with-ids 的 JSON 输出")
    ap.add_argument("--out", required=True, help="修复计划输出 JSON")
    ap.add_argument("--fixdir", default="_fixfiles", help="XML 修复文件输出目录")
    ap.add_argument("--file-prefix", default="d")
    args = ap.parse_args()

    with open(args.local, encoding="utf-8") as f:
        local_text = f.read()
    with open(args.remote_xml, encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)
    xml = data.get("data", {}).get("document", {}).get("content", "")
    if not xml:
        raise SystemExit("XML content 为空")

    # 远端块 -> (纯文本, 加粗段数)
    remote_blocks = []
    for bid, tag, inner in iter_blocks(xml):
        plain = strip_tags(inner)
        if not plain.strip():
            continue
        nb = len(B_OPEN_RE.findall(inner))
        remote_blocks.append((bid, tag, plain, nb))

    index = {}
    for k, (bid, tag, plain, nb) in enumerate(remote_blocks):
        index.setdefault(fingerprint(plain), []).append(k)

    os.makedirs(args.fixdir, exist_ok=True)
    plan = []
    used = set()

    for li, ln in lines(local_text):
        lb = bold_segments(ln)
        if not lb:
            continue
        fp = fingerprint(ln)
        cand = index.get(fp)
        if not cand:
            continue
        k = next((c for c in cand if c not in used), None)
        if k is None:
            continue
        used.add(k)
        bid, tag, plain, nb = remote_blocks[k]
        if nb != len(lb):
            xml_inner = build_xml(ln)
            plan.append(
                {
                    "local_line": li + 1,
                    "bid": bid,
                    "tag": tag,
                    "local": ln,
                    "local_bold_count": len(lb),
                    "remote_bold_count": nb,
                    "xml_inner": xml_inner,
                }
            )

    for i, item in enumerate(plan):
        path = os.path.join(args.fixdir, "%s%02d.xml" % (args.file_prefix, i))
        with open(path, "w", encoding="utf-8") as f:
            f.write(item["xml_inner"])
        item["file"] = path

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)

    print("远端文本块 %d｜本地含加粗行 %d｜定位到漂移块 %d"
          % (len(remote_blocks), sum(1 for _, l in lines(local_text) if bold_segments(l)), len(plan)))
    for item in plan:
        print(
            "  L%-4d %-8s %s → 本地 %d 段 / 远端 %d 段  %s"
            % (
                item["local_line"],
                item["bid"],
                item["tag"],
                item["local_bold_count"],
                item["remote_bold_count"],
                item["local"][:70],
            )
        )
    print("修复计划：%s；XML 文件目录：%s" % (args.out, args.fixdir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
