---
name: prototype-style-port
description: 把线上原型站/设计稿的视觉风格，规格化扒下来并移植到本地前端工程（Vue/Element Plus 优先）。当用户给出一个原型站 URL（或截图）并说「按这个风格改」「对齐这个原型」「重做 UI」，或需要把设计 token 落到某个前端工程时使用。也适用于只需「扒出原型真实设计规格」，以及把已做好的「原型 1:1 复刻快照（HTML+产物 CSS）」逐个落成真实 Vue 页面（SFC）的场景。
agent_created: true
---

# 原型风格移植（prototype-style-port）

把「一个能打开的原型站」变成「本地工程里可落地的设计 token + 组件皮肤 + 实测验收」。
核心原则：**规格来自实测，不来自肉眼**。所有数值（色值、圆角、模糊、阴影、尺寸）都要能从
产物 CSS 或 `getComputedStyle` 里指出来；拿不准就用像素采样对比，别靠"看起来差不多"。

## 触发场景

- 用户给一个原型站 URL + 「按这个风格改 <目录>」
- 用户给设计稿截图，要求统一多个前端工程的观感
- 只需要产出「设计规格说明书」（不落代码）

## 流程

### 0. 先定位「改哪个工程、改哪一层」

```
① 找到工程的样式入口与加载顺序（如 src/theme/index.scss 里 @use 的顺序）
② 找到设计 token 的唯一定义处（哪一层的变量最后加载、能压过其他）
③ 统计现有 token / 工具类在业务页面里的**实际引用量**（grep 计数）
```

第 ③ 步决定杠杆点，**不要跳过**：
- 引用量高 → 页面自己在用这些类 ⇒ 改类定义即可
- 引用量 **= 0**（常见！）→ 页面全靠组件库（Element Plus 等）承载 ⇒ **真正的杠杆是
  「token + 组件库变量映射」**，改页面反而是次要的

同时确认**主题变量的注入方式**：
- 是否有组件把配色**以行内样式写到 `<html>`**（如 `document.documentElement.style.setProperty`）
- 行内样式优先级 > 样式表 ⇒ 这类工程通常有 `THEME_VERSION` 之类的缓存版本号，
  **换版必须升版本号**，否则旧 localStorage/config 会把新默认值整片盖掉（症状：改 CSS 完全无效）
- 首屏是否真的拿到了你要的主色：若主色只在"用户操作后"才写入，**必须把主色族写死在 SCSS 里**

### 1. 扒原型规格

**Next.js 站（App Router）**
```bash
curl -sL <url> -o index.html                 # 找到 /_next/static/css/*.css 与 chunks/app/page-*.js
curl -sL <origin>/_next/static/css/<hash>.css -o proto.css
curl -sL <origin>/_next/static/chunks/app/page-<hash>.js -o proto_page.js
```
- 设计 token：在 `proto.css` 里搜 token 命名空间（如 `#some-id{--a:…;--b:…}`）或 `:root{…}` /
  `[data-theme=…]{…}` 块
- 页面 DOM 骨架：整个原型 HTML 常以**单引号模板字符串**存在 page chunk 里
  （`x.innerHTML='<div id="…"…'`）。按字符扫出该字符串再解 JS 转义（`\n \' \\ \uXXXX`）
  即可拿到结构，**不需要浏览器**

**通用**：从 `proto.css` 里按类名前缀抽取规则，按选择器分组，生成一份可读的规则清单。

### 1-B. 要「1:1 复刻」而不只是「对齐风格」：直接复用 DOM + 产物 CSS

§1 是扒 token 再在工程里重实现，适合**落进既有工程**。
但如果目标是「先做一版给人看、要像素级像」，重实现永远达不到 1:1 —— 改抓原型的**渲染后 DOM**：

```js
// playwright：登录后逐页抓
const h = await page.evaluate(() => '<!DOCTYPE html>\n' + document.documentElement.outerHTML);
```

先侦察，把决定这条路走不走得通的事实量出来：

