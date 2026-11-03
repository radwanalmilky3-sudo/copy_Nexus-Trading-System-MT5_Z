# Retail vs Interbank FX Execution（研究级）

- 深度层级: L2–L3
- 角色: boundary / data_contract
- DOI/URL: 监管披露（NFA/ESMA 类成本与执行报告）、银行间微观结构文献、零售平台公开执行说明
- 开放获取: 部分
- 本项目映射: Dukascopy/broker 可实现性；禁止 mid 利润宣传
- 复制状态: extension_only

## 1. 经济机制

银行间 FX 是 **多层、多方、常带 last-look 的询价/撮合生态**；零售是 **客户—做市商/STP 通道** 合同。同一名义“EURUSD 点差 0.2 pip”在两边的 **信息集、拒绝权、库存转移、swap 记账** 都不同。研究若把学术 mid 或单一零售流当成“市场有效价”，会把 **不可实现的 midquote premium** 写成 alpha。

## 2. 对照表

| 维度 | Interbank / institutional | Retail / electronic broker |
|---|---|---|
| 对手方 | 银行、ECN、prime、平台多边 | 通常 B-book/A-book 混合或单一流动性路由 |
| 价格形成 | 多方报价、可拒绝、last-look 常见 | 平台展示 bid/ask；成交规则由客户协议定 |
| 深度 | 分层；研究需 L2/L3 或代理 | 常见仅 top-of-book |
| 延迟 | 微秒–毫秒级竞争 | 网络+平台；对冲延迟可转成滑点 |
| 最小单位 | 机构名义 | 微型手/小数手常见 |
| 融资 | 独立 CSA/ISDA、抵押、内部资金曲线 | **账户 swap / financing** 日终规则 |
| 定盘执行 | 可谈 fixing order、VWAP、guaranteed fix（合同） | 少见真正 guaranteed WMR；多为市价/限价 |
| 数据可得性 | 贵、有许可 | Dukascopy 等零售流相对可得 |
| 监管披露 | 机构最佳执行框架 | 零售成本/风险披露、杠杆上限（辖区） |

## 3. 执行路径（字段级）

```text
# institutional (schematic)
RFQ/stream → quote (bid/ask, size, TTL) → accept/reject/last-look → fill or decline
→ allocation / prime give-up → settlement instructions

# retail (schematic)
client order → platform risk engine → LP route or internalize
→ fill at platform price → account ledger (PnL, margin, swap)
```

研究必须记录：

| 字段 | 含义 |
|---|---|
| `quote_source` | 谁的 bid/ask |
| `fill_model` | mid / side / touch / aggressive |
| `reject_rate` | last-look / 拒单（若可得） |
| `latency_assumption` | 信号→下单→成交 |
| `holding_financing` | swap 规则来源 |
| `partial_fill_policy` | 是否允许 |

## 4. 价格源不可互换（强化）

| 源 | 可支撑 | 不可支撑 |
|---|---|---|
| 学术 mid (Olsen 等) | 因子横截面方向探索 | 零售净收益、执行 alpha |
| 单一零售 tick (Dukascopy) | 该通道可成交侧研究 | 全市场最优价、机构 fill |
| 银行间专有 tape | 微观结构论文级 | 无许可不可用于本开源项目 bulk |
| Yahoo/日线 mid | 软件与粗探索 | 任何“可交易夏普”声明 |

## 5. 成本栈差异

**机构：** spread + market impact + last-look opportunity cost + prime/brokerage + funding (CSA/XCCY)。  
**零售：** spread + commission + swap + 可能的滑点/扩大点差（新闻窗）+ 隔夜融资标记。

```text
implementable_net ≠ mid_to_mid_gross
retail_net ≠ institutional_net  even if mid path identical
```

## 6. 本项目硬边界

- 慢周期与日内回测：默认 **side-correct bid/ask**（有数据时）。  
- 缺历史 swap → 净收益 fail closed；可做方向/排序探索并标注 `cost_incomplete`。  
- 禁止把机构 CIP 套利文献的利润数字迁移为零售账户期望。  
- 禁止 last-look 学术结论直接当作零售平台无拒绝成交。

## 7. 与相邻目录

- `03_microstructure_intraday`：窗口内流动性、fix 抢跑。  
- `06_broker_costs`：swap 合同与 CIP 对照。  
- `05_data_contracts`：字段级允许/禁止。

## 8. 精读问题

1. 在只有 Dukascopy bid/ask 时，哪些执行假设是 **可审计的上界/下界**？  
2. last-look 文献的 reject 如何（或不如何）映射到零售“滑点”？  
3. 为何正的 academic carry 在零售 swap 表上可能为负？
