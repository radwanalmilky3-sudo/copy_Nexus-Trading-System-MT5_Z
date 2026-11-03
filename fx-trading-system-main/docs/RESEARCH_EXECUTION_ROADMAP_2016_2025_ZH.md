# 2016–2025 外汇因子研究执行路线

更新日期：2026-07-16。

## 结论先行

本项目当前处于**研究基础设施和候选淘汰阶段**，尚未发现可以批准交易的盈利因子，也没有
冻结可交易模型。Dukascopy 到达后要回答的是“候选在真实历史双边报价、点差和近十年市场中
是否仍成立”，不是“如何把回测调成盈利”。

研究固定为两条互相隔离的路线：

1. 慢周期：21 / 42 / 63 个交易日持有，约每 21 个交易日调仓；
2. 日内：定盘窗口、本地交易时段和亚洲—伦敦时段响应，持有约 1–4 小时。

正式 Dukascopy 研究区间固定为 `2016-01-01` 至 `2025-12-31`，命令中的排他结束时间是
`2026-01-01`。这十年只够慢周期的一个“8 年训练 + 2 年 OOS”切分，不能独立提供三个以上
非重叠长期 OOS 窗口。2006 年以来的 Yahoo midpoint 和外部历史已经用于提出、修改和淘汰
假设；市场历史已查看至 `2026-07-13`。因此，重跑 2016–2025 Dukascopy 可以提供新的成交侧
证据，但不能把同一市场时期重新命名为 untouched holdout。最终推断必须依赖冻结后严格新增
的 3–6 个月前向数据。

本文是一份执行契约，不是收益承诺。任何“因子显著”“OOS 同号”或“免费数据为正”都不等于
扣除点差、滑点、融资、组合约束后的策略盈利。

## 当前证据快照

最新免费数据筛选是 `outputs/long_horizon_free_screen_v4/`：

| 项目 | v4 结果 |
|---|---:|
| 数据 | Yahoo 日频 midpoint + 免费外部数据 |
| 品种 | 12 个货币对 |
| 因子 | 43 个 |
| 期限 | 21 / 42 / 63 日 |
| 非重叠 OOS 折 | 5 |
| 每折统一检验数 | 129 |
| 总训练检验数 | 645 |
| 训练入选 | 2 |
| 方向因子入选 | 0 |
| 风险状态因子入选 | 2 |
| 入选因子 OOS 同号 | 0 / 2 |
| 在至少两个训练折重复入选 | 0 |

仅第 0 折的 `risk_nfci × 63d` 和 `risk_stlfsi × 63d` 通过 BH FDR 10%；两者是预测未来
**绝对收益状态**的非方向因子，且 OOS IC 都翻为负值。它们不能决定做多或做空，当前也没有
资格成为风险缩放器。新增的商品货币、Value×Trend、仓位拥挤反转、政策不确定性、地缘风险和
严格 GSCPI vintage 因子均未晋级。

v4 使用 20,000 次 bootstrap。对 `m=129`、`q=0.10` 的检验族，经验 p 值至少需要：

```text
B >= ceil(m / q) - 1 = 1,289
```

否则最小可达 p 值连第一条 BH 阈值都无法分辨。当前实现已把这个条件变成硬门槛。v4 的结论
是“继续拒绝方向 alpha”，不是“风险状态因子有效”。

已经具备的准备工作包括：

- Dukascopy SQLite 下载器 v1.1.0：默认 14 品种、排他结束 `2026-01-01`、断点续传、
  每库哈希/sidecar、整体 transfer manifest、完整性验证和 1h/4h 聚合；
- 21/42/63 日无泄漏标签、21 日调仓、purge、非重叠 OOS 和统一 BH FDR；
- 搜索历史注册表、产物 SHA-256 和无效轮次保留；
- World Bank Pink Sheet、GSCPI、Global EPU、GPR 等补充数据下载；
- OFR FSI、ECB CISS、BoC BCPI、RBA I2，以及 Cboe EVZ/EUVIX/JYVIX/BPVIX 的
  current-vintage 快照及原始版本归档；Cboe 只作三币种 30 日隐含波动风险状态；
- Philadelphia Fed RTDSM CPI/IP 真 vintage：572,140 行；严格 as-of 提取只在同一 vintage 内
  计算 CPI 12 月和 IP 6 月 log change，未来修订不会回填；
