---
name: chrome-extension-mv3
description: 写、改、验收 Chrome MV3 浏览器扩展时使用。覆盖「整页截图」这类必须逐屏滚动 + 拼接的能力，以及用 Playwright 真机加载扩展做自动化验收。触发词：写浏览器插件 / Chrome 扩展 / MV3 / manifest v3 / captureVisibleTab / 整页截图 / 全页截图 / 扩展自动化测试 / --load-extension。
agent_created: true
---

# Chrome MV3 扩展开发与验收

把「一个浏览器扩展需求」变成「真机上加载过、跑通过、有自动化断言的产物」。

核心原则：**扩展必须真的在浏览器里加载跑通并留下可复跑的断言** —— 光有语法正确的代码不算交付。
MV3 有一批「写错了不报错、只是行为不对」的陷阱，下面 6 条是最费时间的那批。

## 何时用

- 用户要「装个浏览器插件做 X」（截图、取色、批量操作页面、注入脚本…）
- 需要 `chrome.tabs.captureVisibleTab` / `chrome.scripting` / service worker 编排
- 要给已有扩展补验收脚本

**先做一步判断**：用户说的「插件」是不是指 WorkBuddy 的连接器（Connector）？
用 `search_plugins` 查一下。如果插件市场里有现成 Connector 能满足，优先用它；
没有（例如「网页整页截图」这类纯浏览器能力）才走自定义扩展这条路。

**另一个前置判断**：真的需要写扩展吗？很多需求本机已有更轻的方案：
- 只截自己正在看的页面 → Chrome 自带 DevTools：`⌘⌥I` → `⌘⇧P` → 输入 `full` → **Capture full size screenshot**
- 批量 / 命令行 / 定时 → 命令行截图工具（如项目里的 `tools/webshot/`，支持 `--state` 复用登录态、`--token` SPA 免登）
- 只有「要在自己浏览器里一键、带登录态、不改工作流」时才值得写扩展

---

## 目录骨架

```
<ext-dir>/
  manifest.json        MV3 清单
  background.js        service worker（编排都在这里）
  popup.html/.css/.js  弹窗 UI（只发指令 + 展示）
  icons/               16/48/128（用脚本生成，别找设计）
  README.md            安装步骤 + 已知限制
  install.sh           打开 chrome://extensions + 目录 pbcopy 进剪贴板
  verify.cjs           自动化验收（真实 Chromium 加载扩展）
```

**权限最小化**：能只用 `activeTab` 就别写 `host_permissions: ["<all_urls>"]`。
`activeTab` 在用户点图标时对该页临时授权，足够 `scripting.executeScript` + `captureVisibleTab`，
安装时不会吓人地提示「读取所有网站数据」。

**编排必须放 service worker**：popup 只要用户点一下别处就关了。截图/长任务写在 popup 里，
一半进程就没了。popup 只负责 `sendMessage` + 听 `progress` + 展示结果。

---

## 🔴 六个「写错了不报错」的坑

### 1. `captureVisibleTab` 有配额：每秒 2 次

屏间必须留 ≥500ms（实装 620ms 更稳）。命中配额**直接抛错**，不是排队等待。
这是「整页截图为什么快不起来」的根因 —— 不是性能问题，是 API 限流。
仍然要包退避重试，因为别的扩展/系统截图可能正在占额度。

### 2. 缩放比例必须用 `innerWidth` 还原，**不能用 `clientWidth`**

`captureVisibleTab` 截的是**视口**（`innerWidth × innerHeight`，含滚动条的占位宽度），
返回设备像素。比例 = `首屏图宽 / window.innerWidth`。

用 `documentElement.clientWidth`（少一个滚动条宽，典型差 15px）比例会算大 ~1.3%，
每屏多步进十几像素 ⇒ **拼出来每屏底部一道白缝**。

这个 bug 最阴的地方：**总高度看起来对、比例看起来对，尺寸断言抓不到**，只有像素级检查能发现。
（真实经历：先写对了，又「修」成 clientWidth，白缝才出现。）

### 3. `position:fixed` / `sticky` 每屏都会重复

处理：**首屏保留**（顶栏本来就该在顶上），**第 2 屏起临时 `visibility:hidden`**。
记下元素原本的内联 `visibility`（用 `dataset` 存），结束时还原 —— 否则会破坏页面原有样式。

收集时避免全量 `getComputedStyle`：`body *` 上万个元素逐个取样式很慢，
加个上限（如 20000）并只处理可见元素。

### 4. 最后一屏 `scrollTo` 被浏览器 clamp ⇒ 与上一屏重叠

