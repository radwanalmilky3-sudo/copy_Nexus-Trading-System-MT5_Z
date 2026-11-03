# agent/ — 机器可读索引

供其他 agent **小体积加载**，避免扫描整库 PDF（清理后约 **341** 篇；仍禁止批量灌上下文）。

| 文件 | 大小意图 | 用途 |
|---|---|---|
| [`routes.json`](./routes.json) | 最小 | intent → `read_first` / `fail_closed_if` / `do_not` |
| [`keywords.json`](./keywords.json) | 最小 | 关键词 → intent |
| [`catalog.json`](./catalog.json) | 中等 | 全量笔记元数据 + hubs + rules + routes |
| [`pdf_index.jsonl`](./pdf_index.jsonl) | 中等 | **L3** 341 PDF：title/abstract 元数据（优先流式过滤） |
| [`pdf_index.json`](./pdf_index.json) | 中等 | 同上，单 JSON |
| [`pdf_abstracts/`](./pdf_abstracts/) | 中等 | 摘要 sidecar（**338**/341；~1.3M；3 篇 thin 无有效文本） |
| [`pdf_l3_stats.md`](./pdf_l3_stats.md) | 小 | L3 统计与限制 |

## 推荐加载顺序

1. `routes.json` 或 `keywords.json` 解析意图  
2. 只 `read` `read_first` 列表中的 md  
3. 需要时再读 `catalog.json` 做笔记检索（按 `id`/`title`/`project_map` 过滤）  
4. 需要发现本地 PDF：过滤 `pdf_index.jsonl` → 读命中 `abstract_file`  
5. 原文：仅笔记点名或 L3 命中路径；核 `../_pdfs/MISLABEL_LOG.md`

## 再生

- **笔记 catalog：** 扫描 `*/notes/*.md` 前 40 行元数据 + 一级标题（按既有逻辑刷新 `catalog.json`）。  
- **PDF L3：** `uv run python research/scripts/build_pdf_l3_index.py`  
  （pypdf 抽前 2 页 → title/abstract；PDF 增删后重跑。）

## 不要

- 不要把 `catalog.json` 与大量 PDF 正文 / 全部 abstracts 同时塞进上下文  
- 不要假设文件名 = 论文标题（看 mislabel + `title_guess`）  
- 不要对已 purge 的冷库做 L3 / 全号段恢复
