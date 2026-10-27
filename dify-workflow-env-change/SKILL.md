---
name: dify-workflow-env-change
description: 修改远程 Dify 工作流的「环境变量」（含 secret），并确保服务 API 真跑时生效。当用户说「改 Dify 的 GITHUB_AUTH / GITHUB_API_BASE」「环境变量改了没生效」「Dify 工作流改了不生效」「控制台登录不了/被锁」「换个 PAT 给 Dify」时使用。覆盖三个必踩坑：控制台账号与代理、写的是草稿而非发布版、secret 值无法用 psql 明文改。
agent_created: true
---

# 改 Dify 工作流环境变量（并让它真生效）

适用：Dify 部署在**另一台机器**（本仓库场景：`192.168.110.172`，Postgres `:5433`、Redis `:6379`、控制台 `http://192.168.110.172`），
工作流由 PIG/python-ai 通过**服务 API** 调用。本仓库已有现成工具：

| 工具 | 作用 |
|---|---|
| `tools/dify_set_env.py` | 读/写某个应用的**环境变量**（`--list` / `--set K=V` / `--set-secret K=@ENVVAR`） |
| `tools/dify_workflow_env_sync.py` | **声明式批量同步**：按 `deploy/dify-workflow-env.yml` 清单一次写多个应用（`--scaffold` / `--check` / `--apply`），值只从环境变量取 |
| `tools/dify_workflow_publish.py` | 把 **draft 发布**成新的已发布版本（服务 API 只跑这个），可 `--force` |
| `tools/dify_push_graph.py` | 推 DSL 到 draft（会覆盖画布，慎用） |
| `tools/reset_dify_password.py` | 忘记口令 / 被锁时的恢复口径（PBKDF2 格式写死在这里） |

## ⚠️ 先判：这里该不该用 env 同步

本 skill 只解决「怎么改、怎么让 secret 生效」的**机制**问题，不代表架构上应该把凭据放在工作流环境变量里。

- 凭据是 **PIG 用户身份**（`PIG_USER` / `PIG_PASSWORD_ENC` / `PIG_BASIC_AUTH`）⇒ **不要用本 skill**
  继续复制。正解是身份透传 + 内部代签，见 `linmo-pig-full/docs/dify-agent-identity-sso.md`
  （用户只在 PIG 登录一次，Dify 不持 PIG 用户凭据）。
- 凭据是**第三方系统、且属于无人定时任务**（禅道 / 账套 / GitHub / JEV）⇒ 优先迁到 PIG
  `ops_connector_credential`（AES 加密 + 凭据接口），或改用有作用域的 `sys_api_key`（`sk-`）。
- 只有「必须整片替换某个不可迁的第三方 secret」时，才按下面流程走。

## 三个必踩坑（按踩到的顺序）

### 坑 1：控制台登录进不去
- `--base-url` / `--email` 的默认值**取 `dify_push_graph.py` 的 `DEFAULT_BASE` / `DEFAULT_EMAIL`**
  （当前 = `DIFY_CONSOLE_BASE_URL` 环境变量或 `http://192.168.110.172`；`DIFY_CONSOLE_EMAIL` 或 `liyuying@linmo.xin`）。
  2026-10 之前的版本曾默认 `localhost:8080` + `admin@linmo.local`（**已不存在**），看到旧报错别照旧文档排查。
  换环境仍要显式传 `--base-url`；真实账号在 Dify 库里查：
  ```bash
  psql -h <dify_host> -p 5433 -U postgres -d dify -c "SELECT id,email,name,status FROM accounts;"
  ```
- 报 `401 Invalid email or password` = 邮箱不对；报 `429 email_code_login_limit` = **口令错太多次被锁**（锁定按账号算，换个账号立刻可用）。
- 🔴 **本机 Python 必须绕开沙箱代理**，否则代理转发 HTTPS 报 `502 upstream connect failed`（curl 侧对应 `--noproxy '*'`）：
  ```bash
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
      NO_PROXY='*' no_proxy='*' DIFY_CONSOLE_PASSWORD='<pw>' \
      python3 tools/dify_set_env.py --base-url http://<dify_host> --email <real@email> ...
  ```
- **口令丢失时不要动别人的账号**：直连 Postgres 新增一个专用自动化账号（`accounts` + `tenant_account_joins`），密码格式 =
  `password = base64(hexlify(pbkdf2_hmac('sha256', pw, salt, 10000)))`、`password_salt = base64(salt)`；
  `tenant_account_joins.role` 取 `admin`、`current=true`、`tenant_id` 用现网那一个。删除这两行即回滚。

### 坑 2：改完了「没生效」——你改的是草稿
Dify 的 `workflows` 表里同一应用有**两行**：`version='draft'` 与 `version='<时间戳>'`，`apps.workflow_id` 指向已发布那行。
`dify_set_env.py` 写的是 **draft**，而 **`POST /v1/workflows/run` 只跑已发布版** ⇒ 现象与「完全没改」一致。

```bash
python3 tools/dify_workflow_publish.py --app-id <uuid> --force      # 改完必须发布
```
> `--force` 不可省：不带时它按 **graph** 规范化比对，只改了环境变量（graph 没变）会被判定「无需发布」而跳过。
> 发布后 `apps.workflow_id` 会变，**记下旧值**用于回滚。

### 坑 3：secret 无法用 psql 明文改
`workflows.environment_variables` 是 JSONB，但 `value_type='secret'` 的值经 Dify `SECRET_KEY` **加密**存储。
不知道 `SECRET_KEY` 就不要试图直接 UPDATE——必须走控制台 API（上面两个工具）。
**验收判据**：`--set-secret` 后工具只会说「已掩码(无法判断是否为空)」，必须**真跑一次**工作流才算验收。

