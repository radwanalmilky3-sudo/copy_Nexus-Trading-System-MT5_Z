# [Burnside, Eichenbaum & Rebelo 2011] Carry Trade and Momentum in Currency Markets（ARFE survey）

- 深度层级: L3
- 引用链角色: foundational survey
- DOI/URL: https://doi.org/10.1146/annurev-financial-102710-144913 ；NBER WP 16942
- 开放获取: `_pdfs/burnside_arfe_survey.pdf`（与 `_pdfs/_nber/burnside_eichenbaum_rebelo_carry_momentum_w16942.pdf` 同文）
- 本项目映射: carry / momentum 解释谱系；**不是**零售可实现净收益证明
- 复制状态: extension_only（组合定义可对照） / fail_closed_missing_data（1M forward + 成本）
- 公式置信度: high（NBER WP 全文）
- published premium vs implementable: 文中 1976–2010 等权 carry/momentum **毛/学术成本口径**；≠ 零售 bid/ask + account swap
- 2016–2025 外推风险: 高。CIP 常态偏离、Basel/Volcker、定盘改革、零售点差结构均改变；文中 CIP≈成立的等价性论证需用 Du–Tepper–Verdelhan / Borio 更新

## 1. 经济机制

综述两条经典货币投机策略的**支付性质**，并系统评估三类解释：

1. **风险补偿**：平均超额收益来自对 SDF 风险因子的暴露。  
2. **稀有灾难 / peso**：样本内平均收益被未充分实现的坏状态抬高；期权隐含 SDF 在“中等损失 + 高边际价值”状态上定价。  
3. **价格压力（price pressure）**：可交易价格依赖数量，边际交易利润可为零而**平均**利润仍为正——观察者若把平均当边际会误判“桌上有钱未捡”。

核心经验判断（作者口径）：

- 传统股票风险因子（CAPM、FF3、C-CAPM 等）**不能**定价 carry 与 momentum 的平均支付（beta 近零或经济上过小）。  
- 为 carry 组合特制的货币因子（DOL + HML_FX，或 DOL + VOL）能拟合按 forward discount 排序的组合，但**不能**同时解释 momentum。  
- 2008 危机**不能**单独充当“同时杀死 carry 与 momentum 的稀有灾难”：危机中 momentum 仍赚钱 → 联合策略的 peso 叙事被削弱。  
- 价格压力给出“平均正、边际零”的微观一致图景，但是否在 FX 中经验成立仍开放。

## 2. 精确公式

约定：\(S_t\) 为 **USD per FCU**；\(i_t\) 美元无风险利率；\(i^*_t\) 外币利率；\(F_t\) 一月远期。

```text
# 做多外币（借美元、贷外币）的超额支付（忽略交易成本）
z^L_{t+1} = (1 + i*_t) * S_{t+1}/S_t - (1 + i_t)

# 利率差分 carry（sign 规则）
z^C_{t+1} = sign(i*_t - i_t) * z^L_{t+1}

# 远期实施（卖出 forward premium 货币 / 买入 forward discount 货币）
z^F_{t+1} = sign(F_t - S_t) * (F_t - S_{t+1})
# 文中另一归一化：合约规模 (1+i_t)/F_t 时与利率差分在 CIP 下成比例

# CIP:
(1+i_t)/(1+i*_t) = F_t / S_t
# ⇒ CIP 成立时 z^C 与 z^F 成比例（符号一致）

# 等权 carry 组合：各币种对 USD 的 carry 等权，总赌注归一为 1 USD

# 动量（相对自身近期盈利方向；非纯横截面相对排序）
# 文中 ℓ=1 月：若上月做多外币盈利则继续做多
z^M_{t+1} = sign(z^L_t) * z^L_{t+1}

# 等权 momentum 组合：同上，多币种等权

# 按 forward discount 排序的 S1–S5（与 Lustig 等一致）
# DOL = mean(S1..S5)
# HML_FX = S5 - S1

# 全球货币波动 VOL：当月各币种对 USD 日对数收益标准差的横截面平均

# 线性 SDF / 定价（GMM）
E[m_{t+1} z_{t+1}] = 0
m = 1 - (f - μ)' b
# 时序 beta: z_t = a + f_t' β + e_t
# 横截面: E[z] ≈ β' λ
```

**50-50 策略：** 等权 carry 与等权 momentum 再等权混合；文中显示分散化后 Sharpe 更高、与单一策略相关但不完全重合。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 最多约 20 主要币种 vs USD |
| 频率 | 月末（日数据取月末） |
| 样本 | 约 1976-02 至 2010-12 |
| 价格/远期 | Datastream 等；spot + 1M forward |
| 股票对照 | 美股超额收益 |
| 排序 | forward discount 五分位；等权 carry / momentum |

关键描述统计（年化，文中 Table 1 口径）：

