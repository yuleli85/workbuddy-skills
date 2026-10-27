---
name: xdy-daily-account-data
description: 抓取小豆芽（xdy）账号的当日/近期数据并出日报 —— 每日版本检查 → 跑采集+入湖流水线 → 补拉晚入库数据 → 用 analyze.py 按 account_id 出数 → 产出 L0/L1/L2/L3 分层报告与异常清单。当用户说「抓取小豆芽的今日账号数据」「小豆芽账号数据」「小豆芽日报」「今天的账号数据」，或需要查看抖音/小红书/公众号/头条号/知乎各账号的趋势与作品指标，或定时自动化每天跑小豆芽采集时使用。
agent_created: true
---

# 小豆芽账号数据每日抓取

**目标**：把团队 7 个账号（5 个平台）的**当日及近 7 日数据**拉到本地落盘、同步入湖，并产出一份可回溯的分层日报。

**核心不是"查一次数"，是"别丢数据"** —— 免费版查询窗口只有**最近 7 天且滚动**，越界直接拒绝。不落盘，历史数据永久拿不回来。所以流程里「落盘 + 入湖」优先于「出报告」。

## 资产位置（先记住这三个）

| 项 | 路径 |
|---|---|
| 采集器 | `/Users/shan/WorkBuddy/2026-10-09-18-06-59/xdy-collector` ← 记作 `$C` |
| Python | `/Users/shan/.workbuddy/binaries/python/versions/3.13.12/bin/python3` ← 记作 `$PY` |
| 报告输出 | `/Users/shan/WorkBuddy/小豆芽/output/小豆芽账号数据_YYYY-MM-DD.md`（同名 `.html` + 4 个 CSV，2026-10-16 起统一落这里） |

采集器有完整说明：`$C/README.md`（脚本参数、入湖契约、排障对照全在里面）。**遇到本文没覆盖的问题，先读它。**

---

## 执行流程

### 0. 每日版本检查（每次会话首次执行）

```bash
/bin/zsh -lic 'xdy-cli update 2>&1; echo "update_exit=$?"'
```

**必须放进 `zsh -lic`**：`xdy-cli` 装在 nvm 的 node 目录下，`npm` 的 shebang 是 `env node`，直接跑会解析到 WorkBuddy 托管 node 而报错或走错环境。

- 输出 `✓ 已是最新版本` → 继续。
- **有新版** → 等更新与 Skill 同步完成后**重新读取 xdy-cli 的技能文档**，再继续（指标口径可能变）。
- 检查失败（离线等）**不阻塞业务**，直接继续，稍后补。

> 同一天内无需重复；不确定当天是否查过就跑一次。它是幂等的。

### 1. 判断上次跑到哪、今天该不该跑

```bash
cd "$C"
cat state.json                      # last_refresh_date → 今天是否已下发过刷新
wc -l data/csv/*.csv                # ★ 长表行数：比上一日骤减 = CSV 可能被删（见陷阱 5）
ls data/raw/                        # 已有的原始存档日期
ls -t logs/ | head -8               # 最近日志
tail -20 "logs/pipeline-$(date +%F).log" 2>/dev/null
"$PY" analyze.py --cover            # 各账号数据到位到哪天
```

用 `analyze.py --cover` 而不是手写脚本看覆盖 —— 它按 `account_id` 聚合（原因见「关键陷阱 1」）。

**同一天内被再次调用时**（`state.json.last_refresh_date` 已是今天）：不必期待新数据 —— `--refresh` 会跳过下发，
服务端若还没到刷新时点（约 17:50），拉回来的就是上午那批。**照跑无妨，但要先说清「本轮预期 0 新增」。**
判据永远是 `analyze.py --cover` 的 `max(date)` 与当日行数，不是流水线的退出码。

### 2. 跑流水线（采集 + 入湖）

```bash
cd "$C" && ./run_pipeline.sh
```

**建议后台跑**（含 `data update` 下发与多平台分页拉取，通常 10 秒～2 分钟）。

退出码：`0` 两段都成 ｜ `1` 采集失败 ｜ `2` 入湖失败 ｜ `3` 都失败。