- 2022 年 1 月以后的 GSCPI 月度 vintage 矩阵及发布时间规则；
- bootstrap 分辨率硬门槛和 Monte Carlo p 值误差报告；
- BH 主门槛、BY 依赖敏感性，以及跨全部列共享日期映射的 block/stationary 重采样核心；
- 共同日期置换、shadow/random factors 和必须被拒绝的 future-information canary；
- IANA/DST 感知的 Tokyo/ECB/WMR、LOCAL、ASIA-LDN 与纽约 17:00 FX 日界模板；
- Breedon–Ranaldo 全文核对后的 `LOCAL-PAPER` 12 单元面板和见数前 amendment：欧洲重叠腿
  按 open-to-open，假日不预删，普通 crosses 排除周六 `00:00–24:00 UTC`、JPY/AUD crosses
  排除周六 `00:00–18:00 UTC`，边界使用时点当时或之前 5 秒内最后 prevailing bid/ask；另有
  明确标为项目扩展、缺腿不重归一化的六个固定 `1/6` pair sleeves；
- 四段 FIX-W（`-preTokyo + postTokyo - preECB + postWMR`）的冻结 G9 美元腿组合，反向
  报价按 `bid=1/original_ask`、`ask=1/original_bid` 统一为 USD/外币，并按可成交侧计费；
- verified publication calendar 接口、自然月逐日完整的实际 WMR 月末标签，以及事件 SQLite
  窄窗解码和一次性整库 transfer receipt；
- Dukascopy SQLite 到纽约 17:00 日线 bid/ask 的只读桥：逐 payload 复验，源小时缺失、
  `no_data`、无 tick 或开收边界超过 5 秒均不生成日线；跨品种正式适配器不做隐式交集/填充，
  并保留收盘实际发生的 21:00/22:00 UTC 时间；
- WM/Reuters、Refinitiv、LSEG 官方 service-alteration 历史 PDF 与 ECB 官方 2:15 p.m. CET
  日期已生成 2016–2025 的 10,959 行事件日历；Tokyo/ECB/WMR 分别有
  2,575 / 2,560 / 2,580 个发布日，三类同时发布的日期共 2,557 个；
- CFTC 2016–2025 的 522 行发布时间证据日历及 12 份 raw/hash：489 tentative、16 announced、
  10 rule-derived、7 actual-date-only、0 actual timestamp；它不会把 current revised archive
  升级成 as-published vintage；
- 21/42/63 日重叠 sleeve 资本守恒、主账户净交易、每日成本/PnL 账本及合成端到端 runner；
- 成本后组合验证桥接层：要求完整候选集、精确共同日期索引、完整历史试验数，并对
  价格 PnL、spread、slippage、financing、cash interest、NAV 和复利回报做 fail-closed 勾稽；
- 完整试验数约束下的 DSR、16 块 CSCV/PBO、SPA 输入校验，以及透明的 studentized Hansen
  SPA 核心（stationary LRV、三种 recentering、plus-one p 值）；
- 日内共同事件日面板、joint stationary bootstrap、BH/BY、联合符号负对照、future-information
  canary，以及 DSR/PBO/SPA 诊断入口；

尚未完成、但在正式策略组合回测前必须完成的工作包括：

- 正式慢周期 factor-only 编排/CLI 已接通：SQLite 至严格共同纽约收盘日线、注册表约束的
  7 个候选单元，以及 21/42/63 日 close-t decision / next-open / scheduled-close 信号调度；
  它硬禁未来标签、组合收益和交易批准。独立次日开盘/收盘两阶段合成账本已经实现，但尚未与
  冻结调度串联；其余未接通项包括重叠 sleeve 与跨候选预算、账户币种 quantity/FX conversion、
  未实现 PnL cost basis/broker settlement、历史 financing/真实 forward、slippage/commission，
  逐品种 quote timestamp/staleness，
  以及正式净收益后的 SPA runner/manifest 串联；FIX-W 的 SQLite 窄窗、rolling spread 和日内统计入口
  已经接通；
- ASIA-LDN 敏感性分析所需的金融中心节假日和半日市数据；`LOCAL-PAPER` 主规格沿用原文，
  先应用逐单元 UTC working-week 边界，再包含仍有可成交边界报价的假日；Tokyo/ECB/WMR 的官方发生日历已经
  下载并通过 CSV、raw source 与 manifest 三层哈希；
- 用到达后的真实 tick 实例化已测试的事件报价选择、5 秒边界完整性和滚动 spread 门槛；
- 目标账户 2016–2025 历史 swap，或同口径的真实远期点；
- 严格前向运行期。

