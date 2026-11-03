# FX 执行与报价基础（研究级笔记）

- 深度层级: L2–L3  
- 角色: data_contract / boundary  
- 目的: 支撑后续因子笔记中的“可实现性”段落，不是交易教程  

## 1. 报价与收益方向

- **直接报价 / 间接报价**必须在公式里固定；同一论文的 `USD per foreign` vs `foreign per USD` 弄反会翻转整个因子符号。  
- 零售平台常见 **base/quote** 与学术 **indirect quote** 混用：复制清单必须写 `quote_convention`。  
- 点值（pip）、合约名义、账户结算币种进入 **主账户净额** 时，不能只在“货币对空间”算收益。

## 2. Settlement 与 rollover

```text
trade_date t
spot_settlement = t + T+1 or T+2 (币种对依赖；需日历)
forward_settlement = spot_settlement + tenor_business_rules
rollover / swap: 零售账户按日 multipled by position，规则来自 broker 合同而非利率平价恒等式
```

- 学术 carry 常用 **forward discount**；零售 PnL 常见 **swap credits/debits**。二者经济相关但**数据合同不同**。  
- 缺历史 swap 时：价格方向研究可做探索；**历史净收益** fail closed（本项目硬规则）。

## 3. 交易时段与定盘（与 03 目录衔接）

| 事件 | 典型 civil time | 研究含义 |
|---|---|---|
| Tokyo fix | 09:55 JST 一带 | FIX-W 预/后窗 |
| ECB ref | 14:15 CET | 参考价，非 WMR |
| WMR | 16:00 London | 基准定盘；月末对冲流 |
| NY 17:00 | America/New_York | 本项目 FX 日界 |

Civil time → UTC 必须 **逐日 IANA/DST**，禁止固定偏移。

## 4. 价格源不可互换

| 源 | 是什么 | 不能声称 |
|---|---|---|
| 学术 mid / Olsen | 研究报价 | 零售可成交价 |
| Dukascopy tick | 单一零售流 | 全市场深度/最优价 |
| Broker practice | 账户可成交侧 | 历史全样本无缺口的研究宇宙（除非有导出） |
| Yahoo mid | 粗日线 | 任何净成本利润 |

## 5. 成本栈（进入净收益的顺序）

```text
gross price PnL
  - spread (bid/ask side-correct)
  - slippage / latency (模型或保守假设)
  - swap / financing
  - commissions
  ± cash interest on margin
= net
```

任一历史序列缺失 → 对应项标 `cost_incomplete`，禁止把 mid 回测改名为 net。

## 6. 本项目映射

- 慢周期：next-open、sleeve、主账户账本  
- 日内：5 秒 prevailing bid/ask、事件边界  
- 否决：三角套利 bar 回测、马丁网格、无成本 mid alpha 宣传  

## 7. 精读问题

1. 为何 “正 carry 的货币对” 在零售账户仍可能日均 swap 为负？  
2. T+2 与季度末 CIP 检验的 settlement 标志如何耦合？  
3. 同一时刻 bid/ask 缺失 5 秒以上，事件研究应删除还是插值？本项目选择是什么？  
