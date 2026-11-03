# 项目现状与 14 库正式 intake 验证报告

生成时间（UTC）：`2026-08-02T13:28:53Z`
项目根目录：`/Users/open/fx-trading-system`
主分支：`main`，HEAD = `565ea96`（2026-07-15），**无 remote**，工作树脏路径 **158** 条（未提交）。

> 本报告由 Claude（会话内）核对磁盘后写就，可直接被另一个 Agent 只读复核。文档与磁盘冲突时以磁盘为准。
> 复核口径：每条结论后面给出可运行的命令或文件路径，重新执行应得到相同结果。

---

## 0. 一句话结论

- **Dukascopy 14 品种正式行情库已下载完成，并通过本仓库的 formal intake 合同：`verdict=formal_ready`、`full_intake_ready=true`、14/14 formal-ready、慢周期 12/12、FIX-W 9/9。** 这是相对 `outputs/dukascopy_intake/intake_ledger.json`（2026-07-16，`intake_incomplete`、0/14、指向旧目录）的实质推进。
- **G0 分角色/全宇宙深度微观结构审计已闭环：14/14 PASS**（产物
  `outputs/dukascopy_audit_fresh_v111_20260802/G0_UNIVERSE_CLOSURE.json`；
  零 error/warning/crossed/sha_mismatch/lzma_err/ts_regression/missing；总 tick ≈ 41.01 亿）。
  **历史真实成本仍未齐**、**无获批策略**。
- 项目仍处于「研究基础设施成熟 + 正式行情数据合同已闭环；G0 深度审计与 outcome-blind 冻结未在新库上执行」阶段，**未进入真实资金或获准 practice**。

---

## 1. 本次 intake 验证做了什么

用仓库自带合同代码（`src/fx_system/dukascopy_intake.py`）对**新 14 库目录**重新构建 intake ledger：

```bash
cd /Users/open/fx-trading-system
uv run python - <<'PY'
from pathlib import Path
from fx_system.dukascopy_intake import build_intake_ledger, write_intake_ledger
data_dir = Path('data/dukascopy_sqlite_fresh_20160101_20260101_v111')
config = Path('configs/dukascopy_intake_universe.yaml')
ledger = build_intake_ledger(data_dir, config_path=config)
write_intake_ledger(ledger, Path('outputs/dukascopy_intake/intake_ledger_fresh_v111_20260802.json'))
print(ledger.verdict, ledger.full_intake_ready, len(ledger.formal_ready_symbols))
PY
```

**结果：** `verdict=formal_ready`，`full_intake_ready=true`，`formal_ready=14/14`，
`slow_horizon_ready=true (12/12)`，`fix_w_ready=true (9/9)`，`issues=()`，`batch_manifest_present=true`。
产物已落盘：`outputs/dukascopy_intake/intake_ledger_fresh_v111_20260802.json`。

合同代码逐符号检查：数据库存在 → `.sha256`/`.json` sidecar 齐 → sidecar 字段一致（file/integrity/schema/parser/provider/base_url）→ 区间与统一合同一致 → 在批次 manifest 内 → 调用 `verify_database_transfer` 做 transfer 完整性校验。全部通过才判 `formal_ready`。

> 注意：这里新生成的是**新目录的** ledger，**未覆盖**旧 ledger `outputs/dukascopy_intake/intake_ledger.json`（它仍保留 2026-07-16 的旧状态作为历史记录）。

## 2. 14 库逐品种核对（合同 + manifest + deep verify 三源交叉）

数据目录：`data/dukascopy_sqlite_fresh_20160101_20260101_v111/`
批次 manifest：`_sqlite_manifest.json`（`program_version=1.1.1`，`parser_version=dukascopy-bi5-v1`，`created_at=2026-07-27T16:32:34Z`）
下载器：`/Users/open/dukascopy-sqlite-downloader`，git commit `63ee417cfeaa5d96242f9126428d09303262bc6b`，`download_dukascopy_sqlite.py` SHA-256 `3faffb11…4b6ce5`（=任务书冻结值，工作树 clean）。

冻结区间：`[2016-01-01T00:00:00Z, 2026-01-01T00:00:00Z)`，`expected_hours=63138`，`missing_hours=0`（全部 14 品种）。
`no_data` 是 Dukascopy 端无行情的周末/节假日小时（约 792–873/品种），属正常，不是缺测。