搜索账本当前公开 6 轮、3,057 个折内假设检验和 3,312 次因子—结果评估；共有 16 个登记
假设，其中 13 个 active、3 个 `superseded_unevaluated`，所有已登记产物哈希均已验证。这里的
数量是研究暴露，不是可以合并为独立样本的统计量。

## 数据含义和 PIT 边界

“真实市场数据”“current-vintage”“严格 PIT”和“压力情景”是四个不同维度，不能互相替换。

| 分类 | 本项目中的数据 | 允许用途 | 禁止表述 |
|---|---|---|---|
| 历史市场观察 | Dukascopy tick bid/ask、报价量；真实 1M forward points（取得后） | 重建可成交侧、历史点差、价格路径和市场 carry | Dukascopy 报价不等于目标账户实际成交，也不是全市场 consolidated tape |
| 严格 PIT | 带真实 `available_time` 的发布 vintage；2022-01 后 GSCPI vintage；已归档的 Philly Fed RTDSM CPI/IP vintage | as-of 合并、严格前向或对应 vintage 区间的历史检验 | 不能用最后修订值回填早期日期 |
| Current-vintage | BIS REER、Pink Sheet、Global EPU、GPR、普通 GSCPI 历史；已归档的 OFR FSI、ECB CISS、BoC BCPI、RBA I2、Cboe FX IV 抓取时点快照 | 经济动机探索、状态诊断、提出待前向验证假设 | 不能加一个人为发布滞后就称为严格 PIT；Cboe 30 日 IV 不能冒充一年期 OTC smile/VRP |
| 近似发布时间 + current archive | 当前 CFTC TFF 使用报告日后 60 天的保守 `available_time`，数值来自会修订的 Historical Compressed 当前档案 | 探索仓位因子，降低明显泄漏风险 | 不能称为逐期真实发布时间、as-published vintage 或即时订单流；两项都验证前不得严格晋级 |
| 压力情景 | OANDA 2025–2026 融资表应用于 2016–2025；政策/隔夜利差代理 | 估算不利成本、敏感性分析 | 不能称为 2016–2025 已实现融资、OIS 或真实 forward carry |

额外约束：

1. 政策利率和普通隔夜参考利率不是 OIS；利率平价合成的远期点也不是独立市场报价。
2. Ordinary GSCPI 的完整历史是 current-vintage；只有保存的月度 vintage 区间才可按实际
   vintage 使用。当前严格覆盖从 2022 年 1 月开始，所以较低覆盖率是正确行为。
3. CFTC 有报告日期但没有完整逐期历史发布时间。补齐真实发布时间前，它不能推动严格晋级。
4. Current-vintage 数据可以产生一个值得前向测试的假设，但不能单独证明历史可交易性。
5. 任何新下载都要保存原始响应、抓取时间、来源 URL、SHA-256、解析版本和可用时间规则。

### 补充数据优先顺序

在免费范围内按以下顺序推进：

1. Philadelphia Fed RTDSM CPI/IP：真 vintage，优先用于宏观状态和变化率；
2. OFR Financial Stress Index：current-vintage，先做风险状态探索；
3. ECB CISS：current-vintage，先做欧洲系统性风险状态探索；
4. Cboe EVZ/EUVIX/JYVIX/BPVIX：current-vintage，只做 EUR/JPY/GBP 波动机制审计；四条
   都在首次归档前停止，不能提供严格前向晋级期；
5. Bank of Canada BCPI：current-vintage，可细化 CAD 商品暴露；
6. RBA I2：current-vintage，可补充澳洲商品价格；
7. OECD Economic Outlook：官方 API 窄查询下载器已实现，覆盖 EO99–118 的五个固定预测
   变量；它是日期级 forecast edition，不是 actual-data vintage 或 consensus surprise。
   EA15/16/17 构成变化禁止自动接续；任何方向假设仍须先冻结，原始响应重新分发前另行核对
   OECD 条款。

OFR/CISS/Cboe/BCPI/RBA 已下载，历史回填使用首次抓取时点作为 `available_time`；从本项目开始
定期保存的新快照，未来才可能形成 forward-strict 的自建 vintage 档案。RTDSM 已下载但尚未
据结果提出新的方向规则；若要形成 CPI/IP 因子，必须先在注册表冻结公式再运行。

## 路线 A：慢周期因子

### 研究对象和统计单位

- 品种固定为 EURUSD、GBPUSD、USDJPY、USDCHF、AUDUSD、NZDUSD、USDCAD、EURGBP、
  EURJPY、GBPJPY、AUDJPY、CADJPY；
