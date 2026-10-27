---
name: dify-chatflow-build
description: 在 Dify（本机实例 192.168.110.172）里从零建一个能查业务数据的 chatflow（对话式智能体），并交付「脚本生成 DSL → 推送 → 发布 → 真跑验收」。当用户说「在 dify 里做一个 XX 智能体/问答助手」「把这个页面的数据接进 Dify」「Dify 里加个对话应用」「查 XX 数据的智能体」时使用。覆盖：新建 app 的正确姿势（copy 而非 create）、advanced-chat 专用运行端点、PIG OAuth2 密文登录、URL 多查询参数会 404、模型通道压测与更换、单出口 code_guard 防空白回复、数仓脏数据在快照侧清洗、drilldown vs task/page 的体积取舍、本机 19 与服务器 172 是两套代码同一个库。
agent_created: true
---

# 在 Dify 里从零建一个数据问答 chatflow

## 0. 先决条件（都在 linmo-pig-full 仓库里）

- 客户端：`tools/dify_push_graph.py` 的 `Console`（登录 + cookie + csrf 全内置）
- 凭据：`deploy/.env` 的 `DIFY_CONSOLE_PASSWORD`，账号 `liyuying@linmo.xin`
- Python 环境：`/Users/shan/.workbuddy/binaries/python/envs/default/bin/python`（系统 python 没有 requests/yaml）
- 一律 `env -u http_proxy -u https_proxy ... NO_PROXY='*'`，否则 502

## 1. 🔴 建 app：用 copy，不要用 create

`POST /console/api/apps` 能创建成功（201），但**草稿未初始化** —— 紧接着推图会报
`404 draft_workflow_not_exist: Draft workflow need to be initialized.`

正确姿势：**复制一个同 mode 的现成应用**，草稿是现成的：

```python
c.call("POST", "/apps/5ba64b2e-f893-4f96-8b0f-6ecd846edb16/copy",
       {"name": "rd-chat 研发数据问答", "icon": "🐈", "icon_background": "#E4FBCC",
        "mode": "advanced-chat"})   # 201 → 新 id
c.call("DELETE", "/apps/<创错的空壳 id>")   # 收拾掉 create 出来的残骸，204
```

`5ba64b2e…` 是本实例的 market-chat（advanced-chat）模板，长期可用。

## 2. 运行端点：advanced-chat 是独立路径

| 用途 | 端点 |
|---|---|
| workflow 应用 草稿跑 | `POST /apps/<id>/workflows/draft/run` |
| **advanced-chat 草稿跑** | `POST /apps/<id>/advanced-chat/workflows/draft/run` |
| 发布版（外部调用） | `POST /v1/chat-messages` + `Authorization: Bearer app-xxx` |

用错会得到 `404 App mode is not in the supported list: {'workflow'}`。
chatflow 的 run payload：`{"inputs": {...}, "query": "...", "files": []}`；返回 SSE，
看 `node_finished`（逐节点）与 `workflow_finished`（`status` / `outputs.text`）。
`status=partial-succeeded` 不算失败（多半是某节点 default-value 兜底）。

## 3. PIG 数据接口怎么选（体积决定形状）

| 想要 | 用 | 别用 |
|---|---|---|
| 某智能体指标/预警 | `GET /admin/ops/agent/details/{code}?days=N`（~16KB） | — |
| 超期任务/在途项目/在办/未分配/提交明细 | `GET /admin/ops/agent/{code}/drilldown?type=<task_overdue\|project_active\|task_doing\|task_unassigned\|commit>&days=N&size=200`（~11KB） | `GET /admin/ops/project/task/page` —— 带 `rawJson`，`size=100` 单响应 **785KB**，撞 Dify 代码节点 400000 字符逐值上限 |

合法 `type` 是单数 `commit`，写 `commits` 回 400「未知下钻类型」。

## 4. 🔴 PIG 登录不吃明文密码

`POST {base}/auth/oauth2/token`（`Authorization: Basic base64("mzlc:mzlc")`，
`Content-Type: x-www-form-urlencoded`）的 `password` 必须是
`AES-128-CFB / NoPadding / IV=key` 的密文，key = `VITE_PWD_ENC_KEY`（默认 `maozailingchuang`）。
密文确定性 ⇒ 可当 secret 存进 Dify 环境变量：

```bash
node -e "const c=require('crypto'),k=Buffer.from('maozailingchuang','utf8');\
console.log(c.createCipheriv('aes-128-cfb',k,k).update('123456','utf8','base64'))"   # 0tERavkv
```

