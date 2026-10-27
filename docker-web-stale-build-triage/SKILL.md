---
name: docker-web-stale-build-triage
description: 诊断并修复「Docker 化的前端工程改了代码却不生效 / 更新很慢 / 本地能 build 或 up 而 CI 挂」。当用户说「本地改了但服务没变」「刷新还是旧页面」「up --build 要等很久」「容器里跑的不是最新代码」「容器重建了但修复没生效」「docker ps 显示 healthy 但页面还是旧的」「改的配置文件没生效」「加了环境变量不生效」「容器里连不上宿主机的服务」「本地构建通过、CI 报 failed to compute cache key / not found」「CI 报 network … declared as external, but could not be found」时使用。覆盖六层独立成因——浏览器启发式缓存（含 nginx 缓存头的正确写法）、构建上下文臃肿、包管理器与 lockfile 错配、改了配置却没生效（仓库里有多份副本；编排没有 `env_file` 时新键永远进不了容器）、容器静默停在旧镜像（`--force-recreate` 只重建容器不重建镜像）、以及环境变量配对了却被**对端主动拒绝**（如 Chrome DevTools 端点校验 Host 头，必须用 IP 而非主机名）；并含两类「本机能跑、只有 CI 挂」的环境差异排查（被 gitignore 的文件被显式 COPY；编排声明了只在本机存在的 external 网络）。
agent_created: true
---

# Docker 化前端：改了不生效 / 构建慢 的排查

## 核心原则

**先分清"慢"和"不生效"是两回事**，再定位到具体一层。不要一上来就建议"重建镜像"。
多数情况下用户报告的"没生效"根本不是构建问题，而是浏览器缓存或包管理器错配。

**配置类问题问三句**：**文件里登记了吗？→ 进容器了吗？→ 对端接受了吗？**
三步都能"静默失败"，症状却都是"没生效 / 连不上"（层 6）。
🔴 而且**改 env 不等于要重建镜像** —— 只有改了镜像内的东西才需要 `build`。

**还有个高频变体：本机全绿、CI 才红**（`failed to compute cache key: " /x": not found`）——
那不是"不生效"而是"构建不出来"，根因通常是 `COPY` 的文件被 `.gitignore` 了（层 3 末尾）。
一旦见到"我这能跑"，先问：**这个文件在 git 里吗？**

排查顺序（按出现频率，从高到低）：

| # | 层 | 典型症状 | 判据 |
|---|---|---|---|
| 1 | **浏览器启发式缓存** | 改了、刷新还是旧的 | 服务端 access log **一条记录都没有** |
| 2 | **构建上下文臃肿** | 每次 build 都要等很久 | `transferring context` 体积异常大 |
| 3 | **包管理器与 lockfile 错配** | 本地好的、容器里行为不一样 | lockfile 未进上下文，`npm ci` 被静默兜底 |
| 3b | **`COPY` 的文件没入库** | 本机 build 通过、**CI 挂** | `git ls-files <文件>` 为空 |
| 4 | 构建缓存假命中 | "重建"了但什么都没变 | 全部步骤 `CACHED` ⇒ 源码指纹确实没变 |
| 5 | **容器静默停在旧镜像** | 镜像明明重建了、`up --force-recreate` 也报成功，页面还是旧 | `docker inspect -f '{{.Image}}' <c>` ≠ `docker image inspect -f '{{.Id}}' <tag>` |
| 6 | **环境变量/配置没进容器**（含"进去了但被对端拒绝"） | `.env` 加了新键、容器也 recreate 了，应用仍走默认值／"连不上"但报错让你去查对端没启动 | `docker exec <c> sh -c 'env \| grep KEY'` 为空；或同一地址**主机名**形态 5xx、**IP** 形态 200 |

---

## 层 0：`build` 根本跑不起来（先排掉，否则后面四层都无从谈起）

### 🔴 症状：`error getting credentials - err: exec: "docker-credential-desktop": executable file not found in $PATH`

**根因**：`~/.docker/config.json` 里有 `"credsStore": "desktop"`，buildx 解析基础镜像时会调外部凭据助手。
当用**完整 docker 路径**调用（如 macOS 的 `/Applications/Docker.app/Contents/Resources/bin/docker`）
或运行环境 PASS 被精简时，助手二进制不在 `$PATH` ⇒ **连 `FROM` 的元数据都拉不到**，构建在第 1 步就死。

**判据**：报错里同时出现 `error getting credentials` 与 `docker-credential-*`；
日志停在 `load metadata for ...` 而没有任何编译输出（易被误判成"网络慢/镜像拉不下来"，其实是本地加锁问题）。

**修复**（macOS Docker Desktop，该目录同时含 `docker` 与凭据助手）：
```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose ... build <svc>
```
> 判据：`ls /Applications/Docker.app/Contents/Resources/bin/` 里应能看到 `docker-credential-desktop`。
> 若坚持不改 PATH，也可临时改 `credsStore` 为 `osxkeychain`（或删掉该键），但会动用户全局配置，优先级更低。

