# [Menkhoff, Sarno, Schmeling & Schrimpf 2017] Currency Value

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1093/rfs/hhw067
- 开放获取: City OA https://openaccess.city.ac.uk/id/eprint/14851/13/FXVALUE_Rev3_cepr.pdf
- 本项目映射: REER/价值偏离；BIS REER current-vintage 边界
- 复制状态: extension_only（REER vintage / 宏观 fundamentals）
- 公式置信度: high（accepted manuscript）
- published premium vs implementable: 简单价值 Sharpe~0.5；宏观调整后~0.8–0.9（降波）；零售执行未测
- 2016–2025 外推: 中高；PPP 回归慢、宏观数据修订与 vintage 污染关键

## 1. 经济机制

实际汇率（RER）的现值分解：RER 反映**预期货币风险溢价**、**预期实际利差**与可能非 1 的长期均值。直接用 RER 水平/长期变化作“便宜/贵”信号会混入宏观基本面（生产率 HBS、出口质量、NFA、产出缺口）。剥离这些后，残差价值信号更贴近风险溢价，横截面预测更强、波动更低。

## 2. 精确公式

```text
# 注意：文中 Q 为实际汇率（定义使表述方便）；名义 S 较高=外币更贵
# 超额收益与 RER（示意，见文 Eq.2–4）
rx_{t+1} = -(q_{t+1}-q_t) + (ri*_t - ri_t)   # 实际利率形式
q_t = sum_h E_t[rx_{t+h}] - E_t[ri* - ri] + E_t[q_{∞}]

# 基准价值信号：5 年对数 RER 变化
Δ^(5y) q_{j,t} = q_{j,t} - q_{j,t-5y}

# 线性权重组合（季度再平衡）
w_{j,t+1} = c_t * (x_{j,t} - x̄_t)
c_t = 1 / sum_j |x_{j,t} - x̄_t|
# x = Δ^(5y)q 或残差价值；高于截面均值 → 正权重
rx^p_{t+1} = sum_j w_{j,t+1} rx_{j,t+1}

# 宏观调整（每季横截面回归）
Δ^(5y) q_{j,t} = α_t + β_t' X_{j,t} + ε^q_{j,t}
# X: 生产率/HBS、出口质量、NFA、产出缺口（水平或期望代理）
# 交易信号用残差 ε^q（更纯的 risk-premium 价值）
# 期望代理：EWMA (φ=0.98) 或国家/面板 VAR 迭代
```

亦报告 rank 组合。预测回归含时间固定效应与控制。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 23 经济体 / 22 对 USD 汇率 |
| 频率 | 季度 |
| 样本起止 | 1970Q1–2014Q1（宏观+FX） |
| 来源 | Global Financial Database 等；宏观 fundamentals 多源 |
| 再平衡 | 季度末 |

## 4. 成本与可实现性

- 原文：组合权重与预测；交易成本非主表核心
- 迁移破坏点：
  - **BIS REER current-vintage** 回填修订 → 历史信号不可 PIT
  - 宏观 X 的发布滞后与修订
  - 季度信号 vs 项目 1–3 月持有需扩展规则
- published Sharpe 改善主要来自**降波**而非抬收益

## 5. 识别与稳健性

- 简单 5y RER 价值：显著正超额，Sharpe ~0.5
- 残差价值：Sharpe 升至 ~0.8–0.9
- 与 carry、momentum 信息不同
- 控制 fundamentals 后预测更持久（多年 horizon）

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| PIT REER / 实际汇率 | 是 | BIS 多为 current vintage | **extension + 新前向**；严格 PIT fail closed |
| 5 年窗口 q_t - q_{t-5y} | 是 | 可算若有历史 | 样本长度 |
| 宏观 X 与发布日 | 调整版需要 | 不完整 | 仅用原始 REER 扩展 |
| 季度权重/rank | 是 | 可 | — |
| FX 超额收益（含利差） | 是 | forward 缺 | spot 近似 extension |

## 7. 本项目映射

- registry：currency value / REER
- 持有期：季度信号；项目月度/日度决策需冻结映射
- 否决：把 current-vintage REER 当严格 PIT 主证据；宏观调整网格事后挑选
- reused-history：是

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Asness, Moskowitz & Pedersen (2013) | 5y 价值定义参照 |
| theory | Engel & West；Froot & Ramadorai | 现值/宏观 |
| parallel | Menkhoff et al. momentum | 同作者链 |
| imbalance | Della Corte, Riddiough & Sarno | 外部失衡 |

## 9. 精读问题

1. 无 as-published CPI/REER 时，5y 变化信号的修订误差有多大？
2. G9 上线性权重 vs 3 分位排序的换手差异？
3. 残差价值是否在 2016–2025 仍独立于 carry？
4. 产出缺口实时估计（output gap）是否引入巨大前视？
5. 价值与动量 agreement gate 是否构成未注册组合规格？
