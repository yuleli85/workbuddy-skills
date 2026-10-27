#!/usr/bin/env python3
"""Junk File Cleaner — 开发构建产物扫描与安全清理（macOS 废纸篓）

用法:
  扫描:   python3 scan_junk.py [--roots /path1,/path2] [--min-size-mb 1] [--report out.md] [--json out.json]
  清理:   python3 scan_junk.py --trash /path/to/node_modules [/path/to/dist ...]
          (仅允许清理构建产物名录内的目录，一律移入废纸篓，可还原)
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

# 只把这些目录名认定为「构建产物」——白名单机制，宁可漏报不可误报
TARGET_DIRS = {
    "node_modules", "dist", "build", "target", "out_next",
    ".gradle", ".next", ".nuxt", ".turbo", ".parcel-cache",
    ".angular", ".svelte-kit", ".docusaurus",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", ".tox", ".eggs",
    "coverage", ".nyc_output", ".cache", ".eslintcache",
}
TARGET_FILES = {".eslintcache", ".DS_Store"}

SKIP_DIRS = {"Library", ".Trash", ".git", ".svn", ".hg", "System Volumes", "proc", "sys", "dev"}

# 运行时数据排除：路径命中这些关键词的一律不报（是运行时依赖，删了会弄坏服务）
RUNTIME_EXCLUDE = ("docker/volumes/", "plugin_daemon", "/venvs/")


def is_runtime(path: str) -> bool:
    return any(k in path for k in RUNTIME_EXCLUDE)


def is_target(name: str) -> bool:
    return name in TARGET_DIRS or name in TARGET_FILES


def dir_size(path: str) -> int:
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        # 嵌套产物（如 node_modules 内再有 .cache）不再重复统计
        dirs[:] = [d for d in dirs if not is_target(d) and d not in SKIP_DIRS]
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def newest_mtime(path: str) -> float:
    latest = os.lstat(path).st_mtime
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [d for d in dirs if not is_target(d)]
            for f in files:
                try:
                    latest = max(latest, os.lstat(os.path.join(root, f)).st_mtime)
                except OSError:
                    pass
    return latest


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}TB"


def scan(roots: list, min_size: int) -> list:
    found = []
    for root in roots:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        stack = [root]
        while stack:
            cur = stack.pop()
            try:
                entries = os.listdir(cur)
            except OSError:
                continue
            for name in entries:
                p = os.path.join(cur, name)
                if not is_target(name):
                    if os.path.isdir(p) and name not in SKIP_DIRS:
                        stack.append(p)
                    continue
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if os.path.isdir(p) and not os.path.islink(p):
                    if is_runtime(p):
                        continue
                    size = dir_size(p)
                    if size >= min_size:
                        found.append({
                            "path": p, "size": size, "type": name,
                            "mtime": newest_mtime(p),
                        })
                elif os.path.isfile(p):
                    if st.st_size >= min_size:
                        found.append({"path": p, "size": st.st_size, "type": name,
                                      "mtime": st.st_mtime})
    found.sort(key=lambda x: -x["size"])
    return found


def write_report(items: list, out_md: str, out_json: str | None, roots: list):
    now = datetime.datetime.now()
    total = sum(i["size"] for i in items)
    lines = [
        f"# 垃圾文件扫描报告 — {now:%Y-%m-%d %H:%M}",
        "",
        f"- 扫描根目录：{'、'.join(roots)}",
        f"- 发现构建产物：**{len(items)} 项**，合计可释放 **{human(total)}**",
        f"- 删除方式：全部可安全移入废纸篓（可还原）",
        "",
        "| # | 路径 | 类型 | 大小 | 最近修改 |",
        "|---|------|------|------|----------|",
    ]
    for idx, i in enumerate(items, 1):
        age = datetime.datetime.fromtimestamp(i["mtime"])
        days = (now - age).days
        age_s = f"{age:%Y-%m-%d}（{days}天前）" if days > 0 else "今天"
        lines.append(f"| {idx} | `{i['path']}` | {i['type']} | {human(i['size'])} | {age_s} |")
    lines += ["", "> 确认后执行清理：告诉 AI「清理报告里的第 N 项」或「全部清理」即可（移入废纸篓）。"]
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"scanned_at": now.isoformat(), "roots": roots,
                       "total_size": total, "items": items}, f, ensure_ascii=False, indent=1)


def do_trash(paths: list) -> int:
    ok = 0
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        name = os.path.basename(p)
        if name not in TARGET_DIRS and name not in TARGET_FILES:
            print(f"❌ 拒绝：{p} 不在构建产物白名单内（防误删）")
            continue
        if not os.path.exists(p):
            print(f"⚠️ 跳过（不存在）：{p}")
            continue
        r = subprocess.run(["/usr/bin/trash", p], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"🗑️ 已移入废纸篓：{p}")
            ok += 1
        else:
            print(f"❌ 失败：{p} — {r.stderr.strip()}")
    print(f"\n完成：{ok}/{len(paths)} 项已进废纸篓（可在 Finder 废纸篓中还原）")
    return 0 if ok == len(paths) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", default="/Users/shan/WorkBuddy,/Users/shan/Claude,/Users/shan/my-strapi-project,/Users/shan/dify,/Users/shan/ai-secretary,/Users/shan/jenkins-agent")
    ap.add_argument("--min-size-mb", type=int, default=1)
    ap.add_argument("--report")
    ap.add_argument("--json")
    ap.add_argument("--trash", nargs="*", help="要移入废纸篓的路径列表（仅限构建产物）")
    args = ap.parse_args()

    if args.trash is not None:
        sys.exit(do_trash(args.trash))

    roots = [r.strip() for r in args.roots.split(",") if r.strip()]
    items = scan(roots, args.min_size_mb * 1024 * 1024)
    total = sum(i["size"] for i in items)
    print(f"扫描完成：{len(items)} 项，合计 {human(total)}")
    for i in items[:15]:
        print(f"  {human(i['size']):>9}  {i['path']}")
    if len(items) > 15:
        print(f"  ... 其余 {len(items) - 15} 项见报告")
    if args.report:
        write_report(items, args.report, args.json, roots)
        print(f"\n报告已写入：{args.report}")


if __name__ == "__main__":
    main()
