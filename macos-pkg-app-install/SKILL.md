---
name: macos-pkg-app-install
description: 在 macOS 上把图形应用（尤其 .pkg 安装包类型，如 Windows App / Microsoft Remote Desktop、Docker Desktop、企业客户端等）从命令行真正装好并验证启动，同时绕过三类必然踩到的拦截。当用户说「帮我安装 XX」「装个远程桌面 / RDP 客户端 / 客户端软件」「装个终端」「brew 装不上」「安装失败」「installer 报 package path specified was invalid」「Homebrew 报 Operation not permitted locks」「brew 报 You have not agreed to the Xcode license」「装个 dmg 应用 / 装个 Markdown 查看器」「双击 .md 不渲染 / 改默认打开方式 / 默认程序没变」时使用。覆盖：① 先确认需求指向（别急着装，RDP / SSH / VNC / 远程控制是四件事）；② Homebrew cask 写 locks 被沙箱拦 → 需要禁用沙箱重试；③ 禁止设 HOMEBREW_NO_INSTALL_FROM_API=0（会丢 cask 并触发 tap clone）；④ 用 formulae.brew.sh API 取官方 pkg 直链与 sha256，curl 下载 + 校验 + 验签；⑤ ~/Downloads 受 TCC 保护，提权后 installer 读不到 → 必须先移到 /Users/Shared；⑥ osascript `with administrator privileges` 弹系统授权框完成提权安装；⑦ 装完验证 .app 存在、读版本、启动；⑧ brew 被 **Xcode 许可门**整体拦死（`You have not agreed to the Xcode license`）的诊断，与「路径 B：.dmg 直取上游 release」（hdiutil 挂载/拷贝/卸载全免授权 + **`.app` 拷贝必须 `ditto`，`cp -R` 会在 `app.asar` 上「Operation not permitted」半途失败且 du 看不出、只有 `spctl` 报 `sealed resource is missing or invalid`** + `xattr` 去 quarantine + `lsregister` 注册 + 验签要用 `codesign --verify --deep --strict` 而非 `codesign -dv`）；⑨ 「路径 C：CLI tar.gz → `~/.local/bin`」；⑩ 「第 7 步：设为默认打开方式」——`duti -s` 后**必须 `killall -u $USER lsd`** 才生效（cfprefsd 不够，本机 macOS 26 实测），用于修「装了却仍用旧程序打开」「双击 .md 不渲染」。
agent_created: true
---

# macOS 图形应用（.pkg）命令行安装

## 第 0 步：先确认要装的是什么

macOS 上「远程终端」至少有四种完全不同的东西，装错等于白干：

| 用户意图 | 该装的 | Homebrew cask |
|---|---|---|
| RDP 连 Windows 图形桌面 | Windows App（原 Microsoft Remote Desktop） | `windows-app` |
| SSH 连服务器命令行 | Termius / Tabby / iTerm2（自带 ssh） | `termius` / `tabby` |
| VNC 图形桌面 | VNC Viewer | `vnc-viewer` |
| 双向远程控制 | RustDesk / AnyDesk / TeamViewer | `rustdesk` / `anydesk` / `teamviewer` |

**先问清楚再动手**，用 AskUserQuestion 给上面四类做选项（可多选）。
同时先探明环境，避免白装：

```bash
sw_vers; uname -m                      # 版本 + 架构（arm64 要原生包）
brew --version; which brew
xcode-select -p; /usr/bin/xcodebuild -version   # brew 是否被 Xcode 许可门拦（见「路径 B」）
ls /Applications | grep -iE 'remote|vnc|ssh|anydesk|teamviewer|iterm|tabby|warp'
ls ~/Applications 2>/dev/null          # 用户级安装位置（免 sudo 的落点）
df -h / | tail -1                      # 磁盘余量
```

已经装了同类应用（如 iTerm2、UURemote）要指出来，避免重复安装。

