---
name: zentao-batch-tasks
description: 在禅道（ZenTao）里从需求/CSV 批量创建任务、按执行/看板落库、把任务关联到需求并指派给指定账号；也覆盖「列出某项目/看板的全部任务」与「新建执行/看板并把任务整体复制过去」。当用户说「在禅道里建任务」「按这份需求 CSV 批量建任务」「把这个看板填满任务」「把需求拆成任务挂到执行下」「新建一个看板」「把这批任务复制到新看板」「拉取禅道任务清单做汇报汇总」时使用。覆盖 REST API 认证、Cloudflare 拦截、必填字段、中文名到账号映射，以及建执行/复制任务的静默失败坑。
agent_created: true
---

# 禅道（ZenTao）批量建任务

ZenTao 22.x 实战流程。目标：把一批需求（story）拆成任务（task），落到指定执行（execution）下，并关联回需求。

## 一、认证（两条路，优先 REST API）

### 路径 A：REST API Token（首选，最简单）
```bash
curl -sS -X POST "https://<站点>/api.php/v1/tokens" \
  -H "Content-Type: application/json" \
  -d '{"account":"admin","password":"原始密码"}'
# -> {"token":"xxxxxxxx"}   HTTP 201
```
后续所有请求带头部 `Token: xxxxxxxx`。

**注意**：`/tokens` 收的是**原始明文密码**，不要做任何 md5。这是验证凭据对不对的最快探针——它失败就说明账号密码本身有问题，别再去折腾加密。

### 路径 B：Web 会话登录（REST API 被关时用）
ZenTao 22.x 前端登录是「先取随机串、再双重 md5」：
1. `GET /index.php?m=user&f=refreshRandom` → 返回纯数字随机串 `rand`
2. `password = md5( md5(明文密码) + rand )`（字符串拼接后整体 md5，小写 hex）
3. `POST /index.php?m=user&f=login`，form 字段：
   `account, password, passwordStrength, referer, verifyRand(=rand), keepLogin, captcha`
   必须带 `X-Requested-With: XMLHttpRequest` 才回 JSON
4. 成功 → `{"result":"success",...}`；失败 → `{"result":"fail","message":"您还有N次尝试机会。"}`

登录失败有**次数限制**，报「还有 N 次」时立刻停手，别反复重试，否则锁号。

## 二、必踩的坑（都是实测踩出来的）

| 坑 | 现象 | 解法 |
|---|---|---|
| Cloudflare 拦非浏览器 UA | Python `urllib` 请求返回 **403 Forbidden**（curl 却正常） | 请求头加浏览器 UA：`Mozilla/5.0 (...) Chrome/124.0 Safari/537.36` |
| 任务的「预计开始」必填 | `400 {"error":"『预计开始』不能为空。"}` | 创建任务必须传 `estStarted`，通常也要 `deadline` |
| 任务日期受执行区间约束 | 执行有 `taskDateLimit: auto` | `estStarted`/`deadline` 要落在执行（execution）的 begin~end 之内 |
| CSV 导出编码 | UTF-8 解码报 `invalid start byte` | 禅道导出的 CSV 是 **GB18030**，用 `raw.decode('gb18030')` |
| 中文名 vs 登录账号 | CSV 里是「洪志强」这种中文名 | 先 `GET /api.php/v1/users` 拿 account↔realname 映射再填 `assignedTo` |
| CSV 里 `编号` 字段 | 值是 `"319\t"` 带制表符 | 一律 `.strip()` 后再 `int()` |

## 三、常用端点

```
POST /api.php/v1/tokens                                  # 换 token
GET  /api.php/v1/executions/{id}                         # 执行详情（看 begin/end/hasProduct）
GET  /api.php/v1/executions/{id}/tasks                   # 执行下任务列表
POST /api.php/v1/executions/{id}/tasks                   # 创建任务
GET  /api.php/v1/users                                   # 用户列表（account + realname）
```

创建任务的 payload（实测可用）：
```json
{
  "name": "任务名",
  "type": "design|devel|test|ui|affair|misc",
  "pri": 3,
  "story": 313,
  "assignedTo": "hongzhiqiang",
  "estimate": 4,
  "left": 4,
  "estStarted": "2026-10-05",
  "deadline": "2026-10-09"
}
```
`estimate` 没值就整个字段省略（别传 0，否则剩余工时为 0）。返回体里直接带新建任务的 `id`。

