# 第二层：结构化外部数据因子层建设计划

日期：2026-07-17。所有权：当前主 agent。

## 目标

第二层不负责第一轮价格因子结果，也不以新闻文本为起点。它建设一套 broker-neutral、
point-in-time、版本可追溯的结构化经济数据层，使利率、仓位、价值、商品和风险状态因子能够
声明“当时市场究竟知道什么”。

第二层只建设数据资格、特征和 outcome-blind 合同；在单独预注册前不把这些外部因子加入
价格层的 48 个假设，也不打开新增收益标签。

## 数据资格等级

每个 series 必须落入且只能落入一个等级：

| 等级 | 含义 | 允许用途 |
|---|---|---|
| `verified_strict_pit` | 保存了当期数值、真实/保守发布时间、版本和原始证据 | 可申请正式因子轮次 |
| `conservative_pit_current_archive` | available time 保守，但数值是当前修订档 | 探索/状态压力，不冒充 vintage |
| `exploratory_current_vintage` | 只有当前历史或人为 release lag | 机制研究与淘汰 |
| `research_only_retrieved_later` | 历史值事后回取，原发布时间不可证明 | 压力情景 |
| `ineligible` | 来源、时间、许可、单位或版本合同不完整 | 不进入 factor panel |

增加人为滞后不能把 current-vintage 升级成 strict PIT。

## 统一数据合同

每个外部数据集至少保存：

```text
source_id
series_id
observation_time
available_time
vintage_time
value
unit
revision_id
source_url
retrieved_at
raw_sha256
parser_version
quality
license_status
```

因子目录同时声明：

```text
data_dependencies
minimum_quality
maximum_staleness
revision_policy
directional_or_regime
eligible_horizons
missing_rule
```

加载器只允许向后 as-of join；不得 exact/nearest 向未来匹配，不得用 current value 填历史缺口。

## 建设优先级

1. 官方政策利率与隔夜参考利率：先作为结构化利率状态；不得冒充 OIS、forward 或账户 carry。
2. CFTC positioning：保留 60 天保守滞后和 current-revised 限制；优先做拥挤状态，不直接晋级。
3. BIS REER/value：明确 current-vintage 与真实 vintage 的边界，建立月度 available-time 合同。
4. GSCPI、金融压力、商品和全球风险：优先使用已有 preserved vintage；其余保持 exploratory。
5. 真正 OIS/forward：只有可交易历史、bid/ask、时间与许可齐全后才建立正式 carry 因子。
6. 央行/宏观事件日历：先作为 blackout/regime 输入；数值 surprise 需另外取得逐期 vintage。

非结构化央行声明、新闻和情绪分析暂不进入本阶段。

## 首个交付里程碑

- 一份逐 series 的资格台账与 blocker；
- 统一 external dependency metadata；
- outcome-blind eligible/excluded factor catalog；
- strict/conservative/current-vintage 三类 fixture；
- as-of、staleness、revision、prefix invariance 和 future-information canary 测试；
- 第二层不改变价格层的 factor count、FDR family 或任何已冻结 alpha hash。

首版机器目录已经实现于 `configs/external_factor_source_registry.yaml`，审计入口为
`scripts/audit_external_factor_sources.py`。2026-07-19 当前审计登记 13 个数据源视图，13/13 字节
完整性通过；当前没有正式方向源，GSCPI preserved vintages、RTDSM verified rows 与 Treasury
TIC `tressect` 通过风险状态资格，两个日历通过事件控制资格。RTDSM 逐行审计由
`scripts/audit_rtdsm_eligibility.py` 生成。详见
`outputs/external_factor_eligibility_20260717/ELIGIBILITY_REPORT_ZH.md`。

## 首个严格 PIT 特征面板（已完成）

`src/fx_system/structured_external_features.py` 已实现统一的 outcome-blind 接口，把三个正式
regime 定义分成特征值表和逐行谱系表：

```text
gscpi_risk_state_pit
us_cpi_12m_log_inflation
us_ip_6m_log_growth
```

构建入口是 `scripts/build_structured_external_regime_panel.py`，正式产物位于
`outputs/structured_external_regime_panel_20260717/`。默认面板覆盖
`[2016-01-01, 2026-01-01)` 的 3,653 个日度 UTC 决策时点，生成 10,959 行谱系。每一行都保存
实际选中的 observation、baseline、vintage、available time、staleness、严格资格及源文件和
manifest 哈希。

真实源审计结果：未来信息违规 0，非严格 ready 行 0，三个跨历史检查点的 truncated-prefix 与
未来版本篡改 canary 全部通过。GSCPI 因 preserved vintage 从 2022 年开始且六版本变化需要
热身，首个可用决策日是 2022-07-08；不得回填此前历史。IP 在 2025-12-02 至 2025-12-24 有
23 天超过 75 天 staleness 上限，因为 2025-10/11 两个 vintage 的日期仍未核验、只属
`conservative_pit`；严格面板正确留空，直到 `IPT25M12` 的核验发布日期。

该产物仍只是外部状态输入，不是方向 alpha，也未建立它与收益的交互。未来若把 regime 用于
筛选或调节价格因子，必须先冻结交互形式、缺失规则和新增多重检验家族，不能把它悄悄加入
第一层的 48 个假设。

## 五因子组合包与交互草案（2026-07-19）

正式事件控制也已完成统一接口：

- `benchmark_publication_state`：过去 24 小时内 Tokyo/ECB/WMR 已完成事件的三位 bitmask，
  组件谱系另存，不能只按 local date 猜测；
- `phillyfed_spf_release_state`：官方 date-only 发布经过 next-New-York-day
  `available_time` 后的一次脉冲，forecast values 永不加载。

事件控制的 `maximum_staleness_days=1` 代表过去 24 小时窗口的实际年龄上限，不代表可跨日
无限 carry。SPF 的 40 个脉冲中 32 个落在周日 00:00 UTC；下游若采用工作日决策，必须另行
冻结是否保留周日或滚动到下一可用决策。

两者与 GSCPI、RTDSM CPI/IP 合并为
`outputs/structured_external_feature_package_20260719/` 的五因子包，组合层会核对两个子
面板的每个 decision/feature 键、值、谱系、状态和 SHA-256。事件控制默认仅为 nuisance/blackout
control，不是方向 alpha。

央行日历另有一个严格 EURUSD source view：FED 81 行、ECB 80 行的真实/规则发布时间行，
不含 2 行 ECB date-only，父日历仍因 BOE 等缺口保持 `complete=false`。该 view 仅用于未来
EURUSD 公告风险 blackout 候选，不进入五因子包或现有 FDR 家族；GBPUSD 需先补 BOE adapter。

下一轮交互研究只做一份 outcome-blind 草案：固定
`momentum_252d_skip_21d × {CPI, IP} -> 63d` 与
`vol_ratio_21_126 × {CPI, IP} -> 21d` 四个双侧交互；训练折内 ECDF、统一 complete-date
mask、8 个检验（4 个正式 + 4 个 matched shadow）共用 BH 家族。完整规则见
`docs/STRUCTURED_EXTERNAL_INTERACTION_PREREGISTRATION_DRAFT_ZH.md`。在独立授权前不打开
收益标签，GSCPI 交互登记为 `deferred_missing_data`。

安全状态固定为：

```text
return_labels_opened=false
factor_outcome_evaluations_added=0
formal_net_returns_ready=false
trading_approval=false
```
