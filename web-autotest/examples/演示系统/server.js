'use strict';
// 演示用的小后台：故意埋了几处问题，用来看本技能能不能都查出来。
//   node server.js [端口]     默认 5173，账号 admin / 123456
// 埋的问题：角色管理接口 500；菜单管理页面程序报错；订单接口回 200 但业务码出错；
//          数据报表打开慢；旧版统计是 404 页；用户按「启用」筛选时混进了停用的人（逻辑错）。

const http = require('http');
const port = Number(process.argv[2] || process.env.PORT || 5173);
const TOKEN = 'demo-token-' + Math.random().toString(36).slice(2);
let users = [
  { id: 1, username: 'admin', phone: '13800000001', status: 1 },
  { id: 2, username: 'zhangsan', phone: '13800000002', status: 1 },
  { id: 3, username: 'lisi', phone: '13800000003', status: 0 },
  { id: 4, username: 'wangwu', phone: '13800000004', status: 1 },
  { id: 5, username: 'zhaoliu', phone: '13800000005', status: 0 },
];
let nextId = 6;

const MENU = [
  { name: '首页', path: '/home' },
  { name: '系统管理', path: '/system', children: [
    { name: '用户管理', path: 'user' }, { name: '角色管理', path: 'role' }, { name: '部门管理', path: 'dept' }, { name: '菜单管理', path: 'menu' }] },
  { name: '业务中心', path: '/biz', children: [
    { name: '订单列表', path: 'order' }, { name: '数据报表', path: 'report' }, { name: '旧版统计', path: 'legacy' }] },
  { name: '帮助', path: '/help', children: [{ name: '在线文档', path: '/docs.html', external: true }] },
];

const OPENAPI = {
  openapi: '3.0.0', info: { title: '演示后台', version: '1.0' }, servers: [{ url: '/api' }],
  paths: {
    '/health': { get: { summary: '健康检查' } },
    '/menu': { get: { summary: '菜单树' } },
    '/users': {
      get: { summary: '用户分页', parameters: [{ name: 'current', in: 'query' }, { name: 'size', in: 'query' }, { name: 'keyword', in: 'query' }, { name: 'status', in: 'query' }] },
      post: { summary: '新增用户', requestBody: { content: { 'application/json': {} } } },
    },
    '/users/{id}': { get: { summary: '用户详情', parameters: [{ name: 'id', in: 'path', required: true }] }, delete: { summary: '删除用户', parameters: [{ name: 'id', in: 'path', required: true }] } },
    '/roles': { get: { summary: '角色列表' } },
    '/dept/tree': { get: { summary: '部门树' } },
    '/orders': { get: { summary: '订单分页', parameters: [{ name: 'current', in: 'query' }, { name: 'size', in: 'query' }] } },
    '/report/summary': { get: { summary: '报表汇总' } },
    '/export/{taskId}': { get: { summary: '导出结果', parameters: [{ name: 'taskId', in: 'path', required: true }] } },
  },
};

const ok = data => ({ code: 0, msg: 'ok', data });
const fail = msg => ({ code: 1, msg });

function api(req, url, body) {
  const p = url.pathname.replace(/^\/api/, '');
  if (p === '/openapi.json') return [200, OPENAPI];
  if (p === '/health') return [200, ok('up')];
  if (p === '/login' && req.method === 'POST') {
    return body.username === 'admin' && body.password === '123456' ? [200, ok({ token: TOKEN, name: '管理员' })] : [200, fail('用户名或密码错误')];
  }
  if (req.headers.authorization !== 'Bearer ' + TOKEN) return [401, fail('请先登录')];
  if (p === '/menu') return [200, ok(MENU)];
  if (p === '/users' && req.method === 'GET') {
    const kw = url.searchParams.get('keyword') || '';
    const st = url.searchParams.get('status');
    let list = users.filter(u => !kw || u.username.includes(kw));
    // 埋的逻辑错：筛「停用」是对的，筛「启用」忘了过滤
    if (st === '0') list = list.filter(u => u.status === 0);
    const size = Number(url.searchParams.get('size') || 10), cur = Number(url.searchParams.get('current') || 1);
    return [200, ok({ records: list.slice((cur - 1) * size, cur * size), total: list.length })];
  }
  if (p === '/users' && req.method === 'POST') {
    if (!body.username) return [200, fail('用户名不能为空')];
    if (users.some(u => u.username === body.username)) return [200, fail('用户名已存在')];
    if (body.phone && !/^1\d{10}$/.test(body.phone)) return [200, fail('手机号格式不对')];
    const u = { id: nextId++, username: body.username, phone: body.phone || '', status: 1 };
    users.push(u); return [200, ok(u)];
  }
  let m;
  if ((m = p.match(/^\/users\/(\d+)$/))) {
    const u = users.find(x => x.id === Number(m[1]));
    if (req.method === 'DELETE') { if (!u) return [200, fail('用户不存在')]; users = users.filter(x => x !== u); return [200, ok(true)]; }
    return u ? [200, ok(u)] : [200, fail('用户不存在')];
  }
  if (p === '/roles') return [500, { timestamp: Date.now(), status: 500, error: 'Internal Server Error', path: '/api/roles' }];
  if (p === '/dept/tree') return [200, ok([{ id: 1, name: '总公司', children: [{ id: 2, name: '技术部' }, { id: 3, name: '市场部' }] }])];
  if (p === '/orders') return [200, { code: 500, msg: '数据库连接超时', data: null }];
  if (p === '/report/summary') return ['slow', ok({ orders: 128, amount: 35600 })];
  return [404, fail('接口不存在')];
}

