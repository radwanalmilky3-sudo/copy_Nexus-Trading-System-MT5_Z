# Dukascopy SQLite 单文件下载器

脚本：`scripts/download_dukascopy_sqlite.py`。当前版本：`1.1.0`。公开仓库：
<https://github.com/jlcbk/dukascopy-sqlite-downloader>；v1.1 发布提交：`e27bb2a`。

它用于把耗时的原始 tick 下载放到可直连 Dukascopy 的海外 VPS，原始 LZMA `bi5` payload
直接作为 BLOB 写入“每个货币对一个 SQLite”。VPS 不做聚合；数据库通过 HTTPS 转移回本机
后，再按需生成 1h/4h CSV。

## 文件生命周期

```text
下载中（禁止发布）
dukascopy_sqlite/.work/EURUSD.sqlite.part

该品种全部小时完成 + WAL checkpoint + SQLite quick_check
                         │
                         ▼ 原子 rename
可发布
dukascopy_sqlite/EURUSD.sqlite
dukascopy_sqlite/EURUSD.sqlite.sha256
dukascopy_sqlite/EURUSD.sqlite.json
```

下载失败不会写入假记录；再次运行相同命令只补缺失小时。404/空文件只有在距离当前时间超过
7 天时才固化为 `no_data`，避免把上游发布延迟永久缓存。每个成功 payload 在入库前检查：

- LZMA 可解压且长度为 20-byte 记录的整数倍；
- tick 毫秒偏移单调并位于当前小时；
- ask ≥ bid > 0；
- bid/ask quote size 有限且非负；
- 保存压缩 payload 的 SHA-256、字节数、tick 数和来源 URL。

## VPS 安装

需要 Python 3.11+。只有下载命令需要 `httpx`；校验和聚合只使用标准库。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'httpx>=0.27,<1'

curl -L -O \
  https://raw.githubusercontent.com/jlcbk/dukascopy-sqlite-downloader/main/download_dukascopy_sqlite.py
chmod +x download_dukascopy_sqlite.py
python download_dukascopy_sqlite.py --version
```

`--version` 应输出 `1.1.0`。v1.1 将默认排他结束时间更新为 `2026-01-01`，
并在原 12 个慢周期品种外增加 `USDNOK` / `USDSEK`。如果 VPS 上的旧版任务仍在运行，
先让原进程结束，再更新脚本并重跑同一目录；不要让新旧两个进程并发写同一数据库。
续传只会补已有库的缺失小时，并新建 NOK/SEK 数据库。

## VPS 直连下载

默认明确忽略 `HTTP_PROXY/HTTPS_PROXY`，直接连接 Dukascopy。建议先下载一个小时验证：

```bash
python download_dukascopy_sqlite.py download \
  --symbols EURUSD \
  --start 2025-01-06T00:00:00Z \
  --end 2025-01-06T01:00:00Z \
  --database-dir /srv/dukascopy_sqlite \
  --workers 1
```

完整任务：

```bash
python download_dukascopy_sqlite.py download \
  --start 2016-01-01 \
  --end 2026-01-01 \
  --database-dir /srv/dukascopy_sqlite \
  --workers 2 \
  --retries 5 \
  --timeout 30
```

建议在 `tmux` 或 systemd 中运行。中断后重复相同命令即可续传。只有显式传入以下参数时才
使用代理：

```bash
--proxy http://127.0.0.1:7890
```

如果确实希望读取 VPS 的环境代理变量，使用 `--use-env-proxy`。

## 逐品种 HTTPS 发布

脚本按品种顺序下载。一个品种完全结束后才会在 `/srv/dukascopy_sqlite/` 根目录出现
`EURUSD.sqlite`；下载中的 `.part/-wal/-shm` 只存在于 `.work/`。

不要公开 `.work/`。Nginx 示例：

```nginx
location /dukascopy/ {
    alias /srv/dukascopy_sqlite/;
    autoindex off;
    auth_basic "Dukascopy data";
    auth_basic_user_file /etc/nginx/dukascopy.htpasswd;
}

location ^~ /dukascopy/.work/ {
    deny all;
}
```

建议启用 Basic Auth、随机路径或源 IP 白名单，不要公开无保护的大文件链接。Nginx 默认支持
HTTP Range，因此本机可以断点续传：

```bash
curl -C - -u USER:PASSWORD -O \
  https://YOUR_VPS/dukascopy/EURUSD.sqlite
curl -C - -u USER:PASSWORD -O \
  https://YOUR_VPS/dukascopy/EURUSD.sqlite.sha256
curl -C - -u USER:PASSWORD -O \
  https://YOUR_VPS/dukascopy/EURUSD.sqlite.json
```

v1.1 默认下载宇宙的 14 个品种全部完成后，在 VPS 生成整体传输 manifest。
相较于最初的 12 品种版本，`USDNOK` 和 `USDSEK` 补齐了正式 FIX-W 所需的 NOK/SEK
美元腿数据：

```bash
python download_dukascopy_sqlite.py manifest \
  --database-dir /srv/dukascopy_sqlite
```

然后一并下载 `_sqlite_manifest.json`。

这 14 个品种是传输和可复用数据宇宙，不是一个等权交易组合。正式 FIX-W 组合只使用
AUD/CAD/CHF/EUR/GBP/JPY/NOK/NZD/SEK 九个冻结 G9 美元腿；其余交叉盘供慢周期
和其他预注册实验使用。

## 本机验证

```bash
python download_dukascopy_sqlite.py verify \
  --database-dir ./dukascopy_sqlite
```

该命令检查文件大小、整个数据库 SHA-256 和 SQLite `quick_check`。若要逐个解压并验证全部
payload：

```bash
python download_dukascopy_sqlite.py verify \
  --database-dir ./dukascopy_sqlite \
  --deep
```

项目内的正式 FIX-W runner 还会核对数据库 schema、metadata、parser/source 契约，
并在一次 runner 调用内为每个必需数据库建立可复用的 `DatabaseTransferVerification`
receipt。它会返回 `transfer_audit`，但不会自动把 receipt 另存为持久文件；调用方要
保存 runner 产物。随后的事件窄窗仍会逐小时复验压缩 payload SHA-256，所以整库验证
不会取代事件级完整性检查。

## 本机按需聚合

```bash
python download_dukascopy_sqlite.py aggregate \
  --database-dir ./dukascopy_sqlite \
  --output-dir ./data/dukascopy_bid_ask \
  --start 2016-01-01 \
  --end 2026-01-01 \
  --interval 4h
```

默认只要有一个应请求小时没有数据库状态就拒绝生成正式结果；`--allow-incomplete` 只用于
诊断，产出的 manifest 会记录失败小时且不能通过项目数据审计。v1.1 默认聚合结果为
14 个 CSV 和 `_data_manifest.json`；慢周期配置仍只读取其中原先冻结的 12 个货币对。
FIX-W 不用聚合 CSV 代替 tick，而是直接从 SQLite 提取其 9 个 G9 腿的事件边界窄窗。

## 容量

- 14 个 SQLite 合计预计约 30–60 GB，极端情况下可能更高；
- 每个数据库通常约 1–5 GB，随品种流动性不同；
- 聚合后的全部 4h CSV 通常约 50–200 MB；
- SQLite 内仍保存 Dukascopy 原始压缩 payload，不保存解压 tick，因此不会膨胀到逐 tick
  明细落盘的体量。
