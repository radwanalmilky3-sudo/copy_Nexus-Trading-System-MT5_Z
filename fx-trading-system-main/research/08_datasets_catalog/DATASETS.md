# 08 Datasets Catalog

| 数据集 | 官方入口 | 频率 | 字段要点 | lag / available_time | 许可 | 允许角色 | 禁止推断 | PIT | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| Dukascopy tick bid/ask | 项目下载器 | tick | bid, ask, time, volume proxy | 报价时点 | 研究用；非全市场 | 执行侧主价格 | 全市场深度/机构 OF | 报价时点 | 项目管线 |
| Yahoo FX midpoint | yfinance | daily | mid only | 收盘后 | 供应商条款 | 探索/软件 | 可成交利润 | mid only | 已用 v4 |
| BIS REER | https://data.bis.org/ | monthly | REER index | 发布后；常 current | BIS | value 探索 | strict vintage 价值 alpha | current | planned/archived |
| World Bank Pink Sheet | worldbank.org | monthly | 商品 USD 价格 | 发布后 | WB | 商品货币探索 | 忽略美元内生性 | current | planned/archived |
| CFTC TFF futures | https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm | weekly | OI, dealer/AM/LM long-short | 默认 +60d 近似 | 公共领域/官方 | 拥挤探索 | 签名 OF；as-published 全链 | 近似 | 部分 |
| CFTC Weekly Swaps | https://www.cftc.gov/MarketReports/SwapsReports/ | weekly editions | gross notional, tickets | edition/抓取规则 | 官方 | 活动/规模状态 | 方向 OF/carry | false | 审计见 docs |
| Cboe EVZ | https://www.cboe.com/us/indices/dashboard/evz/ ；CSV https://cdn.cboe.com/api/global/us_indices/daily_prices/EVZ_History.csv | daily | 30D IV index | 交易日；current 抓取 | Cboe | EUR 风险状态 | 1Y OTC VRP | current | 可下载 |
| Cboe EUVIX | https://www.cboe.com/us/indices/dashboard/euvix/ ；CSV .../EUVIX_History.csv | daily | 30D IV | 已停止更新（档至 ~2022-11） | Cboe | EUR 机制 | 横截面 VRP | current | 历史 only |
| Cboe JYVIX | https://www.cboe.com/us/indices/dashboard/jyvix/ ；CSV .../JYVIX_History.csv | daily | 30D IV | ~2022-11 停 | Cboe | JPY 机制 | 全 G9 IV | current | 历史 only |
| Cboe BPVIX | https://www.cboe.com/us/indices/dashboard/bpvix/ ；CSV .../BPVIX_History.csv | daily | 30D IV | ~2023-07 停 | Cboe | GBP 机制 | Della Corte 复制 | current | 历史 only |
| OFR FSI | https://www.financialresearch.gov/financial-stress-index/ | daily | stress index | 发布/抓取 | OFR | 风险状态 | 方向 alpha | current | planned/archived |
| ECB CISS | ECB SDW | daily/weekly | systemic stress | 发布/抓取 | ECB | 欧风险状态 | 方向 | current | planned/archived |
| NFCI / STLFSI | FRED / Chicago Fed | weekly | financial conditions | FRED 时点 | Fed | 风险状态 | OOS 已翻号当有效 | current | 已测 |
| Philly Fed RTDSM | philadelphiafed.org | vintage | CPI/IP levels by vintage | vintage available_time | Philly Fed | 宏观状态 | surprise | as-of 严格 | 已有 |
| ALFRED | https://alfred.stlouisfed.org/ | vintage | series×vintage | vintage date | StL Fed | 美宏观状态候选 | 公告时钟/consensus | vintage query | planned |
| NY Fed primary dealer | https://markets.newyorkfed.org/static/docs/markets-api.html ；all timeseries https://markets.newyorkfed.org/api/pd/get/all/timeseries.csv | weekly | dealer positions aggregates | 现档；注意 SBN breaks | NY Fed | 负对照/能力状态 | 2016–2025 方向 alpha | aggregate 现档 | planned |
| BIS GLI | https://data.bis.org/topics/GLI | quarterly | FX credit aggregates | 发布后 | BIS | 低频 funding 状态 | G9 日方向 | 无 full as-pub | planned |
| BIS LBS | https://data.bis.org/topics/LBS | quarterly | cross-border claims | 发布后+breaks | BIS | 结构审计 | 日流/OF | 无 full as-pub | planned |
| BIS OTC der. | https://data.bis.org/topics/OTC_DER | semiannual | notional/MV | 发布后 | BIS | 机制 | 存量→即期 | 无 full as-pub | planned |
| BIS Triennial | https://www.bis.org/statistics/rpfx22.htm | 3-yearly | turnover structure | 调查年 | BIS | 流动性假设 | 高频序列 | n/a | reference |
| OANDA financing | OANDA API/docs | daily | financing long/short | 账户可得后 | 厂商 | **融资成本压力** | 价格真理/全市场 forward | 账户后 | planned |
| LSEG WMR | methodology PDF | event | fix times, not tradeable mid for us | 官方历 | LSEG 条款 | 定盘日历 | 零售成交 | 官方历 | 已用日历 |
| ECB FX ref | ECB EXR CSV | business day | 14:15 CET dates | 官方 | ECB | ECB fix 日 | 成交价 | 官方 | 已用日历 |

