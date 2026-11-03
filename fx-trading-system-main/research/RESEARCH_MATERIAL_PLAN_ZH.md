# 外汇量化因子资料查找计划

更新日期：2026-07-16  
约束：本仓库仅允许在 `research/` 写入；其余目录只读。  
目标：建立**研究级深度**的外汇量化资料库，支撑本项目因子挖掘、复制边界、验证与成本合同。  
读者假设：可用最强模型精读与推导；**不因“新人”而降维、不写科普替代论文**。

---

## 0. 一页结论

本项目已经有较完整的研究基础设施与文献地图（见 `docs/FX_FACTOR_LITERATURE_MAP_ZH.md`、`docs/LONG_HORIZON_FACTOR_RESEARCH_ZH.md`、`docs/RESEARCH_EXECUTION_ROADMAP_2016_2025_ZH.md`）。当前**没有批准交易的因子**；最大硬缺口是：

1. 目标账户 2016–2025 真实 swap/rollover 或同口径 forward points  
2. 完整可成交 bid/ask 宇宙（Dukascopy 仍在接收）  
3. 宏观 surprise 所需的历史 consensus（通常不可免费）  
4. 严格 as-published vintage 的外部数据链

`research/` 的任务不是再发明一轮因子网格，也不是做浅层入门合集，而是：

> 把**顶刊/工作论文原文、可复制公式、识别策略、数据合同、失败模式与本项目映射**收齐，并标注  
> “精确复制 / 有边界的项目扩展 / 仅机制参考 / 明确否决”。

### 深度标准（强制）

每条入库资料至少达到下列之一；达不到则标 `shallow_reject`，不占主目录：

| 层级 | 要求 | 示例 |
|---|---|---|
| L3 机制深度 | 完整收益定义、排序规则、持有期、样本、成本处理、稳健性表 | Lustig carry；Menkhoff momentum |
| L4 合同深度 | 可写成 point-in-time 数据字段与 fail-closed 条件 | CIP basis 所需 spot/forward/OIS/settlement |
| L5 推断深度 | 多重检验、样本重叠、数据挖掘暴露、样本外设计 | DSR/PBO/SPA；Harvey et al. |
| L2 仅允许作附录 | 官方 methodology / 数据字典 / 日历 | WMR PDF、CFTC release notes |
| L1 禁止作主源 | 博客心得、指标教程、无公式回测截图 | 一律不进 02–06 主 catalog |

**笔记最低规格（每篇核心论文）：**

1. 经济机制（1 段，不是口号）  
2. 精确公式（收益、信号、组合权重、滞后）  
3. 数据与样本（来源、频率、币种集合、起止）  
4. 成本与可实现性（原文扣了什么；迁移到零售 bid/ask 后会坏在哪）  
5. 识别与稳健性（控制变量、子样本、危机窗）  
6. 复制清单（字段级：有则精确复制 / 缺则 fail closed / 可做的扩展须另标名）  
7. 本项目映射（registry 因子名、持有期、否决条件、是否 reused-history）  
8. 后续文献（引用链上 2–5 篇：确认、反驳或边界收紧）

**明确加码（相对初版计划）：**

- 不只收“一篇代表作”，要收**引用链**：奠基 → 主要复制/反驳 → 2015 后更新 → 与零售执行相关的边界论文  
- 公式级，不只摘要级；能写伪代码就写伪代码  
- 区分 **published premium** vs **implementable net of costs**  
- 对 2016–2025 样本外推写明：制度变化（Basel/Volcker、CIP 偏离常态化、定盘改革）  
- 新人路径 = **深度研读顺序**，不是简化读本；基础缺口用 L2 官方文档补，不用二手鸡汤  

---

## 1. 与本项目的对齐关系

| 项目现状 | research 要补什么 |
|---|---|
| 慢周期：Carry / Momentum / Value / Commodity / Risk state 已入注册表 | 原文公式 + 复制合同 + 后续反驳/边界文献 |
| 日内：FIX-W、LOCAL-PAPER、ASIA-LDN 已有冻结规格 | 定盘/时段全文核对 + 成本后转负的证据 |
| v4 免费数据筛选：方向因子 0 入选 | 机制与验证深度，不扩技术指标网格 |
| 成本 incomplete | financing/forward/CIP 字段级合同与 broker 证据 |
| 使用者可调用最强模型 | 提供可精读的 L3–L5 材料与结构化笔记，而非浅释 |

---

## 2. 目录结构（已创建）

