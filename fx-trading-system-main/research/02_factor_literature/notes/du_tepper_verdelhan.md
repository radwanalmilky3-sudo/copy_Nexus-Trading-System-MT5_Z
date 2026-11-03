# [Du, Tepper & Verdelhan 2018] Deviations from Covered Interest Rate Parity

- 深度层级: L4
- 引用链角色: boundary / data_contract
- DOI/URL: https://doi.org/10.1111/jofi.12620 ；NBER WP 23170
- 开放获取: https://www.nber.org/system/files/working_papers/w23170/w23170.pdf
- 本项目映射: CIP/basis **合同约束**，不是方向 alpha
- 复制状态: fail_closed_missing_data（同步 spot、forward、OIS/repo）
- 公式置信度: high（NBER WP）
- published premium vs implementable: 展示的是受约束中介下的套利边界，不是散户可扩规模 alpha
- 2016–2025 外推: **直接相关**——后危机样本正是制度现状

## 1. 经济机制

教科书 CIP：用远期对冲后，美元利率应等于外币利率的合成美元利率。后危机出现**持续、系统性**的 cross-currency basis，且在无信用风险的 repo/KfW 等工具上仍存在。解释中心是**金融中介资产负债表成本**（杠杆率、RWA、窗口粉饰）与美元对冲需求，而非简单 Libor 信用差异。季度末 basis 扩大是监管报告日的标志性事实。

## 2. 精确公式

```text
# CIP（n 年）
(1 + y$_{t,t+n})^n = (1 + y_{t,t+n})^n * S_t / F_{t,t+n}

# 对数远期溢价
ρ_{t,t+n} ≡ (1/n)(f_{t,t+n} - s_t) = y_{t,t+n} - y$_{t,t+n}   # 无偏离时

# 交叉货币基差 x：CIP 偏离（文中定义）
(1 + y$)^n = (1 + y + x)^n * S / F
# x ≈ 直接美元利率 − 合成美元利率

# 季度末合同（项目地图 / 正式定义需 settlement）
# QendW=1: T+2 结算落在本季最后一周，且 1W 远期到期落在下季
# QendM=1: 1M 远期的 settlement 与 maturity 跨季
# 因变量常为 |basis| 或 basis 水平，不是 spot 方向
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 工具 | Libor、repo、公司/超主权债券、XCCY 互换 |
| 币种 | G10 等 |
| 频率 | 日 |
| 样本 | 2000s–2016（强调危机后） |
| 关键 | 同步利率曲线 + spot + forward |

## 4. 成本与可实现性

- “套利”受中介资本与监管约束，**规模有限**
- 零售账户通常**无法**以银行同业条件交易 basis
- 对项目的含义：不能用政策利率或单一 OIS 公式生成的 \(\hat F\) 冒充可交易 forward

## 5. 识别与稳健性

- 危机后 basis 持续；多市场 basis 共动
- 季度末/年末尖峰
- 与其他固定收益流动性策略相关
- 信用风险解释不足以消除 repo/KfW basis

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| spot bid/ask + 时间戳 | 是 | 部分 | fail closed |
| 匹配 tenor 的 forward bid/ask | 是 | **缺** | fail closed |
| 同期限 OIS/repo/当时基准 | 是 | 缺完整 | fail closed |
| spot/forward 结算日 | 是 | 需日历 | 无则 Qend 不可定义 |
| 交易对手/账户 | 合同 | 零售 | 不可称银行套利复制 |

## 7. 本项目映射

- **不**增加方向候选或 FDR 方向分母
- 所有 carry/forward excess 实验的硬前置合同
- 合成 \(\hat F\) 仅允许压力测试并明确标注
- BIS 低频统计 ≠ 逐日 basis 面板

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| crisis CIP | Baba, Packer 等 | 危机期偏离 |
| BIS | Borio et al. 2016/2022 | 美元融资与 FX swap |
| intermediary | He–Krishnamurthy；Du 后续 | 理论 |
| project | Lustig carry | 前危机 CIP≈成立假设被削弱 |

## 9. 精读问题

1. 零售 swap 曲线与 Libor/OIS basis 的映射误差有多大？
2. 忽略结算日的“月末 dummy”会如何误测 Qend？
3. basis 扩大时，HML_FX 的 forward discount 排序是否机械变化？
4. 能否用公开代理监测 basis 状态而不交易 basis？
5. 2016–2025 哪些监管修订改变了季度末尖峰幅度？
