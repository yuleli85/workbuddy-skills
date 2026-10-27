---
name: linmo-403-permission-triage
description: 排查灵猫企管（linmo-pig-full）里「页面能打开、点进去/切换页签报 403 Forbidden」的授权断链问题，并交付幂等的补齐授权脚本。当用户贴出形如 `https://pc.mzlc.me/api/admin/... 403 Forbidden`、说「XX 页面 403」「权限不足」「普通用户打不开」「管理员能开普通用户不行」，或要求「把权限补上/授权」时使用。
agent_created: true
---

# 灵猫企管 403 授权断链排查

## 0. 先记住三条判据（能省一半时间）

1. **403 ≠ 没登录。** 后端 `GlobalBizExceptionHandler` 产出 `{"code":1,"msg":"权限不足，不允许访问"}`；
   **不带 token 时全站是 `424 token expired`** ⇒ 用户能看到 403 = 鉴权通过、**授权失败**。
   前端源码 grep「权限不足」恒 0 命中，别误判成前端问题。
2. **权限判定走 Redis db5 缓存，TTL = -1。** `gl:user_details::<username>` / `gl:menu_details::<roleId>`
   **永不过期** ⇒ **只改 `sys_role_menu` 不清缓存 = 白改**。
3. **根因通常是「新菜单只授了 role 1」。** 新建菜单脚本只写 `INSERT INTO sys_role_menu (role_id=1, …)`
   ⇒ 管理员能开、普通用户（role 2）恒 403，且**逐页连报**（用户会一个个贴 URL 过来）。

## 1. 定位权限点（代码侧，30 秒）

```bash
# 拿报障 URL 的路径段去后端找 controller（URL 里 /api/admin/ 是网关前缀，真实映射去掉它）
# 例：/api/admin/ops/agent/industry/page  →  @RequestMapping("/ops/agent/industry") + @GetMapping("/page")
```
- 打开命中的 Controller，读方法的 `@HasPermission("…")` ⇒ 这就是需要的权限点。
- **同一 Controller 的多个方法常共用同一权限点** ⇒ 用户贴第二个 URL 时先比对，多半是同一件事，别重复劳动。

## 2. 线上实测（区分「接口坏」还是「授权缺」）

用 `agent-browser` 或 Playwright 起真实浏览器，admin 登录后 fetch 该接口：

```js
// 模板见 /tmp/verify/*.mjs（历史脚本），关键片段：
let auth = null;
p.on('request', r => { const h = r.headers()['authorization'];
  if (h && r.url().includes('/api/admin')) auth = h; });
// 登录 admin/123456 后：
const r = await p.evaluate(async ({h,u}) => {
  const x = await fetch(u, { headers: { Authorization: h } });   // 🔴 evaluate 只收 1 个参数，必须包对象
  return { s: x.status, b: (await x.text()).slice(0,300) };
}, { h: auth, u: '/api/admin/ops/agent/industry/page?current=1&size=20' });
```
- **admin 200 ⇒ 接口健康，纯授权问题**（→ 第 3 步）
- admin 也 403 ⇒ 该权限点在 `sys_menu` 里根本没有行（见第 5 步「权限点未落菜单」）

同时读两个角色的菜单树（`/api/admin/menu/tree/1` 管理员、`/api/admin/menu/tree/<uid roleId>` 普通用户）：
```js
const ids = await p.evaluate(async ({h}) => (await (await fetch('/api/admin/menu/tree/2',
  {headers:{Authorization:h}})).json()).data, {h: auth});
// HAS_6075=false ⇒ 该权限点没授给 role 2 ⇒ 就是它
```
另可 `GET /api/admin/user/page?current=1&size=50` 看线上有哪些账号。

## 3. 用本机库反推「会 403 的完整清单」（不必连线上库）

关键前提：**线上 `role 1` 菜单树条数 == 本机 `sys_menu` 总数**（2026-10-07 实测都是 **397**）⇒ 结构一致，可用本机库反推。

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:$PATH"
docker exec linmo-mysql mysql -uroot -proot -N -e "
use pig;
SELECT m.menu_id, m.parent_id, m.name, m.permission
FROM sys_menu m
WHERE m.permission IS NOT NULL AND m.permission <> '' AND m.del_flag='0'
  AND m.menu_id NOT IN (<线上 role 2 的菜单 ID 列表>)
  AND m.parent_id IN (<线上 role 2 的菜单 ID 列表>)      -- ← 父已授权、本级漏授 = 真断链
ORDER BY m.parent_id, m.menu_id;"
```
- 有现成工具：**`tools/audit_permission_menu.py`**（注解权限点 ↔ `sys_menu` 全量对账，`--role N` 指定角色，`--json` 输出机器可读）。它查的是本机库。
- 判断「批量漏授」还是「有意最小权限」：查 `create_time`。**同一秒批量新建 = 批量漏授**。

## 4. 交付幂等授权脚本

模板（**复制改 `permission IN (...)` 即可**，参考 `pig/db/common/20261007_role2_view_perm_grant.sql`）：

```sql
INSERT INTO sys_role_menu (role_id, menu_id)
SELECT 2, m.menu_id
FROM sys_menu m
WHERE m.permission IN ('…', '…')
  AND m.del_flag = '0'
  AND EXISTS (SELECT 1 FROM sys_role r WHERE r.role_id = 2)
  AND NOT EXISTS (SELECT 1 FROM sys_role_menu rm WHERE rm.role_id = 2 AND rm.menu_id = m.menu_id);
