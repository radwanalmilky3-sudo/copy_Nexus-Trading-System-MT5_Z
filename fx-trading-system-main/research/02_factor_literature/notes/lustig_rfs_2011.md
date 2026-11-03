# [Lustig, Roussanov & Verdelhan 2011] Common Risk Factors in Currency Markets

- 深度层级: L3
- 引用链角色: foundational
- DOI/URL: https://doi.org/10.1093/rfs/hhr068 ；NBER WP 14082: https://www.nber.org/papers/w14082
- 开放获取: NBER 工作论文 PDF https://www.nber.org/system/files/working_papers/w14082/w14082.pdf
- 本项目映射: slow carry / HML_FX 合同；forward discount 排序
- 复制状态: fail_closed_missing_data（缺当时可交易 1M forward points / 账户 swap）
- 公式置信度: high（NBER WP 全文核对）
- published premium vs implementable: 原文净 bid-ask 后 HML 仍约 4.8% p.a.；**不等于**零售账户 + financing 后的净收益
- 2016–2025 外推风险: 高。样本主至 2008/2009；后危机 CIP 常态偏离、Basel/Volcker、零售点差结构均改变

## 1. 经济机制

货币超额收益的横截面不是“高息货币随机赚钱”，而是**全球共同风险因子暴露**的补偿。将货币按 forward discount（≈利差）排序后，高息货币在全球风险价格升高时对共同 SDF 冲击加载更多；低息货币提供保险。DOL/RX 捕捉美元/本国特异成分，HML_FX 捕捉共同风险成分。机制是风险定价，不是无条件 UIP 失效口号。

## 2. 精确公式

约定：\(s_t\)、\(f_t\) 为对数即期/1M 远期，**外币单位 / 1 USD**；\(s\) 上升=美元升值/外币贬值。

```text
# 1M 对数超额收益（买外币远期、一月后现货卖出）
rx_{t+1} = f_t - s_{t+1}
         = (f_t - s_t) - Δs_{t+1}

# CIP 成立时
f_t - s_t ≈ i*_t - i_t
rx_{t+1} ≈ i*_t - i_t - Δs_{t+1}

# 净 bid/ask（做多外币 / 做空外币）
rx^L_{t+1} = f^b_t - s^a_{t+1}
rx^S_{t+1} = -f^a_t + s^b_{t+1}

# 组合：月末按 forward discount (f-s) 分 6 组（P1 最低息 … P6 最高息）
# 组内等权平均 log excess return
# 假设：P1 全部做空外币，P2–P6 做多外币（净成本计算用）

DOL_t  = (1/6) * sum_{j=1..6} rx^j_t     # 文中亦称 RX
HML_FX_t = rx^{P6}_t - rx^{P1}_t

# 多期 k 月合约（稳健性）
rx^k_{t+k} = -Δs_{t→t+k} + f^k_t - s_t
```

再平衡：每月末。排序信号：当期可观察的 1M forward discount。无 skip 月。

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 主样本 37 币种；稳健 15 发达币种 |
| 频率 | 月末（日数据构月末） |
| 样本起止 | 1983-11 至 2008-03（NBER WP）；发表版延至约 2009 |
| 价格/远期来源 | Barclays & Reuters via Datastream；spot + 1M forward |
| 排序与再平衡 | 月末按 1M forward discount 分六组，等权，月度再平衡 |
| 组合切换 | 平均约 29%/月货币换组；角组合更持久 |

## 4. 成本与可实现性

- 原文扣除：spot+forward **bid-ask**；保守（Reuters 指示性价差约 2× 银行间）
- 净 HML（P6−P1）约 **4.83% p.a.**，Sharpe ≈ **0.54**（全样本含新兴）
- 迁移到零售 bid/ask + 账户 swap 的破坏点：
  1. 必须用**可成交 forward points 或账户 rollover**，不能用政策利率伪造 \(F\)
  2. 月度全换仓 + 零售点差可能显著高于 Datastream 指示价
  3. 融资/隔夜 swap 与 1M forward 隐含利差在 CIP 偏离时不可互换（见 Du–Tepper–Verdelhan）
- midquote premium ≠ implementable net：**已扣 spread 的学术 premium 仍非零售净**

## 5. 识别与稳健性

- 主结果：六组合平均超额收益随 forward discount 单调上升；HML_FX 解释约 70% 横截面平均收益差异
- 发达子样本类似；其他国家投资者视角稳健
- 控制：与标准股权/债券因子弱相关；HML_FX 有正消费增长 beta
- 已知失败/衰减：后危机 carry 回撤与 crash 文献相关；本项目 v4 未晋级方向因子
- 关键假设：主样本期 CIP 近似成立；2010 后该假设结构性弱化

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 月末 spot mid/bid/ask | 是 | Dukascopy 可构造 | 无完整 bid/ask 则净收益 fail closed |
| 月末 1M forward bid/ask 或账户 swap | 是 | 缺目标账户历史 swap / forward points | **fail_closed_missing_data** |
| 报价惯例（FCU per USD）与结算日 | 是 | 需契约 | 惯例错则符号反 |
| 币种宇宙与可得性日历 | 是 | G9 子集 | 只能 extension（G9 carry） |
| 月度再平衡时点（EOM） | 是 | 可定义 | 需冻结 bar 规则 |
| 融资/杠杆上限 | 实现层 | incomplete | 不可宣称零售可实现 |

## 7. 本项目映射

- registry / 实验名：`slow_carry` / HML_FX 类；不可用政策利率 carry 冒充
- 持有期：原文 1M；项目 21/42/63 日为扩展
- 否决条件：无真实 forward/swap；净成本后跨折不同号；reused-history 无新前向
- reused-history 备注：2016–2025 已被多轮搜索查看 → 任何 carry 结果按 reused 处理

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Lustig & Verdelhan (2007) 组合方法 | 按利率排序的前身 |
| foundational | Fama (1984) UIP / forward premium | 现象起源 |
| critique / crash | Brunnermeier, Nagel & Pedersen (2008) | carry 负偏与融资 |
| boundary | Du, Tepper & Verdelhan (2018) | CIP 偏离 → forward≠现金利差 |
| replication | Menkhoff et al. (carry/vol risk, JF 2012) | 波动风险定价视角 |

## 9. 精读问题（给最强模型）

1. 在 CIP 系统性偏离下，用 \(i^*-i\) 代替 \(f-s\) 会如何偏置 HML_FX 的符号与排序？
2. DOL 与 HML_FX 正交化后，G9 子集的横截面 R² 是否仍支持“单一斜率因子”？
3. 将月度再平衡改为 21 日固定 sleeve，换手与净 spread 的弹性有多大？
4. 2008–2009、2015 CHF、2020 COVID 三段 crash 中，事前 VIX/ funding 门控能否在**不偷看阈值**下降低左尾？
5. 若只有 retail swap 而没有 1M outright forward，何种合同可称为“broker-carry”而非 LRV 复制？
