# [Jurek 2009/2014 线] Crash-Neutral Currency Carry Trades

- 深度层级: L3
- 引用链角色: foundational / critique（用期权把 crash 从 carry 中“对冲掉”）
- DOI/URL: SSRN abstract_id=1262934；后续 RFS 发表线 *Crash-Neutral Currency Carry Trades*
- 开放获取: `_pdfs/_ssrn/jurek_crash_neutral_currency_carry_ssrn1262934_mirror.pdf`（first-page OK）
- **PDF 卫生**: `_pdfs/_nber/jurek_crash_w15026.pdf` **误标**——正文为 Caldara et al. *Computing DSGE Models with Recursive Preferences*（NBER w15026），**禁止**当 Jurek 引用
- 本项目映射: carry 左尾/期权对冲成本上界；**非**零售可交易 RR 因子
- 复制状态: fail_closed_missing_data（OTC FX 期权曲面 + 对冲执行）
- 公式置信度: high（作者 SSRN 稿 2009-04）
- published premium vs implementable: 未对冲 carry 高 SR 在扣除 crash 对冲后近似消失（美元中性）；零售无 OTC 对冲腿
- 2016–2025 外推: 危机年（2008 样本内）已显示月度对冲劣于季度；期权流动性与 skew 定价结构会变

## 1. 经济机制

UIP/远期溢价异象使“借低息、投高息”的 G10 carry 历史超额收益与**高 Sharpe、强负偏**并存。Crash-risk 假说：高息货币超额收益是对**大幅贬值（crash）**风险的补偿。Jurek 用 FX 期权在预设阈值外对冲贬值尾部，构造 **crash-neutral** carry：若均值收益主要来自 crash 补偿，则对冲后超额应显著下降/消失。结果支持该叙事——尤其在**美元中性**组合上，对冲后均值统计上不可区分于 0；非美元中性组合仍弱显著且依赖权重。对冲成本差分暗示未对冲收益中仅一部分可归因于可对冲 crash 溢价；2008 显示损失常为**多期连续回撤**而非单跳，故滚动 1M 保护往往贵于更长保护。

## 2. 精确公式

```text
# 报价惯例以正文为准（G10 vs USD）
# CIP: F_{t,τ} = S_t * exp((r_d - r_f)*τ)  # 或市场远期

# 未对冲双边 carry 超额（概念）:
# 做多高息外币、融资低息本币:
# R_CT ≈ exp(r_f * τ) * (S_{t+τ}/S_t) - exp(r_d * τ)
# 等权/利差加权组合: equal- vs spread-weighted

# Crash 定义:
# 汇率冲击超过 (a) 固定阈值 / fixed delta，或 (b) 期权 IV 的倍数

# Crash-neutral:
# 在 carry 上叠加 OTM 保护，消除阈值外贬值
# 对冲频率: monthly vs quarterly（季度对冲年化约高 1–2%）
# 美元中性: 消除净 USD 敞口后再评估

# 关键结果（样本叙述）:
# 1990–2007 等权 ~4.42% 年化超额, vol~5.05%, SR~0.88
# 含 2008 后全样本 SR 降至 ~0.57；负偏约 -1.62（等权月度）
# 美元中性 + crash 对冲后: 超额统计上 ≈ 0
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 币种 | G10：AUD,CAD,CHF,EUR,GBP,JPY,NOK,NZD,SEK,USD |
| 频率 | 月度组合；对冲月/季 |
| 样本 | 核心展示约 1990–2008；期权子样本约 1999–2008 |
| 数据 | 即期/利率或远期；**J.P. Morgan FX 期权** |
| 对照 | Fama–French 与动量总回报指数（同波动缩放） |

## 4. 成本与可实现性

- 原文：期权对冲成本**内生于** crash-neutral 收益（保护费吃掉 carry）
- 迁移：零售无匹配的 OTC 曲面与对冲执行 → **不能**声称“已对冲 crash 仍有 alpha”
- midquote carry SR ≠ 可实现净收益；对冲后为 0 更接近“风险补偿”而非免费午餐

## 5. 识别与稳健性

- 美元中性 vs 非中性：中性后对冲结果更“干净”
- 等权 vs 利差加权：非中性结果对权重敏感
- 对冲期限：季度优于月度（样本内 1–2% 年化）
- 2008 危机窗：对冲规则选择影响存活路径
- 与 peso/罕见灾难叙事一致，但是**可交易对冲**检验而非纯理论

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| G10 即期 + 1M 利率/远期 | 是 | 远期缺 | fail closed / 利率扩展 |
| OTC FX OTM 期权（多期限） | 是 | 无 | fail closed |
| 对冲再平衡与成交价 | 是 | 无 | fail closed |
| 美元中性约束 | 是（主结论） | 可实现于权重 | 仅扩展诊断 |

## 7. 本项目映射

- registry：不作“crash-neutral 精确复制”；作 **carry 左尾否决/成本上界** 文献锚点
- 持有期：1M 信号；对冲频率异质性警告 reused-history
- 否决：用 Cboe 股指 IV/单点 RR 冒充 FX crash hedge；忽略美元中性
- 与 Della Corte VRP/RR、BNP crash、Burnside peso 同簇

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational crash | Brunnermeier–Nagel–Pedersen | 偏度/funding |
| options VRP | Della Corte–Ramadorai–Sarno | 期权隐含排序 |
| peso | Burnside et al. w14054 | 罕见灾难 vs 样本 |
| survey | Burnside ARFE | carry 解释谱 |

## 9. 精读问题（给最强模型）

1. crash 阈值用绝对点 vs σ_IV 倍数，对 2016–2025 结论是否稳健？
2. 季度对冲优势是期权期限结构还是再平衡成本假象？
3. 美元中性约束去掉后，残留收益是 dollar factor 还是 crash？
4. 零售账户用 listed FX 期权能否近似 OTM 保护，缺口多大？
5. 与 HML_FX / 全球 FX vol 因子正交后，crash-neutral 残差是否仍为 0？
