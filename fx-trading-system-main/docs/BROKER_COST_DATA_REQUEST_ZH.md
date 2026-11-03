# Broker 历史融资与远期报价数据请求

## 当前状态与用途

目标 broker、法律实体、账户类型和账户币种尚未确定，因此本项目当前成本结论固定为
`cost_incomplete_research_only`。Dukascopy tick 的 bid/ask 可以支持报价与点差研究，但不能
代替实际账户的隔夜融资、加点、三倍计息和换汇成本。

下面的正文可以直接发送给候选 broker。方括号内容由账户持有人填写；不知道时保留“请贵司
确认”，不要自行假设。请求区间为 `[2016-01-01, 2026-01-01)`，即最后一个覆盖日为
2025-12-31。

## 可直接发送的请求正文

**主题：请求提供外汇保证金账户历史融资费率、计息规则与可交易远期报价数据**

您好：

我正在评估贵司外汇保证金交易服务，希望对拟开立/已有账户的历史交易成本进行独立核验。
请协助确认并尽可能提供以下资料：

- broker 完整法律实体名称、监管辖区和监管编号；
- 账户类型：`[待填写/请贵司确认]`；账户币种：`[待填写/请贵司确认]`；
- 区间：2016-01-01（含）至 2026-01-01（不含）；
- 品种：EURUSD、GBPUSD、USDJPY、USDCHF、AUDUSD、NZDUSD、USDCAD、EURGBP、
  EURJPY、GBPJPY、AUDJPY、CADJPY、USDNOK、USDSEK；若某品种或年份不可用，请明确列出。

第一部分，请提供逐品种历史隔夜融资/rollover/swap 表。每次费率或规则变化至少包含：生效
时间、客户当时可获知的时间、long 费率、short 费率、单位、日计数规则、账户币种、broker
加点是否已包含、三倍计息星期、每个结算日实际 rollover multiplier，以及节假日或临时变更。
时间请使用带时区的 ISO 8601；若只能提供当地时间，请同时给出时区和夏令时规则。

第二部分，请提供完整计息方法：名义本金基准、使用 bid/ask/mid 的方式、每日 cut-off、周末
与节假日处理、三倍/多倍计息、负利率、四舍五入、最低费用、融资费入账币种、账户币种换汇
汇率及其加点，以及历史上规则变更的生效日。请区分“展示费率”和账户实际扣/入账金额。

第三部分，如贵司提供 deliverable forward、NDF 或可交易 forward points 历史，请提供 1M、
3M 的逐次/逐日 bid points、ask points、同一时刻 spot bid/ask、报价单位、观察时间、客户可用
时间、venue/流动性来源和修订编号。若贵司不提供历史可交易远期，请直接回复“不提供”；政策
利率、利率平价合成值或当前网页截图不能代替历史可交易 bid/ask。

首选 CSV 或其他机器可读格式，并请附字段说明、原始导出文件名/版本、生成时间、支持工单号
或可复核的来源标识。若因许可限制不能发送数据，请告知可购买产品、可查询 API、最早日期、
保留期限、费用和许可范围。

另外请确认：practice/demo 与 live 账户的融资规则是否完全一致；不同法律实体、账户层级、
交易规模是否使用不同费率；历史数据是否包含事后更正，如包含，请说明版本和更正时间。

谢谢。

## 收到数据后的本地合同

融资 CSV 使用
[broker_financing.schema.csv](../examples/cost_contract/broker_financing.schema.csv)，远期 CSV 使用
[tradable_forward_quotes.schema.csv](../examples/cost_contract/tradable_forward_quotes.schema.csv)。
核心字段解释如下：

| 字段 | 含义 | 关闭条件 |
|---|---|---|
| `effective_time` / `observation_time` | 成本生效时间/报价时刻 | 必须明确时区 |
| `available_time` | 当时客户最早可知或可取得的时间 | 远期不得早于报价时刻 |
| `long_financing`, `short_financing` | 同一口径的多空融资值 | 不允许用一侧的相反数推造另一侧 |
| `unit`, `day_count` | 金额口径与日计数 | 缺失时不能换算实际成本 |
| `triple_swap_weekday` | 常规三倍计息星期 | 不能默认周三适用于所有品种 |
| `rollover_multiplier` | 该费率行对应的实际日数乘数 | 需覆盖假日和临时调整 |
| `account_currency` | 被请求账户的结算币种 | 不默认 USD |
| `broker_entity` | 完整法律实体 | 品牌名不足以通过审计 |
| `source`, `provenance`, `version` | 来源、工单/档案标识与版本 | 空白即失败 |
| `quote_quality` | 明确的数据性质 | 自填标签不证明真实性 |

融资正式候选标签只能是 `historical_target_broker_schedule`；远期正式候选标签只能是
`historical_tradable_bid_ask`。`software_fixture`、`unknown_unverified`、mid-only、政策利率或
合成远期只能用于软件/研究。

CSV 旁必须放同名 `.manifest.json`，记录 CSV 精确 SHA-256 和逐行来源目录，格式见
[source_manifest.schema.json](../examples/cost_contract/source_manifest.schema.json)。manifest 只能
证明“审核的是哪一份字节”，不能证明 broker 数据真实；来源真实性仍需人工复核工单、法律
实体和说明文档。

运行审计示例：

```bash
uv run fxtrade cost-coverage-audit \
  --swap-csv /path/to/broker_financing.csv \
  --forward-csv /path/to/tradable_forward_quotes.csv \
  --broker-entity '完整法律实体名称' \
  --account-currency '实际账户币种' \
  --symbols 'EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,NZDUSD,USDCAD,EURGBP,EURJPY,GBPJPY,AUDJPY,CADJPY,USDNOK,USDSEK'
```

即使 schema、manifest 和覆盖率通过，CLI 仍不会自行把来源真实性设为已验证，也不会批准
正式净收益或交易。真实性确认需要独立的外部证据审核流程；在该流程存在前，报告保持
`cost_incomplete_research_only`。

## 仍需账户持有人决定的最小字段

1. broker 的完整法律实体（不是品牌简称）；
2. live 账户类型/层级；
3. 账户币种；
4. 所属监管辖区；
5. 该实体对每个品种的三倍计息与节假日规则；
6. 是否购买/获许可保存和用于回测的历史数据。
