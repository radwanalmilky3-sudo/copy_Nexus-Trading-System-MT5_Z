# 深度研读路径（6 周）

读者：可用最强模型精读与推导。  
原则：先建立否决权，再学机制；每课必须对照本项目 fail-closed 边界。  
笔记模板：`../notes/_NOTE_TEMPLATE.md`  
总索引：`../NOTES_INDEX_ZH.md` · 收口：`../STUDY_CLOSURE_ZH.md` · 缺口：`../notes/GAPS.md`  
PDF 根：`../_pdfs/`（打开前核首页标题 / `MISLABEL_LOG.md`）

---

## Week 1 — 验证与数据挖掘（否决权）

**目标：** 任何“显著因子”在完整试验次数下是否仍成立。

| 顺序 | 文献 | 笔记 | OA PDF（相对 `_pdfs/`） | 本项目对照 |
|---|---|---|---|---|
| 1.1 | Harvey–Liu–Zhu | `04_validation_methods/notes/harvey_liu_zhu_factor_zoo.md` | `_validation/harvey_liu_zhu_w20592.pdf` | 搜索账本、全部尝试披露 |
| 1.2 | Benjamini–Hochberg | `04/.../benjamini_hochberg_1995.md` | 见 04 catalog / `_validation/` | 每折 m=129 统一家族 |
| 1.3 | Stationary bootstrap + empirical p | `04/.../politis_romano_1994_stationary_bootstrap.md`；`phipson_smyth_2010_empirical_p.md` | 见 04 | B=20,000；`(k+1)/(B+1)` |
| 1.4 | Deflated Sharpe | `04/.../bailey_2014_deflated_sharpe.md` | `_validation/` 内 Bailey DSR | 完整 trial count |
| 1.5 | PBO / CSCV | `04/.../bailey_pbo_cscv.md` | 见 04 | 成本后组合验证 |
| 1.6 | Hansen SPA | `04/.../hansen_2005_spa.md` | 见 04 | 内部 SPA；勿盲信 arch |

**配套：** `04_validation_methods/METHODS_MAP.md`

**精读问题：**

1. 若只报告“入选的 2 个风险因子”而隐藏 643 次失败，推断错在哪？  
2. v4 方向因子 0 入选，是功效不足还是应接受空模型？  
3. 为何 reused 2016–2025 不能当 untouched holdout？

**产出检查：** 能讲清 FDR 分母、DSR 输入、PBO 含义。

---

## Week 2 — Carry、crash 与融资合同

| 顺序 | 文献 | 笔记 | OA PDF | 本项目对照 |
|---|---|---|---|---|
| 2.1 | Lustig–Roussanov–Verdelhan | `02_factor_literature/notes/lustig_rfs_2011.md` | `_nber/lustig_roussanov_verdelhan_common_risk_factors_w14082.pdf` | 无真实 forward → fail closed |
| 2.2 | Menkhoff et al. carry/vol | `02/.../menkhoff_jf_2012_carry.md` | 见 02 catalog OA / City | 风险门控事前冻结 |
| 2.3 | Brunnermeier–Nagel–Pedersen | `02/.../brunnermeier_nagel_pedersen.md` | `_nber/brunnermeier_nagel_pedersen_carry_crashes_w14473.pdf` | 不能事后选危机阈值 |
| 2.4 | Borio BIS basis | `06_broker_costs/notes/borio_bis_basis.md` | `_bis/` Borio 2016/2022 或 `work590`/`r_qt1609e` | 政策利率 ≠ 可交易 carry |
| 2.5 | Du–Tepper–Verdelhan | `02/.../du_tepper_verdelhan.md`；`06/.../du_tepper_verdelhan_cip.md` | `_nber/du_tepper_verdelhan_cip_deviations_w23170.pdf` | Qend 字段级合同 |
| 2.6 | Moreira–Muir | `02/.../moreira_muir.md` | `_nber/moreira_muir_volatility_managed_portfolios_w22208.pdf` | ≠ 项目 threshold gate |

