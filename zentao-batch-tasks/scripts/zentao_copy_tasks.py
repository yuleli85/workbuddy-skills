#!/usr/bin/env python3
"""把一个执行（源看板）的任务整体复制到另一个执行（目标看板）。

用法：
  python3 zentao_copy_tasks.py --base https://zen.example.com --token <TOKEN> \
      --src 29 --dst 34 [--dry-run]

说明：
  - 先 POST 建任务，再对 status!=wait / left!=estimate 的任务 PUT 回填状态与工时
    （禅道 POST 建任务时会静默丢弃 status/consumed/left）。
  - 子任务自动映射到新父任务 ID。
  - finishedBy/finishedDate 无法保真，会被改写成 Token 用户与当前时间。
  - --dry-run 只打印载荷，不写任何数据（务必先跑一遍）。
"""
import argparse, json, subprocess, sys, time

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True, help="站点根，如 https://zen.example.com")
ap.add_argument("--token", required=True, help="POST /api.php/v1/tokens 拿到的 token")
ap.add_argument("--src", type=int, required=True, help="源执行ID")
ap.add_argument("--dst", type=int, required=True, help="目标执行ID")
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

TOKEN, BASE, SRC, DST, DRY = args.token, args.base.rstrip("/"), args.src, args.dst, args.dry_run


def api(method, path, payload=None):
    cmd = ["curl", "-sS", "-X", method, f"{BASE}{path}",
           "-H", f"Token: {TOKEN}", "-H", f"User-Agent: {UA}",
           "-H", "Content-Type: application/json"]
    if payload is not None:
        cmd += ["-d", json.dumps(payload, ensure_ascii=False)]
    cmd += ["-w", "\n%{http_code}"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    body, _, code = out.rpartition("\n")
    try:
        return int(code), json.loads(body)
    except Exception:
        return int(code or 0), body


def acct(v):
    if isinstance(v, dict):
        return v.get("account") or ""
    return v or ""


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


# ---------- 读源任务 ----------
code, data = api("GET", f"/api.php/v1/executions/{SRC}/tasks?limit=200")
src = data["tasks"]
src.sort(key=lambda t: ((t.get("order") or 0), t["id"]))
print(f"源任务 {len(src)} 条\n")

def pid(t):
    """父任务ID；禅道把 '0' 当无父返回（字符串），必须显式判 0。"""
    v = str(t.get("parent") if t.get("parent") is not None else "0").strip()
    return v if v not in ("", "0") else None


parents = [t for t in src if not pid(t)]
children = [t for t in src if pid(t)]

mapping = {}   # 老ID -> 新ID
plan = []


def build(t, new_parent=None):
    p = {"name": t["name"], "type": t["type"], "pri": t["pri"]}
    if t.get("story"):
        p["story"] = t["story"]
    a = acct(t.get("assignedTo"))
    if a:
        p["assignedTo"] = a
    if fnum(t.get("estimate")) > 0:
        p["estimate"] = fnum(t["estimate"])
    if t.get("estStarted"):
        p["estStarted"] = str(t["estStarted"])[:10]
    if t.get("deadline"):
        p["deadline"] = str(t["deadline"])[:10]
    if new_parent:
        p["parent"] = new_parent
    return p


print("=== 第一批：主任务 ===")
for t in parents:
    p = build(t)
    plan.append(("create", t, p))

print("=== 第二批：子任务 ===")
for t in children:
    p = build(t, new_parent=f"<<{pid(t)}的新ID>>")
    plan.append(("create", t, p))

for kind, t, p in plan:
    print(f"  [{t['id']}] {t['name'][:44]:<46} {json.dumps(p, ensure_ascii=False)[:150]}")

need_put = [t for t in src if t["status"] != "wait" or fnum(t.get("left")) != fnum(t.get("estimate"))]
print(f"\n=== 需要改状态的 {len(need_put)} 条 ===")
for t in need_put:
    print(f"  [{t['id']}] {t['name'][:40]:<42} {t['status']:<6} consumed={t['consumed']} left={t['left']} estimate={t['estimate']}")

if DRY:
    print("\n[干跑] 未写入任何数据")
    sys.exit(0)

# ---------- 正式执行 ----------
print("\n=== 开始创建 ===")
created = {}
for t in parents + children:
    new_parent = mapping.get(pid(t)) if pid(t) else None
    p = build(t, new_parent)
    c, r = api("POST", f"/api.php/v1/executions/{DST}/tasks", p)
    if c in (200, 201) and isinstance(r, dict) and r.get("id"):
        created[t["id"]] = r["id"]
        mapping[t["id"]] = r["id"]
        print(f"  OK  {t['id']} -> {r['id']}  {t['name'][:40]}")
    else:
        print(f"  ERR {t['id']}  HTTP{c}  {str(r)[:160]}  <- {t['name'][:40]}")
    time.sleep(0.25)

print("\n=== 回填状态/工时 ===")
for t in need_put:
    nid = created.get(t["id"])
    if not nid:
        print(f"  SKIP {t['id']}（未创建成功）")
        continue
    p = build(t)
    p.update({"status": t["status"], "left": fnum(t.get("left")),
              "consumed": fnum(t.get("consumed"))})
    if pid(t) and created.get(pid(t)):
        p["parent"] = created[pid(t)]
    c, r = api("PUT", f"/api.php/v1/tasks/{nid}", p)
    okk = c == 200 and isinstance(r, dict) and r.get("status") == t["status"]
    print(f"  {'OK ' if okk else 'ERR'} {t['id']}->{nid} {t['status']:<6} HTTP{c} 实际={r.get('status') if isinstance(r,dict) else r}")
    time.sleep(0.25)

json.dump(created, open("/tmp/zt_copy_map.json", "w"), ensure_ascii=False, indent=1)
print(f"\n创建成功 {len(created)} / {len(src)} 条；映射已存 /tmp/zt_copy_map.json")