`Enc-Flag: false` 这个头加不加都能通；`PIG_BASE_URL` 形如 `http://192.168.110.172:8890/api`（**必须带 /api**）。

## 5. 图的标准骨架（9~12 节点，已验证）

推荐**单出口**（比双 answer 更稳，见下面第 4 条）：

```
start(days) → http_login → code_token(失败必抛)
 → http_xxx …（每个 HTTP 节点 error_strategy=default-value）
 → code_facts(压事实快照) → llm → code_guard(出口兜底) → answer({{#code_guard.final_text#}})
```

老写法也能用，但只在确认模型不会返回空白时才是安全的：

```
… → llm → if-else(text not empty) ├ true → answer
                                  └ false → answer_fallback
```

四条硬规则：
1. **登录节点不兜底**（`error_strategy` 不设），失败要炸；否则下游全 401 会被伪装成"没数据"。
2. **数据节点兜底 + 代码节点自曝缺口**：快照顶部输出「⚠️ 本次未取到的数据源」，绝不让 LLM 把空当零。
3. **LLM 节点兜底成空串**：上游模型偶发 400（额度/通道）时不至于整轮挂掉。
4. **出口判定用长度，不用 `not empty`**：实测模型偶发「succeeded 但 text 是空白字符」，
   `not empty` 判为 true → 用户拿到一条空白回复（比报错更糟）。用一个 code 节点兜住：

```python
def main(text: str, facts: str) -> dict:
    t = (text or "").strip()
    if len(t) >= 20:
        return {"final_text": t}
    return {"final_text": "⚠️ 本次没能生成解读（模型返回空内容或调用失败）。"
                          "数据已取到，下面是原始快照：\n\n" + (facts or "")[:1800]}
```

这个节点也顺带取代了双分支，图更短、少一条边。

## 6. HTTP 节点取数：URL 只准带一个 query 参数

🔴 **URL 里拼 `?a=1&b=2` 只会发出第一个参数**，后半段被当成路径 ⇒ 后端回
`404 No static resource ...`，而你用 curl 测同一个 URL 是 200（curl 没这个问题）。

```yaml
# ✗ 会 404
url: '{{#env.BASE#}}/detail?days=7&top=10'
# ✓ 只带一个参数，其余交给后端默认值
url: '{{#env.BASE#}}/detail?days={{#start.days#}}'
```

需要多个参数时用节点的 `params` 字段（query string），不要拼进 url。

排查手法：节点报 404 但 curl 通 → 先怀疑 URL 模板，不要怀疑后端。

## 7. 模型选择：先压测，别信「active」，也别信「昨天能用」

**模型清单会实时变**。先查当前租户到底有哪些（不要在 DSL 里凭记忆写模型名）：

```
GET /console/api/workspaces/current/models/model-types/llm
```

2026-10-19 实测：`deepseek-v4-flash` 在应用已跑通后突然从清单消失，服务接口直接报
`Model deepseek-v4-flash not exist.` —— 整轮 workflow 根本没启动（草稿运行也一样），
画布看不出任何问题。同一时期清单里是：`deepseek-v4.1-flash`、`qwen3.5-35b-a3b`。

实测稳定性（同一张 ~3k token 的项目快照）：
- `deepseek-v4.1-flash`：6 问稳定挂 1 问，400 / `Unknown error`，重试 4 次全失败（兜底能接住，但用户看到的是原始快照）。
- `qwen3.5-35b-a3b`：6/6 + 连测 4 次全通过；结构服从性好，但会自己算「覆盖率/削减比例」这类快照没有的数，
  提示词必须显式禁止二次汇总（见 §8）。

换模型后必须压测：连问 5~6 个不同意图，统计 success / fallback，只看一次成功不算数。
判据：answer 不以 `⚠️` 开头且长度 > 0。

## 8. 提示词必须写死的 4 条（否则一定出事）

- 只用快照里的数字，没有就说"当前数据未提供"
- 结论 → 依据（带口径与单位）→ 建议（谁/做什么/什么时候）
- **篇幅上限**：`max_tokens` 配 2400，提示词写「不超过 900 字」；
  太小会在半句截断（`completion_tokens` 顶满即证据），太大则模型啰嗦
- **日期只准抄快照里的「生成时间」与「截止日」**，模型会自己编"今天（2026-10-XX）"

指标类对话还要额外加 **口径铁律**：
- 增量 vs 存量 vs 累计，哪些能相加、哪些绝对不能（作品累计播放 ≠ 窗口增量播放）
- 比率类只说"平均 X%"，不能说"总 X%"
- 空值 `-` 是"未上报"，不是 0%
- 样本天数不足时必须提醒「只能看方向」

