---
name: undervalued-stock-daily-screen
description: 用 westock CLI 做「A股严重低估个股」的每日筛选与日报闭环 —— 多路条件筛选 → 盈利趋势核验 → 自身历史估值分位 → 交叉验证（A/H 溢价 / 港股前瞻 / 政策映射）→ 分档结论与日报。当用户说「帮我找出当天严重低估的个股」「低估股筛选」「按低PE高股息选一批」「这个池子里哪些是真低估」，或定时自动化每天跑低估筛选日报时使用。
agent_created: true
---

# 严重低估个股每日筛选

**目标**：产出一份「可追溯、带评级、能经得起 3 年后回看」的低估个股日报。不是「低 PE 榜」，而是**剔除了伪低估之后的真低估名单 + 验证窗口**。

## 核心原则

1. **低 PE ≠ 低估**。必须过四道关：估值低 → 盈利真实 → 自身历史分位低 → 交叉验证。
2. **绝对便宜 ≠ 相对便宜**。一只股 PE 6 倍可能是被错杀，也可能是估值中枢下移。**这是最容易漏掉的一维**。
3. **每个数字标注来源与时点**；缺失标 `[MISSING]`，陈旧标 `[STALE]`，媒体来源标 `[媒体口径·待核]`，推断标 `[假设]`。
4. **休市日不虚构价格**。A股休市时明确写出「当天无新价格」，用最近有效收盘 + 假期信息面做重估。
5. **报告末尾统一声明**：本报告仅供研究参考，不构成个人投资建议。
6. **硬门槛必须逐项过**。入池前把 PE / 股息率 / 分位三个数逐一对照定义，**不要凭"低估值 + 盈利正增长"的印象入池**。反例：深圳燃气曾长期被列 B 级，复核后发现 PE 12.24（>12）且股息 2.43%（<3%），**根本未过硬门槛**。

## 「严重低估」操作定义（固定，勿逐日漂移）

```
真低估 = PE_TTM < 12
        AND PE_TTMPct5Y < 5%        ← 相对自身 5 年最便宜
        AND PB_LFPct5Y < 35%
        AND 2026H1 归母同比 > 0
        AND 2026Q2 扣非单季同比 > 0   ← 剔除一次性损益
```

分档输出：**S 级**（分位 <1% + 盈利正增长 + **扣非单季 ≥ 归母单季**）｜**A 级**（分位 <1% 但扣非单季 < 归母单季（含非经常增益），或盈利可持续性待验证，如券商集群、保险投资收益驱动）｜**B 级**（分位 1%~10% + 逐季改善）｜**观察**（低估值+盈利下行）｜**剔除**（价值陷阱）。

> 「扣非单季 ≥ 归母单季」的判读标准（2026-10-15 固化，勿再含糊）：**逐只比较 `NPParentCompanyCutYOY_Q` 与 `NPParentCompanyYOY_Q`**。前者 ≥ 后者 ⇒ 去年同期有高非经常基数、经营端实际更强 ⇒ S 级；前者 < 后者 ⇒ 本期含非经常增益 ⇒ 降 A 级。

**第二道并列门槛（2026-10-15 新增，必做）**：S/A/B 级各票都要标**股息率（`DividendRatioTTM`）**，并把「严定义 + 股息率 ≥3%」单列一档「严格优选」。原因：严定义只看估值分位与盈利质量，会选出股息 1~2% 的标的；而股息 ≥3% 是本方法长期偏好的现金回报门槛。两张表并列，避免档次混淆。

## 执行步骤

### 0. 环境与前提（每次必做）

```bash
export PATH="$HOME/.local/bin:$PATH"   # westock CLI 安装于 ~/.local/bin
westock trade-calendar --start <起> --end <止>          # A股
westock trade-calendar --market hk --start <起> --end <止>  # 港股
```

**为什么必做**：A股与港股假期安排不同。必须先确认「今天有没有新价格」、港股是否在交易（港股是 A股复市的开盘前瞻）。**不要凭印象判断交易日。**

### 1. 确认数据时点

```bash
westock quote sh000001        # 看 time 字段 → 确认 A股最新有效收盘日
westock quote hkHSI           # 港股 time 字段 + prev_close
```

用 `westock quote <code> --date <YYYY-MM-DD>` 可取指定日收盘（非交易日会回退到最近交易日）。

