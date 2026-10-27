---
name: daily-agent-digest-local-package
description: 在 mac 上把 daily-agent-digest 从当前工作区重新打包成可安装客户端（菜单栏 App + DMG + onefile 引擎），不需要 GitHub Actions 与 Apple 开发者证书。当用户说「重新打包一个客户端」「打个包」「本地出个安装包」「重新构建 App」「打包 DMG」「让改动在客户端里生效」时使用。内含隔离 venv 装 PyInstaller、onefile/onedir 双引擎、App 包内引擎断言、版本号必须可被 Swift 解析、以及沙箱下 --app-command 会被 SIGKILL 等坑。
agent_created: true
---

# 本地重新打包 daily-agent-digest 客户端（macOS）

**仓库**：`/Users/shan/work/daily-agent-digest`
**目标**：把当前工作区的引擎 + Swift 菜单栏 App 打成 `dist/` 下的安装包，**不依赖 CI、不依赖 Apple 证书**。

## 三条铁律

1. **别改源码来打包**。打包只是构建；如果引擎有未提交改动，产物就带着它 —— 打完包要在说明里写明 `git_commit` 与 dirty 状态。
2. **App 包里必须是 onedir 引擎**。App 的每个菜单动作都新起一个进程：onefile 每次要解包再 exec（3–6s），onedir 0.03–0.3s。放错布局的表现是"点一下转好几秒"。
3. **打完必须回验**，不能只看"build completed"：`--engine-path` 要指向包内 onedir；引擎真跑一次采集；DMG 要挂载后校验。

## 首选路径：一条命令跑完（`scripts/build-dmg.sh`）

仓库里已经有把下面全部步骤封好的脚本，**不要再手抄 §1–§4**：

```sh
cd /Users/shan/work/daily-agent-digest && mkdir -p .build/tmp .build/pyinstaller-cache
TMP=/tmp DIGEST_RELEASE_VERSION=v0.7.1-dev \
  DIGEST_BUILD_VENV=/Users/shan/.workbuddy/binaries/python/envs/digest-build \
  bash scripts/build-dmg.sh
```

它按顺序做：跑协议测试 → PyInstaller onedir 引擎 → Swift App → ad-hoc 签名 → **断言 App 解析到包内引擎并真跑一次** → 建 DMG → 挂载校验 DMG。产出 `dist/Daily Agent Digest.app` 与 `dist/Daily-Agent-Digest-<版本>-arm64.dmg`（注意 App 名字**不带 arm64**）。

两个坑：

- **`hdiutil create` 需要非沙箱**：它会往 `/Volumes/<卷名>` 写。在受限/沙箱环境里会失败在最后一步，报 `hdiutil: create failed - 操作不被允许`（**前面全部已成功**：引擎、App、签名、包内引擎回验都过了）。重跑时放开沙箱即可，不必重做前面的步骤。
- **`TMP=/tmp` 必须传**：`native/macos/build.sh` 里用了未定义的 `$TMP`（见下方坑）。
- `DIGEST_BUILD_VENV` 指向现成的隔离 venv 可跳过建 venv；不传就用 `$ROOT/.build/venv`（脚本自己会装 PyInstaller 6.16.0）。

**版本号**：脚本默认 `v0.6.8`，**显式传** `DIGEST_RELEASE_VERSION`。用「最新 tag +1 再缀 `-dev`」（如 `v0.7.1-dev`），既能被 Swift 解析成 `[0,7,1]`，也不至于被 App 的「检查最新版本」当成正式发布。

## 步骤

### 0. 前置（每次会话只需一次）
PyInstaller 装在隔离 venv，**不要**装进系统 python：

```sh
VENV=/Users/shan/.workbuddy/binaries/python/envs/digest-build
[ -x "$VENV/bin/python" ] || /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -m venv "$VENV"
"$VENV/bin/pip" install -q "pyinstaller==6.16.0"   # 与 CI 对齐
```

