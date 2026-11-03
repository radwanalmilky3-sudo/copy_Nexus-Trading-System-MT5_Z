# FX Rollover / Swap Mechanics（研究级）

- 深度层级: L2–L3
- 角色: foundational / data_contract
- DOI/URL: 主经纪/零售 financing 文档、CIP 文献（Du–Tepper–Verdelhan 等）、BIS basis 讨论
- 开放获取: 部分
- 本项目映射: 账户 swap 账本、carry 可实现性、`06_broker_costs`
- 复制状态: extension_only（缺历史账户 swap → 净收益 fail closed）

## 1. 经济机制

持有 FX 头寸越过 **日终 rollover 点** 时，经济上接近 **滚动 spot 并叠加近端/远端远期点**（或等价的货币利息差）。银行间用 **tom/next、spot/next swap points** 与资金曲线；零售平台用 **swap long/short 点或账户货币借贷利率** 写入客户账本。二者都与 **利率平价** 相关，但 **不是恒等**：信用、库存、营销加点、周末乘数、点差嵌入都会造成 **basis**。

## 2. 精确分解

```text
# 经济（简化，非某一券商公式）
forward_points(tenor) ≈ F - S
CIP_fair: F/S ≈ (1+i_quote*τ)/(1+i_base*τ)   # 约定相关

# 零售账户常见形态（示意）
daily_swap_ccy = position_side * notional_factor * swap_rate_side
weekend_swap   = daily_swap * weekend_multiplier   # 常在周三或其它约定日三倍
admin_markup   = broker_spread_on_swap
ledger_credit_debit = f(daily_swap, weekend, admin_markup, account_ccy_conversion)
```

字段级：

| 字段 | 含义 | 常见陷阱 |
|---|---|---|
| `rollover_time` | 日终判定时刻（平台时区） | 当成 UTC 午夜 |
| `swap_long` / `swap_short` | 多/空融资率 | 不对称；非 ± 镜像 |
| `triple_swap_day` | 周末利息打包日 | 假设总是周三 |
| `notional_basis` | 按手/按基础货币/按账户币 | 单位搞错一个数量级 |
| `storage_ccy` | 借贷以何币计 | 与报价币混淆 |
| `value_date_align` | 与 T+1/T+2 对齐 | 与 civil 日界混淆 |

## 3. 学术 carry vs 零售 swap

| 概念 | 数据 | 研究用途 |
|---|---|---|
| Forward discount | 官方/供应商 forward 或利率构造 | 学术 carry 排序 |
| Cross-currency basis | CIP 偏离 | 融资摩擦、危机状态 |
| Broker swap schedule | 平台公布或 API | **账户可实现净收益** |
| Implied swap from mid interest | 利率中点 | 探索；≠ 账户 |

**硬规则：**

```text
academic_carry_signal  可用于  横截面排序（声明数据源）
broker_swap_ledger     才是   零售持有期融资 PnL
mid_interest_proxy     不可改名为 implementable_net
```

## 4. 周末、假日与三倍 swap

- 零售常把周六日利息集中在某一营业日以 **3×**（或平台规则）记账。  
- 假日可能额外调整。  
- 研究回测若用“年化利率/365”平滑，会 **抹平** 三倍日与不对称 long/short——只可作敏感性，不可作主净收益。

## 5. 与 settlement 的关系

```text
trade Tuesday → spot settlement often Thursday (T+2)
holding past rollover Wednesday → financing for next value day roll
```

- Rollover **时刻**（如 17:00 New York 平台）是 **账本日界**。  
- Settlement **日期**是 **交割日历**。  
- 混用导致 CIP 日与 swap 日错位（见 `settlement_t1_t2_calendars.md`）。

## 6. 成本进入净收益的顺序

```text
gross price PnL (side-correct)
  - open/close spread & slippage
  - sum of daily swap credits/debits (incl. triple days)
  - commissions
  ± margin cash interest (if any)
= net account PnL
```

缺失任一历史序列：

- 标 `cost_incomplete`  
- 禁止报告“净夏普可交易”  
- 允许：方向 IC、排序、无成本机制检验（明确标注）

## 7. 禁止推断

- 禁止 `swap = i_base - i_quote` 无加点恒等。  
- 禁止用单一货币政策利率代替账户 swap 表。  
- 禁止把 OANDA/某平台规则推广为全市场。  
- 禁止在无 swap 史时用 mid carry 回测声称零售可实现。

## 8. 本项目映射

- 主账户：swap 分录进入账本（有 API/导出后）。  
- 探索：forward discount 因子与 swap 符号对照。  
- 否决：无融资的多空 carry “净收益”排行榜。  
- 详见 `06_broker_costs/` 与 CIP checklist。

## 9. 精读问题

1. 为何 long 与 short swap 点差之和常显著为负（客户视角）？  
2. 三倍日是否应在事件研究中剔除或单独分层？  
3. CIP basis 扩大时，零售 swap 表调整的滞后有多长？如何测量？
