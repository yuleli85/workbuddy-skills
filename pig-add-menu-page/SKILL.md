---
name: pig-add-menu-page
description: 在 PIG（linmo-pig-full）里「新增一个页面 + 把它挂进菜单 + 调通」的闭环。适用于用户说「把 X 复制一份到 Y 菜单下」「新增一个 X 页面」「加个菜单叫 X」「这个功能帮我调通」，以及任何需要往 sys_menu 插入新行并让前端能打开该页面的任务。覆盖三端（pig-ui 8888 / pig-pc-ui 8890 / pig-mob-ui 8899）的源码落点、菜单 SQL 的 owner 归属与守卫登记、sort_order 独占判据、Redis 缓存清理、镜像重建与对账、探针验证。触发词：新增菜单 / 加个菜单 / 复制一份到 / 挂到菜单下 / 新建页面 / 调通功能 / 面包屑归错中心 / 页面横向溢出 / 容器重建不生效 / 菜单点开没有页面（配套 menu-page-coverage-audit）。
agent_created: true
---

# PIG：新增页面 + 挂菜单 + 调通

把「我想要一个 X 页面挂在 Y 菜单下」变成**有落点、有守卫、有复验**的闭环。

核心原则：**先摸清现状（三端是否同源 / 6000 段谁 owner），再动手；改完必须用探针复验，且库里用最小改动。**

---

## 阶段 0：先摸清三件事（不做这步必踩坑）

### ① 三端同源吗？

```bash
for d in pig-ui pig-pc-ui pig-mob-ui; do printf "%-12s " $d; md5 -q $d/src/views/<路径>/index.vue 2>/dev/null || echo "(无)"; done
```

**实测差异很大**（2026-10-04 复制 AI 对话时发现）：
- `views/ai/chat/index.vue`：pc-ui 是 **21 行壳**（→ `linmo/views/AiChat.vue`），pig-ui/mob-ui 是 **416 行原版** —— 三端不是同一个页面。
- 三端 `linmo/views/AiChat.vue` 与 `linmo/linmo-port.css` 是**逐字节一致**的共用件 ⇒ 复用安全。

**要"复用复刻版"就新建壳，别复制源码**（复制会变两份要各自维护）。壳的写法照 `views/ops/home/index.vue`：

```vue
<template>
	<div id="linmo-b2b-mockup" class="linmo-embedded"><XxxView /></div>
</template>
<script setup lang="ts" name="opsXxx">
import XxxView from '/@/views/linmo/views/Xxx.vue';
import '/@/views/linmo/linmo-port.css';
</script>
<style scoped>
.linmo-embedded :deep(.lm-main) { height: auto; overflow: visible; min-height: 100%; }
</style>
```

🔴 `id="linmo-b2b-mockup"` **不能漏**：`linmo-port.css` 与 `views/ops/ops-theme-lock.css`（经营中心蓝白兜底）的作用域都锚在这个 id 上，漏掉 = 原型样式全部落空、整页裸奔。放进 `/ops/*` 还会自动被 `utils/opsTheme.ts` 撤掉 dark 标记。

### ② 父菜单下已用了哪些 id？

```bash
docker exec linmo-mysql mysql -uroot -proot -N -e "
SELECT menu_id,name,parent_id,path,sort_order,visible,menu_type FROM pig.sys_menu
WHERE del_flag='0' AND (menu_id=<父id> OR parent_id=<父id>) ORDER BY sort_order,menu_id;"
```

选一个**空闲的 menu_id**（同段内不撞）。6000 段 2026-10-04 已用到 6076。

### ③ 这个段有几个 owner？

```bash
grep -rln "6000 AND 6099\|BETWEEN 6000" pig/db/**/*.sql
```

6000~6099 是**多 owner 共用段**（2026-10-04 为 5 个）：`ops_agent.sql`（主 owner，整段 DELETE + 重插 34 条）、`ops_center_menu.sql`、`pig_dw_menu_quartz.sql`、`ops_market.sql`、`ops_linmo_ai_menu.sql`。
⇒ **新 owner 的菜单行必须同步登记进 `ops_center_menu_restore.sql` 的 ①菜单行 / ②授权 / ③哨兵清单**，
否则守卫末尾的哨兵会 `CHECK` 违例、**把整批升级停下**（这是设计行为，不是误报）。见该文件头部【新增 owner 时怎么办】。

### ④ 有「无 DELETE 覆盖」的安全段吗？（能省掉整条守卫链）

