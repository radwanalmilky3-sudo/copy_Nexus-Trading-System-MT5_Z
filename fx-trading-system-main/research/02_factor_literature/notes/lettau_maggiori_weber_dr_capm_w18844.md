# [Lettau, Maggiori & Weber 2014] Conditional Risk Premia in Currency Markets and Other Asset Classes

- 深度层级: L3
- 引用链角色: foundational / critique（下行风险 CAPM 统一定价 carry 等）
- DOI/URL: JFE 2014；NBER w18844 https://www.nber.org/papers/w18844
- 开放获取: `_pdfs/_nber/lettau_maggiori_weber_conditional_currency_premia_w18844.pdf`；数据附录 http://www.nber.org/data-appendix/w18844
- 本项目映射: carry 的**风险定价**对照（DR-CAPM）；解释“无条件 CAPM 失败”但条件 beta 成功
- 复制状态: extension_only（需市场组合+多资产测试组合）/ fail_closed_missing_data（完整货币 forward 面板）
- 公式置信度: high（NBER WP）
- published premium vs implementable: 解释横截面期望收益，不证明零售可实现
- 2016–2025 外推: 下行相关结构可能时变；需 OOS

## 1. 经济机制

无条件 CAPM 无法定价货币横截面：高息与低息货币的 **β 差距太小**，解释不了收益差距。**Downside-risk CAPM (DR-CAPM)** 允许 β 与风险价格在市场下行时改变。关键经验：高息货币在**市场坏状态**与市场的共变动更强；坏状态风险价格也更高。正确捕获条件 β 与条件风险价格后，可统一定价货币、股票组合、商品、主权债、股指期权等——对比 PCA 在跨资产时需要很多因子，DR-CAPM 用两个“基本面”加载（β 与 downside β 差）更紧凑。

## 2. 精确公式

```text
# 货币超额收益（标准 carry 排序组合）
# rx^i_{t+1}: 高/低息货币组合或单币对 USD

# 市场超额收益 rM_{t+1}
# 下行指示: 1_{rM_{t+1} < δ} ，常用 δ=0 或样本分位

# 无条件 CAPM:
E[rx^i] = β^i * λ_M
β^i = cov(rx^i, rM)/var(rM)

# Downside beta:
β^{i-} = cov(rx^i, rM | rM < δ) / var(rM | rM < δ)

# DR-CAPM 定价（概念）:
E[rx^i] = β^i * λ + (β^{i-} - β^i) * λ^-
# 即对 downside 相对暴露 (β^- - β) 支付额外溢价 λ^-

# 经验图景:
# 高息货币: β^- - β 更大 → 更高 E[rx]
# 无条件 β 差距不足 → CAPM 失败
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 货币 | 利率排序的货币组合（carry 横截面） |
| 其他测试资产 | 美股组合、商品、主权债、期权等 |
| 频率 | 月度 |
| 样本 | 跨资产对齐的共同样本（约 1970s/80s–2010s，视资产而定） |
| 市场因子 | 股票市场超额收益 |

## 4. 成本与可实现性

- 原文资产定价检验，非交易成本中心
- 迁移：即使 DR-CAPM 拟合好，零售净 carry 仍可能≤0
- mid ≠ net：定价成功 ≠ 可交易套利

## 5. 识别与稳健性

- 主结果：DR-CAPM 拟合货币横截面；跨资产联合仍有效
- 对照：无条件 CAPM、消费 CAPM 变体、PCA 因子
- 关键点：下行阈值 δ、市场组合定义、小样本条件矩噪声
- 与 Lustig HML_FX：可并存——HML 是可交易因子，DR-CAPM 是经济约束

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 货币组合 rx | 是 | forward 缺 | fail closed 精确 |
| 市场超额 | 是 | 可得 | — |
| 下行阈值规则 | 是 | 需预注册 | 数据挖掘风险 |
| 多资产测试 | 原文 | 超出 | 仅货币扩展 |

## 7. 本项目映射

- registry：不作为新 alpha 信号；作 **risk model / 诊断**（carry 是否只是 downside β）
- 否决：用全样本 δ 优化后再报告定价 R²
- reused-history：δ、市场定义变体计入试验

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| method | Ang–Chen–Xing downside beta | 股权前身 |
| FX factors | Lustig–Roussanov–Verdelhan | 可交易因子 |
| critique | Burnside 风险因子失败 | 无条件相关≈0 |
| vol | Menkhoff VOL | 另一风险通道 |

## 9. 精读问题（给最强模型）

1. δ=0 vs 10% 分位对 2016–2025 货币横截面？
2. 用全球股票还是美国市场作 rM？
3. DR-CAPM 残差是否仍被 HML_FX 解释？
4. 下行 β 估计的重叠月度如何处理？
5. 若净成本后 E[rx]≈0，定价等式是否自动“成立”而无经济内容？
