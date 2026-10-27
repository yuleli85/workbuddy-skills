'use strict';
// 变量替换、JSON 路径取值、断言匹配：接口检查和功能用例共用。

const fs = require('fs');
const path = require('path');

function pad(n, w = 2) { return String(n).padStart(w, '0'); }

function builtinVars() {
  const d = new Date();
  return {
    now: String(Date.now()),
    date: `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`,
    time: `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`,
    rand: String(Math.floor(100000 + Math.random() * 900000)),
  };
}

// 取变量：支持 env.X、a.b.c
function lookup(vars, name) {
  name = name.trim();
  if (name.startsWith('env.')) return process.env[name.slice(4)];
  if (name in vars) return vars[name];
  if (name in builtinVars()) return builtinVars()[name];
  let cur = vars;
  for (const k of name.split('.')) {
    if (cur == null || typeof cur !== 'object') return undefined;
    cur = cur[k];
  }
  return cur;
}

// 把 ${x} 换成变量值。整串就是一个 ${x} 时保留原类型（数字、对象）。
function interp(value, vars) {
  if (typeof value === 'string') {
    const whole = value.match(/^\$\{([^}]+)\}$/);
    if (whole) {
      const v = lookup(vars, whole[1]);
      if (v === undefined) throw new Error(`变量没有值：${whole[1]}`);
      return v;
    }
    return value.replace(/\$\{([^}]+)\}/g, (_, k) => {
      const v = lookup(vars, k);
      if (v === undefined) throw new Error(`变量没有值：${k}`);
      return typeof v === 'object' ? JSON.stringify(v) : String(v);
    });
  }
  if (Array.isArray(value)) return value.map(v => interp(v, vars));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[interp(k, vars)] = interp(v, vars);
    return out;
  }
  return value;
}

// 简版 JSON 路径：$.a.b[0].c、$.list[*].name、$.list.length、$['带点的键']
function parsePath(p) {
  if (typeof p !== 'string') throw new Error(`路径要写成字符串：${p}`);
  let s = p.trim();
  if (s === '$') return [];
  if (s.startsWith('$')) s = s.slice(1);
  const tokens = [];
  const re = /\.([^.[\]]+)|\[(\d+|\*|-\d+)\]|\[['"]([^'"]+)['"]\]/y;
  let m;
  re.lastIndex = 0;
  while (re.lastIndex < s.length) {
    const start = re.lastIndex;
    m = re.exec(s);
    if (!m) {
      // 允许不带 $ 和点的写法：data.list
      if (start === 0 && !s.startsWith('.') && !s.startsWith('[')) { s = '.' + s; re.lastIndex = 0; continue; }
      throw new Error(`路径写法不对：${p}`);
    }
    if (m[1] !== undefined) tokens.push(m[1] === '*' ? '*' : m[1]);
    else if (m[2] !== undefined) tokens.push(m[2] === '*' ? '*' : Number(m[2]));
    else tokens.push(m[3]);
  }
  return tokens;
}

function getPath(obj, p) {
  const tokens = parsePath(p);
  let cur = [obj];
  let multi = false;
  for (const t of tokens) {
    const next = [];
    for (const c of cur) {
      if (c == null) continue;
      if (t === '*') {
        multi = true;
        if (Array.isArray(c)) next.push(...c);
        else if (typeof c === 'object') next.push(...Object.values(c));
      } else if (t === 'length' && (Array.isArray(c) || typeof c === 'string')) {
        next.push(c.length);
      } else if (typeof t === 'number' && Array.isArray(c)) {
        next.push(c[t < 0 ? c.length + t : t]);
      } else if (typeof c === 'object' && t in c) {
        next.push(c[t]);
      } else {
        next.push(undefined);
      }
    }
    cur = next;
  }
  return multi ? cur.filter(v => v !== undefined) : cur[0];
}

const OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'notContains', 'matches', 'exists',
  'type', 'len', 'lenGte', 'lenLte', 'in', 'notIn', 'every', 'some', 'none', 'sorted', 'empty', 'notEmpty', 'not'];

function isMatcher(exp) {
  return exp && typeof exp === 'object' && !Array.isArray(exp) &&
    Object.keys(exp).length > 0 && Object.keys(exp).every(k => OPS.includes(k));
}

function show(v) {
  if (v === undefined) return '（没有这个字段）';
  const s = typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v);
  return s && s.length > 160 ? s.slice(0, 160) + '…' : s;
}

function deepEqual(a, b) {
  if (a === b) return true;
  // 数字和数字字符串视为相等，后端常把 id 回成字符串
  if ((typeof a === 'number' && typeof b === 'string') || (typeof a === 'string' && typeof b === 'number')) {
    return String(a) === String(b);
  }
  if (typeof a !== typeof b || a == null || b == null || typeof a !== 'object') return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a), kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every(k => deepEqual(a[k], b[k]));
}

function typeOf(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  return typeof v;
}