2026-10-15 实测：**9910 段（「基础工具」/ Base Tools，`parent_id=-1`）没有任何 `DELETE FROM sys_menu` 覆盖**
（`grep -rn "DELETE FROM sys_menu" pig/db_bak/` 逐条核对）⇒ 往这里插菜单**无需登记 `ops_center_menu_restore.sql`**，
也不会被 owner 脚本重跑冲掉。菜单 id 用 `9911+`（9910 自身是父节点）。

```bash
# 判据：本段 id 区间有没有被任何 DELETE 覆盖
grep -rn "DELETE FROM sys_menu" pig/db_bak/ | grep -E "991[0-9]|9[0-9]{3} AND"
```

⇒ **优先把新菜单挂到无 DELETE 覆盖的段**（少一半工作量、零守卫风险）；只有必须落在 6000/经营中心这类
多 owner 段时才走 ③ 的登记流程。

---

## 阶段 1：菜单 SQL（本功能一个文件）

模板见 `pig/db/ops/ops_linmo_ai_menu.sql`。要点：

- `INSERT ... ON DUPLICATE KEY UPDATE`（**幂等**）。
  ⚠️ **不要**用 `DELETE FROM sys_menu WHERE menu_id=...`：`sys_role_menu` 主键是 `(role_id,menu_id)`，
  删菜单不清授权会留孤儿；不带 `role_id` 的 DELETE 还可能误删非超管授权。
- 授权：`INSERT IGNORE INTO sys_role_menu (role_id,menu_id) VALUES (1,<id>)`（超管）。
- 字段取值对齐同段既有行（`icon` 用 `ele-*`、`menu_type='0'` 叶子、`visible='1'`）。
- 页面类菜单：`path` = `/ops/xxx/index`、`component` = `ops/xxx/index`（**去掉 views/ 前缀、不带 .vue**）。
  解析在 `router/backEnd.ts` 的 `dynamicImport()`：`k.startsWith(\`${component}.vue\`)`，
  **glob 命中 2 个即返回 false** ⇒ 别同时放 `index.vue` 和 `index.ts`。
- 写在末尾的校验 SQL（便于复跑核对）。

### 🔴 `path` 首段必须与父菜单同源（否则面包屑/归属中心串台）

2026-10-15 实测：菜单挂在 **9910「基础工具」（`path=/tools`）** 下，却写成
`path=/ops/schedule/index` ⇒ 前端按**一级路径前缀**分组，面包屑显示成
「**经营中心** / 定时任务总览」，侧边栏也归错组。

⇒ 规则：**子菜单 `path` 的父级前缀 = 父菜单 `path`**。父是 `/tools` 就写
`/tools/schedule/index`，`component` 同步 `tools/schedule/index`，`.vue` 也要
`git mv` 到 `src/views/tools/schedule/`（**目录与 component 对齐**，别留在 `views/ops/`）。
改完必清 Redis 双缓存（阶段 2）才看得到。

### 🔴 sort_order 必须独占（本轮最值钱的判据）

- 实测 `/admin/menu` 的 children 顺序 = `sort_order` **升序**（虽 `SysMenuMapper.xml` 写的是 `DESC`，
  后端构树时又排了一次），但**同值时的相对顺序不稳定**：
  清 Redis 缓存连测三轮，同一对同值菜单出现**两种位次**（6076/6003 得 3/4/3；6033/6020 也来回换）。
- ⇒ **要精确落位，必须给一个独占的 `sort_order`**。列类型是 `int`，**没有小数可用**。
- ⇒ 若目标位置两边都是紧邻的整数（如要在 4 与 5 之间），唯一办法是**让后面那批各后移一位**，
  并把让位**同时写进 owner 脚本与守卫** —— 只改一处，另一边重跑就把值写回去、又变并列。
- 复核口径：**清缓存 → 请求 `/admin/menu` → 连测三轮**比位次是否一致。

---

## 阶段 2：库里执行（最小改动）

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"   # 本机 docker 不在 PATH
docker exec -i linmo-mysql mysql -uroot -proot pig < pig/db/<新脚本>.sql
```

🔴 **只做增量时，用最小 `UPDATE`/`INSERT`，别重跑 `ops_agent.sql`** ——
它是 `DELETE ... BETWEEN 6000 AND 6099` + 重插 34 条，会连带删掉另外 4 个 owner 的行
（靠守卫补回，但那是"先破坏再修复"）。改 sort 就 `UPDATE sys_menu SET sort_order=... WHERE menu_id=...`。

### 清 Redis DB5（两处都要清，只清前者前端仍看不到）

```bash
python - <<'PY'
import redis
r = redis.from_url("redis://127.0.0.1:6380/5")
for p in ("gl:menu_details*", "gl:user_details*", "site_config_details*"):
    ks = list(r.scan_iter(match=p, count=500))
    if ks: r.delete(*ks)
    print(p, len(ks))
