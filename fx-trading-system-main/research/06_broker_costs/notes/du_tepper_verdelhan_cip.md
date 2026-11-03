# [Du, Tepper & Verdelhan 2018] Deviations from Covered Interest Rate Parity

- 深度层级: L5
- 引用链角色: foundational / data_contract
- DOI/URL: https://doi.org/10.1111/jofi.12620
- 开放获取: NBER w23170 https://www.nber.org/system/files/working_papers/w23170/w23170.pdf ；SSRN 2768207
- 本项目映射: CIP 字段合同；`QendW`/`QendM`；**非** spot 方向策略
- 复制状态: fail_closed_missing_data（缺同步 forward+OIS+结算）

## 1. 经济机制

主要货币 CIP 偏离在危机后仍大、持续且系统。信用风险与简单买卖价差不能完全解释。偏离在**季末进入银行资产负债表的远期**上特别强，指向银行监管/报表约束对资产价格的因果压力。CIP basis 还与其他固收利差和名义利率相关。

## 2. 精确公式

```text
# CIP 套利（示意，实现必须锁报价方向与 day-count）:
# 借款货币 A、经 FX swap 换 B、投 B、远期换回 A
# 利润 ≈ 现金利差 − 远期点差  （无 basis 时应≈0）

# 文中关注 |basis| 在监管窗口的抬升
# Quarter-end 标志（项目文献地图冻结口径）:

QendW = 1  iff
  spot T+2 settlement ∈ 本季度最后一周
  AND 1W forward maturity ∈ 下一季度

QendM = 1  iff
  1M forward 的 settlement 与 maturity 跨季度

# 回归结构（概念）:
|basis_{tenor,t}| = α + β * QendFlag_t + controls + ε_t
```

**数据合同最小集：**

```text
spot, outright forward (同 tenor),
matching-maturity OIS/repo/当时基准利率,
settlement & maturity calendar,
quote convention, timestamp
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 主要货币对 |
| 频率 | 日度 basis |
| 样本 | 危机后为主（见原文表） |
| 价格/远期/利率 | 银行间/Bloomberg 类市场数据 |
| 排序与再平衡 | 事件/日历回归，非横截面货币排序因子 |

## 4. 成本与可实现性

- 原文：套利利润与 basis，银行间摩擦
- 零售：tom-next + admin markup **不是** 文中 1W/1M CIP 面板
- midquote premium ≠ implementable：无双边 forward 不能声称复制
- 用 spot 季度末形态替代 Qend 合同 = **另一实验**

## 5. 识别与稳健性

- 主结果：季末 basis 抬升；监管渠道
- 控制：信用、流动性等（见原文）
- 已知衰减/边界：制度变化后窗口强度可改；2016–2025 需自建合同而非照搬系数

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 1W/1M 双边 forward | 是 | 无正式史 | fail closed |
| 同 tenor OIS | 是 | 仅示例/proxy 路径 | fail closed |
| T+2 / maturity 日历 | 是 | 未完整 CIP 日历 | fail closed |
| Dukascopy spot | 执行扩展 | 进行中 | 不能叫 DTV 复制 |
| 账户 swap | 净收益 | 缺 | cost_incomplete |

## 7. 本项目映射

- `CIP_CONTRACT_CHECKLIST.md`
- 文献地图否决：无 forward 的“季度末方向”
- 不增加 FDR 方向候选
- 注册：若未来做 |basis| 事件研究，须单列假设并计入试验数

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Du–Tepper–Verdelhan | CIP 偏离与季末 |
| macro plumbing | Borio et al. | 对冲需求与套利约束 |
| boundary | 本项目零售成本 | 不同微观结构 |

## 9. 精读问题

1. 1W vs 1M basis 对 21 日持有 carry 的映射误差有多大？
2. 季末窗口应用风险门控时，如何避免用结果反选阈值？
3. 零售 triple-swap Wednesday 与银行季末是否同机制？