## 9. 数据质量：脏数据要在快照侧清洗

数仓宽表常有脏行，直接进快照会被模型当成真实业务对象：

| 脏数据 | 处置 |
|---|---|
| `platform_id` 有、`name` 双空的行 | 生成快照时过滤掉（否则出现「- / - 播放 0」这种假账号） |
| 公众号 `<p>…</p>` 富文本标题 | 正则去标签 + 解 HTML 实体 + 压空白 + 截断 |
| 采集联调遗留（标题含"测试/容错"） | 快照里显式标注，提示词要求排除 |

原则：**能在快照侧清掉的，不要指望提示词**（提示词是软约束，文本清洗是硬的）。

## 10. 推送与发布

```bash
python3 tools/dify_push_graph.py --dsl <yml> --app-id <id> --preserve-env --publish
```

- `--preserve-env` 不能省（推图清空环境变量，secret 清空后 API 查不回明文）
- 必须 `--publish`：`/v1/chat-messages` 跑的是发布版
- 推之前 Studio 页面 Ctrl+F5，否则旧画布会把旧图存回草稿
- 应用公开访问地址：`GET /apps/<id>` → `site.access_token` → `http://host/chat/<token>`（截图验收用这个最省事，比 Studio 预览好点）

## 8. 验收清单（缺一不可）

1. 纯本地脚本跑 code 节点 + 与服务端 `total` 对账（`tools/dify_rd_chat_verify.py` 是范式）
2. 反向用例：401 时 token 节点必须抛可读异常
3. 缺数据源：`data_ok=0` + 快照顶部标注
4. 草稿真跑 3~4 个不同意图
5. **发布版服务 API** 跑一次，检查答案结尾是否完整（截断只能在这一步发现）
6. 截图：Studio 画布 + `/chat/<token>` 的真实问答

## 11. 已知坑速查

| 现象 | 真因 | 处置 |
|---|---|---|
| 节点 404 `No static resource`，但 curl 同一 URL 200 | URL 里拼了 `&` 第二个参数 | URL 只带一个参数（§6） |
| 用户拿到一条空白回复 | 模型 succeeded 但 text 是空白字符，`not empty` 放行 | 用 code_guard 按长度兜（§5） |
| 同一问题时好时坏，错误只有 `Unknown error` | 模型通道不稳 | 换模型 + 压测（§7） |
| 整轮没启动，报 `Model xxx not exist.` | 租户模型清单变了（模型被下架/改名） | 查 `/workspaces/current/models/model-types/llm`，换清单里现存的（§7） |
| code 节点 failed，报 `DeprecationWarning: datetime.utcnow()` | Python 3.12 起 utcnow 弃用，Dify 沙箱把 warning 当异常 | 改 `datetime.now(timezone(timedelta(hours=8)))` |
| 新加的接口在 172 上是 404、本机 200 | 本机与服务器是**两套代码、同一个库** | 确认 `PIG_BASE_URL` 指向哪台；要么部署 jar，要么改指向 |
| `draft_workflow_not_exist` | 用 create 建的 app | 改用 copy（§1） |
| `App mode is not in the supported list` | 用错运行端点 | 加 `/advanced-chat`（§2） |
| 节点① `url should start with http://` | 环境变量被推图清空 | `--preserve-env` 重推 |
| `blocked by SSRF protection` | Dify 默认拦私网 | 主机 compose 加 `SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.110.0/24` 重建 ssrf_proxy/api/worker |
| 登录 401 `用户名不存在或者密码错误` | 密码没加密 | §4 生成密文 |
| 答案断在半句 | max_tokens 太小 | 2400 + 900 字约束，重新发布 |
| 上游接口 `429`，整轮 0.8s 就 failed | 上游限流（账套/第三方 OpenAPI 常有每分钟配额），**不是**密钥过期 | 先查该节点的 `outputs.error_message`；别急着改密钥/重发。对话场景改用预加载快照接口，别让每次提问穿透上游 |
| 草稿跑得通、服务 API 跑不通，图一模一样 | 环境变量是**按版本快照**存的，草稿与发布版的 secret 密文可能不同 | 先 `--publish-only`（只发布草稿，不推图）再复测；仍失败说明不是 env 问题 |

## 12. 对话型智能体的取数原则（金融/财务类尤其重要）

1. **一问一次上游 = 必挂**。对话里每次提问都穿透到外部 OpenAPI 的接口，早晚撞限流/超时。
   优先找**预加载快照**接口（PIG 的 `ai_finance_dashboard_snapshot` 就是 5 分钟预加载一次）；
   快照接口拿不到的维度，宁可回答「当前未接入」，也不要塞一个会超时的节点。
