# [Politis & Romano 1994] The Stationary Bootstrap

- 深度层级: L5
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1080/01621459.1994.10476870
- 开放获取: JASA；方法标准复述
- 本项目映射: `joint_stationary_bootstrap_indices`；SPA 内 `_stationary_bootstrap_indices`
- 复制状态: exact_possible（算法级）

## 1. 经济机制

金融日收益有序列相关与波动聚类。IID bootstrap 破坏时间依赖，使均值/夏普/SPA 的 null 过窄。Stationary bootstrap 用随机几何长度块重采样，使 bootstrap 序列仍近似平稳，并在同步抽行时保留多候选横截面相关——这是联合多重检验的基础设施。

## 2. 精确公式

期望块长 \(\ell\)，重启概率 \(p=1/\ell\)。

```text
路径生成（项目 joint 版）:
  I_0 ~ Uniform{0,...,n-1}
  for t=1..n-1:
    with prob p: I_t ~ Uniform{0,...,n-1}   # 新块
    else:        I_t = (I_{t-1} + 1) mod n  # 延续（环形）

对 panel X (n×m)：
  所有列共用同一 I 路径 → 同步日期重采样
  禁止按列独立 bootstrap
```

几何块长：\(P(L=k)=p(1-p)^{k-1}\)，\(E[L]=\ell\)。

固定长度 circular block bootstrap 是姐妹方法（项目：`joint_circular_block_bootstrap_indices`）。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 对象 | 平稳弱依赖时间序列 |
| 频率 | 任意规则网格 |
| 样本 | n 应 ≫ ℓ |
| 来源 | 数值序列 |
| 排序 | 时间顺序块 |

## 4. 成本与可实现性

- 方法不涉及成本
- 若序列是 mid 收益，bootstrap 只传播 mid 不确定性
- 项目要求：bootstrap 作用在 **净收益共同日期矩阵** 上

## 5. 识别与稳健性

- 主结果：对平稳过程 bootstrap 一致性（适当 ℓ 增长）
- 块长选择：过短 → 低估依赖；过长 → 方差爆炸
- 项目默认：日级 `bootstrap_block_days=63`；bar 级 `bootstrap_block_bars`；SPA `expected_block_length=63`
- 已知失败：列独立重采样破坏因子横截面相关 → 假 FDR/SPA

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| n, B, ℓ | 是 | 配置 + 函数参数 | fail closed |
| 同步 indices | 是 | joint_* 函数 | 禁止自制独立路径 |
| 环形边界 | 是 | mod n | 与实现一致 |

## 7. 本项目映射

- `statistical_validation.joint_stationary_bootstrap_indices`
- `statistical_validation.joint_circular_block_bootstrap_indices`
- `hansen_spa._stationary_bootstrap_indices`（批量路径，固定 seed 可复现）
- `intraday_validation`：`resampling=joint_stationary_bootstrap_event_date_rows`
- factor 路径另有 moving-block rank test（`_block_bootstrap_rank_test`）

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Politis–Romano (1994) | stationary bootstrap |
| application | White (2000), Hansen (2005) | RC/SPA 重采样 |
| boundary | 固定块 / circular block | 敏感性 |

## 9. 精读问题

1. 重叠持有期收益的 MA 结构下，ℓ=63 是否系统偏短？
2. 环形拼接在样本两端危机窗是否扭曲极端分位？
3. SPA 的 LRV 权重与路径生成是否使用同一 p？