### 同类的另一条：探针/脚本**放 `/tmp` 跑会找不到浏览器**

`playwright` 的浏览器 revision 按**模块解析到的包**绑定。把检查脚本写到 `/tmp` 执行时，
解析链与仓库内不同，可能要求一个缓存里不存在的 revision（如要 `chromium_headless_shell-1243`，而缓存只有 `-1234`），
报 `Executable doesn't exist at .../ms-playwright/...`。
**修复**：把脚本**放在仓库目录内**执行（必要路径写绝对路径）。仓库若把 `output/` 列入 `.gitignore`，放那里最干净、不留痕。

## 层 1：浏览器启发式缓存（最常被误判）

### 症状
构建与重启都做了，服务端日志也正常，但浏览器里还是旧内容。**用户按 F5 无效，只有 Ctrl+Shift+R 才正常。**

### 根因
nginx（或任何静态服务器）响应里**既没有 `Cache-Control` 也没有 `Expires`** 时，
浏览器会启用**启发式缓存**：

```
freshness_lifetime = (Date − Last-Modified) × 10%
```

产物越旧，这个窗口越长（放了几天 ⇒ 窗口可达数小时）。窗口内按 F5，
**浏览器根本不发请求**，直接用本地副本渲染。

### 判据（关键，一眼区分两种成因）
```bash
# 看 access log 有没有用户的浏览器请求
docker logs <容器> --tail 30 | grep -v Wget   # 排除 healthcheck
```
- **没有记录** ⇒ 请求根本没到服务器 ⇒ **被浏览器缓存**（层 1）
- **有记录但内容是旧的** ⇒ 才可能是构建/重建问题（查层 2~4）

### 修复

口径：**只有带内容哈希的构建产物才长缓存，其余一律必须协商**。

```nginx
# 入口：可缓存但必 revalidate（内容没变返 304 省流量，变了立刻 200）
location = /index.html {
    add_header Cache-Control "no-cache, must-revalidate" always;
}
# 站点根 `/` 不能省：浏览器访问站点根发的是 GET /，只写 = /index.html 时可能匹配不到
location = / {
    add_header Cache-Control "no-cache, must-revalidate" always;
    try_files /index.html =404;
}
# 兜底：所有非哈希资源（public/ 下的 iconfont/styles/fonts、favicon 等）必须协商
location / {
    add_header Cache-Control "no-cache, must-revalidate" always;
}
# 唯一的长缓存分支：文件名里含 8 位内容 hash 的构建产物
location ~* '^/assets/.+\.[A-Za-z0-9_-]{8}\.(js|mjs|css|woff2?|ttf|eot|svg|png|jpe?g|gif|webp|ico)$' {
    add_header Cache-Control "public, max-age=31536000, immutable" always;
}
```

#### 🔴 反模式：`location /assets/ { immutable }` —— 不要这么写
`public/` 下的资源**不进 hash、保持原文件名**，而且往往**就在 `/assets/` 下面**、
还被 `index.html` 直接引用（Vite 项目里典型是 `/assets/iconfont/iconfont.css`、
`/assets/styles/font-awesome.min.css`、`/assets/fonts/*`）。
一刀切长缓存 ⇒ 改图标/字体**一年不生效**，症状与启发式缓存同一副面孔、更难查。
（用正则限定"含 hash 才长缓存"，则日后往 `public/` 新增无哈希资源只会退化成协商，**失败方向是安全的**。）

#### 🔴 坑 1：哈希字符集别想当然（Vite 5+ 是 **base64url**，不是十六进制）
实测产物名：`401.DIcI82Bl.js`、`CenterHome.C722--D2.js`、`Popup.lZVS7M0L.js`、`iconfont.D9nhFZW9.woff2`
⇒ 含**大写字母与 `-`/`_`**。写成 `[0-9a-f]{8}` 会**一条都不命中**（正解 `[A-Za-z0-9_-]{8}`）。
⚠️ 确认字符集的命令：
```bash
docker exec <容器> sh -c 'ls /data/assets | head -20'
docker exec <容器> sh -c "ls /data/assets | grep -cE '\.[A-Za-z0-9_-]{8}\.(js|css)\$'"
# 再反向确认 public 资源不会被误命中：
docker exec <容器> sh -c "ls /data/assets/iconfont /data/assets/styles /data/assets/fonts \
  | grep -E '\.[A-Za-z0-9_-]{8}\.(js|css|png|svg|woff2?|ttf)\$' || echo '(无误命中)'"
```

#### 🔴 坑 2：正则里的 `{n}` 必须给整条正则加引号
不加引号，nginx 会把 `{` 当块分隔符，**`nginx -t` 直接失败**：
```
[emerg] unknown directive "8}\.(js|mjs|css|...)$" in /etc/nginx/conf.d/default.conf:63
```
用**单引号**（双引号会让 nginx 对结尾的 `$` 做变量插值）：
`location ~* '^/assets/.+\.…{8}\.(js|…)$' {`

