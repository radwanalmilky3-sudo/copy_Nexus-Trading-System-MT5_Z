# [Borio et al. 2016 / 2022] Cross-currency basis 与表外美元义务

- 深度层级: L4
- 引用链角色: data_contract / boundary
- DOI/URL:
  - 2016: https://www.bis.org/publ/qtrpdf/r_qt1609e.htm
  - 2022: https://www.bis.org/publ/qtrpdf/r_qt2212h.htm
- 开放获取: BIS 官方 HTML/PDF **是**
- 本项目映射: CIP/资金压力合同；**不是** G9 日度方向因子
- 复制状态: extension_only（机制/状态）；fail_closed_missing_data（日度 basis 交易）

## 1. 经济机制

**2016：** CIP 在危机后持续偏离。cross-currency basis 度量“通过 FX swap 借入某货币”相对“现金市场直接借入”的成本差。偏离由（i）价格不敏感的对冲需求（银行结构性美元缺口、机构投资者境外资产对冲、企业发行后互换）与（ii）套利者资产负债表成本上升（资本、杠杆、信用额度、抵押品）共同支撑。

**2022：** FX swaps / outright forwards / currency swaps 创造大量**表外**美元付款义务；常规债务统计看不见其地理与对手方拆分。存量巨大且期限短 → 滚动融资脆弱（2008、2020-03）。

## 2. 精确公式

```text
# CIP 教科书（惯例依赖报价）
F/S ≟ (1 + r_USD * τ) / (1 + r* * τ)   # 或相反；实现时锁死 convention

# Basis 概念（Borio 2016）:
# 非零 basis = 通过 FX swap 融资成本 ≠ 现金市场融资成本
# 市场常用 cross-currency basis swap 报价 b 使平价恢复：
# 一侧 Libor+ b 与另一侧 Libor 互换（细节依货币与 tenor）

# 需求 × 摩擦示意:
basis ∝ (hedging_demand) × (balance_sheet_cost / risk_premium)
```

**2022 估算（非交易信号）：**

```text
# 非银表外美元负债 ≈ 0.5 * dealers 对非银美元 FX swap 存量
# 非美银行表外美元债 ≈ 复杂组合：全球 OTCD − 美国银行 OCC + LBS/CBS 调整
# 2022-06: FX swap/forward/currency swap 名义 ~$97T；美元一侧 ~88%
```

## 3. 数据与样本

| 项 | 2016 | 2022 |
|---|---|---|
| 资产/币种 | 主要自由兑换、高主权评级 | 全球美元腿为主 |
| 频率 | 研究用 3M/2Y basis 等 | 半年/三年调查 + 存量 |
| 来源 | BIS banking stats、对冲代理、债券发行 | Triennial、OTCD、GLI、LBS/CBS、OCC |
| 用途 | 解释 basis 水平/符号 | 度量“失踪的美元债” |

## 4. 成本与可实现性

- 原文：解释性，不给可交易日度规则
- 迁移：需要逐对、双边、带结算日的 forward + OIS 才能谈 CIP 交易层
- BIS 聚合 **不能** 填 G9 每日方向或零售 swap

## 5. 识别与稳健性

- 主结果：CIP 偏离持续；对冲需求与监管后套利约束
- 2022：表外美元义务大于表内；短期限滚动风险
- 失败模式：把季度 GLI 当 alpha；把 basis 符号当无成本方向

## 6. 复制清单

| 字段 | 需要？ | 本项目 | 缺失时 |
|---|---|---|---|
| 日度双边 forward | 交易层 | 缺 | fail closed |
| 同 tenor OIS | CIP | 缺正式史 | fail closed |
| BIS 低频状态 | 分层/风险 | 可目录化 | 仅发布后状态 |
| 零售 swap | 账户净收益 | 缺 | cost_incomplete |

## 7. 本项目映射

- 文献地图：约束合同，不增方向候选/FDR 分母
- `CIP_CONTRACT_CHECKLIST.md` 字段来源
- 否决：`F_hat` 冒充 market F；BIS 补洞

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Borio et al. 2016 | basis 定义与机制 |
| extension | Borio–McCauley–McGuire 2022 | 表外美元债 |
| micro CIP | Du–Tepper–Verdelhan | quarter-end 识别 |

## 9. 精读问题

1. 零售 tom-next 与 3M xccy basis 的期限结构如何对齐到 21 日持有？
2. 季度末监管窗口是否应只做风险 off，而非方向因子？
3. 2022 估算假设（非银不借美元等）对 2016–2025 稳健吗？