PY
```

⚠️ 别用 `--scan | while read` 或 `for k in $KEYS`（zsh 不按换行分词 ⇒ 静默无效）。

---

## 阶段 3：让变更持久化（别漏）

- **`pig/db/initdb-loader.sh`**：把新脚本登记进 `ORDER` 数组（**不登记会被兜底追加到末尾并告警**）。
  位置要满足依赖：挂在 6000 下的要排在 `ops_agent.sql` 之后；会被守卫纳管的要排在守卫**之前**。
- **两处装载都是通配，新文件无需改配置**：
  - MySQL 镜像：`pig/db/Dockerfile` 里 `COPY . /opt/pig-db/`（递归收子目录）；
  - boot 包：`pig/pig-boot/pom.xml` 的 `copy-db-scripts` 把 `${basedir}/../db/**/*.sql` 拷到 `outputDirectory/db`
    （**必须 `**/*.sql`**：`*.sql` 只匹配一层，2026-10-13 搬目录后会**静默打进 0 个脚本**；
    同时 exclude `manual/**` 与 `merged/**`。服务端 `DbUpgradeService` 用 `classpath*:db/**/*.sql` 扫）。
- **新脚本放哪个子目录**：2026-10-13 起 `pig/db/` 按功能域分域（`common/ ai/ kb/ ops/ hr/ industry/
  project/ connector/ market/ rd/ media/ biz/`）——菜单脚本归 **`ops/`**，别放顶层。不同域**不得同名**。

### 🔴 `pig/db` 是合并生成物 —— 新脚本必须走 3 步才能进镜像

2026-10-15 实测：`pig/db/` 下的 `01~06*.sql` **不是手写文件**，而是
`pig/db_bak/` 里 180 个脚本按 `ORDER` 保序切段、由 `tools/consolidate_db.py` 生成的合并物。
**只往 `pig/db_bak/` 加文件 + 登记 `ORDER` 不够**，新脚本不会出现在 `pig/db` 里 ⇒ 也不进镜像/initdb。

```bash
# ① 脚本落 pig/db_bak/<域>/ ，并把文件名加进 pig/db_bak/initdb-loader.sh 的 ORDER 数组
# ② 改 tools/consolidate_db.py 的 SEGMENTS：把该段「末个脚本」的结束序号 +1
#    （合计必须仍等于 ORDER 条数，否则自检报错）
# ③ 重跑并验证
python tools/consolidate_db.py --verify        # 期望：脚本数 == ORDER 条数、自检通过
git diff --stat pig/db/                        # 应看到且仅看到 1 个段文件变化
```

🔴 **重生成会改掉全部 6 个合并文件**（每个文件头都嵌了 ORDER 指纹）⇒
`sys_db_migration` 里的 6 条 baseline 的 `checksum` 全部失效 ⇒ **在线升级会整批重跑**。
修：

```bash
python output/db-backup/gen_migration_baseline.py     # 重算 sha256 → output/db-backup/migration-baseline.sql
docker exec -i linmo-mysql mysql -uroot -proot pig < output/db-backup/migration-baseline.sql
# 复核：6/6 checksum 与 pig/db/0*.sql 实际值一致
```

⚠️ **重置库后**同样要把这 6 个合并文件名作 baseline 写进 `sys_db_migration`
（`status=SUCCESS, cost_ms=0` = 只记账不执行），否则升级页会整批重跑。
- ⚠️ **boot 未重建 ⇒ 「数据库升级」页面看不到新脚本**。但如果已登记进守卫的 ①，**功能不会丢**
  （守卫会在每次 `ops_agent.sql` 变更时把它补回来）。要不要重建 boot 取决于是否要走升级链路，属取舍项。

---

## 阶段 4：前端构建与部署

| 端 | 类型 | 生效方式 |
|---|---|---|
| pig-ui 8888 | nginx 容器托管构建产物 | **必须 rebuild 镜像 + `--force-recreate`** |
| pig-pc-ui 8890 | 同上（`--profile pcui`） | 同上 |
| pig-mob-ui 8899 | 本机 Vite dev | 改文件**即时生效**，无需构建 |

```bash
docker compose --profile pcui --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml build --progress plain pig-ui pig-pc-ui   # 命令 1
docker compose --profile pcui --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml up -d --force-recreate --no-deps pig-ui pig-pc-ui   # 命令 2
```

🔴 **build 与 up 必须分两条命令**（`up --build` 沿依赖链重建 ⇒ 打断 boot 连接池）；
**加 `--no-deps`** —— 否则 `--force-recreate` 会连带重建被依赖服务。
**两个 env-file 都要带**、**别带 `.env.mac`**（8888 静默消失）。

🔴 `build --progress plain` 用来判「镜像是否真吸收了本次改动」：看 RUN/COPY 步是否全 `CACHED`。
⚠️ **全 CACHED 也可能产出新镜像 ID**（标签↔容器漂移，见下），所以 CACHED 不等于"没生效"，
要配合内容级探针（`docker exec <c> grep -rl "<本次新增的文案>" /data/assets`）判定。

### 回读对账（`--force-recreate` 只重建容器，不重建镜像）

```bash
echo "container=$(docker inspect -f '{{.Image}}' linmo-pig-ui)"
echo "image    =$(docker image inspect -f '{{.Id}}' linmo/pig-ui:1.0.0)"
```

两者不相等 = 容器停在旧镜像（`docker ps` 仍显示 healthy 骗人）。

⚠️ **别用 `set -- $pair` 拆字符串**：zsh 不做变量分词 ⇒ 两个变量都空 ⇒ 假"一致"。

---

## 阶段 5：探针复验（三端各跑一次）

用 `output/audit/probe_linmo_ai.cjs` 作模板。判据（**缺一不可**）：

1. **非 404**：文本不含「页面不存在」类文案；
2. **壳与内容都在**：根容器有尺寸（`clientWidth > 0`）**且**内部特征元素存在
   （如 `textarea.lm-input`）—— 只看"DOM 有节点"会把「组件没挂上、只剩外壳」误判为通过；
3. **关键交互元素在首屏内**：`el.getBoundingClientRect().bottom <= innerHeight`。
   移动端尤其重要：原型是桌面双栏，375px 下输入框会被顶到 600px 开外；
4. **无横向溢出**：根容器 `scrollWidth - clientWidth === 0`（**别用 `<= 8` 放过**，见下）；
5. **console error / pageerror / requestfailed 为空**（⚠️ **先记录基线**：登录后进页面前先数一次，
   只算「新增」的错误 —— 项目里存在**既有**报错，如菜单 6084「业务功能绑定」缺组件）。

### 🔴 横向溢出：必查，且「一端正常」不能当通过

2026-10-15 实测同一页面：**pcui 报 `rootOverflowPx = 6`，ui 报 `0`** —— 两端外层布局宽度不同
（`rootClientWidth` 实测 1440 vs 1460），同一处溢出**一端暴露、另一端被吸收**。

**真凶几乎总是 `el-row :gutter="N"`**：它给行加 `-N/2` 的负外边距，行宽 = 容器 + N ⇒ 根容器溢出。
（本次一开始怀疑表格列宽合计过大，收窄 10 列后**溢出仍是 6px** —— 方向错了。）

修法（二选一）：
- ✅ **改 CSS Grid**：`.stat-grid { display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap:12px }`
  + 断点（1199px→3 列、767px→2 列）。`minmax(0,1fr)` 不会撑破容器。**推荐**。
- ✅ 给卡片外层容器补 `padding: 0 6px`（吸收负边距）。

⚠️ **别把「表内裁剪」当根溢出**：`el-table` 定宽列里的 `<code>` 长文本（如
`productionJob.triggerMonthlySummary`）测得 right 超根边界 24~39px，属**表内裁剪**，不计入根溢出。
`el-table` 用 `min-width` 列时余量会自动分配 ⇒ 想消除「表内横向滚动条」，把**所有列合计**压到
容器内即可（本轮 1470 → 1336），保留 2~3 个 `min-width` 列吸收余量，别全给死宽度。

**诊断脚本**（直接给最毒的元素，别自己写）：
```bash
cd ~/.workbuddy/binaries/node/workspace
/Users/shan/.workbuddy/binaries/node/versions/22.22.2-3/bin/node diag-overflow.mjs http://localhost:8890
```

⚠️ **每页先 `about:blank` 再 `goto`**（SPA 只切 hash 不重载，否则测到上一页 DOM）。

**三端各跑一次**：「A 端 0 失败」推不出「B 端 0 失败」（同源≠同观感）。

### 功能链路要单独端到端

页面渲染 PASS ≠ 功能通。用 `output/audit/e2e_linmo_ai_chat.cjs` 作模板：
真浏览器输入 → 点发送 → 等流式结束（光标消失 + 文本长度连续 3 次不变）→ 断言回复非空。
也可先用 `curl -N` 直接打后端 SSE 端点确认代理链路：
```bash
curl -sN --noproxy '*' -X POST http://localhost:8888/api/ai/v1/chat \
  -H "Authorization: Bearer $(cat output/pig-token.txt)" -H 'Content-Type: application/json' \
  -d '{"query":"你好","app":"","conversation_id":"","user":"linmo-portal","response_mode":"streaming"}'