**加码（同周可选）：**  
`koijen_moskowitz_pedersen_vrugt_carry_w19325.md` · `jurek_crash_neutral_currency_carry.md` · `burnside_peso_carry_w14054.md` · `CIP_CONTRACT_CHECKLIST.md`

**精读问题：**

1. 政策利率 / `F_hat` / 1M forward / 账户 swap 四层差在哪？  
2. vol-managed 是新方向还是仓位管理？  
3. 缺零售 swap 史时，哪些结论禁止写？

---

## Week 3 — Momentum、Value、联合证据

| 顺序 | 文献 | 笔记 | OA PDF | 本项目对照 |
|---|---|---|---|---|
| 3.1 | Menkhoff momentum | `02/.../menkhoff_jfe_2012_mom.md` | `_bis/work366.pdf` | 21/63/126/252、skip-21 在搜索账本 |
| 3.2 | Moskowitz TSMOM | `02/.../moskowitz_ooi_pedersen.md` | `_nber/moskowitz_oonoi_pedersen_time_series_momentum_w16348.pdf`（核首页） | sleeve 资本守恒 |
| 3.3 | Menkhoff value | `02/.../menkhoff_rfs_value.md` | 见 02 catalog OA | REER current-vintage 探索 only |
| 3.4 | Asness–Moskowitz–Pedersen | `02/.../asness_moskowitz_pedersen.md` | `_nber/asness_moskowitz_pedersen_value_momentum_w12022.pdf` 等 | 不得事后 agreement 逃 FDR |
| 3.5 | Ready / Ferraro | `02/.../ready_roussanov_ward.md`；`ferraro_rogoff_rossi.md` | 见 02 / `_nber/` commodity 相关 | Pink Sheet 美元内生性 |

**加码：** `lettau_maggiori_weber_dr_capm_w18844.md` · `chernov_dahlquist_lochstoer_anatomy_w32900.md`

**精读问题：**

1. 横截面动量与 TSMOM 的经济叙事差在哪里？  
2. REER current-vintage 如何污染历史回测？  
3. v4 为何这些方向均未晋级仍要保留在账本？

---

## Week 4 — 微观结构与定盘

| 顺序 | 文献 | 笔记 | OA PDF | 本项目对照 |
|---|---|---|---|---|
| 4.1 | Krohn–Mueller–Whelan | `03_microstructure_intraday/notes/krohn_mueller_whelan.md` | `_pdfs/_micro/` 或 03 catalog | FIX-W；成本后可转负 |
| 4.2 | Breedon–Ranaldo | `03/.../breedon_ranaldo.md` | `_micro/` SNB 等 | LOCAL-PAPER；1/6 sleeve=扩展 |
| 4.3 | Mancini–Ranaldo–Wrampelmeyer | `03/.../mancini_ranaldo_wrampelmeyer.md` | `_micro/` | 入场 spread q90；无未来平仓 spread |
| 4.4 | Melvin–Prins | `03/.../melvin_prins.md` | `_micro/` | 无 PIT 股票映射→只叫月末放大 |
| 4.5 | Andersen / Faust | `03/.../andersen_et_al_aer.md`；`faust_et_al.md` | `_micro/` / Fed IFDP | 无 consensus→禁止方向 surprise |
| 4.6 | WMR/ECB methodology | `03/.../lseg_wmr_methodology.md`；`01/.../wmr_ecb_tokyo_fix_comparison.md` | `_official/lseg_wmr_fx_methodology.pdf` | IANA/DST；5 秒 prevailing quote |

**配套：** `03_microstructure_intraday/INTRADAY_SOURCE_MAP.md` · `10/.../fx_microstructure_survey_map.md`

**精读问题：**

1. 为何 1h bar 不能验证 `:55` / WMR 五分钟窗？  
2. 流动性过滤用到未来信息，偏差方向是什么？  
3. Dukascopy 单一报价源限制了哪些“全市场深度”主张？

