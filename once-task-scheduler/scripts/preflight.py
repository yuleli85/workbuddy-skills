#!/usr/bin/env python3
"""一次性定时任务的注册前预检 (preflight).

用途: 在调用 automation_update(mode=create, scheduleType=once) 之前, 机械校验
待执行 Prompt 是否满足「到点后一个回合内跑完、绝不中途反问」的硬约束.

退出码: 0 = 可注册 (允许有 WARN), 1 = 存在 FAIL, 禁止注册.

用法:
  python3 preflight.py --at "2026-10-25T09:00" --file /tmp/once-prompt.md
  python3 preflight.py --at "2026-10-25T09:00" --text "任务内容..."
  echo "任务内容" | python3 preflight.py --at "2026-10-25T09:00" --stdin
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

FAIL_TAG = "[FAIL]"
WARN_TAG = "[WARN]"
PASS_TAG = "[PASS]"

# C2: 任何形式的「征询用户意见」都会让到了点的那个回合直接收尾, 任务永久挂起.
ASK_PATTERNS = [
    r"是否需要", r"需不需要", r"要不要", r"可以吗", r"请问", r"你希望",
    r"是否继续", r"要不要我", r"需要我", r"确认一下", r"是否同意", r"是否确认",
    r"是否要", r"你确认", r"告诉我你", r"请告知",
    r"should\s+i", r"do\s+you\s+want", r"shall\s+i", r"would\s+you\s+like",
    r"let\s+me\s+know", r"confirm\s+whether",
]

# C1: 跨会话没有上下文, 任何指代都会指向「不存在的刚才」.
VAGUE_PATTERNS = [
    r"刚才", r"之前(?:的|那个|提到|说)", r"上面(?:的|那个|提到)", r"那个文件",
    r"那个目录", r"当前目录", r"如上(?:所述)?", r"前述", r"前面提到",
    r"我们(?:说|聊)的", r"the\s+file\s+above", r"as\s+mentioned",
]

# C2 配套: 信息缺失时必须有一条写死的兜底路径, 而不是回头问人.
FALLBACK_PATTERNS = [
    r"默认", r"兜底", r"fallback", r"取不到",
    r"缺失(?:信息)?(?:时|处置)", r"处置",
    r"若[^\n]{0,40}(?:不可|无法|失败|没有|找不到|不存在|缺失)",
    r"(?:失败|异常|不可用|不存在)时",
    r"失败则", r"任何一步失败", r"否则",
]

# C3: 终止判据必须机器可判, 不能是「看起来做完了」.
TERMINAL_PATTERNS = [
    r"终止判据", r"完成判据", r"验收标准", r"退出码", r"exit\s*code", r"test\s+-[sfed]",
    r"存在且非空", r"条数", r"校验", r"assert", r"verify", r"diff\s", r"返回\s*0",
]

# C4: 单回合预算声明.
BUDGET_PATTERNS = [
    r"单(?:个)?回合", r"一个回合", r"一次(?:性)?跑完", r"turn", r"回合内",
    r"\d+\s*分钟", r"\d+\s*min", r"不超过",
]

# C5: 成败都留痕.
LEDGER_PATTERNS = [r"写入", r"保存到", r"输出到", r"落盘", r"留痕", r"记录到", r">>?"]

PATH_PATTERN = re.compile(r"(?:^|[\s=`'\"(])/[^\s`'\"()]+")


def _hits(patterns: list[str], text: str) -> list[str]:
    found: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            found.append(m.group(0))
    # 去重保序
    return list(dict.fromkeys(found))


def parse_at(raw: str) -> dt.datetime:
    """解析 scheduledAt. 允许 '2026-10-25T09:00' 或带秒; naive 视为本地时间."""
    s = raw.strip().replace(" ", "T")
    try:
        value = dt.datetime.fromisoformat(s)
    except ValueError as exc:
        raise SystemExit(f"{FAIL_TAG} scheduledAt 无法解析: {raw!r} ({exc})")
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description="一次性任务 Prompt 预检")
    ap.add_argument("--at", required=True, help="计划执行时间, 如 2026-10-25T09:00")
    ap.add_argument("--file", help="Prompt 文件路径")
    ap.add_argument("--text", help="Prompt 文本")
    ap.add_argument("--stdin", action="store_true", help="从标准输入读取 Prompt")
    ap.add_argument("--max-minutes", type=int, default=10,
                    help="单回合预算上限(分钟), 任务预计耗时应小于此值")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总结果")
    args = ap.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text:
        text = args.text
    elif args.stdin:
        text = sys.stdin.read()
    else:
        ap.error("必须提供 --file / --text / --stdin 之一")

    text = text.strip()
    if not text:
        print(f"{FAIL_TAG} Prompt 为空")
        return 1

    fails: list[str] = []
    warns: list[str] = []
    passes: list[str] = []

    def check(name: str, ok: bool, detail: str, *, hard: bool, fix: str) -> None:
        if ok:
            passes.append(f"{PASS_TAG} {name}")
            return
        line = f"{'[FAIL]' if hard else '[WARN]'} {name} -> {detail}\n       修法: {fix}"
        (fails if hard else warns).append(line)

    # C1 自包含: 不允许模糊指代; 建议至少一个绝对路径
    vague = _hits(VAGUE_PATTERNS, text)
    check("C1 自包含(无跨会话指代)", not vague,
          f"发现指代词 {vague}", hard=True,
          fix="把「刚才那个」换成绝对路径, 如 /Users/shan/WorkBuddy/xxx/report.md")

    has_abs = bool(PATH_PATTERN.search(text))
    check("C1 自包含(含绝对路径)", has_abs,
          "未发现以 / 开头的绝对路径", hard=False,
          fix="补上输入文件/输出目录的绝对路径; 纯命令类任务可忽略")

    # C2 禁反问
    asks = _hits(ASK_PATTERNS, text)
    check("C2 禁反问", not asks,
          f"发现征询语 {asks}, 到点后模型会停下来等确认", hard=True,
          fix="删除所有征询语句, 改为「绝不提问, 按默认值执行并记录」")

    # C2 配套: 缺失信息兜底
    fallback = _hits(FALLBACK_PATTERNS, text)
    check("C2 缺失信息兜底", bool(fallback),
          "未写明信息缺失时怎么办", hard=False,
          fix="加一句「若 X 不存在, 则用默认值 Y; 若 Y 也不可得, 跳过并在报告里标注」")

    # C3 终止判据
    terminal = _hits(TERMINAL_PATTERNS, text)
    check("C3 终止判据机器可判", bool(terminal),
          "未发现可机器验证的完成条件", hard=False,
          fix="写明「判据: test -s <产物> 退出码为 0」或「条数 == N」或「退出码 == 0」")

    # C4 单回合预算
    budget = _hits(BUDGET_PATTERNS, text)
    check("C4 单回合预算声明", bool(budget),
          "未声明「一个回合内跑完」的约束", hard=False,
          fix="加一句「全部步骤必须在单个回合内完成, 不得分多次或留待下次」")

    # C5 落盘
    ledger = _hits(LEDGER_PATTERNS, text)
    check("C5 成败留痕", bool(ledger),
          "未要求把结果写入固定位置", hard=False,
          fix="指定 run 记录路径, 成功失败都写, 便于事后确认「到底做没做」")

    # 时间合法性: once 任务不能设在过去
    when = parse_at(args.at)
    now = dt.datetime.now()
    delta = (when - now).total_seconds() / 60.0
    check("时间在未来", delta > 0,
          f"scheduledAt={when.isoformat()} 已过去 {abs(delta):.0f} 分钟", hard=True,
          fix="重设一个未来时间; 一次性任务设在过去不会补跑")

    if not args.quiet:
        print(f"\n=== 预检对象: {len(text)} 字符, 计划 {when:%Y-%m-%d %H:%M} (T{delta:+.0f}min) ===\n")
        for line in passes:
            print(line)
        for line in warns:
            print(line)
        for line in fails:
            print(line)

    verdict = "FAIL" if fails else ("PASS(有警告)" if warns else "PASS")
    print(f"\n结果: {verdict} | PASS={len(passes)} WARN={len(warns)} FAIL={len(fails)}")
    if fails:
        print("→ 禁止注册, 先按上面的修法改 Prompt 再跑一次.")
        return 1
    if warns:
        print("→ 可注册, 但建议逐条消化警告 (它们是历史上真正挂过的点).")
    else:
        print("→ 可以注册: automation_update(mode=create, scheduleType=once, scheduledAt=...).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
