# ECB CISS (Composite Indicator of Systemic Stress)

- 深度层级: L2
- 角色: data_contract
- 快照:
  - `research/_html_snapshots/ecb_ciss.html`（优先 data-information；若拉取失败则可能为门户/工作论文列表——以文件内 title 为准）
  - 相关: `ecb_data_portal.html`, `ecb_ciss_info.html`, `ecb_ciss_portal.html`（若存在）
- 官方入口:
  - Dataset: https://data.ecb.europa.eu/data/datasets/CISS
  - Info: https://data.ecb.europa.eu/data/datasets/ciss/data-information
  - 方法论文: Holló, Kremer, Lo Duca, ECB WP 1426

## Allowed use

- 欧元区（及变体）**系统性压力** 状态变量
- New CISS / classic CISS / SovCISS 等变体的 **regime 分层**
- 与 OFR FSI、NFCI 交叉验证压力度量

## Forbidden inference

- **非** FX 横截面方向信号
- 综合指标 **不可** 拆成“可交易子策略”除非对每个成分有独立数据合同
- 禁止把 CISS 上升直接解释为“做多美元”等单一方向故事而不做样本外与多重检验

## PIT / vintage

| 项 | 状态 |
|---|---|
| 频率 | classic 常周度更新；New CISS 偏日度（以门户元数据为准） |
| 修订 | 成分修订可能回写；`current` |
| PIT | 无本地按日归档时 `pit_status=current_release` |

## 字段提示

```text
# 例（系列码以 ECB 门户为准）
KEY ≈ CISS.D.U2.... 或文档中的 SS_CI / SS_CIN
date, series_key, value, freq, geo
```

## 本项目映射

- 风险状态；危机窗
- 不进入主 alpha 注册表 unless 预注册为状态过滤