先跑测试，避免把坏代码打进包：`python3 -m unittest discover -s tests`（源码引擎用系统/托管 python 都行）。

### 1. 引擎两份
```sh
cd /Users/shan/work/daily-agent-digest && rm -rf dist && mkdir -p dist
PY=/Users/shan/.workbuddy/binaries/python/envs/digest-build/bin
"$PY/pyinstaller" --onefile --name daily-agent-digest-macos-arm64 \
  --distpath dist --workpath /tmp/dag-work-onefile --specpath /tmp/dag-spec-onefile daily_agent_digest.py
"$PY/pyinstaller" --onedir  --name daily-agent-digest \
  --distpath dist/engine-arm64 --workpath /tmp/dag-work-onedir --specpath /tmp/dag-spec-onedir daily_agent_digest.py
```
- `--workpath` / `--specpath` **必须各自独立**，否则第二次会撞上第一次的中间产物和同名 `.spec`。
- 引擎是纯标准库，构建很快（10 秒级）。
- **注意 onedir 的产物是个目录**：真正可执行文件在 `dist/engine-arm64/daily-agent-digest/daily-agent-digest`。

### 2. App 包
```sh
SHA=$(git rev-parse --short HEAD); VERSION=v0.6.8-dev   # 版本号见下方"版本号"
APP="dist/Daily Agent Digest arm64.app"
TMP=/tmp DIGEST_RELEASE_VERSION="$VERSION" DIGEST_UI_BUILD_ID="$SHA" \
  DIGEST_ENGINE_BIN="$PWD/dist/daily-agent-digest-macos-arm64" \
  bash native/macos/build.sh "$APP"
mkdir -p "$APP/Contents/Resources/engine"
ditto dist/engine-arm64/daily-agent-digest "$APP/Contents/Resources/engine"
"$APP/Contents/MacOS/DailyAgentDigest" --engine-path   # 必须输出 .../Contents/Resources/engine/daily-agent-digest
"$APP/Contents/MacOS/DailyAgentDigest" --self-test | tail -3
```

**坑**：
- `build.sh` 里用了未定义的 `$TMP`（只在 `AppIcon.icns` 需要重建时才会展开）→ 显式传 `TMP=/tmp`，否则某天源图变新时会以 `TMP: unbound variable` 失败。
- 图标源图必须存在（`native/macos/assets/app-icon-1024.png`），否则 build.sh 直接 exit 1。
- 模块缓存已由脚本指向 `/tmp/dag-clang-modcache`；Swift 与 Clang 是两套缓存，受限环境下别自己改回去。
- **版本号必须能被 Swift 解析**：`DailyAgentDigest.swift:versionNumbers()` 按 `.` 切分取数字前缀，`v0.6.8-dev` → `[0,6,8]` 可比较；纯 `local-abc123` 会被判成"开发构建，无法比较"，"检查最新版本"会说不出人话。以最新 tag 为基准 +1 再缀 `-dev` 最稳。

### 3. 打包 zip / DMG
```sh
rm -rf /tmp/dag-dmg-stage && mkdir -p /tmp/dag-dmg-stage
ditto -c -k --keepParent "$APP" "dist/Daily-Agent-Digest-arm64-app.zip"
ditto "$APP" "/tmp/dag-dmg-stage/Daily Agent Digest arm64.app"   # 用 ditto 而非 cp -R，保住扩展属性
ln -s /Applications /tmp/dag-dmg-stage/Applications
hdiutil create -volname 'Daily Agent Digest' -srcfolder /tmp/dag-dmg-stage -ov -format UDZO \
  "dist/Daily-Agent-Digest-arm64.dmg"
cp install.sh dist/install.sh
(cd dist && shasum -a 256 daily-agent-digest-macos-arm64 Daily-Agent-Digest-arm64-app.zip Daily-Agent-Digest-arm64.dmg > SHA256SUMS)
```

