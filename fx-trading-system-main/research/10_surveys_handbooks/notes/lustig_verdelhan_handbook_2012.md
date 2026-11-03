# [Lustig & Verdelhan 系] Exchange Rates in an SDF Framework — 短卡 + PDF 警告

- 深度层级: L3（框架短卡）
- 引用链角色: survey map
- DOI/URL: *Handbook of Exchange Rates* 章路线；实证以 LRV 论文为准
- 开放获取: **警告** — `research/_pdfs/lustig_verdelhan_sdf_chapter.pdf` **不是** Lustig–Verdelhan handbook 章；打开首页为 **Burnside & Graveline NBER w18646**（见 `burnside_graveline_asset_market_view.md`）
- 本项目映射: SDF/欧拉语言；**实证复制**走 `02_factor_literature/notes/lustig_rfs_2011.md`
- 复制状态: extension_only（框架）；实证 fail_closed_missing_data（forward）
- 公式置信度: medium（手册正文未可靠 OA；恒等式为标准国际金融）

## 1. 经济机制

资产市场观点的**教科书表述**：完整市场下，实际/名义汇率变动与两国 SDF（IMRS）之差相连；利率由 SDF 的条件期望决定；UIP 失效对应风险溢价。Carry 按利率/forward discount 排序，被解释为对全球风险因子暴露的排序。

**必须并读：** Burnside–Graveline 对“汇率变动 = 风险补偿差”的**识别批判**（同目录笔记）。可交易 HML_FX 的存在是**组合事实**，不自动等于错误解读的 IMRS 差分交易信号。

## 2. 精确公式

```text
E_t[ M_{t+1} R^x_{t+1} ] = 0

# 完整市场对数示意（符号惯例依文而定）
# Δs ≈ m - m*   或相反；实现时锁死报价与 numeraire

# 实证对接
# DOL ≈ 平均对外币超额
# HML_FX = 高息组合 - 低息组合
```

## 3–6. 数据 / 成本 / 识别 / 清单

见 `../../02_factor_literature/notes/lustig_rfs_2011.md` 与 `burnside_graveline_asset_market_view.md`。  
后危机 CIP：用 \(i^*-i\) 替代 \(f-s\) 会破坏教科书替换（`06` + Du–Tepper–Verdelhan）。

## 7. 本项目映射

- 理论入口 only；不把 SDF 恒等式注册为因子。  
- 真 handbook 章 PDF 未可靠落盘前，禁止引用错误文件名。

## 8. 引用链

| 角色 | 文献 |
|---|---|
| 实证 | Lustig–Roussanov–Verdelhan RFS 2011 |
| 批判 | Burnside–Graveline w18646 |
| 消费风险前身 | Lustig–Verdelhan AER 2007 |
| 边界 | Du–Tepper–Verdelhan CIP |

## 9. 精读问题

1. 在 G9 上两因子（DOL/HML）是否仍充分？  
2. 阅读 handbook 章前，如何先用 Burnside–Graveline 一页纸避免识别捷径？  
3. 项目 registry 中 `slow_carry` 应绑定 \(f-s\) 还是账户 swap？
