---
name: menu-page-coverage-audit
description: 审计「菜单点开没有网页 / 空白 / 404 / 报没有匹配到页面组件」，定位是菜单配置错还是前端缺组件副本，并给出补齐或隐藏的处置。当用户说「菜单下没有网页」「菜单点不开」「这个菜单是空的」「菜单丢失/清理菜单」「点菜单报 404」「没有匹配到页面组件」「菜单里有但页面出不来」「清理无用菜单」时使用。覆盖：① sys_menu 字段语义（visible='1' 才是显示、menu_type='0' 才是菜单页）与目录/叶子/外链/按钮四类节点的区分；② 必须模拟前端 backEnd.ts 的组件解析回落（componentPath 优先、否则用 path 推导）——漏掉这一步会把「component 为 NULL 但有网页」的菜单误判为死菜单；③ 双前端工程（主站 + 裁剪客户端）共用一张菜单表时的「单端报错 = 副本缺失」，须两端分别实渲染；④ 处置决策：补齐副本 vs 隐藏 vs 删除（共用菜单表 ⇒ 隐藏会连带另一端起失去入口）；⑤ 收口：重建前端镜像、清 Redis 菜单缓存、浏览器实渲染验证。
agent_created: true
---

# 菜单-页面覆盖审计

## 核心判据

**「菜单下没有网页」不一定真没有网页。** 本项目的前端在 `component` 为空时会**用 `path` 推导组件名**，
所以 `sys_menu.component` 为 `NULL` 的菜单照样能打开。直接按「component 为空」下结论会把好菜单误判成死菜单。

**真正的判据是四要素同时成立**：

```
menu_type = '0'        且
visible   = '1'        且
不是目录节点（无未删除子节点）  且
组件解析失败
```

固定列序的导出（`NULL` 原样导出，不要替换）：

```bash
docker exec <mysql容器> sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B -e \
  "SELECT menu_id,name,path,component,parent_id,menu_type,visible,del_flag \
   FROM pig.sys_menu ORDER BY menu_id;"' > sys_menu.tsv
```

然后跑本技能附带的脚本（把 `--front` 按实际工程名与 views 路径替换）：

```bash
python scripts/menu_page_coverage.py --menu-tsv sys_menu.tsv \
  --front web=./pig-ui/src/views --front pc=./pig-pc-ui/src/views \
  --exclude-prefix linmo/
```

---

## 一、字段语义（踩过才知道的坑）

| 字段 | 值 | 含义 |
|---|---|---|
| `menu_type` | `'0'` | **菜单页**（参与判断） |
| | `'1'` | 按钮/权限点（`component` 恒 NULL，必须排除） |
| `visible` | **`'1'`** | **显示**（建表默认值就是 1） |
| | `'0'` | 隐藏（应排除） |
| `del_flag` | `'0'` | 未删除 |

> 🔴 **`visible='1'` 才是显示**。搞反会得出「全库只有个位数可见菜单」的荒谬前提，
> 并让所有后续结论失效。下手前先用 `SELECT visible, COUNT(*) ... GROUP BY visible` 对一眼数量级。

---

## 二、四类节点必须分开处理

| 类型 | 特征 | `component` 为空 | 判定 |
|---|---|---|---|
| **目录节点** | 有未删除子节点 | 允许（靠 `redirect` 工作） | 正常，**绝不能判为问题** |
| **叶子菜单** | 无子节点 | 不允许 | **问题候选** |
| **外链菜单** | `path` 以 `http` 开头 | 允许 | 正常，走 `link.vue` / `iframes.vue` |
| **`iframe:` 形态** | `path`/`component` 以 `iframe:` 开头 | — | **2026-10-17 起不可路由**：`backEndComponent` 的同源内嵌分支已随 linmo-web 下线删除 ⇒ 点开必兜底 404。这类条目要**单独统计**（不能混进 404 计数，也不能当非路由跳过），处置是下线菜单，不是给前端补 iframe |
| **按钮** | `menu_type='1'` | 恒为空 | 排除 |

判据来源：`src/router/backEnd.ts` 的 `backEndComponent()` —— 现在的处理顺序是
**`http` 外链 → `componentPath` → `path` 推导**，最后才兜底 404。

