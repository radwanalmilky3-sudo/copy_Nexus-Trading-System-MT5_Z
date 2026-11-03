# [Hassan & Mano 2019] Forward and Spot Exchange Rates in a Multi-Currency World

- 深度层级: L3
- 引用链角色: critique（carry 质量 / 来源分解）
- DOI/URL: https://doi.org/10.1093/qje/qjy016 ；NBER WP 20294 https://doi.org/10.3386/w20294
- 开放获取: NBER https://www.nber.org/system/files/working_papers/w20294/w20294.pdf
- 本项目映射: 区分 **静态横截面 carry** vs **动态/FPP/美元交易**；否决“Fama 回归即 carry”
- 复制状态: fail_closed_missing_data（多币 1M forward 全历史）+ 概念上 extension_only（分解诊断）
- 公式置信度: high（NBER 修订版全文）
- published premium vs implementable: 线性 carry 的 Sharpe 约为 5-bin 排序的 80–105%；仍 mid/指示成本世界
- 2016–2025 外推风险: 中高。机制是分解恒等式，对样本更稳健；但弹性估计依赖信息集假设

> 目录备注：CATALOG 旧 DOI `10.1017/S0022109019000887` 指向他刊；**正典**为 QJE 2019 / NBER w20294。slug `hassan_mano` 保留。

## 1. 经济机制

UIP 失效不是单一现象。将期望超额收益与 forward premium 的无条件协方差拆成三维：

1. **cross-currency（横截面）**：某些货币**持久**更高的 forward premium / 利率，对应持久更高期望收益（高息贬值但不够抵消利差）；
2. **between-time-and-currency（币种内相对自身均值的时变）**：动态相对利差；
3. **cross-time（时间维 / 美元）**：美元相对“世界平均”利率的时变。

**Carry 异象**主要由 (1) 驱动（约 44–100% 系统变异）；**FPP 与 dollar trade** 几乎全由 (3) 驱动；(2) 贡献通常不显著。因此“解释 carry”主要要求**持久国别风险溢价不对称**；“解释 Fama 回归”主要要求**美元期望收益时变**——二者可分离。另：带币种固定效应的 Fama 回归未纠正投资者对未来均值利率的不确定性，故**实现收益弹性 > 期望收益弹性**；纠正后常不能拒绝“投资者预期高息货币贬值”。

## 2. 精确公式

```text
# 单币 log 超额收益与 Fama 回归
rx_{i,t+1} = f_{i,t} - s_{i,t+1}
rx_{i,t+1} = α_i + β^{fpp}_i (f_{i,t} - s_{i,t}) + ε_{i,t+1}     # Eq.(1)
# CIP 下 f-s = 利差；β^{fpp}>0 即经典 FPP（高息货币升值的“回归表述”）

# 三维分解（概念）: Cov(E[rx], forward premium) =
#   cross-currency + between-time-and-currency + cross-time
# 在标准信息集下，每一项 = 某线性策略期望收益 = 对应维回归斜率的函数

# 策略映射
# carry ≈ cross-currency + between-time-and-currency
# FPP   ≈ between-time-and-currency + cross-time
# dollar trade ≈ cross-time

# 线性 carry（便于与回归系数解析对应）
# 权重 ∝  demeaned forward premium（相对截面均值）
w_{i,t} ∝ (f_{i,t}-s_{i,t}) - mean_j (f_{j,t}-s_{j,t})
# 归一化后多空美元中性；Sharpe ≈ 传统 5-bin 排序的 0.80–1.05 倍

# 信息集变体（稳健）
# - 用样本均值 / 扩展窗口均值 / 贝叶斯收缩均值 代替“投资者已知 α_i”
# - 纠正后: 常不拒绝 E[Δs | high i*] > 0（高息预期贬值）
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 资产/币种 | 宽截面发达+新兴（与标准 carry 数据集一致族；见 NBER 附录） |
| 频率 | 月度 |
| 样本起止 | 约 1980s–2010s（随修订版延长；以 NBER 表为准） |
| 价格/远期来源 | spot + forward（Datastream/Barclays–Reuters 类） |
| 排序与再平衡 | 线性权重或分位组合；信息集假设多规格 |

## 4. 成本与可实现性

- 原文：主结果为毛/标准学术超额收益分解，**非**零售成本中心
- 迁移：三维分解在缺 forward 时只能用利率伪 proxy → 混淆 CIP 偏离与 UIP 失效
- midquote ≠ net：线性权重换手可能低于极端分位，但仍需 swap 合同

## 5. 识别与稳健性

- 主结果：carry 的系统变异 **主要在横截面**；FPP≈dollar trade 的时间维
- between-time-and-currency 弹性常不显著 → “动态相对 carry”弱
- 控制：多种投资者信息集；线性 vs 分位组合
- 失败模式：把单币 Fama β>1 直接当“可交易动态 carry 信号”

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 多币月末 f,s 长面板 | 是 | 缺完整 forward | fail_closed_missing_data |
| 币种均值/先验规则 | 是（分解） | 可定义 | 必须预注册信息集 |
| 线性权重归一与美元中性 | 是 | 可实现（有数据时） | extension |
| 账户成本 | 实现层 | incomplete | 仅诊断分解，不宣称净 alpha |

## 7. 本项目映射

- registry：`carry_static_xs` vs `carry_dynamic` / `dollar_trade` **分注册**
- 持有期：月度
- 否决：用 Fama 回归 t 统计代替组合；合并三维进同一 FDR 族而不声明
- 质量含义（“carry quality”）：优先 **持久高息差横截面** 暴露；弱化“相对自身均值的短窗利差反转信号”作为主 carry

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Fama (1984) | FPP 回归 |
| foundational | Lustig et al. (2011) | 组合 carry / DOL |
| critique | 本文 | 分解并分离 carry 与 FPP |
| boundary | Ready, Roussanov & Ward (2017) | 持久国别（商品贸易）微观基础 |
| boundary | Du et al. (2018) | CIP 偏离污染 f−s 解读 |

## 9. 精读问题（给最强模型）

1. 在 G9 子集上，cross-currency 份额是否仍主导 carry？
2. 用政策利率代替 f−s 时，三维分解哪一项最先失真？
3. 递归均值 vs 全样本均值对 “期望弹性” 结论的敏感性？
4. 线性权重 carry 与 5-bin HML 在 2016–2025 净成本后排序是否一致？
5. dollar trade 与项目 `DOL` 因子是否应共享同一 FDR 族？