> ⚠️ **`/Applications` 和 `~/Applications` 两条路径都必须查。** 只 `ls /Applications` 会漏掉按「路径 B」
> 装到用户目录的那份，结果同一 App 装两遍（2026-10-15 就这样白下了 28 分钟的 Obsidian 1.14.4 dmg，
> 装完才发现 `~/Applications/Obsidian.app` 早就在）。查完再决定装不装。

## 第 1 步：确认 cask 名与最低系统版本

```bash
brew search --cask remote-desktop      # 模糊找候选
brew info --cask windows-app           # 看版本 / min_os / 安装器类型（Pkg 还是 App）
```

**注意**：旧 cask 名可能已被上游重命名（`microsoft-remote-desktop` → `windows-app`），
报 `No Cask with this name exists` 时先 `brew search --cask` 找新名，
再看 `Requirements: macOS >= xx` 是否满足本机版本。

## 第 2 步：取官方直链 + 校验值（关键，绕开 Homebrew）

Homebrew 的下载路径会写 `/opt/homebrew/var/homebrew/locks/`，在受限/沙箱环境里被拒：

```
Error: Operation not permitted @ apply2files - .../xxx.pkg.incomplete.download.lock
```

**不要**用 `HOMEBREW_NO_INSTALL_FROM_API=0` 去绕——那会强制 brew 放弃 API、去找本地 tap，
本地没有 `homebrew-core` 就报 `No Cask with this name exists`，接着 clone tap 又被沙箱拦，
比原问题更糟。Homebrew 7.x 默认走 API，正常情况就够了。

直接从 brew API 拿官方包地址（走网络，不碰本地文件）：

```bash
curl -s "https://formulae.brew.sh/api/cask/<cask>.json" -o /tmp/c.json
python3 -c "
import json; d=json.load(open('/tmp/c.json'))
print('version:', d['version']); print('url:', d['url'])
print('sha256:', d['sha256']); print('min_os:', d.get('depends_on',{}).get('macos'))"
```

## 第 3 步：下载 → 校验 → 验签（三步都不能省）

```bash
curl -L --progress-bar -o ~/Downloads/App_x.y.z_installer.pkg "<url>"
shasum -a 256 ~/Downloads/App_x.y.z_installer.pkg     # 必须与 API 的 sha256 完全一致
pkgutil --check-signature ~/Downloads/App_x.y.z_installer.pkg
```

验签要看到两条才算干净：
- `signed by a developer certificate issued by Apple for distribution`
- `Notarization: trusted by the Apple notary service`

并核对 `Developer ID Installer` 的发行方名称（如 `Microsoft Corporation (UBF8T346G9)`）。
sha256 不匹配或签名主体不对 → **立即停止**，不要安装，告知用户。

## 第 4 步：装前必须挪出 ~/Downloads（最大的坑）

macOS 的 TCC 保护 `~/Downloads`。`osascript ... with administrator privileges` 提权后，
root 进程**读不到** `~/Downloads` 里的 pkg，`installer` 会报一个极具误导性的错误：

```
installer: Error - the package path specified was invalid: '/Users/shan/Downloads/xxx.pkg'.
```

看到这句别怀疑路径拼错，**就是 TCC**。解法：

```bash
mv ~/Downloads/App_x.y.z_installer.pkg /Users/Shared/
```

`/Users/Shared` 不受 TCC 保护，root 可读。

> 反面信号：如果报的是 `User canceled` 或 `-128`，那是用户点了取消，不是权限问题。

## 第 5 步：提权安装（弹系统授权框）

`.pkg` 必须 root 安装。在沙箱/非交互环境里 `sudo` 直接不可用
（`operation not permitted: sudo`），用 osascript 触发**图形化密码框**，用户只需输一次密码：

```bash
osascript -e 'do shell script "/usr/sbin/installer -pkg /Users/Shared/App_x.y.z_installer.pkg -target /" with administrator privileges with prompt "安装 App 名称"'
```

