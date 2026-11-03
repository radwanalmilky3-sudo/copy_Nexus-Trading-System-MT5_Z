# LSEG WMR FX Benchmarks Methodology（L2 官方合同）

- 深度层级: L2（官方 methodology；允许作附录与日历合同）
- 引用链角色: data_contract
- DOI/URL: https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/wmr-fx-methodology.pdf （v30, January 2026）
- 相关: https://www.lseg.com/content/dam/ftse-russell/en_us/documents/methodology/wmr-service-alterations.pdf
- 本项目映射: Tokyo / WMR 事件时刻、五分钟窗、半日/停服例外表、月末实际发布日
- 复制状态: 官方规则已部分接入 `PublicationCalendar`；半日例外仍依赖人工转录 + hash 审计

## 1. 关键时间（Spot）

| 项目 | 官方规则（v30） |
|---|---|
| 小时点 | 周一 06:00 香港/新加坡 至 周五 22:00 英国，整点 |
| Trade currencies 半点 | 2012 起仅 Trade Currencies 提供 half-hourly |
| Closing Spot | **16:00 UK time（4 p.m. UK）** |
| Tokyo Benchmark | **09:55 JST（文档写 9.55JST / 00:55 GMT 叙述）** |
| 其他专项 | 11:00 UK；14:00 CET；12:00 EST CAD Noon |
| 目标发布滞后 | 计算完成后约 **15 分钟** 发布 spot |

Trade Currencies（25）：AUD, CAD, CHF, CNH, CZK, DKK, EUR, GBP, HKD, HUF, ILS, INR, JPY, MXN, NOK, NZD, PLN, RON, RUB, SEK, SGD, THB, TOF, TRY, ZAR。

## 2. 计算窗（与项目 2m30s 对齐）

官方对 Trade / Non-Trade spot：

```text
# 以计算时刻为中心的 5 分钟窗
snapshots from T - 2m30s to T + 2m30s
# Non-trade: 每 15s 报价快照 → 独立 median bid / median offer
# Trade: 每秒 trades + orders；优先成交，不足则订单，再 expert judgement
```

本项目：

- `EVENT_WINDOW_HALF_WIDTH = 2 minutes 30 seconds`
- FIX-W 的 `post_wmr` **从 WMR + 2m30s 起**，避免在定盘窗内抢跑/抢价
- 事件日必须来自 verified publication calendar，不得用“工作日启发式”

## 3. 假日 / 半日 / 低流动性

监控中心：**US, UK, Germany, Japan**。

原则：在不损害质量的前提下，尽可能按正常时刻计算。

| 条件 | 规则摘要 |
|---|---|
| ≥2 个中心开放 | Closing Spot/Forward 正常生产 |
| 一个或多个中心关闭 | Intraday 可能不生产 |
| 仅一个中心开放 | 通常不生产；月末可能例外评估 |
| 圣诞/新年前低流动性 | 可能提前最后计算时刻（见 Service Alterations） |
| 特定币种无流动性 | 可继续提供 last published rate |
| CAD Noon | 遵循加拿大假日，假日不发布 |

Service Alterations PDF 给出未来多年的具体半日/停服表；本项目历史例外依赖 Internet Archive 快照 + 人工转录。

## 4. 本项目已经使用什么

| 用途 | 状态 |
|---|---|
| WMR 16:00 Europe/London | 是 |
| Tokyo 09:55 Asia/Tokyo | 是 |
| ECB 14:15 Europe/Berlin（ECB 官方 CSV，非 WMR） | 是 |
| 5 分钟半窗 2m30s | 是 |
| 实际 WMR 月末日 `actual_wmr_month_end` | 是（自然月逐日完整日历） |
| Service alteration 自动反解 | **否**；人工转录 + 测试覆盖关键半日 |
| 把 WMR 官方 mid 当成交价 | **否**；执行侧用 Dukascopy bid/ask |

## 5. 否决 / 禁止

1. 用“每个工作日 16:00”代替停服/半日表。
2. 用 WMR 定盘价序列回测零售可成交收益。
3. 重新分发 LSEG PDF 前不核条款。
4. 忽略 raw source SHA-256 / manifest。

## 6. 精读问题

1. 历史版本（v 前序）何时把 London fix 从 1 分钟窗扩到 5 分钟？对 2016–2025 样本如何分段？
2. 半日“last fix 12:00”时，项目 FIX-W 的 post_wmr 段应空还是改锚？
3. Tokyo 09:55 与 ECB 14:15 在同一 DST 切换周的 UTC 对齐审计清单？
