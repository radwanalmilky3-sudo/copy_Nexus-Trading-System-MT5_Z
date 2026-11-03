# AGENTS.md — 给 Agent 的项目使用说明（根入口）

**你是 AI agent？本文件是你在本仓库的第一站。** 先读完它，再动手。
人向介绍见 `README.md`（可能滞后于实际进展）；**以本文件和 `docs/PROJECT_HANDOFF_SUMMARY_ZH.md` 顶部更新节为准。**

## 0. 30 秒决策树

```text
1. 这是什么项目？                 → §1
2. 我该先读哪些文件？             → §2 权威文件地图
3. 用户问"能否交易 / 能否复制"？   → §3 红线（默认 fail closed，不得擅自放宽）
4. 现在进行到哪一步 / 卡在哪？     → §4
5. 怎么跑代码 / 数据在哪？         → §5、§6
6. 查外汇文献 / 知识库？           → research/AGENTS.md（子协议，别在本文件找）
7. 已经踩过的坑？                 → §7
```

## 1. 这是什么

外汇量化**因子挖掘研究系统**——本地研究基础设施。

- **不是交易系统**：无真实账户连接；OANDA 适配器只允许 `fxPractice`，代码层禁生产域名。
- **截至 2026-08-02：未批准任何交易策略。** 这不是谦虚，是事实。
- 仓库 public（`jlcbk/fx-trading-system`），但 `data/`、`outputs/`、`research/_pdfs/` **不在 git**；
  19 GiB Dukascopy 行情库仅本机，靠 sidecar SHA 可用下载器 v1.1.1（commit `63ee417`）重抓。
- 正式研究区间冻结为 `[2016-01-01, 2026-01-01)`，14 品种。

## 2. 权威文件地图（按顺序读，通常 2–4 个）

| 优先级 | 路径 | 何时读 |
|---|---|---|
| P0 | `AGENTS.md`（本文件） | 每次进仓库 |
| P0 | `docs/PROJECT_HANDOFF_SUMMARY_ZH.md` | 项目状态；**顶部「2026-08-02 更新」=最新**，下方 7-16 正文=历史 |
| P0 | `docs/PROJECT_STATUS_20260802_INTAKE_VERIFIED_ZH.md` | intake 验证 + 只读复核清单（每项有命令+判据） |
| P1 | `docs/IBKR_COST_ACQUISITION_PLAN_ZH.md` | 成本数据路径（broker=IBKR，无账户） |
| P1 | `docs/RESEARCH_FIXED_COST_ASSUMPTIONS_ZH.md` | **研究用固定成本假设**（software_fixture；可 research-net） |
| P1 | `configs/research_fixed_costs.yaml` | 机读成本假设 |
| P1 | `configs/long_horizon_dukascopy_research_costs.yaml` | 新 14 库 + 研究成本的慢周期配置 |
| P1 | `docs/NY_CLOSE_DAILY_COVERAGE_DESIGN_ZH.md` | WP6 冻结前硬设计点（日线覆盖缺口） |
| P1 | `outputs/dukascopy_intake/intake_ledger_fresh_v111_20260802.json` | 数据合同状态机（`verdict`/`formal_ready`） |
| P1 | `outputs/dukascopy_audit_fresh_v111_20260802/G0_UNIVERSE_CLOSURE.json` | **G0 全宇宙收尾**（14/14 PASS，门禁+逐品种摘要；不在 git，仅本机） |
| P1 | `outputs/dukascopy_audit_fresh_v111_20260802/G0_UNIVERSE_CLOSURE_ZH.md` | G0 收尾中文报告 |
| P1 | `research/AGENTS.md` | **查文献/知识库走这里**（30秒路由、L3 索引、笔记优先） |
| P2 | `outputs/research_registry_audit.json` | 研究注册表（已披露假设/因子/检验数） |
| P2 | `docs/PRICE_ONLY_ROUND1_FINAL_REMEDIATION_HANDOFF_ZH.md` | 第一轮为何被验收否决（不可恢复） |

**单一事实源（SSOT）：** 状态字段以 `outputs/*.json` 磁盘为准，文档与磁盘冲突时以磁盘为准并标出。

## 3. 红线（违反 = 错误结论 / 违规）

### 3.1 不可改变的安全状态（任何 agent 不得擅自改判）

```text
approved_strategy        = false
trading_approval         = false
formal_net_returns_ready = false
return_labels_opened     = false   （新 14 库 + 第二层五因子包均未打开）
fresh_forward_required   = true
cost verdict             = cost_incomplete_research_only
price_only round1        = invalidated_but_data_inspected （不可恢复）
```

### 3.2 数据纪律

1. **不打开收益标签**，除非：G0 14 库全 PASS（✅ 已满足）+ WP6 outcome-blind 冻结 + 用户单次授权。后两者缺一不可。
2. **不用 mid-only / 政策利率 / 合成远期 / Yahoo 冒充真实 broker 成本。** 合成只能标 `software_fixture`，仅研究。
3. **不删除失败品种静默缩小研究宇宙**；失败要写进 manifest。
4. **不在结果出来后改 cut-off / 因子 / 阈值 / 成本假设。** 选定动作必须在 WP6 冻结时完成。
5. **任何外部数据必须有 `available_time` + 版本 + 哈希；** 越过决策时点的数据禁用。
6. **2016–2025 是 reused-history，不是 untouched holdout。** forward 必须严格晚于 alpha freeze。
7. **写入边界：** 工程/文档改动（`src/` `configs/` `docs/` `scripts/` `tests/`）可做并提交；**交易/收益/成本相关状态字段（§3.1）不得擅自改判**，需用户明确授权。

