# [Itskhoki & Mukhin 2017] Exchange Rate Disconnect in General Equilibrium

- 深度层级: L3
- 引用链角色: foundational theory / boundary（宏观 disconnect 与 UIP 统一框架）
- DOI/URL: NBER w23401 https://www.nber.org/papers/w23401 ；发表线 AER 2021
- 开放获取: `_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf`（首页校验：*Exchange Rate Disconnect in General Equilibrium*, May 2017）
- 误标警告: `_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w27847.pdf` **不是**本文，正文为 Hassan–Zhang w27847
- 本项目映射: 解释边界——基本面弱相关 ≠ 可交易 alpha；金融/资产需求冲击主导汇率时，因子应偏风险溢价/中介而非短窗 PPP
- 复制状态: extension_only（理论/校准模型；无交易策略表）
- 公式置信度: high（NBER WP 全文）
- published premium vs implementable: 不提供策略 premium
- 2016–2025 外推: disconnect 仍是默认；价值/宏观缺口类信号需长持有 + vintage 纪律

## 1. 经济机制

广义 *exchange rate disconnect* 同时覆盖：Meese–Rogoff（名义汇率近随机游走、与宏观基本面弱相关）、PPP/Mussa（实际汇率跟踪名义、高波动高持续）、贸易条件相对实际汇率低波动、Backus–Smith（相对消费与实际汇率相关符号/幅度失败）、Fama UIP/forward premium。作者证明：在一般均衡中，**唯一**能在近自给经济极限下仍产生大幅汇率波动、却对国内量价利率影响趋于零的驱动冲击，是**国际资产需求（金融）冲击**——可微基础为噪声交易+有限套利、异质信念、金融摩擦（如 Gabaix–Maggiori）或时变风险溢价。传递机制则由微观估计约束：消费 home bias、战略互补定价→LOP 违反、国内外商品弱替代、稳定国内通胀的货币政策。名义粘性改善定量表现但**非** disconnect 必要条件。对因子研究：慢周期“价值”若存在，应理解为均衡重置/风险，而非无摩擦 PPP 套利；carry/UIP 溢价与金融状态共变，危机时同步恶化。

## 2. 精确公式

```text
# 实际汇率（示意）
Q_t = S_t P*_t / P_t

# Disconnect 诊断矩（文中 Table 2 类目标）:
# corr(Δs, Δmacro) 低；σ(Δs) 大；RER 半生约 3–5 年
# Backus-Smith: corr(c-c*, q) 弱/负
# UIP: E_t[Δs_{t+1}] ≠ i_t - i*_t  （forward premium / risk premium）

# 驱动冲击（唯一通过 near-autarky 诊断）:
# 国际资产需求冲击 ξ_t（小而持续）
# 对外国资产需求↑ → 本币即期大幅贬值 + 此后缓慢升值路径
# 预期升值提高本币资产相对回报 → 出清资产市场
# 跨期预算：未来升值路径由冲击当期意外贬值平衡
# ξ 越持续 → 初始贬值越大 → s 更接近随机游走

# 传递（商品侧）:
# home bias + pricing-to-market (strategic complementarities)
# + 低替代弹性 → 限制支出切换与价格/贸易条件对 s 的响应

# UIP 冲击同构: 资产需求冲击 ≈ UIP shock（Devereux–Engel, Kollmann 等）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 类型 | 动态一般均衡理论 + 定量校准；非交易回测 |
| 经验锚 | 发达市场浮动汇率时代 disconnect 矩（Table 2） |
| 扩展 | 多冲击方差分解：金融冲击解释大部分汇率波动；货币/生产率有限 |
| 策略表 | 无 |

## 4. 成本与可实现性

- 无交易成本讨论
- 迁移：任何“宏观缺口/PPP”信号必须声明 **PIT vintage** 与持有期；短窗基本面回归默认否决
- midquote premium 不适用

## 5. 识别与稳健性

- 理论选择：near-autarky 极限作为冲击筛选器
- 单冲击基准即可匹配 disconnect 矩；多冲击校准后金融冲击仍主导
- 名义粘性 + Taylor 规则：定量稳健
- 与 Mussa、Engel risk-premium 扩展在文中后续处理
- 已知边界：非分割市场无套利模型的偏好无关条件见 Lustig–Stathopoulos–Verdelhan 期限结构文

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 正确 disconnect PDF (w23401) | 精读 | **有** | — |
| REER / 相对价格 | value 扩展 | 部分 | vintage → extension |
| 金融冲击代理（VIX/美元/basis/中介） | 叙事对照 | 部分 | 预注册状态变量 |
| 交易策略权重 | 否（本文无） | — | — |

## 7. 本项目映射

- registry：约束 `currency_value` / 宏观缺口类实验预期；支持“金融状态 > 同期宏观”叙事
- 持有期：若做 PPP/BEER 半生，应用年/多年而非日内
- 否决：把 Meese–Rogoff 失败反向解释为“宏观因子高频可交易”
- 与地图笔记：`itskhoki_real_exchange_disconnect_map.md`（w28225）互补；**本注为正典 disconnect 原文**

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational facts | Meese–Rogoff；Fama UIP；Obstfeld–Rogoff six puzzles | 目标矩 |
| transmission | Atkeson–Burstein；Gopinath 等定价 | 微观传递 |
| finance twin | Gabaix–Maggiori；Farhi–Gabaix | 金融冲击微基础 |
| survey twin | Itskhoki w28225 | 叙述综合 |

## 9. 精读问题（给最强模型）

1. 资产需求冲击与零售 carry 的 funding/swap 摩擦在识别上如何区分？
2. 多冲击方差分解中“金融冲击占比”对 2010 后 CIP 常态偏离是否改变？
3. 若 RER 半生 3–5 年，项目 21/63 日价值因子在理论上应有何先验？
4. near-autarky 诊断能否用于否决“生产率冲击驱动 G9 carry”的叙述？
5. disconnect 与订单流/微观结构文献如何并存（Evans–Lyons vs 宏观矩）？
