# [Falconio 2016/rev.2021] Carry Trades and Monetary Conditions（ECB WP 1968）

- 深度层级: L3
- 引用链角色: extension（**美国货币条件 × carry 状态依赖**）
- DOI/URL: ECB WP 1968 https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp1968.en.pdf
- 开放获取: `_pdfs/_ecb/ecb_wp1968_carry_trades_monetary.pdf`（first-page OK）
- 本项目映射: carry 的**体制/门控**文献；非新横截面因子
- 复制状态: extension_only（货币条件指标定义）
- 公式置信度: high（ECB WP，2021-12 修订）
- published premium vs implementable: 状态依赖均值/SR；交易成本与零售 swap 未闭合
- 2016–2025 外推: 后 ZLB/QT 体制需样本外重估；不可沿用危机前系数

## 1. 经济机制

Carry 盈利的主流风险解释强调全球 FX 波动与风险厌恶（Menkhoff et al.；BNP）。同时，美国货币政策驱动全球金融周期（Rey 等）。本文将二者相连：在**2008 危机前**，美国扩张性货币条件 → 国际风险厌恶下降 → 货币风险溢价压缩 → **carry 更高收益、更高 SR、更低 downside**。危机与 **ZLB** 期，衰退压制风险承担，美联储宽松**无法**同样压低国际风险厌恶，carry 在货币条件分箱间差异不显著。

## 2. 精确公式

```text
# 货币排序（标准六分位）:
# 按远期贴水/利差将货币分为 P1..P6
# Carry = long P6 − short P1   # 零成本

# 货币条件状态:
# ΔMP_t = 美国货币条件在 t−1 → t 的变化（扩张/紧缩分箱）
# 具体代理以正文为准（政策利率路径/宽松指标等）

# 状态依赖表现:
# 对每个货币条件箱 b:
#   mean(rx_carry | b), SR(b), downside risk(b)
# 危机前: expansive b → 更高 mean/SR、更低 downside
# 危机+ZLB: 箱间差异不显著

# 叙事链:
# US expansion → ↓ international risk aversion → ↓ currency RP → ↑ carry returns
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 策略 | 利率/远期贴水六分位 carry |
| 状态变量 | 美国货币条件变化 |
| 分段 | 危机前 vs 危机+ZLB |
| 频率 | 与组合再平衡一致（典型月度） |
| 修订 | 2021-12 修订版 |

## 4. 成本与可实现性

- 原文：状态依赖风险收益，非执行成本研究
- 迁移：用美联储事件/利率变化做**事前**状态，避免事后标签危机
- 门控降低交易频率时成本结构变化

## 5. 识别与稳健性

- 主结果在危机前显著、危机+ZLB 消失 → 强体制依赖
- 与全球金融周期叙事一致
- 经济价值：货币溢价可预测性是否“有价值”取决于状态定义是否可交易/可预注册

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 远期贴水排序 | 是 | 缺 forward 则扩展 | 标记 |
| 美国货币条件序列 | 是 | 政策利率/路径可构造 | 定义冻结 |
| 危机分段规则 | 是 | 可预注册 | 禁止事后窗 |
| 风险厌恶代理 | 诊断 | VIX 等 | 非必须交易 |

## 7. 本项目映射

- registry：`slow_carry` + **货币条件门控**扩展；门控超参进 FDR
- 否决：全样本估一个“宽松→做多 carry”系数用于 2022–2025
- 与 Moreira–Muir vol 管理、BNP VIX 门控并列，勿三重嵌套无纪律

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| vol risk | Menkhoff et al. JF 2012 | FX vol |
| crash | Brunnermeier–Nagel–Pedersen | 风险厌恶 |
| cycle | Rey / Miranda-Agrippino–Rey | 全球金融周期 |
| related | ECB WP2149 curvy | 信号改造另一路线 |

## 9. 精读问题（给最强模型）

1. 货币条件用联邦基金变化 vs 影子利率 vs 大类资产宽松指数，分箱是否同向？
2. 扩张箱的高 SR 是否集中在少数月份（偏度）？
3. 欧央行/日央行条件是否有增量，还是美元主导？
4. 2022 激进加息体制更像危机前还是新机制？
5. 门控与 vol 目标同时开时如何避免过拟合？
