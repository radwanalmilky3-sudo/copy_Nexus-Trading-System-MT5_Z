# 第二层结构化外部数据层交接说明

日期：2026-07-19。

第二层现在是一个 broker-neutral、outcome-blind 的结构化外部数据层，不是盈利策略。它的
职责是回答：某个价格决策时点，外部数据当时是否已经可用、来自哪个版本、是否过期，以及
事件控制是否已经实际发生。

## 当前交付

统一包位于 `outputs/structured_external_feature_package_20260719/`：

- `feature_values.csv`：3,653 个日度 UTC 决策键、5 个正式定义；
- `feature_lineage.csv`：18,265 行逐特征谱系；
- `event_component_lineage.csv`：10,996 行 Tokyo/ECB/WMR/SPF 组件谱系；
- `manifest.json`：子面板、源文件、目录、代码和输出 SHA-256；
- `REPORT_ZH.md`：覆盖和使用边界。

五个正式定义是：

```text
gscpi_risk_state_pit
us_cpi_12m_log_inflation
us_ip_6m_log_growth
benchmark_publication_state
phillyfed_spf_release_state
```

三个 regime 因子使用 preserved vintage 或 verified RTDSM；两个事件控制使用完整的官方
发布日期/服务日历。所有 ready 行都必须是 `verified_strict_pit`，所有 available time 都
必须不晚于 decision time。

## 真实覆盖边界

- CPI：3,653/3,653 ready；
- IP：3,630/3,653 ready；2025-12-02 至 2025-12-24 的 23 天超过 75 天上限而留空；
- GSCPI：1,273/3,653 ready；首个完整 ready 是 2022-07-08，早期不回填；
- Benchmark：3,652/3,653 ready；首个决策边界因过去 24 小时窗口在样本外而不可用；
- SPF：3,652/3,653 ready，40 个保守 available-time 脉冲；其中 32 个落在周日 00:00 UTC，
  当前包保留周日边界，不为工作日研究偷偷平移。

## 关键实现入口

```text
src/fx_system/structured_external_features.py
src/fx_system/structured_event_controls.py
src/fx_system/structured_external_package.py
scripts/build_structured_external_regime_panel.py
scripts/build_structured_external_event_panel.py
scripts/build_structured_external_feature_package.py
```

额外审计候选：`outputs/eurusd_central_bank_event_candidate_20260719/`。它从父央行日历中抽出
FED 81 行和 ECB 80 行严格有 UTC 发布时间的事件（共 161 行），排除 2 行 ECB date-only
事件。父日历仍 `complete=false`，BOE=0，因此该候选仅可作为 EURUSD 公告风险 blackout，未
加入当前五因子包、未进入任何 FDR 家族。下一批免费严格-PIT路线见
`docs/FREE_STRICT_PIT_NEXT_SOURCES_ROADMAP_ZH.md`。

Treasury TIC 的 `tressect` 也已完成严格 parser、schema/单位/月份覆盖校验和 86 次相邻
revision matrix，物化为 `treasury_tic_tressect_vintages` source view。它覆盖 87 个 release
vintage、43,326 行观测，允许作为低频 USD funding/foreign-demand 状态候选；不属于方向 alpha，
没有加入五因子组合包或任何收益检验。完整审计见 `docs/TREASURY_TIC_TRESSECT_AUDIT_ZH.md`。

测试覆盖严格 schema、版本选择、staleness、时间边界、组件 bitmask、未来篡改 canary、子面板
键/值/谱系对账和失败关闭。下一轮交互研究草案位于
`docs/STRUCTURED_EXTERNAL_INTERACTION_PREREGISTRATION_DRAFT_ZH.md`，当前仍未授权打开收益
标签。

## 接手后的顺序

1. 核对五因子包 manifest、源 manifest 和输出 SHA-256；
2. 冻结第一层价格目录和本预注册草案，不根据第一层表现更换两个价格锚点；
3. 先实现统一 complete-date mask、训练折 ECDF、nuisance event controls 和 8 假设 BH 家族；
   先明确工作日决策对周日 SPF 脉冲的处理，不得在结果后移动脉冲；
4. 完成 prefix、future-availability、OOS 篡改不变性测试后，才能单独授权一次收益标签打开；
5. GSCPI 交互保持 `deferred_missing_data`，除非市场历史延长到能满足 5 年训练 + 1 年 OOS；
6. 任何候选都必须经历成本/forward/新增历史确认，不能改写为交易批准。

安全状态固定为：

```text
return_labels_opened=false
factor_outcome_evaluations_added=0
formal_net_returns_ready=false
trading_approval=false
```
