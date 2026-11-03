# 研读收口（深度笔记 × 索引）

更新日期：2026-07-17  
目的：在 **341 相关 OA PDF**（已清 bulk + E/F）与 **87 主题深度笔记** 已落盘的前提下，给出可执行的研读入口与边界，而不是再堆文件。

---

## 1. 一页结论

| 维度 | 状态 |
|---|---|
| 资料体量 | `_pdfs/` **341** PDF · **~372M**（bulk 删 7973 + E/F 删 77；manifest 历史 9480 行） |
| 深度笔记 | **87** 主题 L3–L5 笔记（见 [`NOTES_INDEX_ZH.md`](./NOTES_INDEX_ZH.md)） |
| 研读路径 | 六周周历 + 阅读栈两套序已对齐 |
| 项目研究结论 | **仍无批准交易因子**；v4 方向 0 入选 |
| 最大硬阻塞 | G1 账户 swap 史 · G2 可交易 forward · G3 全宇宙 Dukascopy · 成本 incomplete |

**收口原则：** 读完笔记 ≠ 可以交易；只能把不确定性变成可审计的 fail-closed 结论。

---

## 2. 从哪里开始（选一条）

### 0. 你是 Agent？

打开：[`AGENTS.md`](./AGENTS.md) → [`agent/routes.json`](./agent/routes.json)  
（意图路由 + 硬规则；**不要**整库加载 PDF。）

### A. 六周精读（推荐，机制依赖序）

打开：[`09_deep_study_path/DEEP_STUDY_PATH_ZH.md`](./09_deep_study_path/DEEP_STUDY_PATH_ZH.md)

```text
Week1 验证/否决权 → Week2 Carry/CIP → Week3 Mom/Value
→ Week4 微观定盘 → Week5 流动性/期权/低频 → Week6 项目契约
```

### B. 资料库索引序（快速定位）

打开：[`notes/READING_STACK_ZH.md`](./notes/READING_STACK_ZH.md)

```text
04 验证 → 10 综述 → 06 成本 → 02 因子 → 03 微观 → 05/08 数据
```

### C. 只查某一篇

打开：[`NOTES_INDEX_ZH.md`](./NOTES_INDEX_ZH.md) 或检索 [`agent/catalog.json`](./agent/catalog.json)  
→ 笔记 → `_pdfs/`（核首页标题）

---

## 3. 与本项目的映射（读任何因子前）

| 问题 | 答案位置 |
|---|---|
| 为何 v4 拒绝方向因子？ | `docs/LONG_HORIZON_FACTOR_RESEARCH_ZH.md`（仓库只读） |
| 文献→项目边界？ | `docs/FX_FACTOR_LITERATURE_MAP_ZH.md` |
| 复制字段清单？ | `02_factor_literature/replication_checklist.md` |
| 验证方法→代码？ | `04_validation_methods/METHODS_MAP.md` |
| CIP/swap 缺什么？ | `06_broker_costs/CIP_CONTRACT_CHECKLIST.md` + `SWAP_FORWARD_SOURCES.md` |
| 仍缺什么硬数据？ | `notes/GAPS.md`（G/C/V/R） |
| PDF 文件名可信吗？ | **否** → `_pdfs/MISLABEL_LOG.md` |

---

## 4. 核心笔记 × 已验证 OA PDF（优先深读）

