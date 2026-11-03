# 深度阅读栈（READING STACK）

更新日期：2026-07-17（研读收口对齐 NOTES_INDEX + 已验证 PDF）  
读者：可用最强模型精读；不降维。  
原则：**先否决权，再机制；先合同，再溢价；综述地图 → 单篇公式 → 成本 → 验证。**

合法 PDF 根目录：`research/_pdfs/`（清理后 **341** 文件；历史 manifest 见 `DOWNLOAD_MANIFEST.csv`；策略见 `_PURGE_SUMMARY_ZH.md` / `_PURGE2_EF_SUMMARY_ZH.md`）。  
**打开 PDF 前核对首页标题**——见 `_pdfs/MISLABEL_LOG.md`。  
总索引：`../NOTES_INDEX_ZH.md` · 收口：`../STUDY_CLOSURE_ZH.md` · 六周：`../09_deep_study_path/DEEP_STUDY_PATH_ZH.md`

---

## 0. 总顺序（约 10–14 个深读单元）

```text
[否决权] 04 验证方法
    → [地图] 10 survey / handbook
    → [合同] 06 成本/CIP + 01 基础
    → [慢周期] 02 因子主链
    → [日内] 03 微观结构
    → [数据边界] 05/08
    → [路径] 09 六周计划对齐
```

---

## 1. 否决权（必须先于任何“显著因子”）

| 秩 | 读什么 | 笔记 | PDF / 源 |
|---|---|---|---|
| 1 | Harvey–Liu–Zhu factor zoo | `04_validation_methods/notes/harvey_liu_zhu_factor_zoo.md` | `_pdfs/_validation/harvey_liu_zhu_w20592.pdf` |
| 2 | BH / BY FDR | `04/.../benjamini_hochberg_1995.md`；`benjamini_yekutieli_2001.md` | 04 catalog / `_validation/` |
| 3 | Deflated Sharpe | `04/.../bailey_2014_deflated_sharpe.md` | `_validation/` Bailey DSR |
| 4 | PBO / CSCV | `04/.../bailey_pbo_cscv.md` | 见 04 |
| 5 | Hansen SPA + White RC | `04/.../hansen_2005_spa.md`；`white_2000_reality_check.md` | **勿盲信 arch SPA** |
| 6 | Stationary bootstrap + empirical p | `04/.../politis_romano_1994_*.md`；`phipson_smyth_2010_*.md` | 见 04 |

**产出检查：** v4 `m=129,q=0.10`、完整试验数 N、成本不全时只能 research diagnostics。

---

## 2. 综述地图（10）

| 秩 | 读什么 | 笔记 | PDF |
|---|---|---|---|
| 7 | Burnside ARFE carry+mom 解释谱系 | `10_surveys_handbooks/notes/burnside_arfe_2011.md` | `_pdfs/burnside_arfe_survey.pdf`（w16942）✓ |
| 8 | Burnside handbook carry 与风险 | `10/.../burnside_handbook_carry_risk.md` | `_pdfs/burnside_carry_risk.pdf`（w17278）✓ |
| 9 | Burnside–Graveline asset market view **批判** | `10/.../burnside_graveline_asset_market_view.md` | `_pdfs/lustig_verdelhan_sdf_chapter.pdf`（**误标=w18646**） |
| 10 | Hassan–Zhang currency risk | `10/.../hassan_zhang_economics_currency_risk_w27847.md` | 核首页；勿与 disconnect w23401 混淆 |
| 11 | BIS Triennial 2022 结构 only | `10/.../bis_triennial_2022_fx.md` | `_bis/rpfx22_fx.pdf` + annex |
| 12 | 微观结构综述地图 | `10/.../fx_microstructure_survey_map.md` | 链 03 + WMR |

书目：`10/.../TEXTBOOKS_AND_SURVEYS.md`

---

## 3. 成本与 CIP 合同

