# 外汇因子与验证方法文献地图

更新日期：2026-07-17。

这份地图只收录能转化为明确数据契约或可证伪实验的资料。论文中的毛收益、midquote 异象和
资产定价解释都不自动等于散户保证金账户可实现利润；项目最终只接受真实 bid/ask、滑点、
融资和完整搜索暴露后的证据。

## 2026-07 可重复研究发现与人工分流

`scripts/discover_fx_research.py` 已用五组固定 OpenAlex 查询保存原始响应、内容哈希、归档、
候选 CSV 和 manifest。本轮得到 249 条 query-match、245 篇唯一论文；候选 CSV 的 SHA-256 为
`8c8374f5e9b50b47549ff789168e702e51dc31690ed0eafd47a94dd56058c1b1`。OpenAlex 只用于发现，
引用数只用于安排阅读顺序；论文结论必须回到正文、公式和页码核验。所有记录仍为
`candidate_unreviewed_not_registered`，本轮 `factor_registry_modified=false`、
`outcome_evaluations_added=0`。

人工审查以唯一论文为单位，优先用规范化 DOI 去重，其次用 OpenAlex ID。每条决定必须保留
全部 query hit、审查日期、候选 CSV/manifest/正文 SHA、正文证据页码、复制或项目扩展身份、
观测量、频率、PIT 时钟、报价方向、许可、成本、benchmark 和否决条件。分类变更只能追加新
版本，不能覆盖旧决定：

- `CONTRACT_READY_NO_OUTCOME`：现在可以冻结 schema、时钟、合成 canary 或研究流程，但不读
  方向收益；
- `DEFERRED_HARD_DATA`：缺少不能被 spot、tick count 或 current-vintage 替代的硬输入；
- `METHOD_OR_NEGATIVE_CONTROL`：只提高证据门槛或提供失败先验，不产生新方向候选。

首轮 20 篇高价值短名单如下。这里的“合同就绪”不代表策略或因子获准：

