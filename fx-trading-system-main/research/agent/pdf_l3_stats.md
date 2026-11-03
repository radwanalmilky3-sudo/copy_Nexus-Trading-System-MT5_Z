# PDF L3 索引统计

生成：`2026-07-17T01:50:42Z`
脚本：`scripts/build_pdf_l3_index.py`
范围：当前磁盘 `_pdfs/**/*.pdf`（**341**）

## 文件

| 文件 | 用途 |
|---|---|
| `agent/pdf_index.json` | 全量记录（机器） |
| `agent/pdf_index.jsonl` | 一行一条（流式过滤） |
| `agent/pdf_abstracts/*.txt` | 标题+摘要摘录 sidecar |

## 优先级

| priority | n | 含义 |
|---|---:|---|
| hot | 55 | 知识文档有反链 |
| warm | 278 | 精选目录或 FX 关键词 |
| cold | 8 | 仅库存（保留集内仍可能偏学术） |

## 抽取状态

| status | n |
|---|---:|
| ok | 338 |
| thin_or_scan | 3 |

- 文本过薄（`<80` chars，多为扫描/坏提取）：**3**
- 至少一篇笔记/文档反链：**55**

## 分目录

| source | n |
|---|---:|
| `(root)` | 3 |
| `02_factor` | 14 |
| `_arxiv` | 26 |
| `_bis` | 24 |
| `_ecb` | 13 |
| `_fed` | 15 |
| `_imf` | 2 |
| `_micro` | 30 |
| `_nber` | 76 |
| `_official` | 95 |
| `_ssrn` | 12 |
| `_validation` | 31 |

## Agent 用法

1. 笔记 / `routes.json` 优先
2. 需要搜 PDF：读 `pdf_index.jsonl`，按 `tags_guess` / `title_guess` / `ids` / `priority` 过滤
3. 命中后读对应 `abstract_file`（短）
4. 仍不够再开 **一个** 原 PDF 首页；核 `MISLABEL_LOG`
5. **禁止**把全部 abstracts 一次塞进上下文（按查询 top-k）

## 限制

- `title_guess` / abstract 由首页启发式抽取，**非**出版元数据
- 扫描件、双栏、公式页可能 `thin_or_scan`
- 不做向量库；不做 8000 冷库恢复
