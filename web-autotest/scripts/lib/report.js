'use strict';
// 出报告：一个 HTML（浏览器直接打开）、一份 results.json（给 AI 和程序读）、一份 junit.xml（给流水线）。

const fs = require('fs');
const path = require('path');

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const LABEL = { pass: '通过', warn: '注意', fail: '有问题', skip: '跳过' };
const badge = st => `<span class="b ${st}">${LABEL[st] || st}</span>`;

function count(list) {
  const c = { total: list.length, pass: 0, warn: 0, fail: 0, skip: 0 };
  for (const x of list) c[x.status] = (c[x.status] || 0) + 1;
  return c;
}

function summarize(R) {
  const s = {};
  if (R.menus) s.menus = count(R.menus.items);
  if (R.apis) s.apis = { total: R.apis.length, fail: R.apis.filter(a => a.bad).length, pass: R.apis.filter(a => !a.bad).length };
  if (R.openapi) s.openapi = count(R.openapi);
  if (R.apiCases) s.apiCases = count(R.apiCases);
  if (R.flows) s.flows = count(R.flows);
  s.failed = Object.values(s).reduce((n, c) => n + (c.fail || 0), 0) + (R.fatal ? 1 : 0);
  return s;
}

function card(title, c, note) {
  if (!c) return '';
  return `<div class="card ${c.fail ? 'bad' : 'good'}"><div class="ct">${title}</div><div class="cn">${c.fail ? `<em>${c.fail}</em> / ` : ''}${c.total}</div>
  <div class="cs">${c.fail ? `${c.fail} 个有问题` : '全部正常'}${c.warn ? `，${c.warn} 个要注意` : ''}${c.skip ? `，${c.skip} 个跳过` : ''}</div>${note ? `<div class="cs">${note}</div>` : ''}</div>`;
}

function rel(dir, f) { return f ? path.relative(dir, f).split(path.sep).join('/') : ''; }

function stepsTable(dir, steps, head) {
  if (!steps || !steps.length) return '';
  return `<table class="steps"><tr><th>#</th><th>${head}</th><th>结果</th><th>说明</th></tr>${steps.map(s => `<tr class="${s.status}"><td>${s.index}</td><td>${esc(s.title)}</td><td>${badge(s.status)}</td><td>${esc(s.error || s.detail || '')}${s.shot ? ` <a href="${rel(dir, s.shot)}" target="_blank">截图</a>` : ''}${s.response && s.status === 'fail' ? `<pre>${esc(s.response)}</pre>` : ''}</td></tr>`).join('')}</table>`;
}

