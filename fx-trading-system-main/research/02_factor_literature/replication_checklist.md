# Replication Checklist — Field Level

更新：2026-07-17。用于 **Carry / Momentum / Value / Liquidity RP / VRP**。  
图例：`Y`=精确复制需要；`E`=项目扩展可改；`N`=不需要。  
项目列：`have` / `partial` / `missing` / `na`。

---

## A. Carry（Lustig–Roussanov–Verdelhan HML_FX）

| 字段 | 频率 | 滞后/时点 | 需要 | 项目 | 缺失时 |
|---|---|---|---|---|---|
| spot mid | EOM | t 可交易收盘 | Y | partial (Duka) | 净收益不可信 |
| spot bid/ask | EOM | 与成交同侧 | Y (net) | partial | 只报毛收益 |
| 1M forward mid | EOM | t | Y | **missing** | **fail closed** |
| 1M forward bid/ask | EOM | t | Y (net) | **missing** | fail closed |
| 报价惯例 FCU per USD | — | 固定 | Y | have (需审计) | 符号错误 |
| 结算日 spot/forward | — | T+2 等 | Y (CIP 对齐) | partial | 与 swap 错配 |
| 币种宇宙 | 月 | 当时可交易 | Y | G9 only | extension |
| 六分位排序 | 月 | 按 f−s | Y | E→三分位 | extension |
| 组内等权 | 月 | — | Y | E | — |
| P1 做空 / P6 做多 | 月 | — | Y | have | — |
| DOL/HML 定义 | 月 | — | Y | have | — |
| 账户 swap 历史 | 日 | 隔夜 | E/实现 | **missing** | 不可宣称零售净 |
| 杠杆上限 | — | 账户 | 实现 | incomplete | 不可实现 |

**成本：** 原文 bid-ask；项目须 + financing。  
**2016–2025：** CIP 偏离常态 → 政策利率 carry ≠ forward carry。

---

## B. Momentum — Cross-sectional（Menkhoff et al. JFE 2012）

| 字段 | 频率 | 滞后/时点 | 需要 | 项目 | 缺失时 |
|---|---|---|---|---|---|
| 滞后超额收益 f 月 | 月 | t 末用 t−f:t | Y | partial | spot-only extension |
| formation f | — | {1,3,6,9,12} | Y | E 日度网格 | 计入 FDR |
| holding h | — | 主 h=1 | Y | E 21/63/… | 计入 FDR |
| 六分位 High−Low | 月 | 等权 | Y | E G9 分位 | extension |
| 1M forward 进 rx | 月 | — | Y (全文) | missing | spot mom extension |
| bid/ask 进出规则 | 月 | 文内 enter/exit | Y (net) | partial | 低估成本 |
| skip month | — | 原文无强制 | E | skip-21 账本 | 预注册 |
| 美元中性 | — | H−L | Y | have | — |

**成本：** 高换手；指示性价差下仍可能正，零售未证。  
**与 carry：** 低相关 → 可同组合但须独立注册。

---

## C. Momentum — Time-series（Moskowitz–Ooi–Pedersen）

| 字段 | 频率 | 滞后/时点 | 需要 | 项目 | 缺失时 |
|---|---|---|---|---|---|
| 资产自身超额收益 | 日/月 | 收盘后 | Y | partial | spot-only extension |
| lookback k（主 12m） | 月 | sign(r_{t−k:t}) | Y | E | FDR |
| hold h（主 1m） | 月 | 重叠 sleeve | Y | E | 资本守恒 |
| EWM vol COM=60d | 日 | σ_{t−1} 用于 t | Y | have | — |
| target vol / 1/σ 仓位 | 月 | — | Y | E + 杠杆帽 | 无帽不可实现 |
| 期货/远期合约链 | — | 展期 | Y | missing | swap 近似 extension |
| 多资产分散 | — | 58 工具 | N/E | FX only | extension |

---

## D. Value（Menkhoff et al. RFS）

