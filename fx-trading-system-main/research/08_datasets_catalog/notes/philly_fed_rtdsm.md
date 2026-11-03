# Philadelphia Fed Real-Time Data Set for Macroeconomists (RTDSM)

- 深度层级: L2
- 角色: data_contract
- 快照: `research/_html_snapshots/philly_rtdsm.html`
- 官方入口: https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists

## Allowed use

- **宏观变量 vintage / as-of** 研究（美国）
- 真实时点可得 GDP、通胀、就业等路径的复制
- 宏观状态过滤的 **严格 PIT** 候选主源之一

## Forbidden inference

- **非** 公告时钟 surprise（缺 consensus/预期）
- 非全球宏观面板（以 RTDSM 覆盖为准，主要美国）
- 禁止用 latest vintage 回填历史决策点

## PIT / vintage

| 项 | 状态 |
|---|---|
| PIT | **强**：按 vintage 日期组织 |
| 正确用法 | 决策日 `t` 只用 `vintage <= t` 的观测 |
| 错误用法 | 最终修订值假装实时 |

```text
required_keys: series_id, observation_date, vintage_date, value
pit_status = strict_vintage when joined on vintage_date
```

## 本项目映射

- 美宏观状态；与 ALFRED 互补
- 已有项目语境：可作为 as-of 严格源
