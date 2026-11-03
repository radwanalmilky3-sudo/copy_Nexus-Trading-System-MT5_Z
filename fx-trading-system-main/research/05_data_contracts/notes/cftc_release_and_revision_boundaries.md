# [CFTC COT/TFF] 发布、修订与订单流边界

- 深度层级: L4
- 引用链角色: data_contract / boundary
- DOI/URL:
  - About: https://www.cftc.gov/MarketReports/CommitmentsofTraders/AbouttheCOTReports/cot_about
  - Schedule: https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm
  - Historical Compressed: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
  - Special Announcements: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm
- 开放获取: 是
- 本项目映射: 货币期货拥挤/仓位特征；`availability_lag_days=60` 默认
- 复制状态: extension_only / strict 晋级 fail closed

## 1. 经济机制

TFF 报告大户在金融期货上的分类持仓（Dealer、Asset Manager、Leveraged Money 等）。它反映**监管报告口径的周度仓位存量**，可能与拥挤、风险承载相关，但：

1. 不是交易级签名订单流；  
2. 不是即期 OTC 定盘流量；  
3. 不是带准确历史发布时间的 as-published 面板（除非自建）。

## 2. 精确公式 / 合同

```text
# 项目解析（futures-only TFF 货币）
net_ratio_category = (long - short) / open_interest

# 默认 PIT 近似
observation_time = report_date (usually Tuesday)
available_time   = observation_time + 60 calendar days
availability_quality = approximate_conservative_60d_lag
value_vintage_quality = current_revised_historical_archive_not_as_published_vintage

# 发布日历证据层级
date_evidence_kind ∈ {
  official_tentative_schedule,
  official_exception_announced,
  official_exception_actual,
  rule_derived_mapping
}
verified_actual_timestamp_utc only if verified_actual and time known
```

货币合约映射（项目代码）：CAD 090741, CHF 092741, GBP 096742, JPY 097741, EUR 099741, NZD 112741, AUD 232741。

## 3. 数据与样本

| 项 | 内容 |
|---|---|
| 频率 | 周 |
| 报告 vs 发布 | 周二 as-of；通常周五 15:30 ET 发布（tentative） |
| 历史文件 | 年度 ZIP；会重分类/修订 |
| 2016–2025 项目日历 | 522 行证据；0 个 actual timestamp 全验证（路线图快照） |

## 4. 成本与可实现性

- 仓位因子即使有 alpha 叙事，也必须过慢周期成本合同（spread/swap）。
- 时间泄漏（用未发布仓位）会虚假提高拥挤反转表现。

## 5. 识别与稳健性

- 分类依赖 Form 40，CFTC 可重分类（历史公告可查）。
- 2023 ION、2025 拨款中断等导致延迟与追赶发布 → edition date ≠ actual time。

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 当前历史 ZIP | 探索 | 是 | — |
| 逐期 as-published 字节 | 严格 | 否 | strict=false |
| 实际发布时间戳 | 严格 | 基本无 | 60d lag / calendar |
| 签名 OF | Evans–Lyons | 否 | 禁止替代 |

## 7. 本项目映射

- 拥挤反转等：探索 + FDR；**不得严格晋级**直至时间与值两维证据齐
- 对齐规则：**CFTC ≠ signed order flow**
- Weekly Swaps Report：活动/规模状态，同样非方向 OF（见 docs 审计）

## 8. 引用链

| 角色 | 文献/文档 | 关系 |
|---|---|---|
| boundary | Evans–Lyons | 真 OF 定义 |
| related | 项目 cftc_release_calendar | 证据枚举 |
| related | CFTC swaps archive 审计 | 另一非 OF 源 |

## 9. 精读问题

1. 60 日 lag 是否过度保守以至于信号死亡？如何在不放宽泄漏下用 verified Friday 子集？
2. Leveraged money net 与 CTA 趋势拥挤的识别差异？
3. 重分类公告如何生成 break dummy 而不前视？
