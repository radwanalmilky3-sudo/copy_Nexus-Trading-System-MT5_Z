# [Lustig, Stathopoulos & Verdelhan] The Term Structure of Currency Carry Trade Risk Premia

- 深度层级: L3
- 引用链角色: foundational / critique（短端 carry vs 长端债券 carry）
- DOI/URL: NBER w19623 https://www.nber.org/papers/w19623 ；AER 2019 线
- 开放获取: `_pdfs/_nber/lustig_stathopoulos_verdelhan_term_structure_carry_risk_premia_w19623.pdf`；`_pdfs/_ssrn/lustig_stathopoulos_verdelhan_term_structure_aer2019.pdf`
- 本项目映射: **禁止**把“短端 HML_FX 溢价”外推到长债/长持有无条件成立；长端需本地期限溢价对冲叙事
- 复制状态: fail_closed_missing_data（多国零息/国债全收益曲线）
- 公式置信度: high（NBER revised 2018 WP）
- published premium vs implementable: 短端 T-bill carry 学术溢价 ≠ 零售 swap；长端债券需国债市场准入与久期成本
- 2016–2025 外推: 高；QE/负利率改变本地期限溢价，可能强化或削弱“下行期限结构”

## 1. 经济机制

固定**一个月投资期限**，用外国债券做 carry：随债券**久期上升**，美元计量的 carry 超额**递减至约零**。原因：高息货币的货币风险溢价被**本地货币期限溢价**抵消——高短端利率国往往伴随对本地长债不利的状态，使 \(rx^{(k),\$}\) 中本地债券超额与 \(rx^{FX}\) 对冲。时间序列上：利差/斜率可预测货币超额，但对 10Y 美元债超额差分预测消失。理论：无套利下，长端跨国债券溢价差由 SDF **永久成分**波动差决定；要匹配“长端 carry≈0”，各国永久成分波动须大致相等。标准 LRV 仿射模型给出**平坦**期限结构，与事实冲突。偏好无关条件是对现有 UIP 模型的硬约束。

## 2. 精确公式

```text
# 零息: log P_t^{(k)} = -k y_t^{(k)}
# 一期持有收益: R_{t+1}^{(k)} = P_{t+1}^{(k-1)} / P_t^{(k)}
# 本地对数超额: rx_{t+1}^{(k)} = log(R_{t+1}^{(k)} / R_t^f)

# S = 外币 per USD；↑S = 美元升值
# 货币对数超额（借本币、投外币短端）:
rx^{FX}_{t+1} = r^{f*}_t - r^f_t - Δs_{t+1}

# 外国债券美元超额:
rx^{(k),$}_{t+1} = rx^{(k),*}_{t+1} + rx^{FX}_{t+1}
# E[rx^{(k),$}] = 本地期限溢价 + 货币风险溢价

# 策略 1（利率水平 carry，固定 1M 地平线）:
# 多高短端利率国债券 / 空低利率国债券（含本国对照）
# 策略 2（斜率）:
# 多平坦曲线国 / 空陡峭曲线国
# 关键结果: k↑ → 策略平均超额 ↓ → 长端 ≈ 0

# 偏好无关（完整市场）:
# 长端跨国美元债券溢价差 ∝ σ(永久 SDF 成分) 之差
# 短端 carry 溢价 ∝ σ(SDF) 之差（Bekaert/Bansal/BFT）

# 预测回归（示意）:
rx^{(10),$}_{t+1} - rx^{(10)}_{t+1}  ~  (r^{f*}-r^f) 或 斜率差
# 货币腿可预测；本地债腿反向 → 净美元债腿弱/不显著
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | G10：AU,CA,DE,JP,NZ,NO,SE,CH,UK + US |
| 频率 | 月度 |
| 样本起止 | 全收益指数约 1951–2015；零息主 1975–2015（各国起点不同） |
| 价格来源 | Global Financial Data 10Y 全收益 + T-bill；零息曲线；CPI；S&P 主权评级 |
| 排序与再平衡 | 按短端利差或斜率差排序/信号；1M 持有 |

## 4. 成本与可实现性

- 原文：债券与货币超额；非零售 FX only
- 迁移破坏点：
  1. 项目主战场是 FX spot/swap，**无**多国国债融资曲线 → 长端策略 fail closed
  2. 短端结果强化 LRV carry，但仍需可交易 forward/swap
  3. 久期对冲、国债 bid-ask、结算与 FX 点差叠加
- midquote 短端 carry ≠ 长端可实现净收益

## 5. 识别与稳健性

- 横截面与时间序列一致：期限结构向下
- 分解：货币溢价被本地期限溢价抵消
- 模型：Vasicek/CIR、习惯、LRR、灾难、LRV 标准校准均难匹配；需强制永久成分波动跨国相等
- 与 long-run UIP：永久冲击相关但条件更弱（长端 carry 零不必处处 long-run UIP）
- 分割市场模型（Gabaix–Maggiori 等）不受该偏好无关条件约束——开放问题

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| G10 短端利率/1M forward | 短端对照 | 部分 | fail closed 净 |
| 多国零息/国债全收益曲线 | 长端主结果 | **无** | **fail closed** |
| 1M 持有地平线 | 是 | 可 | — |
| 本地 vs 美元收益分解 | 是 | 无债 | fail closed |
| 通胀/评级控制 | 稳健性 | 部分 | extension |

## 7. 本项目映射

- registry：注释 `slow_carry`——**仅短端**；禁止“持有期拉长自动保留 carry 溢价”
- 与 ECB curvy trade / 斜率信号：斜率预测货币腿，但本文显示美元债净腿被对冲
- 否决：用 10Y 利差当零售 FX 信号却声称 LSV 复制
- 理论否决：无永久成分约束的 SDF 故事解释短端却忽略长端

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Lustig–Roussanov–Verdelhan RFS 2011 | 短端 HML_FX |
| theory | Alvarez–Jermann；Backus–Foresi–Telmer | SDF 分解/条件 |
| related emp | Ang–Chen；Berge–Jordà–Taylor | 斜率预测汇率 |
| boundary | Gabaix–Maggiori | 分割市场例外 |

## 9. 精读问题（给最强模型）

1. 零售只有 tom-next swap 时，如何对应文中“短端”而非“伪长端”？
2. 2010 后 CIP 偏离如何进入 \(rx^{FX}\) 与本地债分解？
3. 曲线曲率（ECB curvy）与本文斜率策略在美元债净收益上是否也被抵消？
4. 永久成分波动相等的校准是否与 disaster 模型兼容？
5. G9 子集缺失若干 G10 债市时，短端结果是否仍稳健？
