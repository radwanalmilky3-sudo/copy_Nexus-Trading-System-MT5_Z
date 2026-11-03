# 资料缺口（活文档）

更新日期：2026-07-17  
规则：只记**阻塞精确复制或正式净收益**的缺口；随收集更新。

## 硬阻塞（正式结论）

| ID | 缺口 | 影响 | 状态 |
|---|---|---|---|
| G1 | 目标账户 2016–2025 行级 swap/rollover | 慢周期净收益 fail closed | open |
| G2 | 同口径可交易 1M/1W forward points（bid/ask） | carry / CIP / liquidity RP 精确复制 | open |
| G3 | 完整 Dukascopy 14 品种 + 原始 manifest | G0 全宇宙 | 项目侧进行中；research 不存行情 |
| G4 | 历史 MMS/Bloomberg consensus | 宏观 surprise 方向 | 通常不可免费；open |
| G5 | 外部数据 as-published vintage 全链 | strict PIT | 部分有（RTDSM/GSCPI）；其余 open |

## 精确复制阻塞（可探索/扩展）

| ID | 缺口 | 相关文献 | 状态 |
|---|---|---|---|
| R1 | 15 币种 + 日度 1M forward（Söderlind） | liquidity RP | open |
| R2 | 一年期 OTC option smile 全截面 | Della Corte VRP/RR | open |
| R3 | 八币种外部资产负债表同口径 | Della Corte imbalance | open |
| R4 | 签名订单流 | Evans–Lyons | 无授权；open |

## 成本 / CIP 合同缺口（2026-07-17 增补）

| ID | 缺口 | 影响 | 状态 |
|---|---|---|---|
| C1 | `broker_legal_entity` 未确认 | `audit_cost_coverage` 无法 `historical_market_*` | open；见 `examples/cost_contract/broker_swap_forward_request.json` |
| C2 | forward 结算日/maturity 日历字段未入库 | Du–Tepper–Verdelhan `QendW`/`QendM` 不能严格构造 | open；清单见 `06_broker_costs/CIP_CONTRACT_CHECKLIST.md` |
| C3 | 同 tenor 历史 OIS（非 policy proxy） | CIP basis 与严格 carry | open；示例为 `unknown_unverified` |
| C4 | OANDA 公开 financing 仅约 1y 且非账户条款 | 不能外推 2016–2025 net | open；脚本可归档公开表 |
| C5 | mid-only / 合成 `F_hat` 误用风险 | 伪 carry 复制 | 流程否决已写；数据层仍可能误标 → 靠 quote_quality 门 |
| C6 | 零售 tom-next 与银行间 1M basis 期限错位 | 机制对照不等于成本替代 | 记录为解释边界 |

**编码真理：** `cost_incomplete` → 无正式净 PnL；政策利率/`F_hat` ≠ 可交易 forward。

## 验证方法接线缺口（2026-07-17 增补）

| ID | 缺口 | 影响 | 状态 |
|---|---|---|---|
| V1 | 正式 runner 未调用 `hansen_spa_test` | `spa_executed=False`；仅有输入校验 | open；核心已在 `hansen_spa.py` |
| V2 | arch SPA 易被误用为正式 studentized SPA | 假 studentize / p=0 | 文档否决；TOOLS_MAP 已记 |
| V3 | 完整试验数 N 与历史搜索账本对齐 | DSR/PBO 分母；含既往 ~3,312 次暴露 | 流程要求有；自动化合并仍依赖 registry 纪律 |
| V4 | MCS / Romano–Wolf 未实现 | 仅能用 BH+SPA 诊断 | 可接受延迟；非硬阻塞净收益 |
| V5 | BY 分辨率 vs B | m 大时 BY 第一阈值可能仍难及 | 敏感性；主门槛 BH + B=20000 |
| V6 | 净收益矩阵在成本完备前的解释 | 统计显著 ≠ 可交易 | 政策：research diagnostics only |

**编码真理：** v4 `m=129,q=0.10` 需 `B≥1289`（用 20000）；DSR/PBO 的 trial count 含全部搜索史；SPA 只校正传入列。

## 微观结构 / PIT 缺口（2026-07-17 Agent-Micro 增补）

