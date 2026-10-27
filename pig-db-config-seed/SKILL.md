---
name: pig-db-config-seed
description: 把 PIG（linmo-pig-full）运行库里「只存在于运行库的配置数据」固化成 pig/db 下的可重放初始化种子 SQL。适用于用户说「把这个页面的配置备份成初始化 SQL」「清库后不能丢」「把 Dify 应用配置存进 pig/db」「把这批配置固化进 initdb」。覆盖取数（docker exec -i + JSON_OBJECT + mysql -N -B -r）、幂等包装（临时表 + NOT EXISTS + 非密钥列按需刷新）、密钥剥离红线（api_key_cipher 只进 output/ 不入库）、initdb-loader.sh ORDER 登记、临时库复验与现网零副作用复跑。
agent_created: true
---

# PIG：把运行库配置固化成 pig/db 初始化种子

目标：**清库（`down -v` / 重建数据卷）后，配置自动回来**；且脚本可重复执行、不泄露密钥。

现成入口：`tools/gen_ai_dify_seed.py`（AI 配置页那一份已落地，照它改列名即可复用）。

## 判据（先想清楚再动手）

1. **哪些数据需要固化**：凡「运行库写入 + 清库即丢 + 重同步拿不回」的才算。
   例：`/ai/config` 的应用清单来自 `sync-from-dify`（可再同步），但人工调过的
   `enabled` / `base_url` / `model_code` 同步**不会**带回来 ⇒ 值得固化。
2. **🔴 密钥不入库**：`api_key_cipher` / `dataset_key_cipher` 用 `security.encode-key`
   （仓库内可读的约定值）可解 ⇒ 进 git 等于裸密钥入版本库。
   - 入库版（`pig/db/**/*.sql`）：**剥离**密钥列，并在文件头注释里列出「已配密钥的 app_code」，
     提醒导入后去控制台补 Key（否则报 `app_key_not_configured`）。
   - 完整版（含密文）：写 `output/db-backup/<date>/xxx_full.sql` —— `output/` 被 .gitignore
     整体忽略，**禁止 `git add -f`**。
3. **(app_code, tenant_id) 不是唯一键**（只是普通索引）⇒ 不能用 `ON DUPLICATE KEY`，
   必须显式 `NOT EXISTS`。
4. **幂等契约**：不 DELETE、不覆盖既有行、**不碰 del_flag**（软删行不被复活）、
   非密钥列仅在值真变了时才 UPDATE（`<=>` 做 NULL 安全比较，避免每次重跑刷 `update_time`）。

## 取数（三个已踩过的坑）

```bash
P=~/.workbuddy/binaries/python/envs/default/bin/python
$P tools/gen_ai_dify_seed.py            # 生成两份产物
```

- **Docker 不在 PATH** ⇒ 用 `/Applications/Docker.app/Contents/Resources/bin/docker`（脚本里已兜底）。
- **SQL 走 stdin**（`subprocess.run(cmd, input=sql)` + `docker exec -i`）。
  拼进 `sh -c "…"` 时反引号会被当**命令替换**执行，实测把 `` `ai_app_config` `` 变成空串，
  报 `ERROR 1064 near 'WHERE 1=1'`。
- **必须 `mysql -N -B -r`**：默认 batch 模式会把输出里的引号再转义一层，
  JSON 里的 `\"` 变成 `\\"`（反斜杠 + 提前闭合引号），Python `json.loads` 报
  `Expecting ',' delimiter`。`--raw` 关掉这层转义。
- 行数据用 `JSON_OBJECT(...)` 取：`-B` 制表符输出无法区分 NULL 与字符串 `'NULL'`，
  且列内含制表符/换行会串列。datetime 列用 `DATE_FORMAT(...,'%Y-%m-%d %H:%i:%s')` 去 `.000000`。
- SQL 字面量转义：`\` → `\\`、`'` → `\'`、换行 → `\n`（脚本内 `sql_str()` 已实现）。

