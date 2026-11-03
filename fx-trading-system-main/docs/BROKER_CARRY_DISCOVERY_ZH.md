# Broker 报价、Carry 与受约束因子挖掘

## 已完成的开发范围

这一阶段把系统从“midpoint 技术因子验证器”扩展为以下完整研究链路：

```text
Dukascopy tick / OANDA fxPractice bid/ask 或双边 CSV
        + 历史 spread / swap
        + point-in-time 利率和 forward points
                         │
                         ▼
          Carry 因子 + 原有价格因子
                         │
                         ▼
         有预算、可追踪谱系的因子 DSL
                         │
                         ▼
  paired bootstrap + FDR + purged walk-forward
                         │
                         ▼
       1.0x / 1.5x / 2.0x 成本压力测试
                         │
                         ▼
       rejected / 新 holdout / paper 候选
```

软件链路已经可以运行，但仓库不包含用户的 OANDA token、商业 forward 数据或历史融资
记录。合成数据端到端运行仅用于验证软件，不是盈利证据。

## Bid/ask 数据

当前无凭证的长历史入口优先使用 Dukascopy。下载器读取每小时 UTC `bi5` 文件（月目录为
0-based），按大端 20-byte tick 契约解码 ask/bid 和报价量，并以明确的 JPY/非 JPY
instrument metadata 缩放价格。每个小时在写入不可变缓存前必须通过 LZMA、长度、时间偏移、
非负有限报价量和 ask ≥ bid 校验：

```bash
uv run fxtrade factor-download \
  -c configs/dukascopy_bid_ask_download.yaml \
  -o data/dukascopy_bid_ask
```

1h OHLC 从逐 tick 双边报价独立聚合；mid high/low 由同一 tick 的 midpoint 聚合，不是把
bid/ask 的独立极值相加平均。4h 必须恰有四个完整源小时，不补值、不制造空 bar；当前未完成
小时根本不下载。缓存支持首次长下载中断续传，CSV manifest 保留来源、源小时覆盖率、解析器
版本、价格 divisor 和 CSV SHA-256。

OANDA 仍可作为有 practice token 时的另一条数据入口。其下载器只允许
`https://api-fxpractice.oanda.com`，请求 `price=BA`，分页拉取完整 candle，拒绝真实交易域名。
使用方式：

```bash
export OANDA_PRACTICE_TOKEN='...'
uv run fxtrade factor-download \
  -c configs/oanda_bid_ask_download.yaml \
  -o data/oanda_bid_ask
```

CSV 每行至少包含：

```text
timestamp
bid_open,bid_high,bid_low,bid_close
ask_open,ask_high,ask_low,ask_close
volume
```

系统从双边价格派生 mid OHLC，并检查：双边各自 OHLC 合法、ask 不低于 bid、时间 UTC、
排序、重复和不完整 candle。回测中：

- 多头按 ask 入场、bid 平仓；空头按 bid 入场、ask 平仓。
- 多头止盈止损检查 bid high/low；空头检查 ask high/low。
- spread 压力测试围绕 mid 放大实际双边报价，不再用固定 spread 替代。
- `spread_atr` 与 `spread_z_20` 把当时可见的执行拥挤状态作为非方向因子。

## 历史 swap

OANDA candle API 不返回历史融资费率，因此每个品种需要独立的 point-in-time 文件：

```csv
available_time,swap_long_pips,swap_short_pips
2025-01-02T22:00:00Z,-0.72,0.31
```

文件放在 `data/historical_swaps/EURUSD.csv` 等路径。系统只向后 as-of join，不会把未来费率
回填到过去；超过配置的 staleness 后视为缺失。示例见
`examples/swaps/EURUSD.example.csv`。

## Point-in-time 利率与远期数据

利率文件 `currency_rates.csv`：

```csv
observation_time,available_time,currency,policy_rate,ois_1m,ois_3m,ois_source,ois_provenance,ois_quote_quality
2025-01-29T00:00:00Z,2025-01-29T19:00:00Z,USD,4.50,4.32,4.25,licensed_vendor,vendor_ois_archive/v1,historical_market_ois_quote
```

远期文件 `forward_points.csv`：

```csv
observation_time,available_time,symbol,forward_points_1m,forward_points_3m,spot_reference,source,provenance,quote_quality
2025-01-31T16:00:00Z,2025-01-31T16:00:01Z,EURUSD,0.00165,0.00492,1.0390,licensed_vendor,vendor_forward_archive/v2,historical_market_quote
```

