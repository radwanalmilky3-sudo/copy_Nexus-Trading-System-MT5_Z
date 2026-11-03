# [Burnside, Cerrato & Zhang 2020/2022] Foreign Exchange Order Flow as a Risk Factor

- 深度层级: L3
- 引用链角色: foundational boundary（微观结构 × SDF 定价因子）
- DOI/URL: NBER w27199 https://www.nber.org/papers/w27199
- 开放获取: `_pdfs/_nber/fx_order_flow_risk_factor_w27199.pdf`（first-page OK）
- 本项目映射: 订单流**不能**当零售方向信号；若有分段客户流，可作 crash/拥挤**诊断因子**
- 复制状态: fail_closed_missing_data（银行客户订单流）
- 公式置信度: high（NBER WP rev. 2022）
- published premium vs implementable: 因子定价成功 ≠ 可交易 order-flow 策略；客户分段不可得
- 2016–2025 外推: 电子化/内部化后客户流结构变化；机制仍相关

## 1. 经济机制

汇率文献两支看似对立：（1）**摩擦less SDF/风险补偿**解释 carry 等异象；（2）**微观结构**中异质信息经 **order flow** 进入价格（Evans–Lyons 线）。本文用客户订单流构造与 **carry / momentum 买卖压力**相关的定价因子，表明：看似 SDF 友好的横截面证据也可与订单流驱动相容。Order-flow 因子是 **currency crash risk** 的良好代理；且关联依客户分段而异——**金融客户**像风险承担者，**非金融客户**像流动性提供者。

## 2. 精确公式

```text
# 微观结构线性原型（Evans–Lyons 类）:
# Δs_t = α + β · FundamentalsNews_t + λ · OF_t + ε_t
# OF_t = 对做市商的净买入（buy - sell 客户单）

# 本文：不用逐笔预测汇率，而把 OF 聚合成**策略相关压力**定价因子
# 概念上（细节以正文分段定义为准）:
# OF_carry,t  ∝  与高息货币买入 / 低息货币卖出一致的客户净流
# OF_mom,t   ∝  与动量多头一致的客户净流

# 货币超额收益（标准）:
# rx_{i,t+1} = (i*_{i,t} - i_t) - Δs_{i,t+1}   # 或远期形式

# 资产定价（线性 beta）:
# E[rx_i] = β_i' · λ
# 候选因子含 OF_carry、OF_mom 及对照（HML_FX、全球 FX vol 等）

# 分段:
# OF^fin vs OF^nonfin ：同一方向压力对收益的载荷符号/角色可反号
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产 | 多币种货币超额 / 利率排序组合 |
| 关键数据 | 客户订单流（含金融 vs 非金融分段） |
| 频率 | 因子构造与组合再平衡以文中日历为准（典型月/日聚合） |
| 对照策略 | carry、momentum |
| 样本 | 见 NBER 稿数据节（银行流样本窗受限） |

## 4. 成本与可实现性

- 原文：定价/解释；非零售执行研究
- 迁移：**无授权客户流 = fail closed**；不可用公开 mid 量价冒充 OF
- 即使 β 显著，交易 OF 本身改变流、有延迟与披露约束

## 5. 识别与稳健性

- OF 因子与 carry 收益共变，解释 crash 特征
- 客户分段：金融 vs 非金融角色不对称（风险承担 vs 供给流动性）
- 意在调和 SDF 与微观结构，而非否定其中一支
- 对标准股票风险因子定价 FX 的无力形成对照（与 Burnside 既有立场一致）

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 分段客户订单流 | 是 | 无 | fail closed |
| 即期 + 利率/远期 | 是 | 部分 | 标准 carry 可扩展 |
| 策略标签（carry/mom 篮子） | 是 | 可构造 | — |
| 银行间公开 OF 代理 | 否（非等价） | CLS 等有限 | 不可替换正文因子 |

## 7. 本项目映射

- registry：不设 `order_flow_factor` 交易规则
- 用途：解释 carry 拥挤/crash 的**外部效度**；与 CFTC 定位、VIX 门控叙事对照
- 否决：用 Dukascopy 主动买卖差当“客户 OF 风险因子”
- 机制链：`03_microstructure_intraday/notes/evans_lyons.md`

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational micro | Evans & Lyons (2002) | OF 决定汇率 |
| SDF carry | Lustig–Roussanov–Verdelhan | HML_FX |
| vol risk | Menkhoff et al. JF 2012 | 全球 FX vol |
| crash | Brunnermeier–Nagel–Pedersen | 左尾 |

## 9. 精读问题（给最强模型）

1. OF_carry 与 HML_FX 的相关系数在危机年是否结构性上升？
2. 金融客户流领先还是滞后于利差排序再平衡？
3. 无客户分段时，总 OF 是否仍定价，还是平均掉信号？
4. 日度 OF 聚合到月度因子的信息损失有多大？
5. 与 CIP/美元融资压力指标是互补还是相互吸收？
