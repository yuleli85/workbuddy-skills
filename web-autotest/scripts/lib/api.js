'use strict';
// 接口检查：① 按接口文档（OpenAPI / Swagger）把查询类接口逐个调一遍；② 跑写好的接口用例。

const fs = require('fs');
const { interp, urlMatches } = require('./util');

async function loadSpec(S, src) {
  if (!fs.existsSync(src)) {
    const resp = await S.context.request.get(S.abs(src, S.apiBase), { headers: safeHeaders(S), failOnStatusCode: false, ignoreHTTPSErrors: true });
    const txt = await resp.text();
    if (resp.status() >= 400) throw new Error(`接口文档取不到：状态码 ${resp.status()}`);
    try { return JSON.parse(txt); } catch { return require('js-yaml').load(txt); }
  }
  const txt = fs.readFileSync(src, 'utf8');
  return /\.ya?ml$/.test(src) ? require('js-yaml').load(txt) : JSON.parse(txt);
}
function safeHeaders(S) { const o = {}; for (const [k, v] of Object.entries((S.cfg.api && S.cfg.api.headers) || {})) { try { o[k] = String(interp(v, S.vars)); } catch {} } return o; }

function exampleOf(p) {
  const s = p.schema || {};
  if (p.example !== undefined) return p.example;
  if (s.example !== undefined) return s.example;
  if (s.default !== undefined) return s.default;
  if (s.enum && s.enum.length) return s.enum[0];
  return undefined;
}

// 一个接口文档里的接口 → 能直接调的请求；缺必填参数的跳过并说明
function buildRequests(spec, O) {
  const methods = (O.methods || ['GET']).map(m => m.toUpperCase());
  const params = O.params || {};
  const basePath = O.basePath ?? (spec.basePath || (spec.servers && spec.servers[0] && new URL(spec.servers[0].url, 'http://x').pathname) || '');
  const out = [];
  for (const [p, ops] of Object.entries(spec.paths || {})) {
    for (const [m, op] of Object.entries(ops)) {
      const M = m.toUpperCase();
      if (!['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].includes(M)) continue;
      const full = (basePath.replace(/\/$/, '') + p);
      const item = { key: `${M} ${full}`, method: M, path: full, summary: op.summary || op.description || '', tag: (op.tags || [])[0] || '' };
      if (!methods.includes(M)) continue;
      if ((O.exclude || []).some(e => urlMatches(item.key, e))) continue;
      if (O.include && !O.include.some(e => urlMatches(item.key, e))) continue;
      const all = [...(ops.parameters || []), ...(op.parameters || [])];
      let url = full, missing = [];
      const query = {};
      for (const prm of all) {
        const v = params[`${M} ${full}`]?.[prm.name] ?? params[prm.name] ?? exampleOf(prm);
        if (prm.in === 'path') { if (v === undefined) missing.push(prm.name); else url = url.replace(`{${prm.name}}`, encodeURIComponent(v)); }
        else if (prm.in === 'query') { if (v !== undefined) query[prm.name] = v; else if (prm.required) missing.push(prm.name); }
      }
      // 分页参数后端常要求必填，给个默认
      for (const [k, v] of Object.entries(O.defaultQuery || { current: 1, size: 10, page: 1, pageNum: 1, pageSize: 10 })) {
        if (all.some(x => x.name === k && x.in === 'query') && query[k] === undefined) query[k] = v;
      }
      item.request = { method: M, url, query };
      const body = O.bodies && O.bodies[item.key];
      if (body) item.request.json = body;
      else if (M !== 'GET' && M !== 'DELETE' && (op.requestBody || all.some(x => x.in === 'body'))) missing.push('请求体');
      if (missing.length) item.skip = `缺参数 ${missing.join('、')}（在 api.openapi.params 里给值就会测）`;
      out.push(item);
    }
  }
  return out;
}

async function runOpenapi(S) {
  const O = S.cfg.api.openapi;
  const conf = typeof O === 'string' ? { url: O } : O;
  const spec = await loadSpec(S, conf.url || conf.file);
  const reqs = buildRequests(spec, conf);
  console.log(`  接口文档里可测的 ${reqs.length} 个（只测 ${(conf.methods || ['GET']).join('、')}）`);
  const results = [];
  for (const it of reqs) {
    const r = { key: it.key, summary: it.summary, tag: it.tag, status: 'pass' };
    results.push(r);
    if (it.skip) { r.status = 'skip'; r.problem = it.skip; continue; }
    const res = await S.request({ ...it.request, expect: { ...(conf.expect || {}) } });
    r.http = res.status; r.ms = res.ms; r.url = res.url; r.sample = res.bodySnippet;
    if (res.error) { r.status = 'fail'; r.problem = res.error; }
    else if (res.ms > (conf.slowMs || 3000)) { r.status = 'warn'; r.problem = `慢：${res.ms} 毫秒`; }
    console.log(`  [${{ pass: '通过', warn: '注意', fail: '有问题', skip: '跳过' }[r.status]}] ${it.key}${r.problem ? '：' + r.problem.slice(0, 120) : ''}`);
  }
  return results;
}

module.exports = { runOpenapi, buildRequests };
