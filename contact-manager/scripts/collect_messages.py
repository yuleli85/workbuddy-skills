#!/usr/bin/env python3
"""联系人管理智能体 — 消息采集器
拉取时间窗口内：全部私聊消息 + 群里 @我/@所有人 的消息（机器人/系统助手排除）
输出 JSON 供分类与「今日必做」提炼使用。

用法: python3 collect_messages.py --output /path/digest.json [--since 2026-10-17T18:00] [--until 2026-10-18T08:30]
"""
import argparse
import datetime
import json
import re
import subprocess
import sys

MY_OPEN_ID = "ou_a56cc3f1bc5d7da81b5595016b53aff3"  # 李映钰（昵称 阿钰）
MY_NAMES = ("阿钰", "李映钰")
AT_ME = re.compile(r"@(?:%s|_all)\b" % "|".join(MY_NAMES))

# 系统/机器人会话黑名单（按名称精确匹配）
BOT_CHATS = {
    "飞书智能助手", "日历助手", "云文档助手", "文档共享助手", "假勤",
    "账号安全中心", "用户387974的工作伙伴", "阿钰's Feishu Assistant",
    "猫仔-全体成员", "飞行社",
}


def run(args: list) -> str:
    r = subprocess.run(["lark-cli"] + args + ["--as", "user"],
                       capture_output=True, text=True, timeout=300)
    out = "\n".join(l for l in (r.stdout or "").splitlines()
                    if "proxy detected" not in l)
    if r.returncode != 0:
        print(f"WARN cmd failed: {' '.join(args[:3])}: {r.stderr[:200]}", file=sys.stderr)
    return out


def list_chats() -> list:
    chats, token = [], ""
    while True:
        cmd = ["im", "+chat-list", "--types", "p2p,group"]
        if token:
            cmd += ["--page-token", token]
        d = run(cmd)
        try:
            j = json.loads(d)
        except json.JSONDecodeError:
            break
        for c in (j.get("data", {}).get("items")
                  or j.get("data", {}).get("chats") or []):
            if c.get("name") not in BOT_CHATS:
                chats.append(c)
        pg = j.get("meta", {}).get("pagination", {})
        token = pg.get("next_token") or ""
        if pg.get("complete", True) or not token:
            break
    return chats


def parse_msg(line: str, is_group: bool) -> dict | None:
    try:
        o = json.loads(line)
    except json.JSONDecodeError:
        return None
    if "message_id" not in o:
        return None
    content = (o.get("content") or "").strip()
    if o.get("deleted"):
        return None
    if is_group and not AT_ME.search(content):
        return None
    sender = (o.get("sender") or {})
    return {
        "sender": sender.get("name") or sender.get("id", "?"),
        "self": sender.get("id") == MY_OPEN_ID,
        "time": o.get("create_time", ""),
        "type": o.get("msg_type"),
        "text": content[:600],
        "link": o.get("message_app_link", ""),
    }


def fetch_messages(chat_id: str, since: str, until: str, is_group: bool) -> list:
    out = run(["im", "+chat-messages-list", "--chat-id", chat_id,
               "--start", since, "--end", until, "--order", "asc",
               "--format", "ndjson"])
    msgs = []
    for line in out.splitlines():
        m = parse_msg(line, is_group)
        if m:
            msgs.append(m)
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--since", help="ISO 起始，默认昨天 18:00")
    ap.add_argument("--until", help="ISO 结束，默认现在")
    args = ap.parse_args()

    now = datetime.datetime.now()
    until = args.until or now.strftime("%Y-%m-%dT%H:%M")
    since = args.since or (now - datetime.timedelta(days=1)).replace(
        hour=18, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")

    result = {"window": {"since": since, "until": until},
              "me": {"name": "李映钰", "open_id": MY_OPEN_ID}, "chats": []}
    for c in list_chats():
        is_group = c.get("chat_mode") == "group"
        label = c.get("name") or "(P2P)"
        msgs = fetch_messages(c["chat_id"], since, until, is_group)
        if msgs:
            result["chats"].append({"chat": label, "mode": c.get("chat_mode"),
                                    "chat_id": c["chat_id"], "messages": msgs})

    total = sum(len(c["messages"]) for c in result["chats"])
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"采集完成：{len(result['chats'])} 个会话 / {total} 条消息 → {args.output}")
    for c in result["chats"]:
        print(f"  [{c['mode']}] {c['chat']}: {len(c['messages'])} 条")


if __name__ == "__main__":
    main()
