# [Asness, Moskowitz & Pedersen 2013] Value and Momentum Everywhere

- 深度层级: L3
- 引用链角色: replication（跨资产统一 value/mom；FX 子结果）
- DOI/URL: https://doi.org/10.1111/jofi.12021
- 开放获取: 作者页 PDF（Stern）https://w4.stern.nyu.edu/facdir/lpederse/papers/ValMomEverywhere.pdf ；AQR 相关数据页
- 本项目映射: FX **5y PPP value** + **12-1 momentum** 统一权重合同；与 menkhoff_rfs_value / menkhoff_jfe_2012_mom 对照
- 复制状态: extension_only（CPI vintage、持有期、成本；FX 子集可探索）
- 公式置信度: high（JoF 作者 PDF 全文）
- published premium vs implementable: 跨资产 50/50 value+mom 强；FX 单独仍有溢价；未扣零售 swap
- 2016–2025 外推风险: 中高。样本至 2011；后危机价值因子普遍承压

## 1. 经济机制

价值与动量在**八类市场**（美/英/欧/日个股、国别股指、国债、**货币**、商品期货）普遍存在正溢价；同类策略跨市场高度共变，而 value 与 momentum **负相关**。这支持全球共同风险（部分来自**融资流动性**：momentum 正暴露、value 负暴露），也挑战仅服务美股企业投资/行为模型的局部解释。对 FX：动量是短期相对收益延续；价值是**长期实际汇率均值回复（PPP）**。50/50 组合更接近有效前沿且对单一流动性风险更免疫。

## 2. 精确公式

```text
# 货币宇宙（10 发达）: AUD, CAD, DEM/EUR, JPY, NZD, NOK, SEK, CHF, GBP, USD
# 收益: 美元计，含利差（forward 或 spot+LIBOR）

# Momentum（全资产统一）
MOM_signal_{i,t} = return_{i,t-12→t-1}     # 过去 12 个月，跳过最近 1 个月
# 跳过最近月为与股票统一；FX 不跳过更强 → 文中结果偏保守

# Value（货币专用，5 年 PPP 变化）
# “负的 5 年汇率收益 + 通胀差调整”
# 用 4.5–5.5 年前平均 spot 平滑“账面”
spot_long = average(S_{t-5.5y : t-4.5y})
Value_FX = - [ log(spot_long / S_t) - (Δlog CPI* - Δlog CPI_US)_{same window} ]
# = 5 年实际汇率变化意义上的“便宜度”
# 高 Value → 外币实际贬值过多 → 更“便宜”

# 组合权重（rank 多空）
rank_i = cross-sectional rank(signal_i)
w_i ∝ rank_i - mean(rank)
# 缩放: 多头$1/空头$1 或 10% 事前年化波动目标
# 月度再平衡；value 与 mom 可 50/50 组合

# 三因子基准（全球）
# MKT_global + VALUE_everywhere + MOM_everywhere
```

早期 WP 版本曾用含利差的 5 年 UIP 偏离作 value；**发表 JoF 版以 CPI 调整 PPP 为准**。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | FX：10 发达货币对 USD |
| 频率 | 月度 |
| 样本起止 | 约 1979-01 至 2011-07（随资产类不同起点） |
| 价格来源 | Datastream spot；forward 或 LIBOR 构超额收益；CPI 通胀 |
| 排序与再平衡 | 月度 rank 权重；全样本与分市场报告 |

## 4. 成本与可实现性

- 原文：主结果偏毛收益/波动缩放；跨资产比较优先于微观成本
- 迁移破坏点：
  1. CPI **current vintage** 破坏严格 PIT（与 menkhoff_rfs_value 相同族问题）
  2. 5 年窗口对 G9 小样本噪声大
  3. 12-1 mom 换手 + 零售点差
- midquote ≠ net：50/50 降低换手但仍非账户净

## 5. 识别与稳健性

- 主结果：FX value 与 FX mom 均正溢价；跨资产 value（mom）正相关；value–mom 负相关
- 流动性：funding liquidity 部分解释共变；不能解释 value 正溢价本身
- 控制：三因子可价格美股 FF 组合与部分对冲基金指数
- 衰减：2010s 全球 value 弱；需新前向

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 月度 spot 长历史 | 是 | Dukascopy/扩展 partial | extension |
| 5y CPI 双边 + vintage | 是（精确 value） | 缺严格 vintage | extension_only |
| 1M forward 或 LIBOR 超额 | 是 | forward 缺 | 仅 spot mom/value 为 extension |
| rank 权重与 vol 目标 | 是 | 可实现 | 预注册缩放 |
| 融资成本 | 实现层 | incomplete | cost_incomplete |

## 7. 本项目映射

- registry：`fx_value_5y_ppp`（对照 `menkhoff_rfs_value` REER）；`fx_mom_12_1`（对照 menkhoff 多 horizon）
- 持有期：月度；项目日度 sleeve 为扩展
- 否决：REER 与 5y PPP 混为同一试验；无 CPI 时用名义 5y 收益冒充发表版 value
- 与 menkhoff_rfs_value：后者更偏宏观净化 REER；Asness 为统一跨资产 5y 实际汇率

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Jegadeesh–Titman / DeBondt–Thaler | mom / 长期反转 |
| replication | Menkhoff et al. (JFE 2012 mom; RFS value) | FX 专向加深 |
| joint | 本文 | 跨资产共变与三因子 |
| boundary | Moskowitz, Ooi & Pedersen (TSMOM) | 时间序列动量平行 |
| boundary | funding liquidity 文献 | 部分共变源 |

## 9. 精读问题（给最强模型）

1. G9 上 5y PPP value 与 BIS REER value 秩相关与净收益差多少？
2. 跳过 vs 不跳过最近月对 FX mom 在 2016–2025 的净 Sharpe？
3. 50/50 value+mom 是否降低对账户 swap 符号错误的敏感性？
4. rank 权重 vs 三分位等权：FDR 族应如何拆分？
5. CPI 仅用 final vintage 时，严格 PIT 下 value 是否仍显著？
