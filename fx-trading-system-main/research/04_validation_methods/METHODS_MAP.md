# METHODS_MAP — 验证方法 → 本项目符号

更新日期：2026-07-17  
范围：只读扫描 `src/fx_system/**`；不改代码。

## 总原则

| 原则 | 含义 |
|---|---|
| 净收益优先 | DSR/PBO/SPA 的正式解释需要成本调整日收益；`cost_incomplete_research_only` 禁止正式净 PnL 主张 |
| 完整试验数 | DSR/PBO 的 N 含全部搜索史，不是 finalists |
| SPA 范围 | 只校正传入列；不能替代历史搜索披露 |
| Bootstrap 同步 | 多候选必须共用日期路径 |
| Plus-one p | 永不报 0；与 FDR 分辨率耦合 |
| v4 分辨率 | m=129,q=0.10 → B≥1289；配置常用 B=20000 |

## 映射表

| 方法 | 代码符号 | 主要调用点 | 状态 | 关键 caveat |
|---|---|---|---|---|
| BH FDR | `statistical_validation.benjamini_hochberg` | `factor_research`, `long_horizon_research`, `intraday_validation` | **已接线** 主门槛 | m 必须=统一检验族；PRDS 假定 |
| BY FDR | `statistical_validation.benjamini_yekutieli` | 同上 | **已接线** 敏感性 | \(H_m\) 更严；需更高 B |
| FDR 最小 B | `minimum_resamples_for_fdr` | factor/long_horizon 门禁 | **已接线** | `ceil(m·c/q)-1` |
| Stationary bootstrap（联合） | `joint_stationary_bootstrap_indices` | `intraday_validation` | **已接线** | 禁止列独立重采样 |
| Circular block bootstrap | `joint_circular_block_bootstrap_indices` | 统计模块可用 | 工具 | 固定块长敏感性 |
| Moving-block rank p | `factor_research._block_bootstrap_rank_test` | 因子 IC/rank | **已接线** | plus-one；块=bar |
| White Reality Check | （无独立函数） | 思想并入 SPA | 未单列 | 劣模型功效问题 |
| Hansen SPA | `hansen_spa.hansen_spa_test` | **核心存在** | **runner 未执行** | studentized+re-center+plus-one；`trading_approval=False` |
| SPA 输入 | `prepare_spa_inputs` → `SPAInputs` | `portfolio_validation_runner`, `intraday_validation` | 输入校验 | 转 loss 供 arch 交叉核验 |
| SPA 执行标志 | `spa_executed: False` | runner manifests | 硬编码未跑 | 有输入 ≠ 已检验 |
| arch SPA | 可选外部 | `prepare_spa_inputs` 文档 | **交叉核验 only** | **`studentize` 可能不进计算路径**；退化可 p=0 |
| DSR | `deflated_sharpe_ratio` | portfolio/intraday runners | **已接线** | 必须 `total_trials_evaluated` 或 complete matrix |
| PBO/CSCV | `cscv_probability_of_backtest_overfitting` | 同上 | **已接线** | 16 块；并列/零波动 → undefined |
| 共同日期矩阵校验 | `validate_daily_net_return_matrix` | DSR/PBO/SPA | **已接线** | 禁止 silent intersect/fill |
| Plus-one SE | `monte_carlo_p_value_standard_error` | SPA | **已接线** | |
| MCS | — | — | **未实现** | 仅敏感性计划 |
| Romano–Wolf | — | — | **未实现** | FWER 备选 |
| Harvey–Liu–Zhu | 注册表 + 试验计数哲学 | `research_registry`, DSR N | 流程 | 非单函数门槛 |

## 配置旋钮（只读摘要）

| 配置 | 默认/示例 | 文件 |
|---|---|---|
| `factor_fdr_level` | 0.10 | `factor_config`, `long_horizon_config` |
| `bootstrap_samples` | long-horizon 20000；factor 路径可更低 | 同上 |
| `bootstrap_block_days` | 63 | long_horizon |
| `bootstrap_block_bars` | 20（CFTC 验证周需更大） | factor_config |
| SPA `expected_block_length` | 63 | `hansen_spa_test` |
| SPA `reps` | 50000 | `hansen_spa_test` |
| CSCV blocks | 16 固定 | `CSCV_BLOCK_COUNT` |

## 端到端缺口

1. **正式 SPA 未串联**：`hansen_spa_test` 存在，但 `portfolio_validation_runner` / `intraday_validation` 只准备输入并写 `spa_executed=False`。
2. **成本门**：`broker_cost_contract.audit_cost_coverage` → 常 `cost_incomplete_research_only`，`formal_net_returns_ready=False` 硬编码倾向。
3. **arch 不可作主 SPA**：见 `docs/OPEN_SOURCE_SELECTION_ZH.md`。
4. **历史搜索 N**：文献地图称既往约 3,312 次搜索；DSR 必须显式并入，不能靠当前矩阵列数。

## 推荐诊断顺序（研究，非交易批准）

```text
完整候选净收益矩阵（共同 UTC 日）
    → BH（主）+ BY（敏）
    → DSR（完整 N）
    → PBO/CSCV（16 块）
    → hansen_spa_test（studentized；接通后）
    → 冻结后新 3–6 月 forward evidence
```
