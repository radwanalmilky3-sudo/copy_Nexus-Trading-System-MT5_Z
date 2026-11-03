# SWAP / FORWARD 来源状态（项目内只读审计）

更新日期：2026-07-17  
原则：`cost_incomplete_research_only` ⇒ **禁止正式净 PnL 主张**。政策利率 / 合成 `F_hat` **≠** 观察到的可交易远期。

## 1. 项目内已有（软件合同，非完整市场史）

| 组件 | 路径 | 作用 | 是否足以正式净收益 |
|---|---|---|---|
| 成本合同模块 | `src/fx_system/broker_cost_contract.py` | swap/forward schema、覆盖审计、`CostVerdict` | 否（无真实史） |
| 历史 swap 挂接 | `data.attach_historical_swaps` | as-of join `available_time`；禁未来回填 | 依赖外部 CSV |
| PIT 利率/远期解析 | `point_in_time.py` | `currency_rates` / `forward_points` + manifest 哈希 | 质量标签门禁 |
| 长周期执行融资 | `long_horizon_execution.py` | 会话级 long/short financing per unit | 需已验证费率 |
| 示例 swap | `examples/swaps/EURUSD.example.csv` | 格式样例 | **否** |
| 示例 PIT | `examples/point_in_time/*.example.csv` + manifest | `unknown_unverified` 故意 | **否** |
| 数据请求模板 | `examples/cost_contract/broker_swap_forward_request.json` | 向目标经纪商索取字段清单 | 实体未确认 |
| OANDA 公开融资下载器 | `scripts/download_oanda_financing_history.py` | 抓取 public labs API 约一年日频 | **非**目标账户 2016–2025；**非** OIS/forward |
| Broker carry 文档 | `docs/BROKER_CARRY_DISCOVERY_ZH.md` | bid/ask、swap、PIT 契约说明 | 规范文档 |
| 文献地图 CIP 段 | `docs/FX_FACTOR_LITERATURE_MAP_ZH.md` | 字段合同与 fail closed | 规范文档 |

### 1.1 Swap / financing 字段（合同）

**现代 schema（`SWAP_REQUIRED_COLUMNS`）：**

```text
symbol, available_time, long_financing, short_financing,
unit, day_count, source, version
```

可选：`effective_time, markup, holiday_multiplier, account_currency, triple_swap_weekday, broker_entity, notes`

**单位白名单：** `account_currency_per_unit | pips | quote_currency_per_unit`  
**日算白名单：** `actual_360 | actual_365 | broker_schedule`

**遗留 schema（仍接受）：** `available_time, swap_long_pips, swap_short_pips` → 映射为 long/short_financing，source 默认 `legacy_unspecified`（**不能**标 historical market）。

### 1.2 Forward 字段（合同）

**现代 schema：**

```text
symbol, observation_time, available_time, tenor,
bid_points, ask_points, points_unit, source, version
```

可选：`spot_bid, spot_ask, spot_reference, revision_id, broker_entity, notes`

- tenor ∈ {`1M`,`3M`}
- `ask_points ≥ bid_points`
- `available_time ≥ observation_time`
- 仅 mid 的 `forward_points_1m` 会标 `_legacy_mid_only` → **不可**作可交易历史

### 1.3 质量标签（PIT）

正式晋级只认：

- OIS：`ois_quote_quality=historical_market_ois_quote`
- Forward：`quote_quality=historical_market_quote`

明确**非市场**（覆盖率不计入正式）：  
`policy_rate_proxy`, `overnight_rate_proxy`, `synthetic_curve`, `synthetic_interest_parity`, `broker_financing_proxy`, `software_synthetic`, `unknown_unverified`

### 1.4 审计 verdict

`audit_cost_coverage`：

```text
historical_market_cost_ready
  仅当：broker_entity 已声明
       + swap 与 forward 均为 verified market
       + 覆盖 ≥ 阈值且无 stale gap
       + 无 issues

否则: cost_incomplete_research_only
formal_net_returns_ready: 实现中不因软件通过而自动 True
```

## 2. 目标经纪商必须提供（硬依赖）