## 需求「从 docker compose / yml 传入 env」怎么答

**没有直通路**，别去找开关。三个事实（都有本仓库代码证据）：

1. `env.*` 存在 Postgres `workflows.environment_variables`，secret 还按租户 RSA 加密 ⇒ compose 的 `environment:` 进不了它；
2. 代码节点跑在独立 `dify-sandbox` 容器，**不继承** api 容器的进程环境；
3. 唯一"写在 yaml 里就落库"的原语是 **DSL 的 `workflow.environment_variables`**（`tools/dify/github-commits-fetch.workflow.yml` 就这么写），
   但值会**明文进 git**；而 `dify_push_graph.py` 推图时该字段缺省即空数组 ⇒ **一次推图把现有变量整片抹掉**
   （secret 抹掉后只能去 Studio 重设，接口只回 20 个星号），所以推图必须配 `--preserve-env` 或逐个 `--set-env-secret` 给回。

要"一处声明、多应用生效"，走那条桥（本仓库已落地）：

```bash
# ① 按线上现状生成清单骨架（只读线上，writes 本地 deploy/dify-workflow-env.yml）
python3 tools/dify_workflow_env_sync.py --scaffold
# ② 把清单里的 from 改成 .env 里真实的变量名，看差异
python3 tools/dify_workflow_env_sync.py --check
# ③ 写入（逐应用 upsert，只动清单里声明的变量）
python3 tools/dify_workflow_env_sync.py --apply
```

- 值来源：`value` 字面量 > `from` 指定环境变量 > 同名环境变量；**来源为空默认跳过，绝不写空串**
  （防重演「GITHUB_AUTH 明文 0 字符、界面却显示已配置」那次事故）。
- 想在 compose 里跑：`dify-docker/docker-compose.env-sync.yml`（一次性服务，`run --rm wf_env_sync --check/--apply`），
  值在它的 `environment:` 里声明、真值放 `.env`。**别加进常驻 up**，否则每次起栈都覆盖控制台手工改动。
- 改完 env 仍要**发布**（坑 2），且 secret 只能真跑验收（坑 3）。



1. 探活：控制台可达 → 用真账号 `--list` 看到现有变量。
2. 写入：`--set K=V`（普通串）/ `--set-secret K=@ENVVAR`（密钥，值走本机环境变量，避免进 shell 历史）。
3. **发布**：`dify_workflow_publish.py --force`。
4. **真跑一次**（服务 API 或经 python-ai 触发），核对输出/落库——secret 无法从接口判断是否为空。
5. 记回滚：旧 `workflow_id`、旧变量值。

## 相关易错点

- 换 `GITHUB_API_BASE` 这类「取数源」时，**常需与鉴权变量成对改**：只换 base 而 auth 还是旧源（例如本地单仓桥的共享密钥），
  会让**原本能用的私有仓也 401/404**，看起来像「全面崩了」。
- 连接器编码会成为下发 `source`（PIG `contactSourceOf`），而 python-ai `_SPECS` **按 source 精确查**；
  `source` 带后缀的多实例连接器需要登记别名，否则掉进默认规格，报错却指向工作流的输出键。

## 配套：本地栈里的 `DIFY_CONSOLE_PASSWORD`（python-ai 容器）

> 2026-10-12 实测定稿。`DIFY_CONSOLE_PASSWORD` **不是工作流变量**，而是 python-ai「同步 API Key」功能
> （登控制台读回**明文** token ⇒ 交 PIG `AiKeyCipher` 加密落 `ai_app_config.api_key_cipher`）的凭据。

- **落点**：`deploy/.env`（**gitignored**，`.gitignore:15`）。**绝不写进 `.env.dev`**（被跟踪）或代码。
  配套 `DIFY_CONSOLE_EMAIL` / `DIFY_CONSOLE_BASE_URL` 已由 `docker-compose.dev.yml` 注入 ⇒ 通常**只缺口令**，
  动手前先 `docker exec linmo-python-ai env | grep DIFY_CONSOLE` 确认缺哪个。
- **填明文**：`python-ai-service/app/services/dify_api_key_sync.py` 内部自做 `base64`
  （见该文件 docstring 第 17–18 行）。**填已编码值会静默解成乱码 ⇒ 报 `Invalid email or password`**，
  看起来像口令错，实际是编码错。
- 🔴 **必须 recreate，不是 restart**：env 在**容器创建时**注入，`docker restart` **不重读 env-file**。正确命令：
  ```
  docker compose --env-file deploy/.env.dev --env-file deploy/.env \
    -f deploy/docker-compose.dev.yml --profile pcui up -d python-ai
  ```
- **验收（单次即可，别重试以免 429 锁账号）**：
  ```
  curl -s -o /tmp/r -w '%{http_code}\n' -X POST 'http://<dify-host>/console/api/login' \
    -H 'Content-Type: application/json' \
    --data "{\"email\":\"<email>\",\"password\":\"$(printf '%s' '<明文口令>' | base64)\"}"
  ```
  `200` + `{"result":"success"}` = 有效；`401 Invalid email or password` = 值错/编码错；`429 email_code_login_limit` = 账号被锁。
- **留空 ⇒ 该功能静默关闭**（只打一条 WARNING，不报错）⇒ 排查「同步 API Key 没反应」时**先查这个变量**，
  症状文案就是「未配置 Dify 控制台口令（DIFY_CONSOLE_PASSWORD）」。