```text
research/
├── RESEARCH_MATERIAL_PLAN_ZH.md   # 本计划
├── 01_foundations/                # 外汇市场、报价、结算、交易时段基础
├── 02_factor_literature/          # 慢周期因子经典文献与笔记
├── 03_microstructure_intraday/    # 定盘、时段、流动性、公告微观结构
├── 04_validation_methods/         # FDR/DSR/PBO/SPA/walk-forward/防过拟合
├── 05_data_contracts/             # PIT、vintage、available_time、日历
├── 06_broker_costs/               # spread/swap/rollover/forward/CIP
├── 07_open_source_tools/          # 开源回测/因子库索引（只收录可审计者）
├── 08_datasets_catalog/           # 免费/半免费数据源目录与下载边界
├── 09_deep_study_path/            # 深度研读路径（非浅显入门）
└── notes/                         # 公式笔记、引用链、待核验问题
```

每个子目录最终应至少有：

- `README.md`：收什么、不收什么、深度门槛  
- `CATALOG.md`：DOI/URL、开放获取、L 级、复制状态  
- 原文链接（优先 DOI / NBER / BIS / 期刊官方；能合法落盘则落盘）  
- `notes/<paper_slug>.md`：满足上文「笔记最低规格」的 L3+ 笔记  
- `replication_checklist.md`（主题级）：字段、频率、滞后、成本、否决

---

## 3. 资料查找方向（按优先级）

### P0 — 立刻需要（直接堵住当前研究硬缺口）

#### P0.1 真实融资与远期合同

**要找：**

- 目标 broker（OANDA / 计划使用的零售账户）历史 swap / financing / rollover 文档与可导出历史  
- 官方 1M/1W forward points 或可交易 outright forward 的公开/半公开来源说明  
- CIP / cross-currency basis 机制资料（约束合同，不是方向因子）

**优先来源：**

| 类型 | 候选来源 | 用途 |
|---|---|---|
| Broker 官方 | OANDA financing history API/文档、账户条款 | 真实融资成本合同 |
| 学术 | Du, Tepper & Verdelhan (CIP quarter-end)；Borio et al. BIS 季报 | 解释为何政策利率 ≠ 可交易 carry |
| 市场结构 | LSEG WMR methodology；ECB reference rates 说明 | 结算/定盘口径 |

**产出文件建议：**

- `06_broker_costs/SWAP_FORWARD_SOURCES.md`  
- `06_broker_costs/CIP_CONTRACT_CHECKLIST.md`

**否决：** 用政策利率或 OIS 公式伪造 `F_hat` 后声称“真实 carry 复制”。

#### P0.2 慢周期因子：奠基作 + 引用链（深度，不只一篇代表）

| 主题 | 核心（必精读） | 加码（复制/反驳/边界） | 深度焦点 |
|---|---|---|---|
| Carry | Lustig–Roussanov–Verdelhan；Menkhoff–Sarno–Schmeling–Schrimpf | Hassan–Mano；carry 分解与质量 | HML_FX 定义、美元因子、forward discount 精确构造 |
| Carry crash | Brunnermeier–Nagel–Pedersen | 后续 funding liquidity / crash risk 文献 | 负偏度、VIX/funding 状态、门控能否事前冻结 |
| Currency momentum | Menkhoff et al. JFE 2012 | 与 value 联合（Asness–Moskowitz–Pedersen） | 1–12m 形成期、skip、横截面排序、成本敏感性 |
| TS momentum | Moskowitz–Ooi–Pedersen | 资产类别外推边界 | 自身趋势 vs 横截面；重叠持有与 vol scaling |
| Currency value | Menkhoff et al. RFS | REER 构造与 vintage 问题 | 长期均值窗口、current-vintage 污染 |
| Commodity FX | Ready–Roussanov–Ward；Ferraro–Rogoff–Rossi | 贸易结构 vs 油价冲击识别 | 美元计价商品的内生性 |
| External imbalance | Della Corte–Riddiough–Sarno | 数据可得性审计 | 为何本项目暂不实现（八币种资产负债表） |
| Vol-managed | Moreira–Muir | 与阈值门控的区别 | own-factor RV、全样本 c 的 PIT 修正 |
| Liquidity RP | Söderlind–Somogyi 2024 | G9 子集扩展边界 | 1M forward 硬依赖、beta 符号与滞后 |
| Option VRP/RR | Della Corte–Ramadorai–Sarno | Cboe 30D IV 不能冒充 | OTC smile 五点 vs 交易所 IV |
| Dollar / basis | Borio et al.；Du–Tepper–Verdelhan | CIP 常态偏离 | 合同约束，不是方向 alpha |
| Dealer capacity | Fang IFDP 2019 | 2016–2025 衰减 | 负对照，不进方向候选 |

