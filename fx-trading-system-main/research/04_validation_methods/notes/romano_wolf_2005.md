# [Romano & Wolf 2005] Stepwise Multiple Testing

- 深度层级: L5
- 引用链角色: boundary
- DOI/URL: https://doi.org/10.1111/j.1468-0262.2005.00615
- 开放获取: Econometrica；作者稿常见
- 本项目映射: 多策略 FWER 备选；**无生产实现**
- 复制状态: extension_only

## 1. 经济机制

当目标是控制 **family-wise error**（至少一个假阳性的概率）并可能识别多个优于基准的策略时，逐步（stepwise）方法比单步 Bonferroni 更有功效，又比 FDR 更严。适合“要从家族中点名多个可交易规则”的监管式披露；本 lab 当前主路径是 FDR+SPA 诊断。

## 2. 精确公式（概念）

```text
H_k: E[d_k] ≤ 0  # 模型 k 不优于基准

逐步:
  1. 对当前存活假设计算 studentized 统计量
  2. 用 bootstrap 得共同 max 分位临界值
  3. 拒绝最极端者后，对剩余集合重算临界值
  4. 直至无人拒绝

控制 FWER ≤ α
```

## 3. 数据与样本

需要与 SPA 相同的共同日期相对绩效面板 + 同步 bootstrap。

## 4. 成本与可实现性

- 输入必须是净可实现相对收益
- FWER 通过仍受融资合同约束

## 5. 识别与稳健性

- 比 FDR 保守；假阴性更多
- 项目：仅 catalog 备选

## 6. 复制清单

| 字段 | 需要？ | 本项目 | 缺失时 |
|---|---|---|---|
| 共同净收益 | 是 | 有 | — |
| RW 算法 | 是 | 无 | extension_only |

## 7. 本项目映射

- 文献地图列为将来多策略识别备选
- 不替代 BH 主门槛

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| FWER | Romano–Wolf | stepwise MTP |
| FDR | BH/BY | 更松主路径 |
| SPA | Hansen | 家族相对基准 |

## 9. 精读问题

1. 在 m=129 时 FWER 是否过严导致空模型成为唯一结果？
2. 与 SPA 的逻辑顺序？
3. studentized RW 与项目 SPA LRV 能否共享？