// 返回 null 表示通过，否则返回一句中文原因
function match(actual, exp, label = '值') {
  if (!isMatcher(exp)) {
    return deepEqual(actual, exp) ? null : `${label} 应为 ${show(exp)}，实际 ${show(actual)}`;
  }
  for (const [op, e] of Object.entries(exp)) {
    let ok = true, why = '';
    const num = Number(actual);
    switch (op) {
      case 'eq': ok = deepEqual(actual, e); why = `应为 ${show(e)}`; break;
      case 'ne': ok = !deepEqual(actual, e); why = `不应为 ${show(e)}`; break;
      case 'gt': ok = actual != null && num > e; why = `应大于 ${e}`; break;
      case 'gte': ok = actual != null && num >= e; why = `应不小于 ${e}`; break;
      case 'lt': ok = actual != null && num < e; why = `应小于 ${e}`; break;
      case 'lte': ok = actual != null && num <= e; why = `应不大于 ${e}`; break;
      case 'contains':
        ok = Array.isArray(actual) ? actual.some(x => deepEqual(x, e)) : String(actual ?? '').includes(String(e));
        why = `应包含 ${show(e)}`; break;
      case 'notContains':
        ok = Array.isArray(actual) ? !actual.some(x => deepEqual(x, e)) : !String(actual ?? '').includes(String(e));
        why = `不应包含 ${show(e)}`; break;
      case 'matches': ok = new RegExp(e).test(String(actual ?? '')); why = `应符合 ${e}`; break;
      case 'exists': ok = (actual !== undefined && actual !== null) === Boolean(e); why = e ? '应存在' : '不应存在'; break;
      case 'type': ok = typeOf(actual) === e; why = `类型应为 ${e}`; break;
      case 'len': ok = actual != null && actual.length === e; why = `长度应为 ${e}`; break;
      case 'lenGte': ok = actual != null && actual.length >= e; why = `长度应不小于 ${e}`; break;
      case 'lenLte': ok = actual != null && actual.length <= e; why = `长度应不大于 ${e}`; break;
      case 'empty': ok = (actual == null || actual.length === 0 || (typeof actual === 'object' && Object.keys(actual).length === 0)) === Boolean(e); why = e ? '应为空' : '不应为空'; break;
      case 'notEmpty': return match(actual, { empty: !e }, label);
      case 'in': ok = e.some(x => deepEqual(actual, x)); why = `应是 ${show(e)} 之一`; break;
      case 'notIn': ok = !e.some(x => deepEqual(actual, x)); why = `不应是 ${show(e)} 之一`; break;
      case 'not': { const r = match(actual, e, label); ok = r !== null; why = `不应满足 ${show(e)}`; break; }
      case 'every': case 'some': case 'none': {
        if (!Array.isArray(actual)) { ok = false; why = '应是列表'; break; }
        const fails = actual.map((x, i) => [i, matchItem(x, e)]).filter(([, r]) => r);
        if (op === 'every' && fails.length) {
          const [i, r] = fails[0];
          return `${label} 第 ${i + 1} 条不符合（共 ${actual.length} 条，${fails.length} 条不符合）：${r}`;
        }
        if (op === 'some') { ok = actual.length > 0 && fails.length < actual.length; why = `应至少有一条满足 ${show(e)}`; }
        if (op === 'none') { ok = fails.length === actual.length; why = `不应有任何一条满足 ${show(e)}`; }
        break;
      }
      case 'sorted': {
        if (!Array.isArray(actual)) { ok = false; why = '应是列表'; break; }
        const cmp = (a, b) => (typeof a === 'number' && typeof b === 'number') ? a - b : String(a).localeCompare(String(b));
        for (let i = 1; i < actual.length && ok; i++) {
          const c = cmp(actual[i - 1], actual[i]);
          if (e === 'desc' ? c < 0 : c > 0) ok = false;
        }
        why = e === 'desc' ? '应从大到小排列' : '应从小到大排列'; break;
      }
      default: ok = false; why = `不认识的判断写法 ${op}`;
    }
    if (!ok) return `${label} ${why}，实际 ${show(actual)}`;
  }
  return null;
}

// 列表里每一项的判断：对象形式时按「字段: 期望」逐个比
function matchItem(item, exp) {
  if (exp && typeof exp === 'object' && !Array.isArray(exp) && !isMatcher(exp)) {
    for (const [p, e] of Object.entries(exp)) {
      const r = match(getPath(item, p), e, p);
      if (r) return r;
    }
    return null;
  }
  return match(item, exp, '这一项');
}

function ensureDir(d) { fs.mkdirSync(d, { recursive: true }); return d; }

function safeName(s) { return String(s).replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 80); }

function toRegex(pat) {
  if (pat instanceof RegExp) return pat;
  const m = String(pat).match(/^\/(.+)\/([gimsuy]*)$/);
  return m ? new RegExp(m[1], m[2]) : null;
}

// 字符串含有就算匹配；写成 /正则/ 按正则
function urlMatches(url, pat) {
  const re = toRegex(pat);
  return re ? re.test(url) : url.includes(String(pat));
}

// 把 /api/user/123/detail 归成 /api/user/{id}/detail，方便汇总接口清单
function normalizeApiPath(u) {
  let p;
  try { p = new URL(u).pathname; } catch { p = String(u).split('?')[0]; }
  return p.split('/').map(seg => {
    if (/^\d+$/.test(seg)) return '{id}';
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(seg)) return '{id}';
    if (/^[0-9a-f]{16,}$/i.test(seg)) return '{id}';
    return seg;
  }).join('/');
}

function resolvePath(base, p) { return path.isAbsolute(p) ? p : path.join(base, p); }

module.exports = { interp, lookup, getPath, match, matchItem, isMatcher, ensureDir, safeName, urlMatches, normalizeApiPath, resolvePath, builtinVars, show };
