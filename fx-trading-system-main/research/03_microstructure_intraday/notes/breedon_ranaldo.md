# [Breedon & Ranaldo 2013] Intraday Patterns in FX Returns and Order Flow

- 深度层级: L4
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1111/jmcb.12032 ；SNB WP 2011-4 PDF（合法工作论文）
- 开放获取: SNB working paper；期刊 JMCB
- 本项目映射: `LOCAL-PAPER` 12 单元面板；`LOCAL-PORTFOLIO` 为项目扩展（固定 1/6 sleeves）
- 复制状态: extension_only（零售 bid/ask + 无授权 EBS 订单流）；精确 EBS 复制 fail_closed_missing_data

## 1. 经济机制

本币交易时段内，市场参与者（国际基金、进口商等）倾向于在**本地交易时段**用本币净买入外币，形成可预测的本币卖压。该订单流不是私有信息，却通过组合平衡/流动性渠道压低本币、推高外币；非本地时段则反向。因此出现“本地时段本币贬值、外地时段升值”的日内季节性。这是**无信息订单流 → 价格**的强证据，而非宏观 surprise。

## 2. 精确公式

SNB WP / 期刊叙述的核心检验（六对 × 本地时段）：

```text
# 六对：EURUSD, USDJPY, GBPUSD, EURJPY, USDCHF, AUDUSD
# 每个 unit = (pair, local_session, direction)
# direction：在“本币时段”做空本币 / 做多外币（按报价约定符号）

# 重叠时段（Europe 与 New York 重叠）：open-to-open
# 非重叠：open-to-close
# Europe 时钟：论文 Dublin；本项目用 Europe/London 作为等价 civil clock

R_unit,t = direction * log(P_exit / P_entry)
# 主结果：可成交侧；mid 仅作对照

# 简单策略列（Table 2 末列）：本地时段 short base，对手时段 long base
# 多数 pair 扣 spread 后不盈利；EURUSD 因点差极窄可仍为正（样本内）
```

本项目冻结 12 单元（`LOCAL_PAPER_UNITS`）：

```text
EURUSD Europe short / New York long
USDJPY Tokyo long / New York short
GBPUSD Europe short / New York long
EURJPY Europe short / Tokyo long
USDCHF Europe long / New York short
AUDUSD Sydney short / New York long

# Europe 重叠腿 exit = New York 08:00 open（open-to-open）
# 边界：时点当时或之前 ≤5s 最后 prevailing bid/ask
# 周六：普通 crosses 排除 00:00–24:00 UTC；JPY/AUD crosses 排除 00:00–18:00 UTC
# 假日：不预删；有合格边界报价则保留审计行
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 6 pairs：EUR/USD, USD/JPY, GBP/USD, EUR/JPY, USD/CHF, AUD/USD |
| 频率 | EBS 高频成交与最优 bid/offer |
| 样本起止 | 约 1997–2007（10 年） |
| 价格/订单流 | EBS 客户发起买卖笔数；辅以 BNP Paribas 地理客户流 |
| 排序与再平衡 | 无横截面排序；固定时段方向 |

## 4. 成本与可实现性

- 原文扣除：报告 mid/成交价路径，并**明确**多数简单 time-of-day 策略在计入 trading costs 后不盈利；**例外是 EUR/USD**。
- 迁移破坏点：
  1. Dukascopy spread ≫ EBS interdealer；
  2. 无 EBS 签名订单流 → 只能复制收益季节性，不能复制 order-flow 解释回归；
  3. 事后只保留 EURUSD 属于数据挖掘，禁止。
- midquote premium ≠ implementable net：项目主结果必须是 executable log return。

## 5. 识别与稳健性

- 主结果：本地时段本币贬值显著；order flow 同号；将 returns 对 order flow 回归后时段虚拟变量失去解释力。
- 子样本：EURUSD 效应跨年稳定性单独图示；其他 pair 更弱/不稳定。
- 控制：地理客户流与宏观资本流叙事一致但非因果证明。
- 已知失败：扣成本后多数 pair 转负；2010 后电子化与定盘改革可能改变形态。

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 6 对 tick bid/ask | 是 | Dukascopy 计划宇宙 | fail closed |
| 本地 open/close IANA 边界 | 是 | `session_window` | fail closed |
| EBS 签名订单流 | 机制复制需要 | 无授权 | 机制 only |
| 周六/假日规则 | 是 | 冻结 UTC 规则 | 不得 invent |
| 六对组合权重 | 否（论文无） | `LOCAL-PORTFOLIO` 扩展 | 必须标 extension |

## 7. 本项目映射

- registry：`LOCAL-PAPER`；扩展 `LOCAL-PORTFOLIO`（固定 1/6，缺任一 unit 则全日空，不 renormalize）
- 持有期：约半个交易日（open–close / open–open）
- 否决条件：
  1. bid/ask 后组合或多数 unit 净收益 ≤0 仍宣称可交易；
  2. 事后只报告 EURUSD；
  3. 把 `LOCAL-PORTFOLIO` 说成论文复制；
  4. EURJPY 表格符号矛盾时搜索反向规格（保留为 reciprocal/direction canary）；
  5. 1h bar 代替 5s 边界。
- reused-history：是；需冻结后新前向。

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Cornett et al. 1995；Ranaldo 2009 | 本地时段收益前驱 |
| mechanism | Evans & Lyons | 订单流价格影响 |
| related | Krohn et al. | 定盘窗 vs 本地时段分解 |
| boundary | 本项目 LOCAL-PORTFOLIO | 非论文组合 |

## 9. 精读问题

1. 期刊最终表对 EURJPY Europe/Tokyo 的符号是否与报价约定一致？如何设 canary？
2. Dublin vs London civil clock 在 DST 边界是否有任何交易日分歧？
3. 将 EBS 点差替换为 Dukascopy 历史 q50/q90 后，EURUSD 例外是否仍成立？
