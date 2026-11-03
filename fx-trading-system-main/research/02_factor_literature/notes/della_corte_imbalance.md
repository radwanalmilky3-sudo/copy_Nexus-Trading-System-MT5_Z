# [Della Corte, Riddiough & Sarno 2016] Currency Premia and Global Imbalances

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1093/rfs/hhw038
- 开放获取: City OA https://openaccess.city.ac.uk/id/eprint/13287/1/FX_NFA_full.pdf
- 本项目映射: **外部失衡 IMB 因子**（NFA × 负债本币份额）；非当前可交易主线
- 复制状态: fail_closed_missing_data（Lane–Milesi-Ferretti NFA + 负债币种结构 + 1M forward）
- 公式置信度: high（City OA 全文）
- published premium vs implementable: 有 bid-ask 净版本；Sharpe 可与 carry 比肩；仍非零售 swap
- 2016–2025 外推风险: 高。全球失衡格局、美元负债结构与 CIP 偏离同期演变

## 1. 经济机制

基于 Gabaix–Maggiori 中介约束：期望货币超额收益不仅依赖利差，还依赖**外部净头寸与中介风险承担能力**。净债务国、且负债以外币计价（“原罪”）的货币，在全球风险上升时需更大幅度贬值以实现外部调整 → 事前要求更高溢价。净债权且本币负债国提供对冲。故双变量排序构造的 **IMB** 捕捉全球失衡风险，与 CAR/carry 正相关但不完全重叠，并在多类货币组合（含 mom/value/RR 等）中被定价。

## 2. 精确公式

```text
# 超额收益（报价：USD per foreign unit；上升=外币升值）
RX_{t+1} = (S_{t+1} - F_t) / S_t
# 或 RX = (S_{t+1}-S_t)/S_t - (F_t-S_t)/S_t
# CIP 下 forward premium ≈ 利差；亦报告 bid-ask 净

# 排序变量（年度，月内持恒）
nfa = (ForeignAssets - ForeignLiabilities) / GDP
# Lane & Milesi-Ferretti 等

ldc = 外债中以本币计价的份额
# 高 ldc = 低原罪；Benetrix–Lane–Shambaugh 更新
# 年末值 hold constant 至下一年；早期比例可回填

# 序贯双排序 → 五组合
# 1) 按 nfa 分两大篮（债权/债务）
# 2) 篮内按 ldc 再排序
# Portfolio 1（最安全）: 高 nfa + 高 ldc
# Portfolio 5（最风险）: 低 nfa + 低 ldc
# 组内等权 RX

# IMB 因子
IMB = RX^{P5} - RX^{P1}
# 多债务/外币负债货币，空债权/本币负债货币

# 资产定价
M_{t+1} = 1 - b'(f_{t+1}-μ)
E[RX^j] = λ' β^j
# 因子: DOL + IMB；或 DOL + CAR + IMB
# λ_IMB > 0 约 3–8% p.a. 量级（见表）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 宽截面（约 1983 起有 forward 的货币集） |
| 频率 | 月度 FX；年度外部账户 |
| 样本起止 | 约 1983–2014 族（以发表表为准） |
| 价格来源 | spot/1M forward（Datastream 类） |
| 宏观 | LMF 外部财富；负债币种结构数据 |
| 排序与再平衡 | 月度 FX；宏观信号年更 hold-constant |

## 4. 成本与可实现性

- 原文：报告 gross 与 transaction-cost net
- 迁移破坏点：
  1. NFA/ldc **发布时滞与修订**（vintage）
  2. 无 1M forward → 不能复制 RX
  3. G9 上 nfa/ldc 截面变异不足
- midquote ≠ net；零售 swap 另计

## 5. 识别与稳健性

- 主结果：IMB 均收益与 Sharpe 强；定价多类货币组合；控制 CAR 后仍有信息
- 坏时期：风险厌恶上升时债务国货币贬值（假设 2）
- 稳健：替代失衡度量、子样本
- 失败：用季度经常账户近似代替 NFA 存量结构

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 多国 NFA/GDP 时序 | 是 | 缺正式 PIT 库 | fail_closed_missing_data（R3） |
| 负债本币份额 ldc | 是 | 缺 | fail_closed |
| 发布时滞日历 | 是 | 缺 | 否则 look-ahead |
| 1M forward bid/ask | 是 | 缺 | fail_closed |
| G9 子集 | 探索 | partial | extension only；功效低 |

## 7. 本项目映射

- registry：`imbalance_imb` — **默认不进入方向候选**直至 R3 关闭
- 持有期：月度
- 否决：用单一经常账户/GDP 冒充双排序 IMB；与 value 信号静默合并
- 文献地图：与 menkhoff_rfs_value、Gabaix–Maggiori 同属“外部头寸”族

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Gabaix & Maggiori (2015) | 中介/失衡理论 |
| foundational | Lane–Milesi-Ferretti | NFA 数据 |
| replication | Lustig et al. carry | CAR 对照 |
| boundary | Menkhoff et al. value | 估值/外部 |
| boundary | Borio BIS / Du et al. | 美元融资与表外头寸 |

## 9. 精读问题（给最强模型）

1. 仅用年度 CA/GDP 单变量排序相对双排序 IMB 的信息损失？
2. LMF 修订是否足以在 2016–2025 反转 IMB 符号？
3. IMB 与 HML_FX 相关在 CIP 偏离期是否上升？
4. G9 债权国（日/瑞）空头腿是否被零售 swap 扭曲？
5. 若 macro 仅季度发布，hold-constant 规则如何预注册？
