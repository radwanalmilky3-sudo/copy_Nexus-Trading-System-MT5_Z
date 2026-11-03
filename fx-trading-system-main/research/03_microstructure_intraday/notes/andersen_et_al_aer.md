# [Andersen, Bollerslev, Diebold & Vega 2003] Micro Effects of Macro Announcements

- 深度层级: L3
- 引用链角色: foundational（公告微观结构）
- DOI/URL: https://doi.org/10.1257/000282803321455151 ；作者 PDF http://public.econ.duke.edu/~boller/Published_Papers/aer_03.pdf
- 开放获取: 作者页 PDF
- 本项目映射: **blackout**（仅实际发布时间）；禁止无 consensus 的方向 surprise
- 复制状态: fail_closed_missing_data（对方向 surprise）；blackout 扩展可用

## 1. 经济机制

宏观公告的**未预期成分**在数分钟内进入汇率条件均值与波动率。价格发现接近瞬时；波动持续更久。只有 surprise = actual − expected 才是冲击；已被预期的部分在公告前大体进入价格。因此“有公告就交易方向”没有理论支持；“有公告就回避开仓”才是与文献一致的风险控制。

## 2. 精确公式

```text
S_{k,t} = (A_{k,t} - E_{k,t}) / sigma_k   # 标准化 surprise；E 为 MMS 等调查中位数

R_{tau} = sum_{j} beta_j S_{j,t} * 1{tau in window} + e_tau
# 高频收益区间：文中以 5 分钟等实时区间为主

# 本项目允许：
blackout = [T_release - 30min, T_release + 60min]  # 禁止新开仓（路线图冻结）
# 本项目禁止：
sign_trade = f(A - E)   # 当 E 无 PIT consensus 时
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 货币 | DEM/USD, GBP/USD, JPY/USD, CHF/USD 等 |
| 频率 | 5 分钟级 |
| 新闻 | 美国就业、通胀、产出等 |
| 预期 | 市场调查中位数（MMS 类） |

## 4. 成本与可实现性

- 公告窗点差与滑点上升；即使方向正确也可能净亏。
- 无历史 consensus 时，任何“方向公告策略”都不是本文复制。

## 5. 识别与稳健性

- 条件均值跳跃 + 波动持续；非对称性存在。
- 2016–2025 必须用**逐事件实际发布时间**（FOMC 时刻已变迁）。

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 实际 release timestamp | blackout 需要 | 官方日历部分 | 未知则扩大/跳过 |
| PIT consensus median | surprise 需要 | 通常不可免费 | 禁止方向 surprise |
| 高频报价 | 是 | Dukascopy | 1h 不足 |

## 7. 本项目映射

- blackout 过滤 only
- 否决：用“新闻标题情绪”或实际值水平冒充 surprise；沿用旧 FOMC 14:15 规则不核验

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| related | Faust et al. JME | 20 分钟窗 + MMS |
| related | Evans & Lyons | 新闻经订单流间接传导 |
| boundary | 官方 BLS/BEA/Fed 发布时间 | 时钟证据 |

## 9. 精读问题

1. 5 分钟均值效应在扣 spread 后还剩多少？
2. 标准化 sigma 用扩展窗还是全样本？
3. 多国公告叠加时 blackout 如何并集而不过度空仓？
