# 外汇量化研究项目交接与后续执行计划（草案）

## 2026-08-02 状态更新（最新；下方 2026-07-16 正文保留作历史）

**数据接收（WP1）已闭环：** Dukascopy 14 品种正式行情库全部到位，通过本仓库 formal intake 合同：
`verdict=formal_ready`、`formal_ready=14/14`、慢周期 12/12、FIX-W 9/9、`full_intake_ready=true`。
- 目录 `data/dukascopy_sqlite_fresh_20160101_20260101_v111/`（≈18.95 GiB），区间 `[2016-01-01, 2026-01-01)`，
  下载器 v1.1.1（commit `63ee417`），逐 payload deep verify 全过。
- 新 intake ledger：`outputs/dukascopy_intake/intake_ledger_fresh_v111_20260802.json`（旧 `intake_ledger.json` 保留作历史）。
- 验证报告：`docs/PROJECT_STATUS_20260802_INTAKE_VERIFIED_ZH.md`。

**G0 深度微观结构审计（WP2）已闭环：14/14 PASS。** 产物
`outputs/dukascopy_audit_fresh_v111_20260802/`（每库 `*_dukascopy_audit.json` +
`G0_UNIVERSE_CLOSURE.json` / `G0_UNIVERSE_CLOSURE_ZH.md`）。
零 error、零 warning、零 crossed quote、零 sha256 mismatch、零 lzma error、
零 timestamp regression、零 missing hours；总 tick ≈ **41.01 亿**。
全 14 / 慢周期 12 / FIX-W 9 研究宇宙全部就绪。**不打开收益标签，不批准交易。**

**共同覆盖（WP2 小时维度，已产出）：** `outputs/fresh14_common_coverage_20260802/`。
小时级共同 ok = 98.55%（全14）；纽约 17:00 ET 收盘日线共同覆盖 = 79.0%（缺口成因与处理方案见
`docs/NY_CLOSE_DAILY_COVERAGE_DESIGN_ZH.md`，是 WP6 冻结前硬设计点）。

**成本（WP3）决策 + 研究层启用：** 目标 broker 定为 **Interactive Brokers**。账户持有人尚无 IBKR 账户，
故路径 C（Flex Query 账户历史）不可行；正式成本合同只能靠路径 B（商业数据付费）解锁。
**2026-08-03：已落地研究用固定成本假设**（`docs/RESEARCH_FIXED_COST_ASSUMPTIONS_ZH.md`，
`configs/research_fixed_costs.yaml`，融资 schedule
`data/research_costs/broker_financing_research_fixed_v1.csv`，`quote_quality=software_fixture`）。
cost-coverage-audit 覆盖率 1.0，verdict 仍为 **`cost_incomplete_research_only`**（正确 fail closed）。
研究可报 gross / research-net / formal-net=N/A；**不**解锁交易批准。

**工程可恢复性（WP0）已解决：** 仓库已上云 → **https://github.com/jlcbk/fx-trading-system**（public，jlcbk 账号）。
git 历史从「无 remote + 158 条裸改动」收敛为干净 4-commit 历史；19 GiB 行情库靠 sidecar SHA 可重抓，
M1 离线归档在 `/Users/open/fx-trading-system-archives/m1_intake_ready_20260802T134229Z/`。

**不变的固定安全状态：**
```text
approved_strategy = false   trading_approval = false
formal_net_returns_ready = false   fresh_forward_required = true
return_labels_opened = false（新14库与第二层均未打开）
```

**WP6 outcome-blind 冻结已完成（2026-08-04）：** 7 慢周期候选、2,588 共同会话、824 ready
next-open 决策；`future_labels_generated=false`、`trading_approval=false`、哈希链验证通过。
产物 `outputs/long_horizon_dukascopy_freeze_wp6_20260803/`。合同 `docs/WP6_OUTCOME_BLIND_FREEZE_CONTRACT_ZH.md`。

**接手 Agent 的下一项：** 用户单次授权后打开收益标签做预注册检验（WP6→screen）。
成本侧等「出现值得验证的候选」再决策商业数据。

---

更新日期：2026-07-16

M0 进度（2026-07-16）：NEXT-01/02/03 完成。离线归档
`/Users/open/fx-trading-system-archives/m0_20260716T052213Z`；
pytest 399→404；当时 intake ledger `intake_incomplete`（GBPUSD legacy_range_mismatch，其余 13 pending）；
研究 verdict 仍为 `no approved strategy`。详见
`outputs/handoff_baseline/M0_REPORT_ZH.md`。

数据接收更新（2026-07-16）：EURUSD 已下载并完成深度审计；当前 EURUSD、GBPUSD 均为
`legacy_range_mismatch`，其余 12 个品种 `pending`，`formal_ready=0/14`。详见
`outputs/dukascopy_intake/intake_ledger.json`。

数据等待期（同日）：NEXT-05/06/07 软件合同已落地（WP3 成本 schema/audit、
WP4 合成 two-stage 桥、WP5 假日合同 + 四央行 deferred）。成本 verdict 固定
`cost_incomplete_research_only`。未开收益。详见
`outputs/handoff_baseline/WP345_PROGRESS_ZH.md`。

免费资料更新（2026-07-17）：Treasury TIC 2016–2025 月度发布 ZIP 已完成 120/120，原始
326,637,026 bytes、raw 与内容哈希 archive 合计约 624 MiB；两份 SHA、ZIP 完整性和连续月份
已复核。下载器 v1.1 使用页面/说明日期与 ZIP 文件日期的较晚者再加一天作为保守可用时间。
跨版审计已证明 NPR 等历史值会大幅回修，因此当前仍为 `strict_pit_eligible=false`，不能注册
方向因子。OpenAlex 五组固定查询另发现 249 条匹配、245 篇唯一论文，首轮 20 篇已分为 5 个
无收益合同、10 个硬数据 deferred、5 个方法/负对照；registry 和 outcome evaluation 均未变。

同日准备工作继续完成：TIC phase-one 审计解析 120 个 NPR vintage 和 119 个相邻修订；
BIS GLI/LBS 8/8 官方资源已下载并双 SHA 复核；ALFRED/ECB SPF 目录已落盘；broker-neutral
成本合同、CSV/manifest schema 和中文数据请求模板已完成；EURUSD/GBPUSD outcome-blind
日线 SQLite 缓存已实现。真实缓存仍因缺 VPS `_sqlite_manifest.json` fail closed。CFTC BPR
保存 82/240 页后被官方 HTTP 403 阻塞，支持哈希核验续传但没有完整 manifest。所有新产物均
保持 `return_labels_opened=false`、`outcome_evaluations_added=0`，研究 verdict 仍为
`no approved strategy`。

