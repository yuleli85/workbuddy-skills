'use strict';
// 菜单巡检：找出所有菜单项，逐个点开，看页面有没有报错、接口有没有出错、是不是空白页。

const path = require('path');
const { getPath, interp, safeName, urlMatches } = require('./util');
const { shortUrl, cleanErr } = require('./steps');

// 常见后台框架的菜单写法；auto 时按顺序找页面上有的那种
const PROFILES = {
  element: { root: '.el-menu', title: '.el-sub-menu__title, .el-submenu__title', sub: '.el-sub-menu, .el-submenu', open: 'is-opened', leaf: '.el-menu-item' },
  antd: { root: '.ant-menu', title: '.ant-menu-submenu-title', sub: '.ant-menu-submenu', open: 'ant-menu-submenu-open', leaf: '.ant-menu-item' },
  arco: { root: '.arco-menu', title: '.arco-menu-inline-header', sub: '.arco-menu-inline', open: 'arco-menu-inline-open', leaf: '.arco-menu-item' },
  naive: { root: '.n-menu', title: '.n-submenu > .n-menu-item', sub: '.n-submenu', open: 'n-submenu--expanded', leaf: '.n-menu-item:not(.n-submenu > .n-menu-item)' },
  iview: { root: '.ivu-menu', title: '.ivu-menu-submenu-title', sub: '.ivu-menu-submenu', open: 'ivu-menu-opened', leaf: '.ivu-menu-item' },
  generic: { root: 'aside, nav, [role=navigation], .sidebar, .side-menu, .menu', title: '[aria-expanded]', sub: '[aria-expanded]', open: '', leaf: 'a[href], [role=menuitem]' },
};

const DEFAULT_ERROR_TEXTS = ['404', 'Not Found', '页面不存在', '页面找不到', '无权访问', '403', '500', '系统异常', '服务器错误', '服务异常', 'Internal Server Error', '加载失败'];
const { ERROR_SELECTORS } = require('./session');

async function detectProfile(page, M) {
  if (M.dom && M.dom.leaf) return { name: 'custom', root: 'body', title: '', sub: '', open: '', ...M.dom };
  const want = (M.dom && M.dom.profile) || 'auto';
  const names = want === 'auto' ? Object.keys(PROFILES) : [want];
  for (const n of names) {
    const p = PROFILES[n];
    const has = await page.locator(`:is(${p.root}) :is(${p.leaf}), :is(${p.root}) :is(${p.title || p.leaf})`).count().catch(() => 0);
    if (has) return { name: n, ...p };
  }
  return null;
}

// 在页面里执行：列出看得见的菜单项（带上层菜单名），以及没展开的子菜单标题
function scanFn({ P, mark }) {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const roots = [...document.querySelectorAll(P.root)].filter(vis);
  const inRoot = el => roots.some(r => r.contains(el));
  const chain = el => {
    const out = [];
    if (!P.sub) return out;
    let cur = el.parentElement;
    while (cur) {
      const sub = cur.closest(P.sub);
      if (!sub || !inRoot(sub)) break;
      const t = P.title ? [...sub.querySelectorAll(P.title)].find(x => x.closest(P.sub) === sub) : null;
      if (t && t !== el && !t.contains(el)) out.unshift(txt(t));
      cur = sub.parentElement;
    }
    return out;
  };
  const leaves = [], titles = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(P.leaf)) {
    if (!inRoot(el) || !vis(el)) continue;
    if (P.title && el.matches(P.title)) continue;
    const name = txt(el);
    if (!name) continue;
    const parents = chain(el);
    const key = [...parents, name].join(' / ');
    if (seen.has(key)) continue; seen.add(key);
    const a = el.matches('a[href]') ? el : el.querySelector('a[href]') || el.closest('a[href]');
    leaves.push({ key, name, parents, href: a ? a.getAttribute('href') : null, disabled: el.matches('.is-disabled, .ant-menu-item-disabled, [aria-disabled=true]') });
  }
  if (P.title) for (const el of document.querySelectorAll(P.title)) {
    if (!inRoot(el) || !vis(el)) continue;
    const sub = P.sub ? el.closest(P.sub) : null;
    const open = el.getAttribute('aria-expanded') === 'true' || (sub && P.open && sub.classList.contains(P.open));
    const key = [...chain(el), txt(el)].join(' / ');
    titles.push({ key, open });
  }
  if (mark) {
    document.querySelectorAll('[data-autotest]').forEach(e => e.removeAttribute('data-autotest'));
    const [kind, key] = mark;
    const pool = kind === 'leaf' ? document.querySelectorAll(P.leaf) : document.querySelectorAll(P.title);
    for (const el of pool) {
      if (!inRoot(el) || !vis(el)) continue;
      if (kind === 'leaf' && P.title && el.matches(P.title)) continue;
      if ([...chain(el), txt(el)].join(' / ') === key) { el.setAttribute('data-autotest', '1'); return { marked: true }; }
    }
    return { marked: false };
  }
  return { leaves, titles };
}

