# FX Portfolio System

> 🤖 **AI agent 请先读 [`AGENTS.md`](./AGENTS.md)。** 那里有项目使用说明、当前状态、红线、运行环境与关键命令。
> 本 README 是人向功能介绍，**可能滞后于实际进展**（例如仍写 7 品种，实际已 14 品种）；
> 一切以 `AGENTS.md` 和 [`docs/PROJECT_HANDOFF_SUMMARY_ZH.md`](./docs/PROJECT_HANDOFF_SUMMARY_ZH.md) 顶部「2026-08-02 更新」节为准。
>
> 一句话现状：**外汇量化因子挖掘研究系统（本地基础设施），14 品种 Dukascopy 行情已通过正式 intake；尚未批准任何交易策略。**

一个面向常见外汇货币对的本地研究、组合回测、策略筛选和模拟交易系统。系统默认交易
`EURUSD / GBPUSD / USDJPY / USDCHF / AUDUSD / NZDUSD / USDCAD`，强调低目标/止损比、
周内持仓和跨货币组合风控。

> 这是研究与模拟交易软件，不承诺盈利，也不构成投资建议。默认配置不连接真实账户；
> OANDA 适配器只允许 `fxPractice` 域名，代码层禁止生产域名。

## 已实现

- 六类候选策略：regime-aware 均值回归、趋势回踩、伦敦时段突破、假突破反转、
  全货币图强弱反转、滚动 Engle–Granger 协整价差。
- 60+ 个价格、波动、结构、日历、横截面和多货币图因子；三重障碍标签、训练内概率校准、
  purged walk-forward、成对 block bootstrap、FDR 校正、动态成本期望 R 和一次性 holdout。
- Broker bid/ask OHLC、历史 spread/swap、point-in-time 利率/forward points、carry 因子，
  免费 CFTC 周频仓位因子，以及带搜索预算和完整谱系的受约束因子 DSL。
- 信号只用已收盘 K 线，最早在下一根 K 线开盘执行，避免 look-ahead。
- 每个策略目标/止损比低于 0.85；全局硬上限 0.85；最长持仓硬上限 168 小时。
- 共享币种敞口：同时持有 EURUSD 与 GBPUSD 时，美元风险会合并，而不是当作独立资产。
- 组合风险：单笔风险、总风险、总杠杆、单币种敞口、相关簇、单日亏损和回撤熔断。
- 成本模型：逐品种点差、滑点、双边佣金、可配置 long/short swap，周三三倍 swap。
- 保守回测：同一根 K 线同时触发止损与止盈时按止损成交。
- 策略横向筛选、滚动 walk-forward 样本外选择、可复现 manifest 和数据 SHA-256。
- 公共 Yahoo midpoint、Dukascopy bid/ask tick、CSV 和相关多货币合成数据适配器。
- 搜索历史注册表、BH/BY 多重检验、共享日期块重采样、负对照和 future-information canary。
- 21/42/63 日资本守恒 sleeve 与主账户净额目标；组合收益仍须等待 Dukascopy 和历史融资验证。
- 无副作用的模拟订单计划，以及必须显式确认的 OANDA `fxPractice` 下单适配器。

## 快速开始

需要 Python 3.11+ 和 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync --all-extras
uv run fxtrade validate-config -c configs/demo.yaml
uv run fxtrade backtest -c configs/demo.yaml
uv run fxtrade screen -c configs/demo.yaml
uv run fxtrade walk-forward -c configs/demo.yaml --train-bars 1200 --test-bars 400
uv run fxtrade factor-download -c configs/factors_daily.yaml
uv run fxtrade factor-mine -c configs/factors_daily.yaml
# 只在旧 holdout 之前运行第二轮严格 FDR 开发研究
uv run fxtrade factor-mine -c configs/factors_daily_round2_dev.yaml
# 无外部凭证的 bid/ask + carry + DSL 软件验收
uv run fxtrade factor-mine -c configs/factors_carry_synthetic.yaml
# 正式 2016–2025 原始 tick 任务使用 v1.1 单文件 SQLite 下载器；完整流程见下文
uv run python scripts/download_dukascopy_sqlite.py --version
# 实盘级数据准备完成后先审计，再进行开发研究
uv run fxtrade factor-data-audit -c configs/factors_broker_carry_dev.yaml
# 可选的 CFTC 探索路径；approximate 发布时间不会生成可晋级候选
uv run fxtrade cftc-download --start-year 2006
uv run fxtrade factor-mine -c configs/factors_broker_carry_cftc_exploratory.yaml
# 免费官方隔夜/政策参考利率；只有来源明确标为 OIS 的列会设 is_ois=true
uv run python scripts/download_official_fx_rates.py --output data/official_rates
# 免费补充数据；current-vintage 快照和真实 vintage 分开保存
uv run python scripts/download_fx_supplemental_data.py --output data/supplemental_fx
uv run python scripts/download_phillyfed_rtdsm.py --output data/supplemental_fx
uv run python scripts/download_phillyfed_spf.py --output data/supplemental_fx
# 独立的 1–3 个月慢周期研究，不受 168 小时短周期上限影响
uv run fxtrade long-horizon-build -c configs/long_horizon_free.yaml
uv run fxtrade long-horizon-screen -c configs/long_horizon_free.yaml
# SQLite 到达后先做 outcome-blind 冻结；此命令不生成标签或组合收益
uv run fxtrade dukascopy-intake-ledger \
  --database-dir data/dukascopy_sqlite
