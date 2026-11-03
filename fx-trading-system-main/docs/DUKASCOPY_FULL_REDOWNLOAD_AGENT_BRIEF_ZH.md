# Dukascopy 14 品种本机从零重下 Agent 任务书

日期：2026-07-23。

## 0. 给接手 Agent 的直接指令

你负责在当前 Mac 本机直接连接 Dukascopy，使用固定版本的公开下载器，在一个**全新的空目录**
重新下载 14 个外汇品种在 `[2016-01-01, 2026-01-01)` 内的全部原始小时 `bi5` payload，按
“每个品种一个 SQLite”保存。下载完成后在本机执行整库校验和逐 payload 深度校验，生成唯一
的 14 库批次 manifest。

本任务不使用 VPS、不配置 HTTPS、不上传或发布文件。完成后只向用户报告本机目录、逐品种
统计、哈希和校验结果。

本任务允许中断后在本次新目录中续传。“从零重下”是指初始正式目录不含任何旧 SQLite、
sidecar、`.part` 或 manifest；不是每次断线都删除已下载内容重新开始。

不要修改或覆盖当前旧库：

```text
/Users/open/fx-trading-system/data/dukascopy_sqlite/EURUSD.sqlite
/Users/open/fx-trading-system/data/dukascopy_sqlite/GBPUSD.sqlite
```

完成前不要运行聚合、因子筛选、回测、收益标签或交易代码。

### 0.1 用 `/goal` 一次启动完整任务

在负责下载的 Agent 所在会话中输入下面一条命令。不要给本任务设置 token budget；下载和深验
是长任务，预算耗尽不应成为人为停止条件。

```text
/goal start 严格按照 /Users/open/fx-trading-system/docs/DUKASCOPY_FULL_REDOWNLOAD_AGENT_BRIEF_ZH.md 从头到尾执行本机 Dukascopy 14 品种重下载任务；持续推进、监控并对可恢复故障续传，直至 14 个 SQLite 及其 sidecar 和唯一批次 manifest 全部生成，普通 verify、逐 payload deep verify、最终文件与合同检查全部通过并提交完整报告；不得使用 VPS、代理或 HTTPS 发布，不得覆盖或删除旧库；只有任务书定义的真实外部硬阻塞才能停止并明确报告，未满足全部成功标准不得标记 goal complete。
```

`/goal` 是当前 Agent 会话的持久目标，不是 detached job、定时任务或额外权限。它会跨多轮和
进程重启保留，但仍需 Agent 真正启动并监控下载进程。下载命令必须使用第 9 节的
`caffeinate`；Agent 不能在命令刚进入后台或仍在运行时宣告完成。

常用状态命令：

```text
/goal
/goal resume
```

若该会话已有旧目标，先用 `/goal` 查看；确认旧目标已经结束后使用 `/goal clear`，再执行上面
的 `/goal start`。只有第 17 节全部满足时才能由 Agent 标记 complete。磁盘不足、三次直连
smoke 均失败等真实外部阻塞应按任务书报告；`/goal` 不会也不得绕过这些硬门。

## 1. 为什么要重下

主项目正式 intake 合同要求：

```text
provider=dukascopy
program_version=1.1.1
parser_version=dukascopy-bi5-v1
database_schema_version=1
range=[2016-01-01T00:00:00Z, 2026-01-01T00:00:00Z)
symbols=固定14品种
```

本机当前只有 EURUSD、GBPUSD 两个 v1.0.0 旧库，结束于 `2025-09-15`，且没有正式 14 库
`_sqlite_manifest.json`。它们虽然单库完整性审计通过，但不符合统一区间，因此当前正式 intake
是 `0/14 formal-ready`。

本任务使用新目录重下，不扩展、复制或刷新旧库，目的是得到同一程序版本、同一区间、同一
批次合同下的 14 个可复核数据库。

## 2. 冻结下载宇宙与区间

顺序必须保持如下，不得删除失败品种后继续冒充完整批次：

```text
EURUSD
GBPUSD
USDJPY
USDCHF
AUDUSD
NZDUSD
USDCAD
EURGBP
EURJPY
GBPJPY
AUDJPY
CADJPY
USDNOK
USDSEK
```

