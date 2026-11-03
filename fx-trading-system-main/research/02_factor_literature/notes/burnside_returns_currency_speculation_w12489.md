# [Burnside, Eichenbaum, Kleshchelski & Rebelo 2006/2008] The Returns to Currency Speculation

- 深度层级: L3
- 引用链角色: foundational（carry 支付性质 + 交易成本/价格压力边界）
- DOI/URL: NBER w12489 https://www.nber.org/papers/w12489 ；后续大幅修订为 RFS 2011 的 peso 文（w14054）
- 开放获取: `_pdfs/_nber/burnside_eichenbaum_rebelo_carry_trade_w12489.pdf`（= `burnside_returns_currency_w12489.pdf`）
- 本项目映射: carry 毛收益对照；**平均 Sharpe ≠ 边际可实现**；点差随规模上升 + order-flow 价格压力
- 复制状态: fail_closed_missing_data（1M forward bid/ask 全样本）/ extension_only（spot+利率近似）
- 公式置信度: high（NBER WP 全文）
- published premium vs implementable: 文中指示性 bid/ask 后 SR 仍高；但规模依赖点差与价格压力可把**边际** SR 压到 0
- 2016–2025 外推风险: 高。零售点差、swap、CIP 常态偏离与电子做市结构均变

## 1. 经济机制

Forward premium puzzle / UIP 失败意味着：远期升水货币往往继续贬值不足或升值，于是卖升水、买贴水的 **carry / forward 投机** 有正平均支付。本文核心不是再证明 β 回归，而是刻画这些策略支付的**矩性质**，并问：高 Sharpe 是否风险补偿？经验上支付与传统消费/股市/FF 因子几乎不相关 → 不能用教科书风险解释。那么为何套利不把机会抹平？作者给出两条**摩擦**通道：（i）bid–ask 随订单规模上升；（ii）微观结构 **price pressure**（净订单流推动汇率）。二者合起来使**平均** SR 可为正而**边际** SR 可为 0——观察者把平均当边际会高估“桌上还有钱”。

## 2. 精确公式

约定：汇率为 **FCU per GBP**（文中以英镑为计价锚）；\(F_t,S_t\) 一月远期/即期；\(r_t,r^*_t\) 本币/外币利率。

```text
# CIP（无摩擦）
(1 + r_t) = (F_t / S_t) * (1 + r*_t)

# 利率差分 carry（借低息、贷高息；归一 yt 英镑借款规模）
# 英镑支付:
payoff_interest ≈ yt * [ (1+r*_t)*S_{t+1}/S_t - (1+r_t) ]

# 远期实施（文中主策略；成本更低、样本更长）
# 卖出 forward premium 货币 / 买入 forward discount 货币
# 若以 xt 为卖出的英镑远期名义:
z_{t+1} = xt * (F_t - S_{t+1})     # 英镑计价支付

# 符号规则（无点差）:
# sell FCU forward when F ≥ S (forward premium);
# buy FCU forward when F < S  (forward discount)
# 组合层: 多币种等权，总赌注归一为 1 单位本币

# 有点差版本（概念）:
# 成交价用 ask/bid 对应方向；只有预测支付超过点差才开仓
# “carry without TC” vs “carry with TC” 两套结果并列表

# BGT 策略（Bilson–Fama–BGT 回归预测）:
# 回归: (F_t - S_{t+1})/S_t = a + b*(F_t - S_t)/S_t + e
# 递归估计 â_t, ˆb_t（滚动/递归，首窗约 30 点）
# 当预测 E_t[F-S_{t+1}] > 0 时卖出远期，否则买入
# 同样分 with/without bid-ask

# 价格压力含义（定性）:
# 边际单位投机的预期收益随净订单流规模下降
# ⇒ average SR > 0 可与 marginal SR ≈ 0 共存
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | BEF, CAD, FRF, DEM, ITL, JPY, NLG, CHF, GBP, USD（对 GBP） |
| 频率 | 日数据压成**非重叠月度**（1M/3M） |
| 样本起止 | 即期/远期约 1976-01–2005-12；利率约 1981–2005 |
| 价格/远期/利率 | Datastream 银行间 **bid/ask** spot + 1M/3M forward + 利率 |
| 排序与再平衡 | 按 forward premium 符号方向；等权多币种；月度 |

## 4. 成本与可实现性

- 原文扣除：指示性 bid/ask（with TC 版本）；**无**零售 overnight swap 账户条款
- 迁移破坏点：零售点差非线性、最小手数、swap 与银行间 1M forward 期限错位
- midquote premium ≠ implementable net：文中明确 **price pressure + size-dependent spread** 切断平均→边际

## 5. 识别与稳健性

- 主结果：组合 carry / BGT 的高 SR 主要来自**低波动**而非超高均值；与消费、S&P、FF、工业产值等因子相关不显著
- 有/无 TC：点差显著降低但未必抹平平均 SR
- 政策含义：在开放宏观模型里硬塞“风险溢价冲击”可能引入利率–产出伪相关
- 已知失败：传统线性 SDF 解释失败 → 引出后续 peso/期权文（w14054）

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 1M forward bid/ask | 是 | 缺历史可交易点 | fail closed 精确；利率扩展 only |
| 日→月对齐日历 | 是 | 可构造 | 必须非重叠 |
| 多币种 universe | 是 | Dukascopy 子集 | 扩展/负对照 |
| 规模依赖点差 | 原文机制 | 无 | 不可复制边际 SR |
| 订单流 | 机制 | 无 | 仅叙事 |

## 7. 本项目映射

- registry：`slow_carry_*` 毛收益对照；**不**把 w12489 当净收益证明
- 持有期：1M 再平衡
- 否决：用 mid 无点差 SR 宣称可交易；忽略 marginal vs average
- reused-history：BGT 式递归回归系数若作信号，窗口超参计入 FDR

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Fama (1984) forward premium | 谜题定义 |
| extension | Burnside et al. RFS 2011 (w14054) | peso + 期权 |
| survey | Burnside–Eichenbaum–Rebelo ARFE 2011 | 汇总 |
| boundary | Evans–Lyons 订单流 | price pressure 微观基础 |

## 9. 精读问题（给最强模型）

1. 把计价锚从 GBP 改为 USD 后，等权 carry 的矩是否稳健？
2. “with TC” 的开仓阈值若用滚动分位而非固定点差，SR 如何变？
3. 2016–2025 零售 swap 下，forward 实施与 interest 实施是否仍近似等价（CIP 失败）？
4. BGT 递归窗 30 点是否前视/数据挖掘敏感？
5. 如何用项目 cost contract 形式化“边际 SR=0”而不伪造订单流？