function html(R, dir) {
  const S = R.summary;
  const parts = [];
  parts.push(`<div class="cards">${card('菜单', S.menus)}${card('页面调到的接口', S.apis && { ...S.apis, warn: 0, skip: 0 })}${card('接口文档逐个调', S.openapi)}${card('接口用例', S.apiCases)}${card('功能用例', S.flows)}</div>`);
  if (R.fatal) parts.push(`<div class="fatal">没跑完：${esc(R.fatal)}</div>`);

  // 有问题的先列出来
  const issues = [];
  for (const m of (R.menus ? R.menus.items : [])) if (m.status === 'fail') issues.push(['菜单', m.key, m.problems.filter(p => p.level === 'fail').map(p => p.text).join('；')]);
  for (const a of (R.apis || [])) if (a.bad) issues.push(['接口', a.key, a.problems.join('；') + (a.pages.length ? `（在：${a.pages.join('、')}）` : '')]);
  for (const a of (R.openapi || [])) if (a.status === 'fail') issues.push(['接口文档', a.key, a.problem]);
  for (const f of [...(R.apiCases || []), ...(R.flows || [])]) if (f.status === 'fail') issues.push([f.kind === 'api' ? '接口用例' : '功能用例', f.name, f.error]);
  if (issues.length) parts.push(`<h2>要修的问题（${issues.length}）</h2><table><tr><th>类别</th><th>哪里</th><th>问题</th></tr>${issues.map(i => `<tr class="fail"><td>${i[0]}</td><td>${esc(i[1])}</td><td>${esc(i[2])}</td></tr>`).join('')}</table>`);
  else if (!R.fatal) parts.push('<h2 class="ok">没发现要修的问题</h2>');

  if (R.menus) {
    parts.push(`<h2>菜单巡检 <small>${R.menus.items.length} 项${R.menus.excluded.length ? `，排除：${esc(R.menus.excluded.join('、'))}` : ''}</small></h2>`);
    if (R.menus.home && R.menus.home.length) parts.push(`<div class="warnbox">首页本身：${esc(R.menus.home.join('；'))}</div>`);
    parts.push(`<table class="filt"><tr><th>#</th><th>菜单</th><th>结果</th><th>问题</th><th>耗时</th><th>调到的接口</th><th>截图</th></tr>${R.menus.items.map((m, i) => `<tr class="${m.status}"><td>${i + 1}</td><td>${esc(m.key)}<div class="u">${esc(m.url || '')}</div></td><td>${badge(m.status)}</td><td>${m.problems.map(p => `<div class="p ${p.level}">${esc(p.text)}</div>`).join('')}</td><td>${m.ms ? (m.ms / 1000).toFixed(1) + ' 秒' : ''}</td><td>${m.apis.length ? `<details><summary>${m.apis.length} 个</summary>${m.apis.map(a => `<div class="${a.problem ? 'p fail' : ''}">${a.status} ${esc(a.method)} ${esc(a.url)}${a.ms != null ? ` · ${a.ms}ms` : ''}${a.problem ? ' · ' + esc(a.problem) : ''}</div>`).join('')}</details>` : ''}</td><td>${m.shot ? `<a href="${rel(dir, m.shot)}" target="_blank"><img src="${rel(dir, m.shot)}" loading="lazy"></a>` : ''}</td></tr>`).join('')}</table>`);
  }
  if (R.apis && R.apis.length) {
    parts.push(`<h2>接口清单 <small>巡检和用例过程中页面实际调到的 ${R.apis.length} 个接口</small></h2>
    <table class="filt"><tr><th>接口</th><th>结果</th><th>调用次数</th><th>状态码</th><th>最慢</th><th>问题</th><th>在哪些页面</th></tr>${R.apis.map(a => `<tr class="${a.bad ? 'fail' : 'pass'}"><td>${esc(a.key)}</td><td>${badge(a.bad ? 'fail' : 'pass')}</td><td>${a.count}${a.bad ? `（错 ${a.bad}）` : ''}</td><td>${esc(Object.entries(a.statuses).map(([k, v]) => `${k}×${v}`).join(' '))}</td><td>${a.maxMs ? a.maxMs + 'ms' : ''}</td><td>${esc(a.problems.join('；'))}</td><td>${esc(a.pages.join('、'))}</td></tr>`).join('')}</table>`);
  }
  if (R.openapi) {
    parts.push(`<h2>接口文档逐个调</h2><table class="filt"><tr><th>接口</th><th>说明</th><th>结果</th><th>状态码</th><th>耗时</th><th>问题</th></tr>${R.openapi.map(a => `<tr class="${a.status}"><td>${esc(a.key)}</td><td>${esc(a.summary)}</td><td>${badge(a.status)}</td><td>${a.http ?? ''}</td><td>${a.ms != null ? a.ms + 'ms' : ''}</td><td>${esc(a.problem || '')}${a.status === 'fail' && a.sample ? `<pre>${esc(a.sample)}</pre>` : ''}</td></tr>`).join('')}</table>`);
  }
  for (const [title, list, head] of [['接口用例', R.apiCases, '接口'], ['功能用例', R.flows, '步骤']]) {
    if (!list || !list.length) continue;
    parts.push(`<h2>${title}</h2>${list.map(f => `<details class="case ${f.status}" ${f.status === 'fail' ? 'open' : ''}><summary>${badge(f.status)} ${esc(f.name)} <small>${esc(f.file || '')}${f.ms ? ' · ' + (f.ms / 1000).toFixed(1) + ' 秒' : ''}</small>${f.error ? `<div class="err">${esc(f.error)}</div>` : ''}</summary>${f.desc ? `<p>${esc(f.desc)}</p>` : ''}${stepsTable(dir, f.steps, head)}${f.cleanup && f.cleanup.length ? '<div class="sub">清理</div>' + stepsTable(dir, f.cleanup, head) : ''}</details>`).join('')}`);
  }

  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(R.name)} 自动化测试报告</title><style>