| 策略 | Mean | SD | Sharpe | 备注 |
|---|---|---|---|---|
| 等权 carry | 4.6% | 5.1% | 0.89 | 分散化显著降波 |
| 等权 momentum | 4.5% | 7.3% | 0.62 | 与 carry 相关低（约 0.10） |
| 50-50 | 4.5% | 4.6% | 0.98 | 混合 |
| 美股 | 6.5% | 15.7% | 0.41 | 对照 |
| 单币种 carry 平均 | 4.6% | 11.3% | 0.42 | 波动约为组合 2× |

## 4. 成本与可实现性

- 原文：策略定义层多抽象交易成本；CIP 讨论承认危机后显著偏离（流动性/对手方）。  
- **破坏点（迁到本项目）：**  
  1. 无真实 1M forward bid/ask 或账户 swap → 不能宣称 BER 式 carry 复制。  
  2. CIP 不成立时，利率差分 carry ≠ 远期 carry（与项目 fail-closed 一致）。  
  3. 等权多币种月度换手 + 零售点差可能吞噬学术 Sharpe。  
  4. 价格压力叙事意味着**可扩展容量有限**；零售账户规模小，但不能把学术平均收益当边际可扩收益。  
- midquote premium ≠ implementable net：**成立**。

## 5. 识别与稳健性

- **传统因子：** CAPM / FF3 / quadratic CAPM / C-CAPM 等对 carry、momentum 的 beta 多不显著；FF 对 carry 的市场 beta 虽显著但极小（≈0.045），隐含期望收益远低于样本均值。  
- **货币特制因子：** DOL+HML_FX 对 S1–S5 拟合好（构造性成分重）；对 momentum beta 不显著。DOL+VOL：高息货币对波动上升更脆弱（VOL beta 在 S5 为负）。加入 momentum 作测试资产后，货币因子模型对 momentum 定价误差大。  
- **Peso / 期权：** 主张“中等损失 + 高 SDF”而非样本内巨大崩溃单独解释。  
- **危机：** 2008 对 carry 差、对 momentum 不构成同向灾难。  
- **已知失败模式：** 把 HML_FX 当“已发现统一 SDF”、忽略 momentum 正交；把危机后一段当稀有灾难充分实现。

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 月末 spot | 是 | Dukascopy 可构造 | 无 bid/ask 则净收益 fail closed |
| 1M forward 或账户 swap | 是 | 缺 | **fail_closed_missing_data** |
| 币种宇宙与可得性日历 | 是 | G9 子集 | extension_only |
| 日收益→VOL 因子 | 可选 | 可构造 | 仅机制对照 |
| 期权隐含 SDF | 否（本项目） | 无 OTC smile 全截面 | 不复制 peso 期权检验 |
| 零售融资历史 | 实现层 | incomplete | 禁止正式净 PnL |

## 7. 本项目映射

| 项 | 映射 |
|---|---|
| registry | `slow_carry`、动量族（XS/TS）解释框架 |
| 持有期 | 文中 1M；项目 21/42/63 为扩展 |
| 否决 | 政策利率伪 F；无成本宣称 ARFE 表内 Sharpe；用 2008 单独证伪/证实 peso |
| 验证 | 任何 carry+mom 联合需完整试验数 + 成本后矩阵（04） |
| reused-history | 2016–2025 已多轮查看 → 结果按 reused 处理 |

## 8. 引用链（2–5 篇 + 本库笔记）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Fama 1984；Bilson 1981 | UIP / forward premium 起源 |
| foundational | Lustig–Roussanov–Verdelhan | DOL/HML_FX |
| foundational | Menkhoff et al. JF 2012 | VOL 风险 |
| crash | Brunnermeier–Nagel–Pedersen | 负偏与融资 |
| handbook 深化 | Burnside w17278 | 风险因子分类加细 |
| boundary | Du–Tepper–Verdelhan；Borio BIS | CIP 合同 |
| 本库 | `02/.../lustig_rfs_2011.md`；`menkhoff_jfe_2012_mom.md`；`brunnermeier_nagel_pedersen.md` | 单篇下钻 |

## 9. 精读问题（给最强模型）

1. 在 CIP 系统性偏离下，文中 \(z^C\) 与 \(z^F\) 的比例关系如何断裂？零售 tom-next 更接近哪一侧？  
2. 为何 DOL+HML_FX 对 S1–S5 的高 \(R^2\) 不能被解读为“已发现真实 SDF”？（构造性 vs 外生风险）  
3. 价格压力例子中，平均利润与边际利润分离对**回测容量假设**意味着什么？  
4. 若只交易 G9 且强制净点差，等权 carry 的 Sharpe 从 0.89 衰减到什么量级才应 fail closed？  
5. 50-50 carry+momentum 在项目 FDR 族中应算 1 个预设组合还是 2 个因子的事后混合？
