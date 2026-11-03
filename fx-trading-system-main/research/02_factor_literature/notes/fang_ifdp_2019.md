# [Correa & DeMarco 2019 IFDP 1262] Dealer Leverage and Exchange Rates

- 深度层级: L3
- 引用链角色: boundary / negative_control
- DOI/URL: https://doi.org/10.17016/IFDP.2019.1262
- 开放获取: Fed IFDP PDF https://www.federalreserve.gov/econres/ifdp/files/ifdp1262.pdf
- 本项目映射: 2016–2025 **负对照** / dealer-capacity 状态；**非**方向 alpha
- 复制状态: negative_control
- 公式置信度: high（IFDP 全文）；**目录更正**：slug `fang_ifdp_2019` 原标注有误，正式作者为 **Correa & DeMarco**（非 Xiang Fang）
- published premium vs implementable: 预测关系在样本前期更强，后期衰减
- 2016–2025 外推: 论文自身强调监管后衰减 → 适合负对照

## 1. 经济机制

中介资产定价：一级交易商（primary dealers）的资产负债表容量影响其吸收 FX 风险的意愿，从而影响预期汇率。关键发现是**异质性**：在美外资控股 dealer 的短债/杠杆变化驱动汇率可预测性，美资总部 dealer 不显著——与 2000 年代外资 dealer 相对更大的资产负债表容量一致。渠道上，**货币与衍生品头寸**可能强于跨境贷款。监管（Basel、Volcker、杠杆率）改变约束后，预测关系减弱。

## 2. 精确公式

```text
# 主预测式（IFDP 1262 Eq.1）
ΔExRate_{i,t} = β0
  + β1 * Δln(DealerSTBorr)_{t-1}
  + β2 * RateDiff_{i,t-1}
  + β3 * X_{t-1}
  + β4 * X_{i,t-1}
  + ε_t

# DealerSTBorr = overnight_and_continuing_repo + securities_lent
# （纽约联储 primary dealer 短债代理）

# ΔExRate: 1 个月美元兑外币百分比变化（双边）
# RateDiff: Fed Funds 与对手国政策利率差
# 控制: 股指收益差、滞后汇率变化、VIX 及变化、QE 等

# 异质性: DealerSTBorr 拆 total / foreign-headquartered / domestic-headquartered
```

文献地图中的 `DealerSTBorr` 定义与此一致。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| Dealer | NY Fed primary dealer 报告；微观数据拆分内外资 |
| FX | 主要双边美元汇率 |
| 频率 | 月（主）；亦讨论周 |
| 样本 | 2000 年代为主；滚动窗显示约 2010–2013 后显著性下降 |
| 补充 | TIC 跨境贷款；FX 衍生品持仓微数据 |

## 4. 成本与可实现性

- 不是可交易“dealer 因子基金”；公开 aggregate 无法重建外资 dealer 核心拆分
- 公开 NY Fed Markets API 为**当前历史**非逐次 vintage，且跨 SBN2015/2022/2024 定义
- 即便预测存在，执行仍耗点差；且 2016 后不应作 alpha 来源

## 5. 识别与稳健性

- 总体 dealer 杠杆可预测汇率；**外资**驱动
- 控制利率差与风险变量后仍见效应（样本内）
- 滚动窗：预测力在监管强化后衰减——作者明确联系 Basel III / Volcker / leverage ratio
- 渠道测试：FX 头寸 vs 跨境贷款

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| DealerSTBorr 时间序列 | 是 | 公开 aggregate 可下 | 无 foreign 拆分 |
| foreign vs domestic 微数据 | 核心解释 | **保密** | 只能 aggregate 弱复制 |
| 汇率月变化 | 是 | 有 | — |
| 政策利差 | 是 | 可 | — |
| series break / SBN 版本 | 是 | 需保存元数据 | 拼接错误 |
| as-published vintage | 严格 PIT | 无 | strict_pit_eligible=false |

## 7. 本项目映射

- **负对照**：2016–2025 预注册“不应作为方向 alpha”
- 可作低频 dealer-capacity **风险状态**（发布后生效）
- 不新增方向候选
- 目录：保留 slug 兼容，标题改为 Correa–DeMarco

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| intermediary AP | Adrian–Etula–Muir；He–Kelly–Manela | 框架 |
| CIP | Du–Tepper–Verdelhan | 监管与中介约束 |
| related | Cenedese 等 currency mispricing & BS | 并行 |
| note | Xiang Fang 相关工作 | 不同论文；勿混淆 |

## 9. 精读问题

1. 仅用公开 aggregate STBorr，2016–2025 OOS 符号是否稳定为“应失败”？
2. SBN 断点如何做正式拼接规则？
3. 周频峰值 5–6 周的说法与月度回归如何对齐？
4. 状态变量滞后到“发布可获得日”后效应是否消失？
5. 与 CIP basis 状态是否共线？