两品种 commissioning（同日）：新增慢周期 12 对、FIX-W 9 腿、全量 14 库三个独立 readiness
gate；EURUSD/GBPUSD 的数据库证据、纽约收盘/DST 和 6 个事件边界探针全部通过。当前
`417 passed`、ruff 通过；`return_labels_opened=false`、新增 outcome evaluation 为 0。详见
`outputs/dukascopy_commissioning/EURUSD_GBPUSD_commissioning.json`。阶段代码快照位于
`/Users/open/fx-trading-system-archives/m0_1_20260716T154419Z`。

主项目目录：`/Users/open/fx-trading-system`

独立下载器目录：`/Users/open/dukascopy-sqlite-downloader`

## 1. 一页结论

这是一个面向主要外汇货币对的本地量化研究系统，覆盖行情归档、因子研究、防未来泄漏、
多重检验、组合账本、成本建模、事件研究和 OANDA practice 执行软件。系统目前最成熟的是
**研究基础设施和失败关闭的数据契约**，不是盈利策略。

截至 2026-07-16：

- 没有任何方向因子或策略获得交易批准；
- 没有冻结的盈利模型；
- 默认 `paper_enabled=false`，获准模拟订单计划为空；
- 既有传统策略、多因子、严格成对 FDR 和慢周期研究均已拒绝或保持探索状态；
- 免费数据和 point-in-time 基础设施已经准备了相当一部分；
- 本机已收到 GBPUSD、EURUSD 两个 Dukascopy SQLite，合计约 2.80 GB；
- GBPUSD 的 60,486 个 payload 和 283,237,102 条 tick、EURUSD 的 60,491 个 payload 和
  275,108,137 条 tick 均通过机械审计；
- 两库仍是下载器 1.0.0 的旧区间 `[2016-01-01, 2025-09-15)`，缺原始
  `_sqlite_manifest.json`；GBPUSD 另有一个需 v1.1.1 重抓的孤立行情空档；
- 其余 12 个正式 Dukascopy 品种尚未到达，完整研究数据宇宙未通过 G0；
- 目标 broker 的 2016--2025 历史 swap/rollover 或同口径真实 forward points 仍缺，
  因此慢周期正式历史净收益必须 fail closed。

最准确的项目定位是：

> 已经建成一套较严格的外汇因子研究实验室，现处于正式 bid/ask 数据接收与 G0 数据验收阶段；
> 尚未发现可声称盈利的因子，也尚未进入真实资金或获准 practice 策略阶段。

## 2. 接手 Agent 的执行计划（重点）

### A. 接手后的目标状态

下一位 agent 的任务不是继续补一份总结，而是把项目从“基础设施基本齐全、正式数据刚开始
到达”推进到以下可验证状态：

1. 主项目有可恢复的代码快照，未提交工作不再依赖当前单台机器；
2. 正式 Dukascopy 数据宇宙全部到达、传输可追溯、逐库审计通过，并形成跨品种共同覆盖报告；
3. 2016--2025/2026 的统一区间契约被明确解决，不再同时存在两个相互矛盾的 end date；
4. 7 个慢周期方向候选完成 outcome-blind 因子和交易调度冻结；
5. 慢周期 next-open、重叠 sleeve、主账户净额、bid/ask、融资和 FX 换算串成正式账本；
6. FIX-W、LOCAL-PAPER 和 ASIA-LDN 的 tick、日历与 spread 过滤入口具备正式运行条件；
7. 在完整注册表和成本契约下运行一轮预注册研究，允许结果为空或被拒绝；
8. 若没有候选通过，保存空模型并停止**当前注册轮次**；若有候选通过，冻结后进入全新
   3--6 个月 forward，而不是继续在旧历史上调参；
9. 当前轮关闭后，如用户决定继续研究，另开有独立假设、数据合同和 trial budget 的新因子轮次，
   旧历史只作探索训练，不能重新获得 untouched holdout 身份。

交接工作的成功标准是“把下一项不确定性变成可审计结论”，不是保证找到盈利因子。

### B. 总体依赖关系

```text
WP0 工程快照与基线
        │
        ├─────────────┬─────────────────┬──────────────────┐
        ▼             ▼                 ▼                  ▼
WP1 数据接收     WP3 成本数据合同   WP4 慢周期账本     WP5 日内缺件
与区间统一       与 broker 请求包    软件串联           和日历补齐
        │             │                 │                  │
        └──────┬──────┴─────────┬───────┴──────────────────┘
               ▼                ▼
        WP2 全宇宙 G0 审计   软件/负对照验收
               │
               ▼
        WP6 outcome-blind 冻结
               │
        ┌──────┴────────┐
        ▼               ▼
  慢周期预注册检验   日内预注册检验
        └──────┬────────┘
               ▼
        WP7 成本后组合验证
               │
         通过？├─ 否 → 空模型/关闭当前轮 → WP9 新研究章程
               ▼是
        WP8 冻结后新前向期
```

WP0、WP3、WP4 和 WP5 不需要等待其余 Dukascopy 文件，可以立即并行推进。慢周期 WP6 必须
等待 12 对慢周期 gate，FIX-W 必须等待 9 腿 gate，全项目 intake 才要求 14 库 gate；三者都
仍需原始 manifest 和对应 G0，不能为了保持开发节奏绕过依赖。

### C. 工作包清单

| ID | 工作包 | 现在能否开始 | 主要产物 | 完成定义 |
|---|---|---|---|---|
| WP0 | 工程可恢复性 | 是，最高优先级 | 主项目快照、remote/归档、环境与数据清单 | 新目录可恢复代码；`399 passed`；ruff 通过；数据/outputs 未丢失 |
| WP1 | Dukascopy 接收与区间统一 | 是 | 14 库及 sidecar、原始 manifest、下载批次清单 | 所有 symbol/range/parser/bytes/hash 与统一契约一致 |
| WP2 | 分角色及全量 G0 数据审计 | 等对应 12/9/14 子宇宙 | 每库审计、共同覆盖、session 抑制、异常复核报告 | 无未解释缺行/交叉报价/哈希错误；对应覆盖门槛通过或明确拒绝 |
| WP3 | 历史成本与 carry 合同 | 是，但依赖外部资料 | broker 请求包、swap/forward schema、coverage audit | 真实 2016--2025 行级来源和可用时间满足门槛；否则保持 cost-incomplete |
| WP4 | 慢周期正式账本闭环 | 是 | next-open/close 两阶段账本、sleeve、净额、FX conversion、成本测试 | 价格 PnL、spread、slippage、financing、NAV 逐日勾稽为零差异 |
| WP5 | 日内正式输入闭环 | 是 | 四个缺失央行日历、ASIA-LDN 假日、事件窗口验收 | 所需 calendar/raw/hash 完整；5 秒边界和 spread warmup 全部测试 |
| WP6 | 预注册候选冻结与检验 | 等 WP2；收益前先冻结 | 冻结 manifest、候选调度、完整 trial count、训练/OOS 统计 | 候选集合与 registry 完全相等；没有结果驱动新增窗口 |
| WP7 | 成本后组合验证 | 等 WP3/4/6 | 主账户账本、1x/1.5x/2x 成本、DSR/PBO/SPA | 通过既定 G3，或机器可读地拒绝并停止 |
| WP8 | 全新 forward/practice | 只在 WP7 通过后 | frozen model、前缀哈希、每日 forward ledger | 严格晚于冻结日，至少 3--6 个月，不重选因子/阈值 |
| WP9 | 下一轮新因子发现 | 当前轮关闭且用户确认后 | research charter、factor catalog、trial budget、预注册候选 | 有限候选集和经济机制冻结；旧历史仅作探索，最终仍等新 forward |