---

## Week 5 — 流动性风险、期权、低频状态、理论边界

| 顺序 | 文献 | 笔记 | OA PDF | 本项目对照 |
|---|---|---|---|---|
| 5.1 | Söderlind–Somogyi | `02/.../soderlind_somogyi_2024.md` | `_ssrn/` 或 02 catalog | 真 1M forward 硬依赖 |
| 5.2 | Della Corte VRP/RR | `02/.../della_corte_vrp.md` | 见 02 / City OA | Cboe 30D ≠ 1Y OTC VRP |
| 5.3 | Della Corte imbalance | `02/.../della_corte_imbalance.md` | 见 02 | 八币种资产负债表缺→不实现 |
| 5.4 | Correa–DeMarco dealer | `02/.../fang_ifdp_2019.md` | `_fed/correa_demarco_ifdp1262_dealer_leverage.pdf` | 2016–2025 负对照 |
| 5.5 | BIS 低频 / 数据集边界 | `05/.../bis_low_frequency_pit_bans.md`；`08_datasets_catalog/DATASETS.md` | `_bis/` GLI/LBS 相关 | 禁止当 G9 日方向 |
| 5.6 | Disconnect 理论 | `02/.../itskhoki_mukhin_disconnect_w23401.md` | `_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf` | 解释边界，非零售 alpha |

**精读问题：**

1. 用 spot 22 日收益代替 forward excess 时删掉了什么？  
2. 负 beta 溢价的交易方向为何必须事前冻结？  
3. 低频风险状态如何进注册表而不膨胀方向 FDR？

---

## Week 6 — 本项目契约串讲

**必读（仓库内，只读 docs + research）：**

1. `docs/LONG_HORIZON_FACTOR_RESEARCH_ZH.md` — v4 拒绝结论  
2. `docs/RESEARCH_EXECUTION_ROADMAP_2016_2025_ZH.md` — 双路线与 forward  
3. `docs/PROJECT_HANDOFF_SUMMARY_ZH.md` — WP0–WP9  
4. `docs/FX_FACTOR_LITERATURE_MAP_ZH.md` — 文献地图  
5. `research/notes/GAPS.md` — 硬阻塞  
6. `research/STUDY_CLOSURE_ZH.md` — 收口检查题  
7. `research/04_validation_methods/METHODS_MAP.md` — 方法→代码只读映射  
8. `research/06_broker_costs/CIP_CONTRACT_CHECKLIST.md` — 字段合同  

**必做对照题：**

1. 列出 3 个 `exact_possible` 与 5 个 `fail_closed_missing_data`。  
2. WP3 未完成时，WP7 为何不能出“历史净收益”？  
3. 设计 WP9 新章程：有限候选、机制、trial budget、新 forward——各一段。  
4. 走一遍 v4：m、q、B_min、实际 B、入选数、OOS 同号。  
5. 从 `MISLABEL_LOG.md` 举 3 个文件名与首页不一致的 PDF。  

**结业标准（自检）：**

- [ ] 能手写 carry / momentum / FIX-W 的收益定义  
- [ ] 能说明 CIP 字段清单  
- [ ] 能解释 DSR/PBO/SPA 各校正什么、不校正什么  
- [ ] 接受“空模型”为合法研究产出  
- [ ] 不把 mid 回测、Cboe 30D、CFTC 仓位误写成可交易方向 alpha  

---

## 使用方式

1. 每周先读表中**笔记**，再开 **OA PDF**（核首页）。  
2. 用最强模型时：粘贴笔记 §2 公式 + §6 复制清单，要求**挑错/核对**，不要“通俗解释”。  
3. 笔记与原文冲突：写入 `notes/ERRATA.md`，**不**改注册表搜收益。  
4. 与 `READING_STACK_ZH.md` 冲突时：以 **GAPS 硬阻塞 + 复制合同** 为准。  
