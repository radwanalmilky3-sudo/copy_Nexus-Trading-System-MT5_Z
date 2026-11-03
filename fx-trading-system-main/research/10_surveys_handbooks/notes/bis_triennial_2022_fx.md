# [BIS 2022] Triennial Central Bank Survey — OTC FX Turnover（解释性笔记）

- 深度层级: L2 官方 + L3 解释（**结构校准 only**）
- 引用链角色: data_contract / boundary
- DOI/URL: https://www.bis.org/statistics/rpfx22.htm  
  - 主文: `_pdfs/_bis/rpfx22_fx.pdf`  
  - 详表 annex: `_pdfs/_bis/bis_triennial_2022_fx_annex.pdf`  
  - 2019 对照: `_pdfs/_bis/rpfx19_fx.pdf`
- 开放获取: BIS 官方 **是**
- 本项目映射: 币种宇宙、工具结构、对手方与地理集中度；**禁止**作日/月方向或拥挤度时间序列
- 复制状态: negative_control for alpha；extension_only for universe design
- 公式置信度: high（官方定义）；解释层 medium
- published premium vs implementable: 不涉及溢价
- 2016–2025 外推风险: 低（本就是 2022-04 截面）；下一次调查前结构可能漂移

## 1. 经济机制 / 调查目的

BIS 三年一度央行调查是全球 OTC **外汇与利率衍生品**规模与结构的最全面公开源。目标：提高 OTC 透明度，供央行与市场参与者监测，并服务监管改革讨论。

**不是**价格发现模型，也**不是**可交易信号库。对研究的正确用法：

1. 校准“G9 / 主要对”是否仍覆盖大部分可交易流动性。  
2. 理解 **FX swap 主导** → 融资/对冲存量巨大（与 Borio 2022 表外美元义务叙事衔接）。  
3. 理解交易对手结构（dealer / 其他金融机构 / 非金融客户）与地理集中（UK/US/SG/HK/JP）。  
4. 设定微观结构外推边界：零售/单一报价源 ≠ 全球 OTC。

## 2. 精确“公式”与统计定义

```text
# 调查窗：2022-04 全月；报告为日均成交额（USD）
# 报告主体：销售台（sales desk），不论成交执行地；未并表（含关联方交易）

# 双重计算调整：
# net-net : 扣除本地 + 跨境 dealer 间双重计算 → 全球总量主口径
# net-gross: 仅扣本地 dealer 双重计算 → 地理分布常用

# 工具拆分（FX）：
# Spot | Outright forward | FX swap | Currency swap | FX options (+ other)

# 2022 引入 non-market-facing 子项：
# - back-to-back（客户成交后自动在销售台间转移风险）
# - compression（压缩名义、净暴露不变）
# 合计 non-market-facing ≈ 12% of global FX turnover（2022）

# 货币份额惯例：
# 每笔交易两侧货币各计一次 ⇒ 所有货币份额之和 = 200%
```

## 3. 数据与样本（2022 要点）

| 项 | 2022 调查 |
|---|---|
| 管辖区 | 52 |
| 报告机构 | >1,200 银行与其他 dealer |
| 全球 FX 日均（net-net） | **$7.5T**（2019: $6.6T，+14%） |
| 工具结构 | FX swaps **51%**；spot **28%**；outright forwards **15%**；options ~4%；currency swaps ~2% |
| 美元 | 一侧出现于 **88%** 交易（与 2019 相同） |
| 欧元 / 日元 / 英镑 | ~30.5% / 17% / 13%（一侧份额） |
| CNY | 份额上升最显著的大币种之一（调查强调） |
| 对手方 | inter-dealer 升至约 **46%**（2019: 38%）；非金融客户降至 ~6% |
| 其他金融机构 | 非报告银行、机构投资者、对冲基金/PTF 等；机构投资者与 HF/PTF 份额趋势下行 |
| 地理（net-gross） | UK+US+SG+HK+JP ≈ **78%**；UK ~38%（2019: 43%），US ~19% |
| 跨境 | 总成交中跨境约 **62%**（2019: 56%） |
| 环境备注 | 2022-04 波动升高（利率路径、商品、地缘）；部分法域仍有疫情限制 |

Annex 表 1 量级（百万美元日均，net-net，与主文一致量级）：

| 工具 | 约日均 |
|---|---|
| Total | 7,505,992 |
| Spot | 2,104,019 |
| Outright forwards | 1,163,471 |
| FX swaps | 3,810,157 |
| Currency swaps | 123,945 |
| FX options | 304,330 |

## 4. 成本与可实现性

- 调查给**名义成交**，不给可成交点差、不给零售 swap。  
- FX swap 占主导 → 学术 “1M outright carry” 只覆盖工具结构中的一小块；融资腿大量在 swap/tom-next。  
- 对本项目：OANDA/Dukascopy 路径的成本合同**不能**用 Triennial 平均量“填”。  

## 5. 识别与稳健性（解释层）

- 增长率受汇率折算、关联方/ back-to-back 识别改进、疫情影响。  
- 2022 首次拆 non-market-facing → 与历史调查比价时注意口径。  
- 地理用 net-gross，全球总量用 net-net → **禁止混用口径讲故事**。  
- 货币份额和为 200% → 禁止当成 100% 概率权重。

## 6. 复制清单 / 允许用途

| 用途 | 允许？ | 条件 |
|---|---|---|
| G9 宇宙覆盖论证 | 是 | 引用调查年与表号 |
| 工具结构（swap vs spot）教育 | 是 | |
| 流动性假设校准（研究设计） | 是 | 定性/粗校准 |
| 月度拥挤度 / 日方向因子 | **否** | 三年一点 |
| 替代 signed order flow | **否** | |
| 填补零售 historical swap | **否** | |
| FDR 候选特征 | **否** | |

| 字段 | 项目 | 缺失时 |
|---|---|---|
| 调查 edition 与表定义 | 必须记录 | 不可比 |
| net-net vs net-gross | 必须声明 | 误读地理 |
| 日度时间序列 | 无 | 禁止伪高频化 |

## 7. 本项目映射

| 项 | 映射 |
|---|---|
| `08_datasets_catalog` | BIS Triennial 条目；`strict_pit_eligible=false` 作方向 |
| `06_broker_costs` / Borio | swap 存量与表外美元 → 融资合同背景 |
| `03_microstructure` | 成交集中 UK/US；定盘与主中心时区 |
| `02_factor` | 不增加方向因子；仅说明学术 G10 样本的市场代表性 |
| 否决 | “根据 Triennial，某币种拥挤，故反转” |

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| 姊妹调查 | 2019 / 2016 Triennial | 结构对照 |
| 机制 | Borio et al. 2016/2022 | basis 与表外美元 |
| 微观 | Lyons；Evans–Lyons；Mancini–Ranaldo–Wrampelmeyer | 成交结构 vs 价格影响 |
| 本库 | `06/.../borio_bis_basis.md`；`08/...` BIS 笔记 | |

## 9. 精读问题

1. 在 FX swaps = 51% 的市场里，用 1M outright forward 复制 carry 遗漏了哪类融资风险？  
2. inter-dealer 份额在波动月上升，对“客户订单流 alpha”外推意味着什么？  
3. 为何 net-gross 地理份额不能直接解释“价格在伦敦决定”？  
4. CNY 份额上升如何影响“G9 only”研究的外推声明？  
5. 将 Triennial 与 Dukascopy tick 覆盖对比时，最小诚实表述应包含哪三个限制？