### D. 各工作包的具体任务

#### WP0：先让项目可移交、可恢复

负责人应在第一次工作会话完成：

1. 保存 `git status --short`、HEAD、Python/uv 版本、`uv.lock` 哈希；
2. 将当前未提交的代码、配置、测试和文档建立不可变快照；
3. 配置主项目 remote，或生成带校验和的离线代码归档；
4. 单独生成 `data/` 和 `outputs/` 文件清单、字节数、SHA-256，不把大型文件直接混入源码 Git；
5. 在干净恢复目录运行 `uv sync --all-extras`、全量 pytest 和 ruff；
6. 保存 baseline 结果，并在后续每个工作包结束时更新本交接文档的进度表。

这是实际开发工作的起点。若 WP0 没完成，之后新增的任何代码仍有再次丢失的风险。

#### WP1：管理 VPS 下载，而不是被动等文件

1. 与 VPS 冻结唯一任务区间。建议统一扩展至
   `[2016-01-01T00:00:00Z, 2026-01-01T00:00:00Z)`，与当前 v1.1 配置一致；
2. 确认 14 个品种、下载器 commit `63ee417`、parser、price divisor 和命令行完整记录；
3. 先刷新 GBPUSD 的 765 个 `no_data`，重点检查 `2016-09-02T18:00:00Z`；
4. 每个品种发布后生成 `.sha256`、`.json`，整个批次生成原始 `_sqlite_manifest.json`；
5. 用 HTTPS Range 下载到本机；未完成文件不替换已验收数据库；
6. 每到一个品种就做传输和 payload 审计，但不开始跨品种收益研究；
7. 维护接收表：symbol、range、bytes、SHA、ok/no_data、异常、验收状态、是否需重抓。

若用户决定保留 2025-09-15 排他边界，agent 必须建立单独命名且全项目一致的配置、manifest
和研究声明；不能只改某个 CLI 参数。

#### WP2：把“单库通过”升级为分角色“研究宇宙通过”

对应数据到达后按以下顺序；慢周期、FIX-W、全量 intake 分别使用 12、9、14 品种 gate：

1. 对每库运行 transfer verification 和 `scripts/audit_dukascopy_sqlite.py`；
2. 分类所有 `no_data`：纽约周边界、节假日、延迟开市、无法解释的活跃时段空档；
3. 统计各品种 spread、tick gap、跳变、年份和 UTC hour-of-week，并固定人工复核预算；
4. 检查 Brexit、2020-03、2022 mini-budget、CHF 等各货币自身压力期；
5. 生成 12 对慢周期共同纽约收盘日线覆盖和 9 腿 FIX-W 事件日共同覆盖；
6. 验证 21:00/22:00 UTC DST 收盘、5 秒开收边界和 session 抑制；
7. 将 G0 结果写入单一 universe manifest，失败品种不得被静默删除后重算权重。

只有相应的 WP2 子宇宙 G0 通过，才能打开该研究族的 WP6 收益标签与检验。慢周期不必为
仅服务 FIX-W 的 `USDNOK`/`USDSEK` 等待，但不得缺少自身 12 对中的任何品种；全项目接收完成
仍以 14 库 gate 为准。

#### WP3：主动推进真正的成本数据

接手 agent 不能只写“等待 broker 数据”，应完成可交付的请求和接收合同：

1. 明确目标 broker、监管实体、账户币种、账户类型和 triple-swap 规则；
2. 形成请求字段：symbol、effective date/time、long/short financing、单位、day-count、
   markup、holiday multiplier、source/version；
3. 为真实 1M forward points 定义 spot/forward timestamp、tenor、bid/ask、points unit、
   source、available_time 和 revision policy；
4. 编写 schema validator、manifest validator、coverage/staleness audit 和小型 fixture 测试；
5. 数据未到时允许继续做软件测试，但 formal portfolio 必须返回
   `cost_incomplete_research_only`；
6. OANDA 2025--2026 和政策利差只保留为压力情景，不填充历史空白。

#### WP4：补齐慢周期组合执行链

建议以当前 `long_horizon_execution.py` 和 `portfolio_runner.py` 为基础，按顺序接通：

1. 冻结 schedule 的 decision close → next open → scheduled close；
2. 21/42/63 日 1/2/3 sleeve 的资本守恒与缺失候选 flat 规则；
3. 多候选、多期限、多货币对先合并为主账户净目标，再产生净交易；
4. 账户币种 quantity、base/quote 现金流和当时可得 FX conversion；
5. bid/ask 入退场、quote age/staleness、slippage、commission；
6. 每日 financing、cash interest、realized/unrealized PnL 和 cost basis；
7. 每日 NAV、杠杆、币种腿敞口、turnover 和 sleeve contribution；
8. 将所有明细交给 `portfolio_validation_runner.py` 做逐项勾稽；
9. 增加 property/fixture 测试：资本守恒、净额不重复收费、跨币种换算、周末和 DST。

该工作包可以用合成 fixture 完成软件验收，但不得用合成收益决定候选。

#### WP5：完成日内研究缺件

1. 完成 BoE、SNB、BoC、RBNZ 官方政策事件适配器，或将宏观 blackout 继续标为 deferred；
2. 为 ASIA-LDN 建立 Tokyo/London 金融中心节假日和半日市输入及 manifest；
3. 对 FIX-W 六个独特边界×九腿做 tick 窄窗性能和一次性 transfer receipt 测试；
4. 对 LOCAL-PAPER 12 单元逐一验证 IANA 时钟、周边界、open-to-open/open-to-close 语义；
5. 固定 rolling spread 60 日 warmup、40 有效观测和 90% 分位逻辑；
6. 保存每个自然日的接受/拒绝原因，不能只输出有收益的日期；
7. 在正式结果前运行联合符号负对照和 future-information canary。

