---
name: linmo-openapi-apikey-triage
description: 排查灵猫企管（linmo-pig-full）里「业务系统用 API 密钥调用开放接口失败/无响应」并对上报类接口做端到端 smoke 验收。当用户贴出形如 `http://localhost:8888/api/admin/xxx/api/report 无响应` 或 `http://localhost:8890/...`、说「接口调不通」「连接失败，后端无响应」「密钥无效」「403/401/405」「上报没数据」「帮我验收一下这个接口」「当前版本:smoke」，或需要新建/解密一把 API 密钥跑通链路时使用。覆盖：请求到没到服务（含来源 IP 证据法）→ 状态码分流 → 密钥 app_code 授权 → 建密钥跑用例集 → 核库/核导出。
agent_created: true
---

# 灵猫企管 开放 API（API 密钥）排查与上报接口 smoke 验收

## 0. 先背四条判据（能省一半时间）

1. **接口活着 ≠ 调用成功。** 浏览器直接打开上报地址**永远不会有正常响应**（GET 不在映射里 → **405**
   `Request method 'GET' is not supported`）。用户口中的「无响应」十有八九是**浏览器直接打开了 URL**，
   或**请求压根没到服务**（见 §2）。先分清是「HTTP 层失败」还是「TCP 层没到」，别一上来就查代码。
2. **密钥的 `app_code` 必须与该接口声明的常量一致，否则 403。**
   `EntWorkLogController.APP_CODE = "work-log"`；密钥表 `pig.sys_api_key.app_code` 是 `test`/`tw`
   → 报 `API 密钥的应用编码应为 work-log，当前为 test`。**这不是密钥无效**，是「密钥未授权访问本接口」。
   ⚠️ **「测试连接」通过 ≠ 能上传**：日报客户端（`daily-agent-digest`）的「测试连接」打的是
   `/admin/api-key/verify`，而**该接口不校验 `app_code`**，所以它会回「验证通过」而上传照旧 403。
   2026-10-08 实测：密钥 `test22`（`app_code=yrd`）校验通过、上传报
   `API 密钥的应用编码应为 work-log，当前为 yrd`。判据一律看**上报的 `submit_error` 原文**，
   别因为校验通过就回头怀疑客户端地址/密钥。
3. **`X-API-Key` 头不产生调用日志、不吃配额。** `ApiKeyCallInterceptor.resolveApiKeyToken()` 只读
   `Authorization` 头。⇒ 用文档推荐的 `X-API-Key` 调用时，R5 的 QPS/日配额与 R6 的调用日志**静默失效**。
   要留审计痕迹就用 `Authorization: Bearer sk-...`。（这是**已知待修 bug**，见 §5）
4. **密钥明文可解密。** `api_key_cipher` = AES-256-GCM，key = `SHA-256(API_KEY_ENCRYPT_KEY)`，
   明文形如 `sk-<主键ID>-<随机串>`。⇒ 能拿库里的密文复原出可用的真实密钥做端到端复现（§3）。

## 1. 状态码分流表（实测口径）

| 现象 | 状态码 | 含义 / 处置 |
|------|--------|-------------|
| GET / HEAD 打开 URL | **405** | 接口只收 POST。浏览器打开必现，属预期 |
| POST，无 `X-API-Key` 也无 `Authorization` | **401** | `缺少 API 密钥（请通过 X-API-Key 请求头携带）` |
| POST，密钥格式不合法 / 不存在 / 停用 / 过期 / IP 不在白名单 | **401** | `API 密钥无效、已禁用、已过期或来源 IP 不在白名单` |
| POST，密钥有效但 `app_code` 不匹配 | **403** | 见判据 2 |
| POST，密钥 `authorized_url` 配了但请求路径不在其中 | **403** | `该 API 密钥未授权访问本接口` |
| 带 `Origin` 的跨域请求 / OPTIONS 预检 | **403** `Invalid CORS request` | 浏览器跨域必挂；非跨域场景（curl/服务端）不受影响 |
| `https://host:8888/...` | 无响应 | 8888 是明文 http，不做 TLS ⇒ **连接层直接无响应** |
| 任何请求但 curl 返回 **`000`** | 连不上 | **TCP 层就没通**，压根没到 nginx。see §2：多半是异地写 `localhost` |
| POST 无附件但用 `-F`（multipart） | 走表单分支 | 与 JSON 分支同路径，靠 `Content-Type` 分流 |
| **返回 HTML 页**（`<!doctype html>`）而非 JSON | 404 | **打到别的站点了**：Pig 的 4xx/5xx **全是 JSON R 包装**，一旦出现 HTML 就说明请求根本没到 Pig。最高频原因是**端口漏写** —— 同机 `:80` 常被别的系统占着（实测 `192.168.110.172:80` 是另一个 Next.js 站点，根路径 307→`/signin`，回 nginx HTML 404）。要用 `:8888`(统一端)/`:8890`(PC 端) |

