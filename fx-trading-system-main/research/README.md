# research — FX 量化研究知识库

面向：**人类精读** + **其他 Agent 检索**。  
默认深度：L3–L5 笔记（机制/公式/数据合同/复制边界）；**不为“新人”降维**。

## 30 秒入口

| 你是… | 先打开 |
|---|---|
| **另一个 Agent** | [`AGENTS.md`](./AGENTS.md) → [`agent/routes.json`](./agent/routes.json) |
| **人类要学** | [`STUDY_CLOSURE_ZH.md`](./STUDY_CLOSURE_ZH.md) → [`09_deep_study_path/DEEP_STUDY_PATH_ZH.md`](./09_deep_study_path/DEEP_STUDY_PATH_ZH.md) |
| **查一篇笔记** | [`NOTES_INDEX_ZH.md`](./NOTES_INDEX_ZH.md) |
| **查能否复制/交易** | [`notes/GAPS.md`](./notes/GAPS.md) |
| **查 PDF** | [`_pdfs/INVENTORY.md`](./_pdfs/INVENTORY.md) + [`_pdfs/MISLABEL_LOG.md`](./_pdfs/MISLABEL_LOG.md) |

## 库里有什么

| 类型 | 规模（约） | 说明 |
|---|---:|---|
| 主题深度笔记 | **87** | 主知识；路径见 NOTES_INDEX |
| OA PDF | **341** / ~372M | 辅证（已清 bulk + E/F）；**L3** 见 `agent/pdf_index.jsonl` |
| 意图路由 | 12 | `agent/routes.json` |
| 硬缺口 | G/C/V/R | `notes/GAPS.md` |

## 目录地图

```text
research/
  AGENTS.md              # Agent 总协议（外层 agent 先读这一份）
  README.md              # 本文件
  INDEX.md               # 人类目录状态
  NOTES_INDEX_ZH.md      # 笔记总表
  STUDY_CLOSURE_ZH.md    # 研读收口
  agent/
    routes.json          # intent → read_first
    keywords.json        # 关键词 → intent
    catalog.json         # 87 笔记元数据 + rules
    pdf_index.jsonl      # 341 PDF 索引（title/abstract 元数据）
    pdf_abstracts/       # 按需摘要 sidecar（338；3 篇 thin）
    HOW_TO_QUERY.md      # 速查
    README.md
  01_foundations/ … 10_surveys_handbooks/
  notes/                 # GAPS, READING_STACK, ERRATA, template
  _pdfs/                 # OA PDF + INVENTORY + MISLABEL + purge 记录
```

## 硬规则（所有读者）

1. 笔记优先于 PDF；PDF 优先于二手博客。  
2. 文件名不可信 — 看首页标题 / MISLABEL_LOG。  
3. 缺真实 swap/forward → **fail closed**，无正式净收益。  
4. 截至快照：**无批准交易因子**。  
5. 只写 `research/`（除非用户另授权）。

## 与主仓库关系

- 项目代码/配置：`src/`、`configs/`、`docs/` — 研究 agent **默认只读**。  
- 文献地图与路线：`docs/FX_FACTOR_LITERATURE_MAP_ZH.md` 等。  
- 本目录是**知识库**，不是回测产出目录。