**⚠️⚠️ 关于 `screen condition --date`（2026-10-14 实测推翻旧结论，务必读）**

`screen condition` 的 `--date <交易日>` **只对「估值分位列」生效**（`PE_TTMPct5Y` / `PB_LFPct5Y` / `PE_TTM` / `ROE` 等会随日期变化）；
**「价格列」(`ClosePrice` / `ChangePCT`) 完全不回溯 —— 它永远是运行时刻的实时快照，与 `--date` 无关。**

证据（东方精工 `sz002611`，用 `quote --date` 逐日对照）：

| 日期 | 实际收盘（`quote --date`） | screen 返回的 ClosePrice/ChangePCT |
|---|---|---|
| 2026-10-09 | 13.66 (+0.37%) | 13.21 / -0.97 |
| 2026-10-12 | 13.41 (-1.83%) | 13.21 / -0.97 |
| 2026-10-13 | 13.34 (-0.52%) | 13.21 / -0.97 |

三个交易日返回**完全相同**的价格 ⇒ 该列与日期无关。

**正确做法（必须遵守）**：
1. **价格一律用 `westock quote <code> --date <交易日>` 取**，绝不用 screen 的价格列充当「收盘截面」。
2. screen 只用来取**估值分位与估值倍数**。
3. **不要在交易日运行时宣称「已用 `--date` 拿到完整收盘截面」** —— 那是假的。休市日运行时实时价恰好等于最近收盘，所以休市日无害；交易日运行时会**系统性把盘中价写成收盘价**。

```bash
westock screen condition --preset LowPE --market hs --limit 5 --date 2026-10-08   # 仅估值列有意义
westock quote sh600036,sh601318 --date 2026-10-13                                 # 价格必须这样取
```

**⚠️ 开市日盘中运行的强制口径声明**：若运行时刻落在交易时段（尤其开盘 30 分钟内），`screen` / `quote` 返回的是**盘中快照而非收盘价**。此时必须在报告「前提」一节显式写明：① 运行时刻距开盘多少分钟；② 全部结论基于盘中定价；③ **买入决策前须以当日收盘重算**。绝不可把盘中价当作收盘价写成事实。

### 2. 多路筛选（至少四路，交叉验证）

```bash
# 路径一：LowPE 预设
westock screen condition --preset LowPE --market hs --limit 25

# 路径二：低PE × 高ROE × 低PB × 高股息
westock screen condition --expression "intersect([PE_TTM > 0, PE_TTM < 12, ROETTM >= 12, PB < 1.5, DividendRatioTTM >= 3])" --limit 30 --orderby DividendRatioTTM --desc

# 路径三：破净 × 股息 ≥4% × ROE ≥10%
westock screen condition --expression "intersect([PE_TTM > 0, PB < 1, DividendRatioTTM >= 4, ROETTM >= 10])" --limit 30 --orderby DividendRatioTTM --desc

# 路径四（关键）：自身历史估值低分位 × 低估值 × 高ROE
westock screen condition --expression "intersect([PE_TTM > 0, PE_TTM < 12, PB < 1.2, ROETTM >= 12, PE_TTMPct5Y < 30, PB_LFPct5Y < 30])" --limit 30 --orderby DividendRatioTTM --desc

# 路径五（最高优先级，增量的主要来源）：按 PE 历史分位【升序】拉全市场
# ⚠️ 不要只按股息率排序 —— 那会形成路径依赖，券商/消费品/制造业的极端低分位标的永远进不了视野
westock screen condition --expression "intersect([PE_TTM > 0, PE_TTM < 15, ROETTM >= 8, DividendRatioTTM >= 2.5, PE_TTMPct5Y >= 0, PB_LFPct5Y >= 0])" --limit 40 --orderby PE_TTMPct5Y --asc
# 把 PE_TTMPct5Y >= 0 / PB_LFPct5Y >= 0 写进表达式，只是为了「逼出这两列」，不是过滤条件

# 路径六：只要分位列、按股息降序（用于给某个已知池子补分位）
westock screen condition --expression "intersect([PE_TTM > 0, PE_TTM < 12, DividendRatioTTM >= 3, PE_TTMPct5Y >= 0, PB_LFPct5Y >= 0])" --limit 80 --orderby DividendRatioTTM --desc

# 辅助：策略选股
westock screen strategy --type high_dividend,pb_roe,profit_preannounce --limit 20
westock screen strategy --list        # 查本渠道可用策略
```