**产出：**

- `02_factor_literature/CATALOG.md`（DOI、L 级、开放获取、复制状态）  
- 每篇 L3+ 笔记（见深度标准 8 项）  
- `02_factor_literature/CITATION_GRAPH.md`（主题内引用关系）

#### P0.3 验证与防数据挖掘（项目已实现，需要“为什么这样写”的教材）

| 方法 | 必收 | 用途 |
|---|---|---|
| Multiple testing / FDR | Benjamini–Hochberg；Harvey, Liu & Zhu | 解释统一 FDR 分母 |
| Deflated Sharpe | Bailey & López de Prado | DSR |
| PBO / CSCV | Bailey et al. | 过拟合概率 |
| SPA | Hansen | 优越预测能力检验 |
| Purged CV | López de Prado AFML 相关章节 | purge / embargo 直觉 |
| Bootstrap | Politis & Romano stationary bootstrap | 块重采样依据 |

**产出：** `04_validation_methods/METHODS_MAP.md`（方法 → 项目代码入口对照，只写映射，不改代码）

---

### P1 — 高价值（支撑日内与微观结构）

#### P1.1 定盘与时段

| 主题 | 文献 | 本项目对应 |
|---|---|---|
| 全球定盘 | Krohn, Mueller & Whelan | FIX-W |
| 本地时段 | Breedon & Ranaldo | LOCAL-PAPER |
| London fix 对冲 | Melvin & Prins | WMR 月末交互项 |
| FX 流动性 | Mancini, Ranaldo & Wrampelmeyer | spread q90 过滤 |
| 宏观公告 | Andersen et al.；Faust et al. | blackout / 禁止无 consensus 的 surprise |

**产出：** `03_microstructure_intraday/INTRADAY_SOURCE_MAP.md`

#### P1.2 日历与 PIT 数据合同

**要找：**

- CFTC 发布日历与 COT/TFF 修订说明  
- ALFRED / Philadelphia Fed RTDSM vintage 使用说明  
- BIS GLI / LBS / OTC / Triennial 的**允许用途边界**  
- 各国央行假日与利率决议时间戳来源  
- Cboe EVZ/EUVIX/JYVIX/BPVIX 官方定义（仅风险状态）

**产出：** `05_data_contracts/PIT_AND_VINTAGE_GUIDE.md`  
**硬规则：** 无 `available_time` / 无 as-published 证据 → `strict_pit_eligible=false`

#### P1.3 公开数据集目录（可下载边界）

| 数据 | 来源 | 允许角色 |
|---|---|---|
| Spot bid/ask tick | Dukascopy（项目已有管线） | 执行侧主价格 |
| 政策利率 / 官方利率 | 央行 / FRED / ECB | 参考，非真实 swap |
| REER | BIS | Value 探索（current-vintage） |
| 商品价格 | World Bank Pink Sheet | 商品货币探索 |
| 风险状态 | OFR FSI、ECB CISS、NFCI、STLFSI | 非方向风险 |
| 隐含波动 | Cboe 三币种 30D IV | 风险状态，非横截面 VRP |
| 仓位 | CFTC | 拥挤探索，非订单流 |
| Dealer aggregate | NY Fed Markets API | 2016–2025 负对照 |

**产出：** `08_datasets_catalog/DATASETS.md`（字段、频率、lag、许可、禁止推断）

---

### P2 — 深度研读路径与市场微观基础（不降维）

#### P2.1 市场与执行基础（L2–L3，官方 + 学术，不是零售教程）

- 报价约定、settlement、rollover 的**官方/主经纪商级**说明  
- 零售 vs 银行间：延迟、last-look、点差制度、swap 标记  
- 为何 Olsen/Dukascopy/broker mid 不可互换  
- 定盘方法论（WMR/ECB/Tokyo）原文

**产出：** `01_foundations/` 以 methodology + 学术微观结构为主，禁止“外汇入门 10 课”式主源

#### P2.2 深度研读路径（供最强模型 + 人一起啃）

按**机制依赖顺序**，不是按“好不好懂”：

