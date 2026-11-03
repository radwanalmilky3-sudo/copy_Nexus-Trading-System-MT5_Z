# 免费严格 PIT 数据下一步路线

日期：2026-07-19。范围：只读本地盘点，不读取价格收益。

## 优先级

1. **央行政策事件控制**：现有 FED/ECB 时间戳完整子集已经抽出 161 行（FED 81、ECB 80），
   可作为 EURUSD announcement-risk blackout 候选。ECB 另有 2 行 date-only 非例行事件被
   排除。BOE 适配器仍为 0 行，因此 GBPUSD 尚不能获得对称 FED/BOE 控制；下一步优先补 BOE
   官方历史适配器。
2. **Treasury TIC 月度发布档案**：本机已有 2016–2025 的 120/120 ZIP，原始约 327 MB。
   `npr_history` 已完成 120 vintage 与 119 次相邻修订审计；`tressect` 又完成 87 个 vintage、
   86 次相邻修订审计，已物化为严格 PIT 的低频 USD funding/foreign-demand 状态候选。其他
   系列仍保持 parser-pending；`tressect` 尚未成为方向因子或收益检验对象。详见
   `docs/TREASURY_TIC_TRESSECT_AUDIT_ZH.md`。
3. **OECD Economic Outlook 历史版次**：目标 EO99–EO118、八个货币经济体、五个窄频变量，
   预计不到 1 MiB。当前首请求遇到 HTTP 429；应从获准网络/VPS 低频重试，保存每版原始响应、
   官方发布日期和 composition break（EA15/16/17），不能盲接欧元区口径。
4. **ONS UK GDP real-time editions**：ABMI/YBHA 目录各 78 edition，共 156 个工作簿、目录估算
   约 89 MB（缓存与归档约 170 MiB），OGL v3。必须从工作簿内解析原始发布日期；edition 页
   重复的最新日期不能冒充历史 available time。先做可证明日期的严格子集。
5. **ECB SPF 逐季附件**：本地已有 2018-Q3 至 2025-Q4 的 30/40 季度和约 47 MiB 附件；
   2016-Q1 至 2018-Q2 缺 10 季。先验证逐季附件 hash、真实发布日期和 revision behavior，
   不用当前 consolidated forecasts 冒充 as-published vintage。
6. **ALFRED**：CPI、工业生产以外可补 PAYEMS、UNRATE、GDPC1 vintage，但需要免费
   `FRED_API_KEY`，且查询时间本身不能证明原始 release clock。优先级低于本机已完整归档的
   TIC，也与 RTDSM 部分重叠。

## 暂不升级

- BIS GLI/LBS 是 current snapshot，不是 release vintage；
- CFTC TFF/BPR/weekly swaps 是 current/revised、403 部分或非方向活动量；
- 官方政策/隔夜利率、商品、风险和 REER 当前历史不能通过增加人为滞后变成 strict PIT；
- OANDA financing 是 broker-specific 且历史较短，不属于 broker-neutral 因子发现层。

所有新增来源必须先登记 source view、原始/manifest SHA、row-level eligibility 和 prefix canary，
再单独预注册因子家族；不得加入第一层 48 个假设。

```text
return_labels_opened=false
factor_outcome_evaluations_added=0
trading_approval=false
```
