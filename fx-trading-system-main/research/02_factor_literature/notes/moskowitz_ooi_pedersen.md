# [Moskowitz, Ooi & Pedersen 2012] Time Series Momentum

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1016/j.jfineco.2011.11.003
- 开放获取: 作者页/Stern PDF https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
- 本项目映射: 单资产 TS momentum；与横截面 MOM 区分
- 复制状态: extension_only（期货收益、vol 目标、重叠持有）
- 公式置信度: high（JFE 作者 PDF）
- published premium vs implementable: 期货样本高 Sharpe；FX 子集仍显著但需扣点差/展期
- 2016–2025 外推: CTA 拥挤与波动目标产品普及 → 衰减风险中等偏高

## 1. 经济机制

**时间序列动量**：资产自身过去 1–12 个月超额收益的符号预测未来收益（趋势延续），更长 horizon 部分反转。主要来自收益**自协方差**，而非横截面相对排序。与投机者仓位同向、对冲者反向一致。行为 underreaction + 延迟 overreaction 与部分理性理论均可讨论，但论文以广泛资产类实证为主。

## 2. 精确公式

```text
# 事前年化方差（EWM 日收益，无前视；用于 t 的仓位时用 σ_{t-1}）
σ²_t = 261 * sum_{i=0..∞} (1-δ) δ^i (r_{t-1-i} - r̄_t)²
# center of mass: δ/(1-δ) = 60 日

# 可预测性回归（波动缩放）
r^s_t / σ^s_{t-1} = α + β_h * (r^s_{t-h} / σ^s_{t-h-1}) + ε
# 或符号形式:
r^s_t / σ^s_{t-1} = α + β_h * sign(r^s_{t-h}) + ε
# h = 1..12 为正；更长为负（反转）

# 交易策略（主规格 lookback k=12，hold h=1）
# 过去 k 月超额收益 >0 做多，<0 做空
# 仓位与 1/σ_{t-1} 成正比，使各工具目标波动一致
# 论文实现：每工具目标约 40% 年化波动规模（组合分散后总 vol 约 10% 量级）
r^{TSMOM,s}_{t,t+1} = sign(r^s_{t-12,t}) * (target_vol / σ^s_{t-1}) * r^s_{t,t+1}

# 多 lookback/hold 组合：重叠投资组合平均（JT 风格）
# 资产类等权/风险平价聚合
```

FX：货币远期/期货超额收益（含利率/展期成分），非纯 spot。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产 | 58 个期货：商品、股指、债券、**货币远期** |
| FX 腿 | AUD, EUR, CAD, JPY, NOK, NZD, SEK, CHF, GBP vs USD 等 |
| 频率 | 月度策略；日度估 vol |
| 样本 | 最长达 1965–2009；FX 多自 1970s |
| 再平衡 | 月度信号与持有 |

## 4. 成本与可实现性

- 原文：期货/远期；讨论成本后仍有利润（细节因资产而异）
- 迁移到零售 FX：
  - 无交易所期货时用 spot+swap 近似展期
  - 波动目标导致杠杆时变 → 融资与爆仓约束
  - 重叠持有需**资本守恒 sleeve**（项目已强调）
- midquote 趋势 ≠ 净成本趋势跟踪

## 5. 识别与稳健性

- 几乎所有工具 12-1 TSMOM 为正平均收益
- 相对市场/债券/商品/ SMB/HML/UMD 有 alpha；与横截面动量相关但不相同
- 极端市场表现相对好（论文叙事）
- 分解：利润主要来自 auto-covariance

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 日度超额收益（含融资） | 是 | forward/swap 缺 | spot-only extension |
| EWM vol（60 日质心） | 是 | 可算 | 规格冻结 |
| sign(过去 k 月收益) | 是 | 可算 | — |
| target vol / 杠杆上限 | 是 | 需账户约束 | 无上限则不可实现 |
| 重叠持有会计 | 是 | sleeve 框架 | 否则高估资本效率 |
| 多资产分散 | 原文关键 | 仅 FX | FX-only extension |

## 7. 本项目映射

- registry：TS momentum / trend 状态
- 持有期：12-1 主规格；项目多 horizon 网格需进 FDR
- 否决：用未收盘价格；重叠双计收益；无杠杆上限的“纸面 40% vol”
- reused-history：是

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Jegadeesh-Titman；趋势跟踪 CTA 文献 | 方法与实践 |
| parallel | Menkhoff et al. (2012) 横截面货币动量 | 对照 |
| joint | Asness et al. (2013) | 跨资产 |
| sizing | Moreira & Muir (2017) | 另一类 vol 管理 |

## 9. 精读问题

1. FX 子集上 12-1 与 1-1、3-3 的净成本后排序？
2. \(\sigma\) 用 mid 收益还是 ask-bid 成交收益估，仓位差多少？
3. 资本守恒下 12 个重叠月 sleeve 的真实杠杆路径？
4. TSMOM 与横截面 MOM 在 G9 的相关是否高到应合并检验族？
5. 2016–2025 波动目标基金增长是否削弱 TSMOM？