```text
Week 1  验证与数据挖掘（先建立否决权）
        Harvey–Liu–Zhu；Bailey DSR/PBO；Hansen SPA；项目 v4 拒绝结论
Week 2  Carry 机制与 crash
        LRV；Menkhoff carry；BNP crash；Borio basis；真实 forward 合同
Week 3  Momentum / Value / 联合证据
        Menkhoff mom；TSMOM；currency value；AMP value-momentum
Week 4  微观结构与定盘
        Breedon–Ranaldo；Krohn et al.；Mancini et al.；成本后转负
Week 5  流动性风险、VRP、vol-managed
        Söderlind–Somogyi；Della Corte options；Moreira–Muir
Week 6  本项目契约对照
        逐条映射 registry、cost incomplete、reused-history、WP6–9
```

**产出：** `09_deep_study_path/DEEP_STUDY_PATH_ZH.md`  
每课输出：精读问题清单 + 必推导公式 + 与代码/配置的对照点（只读映射）

#### P2.3 明确不收录 / 低优先级

| 类型 | 原因 |
|---|---|
| 外汇“圣杯”指标合集、YouTube 信号课 | 无经济机制、不可审计 |
| 无成本 mid-only 回测博客 | 与 fail-closed 冲突 |
| 把论文缩成“三句话结论”的二手文 | 可作索引，不可替代原文 |
| 三角套利零售 bar 回测 | 执行不可行 |
| 无限技术指标网格 | 抬高 FDR 分母，v4 已拒绝 |
| 付费信号/跟单广告 | 无研究价值 |
| 只讲直觉不给公式的“因子科普” | 达不到 L3 |

---

### P3 — 可选扩展（WP9 新章程前再开）

仅当当前轮关闭、用户确认新研究章程后收集：

- External imbalances（Della Corte et al.）八币种资产负债表  
- OTC option smile 全截面（VRP/RR 精确复制）  
- 授权订单流（Evans & Lyons 机制，非 CFTC 替代）  
- 多 broker 历史 financing 对比  
- 非 G9 新兴市场货币扩展

---

## 4. 查找工作流程（执行顺序）

```text
Phase A  盘点已有
  └─ 对照 docs/FX_FACTOR_LITERATURE_MAP_ZH.md 做“已引用 / 未落盘”清单

Phase B  落盘 P0 文献与成本资料
  ├─ 02_factor_literature：核心 10–15 篇
  ├─ 04_validation_methods：FDR/DSR/PBO/SPA
  └─ 06_broker_costs：swap/forward/CIP 合同

Phase C  落盘 P1 日内与数据目录
  ├─ 03_microstructure_intraday
  ├─ 05_data_contracts
  └─ 08_datasets_catalog

Phase D  深度研读路径与执行基础
  ├─ 01_foundations（methodology + 微观结构，非科普）
  └─ 09_deep_study_path

Phase E  索引与缺口报告
  └─ research/INDEX.md + notes/GAPS.md
```

每条资料入库模板（写入对应 `CATALOG.md`）：

```markdown
### [短标题]
- 类型: paper | official_doc | dataset | code
- 引用: Author (Year) / 官方机构
- DOI/URL:
- 开放获取: yes | no | abstract_only | preprint
- 深度层级: L2 | L3 | L4 | L5
- 引用链角色: foundational | replication | critique | boundary | data_contract
- 本项目映射: 因子名 / 验证方法 / 成本合同 / 否决边界
- 数据依赖（字段级）: ...
- 精确公式要点: ...
- 成本处理（原文）: none | spread | swap | both | unclear
- 2016–2025 外推风险: ...
- 复制状态: exact_possible | extension_only | fail_closed_missing_data | negative_control
- 笔记路径: notes/<slug>.md
- 状态: planned | linked | downloaded | deep_noted
- 备注:
```

---

## 5. 按主题的搜索关键词（可直接检索）

### 5.1 学术检索

- Google Scholar / SSRN / NBER / BIS Working Papers / Fed IFDP  
- 关键词包：

```text
"currency carry trade" risk factors Lustig
"currency momentum strategies" Menkhoff
"time series momentum" Moskowitz
"currency value" REER Menkhoff
"carry trades and currency crashes" Brunnermeier
"volatility managed portfolios" Moreira Muir
"liquidity risk premia" foreign exchange Söderlind
"fixing window" foreign exchange Krohn
"intraday patterns" FX Breedon Ranaldo
"deflated sharpe ratio" Bailey
"probability of backtest overfitting"
"superior predictive ability" Hansen
"covered interest parity" Du Tepper Verdelhan
"cross-currency basis" Borio
```

### 5.2 官方与数据门户

