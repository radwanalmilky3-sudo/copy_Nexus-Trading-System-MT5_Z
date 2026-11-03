# 研究用固定成本假设（Research Cost Assumptions）

日期：2026-08-03。  
状态：`software_fixture` / `cost_incomplete_research_only`。  
**不解锁** `formal_net_returns_ready`，**不批准**交易。

> 用途：在真实 IBKR 历史融资缺失时，用一套**显式、可复现、可压力测试**的固定/规则成本，
> 开启研究层净收益（research-net）计算。  
> 非用途：冒充目标账户真实历史成本。

## 1. 账户与产品假设

| 字段 | 取值 | 说明 |
|---|---|---|
| 目标 broker 品牌 | Interactive Brokers | 用户已定；法律实体未开户确认 |
| `broker_entity`（研究标签） | `IBKR_RESEARCH_ASSUMPTION_UNVERIFIED` | 故意非真实法律实体名，防升格 |
| 账户类型假设 | IBKR Pro / 外汇保证金 | 研究默认 |
| `account_currency` | `USD` | 研究默认 |
| 产品剖面 | `rolling_spot_margin` | 滚动 spot 保证金；不要求 forward 表 |
| 研究区间 | `[2016-01-01, 2026-01-01)` | 与行情宇宙一致 |
| 品种 | 正式 14 品种 | 与 intake 宇宙一致 |

## 2. 执行成本（点差 / 滑点 / 佣金）

这些是**研究默认值**，不是 IB 实时报价承诺。

### 2.1 点差（单边，pips）

Dukascopy bid/ask 可用于更精细回测；下表是**无 tick 时的固定回退**，并用于 1x 压力基准。

| 组别 | 品种 | 默认点差（pips） |
|---|---|---|
| G7 直盘 | EURUSD, USDJPY, GBPUSD, USDCHF, USDCAD, AUDUSD, NZDUSD | 0.8 |
| 欧系交叉 | EURGBP, EURJPY, GBPJPY | 1.2 |
| 商系交叉 | AUDJPY, CADJPY | 1.4 |
| 北欧 | USDNOK, USDSEK | 3.0 |

定义：1 pip = 对 JPY 计价对为 0.01，其余为 0.0001。

### 2.2 滑点

- 默认：`0.15` pips（单边，入场与出场各计一次）
- 压力：随成本倍数放大（见 §4）

### 2.3 佣金

- 默认：`USD 35 / 百万名义本金`（单边），近似 IB Pro 外汇量级
- 往返：开+平各计一次 → 约 `70 USD / 百万` 往返（未计点差/融资）

## 3. 隔夜融资（固定 research schedule）

真实 IB 历史 swap **不可得**（无账户 / 无商业数据）。采用：

```text
每日融资（账户币种 USD，名义 1 单位 base）≈
  notional_usd * (long_or_short_rate_annual) / 360
```

本假设表提供的是 **固定年化费率（annual rate）→ 换算为每日 `account_currency_per_unit`** 的
**时间不变** research schedule（不是利率路径合成）。

### 3.1 固定年化融资假设（研究用，粗校准）

符号：`long` = 持有 base 多头（买入 base/卖出 quote）隔夜年化；`short` 同理。  
单位：小数（0.01 = 1%/年）。符号以**支付为负、收取为正**（账户现金方向）。

| Symbol | long_annual | short_annual | 备注（极粗经济直觉，非 IB 官方） |
|---|---:|---:|---|
| EURUSD | -0.015 | +0.005 | 欧系低息 vs 美元 |
| GBPUSD | -0.010 | +0.000 | |
| USDJPY | +0.020 | -0.035 | 美元高息 vs 日元 |
| USDCHF | +0.012 | -0.025 | |
| AUDUSD | -0.005 | -0.005 | 澳息阶段性变化大，固定值误差大 |
| NZDUSD | -0.008 | -0.002 | |
| USDCAD | +0.005 | -0.015 | |
| EURGBP | -0.008 | -0.002 | |
| EURJPY | +0.010 | -0.025 | |
| GBPJPY | +0.012 | -0.028 | |
| AUDJPY | +0.015 | -0.030 | |
| CADJPY | +0.012 | -0.028 | |
| USDNOK | +0.005 | -0.020 | 北欧点差大，融资亦更不确定 |
| USDSEK | +0.005 | -0.020 | |