- 前 12 个是慢周期研究宇宙；
- FIX-W 使用 EURUSD、GBPUSD、USDJPY、USDCHF、AUDUSD、NZDUSD、USDCAD、USDNOK、
  USDSEK 九条 USD 腿；
- 14 个品种是数据接收宇宙，不是等权交易组合。

冻结边界：

```text
start=2016-01-01T00:00:00Z
end_exclusive=2026-01-01T00:00:00Z
```

不得擅自改到当前日期，也不得沿用旧的 `2025-09-15`。2026 年新增 forward 数据属于另一项
持续采集任务，不能混进本批次。

## 3. 固定下载器

本机已有独立公开仓库：

```text
path=/Users/open/dukascopy-sqlite-downloader
github=https://github.com/jlcbk/dukascopy-sqlite-downloader
version=1.1.1
git_commit=63ee417cfeaa5d96242f9126428d09303262bc6b
download_dukascopy_sqlite.py bytes=42535
download_dukascopy_sqlite.py sha256=3faffb1107f0f5f65daed6b0cd7c552352810d66a41c67b915ed4110284b6ce5
```

任务中途不得 `git pull`、修改源码、切换 commit 或升级依赖。v1.1.1 修复了已发布库刷新
`no_data` 的问题；本任务使用新目录，不传 `--refresh-no-data`。

## 4. 本机目录合同

固定建议路径：

```text
下载器：/Users/open/dukascopy-sqlite-downloader
新数据库：/Users/open/fx-trading-system/data/dukascopy_sqlite_fresh_20160101_20260101_v111
日志：/Users/open/fx-trading-system/outputs/dukascopy_full_redownload_20260723
```

数据库目录必须在首次开始时不存在。日志不能写进数据库目录，否则会改变最终传输文件集合。
任务完成后也不要自行把新目录改名为 `data/dukascopy_sqlite`；由主项目在独立验收后决定如何
替换旧库。

## 5. 磁盘空间硬门

14 个 SQLite 预计约 30--60 GB，极端情况可能更高。下载中还需要 WAL、临时文件、deep
verify 和系统运行余量。

2026-07-23 实测当前数据卷约为：

```text
228 GiB total
118 GiB used
69 GiB available
```

这低于本任务的安全开工线。接手 Agent 必须先运行：

```bash
df -h /Users/open
```

开工条件：

- 最低 `80 GiB` 可用；
- 建议 `100 GiB` 可用；
- 下载过程中剩余空间不得低于 `15 GiB`。

如果仍只有约 69 GiB：

1. 可以继续做第 7 节的一小时 smoke test；
2. 不得开始全量下载；
3. 向用户报告空间不足，请用户指定外接磁盘路径或授权清理；
4. 不得自行删除 `data/`、`outputs/`、`research/`、旧 SQLite 或其他用户文件。

若用户指定外接卷，则只需把 `DATA_DIR` 和 `LOG_DIR` 改到该卷；其他合同不变。

## 6. 代码与环境预检

```bash
cd /Users/open/dukascopy-sqlite-downloader

git status --short
git rev-parse HEAD
sha256sum download_dukascopy_sqlite.py
uv run python download_dukascopy_sqlite.py --version
uv run pytest -q
uv run ruff check .
```

必须得到：

```text
git status => clean
HEAD => 63ee417cfeaa5d96242f9126428d09303262bc6b
script SHA => 3faffb1107f0f5f65daed6b0cd7c552352810d66a41c67b915ed4110284b6ce5
version => 1.1.1
pytest => 7 passed
ruff => All checks passed
```

如果任一不符，停止并报告，不要通过编辑源码“修到能跑”。

同时保存：

```bash
date -u
sw_vers
uname -a
uv run python --version
df -h /Users/open
```

## 7. 本机直连 smoke test

此前本机曾出现 DNS/TCP/TLS 成功但 HTTPS 无首字节的情况，因此全量下载前必须真实下载一个
小时。Smoke 使用 `/tmp`，不能污染正式目录：