```

**必须做**：
1. **事务 + 回滚验证**（不落库）：
   ```bash
   docker cp <脚本> linmo-mysql:/tmp/g.sql
   docker exec linmo-mysql mysql -uroot -proot -N -e "use pig;
   SELECT CONCAT('BEFORE=',COUNT(*)) FROM sys_role_menu WHERE role_id=2;
   START TRANSACTION; SOURCE /tmp/g.sql;
   SELECT CONCAT('AFTER_1ST=',COUNT(*)) FROM sys_role_menu WHERE role_id=2;
   SOURCE /tmp/g.sql;
   SELECT CONCAT('AFTER_2ND=',COUNT(*)) FROM sys_role_menu WHERE role_id=2;  -- 幂等：两次相等
   ROLLBACK;
   SELECT CONCAT('AFTER_ROLLBACK=',COUNT(*)) FROM sys_role_menu WHERE role_id=2;"
   ```
2. **落位 + 登记**：授权脚本归 **`pig/db/ops/`** 域（2026-10-13 起 `pig/db/` 按功能域分子目录；
   纯基础/账号权限类可归 `common/`，如模板 `20261007_role2_view_perm_grant.sql` 就在 `common/`）。
   再**登记进 `pig/db/initdb-loader.sh` 的 ORDER**（`ORDER` 只写文件名，与子目录解耦；
   放在建出这些菜单的脚本**之后**，通常在 `ops_center_menu_restore.sql` / `mzlc_enterprise_agent.sql` 之后）。
   ⚠️ 不同子目录不得同名 —— loader 按 basename 寻址，重名直接 `exit 1`。
3. **分级处理**，不要无脑全授：
   | 级别 | 判据 | 处置 |
   |---|---|---|
   | 只读查看 | `*_view` / 名称含「查看/查询」 | 直接授，风险低 |
   | 写操作 | adopt/reject/regen/urge/transfer/verify/sediment/exec/edit/handle | **要产品确认** |
   | 授权管理 | `*_admin`（如 `ai_finance_admin`） | 不授普通用户 |
   | 整段未授权 | `parent` 也不在角色里 | 非断链，预期状态 |

## 5. 在已运行的库上生效（三步，缺一不可）

```bash
# ① 执行授权
docker exec -i <mysql> mysql -uroot -p<pwd> pig < pig/db/ops/<脚本>.sql
# ② 清权限缓存（db5）——不清 403 不消失
docker exec <redis> redis-cli -n 5 --scan --pattern 'gl:user_details::*' | xargs -r -I{} docker exec -i <redis> redis-cli -n 5 del {}
docker exec <redis> redis-cli -n 5 --scan --pattern 'gl:menu_details::*'   | xargs -r -I{} docker exec -i <redis> redis-cli -n 5 del {}
# ③ 用户重新登录
```
> ⚠️ macOS 的 `xargs` 是 BSD 版（无 `-r`），上面是给 Linux 服务器的；本机执行请把 `--scan` 结果拼成 `del`。
> ⚠️ **线上 `pc.mzlc.me` 是独立部署**：实测「线上触发 403 不写入本机 `sys_security_event`」、本机无 443 监听/无 cloudflared ⇒ **本机改库不影响线上**，必须拿到线上执行通道。

## 6. 两个易踩的伴生坑

1. **权限点未落菜单**：Controller 有 `@HasPermission("x")` 但 `sys_menu` 里**没有**对应行 ⇒ **连管理员都 403**。
   判据：`select count(*) from sys_menu where permission='x';` 为 0。
   常见成因：菜单清理脚本（`menu_cleanup_unused_*.sql`）以「`visible='0'` 没用」为由物理删除，但权限点是**接口的判定依据**。
   处置：优先用清理脚本留下的备份表（`sys_menu_bak_<date>`）`INSERT IGNORE … SELECT` 精确还原，**别手写 menu_id**。
2. **前端不按权限过滤页签**：`AgentReport.vue` 只按 `agentCode` 切页签 ⇒ 无权限页签照样能点、然后静默 403。属 UX 缺陷，正解是「无权限则隐藏/置灰」。

## 7. 交付清单模板

- [ ] 定位：Controller + `@HasPermission` 值（截图/行号）
- [ ] 实测：admin 200 vs 报障账号 403
- [ ] 根因：权限点 menu_id + 哪些角色被授权 + `create_time` 证据
- [ ] 脚本：`pig/db/ops/<日期>_<主题>_grant.sql`（归 ops 域；幂等 + 事务验证输出）
- [ ] 登记：`pig/db/initdb-loader.sh`
- [ ] 报告：`output/403-*-排查-<日期>.md`（分级清单 A/B/C/D）
- [ ] 生效三步 + 「本机≠线上」提醒
