# [Harvey, Liu & Zhu 2016] … and the Cross-Section of Expected Returns

- 深度层级: L5
- 引用链角色: foundational / boundary
- DOI/URL: https://doi.org/10.1111/jofi.12883 ；RFS 2016；NBER w20592
- 开放获取: https://www.nber.org/system/files/working_papers/w20592/w20592.pdf ；作者 https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF
- 本项目映射: 搜索账本 + 提高新因子证据门槛；非单一函数
- 复制状态: extension_only（门槛哲学与披露；非股票因子动物园复刻）

## 1. 经济机制

学术界已测试数百个解释截面收益的因子。标准 \(t>2\) 在多重检验下过松，导致大量“显著”假因子。正确的研究生产函数是：公开尝试次数、相关结构与历史门槛，对新因子要求更高的 t / 更严的多重检验。对本 FX lab：每一次 DSL 生成、窗口网格、成本压力倍率都是尝试。

## 2. 精确公式

多重检验下的显著性门槛（概念）：

```text
# 历史累计因子数 M_t 上升时，单因子 |t| 门槛 τ(M) 上升
# 文中经验规则：新因子应接近 |t| > 3（视相关与缺失测试调整）

# Bonferroni 式极端保守:
τ_Bonf ≈ Φ^{-1}(1 - α/(2M))

# 更精细：考虑因子相关、未发表测试（file drawer）
# 本文用多种 multiple-testing 调整给出时间路径上的 cutoff
```

与项目工具栈对齐（非原文公式）：

```text
完整试验数 N_total = 注册表全部假设 + 生成候选 + 废弃轮次
BH/BY: m = 当折统一检验族大小
DSR: total_trials_evaluated = N_total
SPA: 仅校正传入矩阵列 ⊂ N_total  ⇒ 必须另文披露其余暴露
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产 | 股票因子动物园元研究 |
| 频率 | 月截面为主 |
| 样本 | 文献累计至写作时 |
| 来源 | 已发表因子列表 |
| 排序 | 因子 t 统计量 |

## 4. 成本与可实现性

- 原文多为纸面因子，成本处理不一
- 迁移：FX 零售实现必须在“更高统计门槛”之外再过 bid/ask+swap 关
- 高 t 的 mid 因子在融资后可为负

## 5. 识别与稳健性

- 主结果：多数已发表因子在合理多重检验下不可信；新因子门槛上移
- 子样本：随时间尝试增多门槛升高
- 本项目：v4 等轮次的 m、历史搜索次数必须进账本

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 全部尝试列表 | 是 | `configs/factor_research_registry.yaml` | fail closed 披露 |
| 每尝试经济机制 | 是 | 注册表字段 | 不得裸网格 |
| 相关/家族结构 | 建议 | 部分（DSL 谱系） | 敏感性 |
| 新前向证据 | 是 | `fresh_forward_required` | 否决晋级 |

## 7. 本项目映射

- 无 `harvey_threshold()` 函数；体现在：
  - `research_registry` 审计
  - DSR `total_trials_evaluated`
  - FDR 分母含生成因子
  - 文献地图要求 reused-history + 新 holdout
- 否决：看完 2016–2025 结果再加因子却不增加 N

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Harvey–Liu–Zhu | 因子动物园门槛 |
| tools | BH/BY, DSR, PBO, SPA | 可操作多重检验 |
| boundary | 本项目 cost_incomplete | 统计门槛必要非充分 |

## 9. 精读问题

1. FX 因子相关结构下，t>3 规则应如何换算为日净收益 DSR/BH？
2. 未发表内部尝试如何进入 M 而不泄露未来选择？
3. “机制预注册”能否部分替代纯多重检验惩罚？