## 2. 「无响应 / 连接失败 / 后端无响应」先二分，别碰后端（30 秒）

**顺序不能反：① 本机 curl 通不通 → ② nginx 日志有没有这条请求 → ③ 有记录才去看状态码。**

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"   # 本机 docker 不在默认 PATH

# ① 本机自测（4 组合，全 401 = 服务活着，问题在客户端）
for H in 127.0.0.1 localhost; do for P in 8888 8890; do
  printf "%-20s " "$H:$P"
  curl -s -m 8 -o /dev/null -w "HTTP=%{http_code}\n" \
    -X POST "http://$H:$P/api/admin/enterprise/worklog/api/report" -d "a=b"
done; done

# ② nginx 访问日志（容器内，access log 走 stdout）
docker logs --since 10m linmo-pig-ui 2>&1 | grep -i worklog

# ★ 杀手锏：聚合来源 IP —— 只有 127.0.0.1 / 172.18.0.1 就说明「从来没有外部请求到达过」
docker logs --since 2h linmo-pig-pc-ui 2>&1 | grep -oE "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | sort | uniq -c | sort -rn

# ③ 开放 API 调用日志（只记 Authorization: Bearer 方式，见判据 3）
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 -t \
  -e "select api_key_id,method,path,status,duration_ms,call_time from pig.sys_api_key_call_log order by id desc limit 10;"'
```

**② 无记录 + 来源 IP 只有 `127.0.0.1`/`172.18.0.1`（Docker 网桥网关 = 本机）⇒ 100% 是客户端/网络，立刻停手，别再查后端。**
按这五条对号入座：

| # | 原因 | 判据 / 修法 |
|---|------|-------------|
| 1 | **在别的机器/容器里写了 `localhost`**（最常见） | `localhost` 永远指**调用方自己** ⇒ TCP 层直接失败（curl `000`），**nginx 一点日志都不留**。改用 Mac 局域网 IP 或 `host.docker.internal` |
| 2 | 用了 `https://` | 8888/8890 都是明文 http，不做 TLS ⇒ 连接层无响应 |
| 3 | 终端/系统挂了 HTTP 代理 | `env \| grep -i proxy`、`scutil --proxy`；`localhost` 被丢给代理就石沉大海 |
| 4 | host / 端口写错 | 统一前端网关 **8888**、PC 端 **8890**、后端直连 **9999**（直连不带 `/api` 前缀）。**漏写端口最隐蔽**：URL 落到 `:80` → 打到同机另一个站点，回 **HTML** 404（Pig 只回 JSON）→ 客户端报"连接失败"，容易被误判成客户端 bug 或去怀疑打包。判据：`curl -s -o /dev/null -w '%{http_code}\n' -X POST "<url>"` 与 `curl -s "<url>" \| head -c 15` 看是 JSON 还是 `<!doctype` |
| 5 | 跨网段 / 不在同一二层网络 | 需端口转发或反代；先确认真能 ping 通这台机 |

**精确复现「从别处调 localhost」的症状**（决定性，可当验收标准用）：

```bash
# A) 外部容器用 localhost  -> HTTP=000（= 连接失败，与用户症状逐字吻合）
docker run --rm --network bridge curlimages/curl -s -m 6 -o /dev/null -w "HTTP=%{http_code}\n" \
  -X POST "http://localhost:8890/api/admin/enterprise/worklog/api/report" -d "a=b"
# B) 外部容器用 host.docker.internal -> HTTP=401（通）
docker run --rm --network bridge curlimages/curl -s -m 6 -o /dev/null -w "HTTP=%{http_code}\n" \
  -X POST "http://host.docker.internal:8890/api/admin/enterprise/worklog/api/report" -d "a=b"
```

