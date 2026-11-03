# [Melvin & Prins 2015] Equity Hedging and Exchange Rates at the London 4pm Fix

- 深度层级: L3
- 引用链角色: boundary
- DOI/URL: https://doi.org/10.1016/j.finmar.2014.11.001 ；ECB 研讨会稿 PDF
- 开放获取: 研讨会稿；期刊 J. Financial Markets
- 本项目映射: WMR **月末交互项**（单一预注册放大），非独立方向因子
- 复制状态: fail_closed_missing_data（缺 PIT 股票收益与对冲映射时只能叫月末放大）

## 1. 经济机制

国际权益组合经理按基准汇率估值并对冲 FX 风险。WMR 伦敦 16:00 定盘是组合估值的主基准，对冲交易在定盘附近集中。月内权益上涨 → 外币权益敞口市值上升 → 月末需卖出外币/买入本币（或相反，取决于组合 base）以恢复对冲比率。因此**过去一个月权益收益**应能预测**月末定盘前**的汇率方向。这是“对冲渠道的汇率调整”，不是宏观 surprise，也不是无条件 FIX-W。

## 2. 精确公式

```text
# 识别时刻：月末 WMR 4pm fix 附近
# 方向识别：月内/月初至定盘前的国际权益收益

HedgePressure_{c,t} = f( EquityReturn_{foreign,c,t}^{month-to-date} )

# 预测式（概念）：
FX_move_into_fix_{c,t} = a + b * EquityReturn_{c,t}^{MTD} + controls + e

# 符号：权益升值 → 定盘前对应货币贬值（对冲卖出外币）
# 本项目冻结：仅增加 is_actual_wmr_month_end 交互，不估计 b 的权益通道
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 主要货币 vs 对冲相关权益市场 |
| 频率 | 日/日内，聚焦月末定盘窗 |
| 样本 | 研讨会/期刊版本覆盖 2000s–2010s（以正式刊文为准） |
| 关键数据 | 权益指数收益 + FX 定盘邻域价格 |
| 识别 | 4pm fix 制度性聚合成交时点 |

## 4. 成本与可实现性

- 原文：检验对冲渠道是否存在，不是零售可交易 alpha 产品说明书。
- 迁移：即使月末放大在 mid 上显著，零售账户在 WMR 五分钟窗的点差/滑点常尖峰。
- 无 PIT 权益收益与明确对冲映射时，**禁止**声称复制因果通道。

## 5. 识别与稳健性

- 主结果：月内权益升值预测定盘前货币贬值。
- 制度识别依赖“对冲交易挤在 4pm”的市场结构。
- 衰减风险：定盘改革、被动份额变化、对冲比率实务变化。

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 实际 WMR 月末日 | 是 | `actual_wmr_month_end` | fail closed |
| PIT 多国权益收益 | 因果复制需要 | 无 | 仅月末哑变量交互 |
| 对冲比率/基金流 | 理想 | 无 | 不声称渠道复制 |
| tick 定盘邻域 | 是 | Dukascopy | 1h 否决 |

## 7. 本项目映射

- 实验：WMR month-end interaction on FIX-W / fix-window family
- 持有期：定盘窗或 FIX-W 同日
- 否决：把月末哑变量收益解释为“已复制 Melvin–Prins 对冲渠道”；或在搜索族外临时加权益信号
- reused-history：是

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| related | Krohn et al. | 定盘反转库存解释 |
| boundary | LSEG WMR methodology | 定盘定义 |
| related | Evans & Lyons | 订单流中介 |

## 9. 精读问题

1. 权益收益的国家映射与报价货币如何对齐 G9？
2. 月末定义是日历月末还是实际 WMR 发布日？
3. 定盘改革后窗口从 1 分钟扩到 5 分钟是否削弱聚合成交？
