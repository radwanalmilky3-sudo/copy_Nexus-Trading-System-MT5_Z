# [Itskhoki 2021] The Story of the Real Exchange Rate（+ disconnect 映射）

- 深度层级: L3
- 引用链角色: foundational theory survey / boundary（汇率 disconnect 与 UIP）
- DOI/URL: NBER w28225 https://www.nber.org/papers/w28225
- 开放获取: `_pdfs/_nber/itskhoki_story_real_exchange_rate_w28225.pdf`
- PDF 标签警告: `_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w27847.pdf` **误标**，正文为 Hassan & Zhang *The Economics of Currency Risk* (w27847)，**不是** Itskhoki–Mukhin disconnect 原文
- 正典 disconnect 原文: `_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf` → L3 笔记 `itskhoki_mukhin_disconnect_w23401.md`
- 本项目映射: 解释边界——宏观基本面弱预测 ≠ 可交易 alpha；金融冲击主导汇率波动时因子应偏风险/中介而非 PPP 口号
- 复制状态: extension_only（理论综述）
- 公式置信度: medium–high（w28225 机制；w23401 正典已 deep_noted）
- published premium vs implementable: 不提供策略；约束“基本面回归”类因子预期
- 2016–2025 外推: disconnect 仍是默认；价值/PPP 因子必须带长持有与成本纪律

## 1. 经济机制

Itskhoki 线（含与 Mukhin 的 disconnect 工作）把开放经济事实重组为：**名义/实际汇率近似随机游走、与宏观基本面弱相关（Mussa 等）**，同时 UIP/货币溢价与国际资产持仓模式需要**金融冲击 + 有限套利/不完全市场**才能同时匹配。贸易与价格粘性解释部分传递，但难以单独产生观测到的汇率波动幅度；**金融部门冲击**通过资产需求移动汇率，再反馈到实体。对因子研究的含义：慢周期“价值”若存在，应被理解为风险/均衡重置，而非无摩擦 PPP 套利；carry 则更贴近货币风险溢价与中介约束。

## 2. 精确公式

```text
# 实际汇率（示意）:
Q_t = S_t P*_t / P_t

# Disconnect 核心矩（定性）:
# corr(Δs, Δmacro fundamentals) 低
# σ(Δs) >> σ(宏观差分可解释部分)
# UIP: E_t[Δs_{t+1}] ≠ i_t - i*_t ；存在货币风险溢价 rp_t

# 资产需求 / 金融冲击（概念）:
# 净外部资产需求 D( rp_t , shock^fin_t ) = 供给
# shock^fin 大 → s 大幅调整以出清

# 与 carry:
# rp_t 与利差相关成分可产生 carry 平均利润
# 但 rp 由金融状态驱动 → 危机时同步恶化（左尾）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 类型 | 理论综述 / 叙述性综合 |
| 经验锚 | 发达市场浮动汇率时代典型事实 |
| 策略表 | 无 |

## 4. 成本与可实现性

- 无交易策略成本
- 迁移：任何“基本面缺口”信号必须声明 **PIT vintage** 与持有期；否则是故事不是复制

## 5. 识别与稳健性

- 统一：disconnect、UIP 失败、国际风险共享不足
- 与 Gabaix–Maggiori 中介模型、Farhi–Gabaix 灾难模型可并列而非互斥
- PDF 治理：勿引用误标 w27847 文件当 disconnect 原文

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 正确 disconnect 原文 PDF | 精读 Itskhoki–Mukhin | **缺口**（文件名错文） | 重新 OA 下载；见 GAPS |
| REER/PPP | value 扩展 | 部分 | vintage 问题 |
| 金融冲击代理 | 叙事对照 | VIX/美元/basis | 预注册 |

## 7. 本项目映射

- registry：约束 `currency_value` / 宏观缺口类实验预期
- 否决：短窗 PPP 均值回复当高频信号
- 备注：精读栈优先正确 Itskhoki–Mukhin PDF + 本文 w28225

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| theory twin | Gabaix–Maggiori | 金融中介 |
| value emp | Menkhoff et al. RFS value | 经验价值 |
| UIP survey | Engel 1996 | 经典谜题 |
| mislabeled OA | Hassan–Zhang w27847 | 误落盘文件正文 |

## 9. 精读问题（给最强模型）

1. disconnect 与 Menkhoff value 的 5y 窗口如何不矛盾？
2. 金融冲击可观测代理的最小集合是什么？
3. 浮动 vs 管理浮动样本对 disconnect 矩的影响？
4. 项目 2016–2025 日度 FX 是否仍近似 RW 到无法用宏观月度预测？
5. 如何在 registry 标注“theory boundary only”避免被 FDR 当策略？
