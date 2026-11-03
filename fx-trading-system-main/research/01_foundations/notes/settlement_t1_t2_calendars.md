# FX Settlement T+1 / T+2 Calendars（研究级）

- 深度层级: L2
- 角色: data_contract / foundational
- DOI/URL: 综合 ISDA FX 市场惯例、CLS 结算实践、ECB/央行公开说明（非零售入门文）
- 开放获取: 部分官方公开
- 本项目映射: 远期/spot 日界、carry settlement 对齐、事件研究日历
- 复制状态: extension_only（完整 holiday calendar 需官方/vendor 表）

## 1. 经济机制

Spot FX 不是“成交即结算”。标准 **spot settlement** 决定资金与币种的实际交割日；forward/NDF 的 tenor 从 **spot settlement** 起算而非 trade date 机械加日历日。错误的 T+1/T+2 假设会把利率差分错一天、破坏 CIP 与 broker swap 对照。

## 2. 精确惯例（字段级）

```text
trade_date        = 成交日 (business day in relevant centers)
spot_date         = trade_date + settlement_lag  (business days, joint calendar)
value_date_spot   = spot_date
forward_value     = spot_date + tenor_business_rules
broken_date       = explicit calendar date (not integer tenor)

settlement_lag defaults (market convention, not universal law):
  most G10 pairs vs USD          → T+2
  USD/CAD, USD/TRY, USD/PHP, ... → T+1  (典型例外；以当前市场惯例表为准)
  some EM / local pairs          → local convention (may be T+1 or T+2)

business day = joint good business day in BOTH currency centers
              (+ often New York for USD legs in CLS context)
```

关键：

| 字段 | 含义 | 研究错误模式 |
|---|---|---|
| `settlement_lag` | trade→spot 营业日数 | 固定 2 天忽略 CAD 等 T+1 |
| `joint_calendar` | 双方货币中心同时营业 | 只用纽约假日 |
| `modified_following` | 月末/假日调整 | 把 forward 当自然日加 |
| `end_of_month` | 月末规则 | 月末 roll 错位 |
| `fixing_vs_value` | 定盘日 ≠ 交割日 | 用 fix 日当 settlement |

## 3. 日历构建清单

研究管线需要的最小日历合同：

1. **货币中心映射**：USD→New York；EUR→TARGET2；GBP→London；JPY→Tokyo；AUD→Sydney；CAD→Toronto；CHF→Zurich；NZD→Wellington；…  
2. **联合营业日**：`is_business(d, ccy1) AND is_business(d, ccy2)`；USD 腿常再要求 NY 营业。  
3. **假日源**：央行/交易所官方假日表，或已审计 vendor 表；禁止硬编码“固定周末”。  
4. **半日/特殊日**：部分中心有 half-day；定盘与结算规则可能不同——字段分开存。  
5. **时区**：settlement 是 **calendar date** 概念；与 WMR 16:00 London 的 **timestamp** 不同层。

```text
# pseudo
def spot_date(trade_date, pair, calendars, lag_table):
    lag = lag_table[pair]   # 1 or 2 typically
    d = trade_date
    steps = 0
    while steps < lag:
        d = next_calendar_day(d)
        if joint_business(d, pair, calendars):
            steps += 1
    return d
```

## 4. 与本项目的耦合

| 用途 | 需要 settlement 吗 | 缺失时 |
|---|---|---|
| Dukascopy 日界 PnL（零售） | 间接：日界 ≠ settlement | 可用账户日界，但不得声称 CLS value date |
| 学术 forward discount | 是 | fail closed 对 CIP 严格检验 |
| Broker swap vs CIP | 是（对齐 value date） | 只能做符号/量级探索 |
| 事件研究（fix 窗） | 否（用 timestamp） | N/A |
| 月末对冲流 | 半：日历日 + 定盘时刻 | 错配会污染月末 alpha |

## 5. T+1 迁移语境（研究备注）

- 证券 T+1 缩短 **不等于** 自动改写全部 FX spot 惯例。  
- 任何“全球 FX 已全面 T+1”断言必须有 **pair-level** 出处；本目录默认按 **pair convention table + joint calendar** 建模。  
- 复制论文时：记录论文样本期的惯例，不把 2024+ 惯例回灌到 2010 样本。

## 6. 禁止推断

- 禁止用“自然日 +2”替代营业日。  
- 禁止用单一国家假日表覆盖交叉盘。  
- 禁止把 **fixing date** 与 **value date** 混为同一字段。  
- 禁止在无 holiday 表时输出“精确 settlement-aligned carry”。

## 7. 本项目映射

- 配置建议字段：`settlement_lag_by_pair`, `calendar_ids`, `joint_centers`  
- 否决：无日历的“精确 CIP 日度套利”宣传  
- 与 `06_broker_costs`：swap 起息与 spot value date 对照清单

## 8. 精读问题

1. USD/CAD 在加拿大假日、美国营业日时，spot lag 如何数？  
2. 交叉盘 EUR/JPY 的 joint centers 是否必须包含 USD/NY？在何种合同下？  
3. 本项目若只做零售 swap 账本，哪些研究问题可以 **不** 建完整 T+2 引擎？
