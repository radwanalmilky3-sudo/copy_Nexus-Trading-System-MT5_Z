# OFR Financial Stress Index (FSI)

- 深度层级: L2
- 角色: data_contract
- 快照: `research/_html_snapshots/ofr_fsi.html`
- 官方入口: https://www.financialresearch.gov/financial-stress-index/

## Allowed use

- **风险状态 / 压力环境** 协变量（日度综合压力）
- 子样本分层：高压 vs 低压 regime
- 与其它 FSI（ECB CISS、NFCI）对照稳健性

## Forbidden inference

- **非方向性汇率预测因子**（默认禁止把 FSI 水平/变化直接当 long/short FX 信号的“已验证 alpha”）
- 非微观流动性；非结算风险的逐对手方度量
- 成分与权重变更后禁止无说明拼接

## PIT / vintage

| 项 | 状态 |
|---|---|
| 频率 | 日度（以 OFR 发布为准） |
| 修订 | 可能随成分数据修订；需查方法论页 |
| PIT | `current_release`；无完整 ALFRED 式 vintage 时不得声称 strict as-of |

## 字段提示

```text
date, fsi_level, optional_components..., source=ofr, download_ts
```

## 本项目映射

- 风险状态袖套 / 危机窗标签
- 与已测 NFCI/STLFSI：可并列，避免多重定义 p-hacking 不报告尝试次数
