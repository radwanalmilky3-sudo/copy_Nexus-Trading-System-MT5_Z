# 外汇因子研究外部数据下载计划

更新日期：2026-07-17。

这份清单只解决 Dukascopy 价格之外的数据准备。数据被分成三类：已经可以公开下载的原始
资料、需要目标 broker 提供的执行成本资料，以及需要商业授权的市场资料。公开代理数据不会
被重命名成 OIS、远期点或真实 carry。

## 已完成的公开下载

运行：

```bash
uv run python scripts/download_fx_reference_data.py \
  --output data/external_raw

uv run fxtrade cftc-download \
  --start-year 2006 \
  -o data/point_in_time/currency_positioning.csv

uv run python scripts/download_cftc_release_calendar.py \
  --output-dir data/cftc_release_calendar

uv run python scripts/download_oanda_financing_history.py \
  --output data/oanda_financing_us

uv run python scripts/download_official_fx_rates.py \
  --output data/official_rates

uv run python scripts/download_fx_supplemental_data.py \
  --output data/supplemental_fx

uv run python scripts/download_phillyfed_rtdsm.py \
  --output data/supplemental_fx

uv run python scripts/download_phillyfed_spf.py \
  --output data/supplemental_fx

uv run python scripts/download_ons_gdp_realtime.py \
  --output-dir data/ons_gdp_realtime

uv run python scripts/download_treasury_tic_archives.py \
  --output-dir data/treasury_tic \
  --start-year 2016 \
  --end-year 2025 \
  --download-zips
```

CFTC Bank Participation Reports 已执行真实下载。当前保存 82 个报告页，最新完整月份为
2019-03；下一请求被 CFTC 以 HTTP 403 拒绝，故没有正式 manifest 或 normalized CSV。
下载器现支持对未完成缓存代做逐文件 SHA/archive 核验后续传；只能从获准网络重试：

```bash
uv run python scripts/download_cftc_bank_participation.py \
  --output data/cftc_bank_participation \
  --resume-generation \
  data/cftc_bank_participation/raw/cache/generations/20260716T212702271027Z_eaa80b367268
```

OECD Economic Outlook 的独立下载器已经实现。2026-07-16 在本环境正式尝试时，首条
EO99 legacy archive 请求即被 Cloudflare 以 HTTP 429 拒绝（`Retry-After: 0`），因此程序
正确停止，未写入任何正式 OECD 产物。现代 public API 的 EO118 窄查询同时可以返回 200，
但不能只用 modern 版次拼成一份伪称完整的 EO99–118 数据。应从获准网络重试，或人工取得
OECD 官方导出；不得切换代理、规避 Cloudflare 或抓取全库来绕过限制。命令仍为：

```bash
uv run python scripts/download_oecd_economic_outlook.py \
  --output data/oecd_economic_outlook
```

它只访问 OECD 官方 SDMX API，并在服务端固定筛选 8 个货币经济体、5 个已逐版核验的年频
变量和“出版年到出版年 + 2”目标期。单个窄响应实测约 13–25 KiB，EO107 两个情景各约
17 KiB；程序仍以 2 MiB/响应为硬上限，绝不回退到默认可能达到 0.5–2 GB 的完整 dataflow。
默认请求间隔 0.75 秒，支持重试、缓存、原始快照、SHA-256、manifest 和原子替换。

扩展后实测 39/39 个任务成功。下载器按来源限速，但 FRED 与 CFTC 两个独立来源可以同时下载；
历史年度 CFTC 文件默认复用，FRED 和当前年度 CFTC 默认刷新。`--skip-existing` 可用于只补齐
中断的文件，`--refresh` 可强制刷新全部文件。

官方利率下载器另有 8/8 个来源成功，共标准化 55,756 行。它保存官方原始响应和统一 CSV；
当前磁盘占用约 21.3 MiB（原始响应约 5.8 MiB、标准化 CSV 约 15 MiB）。

每个原始文件都有 `.meta.json`，记录来源 URL、抓取时间、响应元数据、SHA-256、文件大小和
覆盖区间；`latest_manifest.json` 汇总整次运行。文件先验证、再原子替换，失败响应不会覆盖
有效缓存。

