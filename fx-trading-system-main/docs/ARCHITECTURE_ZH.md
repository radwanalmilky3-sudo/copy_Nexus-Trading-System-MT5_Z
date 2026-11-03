# 架构与数据流

## 数据流

```text
CSV / Yahoo / Synthetic / OANDA fxPractice BA / Dukascopy tick BA
          │
          ▼
  UTC mid 或 bid/ask OHLC 校验与对齐
          │
          ├── 慢周期日频面板 → 21 日调仓 → 21/42/63 日标签
          │                         → purge + BH/BY + 非重叠 OOS
          │                         → 1/2/3 sleeve → 主账户净目标
          │                         → 每日 MTM/成本账本 → DSR/PBO/SPA 输入
          ├── current-vintage 快照 / GSCPI 与 RTDSM 真 vintage
          │                         → available_time / future canary
          ├── IANA 事件模板 → Tokyo / ECB / WMR / 本地时段 / FX 日界
          ├── point-in-time 利率 / forward / swap
          ├── CFTC TFF → 保守 available_time → 周频币种仓位差
          │               │
          │               ▼
          │       Carry + 受约束因子 DSL
          ├── 单品种策略 ──────┐
          └── 多货币策略 ──────┤
                               ▼
                        加权冲突消解
                               │（收盘信号）
                               ▼
                       下一根 K 线开盘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
       组合风险与币种敞口                 成交成本与 FX 换算
              └────────────────┬────────────────┘
                               ▼
                  事件回测 / 模拟订单计划
                               │
                               ▼
               Trades + Equity + Manifest + Report
```

## 关键不变量

1. 策略在时间 `t` 的 close 上生成信号，执行调度使用 `searchsorted(..., side="right")`，因此
   只能在该品种严格晚于 `t` 的 bar 开盘成交。
2. `target_atr / stop_atr <= risk.max_reward_risk <= 1.0`，即使策略参数写得更高，执行引擎
   也会再次裁剪目标距离，风险层还会拒绝越界信号。
3. `max_holding_hours <= 168` 同时由配置验证和执行引擎限制。
4. 所有 PnL、风险、名义本金和货币敞口通过当时可用的 FX 图换算为 USD；非 USD quote
   不使用固定点值。
5. 协整双腿共享 `group_id`；组内任一腿未通过风险检查时，已预开的腿回滚。
6. 回测结束强制平掉全部头寸，不把未实现收益伪装成已实现结果。
7. 同 bar 止盈止损顺序未知时按止损，防止乐观偏差。
8. `enabled` 只表示进入研究；只有额外标记 `paper_enabled` 的策略才能生成 practice 订单计划。
9. 实时数据源删除尚未收盘的最后一根 K 线；practice 计划带到期时间和稳定 client ID，
   重复提交由 broker 幂等键拒绝。
10. 双边数据按可成交侧执行：long 为 ask 入/bid 出，short 为 bid 入/ask 出；止盈止损也检查
    对应可成交侧的 high/low。
11. 宏观、利率、远期和 swap 只按 `available_time` 向后合并；修订值不会回填到其发布时间前。
    OIS/forward 正式覆盖率还要求逐行 source/provenance/quote-quality 与哈希 manifest 相互验证；
    政策/隔夜利率代理和利率平价合成远期只保留在探索层，不能晋级。
12. DSL 不执行任意代码；候选数、复杂度、原语和算子均由配置限制，所有候选计入 FDR。
13. 只有 candidate verdict 才生成冻结模型；forward 命令校验模型 SHA-256、因子/成本/风险/
    市场契约，只接受严格晚于冻结时间的数据，且没有任何拟合或重选路径。
14. 1–3 个月慢周期模块与 168 小时短周期引擎隔离；筛选只使用 21 日调仓标记，63 交易日
    bootstrap 块按调仓频率换算为 3 个观测，训练标签终点必须早于 OOS 起点。
15. 21/42/63 日期限分别只有 1/2/3 个等预算 slot；warm-up 保留现金，不放大已填 slot。
    所有 sleeve 先汇总成主账户目标，只对净 `Δq` 计算换手和成本。
16. 可成交 bid/ask 已含 spread 时不再重复扣 spread；等价的 mid 会计只允许逐笔扣一个
    half-spread。每日价格、点差、滑点、融资、利息之和必须精确对上 NAV 变化。
17. 负对照使用跨全部品种共同的日期映射；future-information canary 必须在任何收益计算前被
    availability audit 拒绝。
18. 日内事件按每个本地日期使用 IANA 时区逐端点转换，manifest 记录 tzdb；节假日和 LSEG
    实际发布日不能由周一至周五规则猜测。
19. FIX-W 使用冻结 G9 美元腿和四段有符号头寸；USD 为基准货币的市场报价先交换 bid/ask
    后取倒数，缺腿不重归一化。每次正式 runner 调用对 9 个必需数据库各做一次整库
    传输验证并复用 receipt，窄窗仍逐小时验证 payload SHA-256；receipt 本身不会被自动另存。
20. Tokyo/WMR 是否发生来自 WM/Reuters、Refinitiv、LSEG 的官方 service-alteration PDF；ECB
    日期来自官方 `EXR.D.USD.EUR.SP00.A` 2:15 p.m. CET 序列。正式 calendar 同时验证 CSV、
    source manifest 和原始文件哈希，周末及半日服务不靠通用假日包猜测。
21. 日内验证要求声明完整候选集，只使用共同事件日交集且不填充缺失；联合 stationary
    bootstrap、BH/BY、共同日期符号负对照和 future canary 先于 DSR/PBO 诊断。项目已有
    透明、真正 studentized 的 Hansen SPA 核心，但正式 runner 尚未调用，且不会自动批准交易。

## 当前边界

- Yahoo 仍是 midpoint 公共数据；OANDA candle API 有 bid/ask，但历史 swap 和 point-in-time
  forward/OIS 必须由独立授权数据补充。
- bar 回测无法知道 bar 内路径；保守 stop-first 只能降低而不能消除这一不确定性。
- Carry 数据契约和因子已启用；仓库不分发商业 OIS/forward 历史。宏观 surprise、订单簿和
  新闻数据仍需新的 point-in-time 适配器。
- DSR、PBO 和项目内 Hansen SPA 都只是统计诊断；SPA 核心已有合成测试，但正式组合 runner
  尚未调用，也没有合格方向候选可运行真实组合。这些诊断不能替代新的冻结后前向样本；SPA
  只修正实际传入的共同日期候选列，不能自动覆盖未形成收益列的 3,312 次历史搜索。
- Dukascopy SQLite 已能经整库 transfer receipt 与逐 payload 哈希生成纽约 17:00 日线
  bid/ask；日线只在开收边界 5 秒内有报价且全部源小时完整时生成。正式跨品种适配器拒绝
  单品种缺日、不做交集或填充，并保留真实 21:00/22:00 UTC 收盘时间。
- 慢周期 SQLite factor-only 编排/CLI、注册表约束的完整 7 单元候选，以及 21/42/63 日
  close-t decision / next-open / scheduled-close 信号调度已接通；它不会生成未来标签或收益。
  成本后账本到 DSR/PBO/SPA 输入的另一端也已具备，独立次日开盘/收盘两阶段合成账本亦已
  通过测试；尚未接通的是两端串联、重叠 sleeve 与跨候选预算、账户币种 quantity/FX
  conversion、未实现 PnL cost basis/broker settlement、历史 financing/真实 forward、
  slippage/commission、逐品种 quote timestamp，以及 SPA 正式 runner/manifest。
- OANDA 只实现 practice 市价单 + attached stop/target；没有真实资金执行路径。
