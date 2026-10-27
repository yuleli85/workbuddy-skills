#!/usr/bin/env python3
"""代码审计工具。

  python audit.py scan   <项目目录> [-o 输出目录] [--since 版本] [--exclude 路径 ...] [--no-tools] [--online]
  python audit.py check  <输出目录>
  python audit.py report <输出目录> [--fail-on 严重|高|中]
  python audit.py demo

只用 Python 3.8+ 自带的库，不用装依赖。
"""
import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_lib import scan as scanmod  # noqa: E402
from audit_lib import report as rep  # noqa: E402

HERE = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass


def cmd_scan(a):
    root = Path(a.project)
    if not root.is_dir():
        sys.exit('找不到项目目录：%s' % root)
    out = Path(a.out) if a.out else root / '审计结果'
    res = scanmod.scan(root, out, since=a.since, excludes=a.exclude or [], tools=not a.no_tools, online=a.online)
    rep.worksheet(res, out)
    new_tpl = rep.template(res, out)
    c = Counter(h['level'] for h in res['hits'])
    print('扫描完成：%s，文件 %d 个，代码 %d 行' % (res['project'], res['files'], sum(l['lines'] for l in res['languages'])))
    print('框架：%s' % ('、'.join(res['stack']['frameworks']) or '没认出来'))
    print('自动扫描疑点 %d 条（%s），要逐条核对' % (len(res['hits']), '，'.join('%s %d' % (k, c[k]) for k in rep.LEVELS if c[k])))
    miss = [d['item'] for d in res['deliverables'] if d['auto'] in ('缺失', '不全')]
    if miss:
        print('交付物缺失或不全：%s' % '、'.join(miss))
    print('底稿：%s' % (out / '审计底稿.md'))
    print('结论：%s%s' % (out / '审计结论.json', '（新建的模板）' if new_tpl else '（已存在，没覆盖）'))


def cmd_check(a):
    errs, warns = rep.check(a.outdir)
    for x in errs:
        print('错误：' + x)
    for x in warns:
        print('提醒：' + x)
    if not errs and not warns:
        print('检查通过')
    return 1 if errs else 0


def cmd_report(a):
    errs, warns = rep.check(a.outdir)
    for x in errs:
        print('错误：' + x)
    if errs:
        print('先改好审计结论.json 再出报告')
        return 2
    for x in warns:
        print('提醒：' + x)
    r = rep.render(a.outdir)
    print('结论：%s（按问题级别建议：%s，%s）' % (r['verdict'], r['suggested'], r['why']))
    print('问题 %d 个：%s' % (r['issues'], '，'.join('%s %d' % (k, r['levels'][k]) for k in rep.LEVELS if r['levels'][k]) or '无'))
    print('报告：%s' % (Path(a.outdir) / '审计报告.html'))
    print('　　　%s（可用 pandoc 转 Word）' % (Path(a.outdir) / '审计报告.md'))
    if a.fail_on:
        lv = rep.LEVELS[:rep.LEVELS.index(a.fail_on) + 1]
        if any(r['levels'][k] for k in lv):
            return 1
    return 0


# 演示项目里埋的问题：自动扫描应该查出来的规则
DEMO_EXPECT = {
    'SEC-SQL-FORMAT': 'SQL 注入',
    'SEC-HARDCODED-SECRET': '口令写死在代码里',
    'SEC-WEAK-HASH': '用 MD5 存口令',
    'SEC-DESERIALIZE': '不安全的 yaml.load',
    'SEC-DEBUG-ON': '调试模式开着',
    'BUG-PY-MUTABLE-DEFAULT': '可变默认参数',
    'BUG-PY-EXCEPT-PASS': '吞掉异常',
    'BUG-MONEY-FLOAT': '金额用浮点数',
    'DEP-KNOWN-VULN': '有漏洞的组件版本',
    'DELIV-ENV-UNDOC': '配置项文档没写',
    'SEC-WEAK-RANDOM': '验证码用了可预测随机数',
    'FUNC-TODO': '没做完的功能标记',
}


def cmd_demo(a):
    proj = HERE / 'examples' / '演示项目'
    out = HERE / 'examples' / '演示项目-审计结果'
    if out.exists():
        shutil.rmtree(out)
    res = scanmod.scan(proj, out, tools=False)
    res['root'] = 'examples/演示项目'  # 示例结果随技能分发，不留本机路径
    (out / 'scan.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    rep.worksheet(res, out)
    rep.template(res, out)
    found = {h['rule'] for h in res['hits']}
    ok = True
    print('自动扫描应查出 %d 类：' % len(DEMO_EXPECT))
    for rule, desc in DEMO_EXPECT.items():
        hit = rule in found
        ok &= hit
        print('  %s %s（%s）' % ('√' if hit else '×', desc, rule))
    deliv = {d['item']: d['auto'] for d in res['deliverables']}
    for item, want in (('部署手册', '不全'), ('用户使用手册', '不全')):
        hit = deliv.get(item) == want
        ok &= hit
        print('  %s 交付物「%s」判为%s（实际：%s）' % ('√' if hit else '×', item, want, deliv.get(item)))
    shutil.copy(HERE / 'examples' / '演示项目-审计结论.json', out / '审计结论.json')
    errs, warns = rep.check(out)
    for x in errs + warns:
        print('  检查：' + x)
    r = rep.render(out)
    print('人工审出的问题（越权、满减算错、导出没做、状态能乱改）在示例结论里，报告：%s' % (out / '审计报告.html'))
    print('报告结论：%s；问题 %d 个（%s）' % (r['verdict'], r['issues'], '，'.join('%s %d' % (k, r['levels'][k]) for k in rep.LEVELS if r['levels'][k])))
    print('自检%s' % ('通过' if ok and not errs and r['pending'] == 0 else '没通过'))
    return 0 if ok and not errs else 1


def main():
    p = argparse.ArgumentParser(description='代码审计工具')
    sub = p.add_subparsers(dest='cmd')
    s = sub.add_parser('scan', help='扫描项目，生成底稿和结论模板')
    s.add_argument('project')
    s.add_argument('-o', '--out', help='输出目录，默认 <项目>/审计结果')
    s.add_argument('--since', help='只查这个版本（git 提交或分支）之后改过的文件，用于审查一次改动')
    s.add_argument('--exclude', nargs='*', help='不扫的目录（相对项目目录）')
    s.add_argument('--no-tools', action='store_true', help='不调外部工具（gitleaks 等）')
    s.add_argument('--online', action='store_true', help='允许联网的检查（npm audit）')
    c = sub.add_parser('check', help='检查审计结论.json 写全没有')
    c.add_argument('outdir')
    r = sub.add_parser('report', help='出审计报告')
    r.add_argument('outdir')
    r.add_argument('--fail-on', choices=['严重', '高', '中'], help='有这个级别及以上的问题时退出码为 1（给流水线用）')
    sub.add_parser('demo', help='用演示项目自检')
    a = p.parse_args()
    if not a.cmd:
        p.print_help()
        return 0
    return {'scan': cmd_scan, 'check': cmd_check, 'report': cmd_report, 'demo': cmd_demo}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
