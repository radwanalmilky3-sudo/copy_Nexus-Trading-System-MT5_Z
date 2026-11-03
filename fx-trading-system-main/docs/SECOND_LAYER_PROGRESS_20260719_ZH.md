# 第二层推进报告（2026-07-19）

本阶段完成 Treasury TIC `tressect` 的严格 point-in-time 数据准备，没有打开价格收益标签。

## 已完成

- 120/120 官方 TIC ZIP、成员目录和 catalog SHA-256 继续通过。
- `tressect.txt` 在 87 个版本中存在；全部验证为 UTF-8、四列、百万美元单位、连续倒序月度
  历史，最早到 `1978-01`。
- 总额与三项分解的显示舍入残差严格限制在 `[-1, +1]` 百万美元；更大误差失败关闭。
- 87 个 release vintage 与 86 次相邻 revision transition 已物化；每次新增 1 月、删除 0 月、
  schema 变化 0 次；共有 117 条跨版本月份修订记录、282 个单元格变化。
- 生成 `treasury_tic_tressect_vintages` source view，normalized 数据 43,326 行，并保存
  独立 manifest、审计输出哈希和 normalized SHA-256。
- 外部数据源资格审计更新为 13/13 完整；正式 regime source 增加 Treasury TIC `tressect`。

## 尚未做

- 没有把 TIC 流量变成方向 alpha；没有新增 factor definition、FDR family 或收益评估。
- 没有把 2023-04 之后不存在的 `tressect` 记录人工延长或 forward-fill。
- `npr_history` 和 `tressect` 虽都完成 parser/revision audit，仍属于研究输入；任何使用都要
  另行预注册状态公式、staleness、缺失和交互家族。

## 可复核入口

```text
scripts/audit_treasury_tic_revisions.py
scripts/materialize_treasury_tic_tressect.py
tests/test_treasury_tic_revision_audit.py
tests/test_treasury_tic_tressect_materializer.py
docs/TREASURY_TIC_TRESSECT_AUDIT_ZH.md
outputs/treasury_tic_revision_audit/audit_manifest.json
data/treasury_tic/normalized/tressect_manifest.json
outputs/external_factor_eligibility_20260719/source_audit.json
```

安全状态：

```text
return_labels_opened=false
factor_outcome_evaluations_added=0
formal_net_returns_ready=false
trading_approval=false
```
