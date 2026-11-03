# Factor Literature Citation Graph

更新：2026-07-17（Wave2）。节点以 catalog slug 为准；边表示**思想/合同依赖**，非完整文献计量。

## 1. 总览（角色分层）

```text
[foundational premia]
  lustig_rfs_2011 ──HML_FX/DOL──► menkhoff_jf_2012_carry (VOL)
       │                              │
       │                              ▼
       ├────────────────────► brunnermeier_nagel_pedersen (crash)
       │                              │
       ▼                              ▼
  hassan_mano ──decompose──► (static XS carry vs FPP/dollar)
       │
  menkhoff_jfe_2012_mom ◄──parallel──► moskowitz_ooi_pedersen
       │                              │
       ▼                              ▼
  menkhoff_rfs_value ◄──joint── asness_moskowitz_pedersen
       │
       ▼
  della_corte_imbalance (external BS; fail closed)
  ready_roussanov_ward ──IMX──► lustig unconditional carry
  ferraro_rogoff_rossi ──daily oil──► (high-freq boundary)

[liquidity / options]
  soderlind_somogyi_2024 ──liq risk──► (carry explanation partial)
  della_corte_vrp ──VRP/RR──► (orthogonal-ish to carry/mom)

[position sizing / gates]
  moreira_muir ──own-factor 1/RV──► (needs lustig carry series)
  brunnermeier_nagel_pedersen ──funding/VIX──► project vol gate (extension)
  menkhoff_jf_2012_carry ──global FX VOL──► pricing (≠ Moreira gate)

[contracts / negative controls]
  du_tepper_verdelhan ──CIP──► borio_bis_2016_basis / borio_bis_2022_fxswap
       │
       └──constraints──► lustig_rfs_2011 implementability (post-2010)
  fang_ifdp_2019 (Correa–DeMarco) ──dealer BS──► negative_control 2016–2025
```

## 2. 主题内边（foundational → replication/critique → boundary）

### 2.1 Carry

| from | to | 关系 |
|---|---|---|
| Fama 1984 / UIP | lustig_rfs_2011 | 现象 → 风险因子结构 |
| lustig_rfs_2011 | menkhoff_jf_2012_carry | 波动风险定价 carry |
| lustig_rfs_2011 | brunnermeier_nagel_pedersen | 平均溢价 vs crash/skew |
| lustig_rfs_2011 | moreira_muir | carry 因子成为 vol-managed 输入 |
| lustig_rfs_2011 | du_tepper_verdelhan | 前危机 CIP≈成立假设被后危机削弱 |
| lustig_rfs_2011 | hassan_mano | 组合事实 → 三维协方差分解 |
| hassan_mano | lustig_rfs_2011 | 静态横截面 vs FPP/dollar 分离 |
| brunnermeier_nagel_pedersen | project gate | 融资压力门控动机（扩展） |
| ready_roussanov_ward | lustig_rfs_2011 | 贸易结构 subsume 无条件 carry |
| menkhoff_jf_2012_carry | soderlind_somogyi_2024 | vol vs liquidity 定价竞争 |

### 2.2 Momentum

| from | to | 关系 |
|---|---|---|
| Jegadeesh–Titman | menkhoff_jfe_2012_mom | 横截面组合方法迁到 FX |
| menkhoff_jfe_2012_mom | moskowitz_ooi_pedersen | XS vs TS；低相关但同属动量族 |
| both | asness_moskowitz_pedersen | 跨资产 value+mom |
| menkhoff_jfe_2012_mom | 成本/limits 文献 | 可实现性边界 |

### 2.3 Value

| from | to | 关系 |
|---|---|---|
| Asness et al. 5y value | menkhoff_rfs_value | 信号定义参照 + 宏观净化 |
| asness_moskowitz_pedersen | menkhoff_rfs_value | 统一 5y PPP vs REER 深化 |
| menkhoff_rfs_value | della_corte_imbalance | 外部头寸/估值 |
| menkhoff_rfs_value | project REER | current-vintage → extension_only |

### 2.4 Commodity & imbalance

| from | to | 关系 |
|---|---|---|
| Ready–Roussanov–Ward | Ferraro–Rogoff–Rossi | 商品–汇率：低频结构 vs 日度价格 |
| Ready–Roussanov–Ward | Hassan–Mano | 持久国别溢价微观基础 |
| Gabaix–Maggiori | della_corte_imbalance | 中介 + 外部失衡 |
| della_corte_imbalance | lustig / menkhoff value | 平行风险因子 |

### 2.5 Liquidity RP & VRP

| from | to | 关系 |
|---|---|---|
| Acharya–Pedersen | soderlind_somogyi_2024 | 流动性 beta 定价 |
| Mancini–Ranaldo–Wrampelmeyer | soderlind_somogyi_2024 | FX 流动性测度 |
| Britten-Jones–Neuberger | della_corte_vrp | model-free IV |
| della_corte_vrp | Cboe 30D IV | **非等价**；状态代理 only |

### 2.6 CIP / Dealer

| from | to | 关系 |
|---|---|---|
| du_tepper_verdelhan | borio BIS notes（06） | 机制与统计 |
| du_tepper_verdelhan | 一切 forward excess | 数据合同硬前置 |
| He–Krishnamurthy / Adrian et al. | fang_ifdp_2019 (Correa–DeMarco) | 中介 AP |
| fang_ifdp_2019 | 2016–2025 research | 衰减 → 负对照 |

## 3. 对本项目的“边约束”（只读结论）

1. **Carry 精确复制**依赖 lustig 公式 **且** 不被 du CIP 合同否决。  
2. **Vol gate ≠ Moreira–Muir ≠ Menkhoff VOL 定价**：门控动机连 BNP；1/RV 连 own-factor；VOL 是横截面定价因子。  
3. **Hassan–Mano**：静态 XS carry 与 FPP/dollar trade **分注册**。  
4. **Momentum 两条线**（XS Menkhoff / TS Moskowitz）必须分注册，合并时进同一 FDR 族要预声明。  
5. **Value**：Asness 5y PPP 与 Menkhoff REER 分信号；BIS REER 默认 extension + 新前向。  
6. **IMB / VRP / liq RP**：宏观外部账户或 smile/forward 缺失时 fail closed。  
7. **Commodity**：IMX 低频 vs 油价日度 — 不同 FDR 族；日度默认 exploratory。  
8. **Dealer BS** 只连负对照节点，不连 alpha 节点。

## 4. 深读优先级（若继续）

1. ~~menkhoff_jf_2012_carry~~ ✓  
2. ~~hassan_mano~~ ✓  
3. ~~asness_moskowitz_pedersen~~ ✓  
4. ~~della_corte_imbalance~~ ✓  
5. ~~ready_roussanov_ward / ferraro_rogoff_rossi~~ ✓  
6. 下一波：后样本衰减复制、成本后 net、Engel 1996 UIP 综述（10/）