**外部客户端该用的地址**：`http://<Mac 局域网 IP>:8890/...`（查 IP：`ipconfig getifaddr en0`）。
容器内调用用 `host.docker.internal:8890`。

## 2.1 8888 与 8890 等价，别怀疑「8890 没转发」

- **8888 = `linmo-pig-ui`**（统一/移动端网关），**8890 = `linmo-pig-pc-ui`**（PC 端网关）。
- 两者 nginx `default.conf` **md5 不同**（pc-ui 多 `/api/ai/` 直转 `python-ai:8090` 等块），但 `^~/api/` 这段
  **上游与 rewrite 完全一致**：都 `set $pig_upstream http://pig-gateway:9999` + resolver 运行时解析。
- 实测同一把 `work-log` 密钥 POST 两边 **返回同一个 `id`** ⇒ 写同一库同一行（同人同日 upsert），行为无差异。
- nginx 只有 **1 个 server 块**（`listen 80; server_name localhost;`）⇒ 唯一块即默认 server，
  **任意 Host 头都能命中**（实测 `Host: pc.mzlc.me` / `foo.bar` 均 401）。所以 `server_name localhost` 不构成限制。

## 2.2 403「应用编码应为 work-log，当前为 X」→ 改字段，不用换密钥

**判据 2 的正面修法。** 用户业务系统实际用的那把密钥 `app_code` 填错了，改对即可，**密钥字符串不变 ⇒ 业务系统零改动**。

```bash
# 管理端点 = PUT /admin/api-key/admin（注意与用户自助的 PUT /admin/api-key 不是同一个）
curl -s -X PUT "http://127.0.0.1:9999/admin/api-key/admin" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
    "id":"<密钥主键>","name":"<原名>","appCode":"work-log","username":"admin",
    "authorizedUrl":"/admin/enterprise/worklog/api/report\n/admin/api-key/verify","status":"0"}'
```

**三个必须知道的坑：**

1. ⚠️ **`updateByAdmin` 是全量覆盖语义** —— `setAuthorizedUrl(normalizedAndValidate(...))`、`setAllowedIps(...)`。
   **不传 `authorizedUrl` 就会被清空**，该密钥的 URL 白名单静默丢失（之后它就能访问所有接口了，是权限放宽）。
   ⇒ 改任何字段前，先从库里 `select authorized_url, allowed_ips from pig.sys_api_key where id=...` 取出原值带上。
2. `username` 传空 = 判定为「应用级密钥」，此时**必须**至少配一条授权 URL，否则报
   `未指定使用人时属于应用级密钥，必须配置至少一个授权URL`。
3. 授权 URL 格式：**换行或逗号分隔**，落库归一为换行；支持 `http(s)://host/path` 绝对地址或 `/admin/xxx` 相对路径；
   比对是**按段对齐的路径后缀匹配**（`path.equals(req) || path.endsWith(req)`），所以 nginx 前缀差异不影响。

**改之前先做安全性核验（3 步，别偷懒）**——确认这个字段没有别的消费方：

```bash
# ① app_code 在代码里的消费方（正常只有 EntWorkLogController 的 APP_CODE 校验）
grep -rn "getAppCode\|app_code" --include="*.java" pig/ | grep -v "/target/"
# ② 该密钥的 URL 白名单 —— 白名单本身决定了它不可能被别的系统拿去调其他接口
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -t \
  -e "select id,app_code,name,authorized_url from pig.sys_api_key where del_flag=\"0\";"'
# ③ 改完立刻用它原来那串密钥实测两个端口
curl -s -m 20 -w "\n[HTTP %{http_code}]\n" -X POST "http://localhost:8890/api/admin/enterprise/worklog/api/report" \
  -H "X-API-Key: sk-<主键>-<原随机串>" --data-urlencode "title=t" --data-urlencode "content=c"
```

**回滚**：同一端点把 `appCode` 改回原值即可（记得同样带上 `authorizedUrl`）。