> 盘点脚本口径：`tools/pc_static_unused2.py --end <pig-ui|pig-pc-ui|pig-mob-ui>`，
> 输出里的 `nonRoutableIframe` 就是上面第四类；**孤儿/死文件必须按端分别跑**，
> 三端不同源，拿 pc 单端结论代表三端会被判错（第 19 轮报告就是这么错的）。
> 另：判「死文件」还要查**构建层** —— `components/IconSelector/index.ts` 被 `vite.config.mts`
> 的 `svgBuilder` 引用，`grep src/` 为 0 也不代表能删；`home/schedule|shortcut/index.vue`
> 被首页挂件引用。删前先跑一次 `npm run build`。


---

## 三、组件解析必须模拟前端回落

```
componentPath 有值  →  用它
否则                →  用 path 去掉前导 '/' 推导  →  views/<path>.vue
```

两条推论：

1. **`component` 为 NULL ≠ 打不开**（只要 `path` 能推导出文件）。
2. 前端 glob 若有**负模式**（如 `import.meta.glob(['../views/**/*.{vue,tsx}', '!../views/linmo/**'])`），
   即使文件存在也装配不出来 ⇒ 用 `--exclude-prefix` 把被排除的前缀传进去。

---

## 四、双前端工程：必须两端分别验证

本项目有两个前端工程（主站 + 裁剪客户端）**共用同一张 `sys_menu` 表**，各自的 `src/views` 覆盖不同。
于是同一份菜单数据会在一端正常、在另一端 404。

**分流判据**：

| 现象 | 结论 |
|---|---|
| 只有一端报「没有匹配到页面组件」 | 该端**缺组件副本** ⇒ 移植遗漏 |
| 两端都报 | 菜单配置错 / 组件真不存在 |

⚠️ 静态比对只能给出「候选」。**必须用浏览器实渲染两端各探一次**，否则会把
「component 为 NULL 但靠 path 推导能打开」的菜单当成故障去清理。

---

## 五、处置决策：先算「清理」的代价

候选确认后，三条路：

| 方案 | 动作 | 代价 |
|---|---|---|
| **补齐副本**（首选） | 复制组件 + 追加其依赖接口 | 需重建前端镜像；若两端 api 文件差异大，**只能段落追加，不可整文件覆盖** |
| **隐藏** | `visible='0'` | 菜单表两端共用 ⇒ **另一端也一起失去入口**（页面代码仍在，可恢复） |
| **删除** | 删 `sys_menu` + `sys_role_menu` + 下线对应 SQL | 不可逆；同样影响两端 |

🔴 **下结论前先确认「另一端是不是好的」**。若另一端本来就正常，「清理」等于把可用功能连同入口一起砍掉 ——
这种情况应改为补齐。

---

## 六、执行顺序

1. **导出 + 静态比对**（上文脚本）→ 得到候选清单
2. **两端实渲染验伪** → 把候选分成「真故障」和「假问题（外链 / path 推导可解）」
3. **定方案**（补齐 / 隐藏 / 删除），把代价讲清楚再动手
4. **改**：
   - 补组件：`cp` 组件本体，**逐段追加**其 api 依赖（追加前先 grep 确认无同名函数）
   - 隐藏/改配置：走 SQL 脚本，脚本要**可重放**（`WHERE NOT EXISTS` / `INSERT IGNORE`），并登记进迁移表
5. **重建**：前端是构建产物镜像 ⇒ 改了 `src/` 必须 `docker compose ... build <服务>` + `up -d --no-deps --force-recreate`
6. **清缓存**：菜单树与用户权限在 Redis 里（本项目是 `db5`：`gl:menu_details::*`、`gl:user_details::*`）
7. **复验**：产物级特征串 + 浏览器实渲染（0 失败请求 / 0 异常 / 页面有真实数据而不只是「没报错」）
8. **提交**：显式指定路径，禁用 `git add -A`（工作区常有并行会话的未提交改动）

---

## 七、坑

- **Redis 键清不掉**：zsh 下 `for k in $KEYS` 不按换行分词 ⇒ `del` 静默无效。用 `xargs` 或 `redis-cli --scan | xargs -r redis-cli del`。
- **重建前端后 nginx 502**：服务名解析到旧上游 IP，属缓存/上游问题，不是本次改动引起的。判据：容器内直连返回正常（甚至 404），经反代却 502。
- **`grep` 可能是代理 shim**：本机 PATH 首个 `grep` 不支持 BRE 交替 `\|`，会让「校验」假报「内容没落地」。校验一律用 Grep 工具或 `grep -E`。
- **同文件并行编辑会丢**：同一文件连续发多个编辑操作，部分会报成功但未生效。逐个改、改完回读。
- **别只看「没报错」**：页面 404 兜底与空白在截图里都不明显。要断言 bodyText 里出现业务特征串（如卡片标题、统计数字），才算真渲染。