# 只有 EURUSD/GBPUSD 时可先验收真实边界；此命令不生成标签、收益或仓位
uv run fxtrade dukascopy-two-symbol-commission \
  --database-dir data/dukascopy_sqlite
uv run fxtrade long-horizon-freeze-sqlite \
  --database-dir data/dukascopy_sqlite \
  -c configs/long_horizon_dukascopy_sqlite.yaml \
  -d configs/long_horizon_dukascopy_candidates.yaml
# 每轮查看结果后必须登记并验证搜索暴露
uv run fxtrade research-registry-audit \
  -r configs/factor_research_registry.yaml \
  -o outputs/research_registry_audit.json
# 只有 candidate verdict 生成 frozen_factor_model.json 后才能运行
uv run fxtrade factor-forward-evaluate \
  --model outputs/factors_broker_carry_dev/frozen_factor_model.json \
  -c configs/factors_broker_carry_forward.yaml
```

示例回测使用合成数据，只验证系统行为，不能验证策略收益。产物写入 `outputs/`：

```text
metrics.json           组合和交易指标
trades.csv             每笔交易、成本、R multiple、持仓时间、退出原因
equity.csv             权益、浮盈亏、杠杆和回撤时间序列
signals.csv            实际进入引擎的收盘信号
rejected_signals.json  被哪条风控规则拒绝
run_manifest.json      完整配置、代码版本、数据范围和数据哈希
report.md              人类可读报告
```

## 使用公共历史行情

Yahoo 只适合研究，不是 broker 可成交 bid/ask：

```bash
# 默认拉取 1h 后重采样为 4h；Yahoo 通常只提供最近约 730 天的小时数据
uv run fxtrade download -c configs/default.yaml
uv run fxtrade backtest -c configs/default.yaml
uv run fxtrade screen -c configs/default.yaml
```

生产前应换成目标 broker 的历史 bid/ask，并把真实 spread 与 swap 填入配置。CSV 格式：

```csv
timestamp,open,high,low,close,volume
2025-01-02T00:00:00Z,1.1030,1.1042,1.1022,1.1038,1000
```

每个文件以货币对命名，例如 `data/EURUSD.csv`。

## 使用 Dukascopy 双边 tick

Dukascopy 的公开历史数据不需要 token。正式 2016–2025 原始数据任务使用
`download_dukascopy_sqlite.py` v1.1.1；公开仓库为
<https://github.com/jlcbk/dukascopy-sqlite-downloader>，当前发布提交为 `63ee417`。
它按 UTC 小时拉取 LZMA `bi5` bid/ask tick，把原始压缩 payload 保存为每个品种
一个 SQLite，然后在本机按需聚合：

```bash
uv run python scripts/download_dukascopy_sqlite.py download \
  --start 2016-01-01 --end 2026-01-01 \
  --database-dir ./dukascopy_sqlite
