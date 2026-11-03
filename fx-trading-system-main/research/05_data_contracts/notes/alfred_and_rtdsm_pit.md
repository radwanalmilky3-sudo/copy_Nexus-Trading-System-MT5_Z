# [ALFRED + RTDSM] 宏观 Vintage 与严格 PIT

- 深度层级: L4
- 引用链角色: data_contract
- DOI/URL:
  - ALFRED: https://alfred.stlouisfed.org/ ；Help https://alfred.stlouisfed.org/help
  - RTDSM: https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists
- 开放获取: 是（官方）
- 本项目映射: day-level 宏观状态；**非** surprise
- 复制状态: RTDSM CPI/IP exact_possible（已下载校验）；ALFRED conditional

## 1. 经济机制

宏观数据会修订。用最终修订值回测“当时决策”会造成前视偏差。Vintage 数据库保存每个发布日可见的历史路径，使 as-of 特征成为可能。但 vintage **不等于** 公告微观结构：它通常没有调查中位数，也未必有秒级时钟。

## 2. 精确公式 / 合同

```text
# 决策时点 d
X_asof(d) = value from latest vintage V with available_time(V) <= d
            and observation_time < available_time

# RTDSM 项目实现（概念）
CPI_12m_log = log(CPI_t / CPI_t-12)   # 仅在同一 vintage 内
IP_6m_log   = log(IP_t / IP_t-6)

# 禁止
X_final_revised_used_as_if_known_in_2016
S = actual - consensus   # 当 consensus 缺失
```

## 3. 数据与样本

| 项 | ALFRED | RTDSM |
|---|---|---|
| 对象 | 大量 FRED 序列的历史 vintage | 专为实时宏观研究整理的矩阵 |
| 时间粒度 | 发布日/vintage 日 | vintage 日 |
| 本项目状态 | planned/逐 series 审计 | CPI/IP 已落地 |
| 覆盖 | 因 series 而异 | 长历史真 vintage |

## 4. 成本与可实现性

- 与交易成本无关；错误 PIT 会污染慢周期因子与风险状态。
- ALFRED 上传延迟（帮助文档称通常一工作日内）→ 不能当交易所时钟。

## 5. 识别与稳健性

- 必须固定：单位、季调、是否 log、是否 YoY、缺失规则。
- 基准修订/基年更换会造成 vintage 断点，需记录。

## 6. 复制清单

| 字段 | 需要？ | 本项目有无 | 缺失时 |
|---|---|---|---|
| vintage 矩阵 | 是 | RTDSM 有；ALFRED 按 series | fail closed |
| available_time | 是 | 校验列 | fail closed |
| 源 release 证据 | 严格晋级 | 部分 | strict=false |
| consensus | surprise only | 无 | 禁止方向 surprise |

## 7. 本项目映射

- RTDSM：优先宏观状态；新方向规则须先注册表冻结
- ALFRED：扩大资料地图，不自动进 FDR 分母
- 否决：用 FRED 当前值 + “假设上月末可知”

## 8. 引用链

| 角色 | 文献/文档 | 关系 |
|---|---|---|
| methodology | ALFRED help / capturing data PDF | vintage 定义 |
| related | Croushore–Stark RTDSM 传统 | 实时宏观 |
| boundary | Faust/Andersen | 需要 consensus 的层 |

## 9. 精读问题

1. RTDSM vintage 日与 BLS 实际发布时间差多少小时？
2. ALFRED `realtime_start/end` 与项目 `available_time` 如何一一映射？
3. 哪些序列永远不该标 strict（合成、模型估计值）？
