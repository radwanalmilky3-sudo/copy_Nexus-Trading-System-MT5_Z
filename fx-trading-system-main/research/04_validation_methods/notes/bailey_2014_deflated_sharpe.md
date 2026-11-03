# [Bailey & López de Prado 2014] The Deflated Sharpe Ratio

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.3905/jpm.2014.40.5.094
- 开放获取: SSRN abstract_id=2460551；作者 PDF https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- 本项目映射: `deflated_sharpe_ratio`；完整试验次数 fail-closed
- 复制状态: exact_possible（日尺度 PSR/DSR 诊断）

## 1. 经济机制

在 N 次策略试验中挑出最大 Sharpe，该“最优”夏普的原假设分布不是单策略 null。若不把选择偏误与非正态（偏度/峰度）同时折入，就会把数据挖掘运气读成 alpha。DSR 给出：在披露的试验宇宙下，观测夏普是否仍显著高于期望最大夏普。

## 2. 精确公式

日收益 \(\{r_t\}_{t=1}^T\)，样本夏普（日尺度，无年化）：

```text
SR = mean(r) / std(r, ddof=1)
γ3 = skewness,  γ4 = kurtosis (四阶 / 二阶²)
```

期望最大夏普（正态近似，N 次试验）：

```text
E[max SR] ≈ μ_SR + σ_SR * [ (1-γ) Φ^{-1}(1-1/N) + γ Φ^{-1}(1-1/(N e)) ]
γ = Euler–Mascheroni ≈ 0.5772156649
```

项目两条合法路径：

```text
A) candidate_set_is_complete=True:
     μ_SR, σ_SR 来自完整矩阵各列日 Sharpe 的 mean/std

B) total_trials_evaluated = N（完整搜索次数）:
     μ_SR = 0
     σ_SR = 1/√(T-1)   # IID 零夏普 null SE
     # 禁止用 finalists 矩阵冒充搜索空间
```

方差调整与 z：

```text
V = 1 - γ3*SR + ((γ4-1)/4)*SR²
z = (SR − E[max SR]) * √(T-1) / √V
DSR probability = Φ(z)   # Probabilistic Sharpe vs expected max
```

`V≤0` 或未披露试验宇宙 → fail closed。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产 | 通用策略收益 |
| 频率 | 项目锁定日净收益 |
| 样本 | T 共同日期 |
| 来源 | 回测净收益 |
| 排序 | 选定候选 vs 试验宇宙 |

## 4. 成本与可实现性

- 必须使用 **net** 日收益；毛收益 DSR 只诊断毛数据挖掘
- `cost_incomplete` 时 DSR 可作软件诊断，但 `trading_approval` 仍 false
- midquote premium 的高 SR 会抬高 DSR 假阳性

## 5. 识别与稳健性

- 主结果：选择偏误 + 非正态修正
- 项目强制：`total_trials_evaluated` 必须 ≥ 供给列数，且计入**所有**丢弃/作废轮次
- 已知失败：N=幸存者数；年化 SR 混入日公式；在同一历史反复挖矿后仍用旧 N

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 选定候选日收益 | 是 | 矩阵列 | fail closed |
| 完整 N | 是 | `total_trials_evaluated` / 完整矩阵 | fail closed |
| 偏度峰度 | 是 | 样本矩 | 内算 |
| 共同日期 T | 是 | DatetimeIndex | fail closed |

## 7. 本项目映射

- `portfolio_validation.deflated_sharpe_ratio` → `DeflatedSharpeResult`
- 调用：`portfolio_validation_runner.run_portfolio_candidate_validation`、`intraday_validation`
- selected 由**调用方冻结**，runner 不按实现收益挑赢家
- 否决：N 不含 DSL 生成尝试 / 既往搜索账本

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Bailey–LdP (2014) DSR | 选择偏误夏普 |
| companion | Bailey et al. PBO | 过拟合概率 |
| boundary | Harvey–Liu–Zhu | 因子 t 门槛 |

## 9. 精读问题

1. 路径 B 的 IID 零夏普 null 在序列相关下是否过度保守/宽松？
2. 如何把注册表中的 3,312 历史试验并入 N 而不重复计算相关结构？
3. 日 SR 与 21 日持有重叠收益的有效样本量如何对齐？
