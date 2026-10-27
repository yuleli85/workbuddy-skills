'use strict';
// 功能用例：一个用例是一串步骤（页面操作 + 接口调用 + 判断），失败就停，最后总要跑清理步骤。

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { runSteps } = require('./steps');

function expandGlobs(baseDir, patterns) {
  const out = [];
  for (const pat of [].concat(patterns || [])) {
    const abs = path.isAbsolute(pat) ? pat : path.join(baseDir, pat);
    if (!/[*?]/.test(abs)) { if (fs.existsSync(abs)) out.push(...(fs.statSync(abs).isDirectory() ? listCases(abs) : [abs])); continue; }
    const dir = path.dirname(abs);
    const re = new RegExp('^' + path.basename(abs).replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$');
    if (fs.existsSync(dir)) out.push(...fs.readdirSync(dir).filter(f => re.test(f)).sort().map(f => path.join(dir, f)));
  }
  return [...new Set(out)];
}
function listCases(dir) { return fs.readdirSync(dir).filter(f => /\.(ya?ml|json)$/.test(f)).sort().map(f => path.join(dir, f)); }

function loadCases(file) {
  const txt = fs.readFileSync(file, 'utf8');
  const doc = /\.json$/.test(file) ? JSON.parse(txt) : yaml.load(txt);
  const list = Array.isArray(doc) ? doc : doc.cases ? doc.cases.map(c => ({ ...c, tags: [...(doc.tags || []), ...(c.tags || [])] })) : [doc];
  return list.map((c, i) => ({ ...c, name: c.name || `${path.basename(file)} 第 ${i + 1} 个`, file }));
}

// 一行数据的简称：有 name 用 name，否则把各列值连起来
function rowLabel(row) {
  if (row.name) return String(row.name);
  return Object.values(row).map(v => typeof v === 'object' ? JSON.stringify(v) : String(v)).join('，').slice(0, 50);
}

async function runFlows(S, files, kind) {
  const shotDir = path.join(S.opts.reportDir, 'shots');
  const results = [];
  for (const file of files) {
    let cases;
    try { cases = loadCases(file); } catch (e) {
      results.push({ name: path.basename(file), file, status: 'fail', steps: [], error: '用例文件读不了：' + String(e.message).split('\n')[0] });
      continue;
    }
    for (const c of cases) {
      if (S.opts.grep && !c.name.includes(S.opts.grep) && !(c.tags || []).includes(S.opts.grep)) continue;
      if (c.skip) { results.push({ name: c.name, file, status: 'skip', steps: [], error: typeof c.skip === 'string' ? c.skip : '标了跳过' }); continue; }
      const rows = c.each ? c.each : [null];
      for (const row of rows) {
        const name = row ? `${c.name}（${rowLabel(row)}）` : c.name;
        const V = { ...S.vars, ...(c.vars || {}), ...(row || {}) };
        const needsPage = [...(c.steps || []), ...(c.cleanup || [])].some(s => !('api' in s) && !('set' in s) && !('log' in s));
        const page = needsPage ? await S.newPage() : null;
        const mon = page ? S.monitor(page, name) : null;
        const t0 = Date.now();
        S.opts.caseDir = path.dirname(file);
        const steps = await runSteps(S, page, c.steps || [], { label: name, vars: V, shotDir, monitor: mon });
        let cleanup = [];
        if (c.cleanup) cleanup = await runSteps(S, page, c.cleanup, { label: name + '-清理', vars: V, shotDir, continueOnFail: true });
        const failed = steps.find(s => s.status === 'fail');
        const cleanFail = cleanup.find(s => s.status === 'fail');
        const r = { name, file: path.relative(S.opts.configDir, file), kind, tags: c.tags || [], desc: c.desc || '', status: failed ? 'fail' : cleanFail ? 'warn' : 'pass', ms: Date.now() - t0, steps, cleanup };
        if (failed) r.error = `第 ${failed.index} 步「${failed.title}」：${failed.error}`;
        else if (cleanFail) r.error = `清理没做干净：${cleanFail.title}：${cleanFail.error}`;
        results.push(r);
        if (page) await page.close().catch(() => {});
        console.log(`  [${{ pass: '通过', warn: '注意', fail: '有问题' }[r.status]}] ${name}${r.error ? '：' + r.error.slice(0, 160) : ''}`);
      }
    }
  }
  return results;
}

module.exports = { runFlows, expandGlobs };