```text
BIS effective exchange rate REER
World Bank Pink Sheet commodities
CFTC Commitments of Traders historical
Philadelphia Fed real-time data set RTDSM
ALFRED St Louis Fed vintage
Cboe EVZ EUVIX JYVIX BPVIX history
OANDA financing rates documentation
LSEG WMR methodology PDF
ECB euro foreign exchange reference rates
NY Fed primary dealer statistics API
OFR Financial Stress Index
ECB CISS
```

### 5.3 开源工具（只收录，不默认接入）

```text
vectorbt / backtesting.py / zipline-reloaded  # 通用回测参考
alphalens-reloaded / empyrical-reloaded      # 因子分析展示
arch / statsmodels                           # 统计
polars / pandas                              # 数据
```

开源工具页只做**对照表**：能否处理 bid/ask、PIT、多重检验、融资；不能处理则标注“不适合本项目正式路径”。

---

## 6. 与项目工作包的对应

| research 包 | 支撑的项目 WP |
|---|---|
| 06_broker_costs | WP3 成本合同 |
| 02_factor_literature + 04_validation | WP6/WP7 预注册与成本后验证 |
| 03_microstructure_intraday | WP5 日内入口 |
| 05_data_contracts + 08_datasets | WP1/WP2 数据验收与 G0 |
| 09_deep_study_path | 深度研读与项目契约对照，不阻塞 WP |

原则：

- research 资料**不能**绕过 `cost_incomplete` / `empirical_ready=false`  
- 读到新因子想法 → 只记入 `notes/`，**不得**直接扩注册表搜收益  
- 新候选进入搜索必须走 WP9 章程 + trial budget

---

## 7. 交付物清单（本计划完成后的完成定义）

| # | 交付物 | 完成标准 |
|---|---|---|
| 1 | `research/INDEX.md` | 全部子目录可导航 |
| 2 | 核心文献 catalog ≥ 20 条 | 含 DOI、映射、状态 |
| 3 | 核心论文 L3+ 深度笔记 | 满足 8 项最低规格；含公式与复制清单 |
| 4 | 主题引用链图 | 奠基→复制/反驳→边界 |
| 5 | 数据集目录 | 字段、频率、PIT、禁止推断 |
| 6 | 成本/远期来源清单 | 已有/缺失/需向 broker 申请 |
| 7 | 深度研读路径 6 周 | 问题清单 + 必推导公式 + 只读代码映射 |
| 8 | `notes/GAPS.md` | 仍缺且阻塞精确复制或正式净收益的资料 |

非目标：

- 不保证找到盈利因子  
- 不在 research 外写代码/改配置  
- 不下载大型行情库到 research（行情走项目 `data/` 管线）  
- 不收录盗版付费数据库导出  
- **不做浅显科普替代顶刊精读**  
- 不把“新人友好”写成降低机制/公式/检验深度

---

## 8. 预估工作量（人工检索 + 摘要）

| 阶段 | 内容 | 粗估 |
|---|---|---|
| A | 对照现有 docs 做 gap 表 | 0.5 天 |
| B | P0 文献与成本 | 2–3 天 |
| C | P1 日内/数据 | 2 天 |
| D | 深度研读路径 + 执行基础 | 1.5–2 天 |
| E | 索引、引用链、GAPS | 0.5–1 天 |
| **合计** | | **约 8–11 天**（深度笔记拉长，不压缩公式推导） |

可并行：B 的文献精读 与 C 的数据/微观结构合同；主 agent 统一 L 级与复制状态。

---

## 9. 下一步（等你确认后执行）

建议顺序（仍只写 `research/`；深度优先）：

1. 各子目录 `README.md`（写入 L3+ 门槛）  
2. 从文献地图生成 `02_factor_literature/CATALOG.md` + 引用链骨架  
3. P0 核心论文：合法链接落盘 + **完整 8 项深度笔记**（不是一句话摘要）  
4. `04_validation_methods` 与项目检验实现的对照（方法深度）  
5. `06_broker_costs` + `08_datasets_catalog` 字段级合同  
6. `09_deep_study_path/DEEP_STUDY_PATH_ZH.md`  
7. `notes/GAPS.md`

并行建议（1 主 + 3 子，仍保持深度）：

- Agent-Lit：02 因子引用链 + 深度笔记  
- Agent-Micro：03 + 05 + 08  
- Agent-CostVal：06 + 04  
- 主 agent：统一 L 级口径、去重、GAPS、研读路径

确认“按深度标准开始收集”后执行。