> ⚠️ **`--type` 多个策略逗号分隔时，只要有一个不可用就整体报错**。逐个跑更稳。

### 3. ⚠️ 字段名陷阱（最容易浪费时间的地方）

**沪深与港股的字段名不同**，用错**不会提示"字段不存在"，而是返回 `[code=1620053001] error_type=2 suggest=3 msg=service error`**。看到这个错先怀疑字段名，不要怀疑服务故障。

| 含义 | 沪深(HS) | 港股(HK) |
|---|---|---|
| 市盈率 TTM | `PE_TTM` | `PeTTM` |
| 市净率 | `PB` | `PbLF` |
| 股息率 TTM | `DividendRatioTTM` | `DivTTM` |
| 总市值 | `TotalMV` | `TotalMV` |
| PE 5 年分位 | `PE_TTMPct5Y` | `Pe_TTMPct5Y` |
| PB 5 年分位 | `PB_LFPct5Y` | `Pb_LFPct5Y` |
| 多期涨跌 | `Chg5D/10D/20D/60D/ChgYtd` | 同 |

**其他字段**：`ROETTM`、`PE_Fwd`、`PE_Lyr`、`PS_TTM`、`TurnoverRate`、`ClosePrice`、`ChangePCT`。完整清单见 finance-data 插件的 `skills/westock-tool/references/fields-guide.md`。

### 4. 盈利趋势核验（全候选必过，不可抽查）

低 PE 有三种来源：真低估 / 一次性收益 / **盈利下滑**。第三步只能剔除前两者。

```bash
westock finance <code1>,<code2>,... --type income --limit 1
```

**必看列**（宽表，**不要用 `cut` 截断，列会错位**；建议用 python 解析 markdown 表按列名取值）：

| 列 | 含义 |
|---|---|
| `NPParentCompanyOwners` | 归母净利润（本期累计） |
| `NPParentCompanyYOY` | 归母同比（H1/Q1 累计） |
| `NPParentCompanyYOY_Q` | **归母单季同比**（关键，看趋势是否在恶化/收敛） |
| `NPParentCompanyCutYOY_Q` | **扣非单季同比**（识别 Q2 是否靠非经常损益） |
| `NPDeductNonRecurringPL` | 扣非净利润 |
| `ROETTM` | ROE(TTM) |
| `TORGrowRate` / `TORGrowRate_Q` | 营收同比 |

**判读规则**：
- 归母单季为正、**扣非单季也为正** → 盈利真实（最干净）
- 归母单季为正、**扣非单季为负** → Q2 靠非经常损益撑，降级为观察
- 扣非单季增速 **> 归母单季增速** → 去年同期有高非经常基数，经营端实际更强
- **PE(前瞻) > PE(TTM)** → 市场用盈利预测下行主动压估值，与净利下滑互相印证
- **PE(前瞻) < PE(TTM)** → 市场定价盈利继续增长

### 5. 自身历史估值分位（本方法的核心增量）

上一步的 `PE_TTMPct5Y` / `PB_LFPct5Y` 是**区分「被错杀」与「估值中枢下移」的唯一工具**。

- 分位 **< 10%** + 盈利正增长 → 真低估（S 级）
- 分位 **< 10%** + 盈利下滑 → **分位陷阱**，剔除（典型：PE 分位 2.94%/PB 分位 0.24% 但 H1 净利 -62%）
- 分位 **> 50%** 但 PE 绝对低 → **「不贵，但不便宜」**，降级为持有/观察

> 银行股尤其要注意：城商行/农商行普遍 PE 6 倍左右，但分位可差 70 个百分点（0.32% vs 94.76%）。**不分位，就会把"回到自己的历史常态"误判成"被错杀"。**

### 6. 交叉验证（三选二以上）

**6.1 A/H 溢价**（同一家公司、同一盈利，价格互证）

```bash
westock quote fxHKDCNY                      # 取汇率
westock quote <A股code>,<H股code> --date <YYYY-MM-DD>
```

