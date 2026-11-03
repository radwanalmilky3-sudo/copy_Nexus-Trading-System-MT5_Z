# research 资料库索引

更新日期：2026-07-17（**研读收口** + **PDF 冷库清理**；PDF 快照 **2026-07-17T01:24:19Z**）

### 入口（优先）

| 角色 | 文件 | 用途 |
|---|---|---|
| **Agent** | [AGENTS.md](./AGENTS.md) + [agent/routes.json](./agent/routes.json) | 意图路由、硬规则、上下文预算 |
| **Agent** | [agent/catalog.json](./agent/catalog.json) | 87 笔记元数据（机器检索） |
| **Agent** | [agent/pdf_index.jsonl](./agent/pdf_index.jsonl) + [pdf_l3_stats.md](./agent/pdf_l3_stats.md) | **341** PDF 的 L3（标题/摘要/tags） |
| 人类/Agent | [README.md](./README.md) | 知识库总览 |
| 人类 | [STUDY_CLOSURE_ZH.md](./STUDY_CLOSURE_ZH.md) | 收口结论、检查题、边界 |
| 人类 | [NOTES_INDEX_ZH.md](./NOTES_INDEX_ZH.md) | **87** 主题深度笔记总表 |
| 人类 | [notes/READING_STACK_ZH.md](./notes/READING_STACK_ZH.md) | 索引序深读栈 + 已验证 PDF |
| 人类 | [09_deep_study_path/DEEP_STUDY_PATH_ZH.md](./09_deep_study_path/DEEP_STUDY_PATH_ZH.md) | 六周周历（笔记+PDF 列已填） |
| 任意 | [notes/GAPS.md](./notes/GAPS.md) | 硬阻塞 G/C/V/R |

### 目录状态

| 目录 | 内容 | 状态 |
|---|---|---|
| [RESEARCH_MATERIAL_PLAN_ZH.md](./RESEARCH_MATERIAL_PLAN_ZH.md) | 查找方向与深度标准 | 已写 |
| [_BULK_CAMPAIGN_ZH.md](./_BULK_CAMPAIGN_ZH.md) | 7h 批量作战日志 | densify 收口 |
| [_BULK_PROGRESS_ZH.md](./_BULK_PROGRESS_ZH.md) | 进度快照 | 见最新 |
| [_BULK_STATUS_ZH.md](./_BULK_STATUS_ZH.md) | 一页状态 | densify 结束 |
| [_pdfs/](./_pdfs/) | 合法 OA PDF（已清 bulk + E/F） | **341 PDF / ~372M**；bulk 删 **7973** + E/F 删 **77**；误标 **10** → [`MISLABEL_LOG.md`](./_pdfs/MISLABEL_LOG.md)；[`INVENTORY.md`](./_pdfs/INVENTORY.md)；[`_PURGE2_EF_SUMMARY_ZH.md`](./_pdfs/_PURGE2_EF_SUMMARY_ZH.md) |
| [_html_snapshots/](./_html_snapshots/) | 官方数据落地页快照 | 24 文件 |
| [01_foundations](./01_foundations/) | FX 执行/报价/settlement/定盘 | **5** 深度笔记 + CATALOG |
| [02_factor_literature](./02_factor_literature/) | 慢周期因子 | **37** 笔记 + 引用链 + 复制清单 |
| [03_microstructure_intraday](./03_microstructure_intraday/) | 定盘/时段/流动性/公告 | **8** 笔记 + INTRADAY_SOURCE_MAP |
| [04_validation_methods](./04_validation_methods/) | FDR/DSR/PBO/SPA | **11** 笔记 + METHODS_MAP |
| [05_data_contracts](./05_data_contracts/) | PIT / vintage | GUIDE + **3** 笔记 |
| [06_broker_costs](./06_broker_costs/) | swap/forward/CIP | 清单 + **4** 笔记 |
| [07_open_source_tools](./07_open_source_tools/) | 开源对照 | TOOLS_MAP |
| [08_datasets_catalog](./08_datasets_catalog/) | 数据集目录 | DATASETS + **9** 笔记 |
| [09_deep_study_path](./09_deep_study_path/) | 六周精读路径 | DEEP_STUDY_PATH（路径已补全） |
| [10_surveys_handbooks](./10_surveys_handbooks/) | 综述/手册 | **10** 主题笔记 + CATALOG |
| [notes](./notes/) | 模板、GAPS、阅读栈 | G/C/V/R + READING_STACK |

**写入边界：** 仅 `research/` 可写。  
**研究原则：** midquote 异象 ≠ 可实现利润；`cost_incomplete` → fail closed。  
**深度原则：** L3+ 主源；合法 OA 下载；不下行情大库、不盗版。  
**PDF 卫生：** 文件名不可信；first-page / `MISLABEL_LOG` 优先；误标文件本轮保留不删。  
**下载状态：** densify 已结束；**2026-07-17** 已按「笔记引用 / 精选目录 / FX 关键词」删除无关 bulk，不再追求补齐扫号缺口。