流水线做的事：① `collect.py --refresh`（先下发采集、再拉数落盘）② `push_to_linmo.py`（本地 CSV → 灵猫 PIG 入湖）。

### 3. 补拉一轮（**关键，别省**）

```bash
cd "$C"
sleep 45
"$PY" collect.py --refresh 2>&1 | tail -8
```

**为什么必做**：服务端各平台入库节奏不同，一轮往往只拿到部分账号。实测补拉常能多拿几十行趋势 + 若干作品（曾一轮补出 +39 行趋势 / +3 条作品，并纠正了前一轮落盘的「播放 0 / 发布 0」为「11 / 1」）。

**但补拉连续 0 新增也是正常的** —— 说明服务端尚未刷新（跑得早于约 17:50），而不是脚本坏了。
今天 08:55 与 15:26 两轮就完全一致（同为 0 新增，`trend_update_time` 一行未变）。
**「0 新增」不构成失败**，不要为此反复重跑：跑一次确认即可，然后在报告里写明数据时点。

`--refresh` 有 **每日下发守卫**（`state.json.last_refresh_date`），重复运行只会跳过下发、不会重复提交 `data update`。所以补拉是安全的、可多次的。

补拉后**再跑一次入湖**补齐新数据：

```bash
"$PY" push_to_linmo.py 2>&1 | tail -10
```

### 4. 出数（一律用 analyze.py）

```bash
cd "$C"
"$PY" analyze.py --cover                  # 到位情况（判断哪些号还没补齐）
"$PY" analyze.py --days 4                 # 全账号近 4 日关键指标 + 最近作品
"$PY" analyze.py --date 2026-10-14        # 某一天的全部指标
"$PY" analyze.py --days 7 --no-works      # 只看趋势
```

**禁止手写聚合脚本取数**。要临时算就基于 `analyze.py` 的输出二次处理，或明确按 `account_id` 分组。

### 5. 出报告

按 `references/daily-report-template.md` 的骨架写，落到工作区根目录。

#### 5.1 摘要段已自动化（2026-10-17 起，别再手补）

```bash
cd /Users/shan/WorkBuddy/小豆芽
"$PY" scripts/fetch_xdy_daily.py <YYYY-MM-DD>                       # ① 先抓当日快照 → output/xdy_snapshot_<date>.json（render 的输入，没有它 render_xdy_report 会 FileNotFoundError）
"$PY" scripts/xdy_digest.py <YYYY-MM-DD>                            # ② digest → output/xdy_digest_<date>.md
"$PY" scripts/render_xdy_report.py output/xdy_snapshot_<date>.json  # ③ 渲染 .md（digest 自动插到标题下方）
"$PY" scripts/render_xdy_html.py   output/xdy_snapshot_<date>.json  # ④ 渲染 .html（抽 .md 的「关键结论」+ 登录失效告警）
"$PY" scripts/render_xdy_csv.py    output/xdy_snapshot_<date>.json  # ⑤ 产出 4 个 CSV（账号清单/指标/指标长表/作品明细）
```

> 📌 **「指标长表」= 采集器 `account_trend.csv` 原样复制**（2026-10-22 起，liyuying 要求）：
> 逐日 × 账号 × 指标，含 `account_id / platform_id / login_status / trend_update_time / pulled_at` 全列。
> 旧的「窗口聚合长表」（今日+近7天两档、只有账号名没有 account_id）已废弃 —— 缺逐日粒度没法透视。
> `render_xdy_csv.py` 找不到采集器长表时会退回旧格式并在 stderr 告警。