- 这一步通常需要 `dangerouslyDisableSandbox: true`。
- 用**双引号**包裹内层命令，外层用单引号包 osascript 表达式。
- 成功输出：`installer: Installing at base path /` + `installer: The install was successful.`
- 跑在后台 + `TaskOutput` 阻塞等待，给足用户输密码的时间（超时 ≥300s）。

## 第 6 步：验证并启动

```bash
ls -d "/Applications/App 名称.app" && echo "已就位"
defaults read "/Applications/App 名称.app/Contents/Info.plist" CFBundleShortVersionString
open -a "App 名称"
```

装完主动告知用户安装包保留位置，并给出清理命令（别擅自删，让用户决定）：
`rm -f /Users/Shared/App_x.y.z_installer.pkg`

## 第 7 步：设为默认打开方式（duti + 必须重启 lsd）

装完 App **不会**自动接管文件关联 —— 用户双击 `.md` 仍会打开旧程序，这才是「装了却没用」的真正原因。
两条命令，但**第二条不能省**：

```bash
brew install duti                              # 一次性，88KB
duti -s <bundle-id> .md all                    # 例：duti -s md.obsidian .md all
duti -s <bundle-id> net.daringfireball.markdown all
killall -u "$(id -un)" lsd                     # ⚠️ 关键：不重启 lsd，改了也不生效
duti -x md                                     # 验证：应输出新 App 的名字 + 路径 + bundle-id
```

**本机实测（macOS 26.6.2）**：

- 只跑 `duti -s` 会返回 **exit 0**，并真的写进
  `~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist`
  （`plutil -p` 能看到 `LSHandlerRoleAll => md.obsidian`），
  但 `duti -x md` **依旧返回旧 App** —— 极易误判为「duti 不支持 macOS 26」而放弃。
- `killall -u $USER cfprefsd` **不够**（刷了 plist 缓存但 lsd 仍用旧值）；必须重启 **lsd**。
- 实在不行才用 `lsregister -kill -r -domain local -domain system -domain user` 重建库（重，最后手段）。
- 先查冲突者：`lsregister -dump | awk '/^path:/{p=$0} /net\.daringfireball\.markdown/{print p}' | sort -u`
  —— 本机当年占着 `.md` 的是第三方 **NotePad**（`com.netgensoft.textnote`，纯文本编辑器，不渲染 Markdown）。

## 路径 B：.dmg 应用（brew 不可用时的正路）

**先判 brew 是否被 Xcode 许可门整体拦死**（2026-10-13 本机实测）：

```
Error: You have not agreed to the Xcode license. Please resolve this by running:
  sudo xcodebuild -license accept
```

`brew install` 与 `brew config` **一律**报这句，与「写 locks 被拦」是两回事。诊断三步：

```bash
xcode-select -p                        # = /Applications/Xcode.app/Contents/Developer ⇒ 完整版 Xcode
/usr/bin/xcodebuild -version           # ⚠️ 可能**正常输出** Xcode 27.0 —— 别据此判定许可已 accept
DEVELOPER_DIR=/Library/Developer/CommandLineTools brew config   # ❌ 无效
#    CLT 的 xcodebuild 报 "requires Xcode, but active developer directory ... is a command line tools instance"
sudo -n true                           # 需密码 ⇒ 沙箱内无法自行 accept
```

- **根治**：让用户在**自己的终端**跑一次 `sudo xcodebuild -license accept`（AI 侧 sudo 需密码，做不到）。
- **当天要干活就绕过**：不碰 brew / xcrun，直接走上游 release。本次实测沙箱内全链路可用。

