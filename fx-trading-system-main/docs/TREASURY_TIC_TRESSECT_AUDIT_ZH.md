# Treasury TIC `tressect` 严格 PIT 审计

日期：2026-07-19。

## 结论

2016–2025 官方 Treasury TIC 发布档案共 120 个 ZIP，全部通过 ZIP、成员目录和输入 catalog
SHA-256 校验。`tressect.txt` 在其中 87 个发布版本（2016-01-19 至 2023-03-15）中存在，已完成
固定 schema 解析与相邻版本修订审计；其余 33 个版本没有该历史表，不做人工延长或回填。

机器产物：

```text
outputs/treasury_tic_revision_audit/tressect_vintages.csv
outputs/treasury_tic_revision_audit/tressect_revision_summary.csv
data/treasury_tic/normalized/tressect_vintages.csv
data/treasury_tic/normalized/tressect_manifest.json
```

## Schema 合同

- UTF-8 `tressect.txt`；所有 87 个版本均为四个整数列；单位是百万美元。
- 列分别为：总外国净购买、外国官方机构、其他外国人、国际与区域组织。
- 每个 vintage 从最新参考月严格倒序到 `1978-01`，月份连续、无重复、无缺失。
- 总额与三个分项允许最多 1 百万美元显示舍入残差；观测到的残差只有 `-1/0/+1`，超过 1
  即失败关闭。
- 每个版本的最新观测与该发布的 TIC reference month 一致；`available_time` 为官方发布日期
  后的下一个 UTC 日边界。

## 修订审计

- 87 个 vintage、86 次相邻转换、43,326 行 release-vintage 观测。
- 每次转换新增恰好 1 个月、删除 0 个月、schema 改变 0 次。
- 相邻版本中共有 117 条 `release-transition × observation-period` 修订记录、282 个单元格变化；
  最远修订年龄为 45 个月。
- 因此下游必须按 as-published vintage 做 backward as-of join，不能把最后版本历史回填到早期
  决策日。

## 资格边界

该 source view 已登记为 `verified_strict_pit`，允许作为低频 USD funding/foreign-demand
状态候选，并写入 `configs/external_factor_source_registry.yaml`。它尚未登记为方向因子，未
加入任何收益检验、第一层 16 因子/48 假设或 FDR 家族。它也不代表已发现盈利策略。

```text
formal_factor_registered=false
return_labels_opened=false
factor_outcome_evaluations_added=0
trading_approval=false
```

下一步若使用该 source view，必须另行预注册状态交互、staleness、缺失处理和多重检验；不得
因为它通过数据资格审计就直接解释为美元方向 alpha。