| Symbol | intake 状态 | 字节 | SHA-256(前16) | ok_hours | no_data | missing |
|---|---|---|---|---|---|---|
| EURUSD | formal_ready | 1,471,393,792 | 196a3658… | 62346 | 792 | 0 |
| GBPUSD | formal_ready | 1,382,801,408 | fca48d45… | 62341 | 797 | 0 |
| USDJPY | formal_ready | 1,496,346,624 | 73de27cd… | 62344 | 794 | 0 |
| USDCHF | formal_ready |   897,630,208 | 244e93c5… | 62338 | 800 | 0 |
| AUDUSD | formal_ready | 1,036,652,544 | 120b6435… | 62343 | 795 | 0 |
| NZDUSD | formal_ready |   831,209,472 | a5938471… | 62335 | 803 | 0 |
| USDCAD | formal_ready | 1,137,401,856 | 94bc7f35… | 62342 | 796 | 0 |
| EURGBP | formal_ready | 1,158,037,504 | af59a208… | 62342 | 796 | 0 |
| EURJPY | formal_ready | 2,088,669,184 | 3f411405… | 62344 | 794 | 0 |
| GBPJPY | formal_ready | 1,831,919,616 | 52eb29c6… | 62342 | 796 | 0 |
| AUDJPY | formal_ready | 1,481,375,744 | 7898a718… | 62342 | 796 | 0 |
| CADJPY | formal_ready | 1,300,557,824 | e497cea8… | 62344 | 794 | 0 |
| USDNOK | formal_ready | 1,484,050,432 | 7ce36af2… | 62265 | 873 | 0 |
| USDSEK | formal_ready | 1,349,877,760 | f36c72f3… | 62301 | 837 | 0 |

合计：`18,947,923,968` 字节（≈ 18.95 GiB）。

**三源一致性：**
- intake ledger：14/14 `formal_ready`，14/14 `range_matches_unified=true`、`has_sidecars=true`、`in_batch_manifest=true`、`issues=[]`；
- manifest：14/14 `integrity=ok`，全部 `missing_hours=0`，区间 = 冻结值；
- deep verify 日志（`outputs/dukascopy_full_redownload_20260723/deep_verify.log`）：14 个 `deep verification complete`，末行 `All transferred databases match the manifest.`

每库逐 payload 的 deep verify（重算每条 bi5 小时 payload 的 SHA-256 与 manifest 对照）已全部通过。

## 3. 还没做（intake 之外、尚未在新库闭环的事项）

1. **G0 分角色深度微观结构审计（WP2）已在新 14 库闭环：14/14 PASS。**
   产物 `outputs/dukascopy_audit_fresh_v111_20260802/`（每库 audit + `G0_UNIVERSE_CLOSURE.json`）。
   旧 `outputs/dukascopy_audit/` 仍是 2026-07-16 旧 1.0 库的历史报告，勿混用。
   共同覆盖见 `outputs/fresh14_common_coverage_20260802/`。
2. **历史真实成本未齐（WP3）。** 目标 broker 已定为 **Interactive Brokers (IBKR)**（2026-08-02 决策，实体待开户时确认）。关键约束：**账户持有人尚无 IBKR 账户**，因此路径 C（账户 Flex Query 导出历史融资）天然不可行；正式成本合同只能靠路径 B（买 Bloomberg/Refinitiv 商业历史 swap）解锁，否则只能走路径 A（合成，仅 `software_fixture`/研究口径）。详见 `docs/IBKR_COST_ACQUISITION_PLAN_ZH.md`。
   - 战略决定（2026-08-02）：**暂不做满 IB 合成**。理由：成本是「有候选之后」才用得上，当前无候选，先投入合成是 YAGNI；OANDA 合成（`factors_carry_synthetic`、`convert_oanda_financing_to_cost_contract.py`）已能让软件链和成本压力测试跑通。路径 B 商业数据购买推迟到「出现值得验证的候选」时再决策。
   - `official_rates` 已覆盖 6 币种（USD/EUR/GBP/CAD/AUD/CHF），缺 JPY/NZD/NOK/SEK（做满合成时补）。
   - 正式净收益账本保持 `cost_incomplete_research_only`。
3. **outcome-blind 冻结与预注册检验（WP6）未启动。** G0 通过后才允许打开该研究族的收益标签。
4. **forward 合同 `blocked_until_alpha_freeze`。** `alpha_freeze_time=null`（无通过历史筛选的 frozen alpha）；`2026-01-01..2026-07-13` 因已被查看，不能当 untouched forward。
5. **工程可恢复性（WP0）存在风险：** HEAD 停在 2026-07-15，**158 条未提交改动**，**无 remote**。新 14 库目录（≈19 GiB）当前仅在本机，未做带 SHA-256 的离线归档（旧归档在 `/Users/open/fx-trading-system-archives/`，最新是 `m0_1_20260716T154419Z`，早于本次重下）。