> ⚠️ **顺序必须是 fetch → digest → render**：`xdy_digest.py` 不产出快照 JSON，`xdy_snapshot_<date>.json` 由 `fetch_xdy_daily.py` 生成；跳过 ① 会让 ③ 直接报错。
> ⚠️ **HTML 抽结论的硬条件**：md 里标题必须是**二级** `## 关键结论`（写成 `###` 抽不到），且条目默认支持 `- ` / `1.` / `1)`（2026-10-19 已修掉只认 `- ` 的 bug）。渲染完用 `grep -c "<结论里的关键词>" output/小豆芽账号数据_<date>.html` 验证真的进去了。
> ⚠️ **digest 解析的「入湖轮次归属」基本不可信**（2026-10-18 / 10-20 / 10-21 连续复现：把首轮数字挂到补拉名下、PIG 落库行数取的是首轮值）：摘要表的「入湖 / PIG 落库」两行**一律按 `logs/push-<date>.log` 的每轮实测数字手写**，最终落库行数以最后一轮 `PIG 侧落库行数` 为准。别再指望自动解析，浪费一次核对。

`xdy_digest.py` 自动产出三段（**跑在 render 之前**，否则 render 看不到 digest）：

| 段 | 数据来源 |
|---|---|
| 抓取结果 | 解析 `logs/collect-<date>.log` + `logs/push-<date>.log`（两轮自动区分）+ CSV 行数 |
| 数据到位情况 | 按 `account_id` 聚合 `data/csv/account_trend.csv`（max(date) / 天数 / 登录状态 / 最近刷新） |
| 发布矩阵 | `works.csv` 按 `publish_local` 归日（含全平台零发布日提示） |

**只剩两段要人工 Edit**：`## 关键结论`（需跨日跨平台判断，脚本留 `<!-- KEY-CONCLUSIONS -->` 占位）与
`## 口径与异常清单`（半静态）。HTML 侧会自动从 `.md` 抽「关键结论」渲染成置顶卡片
（**单一来源，不要在 HTML 里重复维护结论**），并自动列出登录失效账号告警条。

> 日志是**追加**写入的，同日多轮都能解析出来 —— 所以「首轮 / 补拉」两个数字是自动区分的，不用记。

> ⚠️ `render_xdy_report.py` 会**覆盖**同名 `.md`。同日重复执行时先跑 digest + render 拿新骨架，
> 再把当天已论证的结论 Edit 回去；或者先备份旧 `.md` 再对比。

> ⚠️ **同一天内重复执行时，增量更新已有报告，不要整体重写。** 文件名固定为
> `小豆芽-今日账号数据-YYYYMMDD.md`，同日第二次跑会命中同一路径 —— 用 Edit 追加/校正
> （如补一行「二轮核对记录」、在异常清单加一条），把当天已论证的结论保留下来。
> **重写会丢掉当天早先的分析。** 具体做法：改头部采集时间行 → 改「数据到位」段 →
> 表格里加一行核对结果 → 异常清单加一条 → 页脚注明两轮。

**必须包含**（缺一不可）：

1. **抓取结果表**：窗口起止、趋势长表行数（首轮新增 / 补拉新增）、作品表行数、入湖条数与失败数
2. **数据到位情况**：哪些账号到当天、哪些还停在前一天，并说明原因（跑早了 / 服务端未刷新）
3. **今日实际数据**：按 `account_id` 分列，不按账号名
4. **1~3 个真正的结论**：跨日/跨平台的趋势判断，不是数字罗列
5. **口径与异常清单**：小样本、零样本残留、未满额日期等

再用 `show_widget` 出一张图讲清当天最重要的那个发现（**当前 IDE 是 light 主题 → 亮色背景 + 深色文字**）。

### 6. 收尾

- 采集器有新踩的坑 → 追加到 `$C/README.md`
- 写当日工作区记忆日志
- `present_files` 呈现报告 + 数据表

---

## 关键陷阱（都踩过，逐条遵守）

### 1. ⚠️ 抖音有两个同名账号「猫仔灵创」——必须按 `account_id` 聚合

| 账号名 | 别名 | account_id 前缀 |
|---|---|---|
| 猫仔灵创 | （空） | `28282ea3…` |
| 猫仔灵创 | 灵创 | `337c6af2…` |
| 猫仔灵创日常号 | 日常号 | `80dfa5f5…` |

按 `account_name` 分组会把两个号**合并成一个，后写覆盖先写，且不报错**。

