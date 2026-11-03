# [Menkhoff, Sarno, Schmeling & Schrimpf 2012] Carry Trades and Global FX Volatility

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1111/j.1540-6261.2012.01728.x
- 开放获取: City OA https://openaccess.city.ac.uk/id/eprint/3391/1/CTVOL_R3_v4_paper.pdf
- 本项目映射: carry 的 **全球 FX 波动风险**解释；VOL 因子 / vol-gate 动机（与 Moreira–Muir own-RV 不同）
- 复制状态: fail_closed_missing_data（1M forward bid/ask + 全宇宙日度 |Δs|）
- 公式置信度: high（City OA 全文核对）
- published premium vs implementable: 净指示性 bid-ask 后 H/L 仍显著；**≠** 零售 swap + 真实点差净
- 2016–2025 外推风险: 高。样本至 2009-08；后危机 CIP 常态偏离与 VIX/FX vol 结构变化

## 1. 经济机制

Carry 高息货币在**未预期全球 FX 波动上升**时系统性跑输，低息货币提供对冲。因此高息溢价是对 **VOL 风险暴露**（投资机会集恶化）的补偿，而非无条件 free lunch。相对 Lustig–Roussanov–Verdelhan 用可交易 HML_FX 做斜率因子，本文用**非交易**全局波动创新作为状态变量；DOL 仍作水平因子。流动性（TED、点差、Pástor–Stambaugh）有定价力但在联合检验中被 VOL 主导。

## 2. 精确公式

约定：\(s,f\) 对数即期/1M 远期（外币 per USD 惯例与 LRV 一致族）；月末再平衡。

```text
# 对数超额收益（持有外币 k）
rx^k_{t+1} ≡ i^k_t - i_t - Δs^k_{t+1} ≈ f^k_t - s^k_{t+1}     # Eq.(3)

# 组合：月末按 forward discount (f-s) 分五组
# P1 = 最低息（融资货币，净成本用 short 腿）
# P5 = 最高息（投资货币，净成本用 long 腿）
# 组内等权 log excess；H/L = HML_FX = P5 - P1
# DOL = (1/5) * sum_{j=1..5} rx^j

# 净 bid-ask（进出组合时扣；约 30%/月换手）
# 当月进入且当月退出:
rx^L = f^b_t - s^a_{t+1} ;  rx^S = -f^a_t + s^b_{t+1}
# 进入后继续持有: spot 用 mid；退出: spot 用 ask/bid 平仓

# 全球 FX 波动水平（月度，由日度构造）Eq.(4)
σ^{FX}_t = (1/T_t) * sum_{τ∈T_t} [ (1/K_τ) * sum_{k∈K_τ} |r^k_τ| ]
# r^k_τ = 日度 log spot 收益；|·| 抑极端值（含 EM）
# 亦构造 σ^{FX,DEV} 仅发达子样本

# 波动创新（主规格）: AR(1) 残差
σ^{FX}_t = a + ρ σ^{FX}_{t-1} + ε_t
VOL_t := ε_t                              # 非交易因子
# 稳健: 一阶差分 Δσ（有约 -22% 自相关，故非首选）

# SDF / beta 定价
m_{t+1} = 1 - b_DOL*(DOL_{t+1}-μ_DOL) - b_VOL*VOL_{t+1}
E[rx^i] = λ' β^i
# 预期: λ_VOL < 0；P5 的 β_VOL < 0；P1 的 β_VOL > 0
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 全样本 48 币；发达 15（欧元后约 10） |
| 频率 | 月末组合；波动由日度聚合 |
| 样本起止 | 1983-11 至 2009-08 |
| 价格/远期来源 | BBI & Reuters via Datastream；spot + 1M forward |
| 排序与再平衡 | 月末按 \(f-s\) 五分位等权；月度再平衡 |
| 期权稳健 | zero-beta straddle 验证 VOL 风险价格量级 |

## 4. 成本与可实现性

- 原文扣除：spot/forward **bid-ask**（进出与持有规则分情形）；主表为 net
- 迁移破坏点：
  1. 无 1M forward bid/ask → 不能复制净 carry
  2. 零售 swap ≠ 银行间 1M forward discount（CIP 偏离后）
  3. VOL 为**解释因子**，不是可交易 alpha 本身；因子模拟组合需 5 组合回归
- midquote premium ≠ implementable net：已扣指示价差的学术 net 仍非账户净

## 5. 识别与稳健性

- 主结果：五组合均收益随 forward discount 上升；DOL+VOL 解释 >90% 横截面；\(\lambda_{VOL}\) 显著为负
- 子样本：发达币种、其他基准货币、替代 vol 代理（含 IV）
- 控制：流动性有用但联合中弱于 VOL；可价格 equity momentum、公司债等
- 已知失败/衰减：2008 危机 carry 崩盘与高 VOL 同现；后样本 CIP/监管改变后因子稳定性待验
- 方法注意：全样本 AR(1) 估计有 errors-in-variables；作者用滚动/差分稳健

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 月末 1M forward bid/ask | 是（净收益） | 缺 | fail_closed_missing_data |
| 日度全宇宙 spot（构 σ^FX） | 是（VOL） | G9 子集 partial | extension_only（G9 vol） |
| 月末五分位宇宙日历 | 是 | G9 过窄 | extension only |
| AR(1) VOL 残差时点规则 | 是 | 可定义 | 需冻结 in-sample vs 递归 |
| 账户 swap/融资 | 实现层 | incomplete | cost_incomplete |

## 7. 本项目映射

- registry / 实验名：`slow_carry` 风险分解；`vol_gate` **动机文献**（非 Moreira–Muir 公式）
- 持有期：原文 1M；项目 21/42/63 日为扩展
- 否决条件：用政策利率伪 \(f-s\)；把 VIX 门控直接当 VOL 定价复制；无 forward 宣称 net carry
- reused-history：2016–2025 搜索史 → 任何 VOL 增强 carry 按 reused

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Lustig, Roussanov & Verdelhan (2011) | DOL/HML 组合方法 |
| foundational | Ang et al. (2006) | 股票市场 vol 风险价格 |
| critique / crash | Brunnermeier, Nagel & Pedersen (2008) | 流动性与 crash |
| boundary | Du, Tepper & Verdelhan (2018) | 后危机 CIP → \(f-s\) 合同 |
| replication | Hassan & Mano (2019) | carry 横截面 vs 时序分解 |

## 9. 精读问题（给最强模型）

1. 仅用 G9 日度 |Δs| 构造的 VOL 是否仍能单调定价 forward-discount 组合？
2. AR(1) 全样本残差 vs 递归残差对 2016–2025 λ_VOL 符号是否稳健？
3. 零售 swap 净 carry 的 β_VOL 是否与学术 net 同号？
4. VOL 与 Moreira–Muir 1/RV 门控：前者定价横截面，后者缩放时间序列——能否在同一实验中声明正交角色？
5. 2008 / 2020 两段高 VOL 中，低息货币对冲收益是否被零售点差吃掉？