| 量什么 | 为什么 |
|---|---|
| `canvas` 数量 | canvas 是**黑盒**，outerHTML 抓下来是空白 ⇒ 必须逐个 `toDataURL()` 换成 `<img>` |
| `svg` 数量 | SVG 随 outerHTML 完整带走，这是最好的情况 |
| `img` / `@font-face` / CSS 内 `url()` | 有外链就得逐个下载改路径；全是 data-URI 则**完全离线可用** |
| 各页 `<link rel=stylesheet>` 的 href | 按需现下 —— 产物 CSS 文件名带 hash，**每次部署都会变**，别复用上次缓存的 |

组装三步（其余一律保持原样）：
1. 摘掉框架的 hydration `<script>`（Next/Nuxt 留着会报错、闪烁）；写个 `assert '<script' not in h` 兜底
2. 远程 stylesheet → 本地共用一份 `app.css`（7 页共用，浏览器只缓存一次）；页面自带 inline `<style>` 原样保留
3. 用**声明式锚点**把路由接上：优先 `data-page` / `data-route` 这类原型自带的属性；
   **不要用文本猜测**（图标、空格、多语言都会翻车），也不要在导航项外面套 `<a>` 去改结构。
   没有锚点的入口宁可留成"点不动"，也不要接错目标。

判断陷阱：内页入口的 `data-page` 常常**仍是父级页**（如「看项目进度」的 `data-page` 还是"经营中心"）
—— 它们靠 `data-route` 区分，别被 `data-page` 误导成一级页面。
另外父页面默认选中项自身不要绑跳转（否则自跳、刷新）。

验证：逐页打开，比对 svg 数与源快照一致、`getComputedStyle` 抽查关键视觉（如 `backdrop-filter`）、
**逐个点击入口确认跳到的文件名正确**、控制台零报错。

### 2. 截图（观感只能靠这个）

**首选 `<repo>/tools/webshot`**（已装在 `~/.local/bin/webshot`）—— 整页 / 元素 / 设备预设 /
暗色 / 批量 / PDF / 剪贴板一把梭，不必每次现写脚本：
```bash
webshot <url> -f                                   # 整页长图
webshot <url> -f -w 1600 -o x.png                  # 指定宽与输出名
webshot <url> -f -d iphone-15 --dark               # 手机 + 暗色
webshot <url> -f --token <t>                       # 免登（token 自动插进 hash 内）
```
⚠️ **SPA 整页截图必踩的坑**：滚动常被放在内层容器（`<main style="overflow-y:auto">`），
此时 `document.scrollHeight` 恒等于视口高，裸 `fullPage` 只能截到一屏。webshot 的 `unroll`
会「撑开滚动容器 + 沿祖先链解锁 `overflow:hidden` / `height:100vh`」——**只撑容器不够，
祖先不解锁高度传导不过去**。要它别动 DOM 就加 `--no-unroll`。详见该目录 README。

需要更细的控制（抓 `innerText`、逐元素计算样式、导出 DOM 快照）时，再回落到自己写
playwright 脚本，复用本机已有的内核，别去装新浏览器：
```bash
NODE_PATH=<托管 node_modules，含 playwright> \
  <托管 node>/bin/node shot.cjs
# 或利用 ~/Library/Caches/ms-playwright 里缓存的 chromium
```
截图脚本要点：`deviceScaleFactor: 2`、`locale: 'zh-CN'`、抓 `console`/`pageerror`、
同时导出 `innerText`（便于确认页面真的渲染了）。

**进不去后台时的绕行顺序**（由稳到繁）：
1. 项目既有的**免登/直登链路**（如 `#/<路由>?access_token=<t>`，令牌由项目自带脚本自愈）← 首选
2. 用真实凭据登录（`input[type=email|password]` + 提交按钮文本兜底）
3. 图形/滑块验证码：**不要**去写图像识别，优先改成 1

**自动化截图时怎么"跳过登录"** —— 先诊断登录态存在哪，再选喂法。猜错就是白折腾：

```
登录一次 → dump localStorage / sessionStorage / cookies → 按结果选
```

