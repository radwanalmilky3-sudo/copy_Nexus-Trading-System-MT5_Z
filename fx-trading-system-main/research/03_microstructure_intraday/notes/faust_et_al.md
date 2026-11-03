# [Faust, Rogers, Wang & Wright 2007] High-Frequency Response of Exchange Rates and Interest Rates to Macro Announcements

- 深度层级: L3
- 引用链角色: replication / boundary
- DOI/URL: https://doi.org/10.1016/j.jmoneco.2006.05.015 ；会议/工作论文 PDF
- 开放获取: 工作论文版本
- 本项目映射: surprise **合同**（actual − MMS median；20 分钟窗）；无 consensus 则 fail closed
- 复制状态: fail_closed_missing_data

## 1. 经济机制

美国宏观 surprise 在极短窗内同时移动汇率与国内外利率。更强的实际数据通常使 USD 升值并抬升利率；联合反应需用 UIP/风险溢价或超调叙事解释。关键识别来自**精确时间窗 + 调查预期**，不是日度 OHLC。

## 2. 精确公式

```text
# 项目文献地图冻结的合同
window = [T - 5min, T + 15min]   # 共 20 分钟
S = actual - MMS_median_consensus

Δs_window = a + b * S + e
# 1987–2002 样本中多数美国数据 08:30 ET；历史 FOMC ~14:15 ET
# 2016–2025：逐事件核验实际发布时间，不得照搬旧 FOMC 时刻
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产 | FX + 美/外利率期限结构 |
| 样本 | 约 1987–2002 高频 |
| 指标 | CPI, PPI, GDP, NFP, unemployment, claims, housing, retail, trade, funds target 等 |
| 预期 | MMS；政策可用资金期货 |

## 4. 成本与可实现性

- 20 分钟窗仍跨越公告冲击；零售点差跳升。
- 无 MMS/Bloomberg 历史中位数 → **不能**构造方向规则。

## 5. 识别与稳健性

- 联合资产反应；部分指标效应随时间变化（如 PPI）。
- 对 2016–2025：制度与发布时刻变迁是硬风险。

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| MMS/Bloomberg median | 是 | 通常无 | fail closed |
| 官方 actual + timestamp | 是 | 部分 | 无则 blackout only |
| 利率期货 | 联合检验 | 非必须 | 可省略联合层 |

## 7. 本项目映射

- surprise 合同文档化；不进方向候选直至授权 consensus
- 否决：用 ALFRED 水平值或 RTDSM 代替 consensus；用“好于去年”冒充 surprise

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Andersen et al. AER | 更早微观发现 |
| related | Evans & Lyons | 间接传导 |
| boundary | 官方发布日历 | 时钟 |

## 9. 精读问题

1. 5+15 窗与对称 ±10 窗的估计差异？
2. 哪些指标在 2010 后失效？
3. 若只有 actual 没有 E，波动回归是否仍可预注册为风险状态？
