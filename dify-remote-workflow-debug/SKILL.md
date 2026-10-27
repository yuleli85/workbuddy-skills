---
name: dify-remote-workflow-debug
description: 排查并修复**只存在于远端 Dify 上**（仓库里没有 DSL）的工作流节点报错 —— 从控制台拉草稿、用真实输入在本地复现、改图、推回并发布、再真跑验收。当用户贴出 Dify 控制台的工作流报错（形如 `ValueError: …超过 Dify 代码节点 380000 上限`、`流程中有 N 个节点运行异常`、`records JSON 共 … 字符`）或说「这个工作流报错帮我修」「Dify 节点异常」时使用。也适用于需要读出某个 Dify app 的运行/节点级日志、取出用户上传的原文件做复现。
agent_created: true
---

# 修远端 Dify 工作流（控制台通道）

适用场景：**app 只活在远端 Dify 里**（`192.168.110.172`，本仓 `linmo-pig-full`），仓库没有对应 DSL。
本仓已有可复用客户端：`tools/dify_push_graph.py` 的 `Console` 类（登录 + cookie + csrf 全内置）。

## 0. 前置（两个必踩坑）

```bash
# ① 登录地址/账号：默认值都是错的。真实邮箱 liyuying@linmo.xin，
#    口令在 gitignored deploy/.env（内网 172）/ deploy/.env.gaoliang（公网 110.41.51.12 同口令）
# ② 绕开沙箱代理，否则 502 upstream connect failed
# ③ 用户给的入口可能是另一套独立 Dify（见 §11），先对用户入口登录验证再排查
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
    NO_PROXY='*' no_proxy='*' \
    DIFY_CONSOLE_PASSWORD="$(grep -m1 '^DIFY_CONSOLE_PASSWORD=' deploy/.env | cut -d= -f2-)" \
    python3 tools/dify_push_graph.py --base-url http://192.168.110.172 --email liyuying@linmo.xin --list
```

`Console` 用法（自己的临时脚本放 `output/`，那里被 gitignore）：

```python
import pathlib, sys, os
sys.path.insert(0, str(pathlib.Path("tools").resolve()))
from dify_push_graph import Console
c = Console("http://192.168.110.172", "liyuying@linmo.xin", PW); c.login()
st, body = c.call("GET", f"/apps/{APP}/workflows/draft")
```

## 1. 先定位「是哪个 app」

贴过来的只是 URL（`/app/<uuid>/workflow`）时，别猜：

```bash
# 运行库备份/转储里 uuid ↔ app_code（ai_app_config* 表）
grep -rn "<uuid>" output/db-backup/restore-runtime-*.sql | head
# 或用控制台直接列全部 app
python3 tools/dify_push_graph.py --list
```

## 2. 拉运行日志：把「N 个节点异常」摊开（别只看第一条）

| 目的 | 接口 |
|---|---|
| 最近运行列表 | `GET /apps/{app}/workflow-runs?limit=5` → `data[]` 里看 `status` / `exceptions_count` |

🔴 **这个列表只含 Studio（草稿）运行，不含 Service API 触发的运行**（2026-10-19 实测：直连
`/v1/workflows/run` 成功、`workflow_run_id` 都拿到了，控制台列表里查不到）。所以：
- 「服务端调用到底跑没跑/输出了什么」→ 看调用方日志（python-ai 的 `dify call done request_id=…`）
  或**用 app key 直连再跑一次**，别据控制台列表断言「没跑」；
- app key 可从控制台取：`GET /apps/{app}/api-keys`（返回明文 `app-…`，还带 `last_used_at`，
  能判断「调用方到底用没用这把 key」——对不上就是 `ai_app_config` 里的 Key 过期/指错应用）。
| 节点级明细 | `GET /apps/{app}/workflow-runs/{run_id}/node-executions` → `data[]`，每项含 `node_id/status/error/inputs/outputs/inputs_truncated/outputs_truncated` |

