# [Hansen 2005] A Test for Superior Predictive Ability

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1198/073500105000000063
- 开放获取: SSRN abstract_id=264569；UNC CDR 存档稿
- 本项目映射: `hansen_spa_test`（真正 studentized + plus-one p）；**正式 runner 尚未调用**
- 复制状态: exact_possible（内部核心）；extension_only（端到端生产 runner）

## 1. 经济机制

White RC 在候选集含大量明显劣模型时功效不足。SPA 通过对相对绩效做 **studentization**，并用 **sample-dependent recentering** 削弱劣模型对 null 分布的污染，检验“是否存在至少一个模型严格优于基准”。它回答的是家族级相对表现，不是挑赢家交易授权。

## 2. 精确公式

损失差（项目用收益差等价）：\(d_{k,t}=r_{k,t}-r_{0,t}\)（收益越高越好 ⇒ 损失取负）。

```text
¯d_k = mean_t d_{k,t}
ω_k² = stationary-bootstrap population long-run variance of {d_{k,t}}

Studentized mean:
  t_k = √n * ¯d_k / ω_k

Observed SPA statistic:
  T = max(0, max_k t_k)

Recentering means μ̃_k（三种）:
  lower (liberal):      μ̃_k = max(0, ¯d_k)
  consistent (推荐):    μ̃_k = ¯d_k  if ¯d_k ≥ -ω_k * √( (2 ln ln n)/n )
                        0       otherwise
  upper (least fav.):   μ̃_k = ¯d_k

Bootstrap path b（同步 stationary bootstrap）:
  ¯d*_k,b = mean of resampled d
  T*_b = max(0, max_k  √n * (¯d*_k,b − μ̃_k) / ω_k )

p-type = (#{T*_b ≥ T} + 1) / (B + 1)   # plus-one, ≥ ties
```

项目不变量：`lower.p ≤ consistent.p ≤ upper.p`。

**Stationary-bootstrap LRV（项目实现要点）：**

```text
γ0 = mean demeaned d^2
γ_ℓ = mean demeaned_t * demeaned_{t+ℓ}
p = 1/expected_block_length
w_ℓ = (1-ℓ/n)(1-p)^ℓ + (ℓ/n)(1-p)^{n-ℓ}
ω² = γ0 + 2 Σ_ℓ w_ℓ γ_ℓ
```

零/非正 LRV → fail closed（拒绝退化输入）。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 对象 | 共同样本期的多模型损失序列 |
| 频率 | 与预测评估频率一致（项目：日净收益） |
| 样本 | n 需足以支撑块 bootstrap（项目：≥ 2 个期望块） |
| 来源 | 预计算净收益/损失 |
| 排序 | max studentized 均值 |

## 4. 成本与可实现性

- 原文：损失函数由用户定义
- 本项目硬约束：`candidate_net_returns` 必须是 **成本调整后** 日净收益；UTC 共同日期；无 fill
- `cost_incomplete_research_only` ⇒ 不得把 SPA 拒绝/通过写成可交易证据
- SPA 只校正**实际传入的列**；不能替代对全部历史搜索次数的 DSR 披露

## 5. 识别与稳健性

- 主结果：比 RC 更有功效、对劣模型更稳健
- 三种 p：报告 consistent 为主，上下界披露
- 已知陷阱：
  1. **arch 包 SPA 的 `studentize` 可能不进入计算路径**（项目审计结论）→ 不能当正式 studentized SPA
  2. 退化输入返回 p=0 → 项目强制 plus-one 与方差检查
  3. runner 中 `spa_executed=False`：输入校验通过 ≠ 已执行检验

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| T×N 净收益矩阵 | 是 | `validate_daily_net_return_matrix` | fail closed |
| benchmark Series 同 index | 是 | `hansen_spa_test` 参数 | fail closed |
| expected_block_length | 是 | 默认 63 | 配置 |
| reps, seed | 是 | 默认 50_000 / 调用方 | 配置 |
| studentize + re-center | 是 | 内部强制 | 无开关关闭 |

## 7. 本项目映射

- 核心：`src/fx_system/hansen_spa.py::hansen_spa_test`
- 输入适配：`portfolio_validation.prepare_spa_inputs`（转 loss 供 arch 交叉核验）
- 调用缺口：`portfolio_validation_runner` / `intraday_validation` 写 `spa_executed: False`
- `trading_approval=False` 硬编码
- 否决：用 arch 默认 SPA 代替内部核心；对 finalists-only 矩阵宣称家族检验

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | White (2000) | Reality Check |
| foundational | Hansen (2005) | SPA |
| bootstrap | Politis–Romano (1994) | stationary bootstrap |
| empirical p | Phipson–Smyth (2010) | (k+1)/(B+1) |

## 9. 精读问题

1. consistent recentering 的 \(\sqrt{2\ln\ln n}\) 阈值在 n≈2500 交易日下的有限样本行为？
2. 块长 63 日对 21/42/63 持有重叠收益是否匹配？
3. 如何把 SPA 与 BH 分层：先家族相对基准，再家族内 FDR？
