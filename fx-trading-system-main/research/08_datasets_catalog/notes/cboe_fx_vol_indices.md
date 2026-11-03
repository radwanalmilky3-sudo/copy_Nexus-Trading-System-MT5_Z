# Cboe FX / Currency Volatility Indices (EVZ, EUVIX, JYVIX, BPVIX)

- 深度层级: L2
- 角色: data_contract
- 快照: `research/_html_snapshots/cboe_evz.html`, `cboe_euvix.html`, `cboe_jyvix.html`, `cboe_bpvix.html`
- 官方入口:
  - EVZ: https://www.cboe.com/us/indices/dashboard/evz/
  - EUVIX: https://www.cboe.com/us/indices/dashboard/euvix/
  - JYVIX: https://www.cboe.com/us/indices/dashboard/jyvix/
  - BPVIX: https://www.cboe.com/us/indices/dashboard/bpvix/
- 附加: EVZ 停用咨询结果 PDF 快照 `cboe_evz_cessation_notice.pdf`（2025-01 起停发语境）

## Allowed use

- **风险状态 / 波动环境** 协变量（按指数覆盖的币种或 ETF 期权隐含波动）
- 事件窗分层：高/低 IV 状态
- 与已实现波动对照做 **描述性** VRP 风格探索（需自建 RV；且覆盖有限）

## Forbidden inference

- **非** G9/G10 全截面 1M/1Y VRP 面板
- **非** 可交易 VIX 期货/期权收益（除非另有合约与成本数据）
- **非** 方向性汇率 alpha 的充分统计量
- EVZ：停发后不得假装有连续实时官方更新；历史段须标 `series_status=ceased`

## PIT / vintage

| 项 | 状态 |
|---|---|
| 发布 | 通常日度指数水平（以 Cboe 发布为准） |
| 修订 | 指数方法论变更需记录 effective date |
| as-published 全链 | **无严格 vintage 库**；现档下载 = current methodology view of history |
| 研究默认 | `pit_status = current_release`；禁止声称 strict ALFRED-style vintage |

## 字段提示

```text
date, index_id ∈ {EVZ, EUVIX, JYVIX, BPVIX}, level, source=cboe, asof_download_ts
```

## 本项目映射

- 三币种/有限币种 **风险状态袖套**，不是横截面波动因子宇宙
- 与 `02_factor_literature` 中 VRP 文献：仅 extension，非 exact replication
