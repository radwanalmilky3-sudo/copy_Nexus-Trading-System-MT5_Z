# [Moreira & Muir 2017] Volatility-Managed Portfolios

- 深度层级: L3
- 引用链角色: boundary（仓位管理，非新方向）
- DOI/URL: https://doi.org/10.1111/jofi.12513 ；NBER WP 22208
- 开放获取: https://www.nber.org/system/files/working_papers/w22208/w22208.pdf
- 本项目映射: own-factor inverse-variance sizing；**区分** global-vol 阈值门控
- 复制状态: extension_only（依赖可交易 carry 因子序列）
- 公式置信度: high（NBER WP）
- published premium vs implementable: 提高 Sharpe/alpha；c 用全样本校准不影响 Sharpe 但影响杠杆路径
- 2016–2025 外推: 中；vol timing 拥挤可能降低 alpha

## 1. 经济机制

短期方差高度可预测，而条件风险溢价并不同比例上升 → 高波动期 **μ/σ²** 变差。均值-方差投资者应在高实现方差后**降低**风险暴露。对已有因子（含 FX carry）做 inverse-variance 缩放可提高 Sharpe。这是**同一方向上的风险管理**，不是新的横截面排序信号。

## 2. 精确公式

```text
# 波动管理组合
f^σ_{t+1} = (c / σ̂²_t(f)) * f_{t+1}

# 主代理：上一个自然月的实现方差（日收益）
σ̂²_t(f) = RV²_t(f) = sum_{d in month t} (f_d - mean_t(f))²
# 文中写为对月内约 22 个交易日的平方偏差和

# c: 使 managed 与 unmanaged 无条件波动相同
# 注意：c 常用全样本；正式 PIT 应在训练窗冻结 c 或固定 target vol

# 评价
f^σ_{t+1} = α + β f_{t+1} + ε_{t+1}
# α>0 ⇒ vol timing 提高相对原因子的风险调整表现

# FX Carry: Lustig et al. high-minus-low 利率/forward discount 因子
# 日度用 high/low 组合汇率变化构造 RV
```

**没有**离散阈值，**不是** `global_fx_vol_innovation_z < 1` 这类门控。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 因子 | Mkt, SMB, HML, Mom, RMW, CMA, IA, ROE, **FX Carry** |
| Carry 来源 | Lustig et al. / Verdelhan 数据 |
| 频率 | 月度缩放；日度 RV |
| 样本 | 股权因子长样本；Carry 约 1983 起 |

## 4. 成本与可实现性

- 换手上升；原文稳健性仍显示益处
- 迁移：
  - 必须先有**可交易 carry 因子**的日收益
  - 杠杆在低 vol 时上升 → 融资与账户上限
  - 全样本 c 不改 Sharpe 但改绝对波动与破产概率

## 5. 识别与稳健性

- 多因子 α 与 Sharpe 提升；Carry 包含在受益集合
- 与“高 vol 高溢价”代表代理人模型张力
- 更复杂方差预测非必须

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 日度因子收益 f_d | 是 | carry 缺真实 forward | fail closed for exact |
| 上月 RV | 是 | 可算 | — |
| 月度缩放时点 | 是 | 月初/月末冻结 | — |
| c 或 target vol | 是 | 需 PIT 规则 | 全样本 c = 研究-only |
| 杠杆上限 | 实现 | incomplete | 不可无限放大 |

## 7. 本项目映射

- registry：对已有 carry 的 vol-managed sleeve；**不是** `slow_carry_volatility_gate` 的精确对应
- 否决：把阈值门控汇报为 Moreira–Muir 复制；无 forward 的伪 carry 上做 vol 管理还称复制
- reused-history：是

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Lustig et al. (2011) | Carry 因子输入 |
| parallel | BNP crash | 高 vol/funding 降仓动机 |
| boundary | 项目 global vol gate | 不同合同 |

## 9. 精读问题

1. 用 21 日滚动 RV 代替自然月 RV，α 是否稳定？
2. 在杠杆上限 2× 下，managed carry 的 α 还剩多少？
3. managed 与 unmanaged 的相关导致的多重检验如何处理？
4. 危机月“降仓”是否只是卖在最差之后（执行时点）？
5. 与阈值 gate 同时使用是否双重缩仓过度？
