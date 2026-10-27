---
name: dify-zentao-list-dsl
description: 把「禅道某个列表页」做成一个可导入 Dify 的工作流 DSL 文件，并把生成物端到端验证到「抓取条数 == 服务端 total」。当用户说「帮我写一个 Dify 工作流的 DSL 文件」「采集禅道 XX 列表的数据」「参考禅道另外一个 yml 再做一个」「翻页抓禅道任务/需求/Bug 列表」时使用。覆盖：① 禅道 REST v1 取数端点与翻页；② Cloudflare 拦非浏览器 UA（403 error code 1010）这个必踩坑；③ Dify 代码节点输出上限（对象数组 ≤30、字符串 ≤400000）导致的「不能直接返回任务数组」设计；④ 用 Python 脚本生成 YAML（避免手写转义炸掉）+ 独立校验脚本（YAML 合法 / 变量引用可解析 / 代码可编译 / 真实接口跑通）。
agent_created: true
---

# 禅道列表 → Dify 工作流 DSL

## 0. 交付物长什么样

一个 `.yml` 文件（Dify 导入用）+ 两个生成/校验脚本。**不要手写这个 YAML** —— 代码节点的 Python 正文含大量引号/换行，手写 YAML 转义必炸。用脚本生成。

参考实现（可直接抄）：
- `build_zentao_dsl.py` —— 构造 dict → `yaml.safe_dump`，代码块用 `LiteralStr` 子类强制 `|` 块风格
- `verify_zentao_dsl.py` —— 四段校验（见 §4）

## 1. 禅道取数端点（REST v1，Token 认证）

| 用途 | 请求 |
|---|---|
| 登录拿 Token | `POST {BASE}/api.php/v1/tokens`，body `{"account":..,"password":..}`，**成功是 HTTP 201 不是 200**，返回 `{"token":"..."}` |
| 校验执行权限 / 拿执行清单 | `GET {BASE}/api.php/v1/executions?page=1&limit=200` |
| 拉某执行下任务 | `GET {BASE}/api.php/v1/executions/{executionID}/tasks?page=N&limit=M` |

- 认证头就是 `Token: <token>`（不是 `Authorization`）。
- 列表响应形如 `{"page":1,"total":27,"limit":100,"tasks":[...]}`，**`total` 是总数不是当页条数**（但仍建议取 `max(total, len(tasks))` 兜底）。
- 页面 `index.php?m=execution&f=task&executionID=25` ↔ API 里的 `executionID=25`。
- `assignedTo` 是**对象**（`{id,account,realname}`）且可能为 `null`；同时有平铺的 `assignedToRealName`（未分配时为 `""`）。
- `execution` 字段是**整数**不是对象。

## 2. ⚠️ 必踩坑：Cloudflare 封 `python-urllib` 这类 UA（error code 1010）

站点（`zen.mzlc.me`）前面挂着 Cloudflare。**error code 1010 = 按「浏览器签名 / UA」封禁**。
2026-10-15 用 curl 逐 UA 实测（打 `POST /api.php/v1/tokens`）：

| User-Agent | 结果 |
|---|---|
| 裸 `Python-urllib/3.13` | ❌ **403 error code: 1010** |
| 完全不带 UA / 空 UA | ✅ 201 |
| `python-httpx/0.28.1` | ✅ 201 |
| `python-requests/2.32.3` | ✅ 201 |
| `Go-http-client/1.1` | ✅ 201 |
| `curl/8.7.1` | ✅ 201 |
| `Dify/1.0.0` | ✅ 201 |
| Chrome 130 UA | ✅ 201 |

结论修正（别再套用"CF 拦一切非浏览器 UA"的错误结论）：**CF 只对特定已知 UA 特征下手**，
`python-urllib` 是典型靶子（扫描器常用），而 httpx / requests / 空 UA 都能过。

**但仍然要给每个 HTTP 节点显式加浏览器 UA**（`Mozilla/5.0 ... Chrome/130.0.0.0 Safari/537.36`）——
不依赖 Dify 默认值，且规则随时可能收紧。多行 headers 用
`LiteralStr("Token:{{#x.y#}}\nUser-Agent: " + UA)` 生成，YAML 渲染成 `|-` 块，不会被折叠吃掉换行。

