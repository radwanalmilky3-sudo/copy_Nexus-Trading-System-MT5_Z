# [Menkhoff, Sarno, Schmeling & Schrimpf 2012] Currency Momentum Strategies

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1016/j.jfineco.2012.06.009
- 开放获取: BIS WP 366 https://www.bis.org/publ/work366.pdf ；City OA https://openaccess.city.ac.uk/id/eprint/3296/
- 本项目映射: 横截面 currency momentum；21/63/126/252 与 skip-21 搜索账本
- 复制状态: extension_only（成本与持有期）；精确 6 分位+1M forward 需数据
- 公式置信度: high（BIS WP 全文）
- published premium vs implementable: 毛收益 6–10% p.a.；扣指示性 bid-ask 后显著下降但未归零；零售+融资后未验证
- 2016–2025 外推风险: 高。样本至 2010；后期流动性、算法与 carry-momentum 拥挤改变

## 1. 经济机制

横截面货币动量：过去赢家货币相对输家继续跑赢。与股票动量类似，难以被标准风险因子完全解释；在 FX 中与 **carry 低相关**，且利润同时出现在 **spot 变动** 中（非仅利差）。作者强调 limits to arbitrage（特异波动、国别风险、换手成本）与行为 under/over-reaction，而非单一消费 beta。不同于 filter/MA 的**单币时间序列技术规则**。

## 2. 精确公式

```text
# 对数超额收益（USD 投资者）
rx^k_{t+1} ≡ i^k_t - i_t - Δs^k_{t+1} ≈ f^k_t - s^k_{t+1}
# s,f: 外币 / USD 对数报价

# 净成本（1M forward 腿总要交易；spot 腿仅在进出时）
# 进入并当月退出:
rx^L = f^b_t - s^a_{t+1}
rx^S = -f^a_t + s^b_{t+1}
# 进入后继续持有（下月末仍在组合）:
rx^L = f^b_t - s_{t+1}
rx^S = -f^a_t + s_{t+1}
# 已在组合、本月末退出: spot 用 ask/bid 平仓

# 组合
formation f ∈ {1,3,6,9,12} 月
holding   h ∈ {1,3,6,9,12} 月
# 每月末：按过去 f 个月滞后收益排序，六分位
# Low = 最低 1/6 滞后收益；High = 最高 1/6
# 等权；MOM_{f,h} = High - Low（美元中性）
# 重叠持有：类 Jegadeesh-Titman 多组合平均

# 主报告基准
MOM_1,1 ; MOM_6,1 ; MOM_12,1
# 亦报告按滞后 spot 变化排序的“纯即期动量”
```

无强制 skip-month（与部分股权动量不同）；项目 `skip-21` 为扩展。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 48 国（发达+新兴）；早期 GBP 报价转 USD |
| 频率 | 月末 |
| 样本起止 | 1976-01 至 2010-01 |
| 价格/远期 | BBI + Reuters via Datastream；spot 与 1M forward；含 bid/ask |
| 排序与再平衡 | 月末六分位；持有 h 月 |

## 4. 成本与可实现性

- 原文扣除：指示性 bid-ask；作者强调指示价差偏高 → 净收益是**保守下界**
- 成本显著削弱但**不能完全消灭**动量；换手高的规格更脆弱
- 迁移破坏点：
  - 零售点差 + 频繁月度换仓
  - 无 forward 时用 spot-only 会删掉利差但仍可测“即期动量”扩展
  - 新兴货币可达性/资本管制
- midquote premium ≠ implementable net：明确

## 5. 识别与稳健性

- 主结果：短持有（h=1）年化超额约 **6–10%**；MOM(1,1) Sharpe 可至 ~0.95（毛）
- 与 carry、HML_FX、全球 FX vol、FF3+Carhart、流动性代理等回归后 alpha 仍在
- 子样本：早期紧密挂钩货币多 → 早期利润较弱；OOS 分段仍存在
- 与技术规则低相关；长horizon 有反转迹象
- 已知衰减：后续样本拥挤与成本上升是外推风险

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 日/月末 spot 收益序列 | 是 | Dukascopy | — |
| 1M forward / 融资 | 超额收益完整版需要 | 缺 | spot-only = extension |
| bid/ask | 净收益需要 | 部分/进行中 | 只报毛收益不可晋级 |
| 形成期 f、持有 h、分位规则 | 是 | 可实现 | 规格必须预注册 |
| skip 规则 | 项目扩展 | 有 skip-21 账本 | 计入 FDR 分母 |
| 币种宇宙 G9 vs 48 | 子集 | G9 | extension_only |

## 7. 本项目映射

- registry：横截面 momentum 族；v4 方向未晋级
- 持有期：原文主 h=1M；项目 21/63/126/252 日
- 否决：成本后跨折不同号；与已登记搜索重复窥探同一历史
- reused-history：是

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Jegadeesh & Titman (1993) | 股权动量方法 |
| foundational | Lustig et al. (2011) | 货币组合与 carry 对照 |
| parallel | Moskowitz, Ooi & Pedersen (2012) | 时间序列动量 |
| joint | Asness, Moskowitz & Pedersen (2013) | value+mom everywhere |
| critique | 成本/limits 文献 (Korajczyk-Sadka 等) | 可实现性 |

## 9. 精读问题

1. MOM_{f,h} 利润有多少来自 spot vs forward discount？项目若只有 spot，偏差方向？
2. 六分位在 G9（仅 9 腿）是否退化为 3–3 或 2–2？统计功效如何？
3. skip-21 相对 f=1 无 skip，换手与反转暴露差多少？
4. 2016–2025 若动量与 carry 相关性上升，联合风险预算如何设？
5. 指示性价差 vs Dukascopy 有效价差：净 Sharpe 对价差乘数的弹性？