- 落盘侧安全：`collect.py` 幂等键与 PIG 契约 `xdy_account_trend` 的幂等键**都含 `account_id`**。
- 易错侧只有**分析环节** —— 这就是 `analyze.py` 存在的理由，它检测到同名账号会主动告警。**看到告警不要忽略。**
- ⚠️ **报告里的 L4 作品表与 L3 部分标题按 `account_name` 渲染，不显示 `account_id`** —— 两个「猫仔灵创」在表里长得一模一样。
  任何关于「同一作品是否双发 / 谁发的」的判断，**必须回 `data/csv/works.csv` 按 `account_id` + `work_id` 核实**，别只看渲染后的表。
  2026-10-24 就因此把「同一支 54.955s 素材错峰投两号（主号 09:55 / 灵创 14:53，`work_id` 不同）」误判成「同标题同秒双发」，次日才更正。
  判据：`work_id` 相同才是重复投递；`work_id` 不同但 `duration_sec` 相同 = 一稿多号矩阵分发（正常的运营动作，不是 bug）。

### 2. ⚠️「刷新时间」≠「数据到位」

`trend_update_time` 变成今天，**不代表今天有曲线点**。实测多次出现「6 个账号刷新时间全是今天，但只有 2 个号有当天数据」。

**判到位看两个东西**：`max(date)` 是否等于今天 + 当日行数是否满额（满额约 96 行 = 7 账号 × 约 13.7 指标）。

还有第三种状态「**半行**」：某日存在但只回 1~2 个指标（2026-10-21 实测头条 10-20 只有 `总收益=0`，曝光/播放/粉丝全缺）。**缺 ≠ 0**，不能读成「当天归零」；在报告里标注并次日复核是否补齐。

### 2b. ⚠️ 登录状态是会变的 —— 每次都要按 `account_id` 对比昨日

`loginStatus` 只有 `Succesed`（正常，平台原文少一个 s）与 `Never`（失效）两种取值。
**失效是突发事件，不是一次性事故**：2026-10-17 小红书 `74b2d50978` 就从连续 3 天的 `Succesed` 翻成 `Never`，
当天数据直接缺行。所以：

- 出数前**必须**拿今天的 `loginStatus` 跟昨天快照（`output/xdy_snapshot_<昨天>.json`）逐 `account_id` 对比，
  把「新增失效」当成当天第一优先级结论写进报告，别只当成一行备注。
- 失效的账号 `data works` 会返回 **0 条**（不是报错）→ L4 里该平台整段消失，**要在报告里注明「不是漏抓」**。
- L2「今日账号数据」里，失效账号可能仍返回三个 0（`留言 / 点赞 / 喜欢`）—— 那是**失效前最后一天的陈旧残留**，
  不是今日数据，必须标注，否则会被误读成「今天数据是 0」。
- 失效账号的点位判定同理：数据止于失效前一天，此后每天都缺，且 7 天窗口滚动 → **修得越晚，永久丢失越多**。

### 3. ⚠️ 单条作品的比率指标在小样本下会整个翻转
抖音那条 10-10 的作品：`playCount=3` 时读 `2秒跳出 50% / 5秒完播 50%`，涨到 `playCount=20` 时变成 **`58.6% / 3.4%`**。

**任何单条作品的 `bounce_rate_2s` / `completion_rate_5s` 判断，都要等 `playCount` 上百。** 播放为 0 却有条率读数 = 零样本残留值，直接忽略（曾见「播放 0 / 均播 25s」）。

### 4. ⚠️ 7 天窗口是滚动的，数据会永久滑出

免费版：账号趋势 7 天、作品 7 天（付费才 30 / 90 天）。语义是「最近 N 天**含今天**」，即 `[今天-6, 今天]`，**不是「任意区间内最多 N 天」**；越界**直接拒绝、不自动截断**。

→ 这就是「每天都得跑」的原因。漏一天就少一天，且拿不回来。好在窗口滚动，明天的运行会补上仍落在窗口内的日期。

**「某天 D 的最后可补日」= D+6 当天**（窗口起点正好是 D 的那一天）。如 10-16 的数据，10-22 仍在窗口内、10-23 起永久丢失。**别靠心算**，直接 `date -j -f %Y-%m-%d <D> +%Y-%m-%d -v+6d` 算。2026-10-18 报告就因为算错，误把「还在窗口内」写成「已永久滑出」。

