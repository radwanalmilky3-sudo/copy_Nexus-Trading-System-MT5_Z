# IBKR（盈透）历史成本数据获取计划

日期：2026-08-02。目标 broker 已定为 **Interactive Brokers (IBKR)**。实体/账户类型/币种待账户持有人确认（见末节）。

> 本文档替代通用请求包 `BROKER_COST_DATA_REQUEST_ZH.md` 对 IB 的适用部分。IB 的数据现实与通用 broker 不同，必须单列。

## 1. 关键约束（先读）

IB **不发布逐品种历史 swap / 融资 schedule**。历史融资数据只有一条官方获取路径：**Flex Query 账户报表**，而 Flex Query **只导出该账户自己实际产生过的融资扣费**，不是市场通用 schedule。

因此对新研究账户（无 2016–2025 真实持仓历史）：

- 「向 IB 请求 2016–2025 逐品种历史 swap schedule」**基本不通**；
- 正式成本合同 `historical_target_broker_schedule` 在 IB 上**只有当账户持有人有多年真实持仓、并能 Flex Query 导出时**才可达；
- 否则只能走合成（`software_fixture`，仅研究）或商业数据（付费）。

## 2. 三条现实路径

### 路径 A：合成（现在可做，仅研究口径）

IB 对外汇保证金的隔夜融资按公式：

```text
financing_rate ≈ benchmark_rate(base_currency) − benchmark_rate(quote_currency) + IB_premium(tier, direction)
```

- benchmark rate：每个币种的公开政策利率（SOFR/ESTR/SONIA/€STR/TONA/SONIA 等），部分已落 `data/official_rates/`；
- IB premium：按账户资产分层（≤$10k / $10k–$100k / $100k–$1M / >$1M），方向（多/空）不同，IB 官网有**当前**快照，但历史上调过、不一定有逐日历史；
- 三倍计息：IB 外汇一般按 value date 在周三计三倍（覆盖周末），但 NOK/SEK/JPY 等币种周末/假日规则有差异，需 IB 确认。

产物标签：`software_fixture` / `synthetic`。**不能**解锁正式净收益，只用于软件测试和成本压力情景。

可立即做的工程：
1. 把 `data/official_rates/` 的 benchmark 扩到 14 品种涉及的 9 个币种（USD/EUR/GBP/JPY/CHF/AUD/NZD/CAD/NOK/SEK）完整 2016–2025 日序列；
2. 抓取 IB 当前 premium tier 快照，标注「无逐日历史」；
3. 实现合成 financing 生成器，输出带 `quote_quality=software_fixture` 的 cost contract CSV。

### 路径 B：商业数据（付费，可解锁正式）

Bloomberg (`SWPM`) / Refinitiv 历史 FX swap points。若有订阅，按 `tradable_forward_quotes.schema.csv` 落盘，标签 `historical_tradable_bid_ask`，需附来源/版本 manifest。买不到则维持 `cost_incomplete`。

### 路径 C：账户历史 Flex Query（仅当有真实持仓）

若账户持有人在 IB 有多年真实外汇持仓，可用 Flex Query 导出**该账户**的历史融资扣费：

- 入口：Client Portal / Account Management → Reports → Flex Queries；
- 选 **Activity Flex Query**，加 section **"Financing"** 或 **"Interest Accruals"**，字段含 `date`、`symbol`、`currency`、`long/short financing`、`quantity`、`rate`；
- 区间设 2016-01-01 至 2026-01-01，CSV 或 XML；
- 产物标签 `historical_target_broker_schedule`（仅对该账户、该实体有效）。

参考：`ibkrguides.com/orgportal/performanceandstatements/flex.htm`、IBKR Campus「Activity Flex Query」。

## 3. 成本合同标签边界（不变）

```text
historical_target_broker_schedule  ← 仅路径 C（账户 Flex Query，有真实持仓）
historical_tradable_bid_ask        ← 仅路径 B（商业数据，付费）
software_fixture / synthetic       ← 路径 A（合成）；只用于研究/压力，不进正式净收益
```

无论走哪条，CLI `cost-coverage-audit` 不会自行把来源真实性设为已验证，也不会批准交易。正式净收益在路径 B 或 C 达成前保持 `cost_incomplete_research_only`。

## 4. 待账户持有人确认的最小字段

1. **IB 法律实体**（不是品牌）：IBKR LLC（US, SEC/FINRA）/ IBKR HK（香港证监会）/ IBKR UK（FCA）/ IBKR Central Europe（CNBV/CONSOB 等授权）/ 其他——融资规则按实体不同；
2. 账户类型：IBKR Pro / Lite；保证金：Reg T / Portfolio Margin；
3. 账户币种：USD（默认）/ 其他；
4. 账户资产规模 tier（决定 premium 分层）；
5. 是否已有该账户 2016–2025 真实外汇持仓历史（决定路径 C 可行性）；
6. 是否有/愿购商业历史 swap 数据（决定路径 B）。

## 5. 与项目其他工作的关系

- 不阻塞 G0（行情审计独立进行）；
- 不阻塞第二层五因子包；
- 是 WP7（成本后组合验证）的硬前置：路径 B/C 不达成，正式净收益账本永远 `cost_incomplete`，任何候选都无法获交易批准——即使 G0 和因子检验全过。
