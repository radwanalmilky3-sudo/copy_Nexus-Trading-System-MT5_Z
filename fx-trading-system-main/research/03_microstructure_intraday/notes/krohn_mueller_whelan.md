# [Krohn, Mueller & Whelan 2024] Foreign Exchange Fixings and Returns around the Clock

- 深度层级: L4
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1111/jofi.13306 ；作者接受稿 https://wrap.warwick.ac.uk/id/eprint/177333/ ；SSRN abstract_id=3521370
- 开放获取: WRAP 作者接受稿可读；期刊版 Wiley
- 本项目映射: `FIX-W` 四段组合（`-preTokyo + postTokyo - preECB + postWMR`）
- 复制状态: extension_only（G9 美元腿冻结组合 + 可成交 bid/ask + 官方发布日历）；midquote 毛收益不足以免否决

## 1. 经济机制

外汇定盘（Tokyo 09:55、ECB 14:15 CET、London WMR 16:00）是全球资产估值与对冲的参考时刻。大量客户在定盘前后无条件地索取 USD 流动性；做市商必须中介这部分需求并承担库存风险，因此要求补偿。补偿通过 bid–ask 与正的预期库存收益同时出现，表现为定盘前 USD 升值、定盘后 USD 贬值的 V 型/日间 W 型路径。自然实验（DST 错位、非同步假日、定盘引入与交易结构变化）显示：**存在已发布参考价**本身决定反转时点，而非泛化的“亚洲/欧洲开盘”。

## 2. 精确公式

原文（AAM/SSRN 叙述）对 G9 货币，按 ET 报告日内窗口（并强调 Tokyo 用 09:55 当地时间对齐 DST）：

```text
# 原文讨论的五段（时间以 ET 叙述；Tokyo 边界按 09:55 Asia/Tokyo 对齐）
pre_T  : 17:00 NY_prev → Tokyo_fix
post_T : Tokyo_fix → Europe open (~02:00 ET / Berlin 08:00)
pre_E  : Europe open → ECB_fix (14:15 Berlin)
E_to_L : ECB_fix → WMR_fix (16:00 London)
post_L : WMR_fix → 17:00 NY

# 反转组合（Tokyo 窗 / Europe 窗）：定盘前做多 USD，定盘后反手做空 USD
R_Tokyo,t  = + r_pre_T,t  - r_post_T,t
R_Europe,t = + r_pre_E,t  - r_post_L,t   # 文中将 ECB 前与 WMR 后合为 Europe 窗

# DOL：九个外币对 USD 等权
DOL_t = mean_i r_i,t
```

本项目冻结的可执行规格（见 `src/fx_system/intraday_research.py`）**不是**五段全复制，而是四段有符号组合，且 post-WMR 从 **WMR+2m30s** 起（避开五分钟定盘窗中心之后的半窗）：

```text
segments (sign on USD-per-foreign standardized quotes):
  pre_tokyo  : NY17:00_prev → Tokyo 09:55 , sign = -1
  post_tokyo : Tokyo 09:55  → Berlin 08:00, sign = +1
  pre_ecb    : Berlin 08:00  → ECB 14:15  , sign = -1
  post_wmr   : WMR+2:30     → NY 17:00   , sign = +1

# 反向报价腿：bid' = 1/ask, ask' = 1/bid
# 起点：边界严格之后 ≤5s 首个有效报价
# 终点：边界当时或之前 ≤5s 最后有效报价
# G9 任一腿/任一段缺失 → 当日 composite 不重归一化，为空
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | Top-9 / G9 交易量最大 USD 腿（约覆盖全球 spot 75%，BIS Triennial） |
| 频率 | 高频日内；分钟级构造与 1 分钟 RV |
| 样本起止 | 1999-01 至 2019-12（约 21 年） |
| 价格来源 | 高频 FX（定盘程序叙述对齐 Thomson Reuters / 公开定盘规则） |
| 排序与再平衡 | 无横截面排序；日内固定窗口反转，等权 DOL |

## 4. 成本与可实现性

- 原文扣除：主结果大量报告 **未扣交易成本** 的 mid/反转收益；并明确年化数字“before taking transaction costs into account”。
- 迁移到零售 bid/ask 后的破坏点：
  1. 定盘窗流动性索取方支付 spread；库存溢价本就通过 spread 与短期价格压力共同实现；
  2. Dukascopy 是**单一零售报价源**，不是 EBS/全市场 consolidated tape；
  3. 四段任一段 spread 恶化即可抹掉 1–3 bps 量级的日均毛效应。
- midquote premium ≠ implementable net：**若可成交侧净收益 ≤0，直接否决**，禁止靠缩短窗口或事后删腿“抢救”。

## 5. 识别与稳健性

- 主结果：G9 在 Tokyo 与 Europe 定盘前后出现系统 V/W 型；DOL 定盘前约 2 bps 量级贬值、定盘后对称反转（量级随币种变化）。
- 自然实验：日本假日无 Tokyo 定盘时 Tokyo 反转消失、欧洲窗仍在；DST 改变 Tokyo 相对 ET 时钟但反转钉住当地 09:55；定盘引入/交易结构变化改变反转时点。
- 机制：无条件 USD 需求 → 做市商库存 → 与波动状态交互的订单不平衡；非纯非对称信息。
- 已知失败或衰减：流动性供给者视角与流动性索取者视角收益符号相反；2016–2025 监管/电子化后需独立迁移检验。

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| tick bid/ask + UTC 时间戳 | 是 | Dukascopy SQLite（到达后） | fail closed |
| 官方 Tokyo/ECB/WMR 发生日与时刻 | 是 | `PublicationCalendar` + raw hash | fail closed |
| G9 九腿：AUD/CAD/CHF/EUR/GBP/JPY/NOK/NZD/SEK | 是 | 下载宇宙含 NOK/SEK | 缺腿不重归一 |
| 5s 边界报价完整性 | 是 | 硬编码 | 当日腿/组合空 |
| 全市场订单流 | 否（机制） | 无 | 不声称库存识别复制 |
| 目标账户实际成交价 | 晋级时 | 无 | research_only |

## 7. 本项目映射

- registry / 实验名：`FIX-W`；runner `run_fix_w_from_sqlite`
- 持有期：四段日内，事件日为单位
- 否决条件：
  1. 可成交净收益（long ask-in/bid-out 或 signed 可成交侧）≤0；
  2. 官方日历未 verified / 半日市/停服未审计；
  3. 用 1h bar 冒充 5s 边界；
  4. 缺腿后对剩余腿 renormalize；
  5. 未过 spread q90 过滤却报告 filtered composite。
- reused-history 备注：1999–2019 文献与 Yahoo 探索已看过同市场史；Dukascopy 2016–2025 只作执行迁移/否决，不作 untouched holdout。

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Evans & Lyons 订单流 | 库存/信息传导机制 |
| related | Melvin & Prins 月末 WMR 对冲 | 定盘需求的机构来源之一 |
| related | Ito & Yamada Tokyo fix | 东京定盘制度 |
| boundary | LSEG WMR methodology | 五分钟窗与半日规则的官方合同 |
| extension boundary | Mancini et al. 流动性 | spread 过滤与共同流动性 |

## 9. 精读问题（给最强模型）

1. 原文 Europe 窗是 `+preECB −postWMR` 还是包含 ECB→WMR 中段？项目删掉 ECB→WMR 中性段的统计后果？
2. “liquidity demander after costs can lose” 的原文表号与数值阈值如何翻译成项目硬门槛？
3. post-WMR 从 `16:00` 还是 `16:02:30` 起算对可成交侧更保守？
