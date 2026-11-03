# CIP / Carry 数据合同检查清单（字段级）

更新日期：2026-07-17  
主文献：Du–Tepper–Verdelhan；Borio et al. BIS；本项目 `broker_cost_contract` / 文献地图。

## 0. 总否决

```text
缺任一侧 spot/forward 双边、tenor、结算约定、或同步现金/OIS
  → 严格 CIP / 可交易 carry 检验 fail closed

政策利率或 CIP 公式生成的 F_hat
  → 可标 synthetic；不可改名为 observed tradable forward

cost_incomplete_research_only
  → 禁止正式 net PnL 结论
```

## 1. 单期最小输入（同源快照）

| 字段 | 定义 | 必须 | 项目落点 | 缺失 |
|---|---|---|---|---|
| `quote_timestamp` | 报价时刻 | 是 | observation_time | fail closed |
| `available_time` | 决策可知时刻 | 是 | PIT join | fail closed |
| `pair` | 货币对 | 是 | symbol | fail closed |
| `quote_convention` | 直接/间接；每外币多少 USD 等 | 是 | 文档+校验 | 错号则废 |
| `tenor` | 1W/1M/3M… | 是 | forward tenor | fail closed |
| `spot_bid` | 可成交即期买 | 是* | forward 可选列；Dukascopy spot | fail closed* |
| `spot_ask` | 可成交即期卖 | 是* | 同上 | fail closed* |
| `forward_bid` / `bid_points` | 远期买价或 points | 是 | bid_points | fail closed |
| `forward_ask` / `ask_points` | 远期卖价或 points | 是 | ask_points | fail closed |
| `points_unit` | absolute_price / pips | 是 | 合同白名单 | fail closed |
| `spot_settlement_date` | 即期交割日 | CIP 严格 | 未建专用列 | fail closed for CIP |
| `forward_settlement_date` | 远期交割日 | CIP 严格 | 未建专用列 | fail closed for CIP |
| `forward_maturity_date` | 到期/maturity | quarter-end | 未建专用列 | fail closed for Qend |
| `ois_base` / `ois_quote` | 同 tenor 无风险曲线 | CIP 严格 | currency_rates ois_* | 非 proxy |
| `cash_rate_base/quote` | 若用 libor/repo 替代 | 条件 | 需声明 | 口径不一致废 |
| `venue_or_account` | 银行间 vs 零售账户 | 是 | broker_entity | 未声明则研究 only |
| `source, version, hash` | 可复核 | 是 | manifest | fail closed 晋级 |

\*零售执行研究可用 Dukascopy 双边 spot；但 **carry/CIP 精确复制**仍要与 forward **同一惯例、同一时间网格**。

## 2. 核心公式

### 2.1 无成本 CIP（对数近似）

```text
# S: spot；F: outright forward；r, r*: 同 tenor 连续或匹配 day-count 利率
F / S = (1 + r_quote * τ) / (1 + r_base * τ)     # 惯例依赖报价方向！

# cross-currency basis b（概念：使平价恢复的加点）
# 实际市场报价常使
F/S ≈ (1 + r_quote * τ + b * τ) / (1 + r_base * τ)
# 或等价地定义 xccy basis swap 上的 b（Borio/Du 口径需对齐）
```

### 2.2 可交易 forward 与合成

```text
F_mid_mkt = observed from bid/ask points + spot
F_hat_CIP = S * (1+r_q τ)/(1+r_b τ)    # 合成；≠ market F
basis_proxy ∝ (F_mkt - F_hat) / S      # 仅当 F_mkt 与 r 同期同源
```

### 2.3 零售实现 vs 纸面超额

```text
# 纸面 forward excess（常见学术）:
rx ≈ (F_{t→t+h} - S_{t+h}) / S_t     # 或 log；多空按折扣排序

# 零售账户近似（非充分统计）：
# 入场/出场跨 bid-ask + 持有期 swap/rollover 累计
# 无行级 swap ⇒ 不得报 net rx
```

## 3. Du–Tepper–Verdelhan quarter-end 标志

因变量是 **CIP basis 绝对值**（1W/1M），不是 spot 方向哑变量。

| 标志 | 合同（字段级） | 本项目 |
|---|---|---|
| `QendW=1` | **T+2 spot settlement** 落在**本季度最后一周**，且 **1W forward maturity** 落在**下一季度** | 需 settlement/maturity 日历；**仅 spot spread 季节性 ≠ 复制** |
| `QendM=1` | **1M forward** 的 settlement 与 maturity **跨季度** | 同上 |
| 同步输入 | spot、真实 forward、同 tenor OIS/repo/当时基准 | G2 未满足则 fail closed |
| 禁止 | 用 Dukascopy spread 季度末形态声称 CIP/dealer balance-sheet 机制 | 文献地图已否决 |

## 4. 报价惯例检查

| 检查 | 通过条件 |
|---|---|
| 方向 | 全样本统一 USD 为 base 或 quote；cross 单独声明 |
| points 缩放 | JPY 与非 JPY pip 定义一致；`points_unit` 匹配 |
| bid-ask 交叉 | spot 与 forward 均 ask≥bid |
| 时间对齐 | 利率/OIS available_time ≤ 决策；forward 不超前 |
| day-count | τ 与 OIS 合约 day-count 一致（ACT/360 等） |
| 修订 | 同 observation 多版本用更晚 available_time；manifest 记录 |

## 5. 与 broker 成本合同的交汇

| 门 | 条件 |
|---|---|
| 研究可跑 | 示例/合成 + `cost_incomplete_research_only` |
| broker_ready 方向（文档） | bid/ask 史、swap 覆盖、市场 carry 覆盖等（见 BROKER_CARRY 审计） |
| CIP 严格 | 本节清单 + quarter-end 日期字段 |
| 正式 net | `historical_market_cost_ready` 且业务层打开 `formal_net_returns_ready` |

## 6. 最小验收用例（软件）

1. 故意 `policy_rate` 填入 `ois_1m` 但 `ois_quote_quality=policy_rate_proxy` → 严格覆盖率不升。  
2. mid-only forward → `legacy_mid_only` issue。  
3. `ask_points < bid_points` → schema 拒绝。  
4. 缺 `broker_entity` → 无法 historical_market。  
5. 有 spot 无 forward → carry/CIP 精确复制 fail closed。