所以拼接必须用**注入脚本返回的实际 `scrollY`**，不能用理论值 `i × vh`。
重叠部分被后画的图自然覆盖，结果才对。

同时要有防死循环保险丝：某次滚动后 `scrollY` 没前进就 break。

### 5. Chrome 137+ 官方版封了命令行 `--load-extension`

自动化验收**必须用 Playwright 自带的 Chromium**（`channel: 'chromium'`）。
用 `channel: 'chrome'` 会**静默加载不上**：不报错，只是 `waitForEvent('serviceworker')` 超时，
从错误信息完全看不出真实原因。

`launchPersistentContext` 时：
```js
args: [`--disable-extensions-except=${dir}`, `--load-extension=${dir}`],
```
另外扩展在**无头模式下加载不稳定**，验收脚本默认有头 + `--window-position=-2400,-2400` 挪出屏幕。

### 6. `activeTab` 只在「用户真的点了图标」时才授予

自动化里没有这个手势，直接调会报
`Cannot access contents of the page. Extension manifest must request permission to access the respective host.`

解法：验收时**临时复制一份扩展，只追加 `host_permissions`，其余逐字节相同**，跑完删。
不要为了测试去改生产 manifest —— 那会把安装时的权限提示变宽。

```js
const mf = JSON.parse(fs.readFileSync(`${dir}/manifest.json`, 'utf8'));
mf.host_permissions = ['<all_urls>'];
```
并在验收输出里**明说**「跑的是补了权限的副本」，别让人以为测的是原物。

---

## 验收设计：尺寸对 ≠ 内容对

尺寸断言只能证明「没截断」。**错位、重复、白缝这些才是高频 bug，必须像素级验。**

分工：
- `verify.cjs`：控制 Playwright、加载扩展、驱动流程、断言尺寸/分屏数
- `verify-image.py`：读产物 PNG，逐行分析色块（需要 PIL）

### 造一个「会暴露问题」的测试页

别用真实网页当夹具 —— 结果不稳定、无法断言。造一个长页面，包含：
- 8 个等高的**交替纯色**色带（验证有没有漏屏/重叠/丢屏）
- 一个 **`position:fixed` 顶栏**（验证有没有重复出现）
- 每屏可见的标题文字（顺带暴露采样问题，见下）

### 像素级 4 条断言

| 断言 | 抓什么 bug |
|---|---|
| 无空白缝隙 | 缩放比例算错（坑 2）⇒ 每屏底部一道白缝 |
| fixed 顶栏只出现一次 | fixed 处理逻辑回归（坑 3） |
| N 条色带都在 | 整屏丢失 |
| 色带起点间距均匀 | 重叠 / 漏屏 |

### 像素分析两个反直觉点

- **逐行取「众数颜色」，不要抽单列**。色带正中是白色标题文字，抽中轴单列会把一条色带切成
  好几段，导致「8 条色带」误报成 12 段。众数法天然免疫文字干扰（采样 240 点左右即可）。
- **首段间距要跳过**。第一条色带被 fixed 顶栏遮掉一截，首间距天然偏小（是预期行为，不是错位）。

### 别信页面里的 `devicePixelRatio`

Playwright 的 `deviceScaleFactor` 只影响**页面 JS 读到的** dpr；
`captureVisibleTab` 走的是**窗口真实缩放**。两者可能不一致（macOS 非整数缩放下尤其明显）。
⇒ 缩放倍数从**产物尺寸反推**（`图高 / 页面 scrollHeight`），别拿页面 dpr 当期望值。

---

## 怎么问「装好了吗」

用户装扩展必须自己点（无法代点）。给一条命令降低摩擦：

```bash
echo "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" | pbcopy   # 目录进剪贴板
open -a "Google Chrome" "chrome://extensions"
```

然后三步：打开「开发者模式」→「加载已解压的扩展程序」→ 选择框里 `⌘⇧G` 粘贴路径。

⚠️ 提醒用户：Chrome 是**按路径引用**这个目录的 —— 移动/删除目录扩展就失效。
想长期用应复制到固定位置（如 `~/chrome-ext/<name>`）再加载。
（开发者模式加载**不受**坑 5 那个命令行限制影响，可以正常用。）

---

## 反模式

- 把长任务编排写在 popup 里（用户一点别处就断）
- 为了"顺手"申请 `<all_urls>`（安装提示变宽，体验变差）
- 只用尺寸断言就宣布通过（抓不到白缝/重复/错位）
- 用真实网页当测试夹具（不稳定、无法断言）
- 用 `channel: 'chrome'` 做扩展验收（静默加载不上，坑 5）
- 让验收跑在改过权限的副本上却不说明（读数会被误解）
- 说「装好了」而不告诉用户目录不能移动