#### 🔴 坑 3：`nginx -t` 通过 ≠ 规则命中
语法对不对，和"这条 location 到底有没有匹配上"是两件事（坑 1 就是典型：语法全绿、逻辑全错）。
**必须真发请求断言**。造一棵用**真实文件名**的假 `/data`，跑一个临时 nginx：
```bash
mkdir -p /tmp/probe/data/assets/{iconfont,styles,fonts}
: > /tmp/probe/data/index.html
# 用真实 hash 名，别用 index.a1b2c3d4.js 这种假名（假名会让你误判成"修好了"）
for n in "401.DIcI82Bl.js" "index.B54_gIuU.css" "logo-mini.DxRIPo1t.svg"; do : > "/tmp/probe/data/assets/$n"; done
docker run -d --name probe -p 18100:80 \
  -v "$PWD/<conf>":/etc/nginx/conf.d/default.conf:ro -v /tmp/probe/data:/data:ro <nginx镜像>
for p in /assets/401.DIcI82Bl.js /assets/iconfont/iconfont.css /; do
  printf '%-34s ' "$p"
  curl -s --noproxy '*' -o /dev/null -D - "http://127.0.0.1:18100$p" | tr -d '\r' | awk '/^Cache-Control:/{print $2,$3,$4,$5}'
done
docker rm -f probe
```
⚠️ **取值别用定长切片**（`substr($0,16)` 这类）：算错一位会把"对"读成"错"，真的会被自己误导。
⚠️ 线上复核时比**镜像 ID**，别只看 `Up X minutes`（完整判据与处置见 **层 5**）：
```bash
docker inspect <容器> --format '{{.Image}}'      # 与下一条比，不等就说明容器还在用旧镜像
docker inspect <镜像tag> --format '{{.Id}}'
```

#### 🔴 坑 4：探针 URL 拼错 ⇒ 制造「规则没命中」的假象
从容器里取真实产物名时，`ls` 返回的是**容器内绝对路径**：
```bash
H=$(docker exec <容器> sh -c 'ls /data/assets/*.js | head -1')   # → /data/assets/401.DIcI82Bl.js
curl ... "http://127.0.0.1:8890$H"                               # ❌ GET /data/assets/... 落到兜底 location
curl ... "http://127.0.0.1:8890/assets/$(basename "$H")"          # ✅ GET /assets/401.DIcI82Bl.js
```
前者的请求**根本不进**你要验的那条 `location`，而是被**兜底 `location /`**接管
⇒ 你若给兜底也加了 `no-cache`，输出就是 `no-cache`，**看起来正正常常，实则正则一次都没匹配**，
会让你误以为修复失效、然后去改本来正确的配置。**两次踩中这个坑。**
加固：断言里同时打 `HTTP` 状态码，并**先打一条已知必须命中的 URL**（如 `/assets/<真实 hash 名>`）
确认能读到 `immutable`，再往下批量跑。

- 旧的 `location = /index.html` 之所以"有的情况下也生效"：`GET /` 会经 `index` 指令**内部重定向**到
  `/index.html`，内部重定向会重新走 location 匹配。但这条依赖实现细节，**显式写 `location = /` 更稳**。
- **秒级生效、不必重建镜像**（仅当容器是 bind-mount 或可写层未被重建时）：
  ```bash
  docker cp <conf> <容器>:/etc/nginx/conf.d/default.conf
  docker exec <容器> nginx -t && docker exec <容器> nginx -s reload
  ```
  ⚠️ 若 conf 是构建期 `COPY` 进镜像的（本仓库就是），`docker cp` 的修改**会在下次 recreate 时被冲掉**
  ⇒ 正确做法仍是改源码文件 + 重新 build + `--force-recreate`。
- 验证：`curl -sD - -o /dev/null http://localhost:<port>/ | grep -i cache-control`

---

## 层 2：构建上下文臃肿

### 症状
`docker compose build` 每次开头都要等一段"无进展"的时间。

### 诊断
```bash
# 看实际传输量（首次构建才是全量）
docker compose ... build --progress=plain <svc> 2>&1 | grep "transferring context"

# 秒级测量"按现有 .dockerignore，到底会传多少"（不跑构建）
# ⚠️ 基础镜像走本机可用的镜像站；直连 Docker Hub 在部分网络下不可达
cat > /tmp/ctxcheck.Dockerfile <<'EOF'
FROM docker.m.daocloud.io/library/busybox:latest
COPY . /src
RUN du -sh /src && du -sh /src/* | sort -rh | head -8
EOF
docker build -f /tmp/ctxcheck.Dockerfile --progress=plain <前端目录>
docker rmi $(docker images -q --filter "dangling=true")   # 用完清掉临时镜像
```

