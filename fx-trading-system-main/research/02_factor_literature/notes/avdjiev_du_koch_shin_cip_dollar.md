# [Avdjiev, Du, Koch & Shin 2016/2019] The Dollar, Bank Leverage and CIP Deviations

- 深度层级: L3
- 引用链角色: boundary / data_contract（美元–银行杠杆–CIP 三角）
- DOI/URL: BIS WP 592；AER: Insights 2019 线；NBER 编号常与 w24555 混淆
- 开放获取: `_pdfs/_bis/avdjiev_du_koch_shin_wp592_cip_dollar.pdf`
- PDF 标签警告: `_pdfs/_nber/avdjiev_du_koch_shin_cip_w24555.pdf` **误标**，正文为 Kalemli-Özcan–Laeven–Moreno *Debt Overhang…* (w24555)，**不是**本文
- 本项目映射: CIP / 美元融资状态；**非** spot 方向策略；与 `06_broker_costs` 合同交叉
- 复制状态: fail_closed_missing_data（同步 basis + 跨境贷款 + 结算日历）
- 公式置信度: high（BIS WP）
- published premium vs implementable: basis 套利“无风险”在银行资产负债表约束下不可无限规模；零售更不可做
- 2016–2025 外推: 美元强 ↔ basis 走阔 仍是关键状态事实

## 1. 经济机制

CIP 在教科书中应消除无风险套利，但 GFC 后偏离持续。作者强调：**套利需银行杠杆**；银行（及依赖银行融资的主体）面临资产负债表约束，故偏离可持久。核心经验三角：

1. **美元走强** ↔ **cross-currency basis 走阔**（CIP 偏离变大）  
2. **美元走强** ↔ **跨境美元银行贷款收缩**  
3. 各货币 basis 对美元因子的 **β 不同** → 解释截面套利利润差异  

美元是全球银行杠杆的影子价格代理：美元升值对应风险承受力下降、套利资本退出、偏离扩大。传统“避险货币”（JPY、CHF）对美元因子暴露更高、basis 更大；高息 carry 货币暴露更低。

## 2. 精确公式

```text
# Cross-currency basis（示意，与 Du–Tepper–Verdelhan 同族）:
# 现金市场美元利率 vs 经 FX swap 从外币换入美元的隐含美元利率之差
basis_t ≈ r^{USD, cash}_t - r^{USD, FX-swap implied}_t
# 符号惯例以文中/市场报价为准；关注 |basis| 与符号稳定定义

# 三角关系（回归概念）:
Δ basis_t = a + b * Δ DollarBroad_t + controls + e_t
# b > 0 方向: 美元升值 → 偏离扩大（与图1镜像）

Δ Loan^{USD cross-border}_t = c + d * Δ DollarBroad_t + ...
# d < 0: 美元升值 → 贷款收缩

# 截面:
# basis_i 对美元因子的 β_i 解释 E[套利利润_i]
# 事件研究: 2016 美国大选后美元贬值窗口
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 货币 | 约 10 个最流动性货币 vs USD |
| 频率 | 日/周 basis；季度跨境贷款 |
| 样本 | 约 2007–2017（BIS 修订版窗口） |
| 美元 | FRB broad dollar index |
| 贷款 | BIS 跨境银行美元贷款流量 |

## 4. 成本与可实现性

- 原文：银行间/机构套利约束；无零售
- 迁移：零售 swap **不是** CIP basis；期限与法律实体均错位（见 C6）
- mid ≠ net：观测到 basis ≠ 账户可赚 basis

## 5. 识别与稳健性

- 水平与变化回归；滚动窗稳定性
- 截面 β 排序与避险/高息货币叙事一致
- 事件研究增强因果叙述
- 与季度末监管窗口（Du–Tepper–Verdelhan）互补：本文强调**美元周期**，DTV 强调**日历监管**

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 同 tenor OIS + forward | basis | 缺 | fail closed |
| 结算/到期日 | 是 | 缺日历字段 | C2 |
| 美元指数 | 状态 | 可得 | 诊断 |
| BIS 贷款 | 三角第三边 | 低频 | 状态 only |
| 正确 PDF | 是 | BIS 正确；NBER 文件误标 | 已记录 |

## 7. 本项目映射

- registry / 合同：`06_broker_costs` CIP checklist；美元强作 **funding stress 诊断**
- 否决：用零售点差序列冒充 cross-currency basis
- 跨笔记：`du_tepper_verdelhan_cip.md`、`borio_bis_basis.md`

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational CIP | Du–Tepper–Verdelhan | 监管窗口 |
| official | Borio BIS 季报 | 市场结构 |
| theory | Gabaix–Maggiori | 中介风险 |
| dollar safety | Jiang–Krishnamurthy–Lustig | 美元便利收益 |

## 9. 精读问题（给最强模型）

1. 广义美元与 DXY 谁对 G10 basis 更稳？
2. Qend 与美元周期交互是否超可加？
3. 2016–2025 截面 β 排序是否重排？
4. 项目无 OIS 时，政策利率 proxy 偏差上界？
5. 如何 fail-closed 防止把 basis 诊断写成交易信号？