### ⚠️ 未闭环的问题（2026-10-15，别重复踩）

用户把生成的 DSL 导入 Dify 运行后，**第一个红节点就是「禅道登录拿Token」，报错仍是 403 / error code 1010**，
而且这时 headers 里**已经显式写了 Chrome UA**。这跟上面的 curl 实测结果**直接矛盾** ⇒
说明**节点里配的 User-Agent 根本没发出去**。待验证的候选（按可能性）：

1. Dify 的 **SSRF 代理（squid）** 剥掉或覆盖了自定义请求头；
2. Dify http-request 节点的 **多行 `headers` 文本没被正确解析**（第一行生效、第二行被丢）；
3. 用户实际运行的不是带 UA 的那份文件（版本串了）；
4. CF 拦的是别的特征（但 1010 明确是 UA/浏览器签名类，可能性低）。

**下一步做法**：① 把 headers 精简成**只有一行** `User-Agent: ...`（排除多行解析问题）；
② 在 Dify 里用单节点调试只跑登录节点看请求头；③ 兜底方案 —— **不直连禅道**，
让 Dify 打一个本机反向代理（Python/FastAPI 或 nginx），由代理注入 UA 再转发到禅道
（用户本工作区本来就有 `linmo-python-ai` 容器可挂端点）。

## 3. 排障技巧：拿"能跑通的参考 DSL"做逐字段 diff

手上有另一份**已知可跑**的同站点 DSL 时，别靠肉眼比。用脚本做两级 diff，能 5 分钟排除结构问题：

- **字段级**：逐节点比对 `node` 的键集合与 `node["data"]` 的键集合 → 抓"漏了必填字段"。
- **取值级**：递归比对 `node["data"]`，跳过 `desc/title/position/height/width/zIndex/selected` 等布局噪音
  → 剩下的每条差异都应是**有意改动**，否则就是 bug。
- **边级**：比对 `source/target/sourceHandle/targetHandle/type` 与 `data` 里的
  `isInIteration/iteration_id`（迭代内部边还有 `zIndex=1001`）。

2026-10-15 用这招确认过：新生成文件与参考文件在 12 个共有节点上**字段与连线完全一致**，
从而把故障范围从"DSL 写错了"收敛到"运行期/环境"。**这份 DSL 严格线性**（start→login→extract→list_exec→
validate→page1→parse→iterate→merge→end），单点失败只会让 1 个节点报错 —— 所以 Dify 提示
「流程中有 N 个节点运行异常」时，要看追踪里**第一个**变红的节点，别被 N 这个数字带偏。

## 4. ⚠️ Dify 代码节点输出上限 → 决定了管线形状

| 类型 | 上限 |
|---|---|
| 对象数组 / 字符串数组 | **30 个元素** |
| 字符串 | **400000 字符** |
| 数字数组 | 1000 |

推论（照抄，别重新发明）：
1. **代码节点绝不返回「任务数组」** —— `page_size>30` 会直接报 `The length of output variable xxx must be less than 30 elements`。改为在节点间传**原始 body 字符串**，只在最后一个 merge 节点里 `json.loads`。
2. 翻页计划用**数字数组**（页码列表，上限 1000，够用）。
3. merge 出来的 `tasks_json` 用 ~380000 字符做阈值，超了**显式标记** `tasks_truncated=true` 并写进报表，**绝不静默截断**。

## 5. 管线形状（12 节点，已验证）

```
start(execution_id, page_size)
 → login(POST /tokens)              → 提取Token(code)
 → 取可访问的执行清单(GET /executions) → 校验执行ID权限(code)   # 不在清单里就报错并列出可用 ID
 → 拉取第1页任务(GET tasks?page=1&limit=page_size_safe)
 → 解析首页与翻页计划(code → first_page_body + remaining_pages[] + total)
 → 迭代拉取后续页(iteration) ─┐
                              └→ 拉取第N页任务(GET tasks?page={{item}})
 → 汇总全部任务(code)  # 合并首页 body + 迭代输出的 body[]，去重/排序/出 Markdown 表 + tasks_json
 → 结束(tasks_json / report_markdown / fetched_count / total)
```