```bash
cd /Users/open/dukascopy-sqlite-downloader

export SMOKE_DIR=/tmp/dukascopy_smoke_v111_20260723
test ! -e "$SMOKE_DIR"
mkdir -p "$SMOKE_DIR"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

uv run python download_dukascopy_sqlite.py download \
  --symbols EURUSD \
  --start 2025-01-06T00:00:00Z \
  --end 2025-01-06T01:00:00Z \
  --database-dir "$SMOKE_DIR" \
  --workers 1 \
  --retries 5 \
  --timeout 30 \
  --batch-size 1

uv run python download_dukascopy_sqlite.py manifest \
  --symbols EURUSD \
  --database-dir "$SMOKE_DIR"

uv run python download_dukascopy_sqlite.py verify \
  --database-dir "$SMOKE_DIR" \
  --deep
```

只有 download、manifest、deep verify 全部退出 0，才能通过网络门。下载器默认
`trust_env=false`；本任务还要求清除代理环境变量，禁止传入 `--proxy` 或 `--use-env-proxy`。

若 smoke 失败：

- 再选择两个正常工作日小时各试一次；
- 保存错误、UTC 时间以及 `curl -v --noproxy '*'` 的连接证据；
- 三次均无首字节或失败后，状态记为 `blocked_local_direct_connectivity`；
- 不得擅自改用代理、VPS 或别的数据源。

## 8. 创建全新正式目录

只有磁盘和 smoke 两个门都通过后才能执行：

```bash
export DOWNLOADER_ROOT=/Users/open/dukascopy-sqlite-downloader
export DATA_DIR=/Users/open/fx-trading-system/data/dukascopy_sqlite_fresh_20160101_20260101_v111
export LOG_DIR=/Users/open/fx-trading-system/outputs/dukascopy_full_redownload_20260723

test ! -e "$DATA_DIR"
mkdir -p "$DATA_DIR" "$LOG_DIR"
chmod 0750 "$DATA_DIR" "$LOG_DIR"
test -z "$(find "$DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit)"
```

首次创建后记录路径。中断续传时必须复用同一 `DATA_DIR`，不要再次执行 `test ! -e`，也不要
换新目录。程序会在 `$DATA_DIR/.work/` 保存正在下载的 `.part`。

## 9. 全量本机下载

长任务必须防止 Mac 睡眠。优先在 `tmux` 中运行；若没有 tmux，至少让 `caffeinate` 包裹整个
进程，并确保 Agent 持续监控该执行会话。

下载器支持多线程下载。实现方式是 `ThreadPoolExecutor`：当前品种的不同小时 URL 会并发
请求，`--workers` 的合法范围是 1--32；SQLite 写入仍由主线程分批提交。14 个品种本身按
`SYMBOLS` 顺序逐个处理，所以 `--workers 2` 表示每个品种最多两个并发 HTTP 请求，不表示
14 个数据库同时下载。

Dukascopy 的小时文件端点可以并发请求，但没有应被依赖的“无限并发”服务合同。固定批次默认
使用 `--workers 2`，这也是下载器 README 的全量任务建议值。只有连续观察至少 30 分钟、无
429、超时没有明显上升且磁盘正常时，才可在下一次续传命令中试用 `--workers 4`；必须把参数
变化及时间写入日志。出现 429、连接重置或超时率上升时降回 2，仍不稳定则降为 1。不得超过
4，不得另开多个下载器进程并行写同一个 `DATA_DIR`。

```bash
cd "$DOWNLOADER_ROOT"
set -o pipefail

export SYMBOLS=EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,NZDUSD,USDCAD,EURGBP,EURJPY,GBPJPY,AUDJPY,CADJPY,USDNOK,USDSEK
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

caffeinate -dimsu uv run python download_dukascopy_sqlite.py download \
  --symbols "$SYMBOLS" \
  --start 2016-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z \
  --database-dir "$DATA_DIR" \
  --workers 2 \
  --retries 5 \
  --timeout 30 \
  --batch-size 64 \
  2>&1 | tee -a "$LOG_DIR/download.log"
```

本次是新目录，不得传 `--refresh-no-data`。

下载器按品种顺序处理，每个品种内部最多两个并发请求。一个品种全部完成、WAL checkpoint、
SQLite quick check 后，才会从 `.work/SYMBOL.sqlite.part` 原子发布为根目录的
`SYMBOL.sqlite`、`.sqlite.json`、`.sqlite.sha256`。

