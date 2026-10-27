---
name: pig-ui-browser-verify
description: 在 linmo-pig-full（灵猫企管）里用真实浏览器（Playwright）实拍验收前端页面 —— 登录、导航到 hash 路由、点击页签、断言渲染结果、截图存档，并在需要时重建 pc-ui/pig-ui 容器让改动生效。当用户说「看看这个页面出来没有」「验收一下 UI」「截图给我看」「按原型对一下」「本地页面打不开/空白」「改了前端但 8890 没变」时使用。也覆盖「按截图 1:1 复刻某页 → 实拍比对」的闭环。
agent_created: true
---

# PIG 前端页面浏览器实拍验收（pig-ui-browser-verify）

**目的**：把「我改完了」变成「我实拍给你看了」。凡是改前端页面/复刻原型的任务，
**最后一步必须是真机浏览器截图 + 关键断言**，不能只看构建通过。

核心原则：**判据来自实测，不来自肉眼**。颜色、坐标、是否可见、能不能滚到底，都用
`getComputedStyle` / `getBoundingClientRect` / 像素采样拿数，别靠"看起来差不多"。

---

## 0. 五条铁律（踩过的坑，先看这里）

1. **`document.documentElement.scrollHeight === innerHeight` 是正常的**，不代表页面不能滚。
   PIG 的滚动宿主是 Element Plus 的 `.el-scrollbar__wrap`。
2. **页面里有 7 个 `.el-scrollbar__wrap`**，第一个是侧边栏的（不可滚）。
   必须找「**包含目标根元素** 且 `scrollHeight > clientHeight`」的那个，否则得出「最大滚动 0」的错判。
3. **沙箱里 chromium 缓存版本 ≠ playwright 期望版本**，且**沙箱注入的 proxy 会拦 localhost**。
   照抄下面 §2 的启动参数，别自己试。
4. **写 .mjs 脚本用 Write 工具，不要用 `cat <<'EOF'` heredoc**：脚本里只要出现 JS 模板字符串
   `` `${r.status()} …` `` 这类 `${...}`，经 Bash 工具的 heredoc 会报 `Bad substitution`（2026-10-11 实测）。
   另外 `.mjs` 是 ESM，**完全忽略 NODE_PATH**，`import { chromium } from 'playwright'` 在 `/tmp` 这类目录下
   会稳定报 `ERR_MODULE_NOT_FOUND`。两种走法都行：
   ① `createRequire('/Users/shan/.workbuddy/binaries/node/workspace/')`（通用，脚本放哪都行）；
   ② **把 `.mjs` 直接写到 `/Users/shan/.workbuddy/binaries/node/workspace/` 里再 `cd` 过去执行** ——
      node 从脚本所在目录逐级向上找 `node_modules`，裸 `import { chromium } from 'playwright'` 就能解析
      （2026-10-13 实测，适合一次性脚本，比 createRequire 少一层样板）。
5. **线上环境也能直接验**：`pc.mzlc.me` 可达（200）时，同一脚本传 `BASE=https://pc.mzlc.me`
   即可对线上做 A/B 对照（本地已修复 vs 线上未修复），是「证明修没修对」的最快手段。

---

## 1. 环境事实（本机）

| 项 | 值 |
|---|---|
| playwright | `/Users/shan/.workbuddy/binaries/node/workspace/node_modules`（**ESM 不吃 `NODE_PATH`**；用 `createRequire` 指过去，或把脚本放进该目录，见 §2） |
| chromium 可执行 | `/Users/shan/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell` |
| node | `/Users/shan/.workbuddy/binaries/node/versions/22.22.2-3/bin/node` |
| docker | `/usr/local/bin/docker`（**不在沙箱 PATH**，先 `export PATH="/usr/local/bin:$PATH"`） |
| 前端端口 | pig-ui **8888** / pig-pc-ui **8890** / pig-mob-ui 8899 |
| 登录 | `admin` / `123456`，**无验证码** |

> 别去装 `agent-browser`（skill 市场那个）—— 本机已有 playwright + chromium 缓存，装它要重下 500MB。

---

## 2. 启动骨架（复制即用）