覆盖请求窗口见请求模板：`2016-01-01Z` … `2026-01-01Z`（可调），符号含 G9/扩展 12 对。

### 2.1 账户融资（swap/rollover）

| 需求 | 说明 |
|---|---|
| 法人实体 | `broker_legal_entity`；practice ≠ live 条款 |
| 账户币种 | 影响 charge 折算 |
| 逐日/逐生效 long & short 费率 | 与平台实际入账一致 |
| 单位与 day-count | 与合同白名单对齐或可无损换算 |
| 三倍掉期星期 | 通常周三；以实体为准 |
| 假日乘数 / 特殊日历 | 影响周末与假日滚动 |
| markup / admin | 相对 tom-next 的加点 |
| 生效与可知时间 | `effective_time` vs `available_time`（PIT） |
| 版本与源 | 可哈希归档 |

**OANDA 公开页/API 不能替代上述完整史：** 公开表约一年、division/trading group 可能与用户账户不同；脚本明确不把数据称为 OIS/forward。

### 2.2 可交易远期

| 需求 | 说明 |
|---|---|
| 双边 points | bid/ask，非 mid-only |
| tenor | 至少 1M；CIP/quarter-end 可能需 1W |
| 同时点 spot bid/ask | 报价惯例一致 |
| 结算日 | spot settlement、forward settlement/maturity |
| 同源时间戳 | observation/available |
| venue | 银行间 vs 零售加点 |

## 3. 免费代理：**不是**替代品

| 代理 | 可用作 | **禁止**声称 |
|---|---|---|
| 政策利率差 | 探索 `rate_differential`；机制 | 可交易 carry 复制；OIS |
| 利率平价合成 `F_hat` | 压力测试合成路径 | 观察到的市场 forward |
| 隔夜参考利率代理 | 研究标签 | historical_market_ois_quote |
| OANDA 公开 ~1y financing | 软件/近期压力 | 2016–2025 目标账户成本 |
| Dukascopy bid/ask spot | 执行价与 spread | swap；forward points |
| BIS GLI/LBS/OTC 统计 | 低频资金状态 | 日度 G9 方向或逐对 swap |
| Yahoo/mid 公共行情 | 非执行研究 | broker_ready 净收益 |

## 4. OANDA 官方文档 URL（已核验入口）

| 用途 | URL |
|---|---|
| US financing fees（公式与 admin 表） | https://www.oanda.com/us-en/trading/financing-fees/ |
| US financing FAQ | https://help.oanda.com/us/en/faqs/financing-costs-us.htm |
| US charges | https://www.oanda.com/us-en/trading/our-charges/ |
| UK financing costs | https://www.oanda.com/uk-en/trading/financing-costs/ |
| BVI/GM financing | https://www.oanda.com/bvi-en/cfds/financing-costs/ |
| 公开融资表页（下载器 SOURCE_PAGE） | https://www.oanda.com/us-en/trading/financing-fees/ |
| labs API（下载器 BASE_URL） | https://labs-api.oanda.com/v1/financing-rates |
| fxTrade 客户协议（费率裁量） | https://www.oanda.com/register/docs/divisions/oc/fxtrade_customer_agreement.pdf |

**US 页公式（官方）：**

```text
Financing cost/credit = position_value × funding_rate × (1/365)
position_value = size × price_at_5pm_ET
# 负 rate = 扣款；正 rate = 入账
# Forex funding ≈ LP tom-next 混合 + 年化 admin fee
# 通常 17:00 ET 隔夜；FX T+2 ⇒ 周三常三倍；周末不收
```

Admin fee（年化，US 页）：TRY 4%；CZK/HUF/SAR/THB/ZAR 2%；其他 1%。

## 5. 状态一句话

| 项 | 状态 |
|---|---|
| 软件契约与 fail-closed 审计 | **有** |
| 目标账户 2016–2025 行级 swap | **缺（G1）** |
| 同口径可交易 forward bid/ask | **缺（G2）** |
| 免费代理填洞 | **明确否决** |
| 正式净收益 | **关闭** |
