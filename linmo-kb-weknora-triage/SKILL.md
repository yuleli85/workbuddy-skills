---
name: linmo-kb-weknora-triage
description: 排查灵猫企管（linmo-pig-full）知识库/WeKnora 接入故障并修到可用 —— 覆盖 `412 weknora_not_configured`、`404 weknora_kb_not_found`、KB 页面无数据/报「未配置」、`available:false`（桥 fail-closed）。当用户贴出「WeKnora 管理域未配置：请检查 deploy/.env.dev 的 WEKNORA_BASE_URL / WEKNORA_API_KEY」「kb_binding 中的 KB UUID 与 WeKnora 实际不一致」「知识库页面打不开」，或要求「把知识库配好」「补齐 WEKNORA 变量」时使用。核心价值：把「配置类报错」拆成**三层不同根因**（L1 密钥/base_url、L2 绑定 UUID 漂移、L3 代码 bug），并给出各自的幂等修法与实测证据，同时严守「真密钥只进 gitignored deploy/.env」这条安全红线。
agent_created: true
---

# 灵猫企管：KB / WeKnora 接入故障排查

> 首次实战：2026-10-12。`weknora_not_configured` 看着像「填两个变量就行」，实际叠了两层根因，且**报错文案本身会误导你**（它只说「未配置」，不校验 base_url 可达性）。

## 0. 先按症状分层（别一上来就补变量）

| 症状 | 层 | 根因 | 修法 |
|---|---|---|---|
| `412 weknora_not_configured`（管理域） | **L1a** | `WEKNORA_BASE_URL` 或 `WEKNORA_API_KEY` 为空 | 见 §2 |
| 同上（检索域另报） | **L1b** | `WEKNORA_RETRIEVE_API_KEY` 为空 | 见 §2 |
| 管理域能列库，但页面 404 | **L2** | `kb_binding.weknora_kb_id` 与实例实际 UUID 不一致 | 重放种子，见 §3 |
| 页面能开但文档列不出 | **L2** | 同上 | 同上 |
| 桥（Dify 外部知识库）503 / `available:false` | **L4** | `KB_BRIDGE_TOKEN` 为空（fail-closed） | 补令牌（须与 Dify 侧同值） |
| `GET /internal/v1/kb/reconcile` 恒返回 `{"kbs":[]}` | **L3** | python-ai 代码 bug（§4） | 改码 + 重建 |

🔴 **L1 与 L2 常同时存在**：先修 L1，才会暴露 L2。修完 L1 一定要把 PIG 侧 `library/{id}/documents` 也打一遍，别停在「无 token 变 200」。

## 1. 拓扑与落点（先记住，别猜）

| 项 | 值 |
|---|---|
| 权威 WeKnora 实例 | **`https://we.linmo.xin/api/v1`**（含 `/api/v1`，client 直接在其后拼路径） |
| 已死实例 | **`https://we.mzlc.me/api/v1`** —— 带不带 Key **都 502**（Cloudflare 上游不可达） |
| 本地 WeKnora | `WeKnora-*` 7 容器（`:18080` UI / `:8083`），**当前未运行**；须 `--profile neo4j --profile minio` 两阶段起 |
| `WEKNORA_BASE_URL` 落点 | `deploy/.env.dev`（**非密**，可入库）；compose 默认值也是 `we.linmo.xin` |
| 两枚真 Key 落点 | 🔴 **gitignored 的 `deploy/.env`**（不是 `.env.dev`！见 §5 红线） |
| 生效方式 | `up -d python-ai` —— **recreate**；`restart` **不重读** env-file |
| 判据：实例是否在跑 | 无 Key 打 `{base}/knowledge-bases` → **401 = 在跑**；**502 = 上游死** |
| 判据：base_url 选哪个 | 拿它的库 UUID 与仓库 **`pig/db/kb/kb_binding_seed.sql`** 比对，**逐字一致**的才是权威（全新 initdb 就该得到它） |

启动口径（两个 `--env-file`，**顺序不能反**，后者覆盖前者）：

```bash
cd <repo>/   # 必须是运行中容器所属的那份副本，见 linmo-stack-rebuild-reset §0.0
docker compose --env-file deploy/.env.dev --env-file deploy/.env \
  -f deploy/docker-compose.dev.yml --profile pcui up -d python-ai
```

## 2. 修 L1：base_url / 密钥

1. **先判 base_url 是否可达**，别假设「有值就是对的」：
   ```bash
   for h in we.linmo.xin we.mzlc.me; do printf '%s → ' "$h"; \
     curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' --max-time 12 "https://$h/api/v1/knowledge-bases"; done
   # 401 = 在跑；502 = 死（换掉）
   ```
2. **改 `deploy/.env.dev`**：把 `WEKNORA_BASE_URL` 指向可达实例；顺手加注释警示「本文件被 git 跟踪、禁写真密钥」。
3. **真密钥写 gitignored `deploy/.env`**。密钥可能已存在于 git 历史（本项目发生过 P0 泄漏），可取回而不必找管理员：
   ```bash
   # 找泄漏提交：git log --all --oneline -- deploy/.env.dev
   MK=$(git show <commit>:deploy/.env.dev | grep -E '^WEKNORA_API_KEY=' | cut -d= -f2-)
   RK=$(git show <commit>:deploy/.env.dev | grep -E '^WEKNORA_RETRIEVE_API_KEY=' | cut -d= -f2-)
   [ -n "$MK" ] && [ -n "$RK" ] && { printf 'WEKNORA_API_KEY=%s\nWEKNORA_RETRIEVE_API_KEY=%s\n' "$MK" "$RK"; } >> deploy/.env
   ```
   🔴 全程用 shell 变量流转，**不要 echo 明文**（密钥会落进会话记录/日志）。
