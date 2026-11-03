# World Bank Commodity Markets (“Pink Sheet”)

- 深度层级: L2
- 角色: data_contract
- 快照: `research/_html_snapshots/worldbank_pink.html`
- 官方入口: https://www.worldbank.org/en/research/commodity-markets

## Allowed use

- 月度商品价格（能源、金属、农业等）**机制/状态**
- 商品货币（AUD、CAD、NOK、ZAR 等）的 **探索性** 基本面对照
- 与 REER/贸易条件叙事的低频对齐

## Forbidden inference

- **美元计价商品** 与 USD 指数存在内生性：禁止朴素“商品↑ → 商品货币↑”无控制的因果声称
- 非日度交易信号；插值到日度再回测 alpha 需极强辩护否则否决
- 非 FX 成交数据

## PIT / vintage

| 项 | 状态 |
|---|---|
| 频率 | 月度为主 |
| 修订 | 历史单元格可能修订；Pink Sheet 版本日应归档 |
| PIT | `current` unless 本地按发布月存档 |

```text
ref_month, commodity_code, price, unit, pink_sheet_issue_date
```

## 本项目映射

- 商品货币探索袖套
- 与 BIS REER 同属低频基本面层