`observation_time` 表示数据对应时期，`available_time` 表示市场真正可知的时间。修订值可以
具有相同 observation time，但必须有更晚的 available time。因子合并只允许
`available_time <= feature_time`。forward points 使用货币对价格单位，不是 pip 数；
`spot_reference` 是同一 forward 快照对应的即期价，防止用未来或错位 spot 年化。

每一行还必须声明来源、可复核的数据集/版本 provenance 和报价质量。正式晋级只认可
`ois_quote_quality=historical_market_ois_quote` 与
`quote_quality=historical_market_quote`。以下标签可供探索或软件验收，但严格市场覆盖率恒为
零：`policy_rate_proxy`、`overnight_rate_proxy`、`synthetic_curve`、
`synthetic_interest_parity`、`broker_financing_proxy`、`software_synthetic` 和
`unknown_unverified`。也就是说，即使把政策利率数值复制进 `ois_1m/ois_3m`，非空值覆盖率
也不能冒充 OIS 覆盖率。

此外，两个 CSV 各自必须有相邻的 `currency_rates.manifest.json` 和
`forward_points.manifest.json`。manifest 使用 `schema_version=1`，写明 `dataset_kind`、精确
CSV 字节的 `csv_sha256`，并在 `source_catalog` 中逐项声明行内出现的
`source/provenance/quote_quality` 三元组；利率文件的行内 `ois_*` 字段映射到同一三元组。
只在 YAML 声明“高质量来源”不能自证。正式 broker 配置要求 manifest、哈希、逐行元数据和
质量标签同时通过；模板见 `examples/point_in_time/*.manifest.example.json`。
仓库示例故意使用 `unknown_unverified`，即使补上正确哈希也只能验证解析流程，不能让研究晋级。

实现的 carry 因子：

- `rate_differential`：base 减 quote 的政策利率差。
- `curve_slope_differential`：两种货币 OIS 3M–1M slope 之差。
- `forward_discount_1m`：按 30 天年化的 1M forward discount。
- `carry_to_vol_20`：利率差除以 20-bar 年化波动率。

免费数据不能可靠替代商业 OIS 与可交易 forward 历史。系统不会把普通短端利率重命名为
OIS，也不会用利率平价合成 forward points 后再把它当成独立市场证据；这两类文件缺失时
`broker_ready` 继续为 false。

## CFTC 周频仓位数据

CFTC Traders in Financial Futures 档案无需 token。官方 `2006–2016` 合并历史把七种主要
货币追溯到 2006 年 6 月，逐年文本档案从 2010 年 7 月开始；下载器合并重叠部分时优先保留
逐年档案并按货币/报告日去重。以下命令下载完整可用历史至当前年，
标准化七种非美元货币期货，并写入 point-in-time 目录：

```bash
uv run fxtrade cftc-download \
  --start-year 2006 \
  -o data/point_in_time/currency_positioning.csv
```

期货价格方向均解释为“外币兑 USD”；USD 自身作为 0 的中性锚，cross 则使用 base 减 quote。
系统使用报告日后 60 天作为 `available_time`，以覆盖常规周五发布和已知政府停摆造成的
积压；这不是逐期实际发布时间档案，而是有意牺牲新鲜度的保守近似。原始输入和派生因子包括：

- `cftc_dealer_net`：base 减 quote 的交易商净仓位/未平仓量；
- `cftc_asset_manager_net`：资管净仓位差；
- `cftc_leveraged_net`：杠杆资金净仓位差；
- `cftc_leveraged_change_4w`：杠杆资金净仓位比例的 4 周变化差；
- `cftc_leveraged_z_156`：最多 156 周窗口的杠杆仓位 z-score 差。

默认配置把 `positioning_release_quality` 标记为 `approximate`，因此 CFTC 因子只能做探索，
不能让研究晋级；只有补齐逐期真实发布时间并显式标记为 `verified` 后，仓位覆盖率不少于
80%、并把 bootstrap block 扩大到至少 13 个交易周，才能通过数据审计。CFTC 是低频、延迟
且只覆盖期货市场参与者的状态变量，不应被当作即时订单流。

严格开发配置 `factors_broker_carry_dev.yaml` 默认关闭近似 CFTC；探索运行使用：

```bash
uv run fxtrade factor-mine \
  -c configs/factors_broker_carry_cftc_exploratory.yaml
```

CSV 示例见 `examples/point_in_time/`。

## 受约束因子 DSL

DSL 不执行任意 Python 表达式，只允许配置中的原语和算子：

- 时序：`delta`、`ts_zscore`、`ts_mean`、`ts_std`；
- 横截面：`cs_rank`；
- 条件交互：一个方向因子乘一个非方向状态因子。