| 主题 | 笔记 | OA PDF（相对 `_pdfs/`） |
|---|---|---|
| Factor zoo | `04/.../harvey_liu_zhu_factor_zoo.md` | `_validation/harvey_liu_zhu_w20592.pdf` |
| HML_FX | `02/.../lustig_rfs_2011.md` | `_nber/lustig_roussanov_verdelhan_common_risk_factors_w14082.pdf` |
| Carry crash | `02/.../brunnermeier_nagel_pedersen.md` | `_nber/brunnermeier_nagel_pedersen_carry_crashes_w14473.pdf` |
| Vol-managed | `02/.../moreira_muir.md` | `_nber/moreira_muir_volatility_managed_portfolios_w22208.pdf` |
| CIP | `02/.../du_tepper_verdelhan.md` | `_nber/du_tepper_verdelhan_cip_deviations_w23170.pdf` |
| Disconnect | `02/.../itskhoki_mukhin_disconnect_w23401.md` | `_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf` |
| Carry term structure | `02/.../lustig_stathopoulos_verdelhan_term_structure_w19623.md` | `_nber/lustig_stathopoulos_verdelhan_term_structure_carry_risk_premia_w19623.pdf` |
| Koijen Carry | `02/.../koijen_moskowitz_pedersen_vrugt_carry_w19325.md` | `_nber/koijen_moskowitz_pedersen_vrugt_carry_w19325.pdf` |
| DR-CAPM | `02/.../lettau_maggiori_weber_dr_capm_w18844.md` | `_nber/lettau_maggiori_weber_conditional_currency_premia_w18844.pdf` |
| Anatomy | `02/.../chernov_dahlquist_lochstoer_anatomy_w32900.md` | `_nber/w32900.pdf` |
| TSMOM | `02/.../moskowitz_ooi_pedersen.md` | `_nber/moskowitz_oonoi_pedersen_time_series_momentum_w16348.pdf`（核首页） |
| Currency mom | `02/.../menkhoff_jfe_2012_mom.md` | `_bis/work366.pdf` |
| Dealer 负对照 | `02/.../fang_ifdp_2019.md` | `_fed/correa_demarco_ifdp1262_dealer_leverage.pdf` |
| WMR | `03/.../lseg_wmr_methodology.md` | `_official/lseg_wmr_fx_methodology.pdf` |

完整表：`NOTES_INDEX_ZH.md` + 各目录 `CATALOG.md`。

---

## 5. 读完应能回答的检查题（收口标准）

1. **否决权：** v4 的 m、q、B_min、实际 B、入选数、OOS 同号各是多少？完整试验数 N 为何不能只算 finalists？  
2. **Carry 合同：** 政策利率 / `F_hat` / 可交易 1M forward / 账户 swap 四层差在哪里？缺哪一层时哪些结论禁止写？  
3. **验证：** DSR、PBO、SPA 各校正什么、**不**校正什么？为何 arch SPA 不能直接当正式 studentized SPA？  
4. **微观：** 为何 1h bar 不能验证 FIX-W / LOCAL 5 秒边界？spread q90 为何不能用未来平仓 spread？  
5. **项目：** 列出 3 个 `exact_possible` 与 5 个 `fail_closed_missing_data`；WP3 未完成时 WP7 为何不能出历史净收益？  
6. **卫生：** 举 3 个文件名与首页标题不一致的 PDF（见 MISLABEL_LOG）。

---

## 6. 明确不做什么（收口边界）

- 不因“读了很多论文”扩注册表搜收益  
- 不把 mid / Yahoo / 合成 carry 写成可实现 alpha  
- 不把 Cboe 30D IV 当 Della Corte 1Y VRP  
- 不把 CFTC 当 signed order flow  
- 不把 2016–2025 重标为 untouched holdout  
- 新候选 → 仅 WP9 新章程 + trial budget + 冻结后新 forward  

---

## 7. 建议下一动作（研究，非交易）

1. **研读：** 按 Week1–2 精读 04+02 carry/CIP 链（笔记 + 已验证 PDF）。  
2. **合同：** 对照 `GAPS.md` G1/G2/C1–C4，推动 broker swap/forward 数据请求（仓库外/WP3）。  
3. **代码只读：** 用 `METHODS_MAP.md` 对照项目 FDR/DSR/PBO/SPA 入口，不改代码除非单独立项。  
4. **笔记纠错：** 发现笔记与 PDF 冲突 → `notes/ERRATA.md`（可新建），不改注册表。

---

## 8. 文件清单（本收口新增/对齐）

| 文件 | 角色 |
|---|---|
| `NOTES_INDEX_ZH.md` | 87 笔记总表 |
| `STUDY_CLOSURE_ZH.md` | 本文件 |
| `09_deep_study_path/DEEP_STUDY_PATH_ZH.md` | 六周路径 + 笔记/PDF 列 |
| `notes/READING_STACK_ZH.md` | 索引序 + 误标 + Wave3/4 补链 |
| `INDEX.md` | 入口状态 |