## 幂等包装模板（单块 SQL）

```sql
DROP TEMPORARY TABLE IF EXISTS `tmp_seed`;
CREATE TEMPORARY TABLE `tmp_seed` (…列…);          -- 只放种子需要的列
INSERT INTO `tmp_seed` (…) VALUES (…), (…);

-- 新增：不存在才插
INSERT INTO `目标表` (…)
SELECT … FROM `tmp_seed` s
 WHERE NOT EXISTS (SELECT 1 FROM `目标表` t
                    WHERE t.`业务键` = s.`业务键` AND t.`tenant_id` = s.`tenant_id`);

-- 刷新：只动非密钥列，值没变不写
UPDATE `目标表` t JOIN `tmp_seed` s ON …
   SET t.`列` = s.`列`, …, t.`update_time` = NOW()
 WHERE t.`del_flag` = '0'
   AND NOT (t.`列` <=> s.`列` AND …);
DROP TEMPORARY TABLE IF EXISTS `tmp_seed`;
```

多表（如 `ai_app_config` + `ai_model_config`）＝把上面整块复制一遍换列名。

## 必做的两步登记 / 复验

1. **落位 + 登记**：脚本放进**对应功能域子目录**（2026-10-13 起 `pig/db/` 已分域：
   `common/ ai/ kb/ ops/ hr/ industry/ project/ connector/ market/ rd/ media/ biz/`；
   AI 应用/模型配置归 `ai/`，菜单归 `ops/`，KB 归 `kb/`），再**登记 `pig/db/initdb-loader.sh`
   的 `ORDER`**（`ORDER` 只写文件名，与子目录解耦），位置在它依赖的建表脚本之后
   （AI 那份排在 `ai_app_sync_v2.sql` 之后，因为该文件才补出 `dify_mode`/`dify_status`）。
   未登记 ⇒ 仍会执行（兜底按字典序追加到末尾）但**顺序不受控**，且日志会刷提醒。
   ⚠️ 不同子目录**不得出现同名脚本** —— loader 按 basename 寻址，重名会直接 `exit 1`。
2. **临时库复验**（别拿现网库当试验田）：

```bash
D=/Applications/Docker.app/Contents/Resources/bin/docker
$D exec -i linmo-mysql mysql -uroot -proot -e "
 DROP DATABASE IF EXISTS seed_check;
 CREATE DATABASE seed_check DEFAULT CHARACTER SET utf8mb4;
 CREATE TABLE seed_check.t LIKE pig.t;"        # 每个目标表一行 LIKE
$D exec -i linmo-mysql mysql -uroot -proot seed_check < pig/db/<域>/xxx_seed.sql   # ① 空表插入
$D exec -i linmo-mysql mysql -uroot -proot seed_check < pig/db/<域>/xxx_seed.sql   # ② 幂等复跑
# ③ 负向测试：手工改坏一行 + 塞一个 api_key_cipher 哨兵 ⇒ 复跑后元数据被修回、密钥不被覆盖
```

3. **现网库复跑零副作用**：比对 `count(*) / 密钥非空数 / md5(group_concat(id, 更新时间))` 前后一致；
   再打一次页面接口（如 `/admin/ai/apps/page` 的 `data.total`）确认行数吻合。
4. 脚本头含 `DROP DATABASE` 会被 loader **内容级拒执行** ⇒ 生成物里别出现这几个字。

## 常见误判

- 「种子导入成功」≠「页面看到」：`ai_app_config` 有 Redis 缓存路径的页面（菜单/权限）才要清缓存，
  纯数据表（本类）不用。
- 旧库上跑种子时，`NOT EXISTS` **不看 del_flag** ⇒ 只有软删行的 app_code 不会被复活（这是有意的契约）。
- 生成器会覆盖 `pig/db/**/*.sql` ⇒ **别手改生成物**，改脚本再重跑。