#### WP6：先冻结，再看结果

慢周期执行：

1. registry audit 必须通过；
2. 运行 `long-horizon-freeze-sqlite`，确认 7 个候选单元一项不少、一项不多；
3. 保存输入数据库/外部数据/配置/代码前缀哈希；
4. 冻结调仓日、期限、符号、缺失规则、权重 transform 和 trial count；
5. 验证产物不含 `_forward_*`、`_label_*` 或组合收益；
6. 只有冻结验收后才单独启动标签/OOS 检验进程。

日内执行：

1. 固定 FIX-W、LOCAL-PAPER、ASIA-LDN、WMR 交互和 spread filter 的完整候选集；
2. 固定共同事件日和 calendar manifest；
3. 所有候选进入同一多重检验家族；
4. 输出 gross mid 仅作机制诊断，主判定必须是 bid/ask + slippage；
5. 某族全部失败时接受空结果，不新增相邻 5/10/15 分钟窗口补救。

#### WP7：把“因子有效”升级为“组合可交易性检验”

仅允许 WP6 通过训练/OOS 门槛的方向候选进入：

1. 完整候选集和完整历史 trial count 进入 White/SPA；
2. 报告 Deflated Sharpe 和 CSCV/PBO，不只报告普通 Sharpe；
3. 运行 1.0x、1.5x、2.0x 成本，1.5x 转负即不晋级；
4. 至少 100 笔交易、75% 开发折为正、每折 PF 不低于 1.10；
5. 分品种、年份、市场状态和危机窗口做贡献分解；
6. 单一危机、单一货币、邻域扰动翻号或历史融资缺失时保持 `research_only`；
7. 机器可读 verdict 只能是 reject、empty model 或 candidate-requires-forward。

#### WP8：冻结后 forward，而不是再次回测旧历史

1. 冻结因子公式、系数、阈值、风险、成本、输入前缀哈希和代码 commit；
2. `factor-forward-evaluate` 只接受严格晚于冻结截止时间的数据；
3. 前 90 天只收集，不得根据结果修改模型；
4. 运行 3--6 个月 OANDA practice，覆盖多种波动状态；
5. 每日保存报价年龄、拒单、滑点、融资、订单幂等 ID 和账本对账；
6. forward 失败则淘汰；调参后的版本必须重新注册，并等待新的 forward 时间。

#### WP9：当前轮失败后，怎样继续挖掘新因子

WP9 不是在拒绝结果旁边加几个参数，而是一次新的、单独计数的研究轮。建议按以下顺序开展：

1. 封存上一轮的配置、结果、失败原因和累计 trial exposure，先写 postmortem；
2. 建立 `factor_catalog`，每个候选必须声明经济机制、预期方向、可用时间、交易期限、适用品种、
   缺失规则、成本敏感性和与既有因子的差异；
3. 优先研究四类机制：真实 forward/swap 支持的 carry 与曲线形状；PIT REER/宏观修订支持的 value；
   有真实发布日期的仓位拥挤；tick 支持的 fixing、时区库存和流动性事件效应；
4. 把趋势、价值、carry、仓位和风险状态先做单因子 IC、排序单调性、跨品种覆盖、换手和状态稳定性
   诊断，再考虑组合；风险状态不得偷换成方向信号；
5. 组合模型先用等权 rank ensemble 和收缩线性模型作为 champion/challenger；只有两者都无法表达
   已登记机制时才增加非线性，并把超参数全部计入搜索预算；
6. 在看收益前冻结 feature schema、PIT join、neutralization、窗口、符号、期限、再平衡、成本和
   最大 trial 数；构造联合符号负对照与 future-information canary；
7. 旧历史上的 nested/purged walk-forward 只能用于探索筛选和估计稳定性；任何晋级候选仍须冻结，
   并等待严格晚于冻结日的新数据；
8. 一轮只解决一个主要经济问题。慢周期与日内分别登记、分别计数，不能把失败家族的预算转移到
   另一家族后合并报告。

WP9 的完成标准不是“发现高 Sharpe”，而是形成一个有限、可复现、可证伪的新候选集合。若严格
PIT 数据或真实成本仍缺失，对应机制保持 deferred，不用代理变量伪装成正式因子。

### E. 接手后的执行队列与首个暂停点

下一位 agent 不应从“再找一些因子”开始。默认领取顺序如下；同一编号的任务完成前，不得用
后续收益结果替代其验收产物。

| 任务 | 立即动作 | 交付物 | 是否需要等待数据 |
|---|---|---|---|
| `NEXT-01` | 只读恢复现场，保存 Git、环境、测试和 registry 基线 | `handoff_baseline` 报告及命令输出 | 否 |
| `NEXT-02` | 建立代码不可变快照；为 `data/`、`outputs/` 建清单和哈希 | 可恢复代码归档/remote 引用、资产 manifest | 否 |
| `NEXT-03` | 建立 14 库接收台账和统一验收入口 | intake ledger、sidecar/manifest/区间 validator | 否 |
| `NEXT-04` | 接收并重审 GBPUSD v1.1.1 刷新版本；以后逐库重复 | per-symbol transfer/deep-audit verdict | 等 VPS 文件 |
| `NEXT-05` | 实现历史 swap/forward schema、coverage audit 和 fixtures | WP3 验收测试；缺数据时明确 fail closed | 否 |
| `NEXT-06` | 用合成 fixture 补齐慢周期两阶段主账户账本 | WP4 勾稽报告和 property tests | 否 |
| `NEXT-07` | 补四个央行适配器和 ASIA-LDN 日历合同 | WP5 calendar manifest 和测试 | 否，可分批 |
| `NEXT-08` | 全库到齐后运行跨品种共同覆盖 G0 | universe manifest 与 pass/retry/reject | 是 |
| `NEXT-09` | G0 通过后生成 outcome-blind 冻结产物 | 7 个慢周期候选及日内候选 manifest | 是 |
| `NEXT-10` | 用户确认解盲后只运行一次预注册检验 | reject/empty/candidate 机器 verdict | 是 |
| `NEXT-11` | 当前轮 reject/empty 后封存结果，并提报下一轮 research charter | WP9 候选目录、数据资格和 trial budget | 需用户确认新轮次 |

首个阶段成果定义为 `NEXT-01` 至 `NEXT-03` 完成：代码可恢复、基线可复现、后续 SQLite 有统一
接收入口。接手 agent 到达这里应先暂停并向用户报告，再继续任何会改动研究逻辑或查看新收益的
工作。若 VPS 数据尚未到齐，恢复工作后按 `NEXT-05`、`NEXT-06`、`NEXT-07` 推进，不增加候选。