### 5. ⚠️ `data/raw/` 是真正的底牌，别删；CSV 丢了它才救得回来

`merge_csv` 的设计是「当前 API 响应 + 现有 CSV」，**它不读 `raw/`**。所以 `account_trend.csv` 一旦被删，就只剩 7 天窗口能拉回的 ~515 行，更早日期**永久缺块**。

**为什么还能救**：`data/raw/<日期>/` 是**逐日累积**的 —— 每次运行的窗口 `[today-6, today]` 会把当时能看到的更早日期一并 dump。按**日期正序**并集所有存档即可还原完整长表（2026-10-15 实测从 raw 还原出 1082 行 / 13 天，与事发前完全一致）。

**两道防线**：
- 自动：`collect.py` 合并前调 `seed_trend_from_raw()` —— CSV 不存在而 `raw/` 有存档就自动重建种子（定时任务路径同样受保护）。
- 手动：`python3 rebuild_from_raw.py --dry-run` 预演 → `python3 rebuild_from_raw.py`（自动备份）。恢复后**重跑入湖 + 直查校验**。

→ 结论：**要清空间就清 `logs/`，绝不要清 `data/raw/`。**

### 6. `data update` 是写操作、非幂等，每天只提交一次

没有 taskId、没有进度接口、不自动重试，返回 `submitted` **只代表已下发**。守卫在 `state.json`，**不要绕过脚本直接调 `data update`**。

### 7. 其他口径纪律

| 坑 | 纪律 |
|---|---|
| AVG / LAST 类指标 | **跨天、跨账号求和没有意义**，只能横向比 |
| 指标缺失 | **不等于 0**。指标集按平台裁剪，窗口内无曲线点的指标会被整个剔除 |
| 比率字段 | 作品表是**小数**（`0.625` = 62.5%）；小红书 `coverClickRatio` 是**百分数**（`12` = 12%） |
| 账号播放量 vs 作品播放量 | `data account` 是**当日新增**，`data works` 是作品**累计**，两者不等不是矛盾 |
| 登录状态成功值 | `Succesed`（少一个 s），不是 `Successed` |
| 手动跑的时点 | 服务端约 **17:50** 刷新。白天（09:00/13:45/15:15）手动跑，当日数据天然不全，**属正常，不是故障** |
| ⚠️ **盘中当日低值不能当趋势拐点** | 当日的「低」极可能只是**未结算**。实测知乎 10-15 盘中读 **5**（据此写了「已近归零」），结算后实为 **37**；10-16 盘中读 4，实为 33。**判定衰减必须用「已结算日」**（即 ≤ 昨天），当日值只能看不能判 |
| ⚠️ 自写脚本读 CSV 会踩两个格式坑 | ① `account_trend.csv` 表头带 **BOM**，用 `utf-8` 读首个列名会变成 `\ufeffdate`（KeyError），一律用 `utf-8-sig`；② `works.csv` / 长表的 `platform_id` 是**数字串**（`3`/`5`/`12`/`1`/`2`），不要用 `p3` 之类别名去匹配。发布矩阵这类 `analyze.py` 不覆盖的统计才需自写，且只做二次处理 |

### 8. 定时器已存在两条，别再建

| 来源 | 时间 | 入口 |
|---|---|---|
| WorkBuddy 自动化「小豆芽账号数据每日采集」 | 每天 20:00 | `./run_pipeline.sh` |
| macOS LaunchAgent（`install_schedule.sh`） | 实际 21:00 | 同一个 `run_pipeline.sh` |

两条都不重复下发（守卫），且**单实例锁 + 幂等推送**保证重叠执行也安全 —— 只是白跑一轮采集。**创建自动化前先查是否已存在，不要新增第三条。**

---

## 数据解读基线

### 账号 → 流量主指标（横向比较时用这个）

