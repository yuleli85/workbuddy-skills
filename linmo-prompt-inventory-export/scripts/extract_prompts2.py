#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析全部 Dify DSL（workflow / advanced-chat / chat），提取提示词全文 -> JSON"""
import json
import os

import yaml

BASE = "/Users/shan/works/linmo-pig-full"
TARGETS = [
    ("deploy/dify/workflows", "deploy/dify/workflows/*.yml"),
    ("deploy/dify/workflows/matter-mcp-20261019", "deploy/dify/workflows/matter-mcp-20261019/*.yml"),
    ("tools/dify", "tools/dify/*.yml"),
    ("docs/dify", "docs/dify/*.yml"),
]
OUT = "/tmp/prompts_dsl.json"


def collect_files():
    files = []
    for _, pattern in TARGETS:
        import glob
        for p in sorted(glob.glob(os.path.join(BASE, pattern))):
            if p not in files:
                files.append(p)
    return files


def walk_prompt_templates(node, out):
    """递归找所有含 prompt_template 的节点"""
    if isinstance(node, dict):
        if isinstance(node.get("prompt_template"), list):
            out.append(node)
        for v in node.values():
            walk_prompt_templates(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_prompt_templates(v, out)


def main():
    result = []
    for path in collect_files():
        rel = os.path.relpath(path, BASE)
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except Exception as e:
            result.append({"file": rel, "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        doc = doc or {}
        app = doc.get("app") or {}
        entry = {
            "file": rel,
            "app_name": app.get("name"),
            "mode": app.get("mode"),
            "description": (app.get("description") or "").strip(),
            "llm_nodes": [],
        }
        # 1) graph 内 LLM 节点
        holders = []
        walk_prompt_templates(doc.get("workflow") or {}, holders)
        walk_prompt_templates(doc.get("graph") or {}, holders)
        seen = set()
        for h in holders:
            msgs = []
            for m in h.get("prompt_template") or []:
                if isinstance(m, dict) and (m.get("text") or "").strip():
                    msgs.append({"role": m.get("role") or m.get("id") or "", "text": m.get("text")})
            if not msgs:
                continue
            model = h.get("model") or {}
            sig = (h.get("title"), msgs[0]["text"][:60])
            if sig in seen:
                continue
            seen.add(sig)
            entry["llm_nodes"].append({
                "title": h.get("title") or h.get("id"),
                "desc": h.get("desc"),
                "model": model.get("name"),
                "provider": model.get("provider"),
                "completion_params": model.get("completion_params"),
                "messages": msgs,
            })
        # 2) simple chat: app.model_config.prompt
        mc = app.get("model_config") or {}
        prompt = mc.get("prompt") if isinstance(mc, dict) else None
        if isinstance(prompt, list):
            msgs = [
                {"role": m.get("role", ""), "text": m.get("text", "")}
                for m in prompt
                if isinstance(m, dict) and (m.get("text") or "").strip()
            ]
            if msgs:
                entry["llm_nodes"].append({
                    "title": "app.model_config.prompt",
                    "desc": None,
                    "model": (mc.get("model") or {}).get("name"),
                    "provider": (mc.get("model") or {}).get("provider"),
                    "completion_params": (mc.get("model") or {}).get("completion_params"),
                    "messages": msgs,
                })
        result.append(entry)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    ok = [e for e in result if not e.get("error")]
    nodes = sum(len(e["llm_nodes"]) for e in ok)
    chars = sum(len(m["text"]) for e in ok for n in e["llm_nodes"] for m in n["messages"])
    print(f"files={len(result)} ok={len(ok)} err={len(result)-len(ok)} llm_nodes={nodes} chars={chars}")
    for e in result:
        if e.get("error"):
            print("  ERR", e["file"], e["error"][:100])
        elif not e["llm_nodes"]:
            print("  NO-LLM", e["file"])


if __name__ == "__main__":
    main()
