# 1–3 个月外汇多因子研究手册

更新日期：2026-07-16。当前实现版本：`long-horizon-v5`。

## 当前结论

系统已经具备慢周期因子的无泄漏构建、训练内多重检验和非重叠样本外诊断能力，但尚未发现
可以声称盈利的方向因子，也没有冻结任何交易模型。目标账户 2016–2025 历史
swap/rollover 或同口径真实远期点仍缺失，因此即使 Dukascopy 价格审计通过，慢周期
正式策略组合也必须 fail closed，不得把不完整成本结果写成历史净收益。

免费 Yahoo midpoint 数据的 v4 基线结果位于
`outputs/long_horizon_free_screen_v4/`：

| 项目 | 结果 |
|---|---:|
| 历史长度 | 20.12 年 |
| 品种 | 12 个货币对 |
| 因子 | 43 个 |
| 持有期 | 21 / 42 / 63 个交易日 |
| 非重叠 OOS 折 | 5 个，每折 2 年 |
| 每折统一 FDR 假设数 | 129 |
| 总训练假设数 | 645 |
| 训练入选 | 2 |
| 方向因子入选 | 0 |
| 入选后的 OOS 同号 | 0 / 2 |
| 在两个或以上训练折重复入选 | 0 |

2 次入选全部来自第 0 折，且都是预测未来**绝对收益/波动状态**的 63 日非方向因子：NFCI
和 STLFSI。两者 OOS 都翻号，因此当前连风险开关资格也没有，更不能直接决定买卖方向。
其余四个训练窗没有因子通过统一 FDR；方向 Momentum、Trend、Value、商品货币、仓位拥挤
和公开利率参考均未晋级。

`data_audit.json` 仍把该结果标为 `software_or_exploratory` 和
`empirical_ready=false`。主要原因是 Yahoo 不是可成交 bid/ask，12 个品种共同日期覆盖只有
最低严格覆盖约 92%，宏观数据多为 current-vintage，CFTC 发布时间是保守近似且数值来自
会修订的 Historical Compressed 当前档案而非 as-published vintage，标签也没有目标账户融资费。

## v5 的时间与统计契约

1. 因子只使用 `_feature_time` 当时已经可得的数据；外部数据按 `available_time` 向后合并。
2. 信号日之后的下一交易日开盘才入场；21/42/63 日标签都记录独立的 label end time。
3. 训练样本必须满足最长 63 日标签在 OOS 开始前已经结束，边界样本会被 purge。
4. 只在每 21 个交易日的 `_rebalance_eligible` 时点计算训练和 OOS 统计；不把每日重叠标签
   当作独立交易机会。
5. 8 年训练、2 年 OOS、2 年步长，因此 OOS 窗口互不重叠。
   `empirical_ready` 还要求至少 3 个完整 walk-forward 折；一个 OOS 折只能用于有限确认。
6. 每折将 43 个因子 × 3 个期限的 129 个 p 值放在同一个 Benjamini–Hochberg FDR 家族中，
   不按因子家族拆分以逃避多重检验惩罚。
7. bootstrap 时间块为 63 个交易日；在 21 日调仓频率下严格换算成 3 个调仓观测。
8. 方向因子用每日横截面 Spearman IC；非方向风险因子只预测未来绝对收益状态。
9. bid/ask 数据到齐后，long 用 ask 入/bid 出，short 用 bid 入/ask 出；Yahoo 阶段只保留
   midpoint 标签，不能估算真实可成交利润。

v1 曾把所有日度行送入筛选，并把 63 个交易日误当作 63 个调仓观测。v2 修正单位，但只有
1,000 次 bootstrap，无法分辨 111 个检验的首条 BH 阈值，因此也已失效。v3 用 20,000 次
bootstrap 重跑 37 因子，仍只有两个风险状态在首折入选且 OOS 翻号。v4 增加 6 个预注册
补充因子，总数 43，结论仍为拒绝。v5 只增加纽约 17:00 日线的精确首末报价时间契约，
尚未运行新的因子筛选；上表仍是 v4 Yahoo 基线。所有无效/失败轮次都保留在搜索账本，
不能选择性遗忘。

## 免费数据阶段怎么用

刷新免费数据：

```bash
uv run python scripts/download_fx_reference_data.py \
  --output data/external_raw

uv run fxtrade cftc-download \
  --start-year 2006 \
  -o data/point_in_time/currency_positioning.csv

uv run python scripts/download_official_fx_rates.py \
  --output data/official_rates \
  --refresh

uv run python scripts/download_oanda_financing_history.py \
  --output data/oanda_financing_us

uv run python scripts/download_fx_supplemental_data.py \
  --output data/supplemental_fx

uv run python scripts/download_phillyfed_rtdsm.py \
  --output data/supplemental_fx
```

