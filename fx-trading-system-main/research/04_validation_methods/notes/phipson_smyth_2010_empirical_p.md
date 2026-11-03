# [Phipson & Smyth 2010] Permutation P-values Should Never Be Zero

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.2202/1544-6115.1585
- 开放获取: 生物统计文献；方法可合法复述
- 本项目映射: plus-one p 贯穿 bootstrap / SPA
- 复制状态: exact_possible

## 1. 经济机制

蒙特卡洛/置换检验若报告 \(p=0\)，会虚假暗示“不可能的原假设”，并在下游 FDR 中产生不可分辨的零 p。正确做法是把观测统计量算作一次极端结果，使最小 p 为 \(1/(B+1)\)。

## 2. 精确公式

```text
# 单边 “越大越极端”
k = #{ b : T*_b ≥ T_obs }     # 或 >；项目 SPA 用 ≥
p = (k + 1) / (B + 1)

# 性质:
min p = 1/(B+1) > 0
p ∈ {1/(B+1), 2/(B+1), ..., 1}
```

与 BH 耦合：见 `minimum_resamples_for_fdr`。

蒙特卡洛 SE（项目）：

```text
se(p) = √( p(1-p) / (B+1) )
```

## 3. 数据与样本

| 项 | 原文 | 项目 |
|---|---|---|
| 对象 | 置换检验 | bootstrap 均值/SPA |
| B | 用户选 | 常 20_000 或 SPA 50_000 |

## 4. 成本与可实现性

- 纯统计；不改变成本合同
- 但 p 永不 0 可阻止“伪完美”净收益叙事

## 5. 识别与稳健性

- 主结果：置换 p 不应为 0
- 项目：`pvalue_correction="plus_one_greater_than_or_equal"`
- 陷阱：arch 等库在退化输入下可返回 p=0

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| exceedance 计数 k | 是 | SPA / bootstrap | fail closed |
| B | 是 | reps | 配置 |

## 7. 本项目映射

- `hansen_spa_test` p 计算
- `factor_research._block_bootstrap_rank_test`：`/(bootstrap_samples+1)`
- `intraday_validation` exceedances
- `monte_carlo_p_value_standard_error`

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Phipson–Smyth (2010) | plus-one p |
| application | Hansen SPA / BH 分辨率 | 项目接线 |

## 9. 精读问题

1. 用 `>` 还是 `≥` 对离散 bootstrap 分布的影响？
2. B=20000 时最小 p 对 m=129 的 BH 第一阈值余量多大？
3. 双侧 plus-one 在 IC 符号不确定时如何定义？
