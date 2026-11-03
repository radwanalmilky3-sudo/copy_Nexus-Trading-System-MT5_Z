# [Mancini, Ranaldo & Wrampelmeyer 2013] Liquidity in the Foreign Exchange Market

- 深度层级: L3
- 引用链角色: foundational（流动性度量）/ boundary（对本项目的过滤用途）
- DOI/URL: https://doi.org/10.1111/jofi.12053 ；SFI RP 09-44 / 作者页数据
- 开放获取: 工作论文与作者 FX liquidity index（学术用途）
- 本项目映射: FIX-W **过去 60 事件日 spread q90** 入场过滤（项目执行合同，非全文复制）
- 复制状态: extension_only

## 1. 经济机制

外汇流动性在横截面与时间序列上高度共同变动，并与股票/债券流动性相关。危机中系统性 FX 流动性蒸发；货币收益对流动性风险的暴露应被定价（帮助解释 carry 等）。做市与电子经纪的价差、深度、冲击成本与收益反转度量共同刻画“变现成本”。对本项目，关键不是再估一个流动性风险因子，而是：**在低流动性状态下继续做流动性索取的定盘策略，期望收益更可能被 spread 吞噬**。

## 2. 精确公式

原文族（工作论文/期刊，概念层）：

```text
# 多维流动性度量（日度，按 pair）：
# - proportional bid-ask spread
# - effective cost / price impact
# - return-reversal / Pastor-Stambaugh 风格（适配 FX order flow）
# - 深度相关指标

bas_{i,t} = (ask_{i,t} - bid_{i,t}) / mid_{i,t}
L_market,t = PCA or average across measures and pairs
# 资产定价：货币组合对 L 冲击的 beta 进入横截面
```

本项目冻结的**执行过滤**（非论文主回归）：

```text
for each (market_symbol, FIX-W segment entry):
  history = entry_spread of past 60 scheduled event days (strictly before t)
  if ordinal < 60: status = warmup
  elif count(history finite) < 40: status = insufficient_history
  else:
    q90 = quantile(history, 0.90)
    pass iff current_entry_spread <= q90

# 禁止使用平仓 spread 或未来日期
# 任一段或任一 G9 腿失败 → filtered composite 为空（不部分保留）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 币种 | 九大主要货币对（高频） |
| 频率 | 超高频 → 日度流动性 |
| 样本 | 含 2007–2009 危机的现代电子经纪样本 |
| 来源 | 电子经纪/交易数据（非零售 Dukascopy） |

## 4. 成本与可实现性

- 原文：流动性是**被定价的风险**，不是免费的执行过滤器说明书。
- 项目 q90 是保守的“避免最差流动性日入场”规则，可能降低换手与收益；不得事后调分位。
- Dukascopy spread 水平与 EBS 不可比；过滤只在**同一数据源内部**相对化。

## 5. 识别与稳健性

- 共同流动性、危机恶化、风险溢价。
- 对本项目：过滤应 pre-registered；不得用全样本分位。

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 入场 bid/ask spread 时间序列 | 是 | tick 构造 | fail closed |
| 过去 60 事件日 | 是 | 代码常量 | warmup |
| 全市场深度/订单流 | 论文主度量需要 | 无 | 不声称全文复制 |
| PCA 市场流动性因子 | 否（本映射） | 可选探索 | 不进方向候选 |

## 7. 本项目映射

- `apply` spread q90 on FIX-W segments
- 否决：用未来 spread；过滤失败仍输出 filtered 收益；把 q90 说成 Mancini 风险溢价复制
- Dukascopy ≠ 全市场深度（硬对齐规则）

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| related | Söderlind & Somogyi 2024 | 流动性**风险暴露**横截面（需 1M forward） |
| related | Krohn et al. | 定盘时流动性需求 |
| boundary | Pastor–Stambaugh | 反转型流动性度量祖先 |

## 9. 精读问题

1. 日度 bas 与事件边界瞬时 spread 哪个更适合定盘过滤？
2. q90 vs q80 是否应进入搜索预算（当前冻结 q90，不应静默改）？
3. 危机子样本过滤通过率过低时，策略是否应直接空仓而非放宽阈值？