async function scan(page, P, mark) { return page.evaluate(scanFn, { P, mark }); }

// 一层层展开子菜单，收齐所有菜单项。手风琴菜单（一次只开一个）也能收齐。
async function discoverDom(page, P) {
  const all = new Map();
  const tried = new Set();
  for (let round = 0; round < 200; round++) {
    const { leaves, titles } = await scan(page, P);
    for (const l of leaves) if (!all.has(l.key)) all.set(l.key, l);
    const next = titles.find(t => !t.open && !tried.has(t.key));
    if (!next) break;
    tried.add(next.key);
    await openPath(page, P, next.key.split(' / '));
  }
  return [...all.values()];
}

// 按「上层 / 上层 / 名字」把子菜单依次展开
async function openPath(page, P, names) {
  for (let i = 1; i <= names.length; i++) {
    const key = names.slice(0, i).join(' / ');
    const { titles } = await scan(page, P);
    const t = titles.find(x => x.key === key);
    if (!t) return false;
    if (t.open) continue;
    const r = await scan(page, P, ['title', key]);
    if (!r.marked) return false;
    await page.locator('[data-autotest="1"]').click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(350);
  }
  return true;
}

// 菜单从接口取：适合顶部菜单、折叠菜单这类不好点的
async function discoverApi(S, M) {
  const A = M.api;
  const res = await S.request(A.request || { url: A.url });
  if (res.error) throw new Error('取菜单接口没通过：' + res.error);
  const list = getPath(res.json, A.list || '$.data');
  if (!Array.isArray(list)) throw new Error(`菜单接口返回里 ${A.list || '$.data'} 不是列表`);
  const out = [];
  const keyName = A.name || 'name', keyPath = A.path || 'path', keyChildren = A.children || 'children';
  const walk = (items, parents, base) => {
    for (const it of items) {
      const name = getPath(it, keyName) ?? getPath(it, 'meta.title') ?? '';
      let p = getPath(it, keyPath) || '';
      if (p && !p.startsWith('/') && !/^https?:/.test(p)) p = (base.replace(/\/$/, '') + '/' + p);
      const kids = getPath(it, keyChildren);
      const skip = A.skip && Object.entries(A.skip).some(([k, v]) => [].concat(v).map(String).includes(String(getPath(it, k))));
      if (skip) continue;
      if (Array.isArray(kids) && kids.length) walk(kids, [...parents, name], p || base);
      else if (p) out.push({ key: [...parents, name].join(' / '), name, parents, route: p });
    }
  };
  walk(list, [], '');
  return out;
}

async function pageProblems(page, M) {
  const errorTexts = M.errorTexts || DEFAULT_ERROR_TEXTS;
  const content = M.content || '.el-main, .app-main, main, .ant-layout-content, .arco-layout-content, #app';
  return page.evaluate(({ errorTexts, content, errSel, minText }) => {
    const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const area = [...document.querySelectorAll(content)].filter(vis).pop() || document.body;
    const text = (area.innerText || '').replace(/\s+/g, ' ').trim();
    const out = [];
    // 只在正文开头、或整段正文很短时才把「404」这种词当错误页，免得表格里的数字误报
    const head = text.slice(0, 200);
    const hit = errorTexts.find(t => (text.length < 300 ? text : head).includes(t));
    if (hit) out.push({ level: 'fail', text: `页面显示「${hit}」：${head.slice(0, 80)}` });
    const toasts = (window.__autotestToasts || []).splice(0);
    if (toasts.length) out.push({ level: 'fail', text: `弹出错误提示：${[...new Set(toasts)].join(' / ').slice(0, 150)}` });
    const rich = area.querySelector('table, canvas, svg, img, iframe, form, input, .el-table, .ant-table, video');
    if (text.length < minText && !rich) out.push({ level: 'warn', text: `页面几乎是空的（正文 ${text.length} 个字）` });
    return { out, textLen: text.length };
  }, { errorTexts, content, errSel: M.errorSelectors || ERROR_SELECTORS, minText: M.blankMinText ?? 10 });
}

