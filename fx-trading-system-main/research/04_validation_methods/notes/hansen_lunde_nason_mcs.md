# [Hansen, Lunde & Nason 2011] The Model Confidence Set

- 深度层级: L5
- 引用链角色: critique / sensitivity
- DOI/URL: https://doi.org/10.3982/ECTA5771
- 开放获取: Econometrica；作者稿常见
- 本项目映射: 计划中敏感性；**无生产实现符号**
- 复制状态: extension_only

## 1. 经济机制

SPA 问“是否存在优于基准的模型”。MCS 问另一问题：在给定置信水平下，哪些模型**尚未被证明劣于**集合中最优者。输出是“幸存模型集合”，适合披露多个难分伯仲的候选，而不是单一赢家。

## 2. 精确公式（概念）

```text
损失 L_{i,t}；相对损失 d_{ij,t} = L_{i,t} - L_{j,t}

等价模型集合 M*
逐步剔除:
  在当前集合 M 上检验 H0: E[d_{ij}]=0 ∀ i,j ∈ M
  若拒绝，剔除“最差”模型（如 max t-stat 相对损失）
  直到不拒绝 → 剩余 = MCS

p 值序列与消除规则需与 bootstrap 一致（stationary/block）
```

## 3. 数据与样本

| 项 | 要求 |
|---|---|
| 共同日期损失/收益 | 必须 |
| 预冻结候选集 | 必须 |
| 净成本 | 正式用途必须 |

## 4. 成本与可实现性

- 同 SPA：无净成本则 MCS 只是毛模型集合
- 不得把 MCS 幸存当作交易批准

## 5. 识别与稳健性

- 相对 SPA/BH 的补充视角
- 项目状态：CATALOG planned；代码未实现

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 共同净收益矩阵 | 是 | 有验证器 | 可扩展 |
| MCS 算法 | 是 | 无 | extension_only |

## 7. 本项目映射

- 文献地图：SPA/BH 外敏感性
- 实现优先级：低于接通 `hansen_spa_test` 到 runner

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| related | Hansen SPA | 相对基准 |
| related | Romano–Wolf | FWER 逐步 |
| MCS | HLN 2011 | 置信模型集 |

## 9. 精读问题

1. MCS 与 BH 同时报告时如何避免“集合叙事”洗白单一弱因子？
2. 消除规则对相关 FX sleeves 的敏感度？
3. 在 cost_incomplete 下是否应完全禁止 MCS 输出？
