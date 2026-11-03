# [Della Corte, Ramadorai & Sarno 2016] Volatility Risk Premia and Exchange Rate Predictability

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1016/j.jfineco.2016.02.015
- 开放获取: City OA https://openaccess.city.ac.uk/id/eprint/13156/
- 本项目映射: 横截面 VRP / 10Δ RR；Cboe 30D IV **不能**冒充
- 复制状态: fail_closed_missing_data（OTC 一年期 smile）
- 公式置信度: high（accepted manuscript + 文献地图）
- published premium vs implementable: 期权隐含信号；现货/远期执行仍耗点差
- 2016–2025 外推: 中高；期权流动性与 vol 定价结构变化

## 1. 经济机制

货币**波动风险溢价** VRP = 物理测度预期实现波动 − 风险中性（model-free）隐含波动，度量“为波动保险支付的成本”。高保险成本货币 vs 低保险成本货币的横截面可预测即期收益。机制与 limits to arbitrage（对冲者/投机者、资金约束、VIX×TED）一致；与传统宏观汇率模型菜单不同。Risk reversal 捕捉偏度价格，提供平行排序。

## 2. 精确公式

```text
# 波动互换（概念）
VP_{t,τ} = RV_{t,τ} - SW_{t,τ}
SW_{t,τ} = E^Q_t[RV_{t,τ}]

# Model-free 隐含方差（Britten-Jones–Neuberger / Jiang–Tian）
E^Q[RV²_{t,τ}] = κ * [ ∫_0^F (1/K²) P(K) dK + ∫_F^∞ (1/K²) C(K) dK ]
E^Q[RV] = sqrt(E^Q[RV²])   # 波动互换执行价近似

# 外汇 OTC：固定 delta 五点 smile → 样条 → 数值积分
# 主预测用 1Y 期限

# 事前 VRP（Bollerslev–Tauchen–Zhou 风格）
VRP_{t,τ} = E^P_t[RV_{t,τ}] - E^Q_t[RV_{t,τ}]
E^P ≈ 滞后实现波动 RV_{t-τ,τ} = sqrt( 252/τ * sum r² )

# 项目文献地图中的可操作形式（月末）
VRP_{i,t} = realized_vol_{i,t-252:t} - model_free_IV_{i,t,1y}
RR_{i,t}  = IV_{i,t,1y,10δ_call} - IV_{i,t,1y,10δ_put}

# 组合：按 VRP 或 RR 五分位，等权，持有 1 月
# VRP: 多最高组 / 空最低组
# RR:  多最低组 / 空最高组（符号按原文）
# 收益主要来自即期变动，而非利差
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 期权 | JP Morgan OTC FX 波动曲面（ATM、25/10Δ RR、BF 等） |
| 利率/转换 | Bloomberg |
| 频率 | 月 |
| 样本 | 约 1996–2011 量级（以 OA 版表格为准） |
| 币种 | 主要 G10 等可交易货币 |

## 4. 成本与可实现性

- 信号来自期权；组合在 FX 现货/远期执行
- 需考虑 FX 点差；期权本身若交易 VRP 则另计
- Cboe EVZ/EUVIX/JYVIX/BPVIX：**30 日、三币种、中途停止** → 仅风险状态，不是本因子

## 5. 识别与稳健性

- VRP 排序策略显著；与 carry/momentum 低相关、有分散
- 标准风险因子难完全解释
- 资金/对冲流量证据支持 limits to arbitrage 渠道

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 1Y OTC smile 五点 | 是 | **无** | **fail closed** |
| 日收益以实现 RV | 是 | 有 | — |
| 10Δ RR | RR 因子需要 | 无 | fail closed |
| 月末排序 + 1M 持有 | 是 | 可 | — |
| Cboe 30D IV | 否（非替代） | 部分 | 仅状态/审计 |

## 7. 本项目映射

- 不进方向候选直至 OTC smile 合同满足
- Cboe 序列：EUR/JPY/GBP 风险状态或机制审计
- 30D IV − 21D RV 代理必须标 **项目扩展**
- reused-history：若将来实现

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| option IV | Britten-Jones & Neuberger；Jiang & Tian | model-free |
| equity VRP | Bollerslev, Tauchen & Zhou | 预测结构 |
| FX smile | Della Corte, Sarno, Tsiakas 等 | 前作 |
| boundary | 本项目 Cboe 数据边界 | 不可冒充 |

## 9. 精读问题

1. 用 1M 而非 1Y IV 是否改变横截面排序稳定性？
2. VRP 定义 P−Q vs Q−P 符号错误会如何反转策略？
3. 仅三币种 Cboe 能否做任何有功效的横截面？
4. 期权流动性差的日子信号是否应标记缺失而非插补？
5. VRP 与 carry crash 状态是否应联合门控？