// 菜单巡检主流程
async function runMenus(S) {
  const M = S.cfg.menus || {};
  const shotDir = path.join(S.opts.reportDir, 'shots');
  const page = await S.newPage();
  const mon = S.monitor(page, '进入首页');
  const startUrl = S.abs(M.start || '/');
  await page.goto(startUrl, { waitUntil: 'domcontentloaded' });
  await mon.settle(M.maxWait || 15000);
  await page.waitForTimeout(M.wait ?? 800);
  if (M.beforeSteps) { const { runSteps } = require('./steps'); await runSteps(S, page, M.beforeSteps, { label: '巡检前准备' }); }
  const homeEvents = mon.take();

  const source = M.source || (M.list ? 'list' : M.api ? 'api' : 'dom');
  let items = [], P = null;
  if (source === 'list') items = M.list.map(x => typeof x === 'string' ? { key: x, name: x, parents: [], route: x } : { key: x.name || x.url, name: x.name || x.url, parents: [], route: x.url });
  else if (source === 'api') items = await discoverApi(S, M);
  else {
    P = await detectProfile(page, M);
    if (!P) {
      const f = path.join(shotDir, '没找到菜单.png'); await page.screenshot({ path: f }).catch(() => {});
      throw new Error(`首页（${page.url()}）上没认出菜单。看截图「没找到菜单」：没登录上就检查 login；菜单写法特殊就在 menus.dom 里写 root/title/leaf 选择器，或改用 menus.source: api / list`);
    }
    items = await discoverDom(page, P);
  }
  const found = items.length;
  const ex = M.exclude || ['退出', '登出', '注销', 'logout'];
  const excluded = items.filter(it => ex.some(e => urlMatches(it.key, e) || (it.href && urlMatches(it.href, e)) || (it.route && urlMatches(it.route, e))));
  items = items.filter(it => !excluded.includes(it));
  if (S.opts.grep) items = items.filter(it => it.key.includes(S.opts.grep));
  if (M.limit) items = items.slice(0, M.limit);
  console.log(`  找到 ${found} 个菜单项，这次测 ${items.length} 个（${source === 'dom' ? '页面菜单，' + P.name + ' 样式' : source === 'api' ? '菜单接口' : '配置清单'}）${excluded.length ? `，排除：${excluded.map(e => e.name).join('、')}` : ''}`);

  const results = [];
  const routePrefix = M.routePrefix ?? '';
  for (const it of items) {
    const r = { key: it.key, name: it.name, parents: it.parents, status: 'pass', problems: [], apis: [] };
    results.push(r);
    if (it.disabled) { r.status = 'skip'; r.problems.push({ level: 'info', text: '菜单是禁用状态' }); continue; }
    mon.where = it.key; mon.take();
    // 清掉上一页记下的错误提示，不算到这一页头上
    await page.evaluate(() => { if (window.__autotestToasts) window.__autotestToasts.length = 0; }).catch(() => {});
    let t0 = Date.now();
    let popup = null;
    try {
      if (it.route) {
        const u = /^https?:/.test(it.route) ? it.route : S.abs(routePrefix + it.route);
        t0 = Date.now();
        await page.goto(u, { waitUntil: 'domcontentloaded' });
      } else {
        await openPath(page, P, it.parents.length ? it.parents : []);
        const mk = await scan(page, P, ['leaf', it.key]);
        if (!mk.marked) {
          // 被别的展开挤掉了，回首页再找一次
          await page.goto(startUrl, { waitUntil: 'domcontentloaded' }); await mon.settle(8000);
          await openPath(page, P, it.parents);
          if (!(await scan(page, P, ['leaf', it.key])).marked) throw new Error('菜单项找不到了（可能要先点别的才出现）');
        }
        const popP = page.context().waitForEvent('page', { timeout: 1500 }).catch(() => null);
        t0 = Date.now();
        await page.locator('[data-autotest="1"]').click({ timeout: 8000 });
        popup = await popP;
      }
      if (popup) {
        await popup.waitForLoadState('domcontentloaded').catch(() => {});
        r.url = popup.url(); r.external = true;
        r.problems.push({ level: 'info', text: '在新窗口打开（外链），只记网址不检查内容' });
        await popup.close().catch(() => {});
      } else {
        const settled = await mon.settle(M.maxWait || 15000);
        if (settled < 0) r.problems.push({ level: 'warn', text: `${Math.round((M.maxWait || 15000) / 1000)} 秒内页面请求没停（可能有轮询或一直在加载）` });
        await page.waitForTimeout(M.wait ?? 800);
        r.ms = Math.max(mon.lastActivity - t0, 0); // 点下去到最后一个请求结束
        r.url = page.url();
        const pp = await pageProblems(page, M);
        r.problems.push(...pp.out);
        if (r.ms > (M.slowMs || 5000)) r.problems.push({ level: 'warn', text: `打开慢：${(r.ms / 1000).toFixed(1)} 秒` });
      }
    } catch (e) {
      r.problems.push({ level: 'fail', text: '打不开：' + cleanErr(e) });
    }
    // 这一段里的报错和接口
    const C = S.cfg.checks || {};
    for (const ev of mon.take()) {
      if (ev.kind === 'api') { r.apis.push({ method: ev.method, url: shortUrl(ev.url), status: ev.status, ms: ev.ms, problem: ev.text }); if (ev.bad) r.problems.push({ level: 'fail', text: `${ev.text}：${ev.method} ${shortUrl(ev.url)}` }); }
      else if (ev.kind === 'pageerror') r.problems.push({ level: 'fail', text: '页面程序报错：' + ev.text });
      else if (ev.kind === 'console') {
        // Vue、React 会把渲染时的程序错误吞掉只打到控制台，这类按页面程序报错算
        const crash = /^(Uncaught\s+)?(TypeError|ReferenceError|SyntaxError|RangeError|EvalError|URIError)\b|Unhandled error during execution|The above error occurred in/.test(ev.text);
        r.problems.push({ level: crash || C.failOnConsoleError ? 'fail' : 'warn', text: (crash ? '页面程序报错：' : '控制台报错：') + ev.text.split('\n')[0] });
      }
      else if (ev.kind === 'reqfail') r.problems.push({ level: ev.type === 'xhr' || ev.type === 'fetch' || ev.type === 'script' ? 'fail' : 'warn', text: `${ev.text}：${ev.method} ${shortUrl(ev.url)}` });
      else if (ev.kind === 'resource') r.problems.push({ level: 'fail', text: `${ev.text}：${shortUrl(ev.url)}` });
    }
    r.status = r.problems.some(p => p.level === 'fail') ? 'fail' : r.problems.some(p => p.level === 'warn') ? 'warn' : 'pass';
    if (!popup) {
      const f = path.join(shotDir, safeName(`菜单-${results.length}-${it.key}`) + '.png');
      await page.screenshot({ path: f }).catch(() => {}); r.shot = f;
    }
    const mark = { pass: '通过', warn: '注意', fail: '有问题', skip: '跳过' }[r.status];
    const shown = r.problems.filter(p => p.level !== 'info').map(p => p.text).join('；');
    console.log(`  [${mark}] ${it.key}${shown ? '：' + shown.slice(0, 200) : ''}`);
  }
  await page.close();
  return { source, profile: P && P.name, items: results, excluded: excluded.map(e => e.key), home: homeEvents.filter(e => e.kind === 'pageerror' || e.bad).map(e => e.text + (e.url ? ' ' + shortUrl(e.url) : '')) };
}

module.exports = { runMenus };