| 组 | 内容 | 覆盖 | 原始体积 | 当前研究资格 |
|---|---|---|---:|---|
| CFTC | 2006–2016 合并历史 + 2010–2026 年度 TFF ZIP | 2006-06 起 | 9.71 MiB | 60 天保守滞后；公开压缩档是 current/revised archive，不是 as-published vintage；仅探索 |
| CFTC release evidence | 10 份年度 Wayback schedule + 官方 special announcements + PR 7864-19 | 2016–2025，522 个 report dates | 约 1 MiB | 489 tentative、16 announced、10 rule-derived、7 actual-date-only；0 个 actual timestamp，不能严格晋级 |
| CFTC BPR（部分下载、403 阻塞） | 目标 120 个月 × Futures/Options；当前 82/240 页，至 2019-03 | 目标 2016-01 至 2025-12 | 当前约数十 MiB；完整预计 0.15–0.40 GB | 无完整 manifest/normalized；仅探索，不是 COT、现货订单流或 alpha |
| Value | 8 种货币 BIS 实际广义有效汇率，经 FRED 分发 | 1994-01 起 | 0.05 MiB | 当前版本价值代理，不是 PIT 修订档案 |
| Risk | VIX、广义美元指数、NFCI、STLFSI、美国高收益利差 | 各系列不同 | 0.34 MiB | 可做风险状态；需逐系列覆盖审计 |
| Rates reference | 8 种货币政策/即期货币市场参考利率 | 各系列不同 | 0.63 MiB | 只能探索，不能作为严格 carry |
| Official rates | SOFR、€STR、SONIA、CORRA、AONIA、政策利率；RBA AUD 1M/3M OIS | 1997 年后不等 | 21.3 MiB | 参考利差仅探索；只有 RBA 明确命名的列是 OIS |
| Supplemental | Pink Sheet、GSCPI、GEPU、GPR、OFR FSI、ECB CISS、BoC BCPI、RBA I2、Cboe EVZ/EUVIX/JYVIX/BPVIX | 各系列不同 | 66 MiB（raw 11、normalized 43、archive 11 MiB） | 仅 GSCPI 2022-01 后 vintage 可严格 as-of；其余为 current-vintage |
| Philly Fed RTDSM | CPI 季度 vintage、工业生产月度 vintage、Fed G.17 发布日 | CPI vintage 1994 起；IP vintage 1962 起 | 约 11 MiB（含原始、压缩标准化和首份归档） | 572,140 行真实 vintage；日期级可用时间，不能用于发布日内交易 |
| Philly Fed SPF | 官方发布日期、均值/中位数合并历史、文档与勘误 | 2016–2025 日历 40 季 | 约 6 MiB（raw 与首份 archive） | 发布日期可核实；预测值是 current consolidated archive，不是逐季 as-published 文件 vintage |
| ONS GDP real-time | ABMI 实际 GDP 与 YBHA 名义 GDP 的官方 edition 工作簿 | 2016–2025，共 156 份 | 原始约 85 MiB；cache 与 archive 双份约 170 MiB | 目录完整；旧版工作簿缺精确原始发布日期，默认 fail closed，不产出部分 PIT 面板 |
| Treasury TIC 月度发布档案 | 官方 release ZIP、发布页、文件说明、SHA 和成员清单 | 2016–2025，120/120 个月 | 原始 ZIP 326,637,026 bytes；raw 与内容哈希 archive 合计约 624 MiB | 发布档案完整；series parser 与跨版修订审计未完成，`strict_pit_eligible=false`；只能作低频状态候选 |
| BIS GLI / LBS | 官方 topic/bulk/methodology/break 资料及两个 flat CSV ZIP | 季度；当前快照 | 原始 359,035,286 bytes；raw+archive 约 698 MiB | 8/8 资源和双 SHA 通过；current-vintage，不能作方向/订单流/strict PIT 历史输入 |
| BIS OTC / Triennial（资料已核验，未下载） | OTC FX 衍生品存量、信用暴露及三年一度 turnover 结构 | 半年 / 三年 | 预计较小；尚未建立下载器 | 结构和机制校验；没有逐日逐币种对的可交易价格、方向或仓位 |
| ALFRED / ECB SPF 目录 | 5 个美国宏观 series；ECB 官方发现链、release pages 与附件 | ALFRED 待 key；ECB 2018-Q3 至 2025-Q4 共 30/40 季度 | ECB 目录约 47 MiB | ALFRED 缺 API key；ECB 早期 10 季度未由官网目录暴露；均非 strict PIT 或日内 surprise |