若命令退出 1、网络中断、Mac 重启或 Agent 会话中断，检查日志后重复第 9 节的完全相同命令。
不要删除 `.work`；程序只补缺失小时。任何时候只能有一个进程写该 `DATA_DIR`。

## 10. 监控和错误处理

至少每个品种发布后记录一次：

```bash
tail -n 100 "$LOG_DIR/download.log"
du -sh "$DATA_DIR"
df -h /Users/open
find "$DATA_DIR" -maxdepth 1 -type f -name '*.sqlite' -ls
```

剩余空间接近 `15 GiB` 时必须安全停止，并报告用户；不能等磁盘写满。

| 情况 | 处理 |
|---|---|
| 临时超时、5xx、连接断开 | 让内置重试执行；仍失败则用原命令续传 |
| 429/限流 | 不提高并发，必要时将 workers 降为 1 后继续 |
| 404/空文件 | 由程序按“距当前时间超过 7 天”规则决定是否固化 `no_data` |
| LZMA、记录长度、tick 时间或 ask/bid 校验失败 | 真实失败，不得改成 `no_data` |
| 单品种仍有 missing hour | 不生成最终 manifest，重复下载 |
| 磁盘不足 | 安全停止并请求用户选择扩容/外接卷；不自行删文件 |
| 想升级代码或依赖 | 本批次禁止；保持固定 commit 和 uv 环境 |

不得手工编辑 SQLite、插入状态或从 14 品种中删除失败品种。

## 11. 生成 14 库批次 manifest

只有下载命令退出 0，并打印：

```text
Download complete. Run the manifest command before transferring databases.
```

才执行：

```bash
cd "$DOWNLOADER_ROOT"

uv run python download_dukascopy_sqlite.py manifest \
  --symbols "$SYMBOLS" \
  --database-dir "$DATA_DIR" \
  --output "$DATA_DIR/_sqlite_manifest.json"
```

该文件必须是唯一的完整批次 manifest。不要生成或保留两品种临时 manifest，不要复制旧
manifest。

## 12. 本机普通校验和深度校验

普通校验检查每库 bytes、整库 SHA、manifest 和 SQLite quick check：

```bash
uv run python download_dukascopy_sqlite.py verify \
  --database-dir "$DATA_DIR" \
  --manifest "$DATA_DIR/_sqlite_manifest.json"
```

深度校验会逐个读取全部 `ok` payload，复算 payload SHA、LZMA 解压并验证全部 tick：

```bash
set -o pipefail
caffeinate -dimsu uv run python download_dukascopy_sqlite.py verify \
  --database-dir "$DATA_DIR" \
  --manifest "$DATA_DIR/_sqlite_manifest.json" \
  --deep \
  2>&1 | tee "$LOG_DIR/deep_verify.log"
```

Deep verify 可能持续数小时，必须等待退出 0；它不是抽样验证。

## 13. 最终文件集合与合同检查

```bash
cd "$DATA_DIR"

for sidecar in ./*.sqlite.sha256; do
  shasum -a 256 -c "$sidecar"
done

test "$(find . -maxdepth 1 -type f | wc -l)" -eq 43
test "$(find . -maxdepth 1 -type f -name '*.sqlite' | wc -l)" -eq 14
test "$(find . -maxdepth 1 -type f -name '*.sqlite.json' | wc -l)" -eq 14
test "$(find . -maxdepth 1 -type f -name '*.sqlite.sha256' | wc -l)" -eq 14
test -f ./_sqlite_manifest.json

test -z "$(find . -maxdepth 2 -type f \
  \( -name '*.part' -o -name '*-wal' -o -name '*-shm' -o -name '*.tmp' \) -print -quit)"
```

43 项 = 14 SQLite + 14 JSON sidecar + 14 SHA sidecar + 1 batch manifest。日志位于
`outputs/`，不计入数据目录。

检查 manifest：