body{font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f5f6f8;color:#222}
.wrap{max-width:1280px;margin:0 auto;padding:24px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}h2 small{font-weight:normal;color:#888;font-size:13px}h2.ok{color:#1a7f37}
.meta{color:#666;font-size:13px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}
.card{background:#fff;border-radius:8px;padding:14px 18px;min-width:170px;border-top:4px solid #1a7f37;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.card.bad{border-top-color:#d1242f}.ct{color:#666;font-size:13px}.cn{font-size:28px;font-weight:600}.cn em{color:#d1242f;font-style:normal}.cs{color:#666;font-size:12px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.06)}
th,td{padding:8px 10px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}th{background:#fafafa;font-weight:600;white-space:nowrap}
td img{width:160px;border:1px solid #ddd;border-radius:4px}
.u{color:#999;font-size:12px;word-break:break-all}
.b{display:inline-block;padding:0 8px;border-radius:10px;font-size:12px;white-space:nowrap}
.b.pass{background:#dafbe1;color:#1a7f37}.b.fail{background:#ffebe9;color:#d1242f}.b.warn{background:#fff8c5;color:#9a6700}.b.skip{background:#eee;color:#666}
.p.fail{color:#d1242f}.p.warn{color:#9a6700}.p.info{color:#888}
tr.fail td:first-child{box-shadow:inset 3px 0 #d1242f}
pre{white-space:pre-wrap;word-break:break-all;background:#f6f8fa;padding:6px;border-radius:4px;font-size:12px;max-height:160px;overflow:auto;margin:4px 0 0}
details.case{background:#fff;border-radius:8px;margin:8px 0;padding:10px 14px;box-shadow:0 1px 2px rgba(0,0,0,.06)}details.case summary{cursor:pointer}
details.case table{box-shadow:none;margin-top:8px}.err{color:#d1242f;margin:4px 0 0 4px}.sub{margin-top:8px;color:#666}
.fatal,.warnbox{background:#ffebe9;color:#d1242f;padding:12px 16px;border-radius:8px;margin-top:16px}.warnbox{background:#fff8c5;color:#9a6700}
.tool{margin-top:12px}.tool label{cursor:pointer;color:#555}
body.only tr.pass,body.only tr.skip,body.only details.case.pass{display:none}
</style></head><body><div class="wrap">
<h1>${esc(R.name)} 自动化测试报告</h1>
<div class="meta">被测地址：${esc(R.baseUrl)} · 开始 ${esc(R.startedAt)} · 用时 ${(R.ms / 1000).toFixed(0)} 秒</div>
<div class="tool"><label><input type="checkbox" onchange="document.body.classList.toggle('only',this.checked)"> 只看有问题的</label></div>
${parts.join('\n')}
</div></body></html>`;
}

function junit(R) {
  const suites = [];
  const tc = (name, cls, st, msg, ms) => `<testcase name="${esc(name)}" classname="${esc(cls)}" time="${((ms || 0) / 1000).toFixed(2)}">${st === 'fail' ? `<failure message="${esc(msg)}"/>` : st === 'skip' ? '<skipped/>' : ''}</testcase>`;
  const suite = (name, cases) => `<testsuite name="${esc(name)}" tests="${cases.length}" failures="${cases.filter(c => c.includes('<failure')).length}">${cases.join('')}</testsuite>`;
  if (R.menus) suites.push(suite('菜单巡检', R.menus.items.map(m => tc(m.key, '菜单', m.status, m.problems.filter(p => p.level === 'fail').map(p => p.text).join('；'), m.ms))));
  if (R.apis) suites.push(suite('接口清单', R.apis.map(a => tc(a.key, '接口', a.bad ? 'fail' : 'pass', a.problems.join('；'), a.maxMs))));
  if (R.openapi) suites.push(suite('接口文档', R.openapi.map(a => tc(a.key, '接口文档', a.status, a.problem, a.ms))));
  if (R.apiCases) suites.push(suite('接口用例', R.apiCases.map(f => tc(f.name, '接口用例', f.status, f.error, f.ms))));
  if (R.flows) suites.push(suite('功能用例', R.flows.map(f => tc(f.name, '功能用例', f.status, f.error, f.ms))));
  return `<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>${suites.join('')}</testsuites>\n`;
}

function writeReport(R, dir) {
  R.summary = summarize(R);
  fs.writeFileSync(path.join(dir, 'report.html'), html(R, dir));
  fs.writeFileSync(path.join(dir, 'results.json'), JSON.stringify(R, null, 2));
  fs.writeFileSync(path.join(dir, 'junit.xml'), junit(R));
  return R.summary;
}

module.exports = { writeReport };