| 平台 | 账号 | 流量主指标 |
|---|---|---|
| 抖音 | 猫仔灵创 ×2、猫仔灵创日常号 | `playCount` 播放量 |
| 小红书 | 清风徐来 | `exposureCount` 曝光数 |
| 微信公众号 | 猫仔灵创 | `playCount` 播放量 |
| 头条号 | 端庄原野P1y | `exposureCount` 曝光数 |
| 知乎 | 赖小赖 | `readCount` 阅读数 |

### 平台机制不同，不能用一套节奏管

| 平台 | 机制 | 含义 |
|---|---|---|
| 小红书 | **推荐流** | 发布即入流量池。停更断流、复更回量。曝光对「是否更新」高度敏感（实测停更 3 天后复更，当日曝光回 4 倍） |
| 知乎 | **搜索 / 长尾** | 单篇阅读由搜索与历史沉淀决定。**发新内容不抬升旧内容**，老文长尾衰减完就一路向下 |
| 抖音 | **推荐 + 更新权重** | 完全停更时流量迅速归零；也是唯一提供「单条前 3 秒」指标的平台 |

**判断掉量时先分开两种成因**：① 内容变差（看比率类指标是否恶化）② 平台不给量。若**质量类指标稳定但流量暴跌**（实测：封面点击率 6 天稳在 12~19 不动，曝光 -95%），多半是停更导致，而不是内容退步。

### 发布量口径：用作品表归日，别用趋势表 `publishCount`

统计「某天到底发了没有」，**用 `works.csv` 按 `publish_local` 归日**，不要用趋势表的 `publishCount` ——
后者受「当日数据未补全」影响会读出假的 0（实测 10-13 趋势表 `publishCount=0`，而作品表明确有 2 条公众号发布）。

按「平台 × 日期」排成矩阵后，一眼能看出**谁在发、谁停了** —— 这是解释流量衰减最快的视角，比逐账号看指标直观得多。
矩阵用法：格子 = 当日发布条数，再叠一列「最新流量 vs 基准日的降幅」，就能直接呈现「停更 → 断流」的对应关系。

### 抖音「单条前 3 秒」是本团队唯一可指导内容创作的量化口径

作品表（`works.csv`）对抖音作品给出 `bounce_rate_2s` / `completion_rate_5s` / `avg_view_time`。分析开头效果**必须按 `duration_sec` 分层**（15 秒竖屏短片与 143 秒宣传片口径不同，不可混比）。

---

## 排障

| 现象 | 先查 |
|---|---|
| 流水线退出码非 0 | `tail -40 "logs/pipeline-$(date +%F).log"`，再分别看 `logs/collect-*.log` / `logs/push-*.log` |
| 采集 0 行 / 大量平台无数据 | 客户端是否离线（`data update` 下发失败只记日志、不中断）；`analyze.py --cover` 看服务端仓库里已有多少 |
| 入湖 `HTTP 404`（Tomcat HTML） | `config.json` 的 `linmo.ctx_path` 少了 `/admin` |
| 入湖 `401 内部令牌无效` | 两端令牌不一致（灵猫仓库 `deploy/.env.dev` 的 `INTERNAL_AI_TOKEN`） |
| 入湖 `400 契约未登记` | 跑 `$C/sql/xdy_contracts.sql` |
| 入湖 `HTTP 0 URLError: Connection refused` | **PIG 全栈没在跑**，不是契约/令牌问题。先 `docker ps`（正常应有 `deploy-*` 一串容器，只剩 `1panel` 就是全停了）与 `lsof -nP -iTCP:9999 -sTCP:LISTEN`（空 = 无监听）；`curl --noproxy '*'` 返回 `000` 才证明真停（返回 502 是系统代理在代答）。**采脚本本身照常可用，本地数据无损**，别为此重跑采集。PIG 起来后跑一次 `push_to_linmo.py` 即可补齐 —— 这是停机不是重建，**不要用 `--full`** |
| 凭据问题 | 凭据**不在采集器目录**：小豆芽走 `~/.xdy-cli.yaml` / `$XDY_ACCESS_KEY`；灵猫令牌走 `--token` → `$LINMO_INTERNAL_TOKEN` → `~/.linmo-collector.env` → 灵猫 `deploy/.env.dev` |
| ⚠️ 入湖日志只有一行「**未找到内部令牌**」（不是 401） | `config.json` 的 `linmo.env_file` 指向的文件**路径不存在**。灵猫仓库已把 `deploy/.env.dev` 拆成按开发者的 `.env.<user>`（本机为 `.env.liyuying`），2026-10-20 因此整轮入湖失败。处置：`ls /Users/shan/work/linmo-pig-full/deploy/.env*` 确认真实文件名 → 改 `config.json` 的 `linmo.env_file` → 重跑 `push_to_linmo.py`（**采集不必重跑，CSV 已落盘**） |
| ⚠️ 入湖日志出现 `新增 N / 覆盖 0` **且带 `自动建表/变更：CREATE TABLE`** | **PIG 侧 ODS 表被清空重建过**（见下节）。水位线只回补最近 7 天 → 历史数据会缺。跑 `push_to_linmo.py --full` 补全 |
| ⚠️ **`account_trend.csv` 不见了 / 重跑后趋势长表行数骤减**（如 1082 → 515） | CSV 被删（2026-10-15 真实发生过）。**7 天窗口拉不回更早日期**。`collect.py` 会自动从 `raw/` 重建种子（日志打印 `⚠️ 趋势长表缺失，已从 raw 存档重建种子 N 行`）；要预演或核查就手动 `python3 rebuild_from_raw.py --dry-run` → `python3 rebuild_from_raw.py`。恢复后重跑入湖并直查校验 |