```js
// 🔴 必须用 createRequire —— 脚本是 .mjs（ESM），而 **ESM 完全忽略 NODE_PATH**：
//    写 `import { chromium } from 'playwright'` 会稳定报
//    `ERR_MODULE_NOT_FOUND: Cannot find package 'playwright' imported from /private/tmp/verify/xx.mjs`
//    （2026-10-09 实测，别去怀疑 playwright 没装）。
import { createRequire } from 'module';
const require = createRequire('/Users/shan/.workbuddy/binaries/node/workspace/');
const { chromium } = require('playwright');

const EXEC = '/Users/shan/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const b = await chromium.launch({ executablePath: EXEC, args: ['--no-proxy-server', '--proxy-bypass-list=*'] });
const p = await (await b.newContext({ viewport: { width: 1680, height: 1000 } })).newPage();
```

运行（**必须清代理**，否则 `ERR_PROXY_CONNECTION_FAILED`）：

```bash
cd /Users/shan/work/linmo-pig-full && \
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy NO_PROXY='localhost,127.0.0.1' \
/Users/shan/.workbuddy/binaries/node/versions/22.22.2-3/bin/node /tmp/verify/xx.mjs
```

⚠️ **别写 `proxy: { server: 'direct://' }`** —— 无效，反而报代理错。

### 登录 + 导航到 hash 路由

```js
const BASE = 'http://localhost:8890';
await p.goto(BASE + '/#/ops/agent/index', { waitUntil: 'domcontentloaded' });
await p.waitForTimeout(3500);
if (await p.locator('input[type="password"]').count()) {          // 会跳 /#/login?redirect=...
  const t = p.locator('input:not([type="password"]):not([type="checkbox"]):not([type="hidden"])');
  await t.nth(0).fill('admin');
  await p.locator('input[type="password"]').first().fill('123456');
  await p.locator('button:has-text("登录"), button:has-text("登 录")').first().click();
  await p.waitForTimeout(4000);
  await p.goto(BASE + '/#/ops/agent/index', { waitUntil: 'domcontentloaded' });  // 登录后必须重新 goto
  await p.waitForTimeout(3500);
}
```

> 🔴 **登录后一定要重新 `goto` 目标 hash**。直接改 `location.hash` 不会触发路由重载。

---

## 3. 正确判断「能不能滚到底」

```js
const host = await p.evaluate(() => {
  const mock = document.querySelector('#linmo-b2b-mockup');      // 换成你的页面根元素
  const w = [...document.querySelectorAll('.el-scrollbar__wrap')]
    .find((x) => x.contains(mock) && x.scrollHeight > x.clientHeight + 2);
  if (!w) return null;
  w.scrollTop = w.scrollHeight;                                   // 滚到底
  return { max: w.scrollHeight - w.clientHeight, scrollTop: w.scrollTop };
});
// 再断言：目标卡片 / 条目 rect.top < innerHeight && rect.bottom > 0
```

**验收口径**：所有承载数据的卡片 + 条目在滚到底后逐个 `inView === true`，才算「能看到全部数据」。
构建产物里若某容器带 `overflow:hidden` + 固定高，会表现为「滚动条在但滚不动」——
此时查 `linmo-port.css` 的 `#linmo-b2b-mockup { overflow:hidden; min-height:760px }`，
按需在页面级用 `overflow: visible !important` 覆盖（**ID 特异性高，必须 `!important`**）。

---

## 4. 让改动生效（前端是构建产物镜像）

```bash
export PATH="/usr/local/bin:$PATH"
cd /Users/shan/work/linmo-pig-full
docker compose --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml --profile pcui build pig-pc-ui        # 约 35~41s
docker compose --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml --profile pcui up -d --force-recreate pig-pc-ui
```

- 🔴 **两个 `--env-file` 都要带**，`--profile pcui` 必须带（否则 pig-pc-ui 不在范围）。
- ⚠️ **`up -d --force-recreate pig-pc-ui` 会顺带重建 `python-ai`**（依赖图牵连 + 新建卷）。
  若**只想动前端**：`docker cp <本地dist或conf> 容器:/path && nginx -s reload`，别整机 recreate。
- **验证产物真的换了**（比看时间戳可靠）：
  ```bash
  docker exec linmo-pig-pc-ui sh -lc "grep -rl '你的新增文案' /data/assets | head"
  ```
