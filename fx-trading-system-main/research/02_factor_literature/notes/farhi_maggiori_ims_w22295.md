# [Farhi & Maggiori 2018] A Model of the International Monetary System

- 深度层级: L3
- 引用链角色: foundational theory（储备货币层级 / Triffin 现代版）
- DOI/URL: QJE 2018；NBER w22295 https://www.nber.org/papers/w22295
- 开放获取: `_pdfs/_nber/farhi_maggiori_global_currency_hierarchy_w22295.pdf`
- 本项目映射: 美元便利/储备需求作为 **长期风险溢价与安全资产**边界；非短线因子
- 复制状态: extension_only（理论）
- 公式置信度: high（机制层）
- published premium vs implementable: 解释储备货币溢价与体系不稳定性；不给出零售交易规则
- 2016–2025 外推: 美元稀缺、财政/储备供需仍相关（与 dollar safety 文献对话）

## 1. 经济机制

构建国际货币体系模型：世界对**安全储备资产**有需求；霸权货币发行国提供安全债，但面临 **Triffin 式权衡**——扩大供给满足全球需求可能侵蚀安全性/信心。体系可呈现：储备货币溢价、过度发行激励、信心危机与体系转型。对汇率与货币溢价：美元（或霸权货币）资产具有便利收益，影响利率平价与货币层级；危机中安全资产争夺放大汇率与 basis 波动。与纯 carry 风险因子不同，这里强调**公共品式安全资产供给**与地缘/财政约束。

## 2. 精确公式

```text
# 概念:
# 世界安全资产需求 D_safe( r_safe, risk, confidence )
# 霸权供给 S_safe( fiscal capacity, issuance )
# 均衡便利收益 / 安全溢价 s_t 使 D=S

# 对汇率/UIP 的含义（示意）:
# 霸权货币资产: i_heg ≈ i* + E[Δs] - convenience_yield + risk terms
# convenience_yield > 0 ⇒ 更低收益率 / 特殊融资条件

# 危机: confidence↓ ⇒ 对安全资产争夺 ↑ ⇒ 汇率与跨境融资条件跳变
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 类型 | 理论 |
| 经验动机 | 储备构成、美元份额、历史体系更迭 |
| 策略 | 无 |

## 4. 成本与可实现性

- 无直接策略
- 迁移：美元便利是解释变量，不是可卖空的稳定 alpha 源

## 5. 识别与稳健性

- 现代 Triffin 逻辑与储备货币不稳定性
- 与 Jiang–Krishnamurthy–Lustig dollar safety 经验线互补
- 边界：难以用日度信号操作“体系状态”

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 理论 PDF | 是 | 有 | — |
| 储备数据 | 对照 | COFER 等低频 | 状态 only |

## 7. 本项目映射

- 解释 **dollar 因子 / 安全溢价** 长期背景
- 否决：把财政新闻当无预注册高频 FX 信号

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| safety | Jiang–Krishnamurthy–Lustig | 美元便利收益 |
| CIP | Du–Tepper–Verdelhan / Avdjiev et al. | 美元融资 |
| hierarchy emp | Maggiori–Neiman–Schreger | 货币层级持仓 |

## 9. 精读问题（给最强模型）

1. 便利收益变化与 HML_FX 正交吗？
2. 储备需求冲击的可观测代理？
3. 多储备货币均衡对 carry 横截面的含义？
4. 与 Gabaix–Maggiori 中介模型如何嵌套？
5. 对 2016–2025 美元周期，模型预测哪些可证伪矩？
