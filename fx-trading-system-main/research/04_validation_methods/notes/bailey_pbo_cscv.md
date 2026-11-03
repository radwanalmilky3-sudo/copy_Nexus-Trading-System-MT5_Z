# [Bailey, Borwein, López de Prado & Zhu] Probability of Backtest Overfitting (CSCV)

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.21314/JCF.2016.322 ；SSRN abstract_id=2326253
- 开放获取: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf ；附录 SSRN 2568435
- 本项目映射: `cscv_probability_of_backtest_overfitting`；固定 16 块
- 复制状态: exact_possible（16-block CSCV）

## 1. 经济机制

即使 IS 最优策略夏普很高，其 OOS 相对排名仍可能系统性低于中位——这就是 backtest overfitting。PBO 估计“IS 赢家在 OOS 表现低于中位”的概率；高 PBO 意味着策略选择过程不可信，而非单一参数点估计误差。

## 2. 精确公式

将共同日期面板分成 \(S=16\) 个连续块。对每个组合 \(c\in\binom{16}{8}\)：

```text
IS = 8 块并集；OOS = 互补 8 块
选 k* = argmax_k SR_IS(k)   # 必须唯一，否则 undefined
ω = rank_OOS(k*) / (N+1)     # 升序平均秩 / (N+1)
λ = logit(ω) = ln( ω / (1-ω) )

PBO = mean( 1{λ ≤ 0} )      # OOS 相对表现 ≤ 中位 的比例
```

项目细节：

```text
- 每块 ≥2 观测；总行 ≥ 16*2
- 用块内 sum / sumsq 聚合 SR，避免重复扫原始收益
- 零波动 split 或 IS 并列赢家 → defined=False（不任意破平）
- selection_counts 披露各列被选为 IS 赢家的次数
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 对象 | 多策略对齐收益矩阵 |
| 频率 | 规则网格（项目：日） |
| 样本 | 足够分 16 块 |
| 来源 | 回测净收益 |
| 排序 | IS max SR → OOS 秩 |

## 4. 成本与可实现性

- 应用在净收益矩阵上才对交易有意义
- 成本缺失时 PBO 仍可诊断“毛收益选择不稳”，但不能洗白成本缺口
- 候选列必须是**完整声明集**，不能只放 finalists（会系统性低估 PBO）

## 5. 识别与稳健性

- 主结果：CSCV 估计 PBO
- 固定 16 块：\(\binom{16}{8}=12870\) 次组合（项目 `split_count`）
- 已知失败：时间块破坏后结构突变时解释需谨慎；策略高度相关时秩不稳定

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| T×N 矩阵 N≥2 | 是 | validate matrix | undefined |
| 16 连续块 | 是 | `CSCV_BLOCK_COUNT=16` | 固定 |
| 破平规则 | 是 | 并列 → undefined | 不硬破 |

## 7. 本项目映射

- `portfolio_validation.cscv_probability_of_backtest_overfitting` → `PBOResult`
- runner / intraday_validation 写出 `pbo_splits.csv`、`pbo_selection_counts.csv`
- 与 DSR 并行；均不批准交易
- 否决：对子集矩阵报低 PBO 当作稳健

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Bailey et al. PBO | CSCV |
| companion | DSR | 选择偏误另一面 |
| boundary | purged/embargo CV | 标签泄漏另一类问题 |

## 9. 精读问题

1. 16 块对 2016–2025 ≈10 年日频是否过粗/过细？
2. 相关候选导致 IS 并列时，预注册破平规则应如何写？
3. PBO 与 SPA 同时通过/冲突时的决策表？
