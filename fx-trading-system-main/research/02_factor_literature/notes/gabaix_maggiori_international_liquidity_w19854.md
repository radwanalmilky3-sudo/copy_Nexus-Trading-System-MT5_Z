# [Gabaix & Maggiori 2015] International Liquidity and Exchange Rate Dynamics

- 深度层级: L3
- 引用链角色: foundational theory（金融中介摩擦 → UIP/disconnect）
- DOI/URL: QJE 2015；NBER w19854 https://www.nber.org/papers/w19854
- 开放获取: `_pdfs/_nber/gabaix_maggiori_international_liquidity_w19854.pdf`
- 本项目映射: carry 的**中介风险溢价**叙事；资金流/全球流动性状态变量动机；**非**可交易因子配方
- 复制状态: extension_only（理论）
- 公式置信度: high（NBER WP 机制）
- published premium vs implementable: 解释为何利差可伴随可预测超额收益；不提供无摩擦套利配方
- 2016–2025 外推: 银行杠杆、美元融资、CIP 文献（Avdjiev–Du–Koch–Shin；Du–Tepper–Verdelhan）是经验近亲

## 1. 经济机制

在标准开放宏观骨架上引入**有限风险承受力的全球金融中介**（financiers）。国际资本流动必须由中介吸收货币风险；中介风险承受力有限时，为诱使其持仓，失衡方向的货币必须提供**预期超额收益**。于是：（i）UIP 失败/ carry 可盈利，因为利差状态下中介需要补偿；（ii）全球风险偏好/中介资本冲击导致汇率大波动且与宏观基本面**disconnect**；（iii）流入国货币升值压力与 carry 平仓时的突然贬值可共存。金融渠道可与贸易净出口渠道**方向相反**：本币对美元升值时金融条件放松。

## 2. 精确公式

```text
# 概念结构（非完整一般均衡抄写）:
# 家庭/国家有外部金融需求 Imbalance_t（资本流动）
# 中介以有限风险承受力 Γ_t 吸收净 FX 暴露
# 汇率 e_t 调整以使中介参与约束成立

# 风险溢价 / 预期贬值（示意）:
E_t[Δe_{t+1}] ≈ i_t - i*_t + RP( Imbalance_t , Γ_t )
# Γ↓（中介紧缩）⇒ |RP|↑ ⇒ 汇率跳变以重建激励

# Carry 含义:
# 给定利差，高息侧往往对应需要中介提供多头的方向
# 中介紧缩冲击: 即时 carry 亏损 + 提高未来预期收益（风险溢价上升）

# Disconnect:
# e_t 对传统宏观基本面（产出、通胀）敏感度可低
# 对组合流 / 金融冲击敏感度高
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 性质 | 理论模型 + 定性/部分定量对照 |
| 经验动机 | 总资本流、集中做市、carry、disconnect 文献事实 |
| 非策略复制 | 无强制交易频率/排序表 |

## 4. 成本与可实现性

- 原文无零售成本
- 迁移：用“全球风险偏好/美元强势/中介杠杆”做**状态门控**是扩展，不是精确复制
- mid ≠ net：中介约束时代 CIP 与 swap 成本一阶重要

## 5. 识别与稳健性

- 统一解释 UIP 失败、总流、disconnect、危机放大
- 与 portfolio balance 古典文献、中介资产定价文献对接
- 边界：参数化 Γ 与 Imbalance 的映射在数据上常不唯一

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 理论 | — | PDF 有 | — |
| 跨境银行贷款/杠杆 | 经验映射 | BIS 部分 | extension |
| 美元指数 | 状态代理 | 可得 | 预注册 |
| 可交易 forward | 若做 carry 对照 | 缺 | fail closed net |

## 7. 本项目映射

- registry：funding/liquidity **gate** 动机，不新增无理论锚的流因子
- 否决：把任意资本流修订序列当严格 PIT 信号
- reused-history：流动性代理搜索计入 FDR

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| empirical CIP | Du–Tepper–Verdelhan | 中介约束价格 |
| dollar-basis | Avdjiev–Du–Koch–Shin | 美元–basis–贷款三角 |
| disconnect | Itskhoki–Mukhin 线 | 金融冲击主导汇率 |
| carry crash | BNP 2008/09 | 平仓动力学 |

## 9. 精读问题（给最强模型）

1. 用 VIX 还是广义美元指数代理 Γ，对 2016–2025 carry 门控更稳？
2. 模型预测的“流入升值”与 CFTC 投机净头寸如何对齐？
3. 零售账户能否暴露在中介 RP 上，还是只吃到噪声点差？
4. Imbalance 用贸易余额还是金融账户更贴近模型？
5. 与 HML_FX 风险因子叙事是替代还是嵌套？