### 4. 回验（少一步都别交付）
```sh
# (a) 打包后的引擎在真实 HOME 上采集结果与源码引擎"程序化"逐源比对 —— 不要靠肉眼看
D=$(date +%F)
env -u LLM_BASE_URL -u LLM_API_KEY -u LLM_MODEL DIGEST_HOME=/tmp/dag-pkg \
  "dist/Daily Agent Digest arm64.app/Contents/Resources/engine/daily-agent-digest" \
  --date "$D" --root "$HOME" --out /tmp/pkg.json
env -u LLM_BASE_URL -u LLM_API_KEY -u LLM_MODEL DIGEST_HOME=/tmp/dag-src \
  python3 daily_agent_digest.py --date "$D" --root "$HOME" --out /tmp/src.json
python3 - <<'PY'
import json
def snap(p):
    c = json.load(open(p))['coverage']
    return c['providers'], c['events'], {n: (st.get('prompt',0), st.get('result',0), st.get('deliverable',0))
                                         for n, st in c['collect'].items()}
a, b = snap('/tmp/pkg.json'), snap('/tmp/src.json')
print('打包', a[0], a[1], '| 源码', b[0], b[1], '| 逐源一致:', a[2] == b[2])
PY
# (b) 挂载 DMG，校验 Applications 快捷方式 + 包内引擎 + engine-path
MP=$(mktemp -d); hdiutil attach dist/Daily-Agent-Digest-arm64.dmg -mountpoint "$MP" -nobrowse -quiet
[ -L "$MP/Applications" ] && test -x "$MP/Daily Agent Digest arm64.app/Contents/Resources/engine/daily-agent-digest"
"$MP/Daily Agent Digest arm64.app/Contents/MacOS/DailyAgentDigest" --engine-path
hdiutil detach "$MP" -quiet
```
**采集条数不必是整数天全量**：`--date` 若为今天，结果会随当天真实会话变动；关键是"打包 = 源码"这个**等式**成立，而不是某个固定条数。
**`git_dirty` 别误报**：`git status --short` 里出现 `.workbuddy/`（工作区记忆目录）是**正常的**，不算代码 dirty —— 报出处时说明清楚，别让它看起来像"带着未提交代码打的包"。
再顺手跑一次 `bash native/macos/ui-smoke-test.sh`（真编译 Swift + 跑失败态映射自检）。

## 三个假故障（别当成真 bug）与一个真故障

### 真故障：从 DMG 装出来的 App，「每一个动作都失败」（`com.apple.quarantine`）

**这不是假故障，是本项目最容易被误判的一条**，2026-10-08 实测踩到：

从**网络下载**的 DMG 拖进 `/Applications` 后，整个 bundle **连同 `Contents/Resources/engine/daily-agent-digest`** 都会被打上隔离标记。用户点了「仍要打开」放行的是 **App 主程序**，而包内那个**嵌套引擎**没有这一段交互 —— 内核直接拒绝 exec（EPERM / `Operation not permitted`），`Process.run()` 抛错。表现：**App 能打开、设置窗口能出来，而每个菜单动作（设置/测试连接/生成/上传）都失败**。

判据（一行定性，比查地址密钥快得多）：

```sh
xattr -l "/Applications/Daily Agent Digest.app/Contents/Resources/engine/daily-agent-digest"
# 有 com.apple.quarantine → 就是它
# 决定性 A/B：同一个文件带这个属性 exec 报 EPERM，xattr -dr 之后立刻能跑
```

修法：

```sh
xattr -dr com.apple.quarantine "/Applications/Daily Agent Digest.app"
```

**已在源码侧堵缝**：`Backend.launchFailureDiagnosis()` 在 `Process.run()` 抛错时不再只透出
`localizedDescription`，而是说明「这不是地址/密钥的问题」、给出引擎路径与原始错误，并在检测到
`getxattr(...,"com.apple.quarantine")` 时直接打印那条 `xattr -dr` 命令（`--self-test` 有对应断言）。
写这段时注意：**`getxattr` 的第二参必须 `withCString`**，直接 `&String` 只会暴露内部表示。

