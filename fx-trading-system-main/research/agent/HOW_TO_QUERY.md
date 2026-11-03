# Agent 查询速查卡

## 最小工作流

```text
load  agent/routes.json          # 或 keywords.json
match intent from user question
read  each path in read_first[]  # markdown only
check notes/GAPS.md for fail_closed_if[]
if need PDF discovery:
  filter agent/pdf_index.jsonl   # 索引够用；可扫 abstract sidecar
  # 禁止：为全库预写深度笔记 / 预抽全文
if need formula or verify: open ONE pdf (note or index hit) + 按需抽取首页
answer with: conclusion + sources + fail-closed caveats
```

## 示例

| 用户问题 | intent | 先读 |
|---|---|---|
| carry 怎么做？有没有 edge？ | carry | Lustig + BNP + CIP checklist + GAPS G1/G2 |
| 我们 SPA 接好了吗？ | validation_fdr_dsr_pbo_spa | METHODS_MAP + hansen_2005_spa + GAPS V1 |
| FIX 窗口能赚钱吗？ | intradaily_fix_local | INTRADAY_SOURCE_MAP + Krohn + 成本否决 |
| 有没有批准策略？ | project_status_v4 | STUDY_CLOSURE + GAPS → **没有** |

## 上下文预算

- 默认：≤ **5** 个 md，≤ **5** 个 abstract sidecar，≤ **2** 个 PDF 原文片段  
- 禁止：递归读 `_pdfs/**/*.pdf`；禁止一次加载全部 `pdf_abstracts/`  
- 笔记列表：`catalog.json` 的 `notes[]`  
- PDF 列表：`pdf_index.jsonl`（**341** 条 L3；见 `pdf_l3_stats.md`）

## 输出模板（建议）

```markdown
## 结论
...
## 依据
- note: path
- pdf: path (first-page title: ...)
## 硬限制
- GAPS: ...
- 不可声称: ...
## 若要落地代码
- 只读映射: METHODS_MAP / replication_checklist
- 改注册表: 需 WP9 + 用户确认
```
