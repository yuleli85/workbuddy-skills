---
name: frontend-light-theme-lock
description: 让前端「默认样式风格固定成指定亮色主题，不随操作系统/浏览器的深色模式变化」（Vue + Element Plus / Tailwind 技术栈优先）。当用户说「设置默认的样式风格」「不要随安装/操作系统变化」「系统默认蓝白色」「关闭跟随系统深色模式」「页面在别人电脑上变黑了」「一装到深色系统的客户机就变样」时使用。覆盖 4 个独立成因——useDark 的 auto 初值（含被持久化到 localStorage 的存量）、CSS color-scheme + light-dark() 跟随系统、服务端模板硬编码 dark、tailwind darkMode 类；并给出 Playwright 深色模拟 + A/B 反事实的验收方法（含免验证码登录）。
agent_created: true
---

# 固定前端默认主题（不跟随系统深浅色）

用户说"默认蓝白色""不要随系统变化"时，**真实诉求是**：默认外观在任何机器上都一致，
并且不读 `prefers-color-scheme`。

## 核心原则

**"跟随系统"从来不是一个开关，而是 4 个彼此独立的来源。漏掉任何一个，用户都会在某台机器上看到深色。**
而且其中两个来源带有**存量状态**（已写进用户浏览器），"只改代码"必然治不好老用户。

| # | 来源 | 判据（怎么找） | 症状 |
|---|------|-------------|------|
| 1 | `@vueuse/core` 的 `useDark()` 初值 `'auto'` | `grep -rE "useDark\(" src`（**每一个调用点**都要查，同一页面常有多处） | 首帧闪深色；深色系统上持续深色 |
| 2 | 同上的 **localStorage 存量** | `useDark` 底层是 `useStorage('vueuse-color-scheme', initialValue)`，初值会被**写进 localStorage** | 改了 `initialValue` 仍无效（老用户浏览器里已经是 `'auto'`） |
| 3 | CSS `color-scheme: light dark` + `light-dark()` | `grep -rE "color-scheme\|light-dark\(" src` | 该**局部子树**（常是移植/换肤页）整块变深，与宿主主题打架 |
| 4 | 服务端模板 / 静态页硬编码 | `grep -rn "class=\"dark\"\|matchMedia\|prefers-color-scheme" src templates *.html` | 某些页面（认证页、安装页、警告层）一直是深色 |

另需确认 `tailwind.config.js` 的 `darkMode: 'class'`（若是 `'media'`，则所有 `dark:` 工具类都跟随系统，**必须改成 `'class'`**）。

## 修法（每层的正确落点）

### 第 1+2 层：必须**成对**存在，缺一不可

**(a) `index.html` `<head>` 首帧前内联脚本** —— 处理存量存储，且避免闪烁：

```html
<!-- 默认主题：亮色。固定不跟随操作系统深色模式；清理 @vueuse 历史遗留的 'auto' 值 -->
<meta name="color-scheme" content="light"/>
<script>
	(function () {
		try {
			if (localStorage.getItem('vueuse-color-scheme') === 'auto') localStorage.setItem('vueuse-color-scheme', 'light');
		} catch (e) {}
		var el = document.documentElement;
		el.classList.remove('dark');
		el.setAttribute('data-theme', 'light');
		el.style.colorScheme = 'light';
	})();
</script>
```

> 为什么必须放 `<head>`：这是**唯一**在 Vue 启动前执行的位置。放在组件里 = 已经渲染过一帧深色。

**(b) 所有 `useDark()` 加初值**：`useDark({ initialValue: 'light' })`。
`initialValue` 只影响"键不存在时写什么默认值"，所以 **只有 (a) 能救存量**。

若主题真源在状态管理里（如 `themeConfig.isDark`），保持它作为用户**主动**切换的唯一出口；
不要为了"钉死"而删掉手动切换（除非用户明确要求），默认值才是这次的诉求。

### 第 3 层：`light-dark()` 的解析看**最近的 `color-scheme`**

