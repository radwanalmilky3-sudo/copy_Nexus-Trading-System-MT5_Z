# [Ready, Roussanov & Ward 2017] Commodity Trade and the Carry Trade

- 深度层级: L3
- 引用链角色: foundational（商品货币 / 无条件 carry 微观基础）
- DOI/URL: https://doi.org/10.1111/jofi.12546 ；NBER WP 19371
- 开放获取: NBER https://www.nber.org/system/files/working_papers/w19371/w19371.pdf
- 本项目映射: **商品出口结构**排序的无条件 carry（IMX）；与利差 carry 重叠诊断
- 复制状态: extension_only（贸易数据低频 + 缺 forward 时仅机制）
- 公式置信度: high（NBER 全文 + 实证表）
- published premium vs implementable: 毛收益组合；表 4 明确 **未扣 bid-ask**
- 2016–2025 外推风险: 中。贸易专业化缓慢变化；商品周期与后危机 carry 结构仍可能漂移

## 1. 经济机制

完整市场 GE：商品国出口初级投入、进口制成品；生产国相反。凸性/运力约束的冰山贸易成本使**生产国吸收更多全球生产率冲击**，商品国消费更平滑 → 预防性储蓄更弱 → **平均利率更高**。商品货币在好时升值、坏时贬值 → 对生产国定价核风险 → 正货币风险溢价。故无条件 long 商品货币 / short 避险（制成品出口）货币 ≈ 传统 carry，并能被贸易结构排序所**包容**（subsume unconditional carry，但不消灭条件 carry）。BDI/商品价格度量市场分割与运力紧张时，无条件 carry 条件期望更高。

## 2. 精确公式

```text
# 模型层（概念）
# 商品国产出 y_c = z_c
# 生产国 y_p = z_p * [z_c (1-τ_c)]^β
# 冰山成本 τ_i(x,z_k) = κ0 + κ1 * x/z_k
# 实际汇率与边际效应挂钩；商品货币风险溢价:
E[dR^e | F] = -E[(dS/S) * (dπ_p/π_p) | F]   # 对生产国定价核协方差

# 实证超额收益（标准 FX）
rx ≈ (f - s) - Δs     # 月度 log；未扣 spread 的主表

# 贸易结构信号（年度 Comtrade）
# basic = 初级/基础商品净出口
# finished = 制成品净进口（或 finished 净出口的相反）
ratio = (net_exports_basic + net_imports_finished) / total_trade_all_goods
# 每年排名用 **过去四年平均** ratio（避免时点噪声）

# 组合
# 按 ratio 分 5 或 6 组（全样本 / 发达子样本）
# IMX = long 最高 ratio（商品出口/制成品进口国）
#       - short 最低 ratio（制成品出口/商品进口国）
# 月度 FX 收益，贸易信号年更（前四年均值）

# 对照策略
# 传统 carry: 按当期 forward discount / 利率排序的 HML
# 检验: IMX 能否解释无条件 carry 均收益；条件 carry 仍残留
# 预测: BDI、商品价格指数 → 预测无条件 carry，而非纯条件成分
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 多国；表 4 全样本与发达子样本 |
| 频率 | 贸易：年；FX：月 |
| 样本起止 | 主实证约 1988-01 至 2012-12（表 4） |
| 价格/远期 | Barclays & Reuters via Datastream |
| 贸易数据 | UN Comtrade（NBER extracts） |
| 排序与再平衡 | 贸易 rank 用过去 4 年均值；FX 月度持有 |

## 4. 成本与可实现性

- 原文：明确 **returns do not take into account bid-ask spreads**
- 迁移：贸易信号极低频 → 换手低于利率排序，但腿仍是 FX 现远
- 零售：商品货币（AUD/NZD/CAD/NOK）点差与 swap 异质大
- midquote ≠ net

## 5. 识别与稳健性

- 主结果：贸易结构排序产生显著超额收益斜率；与无条件 carry 高度重叠
- 消费：商品国总消费更平滑（模型一致）
- 预测：BDI、商品指数预测无条件 carry
- 边界：不消除**条件** carry（时变利差排序）
- 与 Ferraro–Rogoff–Rossi：商品价格–汇率日度共变互补

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| Comtrade 净出口分解 + GDP/贸易 | 是 | 缺入库 | extension / fail closed 精确 IMX |
| 4 年滚动均值 PIT | 是 | 可定义 | 需发布时滞 |
| 月度 spot+forward | 是 | forward 缺 | fail_closed 净；spot-only 非原文 |
| BDI / 商品指数 | 预测层 | 可外部 | 仅状态，非方向默认 |
| bid-ask | 净收益 | incomplete | 毛→探索 only |

## 7. 本项目映射

- registry：`commodity_imx` / `commodity_currency_unconditional`；**与 slow_carry 相关但分信号**
- 持有期：月度 FX；信号年更
- 否决：把油价日度动量（Ferraro）与 IMX 混为同一试验；无贸易数据用“商品货币标签”手工硬编码而不声明 extension
- G9：AUD/CAD/NOK 等部分覆盖 → 小样本 extension

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Lustig et al. (2011) | 无条件 carry 被 IMX 解释 |
| foundational | 本文模型 | 贸易专业化 + 运力 |
| replication | Ferraro, Rogoff & Rossi | 商品价格–汇率 |
| critique | Hassan & Mano | 持久横截面溢价 |
| boundary | Bakshi–Panayotov 等 | 商品指数预测 carry |

## 9. 精读问题（给最强模型）

1. 仅 G9 手工商品货币多空，是否伪复制 IMX？
2. 贸易数据发布时滞下，严格 PIT 的 IMX 是否仍 subsume carry？
3. 2014–2016 / 2020 商品崩盘中 IMX 与 HML_FX 尾部是否同步？
4. BDI 预测信号若进 FDR，应属状态层还是方向层？
5. 无 forward 时用利率排序对照 IMX 的重叠 R² 如何报告？
