# GBPUSD Dukascopy 原始 tick 数据审计

审计日期：2026-07-16

数据区间：`[2016-01-01T00:00:00Z, 2025-09-15T00:00:00Z)`

## 结论

该数据库通过文件传输、SQLite 结构、全部压缩 payload 和全部 tick 的机械完整性审计，
价格尺度也与独立的 Federal Reserve `DEXUSUK` 日频参考高度一致。当前状态为
**有条件通过研究验收**，不是“完全无缺口”：

1. `2016-09-02T18:00:00Z` 是唯一无法由标准纽约外汇周边界、圣诞或新年解释的
   `no_data` 小时。前一小时最后报价停在 `17:05:29.999Z`，下一小时在
   `19:00:00.156Z` 恢复，形成约 1 小时 54 分 30 秒的源数据空档。
2. 本机尚缺 VPS 同批次生成的 `_sqlite_manifest.json`。数据库、`.sha256` 和 `.json`
   已互相吻合，但正式 transfer receipt 仍需原始目录 manifest，不能在本机事后伪造。
3. 文件截止到 2025-09-15 排他边界，不是完整的 2025 日历年。

在 VPS 重抓空小时并传回新数据库、sidecar 和原始 manifest 之前，不应把这份单品种数据
加入正式冻结的多品种因子样本。诊断研究可以保留原始文件，并明确抑制跨越该空档的 session。

## 传输与结构

| 项目 | 结果 |
|---|---:|
| 文件字节数 | 1,354,809,344 |
| SHA-256 | `6d54500c2ed28ad1d7c42cdf856307a34e44f415796be66d7788d36b0be2bba5` |
| SHA sidecar | 匹配 |
| SQLite `PRAGMA quick_check` | `ok` |
| 残留 `.part` / WAL / SHM | 0 |
| schema / provider / parser / symbol / divisor | 全部匹配 |

## 小时覆盖

宽口径候选外汇周共有 61,251 小时，数据库也恰有 61,251 条状态记录：

| 状态 | 小时数 | 解释 |
|---|---:|---|
| `ok` | 60,486 | 有非空、可解压 tick payload |
| `no_data` | 765 | 来源返回 HTTP 200 空 payload |
| 数据库中缺行 | 0 | 候选小时集合完全匹配 |
| 范围外或未知状态行 | 0 | 无 |

对 765 个 `no_data` 小时按 `America/New_York` 的标准外汇周重新分类：

| 类别 | 小时数 |
|---|---:|
| 周五纽约 17:00 已收市 | 333 |
| 周日纽约 16:00 尚未开市 | 173 |
| 圣诞 / 新年核心休市 | 255 |
| 2019-05-26 美国阵亡将士纪念日周末延迟开市 | 3 |
| 无法由上述规则解释的孤立空档 | 1 |

因此，`missing=0` 只表示数据库没有遗漏应记录的小时状态，不表示每个候选小时都有行情。

## Payload 与报价硬约束

| 检查 | 结果 |
|---|---:|
| 已验证 payload SHA-256 | 60,486 / 60,486 |
| LZMA 解压成功 | 60,486 / 60,486 |
| 解压字节数 | 5,664,742,040 |
| 20-byte tick 数 | 283,237,102 |
| `compressed_bytes` / `tick_count` / 首末 offset 不一致 | 0 |
| 非正 bid/ask | 0 |
| crossed quote (`ask < bid`) | 0 |
| 非法 quote size | 0 |
| 小时内乱序或全局时间回退 | 0 |
| 重复毫秒 offset | 0 |

这里的 quote size 是 Dukascopy 的报价流动性代理，不是全市场成交量。

## 市场合理性

全样本 midpoint 位于 `1.034205` 到 `1.501870`，与 2016--2025 年 GBPUSD 的已知量级
一致。平均点差约 1.0474 pip；最大 40 pip。最宽点差集中在周日开盘、圣诞前后、
Brexit 结果期等低流动性或压力窗口，不能当作免费可成交价格，也不应自动删除。

最大的亚秒级报价跳变集中在 `2016-10-06T23:07Z--23:12Z`，对应已知的英镑
flash crash；Brexit、2020 年 3 月和 2022 年英国 mini-budget 窗口均有连续合法报价，
并呈现预期的价格下跌、波动和点差扩大。极端值应在研究中保留为真实风险状态，
不能为了改善回测而 winsorize。

## 独立参考交叉核对

Federal Reserve H.10 / FRED `DEXUSUK` 只用于数据质量核对，不作为交易因子。以纽约当地
12:00 后第一条 Dukascopy midpoint 对照 2,423 个有效日频观测：

| 指标 | 结果 |
|---|---:|
| 价格水平相关系数 | 0.9999982842 |
| 相邻观测收益相关系数 | 0.9997995238 |
| 绝对差异中位数 | 0.9061 bps |
| 绝对差异 95% 分位 | 2.4397 bps |
| 绝对差异 99% 分位 | 3.4361 bps |
| 最大绝对差异 | 10.7729 bps |

这排除了价格除数错十倍、货币对方向颠倒或全局时间错位等问题。两来源不是同一成交场所，
且 FRED 只保留四位小数，因此不要求逐点相等。

## VPS 刷新步骤

公开下载器 `v1.1.1` 已修复“已发布数据库的 `--refresh-no-data` 不会实际重抓”的缺陷，
提交为 `63ee417cfeaa5d96242f9126428d09303262bc6b`。在 VPS 上使用原始完整区间刷新：

```bash
git -C dukascopy-sqlite-downloader pull --ff-only
cd dukascopy-sqlite-downloader
uv sync
uv run python download_dukascopy_sqlite.py download \
  --symbols GBPUSD \
  --start 2016-01-01T00:00:00Z \
  --end 2025-09-15T00:00:00Z \
  --database-dir dukascopy_sqlite \
  --workers 4 \
  --retries 6 \
  --timeout 60 \
  --batch-size 64 \
  --refresh-no-data
uv run python download_dukascopy_sqlite.py manifest \
  --symbols GBPUSD \
  --database-dir dukascopy_sqlite
```

刷新会重查全部 765 个历史空小时。周末和节假日大多仍会保持 `no_data`，重点观察
`2016-09-02T18:00:00Z` 是否变为 `ok`。之后应重新传回：

- `GBPUSD.sqlite`
- `GBPUSD.sqlite.sha256`
- `GBPUSD.sqlite.json`
- `_sqlite_manifest.json`

## 审计产物

- `outputs/dukascopy_audit/GBPUSD_dukascopy_audit.json`
- `outputs/dukascopy_audit/GBPUSD_FRED_DEXUSUK_comparison.json`
- `outputs/dukascopy_audit/reference/DEXUSUK.csv`
- `scripts/audit_dukascopy_sqlite.py`
- `scripts/compare_dukascopy_fred_spot.py`
