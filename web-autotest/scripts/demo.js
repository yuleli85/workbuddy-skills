#!/usr/bin/env node
'use strict';
// 一条命令看效果：起演示后台（故意埋了 6 处问题），跑一遍全套测试，出报告。
//   npm run demo

const { spawn } = require('child_process');
const path = require('path');
const net = require('net');

const root = path.join(__dirname, '..');
const demoDir = path.join(root, 'examples', '演示系统');

function freePort() {
  return new Promise(res => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
}

(async () => {
  const port = await freePort();
  const server = spawn(process.execPath, [path.join(demoDir, 'server.js'), String(port)], { stdio: ['ignore', 'pipe', 'inherit'] });
  await new Promise(r => server.stdout.once('data', r));
  const out = path.join(demoDir, 'autotest-report', 'demo');
  const t = spawn(process.execPath, [path.join(__dirname, 'autotest.js'), 'run', path.join(demoDir, '测试配置.yaml'), '--base', `http://127.0.0.1:${port}`, '--out', out], { stdio: 'inherit' });
  t.on('exit', code => {
    server.kill();
    console.log(code === 1 ? '\n（演示后台本来就埋了问题，查出来是对的；打开上面的报告看看）' : '');
    process.exit(0);
  });
})();
