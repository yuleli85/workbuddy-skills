---
name: electron-desktop-ci-packaging
description: 给 Electron / electron-builder 桌面工程搭「CI 出安装包」流水线（GitHub Actions 或 Jenkins），尤其要出 macOS dmg 时使用。覆盖：mac 包只能在 macOS runner 上构建的硬约束与 runner 选型、Action 版本 pin 的 node24 门槛（pin 错会启动即失败）、GitHub 表达式与 gh CLI 的静默坑、产物验收脚本的平台自适应改造、以及用本机实跑先把 CI 风险清掉的方法。触发词：GitHub Actions 打包 / 打 mac 安装包 / 打包 dmg / 桌面客户端安装包 / electron-builder CI / macos runner / Actions 一启动就失败 / Node.js 20 is deprecated / upload-artifact 版本 / verify-package 在 mac 上红。
agent_created: true
---

# Electron 桌面工程 · CI 出安装包（macOS 为重点）

面向 electron-builder 工程（本仓 = `pig-pc-ui/desktop` 灵猫企管PC版）+ Jenkins 或 GitHub Actions。

## 0. 先定位「哪个工程支持 mac」

别猜。**看 scripts 和打包配置**：

```bash
grep -n 'dist:mac\|--mac' */desktop/package.json        # 有 dist:mac 的才支持
grep -n '^mac:' -A 15 */desktop/electron-builder.yml    # 无 mac 段 = 不支持
```

本仓实测：`pig-ui/desktop` **完全没有** mac 支持（无 `dist:mac`/无 mac target/无 mac 段）⇒ 唯一目标 `pig-pc-ui/desktop`。
两个桌面壳的 `appId`/`productName` 刻意不同（可同时安装），别合并。

## 1. 硬约束：mac 包只能在 macOS 上构建

- dmg 依赖 macOS 自带的 `hdiutil` / `codesign` / `iconutil`；在 Linux/Windows 上 `electron-builder --mac` **直接报错退出**。
- 官方能力矩阵：macOS → 三项全能；Linux/Windows → 不能出 macOS 目标。官方 Docker 镜像也没有 mac 版 ⇒ `docker run` 这条路封死。
- ⇒ runner 必须 `macos-*`。**没有 Mac 时的绕法**（`@electron/packager` + `rcodesign`）**不建议**：产物在非 Apple 机器上跑不了，没有反馈回路（详见 `CI-PACKAGING.md` §9）。

## 2. runner / Action 版本（**最容易让 CI 一启动就红**）

### 2.1 runner 选型（2026-10 实测）

| label | 形态 | 说明 |
|---|---|---|
| `macos-latest` | macOS 26 / **arm64** / 3 vCPU / 7 GB / 14 GB 磁盘 | 默认选它；与 electron-builder 默认 `arch: arm64` 一致 |
| `macos-15-intel` / `macos-26-intel` | Intel / 4 vCPU / 14 GB | 需要 Intel 包或静态 UDID 时用 |
| ~~`macos-14`~~ | — | **2026-11-02 退役**，10 月有多个 brownout 窗口直接失败 ⇒ 别 pin |

费用：macOS runner **$0.062/分钟**（Linux 的 10×）。public 仓库免费不限量；private 消耗免费额度后计费。
⇒ **别配分支 push 触发**，只留 `workflow_dispatch` + tag。

### 2.2 Action pin 必须 ≥ node24（不是警告，是硬失败）

2026-09-23 起 GitHub runners **移除了 Node 20**：凡 `action.yml` 声明 `using: node20` 的 Action **在启动阶段失败**，无警告、无回滚开关。

**别信版本号大小，去读上游 action.yml**（2026-10-08 实测）：

| Action | node20（坏） | node24（好） |
|---|---|---|
| `actions/checkout` | v4 | **v5**（v6 也行，但 v6 改了凭据存放位置，非必要不跨大版本） |
| `actions/setup-node` | v4 | **v5** |
| `actions/cache` | v4 | **v5** |
| `actions/upload-artifact` | v4 **和 v5** | **v6** ← 反例！v5 仍是 node20 |

```bash
# 核实任意 Action 的运行时（一行）
curl -s "https://raw.githubusercontent.com/actions/<repo>/<tag>/action.yml" | grep -A3 '^runs:'
```

⚠️ `node-version: '22'`（setup-node 的输入）管的是**工程自己的** Node，与 Action 的运行时空无冲突，别误删。

## 3. GitHub Actions / gh 的三个静默坑

1. **表达式跨类型比较会强转数字**：`null → 0`、`false → 0` ⇒ `if: ${{ inputs.x != false }}`
   在 **tag 触发**（inputs 全为 null）时判为**假**，步骤被静默跳过。**手动输入的开关一律用 shell 默认值**：
   ```yaml
   env: { RUN_VERIFY: "${{ inputs.run_verify }}" }
   run: |
     [ "${RUN_VERIFY:-true}" = "false" ] && { echo 跳过; exit 0; }
     node scripts/verify-package.cjs
   ```
2. **`gh release create --target` 只吃完整 40 位 SHA**（`$GITHUB_SHA` 正是）。手动触发时 tag 还不存在，
   gh 默认从**默认分支 HEAD** 建 tag ⇒ 会指向错提交；tag 存在时该参数被 API 忽略（无害）。
3. **多行 `--notes` 不能直接写在 YAML 块里**：块缩进会被带进正文，Markdown 里 4 空格=代码块，Release 页跑版。
   用 `NOTES=$(printf '%s\n' "行1" "" "行2")` 拼。