### 常见漏网之鱼
- **同仓库里的其他工程**（如 Electron 桌面端 `desktop/`，自带 `release/` 安装包数百 MB）
- **打包产物目录**（`release/`、`web/`、`out/`、`coverage/`）
- `*.md` / CI 配置 / `.DS_Store`

### ⚠️ 一个容易看走眼的点
`.dockerignore` 里**不含斜杠**的模式（如 `node_modules`）Docker 会匹配**任意层级**
（内部对文件路径逐级做后缀匹配）。所以 `a/node_modules` 早被排除了——
**别再只盯着 node_modules**，去看那些"名字里没有 node_modules"的大目录。

---

## 层 3：包管理器与 lockfile 错配

### 症状
本地一切正常，容器里报错或行为不同；且**构建不报错**，所以排查时想不到依赖层。

### 判据
```bash
ls <前端目录>/*lock*          # 实际用的是哪个包管理器？
grep -n "COPY\|RUN" Dockerfile | head
```
典型反模式：
```dockerfile
COPY package*.json ./                                    # ❌ 通配符不匹配 pnpm-lock.yaml
RUN npm ci ... || npm install ...                        # ❌ npm ci 必然失败，被 || 静默吞掉
```
`npm ci` 在缺少 `package-lock.json` 时**必然退出非零**，被 `||` 兜底成 `npm install`
⇒ 每次都**无锁解析**（装"当前最新匹配版"）。

### 修复（已实测跑通，可直接抄）
```dockerfile
# 🔴 拷 lockfile 前**先确认它在版本控制里**（见下方「CI 才挂」小节）：
#    git ls-files <前端目录>/pnpm-lock.yaml   # 空 ⇒ 没入库 ⇒ 不能写显式路径
COPY package.json ./
COPY pnpm-lock.yam[l] ./          # 字符类 = 「可选拷贝」；缺文件时 BuildKit 静默跳过
RUN --mount=type=cache,target=/root/.cache/pnpm-store \
    npm config set registry https://registry.npmmirror.com \
    && npm install -g pnpm@<版本号> --no-audit --no-fund \
    && pnpm config set store-dir /root/.cache/pnpm-store \
    && pnpm config set strict-dep-builds false \
    && if [ -f pnpm-lock.yaml ]; then \
         echo "[deps] 有 lockfile → 冻结安装" ; \
         pnpm install --frozen-lockfile --prod=false --reporter=append-only ; \
       else \
         echo "[deps] ⚠️ 无 lockfile → 无锁解析安装" ; \
         pnpm install --prod=false --reporter=append-only ; \
       fi
```
> 上面 `COPY package*.json` 的坑与**本段第一版**（写成显式 `COPY package.json pnpm-lock.yaml ./`）
> 是两类不同的错：前者**拷不进** lockfile，后者**拷不到就崩**。详见下方小节。

### 🔴 症状变体：「本机 build 通过，**CI 才挂**」——`COPY` 的文件被 gitignore 了
CI 报错形如：
```
> [<svc> build 3/6] COPY package.json pnpm-lock.yaml ./:
target <svc>: failed to solve: failed to compute cache key:
failed to calculate checksum of ref …: " /pnpm-lock.yaml": not found
```
**根因**：lockfile 被 `.gitignore` 忽略（很多模板默认忽略 `package-lock.json`/`yarn.lock`/`pnpm-lock.yaml`）
⇒ **从未入库**。本机磁盘上有（`pnpm install` 生成的），CI 全新 clone 里没有 ⇒ 显式路径直接失败。
**这是「我这能跑」的经典形态：本地全绿、push 之后才红。**

**一条命令定性**：
```bash
git ls-files <前端目录>/pnpm-lock.yaml     # 空 = 未跟踪（就是它）
git check-ignore -v <前端目录>/pnpm-lock.yaml   # 哪条 .gitignore 规则忽略了它
```
**BuildKit 行为差异（实测，决定修法）**：

| 写法 | 上下文里没有该文件时 |
|---|---|
| `COPY pnpm-lock.yaml ./`（显式路径） | ❌ `"/pnpm-lock.yaml": not found`，构建失败 |
| `COPY pnpm-lock.yam[l] ./`（字符类通配符） | ✅ **静默跳过**，构建继续 |

**最小复现**（`FROM alpine:3.20` + 上面两行，分别在有/无 lockfile 的目录 build 一次即可）。

**别踩的次生坑**：
- 别用 `COPY package*.json ./` 想"两全"——它**匹配不到** `pnpm-lock.yaml`（`.json` 不等于 `.yaml`），
  lockfile 静默丢失、退回无锁解析。