🔴 **`exceptions_count` 会把同一个节点的 retry 各算一次**（节点 `retry_config.max_retries=2` ⇒ retry+retry+exception = 3 条）。
所以「4 个节点异常」可能只是 **1 个真失败 + 1 个预期兜底**：先按 `node_id` 归并再下结论。
🔴 有 `error_strategy=default-value` 的节点，**报错但不算失败**（运行状态是 `partial-succeeded`），别当它是根因。

🚀 **一条命令版**（省掉本节的往返；跳过「预期兜底」噪声，真因直接分类）：
```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy NO_PROXY='*' \
  python3 tools/dify_run_diagnose.py --app-id <uuid> --runs 12      # 总览（每行的「首次异常真因」）
  python3 tools/dify_run_diagnose.py --app-id <uuid> --run <run_id> # 单次运行节点级明细
```
它把 `SSRF` / `url should start with`（URL 空）/ `Connection refused` / `timed out` / DNS 失败 直接判成
「是什么 + 怎么处置」，并**主动跳过**「上传文件模式下 `fetch_csv_http` 必然报的 `url is required`」这类预期噪声。

🔴 **兜底文案是误导源**：HTTP 节点 `error_strategy=default-value` 时，下游只见固定的兜底体
（如「请求未送达入湖端点（连接失败/超时/非 2xx）」），**真因只写在节点执行记录的 `error_message` 里**。
⇒ 凡见到"-999/未送达/网络"这类文案，**一律下钻 `error_message` 再下结论**，否则会把平台策略问题当成网络问题。

## 3. 拿「真实输入」在本地复现（决定性证据）

节点执行里的 `outputs` 就是下游节点的输入，且多半**没截断**（看 `outputs_truncated`）：

```python
# 例：把 document-extractor 的完整文本取出来当复现输入
txt = [it for it in items if it["node_id"] == "extract_csv_doc"][0]["outputs"]["text"]
pathlib.Path("output/dify-dump/real_input.txt").write_text(txt, encoding="utf-8")
```

⚠️ `/files/{id}/preview` 只返回 **3000 字符**截断的预览，**不能**用它做复现输入（用户上传的原件 id 可从
start 节点的 `inputs.<file>.reference` = `dify-file-ref:<base64>` 解出 `record_id`，与 `upload_files.id` 一致）。

复现范式（同一份输入跑「旧码 / 新码」）：

```python
import importlib.util
def load(p):
    s = importlib.util.spec_from_file_location("m", p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
old, new = load("output/dify-dump/old_code.py"), load("output/dify-dump/new_code.py")
# 旧码必须报出与用户完全一致的文案，新码必须通过 ⇒ 才算根因坐实
```

## 4. 改图：**程序化改造**，别手抄节点代码

节点代码 8~10KB，手抄必错。做法：从草稿 JSON 取 `data.code` → 用 `str.replace` 精确替换目标片段（并 `assert old.count(seg)==1`）→ 落盘新码 → 本地跑 harness。

## 5. 落库 + 推送 + 发布 + 回读

1. 导出 DSL 到仓库：`deploy/dify/workflows/<name>.yml`，结构 `{app:{...}, kind:app, version, workflow:{graph, features}}`；
   🔴 **`environment_variables` 写空数组；节点里也不要引用 `{{#env.X#}}`**（推图会把 env 整片清空，见 §8）；
   密钥写占位符 `__NAME__`，头部注释记 app_id、链路、推送命令与占位符含义（**真值不落仓库**）。
