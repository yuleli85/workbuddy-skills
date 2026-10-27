'use strict';
// 功能用例的步骤：页面操作、接口调用、各种判断。登录步骤也走这里。

const path = require('path');
const { interp, getPath, match, urlMatches, safeName } = require('./util');

// 选择器写法：css / Playwright 原生写法，另加几个中文后台常用的简写
//   按钮:保存  文字:新增成功  标签:用户名  提示:请输入用户名  角色:link:首页  测试id:save-btn
function loc(page, sel) {
  if (sel && typeof sel === 'object') {
    let l = loc(page, sel.selector);
    if (sel.hasText) l = l.filter({ hasText: sel.hasText });
    if (sel.nth !== undefined) l = l.nth(sel.nth);
    else if (sel.last) l = l.last();
    return l;
  }
  const s = String(sel);
  const m = s.match(/^(按钮|button|文字|text|标签|label|提示|placeholder|角色|role|测试id|testid)[:：](.+)$/);
  if (m) {
    const v = m[2].trim();
    switch (m[1]) {
      // 「登录」也能找到写成「登 录」的按钮
      case '按钮': case 'button': return visibleFirst(page.getByRole('button', { name: spaced(v) }));
      case '文字': case 'text': return visibleFirst(page.getByText(spaced(v)));
      // 标签、提示默认要整句一致（「用户名」不会误中「请输入用户名」）；前面加 ~ 表示包含就行
      case '标签': case 'label': return visibleFirst(page.getByLabel(v.replace(/^~/, ''), { exact: !v.startsWith('~') }));
      case '提示': case 'placeholder': return visibleFirst(page.getByPlaceholder(v.replace(/^~/, ''), { exact: !v.startsWith('~') }));
      case '测试id': case 'testid': return page.getByTestId(v);
      case '角色': case 'role': { const [role, ...name] = v.split(':'); return visibleFirst(name.length ? page.getByRole(role, { name: name.join(':') }) : page.getByRole(role)); }
    }
  }
  return page.locator(s).first();
}
function spaced(v) { return new RegExp([...v].map(c => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s*')); }
// 后台常把同名按钮藏在别的标签页里，只取看得见的那个
function visibleFirst(l) { return l.locator('visible=true').first(); }

const UI_KEYS = ['goto', 'click', 'dblclick', 'fill', 'type', 'choose', 'check', 'uncheck', 'press', 'hover', 'upload', 'wait',
  'expectText', 'expectNoText', 'expectVisible', 'expectHidden', 'expectUrl', 'expectCount', 'expectValue', 'expectToast',
  'screenshot', 'saveText', 'js', 'dialog', 'reload', 'set', 'api', 'log'];

function stepKind(step) {
  const k = Object.keys(step).find(k => UI_KEYS.includes(k));
  if (!k) throw new Error(`这一步看不懂：${JSON.stringify(step).slice(0, 120)}（能用的写法见说明）`);
  return k;
}

function title(step, kind) {
  if (step.name) return step.name;
  const v = step[kind];
  const s = typeof v === 'string' ? v : v && (v.url || v.selector || v.text || v.option || JSON.stringify(v));
  return `${kind} ${String(s ?? '').slice(0, 60)}`;
}

// 弹出的下拉选项（Element / Ant Design / Arco / 原生 role=option）
const OPTION_SEL = ':is(.el-select-dropdown__item, .el-cascader-node, .el-dropdown-menu__item, .ant-select-item-option, .ant-cascader-menu-item, .arco-select-option, .n-base-select-option, [role=option], li)';
// 提示消息
const TOAST_SEL = ':is(.el-message, .el-notification, .ant-message-notice, .ant-notification-notice, .arco-message, .n-message, .van-toast, [role=alert])';

async function runOne(S, page, step, kind, V) {
  const v = interp(step[kind], V);
  const timeout = step.timeout || undefined;
  switch (kind) {
    case 'goto': { const u = typeof v === 'string' ? v : v.url; await page.goto(S.abs(u), { waitUntil: 'domcontentloaded', timeout }); return; }
    case 'reload': await page.reload({ waitUntil: 'domcontentloaded' }); return;
    case 'click': await loc(page, v).click({ timeout, force: step.force }); return;
    case 'dblclick': await loc(page, v).dblclick({ timeout }); return;
    case 'hover': await loc(page, v).hover({ timeout }); return;
    case 'fill': {
      const pairs = v.selector ? [[v.selector, v.value]] : Object.entries(v);
      for (const [sel, val] of pairs) await loc(page, sel).fill(String(val ?? ''), { timeout });
      return;
    }
    case 'type': await loc(page, v.selector).pressSequentially(String(v.value), { delay: 30 }); return;
    case 'choose': {
      const field = loc(page, v.selector);
      const tag = await field.evaluate(el => el.tagName).catch(() => '');
      if (tag === 'SELECT') { await field.selectOption({ label: String(v.option) }); return; }
      // 组件库的下拉框，真正能点的是外壳，不是里面藏着的输入框
      const h = await field.elementHandle({ timeout });
      const shell = await h.evaluateHandle(el => el.closest('.el-select__wrapper, .el-select, .el-cascader, .el-date-editor, .ant-select-selector, .ant-select, .ant-cascader, .arco-select-view, .n-base-selection, .ivu-select-selection') || el);
      await shell.asElement().click({ timeout });
      await page.waitForTimeout(300);
      for (const opt of [].concat(v.option)) { // 级联选择写成列表：[广东, 深圳]
        await page.locator(OPTION_SEL).locator('visible=true').filter({ hasText: String(opt) }).last().click({ timeout });
        await page.waitForTimeout(200);
      }
      return;
    }
    case 'check': await loc(page, v).check({ timeout, force: step.force }); return;
    case 'uncheck': await loc(page, v).uncheck({ timeout, force: step.force }); return;
    case 'press': {
      if (typeof v === 'string') await page.keyboard.press(v);
      else await loc(page, v.selector).press(v.key);
      return;
    }
    case 'upload': await loc(page, v.selector).setInputFiles([].concat(v.file).map(f => path.resolve(S.opts.caseDir || '.', f))); return;
    case 'wait': {
      if (typeof v === 'number') { await page.waitForTimeout(v); return; }
      if (typeof v === 'string') { await loc(page, v).waitFor({ state: 'visible', timeout }); return; }
      if (v.selector) { await loc(page, v.selector).waitFor({ state: v.state || 'visible', timeout }); return; }
      if (v.idle) { await page.waitForLoadState('networkidle', { timeout }).catch(() => {}); return; }
      return;
    }
    case 'expectText': case 'expectNoText': {
      const o = typeof v === 'string' ? { text: v } : v;
      const scope = o.selector ? loc(page, o.selector) : page.locator('body');
      const want = kind === 'expectText';
      const deadline = Date.now() + (timeout || 8000);
      let last = '';
      while (true) {
        last = (await scope.innerText({ timeout: 3000 }).catch(() => '')) || '';
        const has = toMatch(last, o.text);
        if (has === want) return;
        if (Date.now() > deadline) break;
        await page.waitForTimeout(200);
      }
      throw new Error(want ? `页面上没找到「${o.text}」` : `页面上不该出现「${o.text}」，但出现了`);
    }
    case 'expectVisible': await loc(page, v).waitFor({ state: 'visible', timeout: timeout || 8000 }).catch(() => { throw new Error(`没看到 ${typeof v === 'string' ? v : v.selector}`); }); return;
    case 'expectHidden': await loc(page, v).waitFor({ state: 'hidden', timeout: timeout || 8000 }).catch(() => { throw new Error(`${typeof v === 'string' ? v : v.selector} 应该消失但还在`); }); return;
    case 'expectUrl': {
      const deadline = Date.now() + (timeout || 8000);
      while (!urlMatches(page.url(), v)) {
        if (Date.now() > deadline) throw new Error(`网址应包含 ${v}，实际 ${page.url()}`);
        await page.waitForTimeout(200);
      }
      return;
    }
    case 'expectCount': {
      const l = page.locator(v.selector).locator('visible=true');
      const exp = Object.fromEntries(Object.entries(v).filter(([k]) => k !== 'selector'));
      const deadline = Date.now() + (timeout || 8000);
      let r;
      while ((r = match(await l.count(), exp, `「${v.selector}」的个数`))) {
        if (Date.now() > deadline) throw new Error(r);
        await page.waitForTimeout(250);
      }
      return;
    }
    case 'expectValue': {
      const actual = await loc(page, v.selector).inputValue();
      const r = match(actual, v.value, `${v.selector} 里的值`); if (r) throw new Error(r); return;
    }
    case 'expectToast': {
      const o = typeof v === 'string' ? { text: v } : v;
      const l = page.locator(TOAST_SEL).filter({ hasText: o.text });
      await l.first().waitFor({ state: 'attached', timeout: timeout || 6000 }).catch(async () => {
        const seen = await page.locator(TOAST_SEL).allInnerTexts().catch(() => []);
        throw new Error(`没出现提示「${o.text}」${seen.length ? '，出现的是：' + seen.join(' / ').slice(0, 120) : ''}`);
      });
      return;
    }
    case 'saveText': { const t = (await loc(page, v.selector).innerText()).trim(); const val = v.regex ? (t.match(new RegExp(v.regex)) || [])[1] ?? t : t; S.vars[v.as] = val; V[v.as] = val; return; }
    case 'js': {
      const out = await page.evaluate(new Function(`return (async () => { ${v.includes('return') ? v : 'return ' + v} })()`));
      if (step.expect !== undefined) { const r = match(out, step.expect, '脚本结果'); if (r) throw new Error(r); }
      if (step.save) { S.vars[step.save] = out; V[step.save] = out; }
      return;
    }
    case 'dialog': S.nextDialog = v; return;
    case 'set': Object.assign(V, v); Object.assign(S.vars, v); return;
    case 'log': return;
    case 'screenshot': return; // 截图在外层统一做
  }
}

function toMatch(text, want) {
  const re = typeof want === 'string' && want.match(/^\/(.+)\/([a-z]*)$/);
  return re ? new RegExp(re[1], re[2]).test(text) : text.includes(String(want));
}

// 跑一串步骤。返回每步的结果；遇到失败就停（cleanup 段除外）。
async function runSteps(S, page, steps, { label = '', vars, shotDir, continueOnFail = false, monitor } = {}) {
  const V = vars || S.vars;
  const results = [];
  let stopped = false;
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const kind = stepKind(step);
    const r = { index: i + 1, kind, title: title(step, kind), status: 'pass', ms: 0 };
    results.push(r);
    if (stopped) { r.status = 'skip'; continue; }
    const t0 = Date.now();
    if (monitor) monitor.take();
    try {
      if (kind === 'api') {
        const res = await S.request({ ...step.api, expect: step.expect || step.api.expect, save: step.save || step.api.save }, { vars: V, label: r.title });
        r.detail = `${res.method} ${res.url} → ${res.status ?? '无响应'}（${res.ms} 毫秒）`;
        r.response = res.bodySnippet;
        if (res.error) throw new Error(res.error);
      } else {
        // 操作后要等的接口：response: {url, method, expect, save}
        let waitResp = null;
        if (step.response) {
          const R = interp(step.response, V);
          waitResp = page.waitForResponse(resp => urlMatches(resp.url(), R.url) && (!R.method || resp.request().method() === R.method.toUpperCase()), { timeout: step.timeout || 15000 })
            .then(resp => ({ resp, R })).catch(e => ({ err: e }));
        }
        await runOne(S, page, step, kind, V);
        if (waitResp) await checkResponse(S, await waitResp, V, r);
        if (kind === 'screenshot' && shotDir) {
          const f = path.join(shotDir, safeName(`${label}-${i + 1}-${step.screenshot}`) + '.png');
          await page.screenshot({ path: f, fullPage: true }); r.shot = f;
        }
      }
      // 这一步里页面冒出的程序报错、接口出错
      if (monitor && !step.allowErrors) {
        await page.waitForTimeout(kind === 'api' ? 0 : 150);
        const evs = monitor.take().filter(e => e.kind === 'pageerror' || (e.kind === 'api' && e.status >= 500) || (e.kind === 'console' && /^(Uncaught\s+)?(TypeError|ReferenceError|SyntaxError|RangeError)\b/.test(e.text)));
        if (evs.length) throw new Error('这一步页面出错：' + evs.map(e => e.text + (e.url ? ' ' + shortUrl(e.url) : '')).join('；'));
      }
    } catch (e) {
      r.status = 'fail';
      r.error = cleanErr(e);
      if (shotDir && kind !== 'api' && page) {
        const f = path.join(shotDir, safeName(`${label}-第${i + 1}步失败`) + '.png');
        await page.screenshot({ path: f, fullPage: false }).catch(() => {}); r.shot = f;
      }
      if (!continueOnFail) stopped = true;
    }
    r.ms = Date.now() - t0;
  }
  return results;
}

async function checkResponse(S, got, V, r) {
  if (got.err) throw new Error(`没等到接口 ${got.R ? got.R.url : ''}（${cleanErr(got.err)}）`);
  const { resp, R } = got;
  const status = resp.status();
  let json; const body = await resp.text().catch(() => '');
  try { json = JSON.parse(body); } catch {}
  r.detail = `${resp.request().method()} ${shortUrl(resp.url())} → ${status}`;
  r.response = body.slice(0, 400);
  const exp = R.expect || {};
  const errs = [];
  if (exp.status !== undefined) { const m = match(status, Array.isArray(exp.status) ? { in: exp.status } : exp.status, '状态码'); if (m) errs.push(m); }
  else if (status >= 400) errs.push(`状态码 ${status}`);
  const ownsCode = exp.json && Object.keys(exp.json).some(k => /(^|\.)code$/.test(k));
  if (exp.business !== false && !ownsCode && status < 400) { const be = S.businessError(json); if (be) errs.push(be); }
  if (exp.json) for (const [p, e] of Object.entries(exp.json)) { const m = match(getPath(json, p), e, p); if (m) errs.push(m); }
  if (errs.length) throw new Error(errs.join('；'));
  if (R.save) for (const [name, p] of Object.entries(R.save)) {
    const val = getPath(json, p);
    if (val === undefined) throw new Error(`要存的 ${name} 没取到（${p}）`);
    V[name] = val; S.vars[name] = val;
  }
}

function shortUrl(u) { try { const x = new URL(u); return x.pathname + (x.search.length > 60 ? x.search.slice(0, 60) + '…' : x.search); } catch { return u; } }
function cleanErr(e) {
  let s = String(e && e.message || e);
  s = s.replace(/\x1b\[[0-9;]*m/g, '');
  const lines = s.split('\n').filter(l => l.trim() && !/^\s*(at |Call log:|- )/.test(l));
  s = lines.slice(0, 2).join(' ');
  s = s.replace(/^(locator|page|elementHandle)\.\w+: /, '');
  s = s.replace(/Timeout (\d+)ms exceeded\.?/, (_, ms) => `等了 ${Math.round(ms / 1000)} 秒没等到`);
  return s.slice(0, 400);
}

module.exports = { runSteps, loc, shortUrl, cleanErr, TOAST_SEL };