| ID | 缺口 | 影响 | 状态 |
|---|---|---|---|
| G6 | CFTC TFF/COT 逐期 **actual release timestamp** 全样本证据（非 tentative） | 拥挤因子不能 strict 晋级；60d lag 仅为保守近似 | open |
| G7 | CFTC Historical Compressed 的 **as-published 字节链**（抗事后重分类） | `value_vintage_quality` 停留在 current revised archive | open |
| G8 | LSEG WMR **service-alteration 历史 PDF 自动反解/二次校对**（现为人工转录） | 半日/停服日 FIX-W 事件日历操作风险 | open |
| G9 | ASIA-LDN 所需金融中心 **节假日与半日市** 权威输入 | formal ASIA-LDN 敏感性未闭合 | open |
| G10 | 授权 **EBS/全市场** 报价或成交（相对 Dukascopy 零售） | Breedon/Krohn/Mancini 精确微观复制与成本外推 | open |
| G11 | Melvin–Prins 通道所需 **PIT 多市场权益收益 + 对冲映射** | 月末项只能做放大交互，不能称对冲因果复制 | open |
| G12 | BIS GLI/LBS/OTC 历次发布的 **as-published 响应链** | 低频状态不能标 strict_pit_eligible | open |

## 因子文献复制缺口（2026-07-17 Wave2 增补）

| ID | 缺口 | 相关文献 | 状态 |
|---|---|---|---|
| R3 | 多国 NFA/GDP + 负债本币份额（ldc）PIT 全链 | della_corte_imbalance | open（原 R3 保留并细化） |
| R5 | 全球日度全宇宙 \|Δs\| 构 Menkhoff σ^FX + 递归 AR(1) 规则 | menkhoff_jf_2012_carry | open；G9 仅 extension |
| R6 | Hassan–Mano 信息集（币种均值先验）预注册 + 长面板 forward | hassan_mano | open |
| R7 | UN Comtrade 初级/制成品净贸易 4y 均值 + 发布时滞 | ready_roussanov_ward IMX | open |
| R8 | 日度油价与 FX bar **时区对齐**合同（同期 vs 滞后） | ferraro_rogoff_rossi | open；月度作负对照 |
| R9 | Asness 5y PPP value 所需双边 CPI **vintage**（非 final only） | asness_moskowitz_pedersen | open；与 REER vintage 并列 |
| R10 | 目录误 DOI/误标 PDF 清理（hassan 旧 DOI；`lustig_verdelhan_sdf_chapter.pdf`=w18646） | 10 surveys / 02 catalog | open 流程 |
| R11 | **Itskhoki–Mukhin exchange-rate disconnect 正确 OA PDF** | 精读 disconnect 原文 | **closed（PDF+L3）**：`_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf` + `02_factor_literature/notes/itskhoki_mukhin_disconnect_w23401.md`。误标 `..._w27847.pdf` 仍为 Hassan–Zhang，勿混用 |
| R12 | **Avdjiev CIP** 勿用 `_nber/avdjiev_*_w24555.pdf`（实为 Kalemli debt overhang）；正典 `_bis/...wp592...` | CIP 合同引用 | 已记笔记；文件名治理 open |
| R13 | 多份 `_nber/burnside_carry_w13918/w15212` 等短名 **错文**；打开首页校验强制 | 引用卫生 | open 流程 |
| R14 | **`_bis/work331.pdf` 非 carry**（Vickers 竞争政策）；BIS carry 政策文用 `bis_pap81_currency_carry_latam.pdf`。**`_ecb/ecb_wp964_*carry*crashes*.pdf` 误标**（实为 Kátay 工资保险） | 引用卫生 | **closed（记录）**：Wave4 已绕开并 deep_note 正典 PDF |
| R15 | Jurek crash-neutral / Huang PUW 所需 **OTC FX 期权（10δ）+ 主权 CDS** | 精确 crash-neutral 与 PUW 因子 | open；与 R2 期权缺口并列 |
| R16 | Breedon–Rime–Vitale 所需 **EBS 签名订单流 + Reuters 个体调查** | forward bias 订单流分解 | open；与 R4 并列（授权微观） |
| R17 | LSV 期限结构 / ECB curvy 所需 **G10 国债零息或 NS 全曲线** | 长端 carry 与曲率排序 | open |

## 已在项目 docs、待 research 落盘深度笔记

见各子目录 CATALOG；04/06/07 主验证与成本批已落盘（2026-07-17）。03 微观结构 + 05 PIT 合同 + 08 数据集总表本轮已落盘。02 Wave2–3 主表已 deep_noted；Wave4 新增 Itskhoki–Mukhin w23401、Jurek、LSV term structure、Huang–MacDonald、Breedon–Rime–Vitale、BIS pap81、ECB 2149/2731/1968、Jylhä 等 L3；Borio/Avdjiev 合同在 06。