计算：`H折CNY = H价 × 汇率`，`A/H溢价 = A价 / H折CNY - 1`。**A 折价（负溢价）是全池最稀缺信号**；A 溢价 > 30% 时优先看 H 股。

**6.2 港股假期定价**（A股休市期间港股在交易 = 复市开盘前瞻）

逐日取恒指与目标板块的港股收盘，算**累计跌幅**而非只看单日。若假期跌幅在收窄、或从低点回补，则「A股补跌」判断要弱化。

**6.3 政策面 → 个股催化映射**：只写「为什么是现在」。**政策是"能否修复的条件"，不是"已修复的事实"** —— 盈利下滑若发生在政策落地之前，必须等财报才能验证。

```bash
westock news list sh000001 --limit 15 --type 2   # 市场资讯
westock news list hkHSI --limit 15 --type 2
westock news list <code> --limit 8 --type 3      # 公告+研报+新闻
```

**6.4 前瞻信号**：中概股（纳斯达克中国金龙指数）是外资给中国资产报价的窗口；美股/日经/美债 10Y 是外部约束。**历史节后统计必须配"反例年份"**（如 2018 年美债飙升导致节后大幅补跌，降准也未能止住）。

### 7. 催化剂与验证窗口

```bash
westock disclosure <code1>,<code2>,...              # 三季报/年报预约披露日
westock earnings <code1>,<code2>,... --kind forecast # 业绩预告（期数）
westock screen event --type earnings_forecast --limit 25   # 全市场近一月发预告的
westock screen event --type earnings_schedule --limit 25   # 一月内将披露的
```

**要点**：明确列出「结论的兑现日」。若核心池内无一只发预告，必须写明「三季报是唯一验证窗口，无前瞻信号」。

### 8. 分档成文

固定结构（顺序不要乱）：

1. **前提**：当天有没有新价格，数据基准是哪一天
2. **本轮方法增量**（相对上一份报告改了什么，为什么改）
3. **结论速览**：① 真低估 ② 低估值但盈利下行→观察 ③ 价值陷阱→剔除
4. **逐票说明**：新增入池/剔除的理由，含扣非单季
5. **交叉验证**：A/H 溢价 / 港股前瞻 / 政策映射 / 前瞻信号与风险
6. **伪低估清单**：一次性收益、周期顶部、PE 失真
7. **原始筛选明细**（含分位列，便于复核）
8. **更正与数据纪律**（若上一份报告有错，显式更正）
9. **催化剂日历**
10. **方法论备注 + 免责声明**

## 常用剔除逻辑（复用）

| 类型 | 特征 | 例 |
|---|---|---|
| 一次性收益 | ROE 异常高（>35%）、PB 仍高、主业弱 | 破产重整、出售资产 |
| 周期顶部 | 低 PE + 极高 ROE（>25%），且处在商品价格高位 | 电解铝、铜、存储、创新药 |
| PE 失真 | 保险/券商 PE 被投资收益压低 | 属行业常态，非个股低估 |
| **盈利下滑陷阱** | **低 PE + 归母同比大幅为负** | 本方法最主要剔除对象 |
| **分位陷阱** | **分位极低 + 盈利崩塌** | 看分位不看盈利就会踩 |
| **反向分位陷阱** | **PE 分位极高 + PB 分位极低（同一只股）** | PE 5.73 看似便宜，但 PE 分位 99.60% / PB 分位 1.59% → 盈利比价格跌得更快，H1 -24%/扣非单季 -51%（标本：中国建筑） |
| **高股息陷阱** | **股息率极高（>8%）+ 利润即将消失** | 索菲亚 股息 10.68% 但 H1 **-80.61%** —— 高股息来自崩溃前的利润 |

## 工具速查

```bash
westock profile <code>            # 核验主营业务（禁止凭印象描述公司）
westock dividend <code> --years 3 # 分红历史（无 --limit；注意 TTM 股息率口径可能只取最近一期年报）
westock quote <code>[,<code>]     # 实时/指定日行情
westock finance <code> --type income|balance|cashflow --limit N --fields core|all
westock screen condition|strategy|event|label|ranking
westock news list <code> --type 0公告|1研报|2新闻|3全部
```

## 已知坑