**留着当素材**：库里那把 `app_code=test` 的密钥**故意不修** —— 它是「应用编码不匹配 → 403」用例的唯一素材
（`worklog-curl-tests.sh` 的 `API_KEY_OTHER`）。

## 3. 端到端 smoke 验收（复制即用）

```bash
cd /Users/shan/work/linmo-pig-full
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
PY=/Users/shan/.workbuddy/binaries/python/envs/default/bin/python   # 需 pip install redis cryptography

# ① 取一个「活着」的管理端令牌（内部走 tools/pig_login.py，默认 admin/123456，Redis db5，会先解锁）
$PY tools/pig_token.py                      # -> output/pig-token.txt（output/ 已 gitignore）

# ② 用真接口建一把 app_code=work-log 的密钥（需要 sys_apikey_add；明文只在本次响应里）
TOKEN=$(cat output/pig-token.txt | tr -d '\n\r ')
curl -s -X POST "http://127.0.0.1:9999/admin/api-key/admin" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"appCode":"work-log","name":"工作日志上报-smoke验收","username":"admin","status":"0"}'
# -> {"code":0,"data":"sk-<id>-<secret>",...}

# ③ 跑项目自带用例集（18 条，退出码即结果）
API_KEY='sk-...' BASE_URL='http://localhost:8888/api' bash tools/postman/worklog-curl-tests.sh
# 想连带跑「应用编码不匹配 -> 403」：追加 API_KEY_OTHER='<另一把不同 app_code 的密钥>'
# 「第二个使用人」用例需要库里存在第二个用户，否则客观 SKIP

# ④ 核库 + 核导出
docker exec linmo-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 -t \
  -e "select id,username,report_date,report_source,item_count,report_chars,coverage_note from pig.ent_work_log order by id desc limit 5;"'
curl -s "http://localhost:8888/api/admin/enterprise/worklog/page?current=1&size=5" -H "Authorization: Bearer $TOKEN" | head -c 400
curl -s "http://localhost:8888/api/admin/enterprise/worklog/export-markdown" -H "Authorization: Bearer $TOKEN" | head -12
```

**解密库里的密钥（复现用户真实调用时用）：**

```python
import base64, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
root = open('deploy/.env.dev').read().split('API_KEY_ENCRYPT_KEY=')[1].splitlines()[0]
aes = AESGCM(hashlib.sha256(root.encode()).digest())
raw = base64.b64decode(CIPHER)          # 取 pig.sys_api_key.api_key_cipher
print(aes.decrypt(raw[:12], raw[12:], None).decode())   # -> sk-<id>-<secret>
```

## 4. 工作日志 JSON 上报契约（最易踩）

字段是 **`work_items`**（**不是 `items`**），且 **`release_version` 必填**，否则 400。
`date` 已改为可选（**仅留痕**，归属日取服务器时间）。条目：`title / desc / status / source_task_ids`。

```json
{"date":"2026-10-08","generated_at":"2026-10-08T10:38:00+08:00","release_version":"v0.6.7",
 "report_chars":156,"coverage_note":"说明",
 "work_items":[{"title":"主题","desc":"详述","status":"completed","source_task_ids":["provider/session"]}]}
```

语义：**同人同日覆盖为一条最新记录**（`result=updated`）；报文与上次完全一致 → `result=unchanged` 且不写库；
>50 条 / >1MB / 缺 `release_version` / 条目缺 `title` → 4xx，**不截断静默存下**。

## 5. 已知待修 / 注意

- 🔴 `ApiKeyCallInterceptor.resolveApiKeyToken()` 只读 `Authorization`；修法：先取 `X-API-Key`，
  为空再回落 `Authorization`（一处小改 + 补用例）。修之前别用「调用日志」判定 X-API-Key 调用是否发生过。
- `pig.ent_work_log` 的表名**不带** `mzlc_` 前缀；库名是 `pig`（不是 `linmo-pig`，`-` 还需反引号）。
- `worklog-curl-tests.sh` 默认 `BASE_URL=http://localhost/api`（80 端口）；本机要显式传 `:8888/api`。
- 本机 `grep` 是 brokered shim，**不支持 BRE 的 `\|`**（静默无匹配、假报「没落地」）→ 一律用 `grep -E 'a|b'`。