## 4. 研究/策略状态（固定安全字段）

研究 registry：`outputs/research_registry_audit.json`（`registry_date=2026-07-16`，`search_rounds=8`）。

```text
market_history_previously_inspected_through = 2026-07-13
registered_hypotheses = 20         active = 17
directional_hypotheses = 12        active_directional = 10
risk_or_execution_hypotheses = 8
disclosed_unique_factor_definitions_sum = 286
disclosed_fold_level_hypothesis_tests = 3249
disclosed_factor_outcome_evaluations = 3504
fresh_forward_required = True
```

**第二层（结构化外部数据，broker-neutral、outcome-blind）：**
`outputs/structured_external_feature_package_20260723/` 五因子包（`gscpi_risk_state_pit`、`us_cpi_12m_log_inflation`、`us_ip_6m_log_growth`、`benchmark_publication_state`、`phillyfed_spf_release_state`），manifest hash 闭合。CPI 3653/3653 ready；IP/GSCPI/SPF 各有覆盖边界（见 `SECOND_LAYER_HANDOFF_ZH.md`）。Treasury TIC `tressect` 已物化为 source view，未进入任何收益检验。

**纯价格第一轮（EURUSD/GBPUSD）：**
`outputs/price_only_round1_20260717/`，经独立验收判为
`historical_run_status=invalidated_but_data_inspected`、
`provisional_interpretation=insufficient_valid_oos_evidence`、
`historical_run_valid_for_inference=false`。
整改已收口证据链与回归测试，但**结论不可恢复**（详见 `PRICE_ONLY_ROUND1_FINAL_REMEDIATION_HANDOFF_ZH.md`）。

**全局不可改变状态（当前）：**

```text
approved_strategy        = false
trading_approval         = false
formal_net_returns_ready = false
return_labels_opened     = false （第二层 / 新 14 库均未打开）
factor_outcome_evaluations_added = 0 （本轮）
fresh_forward_required   = true
```

## 5. 复核清单（给独立 Agent）

| 检查 | 命令/文件 | 通过判据 |
|---|---|---|
| 正式 intake | 重跑第 1 节脚本 | `verdict=formal_ready`, `formal_ready=14/14` |
| 批次 manifest | `data/dukascopy_sqlite_fresh_20160101_20260101_v111/_sqlite_manifest.json` | `program_version=1.1.1`，14 库 `integrity=ok`、`missing_hours=0` |
| deep verify | `outputs/dukascopy_full_redownload_20260723/deep_verify.log` | 14 行 `complete`，末行 `All transferred databases match the manifest.` |
| sidecar 齐 | `ls data/dukascopy_sqlite_fresh_20160101_20260101_v111/*.sqlite{,.json,.sha256}` | 每品种 3 文件齐全 |
| 下载器冻结 | `/Users/open/dukascopy-sqlite-downloader` git HEAD + script SHA | `63ee417…`，script `3faffb11…4b6ce5` |
| 旧 vs 新 ledger | `outputs/dukascopy_intake/intake_ledger.json` vs `…_fresh_v111_20260802.json` | 旧 `intake_incomplete/0/14`、新 `formal_ready/14/14` |
| registry 安全 | `outputs/research_registry_audit.json` | `fresh_forward_required=true`，无 approved |
| 第二层 hash | `outputs/structured_external_feature_package_20260723/manifest.json.sha256` | 与 manifest 一致 |
| 第一轮结论 | `outputs/price_only_round1_20260717/screen_summary.json` | `approved_strategy=false` |
| 工程可恢复 | `git status --short \| wc -l`；`git remote -v` | ⚠️ 158 脏路径、无 remote（需归档） |
| 磁盘 | `df -h /Users/open` | 75 GiB 可用（2026-08-02 实测） |

## 6. 建议的下一步顺序

1. **对新 14 库逐库运行 `scripts/audit_dukascopy_sqlite.py`**，产出 12 份审计 JSON + 慢周期/FIX-W 共同覆盖 universe manifest（G0）。
2. G0 通过后，冻结 outcome-blind 候选调度（WP6），再授权**单次**收益标签打开做预注册检验。
3. 并行推进 broker 历史成本资料请求（WP3）。
4. 对新 14 库目录与未提交改动做带 SHA-256 的离线归档（WP0 可恢复性）。
5. 任何候选都须经成本后验证（G3）与全新 forward，**不回写历史结论、不自动产生交易批准**。