## 四、推荐工作流

1. **先探针**：`POST /tokens`。失败就找用户要正确凭据，别猜。
2. **读执行信息**：`GET /executions/{id}`，确认 `begin`/`end`，定 `estStarted`/`deadline`。
3. **读现有任务**：`GET /executions/{id}/tasks`，避免重复建。
4. **解析需求**：CSV 按 GB18030 读，`.strip()` 所有字段。
5. **建映射表**：中文创建人 → 禅道 account（跑一次 `GET /users`）。
6. **干跑**：先 `--dry-run` 打印全部 payload 核对。
7. **正式跑**：逐条创建，每条之间 sleep 0.3s，记录成功/失败清单。
8. **回读校验**：再拉一次任务列表，核对条数、story 关联、指派、工时合计。

`scripts/zentao_batch_tasks.py` 已实现 1–8 全流程：
```bash
python3 scripts/zentao_batch_tasks.py \
  --account admin --password 'xxx' \
  --plan tasks_plan.json --execution 29 \
  --est-started 2026-10-05 --deadline 2026-10-09 \
  --skip-seq 1 --dry-run
```
`--plan` 是 `{"tasks":[{"seq","story","name","tag","assignedTo","estimate","pri"}]}` 结构的 JSON。

## 五、把需求关联到执行（极易踩坑，务必先看）

**只把 `zt_task.story` 写上是不够的。** 需求详情页的「迭代任务」tab 只显示**已关联到本执行的需求**下的任务。需求没关联到执行 → 需求页永远显示空的，任务重建多少次都没用。

### 硬性规则（源码级证据）
`module/execution/model.php::linkStory()` 里：

```php
$notAllowedStatus = $this->app->rawMethod == 'batchcreate' ? 'closed' : 'draft,reviewing,closed';
foreach($stories as $storyID)
{
    ...
    if(strpos($notAllowedStatus, (string)$storyList[$storyID]->status) !== false) continue;
}
```

- **`draft` / `reviewing` / `closed` 状态的需求会被静默跳过**
- 跳过之后接口依然返回 `{"result":"success","message":"保存成功"}` —— 这就是最大的坑，返回成功 ≠ 关联上了
- `projectstory` 模块自己没有 link 逻辑，全部走 `executionModel::linkStory`，**没有旁路**

### 关联接口
```bash
POST /index.php?m=execution&f=linkStory&executionID={id}
     stories[]={storyID}&stories[]={storyID}...       # 字段名就是 stories，必须是数组
     Header: X-Requested-With: XMLHttpRequest
     Header: Referer: https://<站点>/index.php?m=execution&f=linkStory&executionID={id}
```
- 传字符串 `stories=314` 会直接 `Fatal error: array_values(): Argument #1 must be of type array, string given`，反过来可用来确认字段名
- 校验：`GET /api.php/v1/executions/{id}/stories` 看已关联需求清单

### 需求评审通过（把 reviewing 变 active）
```bash
POST /index.php?m=story&f=review&storyID={id}
     reviewedDate=2026-10-05 11:30:00
     &result=pass
     &status=active        # ⚠️ 必须带！见下
     &comment=...
```
`result` 取值：`pass`(确认通过) / `clarify`(有待明确) / `reject`(拒绝)。

**⚠️ 最容易翻车的点：`status` 字段必须显式提交。**
`storyModel::review()` 里是这么写的：
```php
$this->dao->update(TABLE_STORY)->data($story, $skipFields)->autoCheck()->checkFlow()->where('id')->eq($storyID)->exec();
```
它把**表单字段整体覆盖写库**，`$skipFields` 只排除 `finalResult,result,comment`。
所以漏传 `status` → `status` 被写成**空字符串**（不是 active，也不是 reviewing，是个空值），需求变成不合法状态。
且接口照样返回 `{"result":"success","message":"保存成功"}`。补救办法就是带上 `status=active` 重跑一次。

评审通过后别急着往下走，**先 GET /stories/{id} 复核 `status` 真的是 `active`**。

⚠️ 这是**会写入评审记录的业务动作**，等于替评审人签字，执行前必须拿到用户明确授权。
另外：评审**子需求**会触发 `computeEstimate(parent)`，连带改变父需求的 `stage`，属于正常联动。