| 状态 | 论文 | 当前可做或阻塞原因 |
|---|---|---|
| CONTRACT | [Foreign Exchange Fixings and Returns around the Clock](https://doi.org/10.1111/jofi.13306) | 冻结 Tokyo/ECB/WMR 时钟、prevailing quote、持有窗口和 bid/ask 成本；不读方向收益 |
| CONTRACT | [Risk Everywhere: Modeling and Managing Volatility](https://doi.org/10.1093/rfs/hhy041) | 建立 realized-volatility、风险预测损失和交易速度合同；只作风险模型 |
| CONTRACT | [Currency Factors](https://doi.org/10.1287/mnsc.2021.4023) | 先做 G10 spot 距离、滚动相关和聚类稳定性；交易量 world factor 仍缺 |
| CONTRACT | [Robust monitoring machine](https://doi.org/10.1186/s40854-023-00497-z) | 冻结创意时间、sealed evaluation、benchmark、训练内 shrinkage 和人工查看日志 |
| CONTRACT | [Forecast evaluation for data scientists](https://doi.org/10.1007/s10618-022-00894-5) | 固定时间切分、共同日期、误差指标、benchmark 和统计比较清单 |
| DEFERRED | [Foreign Safe Asset Demand and the Dollar Exchange Rate](https://doi.org/10.1111/jofi.13003) | 缺 Treasury basis、跨币种 hedge/forward 和对应债券收益率；TIC 不是 basis |
| DEFERRED | [Information Flows in Foreign Exchange Markets](https://doi.org/10.1111/jofi.12378) | 缺 dealer 按客户类型拆分的签名订单流 |
| DEFERRED | [Foreign Exchange Volume](https://doi.org/10.1093/rfs/hhab095) | 缺 OTC 真实成交量；报价更新次数不能替代 |
| DEFERRED | [Foreign Exchange Order Flow as a Risk Factor](https://doi.org/10.1017/S0022109024000796) | 缺金融/非金融客户买卖压力；正式引用前还须核验出版年份元数据冲突 |
| DEFERRED | [The Term Structure of Currency Futures' Risk Premia](https://doi.org/10.1111/jmcb.12872) | 缺多期限期货、到期、roll、settlement、保证金和成本 |
| DEFERRED | [Forecasting with long maturity forward rates](https://doi.org/10.1016/j.jimonfin.2024.103067) | 缺真实长久期 forward；利率平价合成值不是论文观测量 |
| DEFERRED | [A Fundamental Connection](https://doi.org/10.29412/res.wp.2020.20) | 缺逐期调查预测和 surprise vintage；当前 paratext 元数据须先隔离核验 |
| DEFERRED | [Panel Methods And Real-Time Data](https://doi.org/10.71889/5fylantbak.29870426) | 缺九国同口径 real-time PPP/Taylor-rule 面板 |
| DEFERRED | [Time-varying factor loadings](https://doi.org/10.1002/jae.2984) | 缺 FRED-MD/OECD 逐版 vintage 证据链和完整货币覆盖 |
| DEFERRED | [To fix or not to fix](https://doi.org/10.1016/j.pacfin.2024.102311) | 精确复制缺 Refinitiv order book；Dukascopy 只能作为单一报价源扩展 |
| METHOD/NEGATIVE | [Currency Risk Premiums Redux](https://doi.org/10.1093/rfs/hhad049) | 作为强空模型先验和 benchmark，不授权新增方向因子 |
| METHOD/NEGATIVE | [Are carry, momentum and value still there?](https://doi.org/10.1016/j.irfa.2022.102245) | 作为发表后衰减负对照；不得据此反向交易或重调参数 |
| METHOD/NEGATIVE | [… and the Cross-Section of Expected Returns](https://doi.org/10.1093/rfs/hhv059) | 提高多重检验门槛并披露完整因子动物园；不是 FX 策略 |
| METHOD/NEGATIVE | [Causal Factor Investing](https://doi.org/10.1017/9781009397315) | 要求机制图、混杂路径和 falsifier；因果叙述不减少 FDR 分母 |
| METHOD/NEGATIVE | [Simple machine learning methods](https://doi.org/10.1016/j.jimonfin.2018.06.003) | 简单模型优先的方法线索；取得并哈希正文、核验 PIT 后再重新分类 |

明确禁止五类代理替换：`tick count ≠ OTC volume`、`quote size ≠ signed flow`、
`TIC ≠ Treasury basis`、`synthetic forward ≠ observed forward`、
`current vintage ≠ PIT macro`。只有正文、许可、PIT、报价方向、成本和 falsifier 均完整，且在
读取收益前更新检验族，论文才可能进入因子 registry。

## 慢周期因子

| 主题 | 主要证据 | 可测试含义 | 本项目边界 |
|---|---|---|---|
| Carry | [Lustig, Roussanov & Verdelhan](https://doi.org/10.1093/rfs/hhr068)；[Menkhoff et al.](https://doi.org/10.1111/j.1540-6261.2012.01728.x) | 远期折价横截面与全球 FX 波动风险相关 | 必须有当时可交易的 forward points/OIS 或目标账户历史 swap；政策率不是 OIS |
| Carry crash | [Brunnermeier, Nagel & Pedersen](https://doi.org/10.1086/593088) | 高息货币在融资压力和波动跃升时可能出现负偏度/拥挤平仓 | 风险门控必须在信号前冻结，不能看危机结果后选择阈值 |
| Currency momentum | [Menkhoff et al.](https://doi.org/10.1016/j.jfineco.2012.06.009) | 过去 1–12 个月相对强弱可形成横截面排序 | 21/63/126/252 日和 skip-21 已进入搜索账本；v4 没有方向晋级 |
| Time-series momentum | [Moskowitz, Ooi & Pedersen](https://doi.org/10.1016/j.jfineco.2011.11.003) | 单资产自身趋势可作为方向状态 | 只能使用已收盘价格；持有重叠须用资本守恒 sleeve |
| Currency value | [Menkhoff et al.](https://doi.org/10.1093/rfs/hhw067) | REER 相对长期均值可度量价值偏离 | BIS REER 为 current-vintage，历史结果只用于探索并需要新前向期 |
| Commodity currencies | [Ready, Roussanov & Ward](https://doi.org/10.1111/jofi.12546)；[Ferraro, Rogoff & Rossi](https://doi.org/10.1016/j.jimonfin.2015.03.001) | 贸易结构和商品价格可能影响商品货币及油价相关汇率 | Pink Sheet 为 USD 计价 current-vintage；需防止机械美元内生性 |
| External imbalances | [Della Corte, Riddiough & Sarno](https://doi.org/10.1093/rfs/hhw038) | 国家外部资产负债表可能解释货币风险溢价 | 免费范围缺少同口径、逐期可得的八币种数据，暂不实现 |
| Carry quality | [Hassan & Mano](https://doi.org/10.1017/S0022109019000887) | 不同来源的 carry 回报可能具有不同风险含义 | 先验证真实 forward 与融资来源，再讨论组合分解 |
| Currency liquidity premia | [Söderlind & Somogyi](https://doi.org/10.1287/mnsc.2023.01031) | 不是按 spread 水平，而是按货币收益对全市场或本币种流动性冲击的暴露排序 | 原文依赖逐日 1M forward excess return，日调仓且主表未扣交易成本；G9 子集和 21/42/63 日持有都是项目扩展 |
| Volatility-managed carry | [Moreira & Muir](https://doi.org/10.1111/jofi.12513)；[NBER 原文](https://www.nber.org/papers/w22208) | 用 carry 组合自己上一个月的实现方差倒数缩放下月敞口 | 这是已有 carry 的仓位管理，不是新方向；原文没有 global-FX-vol 阈值，仍须真实 forward 和融资成本 |
| Option-implied VRP / risk reversal | [Della Corte, Ramadorai & Sarno](https://doi.org/10.1016/j.jfineco.2016.02.015) | 一年期 OTC option smile 可给出横截面 VRP 和 10-delta risk-reversal 排序 | 免费 Cboe 序列只有三个币种的 30 日 IV 且中途停止，不能冒充这两个方向因子 |
| Value-momentum joint evidence | [Asness, Moskowitz & Pedersen](https://doi.org/10.1111/jofi.12021) | 价值与动量在多个资产类别中可共同作为经济机制，而非二选一技术指标 | 不是对本项目 REER 代理、权重或 agreement gate 的精确复制；不得据此追加一个事后选择的组合规格 |
| Cross-currency basis / dollar funding | [Borio et al.](https://www.bis.org/publ/qtrpdf/r_qt1609e.htm)；[Borio, McCauley & McGuire](https://www.bis.org/publ/qtrpdf/r_qt2212h.htm) | CIP 偏离和 FX-swap 隐含美元融资可解释为何远期与现金利差不能互换 | 需要同期双边 forward、现金利率/OIS、结算日和报价侧；免费低频 BIS 统计只能做机制/风险状态，不给 G9 每日方向 |

慢周期的优先级不是继续枚举技术指标，而是先回答三个更硬的问题：方向是否跨折同号、真实
spread/rollover 后是否仍有余量、同一机制是否能在冻结后的新增时间存活。

## 新核验机制及其数据契约

以下四个主项及后面的否决边界是在未读取 Dukascopy 因子结果的前提下核验的。它们补全了
未来可能用到的合同，但不自动增加方向候选；若将来决定加入搜索，必须先修改注册表、搜索
预算和 FDR 分母，再读取对应收益。

### 流动性风险溢价：可实现，但真实 1M forward 是硬依赖

[Söderlind & Somogyi (2024)](https://doi.org/10.1287/mnsc.2023.01031) 的原文和公式均为
开放访问。原文用 15 个 USD 腿、Olsen 小时报价和 Bloomberg 逐日 1M forward，样本为
1994-01-03 至 2022-09-30。与现有的“入场 spread 不超过历史 q90”执行过滤不同，它研究
的是横截面流动性**风险暴露**。两个有风险溢价证据的合同是：

```text
r_i,t = (f_i,t-22,t - s_i,t) / 22
v_i,t = abs(s_i,t - s_i,t-22)
bas_i,t = (ask_i,t - bid_i,t) / mid_i,t
c_i,t = 0.5 * [ expanding_z_252(bas_i,t)
                + expanding_z_252(CorwinSchultz(high_ask, low_bid)_i,t) ]
c_M,t = equal_weight_mean_i(c_i,t)
v_M,t = equal_weight_mean_i(v_i,t)
```

其中 `s` 和 `f` 是“每一 USD 对应多少外币”的对数间接报价；`f_i,t-22,t` 是 22 个营业日
前签订、在 `t` 到期的真实一月远期。每条 z-score 从 252 日初始窗开始递归估计，不能用
全样本均值和标准差。随后分别以 252 日初始窗的 expanding regression 做波动正交化：

```text
delta22(c_M) = alpha + delta * delta22(v_M) + delta22(c_M_tilde)
delta22(c_i) = alpha + delta * delta22(v_i) + delta22(c_i_tilde)
```

再用每日 252 日 rolling regression 估计两个关键暴露：

```text
beta2_i,t: r_i ~ delta22(c_M_tilde)
beta4_i,t: r_i ~ delta22(c_i_tilde)
```

beta 先取过去 10 日均值，再把交易信号滞后 22 个营业日。原文每天把 15 个 USD 腿分为
tertiles，每组最多五腿、组内等权；其因子定义为做多最高 beta、做空最低 beta。这个定义下
`SIR-beta2` 和 `AIR-beta4` 的已发表平均溢价是负号，符合论文的风险定价方向；若要表达正的
预期风险补偿，交易方向必须在见本项目数据前明确冻结为其相反数，不能看结果后翻向。

原文复制与项目扩展必须严格分开：

- 精确复制需要 AUD、CAD、DKK、EUR、HKD、ILS、JPY、MXN、NZD、NOK、SGD、ZAR、
  SEK、CHF、GBP 共 15 个 USD 腿和逐日真实 1M forward；当前 G9 只有其中九腿。
- 原文为每日重排、重叠 22 日 forward return，表 3 明确未扣交易成本。改成每 21 日调仓、
  持有 21/42/63 日、使用固定 sleeves，均是为本项目 1--3 月周期设计的扩展。
- Dukascopy 的 tick bid/ask 可构造 daily close spread、high ask 和 low bid，但这是从 Olsen
  向单一零售报价源的执行迁移；它没有补上 forward，也不提供全市场流动性。
- 用 spot 22 日收益代替 `r_i` 会同时删除远期溢价和融资，不能称为论文复制。正式方向
  候选仍应 fail closed；在 forward 到位前只适合实现报价端数据质量和公式 canary。
- 论文样本覆盖到 2022-09，而且本项目此前看过相同市场历史的其他因子；即使将来实现，
  仍按 reused-history 处理并要求冻结后的新前向证据。

### Volatility-managed carry：复制的是 own-factor RV，不是阈值门控

[Moreira & Muir](https://doi.org/10.1111/jofi.12513) 的 FX 部分使用按远期折价排序的
high-minus-low carry factor，并用该 carry 组合自己上一个自然月的逐日收益计算实现方差：

```text
f_sigma,t+1 = c / RV2_t(f) * f_t+1
RV2_t(f) = sum_{d in month t} (f_d - mean_t(f))^2
```

每月只在月初更新一次敞口。`c` 在论文中用于让 managed 和 unmanaged 组合具有相同的
无条件波动，不改变策略 Sharpe；但它用到了全样本波动，正式 PIT 实现必须改为在训练期
冻结的 `c` 或事前固定 target volatility。论文的主规格没有离散阈值，也不是用 VIX、
global FX volatility 或 `global_fx_vol_innovation_z < 1` 决定是否交易。

因此，本项目现有的 `slow_carry_volatility_gate` 是有经济动机的项目扩展，不是
Moreira--Muir 复制。若以后保留 exact sensitivity，它应是同一个 carry 方向组合的
no-threshold、own-factor inverse-variance sizing，而不是新增方向因子；真实 1M forward、
可成交 bid/ask、rollover/融资和杠杆上限仍然先决。不能用政策率构造的“carry”来宣称复制。

### Cboe 免费 FX IV：只够做三币种风险状态

Cboe 的官方 dashboard 和 CSV 当前免费提供四条 VIX-style 30 日预期波动序列：

| 货币 | 官方定义与 CSV | 当前文件覆盖 |
|---|---|---|
| EUR | [EVZ dashboard](https://www.cboe.com/us/indices/dashboard/evz/)；[CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/EVZ_History.csv) | 2009-09-18 至 2025-03-11；CurrencyShares Euro Trust option |
| EUR | [EUVIX dashboard](https://www.cboe.com/us/indices/dashboard/euvix/)；[CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/EUVIX_History.csv) | 2008-01-07 至 2022-11-07；CME EUR/USD futures option |
| JPY | [JYVIX dashboard](https://www.cboe.com/us/indices/dashboard/jyvix/)；[CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/JYVIX_History.csv) | 2008-01-07 至 2022-11-07；CME JPY/USD futures option |
| GBP | [BPVIX dashboard](https://www.cboe.com/us/indices/dashboard/bpvix/)；[CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/BPVIX_History.csv) | 2008-01-07 至 2023-07-14；CME GBP/USD futures option |

它们都是从跨越 30 日的两个期权期限、按 VIX 方法插值得到的年化隐含波动。文件每份约
76--80 KiB，下载成本可以忽略，但没有覆盖完整 2016--2025，更没有 AUD、CAD、CHF、
NOK、NZD、SEK。

这与 [Della Corte et al.](https://doi.org/10.1016/j.jfineco.2016.02.015) 的合同不同。后者
在每个月末使用一年期 OTC 的 ATM、10/25-delta risk reversal 和 butterfly 五点 smile：

```text
VRP_i,t = realized_volatility_i,t-252:t - model_free_implied_volatility_i,t,1y
RR_i,t  = IV_i,t,1y,10delta_call - IV_i,t,1y,10delta_put
```

原文分别对 VRP 和 RR 做五分位、等权、月度持有：VRP 做多最高组/做空最低组；RR 做多
最低组/做空最高组。所需 option smile 来自 JP Morgan，利率和 strike 转换来自 Bloomberg。
所以 Cboe 序列最多是 EUR/JPY/GBP 的非方向风险状态或机制审计；把 30 日 IV 减 21 日 RV
得到的代理必须标成项目扩展，不能叫一年期横截面 VRP，也不应进入方向候选。

### 远期、CIP 与资金压力：约束不是可替代因子

[Borio et al. (2016)](https://www.bis.org/publ/qtrpdf/r_qt1609e.htm) 将 cross-currency basis
定义为通过 FX swap 借入某一货币的成本相对于在现金市场直接借入的差额，并记录了金融危机后
CIP 偏离持续存在；[Borio, McCauley & McGuire (2022)](https://www.bis.org/publ/qtrpdf/r_qt2212h.htm)
进一步说明 FX swaps、outright forwards 与 currency swaps 的美元付款义务存在于表外，且常规
债务统计不直接给出其地理和交易对拆分。这两篇资料的用途是收紧数据合同，而不是发明一个
“美元资金方向”因子。

对任何声称为 carry、forward excess return 或 CIP basis 的慢周期实验，单期输入至少必须同一
来源地保留：

```text
quote_timestamp, available_time, pair_and_quote_convention, tenor,
spot_bid, spot_ask, forward_bid, forward_ask,
spot_settlement_date, forward_settlement_date, venue_or_account
```

从政策利率、隔夜参考利率或利率平价公式生成的 `F_hat` 可以作为压力测试中的**合成**数值，
但不是观察到的市场 forward；即使获得一组 OIS，也不能因此把 `F_hat` 重新命名为可交易
forward。缺少其中任一侧、期限或结算约定时，严格 carry 与 CIP 检验 fail closed。BIS 的
全局统计没有逐日、逐货币对、带买卖价的这一合同，不能用于补洞；它们不增加注册表的方向候选
或 FDR 分母。

### 免费全球流动性统计：只允许发布后的低频风险状态

以下 BIS 数据是理解资金压力、期限错配和流动性供给的高质量公开资料，但频率和聚合层级决定
它们不能直接回答“下一根 FX bar 的方向”。

| 官方资料 | 可观测内容 | 频率和可允许用途 | 明确禁止的推断 |
|---|---|---|---|
| [Global liquidity indicators (GLI)](https://data.bis.org/topics/GLI) | 非居民借款人的 USD/EUR/JPY 外币信贷，含银行贷款与国际债券 | 季度；仅在该期**发布后**做 global-funding 风险状态或慢周期条件分层 | 不把全球 USD credit 的变动解释为任一 G9 货币对的可交易方向 |
| [Locational banking statistics (LBS)](https://data.bis.org/topics/LBS) | 报告银行的跨境头寸及国家/币种维度；官方同时公布 revision/break 信息 | 季度；用于覆盖、单位和结构断点审计，或预注册的低频风险状态 | 不把 aggregate claim/liability 当现货订单流、每日资金流或净投机仓位 |
| [OTC derivatives statistics](https://data.bis.org/topics/OTC_DER) | OTC FX 等衍生品的 outstanding notional、市场价值和信用暴露 | 半年；可审计总量、期限和集中度机制 | 不从 USD 换算后的存量变化推断即期方向；汇率本身会改变换算后的水平 |
| [Triennial Survey](https://www.bis.org/statistics/rpfx22.htm) | 四月的一次性全球 FX turnover、货币、工具和交易对手结构 | 三年；只校准结构性市场覆盖、流动性假设和样本外推边界 | 不能作为月度、日内或拥挤度时间序列；更不能用于调参后的收益解释 |

BIS 门户提供公开表、元数据和 release calendar，但本项目尚未取得每次历史发布的 as-published
响应链。因此 2016--2025 的历史行默认 `strict_pit_eligible=false`，除非每次历史发布都有对应的
as-published 原始响应、发布日/时间证据、数据结构版本和 revision/break 文件。未来从现在开始
按发布日保存的原始响应，才可成为其后时间段的自建 forward vintage。对于本项目，低频状态只
能在下一个保守决策日生效；不能用 observation quarter 末日加人为 lag 伪造过去已经可知。

### 公开宏观 vintage 与预测调查：有时间版本不等于有日内 surprise

[ALFRED](https://alfred.stlouisfed.org/) 明确支持检索“某个历史日期当时可得到”的经济数据
vintage；它可以在 RTDSM 覆盖之外，作为少量已审计美国宏观状态序列的候选来源。当前已冻结
CPIAUCSL、INDPRO、PAYEMS、UNRATE、GDPC1 五个目录项，但本机没有 `FRED_API_KEY`，因此
程序没有访问 API，也没有用 current-vintage CSV 降级替代。每个拟用
series 仍须逐一保存 real-time/vintage 查询、原始来源、单位/季调、发布日证据和 hash。只有
在这些证据完整时，它才可能成为月级或更慢决策的 day-level PIT 输入；ALFRED 查询本身不构成
原始公告的具体发布时钟证据，也不提供当时的预测中位数，所以不能支持秒/分钟级 surprise 或
替代 BLS/BEA 原始公告证据。

[ECB Survey of Professional Forecasters](https://www.ecb.europa.eu/stats/ecb_surveys/survey_of_professional_forecasters/html/index.en.html)
自 1999 年开始、每年发布四次 aggregate results 与 microdata，涵盖欧元区通胀、实际 GDP
增长和失业率的多个期限预期。它值得作为 EUR 宏观预期**状态**的资料目录；当前官方发现链
已归档 2018-Q3 至 2025-Q4 的 30/40 个季度；2016-Q1 至 2018-Q2
没有从当前目录发现，明确保持缺失。后续仍须核验确切公布时点和附件修订。它不是八币种一致
预期，也不是 `actual - median_consensus` 的宏观 surprise；不能据其构造日内方向规则。

这两个来源目前只扩大资料地图，不新增假设、参数网格或收益读取。任何从“状态”变成“方向”的
规则都必须先单独登记，并把新增规格计入完整检验族。

### Dealer balance sheet：2016--2025 只作负对照

[Fang (2019), Federal Reserve IFDP 1262](https://doi.org/10.17016/IFDP.2019.1262) 的主预测式为：

```text
delta_1m(USD_per_foreign_i,t)
  = beta0 + beta1 * delta_1m(log(DealerSTBorr_t-1))
    + beta2 * policy_rate_diff_i,t-1 + beta3 * X_t-1 + beta4 * X_i,t-1 + error

DealerSTBorr = overnight_and_continuing_repo + securities_lent
```

论文估计中，较高 dealer short-term borrowing 预测美元在随后一个月升值；周频响应累计值
约在 5--6 周达到峰值。但原文的机构拆分显示结果主要由在美外国 dealer 驱动，而外国/
美国总部拆分来自保密 FR 2004C 微观数据。更重要的是，论文明确报告预测力主要来自
2001--2011，约在 2010--2013 的滚动窗失去显著性，并把衰减与 Basel III、Volcker rule
和 leverage-ratio 约束联系起来。因此对完整处于新监管制度下的 2016--2025，事前用途是
负对照或 dealer-capacity 风险状态，不是方向 alpha。

纽约联储仍免费提供公开 aggregate：

- [Markets API 说明](https://markets.newyorkfed.org/static/docs/markets-api.html)
- [全部历史数值](https://markets.newyorkfed.org/api/pd/get/all/timeseries.csv)
- [当前字段定义](https://markets.newyorkfed.org/api/pd/list/timeseries.csv)
- [官方 series breaks](https://markets.newyorkfed.org/api/pd/list/seriesbreaks.json)

2016--2025 横跨 `SBN2015`、`SBN2022` 和 `SBN2024`，不能直接把不同调查定义拼接。正式
下载必须同时保存 guide sheet、字段映射、series-break 元数据和原始哈希。API 给的是当前
历史，不是逐次发布 vintage；调查为 dealer 自报且纽约联储声明不审计。公开 aggregate
只能复制论文的 aggregate 列，不能重建其 foreign-dealer 核心解释，因此不新增候选。

### 季节性、季度末和宏观公告的否决边界

- [Tse (2017)](https://doi.org/10.1080/13504851.2017.1290766) 在 1973--2015 G10 currency
  futures 中记录一月普遍负、四月正，但其按历史 same-calendar-month return 选组合的
  strategy 明确“不工作”。这不是增加十二个月份哑变量搜索的理由，不预注册季节性 alpha。
- [Du, Tepper & Verdelhan](https://doi.org/10.1111/jofi.12620) 的 quarter-end 合同不是“最后
  一个营业日做某个 spot 方向”：`QendW=1` 要求 T+2 settlement 落在本季度最后一周且
  1W forward maturity 落在下一季度；`QendM=1` 要求 1M forward 的 settlement 和 maturity
  跨季度。因变量是 1W/1M CIP basis 的绝对值，需要同步 spot、真实 forward 和相同期限
  OIS/repo/当时基准利率。只用 Dukascopy spot spread 做季度末检验是另一个执行扩展，不能
  声称复制 dealer balance-sheet/CIP 机制，也没有论文支持的 spot 方向。
- [Faust et al.](https://doi.org/10.1016/j.jmoneco.2006.05.015) 用公告前 5 分钟至后 15 分钟的
  20 分钟窗口，宏观 surprise 为 `actual - MMS median consensus`；其 1987--2002 样本多数
  美国数据在 08:30 ET，历史 FOMC 决定约在 14:15 ET。2016--2025 不能沿用旧 FOMC 时刻，
  必须逐事件核验实际发布时间。BLS、BEA、Census、DOL 和 Federal Reserve 官方页面可支持
  timestamp/blackout，不能免费补出当时 MMS/Bloomberg consensus；缺 consensus 时只能做
  预注册的公告风险/波动或禁止入场，禁止构造方向 surprise。

## 日内与微观结构

| 主题 | 主要证据 | 冻结实验 | 最重要的否决条件 |
|---|---|---|---|
| 全球定盘时点 | [Krohn, Mueller & Whelan](https://doi.org/10.1111/jofi.13306) | Tokyo 09:55、ECB 14:15、WMR 16:00 的预定义窗口 | 论文明确提示流动性索取方计入 bid/ask 后结果可转负；净成本不通过即否决 |
| 本地营业时段 | [Breedon & Ranaldo](https://doi.org/10.1111/jmcb.12032) | 固定 6 对 × 2 本币时段的 12 单元面板；重叠腿 open-to-open，其他 open-to-close；假日有边界报价即保留；普通 crosses 排除周六 `00:00–24:00 UTC`，JPY/AUD crosses 只排除周六 `00:00–18:00 UTC`；逐日 IANA 转 UTC | 论文没有六对组合，项目的固定 `1/6` sleeves 必须另标扩展；多数货币计入 bid/ask 后不盈利，不能事后只留 EUR/USD；EURJPY 表格符号矛盾保留为数值 reciprocal/direction canary，不搜索反向规格 |
| London fix 对冲流 | [Melvin & Prins](https://doi.org/10.1016/j.finmar.2014.11.001) | WMR 月末只增加一个预注册交互项 | 没有 PIT 股票回报和对冲映射时，只能叫月末放大，不能声称复制因果通道 |
| FX 流动性 | [Mancini, Ranaldo & Wrampelmeyer](https://doi.org/10.1111/jofi.12053) | FIX-W 按同市场品种/同四段入场边界分别使用过去 60 个事件日的 spread q90；前 60 日 warmup，之后至少 40 个观测 | 过滤器不得使用未来平仓 spread；四段或 G9 任一失败时不保留 filtered composite；Dukascopy 是单一报价源，不是全市场深度 |
| 宏观公告价格发现 | [Andersen et al.](https://doi.org/10.1257/000282803321455151) | 只有实际历史发布时间可用于 blackout | 缺 PIT consensus 时禁止构造 actual-minus-consensus surprise |
| Order flow | [Evans & Lyons](https://doi.org/10.1016/j.jinteco.2009.03.005) | 作为将来获得授权订单流后的机制参考 | quote size、tick count 和 CFTC 周仓位都不是签名订单流 |

定盘窗口和正式 `LOCAL-PAPER` 的 5 秒 prevailing-quote 边界都需要 tick。1h bar 无法识别
`:55`、`:15`、WMR 五分钟窗内的先后顺序，也不能证明 LOCAL 边界报价的陈旧度；它只适合
粗粒度探索。所有 civil time 先用 IANA 时区逐日生成，再转 UTC，并记录 tzdb 版本。

事件发生日不再由普通工作日推断。WMR 正常时间和五分钟窗口以
[LSEG WMR methodology](https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/wmr-fx-methodology.pdf)
为准，历史停服/半日服务使用官方 service-alteration PDF 的 Internet Archive 快照；ECB
14:15 日期直接来自官方 `EXR.D.USD.EUR.SP00.A` CSV，其标题明确写明 2:15 p.m. CET。
目前 WMR 例外表是按这些官方 PDF 逐行人工转录；关键半日市有测试，但尚未由 PDF
文本自动反解校对。这不改变原始证据的官方性，但要求正式运行保留 raw hash 和转录审计轨迹。

## 抗数据挖掘与推断

| 方法 | 原始资料 | 项目中的用途 |
|---|---|---|
| BH FDR | [Benjamini & Hochberg](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) | 每折统一检验族的主门槛 |
| BY FDR | [Benjamini & Yekutieli](https://doi.org/10.1214/aos/1013699998) | 任意相关结构下的更保守敏感性，不替代主假设注册 |
| Reality Check | [White](https://doi.org/10.1111/1468-0262.00152) | 检查从完整候选集合中挑最好策略的数据窥探 |
| SPA | [Hansen](https://doi.org/10.1198/073500105000000063) | 用共同日净收益矩阵和显式 benchmark 检验相对表现；项目内核心已真正 studentize 并使用 plus-one p 值，正式 runner 尚未串联 |
| Stepwise 多重检验 | [Romano & Wolf](https://doi.org/10.1111/j.1468-0262.2005.00615) | 将来需要识别多个策略时的 family-wise 备选 |
| Stationary bootstrap | [Politis & Romano](https://doi.org/10.1080/01621459.1994.10476870) | 保留时间依赖并对所有品种/候选同步抽日期行 |
| Empirical p 值 | [Phipson & Smyth](https://doi.org/10.2202/1544-6115.1585) | 使用 `(k+1)/(B+1)`，p 值永不报 0 |
| Deflated Sharpe | [Bailey & López de Prado](https://doi.org/10.3905/jpm.2014.40.5.094) | 用完整试验次数、偏度和峰度修正被选择的 Sharpe |
| PBO / CSCV | [Bailey et al.](https://doi.org/10.21314/JCF.2016.322) | 16 连续块检查 IS 最优策略的 OOS 相对排名 |
| Model Confidence Set | [Hansen, Lunde & Nason](https://doi.org/10.3982/ECTA5771) | 在共同日期、净成本收益和预先冻结的候选集合上报告“未被排除”的模型集合；仅作 SPA/BH 之外的敏感性 |
| Factor zoo | [Harvey, Liu & Zhu](https://doi.org/10.1111/jofi.12883) | 提高新因子的证据门槛并公开全部尝试 |
| Elastic net | [Zou & Hastie](https://doi.org/10.1111/j.1467-9868.2005.00503.x) | 只在固定训练集做相关特征收缩，不替代 OOS 推断 |
| Group lasso | [Yuan & Lin](https://doi.org/10.1111/j.1467-9868.2005.00532.x) | 将来按货币/因子家族施加结构约束的候选 |
| Stability selection | [Meinshausen & Bühlmann](https://doi.org/10.1111/j.1467-9868.2010.00740.x) | 检查训练扰动下的选择频率，不把一次入选当稳健性 |

经验 bootstrap 若要分辨 `m` 个检验的第一条 BH 阈值 `q/m`，至少需要：

```text
B >= ceil(m / q) - 1
```

v4 为 `m=129, q=0.10`，最低 1,289 次；项目实际使用 20,000 次。更高重采样次数只能降低
Monte Carlo 分辨率问题，不能修复 current-vintage、成本缺失或反复查看同一历史。

## 从资料到开发任务

1. Dukascopy 未到齐前只完善数据时间契约、共同日历、负对照、组合账本和合成测试。
2. 到齐后先验证 2016–2025 bid/ask 与 spread；不先看哪个因子最好。
3. 用已登记的 43 因子做一次迁移/执行级否决。没有方向候选通过就接受空模型。
4. 只有通过的方向候选才进入 sleeve、融资和主账户成本组合；风险状态不能代替方向信号。
5. 所有候选共享同一每日净收益日期矩阵，再运行 DSR/PBO 并准备严格 SPA 输入；项目内已有
   透明 SPA 核心，但正式 runner 尚未调用。SPA 只校正实际传入的候选收益列，不能替代对
   3,312 次既往搜索的完整披露。
6. 最终只认冻结后新增的 3–6 个月 forward evidence；同一 2016–2025 历史不能重新变成
   untouched holdout。
