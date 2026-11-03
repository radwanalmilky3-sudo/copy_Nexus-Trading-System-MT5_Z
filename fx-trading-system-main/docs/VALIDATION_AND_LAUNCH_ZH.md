# 验证和上线门槛

## 已自动化的门槛

- UTC、OHLC 合法性、时间排序和去重。
- Bid/ask 双边合法性、不可交叉报价、可成交侧 barrier 与历史 swap as-of join。
- Point-in-time `available_time`、修订数据防回填、PIT 数据独立 SHA-256。
- 收盘信号只在后续 bar 执行。
- 目标/止损与 168 小时持仓硬上限。
- 单笔/组合风险、共享币种敞口、杠杆和相关簇。
- 成交成本、非 USD quote 动态换算、同 bar 止损优先。
- 每次运行保存配置、数据范围、SHA-256 和 Git revision。
- 全部 DSL 假设数量与谱系、paired block bootstrap、FDR、1x/1.5x/2x 成本压力产物。
- 冻结模型 contract hash、严格 forward 时间边界，以及前向命令无拟合/无选因子保证。

## 从研究到 practice 前

1. 使用至少两个市场状态周期的目标 broker 历史 bid/ask；4h 策略建议覆盖 8–10 年。
2. 按时间 walk-forward，不允许随机拆分时序数据；只在训练窗做选择。
3. spread、slippage 和 swap 做基准、保守、危机三组压力测试。
4. 检查各货币对、年份和策略贡献，拒绝依赖单一品种/单一季度的结果。
5. 检查参数邻域稳定性；不是只看最优参数点。
6. 用 practice 连续运行至少 3–6 个月，核对订单幂等、断线恢复、broker 拒单和实际滑点。

自动 verdict 不会直接批准交易：开发集通过只能进入新 holdout，holdout 通过只能进入
`research_candidate_requires_paper`。至少 3–6 个月前向期仍需要外部时间证据。

## 真实资金上线前（当前系统不提供真实下单）

- 新增独立代码审计、密钥托管、审计日志、时钟/行情新鲜度检测、订单 reconciliation、
  broker 端总损失保护和人工 kill switch。
- 明确法律、税务和 broker 条款。
- 从极小风险开始，真实资金的初始 `risk_per_trade` 不应直接照搬研究默认值。
