# [Hassan & Zhang 2020] The Economics of Currency Risk（综述卡）

- 深度层级: L3
- 引用链角色: foundational survey（货币风险溢价经济学）
- DOI/URL: NBER w27847 https://www.nber.org/papers/w27847
- 开放获取: `_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w27847.pdf`（**文件名误标**；正文为本篇 Hassan–Zhang）
- 本项目映射: 货币风险理论地图；连接 carry、国家规模、贸易网络、中介约束
- 复制状态: extension_only（综述）
- 公式置信度: high（对综述中的标准定义）
- published premium vs implementable: 综述强调风险溢价来源，不背书零售净 SR
- 2016–2025 外推: 理论分类仍适用；CIP 摩擦章节需用后危机证据更新阅读

## 1. 经济机制

系统梳理**货币风险为何存在、为何有横截面**：从 UIP 失败与 carry 事实出发，评述风险共享、国家规模（Hassan）、贸易网络、中介与金融摩擦、灾难/peso 等解释，并讨论对资本成本与实际配置的含义。核心信息：货币超额收益应优先当作**风险溢价与摩擦**对象，而非免费套利；不同理论对“谁应是高息货币”有可区分预测。

## 2. 精确公式

```text
# 标准货币超额收益（综述记法）:
rx_{i,t+1} = (i*_{i,t} - i_t) - Δs_{i,t+1}
# 或 forward: rx = f_t - s_{t+1}

# CIP:
(1+i)/(1+i*) = F/S
# 危机后 basis 使利率差分与远期实施分叉（综述提示）

# Carry 组合（概念）:
# 多高息货币篮子 / 空低息货币篮子
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 类型 | 综述 + 说明性事实 |
| 例示 | 长期利差与超额收益（如 NZD vs JPY 量级对照） |

## 4. 成本与可实现性

- 综述层提醒商业产品与学术 carry 在 CIP 后不一致
- 项目：任何“理论验证”不得跳过 cost contract

## 5. 识别与稳健性

- 提供理论选择菜单与经验可区分点
- 与 Hassan–Mano（forward/spot 分解）同作者线

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 正确引用文件名 | 是 | 误标路径 | 笔记已更正 |
| 分理论预测表 | 精读 | 本文 | — |

## 7. 本项目映射

- 10_surveys 与 02 交叉阅读入口
- 否决：只摘 carry 事实忽略风险章节

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| companion | Hassan–Mano QJE | 经验分解 |
| theory | Farhi–Gabaix / Gabaix–Maggiori | 机制 |
| factors | Lustig et al. | 可交易因子 |

## 9. 精读问题（给最强模型）

1. 哪条理论对 2016–2025 G10 最不被拒绝？
2. 国家规模 vs 贸易网络 vs 中介，项目数据能测哪条？
3. 综述对 CIP 的处理是否足以指导 cost contract？
4. 与 Chernov et al. 2024 的 EM 前沿如何合读？
5. 误标 PDF 是否还被其他笔记错误引用？
