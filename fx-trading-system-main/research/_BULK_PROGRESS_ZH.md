# 7h 批量进度快照

更新时间（UTC）：**2026-07-16T23:47:08Z**  
开始：`_BULK_WAVE_START.txt` → `2026-07-16T16:25:06Z`  
已用时：**~7.37 h**（7:22:02）— **7h 窗口已过；用户选择继续多线程下载**

## 规模（滚动 / 实测）

| 指标 | 值 |
|---|---:|
| PDF 文件（`_pdfs`） | **5897** |
| research 全树 PDF | **~5899** |
| PDF 内容字节 | **5,864,825,200** (~5.46 GiB) |
| `du -sh research/_pdfs` | **5.5G** |
| `du -sh research/` | **5.5G** |
| Manifest 数据行 | **6064** |
| Manifest ok / fail_403 | **6039** / **7** |
| 深度笔记 `**/notes/*.md`（主题桶，不含模板/GAPS/栈） | **87** |
| notes 路径下 md 全量 | **90** |
| research 全部 `.md` | **148** |
| research 文件总数 | **~6077** |
| `_html_snapshots` 文件 | **24** |
| 已确认误标 PDF | **10**（见 `_pdfs/MISLABEL_LOG.md`） |
| 近 5 / 30 分钟新 PDF | **423** / **2383** |

## PDF 分桶（实测）

| 目录 | PDF 数 |
|---|---:|
| `_nber` | 3543 |
| `_bis` | 1077 |
| `_fed` | 606 |
| `_arxiv` | 313 |
| `_imf` | 96 |
| `_official` | 95 |
| `_ecb` | 77 |
| `_validation` | 31 |
| `_micro` | 30 |
| `02_factor` | 14 |
| `_ssrn` | 12 |
| `(root)` | 3 |
| **合计** | **5897** |

相对 17:38 快照（2081 PDF / 2.5G）→ **本快照 5897 / 5.5G**（约 +3816 PDF，NBER/BIS 为主抬升）。

## 深度笔记完成面（约）

- 01 foundations：5
- 02 factor：37（Wave2–4 主表）
- 03 micro：8
- 04 validation：11
- 05 data contracts：3
- 06 costs：4
- 08 datasets：9
- 10 surveys：10（含 Hassan–Zhang / Burnside–Graveline 误标澄清）

## 卫生本轮

- 误标表升至 **10**（`_pdfs/MISLABEL_LOG.md`；未删除）
- **R11 补全仍有效：** 正确 Itskhoki–Mukhin disconnect  
  `_pdfs/_nber/itskhoki_mukhin_exchange_rate_disconnect_w23401.pdf`
- 重建 `_pdfs/INVENTORY.md`；`INDEX.md` / `_BULK_STATUS_ZH.md` 对齐本冻结
- 下载仍在飞：可见 NBER 区间批量 `urllib` 多线程 + manifest append；近 5 分钟数百个新 PDF

## 仍在飞的波次

- NBER 大号段补齐（例：w29000–33000 步进批量）与 BIS 等 OA 桶
- validation / SSRN OA、误标 rename / Lustig–Verdelhan 正确 OA 仍缺
- **7h 已过，下载不中断**（用户继续）

## 纪律

- 只写 `research/`
- 合法 OA；付费墙跳过
- 不下行情大库
- 引用以 first-page 为准，不盲信文件名
