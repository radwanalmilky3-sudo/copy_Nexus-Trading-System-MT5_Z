# Agent 使用协议（research 知识库）

**给其他 agent / 自动化：** 先读本文件，再按意图路由。不要把整库 PDF 灌进上下文。

## 0. 30 秒决策树

```text
1. 用户问题属于哪类 intent？ → 读 agent/routes.json 或下文 §2
2. 打开 read_first 中的 Markdown 笔记（优先）
3. 需要搜本地 PDF 时：agent/pdf_index.jsonl（L3：title/abstract/tags）→ 读 abstract_file → 仍不够再开 1 个 PDF
4. 若需原文公式：只打开笔记点名或 L3 命中的单个 OA PDF，并核首页标题
5. 查 notes/GAPS.md：若相关 G/C/V/R 为 open，结论必须 fail closed
6. 禁止：改注册表搜收益、声称已有批准策略、用 mid 写净 PnL
```

## 1. 必读枢纽（按顺序，通常 1–3 个文件）

| 优先级 | 路径 | 何时读 |
|---|---|---|
| P0 | `AGENTS.md`（本文件） | 每次进入本库 |
| P0 | `agent/routes.json` | 意图路由（小、机器可读） |
| P0 | `notes/GAPS.md` | 任何“能否复制/能否交易”问题 |
| P1 | `STUDY_CLOSURE_ZH.md` | 项目研究状态与收口边界 |
| P1 | `NOTES_INDEX_ZH.md` | 按主题找笔记 |
| P1 | `notes/READING_STACK_ZH.md` | 推荐深读顺序 |
| P2 | 各桶 `CATALOG.md` / `METHODS_MAP.md` | 需要完整列表时 |
| P2 | `agent/pdf_index.jsonl` + `agent/pdf_abstracts/` | 按标题/摘要/tags 找本地 PDF（L3，**341** 篇） |
| P3 | `_pdfs/...` 单个 PDF | 笔记/L3 不够时；**禁止批量加载** |

**笔记目录：** `agent/catalog.json`（~87 条笔记元数据）。  
**PDF L3：** `agent/pdf_index.json` / `pdf_index.jsonl`（**341** 条）+ `pdf_abstracts/`（**338** 有效；3 篇 `thin_or_scan`）。统计：`agent/pdf_l3_stats.md`。  
**策略：** 索引优先、按需抽 1 个 PDF；不预写全库研读 L3 笔记。

## 2. 意图 → 文件（摘要）

完整版：`agent/routes.json`。常见映射：

| intent | 关键词示例 | 先读 |
|---|---|---|
| `carry` | carry, HML_FX, 利差 | Lustig / Menkhoff carry / BNP + CIP checklist + GAPS |
| `cip_basis` | CIP, basis, 远期 | CIP_CONTRACT_CHECKLIST + Du/Borio/Avdjiev + GAPS |
| `momentum` | momentum, TSMOM | Menkhoff mom + TSMOM + Asness + Harvey zoo |
| `value_reer` | REER, value, PPP | Menkhoff value + BIS REER note + PIT guide |
| `validation_fdr_dsr_pbo_spa` | FDR, DSR, PBO, SPA | METHODS_MAP + Bailey/Hansen/Harvey + GAPS V* |
| `intraday_fix_local` | FIX-W, WMR, LOCAL | INTRADAY_SOURCE_MAP + Krohn/Breedon + WMR |
| `macro_surprise` | surprise, NFP | Faust/Andersen + **G4** |
| `liquidity_vrp_options` | VRP, liquidity RP, Cboe | Söderlind + Della Corte VRP + Cboe note |
| `costs_swap_financing` | swap, financing | SWAP_FORWARD_SOURCES + OANDA note + G1 |
| `pit_vintage_data` | PIT, vintage, CFTC | PIT_AND_VINTAGE_GUIDE + dataset notes |
| `project_status_v4` | 有没有盈利因子, v4 | STUDY_CLOSURE + GAPS + docs/* 只读 |
| `order_flow` | order flow | Evans–Lyons + Breedon OF + R4/R16 |

关键词反查：`agent/keywords.json`（小写 key → intent）。

## 3. 硬规则（违反=错误答案）

1. **笔记优先于 PDF；PDF 优先于网页二手文。**  
2. **文件名 ≠ 标题。** 引用 `_pdfs/` 前查 `MISLABEL_LOG.md` 或读 PDF 首页。  
3. **`cost_incomplete` / 缺 G1·G2 → 禁止正式历史净收益。**  
4. **midquote / Yahoo / 合成 F_hat ≠ 可实现 alpha。**  
5. **截至库快照：无批准交易策略**（v4 方向 0 入选）。  
6. **Cboe 30D ≠ 1Y OTC VRP；CFTC ≠ signed OF；BIS 季频 ≠ G9 日方向。**  
7. **2016–2025 为 reused-history**，不能当 untouched holdout。  
8. **读文献不得扩 FDR 搜索网格**；新候选只走 WP9 章程。  
9. **写入边界：** 默认仅 `research/`；改 `src/`/`configs/` 需用户明确授权。  
10. **上下文预算：** 单次任务通常 ≤5 个 md + ≤2 个 PDF 摘录；禁止 `find _pdfs | xargs cat`。  
11. **PDF 策略（用户约定）：** 默认 **只有索引够用**（`pdf_index.jsonl` + 已有 abstract sidecar）。**不**为 341 篇预写研读 L3 笔记、**不**预跑全文/向量。真正需要公式或核对时，再 **按需** 打开 **1** 个 PDF（或重抽该篇首页）；优先笔记已有内容。

## 4. 推荐查询伪代码

```text
function answer(q):
  intent = match(q, agent/keywords.json) or classify(q, agent/routes.json)
  route  = routes[intent]
  for path in route.read_first:
      read(path)   # markdown
  for gap_id in route.fail_closed_if:
      if gap open in notes/GAPS.md:
          include fail-closed caveat
  if need local pdf discovery:
      filter agent/pdf_index.jsonl by tags_guess|title_guess|ids|priority
      read top-k abstract_file only (k<=5); prefer priority=hot
  if need equation detail:
      open ONE pdf (note-linked or L3 hit); verify first-page title
  never: claim tradable alpha without G1+G2+bid/ask+validation
  never: dump all pdf_abstracts into context
```

## 5. 笔记元数据字段（catalog.json）

每条 note：

```text
id, path, title, bucket, level, role, replication, project_map, doi
```

`replication` 常见值：`exact_possible` | `extension_only` | `fail_closed_missing_data` | `negative_control`。

## 6. 人类入口

- 人类导航：`INDEX.md`、`README.md`  
- 六周学习：`09_deep_study_path/DEEP_STUDY_PATH_ZH.md`  
- 本协议：`AGENTS.md`