```bash
jq -e '
  .schema_version == 1 and
  .program_version == "1.1.1" and
  .parser_version == "dukascopy-bi5-v1" and
  (.databases | length) == 14 and
  all(.databases[];
    .integrity == "ok" and
    .metadata.program_version == "1.1.1" and
    .metadata.parser_version == "dukascopy-bi5-v1" and
    .metadata.requested_start == "2016-01-01T00:00:00Z" and
    .metadata.requested_end_exclusive == "2026-01-01T00:00:00Z" and
    (.metadata.missing_hours | tonumber) == 0 and
    (.metadata.completed_hours | tonumber) == (.metadata.expected_hours | tonumber) and
    (.counts.ok + .counts.no_data) == (.metadata.expected_hours | tonumber)
  )
' _sqlite_manifest.json

shasum -a 256 _sqlite_manifest.json
```

## 14. 进度汇报

接手 Agent 至少在以下节点通知用户：

1. 环境、代码、磁盘预检结果；
2. 三个本机 smoke 尝试中第一个成功，或三次均失败后的阻断证据；
3. 正式目录创建和全量任务启动；
4. 每个品种原子发布后；
5. 14/14 下载完成；
6. 普通 verify 通过；
7. deep verify 通过；
8. 最终文件集合和 manifest 合同通过。

每个品种报告：

| 字段 | 要求 |
|---|---|
| symbol | 固定品种 |
| bytes/GiB | 实际大小 |
| requested range | 必须为统一区间 |
| expected/completed hours | 必须相等 |
| ok/no_data/missing | missing 必须为 0 |
| database SHA-256 | 与 sidecar/manifest 一致 |
| deep verified payloads | 全部 ok payload 数 |

长任务进行中不要只回复“仍在运行”；同时报告当前品种、完成小时、重试/错误和剩余磁盘。

## 15. 最终交付

本机数据目录必须包含：

```text
14 × SYMBOL.sqlite
14 × SYMBOL.sqlite.json
14 × SYMBOL.sqlite.sha256
1  × _sqlite_manifest.json
```

最终消息或报告包含：

- 固定 commit、程序版本和脚本 SHA；
- 最终本机绝对路径；
- 14 品种逐项统计；
- 普通 verify 与 deep verify 的退出状态和日志路径；
- manifest SHA-256；
- 总占用空间、剩余磁盘和完成时间；
- 所有重试、429、异常 `no_data` 或人工介入；
- 明确说明没有修改旧库、没有聚合、没有打开收益标签。

最终机器状态：

```text
download_complete=true
symbols_complete=14/14
deep_verify_passed=true
batch_manifest_complete=true
range_start=2016-01-01T00:00:00Z
range_end_exclusive=2026-01-01T00:00:00Z
aggregation_performed=false
return_labels_opened=false
factor_outcome_evaluations_added=0
trading_approval=false
```

## 16. 不在本任务范围内

- 不使用 VPS、代理或 HTTPS 发布；
- 不聚合 1h/4h/日线；
- 不构建主项目 daily cache；
- 不运行价格因子或外部交互筛选；
- 不打开收益标签；
- 不生成 paper plan、订单或交易批准；
- 不修改下载器源码；
- 不替换或删除本机旧库；
- 不选择性删除数据较差的品种；
- 不声称 Dukascopy 报价等于 broker 实际成交或全市场 consolidated tape。

下载完成后的独立数据审计、正式 intake ledger、旧库切换和后续聚合由主项目另行执行。

## 17. 成功标准

只有以下条件全部成立，任务才算完成：

1. 磁盘硬门和本机直连 smoke 通过；
2. 初始正式目录为空，未复用旧数据库；
3. 固定 commit、版本、脚本 SHA 和测试全部匹配；
4. 14 品种都覆盖同一排他区间；
5. 每库 missing=0、completed=expected、quick_check=ok；
6. 14 个整库 SHA 与 sidecar/manifest 一致；
7. 全部 `ok` payload 深度解压、SHA 和 tick 合法性验证通过；
8. 批次 manifest 恰好包含 14 库；
9. 数据目录恰好有预期 43 项，没有 part/WAL/SHM/tmp；
10. 最终报告包含完整统计、路径和 manifest SHA；
11. 旧库未修改，且没有聚合、回测、收益标签或新增 outcome exposure。

任一条件失败时，状态只能是 `incomplete` 或 `blocked`，不得以部分 14 库宣告成功。
