# WP6 Outcome-blind 冻结合同（慢周期方向候选）

日期：2026-08-03。  
状态：`frozen_awaiting_label_authorization`。  
**本文件冻结研究合同；不打开收益标签；不批准交易。**

## 0. 冻结目的

在查看任何本轮 Dukascopy 正式宇宙上的方向收益结果之前，钉死：

1. 数据宇宙与 G0 资格；
2. 候选集合（7 个慢周期方向单元）；
3. 信号/再平衡/缺失规则；
4. 纽约收盘日线缺口处理；
5. 研究成本假设（research-net only）；
6. 统计门与报告口径；
7. 打开收益标签所需的用户授权条件。

冻结后禁止根据结果增删候选、改 horizon、改 cut-off、改成本假设或改 FDR 分母。

## 1. 数据宇宙（已满足）

| 项 | 冻结值 |
|---|---|
| 行情目录 | `data/dukascopy_sqlite_fresh_20160101_20260101_v111/` |
| 批次 manifest | `_sqlite_manifest.json`（program 1.1.1） |
| tick 库区间 | `[2016-01-01, 2026-01-01)` UTC 小时（末小时 `2025-12-31T23Z`） |
| 冻结日线会话区间 | NY session-start `[2016-01-01, 2025-12-31)` → 最后一场完整会话 start=`2025-12-30`（结束 `2025-12-31T22Z`）。**不可**用 session-start end=`2026-01-01`，否则会纳入 `2025-12-31` 会话并因缺 2026-01-01 小时而 fail closed（2026-08-03 runner 已实测） |
| 慢周期品种（12） | EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD, EURGBP, EURJPY, GBPJPY, AUDJPY, CADJPY |
| FIX-W 额外腿 | USDNOK, USDSEK（本轮慢周期候选**不**纳入权重） |
| formal intake | 14/14 `formal_ready`（`outputs/dukascopy_intake/intake_ledger_fresh_v111_20260802.json`） |
| G0 | 14/14 PASS（`outputs/dukascopy_audit_fresh_v111_20260802/G0_UNIVERSE_CLOSURE.json`） |
| 小时共同 ok（全14） | 98.55% |
| 价格模式 | `bid_ask` only |

## 2. 候选集合（outcome-blind，与注册表精确对齐）

声明文件：`configs/long_horizon_dukascopy_candidates.yaml`  
`declaration_id = slow_directional_registry_freeze_20260716`  
`directions_selected_from_dukascopy_outcomes = false`  
`registration_market_data_cutoff = 2026-07-13`  
`total_trials_evaluated = 3504`（≥ 注册表已披露 outcome evaluations）

| 候选名 | 假设 ID | 因子 | 符号 | horizon |
|---|---|---|---|---|
| slow_commodity_currency_alignment__21d | slow_commodity_currency_alignment | commodity_currency_alignment_12m | + | 21 |
| slow_commodity_currency_alignment__42d | slow_commodity_currency_alignment | commodity_currency_alignment_12m | + | 42 |
| slow_commodity_currency_alignment__63d | slow_commodity_currency_alignment | commodity_currency_alignment_12m | + | 63 |
| slow_value_trend_agreement__42d | slow_value_trend_agreement | value_trend_agreement | + | 42 |
| slow_value_trend_agreement__63d | slow_value_trend_agreement | value_trend_agreement | + | 63 |
| slow_positioning_crowding_reversal__21d | slow_positioning_crowding_reversal | positioning_crowding_reversal | + | 21 |
| slow_positioning_crowding_reversal__42d | slow_positioning_crowding_reversal | positioning_crowding_reversal | + | 42 |

- 变换：`cross_sectional_centered_rank_gross_normalized`
- `gross_target = 1.0`
- 缺失规则：`require_all_eligible_symbols_or_flat`（12 品种不齐则当日 flat）
- 未来 DSR 诊断预选（非晋升）：`slow_commodity_currency_alignment__42d`
- **本轮不含** deferred carry、非方向 risk 状态、日内 FIX-W 族（另册）

## 3. 信号与日程合同