- 调仓间隔固定为 21 个交易日；持有期固定为 21 / 42 / 63 个交易日；
- 因子只使用 `feature_time` 已知的数据，下一可交易 bar 才能入场；
- 训练样本的完整标签必须在 OOS 开始前结束，否则 purge；
- 统计观测是“共同调仓日期”，不是每个重叠日度标签，也不是 12 个完全独立的货币对；
- bootstrap 日期块为 63 个交易日，即 3 个调仓观测；所有品种必须使用同一抽样日期块。

### 候选因子及资格

| 家族 | 冻结候选或基线 | 方向性 | 当前资格 |
|---|---|---:|---|
| Momentum / Trend | 21/63/126/252 日动量、252 跳过最近 21 日、趋势 t-stat、均线偏离、横截面货币强度 | 是 | 可用 Dukascopy 价格重算；既有历史筛选未晋级 |
| Value | BIS REER 的 36/60 月 value、12 月变化 | 是 | current-vintage 探索；需要新前向期确认 |
| Value×Trend | 两个中心化横截面 rank 同号时取均值，期限 42/63 日 | 是 | 已预注册；v4 未晋级；current-vintage 限制 |
| 商品货币 | CAD=油、AUD=基本金属、NZD=农业、JPY=-能源；pair=base-quote | 是 | 已预注册；v4 未晋级；Pink Sheet 为 current-vintage |
| 仓位拥挤反转 | 趋势与杠杆仓位同向且 `abs(z)>=1` 时，反向于 63 日动量 | 是 | 已预注册；v4 未晋级；CFTC 发布时间仍是近似 |
| Carry | 真实 1M forward discount × 低全球 FX 波动门控，inverse-vol sizing | 是 | 缺真实 forward/swap，继续 deferred；不得用政策利差冒充 |
| 风险状态 | 实现波动、NFCI、STLFSI、VIX、GEPU、GPR、GSCPI | 否 | 只能预测绝对收益或缩放仓位，不能直接给方向 |
| 供应链压力 | PIT GSCPI level + 6 月变化 | 否 | 2022-01 后严格 vintage；只能 forward/risk-state 使用 |

方向 alpha 和风险状态必须分开检验、分开报告。一个风险状态因子只有在“既定且已经冻结的方向
策略”上减少回撤或改善成本后收益，才有资格成为风险层；不能用绝对收益可预测性包装成方向
收益。

### 慢周期组合实现契约

21 / 42 / 63 日持有会产生重叠仓位，必须用 1 / 2 / 3 个独立 sleeve 表示：

```text
每个 slot 的预算 = 该期限总预算 / slot 数
21d: 1 slot
42d: 2 slots
63d: 3 slots
```

所有期限、因子和货币对先汇总为一个主账户目标，再按净目标变化交易。只对净换手收费；如果
回报已按 ask 入场、bid 平仓（或反向可成交侧）计算，就不能再额外重复扣一次固定 spread。
每日必须记录主账户 mark-to-market PnL、币种腿敞口、杠杆、换手、融资和各 sleeve 贡献，
组合层 SPA、Deflated Sharpe 和 PBO 才有合法输入。

## 路线 B：日内因子

日内研究不能用 4h bar 代替 tick。尤其 `09:55`、`14:15` 和伦敦定盘前后的 5–15 分钟窗口，
1h bar 也无法重建真实先后路径。1h 数据只适合本地时段和亚洲—伦敦的探索性粗粒度诊断；
正式 FIX-W 和 `LOCAL-PAPER` 的 5 秒边界契约都必须从 SQLite 原始小时 payload 解码 tick，
并按可成交 bid/ask 计算。

### 预定义研究族

1. `FIX-W` 四段组合：
   `-r(previous 17:00 New_York → 09:55 Tokyo)`、
   `+r(09:55 Tokyo → 08:00 Berlin)`、
   `-r(08:00 Berlin → 14:15 Berlin)`、
   `+r(16:02:30 London → 17:00 New_York)`；先把 AUD/CAD/CHF/EUR/GBP/JPY/NOK/NZD/SEK
   九个冻结美元腿标准化为 USD/外币，再等权汇总。任一腿或任一端点缺失时整日组合不重归一化。
   v1.1 的 14 品种是下载宇宙，不是 FIX-W 的组合宇宙。每段起点只接受边界严格之后
   5 秒内的首个报价，终点只接受边界当时或之前 5 秒内的最后报价。