| 字段 | 频率 | 滞后/时点 | 需要 | 项目 | 缺失时 |
|---|---|---|---|---|---|
| 实际汇率 q / REER | 季 | t 可获 | Y | partial **current vintage** | extension + 新前向 |
| Δ^(5y) q | 季 | q_t − q_{t−5y} | Y | partial | 样本长度 |
| 宏观 X（HBS, quality, NFA, gap） | 季 | 发布后 | E (净化) | missing/partial | 仅原始 REER |
| 期望代理 EWMA/VAR | 季 | φ=0.98 等 | E | — | 预注册 |
| 线性权重 w∝x−x̄ | 季 | 再平衡 | Y | E 月度 | extension |
| rank 组合 | 季 | — | E | E | — |
| FX 超额收益 | 季 | 含利差 | Y | forward missing | spot extension |
| as-published vintage | — | available_time | 严格 PIT | missing | strict_pit=false |

---

## E. Liquidity Risk Premia（Söderlind–Somogyi）

| 字段 | 频率 | 滞后/时点 | 需要 | 项目 | 缺失时 |
|---|---|---|---|---|---|
| 真实 1M forward 路径 | 日 | f_{t−22,t} | Y | **missing** | **fail closed** |
| r_i=(f−s)/22 | 日 | — | Y | missing | 禁止 spot 冒充 |
| bas bid-ask mid | 日 | — | Y | partial Duka | 来源迁移标注 |
| high ask / low bid | 日 | Corwin–Schultz | Y | partial | — |
| expanding z 252 | 日 | 禁止全样本 | Y | canary 可 | — |
| Δ22 c 对 Δ22 v 正交 | 日 | expanding | Y | canary 可 | — |
| β2, β4 滚动 252 | 日 | — | Y | canary 可 | — |
| 10 日均 beta | 日 | — | Y | canary 可 | — |
| **lag 22** 营业日 | 日 | 信号延迟 | Y | must | 前视否决 |
| 15 币种宇宙 | 日 | — | Y | G9 | extension |
| 每日三分位 | 日 | 等权 | Y | E 21d 持有 | extension |
| 交易成本 | 日 | 主表无 | 晋级 Y | missing | 未扣成本否决 |
| 溢价符号预注册 | — | 见笔记 | Y | — | 禁止翻向 |

---

## F. VRP / Risk Reversal（Della Corte–Ramadorai–Sarno）

| 字段 | 频率 | 滞后/时点 | 需要 | 项目 | 缺失时 |
|---|---|---|---|---|---|
| 1Y OTC smile 五点 | 月 | t 末 | Y | **missing** | **fail closed** |
| model-free IV | 月 | 积分 | Y | missing | fail closed |
| RV 滞后 1Y | 日→月 | t−252:t | Y | have | — |
| VRP=RV−IV (P−Q) | 月 | 符号冻结 | Y | missing | — |
| 10Δ RR | 月 | call−put IV | Y (RR) | missing | fail closed |
| 五分位等权 1M 持有 | 月 | VRP 多高/空低；RR 多低/空高 | Y | — | — |
| JP Morgan / 等价曲面 | — | — | Y | missing | fail closed |
| Cboe 30D IV | 日 | — | N | partial 3 ccy | **状态 only** |

---

## G. 跨主题否决（所有因子共用）

| 规则 | 说明 |
|---|---|
| midquote ≠ net | 无 bid/ask+融资不得晋级 |
| 政策利率 ≠ forward | 合成 F 仅压力测试 |
| reused-history | 2016–2025 已搜索 → 需冻结后新前向 |
| FDR 分母 | 新规格先注册再看收益 |
| 扩展另名 | G9、21d、阈值 gate、Cboe 代理均不得冒充原文 |

---

## H. 一页优先级（堵硬缺口）

1. 目标账户 2016–2025 **swap/rollover 或 1M forward points**（Carry + Liq RP + 完整 mom/value rx）  
2. 完整 G9 **bid/ask** 宇宙（所有净收益）  
3. 若做 VRP：OTC **1Y smile**（否则 fail closed）  
4. 若做严格 value：REER/CPI **as-published vintage**  
5. Dealer/CIP：**合同与负对照**，不占方向预算  
