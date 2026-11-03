# [OANDA] Financing / Swap 官方文档与导出边界

- 深度层级: L4
- 引用链角色: data_contract
- DOI/URL: 见下表官方链
- 开放获取: 官网文档 **是**；完整 2016–2025 账户史 **否（公开）**
- 本项目映射: `scripts/download_oanda_financing_history.py`；**不可**单独打开 formal net
- 复制状态: extension_only（条款理解 + 近年公开表）；fail_closed_missing_data（目标账户长史）

## 1. 经济机制

零售 FX 隔夜仓收取/支付 financing（swap），通常锚定流动性提供者 tom-next，再加经纪商 admin。费率按账户实体、交易组、工具而异，且可每日调整。这是账户级 **可实现 carry 的一部分**，与银行间 1M CIP basis 相关但不可互换。

## 2. 精确公式（US 官方页）

```text
Financing cost or credit = position_value × applicable_funding_rate × (1/365)
position_value = position_size × price_at_5pm_ET

# funding_rate: 年化；分 long/short；可每日变
# 负值 → 扣款；正值 → 入账
# FX: blend(LP tom-next) + annualized admin fee

Admin fee (US page, annualized):
  TRY pairs: 4%
  CZK, HUF, SAR, THB, ZAR pairs: 2%
  other pairs: 1%

# 持仓跨越 17:00 ET → 记 overnight
# FX T+2 ⇒ Wednesday 通常 triple；Sat/Sun 不收
# 假日可改变 days 覆盖
```

UK/BVI 页表述为 size×rate×duration×账户币换算；**必须以账户法人页为准**。

## 3. 数据与样本

| 项 | 公开文档/API | 目标账户正式史 |
|---|---|---|
| 覆盖 | 约一年日频（labs API 实践） | 需 2016–2025 |
| 字段 | long/short charge & rate, days, instrument, units | 见 swap 合同 |
| 实体 | divisionId / tradingGroupId | 用户 legal entity |
| 与 OIS | **无关** | 仍非 OIS |

## 4. 成本与可实现性

- 公开表：软件压力、近期对照
- **不是** practice 与 live 自动等同
- **不是** forward points
- 脚本拒绝把输出当作 OIS/forward

## 5. 识别与稳健性

- 同日 17:00 前为 indicative；收盘后 finalize
- 指示值可与实扣不同
- 跨实体（US/UK/EU/AU/BVI）条款不同

## 6. 复制清单

| 字段 | 需要？ | 本项目 | 缺失时 |
|---|---|---|---|
| 官方公式理解 | 是 | 本笔记 | — |
| 公开 API 归档 | 可选 | download script | 研究 only |
| 账户行级 10y 史 | 正式 net | **缺** | cost_incomplete |
| broker_entity 声明 | 正式 | 请求模板 null | 门关闭 |

## 7. 本项目映射

- `BASE_URL=https://labs-api.oanda.com/v1/financing-rates`
- `SOURCE_PAGE=https://www.oanda.com/us-en/trading/financing-fees/`
- 请求模板：`oanda_practice_allowed_as=execution_software_stress_only`
- 否决：用一年公开表外推十年净收益

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| 官方 | OANDA financing pages | 账户成本定义 |
| 合同 | broker_cost_contract | schema/verdict |
| 市场 CIP | Du / Borio | 不同层级 |

## 9. 精读问题

1. 如何把 USD charge/units 无损映射到合同 `pips` vs `account_currency_per_unit`？
2. triple Wednesday 与持有 21 日策略的融资方差有多大？
3. 多实体账户时 FDR 前是否必须分实体分层？

## 官方 URL 列表

| 页面 | URL |
|---|---|
| US financing fees | https://www.oanda.com/us-en/trading/financing-fees/ |
| US financing FAQ | https://help.oanda.com/us/en/faqs/financing-costs-us.htm |
| US charges | https://www.oanda.com/us-en/trading/our-charges/ |
| UK financing | https://www.oanda.com/uk-en/trading/financing-costs/ |
| BVI financing | https://www.oanda.com/bvi-en/cfds/financing-costs/ |
| Customer agreement (OC) | https://www.oanda.com/register/docs/divisions/oc/fxtrade_customer_agreement.pdf |
| labs financing API | https://labs-api.oanda.com/v1/financing-rates |