2. `LOCAL-PAPER` 本地时段效应：固定 12 个单元——EURUSD Europe short/New York long、
   USDJPY Tokyo long/New York short、GBPUSD Europe short/New York long、EURJPY Europe
   short/Tokyo long、USDCHF Europe long/New York short、AUDUSD Sydney short/New York long。
   Europe/New York 重叠的首段在 New York 08:00 开盘平仓（open-to-open）；其他段为原文
   open-to-close。Europe/London 作为论文 Dublin 等价时钟；所有自然日均保留审计行，假日不
   预删，但普通 crosses 的周六 `00:00–24:00 UTC` 和 JPY/AUD crosses 的周六
   `00:00–18:00 UTC` 不合资格。每个合资格边界只接受时点当时或之前 5 秒内最后报价，主结果跨
   bid/ask。论文没有六对组合；
   `LOCAL-PORTFOLIO` 是本项目另行冻结的六个 `1/6` sleeves，12 单元任一缺失则整日为空。
3. `ASIA-LDN` 时段响应：形成窗固定为 `[08:00, 15:00) Asia/Tokyo`，响应窗固定为
   `[07:00, 10:00) Europe/London`，检验响应收益对亚洲收益的系数是否小于 0。
4. 月末交互：只为 WMR 增加一个月末放大项；它是额外假设，必须计入同一搜索族。
5. 流动性过滤：FIX-W 按同一市场品种/同一四段入场边界分别建立过去 60 个事件日的
   spread 分布；前 60 个排程日恒为 warmup，之后至少要有 40 个有效观测，且当前
   spread 不高于滚动 90% 分位才允许入场。四段或九腿任一失败时，filtered composite
   为空；阈值只用当日之前的数据。

报价量、tick count 和 spread 是 Dukascopy 活跃度/流动性代理，不是全市场成交量、签名订单流
或 CME 期货持仓。宏观公告只允许做“实际发布时间前 30 分钟至后 60 分钟禁止开仓”的过滤；
没有带真实发布时间和 PIT consensus 的授权数据前，禁止挖掘 actual-minus-consensus surprise。

### 日内统计单位

- 定盘研究的独立单位是事件日，不是窗口内 tick 数；
- 本地时段和 Asia–London 的独立单位是共同交易日；
- 同一天、同一货币的相关货币对必须联合重采样；
- 时间块覆盖至少一个完整周，并对月末、节假日、DST 切换日和危机日分层报告；
- 东京、伦敦和柏林时间必须使用 IANA timezone，并在 manifest 记录 tzdb 版本；
- 文献中的 gross midquote 效应若在 bid/ask 后为负，直接否决，不能靠缩短窗口反复调参挽救。

## 成本优先的回测顺序

任何方向信号都按以下顺序评价，不能先看 midquote 毛收益再挑成本模型：

1. 用当时可成交侧构造单笔收益：多头 ask 入/bid 出，空头 bid 入/ask 出；
2. 叠加可解释的滑点模型，按正常、新闻、低流动性状态分别估计；
3. 慢周期逐日计入与目标账户匹配的 swap/rollover 和多倍计息日；
4. 把所有 sleeve 汇总后只对主账户净换手计费；
5. 报告 1.0x、1.5x、2.0x 成本压力；
6. 分品种、年份、市场状态和事件类型报告贡献，检查是否被单一危机或单一货币驱动。

OANDA 公开融资表只覆盖 2025–2026，且监管实体/账户组未必与目标账户一致。它可以作为
2016–2025 的不利融资压力，但不能写入“历史已实现净收益”。在目标 broker 历史 swap 缺失时，
慢周期组合最多得到 `cost_incomplete_research_only`，不能晋级为经验可交易候选。

## 搜索账本和防过拟合契约

`configs/factor_research_registry.yaml` 是唯一搜索账本，
`outputs/research_registry_audit.json` 是机器审计结果。执行新一轮前必须完成：

1. 登记 hypothesis ID、经济机制、完整公式、预期符号、期限、eligible symbols、缺失规则、
   normalization、数据依赖、市场数据截止时间和否决阈值；
2. 把所有窗口、交互、阈值和模型变体计入搜索预算，不能只登记最后留下的版本；
3. 运行后保存完整产物路径和 SHA-256，并登记 fold-level hypothesis tests 和
   factor-outcome evaluations；
4. 无效实现也保留在账本中。方法无效不代表已经看过的收益结果可以“取消查看”；
5. 新增 v4 及以后轮次必须先通过 registry audit，再打开下一份结果；
6. 已查看至 `2026-07-13` 的历史永远不能恢复为 untouched；最终只认冻结后的新增时间。