| 项 | 冻结值 |
|---|---|
| 决策锚点 | 纽约外汇会话收盘（NY close） |
| 入场 | **下一共同会话 open**（next-open） |
| 再平衡 | 每 21 个共同会话 |
| horizons | {21, 42, 63} 会话 |
| 标签 | 冻结阶段**不生成** forward return / label 列 |
| 组合 PnL | 冻结阶段**不生成** |

机器冻结命令：

```bash
uv run fxtrade long-horizon-freeze-sqlite \
  --database-dir data/dukascopy_sqlite_fresh_20160101_20260101_v111 \
  -c configs/long_horizon_dukascopy_wp6_freeze.yaml \
  -d configs/long_horizon_dukascopy_candidates.yaml \
  -r configs/factor_research_registry.yaml \
  --transfer-manifest data/dukascopy_sqlite_fresh_20160101_20260101_v111/_sqlite_manifest.json \
  -o outputs/long_horizon_dukascopy_freeze_wp6_20260803
```

产物目录（跑通后）：`outputs/long_horizon_dukascopy_freeze_wp6_20260803/`  
关键文件：`manifest.json`、`frozen_candidate_signal_schedule.csv`、`candidate_declaration.json`、
`factor_only_build/factor_panel.csv.gz`（无 `_forward_` / `_label_` 列）。

## 4. 纽约收盘日线缺口（预注册选定）

依据 `docs/NY_CLOSE_DAILY_COVERAGE_DESIGN_ZH.md` 与共同覆盖统计（慢 12 ≈ 79.7% 工作日）：

| 项 | 选定 |
|---|---|
| **正式口径** | **方案 A：session 抑制** |
| 含义 | cut-off 小时非全宇宙共同 `ok` 的工作日：**不产生新信号，持仓维持/按 missing 规则 flat**；不插值 |
| 方案 B 前填 | 仅允许作为事后 robustness，且必须 `imputed=true`；**不进主结果** |
| 方案 C 换日界 | **本轮不采用**；若未来采用须新 declaration_id 与独立预注册 |

不得在打开标签后因样本少而改用 B/C。

### 4.1 日线边界 tick 阈值（2026-08-03 选定）

原 `DAILY_BOUNDARY_MAX_QUOTE_AGE = 5s` 对真实 Dukascopy tick 过严：30.8% 会话（9,619 / 31,308）
因 22:00 UTC 流动性切换点首/末 tick 延迟 >5s 被拒，被拒会话均为高活跃日（8-15 万 tick）。

**选定：freeze 路径 `boundary_max_quote_age = None`（不因边界延迟 suppress 完整会话）。**

- 完整会话（有 tick、无缺小时）一律出 bar；实际延迟记入审计但不 suppress。
- 理由：freeze 是 factor-only，用 close-to-close 收益和 OHLC 形态，边界几秒/几分钟对日线因子无影响。
- `run_dukascopy_daily_from_sqlite` 直接调用仍默认 5s（portfolio ledger 保留严格）。
- 不得在打开标签后因结果改回 5s 或调阈值。

## 5. 成本合同（研究层启用，正式层关闭）

| 项 | 冻结值 |
|---|---|
| 假设文档 | `docs/RESEARCH_FIXED_COST_ASSUMPTIONS_ZH.md` |
| 机读配置 | `configs/research_fixed_costs.yaml` |
| 融资 schedule | `data/research_costs/broker_financing_research_fixed_v1.csv` |
| `quote_quality` | `software_fixture` |
| 压力倍数 | 1.0x / 1.5x / 2.0x；讨论“值得继续”至少看 **1.5x** |
| 正式成本 | `cost_incomplete_research_only` |
| `formal_net_returns_ready` | **false** |

报告必须三层：

```text
gross
research-net   (本固定成本)
formal-net     = N/A
```

## 6. 统计门（打开标签后才执行；此处先钉死）

| 项 | 冻结值 |
|---|---|
| 训练/OOS | 8y train / 2y test / 2y step；最少 3 个 walk-forward 折 |
| 主多重检验 | 训练折内 BH，`q = 0.10` |
| bootstrap | 50,000；块长 63 共同会话日 |
| 最小 \|train IC\| | 0.01（配置门，非偷看后调整） |
| 覆盖门 | market ≥0.80；cross-symbol ≥0.90；factor ≥0.60 |
| 负对照 | 保持时间结构的 shadow / 既有 registry 负对照族；不得从分母删除失败格 |
| 失败 | fail closed；允许本轮零入选 |

