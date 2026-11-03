# [Dreher, Gräb & Kostka 2018] From Carry Trades to Curvy Trades（ECB WP 2149）

- 深度层级: L3
- 引用链角色: extension / critique（用收益率曲线曲率替代短端利差）
- DOI/URL: ECB WP 2149 https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2149.en.pdf
- 开放获取: `_pdfs/_ecb/ecb_wp2149_carry_to_curvy_trades.pdf`（first-page OK）
- 本项目映射: 曲线因子 carry 变体；需完整国债曲线，非仅政策利率
- 复制状态: fail_closed_missing_data（多国 Nelson–Siegel 全曲线）/ extension_only（短端近似）
- 公式置信度: high（ECB WP）
- published premium vs implementable: 更高 SR、更弱负偏仍是学术 mid/利率口径
- 2016–2025 外推: 曲线形态与 QE/QT 改变曲率信息含量

## 1. 经济机制

经典 carry 只用**短端**利差/远期贴水排序，忽略收益率曲线其余信息。Nelson–Siegel 三因子中，**相对曲率（curvature）**对未来汇率（超出远期隐含）有预测力：相对美国曲率更低的货币更易额外贬值。据此做 **curvy trade**——多相对高曲率货币、空相对低曲率货币——可比传统 carry **更高 Sharpe、更小负偏**，且较少依赖 JPY/CHF 等典型融资币，从而**更不易 crash**。标准 FX 波动等定价因子难以线性解释 curvy 收益，与“曲率≈中期路径上更高短端利率→汇率支撑”的解释一致。

## 2. 精确公式

```text
# Nelson–Siegel 即期曲线（标准）:
# y(τ) = β0 + β1 (1-e^{-λτ})/(λτ) + β2 [ (1-e^{-λτ})/(λτ) - e^{-λτ} ]
# Level=β0, Slope=β1, Curvature=β2 （λ 固定或估计）

# 相对曲率（对 USD）:
# C̃_{i,t} = Curvature_{i,t} - Curvature_{USD,t}

# 预测（文中叙事）:
# 更低的国内相对曲率 → 相对美元额外贬值（1–6 个月）
# 超出远期隐含部分 = “unexpected” currency move

# Curvy 组合:
# 按 C̃_{i,t} 排序 G10
# long 高相对曲率 / short 低相对曲率
# 对照: 按短期利差/远期贴水的传统 carry

# 收益分解（叙事）:
# 总收益 = 利率腿 + 即期变动腿
# curvy: 即期腿贡献相对更大，利率腿相对更小；偏度改善
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 宇宙 | G10 货币 |
| 曲线 | 各国收益率曲线 → NS 因子 |
| 频率 | 月度组合；预测窗 1–6 个月 |
| 对照 | 传统 short-rate carry |
| 定价 | 线性资产定价；FX vol 等 |

## 4. 成本与可实现性

- 原文：组合收益分布与定价，非零售 swap/点差
- 迁移：曲率估计需可靠国债曲线与再平衡；零售账户无“曲率现货”工具
- 换手可能异于短端 carry；成本未证明净 SR 仍优

## 5. 识别与稳健性

- 相对曲率预测力 → 组合经济价值
- 币种构成偏离经典 carry funding 集 → 负偏改善
- FX vol 等标准 carry 定价因子对 curvy **失效**（线性框架）
- 与“曲率含中期政策路径”解释一致

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 多国国债曲线多期限 | 是 | 无完整 | fail closed |
| NS 估计（λ 设定） | 是 | 可代码 | 超参计入试验 |
| 1M FX 远期/即期 | 是 | 部分 | 标准约束 |
| 短端利率 only | 对照 | 或有 | 不能替代曲率 |

## 7. 本项目映射

- registry：新试验 `curve_curvature_fx` 须预注册 NS 设定；非 `slow_carry` 别名
- 否决：用单一 2s10s 斜率冒充 curvature 却占用 curvy 标签
- 与 value/EER（ECB 2731）、短端 carry 对照

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational carry | Lustig et al. / Menkhoff et al. | 短端 carry |
| crash | Brunnermeier–Nagel–Pedersen | 负偏基准 |
| curve | Nelson–Siegel 文献 | 因子定义 |
| related ECB | Falconio WP1968 | 货币条件 × carry |

## 9. 精读问题（给最强模型）

1. λ 固定 vs 时变对排序稳定性影响？
2. 曲率与期限利差/水平共线时，正交化后信号是否存活？
3. 2013–2015 与 2022–2023 曲线扭曲期 curvy 是否翻转？
4. 相对德债/美债锚选择是否改变欧元区结果？
5. 交易成本后 curvy 对 carry 的 SR 优势是否消失？