每折的所有方向和期限组合进入一个统一多重检验家族。BH FDR 10% 是最低门槛，同时输出 BY
依赖稳健性；经验 p 值使用 `(k+1)/(B+1)`，永远不报 0。组合挑选还要用 White Reality Check
或 Hansen SPA 检查数据窥探，最终 Sharpe 同时报告 Deflated Sharpe 和 PBO。

负对照必须在正式结果之前固定：

- 保持横截面相关结构的共同日期块置换；
- 与经济含义无关、但覆盖率相近的 shadow factors；
- 故意含未来信息的 canary，必须被 availability audit 拒绝；
- 标签符号或事件日期的联合随机化，检查完整管线是否产生虚假发现。

负对照失败意味着研究管线拒绝，不是某个因子拒绝。

## 阶段晋级与否决标准

### G0：数据和时间审计

必须全部通过：SQLite/CSV SHA-256、SQLite integrity、逐小时深度解码、bid/ask 不交叉、UTC
排序去重、无未恢复下载失败、共同时间覆盖、标签时间顺序、PIT `available_time` 和来源
manifest。慢周期正式输入要求每品种至少 10 年、单品种市场覆盖至少 80%、共同日期覆盖至少
90%；所有缺失都必须显式标记，不能插值制造报价。

任一失败：停止看收益，修复数据后重新生成全新 manifest。

### G1：训练内发现

方向因子必须在预注册符号下满足统一 BH FDR `q<=0.10`，并达到预设最小经济效应。风险状态
只对绝对收益/流动性/回撤目标检验。bootstrap 样本数必须满足 `ceil(m/q)-1` 分辨率硬门槛；
BY、共同日期块和负对照必须同时生成。

零方向因子通过：接受空模型并停止方向组合开发。不能选择“最接近显著”的候选继续交易回测。

### G2：非重叠 OOS 和稳健性

至少要求：

- 多个非重叠 OOS 窗口与预期同号，不依赖一个危机区间；
- 小幅改变调仓日、持有期、winsorization、缺失规则和 block 长度不翻号；
- 分品种和分年份后没有单一来源垄断全部收益；
- shadow/permutation 没有表现出相似“发现率”；
- 通过的方向因子在真实 bid/ask 下仍有正的成本前余量。

2016–2025 只有一个 8+2 切分，所以 Dukascopy 单独不能完成本关。它可以否决候选、校验
成交侧和确认近十年迁移性；要晋级仍需更早的严格数据或冻结后的新前向时间。

OOS 翻号、只在一个训练折入选、只由一个品种/年份贡献或对邻域扰动翻号：否决。v4 的两个
风险状态因子正属于“单折入选且 OOS 翻号”，当前已否决。

### G3：成本调整组合

只有 G2 方向候选才能进入。组合必须使用资本守恒 sleeve、单一主账户净额、每日 MTM、共享
币种敞口和真实融资。沿用当前严格开发门槛：总交易数至少 100，至少 75% 开发折为正，每折
PF 不低于 1.10，且 1.5x 成本下复合收益仍为正；2.0x 作为尾部压力完整报告。

基准成本为负、1.5x 转负、缺历史融资、PF/样本量不足或回撤来自无法执行的 bar 内路径：
否决或保持 `research_only`，不得冻结交易模型。

### G4：一次性冻结后前向期

通过前述门槛只能得到 `research_candidate_requires_new_holdout`。冻结因子公式、系数、阈值、
风险、成本、数据前缀哈希和代码版本后，只接受严格晚于冻结时间的数据；不重选因子、不重拟合。
少于 90 天只标记 `collecting`，完整 paper/practice 期至少 3–6 个月，并覆盖不止一种波动状态。

前向失败就淘汰，不能在同一前向期调参后继续称其为 holdout。前向通过也只得到
`research_candidate_requires_paper_review`，不自动授权真实资金。

## Dukascopy 到达前的动作

按顺序完成，期间不新增结果驱动的窗口搜索：

1. 已完成 RTDSM 真 vintage 与 OFR/CISS/BCPI/RBA/Cboe FX IV current-vintage 下载、解析和
   快照归档；
2. 已完成共同日期块重采样、BY 敏感性、负对照和 availability canary 核心；
3. 已完成 IANA timezone、Tokyo/ECB/WMR 官方发生日历和 `LOCAL-PAPER` 见数前契约修订；
   下一步只为 ASIA-LDN 的预注册敏感性补金融中心节假日输入；
