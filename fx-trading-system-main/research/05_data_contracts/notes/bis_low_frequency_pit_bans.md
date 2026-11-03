# [BIS GLI / LBS / OTC / Triennial] 低频统计：允许与禁止

- 深度层级: L3–L4
- 引用链角色: data_contract
- DOI/URL:
  - GLI https://data.bis.org/topics/GLI
  - LBS https://data.bis.org/topics/LBS
  - OTC https://data.bis.org/topics/OTC_DER
  - Triennial https://www.bis.org/statistics/rpfx22.htm
- 开放获取: 是
- 本项目映射: 发布后低频风险状态 / 结构校准；**永不**作 G9 日方向
- 复制状态: 机制 only；strict_pit_eligible=false（无 full as-published 链）

## 1. 经济机制

BIS 统计描述全球美元/欧元/日元信贷、跨境银行头寸、OTC 衍生品存量与三年一度市场结构。它们解释**融资环境与市场厚度**，不提供可交易的日度货币 foresight。

## 2. 合同

```text
if series is BIS quarterly/semiannual/triennial:
    use only after official release_time
    decision_time >= next_conservative_decision_day(release_time)
    forbid: map(ΔGLI_USD_credit → long/short EURUSD tomorrow)
    forbid: treat LBS claims as order flow
    forbid: FX-translate OTC notionals into spot alpha
```

## 3. 分项

| 产品 | 频率 | 内容 | 允许 | 禁止 |
|---|---|---|---|---|
| GLI | Q | 非居民 USD/EUR/JPY 信贷等 | funding 压力分层 | 日方向 |
| LBS | Q | 跨境头寸、币种/国家 | break/coverage 审计 | 日资金流 |
| OTC | SA | 名义/市值/暴露 | 集中度机制 | 存量变→即期 |
| Triennial | 3Y | 成交额结构 | 流动性假设校准 | 时间序列调参 |

## 4. PIT

未保存每次历史发布 raw 响应前，2016–2025 回填默认 `strict_pit_eligible=false`。从现在起按发布日存档可形成 forward-strict 自建 vintage。

## 5. 本项目映射

- 不增加方向候选或 FDR 分母
- 可作预注册风险状态的外生条件（须先登记）

## 6. 精读问题

1. GLI 发布日与 reference quarter 的最小安全 lag？
2. LBS break-adjusted 与 unadjusted 混用的错误模式？
3. Triennial 2022→2025 结构变化如何写入流动性假设而不数据挖掘？