2. 推送并发布（`--publish` 不可省：服务 API/外部触发跑的是**发布版**，draft 只是画布）：
   ```bash
   # 密钥走 @ENVVAR：不进 argv（ps 看不到）、不落 DSL
   export INTERNAL_AI_TOKEN=$(grep -m1 '^INTERNAL_AI_TOKEN=' deploy/.env.dev | cut -d= -f2-)
   python3 tools/dify_push_graph.py --dsl <yml> --app-id <uuid> --base-url http://192.168.110.172 \
     --email liyuying@linmo.xin \
     --inject LINMO_INTERNAL_TOKEN=@INTERNAL_AI_TOKEN \
     --set-env LINMO_INGEST_URL=http://192.168.110.172:9999/admin/internal/ops/generic-ingest \
     --set-env-secret LINMO_INTERNAL_TOKEN=@INTERNAL_AI_TOKEN --publish
   ```
   `--set-env*` 是把环境变量**给回值**：不给的话工具按设计**拒绝推送**（推图会清空它们，见 §8）。
3. **回读校验**：重新 `GET /apps/{app}/workflows/draft` 与 `/workflows`（发布版），比对 `parse_*` 节点 `data.code`
   **逐字节等于**新码；工具打印的「图指纹」记进交付说明。
4. ⚠️ 推之前让浏览器 **Ctrl+F5**：Studio 页面还开着旧画布时，一次「运行/发布」会把旧图存回草稿，覆盖刚推的修复。

## 6. 真跑验收（最硬的一步）

`POST /apps/{app}/workflows/draft/run` **返回 SSE 流不是 JSON**（裸 `json.loads` 会 `Expecting value: line 1 column 1`）。解析：

```python
st, body = c.call("POST", f"/apps/{APP}/workflows/draft/run", payload)   # 可能 2MB
for line in body.splitlines():
    if line.startswith("data:"):
        ev = json.loads(line[5:])          # event: workflow_started / node_finished / workflow_finished
```

- 文件入参形如：`"csv_file": {"type":"document","transfer_method":"local_file","upload_file_id":"<upload_files.id>","filename":"x.csv"}`，
  与 `inputs` 同级传 `"files": []`。
- 验收看 `workflow_finished` 事件的 `status` / `outputs`（业务字段如 `ok/total/inserted/duplicated/failed`）+ 逐节点 `node_finished` 状态。
- 幂等设计的工作流，重跑出 `inserted=0 / duplicated=N / failed=0` **就是成功**（别当失败）。

## 7. Dify 代码节点限制（本次踩实的语义）

- **逐值限制，不是聚合**：`array[string]` 最多 **30 个元素**；**每个**字符串 ≤ 本部署 **400000** 字符。
  ⇒ 把「所有批次字符数求和」当上限是**错的**（实测 398666 字符合法数据被整轮误杀）。
- 工作流里凡有「批」概念（分批 POST/迭代），正确姿势：
  1. **逐批**校验长度（含估算偏差兜底）；
  2. 批数上限倒推最小粒度 `need = ceil(n/MAX_BATCHES)`，超出则**自适应调大**并写 warning；
  3. 再加业务侧单批条数上限（如 PIG 万能入湖单批 ≤500 条），三者取 min 作为 cap；
  4. 单次能力上限 = `MAX_BATCHES × cap`，超过就**明确报出可执行建议**（按日期/账号拆分），绝不静默截断。
- `tools/dify_push_graph.py` 的静态自检对 `array[string]` 输出会告警「会随机炸」——**若已按上述 1~4 实现，可忽略该告警**。

## 8. 🔴 别让图依赖「环境变量」：推图清空的窗口期（2026-10-15 二次踩坑）

机理（三段，缺一段就看不明白）：
1. `POST /apps/<id>/workflows/draft` **不接受** `environment_variables` 字段，缺省即空数组 ⇒
   **一次推图就把该应用的环境变量整片清空**（工具为此「默认拒绝」推送，除非 `--set-env*` 把值给回）。
2. 于是 `推图（清空） → 回填` 之间有**窗口期**。落在窗口期的运行，引用 `{{#env.X#}}` 的 HTTP 节点
   会把 URL 渲染成**空字符串**，报 `url should start with http:// or https://`
   （`InvalidURLError`，`status_code=0`）⇒ 整轮失败。
