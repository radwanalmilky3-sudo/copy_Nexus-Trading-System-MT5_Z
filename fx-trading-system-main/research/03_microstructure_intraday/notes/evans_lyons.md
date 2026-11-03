# [Evans & Lyons 2008/机制稿] How Is Macro News Transmitted to Exchange Rates?

- 深度层级: L3
- 引用链角色: foundational（机制 only）
- DOI/URL: 项目地图指向 https://doi.org/10.1016/j.jinteco.2009.03.005 ；作者稿 “How Is Macro News Transmitted to Exchange Rates?”
- 开放获取: 作者 PDF
- 本项目映射: **机制参考 only**；无授权签名订单流前不实现方向规则
- 复制状态: fail_closed_missing_data / negative_control 边界

## 1. 经济机制

宏观新闻既可**直接**进入价格（共同知识），也可**间接**通过订单流进入价格（分散信息聚合）。作者表明：订单流渠道可解释新闻对汇率总影响的约三分之二；新闻到达后 order flow 波动对价格的贡献上升。这与“公告一出即完全反映在 mid 价、与成交无关”的观点冲突。

## 2. 精确公式

```text
# 签名订单流
OF_t = buyer_initiated_volume - seller_initiated_volume

# 价格与订单流
Δp_t = α + β News_t + γ OF_t + ε_t
OF_t = δ News_t + η_t

# 总效应 = 直接 β + 间接 γ*δ
# 结论：间接渠道主导（约 2/3）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 货币 | DM/$ 等主要对 |
| 频率 | 交易级 / 高频 |
| 样本 | 1990s 交易数据 + 定时公告 |
| 订单流 | 真实签名成交方向 |

## 4. 成本与可实现性

- 无签名订单流就**没有**本文的可复制信号。
- 本项目可用的 quote size、tick count、CFTC 周仓位**都不是** OF。

## 5. 识别与稳健性

- 区分直接/间接；强调异质信息。
- 对零售研究：最多作“为何 blackout 后仍可能有持续价格发现”的机制注释。

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 签名主动买卖量 | 是 | 无授权 | fail closed / 机制 only |
| 新闻时间戳 | 是 | 部分 | 不估间接渠道 |
| CFTC TFF | 否 | 有 | **禁止**替代 OF |

## 7. 本项目映射

- 明确禁止：CFTC ≠ signed order flow；Dukascopy size ≠ market OF
- 将来若获授权流：先登记假设与数据合同，再进搜索族

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| related | Andersen et al. | 直接公告效应 |
| related | Breedon & Ranaldo | 可预测 OF 季节性 |
| boundary | CFTC TFF 文档 | 非 OF |

## 9. 精读问题

1. News 是 scheduled only 还是 broad news spectrum？
2. 间接渠道在电子经纪时代是否下降？
3. 如何设计负对照证明“用 tick count 冒充 OF”会被拒绝？