**历史披露负担：** 注册表已披露 3504 次 factor-outcome evaluations；本轮结果解释必须承认 reused-history，
`fresh_forward_required = true`。通过训练/OOS 也不等于可交易；须新 forward。

## 7. 明确禁止

1. 打开本冻结包内因子面板的收益标签，除非用户**单次书面/对话授权**；
2. 根据 Dukascopy 结果增删 7 候选或改 expected_sign；
3. 将 research-net 写为 formal-net 或 trading_approval；
4. 静默缩小 12 品种宇宙；
5. 用 mid-only Yahoo 替换本轮 bid/ask 主路径；
6. 把 FIX-W / 外部交互 INT-01… 混进本 declaration（它们是不同预注册）。

## 8. 打开收益标签的授权门槛（用户动作）

同时满足才可授权一次 screen：

1. 本 WP6 冻结产物 `manifest.json` 存在且 `trading_approval=false`、`future_labels_generated=false`；
2. G0 closure 与 intake ledger 路径未改、哈希可复核；
3. 用户明确说授权打开本轮慢周期标签（单次、可撤销概念上仅对后续新 run）；
4. 输出目录为**新**目录，不覆盖冻结产物。

授权后允许的命令形态（示例，授权前不要跑 screen 出标签）：

```text
uv run fxtrade long-horizon-screen -c <授权后专用 config> -o outputs/long_horizon_screen_wp6_<date>
```

（具体 screen config 在授权时另建；必须继承本冻结的候选/宇宙/成本/缺口方案。）

## 9. 安全状态钉

```text
return_labels_opened     = false
approved_strategy        = false
trading_approval         = false
formal_net_returns_ready = false
fresh_forward_required   = true
cost_verdict             = cost_incomplete_research_only
wp6_status               = frozen_awaiting_label_authorization
```

## 10. 产物与文档索引

| 路径 | 角色 |
|---|---|
| 本文件 | 人读冻结合同 |
| `configs/long_horizon_dukascopy_wp6_freeze.yaml` | 冻结用 LongHorizonConfig |
| `configs/long_horizon_dukascopy_candidates.yaml` | 7 候选声明 |
| `configs/factor_research_registry.yaml` | 注册表 |
| `configs/research_fixed_costs.yaml` | 研究成本 |
| `outputs/long_horizon_dukascopy_freeze_wp6_20260803/` | 机器冻结产物（跑通后） |
| `outputs/dukascopy_audit_fresh_v111_20260802/G0_UNIVERSE_CLOSURE.json` | G0 门禁 |
| `docs/NY_CLOSE_DAILY_COVERAGE_DESIGN_ZH.md` | 缺口方案论据 |
| `docs/RESEARCH_FIXED_COST_ASSUMPTIONS_ZH.md` | 成本假设 |

## 11. 冻结执行记录（2026-08-04 完成）

```text
freeze_command_exit: 0 (SUCCESS)
manifest_path: outputs/long_horizon_dukascopy_freeze_wp6_20260803/manifest.json
common_daily_sessions: 2588
declared_candidates: 7
scheduled_candidate_decisions_ready: 824
future_labels_generated: false
portfolio_pnl_generated: false
trading_approval: false
hash_chain_verified: true
forbidden_outcome_columns: none
```

修复记录（4 道墙，均为真实 Dukascopy tick 数据首次端到端暴露）：
1. end 边界 → exclusive session-start end=`2025-12-31`（末会话 2025-12-31 缺 2026 小时）
2. boundary tick 阈值 → freeze 路径 `boundary_max_quote_age=None`（5s 过严拒 30.8%）
3. partial sessions → `build_common_daily_data_from_cache_audit`（跨币种假期日排除不报错）
4. 时间序 → `entry >= decision`（连续会话首笔 tick 可精确等于上一场结束瞬间）

checkpoint 续传机制（`outputs/wp6_freeze.daily_checkpoint.sqlite`）保护全部 31,296 会话，
中断后重跑同一命令秒级恢复。