`light-dark(a, b)` 取 `a` 还是 `b`，取决于**该元素生效的 `color-scheme`**。
一处 `color-scheme: light dark` 就等于"跟随系统"。

- 根上写 `:root{color-scheme:light}` 只能管到根，**局部容器自己声明的会覆盖它**。
- ⚠️ **生成器陷阱**：若产物由脚本生成，而脚本只是「在文件头部追加一句 `X{color-scheme:light}`」，
  会被后面同特异性的原型基线规则**按后写覆盖先写** ⇒ 形同虚设。
  正确做法是在生成器里做归一化（保留显式的 `[data-theme=dark]` 暗色规则）：

```js
root.walkDecls('color-scheme', (decl) => {
	const sel = decl.parent && decl.parent.selector ? decl.parent.selector : '';
	if (sel.includes('[data-theme')) return; // 显式主题规则不动
	if (decl.value.includes('dark')) decl.value = 'light';
});
```

- 生成器的源文件可能已不在仓库（如 `output/proto.css` 被忽略）⇒ 无法重跑时，
  对产物做**单点**修改，同时在生成器里补上同一处理，避免下次重跑被打回。

### 第 4 层：服务端模板 / 静态页

- `<html class="dark">` 硬编码 = 页面上来就是深色；`matchMedia('(prefers-color-scheme: dark)').matches`
  分支 = 跟随系统。删掉分支，只认用户的显式选择。
- **先确认它可达**：Java 项目里查有无 `@Controller` / 视图名引用；**没有任何引用的 ftl/模板是死代码**，
  改了不生效也不该算交付（要么留着，要么明确告知用户）。

## 验收（不做 A/B 就不算验证）

用 Playwright（`playwright-core` + 本机已装的 Chromium 缓存即可，无需重装浏览器）：

```js
const ctx = await browser.newContext({ colorScheme: 'dark' });     // ① 模拟操作系统深色
await ctx.addInitScript(() => {                                     // ② 最坏情况：存量 auto
	try { localStorage.setItem('vueuse-color-scheme', 'auto'); } catch (e) {}
});
```

必须断言的三条（缺一条就不算过）：

1. `matchMedia('(prefers-color-scheme: dark)').matches === true` —— 证明**深色模拟真的生效**（否则测了个亮色环境，白测）；
2. `<html>` **无 `dark` 类**、`data-theme=light`、计算样式 `color-scheme: light`；
3. 关键元素的 `background-color` / `color` 是亮色（如 `rgb(248,250,252)` 配 `rgb(15,23,42)`）。

**A/B 反事实**（证明"故障模式真实存在"，否则说服力不足）：
在同一页面手工 `classList.add('dark')` + `data-theme='dark'` + `color-scheme:dark`，
再读一次背景色 —— 若立刻变成深色，说明这个类/属性正是病根，而现在已经把它钉死。两张截图并列交付。

**需要登录才能看到的页面**：不要硬解滑块验证码。
走接口拿一个真令牌（项目里通常有 `tools/pig_token.py` 之类"探活 + 重登"的工具），
再把它注入为 **cookie**（前端请求拦截器多数直接从 cookie 读 token）：

```js
await ctx.addCookies([{ name: 'token', value: TOKEN, url: 'http://localhost:8888' }]);
```

## 反模式

- ❌ 只改 `useDark()` 的 `initialValue`（存量 `'auto'` 还在，老用户照旧深色）。
- ❌ 在 `App.vue` / 组件 `onMounted` 里"补一刀"（首帧已经闪过了；深色系统上肉眼可见）。
- ❌ 用 `!important` 提高优先级硬压 `color-scheme`（说明有另一个来源没找到）。
- ❌ 只测一台浅色机器就宣布修好（这个 bug 的特性就是"在我这看不出问题"）。
- ❌ 交付时不说明"哪端因不在本机运行/无依赖而未构建"（用户会以为全都生效了）。
