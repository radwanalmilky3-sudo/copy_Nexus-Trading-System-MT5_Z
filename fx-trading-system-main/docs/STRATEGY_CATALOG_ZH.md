# 策略筛选目录

系统不是把策略名字堆在一起，而是先看证据与数据可得性，再用相同成本、相同风险预算做横向
回测，最后通过 walk-forward 只在训练窗选策略、在后续测试窗记分。

## 已实现候选

| 策略 | 交易逻辑 | 多货币 | 默认目标/止损 | 最长持仓 | 主要失败模式 |
|---|---|---:|---:|---:|---|
| Regime mean reversion | 非趋势状态下 z-score + RSI 极端反转 | 否 | 0.72 / 1.15 | 72h | regime 突变、趋势中接飞刀 |
| Trend pullback | EMA 趋势中回踩后重新越过快线 | 否 | 0.90 / 1.25 | 120h | 震荡 whipsaw、新闻跳空 |
| London session breakout | 完整亚洲盘窄区间后伦敦时段突破 | 否 | 0.78 / 1.20 | 20h | 假突破、开盘点差扩大 |
| False breakout reversal | 多日区间被刺穿但收盘退回时反向交易 | 否 | 0.68 / 1.10 | 36h | 趋势恢复、bar 内路径未知 |
| Currency strength reversion | 从所有货币对构造币种收益图，只做全图确认的过度延伸 | 是 | 0.70 / 1.15 | 72h | 同一宏观冲击让“极端”继续扩大 |
| Cointegration spread | 滚动 OLS + Engle–Granger 通过后，成对交易 spread 极值 | 是 | 0.90 / 1.30 | 120h | 协整断裂、双腿执行风险 |

这些是“进入验证的候选”，不是“已证明赚钱”。低目标/止损比意味着需要较高净胜率；点差和
滑点会让实际平均盈利/平均亏损进一步恶化，因此报告同时显示 realized payoff、win rate、
profit factor 和 costs，不能只看胜率。

## 已研究但暂不接入执行

| 候选 | 证据/动机 | 暂缓原因 |
|---|---|---|
| Carry + risk-off filter | 货币 carry 文献充分，但 crash risk 明显 | 需要可靠利率、forward points、swap 与风险代理数据 |
| 宏观 surprise drift | CPI/NFP/央行发布后可能延迟反应或反转 | 需要带 forecast/actual/revision 的经济日历和 tick bid/ask |
| CME FX OI + momentum | OI 增长配合价格突破可区分新资金 | OI 延迟、换月和 spot/future 映射需独立数据管线 |
| Cross-sectional monthly momentum | Menkhoff 等对货币动量有长期证据 | 默认目标是周内持仓，周期不匹配 |
| 三角套利 | 理论无方向风险 | 零售延迟、成交原子性和成本使 bar 数据回测无效 |
| Martingale/grid | 可能产生漂亮高胜率 | 有限资本下尾部破产风险，不进入候选 |

## 研究依据

- Moskowitz, Ooi, Pedersen, *Time Series Momentum*, JFE 2012。
- Menkhoff et al., *Currency Momentum Strategies*, BIS Working Paper 366。
- Brunnermeier, Nagel, Pedersen, *Carry Trades and Currency Crashes*, NBER/JME。
- Engle & Granger, *Co-integration and Error Correction*, Econometrica 1987。
- Breedon & Ranaldo, *Intraday Patterns in FX Returns and Order Flow*, Journal of Money,
  Credit and Banking 2013。

实际筛选命令：

```bash
uv run fxtrade screen -c configs/default.yaml
uv run fxtrade walk-forward -c configs/default.yaml --train-bars 1200 --test-bars 400 --top-k 2
```

`screen` 只用于比较；最终判断应以多个 walk-forward 测试窗、broker bid/ask 成本、参数稳定性
和危机区间压力测试为准。
