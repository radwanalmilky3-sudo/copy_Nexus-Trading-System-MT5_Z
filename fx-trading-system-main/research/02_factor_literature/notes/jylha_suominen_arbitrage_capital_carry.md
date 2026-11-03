# [Jylhä & Suominen] Arbitrage Capital and Currency Carry Trade Returns

- 深度层级: L3
- 引用链角色: boundary（套利资本/拥挤与 carry 收益）
- DOI/URL: SSRN 1107797；Aalto 镜像
- 开放获取: `_pdfs/_ssrn/jylha_arbitrage_capital_currency_carry_ssrn1107797_aalto.pdf`
- 本项目映射: carry 收益的 **套利资本/投机者约束** 渠道；拥挤代理预注册
- 复制状态: extension_only（精确套利资本度量常不可得；可用代理）
- 公式置信度: medium（SSRN/Aalto 稿；以套利资本定价核心）
- published premium vs implementable: 解释时变溢价；拥挤信号本身交易成本与前视风险高
- 2016–2025 外推: 中；对冲基金/银行监管改变套利资本供给

## 1. 经济机制

若 carry 是有限套利下的风险溢价，则**套利资本**充裕时溢价被压缩，资本稀缺或撤出时溢价与崩溃风险上升。论文将投机者/套利者资本与货币 carry 收益联系起来：资本流入抬升高息货币并压低未来期望收益，反转时放大亏损。与 BNP 流动性螺旋、Breedon 订单流、Huang 平仓风险同属“中介/拥挤”家族，但强调**资本存量/约束**而非单一期权矩。

## 2. 精确公式

```text
# 标准 carry 超额 rx_{t+1} = (i*-i) - Δs_{t+1}
# 定价/预测结构（概念）:
# E_t[rx_{t+1}] = f( ArbitrageCapital_t, FundingStress_t, ... )
# 资本↑ → 当期高息货币升值、未来 rx 期望↓
# 资本↓ / 强平 → crash、未来溢价↑

# 实证: 套利资本代理对 carry 组合收益的时序预测与横截面
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 策略 | 货币 carry（主要发达） |
| 关键 | 套利/投机资本代理 |
| 样本 | 现代样本（以 SSRN 稿表为准） |

## 4. 成本与可实现性

- 资本代理若含同期收益成分 → 前视
- 无高频套利资本数据时，不可宣称精确复制
- 拥挤交易本身改变信号（Goodhart）

## 5. 识别与稳健性

- 与 funding、vol、订单流指标马赛克验证
- 风险：代理与 VIX 共线；样本危机点杠杆
- 对项目：更适合 **状态/门控** 而非独立横截面排序因子

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| carry 收益 | 是 | 部分 | 净 fail closed |
| 套利资本精确序列 | 原文 | **无** | extension_only |
| CFTC 投机净持仓 | 弱代理 | 有（lag） | 机制审计 |
| VIX/basis | 对照 | 有 | 预注册 |

## 7. 本项目映射

- registry：拥挤/资本门控扩展；CFTC 仅 60d lag 保守
- 否决：用同期基金收益构造资本代理；无 FDR 的多代理扫描
- 与 G6 CFTC 缺口：严格晋级仍 blocked

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Brunnermeier–Pedersen | 资金流动性 |
| related | Breedon–Rime–Vitale | 订单流拥挤 |
| related | Gabaix–Maggiori | 中介约束 |
| data | CFTC COT | 持仓代理 |

## 9. 精读问题（给最强模型）

1. 哪一代理在 2010 后仍有样本外预测力？
2. 银行监管收紧是否结构性提高 carry 溢价下限？
3. 与美元宽流动性（Avdjiev–Du–Koch–Shin）如何正交化？
4. CFTC lag 与“资本”概念时间错位多大？
5. 资本门控与 vol 门控同时开时如何避免过拟合？
