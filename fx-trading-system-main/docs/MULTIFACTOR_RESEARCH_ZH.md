# 外汇多因子挖掘系统

## 研究目标

系统预测的不是下一根 K 线方向，而是：从下一根 bar 开盘入场后，在最长 120 小时内，
`0.70 ATR` 止盈是否先于 `1.10 ATR` 止损触发。目标/止损比为 0.636，符合低盈亏比约束。

普通 timeout 不等同于完整止损。模型用训练期校准段中非 target 事件的实际平均 R 估计期望值：

```text
Expected net R
= P(target) × target_R
+ (1 - P(target)) × mean_non_target_R
- pair_specific_spread_slippage_commission_R
- extra_cost_buffer_R
```

只有期望净 R 不低于 0.03，并且 long/short 概率差达到门槛时才产生信号。

## 因子库

当前实现 60+ 个 close-of-bar 因子：

- 动量：1/3/6/12/24 bar 收益。
- 反转：10/20/60 bar z-score、RSI。
- 趋势：多组 EMA spread、12/24 bar 效率。
- 波动：多周期 realized volatility、波动比、ATR 百分比、range expansion。
- 结构：通道位置、实体、上下影线平衡。
- 分布与状态：偏度、峰度、收益自相关。
- 第二轮路径与横截面：趋势 t-stat、方差比、符号熵、半方差不对称、Parkinson 波动率、
  K 线收盘位置、跳空、前通道突破距离、横截面动量和货币强度离散度。
- 日历：UTC 小时与星期的周期编码。
- 多货币图：base/quote currency strength、货币图拟合收益和 pair residual。

多货币图通过货币对—币种 incidence matrix 的伪逆分解 `pair return ≈ base strength -
quote strength`。没有闭环的树状货币对集合不能识别 residual，代码会自动禁用该因子；当前研究
加入 EURGBP、EURJPY、GBPJPY、AUDJPY、CADJPY 等交叉盘，使图具有冗余闭环。

## 防止未来泄漏

1. 因子只使用当前已收盘及更早的 bar，最早在下一根 bar 开盘成交。
2. 同一 bar 同时触及止损和止盈时判止损。
3. 到达最大持仓时间的 bar 先按 open 退出，再观察该 bar high/low。
4. 每折训练标签只要延伸到测试窗就会被 purge；训练和测试之间另有 embargo。
5. 测试 feature cohort 预先固定，不会根据未来是否提前结束而删样本。
6. 测试窗后保留完整 evaluation tail，使尾部所有信号都走完相同标签周期。
7. 模型在训练期较早部分拟合，在训练期最后 20% 做 Platt 概率校准；测试期不参与选择。
8. next-open 风控使用当前 open 或上一根 close，相关性不包含当前尚未收盘的收益。
9. walk-forward 测试窗禁止重叠；最后 150 个共同交易日作为一次性 holdout。

## 数据

- Yahoo 日频 midpoint，2010-01-01 至 2026-07。
- 12 个主流及交叉货币对，每个约 4,050–4,238 根合法日线。
- 共同可用 3,269 个交易日。
- Yahoo 原始 OHLC 存在 close 超出 high/low 的非法行；适配器明确删除并写入
  `_data_manifest.json`，不修改价格伪造 K 线。
- Yahoo 没有历史 bid/ask 和可靠 swap，本结果只能用于因子初筛，不能证明实盘表现。

## 最终实证结果

| 类型 | 测试区间 | AUC | 交易数 | 收益 | PF | 最大回撤 |
|---|---|---:|---:|---:|---:|---:|
| Development 1 | 2017-05–2019-07 | 0.548 | 295 | +0.60% | 1.024 | 3.21% |
| Development 2 | 2019-07–2021-08 | 0.548 | 93 | -1.88% | 0.789 | 2.32% |
| Development 3 | 2021-08–2023-08 | 0.529 | 74 | -2.48% | 0.673 | 2.95% |
| Development 4 | 2023-08–2025-09 | 0.555 | 61 | -2.02% | 0.692 | 4.02% |
| Untouched holdout | 2025-09–2026-07 | 0.568 | 13 | -0.25% | 0.781 | 0.93% |

开发窗口复合收益为 -5.68%，只有 1/4 为正；最终 holdout 也为负。因此当前多因子模型状态是
`rejected_for_trading`，不会设置 `paper_enabled`。AUC 略高于 0.5 只说明存在微弱排序信息，
不等于扣除执行约束后盈利。

较稳定的研究候选包括 `weekday_cos`、`return_skew_24`、`efficiency_12/24` 和部分货币图
强度因子。它们只能进入下一轮 broker bid/ask 数据研究，不能单独作为策略上线。

第二轮已经把同一时间/品种的 long/short 合并成一个独立观察：方向因子检验 long/short
realized R 之差，状态因子检验两方向 realized R 的均值；随后按时间做 moving-block bootstrap
并进行 Benjamini–Hochberg FDR 校正。严格 FDR 10% 后，4 个开发折均无合格因子，因此空模型
产生 0 笔交易，结论仍为拒绝。详见
[第二轮成对因子挖掘记录](FACTOR_ROUND2_2026-07-15_ZH.md)。

## 运行

```bash
uv run fxtrade factor-download -c configs/factors_daily.yaml
uv run fxtrade factor-mine -c configs/factors_daily.yaml
```

主要产物：`factor_catalog.csv`、逐折因子统计、系数稳定性、全部样本外预测、每折交易、
数据/配置 manifest 和 `FACTOR_REPORT.md`。
