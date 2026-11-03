# [Chernov, Dahlquist & Lochstoer 2024] Anatomy of Currency Risk Premia

- 深度层级: L3
- 引用链角色: foundational / critique（新兴市场 + 未定价风险对冲抬升策略 SR）
- DOI/URL: NBER w32900 https://www.nber.org/papers/w32900
- 开放获取: `_pdfs/_nber/chernov_dahlquist_lochstoer_anatomy_currency_w32900.pdf`
- 本项目映射: G10-only vs G10+EM 边界；风格策略（dollar/carry 等）的**可对冲未定价风险**；OOS 均值-方差有效基准
- 复制状态: fail_closed_missing_data（宽货币宇宙 forward）/ extension_only（仅 G10 spot 子集）
- 公式置信度: high（NBER WP 2024）
- published premium vs implementable: 学术 SR（如 carry 0.71→1.29 在对冲未定价风险后）仍为 mid/机构口径
- 2016–2025 外推: 文中强调后期 G10 风格 premia 变平而 EM 仍重要——与项目样本高度相关

## 1. 经济机制

经典结论常用 G10 货币：dollar（等权多外币）与截面 carry 等风格收益。本文表明：

1. **浮动新兴市场货币**显著改变风险–收益前沿；仅 G10 的条件最大 SR 趋势向下，GE（G10+EM）更高。  
2. 许多著名交易策略暴露于**不要求风险溢价的共同风险**（unpriced risks，常与地理/区域因子相关）。  
3. 条件剥离这些未定价风险后，策略 SR **大幅上升**（例：carry 0.71→1.29），为定价模型提供新基准。  
4. 用 G10+EM 构造的**实时无条件均值-方差有效（UMVE）**组合，可在样本内/外对风格与动态策略定价。

机制含义：部分“alpha”是对冲不完美；部分“衰退”是 G10 宇宙特有。EM 不是简单加噪声，而是改变可定价前沿。

## 2. 精确公式

```text
# 风格示例:
# Dollar: 等权多一篮子外汇 vs USD
# Carry: 高息多 / 低息空（截面）

# 未定价风险: 对货币收益协方差中不进入风险价格的成分
# 条件对冲: 在每个 t 估计策略对 unpriced factors 的暴露并对冲
# r^{hedged}_{t+1} = r^{strategy}_{t+1} - β_t' f^{unpriced}_{t+1}

# UMVE（无条件均值-方差有效）组合:
# 在扩大宇宙上实时估计 E[r], Σ，形成 mean-variance 切点/UMVE 权重
# 理论: UMVE 超额收益可无条件定价一切可容许动态策略
# 条件 SDF 可表示为 UMVE 收益的函数（Hansen–Richard 族思想）

# 条件最大 SR 路径:
# MSR_t 用扩展宇宙 vs 仅 G 宇宙 → 文中 G 后期走平、GE 仍高
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 宇宙 | G10 与浮动 EM；EM 数据约自 1997 起更完整 |
| 频率 | 月度策略收益为主 |
| 样本 | 长期面板至 2020s（见文中图与表） |
| 策略集 | dollar、carry 及文献中其他风格/动态策略 |
| 评估 | 样本内 + OOS；条件/无条件定价 |

## 4. 成本与可实现性

- 原文：机构/学术货币宇宙；EM 点差与可交易性远差于 G10
- 迁移：项目 Dukascopy 零售宇宙 **不能**声称 GE 前沿；EM 成本可能吞噬对冲后 SR
- mid ≠ net：对冲交易本身增加换手与点差

## 5. 识别与稳健性

- G vs GE 累积收益分叉（1997 后 carry）
- OOS UMVE 仍定价
- 未定价风险与地理因子相关
- 对模型含义：只拟合 G10 两因子可能误判

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 宽宇宙 forward | 是 | 无 | fail closed GE |
| G10 子集 | 部分对照 | 部分品种 | extension |
| 实时 Σ 估计 | UMVE | 可代码 | 超参预注册 |
| EM 可交易成本 | 净 SR | 无 | 不可声称净 |

## 7. 本项目映射

- registry：G10-only 结果标注 **universe boundary**；禁止静默外推 EM
- 否决：在窄宇宙优化对冲 β 后当发现
- reused-history：对冲因子选择计入 FDR

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Lustig–Roussanov–Verdelhan | dollar/carry 因子 |
| methods | Hansen–Richard | 条件/无条件均值-方差 |
| CIP/friction | Du et al. | 后危机结构变化 |
| survey | Burnside ARFE | 风格解释谱 |

## 9. 精读问题（给最强模型）

1. 项目 14 品种接近 G 还是残缺 G？对 UMVE 偏差多大？
2. 未定价地理因子能否用区域 ETF/利率代理？
3. 对冲后 SR 上升有多少来自前视协方差？
4. 2015–2025 G10 carry 变平是否被文中机制预测？
5. 成本后“对冲+carry”是否仍优于裸 carry？