| 诊断结果 | 用哪招（webshot） |
|---|---|
| 有会话 cookie | `--cookie 'k=v'` |
| 无 cookie，localStorage 里有标志位 | `--local-storage 'k=v'` |
| URL / hash 里带 token | `--token <t>` |

🔴 **静态原型站（Next.js 演示站最常见）十有八九是第 2 种**：登录纯前端，守卫就是
`if(!localStorage.getItem('xxx.session')) router.replace('/login')`，**零 cookie、无网络请求可拦**。
此时 `--cookie` / `--token` **完全无效**。

🔴 **写 localStorage 必须用 `addInitScript`（在页面脚本之前），不能用页面执行 JS**：
后者在 `goto` 之后才跑，那时守卫已经把你踢到 `/login` 了，再写也不会重新渲染。

webshot 已支持：`--local-storage 'k=v'`（可多次）、`--state <storageState.json>`、
`--save-state <file>`（导出后反复复用）。**验收判据**：看 `--json` 的 `title` + `scrollH` ——
登录页通常只有一屏高（`scrollH` ≈ 视口高），比看截图快。
本仓库原型站（`linmo-web-frontend.pages.dev`）的状态文件已归档在 `tools/webshot/states/linmo-proto.json`。

### 3. 落代码

按「令牌 → 组件库映射 → 外壳 → 组件语言 → 复用类 → 暗色」分层重写设计系统文件：

1. **令牌**：色值、圆角刻度、字号阶梯、间距、缓动、阴影。命名沿用工程既有前缀，别引入第二套前缀。
2. **组件库映射**：把 `--el-*`（或 antd/mui 对应变量）逐条映射到自己的令牌；
   **主色族 `light-1..9` / `dark-2` 要按色值自己算出来写死**（与库的 `getLightColor` 同算法：与白色按 n/10 混合）。
3. **外壳**：侧栏 / 顶栏 / 内容区 / 多标签。⚠️ 只改视觉，**不要动被 JS 驱动的定位属性**
   （典型：侧栏激活块的 `position/top` 由 JS 按 `offsetTop` 写 inline，改 `top` 会错位；
   需要微调居中就用 `transform: translate(...)` 补）。
4. **组件语言**：卡片 / 按钮 / 输入 / 表格 / 标签 / 分页 / 弹层 / 页签。
5. **复用类**：原型里反复出现的语汇（指标卡、分段控件、胶囊、AI 面板…），命名加工程前缀。
   **若业务页面引用了它们，在注释里写清"尚未被页面使用/已被 N 处使用"** —— 否则下一个人会误判。
6. **暗色**：原型若有暗色档就照实测值反写；**暗色下底纹（光斑/纹理）同样不能省**。

#### 必踩的坑（无一例外要处理）

- 🔴 **玻璃/半透明质感依赖底纹**。只把卡片做成半透明白、页面底留一片纯浅色，
  实测「卡片 vs 底色亮度差 = 0」，卡片整体糊掉。原型的光斑/纹理**不能省、不能减半**。
  没有 DOM 可加时，把光斑写成 `.pageBg{ background-image: radial-gradient(...), … , linear-gradient(...) }`
  （第一层画在最上；用 `background-attachment: fixed` 锚在窗口上）。
- 🔴 描边方向：玻璃的边是**亮边**（`rgba(255,255,255,.7)`），不是常规的深色描边。
- 🔴 页面底图若是**内联 `:style` 注入**的（`backgroundStyle` 之类），样式表要接管必须 `!important`。
- 🔴 尽量保留原文件里解释「为什么这么做」的注释（踩坑注释是最有价值的资产），只改数值与规则。

### 3-B. 把「1:1 复刻产物」落成真实 Vue 页面（不是重实现）

拿到 §1-B 的复刻快照后，「落进 Vue 工程」**不要手工重写模板** —— 快照 DOM 就是模板源、
产物 CSS 就是样式源。机械转换 + 对拍脚本兜底，比手抄可靠一个数量级。