建议节奏如下：

| 阶段 | 主任务 | 可并行任务 | 阶段输出 |
|---|---|---|---|
| 第一次会话 | WP0 快照、恢复验证、确认 remote | 建立 Dukascopy 接收表 | 可恢复基线与测试证据 |
| 数据等待期 | WP3 schema、WP4 账本、WP5 日历 | BPR/ONS/OECD 等非阻塞下载 | 不依赖收益的软件与数据合同 |
| 每个 SQLite 到达 | 单库 transfer + deep audit | FRED/压力期交叉核对 | per-symbol pass/retry/reject |
| 全宇宙到齐 | WP2 共同覆盖 G0 | 性能与存储优化 | universe audit + manifest |
| G0 通过后 | WP6 outcome-blind freeze | 审计冻结产物 | 不含收益的正式候选调度 |
| 冻结通过后 | 一次预注册慢周期和日内检验 | WP4/5 最终接线 | reject/empty/candidate verdict |
| 仅 candidate | WP7 成本后组合 | forward 运维准备 | frozen model 或拒绝 |

上述节奏表达的是优先顺序，不是要求在七天内越过外部依赖。数据没到时应推进 WP3/4/5，而不是新增
未经注册的因子。

### F. 需要用户尽早确认的四个决定

| 决定 | 推荐选项 | 不确认的影响 |
|---|---|---|
| Dukascopy 统一结束日 | 扩展到 2026-01-01 排他 | 当前 GBPUSD 与正式配置冲突，WP2 不能通过 |
| 主项目存放方式 | 建立私有/公开 remote 或不可变离线归档 | 当前大量未提交成果存在丢失风险 |
| 目标 broker/账户实体 | 尽早固定并请求历史 swap/forward | WP3、WP7 无法正式完成 |
| 第一研究优先级 | 慢周期主线；日内基础设施并行 | 两条路线同时看收益会扩大搜索暴露和开发负担 |

### G. 进度汇报格式

接手 agent 每完成一个工作包，应在同一份状态记录中回答：

1. 本次完成了什么，具体产物路径和 SHA-256 是什么；
2. 哪些验收命令通过，测试数是多少；
3. 是否看过新的收益或标签；若看过，新增了多少 trial exposure；
4. 当前阻塞是代码、数据、用户决定还是外部服务；
5. 下一工作包及其前置依赖是什么；
6. 当前 verdict 是否仍为 `no approved strategy`。

不得用“框架已完成”“结果看起来不错”代替机器可验证的产物、门槛和 verdict。

## 3. 仓库与工作区状态

### 3.1 主项目

| 项目 | 当前状态 |
|---|---|
| 路径 | `/Users/open/fx-trading-system` |
| 包名 / 版本 | `fx-portfolio-system 0.6.0` |
| Python | 3.11+ |
| 环境管理 | `uv` |
| 当前 Git HEAD | `565ea96` (`Add frozen factor forward evaluation`) |
| Git remote | **未配置** |
| 工作树 | **大量已修改和未跟踪文件，当前核心进展尚未提交** |
| 完整测试 | 2026-07-16：`399 passed in 35.55s` |
| 静态检查 | 2026-07-16：`uv run ruff check .` 通过 |
| `data/` | 约 2.9 GB |
| `outputs/` | 约 278 MB |
| `.venv/` | 约 335 MB |

这是交接中最大的工程风险。当前 Git HEAD 只代表较早基线，不能代表本文件所述的完整系统。
若通过 Git 仓库而不是同一工作区移交，未提交的代码、配置、文档会丢失；`data/**` 和
`outputs/*` 又被 `.gitignore` 排除，也不会随普通 commit 传输。

下一位 agent 在任何修改前必须先执行：

```bash
cd /Users/open/fx-trading-system
git status --short
uv sync --all-extras
uv run pytest
uv run ruff check .
```

禁止对当前工作树执行 `git reset --hard`、`git checkout -- .` 或批量清理未跟踪文件。
在用户审阅本交接文档后，应优先为当前状态建立可恢复快照，并决定主项目的 remote/commit
策略；不要把 278 MB 历史研究产物全部直接塞进 Git。

### 3.2 独立 Dukascopy 下载器

| 项目 | 当前状态 |
|---|---|
| 路径 | `/Users/open/dukascopy-sqlite-downloader` |
| GitHub | `https://github.com/jlcbk/dukascopy-sqlite-downloader` |
| 当前版本 | `1.1.1` |
| 当前提交 | `63ee417cfeaa5d96242f9126428d09303262bc6b` |
| remote/main | 已与上述提交一致 |
| 测试 | `7 passed` |
| 用途 | VPS 直接下载 Dukascopy，并按品种保存一个 SQLite |

`v1.1.1` 修复了已发布数据库使用 `--refresh-no-data` 时不会真正重抓的缺陷，同时禁止用
局部区间刷新完整发布库，以免把全库 metadata 意外缩成一个小时。

## 4. 研究目标与三条路线

### 4.1 短周期 / 4h 障碍研究

- 持仓上限 120 小时，系统硬上限 168 小时；
- 下一根 bar 开盘执行，目标约 `0.70 ATR`，止损约 `1.10 ATR`；
- 因子包括价格、波动、路径、日历、横截面、多货币图、carry 和受约束 DSL；
- 研究输出经过 purged walk-forward、成对 block bootstrap 和 FDR；
- 当前结果为拒绝，不应继续在同一历史上堆窗口寻找“最好参数”。

### 4.2 慢周期 / 1--3 个月因子

- 21 日调仓；持有期固定为 21 / 42 / 63 个交易日；
- 8 年训练、2 年非重叠 OOS、2 年步长；
- 方向因子与风险状态因子分开检验；
- 21/42/63 日仓位分别用 1/2/3 个资本守恒 sleeve；
- 当前正式候选声明包含 7 个方向性单元：商品货币 3 个期限、Value×Trend 2 个期限、
  仓位拥挤反转 2 个期限；
- 这些候选只允许做 outcome-blind 调度冻结，不代表历史显著或可交易。

### 4.3 日内 tick / 事件研究

预注册的主要族包括：

- `FIX-W`：Tokyo 09:55、Berlin/ECB、London WMR 和纽约 17:00 的冻结四段组合；
- `LOCAL-PAPER`：12 个固定货币对×本地时段方向单元；
- `ASIA-LDN`：亚洲形成窗到伦敦响应窗；
- WMR 月末交互；
- 60 日历史、至少 40 个有效观测的滚动 spread 90% 分位过滤；
- 宏观公告 blackout，目前因为部分央行日历不完整而 deferred。

