# BIS REER / GLI / LBS

- 深度层级: L2
- 角色: data_contract
- 快照:
  - REER/EER: `research/_html_snapshots/bis_reer.html` ← https://www.bis.org/statistics/eer.htm
  - GLI: `bis_gli.html` ← https://data.bis.org/topics/GLI
  - LBS: `bis_lbs.html` ← https://www.bis.org/statistics/bankstats.htm （locational banking）

## Allowed use

| 数据集 | 允许 |
|---|---|
| REER/EER | 实际/名义有效汇率；**value / PPP 偏离类** 探索、低频机制 |
| GLI | 全球流动性、美元信用周期状态（季度/低频） |
| LBS | 跨境银行债权/负债结构；美元融资/外币负债机制 |

## Forbidden inference

- **非** G9 日度方向 alpha 信号源
- REER **current vintage** ≠ 实时决策时点可得的 as-published 路径（除非自建 vintage）
- GLI/LBS **非** 订单流；不可替代 CFTC 或微观成交
- 权重与基期变更时禁止无断点拼接“无缝长期因子”

## PIT / vintage

| 数据集 | PIT |
|---|---|
| REER | 月度；BIS 会修订；默认 `current`；strict PIT 需自建下载档案 |
| GLI | 低频；修订常见；`current` |
| LBS | 季度等；概念/ residual 调整；`current` |

```text
pit_status default = current_release
strict_as_published = false unless local snapshot archive by download_date
```

## 字段提示

```text
# REER
ref_month, currency_area, broad_or_narrow, neer_or_reer, index_level, base_period

# GLI
period, indicator_id, unit, value

# LBS
period, reporting_country, counterparty, currency, claim_type, position
```

## 本项目映射

- value 因子：REER 对齐月度再平衡（探索）
- 机制/负对照：GLI、LBS 状态变量
- 否决：把季度 LBS 插值成日度交易信号并声称可实现
