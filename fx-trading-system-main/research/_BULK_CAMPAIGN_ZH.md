# 7h 批量扩充作战日志

开始（UTC）：见 `_BULK_WAVE_START.txt`  
约束：只写 `research/`；合法 OA（NBER/BIS/Fed/ECB/Cboe/官方 methodology/作者页/期刊 OA）；不盗版付费 PDF；不下行情大库。  
并发上限：10。深度标准不变（L3+ 笔记）。

## 波次

| Wave | 内容 | Agent 数 |
|---|---|---|
| A | 开放 PDF 批量下载 + manifest | 4 |
| B | 剩余因子笔记 + 综述/手册 | 2 |
| C | 等 Micro 完成后补洞 / 或并行 foundations/datasets 不撞车 | 2–3 |
| D | 主端收口 INDEX/GAPS/去重 | 1 主 |

## 下载根目录

```text
research/_pdfs/
  DOWNLOAD_MANIFEST.csv
  _nber/ _bis/ _fed/ _ssrn/ _official/ _validation/ _micro/ 02_factor/
research/_html_snapshots/
```

## 成功度量（7h 内尽量抬高）

- OA PDF 落盘数量与总字节
- 新 deep_noted 篇数
- CATALOG 从 planned → linked/deep_noted
- GAPS 更新准确性