- 降级要**打印原因**（`echo` 一行），别学 `npm ci || npm install` 那种无提示兜底——那才是真坑。
- 想彻底可复现，正解是**把 lockfile 纳入版本控制**（`git add -f` + 删 `.gitignore` 那行），
  而不是在 Dockerfile 里硬要求它存在。Dockerfile 用 `if [ -f … ]` 分流可同时兼容两种仓库状态。
  - 🔴 **纳入前必须验证 lock 与 `package.json` 一致**，否则 `pnpm install --frozen-lockfile` 会报
    `ERR_PNPM_OUTDATED_LOCKFILE`，**本机与 CI 一起失败**（比不纳入更糟）。
    验证法：`git archive HEAD <模块>` + 该 lockfile → `docker build --no-cache`，
    看是否走到 `exporting layers … done` / `naming to … done`——
    若 lock 过期，构建会在**依赖层**就中断，根本到不了这些末尾阶段。
  - 只纳入一个模块时，**把该模块的 `AGENTS.md` / 手册同步改对**（否则下个人又被「未入库」类说法带偏）。
- **验证必须模拟 CI 上下文**，别只看 `nginx -t` 式的语法检查：
  ```bash
  rsync -a --exclude node_modules --exclude dist <前端目录>/ /tmp/ci-sim/
  rm -f /tmp/ci-sim/pnpm-lock.yaml          # 还原 CI 的上下文
  cd /tmp/ci-sim && docker build --no-cache --progress=plain -t ci-sim . 2>&1 | grep -E "\[deps\]|ERROR"
  ```

- ⚠️ **别用 `corepack enable` 单独锁版本**：corepack 只在 `package.json` 有
  `packageManager` 字段时才按它 pin 版本；该字段缺失时会退回到"已知良好版本"
  ⇒ 版本仍会漂移，等于没解决问题。两条正确路线：
  ① 显式 `npm install -g pnpm@<版本>`（与本地 `pnpm -v` 对齐）；或
  ② 补 `packageManager: "pnpm@x.y.z"` 字段后 `corepack enable`（更规范，但要改仓库）。
- ⚠️ **`ERR_PNPM_IGNORED_BUILDS`**：pnpm 10+ 默认不执行依赖的 postinstall **且视为错误**（exit 1）。
  关掉 `strict-dep-builds` 而不是去 approve 脚本——先确认**本机同样状态下是否正常**
  （多数二进制依赖走 `optionalDependencies` 平台包，如 `@esbuild/<platform>`，不靠 postinstall）。
  若本机也依赖 postinstall，则应改用 `pnpm.onlyBuiltDependencies` 显式声明允许列表。
- `--mount=type=cache` 持久化 store ⇒ 重复构建时依赖层近乎秒级命中。
- 实践数据：install 25.2s → 10.5s，完整构建 61s → 39s。

### 🔴 症状变体 2：「本机 `up` 正常，**CI 才挂**」——编排声明的 external 网络只存在于本机

同样是「环境差异」，但这次卡在 `up`（**镜像全部构建成功之后**）：

```
network <名字> declared as external, but could not be found
```

成因：顶层 `networks:` 把某个**由别人创建**的网络声明为 `external: true`（常见于「本机另起
一套 Dify / 中间件」的编排），而它只在开发者本机存在 —— CI 节点上既没有、也没法手工建
⇒ 编排在**解析阶段**就中止，且失败点在构建之后，容易误以为是「构建完了就没事了」。

**判据（两条，均实测）**：
- 只有 `up` / `--dry-run` 会报；`docker compose config --services` **照样成功** ⇒ 不能当判据。
- 报错只指向**按 `networks:` 声明顺序第一个**缺失的 external 网络（compose 顺序检查、遇错即停）。
  反过来用：若你怀疑有两个网络、报告里只出现其中一个，说明**另一个确实存在** ⇒ 缩小改动面。

**修法**：让编排不依赖「本机手工造的网络」。若该网络已无实际用途（例如依赖的服务已迁到远程），
直接删声明 + 从服务 `networks:` 列表里摘掉，注释写成「确需时用**叠加文件**接入，别写回主编排」：

```yaml
# deploy/docker-compose.optional.yml（按需 -f 叠加，不进主路径）
services:
  app:
    networks: [main, extra]        # ⚠️ 必须写全：compose 的 networks 列表是覆盖而非追加
networks:
  extra: { external: true }
```

**A/B 复现（30 秒出结论，推荐）**：
```bash
git show HEAD:deploy/docker-compose.yml > deploy/.tmp-old.yml   # 须放原目录：build context 是相对路径
docker compose -f deploy/.tmp-old.yml up -d --dry-run | tail -3     # 复现 CI 报错
docker compose -f deploy/docker-compose.yml up -d --dry-run | tail -3   # 应全部 Running
rm -f deploy/.tmp-old.yml
```

**顺带自查**：`grep -rn "<网络名>" tools/ docs/` —— 通常还有脚本/文档在教人手工 `docker network connect`。
脚本要改成**默认跳过 + 先判断网络是否存在**再动作，否则会演成「connect 静默失败、却仍
`docker restart` 业务容器并打印成功」的假成功。

---

## 层 4：构建缓存假命中

`--progress=plain` 输出里：
- `COPY . .` / `RUN ... build` 显示 `CACHED` ⇒ **BuildKit 认为源码指纹没变**
  （内容级 hash，`touch` 不生效）⇒ 这次"重建"不会产出任何变化，**不是构建坏了**。