**本地构建的 App 不带隔离标记**（不是从网络来的），所以「重新打一个本地包」本身就是一种修法 —— 但给别人的包一定要在交付说明里写清这条。

### 假故障三（最骗人）：`build/ui-smoke/*.app` 会冒充发布版

`native/macos/ui-smoke-test.sh` 会把 bundle 建在 `build/ui-smoke/Daily Agent Digest.app`，并在
`Contents/Resources/engine/` 放一个**占位引擎**（只为断言 `--engine-path` 选中包内 onedir）。
只要有人从 Finder / Dock / 最近使用点开这个 App，**每个菜单动作**（设置、测试连接、生成、上传）
都拿到**空输出**，界面显示的是：

> 连接失败：后端无响应

——挂在「连接失败」后面，于是所有线索都指向网络：改地址、换端口、查密钥、怀疑打包。
实测用户在这条路上绕了一整圈，真正的原因只是**点错了 App**。识别方法：

```sh
ps aux | grep -i DailyAgentDigest | grep -v grep     # 看实际在跑哪个 bundle 路径
ls -la "<在跑的那个>/Contents/Resources/engine/"     # 17 字节的 daily-agent-digest = 占位引擎
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "<在跑的那个>/Contents/Info.plist"  # smoke
```

已在源码两侧堵这条缝：`Backend.silentEngineDiagnosis()` 让「空输出」直接说明**不是网络/地址/密钥问题**
并带上引擎路径、退出码、App 版本（`.smoke` bundle id / 极小引擎文件都会被点名），多行诊断走弹窗
而非 2 行状态标签；占位引擎改成打印一句 JSON `error` 自报身份；bundle 里额外留
`Contents/Resources/SMOKE-BUILD-测试构建勿用.txt`。

**排查顺序（重要）**：用户报「连接失败」时，**先确认他跑的是哪个 .app**，再去碰地址和密钥。
正式版在 `/Applications/Daily Agent Digest.app`（`scripts/build-dmg.sh` 产出的名字，**不带 arm64**；
`dist/` 里新打的包同理。老文档里写的 `Daily Agent Digest arm64.app` 是 §2 手抄流程的旧命名）。

### 假故障一：`--app-command` 返回 137 (SIGKILL)

不是崩溃、也不是沙箱拦写：引擎会 `sys.stdin.read()` 读一次 JSON（App 总是写 `{}` 进来），
而在自动化工具里 stdin 常是一个**永不关闭的管道** → 一直阻塞 → 被上游杀掉。手工/脚本里跑一律写成
`echo '{}' | … --app-command state` 或 `… --app-command state < /dev/null`。

### 假故障二：`code signature invalid`

未签名的 arm64 二进制在 Apple Silicon 上必须至少有 ad-hoc 签名：PyInstaller 会自己 re-sign
（日志有 `Re-signing the EXE`）。**不要**手工 `codesign -s -` 去覆盖，除非确实报 `code signature invalid`。

## 顺带能验的事

打包后的客户端要验证「上传」链路时，本仓库没有后端，用 `scripts/dev_mock_submit.py`（零依赖、内存存储，
实现 `docs/backend-api.md` 的两个必需接口）：起在 `127.0.0.1:8790`，客户端「设置」里提交地址填
`http://127.0.0.1:8790`（**只填基地址**，客户端自己拼 `/api/v1/me` 与 `/api/v1/digests`）、Key 填 `dag_dev_test`。
命令行直连验证：`echo '{}' | DIGEST_HOME=<临时 home> DIGEST_SUBMIT_URL=http://127.0.0.1:8790 DIGEST_API_KEY=dag_dev_test python3 daily_agent_digest.py --app-command submit`（state 需 `report_status=ready`，否则会被拒绝上报）。

