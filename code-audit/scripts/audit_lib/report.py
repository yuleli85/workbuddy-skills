"""底稿、结论模板、结论检查、出报告。"""
import datetime
import html
import json
import re
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

LEVELS = ['严重', '高', '中', '低', '建议']
DIMS = ['功能', '缺陷', '安全', '合理性', '交付物', '依赖', '合规', '运维', '测试', '规范']
REQ_STATUS = ['已实现', '部分实现', '未实现', '与需求不一致', '无法判断']
DELIV_STATUS = ['齐全', '不全', '缺失', '不适用', '待核']
CHECK_RESULT = ['通过', '部分通过', '不通过', '未做']
VERDICTS = ['属实', '误报', '可接受']


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


# ---------------- 底稿 ----------------
def worksheet(res, outdir):
    L = []
    w = L.append
    w('# 审计底稿：%s' % res['project'])
    w('')
    w('扫描时间 %s；文件 %d 个。这份底稿给审计的人看，不交给客户。' % (res['scannedAt'], res['files']))
    if res.get('git'):
        g = res['git']
        w('代码版本：%s 分支，最近一次提交 %s，共 %s 次提交%s%s。' % (g['branch'], g['last'], g['commits'], '；工作区有没提交的改动' if g['dirty'] else '', '；只查了 %s 之后改过的文件' % g['since'] if g['since'] else ''))
    w('')
    w('## 1. 项目概况')
    w('')
    w('| 语言 | 文件数 | 行数 |')
    w('|---|---|---|')
    for l in res['languages'][:12]:
        w('| %s | %d | %d |' % (l['lang'], l['files'], l['lines']))
    w('')
    st = res['stack']
    w('- 框架：%s' % ('、'.join(st['frameworks']) or '没认出来'))
    w('- 接口文档自动生成：%s；自动建表：%s' % (st.get('apidoc', '无'), st.get('orm_auto', '无')))
    w('- 依赖 %d 个；测试文件 %d 个，源代码文件 %d 个' % (res['deps']['count'], res['tests']['testFiles'], res['tests']['srcFiles']))
    if st['commands']:
        w('- 建议跑一遍确认能构建、测试能过：`%s`' % '`、`'.join(st['commands']))
    w('')
    w('## 2. 交付物（自动判断，要人工确认）')
    w('')
    w('| 项 | 自动判断 | 文件 | 缺的内容 |')
    w('|---|---|---|---|')
    for d in res['deliverables']:
        w('| %s | %s | %s | %s |' % (d['item'], d['auto'], '<br>'.join(d['files'][:5]) + (' 等 %d 个' % len(d['files']) if len(d['files']) > 5 else ''), '；'.join(x for x in ('、'.join(d['missing']), d['note']) if x)))
    w('')
    cons = res['config']
    if cons['envUndocumented'] or cons['springUndefined']:
        w('## 3. 配置一致性')
        w('')
        for k, v in cons['envUndocumented'].items():
            w('- 程序读了环境变量 `%s`，文档和配置样例里没写（%s）' % (k, v[0]))
        for k, v in cons['springUndefined'].items():
            w('- 代码读配置 `%s`，配置文件里没定义、也没默认值（%s）' % (k, v[0]))
        w('')
    w('## 4. 自动扫描疑点（逐条核对，在审计结论的 autoReview 里写结论）')
    w('')
    by_rule = OrderedDict()
    for h in sorted(res['hits'], key=lambda h: (LEVELS.index(h['level']) if h['level'] in LEVELS else 9, h['rule'])):
        by_rule.setdefault(h['rule'], []).append(h)
    for rule, hs in by_rule.items():
        w('### %s　%s（%s，%d 处）' % (rule, hs[0]['title'] if rule not in ('DEP-KNOWN-VULN', 'DELIV-ENV-UNDOC', 'BUG-CONF-UNDEFINED', 'REASON-LONG-FUNC', 'REASON-LONG-FILE', 'REASON-DUPLICATE') else rule_title(rule), hs[0]['level'], len(hs)))
        w('')
        w('处理办法：%s' % hs[0]['advice'])
        w('')
        for h in hs[:40]:
            loc = h['file'] + (':%d' % h['line'] if h['line'] else '')
            w('- `%s` %s%s%s' % (h['id'], loc, '（测试代码）' if h.get('inTest') else '', ('　`%s`' % h['code'].replace('`', "'")) if h['code'] else ('　' + h['title'] if rule in ('DEP-KNOWN-VULN', 'DELIV-ENV-UNDOC', 'BUG-CONF-UNDEFINED', 'REASON-LONG-FUNC', 'REASON-LONG-FILE', 'REASON-DUPLICATE') else '')))
        if len(hs) > 40:
            w('- ……还有 %d 处，见 scan.json' % (len(hs) - 40))
        w('')
    if res['overflow']:
        w('同一文件同一规则超过 8 处的只记了前 8 处：%s' % '；'.join('%s %s 另有 %d 处' % (o['rule'], o['file'], o['more']) for o in res['overflow'][:20]))
        w('')
    if res['deps']['risky']:
        pend = [d for d in res['deps']['risky'] if d['level'] == '待核']
        if pend:
            w('## 5. 版本没读到、要人工确认的组件')
            w('')
            for d in pend:
                w('- %s（%s）：%s' % (d['name'], d['file'], d['desc']))
            w('')
    tools = res.get('tools') or {}
    w('## 6. 外部工具')
    w('')
    if 'gitleaks' in tools:
        w('- 密钥扫描 gitleaks：%s' % '；'.join('%s %s' % ('当前文件' if r['mode'] == 'dir' else '历史提交', ('发现 %d 处' % r['found']) if 'found' in r else ('出错 ' + r['error'])) for r in tools['gitleaks']['runs']))
    else:
        w('- 本机没装 gitleaks，没做密钥的专门扫描和历史提交扫描')
    if 'npmAudit' in tools:
        for a in tools['npmAudit']:
            w('- npm audit（%s）：%s' % (a['dir'], a.get('error') or json.dumps(a['counts'], ensure_ascii=False)))
    w('')
    (Path(outdir) / '审计底稿.md').write_text('\n'.join(L), encoding='utf-8')