日内正式研究必须使用原始 tick 和可成交 bid/ask，不能用 4h 或 1h bar 伪造 5 秒边界。

## 5. 已实现的核心能力

| 模块 | 主要文件 | 能力 |
|---|---|---|
| 行情与校验 | `data.py`、`scripts/download_*.py` | Yahoo/CSV/OANDA/Dukascopy、原始归档、哈希和 manifest |
| Dukascopy 事件读取 | `dukascopy_event_data.py` | 只读 transfer receipt、逐 payload 哈希、窄 tick 窗、边界报价选择 |
| 纽约收盘日线 | `dukascopy_daily.py` | 精确纽约 17:00、DST、bid/ask、缺小时和 5 秒边界失败关闭 |
| 传统策略 | `strategies/`、`engine.py` | 六类策略、下一 bar 执行、保守 bar 内路径、组合风控 |
| 多因子 | `factor_research.py`、`factors.py`、`factor_dsl.py` | 60+ 因子、障碍标签、校准、FDR、受约束 DSL |
| 慢周期 | `long_horizon*.py` | 21/42/63 日标签、PIT 合并、非重叠 OOS、候选冻结和调度 |
| 日内 | `intraday_*.py` | IANA 时区、FIX-W/本地时段构造、共同事件日和联合重采样 |
| 组合账本 | `portfolio*.py`、`long_horizon_execution.py` | sleeve、净目标、bid/ask 成交、成本和每日 PnL 勾稽基础 |
| 统计验证 | `research_controls.py`、`statistical_validation.py`、`hansen_spa.py` | BH/BY、stationary bootstrap、负对照、DSR/PBO/SPA 输入与核心 |
| 搜索注册表 | `research_registry.py`、`configs/factor_research_registry.yaml` | 搜索暴露、文献、假设、修订、产物哈希审计 |
| Practice 执行 | `brokers/oanda.py`、`planner.py` | 无副作用计划、幂等 ID、只允许 OANDA `fxPractice` |
| CLI | `cli.py` | 数据、研究、筛选、冻结、审计、backtest、paper plan 等入口 |

系统已经实现大量必要组件，但“组件存在”不等于“正式组合已串通”。慢周期冻结调度之后的
账户 quantity、FX conversion、未实现 PnL cost basis、历史 financing、slippage/commission、
逐品种 quote timestamp/staleness 与最终组合 SPA manifest 仍未完整接入正式 runner。

## 6. 关键防泄漏与失败关闭约束

接手 agent 不得削弱以下约束：

1. close 时点信号只能在严格晚于该时点的下一可交易 open 执行；
2. 训练标签越过 OOS 边界的样本必须 purge，并保留 embargo；
3. long/short 共享同一路径，方向检验必须使用成对差，不能视为两个独立样本；
4. 所有货币对共享日期块重采样，不能逐品种独立 bootstrap 后拼 p 值；
5. 所有窗口、阈值、交互、期限和结果都计入统一搜索预算与 FDR；
6. 风险状态因子只能预测绝对收益/流动性/回撤，不得包装成方向 alpha；
7. 宏观、利率、forward、swap 和仓位只按真实或保守 `available_time` 向后合并；
8. current-vintage 数据不能通过添加人为 lag 变成严格 PIT；
9. policy rate/overnight reference 不是 OIS，利率平价合成 forward 也不是真实市场 forward；
10. long 用 ask 入/bid 出，short 用 bid 入/ask 出；不能先用 mid 找收益再挑成本模型；
11. `no_data` 和缺小时不能前填；缺一条必要腿时组合为空，不对剩余腿重归一化；
12. 负对照或 future-information canary 失败时拒绝整条研究管线；
13. 同 bar 同时触及止盈止损时按止损；
14. 只有 candidate verdict 才能生成冻结模型，只有全新冻结后数据才能做 forward；
15. OANDA 代码只允许 practice 域名，计划与提交分离，默认不提交订单。

## 7. 已有实证结果：全部未获批准

| 研究轮次 | 数据与结果 | 当前判定 |
|---|---|---|
| 六类传统策略 | 2024-07 至 2026-07 Yahoo 4h；主要策略收益约 -9.8% 至 -11.7% | 拒绝 |
| 协整策略 | 仅 6 笔，约 +0.09% | 样本不足，拒绝 |
| 多因子 v1 | 4 个开发折复合约 -5.68%；已查看 holdout 约 -0.25% | 拒绝 |
| 成对 FDR v2 | 4 个开发折均无 FDR 合格因子，空模型、0 笔交易 | 正确拒绝，不是 0% 盈利 |
| 慢周期 v1 | 统计单位错误，结果已看 | invalidated，但搜索暴露保留 |
| 慢周期 v2 | bootstrap 仅 1,000 次，无法分辨首条 BH 阈值 | invalidated，但搜索暴露保留 |
| 慢周期 v3/v4 | v4 为 43 因子×3 期限×5 折；仅 2 个风险状态在首折入选且 OOS 翻号 | 拒绝 |
| synthetic carry | 仅软件/契约验收 | 不构成市场收益证据 |

`outputs/paper_plan_approved_only.json` 当前为空数组。任何 agent 若声称“已经找到盈利因子”，
必须先解释它如何通过注册表、FDR、非重叠 OOS、真实 bid/ask、历史融资和全新 forward；
否则该表述与当前项目证据矛盾。

## 8. 搜索历史与不可恢复的 holdout

机器审计文件：`outputs/research_registry_audit.json`。

| 指标 | 当前值 |
|---|---:|
| 搜索轮次 | 6 |
| 已披露 unique factor definitions | 266 |
| fold-level hypothesis tests | 3,057 |
| factor-outcome evaluations | 3,312 |
| 注册假设 | 16 |
| active | 13 |
| preregistered | 11 |
| deferred missing data | 2 |
| superseded unevaluated | 3 |
| 已查看市场历史截止 | 2026-07-13 |

因此，2026-07-13 及更早的数据不能重新称为 untouched holdout。新候选即使在旧历史上表现好，
也只能是探索结果；最终只能依赖冻结后新增时间。注册表已有一次 outcome-free 的
`LOCAL-PAPER` 契约修订，必须保留其审计记录。

## 9. 数据资产与研究资格

> 2026-07-17 产品范围更新：核心目标是 broker-neutral 策略/因子挖掘工具。法律实体、辖区和
> 账户类型不再是因子发现的前置条件；它们仅属于未来可选的账户级净收益/执行验证。研究管线
> 应分别报告 `factor_discovery_ready` 与 `historical_cost_validation_ready`，详见
> `docs/FACTOR_MINER_PRODUCT_SCOPE_ZH.md`。