基础 FRED/CFTC 首轮原始包合计 10.73 MiB。标准化 CFTC 文件为 7,333 行、约 1.1 MiB。
ONS 全部工作簿另约 85 MiB；即使同时保存 cache 与 archive，和 Dukascopy tick 数据库相比
仍很小。

主要覆盖情况：

- BIS REER：USD、EUR、GBP、JPY、CHF、CAD、AUD、NZD 均从 1994-01 至 2026-05；
- CFTC：从 2006-06 至当前档案，七种非美元货币期货；
- VIX：1990-01 起；NFCI：1971-01 起；STLFSI：1993-12 起；广义美元指数：2006-01 起；
- 高收益利差当前公开响应只有 2023-07 以后的数据，不能单独用于长期回测；
- CHF 和 NZD 的 OECD/FRED 即期利率分别停在 2024-03 和 2024-12，不能通过正式 carry
  覆盖门槛。
- 官方利率主源覆盖 AUD、CAD、CHF、EUR、GBP、JPY、USD；NZD 主源仍缺。JPY TONA 是 SNB
  月频二次转载而非 BOJ 主源；只有 RBA 源中明确标为 OIS 的 AUD 1M/3M 列被设为
  `is_ois=true`，其余隔夜或政策利率没有被重命名成 OIS。
- 补充下载器 13/13 个来源成功：120,190 行 current-vintage 快照，以及 16,524 行 GSCPI
  vintage。OFR FSI、ECB CISS、BoC BCPI、RBA I2 和四条 Cboe FX IV 的历史行统一使用首次
  抓取时点作为
  `available_time`，没有用观察日加人为滞后来伪造历史 PIT；因此它们只会从归档快照之后
  进入严格前向因子。
- Cboe 四个官方 CSV 合计只有约 0.3 MiB：EVZ 到 2025-03-11，EUVIX/JYVIX 到
  2022-11-07，BPVIX 到 2023-07-14。它们是 EUR/JPY/GBP 的 30 日 VIX-style 隐含波动状态，
  不覆盖完整八币种，也不是一年期 OTC smile、risk reversal 或横截面 VRP。四条序列都早于
  本项目首次归档而停止，因此 2016–2025 只能 current-vintage 探索；它们没有可供严格前向
  晋级的新鲜覆盖。
- 下载器保存每个来源的内容哈希原始快照，并把每次运行的完整 manifest 写入
  `data/supplemental_fx/manifests/`。今后定期 `--refresh` 才能逐步形成自建 vintage；当前
  第一次归档之前的历史仍然不是 PIT。
- RTDSM 下载器另产生 96,913 行 CPI 和 475,227 行工业生产 vintage，重复键为 0，压缩
  标准化文件约 4 MiB。工业生产在官方 G.17 页面可核实的月份从下一个纽约自然日开始可用；
  无法核实的旧月份推迟到下月开始。指数基期可能跨 vintage 改变，变化率必须在同一
  vintage 内计算。
- SPF 只标准化 2016–2025 的 40 个官方新闻发布日期，并在下一个纽约自然日才允许使用；
  日期本身可用于季度事件日历。四份均值/中位数 Excel 是官方当前合并历史，且官方同时发布
  勘误，因此 `value_strict_pit_eligible=false`，不得用发布日期把当前修订值伪装成逐季
  as-published vintage。SPF 也是美国单国季度调查，不是跨货币一致预期或 surprise feed。
- Philadelphia Fed 条款允许信息、教育和研究用途但禁止 excessive access；`robots.txt`
  未禁止这些公开页面或 `/-/media` 下载路径。下载器归档两份证据、默认请求间隔 0.75 秒，
  建议只在季度 SPF 发布后刷新，不调用被 robots 禁止的 `/api/`。

下载程序只访问以下域名，便于设置网络规则：

```text
fred.stlouisfed.org
www.cftc.gov
web.archive.org
labs-api.oanda.com
www.worldbank.org
thedocs.worldbank.org
www.newyorkfed.org
www.policyuncertainty.com
www.matteoiacoviello.com
www.financialresearch.gov
markets.newyorkfed.org
data-api.ecb.europa.eu
www.bankofengland.co.uk
www.bankofcanada.ca
www.rba.gov.au
data.snb.ch
www.philadelphiafed.org
www.federalreserve.gov
www.ecb.europa.eu
www.boj.or.jp
cdn.cboe.com
sdmx.oecd.org
www.snb.ch
www.rbnz.govt.nz
www.ons.gov.uk
www.bis.org
data.bis.org
alfred.stlouisfed.org
api.stlouisfed.org
home.treasury.gov
www.treasury.gov
ticdata.treasury.gov
```