def rule_title(rule):
    return {'DEP-KNOWN-VULN': '有已知漏洞的组件版本', 'DELIV-ENV-UNDOC': '程序要读的配置项文档里没写', 'BUG-CONF-UNDEFINED': '配置项没定义',
            'REASON-LONG-FUNC': '函数太长', 'REASON-LONG-FILE': '文件太长', 'REASON-DUPLICATE': '重复代码'}.get(rule, rule)


# ---------------- 结论模板 ----------------
def template(res, outdir):
    p = Path(outdir) / '审计结论.json'
    if p.exists():
        return False
    rules = OrderedDict()
    for h in res['hits']:
        rules.setdefault(h['rule'], 0)
        rules[h['rule']] += 1
    data = OrderedDict([
        ('project', res['project']),
        ('version', (res.get('git') or {}).get('last', '')[:8]),
        ('purpose', '验收'),
        ('scope', '全部源代码和随附文档'),
        ('date', datetime.date.today().isoformat()),
        ('auditor', ''),
        ('basis', []),
        ('summary', ''),
        ('verdict', ''),
        ('requirements', []),
        ('issues', []),
        ('autoReview', [{'rule': r, 'count': n, 'verdict': '', 'reason': ''} for r, n in rules.items()]),
        ('deliverables', [{'item': d['item'], 'status': {'有': '齐全', '代码自带': '齐全'}.get(d['auto'], d['auto']), 'note': ('缺：' + '、'.join(d['missing'])) if d['missing'] else d['note']} for d in res['deliverables']]),
        ('checks', [{'item': '按说明构建通过', 'result': '未做', 'note': ''}, {'item': '自动化测试全部通过', 'result': '未做', 'note': ''},
                    {'item': '按部署手册在干净环境装起来', 'result': '未做', 'note': ''}, {'item': '主要业务流程走通', 'result': '未做', 'note': ''}]),
    ])
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return True


