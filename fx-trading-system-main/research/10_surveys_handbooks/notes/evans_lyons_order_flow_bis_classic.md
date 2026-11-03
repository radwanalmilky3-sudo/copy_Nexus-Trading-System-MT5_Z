# [Evans & Lyons，BIS Papers 线] Order Flow and Exchange Rate Dynamics（经典微观结构）

- 深度层级: L3
- 引用链角色: foundational（订单流决定汇率的经验基石）
- DOI/URL: JPE 2002 发表线；BIS Papers 转载/会议版
- 开放获取: `_pdfs/_bis/evans_lyons_order_flow_bis.pdf`（first-page OK：*Order flow and exchange rate dynamics*）
- 本项目映射: **机制 only**；无授权 OF 不做方向系统
- 复制状态: fail_closed_missing_data（全市场签名订单流）
- 公式置信度: high（BIS 版正文）
- published premium vs implementable: 日度 \(R^2>50\%\) 是**解释**汇率变动，不是可交易 alpha 承诺
- 2016–2025 外推: 市场结构（ECN、内部化、最后一看）改变 λ，但“流→价”渠道仍在

## 1. 经济机制

宏观汇率模型样本内 \(R^2\) 极低、样本外难赢随机游走（Meese–Rogoff 危机）。作者引入微观结构核心变量 **order flow**（买方发起减卖方发起成交量）作为价格的**近端决定因素**。信息分散于客户，经交易进入做市商，再进入价格；故 OF 对日度汇率变动有极强解释力，并能改善短窗预测。这与“仅利率/货币/贸易余额”的资产市场模型形成对照。

## 2. 精确公式

```text
# 签名订单流
# OF_t = buyer_initiated_volume - seller_initiated_volume

# 日度汇率变动回归（核心）:
# Δs_t = α + β OF_t + γ' X_t + ε_t
# X_t: 可选宏观/利率差等

# 经验量级（文中 DM/$ 全市场）:
# 约 $1bn 净美元购买 → DM 价格中的美元升值约 0.5%
# 日度 Δlog s 回归 R^2 可 > 50%

# 预测:
# 短 horizon 上相对随机游走有改进（样本内/样本外叙事）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 市场 | 即期 FX（经典结果强调 DM/USD 等） |
| 频率 | **日度**（相对宏观月度） |
| 关键 | 订单流（做市/中介记录） |
| 对照 | 纯宏观决定因素模型 |

## 4. 成本与可实现性

- 原文：价格发现/解释，非零售策略
- 迁移：公开 midquote 无法重建签名 OF；经纪商“买卖量”≠ 市场总 OF
- 用 OF 交易存在**同步性与影响**：观测到的 λ 含你自己的冲击

## 5. 识别与稳健性

- 相对宏观模型解释力数量级提升
- 系数经济含义：十亿美元级流对应可测的汇率基点
- 后续文献扩展到新闻传导（直接 vs 经 OF 间接）、多币种、定盘窗

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 签名订单流 | 是 | 无 | fail closed |
| 日度即期 | 是 | 可有 | — |
| 宏观对照变量 | 可选 | 部分 | — |

## 7. 本项目映射

- 与 `03_microstructure_intraday/notes/evans_lyons.md`（新闻传导）互补：本笔记锚定 **OF 水平解释力** 经典结果
- 与 Burnside–Cerrato–Zhang w27199：从“解释 Δs”到“OF 作定价因子”
- 否决：任何无 OF 数据的“微观结构 alpha”宣传

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| journal | Evans–Lyons JPE 2002 | 正典 |
| news | Evans–Lyons 新闻传导 | 间接渠道 |
| risk factor | Burnside et al. w27199 | OF→因子 |
| liquidity | Mancini–Ranaldo–Wrampelmeyer | 流动性测度 |

## 9. 精读问题（给最强模型）

1. 今日 EURUSD 的 λ 是否仍接近文中 0.5%/bn 量级？
2. 定盘窗 OF 与全天 OF 信息比？
3. 内部化比例上升如何偏置可见 OF？
4. 日度 \(R^2\) 高是否与分钟级噪声交易相容？
5. 无 OF 时，用限价簿不平衡作代理的最大相关上限？