## Treasury TIC 月度发布档案

官方 archive page 声明每个 ZIP 包含页面所列日期发布的 TIC 数据。下载器已保存 2016–2025
共 120 个 reference month，raw 与内容哈希 archive 各 120 个 ZIP；两份存储副本的 SHA-256、
全部 ZIP 完整性、120 个唯一 reference month 和 manifest 均已独立复核通过。完整目录当前约
624 MiB。manifest 明确保持 `factor_registry_modified=false`、`outcome_evaluations_added=0`。

页面或文件名的已知日期异常被原样保留：2018-08-15 对应文件名 `20180816`、2018-09-18
对应 `20180919`、2022-02-15 对应 `20220222`；2025 年停摆项的页面 anchor 为
2025-10-17，而说明文字给出的实际发布日为 2025-11-18。下载器对普通日期也只保守到下一个
UTC 自然日可用；若官方 ZIP 文件日期晚于页面/说明日期，则取两者较晚者再加一天。它不把
reference month 当作发布日期。

档案结构本身发生过变化：`npr_history` 有 CSV、TXT 和 HTML 三种格式；2020-06 是唯一 TXT
例外。程序现已覆盖该官方变体并有回归测试。第一阶段已完成 NPR 的 120 个 vintage 和
119 个相邻版本比较，单次最多修改 248 个旧月份、最远回溯 479 个月；bctype、bltype、mfh、
mfhhis01、tressect 和 totalticliabs 仍须解析数值、冻结列语义并建立修订矩阵。全部序列审计
完成前，TIC 只能描述外国官方/私人
美债需求和跨境银行美元资产负债状态，不能声称是 Treasury basis、OTC FX volume、签名现货
订单流或带方向的交易 alpha。

## BIS GLI / LBS 当前快照

已运行：

```bash
uv run python scripts/download_bis_gli_lbs.py \
  --output-dir data/bis_gli_lbs \
  --download-gli \
  --download-lbs
```

结果为 8/8 个官方资源、359,035,286 原始 bytes；raw 与内容哈希 archive 合计约 698 MiB。
GLI ZIP 为 254,255 bytes，展开约 9.3 MB；LBS ZIP 为 356,466,277 bytes，单个 flat CSV 的
官方中央目录大小为 17,672,650,002 bytes。项目只保存并核验 ZIP，不解压 LBS；下载器以
24 GiB 总量、单文件 24 GiB、100 倍压缩比作为硬上限。两份 raw/archive 的 SHA 全部通过。

这些文件是 2026-07 抓取的 current snapshot，不是 2016–2025 每个发布日期的 vintage。
manifest 固定 `strict_pit_eligible=false`、`is_fx_order_flow=false`、
`is_directional_alpha=false`。它们只能作为将来的季度全球流动性/银行资产负债状态候选，且须
从现在开始定期归档，不能把今天的修订历史倒填到旧回测。

## ALFRED 与 ECB SPF 官方目录

已运行：

```bash
uv run python scripts/download_alfred_ecb_spf_catalogs.py \
  --output-dir data/alfred_ecb_spf
```

ECB 严格沿 index、官方 all-releases/filter 目录、release page、附件的链接链保存证据。当前
官方目录可发现 2018-Q3 至 2025-Q4 共 30 个季度、52 个 release page 记录；2016-Q1 至
2018-Q2 的 10 季度没有由当前目录暴露，程序明确列为 missing，没有猜 URL。目录约 47 MiB，
仍缺精确发布时刻、附件修订行为和数值版次规范化。

ALFRED 固定 CPIAUCSL、INDPRO、PAYEMS、UNRATE、GDPC1 五个 series。没有
`FRED_API_KEY` 时程序不访问 API，也不下载 current FRED CSV 作为替代；当前状态为
`blocked_fred_api_key_required`。即使提供 key，第一阶段也只归档 metadata/vintage dates，
观测值逐 vintage 解析完成前仍为 `strict_pit=false`，不能支持日内 surprise。

## 已核验、但刻意未排入因子下载队列的公开资料

