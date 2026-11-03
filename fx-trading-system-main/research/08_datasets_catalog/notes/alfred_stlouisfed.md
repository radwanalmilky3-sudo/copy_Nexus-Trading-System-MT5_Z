# ALFRED (Archival FRED) — St. Louis Fed

- 深度层级: L2
- 角色: data_contract
- 快照: `research/_html_snapshots/alfred.html`
- 官方入口: https://alfred.stlouisfed.org/

## Allowed use

- FRED 系列的 **历史发布档（vintages）**
- 美国宏观/金融序列的 realtime 路径重建
- 与 RTDSM 交叉验证部分宏观量

## Forbidden inference

- **非** 完整公告时钟（无 consensus、无精确发布时间表除非另源）
- 非全球覆盖保证；系列级 vintage 深度不一
- API/下载条款与 FRED 使用政策必须遵守；禁止无视条款 bulk 滥用

## PIT / vintage

| 项 | 状态 |
|---|---|
| PIT | **vintage query 支持** → 可 `strict_as_published` |
| 要求 | 每个观测保留 `realtime_start/realtime_end` 或等价 vintage 键 |
| 默认错误 | 只拉 FRED current 当 ALFRED |

```text
series_id, observation_date, realtime_start, realtime_end, value
```

## 本项目映射

- 美宏观状态候选；与 Philly RTDSM 并列
- 因子注册：任何“实时宏观”实验必须指向 ALFRED/RTDSM 而非 final FRED
