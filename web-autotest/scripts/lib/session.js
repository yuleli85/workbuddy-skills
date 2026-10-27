'use strict';
// 浏览器、登录、接口请求、页面监控（报错、失败请求、业务错误码）。

const fs = require('fs');
const path = require('path');
const { interp, getPath, match, urlMatches, normalizeApiPath } = require('./util');

// 各组件库的错误提示框
const ERROR_SELECTORS = '.el-message--error, .el-notification--error, .ant-message-error, .ant-notification-notice-error, .arco-message-error, .n-message--error-type, .ivu-message-error, .van-toast--fail';

function loadPlaywright() {
  try { return require('playwright'); } catch {
    try { return require('playwright-core'); } catch {
      throw new Error('没装 playwright：在本技能目录跑 npm install，再跑 npx playwright install chromium');
    }
  }
}

class Session {
  constructor(cfg, opts = {}) {
    this.cfg = cfg;
    this.opts = opts;
    this.vars = { ...(cfg.vars || {}) };
    this.apiInventory = new Map(); // 「方法 路径」→ 汇总
    this.business = cfg.api && cfg.api.business; // 业务错误码规则
  }

  abs(u, base) {
    if (/^https?:\/\//.test(u)) return u;
    const b = (base || this.cfg.baseUrl).replace(/\/$/, '');
    return b + (u.startsWith('/') ? u : '/' + u);
  }

  get apiBase() { return (this.cfg.api && this.cfg.api.base) || this.cfg.apiBase || this.cfg.baseUrl; }

  async start() {
    const pw = loadPlaywright();
    const b = this.cfg.browser || {};
    const launch = { headless: this.opts.headed ? false : b.headless !== false };
    const exe = process.env.AUTOTEST_CHROME || b.executablePath;
    if (exe) launch.executablePath = exe;
    if (b.channel) launch.channel = b.channel; // 用本机装的 Chrome：channel: chrome
    if (b.args) launch.args = b.args;
    this.browser = await pw.chromium.launch(launch);
    const [w, h] = b.viewport || [1440, 900];
    this.contextOpts = { viewport: { width: w, height: h }, ignoreHTTPSErrors: true, locale: b.locale || 'zh-CN' };
    this.context = await this.browser.newContext(this.contextOpts);
    this.context.setDefaultTimeout(b.timeout || 15000);
    // 错误提示常两三秒就消失，一出现就记下来
    const errSel = (this.cfg.menus && this.cfg.menus.errorSelectors) || ERROR_SELECTORS;
    await this.context.addInitScript(sel => {
      window.__autotestToasts = [];
      const grab = el => setTimeout(() => { const t = (el.innerText || '').trim(); if (t) window.__autotestToasts.push(t); }, 80);
      new MutationObserver(ms => {
        for (const m of ms) for (const n of m.addedNodes) {
          if (n.nodeType !== 1) continue;
          if (n.matches(sel)) grab(n);
          n.querySelectorAll && n.querySelectorAll(sel).forEach(grab);
        }
      }).observe(document, { childList: true, subtree: true });
    }, errSel);
    await this.login();
  }

  async stop() { if (this.browser) await this.browser.close().catch(() => {}); }

  // ---------- 登录 ----------
  async login() {
    const L = this.cfg.login;
    if (!L) return;
    if (L.api) {
      const r = await this.request(L.api, { label: '登录接口' });
      if (r.error) throw new Error('登录接口没通过：' + r.error);
    }
    if (L.cookies) await this.context.addCookies(interp(L.cookies, this.vars).map(c => ({ url: this.cfg.baseUrl, ...c })));
    const ls = L.localStorage ? interp(L.localStorage, this.vars) : null;
    const ss = L.sessionStorage ? interp(L.sessionStorage, this.vars) : null;
    if (ls || ss) {
      const origin = new URL(this.cfg.baseUrl).origin;
      await this.context.addInitScript(({ ls, ss, origin }) => {
        if (location.origin !== origin) return;
        const put = (store, obj) => {
          if (!obj) return;
          for (const [k, v] of Object.entries(obj)) {
            if (!store.getItem(k)) store.setItem(k, typeof v === 'string' ? v : JSON.stringify(v));
          }
        };
        put(localStorage, ls); put(sessionStorage, ss);
      }, { ls, ss, origin });
    }
    if (L.steps) {
      const { runSteps } = require('./steps');
      const page = await this.newPage();
      const res = await runSteps(this, page, L.steps, { label: '登录' });
      const failed = res.find(s => s.status === 'fail');
      if (failed) {
        const shot = path.join(this.opts.reportDir, 'shots', '登录失败.png');
        await page.screenshot({ path: shot }).catch(() => {});
        const tips = await page.evaluate(() => (window.__autotestToasts || []).join(' / ')).catch(() => '');
        throw new Error(`页面登录没通过（第 ${failed.index} 步「${failed.title}」）：${failed.error}${tips ? `；页面提示「${tips}」` : ''}`);
      }
      // 会话存储（sessionStorage）不随新页面带过去，抄一份到之后每个新页面
      if (L.keepSessionStorage !== false) {
        const dump = await page.evaluate(() => JSON.stringify(Object.assign({}, sessionStorage))).catch(() => '{}');
        const origin = new URL(this.cfg.baseUrl).origin;
        await this.context.addInitScript(({ dump, origin }) => {
          if (location.origin !== origin || sessionStorage.length) return;
          const o = JSON.parse(dump);
          for (const k of Object.keys(o)) sessionStorage.setItem(k, o[k]);
        }, { dump, origin });
      }
      await page.close();
    }
  }

  async newPage() {
    const page = await this.context.newPage();
    page.on('dialog', d => (this.nextDialog === 'dismiss' ? d.dismiss() : d.accept()).catch(() => {}));
    return page;
  }

  // ---------- 业务错误码 ----------
  // 很多后端出错也回 200，要看返回里的 code。规则写在 api.business。
  businessError(json) {
    const B = this.business;
    if (!B || json == null || typeof json !== 'object') return null;
    const code = getPath(json, B.path || '$.code');
    if (code === undefined) return null;
    const ok = (B.ok || [0, 200]).map(String);
    if (ok.includes(String(code))) return null;
    const msg = B.msgPath ? getPath(json, B.msgPath) : (json.msg ?? json.message);
    return `业务错误码 ${code}${msg ? '：' + String(msg).slice(0, 120) : ''}`;
  }

  // ---------- 接口请求 ----------
  // spec: {method,url,query,json,form,multipart,headers,expect,save,timeout}
  async request(rawSpec, { label = '', vars } = {}) {
    const V = vars || this.vars;
    const spec = interp(rawSpec, V);
    const method = (spec.method || 'GET').toUpperCase();
    const url = this.abs(spec.url, this.apiBase);
    const headers = { ...(this.cfg.api && this.cfg.api.headers ? safeInterp(this.cfg.api.headers, V) : {}), ...(spec.headers || {}) };
    const opt = { method, headers, timeout: spec.timeout || 20000, failOnStatusCode: false, ignoreHTTPSErrors: true };
    if (spec.query) opt.params = spec.query;
    if (spec.json !== undefined) opt.data = spec.json;
    if (spec.form) opt.form = spec.form;
    if (spec.multipart) {
      opt.multipart = {};
      for (const [k, v] of Object.entries(spec.multipart)) {
        opt.multipart[k] = (v && v.file) ? { name: path.basename(v.file), mimeType: v.mimeType || 'application/octet-stream', buffer: fs.readFileSync(v.file) } : v;
      }
    }
    const t0 = Date.now();
    let resp, body, json, err = null;
    try {
      resp = await this.context.request.fetch(url, opt);
      body = await resp.text();
      try { json = JSON.parse(body); } catch { json = undefined; }
    } catch (e) {
      return { method, url, ms: Date.now() - t0, error: '请求发不出去：' + String(e.message).split('\n')[0] };
    }
    const ms = Date.now() - t0;
    const status = resp.status();
    const exp = spec.expect || {};
    const errs = [];
    // 状态码
    if (exp.status !== undefined) {
      const e = Array.isArray(exp.status) ? { in: exp.status } : exp.status;
      const r = match(status, e, '状态码'); if (r) errs.push(r);
    } else if (status >= 400) errs.push(`状态码 ${status}`);
    // 业务码：用例自己写了 business: false 或写了 $.code 判断时不再自动查
    const ownsCode = exp.json && Object.keys(exp.json).some(k => /(^|\.)code$/.test(k));
    if (exp.business !== false && !ownsCode && json !== undefined && status < 400) {
      const be = this.businessError(json); if (be) errs.push(be);
    }
    if (exp.json) {
      if (json === undefined) errs.push('返回的不是 JSON：' + String(body).slice(0, 80));
      else for (const [p, e] of Object.entries(exp.json)) { const r = match(getPath(json, p), e, p); if (r) errs.push(r); }
    }
    if (exp.body) { const r = match(body, exp.body, '返回内容'); if (r) errs.push(r); }
    if (exp.headers) for (const [h, e] of Object.entries(exp.headers)) { const r = match(resp.headers()[h.toLowerCase()], e, '响应头 ' + h); if (r) errs.push(r); }
    if (exp.time !== undefined) { const r = match(ms, typeof exp.time === 'number' ? { lte: exp.time } : exp.time, '耗时毫秒'); if (r) errs.push(r); }
    if (errs.length) err = errs.join('；');
    // 存变量
    if (spec.save && !err) {
      for (const [name, p] of Object.entries(spec.save)) {
        const v = p === 'status' ? status : p === 'body' ? body : getPath(json, p);
        if (v === undefined) { err = `要存的 ${name} 没取到（${p}）`; break; }
        this.vars[name] = v; if (vars) vars[name] = v;
      }
    }
    return { method, url, status, ms, json, bodySnippet: String(body).slice(0, 400), error: err, label };
  }

  // ---------- 页面监控 ----------
  // 挂在页面上，记下报错、失败请求和接口调用，按「段」取出（每点一个菜单一段）
  monitor(page, where) {
    const M = { events: [], inflight: 0, lastActivity: Date.now(), where };
    const C = this.cfg.checks || {};
    const ignoreReq = (C.ignoreRequests || []).concat(['hot-update', '/sockjs-node', '/__vite_ping', 'favicon.ico']);
    const ignoreCon = C.ignoreConsole || [];
    const apiMark = (this.cfg.api && this.cfg.api.match) || null; // 哪些请求算接口，默认 xhr/fetch
    const push = e => M.events.push({ ...e, at: Date.now(), where: M.where });
    page.on('pageerror', e => push({ kind: 'pageerror', text: String(e.message || e).split('\n')[0].slice(0, 300) }));
    page.on('console', m => {
      if (m.type() !== 'error') return;
      const t = m.text();
      if (ignoreCon.some(p => urlMatches(t, p))) return;
      if (/^Failed to load resource/.test(t)) return; // 失败的请求另有记录，这里不重复
      push({ kind: 'console', text: t.slice(0, 300) });
    });
    const starts = new WeakMap();
    page.on('request', r => {
      if (['xhr', 'fetch', 'document', 'script', 'stylesheet'].includes(r.resourceType())) {
        M.inflight++; starts.set(r, Date.now()); M.lastActivity = Date.now();
      }
    });
    const done = r => { if (starts.has(r)) { M.inflight = Math.max(0, M.inflight - 1); M.lastActivity = Date.now(); } };
    page.on('requestfailed', r => {
      done(r);
      const u = r.url(); if (ignoreReq.some(p => urlMatches(u, p))) return;
      const f = r.failure(); const why = f ? f.errorText : '';
      if (/ERR_ABORTED/.test(why)) return; // 换页时取消的请求不算错
      push({ kind: 'reqfail', url: u, method: r.method(), type: r.resourceType(), text: `请求失败（${why}）` });
    });
    page.on('response', async resp => {
      const r = resp.request();
      const t0 = starts.get(r); done(r);
      const u = resp.url(); if (ignoreReq.some(p => urlMatches(u, p))) return;
      const type = r.resourceType();
      const isApi = apiMark ? [].concat(apiMark).some(p => urlMatches(u, p)) : (type === 'xhr' || type === 'fetch');
      const status = resp.status();
      const ms = t0 ? Date.now() - t0 : null;
      if (!isApi) {
        if (status >= 400 && ['document', 'script', 'stylesheet'].includes(type)) push({ kind: 'resource', url: u, status, type, text: `资源加载失败 ${status}` });
        return;
      }
      let be = null, snippet = '';
      try {
        const ct = resp.headers()['content-type'] || '';
        if (/json/.test(ct) || status >= 400) {
          const txt = await resp.text(); snippet = txt.slice(0, 300);
          try { be = this.businessError(JSON.parse(txt)); } catch {}
        }
      } catch {}
      const ev = { kind: 'api', url: u, method: r.method(), status, ms, text: '' };
      if (status >= 400) ev.text = `接口返回 ${status}`;
      else if (be) ev.text = be;
      ev.bad = Boolean(ev.text);
      push(ev);
      this.recordApi(ev, snippet);
    });
    M.take = () => { const e = M.events; M.events = []; return e; };
    // 等页面安静：没有进行中的请求，且安静了 quietMs
    M.settle = async (maxMs = 15000, quietMs = 600) => {
      const t0 = Date.now();
      M.lastActivity = Math.max(M.lastActivity, t0); // 至少等 quietMs，免得请求还没发出就算「安静」了
      while (Date.now() - t0 < maxMs) {
        if (M.inflight === 0 && Date.now() - M.lastActivity >= quietMs) return Date.now() - t0;
        await page.waitForTimeout(100);
      }
      return -1;
    };
    return M;
  }

  recordApi(ev, snippet) {
    const key = `${ev.method} ${normalizeApiPath(ev.url)}`;
    let a = this.apiInventory.get(key);
    if (!a) { a = { key, method: ev.method, path: normalizeApiPath(ev.url), count: 0, statuses: {}, bad: 0, maxMs: 0, problems: [], pages: [], sample: snippet, exampleUrl: ev.url }; this.apiInventory.set(key, a); }
    a.count++;
    a.statuses[ev.status] = (a.statuses[ev.status] || 0) + 1;
    if (ev.ms && ev.ms > a.maxMs) a.maxMs = ev.ms;
    if (ev.bad) { a.bad++; if (!a.problems.includes(ev.text) && a.problems.length < 5) a.problems.push(ev.text); }
    if (ev.where && !a.pages.includes(ev.where) && a.pages.length < 8) a.pages.push(ev.where);
  }
}

// 接口公共请求头里引用的变量（比如登录后才有的 token）还没值时先跳过这个头
function safeInterp(headers, vars) {
  const out = {};
  for (const [k, v] of Object.entries(headers)) { try { out[k] = String(interp(v, vars)); } catch {} }
  return out;
}

module.exports = { Session, ERROR_SELECTORS };
