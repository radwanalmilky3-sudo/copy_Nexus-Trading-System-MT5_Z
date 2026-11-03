# WMR vs ECB vs Tokyo Fix — 对照表（研究级）

- 深度层级: L2–L3
- 角色: foundational / data_contract
- DOI/URL:
  - LSEG WMR methodology（官方 PDF）
  - ECB euro reference rates 页面
  - 东京定盘市场惯例 / 学术 FIX 文献（见 03_microstructure）
- 开放获取: 方法论摘要公开；完整 tick 权重细节部分付费
- 本项目映射: 日界、事件窗、value 因子定盘对齐
- 复制状态: extension_only（无官方 WMR 许可序列则不可声称“官方 WMR 复制”）

## 1. 经济机制

“定盘价”是 **基准/参考构造**，不是统一的可成交成交价。不同 fix 服务不同用户（资产管理人基准、ECB 统计、日本进出口结算），窗口长度、贡献源、异常处理不同。用 ECB 参考价当 WMR 月末对冲代理，或用 Tokyo fix 当全球日收盘，会引入 **系统性时间错配**。

## 2. 对照表

| 维度 | WMR (LSEG / WM Reuters) | ECB euro FX reference rates | Tokyo fix（市场惯例） |
|---|---|---|---|
| 典型用途 | 投资组合估值、指数、对冲基准 | 欧元区统计与政策参考 | 日本企业/银行进出口结算、本地基准 |
| 主时刻（civil） | 16:00 London（主定盘；另有多时点服务） | 14:15 CET | 约 09:55 JST（传统“定盘”窗；细节随平台/时代） |
| 窗口结构 | 方法论规定的短窗采样/中位或相关稳健统计（以现行 WMR methodology 为准） | 集中采集参考报价 | 市场参与者在定盘前后交易；学术常定义 pre/post 窗 |
| 是否“可成交保证” | **否** — 基准；执行需另议 | **否** — 参考价 | **否** — 惯例锚点 |
| 主要货币覆盖 | 广（多币种服务） | 以 EUR 交叉为主的参考集 | 以 JPY 交叉为中心的本地重要性 |
| 月末效应文献 | 强（对冲流、WMR 窗口压力） | 相对弱于 WMR 作为全球资管基准 | 本地结算流；与全球资管 WMR 流不同 |
| DST 风险 | London 夏令时 ↔ UTC 偏移变化 | CET/CEST | JST 无 DST，但与 UTC 对照仍要 IANA |
| 本项目默认角色 | 全球基准事件 / 月末研究锚 | 欧元参考对照，**非** WMR 替代 | Asia 开盘/本地定盘事件 |

## 3. 时间字段合同

```text
fix_id            ∈ {WMR_1600_LON, ECB_1415_CET, TKY_0955_JST, ...}
civil_local_time  = 墙上时钟（带时区名，非固定 UTC 偏移）
window_start_utc  = tz_convert(civil - pre_seconds)
window_end_utc    = tz_convert(civil + post_seconds)
source_series     = 官方序列 or 代理（必须标注 proxy）
tradable_flag     = false for reference/benchmark unless broker contract says otherwise
```

**强制规则：** civil time → UTC 必须用 **逐日 IANA/DST**，禁止 `UTC+0 = London` 全年假设。

## 4. 互相不可替代的原因

1. **时刻不同**：14:15 CET ≠ 16:00 London ≠ 09:55 JST。  
2. **用户流不同**：ECB 参考更新 ≠ 全球共同基金 16:00 对冲。  
3. **构造不同**：参考采集 vs 基准方法论 vs 市场惯例成交聚集。  
4. **修订/可用性**：官方历史发布节奏、货币列表、方法论变更日不同。

## 5. 代理使用规则（本项目）

| 研究问题 | 可接受锚 | 禁止 |
|---|---|---|
| 月末全球对冲流 | WMR 窗（或明确 proxy + 误差讨论） | 用 ECB 14:15 冒充 WMR |
| 欧元区宏观对齐 | ECB ref | 声称可成交执行价 |
| Asia 开盘微观结构 | Tokyo 定盘窗 + 本地流动性 | 用 NY 17:00 日界替代 |
| 本项目 FX 日界 PnL | 配置的 America/New_York 17:00（账户/研究日界） | 把日界叫做 “WMR close” |

## 6. 与 03_microstructure 的边界

- 本笔记只固定 **定义与对照**。  
- 窗口内流动性、last-look、抢跑等 → `03_microstructure_intraday/`。  
- 若 Micro 已有 WMR 专文，本表作 foundations 入口，不重复微观实证。

## 7. 本项目映射

- 事件研究配置键：`fix_id`, `pre_s`, `post_s`, `tz`  
- 否决：三 fix 混用同一 “close” 字段  
- 数据合同：任何 `close` 列必须带 `close_definition`

## 8. 精读问题

1. 方法论变更日（WMR 窗口规则调整）如何切断前后样本？  
2. 仅有 Dukascopy 报价时，如何 **诚实** 标注 “WMR-window proxy”？  
3. ECB 参考价是否可用于价值因子的 monthly REER 对齐？代价是什么？
