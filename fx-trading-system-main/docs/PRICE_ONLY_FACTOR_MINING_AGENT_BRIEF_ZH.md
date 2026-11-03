# EURUSD/GBPUSD 纯价格因子挖掘 Agent 任务书

日期：2026-07-17。

## 1. 授权与任务边界

用户已明确把第一层工作交给另一位 agent：仅使用 EURUSD、GBPUSD 的价格、bid/ask、tick
路径、点差和时间信息开展因子挖掘。此授权允许在完成下面的 outcome-blind 预检和预注册后，
使用现有脚本的 `--open-return-labels --screen` 运行一次冻结的第一轮历史筛选。

授权不包括：

- 新增宏观、利率、CFTC、REER、新闻、文本或 broker 字段；
- 扩大到其他货币对；
- 看结果后增加窗口、改变方向、拆分多重检验家族或删除失败年份；
- 把旧历史称为 untouched holdout；
- 生成交易批准、实盘订单或“已经盈利”的结论。

第一轮只回答：在两个品种、三个慢周期期限上，预先冻结的价格因子是否产生可复核的探索性
预测证据。成功状态最多是 `price_factor_candidate_requires_cost_validation_and_forward`。

## 2. 不可变输入

| 项目 | 路径/合同 |
|---|---|
| 原始数据库 | `data/dukascopy_sqlite/EURUSD.sqlite`、`GBPUSD.sqlite` |
| 旧区间 transfer manifest | `data/dukascopy_sqlite/_sqlite_manifest_EURUSD_GBPUSD_legacy.json` |
| outcome-blind 日线缓存 | `data/dukascopy_daily_cache/EURUSD_GBPUSD_legacy_to_20250915.sqlite` |
| 两品种配置 | `configs/long_horizon_two_pair_time_series.yaml` |
| 运行入口 | `scripts/run_two_pair_long_horizon_research.py` |
| 研究模式 | `time_series_panel` |
| 品种 | `EURUSD, GBPUSD`，顺序固定 |
| 区间 | `[2016-01-01, 2025-09-15)` |
| 再平衡 | 每 21 个共同交易日 |
| 期限 | 21、42、63 个交易日 |

缓存和数据库必须通过现有 receipt、sidecar、文件大小和 SHA-256 验证。不得重新下载、修改或
覆盖这些文件。工作树已有大量属于项目的未提交改动，禁止 `git reset --hard`、`git checkout`
覆盖、`git clean` 或删除不相关文件。

## 3. 第一轮精确因子集合

在打开任何收益标签前，必须把 long-horizon factor catalog 增加 outcome-blind 依赖元数据，并
证明本轮 eligible catalog 恰好只有下列 16 个因子：

```text
momentum_21d
momentum_63d
momentum_126d
momentum_252d
momentum_252d_skip_21d
trend_tstat_63d
trend_tstat_126d
trend_tstat_252d
ma_gap_63d
ma_gap_126d
ma_gap_252d
realized_vol_21d
realized_vol_63d
realized_vol_126d
vol_ratio_21_126
global_fx_vol_21
```

其中前 11 个是方向因子；后 5 个只能预测未来绝对收益/风险状态，不得被改成方向信号。每个
因子测试 21/42/63 日三个期限，因此每个训练折的统一多重检验家族固定为：

```text
16 factors × 3 horizons = 48 hypotheses per fold
```

以下内容必须在结果前排除，并在 manifest 中记录 exclusion reason：

- `currency_graph`：两品种没有货币图环路冗余；
- `cross_sectional`、`value_trend`：两个品种不能支持宽横截面结论；
- value、positioning、rate、commodity、external risk：本轮外部数据关闭；
- 所有 DSL 自动生成表达式；
- 所有未在上面列出的新窗口、交互项和相对价差。

建议给 factor definition 增加至少这些字段：

```text
data_dependencies
minimum_symbols
requires_graph_cycle
requires_cross_section
requires_external_data
price_only_eligible
```

过滤必须只读取配置和输入能力，禁止读取未来收益、IC、p 值或回测结果。

## 4. 预运行门

在第一次打开标签前，创建独立的
`outputs/price_only_round1_20260717/preregistration_manifest.json`，至少保存：

- 当前 `HEAD`、dirty 状态及所有本轮修改文件的 SHA-256；
- config、runner、缓存、缓存 receipt、transfer manifest 的 SHA-256；
- 精确 16 因子目录、方向属性和排除目录；
- `hypotheses_per_fold=48`；
- 期限、再平衡、训练/测试/step、block length、bootstrap 次数、BH/BY 阈值；
- 缺失数据规则、共同日期规则和下一 open/未来 close 标签合同；
- `market_history_previously_inspected_through=2026-07-13`；
- `inference_eligibility=exploratory_reused_history_requires_new_forward`；
- 本任务书路径和 SHA-256；
- `return_labels_opened=false`、`trading_approval=false`。