生产者四件套（建议放进 `<repo>/tools/proto-port/`，可复用）：
`extract-css.cjs`（产物 CSS → 工程内样式文件）· `gen-vue.cjs`（快照 DOM → SFC）·
`diff-styles.cjs`（计算样式对拍 + 标签普查）· `probe-*.cjs`（真机打开 + 交互断言 + 截图）。

**CSS 抽取 5 条隐性规则（少一条就是静默降级，最难查）**

1. **根节点上的自定义属性块（`:root` / `html>body`）会被当成"非本作用域"整条丢弃**，
   而作用域规则里正引用它们 ⇒ 属性值整条失效、**静默回落**（实测 `font-weight` 掉回 400）。
   必须把这些属性块**捞回并改挂到新作用域根**。
2. **rem 相对根元素**。原型 `html{font-size:16px}`、工程可能压到 14px ⇒ 不换算整体缩 0.875 倍。
   ⚠️ css-tree 把 `.82rem`、`calc(.75rem * var(--x))` 解析成 **Raw 而非 Dimension 节点**，
   只处理 Dimension 节点实测只转了 2 处 ⇒ 必须**再遍历 Raw 节点做定点正则替换**，
   并跳过含 `data:`/`url()` 的节点。
3. 产物 CSS 的 **base/reset 层里有真实生效的排版规则**（`h1,h2{font-weight:…}`、`b,strong,th`、
   `small`），它们不在作用域选择器里，整片丢弃同样造成回落 ⇒ 要**救回并补作用域前缀**。
4. **祖先链必须完整**：抽取后很多规则写成 `html body .新根 .新作用域 …`，
   组件里少补一层祖先即**静默失效**（只能靠对拍发现）。补链比改选择器安全。
5. **抽取根节点要选最外层那个有意义的容器**，别只抽"网格/列表"层 ——
   快照里 `.占位容器 h2{font-size:19px}` 这类后代规则会因为祖先层没被抽走而**不命中**。

另外：**所有 id 必须降级为 class**。工程的多标签 / keep-alive 会让同一页面多实例共存，
固定 id 直接撞车（`aria-labelledby`、`label[for]` 这类引用一并去掉）。

**DOM → SFC 的雷区**

- **SVG 驼峰标签序列化必须用 `el.localName`**；用 `tagName.toLowerCase()` 会把
  `linearGradient`/`clipPath` 压成小写，Vue 直接报 `Failed to resolve component: lineargradient`。
- 交互属性**先写 `v-on:` / `v-bind:` 长写法，序列化后再归一成 `@` / `:`** ——
  jsdom 的 `setAttribute` 按 XML Name 校验，`@click` 会被 `InvalidCharacterError` 拒掉。
- **布尔属性用 `v-show` 别用 `:hidden`**：`hidden` 不在 Vue 的布尔属性特判里，
  `:hidden="false"` 会渲染成 `hidden="false"`，而该属性**只要存在就隐藏**。
- 加绑定前先 `removeAttribute` 掉同名静态值（否则 `aria-pressed` 静态+绑定重复）。
- 返回按钮**用 `window.history.state.back`**，别用 `history.length > 1` ——
  直接输地址打开时前一条是空白页，长度恒 >1，会跳 `about:blank`。
- 外壳归属先问清：**只落内容区**（保留工程原生侧栏/顶栏/多标签）+ 菜单段位另开一段并存，
  通常最稳；整页替换会和工程的路由/菜单/滚动体系打架。

**验收：用计算样式对拍，不要用像素**

像素比对会被外壳宽度差异淹没（原型侧栏 144px vs 工程导轨+分栏 ~280px，内容区宽度天然不同）。
**对拍必须限定"本页可见主体根"**：复刻快照是整页 DOM，其它页那份 `#dashboard` 仍存在只是
`display:none`，不加限定会选中隐藏元素 ⇒ 结果全错（实测踩过）。
另配一份**标签普查**（用 `localName` 统计每种标签计数）——它能证明"元素没丢/没重复/没被压平"，
计算样式只能证明"选中的那个元素样式对"。

