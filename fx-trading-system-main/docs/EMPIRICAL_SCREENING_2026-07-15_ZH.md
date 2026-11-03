# 策略实证筛选记录（2026-07-15）

## 数据与口径

- 数据：Yahoo 公共 hourly midpoint，下载后按 UTC 重采样为 4h。
- 品种：EURUSD、GBPUSD、USDJPY、USDCHF、AUDUSD、NZDUSD、USDCAD。
- 区间：2024-07-16 00:00 UTC 至 2026-07-14 12:00 UTC。
- 样本：每品种 2,988–3,010 根完整 4h bar；不足 4 个小时样本和未收盘 bar 已删除。
- 成本：逐品种 0.7–1.2 pip spread、0.15 pip slippage、每百万基础货币每边 35 USD
  等价佣金；Yahoo 没有可靠历史 swap，因此本轮 swap 为 0。
- 风险：单笔 0.3%，组合 1.5%，共享币种/杠杆/相关性限制，12% 回撤熔断。

Yahoo 不是可成交 broker bid/ask，本轮只能淘汰明显不合格候选，不能证明剩余候选可实盘。

## 全样本同口径筛选

| 排名 | 策略 | 交易数 | 收益 | Sharpe | 最大回撤 | 胜率 | 实际盈亏比 | PF | 结论 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Session breakout | 509 | -10.71% | -1.39 | 12.01% | 56.78% | 0.616 | 0.809 | 拒绝上线 |
| 2 | Regime mean reversion | 517 | -9.78% | -1.43 | 12.17% | 60.35% | 0.552 | 0.839 | 拒绝上线 |
| 3 | Ensemble | 630 | -11.31% | -1.51 | 12.16% | 58.89% | 0.583 | 0.834 | 拒绝上线 |
| 4 | False breakout reversal | 564 | -11.70% | -1.55 | 12.02% | 59.57% | 0.556 | 0.819 | 拒绝上线 |
| 5 | Currency strength reversion | 505 | -11.02% | -1.59 | 12.11% | 60.59% | 0.529 | 0.813 | 拒绝上线 |
| 6 | Trend pullback | 373 | -11.59% | -1.92 | 12.04% | 54.96% | 0.633 | 0.772 | 拒绝上线 |
| 7 | Cointegration spread | 6 | +0.09% | +0.17 | 0.58% | 66.67% | 0.573 | 1.146 | 样本严重不足，拒绝上线 |

低盈亏比策略需要足够高的净胜率。比如实际盈亏比为 0.552 时，忽略成本的盈亏平衡胜率已经是
64.4%；Regime mean reversion 的 60.35% 仍不足。只展示高胜率而不同时展示实际盈亏比和 PF
会造成误导。

## 滚动样本外

使用 1,200 根训练 bar 排名、选择前 2 个候选，再在后续 400 根完全样本外 bar 交易；窗口
每次前移 400 根。

| Fold | 训练窗选择 | 测试交易数 | 测试收益 | 测试 Sharpe | 测试最大回撤 |
|---:|---|---:|---:|---:|---:|
| 1 | Currency strength + Regime MR | 152 | -5.04% | -2.98 | 7.48% |
| 2 | Currency strength + Regime MR | 114 | -2.53% | -2.08 | 4.01% |
| 3 | Currency strength + Session breakout | 156 | -5.80% | -4.00 | 7.67% |
| 4 | Currency strength + Session breakout | 95 | -3.07% | -2.74 | 3.87% |

四个样本外窗口全部为负；因此没有策略被标记为 `validated_pass`。OANDA practice 只用于验证
执行软件，不代表策略获准使用真实资金；默认配置中所有候选的 `paper_enabled` 均为 false。

## 下一轮研究优先级

1. 目标 broker 的 8–10 年历史 bid/ask、真实 spread、swap 与 rollover。
2. Regime MR 与 currency-strength 只做参数邻域和状态过滤稳定性研究，不追单点最优。
3. 协整策略需要更长样本和更宽的相关货币篮子，当前 6 笔完全不足。
4. Session/false-breakout 在当前口径明显不合格，默认不应作为资金策略。
5. Carry + risk-off 只有在利率、forward point 和 swap 数据齐备后才进入同口径筛选。
