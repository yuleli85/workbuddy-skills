#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时任务看板 · 引擎（scheduler-board skill）

只读 WorkBuddy 的 SQLite 库（automations / automation_runs /
automation_runtime_state），解析每条运行记录的 startedAt / finishedAt，
算出每个任务的执行耗时统计，并输出三种形态之一：

    board    生成可交互 HTML 看板（默认）
    summary  输出 Markdown 摘要，直接贴进对话
    json     输出原始 JSON，供其它脚本消费

统计口径（重要）：
    success=false 且 error 存在且耗时 < 2 秒的记录，判为「撞锁跳过」
    （典型 `Automation is already running`），不计入耗时与成功率分母。

用法：
    python3 build_board.py                        # 生成到 out/index.html
    python3 build_board.py --mode summary         # 打一份摘要
    python3 build_board.py --open                 # 生成并用浏览器打开
    python3 build_board.py --db /path/db --out /tmp/x.html
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "index.template.html"
DEFAULT_OUT = SKILL_DIR / "out" / "index.html"
DEFAULT_DB = Path.home() / ".workbuddy" / "workbuddy.db"
LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone(timedelta(hours=8))

WEEKDAYS = {"MO": "周一", "TU": "周二", "WE": "周三", "TH": "周四", "FR": "周五", "SA": "周六", "SU": "周日"}
WD_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


# ------------------------------------------------------------------ 时间格式
def fmt_ms(ms) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, LOCAL_TZ).isoformat(timespec="seconds")
    except Exception:
        return None


def fmt_dur(sec: float | None) -> str:
    if sec is None:
        return "—"
    if sec < 1:
        return f"{sec:.1f}s"
    if sec < 60:
        return f"{round(sec)} 秒"
    if sec < 3600:
        m, s = int(sec // 60), round(sec % 60)
        return f"{m} 分 {s} 秒" if s else f"{m} 分钟"
    h, m = int(sec // 3600), round((sec % 3600) / 60)
    return f"{h} 小时 {m} 分" if m else f"{h} 小时"


def rel(ms) -> str:
    if not ms:
        return "—"
    diff = int(ms) - int(datetime.now(LOCAL_TZ).timestamp() * 1000)
    a = abs(diff)
    if a < 60000:
        t = "不到 1 分钟"
    elif a < 3600000:
        t = f"{round(a / 60000)} 分钟"
    elif a < 86400000:
        t = f"{round(a / 3600000)} 小时"
    else:
        t = f"{round(a / 86400000)} 天"
    return f"{t}后" if diff >= 0 else f"已过 {t}"


# ------------------------------------------------------------------ rrule
def describe_rrule(rrule: str | None, scheduled_at: str | None = None) -> str:
    if not rrule:
        if scheduled_at:
            try:
                dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                return f"单次 · {dt:%Y-%m-%d %H:%M}"
            except Exception:
                return "单次"
        return "—"

    p = {}
    for seg in rrule.split(";"):
        if "=" in seg:
            k, v = seg.split("=", 1)
            p[k.upper()] = v

    freq = p.get("FREQ", "").upper()
    interval = int(p.get("INTERVAL", "1") or 1)
    byhour, byminute = p.get("BYHOUR"), p.get("BYMINUTE", "0")
    byday = p.get("BYDAY")
    bymonthday, bymonth = p.get("BYMONTHDAY"), p.get("BYMONTH")

    def hhmm() -> str:
        if byhour is None:
            return ""
        hours = [h for h in byhour.split(",") if h.strip()]
        mins = [m for m in byminute.split(",") if m.strip()]
        if len(hours) == 1:
            return f"{int(hours[0]):02d}:{int(mins[0]) if mins else 0:02d}"
        return " / ".join(f"{int(h):02d}:00" for h in hours)

    if freq == "HOURLY":
        base = f"每 {interval} 小时" if interval > 1 else "每小时"
        if byday:
            sel = [d.strip() for d in byday.split(",")]
            sel.sort(key=lambda d: WD_ORDER.index(d) if d in WD_ORDER else 9)
            return f"{'、'.join(WEEKDAYS.get(d, d) for d in sel)} {base}"
        return base
    if freq == "DAILY":
        return f"{f'每 {interval} 天' if interval > 1 else '每天'} {hhmm()}".strip()
    if freq == "WEEKLY":
        days = ""
        if byday:
            sel = [d.strip() for d in byday.split(",")]
            sel.sort(key=lambda d: WD_ORDER.index(d) if d in WD_ORDER else 9)
            days = "、".join(WEEKDAYS.get(d, d) for d in sel)
        return f"{f'每 {interval} 周' if interval > 1 else '每周'} {days} {hhmm()}".strip()
    if freq == "MONTHLY":
        return f"{f'每 {interval} 个月' if interval > 1 else '每月'} {f'{bymonthday} 日' if bymonthday else ''} {hhmm()}".strip()
    if freq == "YEARLY":
        return f"每年 {f'{bymonth} 月' if bymonth else ''}{f'{bymonthday} 日' if bymonthday else ''} {hhmm()}".strip()
    return rrule


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return round(s[0], 1)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


# ------------------------------------------------------------------ 取数
def connect_readonly(db: Path):
    """优先只读直连；WAL 库在沙箱里若拿不到 -shm 权限，就复制一份再读。"""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT count(*) FROM automations").fetchone()
        return con
    except sqlite3.Error:
        tmp = Path(tempfile.mkdtemp(prefix="schedboard-"))
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db) + suffix)
            if src.exists():
                try:
                    shutil.copy2(src, tmp / (db.name + suffix))
                except Exception:
                    pass
        con = sqlite3.connect(str(tmp / db.name))
        return con