## 4. 当前状态与阻塞（2026-08-02，G0 收尾后）

- ✅ **数据接收（WP1）已闭环**：14 品种 formal intake `formal_ready`，deep verify 全过。
- ✅ **G0 微观结构审计（WP2）已闭环：14/14 PASS**。产物
  `outputs/dukascopy_audit_fresh_v111_20260802/G0_UNIVERSE_CLOSURE.json`
  （零 error/warning/crossed/sha_mismatch/lzma_err/ts_regression/missing；总 tick ≈ 41.01 亿）。
- ✅ **共同覆盖（WP2 小时维度）已产出**：`outputs/fresh14_common_coverage_20260802/`
  （小时共同 ok 98.55%；纽约收盘日线 79%）。
- ⚠️ **成本（WP3）**：正式门仍阻塞（无 IB 账户/无商业历史）。**研究层固定成本已启用**
  （`docs/RESEARCH_FIXED_COST_ASSUMPTIONS_ZH.md` + `data/research_costs/broker_financing_research_fixed_v1.csv`，
  `software_fixture`）。可算 research-net；`formal_net_returns_ready=false`。
- ⏭ **下一步**：WP6 outcome-blind 冻结（含 NY-close 方案 + 本成本假设预注册）→ 用户单次授权打开收益标签。

## 5. 运行环境

- Python 3.11+，[uv](https://github.com/astral/uv) 管理依赖。
- 环境：`uv sync --all-extras`
- 检查：`uv run pytest`（全量）、`uv run ruff check .`
- CLI 入口：`uv run fxtrade <command>`（定义见 `pyproject.toml` `[project.scripts]`）
- **数据不在 git**：`data/` 被 gitignore。行情库在 `data/dukascopy_sqlite_fresh_20160101_20260101_v111/`（仅本机）。
- 下载器独立仓库：`/Users/open/dukascopy-sqlite-downloader`（v1.1.1, commit `63ee417`）。

## 6. 关键命令

```bash
# 14 品种 formal intake 台账
uv run fxtrade dukascopy-intake-ledger \
  --database-dir data/dukascopy_sqlite_fresh_20160101_20260101_v111 \
  -c configs/dukascopy_intake_universe.yaml

# 单库 G0 深度微观结构审计（只读，tick 级，~10–19 分钟/库）
uv run python scripts/audit_dukascopy_sqlite.py \
  data/dukascopy_sqlite_fresh_20160101_20260101_v111/EURUSD.sqlite \
  --symbol EURUSD --output-dir outputs/dukascopy_audit_fresh_v111_20260802

# 共同覆盖 manifest（只读 hours 表，秒级）
uv run python scripts/build_fresh14_common_coverage.py

# 成本覆盖率审计（需先有 swap/forward CSV）
uv run fxtrade cost-coverage-audit --help
```

## 7. 已知陷阱

- **两个数据目录别混**：`data/dukascopy_sqlite/`（旧 1.0.0 库，止 2025-09-15，**不正式**）vs `data/dukascopy_sqlite_fresh_20160101_20260101_v111/`（新正式 14 库）。正式研究只用后者。
- **`no_data` 是真实市场关闭**（周末/节假日/早关市），**不是缺测**；`missing_hours=0` 才是完整性指标。
- **纽约 17:00 ET 收盘日线共同覆盖只有 79%**——慢周期若用它做锚点，缺日处理必须在 WP6 预注册（见 `NY_CLOSE_DAILY_COVERAGE_DESIGN_ZH.md`）。
- **zsh 不对未加引号变量分词**：批量脚本传空格分隔的 symbol 列表时用 `${=VAR}`（见 `scripts/run_dukascopy_audit_fresh_v111.sh`）。
- **长任务后台 + `caffeinate -dimsu`** 防 Mac 睡眠；不要在交互会话里同步等数小时的 tick 审计。
- **`research/_pdfs/`（版权 PDF）不在 git**；查文献走 `research/AGENTS.md` 的 L3 索引，别 `find _pdfs | xargs cat`。

## 8. 工作模式（给协作 agent）

- **只读优先**：改任何东西前先读 §2 权威文件，确认你改的不是被冻结的结论。
- **一次一个有界任务**；不要同时铺开多个改判。
- **磁盘为准**：复算验证文档声明，不一致以磁盘为准并标 FAIL。
- **不替用户拍板**：broker / 成本投入 / 商业数据购买 / 交易批准 / forward 启动都是用户决策，agent 只准备材料和推荐。
- **提交卫生**：改动按逻辑分组 commit；`data/` `outputs/` `*.sqlite` `*.bi5` 已 gitignore，别强行 add。
- **诚实评估优先**：用户明确邀请 push back 时，给基于证据的判断，不要机械执行可疑分支。