- 探活：`curl -s --noproxy '*' -o /dev/null -w '%{http_code}' http://localhost:8890/` ⇒ 200。
  🔴 **`curl` 必须加 `--noproxy '*'`**，否则走代理失败会返纯文本，极易误判成 nginx 502。

> pc-ui 走 **pnpm**（仓库只有 `pnpm-lock.yaml`）；本地开发想快就用 `pnpm dev`（8892，HMR <1s），
> 容器 8890 是生产态，每次都要重新 build。

---

## 4.5 改「壳组件」的额外规矩（三端同源 + 一次出两镜像）

`views/linmo/views/agents/` 下的**壳组件**（`AgentOverviewCard.vue` / `AgentSummaryCard.vue` / `AgentAlertCard.vue` …）
在三端是**逐字节同源**的（2026-10-14 实测 `AgentOverviewCard.vue` 三端同一 blob `67e1b16b`）。改前先验，改后必须三端一起改：

```bash
for d in pig-ui pig-mob-ui pig-pc-ui; do
  printf '%-10s %s\n' "$d" "$(git hash-object $d/src/views/linmo/views/agents/AgentOverviewCard.vue | cut -c1-12)"
done      # 三行同一 hash ⇒ 同源；改完必须仍是三行同一 hash
```

- ⚠️ **只改一端 ⇒ 页面之间立刻不一致**（mob-ui 8899 与 pc-ui 8890 不同源是另一回事，`AgentOverviewCard` 这类壳是真同源）。
- **一次 build 出两个镜像**（pig-ui 的 `npm ci` 与 pig-pc-ui 的 `pnpm` 在同一条命令里并行跑）：

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"   # 与 /usr/local/bin/docker 等价
cd /Users/shan/work/linmo-pig-full                                     # 🔴 必须是**运行栈**那侧的 checkout
docker compose --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml --profile pcui build pig-ui pig-pc-ui   # 实测 1m03s
docker compose --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml --profile pcui up -d --no-deps pig-ui pig-pc-ui
# 判「真的换了」：容器 .Image == 镜像 .Id（SAME），别只看 Created 时间
```

- 🔴 **`.vue` 模板里删元素时的 lint 坑**：`v-for="(v, k) in trend.periods"` 若把用到 `v` 的子节点删掉，
  `v` 就成了未使用变量 ⇒ 被 `plugin:vue/vue3-essential` 的 `vue/no-unused-vars` +
  `@typescript-eslint/no-unused-vars:[2]` 判错。**改成 `v-for="k in Object.keys(trend.periods)"`**
  （本仓模板已有 `Object.keys($slots)` 先例；`Object` 在 Vue 3 模板全局白名单里）。
  注意三端 build **只跑 `vite build`，不含 vue-tsc / eslint** ⇒ lint 错**不会**挡构建，会在 CI/lint 阶段才爆。
- 🔴 **定位元素的坑**：`article.lm-detail-card` 的 `first()` 命中的是「**智能体总结**」卡，不是「**概况卡**」。
  要验概况卡头部的胶囊请直接 `.lm-trend-periods`（全页唯一，`count() === 1`），别靠 `.lm-detail-card` 序号。


## 4.6 用户说「改了没看到」时，先做四层对账，别急着改代码

反复出现的场景：改完 + 重建 + 实拍全过了，用户仍贴旧截图说「没改」。**根因几乎总是浏览器没刷新**，
但也可能构建没带上代码。用固定四层对账一次分清（本项目 2026-10-14 实测两次）：

| 层 | 命令 | 通过标准 |
|---|---|---|
| 代码 | 两 checkout `git hash-object <file>` 比对 + grep 新标记 | blob 一致且含新逻辑 |
| 产物 | `docker inspect <容器> --format '{{.Image}}'` vs `docker image inspect <镜像> --format '{{.Id}}'` | 两串相等 |
| 服务 | `docker exec <容器> sh -c 'grep -rl <新标记> /data/assets'` + `curl -sI` | 命中 chunk；`Cache-Control: no-cache` |
| 渲染 | 无缓存 Playwright dump DOM | 元素结构/文本 = 期望 |

⚠️ `docker inspect` **只在名字对得上时才有意义**：本项目容器名是 `linmo-pig-ui` / `linmo-pig-pc-ui`
（**不是** `linmo-pcui`）。且**别在 zsh 里写 `for pair in "a b"; do set -- $pair`** —— zsh 不做词分割，
`$1` 会是整串、`$2` 空 ⇒ `docker inspect "linmo-$1"` 永远「容器不存在」，会得出「没生效」的**假结论**。
逐个变量赋值，或干脆写死两条命令。

🔴 **判定「是不是另一个版本」必须放大原图核对文案**：缩略图肉眼读会把「在途项目」看成「在办项目」、
「超期任务」看成「超额任务」，进而误判成「用户在另一套环境」。正确做法：把用户截图裁到关心区域、
放大 3× 再读（`Image.resize(..., LANCZOS)`）。

🔴 本机前端 nginx 已正确设置：`index.html` = `no-cache, must-revalidate`，hash 产物 = 一年 immutable
⇒ **不存在「普通刷新拿到旧页面」**，让用户 F5 即可；仍不行才怀疑强缓存或另一个部署。

## 4.7 只想「眼看新改动」但运行镜像落后于源码时：临时预览容器（不碰在跑栈）

适用：私仓镜像版编排（`deploy-*` 容器）的 tag 落后于本地 dev 源码，重打镜像又太重。
做法 = 用本机现成 `nginx:1.27-alpine` 挂本地 dist + 仓库 nginx.conf，挂到 `deploy_backend` 网络借后端：

```bash
docker rm -f tmp-verify-ui >/dev/null 2>&1 || true
docker run -d --name tmp-verify-ui --network deploy_backend -p 18888:80 \
  -v <repo>/pig-ui/dist:/data:ro \
  -v <repo>/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro \
  nginx:1.27-alpine