### 9.1 市场行情

| 数据 | 本机状态 | 允许用途 | 主要限制 |
|---|---|---|---|
| Yahoo midpoint | 已有日频和 4h 数据及多轮输出 | 软件验证、淘汰明显无效假设 | 非 broker bid/ask；无可靠历史 swap |
| Dukascopy SQLite | GBPUSD、EURUSD 已到达并机械审计通过；均为旧区间、非 formal-ready | bid/ask、tick 路径、点差、事件和日线重建 | 单一报价源；不是目标 broker 成交或全市场 tape；缺新区间和批次 manifest |
| OANDA financing | 已归档美国实体 2025--2026 | 不利融资压力和当前执行参考 | 不能写成 2016--2025 历史已实现融资 |
| 目标 broker 历史 swap/forward | 未取得 | 正式 carry 与慢周期净收益 | 当前最重要缺口之一 |

正式数据宇宙的设计为 14 个 SQLite：原慢周期 12 对加 `USDNOK`、`USDSEK`。慢周期仍只消费
冻结的 12 对；FIX-W 使用九个 G9 美元腿的组合宇宙。数据宇宙和策略权重宇宙不能混淆。

### 9.2 外部数据

| 数据组 | 当前状态 | 资格边界 |
|---|---|---|
| FRED/BIS REER、风险、参考利率 | 39/39 下载任务成功 | 多数 current-vintage，探索用途 |
| CFTC TFF 仓位 | 2006 起，已标准化 | 60 天保守 lag + current/revised archive；只探索 |
| CFTC 发布证据日历 | 2016--2025，522 个 report dates | 0 个完整 actual timestamp；不能严格晋级 |
| CFTC Weekly Swaps | 2018 起 336 个 edition | 全部 `strict_pit_eligible=false`；结构/活动研究 |
| CFTC BPR | 下载器已实现，尚未全量执行 | current permanent copy，预计 0.15--0.40 GB |
| 官方隔夜/政策利率 | 8/8 源成功、55,756 行 | 只有 RBA 明确命名 AUD 1M/3M OIS；NZD 主源缺 |
| Supplemental | Pink Sheet、GSCPI、GEPU、GPR、OFR、CISS、BCPI、RBA、Cboe 已下载 | 多数 current-vintage；GSCPI 2022-01 后有严格 vintage |
| Philly Fed RTDSM | 572,140 行 CPI/IP 真 vintage | 可做慢周期 as-of；不能做日内 surprise |
| Philly Fed SPF | 40 个 2016--2025 官方发布日期 | 数值是 current consolidated archive，不是逐季原版 |
| ONS GDP real-time | 156 个 edition 目录已建立 | 旧工作簿缺原始发布时间；当前 fail closed、无完整 PIT 面板 |
| WMR/Tokyo/ECB 日历 | 2016--2025，10,959 行，manifest/raw hash 完整 | 可供正式事件日历加载 |
| 八央行 blackout | Fed/ECB/BoJ/RBA 已实现 | BoE/SNB/BoC/RBNZ 仍 fail closed，正式完整加载会拒绝 |
| OECD Economic Outlook | 下载器已实现 | EO99 请求被 429；不得只用现代版伪装完整历史 |
| BIS GLI/LBS/OTC/Triennial、ALFRED | 已做资料目录，未下载/未建完整契约 | 目前不得进入正式因子 runner |

所有新外部数据必须保存 raw、URL、retrieved time、SHA-256、解析版本、available-time 规则和
manifest。下载成功不自动意味着可以进入方向因子。

## 10. 已接收 Dukascopy 数据验收结果

### 10.1 GBPUSD

数据库：`data/dukascopy_sqlite/GBPUSD.sqlite`

| 项目 | 结果 |
|---|---:|
| 区间 | 2016-01-01 至 2025-09-15 排他边界 |
| 文件大小 | 1,354,809,344 bytes |
| SHA-256 | `6d54500c...b0be2bba5` |
| 候选小时 | 61,251 |
| `ok` | 60,486 |
| `no_data` | 765 |
| 数据库缺行 | 0 |
| payload SHA/LZMA/字段错误 | 0 |
| tick | 283,237,102 |
| crossed/nonpositive/乱序/非法 size | 0 |

765 个 `no_data` 中：506 个是标准纽约周边界，255 个是圣诞/新年，3 个是 2019 年美国
阵亡将士纪念日周末延迟开市，剩余 1 个为 `2016-09-02T18:00:00Z` 的孤立空档。
该空档前一小时在 `17:05:29.999Z` 后停止报价，`19:00:00.156Z` 才恢复。

独立 FRED `DEXUSUK` 对照 2,423 个纽约中午观测：价格水平相关系数 0.999998，
相邻观测收益相关系数 0.999800，绝对差异中位数约 0.91 bps，价格尺度和方向合理。

当前判定为**机械审计通过、正式研究有条件通过**，尚缺：

1. VPS 用下载器 v1.1.1 重查历史 `no_data`；
2. 重新传回数据库及两个 sidecar；
3. 传回 VPS 同批次原始 `_sqlite_manifest.json`；
4. 按新文件重新运行全库审计；
5. 与其余货币对形成共同覆盖后再进入 G0。

注意：`configs/long_horizon_dukascopy_sqlite.yaml` 当前要求结束于 `2026-01-01`，而本文件只到
`2025-09-15`。这是明确的区间契约不一致。下一位 agent 必须选择延长全部数据库到
2026-01-01，或经用户确认建立另一个明确命名的 2025-09-15 排他配置；不得静默忽略。

完整报告见 `docs/GBPUSD_DUKASCOPY_DATA_AUDIT_2026-07-16_ZH.md`。

### 10.2 EURUSD

数据库：`data/dukascopy_sqlite/EURUSD.sqlite`

| 项目 | 结果 |
|---|---:|
| 区间 | 2016-01-01 至 2025-09-15 排他边界 |
| 下载器 | 1.0.0 |
| 文件大小 | 1,445,834,752 bytes |
| SHA-256 | `91041f23...a11ea30` |
| 候选小时 | 61,251 |
| `ok` | 60,491 |
| `no_data` | 760 |
| 数据库缺行 | 0 |
| payload SHA/LZMA/字段错误 | 0 |
| tick | 275,108,137 |
| crossed/nonpositive/乱序/非法 size | 0 |

远端 sidecar、本地文件和审计计算的 SHA-256 三方一致，SQLite `quick_check=ok`。深度审计检查
全部 60,491 个压缩 payload 和 275,108,137 条 tick，`error_count=0`、`warning_count=0`，并覆盖
Brexit、2020 年 3 月和 2022 年英国 mini-budget 压力窗口。