> 这些数字**不是**预测，也**不是** IB 费率。它们只为让慢周期账本在研究层“有一个显式融资项”，
> 并支持 1x/1.5x/2x 压力。任何基于它们的净收益只能标 `research-net`。

### 3.2 日计数与三倍日

| 字段 | 取值 |
|---|---|
| `day_count` | `actual_360` |
| `unit` | `account_currency_per_unit` |
| `triple_swap_weekday` | `wednesday`（研究假设；实体未确认） |
| 普通日 `rollover_multiplier` | `1` |
| 三倍日 `rollover_multiplier` | `3` |
| 节假日调整 | **不做**（研究简化；真实 IB 会有） |

每日融资金额（研究公式）：

```text
daily_long  = long_annual  / 360   # 乘以名义 base 数量与 FX 换算后得到 USD
daily_short = short_annual / 360
三倍日：再乘 rollover_multiplier=3
```

落盘 CSV 中 `long_financing` / `short_financing` 已是 **每日、每 1 base 单位、USD** 的
`account_currency_per_unit` 值（未乘仓位），`rollover_multiplier` 另列。

### 3.3 时间结构

- 为满足覆盖审计的月度密度，对每个品种、每个日历日写一行
  `effective_time = 当日 22:00:00Z`（纽约冬令 17:00 近似；研究简化，不做 DST 逐日切换）
- `available_time = effective_time`（fixture 无信息时滞）
- `quote_quality = software_fixture`
- `source = research_fixed_cost_assumptions_v1`
- `provenance = docs/RESEARCH_FIXED_COST_ASSUMPTIONS_ZH.md`
- `version = research_fixed_cost_v1`

## 4. 成本压力倍数

与现有因子管线对齐：

| 倍数 | 含义 |
|---|---|
| 1.0x | 上表默认点差/滑点/佣金/融资 |
| 1.5x | 全部执行与融资成本 ×1.5 |
| 2.0x | 全部 ×2.0 |

晋升研究候选时：**至少在 1.5x 压力下仍成立**，才进入“值得继续”的讨论；  
即使如此也**不是**交易批准。

## 5. 报告口径（强制）

任何使用本假设的回测/筛选，必须同时给出三层：

```text
gross            : 未扣或仅扣最小执行摩擦前的收益（文档中定义清楚）
research-net     : 应用本假设表后的净收益（software_fixture）
formal-net       : N/A   （cost_incomplete_research_only）
```

机器字段保持：

```text
quote_quality              = software_fixture
cost_contract_verdict      = cost_incomplete_research_only
formal_net_returns_ready   = false
trading_approval           = false
return_labels_opened       = false   # 除非另有用户单次授权
```

## 6. 产物路径

| 路径 | 内容 |
|---|---|
| `docs/RESEARCH_FIXED_COST_ASSUMPTIONS_ZH.md` | 本文 |
| `configs/research_fixed_costs.yaml` | 机读假设 |
| `data/research_costs/broker_financing_research_fixed_v1.csv` | 融资 schedule（fixture） |
| `data/research_costs/broker_financing_research_fixed_v1.manifest.json` | 字节 manifest |
| `scripts/build_research_fixed_cost_schedule.py` | 生成器 |
| `configs/long_horizon_dukascopy_research_costs.yaml` | 挂接新 14 库 + 本成本的研究配置 |

## 7. 明确不做的事

1. 不把本表标成 `historical_target_broker_schedule`
2. 不声称 IB 官方或可实盘
3. 不因“research-net 好看”自动打开交易或 formal-net
4. 不用当前网页费率回填 2016–2020 后假装是历史
5. 不在未授权时打开收益标签

## 8. 何时废弃本表

出现以下任一，本表降级为对照，不再作为主 research-net 来源：

- 购入商业历史 swap/forward，并通过 cost-coverage-audit 的历史门；或
- 持有 IB 账户多年真实持仓并导出 Flex Query 融资流水。