1. **`buffet` / `graham` 大师策略可能在本渠道不可用**（`--list` 里能看到但调用被拦截）→ 逐个跑，被拦截就换 `pb_roe` / `high_dividend`。
2. **`screen condition --date` 只改估值列，不改价格列**（详见「第 1 步 · 确认数据时点」的红框）。`--date` 传**非交易日**会报 service error。**价格必须用 `quote --date` 取。**
2b. **`quote` 不支持 `--limit`** —— 加了会静默返回空表（无 header），误判为「接口挂了」。直接 `westock quote <codes>` 即可。
2c. **`quote --date` 的口径是可靠的**：返回该交易日的收盘价 + 当日涨跌幅 + 当日成交额（已验证 `sh000001` 10/12 成交额 7149.10 亿、10/13 7793.02 亿，与逐日实际完全一致）。**核对 screen 与 quote 冲突时，以 `quote --date` 为准。**
3. **`finance` 频率限制很严** → 每次最多 **8 只**（逗号分隔），批次间隔 **`sleep 30`**，否则整批返回 `[LOCAL_RATE_LIMITED]`（表现为 `!! NO HEADER` + "未找到财报数据"）。被限流后等 30s 重跑即可，不必换方式。**`westock disclosure` 同样有本地限流**，连续多批会整体返回 `[LOCAL_RATE_LIMITED]`，需穿插 sleep。
3b. **`finance` 返回的 `[Batch] 状态: success | 总数: 1` 是假的** —— 传 8 个代码也显示「总数: 1」，但表格里 8 行数据都在。不要因为看到「总数: 1」就以为只取到一只而重跑。
3c. **`finance` 宽表解析脚本（已固化，直接复用）**：按列名取值，兼容「多代码首列 `code`」与「单代码无 `code` 列」两种表头；只用 `NPParentCompanyYOY` / `NPParentCompanyYOY_Q` / `NPParentCompanyCutYOY_Q` / `ROETTM` / `TORGrowRate` 五列即可判读。

```python
#!/usr/bin/env python3
"""python3 wcheck.py <markdown_file>"""
import sys, re
COLS=["NPParentCompanyYOY","NPParentCompanyYOY_Q","NPParentCompanyCutYOY_Q","ROETTM","ORGrowRate"]
hdr=None; rows=[]
for line in open(sys.argv[1], encoding="utf-8"):
    if not line.startswith("|"): continue
    cells=[c.strip() for c in line.strip().strip("|").split("|")]
    if all(re.fullmatch(r"-{2,}", c or "-") for c in cells): continue
    if hdr is None: hdr=cells; continue
    rows.append(dict(zip(hdr,cells)))
for r in rows:
    print(r.get("code","?"), " | ".join(f"{c}={r.get(c,'N/A')}" for c in COLS if c in r))
```
4. **`finance` 宽表不能用 `cut` 截断**（列错位），用 python 按列名解析。多代码时首列是 `code`，单代码时没有 `code` 列 —— 解析脚本要两种都兼容（判 `hdr[0]=='code'`）。
5. **港股/A股字段名不同**（见第 3 步），**用错只报 service error**。
6. **港股盘中早期数据（开盘 10 分钟内）不作结论依据**，必须用完整交易日收盘。
7. **同一文件不要在一次消息里并发多个 Edit**（实测会丢），逐个改并回读校验。
8. **`screen condition` 不支持 `--fields`**（会报 `unknown flag`）→ 想让某列出现，就把它以 `XX >= 0` 的形式写进 `intersect([...])`。
9. **`westock quote` 取不到美债收益率**（`usTNX` / `usTN10Y` 均返回"未找到行情数据"）。美元指数同理。→ 美债 10Y 标 `[MISSING]`，改用**美联储会议纪要内容**作为利率风险的替代信号，不要静默跳过该风险项。
10. **`westock disclosure` 个别行返回 Base64 编码的 `disclosureDesc`**（实测 `sh688187`）。发现中文描述是乱码串时先试 `base64 -d` 解码，不要当成数据缺失。
11. **可用的外围/中概代码**：`usIXIC`（纳指）、`usDJI`、`jpN225`、`hkHSI`、`hkHSCEI`（国企指数）、`hkHSTECH`（恒生科技）、`usHXC`（纳斯达克中国金龙指数）、`fxHKDCNY`。这些都可以 `--date` 逐日取，用来拼假期的完整序列。