当前判定为**机械审计通过、正式 intake 未通过**：数据库仍是 1.0.0 生成的旧区间，尚未按
v1.1.1 扩展到 `2026-01-01` 并刷新 `no_data`，且服务器未提供 `_sqlite_manifest.json`。它可以用于
接收验证和软件测试，不得据此打开 WP2 全宇宙 G0 或收益检验。

机器报告见 `outputs/dukascopy_audit/EURUSD_dukascopy_audit.json`。

## 11. 阶段门、暂停点与失败分支

| 里程碑 | 必须完成的工作包 | 允许产生的结论 | 必须暂停/停止的条件 |
|---|---|---|---|
| M0 可恢复基线 | WP0、WP1 的接收台账/validator 子集 | 项目可恢复、数据接收流程可复现 | 完成后先向用户汇报；未备份不得继续修改 |
| M1 正式数据就绪 | WP1、WP2 | 14 库 G0 pass/retry/reject | 任一必要品种失败则修复或拒绝，不静默缩小宇宙 |
| M2 解盲前冻结 | WP3、WP4、WP5、WP6 | 成本/账本/日历软件通过，候选已冻结 | 历史成本不完整则保持 `cost_incomplete_research_only`；解盲前暂停 |
| M3 一次正式检验 | WP7 | `reject`、`empty model` 或 `candidate-requires-forward` | reject/empty 立即关闭当前轮；不得在同一历史补参数 |
| M4 新前向期 | WP8 | `collecting`、forward reject 或 practice candidate | 少于 90 天不评价；失败后淘汰，修改即视为新模型 |
| M3-R 新研究分支 | WP9 | 只生成新的有限候选与预注册章程 | 必须由用户确认开启；不得继承旧轮次的“预注册”标签 |

M0 的只读基线命令为：

```bash
cd /Users/open/fx-trading-system
git status --short
du -sh data outputs
uv run pytest
uv run ruff check .
uv run fxtrade research-registry-audit \
  -r configs/factor_research_registry.yaml \
  -o outputs/research_registry_audit.json
```

应确认测试基线仍为 399 项、registry 所有 supplied artifact 哈希通过，并确认
`outputs/paper_plan_approved_only.json` 仍为空。任何数量变化都先解释是预期新增测试还是环境/代码
漂移，不能机械地把“不是 399”判为失败。

M2 解盲前才允许运行以下冻结命令：

```bash
uv run fxtrade long-horizon-freeze-sqlite \
  --database-dir data/dukascopy_sqlite \
  -c configs/long_horizon_dukascopy_sqlite.yaml \
  -d configs/long_horizon_dukascopy_candidates.yaml \
  -r configs/factor_research_registry.yaml \
  -o outputs/long_horizon_dukascopy_freeze
```

它只允许生成 factor-only 调度。如果数据库区间、manifest 或候选声明不一致，应保留失败并修复
输入合同，不能放宽验证器去“先跑起来”。只有用户看到 M2 报告并明确继续，agent 才能打开标签
或运行收益检验。

不在关键路径上的免费补充数据包括 CFTC BPR、ONS 原始工作簿、OECD EO99--118 窄查询，以及
机制先登记后的 BIS/ALFRED。它们可以在等待期下载和归档，但不得延迟 M0--M2，也不得仅因为
“数据免费”就增加因子维度和搜索预算。

## 12. 关键文件导航

| 目的 | 文件 |
|---|---|
| 本交接总览 | `docs/PROJECT_HANDOFF_SUMMARY_ZH.md` |
| 总体执行路线 | `docs/RESEARCH_EXECUTION_ROADMAP_2016_2025_ZH.md` |
| 慢周期研究契约 | `docs/LONG_HORIZON_FACTOR_RESEARCH_ZH.md` |
| 外部数据状态 | `docs/EXTERNAL_DATA_DOWNLOAD_PLAN_ZH.md` |
| 文献和方法 | `docs/FX_FACTOR_LITERATURE_MAP_ZH.md` |
| GBPUSD 审计 | `docs/GBPUSD_DUKASCOPY_DATA_AUDIT_2026-07-16_ZH.md` |
| EURUSD 审计 JSON | `outputs/dukascopy_audit/EURUSD_dukascopy_audit.json` |
| 两品种 commissioning | `outputs/dukascopy_commissioning/EURUSD_GBPUSD_commissioning.json` |
| 分角色 intake ledger | `outputs/dukascopy_intake/intake_ledger.json` |
| Dukascopy 工作流 | `docs/DUKASCOPY_SQLITE_DOWNLOADER_ZH.md` |
| 搜索账本 | `configs/factor_research_registry.yaml` |
| 搜索账本审计 | `outputs/research_registry_audit.json` |
| 慢周期冻结候选 | `configs/long_horizon_dukascopy_candidates.yaml` |
| GBPUSD 审计 JSON | `outputs/dukascopy_audit/GBPUSD_dukascopy_audit.json` |
| FRED 对照 JSON | `outputs/dukascopy_audit/GBPUSD_FRED_DEXUSUK_comparison.json` |
| 全库审计工具 | `scripts/audit_dukascopy_sqlite.py` |
| 两品种 commissioning runner | `src/fx_system/dukascopy_commissioning.py` |
| transfer/event reader | `src/fx_system/dukascopy_event_data.py` |
| 纽约收盘日线 | `src/fx_system/dukascopy_daily.py` |
| 慢周期冻结 runner | `src/fx_system/long_horizon_runner.py` |
| 日内 FIX-W runner | `src/fx_system/intraday_runner.py` |
| 组合账本 | `src/fx_system/portfolio_runner.py` |

## 13. 禁止误读的几句话

- “程序能回测”不等于“策略盈利”。
- “数据库 missing=0”不等于“每小时都有行情”。
- “FRED/CFTC 已下载”不等于“数据严格 PIT”。
- “Dukascopy 有 bid/ask”不等于“目标 broker 会按同价成交”。
- “风险状态可预测”不等于“它能决定做多或做空”。
- “空模型收益 0%”不等于“模型保本”，而是系统拒绝交易。
- “已预注册候选”不等于“候选已通过检验”。
- “历史上看起来稳定”不等于“还拥有 untouched holdout”。
- “practice 下单软件可用”不等于“任何策略已获准下单”。

下一阶段的技术目标不是尽快产出一个漂亮 Sharpe，而是先让每一条收益都能回答：数据当时是否
可得、报价是否可成交、成本是否完整、试验是否计数、OOS 是否真的没被看过、结果是否能由
单一危机或单一货币解释。只有这些问题全部有可审计答案，盈利讨论才有意义。
