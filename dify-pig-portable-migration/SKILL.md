---
name: dify-pig-portable-migration
description: 让 Dify 工作流在迁移/换机器/换 IP 之后不用改任何工作流 —— 审计 DSL 可移植性断点、改成容器固定名 + squid 主机名白名单、真机验证链路。当用户说「dify 迁移要改什么」「dify 跟着部署」「换机器工作流不用改」「工作流地址写死了」「Dify 调 PIG 报 403 / SSRF protection」「PIG_BASE_URL 怎么填」时使用。
agent_created: true
---

# Dify × PIG 迁移零改动

## 三条底层事实（先确认，别猜）

1. **Dify 工作流环境变量不是容器进程的环境变量**：存在 Postgres 的 `workflows.environment_variables`，每个应用一份。compose 里写 `environment:` 不会变成 `{{#env.XXX#}}`。
2. **`value_type: string` 的 value 会随 DSL 导出/导入**；`value_type: secret` 的 value 恒为 `''`。
   ⇒ 地址可以随 DSL 走（只要值本身环境无关）；密钥必须在导入后注入。这两件事分开治理。
3. **HTTP 节点经 squid 出网**：`api/worker --HTTP_PROXY--> ssrf_proxy(:3128) --> 目标`。
   squid 默认 `http_access deny to_private_networks`；放行由 `SSRF_PROXY_ALLOW_PRIVATE_IPS`（acl `dst`）或 `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS`（acl `dstdomain`）生成，插在 deny 之前。

## 第一步：体检（只读）

```bash
$PY tools/dify/dsl_portability_check.py          # 退出码 0 = 无 E 级
```
在 `linmo-pig-full` 仓库根跑。它扫 `deploy/dify/workflows`、`tools/dify`、`docs/dify`，报：
E1 地址写死私网 IP ｜ E2 占位符未替换 ｜ E3 `/admin` 语义混用 ｜ W1 变量存整条 URL。

## 第二步：定规范值（唯一真源）

| 变量 | 值 | 语义 |
|---|---|---|
| `PIG_BASE_URL` | `http://pig:9999/admin` | **含** `/admin`，url 里只写 `/internal/...` |
| `PY_BASE_URL` | `http://linmo-python-ai:8090` | 不含 context-path |

铁律：url 字段里不出现 IP、端口、`/admin`；新地址只加**基地址**变量，不存整条 URL。

## 第三步：接网络（两侧叠加文件，别写主编排）

```bash
docker network create linmo-dify-net 2>/dev/null || true
# PIG 侧：pig-gateway 加 dify-client 网络，alias pig / pig-gateway
docker compose -f deploy/docker-compose-liyuying-v1.yml -f deploy/docker-compose.dify-client.yml \
               --env-file deploy/.env.liyuying --env-file deploy/.env up -d pig-gateway
# Dify 侧：只接 ssrf_proxy（API/worker 不必接）
cd dify-docker && docker compose -f docker-compose.yaml -f docker-compose.override.yml \
               -f docker-compose.pig-net.yml up -d --force-recreate ssrf_proxy
```
白名单默认值已写进 `docker-compose.pig-net.yml`（`${SSRF_PROXY_ALLOW_PRIVATE_DOMAINS:-pig,pig-gateway}`），**不需要手填 .env**。

## 第四步：验证（两条，缺一不可）

```bash
# 现象级：经 squid 真发一次请求
docker run --rm --network linmo-dify-net alpine:latest sh -c \
  'http_proxy=http://<ssrf_proxy>:3128 wget -S -qO- --timeout=8 http://pig:9999/admin/auth/code 2>&1 | head -2'
```
- `424` = 通（PIG 无 token 的标准应答）
- `403` = squid 拦的 → 查 `/etc/squid/dify_allow_private.conf` 是否有 `acl ... dstdomain pig`
- 000 / 解析失败 = 网络没接上 → 查两侧是否都挂 `linmo-dify-net`、别名是否 `pig`

## 踩坑（都踩过）

- **zsh 不做词分割**：`extra="-e X=pig"` 经 `$extra` 会成为一个单词 ⇒ docker 把变量名解析成 `" X"`（带前导空格）⇒ 白名单静默为空。排查 `docker inspect --format '{{json .Config.Env}}'`。脚本里别把 `-e` 塞变量。
- **external 网络禁止写进主编排**：没有该网络的机器（含 CI）上任何 compose 命令在**解析阶段**中止；`config --services` 不报错，只有 `up`/`--dry-run` 才暴露。2026-09-29 因此打挂过 Jenkins。
- **别用 `host.docker.internal`**：解析出宿主网关 IP（随网络变），仍要按 IP 放行，等于没解决。
- **`--force-recreate` 只给 ssrf_proxy 和 pig-gateway**，别加整栈。

## 参考

仓库内完整方案 + 迁移清单 + 实测记录：`docs/dify/dify-portability.md`。