```

---

## 移动端适配（只在 mob-ui 做）

`views/linmo/linmo-port.css` 是**原型生成物，勿手改**；`views/linmo/linmo-mobile.css` 是
**只有 mob-ui 有**的收口层 ⇒ 加规则加在这里，用 `html.is-mobile #linmo-b2b-mockup ...` 前缀
（同带 `#linmo-b2b-mockup` ⇒ 特异性更高，能压过生成物，且与 import 顺序无关）。

原型 AI 对话是双栏 `grid-template-columns:minmax(250px,286px) minmax(0,1fr)`，375px 下对话区只剩 ~37px。处置：
- 单列 + **`order` 反转**把 `.lm-ai-chat` 提到前面（**首屏必须先看到输入框**）；
- `.lm-ai-chat` 用**定高**（`min-height` + `max-height: calc(100vh - 190px)`）而不是只有 min-height ——
  它内部是 `auto / minmax(0,1fr) / auto` 三行网格，**只有外层高度确定时中间行才收缩并滚动**；
- 快捷问题由换行改**单行横向滚动**（省高度、保入口）；会话栏 `order:1` 沉底 + `max-height:30vh` 自滚。

---

## 反模式

- ❌ 没确认三端是否同源就开工 —— `/ai/chat` 三端不是同一个页面
- ❌ 漏 `id="linmo-b2b-mockup"` —— 原型样式全落空
- ❌ 子菜单 `path` 不跟父菜单前缀同源（父 `/tools` 却写 `/ops/...`）—— 面包屑/侧边栏归错中心
- ❌ 往 6000 段插菜单却不登记守卫 —— 哨兵 CHECK 违例会停掉整批升级
- ❌ 加了 `pig/db_bak/` 脚本就以为完事 —— 不重跑 `consolidate_db.py` 不进 `pig/db`/镜像/initdb
- ❌ 重跑 `consolidate_db.py` 后不刷 `sys_db_migration` baseline —— 在线升级整批重跑
- ❌ 给菜单用「与别人相同的 sort_order」又期望位置固定 —— 同值位次不稳定，必须独占
- ❌ 只改 owner 脚本不改守卫（或反之）的让位 —— 另一边重跑就把值写回去
- ❌ 改库里几个 sort 却重跑 `ops_agent.sql` —— 整段 DELETE 先破坏再靠守卫补
- ❌ 清缓存只清 `gl:menu_details*` —— 还要清 `gl:user_details*`
- ❌ 只 `build` 不 `up --force-recreate`，或只 `up` 不 `build` —— 前者老镜像、后者旧容器
- ❌ `--force-recreate` 不带 `--no-deps` —— 会连带重建被依赖服务
- ❌ 用 `set -- $pair` 拆字符串比对镜像 —— zsh 不分词，会给你假的"一致"
- ❌ 探针只判"DOM 有节点" —— 要判关键交互元素存在**且在首屏内**
- ❌ 横向溢出只查 `main` / 只怀疑表格列宽 —— 真凶多为 `el-row :gutter` 负外边距
- ❌ 横向溢出「A 端 0 就宣布通过」—— 两端 `rootClientWidth` 不同，**一端会掩盖另一端**
- ❌ 把 console 既有报错算到本次 —— 先取基线、只比新增
- ❌ 把「pig-ui 不显示面包屑」当 bug 修 —— `pig-ui` 是 **classic 布局**，PIG 原生
  在 `layout==='classic'||'transverse'` 时 `isShowBreadcrumb=false`，**只有 pcui 显示面包屑**
- ❌ 页面 PASS 就宣布调通 —— 功能链路（SSE 收发）要单独端到端
- ❌ 三端只跑一端 —— 同源≠同观感
