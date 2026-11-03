# [White 2000] A Reality Check for Data Snooping

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1111/1468-0262.00152
- 开放获取: 作者/机构稿常见；正式 Econometrica
- 本项目映射: Reality Check 思想；正式实现优先 Hansen SPA（studentized）
- 复制状态: extension_only（项目未单独实现 White RC 函数）

## 1. 经济机制

从大量技术规则/预测模型中挑“最好”的那一个，其样本内表现的 p 值若按单假设计算会严重过乐观。Reality Check 的原假设是：在完整候选集合中，没有任何模型优于基准。它直接针对“挑选最好规则”的数据窥探。

## 2. 精确公式

记相对损失差（或相对绩效）\(d_{k,t}=L_{0,t}-L_{k,t}\)（基准 0 vs 模型 k），样本均值 \(\bar d_k\)。

```text
H0: max_k E[d_k] ≤ 0   # 无模型优于基准

White RC 统计量（非 studentized）:
  T_n = max_k √n * ¯d_k

Bootstrap 中心化（stationary bootstrap 路径 b）:
  T*_b = max_k √n * (¯d*_k,b − ¯d_k)

p = P*( T* ≥ T_n )
```

关键：bootstrap 必须在**同一日期路径**上同步重采样所有模型，以保留横截面相关。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产 | 应用常为股票技术规则；方法通用 |
| 频率 | 日/更高频预测误差序列 |
| 样本 | 取决于应用 |
| 来源 | 损失序列必须预计算 |
| 排序 | 取 max 相对基准 |

## 4. 成本与可实现性

- 原文扣除：应用相关；方法本身不定义成本
- 破坏点：若 \(d_k\) 用 mid 收益构造，RC 拒绝只能说明“毛收益窥探显著”
- 本项目：必须喂 **共同日期净收益** 矩阵；`cost_incomplete` 时不得做正式 RC/SPA 晋级

## 5. 识别与稳健性

- 主结果：控制“最好模型”的 data-snooping
- 已知弱点：包含大量劣模型时，max 统计量被差模型污染，功效下降（Hansen SPA 的动机）
- 非 studentized：不同波动模型混杂

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 完整候选共同日期收益 | 是 | `validate_daily_net_return_matrix` | fail closed |
| 显式 benchmark | 是 | `prepare_spa_inputs` 默认 0 基准 | 需声明 |
| 同步 stationary bootstrap | 是 | `joint_stationary_bootstrap_indices` / SPA 内置 | 内置 |
| 完整搜索族 | 是 | 注册表 + total_trials | 少计则无效 |

## 7. 本项目映射

- 无独立 `white_reality_check()` 符号
- 思想由 `hansen_spa_test`（studentized + recentering）与 runner 的 `spa_inputs` 继承
- `spa_executed=False`：正式 runner 尚未串联 SPA 执行
- 否决：只对“幸存者列”做 RC 等于自欺

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | White (2000) | Reality Check |
| extension | Hansen (2005) SPA | studentize + re-center |
| bootstrap | Politis–Romano (1994) | stationary bootstrap |

## 9. 精读问题

1. 基准取零收益 vs 取 carry 被动组合，对 FX 因子 lab 的经济含义差在哪里？
2. 既往 3,312 次搜索若不进入同一损失矩阵，RC/SPA 校正范围是什么？
3. 非 studentized RC 在波动差异极大的 sleeve 上是否会系统偏向高波动规则？