4. 已完成 SQLite 纽约收盘执行报价、factor-only 冻结候选、21/42/63 日次日开盘信号调度，
   以及开盘/收盘两阶段合成事件账本；下一步串联账户币种 quantity/FX conversion、cost basis、
   历史 financing、slippage/commission 与逐品种 quote time，缺任一输入时不生成正式净收益；
5. 继续为目标 broker 历史 swap/真实 forward points 准备 PIT 数据契约，缺数据时保持硬失败；
6. 每轮继续更新搜索账本并运行：

```bash
uv run fxtrade research-registry-audit \
  -r configs/factor_research_registry.yaml \
  -o outputs/research_registry_audit.json
```

7. 只做软件级测试、合成数据负对照和下载器校验，不继续反复查看 Yahoo 最优因子。

Tokyo/ECB/WMR 正式事件日历可重复生成：

```bash
uv run python scripts/download_wmr_publication_calendar.py \
  --output-dir data/benchmark_calendars \
  --refresh
```

它保留 6 份官方/Internet Archive 原始证据、逐文件 SHA-256 和 CSV manifest。LSEG 原始文档
只供本地研究审计；重新分发前必须另行核对发布方条款。目前 WMR 例外表是根据这些
官方 PDF 逐行人工转录，关键半日市有测试覆盖，但尚未由 PDF 文本自动反解并二次核对。
这是事件日历的剩余操作风险，不得因为原始文档来自官方就省略人工转录审计。

## Dukascopy 到达后的动作

### 1. 验证转移

数据库、每库 `.sha256` / `.json` 和 `_sqlite_manifest.json` 必须同目录：

```bash
uv run python scripts/download_dukascopy_sqlite.py verify \
  --database-dir ./dukascopy_sqlite

uv run python scripts/download_dukascopy_sqlite.py verify \
  --database-dir ./dukascopy_sqlite \
  --deep
```

正式研究不得跳过失败库，不得手工修改数据库，也不得用 `--allow-incomplete` 绕过审计。

### 2. 生成彼此独立的研究输入

慢周期生成 4h bid/ask：

```bash
uv run python scripts/download_dukascopy_sqlite.py aggregate \
  --database-dir ./dukascopy_sqlite \
  --output-dir ./data/dukascopy_bid_ask \
  --start 2016-01-01 \
  --end 2026-01-01 \
  --interval 4h
```

ASIA-LDN 粗粒度诊断和旧 LOCAL 探索模板可生成 1h bid/ask 到独立目录：

```bash
uv run python scripts/download_dukascopy_sqlite.py aggregate \
  --database-dir ./dukascopy_sqlite \
  --output-dir ./data/dukascopy_bid_ask_1h \
  --start 2016-01-01 \
  --end 2026-01-01 \
  --interval 1h
```

正式 FIX-W 与 `LOCAL-PAPER` 都不使用上述 1h 输出代替 tick；从原 SQLite payload 按冻结
边界邻域另行提取。每个库先
用 `.sha256`、`.json` 和 `_sqlite_manifest.json` 做一次整库 SHA-256/quick-check，得到不可变
transfer receipt；之后窄窗逐 payload 复验哈希，并保存事件级源小时哈希、DST/tzdb 版本。

当前正式编排入口只覆盖 `fx_system.intraday_runner.run_fix_w_from_sqlite`；`LOCAL-PAPER`
已有合成报价构造与组合契约，但 SQLite 窄窗 runner 尚未接入。FIX-W runner 在单次调用内对
9 个 G9 腿数据库各计算一次可复用 transfer receipt，每日按 6 个独特边界提取
54 个库—边界窄窗，输出腿、G9 composite、边界小时审计和 transfer audit。receipt
是当次运行的内存验证对象，项目不会自动把它另存为文件；正式调用方必须持久化
`transfer_audit` 和其他输出。缺源小时会清空影响腿及整日组合，不会用其他腿补权。
该函数接收已构造的 `PublicationCalendar`；正式调用方必须先用
`load_publication_calendar(..., require_manifest=True)` 验证 CSV、manifest 和所有 raw source。
下游 FIX-W 构造层还会硬检查 `formal_experiment` 和 `manifest_verified`，所以人工构造的
未验证 calendar 不能产生正式结果；已验证的 calendar/raw 哈希不会在每个事件窄窗内重算。