const PAGE = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>演示后台</title><style>
body{margin:0;font:14px "Microsoft YaHei",sans-serif;display:flex;height:100vh}
aside{width:210px;background:#304156;color:#bfcbd9;overflow:auto}aside ul{list-style:none;margin:0;padding:0}
.el-menu-item,.el-sub-menu__title{padding:0 20px;line-height:50px;cursor:pointer}.el-menu-item:hover,.el-sub-menu__title:hover{background:#263445}
.el-sub-menu .el-menu{display:none}.el-sub-menu.is-opened>.el-menu{display:block}.el-sub-menu .el-menu-item{padding-left:40px;background:#1f2d3d}
.el-menu-item.is-active{color:#409eff}
.el-main{flex:1;padding:20px;overflow:auto}
table{border-collapse:collapse;width:100%;margin-top:12px}td,th{border:1px solid #ebeef5;padding:8px}
button{padding:6px 14px;margin-right:6px;cursor:pointer}input{padding:6px}
.el-message{position:fixed;top:20px;left:50%;transform:translateX(-50%);padding:10px 20px;border-radius:4px}
.el-message--success{background:#f0f9eb;color:#67c23a}.el-message--error{background:#fef0f0;color:#f56c6c}
.dialog{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center}.dialog>div{background:#fff;padding:20px;width:360px}
.el-select{display:inline-block;position:relative}.el-select-dropdown{position:absolute;top:34px;left:0;background:#fff;border:1px solid #ddd;z-index:9}.el-select-dropdown__item{padding:6px 16px;cursor:pointer;white-space:nowrap}
.login{margin:120px auto;width:320px}.login input{display:block;width:100%;margin:10px 0;box-sizing:border-box}
</style></head><body><div id="app" style="display:flex;width:100%"></div><script>
const $ = s => document.querySelector(s);
const token = () => localStorage.getItem('token');
async function req(method, url, body) {
  const r = await fetch('/api' + url, { method, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token() }, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) { localStorage.removeItem('token'); location.hash = '#/login'; throw new Error('未登录'); }
  if (r.status >= 500) { msg('服务器开小差了', 'error'); throw new Error('服务器错误'); }
  return r.json();
}
function msg(t, type) { const d = document.createElement('div'); d.className = 'el-message el-message--' + type; d.textContent = t; document.body.appendChild(d); setTimeout(() => d.remove(), 2500); }
function loginPage() {
  $('#app').innerHTML = '<div class="login"><h2>演示后台登录</h2><input name="username" placeholder="请输入用户名"><input name="password" type="password" placeholder="请输入密码"><button id="loginBtn">登 录</button></div>';
  $('#loginBtn').onclick = async () => {
    const r = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: $('[name=username]').value, password: $('[name=password]').value }) }).then(r => r.json());
    if (r.code !== 0) return msg(r.msg, 'error');
    localStorage.setItem('token', r.data.token); location.hash = '#/home';
  };
}
let menuTree = null;
async function layout() {
  if (!menuTree) menuTree = (await req('GET', '/menu')).data;
  if ($('aside')) return;
  const item = (m, base) => {
    if (m.children) return '<li class="el-sub-menu"><div class="el-sub-menu__title">' + m.name + '</div><ul class="el-menu">' + m.children.map(c => item(c, m.path)).join('') + '</ul></li>';
    const to = m.external ? m.path : '#' + (m.path.startsWith('/') ? m.path : base + '/' + m.path);
    return '<li class="el-menu-item" data-to="' + to + '"' + (m.external ? ' data-ext="1"' : '') + '>' + m.name + '</li>';
  };
  $('#app').innerHTML = '<aside><ul class="el-menu">' + menuTree.map(m => item(m, '')).join('') + '<li class="el-menu-item" data-logout="1">退出登录</li></ul></aside><section class="el-main" id="main"></section>';
  $('aside').onclick = e => {
    const t = e.target.closest('.el-sub-menu__title, .el-menu-item'); if (!t) return;
    if (t.classList.contains('el-sub-menu__title')) {
      const sub = t.parentElement, open = sub.classList.contains('is-opened');
      document.querySelectorAll('.el-sub-menu.is-opened').forEach(s => s.classList.remove('is-opened')); // 手风琴：一次只开一个
      if (!open) sub.classList.add('is-opened'); return;
    }
    if (t.dataset.logout) { localStorage.removeItem('token'); location.hash = '#/login'; return; }
    if (t.dataset.ext) { window.open(t.dataset.to, '_blank'); return; }
    location.hash = t.dataset.to;
  };
}
const pages = {
  '/home': () => '<h2>欢迎使用演示后台</h2><p>今日订单 128 笔，待处理工单 6 个。</p>',
  '/system/user': async () => {
    setTimeout(bindUser);
    return '<h2>用户管理</h2><input id="kw" placeholder="请输入用户名"> <div class="el-select" id="st"><input readonly placeholder="状态" id="stv"></div> <button id="search">查询</button><button id="add">新增</button><table id="tbl"></table>';
  },
  '/system/role': async () => { const r = await req('GET', '/roles'); return '<h2>角色管理</h2>' + JSON.stringify(r); },
  '/system/dept': async () => { const r = await req('GET', '/dept/tree'); return '<h2>部门管理</h2><ul>' + r.data.map(d => '<li>' + d.name + '<ul>' + d.children.map(c => '<li>' + c.name + '</li>').join('') + '</ul></li>').join('') + '</ul>'; },
  '/system/menu': async () => { const conf = window.menuConfig; return '<h2>菜单管理</h2>' + conf.items.map(x => x.name).join(''); },
  '/biz/order': async () => { const r = await req('GET', '/orders?current=1&size=10'); return '<h2>订单列表</h2><table><tr><th>订单号</th><th>金额</th></tr>' + ((r.data && r.data.records) || []).map(o => '<tr><td>' + o.no + '</td></tr>').join('') + '</table>'; },
  '/biz/report': async () => { const r = await req('GET', '/report/summary'); return '<h2>数据报表</h2><p>订单 ' + r.data.orders + ' 笔，金额 ' + r.data.amount + ' 元</p>'; },
};
let stVal = '';
async function loadUsers() {
  const q = new URLSearchParams({ current: 1, size: 20, keyword: $('#kw').value }); if (stVal !== '') q.set('status', stVal);
  const r = await req('GET', '/users?' + q);
  $('#tbl').innerHTML = '<tr><th>用户名</th><th>手机号</th><th>状态</th><th>操作</th></tr>' + r.data.records.map(u => '<tr><td>' + u.username + '</td><td>' + u.phone + '</td><td class="status">' + (u.status ? '启用' : '停用') + '</td><td><button class="del" data-id="' + u.id + '">删除</button></td></tr>').join('');
}
function bindUser() {
  loadUsers();
  $('#search').onclick = loadUsers;
  $('#stv').onclick = () => { const dd = document.createElement('div'); dd.className = 'el-select-dropdown'; dd.innerHTML = '<div class="el-select-dropdown__item" data-v="">全部</div><div class="el-select-dropdown__item" data-v="1">启用</div><div class="el-select-dropdown__item" data-v="0">停用</div>'; $('#st').appendChild(dd); dd.onclick = e => { const it = e.target.closest('.el-select-dropdown__item'); stVal = it.dataset.v; $('#stv').value = it.textContent; dd.remove(); }; };
  $('#add').onclick = () => {
    const d = document.createElement('div'); d.className = 'dialog';
    d.innerHTML = '<div><h3>新增用户</h3><p><input id="nu" placeholder="用户名"></p><p><input id="np" placeholder="手机号"></p><button id="save">保存</button><button id="cancel">取消</button></div>';
    document.body.appendChild(d);
    $('#cancel').onclick = () => d.remove();
    $('#save').onclick = async () => { const r = await req('POST', '/users', { username: $('#nu').value, phone: $('#np').value }); if (r.code !== 0) return msg(r.msg, 'error'); d.remove(); msg('新增成功', 'success'); loadUsers(); };
  };
  $('#tbl').onclick = async e => { const b = e.target.closest('.del'); if (!b) return; if (!confirm('确定删除吗？')) return; const r = await req('DELETE', '/users/' + b.dataset.id); if (r.code === 0) { msg('删除成功', 'success'); loadUsers(); } };
}
async function route() {
  const h = location.hash.slice(1) || '/home';
  if (h === '/login' || !token()) { document.body.querySelector('aside') && ($('#app').innerHTML = ''); return loginPage(); }
  await layout();
  document.querySelectorAll('.el-menu-item').forEach(i => i.classList.toggle('is-active', i.dataset.to === '#' + h));
  const fn = pages[h];
  $('#main').innerHTML = fn ? await fn() : '<div style="text-align:center;margin-top:100px"><h1>404</h1><p>页面不存在</p></div>';
}
window.addEventListener('hashchange', route); route();
</script></body></html>`;

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  let raw = '';
  req.on('data', c => raw += c);
  req.on('end', () => {
    if (url.pathname.startsWith('/api/')) {
      let body = {}; try { body = JSON.parse(raw || '{}'); } catch {}
      const [st, data] = api(req, url, body);
      const send = code => { res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(data)); };
      return st === 'slow' ? setTimeout(() => send(200), 3500) : send(st);
    }
    if (url.pathname === '/docs.html') { res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); return res.end('<h1>在线文档</h1>'); }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(PAGE);
  });
}).listen(port, '127.0.0.1', () => console.log(`演示后台：http://127.0.0.1:${port}  账号 admin / 123456`));
