# Broker-neutral 外汇策略/因子挖掘工具范围

日期：2026-07-17。

## 产品目标

本项目的核心产品是可复现、可审计的外汇策略与因子挖掘工具，不是某一家 broker 的开户、
合规或实盘接入系统。核心研究输入是市场数据、当时可得的外部数据、因子定义、标签合同、
统计检验和用户配置的通用成本压力情景。broker 法律实体、监管辖区、账户层级和 API 凭据
不得成为因子发现的前置条件。

工具仍区分“发现信号”和“证明净收益”。这是证据等级的区别，不是要求用户先选择 broker：

1. 因子发现可以使用经完整性验证的 EURUSD/GBPUSD bid/ask 历史，输出 IC、方向、稳定性、
   换手、非重叠 OOS 和多重检验结果。
2. 策略构造使用观测 bid/ask，加上配置化的 spread、slippage、commission 和 financing 压力
   网格，判断结果是否只在零成本下成立。
3. 只有需要声称“某个真实账户可实现的净收益”时，才接入可选的 broker 成本/成交适配器。
   这一步不反向阻止工具报告一个 `factor_candidate_requires_cost_validation` 因子候选。

## 三层边界

| 层 | 核心输入 | 可以输出 | 不可以声称 |
|---|---|---|---|
| 因子发现层 | bid/ask 行情、PIT 特征、标签、purged OOS、FDR | 因子 IC、稳定性、候选/拒绝 | 最终净盈利、可实盘 |
| 通用成本压力层 | 观测点差、配置化滑点/佣金/融资情景 | 成本敏感性、robust/not robust | 等于某个具体账户账单 |
| 可选执行层 | broker adapter、账户实际费用和成交回报 | 账户级 forward/paper 证据 | 保证未来盈利 |

OANDA US/SG 只属于第三层的未来插件。现有 OANDA 公开融资归档保持离线、许可未确认、
research-only，不进入核心 gate，也不要求继续补充。

## 机器状态

短周期多因子管线应分别输出：

- `factor_discovery_ready`：行情来源、bid/ask、历史长度、覆盖率、共同时间网格、manifest 和
  hash 足以进行严谨因子发现；不检查法律实体。
- `historical_cost_validation_ready`：额外具有满足合同的历史成本输入。它只控制净收益升级，
  不控制能否发现因子。
- `factor_candidate_requires_cost_validation`：统计门和通用成本压力门通过，但尚不能声称账户级
  净收益。
- `research_candidate_requires_new_holdout` / `research_candidate_requires_paper`：只有历史成本
  证据也通过后才允许进入的更高等级。

旧字段 `broker_ready` 暂作为 `historical_cost_validation_ready` 的兼容别名保留，新代码和报告
不得再用它表达“因子是否可挖掘”。

## EURUSD/GBPUSD 当前可做的研究

两库足以推进以下工作，无需等待 14 库或选定 broker：

- 单品种时间序列因子：趋势、反转、波动率、价格路径、区间位置、跳空、时段与流动性状态；
- 两品种共同状态：EURUSD 与 GBPUSD 的相关性、相对动量、残差、USD 共同冲击和分化；
- 日内事件/时段效应：基于原始 tick 的 fixing、纽约换日、伦敦/纽约重叠等边界；
- 21/42/63 日方向标签的软件与统计管线验证；
- 真实 bid/ask 入退场与 1.0x/1.5x/2.0x 通用成本压力。

两品种不适合冒充宽横截面证据。需要跨十余货币对排序、货币图冗余残差或跨货币普适性时，
再使用后续到达的更大 universe。工具应把“研究 universe 不足”记录为候选适用范围，而不是
把它误写成 broker 问题。

现已增加 `research_mode=time_series_panel` 和两品种配置
`configs/long_horizon_two_pair_time_series.yaml`。该模式按品种内时间序列 rank 计算方向证据，
再按共同日期聚合和 block bootstrap；`currency_graph`、`cross_sectional`、`value_trend` 家族在
检验前 outcome-blind 排除。执行脚本默认拒绝打开历史结果，必须由用户显式传入
`--open-return-labels`；因此本轮只完成软件与配置验证，没有运行真实收益筛选。

## 工作流所有权

| 工作流 | 当前负责人 | 文档 | 结果隔离 |
|---|---|---|---|
| 第一层：纯价格因子挖掘 | 用户指定的另一 agent | `docs/PRICE_ONLY_FACTOR_MINING_AGENT_BRIEF_ZH.md` | `outputs/price_only_round1_20260717/` |
| 第二层：结构化外部数据因子层 | 当前主 agent | `docs/STRUCTURED_EXTERNAL_FACTOR_LAYER_PLAN_ZH.md` | 不打开收益标签 |

两条工作流不得共享未登记的结果反馈。第二层不能根据第一层结果选择外部变量；第一层也不能在
看到失败结果后临时引入第二层数据。

## 当前安全状态

本次范围调整只改研究门和产品边界，不运行新的真实收益试验，不增加 outcome trial：

```text
approved_strategy: false
verdict: no approved strategy
return_labels_opened: false
factor_outcome_evaluations_added: 0
formal_net_returns_ready: false
trading_approval: false
```