| 秩 | 读什么 | 笔记 | PDF |
|---|---|---|---|
| 13 | Borio BIS basis / FX swaps | `06_broker_costs/notes/borio_bis_basis.md` | `_bis/` Borio / work590 等 |
| 14 | Du–Tepper–Verdelhan CIP | `06/.../du_tepper_verdelhan_cip.md`；`02/.../du_tepper_verdelhan.md` | `_nber/du_tepper_verdelhan_cip_deviations_w23170.pdf` |
| 15 | Avdjiev dollar–CIP 三角 | `02/.../avdjiev_du_koch_shin_cip_dollar.md`；`06/.../avdjiev_cip_dollar_contract.md` | **正典** `_bis/work592.pdf` 一类；**勿用** 误标 `avdjiev_*_w24555` |
| 16 | OANDA financing 边界 | `06/.../oanda_financing_docs.md` | `_html_snapshots/oanda_*` |
| 17 | CIP 字段清单 | `06_broker_costs/CIP_CONTRACT_CHECKLIST.md` | — |
| 18 | swap/forward 来源 | `06_broker_costs/SWAP_FORWARD_SOURCES.md` | — |

---

## 4. 慢周期因子主链（02）

| 秩 | 读什么 | 笔记 | PDF |
|---|---|---|---|
| 19 | Lustig–Roussanov–Verdelhan HML_FX | `02/.../lustig_rfs_2011.md` | `_nber/lustig_roussanov_verdelhan_common_risk_factors_w14082.pdf` |
| 20 | Brunnermeier–Nagel–Pedersen crash | `02/.../brunnermeier_nagel_pedersen.md` | `_nber/brunnermeier_nagel_pedersen_carry_crashes_w14473.pdf` |
| 21 | Menkhoff carry/vol | `02/.../menkhoff_jf_2012_carry.md` | 见 02 catalog OA |
| 22 | Menkhoff momentum | `02/.../menkhoff_jfe_2012_mom.md` | `_bis/work366.pdf` |
| 23 | Moskowitz TSMOM | `02/.../moskowitz_ooi_pedersen.md` | `_nber/moskowitz_oonoi_pedersen_time_series_momentum_w16348.pdf`（核首页） |
| 24 | Menkhoff value | `02/.../menkhoff_rfs_value.md` | 见 02 OA |
| 25 | Asness VME | `02/.../asness_moskowitz_pedersen.md` | `_nber/asness_moskowitz_pedersen_value_momentum_w12022.pdf` |
| 26 | Moreira–Muir vol-managed | `02/.../moreira_muir.md` | `_nber/moreira_muir_volatility_managed_portfolios_w22208.pdf` |
| 27 | Koijen Carry | `02/.../koijen_moskowitz_pedersen_vrugt_carry_w19325.md` | `_nber/koijen_moskowitz_pedersen_vrugt_carry_w19325.pdf` |
| 28 | LSV term structure | `02/.../lustig_stathopoulos_verdelhan_term_structure_w19623.md` | `_nber/lustig_stathopoulos_verdelhan_term_structure_carry_risk_premia_w19623.pdf` |
| 29 | Jurek crash-neutral | `02/.../jurek_crash_neutral_currency_carry.md` | `_ssrn/jurek_*`（**非** 误标 `jurek_crash_w15026`） |
| 30 | Söderlind–Somogyi liquidity RP | `02/.../soderlind_somogyi_2024.md` | `_ssrn/` 或 02 |
| 31 | Della Corte VRP/RR | `02/.../della_corte_vrp.md` | 见 02 |
| 32 | Della Corte imbalance | `02/.../della_corte_imbalance.md` | 见 02 |
| 33 | Correa–DeMarco dealer 负对照 | `02/.../fang_ifdp_2019.md` | `_fed/correa_demarco_ifdp1262_dealer_leverage.pdf` |
| 34 | Itskhoki–Mukhin disconnect | `02/.../itskhoki_mukhin_disconnect_w23401.md` | `_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf` |
| 35 | Chernov anatomy | `02/.../chernov_dahlquist_lochstoer_anatomy_w32900.md` | `_nber/w32900.pdf` |
| 36 | Lettau–Maggiori–Weber DR-CAPM | `02/.../lettau_maggiori_weber_dr_capm_w18844.md` | `_nber/lettau_maggiori_weber_conditional_currency_premia_w18844.pdf` |

引用：`02_factor_literature/CITATION_GRAPH.md`  
复制：`02_factor_literature/replication_checklist.md`  
全表：`NOTES_INDEX_ZH.md` §02

