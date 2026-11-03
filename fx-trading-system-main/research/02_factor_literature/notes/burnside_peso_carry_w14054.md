# [Burnside, Eichenbaum, Kleshchelski & Rebelo 2011] Do Peso Problems Explain the Returns to the Carry Trade?

- 深度层级: L3
- 引用链角色: foundational / critique（传统风险因子失败 → peso/期权隐含 SDF）
- DOI/URL: RFS 2011；NBER w14054 https://www.nber.org/papers/w14054
- 开放获取: `_pdfs/_nber/burnside_peso_carry_w14054.pdf`
- 本项目映射: carry 左尾/灾难定价边界；**非**方向信号；期权对冲 carry 用于识别而非交易 alpha
- 复制状态: fail_closed_missing_data（1M forward + CME/OTC 期权）
- 公式置信度: high（NBER WP 修订版全文）
- published premium vs implementable: 未对冲 carry 平均支付高；**对冲后**平均支付显著下降 → 样本内“免费午餐”部分是未实现坏状态的定价
- 2016–2025 外推: peso 叙事仍相关，但 2008 已部分实现；不能把历史期权溢价直接当零售净收益

## 1. 经济机制

Carry（借低息贷高息 / 卖升水买贴水）平均支付为正，且与消费、股市、Fama–French 等**传统风险因子无显著无条件相关**，故线性 SDF 解释失败。作者主张 **peso problem**：样本内几乎未实现的状态上，SDF \(M\) 极高且 carry 支付为负；定价方程要求非 peso 样本的风险调整平均支付为正。关键识别：**不是**要求 peso 状态有“极端负支付”本身，而是要求该状态 **\(M_0\) 足够大**。用 **ATM 期权对冲后的 carry** 把坏状态支付截断，再与股票市场对冲策略对照，反推 peso 状态的 \(M_0\) 与损失规模，发现与“高边际价值状态”一致。

## 2. 精确公式

约定：\(S_t\) 为 **USD per FCU**；\(F_t\) 1M 远期；\(r_t,r^*_t\) 美元/外币利率。

```text
# 利率差分 carry（归一 1 USD 赌注；yt 为美元借款量符号）
payoff = yt * [ (1+r*_t)*S_{t+1}/S_t - (1+r_t) ]
yt = +1 if r_t < r*_t else -1

# 远期等价实施（CIP 下与上式成比例；文中主用）
wt = +1/F_t if F_t ≥ S_t else -1/F_t   # 卖/买 1 USD 名义的 FCU 远期
z_{t+1} = wt * (F_t - S_{t+1})

# CIP:
(1+r_t) = (F_t/S_t)*(1+r*_t)

# 零净投资定价:
E_t[ M_{t+1} z_{t+1} ] = 0
⇒ E[z] = -cov(M,z)/E[M]

# 两状态 peso 分解（非 peso 集 Ω_N，peso 集 Ω_P，概率 p）:
# 简化: peso 状态 z=z0<0, M=M0
(1-p) E_N[M z] + p M0 z0 = 0

# 期权:
call 净支付 zC = max(0, S_{t+1}-K) - C_t(1+r)
put  净支付 zP = max(0, K-S_{t+1}) - P_t(1+r)

# 对冲 carry（hedged carry）:
# 若 F≥S（卖 FCU 远期）: 买 1/F 份 call
# 若 F<S （买 FCU 远期）: 买 1/F 份 put
zH_{t+1} = z_{t+1} + zC_{t+1}/F_t   if F≥S
         = z_{t+1} + zP_{t+1}/F_t   if F<S

# 最小对冲支付（期权实值时）:
h = -P(1+r)/F   if F≥S
  = -C(1+r)/F   if F<S     # 恒为负（期权费）

# 由对冲/未对冲矩反推 peso 损失（文中式）:
z0 = E_N[h] * E_N[M z] / E_N[M zH]     # 概念形式；实现用样本矩+风险调整
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 主要发达市场货币 vs USD（与 w12489 一脉） |
| 频率 | 月度（远期一月） |
| 样本 | 约 1980s–2000s（期权子样本受 CME 货币期权可得性约束） |
| 价格 | spot + 1M forward；CME 货币期权（作者致谢 CME） |
| 对照 | 股市多头 + ATM put 对冲策略，用于独立估计 peso 态 \(M_0\) |

## 4. 成本与可实现性

- 原文：指示性点差/期权费进入对冲策略；重点是**识别**而非卖零售产品
- 迁移：OTC RR/25Δ 与 CME 上市期权不同；零售无对应 ATM 货币期权簿
- mid ≠ net：对冲后平均支付下降本身说明“毛 carry”含灾难保险费

## 5. 识别与稳健性

- 未对冲 carry：高平均支付、与传统因子相关≈0
- 对冲 carry：平均支付大幅降低（付保险费）
- 与对冲股市策略得到的 \(M_0\) 估计相近 → 支持共同 peso 态高 SDF
- 多 peso 状态扩展：定性结论稳健
- 边界：若样本已实现 2008 类崩溃，peso 解释权重下降、已实现风险解释上升（与 BNP crash、Menkhoff VOL 对话）

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 1M forward | 是 | 缺 | fail closed |
| 货币期权 ATM 价 | 是（对冲识别） | 无 | fail closed 本文识别 |
| 传统风险因子序列 | 对照 | 部分可得 | extension |
| 实现偏度/VIX | 相关但不充分 | 有 | 不能替代期权 SDF |

## 7. 本项目映射

- registry：不新增“peso 因子”；用于 **否决**“无条件高 SR=可交易 alpha”
- 持有期：1M
- 否决：把期权隐含 skew 当无成本方向信号反转；无期权却声称已排除 peso
- reused-history：任何“灾难门控”超参搜索计入 FDR

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | w12489 Returns to Currency Speculation | 前身 |
| theory | Farhi–Gabaix rare disasters | 灾难定价结构 |
| crash | Brunnermeier–Nagel–Pedersen | 已实现左尾 |
| survey | Burnside ARFE 2011 | 把 peso 与价格压力并列 |

## 9. 精读问题（给最强模型）

1. 2016–2025 已实现多次 carry 平仓，peso 概率 \(p\) 应如何用期权重估？
2. 用 risk reversal 代替 ATM 对冲，识别的 \(M_0\) 偏差方向？
3. CIP 失败后，利率差分与远期实施支付不成比例时，peso 分解如何改写？
4. 对冲 carry 的负平均是否已被期权做市商风险溢价主导？
5. 项目若只有 VIX/实现 vol，最多能做哪种**弱** peso 诊断？
