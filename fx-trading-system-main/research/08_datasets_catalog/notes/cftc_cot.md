# CFTC Commitments of Traders (COT) / TFF

- 深度层级: L2
- 角色: data_contract
- 快照: `research/_html_snapshots/cftc_cot.html`
- 官方入口: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm

## Allowed use

- 期货/期权分类持仓的 **拥挤度 / 定位** 探索（currency futures 等）
- 周度状态变量；与价格趋势对照的描述统计
- TFF（Traders in Financial Futures）等报告变体（字段不同，勿混表）

## Forbidden inference

- **非** 即期 FX 订单流；期货持仓 ≠ 即期银行间流
- **非** 完整 as-published 事件时钟，除非使用 **release calendar + 首次发布档**
- 禁止把“非商业净多”直接当无成本可交易 alpha 而不处理发布滞后与多重测试
- 合约切换、option 并入规则变更时禁止无断点拼接

## PIT / vintage

| 项 | 状态 |
|---|---|
| 频率 | 周度（报告与发布日不同） |
| 关键 | `report_date` vs `release_datetime` |
| PIT | 近似可得；**严格**需 release calendar + 首发快照 |
| 本项目 | 已有 CFTC 相关代码/审计文档语境 → 对齐 `release` 而非 `asof_report` 误用 |

```text
report_date, release_date, market_code, trader_category, long, short, spreading, open_interest
pit_join_key = release_date  # for decisioning
```

## 本项目映射

- 拥挤探索；`factors_broker_carry_cftc_exploratory` 类配置
- 否决：把 COT 当 tick 级知情交易
