# [Brunnermeier, Nagel & Pedersen 2008/2009] Carry Trades and Currency Crashes

- 深度层级: L3
- 引用链角色: foundational（crash / funding）
- DOI/URL: https://doi.org/10.1086/593088 ；NBER WP 14473
- 开放获取: https://www.nber.org/system/files/working_papers/w14473/w14473.pdf
- 本项目映射: carry crash 风险门控；**非**新方向因子
- 复制状态: extension_only（gate）；完整期货持仓+期权 RR 为数据扩展
- 公式置信度: high（NBER WP）
- published premium vs implementable: 解释 carry 左尾，不提供稳定正 premium 策略
- 2016–2025 外推: funding 渠道仍相关，但 VIX 阈值不可事后挑选

## 1. 经济机制

Carry 的平均正收益与**负偏度/crash risk**共存：高息货币“上楼梯、下电梯”。资金流动性收紧（VIX、TED 等代理）时，杠杆 carry 头寸被迫平仓 → 投资货币急贬、融资货币急升。这与 Brunnermeier–Pedersen 流动性螺旋一致：保证金↑、资金↓、价格冲击放大。Crash 风险可在均衡中阻止投机者把 UIP 套利到零。

## 2. 精确公式

```text
# 汇率：st = log(外币 per USD)
# 外币投资、美元融资的超额收益
z_{t+1} ≡ (i*_t - i_t) - Δs_{t+1}
# UIP: E_t[z_{t+1}] = 0

# 实现偏度：季度 t 内日度汇率变化 (-Δs) 的样本偏度
Skewness_t = skewness( daily (-Δs) within quarter t )

# 投机持仓代理（CFTC）
Futures_t = (noncommercial long - short) / noncommercial open interest
# 在外币期货上的净多头比例

# 关键回归结构（概念）
# 利差预测未来 skewness 为负；VIX 上升伴随 carry 平仓与后续 crash 风险变化
# 交互: VIX_t * sign(i*_{t-1} - i_{t-1}) 等用于状态依赖预测
```

组合层面：并非 LRV 式六分位 HML，而是**双边相对 USD 的利差状态**与八大货币横截面/时间序列。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | AUD, CAD, JPY, NZD, NOK, CHF, GBP, EUR vs USD |
| 频率 | 日度构偏度；主分析季度；亦用周度 |
| 样本起止 | 1986–2006（风险逆转 1998–2006） |
| 数据 | 利率、即期、CFTC 期货持仓、期权 risk reversal |
| 排序 | 按利差看 skewness/RR 横截面 |

## 4. 成本与可实现性

- 原文重点不是扣成本后的 alpha，而是 **crash 特征与 funding 状态**
- 迁移：用 VIX/TED 做**事前冻结**的风险门控可以是项目扩展；用危机后挑选的阈值是数据挖掘
- 门控降低交易频率 → 成本结构改变，但也可能削减右尾利润

## 5. 识别与稳健性

- 横截面：更高 \(i^*-i\) ↔ 更负的实现偏度与 risk reversal
- 时间序列：VIX 上升 ↔ 投机 carry 仓位下降、投资货币承压
- 平仓后未来 crash risk 与 crash 价格的动态：损失降低未来 crash 概率但提高 crash 价格（论文叙事）
- 控制：不是简单无条件 skewness（无条件货币对 skew 可因计价对称接近 0）

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 日度 FX 收益 | 是（偏度） | 有/可有 | — |
| 利差或 forward discount | 是 | forward 缺则用利率扩展 | 标记 extension |
| VIX / TED / funding | 门控 | VIX 可得 | 阈值必须预注册 |
| CFTC futures 持仓 | 原文代理 | 周度；非实时 | 只作机制/低频状态 |
| 期权 risk reversal | 原文 | OTC 缺 | fail closed for RR 复制 |

## 7. 本项目映射

- registry：`slow_carry_volatility_gate` 等为**有动机的扩展**，不是 BNP 精确复制
- 持有期：门控作用于已有 carry 方向
- 否决：事后按危机窗调阈值；把 crash 指标当方向信号反转钓鱼
- reused-history：门控超参搜索计入 FDR

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Brunnermeier & Pedersen (2009) 流动性螺旋 | 理论 |
| foundational | Lustig et al. (2011) | carry 因子 |
| boundary | Moreira & Muir (2017) | vol 管理 vs 阈值门控 |
| boundary | Du et al. (2018) | 融资/资产负债表摩擦 |

## 9. 精读问题

1. 用全球 FX 实现波动代替 VIX，门控经济含义差在哪里？
2. 偏度用日度窗口 21/63 日 rolling 是否仍预测下一持有期左尾？
3. 门控应作用于名义敞口、杠杆，还是完全暂停交易？
4. 2016–2025 中哪些事件是“carry crash”模板（2016 脱欧、2020、2022 JPY）？
5. 如何在不引入前视的前提下冻结门控阈值（训练窗分位数）？