**不要把 AccessKey 或内部令牌打印到输出、写进报告或日志里。**

### ⚠️ PIG 全栈重建后必须手动全量重推

**症状**：入湖日志从平时的「新增小 / 覆盖大」变成「**新增大 / 覆盖 0**」，并打印 `自动建表/变更：CREATE TABLE pig_dw.ods_xdy_*`。

**根因**：灵猫 PIG 的 docker 全栈被重建（`docker ps` 里所有 `linmo-*` / `deploy-mysql-1` 容器的 `Up` 时间都很短），`pig_dw` 下的 ODS 表随之清空。而入湖是**水位线增量**（`[上次最大日期-6, ∞)`）—— **只会补最近 7 天**。

**后果**：距上次推送**超过 7 天**的那段历史，会永久缺席 PIG 侧（本地 CSV 与 raw JSON 不受影响，数据没丢）。

**修复**：

```bash
cd "$C"
"$PY" push_to_linmo.py --full --dry-run   # 先看要推多少条
"$PY" push_to_linmo.py --full             # 全量重推（忽略水位线）
```

**校验**（直查 MySQL，注意容器名与列名）：

```bash
docker exec -i deploy-mysql-1 sh -c "MYSQL_PWD=root mysql -uroot --default-character-set=utf8mb4 -N -e \"
SELECT COUNT(*), MIN(date), MAX(date) FROM pig_dw.ods_xdy_account_trend;
SELECT COUNT(DISTINCT CONCAT(platform_id,'|',account_id,'|',date,'|',metric_key)) FROM pig_dw.ods_xdy_account_trend;
\""
```

判据：行数 == 本地 CSV 行数、去重键数 == 行数、日期范围覆盖全部落盘日期。

> **两个易错点（实测）**：MySQL 容器名是 **`deploy-mysql-1`**（不是 `linmo-mysql`）；ODS 表的日期列名是 **`date`**（不是 `dt`）。`--full` 不会打乱水位线（最大日期仍是今天）。

---

## 一次性准备（已做过，换机时才需要）

```bash
xdy-cli config init <YOUR_ACCESS_KEY>        # 写 ~/.xdy-cli.yaml
xdy-cli sync-skills --global                 # 同步官方技能文档
# 灵猫入湖契约（只需登记一次）。容器名先探测：docker ps → 找 mysql 那个（本机为 deploy-mysql-1）
MYSQL_CT=$(docker ps --format '{{.Names}}' | /usr/bin/grep -i mysql | head -1)
docker exec -i "$MYSQL_CT" sh -c \
  "MYSQL_PWD=root mysql -uroot --default-character-set=utf8mb4" < "$C/sql/xdy_contracts.sql"
```
