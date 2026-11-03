# [Koijen, Moskowitz, Pedersen & Vrugt 2018] Carry

- 深度层级: L3
- 引用链角色: foundational（跨资产 carry 统一；含 FX 专节）
- DOI/URL: JFE 2018；NBER w19325 https://www.nber.org/papers/w19325
- 开放获取: `_pdfs/_nber/koijen_moskowitz_pedersen_vrugt_carry_w19325.pdf`
- 本项目映射: FX carry 信号定义的**跨资产对照**；全局 carry 拥挤/周期暴露；**非**零售净收益证明
- 复制状态: fail_closed_missing_data（1M forward）/ extension_only（利率近似）
- 公式置信度: high（NBER WP）
- published premium vs implementable: 多资产 long-short 高 SR 为学术/期货保证金口径；≠ 零售 FX swap
- 2016–2025 外推: 跨资产 carry 相关性在压力期上升；FX 子块仍受 CIP/点差约束

## 1. 经济机制

任意资产收益可分解为 **carry**（假设价格不变时可事前观测的收益部分）+ 预期价格升值。Carry 是**模型无关**的可测预期收益分量。经验上 carry 在货币、股票、债券、商品、信用、期权等截面与时序均有预测力；“高 carry 多、低 carry 空”的跨资产策略有强收益，但暴露于全球周期与流动性。对 FX：carry 即利差（远期隐含），经典 UIP 假设各币预期收益相等被拒绝；崩溃/流动性故事在 FX 更强，但**并非所有资产类**的 carry 都有同样 crash 形态——故不能把 FX crash 叙事无条件外推到“万物 carry”。

## 2. 精确公式

```text
# 一般期货超额收益（保证金资本 X_t）:
r_{t+1} = (F_{t+1} - F_t) / X_t

# Carry = 假设现货价不变时的超额收益:
# 到期 F_{t+1}=S_{t+1} 且 S_{t+1}=S_t ⇒ F_{t+1}=S_t
C_t = (S_t - F_t) / X_t

# 货币（1M forward；S 为本币/外币报价族与文中一致）:
# 无套利 F_t = S_t (1+r_f)/(1+r_f*)
# 取 X_t = F_t 的常见归一:
C_t = (S_t - F_t)/F_t = (r_f* - r_f) / (1 + r_f)
# ≈ 外币−本币利差（小利率时）

# FX 策略:
# 截面: 高 C 货币多头 / 低 C 货币空头（等权或波动调整变体）
# 时序: 单币 carry 符号或水平预测自身超额收益

# 收益分解:
# realized return = carry + price appreciation
# 可进一步拆 static（长期平均 carry 排序）vs dynamic（时变）

# 风险暴露（文中）:
# 全局 carry 组合对全球业务周期/流动性因子加载
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| FX 资产 | 主要货币 1M forwards（作者致谢 Hassan–Mano–Verdelhan 数据协助） |
| 其他类 | 全球股指、国债、商品期货、信用、期权等 |
| 频率 | 月度为主 |
| 样本 | 跨资产类可得性不一，约 1980s/1990s–2010s |
| 再平衡 | 月度按 carry 排序 |

## 4. 成本与可实现性

- 原文：期货/ implic it 融资口径；FX 有学术成本讨论但非零售 swap
- 迁移：货币腿必须用账户 financing；跨资产“全球 carry”零售不可直接搬
- mid ≠ net：高 SR 在扣除真实点差+swap+保证金后未知

## 5. 识别与稳健性

- 截面与时序预测在多类资产成立
- 与传统预测变量（曲线斜率、便利收益、股利率）相关但不相同，常更强
- 压力期跨类相关上升 → 分散化有限
- FX 特有 crash 与其他类不对称

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 1M FX forward | FX 块 | 缺 | fail closed |
| 利率代理 | 扩展 | 政策利率可能 | extension only + 标记 |
| 其他资产类 | 跨资产 | 超出项目范围 | 不做 |
| 流动性/周期因子 | 暴露分析 | 部分 | 诊断 |

## 7. 本项目映射

- registry：`slow_carry` 定义与 \(C_t≈i^*-i\) 对齐；跨资产结论仅作**外部效度**
- 持有期：1M
- 否决：把商品/债券 carry 信号未经映射塞进 FX 宇宙
- reused-history：波动调整权重变体算新试验

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| FX foundational | Lustig–Roussanov–Verdelhan | 货币风险因子 |
| crash | Brunnermeier–Nagel–Pedersen | FX 左尾 |
| TSMOM | Moskowitz–Ooi–Pedersen | 同作者动量线 |
| survey | Burnside ARFE | carry/mom 解释谱 |

## 9. 精读问题（给最强模型）

1. \(C_t=(S-F)/F\) 与 \(\log(F/S)\) 排序在 G10 是否一致？
2. dynamic vs static 分解在 2016–2025 FX 谁主导？
3. 全球 carry 拥挤指标能否作门控而不数据挖掘？
4. CIP 偏离时“利率 carry”与“forward carry”分歧如何处理？
5. 波动目标化是否把 Moreira–Muir 叠进 carry 并膨胀试验数？