3. **最坑的是症状**：HTTP 节点若 `error_strategy=default-value`，这个异常被吞成静态兜底 JSON，
   汇总层只看到「HTTP 未返回可用响应（网络/超时/非2xx）」——**排查方向被带偏到网络**。
   实测同一份图、同一版本，16:37 两次成功、16:41 一次全批失败（就是撞上窗口期）。

判据（怎么一眼认出是它）：
- 报告里多批同一条 msg、且 `status_code=0`；
- 逐节点日志里 `push_batch_http` 的 `error_message` = `url should start with http:// or https://`；
- 同一图前后两次运行结果不一致（成功 ↔ 全失败）——**静态配置问题不会这样，一定是运行时环境抖动**。

修法（按性价比排序）：
1. **非密钥的地址/开关直接内联进节点**（本例入湖 URL 内联常量）⇒ 根除窗口期影响；
2. **密钥用占位符 `__NAME__` + `--inject NAME=@ENVVAR`** ⇒ 既不落仓库、也不受窗口期影响；
3. 汇总节点对 `code=-999` 单列分支，输出**排查顺序**（连通性 → 服务是否在跑 → 上下文路径 → 读超时），
   并把 `status_code=0` 判为「请求未送达」而非「服务端拒绝」；
4. 推图仍用 `--set-env/--set-env-secret` 把变量**给回值**，纯粹别让后来人看到空配置面板。
   ℹ️ 备份明文：`GET /apps/<id>/workflows/draft/environment-variables` 对 secret **回明文**
   （`/workflows/draft` 里的 `environment_variables` 字段才是 20 个星号掩码）。
   🔴 **优先用 `--preserve-env` 而不是 `--set-env*`**（2026-10-15）：前者原样读回并回填，
   连 `id` / `description` / 密文都保住；后者是 upsert，`id` 与 `description` 会被重建丢掉。
5. 🔴 **回填必须排在 `publish` 之前**（`tools/dify_push_graph.py` 已按此顺序，2026-10-15 修正）：
   发布会把「当前草稿的 `environment_variables`」**快照**成新版本 ⇒ 若顺序是「推图(清空) → 发布 → 回填」，
   则**发布版拿到空 env**，草稿看着正常但外部调用 401。两段式流程用 `--publish-only` 补发布。

**⚠️ 同一个 app 可能被多个会话并发推送**（2026-10-15 实测该 app 一天内 7 个发布版互相覆盖，
其中一版令牌没注入、仍是 `__LINMO_INTERNAL_TOKEN__` 占位符 ⇒ 谁用了谁 401）。动手前后都要复核：

```bash
# 列出该 app 的全部版本，逐版判「是否含预期特征串」（如 _pad_datetime / 令牌是否已注入）
psql "$DIFY_DB_DSN" -t -A -F'|' -c "SELECT coalesce(version,'draft'), coalesce(version_number,0), updated_at,
 (case when graph::text like '%__LINMO_INTERNAL_TOKEN__%' then 'PLACEHOLDER' else 'injected' end)
 FROM workflows WHERE app_id='<app-id>' ORDER BY 2 DESC LIMIT 5;"
```

判据：**最新版本号最大者 = 外部调用实际用的那版**；必须同时满足「特征补丁在」+「占位符已注入」。
若仓库里出现**两份描述同一 app 的 DSL**，先逐字 diff 代码节点（`difflib` 解出 `code` 字段再对比），
以**超集**那份为唯一真源并删掉重复文件 —— 否则下次推图必覆盖对方的改动。

验收（本次靠它证明「真免疫」）：**把相关环境变量全清空后重跑，仍 `ok=true`**。

## 8b. 🔴 私网目标会被 Dify 的 SSRF 防护**间歇**拦截（2026-10-15 三次踩坑）