- 显示 `DONE <n>s` ⇒ 真跑了。

这条能区分"构建成功了但页面没变"（⇒ 查层 1）和"源码真的没被改动/改的不是这个工程"。

---

## 层 5：容器静默停在旧镜像（`--force-recreate` 不重建镜像）

### 症状
镜像**确实重建了**、`up -d --force-recreate --no-deps <svc>` **报 Started 成功**、
`docker ps` 显示 `Up Nh (healthy)` —— 但页面上的修复就是不生效。
最容易发生在**「build 与 up 拆成两条命令」**的流程里：如果 `up` 跑在 `build` **完成之前**
（或跑的是上一轮镜像），compose 会拿「当前 tag 指向的镜像」建容器，新镜像就白建了。

> `--force-recreate` 的语义是"**容器**一定是新建的"，**不是**"用的**镜像**一定是最新的"。
> `Up 5 minutes (healthy)` 只说明容器活着，**不构成镜像已更新的证据**。

### 判据（三把尺子，按顺序）
```bash
# ① 容器实际所跑的镜像 ID   vs   该 tag 现在指向谁
docker inspect -f '{{.Config.Image}} {{.Image}}' <容器>
docker image inspect -f '{{.Id}}' <镜像Tag>
# 不等 ⇒ 容器落后。再看时序确认因果：
docker inspect -f '{{.State.StartedAt}}' <容器>          # 如 00:04:47
docker image inspect -f '{{.Created}}'  <镜像Tag>        # 如 00:24:01  ⇒ 容器早于镜像，铁证

# ② 证明「镜像里有」（不必启动容器）
docker run --rm --entrypoint sh <镜像Tag> \
  -c 'grep -o "el-tag--dark{[^}]*}" /data/assets/index.*.css'

# ③ 证明「容器跑的就是它」
docker exec <容器> sh -c 'ls /data/assets/index.*.css; grep -o "…" /data/assets/index.*.css'
```
②③ 分开做的价值：只做 ③ 的话，若容器落后你会误判成「构建没生效」，从而去重跑构建（治错了病）。

### 处置
- 镜像已新 ⇒ 只需 `up -d --force-recreate --no-deps <svc>`，**之后回读 `.Image` 确认换掉**。
- 镜像没新 ⇒ 先 `build <svc>`（与 up **分两条命令**），再 up。
- 收口时顺手扫一遍全部服务，一次抓出所有落后者：
```bash
for c in $(docker ps --filter 'label=com.docker.compose.project=<proj>' --format '{{.Names}}'); do
  img=$(docker inspect -f '{{.Config.Image}}' "$c"); cid=$(docker inspect -f '{{.Image}}' "$c")
  cur=$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null)
  [ "$cur" = "$cid" ] && echo "OK   $c" || echo "🔴 落后 $c  ($(docker inspect -f '{{.State.StartedAt}}' "$c") vs $(docker image inspect -f '{{.Created}}' "$img"))"
done
```

### 🔴 顺带两个「产物探测」的假阴性（会让你误判成"规则没进产物"）
1. **产物选择器带前缀**：作用域化编译会加前缀（实测 Vite + 自定义 wrapper 可得
   `html:not(.is-mobile) .el-tag--success.el-tag--dark{…}`），且各端产物文件名 hash 不同
   ⇒ **别按文件名找、别按选择器形状 grep**，一律 `grep -F '<特征值>'`（如 `#52575e`、`pc-brand-soft`）。
2. **`grep -c` 会对非命中文件也打印 `0`**，再配 `head -3` 截断 ⇒ 看起来"三行全 0 = 未命中"。
   数**命中文件数**要用 `grep -rl -- '<pat>' <glob> | wc -l`。

### 🔴 形态变体：`docker cp` 直投（不烘焙镜像）——「当场生效，recreate 后静默回退」

常见"快路径"：`docker cp <dist>/. <容器>:/data/` + `docker exec <容器> nginx -s reload`。
秒级生效，代价是产物落在**容器可写层**，任何 `up -d` / `--force-recreate` / 镜像重建都会
把它连容器一起丢掉（现场表现成"几天前修好的又回去了"）。

**判据（区分"镜像权威"还是"直投残留"）**：
```bash
docker exec <容器> md5sum /data/index.html                                  # 运行中看到的
docker run --rm --entrypoint sh <镜像Tag> -c 'md5sum /data/index.html'      # 镜像里烘焙的
docker image inspect -f '{{.Id}}' <镜像Tag>; docker inspect -f '{{.Image}}' <容器>
```
- 全一致 ⇒ 容器就是镜像建出来的，recreate 安全。
- `/data` ≠ 镜像内 `/data` ⇒ **直投残留**：这次运行的产物没进镜像，**必须补一次 `build` 才算真落地**。

