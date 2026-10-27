#!/usr/bin/env node
'use strict';
// 网页系统自动化测试入口
//   node autotest.js run  测试配置.yaml [--only menus,api,flows] [--grep 关键字] [--headed] [--out 报告目录]
//   node autotest.js init 目录          生成一套配置和用例模板
//   node autotest.js check 测试配置.yaml   只检查配置和用例写法，不打开浏览器

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { Session } = require('./lib/session');
const { runMenus } = require('./lib/menus');
const { runOpenapi } = require('./lib/api');
const { runFlows, expandGlobs } = require('./lib/flows');
const { writeReport } = require('./lib/report');
const { ensureDir } = require('./lib/util');

function args() {
  const a = process.argv.slice(2);
  const o = { cmd: a[0], file: a[1] };
  for (let i = 2; i < a.length; i++) {
    if (a[i] === '--only') o.only = a[++i].split(',');
    else if (a[i] === '--grep') o.grep = a[++i];
    else if (a[i] === '--headed') o.headed = true;
    else if (a[i] === '--out') o.out = a[++i];
    else if (a[i] === '--base') o.base = a[++i];
  }
  return o;
}

function loadConfig(file) {
  if (!file || !fs.existsSync(file)) throw new Error(`找不到测试配置：${file || '（没给）'}`);
  const cfg = yaml.load(fs.readFileSync(file, 'utf8'));
  if (!cfg || !cfg.baseUrl) throw new Error('测试配置里要写 baseUrl（被测系统的地址）');
  return cfg;
}

async function run(o) {
  const cfgFile = path.resolve(o.file);
  const configDir = path.dirname(cfgFile);
  const cfg = loadConfig(cfgFile);
  if (o.base) cfg.baseUrl = o.base;
  if (process.env.AUTOTEST_BASE_URL) cfg.baseUrl = process.env.AUTOTEST_BASE_URL;
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
  const reportDir = path.resolve(o.out || path.join(configDir, (cfg.report && cfg.report.dir) || 'autotest-report', stamp));
  ensureDir(path.join(reportDir, 'shots'));
  const only = o.only || ['menus', 'api', 'flows'];
  const R = { name: cfg.name || '被测系统', baseUrl: cfg.baseUrl, startedAt: new Date().toLocaleString('zh-CN', { hour12: false }), ms: 0 };
  const t0 = Date.now();
  const S = new Session(cfg, { ...o, reportDir, configDir });
  try {
    console.log(`被测系统：${R.name}（${cfg.baseUrl}）`);
    await S.start();
    if (cfg.login) console.log('登录：通过');
    if (only.includes('menus') && cfg.menus !== false) {
      console.log('一、菜单巡检');
      R.menus = await runMenus(S);
    }
    if (only.includes('api') && cfg.api && cfg.api.openapi) {
      console.log('二、按接口文档逐个调');
      try { R.openapi = await runOpenapi(S); } catch (e) { console.log('  ' + e.message); R.openapi = [{ key: '接口文档', status: 'fail', problem: e.message }]; }
    }
    if (only.includes('api') && cfg.api && cfg.api.cases) {
      console.log('三、接口用例');
      R.apiCases = await runFlows(S, expandGlobs(configDir, cfg.api.cases), 'api');
    }
    if (only.includes('flows') && cfg.flows) {
      console.log('四、功能用例');
      R.flows = await runFlows(S, expandGlobs(configDir, cfg.flows), 'flow');
    }
  } catch (e) {
    R.fatal = String(e.message || e).split('\n')[0];
    console.log('没跑完：' + R.fatal);
  } finally {
    R.apis = [...S.apiInventory.values()].sort((a, b) => (b.bad > 0) - (a.bad > 0) || a.key.localeCompare(b.key));
    if (!R.apis.length) delete R.apis;
    await S.stop();
  }
  R.ms = Date.now() - t0;
  const sum = writeReport(R, reportDir);
  console.log('\n结果：');
  const line = (n, c) => c && console.log(`  ${n}：共 ${c.total}，有问题 ${c.fail || 0}${c.warn ? `，要注意 ${c.warn}` : ''}${c.skip ? `，跳过 ${c.skip}` : ''}`);
  line('菜单', sum.menus); line('页面调到的接口', sum.apis); line('接口文档', sum.openapi); line('接口用例', sum.apiCases); line('功能用例', sum.flows);
  console.log(`报告：${path.join(reportDir, 'report.html')}`);
  return sum.failed ? 1 : 0;
}

function check(o) {
  const cfgFile = path.resolve(o.file);
  const cfg = loadConfig(cfgFile);
  const dir = path.dirname(cfgFile);
  const loadCasesForCheck = f => (/\.json$/.test(f) ? JSON.parse : yaml.load)(fs.readFileSync(f, 'utf8'));
  let n = 0, bad = 0;
  for (const [k, pats] of [['接口用例', cfg.api && cfg.api.cases], ['功能用例', cfg.flows]]) {
    for (const f of expandGlobs(dir, pats || [])) {
      try { loadCasesForCheck(f); n++; } catch (e) { bad++; console.log(`${k} ${path.relative(dir, f)} 写法有错：${e.message.split('\n')[0]}`); }
    }
  }
  console.log(`配置能读；用例文件 ${n} 个能读${bad ? `，${bad} 个有错` : ''}`);
  return bad ? 2 : 0;
}

function init(o) {
  const dir = path.resolve(o.file || 'autotest');
  const tpl = path.join(__dirname, '..', 'templates');
  ensureDir(dir);
  const copy = (src, dst) => {
    if (fs.statSync(src).isDirectory()) { ensureDir(dst); for (const f of fs.readdirSync(src)) copy(path.join(src, f), path.join(dst, f)); }
    else if (!fs.existsSync(dst)) fs.copyFileSync(src, dst);
  };
  copy(tpl, dir);
  console.log(`模板放到了 ${dir}：先改 测试配置.yaml 里的地址和登录，再跑 node ${path.relative(process.cwd(), __filename)} run ${path.join(dir, '测试配置.yaml')}`);
  return 0;
}

(async () => {
  const o = args();
  let code;
  try {
    if (o.cmd === 'run') code = await run(o);
    else if (o.cmd === 'init') code = init(o);
    else if (o.cmd === 'check') code = check(o);
    else { console.log('用法：autotest.js run 测试配置.yaml [--only menus,api,flows] [--grep 关键字] [--headed] [--out 目录]\n      autotest.js init 目录\n      autotest.js check 测试配置.yaml'); code = 2; }
  } catch (e) { console.error(e.message); code = 2; }
  process.exit(code);
})();