**症状**：HTTP 节点全批失败，下游只看到 `code=-999`「请求未送达入湖端点（连接失败/超时/非 2xx）」，
`status_code=0`。**看着像网络问题，其实是平台策略**。真因只在节点 `error_message` 里：

```
Access to 'http://<私网IP>:<port>/...' was blocked by SSRF protection
(e.g. SSRF_PROXY_ALLOW_PRIVATE_IPS=172.21.0.0/16 to allow 172.21.0.0/16).
```

**判据（区分"平台策略"与"真网络故障"）**：`status_code=0` + **同一张图前后多次运行结果不一致**
（一段时间全通、某个瞬间全失败）。静态配置问题不会这样 —— 这是运行时环境在变。

**机理**：Dify 对私网目标（`10/8`、`172.16/12`、`192.168/16`、`127/8`）默认拒绝，
放行名单是进程级环境变量 `SSRF_PROXY_ALLOW_PRIVATE_IPS`。
当目标私网 IP **不在名单**里时，只要 172 上重建 `ssrf_proxy` / `api` / `agent_ssrf_proxy`，
窗口期内应用层校验生效 ⇒ 请求被拒；重建完成、squid 接管后又恢复正常。

**根治（必须在 Dify 所在主机执行，本机无通道）**：
```bash
cd /opt/dify/docker && cp .env .env.backup-$(date +%Y%m%d)-ssrf
# 追加目标私网地址（多值逗号分隔），例：
#   SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.110.199/32,192.168.110.172/32
vi .env && docker compose up -d --force-recreate ssrf_proxy agent_ssrf_proxy api worker
```
🔴 用 `/32` 或最小必要网段，**绝不要 `0.0.0.0/0`**（等于关闭防护）。
🔴 同项目已有先例可对照：`tools/weknora-dify-bridge/README.md` 记录了为 WeKnora 桥放行 `192.168.110.199/32`。

**⚠️ 不要试图用"公网域名"绕过**：那会把内部端点（如 `/admin/internal/*`）暴露到公网，违反
「内部接口仅限内网 + 内部令牌」的架构硬约束，属禁止项。

**工作流侧能做的最佳缓解**：让报告**自己说清**这是 SSRF（把根因写成兜底文案 + 汇总分支明确指引），
而不是留一句"网络问题"。见 §2 的 `tools/dify_run_diagnose.py`。

## 11. 🔴 用户给的 URL 入口 ≠ 内网控制台入口：可能是两套独立 Dify（2026-10-22 实测）

用户贴 `http://110.41.51.12/app/<uuid>/workflow`（公网 IP），而本仓工具默认打 `192.168.110.172`。
**同 app UUID + 历史 runs 一致 ≠ 同一套实例**：可能是同一份 DSL 各自导入过、数据完全分库的两套部署。
本次实锤差异：入湖 URL 各自内联（172→`192.168.110.172:9999`，公网→`192.168.0.9:9999`）；
今天的新运行只在公网实例可见，从 172 查 `workflow-runs` **看不到**。

判据与流程：
1. **先对用户给的入口登录验证**（口令可能同 `deploy/.env.gaoliang`）：`Console("http://110.41.51.12", ...)` 登录成功 + app 存在 + 有 172 看不到的新运行 ⇒ 两套实例，**后续所有查询/复现都以用户的入口为准**。
2. 从内网口查「用户跑没跑」会得出错误结论（列表里没有 ≠ 没跑）——排查运行记录必须用用户实际访问的入口。
3. 复现用户动作时走同一入口。本次公网实例 `POST /console/api/files/upload` 稳定 500
   （页面静默失败 ⇒ 运行时 start 节点 `csv_file=null` ⇒ parse_csv 报「没有拿到 CSV 内容」），
   内网实例同样脚本全通 ⇒ 定位为平台存储层问题（查 api 日志 + `STORAGE_TYPE`/`OPENDAL_*`，Dify 1.x 本地存储 = `opendal`+`fs`+`storage`），不是工作流问题。
