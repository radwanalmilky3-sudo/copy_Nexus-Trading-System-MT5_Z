# 价格因子 × 外部状态：Outcome-blind 预注册草案

状态：`draft_not_authorized`。日期：2026-07-19。

这不是已经执行的回测，也没有打开收益标签。它只冻结下一轮在价格层完成之后可以执行的
研究问题、样本规则和检验分母。

## 研究问题

价格因子是否只在特定的美国宏观状态下更有效？本轮只测试“状态改变价格因子预测强度”的
交互，不把外部变量直接解释成方向 alpha。

价格锚点和期限事前固定为四个假设：

| ID | 价格因子 | 外部状态 | 标签/期限 |
|---|---|---|---|
| INT-01 | `momentum_252d_skip_21d` | `us_cpi_12m_log_inflation` | 63 日方向收益 |
| INT-02 | `momentum_252d_skip_21d` | `us_ip_6m_log_growth` | 63 日方向收益 |
| INT-03 | `vol_ratio_21_126` | `us_cpi_12m_log_inflation` | 21 日绝对收益 |
| INT-04 | `vol_ratio_21_126` | `us_ip_6m_log_growth` | 21 日绝对收益 |

选择这两个价格锚点是基于机制先验：跳过短期的长期动量代表方向趋势，短/长波动比代表
风险状态。禁止阅读第一层筛选结果后替换锚点、窗口或期限。`gscpi_risk_state_pit` 不在
本轮主检验中使用，因为它首个完整 ready 时点是 2022-07-08，现有价格历史不足以同时提供
5 年训练和 1 年完整非重叠 OOS。

## 状态变换

每个训练折单独执行以下变换，OOS 不重新估计边界：

1. 价格因子按品种在训练折内做 ECDF rank，映射到 `[-1, 1]`。
2. CPI/IP 按共同日期在训练折内做 ECDF rank，映射到 `[-1, 1]`。
3. 交互项是二者乘积；主效应、品种固定效应和预先指定的事件 nuisance control 作为控制项。
4. OOS 使用训练折的 ECDF 边界并做端点裁剪，不查看 OOS 的分布、收益或显著性来重排。

交互检验为双侧检验。没有给交互系数预设正负号，不把 `expected_sign` 的 regime-only 语义
冒充方向号。

## 样本与统计合同

- EURUSD、GBPUSD；共同决策日期；21 个共同交易日再平衡；
- 5 年训练、1 年 OOS、1 年滚动步长；标签终点严格早于测试窗口边界；最大 63 日 purge；
- 63 日共同日期块 bootstrap，50,000 次；
- CPI 和 IP 必须同时 `ready`、`verified_strict_pit`，且不超过各自 staleness 上限；
- 任一品种价格因子、标签或外部状态缺失时，整日期从四个正式假设共同删除；不插值、不把
  缺失当状态、不跨上限 forward-fill；
- 每折正式交互 4 个；另生成 4 个保持时间结构和缺失掩码的 matched shadow 状态，作为
  负对照；共 8 个训练假设进入同一个 BH 家族；
- 主门 `BH q <= 0.10`；BY 只做任意依赖敏感性，不能替代主门；覆盖率低于 60% 或样本不足的
  格子仍保留并赋 `p=1`，不能从分母删除；
- 事件控制只作 nuisance/blackout control，不与价格因子交互，不解释其系数，也不进入候选。
- 事件控制的窗口是过去 24 小时，实际 source age 上限为 1 个日历日；不得把
  `maximum_staleness_days=1` 误读为允许跨日无限 carry。
- SPF 的 40 个脉冲中有 32 个落在周日 00:00 UTC。当前日度包保留这些周日决策；若执行层
  只允许周一至周五，必须在另一份预注册中明确“保留周日”或“滚到下一可用决策”，不能事后
  把事件日期移动。

## 反泄漏门

执行前必须冻结价格配置、外部五因子包、所有源/输出 SHA-256、代码版本和本预注册草案。
随后至少通过：

- 每个 source 截断到训练截止日后重建，历史前缀值和谱系完全一致；
- 向未来 vintage/event 追加或篡改值，既有训练前缀不变；
- 将 `available_time` 推迟到决策时点以后，该值变为不可用；
- 篡改 OOS 外部值或 OOS 标签，不改变训练 transform、系数、p 值或选择结果；
- 时区/DST 依照事件行的 IANA timezone，禁止只按 local date 近似；
- 不增加新的窗口、阈值、滞后、分位数门、交互或 FDR 家族。

## 可接受结论

即使四个交互都通过训练、OOS、分品种稳定性和负对照门，最高结论也只能是：

```text
external_interaction_candidate_requires_new_forward
```

不能称为已盈利、不能生成 broker 订单、不能写入 `paper_plan_approved_only.json`。由于已有
历史会被重复使用，真正确认必须依赖 alpha 冻结后的新增 forward 市场数据。

## 当前状态

```text
draft_not_authorized=true
return_labels_opened=false
factor_outcome_evaluations_added=0
trading_approval=false
gscpi_interaction_status=deferred_missing_data
```