# ---------------- 合并自动命中 ----------------
def match_review(h, r):
    if r.get('ids') and h['id'] not in r['ids']:
        return False
    if r.get('id') and h['id'] != r['id']:
        return False
    if r.get('rule') and h['rule'] != r['rule']:
        return False
    if r.get('path') and not h['file'].startswith(r['path']):
        return False
    return bool(r.get('ids') or r.get('id') or r.get('rule'))


def merge(res, con):
    """返回 (问题列表, 自动命中核对情况)。属实的自动命中按规则并成问题；更具体的核对条目优先。"""
    reviews = con.get('autoReview') or []
    # 越具体的越优先：按 id > ids > rule+path > rule
    def spec(r):
        return 0 if r.get('id') else 1 if r.get('ids') else 2 if r.get('path') else 3
    reviews = sorted([r for r in reviews if r.get('verdict')], key=spec)
    issues = [dict(i) for i in con.get('issues') or []]
    by_id = {i.get('id'): i for i in issues}
    stat = Counter()
    pending, dismissed = [], []
    auto_groups = OrderedDict()
    for h in res['hits']:
        r = next((r for r in reviews if match_review(h, r)), None)
        if not r:
            pending.append(h)
            stat['待核'] += 1
            continue
        stat[r['verdict']] += 1
        if r['verdict'] != '属实':
            dismissed.append((h, r))
            continue
        loc = h['file'] + (':%d' % h['line'] if h['line'] else '')
        if r.get('issue') and r['issue'] in by_id:
            tgt = by_id[r['issue']]
            w = tgt.get('where') or []
            if isinstance(w, str):
                w = [w] if w else []
            if loc not in w:
                w.append(loc)
            tgt['where'] = w
            continue
        key = (h['rule'], r.get('level') or h['level'], h['title'] if h['rule'] in ('DEP-KNOWN-VULN', 'DELIV-ENV-UNDOC', 'BUG-CONF-UNDEFINED') else '')
        g = auto_groups.get(key)
        if not g:
            g = auto_groups[key] = {'dim': h['dim'], 'level': key[1], 'title': h['title'] if key[2] else re.sub(r'（[^）]*\d[^）]*）', '', h['title']),
                                    'where': [], 'detail': r.get('reason') or '', 'impact': r.get('impact') or '', 'fix': r.get('fix') or h['advice'], 'auto': True}
            if r.get('req'):
                g['req'] = r['req']
        g['where'].append(loc)
    issues += list(auto_groups.values())
    for i in issues:
        if isinstance(i.get('where'), str):
            i['where'] = [i['where']] if i['where'] else []
    n = 0
    for i in issues:
        if not i.get('id'):
            n += 1
            while 'A%02d' % n in by_id:
                n += 1
            i['id'] = 'A%02d' % n
    issues.sort(key=lambda i: (LEVELS.index(i['level']) if i.get('level') in LEVELS else 9, bool(i.get('auto')), str(i.get('id'))))
    return issues, stat, pending, dismissed


def suggest_verdict(issues, purpose):
    c = Counter(i.get('level') for i in issues)
    act = {'验收': '验收', '上线': '上线'}.get(purpose, '合入')
    if c['严重']:
        return '不建议%s' % act, '有 %d 个严重问题' % c['严重']
    if c['高']:
        return '修完高级别问题后再%s' % act, '有 %d 个高级别问题' % c['高']
    if c['中']:
        return '可以%s，其余问题限期整改' % act, '没有严重和高级别问题'
    return '可以%s' % act, '没有严重、高、中级别问题'


