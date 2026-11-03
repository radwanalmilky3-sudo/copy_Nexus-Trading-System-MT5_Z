# [Huang & MacDonald 2013] Currency Carry Trades, Position-Unwinding Risk, and Sovereign Credit Premia

- 深度层级: L3
- 引用链角色: replication / critique（期权隐含平仓风险 + 主权 CDS 定价 carry）
- DOI/URL: MPRA 51207 https://mpra.ub.uni-muenchen.de/51207/ ；SSRN 2287287
- 开放获取: `_pdfs/_ssrn/huang_macdonald_position_unwinding_risk_mpra51207.pdf`（及 ssrn2287287_mpra 镜像）
- 本项目映射: carry 风险因子分解——**主权信用 + 平仓似然**；非默认方向信号
- 复制状态: fail_closed_missing_data（FX 期权截面 + 主权 CDS 全宇宙）
- 公式置信度: medium–high（MPRA 长稿；期权公式页 OCR 密，主定义清晰）
- published premium vs implementable: 资产定价 R² 高 ≠ 可交易；CDS/期权信号有点差与主权 dual-trigger
- 2016–2025 外推: 中；欧债危机后主权–FX 联动结构变化

## 1. 经济机制

在 LRV 式 forward-discount 组合上，高息货币不仅暴露于全球波动，还暴露于更高的**仓位平仓（position-unwinding）风险**——用扩展 Garman–Kohlhagen / 矩调整期权模型得到的风险中性尾部概率代理（动机来自 Brunnermeier–Nagel–Pedersen 流动性螺旋）。同时，**主权 CDS** 作为国家信用/外部调整（全球失衡估值渠道）的可交易代理：高息货币对主权违约风险正暴露，低息货币对冲。主权信用溢价 + 平仓似然指标共同解释 carry 组合横截面 **>90%** 变异。叙事合成：主权信用、全球流动性失衡与流动性螺旋，而非纯消费 beta。

## 2. 精确公式

```text
# 组合: 按 forward discount（≈利差，CIP 下）排序，LRV 风格多空
# GDR / DOL: 组合平均超额（美元水平因子）
# HML_FB: 高息组 − 低息组（forward bias 斜率因子）

# 期权侧: Garman–Kohlhagen (1983) FX 期权 + 偏度/峰度调整
# 对每个币种 i 得尾部/平仓相关风险中性概率 ψ_{i,t}
# 组合级 position-unwinding likelihood:
PUW_{t+T} = (1/K_{t+T}) * sum_{i=1..K} ψ_{i,t+T}
# PUW 是似然指标，非字面破产概率；与全局偏度 GSQ 对照

# 主权因子: 各国 CDS 利差水平/变化；高息组合对主权违约风险 β>0
# 线性因子模型（示意）:
E[rx^j] = λ' β^j
# 候选因子: 主权信用组合、PUW 因子、GDR、对照 GVI/流动性/股权

# 另: 提出“免疫 crash”的替代 carry 规则（阈值过滤 PUW）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产 | 多币种 carry 组合（发达+新兴扩展；以 Datastream 型 FX/利率为主） |
| 期权 | 货币期权截面（矩/密度） |
| 主权 | 主权 CDS 利差 |
| 频率 | 组合月度；CDS/期权更高频可用 |
| 样本 | 约 2000 年代主样本（CDS 时代；以表为准 ~1996/2000s–2011 量级） |
| 排序 | forward discount 五/六分位类 |

## 4. 成本与可实现性

- 原文重点：资产定价解释，非零售执行
- 迁移破坏点：OTC 期权 + 主权 CDS 均非零售标的；用股权 CDS 或单一 VIX 替代会错机制
- 阈值过滤 PUW 的“免疫策略”若在全样本上选阈值 → 数据挖掘

## 5. 识别与稳健性

- 横截面定价：主权 + PUW 高 R²
- 因果叙事：Granger 等显示主权风险驱动波动/流动性等国别因子并外溢
- 对照：消费、VIX、TED、Pastor–Stambaugh、FF 等单独不足（呼应 Burnside）
- 稳健：机制转换 β、peso、β 排序组合等（长附录）
- 与 Jurek：互补——Jurek 直接对冲收益；本文提取定价因子

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 1M forward / 利差排序 | 是 | 缺可交易 forward | fail closed 净 |
| FX 期权矩/密度 | PUW | **无** | **fail closed** |
| 主权 CDS 面板 | 是 | **无**（零售不可） | fail closed / 仅宏观扩展 |
| 全局 FX 波动 GVI | 对照 | 可近似 | extension |
| CFTC 持仓 | 非必须 | 有周度 | 机制审计 |

## 7. 本项目映射

- registry：`slow_carry` 风险分解实验；**不**把主权 CDS 当默认 G9 信号
- 否决：无 CDS/期权却声称 Huang–MacDonald 复制；用单一 EM 货币 CDS 外推 G10
- 可探索：以 VIX/实现偏度作 **PUW 弱代理** 仅 extension，预注册

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Lustig–Roussanov–Verdelhan | 组合排序 |
| foundational | Brunnermeier–Nagel–Pedersen | 平仓/螺旋 |
| options twin | Jurek crash-neutral | 对冲 vs 因子 |
| macro | Gourinchas–Rey；Caballero–Farhi–Gourinchas | 失衡/估值 |

## 9. 精读问题（给最强模型）

1. PUW 对阈值 k 与期限 T 的敏感性是否在样本外稳定？
2. 无 CDS 时，财政/外债代理能否保留横截面 R²？
3. 与 Della Corte VRP 的信息重叠有多大？
4. 2011–2025 主权–FX 相关结构突变如何检验？
5. “免疫 crash 的替代 carry”是否只是低 PUW 子集的数据挖掘？