### 排查顺序
1. `GET /executions/{id}/stories` → 缺哪几条
2. 逐条 `GET /stories/{id}` 看 `status`：`reviewing` 就是被规则挡了
3. 授权后 `f=review` 评审通过 → 再 `f=linkStory`
4. 复验 `GET /executions/{id}/stories` + 需求页能列出 taskID

现成脚本：`scripts/zentao_link_stories.py`（`--check-only` 只读体检，`--review-pass` 先评审再关联）。

## 六、任务拆解模板（智能体/平台类需求，实测好用）


每条需求拆 4 个任务，标签决定禅道 `type`：

| 标签 | type | 内容 |
|---|---|---|
| 方案设计 | design | 业务现状梳理、流程与数据源确认、能力边界与验收口径 |
| 智能体开发 / 基座开发 | devel | 角色与 Prompt 设计、工作流编排、工具调用、知识库沉淀 |
| 客户端集成 | devel | 客户端入口/对话/看板页面集成与数据展示 |
| 联调验收 | test | 端到端联调、测试用例执行、验收上线 |

工时按需求预计工时 / 4 均摊；需求没填工时就整条留空。

## 七、只读：定位项目 → 执行 → 任务列表（「把某项目的任务列出来」）

用户给一个看板/项目 URL（如 `?m=kanban&f=space`）要「列出某项目的任务」时，**不要**去抓 HTML（`f=space` 页面带会话跳转，curl 常拿 302 / 空 body）。走 API 三级下钻：

```bash
GET /api.php/v1/projects?limit=50          # 全部项目：id / name / model / status / parent
GET /api.php/v1/projects/{pid}/executions  # 项目下的执行（看板型项目一般为 type=kanban）
GET /api.php/v1/executions/{eid}/tasks?limit=200   # 任务全量，total 字段给总数
```

要点：
- 看板型项目（`model=kanban`）的任务挂在**执行**下，不在 project 下；一个项目可能只有 1 个执行（如「客户端」）。
- `projects` 默认 `limit=20`，项目多于 20 个时必须显式 `limit=50` 之类，否则漏项。
- `GET /api.php/v1/projects/{id}` 返回体的 `project` 可能是 **int**（不是 dict），解析前先判类型，别直接 `.get()`。
- 任务字段直接用现成的：`assignedToRealName`（中文名，不用自己映射）、`estimate`/`consumed`/`left`、`estStarted`/`deadline`、`pri`、`type`、`status`、`storyTitle`。
- **没有** `kanban`/泳道（lane）API：`GET /executions/{id}/kanban` → 404 `{"error":"not found"}`；泳道信息仅在 web 页面 DOM 里，API 拿不到，别浪费时间。
- 状态码 → 中文：`wait` 未开始 / `doing` 进行中 / `done` 已完成 / `closed` 已关闭 / `cancel` 已取消 / `pause` 已暂停。
- 类型码 → 中文：`design` 设计 / `devel` 开发 / `test` 测试 / `ui` 界面 / `affair` 事务。
- 排序用 `order` 字段（看板列内顺序），同级再按 `id`。
- 同一批任务里任务名可能**重复**（同一需求被指派给多人各建一套），不是数据错误，别去重。

## 八、新建执行/看板 + 把任务整体复制过去（跨执行搬运）

用户说「在禅道里新建一个看板/执行」「把这批任务复制到新看板」时走这条链路。实测可行，但有三组坑。

### 1. 新建执行

```bash
POST /api.php/v1/projects/{pid}/executions
     {"name":"客户端二期","begin":"2026-10-09","end":"2026-10-23"}
```

- **项目只能从 URL 路径取**。body 里写 `project` / `projectID` / `projectId` 一律不认，报 `{"project":"所属项目不能为空。"}`。
- 必填：`name`（迭代名称）、`begin`（计划开始）、`end`（计划完成），缺一个就 400。报错顺序就是校验顺序。
- **`end` 必须 ≤ 项目截止日**，否则 400：`看板截止日期应小于等于项目的截止日期：YYYY-MM-DD`。想更长就得先改项目截止日。
- 返回体直接带新执行 `id`（HTTP 201）。
- **新建的执行默认 `acl=private`**，与项目/原看板不一致。补一刀对齐：
  `PUT /api.php/v1/executions/{id}` → `{"acl":"open"}`