2. **占比、合计、同比一律在 code 节点算好**。让模型算，它一定会在某个回答里自己加两个数、
   自己算个 74.1%，而且看不出来是编的。快照里给了现成百分比，模型就只会抄。
3. **口径边界写进提示词**。财务类至少写死：进账≠收入、出账≠成本、余额变动≠利润；
   零发生日 ≠ 没有业务。否则模型会把现金收付当成利润表来讲。
4. **技术故障不许变成业务建议**。快照里说明「上游限流导致利润表未生成」即可，
   提示词要明确禁止输出「联系 IT / 找供应商 / 重启任务」这类动作。

## 13. 模拟/演示数据源：必须首行声明（市场类尤其重要）

有些页面接的是 `*_simu_*` 表 / `simulated:true` 的接口（灵猫市场页就是：`crm-simulate`、
`runStatus=PENDING_DATA`）。这种数据源做出来的问答智能体，最大的风险不是答错，是**被当成真数汇报**。

做法：
1. 快照第一段就写数据性质，并把判断依据列出来（`simulated` 原值、来源连接器、agent.runStatus、remark）。
2. 提示词铁律 0：`simulated=true` 时**回答第一行固定输出** `⚠️ 模拟数据（来源 X）…`，
   然后才进正文。`simulated=false` 时自动换成「数据性质：真实连接器数据」。
3. 验收脚本把「首段含『模拟数据』」做成判据，缺了就算不通过。

## 14. 禁算术：光写「禁止计算」没用，要写成机械禁令

实测 qwen3.5-35b 会在四轮里稳定踩这四种「看起来无害」的运算：

| 模型写法 | 它算了什么 | 为什么错 |
|---|---|---|
| 「缺口 14 个」 | 110 − 96 | 110 是预测里的期望值，不是目标 |
| 「大 B 端约 29 个」 | 96 × 30% | 快照只给占比，没给子集个数 |
| 「可转化约 12 个」 | 96 × 12.8% | 快照没算这一步 |
| 「差 2 个百分点」 | 20% − 18% | 快照只说「低于 20% 警戒线」 |
| 「同比 +21.9%」 | 自造口径标签 | 其实是「较上一周期（30 天）」 |

有效的三条做法，缺一效果就打折：
1. **把能算的提前算好写进快照**（日均、近 7 天、环比、净增），模型有现成数就不会自己算。
2. **在快照末尾列「具体禁例」**，用真实踩过的原句（`「110 减 96，缺口 14 个」→ 禁止`）。
   模型对上下文末尾的指令明显更敏感；只写抽象规则会被忽略。
3. **字符串级禁令**：不许出现「同比 / 环比 / YoY / QoQ」四个词，统一写「较上一周期」。
   这类可 grep 的规则比「不要自造口径」有效得多，验收时也能直接 `grep` 复验。

## 15. 枚举窗口参数：固定取最大窗口，别做用户输入

`overview(days)` 只接受 `7/15/30`，其它值抛 400。别在 start 节点放个 number 让用户填——
对话场景必然有人填 12。做法：**URL 写死最大窗口（30）**，30 天天然包含近 7 天/前 7 天，
在 code 节点把短窗口切片算好写进快照即可；顺带避开 Dify 多 query 参数 404 的坑。

## 16. 验收脚本别用 ⚠️ 判兜底

当正常回答的第一行就是 `⚠️ 模拟数据…` 时，「以 ⚠️ 开头 = 兜底」这条判据会把 7/7 正常
全判成失败（实测踩过）。兜底文案要认固定串：`本次没能生成解读`。

## 17. 数字别让模型写：把「数据依据」改成代码直出

2026-10-19 做人事智能体时踩透的一条：**只要模型有机会写数字，它就会自算**（占比、
「还剩 4 天」、「迟到2+未打卡3=5 人异常」、「35−2=33 人」），加多少提示词都堵不完；
而代码侧「逐句删违规内容」又会出现**把整节删空**的副作用（实测出现过空的「一句话结论」）。

稳定解法是把职责切开：

| 谁 | 产出 | 说明 |
|---|---|---|
| `code_facts` | `facts_text` | 给模型看的完整快照（口径、明细、红线、禁例） |
| `code_facts` | `facts_card` | **给用户看的**数字卡片（15~20 条，全部精确、可追溯） |
| `llm` | 只写 `一句话结论` + `建议动作` | 提示词明确：**全文不写数字**（日期/姓名除外），不写「数据依据」 |
| `code_guard` | 拼装 | `banner` + 模型正文 + `**数据依据（系统直出，未经模型改写）**` + `facts_card` |

