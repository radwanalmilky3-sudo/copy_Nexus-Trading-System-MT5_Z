# 第二轮外汇因子挖掘记录（2026-07-15）

## 结论

第二轮没有找到可批准交易的盈利因子。严格按时间成对、moving-block bootstrap 和
Benjamini–Hochberg FDR 10% 检验后，4 个开发窗口均没有因子通过训练内准入门槛；系统因此
使用空模型、产生 0 笔交易，并保持 `rejected_for_trading`。0% 收益不是盈利结果，而是风控
正确拒绝了没有统计证据的候选。

本轮只使用 2010-01-01 至 2025-09-14 的数据。最后一个开发测试窗结束于 2025-09-03，
其后的几根 bar 只用于完成标签和持仓评估。已经查看过的 2025-09-26 至 2026-07-02 holdout
没有参与本轮选因子、拟合或调参。

## 新增候选

在原有约 50 个因子上增加 12 个候选：

- K 线与跳空：`close_location_value`、`gap_atr`、`breakout_distance_20`。
- 路径趋势：`trend_tstat_20/60`、`variance_ratio_5_60`。
- 分布状态：`semivariance_asymmetry_24`、`sign_entropy_24`。
- 波动估计：`parkinson_vol_ratio_20`。
- 横截面与货币图：`cross_sectional_momentum_12`、`currency_dispersion_12`、
  `pair_residual_z_12`。

严格三角一致的汇率图只有浮点残差。代码对 residual z-score 增加了相对尺度下限，防止把
约 `1e-15` 的数值噪声标准化成伪因子。

## 为什么要做成对检验

每个时间和品种同时生成 long/short 两个标签；它们共享同一段未来价格路径，不能被视为两个
独立样本。本轮把每个 `timestamp × symbol` 压缩成一个独立观察：

```text
方向因子结果 = (long realized R - short realized R) / 2
状态因子结果 = (long realized R + short realized R) / 2
```

方向因子必须解释第一项，才能提供做多或做空的选择能力；波动、星期等非方向因子只能解释
第二项，用于判断市场状态，不能单独充当方向 alpha。统计量随后按时间聚类，以 20-bar moving
blocks 做 1,000 次 bootstrap，并对每折的全部候选做 FDR 校正。

这个修正揭示了第一轮 AUC 略高于 0.5 的局限：星期和波动因子能预测“障碍是否容易触及”，
但 long/short 概率差不足以覆盖点差、滑点、佣金与低目标/止损比。

## 实证结果

| 开发窗 | 测试区间 | FDR 合格因子 | 交易数 | 收益 |
|---:|---|---:|---:|---:|
| 1 | 2017-05-04—2019-07-03 | 0 | 0 | 0.00% |
| 2 | 2019-07-04—2021-08-13 | 0 | 0 | 0.00% |
| 3 | 2021-08-18—2023-08-14 | 0 | 0 | 0.00% |
| 4 | 2023-08-15—2025-09-03 | 0 | 0 | 0.00% |

`return_skew_24` 的 paired OOS IC 在 4 折同号、均值约 0.023，但平均 q 值约 0.938；
`pair_residual_3/6` 也同号但效应更小。它们只能作为观察名单，不能称为显著因子。

未启用严格 FDR 门槛的探索性模型加入新因子后，4 折复合收益为 -14.91%，0/4 盈利。这一
结果不用于选参数，只用于说明继续堆价格因子会扩大过拟合，而不是自然产生 alpha。

## 下一轮应改变什么

当前瓶颈不是模型复杂度，而是信息集。合理的下一轮顺序是：

1. 获取目标 broker 至少 8–10 年历史 bid/ask、实际 spread、swap/rollover 与交易时段数据；
   重新估算标签和净 R，而不是继续依赖 Yahoo midpoint。
2. 增加有经济来源且与价格技术指标不同的信息：央行政策利率与 OIS/forward points（carry）、
   宏观 surprise、CFTC 仓位、CME 成交量与持仓量、期权风险逆转和隐含波动率。
3. 预先登记少量假设。每个经济假设只实现少数窗口，继续使用成对 block bootstrap 与 FDR，
   避免把上百个参数组合当作独立发现。
4. 不再使用已经查看过的 holdout。候选冻结后，至少运行 3–6 个月全新 OANDA practice
   前向期，只有扣成本后多个市场状态均为正才考虑下一阶段。

复现命令：

```bash
uv run fxtrade factor-mine -c configs/factors_daily_round2_dev.yaml
```

主要产物位于 `outputs/factors_daily_round2_fdr_dev/`，其中
`oos_factor_statistics_by_fold.csv` 包含每折 paired OOS IC、bootstrap p 值和 FDR q 值。