- **建之前先确认要「看板」还是「任务列表」** —— 看板项目只能建 `kanban`，永远拿不到列表视图。详见第九节。

### 2. 复制任务的正确姿势：**建 + 改** 两步

`POST /executions/{id}/tasks` 会**静默丢弃** `status` / `consumed` / `left`：

| 传了 | 实际落库 |
|---|---|
| `"status":"done"` | `wait` |
| `"consumed":5` | `0.00` |
| `"left":3` | `estimate`（被强制等于预计工时） |

所以必须两步：
1. `POST /executions/{newID}/tasks` 建任务（name/type/pri/story/assignedTo/estimate/estStarted/deadline/parent）
2. 对 `status != wait` 或 `left != estimate` 的任务，再 `PUT /api.php/v1/tasks/{newID}` 回填
   `{"...原字段..., "status":..., "left":..., "consumed":...}`

**`PUT /tasks/{id}` 反过来是能改这些的**（实测 `status=done` + `consumed=5` + `left=0` 都生效）。但：
- `finishedBy` 会被改写成**当前 Token 用户**、`finishedDate` 改成**当前时间**，原值保真不了 → 提前告知用户。
- PUT 是全量覆盖语义，要把原字段一并带上，别只传增量（否则可能被清空）。

### 3. 必踩的坑

| 坑 | 现象 | 解法 |
|---|---|---|
| 任务「预计开始」必填 | `400 {"error":"『预计开始』不能为空。"}` | 源任务自己没填日期的，用执行区间的 begin/end 补上再建 |
| `parent` 是字符串 `"0"` | Python `if t.get('parent')` **恒真**，主/子任务分类全错 | 显式判：`v not in ("","0")`；同时注意 map 的 key 类型一致（str vs int），否则 `.get()` 静默返回 None，子任务的 parent 挂不上 |
| `DELETE /api.php/v1/tasks/{id}` | 返回 `{"message":"success"}` 但**任务根本没删**（GET 仍能取到，`deleted=0`） | 必须走 web 会话：`GET /index.php?m=task&f=delete&taskID={id}&confirm=yes` |
| 日期超执行区间 | API **不拦**，照建不误 | `taskDateLimit=auto` 只在 UI 层生效，API 层放行；不必为此改期 |
| 同名任务 | 一个名字对多条记录 | 验收**必须按 ID 映射**比对，不能按名称 join，否则误配一堆 |

### 4. 验收（页面级，比 API 更硬）

执行看板的卡片数据**内嵌在页面 HTML 的转义 JSON 里**，不在独立的 AJAX 接口：

```bash
GET /index.php?m=execution&f=kanban&executionID={newID}
```

页面里卡片形如（注意整体被 `&quot;` 转义、`/` 写成 `\/`，且 `"name"` 是数字不是字符串）：

```
{"column":546,"lane":63,"title":"任务名","id":409,"name":409,...}
```

正确姿势：先 `html.unescape(body)`，再
`re.findall(r'\{"column":(\d+),"lane":(\d+),"title":"(.*?)","id":(\d+)', raw)`
→ 得到卡片 ID 集合，与 `GET /executions/{id}/tasks` 的 ID 集合比对。

列/泳道定义也在同一页，键是 `"cols"` / `"lanes"`（是 JSON 数组，要自己做括号配平截取）：
新建执行会自动继承项目模板的列结构（如 7 列：未开始/已计划/已立项/研发中/交付中/已交付/已关闭 + 泳道「父研发需求」），一般不用手工建列。

> 注：`?m=kanban&f=space`（看板空间）是个 **JS 空壳**（约 12KB），browseType=public/involved/cooperation/private 都不含数据，别指望用它验收。

### 5. 可复用脚本

- `scripts/zentao_web_session.py` — 禅道 web 会话登录（`DELETE` 任务、读看板页都要它）：
  `GET /index.php?m=user&f=refreshRandom` → `pwd = md5(md5(明文)+rand)` →
  `POST /index.php?m=user&f=login`，带 `X-Requested-With: XMLHttpRequest`。导入后直接 `req()` 复用会话。
