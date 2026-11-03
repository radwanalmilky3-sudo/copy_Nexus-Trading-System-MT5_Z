# CFTC Weekly Swaps Report 外汇研究审计

审计日期：2026-07-16。

## 结论

CFTC 官方 [Weekly Swaps Report](https://www.cftc.gov/MarketReports/SwapsReports/index.htm)
可以免费、合法、自动下载，且官方
[Archive](https://www.cftc.gov/MarketReports/SwapsReports/Archive/index.htm) 明确称其中保存的是
历次 `previous publications`。本项目已实现独立下载器：

```bash
uv run python scripts/download_cftc_weekly_swaps.py \
  --output data/cftc_weekly_swaps
```

它适合构造 **FX swaps 活动、流动性或市场规模状态**，不适合构造方向性订单流或 carry：

- 官方数据是 SDR 报送的 market-facing gross notional、ticket volume 和 dollar volume；
- 没有买卖方向、价格、forward points，也没有“货币 × participant type”的交叉表；
- 逐币种只稳定披露 EUR、GBP、CHF、CAD、JPY、AUD 等，NZD 被并入 Asia/Pacific `Other`；
- 因此不得称为现货订单流、dealer 净头寸、市场 forward、OIS、swap 收益或 alpha。

## 覆盖与缺口

Archive 背景称 FX swaps 在 2018-10-17 加入，但该日期的 XLSX 实际没有 19–21 号 FX 表；
第一个可解析版本是 2018-10-24。冻结到 2025-12-29 后，官网当前能发现 336 份有效链接：

| 年份 | 可下载版本数 | 审计说明 |
|---|---:|---|
| 2018 | 9 | 10-24 起；12-26 坏链接与官方停摆说明冲突，拒绝下载 |
| 2019 | 47 | 联邦停摆后从 02-06 恢复，不补不存在的周 |
| 2020 | 52 | 12 月从周三改到周一附近有 12 天版次间隔 |
| 2021 | 52 | 官方版次链接完整 |
| 2022 | 52 | 12 月存在方法和字段断点 |
| 2023 | 51 | 01-30 单元错误链接到 2024-01-29，程序不猜 URL |
| 2024 | 21 | 官网仅链接 01–02 月及 09-30 后版次，中间长缺口不插值 |
| 2025 | 52 | 10–11 月版次在拨款中断后追赶发布，文件日期不是实际发布时间 |

单份 XLSX 实测约 55–85 KiB。336 份工作簿约 20–30 MiB；加 evidence HTML、cache 和按
内容哈希保存的 archive 双份后，预计总目录约 50–90 MiB，不是 GB 级任务。标准化 CSV 预计
约 56,730 行，体积只有数十 MiB 以内。

## 字段契约

下载器只规范化官方逐币种表：

| Sheet | 指标 | 单位 |
|---|---|---|
| 19b | gross notional outstanding | USD millions |
| 20b | transaction ticket volume | ticket count |
| 21b | transaction dollar volume | USD millions |

每行保留 edition date、reporting-period Friday、保守 `availability_time`、货币、product、
source URL 和 XLSX SHA-256。产品字段不跨断点伪造连续性：

- 2022-12-05 及以前：旧方法、`Exotics` 与 `Cross Currency` 分列；
- 2022-12-12/19：新方法已经启用，但产品仍分列；12-19 的原始列名短暂为 `EXOTIC`；
- 2022-12-26 起：两列合并为官方 `Other`，不反推拆分值。

CFTC [Explanatory Notes](https://www.cftc.gov/MarketReports/SwapsReports/ExplanatoryNotes/index.htm)
说明 reporting period 是发布日前约两周半结束的周五。普通版次使用官方 archive 的
publication date，但缺逐期 actual timestamp，程序推迟到下一个纽约自然日才可用。2025-10-06
至 2025-11-10 的追赶版次依据官方
[Release Schedule](https://www.cftc.gov/MarketReports/SwapsReports/ReleaseSchedule/index.htm)
不能把 edition label 当实际发布日期，因此只从本项目首次抓取时点可用。

## PIT 与完整性边界

所有标准化行统一为 `strict_pit_eligible=false`。原因不是数据内容无价值，而是两项正式晋级
证据仍不完整：

1. 逐期实际发布日期/时间没有完整映射，2025 catch-up 已证明 edition date 可不同于实际发布；
2. 官方称这些文件是历史 publications，但本项目没有在原发布时取得密码学哈希，不能升级为
   `verified_as_published_vintage`。

下载器对工程完整性仍严格失败关闭：archive 年度计数、官方域名和路径、XLSX ZIP、sheet、
版次日期、reporting-period Friday、逐表表头、行标签、近似加总、raw/cache/archive、metadata、
manifest 和标准化 CSV 任一不符都会停止。官方总计因独立四舍五入可以与分项相差 1–2，超过
此范围才拒绝。

CFTC [Web Policy](https://www.cftc.gov/webpolicy/index.htm) 说明政府信息属于 public domain，
可自由复制和分发并建议注明 CFTC 来源；程序保存该政策页的原始响应和哈希作为本次下载的
许可证据。研究使用仍应注明来源，不得暗示 CFTC 为策略或收益结论背书。

## 允许的研究用途

在 Dukascopy 到达前，可以先冻结不看收益的机制变量，例如：

- 各币种 `swaps_and_forwards` dollar volume 的 13/26 周自身 z-score；
- ticket volume 与 dollar volume 的比率，作为平均 ticket size 的粗代理；
- gross notional 与 weekly dollar volume 的 turnover 粗代理；
- 全市场活动状态门控，而不是直接的多空信号。

这些公式仍须在看结果前登记，并按 2018、2022 方法断点和 2024 缺口做覆盖门禁。它们不能
补齐 2016–2018，也不能补齐 NZD 横截面，因此不应直接加入要求完整 2016–2025 G8 面板的正式
候选集。