⚠️ **别用「产物 md5 / asset hash」判"新旧版本"**：实测**同一份源码两次构建，全部 asset hash 都不同**
（同日同仓：`context.cr5UZg23.js` vs `context.CiFIeIW9.js`）⇒ `md5 不等` 只说明"不是同一次构建"，
**不等于版本落后**。判版本只认**源码专有串**：挑一个只存在于新代码里的字面量（新增错误提示 /
新增文案 / 新增键名），双侧 `grep -rl` 命中与否即结论。反面教材：新旧代码都有的字段名
（如 `firstSeenText`）不能当标记，否则给出"已更新"的假阳性。

---

## 层 6：环境变量/配置没进容器（含「进去了但被对端拒绝」）

### 6.1 症状：`.env` 加了新键、容器也 recreate 了，应用仍走默认值

**根因**：`docker compose --env-file .env.dev` 里的 `--env-file` **只做 `${}` 插值**，
它**不会**把文件内容注入容器。容器能拿到哪些变量，取决于编排 `environment:` **显式列了哪些**；
没有 `env_file:` 时，未登记的键**永远不会进容器**（而且**不报错**，静默走默认值）。

**判据（按顺序，三条一次跑完）**

```bash
# ① 编排到底有没有 env_file？（空 = 全靠显式列表 ⇒ 新键必须自己登记）
grep -nE 'env_file|^\s+- \.env' deploy/docker-compose*.yml

# ② 容器真的拿到了吗？（别只看文件——文件对了不代表进得去）
docker exec <c> sh -c 'env | grep -E "^MY_|^HR_" | sort'

# ③ 编排解析出来的值对不对（最省事一步，同时验插值与键名）
docker compose --env-file .env.dev --env-file .env -f docker-compose.dev.yml config \
  | grep -nE -A3 'MY_KEY'
```

**修复**：在目标服务 `environment:` 里登记，默认值写 `${VAR:-default}`：

```yaml
      MY_KEY: ${MY_KEY:-default-value}
```

### 🔴 两条效率/陷阱事实

- **env 变更不需要重建镜像**：改 `environment:` 只需 `up -d --force-recreate <svc>`。
  只有改了**镜像内**的东西（源码、依赖、烘焙进镜像的 conf）才要 `build`。
  别为了改一个变量白等一次构建（本轮实测：改 `.env` + 编排 → 只 recreate；同时改了 `.py` 才需要 build）。
- **键名可能不是"父前缀 + 嵌套名"，而是"子模型自己的 env_prefix"**。实测（pydantic-settings 分层配置）：

  | 写法 | 结果 |
  |---|---|
  | `BOSS_CDP_URL`（子模型 `env_prefix="BOSS_"`） | ✅ 生效 |
  | `HR_BOSS_CDP_URL`（父模型 `HR_` + 字段 `boss`） | ❌ **静默无效** |
  | `HR_BOSS__CDP_URL`（双下划线嵌套风格） | ❌ 静默无效 |

  ⇒ 父模型 `hr: HrSettings(env_prefix="HR_")` 下的 `boss: BossSettings(env_prefix="BOSS_")`，
  **生效的是裸 `BOSS_*`**；只有父模型自己的**扁平**字段才用父前缀（`HR_BOSS_ACCOUNT_ID`）。
  **别靠推理，用上面 ③ 一次性验**：同时给多个候选键名赋**不同值**，看哪个赢。

---

### 6.2 症状：值配对了、从宿主机 `curl` 也通，容器里就是"连不上"，
### 而报错信息让你去检查**对端进程没启动** —— 但你确认它明明在跑

这类不是"配置没生效"，是**对端主动拒绝**，而错误信息把归因带偏了。
实例：**Chrome DevTools 端点的 `Host` 头校验**（2026-10-04 实测）。

容器访问宿主机 Chrome 调试端口（`--remote-debugging-port=9222`）最自然的写法是
`http://host.docker.internal:9222`。它**不通**：

| 请求 | 结果 |
|---|---|
| `http://host.docker.internal:9222/json/version` | **500** `Host header is specified and is not an IP address or localhost.` |
| `http://192.168.65.254:9222/json/version` | **200** |

Chrome 的 DevTools HTTP 端点要求 `Host` 头是 **IP 字面量或 localhost**，主机名形态一律 500。
而"探测把非 200 当不可达"的代码会把它归类成"端口没开"，抛出"请先启动 Chrome"
⇒ **完全误导**：Chrome 明明在跑，真正的问题是 Host 头不合规。

**正确做法**：把主机名解析成 IP 再请求。不想把 Docker 网关 IP（`host.docker.internal` → `192.168.65.254`）
硬编码进配置，就在代码里做**主机名 → IP 候选展开**（配置保留可读写法）：

```python
if host and not _is_ip(host):          # _is_ip: ipaddress.ip_address() 解析成功即真
    for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
        candidates.append(f"{scheme}://{ip}:{port}")
```