4. **先验证密钥再重建**（省一轮）：
   ```bash
   curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' -H "X-API-Key: $MK" https://we.linmo.xin/api/v1/knowledge-bases  # 期望 200
   ```
5. 重建容器 + 校验注入：
   ```bash
   docker exec linmo-python-ai sh -c 'for k in WEKNORA_BASE_URL WEKNORA_API_KEY WEKNORA_RETRIEVE_API_KEY; \
     do v=$(eval echo \$$k); printf "%s len=%s\n" "$k" "${#v}"; done'
   # 期望：base_url len=27（https://we.linmo.xin/api/v1）、两 Key len=46
   ```

## 3. 修 L2：绑定 UUID 漂移

症状：管理域能列库，但 PIG 报 `404 weknora_kb_not_found; kb_binding 中的 KB UUID 与 WeKnora 实际不一致`。

```bash
# 查当前（错）值与期望值
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
  -e "SELECT binding_id,secret_level,weknora_kb_id FROM pig.kb_binding ORDER BY binding_id;"'
grep -E "^VALUES|'" pig/db/kb/kb_binding_seed.sql   # 期望值（= 权威实例的 UUID）

# 备份 → 幂等重放
ts=$(date +%Y%m%d-%H%M%S); mkdir -p ~/.linmo-bridge/backups
docker exec linmo-mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" pig kb_binding' \
  > ~/.linmo-bridge/backups/kb_binding-$ts.sql
docker exec -i linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < pig/db/kb/kb_binding_seed.sql
```

- 种子是 `INSERT ... ON DUPLICATE KEY UPDATE`（按 `binding_id`），**可重放**；刻意**不 UPDATE `dify_app_code` / `dify_knowledge_id`**（它们是已上线路由键，回退会打断检索）。**不要**自己写裸 `UPDATE` 替代。
- 🔴 常见误判：修后 binding 3/4 仍报错 —— 若文案是「**当前账号密级不足**」，那是**正常鉴权**（该账号没有 SECRET/CONFIDENTIAL 权限位），**不是故障**。只有 `weknora_kb_not_found` 才是 UUID 问题。

## 4. L3：已知代码 bug（`reconcile` 恒空）

- 位置：`python-ai-service/app/weknora/service.py::_extract_kb_ids`
- 现象：它取 `item["kb_id"]`，而 WeKnora 实际返回 **`id`**（`{"data":[{"id": "...", "name": "public", ...}]}`）⇒ 不带 `kb_ids` 参数的 `GET /internal/v1/kb/reconcile` **恒返回 `{"kbs":[]}`**。
- 影响：`KbReconcileJob`（已确认**只读**，无 update/delete）会把每个 PIG 文档都报成「WeKnora 无」⇒ **假告警风暴**，不损坏数据。
- 为什么测试没抓到：`tests/test_weknora_api.py` 的 fixture 也按错形状写（`[{"kb_id": "kb-1"}]`）⇒ 全绿而生产坏。**改代码时 fixture 必须同步改成真实形状**。
- 修法：`ids = [str(item.get("kb_id") or item.get("id")) for item in data if isinstance(item, dict) and (item.get("kb_id") or item.get("id"))]`

## 5. 🔴 安全红线（本项目踩过 P0）

- `deploy/.env.dev` **被 git 跟踪** ⇒ **永不写真密钥**（dev `7ce3fa28` 曾把 `sk-…` 与 64 位 hexToken 写进去并推到 `origin/dev`）。
- 真密钥 → **gitignored `deploy/.env`**；它同时是「覆盖 `.env.dev` 空值」的机制（`--env-file` 后者优先，已实测）。
- 备份 env 文件要**移出仓库**（`~/.linmo-bridge/backups/`），否则 `.env.dev.bak-*` 不在忽略规则里、会污染 `git status` 甚至被提交。
- 修完如实上报「该密钥仍是泄漏过的那一枚，轮换 + `git filter-repo` 清历史仍是待办」。

## 6. 验证清单（缺一项就不算修完）

```bash
TOKEN=$(docker exec linmo-python-ai sh -c 'echo $INTERNAL_AI_TOKEN')
# 1) 管理域（原来报 412 的那个）
curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' -H "X-Internal-Token: $TOKEN" \
  http://127.0.0.1:8090/internal/v1/kb/knowledge-bases            # 期望 200，且能列出 5 库
# 2) 无令牌应被拒
curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8090/internal/v1/kb/knowledge-bases            # 期望 401
# 3) 检索域（走 retrieve Key）
curl -s --noproxy '*' -X POST -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"测试","top_k":3}' \
  http://127.0.0.1:8090/internal/v1/kb/knowledge-bases/<public_kb_id>/search   # 期望 200 真实内容
# 4) PIG 侧真实用户路径（macOS 取 token 见 §7）
curl -s -H "Authorization: Bearer $PIG_TOKEN" \
  http://127.0.0.1:9999/admin/kb/document/library/1/documents      # 期望 200 真实文档
# 5) 浏览器实拍（KB 四页）
node /tmp/verify/kb_after_fix.mjs                                  # bad=False / 0 console 错误
```

## 7. 本机取 PIG token（macOS）

```bash
/Users/shan/.workbuddy/binaries/python/envs/linmo-tools/bin/python tools/pig_login.py admin 123456
# → 写 output/pig-token.txt
```

⚠️ `tools/get_token_win.sh` 是 **Windows 专用**（node 路径写死 `C:/Users/56389/...`）⇒ 在 macOS 上**静默无输出**，别被退出码 0 骗到。
