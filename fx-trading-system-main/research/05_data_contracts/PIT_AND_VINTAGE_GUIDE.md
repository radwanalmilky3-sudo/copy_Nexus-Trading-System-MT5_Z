# Point-in-Time 与 Vintage 指南

更新日期：2026-07-17  
原则：**没有 as-published 证据链 → `strict_pit_eligible=false`**。Current-vintage + 人为 lag ≠ strict PIT。

## 1. 术语

| 术语 | 定义 | 本项目用法 |
|---|---|---|
| observation_time | 经济量所属期 | 标签/对齐 |
| available_time | 决策者最早可知时刻 | as-of 合并硬约束 |
| vintage | 某一发布日当时可见的整条历史 | RTDSM/ALFRED |
| as-published | 当时公布的文件字节级留存 | 最强 PIT |
| current-vintage | 今日修订后的历史 | 仅探索 |
| approximate lag | 用规则滞后代替真实发布时间 | CFTC 默认 60d |

Fail-closed：`available_time > decision_time` 的特征不得进入信号。

## 2. ALFRED（St. Louis Fed）

- 入口：https://alfred.stlouisfed.org/ ；Help：https://alfred.stlouisfed.org/help  
- 方法论要点：在 FRED 修订时归档“当时生效”的序列值；vintage = as-of 日期下的序列版本。  
- Release date 优先级（官方 help）：源实际发布日 > 提供方日期 > 首次进入 FRED 日期。  
- API：`fred/series/vintagedates` + observations with vintage params。

| 允许 | 禁止 |
|---|---|
| 已审计美国宏观状态的 day-level as-of | 当作 BLS/BEA 原始公告**秒级时钟** |
| 修订研究、实时预测复现 | 提供 MMS/Bloomberg **consensus** |
| 逐 series 保存查询、单位、hash | 未逐 series 审计就标 strict PIT |

**PIT 资格**：`conditional` — 仅当该 series 的 vintage 查询、发布日证据与 hash 完整。

## 3. RTDSM（Philadelphia Fed）

- 入口：https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists  
- 结构：每个 vintage 是“当时数据簿”的完整历史；本项目已下载 CPI/IP 真 vintage。  
- 代码合同（`macro_vintages.py`）：`observation_time < available_time`；同 vintage 内算 CPI 12m / IP 6m log change；禁止未来修订回填。

| 允许 | 禁止 |
|---|---|
| 严格 as-of 宏观状态/变化率 | 当作公告 surprise（无 consensus） |
| 训练/探索在 vintage 覆盖期 | 覆盖外插值伪造 |

**PIT 资格**：`true`（已归档 CPI/IP 行，`pit_eligible` 校验通过时）。

## 4. CFTC COT / TFF

### 4.1 发布

- 一般规则：周二持仓，**周五 15:30 Eastern** 发布（tentative schedule）。  
- 官方：https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm  
- 假日可延迟 1–2 天；tentative ≠ 已验证实际发布时间。  
- 本项目 `CFTCReleaseCalendar`：区分  
  `official_tentative_schedule` / `official_exception_announced` / `official_exception_actual` / `rule_derived_mapping`；  
  `verified_actual=true` 仅当官方写明确实发布。

### 4.2 数值修订

- Historical Compressed：https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm  
- 当前 ZIP 是**会修订的现行档案**，不是逐期 as-published 字节链。  
- Special Announcements 记录过重分类与格式修正。  
- 代码标记：  
  `availability_quality = approximate_conservative_{lag}d_lag`（默认 lag=60）  
  `value_vintage_quality = current_revised_historical_archive_not_as_published_vintage`

### 4.3 允许 / 禁止

| 允许 | 禁止 |
|---|---|
| 拥挤/仓位状态探索 | 签名订单流 |
| 保守 lag 后的慢周期特征 | 严格晋级（在 actual timestamp + as-published 未齐前） |
| TFF 货币期货净比 | 当作定盘窗 OF 或即期方向因果 |

**PIT 资格**：`false`（时间近似 + 值非 as-published）。自建 forward 抓取未来可部分升级时间维，值维仍需 as-published 策略。

## 5. BIS 低频统计

| 产品 | 频率 | 允许 | 禁止 | PIT |
|---|---|---|---|---|
| [GLI](https://data.bis.org/topics/GLI) | 季度 | 发布后 global-funding 风险状态 | G9 日方向 | 无 full as-published → false |
| [LBS](https://data.bis.org/topics/LBS) | 季度 | 结构/break 审计；低频状态 | 日度资金流/OF | false |
| [OTC derivatives](https://data.bis.org/topics/OTC_DER) | 半年 | 存量/集中度机制 | 用 USD 换算存量变推断即期方向 | false |
| [Triennial](https://www.bis.org/statistics/rpfx22.htm) | 三年 | 结构覆盖与流动性假设校准 | 月/日时间序列调参 | false |

规则：只用**发布后**信息；不得用 observation quarter 末日 + 人为 lag 伪造历史可知。

## 6. 其他相关合同（摘要）

| 源 | PIT | 备注 |
|---|---|---|
| GSCPI | 2022-01 后保存的月度 vintage 为 true；普通历史 current | 已有项目实现 |
| OFR FSI / ECB CISS / Cboe IV | current（首次抓取 timestamp） | 向前自建快照可进化 |
| BIS REER / Pink Sheet | current | value/商品探索 |
| NY Fed primary dealer API | aggregate 现档；跨 SBN break | 2016–2025 负对照 |
| OANDA financing | 账户可得后 | 非 2016–2025 已实现融资真理 |
| OECD EO | forecast edition，非 actual vintage | 非 surprise |

## 7. 决策表：能否进 strict 特征店

```text
if as_published_bytes AND release_timestamp_verified:
    strict_pit_eligible = true
elif true_vintage_matrix (RTDSM/ALFRED audited) AND available_time <= decision_time:
    strict_pit_eligible = true  # day-level macro state only
elif conservative_lag_only OR current_archive:
    strict_pit_eligible = false
    use = exploration | risk_state | negative_control
else:
    fail closed
```

## 8. 存储最低字段

每次外部下载：

```text
source_url, retrieved_at, sha256, parser_version,
observation_time, available_time, available_time_rule,
pit_eligible, value_vintage_quality, license_note
```
