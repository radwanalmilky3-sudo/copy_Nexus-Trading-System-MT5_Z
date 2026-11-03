# 7h 批量 — 一页状态（Wave D 库存）

**快照 UTC：** densify 峰值 2026-07-17T00:09:58Z；**冷库清理** 2026-07-17T01:24Z  
**开始：** 2026-07-16T16:25:06Z（`_BULK_WAVE_START.txt`）  
**状态：** densify **全部结束** → 已按相关性 **purge**（见 `_pdfs/_PURGE_SUMMARY_ZH.md`）  
**写入边界：** 仅 `research/`；合法 OA；主吞吐=本机 Python 线程池。

## 核心数字

| 指标 | densify 峰值 | **清理后（当前）** |
|---|---:|---:|
| PDF（`_pdfs`） | 8391 | **341**（先 bulk→418，再 E/F→341） |
| 字节 / `du` | ~8.51 GiB / 8.5G | **~386 MB / `du` 372M** |
| 删除累计 | — | bulk **7973** + E/F **77** |
| Manifest 行 | 9480 | 9480（历史；可含已删路径） |
| 主题深度笔记 | ~87 | **87**（另 `notes/` 枢纽 4 个 md） |
| 已确认误标 | 10 | **10**（保留） |
| PDF L3 索引 | — | **341** 条（abstract sidecar **338**） |

## PDF 分桶（当前 341）

`_official` 95 · `_nber` 76 · `_validation` 31 · `_micro` 30 · `_arxiv` 26 · `_bis` 24 · `_fed` 15 · `02_factor` 14 · `_ecb` 13 · `_ssrn` 12 · root 3 · `_imf` 2

## 后台任务

**无** — 全部 densify nohup 已退出。

## 关键卫生

- **Itskhoki–Mukhin disconnect 正确 PDF 可用：**  
  `research/_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf`  
  first-page：*Exchange Rate Disconnect in General Equilibrium*（NBER **w23401**）。  
  旧路径 `..._w27847.pdf` 仍为 **Hassan–Zhang** 误标（保留不删）。
- 误标全表：**10** 条 — `_pdfs/MISLABEL_LOG.md`；库存：`_pdfs/INVENTORY.md`。

## 笔记面（粗）

01:5 · 02:37 · 03:8 · 04:11 · 05:3 · 06:4 · 08:9 · 10:10 · 中枢 notes 3（模板/GAPS/栈）

## 仍开缺口（摘自 `notes/GAPS.md`，不展开）

- **硬阻塞：** G1 G2 G4 G5（G3 项目侧进行中）
- **成本/CIP：** C1–C4（C5–C6 为解释边界）
- **验证接线：** V1（V2–V6 诊断/延迟）
- **微观/PIT：** G6–G12
- **复制/文献：** R1–R4 R5–R10 R12–R13 R15–R17（R11/R14 closed 口径以 GAPS 为准）

## 进行中 / 下一步

1. **下载波次继续**（NBER/BIS 等；勿 stop；7h 后用户仍继续）。  
2. Lustig–Verdelhan 正确 OA 仍缺；Avdjiev CIP 用 BIS wp592。  
3. Wave D 收口：INDEX / GAPS / 去重 / 引用卫生（文件名不可信）。  
4. 正式净收益仍受 G1–G2 / `cost_incomplete` 硬门控。

## 指针

- 总索引：`INDEX.md`  
- 进度表：`_BULK_PROGRESS_ZH.md`  
- 作战日志：`_BULK_CAMPAIGN_ZH.md`  
- PDF 库存：`_pdfs/INVENTORY.md`
