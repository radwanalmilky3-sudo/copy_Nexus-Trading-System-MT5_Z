# [Benjamini & Hochberg 1995] Controlling the False Discovery Rate

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1111/j.2517-6161.1995.tb02031.x
- 开放获取: 期刊页；方法已成为标准算法（教科书复述合法）
- 本项目映射: `benjamini_hochberg`；每折主 FDR 门槛
- 复制状态: exact_possible（对给定 p 向量）

## 1. 经济机制

多重检验中“假阳性比例”比 family-wise error 更贴合因子搜索：研究者愿意容忍少量假发现，但要控制期望中的假发现率。FX 实验室在同一折内同时筛几十到上百个候选时，若不控制 FDR，挑出的“显著”因子几乎必然含数据挖掘伪迹。

## 2. 精确公式

设有 \(m\) 个假设，原始 p 值排序 \(p_{(1)}\le\cdots\le p_{(m)}\)。在水平 \(q\in(0,1]\) 下：

```text
BH step-up:
  找最大 k 使 p_(k) ≤ (k/m) * q
  拒绝 H_(1),...,H_(k)（若存在）

adjusted q-value（项目实现）:
  q_(i) = min_{j≥i} ( m / j * p_(j) )   # 从大到小 running min，再 clip 到 [0,1]
  拒绝当 q_i ≤ q
```

在独立性或 PRDS（positive regression dependence on subset）下，该程序控制 FDR ≤ q。

**与 bootstrap 分辨率的耦合（项目硬约束）：**

经验 p 采用 plus-one：

```text
p = (k + 1) / (B + 1) ≥ 1/(B+1)
```

要让“最强”假设有可能跨过第一条 BH 线 \(q/m\)，需要：

```text
1/(B+1) ≤ q/m
⇔  B ≥ ceil(m/q) - 1
```

v4：`m=129, q=0.10` → `B ≥ 1289`；项目配置 `bootstrap_samples=20_000`。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 对象 | 任意多重检验 p 值族 |
| 频率 | 与检验构造无关 |
| 样本起止 | 方法论文；无市场样本 |
| 价格/远期/利率来源 | 不适用 |
| 排序与再平衡 | p 值升序排序 |

## 4. 成本与可实现性

- 原文扣除：none（统计程序）
- 迁移到零售 bid/ask + 账户 swap 后的破坏点：若 p 值来自毛收益或 midquote，FDR 只控制“毛收益假发现”，不能证明净收益可交易。
- midquote premium ≠ implementable net：FDR 通过 ≠ 净 PnL 通过。

## 5. 识别与稳健性

- 主结果：在独立性/PRDS 下 FDR 控制。
- 任意相关：需 BY 或重采样-FDR。
- 已知失败：分母 m 少计（只报入选因子）会系统性地过松；事后改族破坏注册。

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 完整假设数 m | 是 | 注册表 + 生成候选计数 | fail closed |
| 每个假设 p 值 | 是 | bootstrap p | fail closed |
| q 水平 | 是 | `factor_fdr_level` 默认 0.10 | 配置 |
| B 分辨率 | 是 | `minimum_resamples_for_fdr` | 拒绝运行 |

## 7. 本项目映射

- 符号：`src/fx_system/statistical_validation.py::benjamini_hochberg`
- 调用：`factor_research.py`、`long_horizon_research.py`、`intraday_validation.py`
- 主门槛字段：`fdr_q_value`、`fdr_significant`；`primary_fdr="BH"`
- 否决条件：未达 `B≥ceil(m/q)-1` 且 `require_fdr_significance` 时拒绝；p 来自未扣融资净收益时不得晋级
- reused-history：同一 2016–2025 反复查看后，即使 q 仍显著，仍要求冻结后新前向期

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Benjamini & Hochberg (1995) | FDR 定义与 BH 步骤 |
| critique/extension | Benjamini & Yekutieli (2001) | 任意相关 |
| boundary | Harvey–Liu–Zhu (2016) | 因子动物园与更高门槛 |

## 9. 精读问题（给最强模型）

1. 本项目横截面 IC / 配对收益在折内是否满足 PRDS？若不满足，BY 敏感性应如何进入晋级门槛？
2. 生成式 DSL 候选是否全部计入 m，还是只计“通过 canary 的子集”？
3. 多折 walk-forward 中“每折独立 BH”与“全局试验账本”如何同时不低估搜索暴露？
