# [Söderlind & Somogyi 2024] Currency Liquidity Risk Premia

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1287/mnsc.2023.01031
- 开放获取: 期刊称 open；SSRN https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4067387 ；公式亦见项目文献地图
- 本项目映射: 流动性**风险暴露**排序，非 spread 水平过滤
- 复制状态: fail_closed_missing_data（逐日 1M forward + 15 USD 腿）
- 公式置信度: high（项目地图 + SSRN/开放公式核对；与 Management Science 开放版本一致）
- published premium vs implementable: 表 3 主结果**未扣交易成本**；日调仓
- 2016–2025 外推: 样本至 2022-09；与 reused-history 重叠

## 1. 经济机制

Acharya–Pedersen 型流动性调整 CAPM 在 FX 的应用：货币收益对**系统性/个体流动性冲击**的协方差应被定价。关键不是“点差宽的货币溢价”，而是对全市场或自身 illiquidity 创新的 **beta**。高流动性风险暴露要求补偿；实证上部分 beta 组合平均溢价为负号，交易方向须在见结果前按风险定价符号冻结。

## 2. 精确公式

（与 `docs/FX_FACTOR_LITERATURE_MAP_ZH.md` 一致；s,f 为**每 USD 外币**的对数间接报价。）

```text
r_{i,t} = (f_{i,t-22,t} - s_{i,t}) / 22
# f_{i,t-22,t}: 22 个营业日前签订、于 t 到期的真实 1M 远期

v_{i,t} = abs(s_{i,t} - s_{i,t-22})
bas_{i,t} = (ask_{i,t} - bid_{i,t}) / mid_{i,t}
c_{i,t} = 0.5 * [ expanding_z_252(bas_{i,t})
                + expanding_z_252(CorwinSchultz(high_ask, low_bid)_{i,t}) ]
c_{M,t} = equal_weight_mean_i(c_{i,t})
v_{M,t} = equal_weight_mean_i(v_{i,t})

# 波动正交化（expanding，252 日起）
Δ22(c_M) = α + δ Δ22(v_M) + Δ22(c̃_M)
Δ22(c_i) = α + δ Δ22(v_i) + Δ22(c̃_i)

# 252 日滚动回归暴露
β2_{i,t}: r_i ~ Δ22(c̃_M)     # systematic illiquidity
β4_{i,t}: r_i ~ Δ22(c̃_i)     # idiosyncratic

# 信号：过去 10 日平均 beta，再滞后 22 个营业日
# 每日三分位，组内等权；多高 beta / 空低 beta
# 已发表 SIR-β2、AIR-β4 平均溢价为负号 → 正风险补偿交易取其相反数须预注册
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 币种 | 15 USD 腿：AUD,CAD,DKK,EUR,HKD,ILS,JPY,MXN,NZD,NOK,SGD,ZAR,SEK,CHF,GBP |
| 频率 | 日；信号日频；收益按 22 日 forward 重叠 |
| 样本 | 1994-01-03 – 2022-09-30 |
| 报价 | Olsen 小时 → 日；Bloomberg 1M forward |
| 再平衡 | 每日重排（原文） |

## 4. 成本与可实现性

- 原文主表：**未扣交易成本**
- 日调仓在零售点差下极易转负
- 项目扩展：21/42/63 日持有 + 固定 sleeve ≠ 原文复制
- 用 spot 22 日收益代替 r_i：**删除远期溢价与融资**，不得称复制

## 5. 识别与稳健性

- 流动性风险溢价可达约 3–4% p.a. 量级（版本间表述）
- 不被标准 DOL/CAR 完全吸收
- 与静态 carry 相关 → 机制上支持流动性解释 carry 的一部分
- 正交化 vol 后仍存在

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 逐日 1M forward（22 日前签约） | 是 | **无** | **fail closed** |
| 日 bid/ask、high ask、low bid | 是 | Dukascopy 可 | 来源迁移需标注 |
| 15 币种宇宙 | 是 | 仅 G9 子集 | G9 = extension |
| expanding z / 回归窗 252 | 是 | 可 | 禁止全样本 z |
| 10 日均 beta + lag 22 | 是 | 可 | 符号预注册 |
| 成本 | 实现晋级需要 | incomplete | 未扣成本不可晋级 |

## 7. 本项目映射

- 正式方向候选：forward 到位前 **fail closed**
- 可做：报价端公式 canary / 数据质量
- 21 日调仓等为扩展，另名注册
- reused-history：是

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Acharya & Pedersen (2005) | 流动性 CAPM |
| FX liq | Mancini, Ranaldo & Wrampelmeyer | 流动性测度 |
| carry | Lustig et al.；Menkhoff vol risk | 对照因子 |
| data | Olsen / Bloomberg 合同 | 复制边界 |

## 9. 精读问题

1. 仅 G9 时 tertile 每组 3 腿，推断是否失效？
2. Corwin–Schultz 用 retail high ask/low bid 是否系统偏大？
3. 负溢价符号的风险定价解释与“反转交易”如何预注册？
4. lag 22 与 21 日项目持有如何对齐避免前视？
5. 日频 beta 换手的成本弹性曲线？