## 字段级最低要求（入库）

```text
dataset_id, source_url, retrieved_at, sha256,
frequency, observation_time, available_time_rule,
fields[], license, forbidden_inferences[],
pit_class ∈ {strict, vintage_query, approximate, current, quote_time, none}
```

## 对齐口号（强制）

1. Cboe 30D IV ≠ Della Corte 1Y OTC VRP  
2. CFTC ≠ signed order flow  
3. BIS quarterly ≠ daily G9 direction  
4. Dukascopy ≠ full market depth  
5. OANDA financing ≠ 2016–2025 已实现 swap 真理（除非同账户历史）  
6. No consensus → no directional macro surprise

---

## Agent-Foundations-Datasets 扩展（2026-07-17，追加不改表结构）

HTML 落地页快照：`research/_html_snapshots/`（见该目录 `README.md`）。  
Allowed / forbidden / PIT 短笔记：`research/08_datasets_catalog/notes/`。

| 数据集簇 | 笔记 | 主快照 |
|---|---|---|
| Cboe EVZ/EUVIX/JYVIX/BPVIX | [notes/cboe_fx_vol_indices.md](notes/cboe_fx_vol_indices.md) | `cboe_evz.html`, `cboe_euvix.html`, `cboe_jyvix.html`, `cboe_bpvix.html`, `cboe_evz_cessation_notice.pdf` |
| BIS REER + GLI + LBS | [notes/bis_reer_gli_lbs.md](notes/bis_reer_gli_lbs.md) | `bis_reer.html`, `bis_gli.html`, `bis_lbs.html` |
| OFR FSI | [notes/ofr_fsi.md](notes/ofr_fsi.md) | `ofr_fsi.html` |
| ECB CISS | [notes/ecb_ciss.md](notes/ecb_ciss.md) | `ecb_ciss.html`, `ecb_ciss_portal.html`, `ecb_data_portal.html` |
| Philly Fed RTDSM | [notes/philly_fed_rtdsm.md](notes/philly_fed_rtdsm.md) | `philly_rtdsm.html` |
| ALFRED | [notes/alfred_stlouisfed.md](notes/alfred_stlouisfed.md) | `alfred.html` |
| NY Fed Markets API | [notes/nyfed_markets_api.md](notes/nyfed_markets_api.md) | `nyfed_markets_api.html` |
| World Bank Pink Sheet | [notes/worldbank_pink_sheet.md](notes/worldbank_pink_sheet.md) | `worldbank_pink.html` |
| CFTC COT | [notes/cftc_cot.md](notes/cftc_cot.md) | `cftc_cot.html` |

### 快照获取备注

- EVZ 旧路径 404 → dashboard URL 成功；并保存 2025-01 停用咨询 PDF。  
- `sdw.ecb.europa.eu` 解析失败 → 改用 `data.ecb.europa.eu` CISS 页。  
- 同目录 `oanda_*` 若存在，属其他 agent，本波次不删改。

### PIT 总原则（本批笔记）

```text
strict_vintage: Philly RTDSM, ALFRED (when realtime bounds stored)
current_release: BIS*, OFR FSI, ECB CISS, Cboe IV, Pink Sheet, NY Fed aggregate
release_calendar_approx: CFTC COT (release_date ≠ report_date)
```