构建和筛选：

```bash
uv run fxtrade long-horizon-build \
  -c configs/long_horizon_free.yaml \
  -o outputs/long_horizon_free_build

uv run fxtrade long-horizon-screen \
  -c configs/long_horizon_free.yaml \
  -o outputs/long_horizon_free_screen_v4
```

这一阶段只用于：验证软件、排除明显无效假设、观察因子方向是否稳定、制定下一轮有限且有经济
含义的候选。不能根据全样本最好 IC 反复改参数，也不能把 Yahoo 结果写成收益承诺。

## Dukascopy 数据到达后的操作顺序

### 1. 验证转移文件

数据库、每库 `.sha256`/`.json` 和 `_sqlite_manifest.json` 应放在同一目录。先做哈希和 SQLite
完整性校验，再做逐小时 payload 深度解码：

```bash
uv run python scripts/download_dukascopy_sqlite.py verify \
  --database-dir ./dukascopy_sqlite

uv run python scripts/download_dukascopy_sqlite.py verify \
  --database-dir ./dukascopy_sqlite \
  --deep
```

不得跳过失败库、手工修改数据库或用 `--allow-incomplete` 生成正式研究数据。

### 2. 在本机聚合 4h bid/ask

`--start` 和 `--end` 必须与 VPS 下载任务记录的请求区间一致，end 是 UTC 排他边界：

```bash
uv run python scripts/download_dukascopy_sqlite.py aggregate \
  --database-dir ./dukascopy_sqlite \
  --output-dir ./data/dukascopy_bid_ask \
  --start 2016-01-01 \
  --end 2026-01-01 \
  --interval 4h
```

`--start` / `--end` 仍必须与传输 manifest 记录的请求区间一致；上述命令是 v1.1 冻结
2016–2025 契约。v1.1 默认聚合输出包含 14 个 CSV 和 `_data_manifest.json`，这是下载
宇宙；`configs/long_horizon_dukascopy.yaml` 仍只消费其中冻结的 12 个慢周期货币对。
新增的 `USDNOK` / `USDSEK` 是补齐 FIX-W G9 数据腿，不会自动进入慢周期因子宇宙。
每根 4h bar 只有四个源小时状态完整时才生成；manifest 记录缺失小时、解析版本和
CSV SHA-256。

### 3. 先冻结 factor-only 调度，不生成未来收益

```bash
uv run fxtrade long-horizon-freeze-sqlite \
  --database-dir ./dukascopy_sqlite \
  -c configs/long_horizon_dukascopy_sqlite.yaml \
  -d configs/long_horizon_dukascopy_candidates.yaml \
  -r configs/factor_research_registry.yaml \
  --start 2016-01-01 \
  --end 2026-01-01 \
  -o outputs/long_horizon_dukascopy_freeze
```

这个入口只串联整库/逐小时哈希验证、纽约 17:00 共同日线、当时可得因子和下一交易日开盘
目标调度。它不会生成 `_forward_*`、`_label_*`、walk-forward folds 或 portfolio return。
候选声明必须与注册表中全部 `slow + preregistered + directional` 单元逐项相符：商品货币
3 个期限、Value×Trend 2 个期限、Positioning crowding reversal 2 个期限，共 7 个；deferred
carry 不会被静默纳入，非方向 risk state 不能生成买卖目标。累计 trial disclosure 不得低于
注册表已经暴露的 3,312 次 factor-outcome evaluation。

必须先检查：

- 每个品种的起止时间和市场覆盖；
- bid/ask 非交叉、spread 分布和异常尾部；
- 12 品种共同调仓日期；
- 21/42/63 日 decision close → next-session open → scheduled close 的时间顺序；
- 外部数据 available time、staleness 和资格标记；
- manifest 中所有输入哈希。

当前 Dukascopy 任务从 2016 年开始，约 10 年，只够 8 年训练 + 2 年 OOS 的最低边界，无法
独立提供多个非重叠长期 OOS 折。正确做法是用 20 年免费数据提出有限假设，再用 Dukascopy
确认成交侧、点差和近十年稳健性；不能把两套数据反复来回筛选直到显著。

### 4. 只有预先冻结候选才能做执行级确认

免费阶段若未来出现方向候选，先冻结以下内容，再打开 Dukascopy OOS：

```text
factor name + formula
expected sign
holding horizon
rebalance rule
normalization and missing-data rule
eligible symbols
risk scaling rule
all rejection thresholds
input hashes and freeze timestamp
```

当前 7 个冻结单元只是既有预注册假设的完整评估调度，并不表示任何方向因子已经通过，更不是
交易模型。现有波动状态因子可以另开风险模型研究，但必须与方向 alpha 的 FDR 家族、标签和
结论分开。