另：清理 `NODE_OPTIONS`（`NODE_OPTIONS= npm run ...`）—— CI 若注入删除防护钩子（`--require`）会让打包中断。
只 stash/装依赖时**不要**给 mac 传 `electronDist=node_modules/electron/dist`（那是 Windows 专用的 rename 绕行，darwin 上找不到 `Electron.app` 直接报错）。

## 4. 产物验收脚本要做「平台自适应」

**典型必炸点**：`verify-package.cjs` 这类脚本硬编码 `release/win-unpacked/...`，在 mac 节点上跑必红
（Jenkins 的 mac 段同样会红，且往往从未在真机上跑过）。

两平台的解包结构完全不同：

```
win32   release/win-unpacked/resources/app.asar
darwin  release/mac-arm64/<产品名>.app/Contents/Resources/app.asar
```

改法（**保留 Windows 分支原样**，只加 darwin 分支）：

```js
const IS_MAC = process.platform === 'darwin';
function unpackedDir() {                     // release/mac-arm64 | mac | mac-universal
  const dirs = fs.readdirSync(RELEASE, { withFileTypes: true })
    .filter(e => e.isDirectory()).map(e => e.name);
  const hit = IS_MAC ? dirs.find(n => /^mac(-[a-z0-9]+)?$/.test(n)) : dirs.find(n => n === 'win-unpacked');
  ...
}
function resourcesDir() {                    // win32: <unpacked>/resources
  return IS_MAC ? path.join(unpackedDir(), `${PRODUCT_NAME}.app`, 'Contents', 'Resources')
                : path.join(unpackedDir(), 'resources');
}
```

`productName` 在 `electron-builder.yml` 里（不在 package.json）；产物名里的版本号**从 `package.json` 读**，别硬编码。
**改完必须证明未破坏 Windows 分支**：把新旧表达式算出的路径/产物名逐字比对（脚本比对即可）。

### 四个「拍脑袋会错」的 mac 断言

| 我一开始的假设 | 实测真相 |
|---|---|
| `.app` 主程序很大 | **只有 52 KB**（Mach-O 启动器）；Chromium 在 `Contents/Frameworks`，约 **285 MB** ⇒ 断言 Frameworks 体积 |
| 递归统计目录体积用 `statSync` 就行 | **必须跳过 symlink**：`.framework` 的 `Versions/Current` → 同一份二进制算两遍，285MB 虚报 **478MB**（用 `entry.isSymbolicLink()` 跳过 + `lstatSync`） |
| 只要文件存在就够 | 要**真验签名**：`codesign --verify --deep --strict <app>`；并断言 `mac.identity` 是 ad-hoc `'-'` 而非 `null`（写 null 会**静默跳过签名** ⇒ 用户端报「应用已损坏」） |
| Info.plist 不用看 | 断言 `CFBundleIdentifier` == `appId`（防止两个桌面端互顶） |

## 5. 用本机实跑先把 CI 风险清掉（关键一步）

CI 一轮十几分钟，本机 mac 跑一遍只要 2 分钟。**先在 Mac 上按 CI 的同一条命令跑通**：

```bash
export PATH="<受管 node>/bin:$PATH"
cd <工程> && npm install --no-audit --no-fund && npm run build      # 前端（若桌面壳依赖 dist）
cd desktop && NODE_OPTIONS= npm install --no-audit --no-fund
NODE_OPTIONS= npm run dist:mac -- --arm64                           # 与 workflow 逐字一致
node scripts/verify-package.cjs                                     # 改过的验收脚本
```

内网/慢网加速：`export ELECTRON_MIRROR=https://registry.npmmirror.com/-/binary/electron/`（实测 GitHub 直连 34 KB/s vs 镜像 5.8 MB/s）。

**顺手把两个容量问题量掉**（省得在 CI 上才发现）：

```bash
# 前端构建峰值内存（沙箱里 ps 常被拦，用 Node 自身 API）
# /tmp/mem-report.cjs: process.on('exit', () => appendFileSync('/tmp/peak.txt', 'PEAK_RSS_MB='+Math.round(process.resourceUsage().maxRSS/1024)+'\n'))
NODE_OPTIONS="--max-old-space-size=8192 --require /tmp/mem-report.cjs" node ./node_modules/vite/bin/vite.js build
```

实测结论（本仓）：`--max-old-space-size=8192` 只是上限，**真实峰值 2.06 GB** ⇒ 7 GB runner 够用；
磁盘 14 GB 上限 vs 实际占用约 2.5 GB（工作区 + node_modules + release + electron 缓存）⇒ 余量充足。

## 6. 收尾：产物去哪 + 文档要写清什么

- `actions/upload-artifact@v6`（`if-no-files-found: error`，**别让它静默出空包**），保留 30 天；
  要长期下载链接就建 Release（手动 `--target $GITHUB_SHA`，或 tag 触发）。
- artifact 名用 **ASCII**（中文名在某些客户端下载异常）。
- 写进 `$GITHUB_STEP_SUMMARY`：文件名、体积、**SHA-256**、构建提交、runner 架构 —— 发给用户时可直接带上。
- 文档必须交代：① 3 步操作 ② 用户需确认什么（Actions 是否被禁用、仓库 public/private 决定花钱）③ 首次打开被拦怎么办（ad-hoc：右键打开 / `xattr -dr com.apple.quarantine`）④ 升级到签名+公证需要哪些凭据与改动点。
- 文档里**明确写没做的事**：autoUpdater（无 `publish` ⇒ 不生成 `latest.yml`，产物里 `.blockmap` 用不上）、Windows 包走谁、未签名。

## 7. 别用 `git add .` 提交打包产物

`build/icon.icns` 这类**生成物常常没进 `.gitignore`**（`.gitignore` 往往只放行了 `icon.ico`/`icon.png`）。
打完包后按**精确路径** add，否则会把几百 KB 二进制裹进提交。