预运行验收必须包括：

```bash
uv run pytest -q
uv run ruff check \
  src/fx_system/long_horizon.py \
  src/fx_system/long_horizon_config.py \
  src/fx_system/long_horizon_research.py \
  scripts/run_two_pair_long_horizon_research.py

# 预期退出码 2，证明默认不会打开标签
uv run python scripts/run_two_pair_long_horizon_research.py
```

若因子目录不是精确 16 个、假设数不是 48、数据库证据失败或测试失败，禁止运行筛选。

## 5. 唯一一次历史筛选

预运行门通过后，使用新的、此前不存在的输出目录运行一次：

```bash
uv run python scripts/run_two_pair_long_horizon_research.py \
  --config configs/long_horizon_two_pair_time_series.yaml \
  --cache data/dukascopy_daily_cache/EURUSD_GBPUSD_legacy_to_20250915.sqlite \
  --database-dir data/dukascopy_sqlite \
  --transfer-manifest \
    data/dukascopy_sqlite/_sqlite_manifest_EURUSD_GBPUSD_legacy.json \
  --output outputs/price_only_round1_20260717 \
  --open-return-labels \
  --screen
```

统计合同：

- 信号时刻严格早于下一 open，标签终点严格晚于入场；
- 越过测试期边界的训练标签必须 purge；
- 测试窗口不重叠；
- 只使用 rebalance-eligible 日期；
- 63 日日期块 bootstrap，50,000 次；
- 48 个假设在每折共用一个 BH FDR 家族，`q <= 0.10`；
- BY 只作任意依赖敏感性结果，不能替换主判定；
- 训练折选择后才查看对应 OOS；OOS 不再反向改变因子。

当前 screen 的方向统计使用 forward mid return 诊断预测关系，因此本步骤只能产生因子证据，
不能产生可交易净收益结论。必须同时保留数据集中的 executable long/short bid/ask 标签，供后续
候选策略转换使用。

## 6. 预先固定的候选判定

每个 factor/horizon 只有同时满足下列条件才可标为价格因子候选：

1. 训练期覆盖率至少 60%；
2. 训练期绝对 IC 至少 0.01；
3. 训练期 BH `q <= 0.10`；
4. 至少两个训练折入选；
5. 入选对应的 OOS 平均 IC 与训练平均 IC 同号；
6. OOS sign-match fraction 至少 75%；
7. 结果不是只有一个品种有有效行；必须报告 EURUSD、GBPUSD 分品种贡献；
8. future-information canary、时间错位或联合符号负对照不得产生类似显著性。

若没有候选，机器 verdict 必须是 `empty_price_factor_model`。不得增加相邻窗口或把 48 个假设
拆成多个较小 FDR 家族补救。

## 7. 因子候选到策略候选

只有满足第 6 节的候选可进入这个阶段。需要新增独立的 alpha-only freeze：冻结因子、方向、
系数、数据截止、试验暴露和代码哈希，但不把 broker、法律实体或真实账户成本写入 alpha 哈希。

随后用下一 open 的 ask/bid 和期限终点的 bid/ask 构造可执行方向收益，并单独输出：

```text
expected_gross_r
expected_scenario_r
expected_net_r = null  # 历史融资未知时
```

执行成本使用显式的通用情景和 1.0x/1.5x/2.0x 压力，不得把未知融资填零后称为净收益。只有
1.5x 仍为正、分折与分品种不集中、且会计勾稽通过，才可输出
`price_factor_candidate_requires_cost_validation_and_forward`。

## 8. 结果后的纪律

- 无论成功、失败、空模型或软件错误，都保存完整输出和哈希；
- 将本轮 16 个定义、48 个每折假设和实际 fold-level/outcome evaluation 数写入 registry；
- 若结果后发现实质性 bug，本轮标为 invalidated，但试验暴露不能归零；
- 不得将 2026-07-13 以前任何历史重新命名为 untouched holdout；
- 真正晋级只能依赖 alpha 冻结之后新增的市场数据；
- 不生成 OANDA 订单、不修改 `paper_plan_approved_only.json`，交易批准保持 false。

## 9. 向用户和主项目交付

最终提交一份中文报告和机器 manifest，至少回答：

- 16 个因子是否全部按合同进入；48 个假设是否统一计数；
- 数据、PIT、purge、bootstrap 和 FDR 门是否通过；
- 哪些 factor/horizon 被训练期选择；对应 OOS 是否同号；
- EURUSD/GBPUSD 分别贡献多少；
- verdict 是 empty、reject 还是 candidate-requires-cost-and-forward；
- 新增了多少 factor-outcome evaluations；
- 为什么结果仍不是盈利保证或实盘批准。

