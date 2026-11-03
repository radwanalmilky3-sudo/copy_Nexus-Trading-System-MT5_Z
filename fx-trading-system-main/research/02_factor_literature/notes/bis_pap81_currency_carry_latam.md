# [BIS Papers No 81] Currency Carry Trades in Latin America

- 深度层级: L3
- 引用链角色: boundary / data_contract（政策视角下 EM carry 与金融稳定）
- DOI/URL: https://www.bis.org/publ/bppdf/bispap81.htm
- 开放获取: `_pdfs/_bis/bis_pap81_currency_carry_latam.pdf`
- PDF 卫生: `_pdfs/_bis/work331.pdf` **不是** carry 文（实为 John Vickers *Central banks and competition authorities*，BIS WP 331）；勿引用为 carry
- 本项目映射: EM/拉美 carry 的政策与市场微观约束；G9 主宇宙外的 **否决/情景** 参考
- 复制状态: extension_only（政策研究报告；非标准学术因子表）
- 公式置信度: medium（研究组报告，多章节描述性）
- published premium vs implementable: 强调跨境资金流与本地市场条件，非零售可复制 alpha
- 2016–2025 外推: 中高作为风险情景模板（利差吸引、突然停止）

## 1. 经济机制

拉美（及新兴）货币 carry：全球投资者借入低息核心货币、投资高息本币资产/货币，推高本地资产与汇率，积累**拥挤与融资脆弱性**。当全球风险偏好逆转、美元走强或本地冲击出现时，仓位平仓导致汇率超调、本地利率飙升与金融稳定压力。与发达 G10 carry 的共同内核是 UIP 偏离 + crash/funding；差异在于：主权与通胀风险、资本流动管理、本地债市深度、美元化与对冲渠道。报告从操作/政策视角汇总区域内 carry 的规模、渠道与政策应对，而非提出新 SDF 因子。

## 2. 精确公式

```text
# 概念层（标准 carry，本币投资）:
# 借 funding currency @ i_f，投 local @ i_l
# 超额 ≈ (i_l - i_f) - Δs_{local per funding}
# 风险: 全球 risk-on/off、美元周期、本地政策突变 → 平仓

# 政策相关状态变量（报告强调，非统一回归式）:
# - 跨境银行/组合资金流
# - 本地利率与期限溢价
# - 外汇干预与资本流动管理工具
# - 企业/银行外币负债（隐性 carry）

# 与学术 HML_FX: 同属利差排序逻辑，但 EM 子集左尾与政策内生性更强
```

## 3. 数据与样本

| 项 | 原文 |
|---|---|
| 区域 | 拉丁美洲主要经济体（CGDO 美洲研究组） |
| 类型 | BIS Papers 政策研究汇编 |
| 频率/样本 | 多章节，危机前后对照（2000s–2010s 叙述） |
| 数据 | 官方利率、跨境资金、FX 与本地债市场描述性统计 |

## 4. 成本与可实现性

- 非零售回测；强调机构与跨境渠道
- 迁移：项目 G9 宇宙**不应**直接套用拉美利差信号；EM 扩展需独立成本、资本管制与结算合同
- 隐性企业 carry（贸易信贷等）见 BIS WP 773 Hardy–Saffie 线

## 5. 识别与稳健性

- 政策案例与区域比较为主；非单一 t 统计主表
- 稳健含义：carry 的宏观审慎外部性——即使私人 Sharpe 可观，社会风险外部化
- 与发达市场 crash 文献一致，但政策工具集不同

## 6. 复制清单（字段级）

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| 拉美全套可交易 FX+利率 | EM 扩展 | **无**（主 G9） | 不进主 registry |
| 跨境资金流 | 机制 | BIS 低频 | 非 strict PIT |
| G9 利差 | 对照 | 部分 | — |

## 7. 本项目映射

- registry：不设默认 `latam_carry`；作 EM 否决与情景库
- 否决：用拉美历史高利差论证 G9 carry 可扩展杠杆
- 关联：`bis_wp773_carry_to_trade_credit`、BNP funding spiral

## 8. 引用链（2–5 篇）

| 角色 | 文献 | 关系 |
|---|---|---|
| foundational | Brunnermeier–Nagel–Pedersen | crash/funding |
| related BIS | Hardy–Saffie WP 773 | 企业部门 carry 中介 |
| related | Bruno–Shin | 跨境银行与风险承担 |
| mislabel | BIS WP 331 Vickers | 文件名陷阱 |

## 9. 精读问题（给最强模型）

1. 拉美“突然停止”模板哪些指标可映射到 G9 2016–2025 压力周？
2. 资本流动管理如何改变可测的 UIP 回归系数？
3. 企业外币负债渠道是否使 CFTC 期货持仓低估真实拥挤？
4. 与全球美元周期（Verdelhan dollar）交互如何检验？
5. 政策报告的描述性结论如何避免被误写成因子 alpha？
