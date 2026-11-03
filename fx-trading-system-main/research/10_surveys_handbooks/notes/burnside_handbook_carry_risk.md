# [Burnside 2011] Carry Trades and Risk（Handbook of Exchange Rates 章 / NBER w17278）

- 深度层级: L3
- 引用链角色: foundational handbook / risk taxonomy
- DOI/URL: NBER WP 17278；*Handbook of Exchange Rates*（James, Marsh & Sarno eds., Wiley）
- 开放获取: `_pdfs/burnside_carry_risk.pdf`；同文 `_pdfs/_nber/lustig_w17278.pdf`（**文件名误标为 lustig**）
- 本项目映射: carry 风险解释清单；EW vs HML 杠杆差异；货币因子无法统一定价股票
- 复制状态: extension_only / fail_closed_missing_data（forward）
- 公式置信度: high
- published premium vs implementable: 1976–2010 Datastream forward 策略；非零售
- 2016–2025 外推风险: 高（危机后市场 beta 时变、CIP、监管）

## 1. 经济机制

本章回答：carry 的历史正超额收益是否为**风险溢价**？

分层结论：

1. **传统股票因子**（CAPM、FF3、C-CAPM）：与 carry 相关弱；beta 过小，无法合理化均值。  
2. **货币特制因子**（Lustig DOL+HML；Menkhoff VOL；Rafferty 全局 skewness/crash）：在**货币组合横截面**上有解释力，但**不能**定价美股 FF25；股票因子也不能定价货币 → **无统一跨市场风险叙事**（作者不喜欢“完全分割”作为逃逸舱，因其削弱 SDF 可检验性）。  
3. **时变市场风险**：危机中 carry 与股市相关上升，但样本内时变 market beta **不足以**解释 carry 平均收益。  
4. **Peso / 危机风险**仍是开放候选：不是简单“已实现 skewness 很大”（EW/HML 的偏度甚至弱于美股），而是未充分进入样本的状态。

相对 ARFE 综述：本章更集中 **carry-only**，并明确对比 **EW carry**（多币种等权、总赌注 1 USD）与 **HML carry**（S5−S1，有效赌注 2 USD、杠杆更高）。

## 2. 精确公式

```text
# 利率差分支付（USD 为本币；S = USD per FCU）
z_{t+1} = sign(i*_t - i_t) * [ (1+i*_t) S_{t+1}/S_t - (1+i_t) ]

# 远期实施（文中主测）
# 合约规模归一使与 CIP 下利率策略可比：
z_{t+1} = sign(F_t - S_t) * (1+i_t)/F_t * (F_t - S_{t+1})

# CIP:
(1+i_t)/(1+i*_t) = F_t/S_t

# 季度超额（由月度复合）用于消费因子检验
R_t = 1 + i_{t-1} + z_t
z^q_s = R_t R_{t-1} R_{t-2} - R^f_t R^f_{t-1} R^f_{t-2}
z^{q,real}_s = z^q_s / (1+π_s)

# EW carry: 最多 20 币种对 USD 的单币 carry 等权，总赌注 1 USD

# 五分位 S1..S5：含 USD 在内按利率/远期升水排序；
# 组内等权；USD 支付记 0
# HML carry = 多 S5 空 S1（总多空各 1 USD）

# 因子回归
z_t = a + f_t' β + e_t
# GMM: E[m z]=0, m=1-(f-μ)'b
```

**VOL / SKW：** 全局货币已实现波动与已实现偏度（文中引用 Menkhoff、Rafferty 构造）；用于第二套货币因子。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 币种 | 欧元 + 20 国货币（含发达与部分 EM） |
| 频率 | 月末 1M forward；另算季度实值 |
| 样本 | 1976-01 至 2010-10（币种 unbalanced） |
| 来源 | Reuters/WMR、Barclays via Datastream；USD 利率用 French Rf |
| 构造细节 | 早期 GBP 交叉构造 USD 报价；澳新南非用 Barclays 补 1983–1996 |

描述（年化量级，文中 Table I）：