# ---------------- 检查 ----------------
def check(outdir):
    outdir = Path(outdir)
    errs, warns = [], []
    res = load(outdir / 'scan.json')
    try:
        con = load(outdir / '审计结论.json')
    except ValueError as e:
        return ['审计结论.json 不是合法的 JSON：%s' % e], []
    if not (con.get('summary') or '').strip():
        errs.append('summary（总体结论）没写')
    if not con.get('requirements'):
        warns.append('requirements（需求对照）是空的：有需求依据的要逐条对照；确实没有需求文档的，在 basis 里写明「按代码和文档推断功能」')
    ids = set()
    for i in con.get('issues') or []:
        for k in ('level', 'dim', 'title'):
            if not i.get(k):
                errs.append('问题 %s 缺 %s' % (i.get('id') or i.get('title') or '?', k))
        if i.get('level') and i['level'] not in LEVELS:
            errs.append('问题 %s 的级别「%s」不在 %s 里' % (i.get('id'), i['level'], '/'.join(LEVELS)))
        if i.get('dim') and i['dim'] not in DIMS:
            errs.append('问题 %s 的维度「%s」不在 %s 里' % (i.get('id'), i['dim'], '/'.join(DIMS)))
        if not i.get('where'):
            warns.append('问题 %s 没写位置 where' % i.get('id'))
        if not i.get('fix'):
            warns.append('问题 %s 没写怎么改 fix' % i.get('id'))
        if i.get('id'):
            if i['id'] in ids:
                errs.append('问题编号 %s 重复' % i['id'])
            ids.add(i['id'])
    issues, stat, pending, _ = merge(res, con)
    reqs_with_issue = {i.get('req') for i in issues}
    for r in con.get('requirements') or []:
        if r.get('status') not in REQ_STATUS:
            errs.append('需求 %s 的状态「%s」不在 %s 里' % (r.get('id'), r.get('status'), '/'.join(REQ_STATUS)))
        elif r['status'] in ('部分实现', '未实现', '与需求不一致') and r.get('id') not in reqs_with_issue:
            warns.append('需求 %s 是「%s」，问题清单里没有对应的问题（问题里写 req: "%s"）' % (r.get('id'), r['status'], r.get('id')))
    for r in con.get('autoReview') or []:
        if r.get('verdict') and r['verdict'] not in VERDICTS:
            errs.append('autoReview 里 %s 的结论「%s」不在 %s 里' % (r.get('rule') or r.get('id'), r['verdict'], '/'.join(VERDICTS)))
        if r.get('verdict') in ('误报', '可接受') and not r.get('reason'):
            warns.append('autoReview 里 %s 判了「%s」但没写理由' % (r.get('rule') or r.get('id'), r['verdict']))
        if r.get('issue') and r['issue'] not in ids:
            errs.append('autoReview 里 %s 指向的问题 %s 不存在' % (r.get('rule') or r.get('id'), r['issue']))
    for d in con.get('deliverables') or []:
        if d.get('status') not in DELIV_STATUS:
            errs.append('交付物「%s」的状态「%s」不在 %s 里' % (d.get('item'), d.get('status'), '/'.join(DELIV_STATUS)))
        elif d['status'] == '待核':
            warns.append('交付物「%s」还是待核' % d.get('item'))
    for c in con.get('checks') or []:
        if c.get('result') not in CHECK_RESULT:
            errs.append('验证项「%s」的结果「%s」不在 %s 里' % (c.get('item'), c.get('result'), '/'.join(CHECK_RESULT)))
    if pending:
        warns.append('还有 %d 条自动扫描疑点没核对（规则：%s）' % (len(pending), '、'.join(sorted({h['rule'] for h in pending}))))
    deliv_issue = any(i.get('dim') == '交付物' for i in issues)
    if any(d.get('status') in ('缺失', '不全') for d in con.get('deliverables') or []) and not deliv_issue:
        warns.append('交付物有缺失或不全，问题清单里没有「交付物」维度的问题')
    return errs, warns


