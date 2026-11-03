# 日内文献 → 实验映射（INTRADAY_SOURCE_MAP）

更新日期：2026-07-17  
约束：映射到项目冻结实验；**净成本转负即否决**；扩展必须显式命名。

## 1. 总表

| 文献 | 项目实验 | 需要的数据 | 主统计单位 | 成本后否决 | 其他硬否决 |
|---|---|---|---|---|---|
| Krohn–Mueller–Whelan | **FIX-W** | tick bid/ask；Tokyo/ECB/WMR 官方历 | 事件日 | 可成交净收益 ≤0 | 缺腿 renormalize；1h 代替 tick；未 verified 日历 |
| Breedon–Ranaldo | **LOCAL-PAPER** | 6 对 tick；IANA 时段 | 交易日 × 12 unit | 多数 unit/组合 executable ≤0 仍宣称可交易 | 事后只留 EURUSD；把 1/6 组合叫论文复制 |
| Breedon–Ranaldo（扩展） | **LOCAL-PORTFOLIO** | 完整 12 unit | 交易日 | 同上 | 缺 unit 仍 renormalize |
| 项目扩展 | **ASIA-LDN** | tick 或严格边界报价 | 共同交易日 | 响应系数交易化后净≤0 | 金融中心假日未处理却声称 formal |
| Melvin–Prins | **WMR 月末交互** | 实际 WMR 月末；可选 PIT 权益 | 事件日 | 定盘窗成本后≤0 | 无权益映射却称对冲渠道复制 |
| Mancini–Ranaldo–Wrampelmeyer | **spread q90** | 入场 spread 历史 | 事件日/段 | 过滤后样本过薄且仍数据挖掘阈值 | 用未来/平仓 spread；Dukascopy 当全市场深度 |
| Andersen et al. | **blackout** | 实际发布时间 | 事件 | n/a（风控） | 无 consensus 却做方向 surprise |
| Faust et al. | **surprise 合同** | actual + MMS median | 20 分钟窗 | 窗内成本后≤0 | 缺 consensus |
| Evans–Lyons | 机制 only | 签名 OF | — | — | CFTC/quote size 冒充 OF |
| LSEG WMR PDF | 定盘日历合同 | methodology + alterations | — | — | 启发式工作日定盘 |

## 2. FIX-W 细节

```text
符号：G9 USD 腿标准化为 USD/foreign
  AUD,CAD,CHF,EUR,GBP,JPY,NOK,NZD,SEK
段：
  - pre_tokyo  (NY17 prev → Tokyo 09:55)
  + post_tokyo (Tokyo → Berlin 08:00)
  - pre_ecb    (Berlin 08:00 → ECB 14:15)
  + post_wmr   (WMR+2m30s → NY17)
边界：start 严格后 ≤5s 首报价；end 当时或前 ≤5s 末报价
过滤：每段入场 spread 的 past-60 q90；warmup 60；min obs 40
```

**实施否决（成本）**

1. gross mid 显著但 executable long/short 组合期望 ≤0。  
2. 1.5× spread 压力转负。  
3. 仅在未过滤全样本盈利、q90 后翻号且未预注册。  

**实施否决（合同）**

1. 任一日缺任一 G9 腿或任一段 → composite 空。  
2. 日历 `not_published` / 非 verified。  
3. 把五段原文窗改成未登记的新切分。

## 3. LOCAL-PAPER / LOCAL-PORTFOLIO

| 项 | LOCAL-PAPER | LOCAL-PORTFOLIO |
|---|---|---|
| 是否论文 | 是（12 unit 面板） | **否**（项目扩展） |
| 权重 | 不组合 | 每 pair 固定 1/6 |
| 缺数据 | unit 标记 incomplete | **全日空**，不重归一 |
| 成本 | unit 级 executable | sleeve 复合后 executable |

**成本否决**：论文已写多数 pair 扣费不赚；项目若仅在 EURUSD 上“发现”盈利且未在完整 12 unit 预注册，否决。

## 4. ASIA-LDN

```text
formation: [08:00, 15:00) Asia/Tokyo
response : [07:00, 10:00) Europe/London
H0: coef(response ~ asia_formation) < 0
```

否决：用 1h 诊断结果当 formal；忽略假日/半日导致伪重叠；把预测系数未经成本与多重检验直接当交易规则。

## 5. blackout / surprise

| 模式 | 允许 | 禁止 |
|---|---|---|
| 有实际 timestamp，无 consensus | blackout 禁开仓 | 方向 |
| 有 actual + PIT median | 预注册 surprise 检验 | 未登记的指标网格 |
| 只有新闻标题/实际水平 | 无 | 一切方向 |

Blackout 默认：`[T-30m, T+60m]`（路线图）；与定盘策略叠加时取并集。

## 6. 数据源边界（横跨所有日内实验）

| 源 | 可以 | 不可以 |
|---|---|---|
| Dukascopy tick | 可成交侧路径、点差 | 全市场深度、机构 OF |
| LSEG WMR mid | 事件时刻合同 | 零售成交价 |
| CFTC TFF | 拥挤状态探索 | 签名 OF / 定盘流 |
| 1h bars | ASIA-LDN 粗诊断 | FIX-W / LOCAL 正式边界 |

## 7. 晋级顺序（成本优先）

1. 边界完整性与日历审计（零收益查看）  
2. gross mid 符号是否与预注册一致  
3. executable bid/ask  
4. spread q90 后  
5. 1.5×/2.0× 成本压力  
6. 联合事件日 bootstrap + BH/BY + 负对照  
7. 冻结后新前向  

任一步成本转负：**停止**，不缩短窗口反复搜。