附带：Chrome 回显的 `webSocketDebuggerUrl` 是**按请求的 Host 拼装**的（走 IP 就回
`ws://192.168.65.254:9222/...`）⇒ 走 IP 时 Playwright `connect_over_cdp` 也直连，无需额外处理。

**通用判据**

> **"不可达"要先分清是「没人听」还是「有人听但拒绝了你」。**
> 一次性把两种可能都排掉：容器内对**同一目标**请求**两种写法**（主机名 / 解析出的 IP），比状态码 ——
> 一个 5xx + 一个 200，就是对端在做 Host / SNI / 白名单校验，与"服务没起"无关。

```bash
docker exec <c> python -c "
import socket, httpx
h = 'host.docker.internal'
for u in (f'http://{h}:9222/json/version', f'http://{socket.gethostbyname(h)}:9222/json/version'):
    try:
        r = httpx.get(u, timeout=6); print(r.status_code, u, r.text[:80])
    except Exception as e:
        print('EXC', u, type(e).__name__, e)
"
```

---

## 定位"改的到底是哪个工程"

多前端工程（`web/`、`pc/`、`mobile/`、`desktop/`）并存时，最常见的乌龙是
**改了 A 工程的源码，却重建 B 工程的容器 / 访问 B 的端口**。

判据：
```bash
# 1. 各容器实际映射的端口
for c in $(docker ps --format '{{.Names}}'); do printf '%-24s ' "$c"; docker port "$c" | tr '\n' ' '; echo; done
# 2. 用户是否真在访问这个容器（找真实浏览器 UA）
docker logs <容器> --tail 30
# 3. 容器内产物 vs 本源码：比时间戳 + 入口文件引用的 assets hash
docker exec <容器> ls -la /data/index.html
grep -o 'assets/[a-zA-Z0-9._-]*\.js' <本地>/dist/index.html | head
```

### ⚠️ 端口可能被 `--env-file` 覆盖层悄悄改掉
命令里叠了多个 env-file 时，后一个会覆盖前一个。若某层定义了 `HOST_*_PORT`
之类的**插值**键，容器实际发布的端口会变，而 nginx 里 `listen` 可能仍是默认值
⇒ 你会去敲一个"文档上写着、实际没开"的端口。**以 `docker port <容器>` 为准，别信文档。**
（同理：这类键还可能让宿主机其他服务的端口被悄悄挤掉，表现为"某个服务突然不见了"。）

### ⚠️ 同一个配置文件在仓库里可能有两份，改错的那份等于没改
多前端工程里常见"历史重构留下的残留副本"：`<app>/Dockerfile` 与 `<app>/docker/Dockerfile`
并存、`<app>/<x>.conf` 与 `<app>/docker/<x>.conf` 并存。**你改 A，镜像用的是 B。**

先确定"到底哪份进了镜像"，别读文件猜：
```bash
# 1) 用哪份 Dockerfile：compose 没写 dockerfile: 时 = 上下文根的 Dockerfile
grep -n -A6 "^  <service>:" deploy/docker-compose.yml
# 2) 那份 Dockerfile 引用了哪个 conf
grep -n -E "COPY|ADD" <app>/Dockerfile
# 3) 收官验证（最省事，一步到位）：把镜像里烘进去的抠出来，与候选文件逐个 diff
docker run --rm --entrypoint sh <镜像> -c 'cat /etc/nginx/conf.d/default.conf' > /tmp/baked.conf
for f in <app>/*.conf <app>/docker/*.conf; do
  printf '%-42s ' "$f"; diff -q /tmp/baked.conf "$f" >/dev/null && echo '✅ 就是它' || echo '✗'
done
```
发现残留副本时**只报告、别顺手删**（是否删除属用户决策）。

---

## 开发期别用容器：dev server 才是正解

如果用户是在**开发调试**，最彻底的方案是绕开 docker：让前端 dev server（Vite / webpack-dev-server）
直跑，享受 HMR（改代码 < 1 秒生效）。容器只留给演示/联调验收。

配置要点：
- **端口必须避开容器已占用的端口**。且注意 Vite 默认 `strictPort=false`——
  端口被占时**静默 +1，不报错不提示**，极易误判为"配置没生效"。显式指定一个空闲端口。
- dev server 的接口代理要与 nginx 逐条对齐（否则"开发正常、容器 404"）。

| 通道 | 生效方式 | 用途 |
|---|---|---|
| dev server | 改代码 < 1 秒 | 日常开发 |
| 容器（nginx） | 重新 build + 重建容器 | 演示、验收 |

---

## 输出要求

给用户的结论要包含：
1. **实测数字**（上下文多少 MB → 多少 MB；构建多少秒 → 多少秒；HMR 多少毫秒），不要只说"优化了"。
2. **区分"慢"与"不生效"**，并说明各自的根因——这是两件独立的事。
3. 明确哪些改动是**立即生效**的（如 `docker cp` + reload），哪些要等下次构建。
4. 未处置的相邻问题要显式列出（例如"另外两个前端工程的 nginx conf 也缺缓存头"）。