---

## 5. 微观结构与定盘（03）

| 秩 | 读什么 | 笔记 | PDF |
|---|---|---|---|
| 37 | 地图 | `10/.../fx_microstructure_survey_map.md` | — |
| 38 | Krohn fix | `03/.../krohn_mueller_whelan.md` | `_micro/` |
| 39 | Breedon–Ranaldo | `03/.../breedon_ranaldo.md` | `_micro/` |
| 40 | Melvin–Prins | `03/.../melvin_prins.md` | `_micro/` |
| 41 | Mancini 流动性 | `03/.../mancini_ranaldo_wrampelmeyer.md` | `_micro/` |
| 42 | Andersen / Faust | `03/.../andersen_et_al_aer.md`；`faust_et_al.md` | `_micro/` |
| 43 | Evans–Lyons OF 机制 only | `03/.../evans_lyons.md`；`10/.../evans_lyons_order_flow_bis_classic.md` | 无授权 OF |
| 44 | WMR methodology | `03/.../lseg_wmr_methodology.md` | `_official/lseg_wmr_fx_methodology.pdf` |

总图：`03_microstructure_intraday/INTRADAY_SOURCE_MAP.md`

---

## 6. 基础与数据合同

| 秩 | 读什么 | 路径 |
|---|---|---|
| 45 | 执行/报价/settlement/定盘 | `01_foundations/notes/*.md`（5 篇） |
| 46 | PIT / vintage | `05_data_contracts/PIT_AND_VINTAGE_GUIDE.md` + 3 笔记 |
| 47 | 数据集边界 | `08_datasets_catalog/DATASETS.md` + 9 笔记 |
| 48 | 缺口活文档 | `notes/GAPS.md` |
| 49 | 六周路径 | `09_deep_study_path/DEEP_STUDY_PATH_ZH.md` |
| 50 | 收口检查题 | `STUDY_CLOSURE_ZH.md` |

---

## 7. PDF 误标速查（阅读栈专用）

| 路径 | 实际内容 |
|---|---|
| `_pdfs/burnside_arfe_survey.pdf` | BER w16942 ARFE survey ✓ |
| `_pdfs/burnside_carry_risk.pdf` | Burnside w17278 handbook ✓ |
| `_pdfs/lustig_verdelhan_sdf_chapter.pdf` | **Burnside–Graveline w18646** |
| `_nber/avdjiev_*_w24555.pdf` | **Kalemli debt overhang**（CIP 用 BIS work592） |
| `_nber/itskhoki_mukhin_*_w27847.pdf` | **Hassan–Zhang**（disconnect 用 **w23401**） |
| `_nber/jurek_crash_w15026.pdf` | **非 Jurek**（用 `_ssrn/jurek_*`） |
| 短名 `burnside_carry_w13918/w15212` 等 | 错文 — 强制首页校验 |
| `_bis/work331.pdf` | **非** currency carry 政策文 |

全表：`_pdfs/MISLABEL_LOG.md`

---

## 8. 硬规则（读完仍须遵守）

1. midquote / 学术 bid-ask premium ≠ 零售 + financing 净收益。  
2. 无真实 forward/swap → carry / CIP / 部分 liquidity RP **fail closed**。  
3. Triennial / GLI / LBS → 结构或发布后状态，**非** G9 日方向。  
4. CFTC ≠ signed order flow；Cboe 30D ≠ 1Y OTC VRP。  
5. 2016–2025 已被多轮搜索 → **reused-history**，非 untouched holdout。  
6. SPA/DSR/PBO 的正式解释需要成本调整收益与完整试验数。  
7. 新候选只进 WP9 章程，不因“读了很多”扩 FDR 分母。

---

## 9. 与 09 六周路径的关系

本栈是**资料库索引序**；`09_deep_study_path/DEEP_STUDY_PATH_ZH.md` 是**教学周历序**（已填笔记/PDF 列）。  
两者一致：Week1 验证 → Week2 carry/CIP → Week3 mom/value → Week4 微观 → Week5 流动性/期权/低频 → Week6 项目契约。  
冲突时：以 **GAPS 硬阻塞 + 复制合同 + STUDY_CLOSURE 检查题** 为准。
