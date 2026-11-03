# [Avdjiev–Du–Koch–Shin] CIP 合同短注（06）

- 深度层级: L3（合同）
- 引用链角色: data_contract
- 主笔记: `../../02_factor_literature/notes/avdjiev_du_koch_shin_cip_dollar.md`
- 开放获取: `_pdfs/_bis/avdjiev_du_koch_shin_wp592_cip_dollar.pdf`
- 复制状态: fail_closed_missing_data

## 合同要点

```text
# 最小字段（与 DTV + Borio 对齐）:
spot, outright forward(tenor),
matching OIS/cash rate,
settlement_date, maturity_date,
broker_legal_entity, quote_quality

# 状态诊断（非交易信号）:
DollarBroad_t, |basis_t|, QendW/QendM
```

## 硬否决

- 零售 tom-next swap ≠ cross-currency basis  
- 误标 NBER `avdjiev_*_w24555.pdf` 不得作引用源  
- `cost_incomplete` → 无正式净 PnL  

## 与既有 06 笔记

- `du_tepper_verdelhan_cip.md`：季末监管  
- `borio_bis_basis.md`：市场结构  
- 本文：美元杠杆三角  