4. 工作流侧排查全绿时，**往平台层想**：用最小脚本直接 curl 控制台接口对照两个实例
   （上传/文件预览/模型列表），「同图同输入一个实例通一个不通」就是平台差异，别再抠节点。

## 9. 交付物清单（照做不漏）

- [ ] 仓库内 DSL（`deploy/dify/workflows/*.yml`，含头部说明与推送命令）
- [ ] 修复报告（`output/<topic>-YYYY-MM-DD.md`：根因证据链 / diff 摘要 / 真跑结果 / 残留建议），走 `present_files` 交付
- [ ] 记忆：日报 + 主题文件（app_id↔app_code、env 名、限制语义）
- [ ] 若根因在**平台侧**（如 SSRF 白名单）：把「需要谁在哪台机执行什么」单独列成一段，别混进代码改动里

---

## 10. 「Model is not configured」= 节点引用的 provider 在当前工作区已不存在（2026-10-16 实测）

**症状**：服务 API / 上游报 `dify HTTP 400 ... body={"code":"invalid_param","message":"Model is not configured"}`。
⚠️ 仓里 python-ai 的这条错误文案**自带误导尾巴**（「该地址没有端口(Dify 默认 80)；实例若不在 80 端口，请补端口」）——
`http 400` 说明**已经连上 Dify 了**，别去改端口/网络/密钥。

**根因**：该 Dify 实例做过模型通道迁移（本仓：原生 `langgenius/deepseek/deepseek` 被移除，
改走自建 `langgenius/openai_api_compatible/openai_api_compatible`），而部分应用节点仍写死旧 provider。

**判据（一条命令拿白名单）**：

```python
st, b = c.call("GET", "/workspaces/current/models/model-types/llm")      # 还有 rerank / text-embedding / speech2text
avail = {it["provider"]: {m["model"] for m in it.get("models") or []} for it in json.loads(b)["data"]}
# 任何节点里 provider 不在 avail 的键 ⇒ 失效引用
```

🔴 **扫描必须递归任意深度，且三种节点都带 model，只查 `type=="llm"` 必漏**：

| 位置 | 说明 |
|---|---|
| `data.model.{provider,name}` | `llm` / **`parameter-extractor`（参数提取器）** / `question-classifier`（问题分类器） |
| `data.single_retrieval_config.model` | `knowledge-retrieval`；`retrieval_mode="multiple"` 时**不生效**但仍是脏引用 |
| `data.multiple_retrieval_config.reranking_model` | rerank 模型，去 `model-types/rerank` 校验（`bge-reranker-v2-m3` 实测 active） |

🔴 **必须同时校验发布版**：`GET /apps/{id}/workflows?page=1&limit=5` 的 `items` 里**带完整 graph**；
`max(version_number)` 那条就是服务 API 实际用的。**草稿修了不 `POST /workflows/publish` 等于没修** ——
曾遇到「草稿早已迁好、发布版还是几个月前的旧图」这种只差一次发布的情况。

**修法**：GET draft → 只替换 `provider`/`name`（prompt、结构、参数、env 一律不动）→
`POST /workflows/draft`（带 `hash`）→ 回读 → `POST /workflows/publish` → 回读发布版。
批量脚本范式见 `output/dify_fix_stale_model_all.py`。

**验收**：走真实调用链（本仓 `POST /api/v1/chat` + `X-Internal-Token`，body `{query, app, response_mode:"blocking", user, request_id}`），
看 `degraded=false` + `answer` 非兜底文案；再全量复扫确认 0 处残留。

⚠️ 推图会清空环境变量（见 §8）；⚠️ 这是对**远端生产**的改动，改完提醒使用者 **Ctrl+F5**，
否则 Studio 旧画布一次「运行/发布」会把旧图写回覆盖修复。