def load(db_path: Path) -> dict:
    if not db_path.exists():
        raise SystemExit(f"找不到 WorkBuddy 数据库：{db_path}\n（用 --db 指定，或确认 WorkBuddy 已启动过）")

    con = connect_readonly(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    automations = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM automations")}
    try:
        runtime = {r["automation_id"]: dict(r) for r in cur.execute("SELECT * FROM automation_runtime_state")}
    except sqlite3.Error:
        runtime = {}

    runs_by_task: dict[str, list[dict]] = {}
    last_completed: dict[str, int] = {}
    for row in cur.execute("SELECT automation_id, runs_json, created_at FROM automation_runs"):
        tid = row["automation_id"]
        bucket = runs_by_task.setdefault(tid, [])
        try:
            entries = json.loads(row["runs_json"] or "[]")
        except Exception:
            entries = []
        for it in entries:
            start, end = it.get("startedAt"), it.get("finishedAt")
            if not start or not end:
                continue
            dur = (int(end) - int(start)) / 1000.0
            if dur < 0:
                continue
            err = it.get("error") or ""
            skipped = bool(err) and dur < 2          # 撞锁 / 未真正启动
            bucket.append({
                "start": int(start),
                "end": int(end),
                "dur": round(dur, 1),
                "success": bool(it.get("success", True)),
                "skipped": skipped,
                "error": err,
                "conversationId": it.get("conversationId"),
            })
            if int(end) > last_completed.get(tid, 0):
                last_completed[tid] = int(end)
        if not entries and row["created_at"]:
            last_completed.setdefault(tid, int(row["created_at"]))

    tasks = []
    for tid, a in automations.items():
        runs = sorted(runs_by_task.get(tid, []), key=lambda x: x["start"])
        executed = [r for r in runs if not r["skipped"]]
        skipped = [r for r in runs if r["skipped"]]
        durs = [r["dur"] for r in executed]
        failed = [r for r in executed if not r["success"]]
        rt = runtime.get(tid, {})

        cwds = []
        try:
            cwds = json.loads(a.get("cwds") or "[]")
        except Exception:
            cwds = []

        tasks.append({
            "id": tid,
            "shortId": tid[:8],
            "name": a.get("name") or "(未命名)",
            "status": a.get("status") or "UNKNOWN",
            "deleted": a.get("deleted_at") is not None,
            "scheduleType": a.get("schedule_type"),
            "rrule": a.get("rrule"),
            "scheduleText": describe_rrule(a.get("rrule"), a.get("scheduled_at")),
            "nextRunAt": a.get("next_run_at"),
            "lastRunAt": (executed[-1]["start"] if executed else None) or last_completed.get(tid)
                         or rt.get("last_run_at") or a.get("last_run_at"),
            "cwd": cwds[0] if cwds else "",
            "cwdName": Path(cwds[0]).name if cwds else "未指定目录",
            "lastError": rt.get("last_error"),
            "running": bool(rt.get("running")),
            "stats": {
                "count": len(executed),
                "skipCount": len(skipped),
                "failCount": len(failed),
                "rawCount": len(runs),
                "avg": round(statistics.fmean(durs), 1) if durs else 0.0,
                "median": round(statistics.median(durs), 1) if durs else 0.0,
                "p90": percentile(durs, 0.9),
                "max": round(max(durs), 1) if durs else 0.0,
                "min": round(min(durs), 1) if durs else 0.0,
                "total": round(sum(durs), 1),
                "successRate": round((len(executed) - len(failed)) / len(executed) * 100, 1) if executed else None,
                "lastDur": executed[-1]["dur"] if executed else None,
                "lastSuccess": executed[-1]["success"] if executed else None,
                "firstRunAt": executed[0]["start"] if executed else None,
            },
            "runs": runs,
        })

    con.close()
    tasks.sort(key=lambda t: (t["nextRunAt"] is None, t["nextRunAt"] or 0, t["name"]))

    return {
        "generatedAt": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "source": str(db_path),
        "tz": str(LOCAL_TZ),
        "tasks": tasks,
        "totals": {
            "tasks": len(tasks),
            "active": sum(1 for t in tasks if not t["deleted"] and t["status"] == "ACTIVE"),
            "deleted": sum(1 for t in tasks if t["deleted"]),
            "runs": sum(t["stats"]["count"] for t in tasks),
            "skipped": sum(t["stats"]["skipCount"] for t in tasks),
            "runSeconds": round(sum(t["stats"]["total"] for t in tasks), 1),
        },
    }


# ------------------------------------------------------------------ 渲染 HTML
def render(payload: dict, template: Path, out: Path) -> Path:
    if not template.exists():
        raise SystemExit(f"找不到模板：{template}")
    html = template.read_text(encoding="utf-8")
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    marker = "/*__DATA__*/"
    if marker not in html:
        raise SystemExit(f"模板缺少数据标记 {marker}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html.replace(marker, "window.__DATA__=" + data_js + ";"), encoding="utf-8")
    return out


# ------------------------------------------------------------------ 摘要
def summarize(payload: dict, threshold: float, top: int) -> str:
    tasks = [t for t in payload["tasks"] if not t["deleted"]]
    tot = payload["totals"]
    ran = [t for t in tasks if t["stats"]["count"] > 0]
    lines = [
        f"## 定时任务概览（{payload['generatedAt'].replace('T', ' ')[:16]}）",
        "",
        f"- 任务 **{len(tasks)}** 个（启用 {sum(1 for t in tasks if t['status'] == 'ACTIVE')}，另有 {tot['deleted']} 个已删除未计入）",
        f"- 真实执行 **{tot['runs']}** 次，撞锁跳过 {tot['skipped']} 次",
        f"- 累计耗时 **{tot['runSeconds'] / 3600:.1f} 小时**，平均每次 {fmt_dur(tot['runSeconds'] / tot['runs']) if tot['runs'] else '—'}",
        "",
    ]

    if ran:
        by_avg = sorted(ran, key=lambda t: -t["stats"]["avg"])[:top]
        lines += ["### 最耗时 TOP{}（按平均耗时）".format(len(by_avg)), "",
                  "| 任务 | 平均 | 最长 | P90 | 执行次数 | 成功率 |", "|---|---|---|---|---|---|"]
        for t in by_avg:
            s = t["stats"]
            lines.append(f"| {t['name']} | {fmt_dur(s['avg'])} | {fmt_dur(s['max'])} | {fmt_dur(s['p90'])} | "
                         f"{s['count']} | {s['successRate']:.0f}% |")
        lines.append("")

    hot = [t for t in ran if (t["stats"]["lastDur"] or 0) >= threshold]
    if hot:
        lines += [f"### 最近一次超过 {fmt_dur(threshold)} 的任务", ""]
        for t in sorted(hot, key=lambda x: -(x["stats"]["lastDur"] or 0)):
            lines.append(f"- **{t['name']}**：最近 {fmt_dur(t['stats']['lastDur'])}（平均 {fmt_dur(t['stats']['avg'])}）")
        lines.append("")

    never = [t for t in tasks if t["stats"]["count"] == 0 and t["status"] == "ACTIVE"]
    if never:
        lines += ["### 从未执行过（启用中）", ""]
        for t in never:
            nxt = f"，下次 {rel(t['nextRunAt'])}" if t["nextRunAt"] else "，无下次执行时间"
            lines.append(f"- {t['name']}（{t['scheduleText']}{nxt}）")
        lines.append("")

    fails = [t for t in ran if (t["stats"]["successRate"] or 100) < 100]
    if fails:
        lines += ["### 有失败记录", ""]
        for t in sorted(fails, key=lambda x: x["stats"]["successRate"]):
            s = t["stats"]
            lines.append(f"- **{t['name']}**：成功率 {s['successRate']:.0f}%（失败 {s['failCount']} / {s['count']} 次）")
        lines.append("")

    # 按目录汇总
    bydir: dict[str, list] = {}
    for t in ran:
        bydir.setdefault(t["cwdName"], []).append(t)
    if len(bydir) > 1:
        rows = sorted(((k, len(v), sum(x["stats"]["total"] for x in v)) for k, v in bydir.items()),
                      key=lambda r: -r[2])
        lines += ["### 按工作目录", "", "| 目录 | 任务数 | 累计耗时 |", "|---|---|---|"]
        for name, n, sec in rows:
            lines.append(f"| {name} | {n} | {fmt_dur(sec)} |")
        lines.append("")

    upcoming = sorted([t for t in tasks if t["nextRunAt"] and t["nextRunAt"] > 0 and not t["deleted"]],
                      key=lambda t: t["nextRunAt"])[:3]
    if upcoming:
        lines += ["### 接下来执行", ""]
        for t in upcoming:
            lines.append(f"- {fmt_ms(t['nextRunAt'])[5:16].replace('T', ' ')} · {t['name']}（{rel(t['nextRunAt'])}）")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description="定时任务看板：排序 / 分组 / 耗时统计")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="WorkBuddy 数据库路径")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--mode", choices=["board", "summary", "json"], default="board")
    ap.add_argument("--threshold", type=float, default=600, help="超时阈值（秒），默认 600")
    ap.add_argument("--top", type=int, default=5, help="摘要里最耗时任务条数")
    ap.add_argument("--open", action="store_true", help="生成后用系统浏览器打开")
    args = ap.parse_args()

    payload = load(Path(args.db).expanduser())

    if args.mode == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.mode == "summary":
        print(summarize(payload, args.threshold, args.top))
        return 0

    out = render(payload, Path(args.template), Path(args.out).expanduser())
    t = payload["totals"]
    print(f"✅ 看板已生成：{out}")
    print(f"   任务 {t['tasks']} 个（启用 {t['active']}，已删除 {t['deleted']}）"
          f" · 真实执行 {t['runs']} 次 · 撞锁跳过 {t['skipped']} 次")
    print(f"   累计耗时 {t['runSeconds'] / 3600:.1f} 小时"
          f" · 平均每次 {fmt_dur(t['runSeconds'] / t['runs']) if t['runs'] else '—'}")
    print(f"   数据源 {payload['source']}")

    if args.open:
        try:
            opener = "open" if sys.platform == "darwin" else ("start" if os.name == "nt" else "xdg-open")
            subprocess.run([opener, str(out)], check=False)
            print("   已在浏览器打开")
        except Exception as e:
            print(f"   自动打开失败（{e}），手动打开上面的路径即可")
    return 0


if __name__ == "__main__":
    sys.exit(main())