## 客户端「能用」的验收口径（客户端全绿 ≠ 能用）

用户说「配置好了还是不能用」时，把这条链**逐段**验，别只看一段：

```sh
H="$HOME/Library/Application Support/Daily Agent Digest"          # 所有配置/状态都在这里
sed 's/\(API_KEY="sk-[^-]*-\).*/\1***"/' "$H/.env"               # LLM_* 与 DIGEST_* 共用一个 0600 的 .env
E="/Applications/Daily Agent Digest.app/Contents/Resources/engine/daily-agent-digest"
printf '{}' | "$E" --app-command settings      # ① 设置窗口读到的配置(报「读取配置失败」的那次调用)
printf '{}' | "$E" --app-command check-submit  # ② 密钥校验(走 {基地址}/admin/api-key/verify,只读不写库)
printf '{}' | "$E" --app-command generate      # ③ 真采集 + LLM 归并(report_status 应为 ready)
printf '{}' | "$E" --app-command submit        # ④ 真上报
```

- **② 绿 ≠ ④ 绿。** 校验接口只证明「地址可达 + 密钥有效」，**不校验密钥的应用编码**；上报接口会校验，
  于是出现「测试连接通过、一上传就 403」。实测原文：`HTTP 403: API 密钥的应用编码应为 work-log，当前为 yrd`。
  ⇒ 上报失败看 `submit_error` 原文，**别因为 ② 通过就回头怀疑客户端**。服务端侧处置见技能
  `linmo-openapi-apikey-triage`（改 `app_code` 字段即可，密钥串不变、业务系统零改动）。
- 用户给的提交地址**两种写法都行**（完整接口地址 / 基地址）：客户端用 `submit_base()` 把
  `/admin/enterprise/worklog/api/report` 剥掉再拼别的接口，所以直接粘贴「API密钥管理」页的授权 URL 也能用。
- `DeepSeek` 侧 `deepseek-flash` 等模型**两种基地址都通**（`https://api.deepseek.com` 与 `.../v1`）；
  引擎拼的是 `base + /chat/completions`。测真连通性时注意 `max_tokens` 给小了会全被 `reasoning_content` 吃掉、
  `content` 为空 —— 那是模型的思考段，不是接口坏了。
- **别用假 HOME 试完就交付**：`--app-command settings`/`generate` 我会写成临时 `DIGEST_HOME` 试，
  但注意 `save-settings` 会在**真实的**数据目录建 `.env`/`state.json`。交付前把排查期产生的
  脏 `state.json`（`last_error: unknown app command` 之类）清掉，再写正式配置。
- **GUI 起没起来**：`pgrep -fl DailyAgentDigest` 看进程与 bundle 路径。想看 `tray.debug.log` 需要
  `DIGEST_DEBUG=1`，但 `launchctl setenv` 在普通用户会话会报 `Not privileged to set domain environment`
  —— 日志拿不到时，用上面四条 CLI 等价验（同一个引擎、同一个数据目录）。

## 交付时要说明的三件事

1. **未签名/未公证**：本机构建无 quarantine，直接能跑；拷给别人的机器会被 Gatekeeper 拦（要正式发布必须走 `v*` tag 的 CI，带 Developer ID 证书）。**别人从下载的 DMG 装出来的 App 会包着 quarantine，包内引擎起不来 —— 见上文「真故障」，这是必须写进交付说明的一条。**
2. **设备架构**：本机 arm64，产物只对 arm64 有效；x86_64 要在 Intel 机器或 CI 上打。
3. **本机是否已装**：如果 `~/Library/Application Support/Daily Agent Digest` 与 `/Applications` 都没有副本，说明只是产出了安装包；安装是另一步（`install.sh` 走 GitHub release，本地包则直接把 .app 拖进 /Applications，或从 DMG 拖拽）。