# ---------------- 报告 ----------------
CSS = '''
body{font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC","Source Han Sans SC",sans-serif;color:#1f2329;max-width:1080px;margin:24px auto;padding:0 24px;line-height:1.65;font-size:14px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 12px;padding-bottom:6px;border-bottom:2px solid #e5e6eb}h3{font-size:15px;margin:18px 0 6px}
.meta{color:#646a73;font-size:13px}.meta span{margin-right:18px}
.verdict{margin:18px 0;padding:14px 18px;border-radius:8px;background:#f2f3f5;border-left:6px solid #3370ff}
.verdict.bad{border-color:#f54a45;background:#fff0f0}.verdict.warn{border-color:#ff8800;background:#fff7ec}.verdict.ok{border-color:#00b42a;background:#eefbf0}
.verdict b{font-size:18px}
.tiles{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.tile{flex:1;min-width:92px;padding:10px 12px;border:1px solid #e5e6eb;border-radius:8px}
.tile .n{font-size:24px;font-weight:600}.tile .l{color:#646a73;font-size:12px}
table{border-collapse:collapse;width:100%;margin:8px 0 16px;font-size:13px}th,td{border:1px solid #dee0e3;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f5f6f7;font-weight:600;white-space:nowrap}
.lv{display:inline-block;padding:0 8px;border-radius:10px;font-size:12px;white-space:nowrap;color:#fff}
.lv-严重{background:#c9353f}.lv-高{background:#f54a45}.lv-中{background:#ff8800}.lv-低{background:#3370ff}.lv-建议{background:#8f959e}
.st{white-space:nowrap;font-weight:600}.st-good{color:#00a02a}.st-bad{color:#e22e28}.st-mid{color:#d97a00}.st-na{color:#8f959e}
code{font-family:Consolas,Menlo,monospace;font-size:12px;background:#f5f6f7;padding:1px 4px;border-radius:3px;overflow-wrap:anywhere}
td.pos{width:30%}td.pos code{white-space:nowrap}
.issue{border:1px solid #e5e6eb;border-radius:8px;padding:10px 14px;margin:10px 0;page-break-inside:avoid}
.issue .t{font-weight:600;font-size:14px}.issue .row{display:flex;gap:10px}.issue .k{color:#646a73;flex:0 0 56px}.issue .v{flex:1}
.small{color:#646a73;font-size:12px}
@media print{body{margin:0;max-width:none}h2{page-break-after:avoid}.issue{page-break-inside:avoid}}
'''


def e(s):
    return html.escape(str(s if s is not None else ''))


def st_class(s):
    if s in ('已实现', '齐全', '通过'):
        return 'st-good'
    if s in ('未实现', '缺失', '不通过', '与需求不一致'):
        return 'st-bad'
    if s in ('部分实现', '不全', '部分通过', '待核'):
        return 'st-mid'
    return 'st-na'


