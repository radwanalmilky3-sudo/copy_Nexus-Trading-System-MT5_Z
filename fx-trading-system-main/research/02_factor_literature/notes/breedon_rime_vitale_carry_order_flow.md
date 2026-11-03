# [Breedon, Rime & Vitale 2015] Carry Trades, Order Flow and the Forward Bias Puzzle

- 深度层级: L3
- 引用链角色: foundational microstructure（订单流分解 forward bias）
- DOI/URL: QMUL WP 761 / SSRN 2643531；相关 NY Fed 2010 版本
- 开放获取: `_pdfs/_ssrn/breedon_rime_vitale_carry_order_flow_forward_bias_ssrn2643531.pdf`；`_pdfs/_ssrn/breedon_rime_vitale_carry_order_flow_nyfed2010.pdf`
- 本项目映射: **机制参考 only**——订单流解释 Fama β；不可无 EBS 数据做方向因子
- 复制状态: fail_closed_missing_data（EBS 成交订单流 + Reuters 个体调查）
- 公式置信度: high（2015 WP）
- published premium vs implementable: 分解解释 ≠ 可交易信号；订单流实时不可得
- 2016–2025 外推: 微观结构平台迁移（EBS 份额变化）削弱外推

## 1. 经济机制

Forward bias（Fama β≪1）可分解为：**预期误差** + **时变风险溢价**。在 Evans–Lyons 微观结构逻辑下，carry 引发的**组合再配置订单流**必须由对手方以更高风险溢价吸收 → 高息货币被“抬升”，同时订单流预测收益**负偏/崩溃风险**上升。作者用约十年 EBS 真实成交订单流 + Reuters 调查预期，发现订单流可解释 **一半以上** forward bias（尤其典型 carry 货币对），其余为预期误差。Carry 活动通过订单流渠道同时制造溢价与 crash 风险。

## 2. 精确公式

```text
# Fama / FRU:
s_{t+1} - s_t = α + β (f_t - s_t) + ε_{t+1}
# H0: α=0, β=1；实证 β 常为负（Froot–Thaler 平均约 -0.88）

# 调查预期分解（Froot–Frankel 传统）:
# β 的偏离 = 预期误差贡献 + 风险溢价贡献

# 本文核心:
# 风险溢价部分 = 函数(订单流 OF_t)
# OF = 外币净主动买压（成交方向加总）
# 利差与 OF 负相关 → 与 forward bias 一致的时变 rp

# 预测/分解回归（概念）:
Δs_{t+1} = a + b (f-s)_t + c OF_t + u
# 或 rp_t = g(OF_t)；carry 强度 → OF → 未来 skewness↓

# CIP 在样本内（至 2007-04）视为成立；危机后 CIP 破裂不在样本
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 货币对 | 主：EURUSD, USDJPY, GBPUSD（EBS 主导盘） |
| 订单流 | EBS 真实成交，约 **1997-01 – 2007-04**（十年，长于多数微观研究） |
| 预期 | Reuters 调查：金融机构个体预测（非仅均值） |
| 频率 | 与调查/利差对齐的低频（日/周/月层，以表为准） |
| 对照 | 优于指示性报价订单流研究（如部分 Burnside 微观设定） |

## 4. 成本与可实现性

- 原文不是零售执行回测
- 迁移：无授权 EBS/全市场订单流 → **不能**复制分解或信号
- Dukascopy 零售流 ≠ EBS 做市商间流（符号、覆盖、噪音）
- 调查预期数据同样不可持续获取

## 5. 识别与稳健性

- 主结果：OF 解释 >50% forward bias；carry 对更强
- OF 预测偏度：carry 相关流增加崩溃风险
- 预期误差仍解释剩余部分（学习/比索/疏忽等文献兼容）
- 样本止于 2007 春：避开 CIP 危机，也限制危机外推
- 与 Breedon–Ranaldo 日内本地时段流：同属订单流价格压力族，频率与问题不同

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| EBS 签名订单流 | 是 | **无** | **fail closed** |
| Reuters 个体调查 | 分解预期 | **无** | fail closed 分解 |
| 即期/远期/利差 | 是 | 部分 | 净收益仍 fail closed |
| 零售 tick 流 | 弱代理 | Dukascopy 可能 | 仅 negative_control |

## 7. 本项目映射

- registry：不进方向候选；机制注释链接 `evans_lyons`、BNP crash
- 否决：用零售净买压冒充 EBS OF 做正式 carry
- 可做：文献对照图——利差状态 vs 事后偏度（无 OF）

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Evans–Lyons | 订单流定价 |
| foundational | Fama；Froot–Frankel | bias 与调查分解 |
| crash twin | Brunnermeier–Nagel–Pedersen | 平仓与偏度 |
| related | Breedon–Ranaldo 日内模式 | 另一订单流课题 |

## 9. 精读问题（给最强模型）

1. 2010 后 EBS 市场份额下降，分解系数是否结构突变？
2. 无调查时，用远期隐含预期替代会如何偏 OF 份额？
3. 订单流对偏度的预测能否转化为预注册门控？
4. 与 Gabaix–Maggiori 中介约束模型的映射是否同构？
5. 三对货币结论外推到 AUD/NZD carry 核心对是否成立？