- `scripts/zentao_copy_tasks.py` — 跨执行复制任务全流程：读源执行 → 建 → 回填 → 输出 ID 映射到 `/tmp/zt_copy_map.json`。
  ```bash
  python3 scripts/zentao_copy_tasks.py --base https://zen.mzlc.me --token <TOKEN> \
      --src 29 --dst 34 --dry-run      # 先干跑核对载荷，再去掉 --dry-run
  ```
- 验收：按 **ID 映射**逐字段比对（名称/类型/优先级/状态/消耗/剩余/负责人），
  再做一次页面级卡片数比对（见第 4 小节）。顺带核对**源看板未被改动**（只读操作不该动它）。

---

## 九、执行类型决定页面视图：看板（泳道） vs 任务列表（表格）

> **用户说「我要的是任务列表，不是这种泳道」时，根因几乎不是样式，是执行类型选错了。**

| 项目 model | 能建的执行 type | 打开的默认页面 |
|---|---|---|
| `scrum` | `sprint`（短期迭代）/ `kanban` | 迭代 → **任务列表**（表格 + 左侧模块树）；看板 → 泳道 |
| `kanban`（看板项目） | **只能 `kanban`** | 只有泳道看板，**没有任务列表视图** |
| `waterfallplus` | `stage`（阶段） | 阶段视图 |

### 一眼判断（实测口诀）

```bash
GET /index.php?m=execution&f=task&executionID={X}
GET /index.php?m=execution&f=kanban&executionID={X}
```

- 两个 URL 返回**字节数完全相同** ⇒ X 是看板型执行，**列表页根本不存在**（`f=task` 被回落成看板页）。
- `f=task` 页面「含『任务名称』**且不含『泳道』**」⇒ 这才是真正的任务列表页。

### 类型建完不可改（三条实测）

- `m=execution&f=edit&executionID={X}` 表单里**没有「类型」字段** → 执行类型建完锁死。
- 看板项目的 `m=execution&f=create&projectID={X}` 表单里**没有「执行类型」/「短期迭代」选项** → 只能建看板。
- 项目编辑页在有执行时**不渲染模型下拉**（模型是 `<input type="hidden" name="model">`，靠点 `.model-drop` 重载页面）→ 想把看板项目改成 scrum，得先清空它下所有执行，等于删数据，**别碰**。

### 强制覆盖 type 也没用

对看板项目 `POST /projects/{id}/executions` 显式传 `{"type":"sprint"}`，返回体里 `"type"` 仍是 `"kanban"` —— 服务端按项目模型强制覆盖，不要试图绕过。

### 结论：要给「任务列表」，唯一正路是在 scrum 项目下建 sprint 执行

1. 建 scrum 项目（`parent` 抄源项目，`vision` 抄源项目）：
   ```bash
   POST /api.php/v1/projects
   {"name":"<名字>","begin":"YYYY-MM-DD","end":"YYYY-MM-DD",
    "parent":<项目集ID>,"model":"scrum","products":[<产品ID>],"vision":"rnd"}
   ```
   - **`products` 必填**（否则报 `『products』不能为空。`）。传 `[]` 也能过，但**传上源任务所属产品 ID** 才能让任务的模块归属和左侧模块树正常显示。
   - 报错顺序即校验顺序：`name` → `begin` → `products`。
   - 建完 ZenTao 会**自动附带一条与项目同名的 sprint 执行**；不要就删（`m=execution&f=delete&executionID={id}&comfirm=yes`，注意源码里就是拼错的 `comfirm`）。
2. 在项目下建 sprint 执行：`POST /api.php/v1/projects/{newPj}/executions`，body 带 `"type":"sprint"`；再 `PUT /executions/{id}` → `{"acl":"open"}` 对齐权限。
3. 用 `scripts/zentao_copy_tasks.py` 把源执行任务整体复制过去（第八节）。
4. 验收：`f=task` 页内嵌 JSON 里 `{"id":N,"project":<newPj>` 的条数 == API 任务数，且状态分布一致。列表页**分页**，别用「任务名命中数」当总数判据。

> 注：`GET /projects/{id}/executions` 对个别新建项目会返回 `{"executions":[{}]}`（空对象），是 API 序列化怪癖，**不代表执行没建成** —— 用全局 `GET /executions?limit=200` 按 `project` 字段筛才准。
