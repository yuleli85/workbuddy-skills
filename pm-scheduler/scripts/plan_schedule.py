#!/usr/bin/env python3
"""排期规划器 — 输入需求拆解后的任务清单，输出避周末、限并发的排期方案

输入 JSON 格式（数组，按顺序即拆解顺序）:
[
  {"name": "任务名", "req": "所属需求", "priority": "P0", "days": 2}
]

用法:
  python3 plan_schedule.py --input tasks.json [--start 2026-10-19] [--capacity 2]
  输出 Markdown 排期表到 stdout
"""
import argparse
import datetime
import json
import sys

PRIO_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def next_weekday(d: datetime.date) -> datetime.date:
    while d.weekday() >= 5:  # 5=周六 6=周日
        d += datetime.timedelta(days=1)
    return d


def plan(tasks: list, start: datetime.date, capacity: int) -> list:
    tasks.sort(key=lambda t: (PRIO_ORDER.get(t.get("priority", "P2"), 2),))
    load = {}  # date -> 占用数
    result = []
    for t in tasks:
        days = max(1, int(t.get("days", 1)))
        cur = next_weekday(start)
        while True:
            # 尝试从 cur 开始连续 days 个工作日，每天占用 < capacity
            probe, span, ok = cur, [], True
            while len(span) < days:
                probe = next_weekday(probe)
                if load.get(probe, 0) >= capacity:
                    ok = False
                    break
                span.append(probe)
                probe += datetime.timedelta(days=1)
            if ok:
                for d in span:
                    load[d] = load.get(d, 0) + 1
                result.append({**t, "start": span[0], "end": span[-1]})
                break
            cur += datetime.timedelta(days=1)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="任务清单 JSON 文件")
    ap.add_argument("--start", default=None, help="排期起始日 YYYY-MM-DD，默认明天")
    ap.add_argument("--capacity", type=int, default=2, help="每日并行任务上限")
    args = ap.parse_args()

    tasks = json.load(open(args.input, encoding="utf-8"))
    start = (datetime.date.fromisoformat(args.start) if args.start
             else datetime.date.today() + datetime.timedelta(days=1))
    result = plan(tasks, start, args.capacity)

    lines = [
        f"# 排期方案（{start} 起 · 日并行上限 {args.capacity} · 自动避周末）",
        "",
        "| 需求 | 任务 | 优先级 | 预估工期 | 开始 | 截止 |",
        "|---|---|---|---|---|---|",
    ]
    for t in result:
        lines.append(f"| {t.get('req','')} | {t['name']} | {t.get('priority','P2')} "
                     f"| {t.get('days',1)}天 | {t['start']} | {t['end']} |")
    total = sum(int(t.get("days", 1)) for t in result)
    lines += ["", f"共 {len(result)} 个任务 / {total} 人天，预计完成日：{result[-1]['end'] if result else '-'}"]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