| 组合 | Mean | SD | Sharpe | 备注 |
|---|---|---|---|---|
| 单币种平均 | ~4.6% | ~11.3% | ~0.42 | 截面差异大（如 CHF 低、DKK 高） |
| EW | ~4.6% | ~5.1% | ~0.90 | 分散化 |
| HML | ~6.0% | ~9.5% | ~0.63 | 更高杠杆 |
| 美股 | ~6.3% | ~15.7% | ~0.40 | 对照 |

EW 与 HML 月相关约 0.51；二者与美股相关弱，但 2008–09 共同糟糕。

## 4. 成本与可实现性

- 原文以 forward 策略测支付；讨论 CIP 在危机中的破裂（对手方/流动性）。  
- HML **名义赌注 2 USD** vs EW **1 USD** → 比较均值时必须声明杠杆。  
- 迁到零售：  
  - 缺账户 swap / 可成交 forward → fail closed  
  - 零售无法无摩擦做空一篮子低息货币到学术 HML 深度  
  - 点差与隔夜融资使 EW 的“高 Sharpe”最易被成本打穿  
- 偏度：文中强调组合层 skewness **不一定**比股市更极端 → 不能仅靠样本偏度讲“崩盘溢价已实现”。

## 5. 识别与稳健性

- 传统因子失败：零 beta 或 beta 过小。  
- 货币因子：在 S1–S5 上 R²/定价尚可；加入股票组合后 R² 崩、J 检验拒。  
- 时变 β：滚动窗口显示危机后 market beta 上升，但**样本内**仍解释不了平均 carry。  
- 分割市场假说：作者认为其使 SDF 解释“不可证伪”，故不满意。  
- 对 momentum：指向 ARFE / 相关工作——定价 carry 的因子往往**定不住**短窗 momentum。

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目 | 缺失时 |
|---|---|---|---|
| 1M forward 月末 | 是 | 缺 | fail closed |
| 多币种可得性 | 是 | G9 | extension HML/EW |
| 日数据构 VOL/SKW | 可选 | 可 | 仅机制 |
| 美股因子 | 对照 | 可取 French | 非交易信号 |
| 消费数据 | C-CAPM | 非优先 | 不复制消费检验 |
| 杠杆与保证金 | 实现 | incomplete | 禁止宣称 HML 零售可复制 |

## 7. 本项目映射

| 项 | 映射 |
|---|---|
| EW vs HML | 注册表需写清赌注归一；G9 上 HML 自由度极低 |
| 风险门控 | 时变 beta / VOL 只作状态，不事后挑危机阈值 |
| 否决 | “货币因子已统一资产定价”；用政策利率 HML 冒充实盘 |
| 与 04 | 多因子网格必须把 EW/HML/vol-managed 变体计入试验数 |
| 与 06 | CIP 破坏 → 利率差分回测与远期回测分叉 |

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| survey 姊妹 | Burnside–Eichenbaum–Rebelo ARFE / w16942 | 含 momentum + price pressure |
| foundational | Lustig–Roussanov–Verdelhan | HML_FX |
| vol risk | Menkhoff et al. | VOL |
| crash | Brunnermeier–Nagel–Pedersen；Rafferty SKW | 崩盘因子 |
| boundary | Du–Tepper–Verdelhan | 后危机 CIP |
| 本库 | `02/.../lustig_rfs_2011.md`；`moreira_muir.md`；`06/.../du_tepper_verdelhan_cip.md` | |

## 9. 精读问题

1. 在只有 G9 时，五分位 HML 是否退化为近 2–3 币种赌注？有效自由度与过拟合风险？  
2. 如何把文中“时变 market beta 不足” Formal 成项目门控的**事前**可测统计量？  
3. 若货币因子定价股票失败，项目是否仍允许“仅 FX 内 SDF”？对可交易结论的披露标准应是什么？  
4. EW Sharpe≈0.9 在扣零售点差+swap 后，达到 DSR 显著需要怎样的均值保留比例？  
5. 把 HML 与 EW 同时送入 SPA 时，共享成分如何处理以免伪独立？