⚠️ **普查必须把「内容区」和「外壳区」分开统计**。工程外壳（多标签栏 / 侧栏图标）的计数会随
标签开合自然波动（实测 `<i> / <li> / <path> / <span> / <svg>` 同步 -5），
混在一起统计会被误判成结构回归 —— 这类误报会让人白查半天。

### 4. 实测验收（别用肉眼下结论）

起 dev 服务 → 截图 → **像素采样对比原型与新实现**：

```python
# 沿一条水平扫描线/取色块均值，量「卡片内部 vs 卡片旁页面底」的亮度差 ΔL
lum = lambda t: 0.2126*t[0] + 0.7152*t[1] + 0.0722*t[2]
```
- 采样窗口别跨到元素边缘（±3px 以内；7px 窗口落在 7px 缝隙上会两边都沾）
- 采样点必须落在**语义相同的区域**（双方布局不同时，"同一相对坐标"往往不是同一个东西）
- 判据：ΔL 落进原型同区间即通过；**ΔL ≈ 0 就是失败**（元素与底同色）

必查项：登录页 / 主界面 / 含重表格的页 / 含抽屉或弹窗的页 / 暗色档 /
侧栏激活项对齐（用 `getBoundingClientRect` 打印元素盒子，验证上下留白均分）。

### 5. 换肤改的是被桌面端打包的前端？必须重新出包并验真机

改了 `src/theme/**` 而工程又被打进 Electron 安装包（如 `pig-pc-ui/desktop`）时，
**dev 服务验过 ≠ 用户装到的版本变了**：安装包里的 `resources/web` 是构建快照，必须重跑全链路。

典型链路（以 `pig-pc-ui` + `desktop/` 为例）：
```bash
npm run build --prefix <前端工程>        # 产出 dist/
cd <前端工程>/desktop && npm run dist:mac # icon → prepare:web(dist→web) → electron-builder --mac
```

四个几乎每次都会踩的坑：

1. **`ELECTRON_RUN_AS_NODE=1` 可能已在宿主 shell 环境里被设上** ⇒ 直接执行
   `<App>/Contents/MacOS/<binary>` 不会起 Electron，而是**掉进 Node REPL**（端口不监听；
   Chromium 开关如 `--remote-debugging-port` 会报 `bad option:`，极易误判成"Electron 不支持该开关"）。
   验收启动**必须用 `open <App>`**（经 launchd，环境干净）或 `env -u ELECTRON_RUN_AS_NODE`。
   退出别用 `osascript ... quit`（TCC 会挡，权限违例 -10004），直接 `kill`。

2. **"覆盖式同步、刻意不清空"的中间目录会累积幽灵文件。** `prepare-web.mjs` 这类脚本为绕开
   受管环境的批量删除拦截，只覆盖不清理 ⇒ 历史 hash 产物越积越多并被原样打进包
   （实测：dist 17MB / 1497 文件，而 `web/` 积到 82MB / 8573 文件，包虚高 30MiB）。
   干净重建的正解是**改名隔离**，不是删除：
   ```bash
   mv web "release-stale-web-$(date +%Y%m%d-%H%M)"   # 新名字必须落进 .gitignore 的 release*/ 规则
   mv release/mac-arm64 release/mac-arm64.stale-...   # 否则 builder 清 appOutDir 也会撞删除拦截
   ```
   名字若不被 gitignore 覆盖，几千个未跟踪文件会污染 `git status`。

3. **通用的产物断言脚本常常没有本平台分支。** 见到一堆 FAIL 先读脚本再下结论 ——
   例如 `verify-package.cjs` 只断言 Windows 的 `release/win-unpacked`，只打 mac 时必然
   FAIL 并 ENOENT，**这不是包坏了**。别急着改包，先确认脚本覆盖范围。