冻结入口故意在组合账本前 fail closed。现有组合 runner 是调仓日收盘成交语义，不能冒充
long-horizon 的次日开盘成交；其 sleeve 数值还是抽象目标权重，不能直接当作不同报价尺度的
实际 quantity。CSV 中的 `proposed_tranche_weight` 只是“单候选、单次 vintage”的横截面信号，
不是最终组合资本权重；21 日调仓下的 42/63 日 tranche 会重叠，7 个候选之间也尚未冻结资金
预算或 benchmark。正式组合继续要求：次日开盘成交并在当日收盘 MTM、overlapping sleeve
资本守恒、跨候选预算、NAV×权重到数量的账户币种换算、provider-native 历史 financing/真实
可交易 forward 成本、charge-currency 转账户币种、slippage、commission/其他 broker fees、
逐品种真实 quote timestamp/staleness，以及跨币种未实现 PnL 的 cost basis/settlement。缺任何
一项都不生成“净收益”，缺融资不能按 0 填充。

正式次日开盘账本的事件顺序也必须提前固定，不能把旧的 close-to-close runner 整体平移一天：

1. `decision close(t)` 只读取当时已经收盘的因子，不成交；
2. 旧仓位先跨过纽约 17:00 rollover，按该时点的真实 long/short、计息天数和费用币种记
   financing，再用新 session 的第一笔合格报价标记隔夜价格变化；
3. `next open(t+1)` 才将新 vintage 的资本权重按交易前 NAV 和当时 FX conversion graph 转成
   base-currency quantity；所有新开/存续调整先在主账户净额化，再按 ask 买入、bid 卖出并扣
   冻结的 adverse slippage；
4. 新旧仓位从 open 标记到该 session 的最后一笔合格 close 报价；到期 vintage 在 close 以
   bid 平多仓、ask 平空仓，不能推迟到下一日开盘；
5. 只有上述价格 PnL、两端 spread、slippage、financing、cash interest 和币种换算全部在同一
   账户币种勾稽后，才形成一行净收益。

按这个边界，`H` 日标签从 `t+1` 开盘持有到 `t+H` 收盘，包含 `H` 个日内区间，但通常只跨
`H-1` 个持仓 rollover；节假日多倍计息必须读取 broker 记录，不能从星期几机械猜测。实际
扣费时点和是否在边界前后持仓仍以目标 broker 的账户合同为准。独立两阶段合成账本已经实现
并验证上述顺序、净额化和 NAV 恒等式，但尚未接入正式 runner。它的非 USD multiplier 只适用
于“每个边界以账户币种现金结算/重置 mark”的显式假设；真实 rolling-spot broker 的未实现
PnL 若按持仓成本价持续换算，还必须跟踪 lot cost basis 与 quote liability。现有
`portfolio_runner.run_portfolio` 仍只可作为通用 close-to-close 组件，不可用于正式慢周期结果。

## 晋级门槛

一个慢周期方向因子至少同时满足：

- 训练内通过预先定义的统一 FDR，而不是单独 p 值显著；
- 在多个非重叠 OOS 窗口同号，且不是只由单一危机区间贡献；
- 12 个相关货币对按时间块/货币图处理，不伪装成独立样本；
- Dukascopy long/short 可成交收益扣除历史 spread、滑点和可用融资费后仍有余量；
- 对调仓日、持有期、winsorization 和缺失规则的小幅扰动不翻号；
- 不依赖 current-vintage 宏观值、近似发布时间或来源不一致的免费利率才能成立；
- 冻结后只做一次最终 holdout，失败就淘汰，不在 holdout 上继续调参。

通过因子筛选仍不等于策略盈利。后续还需要组合权重、共享币种敞口、换手、融资、极端 spread、
容量和回撤约束的完整组合回测；任何一步未通过都不能进入 paper trading。

## 下一轮开发优先级

1. 数据到达前：保持下载器、聚合器、manifest 和慢周期测试可复现；每次代码变更跑全套测试。
2. 数据到达后：先验证/聚合/审计，再复算固定的 43 因子，不立即扩大搜索空间。
3. 若价格与执行契约通过：单独开发风险状态模型，验证它是否改善既定方向策略的回撤和仓位，
   不把它包装成方向 alpha。
4. 只有在基线审计后，再加入少量预注册的经济交互，例如 Value×Trend、Positioning crowding
   × reversal、Trend×volatility scaling；每个交互都计入同一个搜索预算和 FDR。
5. 严格 carry 等八币种同口径 OIS/真实 forward points 或目标 broker 历史 swap 到齐后再开；
   免费政策/隔夜利差继续保持探索资格。
