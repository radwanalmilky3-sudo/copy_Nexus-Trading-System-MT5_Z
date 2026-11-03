# [Rubaszek, Beckmann, Ca' Zorzi & Kwas 2022] Boosting Carry with Equilibrium Exchange Rate Estimates（ECB WP 2731）

- 深度层级: L3
- 引用链角色: foundational extension（**value/EER 慢收敛 × carry**）
- DOI/URL: ECB WP 2731 https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2731.en.pdf
- 开放获取: `_pdfs/_ecb/ecb_wp2731_boosting_carry_eer.pdf`（first-page OK）
- 本项目映射: 最接近项目 **currency value + carry 混合**；REER/PPP/BEER **vintage** 关键
- 复制状态: extension_only（均衡汇率定义与修订）/ fail_closed 若无 PIT 宏观
- 公式置信度: high（ECB WP）
- published premium vs implementable: 组合层盈利叙事；非零售净收益
- 2016–2025 外推: 慢均值回复与 carry 共存的逻辑仍强；均衡估计误差大

## 1. 经济机制

两支 FX 文献常被用来支持“汇率不可预测”：（i）时间序列上随机游走难被宏观模型击败；（ii）组合层 **carry** 把未来汇率当噪声仍能赚钱。作者主张替代范式：**汇率向长期均衡缓慢收敛**（PPP 均值回复或 BEER 基本面锚）。短 horizon 收敛太慢，故无法单独碾压 carry 的“确定利差”；但错位信息仍有组合价值，且可与 carry **叠加提升**表现。即：value/EER 解释“慢预测”，carry 解释“短端利差主导”，二者可 boost。

## 2. 精确公式

```text
# 均衡汇率（两类）:
# PPP:  q̄_i  s.t.  real rate 均值回复到常数/慢变锚
# BEER: q̄_i = f( fundamentals_i )  # 有限基本面集合

# 错位:
# mis_{i,t} = s_{i,t} - q̄_{i,t}     # 或 log 实际汇率相对均衡
# 低估（低 s 相对均衡，视报价）→ 预期升值

# 纯 EER 组合:
# 权重 w_i ∝ 错位规模（多低估 / 空高估）
# 递归样本内估计均衡，避免全样本偷看（文中 quarterly recursive）

# Carry:
# 标准: 多高收益 / 空低收益货币

# Boost:
# 结合 misalignment 与 yield 信号的混合权重/过滤
# 叙事: 单独 EER 难稳定胜过 carry；混合可提升

# 与慢收敛一致:
# 短 horizon |E[Δs]| << |i*-i| 时，carry 仍主导；EER 提供倾斜
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 宇宙 | G10 发达经济体 |
| 频率 | **季度** |
| 样本 | 1975:Q1–2020:Q4 |
| 均衡 | 双边 vs USD 的 PPP 与 BEER |
| 方法 | 递归估计均衡 → 组合权重 |

## 4. 成本与可实现性

- 原文：组合风险收益特征，非点差/swap 净额
- 迁移：宏观/价格指数修订 → **必须 PIT/vintage**；否则 value 信号前视
- 季度再平衡降换手，但零售 swap 仍可吞噬利差

## 5. 识别与稳健性

- 纯错位组合可盈利 → 反驳“纯随机游走”
- 仍难系统性战胜纯 carry → 与慢收敛一致
- 混合/boost 改善 carry
- 均衡定义（PPP vs BEER）与估计不确定性是关键稳健性轴

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 名义/实际汇率长历史 | 是 | 部分 | extension |
| 价格/基本面 vintage | 是 | 弱 | fail closed for claim |
| 利率/carry 腿 | 是 | 部分 | 标准约束 |
| 递归估计代码纪律 | 是 | 需实现 | 全样本 EER = 作弊 |

## 7. 本项目映射

- registry：对齐 `currency_value` / Menkhoff RFS value；boost = **预注册**混合，非事后网格
- 持有期：季度逻辑 vs 项目月度——频率转换要记 reused-history
- 否决：用最终修订 CPI/IMF 序列回填 2010s 错位
- 与 `menkhoff_rfs_value.md`、Asness VME 对照

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| value | Menkhoff et al. RFS | 实际汇率价值 |
| carry | Lustig / Menkhoff JF | 短端利差 |
| forecast | Ca' Zorzi–Rubaszek 相关 | 慢收敛预测 |
| imbalance | Della Corte et al. | 外部失衡另一锚 |

## 9. 精读问题（给最强模型）

1. PPP 与 BEER 错位符号冲突时如何仲裁？
2. 递归窗长度改变是否翻转 boost？
3. 月度下采样/插值均衡会否引入前视？
4. 2016–2025 通胀冲击后 PPP 锚是否失效？
5. boost 权重优化是否应计入 FDR 试验计数？