关键设计点：
- **校验执行权限节点**：`error_strategy: default-value` + `default_value`(body/status_code)，权限校验失败时不阻断主流程（尽力而为）。
- **禅道失败也会返回 HTTP 200**：body 是 `{"status":"fail","message":"..."}` **紧接**另一段 JSON。所以解析必须用 `json.JSONDecoder().raw_decode()` **只解析首段**，否则会抛 `Extra data` —— 看起来像代码 bug，其实是权限问题。**翻页时遇到 fail 必须报错，不能静默跳过**（静默跳过 = 伪造成功）。
- 迭代节点：`flatten_output: true`、`output_type: array[string]`、`output_selector: [fetch_page_n_node, body]`；`merge` 用 `[iterate_pages_node, output]` 接。
- 负责人取值优先级：`assignedToRealName → assignedTo(对象取 realname/account/id)`，都空 → `未分配`。
- 报表标题带上执行名（校验节点顺带返回 `execution_name`），便于辨认。

## 6. 环境变量（DSL 里声明，值留空）

| 名称 | 类型 | 说明 |
|---|---|---|
| `ZENTAO_BASE` | string | `https://zen.mzlc.me`（不带末尾斜杠） |
| `ZENTAO_ACCOUNT` | **secret** | 禅道账号 |
| `ZENTAO_PASSWORD` | **secret** | 禅道密码 |

**不要把明文口令写进 DSL 文件**（会进版本库/分享出去）。凭据只在导入 Dify 后填在环境变量里。

## 7. 校验脚本必须做的四件事

1. `yaml.safe_load` 通得过，并打印节点/边数量。
2. 扫 `{{#node.var#}}`：**每个引用都要能解析**。给每个节点建「可提供变量表」（code 节点取 `outputs` keys；http-request 固定 `body/status_code/headers/files`；start 取 `variables`；iteration 有 `output/item/index`），引用对不上就报错。
3. 每个 code 节点的 `code` 过 `compile()`，抓语法错误。
4. **端到端真跑一遍**：把 code 节点的 `code` 用 `exec()` 装进命名空间、按 DSL 里的 `variables` 映射调用 `main(**kwargs)`，HTTP 步骤用同样的 UA 真打接口。最后断言 `fetched_count == 服务端 total` 且 `len(tasks_json) <= 400000`。顺带断言一个**不存在的 execution_id 会报错**（反向用例）。

第 4 步是关键 —— 只做 1~3 只能证明「文件格式没问题」，证明不了「跑起来能取到数」。

## 8. 收尾

- 交付物：`<名字>.yml` + `build_*.py` + `verify_*.py`（脚本本身就是可复现的源码，别删）。
- 告诉用户导入后在**环境变量**里填账号密码，以及默认 `execution_id` 是多少。
- 参考实现对话：禅道执行任务抓取（执行 ID 25「一期实施」/ 40「客户端二期」）。

## 9. 脚本已按执行 ID 参数化 —— 换列表只需一条命令

不要每次重写脚本，也不要在源码里改数字再跑。参考实现的两个脚本都已接受执行 ID 作为 `argv[1]`：

```bash
python3 build_zentao_dsl.py 40     # → 禅道执行任务抓取-执行40.yml（app 名/描述/默认 execution_id 全部自动带 ID）
python3 verify_zentao_dsl.py 40    # 端到端校验同一个文件
```

**建议的新增执行流程**：① 先打一次 `GET /executions?page=1&limit=200` 确认 ID 存在并拿到执行名/条数（顺带校验脚本里的断言预期）；② 跑 `build` + `verify`；③ 交付 `.yml`。

已知执行清单（`zen.mzlc.me`，随项目推进变化，以实际接口为准）：

| ID | 名称 | 类型 |
|---|---|---|
| 40 | 客户端二期 | sprint |
| 29 | 客户端 | kanban |
| 25 | 一期实施 | sprint |
| 22 | 首期智能信访能力建设迭代 | sprint |
| 9 / 11 | Spring0 / Spring1 | sprint |
| 14–19 | 需求/设计/开发/测试/发布/总结评审 | stage |