```bash
# ① 取最新版本资产（GitHub API，无需 token）
curl -s https://api.github.com/repos/<owner>/<repo>/releases/latest | \
  /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -c "
import sys,json; d=json.load(sys.stdin); print(d['tag_name'])
[print(a['name'], a['browser_download_url']) for a in d['assets'] if a['name'].endswith(('.dmg','.zip'))]"

# ① 取最新版本资产 + **校验值**（官网上有 .dmg 直链就用官网；有 brew cask 就用 brew API 拿 sha256）
curl -s https://api.github.com/repos/<owner>/<repo>/releases/latest | \
  /Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -c "
import sys,json; d=json.load(sys.stdin); print(d['tag_name'])
[print(a['name'], a['browser_download_url']) for a in d['assets'] if a['name'].endswith(('.dmg','.zip'))]
# 若该 App 也是 brew cask：curl -s https://formulae.brew.sh/api/cask/<name>.json ⇒ version/url/sha256"
# 官方文档页往往内嵌 CDN 直链，直接扒（比翻页面快，且拿得到真实版本号）：
#   curl -sL "<官方 install 页 URL>" | grep -oE 'https://[^"'"'"' ]+\.(dmg|zip)' | sort -u

# ② 下载 → 校验 → 挂载 → 拷贝 → 卸载（hdiutil 不需要授权）
curl -fL --retry 3 --retry-delay 2 -o ~/Downloads/x.dmg "<dmg_url>"
shasum -a 256 ~/Downloads/x.dmg                            # 必须与 brew API / 官方发布的 sha256 完全一致
hdiutil verify ~/Downloads/x.dmg                           # 要看到 checksum is VALID
hdiutil attach ~/Downloads/x.dmg -nobrowse                 # 记下 /Volumes/<卷名>
ditto "/Volumes/<卷名>/Xxx.app" /Applications/Xxx.app      # ⚠️ 必须 ditto，别用 cp -R（见下）
hdiutil detach "/Volumes/<卷名>" || hdiutil detach "/Volumes/<卷名>" -force   # 报「资源忙」就加 -force
xattr -dr com.apple.quarantine /Applications/Xxx.app       # 网络下载必带，清掉免 Gatekeeper 拦
```

- 🔴🔴 **拷贝 `.app` 必须用 `ditto`，`cp -R` 会在 Electron 大包上静默半途失败**（2026-10-16 装 ZCode 实测）：
  ```
  cp: /Applications//Xxx.app/Contents/Resources/app.asar: Operation not permitted
  ```
  `cp -R` 报这一句后**仍是 exit 1、但已拷进去大半个 bundle**，此时 `du -sh` 看着像成功了；
  只有 `spctl` 会戳穿它（`a sealed resource is missing or invalid`）。
  **判据：`du -sh 源 目标` 必须完全相等**（本次 772M vs 772M，`app.asar` 340515749B 两边一致）。
  ```
  ditto "/Volumes/<卷名>/Xxx.app" /Applications/Xxx.app    # 正确
  ```
- 装到 **`/Applications` 还是 `~/Applications`**：先判可写性 —— `[ -w /Applications ] && echo 可写`。
  **admin 用户的 `/Applications` 通常是可写的（实测本机 macOS 26.6.2 可写，无需 sudo）**，可写就装
  `/Applications`（与用户预期一致、Launchpad 直接可见）；不可写才落 `~/Applications`（用户可写，
  同属 LaunchServices 索引范围，Spotlight 与 Finder「打开方式」都认，本机 LibreOffice 就是这么装的）。
  两条路径装前都要 `ls` 查一遍，别重复装。
- 注册一次，让双击关联生效：
  ```bash
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/Xxx.app
  ```
- 🔴 **验签必须用「校验」而不是「打印」**：`codesign -dv` **只打印签名信息、不校验封签** ——
  半截拷贝的 bundle 一样能打出正常的 `Authority=...`，会骗过你。两条都要跑：
  ```bash
  codesign --verify --deep --strict --verbose=2 /Applications/Xxx.app  # 期望 valid on disk + satisfies its Designated Requirement
  spctl -a -vvv -t exec /Applications/Xxx.app                          # 期望 accepted / source=Notarized Developer ID / origin=...
  ```
- 启动验证：`open -a /Applications/Xxx.app; sleep 8; pgrep -fl Xxx`（Electron 应用会起一串 Helper 子进程，属正常）