每个生成因子记录表达式、父因子、算子、窗口、复杂度和生成顺序。搜索预算由
`max_generated_factors` 硬限制，全部生成候选都计入同一折 FDR 的假设总数，不能只报告最后
入选的公式。

## 运行开发研究

准备 broker CSV、swap 和 PIT 文件后：

```bash
uv run fxtrade factor-data-audit -c configs/factors_broker_carry_dev.yaml
uv run fxtrade factor-mine -c configs/factors_broker_carry_dev.yaml
```

`factor-data-audit` 必须先显示 `broker_ready=true`：所有品种都有 bid/ask、最短历史不少于
8 年、swap 与 `historical_market_carry_coverage` 均不少于 80%，市场 bar 密度不少于 80%，跨品种共同时间戳
覆盖不少于 90%，已知源小时覆盖不少于 95%。时间网格、尾部完整性、来源 manifest 和 CSV
哈希也必须通过，任一未恢复的下载失败或超过 120 小时的市场数据中断都会阻止晋级。合成
数据、Yahoo midpoint、稀疏长跨度数据和来源不明的裸 CSV 永远不能通过这一门槛。
这里的 `carry_coverage`（等同于 `historical_market_carry_coverage`）要求政策利差、经 manifest
验证的真实 OIS slope 和经 manifest 验证的历史市场 forward discount 在同一行都可用。
仅检查非空数值的 `exploratory_carry_value_coverage` 只用于诊断，不参与晋级。旧裸 CSV 只能在明确设置
`allow_legacy_unverified_carry_rows=true` 的探索配置中继续运行；系统给它补
`unknown_unverified` 标签，因此政策率/合成远期不能绕过门槛。

该配置结束于 2025-09-15，不重用已经查看过的 Yahoo holdout。主要新增产物：

- `factor_catalog.csv`：固定与 DSL 因子的完整谱系；
- `oos_factor_statistics_by_fold.csv`：paired OOS IC、block-bootstrap p 和 FDR q；
- `cost_stress_by_fold.csv`：1x、1.5x、2x 成本结果；
- `factor_manifest.json`：市场数据哈希、PIT 数据哈希、搜索预算和最终 verdict。
- `frozen_model_status.json`：拒绝时说明原因；只有开发门槛通过才生成带 SHA-256 的
  `frozen_factor_model.json`。

没有真实外部数据时可运行软件验收：

```bash
uv run fxtrade factor-mine -c configs/factors_carry_synthetic.yaml
```

当前确定性合成验收测试了 89 个假设（含 20 个 DSL 表达式），基准成本复合收益 -5.38%，
1.5x 成本 -5.45%，最终为 `rejected_for_trading`。这证明拒绝路径、成本压力和产物工作正常，
不评价 carry 在真实市场中的有效性。

## 晋级逻辑

默认开发晋级至少要求：

- 每折存在通过配置筛选的因子；
- 总交易数不少于 100；
- 至少 75% 开发折盈利；
- 每折 PF 不低于 1.10；
- 1.5x 成本下复合收益仍为正。

开发门槛通过但没有新 holdout 时，只能得到 `research_candidate_requires_new_holdout`；
holdout 也通过时仍只能得到 `research_candidate_requires_paper`。系统不会自动批准真实交易。

## 冻结模型与前向期

只有上述 candidate verdict 才能冻结。模型 JSON 固化：入选因子及谱系、缺失值统计、标准化
参数、线性系数、Platt 校准器、收益假设、研究截止时间、DSL/因子配置和 contract SHA-256。
模型还锁定完整研究输入的逐品种终点、market/PIT 历史前缀哈希、来源/解析器语义和 PIT 配置。
任何历史修订、字段修改、因子实现版本改变、配置改变或品种集合变化都会拒绝前向运行；研究
时已经存在但未组成完整 walk-forward 折的尾部，也不会被冒充成新前向数据。

把严格晚于冻结时间的新 bid/ask、swap 和 PIT 数据追加到原目录后执行：

```bash
uv run fxtrade factor-forward-evaluate \
  --model outputs/factors_broker_carry_dev/frozen_factor_model.json \
  -c configs/factors_broker_carry_forward.yaml \
  -o outputs/factor_forward
```

该命令不重新筛选、不重新拟合，也不会下单；只生成 forward predictions、signals、trades、
equity 和 manifest。未达到配置的 90 天时状态为 `collecting`，达到后也只是
`duration_complete_requires_review`，仍需人工检查并继续累计到计划的 3–6 个月。