好处：模型算术错误从「用户可见」变成「不可能发生」；验收时只需检查卡片里的数字。
配套三条实现细节：
1. `facts_card` 里每个数字都要带口径后缀（`人天` / `花名册行数` / `阶段记录数`），
   否则模型在建议里会把它当人数用。
2. `code_guard` 仍保留逐句过滤（占比、天数推算、周几、分类相加）当安全网，
   但**必须**再补一个「空标题清理」：`line.strip().strip("*").rstrip("：:")` 之后比对标题名——
   实测模型会输出 `**一句话结论：**`（冒号在粗体里），只按 `startswith` 判会漏。
3. 过滤后若「一句话结论」整节消失，用 `sys.query` 做**主题兜底句**补位
   （code 节点可以取 `["sys","query"]`，实测 advanced-chat 可用）。
   兜底句只讲判断、不带数字，避免与卡片冲突。

## 18. 情报类数据源：先找「同一个响应里的多个时间窗」

2026-10-19 做行业智能体（`ops/agent/industry`）时发现，`intel/overview` 一个响应里
同时存在**两套时间窗**，这是最容易说错的口径：

| 字段 | 实际含义 |
|---|---|
| 顶层 `periodStart` | 本周一 00:00（按 `period=week` 算） |
| `modules[peer].periodStart` | 本周一（`countLabel=本周新增`） |
| `modules[tech/policy].periodStart` | **当日 00:00**（`countLabel=当日新增`） |

⇒ code 节点必须**逐模块**读它自己的 `periodStart` / `countLabel` 再拼卡片，
不能拿顶层 `periodStart` 统一描述三个模块。同理 `count` 是本期新增、`total` 是累计存量，
两个数一个都不能省 —— 只给 total 会让人以为「一直没更新」，只给 count 会让人以为「就这么多」。

配套的三条经验：

1. **UTC 时间必须转**：AIHOT `hot-topics` 的 `latestAt` 是 `...Z`，直接展示会把
   20:00 的热点写成中午。code 节点里 `fromisoformat(s.replace("Z","+00:00")) + timedelta(hours=8)`。
2. **「新增 0」先看批次结果**：`lastResult` 形如「拉取 23 / 新增 0 / 跳过 23」是幂等跳过，
   不是采集失败。快照里要把这句写死，否则模型会报「行业断更」。
3. **采集覆盖要写明「窄」**：单个关键词检索源只有十几条存量时，任何「行业整体如何」的推断
   都是错的。快照里直接写「不能据此推断行业整体」，并在 `code_guard` 里把
   「行业都在 / 全行业」这类措辞当风险（本应用用主题兜底句兜住）。

### 18.1 `code_guard` 正则的两个自伤 bug（实测）

1. **`周[一二三四五六日天]` 会拦自家文案**：提示词推荐的时点是「下周一前」，
   正好命中 `周一`，把合规句子删了。改成负向断言：
   `(?<![下本上每])周[一二三四五六日天]`。
2. **空标题判定要「先去冒号再去星号」**：`**一句话结论**：` 的结尾是冒号，
   `strip("*").rstrip("：:")` 拿不到标题名。正确顺序：
   `line.strip().rstrip("：:").strip().strip("*").strip()`。
   而且 **`nxt`（下一行）那一处必须同样改** —— 只改 `key` 会出现「标题没删干净、
   但 `一句话结论` 又判断为存在」，最终结果是既没兜底、又留个空标题。

### 18.2 数字白名单：允许抄名字，不允许算数

行业场景里名字本身带数字（`DeepSeek V4.1-Flash`、`深南府〔2026〕11 号`）。做法不是
「一律禁数字」，而是**token 白名单**：

```python
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/+]*")
def _digits_whitelisted(clause, facts):
    for m in TOKEN.finditer(clause):
        t = m.group(0)
        if any(ch.isdigit() for ch in t) and t not in facts:
            return False
    return True
```

再用 `BAD` 正则硬拦「数字+量词 / 百分比 / 具体日期 / 倒计时 / 周几 / 算术式」，
两者叠加：抄快照里的版本号能过，自己算的「14 条里 8 条占 57%」必被删。

### 18.3 验收脚本：口径 banner 不是模型输出

`code_guard` 拼在最前面的 `数据口径：… 统计锚点日 2026-10-19；…` 含日期，会被
「模型段落不许有日期」的判据误伤（本次 8/8 全红）。验收脚本取模型段落时必须先剔掉
以 `数据口径` 开头的行，再跑正则。
