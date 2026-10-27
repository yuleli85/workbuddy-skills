# 网页系统自动化测试技能（web-autotest）

给 AI 编程工具（Claude Code 等支持技能的工具）用的自动化测试技能，也可以直接当命令行工具用。

能做三件事：
1. **菜单巡检**：自动找出系统里所有菜单（支持 Element、Ant Design、Arco、Naive、iView 等常见后台，也能从菜单接口取），逐个点开，查：页面打不开、页面程序报错、接口返回 4xx/5xx、接口回 200 但业务错误码不对、弹出错误提示、显示 404 等错误页、空白页、打开慢。每页截图。
2. **接口检查**：页面实际调到的所有接口自动汇总成清单（状态码、最慢耗时、出错次数、在哪些页面调的）；有接口文档的，把查询类接口逐个调一遍；再用接口用例测规则。
3. **功能逻辑**：用简单的 YAML 写用例（接口调用、页面点击填写、各种判断），验证增删改查、校验、筛选、排序、计算、状态流转、权限这些规则对不对。

结果出一份 HTML 报告（浏览器直接打开），另有 results.json（明细）和 junit.xml（给流水线）。

## 安装

要 Node 18 以上。

```bash
cd web-autotest
npm install
npx playwright install chromium
```

浏览器下载慢的话，先设镜像再装：
- Windows PowerShell：`$env:PLAYWRIGHT_DOWNLOAD_HOST="https://registry.npmmirror.com/-/binary/playwright"`
- Mac / Linux：`export PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright`

或者不下浏览器，在测试配置里写 `browser: { channel: chrome }` 用本机装的 Chrome。

装好跑 `npm run demo` 看效果：会起一个故意埋了 6 处问题的演示后台（接口 500、页面程序报错、业务错误码、打开慢、404 页、筛选逻辑错），测完报告在 `examples/演示系统/autotest-report/demo/report.html`，6 处都应查出来。

## 放进 AI 工具

把整个 `web-autotest` 文件夹放进工具的技能目录，例如 Claude Code：
- 只给自己用：`~/.claude/skills/web-autotest/`
- 跟项目走：`项目/.claude/skills/web-autotest/`

然后跟 AI 说「用自动化测试技能把 http://测试环境地址 的所有菜单和接口测一遍」「给用户管理写功能用例」即可。AI 会照 SKILL.md 的步骤：问清地址和账号 → 生成配置 → 先跑菜单巡检 → 根据实际接口和需求写用例 → 跑完交问题清单。

## 自己用命令行

```bash
node scripts/autotest.js init autotest                       # 在项目里生成配置和用例模板
# 改 autotest/测试配置.yaml 里的地址、登录方式
export TEST_USER=测试账号 TEST_PASSWORD=密码                  # 账号别写进文件
node scripts/autotest.js run autotest/测试配置.yaml          # 全跑
node scripts/autotest.js run autotest/测试配置.yaml --only menus   # 只巡检菜单
```

全部写法：`references/写法.md`。用例怎么设计：`SKILL.md` 第 4 节。示例：`examples/演示系统/`（演示后台的配置和用例，可照着写）。

## 文件

```
SKILL.md                 给 AI 看的使用步骤和用例设计方法
README.md                本说明
references/写法.md        配置、步骤、判断、选择器的全部写法
scripts/autotest.js      命令入口
scripts/lib/             菜单巡检、接口、用例执行、报告
templates/               init 生成的配置和用例模板
examples/演示系统/        演示后台（server.js）和它的配置、用例
```