这些来源的价值在于减少错误解释，而不是把每一份公开表都变成特征。未建立下载器不代表资料
无用；它避免 current-vintage 宏观序列在没有 PIT 契约时意外进入冻结 runner。

| 来源 | 官方入口 | 最小可行用途 | 进入正式研究前的必要证据 |
|---|---|---|---|
| BIS GLI | <https://data.bis.org/topics/GLI> | USD/EUR/JPY 非居民外币信贷的季度 global-funding 风险状态 | 每个 release 的原始响应、SHA-256、reference period、实际/保守发布日期、表结构和 revision/break 文件；历史门户当前版不能倒推 vintage |
| BIS LBS | <https://data.bis.org/topics/LBS> | 国家/币种维度的跨境银行头寸覆盖与结构断点审计 | 同上，另须冻结 country/currency/position 维度；存量不是现货订单流，也不是可净额化的交易信号 |
| BIS OTC derivatives | <https://data.bis.org/topics/OTC_DER> | FX swap/forward/currency-swap 总量、期限和集中度的机制校验 | 半年发布的每版归档、美元换算与汇率效应说明；不得从存量变化反推现货方向 |
| BIS Triennial Survey | <https://www.bis.org/statistics/rpfx22.htm> | 交易工具、货币、对手方和市场覆盖的结构性校准 | 保留所用 survey edition 和表定义；三年一度四月调查不能变成月度拥挤度序列 |
| ALFRED | <https://alfred.stlouisfed.org/> | RTDSM 未覆盖的少量美国宏观 state | 每个 series 单独核验 source、real-time date、单位、发布证据和许可证；ALFRED 查询本身不构成原始 release clock 证据或 PIT consensus，故禁止日内 surprise |
| ECB SPF | <https://www.ecb.europa.eu/stats/ecb_surveys/survey_of_professional_forecasters/html/index.en.html> | EUR 宏观预期状态的候选目录 | 逐季 release page/附件归档、实际公开时间和字段稳定性；不能把 EUR survey 外推为八币种 consensus 或宏观 surprise |

BIS GLI/LBS 和 ALFRED/ECB SPF 已进入下载/目录阶段，但都仍为 `not_strict_pit`；BIS OTC 与
Triennial 仍是 `catalogued_not_downloaded_not_strict_pit`。只有资料版本与可用时间均能被审计
后，才允许进入特征层；下载器必须将 raw、sidecar、manifest、schema/metadata 和
release/revision evidence 原子化归档。慢周期状态的 `available_time` 至少取可核验发布日后的
下一个保守决策时点；绝不以 reference period 的终点或网页抓取日倒填过去可用性。

## ONS 英国 GDP 实时版次

下载器只允许 ONS 官方页面和它们列出的 edition 工作簿：

```text
https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/realtimedatabaseforukgdpabmi
https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/realtimedatabaseforukgdpybha
```

ABMI 是 chained volume measure 的实际 GDP，YBHA 是 current prices 的名义 GDP。程序固定
2016–2025：2016 年每个系列 6 个 edition，2017–2025 每年每个系列 8 个，合计每个系列
78 份、两个系列 156 份。页面列示大小合计约 85 MiB；同时保留 cache 与内容哈希 archive 后
约 170 MiB，规范化 CSV 相比之下很小。资料采用 Open Government Licence v3.0：
<https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/>。

默认命令只建立完整 edition 目录、原始页面快照、SHA-256 和 manifest，不下载工作簿。需要归档
全部工作簿时显式运行：

```bash
uv run python scripts/download_ons_gdp_realtime.py \
  --output-dir data/ons_gdp_realtime \
  --download-workbooks
```

实测连续快速请求会收到 HTTP 429，因此默认间隔为 1 秒，并遵守 `Retry-After` 和指数退避。
ONS 历史 edition 子页面当前会重复显示最新数据集日期，例如 `30 June 2026`，它不是历史版次的
原始发布日期。现代 XLSX 封面通常明确写有
`The data tables in this spreadsheet were originally published at ...`，旧 XLS 往往只有月份级
vintage 表头而没有精确日期。程序只接受工作簿内唯一、可解析的原始发布日期；不会根据 edition
名称、文件名、页面日期或月份表头推断。只要任意 edition 缺少该证据，就只写工作簿审计和
manifest，不写部分规范化观测文件。