```

v1.1 的默认下载宇宙是 14 个品种：原慢周期 12 个货币对加 `USDNOK` 和
`USDSEK`。这是数据宇宙，不是 FIX-W 组合权重；正式 FIX-W 只使用
AUD/CAD/CHF/EUR/GBP/JPY/NOK/NZD/SEK 九个冻结 G9 美元腿。下载结束后必须一并
传输每库 `.sha256` / `.json` 和 `_sqlite_manifest.json`；整库 SHA-256、SQLite
`quick_check`、schema/metadata/parser/source 未全部通过时，正式事件 runner 会硬失败。

`fxtrade factor-download -c configs/dukascopy_bid_ask_download.yaml` 仍是兼容的直接聚合入口，
但该冻结配置只含 12 个品种且结束于 `2025-09-15`，不得当作完整 2016–2025
FIX-W 数据契约。两条路径的 4h bar 都只在四个源小时完整时保留，且 manifest
记录解析版本与 CSV SHA-256。Dukascopy 是单一报价源；最终 paper/上线前仍须用
目标 broker 校准 spread、slippage 与 swap。

完整 14 库到齐前不必闲置。`dukascopy-intake-ledger` 同时输出慢周期 12 对、FIX-W 9 腿和
全量 14 库三个独立 readiness gate。当前仅有 EURUSD/GBPUSD 时，可以运行
`dukascopy-two-symbol-commission`，用真实 payload 检查纽约 17:00 DST 边界和 Tokyo/WMR/纽约
事件窄窗。该路径永远标记为 `research_only`，不接受 batch manifest 的本地替代品，也不生成
收益标签、因子评价或交易批准。

免费仓位数据可直接从 CFTC Traders in Financial Futures 年度档案下载：

```bash
uv run fxtrade cftc-download --start-year 2006
```

系统只取 AUD/CAD/CHF/EUR/GBP/JPY/NZD 期货，以 USD 为中性锚，生成交易商、资管和杠杆资金
净仓位比例、4 周变化与 156 周 z-score。报告日后统一延迟 60 天才允许因子使用，以覆盖
正常周五发布时间和已知的政府停摆积压；代价是信号明显变慢。由于这仍不是逐期实际发布
时间档案，默认标记为 `approximate`，只能探索、不能晋级交易候选。年度 ZIP 会缓存，并把
URL、SHA-256、获取时间和标准化 CSV 哈希写入 sidecar manifest。

免费官方利率下载器归档 NY Fed、ECB、BoE、BoC、RBA 和 SNB 的原始响应，并生成统一的
`official_rate_observations.csv`：

```bash
uv run python scripts/download_official_fx_rates.py \
  --output data/official_rates \
  --refresh
```

隔夜基准和政策利率只作为探索参考，不会被重命名成 OIS；当前只有 RBA 原始列明确命名的 AUD
1M/3M OIS 标记为 `is_ois=true`，NZD 官方主源仍缺。

补充下载器归档 Pink Sheet、GSCPI、GEPU、GPR、OFR FSI、ECB CISS、BoC BCPI、RBA I2，
以及 Cboe EVZ/EUVIX/JYVIX/BPVIX。其中 OFR/CISS/BCPI/RBA/Cboe 的历史行以首次抓取时点
作为 `available_time`，不会用人为发布滞后伪造 PIT。Philadelphia Fed RTDSM 另保存 CPI/IP
的完整 vintage 矩阵；精确发布时间未知时，
至少推迟到下一个纽约自然日或下月开始。SPF 工具只把 2016–2025 的 40 个官方发布日期
标准化为日期级事件日历；均值/中位数工作簿是带勘误的当前合并历史，不会被标成逐季
as-published PIT 数值。两类下载都保留原始快照、SHA-256 和历次 manifest。

Tokyo 09:55、ECB 14:15、WMR 16:00 的 2016–2025 官方事件日历可用以下命令生成：

```bash
uv run python scripts/download_wmr_publication_calendar.py \
  --output-dir data/benchmark_calendars --refresh
```

输出包含 10,959 个逐自然日事件状态、官方原始 PDF/ECB CSV、逐文件 SHA-256 和 calendar
manifest；Tokyo、ECB、WMR 分别有 2,575、2,560、2,580 个发布日，三类同时发布的
FIX-W 日为 2,557 个。calendar SHA-256 为
`226dada52f60d22d8c1a386f8ef6042457b2c9930ab90bafc67398e1b8011046`。正式 runner
调用方必须用 `load_publication_calendar(..., require_manifest=True)` 加载；缺少 manifest
或任一 raw hash 不一致时会直接拒绝。`run_fix_w_from_sqlite` 接收已加载的 calendar，
其下游正式构造层仍会硬检查 `formal_experiment` 和 `manifest_verified`；不会在每个窄窗内
重复计算 calendar/raw 哈希。WMR 例外表目前由官方 PDF 逐行人工转录，关键半日市
有测试覆盖，但尚未实现 PDF 文本的自动反解校对。

八央行政策公告 blackout 日历的统一下载入口为：

```bash
uv run python scripts/download_central_bank_calendar.py \
  --output-dir data/central_bank_calendars --refresh