当前日内统计入口是 `fx_system.intraday_validation`。正式运行必须声明候选集完整，
以严格共同事件日交集构建净收益矩阵，不填充缺口。推断层使用 joint stationary
bootstrap、`(k+1)/(B+1)` 经验 p 值、BH 主门槛、BY 敏感性、FDR 分辨率硬门槛、
共同日期 Rademacher 符号负对照和 future-information canary；DSR 与 16 块 CSCV/PBO
为诊断；透明 SPA 核心已经实现，但正式组合入口仍只准备严格输入、尚不执行 SPA。SPA 只校正
实际传入的候选列，不能把 7 条收益列说成覆盖 3,312 次历史搜索。任何统计选中都不自动批准交易。

### 3. 先审计，后看因子

```bash
uv run fxtrade long-horizon-build \
  -c configs/long_horizon_dukascopy.yaml \
  -o outputs/long_horizon_dukascopy_build
```

先检查每个品种起止时间、缺失小时、spread 分布/尾部、共同调仓日、long/short 可成交标签、
外部数据 staleness、PIT 资格和全部哈希。G0 未通过，不运行 screen。

### 4. 只打开预注册结果

G0 通过后，按搜索账本中的固定 43 因子和日内事件族运行一次。Dukascopy 结果必须另记为
“execution-transfer / reused-market-history”，不能写成 untouched replication。结果为零或翻号时
保持空模型；结果通过时继续 G2/G3，不现场增加窗口。

### 5. 冻结并开始收集真正的新证据

只有完整成本组合通过，才冻结 contract hash 并开始 OANDA practice 或目标 broker paper
前向期。之后的重点从“找更好因子”转为核对实际 spread、slippage、rollover、拒单、时钟、
断线恢复和信号—成交差异。

## 已核验的研究依据

慢周期因子：

- Menkhoff et al., Currency Momentum，<https://doi.org/10.1016/j.jfineco.2012.06.009>
- Menkhoff et al., Currency Value，<https://doi.org/10.1093/rfs/hhw067>
- Lustig, Roussanov & Verdelhan, Common Currency Risk Factors，
  <https://doi.org/10.1093/rfs/hhr068>
- Menkhoff et al., Carry Trades and Global FX Volatility，
  <https://doi.org/10.1111/j.1540-6261.2012.01728.x>
- Brunnermeier, Nagel & Pedersen, Carry Trades and Currency Crashes，
  <https://doi.org/10.1086/593088>
- Moskowitz, Ooi & Pedersen, Time Series Momentum，
  <https://doi.org/10.1016/j.jfineco.2011.11.003>
- Commodity Trade and the Carry Trade，<https://doi.org/10.1111/jofi.12546>
- Can Oil Prices Forecast Exchange Rates?，<https://doi.org/10.1016/j.jimonfin.2015.03.001>

日内与成本：

- Foreign Exchange Fixings and Returns around the Clock，
  <https://doi.org/10.1111/jofi.13306>
- Intraday Patterns in FX Returns and Order Flow，
  <https://doi.org/10.1111/jmcb.12032>
- Equity Hedging and Exchange Rates at the London 4 p.m. Fix，
  <https://doi.org/10.1016/j.finmar.2014.11.001>
- Liquidity in the Foreign Exchange Market，<https://doi.org/10.1111/jofi.12053>
- Micro Effects of Macro Announcements，<https://doi.org/10.1257/000282803321455151>

多重检验和过拟合控制：

- Benjamini–Hochberg FDR，<https://doi.org/10.1111/j.2517-6161.1995.tb02031.x>
- Benjamini–Yekutieli dependent FDR，<https://doi.org/10.1214/aos/1013699998>
- White Reality Check，<https://doi.org/10.1111/1468-0262.00152>
- Hansen SPA，<https://doi.org/10.1198/073500105000000063>
- Stationary Bootstrap，<https://doi.org/10.1080/01621459.1994.10476870>
- Empirical p-values should never be zero，<https://doi.org/10.2202/1544-6115.1585>
- Deflated Sharpe Ratio，<https://doi.org/10.3905/jpm.2014.40.5.094>
- Probability of Backtest Overfitting，<https://doi.org/10.21314/JCF.2016.322>
- Taming the Factor Zoo，<https://doi.org/10.1111/jofi.12883>

## 最终判定原则

可接受的研究结果包括“没有因子”“数据不够”“成本后为负”和“只能继续收集前向数据”。不可
接受的结果是把 current-vintage 当 PIT、把政策利率叫 OIS、把 2025–2026 融资套到十年历史后
称为实际净收益、把风险状态叫方向 alpha，或在查看 holdout 后继续调参仍称其为样本外。

项目真正追求的是一个可被证伪、成本后仍有余量、冻结后还能在新时间里复现的过程。只有这个
过程反复通过，才可能谈盈利；当前还没有这样的证据。