每一行保留 series、edition、发布日期、保守的下一 UTC 自然日可用时间、来源 URL 与哈希。
修订值始终归属于自身 edition，不用最新版回填旧版。环比或同比只能在同一 edition 内计算，
下载器本身不计算增长率。该数据目前只允许作为 GBP 宏观状态参考，不能直接注册方向性 alpha，
也不能用于发布日内交易。

## OECD Economic Outlook 预测版次

下载器覆盖 EO99–118：EO99–106、EO108–114 使用官方 archive dataflow；EO107 分别保留
single-hit 和 double-hit；EO115–118 使用现代 API 的 1.1–1.4 版本。只选以下五个在每个
版次的窄查询中都已核验存在的原始代码，不根据名称猜测或扩张变量：

```text
GDPV_ANNPCT  Gross domestic product, volume, growth
CPI_YTYPCT   Headline inflation
UNR          Unemployment rate
CBGDPR       Current account balance as a percentage of GDP
NLGQ         General government net lending as a percentage of GDP
```

经济体为 USA、GBR、JPN、CHE、CAN、AUS、NZL 和 OECD 原始欧元区聚合。窄查询纠正了一个
容易混淆的口径：这些数据流不是 EA19/EA20，而是 OECD **成员国** 聚合；EO99 为 EA15，
EO100 同时提供 EA15 和 EA16，EO101–103 为 EA16，EO104 起（含 EO115–118）为 EA17。
程序保留 `economy_code` / `aggregate_variant` 和官方 label；EO100 不生成唯一 EUR 分数，
EA15→EA16→EA17 一律标记 `composition_break=true`，禁止自动接续。

每行保留原始变量名、频率、单位、基期、目标期、观测状态和 scenario。官方出版证据只有日期，
所以可用时间统一设为出版日后的下一工作日 00:00 UTC，并明确标记为
`official_date_only_forecast_edition`。这些是 OECD 当版预测，不是实际经济数据的 release
vintage，也不是 consensus surprise；不能用于发布日内交易。正式因子公式仍须先冻结，当前
工作只准备数据契约，不产生方向规则或收益结论。重新分发原始响应前还需另行核对 OECD 条款。

## CFTC Bank Participation Reports

BPR 下载器与现有 COT/TFF 下载器完全分开。它先从 CFTC 主索引和 CFTC 自己的 Solr 内容索引
自动发现永久页，不根据月份拼接 URL；只有在 2016-01 至 2025-12 每个月恰好存在一个 Futures
和一个 Options 页面（共 240 页）时才进入规范化。路径只允许 `www.cftc.gov` 下两代官方 BPR
目录。缺月、同月多链接、404、表头变化、rowspan 异常或哈希不符都会 fail closed。

原始 HTML 仍然包含非 FX 商品并完整归档；标准化输出只保留页面实际披露的 CME AUD、CAD、
CHF、EUR、GBP、JPY、NZD 合约。某合约某月没有披露时不会补零。Futures 的 long/short 与
Options 的 call/put、call OI、put OI 分列保存，U.S.、NON U.S. 和页面空标签的 combined 行
分别保留；不对 JPY 等合约静默取反。每页另写明 frozen contract 集合中实际披露与缺失的
合约，缺币种不能静默通过或当零。BPR 是期货/期权银行持仓汇总，不是带符号的现货订单流。

普通月份的发布日期来自官方“first Friday after 3:30 ET”制度，标为 rule-derived，且为避免
把 15:30 当成实际完成时间，数据推迟到下一纽约自然日才可用。2025 年 10–11 月有官方停摆
公告但缺完整实际发布时间，程序只使用首次归档时间作为保守可用时间；2025 年 12 月日程中的
catch-up 日期仍标为 intended、不是 actual。2018 年 12 月永久页有官方 CBOT 补充修正说明，
因此标为 corrected permanent report，不冒充原始快照。2019 年 1 月处于联邦停摆期，而 BPR
special page 没有逐报告发布时间证据，同样只从首次归档时点可用。其余 rule-derived 的“次日
可用”也只是晚于 schedule，不证明晚于 actual；全部 BPR 行统一 `strict_pit_eligible=false`，
只能探索。

永久页会被官方更新（2018-12 的 correction 已直接证明这一点），所以一般页面统一标为
`official_permanent_report_current_copy_not_verified_as_published_vintage`，不能仅因 URL 永久
就称为逐期发布时保存的 as-published vintage。