4. **体积/内容/签名三样都要自己量。** 本平台验收模板（都通过才算数）：
   ```bash
   rsync -rcn --delete dist/ "<App>/Contents/Resources/web/"   # 逐文件 checksum，要求零差异输出
   codesign -dv --verbose=2 "<App>" && codesign --verify --verbose=2 "<App>"
   hdiutil attach -nobrowse -readonly out.dmg                  # 卷内 App 再跑一次 rsync 比对
   open "<App>"; curl -s -o /dev/null -w '%{http_code} %{size_download}\n' http://127.0.0.1:<内置服务端口>/
   ```
   最后一步是真机渲染证据：用 playwright 打开该内置端口，`getComputedStyle` 采
   `--el-color-primary` / 自定义令牌，确认换肤在**打包后的运行时**同样生效（首屏值尤其要看 ——
   若主色靠运行时行内注入，首屏会退回框架默认色）。

5. **打包产物目录若落在前端工程内部，会污染 dev server 的文件监听。** 常见形态：
   `vite.config.mts` 里 `root: process.cwd()` 且 `server` 段**没有 `watch.ignored`** ⇒
   `desktop/web/`（dist 的副本）、`desktop/release/`（electron-builder 输出）全在监听范围内，
   **打一次包就往里写几千个文件 ⇒ 构建工具判定"整站变更"并触发全量 page reload**
   （实测连 `LICENSES.chromium.html` 都触发过），表现为开发时页面无端刷新、
   甚至干扰自动化截图/探针的稳定性。修法：
   ```ts
   server: { watch: { ignored: ['**/desktop/**', '**/dist/**', '**/release*/**', '**/.vite/**'] } }
   ```
   ⚠️ **改 `vite.config.*` 必须重启 dev server 才生效**（不像源码走 HMR）。
   ⚠️ 验 HMR 别用 `touch` —— 新版 Vite 会比对内容，`touch` 只改 mtime **不会**触发；
   要真实写入再还原文件。

6. **「重打包」之后要真替换已安装的 App，否则用户点开的还是旧包。** 顺序：停 → 隔离旧包 → `ditto` 新包 → `open`：
   ```bash
   pkill -f "<产品名>.app"                        # osascript quit 会被 TCC 挡（-10004 权限违例）
   mv "/Applications/<产品名>.app" ~/.Trash/"<产品名>.app.$(date +%Y%m%d-%H%M%S)"  # 进废纸篓可回滚
   ditto "release/mac-arm64/<产品名>.app" "/Applications/<产品名>.app"            # 保留权限/xattr/签名
   open "/Applications/<产品名>.app"
   ```
   验收取**哈希对账**（比"窗口打开了"强得多）：构建日志里的入口包名 `dist/assets/index.<hash>.js`
   必须与 `curl -s http://127.0.0.1:<内置服务端口>/ | grep -oE 'assets/index\.[A-Za-z0-9_-]+\.js'`
   完全一致 ⇒ 证明跑的确是刚构建的前端。
   ⚠️ 受管沙箱里 `ps aux` 报 `operation not permitted` ⇒ 定位进程用 `pgrep -fl`；
   `lsof -p <pid>` 的中文列会乱码，先 `export LC_ALL=C`。
   另：这类 Electron 壳内置的静态服务通常**同时反向代理 `/api`** 到后端
   （实测 `127.0.0.1:<内置端口>/api/admin/` 与后端直连同响应）⇒ 桌面端可脱离 nginx 单独验收。

## 交付

- 改了哪些文件、每处为什么（表格）
- 截图（原型参考 + 新实现，含暗色与弹窗）
- **未覆盖的范围明确说出来**（例如"只改了 pc-ui，另外两个前端仍是旧观感"）
- 已知偏差与偏差原因

## 反模式

- 不扒产物、只看截图就手动猜色值
- 把页面逐个手改，却没先确认设计系统层的杠杆点
- 加了 `!important` 却没在注释里写清为什么（下次有人会"顺手清理"掉）
- 号称"对齐了"但没有任何数值/截图证据
- 换了被 Electron 打包的工程的皮肤，却只跑 dev 就说交付完成 —— 安装包里的还是旧快照
- 清理构建中间产物时直接 `rm -rf`（受管环境拦批量删除）；应该「改名隔离」到 gitignore 覆盖的名字下
- 看到产物断言 FAIL 就先怀疑包，不先读断言脚本覆盖的是哪个平台
