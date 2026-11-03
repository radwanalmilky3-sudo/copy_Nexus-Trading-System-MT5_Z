# NY Fed Markets Data APIs

- 深度层级: L2
- 角色: data_contract
- 快照: `research/_html_snapshots/nyfed_markets_api.html`
- 官方入口: https://markets.newyorkfed.org/static/docs/markets-api.html

## Allowed use

- 纽约联储市场操作与相关 **官方公开市场数据**（以 API 目录为准：repo、SOMA、primary dealer 统计等）
- **负对照 / 状态变量**（例如 dealer 综合头寸类序列——若在 API 覆盖内）
- 资金市场压力与政策实施微观结构（机构语境）

## Forbidden inference

- Primary dealer **合计** ≠ 可交易 FX 订单流
- 2016–2025 样本上 **不得默认** 当作 G9 日度方向 alpha 源
- 非零售成交价；非 Dukascopy 替代

## PIT / vintage

| 项 | 状态 |
|---|---|
| 发布 | 各端点自有频率（常周度/日度） |
| PIT | 多为 **aggregate 现档**；修订政策按序列文档 |
| 默认 | `pit_status=current_release` unless endpoint documents revisions + local archive |

## 字段提示

```text
endpoint, asof_date, series_id, value, unit, download_ts
```

## 本项目映射

- 负对照与机制；资金面状态
- 与 `06_broker_costs` CIP/basis 文献对照时作宏观融资背景