实测单页约 0.09–1.1 MiB；240 个页面加发现索引预计下载约 75–200 MiB，cache 与内容哈希
archive 各保留一份后预计约 0.15–0.40 GB。标准化 FX CSV 预计只有数 MiB。下载仍只使用已经
列入网络清单的 `www.cftc.gov`，没有新增域名。

## OANDA 近一年融资费率

OANDA Corporation 美国官网的公开融资表实际支持最近约一年历史查询，不要求交易账户
token。下载器已经回补 2025-07-16 至 2026-07-14 的 364 个自然日、12 个核心货币对，共
4,368 行；原始 JSON、清单和标准化 CSV 总计约 5.2 MiB：

```bash
uv run python scripts/download_oanda_financing_history.py \
  --output data/oanda_financing_us
```

标准化文件保留 source timestamp、计息天数、年化 long/short rate、10 万单位的 long/short
费用、费用币种和原始文件哈希。周末明确返回 `days=0`；节假日可以超过通常的三倍计息，
例如 2026-02-11 的 USD/CNH 为 11 天 rollover。

这批数据来自公开的 `divisionId=1, tradingGroupId=1`，属于 OANDA Corporation 页面口径，
不一定等于用户所属监管实体、账户类型或最终成交账户的扣费。网页也说明当天收盘前为指示值，
所以下载器默认只取昨天及更早日期。费用暂不转换成 pip；必须等历史 spot 和账户币种转换率
到齐后按日计算。

## 仍必须取得的数据

### 目标 broker 历史 swap

优先级最高。每个货币对至少需要：

```text
available_time,swap_long_pips,swap_short_pips
```

还要保留账户类型、计价单位、周三或节假日多倍 rollover 规则和数据生效时间。当前已经获得
OANDA Corporation 公开页面近一年历史，但它不能替代目标账户的最终扣费。OANDA candle API
本身仍不提供融资序列；目标账户应优先导出 transaction history，并从现在开始持续保存账户
所属 division/trading group 的每日最终快照。

### OIS 与可交易 forward points

严格 carry 研究需要逐期当时可知的：

- USD、EUR、GBP、JPY、CHF、CAD、AUD、NZD 的 1M/3M OIS；
- 每个货币对的 1M/3M outright forward points；
- 同一快照的 spot reference、observation time 和 available time。

这些数据通常来自 Bloomberg、LSEG、ICE、CME、Macrobond 或银行/经纪商历史档案。免费政策
利率不能替代 OIS，利率平价合成的远期点也不能再被当成独立市场证据。

当前免费范围只有 AUD 获得了来源明确的日频 1M/3M OIS；这不能补齐八种货币的同口径截面，
所以严格 carry 门槛仍未通过。公开隔夜/政策利差生成的
`overnight_rate_differential_public` 与 `policy_rate_differential_public` 永久保持
`exploratory_not_ois`，除非数据契约和来源整体升级。

### CFTC 实际发布日期

当前标准化文件采用报告日后 60 天的保守可用时间，避免政府停摆等延期发布造成前视偏差。
它可以支持滞后仓位探索，但不是实际发布日期档案。更重要的是，Historical Compressed 文件
是会被修订的当前档案，不是每次发布当时保存的 value vintage；补齐发布时间本身不会把最终
修订值变成 PIT。若要把 CFTC 因子纳入正式晋级，必须同时取得逐期真实发布时间并标记为
`verified_actual_publication`，以及逐期 as-published 数值并标记为
`verified_as_published_vintage`。代码的 verified 门槛同时检查两列，缺一即拒绝。

CFTC 官网确认通常在美东时间 15:30 发布，并提供当年 tentative schedule 和 Historical
Special Announcements。异常页可以恢复 2019、2023、2025 政府停摆或系统故障等重大延期，
但官方没有提供 2006 年以来逐期实际时间的结构化下载。项目已将 2016–2025 固定为 522 行
证据日历并保存 12 份 raw/SHA sidecar：489 行只是 tentative，16 行是例外 announced，
10 行由 2019 追赶规则推导，只有 2023 ION 的 7 行被官方“Today, staff is issuing”证明实际
**日期**，且没有一行能证明实际发布时间戳。2025 最终表使用 intended wording，所以没有
升级为 actual。完整 verified timestamp 日历仍缺；在此之前继续使用 60 天保守滞后。