def render(outdir):
    outdir = Path(outdir)
    res = load(outdir / 'scan.json')
    con = load(outdir / '审计结论.json')
    issues, stat, pending, dismissed = merge(res, con)
    purpose = con.get('purpose') or '验收'
    sv, why = suggest_verdict(issues, purpose)
    verdict = con.get('verdict') or sv
    lc = Counter(i['level'] for i in issues)
    dc = Counter(i['dim'] for i in issues)
    vclass = 'bad' if lc['严重'] else 'warn' if lc['高'] else 'ok'
    reqs = con.get('requirements') or []
    rc = Counter(r.get('status') for r in reqs)
    deliv = con.get('deliverables') or [{'item': d['item'], 'status': d['auto'], 'note': '、'.join(d['missing'])} for d in res['deliverables']]
    checks = con.get('checks') or []
    title = '%s 代码审计报告' % (con.get('project') or res['project'])

    H = []
    a = H.append
    a('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>%s</title><style>%s</style></head><body>' % (e(title), CSS))
    a('<h1>%s</h1>' % e(title))
    a('<div class="meta">%s</div>' % ''.join('<span>%s：%s</span>' % (k, e(v)) for k, v in [
        ('版本', con.get('version')), ('审计目的', {'验收': '交付验收', '上线': '上线前检查', '审查': '代码审查'}.get(purpose, purpose)),
        ('审计日期', con.get('date')), ('审计人', con.get('auditor'))] if v))
    if con.get('scope'):
        a('<div class="meta">审计范围：%s</div>' % e(con['scope']))
    if con.get('basis'):
        a('<div class="meta">审计依据：%s</div>' % e('；'.join(con['basis'])))

    a('<h2>一、结论</h2>')
    a('<div class="verdict %s"><b>%s</b><div>%s</div></div>' % (vclass, e(verdict), e(con.get('summary') or '')))
    a('<div class="tiles">%s</div>' % ''.join('<div class="tile"><div class="n">%d</div><div class="l"><span class="lv lv-%s">%s</span> 问题</div></div>' % (lc[l], l, l) for l in LEVELS))
    if reqs:
        a('<div class="tiles">%s</div>' % ''.join('<div class="tile"><div class="n">%d</div><div class="l">需求%s</div></div>' % (rc[s], s) for s in REQ_STATUS if rc[s] or s in ('已实现', '未实现')))
    a('<table><tr><th>审计维度</th><th>问题数</th><th>其中严重和高</th></tr>')
    for d in DIMS:
        if dc[d]:
            a('<tr><td>%s</td><td>%d</td><td>%d</td></tr>' % (d, dc[d], sum(1 for i in issues if i['dim'] == d and i['level'] in ('严重', '高'))))
    a('</table>')

    sec = 2
    def h2(t):
        nonlocal sec
        a('<h2>%s、%s</h2>' % ('一二三四五六七八九十'[sec - 1], t))
        sec += 1

    if reqs:
        h2('功能实现情况（逐条对照需求）')
        a('<table><tr><th>编号</th><th>需求</th><th>状态</th><th>实现位置</th><th>说明</th></tr>')
        for r in reqs:
            a('<tr><td>%s</td><td>%s</td><td class="st %s">%s</td><td>%s</td><td>%s</td></tr>' % (e(r.get('id')), e(r.get('text')), st_class(r.get('status')), e(r.get('status')), e(r.get('where')), e(r.get('note'))))
        a('</table>')

    h2('问题清单')
    if not issues:
        a('<p>没有发现需要修改的问题。</p>')
    a('<table><tr><th>编号</th><th>级别</th><th>维度</th><th>问题</th><th class="pos">位置</th></tr>')
    for i in issues:
        w = i.get('where') or []
        a('<tr><td>%s</td><td><span class="lv lv-%s">%s</span></td><td style="white-space:nowrap">%s</td><td>%s</td><td class="pos">%s</td></tr>' % (
            e(i['id']), e(i['level']), e(i['level']), e(i['dim']), e(i['title']), '<br>'.join('<code>%s</code>' % e(x) for x in w[:3]) + (' 等 %d 处' % len(w) if len(w) > 3 else '')))
    a('</table>')
    for i in issues:
        a('<div class="issue"><div class="t">%s　<span class="lv lv-%s">%s</span>　%s</div>' % (e(i['id']), e(i['level']), e(i['level']), e(i['title'])))
        w = i.get('where') or []
        if w:
            a('<div class="row"><span class="k">位置</span><span class="v">%s</span></div>' % ('、'.join('<code>%s</code>' % e(x) for x in w[:20]) + (' 等共 %d 处' % len(w) if len(w) > 20 else '')))
        for k, lab in (('detail', '现象'), ('impact', '影响'), ('fix', '修改建议')):
            if i.get(k):
                a('<div class="row"><span class="k">%s</span><span class="v">%s</span></div>' % (lab, e(i[k])))
        a('</div>')

    h2('交付物检查')
    a('<table><tr><th>交付物</th><th>状态</th><th>说明</th></tr>')
    for d in deliv:
        a('<tr><td>%s</td><td class="st %s">%s</td><td>%s</td></tr>' % (e(d.get('item')), st_class(d.get('status')), e(d.get('status')), e(d.get('note'))))
    a('</table>')

    if checks:
        h2('运行验证')
        a('<table><tr><th>验证项</th><th>结果</th><th>说明</th></tr>')
        for c in checks:
            a('<tr><td>%s</td><td class="st %s">%s</td><td>%s</td></tr>' % (e(c.get('item')), st_class(c.get('result')), e(c.get('result')), e(c.get('note'))))
        a('</table>')

    h2('附：项目概况和审计方法')
    a('<table><tr><th>语言</th><th>文件数</th><th>代码行数</th></tr>%s</table>' % ''.join('<tr><td>%s</td><td>%d</td><td>%d</td></tr>' % (e(l['lang']), l['files'], l['lines']) for l in res['languages'][:10]))
    st = res['stack']
    a('<p>框架：%s；第三方依赖 %d 个；自动化测试文件 %d 个。</p>' % (e('、'.join(st['frameworks']) or '—'), res['deps']['count'], res['tests']['testFiles']))
    a('<p>方法：人工逐模块阅读代码，对照需求逐条核对功能；结合自动扫描（写法风险、密钥、配置一致性、组件已知漏洞、重复代码），自动扫描的每条疑点都经人工核对，属实的计入问题清单。'
      '自动扫描共 %d 条疑点：属实 %d 条、误报 %d 条、可接受 %d 条%s。</p>' % (len(res['hits']), stat['属实'], stat['误报'], stat['可接受'], ('、未核对 %d 条' % stat['待核']) if stat['待核'] else ''))
    a('<p class="small">级别说明：严重＝可被直接利用造成数据泄露、篡改或服务被控制，或核心功能不能用、金额算错，必须修复；高＝特定条件下出错或被利用，影响主要功能，%s前修复；中＝影响局部功能或体验，限期修复；低＝规范和可维护性问题，排期修复；建议＝改进意见。</p>' % {'验收': '验收', '上线': '上线'}.get(purpose, '合入'))
    a('</body></html>')
    (outdir / '审计报告.html').write_text('\n'.join(H), encoding='utf-8')

    # Markdown 版（可转 Word）
    M = []
    m = M.append
    m('# %s' % title)
    m('')
    m('；'.join('%s：%s' % (k, v) for k, v in [('版本', con.get('version')), ('审计日期', con.get('date')), ('审计范围', con.get('scope'))] if v))
    if con.get('basis'):
        m('')
        m('审计依据：' + '；'.join(con['basis']))
    m('')
    m('## 一、结论')
    m('')
    m('**%s**' % verdict)
    m('')
    m(con.get('summary') or '')
    m('')
    m('问题数：' + '，'.join('%s %d' % (l, lc[l]) for l in LEVELS))
    sec_md = 2
    if reqs:
        m('')
        m('## %s、功能实现情况' % '一二三四五六七'[sec_md - 1]); sec_md += 1
        m('')
        m('| 编号 | 需求 | 状态 | 实现位置 | 说明 |')
        m('|---|---|---|---|---|')
        for r in reqs:
            m('| %s | %s | %s | %s | %s |' % tuple(str(r.get(k) or '').replace('|', '/').replace('\n', ' ') for k in ('id', 'text', 'status', 'where', 'note')))
    m('')
    m('## %s、问题清单' % '一二三四五六七'[sec_md - 1]); sec_md += 1
    for i in issues:
        m('')
        m('### %s【%s】%s' % (i['id'], i['level'], i['title']))
        m('')
        m('- 维度：%s' % i['dim'])
        if i.get('where'):
            m('- 位置：' + '、'.join('`%s`' % x for x in i['where'][:20]) + (' 等共 %d 处' % len(i['where']) if len(i['where']) > 20 else ''))
        for k, lab in (('detail', '现象'), ('impact', '影响'), ('fix', '修改建议')):
            if i.get(k):
                m('- %s：%s' % (lab, i[k]))
    m('')
    m('## %s、交付物检查' % '一二三四五六七'[sec_md - 1]); sec_md += 1
    m('')
    m('| 交付物 | 状态 | 说明 |')
    m('|---|---|---|')
    for d in deliv:
        m('| %s | %s | %s |' % tuple(str(d.get(k) or '').replace('|', '/') for k in ('item', 'status', 'note')))
    if checks:
        m('')
        m('## %s、运行验证' % '一二三四五六七'[sec_md - 1]); sec_md += 1
        m('')
        m('| 验证项 | 结果 | 说明 |')
        m('|---|---|---|')
        for c in checks:
            m('| %s | %s | %s |' % tuple(str(c.get(k) or '').replace('|', '/') for k in ('item', 'result', 'note')))
    (outdir / '审计报告.md').write_text('\n'.join(M) + '\n', encoding='utf-8')
    return {'verdict': verdict, 'suggested': sv, 'why': why, 'levels': lc, 'pending': len(pending), 'issues': len(issues)}
