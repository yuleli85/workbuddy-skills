#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道批量建任务 —— 读取 plan JSON，在指定执行(execution)下创建任务并关联需求(story)。

plan JSON 结构：
{
  "tasks": [
    {"seq":1, "story":313, "name":"任务名", "tag":"方案设计",
     "assignedTo":"洪志强", "estimate":4, "pri":3},
    ...
  ]
}

用法：
    python3 zentao_batch_tasks.py --account admin --password 'xxx' --execution 29 --plan tasks_plan.json
    python3 zentao_batch_tasks.py ... --dry-run                 # 只打印 payload，不写库
    python3 zentao_batch_tasks.py ... --skip-seq 1,5            # 跳过已创建的任务
    python3 zentao_batch_tasks.py ... --assign-map assign.json  # 覆盖中文名->账号映射
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://zen.mzlc.me"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 任务标签 -> 禅道任务类型
TAG2TYPE = {
    "方案设计": "design",
    "智能体开发": "devel",
    "基座开发": "devel",
    "客户端集成": "devel",
    "联调验收": "test",
}


def make_api(base, token=None):
    def api(url, method="GET", payload=None):
        req = urllib.request.Request(base + url, method=method)
        req.add_header("Accept", "application/json")
        # 关键：Cloudflare 会拦 urllib 默认 UA，必须伪装浏览器
        req.add_header("User-Agent", UA)
        if token:
            req.add_header("Token", token)
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return api


def login(base, account, password):
    return make_api(base)("/api.php/v1/tokens", method="POST",
                          payload={"account": account, "password": password})["token"]


def fetch_user_map(base, token):
    """禅道 account <-> realname 双向映射 (key 为 None，调用方自己建索引)"""
    api = make_api(base, token)
    users = api("/api.php/v1/users")
    users = users.get("users", users)
    name2acct, acct2name = {}, {}
    for u in users:
        acct, name = u.get("account"), u.get("realname")
        if acct and name:
            name2acct[name] = acct
            acct2name[acct] = name
    return name2acct, acct2name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="禅道站点根地址")
    ap.add_argument("--account", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--execution", type=int, required=True, help="执行/看板 ID")
    ap.add_argument("--plan", required=True, help="任务计划 JSON")
    ap.add_argument("--assign-map", help="中文名->账号 映射 JSON，覆盖默认映射")
    ap.add_argument("--est-started", required=True, help="任务预计开始 YYYY-MM-DD（禅道必填）")
    ap.add_argument("--deadline", required=True, help="任务截止日 YYYY-MM-DD")
    ap.add_argument("--skip-seq", default="")
    ap.add_argument("--out", default="zentao_create_result.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    skip = {int(x) for x in args.skip_seq.replace(" ", "").split(",") if x}
    plan = json.load(open(args.plan, encoding="utf-8"))
    tasks = plan["tasks"]

    name2acct = {}
    if args.assign_map:
        name2acct.update(json.load(open(args.assign_map, encoding="utf-8")))

    token = None
    if not args.dry_run:
        token = login(args.base, args.account, args.password)
        live_map, _ = fetch_user_map(args.base, token)
        # 显式映射优先，未命中的中文名用禅道用户表兜底
        for k, v in live_map.items():
            name2acct.setdefault(k, v)
        print(f"[登录成功] token={token[:8]}...  用户表 {len(live_map)} 人", flush=True)

    api = make_api(args.base, token)
    results = []
    for t in tasks:
        if t["seq"] in skip:
            print(f"[跳过] #{t['seq']} {t['name'][:40]}", flush=True)
            continue

        account = name2acct.get(t.get("assignedTo", ""), "")
        payload = {
            "name": t["name"],
            "type": TAG2TYPE.get(t.get("tag", ""), "devel"),
            "pri": int(t.get("pri") or 3),
            "story": t["story"],
            "estStarted": args.est_started,
            "deadline": args.deadline,
        }
        if account:
            payload["assignedTo"] = account
        est = t.get("estimate")
        if est:
            payload["estimate"] = float(est)
            payload["left"] = float(est)

        if args.dry_run:
            print(f"[DRY] #{t['seq']} -> {json.dumps(payload, ensure_ascii=False)}", flush=True)
            continue

        try:
            r = api(f"/api.php/v1/executions/{args.execution}/tasks",
                    method="POST", payload=payload)
            print(f"[OK] #{t['seq']} 任务{r.get('id')} 需求{t['story']} "
                  f"{t.get('tag','')} <- {t.get('assignedTo','')}", flush=True)
            results.append({"seq": t["seq"], "taskId": r.get("id"), "story": t["story"],
                            "tag": t.get("tag"), "status": "ok"})
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            print(f"[FAIL] #{t['seq']} HTTP {e.code} {body[:200]}", flush=True)
            results.append({"seq": t["seq"], "story": t["story"], "tag": t.get("tag"),
                            "status": "fail", "error": body[:300]})
        time.sleep(0.35)

    if not args.dry_run:
        json.dump(results, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        ok = sum(1 for r in results if r["status"] == "ok")
        print(f"\n完成：成功 {ok} / 共 {len(results)}  → {args.out}")
        if ok != len(results):
            sys.exit(1)


if __name__ == "__main__":
    main()
