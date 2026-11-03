# [Benjamini & Yekutieli 2001] The Control of the False Discovery Rate under Dependency

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1214/aos/1013699998
- 开放获取: Annals of Statistics 开放卷期
- 本项目映射: `benjamini_yekutieli`；任意相关敏感性，不替代主假设注册
- 复制状态: exact_possible

## 1. 经济机制

FX 因子候选高度相关：同一 carry 机制的窗口变体、动量 skip 变体、重叠持有期收益在时间与横截面上同步波动。BH 的 PRDS 条件可能勉强成立，但在“任意相关”下，更安全的是把阈值再收紧一个调和数因子，避免因相关结构未知而 FDR 失控。

## 2. 精确公式

```text
c(m) = Σ_{i=1..m} 1/i = H_m   # 第 m 个调和数

BY step-up:
  找最大 k 使 p_(k) ≤ (k/m) * q / c(m)
  拒绝 H_(1)..H_(k)

q-value 形式（项目）:
  q_i = min_{j≥i} ( m * c(m) / j * p_(j) )
```

对任意依赖结构控制 FDR ≤ q；代价是功效显著下降。

**Bootstrap 分辨率（BY）：**

```text
B ≥ ceil(m * H_m / q) - 1
```

因 \(H_m\approx\ln m+\gamma\)，m=129,q=0.10 时 BY 的最小 B 远高于 BH 的 1289。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 不适用（统计） |
| 频率 | 不适用 |
| 样本起止 | 2001 方法论文 |
| 价格/远期/利率来源 | 无 |
| 排序与再平衡 | p 升序 |

## 4. 成本与可实现性

- 原文扣除：none
- 破坏点：与 BH 相同——若输入不是净可实现收益的 p，BY 仍只是“更保守的毛收益筛选”
- mid ≠ net：BY 通过不能打开 `formal_net_returns_ready`

## 5. 识别与稳健性

- 主结果：任意依赖下 FDR 控制
- 项目用法：`by_fdr_q_value`、`by_sensitivity_selected` / `by_fdr_significant` 作敏感性
- 已知失败：把 BY 当主门槛却不提高 B，会导致分辨率不足、永远无法拒绝

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| m, p, q | 是 | 同 BH | fail closed |
| H_m | 是 | `_harmonic_number` | 内置 |
| method="by" 的 min B | 是 | `minimum_resamples_for_fdr(..., method="by")` | 报告但可仅作敏感性 |

## 7. 本项目映射

- 符号：`statistical_validation.benjamini_yekutieli`
- 调用：`factor_research.py`、`long_horizon_research.py`、`intraday_validation.py`
- 角色：敏感性，不替代 BH 主注册
- 否决：不得用“BY 未通过所以只报 BH 通过子集”事后改族

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | BH 1995 | 独立/正依赖 FDR |
| extension | BY 2001 | 任意依赖 |
| boundary | Romano–Wolf | FWER stepwise 备选 |

## 9. 精读问题

1. 在 20k stationary bootstrap 下，BY 的第一阈值是否仍可分辨？
2. 相关结构已知（共同日期矩阵）时，是否应优先重采样-FDR 而非 BY 的 \(H_m\) 上界？
3. 负对照族是否应单独 BY 还是并入主族？