### Tokyo / ECB / WMR 正式事件日历

这一项已经补齐到 2016–2025。免费来源包括 WM/Reuters 2016–2021 service-alteration PDF、
Refinitiv 2022 PDF、LSEG 2023–2025 PDF/方法论，以及 ECB 官方
`EXR.D.USD.EUR.SP00.A` CSV。生成器保留 Internet Archive 原始 PDF、ECB CSV、抓取时间和
SHA-256，再输出逐自然日 10,959 行状态。4pm-only、no-service、午间半日市分别映射到
Tokyo/WMR 的不同状态，不能用一个“假日”布尔值粗暴替代。原始 LSEG 文档只供本地审计，
重新分发前应核对发布方条款。Tokyo/ECB/WMR 实际发布日分别为 2,575 / 2,560 /
2,580，三者共同的 FIX-W 日为 2,557 个；calendar SHA-256 为
`226dada52f60d22d8c1a386f8ef6042457b2c9930ab90bafc67398e1b8011046`。

WMR 例外状态目前是根据上述官方 PDF 逐行人工转录，关键半日市已有测试覆盖，但尚未由
PDF 文本自动反解校对。因此正式运行除了验证 CSV/manifest/raw hash，还应保留转录审计。

## 第二优先级的授权数据

| 数据 | 价值 | 候选渠道 | 当前决策 |
|---|---|---|---|
| CME FX 期货成交量/持仓量/逐笔成交 | 验证机构参与和日内成交强度 | CME DataMine | 官网明确禁止脚本抓取；有预算后采购 |
| 1M/3M 风险逆转、ATM 隐含波动率 | 风险偏好、崩盘溢价和 carry 风险 | LSEG、Bloomberg、CME | 中长期第二阶段 |
| 宏观 surprise/一致预期 | 事件研究和日内 blackout/冲击 | Bloomberg、LSEG、Macrobond | 不用实际值减事后预期伪造 |
| 银行订单流或 ECN 成交 | 真正的微观结构信号 | EBS、Refinitiv、CME、LMAX 等授权源 | Dukascopy quote size 不替代 |

## 更新节奏

- Dukascopy tick：由 VPS 长任务持续下载；完成后复制 SQLite 到本机；
- CFTC：每周末刷新当前年度 ZIP，再生成标准化 CSV；
- CFTC 2016–2025 release evidence：固定 Wayback 年度页通常不刷新；官方 special page 变化时
  用 `--refresh` 重新抓取并复核证据分类，不能因页面新增内容自动升级旧行质量；
- FRED/BIS REER/risk/rate references：每周或每月刷新；
- 官方央行/基准利率：每周刷新；历史响应默认复用时用 `--refresh` 主动更新；
- OFR/CISS/Cboe 等补充快照：每周固定时点 `--refresh`，原始版本自动归档；Pink
  Sheet/BCPI/RBA 月度系列即使未变化也保留抓取 manifest；
- Philly Fed RTDSM：每月刷新一次并固定输入哈希；研究运行使用某一冻结快照，不自动追随修订；
- Philly Fed SPF：每季度正式发布后刷新一次；发布日期日历可更新，预测值仍保持非严格 PIT；
- OANDA 公开 financing：每日纽约收盘后刷新昨天，保留原始 JSON；
- 目标账户 swap：只要费率变更就追加，必须保留历史版本；
- forward/OIS：研究所需至少日频快照，实际频率由授权数据决定。

推荐每周运行：

```bash
uv run python scripts/download_fx_reference_data.py \
  --output data/external_raw

uv run fxtrade cftc-download \
  --start-year 2006 \
  -o data/point_in_time/currency_positioning.csv

uv run python scripts/download_cftc_release_calendar.py \
  --output-dir data/cftc_release_calendar

uv run python scripts/download_oanda_financing_history.py \
  --output data/oanda_financing_us

uv run python scripts/download_official_fx_rates.py \
  --output data/official_rates \
  --refresh

uv run python scripts/download_fx_supplemental_data.py \
  --output data/supplemental_fx \
  --refresh

uv run python scripts/download_phillyfed_rtdsm.py \
  --output data/supplemental_fx \
  --refresh
```

正式因子研究仍以数据审计为入口。文件“已经下载”不等于“可以进入模型”：覆盖不足、当前版本
宏观数据、近似发布时间和来源不明的 CSV 都必须维持探索级标记。