```

当前 v1 已完成 Fed、ECB、BoJ、RBA 四个官方适配器，真实站点审计分别得到
81、82、81、105 条事件。Fed 81 条和 BoJ 2018–2025 的 65 条只在官方正文逐次明确写出
发布时间时才标为 `verified_actual_publication`；ECB/RBA 固定时刻是
`official_rule_derived`，BoJ 2016–2017 和紧急事件缺时刻时使用当地自然日全天 blackout。
BoE、SNB、BoC、RBNZ 仍在 manifest 中显式标成 `fail_closed`，因此正式加载默认会拒绝
当前局部产物；开发审计只能显式传入 `require_complete=False`。任一 raw 或 SHA sidecar
被修改也会拒绝加载。

正式 FIX-W SQLite runner 在一次运行内对 9 个必需数据库各做一次整库传输验证，
每个合格事件日只提取 6 个独特边界邻域（共 54 个库—边界窄窗），且窄窗仍逐 payload
复验 SHA-256。任一源小时不完整都会清空影响腿和整日 G9 组合，不会用其他腿
重归一化。日内统计层只使用完整候选集的共同事件日、joint stationary bootstrap、
BH 主门槛/BY 敏感性、联合符号负对照、future-information canary 和 DSR/PBO/SPA
输入诊断；它只输出研究审计，不自动批准交易。

## 1–3 个月慢周期因子研究

慢周期研究使用下一交易日开盘入场、21/42/63 交易日标签、21 日调仓、严格 purge、8 年训练和
2 年非重叠 OOS。方向因子预测收益方向，风险状态因子只预测绝对收益，不会混为一类：

```bash
uv run fxtrade long-horizon-build -c configs/long_horizon_free.yaml
uv run fxtrade long-horizon-screen -c configs/long_horizon_free.yaml
```

当前免费数据 v4 共 43 个因子、每折 129 个检验；没有方向因子通过统一 FDR。仅两个风险状态
检验在第 0 折入选，且都在 OOS 翻号，因此也已拒绝。不能据此声称存在盈利策略。完整方法、
搜索暴露和 Dukascopy 到达后的验证顺序见慢周期研究手册与 2016–2025 执行路线。

正式 SQLite 入口只验证传输数据库、构造严格共同纽约收盘日线，并为注册表中的 7 个慢周期
方向单元冻结 close-t decision / next-open / scheduled-close 信号。输出的
`proposed_tranche_weight` 不是资本权重；次日开盘账本、重叠 sleeve、币种换算、历史融资、
slippage 和冻结后新前向证据未齐前，不生成正式净收益或交易批准。

## 模拟交易边界

先生成无副作用计划：

```bash
uv run fxtrade paper-plan -c configs/default.yaml
```

策略必须先在配置中显式设为 `paper_enabled: true` 才会进入计划。当前实证筛选没有候选通过，
所以默认计划为空；仅为验证执行软件时可用 `--include-unapproved`，输出仍不会自动提交。

只有 OANDA 模拟账户可提交，且必须同时具备环境变量和显式确认：

```bash
export OANDA_PRACTICE_ACCOUNT_ID='...'
export OANDA_PRACTICE_TOKEN='...'
uv run fxtrade oanda-practice-submit --plan outputs/paper_plan.json --confirm-practice
```

适配器拒绝 `api-fxtrade.oanda.com`。订单计划与提交刻意拆开，便于人工复核。

## 文档

- [架构与数据流](docs/ARCHITECTURE_ZH.md)
- [策略筛选目录](docs/STRATEGY_CATALOG_ZH.md)
- [开源项目选型](docs/OPEN_SOURCE_SELECTION_ZH.md)
- [验证和上线门槛](docs/VALIDATION_AND_LAUNCH_ZH.md)
- [2026-07-15 实证筛选记录](docs/EMPIRICAL_SCREENING_2026-07-15_ZH.md)
- [多因子挖掘系统与最终实证](docs/MULTIFACTOR_RESEARCH_ZH.md)
- [第二轮成对因子挖掘记录](docs/FACTOR_ROUND2_2026-07-15_ZH.md)
- [Broker 报价、Carry 与受约束因子挖掘](docs/BROKER_CARRY_DISCOVERY_ZH.md)
- [1–3 个月外汇多因子研究手册](docs/LONG_HORIZON_FACTOR_RESEARCH_ZH.md)
- [外部数据下载计划](docs/EXTERNAL_DATA_DOWNLOAD_PLAN_ZH.md)
- [Dukascopy SQLite 下载与本机聚合](docs/DUKASCOPY_SQLITE_DOWNLOADER_ZH.md)
- [2016–2025 因子研究执行路线](docs/RESEARCH_EXECUTION_ROADMAP_2016_2025_ZH.md)
- [外汇因子与验证方法文献地图](docs/FX_FACTOR_LITERATURE_MAP_ZH.md)
- [项目交接与后续执行计划](docs/PROJECT_HANDOFF_SUMMARY_ZH.md)
