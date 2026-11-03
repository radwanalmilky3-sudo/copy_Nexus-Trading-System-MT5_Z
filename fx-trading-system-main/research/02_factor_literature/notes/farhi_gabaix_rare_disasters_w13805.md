# [Farhi & Gabaix 2008/2016] Rare Disasters and Exchange Rates

- 深度层级: L3
- 引用链角色: foundational theory（灾难风险 → 远期升水谜题）
- DOI/URL: NBER w13805；后续 QJE 2016 修订线
- 开放获取: `_pdfs/_nber/farhi_gabaix_rare_disasters_exchange_rates_w13805.pdf`
- 本项目映射: carry / UIP 的**灾难风险**理论边界；期权 skew 作为潜在状态变量动机
- 复制状态: extension_only（理论校准）/ fail_closed_missing_data（跨国期权曲面）
- 公式置信度: high（NBER WP 机制与关键式）
- published premium vs implementable: 模型解释**为何**高息货币平均升值；不给出零售可实现净 alpha
- 2016–2025 外推: 全球风险冲击仍相关；但完整市场摩擦less 假设与 CIP/中介约束时代需并用 Gabaix–Maggiori、Du 等

## 1. 经济机制

在**无摩擦、完全市场、任意国家数**框架下，引入**全球稀有灾难**与各国对灾难的**时变暴露**。灾难风险高的国家：汇率贬值（风险溢价高）且利率高；当暴露均值回复时，汇率升值。于是**高息货币平均升值**，Fama 回归系数可小于 1 甚至为负——即 forward premium puzzle 的风险定价版，而非非理性。期权价格原则上可揭示潜在灾难强度与 skew，并辅助预测汇率。扩展可叠加商业周期因子，校准匹配汇率波动、近随机游走与 Fama 系数。

## 2. 精确公式

```text
# UIP / Fama 基准（对数）:
E_t[Δs_{t+1}] = i_t - i*_t     # 系数 1
# 谜题: 回归 Δs 对 (i-i*) 的斜率常 <1 或负

# 模型直觉（文中核心）:
# 世界灾难可冲击各国生产力；国家 i 的灾难暴露过程 mean-reverting
# 高暴露 ⇒ 高货币风险溢价 ⇒ 高利率 + 贬值的汇率水平
# 暴露下降（均值回复）⇒ 风险溢价下降 ⇒ 汇率升值
# ⇒ corr( high i*, subsequent appreciation ) > 0

# 资产观汇率: 汇率是两国 SDF / 边际价值的比（Backus–Foresi–Telmer 族）
# 灾难态: 消费/生产力大跌 ⇒ M 跳升；暴露差异驱动相对 M

# 期权含义（可实施诊断，非完整复制）:
# OTM put/call 隐含 vol → 灾难强度代理
# 跨国 skew 差 → 相对灾难暴露
# 文中: options evidence supportive（定性）

# 校准目标（概念）:
# σ(Δs), Fama β, near-RW, 股债汇期权联合矩
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 性质 | 理论 + 校准；辅以期权定性证据 |
| 资产 | 多国汇率、利率、股票、期权 |
| 频率 | 模型连续/离散时间；经验对照月度常见 |
| 灾难参数 | 借鉴 Barro (2006) 等宏观灾难矩（放大风险价格） |

## 4. 成本与可实现性

- 原文：摩擦less；无 bid/ask、无 CIP 偏离
- 迁移：不能把模型风险溢价直接当交易信号；期权代理需 OTC 曲面
- mid ≠ net：灾难溢价在危机中实现为左尾，与 BNP crash 经验一致

## 5. 识别与稳健性

- 同时解释：汇率“过度”波动、UIP 失败、近随机游走
- 双因子扩展：灾难 + 周期
- 与 Burnside peso：同属“坏状态高 M”，但 FG 给完全市场结构，Burnside 强调样本未实现 + 期权识别
- 局限：无中介资产负债表、无 CIP；2010s 后需金融摩擦补丁

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 理论复制 | 否（非策略） | — | — |
| 期权 skew 代理 | 扩展诊断 | 无 OTC | fail closed |
| 利差/即期 | 对照 | 有/部分 | extension |
| 灾难强度时变 | 模型状态 | 不可直接观测 | 仅用 vol/RR 弱代理 |

## 7. 本项目映射

- registry：理论否决/叙事；**不**注册“rare_disaster_long_short”无预注册代理
- 持有期：n/a
- 否决：用事后危机窗拟合灾难强度当信号
- reused-history：任何 RR/skew 预测搜索计入试验数

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Rietz/Barro disasters | 灾难资产定价 |
| empirical twin | Burnside et al. peso | 期权识别 |
| friction | Gabaix–Maggiori 2015 | 中介替代完全市场 |
| crash | Brunnermeier–Nagel–Pedersen | 已实现左尾 |

## 9. 精读问题（给最强模型）

1. 用 VIX 或全球 FX RV 代替期权灾难强度，Fama 系数预测力剩多少？
2. 模型中“高息=高灾难暴露”与商品货币高息如何调和（Ready–Roussanov–Ward）？
3. 完全市场预测的跨国期权矩在 2016–2025 是否仍成立？
4. 与 DOL/HML_FX 两因子如何嵌套？
5. 灾难强度均值回复半衰期对持有 1M vs 12M carry 的含义？