## 路径 C：CLI 二进制（tar.gz，免编译）

`<name>_<ver>_Darwin_arm64.tar.gz` → `tar -xzf` → `install -m 755 .../bin/<name> ~/.local/bin/`
→ `xattr -d com.apple.quarantine ~/.local/bin/<name>` → `<name> --version`。
（`~/.local/bin` 本机已在 PATH 前部，且是既有 CLI 软链的落点。）

## 排查速查

| 症状 | 真因 | 处置 |
|---|---|---|
| `You have not agreed to the Xcode license`（brew 全命令都报） | 完整版 Xcode 已装但许可未 accept | 用户在本人终端跑 `sudo xcodebuild -license accept`；当天改走「路径 B」 |
| 网络下载的 .app 启动被 Gatekeeper 拦 | 带 `com.apple.quarantine` | `xattr -dr com.apple.quarantine <app>`；先 `spctl -a -t exec` 验签 |
| `Operation not permitted @ apply2files ... .lock` | 沙箱拦 Homebrew 写 locks | 禁沙箱重试；或改走手动下载 |
| `No Cask with this name exists`（此前 info 能查到） | 误设了 `HOMEBREW_NO_INSTALL_FROM_API=0` | 去掉该环境变量，回到 API 模式 |
| `could not write config file .../homebrew-core/.git/config` | 强制本地 tap 后 clone 被拦 | 同上，别碰 tap |
| `the package path specified was invalid` | TCC 挡住 `~/Downloads` | 移到 `/Users/Shared` 再装 |
| `cp: .../app.asar: Operation not permitted`（`.app` 拷到一半） | `cp -R` 在 Electron 大 bundle 上失败（dmg 卷 `noowners` + 大文件） | 改 `ditto`；用 `du -sh 源 目标` 比体积、`spctl` 戳穿半截拷贝 |
| `spctl: a sealed resource is missing or invalid` | bundle 拷贝不完整（**不是签名坏了**） | 删掉重来，用 `ditto`；别去动签名 |
| `hdiutil: couldn't unmount ... 资源忙` / `resource busy` | 还有进程/句柄占着卷（Finder、刚 mount 完的 `ls`、`open` 过里面的 app） | 先 `hdiutil detach "<卷>"`，失败再加 `-force`（会 eject）；确认 `mount \| grep -c <卷名>` = 0 |
| 卷已 eject，`/Volumes/<卷名>` 却还在 | `-force` 后残留空挂载点 | 无害；重挂同版本 dmg 会用同一卷名 |
| `operation not permitted: sudo` | 沙箱内 sudo 不可用 | 改 `osascript ... with administrator privileges` |
| `User canceled` / `-128` | 用户取消了授权框 | 重跑一次，确认用户会点授权 |
| 提示 `macOS >= xx` 不满足 | 系统版本低 | 换旧版 cask 或去 App Store 装 |
| `duti -s` 返回成功但 `duti -x` 仍是旧 App | 改的没被 lsd 重新加载 | `killall -u "$(id -un)" lsd`（cfprefsd 不够）后再验 |
| 启动台出现两个同名 App | `/Applications` 与 `~/Applications` 各装了一份 | 保留一份，卸载**自己刚装的**那份（`brew uninstall --cask <名>`），别删用户原有的 |
| 双击 .md 打开的是纯文本、没有渲染 | 默认程序被第三方 note 类 App 占着（本机是 NotePad） | 按「第 7 步」改绑到 Markdown 阅读器 |

## 备选方案（主路径都不通时）

1. **Mac App Store**：Windows App / 多款远程客户端都在商店上架，图形化安装最省事。
2. **手动双击安装**：`open ~/Downloads/xxx.pkg` 打开安装向导，让用户点完（无需命令行权限）。
3. **纯命令行替代**：不想装 GUI 时，`brew install --cask freerdp` 提供 `xfreerdp` CLI 连 RDP。