# 验收完删掉：docker rm -f tmp-verify-ui
```

- 容器内 DNS 直接解析 `pig:9999` / `python-ai:8090`（deploy 服务的网络别名），登录/接口全通，端口 18888 不与 8888/8890 冲突。
- ⚠️ **别把本地 dist `docker cp` 进在跑的 `deploy-nginx-1`**：本地源码通常领先镜像一大截
  （2026-10-15 实测 962/1723 个 chunk hash 不同）⇒ 热推等于把整个未发布前端偷偷上线，会造成「标签↔内容」漂移。
- 后续核对是否值得重打镜像：`ls /data/assets` 与本地 dist 各自 `sed 's/\.[0-9a-zA-Z_-]*\.js$//'` 归一后 diff。



## 4.8 「自动刷新 / 轮询」类改动的验收口径（2026-10-15 实测）

用户诉求常是「XX 页面要能自动取到最新数据」。这类改动**光断言按钮存在、样式变化是不够的** ——
必须证明「它真的按周期发了请求」，否则可能只是加了个不会跑的开关。

做法（`p.on('request')` 计数 + 等一个周期）：

```js
const hits = { n: 0 };
p.on('request', (r) => {
  const u = r.url();
  if (u.includes('/admin/ops/agent/details/') || u.includes('/admin/ops/agent/commit-trend/')) hits.n += 1;
});
// ① 开启开关 → 应「立即补拉一次」：4s 内计数增加（本项目实测 5 → 10）
// ② 再等一个周期（70s > 60s 间隔）→ 计数必须继续增加（实测 10 → 15）
```

判据：两段 `after > before` 都成立才算通过。**只截图看不出轮询到底有没有跑。**

其它必查项：
- **开关状态要持久化**（本项目用 localStorage `linmo-dept-live-refresh`），验收断言关/开两态的
  `aria-pressed` 与存储值（`'1'` / `'0'`）。
- **后台标签必须跳过**：`document.visibilityState === 'hidden'` 直接 return；切回前台若已超一个周期，
  立即补一次（`visibilitychange` 监听）。
- **卸载 / keep-alive 必须停表**：`onDeactivated` / `onUnmounted` 里 `clearInterval` 并摘
  `visibilitychange` 监听，否则切页后仍在后台打接口。
- **自动刷新只做只读重拉**，别顺手触发采集（写操作）—— 采集留给手动「更新数据」按钮（需 `ops_sync_trigger`）。
- 共用壳（`AgentReport.vue`）改一次 = 七类智能体全受益；改前先验三端同源（§4.5）。
- 交付口径：本机 8888/8890 生效 ≠ 用户看的实例生效。用户截图若来自**他机**（如 `192.168.110.172:8888`），
  必须明说「需那条部署链路出新版本（git 推送 / CI 出镜像）」，别让用户以为刷新一下就有了。

## 5. 按截图 1:1 复刻时的取值套路

截图里的**数值/颜色不要靠肉眼读**，用像素分析：

```python
# 用 /Users/shan/.workbuddy/binaries/python/envs/default/bin/python（有 PIL）
from PIL import Image
import numpy as np
a = np.asarray(Image.open(PIC).convert('RGB')).astype(int)
# 1) 找文字行：某列区间内"暗像素"按行聚簇
# 2) 找曲线：按色相筛（蓝线 B-R>45；灰虚线 abs(R-G)<14 且 B-R>14）
# 3) 找彩色圆点：warm = R-B>18 & R-G>8（红/橙）；green = G-R>18 & G-B>12
# 4) 打印 RGB 直接对现有 CSS 变量
```

典型收获：y 轴刻度可能是**取整后重复**的（如 4/4/3/3/3），说明量程不是 0 起 ——
这时 `gridYs` 的 `:key` **必须用下标**，用取值会重复 key。
同时说明该图用的是**贴近数据的窄量程**（如 `lo = min - span*0.4`、`hi = max + span*0.2`）。

`Read` 工具**能读图片**（jpg/png 都行）—— 第一遍先整图看结构，再逐区域 `crop + resize` 放大核对文案与配色。
⚠️ 裁图坐标要按**真实像素尺寸**算，别按阅读器里看到的那张缩略图的比例；先用 `im.size` 打印确认。

---

## 6. 收尾（必做）

1. **对照图存档**：把「原型截图」和「实拍截图」上下拼一张 PNG 落到 `output/`，用中文字体渲染标题
   （字体走 `/System/Library/Fonts/Supplemental/Songti.ttc`；`PingFang.ttc` 在本机不存在，用它会退化成默认体、中文变方框）。
2. **console/pageerror 要按「逐页增量」判，别用「必须为空」一刀切**：`p.on('console', m => m.type()==='error' && errs.push(...))`，
   并在**每个页面导航前后各记一次 `errs.length`**，差值才是「这一页引入的新错误」。
   本仓有**既存噪声**（如 `sys_menu 4004「站点统计」/tools/data/clarity` 的 component 为 NULL），
   用「总数必须 0」会把既存问题误判成本次回归，也会漏掉「修完仍然报」的真相。
3. **改「隐藏菜单」类修复时，除截图外必须断言两条**：① 该菜单**不在** `document.body.innerText` 里（侧栏/导航已消失）；
   ② `console.error` 里**不再出现**它的名字。只看截图看不出来 —— 菜单可能只是被折叠了。
4. 汇报时给：**结论 + 改了哪些文件 + 怎么生效 + 与原型仍存在的差异（含原因）**。

---

## 7. 表格类页面验收的两个坑（2026-10-16 dbupgrade 页实测）

### 7.1 el-tabs 双面板常驻 ⇒ 表格选择器必须作用域化

页面若用 `el-tabs`（本仓默认不销毁未激活 pane），`.el-table__body tr` 会把**隐藏 tab 的表格行一起抓进来**（dbupgrade 页 = 升级脚本 + SQL 执行台两表），断言会莫名 FAIL。必须用面板根 class 限定：

```js
const S = '.upgrade-panel';   // 目标面板的根 class
await p.$$eval(S + ' .el-table__body tr', ...)      // body 行
await p.$$eval(S + ' .el-table__header th', ...)    // 表头
p.locator(S + ' .el-table__header th').filter({ hasText: '执行时间' })
```

### 7.2 el-table 排序是三态循环，default-sort=descending 时点一下 = 取消排序

Element Plus 列头点击循环是 `ascending → descending → null(取消)`，不是两态。设了 `:default-sort="{ order: 'descending' }"` 时：

- 第 1 次点击 → **null（取消排序，回数据原始顺序）**；
- 第 2 次点击 → ascending；
- 第 3 次点击 → 回 descending。

写断言按这个循环来；若用 `sortable="custom"` + `@sort-change` 自行排序，`order === null` 时记得还原原始列表（后端返回序）。
