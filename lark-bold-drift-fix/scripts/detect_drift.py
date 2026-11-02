#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比对本地 markdown 与飞书线上 markdown，列出「加粗边界漂移」的行。

漂移定义：同一行内本地有 N 个加粗段，线上被合并成 M 个（N != M）。
线上加粗段数少于本地 => 发生了合并（飞书 markdown 解析缺陷）。

**匹配策略：行级内容指纹，不按行号/段号配对。**
飞书文档是多轮 append 累积的，线上行数远多于本轮本地文件，
按序号配对会完全错位。用「去掉加粗/行内代码标记后的纯文本」做指纹：
加粗合并只改 `**` 不改文字，所以指纹在合并前后是一致的。

**为什么按行而不是按段落**：飞书渲染段落时可能把 markdown 源里
用空行分隔的内容合并/拆开（列表项与上一行标题会归为同一段），
段落级比对会误报；行级比对不受段落切分差异影响。

用法：
  python3 detect_drift.py --local local.md --remote remote.md
  python3 detect_drift.py --local local.md --remote remote.json --json
  python3 detect_drift.py --local local.md --remote remote.md --show-text
"""

import argparse
import difflib
import json
import re
import sys

CODE_RE = re.compile(r"`[^`]*`")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
# 归一化时丢弃的字符：加粗标记、反引号、表格管道、各种空白、列表符号
DROP_RE = re.compile(r"[\s`*|>#\-—–+]+")


def strip_code(line: str) -> str:
    """把行内 code 换成等长空格，避免 code 内的 ** 影响加粗计数。"""
    return CODE_RE.sub(lambda m: " " * len(m.group(0)), line)


def bold_segments(line: str) -> list:
    """返回该行的加粗文本列表（code 内的 ** 不计）。"""
    return BOLD_RE.findall(strip_code(line))


def fingerprint(text: str) -> str:
    """内容指纹：去掉所有格式标记后的纯文本。加粗合并不影响指纹。"""
    t = strip_code(text)
    t = t.replace("**", "").replace("__", "")
    return DROP_RE.sub("", t)


def lines(text: str) -> list:
    """保留行号结构（空行也保留，方便对齐），但跳过纯空行。"""
    return [(i, ln) for i, ln in enumerate(text.split("\n")) if ln.strip()]


def build_index(remote_lines: list) -> dict:
    """远端行指纹 -> [行索引]"""
    idx = {}
    for i, ln in remote_lines:
        fp = fingerprint(ln)
        if fp:
            idx.setdefault(fp, []).append(i)
    return idx


def match(fp: str, remote_lines: list, index: dict, used: set):
    """在远端里为本地行找对应行。返回远端行索引或 None。"""
    if not fp:
        return None

    # 1) 指纹精确匹配（绝大多数命中）
    for ri in index.get(fp, []):
        if ri not in used:
            return ri

    # 2) 退化匹配：头尾各 30 字同时包含
    if len(fp) >= 20:
        head, tail = fp[:30], fp[-30:]
        cands = [
            ri
            for ri, rl in remote_lines
            if ri not in used
            and head in fingerprint(rl)
            and tail in fingerprint(rl)
        ]
        if len(cands) == 1:
            return cands[0]

    # 3) 相似度兜底
    best, best_ratio = None, 0.0
    for ri, rl in remote_lines:
        if ri in used:
            continue
        rfp = fingerprint(rl)
        if not rfp or abs(len(rfp) - len(fp)) > max(len(fp), 1):
            continue
        ratio = difflib.SequenceMatcher(None, fp, rfp).quick_ratio()
        if ratio > 0.9:
            ratio = difflib.SequenceMatcher(None, fp, rfp).ratio()
            if ratio > best_ratio:
                best, best_ratio = ri, ratio
    if best is not None and best_ratio >= 0.85:
        return best
    return None


def load_remote(path: str) -> str:
    """远端文件可能是 JSON（docs +fetch 的原始输出）或纯 markdown。"""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    stripped = raw.lstrip()
    if stripped.startswith("{"):
        data = json.loads(raw)
        doc = data.get("data", {}).get("document", {})
        content = doc.get("content", "")
        if not content:
            raise SystemExit("JSON 里找不到 data.document.content")
        return content
    return raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", required=True, help="本地 markdown 路径")
    ap.add_argument("--remote", required=True, help="远端 markdown 或 docs +fetch 的 JSON 输出")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--show-text", action="store_true", help="打印原文")
    args = ap.parse_args()

    with open(args.local, encoding="utf-8") as f:
        local_text = f.read()
    remote_text = load_remote(args.remote)

    local_lines = lines(local_text)
    remote_lines = lines(remote_text)
    index = build_index(remote_lines)
    used = set()
    result = []
    unmatched = []

    for li, ln in local_lines:
        lb = bold_segments(ln)
        if not lb:
            continue  # 本地无加粗的行不可能因合并而漂移
        ri = match(fingerprint(ln), remote_lines, index, used)
        if ri is None:
            unmatched.append((li, ln))
            continue
        used.add(ri)
        rl = remote_lines[[x for x, _ in remote_lines].index(ri)][1]
        rb = bold_segments(rl)
        if len(lb) != len(rb):
            result.append(
                {
                    "local_line": li,
                    "remote_line": ri,
                    "local_bold_count": len(lb),
                    "remote_bold_count": len(rb),
                    "local_bold": lb,
                    "remote_bold": rb,
                    "local_text": ln,
                    "remote_text": rl,
                }
            )

    if args.json:
        print(
            json.dumps(
                {
                    "local_lines": len(local_lines),
                    "remote_lines": len(remote_lines),
                    "unmatched_with_bold": len(unmatched),
                    "drift_count": len(result),
                    "drifts": result,
                    "unmatched": [{"line": i, "text": t} for i, t in unmatched],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(
        "本地行 %d（含加粗 %d）｜远端行 %d｜未匹配 %d"
        % (
            len(local_lines),
            sum(1 for _, l in local_lines if bold_segments(l)),
            len(remote_lines),
            len(unmatched),
        )
    )
    print("检测到加粗漂移行：%d\n" % len(result))
    for d in result:
        print(
            "[local L%d → remote L%d] 本地 %d 段 → 远端 %d 段（合并 %d 段）"
            % (
                d["local_line"] + 1,
                d["remote_line"] + 1,
                d["local_bold_count"],
                d["remote_bold_count"],
                d["local_bold_count"] - d["remote_bold_count"],
            )
        )
        if args.show_text:
            print("    本地：" + d["local_text"][:240])
            print("    远端：" + d["remote_text"][:240])
    if unmatched:
        print("\n未匹配到远端对应行的含加粗行（可能是线上分块差异，非漂移）：%d" % len(unmatched))
        for i, t in unmatched[:5]:
            print("    L%d: %s" % (i + 1, t[:160]))
    return 0 if not result else 2


if __name__ == "__main__":
    raise SystemExit(main())
